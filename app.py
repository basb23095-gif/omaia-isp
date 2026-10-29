# -*- coding: utf-8 -*-
from flask import Flask, request, redirect, session, jsonify, Response, make_response
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, html, ipaddress, socket, datetime, re, threading, time, traceback

try:
    import psycopg2, psycopg2.extras, psycopg2.pool
    PG = True
except Exception:
    psycopg2 = None; PG = False

import sqlite3
from collections import defaultdict

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "omaia_isp_fixed_secret_token_2026_xyz")
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(days=30)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip().replace("postgres://", "postgresql://", 1)
USE_PG = bool(DATABASE_URL.startswith("postgresql://") and PG)

pg_pool = None
if USE_PG:
    try:
        pg_pool = psycopg2.pool.SimpleConnectionPool(1, 20, DATABASE_URL, sslmode='require', connect_timeout=5)
    except Exception as e:
        print("PG Pool Error:", e)

_sqlite_conn = None

BTN_EDIT = """<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"></path></svg>"""
BTN_DEL = """<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path><line x1="10" y1="11" x2="10" y2="17"></line><line x1="14" y1="11" x2="14" y2="17"></line></svg>"""

TR = {
    'ar': {
        'dir': 'rtl', 'toggle_code': 'en', 'lang_toggle': 'English',
        'home': 'الرئيسية', 'towers': 'الأبراج', 'dishes': 'الصحون والآيبيهات',
        'ping': 'البنج (Ping)', 'network': 'الشبكة', 'subs': 'المشتركين', 'ledger': 'الحسابات',
        'users': 'المستخدمين', 'logs': 'السجل', 'settings': 'الإعدادات', 'logout': 'تسجيل خروج',
        'add': 'إضافة', 'edit': 'تعديل', 'delete': 'حذف', 'save': 'حفظ',
        'sure': 'هل أنت متأكد من الحذف؟ لا يمكن التراجع!', 'search': 'بحث...', 'mikrotik': 'ميكروتك',
        'add_tower': '+ برج جديد', 'add_dish': '+ صحن جديد', 'ip': 'الآي بي / دومين', 'name': 'الاسم',
        'manager': 'مدير', 'tech': 'فني', 'phone': 'اسم الدخول/الهاتف', 'role': 'الصلاحية', 'empty': 'لا توجد بيانات',
        'unassigned_edit': 'أدخل الاسم الجديد لقسم "بدون برج":', 'support': 'التواصل والدعم الفني'
    },
    'en': {
        'dir': 'rtl', 'toggle_code': 'ar', 'lang_toggle': 'العربية',
        'home': 'Home', 'towers': 'Towers', 'dishes': 'Dishes & IPs',
        'ping': 'Ping Check', 'network': 'Network', 'subs': 'Subscribers', 'ledger': 'Ledger',
        'users': 'Users', 'logs': 'Logs', 'settings': 'Settings', 'logout': 'Logout',
        'add': 'Add', 'edit': 'Edit', 'delete': 'Delete', 'save': 'Save',
        'sure': 'Are you sure you want to delete?', 'search': 'Search...', 'mikrotik': 'MikroTik',
        'add_tower': '+ New Tower', 'add_dish': '+ New Dish', 'ip': 'IP / Domain', 'name': 'Name',
        'manager': 'Manager', 'tech': 'Tech', 'phone': 'Login/Phone', 'role': 'Role', 'empty': 'No data found',
        'unassigned_edit': 'Enter new name for "Unassigned" section:', 'support': 'Contact & Support'
    }
}

def esc(s): return html.escape(str(s or ''), quote=True)

def get_sqlite():
    global _sqlite_conn
    if _sqlite_conn is None:
        _sqlite_conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), "omia.db"), check_same_thread=False, timeout=15, isolation_level=None)
        _sqlite_conn.row_factory = sqlite3.Row
        try: _sqlite_conn.execute("PRAGMA journal_mode=WAL;")
        except: pass
    return _sqlite_conn

def qall(q, a=()):
    if USE_PG and pg_pool:
        cn = None
        try:
            cn = pg_pool.getconn()
            cur = cn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(q.replace("?", "%s"), a)
            r = [dict(x) for x in cur.fetchall()]
            cur.close()
            pg_pool.putconn(cn)
            return r
        except Exception:
            if cn: pg_pool.putconn(cn, close=True)
            return []
    else:
        try:
            cn = get_sqlite()
            return [dict(x) for x in cn.execute(q, a).fetchall()]
        except:
            return []

def qone(q, a=()):
    r = qall(q, a)
    return r[0] if r else None

def qexec(q, a=()):
    if USE_PG and pg_pool:
        cn = None
        try:
            cn = pg_pool.getconn()
            cur = cn.cursor()
            cur.execute(q.replace("?", "%s"), a)
            cn.commit()
            cur.close()
            pg_pool.putconn(cn)
            return True
        except Exception:
            if cn: pg_pool.putconn(cn, close=True)
            return False
    else:
        try:
            cn = get_sqlite()
            cn.execute(q, a)
            cn.commit()
            return True
        except:
            return False

def get_data(req):
    try:
        if req.is_json: return req.get_json(silent=True) or {}
    except: pass
    return req.form or req.args or {}

def add_log(phone, action, target='', detail='', username=''):
    try:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        uname = str(username or session.get('username') or session.get('phone') or phone or 'sys')
        qexec("INSERT INTO logs(user_phone,username,action,target,detail,time) VALUES(?,?,?,?,?,?)",
              (str(phone or 'sys'), uname, str(action), str(target)[:300], str(detail)[:500], now))
    except: pass

