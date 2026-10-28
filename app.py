# FIXED & EXPANDED VERSION - OMAIA ISP + MIKROTIK INTEGRATION
from flask import Flask, request, redirect, session, jsonify, Response
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, html, ipaddress, secrets, subprocess, json, socket, platform, io, csv, datetime, re, threading, time, traceback
import concurrent.futures as _cf

# دعم ميكروتك الاختياري
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
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(minutes=60)
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
def esc_js(s): return json.dumps(str(s or ''))[1:-1].replace("'", r"\'")

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
        "CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,msg TEXT,time TEXT,read INTEGER DEFAULT 0)",
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

    defaults = [('card_size', '160'), ('icon_size', '44'), ('tower_bg', '#1e2433'), ('dish_bg', '#ffffff06'), ('accent_color', '#ffbe4d')]
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

# ==================== ROUTEROS API HELPERS ====================
def mikrotik_connect(host, user, pwd, port=8728):
    if not ROUTEROS_AVAILABLE:
        raise Exception("routeros_api غير مثبت في السيرفر (pip install routeros_api)")
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
        return jsonify(ok=False, msg='Host و Username مطلوبان'), 400
    
    ok = qexec("INSERT INTO mikrotik_servers(name,host,username,password,port,note) VALUES(?,?,?,?,?,?)",
               (name or host, host, user, pwd, port, note))
    if ok:
        add_log(session.get('phone'), 'إضافة ميكروتك', name or host, f"Host: {host}:{port}")
    return jsonify(ok=ok)

@app.route('/api/mikrotik/del/<int:mid>')
@login_required
@role_required_manager
def api_mikrotik_del(mid):
    srv = qone("SELECT name, host FROM mikrotik_servers WHERE id=?", (mid,))
    ok = qexec("DELETE FROM mikrotik_servers WHERE id=?", (mid,))
    if ok and srv:
        add_log(session.get('phone'), 'حذف ميكروتك', srv['name'], f"Host: {srv['host']}")
    return jsonify(ok=ok)

@app.route('/api/mikrotik/status/<int:mid>')
@login_required
def api_mikrotik_status(mid):
    srv = qone("SELECT * FROM mikrotik_servers WHERE id=?", (mid,))
    if not srv: return jsonify(ok=False, msg='السيرفر غير موجود'), 404
    
    if not ROUTEROS_AVAILABLE:
        return jsonify(ok=False, msg='مكتبة routeros_api غير مثبتة على السيرفر'), 500

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

@app.route('/api/mikrotik/active_users/<int:mid>')
@login_required
def api_mikrotik_active_users(mid):
    srv = qone("SELECT * FROM mikrotik_servers WHERE id=?", (mid,))
    if not srv: return jsonify(ok=False, msg='غير موجود'), 404

    conn = None
    try:
        conn, api = mikrotik_connect(srv['host'], srv['username'], srv['password'], srv['port'])
        users = api.get_resource('/ip/hotspot/active').get()
        return jsonify(ok=True, users=users)
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500
    finally:
        if conn:
            try: conn.disconnect()
            except Exception: pass

# ==================== ROUTES ====================
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

@app.route('/toggle_lang')
@login_required
def toggle_lang():
    cur = session.get('lang', 'ar'); session['lang'] = 'en' if cur == 'ar' else 'ar'
    add_log(session.get('phone'), 'تغيير لغة', session['lang'], 'تغيير اللغة إلى ' + session['lang'])
    return jsonify(ok=True, lang=session['lang'])

@app.route('/toggle_theme')
@login_required
def toggle_theme():
    cur = session.get('theme', 'dark'); session['theme'] = 'light' if cur == 'dark' else 'dark'
    return jsonify(ok=True, theme=session['theme'])

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
        cache_key = f"user:{uin}"
        with _clock:
            uc = _cache.get('user_cache', {}).get(cache_key)
            if uc and time.time() - uc[1] < 30: u = uc[0]
            else: u = None
        if u is None:
            u = qone("SELECT * FROM users WHERE phone=? OR username=?", (uin, uin))
            with _clock:
                if 'user_cache' not in _cache: _cache['user_cache'] = {}
                _cache['user_cache'][cache_key] = (u, time.time())
        if u and check_password_hash(u['password'], pw):
            session.clear(); session['phone'] = u['phone']; session['username'] = u.get('username') or u['phone']; session['role'] = u.get('role') or 'tech'; session.permanent = True
            add_log(u['phone'], 'دخول', uin, f'دخول المستخدم {uin}', u.get('username') or uin)
            return jsonify(ok=True)
        return jsonify(ok=False, msg='بيانات الدخول غير صحيحة'), 401
    except Exception as e: return jsonify(ok=False, msg=str(e)), 500

