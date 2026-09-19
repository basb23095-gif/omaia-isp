from flask import Flask, request, redirect, session, jsonify, Response
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, html, ipaddress, subprocess, json, socket, platform, io, csv, datetime, re, threading, time, traceback
try:
    import psycopg2, psycopg2.extras
    from psycopg2 import pool as pg_pool
    PG=True
except:
    psycopg2=None; pg_pool=None; PG=False
import sqlite3
from collections import defaultdict

app=Flask(__name__)
app.secret_key=os.environ.get("SECRET_KEY","omia-v17-final")
app.config['PERMANENT_SESSION_LIFETIME']=datetime.timedelta(minutes=60)

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
            _pg_pool=pg_pool.ThreadedConnectionPool(2,10,dsn=DATABASE_URL,sslmode='require',connect_timeout=2)
        except:
            _pg_pool=None; USE_PG=False
init_pool()

def esc(s): return html.escape(str(s or ''), quote=True)

def get_conn():
    global USE_PG, _sqlite_conn
    if USE_PG and _pg_pool:
        try:
            c=_pg_pool.getconn()
            if getattr(c,'closed',1)==0: return c
        except:
            try: return psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=2)
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
    if USE_PG and _pg_pool and c and hasattr(c,'closed'):
        try: _pg_pool.putconn(c)
        except:
            try: c.close()
            except: pass
    elif USE_PG and c and hasattr(c,'closed'):
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

def add_log(phone,action,detail):
    try:
        now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)",(phone or 'sys',action,detail,now))
        with _clock: _cache.pop('counts',None)
    except Exception as e:
        print(f"log err {e}")

def get_counts():
    with _clock:
        c=_cache.get('counts')
        if c and time.time()-c[1]<5: return c[0]
    try:
        ns=(qone("SELECT COUNT(*) as c FROM subs") or {}).get('c',0)
        nd=(qone("SELECT COUNT(*) as c FROM dish_ips") or {}).get('c',0)
        nt=(qone("SELECT COUNT(*) as c FROM towers") or {}).get('c',0)
        nl=(qone("SELECT COUNT(*) as c FROM ledger") or {}).get('c',0)
        d=(ns,nd,nt,nl)
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
        "CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,user_phone TEXT,action TEXT,detail TEXT,time TEXT)",
        "CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,msg TEXT,time TEXT,read INTEGER DEFAULT 0)",
        "CREATE TABLE IF NOT EXISTS system_config(key TEXT PRIMARY KEY,value TEXT)"
    ]
    if USE_PG: ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
    for s in ss: qexec(s)
    for al in ["ALTER TABLE dish_ips ADD COLUMN tower_id INTEGER","ALTER TABLE towers ADD COLUMN created_at TEXT"]:
        try: qexec(al)
        except: pass
    idx=[
        "CREATE INDEX IF NOT EXISTS idx_dish_tower ON dish_ips(tower_id)",
        "CREATE INDEX IF NOT EXISTS idx_dish_ip ON dish_ips(ip)",
        "CREATE INDEX IF NOT EXISTS idx_dish_name ON dish_ips(dish_name)",
        "CREATE INDEX IF NOT EXISTS idx_dish_loc ON dish_ips(location)",
        "CREATE INDEX IF NOT EXISTS idx_tower_name ON towers(name)",
        "CREATE INDEX IF NOT EXISTS idx_tower_area ON towers(area)",
        "CREATE INDEX IF NOT EXISTS idx_logs_time ON logs(time)",
        "CREATE INDEX IF NOT EXISTS idx_logs_user ON logs(user_phone)"
    ]
    for iq in idx:
        try: qexec(iq)
        except: pass
    if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",('05344851045',generate_password_hash('admin2024'),'manager','admin'))
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
        if not session.get('phone'): return redirect('/login')
        return f(*a,**kw)
    return w
def is_manager(): return (session.get('role') or '')=='manager'
def role_required_manager(f):
    @wraps(f)
    def w(*a,**kw):
        if not is_manager(): return jsonify(ok=False,msg='ممنوع'),403
        return f(*a,**kw)
    return w
def is_valid_ip(ip):
    ip=(ip or '').strip()
    if not ip: return False
    try: ipaddress.ip_address(ip); return True
    except: return len(ip)>=7 and '.' in ip

@app.after_request
def after(r): r.headers['Cache-Control']='no-cache'; return r

@app.route('/ping')
def ping(): return jsonify(ok=True,use_pg=USE_PG)

@app.route('/api/ping')
@login_required
def api_ping():
    ip=request.args.get('ip','').strip()
    if not is_valid_ip(ip): return jsonify(ok=False,out='IP غير صالح')
    for port in [80,443,8080,8291,22,8728]:
        s=None
        try:
            s=socket.socket(); s.settimeout(0.3)
            if s.connect_ex((ip,port))==0:
                s.close()
                add_log(session.get('phone'),'Ping',f'{ip}:{port} مفتوح')
                return jsonify(ok=True,out=f'{ip}:{port} ✓')
            s.close()
        except:
            try: s.close()
            except: pass
    try:
        cmd=['ping','-c','1','-W','1',ip] if platform.system().lower()!='windows' else ['ping','-n','1','-w','800',ip]
        out=subprocess.check_output(cmd,timeout=1,stderr=subprocess.STDOUT).decode(errors='ignore')
        if 'ttl=' in out.lower():
            m=re.search(r'time[=<]\s*(\d+\.?\d*)',out,re.I); ms=m.group(1) if m else ''
            add_log(session.get('phone'),'Ping',f'{ip} {ms}ms')
            return jsonify(ok=True,out=f'{ip} {ms}ms ✓')
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
    towers=qall("SELECT id,name,area,lat,lng FROM towers ORDER BY name ASC")
    return jsonify(ok=True,towers=towers)

@app.route('/toggle_lang')
@login_required
def toggle_lang():
    cur=session.get('lang','ar'); session['lang']='en' if cur=='ar' else 'ar'
    add_log(session.get('phone'),'تغيير لغة',session['lang'])
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
    if USE_PG:
        qexec("INSERT INTO system_config(key,value) VALUES(?,?) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",(k,v))
    else:
        qexec("INSERT OR REPLACE INTO system_config(key,value) VALUES(?,?)",(k,v))
    return jsonify(ok=True)

@app.route('/api/login_public',methods=['POST'])
def api_login_public():
    try:
        uin=request.form.get('userin','').strip(); pw=request.form.get('password','')
        u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
        if u and check_password_hash(u['password'],pw):
            session.clear(); session['phone']=u['phone']; session['username']=u.get('username') or u['phone']; session['role']=u.get('role') or 'tech'; session.permanent=True
            add_log(u['phone'],'دخول',uin)
            return jsonify(ok=True)
        return jsonify(ok=False,msg='خطأ'),401
    except Exception as e: return jsonify(ok=False,msg=str(e)),500

@app.route('/api/export/<tbl>')
@login_required
def api_export(tbl):
    add_log(session.get('phone'),'تصدير',tbl)
    output=io.StringIO(); output.write('\ufeff'); w=csv.writer(output)
    if tbl=='dishes':
        rows=qall("SELECT * FROM dish_ips ORDER BY location ASC, dish_name ASC"); w.writerow(['ID','اسم','IP','موقع','tower_id'])
        for r in rows: w.writerow([r.get('id',''),r.get('dish_name',''),r.get('ip',''),r.get('location',''),r.get('tower_id','')]); fname='dishes.csv'
    elif tbl=='towers':
        rows=qall("SELECT * FROM towers ORDER BY name ASC"); w.writerow(['ID','اسم','منطقة','lat','lng'])
        for r in rows: w.writerow([r.get('id',''),r.get('name',''),r.get('area',''),r.get('lat',''),r.get('lng','')]); fname='towers.csv'
    else:
        rows=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 2000"); w.writerow(['ID','يوزر','عمل','تفصيل','وقت'])
        for r in rows: w.writerow([r.get('id',''),r.get('user_phone',''),r.get('action',''),r.get('detail',''),r.get('time','')]); fname='logs.csv'
    return Response(output.getvalue(),mimetype='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename={fname}'})

@app.route('/api/clear_logs',methods=['POST'])
@login_required
@role_required_manager
def clear_logs(): qexec("DELETE FROM logs"); return jsonify(ok=True)

@app.route('/api/update_tower_pos',methods=['POST'])
@login_required
def update_tower_pos():
    try:
        d=request.json if request.is_json else request.form; tid=int(d.get('id')); lat=float(d.get('lat')); lng=float(d.get('lng'))
        qexec("UPDATE towers SET lat=?,lng=? WHERE id=?",(lat,lng,tid))
        add_log(session.get('phone'),'تعديل موقع برج',f"ID {tid}")
        return jsonify(ok=True)
    except Exception as e: return jsonify(ok=False,msg=str(e)),400

@app.route('/api/add_dish_to_tower',methods=['POST'])
@login_required
def add_dish_to_tower():
    try:
        d=request.json if request.is_json else request.form; ip=(d.get('ip') or '').strip(); name=(d.get('dish_name') or '').strip(); loc=(d.get('location') or '').strip(); tid=d.get('tower_id')
        if not is_valid_ip(ip): return jsonify(ok=False,msg='IP غير صالح'),400
        if USE_PG: ok=qexec("INSERT INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?) ON CONFLICT (ip) DO UPDATE SET dish_name=EXCLUDED.dish_name, location=EXCLUDED.location, tower_id=EXCLUDED.tower_id",(ip,loc,name,int(tid) if tid and str(tid).isdigit() and int(tid)!=0 else None))
        else: ok=qexec("INSERT OR REPLACE INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?)",(ip,loc,name,int(tid) if tid and str(tid).isdigit() and int(tid)!=0 else None))
        if ok: add_log(session.get('phone'),'إضافة صحن للبرج',f"{name} {ip}")
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
        dishes=qall("SELECT * FROM dish_ips WHERE tower_id IS NULL ORDER BY dish_name ASC")
        return jsonify(ok=True,tower=dict(id=0,name='بدون برج',area=''),dishes=dishes)
    t=qone("SELECT * FROM towers WHERE id=?",(id,))
    if not t: return jsonify(ok=False,msg='غير موجود'),404
    dishes=qall("SELECT * FROM dish_ips WHERE tower_id=? ORDER BY dish_name ASC",(id,))
    return jsonify(ok=True,tower=t,dishes=dishes)

