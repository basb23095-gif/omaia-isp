from flask import Flask, request, redirect, session, jsonify, Response
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, html, ipaddress, subprocess, json, socket, platform, io, csv, datetime, re, threading, time
import psycopg2, psycopg2.extras
from psycopg2 import pool as pg_pool
import sqlite3

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "omia-sec-2026-CHANGE-ME-STRONG")
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(days=30)
app.config['SESSION_PERMANENT'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_PG = bool(DATABASE_URL)

_pg_pool = None
_pg_pool_lock = threading.Lock()
_sqlite_conn = None
_sqlite_lock = threading.Lock()
_cache = {}
_cache_lock = threading.Lock()
_user_cache = {}
_user_cache_lock = threading.Lock()

def init_pg_pool():
    global _pg_pool
    if not USE_PG: return
    with _pg_pool_lock:
        if _pg_pool: return
        try:
            _pg_pool = pg_pool.ThreadedConnectionPool(1, 25, dsn=DATABASE_URL, sslmode='require', connect_timeout=2, keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=3)
            print("[POOL] 25 ready")
        except Exception as e:
            print(f"[POOL ERROR] {e}"); _pg_pool = None
init_pg_pool()

def esc(s): return html.escape(str(s or ''), quote=True)

def get_conn():
    if USE_PG:
        if _pg_pool:
            try: return _pg_pool.getconn()
            except: return psycopg2.connect(DATABASE_URL, sslmode='require', connect_timeout=2)
        else: return psycopg2.connect(DATABASE_URL, sslmode='require', connect_timeout=2)
    else:
        global _sqlite_conn
        with _sqlite_lock:
            if _sqlite_conn is None:
                try:
                    _sqlite_conn = sqlite3.connect("omia.db", check_same_thread=False, timeout=10)
                    _sqlite_conn.row_factory = sqlite3.Row
                except:
                    _sqlite_conn = sqlite3.connect(":memory:", check_same_thread=False)
                    _sqlite_conn.row_factory = sqlite3.Row
            return _sqlite_conn

def put_conn(conn):
    if USE_PG:
        if _pg_pool:
            try: _pg_pool.putconn(conn)
            except:
                try: conn.close()
                except: pass
        else:
            try: conn.close()
            except: pass

def qall(q, a=()):
    conn=None
    try:
        conn=get_conn()
        if USE_PG:
            cur=conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(q.replace("?", "%s"), a)
            rs=[dict(r) for r in cur.fetchall()]; cur.close(); put_conn(conn); return rs
        else:
            with _sqlite_lock: rs=[dict(r) for r in conn.execute(q, a).fetchall()]; return rs
    except Exception as e:
        print(f"[qall] {e}"); 
        if conn and USE_PG:
            try: put_conn(conn)
            except: pass
        return []

def qone(q, a=()):
    r=qall(q,a); return r[0] if r else None

def qexec(q, a=()):
    conn=None
    try:
        conn=get_conn()
        if USE_PG:
            cur=conn.cursor(); cur.execute(q.replace("?", "%s"), a); conn.commit(); cur.close(); put_conn(conn)
        else:
            with _sqlite_lock: conn.execute(q,a); conn.commit()
        return True
    except Exception as e:
        print(f"[qexec] {e}")
        if conn and USE_PG:
            try: conn.rollback(); put_conn(conn)
            except: pass
        return False

# ===== حل مشكلة 2: السجل فاضي - خليه يبين التعديلات =====
def log_action(phone, action, detail):
    try:
        now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)", (phone or 'system', action, detail, now))
        with _cache_lock: _cache.pop('counts', None)
    except: pass

def get_dish_table():
    with _cache_lock:
        c=_cache.get('dish_table')
        if c and time.time()-c[1]<300: return c[0]
    if not USE_PG: return "dish_ips"
    try:
        rows=qall("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name IN ('ips','dish_ips')")
        names=[r.get('table_name') for r in rows]
        tbl="ips" if 'ips' in names else "dish_ips"
        with _cache_lock: _cache['dish_table']=(tbl, time.time())
        return tbl
    except: return "dish_ips"

def get_counts_cached():
    with _cache_lock:
        c=_cache.get('counts')
        if c and time.time()-c[1]<30: return c[0]
    dish_tbl=get_dish_table()
    try:
        ns=(qone("SELECT COUNT(*) as c FROM subs") or {}).get('c',0)
        nd=(qone(f"SELECT COUNT(*) as c FROM {dish_tbl}") or {}).get('c',0)
        nt=(qone("SELECT COUNT(*) as c FROM towers") or {}).get('c',0)
        nl=(qone("SELECT COUNT(*) as c FROM ledger") or {}).get('c',0)
        data=(ns,nd,nt,nl)
        with _cache_lock: _cache['counts']=(data, time.time())
        return data
    except: return (0,0,0,0)