def get_counts():
    try:
        row = qone("SELECT (SELECT COUNT(*) FROM subs) as ns, (SELECT COUNT(*) FROM dish_ips) as nd, (SELECT COUNT(*) FROM towers) as nt, (SELECT COUNT(*) FROM ledger) as nl, (SELECT COUNT(*) FROM mikrotik_servers) as nm")
        return (row.get('ns', 0), row.get('nd', 0), row.get('nt', 0), row.get('nl', 0), row.get('nm', 0)) if row else (0, 0, 0, 0, 0)
    except: return (0, 0, 0, 0, 0)

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
    
    alters = [
        "ALTER TABLE dish_ips ADD COLUMN tower_id INTEGER",
        "ALTER TABLE towers ADD COLUMN created_at TEXT",
        "ALTER TABLE logs ADD COLUMN username TEXT",
        "ALTER TABLE logs ADD COLUMN target TEXT",
        "ALTER TABLE users ADD COLUMN username TEXT",
        "ALTER TABLE ledger ADD COLUMN currency TEXT"
    ]
    for al in alters:
        try: qexec(al)
        except: pass

    fast_hash = generate_password_hash('admin2024', method='pbkdf2:sha256:1000')
    if not qone("SELECT phone FROM users WHERE phone=?", ('admin',)):
        qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)", ('admin', fast_hash, 'manager', 'مدير النظام'))
    if not qone("SELECT phone FROM users WHERE phone=?", ('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)", ('05344851045', fast_hash, 'manager', 'المدير الأساسي'))

    qexec("UPDATE users SET password=? WHERE phone IN ('admin', '05344851045')", (fast_hash,))

    defaults = [('card_size', '110'), ('unassigned_name', 'بدون برج / Unassigned'), ('theme', 'dark')]
    for k, v in defaults:
        if not qone("SELECT key FROM system_config WHERE key=?", (k,)):
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

def is_valid_ip(h): return bool((h or '').strip())

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
    if not is_valid_ip(ip): return jsonify(ok=False, out='IP/Domain Invalid')
    def try_port(p):
        s = None
        try:
            s = socket.socket(); s.settimeout(0.3)
            if s.connect_ex((ip, p)) == 0: return p
        except: pass
        finally:
            if s:
                try: s.close()
                except: pass
        return None
    try:
        import concurrent.futures as _cf
        with _cf.ThreadPoolExecutor(max_workers=3) as ex:
            futs = [ex.submit(try_port, p) for p in [80, 443, 8080, 8291, 22]]
            for f in _cf.as_completed(futs, timeout=1.0):
                if f.result(): return jsonify(ok=True, out=f'{ip}:{f.result()} ✓')
    except: pass
    return jsonify(ok=False, out=f'{ip} لا يرد / Timeout')

@app.route('/api/stats')
@login_required
def api_stats():
    ns, nd, nt, nl, nm = get_counts()
    logs = qall("SELECT * FROM logs ORDER BY id DESC LIMIT 15")
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
            add_log(u['phone'], 'تسجيل دخول', uin, 'تم الدخول بنجاح', u.get('username') or uin)
            return jsonify(ok=True)
        return jsonify(ok=False, msg='بيانات الدخول غير صحيحة'), 401
    except Exception as e:
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
    if not is_valid_ip(ip): return jsonify(ok=False, msg='IP/Domain Invalid'), 400
    tid_val = int(tid) if tid and str(tid).isdigit() and int(tid) != 0 else None
    ok = qexec("INSERT INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?)", (ip, loc, name, tid_val))
    if ok: add_log(session.get('phone'), 'إضافة صحن', f"{name}", f"IP/Domain: {ip}")
    return jsonify(ok=ok)

@app.route('/api/edit_dish/<int:id>', methods=['POST'])
@login_required
def edit_dish(id):
    d = get_data(request)
    ip, name, loc, tid = (d.get('ip') or '').strip(), (d.get('dish_name') or '').strip(), (d.get('location') or '').strip(), d.get('tower_id')
    if not is_valid_ip(ip): return jsonify(ok=False, msg='IP/Domain Invalid'), 400
    tid_val = int(tid) if tid and str(tid).isdigit() and int(tid) != 0 else None
    ok = qexec("UPDATE dish_ips SET ip=?, dish_name=?, location=?, tower_id=? WHERE id=?", (ip, name, loc, tid_val, id))
    if ok: add_log(session.get('phone'), 'تعديل صحن', f"{name}", f"IP/Domain: {ip}")
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
    except: amt = 0
    ok = qexec("INSERT INTO ledger(name,amount,note,currency) VALUES(?,?,?,?)", (d.get('name', ''), amt, d.get('note', ''), d.get('currency', 'USD')))
    if ok: add_log(session.get('phone'), 'إضافة حساب', d.get('name', ''))
    return jsonify(ok=ok)

@app.route('/edit_ledger/<int:i>', methods=['POST'])
@login_required
def eled(i):
    d = get_data(request)
    try: amt = float(d.get('amount') or 0)
    except: amt = 0
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
    p = str(d.get('phone', '')).strip()
    pw = str(d.get('password', '')).strip()
    u = str(d.get('username', '')).strip()
    r = str(d.get('role', 'tech')).strip()
    
    if not p or not pw:
        return jsonify(ok=False, msg="البيانات ناقصة")
    
    hashed_pw = generate_password_hash(pw, method='pbkdf2:sha256:1000')
    
    if USE_PG:
        ok = qexec("INSERT INTO users(phone, password, role, username) VALUES(?, ?, ?, ?) ON CONFLICT (phone) DO UPDATE SET password=EXCLUDED.password, role=EXCLUDED.role, username=EXCLUDED.username", (p, hashed_pw, r, u))
    else:
        ok = qexec("INSERT OR REPLACE INTO users(phone, password, role, username) VALUES(?, ?, ?, ?)", (p, hashed_pw, r, u))
        
    if ok:
        add_log(session.get('phone'), 'إضافة مستخدم', u, f"صلاحية: {r}")
        
    return jsonify(ok=ok)

@app.route('/api/users/edit', methods=['POST'])
@login_required
@role_required_manager
def edit_user():
    d = get_data(request)
    p, pw, r, u = d.get('phone','').strip(), d.get('password','').strip(), d.get('role','tech'), d.get('username','').strip()
    if pw: qexec("UPDATE users SET password=?, role=?, username=? WHERE phone=?", (generate_password_hash(pw, method='pbkdf2:sha256:1000'), r, u, p))
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
    ok = qexec("UPDATE users SET password=? WHERE phone=?", (generate_password_hash(np, method='pbkdf2:sha256:1000'), session.get('phone')))
    add_log(session.get('phone'), 'تغيير كلمة المرور الشخصية', session.get('phone'))
    return jsonify(ok=ok)

@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login')
def login():
    try: l = request.cookies.get('lang', 'ar'); tr = TR.get(l, TR['ar'])
    except: tr = TR['ar']
    return f"""<html dir="rtl"><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>OMAIA ISP</title>
<style>
*{{box-sizing:border-box;font-family:system-ui, -apple-system, sans-serif}}body{{margin:0;min-height:100vh;background:radial-gradient(circle at 50% 0%, #1e293b, #0f172a 70%, #020617);display:flex;align-items:center;justify-content:center;color:#fff}}
.card{{background:rgba(15, 23, 42, 0.4);backdrop-filter:blur(25px) saturate(180%);border:1px solid rgba(255,255,255,0.1);padding:24px;border-radius:24px;width:92%;max-width:350px;box-shadow:0 15px 40px rgba(0,0,0,0.6)}}
input{{width:100%;padding:14px;margin:8px 0;background:rgba(0,0,0,0.3);border:1px solid rgba(255,255,255,0.1);color:#fff;border-radius:12px;outline:none;transition:0.3s}}
input:focus{{border-color:#ffbe4d}}
.btn{{width:100%;padding:14px;border:0;border-radius:12px;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:900;cursor:pointer;margin-top:12px;transition:0.3s}}
.btn:hover{{transform:translateY(-2px);box-shadow:0 5px 15px rgba(255,190,77,0.3)}}
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
<div id=msg style='text-align:center;color:#ef4444;font-size:13px;margin-top:10px;font-weight:bold'></div>
</form>

<div style="margin-top:20px;padding-top:16px;border-top:1px solid rgba(255,255,255,0.05);text-align:center">
    <b style="font-size:12px;color:#94a3b8;display:block;margin-bottom:10px">الدعم الفني والتواصل</b>
    <div style="display:flex;gap:10px;justify-content:center">
        <a href="https://wa.me/905344851045" target="_blank" style="flex:1;background:rgba(37,211,102,0.1);color:#25d366;text-decoration:none;padding:10px;border-radius:10px;font-size:12px;font-weight:bold;border:1px solid rgba(37,211,102,0.3);display:flex;align-items:center;justify-content:center;gap:6px">واتساب</a>
        <a href="https://instagram.com/af_20_1999" target="_blank" style="flex:1;background:rgba(225,48,108,0.1);color:#e1306c;text-decoration:none;padding:10px;border-radius:10px;font-size:12px;font-weight:bold;border:1px solid rgba(225,48,108,0.3);display:flex;align-items:center;justify-content:center;gap:6px">انستغرام</a>
    </div>
</div>

</div>
<script>
document.getElementById('loginForm').addEventListener('submit', async e => {{
  e.preventDefault();
  let b = document.getElementById('loginBtn'), m = document.getElementById('msg');
  b.disabled = true; b.textContent = '⏳ ...'; m.textContent = '';
  let payload = {{ userin: e.target.userin.value, password: e.target.password.value, remember: document.getElementById('rememberBox').checked }};
  try {{
    let res = await fetch('/api/login_public', {{ method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify(payload) }});
    let txt = await res.text();
    let j = JSON.parse(txt);
    if(j.ok) location.replace('/dash?v=home');
    else {{ m.textContent = j.msg || 'البيانات خاطئة'; b.disabled = false; b.textContent = 'تسجيل الدخول'; }}
  }} catch (err) {{ m.textContent = 'خطأ اتصال بالشبكة'; b.disabled = false; b.textContent = 'تسجيل الدخول'; }}
}});
</script></body></html>"""

@app.route('/logout')
def lo(): session.clear(); return redirect('/login')

@app.route('/dash')
@login_required
def dash(): v = request.args.get('v', 'home'); return layout('', v)

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

<div class="card" style="margin-top:12px;padding:16px;display:flex;justify-content:space-between;align-items:center;background:rgba(20, 30, 50, 0.4);border:1px solid rgba(255,190,77,0.2)">
  <div><b style="font-size:14px;color:#fff">💬 {tr['support']}</b><div style="font-size:11px;color:#94a3b8;margin-top:4px">تواصل معنا عبر المنصات الرسمية</div></div>
  <div style="display:flex;gap:10px">
    <a href="https://wa.me/905344851045" target="_blank" style="background:#25d366;color:#000;text-decoration:none;padding:8px 16px;border-radius:12px;font-size:12px;font-weight:bold;box-shadow:0 4px 12px rgba(37, 211, 102, 0.3);display:flex;align-items:center;gap:6px">واتساب</a>
    <a href="https://instagram.com/af_20_1999" target="_blank" style="background:linear-gradient(45deg, #f09433 0%, #e6683c 25%, #dc2743 50%, #cc2366 75%, #bc1888 100%);color:#fff;text-decoration:none;padding:8px 16px;border-radius:12px;font-size:12px;font-weight:bold;box-shadow:0 4px 12px rgba(220, 39, 67, 0.3);display:flex;align-items:center;gap:6px">انستغرام</a>
  </div>
</div>

<div class=card style="margin-top:8px">
    <div style="display:flex;justify-content:space-between;margin-bottom:10px;border-bottom:1px solid rgba(255,255,255,0.05);padding-bottom:8px;align-items:center">
        <b style="color:#ffbe4d;font-size:14px">📜 السجل الأخير (Logs)</b>
        <button class=btn-glass style="background:rgba(255,255,255,0.1);font-size:11px" onclick="loadPage('logs')">عرض السجل الكامل</button>
    </div>
    <div id=logsPreview></div>
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
   
   let lh = (j.logs || []).map(l => {{
        let isLogin = (l.action||'').includes('دخول');
        let isAdd = (l.action||'').includes('إضافة');
        let isDel = (l.action||'').includes('حذف');
        let badgeStyle = isLogin ? 'background:rgba(16,185,129,0.2);color:#10b981' : (isAdd ? 'background:rgba(56,189,248,0.2);color:#38bdf8' : (isDel ? 'background:rgba(239,68,68,0.2);color:#ef4444' : 'background:rgba(255,190,77,0.2);color:#ffbe4d'));
        return `<tr><td style="padding:10px"><small style="color:#94a3b8">${{l.time||''}}</small></td><td style="padding:10px"><span class=badge style="${{badgeStyle}};padding:4px 8px">${{l.action||'-'}}</span></td><td style="padding:10px"><b style="color:#fff">${{l.username||l.user_phone||''}}</b></td><td style="color:#cbd5e1;font-size:12px;padding:10px">${{l.target||''}}</td></tr>`;
   }}).join('');
   document.getElementById('logsPreview').innerHTML='<table style="width:100%;border-collapse:collapse"><tbody>'+(lh || '<tr><td style="text-align:center;color:#666;padding:20px">لا يوجد حركات بعد</td></tr>')+'</tbody></table>';
  }}
 }}catch(e){{}}
}})();
</script>"""

    if v == 'mikrotik':
        servers = qall("SELECT * FROM mikrotik_servers ORDER BY id DESC")
        cards = "".join([f"""<div class="card" id="mk-server-{s['id']}"><div style="display:flex;justify-content:space-between;align-items:center"><div><b style="font-size:14px">🖧 {esc(s['name'])}</b><div style="font-size:11px;color:#94a3b8;margin-top:2px">{esc(s['host'])}:{s['port']}</div></div><div style="display:flex;gap:6px"><button class="btn-glass btn-del icon-only" onclick="delMk(event, {s['id']})">{BTN_DEL}</button></div></div></div>""" for s in servers])
        return f"""
