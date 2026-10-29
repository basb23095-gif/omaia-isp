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

TR = {
    'ar': {
        'dir': 'rtl', 'toggle_code': 'en', 'lang_toggle': 'English',
        'home': 'الرئيسية', 'towers': 'الأبراج', 'dishes': 'الصحون والآيبيهات',
        'ping': 'البنج (Ping)', 'network': 'الشبكة', 'subs': 'المشتركين', 'ledger': 'الحسابات',
        'users': 'المستخدمين', 'logs': 'السجل', 'settings': 'الإعدادات', 'logout': 'تسجيل خروج',
        'add': 'إضافة', 'edit': 'تعديل', 'delete': 'حذف', 'save': 'حفظ',
        'sure': 'هل أنت متأكد من الحذف؟ لا يمكن التراجع!', 'search': 'بحث...', 'mikrotik': 'ميكروتك',
        'add_tower': '+ برج جديد', 'add_dish': '+ صحن جديد', 'ip': 'الآي بي', 'name': 'الاسم',
        'manager': 'مدير', 'tech': 'فني', 'phone': 'اسم الدخول/الهاتف', 'role': 'الصلاحية', 'empty': 'لا توجد بيانات',
        'unassigned_edit': 'أدخل الاسم الجديد لقسم "بدون برج":', 'support': 'الدعم الفني'
    },
    'en': {
        'dir': 'rtl', 'toggle_code': 'ar', 'lang_toggle': 'العربية',
        'home': 'Home', 'towers': 'Towers', 'dishes': 'Dishes & IPs',
        'ping': 'Ping Check', 'network': 'Network', 'subs': 'Subscribers', 'ledger': 'Ledger',
        'users': 'Users', 'logs': 'Logs', 'settings': 'Settings', 'logout': 'Logout',
        'add': 'Add', 'edit': 'Edit', 'delete': 'Delete', 'save': 'Save',
        'sure': 'Are you sure you want to delete?', 'search': 'Search...', 'mikrotik': 'MikroTik',
        'add_tower': '+ New Tower', 'add_dish': '+ New Dish', 'ip': 'IP Address', 'name': 'Name',
        'manager': 'Manager', 'tech': 'Tech', 'phone': 'Login/Phone', 'role': 'Role', 'empty': 'No data found',
        'unassigned_edit': 'Enter new name for "Unassigned" section:', 'support': 'Support'
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

def get_data(req):
    try:
        if req.is_json:
            return req.get_json(silent=True) or {}
    except Exception:
        pass
    return req.form or req.args or {}

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
    except Exception: pass

def get_counts():
    try:
        row = qone("SELECT (SELECT COUNT(*) FROM subs) as ns, (SELECT COUNT(*) FROM dish_ips) as nd, (SELECT COUNT(*) FROM towers) as nt, (SELECT COUNT(*) FROM ledger) as nl, (SELECT COUNT(*) FROM mikrotik_servers) as nm")
        return (row.get('ns', 0), row.get('nd', 0), row.get('nt', 0), row.get('nl', 0), row.get('nm', 0)) if row else (0, 0, 0, 0, 0)
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

    if not qone("SELECT * FROM users WHERE phone=?", ('admin',)):
        qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",
              ('admin', generate_password_hash('admin2024', method='pbkdf2:sha256:150000'), 'manager', 'مدير النظام'))
              
    if not qone("SELECT * FROM users WHERE phone=?", ('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",
              ('05344851045', generate_password_hash('admin2024', method='pbkdf2:sha256:150000'), 'manager', 'المدير الأساسي'))

    qexec("UPDATE users SET password=? WHERE phone IN ('admin', '05344851045')", 
          (generate_password_hash('admin2024', method='pbkdf2:sha256:150000'),))

    defaults = [('card_size', '110'), ('unassigned_name', 'بدون برج / Unassigned'), ('theme', 'dark')]
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
    r.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    r.headers['Pragma'] = 'no-cache'
    return r

@app.route('/api/set_lang/<lang>')
def set_lang(lang):
    if lang not in ['ar', 'en']: lang = 'ar'
    res = make_response(redirect('/dash'))
    res.set_cookie('lang', lang, max_age=31536000)
    return res

@app.route('/api/toggle_theme', methods=['POST'])
@login_required
def toggle_theme():
    cfg = {r['key']: r['value'] for r in qall("SELECT * FROM system_config")}
    cur_t = cfg.get('theme', 'dark')
    new_t = 'light' if cur_t == 'dark' else 'dark'
    if USE_PG: qexec("INSERT INTO system_config(key,value) VALUES('theme',?) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value", (new_t,))
    else: qexec("INSERT OR REPLACE INTO system_config(key,value) VALUES('theme',?)", (new_t,))
    return jsonify(ok=True, theme=new_t)

@app.route('/api/mikrotik/list')
@login_required
def api_mikrotik_list():
    return jsonify(ok=True, servers=qall("SELECT id, name, host, username, port, note FROM mikrotik_servers ORDER BY id DESC"))

@app.route('/api/mikrotik/add', methods=['POST'])
@login_required
@role_required_manager
def api_mikrotik_add():
    d = get_data(request)
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
    d = get_data(request)
    k = (d.get('key') or '').strip(); v = (d.get('value') or '').strip()
    if not k: return jsonify(ok=False), 400
    if USE_PG: qexec("INSERT INTO system_config(key,value) VALUES(?,?) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value", (k, v))
    else: qexec("INSERT OR REPLACE INTO system_config(key,value) VALUES(?,?)", (k, v))
    return jsonify(ok=True)

@app.route('/api/login_public', methods=['POST'])
def api_login_public():
    try:
        d = get_data(request)
        uin = str(d.get('userin') or '').strip()
        pw = str(d.get('password') or '').strip()
        rem = bool(d.get('remember'))
        
        u = qone("SELECT * FROM users WHERE phone=? OR username=?", (uin, uin))
        if u and check_password_hash(u.get('password', ''), pw):
            session.clear()
            session['phone'] = u['phone']
            session['username'] = u.get('username') or u['phone']
            session['role'] = u.get('role') or 'tech'
            if rem: session.permanent = True
            add_log(u['phone'], 'تسجيل دخول', uin, f'{uin}', u.get('username') or uin)
            return jsonify(ok=True)
        return jsonify(ok=False, msg='بيانات الدخول غير صحيحة'), 401
    except Exception as e:
        traceback.print_exc()
        return jsonify(ok=False, msg=str(e)), 500

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
    d = get_data(request)
    ok = qexec("INSERT INTO towers(name,area,lat,lng,created_at) VALUES(?,?,?,?,?)", (d.get('name', 'برج'), d.get('area', ''), 0, 0, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    if ok: add_log(session.get('phone'), 'إضافة برج', d.get('name', ''))
    return jsonify(ok=ok)

@app.route('/edit_tower/<int:id>', methods=['POST'])
@login_required
def edit_tower(id):
    d = get_data(request)
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
    d = get_data(request)
    ip, name, loc, tid = (d.get('ip') or '').strip(), (d.get('dish_name') or '').strip(), (d.get('location') or '').strip(), d.get('tower_id')
    if not is_valid_ip(ip): return jsonify(ok=False, msg='IP Invalid'), 400
    if USE_PG: ok = qexec("INSERT INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?) ON CONFLICT (ip) DO UPDATE SET dish_name=EXCLUDED.dish_name, location=EXCLUDED.location, tower_id=EXCLUDED.tower_id", (ip, loc, name, int(tid) if tid and str(tid).isdigit() and int(tid) != 0 else None))
    else: ok = qexec("INSERT OR REPLACE INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?)", (ip, loc, name, int(tid) if tid and str(tid).isdigit() and int(tid) != 0 else None))
    if ok: add_log(session.get('phone'), 'إضافة صحن', f"{name}", f"IP: {ip}")
    return jsonify(ok=ok)

@app.route('/api/edit_dish/<int:id>', methods=['POST'])
@login_required
def edit_dish(id):
    d = get_data(request)
    ip, name, loc, tid = (d.get('ip') or '').strip(), (d.get('dish_name') or '').strip(), (d.get('location') or '').strip(), d.get('tower_id')
    ok = qexec("UPDATE dish_ips SET ip=?, dish_name=?, location=?, tower_id=? WHERE id=?", (ip, name, loc, int(tid) if tid and str(tid).isdigit() and int(tid)!=0 else None, id))
    if ok: add_log(session.get('phone'), 'تعديل صحن', f"{name}", f"IP: {ip}")
    return jsonify(ok=ok)

@app.route('/del_dish/<int:i>', methods=['POST'])
@login_required
def dd(i):
    ok = qexec("DELETE FROM dish_ips WHERE id=?", (i,))
    if ok: add_log(session.get('phone'), 'حذف صحن', f"ID: {i}")
    return jsonify(ok=ok)

@app.route('/add_sub', methods=['POST'])
@login_required
def asub():
    d = get_data(request)
    ok = qexec("INSERT INTO subs(name,phone,note) VALUES(?,?,?)", (d.get('name', ''), d.get('phone', ''), d.get('note', '')))
    if ok: add_log(session.get('phone'), 'إضافة مشترك', d.get('name', ''))
    return jsonify(ok=ok)

@app.route('/edit_sub/<int:i>', methods=['POST'])
@login_required
def esub(i):
    d = get_data(request)
    ok = qexec("UPDATE subs SET name=?, phone=?, note=? WHERE id=?", (d.get('name',''), d.get('phone',''), d.get('note',''), i))
    if ok: add_log(session.get('phone'), 'تعديل مشترك', d.get('name',''))
    return jsonify(ok=ok)

@app.route('/del_sub/<int:i>', methods=['POST'])
@login_required
def dsub(i):
    ok = qexec("DELETE FROM subs WHERE id=?", (i,))
    if ok: add_log(session.get('phone'), 'حذف مشترك', f"ID: {i}")
    return jsonify(ok=ok)

@app.route('/add_ledger', methods=['POST'])
@login_required
def al():
    d = get_data(request)
    try: amt = float(d.get('amount') or 0)
    except Exception: amt = 0
    ok = qexec("INSERT INTO ledger(name,amount,note,currency) VALUES(?,?,?,?)", (d.get('name', ''), amt, d.get('note', ''), d.get('currency', 'USD')))
    if ok: add_log(session.get('phone'), 'إضافة حساب', d.get('name', ''))
    return jsonify(ok=ok)

@app.route('/edit_ledger/<int:i>', methods=['POST'])
@login_required
def eled(i):
    d = get_data(request)
    try: amt = float(d.get('amount') or 0)
    except Exception: amt = 0
    ok = qexec("UPDATE ledger SET name=?, amount=?, note=?, currency=? WHERE id=?", (d.get('name',''), amt, d.get('note',''), d.get('currency','USD'), i))
    if ok: add_log(session.get('phone'), 'تعديل حساب', d.get('name',''))
    return jsonify(ok=ok)

@app.route('/del_ledger/<int:i>', methods=['POST'])
@login_required
def dll(i):
    ok = qexec("DELETE FROM ledger WHERE id=?", (i,))
    if ok: add_log(session.get('phone'), 'حذف حساب', f"ID: {i}")
    return jsonify(ok=ok)

@app.route('/api/users/add', methods=['POST'])
@login_required
@role_required_manager
def add_user():
    d = get_data(request)
    p, pw, u, r = d.get('phone','').strip(), d.get('password','').strip(), d.get('username','').strip(), d.get('role','tech')
    if not p or not pw: return jsonify(ok=False, msg="البيانات ناقصة")
    ok = qexec("INSERT OR REPLACE INTO users(phone,password,role,username) VALUES(?,?,?,?)", (p, generate_password_hash(pw, method='pbkdf2:sha256:150000'), r, u))
    if ok: add_log(session.get('phone'), 'إضافة مستخدم', u, f"صلاحية: {r}")
    return jsonify(ok=ok)

@app.route('/api/users/edit', methods=['POST'])
@login_required
@role_required_manager
def edit_user():
    d = get_data(request)
    p, pw, r, u = d.get('phone','').strip(), d.get('password','').strip(), d.get('role','tech'), d.get('username','').strip()
    if pw: qexec("UPDATE users SET password=?, role=?, username=? WHERE phone=?", (generate_password_hash(pw, method='pbkdf2:sha256:150000'), r, u, p))
    else: qexec("UPDATE users SET role=?, username=? WHERE phone=?", (r, u, p))
    add_log(session.get('phone'), 'تعديل مستخدم', p)
    return jsonify(ok=True)

@app.route('/api/users/del/<phone>', methods=['POST'])
@login_required
@role_required_manager
def del_user(phone):
    if phone in ['admin', '05344851045']: return jsonify(ok=False, msg="لا يمكن حذف المدير الأساسي")
    ok = qexec("DELETE FROM users WHERE phone=?", (phone,))
    if ok: add_log(session.get('phone'), 'حذف مستخدم', phone)
    return jsonify(ok=ok)

@app.route('/change_pass', methods=['POST'])
@login_required
def cp():
    d = get_data(request); np = (d.get('newpass') or '').strip()
    if not np: return jsonify(ok=False, msg='فارغ'), 400
    ok = qexec("UPDATE users SET password=? WHERE phone=?", (generate_password_hash(np, method='pbkdf2:sha256:150000'), session.get('phone')))
    add_log(session.get('phone'), 'تغيير كلمة المرور الشخصية', session.get('phone'))
    return jsonify(ok=ok)

@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login')
def login():
    try:
        l = request.cookies.get('lang', 'ar')
        tr = TR.get(l, TR['ar'])
    except Exception:
        tr = TR['ar']
    return f"""<html dir="rtl"><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>OMAIA ISP</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<style>
*{{box-sizing:border-box;font-family:system-ui}}body{{margin:0;min-height:100vh;background:radial-gradient(120% 120% at 10% 10%,#1a2344,#0a0e2a 60%);display:flex;align-items:center;justify-content:center;color:#fff}}
.card{{background:rgba(20, 25, 45, 0.6);backdrop-filter:blur(20px);border:1px solid rgba(255,255,255,0.15);padding:24px;border-radius:16px;width:92%;max-width:350px;box-shadow:0 10px 30px rgba(0,0,0,0.5)}}
input{{width:100%;padding:12px;margin:8px 0;background:#0f1424;border:1px solid #ffffff22;color:#fff;border-radius:10px}}
.btn{{width:100%;padding:12px;border:0;border-radius:10px;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:800;cursor:pointer;margin-top:12px}}
</style></head><body>
<div class=card>
<div style='text-align:center;font-weight:900;font-size:26px;margin-bottom:16px'>OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<form id=loginForm>
<input name=userin placeholder='{tr.get('phone', 'اسم الدخول/الهاتف')}' required autofocus>
<input name=password type=password placeholder='***' required>
<label style="display:flex;align-items:center;gap:6px;font-size:13px;margin-top:10px;cursor:pointer">
  <input type="checkbox" name="remember" checked id="rememberBox" style="width:auto;margin:0"> حفظ الدخول
</label>
<button class=btn id=loginBtn>تسجيل الدخول</button>

<div style="display: flex; justify-content: center; gap: 20px; margin-top: 15px;">
  <a href="https://wa.me/905344851045" target="_blank" style="font-size: 22px; text-decoration: none; color:#25d3