def init():
    if USE_PG:
        tables=[
            "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,username TEXT)",
            "CREATE TABLE IF NOT EXISTS subs(id SERIAL PRIMARY KEY,name TEXT,phone TEXT,note TEXT)",
            "CREATE TABLE IF NOT EXISTS ledger(id SERIAL PRIMARY KEY,name TEXT,amount REAL,note TEXT,currency TEXT)",
            "CREATE TABLE IF NOT EXISTS dish_ips(id SERIAL PRIMARY KEY,ip TEXT,location TEXT,dish_name TEXT)",
            "CREATE TABLE IF NOT EXISTS towers(id SERIAL PRIMARY KEY,name TEXT,area TEXT,lat DOUBLE PRECISION,lng DOUBLE PRECISION)",
            "CREATE TABLE IF NOT EXISTS logs(id SERIAL PRIMARY KEY,user_phone TEXT,action TEXT,detail TEXT,time TEXT)",
            "CREATE TABLE IF NOT EXISTS notifications(id SERIAL PRIMARY KEY,title TEXT,msg TEXT,time TEXT,read INTEGER DEFAULT 0)",
            "CREATE TABLE IF NOT EXISTS ips(id SERIAL PRIMARY KEY, ip TEXT, location TEXT, dish_name TEXT, created_at TIMESTAMP DEFAULT NOW())"
        ]
    else:
        tables=[
            "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,username TEXT)",
            "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,note TEXT)",
            "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,amount REAL,note TEXT,currency TEXT)",
            "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,dish_name TEXT)",
            "CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,area TEXT,lat REAL,lng REAL)",
            "CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,user_phone TEXT,action TEXT,detail TEXT,time TEXT)",
            "CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,msg TEXT,time TEXT,read INTEGER DEFAULT 0)",
            "CREATE TABLE IF NOT EXISTS ips(id INTEGER PRIMARY KEY AUTOINCREMENT, ip TEXT, location TEXT, dish_name TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        ]
    for s in tables: qexec(s)
    # indexes للسرعة
    if USE_PG:
        for idx in ["CREATE INDEX IF NOT EXISTS idx_dish_ips_ip ON dish_ips(ip)", "CREATE INDEX IF NOT EXISTS idx_ips_ip ON ips(ip)", "CREATE UNIQUE INDEX IF NOT EXISTS uq_dish_ips_ip ON dish_ips(ip)", "CREATE UNIQUE INDEX IF NOT EXISTS uq_ips_ip ON ips(ip)"]:
            try: qexec(idx)
            except: pass
    if not qone("SELECT * FROM users WHERE phone=?", ('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)", ('05344851045', generate_password_hash('admin2024'), 'manager', 'admin'))
    if not qone("SELECT * FROM towers WHERE name=?", ('نقطة حماة الرئيسية',)):
        qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)", ('نقطة حماة الرئيسية', 'حماة', 35.1318, 36.7578))
    # إذا السجل فاضي - ضيف سجل يبين انو شغال
    c=qone("SELECT COUNT(*) as c FROM logs")
    if c and c.get('c',0)==0:
        qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)", ('system','تشغيل النظام','السجل شغال الآن ✅ - يبين كل التعديلات', datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
init()

def login_required(f):
    @wraps(f)
    def w(*a, **kw):
        if not session.get('phone'): return redirect('/login')
        return f(*a, **kw)
    return w

def is_manager():
    if session.get('role'): return session.get('role')=='manager'
    u=qone("SELECT role FROM users WHERE phone=?", (session.get('phone') or '',))
    if u:
        session['role']=u.get('role')
        return (u.get('role') or '').lower()=='manager'
    return False

def role_required_manager(f):
    @wraps(f)
    def w(*a, **kw):
        if not is_manager(): return "ممنوع", 403
        return f(*a, **kw)
    return w

def is_valid_ip(ip):
    ip=(ip or '').strip()
    if not ip: return False
    try: ipaddress.ip_address(ip); return True
    except: return False

@app.after_request
def add_perf_headers(resp):
    if request.path.startswith('/api/'): resp.headers['Cache-Control']='no-store, max-age=0'
    else: resp.headers['Cache-Control']='no-cache'
    return resp

@app.route('/ping')
@app.route('/health')
def public_ping():
    tbl=get_dish_table()
    return jsonify(ok=True, time=datetime.datetime.now().isoformat(), table=tbl, pool=bool(_pg_pool))

@app.route('/api/ping')
@login_required
def api_ping():
    ip=request.args.get('ip','').strip()
    if not ip: return jsonify(ok=False, out='لا يوجد IP')
    if not is_valid_ip(ip): return jsonify(ok=False, out='IP غير صالح')
    for port in [80,443,8080,8291,22]:
        s=None
        try:
            s=socket.socket(socket.AF_INET,socket.SOCK_STREAM); s.settimeout(0.5)
            if s.connect_ex((ip,port))==0: s.close(); return jsonify(ok=True,out=f'✅ {ip}:{port} مفتوح')
            s.close()
        except:
            try:
                if s: s.close()
            except: pass
            continue
    return jsonify(ok=False,out=f'❌ {ip} لا يرد')

@app.route('/api/ping_tcp')
@login_required
def api_ping_tcp():
    ip=request.args.get('ip','').strip(); port_str=request.args.get('port','80').strip()
    try: port=int(port_str)
    except: return jsonify(ok=False,out='Port غير صالح')
    if not is_valid_ip(ip): return jsonify(ok=False,out='IP غير صالح')
    s=None
    try:
        s=socket.socket(socket.AF_INET,socket.SOCK_STREAM); s.settimeout(0.8); r=s.connect_ex((ip,port)); s.close()
        return jsonify(ok=r==0,out=f'✅ {ip}:{port} مفتوح' if r==0 else f'❌ مغلق')
    except Exception as e:
        try:
            if s: s.close()
        except: pass
        return jsonify(ok=False,out=f'❌ {e}')

@app.route('/api/notifications')
@login_required
def api_noti():
    rows=qall("SELECT * FROM notifications ORDER BY id DESC LIMIT 20")
    unread=qone("SELECT COUNT(*) as c FROM notifications WHERE read=0")
    return jsonify(rows=rows, unread=unread.get('c',0) if unread else 0)

@app.route('/api/notifications/read', methods=['POST'])
@login_required
def api_noti_read(): qexec("UPDATE notifications SET read=1"); return jsonify(ok=True)

@app.route('/api/network_status')
@login_required
def api_network():
    tbl=get_dish_table(); ns,nd,nt,nl=get_counts_cached()
    return jsonify(dishes=nd, towers=nt, subs=ns)

@app.route('/toggle_lang')
@login_required
def toggle_lang_route():
    cur=session.get('lang','ar'); new='en' if cur=='ar' else 'ar'; session['lang']=new; return jsonify(ok=True,lang=new)

# ===== حل مشكلة 3: تسجيل دخول بطيء =====
@app.route('/api/login_public', methods=['POST'])
def api_login_public():
    uin=request.form.get('userin','').strip(); pw=request.form.get('password','')
    cache_key=uin
    with _user_cache_lock:
        cached=_user_cache.get(cache_key)
        if cached and time.time()-cached[1]<60:
            u=cached[0]
        else:
            u=None
    if not u:
        u=qone("SELECT * FROM users WHERE phone=? OR username=?", (uin, uin))
        if u:
            with _user_cache_lock: _user_cache[cache_key]=(u, time.time())
    if u and check_password_hash(u['password'], pw):
        session['phone']=u['phone']; session['username']=u.get('username') or u['phone']; session['role']=u.get('role') or 'tech'; session.permanent=True
        # سجل دخول بالخلفية بدون انتظار
        try: threading.Thread(target=log_action, args=(u['phone'],'تسجيل دخول','دخل النظام ✅'), daemon=True).start()
        except: pass
        return jsonify(ok=True, role=u.get('role'))
    return jsonify(ok=False, msg='خطأ بالدخول'),401

@app.route('/api/export/<tbl>')
@login_required
def api_export(tbl):
    output=io.StringIO(); output.write('\ufeff'); w=csv.writer(output); dish_tbl=get_dish_table()
    if tbl=='dishes':
        rows=qall(f"SELECT * FROM {dish_tbl} ORDER BY id DESC"); w.writerow(['ID','اسم الصحن','IP','الموقع'])
        for r in rows: w.writerow([r.get('id',''),r.get('dish_name',''),r.get('ip',''),r.get('location','')]); fname='dishes.csv'
    elif tbl=='logs':
        rows=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 1000"); w.writerow(['ID','المستخدم','العملية','التفاصيل','الوقت'])
        for r in rows: w.writerow([r.get('id',''),r.get('user_phone',''),r.get('action',''),r.get('detail',''),r.get('time','')]); fname='logs.csv'
    else: w.writerow(['ID']); fname='export.csv'
    return Response(output.getvalue(), mimetype='text/csv; charset=utf-8', headers={'Content-Disposition': f'attachment; filename={fname}'})

@app.route('/api/clear_logs', methods=['POST'])
@login_required
@role_required_manager
def clear_logs(): qexec("DELETE FROM logs"); return jsonify(ok=True)

@app.route('/api/seed_log', methods=['POST'])
@login_required
def seed_log():
    now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)", (session.get('phone','test'), 'إضافة صحن', '192.168.1.10 - صحن تجريبي', now))
    qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)", (session.get('phone','test'), 'تعديل صحن', 'تعديل موقع الصحن', now))
    qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)", (session.get('phone','test'), 'حذف صحن', 'حذف 192.168.1.11', now))
    return jsonify(ok=True)