<div style="max-width:1100px;margin:0 auto">
  <div class=card style="display:flex;justify-content:space-between;align-items:center"><b>{tr['mikrotik']}</b><button class=btn-gold onclick="openAddMikrotikModal()">+ {tr['add']}</button></div>
  <div style="display:flex;flex-direction:column;gap:8px;margin-top:8px">{cards or f"<div class=card style='text-align:center;color:#888'>{tr['empty']}</div>"}</div>
</div>
<script>
window.openAddMikrotikModal=function(){{
  document.getElementById("editBody").innerHTML=`<div style="display:flex;flex-direction:column;gap:6px"><input id="mk_name" placeholder="Name"><input id="mk_host" placeholder="IP / Domain"><input id="mk_user" placeholder="User"><input id="mk_pwd" type="password" placeholder="Pass"><input id="mk_port" type="number" value="8728"><button class="btn-gold" onclick="saveNewMikrotik()" style="width:100%;margin-top:4px;border-radius:9999px">{tr['save']}</button></div>`;
  document.getElementById("editModalTitle").textContent="{tr['add']}"; document.getElementById("editModal").classList.add("show");
}};
window.saveNewMikrotik=async function(){{
  let d={{name:document.getElementById("mk_name").value,host:document.getElementById("mk_host").value,username:document.getElementById("mk_user").value,password:document.getElementById("mk_pwd").value,port:document.getElementById("mk_port").value}};
  if(!d.host||!d.username) return;
  if(await window.apiPost('/api/mikrotik/add', d)) {{ closeEditModal(); loadPage('mikrotik', true); }}
}};
window.delMk=async function(e, id){{
  if(!confirm(MSG_SURE)) return;
  let card = e.currentTarget.closest('.card');
  if(await window.apiPost('/api/mikrotik/del/'+id, {{}})) card.remove();
}};
</script>"""

    if v == 'towers' or v == 'dishes':
        all_towers = qall("SELECT * FROM towers ORDER BY name ASC")
        all_dishes = qall("SELECT * FROM dish_ips ORDER BY dish_name ASC")
        
        cfg = {r['key']: r['value'] for r in qall("SELECT * FROM system_config")}
        un_name = esc(cfg.get('unassigned_name', 'بدون برج / Unassigned'))

        dishes_by_tower = defaultdict(list)
        for d in all_dishes:
            dishes_by_tower[d.get('tower_id') or 0].append(d)

        accordion_html = ""
        t_opts = "<option value='0'>---</option>"

        for idx, t in enumerate(all_towers):
            tid = t['id']
            tname = esc(t['name'])
            t_opts += f"<option value='{tid}'>{tname}</option>"
            
            t_dishes = dishes_by_tower[tid]
            cnt = len(t_dishes)
            
            dishes_html = "".join([f"""
            <div class="dish-row" style="display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid rgba(255,255,255,0.05)">
                <div><b style="font-size:12px">{esc(d.get('dish_name') or '--')}</b><br><span class="ip" style="cursor:pointer;font-size:11px;padding:2px 8px;margin-top:4px;display:inline-block" onclick="openLink('{esc(d.get('ip'))}')">{esc(d.get('ip'))}</span> <small style="color:#94a3b8;font-size:10px">{esc(d.get('location') or '')}</small></div>
                <div style="display:flex;gap:6px">
                    <button class="btn-glass btn-edit icon-only" onclick="openDishModal({d['id']}, {tid}, '{esc(d.get('dish_name') or '')}', '{esc(d.get('ip') or '')}', '{esc(d.get('location') or '')}')">{BTN_EDIT}</button>
                    <button class="btn-glass btn-del icon-only" onclick="delDish(event, {d['id']})">{BTN_DEL}</button>
                </div>
            </div>""" for d in t_dishes]) or f'<div style="color:#666;font-size:11px;text-align:center;padding:10px">{tr["empty"]}</div>'
            
            dishes_html += f"""<button class="btn-gold" onclick="openDishModal(0, {tid},'','','')" style="width:100%;margin-top:12px;padding:8px;font-size:12px;border-radius:9999px;">{tr['add_dish']}</button>"""

            is_fixed_tower = (idx == 0)
            edit_tower_btn = ""
            if not is_fixed_tower:
                edit_tower_btn = f"""<button class="btn-glass btn-edit" style="flex:1" onclick="openEditTower({tid}, '{tname}', '{esc(t.get('area') or '')}')">{BTN_EDIT} {tr['edit']}</button>"""
            
            if v == 'towers':
                accordion_html += f"""
                <div class="card tower-card" id="tower-{tid}" style="padding:14px;transition:all 0.3s ease">
                    <div style="display:flex;justify-content:space-between;align-items:center;">
                        <div style="cursor:pointer;flex:1" onclick="toggleAcc({tid})"><b style="font-size:14px;color:#38bdf8">🗼 {tname}</b><div style="font-size:10px;color:#94a3b8;margin-top:4px">📍 {esc(t.get('area') or '...')}</div></div>
                        <div style="display:flex;gap:8px;align-items:center">
                            <span class=badge style="padding:4px 8px;font-size:11px;cursor:pointer;box-shadow:0 0 10px rgba(255,190,77,0.2)" onclick="toggleAcc({tid})">{cnt}</span>
                        </div>
                    </div>
                    <div id="tower-body-{tid}" style="display:none;margin-top:12px;padding-top:10px;border-top:1px solid rgba(255,255,255,0.05)">{dishes_html}</div>
                    <div style="display:flex;gap:8px;margin-top:14px;border-top:1px solid rgba(255,255,255,0.05);padding-top:10px">
                        {edit_tower_btn}
                        <button class="btn-glass btn-del" style="flex:1" onclick="delTower(event, {tid})">{BTN_DEL} {tr['delete']}</button>
                    </div>
                </div>"""
            else:
                accordion_html += f"""
                <div class="card tower-accordion" id="tower-acc-{tid}" style="padding:14px;transition:all 0.3s ease">
                    <div style="display:flex;justify-content:space-between;align-items:center;">
                        <div style="cursor:pointer;flex:1" onclick="toggleAcc({tid})"><b style="font-size:14px;color:#38bdf8">🗼 {tname}</b> <span class="badge" style="font-size:11px;padding:4px 8px;">{cnt}</span></div>
                    </div>
                    <div id="tower-body-{tid}" style="display:none;margin-top:12px;padding-top:10px;border-top:1px solid rgba(255,255,255,0.05)">{dishes_html}</div>
                </div>"""

        if v == 'dishes':
            u_dishes = dishes_by_tower[0]
            u_cnt = len(u_dishes)
            u_dishes_html = "".join([f"""
            <div class="dish-row" style="display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid rgba(255,255,255,0.05)">
                <div><b style="font-size:12px">{esc(d.get('dish_name') or '--')}</b><br><span class="ip" style="cursor:pointer;font-size:11px;padding:2px 8px;margin-top:4px;display:inline-block" onclick="openLink('{esc(d.get('ip'))}')">{esc(d.get('ip'))}</span> <small style="color:#94a3b8;font-size:10px">{esc(d.get('location') or '')}</small></div>
                <div style="display:flex;gap:6px">
                    <button class="btn-glass btn-edit icon-only" onclick="openDishModal({d['id']}, 0, '{esc(d.get('dish_name') or '')}', '{esc(d.get('ip') or '')}', '{esc(d.get('location') or '')}')">{BTN_EDIT}</button>
                    <button class="btn-glass btn-del icon-only" onclick="delDish(event, {d['id']})">{BTN_DEL}</button>
                </div>
            </div>""" for d in u_dishes]) or f'<div style="color:#666;font-size:11px;text-align:center;padding:10px">{tr["empty"]}</div>'
            u_dishes_html += f"""<button class="btn-gold" onclick="openDishModal(0, 0,'','','')" style="width:100%;margin-top:12px;padding:8px;font-size:12px;border-radius:9999px;">{tr['add_dish']}</button>"""
            
            accordion_html += f"""
            <div class="card tower-accordion" id="tower-acc-0" style="border:1px solid rgba(239,68,68,0.3);padding:14px;">
                <div style="display:flex;justify-content:space-between;align-items:center;">
                    <div onclick="toggleAcc(0)" style="cursor:pointer;flex:1"><b style="font-size:14px;color:#ef4444">{un_name}</b> <span class="badge" style="background:#ef4444;font-size:11px;padding:4px 8px;">{u_cnt}</span></div>
                    <div style="display:flex;gap:12px;align-items:center">
                        <button class="btn-glass btn-edit icon-only" style="background:transparent;box-shadow:none;border:1px solid rgba(255,255,255,0.1);width:28px;height:28px;" onclick="editUnassignedName()">{BTN_EDIT}</button>
                        <div onclick="toggleAcc(0)" style="cursor:pointer;font-size:16px;color:#888">▼</div>
                    </div>
                </div>
                <div id="tower-body-0" style="display:none;margin-top:12px;padding-top:10px;border-top:1px solid rgba(255,255,255,0.05)">{u_dishes_html}</div>
            </div>"""

        if v == 'towers':
            return f"""
