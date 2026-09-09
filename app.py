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

def init_pg_pool():
    global _pg_pool
    if not USE_PG:
        return
    with _pg_pool_lock:
        if _pg_pool:
            return
        try:
            _pg_pool = pg_pool.ThreadedConnectionPool(1, 20, dsn=DATABASE_URL, sslmode='require', connect_timeout=3, keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=3)
            print("[POOL] created")
        except Exception as e:
            print(f"[POOL ERROR] {e}")
            _pg_pool = None
init_pg_pool()

def esc(s): return html.escape(str(s or ''), quote=True)

def get_conn():
    if USE_PG:
        if _pg_pool:
            try:
                return _pg_pool.getconn()
            except:
                return psycopg2.connect(DATABASE_URL, sslmode='require', connect_timeout=3)
        else:
            return psycopg2.connect(DATABASE_URL, sslmode='require', connect_timeout=3)
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
    conn = None
    try:
        conn = get_conn()
        if USE_PG:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(q.replace("?", "%s"), a)
            rs = [dict(r) for r in cur.fetchall()]
            cur.close()
            put_conn(conn)
            return rs
        else:
            with _sqlite_lock:
                rs = [dict(r) for r in conn.execute(q, a).fetchall()]
            return rs
    except Exception as e:
        print(f"[qall] {e} | {q}")
        if conn and USE_PG:
            try: put_conn(conn)
            except: pass
        return []

def qone(q, a=()):
    r = qall(q, a)
    return r[0] if r else None

def qexec(q, a=()):
    conn = None
    try:
        conn = get_conn()
        if USE_PG:
            cur = conn.cursor()
            cur.execute(q.replace("?", "%s"), a)
            conn.commit()
            cur.close()
            put_conn(conn)
        else:
            with _sqlite_lock:
                conn.execute(q, a)
                conn.commit()
        return True
    except Exception as e:
        print(f"[qexec] {e} | {q}")
        if conn and USE_PG:
            try:
                try: conn.rollback()
                except: pass
                put_conn(conn)
            except: pass
        return False

# ===== سجل سريع بدون ما يبطئ =====
def _log_async(phone, action, detail):
    try:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)", (phone or 'system', action, detail, now))
    except: pass

def log_action(phone, action, detail):
    # يشتغل بالخلفية مشان ما يبطئ الإضافة/التعديل/الحذف
    try:
        threading.Thread(target=_log_async, args=(phone, action, detail), daemon=True).start()
    except: pass

def _sync_other_table(other, ip, name, loc, is_update=False, old_ip=None):
    try:
        if is_update:
            # تحديث الجدول الثاني
            qexec(f"UPDATE {other} SET dish_name=?,location=?,ip=? WHERE ip=?", (name, loc, ip, old_ip or ip))
        else:
            # إدخال إذا مو موجود
            ex = qone(f"SELECT id FROM {other} WHERE ip=?", (ip,))
            if not ex:
                qexec(f"INSERT INTO {other}(ip,location,dish_name) VALUES(?,?,?)", (ip, loc, name))
    except: pass

def sync_other_async(other, ip, name, loc, is_update=False, old_ip=None):
    try:
        threading.Thread(target=_sync_other_table, args=(other, ip, name, loc, is_update, old_ip), daemon=True).start()
    except: pass

def get_dish_table():
    with _cache_lock:
        c = _cache.get('dish_table')
        if c and time.time() - c[1] < 120:
            return c[0]
    if not USE_PG:
        return "dish_ips"
    try:
        rows = qall("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name IN ('ips','dish_ips')")
        names = [r.get('table_name') for r in rows]
        tbl = "ips" if 'ips' in names else "dish_ips"
        with _cache_lock:
            _cache['dish_table'] = (tbl, time.time())
        return tbl
    except:
        return "dish_ips"

