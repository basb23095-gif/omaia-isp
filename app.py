# -*- coding: utf-8 -*-
from flask import Flask, request, redirect, session, jsonify, Response
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, html, ipaddress, secrets, json, socket, io, csv, datetime, re, threading, time, traceback
import concurrent.futures as _cf
try:
    import psycopg2, psycopg2.extras
    from psycopg2 import pool as pg_pool
    PG = True
except Exception:
    psycopg2 = None; pg_pool = None; PG = False
import sqlite3
from collections import defaultdict

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(days=30)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip().replace("postgres://", "postgresql://", 1)
USE_PG = bool(DATABASE_URL.startswith("postgresql://") and PG)

_pg_pool = None
_plock = threading.Lock()
_sqlite_conn = None
_slock = threading.Lock()
_cache = {}
_clock = threading.Lock()

SUPPORT_WA = "905345851045"
SUPPORT_WA_LINK = f"https://api.whatsapp.com/send?phone={SUPPORT_WA}&text=مرحبا"
SUPPORT_INSTA = "af_20_1999"
SUPPORT_INSTA_LINK = f"https://instagram.com/{SUPPORT_INSTA}"

def init_pool():
    global _pg_pool, USE_PG
    if not USE_PG or not pg_pool: return
    with _plock:
        if _pg_pool: return
        try:
            _pg_pool = pg_pool.ThreadedConnectionPool(3, 20, dsn=DATABASE_URL, sslmode='require', connect_timeout=5)
        except Exception:
            _pg_pool = None; USE_PG = False
init_pool()

def esc(s):
    return html.escape(str(s or ''), quote=True)

def esc_js(s):
    # آمن للـ JS داخل onclick
    return str(s or '').replace('\\', '\\\\').replace("'", "\\'").replace('"', '\\"').replace('\n',' ').replace('\r',' ')[:200]

def get_conn():
    global USE_PG, _sqlite_conn
    if USE_PG and _pg_pool:
        try:
            c = _pg_pool.getconn()
            if getattr(c, 'closed', 1) == 0: return c
            _pg_pool.putconn(c, close=True)
        except Exception: pass
        try: return psycopg2.connect(DATABASE_URL, sslmode='require', connect_timeout=5)
        except Exception: USE_PG = False
    elif USE_PG:
        try: return psycopg2.connect(DATABASE_URL, sslmode='require', connect_timeout=2)
        except Exception: USE_PG = False
    with _slock:
        if _sqlite_conn is None:
            _sqlite_conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), "omia.db"), check_same_thread=False, timeout=15, isolation_level=None)
            _sqlite_conn.row_factory = sqlite3.Row
            try: _sqlite_conn.execute("PRAGMA journal_mode=WAL;")
            except Exception: pass
        return _sqlite_conn

def put_conn(c):
    if not c: return
    if USE_PG and _pg_pool and hasattr(c, 'closed'):
        try:
            if c.closed == 0: _pg_pool.putconn(c)
            else: _pg_pool.putconn(c, close=True)
        except Exception:
            try: c.close()
            except Exception: pass
    elif USE_PG and hasattr(c, 'closed'):
        try: c.close()
        except Exception: pass

def qall(q, a=()):
    cn = None
    try:
        cn = get_conn()
        if USE_PG and hasattr(cn, 'cursor'):
            cur = cn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(q.replace("?", "%s"), a)
            r = [dict(x) for x in cur.fetchall()]; cur.close(); put_conn(cn); return r
        else:
            with _slock: return [dict(x) for x in cn.execute(q, a).fetchall()]
    except Exception:
        if cn and USE_PG and hasattr(cn, 'closed'):
            try: put_conn(cn)
            except Exception: pass
        return []

def qone(q, a=()):
    r = qall(q, a); return r[0] if r else None

def qexec(q, a=()):
    cn = None
    try:
        cn = get_conn()
        if USE_PG and hasattr(cn, 'cursor'):
            cur = cn.cursor(); cur.execute(q.replace("?", "%s"), a); cn.commit(); cur.close(); put_conn(cn)
        else:
            with _slock: cn.execute(q, a); cn.commit()
        return True
    except Exception as e:
        if cn and USE_PG and hasattr(cn, 'closed'):
            try: cn.rollback(); put_conn(cn)
            except Exception: pass
        print(f"qexec err {e}")
        return False

def cache_get(k, ttl):
    with _clock:
        v = _cache.get(k)
        if v and (time.time() - v[0] < ttl): return v[1]
    return None

def cache_set(k, val):
    with _clock: _cache[k] = (time.time(), val)

def cache_invalidate(keys=None):
    with _clock:
        if keys:
            for k in keys: _cache.pop(k, None)
        else: _cache.clear()

def get_data(req):
    try:
        if req.is_json:
            j = req.get_json(silent=True)
            if j: return j
    except Exception: pass
    return req.form or req.args or {}

def add_log(phone, action, target='', detail='', username=''):
    try:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not username:
            try: username = session.get('username') or session.get('phone') or phone or 'sys'
            except Exception: username = phone or 'sys'
        ok = qexec("INSERT INTO logs(user_phone,username,action,target,detail,time) VALUES(?,?,?,?,?,?)",(phone or 'sys', username, action, str(target)[:300], str(detail)[:500], now))
        if not ok:
            qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)",(phone or 'sys', action, str(detail or target)[:500], now))
        cache_invalidate(['counts','logs_preview','all_data','towers_list','logs','stats'])
    except Exception as e:
        print(f"add_log err {e}")

def get_counts():
    cached = cache_get('counts', 10)
    if cached: return cached
    try:
        row = qone("SELECT (SELECT COUNT(*) FROM subs) as ns, (SELECT COUNT(*) FROM dish_ips) as nd, (SELECT COUNT(*) FROM towers) as nt, (SELECT COUNT(*) FROM ledger) as nl")
        res = (row.get('ns',0), row.get('nd',0), row.get('nt',0), row.get('nl',0)) if row else (0,0,0,0)
        cache_set('counts', res)
        return res
    except Exception:
        return (0,0,0,0)