<div style="max-width:1100px;margin:0 auto">
  <div class=card style="display:flex;justify-content:space-between;align-items:center;padding:14px;"><b>{tr['towers']}</b><button class=btn-gold onclick="openNewTower()" style="padding:8px 16px;font-size:12px;border-radius:9999px;">{tr['add_tower']}</button></div>
  <input id="searchTowers" onkeyup="filterCards('searchTowers', '.tower-card')" placeholder="{tr['search']}" style="margin-top:8px;width:100%;padding:12px;font-size:13px;border-radius:12px;">
  <div class=grid-small id=towersGrid style="margin-top:12px">{accordion_html or f"<div class=card style='text-align:center;color:#666'>{tr['empty']}</div>"}</div>
</div>
<script>
window.toggleAcc = function(tid) {{
  let b = document.getElementById('tower-body-' + tid);
  if(b) b.style.display = b.style.display === 'none' ? 'block' : 'none';
}};
window.openNewTower=function(){{
  document.getElementById("editBody").innerHTML=`<input id=nt_name placeholder="Name"><input id=nt_area placeholder="Area"><button class=btn-gold onclick="saveTower(0)" style="width:100%;margin-top:8px;border-radius:9999px;">{tr['save']}</button>`;
  document.getElementById("editModalTitle").textContent="{tr['add_tower']}"; document.getElementById("editModal").classList.add("show");
}};
window.openEditTower=function(id, name, area){{
  document.getElementById("editBody").innerHTML=`<input id=nt_name value="${{name}}"><input id=nt_area value="${{area}}"><button class=btn-gold onclick="saveTower(${{id}})" style="width:100%;margin-top:8px;border-radius:9999px;">{tr['save']}</button>`;
  document.getElementById("editModalTitle").textContent="{tr['edit']}"; document.getElementById("editModal").classList.add("show");
}};
window.saveTower=async function(id){{
  let d={{name:document.getElementById("nt_name").value, area:document.getElementById("nt_area").value}};
  if(!d.name) return;
  let url = id === 0 ? '/add_tower' : '/edit_tower/'+id;
  if(await window.apiPost(url, d)) {{ closeEditModal(); loadPage('towers', true); }}
}};
window.delTower=async function(e, id){{
  if(!confirm(MSG_SURE)) return;
  let card = e.currentTarget.closest('.card');
  if(await window.apiPost('/del_tower/'+id, {{}})) card.remove();
}};
window.openDishModal=function(id, tid, name, ip, loc){{
  document.getElementById("editBody").innerHTML=`
    <input id="dish_name" placeholder="{tr['name']}" value="${{name}}">
    <input id="dish_ip" placeholder="IP / Domain" value="${{ip}}">
    <input id="dish_loc" placeholder="Location/Note" value="${{loc}}">
    <select id="dish_tid" style="font-weight:bold">{t_opts}</select>
    <button class="btn-gold" onclick="saveDish(${{id}})" style="width:100%;margin-top:8px;border-radius:9999px;">{tr['save']}</button>
  `;
  document.getElementById("dish_tid").value = tid;
  document.getElementById("editModalTitle").textContent = id===0 ? "{tr['add']}" : "{tr['edit']}";
  document.getElementById("editModal").classList.add("show");
}};
window.saveDish=async function(id){{
  let d={{dish_name:document.getElementById("dish_name").value, ip:document.getElementById("dish_ip").value, location:document.getElementById("dish_loc").value, tower_id:document.getElementById("dish_tid").value}};
  if(!d.ip) return alert('يرجى كتابة الآي بي أو الدومين');
  let url = id === 0 ? '/api/add_dish_to_tower' : '/api/edit_dish/'+id;
  if(await window.apiPost(url, d)) {{ closeEditModal(); loadPage(cur, true); }}
}};
window.delDish=async function(e, id){{
  if(!confirm(MSG_SURE)) return;
  let row = e.currentTarget.closest('.dish-row');
  if(await window.apiPost('/del_dish/'+id, {{}})) row.remove();
}};
</script>"""
        else:
            return f"""
<div style="max-width:1100px;margin:0 auto">
  <div class=card style="display:flex;justify-content:space-between;align-items:center;padding:14px;"><b>{tr['dishes']}</b><button class=btn-gold onclick="openDishModal(0,0,'','','')" style="padding:8px 16px;font-size:12px;border-radius:9999px;">{tr['add_dish']}</button></div>
  <input id="searchDishes" onkeyup="filterCards('searchDishes', '.tower-accordion')" placeholder="{tr['search']}" style="margin-top:8px;width:100%;padding:12px;font-size:13px;border-radius:12px;">
  <div style="display:flex;flex-direction:column;gap:10px;margin-top:12px">{accordion_html}</div>
</div>
<script>
window.toggleAcc = function(tid) {{
  let b = document.getElementById('tower-body-' + tid);
  if(b) b.style.display = b.style.display === 'none' ? 'block' : 'none';
}};
window.editUnassignedName = async function() {{
    let newName = prompt("{tr['unassigned_edit']}");
    if(newName) {{
        if(await window.apiPost('/api/set_config', {{key:'unassigned_name', value:newName}})) loadPage('dishes', true);
    }}
}};
window.openDishModal=function(id, tid, name, ip, loc){{
  document.getElementById("editBody").innerHTML=`
    <input id="dish_name" placeholder="{tr['name']}" value="${{name}}">
    <input id="dish_ip" placeholder="IP / Domain" value="${{ip}}">
    <input id="dish_loc" placeholder="Location/Note" value="${{loc}}">
    <select id="dish_tid" style="font-weight:bold">{t_opts}</select>
    <button class="btn-gold" onclick="saveDish(${{id}})" style="width:100%;margin-top:8px;border-radius:9999px;">{tr['save']}</button>
  `;
  document.getElementById("dish_tid").value = tid;
  document.getElementById("editModalTitle").textContent = id===0 ? "{tr['add']}" : "{tr['edit']}";
  document.getElementById("editModal").classList.add("show");
}};
window.saveDish=async function(id){{
  let d={{dish_name:document.getElementById("dish_name").value, ip:document.getElementById("dish_ip").value, location:document.getElementById("dish_loc").value, tower_id:document.getElementById("dish_tid").value}};
  if(!d.ip) return alert('يرجى كتابة الآي بي أو الدومين');
  let url = id === 0 ? '/api/add_dish_to_tower' : '/api/edit_dish/'+id;
  if(await window.apiPost(url, d)) {{ closeEditModal(); loadPage(cur, true); }}
}};
window.delDish=async function(e, id){{
  if(!confirm(MSG_SURE)) return;
  let row = e.currentTarget.closest('.dish-row');
  if(await window.apiPost('/del_dish/'+id, {{}})) row.remove();
}};
</script>"""

    if v == 'ping':
        return f"""