@app.route('/api/export/<tbl>')
@login_required
def api_export(tbl):
    add_log(session.get('phone'), 'تصدير', tbl, f'تصدير جدول {tbl}')
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

@app.route('/api/update_tower_pos', methods=['POST'])
@login_required
def update_tower_pos():
    try:
        d = request.json if request.is_json else request.form; tid = int(d.get('id')); lat = float(d.get('lat')); lng = float(d.get('lng'))
        qexec("UPDATE towers SET lat=?,lng=? WHERE id=?", (lat, lng, tid))
        add_log(session.get('phone'), 'تعديل موقع برج', f"ID {tid}", f"تعديل موقع البرج {tid} إلى {lat},{lng}")
        return jsonify(ok=True)
    except Exception as e: return jsonify(ok=False, msg=str(e)), 400

@app.route('/api/add_dish_to_tower', methods=['POST'])
@login_required
def add_dish_to_tower():
    try:
        d = request.json if request.is_json else request.form; ip = (d.get('ip') or '').strip(); name = (d.get('dish_name') or '').strip(); loc = (d.get('location') or '').strip(); tid = d.get('tower_id')
        if not is_valid_ip(ip): return jsonify(ok=False, msg='IP غير صالح'), 400
        if USE_PG: ok = qexec("INSERT INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?) ON CONFLICT (ip) DO UPDATE SET dish_name=EXCLUDED.dish_name, location=EXCLUDED.location, tower_id=EXCLUDED.tower_id", (ip, loc, name, int(tid) if tid and str(tid).isdigit() and int(tid) != 0 else None))
        else: ok = qexec("INSERT OR REPLACE INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?)", (ip, loc, name, int(tid) if tid and str(tid).isdigit() and int(tid) != 0 else None))
        if ok: add_log(session.get('phone'), 'إضافة صحن للبرج', f"{name}", f"IP: {ip} | الموقع: {loc} | برج: {tid}")
        with _clock: _cache.pop('counts', None)
        return jsonify(ok=ok)
    except Exception as e: return jsonify(ok=False, msg=str(e)), 500

