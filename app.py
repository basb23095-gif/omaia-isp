# -*- coding: utf-8 -*-
from flask import Flask, request, redirect, session, jsonify, Response
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, html, ipaddress, secrets, subprocess, json, socket, platform, io, csv, datetime, re, threading, time, traceback
import concurrent.futures as _cf

try:
    import routeros_api
    ROUTEROS_AVAILABLE = True
except ImportError:
    routeros_api = None
    ROUTEROS_AVAILABLE = False

try:
    import psycopg2, psycopg2.extras
    from psycopg2 import pool as pg_pool
    PG = True
except Exception:
    psycopg2 = None; pg_pool = None; PG = False

import sqlite3
from collections import defaultdict

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "omaia_isp_fixed_secret_token_2026_xyz")
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(days=7)
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
            _pg_pool = None
            USE_PG = False
init_pool()

def esc(s): return html.escape(str(s or ''), quote=True)

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
            _sqlite_conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), "omia.db"), check_same_thread=False, timeout=10, isolation_level=None)
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
            r = [dict(x) for x in cur.fetchall()]
            cur.close(); put_conn(cn)
            return r
        else:
            with _slock: return [dict(x) for x in cn.execute(q, a).fetchall()]
    except Exception as e:
        print(f"[qall]{e}")
        if cn and USE_PG and hasattr(cn, 'closed'):
            try: put_conn(cn)
            except Exception: pass
        return []

def qone(q, a=()):
    r = qall(q, a)
    return r[0] if r else None

def qexec(q, a=()):
    cn = None
    try:
        cn = get_conn()
        if USE_PG and hasattr(cn, 'cursor'):
            cur = cn.cursor()
            cur.execute(q.replace("?", "%s"), a)
            cn.commit(); cur.close(); put_conn(cn)
        else:
            with _slock: cn.execute(q, a); cn.commit()
        return True
    except Exception as e:
        print(f"[qexec]{e}")
        if cn and USE_PG and hasattr(cn, 'closed'):
            try: cn.rollback(); put_conn(cn)
            except Exception: pass
        return False

def add_log(phone, action, target='', detail='', username=''):
    try:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not username:
            try: username = session.get('username') or session.get('phone') or phone or 'sys'
            except Exception: username = phone or 'sys'
        
        ok = qexec("INSERT INTO logs(user_phone,username,action,target,detail,time) VALUES(?,?,?,?,?,?)",
                   (phone or 'sys', username, action, str(target)[:300], str(detail)[:500], now))
        if not ok:
            qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)",
                  (phone or 'sys', action, str((detail or target))[:500], now))
        with _clock:
            for k in ['counts', 'logs_preview', 'all_data', 'towers_list', 'logs']:
                _cache.pop(k, None)
    except Exception as e:
        print(f"add_log err {e}")

def get_counts():
    with _clock:
        c = _cache.get('counts')
        if c and time.time() - c[1] < 60: return c[0]
    try:
        row = qone("SELECT (SELECT COUNT(*) FROM subs) as ns, (SELECT COUNT(*) FROM dish_ips) as nd, (SELECT COUNT(*) FROM towers) as nt, (SELECT COUNT(*) FROM ledger) as nl, (SELECT COUNT(*) FROM mikrotik_servers) as nm")
        if row:
            d = (row.get('ns', 0), row.get('nd', 0), row.get('nt', 0), row.get('nl', 0), row.get('nm', 0))
        else:
            d = (0, 0, 0, 0, 0)
        with _clock: _cache['counts'] = (d, time.time())
        return d
    except Exception: return (0, 0, 0, 0, 0)