<div class=card><b>{tr['ping']}</b><div style="display:flex;gap:10px;margin-top:14px"><input id="pingIp" placeholder="IP / Domain" style="flex:1;margin:0"><button class="btn-gold" style="margin:0;border-radius:9999px;padding:0 20px" onclick="runPing()">Ping</button></div><div id="pingRes" style="margin-top:14px;padding:16px;background:rgba(0,0,0,0.3);border:1px solid rgba(255,255,255,0.05);border-radius:12px;font-family:monospace;min-height:50px;color:#34d399;font-size:14px;text-align:center">Ready</div></div>
<script>
window.runPing=async function(){{
  let ip=document.getElementById('pingIp').value.trim(); if(!ip)return;
  let o=document.getElementById('pingRes'); o.textContent='⏳ ...';
  try{{ let r=await fetch('/api/ping?ip='+encodeURIComponent(ip)); o.textContent=(await r.json()).out; }}catch(err){{o.textContent='Error';}}
}};
</script>"""

    if v == 'network':
        dishes = qall("SELECT id, dish_name, ip, location FROM dish_ips ORDER BY dish_name ASC LIMIT 100")
        cards = "".join([f"""<div class="card net-card" id="net-card-{d['id']}" style="padding:12px;"><div style="display:flex;justify-content:space-between"><b style="font-size:13px">{esc(d.get('dish_name') or '--')}</b></div><div style="margin-top:8px;display:flex;justify-content:space-between;align-items:center"><span class="ip" style="cursor:pointer;font-size:11px;padding:4px 8px" onclick="openLink('{esc(d.get('ip') or '')}')">{esc(d.get('ip') or '')}</span><span class="net-status badge" id="net-status-{d['id']}" style="background:rgba(255,255,255,0.1);color:#fff;font-size:10px;padding:4px 8px;">-</span></div></div>""" for d in dishes])
        return f"""
<div class=card style="display:flex;justify-content:space-between;align-items:center;padding:14px;"><b>{tr['network']}</b><button class=btn-gold onclick="pingAllNetwork()" style="padding:8px 16px;font-size:12px;border-radius:9999px;">Ping All</button></div>
<input id="searchNetwork" onkeyup="filterCards('searchNetwork', '.net-card')" placeholder="{tr['search']}" style="margin-top:8px;width:100%;padding:12px;font-size:13px;border-radius:12px;">
<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(var(--cs, 110px),1fr));gap:10px;margin-top:12px">{cards or f"<div class=card style='text-align:center;color:#666'>{tr['empty']}</div>"}</div>
<script>
window.pingAllNetwork=async function(){{
  let cards=document.querySelectorAll(".net-card");
  for(let c of cards){{
    let id=c.id.replace('net-card-',''); let ipEl=c.querySelector('.ip'); let stEl=document.getElementById('net-status-'+id);
    if(ipEl && stEl){{
      stEl.textContent='...';
      fetch('/api/ping?ip='+encodeURIComponent(ipEl.textContent)).then(r=>r.json()).then(j=>{{
          stEl.textContent=j.ok ? 'Online' : 'Offline';
          stEl.style.background=j.ok ? '#10b981' : '#ef4444';
          stEl.style.color='#fff';
      }}).catch(()=>{{stEl.textContent='Error';}});
    }}
    await new Promise(r=>setTimeout(r, 100));
  }}
}};
</script>"""

    if v == 'subs':
        rs = qall("SELECT * FROM subs ORDER BY name ASC LIMIT 100")
        rows = "".join([f"<tr class='sub-row'><td><b>{esc(r.get('name') or '')}</b></td><td><span class=ip>{esc(r.get('phone') or '')}</span></td><td>{esc(r.get('note') or '')}</td><td style='display:flex;gap:6px;justify-content:flex-end'><button class=\"btn-glass btn-edit icon-only\" onclick=\"openEditSub({r.get('id')}, '{esc(r.get('name') or '')}', '{esc(r.get('phone') or '')}', '{esc(r.get('note') or '')}')\">{BTN_EDIT}</button><button class=\"btn-glass btn-del icon-only\" onclick=\"delSub(event, {r.get('id')})\">{BTN_DEL}</button></td></tr>" for r in rs])
        return f"""
<div class=card style="display:flex;justify-content:space-between;align-items:center;padding:14px;"><b>{tr['subs']}</b><button class=btn-gold onclick="openAddSubModal()" style="padding:8px 16px;font-size:12px;border-radius:9999px;">+ {tr['add']}</button></div>
<input id="searchSubs" onkeyup="filterTable('searchSubs', 'subsTable')" placeholder="{tr['search']}" style="margin-top:8px;width:100%;padding:12px;font-size:13px;border-radius:12px;">
<div style="overflow-x:auto;margin-top:12px">
<table id="subsTable" style="width:100%;min-width:400px"><thead><tr><th>{tr['name']}</th><th>{tr['phone']}</th><th>Note</th><th style="text-align:end">الإجراء</th></tr></thead><tbody>{rows or '<tr><td colspan=4 style="text-align:center;color:#666">Empty</td></tr>'}</tbody></table>
</div>
<script>
window.openAddSubModal = function() {{
  document.getElementById("editBody").innerHTML=`
    <input id="sub_name" placeholder="{tr['name']}">
    <input id="sub_phone" placeholder="{tr['phone']}">
    <input id="sub_note" placeholder="Note">
    <button class="btn-gold" onclick="saveNewSub()" style="width:100%;margin-top:8px;border-radius:9999px;">{tr['save']}</button>
  `;
  document.getElementById("editModalTitle").textContent = "{tr['add']} {tr['subs']}";
  document.getElementById("editModal").classList.add("show");
}};
window.saveNewSub = async function() {{
  let d = {{name: document.getElementById('sub_name').value, phone: document.getElementById('sub_phone').value, note: document.getElementById('sub_note').value}};
  if(await window.apiPost('/add_sub', d)) {{ closeEditModal(); loadPage('subs', true); }}
}};
window.openEditSub = function(id, name, phone, note) {{
  document.getElementById("editBody").innerHTML=`
    <input id="sub_name" value="${{name}}" placeholder="{tr['name']}">
    <input id="sub_phone" value="${{phone}}" placeholder="{tr['phone']}">
    <input id="sub_note" value="${{note}}" placeholder="Note">
    <button class="btn-gold" onclick="saveSub(${{id}})" style="width:100%;margin-top:8px;border-radius:9999px;">{tr['save']}</button>
  `;
  document.getElementById("editModalTitle").textContent = "{tr['edit']} {tr['subs']}";
  document.getElementById("editModal").classList.add("show");
}};
window.saveSub = async function(id) {{
  let d = {{name: document.getElementById('sub_name').value, phone: document.getElementById('sub_phone').value, note: document.getElementById('sub_note').value}};
  if(await window.apiPost('/edit_sub/'+id, d)) {{ closeEditModal(); loadPage('subs', true); }}
}};
window.delSub=async function(e, id){{
  if(!confirm(MSG_SURE)) return;
  let row = e.currentTarget.closest('tr');
  if(await window.apiPost('/del_sub/'+id, {{}})) row.remove();
}};
</script>"""

    if v == 'ledger':
        rs = qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 100")
        rows = "".join([f"<tr><td><b>{esc(r.get('name') or '')}</b></td><td><b style='color:#ffbe4d;font-size:13px'>{r.get('amount')} {esc(r.get('currency') or '')}</b></td><td>{esc(r.get('note') or '')}</td><td style='display:flex;gap:6px;justify-content:flex-end'><button class=\"btn-glass btn-edit icon-only\" onclick=\"openEditLedger({r.get('id')}, '{esc(r.get('name') or '')}', {r.get('amount')}, '{esc(r.get('note') or '')}', '{esc(r.get('currency') or 'USD')}')\">{BTN_EDIT}</button><button class=\"btn-glass btn-del icon-only\" onclick=\"delLedger(event, {r.get('id')})\">{BTN_DEL}</button></td></tr>" for r in rs])
        return f"""
