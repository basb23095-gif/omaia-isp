# -*- coding: utf-8 -*-
from flask import Flask, request, redirect, session, jsonify, Response, make_response
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, html, ipaddress, socket, datetime, re, threading, time, traceback

try:
    import psycopg2, psycopg2.extras
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

# 🚀 تمت إزالة القفل _slock بالكامل لمنع اختناق الشبكة والتأخير
def get_sqlite():
    cn = sqlite3.connect(os.path.join(os.path.dirname(__file__), "omia.db"), timeout=20, isolation_level=None)
    cn.row_factory = sqlite3.Row
    try: cn.execute("PRAGMA journal_mode=WAL;")
    except: pass
    return cn

def qall(q, a=()):
    if USE_PG:
        try:
            cn = psycopg2.connect(DATABASE_URL, sslmode='require', connect_timeout=3)
            cur = cn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(q.replace("?", "%s"), a)
            r = [dict(x) for x in cur.fetchall()]
            cur.close(); cn.close()
            return r
        except Exception:
            return []
    else:
        try:
            cn = get_sqlite()
            res = [dict(x) for x in cn.execute(q, a).fetchall()]
            cn.close()
            return res
        except Exception as e:
            print(f"DB Read Error: {e}")
            return []

def qone(q, a=()):
    r = qall(q, a)
    return r[0] if r else None

def qexec(q, a=()):
    if USE_PG:
        try:
            cn = psycopg2.connect(DATABASE_URL, sslmode='require', connect_timeout=3)
            cur = cn.cursor()
            cur.execute(q.replace("?", "%s"), a)
            cn.commit(); cur.close(); cn.close()
            return True
        except Exception:
            return False
    else:
        try:
            cn = get_sqlite()
            cn.execute(q, a)
            cn.close()
            return True
        except Exception as e:
            print(f"DB Write Error: {e}")
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

    # 🚀 تسريع الدخول
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

# 🚀 إصلاح ميزة إضافة المستخدمين (إضافة فحص قبل الإنشاء لمنع فشل قاعدة البيانات بصمت)
@app.route('/api/users/add', methods=['POST'])
@login_required
@role_required_manager
def add_user():
    d = get_data(request)
    p, pw, u, r =تم فحص الكود بالكامل، والمشاكل التي تسبب البطء الشديد وتعطل إضافة المستخدمين ناتجة عن نقطتين أساسيتين في البنية التحتية البرمجية (الخلفية - Backend):
1. **البطء الشديد (السلاسة):** الكود الحالي يقوم بفتح وإغلاق اتصال بقاعدة البيانات (Postgres) مع كل استعلام، ويستخدم قفل خيوط (`_slock`) يمنع معالجة أكثر من طلب واحد في نفس الوقت. هذا يخنق الموقع تماماً. الحل هو إضافة "تجمع اتصالات" (Connection Pool) والسماح بالاستعلامات المتزامنة.
2. **عطل إضافة اليوزرات:** الكود يستخدم أمر `INSERT OR REPLACE` وهو أمر مخصص لقواعد `SQLite`، وعند تشغيله على استضافة تستخدم `PostgreSQL`، يفشل الأمر بصمت ولا يضيف المستخدم.

لتحويل الموقع إلى "نار" وسلس جداً، ولإضافة أزرار الدعم الفني المطلوبة في واجهة التسجيل (كما تظهر في `image_f2d91f.jpg`)، قم بتحديث الأجزاء التالية في ملف `app.py`:

**أولاً: استبدل دوال الاتصال بقاعدة البيانات (لحل مشكلة البطء جذرياً)**
ابحث عن قسم تهيئة قواعد البيانات والدوال (`qall` و `qexec`) واستبدله بالكامل بهذا الكود:

```python
import psycopg2.pool # أضف هذا الاستدعاء في أعلى الملف مع باقي الـ imports

# --- تحديث دوال الاتصال بقاعدة البيانات لحل مشكلة البطء ---
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip().replace("postgres://", "postgresql://", 1)
USE_PG = bool(DATABASE_URL.startswith("postgresql://") and PG)

pg_pool = None
if USE_PG:
    try:
        # إنشاء Connection Pool لتسريع الاتصالات أضعافاً مضاعفة
        pg_pool = psycopg2.pool.SimpleConnectionPool(1, 20, DATABASE_URL, sslmode='require', connect_timeout=5)
    except Exception as e:
        print("PG Pool Error:", e)

_sqlite_conn = None
# تم إزالة _slock بالكامل لفك الخناق عن النظام والسماح بالتحميل المتزامن

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