def init_db():
    ss = [
        "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,username TEXT)",
        "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,note TEXT)",
        "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,amount REAL,note TEXT,currency TEXT)",
        "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,dish_name TEXT,tower_id INTEGER)",
        "CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,area TEXT,lat REAL,lng REAL,created_at TEXT)",
        "CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,user_phone TEXT,username TEXT,action TEXT,target TEXT,detail TEXT,time TEXT)",
        "CREATE TABLE IF NOT EXISTS system_config(key TEXT PRIMARY KEY,value TEXT)",
        "CREATE TABLE IF NOT EXISTS mikrotik_servers(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, host TEXT, username TEXT, password TEXT, port INTEGER DEFAULT 8728, note TEXT)"
    ]
    if USE_PG: ss = [s.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY") for s in ss]
    for s in ss: qexec(s)
    
    for al in [
        "ALTER TABLE dish_ips ADD COLUMN tower_id INTEGER",
        "ALTER TABLE towers ADD COLUMN created_at TEXT",
        "ALTER TABLE logs ADD COLUMN username TEXT",
        "ALTER TABLE logs ADD COLUMN target TEXT"
    ]:
        try: qexec(al)
        except Exception: pass

    idx = [
        "CREATE INDEX IF NOT EXISTS idx_dish_tower ON dish_ips(tower_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_dish_ip_unique ON dish_ips(ip)",
        "CREATE INDEX IF NOT EXISTS idx_tower_name ON towers(name)",
        "CREATE INDEX IF NOT EXISTS idx_logs_time ON logs(time)",
        "CREATE INDEX IF NOT EXISTS idx_users_phone ON users(phone)"
    ]
    for iq in idx:
        try: qexec(iq)
        except Exception: pass

    if not qone("SELECT * FROM users WHERE phone=?", ('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",
              ('05344851045', generate_password_hash('admin2024', method='pbkdf2:sha256:150000'), 'manager', 'admin'))

    if not qone("SELECT * FROM towers WHERE name=?", ('نقطة حماة الرئيسية',)):
        qexec("INSERT INTO towers(name,area,lat,lng,created_at) VALUES(?,?,?,?,?)",
              ('نقطة حماة الرئيسية', 'حماة', 35.1318, 36.7578, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

    defaults = [('card_size', '120'), ('icon_size', '32'), ('tower_bg', '#1e2433'), ('dish_bg', '#ffffff06'), ('accent_color', '#ffbe4d')]
    for k, v in defaults:
        if not qone("SELECT * FROM system_config WHERE key=?", (k,)):
            qexec("INSERT INTO system_config(key,value) VALUES(?,?)", (k, v))
init_db()

def login_required(f):
    @wraps(f)
    def w(*a, **kw):
        if not session.get('phone'):
            if request.path.startswith('/api/') or request.is_json:
                return jsonify(ok=False, msg='غير مسجل'), 401
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
    if not h: return False
    try:
        ipaddress.ip_address(h)
        return True
    except Exception:
        if len(h) >= 3 and '.' in h and ' ' not in h and re.match(r'^[a-zA-Z0-9.-]+\.[a-zA-Z0-9.-]+$', h):
            return True
        return False

def is_valid_ip(ip): return is_valid_host(ip)

@app.after_request
def after(r):
    r.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    r.headers['Pragma'] = 'no-cache'
    return r

def mikrotik_connect(host, user, pwd, port=8728):
    if not ROUTEROS_AVAILABLE:
        raise Exception("routeros_api غير مثبت")
    connection = routeros_api.RouterOsApiPool(
        host=host,
        username=user,
        password=pwd,
        port=int(port or 8728),
        plaintext_login=True
    )
    api = connection.get_api()
    return connection, api

@app.route('/api/mikrotik/list')
@login_required
def api_mikrotik_list():
    servers = qall("SELECT id, name, host, username, port, note FROM mikrotik_servers ORDER BY id DESC")
    return jsonify(ok=True, servers=servers)

@app.route('/api/mikrotik/add', methods=['POST'])
@login_required
@role_required_manager
def api_mikrotik_add():
    d = request.json if request.is_json else request.form
    name = (d.get('name') or '').strip()
    host = (d.get('host') or '').strip()
    user = (d.get('username') or '').strip()
    pwd = (d.get('password') or '').strip()
    port = int(d.get('port') or 8728)
    note = (d.get('note') or '').strip()
    
    if not host or not user:
        return jsonify(ok=False, msg='بيانات ناقصة'), 400
    
    ok = qexec("INSERT INTO mikrotik_servers(name,host,username,password,port,note) VALUES(?,?,?,?,?,?)",
               (name or host, host, user, pwd, port, note))
    if ok:
        add_log(session.get('phone'), 'إضافة ميكروتك', name or host, f"{host}:{port}")
    return jsonify(ok=ok)

@app.route('/api/mikrotik/del/<int:mid>')
@login_required
@role_required_manager
def api_mikrotik_del(mid):
    srv = qone("SELECT name, host FROM mikrotik_servers WHERE id=?", (mid,))
    ok = qexec("DELETE FROM mikrotik_servers WHERE id=?", (mid,))
    if ok and srv:
        add_log(session.get('phone'), 'حذف ميكروتك', srv['name'])
    return jsonify(ok=ok)

@app.route('/api/mikrotik/status/<int:mid>')
@login_required
def api_mikrotik_status(mid):
    srv = qone("SELECT * FROM mikrotik_servers WHERE id=?", (mid,))
    if not srv: return jsonify(ok=False, msg='غير موجود'), 404
    
    if not ROUTEROS_AVAILABLE:
        return jsonify(ok=False, msg='مكتبة routeros_api غير متوفرة'), 500

    conn = None
    try:
        conn, api = mikrotik_connect(srv['host'], srv['username'], srv['password'], srv['port'])
        res_resource = api.get_resource('/system/resource').get()
        res_identity = api.get_resource('/system/identity').get()
        res_active = api.get_resource('/ip/hotspot/active').get()
        res_ppp = api.get_resource('/ppp/active').get()

        info = {
            'identity': res_identity[0].get('name', '') if res_identity else '',
            'uptime': res_resource[0].get('uptime', '') if res_resource else '',
            'cpu': res_resource[0].get('cpu-load', '0') if res_resource else '0',
            'version': res_resource[0].get('version', '') if res_resource else '',
            'hotspot_active': len(res_active),
            'ppp_active': len(res_ppp)
        }
        return jsonify(ok=True, data=info)
    except Exception as e:
        return jsonify(ok=False, msg=f"تعذر الاتصال: {str(e)}"), 500
    finally:
        if conn:
            try: conn.disconnect()
            except Exception: pass

@app.route('/ping')
def ping(): return jsonify(ok=True, use_pg=USE_PG)

@app.route('/api/ping')
@login_required
def api_ping():
    ip = request.args.get('ip', '').strip()
    if not is_valid_ip(ip): return jsonify(ok=False, out='IP غير صالح')
    def try_port(p):
        s = None
        try:
            s = socket.socket(); s.settimeout(0.25)
            if s.connect_ex((ip, p)) == 0: return p
        except Exception: pass
        finally:
            if s:
                try: s.close()
                except Exception: pass
        return None
    try:
        with _cf.ThreadPoolExecutor(max_workers=3) as ex:
            futs = [ex.submit(try_port, p) for p in [80, 443, 8080]]
            for f in _cf.as_completed(futs, timeout=0.8):
                r = f.result()
                if r: return jsonify(ok=True, out=f'{ip}:{r} ✓')
    except Exception: pass
    return jsonify(ok=False, out=f'{ip} لا يرد')

@app.route('/api/ping_batch', methods=['POST'])
@login_required
def api_ping_batch():
    d = request.json if request.is_json else {}
    ips = (d.get('ips') or [])[:50]
    ips = [i.strip() for i in ips if i and is_valid_host(i.strip())]
    results = {}
    def chk(ip):
        ok = False; out = f"{ip} لا يرد"
        for port in [80, 443, 8080, 8291, 22, 8728]:
            s = None
            try:
                s = socket.socket(); s.settimeout(0.4)
                if s.connect_ex((ip, port)) == 0:
                    ok = True; out = f"{ip}:{port} ✓"; break
            except Exception: pass
            finally:
                if s:
                    try: s.close()
                    except Exception: pass
        if not ok:
            try:
                cmd = ['ping', '-c', '1', '-W', '1', ip] if platform.system().lower() != 'windows' else ['ping', '-n', '1', '-w', '800', ip]
                out_raw = subprocess.check_output(cmd, timeout=1, stderr=subprocess.STDOUT).decode(errors='ignore')
                if 'ttl=' in out_raw.lower():
                    ok = True; out = f"{ip} ✓"
            except Exception: pass
        return ip, ok, out

    with _cf.ThreadPoolExecutor(max_workers=20) as ex:
        futs = [ex.submit(chk, ip) for ip in ips]
        for f in _cf.as_completed(futs):
            try:
                ip, ok, msg = f.result()
                results[ip] = {'ok': ok, 'out': msg}
            except Exception: pass
    return jsonify(ok=True, results=results)

@app.route('/api/stats')
@login_required
def api_stats():
    ns, nd, nt, nl, nm = get_counts()
    logs = qall("SELECT * FROM logs ORDER BY id DESC LIMIT 10")
    return jsonify(ok=True, stats=dict(subs=ns, dishes=nd, towers=nt, ledger=nl, mikrotik=nm), logs=logs)

@app.route('/api/towers_list')
@login_required
def api_towers_list():
    with _clock:
        c = _cache.get('towers_list')
        if c and time.time() - c[1] < 60:
            return jsonify(ok=True, towers=c[0])
    towers = qall("SELECT id,name,area,lat,lng FROM towers ORDER BY name ASC")
    with _clock: _cache['towers_list'] = (towers, time.time())
    return jsonify(ok=True, towers=towers)

@app.route('/api/get_config')
@login_required
def get_config():
    rows = qall("SELECT * FROM system_config")
    cfg = {r['key']: r['value'] for r in rows}
    return jsonify(ok=True, config=cfg)

@app.route('/api/set_config', methods=['POST'])
@login_required
@role_required_manager
def set_config():
    d = request.json if request.is_json else request.form
    k = (d.get('key') or '').strip(); v = (d.get('value') or '').strip()
    if not k: return jsonify(ok=False, msg='key'), 400
    if USE_PG:
        qexec("INSERT INTO system_config(key,value) VALUES(?,?) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value", (k, v))
    else:
        qexec("INSERT OR REPLACE INTO system_config(key,value) VALUES(?,?)", (k, v))
    return jsonify(ok=True)

@app.route('/api/login_public', methods=['POST'])
def api_login_public():
    try:
        uin = request.form.get('userin', '').strip(); pw = request.form.get('password', '')
        u = qone("SELECT * FROM users WHERE phone=? OR username=?", (uin, uin))
        if u and check_password_hash(u['password'], pw):
            session.clear()
            session['phone'] = u['phone']
            session['username'] = u.get('username') or u['phone']
            session['role'] = u.get('role') or 'tech'
            session.permanent = True
            add_log(u['phone'], 'دخول', uin, f'{uin}', u.get('username') or uin)
            return jsonify(ok=True)
        return jsonify(ok=False, msg='بيانات الدخول غير صحيحة'), 401
    except Exception as e: return jsonify(ok=False, msg=str(e)), 500

@app.route('/api/export/<tbl>')
@login_required
def api_export(tbl):
    add_log(session.get('phone'), 'تصدير', tbl)
    output = io.StringIO(); output.write('\ufeff'); w = csv.writer(output)
    if tbl == 'dishes':
        rows = qall("SELECT * FROM dish_ips ORDER BY location ASC, dish_name ASC"); w.writerow(['ID', 'اسم', 'IP', 'موقع', 'tower_id'])
        for r in rows: w.writerow([r.get('id', ''), r.get('dish_name', ''), r.get('ip', ''), r.get('location', ''), r.get('tower_id', '')]); fname = 'dishes.csv'
    elif tbl == 'towers':
        rows = qall("SELECT * FROM towers ORDER BY name ASC"); w.writerow(['ID', 'اسم', 'منطقة', 'lat', 'lng'])
        for r in rows: w.writerow([r.get('id', ''), r.get('name', ''), r.get('area', ''), r.get('lat', ''), r.get('lng', '')]); fname = 'towers.csv'
    else:
        rows = qall("SELECT * FROM logs ORDER BY id DESC LIMIT 2000"); w.writerow(['ID', 'وقت', 'المستخدم', 'اسم المستخدم', 'عمل', 'الهدف', 'تفصيل'])
        for r in rows: w.writerow([r.get('id', ''), r.get('time', ''), r.get('user_phone', ''), r.get('username', ''), r.get('action', ''), r.get('target', ''), r.get('detail', '')]); fname = 'logs.csv'
    return Response(output.getvalue(), mimetype='text/csv; charset=utf-8', headers={'Content-Disposition': f'attachment; filename={fname}'})

@app.route('/api/clear_logs', methods=['POST'])
@login_required
@role_required_manager
def clear_logs(): qexec("DELETE FROM logs"); return jsonify(ok=True)

@app.route('/api/add_dish_to_tower', methods=['POST'])
@login_required
def add_dish_to_tower():
    try:
        d = request.json if request.is_json else request.form; ip = (d.get('ip') or '').strip(); name = (d.get('dish_name') or '').strip(); loc = (d.get('location') or '').strip(); tid = d.get('tower_id')
        if not is_valid_ip(ip): return jsonify(ok=False, msg='IP غير صالح'), 400
        if USE_PG: ok = qexec("INSERT INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?) ON CONFLICT (ip) DO UPDATE SET dish_name=EXCLUDED.dish_name, location=EXCLUDED.location, tower_id=EXCLUDED.tower_id", (ip, loc, name, int(tid) if tid and str(tid).isdigit() and int(tid) != 0 else None))
        else: ok = qexec("INSERT OR REPLACE INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?)", (ip, loc, name, int(tid) if tid and str(tid).isdigit() and int(tid) != 0 else None))
        if ok: add_log(session.get('phone'), 'إضافة صحن', f"{name}", f"IP: {ip}")
        with _clock: _cache.pop('counts', None)
        return jsonify(ok=ok)
    except Exception as e: return jsonify(ok=False, msg=str(e)), 500

@app.route('/api/tower_detail/<int:id>')
@login_required
def tower_detail(id):
    if id == 0:
        dishes = qall("SELECT * FROM dish_ips WHERE tower_id IS NULL ORDER BY dish_name ASC LIMIT 50")
        return jsonify(ok=True, tower=dict(id=0, name='بدون برج', area=''), dishes=dishes)
    t = qone("SELECT * FROM towers WHERE id=?", (id,))
    if not t: return jsonify(ok=False, msg='غير موجود'), 404
    dishes = qall("SELECT * FROM dish_ips WHERE tower_id=? ORDER BY dish_name ASC LIMIT 100", (id,))
    return jsonify(ok=True, tower=t, dishes=dishes)

@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login')
def login():
    return f"""<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>OMAIA ISP</title>
<style>
*{{box-sizing:border-box;font-family:system-ui}}body{{margin:0;min-height:100vh;background:radial-gradient(120% 120% at 10% 10%,#1a2344,#0a0e2a 60%);display:flex;align-items:center;justify-content:center;color:#fff}}
.card{{background:#1e2433ee;border:1px solid #ffffff18;padding:20px;border-radius:14px;width:92%;max-width:340px}}
input{{width:100%;padding:10px;margin:6px 0;background:#0f1424;border:1px solid #ffffff22;color:#fff;border-radius:8px}}
.btn{{width:100%;padding:11px;border:0;border-radius:8px;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:700;cursor:pointer}}
.support{{margin-top:14px;padding-top:10px;border-top:1px dashed #ffffff15;text-align:center}}
.support a{{display:inline-flex;align-items:center;justify-content:center;width:40px;height:40px;border-radius:50%;margin:0 6px;text-decoration:none;font-size:18px}}
</style></head><body>
<div class=card>
<div style='text-align:center;font-weight:800;font-size:22px;margin-bottom:12px'>OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<form id=loginForm>
<input name=userin id=userin placeholder='اسم المستخدم' required autofocus>
<input name=password id=password type=password placeholder='كلمة المرور' required>
<button class=btn id=loginBtn>دخول</button>
<div id=msg style='text-align:center;color:#ff6b6b;font-size:11px;margin-top:6px'></div>
</form>
<div class=support>
<a href="{SUPPORT_WA_LINK}" target="_blank" style="background:#25D366;color:#fff">💬</a>
<a href="{SUPPORT_INSTA_LINK}" target="_blank" style="background:linear-gradient(45deg,#feda75,#d62976);color:#fff">📷</a>
</div>
</div>
<script>
document.getElementById('loginForm').addEventListener('submit', async e => {{
  e.preventDefault();
  let b = document.getElementById('loginBtn'), m = document.getElementById('msg');
  b.textContent = '...'; b.disabled = true;
  try {{
    let res = await fetch('/api/login_public', {{ method: 'POST', body: new FormData(e.target) }});
    let j = await res.json();
    if(j.ok) location.replace('/dash?v=home');
    else {{ m.textContent = j.msg || 'خطأ'; b.textContent = 'دخول'; b.disabled = false; }}
  }} catch {{
    m.textContent = 'خطأ اتصال'; b.textContent = 'دخول'; b.disabled = false;
  }}
}});
</script></body></html>"""

@app.route('/logout')
def lo(): session.clear(); return redirect('/login')

@app.route('/dash')
@login_required
def dash(): v = request.args.get('v', 'home'); return layout('<div class=card>جاري التحميل...</div>', v)

@app.route('/api/page')
@login_required
def ap():
    try: return page_content(request.args.get('v', 'home'))
    except Exception as e: traceback.print_exc(); return f"<div class=card>خطأ: {esc(str(e))}</div>", 500

@app.route('/add_tower', methods=['POST'])
@login_required
def at():
    try:
        d = request.json if request.is_json else request.form; la = float(d.get('lat') or 35.1318); ln = float(d.get('lng') or 36.7578)
        ok = qexec("INSERT INTO towers(name,area,lat,lng,created_at) VALUES(?,?,?,?,?)", (d.get('name', 'برج'), d.get('area', ''), la, ln, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        if ok:
            add_log(session.get('phone'), 'إضافة برج', d.get('name', ''))
            with _clock: _cache.pop('towers_list', None)
        return jsonify(ok=ok)
    except Exception as e: return jsonify(ok=False, msg=str(e)), 500

@app.route('/del_tower/<int:i>')
@login_required
def dt(i):
    if not is_manager(): return jsonify(ok=False, msg='ممنوع'), 403
    qexec("UPDATE dish_ips SET tower_id=NULL WHERE tower_id=?", (i,)); ok = qexec("DELETE FROM towers WHERE id=?", (i,))
    if ok: add_log(session.get('phone'), 'حذف برج', f"{i}")
    return jsonify(ok=ok)

@app.route('/del_dish/<int:i>')
@login_required
def dd(i):
    if not is_manager(): return jsonify(ok=False, msg='ممنوع'), 403
    ok = qexec("DELETE FROM dish_ips WHERE id=?", (i,))
    if ok:
        with _clock: _cache.pop('counts', None)
        add_log(session.get('phone'), 'حذف صحن', f"{i}")
    return jsonify(ok=ok)

@app.route('/add_sub', methods=['POST'])
@login_required
def asub():
    d = request.json if request.is_json else request.form; ok = qexec("INSERT INTO subs(name,phone,note) VALUES(?,?,?)", (d.get('name', ''), d.get('phone', ''), d.get('note', '')))
    if ok: add_log(session.get('phone'), 'إضافة مشترك', d.get('name', ''))
    return jsonify(ok=ok)

@app.route('/del_sub/<int:i>')
@login_required
def dsub(i):
    if not is_manager(): return jsonify(ok=False), 403
    ok = qexec("DELETE FROM subs WHERE id=?", (i,))
    return jsonify(ok=ok)

@app.route('/add_ledger', methods=['POST'])
@login_required
def al():
    d = request.json if request.is_json else request.form
    try: amt = float(d.get('amount') or 0)
    except Exception: amt = 0
    ok = qexec("INSERT INTO ledger(name,amount,note,currency) VALUES(?,?,?,?)", (d.get('name', ''), amt, d.get('note', ''), d.get('currency', 'USD')))
    return jsonify(ok=ok)

@app.route('/del_ledger/<int:i>')
@login_required
def dll(i):
    if not is_manager(): return jsonify(ok=False), 403
    ok = qexec("DELETE FROM ledger WHERE id=?", (i,))
    return jsonify(ok=ok)

@app.route('/change_pass', methods=['POST'])
@login_required
def cp():
    d = request.json if request.is_json else request.form; np = (d.get('newpass') or '').strip()
    if not np: return jsonify(ok=False, msg='فارغ'), 400
    ok = qexec("UPDATE users SET password=? WHERE phone=?", (generate_password_hash(np, method='pbkdf2:sha256:150000'), session.get('phone')))
    return jsonify(ok=ok)

def page_content(v):
    if v == 'home':
        return f"""
<div style="max-width:1100px;margin:0 auto">
<div class=grid-small id=statsGrid>
<div class="card stat" onclick="loadPage('subs')"><div class=ico>👥</div><h4>المشتركين</h4><h3 id=stat-subs>...</h3></div>
<div class="card stat" onclick="loadPage('dishes')"><div class=ico>📡</div><h4>الصحون</h4><h3 id=stat-dishes>...</h3></div>
<div class="card stat" onclick="loadPage('towers')"><div class=ico>🗼</div><h4>الأبراج</h4><h3 id=stat-towers>...</h3></div>
<div class="card stat" onclick="loadPage('ledger')"><div class=ico>📒</div><h4>الحسابات</h4><h3 id=stat-ledger>...</h3></div>
<div class="card stat" onclick="loadPage('mikrotik')"><div class=ico>🖧</div><h4>ميكروتك</h4><h3 id=stat-mikrotik>...</h3></div>
</div>
<div class=card style="margin-top:8px"><div style="display:flex;justify-content:space-between"><b>📜 السجل</b><button class=btn-gold onclick="loadPage('logs')">الكل</button></div>
<div id=logsPreview style="margin-top:6px"></div>
</div>
</div>
<script>
(async()=>{{
 try{{
  let r=await fetch('/api/stats');
  if(r.status===401) {{ location.replace('/login'); return; }}
  let j=await r.json();
  if(j.ok){{
   document.getElementById('stat-subs').textContent=j.stats.subs;
   document.getElementById('stat-dishes').textContent=j.stats.dishes;
   document.getElementById('stat-towers').textContent=j.stats.towers;
   document.getElementById('stat-ledger').textContent=j.stats.ledger;
   let mkEl = document.getElementById('stat-mikrotik');
   if(mkEl) mkEl.textContent=j.stats.mikrotik || 0;
   let lh=j.logs.map(l=>`<tr><td>${{l.time||''}}</td><td><span class=badge>${{l.action||''}}</span></td><td>${{l.user_phone||''}}</td><td>${{(l.detail||'').substring(0,40)}}</td></tr>`).join('') || '<tr><td colspan=4>فارغ</td></tr>';
   document.getElementById('logsPreview').innerHTML='<table style="width:100%"><thead><tr><th>وقت</th><th>عمل</th><th>يوزر</th><th>تفصيل</th></tr></thead><tbody>'+lh+'</tbody></table>';
  }}
 }}catch(e){{}}
}})();
</script>"""

    if v == 'mikrotik':
        servers = qall("SELECT * FROM mikrotik_servers ORDER BY id DESC")
        cards = ""
        for s in servers:
            sid = s['id']
            cards += f"""
<div class="card" id="mk-server-{sid}">
  <div style="display:flex;justify-content:space-between;align-items:center">
    <div>
      <b style="font-size:13px">🖧 {esc(s['name'])}</b>
      <div style="font-size:10px;color:#94a3b8;margin-top:2px">{esc(s['host'])}:{s['port']} | {esc(s['username'])}</div>
    </div>
    <div style="display:flex;gap:4px">
      <button class="glass-btn view" onclick="fetchMikrotikStatus({sid})">⚡</button>
      <button class="glass-btn del" onclick="delMikrotik({sid})">🗑</button>
    </div>
  </div>
  <div id="mk-details-{sid}" style="margin-top:8px;padding:8px;background:#0006;border-radius:6px;font-size:11px;display:none"></div>
</div>"""
        return f"""
<div style="max-width:1100px;margin:0 auto">
  <div class=card style="display:flex;justify-content:space-between;align-items:center">
    <b>سيرفرات ميكروتك</b>
    <button class=btn-gold onclick="openAddMikrotikModal()">+ سيرفر</button>
  </div>
  <div style="display:flex;flex-direction:column;gap:6px;margin-top:8px">{cards or '<div class=card>لا يوجد سيرفرات</div>'}</div>
</div>
<script>
window.openAddMikrotikModal=function(){{
  let b=document.getElementById("editBody");
  b.innerHTML=`
    <div style="display:flex;flex-direction:column;gap:6px">
      <input id="mk_name" placeholder="اسم السيرفر">
      <input id="mk_host" placeholder="IP أو دومين السيرفر">
      <input id="mk_user" placeholder="اسم المستخدم">
      <input id="mk_pwd" type="password" placeholder="كلمة المرور">
      <input id="mk_port" type="number" value="8728" placeholder="المنفذ">
      <input id="mk_note" placeholder="ملاحظات">
      <button class="btn-gold" onclick="saveNewMikrotik()" style="width:100%;margin-top:4px">حفظ</button>
    </div>
  `;
  document.getElementById("editModalTitle").textContent="إضافة سيرفر";
  document.getElementById("editModal").classList.add("show");
}};

window.saveNewMikrotik=async function(){{
  let d={{name:document.getElementById("mk_name").value,host:document.getElementById("mk_host").value,username:document.getElementById("mk_user").value,password:document.getElementById("mk_pwd").value,port:document.getElementById("mk_port").value,note:document.getElementById("mk_note").value}};
  if(!d.host||!d.username){{alert("بيانات ناقصة");return;}}
  let r=await fetch('/api/mikrotik/add',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}});
  let j=await r.json();
  if(j.ok){{closeEditModal();loadPage('mikrotik',true);}}else alert(j.msg||"خطأ");
}};

window.delMikrotik=async function(id){{
  if(!confirm("حذف السيرفر؟"))return;
  let r=await fetch('/api/mikrotik/del/'+id);
  let j=await r.json();
  if(j.ok) loadPage('mikrotik',true);
}};

window.fetchMikrotikStatus=async function(id){{
  let box=document.getElementById("mk-details-"+id);
  box.style.display="block";
  box.innerHTML="⏳ جاري الاتصال...";
  try{{
    let r=await fetch('/api/mikrotik/status/'+id);
    let j=await r.json();
    if(j.ok){{
      let d=j.data;
      box.innerHTML=`
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px">
          <div><b>الهوية:</b> ${{d.identity||'--'}}</div>
          <div><b>الإصدار:</b> ${{d.version||'--'}}</div>
          <div><b>Uptime:</b> ${{d.uptime||'--'}}</div>
          <div><b>CPU:</b> ${{d.cpu}}%</div>
          <div><b>Hotspot:</b> <span class="badge">${{d.hotspot_active}}</span></div>
          <div><b>PPPoE:</b> <span class="badge">${{d.ppp_active}}</span></div>
        </div>
      `;
    }}else box.innerHTML='<span style="color:#ef4444">'+j.msg+'</span>';
  }}catch(e){{box.innerHTML='<span style="color:#ef4444">خطأ اتصال</span>';}}
}};
</script>"""

    if v == 'towers':
        rs = qall("SELECT t.id,t.name,t.area,t.lat,t.lng, COUNT(d.id) as cnt FROM towers t LEFT JOIN dish_ips d ON d.tower_id=t.id GROUP BY t.id,t.name,t.area,t.lat,t.lng ORDER BY t.name ASC")
        cards = ""
        for t in rs:
            tid = t.get('id'); tname = esc(t.get('name') or f'برج {tid}'); tarea = esc(t.get('area') or ''); lat = t.get('lat') or 35.1318; lng = t.get('lng') or 36.7578; cnt = t.get('cnt') or 0
            cards += f'<div class="card tower-card" id="tower-{tid}"><div style="display:flex;justify-content:space-between;align-items:center"><div><b style="font-size:13px">🗼 {tname}</b><div style="font-size:10px;color:#94a3b8;margin-top:2px">📍 {tarea} ({lat:.4f},{lng:.4f})</div></div><span class=badge>{cnt} IP</span></div><div style="display:flex;gap:4px;margin-top:6px"><button class="glass-btn del" onclick="delTower({tid})">🗑</button></div></div>'
        return f"""<div style="max-width:1100px;margin:0 auto"><div class=card style="display:flex;justify-content:space-between;align-items:center"><b>الأبراج</b><button class=btn-gold onclick="openNewTowerPage()">+ برج</button></div><input id="searchTowers" onkeyup="filterCards('searchTowers', '.tower-card')" placeholder="بحث عن برج..." style="margin-top:6px;width:100%"><div class=grid-small id=towersGrid style="margin-top:8px">{cards or '<div class=card>فارغ</div>'}</div></div>
<script>
window.openNewTowerPage=function(){{
  let b=document.getElementById("editBody");
  b.innerHTML='<input id=nt_name placeholder="الاسم"><input id=nt_area placeholder="المنطقة"><div style="display:flex;gap:4px"><input id=nt_lat value="35.1318"><input id=nt_lng value="36.7578"></div><button class=btn-gold onclick="saveNewTowerPage()" style="width:100%;margin-top:6px">حفظ</button>';
  document.getElementById("editModalTitle").textContent="إضافة برج";
  document.getElementById("editModal").classList.add("show");
}};
window.saveNewTowerPage=async function(){{
  let d={{name:document.getElementById("nt_name").value,area:document.getElementById("nt_area").value,lat:document.getElementById("nt_lat").value,lng:document.getElementById("nt_lng").value}};
  if(!d.name)return;
  let r=await fetch("/add_tower",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify(d)}});
  let j=await r.json();
  if(j.ok){{closeEditModal();loadPage('towers',true);}}
}};
window.delTower=async function(id){{
  if(!confirm("حذف البرج؟"))return;
  let r=await fetch('/del_tower/'+id);
  let j=await r.json();
  if(j.ok) loadPage('towers',true);
}};
</script>"""

    if v == 'dishes':
        towers = qall("SELECT t.id, t.name, t.area, t.lat, t.lng, (SELECT COUNT(*) FROM dish_ips WHERE tower_id=t.id) as cnt FROM towers t ORDER BY t.name ASC")
        no_cnt = (qone("SELECT COUNT(*) as c FROM dish_ips WHERE tower_id IS NULL") or {}).get('c', 0)
        accordion_html = ""
        for t in towers:
            tid = t.get('id'); tname = esc(t.get('name') or f'برج {tid}'); tarea = esc(t.get('area') or ''); cnt = t.get('cnt') or 0
            accordion_html += f'''
<div class="card tower-accordion" id="tower-acc-{tid}">
  <div onclick="toggleAccordionLazy({tid})" style="display:flex;justify-content:space-between;align-items:center;cursor:pointer">
    <div><b style="font-size:13px">🗼 {tname}</b> <span class="badge">{cnt} IP</span><div style="font-size:10px;color:#94a3b8">📍 {tarea}</div></div>
    <div>▼</div>
  </div>
  <div id="tower-body-{tid}" style="display:none;margin-top:6px;padding-top:6px;border-top:1px dashed #ffffff22">
    <div id="tower-content-{tid}">...</div>
  </div>
</div>'''
        accordion_html += f'''
<div class="card tower-accordion" id="tower-acc-0" style="border:1px dashed #ef444488">
  <div onclick="toggleAccordionLazy(0)" style="display:flex;justify-content:space-between;align-items:center;cursor:pointer">
    <div><b style="font-size:13px">بدون برج</b> <span class="badge" style="background:#ef4444">{no_cnt} IP</span></div>
    <div>▼</div>
  </div>
  <div id="tower-body-0" style="display:none;margin-top:6px;padding-top:6px;border-top:1px dashed #ffffff22">
    <div id="tower-content-0"></div>
  </div>
</div>'''
        return f"""
<div style="max-width:1100px;margin:0 auto">
  <div class=card style="display:flex;justify-content:space-between;align-items:center">
    <b>الصحون</b>
    <button class=btn-gold onclick="openAddDishModal(0)">+ صحن</button>
  </div>
  <input id="searchDishes" onkeyup="filterCards('searchDishes', '.tower-accordion')" placeholder="بحث عن برج أو صحن..." style="margin-top:6px;width:100%">
  <div style="display:flex;flex-direction:column;gap:6px;margin-top:8px">{accordion_html}</div>
</div>
<script>
window.toggleAccordionLazy=async function(tid){{
  let b=document.getElementById('tower-body-'+tid);
  if(b.style.display==='none'){{
    b.style.display='block';
    let c=document.getElementById('tower-content-'+tid);
    c.innerHTML='⏳ تحميل...';
    try{{
      let r=await fetch('/api/tower_detail/'+tid);
      if(r.status===401){{location.replace('/login');return;}}
      let j=await r.json();
      if(j.ok){{
        c.innerHTML=(j.dishes||[]).map(d=>`
          <div style="display:flex;justify-content:space-between;align-items:center;padding:4px 0;border-bottom:1px solid #ffffff11">
            <div><b style="font-size:12px">${{d.dish_name||'صحن'}}</b> - <span class="ip" style="cursor:pointer" onclick="openLink('${{d.ip}}')">${{d.ip}}</span> <small style="color:#888">${{d.location||''}}</small></div>
            <button class="glass-btn del" onclick="delDish(${{d.id}})">🗑</button>
          </div>
        `).join('') || '<div style="color:#888;font-size:11px">فارغ</div>';
        c.innerHTML += `<button class="btn-gold" onclick="openAddDishModal(${{tid}})" style="width:100%;margin-top:6px">+ إضافة صحن</button>`;
      }}
    }}catch(e){{c.innerHTML='خطأ';}}
  }}else b.style.display='none';
}};
window.openAddDishModal=function(tid){{
  let b=document.getElementById("editBody");
  b.innerHTML=`
    <input id="dish_name" placeholder="اسم الصحن">
    <input id="dish_ip" placeholder="IP">
    <input id="dish_loc" placeholder="الموقع">
    <input type="hidden" id="dish_tid" value="${{tid}}">
    <button class="btn-gold" onclick="saveNewDish()" style="width:100%;margin-top:4px">حفظ</button>
  `;
  document.getElementById("editModalTitle").textContent="إضافة صحن";
  document.getElementById("editModal").classList.add("show");
}};
window.saveNewDish=async function(){{
  let d={{dish_name:document.getElementById("dish_name").value,ip:document.getElementById("dish_ip").value,location:document.getElementById("dish_loc").value,tower_id:document.getElementById("dish_tid").value}};
  if(!d.ip){{alert("IP مطلوب");return;}}
  let r=await fetch('/api/add_dish_to_tower',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}});
  let j=await r.json();
  if(j.ok){{closeEditModal();loadPage('dishes',true);}}
}};
window.delDish=async function(id){{
  if(!confirm("حذف؟"))return;
  let r=await fetch('/del_dish/'+id);
  let j=await r.json();
  if(j.ok) loadPage('dishes',true);
}};
</script>"""

    if v == 'map':
        return """
<div class=card>
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
    <b>الخريطة</b>
    <span id="mapStatus" style="font-size:11px;color:#ffbe4d"></span>
  </div>
  <div id="map" style="height:70vh;border-radius:8px;background:#0f1424"></div>
</div>
<script>
(async function(){
  try {
    let map = L.map('map').setView([35.1318, 36.7578], 11);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 18 }).addTo(map);
    let r = await fetch('/api/towers_list');
    let j = await r.json();
    if(j.ok && j.towers){
      j.towers.forEach(t => {
        if(t.lat && t.lng){
          L.marker([t.lat, t.lng]).addTo(map).bindPopup("<b>"+t.name+"</b><br>"+(t.area||''));
        }
      });
      document.getElementById('mapStatus').textContent = j.towers.length + " برج";
    }
  } catch(e) {}
})();
</script>"""

    if v == 'ping':
        return """
<div class=card>
  <b>البنج</b>
  <div style="display:flex;gap:6px;margin-top:8px">
    <input id="pingIp" placeholder="IP الجهاز" style="flex:1">
    <button class="btn-gold" onclick="runPing()">فحص</button>
  </div>
  <div id="pingRes" style="margin-top:8px;padding:8px;background:#000a;border-radius:6px;font-family:monospace;min-height:30px;color:#22c55e;font-size:11px">جاهز</div>
</div>
<script>
window.runPing=async function(){
  let ip=document.getElementById('pingIp').value.trim();
  if(!ip)return;
  let o=document.getElementById('pingRes');
  o.textContent='...';
  try{
    let r=await fetch('/api/ping?ip='+encodeURIComponent(ip));
    let j=await r.json();
    o.textContent=j.out;
  }catch(e){o.textContent='خطأ';}
};
</script>"""

    if v == 'network':
        dishes = qall("SELECT * FROM dish_ips ORDER BY dish_name ASC LIMIT 100")
        cards = ""
        for d in dishes:
            cards += f"""
<div class="card" id="net-card-{d['id']}">
  <div style="display:flex;justify-content:space-between"><b style="font-size:12px">{esc(d.get('dish_name') or 'صحن')}</b><span class="badge">{esc(d.get('location') or '')}</span></div>
  <div style="margin-top:4px;display:flex;justify-content:space-between;align-items:center">
    <span class="ip" style="cursor:pointer" onclick="openLink('{esc(d.get('ip') or '')}')">{esc(d.get('ip') or '')}</span>
    <span class="net-status" id="net-status-{d['id']}" style="font-size:10px;color:#888">-</span>
  </div>
</div>"""
        return f"""
<div class=card style="display:flex;justify-content:space-between;align-items:center">
  <b>الشبكة</b>
  <button class=btn-gold onclick="pingAllNetwork()">فحص الكل</button>
</div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:8px">{cards or '<div class=card>فارغ</div>'}</div>
<script>
window.pingAllNetwork=async function(){{
  let cards=document.querySelectorAll("[id^=net-card-]");
  for(let c of cards){{
    let id=c.id.replace('net-card-','');
    let ipEl=c.querySelector('.ip');
    let stEl=document.getElementById('net-status-'+id);
    if(ipEl && stEl){{
      stEl.textContent='...';
      fetch('/api/ping?ip='+encodeURIComponent(ipEl.textContent)).then(r=>r.json()).then(j=>{{stEl.textContent=j.out;}}).catch(()=>{{stEl.textContent='لا يرد';}});
    }}
    await new Promise(r=>setTimeout(r, 60));
  }}
}};
</script>"""

    if v == 'subs':
        rs = qall("SELECT * FROM subs ORDER BY name ASC LIMIT 100")
        rows = "".join([f"<tr><td>{esc(r.get('name') or '')}</td><td><span class=ip>{esc(r.get('phone') or '')}</span></td><td>{esc(r.get('note') or '')}</td><td><button class=\"glass-btn del\" onclick=\"delSub({r.get('id')})\">🗑</button></td></tr>" for r in rs])
        return f"""
<div class=card style="display:flex;justify-content:space-between;align-items:center"><b>المشتركين</b><button class=btn-gold onclick="document.getElementById('fSub').style.display='flex'">+ مشترك</button></div>
<form id=fSub style="display:none;gap:4px;margin-top:6px"><input name=name placeholder="الاسم" required><input name=phone placeholder="الهاتف" required><input name=note placeholder="ملاحظة"><button class=btn-gold>+</button></form>
<input id="searchSubs" onkeyup="filterTable('searchSubs', 'subsTable')" placeholder="بحث عن مشترك..." style="margin-top:6px;width:100%">
<table id="subsTable" style="width:100%;margin-top:8px"><thead><tr><th>الاسم</th><th>الهاتف</th><th>ملاحظة</th><th></th></tr></thead><tbody>{rows or '<tr><td colspan=4>فارغ</td></tr>'}</tbody></table>
<script>
document.getElementById('fSub').addEventListener('submit',async e=>{{e.preventDefault();let r=await fetch('/add_sub',{{method:'POST',body:new FormData(e.target)}});let j=await r.json();if(j.ok)loadPage('subs',true);}});
window.delSub=async function(id){{if(!confirm("حذف؟"))return;let r=await fetch('/del_sub/'+id);let j=await r.json();if(j.ok)loadPage('subs',true);}};
</script>"""

    if v == 'ledger':
        rs = qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 100")
        rows = "".join([f"<tr><td>{esc(r.get('name') or '')}</td><td><b>{r.get('amount')} {esc(r.get('currency') or '')}</b></td><td>{esc(r.get('note') or '')}</td><td><button class=\"glass-btn del\" onclick=\"delLedger({r.get('id')})\">🗑</button></td></tr>" for r in rs])
        return f"""
<div class=card style="display:flex;justify-content:space-between;align-items:center"><b>الحسابات</b><button class=btn-gold onclick="document.getElementById('fLed').style.display='flex'">+ إضافة</button></div>
<form id=fLed style="display:none;gap:4px;margin-top:6px"><input name=name placeholder="البيان" required><input name=amount type=number step=0.01 placeholder="المبلغ" required><input name=note placeholder="ملاحظة"><select name=currency><option>USD</option><option>SYP</option></select><button class=btn-gold>+</button></form>
<input id="searchLedger" onkeyup="filterTable('searchLedger', 'ledgerTable')" placeholder="بحث في الحسابات..." style="margin-top:6px;width:100%">
<table id="ledgerTable" style="width:100%;margin-top:8px"><thead><tr><th>البيان</th><th>المبلغ</th><th>ملاحظة</th><th></th></tr></thead><tbody>{rows or '<tr><td colspan=4>فارغ</td></tr>'}</tbody></table>
<script>
document.getElementById('fLed').addEventListener('submit',async e=>{{e.preventDefault();let r=await fetch('/add_ledger',{{method:'POST',body:new FormData(e.target)}});let j=await r.json();if(j.ok)loadPage('ledger',true);}});
window.delLedger=async function(id){{if(!confirm("حذف؟"))return;let r=await fetch('/del_ledger/'+id);let j=await r.json();if(j.ok)loadPage('ledger',true);}};
</script>"""

    if v == 'settings':
        return f"""
<div style="max-width:1100px;margin:0 auto">
  <div class=card>
    <b>كلمة المرور</b>
    <form id=formPass style="display:flex;gap:6px;margin-top:6px">
      <input name=newpass type=password placeholder="كلمة المرور الجديدة" required style="flex:1">
      <button class=btn-gold>حفظ</button>
    </form>
  </div>
  <div class=card style="margin-top:8px">
    <b>الدعم الفني</b>
    <div style="margin-top:4px"><a href="{SUPPORT_WA_LINK}" target="_blank" style="color:#25D366;text-decoration:none">واتساب +{SUPPORT_WA}</a></div>
  </div>
</div>
<script>
document.getElementById("formPass").addEventListener("submit",async e=>{{e.preventDefault();let r=await fetch("/change_pass",{{method:"POST",body:new FormData(e.target)}});let j=await r.json();if(j.ok){{alert("تم الحفظ");e.target.reset();}}}});
</script>"""

    if v == 'logs':
        rs = qall("SELECT * FROM logs ORDER BY id DESC LIMIT 200")
        rows = "".join([f"<tr><td>{esc(r.get('time',''))}</td><td><b>{esc(r.get('username') or r.get('user_phone',''))}</b></td><td><span class=badge>{esc(r.get('action',''))}</span></td><td>{esc(r.get('target',''))}</td><td>{esc(r.get('detail',''))}</td></tr>" for r in rs])
        return f"""
<div class=card style="display:flex;justify-content:space-between;align-items:center"><b>السجل</b><div style="display:flex;gap:4px"><a href="/api/export/logs" class=btn-gold style="text-decoration:none">CSV</a><button class=btn-gold onclick="clearAllLogs()" style="background:#ef4444">مسح</button></div></div>
<table style="width:100%;margin-top:8px"><thead><tr><th>وقت</th><th>المستخدم</th><th>عملية</th><th>الهدف</th><th>تفاصيل</th></tr></thead><tbody>{rows or '<tr><td colspan=5>فارغ</td></tr>'}</tbody></table>
<script>
window.clearAllLogs=async function(){{if(!confirm("مسح؟"))return;await fetch("/api/clear_logs",{{method:"POST"}});loadPage("logs",true);}};
</script>"""

    return "<div class=card>غير موجود</div>"

def layout(c, v='home'):
    cur_user = qone("SELECT * FROM users WHERE phone=?", (session.get('phone') or '',)) or {}
    return f"""<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>OMAIA ISP</title>
<link rel=stylesheet href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'>
<style>
*{{box-sizing:border-box;font-family:system-ui}}html,body{{margin:0;padding:0}}
body{{background:radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 60%, #070a1f 100%);color:#fff;overflow-x:hidden}}
.card{{background:#1e2433ee;color:#fff;padding:8px 10px;border-radius:10px;margin-bottom:6px;border:1px solid #ffffff18}}
.btn-gold{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;padding:6px 10px;border:0;border-radius:6px;font-weight:700;font-size:11px;cursor:pointer}}
.grid-small{{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:6px}}
.top{{position:fixed;top:0;left:0;right:0;height:48px;background:#1e2433;display:flex;align-items:center;justify-content:space-between;padding:0 10px;z-index:1003;border-bottom:1px solid #ffffff18}}
.sidebar{{position:fixed;top:0;right:0;width:240px;height:100vh;background:rgba(15,20,36,0.96);backdrop-filter:blur(15px);z-index:1002;padding:12px;transform:translateX(110%);transition:transform .2s ease;overflow-y:auto;border-left:1px solid #ffffff18}}
.sidebar.active{{transform:none}}
.sidebar a{{display:flex;align-items:center;gap:10px;padding:8px 10px;margin-bottom:6px;color:#fff;text-decoration:none;border-radius:8px;background:#ffffff08;font-size:13px;font-weight:600}}
.sidebar a.active{{background:rgba(255,190,77,0.2);color:#ffbe4d;border:1px solid #ffbe4d}}
#overlay{{position:fixed;inset:0;background:#0008;z-index:1001;display:none}} #overlay.show{{display:block}}
.main{{margin-top:54px;padding:8px;min-height:90vh}}

/* أزرار Glassmorphism الدائرية الأنيقة */
.glass-btn{{width:32px;height:32px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;cursor:pointer;border:1px solid rgba(255,255,255,0.3);background:rgba(255,255,255,0.15);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);color:#fff;font-size:12px;transition:all 0.3s ease;}}
.glass-btn:hover{{background:rgba(255,255,255,0.3);transform:scale(1.1);}}
.glass-btn.del{{background:rgba(239,68,68,0.2);color:#ef4444;border-color:rgba(239,68,68,0.4);}}
.glass-btn.view{{background:rgba(6,182,212,0.2);color:#06b6d4;border-color:rgba(6,182,212,0.4);}}

.ip{{background:#000;color:#ffbe4d;padding:2px 6px;border-radius:4px;font-family:monospace;font-size:10px}}
.badge{{background:#ffbe4d;color:#111;padding:2px 5px;border-radius:4px;font-size:10px;font-weight:700}}
table{{width:100%;border-collapse:collapse}} th{{background:#ffffff11;padding:6px;text-align:right;font-size:11px}} td{{padding:6px;border-bottom:1px solid #ffffff11;font-size:11px}}
#editModal{{position:fixed;inset:0;background:#0009;display:none;align-items:center;justify-content:center;z-index:2000}}
#editModal.show{{display:flex}}
#editBox{{background:#1e2433;border:1px solid #ffffff22;border-radius:10px;padding:14px;width:90%;max-width:380px}}
input,select{{width:100%;padding:8px;border-radius:6px;border:1px solid #ffffff22;background:#0f1424;color:#fff;margin-bottom:6px;font-size:12px}}
.stat{{text-align:center;cursor:pointer;padding:8px 4px}} .stat h4{{margin:2px 0;font-size:11px}} .stat h3{{margin:2px 0;font-size:14px}} .ico{{font-size:18px}}
</style>
<script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>
</head><body>
<div id=overlay onclick="toggleSb(false)"></div>
<div class=sidebar id=sb>
<div style='padding-bottom:10px;border-bottom:1px solid #ffffff18;margin-bottom:8px'><b style="font-size:15px">OMAIA <span style='color:#ffbe4d'>ISP</span></b><br><small>{esc(cur_user.get('username') or '')}</small></div>
<a href="#" onclick="event.preventDefault(); loadPage('home')" id=nav-home>🏠 <span>الرئيسية</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('mikrotik')" id=nav-mikrotik>🖧 <span>ميكروتك</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('towers')" id=nav-towers>🗼 <span>الأبراج</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('dishes')" id=nav-dishes>📡 <span>الصحون</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('map')" id=nav-map>🗺 <span>الخريطة</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('ping')" id=nav-ping>📶 <span>البنج</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('network')" id=nav-network>📊 <span>الشبكة</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('subs')" id=nav-subs>👥 <span>المشتركين</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('ledger')" id=nav-ledger>📒 <span>الحسابات</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('logs')" id=nav-logs>📜 <span>السجل</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('settings')" id=nav-settings>⚙ <span>الإعدادات</span></a>
<a href="/logout" style="margin-top:12px;background:rgba(239,68,68,0.2);color:#ff6b6b">🚪 <span>خروج</span></a>
</div>

<div class=top>
<div style="display:flex;align-items:center;gap:8px"><span onclick="toggleSb()" style='font-size:20px;cursor:pointer'>☰</span> <b style="font-size:15px">OMAIA <span style='color:#ffbe4d'>ISP</span></b></div>
</div>

<div class=main id=mn>{c}</div>

<div id=editModal><div id=editBox><div style='display:flex;justify-content:space-between;margin-bottom:8px'><b id=editModalTitle style="font-size:13px">نافذة</b><button onclick="closeEditModal()" style='background:transparent;border:0;color:#fff;cursor:pointer'>✕</button></div><div id=editBody></div></div></div>

<script>
let cur='{v}';

/* دالة فتح الروابط بشكل آمن وصحيح */
window.openLink = function(ip) {{
  if(!ip) return;
  let u = ip.trim();
  if(!u.startsWith('http://') && !u.startsWith('https://')) u = 'http://' + u;
  window.open(u, '_blank');
}};

/* دوال البحث الفوري */
window.filterTable = function(inpId, tblId) {{
  let q = document.getElementById(inpId).value.toLowerCase();
  document.querySelectorAll('#' + tblId + ' tbody tr').forEach(r => {{
    r.style.display = r.textContent.toLowerCase().includes(q) ? '' : 'none';
  }});
}};

window.filterCards = function(inpId, sel) {{
  let q = document.getElementById(inpId).value.toLowerCase();
  document.querySelectorAll(sel).forEach(c => {{
    c.style.display = c.textContent.toLowerCase().includes(q) ? '' : 'none';
  }});
}};

function toggleSb(f){{let sb=document.getElementById('sb'),ov=document.getElementById('overlay'); let o=f!==undefined?f:!sb.classList.contains('active'); sb.classList.toggle('active',o); ov.classList.toggle('show',o);}}
async function loadPage(v,force=false){{
  cur=v; toggleSb(false);
  document.querySelectorAll('.sidebar a').forEach(a=>a.classList.remove('active'));
  let n=document.getElementById('nav-'+v); if(n) n.classList.add('active');
  let mn=document.getElementById('mn'); mn.innerHTML="<div class=card>تحميل...</div>";
  try{{
    let r=await fetch('/api/page?v='+v);
    if(r.status===401){{ location.replace('/login'); return; }}
    let t=await r.text();
    if(t.includes('"ok":false') && t.includes('غير مسجل')){{ location.replace('/login'); return; }}
    mn.innerHTML=t;
    execScripts();
  }}catch(e){{ mn.innerHTML='<div class=card style="color:#ef4444">خطأ</div>'; }}
}}
function execScripts(){{document.getElementById('mn').querySelectorAll('script').forEach(o=>{{let s=document.createElement('script'); s.textContent=o.textContent; document.body.appendChild(s); o.remove();}});}}
window.closeEditModal=()=>document.getElementById('editModal').classList.remove('show');
loadPage(cur,true);
</script></body></html>"""

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)), debug=False)