<div class=card style="display:flex;justify-content:space-between;align-items:center;padding:14px;"><b>{tr['ledger']}</b><button class=btn-gold onclick="openAddLedgerModal()" style="padding:8px 16px;font-size:12px;border-radius:9999px;">+ {tr['add']}</button></div>
<input id="searchLedger" onkeyup="filterTable('searchLedger', 'ledgerTable')" placeholder="{tr['search']}" style="margin-top:8px;width:100%;padding:12px;font-size:13px;border-radius:12px;">
<div style="overflow-x:auto;margin-top:12px">
<table id="ledgerTable" style="width:100%;min-width:400px"><thead><tr><th>Details</th><th>Amount</th><th>Note</th><th style="text-align:end">الإجراء</th></tr></thead><tbody>{rows or '<tr><td colspan=4 style="text-align:center;color:#666">Empty</td></tr>'}</tbody></table>
</div>
<script>
window.openAddLedgerModal = function() {{
  document.getElementById("editBody").innerHTML=`
    <input id="led_name" placeholder="Details">
    <input id="led_amount" type="number" step="0.01" placeholder="Amount">
    <input id="led_note" placeholder="Note">
    <select id="led_curr"><option>USD</option><option>SYP</option></select>
    <button class="btn-gold" onclick="saveNewLedger()" style="width:100%;margin-top:8px;border-radius:9999px;">{tr['save']}</button>
  `;
  document.getElementById("editModalTitle").textContent = "{tr['add']} {tr['ledger']}";
  document.getElementById("editModal").classList.add("show");
}};
window.saveNewLedger = async function() {{
  let d = {{name: document.getElementById('led_name').value, amount: document.getElementById('led_amount').value, note: document.getElementById('led_note').value, currency: document.getElementById('led_curr').value}};
  if(await window.apiPost('/add_ledger', d)) {{ closeEditModal(); loadPage('ledger', true); }}
}};
window.openEditLedger = function(id, name, amount, note, currency) {{
  document.getElementById("editBody").innerHTML=`
    <input id="led_name" value="${{name}}" placeholder="Details">
    <input id="led_amount" type="number" step="0.01" value="${{amount}}" placeholder="Amount">
    <input id="led_note" value="${{note}}" placeholder="Note">
    <select id="led_curr"><option ${{currency==='USD'?'selected':''}}>USD</option><option ${{currency==='SYP'?'selected':''}}>SYP</option></select>
    <button class="btn-gold" onclick="saveLedger(${{id}})" style="width:100%;margin-top:8px;border-radius:9999px;">{tr['save']}</button>
  `;
  document.getElementById("editModalTitle").textContent = "{tr['edit']} {tr['ledger']}";
  document.getElementById("editModal").classList.add("show");
}};
window.saveLedger = async function(id) {{
  let d = {{name: document.getElementById('led_name').value, amount: document.getElementById('led_amount').value, note: document.getElementById('led_note').value, currency: document.getElementById('led_curr').value}};
  if(await window.apiPost('/edit_ledger/'+id, d)) {{ closeEditModal(); loadPage('ledger', true); }}
}};
window.delLedger=async function(e, id){{
  if(!confirm(MSG_SURE)) return;
  let row = e.currentTarget.closest('tr');
  if(await window.apiPost('/del_ledger/'+id, {{}})) row.remove();
}};
</script>"""

    if v == 'logs':
        rs = qall("SELECT * FROM logs ORDER BY id DESC LIMIT 500")
        rows = "".join([f"<tr><td><small style='color:#94a3b8'>{esc(r.get('time',''))}</small></td><td><b style='color:#fff'>{esc(r.get('username') or r.get('user_phone',''))}</b></td><td><span class=badge style='background:rgba(56,189,248,0.2);color:#38bdf8;padding:4px 8px'>{esc(r.get('action',''))}</span></td><td>{esc(r.get('target',''))}</td><td><small style='color:#cbd5e1'>{esc(r.get('detail',''))}</small></td></tr>" for r in rs])
        clear_btn = f"""<button class="btn-glass btn-del" onclick="clearAllLogs()">{BTN_DEL} مسح السجل</button>""" if is_manager() else ""
        return f"""
<div class=card style="display:flex;justify-content:space-between;align-items:center;padding:14px;"><b>{tr['logs']}</b>{clear_btn}</div>
<input id="searchLogs" onkeyup="filterTable('searchLogs', 'logsTable')" placeholder="{tr['search']}" style="margin-top:8px;width:100%;padding:12px;font-size:13px;border-radius:12px;">
<div style="overflow-x:auto; margin-top:12px"><table id="logsTable" style="width:100%;min-width:600px"><thead><tr><th>التاريخ</th><th>{tr['users']}</th><th>{tr['action']}</th><th>{tr['target']}</th><th>{tr['detail']}</th></tr></thead><tbody>{rows or '<tr><td colspan=5 style="text-align:center;color:#666">Empty</td></tr>'}</tbody></table></div>
<script>
window.clearAllLogs=async function(){{
  if(!confirm(MSG_SURE))return;
  if(await window.apiPost("/api/clear_logs", {{}})) loadPage("logs",true);
}};
</script>"""

    if v == 'settings':
        cfg = {r['key']: r['value'] for r in qall("SELECT * FROM system_config")}
        
        users_html = ""
        if is_manager():
            rs = qall("SELECT * FROM users ORDER BY username ASC")
            u_rows = "".join([f"<tr><td><b>{esc(r.get('username') or '')}</b></td><td><span class=ip style='background:transparent;border:1px solid rgba(255,255,255,0.1);color:#fff'>{esc(r.get('phone') or '')}</span></td><td><span class=badge style='background:rgba(255,190,77,0.15);color:#ffbe4d'>{'Manager' if r.get('role')=='manager' else 'Tech'}</span></td><td style='display:flex;gap:6px;justify-content:flex-end'><button class=\"btn-glass btn-edit icon-only\" onclick=\"openEditUser('{esc(r.get('phone') or '')}', '{esc(r.get('username') or '')}', '{r.get('role')}')\">{BTN_EDIT}</button><button class=\"btn-glass btn-del icon-only\" onclick=\"delUser(event, '{esc(r.get('phone') or '')}')\">{BTN_DEL}</button></td></tr>" for r in rs])
            users_html = f"""
            <div class=card style="margin-top:12px;border-color:rgba(255,190,77,0.3);padding:16px;">
              <div style="display:flex;justify-content:space-between;align-items:center"><b style="color:#ffbe4d">👥 {tr['users']} (Admin)</b><button class=btn-gold onclick="openAddUser()" style="padding:8px 16px;font-size:12px;border-radius:9999px;">+ {tr['add']}</button></div>
              <div style="overflow-x:auto"><table style="width:100%;margin-top:12px;min-width:400px"><thead><tr><th>{tr['name']}</th><th>{tr['phone']}</th><th>{tr['role']}</th><th style="text-align:end">الإجراء</th></tr></thead><tbody>{u_rows or '<tr><td colspan=4 style="text-align:center;color:#666">Empty</td></tr>'}</tbody></table></div>
            </div>"""

        return f"""
<div style="max-width:1100px;margin:0 auto">
  {users_html}
  <div class=card style="margin-top:12px;padding:16px;">
    <b style="font-size:14px">🔒 Change Password</b>
    <form id=formPass style="display:flex;gap:10px;margin-top:12px">
      <input name=newpass type=password placeholder="New Password" required style="flex:1;margin:0;padding:12px;font-size:13px;border-radius:12px;">
      <button class=btn-gold style="margin:0;padding:0 20px;font-size:12px;border-radius:9999px;">{tr['save']}</button>
    </form>
  </div>
  <div class=card style="margin-top:12px;padding:16px;">
    <b style="font-size:14px">🖥 UI Settings</b>
    <div style="display:flex;gap:10px;margin-top:12px">
      <input id="cSize" type="number" placeholder="e.g. 120" value="{cfg.get('card_size','110')}" style="flex:1;margin:0;padding:12px;font-size:13px;border-radius:12px;">
      <button class=btn-gold onclick="saveCardSize()" style="margin:0;padding:0 20px;font-size:12px;border-radius:9999px;">{tr['save']}</button>
    </div>
    <small style="color:#94a3b8;display:block;margin-top:8px;font-size:11px;">Grid Card Size in px (Network & Towers pages).</small>
  </div>