@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login')
def login():
    return f"""<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>OMAIA ISP</title>
<style>
*{{box-sizing:border-box;font-family:system-ui}}body{{margin:0;min-height:100vh;background:radial-gradient(120% 120% at 10% 10%,#1a2344,#0a0e2a 60%);display:flex;align-items:center;justify-content:center;color:#fff}}
.card{{background:#1e2433ee;border:1px solid #ffffff18;padding:22px;border-radius:16px;width:92%;max-width:360px;box-shadow:0 20px 50px #0006}}
input{{width:100%;padding:12px;margin:7px 0;background:#0f1424;border:1px solid #ffffff22;color:#fff;border-radius:10px}}input:focus{{border-color:#ffbe4d;outline:none}}
.btn{{width:100%;padding:12px;border:0;border-radius:10px;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:800;cursor:pointer}} .btn:hover{{transform:scale(1.02)}}
.support{{margin-top:16px;padding-top:12px;border-top:1px dashed #ffffff15;text-align:center}}
.support a{{display:inline-flex;align-items:center;justify-content:center;width:52px;height:52px;border-radius:50%;margin:0 8px;text-decoration:none;font-size:22px;transition:.2s}} .support a:hover{{transform:scale(1.12)}}
</style></head><body>
<div class=card>
<div style='text-align:center;font-weight:900;font-size:24px;margin-bottom:12px'>OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<form id=loginForm>
<input name=userin id=userin placeholder='user' required autofocus>
<input name=password id=password type=password placeholder='password' required>
<label style='display:flex;gap:6px;font-size:12px;margin:8px 0'><input type=checkbox id=remember style='width:14px'> حفظ البيانات</label>
<button class=btn id=loginBtn>دخول ⚡</button>
<div id=msg style='text-align:center;color:#ff6b6b;font-size:11px;min-height:14px;margin-top:8px'></div>
</form>
<div class=support>
<div style='font-size:11px;color:#94a3b8;margin-bottom:10px'>الدعم الفني</div>
<a href="{SUPPORT_WA_LINK}" target="_blank" style="background:#25D366;color:#fff">💬</a>
<a href="{SUPPORT_INSTA_LINK}" target="_blank" style="background:linear-gradient(45deg,#feda75,#d62976);color:#fff">📷</a>
<div style='font-size:10px;color:#64748b;margin-top:10px'>واتساب: +{SUPPORT_WA}<br>انستغرام: {SUPPORT_INSTA}</div>
</div>
</div>
<script>
const u=document.getElementById('userin'),p=document.getElementById('password'),r=document.getElementById('remember');
if(localStorage.getItem('su'))u.value=localStorage.getItem('su');
if(localStorage.getItem('sp')){{p.value=localStorage.getItem('sp'); r.checked=true;}}
document.getElementById('loginForm').addEventListener('submit',async e=>{{
 e.preventDefault(); let b=document.getElementById('loginBtn'),m=document.getElementById('msg'); b.textContent='...'; b.disabled=true;
 try{{let fd=new FormData(e.target); let res=await fetch('/api/login_public',{{method:'POST',body:fd}}); let j=await res.json();
 if(j.ok){{if(r.checked){{localStorage.setItem('su',u.value); localStorage.setItem('sp',p.value);}}else{{localStorage.removeItem('su'); localStorage.removeItem('sp');}} location.replace('/dash?v=home');}}else{{m.textContent=j.msg; b.textContent='دخول ⚡'; b.disabled=false;}}
 }}catch{{m.textContent='شبكة'; b.textContent='دخول ⚡'; b.disabled=false;}}
}});
</script></body></html>"""

@app.route('/logout')
def lo(): session.clear(); return redirect('/login')
@app.route('/api/logout',methods=['POST'])
def api_logout(): session.clear(); return jsonify(ok=True)

@app.route('/dash')
@login_required
def dash(): v=request.args.get('v','home'); return layout('<div class=card>...</div>',v)

@app.route('/api/page')
@login_required
def ap():
    try: return page_content(request.args.get('v','home'))
    except Exception as e: traceback.print_exc(); return f"<div class=card>خطأ {esc(str(e))}</div>",500

@app.route('/api/search')
@login_required
def s():
    q=request.args.get('q','').strip()
    if not q: return jsonify([])
    like="%"+q+"%"; op="ILIKE" if USE_PG else "LIKE"; res=[]
    try:
        for r in qall(f"SELECT * FROM dish_ips WHERE ip {op} ? OR dish_name {op} ? OR location {op} ? LIMIT 15",(like,like,like)):
            res.append({"title":r.get('dish_name') or r['ip'],"sub":r['ip']+" - "+(r.get('location') or ''),"page":"dishes"})
        for r in qall(f"SELECT * FROM towers WHERE name {op} ? OR area {op} ? LIMIT 10",(like,like)):
            res.append({"title":r['name'],"sub":r.get('area','')+" | "+str(r.get('lat') or '')+","+str(r.get('lng') or ''),"page":"towers"})
    except: pass
    return jsonify(res)

@app.route('/add_dish',methods=['POST'])
@login_required
def ad():
    try:
        d=request.json if request.is_json else request.form; ip=(d.get('ip') or '').strip(); name=(d.get('dish_name') or '').strip(); loc=(d.get('location') or '').strip(); tid=d.get('tower_id')
        if not is_valid_ip(ip): return jsonify(ok=False,msg='IP غير صالح'),400
        if USE_PG: ok=qexec("INSERT INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?) ON CONFLICT (ip) DO UPDATE SET dish_name=EXCLUDED.dish_name, location=EXCLUDED.location, tower_id=EXCLUDED.tower_id",(ip,loc,name,int(tid) if tid and str(tid).isdigit() and int(tid)!=0 else None))
        else: ok=qexec("INSERT OR REPLACE INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?)",(ip,loc,name,int(tid) if tid and str(tid).isdigit() and int(tid)!=0 else None))
        if ok: add_log(session.get('phone'),'إضافة صحن',f"{name} {ip}")
        with _clock: _cache.pop('counts',None)
        return jsonify(ok=ok)
    except Exception as e: return jsonify(ok=False,msg=str(e)),500

@app.route('/edit_dish/<int:i>',methods=['POST'])
@login_required
def ed(i):
    if not is_manager(): return jsonify(ok=False,msg='ممنوع'),403
    d=request.json if request.is_json else request.form
    ok=qexec("UPDATE dish_ips SET dish_name=?,ip=?,location=?,tower_id=? WHERE id=?",(d.get('dish_name',''),d.get('ip',''),d.get('location',''),d.get('tower_id') or None,i))
    if ok: add_log(session.get('phone'),'تعديل صحن',f"ID {i}")
    return jsonify(ok=ok)

@app.route('/del_dish/<int:i>')
@login_required
def dd(i):
    if not is_manager(): return jsonify(ok=False,msg='ممنوع'),403
    info=qone("SELECT * FROM dish_ips WHERE id=?",(i,)); ok=qexec("DELETE FROM dish_ips WHERE id=?",(i,))
    if ok:
        with _clock: _cache.pop('counts',None)
        add_log(session.get('phone'),'حذف صحن',f"{info.get('dish_name','')} {info.get('ip','')}" if info else f"ID {i}")
    return jsonify(ok=ok)