def init():
    if USE_PG:
        tables = [
            "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,username TEXT)",
            "CREATE TABLE IF NOT EXISTS subs(id SERIAL PRIMARY KEY,name TEXT,phone TEXT,note TEXT)",
            "CREATE TABLE IF NOT EXISTS ledger(id SERIAL PRIMARY KEY,name TEXT,amount REAL,note TEXT,currency TEXT)",
            "CREATE TABLE IF NOT EXISTS dish_ips(id SERIAL PRIMARY KEY,ip TEXT,location TEXT,dish_name TEXT)",
            "CREATE TABLE IF NOT EXISTS towers(id SERIAL PRIMARY KEY,name TEXT,area TEXT,lat DOUBLE PRECISION,lng DOUBLE PRECISION)",
            "CREATE TABLE IF NOT EXISTS logs(id SERIAL PRIMARY KEY,user_phone TEXT,action TEXT,detail TEXT,time TEXT)",
            "CREATE TABLE IF NOT EXISTS notifications(id SERIAL PRIMARY KEY,title TEXT,msg TEXT,time TEXT,read INTEGER DEFAULT 0)",
            "CREATE TABLE IF NOT EXISTS ips(id SERIAL PRIMARY KEY, ip TEXT, location TEXT, dish_name TEXT, created_at TIMESTAMP DEFAULT NOW())"
        ]
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_dish_ips_ip ON dish_ips(ip)",
            "CREATE INDEX IF NOT EXISTS idx_ips_ip ON ips(ip)",
            "CREATE INDEX IF NOT EXISTS idx_logs_time ON logs(time)",
            "CREATE INDEX IF NOT EXISTS idx_subs_name ON subs(name)",
            "CREATE INDEX IF NOT EXISTS idx_towers_name ON towers(name)"
        ]
    else:
        tables = [
            "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,username TEXT)",
            "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,note TEXT)",
            "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,amount REAL,note TEXT,currency TEXT)",
            "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,dish_name TEXT)",
            "CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,area TEXT,lat REAL,lng REAL)",
            "CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,user_phone TEXT,action TEXT,detail TEXT,time TEXT)",
            "CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,msg TEXT,time TEXT,read INTEGER DEFAULT 0)",
            "CREATE TABLE IF NOT EXISTS ips(id INTEGER PRIMARY KEY AUTOINCREMENT, ip TEXT, location TEXT, dish_name TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        ]
        indexes = []
    for s in tables: qexec(s)
    for s in indexes: qexec(s)
    if not qone("SELECT * FROM users WHERE phone=?", ('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)", ('05344851045', generate_password_hash('admin2024'), 'manager', 'admin'))
    if not qone("SELECT * FROM towers WHERE name=?", ('نقطة حماة الرئيسية',)):
        qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)", ('نقطة حماة الرئيسية', 'حماة', 35.1318, 36.7578))
init()

def login_required(f):
    @wraps(f)
    def w(*a, **kw):
        if not session.get('phone'): return redirect('/login')
        return f(*a, **kw)
    return w

def is_manager():
    u = qone("SELECT * FROM users WHERE phone=?", (session.get('phone') or '',))
    return (u.get('role') or '').lower() == 'manager' if u else False

def role_required_manager(f):
    @wraps(f)
    def w(*a, **kw):
        if not is_manager(): return "ممنوع", 403
        return f(*a, **kw)
    return w

def is_valid_ip(ip):
    ip = (ip or '').strip()
    if not ip: return False
    try: ipaddress.ip_address(ip); return True
    except: return False

@app.after_request
def add_perf_headers(resp):
    if request.path.startswith('/api/'): resp.headers['Cache-Control'] = 'no-store, max-age=0'
    else: resp.headers['Cache-Control'] = 'no-cache'
    resp.headers['X-Accel-Buffering'] = 'no'
    return resp

@app.route('/ping')
@app.route('/health')
def public_ping():
    pg_ok = False; err = None; tbl = get_dish_table()
    if USE_PG:
        try:
            if _pg_pool:
                c = _pg_pool.getconn(); _pg_pool.putconn(c); pg_ok = True
            else:
                c = psycopg2.connect(DATABASE_URL, sslmode='require', connect_timeout=2); c.close(); pg_ok = True
        except Exception as e: err = str(e)[:300]
    else: err = "SQLite"
    return jsonify(ok=True, pg=pg_ok, error=err, time=datetime.datetime.now().isoformat(), table=tbl, pool=bool(_pg_pool))

@app.route('/api/ping')
@login_required
def api_ping():
    ip = request.args.get('ip','').strip()
    if not ip: return jsonify(ok=False, out='لا يوجد IP')
    if not is_valid_ip(ip): return jsonify(ok=False, out='IP غير صالح')
    for port in [80,443,8080,8291,22,23,53,8000,8728]:
        s=None
        try:
            s=socket.socket(socket.AF_INET,socket.SOCK_STREAM); s.settimeout(0.6)
            if s.connect_ex((ip,port))==0: s.close(); return jsonify(ok=True,out=f'✅ متصل - {ip}:{port} مفتوح',port=port,method='tcp')
            s.close()
        except:
            try:
                if s: s.close()
            except: pass
            continue
    try:
        cmd=['ping','-c','1','-W','1',ip] if platform.system().lower()!='windows' else ['ping','-n','1','-w','1000',ip]
        out=subprocess.check_output(cmd,timeout=2,stderr=subprocess.STDOUT).decode(errors='ignore')
        ok='ttl=' in out.lower() or 'bytes from' in out.lower() or '1 received' in out.lower()
        if ok:
            m=re.search(r'time[=<]\s*(\d+\.?\d*)',out,re.I); ms=m.group(1) if m else ''
            return jsonify(ok=True,out=f'✅ متصل {ip} - {ms}ms',ms=ms,method='icmp')
    except: pass
    return jsonify(ok=False,out=f'❌ {ip} لا يرد')

@app.route('/api/ping_tcp')
@login_required
def api_ping_tcp():
    ip=request.args.get('ip','').strip(); port_str=request.args.get('port','80').strip()
    try:
        port=int(port_str)
        if not 1<=port<=65535: raise ValueError()
    except: return jsonify(ok=False,out='Port غير صالح')
    if not is_valid_ip(ip): return jsonify(ok=False,out='IP غير صالح')
    s=None
    try:
        s=socket.socket(socket.AF_INET,socket.SOCK_STREAM); s.settimeout(1.0); r=s.connect_ex((ip,port)); s.close()
        return jsonify(ok=r==0,out=f'✅ {ip}:{port} مفتوح' if r==0 else f'❌ {ip}:{port} مغلق')
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
    cnt=unread.get('c',0) if unread else 0
    return jsonify(rows=rows,unread=cnt)

@app.route('/api/notifications/read', methods=['POST'])
@login_required
def api_noti_read():
    qexec("UPDATE notifications SET read=1"); return jsonify(ok=True)

@app.route('/api/network_status')
@login_required
def api_network():
    tbl=get_dish_table()
    dishes=qall(f"SELECT COUNT(*) as c FROM {tbl}")
    towers=qall("SELECT COUNT(*) as c FROM towers")
    subs_cnt=(qone("SELECT COUNT(*) as c FROM subs") or {}).get('c',0)
    d_cnt=dishes[0].get('c',0) if dishes else 0
    t_cnt=towers[0].get('c',0) if towers else 0
    return jsonify(dishes=d_cnt,towers=t_cnt,subs=subs_cnt)

@app.route('/toggle_lang')
@login_required
def toggle_lang_route():
    cur=session.get('lang','ar'); new='en' if cur=='ar' else 'ar'; session['lang']=new; return jsonify(ok=True,lang=new)

@app.route('/api/login_public', methods=['POST'])
def api_login_public():
    uin=request.form.get('userin','').strip(); pw=request.form.get('password','')
    u=qone("SELECT * FROM users WHERE phone=? OR username=?", (uin, uin))
    if u and check_password_hash(u['password'], pw):
        session['phone']=u['phone']; session['username']=u.get('username') or u['phone']; session.permanent=True
        log_action(u['phone'], 'login', 'دخول')
        return jsonify(ok=True, role=u.get('role'))
    return jsonify(ok=False, msg='خطأ بالدخول'), 401

@app.route('/api/export/<tbl>')
@login_required
def api_export(tbl):
    output=io.StringIO(); output.write('\ufeff'); w=csv.writer(output); dish_tbl=get_dish_table()
    if tbl=='dishes':
        rows=qall(f"SELECT * FROM {dish_tbl} ORDER BY id DESC"); w.writerow(['ID','اسم الصحن','IP','الموقع'])
        for r in rows: w.writerow([r.get('id',''),r.get('dish_name',''),r.get('ip',''),r.get('location','')]); fname='dishes.csv'
    elif tbl=='subs':
        rows=qall("SELECT * FROM subs ORDER BY id DESC"); w.writerow(['ID','الاسم','رقم','ملاحظة'])
        for r in rows: w.writerow([r.get('id',''),r.get('name',''),r.get('phone',''),r.get('note','')]); fname='subs.csv'
    elif tbl=='users':
        rows=qall("SELECT phone,username,role FROM users ORDER BY phone DESC"); w.writerow(['يوزر/رقم','اسم المستخدم','الرتبة'])
        for r in rows: w.writerow([r.get('phone',''),r.get('username',''),r.get('role','')]); fname='users.csv'
    elif tbl=='towers':
        rows=qall("SELECT * FROM towers ORDER BY id DESC"); w.writerow(['ID','اسم البرج','المنطقة','lat','lng'])
        for r in rows: w.writerow([r.get('id',''),r.get('name',''),r.get('area',''),r.get('lat',''),r.get('lng','')]); fname='towers.csv'
    elif tbl=='logs':
        rows=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 1000"); w.writerow(['ID','المستخدم','العملية','التفاصيل','الوقت'])
        for r in rows: w.writerow([r.get('id',''),r.get('user_phone',''),r.get('action',''),r.get('detail',''),r.get('time','')]); fname='logs.csv'
    else: w.writerow(['ID']); fname='export.csv'
    return Response(output.getvalue(), mimetype='text/csv; charset=utf-8', headers={'Content-Disposition': f'attachment; filename={fname}'})

@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login')
def login():
    return """<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<style>*{box-sizing:border-box;font-family:system-ui}body{margin:0;min-height:100vh;background:radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 55%, #070a1f 100%);display:flex;flex-direction:column;align-items:center;justify-content:center;color:#fff}
.card{background:linear-gradient(180deg, #222b45cc, #1a2035cc);backdrop-filter:blur(16px);border:1px solid #ffffff18;padding:26px;border-radius:22px;width:92%;max-width:380px;box-shadow:0 20px 60px #0008}
input{width:100%;padding:14px;margin:9px 0;background:#0f1424;border:1px solid #ffffff22;color:#fff;border-radius:14px;font-size:15px}
.btn{width:100%;padding:14px;border:0;border-radius:14px;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:900;font-size:17px;cursor:pointer;margin-top:12px;transition:all .15s}
.btn:active{transform:scale(0.97)}
.btn:disabled{opacity:.6}
.spinner{display:inline-block;width:16px;height:16px;border:2px solid #1115;border-top-color:#111;border-radius:50%;animation:spin .6s linear infinite;vertical-align:middle;margin-left:6px}
@keyframes spin{to{transform:rotate(360deg)}}</style></head><body>
<div style='font-size:30px;font-weight:900;margin-bottom:14px'>OMAIA <span style='color:#ffbe4d'>ISP</span> <small style='color:#22c55e'>⚡</small></div>
<div class=card><form id=loginForm><input name=userin id=userin placeholder='📱 رقم / يوزر' required autocomplete=username><input name=password id=password type=password placeholder='🔑 كلمة السر' required autocomplete=current-password><label style='display:flex;gap:8px;font-size:13px;color:#aaa;margin:8px 0'><input type=checkbox id=savePass style='width:auto'> حفظ</label><button class=btn id=loginBtn>✨ دخول فوري</button><div id=msg style='text-align:center;margin-top:10px;color:#ff6b6b;font-size:13px;min-height:18px'></div></form></div>
<script>
let u=document.getElementById('userin'), p=document.getElementById('password'), s=document.getElementById('savePass');
let su=localStorage.getItem('omaia_user'), sp=localStorage.getItem('omaia_pass');
if(su){u.value=su; if(sp){p.value=sp; s.checked=true;}}
document.getElementById('loginForm').addEventListener('submit',async e=>{
 e.preventDefault(); let btn=document.getElementById('loginBtn'), msg=document.getElementById('msg');
 if(btn.disabled) return;
 let orig=btn.innerHTML;
 btn.innerHTML='<span class=spinner></span> ثواني...'; btn.disabled=true; msg.textContent='';
 try{
  let fd=new FormData(e.target);
  let r=await fetch('/api/login_public',{method:'POST',body:fd,cache:'no-store'});
  let j=await r.json();
  if(j.ok){
    if(s.checked){localStorage.setItem('omaia_user',u.value);localStorage.setItem('omaia_pass',p.value);}
    msg.style.color='#22c55e'; msg.textContent='✅ تم...';
    setTimeout(()=>location.replace('/dash?v=home'),120);
  } else { msg.style.color='#ff6b6b'; msg.textContent=j.msg||'خطأ'; btn.innerHTML=orig; btn.disabled=false; }
 }catch(err){ msg.style.color='#ff6b6b'; msg.textContent='خطأ شبكة'; btn.innerHTML=orig; btn.disabled=false; }
});
</script></body></html>"""

@app.route('/logout')
def lo(): session.clear(); return redirect('/login')
@app.route('/api/logout', methods=['POST'])
def api_logout(): session.clear(); return jsonify(ok=True)

@app.route('/dash')
@login_required
def dash():
    v=request.args.get('v','home'); return layout(page_content(v), v)

@app.route('/api/page')
@login_required
def ap(): return page_content(request.args.get('v','home'))

@app.route('/api/search')
@login_required
def s():
    q=request.args.get('q','').strip()
    if not q or len(q)<2: return jsonify([])
    like="%"+q+"%"; results=[]; dish_tbl=get_dish_table()
    try:
        for r in qall(f"SELECT * FROM {dish_tbl} WHERE ip LIKE ? OR dish_name LIKE ? OR location LIKE ? ORDER BY id DESC LIMIT 15", (like,like,like)):
            results.append({"title": r.get('dish_name') or r.get('ip') or 'صحن', "sub": r.get('ip',''), "page": "dishes", "type": "dish"})
        if len(results)<20:
            for r in qall("SELECT * FROM subs WHERE name LIKE ? OR phone LIKE ? ORDER BY id DESC LIMIT 10", (like,like)):
                results.append({"title": r.get('name',''), "sub": r.get('phone',''), "page": "subs", "type": "sub"})
        if len(results)<20:
            for r in qall("SELECT * FROM towers WHERE name LIKE ? OR area LIKE ? ORDER BY id DESC LIMIT 10", (like,like)):
                results.append({"title": r.get('name',''), "sub": r.get('area',''), "page": "towers", "type": "tower"})
    except: pass
    return jsonify(results[:20])

@app.route('/toggle_theme')
@login_required
def tt():
    cur=session.get('theme','dark'); session['theme']='light' if cur=='dark' else 'dark'; return jsonify(ok=True)

@app.route('/add_dish', methods=['POST'])
@login_required
def ad():
    dish_tbl=get_dish_table(); ip=request.form.get('ip','').strip(); name=request.form.get('dish_name','').strip(); loc=request.form.get('location','').strip()
    if not ip: return "IP مطلوب",400
    if not is_valid_ip(ip): return "IP غير صالح",400
    ex=qone(f"SELECT * FROM {dish_tbl} WHERE ip=?", (ip,))
    phone=session.get('phone','')
    if ex:
        ok=qexec(f"UPDATE {dish_tbl} SET dish_name=?,location=? WHERE ip=?", (name, loc, ip))
        other="dish_ips" if dish_tbl=="ips" else "ips"
        sync_other_async(other, ip, name, loc, is_update=True, old_ip=ip)
        if ok: log_action(phone, 'تعديل صحن', f'{name} {ip}')
        return "ok updated" if ok else "خطأ", 400 if not ok else 200
    ok=qexec(f"INSERT INTO {dish_tbl}(ip,location,dish_name) VALUES(?,?,?)", (ip, loc, name))
    other="dish_ips" if dish_tbl=="ips" else "ips"
    sync_other_async(other, ip, name, loc)
    if ok: log_action(phone, 'إضافة صحن', f'{name} {ip}')
    return "ok" if ok else "خطأ", 200 if ok else 400

@app.route('/edit_dish/<int:i>', methods=['POST'])
@login_required
def ed(i):
    if not is_manager(): return "ممنوع للفني",403
    dish_tbl=get_dish_table()
    old=qone(f"SELECT ip FROM {dish_tbl} WHERE id=?", (i,))
    old_ip=old.get('ip') if old else ''
    new_ip=request.form.get('ip','').strip()
    new_name=request.form.get('dish_name','').strip()
    new_loc=request.form.get('location','').strip()
    ok=qexec(f"UPDATE {dish_tbl} SET dish_name=?,ip=?,location=? WHERE id=?", (new_name, new_ip, new_loc, i))
    if ok:
        other="dish_ips" if dish_tbl=="ips" else "ips"
        sync_other_async(other, new_ip, new_name, new_loc, is_update=True, old_ip=old_ip)
        log_action(session.get('phone'), 'تعديل صحن', f'ID {i} -> {new_ip}')
    return "ok" if ok else "خطأ", 200 if ok else 400

@app.route('/del_dish/<int:i>')
@login_required
def dd(i):
    if not is_manager(): return "ممنوع للفني",403
    dish_tbl=get_dish_table()
    info=qone(f"SELECT ip,dish_name FROM {dish_tbl} WHERE id=?", (i,))
    ok=qexec(f"DELETE FROM {dish_tbl} WHERE id=?", (i,))
    if ok:
        log_action(session.get('phone'), 'حذف صحن', f"{info.get('dish_name','')} {info.get('ip','')}" if info else f"ID {i}")
    return "ok" if ok else "خطأ", 200 if ok else 400

@app.route('/add_tower', methods=['POST'])
@login_required
def at():
    lat=request.form.get('lat','').strip(); lng=request.form.get('lng','').strip()
    try: la=float(lat) if lat else 35.1312; ln=float(lng) if lng else 36.7578
    except: la=35.1312; ln=36.7578
    ok=qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)", (request.form.get('name',''), request.form.get('area',''), la, ln))
    if ok: log_action(session.get('phone'), 'إضافة برج', request.form.get('name',''))
    return "ok" if ok else "خطأ", 200 if ok else 400

@app.route('/del_tower/<int:i>')
@login_required
def dt(i):
    if not is_manager(): return "ممنوع للفني",403
    ok=qexec("DELETE FROM towers WHERE id=?", (i,))
    if ok: log_action(session.get('phone'), 'حذف برج', f"ID {i}")
    return "ok" if ok else "خطأ", 200 if ok else 400

@app.route('/edit_tower/<int:i>', methods=['POST'])
@login_required
def et(i):
    if not is_manager(): return "ممنوع للفني",403
    lat=request.form.get('lat','').strip(); lng=request.form.get('lng','').strip()
    try: la=float(lat) if lat else 35.1318; ln=float(lng) if lng else 36.7578
    except: la=35.1318; ln=36.7578
    ok=qexec("UPDATE towers SET name=?,area=?,lat=?,lng=? WHERE id=?", (request.form.get('name',''), request.form.get('area',''), la, ln, i))
    if ok: log_action(session.get('phone'), 'تعديل برج', f"ID {i}")
    return "ok" if ok else "خطأ", 200 if ok else 400

@app.route('/add_sub', methods=['POST'])
@login_required
def asub():
    ok=qexec("INSERT INTO subs(name,phone,note) VALUES(?,?,?)", (request.form.get('name',''), request.form.get('phone',''), request.form.get('note','')))
    if ok: log_action(session.get('phone'), 'إضافة مشترك', request.form.get('name',''))
    return "ok" if ok else "خطأ", 200 if ok else 400

@app.route('/del_sub/<int:i>')
@login_required
def dsub(i):
    if not is_manager(): return "ممنوع للفني",403
    ok=qexec("DELETE FROM subs WHERE id=?", (i,))
    if ok: log_action(session.get('phone'), 'حذف مشترك', f"ID {i}")
    return "ok" if ok else "خطأ", 200 if ok else 400

@app.route('/edit_sub/<int:i>', methods=['POST'])
@login_required
def esub(i):
    if not is_manager(): return "ممنوع للفني",403
    ok=qexec("UPDATE subs SET name=?,phone=?,note=? WHERE id=?", (request.form.get('name',''), request.form.get('phone',''), request.form.get('note',''), i))
    if ok: log_action(session.get('phone'), 'تعديل مشترك', f"ID {i}")
    return "ok" if ok else "خطأ", 200 if ok else 400

@app.route('/add_ledger', methods=['POST'])
@login_required
def al():
    try: amt=float(request.form.get('amount') or 0)
    except: amt=0
    ok=qexec("INSERT INTO ledger(name,amount,note,currency) VALUES(?,?,?,?)", (request.form.get('name',''), amt, request.form.get('note',''), request.form.get('currency','USD')))
    if ok: log_action(session.get('phone'), 'إضافة حساب', f"{request.form.get('name','')} {amt}")
    return "ok" if ok else "خطأ", 200 if ok else 400

@app.route('/del_ledger/<int:i>')
@login_required
def dll(i):
    if not is_manager(): return "ممنوع للفني",403
    ok=qexec("DELETE FROM ledger WHERE id=?", (i,))
    if ok: log_action(session.get('phone'), 'حذف حساب', f"ID {i}")
    return "ok" if ok else "خطأ", 200 if ok else 400

@app.route('/edit_ledger/<int:i>', methods=['POST'])
@login_required
def el(i):
    if not is_manager(): return "ممنوع للفني",403
    try: amt=float(request.form.get('amount') or 0)
    except: amt=0
    ok=qexec("UPDATE ledger SET name=?,amount=?,note=?,currency=? WHERE id=?", (request.form.get('name',''), amt, request.form.get('note',''), request.form.get('currency','USD'), i))
    if ok: log_action(session.get('phone'), 'تعديل حساب', f"ID {i}")
    return "ok" if ok else "خطأ", 200 if ok else 400

@app.route('/add_user', methods=['POST'])
@login_required
@role_required_manager
def au():
    ph=request.form.get('phone','').strip() or request.form.get('user_field','').strip()
    if not ph: return "رقم مطلوب",400
    if qone("SELECT * FROM users WHERE phone=?", (ph,)): return "موجود مسبقاً",400
    ok=qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)", (ph, generate_password_hash(request.form.get('password','1234')), request.form.get('role','tech'), ph))
    if ok: log_action(session.get('phone'), 'إضافة يوزر', ph)
    return "ok" if ok else "خطأ", 200 if ok else 400