</div>
<script>
document.getElementById("formPass").addEventListener("submit",async e=>{{e.preventDefault();let r=await window.apiPost("/change_pass", {{newpass:e.target.newpass.value}}); if(r){{alert("تم التغيير بنجاح"); e.target.reset();}}}});
window.saveCardSize = async function(){{
  let sz = document.getElementById("cSize").value;
  if(await window.apiPost("/api/set_config", {{key:"card_size",value:sz}})) {{ document.body.style.setProperty('--cs', sz+'px'); alert('تم الحفظ'); }}
}};

window.openAddUser=function(){{
  document.getElementById("editBody").innerHTML=`
    <input id=u_name placeholder="Full Name">
    <input id=u_phone placeholder="Login Username / Phone">
    <input id=u_pass type=password placeholder="Password">
    <select id=u_role><option value="tech">Tech</option><option value="manager">Manager</option></select>
    <button class=btn-gold onclick="saveUser(true)" style="width:100%;margin-top:12px;border-radius:9999px;padding:12px">{tr['save']}</button>`;
  document.getElementById("editModalTitle").textContent="{tr['add']} {tr['users']}"; document.getElementById("editModal").classList.add("show");
}};
window.openEditUser=function(phone, name, role){{
  document.getElementById("editBody").innerHTML=`
    <input id=u_name value="${{name}}" placeholder="Full Name">
    <input id=u_phone value="${{phone}}" disabled style="opacity:0.5;cursor:not-allowed">
    <input id=u_pass type=password placeholder="New Password (Optional)">
    <select id=u_role><option value="tech">Tech</option><option value="manager">Manager</option></select>
    <button class=btn-gold onclick="saveUser(false)" style="width:100%;margin-top:12px;border-radius:9999px;padding:12px">{tr['save']}</button>`;
  document.getElementById("u_role").value = role;
  document.getElementById("editModalTitle").textContent="{tr['edit']} {tr['users']}"; document.getElementById("editModal").classList.add("show");
}};
window.saveUser=async function(isNew){{
  let d={{username:document.getElementById('u_name').value, phone:document.getElementById('u_phone').value, password:document.getElementById('u_pass').value, role:document.getElementById('u_role').value}};
  if(isNew && (!d.phone || !d.password)) return alert('البيانات ناقصة');
  let url = isNew ? '/api/users/add' : '/api/users/edit';
  if(await window.apiPost(url, d)) {{closeEditModal(); loadPage('settings',true);}}
}};
window.delUser=async function(e, phone){{
  if(!confirm(MSG_SURE)) return;
  let row = e.currentTarget.closest('tr');
  if(await window.apiPost('/api/users/del/'+phone, {{}})) row.remove();
}};
</script>"""

    return "<div class=card>404 Not Found</div>"

def layout(c, v='home'):
    l = request.cookies.get('lang', 'ar'); tr = TR.get(l, TR['ar'])
    cur_user = qone("SELECT * FROM users WHERE phone=?", (session.get('phone') or '',)) or {}
    cfg = {r['key']: r['value'] for r in qall("SELECT * FROM system_config")}
    c_size = cfg.get('card_size', '110')
    theme = cfg.get('theme', 'dark')
    
    bg_style = "radial-gradient(circle at 50% -20%, #1e293b 0%, #0f172a 40%, #020617 100%)" if theme=='dark' else "linear-gradient(135deg, #f1f5f9 0%, #cbd5e1 100%)"
    card_bg = "rgba(15, 23, 42, 0.45)" if theme=='dark' else "rgba(255, 255, 255, 0.85)"
    text_color = "#f8fafc" if theme=='dark' else "#0f172a"
    top_bg = "rgba(15, 23, 42, 0.6)" if theme=='dark' else "rgba(241, 245, 249, 0.9)"

    return f"""<html dir="rtl" lang="{l}"><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>OMAIA ISP</title>
<style>
*{{box-sizing:border-box;font-family:system-ui, -apple-system, sans-serif}}html,body{{margin:0;padding:0}}
body{{background:{bg_style};color:{text_color};min-height:100vh;overflow-x:hidden; --cs: {c_size}px;}}
.card{{background:{card_bg};backdrop-filter:blur(20px) saturate(150%);-webkit-backdrop-filter:blur(20px) saturate(150%);color:{text_color};padding:12px;border-radius:16px;margin-bottom:10px;border:1px solid rgba(255,255,255,0.05);box-shadow:0 8px 32px rgba(0,0,0,0.2);}}
.btn-gold{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;padding:6px 12px;border:0;border-radius:8px;font-weight:900;font-size:11px;cursor:pointer;transition:transform 0.2s, box-shadow 0.2s}}
.btn-gold:hover{{transform:translateY(-2px); box-shadow:0 4px 15px rgba(255,190,77,0.3);}}
.grid-small{{display:grid;grid-template-columns:repeat(auto-fill,minmax(var(--cs, 110px),1fr));gap:10px}}
.top{{position:fixed;top:0;left:0;right:0;height:60px;background:{top_bg};backdrop-filter:blur(25px) saturate(200%);-webkit-backdrop-filter:blur(25px);display:flex;align-items:center;justify-content:space-between;padding:0 16px;z-index:1003;border-bottom:1px solid rgba(255,255,255,0.05);box-shadow:0 4px 20px rgba(0,0,0,0.3)}}