@app.route('/add_tower',methods=['POST'])
@login_required
def at():
    try:
        d=request.json if request.is_json else request.form; la=float(d.get('lat') or 35.1318); ln=float(d.get('lng') or 36.7578)
        ok=qexec("INSERT INTO towers(name,area,lat,lng,created_at) VALUES(?,?,?,?,?)",(d.get('name','كرت'),d.get('area',''),la,ln,datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        if ok: add_log(session.get('phone'),'إضافة برج',d.get('name',''))
        return jsonify(ok=ok)
    except Exception as e: return jsonify(ok=False,msg=str(e)),500

@app.route('/del_tower/<int:i>')
@login_required
def dt(i):
    if not is_manager(): return jsonify(ok=False,msg='ممنوع'),403
    qexec("UPDATE dish_ips SET tower_id=NULL WHERE tower_id=?",(i,)); ok=qexec("DELETE FROM towers WHERE id=?",(i,))
    if ok: add_log(session.get('phone'),'حذف برج',f"ID {i}")
    return jsonify(ok=ok)

@app.route('/edit_tower/<int:i>',methods=['POST'])
@login_required
def et(i):
    if not is_manager(): return jsonify(ok=False,msg='ممنوع'),403
    d=request.json if request.is_json else request.form; la=float(d.get('lat') or 35.1318); ln=float(d.get('lng') or 36.7578)
    ok=qexec("UPDATE towers SET name=?,area=?,lat=?,lng=? WHERE id=?",(d.get('name',''),d.get('area',''),la,ln,i))
    if ok: add_log(session.get('phone'),'تعديل برج',f"ID {i}")
    return jsonify(ok=ok)

@app.route('/add_sub',methods=['POST'])
@login_required
def asub():
    d=request.json if request.is_json else request.form; ok=qexec("INSERT INTO subs(name,phone,note) VALUES(?,?,?)",(d.get('name',''),d.get('phone',''),d.get('note','')))
    if ok: add_log(session.get('phone'),'إضافة مشترك',d.get('name',''))
    return jsonify(ok=ok)

@app.route('/del_sub/<int:i>')
@login_required
def dsub(i):
    if not is_manager(): return jsonify(ok=False),403
    ok=qexec("DELETE FROM subs WHERE id=?",(i,))
    if ok: add_log(session.get('phone'),'حذف مشترك',f"ID {i}")
    return jsonify(ok=ok)

@app.route('/edit_sub/<int:i>',methods=['POST'])
@login_required
def esub(i):
    if not is_manager(): return jsonify(ok=False),403
    d=request.json if request.is_json else request.form; ok=qexec("UPDATE subs SET name=?,phone=?,note=? WHERE id=?",(d.get('name',''),d.get('phone',''),d.get('note',''),i))
    if ok: add_log(session.get('phone'),'تعديل مشترك',f"ID {i}")
    return jsonify(ok=ok)

@app.route('/add_ledger',methods=['POST'])
@login_required
def al():
    d=request.json if request.is_json else request.form
    try: amt=float(d.get('amount') or 0)
    except: amt=0
    ok=qexec("INSERT INTO ledger(name,amount,note,currency) VALUES(?,?,?,?)",(d.get('name',''),amt,d.get('note',''),d.get('currency','USD')))
    if ok: add_log(session.get('phone'),'إضافة حساب',f"{d.get('name','')} {amt}")
    return jsonify(ok=ok)

@app.route('/del_ledger/<int:i>')
@login_required
def dll(i):
    if not is_manager(): return jsonify(ok=False),403
    ok=qexec("DELETE FROM ledger WHERE id=?",(i,))
    if ok: add_log(session.get('phone'),'حذف حساب',f"ID {i}")
    return jsonify(ok=ok)

@app.route('/edit_ledger/<int:i>',methods=['POST'])
@login_required
def el(i):
    if not is_manager(): return jsonify(ok=False),403
    d=request.json if request.is_json else request.form
    try: amt=float(d.get('amount') or 0)
    except: amt=0
    ok=qexec("UPDATE ledger SET name=?,amount=?,note=?,currency=? WHERE id=?",(d.get('name',''),amt,d.get('note',''),d.get('currency','USD'),i))
    if ok: add_log(session.get('phone'),'تعديل حساب',f"ID {i}")
    return jsonify(ok=ok)

@app.route('/add_user',methods=['POST'])
@login_required
@role_required_manager
def au():
    ph=(request.form.get('phone') or request.form.get('user_field','')).strip()
    if not ph: return jsonify(ok=False,msg='رقم مطلوب'),400
    if qone("SELECT * FROM users WHERE phone=?",(ph,)): return jsonify(ok=False,msg='موجود'),400
    ok=qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",(ph,generate_password_hash(request.form.get('password','1234')),request.form.get('role','tech'),ph))
    if ok: add_log(session.get('phone'),'إضافة يوزر',ph)
    return jsonify(ok=ok)

@app.route('/edit_user',methods=['POST'])
@login_required
@role_required_manager
def eu():
    old=request.form.get('old_phone','').strip(); new_ph=(request.form.get('phone') or '').strip(); new_role=request.form.get('role','tech'); new_pass=request.form.get('password','').strip()
    if not old: return jsonify(ok=False,msg='خطأ'),400
    if old!=new_ph and qone("SELECT * FROM users WHERE phone=?",(new_ph,)): return jsonify(ok=False,msg='موجود'),400
    if new_pass: ok=qexec("UPDATE users SET phone=?,username=?,role=?,password=? WHERE phone=?",(new_ph,new_ph,new_role,generate_password_hash(new_pass),old))
    else: ok=qexec("UPDATE users SET phone=?,username=?,role=? WHERE phone=?",(new_ph,new_ph,new_role,old))
    if session.get('phone')==old: session['phone']=new_ph; session['role']=new_role
    if ok: add_log(session.get('phone'),'تعديل يوزر',old+"->"+new_ph)
    return jsonify(ok=ok)

@app.route('/del_user/<ph>')
@login_required
@role_required_manager
def du(ph):
    if ph=='05344851045': return jsonify(ok=False,msg='ممنوع'),400
    ok=qexec("DELETE FROM users WHERE phone=?",(ph,))
    if ok: add_log(session.get('phone'),'حذف يوزر',ph)
    return jsonify(ok=ok)

@app.route('/change_pass',methods=['POST'])
@login_required
def cp():
    d=request.json if request.is_json else request.form; np=(d.get('newpass') or '').strip()
    if not np: return jsonify(ok=False,msg='فارغة'),400
    ok=qexec("UPDATE users SET password=? WHERE phone=?",(generate_password_hash(np),session.get('phone')))
    if ok: add_log(session.get('phone'),'تغيير باسورد','')
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
            rs=qall("SELECT t.id,t.name,t.area,t.lat,t.lng,(SELECT COUNT(*) FROM dish_ips WHERE tower_id=t.id) as cnt FROM towers t ORDER BY t.name ASC")
            cards=""
            for t in rs:
                tid=t.get('id'); tname=esc(t.get('name') or f'برج {tid}'); tarea=esc(t.get('area') or ''); lat=t.get('lat') or 35.1318; lng=t.get('lng') or 36.7578; cnt=t.get('cnt') or 0
                cards+=f'<div class="card tower-card" id="tower-{tid}" data-name="{tname}" data-area="{tarea}" data-lat="{lat}" data-lng="{lng}"><div style="display:flex;justify-content:space-between;align-items:center"><div style="display:flex;gap:10px;align-items:center"><div style="width:var(--icon-size,44px);height:var(--icon-size,44px);background:linear-gradient(135deg,var(--accent,#ffbe4d),#ffb020);border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:20px">🗼</div><div><b style="font-size:14px">{tname}</b><div style="font-size:11px;color:#94a3b8;margin-top:2px">📍 {tarea} <span style="font-size:10px;opacity:.7">{lat:.4f},{lng:.4f}</span></div></div></div><span class=badge>{cnt} IP</span></div><div style="display:flex;gap:6px;margin-top:10px"><button class=mini-btn onclick="openEditTowerPage({tid})">✏️ تعديل</button><button class=mini-btn-del onclick="openDeleteModal(\'/del_tower/{tid}\',{tid},\'{tname}\')">🗑️</button></div></div>'
            return f"""<div style="max-width:1100px;margin:0 auto"><div class=card row style="justify-content:space-between"><b>🗼 الأبراج</b><button class=btn-gold onclick="openNewTowerPage()">+ برج</button></div><div class=grid-small id=towersGrid>{cards}</div></div><script>
window.openNewTowerPage=function(){{
let b=document.getElementById("editBody"); b.innerHTML='<input id=nt_name placeholder="اسم البرج"><input id=nt_area placeholder="المنطقة"><div class=row><input id=nt_lat value="35.1318"><input id=nt_lng value="36.7578"></div><button class=btn-gold onclick="saveNewTowerPage()" style="width:100%">حفظ</button>'; document.getElementById("editModalTitle").textContent="إضافة برج"; document.getElementById("editModal").classList.add("show");
}};
window.saveNewTowerPage=async function(){{
let d={{name:document.getElementById("nt_name").value,area:document.getElementById("nt_area").value,lat:document.getElementById("nt_lat").value,lng:document.getElementById("nt_lng").value}};
if(!d.name) return; let r=await fetch("/add_tower",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify(d)}}); let j=await r.json(); if(j.ok){{closeEditModal(); loadPage("towers",true);}}
}};
window.openEditTowerPage=async function(id){{
let card=document.getElementById("tower-"+id);
if(card){{
 let b=document.getElementById("editBody");
 b.innerHTML='<input id=et_name value="'+card.dataset.name+'"><input id=et_area value="'+card.dataset.area+'"><div class=row><input id=et_lat value="'+card.dataset.lat+'"><input id=et_lng value="'+card.dataset.lng+'"></div><button class=btn-gold onclick="saveTowerPage('+id+')" style="width:100%">حفظ</button>';
 document.getElementById("editModalTitle").textContent="تعديل برج";
 document.getElementById("editModal").classList.add("show");
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
let r=await fetch("/edit_tower/"+id,{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify(d)}}); let j=await r.json(); if(j.ok){{closeEditModal(); loadPage("towers",true);}} else alert("خطأ");
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
        <div style="font-size:11px;color:#94a3b8;margin-top:3px;display:flex;gap:6px;align-items:center">📍 <span>{tarea}</span> <span style="font-size:10px;opacity:.6">{lat:.4f},{lng:.4f}</span></div>
      </div>
    </div>
    <div style="display:flex;gap:6px;align-items:center;flex-shrink:0">
      <button class=mini-btn onclick="event.stopPropagation();openEditTowerPage({tid})" title="تعديل">✏️</button>
      <button class=mini-btn-del onclick="event.stopPropagation();openDeleteModal('/del_tower/{tid}',{tid},'{tname}')" title="حذف">🗑️</button>
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
    <div style="display:flex;gap:10px;align-items:center"><div style="width:44px;height:44px;background:#ef4444;border-radius:10px;display:flex;align-items:center;justify-content:center">⚠️</div><div><b>بدون برج</b><div style="font-size:11px;color:#94a3b8">عناوين غير مربوطة - {no_cnt} IP</div></div></div>
    <div style="display:flex;gap:8px;align-items:center"><span style="background:#ef4444;color:#fff;padding:3px 8px;border-radius:6px;font-size:11px">{no_cnt} IP</span><div id="arrow-0">▼</div></div>
  </div>
  <div class="tower-accordion-body" id="tower-body-0" style="display:none;background:#0f1424"><div id="tower-content-0" style="padding:12px"></div></div>
</div>'''
            part1 = f"""
<div style="max-width:1100px;margin:0 auto">
<div class=card style="display:flex;justify-content:space-between;align-items:center"><b>📡 الصحون - تحميل كسول سريع</b><div class=row><input id=dishTowerSearch placeholder="🔍 بحث برج" oninput="filterTowerAccordion(this.value)" style="padding:8px 12px;border-radius:8px;min-width:180px"><button class=btn-gold onclick="openNewTowerAcc()">+ برج</button></div></div>
<div id=accordionContainer style="display:flex;flex-direction:column;gap:10px;margin-top:12px">{accordion_html}</div>
</div>
<div id=addDishTowerModal style="position:fixed;inset:0;background:#000a;display:none;align-items:center;justify-content:center;z-index:2500">
<div style="background:var(--card-bg,#1e2433);width:95%;max-width:400px;border-radius:14px;padding:18px;border:1px solid #ffffff15"><div style="display:flex;justify-content:space-between;margin-bottom:12px"><b id=addDishModalTitle>+ إضافة صحن</b><button onclick="closeAddDishModal()" style="width:28px;height:28px;background:#ffffff10;border:0;border-radius:6px">✕</button></div><input id=modalDishName placeholder="اسم الصحن" style="width:100%;padding:10px;margin-bottom:8px"><input id=modalDishIp placeholder="IP او دومين - سيفتح في كروم" style="width:100%;padding:10px;margin-bottom:8px"><input id=modalDishLoc placeholder="موقع" style="width:100%;padding:10px;margin-bottom:8px"><input type=hidden id=modalDishTowerId><div class=row style="gap:8px"><button onclick="closeAddDishModal()" style="flex:1;padding:10px;border-radius:8px;background:transparent;border:1px solid #ffffff15;color:var(--text)">إلغاء</button><button onclick="saveDishToTower()" class=btn-gold style="flex:1">حفظ</button></div></div></div>
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
function escHtml(s){return (s||'').toString().replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
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
 let isHidden=body.style.display==='none'||body.style.display==='';
 if(isHidden){
  body.style.display='block';
  if(arrow) arrow.style.transform='rotate(180deg)';
  if(acc.dataset.loaded==='0'){
   let content=document.getElementById('tower-content-'+tid);
   content.innerHTML='<div style="text-align:center;padding:20px;color:#888">⏳ تحميل سريع...</div>';
   try{
    let r=await fetch('/api/tower_detail/'+tid);
    let j=await r.json();
    if(j.ok){
     let dishes=j.dishes||[];
     DISH_CACHE[tid]=dishes;
     acc.dataset.loaded='1';
     renderDishesBatch(tid,0);
    } else content.innerHTML='<div style="color:#ef4444">خطأ</div>';
   }catch(e){content.innerHTML='<div style="color:#ef4444">خطأ '+e+'</div>';}
  }
 } else {
  body.style.display='none';
  if(arrow) arrow.style.transform='rotate(0deg)';
 }
};
window.renderDishesBatch=function(tid,start){
 let dishes=DISH_CACHE[tid]||[];
 let content=document.getElementById('tower-content-'+tid);
 if(!content) return;
 let batchSize=10;
 if(start===0){
  content.innerHTML='<div id="dish-list-'+tid+'" style="display:flex;flex-direction:column;gap:8px"></div><div id="dish-more-'+tid+'" style="margin-top:8px"></div><button class="btn-gold" onclick="openAddDishModal('+tid+')" style="width:100%;margin-top:12px;padding:10px">+ إضافة صحن لهذا البرج</button>';
 }
 let list=document.getElementById('dish-list-'+tid);
 let moreDiv=document.getElementById('dish-more-'+tid);
 let end=Math.min(start+batchSize,dishes.length);
 for(let i=start;i<end;i++){
  let d=dishes[i];
  let row=document.createElement('div');
  row.id='dish-'+d.id;
  row.className='dish-row';
  row.style.cssText='display:grid;grid-template-columns:1fr auto 72px;gap:8px;align-items:center;background:var(--dish-bg,#ffffff06);border:1px solid var(--border,#ffffff10);border-radius:10px;padding:10px';
  let ip=d.ip||'';
  row.innerHTML=`
   <div style="min-width:0">
     <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
       <b style="color:var(--text,#fff);font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${escHtml(d.dish_name||'صحن')}</b>
       <span onclick="openInChrome('${escHtml(ip)}')" style="background:#000;color:var(--accent,#ffbe4d);padding:2px 8px;border-radius:6px;font-family:monospace;font-size:11px;font-weight:700;cursor:pointer" title="افتح في كروم - ${escHtml(ip)}">${escHtml(ip)}</span>
     </div>
     <div style="font-size:11px;color:#94a3b8;margin-top:4px;display:flex;align-items:center;gap:4px">📍 <span style="color:#94a3b8">${escHtml(d.location||'')}</span></div>
   </div>
   <a href="javascript:openInChrome('${escHtml(ip)}')" style="width:32px;height:32px;background:var(--border);border-radius:8px;display:flex;align-items:center;justify-content:center;text-decoration:none;font-size:14px" title="فتح في كروم">🌐</a>
   <div style="display:flex;gap:4px;justify-content:flex-end">
     <button onclick="openEditDishAcc(${d.id})" style="width:32px;height:32px;background:var(--border);border:0;border-radius:8px;cursor:pointer" title="تعديل">✏️</button>
     <button onclick="openDeleteModal('/del_dish/${d.id}',${d.id},'${escHtml(ip)}')" style="width:32px;height:32px;background:#ef444422;border:0;border-radius:8px;color:#ef4444;cursor:pointer" title="حذف">🗑️</button>
   </div>`;
  list.appendChild(row);
 }
 if(end < dishes.length){
  moreDiv.innerHTML=`<button onclick="renderDishesBatch(${tid},${end})" class="btn-gold" style="width:100%;background:#ffffff10;color:var(--text);border:1px dashed var(--border)">عرض المزيد (${dishes.length-end} متبقي) ↓</button>`;
 } else {
  moreDiv.innerHTML=`<div style="text-align:center;font-size:10px;color:#666;margin-top:8px">تم عرض ${dishes.length} عنصر ✓</div>`;
 }
};
window.openAddDishModal=function(tid){
 document.getElementById('addDishTowerModal').style.display='flex';
 document.getElementById('modalDishTowerId').value=tid;
 document.getElementById('addDishModalTitle').textContent='+ إضافة صحن لبرج '+(tid===0?'بدون برج':tid);
};
window.closeAddDishModal=function(){document.getElementById('addDishTowerModal').style.display='none';};
window.saveDishToTower=async function(){
 let name=document.getElementById('modalDishName').value.trim();
 let ip=document.getElementById('modalDishIp').value.trim();
 let loc=document.getElementById('modalDishLoc').value.trim();
 let tid=document.getElementById('modalDishTowerId').value;
 if(!ip){alert('IP مطلوب'); return;}
 if(!name) name='صحن '+ip;
 let r=await fetch('/api/add_dish_to_tower',{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({ip:ip,dish_name:name,location:loc,tower_id:tid})});
 let j=await r.json();
 if(j.ok){
  closeAddDishModal();
  let acc=document.getElementById('tower-acc-'+tid);
  if(acc) acc.dataset.loaded='0';
  let body=document.getElementById('tower-body-'+tid);
  if(body) body.style.display='none';
  toggleAccordionLazy(parseInt(tid));
 }
};
window.openEditDishAcc=async function(did){
 try{let r=await fetch('/api/dish_detail/'+did); let j=await r.json(); if(!j.ok) return; let d=j.dish;
 let b=document.getElementById("editBody");
 b.innerHTML='<div style="display:flex;flex-direction:column;gap:8px"><input id=ed_name value="'+(d.dish_name||"")+'" placeholder="اسم الصحن"><input id=ed_ip value="'+(d.ip||"")+'" placeholder="IP او دومين"><input id=ed_loc value="'+(d.location||"")+'" placeholder="موقع"><button class=btn-gold onclick="saveDishAcc('+did+')" style="width:100%;margin-top:8px">حفظ التعديل ✓</button></div>';
 document.getElementById("editModalTitle").textContent="✏️ تعديل صحن";
 document.getElementById("editModal").classList.add("show");
 }catch(e){alert(e);}
};
window.saveDishAcc=async function(id){
 let d={dish_name:document.getElementById("ed_name").value,ip:document.getElementById("ed_ip").value,location:document.getElementById("ed_loc").value};
 let r=await fetch("/edit_dish/"+id,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(d)});
 let j=await r.json();
 if(j.ok){closeEditModal(); for(let tid in DISH_CACHE){let acc=document.getElementById('tower-acc-'+tid); if(acc) acc.dataset.loaded='0';} loadPage('dishes',true);}
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

        if v=='map':
            return """
<div class=card>
<div class=row style="gap:6px;flex-wrap:wrap">
<input id=mapSearch placeholder="بحث برج أو مدينة..." style="flex:1;min-width:200px;padding:8px" onkeydown="if(event.key==='Enter') searchPlace()">
<button class=btn-gold onclick="doMapSearch()">بحث برج</button>
<button class=btn-gold onclick="searchPlace()" style="background:#0ea5e9">بحث مدينة</button>
<button class=btn-gold onclick="locateMe()" style="background:#22c55e">📍 موقعي</button>
<button class=btn-gold onclick="enableAddMode()" id=addModeBtn style="background:#8b5cf6">+ نقطة</button>
<span id=coordDisplay style="font-size:10px;background:#000;color:#ffbe4d;padding:4px 8px;border-radius:6px">إحداثيات</span>
<span id=mapStatus style="font-size:10px;color:#22c55e"></span>
</div>
<div id=map style="height:72vh;border-radius:10px;margin-top:10px;background:#0f1424"></div>
</div>
<script>
let _towers=[]; let _markers=[]; let _searchMarkers=[]; window._map=null; let addMode=false;
function escHtml(s){return (s||'').toString().replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
window.openInChromeMap=function(ip){let url=ip; if(!url.startsWith('http')) url='http://'+url; window.open(url,'_blank');};
window.doMapSearch=function(){
 let q=document.getElementById("mapSearch").value.toLowerCase().trim();
 if(!q){_markers.forEach(m=>m.setOpacity(1)); return;}
 let f=_towers.filter(t=> (t.name||'').toLowerCase().includes(q) || (t.area||'').toLowerCase().includes(q));
 _markers.forEach((m,i)=>{
  let t=_towers[i]; if(!t) return;
  let show=(t.name||'').toLowerCase().includes(q) || (t.area||'').toLowerCase().includes(q);
  m.setOpacity(show?1:0.2);
 });
 if(f[0]) window._map.flyTo([f[0].lat,f[0].lng],15);
 document.getElementById("mapStatus").textContent=`${f.length} نتيجة`;
};
window.searchPlace=async function(){
 let q=document.getElementById("mapSearch").value.trim(); if(!q) return;
 document.getElementById("mapStatus").textContent='⏳ يبحث...';
 try{
  let r=await fetch('https://nominatim.openstreetmap.org/search?format=json&q='+encodeURIComponent(q)+'&limit=5&countrycodes=sy,lb,tr');
  let data=await r.json();
  _searchMarkers.forEach(m=>window._map.removeLayer(m)); _searchMarkers=[];
  data.forEach(p=>{
   let m=L.marker([parseFloat(p.lat),parseFloat(p.lon)]).addTo(window._map).bindPopup("<b>"+escHtml(p.display_name)+"</b><br><button onclick=\\"addTowerAt("+p.lat+","+p.lon+",'"+p.display_name.replace(/'/g,"")+"')\\" style=\\"padding:6px 10px;background:#ffbe4d;border:0;border-radius:6px;cursor:pointer\\">+ إضافة برج هنا</button>");
   _searchMarkers.push(m);
  });
  if(data[0]) window._map.flyTo([parseFloat(data[0].lat),parseFloat(data[0].lon)],13);
  document.getElementById("mapStatus").textContent=`${data.length} مدينة`;
 }catch(e){document.getElementById("mapStatus").textContent='خطأ';}
};
window.addTowerAt=function(lat,lng,name){
 let b=document.getElementById("editBody");
 b.innerHTML='<input id=nt_name value="'+name.substring(0,30)+'"><input id=nt_area placeholder="المنطقة"><div class=row><input id=nt_lat value="'+lat+'"><input id=nt_lng value="'+lng+'"></div><button class=btn-gold onclick="saveNewTowerMap()" style="width:100%">حفظ برج ✓</button>';
 document.getElementById("editModalTitle").textContent="إضافة برج جديد";
 document.getElementById("editModal").classList.add("show");
};
window.saveNewTowerMap=async function(){
 let d={name:document.getElementById("nt_name").value,area:document.getElementById("nt_area").value,lat:document.getElementById("nt_lat").value,lng:document.getElementById("nt_lng").value};
 if(!d.name) return;
 let r=await fetch("/add_tower",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(d)});
 let j=await r.json();
 if(j.ok){closeEditModal(); loadTowersForMap();}
};
window.enableAddMode=function(){addMode=!addMode; let btn=document.getElementById("addModeBtn"); btn.textContent=addMode?"✓ انقر على الخريطة":"+ نقطة"; btn.style.background=addMode?"#ef4444":"#8b5cf6";};
window.locateMe=function(){if(navigator.geolocation) navigator.geolocation.getCurrentPosition(p=>{let lat=p.coords.latitude,lng=p.coords.longitude; window._map.flyTo([lat,lng],16); L.marker([lat,lng]).addTo(window._map).bindPopup("📍 موقعك الحالي").openPopup();});};
window.loadTowersForMap=async function(){
 document.getElementById("mapStatus").textContent='⏳ تحميل...';
 try{
  let r=await fetch('/api/towers_list'); let j=await r.json();
  if(!j.ok) return;
  _towers=j.towers||[];
  _markers.forEach(m=>{try{window._map.removeLayer(m);}catch{}}); _markers=[];
  let i=0;
  function addBatch(){
   let end=Math.min(i+5,_towers.length);
   for(;i<end;i++){
    let t=_towers[i];
    let m=L.marker([parseFloat(t.lat||35.13),parseFloat(t.lng||36.75)],{draggable:true}).addTo(window._map).bindPopup("<div style='min-width:160px'><b>"+escHtml(t.name)+"</b><br>📍 "+escHtml(t.area||'')+"<br><div style='margin-top:6px;display:flex;gap:4px'><button onclick=\\"openEditTowerMap("+t.id+")\\" style='padding:4px 8px;background:#ffffff10;border:0;border-radius:6px;cursor:pointer'>✏️</button><button onclick=\\"openDeleteModal('/del_tower/"+t.id+"',"+t.id+",'"+escHtml(t.name)+"')\\" style='padding:4px 8px;background:#ef444422;border:0;border-radius:6px;color:#ef4444;cursor:pointer'>🗑️</button></div></div>");
    _markers.push(m);
    m.on("dragend",e=>{let ll=e.target.getLatLng(); fetch("/api/update_tower_pos",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:t.id,lat:ll.lat,lng:ll.lng})});});
   }
   if(i<_towers.length){setTimeout(addBatch,60);} else {document.getElementById("mapStatus").textContent=`${_towers.length} برج ✓`;}
  }
  addBatch();
 }catch(e){document.getElementById("mapStatus").textContent='خطأ '+e;}
};
window.openEditTowerMap=async function(id){
 try{let r=await fetch('/api/tower_detail/'+id); let j=await r.json(); if(!j.ok) return; let t=j.tower;
 let b=document.getElementById("editBody");
 b.innerHTML='<input id=et_name value="'+(t.name||"")+'"><input id=et_area value="'+(t.area||"")+'"><div class=row><input id=et_lat value="'+(t.lat||"")+'"><input id=et_lng value="'+(t.lng||"")+'"></div><button class=btn-gold onclick="saveTowerMap('+id+')" style="width:100%">حفظ ✓</button>';
 document.getElementById("editModalTitle").textContent="تعديل برج"; document.getElementById("editModal").classList.add("show");
 }catch(e){alert(e);}
};
window.saveTowerMap=async function(id){
 let d={name:document.getElementById("et_name").value,area:document.getElementById("et_area").value,lat:document.getElementById("et_lat").value,lng:document.getElementById("et_lng").value};
 await fetch("/edit_tower/"+id,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(d)});
 closeEditModal(); loadTowersForMap();
};
setTimeout(()=>{
 window._map=L.map("map",{zoomControl:false}).setView([35.1318,36.7578],11);
 L.control.zoom({position:'bottomright'}).addTo(window._map);
 let osm=L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",{maxZoom:19,attribution:''}).addTo(window._map);
 let sat=L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",{maxZoom:19,attribution:''});
 L.control.layers({"عادية":osm,"قمر":sat},{},{position:'topleft'}).addTo(window._map);
 window._map.on("mousemove",e=>{document.getElementById("coordDisplay").textContent=e.latlng.lat.toFixed(5)+", "+e.latlng.lng.toFixed(5);});
 window._map.on("click",e=>{if(!addMode) return; let lat=e.latlng.lat,lng=e.latlng.lng; if(confirm("إضافة برج هنا؟\\n"+lat.toFixed(5)+","+lng.toFixed(5))){let b=document.getElementById("editBody"); b.innerHTML='<input id=nt_name placeholder="اسم البرج"><input id=nt_area placeholder="المنطقة"><div class=row><input id=nt_lat value="'+lat+'"><input id=nt_lng value="'+lng+'"></div><button class=btn-gold onclick="saveNewTowerMap()" style="width:100%">حفظ ✓</button>'; document.getElementById("editModalTitle").textContent="إضافة برج"; document.getElementById("editModal").classList.add("show");}});
 loadTowersForMap();
},300);
</script>"""
        if v=='ping':
            return """
<div class=card><h3>📶 البنج</h3><div class=row style="gap:6px;margin-top:8px"><input id=pingIp placeholder="192.168.1.1 او دومين - يفتح في كروم" style="flex:1"><button class=btn-gold onclick="doSinglePing()">سيرفر</button><button class=btn-gold onclick="doClientPing()" style="background:#0ea5e9">جهازي</button><button class=btn-gold onclick="openInChrome()">🌐 افتح في كروم</button></div><div id=pingResult class=pingBox>جاهز - الضغط على IP يفتح في كروم</div></div>
<script>
window.openInChrome=function(){let ip=document.getElementById('pingIp').value.trim(); if(ip){let url=ip; if(!url.startsWith('http')) url='http://'+url; window.open(url,'_blank');}};
window.doSinglePing=async function(){let ip=document.getElementById('pingIp').value.trim(); if(!ip)return; let out=document.getElementById('pingResult'); out.textContent='يفحص '+ip+'...'; try{let r=await fetch('/api/ping?ip='+encodeURIComponent(ip)); let j=await r.json(); out.textContent=j.out+' - انقر لفتح في كروم'; out.onclick=()=>openInChrome(); out.style.cursor='pointer';}catch{out.textContent='خطأ';}};
window.doClientPing=async function(){let ip=document.getElementById('pingIp').value.trim(); if(!ip)return; let out=document.getElementById('pingResult'); out.textContent='يفحص '+ip+'...'; try{let ctrl=new AbortController(); setTimeout(()=>ctrl.abort(),2000); let start=Date.now(); await fetch('http://'+ip,{mode:'no-cors',signal:ctrl.signal}); let ms=Date.now()-start; out.textContent=ip+' ✓ '+ms+'ms - انقر لفتح في كروم'; out.onclick=()=>openInChrome(); out.style.cursor='pointer';}catch{out.textContent=ip+' لا يرد';}};
</script>"""
        if v=='logs':
            rs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 500")
            rows="".join([f"<tr><td>{esc(r.get('time',''))}</td><td><span class=badge>{esc(r.get('action',''))}</span></td><td>{esc(r.get('user_phone',''))}</td><td>{esc(r.get('detail',''))}</td></tr>" for r in rs]) or "<tr><td colspan=4>لا يوجد سجل</td></tr>"
            return f"""<div class=card><div class=row style="justify-content:space-between"><b>📜 السجل - {len(rs)}</b><div class=row><a href="/api/export/logs" class=btn-gold style="text-decoration:none;padding:4px 8px">تصدير</a><button class=btn-gold onclick="clearLogs()" style="background:#ef4444">مسح</button></div></div><table style="width:100%;margin-top:8px"><thead><tr><th>وقت</th><th>عمل</th><th>يوزر</th><th>تفصيل</th></tr></thead><tbody>{rows}</tbody></table></div><script>window.clearLogs=async()=>{{if(!confirm("مسح؟")) return; await fetch("/api/clear_logs",{{method:"POST"}}); loadPage("logs",true);}};</script>"""
        if v=='subs':
            rs=qall("SELECT * FROM subs ORDER BY name ASC")
            rows="".join([f"<tr id=sub-{r.get('id')}><td>{esc(r.get('name') or '')}</td><td><span style='cursor:pointer;color:var(--accent)' onclick=\"openInChrome('{esc(r.get('phone') or '')}')\">{esc(r.get('phone') or '')}</span></td><td>{esc(r.get('note') or '')}</td><td><div style='display:flex;gap:4px'><button class=mini-btn onclick=\"editSub({r.get('id')})\">✏️</button><button class=mini-btn-del onclick=\"openDeleteModal('/del_sub/{r.get('id')}',{r.get('id')},'مشترك')\">🗑️</button></div></td></tr>" for r in rs])
            return f"""<div class=card><div class=row style="justify-content:space-between"><b>👥 المشتركين</b><button class=btn-gold onclick="document.getElementById('fSub').style.display='flex'">+ إضافة</button></div><form id=fSub class=row style="display:none;gap:4px;margin-top:8px"><input name=name placeholder="اسم" required style="flex:1"><input name=phone placeholder="رقم / IP / دومين" style="flex:1"><input name=note placeholder="ملاحظة" style="flex:1"><button class=btn-gold>+</button></form><table style="width:100%;margin-top:8px"><thead><tr><th>اسم</th><th>رقم / IP</th><th>ملاحظة</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>
<script>
window.openInChrome=function(ip){{if(!ip) return; let url=ip; if(!url.startsWith('http')) url='http://'+url; window.open(url,'_blank');}};
document.getElementById("fSub").addEventListener("submit",async e=>{{e.preventDefault(); let fd=new FormData(e.target); let r=await fetch("/add_sub",{{method:"POST",body:fd}}); let j=await r.json(); if(j.ok) loadPage("subs",true);}});
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
closeEditModal();
loadPage("subs",true);
}};
</script>"""
        if v=='ledger':
            rs=qall("SELECT * FROM ledger ORDER BY id DESC")
            rows="".join([f"<tr id=led-{r.get('id')}><td>{esc(r.get('name') or '')}</td><td><span class=ip style='cursor:pointer' onclick=\"openInChrome('{esc(r.get('note') or '')}')\">{r.get('amount')}</span></td><td>{esc(r.get('note') or '')}</td><td>{esc(r.get('currency') or '')}</td><td><div style='display:flex;gap:4px'><button class=mini-btn onclick=\"editLed({r.get('id')})\">✏️</button><button class=mini-btn-del onclick=\"openDeleteModal('/del_ledger/{r.get('id')}',{r.get('id')},'حساب')\">🗑️</button></div></td></tr>" for r in rs])
            return f"""<div class=card><div class=row style="justify-content:space-between"><b>📒 الحسابات</b><button class=btn-gold onclick="document.getElementById('fLed').style.display='flex'">+ إضافة</button></div><form id=fLed class=row style="display:none;gap:4px;margin-top:8px"><input name=name placeholder="اسم" required style="flex:1"><input name=amount type=number step=0.01 placeholder="مبلغ" required style="flex:1"><input name=note placeholder="ملاحظة / دومين" style="flex:1"><select name=currency><option>USD</option><option>SYP</option></select><button class=btn-gold>+</button></form><table style="width:100%;margin-top:8px"><thead><tr><th>اسم</th><th>مبلغ</th><th>ملاحظة</th><th>عملة</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>
<script>
window.openInChrome=function(ip){{if(!ip) return; let url=ip; if(!url.startsWith('http')) url='http://'+url; window.open(url,'_blank');}};
document.getElementById("fLed").addEventListener("submit",async e=>{{e.preventDefault(); let fd=new FormData(e.target); let r=await fetch("/add_ledger",{{method:"POST",body:fd}}); let j=await r.json(); if(j.ok) loadPage("ledger",true);}});
window.editLed=function(id){{
let row=document.getElementById("led-"+id);
let name=row.children[0].textContent;
let amt=row.children[1].textContent;
let note=row.children[2].textContent;
let b=document.getElementById("editBody");
b.innerHTML='<input id=el_name value="'+name+'"><input id=el_amt value="'+amt+'"><input id=el_note value="'+note+'"><button class=btn-gold onclick="saveLed('+id+')" style="width:100%;margin-top:8px">حفظ</button>';
document.getElementById("editModalTitle").textContent="تعديل حساب";
document.getElementById("editModal").classList.add("show");
}};
window.saveLed=async function(id){{
let d={{name:document.getElementById("el_name").value,amount:document.getElementById("el_amt").value,note:document.getElementById("el_note").value}};
await fetch("/edit_ledger/"+id,{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify(d)}});
closeEditModal();
loadPage("ledger",true);
}};
</script>"""
        if v=='network':
            dishes=qall("SELECT * FROM dish_ips ORDER BY dish_name ASC")
            rows="".join([f"<tr id=net-{d.get('id')} data-ip='{esc(d.get('ip') or '')}'><td>{esc(d.get('dish_name') or '')}</td><td><span class=ip style='cursor:pointer' onclick=\"window.open('http://{esc(d.get('ip') or '')}','_blank')\">{esc(d.get('ip') or '')}</span></td><td class=net-out>...</td><td><a href=\"javascript:openInChrome('{esc(d.get('ip') or '')}')\">🌐</a> <button onclick='checkOne({d.get('id')})'>📶</button></td></tr>" for d in dishes])
            return f"""<div class=card><div class=row style="justify-content:space-between"><b>📊 الشبكة - الضغط على IP يفتح في كروم</b><button class=btn-gold onclick="checkAll()">فحص الكل</button></div><table style="width:100%;margin-top:8px"><thead><tr><th>اسم</th><th>IP / دومين</th><th>حالة</th><th></th></tr></thead><tbody>{rows}</tbody></table></div><script>
window.openInChrome=function(ip){{if(!ip) return; let url=ip; if(!url.startsWith('http')) url='http://'+url; window.open(url,'_blank');}};
window.checkOne=async id=>{{let c=document.getElementById("net-"+id); let out=c.querySelector(".net-out"); out.textContent="..."; try{{let r=await fetch("/api/ping?ip="+c.dataset.ip); let j=await r.json(); out.textContent=j.out; out.style.cursor='pointer'; out.onclick=()=>openInChrome(c.dataset.ip);}}catch{{out.textContent="خطأ";}}}};
window.checkAll=async()=>{{for(let c of document.querySelectorAll("[id^=net-]")){{checkOne(c.id.split("-")[1]); await new Promise(r=>setTimeout(r,80));}}}};
</script>"""
        if v=='settings':
            us=qall("SELECT * FROM users ORDER BY phone ASC")
            cfg_rows=qall("SELECT * FROM system_config")
            cfg={r['key']:r['value'] for r in cfg_rows} if cfg_rows else {}
            cards="".join([f"<div class='card' id=user-{esc(u.get('phone') or '')} data-phone='{esc(u.get('phone') or '')}' data-role='{esc(u.get('role') or '')}'><div style='text-align:center'><b>{esc(u.get('username') or u.get('phone') or '')}</b><br><span class=ip style='cursor:pointer' onclick=\"window.open('http://{esc(u.get('phone') or '')}','_blank')\">{esc(u.get('phone') or '')}</span><br><span class=badge>{esc(u.get('role') or '')}</span><div style='display:flex;gap:6px;justify-content:center;margin-top:8px'><button class=mini-btn onclick=\"openEditUser('{esc(u.get('phone') or '')}')\">✏️</button><button class=mini-btn-del onclick=\"openDeleteModal('/del_user/{esc(u.get('phone') or '')}','{esc(u.get('phone') or '')}','يوزر')\">🗑️</button></div></div></div>" for u in us])
            return f"""
<div style="max-width:1100px;margin:0 auto">
<div class=grid-small>
<div class=card><h4>🔑 باسوردي</h4><form id=formPass class=row><input name=newpass type=password placeholder="new password" required style="flex:1"><button class=btn-gold>حفظ</button></form></div>
<div class=card><h4>👤 إضافة يوزر</h4><form id=formUser class=row style="flex-wrap:wrap;gap:4px"><input name=user_field placeholder="user" required style="flex:1"><input name=password type=password placeholder="password" required style="flex:1"><select name=role><option value=tech>tech</option><option value=manager>manager</option></select><button class=btn-gold>➕</button></form></div>
<div class=card><h4>💬 الدعم الفني</h4><div style="display:flex;gap:10px;margin-top:8px"><a href="{SUPPORT_WA_LINK}" target="_blank" style="width:56px;height:56px;background:#25D366;border-radius:50%;display:flex;align-items:center;justify-content:center;text-decoration:none;font-size:26px;color:#fff">💬</a><a href="{SUPPORT_INSTA_LINK}" target="_blank" style="width:56px;height:56px;background:linear-gradient(45deg,#feda75,#d62976);border-radius:50%;display:flex;align-items:center;justify-content:center;text-decoration:none;font-size:26px;color:#fff">📷</a></div><div style="font-size:11px;margin-top:8px">+{SUPPORT_WA} | {SUPPORT_INSTA}</div></div>
</div>
<div class=card style="margin-top:12px"><h4>🎛️ الأحجام والألوان</h4>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:10px">
<div><label style="font-size:11px">حجم الكروت: <span id=cardSizeVal>{cfg.get('card_size','160')}px</span></label><input type=range id=cardSizeSlider min=120 max=400 value={cfg.get('card_size','160')} style="width:100%" oninput="updateCardSize(this.value)"></div>
<div><label style="font-size:11px">حجم الأيقونات: <span id=iconSizeVal>{cfg.get('icon_size','44')}px</span></label><input type=range id=iconSizeSlider min=24 max=100 value={cfg.get('icon_size','44')} style="width:100%" oninput="updateIconSize(this.value)"></div>
</div>
<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-top:12px">
<div><label style="font-size:11px">لون الأبراج</label><input type=color id=towerBgColor value="{cfg.get('tower_bg','#1e2433')}" style="width:100%;height:36px" oninput="updateColor('tower_bg',this.value)"></div>
<div><label style="font-size:11px">لون الصحون</label><input type=color id=dishBgColor value="{cfg.get('dish_bg','#ffffff06')}" style="width:100%;height:36px" oninput="updateColor('dish_bg',this.value)"></div>
<div><label style="font-size:11px">لون التمييز</label><input type=color id=accentColor value="{cfg.get('accent_color','#ffbe4d')}" style="width:100%;height:36px" oninput="updateColor('accent_color',this.value)"></div>
</div>
<div style="display:flex;gap:8px;margin-top:14px">
<button class=btn-gold onclick="saveAllAppearance()" style="flex:1;padding:12px;font-size:13px">💾 حفظ التغييرات</button>
<button onclick="resetAppearance()" style="flex:1;padding:12px;border-radius:8px;background:transparent;border:1px solid var(--border);color:var(--text);cursor:pointer;font-size:13px">🔄 إعادة افتراضي</button>
</div>
<div id=saveStatus style="text-align:center;font-size:11px;margin-top:8px;color:#22c55e"></div>
</div>
<div style="margin-top:12px"><b>👥 اليوزرات</b><div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px;margin-top:8px">{cards}</div></div>
</div>
<script>
window.updateCardSize=function(v){{document.getElementById('cardSizeVal').textContent=v+'px'; document.documentElement.style.setProperty('--card-min',v+'px'); localStorage.setItem('cardSize',v);}};
window.updateIconSize=function(v){{document.getElementById('iconSizeVal').textContent=v+'px'; document.documentElement.style.setProperty('--icon-size',v+'px'); localStorage.setItem('iconSize',v);}};
window.updateColor=function(k,v){{document.documentElement.style.setProperty('--'+k.replace('_','-'),v); localStorage.setItem(k,v);}};
window.saveAllAppearance=async function(){{
 let cfg={{card_size:document.getElementById('cardSizeSlider').value,icon_size:document.getElementById('iconSizeSlider').value,tower_bg:document.getElementById('towerBgColor').value,dish_bg:document.getElementById('dishBgColor').value,accent_color:document.getElementById('accentColor').value}};
 document.getElementById('saveStatus').textContent='⏳ جاري الحفظ...';
 try{{
  for(let [k,v] of Object.entries(cfg)){{await fetch('/api/set_config',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{key:k,value:v}})}});}}
  document.getElementById('saveStatus').textContent='✓ تم حفظ التغييرات بنجاح';
  setTimeout(()=>document.getElementById('saveStatus').textContent='',2000);
 }}catch(e){{document.getElementById('saveStatus').textContent='خطأ '+e;}}
}};
window.resetAppearance=function(){{
 let defaults={{card_size:'160',icon_size:'44',tower_bg:'#1e2433',dish_bg:'#ffffff06',accent_color:'#ffbe4d'}};
 document.getElementById('cardSizeSlider').value=defaults.card_size;
 document.getElementById('iconSizeSlider').value=defaults.icon_size;
 document.getElementById('towerBgColor').value=defaults.tower_bg;
 document.getElementById('dishBgColor').value=defaults.dish_bg;
 document.getElementById('accentColor').value=defaults.accent_color;
 updateCardSize(defaults.card_size);
 updateIconSize(defaults.icon_size);
 updateColor('tower_bg',defaults.tower_bg);
 updateColor('dish_bg',defaults.dish_bg);
 updateColor('accent_color',defaults.accent_color);
 saveAllAppearance();
}};
window.openEditUser=function(ph){{
let c=document.getElementById("user-"+ph);
let b=document.getElementById("editBody");
b.innerHTML='<input id=eu_ph value="'+c.dataset.phone+'" placeholder="user"><select id=eu_role><option value=tech>tech</option><option value=manager>manager</option></select><input id=eu_pass type=password placeholder="password"><button class=btn-gold onclick="saveUser(\\''+ph+'\\')" style="width:100%;margin-top:8px">حفظ</button>';
document.getElementById("eu_role").value=c.dataset.role;
document.getElementById("editModalTitle").textContent="تعديل يوزر";
document.getElementById("editModal").classList.add("show");
}};
window.saveUser=async function(old){{
let fd=new URLSearchParams({{old_phone:old,phone:document.getElementById("eu_ph").value,role:document.getElementById("eu_role").value,password:document.getElementById("eu_pass").value}});
let r=await fetch("/edit_user",{{method:"POST",body:fd}}); let j=await r.json(); if(j.ok){{closeEditModal(); loadPage('settings',true);}} else alert(j.msg);
}};
document.getElementById("formPass").addEventListener("submit",async e=>{{e.preventDefault(); let r=await fetch("/change_pass",{{method:"POST",body:new FormData(e.target)}}); let j=await r.json(); if(j.ok) e.target.reset();}});
document.getElementById("formUser").addEventListener("submit",async e=>{{e.preventDefault(); let r=await fetch("/add_user",{{method:"POST",body:new FormData(e.target)}}); let j=await r.json(); if(j.ok){{e.target.reset(); loadPage('settings',true);}} else alert(j.msg);}});
</script>"""
        return "<div class=card>404</div>"
    except Exception as e:
        traceback.print_exc()
        return f"<div class=card>خطأ {esc(str(e))}</div>"

def layout(c,v='home'):
    th=session.get('theme','dark'); is_dark=(th=='dark')
    cur_user=qone("SELECT * FROM users WHERE phone=?",(session.get('phone') or '',)) or {}
    cfg_rows=qall("SELECT * FROM system_config")
    cfg={r['key']:r['value'] for r in cfg_rows} if cfg_rows else {}
    lang=session.get('lang','ar')
    tr={
      'ar':{'home':'الرئيسية','towers':'الأبراج','dishes':'الصحون','map':'الخريطة','ping':'البنج','network':'الشبكة','subs':'المشتركين','ledger':'الحسابات','logs':'السجل','settings':'الإعدادات','logout':'خروج','support':'الدعم الفني'},
      'en':{'home':'Home','towers':'Towers','dishes':'Dishes','map':'Map','ping':'Ping','network':'Network','subs':'Subs','ledger':'Ledger','logs':'Logs','settings':'Settings','logout':'Logout','support':'Support'}
    }[lang if lang in ['ar','en'] else 'ar']
    return f"""<html dir={'rtl' if lang=='ar' else 'ltr'}><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>OMAIA ISP</title>
<link rel=stylesheet href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'>
<style>
:root{{--card-min:{cfg.get('card_size','160')}px; --icon-size:{cfg.get('icon_size','44')}px; --tower-bg:{cfg.get('tower_bg','#1e2433')}; --dish-bg:{cfg.get('dish_bg','#ffffff06')}; --accent:{cfg.get('accent_color','#ffbe4d')}; --card-bg-dark:#1e2433f2; --card-bg-light:#ffffff; --text-dark:#ffffff; --text-light:#0f172a; --border-dark:#ffffff14; --border-light:#e2e8f0}}
*{{box-sizing:border-box;font-family:system-ui}}html,body{{margin:0;padding:0}}
body.dark{{--bg:radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 60%, #070a1f 100%); --card-bg:var(--card-bg-dark); --text:var(--text-dark); --border:var(--border-dark)}} 
body.light{{--bg:#eef2f7; --card-bg:var(--card-bg-light); --text:var(--text-light); --border:var(--border-light); --tower-bg:#ffffff; --dish-bg:#f8fafc}}
body{{background:var(--bg);color:var(--text);overflow-x:hidden;transition:background .2s,color .2s}}
.card{{background:var(--card-bg);color:var(--text);padding:10px;border-radius:12px;margin-bottom:8px;border:1px solid var(--border)}}
.grid-small{{display:grid;grid-template-columns:repeat(auto-fill,minmax(var(--card-min),1fr));gap:8px}}
.top{{position:fixed;top:0;left:0;right:0;height:56px;background:var(--card-bg);display:flex;align-items:center;justify-content:space-between;padding:0 12px;z-index:1003;border-bottom:1px solid var(--border)}}
.sidebar{{position:fixed;top:0;right:0;width:320px;height:100vh;height:100dvh;background:var(--card-bg);z-index:1002;padding-top:60px;padding-bottom:40px;transform:translateX(110%);transition:transform .25s ease;overflow-y:auto;overflow-x:hidden;overscroll-behavior:contain;border-left:1px solid var(--border)}}
.sidebar.active{{transform:none}}
.sidebar a{{display:flex;align-items:center;gap:12px;padding:14px 16px;margin:6px 12px;color:var(--text);text-decoration:none;border-radius:10px;background:var(--border);font-size:15px;font-weight:600}}
.sidebar a.active{{background:linear-gradient(90deg,var(--accent),#ffb020);color:#111}}
.sidebar::-webkit-scrollbar{{width:6px}} .sidebar::-webkit-scrollbar-thumb{{background:var(--accent);border-radius:10px}}
#overlay{{position:fixed;inset:0;background:#0006;z-index:1001;display:none}} #overlay.show{{display:block}}
.main{{margin-top:62px;padding:10px;min-height:90vh}}
.row{{display:flex;gap:6px;align-items:center;flex-wrap:wrap}}
.btn-gold{{background:linear-gradient(90deg,var(--accent),#ffb020);color:#111;padding:7px 12px;border:0;border-radius:8px;font-weight:700;font-size:11px;cursor:pointer}}
.mini-btn{{background:var(--border);color:var(--text);border:0;padding:5px 8px;border-radius:6px;font-size:11px;cursor:pointer}} .mini-btn-del{{background:#ef4444;color:#fff;border:0;padding:5px 8px;border-radius:6px;font-size:11px;cursor:pointer}}
.ip{{background:#000;color:var(--accent);padding:2px 6px;border-radius:5px;font-family:monospace;font-size:10px;cursor:pointer}} .badge{{background:var(--accent);color:#111;padding:2px 6px;border-radius:5px;font-size:10px;font-weight:700}}
.pingBox{{margin-top:8px;background:#000a;color:#22c55e;border:1px solid var(--border);border-radius:10px;padding:10px;font-family:monospace;min-height:36px;white-space:pre-wrap;font-size:11px;cursor:pointer}}
table{{width:100%;border-collapse:collapse}} th{{background:var(--border);padding:8px;font-size:11px;text-align:right;position:sticky;top:0}} td{{padding:8px;border-bottom:1px solid var(--border)}}
#editModal{{position:fixed;inset:0;background:#0008;display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:.2s;z-index:2000}} #editModal.show{{opacity:1;pointer-events:auto}} #editBox{{background:var(--card-bg);color:var(--text);padding:18px;border-radius:14px;width:92%;max-width:420px;transform:scale(.95);transition:.2s;border:1px solid var(--border)}} #editModal.show #editBox{{transform:scale(1)}}
input,select{{padding:9px 11px;border-radius:8px;border:1px solid var(--border);background:var(--border);color:var(--text);font-size:12px}} input:focus{{border-color:var(--accent);outline:none}}
.wa-float{{position:fixed;bottom:18px;left:18px;width:58px;height:58px;background:#25D366;color:#fff;border-radius:50%;display:flex;align-items:center;justify-content:center;text-decoration:none;z-index:999;font-size:28px;box-shadow:0 6px 20px #25D36666}}
.stat{{text-align:center;cursor:pointer}} .ico{{font-size:20px}}
</style></head><body class="{'dark' if is_dark else 'light'}">
<div id=overlay onclick="toggleSb(false)"></div>
<div class=sidebar id=sb>
<div style='padding:0 16px 14px;border-bottom:1px solid var(--border)'><b style="font-size:16px">OMAIA <span style='color:var(--accent)'>ISP</span></b><br><small style="font-size:11px;opacity:.7">{esc(cur_user.get('username') or '')} • {esc(cur_user.get('role') or '')}</small></div>
<a href="javascript:loadPage('home')" id=nav-home>🏠 <span>{tr['home']}</span></a>
<a href="javascript:loadPage('towers')" id=nav-towers>🗼 <span>{tr['towers']}</span></a>
<a href="javascript:loadPage('dishes')" id=nav-dishes>📡 <span>{tr['dishes']}</span></a>
<a href="javascript:loadPage('map')" id=nav-map>🗺️ <span>{tr['map']}</span></a>
<a href="javascript:loadPage('ping')" id=nav-ping>📶 <span>{tr['ping']}</span></a>
<a href="javascript:loadPage('network')" id=nav-network>📊 <span>{tr['network']}</span></a>
<a href="javascript:loadPage('subs')" id=nav-subs>👥 <span>{tr['subs']}</span></a>
<a href="javascript:loadPage('ledger')" id=nav-ledger>📒 <span>{tr['ledger']}</span></a>
<a href="javascript:loadPage('logs')" id=nav-logs>📜 <span>{tr['logs']}</span></a>
<a href="javascript:loadPage('settings')" id=nav-settings>⚙️ <span>{tr['settings']}</span></a>
<div style='padding:14px 16px;margin-top:12px;border-top:1px dashed var(--border)'>
<div style='font-size:12px;font-weight:700;margin-bottom:10px'>💬 {tr['support']}</div>
<div style='display:flex;gap:12px'>
<a href="{SUPPORT_WA_LINK}" target="_blank" style="flex:1;background:#25D366;color:#fff;padding:12px;border-radius:10px;display:flex;align-items:center;justify-content:center;gap:8px;text-decoration:none;font-size:22px;font-weight:700">💬</a>
<a href="{SUPPORT_INSTA_LINK}" target="_blank" style="flex:1;background:linear-gradient(45deg,#feda75,#d62976);color:#fff;padding:12px;border-radius:10px;display:flex;align-items:center;justify-content:center;gap:8px;text-decoration:none;font-size:22px;font-weight:700">📷</a>
</div>
<div style='font-size:11px;opacity:.7;margin-top:10px;text-align:center'>+{SUPPORT_WA}<br>{SUPPORT_INSTA}</div>
</div>
<a href="javascript:logoutFast()" style='margin:12px;background:#ef444422;display:flex;gap:12px;border:1px solid #ef444444'>🚪 <span>{tr['logout']}</span></a>
</div>

<div class=top>
<div class=row><span onclick="toggleSb()" style='font-size:24px;cursor:pointer;padding:6px 12px;background:var(--border);border-radius:8px'>☰</span></div>
<b style="font-size:16px">OMAIA <span style='color:var(--accent)'>ISP</span></b>
<div class=row>
<button onclick="toggleLangFast()" style="width:38px;height:38px;background:var(--border);border:1px solid var(--border);color:var(--text);border-radius:8px;cursor:pointer;font-size:16px">🌐</button>
<button onclick="toggleThemeFast()" style="width:38px;height:38px;background:var(--border);border:1px solid var(--border);color:var(--text);border-radius:8px;cursor:pointer;font-size:16px">🌓</button>
<input id=topsearch placeholder='🔍' oninput="globalSearchTop(this.value)" style='width:36px;transition:.3s;background:var(--border);border:1px solid var(--border);color:var(--text);padding:6px 10px;border-radius:8px;font-size:11px' onfocus="this.style.width='140px'" onblur="setTimeout(()=>this.style.width='36px',200)">
</div>
</div>

<div id=searchResults style='position:fixed;top:60px;right:10px;max-width:320px;width:90%;background:var(--card-bg);border:1px solid var(--border);border-radius:10px;z-index:1500;display:none;max-height:50vh;overflow:auto;font-size:11px'></div>
<div class=main id=mn>{c}</div>

<div id=editModal><div id=editBox><div class=row style='justify-content:space-between;margin-bottom:12px'><b id=editModalTitle style='font-size:14px'>نافذة</b><button onclick="closeEditModal()" style='width:30px;height:30px;border-radius:50%;background:var(--border);border:0;color:var(--text);font-size:16px'>✕</button></div><div id=editBody></div></div></div>

<a href="{SUPPORT_WA_LINK}" target="_blank" class=wa-float>💬</a>
<script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>
<script>
let cur='{v}';
function toggleSb(f){{let sb=document.getElementById('sb'),ov=document.getElementById('overlay'); let o=f!==undefined?f:!sb.classList.contains('active'); sb.classList.toggle('active',o); ov.classList.toggle('show',o);}}
async function loadPage(v,force=false,push=true){{
 if(push&&cur!==v){{try{{history.pushState({{page:v}},'', '/dash?v='+v)}}catch(e){{}}}}
 cur=v; toggleSb(false); document.querySelectorAll('.sidebar a').forEach(a=>a.classList.remove('active')); let n=document.getElementById('nav-'+v); if(n) n.classList.add('active');
 let mn=document.getElementById('mn');
 mn.innerHTML='<div class=card style="text-align:center;padding:20px">⚡ تحميل...</div>';
 try{{let r=await fetch('/api/page?v='+v,{{cache:'no-store'}}); let h=await r.text(); mn.innerHTML=h; execScripts();}}catch(e){{mn.innerHTML='<div class=card>خطأ</div>';}}
}}
function execScripts(){{document.getElementById('mn').querySelectorAll('script').forEach(o=>{{let s=document.createElement('script'); s.textContent=o.textContent; document.body.appendChild(s); o.remove();}});}}
window.closeEditModal=()=>document.getElementById('editModal').classList.remove('show');
window.openDeleteModal=function(url,id,name){{
 let b=document.getElementById("editBody");
 b.innerHTML='<div style="text-align:center;padding:10px"><div style="font-size:40px">🗑️</div><h3 style="margin:10px 0">تأكيد حذف '+ (name||'') +'؟</h3><p style="font-size:11px;opacity:.7">لا يمكن التراجع</p><div style="display:flex;gap:8px;margin-top:14px"><button onclick="closeEditModal()" style="flex:1;padding:10px;border-radius:8px;background:transparent;border:1px solid var(--border);color:var(--text)">تراجع</button><button id=delConfirmBtn style="flex:1;padding:10px;border-radius:8px;background:#ef4444;color:#fff;border:0">حذف</button></div></div>';
 document.getElementById("editModalTitle").textContent="تأكيد الحذف";
 document.getElementById("editModal").classList.add("show");
 document.getElementById("delConfirmBtn").onclick=async()=>{{
  let el=document.getElementById('tower-'+id)||document.getElementById('dish-'+id)||document.getElementById('sub-'+id)||document.getElementById('led-'+id)||document.getElementById('user-'+id)||document.getElementById('tower-acc-'+id);
  if(el){{el.style.transform='scale(.9)'; el.style.opacity='0';}}
  try{{let r=await fetch(url); let j=await r.json(); if(j.ok){{if(el) el.remove(); closeEditModal();}} else {{if(el){{el.style.transform='scale(1)'; el.style.opacity='1';}} alert(j.msg);}}}}catch(e){{if(el){{el.style.transform='scale(1)'; el.style.opacity='1';}} alert(e);}}
 }};
}};
window.toggleLangFast=async()=>{{try{{let r=await fetch('/toggle_lang'); let j=await r.json(); localStorage.setItem('lang',j.lang); location.reload();}}catch(e){{console.log(e);}}}};
window.toggleThemeFast=async()=>{{try{{let r=await fetch('/toggle_theme'); let j=await r.json(); document.body.className=j.theme; localStorage.setItem('theme',j.theme);}}catch(e){{let cur=document.body.classList.contains('dark')?'dark':'light'; let nxt=cur==='dark'?'light':'dark'; document.body.className=nxt; localStorage.setItem('theme',nxt); try{{await fetch('/toggle_theme');}}catch{{}}}}}};
window.globalSearchTop=async q=>{{let box=document.getElementById('searchResults'); if(!q||q.length<2){{box.style.display='none'; return;}} try{{let r=await fetch('/api/search?q='+encodeURIComponent(q)); let d=await r.json(); if(!d.length){{box.style.display='none'; return;}} let h=''; d.forEach(x=>{{h+='<div onclick="loadPage(\\''+x.page+'\\');document.getElementById(\\'searchResults\\').style.display=\\'none\\'" style="padding:10px;cursor:pointer;border-bottom:1px solid var(--border)"><b>'+x.title+'</b><br><small style="opacity:.6">'+x.sub+'</small></div>';}}); box.innerHTML=h; box.style.display='block';}}catch{{}}}};
window.logoutFast=async()=>{{try{{await fetch('/api/logout',{{method:'POST'}});}}catch{{}} localStorage.clear(); location.replace('/login');}};
window.addEventListener('popstate',e=>{{let v='home'; if(e.state&&e.state.page) v=e.state.page; else {{let p=new URLSearchParams(location.search); v=p.get('v')||'home';}} loadPage(v,false,false);}});
(function(){{let sz=localStorage.getItem('cardSize'); if(sz) document.documentElement.style.setProperty('--card-min',sz+'px'); let ic=localStorage.getItem('iconSize'); if(ic) document.documentElement.style.setProperty('--icon-size',ic+'px'); let th=localStorage.getItem('theme'); if(th) document.body.className=th;}})();
loadPage(cur,true,false);
</script></body></html>"""

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)),debug=False)