@app.route('/edit_user', methods=['POST'])
@login_required
@role_required_manager
def eu():
    old=request.form.get('old_phone','').strip(); new_ph=request.form.get('phone','').strip() or request.form.get('user_field','').strip()
    new_role=request.form.get('role','tech'); new_pass=request.form.get('password','').strip()
    if not old: return "خطأ",400
    if old!=new_ph and qone("SELECT * FROM users WHERE phone=?", (new_ph,)): return "الرقم الجديد موجود",400
    if new_pass: ok=qexec("UPDATE users SET phone=?,username=?,role=?,password=? WHERE phone=?", (new_ph, new_ph, new_role, generate_password_hash(new_pass), old))
    else: ok=qexec("UPDATE users SET phone=?,username=?,role=? WHERE phone=?", (new_ph, new_ph, new_role, old))
    if ok and session.get('phone')==old: session['phone']=new_ph
    if ok: log_action(session.get('phone'), 'تعديل يوزر', f"{old}->{new_ph}")
    return "ok" if ok else "خطأ", 200 if ok else 400

@app.route('/del_user/<ph>')
@login_required
@role_required_manager
def du(ph):
    if ph=='05344851045': return "ممنوع حذف المدير",400
    ok=qexec("DELETE FROM users WHERE phone=?", (ph,))
    if ok: log_action(session.get('phone'), 'حذف يوزر', ph)
    return "ok" if ok else "خطأ", 200 if ok else 400

@app.route('/change_pass', methods=['POST'])
@login_required
def cp():
    np=request.form.get('newpass','').strip()
    if not np: return "فارغة",400
    ok=qexec("UPDATE users SET password=? WHERE phone=?", (generate_password_hash(np), session.get('phone')))
    if ok: log_action(session.get('phone'), 'تغيير كلمة سر', '')
    return "ok" if ok else "خطأ", 200 if ok else 400