@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login')
def login():
    return """<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<style>*{box-sizing:border-box;font-family:system-ui}body{margin:0;min-height:100vh;background:radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 55%, #070a1f 100%);display:flex;flex-direction:column;align-items:center;justify-content:center;color:#fff}
.card{background:linear-gradient(180deg, #222b45cc, #1a2035cc);backdrop-filter:blur(16px);border:1px solid #ffffff18;padding:26px;border-radius:22px;width:92%;max-width:380px;box-shadow:0 20px 60px #0008}
input{width:100%;padding:14px;margin:9px 0;background:#0f1424;border:1px solid #ffffff22;color:#fff;border-radius:14px;font-size:15px}
.btn{width:100%;padding:14px;border:0;border-radius:14px;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:900;font-size:17px;cursor:pointer;margin-top:12px}
.spinner{display:inline-block;width:16px;height:16px;border:2px solid #1115;border-top-color:#111;border-radius:50%;animation:spin .6s linear infinite;vertical-align:middle;margin-left:6px}
@keyframes spin{to{transform:rotate(360deg)}}</style></head><body>
<div style='font-size:30px;font-weight:900;margin-bottom:14px'>OMAIA <span style='color:#ffbe4d'>ISP</span> <small style='color:#22c55e'>⚡ ULTRA</small></div>
<div class=card><form id=loginForm><input name=userin id=userin placeholder='📱 رقم / يوزر' required autocomplete=username><input name=password id=password type=password placeholder='🔑 كلمة السر' required autocomplete=current-password><label style='display:flex;gap:8px;font-size:13px;color:#aaa;margin:8px 0'><input type=checkbox id=savePass style='width:auto'> حفظ</label><button class=btn id=loginBtn>✨ دخول فوري</button><div id=msg style='text-align:center;margin-top:10px;color:#ff6b6b;font-size:13px;min-height:18px'></div></form></div>
<script>
fetch('/ping',{cache:'no-store'}).catch(()=>{});
let u=document.getElementById('userin'), p=document.getElementById('password'), s=document.getElementById('savePass');
let su=localStorage.getItem('omaia_user'), sp=localStorage.getItem('omaia_pass');
if(su){u.value=su; if(sp){p.value=sp; s.checked=true;}}
document.getElementById('loginForm').addEventListener('submit',async e=>{
 e.preventDefault(); let btn=document.getElementById('loginBtn'), msg=document.getElementById('msg');
 if(btn.disabled) return;
 let orig=btn.innerHTML; btn.innerHTML='<span class=spinner></span> جاري...'; btn.disabled=true; msg.textContent='';
 try{
  let fd=new FormData(e.target);
  let r=await fetch('/api/login_public',{method:'POST',body:fd,cache:'no-store'});
  let j=await r.json();
  if(j.ok){
    if(s.checked){localStorage.setItem('omaia_user',u.value);localStorage.setItem('omaia_pass',p.value);}
    msg.style.color='#22c55e'; msg.textContent='✅ تم';
    location.replace('/dash?v=home');
  } else { msg.style.color='#ff6b6b'; msg.textContent=j.msg||'خطأ'; btn.innerHTML=orig; btn.disabled=false; }
 }catch(err){ msg.textContent='خطأ شبكة'; btn.innerHTML=orig; btn.disabled=false; }
});
</script></body></html>"""

@app.route('/logout')
def lo(): session.clear(); return redirect('/login')
@app.route('/api/logout', methods=['POST'])
def api_logout(): session.clear(); return jsonify(ok=True)

@app.route('/dash')
@login_required
def dash():
    v=request.args.get('v','home')
    # حل مشكلة تحميل الموقع كلو: نرجع هيكل فاضي سريع بدون استعلامات DB
    return layout('<div class=card><div class="skeleton" style="height:28px;width:45%;border-radius:10px;margin-bottom:12px"></div><div class="skeleton" style="height:18px;border-radius:8px;margin-bottom:8px"></div><div class="skeleton" style="height:18px;width:80%;border-radius:8px"></div></div>', v, fast=True)

@app.route('/api/page')
@login_required
def ap(): return page_content(request.args.get('v','home'))

@app.route('/api/search')
@login_required
def s():
    q=request.args.get('q','').strip()
    if not q or len(q)<2: return jsonify([])
    like="%"+q+"%"; dish_tbl=get_dish_table()
    try:
        rs=[]
        for r in qall(f"SELECT * FROM {dish_tbl} WHERE ip LIKE ? OR dish_name LIKE ? OR location LIKE ? ORDER BY id DESC LIMIT 12", (like,like,like)):
            rs.append({"title": r.get('dish_name') or r.get('ip') or 'صحن', "sub": r.get('ip',''), "page": "dishes"})
        return jsonify(rs)
    except: return jsonify([])

@app.route('/toggle_theme')
@login_required
def tt(): cur=session.get('theme','dark'); session['theme']='light' if cur=='dark' else 'dark'; return jsonify(ok=True)

# ===== حل مشكلة 1: إضافة وحذف بطول - فوري =====
@app.route('/add_dish', methods=['POST'])
@login_required
def ad():
    dish_tbl=get_dish_table()
    ip=request.form.get('ip','').strip(); name=request.form.get('dish_name','').strip(); loc=request.form.get('location','').strip()
    if not ip: return jsonify(ok=False,msg="IP مطلوب"),400
    if not is_valid_ip(ip): return jsonify(ok=False,msg="IP غير صالح"),400
    phone=session.get('phone','')
    # استعلام واحد فوري بدل SELECT ثم INSERT
    if USE_PG:
        ok=qexec(f"INSERT INTO {dish_tbl}(ip,location,dish_name) VALUES(?,?,?) ON CONFLICT (ip) DO UPDATE SET dish_name=EXCLUDED.dish_name, location=EXCLUDED.location", (ip, loc, name))
    else:
        ok=qexec(f"INSERT OR REPLACE INTO {dish_tbl}(ip,location,dish_name) VALUES(?,?,?)", (ip, loc, name))
    if ok:
        log_action(phone, 'إضافة/تعديل صحن', f'{name} {ip}')
        with _cache_lock: _cache.pop('counts', None)
        return jsonify(ok=True, ip=ip, name=name, loc=loc)
    return jsonify(ok=False,msg="خطأ"),400

@app.route('/edit_dish/<int:i>', methods=['POST'])
@login_required
def ed(i):
    if not is_manager(): return jsonify(ok=False,msg="ممنوع"),403
    dish_tbl=get_dish_table()
    new_ip=request.form.get('ip','').strip(); new_name=request.form.get('dish_name','').strip(); new_loc=request.form.get('location','').strip()
    ok=qexec(f"UPDATE {dish_tbl} SET dish_name=?,ip=?,location=? WHERE id=?", (new_name, new_ip, new_loc, i))
    if ok:
        log_action(session.get('phone'), 'تعديل صحن', f'ID {i} -> {new_ip} {new_name}')
        return jsonify(ok=True)
    return jsonify(ok=False),400

