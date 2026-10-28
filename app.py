# -*- coding: utf-8 -*-
from flask import Flask, request, redirect, session, jsonify, Response, make_response
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

# قاموس اللغات (العربية والإنجليزية)
TR = {
    'ar': {
        'dir': 'rtl', 'toggle_code': 'en', 'lang_toggle': 'English',
        'home': 'الرئيسية', 'towers': 'الأبراج', 'dishes': 'الصحون والآيبيهات',
        'ping': 'البنج', 'network': 'الشبكة', 'subs': 'المشتركين', 'ledger': 'الحسابات',
        'users': 'المستخدمين', 'logs': 'السجل', 'settings': 'الإعدادات', 'logout': 'تسجيل خروج',
        'add': 'إضافة', 'edit': 'تعديل', 'delete': 'حذف', 'save': 'حفظ',
        'sure': 'هل أنت متأكد من الحذف؟ لا يمكن التراجع!', 'search': 'بحث...', 'mikrotik': 'ميكروتك',
        'add_tower': '+ برج جديد', 'add_dish': '+ صحن جديد', 'ip': 'الآي بي', 'name': 'الاسم',
        'manager': 'مدير', 'tech': 'فني', 'phone': 'رقم الهاتف', 'role': 'الصلاحية', 'empty': 'لا توجد بيانات'
    },
    'en': {
        'dir': 'ltr', 'toggle_code': 'ar', 'lang_toggle': 'العربية',
        'home': 'Home', 'towers': 'Towers', 'dishes': 'Dishes & IPs',
        'ping': 'Ping', 'network': 'Network', 'subs': 'Subscribers', 'ledger': 'Ledger',
        'users': 'Users', 'logs': 'Logs', 'settings': 'Settings', 'logout': 'Logout',
        'add': 'Add', 'edit': 'Edit', 'delete': 'Delete', 'save': 'Save',
        'sure': 'Are you sure you want to delete?', 'search': 'Search...', 'mikrotik': 'MikroTik',
        'add_tower': '+ New Tower', 'add_dish': '+ New Dish', 'ip': 'IP Address', 'name': 'Name',
        'manager': 'Manager', 'tech': 'Tech', 'phone': 'Phone', 'role': 'Role', 'empty': 'No data found'
    }
}

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
            for k in ['counts', 'logs']: _cache.pop(k, None)
    except Exception: pass