.sidebar {{
    position: fixed; top: 0; bottom: 0; right: 0; width: 260px;
    background: rgba(15, 23, 42, 0.2) !important; 
    backdrop-filter: blur(35px) saturate(200%); -webkit-backdrop-filter: blur(35px) saturate(200%);
    border-left: 1px solid rgba(255, 255, 255, 0.05);
    box-shadow: -10px 0 40px rgba(0,0,0,0.5); z-index: 1004; padding: 24px 16px;
    transform: translateX(110%); transition: transform 0.4s cubic-bezier(0.16, 1, 0.3, 1);
    overflow-y: auto;
}}
.sidebar.active{{transform:translateX(0)}}
.sidebar a{{display:flex;align-items:center;gap:12px;padding:12px 14px;margin-bottom:8px;color:{text_color};text-decoration:none;border-radius:12px;font-size:13.5px;font-weight:600;transition:all 0.2s ease}}
.sidebar a:hover{{background:rgba(255,255,255,0.08);color:#ffbe4d; transform:translateX(-4px)}}
.sidebar a.active{{background:rgba(255,190,77,0.15);color:#ffbe4d;border:1px solid rgba(255,190,77,0.2); box-shadow:0 4px 15px rgba(255,190,77,0.1)}}
#overlay{{position:fixed;inset:0;background:rgba(0,0,0,0.4);backdrop-filter:blur(3px);z-index:1001;display:none;opacity:0;transition:opacity 0.3s}} 
#overlay.show{{display:block;opacity:1}}

.main{{margin-top:70px;padding:12px;min-height:90vh; transition: none;}}

.btn-glass {{
    display: inline-flex; align-items: center; justify-content: center; gap: 6px;
    border: none; border-radius: 9999px; padding: 8px 14px; cursor: pointer;
    backdrop-filter: blur(15px); -webkit-backdrop-filter: blur(15px);
    background: rgba(255, 255, 255, 0.05); transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
    font-size: 11px; font-weight: 700; color:#fff;
}}
.btn-glass:hover {{ transform: translateY(-2px); background: rgba(255, 255, 255, 0.1); }}
.btn-edit {{ color: #FFC107; border: 1px solid rgba(255, 193, 7, 0.3); }}
.btn-edit:hover {{ background: rgba(255, 193, 7, 0.15); box-shadow:0 4px 10px rgba(255, 193, 7, 0.2) }}
.btn-del {{ color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.3); }}
.btn-del:hover {{ background: rgba(239, 68, 68, 0.15); box-shadow:0 4px 10px rgba(239, 68, 68, 0.2) }}
.btn-glass.icon-only {{ padding: 6px; width: 30px; height: 30px; }}

.sq-btn{{display:inline-flex;align-items:center;justify-content:center;gap:4px;border-radius:8px;padding:6px 10px;font-size:11.5px;font-weight:700;cursor:pointer;border:none;color:#fff;transition:transform 0.15s ease;}}
.sq-btn:hover{{transform:translateY(-1.5px);}}
.sq-btn.edit{{background:rgba(255,255,255,0.1); border:1px solid rgba(255,255,255,0.1);}}
.sq-btn.view{{background:rgba(255,190,77,0.15); color:#ffbe4d; border:1px solid rgba(255,190,77,0.2);}}

.ip{{background:rgba(0,0,0,0.4);color:#ffbe4d;padding:4px 8px;border-radius:8px;font-family:monospace;font-size:11.5px;border:1px solid rgba(255,255,255,0.05)}}
.badge{{background:#ffbe4d;color:#111;padding:4px 8px;border-radius:8px;font-size:10.5px;font-weight:800}}
table{{width:100%;border-collapse:collapse}} th{{background:rgba(255,255,255,0.03);padding:12px 10px;text-align:start;font-size:12.5px;border-bottom:1px solid rgba(255,255,255,0.1);color:#cbd5e1}} td{{padding:12px 10px;border-bottom:1px solid rgba(255,255,255,0.03);font-size:13px}}
#editModal{{position:fixed;inset:0;background:rgba(0,0,0,0.6);display:none;align-items:center;justify-content:center;z-index:2005;backdrop-filter:blur(8px);opacity:0;transition:opacity 0.2s}}
#editModal.show{{display:flex;opacity:1}}
#editBox{{background:rgba(15, 23, 42, 0.95);border:1px solid rgba(255,255,255,0.15);border-radius:20px;padding:24px;width:92%;max-width:380px;box-shadow:0 20px 50px rgba(0,0,0,0.7);transform:translateY(20px);transition:transform 0.3s cubic-bezier(0.16, 1, 0.3, 1)}}
#editModal.show #editBox{{transform:translateY(0)}}
input,select{{width:100%;padding:12px 14px;border-radius:12px;border:1px solid rgba(255,255,255,0.1);background:rgba(0,0,0,0.2);color:#fff;margin-bottom:10px;font-size:13.5px;outline:none;transition:border 0.2s, background 0.2s}}
input:focus,select:focus{{border-color:#ffbe4d; background:rgba(0,0,0,0.4)}}
.stat{{text-align:center;cursor:pointer;padding:16px 4px;transition:0.2s}} .stat:hover{{transform:translateY(-3px)}} .stat h4{{margin:6px 0;font-size:12.5px;color:#94a3b8}} .stat h3{{margin:6px 0;font-size:20px;font-weight:900;color:#fff}} .ico{{font-size:28px}}
</style>
</head><body>
<div id=overlay onclick="toggleSb(false)"></div>
<div class=sidebar id=sb>
<div style='padding-bottom:16px;border-bottom:1px solid rgba(255,255,255,0.05);margin-bottom:16px;text-align:center'><b style="font-size:20px;font-weight:900;letter-spacing:1px">OMAIA <span style='color:#ffbe4d'>ISP</span></b><br><span class="badge" style="background:rgba(255,255,255,0.1);color:#cbd5e1;margin-top:8px;display:inline-block">👋 {esc(cur_user.get('username') or '')}</span></div>
<a href="#" onclick="event.preventDefault(); loadPage('home')" id=nav-home>🏠 <span>{tr['home']}</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('mikrotik')" id=nav-mikrotik>🖧 <span>{tr['mikrotik']}</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('towers')" id=nav-towers>🗼 <span>{tr['towers']}</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('dishes')" id=nav-dishes>📡 <span>{tr['dishes']}</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('ping')" id=nav-ping>📶 <span>{tr['ping']}</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('network')" id=nav-network>📊 <span>{tr['network']}</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('subs')" id=nav-subs>👥 <span>{tr['subs']}</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('ledger')" id=nav-ledger>📒 <span>{tr['ledger']}</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('logs')" id=nav-logs>📜 <span>{tr['logs']}</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('settings')" id=nav-settings>⚙️ <span>{tr['settings']}</span></a>
<div style="margin-top:20px;border-top:1px solid rgba(255,255,255,0.05);padding-top:16px;display:flex;flex-direction:column;gap:8px">
  <div style="display:flex;justify-content:space-around">
    <a href="https://wa.me/905344851045" target="_blank" style="padding:8px 12px;font-size:12px;background:rgba(37,211,102,0.15);color:#25d366;border-radius:10px;text-decoration:none;">واتساب</a>
    <a href="https://instagram.com/af_20_1999" target="_blank" style="padding:8px 12px;font-size:12px;background:rgba(225,48,108,0.15);color:#e1306c;border-radius:10px;text-decoration:none;">انستغرام</a>
  </div>
</div>
</div>

<div class=top>
<div style="display:flex;align-items:center;gap:14px">
  <span onclick="toggleSb()" style='font-size:24px;cursor:pointer;color:#e2e8f0'>☰</span> 
  <b style="font-size:18px;font-weight:900">OMAIA <span style='color:#ffbe4d'>ISP</span></b>
</div>
<div style="display:flex;align-items:center;gap:8px;">
  <a href="/api/set_lang/{tr['toggle_code']}" class="sq-btn view" style="text-decoration:none;">🌐 {tr['toggle_code'].upper()}</a>
  <button onclick="toggleTheme()" class="sq-btn edit">{'🌙' if theme=='dark' else '☀️'}</button>
</div>
</div>

<div class=main id=mn>{c}</div>

<div id=editModal><div id=editBox><div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;border-bottom:1px solid rgba(255,255,255,0.1);padding-bottom:12px'><b id=editModalTitle style="font-size:15px">--</b><button onclick="closeEditModal()" style='background:transparent;border:0;color:#cbd5e1;cursor:pointer;font-size:20px;'>✕</button></div><div id=editBody></div></div></div>

<script>
let cur='{v}';
const MSG_SURE = "{tr['sure']}";

window.apiPost = async function(url, data) {{
    let b = document.activeElement;
    let oldTxt = "";
    if (b && b.tagName === 'BUTTON') {{ oldTxt = b.innerHTML; b.disabled = true; b.style.opacity = '0.5'; b.innerHTML = '⏳...'; }}
    
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 6000); 

    try {{
        let r = await fetch(url, {{ 
            method: 'POST', 
            headers: {{'Content-Type': 'application/json'}}, 
            body: JSON.stringify(data),
            signal: controller.signal
        }});
        clearTimeout(timeoutId);
        let txt = await r.text();
        try {{
            let j = JSON.parse(txt);
            if (b) {{ b.disabled = false; b.style.opacity = '1'; b.innerHTML = oldTxt; }}
            if (!j.ok) {{ alert(j.msg || 'فشلت العملية، يرجى المحاولة مجددا'); return false; }}
            return true;
        }} catch(e) {{
            if (b) {{ b.disabled = false; b.style.opacity = '1'; b.innerHTML = oldTxt; }}
            alert('حدث خطأ غير متوقع في الخادم.');
            return false;
        }}
    }} catch (err) {{
        clearTimeout(timeoutId);
        if (b) {{ b.disabled = false; b.style.opacity = '1'; b.innerHTML = oldTxt; }}
        alert('خطأ اتصال: السيرفر لا يستجيب.');
        return false;
    }}
}};

window.openLink = function(ip) {{
  if(!ip) return; let u = ip.trim();
  if(!u.startsWith('http://') && !u.startsWith('https://')) u = 'http://' + u;
  window.open(u, '_blank');
}};

window.toggleTheme = async function() {{
  let r = await fetch('/api/toggle_theme', {{method:'POST'}});
  let j = await r.json();
  if(j.ok) location.reload();
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
  else {{ sb.classList.remove('active'); setTimeout(()=>ov.classList.remove('show'), 200); }}
}}

async function loadPage(v, force=false){{
  cur=v; toggleSb(false);
  document.querySelectorAll('.sidebar a').forEach(a=>a.classList.remove('active'));
  let n=document.getElementById('nav-'+v); if(n) n.classList.add('active');
  let mn=document.getElementById('mn'); 
  
  try{{
    let r=await fetch('/api/page?v='+v);
    if(r.status===401){{ location.replace('/login'); return; }}
    let t=await r.text();
    if(t.includes('"ok":false') && t.includes('غير مسجل')){{ location.replace('/login'); return; }}
    mn.innerHTML=t;
    execScripts();
  }}catch(e){{ 
    mn.innerHTML=`<div class=card style="color:#ef4444;text-align:center;padding:30px">خطأ في تحميل الصفحة ⚠</div>`; 
  }}
}}

function execScripts(){{
    document.querySelectorAll('.dyn-script').forEach(e => e.remove());
    document.getElementById('mn').querySelectorAll('script').forEach(o=>{{
        let s=document.createElement('script'); 
        s.className = 'dyn-script';
        s.textContent=o.textContent; 
        document.body.appendChild(s); 
        o.remove();
    }});
}}

window.closeEditModal=()=>{{
  let md = document.getElementById('editModal');
  md.style.opacity = '0';
  setTimeout(() => md.classList.remove('show'), 250);
}};
loadPage(cur,true);
</script></body></html>"""

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