def page_content(v):
    req_lang=request.args.get('lang') or session.get('lang','ar'); dish_tbl=get_dish_table()
    def L(ar,en): return ar if req_lang=='ar' else en
    if v=='home':
        ns=(qone("SELECT COUNT(*) as c FROM subs") or {}).get('c',0); nd=(qone(f"SELECT COUNT(*) as c FROM {dish_tbl}") or {}).get('c',0)
        nt=(qone("SELECT COUNT(*) as c FROM towers") or {}).get('c',0); nl=(qone("SELECT COUNT(*) as c FROM ledger") or {}).get('c',0)
        logs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 6")
        log_html="".join([f"<div style='display:flex;justify-content:space-between;padding:8px 10px;border-bottom:1px dashed #ffffff10'><div><b style='color:#ffbe4d'>{esc(l.get('user_phone',''))}</b> <span style='color:#cbd5e1'>{esc(l.get('action',''))}</span> <small style='color:#94a3b8'>{esc(l.get('detail',''))}</small></div><small style='color:#64748b'>{esc(l.get('time',''))}</small></div>" for l in logs])
        if not logs: log_html=f"<div style='padding:12px;color:#64748b'>لا يوجد سجل بعد - سيظهر هنا عند الإضافة/التعديل/الحذف</div>"
        return f'''<div style='max-width:900px;margin:0 auto'><div style='display:grid;grid-template-columns:1fr 1fr;gap:14px'>
        <div class='card anim' onclick="loadPage('subs')" style='cursor:pointer;background:linear-gradient(135deg,#1e2a4a 0%,#162040 100%)'><div style='display:flex;justify-content:space-between'><div><h3 style='margin:0;color:#aab4d0;font-size:13px'>{L('المشتركين','Subs')}</h3><h2 style='margin:6px 0 0;font-size:36px'>{ns}</h2></div><div style='font-size:36px'>👥</div></div></div>
        <div class='card anim' onclick="loadPage('dishes')" style='cursor:pointer;background:linear-gradient(135deg,#1e2f4a 0%,#162840 100%)'><div style='display:flex;justify-content:space-between'><div><h3 style='margin:0;color:#aab4d0;font-size:13px'>{L('الصحون','Dishes')}</h3><h2 style='margin:6px 0 0;font-size:36px'>{nd}</h2><small style='color:#22c55e'>☁ {dish_tbl}</small></div><div style='font-size:36px'>📡</div></div></div>
        <div class='card anim' onclick="loadPage('towers')" style='cursor:pointer;background:linear-gradient(135deg,#2a1e4a 0%,#201640 100%)'><div style='display:flex;justify-content:space-between'><div><h3 style='margin:0;color:#aab4d0;font-size:13px'>{L('الأبراج','Towers')}</h3><h2 style='margin:6px 0 0;font-size:36px'>{nt}</h2></div><div style='font-size:36px'>🗼</div></div></div>
        <div class='card anim' onclick="loadPage('ledger')" style='cursor:pointer;background:linear-gradient(135deg,#4a2a1e 0%,#402016 100%)'><div style='display:flex;justify-content:space-between'><div><h3 style='margin:0;color:#aab4d0;font-size:13px'>{L('الحسابات','Accounts')}</h3><h2 style='margin:6px 0 0;font-size:36px'>{nl}</h2></div><div style='font-size:36px'>📒</div></div></div></div>
        <div class=card style='margin-top:14px'><div style='display:flex;justify-content:space-between;flex-wrap:wrap'><h4>📊 {L('التقارير','Reports')} - <small style='color:#22c55e'>☁ {dish_tbl} • ⚡ FAST</small></h4><div style='display:flex;gap:8px'><a href='/api/export/dishes' class=btn-gold style='text-decoration:none;padding:8px 12px;background:linear-gradient(90deg,#22c55e,#16a34a);color:#fff'>📗 Excel</a><a href='/api/export/logs' class=btn-gold style='text-decoration:none;padding:8px 12px;background:linear-gradient(90deg,#8b5cf6,#7c3aed);color:#fff'>📜 Excel</a></div></div></div>
        <div class=card><div style='display:flex;justify-content:space-between;align-items:center'><h4>📜 {L('آخر النشاطات','Recent')} - السجل شغال ✅</h4><button class=btn-gold onclick="loadPage('logs')" style='padding:6px 12px'>عرض الكل</button></div>{log_html}</div></div>'''
    if v=='ping':
        return f'''<div style='max-width:800px;margin:0 auto'>
        <div class=card style='background:linear-gradient(135deg,#0f172a,#1e293b);border:1px solid #22c55e33'>
        <h3 style='margin:0'>📶 {L('بنج منفصل','Ping')} 🔥 FAST</h3>
        <p style='color:#9ca3af;font-size:12px;margin:6px 0'>Pool 20 • {dish_tbl}</p>
        <div style='display:flex;gap:8px;margin-top:12px;flex-wrap:wrap'>
        <input id=pingIp placeholder='192.168.1.1' style='flex:1;min-width:160px;padding:14px;border-radius:12px;background:#0f1424;border:1px solid #ffffff20;color:#fff;font-family:monospace'>
        <input id=pingPort placeholder='Port' value='80' style='width:80px;padding:14px;border-radius:12px;background:#0f1424;border:1px solid #ffffff20;color:#fff'>
        <button class=btn-gold onclick="doSinglePing()" style='padding:14px 20px;background:linear-gradient(90deg,#22c55e,#16a34a);color:#fff'>📶 Ping</button>
        <button class=btn-gold onclick="doTcpPing()" style='padding:14px 16px;background:linear-gradient(90deg,#0ea5e9,#0284c7);color:#fff'>TCP</button>
        </div>
        <div id=pingResult style='margin-top:14px;min-height:60px;background:#0008;border:1px solid #ffffff0a;border-radius:12px;padding:14px;font-family:monospace;font-size:13px;white-space:pre-wrap'>جاهز...</div>
        </div>
        <div class=card><h4>⚡ صحون سريعة</h4><div id=quickDishes>⏳...</div></div>
        </div><script>
        async function doSinglePing(){{let ip=document.getElementById('pingIp').value.trim(); if(!ip){{alert('IP');return;}} let out=document.getElementById('pingResult'); out.textContent='⏳ '+ip+'...'; out.style.color='#ffbe4d'; try{{let r=await fetch('/api/ping?ip='+encodeURIComponent(ip),{{cache:'no-store'}}); let j=await r.json(); out.textContent=j.out; out.style.color=j.ok?'#22c55e':'#ef4444';}}catch(e){{out.textContent='❌ '+e;}}}}
        async function doTcpPing(){{let ip=document.getElementById('pingIp').value.trim(); let port=document.getElementById('pingPort').value.trim()||'80'; if(!ip){{alert('IP');return;}} let out=document.getElementById('pingResult'); out.textContent='⏳ '+ip+':'+port+'...'; try{{let r=await fetch('/api/ping_tcp?ip='+encodeURIComponent(ip)+'&port='+port); let j=await r.json(); out.textContent=j.out; out.style.color=j.ok?'#22c55e':'#ef4444';}}catch(e){{out.textContent='خطأ';}}}}
        (async()=>{{try{{let r=await fetch('/api/search?q=192',{{cache:'no-store'}}); let d=await r.json(); let h=''; d.filter(x=>x.page==='dishes').slice(0,8).forEach(x=>{{h+='<div style="display:flex;justify-content:space-between;padding:8px 10px;border-bottom:1px solid #ffffff08"><span>🌐 '+x.sub+' - '+x.title+'</span><button class=btn-gold onclick="document.getElementById(\\'pingIp\\').value=\\''+x.sub+'\\'; doSinglePing()" style="padding:5px 10px">Ping</button></div>';}}); document.getElementById('quickDishes').innerHTML=h||'لا يوجد';}}catch(e){{}}}})();
        </script>'''
    if v=='dishes':
        rs=qall(f"SELECT * FROM {dish_tbl} ORDER BY id DESC"); rows_html=""
        for r in rs:
            dn=esc(r.get('dish_name') or 'صحن');ip=esc(r.get('ip') or '');loc=esc(r.get('location') or '');rid=r['id']
            rows_html+=f'<div class="card anim" id="dish-{rid}" data-name="{dn}" data-ip="{ip}" data-loc="{loc}" style="display:flex;justify-content:space-between"><div><b>{dn}</b><br><a href="http://{ip}" target=_blank style="background:#000;color:#ffbe4d;padding:5px 10px;border-radius:8px;font-family:monospace;text-decoration:none">🌐 {ip}</a><br><small style="color:#888">{loc}</small></div><div style="display:flex;flex-direction:column;gap:6px"><button class=btn-gold onclick="quickPingD({rid})" style="padding:7px 12px;background:linear-gradient(90deg,#22c55e,#16a34a);color:#fff">📶</button><div style="display:flex;gap:4px"><button class=btn-gold onclick="editDish({rid})" style="padding:7px 9px">✏</button><button class=btn-del onclick="askDel(\'/del_dish/{rid}\')" style="padding:7px 9px">🗑</button></div></div></div>'
        return f'''<div style='max-width:900px;margin:0 auto'><div class=card><div style='display:flex;justify-content:space-between;flex-wrap:wrap'><h3>📡 {L('الصحون','Dishes')} - {len(rs)}</h3><a href='/api/export/dishes' class=btn-gold style='text-decoration:none;padding:7px 12px'>📗 Excel</a></div><form data-ajax method=post action=/add_dish style='display:flex;gap:6px;flex-wrap:wrap;margin-top:10px'><input name=dish_name placeholder='اسم الصحن' required style='flex:1'><input name=ip placeholder='192.168.1.1' required style='flex:1'><input name=location placeholder='موقع' style='flex:1'><button class=btn-gold id=btnAddDish>➕ حفظ</button></form><input id=searchBox placeholder='🔍 بحث...' oninput="searchDishes(this.value)" style='margin-top:10px;width:100%;padding:12px;border-radius:12px;background:#0f1424;border:1px solid #ffffff18'></div><div id=dl>{rows_html}</div></div><script>
        function editDish(id){{let c=document.getElementById('dish-'+id);document.getElementById('editModal').classList.add('show');document.getElementById('editBody').innerHTML='<input id=edit_dish_name value="'+c.dataset.name+'" style="width:100%;padding:12px;margin:4px 0"><input id=edit_ip value="'+c.dataset.ip+'" style="width:100%;padding:12px;margin:4px 0"><input id=edit_loc value="'+c.dataset.loc+'" style="width:100%;padding:12px;margin:4px 0"><button onclick="saveDish('+id+')" class=btn-gold style="width:100%;padding:12px" id=btnSaveDish>💾 حفظ</button>';}}
        function saveDish(id){{let b=document.getElementById('btnSaveDish'); b.innerHTML='⏳...'; b.disabled=true; let nn=document.getElementById('edit_dish_name').value;let ii=document.getElementById('edit_ip').value;let ll=document.getElementById('edit_loc').value;fetch('/edit_dish/'+id,{{method:'POST',body:new URLSearchParams({{dish_name:nn,ip:ii,location:ll}})}}).then(r=>{{if(!r.ok){{alert('ممنوع'); b.innerHTML='💾 حفظ'; b.disabled=false;}}else{{closeEditModal(); loadPage('dishes',true);}}}});}}
        function quickPingD(id){{let c=document.getElementById('dish-'+id);loadPage('ping');setTimeout(()=>{{let inp=document.getElementById('pingIp');if(inp){{inp.value=c.dataset.ip;doSinglePing();}}}},200);}}
        function searchDishes(q){{q=(q||'').toLowerCase();document.querySelectorAll('[id^=dish-]').forEach(card=>{{let txt=(card.dataset.name+card.dataset.ip+card.dataset.loc).toLowerCase();card.style.display=txt.includes(q)?'flex':'none';}});}}
        </script>'''
    if v=='towers':
        rs=qall("SELECT * FROM towers ORDER BY id DESC"); rows=""
        for r in rs: rows+=f"<div class='card anim' id='tower-{r['id']}' data-name='{esc(r['name'])}' data-area='{esc(r['area'] or '')}' data-lat='{r.get('lat') or 0}' data-lng='{r.get('lng') or 0}'><div style='display:flex;justify-content:space-between'><div><b>🗼 {esc(r['name'])}</b><br><small>{esc(r['area'] or '')}</small></div><div style='display:flex;gap:5px'><button class=btn-gold onclick=\"openEditTower({r['id']})\" style='padding:8px 10px'>✏</button><button class=btn-del onclick=\"askDel('/del_tower/{r['id']}')\" style='padding:8px 10px'>🗑</button></div></div></div>"
        return f'''<div style='max-width:700px;margin:0 auto'><div class=card><h3>🗼 {L('الأبراج','Towers')}</h3><form data-ajax method=post action=/add_tower style='display:flex;gap:6px;flex-wrap:wrap;margin-top:8px'><input name=name placeholder='اسم البرج' required style='flex:1'><input name=area placeholder='المنطقة' style='flex:1'><input name=lat placeholder='lat' style='flex:0.6'><input name=lng placeholder='lng' style='flex:0.6'><button class=btn-gold id=btnAddTower>➕</button></form></div>{rows or '<div class=card>لا يوجد</div>'}<script>
        function openEditTower(id){{let c=document.getElementById('tower-'+id);document.getElementById('editModal').classList.add('show');document.getElementById('editBody').innerHTML='<input id=edit_t_name value="'+c.dataset.name+'" style="width:100%;margin:6px 0;padding:12px"><input id=edit_t_area value="'+c.dataset.area+'" style="width:100%;margin:6px 0;padding:12px"><input id=edit_t_lat value="'+c.dataset.lat+'" style="width:100%;margin:6px 0;padding:12px"><input id=edit_t_lng value="'+c.dataset.lng+'" style="width:100%;margin:6px 0;padding:12px"><button onclick="saveTower('+id+')" class=btn-gold style="width:100%;padding:12px" id=btnSaveTower>💾 حفظ</button>';}}
        function saveTower(id){{let b=document.getElementById('btnSaveTower'); b.innerHTML='⏳...'; b.disabled=true; let nn=document.getElementById('edit_t_name').value;let aa=document.getElementById('edit_t_area').value;let la=document.getElementById('edit_t_lat').value;let ln=document.getElementById('edit_t_lng').value;fetch('/edit_tower/'+id,{{method:'POST',body:new URLSearchParams({{name:nn,area:aa,lat:la,lng:ln}})}}).then(r=>{{if(!r.ok)alert('ممنوع');else{{closeEditModal();loadPage('towers',true);}}}});}}
        </script></div>'''
    if v=='subs':
        rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 200"); rows=""
        for r in rs: rows+=f"<div class='card anim' id='sub-{r['id']}' data-name='{esc(r['name'])}' data-phone='{esc(r['phone'] or '')}' data-note='{esc(r['note'] or '')}' style='display:flex;justify-content:space-between'><div><b>{esc(r['name'])}</b><br>📞 {esc(r['phone'] or '')}</div><div style='display:flex;gap:5px'><button class=btn-gold onclick=\"openEditSub({r['id']})\" style='padding:8px 10px'>✏</button><button class=btn-del onclick=\"askDel('/del_sub/{r['id']}')\" style='padding:8px 10px'>🗑</button></div></div>"
        return f'''<div style='max-width:700px;margin:0 auto'><div class=card><h3>👥 {L('المشتركين','Subs')}</h3><form data-ajax method=post action=/add_sub style='display:flex;gap:5px;flex-wrap:wrap'><input name=name placeholder='الاسم' required style='flex:1'><input name=phone placeholder='رقم' style='flex:1'><input name=note placeholder='ملاحظة' style='flex:1'><button class=btn-gold>➕</button></form></div>{rows}<script>
        function openEditSub(id){{let c=document.getElementById('sub-'+id);document.getElementById('editModal').classList.add('show');document.getElementById('editBody').innerHTML='<input id=edit_s_name value="'+c.dataset.name+'" style="width:100%;margin:6px 0;padding:12px"><input id=edit_s_phone value="'+c.dataset.phone+'" style="width:100%;margin:6px 0;padding:12px"><input id=edit_s_note value="'+c.dataset.note+'" style="width:100%;margin:6px 0;padding:12px"><button onclick="saveSub('+id+')" class=btn-gold style="width:100%;padding:12px">💾</button>';}}
        function saveSub(id){{let nn=document.getElementById('edit_s_name').value;let pp=document.getElementById('edit_s_phone').value;let no=document.getElementById('edit_s_note').value;fetch('/edit_sub/'+id,{{method:'POST',body:new URLSearchParams({{name:nn,phone:pp,note:no}})}}).then(r=>{{if(!r.ok)alert('ممنوع');else{{closeEditModal();loadPage('subs',true);}}}});}}
        </script></div>'''
    if v=='ledger':
        rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 200"); rows=""
        for r in rs: rows+=f"<div class='card anim' id='led-{r['id']}' data-name='{esc(r['name'])}' data-amount='{r['amount']}'><div style='display:flex;justify-content:space-between'><div><b>{esc(r['name'])}</b> - <b style='color:#ffbe4d'>{r['amount']}</b></div><div><button class=btn-gold onclick=\"openEditLed({r['id']})\" style='padding:7px 9px'>✏</button><button class=btn-del onclick=\"askDel('/del_ledger/{r['id']}')\" style='padding:7px 9px'>🗑</button></div></div></div>"
        return f'''<div style='max-width:700px;margin:0 auto'><div class=card><h3>📒 {L('الحسابات','Accounts')}</h3><form data-ajax method=post action=/add_ledger style='display:flex;gap:5px;flex-wrap:wrap'><input name=name placeholder='الاسم' required style='flex:1'><input name=amount type=number step=0.01 placeholder='المبلغ' required style='flex:1'><input name=note placeholder='ملاحظة' style='flex:1'><select name=currency style='flex:0.5'><option>USD</option><option>SYP</option></select><button class=btn-gold>➕</button></form></div>{rows}<script>
        function openEditLed(id){{let c=document.getElementById('led-'+id);document.getElementById('editModal').classList.add('show');document.getElementById('editBody').innerHTML='<input id=edit_l_name value="'+c.dataset.name+'" style="width:100%;margin:6px 0;padding:12px"><input id=edit_l_amount value="'+c.dataset.amount+'" style="width:100%;margin:6px 0;padding:12px"><button onclick="saveLed('+id+')" class=btn-gold style="width:100%;padding:12px">💾</button>';}}
        function saveLed(id){{let nn=document.getElementById('edit_l_name').value;let aa=document.getElementById('edit_l_amount').value;fetch('/edit_ledger/'+id,{{method:'POST',body:new URLSearchParams({{name:nn,amount:aa,note:'',currency:'USD'}})}}).then(()=>{{closeEditModal();loadPage('ledger',true);}});}}
        </script></div>'''
    if v=='logs':
        rs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 300")
        rows="".join([f"<div class='card anim' style='font-size:13px;border-right:4px solid #ffbe4d'><div style='display:flex;justify-content:space-between'><div><b style='color:#ffbe4d'>{esc(r.get('user_phone',''))}</b> <b>{esc(r.get('action',''))}</b><br><small style='color:#cbd5e1'>{esc(r.get('detail',''))}</small></div><small style='color:#64748b'>{esc(r.get('time',''))}</small></div></div>" for r in rs])
        if not rs: rows="<div class=card style='text-align:center;padding:20px;color:#64748b'>📭 السجل فاضي - أول ما تضيف/تعدل/تحذف أي شي رح يظهر هون<br><small>تم إصلاح السجل ✅ هلق صار يسجل كل العمليات تلقائياً</small></div>"
        return f"<div style='max-width:900px;margin:0 auto'><div class=card style='display:flex;justify-content:space-between;align-items:center'><h3>📜 السجل - شغال ✅ ({len(rs)})</h3><div style='display:flex;gap:6px'><a href='/api/export/logs' class=btn-gold style='text-decoration:none;padding:7px 12px'>📗 Excel</a><button onclick=\"if(confirm('مسح السجل؟')){{fetch('/api/clear_logs',{{method:'POST'}}).then(()=>loadPage('logs',true))}}\" class=btn-del style='padding:7px 12px'>🗑 مسح</button></div></div>{rows}</div>"
    if v=='network':
        dish_tbl=get_dish_table(); dishes=qall(f"SELECT * FROM {dish_tbl} ORDER BY id DESC")
        rows="".join([f"<div class='card anim' id='net-{d['id']}' data-ip='{esc(d.get('ip',''))}' style='display:flex;justify-content:space-between'><div><b>{esc(d.get('dish_name') or 'صحن')}</b> - {esc(d.get('ip',''))}<br><small class='net-out'>⏳...</small></div><button class=btn-gold onclick='checkOne({d['id']})'>📶</button></div>" for d in dishes])
        return f'''<div style='max-width:800px;margin:0 auto'><div class=card style='background:linear-gradient(135deg,#0f172a,#1e293b);border:1px solid #ffbe4d33'><h3>📊 حالة الشبكة LIVE - ☁ {dish_tbl}</h3><div style='display:flex;gap:8px;margin-top:8px'><button class=btn-gold onclick='checkAll()' style='flex:1;background:linear-gradient(90deg,#22c55e,#16a34a);color:#fff;padding:12px'>🚀 فحص الكل</button><button class=btn-gold onclick="loadPage('ping')" style='flex:1'>📶 Ping</button></div><div id=summary style='margin-top:10px;font-weight:800'></div></div>{rows}<script>
        async function checkOne(id){{let c=document.getElementById('net-'+id);let out=c.querySelector('.net-out');out.textContent='⏳...';try{{let r=await fetch('/api/ping?ip='+encodeURIComponent(c.dataset.ip));let j=await r.json();out.textContent=j.out.slice(0,80);out.style.color=j.ok?'#22c55e':'#ef4444';}}catch(e){{out.textContent='❌';}}}}
        async function checkAll(){{let cards=document.querySelectorAll('[id^=net-]');let on=0,off=0;for(let c of cards){{let out=c.querySelector('.net-out');out.textContent='⏳...';try{{let r=await fetch('/api/ping?ip='+encodeURIComponent(c.dataset.ip));let j=await r.json();out.textContent=j.ok?'✅ '+j.out.slice(0,50):'❌ '+j.out.slice(0,50);out.style.color=j.ok?'#22c55e':'#ef4444'; if(j.ok)on++; else off++;}}catch(e){{off++;}} document.getElementById('summary').innerHTML='✅ '+on+' | ❌ '+off; await new Promise(r=>setTimeout(r,120));}}}}
        </script></div>'''
    if v=='map':
        towers=qall("SELECT * FROM towers")
        tj_json=json.dumps([{"name":t['name'],"area":t.get('area') or '',"lat":float(t.get('lat') or 35.1318),"lng":float(t.get('lng') or 36.7578)} for t in towers],ensure_ascii=False)
        return f'''<div class=card style='padding:10px;background:linear-gradient(180deg,#0f172a,#111827);border:1px solid #ffffff12'>
        <div style='display:flex;gap:6px;margin-bottom:10px;flex-wrap:wrap'><input id=mapSearch placeholder='🔍 بحث برج...' onkeydown="if(event.key==='Enter'){{event.preventDefault(); doMapSearch();}}" style='flex:1;min-width:140px;background:#1f2937;border:1px solid #ffffff15;color:#fff;padding:10px 12px;border-radius:12px'><button class=btn-gold onclick="doMapSearch()" style='padding:10px 12px'>🔍 بحث</button><button class=btn-gold onclick="locateMe()" style='background:linear-gradient(90deg,#22c55e,#16a34a);color:#fff;padding:10px 12px'>📍 موقعي</button><button class=btn-gold onclick="enableAddPoint()" id=addPointBtn style='background:linear-gradient(90deg,#f59e0b,#d97706);color:#fff;padding:10px 12px'>➕ نقطة</button></div><div id=map style='height:72vh;min-height:460px;border-radius:16px;background:#0f172a;z-index:1;border:2px solid #ffffff0f'></div><div style='margin-top:6px;font-size:11px;color:#6b7280'><span id=coordsLabel style='color:#ffbe4d'>📍 -</span></div></div><script>
        let _towers={tj_json}; let _map=null; let addPointMode=false, tempMarkers=[];
        window.doMapSearch=function(){{let q=document.getElementById('mapSearch').value.trim().toLowerCase(); if(!q) return; let f=_towers.find(t=>t.name.toLowerCase().includes(q)||t.area.toLowerCase().includes(q)); if(f && _map){{_map.flyTo([f.lat,f.lng],17); L.popup().setLatLng([f.lat,f.lng]).setContent('<b>'+f.name+'</b>').openOn(_map);}}}};
        window.locateMe=function(){{if(_map && navigator.geolocation){{navigator.geolocation.getCurrentPosition(p=>{{_map.flyTo([p.coords.latitude,p.coords.longitude],16); L.marker([p.coords.latitude,p.coords.longitude]).addTo(_map).bindPopup('📍 موقعك').openPopup();}});}}}};
        window.enableAddPoint=function(){{addPointMode=!addPointMode; let b=document.getElementById('addPointBtn'); b.textContent=addPointMode?'✅ اضغط على الخريطة':'➕ نقطة';}};
        setTimeout(()=>{{if(typeof L==='undefined'){{document.getElementById('map').innerHTML='⚠ فشل'; return;}} _map=L.map('map',{{zoomControl:true}}).setView([35.1318,36.7578],13); L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:19}}).addTo(_map); _towers.forEach(t=>{{L.marker([t.lat,t.lng]).addTo(_map).bindPopup('<b>'+t.name+'</b>');}}); _map.on('click',e=>{{document.getElementById('coordsLabel').textContent='📍 '+e.latlng.lat.toFixed(5)+','+e.latlng.lng.toFixed(5); if(addPointMode){{let lat=e.latlng.lat.toFixed(6), lng=e.latlng.lng.toFixed(6); L.popup().setLatLng(e.latlng).setContent('<div style="min-width:200px;text-align:right"><b>➕ نقطة</b><br><small>'+lat+','+lng+'</small><br><input id="newPointName" placeholder="اسم" style="width:100%;margin:6px 0;padding:8px;border-radius:8px"><button onclick="saveNewPoint('+lat+','+lng+')" style="width:100%;background:#ffbe4d;border:0;padding:9px;border-radius:8px;font-weight:800">💾 حفظ</button></div>').openOn(_map);}}}}); window.saveNewPoint=function(lat,lng){{let name=document.getElementById('newPointName').value.trim()||'نقطة'; fetch('/add_tower',{{method:'POST',body:new URLSearchParams({{name:name,area:'',lat:lat,lng:lng}})}}).then(()=>{{_map.closePopup(); addPointMode=false;}});}};}},300);
        </script>'''
    if v=='support': return """<div class=card style='text-align:center;max-width:500px;margin:0 auto'><h2>🛠 الدعم</h2><a href='https://wa.me/905344851045' target=_blank style='display:inline-block;background:#22c55e;color:#fff;padding:14px 24px;border-radius:14px;text-decoration:none;margin:6px;font-weight:800'>💬 واتساب</a></div>"""
    if v=='settings':
        us=qall("SELECT * FROM users ORDER BY phone DESC"); uh=""
        for u in us:
            ph=esc(u["phone"]);un=esc(u.get("username") or "");ro=esc(u.get("role") or "")
            badge="<span style='background:#ffbe4d;color:#111;padding:2px 8px;border-radius:8px;font-size:11px;font-weight:800'>مدير</span>" if ro=='manager' else "<span style='background:#ffffff15;color:#aaa;padding:2px 8px;border-radius:8px;font-size:11px'>فني</span>"
            uh+=f'<div class="card anim" id="user-{ph}" data-phone="{ph}" data-username="{un}" data-role="{ro}" style="display:grid;grid-template-columns:1fr auto;gap:12px;align-items:center"><div><b>{un}</b><br><span style="color:#ffbe4d;font-family:monospace">{ph}</span> {badge}</div><div style="display:flex;gap:6px"><button class=btn-gold onclick="openEditUser(\'{ph}\')" style="padding:8px 10px">✏</button><button class=btn-del onclick="askDel(\'/del_user/{ph}\')" style="padding:8px 10px">🗑</button></div></div>'
        return f'''<div style='max-width:800px;margin:0 auto'><div class=card><h3>🔑 كلمة السر</h3><form data-ajax method=post action=/change_pass style='display:flex;gap:8px'><input name=newpass type=password placeholder='جديدة' required style='flex:1'><button class=btn-gold>💾</button></form></div><div style='display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px'><div class=card style='background:linear-gradient(135deg,#1a2340,#121a30);border:1px solid #ffbe4d22;text-align:center'><h4 style='margin:0 0 10px'>🌐 اللغة</h4><button onclick="toggleLang()" id=langBtnSettings style='width:100%;padding:14px;border-radius:12px;border:1px solid #ffffff15;background:linear-gradient(90deg,#1f2937,#111827);color:#fff;font-weight:800;cursor:pointer;font-size:16px'>🌐 عربي</button><small style='color:#22c55e;display:block;margin-top:6px'>يبدل اللغة + اتجاه القائمة</small></div><div class=card style='background:linear-gradient(180deg,#1e2433,#0f1424);border:1px solid #ffbe4d30'><h4 style='text-align:center;margin:0 0 12px'>👤 اضافة يوزر</h4><form data-ajax method=post action=/add_user style='display:flex;flex-direction:column;gap:10px'><input name=user_field placeholder='📱 رقم / يوزر' required style='padding:14px;background:#0f1424;border:1px solid #ffffff20;border-radius:12px;color:#fff'><input name=password type=password placeholder='🔑 password' required style='padding:14px;background:#0f1424;border:1px solid #ffffff20;border-radius:12px;color:#fff'><select name=role style='padding:12px;background:#0f1424;border:1px solid #ffffff20;border-radius:12px;color:#fff'><option value=tech>فني</option><option value=manager>مدير</option></select><button class=btn-gold style='padding:14px'>➕</button></form></div></div>{uh}<script>
        function openEditUser(ph){{let c=document.getElementById('user-'+ph);document.getElementById('editModal').classList.add('show');document.getElementById('editBody').innerHTML='<input id=edit_u_field value="'+c.dataset.phone+'" style="width:100%;padding:12px;border-radius:10px;margin-top:4px"><input id=edit_u_pass type="password" placeholder="كلمة سر جديدة" style="width:100%;padding:12px;border-radius:10px;margin-top:8px"><select id=edit_u_role style="width:100%;padding:12px;border-radius:10px;margin-top:8px"><option value="tech" '+(c.dataset.role=='tech'?'selected':'')+'>فني</option><option value="manager" '+(c.dataset.role=='manager'?'selected':'')+'>مدير</option></select><button onclick="saveUser(\\''+ph+'\\')" class=btn-gold style="width:100%;padding:14px;margin-top:12px">💾 حفظ</button>';}}
        function saveUser(oldPh){{let ff=document.getElementById('edit_u_field').value.trim();let pw=document.getElementById('edit_u_pass').value;let ro=document.getElementById('edit_u_role').value;if(!ff){{alert('مطلوب');return;}}let data={{old_phone:oldPh,phone:ff,username:ff,role:ro}};if(pw.trim()!='')data.password=pw.trim();fetch('/edit_user',{{method:'POST',body:new URLSearchParams(data)}}).then(r=>{{if(!r.ok)r.text().then(t=>alert(t));else{{closeEditModal();loadPage('settings',true);}}}});}}
        </script></div>'''
    return "<div class=card>ok</div>"