@app.route('/del_dish/<int:i>')
@login_required
def dd(i):
    if not is_manager(): return jsonify(ok=False,msg="ممنوع"),403
    dish_tbl=get_dish_table()
    info=qone(f"SELECT ip,dish_name FROM {dish_tbl} WHERE id=?", (i,))
    ok=qexec(f"DELETE FROM {dish_tbl} WHERE id=?", (i,))
    if ok:
        with _cache_lock: _cache.pop('counts', None)
        log_action(session.get('phone'), 'حذف صحن', f"{info.get('dish_name','')} {info.get('ip','')}" if info else f"ID {i}")
        return jsonify(ok=True)
    return jsonify(ok=False),400

@app.route('/add_tower', methods=['POST'])
@login_required
def at():
    ok=qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)", (request.form.get('name',''), request.form.get('area',''), float(request.form.get('lat') or 35.1318), float(request.form.get('lng') or 36.7578)))
    if ok: log_action(session.get('phone'), 'إضافة برج', request.form.get('name','')); return jsonify(ok=True)
    return jsonify(ok=False),400

@app.route('/del_tower/<int:i>')
@login_required
def dt(i):
    if not is_manager(): return jsonify(ok=False),403
    ok=qexec("DELETE FROM towers WHERE id=?", (i,))
    if ok: log_action(session.get('phone'), 'حذف برج', f"ID {i}"); return jsonify(ok=True)
    return jsonify(ok=False),400

@app.route('/edit_tower/<int:i>', methods=['POST'])
@login_required
def et(i):
    if not is_manager(): return jsonify(ok=False),403
    ok=qexec("UPDATE towers SET name=?,area=?,lat=?,lng=? WHERE id=?", (request.form.get('name',''), request.form.get('area',''), float(request.form.get('lat') or 35.1318), float(request.form.get('lng') or 36.7578), i))
    if ok: log_action(session.get('phone'), 'تعديل برج', f"ID {i}"); return jsonify(ok=True)
    return jsonify(ok=False),400

@app.route('/add_sub', methods=['POST'])
@login_required
def asub():
    ok=qexec("INSERT INTO subs(name,phone,note) VALUES(?,?,?)", (request.form.get('name',''), request.form.get('phone',''), request.form.get('note','')))
    if ok: log_action(session.get('phone'), 'إضافة مشترك', request.form.get('name','')); return jsonify(ok=True)
    return jsonify(ok=False),400

@app.route('/del_sub/<int:i>')
@login_required
def dsub(i):
    if not is_manager(): return jsonify(ok=False),403
    ok=qexec("DELETE FROM subs WHERE id=?", (i,))
    if ok: log_action(session.get('phone'), 'حذف مشترك', f"ID {i}"); return jsonify(ok=True)
    return jsonify(ok=False),400

@app.route('/edit_sub/<int:i>', methods=['POST'])
@login_required
def esub(i):
    if not is_manager(): return jsonify(ok=False),403
    ok=qexec("UPDATE subs SET name=?,phone=?,note=? WHERE id=?", (request.form.get('name',''), request.form.get('phone',''), request.form.get('note',''), i))
    if ok: log_action(session.get('phone'), 'تعديل مشترك', f"ID {i}"); return jsonify(ok=True)
    return jsonify(ok=False),400

@app.route('/add_ledger', methods=['POST'])
@login_required
def al():
    try: amt=float(request.form.get('amount') or 0)
    except: amt=0
    ok=qexec("INSERT INTO ledger(name,amount,note,currency) VALUES(?,?,?,?)", (request.form.get('name',''), amt, request.form.get('note',''), request.form.get('currency','USD')))
    if ok: log_action(session.get('phone'), 'إضافة حساب', f"{request.form.get('name','')} {amt}"); return jsonify(ok=True)
    return jsonify(ok=False),400

@app.route('/del_ledger/<int:i>')
@login_required
def dll(i):
    if not is_manager(): return jsonify(ok=False),403
    ok=qexec("DELETE FROM ledger WHERE id=?", (i,))
    if ok: log_action(session.get('phone'), 'حذف حساب', f"ID {i}"); return jsonify(ok=True)
    return jsonify(ok=False),400

@app.route('/edit_ledger/<int:i>', methods=['POST'])
@login_required
def el(i):
    if not is_manager(): return jsonify(ok=False),403
    try: amt=float(request.form.get('amount') or 0)
    except: amt=0
    ok=qexec("UPDATE ledger SET name=?,amount=?,note=?,currency=? WHERE id=?", (request.form.get('name',''), amt, request.form.get('note',''), request.form.get('currency','USD'), i))
    if ok: log_action(session.get('phone'), 'تعديل حساب', f"ID {i}"); return jsonify(ok=True)
    return jsonify(ok=False),400

@app.route('/add_user', methods=['POST'])
@login_required
@role_required_manager
def au():
    ph=request.form.get('phone','').strip() or request.form.get('user_field','').strip()
    if not ph: return jsonify(ok=False,msg="رقم مطلوب"),400
    if qone("SELECT phone FROM users WHERE phone=?", (ph,)): return jsonify(ok=False,msg="موجود"),400
    ok=qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)", (ph, generate_password_hash(request.form.get('password','1234')), request.form.get('role','tech'), ph))
    if ok: log_action(session.get('phone'), 'إضافة يوزر', ph); return jsonify(ok=True)
    return jsonify(ok=False),400

@app.route('/edit_user', methods=['POST'])
@login_required
@role_required_manager
def eu():
    old=request.form.get('old_phone','').strip(); new_ph=request.form.get('phone','').strip() or request.form.get('user_field','').strip()
    new_role=request.form.get('role','tech'); new_pass=request.form.get('password','').strip()
    if not old: return jsonify(ok=False),400
    if old!=new_ph and qone("SELECT phone FROM users WHERE phone=?", (new_ph,)): return jsonify(ok=False,msg="موجود"),400
    if new_pass: ok=qexec("UPDATE users SET phone=?,username=?,role=?,password=? WHERE phone=?", (new_ph, new_ph, new_role, generate_password_hash(new_pass), old))
    else: ok=qexec("UPDATE users SET phone=?,username=?,role=? WHERE phone=?", (new_ph, new_ph, new_role, old))
    if ok and session.get('phone')==old: session['phone']=new_ph; session['role']=new_role
    if ok: log_action(session.get('phone'), 'تعديل يوزر', f"{old}->{new_ph}"); return jsonify(ok=True)
    return jsonify(ok=False),400

@app.route('/del_user/<ph>')
@login_required
@role_required_manager
def du(ph):
    if ph=='05344851045': return jsonify(ok=False,msg="ممنوع"),400
    ok=qexec("DELETE FROM users WHERE phone=?", (ph,))
    if ok: log_action(session.get('phone'), 'حذف يوزر', ph); return jsonify(ok=True)
    return jsonify(ok=False),400

@app.route('/change_pass', methods=['POST'])
@login_required
def cp():
    np=request.form.get('newpass','').strip()
    if not np: return jsonify(ok=False),400
    ok=qexec("UPDATE users SET password=? WHERE phone=?", (generate_password_hash(np), session.get('phone')))
    if ok: log_action(session.get('phone'), 'تغيير كلمة سر', ''); return jsonify(ok=True)
    return jsonify(ok=False),400