def get_counts():
    with _clock:
        c = _cache.get('counts')
        if c and time.time() - c[1] < 60: return c[0]
    try:
        row = qone("SELECT (SELECT COUNT(*) FROM subs) as ns, (SELECT COUNT(*) FROM dish_ips) as nd, (SELECT COUNT(*) FROM towers) as nt, (SELECT COUNT(*) FROM ledger) as nl, (SELECT COUNT(*) FROM mikrotik_servers) as nm")
        d = (row.get('ns', 0), row.get('nd', 0), row.get('nt', 0), row.get('nl', 0), row.get('nm', 0)) if row else (0, 0, 0, 0, 0)
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
    
    for al in ["ALTER TABLE dish_ips ADD COLUMN tower_id INTEGER", "ALTER TABLE towers ADD COLUMN created_at TEXT", "ALTER TABLE logs ADD COLUMN username TEXT", "ALTER TABLE logs ADD COLUMN target TEXT"]:
        try: qexec(al)
        except Exception: pass

    # إضافة الحسابات الأساسية في حال عدم وجودها
    if not qone("SELECT * FROM users WHERE phone=?", ('admin',)):
        qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",
              ('admin', generate_password_hash('admin2024', method='pbkdf2:sha256:150000'), 'manager', 'مدير النظام'))
              
    if not qone("SELECT * FROM users WHERE phone=?", ('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",
              ('05344851045', generate_password_hash('admin2024', method='pbkdf2:sha256:150000'), 'manager', 'المدير الأساسي'))

    # أمر إجباري لتحديث وإصلاح كلمات المرور للحسابين أعلاه (لحل مشكلة عدم القدرة على تسجيل الدخول)
    qexec("UPDATE users SET password=? WHERE phone IN ('admin', '05344851045')", 
          (generate_password_hash('admin2024', method='pbkdf2:sha256:150000'),))

    if not qone("SELECT * FROM system_config WHERE key=?", ('card_size',)):
        qexec("INSERT INTO system_config(key,value) VALUES(?,?)", ('card_size', '120'))
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

def is_valid_ip(h):
    h = (h or '').strip()
    if not h: return False
    try:
        ipaddress.ip_address(h)
        return True
    except Exception:
        if len(h) >= 3 and '.' in h and ' ' not in h and re.match(r'^[a-zA-Z0-9.-]+\.[a-zA-Z0-9.-]+$', h):
            return True
        return False

@app.after_request
def after(r):
    r.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    r.headers['Pragma'] = 'no-cache'
    return r

@app.route('/api/set_lang/<lang>')
def set_lang(lang):
    if lang not in ['ar', 'en']: lang = 'ar'
    res = make_response(redirect('/dash'))
    res.set_cookie('lang', lang, max_age=31536000)
    return res

@app.route('/api/mikrotik/list')
@login_required
def api_mikrotik_list():
    return jsonify(ok=True, servers=qall("SELECT id, name, host, username, port, note FROM mikrotik_servers ORDER BY id DESC"))

@app.route('/api/mikrotik/add', methods=['POST'])
@login_required
@role_required_manager
def api_mikrotik_add():
    d = request.json
    name, host, user, pwd, port = d.get('name','').strip(), d.get('host','').strip(), d.get('username','').strip(), d.get('password','').strip(), int(d.get('port') or 8728)
    if not host or not user: return jsonify(ok=False, msg='بيانات ناقصة'), 400
    ok = qexec("INSERT INTO mikrotik_servers(name,host,username,password,port) VALUES(?,?,?,?,?)", (name or host, host, user, pwd, port))
    if ok: add_log(session.get('phone'), 'إضافة ميكروتك', name or host, f"{host}:{port}")
    return jsonify(ok=ok)

@app.route('/api/mikrotik/del/<int:mid>')
@login_required
@role_required_manager
def api_mikrotik_del(mid):
    srv = qone("SELECT name, host FROM mikrotik_servers WHERE id=?", (mid,))
    ok = qexec("DELETE FROM mikrotik_servers WHERE id=?", (mid,))
    if ok and srv: add_log(session.get('phone'), 'حذف ميكروتك', srv['name'])
    return jsonify(ok=ok)

@app.route('/api/mikrotik/status/<int:mid>')
@login_required
def api_mikrotik_status(mid):
    srv = qone("SELECT * FROM mikrotik_servers WHERE id=?", (mid,))
    if not srv: return jsonify(ok=False, msg='غير موجود'), 404
    if not ROUTEROS_AVAILABLE: return jsonify(ok=False, msg='مكتبة routeros_api غير متوفرة'), 500
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
    except Exception as e: return jsonify(ok=False, msg=f"تعذر الاتصال: {str(e)}"), 500
    finally:
        if conn:
            try: conn.disconnect()
            except Exception: pass

@app.route('/api/ping')
@login_required
def api_ping():
    ip = request.args.get('ip', '').strip()
    if not is_valid_ip(ip): return jsonify(ok=False, out='IP Invalid')
    def try_port(p):
        s = None
        try:
            s = socket.socket(); s.settimeout(0.3)
            if s.connect_ex((ip, p)) == 0: return p
        except Exception: pass
        finally:
            if s:
                try: s.close()
                except Exception: pass
        return None
    try:
        with _cf.ThreadPoolExecutor(max_workers=3) as ex:
            futs = [ex.submit(try_port, p) for p in [80, 443, 8080, 8291, 22]]
            for f in _cf.as_completed(futs, timeout=1.0):
                if f.result(): return jsonify(ok=True, out=f'{ip}:{f.result()} ✓')
    except Exception: pass
    return jsonify(ok=False, out=f'{ip} لا يرد / Timeout')

@app.route('/api/stats')
@login_required
def api_stats():
    ns, nd, nt, nl, nm = get_counts()
    logs = qall("SELECT * FROM logs ORDER BY id DESC LIMIT 10")
    return jsonify(ok=True, stats=dict(subs=ns, dishes=nd, towers=nt, ledger=nl, mikrotik=nm), logs=logs)

@app.route('/api/set_config', methods=['POST'])
@login_required
@role_required_manager
def set_config():
    d = request.json; k = (d.get('key') or '').strip(); v = (d.get('value') or '').strip()
    if not k: return jsonify(ok=False), 400
    if USE_PG: qexec("INSERT INTO system_config(key,value) VALUES(?,?) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value", (k, v))
    else: qexec("INSERT OR REPLACE INTO system_config(key,value) VALUES(?,?)", (k, v))
    return jsonify(ok=True)

@app.route('/api/login_public', methods=['POST'])
def api_login_public():
    try:
        uin = request.form.get('userin', '').strip(); pw = request.form.get('password', '')
        rem = request.form.get('remember') == 'on'
        u = qone("SELECT * FROM users WHERE phone=? OR username=?", (uin, uin))
        if u and check_password_hash(u['password'], pw):
            session.clear()
            session['phone'] = u['phone']
            session['username'] = u.get('username') or u['phone']
            session['role'] = u.get('role') or 'tech'
            if rem: session.permanent = True
            add_log(u['phone'], 'تسجيل دخول', uin, f'{uin}', u.get('username') or uin)
            return jsonify(ok=True)
        return jsonify(ok=False, msg='بيانات الدخول غير صحيحة'), 401
    except Exception as e: return jsonify(ok=False, msg=str(e)), 500

@app.route('/api/clear_logs', methods=['POST'])
@login_required
@role_required_manager
def clear_logs():
    qexec("DELETE FROM logs")
    add_log(session.get('phone'), 'مسح السجل', 'المدير مسح كافة السجلات')
    return jsonify(ok=True)

@app.route('/add_tower', methods=['POST'])
@login_required
def at():
    d = request.json
    ok = qexec("INSERT INTO towers(name,area,lat,lng,created_at) VALUES(?,?,?,?,?)", (d.get('name', 'برج'), d.get('area', ''), 0, 0, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    if ok: add_log(session.get('phone'), 'إضافة برج', d.get('name', ''))
    return jsonify(ok=ok)

@app.route('/edit_tower/<int:id>', methods=['POST'])
@login_required
def edit_tower(id):
    d = request.json
    ok = qexec("UPDATE towers SET name=?, area=? WHERE id=?", (d.get('name'), d.get('area'), id))
    if ok: add_log(session.get('phone'), 'تعديل برج', d.get('name', ''))
    return jsonify(ok=ok)

@app.route('/del_tower/<int:i>', methods=['POST'])
@login_required
def dt(i):
    if not is_manager(): return jsonify(ok=False), 403
    qexec("UPDATE dish_ips SET tower_id=NULL WHERE tower_id=?", (i,))
    ok = qexec("DELETE FROM towers WHERE id=?", (i,))
    if ok: add_log(session.get('phone'), 'حذف برج', f"ID: {i}")
    return jsonify(ok=ok)

@app.route('/api/add_dish_to_tower', methods=['POST'])
@login_required
def add_dish_to_tower():
    d = request.json; ip, name, loc, tid = (d.get('ip') or '').strip(), (d.get('dish_name') or '').strip(), (d.get('location') or '').strip(), d.get('tower_id')
    if not is_valid_ip(ip): return jsonify(ok=False, msg='IP Invalid'), 400
    if USE_PG: ok = qexec("INSERT INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?) ON CONFLICT (ip) DO UPDATE SET dish_name=EXCLUDED.dish_name, location=EXCLUDED.location, tower_id=EXCLUDED.tower_id", (ip, loc, name, int(tid) if tid and str(tid).isdigit() and int(tid) != 0 else None))
    else: ok = qexec("INSERT OR REPLACE INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?)", (ip, loc, name, int(tid) if tid and str(tid).isdigit() and int(tid) != 0 else None))
    if ok: add_log(session.get('phone'), 'إضافة صحن', f"{name}", f"IP: {ip}")
    return jsonify(ok=ok)

@app.route('/api/edit_dish/<int:id>', methods=['POST'])
@login_required
def edit_dish(id):
    d = request.json; ip, name, loc, tid = (d.get('ip') or '').strip(), (d.get('dish_name') or '').strip(), (d.get('location') or '').strip(), d.get('tower_id')
    ok = qexec("UPDATE dish_ips SET ip=?, dish_name=?, location=?, tower_id=? WHERE id=?", (ip, name, loc, int(tid) if tid and str(tid).isdigit() and int(tid)!=0 else None, id))
    if ok: add_log(session.get('phone'), 'تعديل صحن', f"{name}", f"IP: {ip}")
    return jsonify(ok=ok)

@app.route('/del_dish/<int:i>', methods=['POST'])
@login_required
def dd(i):
    if not is_manager(): return jsonify(ok=False), 403
    ok = qexec("DELETE FROM dish_ips WHERE id=?", (i,))
    if ok: add_log(session.get('phone'), 'حذف صحن', f"ID: {i}")
    return jsonify(ok=ok)

@app.route('/add_sub', methods=['POST'])
@login_required
def asub():
    d = request.form; ok = qexec("INSERT INTO subs(name,phone,note) VALUES(?,?,?)", (d.get('name', ''), d.get('phone', ''), d.get('note', '')))
    if ok: add_log(session.get('phone'), 'إضافة مشترك', d.get('name', ''))
    return jsonify(ok=ok)

@app.route('/del_sub/<int:i>', methods=['POST'])
@login_required
def dsub(i):
    if not is_manager(): return jsonify(ok=False), 403
    ok = qexec("DELETE FROM subs WHERE id=?", (i,))
    if ok: add_log(session.get('phone'), 'حذف مشترك', f"ID: {i}")
    return jsonify(ok=ok)

@app.route('/add_ledger', methods=['POST'])
@login_required
def al():
    d = request.form
    try: amt = float(d.get('amount') or 0)
    except Exception: amt = 0
    ok = qexec("INSERT INTO ledger(name,amount,note,currency) VALUES(?,?,?,?)", (d.get('name', ''), amt, d.get('note', ''), d.get('currency', 'USD')))
    if ok: add_log(session.get('phone'), 'إضافة حساب', d.get('name', ''))
    return jsonify(ok=ok)

@app.route('/del_ledger/<int:i>', methods=['POST'])
@login_required
def dll(i):
    if not is_manager(): return jsonify(ok=False), 403
    ok = qexec("DELETE FROM ledger WHERE id=?", (i,))
    if ok: add_log(session.get('phone'), 'حذف حساب', f"ID: {i}")
    return jsonify(ok=ok)

@app.route('/api/users/add', methods=['POST'])
@login_required
@role_required_manager
def add_user():
    d = request.json
    p, pw, u, r = d.get('phone','').strip(), d.get('password','').strip(), d.get('username','').strip(), d.get('role','tech')
    if not p or not pw: return jsonify(ok=False, msg="البيانات ناقصة")
    ok = qexec("INSERT OR REPLACE INTO users(phone,password,role,username) VALUES(?,?,?,?)", (p, generate_password_hash(pw, method='pbkdf2:sha256:150000'), r, u))
    if ok: add_log(session.get('phone'), 'إضافة مستخدم', u, f"صلاحية: {r}")
    return jsonify(ok=ok)

@app.route('/api/users/edit', methods=['POST'])
@login_required
@role_required_manager
def edit_user():
    d = request.json
    p, pw, r = d.get('phone','').strip(), d.get('password','').strip(), d.get('role','tech')
    if pw: qexec("UPDATE users SET password=?, role=? WHERE phone=?", (generate_password_hash(pw, method='pbkdf2:sha256:150000'), r, p))
    else: qexec("UPDATE users SET role=? WHERE phone=?", (r, p))
    add_log(session.get('phone'), 'تعديل مستخدم', p)
    return jsonify(ok=True)

@app.route('/api/users/del/<phone>', methods=['POST'])
@login_required
@role_required_manager
def del_user(phone):
    if phone == 'admin' or phone == '05344851045': return jsonify(ok=False, msg="لا يمكن حذف المدير الأساسي")
    ok = qexec("DELETE FROM users WHERE phone=?", (phone,))
    if ok: add_log(session.get('phone'), 'حذف مستخدم', phone)
    return jsonify(ok=ok)

@app.route('/change_pass', methods=['POST'])
@login_required
def cp():
    d = request.form; np = (d.get('newpass') or '').strip()
    if not np: return jsonify(ok=False, msg='فارغ'), 400
    ok = qexec("UPDATE users SET password=? WHERE phone=?", (generate_password_hash(np, method='pbkdf2:sha256:150000'), session.get('phone')))
    add_log(session.get('phone'), 'تغيير كلمة المرور الشخصية', session.get('phone'))
    return jsonify(ok=ok)

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
    l = request.cookies.get('lang', 'ar'); tr = TR.get(l, TR['ar'])
    return f"""<html dir="{tr['dir']}"><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>OMAIA ISP</title>
<style>
*{{box-sizing:border-box;font-family:system-ui}}body{{margin:0;min-height:100vh;background:radial-gradient(120% 120% at 10% 10%,#1a2344,#0a0e2a 60%);display:flex;align-items:center;justify-content:center;color:#fff}}
.card{{background:rgba(20, 25, 45, 0.6);backdrop-filter:blur(20px);border:1px solid rgba(255,255,255,0.15);padding:24px;border-radius:16px;width:92%;max-width:350px;box-shadow:0 10px 30px rgba(0,0,0,0.5)}}
input{{width:100%;padding:12px;margin:8px 0;background:#0f1424;border:1px solid #ffffff22;color:#fff;border-radius:10px}}
.btn{{width:100%;padding:12px;border:0;border-radius:10px;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:800;cursor:pointer;margin-top:12px}}
</style></head><body>
<div class=card>
<div style='text-align:center;font-weight:900;font-size:26px;margin-bottom:16px'>OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<form id=loginForm>
<input name=userin placeholder='{tr['name']} / {tr['phone']}' required autofocus>
<input name=password type=password placeholder='***' required>
<label style="display:flex;align-items:center;gap:6px;font-size:13px;margin-top:10px;cursor:pointer">
  <input type="checkbox" name="remember" checked style="width:auto;margin:0"> حفظ الدخول (30 يوم)
</label>
<button class=btn id=loginBtn>دخول Login</button>
<div id=msg style='text-align:center;color:#ff6b6b;font-size:12px;margin-top:8px'></div>
</form>
</div>
<script>
document.getElementById('loginForm').addEventListener('submit', async e => {{
  e.preventDefault();
  let b = document.getElementById('loginBtn'), m = document.getElementById('msg');
  b.disabled = true;
  try {{
    let res = await fetch('/api/login_public', {{ method: 'POST', body: new FormData(e.target) }});
    let j = await res.json();
    if(j.ok) location.replace('/dash?v=home');
    else {{ m.textContent = 'بيانات خاطئة'; b.disabled = false; }}
  }} catch {{ m.textContent = 'خطأ اتصال'; b.disabled = false; }}
}});
</script></body></html>"""

@app.route('/logout')
def lo(): session.clear(); return redirect('/login')

@app.route('/dash')
@login_required
def dash(): v = request.args.get('v', 'home'); return layout('<div class=card>...</div>', v)

@app.route('/api/page')
@login_required
def ap():
    try: return page_content(request.args.get('v', 'home'))
    except Exception as e: traceback.print_exc(); return f"<div class=card>Error: {esc(str(e))}</div>", 500

def page_content(v):
    l = request.cookies.get('lang', 'ar'); tr = TR.get(l, TR['ar'])
    if v == 'home':
        return f"""
<div style="max-width:1100px;margin:0 auto">
<div class=grid-small id=statsGrid>
<div class="card stat" onclick="loadPage('subs')"><div class=ico>👥</div><h4>{tr['subs']}</h4><h3 id=stat-subs>...</h3></div>
<div class="card stat" onclick="loadPage('dishes')"><div class=ico>📡</div><h4>{tr['dishes']}</h4><h3 id=stat-dishes>...</h3></div>
<div class="card stat" onclick="loadPage('towers')"><div class=ico>🗼</div><h4>{tr['towers']}</h4><h3 id=stat-towers>...</h3></div>
<div class="card stat" onclick="loadPage('ledger')"><div class=ico>📒</div><h4>{tr['ledger']}</h4><h3 id=stat-ledger>...</h3></div>
<div class="card stat" onclick="loadPage('mikrotik')"><div class=ico>🖧</div><h4>{tr['mikrotik']}</h4><h3 id=stat-mikrotik>...</h3></div>
</div>
<div class=card style="margin-top:8px"><div style="display:flex;justify-content:space-between"><b>📜 {tr['logs']}</b><button class=btn-gold onclick="loadPage('logs')">{tr['search']}</button></div>
<div id=logsPreview style="margin-top:6px"></div>
</div>
</div>
<script>
(async()=>{{
 try{{
  let r=await fetch('/api/stats'); if(r.status===401) return location.replace('/login');
  let j=await r.json();
  if(j.ok){{
   document.getElementById('stat-subs').textContent=j.stats.subs;
   document.getElementById('stat-dishes').textContent=j.stats.dishes;
   document.getElementById('stat-towers').textContent=j.stats.towers;
   document.getElementById('stat-ledger').textContent=j.stats.ledger;
   if(document.getElementById('stat-mikrotik')) document.getElementById('stat-mikrotik').textContent=j.stats.mikrotik || 0;
   let lh=j.logs.map(l=>`<tr><td><small>${{l.time||''}}</small></td><td><span class=badge>${{l.action||''}}</span></td><td>${{l.username||l.user_phone||''}}</td></tr>`).join('') || '';
   document.getElementById('logsPreview').innerHTML='<table style="width:100%"><tbody>'+lh+'</tbody></table>';
  }}
 }}catch(e){{}}
}})();
</script>"""

    if v == 'mikrotik':
        servers = qall("SELECT * FROM mikrotik_servers ORDER BY id DESC")
        cards = "".join([f"""<div class="card" id="mk-server-{s['id']}"><div style="display:flex;justify-content:space-between;align-items:center"><div><b style="font-size:14px">🖧 {esc(s['name'])}</b><div style="font-size:11px;color:#94a3b8;margin-top:2px">{esc(s['host'])}:{s['port']}</div></div><div style="display:flex;gap:6px"><button class="glass-btn view" onclick="fetchMikrotikStatus({s['id']})">⚡</button><button class="glass-btn del" onclick="delMk(event, {s['id']})">🗑</button></div></div><div id="mk-details-{s['id']}" style="margin-top:8px;padding:8px;background:#0006;border-radius:8px;font-size:12px;display:none"></div></div>""" for s in servers])
        return f"""
<div style="max-width:1100px;margin:0 auto">
  <div class=card style="display:flex;justify-content:space-between;align-items:center"><b>{tr['mikrotik']}</b><button class=btn-gold onclick="openAddMikrotikModal()">+ {tr['add']}</button></div>
  <div style="display:flex;flex-direction:column;gap:8px;margin-top:8px">{cards or f"<div class=card>{tr['empty']}</div>"}</div>
</div>
<script>
window.openAddMikrotikModal=function(){{
  document.getElementById("editBody").innerHTML=`<div style="display:flex;flex-direction:column;gap:6px"><input id="mk_name" placeholder="Name"><input id="mk_host" placeholder="IP"><input id="mk_user" placeholder="User"><input id="mk_pwd" type="password" placeholder="Pass"><input id="mk_port" type="number" value="8728"><button class="btn-gold" onclick="saveNewMikrotik()" style="width:100%;margin-top:4px">{tr['save']}</button></div>`;
  document.getElementById("editModalTitle").textContent="{tr['add']}"; document.getElementById("editModal").classList.add("show");
}};
window.saveNewMikrotik=async function(){{
  let d={{name:document.getElementById("mk_name").value,host:document.getElementById("mk_host").value,username:document.getElementById("mk_user").value,password:document.getElementById("mk_pwd").value,port:document.getElementById("mk_port").value}};
  if(!d.host||!d.username) return;
  let r=await fetch('/api/mikrotik/add',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}});
  if((await r.json()).ok){{closeEditModal();loadPage('mikrotik',true);}}
}};
window.delMk=async function(e, id){{
  if(!confirm(MSG_SURE)) return;
  let r=await fetch('/api/mikrotik/del/'+id);
  if((await r.json()).ok) e.target.closest('.card').remove();
}};
window.fetchMikrotikStatus=async function(id){{
  let box=document.getElementById("mk-details-"+id); box.style.display="block"; box.innerHTML="⏳ ...";
  try{{
    let r=await fetch('/api/mikrotik/status/'+id); let j=await r.json();
    if(j.ok){{
      let d=j.data; box.innerHTML=`<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px"><div><b>ID:</b> ${{d.identity}}</div><div><b>CPU:</b> ${{d.cpu}}%</div><div><b>Uptime:</b> ${{d.uptime}}</div><div><b>Hotspot:</b> <span class="badge">${{d.hotspot_active}}</span></div></div>`;
    }}else box.innerHTML='<span style="color:#ef4444">Error</span>';
  }}catch(e){{box.innerHTML='<span style="color:#ef4444">Error</span>';}}
}};
</script>"""

    if v == 'towers':
        rs = qall("SELECT t.id,t.name,t.area, COUNT(d.id) as cnt FROM towers t LEFT JOIN dish_ips d ON d.tower_id=t.id GROUP BY t.id,t.name,t.area ORDER BY t.name ASC")
        cards = "".join([f"""
<div class="card tower-card" id="tower-{t['id']}">
  <div style="display:flex;justify-content:space-between;align-items:center;cursor:pointer" onclick="openTowerDishes({t['id']})">
    <div><b style="font-size:14px;color:#38bdf8">🗼 {esc(t['name'])}</b><div style="font-size:11px;color:#94a3b8;margin-top:4px">📍 {esc(t.get('area') or '...')}</div></div>
    <span class=badge style="padding:4px 8px;font-size:11px">{t['cnt']}</span>
  </div>
  <div style="display:flex;gap:6px;margin-top:12px;border-top:1px solid #ffffff11;padding-top:8px">
    <button class="glass-btn edit" onclick="openEditTower({t['id']}, '{esc(t['name'])}', '{esc(t.get('area') or '')}')">✏️ {tr['edit']}</button>
    <button class="glass-btn del" onclick="delTower(event, {t['id']})">🗑 {tr['delete']}</button>
  </div>
</div>""" for t in rs])
        return f"""
<div style="max-width:1100px;margin:0 auto">
  <div class=card style="display:flex;justify-content:space-between;align-items:center"><b>{tr['towers']}</b><button class=btn-gold onclick="openNewTower()">{tr['add_tower']}</button></div>
  <input id="searchTowers" onkeyup="filterCards('searchTowers', '.tower-card')" placeholder="{tr['search']}" style="margin-top:6px;width:100%">
  <div class=grid-small id=towersGrid style="margin-top:8px">{cards or f"<div class=card>{tr['empty']}</div>"}</div>
</div>
<script>
window.openTowerDishes = async function(tid) {{
  await loadPage('dishes');
  setTimeout(() => {{
    let acc = document.getElementById('tower-body-' + tid);
    if(acc && acc.style.display === 'none') toggleAccordionLazy(tid);
  }}, 200);
}};
window.openNewTower=function(){{
  document.getElementById("editBody").innerHTML=`<input id=nt_name placeholder="Name"><input id=nt_area placeholder="Area"><button class=btn-gold onclick="saveTower(0)" style="width:100%;margin-top:6px">{tr['save']}</button>`;
  document.getElementById("editModalTitle").textContent="{tr['add_tower']}"; document.getElementById("editModal").classList.add("show");
}};
window.openEditTower=function(id, name, area){{
  document.getElementById("editBody").innerHTML=`<input id=nt_name value="${{name}}"><input id=nt_area value="${{area}}"><button class=btn-gold onclick="saveTower(${{id}})" style="width:100%;margin-top:6px">{tr['save']}</button>`;
  document.getElementById("editModalTitle").textContent="{tr['edit']}"; document.getElementById("editModal").classList.add("show");
}};
window.saveTower=async function(id){{
  let d={{name:document.getElementById("nt_name").value, area:document.getElementById("nt_area").value}};
  if(!d.name) return;
  let url = id === 0 ? '/add_tower' : '/edit_tower/'+id;
  let r=await fetch(url, {{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify(d)}});
  if((await r.json()).ok) {{ closeEditModal(); loadPage('towers',true); }}
}};
window.delTower=async function(e, id){{
  if(!confirm(MSG_SURE)) return;
  let r=await fetch('/del_tower/'+id, {{method:'POST'}});
  if((await r.json()).ok) e.target.closest('.card').remove();
}};
</script>"""

    if v == 'dishes':
        towers = qall("SELECT t.id, t.name, t.area, (SELECT COUNT(*) FROM dish_ips WHERE tower_id=t.id) as cnt FROM towers t ORDER BY t.name ASC")
        no_cnt = (qone("SELECT COUNT(*) as c FROM dish_ips WHERE tower_id IS NULL") or {}).get('c', 0)
        accordion_html = "".join([f"""<div class="card tower-accordion" id="tower-acc-{t['id']}"><div onclick="toggleAccordionLazy({t['id']})" style="display:flex;justify-content:space-between;align-items:center;cursor:pointer"><div><b style="font-size:14px;color:#38bdf8">🗼 {esc(t['name'])}</b> <span class="badge">{t['cnt']}</span></div><div style="font-size:18px">▼</div></div><div id="tower-body-{t['id']}" style="display:none;margin-top:10px;padding-top:10px;border-top:1px dashed #ffffff22"><div id="tower-content-{t['id']}"></div></div></div>""" for t in towers])
        accordion_html += f"""<div class="card tower-accordion" id="tower-acc-0" style="border:1px solid rgba(239,68,68,0.4)"><div onclick="toggleAccordionLazy(0)" style="display:flex;justify-content:space-between;align-items:center;cursor:pointer"><div><b style="font-size:14px;color:#ef4444">بدون برج / Unassigned</b> <span class="badge" style="background:#ef4444">{no_cnt}</span></div><div style="font-size:18px">▼</div></div><div id="tower-body-0" style="display:none;margin-top:10px;padding-top:10px;border-top:1px dashed #ffffff22"><div id="tower-content-0"></div></div></div>"""
        
        t_opts = "<option value='0'>---</option>" + "".join([f"<option value='{t['id']}'>{esc(t['name'])}</option>" for t in towers])
        
        return f"""
<div style="max-width:1100px;margin:0 auto">
  <div class=card style="display:flex;justify-content:space-between;align-items:center"><b>{tr['dishes']}</b><button class=btn-gold onclick="openDishModal(0,0,'','','')">{tr['add_dish']}</button></div>
  <input id="searchDishes" onkeyup="filterCards('searchDishes', '.tower-accordion')" placeholder="{tr['search']}" style="margin-top:6px;width:100%">
  <div style="display:flex;flex-direction:column;gap:8px;margin-top:10px">{accordion_html}</div>
</div>
<script>
const towerOpts = `{t_opts}`;
window.toggleAccordionLazy=async function(tid){{
  let b=document.getElementById('tower-body-'+tid);
  if(b.style.display==='none'){{
    b.style.display='block'; let c=document.getElementById('tower-content-'+tid); c.innerHTML='⏳ ...';
    try{{
      let r=await fetch('/api/tower_detail/'+tid); let j=await r.json();
      if(j.ok){{
        c.innerHTML=(j.dishes||[]).map(d=>`
          <div class="dish-row" style="display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid #ffffff11">
            <div><b style="font-size:13px">${{d.dish_name||'--'}}</b><br><span class="ip" style="cursor:pointer;font-size:13px;padding:4px 8px;margin-top:4px;display:inline-block" onclick="openLink('${{d.ip}}')">${{d.ip}}</span> <small style="color:#94a3b8">${{d.location||''}}</small></div>
            <div style="display:flex;gap:6px">
              <button class="glass-btn edit" onclick="openDishModal(${{d.id}}, ${{tid}}, '${{d.dish_name||''}}', '${{d.ip||''}}', '${{d.location||''}}')">✏️</button>
              <button class="glass-btn del" onclick="delDish(event, ${{d.id}})">🗑</button>
            </div>
          </div>
        `).join('') || '<div style="color:#888;font-size:12px;text-align:center;padding:10px">فارغ Empty</div>';
        c.innerHTML += `<button class="btn-gold" onclick="openDishModal(0, ${{tid}},'','','')" style="width:100%;margin-top:12px">{tr['add_dish']}</button>`;
      }}
    }}catch(e){{c.innerHTML='Error';}}
  }}else b.style.display='none';
}};
window.openDishModal=function(id, tid, name, ip, loc){{
  document.getElementById("editBody").innerHTML=`
    <input id="dish_name" placeholder="{tr['name']}" value="${{name}}">
    <input id="dish_ip" placeholder="IP" value="${{ip}}">
    <input id="dish_loc" placeholder="Location/Note" value="${{loc}}">
    <select id="dish_tid" style="font-weight:bold">${{towerOpts}}</select>
    <button class="btn-gold" onclick="saveDish(${{id}})" style="width:100%;margin-top:8px">{tr['save']}</button>
  `;
  document.getElementById("dish_tid").value = tid;
  document.getElementById("editModalTitle").textContent = id===0 ? "{tr['add']}" : "{tr['edit']}";
  document.getElementById("editModal").classList.add("show");
}};
window.saveDish=async function(id){{
  let tid = document.getElementById("dish_tid").value;
  let d={{dish_name:document.getElementById("dish_name").value, ip:document.getElementById("dish_ip").value, location:document.getElementById("dish_loc").value, tower_id:tid}};
  if(!d.ip) return alert("IP Required");
  let url = id === 0 ? '/api/add_dish_to_tower' : '/api/edit_dish/'+id;
  let r=await fetch(url, {{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}});
  if((await r.json()).ok){{
     closeEditModal(); 
     let cBox = document.getElementById('tower-content-' + tid);
     if (cBox) {{
         document.getElementById('tower-body-' + tid).style.display = 'none';
         toggleAccordionLazy(tid);
     }} else loadPage('dishes',true);
  }}
}};
window.delDish=async function(e, id){{
  if(!confirm(MSG_SURE)) return;
  let r=await fetch('/del_dish/'+id, {{method:'POST'}});
  if((await r.json()).ok) e.target.closest('.dish-row').remove();
}};
</script>"""

    if v == 'ping':
        return f"""
<div class=card><b>{tr['ping']}</b><div style="display:flex;gap:8px;margin-top:12px"><input id="pingIp" placeholder="IP" style="flex:1;margin:0"><button class="btn-gold" style="margin:0" onclick="runPing()">Ping</button></div><div id="pingRes" style="margin-top:12px;padding:12px;background:#000a;border-radius:8px;font-family:monospace;min-height:40px;color:#34d399;font-size:13px;text-align:center">Ready</div></div>
<script>
window.runPing=async function(){{
  let ip=document.getElementById('pingIp').value.trim(); if(!ip)return;
  let o=document.getElementById('pingRes'); o.textContent='...';
  try{{ let r=await fetch('/api/ping?ip='+encodeURIComponent(ip)); o.textContent=(await r.json()).out; }}catch(e){{o.textContent='Error';}}
}};
</script>"""

    if v == 'network':
        dishes = qall("SELECT id, dish_name, ip, location FROM dish_ips ORDER BY dish_name ASC LIMIT 100")
        cards = "".join([f"""<div class="card net-card" id="net-card-{d['id']}"><div style="display:flex;justify-content:space-between"><b style="font-size:13px">{esc(d.get('dish_name') or '--')}</b></div><div style="margin-top:8px;display:flex;justify-content:space-between;align-items:center"><span class="ip" style="cursor:pointer;font-size:12px" onclick="openLink('{esc(d.get('ip') or '')}')">{esc(d.get('ip') or '')}</span><span class="net-status badge" id="net-status-{d['id']}" style="background:#ffffff22;color:#fff">-</span></div></div>""" for d in dishes])
        return f"""
<div class=card style="display:flex;justify-content:space-between;align-items:center"><b>{tr['network']}</b><button class=btn-gold onclick="pingAllNetwork()">Ping All</button></div>
<input id="searchNetwork" onkeyup="filterCards('searchNetwork', '.net-card')" placeholder="{tr['search']}" style="margin-top:6px;width:100%">
<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(var(--cs, 120px),1fr));gap:8px;margin-top:10px">{cards or f"<div class=card>{tr['empty']}</div>"}</div>
<script>
window.pingAllNetwork=async function(){{
  let cards=document.querySelectorAll(".net-card");
  for(let c of cards){{
    let id=c.id.replace('net-card-',''); let ipEl=c.querySelector('.ip'); let stEl=document.getElementById('net-status-'+id);
    if(ipEl && stEl){{
      stEl.textContent='...';
      fetch('/api/ping?ip='+encodeURIComponent(ipEl.textContent)).then(r=>r.json()).then(j=>{{
          stEl.textContent=j.ok ? 'Online' : 'Offline';
          stEl.style.background=j.ok ? '#34d399' : '#ef4444';
          stEl.style.color='#000';
      }}).catch(()=>{{stEl.textContent='Error';}});
    }}
    await new Promise(r=>setTimeout(r, 100));
  }}
}};
</script>"""

    if v == 'subs':
        rs = qall("SELECT * FROM subs ORDER BY name ASC LIMIT 100")
        rows = "".join([f"<tr class='sub-row'><td><b>{esc(r.get('name') or '')}</b></td><td><span class=ip>{esc(r.get('phone') or '')}</span></td><td>{esc(r.get('note') or '')}</td><td><button class=\"glass-btn del\" onclick=\"delSub(event, {r.get('id')})\">🗑</button></td></tr>" for r in rs])
        return f"""
<div class=card style="display:flex;justify-content:space-between;align-items:center"><b>{tr['subs']}</b><button class=btn-gold onclick="document.getElementById('fSub').style.display='flex'">+ {tr['add']}</button></div>
<form id=fSub style="display:none;gap:6px;margin-top:8px"><input name=name placeholder="{tr['name']}" required><input name=phone placeholder="{tr['phone']}" required><input name=note placeholder="Note"><button class=btn-gold>{tr['save']}</button></form>
<input id="searchSubs" onkeyup="filterTable('searchSubs', 'subsTable')" placeholder="{tr['search']}" style="margin-top:6px;width:100%">
<table id="subsTable" style="width:100%;margin-top:10px"><thead><tr><th>{tr['name']}</th><th>{tr['phone']}</th><th>Note</th><th></th></tr></thead><tbody>{rows or '<tr><td colspan=4>Empty</td></tr>'}</tbody></table>
<script>
document.getElementById('fSub').addEventListener('submit',async e=>{{e.preventDefault();let r=await fetch('/add_sub',{{method:'POST',body:new FormData(e.target)}});if((await r.json()).ok)loadPage('subs',true);}});
window.delSub=async function(e, id){{if(!confirm(MSG_SURE))return; let r=await fetch('/del_sub/'+id,{{method:'POST'}});if((await r.json()).ok)e.target.closest('tr').remove();}};
</script>"""

    if v == 'ledger':
        rs = qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 100")
        rows = "".join([f"<tr><td><b>{esc(r.get('name') or '')}</b></td><td><b style='color:#ffbe4d;font-size:14px'>{r.get('amount')} {esc(r.get('currency') or '')}</b></td><td>{esc(r.get('note') or '')}</td><td><button class=\"glass-btn del\" onclick=\"delLedger(event, {r.get('id')})\">🗑</button></td></tr>" for r in rs])
        return f"""
<div class=card style="display:flex;justify-content:space-between;align-items:center"><b>{tr['ledger']}</b><button class=btn-gold onclick="document.getElementById('fLed').style.display='flex'">+ {tr['add']}</button></div>
<form id=fLed style="display:none;gap:6px;margin-top:8px"><input name=name placeholder="Details" required><input name=amount type=number step=0.01 placeholder="Amount" required><input name=note placeholder="Note"><select name=currency style="width:80px"><option>USD</option><option>SYP</option></select><button class=btn-gold>{tr['save']}</button></form>
<input id="searchLedger" onkeyup="filterTable('searchLedger', 'ledgerTable')" placeholder="{tr['search']}" style="margin-top:6px;width:100%">
<table id="ledgerTable" style="width:100%;margin-top:10px"><thead><tr><th>Details</th><th>Amount</th><th>Note</th><th></th></tr></thead><tbody>{rows or '<tr><td colspan=4>Empty</td></tr>'}</tbody></table>
<script>
document.getElementById('fLed').addEventListener('submit',async e=>{{e.preventDefault();let r=await fetch('/add_ledger',{{method:'POST',body:new FormData(e.target)}});if((await r.json()).ok)loadPage('ledger',true);}});
window.delLedger=async function(e, id){{if(!confirm(MSG_SURE))return; let r=await fetch('/del_ledger/'+id,{{method:'POST'}});if((await r.json()).ok)e.target.closest('tr').remove();}};
</script>"""

    if v == 'logs':
        rs = qall("SELECT * FROM logs ORDER BY id DESC LIMIT 500")
        rows = "".join([f"<tr><td><small style='color:#94a3b8'>{esc(r.get('time',''))}</small></td><td><b>{esc(r.get('username') or r.get('user_phone',''))}</b></td><td><span class=badge style='background:#38bdf8;color:#000;padding:4px 8px'>{esc(r.get('action',''))}</span></td><td>{esc(r.get('target',''))}</td><td><small style='color:#cbd5e1'>{esc(r.get('detail',''))}</small></td></tr>" for r in rs])
        clear_btn = f"""<button class=btn-gold onclick="clearAllLogs()" style="background:rgba(239,68,68,0.2);color:#ef4444;border:1px solid rgba(239,68,68,0.5)">🗑 Clear Logs</button>""" if is_manager() else ""
        return f"""
<div class=card style="display:flex;justify-content:space-between;align-items:center"><b>{tr['logs']}</b>{clear_btn}</div>
<input id="searchLogs" onkeyup="filterTable('searchLogs', 'logsTable')" placeholder="{tr['search']}" style="margin-top:6px;width:100%">
<div style="overflow-x:auto; margin-top:10px"><table id="logsTable" style="width:100%;min-width:500px"><thead><tr><th>{tr['time']}</th><th>{tr['users']}</th><th>{tr['action']}</th><th>{tr['target']}</th><th>{tr['detail']}</th></tr></thead><tbody>{rows or '<tr><td colspan=5>Empty</td></tr>'}</tbody></table></div>
<script>
window.clearAllLogs=async function(){{
  if(!confirm(MSG_SURE))return;
  await fetch("/api/clear_logs",{{method:"POST"}}); loadPage("logs",true);
}};
</script>"""

    if v == 'settings':
        cfg = {r['key']: r['value'] for r in qall("SELECT * FROM system_config")}
        
        users_html = ""
        if is_manager():
            rs = qall("SELECT * FROM users ORDER BY username ASC")
            u_rows = "".join([f"<tr><td><b>{esc(r.get('username') or '')}</b></td><td><span class=ip style='background:transparent;border:1px solid #ffffff22;color:#fff'>{esc(r.get('phone') or '')}</span></td><td><span class=badge style='background:rgba(255,190,77,0.2);color:#ffbe4d'>{'Manager' if r.get('role')=='manager' else 'Tech'}</span></td><td style='display:flex;gap:6px'><button class=\"glass-btn edit\" onclick=\"openEditUser('{esc(r.get('phone') or '')}', '{esc(r.get('username') or '')}', '{r.get('role')}')\">✏️</button><button class=\"glass-btn del\" onclick=\"delUser(event, '{esc(r.get('phone') or '')}')\">🗑</button></td></tr>" for r in rs])
            users_html = f"""
            <div class=card style="margin-top:10px;border-color:rgba(255,190,77,0.3)">
              <div style="display:flex;justify-content:space-between;align-items:center"><b style="color:#ffbe4d">👥 {tr['users']} (Admin)</b><button class=btn-gold onclick="openAddUser()">+ {tr['add']}</button></div>
              <table style="width:100%;margin-top:12px"><thead><tr><th>{tr['name']}</th><th>{tr['phone']}</th><th>{tr['role']}</th><th></th></tr></thead><tbody>{u_rows or '<tr><td colspan=4>Empty</td></tr>'}</tbody></table>
            </div>"""

        return f"""
<div style="max-width:1100px;margin:0 auto">
  {users_html}
  <div class=card style="margin-top:10px">
    <b>🔒 Change Password</b>
    <form id=formPass style="display:flex;gap:8px;margin-top:10px">
      <input name=newpass type=password placeholder="New Password" required style="flex:1;margin:0">
      <button class=btn-gold style="margin:0">{tr['save']}</button>
    </form>
  </div>
  <div class=card style="margin-top:10px">
    <b>🖥️ UI Settings</b>
    <div style="display:flex;gap:8px;margin-top:10px">
      <input id="cSize" type="number" placeholder="e.g. 120" value="{cfg.get('card_size','120')}" style="flex:1;margin:0">
      <button class=btn-gold onclick="saveCardSize()" style="margin:0">{tr['save']}</button>
    </div>
    <small style="color:#94a3b8;display:block;margin-top:8px">Grid Card Size in px (Network & Towers pages).</small>
  </div>
</div>
<script>
document.getElementById("formPass").addEventListener("submit",async e=>{{e.preventDefault();let r=await fetch("/change_pass",{{method:"POST",body:new FormData(e.target)}});if((await r.json()).ok){{alert("Saved");e.target.reset();}}}});
window.saveCardSize = async function(){{
  let sz = document.getElementById("cSize").value;
  let r = await fetch("/api/set_config", {{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{key:"card_size",value:sz}})}});
  if((await r.json()).ok){{ document.body.style.setProperty('--cs', sz+'px'); alert('Saved'); }}
}};

/* إدارة المستخدمين */
window.openAddUser=function(){{
  document.getElementById("editBody").innerHTML=`
    <input id=u_name placeholder="Full Name">
    <input id=u_phone placeholder="Login Username / Phone">
    <input id=u_pass type=password placeholder="Password">
    <select id=u_role><option value="tech">Tech (View & Edit limits)</option><option value="manager">Manager (Full Admin)</option></select>
    <button class=btn-gold onclick="saveUser(true)" style="width:100%;margin-top:12px">{tr['save']}</button>`;
  document.getElementById("editModalTitle").textContent="{tr['add']} {tr['users']}"; document.getElementById("editModal").classList.add("show");
}};
window.openEditUser=function(phone, name, role){{
  document.getElementById("editBody").innerHTML=`
    <input id=u_name value="${{name}}" disabled style="opacity:0.5;cursor:not-allowed">
    <input id=u_phone value="${{phone}}" disabled style="opacity:0.5;cursor:not-allowed">
    <input id=u_pass type=password placeholder="New Password (Optional)">
    <select id=u_role><option value="tech">Tech</option><option value="manager">Manager</option></select>
    <button class=btn-gold onclick="saveUser(false)" style="width:100%;margin-top:12px">{tr['save']}</button>`;
  document.getElementById("u_role").value = role;
  document.getElementById("editModalTitle").textContent="{tr['edit']} {tr['users']}"; document.getElementById("editModal").classList.add("show");
}};
window.saveUser=async function(isNew){{
  let d={{username:document.getElementById('u_name').value, phone:document.getElementById('u_phone').value, password:document.getElementById('u_pass').value, role:document.getElementById('u_role').value}};
  if(isNew && (!d.phone || !d.password)) return alert('Missing info');
  let url = isNew ? '/api/users/add' : '/api/users/edit';
  let r=await fetch(url, {{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}});
  let j=await r.json(); if(j.ok) {{closeEditModal(); loadPage('settings',true);}} else alert(j.msg||'Error');
}};
window.delUser=async function(e, phone){{
  if(!confirm(MSG_SURE)) return;
  let r=await fetch('/api/users/del/'+phone, {{method:'POST'}});
  let j=await r.json(); if(j.ok) e.target.closest('tr').remove(); else alert(j.msg||'Cannot delete Admin');
}};
</script>"""

    return "<div class=card>404 Not Found</div>"

def layout(c, v='home'):
    l = request.cookies.get('lang', 'ar'); tr = TR.get(l, TR['ar'])
    cur_user = qone("SELECT * FROM users WHERE phone=?", (session.get('phone') or '',)) or {}
    cfg = {r['key']: r['value'] for r in qall("SELECT * FROM system_config")}
    c_size = cfg.get('card_size', '120')

    # شرطية عرض زر المستخدمين في السايد بار فقط للمدير
    users_link = f"""<a href="#" onclick="event.preventDefault(); loadPage('settings')" id=nav-settings>👥 <span>{tr['users']}</span></a>""" if is_manager() else ""

    return f"""<html dir="{tr['dir']}" lang="{l}"><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>OMAIA ISP</title>
<style>
*{{box-sizing:border-box;font-family:system-ui}}html,body{{margin:0;padding:0}}
body{{background:radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 60%, #070a1f 100%);color:#fff;overflow-x:hidden; --cs: {c_size}px;}}
.card{{background:rgba(20, 25, 45, 0.4);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);color:#fff;padding:16px;border-radius:12px;margin-bottom:10px;border:1px solid rgba(255,255,255,0.1);box-shadow:0 4px 15px rgba(0,0,0,0.2)}}
.btn-gold{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;padding:8px 16px;border:0;border-radius:8px;font-weight:800;font-size:12px;cursor:pointer}}
.grid-small{{display:grid;grid-template-columns:repeat(auto-fill,minmax(var(--cs, 120px),1fr));gap:10px}}
.top{{position:fixed;top:0;left:0;right:0;height:55px;background:rgba(15,20,36,0.8);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);display:flex;align-items:center;justify-content:space-between;padding:0 16px;z-index:1003;border-bottom:1px solid rgba(255,255,255,0.1)}}
/* Sidebar Glassmorphism */
.sidebar{{position:fixed;top:0;bottom:0;width:260px;background:rgba(20, 25, 45, 0.35);backdrop-filter:blur(25px);-webkit-backdrop-filter:blur(25px);border-inline-end:1px solid rgba(255,255,255,0.15);box-shadow:0 0 30px rgba(0,0,0,0.5);z-index:1004;padding:20px 14px;transition:transform 0.4s cubic-bezier(0.175,0.885,0.32,1.275);overflow-y:auto}}
html[dir="rtl"] .sidebar{{transform:translateX(110%);right:0;border-radius:24px 0 0 24px}}
html[dir="rtl"] .sidebar.active{{transform:translateX(0)}}
html[dir="ltr"] .sidebar{{transform:translateX(-110%);left:0;border-radius:0 24px 24px 0}}
html[dir="ltr"] .sidebar.active{{transform:translateX(0)}}
.sidebar a{{display:flex;align-items:center;gap:12px;padding:12px 14px;margin-bottom:8px;color:#cbd5e1;text-decoration:none;border-radius:10px;font-size:14px;font-weight:600;transition:all 0.2s ease}}
.sidebar a:hover{{background:rgba(255,255,255,0.1);color:#fff}}
.sidebar a.active{{background:rgba(255,190,77,0.15);color:#ffbe4d;border:1px solid rgba(255,190,77,0.3)}}
#overlay{{position:fixed;inset:0;background:rgba(0,0,0,0.6);backdrop-filter:blur(2px);z-index:1001;display:none;opacity:0;transition:opacity 0.3s}} 
#overlay.show{{display:block;opacity:1}}
.main{{margin-top:65px;padding:12px;min-height:90vh}}
/* أزرار Glassmorphism شفافة ونصف دائرية */
.glass-btn{{display:inline-flex;align-items:center;justify-content:center;gap:6px;border-radius:20px;padding:6px 14px;font-size:12px;font-weight:700;cursor:pointer;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.15);color:#fff;transition:all 0.2s ease}}
.glass-btn:hover{{background:rgba(255,255,255,0.15);transform:translateY(-2px)}}
.glass-btn.edit{{color:#38bdf8;border-color:rgba(56,189,248,0.4);background:rgba(56,189,248,0.1)}}
.glass-btn.del{{color:#ef4444;border-color:rgba(239,68,68,0.4);background:rgba(239,68,68,0.1)}}
.glass-btn.view{{color:#34d399;border-color:rgba(52,211,153,0.4);background:rgba(52,211,153,0.1)}}
.ip{{background:#000;color:#ffbe4d;padding:4px 8px;border-radius:6px;font-family:monospace;font-size:12px}}
.badge{{background:#ffbe4d;color:#111;padding:4px 8px;border-radius:6px;font-size:11px;font-weight:800}}
table{{width:100%;border-collapse:collapse}} th{{background:rgba(255,255,255,0.05);padding:10px;text-align:start;font-size:13px;border-bottom:2px solid rgba(255,255,255,0.1)}} td{{padding:10px;border-bottom:1px solid rgba(255,255,255,0.05);font-size:13px}}
#editModal{{position:fixed;inset:0;background:rgba(0,0,0,0.7);display:none;align-items:center;justify-content:center;z-index:2005;backdrop-filter:blur(5px);opacity:0;transition:opacity 0.3s}}
#editModal.show{{display:flex;opacity:1}}
#editBox{{background:rgba(20, 25, 45, 0.9);border:1px solid rgba(255,255,255,0.2);border-radius:16px;padding:20px;width:92%;max-width:400px;box-shadow:0 15px 40px rgba(0,0,0,0.6);transform:translateY(20px);transition:transform 0.3s}}
#editModal.show #editBox{{transform:translateY(0)}}
input,select{{width:100%;padding:12px;border-radius:10px;border:1px solid rgba(255,255,255,0.2);background:rgba(0,0,0,0.3);color:#fff;margin-bottom:10px;font-size:14px;outline:none;transition:border 0.2s}}
input:focus,select:focus{{border-color:#ffbe4d}}
.stat{{text-align:center;cursor:pointer;padding:16px 4px}} .stat h4{{margin:6px 0;font-size:13px;color:#cbd5e1}} .stat h3{{margin:6px 0;font-size:20px;font-weight:900}} .ico{{font-size:28px}}
</style>
</head><body>
<div id=overlay onclick="toggleSb(false)"></div>
<div class=sidebar id=sb>
<div style='padding-bottom:16px;border-bottom:1px solid rgba(255,255,255,0.1);margin-bottom:16px;text-align:center'><b style="font-size:20px;font-weight:900;letter-spacing:1px">OMAIA <span style='color:#ffbe4d'>ISP</span></b><br><span class="badge" style="background:rgba(255,255,255,0.1);color:#cbd5e1;margin-top:8px;display:inline-block">👋 {esc(cur_user.get('username') or '')}</span></div>
<a href="#" onclick="event.preventDefault(); loadPage('home')" id=nav-home>🏠 <span>{tr['home']}</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('mikrotik')" id=nav-mikrotik>🖧 <span>{tr['mikrotik']}</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('towers')" id=nav-towers>🗼 <span>{tr['towers']}</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('dishes')" id=nav-dishes>📡 <span>{tr['dishes']}</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('ping')" id=nav-ping>📶 <span>{tr['ping']}</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('network')" id=nav-network>📊 <span>{tr['network']}</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('subs')" id=nav-subs>👥 <span>{tr['subs']}</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('ledger')" id=nav-ledger>📒 <span>{tr['ledger']}</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('logs')" id=nav-logs>📜 <span>{tr['logs']}</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('settings')" id=nav-settings>⚙ <span>{tr['settings']}</span></a>
<div style="margin-top:24px;border-top:1px solid rgba(255,255,255,0.1);padding-top:16px">
  <a href="/api/set_lang/{tr['toggle_code']}" style="background:rgba(255,255,255,0.05)">🌐 <span>{tr['lang_toggle']}</span></a>
  <a href="/logout" style="background:rgba(239,68,68,0.15);color:#ff6b6b;border:1px solid rgba(239,68,68,0.3)">🚪 <span>{tr['logout']}</span></a>
</div>
</div>

<div class=top>
<div style="display:flex;align-items:center;gap:16px"><span onclick="toggleSb()" style='font-size:26px;cursor:pointer;text-shadow:0 2px 4px rgba(0,0,0,0.5)'>☰</span> <b style="font-size:18px;font-weight:900">OMAIA <span style='color:#ffbe4d'>ISP</span></b></div>
</div>

<div class=main id=mn>{c}</div>

<div id=editModal><div id=editBox><div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;border-bottom:1px solid rgba(255,255,255,0.1);padding-bottom:12px'><b id=editModalTitle style="font-size:16px">--</b><button onclick="closeEditModal()" style='background:transparent;border:0;color:#cbd5e1;cursor:pointer;font-size:20px;line-height:1'>✕</button></div><div id=editBody></div></div></div>

<script>
let cur='{v}';
const MSG_SURE = "{tr['sure']}";

window.openLink = function(ip) {{
  if(!ip) return; let u = ip.trim();
  if(!u.startsWith('http://') && !u.startsWith('https://')) u = 'http://' + u;
  window.open(u, '_blank');
}};

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

function toggleSb(f){{
  let sb=document.getElementById('sb'), ov=document.getElementById('overlay'); 
  let o = f!==undefined ? f : !sb.classList.contains('active'); 
  if(o) {{ ov.classList.add('show'); setTimeout(()=>sb.classList.add('active'), 10); }}
  else {{ sb.classList.remove('active'); setTimeout(()=>ov.classList.remove('show'), 300); }}
}}

async function loadPage(v,force=false){{
  cur=v; toggleSb(false);
  document.querySelectorAll('.sidebar a').forEach(a=>a.classList.remove('active'));
  let n=document.getElementById('nav-'+v); if(n) n.classList.add('active');
  let mn=document.getElementById('mn'); mn.innerHTML="<div class=card style='text-align:center;padding:40px'>⏳ Loading...</div>";
  try{{
    let r=await fetch('/api/page?v='+v);
    if(r.status===401){{ location.replace('/login'); return; }}
    let t=await r.text();
    if(t.includes('"ok":false') && t.includes('غير مسجل')){{ location.replace('/login'); return; }}
    mn.innerHTML=t;
    execScripts();
  }}catch(e){{ mn.innerHTML=`<div class=card style="color:#ef4444;text-align:center">Error Loading Page</div>`; }}
}}
function execScripts(){{document.getElementById('mn').querySelectorAll('script').forEach(o=>{{let s=document.createElement('script'); s.textContent=o.textContent; document.body.appendChild(s); o.remove();}});}}

window.closeEditModal=()=>{{
  let md = document.getElementById('editModal');
  md.style.opacity = '0';
  setTimeout(() => md.classList.remove('show'), 300);
}};
// Override add class to also set opacity
const origAdd = DOMTokenList.prototype.add;
DOMTokenList.prototype.add = function(...args) {{
  origAdd.apply(this, args);
  if(args.includes('show') && this.contains('show') && this[0]==='show' || this.value.includes('editModal')) {{
    setTimeout(() => document.getElementById('editModal').style.opacity = '1', 10);
  }}
}};

loadPage(cur,true);
</script></body></html>"""

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