@app.route('/api/clear_logs', methods=['POST'])
@login_required
@role_required_manager
def clear_logs():
    qexec("DELETE FROM logs")
    log_action(session.get('phone'), 'مسح السجل', '')
    return jsonify(ok=True)

def layout(c, v='home'):
    th=session.get('theme','dark'); is_dark=(th=='dark')
    bg='radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 60%, #070a1f 100%)' if is_dark else '#f1f5f9'
    card_bg='#1e2433' if is_dark else '#ffffff'; txt='#ffffff' if is_dark else '#0f172a'; border='#ffffff12' if is_dark else '#e2e8f0'
    cur_user=qone("SELECT * FROM users WHERE phone=?", (session.get('phone') or '',)) or {}; role=(cur_user.get('role') or 'tech')
    req_lang=session.get('lang','ar'); is_rtl=req_lang=='ar'
    def L(ar,en): return ar if is_rtl else en
    username_display=esc(cur_user.get('username') or cur_user.get('phone') or session.get('phone') or '')
    # إصلاح القائمة: يمين للعربي، يسار للإنكليزي
    if is_rtl:
        sidebar_pos="right:0; left:auto; transform:translateX(110%);"; sidebar_active_css="transform:none;"; sidebar_hover="transform:translateX(-4px);"
        dir_attr="rtl"; side="right"
    else:
        sidebar_pos="left:0; right:auto; transform:translateX(-110%);"; sidebar_active_css="transform:none;"; sidebar_hover="transform:translateX(4px);"
        dir_attr="ltr"; side="left"
    return f"""<html dir={dir_attr} lang={req_lang}><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1,maximum-scale=1'>
<link rel=stylesheet href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'>
<style>
*{{box-sizing:border-box;font-family:system-ui}}body{{margin:0;background:{bg};color:{txt};overflow-x:hidden;direction:{dir_attr}}}
.anim{{animation:fadeUp .28s ease both}}@keyframes fadeUp{{from{{opacity:0;transform:translateY(10px)}}to{{opacity:1;transform:none}}}}
.top{{position:fixed;top:0;left:0;right:0;height:62px;background:linear-gradient(90deg,#0f172af2,#111827f2);backdrop-filter:blur(16px);color:#fff;display:flex;align-items:center;justify-content:space-between;padding:0 14px;z-index:1003;border-bottom:1px solid #ffffff12}}
.sidebar{{position:fixed;top:0;width:285px;height:100%;background:linear-gradient(180deg,#0f172a 0%,#070e22 100%);color:#fff;z-index:1002;padding-top:70px;{sidebar_pos}transition:transform .32s cubic-bezier(.4,0,.2,1);overflow-y:auto;box-shadow:10px 0 40px #0008;border-{side}:1px solid #ffffff0f}}
.sidebar.active{{ {sidebar_active_css} }}
.sidebar a{{display:flex;align-items:center;gap:11px;padding:12px 15px;margin:6px 11px;color:#cbd5e1;text-decoration:none;border-radius:13px;background:linear-gradient(90deg,#ffffff06,#ffffff03);border:1px solid #ffffff06;transition:all .24s}}
.sidebar a:hover{{background:#ffffff12;{sidebar_hover}color:#fff}}
.sidebar a.active{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:800;box-shadow:0 6px 18px #ffbe4d44}}
#overlay{{position:fixed;inset:0;background:#0009;backdrop-filter:blur(4px);z-index:1001;display:none;opacity:0;transition:opacity .3s}}#overlay.show{{display:block;opacity:1}}
.main{{margin-top:74px;padding:14px;min-height:90vh}}
.card{{background:linear-gradient(180deg,{card_bg},{card_bg});color:{txt};padding:15px;border-radius:15px;margin-bottom:11px;border:1px solid {border};transition:all .22s;box-shadow:0 4px 14px #0002}}
.card:hover{{transform:translateY(-1px);box-shadow:0 10px 28px #0005}}
input,select{{padding:12px 14px;margin:5px 0;border-radius:11px;border:1px solid {border};width:100%;background:#ffffff07;color:{txt};font-size:14px}}
input:focus{{border-color:#ffbe4d;box-shadow:0 0 0 3px #ffbe4d22;outline:none}}
.btn-gold{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;padding:9px 16px;border:0;border-radius:11px;font-weight:800;cursor:pointer;transition:all .2s}}
.btn-gold:disabled{{opacity:.5; cursor:not-allowed}}
.btn-del{{background:linear-gradient(90deg,#ef4444,#dc2626);color:#fff;padding:8px 13px;border:0;border-radius:11px;cursor:pointer}}
#delModal, #editModal{{position:fixed;inset:0;background:#000a;backdrop-filter:blur(10px);display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:.3s;z-index:2000}}
#delModal.show, #editModal.show{{opacity:1;pointer-events:auto}}
#delBox, #editBox{{background:linear-gradient(180deg,{card_bg},#0f1424);color:{txt};padding:24px;border-radius:18px;width:92%;max-width:450px;transform:scale(.92) translateY(18px);transition:.32s}}
#delModal.show #delBox, #editModal.show #editBox{{transform:scale(1) translateY(0)}}
.skeleton{{background:linear-gradient(90deg,#1a2035 25%,#222b45 50%,#1a2035 75%);background-size:200% 100%;animation:shimmer 1.2s infinite}}
@keyframes shimmer{{0%{{background-position:-200% 0}}100%{{background-position:200% 0}}}}
::-webkit-scrollbar{{width:8px}}::-webkit-scrollbar-track{{background:#0a0e2a}}::-webkit-scrollbar-thumb{{background:linear-gradient(180deg,#ffbe4d,#ffb020);border-radius:8px}}
</style></head><body>
<div id=overlay onclick="toggleSb(false)"></div>
<div class=sidebar id=sb>
<div style='padding:0 18px 10px;border-bottom:1px solid #ffffff0a;margin-bottom:8px'><div style='font-weight:900;font-size:17px'>OMAIA <span style='color:#ffbe4d'>ISP</span> <small style='color:#22c55e'>⚡FIXED</small></div><small style='color:#64748b'>{username_display} • {role} • {get_dish_table()}</small><br><small style='color:#ffbe4d'>{L('السجل شغال + اللغة تتبدل + سريع','Logs + Lang + Fast')}</small></div>
<a href="javascript:loadPage('home')" id=nav-home onmouseenter="prefetchPage('home')">🏠 {L('الرئيسية','Home')}</a>
<a href="javascript:loadPage('ping')" id=nav-ping onmouseenter="prefetchPage('ping')" style='background:linear-gradient(90deg,#22c55e18,#16a34a18);border:1px solid #22c55e33'>📶 {L('بنج منفصل','Ping')}</a>
<a href="javascript:loadPage('network')" id=nav-network onmouseenter="prefetchPage('network')">📊 {L('حالة الشبكة','Network')}</a>
<a href="javascript:loadPage('dishes')" id=nav-dishes onmouseenter="prefetchPage('dishes')">📡 {L('الصحون','Dishes')}</a>
<a href="javascript:loadPage('towers')" id=nav-towers onmouseenter="prefetchPage('towers')">🗼 {L('الأبراج','Towers')}</a>
<a href="javascript:loadPage('subs')" id=nav-subs onmouseenter="prefetchPage('subs')">👥 {L('المشتركين','Subs')}</a>
<a href="javascript:loadPage('ledger')" id=nav-ledger onmouseenter="prefetchPage('ledger')">📒 {L('الحسابات','Ledger')}</a>
<a href="javascript:loadPage('logs')" id=nav-logs onmouseenter="prefetchPage('logs')">📜 {L('السجل','Logs')} <span style='background:#22c55e;color:#fff;padding:2px 6px;border-radius:6px;font-size:9px'>FIXED</span></a>
<a href="javascript:loadPage('map')" id=nav-map onmouseenter="prefetchPage('map')">🗺 {L('الخريطة الحية','Map')}</a>
<a href="javascript:loadPage('support')" id=nav-support onmouseenter="prefetchPage('support')">🛠 {L('الدعم','Support')}</a>
<a href="javascript:loadPage('settings')" id=nav-settings onmouseenter="prefetchPage('settings')">⚙ {L('الإعدادات','Settings')}</a>
<a href="javascript:logoutFast()" style='margin-top:10px;background:linear-gradient(90deg,#ef444418,#dc262618);border:1px solid #ef444433'>🚪 {L('خروج','Logout')}</a>
</div>
<div class=top>
<div style='display:flex;gap:8px;align-items:center'>
<span onclick="toggleSb()" style='font-size:24px;cursor:pointer;padding:6px 8px;border-radius:10px;background:#ffffff0a'>☰</span>
<input id=topsearch placeholder='🔍 {L('بحث','Search')}...' oninput="globalSearchTop(this.value)" style='background:#1f2937;border:1px solid #ffffff15;color:#fff;padding:9px 14px;border-radius:12px;width:42px;font-size:13px;transition:all .28s' onfocus="this.style.width='180px'" onblur="setTimeout(()=>{{this.style.width='42px'; let b=document.getElementById('searchResults'); if(b) b.style.display='none';}},250)">
</div>
<div style='font-weight:900;font-size:16px'>OMAIA <span style='color:#ffbe4d'>ISP</span> <span style='color:#22c55e;font-size:10px'>⚡FIXED</span></div>
<div style='display:flex;gap:8px;align-items:center'>
<div id=notifBell onclick="toggleNotif()" style='position:relative;cursor:pointer;font-size:20px;padding:6px 8px;border-radius:10px;background:#ffffff08'>🔔<span id=notifCount style='display:none;position:absolute;top:-4px;right:-4px;background:linear-gradient(90deg,#ef4444,#dc2626);color:#fff;font-size:10px;width:18px;height:18px;border-radius:50%;align-items:center;justify-content:center;font-weight:900'>0</span></div>
<button onclick="toggleTheme()" style='background:#ffffff0a;color:#fff;border:1px solid #ffffff0f;padding:8px 11px;border-radius:11px;cursor:pointer'>🌓</button>
</div>
</div>
<div id=searchResults style='position:fixed;top:66px;{side}:12px;max-width:420px;width:92%;background:linear-gradient(180deg,#1e2433,#171e2f);border:1px solid #ffffff15;border-radius:14px;z-index:1500;display:none;max-height:60vh;overflow:auto;box-shadow:0 16px 40px #000a'></div>
<div id=notifPanel style='position:fixed;top:66px;left:12px;max-width:360px;width:92%;background:linear-gradient(180deg,#1e2433,#111827);border:1px solid #ffffff12;border-radius:14px;z-index:2000;display:none;max-height:70vh;overflow:auto;box-shadow:0 16px 40px #000a'></div>
<div class=main id=mn>{c}</div>
<div id=delModal><div id=delBox><div style='font-size:42px;text-align:center'>🗑</div><h3 style='text-align:center;margin:8px 0'>تأكيد الحذف؟</h3><div style='display:flex;gap:10px;margin-top:14px'><button onclick="closeDel()" style='flex:1;padding:12px;border-radius:12px;border:1px solid {border};background:transparent;color:{txt};cursor:pointer'>تراجع</button><button id=delYes style='flex:1;padding:12px;border-radius:12px;background:linear-gradient(90deg,#ef4444,#dc2626);color:#fff;border:0;cursor:pointer;font-weight:800'>حذف</button></div></div></div>
<div id=editModal><div id=editBox><div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:14px'><h3 id=editTitle style='margin:0'>✏ تعديل</h3><button onclick="closeEditModal()" style='background:#ffffff12;border:0;color:{txt};width:32px;height:32px;border-radius:50%;cursor:pointer'>✕</button></div><div id=editBody></div></div></div>
<script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>
<script>
let cur='{v}'; let lang=localStorage.getItem('omaia_lang')||'{req_lang}';
function applyLang(){{let b=document.getElementById('langBtnSettings'); if(b) b.textContent=lang==='ar'?'🌐 عربي':'🌐 English'; document.documentElement.lang=lang; document.documentElement.dir=lang==='ar'?'rtl':'ltr'; localStorage.setItem('omaia_lang',lang);}}
applyLang();
function toggleSb(force){{let sb=document.getElementById('sb'),ov=document.getElementById('overlay'); let open=force!==undefined?force:!sb.classList.contains('active'); sb.classList.toggle('active',open); ov.classList.toggle('show',open); if(open){{ov.style.display='block'; setTimeout(()=>ov.style.opacity='1',10);}} else {{ov.style.opacity='0'; setTimeout(()=>ov.style.display='none',300);}}}}
// إصلاح اللغة: يعمل reload كامل للموقع مشان القائمة تروح مكانها الصح
window.toggleLang=function(){{
  let newLang=lang==='ar'?'en':'ar';
  lang=newLang; localStorage.setItem('omaia_lang',newLang);
  fetch('/toggle_lang').then(r=>r.json()).then(()=>{{ location.reload(); }});
}};
let pageCache={{}}; try{{pageCache=JSON.parse(localStorage.getItem('omaia_cache_v5')||'{{}}');}}catch(e){{pageCache={{}};}}
function saveCache(){{try{{localStorage.setItem('omaia_cache_v5',JSON.stringify(pageCache));}}catch(e){{}}}}
function prefetchPage(v){{ if(pageCache[v]) return; fetch('/api/page?v='+v+'&lang='+lang,{{cache:'no-store'}}).then(r=>r.text()).then(h=>{{pageCache[v]=h; saveCache();}}).catch(()=>{{}}); }}
async function loadPage(v,force=false,push=true){{
  if(push && cur!==v){{ try{{history.pushState({{page:v}}, '', '/dash?v='+v);}}catch(e){{}} }}
  cur=v; try{{localStorage.setItem('omaia_last_page',v);}}catch(e){{}}
  toggleSb(false);
  document.querySelectorAll('.sidebar a').forEach(a=>a.classList.remove('active')); let nav=document.getElementById('nav-'+v); if(nav) nav.classList.add('active');
  let mn=document.getElementById('mn');
  if(!force && pageCache[v]){{ mn.innerHTML=pageCache[v]; bind(); execScripts(); fetch('/api/page?v='+v+'&lang='+lang,{{cache:'no-store'}}).then(r=>r.text()).then(h=>{{ if(h && h.length>50){{ pageCache[v]=h; saveCache(); }} }}).catch(()=>{{}}); return; }}
  mn.innerHTML='<div class=card><div class="skeleton" style="height:20px;width:40%;border-radius:8px;margin-bottom:10px"></div><div class="skeleton" style="height:14px;border-radius:6px;margin-bottom:6px"></div><div class="skeleton" style="height:14px;width:80%;border-radius:6px"></div></div>';
  try{{let r=await fetch('/api/page?v='+v+'&lang='+lang,{{cache:'no-store'}}); let h=await r.text(); if(h && h.length>20){{ pageCache[v]=h; saveCache(); mn.innerHTML=h; bind(); execScripts(); }} }}catch(e){{ mn.innerHTML='<div class=card>❌ '+e+'<br><button class=btn-gold onclick="loadPage(\\''+v+'\\',true)">↻</button></div>'; }}
}}
function execScripts(){{document.getElementById('mn').querySelectorAll('script').forEach(s=>{{try{{(0,eval)(s.textContent)}}catch(e){{console.error(e)}}}});}}
function bind(){{
  document.querySelectorAll('form[data-ajax]').forEach(f=>{{
    if(f.dataset.bound) return; f.dataset.bound='1';
    f.onsubmit=async e=>{{
      e.preventDefault(); let btn=f.querySelector('button'); let old=btn?btn.innerHTML:''; if(btn){{btn.innerHTML='⏳ ثواني...'; btn.disabled=true;}}
      try{{let r=await fetch(f.action,{{method:'POST',body:new FormData(f)}}); let txt=await r.text(); if(r.ok){{ delete pageCache[cur]; await loadPage(cur,true,false); }} else {{ alert(txt); if(btn){{btn.innerHTML=old; btn.disabled=false;}} }} }}catch(err){{ alert(err); if(btn){{btn.innerHTML=old; btn.disabled=false;}} }}
    }};
  }});
}}
function askDel(u){{window._delUrl=u;document.getElementById('delModal').classList.add('show');}}
function closeDel(){{document.getElementById('delModal').classList.remove('show');window._delUrl=null;}}
window.closeEditModal=function(){{document.getElementById('editModal').classList.remove('show');}}
document.getElementById('editModal').addEventListener('click',e=>{{if(e.target.id==='editModal')closeEditModal();}});
document.getElementById('delModal').addEventListener('click',e=>{{if(e.target.id==='delModal')closeDel();}});
document.getElementById('delYes').onclick=async()=>{{if(window._delUrl){{let btn=document.getElementById('delYes'); let old=btn.innerHTML; btn.innerHTML='⏳...'; btn.disabled=true; let r=await fetch(window._delUrl); if(!r.ok){{let t=await r.text(); alert(t); btn.innerHTML=old; btn.disabled=false; closeDel(); return;}} delete pageCache[cur]; btn.innerHTML=old; btn.disabled=false; closeDel(); loadPage(cur,true,false);}}}};
async function toggleTheme(){{try{{await fetch('/toggle_theme'); location.reload();}}catch(e){{location.reload();}}}}
let searchTimer=null;
window.globalSearchTop=async function(q){{let box=document.getElementById('searchResults'); if(!q || q.trim().length<1){{box.style.display='none'; return;}} clearTimeout(searchTimer); searchTimer=setTimeout(async()=>{{try{{let r=await fetch('/api/search?q='+encodeURIComponent(q),{{cache:'no-store'}}); let d=await r.json(); if(!d || d.length==0){{box.innerHTML='<div style="padding:9px 14px;color:#9ca3af;font-size:12px">لا يوجد</div>'; box.style.display='block'; setTimeout(()=>box.style.display='none',1200); return;}} let h='<div style="padding:8px 12px;font-size:11px;color:#9ca3af;display:flex;justify-content:space-between"><span>🔍 '+d.length+'</span><span onclick="document.getElementById(\\'searchResults\\').style.display=\\'none\\'" style="cursor:pointer">✕</span></div>'; d.slice(0,8).forEach(x=>{{h+='<div onclick="loadPage(\\''+x.page+'\\');document.getElementById(\\'searchResults\\').style.display=\\'none\\'" style="padding:10px 12px;cursor:pointer;border-top:1px solid #ffffff08;display:flex;justify-content:space-between"><div><b style="font-size:12px">'+(x.title||'').substring(0,28)+'</b><br><small style="color:#6b7280">'+(x.sub||'').substring(0,22)+'</small></div><small style="background:#ffbe4d15;color:#ffbe4d;padding:3px 7px;border-radius:6px;font-size:10px">'+x.page+'</small></div>';}}); box.innerHTML=h; box.style.display='block';}}catch(e){{box.style.display='none';}}}},200);}}
window.toggleNotif=async function(){{let panel=document.getElementById('notifPanel'); panel.style.display=panel.style.display==='block'?'none':'block'; if(panel.style.display==='block'){{try{{let r=await fetch('/api/notifications'); let j=await r.json(); let h='<div style="padding:12px"><div style="display:flex;justify-content:space-between"><b>🔔 '+j.unread+'</b><button onclick="readAllNotif()" style="background:linear-gradient(90deg,#ffbe4d,#ffb020);border:0;padding:5px 10px;border-radius:8px;font-weight:800;cursor:pointer;font-size:12px">مقروء</button></div><hr style="border-color:#ffffff0f;margin:8px 0">'; j.rows.forEach(n=>{{h+='<div style="padding:8px;border-bottom:1px solid #ffffff08"><b style="color:#ffbe4d;font-size:12px">'+n.title+'</b><br><small style="color:#ccc">'+n.msg+'</small><br><small style="color:#666">'+n.time+'</small></div>';}}); h+='</div>'; panel.innerHTML=h;}}catch(e){{}}}}}}
window.readAllNotif=async function(){{try{{await fetch('/api/notifications/read',{{method:'POST'}});}}catch(e){{}} document.getElementById('notifCount').style.display='none'; document.getElementById('notifPanel').style.display='none';}}
async function loadNotif(){{try{{let r=await fetch('/api/notifications'); let j=await r.json(); let c=document.getElementById('notifCount'); if(j.unread>0){{c.textContent=j.unread>99?'99+':j.unread; c.style.display='flex';}} else {{c.style.display='none';}}}}catch(e){{}}}}
loadNotif(); setInterval(loadNotif,25000);
window.logoutFast=async function(){{try{{await fetch('/api/logout',{{method:'POST'}});}}catch(e){{}} try{{localStorage.removeItem('omaia_cache_v4'); localStorage.removeItem('omaia_cache_v5');}}catch(e){{}} location.replace('/login');}};
window.addEventListener('popstate',(e)=>{{let v='home'; if(e.state && e.state.page) v=e.state.page; else {{let p=new URLSearchParams(window.location.search); v=p.get('v')||'home';}} loadPage(v,false,false);}});
bind(); execScripts();
setTimeout(()=>{{let pages=['home','dishes','towers','subs','ledger','logs','ping']; let i=0; function next(){{if(i>=pages.length) return; let p=pages[i++]; if(!pageCache[p]){{fetch('/api/page?v='+p+'&lang='+lang,{{cache:'no-store'}}).then(r=>r.text()).then(h=>{{pageCache[p]=h; saveCache(); setTimeout(next,250);}}).catch(()=>setTimeout(next,250));}} else setTimeout(next,80);}} if('requestIdleCallback' in window) requestIdleCallback(next,{{timeout:2000}}); else next();}},1000);
if(!history.state){{try{{history.replaceState({{page:cur}}, '', '/dash?v='+cur);}}catch(e){{}}}}
setInterval(()=>{{fetch('/ping').catch(()=>{{}});}}, 900000);
</script></body></html>"""

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)), debug=False)