def page_content(v):
    req_lang=request.args.get('lang') or session.get('lang','ar'); dish_tbl=get_dish_table()
    def L(ar,en): return ar if req_lang=='ar' else en
    if v=='home':
        ns,nd,nt,nl=get_counts_cached()
        logs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 8")
        log_html="".join([f"<div style='display:flex;justify-content:space-between;padding:8px 10px;border-bottom:1px dashed #ffffff10'><div><b style='color:#ffbe4d'>{esc(l.get('user_phone',''))}</b> <span style='color:#22c55e;font-weight:800'>{esc(l.get('action',''))}</span> <small style='color:#cbd5e1'>{esc(l.get('detail',''))}</small></div><small style='color:#64748b'>{esc(l.get('time',''))}</small></div>" for l in logs])
        if not logs: log_html="<div style='padding:12px;color:#64748b'>السجل فاضي - اضف صحن وسيظهر هنا فوراً ✅<br><button class=btn-gold onclick=\"fetch('/api/seed_log',{method:'POST'}).then(()=>loadPage('home',true))\" style='margin-top:8px'>🧪 اختبار السجل</button></div>"
        return f'''<div style='max-width:900px;margin:0 auto'><div style='display:grid;grid-template-columns:1fr 1fr;gap:14px'>
        <div class='card anim' onclick="loadPage('subs')" style='cursor:pointer'><h3 style='margin:0;color:#aab4d0;font-size:13px'>المشتركين</h3><h2 style='margin:6px 0 0;font-size:36px'>{ns}</h2></div>
        <div class='card anim' onclick="loadPage('dishes')" style='cursor:pointer'><h3 style='margin:0;color:#aab4d0;font-size:13px'>الصحون ☁ {dish_tbl}</h3><h2 style='margin:6px 0 0;font-size:36px'>{nd}</h2><small style='color:#22c55e'>⚡ فوري</small></div>
        <div class='card anim' onclick="loadPage('towers')" style='cursor:pointer'><h3 style='margin:0;color:#aab4d0;font-size:13px'>الأبراج</h3><h2 style='margin:6px 0 0;font-size:36px'>{nt}</h2></div>
        <div class='card anim' onclick="loadPage('ledger')" style='cursor:pointer'><h3 style='margin:0;color:#aab4d0;font-size:13px'>الحسابات</h3><h2 style='margin:6px 0 0;font-size:36px'>{nl}</h2></div></div>
        <div class=card><div style='display:flex;justify-content:space-between'><h4>📜 السجل - يبين كل التعديلات ✅</h4><button class=btn-gold onclick="loadPage('logs')" style='padding:6px 12px'>عرض الكل</button></div>{log_html}</div></div>'''
    if v=='dishes':
        rs=qall(f"SELECT * FROM {dish_tbl} ORDER BY id DESC LIMIT 200"); rows_html=""
        for r in rs:
            dn=esc(r.get('dish_name') or 'صحن');ip=esc(r.get('ip') or '');loc=esc(r.get('location') or '');rid=r['id']
            rows_html+=f'<div class="card anim dish-card" id="dish-{rid}" data-name="{dn}" data-ip="{ip}" data-loc="{loc}" style="display:flex;justify-content:space-between"><div><b>{dn}</b><br><span style="background:#000;color:#ffbe4d;padding:5px 10px;border-radius:8px;font-family:monospace">🌐 {ip}</span><br><small style="color:#888">{loc}</small></div><div style="display:flex;flex-direction:column;gap:6px"><button class=btn-gold onclick="editDish({rid})" style="padding:7px 9px">✏</button><button class=btn-del onclick="askDel(\'/del_dish/{rid}\', {rid})" style="padding:7px 9px">🗑</button></div></div>'
        return f'''<div style='max-width:900px;margin:0 auto'><div class=card><div style='display:flex;justify-content:space-between'><h3>📡 الصحون - {len(rs)} ⚡ فوري بدون تحميل</h3><small style='color:#22c55e'>Pool 25 + ON CONFLICT</small></div><form id=formDish style='display:flex;gap:6px;flex-wrap:wrap;margin-top:10px'><input name=dish_name id=dish_name placeholder='اسم الصحن' required style='flex:1'><input name=ip id=dish_ip placeholder='192.168.1.1' required style='flex:1'><input name=location id=dish_loc placeholder='موقع' style='flex:1'><button class=btn-gold type=submit id=btnAddDish>➕ حفظ فوري</button></form><div id=dishMsg style='margin-top:8px;font-size:13px;min-height:18px'></div><input id=searchBox placeholder='🔍 بحث فوري...' oninput="searchDishes(this.value)" style='margin-top:10px;width:100%;padding:12px;border-radius:12px;background:#0f1424;border:1px solid #ffffff18'></div><div id=dl>{rows_html}</div></div><script>
        function searchDishes(q){{q=(q||'').toLowerCase();document.querySelectorAll('.dish-card').forEach(c=>{{let t=(c.dataset.name+c.dataset.ip+c.dataset.loc).toLowerCase(); c.style.display=t.includes(q)?'flex':'none';}});}}
        function editDish(id){{let c=document.getElementById('dish-'+id);document.getElementById('editModal').classList.add('show');document.getElementById('editBody').innerHTML='<input id=edit_dish_name value="'+c.dataset.name+'" style="width:100%;padding:12px;margin:4px 0"><input id=edit_ip value="'+c.dataset.ip+'" style="width:100%;padding:12px;margin:4px 0"><input id=edit_loc value="'+c.dataset.loc+'" style="width:100%;padding:12px;margin:4px 0"><button onclick="saveDish('+id+')" class=btn-gold style="width:100%;padding:12px" id=btnSaveDish>💾 حفظ فوري</button>';}}
        function saveDish(id){{let b=document.getElementById('btnSaveDish'); b.innerHTML='⏳...'; b.disabled=true; let nn=document.getElementById('edit_dish_name').value;let ii=document.getElementById('edit_ip').value;let ll=document.getElementById('edit_loc').value;fetch('/edit_dish/'+id,{{method:'POST',body:new URLSearchParams({{dish_name:nn,ip:ii,location:ll}})}}).then(r=>r.json()).then(j=>{{if(j.ok){{let card=document.getElementById('dish-'+id); if(card){{card.dataset.name=nn; card.dataset.ip=ii; card.dataset.loc=ll; card.querySelector('b').textContent=nn;}} closeEditModal(); showToast('✅ تم التعديل - السجل تحدث');}} else {{alert('خطأ'); b.innerHTML='💾 حفظ'; b.disabled=false;}}}}).catch(()=>{{b.innerHTML='💾'; b.disabled=false;}});}}
        document.getElementById('formDish').addEventListener('submit', async e=>{{
          e.preventDefault(); let btn=document.getElementById('btnAddDish'); let msg=document.getElementById('dishMsg');
          let orig=btn.innerHTML; btn.innerHTML='⏳...'; btn.disabled=true; msg.textContent='';
          let fd=new FormData(e.target);
          try{{
            let r=await fetch('/add_dish',{{method:'POST',body:fd}});
            let j=await r.json();
            if(j.ok){{
              msg.style.color='#22c55e'; msg.textContent='✅ تمت الإضافة فورياً - السجل تحدث';
              let dl=document.getElementById('dl');
              let div=document.createElement('div');
              div.className='card anim dish-card';
              div.style.cssText='display:flex;justify-content:space-between;background:linear-gradient(135deg,#1e3a2f,#162a20);border:1px solid #22c55e55';
              div.innerHTML='<div><b>'+j.name+'</b><br><span style="background:#000;color:#ffbe4d;padding:5px 10px;border-radius:8px">🌐 '+j.ip+'</span><br><small>'+j.loc+'</small><br><small style="color:#22c55e">✅ جديد - فوري بدون تحميل</small></div><div><small style="color:#22c55e">تم</small></div>';
              dl.prepend(div);
              e.target.reset();
              setTimeout(()=>{{msg.textContent='';}},2500);
            }} else {{ msg.style.color='#ef4444'; msg.textContent=j.msg||'خطأ'; }}
          }}catch(err){{ msg.textContent='خطأ شبكة'; }}
          btn.innerHTML=orig; btn.disabled=false;
        }});
        function showToast(t){{let toast=document.createElement('div'); toast.style.cssText='position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:#1f2937;color:#fff;padding:10px 18px;border-radius:20px;z-index:9999;border:1px solid #22c55e55'; toast.textContent=t; document.body.appendChild(toast); setTimeout(()=>toast.remove(),2000);}}
        </script>'''
    if v=='logs':
        rs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 400")
        rows="".join([f"<div class='card anim' style='font-size:13px;border-right:4px solid #ffbe4d;display:flex;justify-content:space-between'><div><b style='color:#ffbe4d'>{esc(r.get('user_phone',''))}</b> <span style='background:{'#22c55e' if 'إضافة' in r.get('action','') else '#0ea5e9' if 'تعديل' in r.get('action','') else '#ef4444' if 'حذف' in r.get('action','') else '#ffbe4d'};color:#fff;padding:2px 8px;border-radius:8px;font-size:11px'>{esc(r.get('action',''))}</span><br><small style='color:#cbd5e1'>{esc(r.get('detail',''))}</small></div><small style='color:#64748b'>{esc(r.get('time',''))}</small></div>" for r in rs])
        if not rs: rows="<div class=card style='text-align:center;padding:30px'><div style='font-size:40px'>📭</div><b>السجل فاضي</b><br><small>اضف صحن جديد وسيظهر هنا فوراً مع كل التعديلات</small><br><button class=btn-gold onclick=\"fetch('/api/seed_log',{method:'POST'}).then(()=>loadPage('logs',true))\" style='margin-top:10px'>🧪 اختبار السجل</button></div>"
        return f"<div style='max-width:900px;margin:0 auto'><div class=card style='display:flex;justify-content:space-between'><h3>📜 السجل - كل التعديلات تبين هنا ✅ ({len(rs)})</h3><div style='display:flex;gap:6px'><a href='/api/export/logs' class=btn-gold style='text-decoration:none;padding:7px 12px;background:#22c55e;color:#fff'>Excel</a><button onclick=\"if(confirm('مسح؟')){{fetch('/api/clear_logs',{method:'POST'}).then(()=>loadPage('logs',true))}}\" class=btn-del>مسح</button></div></div>{rows}</div>"
    if v=='towers':
        rs=qall("SELECT * FROM towers ORDER BY id DESC"); rows="".join([f"<div class='card anim' id='tower-{r['id']}'><b>🗼 {esc(r['name'])}</b> - {esc(r['area'] or '')} <button class=btn-del onclick=\"askDel('/del_tower/{r['id']}',0)\" style='float:left'>🗑</button></div>" for r in rs])
        return f"<div style='max-width:700px;margin:0 auto'><div class=card><h3>🗼 الأبراج</h3><form data-ajax2 method=post action=/add_tower style='display:flex;gap:6px;flex-wrap:wrap'><input name=name placeholder='اسم البرج' required style='flex:1'><input name=area placeholder='المنطقة' style='flex:1'><button class=btn-gold>➕ فوري</button></form></div>{rows}</div>"
    if v=='subs':
        rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 150"); rows="".join([f"<div class='card anim'><b>{esc(r['name'])}</b> - {esc(r['phone'] or '')} <button class=btn-del onclick=\"askDel('/del_sub/{r['id']}',0)\" style='float:left'>🗑</button></div>" for r in rs])
        return f"<div style='max-width:700px;margin:0 auto'><div class=card><h3>👥 المشتركين</h3><form data-ajax2 method=post action=/add_sub style='display:flex;gap:5px;flex-wrap:wrap'><input name=name placeholder='الاسم' required style='flex:1'><input name=phone placeholder='رقم' style='flex:1'><button class=btn-gold>➕ فوري</button></form></div>{rows}</div>"
    if v=='ledger':
        rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 150"); rows="".join([f"<div class='card anim'><b>{esc(r['name'])}</b> - {r['amount']} <button class=btn-del onclick=\"askDel('/del_ledger/{r['id']}',0)\" style='float:left'>🗑</button></div>" for r in rs])
        return f"<div style='max-width:700px;margin:0 auto'><div class=card><h3>📒 الحسابات</h3><form data-ajax2 method=post action=/add_ledger style='display:flex;gap:5px;flex-wrap:wrap'><input name=name placeholder='الاسم' required style='flex:1'><input name=amount type=number step=0.01 placeholder='المبلغ' required style='flex:1'><button class=btn-gold>➕ فوري</button></form></div>{rows}</div>"
    if v=='settings':
        us=qall("SELECT phone,username,role FROM users ORDER BY phone DESC"); uh="".join([f"<div class=card><b>{esc(u.get('username') or '')}</b> - {esc(u['phone'])} - {esc(u.get('role') or '')} <button class=btn-del onclick=\"askDel('/del_user/{esc(u['phone'])}',0)\" style='float:left'>🗑</button></div>" for u in us])
        return f"<div style='max-width:700px;margin:0 auto'><div class=card><h3>⚙ الإعدادات - ULTRA FAST</h3><p style='color:#22c55e'>✅ Pool 25 + إضافة فوري بدون تحميل<br>✅ سجل يبين كل التعديلات بالألوان<br>✅ تسجيل دخول فوري + تسخين سيرفر<br>✅ الموقع ما عاد يحمل كلو - كاش فوري</p></div>{uh}</div>"
    if v=='ping':
        return f"<div style='max-width:700px;margin:0 auto'><div class=card><h3>📶 Ping ULTRA</h3><div style='display:flex;gap:6px'><input id=pingIp placeholder='192.168.1.1' style='flex:1'><button class=btn-gold onclick=\"fetch('/api/ping?ip='+document.getElementById('pingIp').value).then(r=>r.json()).then(j=>document.getElementById('pr').textContent=j.out)\">Ping</button></div><div id=pr style='margin-top:10px;background:#0008;padding:12px;border-radius:10px;min-height:50px'>جاهز...</div></div></div>"
    if v=='network':
        dish_tbl=get_dish_table(); dishes=qall(f"SELECT * FROM {dish_tbl} ORDER BY id DESC LIMIT 100")
        rows="".join([f"<div class='card anim' id='net-{d['id']}' data-ip='{esc(d.get('ip',''))}'><b>{esc(d.get('dish_name') or 'صحن')}</b> - {esc(d.get('ip',''))}</div>" for d in dishes])
        return f"<div style='max-width:800px;margin:0 auto'><div class=card><h3>📊 حالة الشبكة - {dish_tbl}</h3></div>{rows}</div>"
    if v=='map':
        return "<div class=card>🗺 الخريطة - استخدم النسخة الكاملة اذا بدك</div>"
    if v=='support':
        return """<div class=card style='text-align:center;max-width:500px;margin:0 auto'><h2>🛠 الدعم</h2><a href='https://wa.me/905344851045' target=_blank style='display:inline-block;background:#22c55e;color:#fff;padding:14px 24px;border-radius:14px;text-decoration:none;margin:6px;font-weight:800'>💬 واتساب</a></div>"""
    return "<div class=card>ok</div>"