def init_db():
    ss = [
        "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,username TEXT)",
        "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,note TEXT)",
        "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,amount REAL,note TEXT,currency TEXT)",
        "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,dish_name TEXT,tower_id INTEGER)",
        "CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,area TEXT,lat REAL,lng REAL,created_at TEXT)",
        "CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,user_phone TEXT,username TEXT,action TEXT,target TEXT,detail TEXT,time TEXT)",
        "CREATE TABLE IF NOT EXISTS system_config(key TEXT PRIMARY KEY,value TEXT)"
    ]
    if USE_PG: ss = [s.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY") for s in ss]
    for s in ss: qexec(s)
    for idx in [
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_dish_ip_unique ON dish_ips(ip)",
        "CREATE INDEX IF NOT EXISTS idx_dish_tower ON dish_ips(tower_id)",
        "CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)",
        "CREATE INDEX IF NOT EXISTS idx_logs_time ON logs(time DESC)"
    ]:
        try: qexec(idx)
        except Exception: pass
    for al in ["ALTER TABLE dish_ips ADD COLUMN tower_id INTEGER","ALTER TABLE towers ADD COLUMN created_at TEXT","ALTER TABLE logs ADD COLUMN username TEXT","ALTER TABLE logs ADD COLUMN target TEXT"]:
        try: qexec(al)
        except Exception: pass
    if not qone("SELECT * FROM users WHERE phone=?", ('admin',)): qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)", ('admin', generate_password_hash('admin2024', method='pbkdf2:sha256:150000'), 'manager', 'مدير النظام'))
    if not qone("SELECT * FROM users WHERE phone=?", ('05344851045',)): qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)", ('05344851045', generate_password_hash('admin2024', method='pbkdf2:sha256:150000'), 'manager', 'المدير الاساسي'))
    if not qone("SELECT * FROM towers WHERE name=?", ('نقطة حماة الرئيسية',)): qexec("INSERT INTO towers(name,area,lat,lng,created_at) VALUES(?,?,?,?,?)", ('نقطة حماة الرئيسية', 'حماة', 35.1318, 36.7578, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
init_db()

def login_required(f):
    @wraps(f)
    def w(*a, **kw):
        if not session.get('phone'):
            if request.path.startswith('/api/') or request.is_json: return jsonify(ok=False, msg='غير مسجل'), 401
            return redirect('/login')
        return f(*a, **kw)
    return w

def is_manager(): return (session.get('role') or '') == 'manager'
def role_required_manager(f):
    @wraps(f)
    def w(*a, **kw):
        if not is_manager(): return jsonify(ok=False, msg='ممنوع'), 403
        return f(*a, **kw)
    return w

def is_valid_host(h):
    h = (h or '').strip()
    if not h or len(h) > 253: return False
    try:
        ipaddress.ip_address(h); return True
    except Exception:
        if ' ' in h or '..' in h: return False
        if re.match(r'^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', h) and len(h) >= 3: return True
        if re.match(r'^[a-zA-Z0-9.-]+$', h) and '.' in h: return True
        return False
def is_valid_ip(ip): return is_valid_host(ip)

@app.after_request
def after(r):
    r.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    r.headers['Pragma'] = 'no-cache'
    return r

@app.route('/ping')
def ping(): return jsonify(ok=True, use_pg=USE_PG)

@app.route('/api/ping')
@login_required
def api_ping():
    ip = request.args.get('ip','').strip()
    if not is_valid_host(ip): return jsonify(ok=False, out='IP غير صالح')
    def try_port(p):
        s=None
        try:
            s=socket.socket(); s.settimeout(0.4)
            if s.connect_ex((ip,p))==0: return p
        except Exception: pass
        finally:
            try:
                if s: s.close()
            except Exception: pass
        return None
    try:
        with _cf.ThreadPoolExecutor(max_workers=5) as ex:
            futs=[ex.submit(try_port,p) for p in [80,443,8080,8291,22]]
            for f in _cf.as_completed(futs, timeout=1.0):
                r=f.result()
                if r: return jsonify(ok=True, out=ip+':'+str(r)+' Online')
    except Exception: pass
    return jsonify(ok=False, out=ip+' Offline')

@app.route('/api/ping_batch', methods=['POST'])
@login_required
def api_ping_batch():
    d=get_data(request)
    ips=d.get('ips') or []
    if not isinstance(ips, list): ips=[ips]
    ips=[str(x).strip() for x in ips if is_valid_host(str(x).strip())][:40]
    def check(ip):
        try:
            s=socket.socket(); s.settimeout(0.6)
            ok=s.connect_ex((ip,80))==0 or s.connect_ex((ip,443))==0
            s.close()
            return {'ip':ip,'ok':ok}
        except Exception: return {'ip':ip,'ok':False}
    results=[]
    try:
        with _cf.ThreadPoolExecutor(max_workers=20) as ex:
            results=list(ex.map(check, ips))
    except Exception: results=[{'ip':ip,'ok':False} for ip in ips]
    return jsonify(ok=True, results=results)

@app.route('/api/stats')
@login_required
def api_stats():
    ns,nd,nt,nl=get_counts()
    logs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 15")
    return jsonify(ok=True, stats=dict(subs=ns, dishes=nd, towers=nt, ledger=nl), logs=logs)

@app.route('/api/towers_list')
@login_required
def api_towers_list():
    towers=qall("SELECT id,name,area,lat,lng FROM towers ORDER BY name ASC")
    return jsonify(ok=True, towers=towers)

@app.route('/toggle_lang')
@login_required
def toggle_lang():
    cur = session.get('lang','ar'); session['lang']='en' if cur=='ar' else 'ar'
    add_log(session.get('phone'), 'تغيير لغة', session['lang'], '', session.get('username'))
    return jsonify(ok=True, lang=session['lang'])

@app.route('/toggle_theme')
@login_required
def toggle_theme_fast():
    cur = session.get('theme','dark'); session['theme']='light' if cur=='dark' else 'dark'
    return jsonify(ok=True, theme=session['theme'])

@app.route('/api/set_config', methods=['POST'])
@login_required
@role_required_manager
def set_config():
    d=get_data(request)
    k=(d.get('key') or '').strip();v=(d.get('value') or '').strip()
    if not k: return jsonify(ok=False),400
    if USE_PG: qexec("INSERT INTO system_config(key,value) VALUES(?,?) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",(k,v))
    else: qexec("INSERT OR REPLACE INTO system_config(key,value) VALUES(?,?)",(k,v))
    return jsonify(ok=True)

@app.route('/api/login_public', methods=['POST'])
def api_login_public():
    try:
        d=get_data(request)
        uin=str(d.get('userin') or d.get('user') or '').strip()
        pw=str(d.get('password') or '').strip()
        u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
        if u and check_password_hash(u.get('password',''),pw):
            session.clear()
            session['phone']=u['phone']
            session['username']=u.get('username') or u['phone']
            session['role']=u.get('role') or 'tech'
            session.permanent=True
            add_log(u['phone'],'دخول',uin,'دخول المستخدم '+uin, u.get('username') or uin)
            return jsonify(ok=True)
        return jsonify(ok=False,msg='خطأ في البيانات'),401
    except Exception as e:
        return jsonify(ok=False,msg=str(e)),500

@app.route('/api/export/<tbl>')
@login_required
def api_export(tbl):
    add_log(session.get('phone'),'تصدير',tbl,'',session.get('username'))
    output=io.StringIO(); output.write('\ufeff'); w=csv.writer(output)
    if tbl=='dishes':
        rows=qall("SELECT * FROM dish_ips ORDER BY location ASC, dish_name ASC"); w.writerow(['ID','اسم','IP','موقع','tower_id'])
        for r in rows: w.writerow([r.get('id',''), r.get('dish_name',''), r.get('ip',''), r.get('location',''), r.get('tower_id','')]); fname='dishes.csv'
    elif tbl=='towers':
        rows=qall("SELECT * FROM towers ORDER BY name ASC"); w.writerow(['ID','اسم','منطقة','lat','lng'])
        for r in rows: w.writerow([r.get('id',''), r.get('name',''), r.get('area',''), r.get('lat',''), r.get('lng','')]); fname='towers.csv'
    else:
        rows=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 2000"); w.writerow(['ID','وقت','المستخدم','عمل','الهدف','تفصيل'])
        for r in rows: w.writerow([r.get('id',''), r.get('time',''), r.get('user_phone',''), r.get('action',''), r.get('target',''), r.get('detail','')]); fname='logs.csv'
    return Response(output.getvalue(), mimetype='text/csv; charset=utf-8', headers={'Content-Disposition': f'attachment; filename={fname}'})

@app.route('/api/clear_logs', methods=['POST'])
@login_required
@role_required_manager
def clear_logs(): qexec("DELETE FROM logs"); add_log(session.get('phone'),'مسح السجل','مسح','',session.get('username')); return jsonify(ok=True)

@app.route('/api/add_dish_to_tower', methods=['POST'])
@login_required
def add_dish_to_tower():
    try:
        d=get_data(request); ip=(d.get('ip') or '').strip(); name=(d.get('dish_name') or '').strip(); loc=(d.get('location') or '').strip(); tid=d.get('tower_id')
        if not is_valid_host(ip): return jsonify(ok=False,msg='IP غير صالح'),400
        if USE_PG: ok=qexec("INSERT INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?) ON CONFLICT (ip) DO UPDATE SET dish_name=EXCLUDED.dish_name, location=EXCLUDED.location, tower_id=EXCLUDED.tower_id",(ip,loc,name,int(tid) if tid and str(tid).isdigit() and int(tid)!=0 else None))
        else: ok=qexec("INSERT OR REPLACE INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?)",(ip,loc,name,int(tid) if tid and str(tid).isdigit() and int(tid)!=0 else None))
        if ok: add_log(session.get('phone'),'إضافة صحن',name or ip,"IP:"+ip,session.get('username')); cache_invalidate()
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
        dishes=qall("SELECT * FROM dish_ips WHERE tower_id IS NULL ORDER BY dish_name ASC LIMIT 100")
        return jsonify(ok=True,tower=dict(id=0,name='بدون برج',area=''),dishes=dishes)
    t=qone("SELECT * FROM towers WHERE id=?",(id,))
    if not t: return jsonify(ok=False,msg='غير موجود'),404
    dishes=qall("SELECT * FROM dish_ips WHERE tower_id=? ORDER BY dish_name ASC LIMIT 200",(id,))
    return jsonify(ok=True,tower=t,dishes=dishes)

@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login')
def login_page():
    return """<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>OMAIA ISP</title>
<style>*{box-sizing:border-box;font-family:system-ui}body{margin:0;min-height:100vh;background:radial-gradient(120% 120% at 10% 10%,#1a2344,#0a0e2a 60%);display:flex;align-items:center;justify-content:center;color:#fff}
.card{background:rgba(30,36,51,0.85);backdrop-filter:blur(20px);border:1px solid #ffffff18;padding:22px;border-radius:16px;width:92%;max-width:360px;box-shadow:0 20px 50px #0006;transition:transform 0.3s ease}
.card:hover{transform:translateY(-2px)}input{width:100%;padding:12px;margin:7px 0;background:#0f1424;border:1px solid #ffffff22;color:#fff;border-radius:10px}input:focus{border-color:#ffbe4d;outline:none}
.btn{width:100%;padding:12px;border:0;border-radius:10px;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:800;cursor:pointer;transition:all 0.15s}
.btn:active{transform:scale(0.97)}#topLoader{position:fixed;top:0;left:0;width:0%;height:3px;background:linear-gradient(90deg,#ffbe4d,#ff6b6b);z-index:9999;transition:width 0.3s}</style></head><body>
<div id=topLoader></div><div class=card><div style='text-align:center;font-weight:900;font-size:24px;margin-bottom:12px'>OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<form id=loginForm><input name=userin placeholder='اسم المستخدم' required autofocus><input name=password type=password placeholder='كلمة المرور' required>
<button class=btn id=loginBtn>دخول ⚡</button><div id=msg style='text-align:center;color:#ff6b6b;font-size:11px;min-height:14px;margin-top:8px'></div></form></div>
<script>
function topLoad(p){var t=document.getElementById('topLoader'); if(t){t.style.width=p+'%'; if(p>=100) setTimeout(()=>t.style.width='0%',500);}}
document.getElementById('loginForm').addEventListener('submit', async e => {
  e.preventDefault(); var b=document.getElementById('loginBtn'), m=document.getElementById('msg'); b.textContent='...'; b.disabled=true; topLoad(30);
  try { var fd=new FormData(e.target); topLoad(70); var res=await fetch('/api/login_public',{method:'POST',body:fd}); var j=await res.json();
  if(j.ok){topLoad(100); location.replace('/dash?v=home');} else {m.textContent=j.msg; b.textContent='دخول ⚡'; b.disabled=false; topLoad(0);}
  } catch(err){m.textContent='خطأ شبكة'; b.textContent='دخول ⚡'; b.disabled=false; topLoad(0);}
});
</script></body></html>"""

@app.route('/logout')
def lo(): session.clear(); return redirect('/login')
@app.route('/api/logout', methods=['POST'])
def api_logout(): session.clear(); return jsonify(ok=True)

@app.route('/dash')
@login_required
def dash(): v = request.args.get('v', 'home'); return layout('<div class=card>...</div>', v)

@app.route('/api/page')
@login_required
def ap():
    try: return page_content(request.args.get('v', 'home'))
    except Exception as e: traceback.print_exc(); return "<div class=card>خطأ "+esc(str(e))+"</div>", 500

@app.route('/add_dish', methods=['POST'])
@login_required
def ad():
    try:
        d=get_data(request); ip=(d.get('ip') or '').strip(); name=(d.get('dish_name') or '').strip(); loc=(d.get('location') or '').strip(); tid=d.get('tower_id')
        if not is_valid_host(ip): return jsonify(ok=False, msg='IP غير صالح'), 400
        if USE_PG: ok=qexec("INSERT INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?) ON CONFLICT (ip) DO UPDATE SET dish_name=EXCLUDED.dish_name, location=EXCLUDED.location, tower_id=EXCLUDED.tower_id",(ip,loc,name,int(tid) if tid and str(tid).isdigit() and int(tid)!=0 else None))
        else: ok=qexec("INSERT OR REPLACE INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?)",(ip,loc,name,int(tid) if tid and str(tid).isdigit() and int(tid)!=0 else None))
        if ok: add_log(session.get('phone'),'إضافة صحن',name or ip,"IP:"+ip,session.get('username')); cache_invalidate()
        return jsonify(ok=ok)
    except Exception as e: return jsonify(ok=False,msg=str(e)),500

@app.route('/edit_dish/<int:i>', methods=['POST'])
@login_required
def ed(i):
    d=get_data(request)
    ok=qexec("UPDATE dish_ips SET dish_name=?,ip=?,location=?,tower_id=? WHERE id=?",(d.get('dish_name',''),d.get('ip',''),d.get('location',''),d.get('tower_id') or None,i))
    if ok: add_log(session.get('phone'),'تعديل صحن',"صحن "+str(i),"",session.get('username'))
    return jsonify(ok=ok)

@app.route('/del_dish/<int:i>', methods=['POST','GET'])
@login_required
def dd(i):
    if not is_manager(): return jsonify(ok=False,msg='ممنوع'),403
    info=qone("SELECT dish_name,ip FROM dish_ips WHERE id=?",(i,))
    ok=qexec("DELETE FROM dish_ips WHERE id=?",(i,))
    if ok:
        nm = info.get('dish_name','') if info else str(i)
        add_log(session.get('phone'),'حذف صحن',nm, info.get('ip','') if info else '', session.get('username')); cache_invalidate()
    return jsonify(ok=ok)

@app.route('/add_tower', methods=['POST'])
@login_required
def at():
    try:
        d=get_data(request); la=float(d.get('lat') or 35.1318); ln=float(d.get('lng') or 36.7578)
        ok=qexec("INSERT INTO towers(name,area,lat,lng,created_at) VALUES(?,?,?,?,?)",(d.get('name','كرت'),d.get('area',''),la,ln,datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        if ok: add_log(session.get('phone'),'إضافة برج',d.get('name',''),"",session.get('username')); cache_invalidate()
        return jsonify(ok=ok)
    except Exception as e: return jsonify(ok=False,msg=str(e)),500

@app.route('/del_tower/<int:i>', methods=['POST','GET'])
@login_required
def dt(i):
    if not is_manager(): return jsonify(ok=False,msg='ممنوع'),403
    t=qone("SELECT name FROM towers WHERE id=?",(i,))
    qexec("UPDATE dish_ips SET tower_id=NULL WHERE tower_id=?",(i,)); ok=qexec("DELETE FROM towers WHERE id=?",(i,))
    if ok: add_log(session.get('phone'),'حذف برج',t.get('name','') if t else str(i),"",session.get('username')); cache_invalidate()
    return jsonify(ok=ok)

@app.route('/edit_tower/<int:i>', methods=['POST'])
@login_required
def et(i):
    d=get_data(request); la=float(d.get('lat') or 35.1318); ln=float(d.get('lng') or 36.7578)
    ok=qexec("UPDATE towers SET name=?,area=?,lat=?,lng=? WHERE id=?",(d.get('name',''),d.get('area',''),la,ln,i))
    if ok: add_log(session.get('phone'),'تعديل برج',"برج "+str(i),"",session.get('username'))
    return jsonify(ok=ok)

@app.route('/add_sub', methods=['POST'])
@login_required
def asub():
    d=get_data(request); ok=qexec("INSERT INTO subs(name,phone,note) VALUES(?,?,?)",(d.get('name',''),d.get('phone',''),d.get('note','')))
    if ok: add_log(session.get('phone'),'إضافة مشترك',d.get('name',''),"",session.get('username')); cache_invalidate()
    return jsonify(ok=ok)

@app.route('/del_sub/<int:i>', methods=['POST','GET'])
@login_required
def dsub(i):
    if not is_manager(): return jsonify(ok=False),403
    s=qone("SELECT name FROM subs WHERE id=?",(i,))
    ok=qexec("DELETE FROM subs WHERE id=?",(i,))
    if ok: add_log(session.get('phone'),'حذف مشترك',s.get('name','') if s else str(i),"",session.get('username')); cache_invalidate()
    return jsonify(ok=ok)

@app.route('/edit_sub/<int:i>', methods=['POST'])
@login_required
def esub(i):
    d=get_data(request); ok=qexec("UPDATE subs SET name=?,phone=?,note=? WHERE id=?",(d.get('name',''),d.get('phone',''),d.get('note',''),i))
    if ok: add_log(session.get('phone'),'تعديل مشترك',"مشترك "+str(i),"",session.get('username'))
    return jsonify(ok=ok)

@app.route('/add_ledger', methods=['POST'])
@login_required
def al():
    d=get_data(request)
    try: amt=float(d.get('amount') or 0)
    except Exception: amt=0
    ok=qexec("INSERT INTO ledger(name,amount,note,currency) VALUES(?,?,?,?)",(d.get('name',''),amt,d.get('note',''),d.get('currency','USD')))
    if ok: add_log(session.get('phone'),'إضافة حساب',d.get('name',''),"",session.get('username')); cache_invalidate()
    return jsonify(ok=ok)

@app.route('/del_ledger/<int:i>', methods=['POST','GET'])
@login_required
def dll(i):
    if not is_manager(): return jsonify(ok=False),403
    ok=qexec("DELETE FROM ledger WHERE id=?",(i,))
    if ok: add_log(session.get('phone'),'حذف حساب',"حساب "+str(i),"",session.get('username')); cache_invalidate()
    return jsonify(ok=ok)

@app.route('/edit_ledger/<int:i>', methods=['POST'])
@login_required
def el(i):
    d=get_data(request)
    try: amt=float(d.get('amount') or 0)
    except Exception: amt=0
    ok=qexec("UPDATE ledger SET name=?,amount=?,note=?,currency=? WHERE id=?",(d.get('name',''),amt,d.get('note',''),d.get('currency','USD'),i))
    if ok: add_log(session.get('phone'),'تعديل حساب',"حساب "+str(i),"",session.get('username'))
    return jsonify(ok=ok)

@app.route('/add_user', methods=['POST'])
@login_required
@role_required_manager
def au():
    d=get_data(request); ph=(d.get('phone') or d.get('user_field','')).strip()
    if not ph: return jsonify(ok=False,msg='رقم مطلوب'),400
    if qone("SELECT * FROM users WHERE phone=?",(ph,)): return jsonify(ok=False,msg='موجود مسبقا'),400
    ok=qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",(ph,generate_password_hash(d.get('password','1234'), method='pbkdf2:sha256:150000'),d.get('role','tech'),ph))
    if ok: add_log(session.get('phone'),'إضافة يوزر',ph,"",session.get('username'))
    return jsonify(ok=ok)

@app.route('/edit_user', methods=['POST'])
@login_required
@role_required_manager
def eu():
    d=get_data(request); old=d.get('old_phone','').strip(); new_ph=(d.get('phone') or '').strip(); new_role=d.get('role','tech')
    if not old: return jsonify(ok=False,msg='خطأ'),400
    if old!=new_ph and qone("SELECT * FROM users WHERE phone=?",(new_ph,)): return jsonify(ok=False,msg='موجود'),400
    new_pass=d.get('password','').strip()
    if new_pass: ok=qexec("UPDATE users SET phone=?,username=?,role=?,password=? WHERE phone=?",(new_ph,new_ph,new_role,generate_password_hash(new_pass, method='pbkdf2:sha256:150000'),old))
    else: ok=qexec("UPDATE users SET phone=?,username=?,role=? WHERE phone=?",(new_ph,new_ph,new_role,old))
    if ok: add_log(session.get('phone'),'تعديل يوزر',new_ph,"",session.get('username'))
    return jsonify(ok=ok)

@app.route('/del_user/<ph>', methods=['POST','GET'])
@login_required
@role_required_manager
def du(ph):
    if ph=='05344851045': return jsonify(ok=False,msg='ممنوع'),400
    ok=qexec("DELETE FROM users WHERE phone=?",(ph,))
    if ok: add_log(session.get('phone'),'حذف يوزر',ph,"",session.get('username'))
    return jsonify(ok=ok)

@app.route('/change_pass', methods=['POST'])
@login_required
def cp():
    d=get_data(request); np=(d.get('newpass') or '').strip()
    if not np: return jsonify(ok=False,msg='فارغة'),400
    ok=qexec("UPDATE users SET password=? WHERE phone=?",(generate_password_hash(np, method='pbkdf2:sha256:150000'),session.get('phone')))
    if ok: add_log(session.get('phone'),'تغيير باسورد',session.get('phone') or '',"",session.get('username'))
    return jsonify(ok=ok)

def page_content(v):
    if v == 'home':
        ns,nd,nt,nl=get_counts()
        logs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 10")
        lh_parts=[]
        for l in logs:
            t = esc(l.get('time',''))
            act = esc(l.get('action',''))
            user = esc(l.get('username') or l.get('user_phone',''))
            det = esc(l.get('detail',''))
            lh_parts.append('<tr><td>'+t+'</td><td><span class=badge>'+act+'</span></td><td>'+user+'</td><td>'+det+'</td></tr>')
        lh = "".join(lh_parts) if lh_parts else "<tr><td colspan=4>لا يوجد سجل</td></tr>"
        return '<div style="max-width:1100px;margin:0 auto"><div class=grid-small><div class="card small stat" onclick="event.preventDefault(); loadPage(\'subs\')"><div class=ico>👥</div><h4>مشتركين</h4><h2>'+str(ns)+'</h2></div><div class="card small stat" onclick="event.preventDefault(); loadPage(\'dishes\')"><div class=ico>📡</div><h4>صحون</h4><h2>'+str(nd)+'</h2></div><div class="card small stat" onclick="event.preventDefault(); loadPage(\'towers\')"><div class=ico>🗼</div><h4>أبراج</h4><h2>'+str(nt)+'</h2></div><div class="card small stat" onclick="event.preventDefault(); loadPage(\'ledger\')"><div class=ico>📒</div><h4>حسابات</h4><h2>'+str(nl)+'</h2></div></div><div class=card style="margin-top:10px"><div style="display:flex;justify-content:space-between"><b>📜 السجل</b><button class=btn-gold onclick="event.preventDefault(); loadPage(\'logs\')">الكل</button></div><table style="width:100%;margin-top:8px"><thead><tr><th>وقت</th><th>عمل</th><th>يوزر</th><th>تفصيل</th></tr></thead><tbody>'+lh+'</tbody></table></div></div>'

    if v == 'towers':
        rs=qall("SELECT t.id,t.name,t.area,t.lat,t.lng, COUNT(d.id) as cnt FROM towers t LEFT JOIN dish_ips d ON d.tower_id=t.id GROUP BY t.id,t.name,t.area,t.lat,t.lng ORDER BY t.name ASC")
        cards_parts=[]
        for t in rs:
            tid=t.get('id'); tname=esc(t.get('name') or 'برج '+str(tid)); tarea=esc(t.get('area') or ''); lat=t.get('lat') or 35.1318; lng=t.get('lng') or 36.7578; cnt=t.get('cnt') or 0
            name_js=esc_js(t.get('name') or '')
            card_html='<div class="card tower-card" id="tower-'+str(tid)+'" data-name="'+tname.lower()+'"><div style="display:flex;justify-content:space-between;align-items:center"><div style="display:flex;gap:10px;align-items:center"><div style="width:44px;height:44px;background:linear-gradient(135deg,var(--accent,#ffbe4d),#ffb020);border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:20px">🗼</div><div><b style="font-size:14px">'+tname+'</b><div style="font-size:11px;color:#94a3b8;margin-top:2px">📍 '+tarea+'</div></div></div><span class=badge>'+str(cnt)+' IP</span></div><div style="display:flex;gap:6px;margin-top:10px"><button class="btn-circle edit" onclick="event.preventDefault(); openEditTowerPage('+str(tid)+')">✏ تعديل</button><button class="btn-circle del" onclick="event.preventDefault(); openDeleteModal(\'/del_tower/'+str(tid)+'\','+str(tid)+',\''+name_js+'\')">🗑 حذف</button></div></div>'
            cards_parts.append(card_html)
        cards="".join(cards_parts)
        return '<div style="max-width:1100px;margin:0 auto"><div class=card style="display:flex;justify-content:space-between;align-items:center"><b>🗼 الأبراج</b><button class=btn-gold onclick="event.preventDefault(); openNewTowerPage()">+ برج</button></div><div class=grid-small id=towersGrid>'+cards+'</div></div><script>window.openNewTowerPage=function(){var b=document.getElementById("editBody"); b.innerHTML=\'<input id=nt_name placeholder="اسم البرج"><input id=nt_area placeholder="المنطقة"><div class=row><input id=nt_lat value="35.1318"><input id=nt_lng value="36.7578"></div><button class=btn-gold onclick="event.preventDefault(); saveNewTowerPage()" style="width:100%">حفظ</button>\'; document.getElementById("editModalTitle").textContent="إضافة برج"; document.getElementById("editModal").classList.add("show");}; window.saveNewTowerPage=async function(){var d={name:document.getElementById("nt_name").value, area:document.getElementById("nt_area").value, lat:document.getElementById("nt_lat").value, lng:document.getElementById("nt_lng").value}; if(!d.name) return; var r=await fetch("/add_tower",{method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(d)}); var j=await r.json(); if(j.ok){closeEditModal(); loadPage(\'towers\', true);}}; window.openEditTowerPage=async function(id){try{var r=await fetch(\'/api/tower_detail/\'+id); var j=await r.json(); if(!j.ok) return; var t=j.tower; var b=document.getElementById("editBody"); b.innerHTML=\'<input id=et_name value="\'+t.name+\'"><input id=et_area value="\'+(t.area||"")+\'"><div class=row><input id=et_lat value="\'+(t.lat||"")+\'"><input id=et_lng value="\'+(t.lng||"")+\'"></div><button class=btn-gold onclick="event.preventDefault(); saveTowerPage(\'+id+\')" style="width:100%">حفظ</button>\'; document.getElementById("editModalTitle").textContent="تعديل برج"; document.getElementById("editModal").classList.add("show");}catch(e){alert(e);}}; window.saveTowerPage=async function(id){var d={name:document.getElementById("et_name").value, area:document.getElementById("et_area").value, lat:document.getElementById("et_lat").value, lng:document.getElementById("et_lng").value}; var r=await fetch("/edit_tower/"+id,{method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(d)}); var j=await r.json(); if(j.ok){closeEditModal(); loadPage(\'towers\', true);}};</script>'

    if v == 'dishes':
        towers=qall("SELECT t.id, t.name, t.area, t.lat, t.lng, (SELECT COUNT(*) FROM dish_ips WHERE tower_id=t.id) as cnt FROM towers t ORDER BY t.name ASC")
        no_cnt=(qone("SELECT COUNT(*) as c FROM dish_ips WHERE tower_id IS NULL") or {}).get('c',0)
        parts=[]
        for t in towers:
            tid=t.get('id'); tname=esc(t.get('name') or 'برج '+str(tid)); tarea=esc(t.get('area') or ''); cnt=t.get('cnt') or 0; name_js=esc_js(t.get('name') or '')
            html_block='<div class="card tower-accordion" id="tower-acc-'+str(tid)+'" data-loaded="0"><div class="tower-accordion-header" onclick="event.preventDefault(); toggleAccordionLazy('+str(tid)+')" style="padding:14px;display:flex;justify-content:space-between;align-items:center;cursor:pointer"><div style="display:flex;align-items:center;gap:12px;flex:1"><div style="width:44px;height:44px;background:linear-gradient(135deg,var(--accent,#ffbe4d),#ffb020);border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:20px">🗼</div><div><b style="font-size:14px">'+tname+'</b><div style="font-size:11px;color:#94a3b8">📍 '+tarea+'</div></div></div><div style="display:flex;gap:8px;align-items:center"><span class=badge>'+str(cnt)+' IP</span><button class="btn-circle edit" onclick="event.stopPropagation(); openEditTowerPage('+str(tid)+')" title="تعديل">✏</button><button class="btn-circle del" onclick="event.stopPropagation(); openDeleteModal(\'/del_tower/'+str(tid)+'\','+str(tid)+',\''+name_js+'\')" title="حذف">🗑</button><div id="arrow-'+str(tid)+'">▼</div></div></div><div class="tower-accordion-body" id="tower-body-'+str(tid)+'" style="display:none;background:#0f1424"><div id="tower-content-'+str(tid)+'" style="padding:12px">جاري التحميل...</div></div></div>'
            parts.append(html_block)
        parts.append('<div class="card tower-accordion" id="tower-acc-0" data-loaded="0" style="border:1px dashed #ef444488"><div class="tower-accordion-header" onclick="event.preventDefault(); toggleAccordionLazy(0)" style="padding:14px;display:flex;justify-content:space-between;align-items:center;cursor:pointer"><div style="display:flex;gap:10px;align-items:center"><div style="width:44px;height:44px;background:#ef4444;border-radius:10px;display:flex;align-items:center;justify-content:center">⚠</div><div><b>بدون برج</b><div style="font-size:11px;color:#94a3b8">'+str(no_cnt)+' IP</div></div></div><span style="background:#ef4444;color:#fff;padding:3px 8px;border-radius:6px;font-size:11px">'+str(no_cnt)+' IP</span></div><div class="tower-accordion-body" id="tower-body-0" style="display:none;background:#0f1424"><div id="tower-content-0" style="padding:12px"></div></div></div>')
        accordion_html="".join(parts)
        return '<div style="max-width:1100px;margin:0 auto"><div class=card style="display:flex;justify-content:space-between;align-items:center"><b>📡 الصحون</b><button class=btn-gold onclick="event.preventDefault(); openNewTowerAcc()">+ برج</button></div><div id=accordionContainer style="display:flex;flex-direction:column;gap:10px;margin-top:12px">'+accordion_html+'</div></div><div id=addDishModal style="position:fixed;inset:0;background:#000a;display:none;align-items:center;justify-content:center;z-index:2500"><div style="background:var(--card-bg);width:95%;max-width:400px;border-radius:14px;padding:18px"><b id=addDishTitle>+ صحن</b><input id=mName placeholder="اسم"><input id=mIp placeholder="IP"><input id=mLoc placeholder="موقع"><input type=hidden id=mTid><div class=row><button onclick="event.preventDefault(); closeAddDishModal()">إلغاء</button><button onclick="event.preventDefault(); saveDish()" class=btn-gold>حفظ</button></div></div></div><script>window.DISH_CACHE={}; window.openInChrome=function(ip){if(!ip) return; var url=ip; if(!url.startsWith(\'http\')) url=\'http://\'+url; window.open(url, \'_blank\');}; window.toggleAccordionLazy=async function(tid){var body=document.getElementById(\'tower-body-\'+tid); var acc=document.getElementById(\'tower-acc-\'+tid); var isHidden=!body.classList.contains(\'open\'); if(isHidden){body.style.display=\'block\'; body.classList.add(\'open\'); if(acc.dataset.loaded===\'0\'){var content=document.getElementById(\'tower-content-\'+tid); try{var r=await fetch(\'/api/tower_detail/\'+tid); var j=await r.json(); if(j.ok){DISH_CACHE[tid]=j.dishes||[]; acc.dataset.loaded=\'1\'; renderDishes(tid);}}catch(e){content.innerHTML=\'خطأ\';}}} else {body.classList.remove(\'open\'); setTimeout(()=>body.style.display=\'none\',350);}}; window.renderDishes=function(tid){var dishes=DISH_CACHE[tid]||[]; var content=document.getElementById(\'tower-content-\'+tid); var h=\'<div style="display:flex;flex-direction:column;gap:6px">\'; dishes.forEach(function(d){h+=\'<div class="card" style="display:flex;justify-content:space-between;align-items:center;padding:10px"><div><b>\'+escHtml(d.dish_name)+\'</b><br><span class=ip onclick="event.preventDefault(); openInChrome(\\\'+d.ip+\'\\\')">\'+d.ip+\'</span></div><div style="display:flex;gap:6px"><button class="btn-circle view" onclick="event.preventDefault(); openInChrome(\\\'+d.ip+\'\\\')">👁 عرض</button><button class="btn-circle edit" onclick="event.preventDefault(); openEditDish(\'+d.id+\')">✏ تعديل</button><button class="btn-circle del" onclick="event.preventDefault(); openDeleteModal(\\\'/del_dish/\'+d.id+\'\\\','+ 'd.id' + ', \\\'+d.ip+\'\\\')">🗑 حذف</button></div></div>\';}); h+=\'<button class=btn-gold onclick="event.preventDefault(); openAddDish(\'+tid+\')" style="width:100%;margin-top:8px">+ إضافة صحن</button></div>\'; content.innerHTML=h;}; window.openAddDish=function(tid){document.getElementById(\'addDishModal\').style.display=\'flex\'; document.getElementById(\'mTid\').value=tid;}; window.closeAddDishModal=function(){document.getElementById(\'addDishModal\').style.display=\'none\';}; window.saveDish=async function(){var name=document.getElementById(\'mName\').value.trim(); var ip=document.getElementById(\'mIp\').value.trim(); var loc=document.getElementById(\'mLoc\').value.trim(); var tid=document.getElementById(\'mTid\').value; if(!ip) return; var r=await fetch(\'/api/add_dish_to_tower\',{method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({ip:ip, dish_name:name||\'صحن\', location:loc, tower_id:tid})}); var j=await r.json(); if(j.ok){closeAddDishModal(); document.getElementById(\'tower-acc-\'+tid).dataset.loaded=\'0\'; toggleAccordionLazy(parseInt(tid));}}; window.openEditDish=async function(id){try{var r=await fetch(\'/api/dish_detail/\'+id); var j=await r.json(); if(!j.ok) return; var d=j.dish; var b=document.getElementById("editBody"); b.innerHTML=\'<input id=ed_n value="\'+d.dish_name+\'"><input id=ed_i value="\'+d.ip+\'"><input id=ed_l value="\'+(d.location||"")+\'"><button class=btn-gold onclick="event.preventDefault(); saveEditDish(\'+id+\')" style="width:100%;margin-top:8px">حفظ</button>\'; document.getElementById("editModalTitle").textContent="تعديل صحن"; document.getElementById("editModal").classList.add("show");}catch(e){alert(e);}}; window.saveEditDish=async function(id){var d={dish_name:document.getElementById("ed_n").value, ip:document.getElementById("ed_i").value, location:document.getElementById("ed_l").value}; var r=await fetch("/edit_dish/"+id,{method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(d)}); var j=await r.json(); if(j.ok){closeEditModal(); loadPage(\'dishes\', true);}}; window.openNewTowerAcc=function(){var b=document.getElementById("editBody"); b.innerHTML=\'<input id=nt_name placeholder="اسم البرج"><input id=nt_area placeholder="المنطقة"><div class=row><input id=nt_lat value="35.1318"><input id=nt_lng value="36.7578"></div><button class=btn-gold onclick="event.preventDefault(); saveNewTowerAcc()" style="width:100%">حفظ</button>\'; document.getElementById("editModalTitle").textContent="إضافة برج"; document.getElementById("editModal").classList.add("show");}; window.saveNewTowerAcc=async function(){var d={name:document.getElementById("nt_name").value, area:document.getElementById("nt_area").value, lat:document.getElementById("nt_lat").value, lng:document.getElementById("nt_lng").value}; if(!d.name) return; var r=await fetch("/add_tower",{method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(d)}); var j=await r.json(); if(j.ok){closeEditModal(); loadPage(\'dishes\', true);}};</script>'

    if v == 'logs':
        rs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 500")
        row_parts=[]
        for r in rs:
            tm=esc(r.get('time','')); user=esc(r.get('username') or r.get('user_phone','')); act=esc(r.get('action','')); tgt=esc(r.get('target','')); det=esc(r.get('detail',''))
            row_parts.append('<tr><td>'+tm+'</td><td><b style="color:var(--accent)">'+user+'</b></td><td><span class=badge>'+act+'</span></td><td>'+tgt+'</td><td>'+det+'</td></tr>')
        rows="".join(row_parts) if row_parts else "<tr><td colspan=5>لا يوجد سجل</td></tr>"
        return '<div class=card><div class=row style="justify-content:space-between"><b>📜 السجل - 5 اعمدة</b><button class=btn-gold onclick="event.preventDefault(); clearLogs()" style="background:#ef4444">مسح</button></div><table style="width:100%;margin-top:8px"><thead><tr><th>وقت</th><th>المستخدم</th><th>عمل</th><th>الهدف</th><th>تفصيل</th></tr></thead><tbody>'+rows+'</tbody></table></div><script>window.clearLogs=async function(){if(!confirm("مسح؟")) return; await fetch("/api/clear_logs",{method:"POST"}); loadPage("logs", true);};</script>'

    if v == 'subs':
        rs=qall("SELECT * FROM subs ORDER BY name ASC LIMIT 150")
        row_parts=[]
        for r in rs:
            rid=r.get('id'); name=esc(r.get('name') or ''); phone=esc(r.get('phone') or ''); note=esc(r.get('note') or ''); name_js=esc_js(r.get('name') or 'مشترك')
            row_parts.append('<tr id="sub-'+str(rid)+'"><td>'+name+'</td><td>'+phone+'</td><td>'+note+'</td><td style="display:flex;gap:6px"><button class="btn-circle del" onclick="event.preventDefault(); openDeleteModal(\'/del_sub/'+str(rid)+'\','+str(rid)+',\''+name_js+'\')">🗑 حذف</button></td></tr>')
        rows="".join(row_parts)
        return '<div class=card><div class=row style="justify-content:space-between"><b>👥 المشتركين</b><button class=btn-gold onclick="event.preventDefault(); document.getElementById(\'fSub\').style.display=\'flex\'">+ إضافة</button></div><form id=fSub class=row style="display:none;margin-top:8px"><input name=name placeholder="اسم" required style="flex:1"><input name=phone placeholder="رقم" style="flex:1"><input name=note placeholder="ملاحظة" style="flex:1"><button class=btn-gold>+</button></form><table style="width:100%;margin-top:8px"><thead><tr><th>اسم</th><th>رقم</th><th>ملاحظة</th><th></th></tr></thead><tbody>'+rows+'</tbody></table></div><script>document.getElementById("fSub").addEventListener("submit", async e => { e.preventDefault(); var r=await fetch("/add_sub",{method:"POST", body:new FormData(e.target)}); var j=await r.json(); if(j.ok) loadPage(\'subs\', true); });</script>'

    if v == 'ledger':
        rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 150")
        row_parts=[]
        for r in rs:
            rid=r.get('id'); name=esc(r.get('name') or ''); amt=str(r.get('amount') or '0'); note=esc(r.get('note') or ''); curr=esc(r.get('currency') or ''); name_js=esc_js(r.get('name') or 'حساب')
            row_parts.append('<tr id="led-'+str(rid)+'"><td>'+name+'</td><td>'+amt+'</td><td>'+note+'</td><td>'+curr+'</td><td><button class="btn-circle del" onclick="event.preventDefault(); openDeleteModal(\'/del_ledger/'+str(rid)+'\','+str(rid)+',\''+name_js+'\')">🗑 حذف</button></td></tr>')
        rows="".join(row_parts)
        return '<div class=card><div class=row style="justify-content:space-between"><b>📒 الحسابات</b><button class=btn-gold onclick="event.preventDefault(); document.getElementById(\'fLed\').style.display=\'flex\'">+ إضافة</button></div><form id=fLed class=row style="display:none;margin-top:8px"><input name=name placeholder="اسم" required style="flex:1"><input name=amount type=number step=0.01 placeholder="مبلغ" required style="flex:1"><input name=note placeholder="ملاحظة" style="flex:1"><select name=currency><option>USD</option><option>SYP</option></select><button class=btn-gold>+</button></form><table style="width:100%;margin-top:8px"><thead><tr><th>اسم</th><th>مبلغ</th><th>ملاحظة</th><th>عملة</th><th></th></tr></thead><tbody>'+rows+'</tbody></table></div><script>document.getElementById("fLed").addEventListener("submit", async e => { e.preventDefault(); var r=await fetch("/add_ledger",{method:"POST", body:new FormData(e.target)}); var j=await r.json(); if(j.ok) loadPage(\'ledger\', true); });</script>'

    if v == 'network':
        dishes=qall("SELECT * FROM dish_ips ORDER BY dish_name ASC LIMIT 100")
        card_parts=[]
        for d in dishes:
            did=d.get('id'); dname=esc(d.get('dish_name') or ''); dip=esc(d.get('ip') or '')
            card_parts.append('<div class="card ip-card" id="net-'+str(did)+'" data-ip="'+dip+'" style="padding:10px"><div style="display:flex;justify-content:space-between"><b style="font-size:12px">'+dname+'</b></div><div style="margin-top:6px"><span class=ip onclick="event.preventDefault(); window.open(\'http://'+dip+'\',\'_blank\')">'+dip+'</span> <span class="net-out" style="font-size:10px">...</span></div></div>')
        cards="".join(card_parts)
        return '<div class=card><div class=row style="justify-content:space-between"><b>📊 الشبكة - عمودين</b><button class=btn-gold onclick="event.preventDefault(); checkAll()">فحص الكل</button></div><div style="display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-top:10px">'+cards+'</div></div><script>window.checkAll=async function(){var ips=[]; document.querySelectorAll("[id^=net-]").forEach(function(c){ips.push(c.dataset.ip);}); try{var r=await fetch(\'/api/ping_batch\',{method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({ips:ips})}); var j=await r.json(); if(j.ok){j.results.forEach(function(res){var card=document.querySelector("[data-ip=\'"+res.ip+"\']"); if(card){var out=card.querySelector(".net-out"); if(out){out.textContent=res.ok ? "Online" : "Offline"; out.style.color=res.ok ? "#34d399" : "#ef4444";}}}); return;}}catch(e){} for(var c of document.querySelectorAll("[id^=net-]")){try{var r=await fetch("/api/ping?ip="+encodeURIComponent(c.dataset.ip)); var j=await r.json(); c.querySelector(".net-out").textContent=j.out;}catch(e){} await new Promise(r=>setTimeout(r, 60));}};</script>'

    if v == 'ping':
        return '<div class=card><h3>📶 البنج</h3><div class=row style="margin-top:8px"><input id=pingIp placeholder="192.168.1.1" style="flex:1"><button class=btn-gold onclick="event.preventDefault(); doPing()">فحص</button></div><div id=pingResult class=pingBox style="margin-top:10px;padding:10px;background:#0008;border-radius:8px">جاهز</div></div><script>window.doPing=async function(){var ip=document.getElementById(\'pingIp\').value.trim(); if(!ip) return; var out=document.getElementById(\'pingResult\'); out.textContent=\'يفحص...\'; try{var r=await fetch(\'/api/ping?ip=\'+encodeURIComponent(ip)); var j=await r.json(); out.textContent=j.out;}catch(e){out.textContent=\'خطأ\';}};</script>'

    if v == 'settings':
        us=qall("SELECT * FROM users ORDER BY phone ASC")
        cards_parts=[]
        for u in us:
            uname=esc(u.get('username') or u.get('phone') or ''); phone=esc(u.get('phone') or ''); role=esc(u.get('role') or '')
            cards_parts.append('<div class="card"><b>'+uname+'</b><br>'+phone+' <span class=badge>'+role+'</span></div>')
        cards="".join(cards_parts)
        return '<div style="max-width:1100px;margin:0 auto"><div class=card><h4>🔑 تغيير كلمة المرور</h4><form id=formPass class=row><input name=newpass type=password placeholder="كلمة المرور الجديدة" required style="flex:1"><button class=btn-gold>حفظ</button></form></div><div class=card style="margin-top:12px"><b>👥 اليوزرات</b><div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px;margin-top:8px">'+cards+'</div></div></div><script>document.getElementById("formPass").addEventListener("submit", async e => { e.preventDefault(); var r=await fetch("/change_pass",{method:"POST", body:new FormData(e.target)}); var j=await r.json(); if(j.ok) e.target.reset(); });</script>'

    return "<div class=card>404</div>"

def layout(c, v='home'):
    th = session.get('theme', 'dark'); is_dark = (th == 'dark')
    cur_user = qone("SELECT * FROM users WHERE phone=?", (session.get('phone') or '',)) or {}
    return """<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>OMAIA ISP</title>
<link rel=stylesheet href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<style>
:root{--card-min:160px; --icon-size:44px; --accent:#ffbe4d; --card-bg-dark:#1e2433f2; --card-bg-light:#ffffff; --text-dark:#ffffff; --text-light:#0f172a; --border-dark:#ffffff14; --border-light:#e2e8f0}
*{box-sizing:border-box;font-family:system-ui}html,body{margin:0;padding:0}
body.dark{--bg:radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 60%, #070a1f 100%); --card-bg:var(--card-bg-dark); --text:var(--text-dark); --border:var(--border-dark)} 
body.light{--bg:#eef2f7; --card-bg:var(--card-bg-light); --text:var(--text-light); --border:var(--border-light)}
body{background:var(--bg);color:var(--text);overflow-x:hidden}
.card{background:var(--card-bg);color:var(--text);padding:10px;border-radius:12px;margin-bottom:8px;border:1px solid var(--border);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);transition:transform 0.3s ease, box-shadow 0.3s ease, border-color 0.2s}
.card:hover{transform:translateY(-2px);box-shadow:0 12px 24px rgba(0,0,0,0.2);border-color:rgba(255,190,77,0.3)}
.tower-accordion{border-radius:12px;overflow:hidden;border:1px solid #ffffff10}
.tower-accordion-body{max-height:0;overflow:hidden;opacity:0;transition:max-height 0.35s ease, opacity 0.28s ease;background:#0f1424}
.tower-accordion-body.open{max-height:4000px;opacity:1}
.top{position:fixed;top:0;left:0;right:0;height:56px;background:var(--card-bg);display:flex;align-items:center;justify-content:space-between;padding:0 12px;z-index:1003;border-bottom:1px solid var(--border);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px)}
.sidebar{position:fixed;top:0;right:0;width:320px;height:100vh;background:rgba(20,25,45,0.65);backdrop-filter:blur(20px) saturate(180%);-webkit-backdrop-filter:blur(20px) saturate(180%);z-index:1002;padding-top:60px;transform:translateX(110%);transition:transform 0.25s ease;overflow-y:auto;border-left:1px solid var(--border);border-radius:24px 0 0 24px}
.sidebar.active{transform:none}
.sidebar a{display:flex;align-items:center;gap:12px;padding:14px 16px;margin:6px 12px;color:var(--text);text-decoration:none;border-radius:12px;background:rgba(255,255,255,0.06);font-size:14px;font-weight:600;transition:all 0.2s ease}
.sidebar a:hover{transform:translateX(-4px);background:rgba(255,255,255,0.12)}
.sidebar a.active{background:rgba(255,190,77,0.15);color:#ffbe4d;border-right:4px solid #ffbe4d;transform:none}
.sidebar a.active .menu-icon-circle{background:rgba(255,190,77,0.25)}
.sidebar a:active{transform:scale(0.9)}
#overlay{position:fixed;inset:0;background:#0006;z-index:1001;display:none} #overlay.show{display:block}
.main{margin-top:62px;padding:10px;min-height:90vh}
.row{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.btn-gold{background:linear-gradient(90deg,var(--accent),#ffb020);color:#111;padding:7px 12px;border:0;border-radius:8px;font-weight:700;font-size:11px;cursor:pointer;transition:all 0.15s ease}
.btn-gold:hover{transform:translateY(-1px);box-shadow:0 4px 12px rgba(255,190,77,0.4)} .btn-gold:active{transform:scale(0.9)}
.btn-circle{background:rgba(255,255,255,0.08)!important;backdrop-filter:blur(20px)!important;-webkit-backdrop-filter:blur(20px)!important;border:1px solid rgba(255,255,255,0.18)!important;color:var(--text)!important;padding:6px 12px!important;border-radius:20px!important;font-size:11px!important;font-weight:600!important;cursor:pointer!important;display:inline-flex!important;align-items:center!important;justify-content:center!important;box-shadow:0 4px 12px rgba(0,0,0,0.15), inset 0 1px 0 rgba(255,255,255,0.2)!important;transition:all 0.15s cubic-bezier(0.34,1.56,0.64,1)!important}
.btn-circle:hover{transform:translateY(-2px) scale(1.05)!important}
.btn-circle:active{transform:scale(0.9)!important}
.btn-circle.edit{background:rgba(245,158,11,0.18)!important;color:#ffbe4d!important;border-color:rgba(245,158,11,0.35)!important;box-shadow:0 0 15px rgba(245,158,11,0.25), inset 0 1px 0 rgba(255,255,255,0.2)!important}
.btn-circle.del{background:rgba(239,68,68,0.18)!important;color:#ff6b6b!important;border-color:rgba(239,68,68,0.35)!important;box-shadow:0 0 15px rgba(239,68,68,0.25), inset 0 1px 0 rgba(255,255,255,0.2)!important}
.btn-circle.view{background:rgba(6,182,212,0.18)!important;color:#22d3ee!important;border-color:rgba(6,182,212,0.35)!important;box-shadow:0 0 15px rgba(6,182,212,0.25), inset 0 1px 0 rgba(255,255,255,0.2)!important}
.menu-icon-circle{width:34px;height:34px;background:rgba(255,255,255,0.08);backdrop-filter:blur(8px);border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-size:16px;margin-right:2px;border:1px solid rgba(255,255,255,0.12)}
.sq-btn{padding:5px 10px;border-radius:8px;border:0;font-size:11px;cursor:pointer;transition:all 0.15s ease} .sq-btn:hover{transform:translateY(-1px)} .sq-btn:active{transform:scale(0.9)}
.sq-btn.edit{background:rgba(245,158,11,0.2);color:#ffbe4d} .sq-btn.del{background:rgba(239,68,68,0.2);color:#ff6b6b} .sq-btn.view{background:rgba(6,182,212,0.2);color:#22d3ee}
.support-3d{width:32px!important;height:32px!important;border-radius:50%!important;display:inline-flex!important;align-items:center!important;justify-content:center!important;box-shadow:0 4px 10px rgba(0,0,0,0.25), inset 0 1px 1px rgba(255,255,255,0.4)!important;transform:perspective(80px) rotateX(6deg)!important;transition:all 0.3s cubic-bezier(0.34,1.56,0.64,1)!important}
.support-3d:hover{transform:translateY(-3px) scale(1.12)!important}
#topLoader{position:fixed;top:0;left:0;width:0%;height:3px;background:linear-gradient(90deg,#ffbe4d,#ff6b6b);z-index:9999;transition:width 0.3s ease}
.skeleton{background:linear-gradient(90deg, #ffffff0a 25%, #ffffff14 50%, #ffffff0a 75%);background-size:200% 100%;animation:shimmer 1.5s infinite;border-radius:6px}
@keyframes shimmer{0%{background-position:-200% 0}100%{background-position:200% 0}}
.grid-small{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:8px}
.ip{background:#000;color:var(--accent);padding:2px 6px;border-radius:5px;font-family:monospace;font-size:10px;cursor:pointer} .badge{background:var(--accent);color:#111;padding:2px 6px;border-radius:5px;font-size:10px;font-weight:700}
table{width:100%;border-collapse:collapse} th{background:var(--border);padding:8px;font-size:11px;text-align:right} td{padding:8px;border-bottom:1px solid var(--border)}
#editModal{position:fixed;inset:0;background:#0008;display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:.2s;z-index:2000} #editModal.show{opacity:1;pointer-events:auto} #editBox{background:var(--card-bg);color:var(--text);padding:18px;border-radius:14px;width:92%;max-width:420px;border:1px solid var(--border);backdrop-filter:blur(20px)}
input,select{padding:9px 11px;border-radius:8px;border:1px solid var(--border);background:var(--border);color:var(--text);font-size:12px;transition:all 0.15s}
input:focus,select:focus{border-color:#ffbe4d;box-shadow:0 0 0 3px rgba(255,190,77,0.15);outline:none}
.wa-float{position:fixed;bottom:18px;left:18px;width:56px;height:56px;background:#25D366;color:#fff;border-radius:50%;display:flex;align-items:center;justify-content:center;text-decoration:none;z-index:999;font-size:26px;box-shadow:0 6px 18px rgba(0,0,0,0.3)}
.stat{text-align:center;cursor:pointer} .ico{font-size:20px}
</style></head><body class="%s">
<div id=topLoader></div>
<div id=overlay onclick="toggleSb(false)"></div>
<div class=sidebar id=sb>
<div style='padding:0 16px 14px;border-bottom:1px solid var(--border)'><b style="font-size:16px">OMAIA <span style='color:var(--accent)'>ISP</span></b><br><small style="font-size:11px;opacity:.7">%s • %s</small></div>
<a href="#" onclick="event.preventDefault(); loadPage('home')" id=nav-home><span class=menu-icon-circle>🏠</span> <span>الرئيسية</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('towers')" id=nav-towers><span class=menu-icon-circle>🗼</span> <span>الأبراج</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('dishes')" id=nav-dishes><span class=menu-icon-circle>📡</span> <span>الصحون</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('network')" id=nav-network><span class=menu-icon-circle>📊</span> <span>الشبكة</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('ping')" id=nav-ping><span class=menu-icon-circle>📶</span> <span>البنج</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('subs')" id=nav-subs><span class=menu-icon-circle>👥</span> <span>المشتركين</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('ledger')" id=nav-ledger><span class=menu-icon-circle>📒</span> <span>الحسابات</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('logs')" id=nav-logs><span class=menu-icon-circle>📜</span> <span>السجل</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('settings')" id=nav-settings><span class=menu-icon-circle>⚙</span> <span>الإعدادات</span></a>
<div style='padding:14px 16px;margin-top:12px;border-top:1px dashed var(--border)'>
<div style='font-size:12px;font-weight:700;margin-bottom:10px'>💬 الدعم الفني</div>
<div style='display:flex;gap:8px;justify-content:center;align-items:center'>
<a href="%s" target="_blank" title="واتساب" class=support-3d style="background:#25D366;color:#fff;text-decoration:none;font-size:14px">W</a>
<a href="%s" target="_blank" title="انستغرام" class=support-3d style="background:linear-gradient(45deg,#feda75,#d62976);color:#fff;text-decoration:none;font-size:14px">I</a>
</div>
<div style='font-size:11px;opacity:.7;margin-top:10px;text-align:center'>+%s<br>%s</div>
</div>
<a href="#" onclick="event.preventDefault(); logoutFast()" style='margin:12px;background:rgba(239,68,68,0.12);display:flex;gap:12px;border:1px solid rgba(239,68,68,0.25)'><span class=menu-icon-circle style="background:rgba(239,68,68,0.15)">🚪</span> <span>خروج</span></a>
</div>
<div class=top>
<div class=row><span onclick="event.preventDefault(); toggleSb()" style='font-size:22px;cursor:pointer;padding:6px 12px;background:var(--border);border-radius:8px'>☰</span></div>
<b style="font-size:16px">OMAIA <span style='color:var(--accent)'>ISP</span></b>
<div class=row>
<button onclick="event.preventDefault(); toggleLangFast()" style="width:38px;height:38px;background:var(--border);border:1px solid var(--border);color:var(--text);border-radius:8px;cursor:pointer">🌐</button>
<button onclick="event.preventDefault(); toggleThemeFast()" style="width:38px;height:38px;background:var(--border);border:1px solid var(--border);color:var(--text);border-radius:8px;cursor:pointer">🌓</button>
</div>
</div>
<div class=main id=mn>%s</div>
<div id=editModal><div id=editBox><div class=row style='justify-content:space-between;margin-bottom:12px'><b id=editModalTitle style='font-size:14px'>نافذة</b><button onclick="event.preventDefault(); closeEditModal()" style='width:30px;height:30px;border-radius:50%;background:var(--border);border:0;color:var(--text)'>✕</button></div><div id=editBody></div></div></div>
<a href="%s" target="_blank" class=wa-float>💬</a>
<script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>
<script>
var cur = '%s';
var pageCache = {};
var MSG_SURE = 'هل انت متأكد؟ لا يمكن التراجع!';
function escHtml(s){return (s||'').toString().replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function topLoad(p){var t=document.getElementById('topLoader'); if(t){t.style.width=p+'%%'; if(p>=100) setTimeout(function(){t.style.width='0%%';},500);}}
function toggleSb(f){var sb=document.getElementById('sb'), ov=document.getElementById('overlay'); var o = f !== undefined ? f : !sb.classList.contains('active'); sb.classList.toggle('active', o); ov.classList.toggle('show', o);}
function filterTable(inputId, tableId){var q=document.getElementById(inputId).value.toLowerCase(); var rows=document.getElementById(tableId).querySelectorAll('tbody tr'); rows.forEach(function(r){r.style.display=r.textContent.toLowerCase().includes(q)?'':'none';});}
function filterCards(inputId, selector){var q=document.getElementById(inputId).value.toLowerCase(); document.querySelectorAll(selector).forEach(function(c){c.style.display=c.textContent.toLowerCase().includes(q)?'':'none';});}
function openLink(ip){if(!ip) return; var url=ip; if(!url.startsWith('http')) url='http://'+url; window.open(url,'_blank');}
async function loadPage(v, force){if(!force && pageCache[v]){document.getElementById('mn').innerHTML=pageCache[v]; execScripts(); setActiveNav(v); return;} cur=v; toggleSb(false); setActiveNav(v); var mn=document.getElementById('mn'); topLoad(20); mn.innerHTML='<div style="display:grid;gap:8px"><div class="card"><div class="skeleton" style="height:20px;width:40%%"></div><div class="skeleton" style="height:60px;margin-top:8px"></div></div><div class="card"><div class="skeleton" style="height:100px"></div></div></div>'; try{topLoad(60); var r=await fetch('/api/page?v='+v,{cache:'no-store'}); var h=await r.text(); pageCache[v]=h; topLoad(100); mn.innerHTML=h; execScripts();} catch(e){mn.innerHTML='<div class=card>خطأ بالتحميل</div>'; topLoad(0);}}
function setActiveNav(v){document.querySelectorAll('.sidebar a').forEach(function(a){a.classList.remove('active');}); var n=document.getElementById('nav-'+v); if(n) n.classList.add('active');}
function execScripts(){document.getElementById('mn').querySelectorAll('script').forEach(function(o){var s=document.createElement('script'); s.textContent=o.textContent; document.body.appendChild(s); o.remove();});}
window.closeEditModal=function(){var m=document.getElementById('editModal'); m.style.opacity='0'; setTimeout(function(){m.classList.remove('show'); m.style.opacity='1';},150);};
window.openDeleteModal=function(url, id, name){var displayName=name||'هذا العنصر'; var b=document.getElementById("editBody"); b.innerHTML='<div style="text-align:center;padding:10px"><h3 style="font-size:14px">تأكيد حذف <b style="color:#ef4444">'+escHtml(displayName)+'</b>؟</h3><p style="font-size:11px;color:#94a3b8;margin-top:6px">'+MSG_SURE+'</p><div style="display:flex;gap:8px;margin-top:14px"><button onclick="event.preventDefault(); closeEditModal()" style="flex:1;padding:10px;background:transparent;border:1px solid var(--border);color:var(--text);border-radius:8px">تراجع</button><button id=delConfirmBtn style="flex:1;padding:10px;background:#ef4444;color:#fff;border:0;border-radius:8px">حذف</button></div></div>'; document.getElementById("editModalTitle").textContent="تأكيد الحذف"; document.getElementById("editModal").classList.add("show"); document.getElementById("delConfirmBtn").onclick=async function(){try{var r=await fetch(url,{method:'POST'}); var j=await r.json(); if(j.ok){closeEditModal(); delete pageCache[cur]; loadPage(cur, true);} else alert(j.msg);}catch(e){alert(e);}};};
window.toggleLangFast=async function(){try{var r=await fetch('/toggle_lang'); var j=await r.json(); location.reload();}catch(e){}};
window.toggleThemeFast=async function(){try{var r=await fetch('/toggle_theme'); var j=await r.json(); document.body.className=j.theme; location.reload();}catch(e){}};
window.logoutFast=async function(){try{await fetch('/api/logout',{method:'POST'});}catch(e){} location.replace('/login');};
loadPage(cur, true);
</script></body></html>
""" % (
        'dark' if is_dark else 'light',
        esc(cur_user.get('username') or ''),
        esc(cur_user.get('role') or ''),
        SUPPORT_WA_LINK,
        SUPPORT_INSTA_LINK,
        SUPPORT_WA,
        SUPPORT_INSTA,
        c,
        SUPPORT_WA_LINK,
        v
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)), debug=False)
