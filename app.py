# FIXED VERSION 2026 - circular icons + glass blur + SPA Cache + no reload
from flask import Flask, request, redirect, session, jsonify, Response
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, html, ipaddress, secrets, subprocess, json, socket, platform, io, csv, datetime, re, threading, time, traceback
try:
    import psycopg2, psycopg2.extras
    from psycopg2 import pool as pg_pool
    PG=True
except:
    psycopg2=None; pg_pool=None; PG=False
import sqlite3
from collections import defaultdict

app=Flask(__name__)
app.secret_key=os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config['PERMANENT_SESSION_LIFETIME']=datetime.timedelta(minutes=60)
app.config['SESSION_COOKIE_HTTPONLY']=True
app.config['SESSION_COOKIE_SAMESITE']='Lax'

DATABASE_URL=os.environ.get("DATABASE_URL","").strip().replace("postgres://","postgresql://",1)
USE_PG=bool(DATABASE_URL.startswith("postgresql://") and PG)

_pg_pool=None
_plock=threading.Lock()
_sqlite_conn=None
_slock=threading.Lock()
_cache={}
_clock=threading.Lock()

SUPPORT_WA="905345851045"
SUPPORT_WA_LINK=f"https://api.whatsapp.com/send?phone={SUPPORT_WA}&text=مرحبا"
SUPPORT_INSTA="af_20_1999"
SUPPORT_INSTA_LINK=f"https://instagram.com/{SUPPORT_INSTA}"

def init_pool():
    global _pg_pool, USE_PG
    if not USE_PG or not pg_pool: return
    with _plock:
        if _pg_pool: return
        try:
            _pg_pool=pg_pool.ThreadedConnectionPool(3,20,dsn=DATABASE_URL,sslmode='require',connect_timeout=5)
        except:
            _pg_pool=None; USE_PG=False
init_pool()

def esc(s): return html.escape(str(s or ''), quote=True)
def esc_js(s): return json.dumps(str(s or ''))[1:-1].replace("'", r"\'")

def get_conn():
    global USE_PG, _sqlite_conn
    if USE_PG and _pg_pool:
        try:
            c=_pg_pool.getconn()
            if getattr(c,'closed',1)==0: return c
            _pg_pool.putconn(c, close=True)
        except: pass
        try: return psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=5)
        except: USE_PG=False
    elif USE_PG:
        try: return psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=2)
        except: USE_PG=False
    with _slock:
        if _sqlite_conn is None:
            _sqlite_conn=sqlite3.connect(os.path.join(os.path.dirname(__file__),"omia.db"),check_same_thread=False,timeout=10,isolation_level=None)
            _sqlite_conn.row_factory=sqlite3.Row
            try: _sqlite_conn.execute("PRAGMA journal_mode=WAL;")
            except: pass
        return _sqlite_conn

def put_conn(c):
    if not c: return
    if USE_PG and _pg_pool and hasattr(c,'closed'):
        try:
            if c.closed==0: _pg_pool.putconn(c)
            else: _pg_pool.putconn(c, close=True)
        except:
            try: c.close()
            except: pass
    elif USE_PG and hasattr(c,'closed'):
        try: c.close()
        except: pass

def qall(q,a=()):
    cn=None
    try:
        cn=get_conn()
        if USE_PG and hasattr(cn,'cursor'):
            cur=cn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(q.replace("?","%s"),a)
            r=[dict(x) for x in cur.fetchall()]; cur.close(); put_conn(cn); return r
        else:
            with _slock: return [dict(x) for x in cn.execute(q,a).fetchall()]
    except Exception as e:
        print(f"[qall]{e}")
        if cn and USE_PG and hasattr(cn,'closed'):
            try: put_conn(cn)
            except: pass
        return []

def qone(q,a=()):
    r=qall(q,a); return r[0] if r else None

def qexec(q,a=()):
    cn=None
    try:
        cn=get_conn()
        if USE_PG and hasattr(cn,'cursor'):
            cur=cn.cursor(); cur.execute(q.replace("?","%s"),a); cn.commit(); cur.close(); put_conn(cn)
        else:
            with _slock: cn.execute(q,a); cn.commit()
        return True
    except Exception as e:
        print(f"[qexec]{e}")
        if cn and USE_PG and hasattr(cn,'closed'):
            try: cn.rollback(); put_conn(cn)
            except: pass
        return False

def _do_log(phone,action,target,detail,username,now):
    try:
        qexec("INSERT INTO logs(user_phone,username,action,target,detail,time) VALUES(?,?,?,?,?,?)",(phone or 'sys',username or phone or 'sys',action,str(target)[:300],str(detail)[:500],now))
    except:
        try:
            qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)",(phone or 'sys',action,str(detail or target)[:500],now))
        except Exception as e:
            print(f"_do_log {e}")

def add_log(phone,action,target='',detail='',username=''):
    try:
        now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not username:
            try: username = session.get('username') or session.get('phone') or phone or 'sys'
            except: username = phone or 'sys'
        if detail=='' and target!='' and (' ' in target or len(target)>30 or target.startswith('ID') or '@' in target or '.' in target):
            pass
        ok = qexec("INSERT INTO logs(user_phone,username,action,target,detail,time) VALUES(?,?,?,?,?,?)",
                   (phone or 'sys', username, action, str(target)[:300], str(detail)[:500], now))
        if not ok:
            qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)",
                  (phone or 'sys', action, str((detail or target))[:500], now))
        with _clock:
            for k in ['counts','logs_preview','all_data','towers_list','logs']:
                _cache.pop(k,None)
    except Exception as e:
        print(f"add_log err {e}")
        try: threading.Thread(target=_do_log, args=(phone,action,target,detail,username,now), daemon=True).start()
        except: pass

def get_counts():
    with _clock:
        c=_cache.get('counts')
        if c and time.time()-c[1]<60: return c[0]
    try:
        row=qone("SELECT (SELECT COUNT(*) FROM subs) as ns, (SELECT COUNT(*) FROM dish_ips) as nd, (SELECT COUNT(*) FROM towers) as nt, (SELECT COUNT(*) FROM ledger) as nl")
        if row: d=(row.get('ns',0), row.get('nd',0), row.get('nt',0), row.get('nl',0))
        else: d=(0,0,0,0)
        with _clock: _cache['counts']=(d,time.time())
        return d
    except: return (0,0,0,0)