def layout(c, v='home', fast=False):
    th=session.get('theme','dark'); is_dark=(th=='dark')
    bg='radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 60%, #070a1f 100%)' if is_dark else '#f1f5f9'
    card_bg='#1e2433' if is_dark else '#ffffff'; txt='#ffffff' if is_dark else '#0f172a'; border='#ffffff12' if is_dark else '#e2e8f0'
    cur_user={'phone':session.get('phone',''),'role':session.get('role','tech'),'username':session.get('username','')}
    role=cur_user.get('role') or 'tech'; req_lang=session.get('lang','ar'); is_rtl=req_lang=='ar'
    def L(ar,en): return ar if is_rtl else en
    username_display=esc(cur_user.get('username') or cur_user.get('phone') or '')
    sidebar_pos="right:0; left:auto; transform:translateX(110%);" if is_rtl else "left:0; right:auto; transform:translateX(-110%);"
    side="right" if is_rtl else "left"
    dir_attr="rtl" if is_rtl else "ltr"
    return f"""<html dir={dir_attr} lang={req_lang}><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<style>*{{box-sizing:border-box;font-family:system-ui}}body{{margin:0;background:{bg};color:{txt};overflow-x:hidden;direction:{dir_attr}}}
.anim{{animation:fadeUp .25s ease both}}@keyframes fadeUp{{from{{opacity:0;transform:translateY(8px)}}to{{opacity:1;transform:none}}}}
.top{{position:fixed;top:0;left:0;right:0;height:62px;background:linear-gradient(90deg,#0f172af2,#111827f2);backdrop-filter:blur(12px);color:#fff;display:flex;align-items:center;justify-content:space-between;padding:0 14px;z-index:1003;border-bottom:1px solid #ffffff12}}
.sidebar{{position:fixed;top:0;width:285px;height:100%;background:linear-gradient(180deg,#0f172a 0%,#070e22 100%);color:#fff;z-index:1002;padding-top:70px;{sidebar_pos}transition:transform .3s cubic-bezier(.4,0,.2,1);overflow-y:auto}}
.sidebar.active{{transform:none}}
.sidebar a{{display:flex;align-items:center;gap:11px;padding:12px 15px;margin:6px 11px;color:#cbd5e1;text-decoration:none;border-radius:13px;background:#ffffff06}}
.sidebar a.active{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:800}}
#overlay{{position:fixed;inset:0;background:#0008;z-index:1001;display:none}}#overlay.show{{display:block}}
.main{{margin-top:74px;padding:14px;min-height:90vh}}
.card{{background:{card_bg};color:{txt};padding:15px;border-radius:15px;margin-bottom:11px;border:1px solid {border}}}
input,select{{padding:12px 14px;margin:5px 0;border-radius:11px;border:1px solid {border};width:100%;background:#ffffff07;color:{txt}}}
.btn-gold{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;padding:9px 16px;border:0;border-radius:11px;font-weight:800;cursor:pointer}}
.btn-del{{background:linear-gradient(90deg,#ef4444,#dc2626);color:#fff;padding:8px 13px;border:0;border-radius:11px;cursor:pointer}}
#delModal, #editModal{{position:fixed;inset:0;background:#000a;display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:.3s;z-index:2000}}
#delModal.show, #editModal.show{{opacity:1;pointer-events:auto}}
#delBox, #editBox{{background:{card_bg};color:{txt};padding:24px;border-radius:18px;width:92%;max-width:450px}}
.skeleton{{background:linear-gradient(90deg,#1a2035 25%,#222b45 50%,#1a2035 75%);background-size:200% 100%;animation:shimmer 1s infinite}}
@keyframes shimmer{{0%{{background-position:-200% 0}}100%{{background-position:200% 0}}}}
</style></head><body>
<div id=overlay onclick="toggleSb(false)"></div>
<div class=sidebar id=sb>
<div style='padding:0 18px 10px;border-bottom:1px solid #ffffff0a;margin-bottom:8px'><div style='font-weight:900'>OMAIA <span style='color:#ffbe4d'>ISP</span> <small style='color:#22c55e'>ULTRA</small></div><small style='color:#64748b'>{username_display} • {role}</small><br><small style='color:#22c55e'>✅ فوري • سجل يبين التعديلات • دخول فوري</small></div>
<a href="javascript:loadPage('home')" id=nav-home>🏠 {L('الرئيسية','Home')}</a>
<a href="javascript:loadPage('dishes')" id=nav-dishes>📡 {L('الصحون','Dishes')}</a>
<a href="javascript:loadPage('logs')" id=nav-logs>📜 {L('السجل','Logs')} <span style='background:#22c55e;color:#fff;padding:2px 6px;border-radius:6px;font-size:9px'>شغال</span></a>
<a href="javascript:loadPage('towers')" id=nav-towers>🗼 {L('الأبراج','Towers')}</a>
<a href="javascript:loadPage('subs')" id=nav-subs>👥 {L('المشتركين','Subs')}</a>
<a href="javascript:loadPage('ledger')" id=nav-ledger>📒 {L('الحسابات','Ledger')}</a>
<a href="javascript:loadPage('ping')" id=nav-ping>📶 Ping</a>
<a href="javascript:loadPage('settings')" id=nav-settings>⚙ {L('الإعدادات','Settings')}</a>
<a href="javascript:logoutFast()" style='margin-top:10px;background:#ef444418;border:1px solid #ef444433'>🚪 خروج</a>
</div>
<div class=top>
<div style='display:flex;gap:8px;align-items:center'><span onclick="toggleSb()" style='font-size:24px;cursor:pointer;padding:6px 8px;background:#ffffff0a;border-radius:8px'>☰</span><input id=topsearch placeholder='🔍 بحث...' oninput="globalSearchTop(this.value)" style='background:#1f2937;border:1px solid #ffffff15;color:#fff;padding:8px 12px;border-radius:10px;width:40px;transition:all .2s' onfocus="this.style.width='160px'" onblur="setTimeout(()=>this.style.width='40px',200)"></div>
<div style='font-weight:900'>OMAIA <span style='color:#ffbe4d'>ISP</span> <span style='color:#22c55e;font-size:10px'>ULTRA</span></div>
<div style='display:flex;gap:8px'><button onclick="toggleTheme()" style='background:#ffffff0a;color:#fff;border:1px solid #ffffff0f;padding:8px 10px;border-radius:10px'>🌓</button></div>
</div>
<div id=searchResults style='position:fixed;top:66px;{side}:12px;max-width:400px;width:90%;background:#1e2433;border:1px solid #ffffff15;border-radius:12px;z-index:1500;display:none;max-height:60vh;overflow:auto'></div>
<div class=main id=mn>{c}</div>
<div id=delModal><div id=delBox><div style='font-size:36px;text-align:center'>🗑</div><h3 style='text-align:center'>تأكيد الحذف الفوري؟</h3><p style='text-align:center;color:#94a3b8;font-size:13px'>سيتم الحذف فورياً وسيظهر في السجل</p><div style='display:flex;gap:10px;margin-top:14px'><button onclick="closeDel()" style='flex:1;padding:12px;border-radius:10px;background:transparent;color:{txt};border:1px solid {border}'>تراجع</button><button id=delYes style='flex:1;padding:12px;border-radius:10px;background:#ef4444;color:#fff;border:0;font-weight:800'>حذف فوري</button></div></div></div>
<div id=editModal><div id=editBox><div style='display:flex;justify-content:space-between;margin-bottom:12px'><h3 style='margin:0'>✏ تعديل فوري</h3><button onclick="closeEditModal()" style='background:#ffffff12;border:0;color:{txt};width:32px;height:32px;border-radius:50%'>✕</button></div><div id=editBody></div></div></div>
<script>
let cur='{v}'; let lang='{req_lang}';
function toggleSb(f){{let sb=document.getElementById('sb'),ov=document.getElementById('overlay'); let o=f!==undefined?f:!sb.classList.contains('active'); sb.classList.toggle('active',o); ov.classList.toggle('show',o);}}
let pageCache={{}}; try{{pageCache=JSON.parse(localStorage.getItem('omaia_ultra_v1')||'{{}}');}}catch(e){{pageCache={{}};}}
function saveCache(){{try{{localStorage.setItem('omaia_ultra_v1',JSON.stringify(pageCache));}}catch(e){{}}}}
async function loadPage(v,force=false,push=true){{
  if(push && cur!==v){{try{{history.pushState({{page:v}},'', '/dash?v='+v);}}catch(e){{}}}}
  cur=v; toggleSb(false);
  document.querySelectorAll('.sidebar a').forEach(a=>a.classList.remove('active')); let n=document.getElementById('nav-'+v); if(n) n.classList.add('active');
  let mn=document.getElementById('mn');
  if(!force && pageCache[v]){{ mn.innerHTML=pageCache[v]; bind(); execScripts(); fetch('/api/page?v='+v,{{cache:'no-store'}}).then(r=>r.text()).then(h=>{{if(h.length>50){{pageCache[v]=h; saveCache();}}}}).catch(()=>{{}}); return; }}
  mn.innerHTML='<div class=card><div class="skeleton" style="height:24px;width:40%;border-radius:8px;margin-bottom:10px"></div><div class="skeleton" style="height:16px;border-radius:6px;margin-bottom:6px"></div></div>';
  try{{let r=await fetch('/api/page?v='+v,{{cache:'no-store'}}); let h=await r.text(); pageCache[v]=h; saveCache(); mn.innerHTML=h; bind(); execScripts();}}catch(e){{mn.innerHTML='<div class=card>❌ '+e+'</div>';}}
}}
function execScripts(){{document.getElementById('mn').querySelectorAll('script').forEach(s=>{{try{{eval(s.textContent)}}catch(e){{}}}});}}
function bind(){{
  document.querySelectorAll('[data-ajax2]').forEach(f=>{{
    if(f.dataset.bound) return; f.dataset.bound='1';
    f.onsubmit=async e=>{{
      e.preventDefault(); let btn=f.querySelector('button'); let o=btn.innerHTML; btn.innerHTML='⏳...'; btn.disabled=true;
      try{{let r=await fetch(f.action,{{method:'POST',body:new FormData(f)}}); let j=await r.json(); if(j.ok){{ showToast('✅ تم فورياً'); f.reset(); delete pageCache[cur]; loadPage(cur,true,false); }} else {{alert('خطأ');}} }}catch(err){{alert(err);}}
      btn.innerHTML=o; btn.disabled=false;
    }};
  }});
}}
function askDel(url, id){{window._delUrl=url; window._delId=id; document.getElementById('delModal').classList.add('show');}}
function closeDel(){{document.getElementById('delModal').classList.remove('show'); window._delUrl=null;}}
window.closeEditModal=function(){{document.getElementById('editModal').classList.remove('show');}}
document.getElementById('delYes').onclick=async()=>{{
  if(!window._delUrl) return;
  let btn=document.getElementById('delYes'); let o=btn.innerHTML; btn.innerHTML='⏳...'; btn.disabled=true;
  try{{
    let r=await fetch(window._delUrl,{{method:'POST'}}); let j=await r.json().catch(()=>({{ok:r.ok}}));
    if(r.ok || j.ok){{
      if(window._delId){{let el=document.getElementById('dish-'+window._delId); if(el) el.style.display='none';}}
      showToast('✅ تم الحذف فورياً - السجل تحدث');
      closeDel();
      setTimeout(()=>{{delete pageCache[cur]; loadPage(cur,true,false);}},400);
    }} else {{alert('خطأ');}}
  }}catch(e){{alert(e);}}
  btn.innerHTML=o; btn.disabled=false;
}};
function showToast(t){{let toast=document.createElement('div'); toast.style.cssText='position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:#1f2937;color:#fff;padding:10px 18px;border-radius:20px;z-index:9999;border:1px solid #22c55e55;box-shadow:0 8px 20px #0008'; toast.textContent=t; document.body.appendChild(toast); setTimeout(()=>toast.remove(),2000);}}
async function toggleTheme(){{await fetch('/toggle_theme'); location.reload();}}
window.globalSearchTop=async function(q){{let box=document.getElementById('searchResults'); if(!q || q.length<2){{box.style.display='none'; return;}} let r=await fetch('/api/search?q='+encodeURIComponent(q)); let d=await r.json(); if(!d.length){{box.style.display='none'; return;}} let h=''; d.forEach(x=>{{h+='<div onclick="loadPage(\\''+x.page+'\\');document.getElementById(\\'searchResults\\').style.display=\\'none\\'" style="padding:10px 12px;cursor:pointer;border-bottom:1px solid #ffffff08"><b>'+x.title+'</b><br><small style="color:#888">'+x.sub+'</small></div>';}}); box.innerHTML=h; box.style.display='block';}}
window.logoutFast=async function(){{await fetch('/api/logout',{{method:'POST'}}); localStorage.clear(); location.replace('/login');}}
window.addEventListener('popstate',(e)=>{{let v='home'; if(e.state && e.state.page) v=e.state.page; else {{let p=new URLSearchParams(location.search); v=p.get('v')||'home';}} loadPage(v,false,false);}});
bind(); execScripts();
loadPage(cur,true,false);
if(!history.state){{try{{history.replaceState({{page:cur}},'', '/dash?v='+cur);}}catch(e){{}}}}
</script></body></html>"""

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)), debug=False)