@app.route('/api/dish_detail/<int:id>')
@login_required
def dish_detail(id):
    d = qone("SELECT * FROM dish_ips WHERE id=?", (id,))
    if not d: return jsonify(ok=False, msg='غير موجود'), 404
    return jsonify(ok=True, dish=d)

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
.card{{background:#1e2433ee;border:1px solid #ffffff18;padding:22px;border-radius:16px;width:92%;max-width:360px;box-shadow:0 20px 50px #0006}}
input{{width:100%;padding:12px;margin:7px 0;background:#0f1424;border:1px solid #ffffff22;color:#fff;border-radius:10px}}input:focus{{border-color:#ffbe4d;outline:none}}
.btn{{width:100%;padding:12px;border:0;border-radius:10px;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:800;cursor:pointer}} .btn:hover{{transform:scale(1.02)}}
.support{{margin-top:16px;padding-top:12px;border-top:1px dashed #ffffff15;text-align:center}}
.support a{{display:inline-flex;align-items:center;justify-content:center;width:44px;height:44px;border-radius:50%;margin:0 8px;text-decoration:none;font-size:20px;transition:.2s}}
</style></head><body>
<div class=card>
<div style='text-align:center;font-weight:900;font-size:24px;margin-bottom:12px'>OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<form id=loginForm>
<input name=userin id=userin placeholder='اسم المستخدم' required autofocus>
<input name=password id=password type=password placeholder='كلمة المرور' required>
<label style='display:flex;gap:6px;font-size:12px;margin:8px 0'><input type=checkbox id=remember style='width:14px'> حفظ البيانات</label>
<button class=btn id=loginBtn>دخول ⚡</button>
<div id=msg style='text-align:center;color:#ff6b6b;font-size:11px;min-height:14px;margin-top:8px'></div>
</form>
<div class=support>
<a href="{SUPPORT_WA_LINK}" target="_blank" style="background:#25D366;color:#fff">💬</a>
<a href="{SUPPORT_INSTA_LINK}" target="_blank" style="background:linear-gradient(45deg,#feda75,#d62976);color:#fff">📷</a>
<div style='font-size:11px;color:#94a3b8;margin-top:10px'>الدعم الفني: +{SUPPORT_WA}</div>
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
 }}catch{{m.textContent='فشل الاتصال بالشبكة'; b.textContent='دخول ⚡'; b.disabled=false;}}
}});
</script></body></html>"""

@app.route('/logout')
def lo(): session.clear(); return redirect('/login')

@app.route('/api/logout', methods=['POST'])
def api_logout(): session.clear(); return jsonify(ok=True)

@app.route('/dash')
@login_required
def dash(): v = request.args.get('v', 'home'); return layout('<div class=card>جاري التحميل...</div>', v)

@app.route('/api/page')
@login_required
def ap():
    try: return page_content(request.args.get('v', 'home'))
    except Exception as e: traceback.print_exc(); return f"<div class=card>خطأ {esc(str(e))}</div>", 500

@app.route('/api/search')
@login_required
def s():
    q = request.args.get('q', '').strip()
    if not q: return jsonify([])
    like = "%" + q + "%"; op = "ILIKE" if USE_PG else "LIKE"; res = []
    try:
        for r in qall(f"SELECT * FROM dish_ips WHERE ip {op} ? OR dish_name {op} ? OR location {op} ? LIMIT 15", (like, like, like)):
            res.append({"title": r.get('dish_name') or r['ip'], "sub": r['ip'] + " - " + (r.get('location') or ''), "page": "dishes"})
        for r in qall(f"SELECT * FROM towers WHERE name {op} ? OR area {op} ? LIMIT 10", (like, like)):
            res.append({"title": r['name'], "sub": r.get('area', '') + " | " + str(r.get('lat') or '') + "," + str(r.get('lng') or ''), "page": "towers"})
    except Exception: pass
    return jsonify(res)

@app.route('/add_dish', methods=['POST'])
@login_required
def ad():
    try:
        d = request.json if request.is_json else request.form; ip = (d.get('ip') or '').strip(); name = (d.get('dish_name') or '').strip(); loc = (d.get('location') or '').strip(); tid = d.get('tower_id')
        if not is_valid_ip(ip): return jsonify(ok=False, msg='IP غير صالح'), 400
        if USE_PG: ok = qexec("INSERT INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?) ON CONFLICT (ip) DO UPDATE SET dish_name=EXCLUDED.dish_name, location=EXCLUDED.location, tower_id=EXCLUDED.tower_id", (ip, loc, name, int(tid) if tid and str(tid).isdigit() and int(tid) != 0 else None))
        else: ok = qexec("INSERT OR REPLACE INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?)", (ip, loc, name, int(tid) if tid and str(tid).isdigit() and int(tid) != 0 else None))
        if ok: add_log(session.get('phone'), 'إضافة صحن', f"{name}", f"IP: {ip} | موقع: {loc}")
        with _clock: _cache.pop('counts', None)
        return jsonify(ok=ok)
    except Exception as e: return jsonify(ok=False, msg=str(e)), 500

@app.route('/edit_dish/<int:i>', methods=['POST'])
@login_required
def ed(i):
    if not is_manager(): return jsonify(ok=False, msg='ممنوع'), 403
    d = request.json if request.is_json else request.form
    ok = qexec("UPDATE dish_ips SET dish_name=?,ip=?,location=?,tower_id=? WHERE id=?", (d.get('dish_name', ''), d.get('ip', ''), d.get('location', ''), d.get('tower_id') or None, i))
    if ok: add_log(session.get('phone'), 'تعديل صحن', f"صحن {i}", f"ID {i}")
    return jsonify(ok=ok)

@app.route('/del_dish/<int:i>')
@login_required
def dd(i):
    if not is_manager(): return jsonify(ok=False, msg='ممنوع'), 403
    info = qone("SELECT * FROM dish_ips WHERE id=?", (i,)); ok = qexec("DELETE FROM dish_ips WHERE id=?", (i,))
    if ok:
        with _clock: _cache.pop('counts', None)
        add_log(session.get('phone'), 'حذف صحن', info.get('dish_name', '') if info else f"صحن {i}", f"{info.get('dish_name','')} {info.get('ip','')}" if info else f"ID {i}")
    return jsonify(ok=ok)

@app.route('/add_tower', methods=['POST'])
@login_required
def at():
    try:
        d = request.json if request.is_json else request.form; la = float(d.get('lat') or 35.1318); ln = float(d.get('lng') or 36.7578)
        ok = qexec("INSERT INTO towers(name,area,lat,lng,created_at) VALUES(?,?,?,?,?)", (d.get('name', 'برج'), d.get('area', ''), la, ln, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        if ok:
            add_log(session.get('phone'), 'إضافة برج', d.get('name', ''), f"منطقة: {d.get('area','')} | {la},{ln}")
            with _clock: _cache.pop('towers_list', None)
        return jsonify(ok=ok)
    except Exception as e: return jsonify(ok=False, msg=str(e)), 500

@app.route('/del_tower/<int:i>')
@login_required
def dt(i):
    if not is_manager(): return jsonify(ok=False, msg='ممنوع'), 403
    qexec("UPDATE dish_ips SET tower_id=NULL WHERE tower_id=?", (i,)); ok = qexec("DELETE FROM towers WHERE id=?", (i,))
    if ok: add_log(session.get('phone'), 'حذف برج', f"برج {i}", f"ID {i}")
    return jsonify(ok=ok)

@app.route('/edit_tower/<int:i>', methods=['POST'])
@login_required
def et(i):
    if not is_manager(): return jsonify(ok=False, msg='ممنوع'), 403
    d = request.json if request.is_json else request.form; la = float(d.get('lat') or 35.1318); ln = float(d.get('lng') or 36.7578)
    ok = qexec("UPDATE towers SET name=?,area=?,lat=?,lng=? WHERE id=?", (d.get('name', ''), d.get('area', ''), la, ln, i))
    if ok: add_log(session.get('phone'), 'تعديل برج', f"برج {i}", f"ID {i} تم تعديله")
    return jsonify(ok=ok)

@app.route('/add_sub', methods=['POST'])
@login_required
def asub():
    d = request.json if request.is_json else request.form; ok = qexec("INSERT INTO subs(name,phone,note) VALUES(?,?,?)", (d.get('name', ''), d.get('phone', ''), d.get('note', '')))
    if ok: add_log(session.get('phone'), 'إضافة مشترك', d.get('name', ''), f"هاتف: {d.get('phone','')} | {d.get('note','')}")
    return jsonify(ok=ok)

@app.route('/del_sub/<int:i>')
@login_required
def dsub(i):
    if not is_manager(): return jsonify(ok=False), 403
    ok = qexec("DELETE FROM subs WHERE id=?", (i,))
    if ok: add_log(session.get('phone'), 'حذف مشترك', f"مشترك {i}", f"ID {i}")
    return jsonify(ok=ok)

@app.route('/edit_sub/<int:i>', methods=['POST'])
@login_required
def esub(i):
    if not is_manager(): return jsonify(ok=False), 403
    d = request.json if request.is_json else request.form; ok = qexec("UPDATE subs SET name=?,phone=?,note=? WHERE id=?", (d.get('name', ''), d.get('phone', ''), d.get('note', ''), i))
    if ok: add_log(session.get('phone'), 'تعديل مشترك', f"مشترك {i}", f"ID {i} تم تعديله")
    return jsonify(ok=ok)

@app.route('/add_ledger', methods=['POST'])
@login_required
def al():
    d = request.json if request.is_json else request.form
    try: amt = float(d.get('amount') or 0)
    except Exception: amt = 0
    ok = qexec("INSERT INTO ledger(name,amount,note,currency) VALUES(?,?,?,?)", (d.get('name', ''), amt, d.get('note', ''), d.get('currency', 'USD')))
    if ok: add_log(session.get('phone'), 'إضافة حساب', d.get('name', ''), f"مبلغ: {amt} {d.get('currency','')} | {d.get('note','')}")
    return jsonify(ok=ok)

@app.route('/del_ledger/<int:i>')
@login_required
def dll(i):
    if not is_manager(): return jsonify(ok