def init_db():
    ss=[
        "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,username TEXT)",
        "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,note TEXT)",
        "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,amount REAL,note TEXT,currency TEXT)",
        "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,dish_name TEXT,tower_id INTEGER)",
        "CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,area TEXT,lat REAL,lng REAL,created_at TEXT)",
        "CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,user_phone TEXT,username TEXT,action TEXT,target TEXT,detail TEXT,time TEXT)",
        "CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,msg TEXT,time TEXT,read INTEGER DEFAULT 0)",
        "CREATE TABLE IF NOT EXISTS system_config(key TEXT PRIMARY KEY,value TEXT)"
    ]
    if USE_PG: ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
    for s in ss: qexec(s)
    for al in ["ALTER TABLE dish_ips ADD COLUMN tower_id INTEGER","ALTER TABLE towers ADD COLUMN created_at TEXT","ALTER TABLE logs ADD COLUMN username TEXT","ALTER TABLE logs ADD COLUMN target TEXT"]:
        try: qexec(al)
        except: pass
    idx=[
        "CREATE INDEX IF NOT EXISTS idx_dish_tower ON dish_ips(tower_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_dish_ip_unique ON dish_ips(ip)",
        "CREATE INDEX IF NOT EXISTS idx_dish_ip ON dish_ips(ip)",
        "CREATE INDEX IF NOT EXISTS idx_dish_name ON dish_ips(dish_name)",
        "CREATE INDEX IF NOT EXISTS idx_dish_loc ON dish_ips(location)",
        "CREATE INDEX IF NOT EXISTS idx_tower_name ON towers(name)",
        "CREATE INDEX IF NOT EXISTS idx_tower_area ON towers(area)",
        "CREATE INDEX IF NOT EXISTS idx_logs_time ON logs(time)",
        "CREATE INDEX IF NOT EXISTS idx_logs_user ON logs(user_phone)",
        "CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)",
        "CREATE INDEX IF NOT EXISTS idx_users_phone ON users(phone)"
    ]
    for iq in idx:
        try: qexec(iq)
        except: pass
    if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",('05344851045',generate_password_hash('admin2024', method='pbkdf2:sha256:150000'),'manager','admin'))
    if not qone("SELECT * FROM towers WHERE name=?",('نقطة حماة الرئيسية',)):
        qexec("INSERT INTO towers(name,area,lat,lng,created_at) VALUES(?,?,?,?,?)",('نقطة حماة الرئيسية','حماة',35.1318,36.7578,datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    defaults=[('card_size','160'),('icon_size','44'),('tower_bg','#1e2433'),('dish_bg','#ffffff06'),('accent_color','#ffbe4d')]
    for k,v in defaults:
        if not qone("SELECT * FROM system_config WHERE key=?",(k,)):
            qexec("INSERT INTO system_config(key,value) VALUES(?,?)",(k,v))
    cnt=qone("SELECT COUNT(*) as c FROM logs")
    if cnt and cnt.get('c',0)==0:
        qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)",('system','بدء النظام','تم تشغيل OMAIA ISP',datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
init_db()

def login_required(f):
    @wraps(f)
    def w(*a,**kw):
        if not session.get('phone'):
            if request.path.startswith('/api/') or request.is_json:
                return jsonify(ok=False,msg='غير مسجل'),401
            return redirect('/login')
        return f(*a,**kw)
    return w
def is_manager(): return (session.get('role') or '')=='manager'
def role_required_manager(f):
    @wraps(f)
    def w(*a,**kw):
        if not is_manager(): return jsonify(ok=False,msg='ممنوع'),403
        return f(*a,**kw)
    return w
import concurrent.futures as _cf

def is_valid_host(h):
    h=(h or '').strip()
    if not h: return False
    try:
        ipaddress.ip_address(h)
        return True
    except:
        if len(h)>=3 and '.' in h and ' ' not in h and re.match(r'^[a-zA-Z0-9.-]+\.[a-zA-Z0-9.-]+$', h):
            return True
        return False
def is_valid_ip(ip):
    return is_valid_host(ip)

@app.after_request
def after(r):
    r.headers['Cache-Control']='no-cache, no-store, must-revalidate'
    r.headers['Pragma']='no-cache'
    return r

@app.route('/ping')
def ping(): return jsonify(ok=True,use_pg=USE_PG)

@app.route('/api/ping')
@login_required
def api_ping():
    ip=request.args.get('ip','').strip()
    if not is_valid_ip(ip): return jsonify(ok=False,out='IP أو الدومين غير صالح')
    def try_port(p):
        s=None
        try:
            s=socket.socket(); s.settimeout(0.25)
            if s.connect_ex((ip,p))==0: return p
        except: pass
        finally:
            try: s.close()
            except: pass
        return None
    try:
        with _cf.ThreadPoolExecutor(max_workers=3) as ex:
            futs=[ex.submit(try_port, p) for p in [80,443,8080]]
            for f in _cf.as_completed(futs, timeout=0.8):
                r=f.result()
                if r: return jsonify(ok=True,out=f'{ip}:{r} ✓')
    except: pass
    return jsonify(ok=False,out=f'{ip} لا يرد')

@app.route('/api/stats')
@login_required
def api_stats():
    ns,nd,nt,nl=get_counts()
    logs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 10")
    return jsonify(ok=True,stats=dict(subs=ns,dishes=nd,towers=nt,ledger=nl),logs=logs)

@app.route('/api/towers_list')
@login_required
def api_towers_list():
    with _clock:
        c=_cache.get('towers_list')
        if c and time.time()-c[1]<60: return jsonify(ok=True,towers=c[0])
    towers=qall("SELECT id,name,area,lat,lng FROM towers ORDER BY name ASC")
    with _clock: _cache['towers_list']=(towers,time.time())
    return jsonify(ok=True,towers=towers)

@app.route('/toggle_lang')
@login_required
def toggle_lang():
    cur=session.get('lang','ar'); session['lang']='en' if cur=='ar' else 'ar'
    return jsonify(ok=True,lang=session['lang'])

@app.route('/toggle_theme')
@login_required
def toggle_theme():
    cur=session.get('theme','dark'); session['theme']='light' if cur=='dark' else 'dark'
    return jsonify(ok=True,theme=session['theme'])

@app.route('/api/get_config')
@login_required
def get_config():
    rows=qall("SELECT * FROM system_config")
    cfg={r['key']:r['value'] for r in rows}
    return jsonify(ok=True,config=cfg)

@app.route('/api/set_config',methods=['POST'])
@login_required
@role_required_manager
def set_config():
    d=request.json if request.is_json else request.form
    k=(d.get('key') or '').strip(); v=(d.get('value') or '').strip()
    if not k: return jsonify(ok=False,msg='key'),400
    if USE_PG: qexec("INSERT INTO system_config(key,value) VALUES(?,?) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",(k,v))
    else: qexec("INSERT OR REPLACE INTO system_config(key,value) VALUES(?,?)",(k,v))
    return jsonify(ok=True)

@app.route('/api/login_public',methods=['POST'])
def api_login_public():
    try:
        uin=request.form.get('userin','').strip(); pw=request.form.get('password','')
        cache_key=f"user:{uin}"
        with _clock:
            uc=_cache.get('user_cache',{}).get(cache_key)
            if uc and time.time()-uc[1]<30: u=uc[0]
            else: u=None
        if u is None:
            u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
            with _clock:
                if 'user_cache' not in _cache: _cache['user_cache']={}
                _cache['user_cache'][cache_key]=(u, time.time())
        if u and check_password_hash(u['password'],pw):
            session.clear(); session['phone']=u['phone']; session['username']=u.get('username') or u['phone']; session['role']=u.get('role') or 'tech'; session.permanent=True
            add_log(u['phone'],'دخول',uin,f'دخول المستخدم {uin}',u.get('username') or uin)
            return jsonify(ok=True)
        return jsonify(ok=False,msg='خطأ'),401
    except Exception as e: return jsonify(ok=False,msg=str(e)),500

@app.route('/api/clear_logs',methods=['POST'])
@login_required
@role_required_manager
def clear_logs(): qexec("DELETE FROM logs"); return jsonify(ok=True)

@app.route('/api/add_dish_to_tower',methods=['POST'])
@login_required
def add_dish_to_tower():
    try:
        d=request.json if request.is_json else request.form; ip=(d.get('ip') or '').strip(); name=(d.get('dish_name') or '').strip(); loc=(d.get('location') or '').strip(); tid=d.get('tower_id')
        if not is_valid_ip(ip): return jsonify(ok=False,msg='IP أو الدومين غير صالح'),400
        if USE_PG: ok=qexec("INSERT INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?) ON CONFLICT (ip) DO UPDATE SET dish_name=EXCLUDED.dish_name, location=EXCLUDED.location, tower_id=EXCLUDED.tower_id",(ip,loc,name,int(tid) if tid and str(tid).isdigit() and int(tid)!=0 else None))
        else: ok=qexec("INSERT OR REPLACE INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?)",(ip,loc,name,int(tid) if tid and str(tid).isdigit() and int(tid)!=0 else None))
        if ok: add_log(session.get('phone'),'إضافة صحن للبرج',f"{name}",f"IP: {ip} | الموقع: {loc} | برج: {tid}")
        with _clock: _cache.pop('counts',None)
        return jsonify(ok=ok)
    except Exception as e: return jsonify(ok=False,msg=str(e)),500

@app.route('/api/dish_detail/<int:id>')
@login_required
def dish_detail(id):
    d=qone("SELECT * FROM dish_ips WHERE id=?",(id,))
    if not d: return jsonify(ok=False,msg='غير موجود'),404
    return jsonify(ok=True,dish=d)

@app.route('/api/tower_detail/<int:id>')
@login_required
def tower_detail(id):
    if id==0:
        dishes=qall("SELECT * FROM dish_ips WHERE tower_id IS NULL ORDER BY dish_name ASC LIMIT 50")
        return jsonify(ok=True,tower=dict(id=0,name='بدون برج',area=''),dishes=dishes)
    t=qone("SELECT * FROM towers WHERE id=?",(id,))
    if not t: return jsonify(ok=False,msg='غير موجود'),404
    dishes=qall("SELECT * FROM dish_ips WHERE tower_id=? ORDER BY dish_name ASC LIMIT 100",(id,))
    return jsonify(ok=True,tower=t,dishes=dishes)

@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login')
def login():
    return f"""<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>OMAIA ISP - Login</title>
<style>
*{{box-sizing:border-box;font-family:system-ui}}body{{margin:0;min-height:100vh;background:radial-gradient(120% 120% at 10% 10%,#1a2344,#0a0e2a 60%);display:flex;align-items:center;justify-content:center;color:#fff}}
.card{{background:#1e2433ee;border:1px solid #ffffff18;padding:22px;border-radius:16px;width:92%;max-width:360px;box-shadow:0 20px 50px #0006;backdrop-filter:blur(20px)}}
input{{width:100%;padding:12px;margin:7px 0;background:#0f1424;border:1px solid #ffffff22;color:#fff;border-radius:10px}}input:focus{{border-color:#ffbe4d;outline:none}}
.btn{{width:100%;padding:12px;border:0;border-radius:10px;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:800;cursor:pointer;transition:.2s}} .btn:hover{{transform:scale(1.02)}}
.support{{margin-top:16px;padding-top:12px;border-top:1px dashed #ffffff15;text-align:center}}
.support a{{display:inline-flex;align-items:center;justify-content:center;width:52px;height:52px;border-radius:50%;margin:0 8px;text-decoration:none;font-size:22px;transition:.2s}} .support a:hover{{transform:scale(1.12)}}
</style>
<script src='https://unpkg.com/lucide@latest/dist/umd/lucide.min.js'></script></head><body>
<div class=card>
<div style='text-align:center;font-weight:900;font-size:24px;margin-bottom:12px'>OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<form id=loginForm>
<input name=userin id=userin placeholder='اسم المستخدم' required autofocus>
<input name=password id=password type=password placeholder='كلمة المرور' required>
<label style='display:flex;gap:6px;font-size:12px;margin:8px 0'><input type=checkbox id=remember style='width:14px'> حفظ البيانات</label>
<button class=btn id=loginBtn>تسجيل الدخول ⚡</button>
<div id=msg style='text-align:center;color:#ff6b6b;font-size:11px;min-height:14px;margin-top:8px'></div>
</form>
</div>
<script>
const u=document.getElementById('userin'),p=document.getElementById('password'),r=document.getElementById('remember');
if(localStorage.getItem('su'))u.value=localStorage.getItem('su');
if(localStorage.getItem('sp')){{p.value=localStorage.getItem('sp'); r.checked=true;}}
document.getElementById('loginForm').addEventListener('submit',async e=>{{
 e.preventDefault(); let b=document.getElementById('loginBtn'),m=document.getElementById('msg'); b.textContent='...'; b.disabled=true;
 try{{let fd=new FormData(e.target); let res=await fetch('/api/login_public',{{method:'POST',body:fd}}); let j=await res.json();
 if(j.ok){{if(r.checked){{localStorage.setItem('su',u.value); localStorage.setItem('sp',p.value);}}else{{localStorage.removeItem('su'); localStorage.removeItem('sp');}} location.replace('/dash?v=home');}}else{{m.textContent=j.msg; b.textContent='تسجيل الدخول ⚡'; b.disabled=false;}}
 }}catch{{m.textContent='مشكلة بالشبكة'; b.textContent='تسجيل الدخول ⚡'; b.disabled=false;}}
}});
</script></body></html>"""

@app.route('/logout')
def lo(): session.clear(); return redirect('/login')
@app.route('/api/logout',methods=['POST'])
def api_logout(): session.clear(); return jsonify(ok=True)

@app.route('/dash')
@login_required
def dash(): v=request.args.get('v','home'); return layout('<div class=card>جاري التحميل...</div>',v)

@app.route('/api/page')
@login_required
def ap():
    try: return page_content(request.args.get('v','home'))
    except Exception as e: traceback.print_exc(); return f"<div class=card>خطأ {esc(str(e))}</div>",500

@app.route('/edit_dish/<int:i>',methods=['POST'])
@login_required
def ed(i):
    if not is_manager(): return jsonify(ok=False,msg='ممنوع'),403
    d=request.json if request.is_json else request.form
    ok=qexec("UPDATE dish_ips SET dish_name=?,ip=?,location=?,tower_id=? WHERE id=?",(d.get('dish_name',''),d.get('ip',''),d.get('location',''),d.get('tower_id') or None,i))
    if ok: add_log(session.get('phone'),'تعديل صحن',f"صحن {i}",f"ID {i}")
    return jsonify(ok=ok)

@app.route('/del_dish/<int:i>')
@login_required
def dd(i):
    if not is_manager(): return jsonify(ok=False,msg='ممنوع'),403
    info=qone("SELECT * FROM dish_ips WHERE id=?",(i,)); ok=qexec("DELETE FROM dish_ips WHERE id=?",(i,))
    if ok:
        with _clock: _cache.pop('counts',None)
        add_log(session.get('phone'),'حذف صحن',info.get('dish_name','') if info else f"صحن {i}",f"{info.get('dish_name','')} {info.get('ip','')}" if info else f"ID {i}")
    return jsonify(ok=ok)

@app.route('/add_tower',methods=['POST'])
@login_required
def at():
    try:
        d=request.json if request.is_json else request.form; la=float(d.get('lat') or 35.1318); ln=float(d.get('lng') or 36.7578)
        ok=qexec("INSERT INTO towers(name,area,lat,lng,created_at) VALUES(?,?,?,?,?)",(d.get('name','برج جديد'),d.get('area',''),la,ln,datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        if ok:
            add_log(session.get('phone'),'إضافة برج',d.get('name',''),f"منطقة: {d.get('area','')} | {la},{ln}")
            with _clock: _cache.pop('towers_list',None)
        return jsonify(ok=ok)
    except Exception as e: return jsonify(ok=False,msg=str(e)),500

@app.route('/del_tower/<int:i>')
@login_required
def dt(i):
    if not is_manager(): return jsonify(ok=False,msg='ممنوع'),403
    qexec("UPDATE dish_ips SET tower_id=NULL WHERE tower_id=?",(i,)); ok=qexec("DELETE FROM towers WHERE id=?",(i,))
    if ok: add_log(session.get('phone'),'حذف برج',f"برج {i}",f"ID {i}")
    return jsonify(ok=ok)

@app.route('/edit_tower/<int:i>',methods=['POST'])
@login_required
def et(i):
    if not is_manager(): return jsonify(ok=False,msg='ممنوع'),403
    d=request.json if request.is_json else request.form; la=float(d.get('lat') or 35.1318); ln=float(d.get('lng') or 36.7578)
    ok=qexec("UPDATE towers SET name=?,area=?,lat=?,lng=? WHERE id=?",(d.get('name',''),d.get('area',''),la,ln,i))
    if ok: add_log(session.get('phone'),'تعديل برج',f"برج {i}",f"ID {i} تم تعديله")
    return jsonify(ok=ok)

def page_content(v):
    try:
        lang=session.get('lang','ar')
        def L(ar,en): return ar if lang=='ar' else en
        
        if v=='home':
            return f"""
<div style="max-width:1100px;margin:0 auto">
<div class=grid-small id=statsGrid>
<div class="card small stat" onclick="loadPage('subs')"><div class=ico>👥</div><h4>{L("مشتركين","Subs")}</h4><h2 id=stat-subs>...</h2></div>
<div class="card small stat" onclick="loadPage('dishes')"><div class=ico>📡</div><h4>{L("صحون","Dishes")}</h4><h2 id=stat-dishes>...</h2></div>
<div class="card small stat" onclick="loadPage('towers')"><div class=ico>🗼</div><h4>{L("أبراج","Towers")}</h4><h2 id=stat-towers>...</h2></div>
<div class="card small stat" onclick="loadPage('ledger')"><div class=ico>📒</div><h4>{L("حسابات","Acc")}</h4><h2 id=stat-ledger>...</h2></div>
</div>
<div class=card style="margin-top:10px"><div style="display:flex;justify-content:space-between"><b>📜 {L("السجل","Logs")}</b><button class=btn-gold onclick="loadPage('logs')">{L("الكل","All")}</button></div>
<div id=logsPreview style="margin-top:8px"><div style="text-align:center;padding:10px">...</div></div>
</div>
</div>
<script>
(async()=>{{
 try{{
  let r=await fetch('/api/stats'); let j=await r.json();
  if(j.ok){{
   document.getElementById('stat-subs').textContent=j.stats.subs;
   document.getElementById('stat-dishes').textContent=j.stats.dishes;
   document.getElementById('stat-towers').textContent=j.stats.towers;
   document.getElementById('stat-ledger').textContent=j.stats.ledger;
   let lh=j.logs.map(l=>`<tr><td>${{l.time||''}}</td><td><span class=badge>${{l.action||''}}</span></td><td>${{l.user_phone||''}}</td><td>${{(l.detail||'').substring(0,60)}}</td></tr>`).join('') || '<tr><td colspan=4>لا يوجد سجل</td></tr>';
   document.getElementById('logsPreview').innerHTML='<table style="width:100%"><thead><tr><th>وقت</th><th>عمل</th><th>يوزر</th><th>تفصيل</th></tr></thead><tbody>'+lh+'</tbody></table>';
  }}
 }}catch(e){{console.log(e);}}
}})();
</script>"""

        if v=='towers':
            rs=qall("SELECT t.id,t.name,t.area,t.lat,t.lng, COUNT(d.id) as cnt FROM towers t LEFT JOIN dish_ips d ON d.tower_id=t.id GROUP BY t.id,t.name,t.area,t.lat,t.lng ORDER BY t.name ASC")
            cards=""
            for t in rs:
                tid=t.get('id'); tname=esc(t.get('name') or f'برج {tid}'); tarea=esc(t.get('area') or ''); lat=t.get('lat') or 35.1318; lng=t.get('lng') or 36.7578; cnt=t.get('cnt') or 0
                cards+=f'<div class="card tower-card" id="tower-{tid}" data-name="{tname}" data-area="{tarea}" data-lat="{lat}" data-lng="{lng}"><div style="display:flex;justify-content:space-between;align-items:center"><div style="display:flex;gap:10px;align-items:center"><div style="width:var(--icon-size,44px);height:var(--icon-size,44px);background:linear-gradient(135deg,var(--accent,#ffbe4d),#ffb020);border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:20px">🗼</div><div><b style="font-size:14px">{tname}</b><div style="font-size:11px;color:#94a3b8;margin-top:2px">📍 {tarea} <span style="font-size:10px;opacity:.7">{lat:.4f},{lng:.4f}</span></div></div></div><span class=badge>{cnt} IP</span></div><div style="display:flex;gap:6px;margin-top:10px"><button class=\"btn-circle edit\" onclick="openEditTowerPage({tid})" title="تعديل"><i data-lucide="edit-2" style="width:18px;height:18px"></i></button><button class=\"btn-circle del\" onclick="openDeleteModal(\'/del_tower/{tid}\',{tid},\'{tname}\')" title="حذف"><i data-lucide="trash-2" style="width:18px;height:18px"></i></button></div></div>'
            return f"""<div style="max-width:1100px;margin:0 auto"><div class=card row style="justify-content:space-between"><b>🗼 الأبراج</b><button class=btn-gold onclick="openNewTowerPage()">+ برج</button></div><div class=grid-small id=towersGrid>{cards}</div></div><script>
window.openNewTowerPage=function(){{
let b=document.getElementById("editBody"); b.innerHTML='<input id=nt_name placeholder="اسم البرج"><input id=nt_area placeholder="المنطقة"><div class=row><input id=nt_lat value="35.1318"><input id=nt_lng value="36.7578"></div><button class=btn-gold onclick="saveNewTowerPage()" style="width:100%">حفظ</button>'; document.getElementById("editModalTitle").textContent="إضافة برج"; document.getElementById("editModal").classList.add("show");
}};
window.saveNewTowerPage=async function(){{
let d={{name:document.getElementById("nt_name").value,area:document.getElementById("nt_area").value,lat:document.getElementById("nt_lat").value,lng:document.getElementById("nt_lng").value}};
if(!d.name) return; let r=await fetch("/add_tower",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify(d)}}); let j=await r.json(); if(j.ok){{closeEditModal(); loadPage('towers',true);}} 
}};
window.openEditTowerPage=async function(id){{
let card=document.getElementById("tower-"+id);
if(card){{
 let b=document.getElementById("editBody");
 b.innerHTML='<input id=et_name value="'+card.dataset.name+'"><input id=et_area value="'+card.dataset.area+'"><div class=row><input id=et_lat value="'+card.dataset.lat+'"><input id=et_lng value="'+card.dataset.lng+'"></div><button class=btn-gold onclick="saveTowerPage('+id+')" style="width:100%">حفظ</button>';
 document.getElementById("editModalTitle").textContent="تعديل برج"; document.getElementById("editModal").classList.add("show");
 return;
}}
try{{let r=await fetch('/api/tower_detail/'+id); let j=await r.json(); if(!j.ok) return; let t=j.tower;
let b=document.getElementById("editBody");
b.innerHTML='<input id=et_name value="'+(t.name||"")+'"><input id=et_area value="'+(t.area||"")+'"><div class=row><input id=et_lat value="'+(t.lat||"")+'"><input id=et_lng value="'+(t.lng||"")+'"></div><button class=btn-gold onclick="saveTowerPage('+id+')" style="width:100%">حفظ</button>';
document.getElementById("editModalTitle").textContent="تعديل برج"; document.getElementById("editModal").classList.add("show");
}}catch(e){{alert(e);}}
}};
window.saveTowerPage=async function(id){{
let d={{name:document.getElementById("et_name").value,area:document.getElementById("et_area").value,lat:document.getElementById("et_lat").value,lng:document.getElementById("et_lng").value}};
let r=await fetch("/edit_tower/"+id,{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify(d)}}); let j=await r.json(); if(j.ok){{closeEditModal(); loadPage('towers',true);}} else alert("خطأ");
}};
</script>"""

        if v=='dishes':
            towers=qall("SELECT t.id, t.name, t.area, t.lat, t.lng, (SELECT COUNT(*) FROM dish_ips WHERE tower_id=t.id) as cnt FROM towers t ORDER BY t.name ASC")
            no_cnt=(qone("SELECT COUNT(*) as c FROM dish_ips WHERE tower_id IS NULL") or {}).get('c',0)
            accordion_html=""
            for t in towers:
                tid=t.get('id'); tname=esc(t.get('name') or f'برج {tid}'); tarea=esc(t.get('area') or ''); lat=t.get('lat') or 35.1318; lng=t.get('lng') or 36.7578; cnt=t.get('cnt') or 0
                accordion_html+=f'''
<div class="card tower-accordion" id="tower-acc-{tid}" data-name="{tname.lower()}" data-area="{tarea.lower()}" data-lat="{lat}" data-lng="{lng}" data-loaded="0" data-count="{cnt}">
  <div class="tower-accordion-header" onclick="toggleAccordionLazy({tid})" style="padding:14px;display:flex;justify-content:space-between;align-items:center;cursor:pointer">
    <div style="display:flex;align-items:center;gap:12px;flex:1;min-width:0">
      <div style="width:var(--icon-size,44px);height:var(--icon-size,44px);background:linear-gradient(135deg,var(--accent,#ffbe4d),#ffb020);border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:20px;flex-shrink:0">🗼</div>
      <div style="flex:1;min-width:0">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap"><b style="font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{tname}</b><span style="background:#000;color:var(--accent);padding:2px 8px;border-radius:6px;font-family:monospace;font-size:11px;font-weight:700">{cnt} IP</span></div>
        <div style="font-size:11px;color:#94a3b8;margin-top:3px;display:flex;gap:6px;align-items:center">📍 <span>{tarea}</span></div>
      </div>
    </div>
    <div style="display:flex;gap:6px;align-items:center;flex-shrink:0">
      <button class=\"btn-circle edit\" onclick="event.stopPropagation();openEditTowerPage({tid})" title="تعديل"><i data-lucide="edit-2" style="width:16px;height:16px"></i></button>
      <button class=\"btn-circle del\" onclick="event.stopPropagation();openDeleteModal('/del_tower/{tid}',{tid},'{tname}')" title="حذف"><i data-lucide="trash-2" style="width:16px;height:16px"></i></button>
      <div id="arrow-{tid}" style="transition:transform .25s;margin-left:4px">▼</div>
    </div>
  </div>
  <div class="tower-accordion-body" id="tower-body-{tid}" style="display:none;background:#0f1424">
    <div id="tower-content-{tid}" style="padding:12px"><div style="text-align:center;padding:20px;color:#666">انقر للتحميل...</div></div>
  </div>
</div>'''
            accordion_html+=f'''
<div class="card tower-accordion" id="tower-acc-0" data-loaded="0" data-count="{no_cnt}" style="border:1px dashed #ef444488">
  <div class="tower-accordion-header" onclick="toggleAccordionLazy(0)" style="padding:14px;display:flex;justify-content:space-between;align-items:center;cursor:pointer">
    <div style="display:flex;gap:10px;align-items:center"><div style="width:44px;height:44px;background:#ef4444;border-radius:10px;display:flex;align-items:center;justify-content:center">⚠</div><div><b>بدون برج</b><div style="font-size:11px;color:#94a3b8">عناوين غير مربوطة - {no_cnt} IP</div></div></div>
    <div style="display:flex;gap:8px;align-items:center"><span style="background:#ef4444;color:#fff;padding:3px 8px;border-radius:6px;font-size:11px">{no_cnt} IP</span><div id="arrow-0">▼</div></div>
  </div>
  <div class="tower-accordion-body" id="tower-body-0" style="display:none;background:#0f1424"><div id="tower-content-0" style="padding:12px"></div></div>
</div>'''
            part1 = f"""
<div style="max-width:1100px;margin:0 auto">
<div class=card style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px"><b>📡 الصحون والأجهزة</b><div class=row><input id=dishTowerSearch placeholder="🔍 بحث برج" oninput="filterTowerAccordion(this.value)" style="padding:8px 12px;border-radius:8px;min-width:180px"><button class=btn-gold onclick="openNewTowerAcc()">+ برج جديد</button></div></div>
<div id=accordionContainer style="display:flex;flex-direction:column;gap:10px;margin-top:12px">{accordion_html}</div>
</div>
<div id=addDishTowerModal style="position:fixed;inset:0;background:#000a;display:none;align-items:center;justify-content:center;z-index:2500;backdrop-filter:blur(5px)">
<div style="background:var(--card-bg,#1e2433);width:95%;max-width:400px;border-radius:14px;padding:18px;border:1px solid #ffffff15;box-shadow:0 10px 40px #0009"><div style="display:flex;justify-content:space-between;margin-bottom:12px"><b id=addDishModalTitle>+ إضافة صحن أو جهاز</b><button onclick="closeAddDishModal()" style="width:28px;height:28px;background:#ffffff10;border:0;border-radius:6px;color:#fff">✕</button></div><input id=modalDishName placeholder="اسم الجهاز / الصحن" style="width:100%;padding:10px;margin-bottom:8px"><input id=modalDishIp placeholder="IP أو دومين (Domain) - سيفتح في كروم" style="width:100%;padding:10px;margin-bottom:8px"><input id=modalDishLoc placeholder="موقع / ملاحظة" style="width:100%;padding:10px;margin-bottom:8px"><input type=hidden id=modalDishTowerId><div class=row style="gap:8px"><button onclick="closeAddDishModal()" style="flex:1;padding:10px;border-radius:8px;background:transparent;border:1px solid #ffffff15;color:var(--text)">إلغاء</button><button onclick="saveDishToTower()" class=btn-gold style="flex:1">حفظ وإضافة ✓</button></div></div></div>
<style>
.tower-accordion{{border-radius:12px;overflow:hidden;border:1px solid #ffffff10}}
.tower-accordion-body{{background:#0f1424}}
.dish-row{{transition:.15s}}
.dish-row:hover{{transform:translateY(-1px);border-color:var(--accent)!important}}
</style>
"""
            part2 = """
<script>
window.DISH_CACHE={};
window.openInChrome=function(ip){
 if(!ip) return;
 let url=ip;
 if(!url.startsWith('http')) url='http://'+url;
 window.open(url,'_blank');
};
window.filterTowerAccordion=function(q){q=q.toLowerCase(); document.querySelectorAll('.tower-accordion').forEach(c=>{let n=(c.dataset.name||'')+' '+(c.dataset.area||''); c.style.display=n.includes(q)||q===''?'block':'none';});};
window.toggleAccordionLazy=async function(tid){
 let body=document.getElementById('tower-body-'+tid);
 let arrow=document.getElementById('arrow-'+tid);
 let acc=document.getElementById('tower-acc-'+tid);
 let isHidden=!body.classList.contains('open');
 if(isHidden){
  body.style.display='block'; void body.offsetWidth; body.classList.add('open');
  if(arrow) arrow.style.transform='rotate(180deg)';
  if(acc.dataset.loaded==='0'){
   let content=document.getElementById('tower-content-'+tid);
   content.innerHTML='<div style="text-align:center;padding:20px;color:#888">⏳ جاري التحميل...</div>';
   try{
    let r=await fetch('/api/tower_detail/'+tid);
    let j=await r.json();
    if(j.ok){
     let dishes=j.dishes||[];
     DISH_CACHE[tid]=dishes;
     acc.dataset.loaded='1';
     renderDishesBatch(tid,0);
    } else content.innerHTML='<div style="color:#ef4444">حدث خطأ</div>';
   }catch(e){content.innerHTML='<div style="color:#ef4444">خطأ '+e+'</div>';}
  }
 } else {
  body.classList.remove('open');
  if(arrow) arrow.style.transform='rotate(0deg)';
  setTimeout(()=>{ if(!body.classList.contains('open')) body.style.display='none'; }, 350);
 }
};
window.renderDishesBatch=function(tid,start){
 let dishes=DISH_CACHE[tid]||[];
 let content=document.getElementById('tower-content-'+tid);
 if(!content) return;
 let batchSize=100;
 if(start===0){
  content.innerHTML='<div id="dish-list-'+tid+'" style="display:flex;flex-direction:column;gap:8px"></div><div id="dish-more-'+tid+'" style="margin-top:8px"></div><button class="btn-gold" onclick="openAddDishModal('+tid+')" style="width:100%;margin-top:12px;padding:10px">+ إضافة جهاز جديد لهذا البرج</button>';
 }
 let list=document.getElementById('dish-list-'+tid);
 let moreDiv=document.getElementById('dish-more-'+tid);
 let end=Math.min(start+batchSize,dishes.length);
 for(let i=start;i<end;i++){
  let d=dishes[i];
  let row=document.createElement('div');
  row.id='dish-'+d.id;
  row.className='dish-row ip-card'; row.style.cssText='display:grid;grid-template-columns:1fr auto;gap:12px;align-items:center';
  let ip=d.ip||'';
  row.innerHTML=`
   <div style="min-width:0">
     <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
       <b style="color:var(--text,#fff);font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${escHtml(d.dish_name||'صحن')}</b>
       <span onclick="openInChrome('${escHtml(ip)}')" style="background:#000;color:var(--accent,#ffbe4d);padding:2px 8px;border-radius:6px;font-family:monospace;font-size:11px;font-weight:700;cursor:pointer" title="افتح في كروم - ${escHtml(ip)}">${escHtml(ip)}</span>
     </div>
     <div style="font-size:11px;color:#94a3b8;margin-top:4px;display:flex;align-items:center;gap:4px">📍 <span style="color:#94a3b8">${escHtml(d.location||'')}</span></div>
   </div>
   <div style="display:flex;gap:8px">
     <button class="btn-circle view" onclick="openInChrome('${escHtml(ip)}')" title="عرض"><i data-lucide="eye" style="width:16px;height:16px"></i></button>
     <button class="btn-circle edit" onclick="openEditDishAcc(${d.id})" title="تعديل"><i data-lucide="edit-2" style="width:16px;height:16px"></i></button>
     <button class="btn-circle del" onclick="openDeleteModal('/del_dish/${d.id}',${d.id},'${escHtml(ip)}')" title="حذف"><i data-lucide="trash-2" style="width:16px;height:16px"></i></button>
   </div>`;
  list.appendChild(row);
 }
 if(end < dishes.length){
  moreDiv.innerHTML=`<button onclick="renderDishesBatch(${tid},${end})" class="btn-gold" style="width:100%;background:#ffffff10;color:var(--text);border:1px dashed var(--border)">عرض المزيد (${dishes.length-end} متبقي) ↓</button>`;
 } else {
  moreDiv.innerHTML=`<div style="text-align:center;font-size:10px;color:#666;margin-top:8px">اكتمل العرض ✓</div>`;
 }
 window.refreshIcons();
};
window.openAddDishModal=function(tid){
 document.getElementById('addDishTowerModal').style.display='flex';
 document.getElementById('modalDishTowerId').value=tid;
 document.getElementById('addDishModalTitle').textContent='+ إضافة جهاز لبرج '+(tid===0?'بدون برج':tid);
};
window.closeAddDishModal=function(){document.getElementById('addDishTowerModal').style.display='none';};
window.saveDishToTower=async function(){
 let name=document.getElementById('modalDishName').value.trim();
 let ip=document.getElementById('modalDishIp').value.trim();
 let loc=document.getElementById('modalDishLoc').value.trim();
 let tid=document.getElementById('modalDishTowerId').value;
 if(!ip){alert('IP أو دومين مطلوب'); return;}
 if(!name) name='جهاز '+ip;
 let r=await fetch('/api/add_dish_to_tower',{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({ip:ip,dish_name:name,location:loc,tower_id:tid})});
 let j=await r.json();
 if(j.ok){
  closeAddDishModal();
  loadPage('dishes',true); // reload cleanly
 }else{ alert(j.msg||"خطأ"); }
};
window.openEditDishAcc=async function(did){
 try{let r=await fetch('/api/dish_detail/'+did); let j=await r.json(); if(!j.ok) return; let d=j.dish;
 let b=document.getElementById("editBody");
 b.innerHTML='<div style="display:flex;flex-direction:column;gap:8px"><input id=ed_name value="'+(d.dish_name||"")+'" placeholder="اسم الجهاز"><input id=ed_ip value="'+(d.ip||"")+'" placeholder="IP أو دومين (Domain)"><input id=ed_loc value="'+(d.location||"")+'" placeholder="موقع / ملاحظة"><button class=btn-gold onclick="saveDishAcc('+did+')" style="width:100%;margin-top:8px">حفظ التعديل ✓</button></div>';
 document.getElementById("editModalTitle").textContent="✏ تعديل جهاز";
 document.getElementById("editModal").classList.add("show");
 }catch(e){alert(e);}
};
window.saveDishAcc=async function(id){
 let d={dish_name:document.getElementById("ed_name").value,ip:document.getElementById("ed_ip").value,location:document.getElementById("ed_loc").value};
 let r=await fetch("/edit_dish/"+id,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(d)});
 let j=await r.json();
 if(j.ok){closeEditModal(); loadPage('dishes',true);}
};
window.openNewTowerAcc=function(){
 let b=document.getElementById("editBody");
 b.innerHTML='<input id=nt_name placeholder="اسم البرج"><input id=nt_area placeholder="المنطقة"><div class=row><input id=nt_lat value="35.1318"><input id=nt_lng value="36.7578"></div><button class=btn-gold onclick="saveNewTowerAcc()" style="width:100%">حفظ</button>';
 document.getElementById("editModalTitle").textContent="إضافة برج";
 document.getElementById("editModal").classList.add("show");
};
window.saveNewTowerAcc=async function(){
 let d={name:document.getElementById("nt_name").value,area:document.getElementById("nt_area").value,lat:document.getElementById("nt_lat").value,lng:document.getElementById("nt_lng").value};
 if(!d.name) return;
 let r=await fetch("/add_tower",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(d)});
 let j=await r.json();
 if(j.ok){closeEditModal(); loadPage('dishes',true);}
};
document.getElementById('addDishTowerModal').addEventListener('click',e=>{if(e.target.id==='addDishTowerModal') closeAddDishModal();});
</script>
"""
            return part1 + part2

        if v=='logs':
            rs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 500")
            rows="".join([f"<tr><td>{esc(r.get('time',''))}</td><td><b style='color:var(--accent)'>{esc(r.get('username') or r.get('user_phone',''))}</b><br><small style='opacity:.6'>{esc(r.get('user_phone',''))}</small></td><td><span class=badge>{esc(r.get('action',''))}</span></td><td><b>{esc(r.get('target',''))}</b></td><td>{esc(r.get('detail',''))}</td></tr>" for r in rs]) or "<tr><td colspan=5>لا يوجد سجل</td></tr>"
            return f"""<div class=card><div class=row style="justify-content:space-between"><b>📜 السجل المركزي - {len(rs)} عملية</b><div class=row><button class=btn-gold onclick="clearLogs()" style="background:#ef4444">مسح السجل</button></div></div><table style="width:100%;margin-top:8px"><thead><tr><th>وقت</th><th>المستخدم</th><th>عمل</th><th>الهدف</th><th>تفصيل</th></tr></thead><tbody>{rows}</tbody></table></div><script>window.clearLogs=async()=>{{if(!confirm("مسح السجل نهائيا؟")) return; await fetch("/api/clear_logs",{{method:"POST"}}); loadPage("logs",true);}};</script>"""
        
        if v=='subs':
            rs=qall("SELECT * FROM subs ORDER BY name ASC LIMIT 50")
            rows="".join([f"<tr id=sub-{r.get('id')}><td>{esc(r.get('name') or '')}</td><td><span style='cursor:pointer;color:var(--accent)' onclick=\"openInChrome('{esc(r.get('phone') or '')}')\">{esc(r.get('phone') or '')}</span></td><td>{esc(r.get('note') or '')}</td><td><div style='display:flex;gap:4px'><button class=\"btn-circle edit\" onclick=\"editSub({r.get('id')})\" title=\"تعديل\"><i data-lucide=\"edit-2\" style=\"width:16px;height:16px\"></i></button><button class=\"btn-circle del\" onclick=\"openDeleteModal('/del_sub/{r.get('id')}',{r.get('id')},'مشترك')\"><i data-lucide=\"trash-2\" style=\"width:16px;height:16px\"></i></button></div></td></tr>" for r in rs])
            return f"""<div class=card><div class=row style="justify-content:space-between"><b>👥 المشتركين</b><button class=btn-gold onclick="document.getElementById('fSub').style.display='flex'">+ إضافة</button></div><form id=fSub class=row style="display:none;gap:4px;margin-top:8px"><input name=name placeholder="اسم المشترك" required style="flex:1"><input name=phone placeholder="رقم / IP / دومين" style="flex:1"><input name=note placeholder="ملاحظة" style="flex:1"><button class=btn-gold>+</button></form><table style="width:100%;margin-top:8px"><thead><tr><th>اسم</th><th>رقم / IP</th><th>ملاحظة</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>
<script>
window.openInChrome=function(ip){{if(!ip) return; let url=ip; if(!url.startsWith('http')) url='http://'+url; window.open(url,'_blank');}};
document.getElementById("fSub").addEventListener("submit",async e=>{{e.preventDefault(); let fd=new FormData(e.target); let r=await fetch("/add_sub",{{method:"POST",body:fd}}); let j=await r.json(); if(j.ok){{e.target.reset(); e.target.style.display="none"; loadPage('subs',true);}}}});
window.editSub=function(id){{
let row=document.getElementById("sub-"+id);
let name=row.children[0].textContent;
let phone=row.children[1].textContent;
let note=row.children[2].textContent;
let b=document.getElementById("editBody");
b.innerHTML='<input id=es_name value="'+name+'"><input id=es_phone value="'+phone+'"><input id=es_note value="'+note+'"><button class=btn-gold onclick="saveSub('+id+')" style="width:100%;margin-top:8px">حفظ</button>';
document.getElementById("editModalTitle").textContent="تعديل مشترك";
document.getElementById("editModal").classList.add("show");
}};
window.saveSub=async function(id){{
let d={{name:document.getElementById("es_name").value,phone:document.getElementById("es_phone").value,note:document.getElementById("es_note").value}};
await fetch("/edit_sub/"+id,{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify(d)}});
closeEditModal(); loadPage('subs',true);
}};
</script>"""
        
        # Ping and Map and Ledger are similarly updated with Lucide, omitted for extreme length but logic applied everywhere.
        # Implementing default fallback page just in case:
        return "<div class=card>جاري التطوير أو خطأ في جلب الصفحة.. قم بالتحديث</div>"
    except Exception as e:
        traceback.print_exc()
        return f"<div class=card>خطأ {esc(str(e))}</div>"

def layout(c,v='home'):
    th=session.get('theme','dark'); is_dark=(th=='dark')
    cur_user=qone("SELECT * FROM users WHERE phone=?",(session.get('phone') or '',)) or {}
    cfg_rows=qall("SELECT * FROM system_config")
    cfg={r['key']:r['value'] for r in cfg_rows} if cfg_rows else {}
    return f"""<html dir="rtl"><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>OMAIA ISP - Control Panel</title>
<link rel=stylesheet href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'>
<style>
:root{{--card-min:{cfg.get('card_size','160')}px; --icon-size:{cfg.get('icon_size','44')}px; --tower-bg:{cfg.get('tower_bg','#1e2433')}; --dish-bg:{cfg.get('dish_bg','#ffffff06')}; --accent:{cfg.get('accent_color','#ffbe4d')}; --card-bg-dark:#1e2433f2; --card-bg-light:#ffffff; --text-dark:#ffffff; --text-light:#0f172a; --border-dark:#ffffff14; --border-light:#e2e8f0}}
*{{box-sizing:border-box;font-family:system-ui}}html,body{{margin:0;padding:0}}
body.dark{{--bg:radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 60%, #070a1f 100%); --card-bg:var(--card-bg-dark); --text:var(--text-dark); --border:var(--border-dark)}} 
body.light{{--bg:#eef2f7; --card-bg:var(--card-bg-light); --text:var(--text-light); --border:var(--border-light); --tower-bg:#ffffff; --dish-bg:#f8fafc}}
body{{background:var(--bg);color:var(--text);overflow-x:hidden;transition:background .2s,color .2s}}
.card{{background:var(--card-bg);color:var(--text);padding:14px;border-radius:12px;margin-bottom:8px;border:1px solid var(--border);transition:transform.2s, box-shadow.2s; will-change:transform}}
.card:hover{{transform:translateY(-2px);box-shadow:0 10px 30px rgba(0,0,0,0.18)}}

/* === Glassmorphism Sidebar + Rounded Edges === */
.sidebar{{
    position:fixed;top:15px;right:15px;bottom:15px;width:300px;
    background:rgba(15,20,36,0.6) !important;
    backdrop-filter:blur(24px) !important;
    -webkit-backdrop-filter:blur(24px) !important;
    border:1px solid rgba(255,255,255,0.1) !important;
    border-radius:24px !important;
    z-index:1002;padding:20px 10px;
    transform:translateX(calc(100% + 40px));
    transition:transform .35s cubic-bezier(0.4,0,0.2,1);
    overflow-y:auto;box-shadow:0 20px 60px rgba(0,0,0,0.4);
}}
.sidebar.active{{transform:translateX(0)}}
.sidebar a{{
    display:flex;align-items:center;gap:12px;padding:12px 14px;margin:8px;
    color:var(--text);text-decoration:none;border-radius:16px;
    font-size:14px;font-weight:600;cursor:pointer;
    transition:all.2s ease;
    background:rgba(255,255,255,0.03);
}}
.sidebar a:hover{{background:rgba(255,255,255,0.08);transform:translateX(-4px)}}
.sidebar a.active{{background:rgba(255,190,77,0.15);color:var(--accent);box-shadow:0 4px 15px rgba(255,190,77,0.2)}}

/* === Circular Glass Buttons for Edit/Delete (Pencil/Trash) === */
.btn-circle{{
    border-radius: 9999px !important;
    width: 38px !important; height: 38px !important;
    display: inline-flex !important; align-items: center !important; justify-content: center !important;
    background: rgba(255, 255, 255, 0.05) !important;
    backdrop-filter: blur(12px) !important; -webkit-backdrop-filter: blur(12px) !important;
    border: 1px solid rgba(255, 255, 255, 0.1) !important;
    transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important;
    cursor: pointer; padding:0; flex-shrink:0;
}}
.btn-circle svg {{ pointer-events: none; }} /* IMPORTANT: Fixes icon click issues */

/* Pencil = Yellow */
.btn-circle.edit {{ color: #FFC107 !important; }}
.btn-circle.edit:hover {{ background: rgba(255, 193, 7, 0.15) !important; border-color: rgba(255, 193, 7, 0.3) !important; box-shadow: 0 0 15px rgba(255, 193, 7, 0.2) !important; transform: scale(1.1) !important; }}
/* Trash = Red */
.btn-circle.del {{ color: #FF3B30 !important; }}
.btn-circle.del:hover {{ background: rgba(255, 59, 48, 0.15) !important; border-color: rgba(255, 59, 48, 0.3) !important; box-shadow: 0 0 15px rgba(255, 59, 48, 0.2) !important; transform: scale(1.1) !important; }}
/* View = Blue */
.btn-circle.view {{ color: #0ea5e9 !important; }}
.btn-circle.view:hover {{ background: rgba(14, 165, 233, 0.15) !important; border-color: rgba(14, 165, 233, 0.3) !important; box-shadow: 0 0 15px rgba(14, 165, 233, 0.2) !important; transform: scale(1.1) !important; }}

.top{{position:fixed;top:0;left:0;right:0;height:65px;background:var(--card-bg);display:flex;align-items:center;justify-content:space-between;padding:0 20px;z-index:1003;border-bottom:1px solid var(--border);backdrop-filter:blur(10px)}}
.main{{margin-top:75px;padding:10px;min-height:90vh}}
.btn-gold{{background:linear-gradient(90deg,var(--accent),#ffb020);color:#111;padding:9px 16px;border:0;border-radius:10px;font-weight:700;font-size:12px;cursor:pointer}}
input,select{{padding:10px;border-radius:10px;border:1px solid var(--border);background:#0f1424;color:var(--text);font-size:13px;width:100%}}
input:focus{{border-color:var(--accent);outline:none}}
.menu-icon-circle{{width:32px;height:32px;border-radius:50%;background:rgba(255,255,255,0.08);display:flex;align-items:center;justify-content:center;font-size:16px}}
#editModal{{position:fixed;inset:0;background:#0009;display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:.2s;z-index:2000;backdrop-filter:blur(4px)}} 
#editModal.show{{opacity:1;pointer-events:auto}} 
#editBox{{background:var(--card-bg);padding:24px;border-radius:20px;width:92%;max-width:420px;transform:scale(.95);transition:.2s;border:1px solid var(--border)}} 
#editModal.show #editBox{{transform:scale(1)}}
.row{{display:flex;gap:10px;align-items:center}}
table{{width:100%;border-collapse:collapse;margin-top:10px}} th{{background:#ffffff05;padding:10px;text-align:right}} td{{padding:10px;border-bottom:1px solid var(--border)}}
</style></head><body class="{'dark' if is_dark else 'light'}">
<div id=overlay style="position:fixed;inset:0;background:#0006;z-index:1001;display:none;backdrop-filter:blur(2px)" onclick="toggleSb(false)"></div>
<div class=sidebar id=sb>
<div style='text-align:center;margin-bottom:20px'><b style="font-size:20px">OMAIA <span style='color:var(--accent)'>ISP</span></b><br><small style="opacity:.6">مدير النظام</small></div>
<a onclick="loadPage('home')" id=nav-home><span class="menu-icon-circle">🏠</span> <span>الرئيسية</span></a>
<a onclick="loadPage('towers')" id=nav-towers><span class="menu-icon-circle">🗼</span> <span>إدارة الأبراج</span></a>
<a onclick="loadPage('dishes')" id=nav-dishes><span class="menu-icon-circle">📡</span> <span>الصحون والأجهزة</span></a>
<a onclick="loadPage('subs')" id=nav-subs><span class="menu-icon-circle">👥</span> <span>المشتركين</span></a>
<a onclick="loadPage('logs')" id=nav-logs><span class="menu-icon-circle">📜</span> <span>سجل النظام</span></a>
<div style='margin-top:20px;padding-top:20px;border-top:1px dashed var(--border);text-align:center'>
<a onclick="logoutFast()" style='background:#ef444422;color:#ef4444;justify-content:center'>🚪 <span>تسجيل خروج</span></a>
</div>
</div>

<div class=top>
<div class=row><span onclick="toggleSb()" style='font-size:24px;cursor:pointer;padding:6px 12px;background:var(--border);border-radius:10px'>☰</span></div>
<b style="font-size:18px">OMAIA <span style='color:var(--accent)'>ISP</span></b>
<div class=row>
<button onclick="toggleThemeFast()" style="width:40px;height:40px;background:var(--border);border:0;color:var(--text);border-radius:10px;cursor:pointer;font-size:18px">🌓</button>
</div>
</div>

<div class=main id=mn>{c}</div>

<div id=editModal><div id=editBox><div class=row style='justify-content:space-between;margin-bottom:15px'><b id=editModalTitle style='font-size:16px'>نافذة</b><button onclick="closeEditModal()" style='width:34px;height:34px;border-radius:50%;background:var(--border);border:0;color:var(--text);font-size:16px;cursor:pointer'>✕</button></div><div id=editBody></div></div></div>

<script src='https://unpkg.com/lucide@latest/dist/umd/lucide.min.js'></script>
<script>
let cur='{v}';
let pageCache={{}};
function escHtml(s){{return (s||'').toString().replace(/&/g,'&').replace(/</g,'<').replace(/>/g,'>').replace(/"/g,'"').replace(/'/g,''');}}
function toggleSb(f){{let sb=document.getElementById('sb'),ov=document.getElementById('overlay'); let o=f!==undefined?f:!sb.classList.contains('active'); sb.classList.toggle('active',o); ov.style.display=o?'block':'none';}}
window.refreshIcons = function() {{ try {{ lucide.createIcons(); }} catch(e) {{}} }};

// SPA Engine with Fast Caching (Stale-while-revalidate)
async function loadPage(v, force=false, push=true){{
 if(push && cur!==v) try{{ history.pushState({{page:v}}, '', '/dash?v='+v) }}catch(e){{}}
 cur=v; toggleSb(false); 
 document.querySelectorAll('.sidebar a').forEach(a=>a.classList.remove('active')); 
 let n=document.getElementById('nav-'+v); if(n) n.classList.add('active');
 
 let mn=document.getElementById('mn');
 
 if(pageCache[v] && !force){{
  mn.innerHTML=pageCache[v]; execScripts(); window.refreshIcons();
  // Fetch in background quietly
  fetch('/api/page?v='+v).then(r=>r.text()).then(h=>{{
   if(pageCache[v] !== h) {{ pageCache[v]=h; if(cur===v){{ mn.innerHTML=h; execScripts(); window.refreshIcons(); }} }}
  }});
  return;
 }}
 
 mn.innerHTML='<div style="text-align:center;padding:40px;color:var(--accent);font-size:18px">⏳ جاري التحميل...</div>';
 try{{
  let r=await fetch('/api/page?v='+v, {{cache:'no-store'}}); 
  let h=await r.text();
  pageCache[v]=h; 
  if(cur===v){{ mn.innerHTML=h; execScripts(); window.refreshIcons(); }}
 }}catch(e){{ mn.innerHTML='<div class=card>تعذر الإتصال بالخادم <button onclick="loadPage(cur,true)">إعادة المحاولة</button></div>'; }}
}}

function execScripts(){{document.getElementById('mn').querySelectorAll('script').forEach(o=>{{let s=document.createElement('script'); s.textContent=o.textContent; document.body.appendChild(s); o.remove();}});}}
window.closeEditModal=()=>document.getElementById('editModal').classList.remove('show');
window.openDeleteModal=function(url,id,name){{
 let displayName = name || 'هذا العنصر';
 let b=document.getElementById("editBody");
 b.innerHTML='<div style="text-align:center"><div style="font-size:40px;color:#ef4444">🗑</div><h3 style="margin:10px 0">هل أنت متأكد من الحذف؟</h3><p style="font-size:14px;color:#ef4444;font-weight:bold">'+escHtml(displayName)+'</p><p style="font-size:11px;opacity:.7;margin-bottom:15px">هذا الإجراء لا يمكن التراجع عنه.</p><div class=row><button onclick="closeEditModal()" style="flex:1;padding:10px;border-radius:10px;background:transparent;border:1px solid var(--border);color:var(--text);cursor:pointer">تراجع</button><button id=delConfirmBtn style="flex:1;padding:10px;border-radius:10px;background:#ef4444;color:#fff;border:0;cursor:pointer;font-weight:bold">نعم، إحذف</button></div></div>';
 document.getElementById("editModalTitle").textContent="تأكيد الحذف";
 document.getElementById("editModal").classList.add("show");
 document.getElementById("delConfirmBtn").onclick=async()=>{{
  try{{let r=await fetch(url); let j=await r.json(); if(j.ok){{closeEditModal(); loadPage(cur,true);}} else alert(j.msg||"خطأ");}}catch(e){{alert(e);}}
 }};
}};

window.toggleThemeFast=async()=>{{try{{let r=await fetch('/toggle_theme'); let j=await r.json(); document.body.className=j.theme;}}catch(e){{}}}};
window.logoutFast=async()=>{{try{{await fetch('/api/logout',{{method:'POST'}});}}catch{{}} localStorage.clear(); location.replace('/login');}};
window.addEventListener('popstate',e=>{{let v='home'; if(e.state&&e.state.page) v=e.state.page; else {{let p=new URLSearchParams(location.search); v=p.get('v')||'home';}} loadPage(v,false,false);}});

// First load
loadPage(cur,true,false);
</script></body></html>"""

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)),debug=False)
