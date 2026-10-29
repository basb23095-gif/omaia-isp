# -*- coding: utf-8 -*-
from flask import Flask, request, redirect, session, jsonify, Response
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, html, ipaddress, secrets, json, socket, platform, io, csv, datetime, re, threading, time, traceback
try:
    import psycopg2, psycopg2.extras
    from psycopg2 import pool as pg_pool
    PG = True
except:
    psycopg2 = None; pg_pool = None; PG = False
import sqlite3
import concurrent.futures as _cf
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
SUPPORT_WA_LINK = "WHATSAPP_LINK_PLACEHOLDER"
SUPPORT_INSTA = "af_20_1999"
SUPPORT_INSTA_LINK = "INSTA_LINK_PLACEHOLDER"

def init_pool():
    global _pg_pool, USE_PG
    if not USE_PG or not pg_pool:
        return
    with _plock:
        if _pg_pool:
            return
        try:
            _pg_pool = pg_pool.ThreadedConnectionPool(3, 20, dsn=DATABASE_URL, sslmode='require', connect_timeout=5)
        except Exception as e:
            print(f"pool init failed {e}")
            _pg_pool = None
            USE_PG = False
init_pool()

def esc(s):
    return html.escape(str(s or ''), quote=True)

def get_conn():
    global USE_PG, _sqlite_conn
    if USE_PG and _pg_pool:
        try:
            c = _pg_pool.getconn()
            if getattr(c, 'closed', 1) == 0:
                return c
            _pg_pool.putconn(c, close=True)
        except:
            pass
        try:
            return psycopg2.connect(DATABASE_URL, sslmode='require', connect_timeout=5)
        except:
            USE_PG = False
    elif USE_PG:
        try:
            return psycopg2.connect(DATABASE_URL, sslmode='require', connect_timeout=2)
        except:
            USE_PG = False
    with _slock:
        if _sqlite_conn is None:
            _sqlite_conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), "omia.db"), check_same_thread=False, timeout=10, isolation_level=None)
            _sqlite_conn.row_factory = sqlite3.Row
            try:
                _sqlite_conn.execute("PRAGMA journal_mode=WAL;")
            except:
                pass
        return _sqlite_conn

def put_conn(c):
    if not c:
        return
    if USE_PG and _pg_pool and hasattr(c, 'closed'):
        try:
            if c.closed == 0:
                _pg_pool.putconn(c)
            else:
                _pg_pool.putconn(c, close=True)
        except:
            try:
                c.close()
            except:
                pass
    elif USE_PG and hasattr(c, 'closed'):
        try:
            c.close()
        except:
            pass

def qall(q, a=()):
    cn = None
    try:
        cn = get_conn()
        if USE_PG and hasattr(cn, 'cursor'):
            cur = cn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(q.replace("?", "%s"), a)
            r = [dict(x) for x in cur.fetchall()]
            cur.close()
            put_conn(cn)
            return r
        else:
            with _slock:
                return [dict(x) for x in cn.execute(q, a).fetchall()]
    except Exception as e:
        if cn and USE_PG and hasattr(cn, 'closed'):
            try:
                cn.rollback()
                put_conn(cn)
            except:
                pass
        print(f"qall err {e}")
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
            cn.commit()
            cur.close()
            put_conn(cn)
        else:
            with _slock:
                cn.execute(q, a)
                cn.commit()
        return True
    except Exception as e:
        print(f"qexec err {e}")
        if cn and USE_PG and hasattr(cn, 'closed'):
            try:
                cn.rollback()
                put_conn(cn)
            except:
                pass
        return False

# Cache helpers with TTL
def cache_get(k):
    with _clock:
        v = _cache.get(k)
        if not v:
            return None
        data, ts, ttl = v
        if time.time() - ts > ttl:
            _cache.pop(k, None)
            return None
        return data

def cache_set(k, data, ttl=60):
    with _clock:
        _cache[k] = (data, time.time(), ttl)

def cache_invalidate(prefix=""):
    with _clock:
        if not prefix:
            _cache.clear()
        else:
            for kk in list(_cache.keys()):
                if kk.startswith(prefix):
                    _cache.pop(kk, None)

def get_data():
    cached = cache_get('all_data')
    if cached:
        return cached
    towers = qall("SELECT * FROM towers ORDER BY name ASC")
    dishes = qall("SELECT * FROM dish_ips ORDER BY dish_name ASC")
    subs = qall("SELECT * FROM subs ORDER BY name ASC")
    data = dict(towers=towers, dishes=dishes, subs=subs)
    cache_set('all_data', data, 30)
    return data

def add_log(phone, action, target='', detail='', username=''):
    try:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not username:
            try:
                username = session.get('username') or session.get('phone') or phone or 'sys'
            except:
                username = phone or 'sys'
        user_phone = phone or 'sys'
        qexec("INSERT INTO logs(user_phone,username,action,target,detail,time) VALUES(?,?,?,?,?,?)",
              (user_phone, username, action, str(target)[:300], str(detail)[:500], now))
        cache_invalidate('logs')
        cache_invalidate('counts')
    except Exception as e:
        print(f"add_log err {e}")

def get_counts():
    cached = cache_get('counts')
    if cached:
        return cached
    try:
        row = qone("SELECT (SELECT COUNT(*) FROM subs) as ns, (SELECT COUNT(*) FROM dish_ips) as nd, (SELECT COUNT(*) FROM towers) as nt, (SELECT COUNT(*) FROM ledger) as nl")
        d = (row.get('ns', 0), row.get('nd', 0), row.get('nt', 0), row.get('nl', 0)) if row else (0, 0, 0, 0)
        cache_set('counts', d, 10)
        return d
    except:
        return (0, 0, 0, 0)

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
    if USE_PG:
        ss = [s.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY") for s in ss]
    for s in ss:
        qexec(s)
    # Alter safety
    for al in ["ALTER TABLE dish_ips ADD COLUMN tower_id INTEGER", "ALTER TABLE towers ADD COLUMN created_at TEXT", "ALTER TABLE logs ADD COLUMN username TEXT", "ALTER TABLE logs ADD COLUMN target TEXT"]:
        try:
            qexec(al)
        except:
            pass
    # Unique index for dishes
    try:
        if USE_PG:
            qexec("CREATE UNIQUE INDEX IF NOT EXISTS idx_dish_ip_unique ON dish_ips(ip)")
            qexec("CREATE INDEX IF NOT EXISTS idx_dish_tower ON dish_ips(tower_id)")
            qexec("CREATE INDEX IF NOT EXISTS idx_logs_time ON logs(time DESC)")
        else:
            qexec("CREATE UNIQUE INDEX IF NOT EXISTS idx_dish_ip_unique ON dish_ips(ip)")
            qexec("CREATE INDEX IF NOT EXISTS idx_dish_tower ON dish_ips(tower_id)")
            qexec("CREATE INDEX IF NOT EXISTS idx_logs_time ON logs(time DESC)")
    except:
        pass
    if not qone("SELECT * FROM users WHERE phone=?", ('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)", ('05344851045', generate_password_hash('admin2024', method='pbkdf2:sha256:150000'), 'manager', 'admin'))
    if not qone("SELECT * FROM towers WHERE name=?", ('نقطة حماة الرئيسية',)):
        qexec("INSERT INTO towers(name,area,lat,lng,created_at) VALUES(?,?,?,?,?)", ('نقطة حماة الرئيسية', 'حماة', 35.1318, 36.7578, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
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

def is_manager():
    return (session.get('role') or '') == 'manager'

def role_required_manager(f):
    @wraps(f)
    def w(*a, **kw):
        if not is_manager():
            return jsonify(ok=False, msg='ممنوع'), 403
        return f(*a, **kw)
    return w

def is_valid_host(h):
    h = (h or '').strip()
    if not h:
        return False
    try:
        ipaddress.ip_address(h)
        return True
    except:
        if len(h) >= 3 and '.' in h and ' ' not in h and re.match(r'^[a-zA-Z0-9.-]+\.[a-zA-Z0-9.-]+$', h):
            return True
        return False

def is_valid_ip(ip):
    return is_valid_host(ip)

@app.after_request
def after(r):
    r.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    r.headers['Pragma'] = 'no-cache'
    r.headers['X-Content-Type-Options'] = 'nosniff'
    return r

@app.route('/ping')
def ping():
    return jsonify(ok=True, use_pg=USE_PG)

@app.route('/api/ping')
@login_required
def api_ping():
    ip = request.args.get('ip', '').strip()
    if not is_valid_ip(ip):
        return jsonify(ok=False, out='IP غير صالح')
    def try_port(p):
        s = None
        try:
            s = socket.socket()
            s.settimeout(0.35)
            if s.connect_ex((ip, p)) == 0:
                return p
        except:
            pass
        finally:
            try:
                s.close()
            except:
                pass
        return None
    try:
        with _cf.ThreadPoolExecutor(max_workers=5) as ex:
            futs = [ex.submit(try_port, p) for p in [80, 443, 8080, 8291, 22]]
            for f in _cf.as_completed(futs, timeout=1.2):
                r = f.result()
                if r:
                    return jsonify(ok=True, out=f'{ip}:{r} ✓')
    except:
        pass
    return jsonify(ok=False, out=f'{ip} لا يرد')

@app.route('/api/ping_batch', methods=['POST'])
@login_required
def api_ping_batch():
    try:
        data = request.json or {}
        ips = data.get('ips') or []
        ips = [str(x).strip() for x in ips if str(x).strip()][:100]
        results = {}
        def check_one(ip):
            if not is_valid_ip(ip):
                return (ip, 'IP غير صالح')
            s = None
            try:
                s = socket.socket()
                s.settimeout(0.4)
                for port in [80, 443, 8080]:
                    try:
                        if s.connect_ex((ip, port)) == 0:
                            return (ip, f'{ip}:{port} ✓')
                    except:
                        pass
                return (ip, f'{ip} لا يرد')
            except:
                return (ip, 'خطأ')
            finally:
                try:
                    s.close()
                except:
                    pass
        with _cf.ThreadPoolExecutor(max_workers=20) as ex:
            for ip, out in ex.map(check_one, ips):
                results[ip] = out
        return jsonify(ok=True, results=results)
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500

@app.route('/api/stats')
@login_required
def api_stats():
    ns, nd, nt, nl = get_counts()
    logs = qall("SELECT * FROM logs ORDER BY id DESC LIMIT 10")
    return jsonify(ok=True, stats=dict(subs=ns, dishes=nd, towers=nt, ledger=nl), logs=logs)

@app.route('/api/towers_list')
@login_required
def api_towers_list():
    towers = qall("SELECT id,name,area,lat,lng FROM towers ORDER BY name ASC")
    return jsonify(ok=True, towers=towers)

@app.route('/api/mikrotik/list')
@login_required
def api_mik_list():
    # placeholder for mikrotik list
    return jsonify(ok=True, data=[])

@app.route('/api/mikrotik/add', methods=['POST'])
@login_required
def api_mik_add():
    return jsonify(ok=True)

@app.route('/api/mikrotik/del', methods=['POST'])
@login_required
def api_mik_del():
    return jsonify(ok=True)

@app.route('/api/toggle_theme', methods=['POST'])
@login_required
def api_toggle_theme():
    cur = session.get('theme', 'dark')
    new_theme = 'light' if cur == 'dark' else 'dark'
    session['theme'] = new_theme
    return jsonify(ok=True, theme=new_theme)

@app.route('/toggle_lang')
@login_required
def toggle_lang():
    cur = session.get('lang', 'ar')
    session['lang'] = 'en' if cur == 'ar' else 'ar'
    add_log(session.get('phone'), 'تغيير لغة', session['lang'])
    return jsonify(ok=True, lang=session['lang'])

@app.route('/toggle_theme')
@login_required
def toggle_theme_old():
    cur = session.get('theme', 'dark')
    session['theme'] = 'light' if cur == 'dark' else 'dark'
    return jsonify(ok=True, theme=session['theme'])

@app.route('/api/set_config', methods=['POST'])
@login_required
@role_required_manager
def set_config():
    d = request.json if request.is_json else request.form
    k = (d.get('key') or '').strip()
    v = (d.get('value') or '').strip()
    if not k:
        return jsonify(ok=False, msg='key'), 400
    if USE_PG:
        qexec("INSERT INTO system_config(key,value) VALUES(?,?) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value", (k, v))
    else:
        qexec("INSERT OR REPLACE INTO system_config(key,value) VALUES(?,?)", (k, v))
    return jsonify(ok=True)

@app.route('/api/login_public', methods=['POST'])
def api_login_public():
    try:
        data = request.json if request.is_json else request.form
        get_d = get_data()
        uin = (data.get('userin') or data.get('phone') or '').strip()
        pw = data.get('password') or ''
        u = qone("SELECT * FROM users WHERE phone=? OR username=?", (uin, uin))
        if u and check_password_hash(u['password'], pw):
            session.clear()
            session['phone'] = u['phone']
            session['username'] = u.get('username') or u['phone']
            session['role'] = u.get('role') or 'tech'
            session.permanent = True
            add_log(u['phone'], 'دخول', uin, 'دخول المستخدم ' + esc(uin))
            return jsonify(ok=True)
        return jsonify(ok=False, msg='خطأ في البيانات'), 401
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500

@app.route('/api/export/<tbl>')
@login_required
def api_export(tbl):
    add_log(session.get('phone'), 'تصدير', tbl)
    output = io.StringIO()
    output.write('\ufeff')
    w = csv.writer(output)
    if tbl == 'dishes':
        rows = qall("SELECT * FROM dish_ips ORDER BY location ASC, dish_name ASC")
        w.writerow(['ID', 'اسم', 'IP', 'موقع', 'tower_id'])
        for r in rows:
            w.writerow([r.get('id', ''), r.get('dish_name', ''), r.get('ip', ''), r.get('location', ''), r.get('tower_id', '')])
        fname = 'dishes.csv'
    elif tbl == 'towers':
        rows = qall("SELECT * FROM towers ORDER BY name ASC")
        w.writerow(['ID', 'اسم', 'منطقة', 'lat', 'lng'])
        for r in rows:
            w.writerow([r.get('id', ''), r.get('name', ''), r.get('area', ''), r.get('lat', ''), r.get('lng', '')])
        fname = 'towers.csv'
    else:
        rows = qall("SELECT * FROM logs ORDER BY id DESC LIMIT 2000")
        w.writerow(['ID', 'وقت', 'المستخدم', 'يوزر', 'عمل', 'الهدف', 'تفصيل'])
        for r in rows:
            w.writerow([r.get('id', ''), r.get('time', ''), r.get('user_phone', ''), r.get('username', ''), r.get('action', ''), r.get('target', ''), r.get('detail', '')])
        fname = 'logs.csv'
    return Response(output.getvalue(), mimetype='text/csv; charset=utf-8', headers={'Content-Disposition': f'attachment; filename={fname}'})

@app.route('/api/clear_logs', methods=['POST'])
@login_required
@role_required_manager
def clear_logs():
    qexec("DELETE FROM logs")
    cache_invalidate('logs')
    return jsonify(ok=True)

@app.route('/api/update_tower_pos', methods=['POST'])
@login_required
def update_tower_pos():
    try:
        d = request.json if request.is_json else request.form
        tid = int(d.get('id'))
        lat = float(d.get('lat'))
        lng = float(d.get('lng'))
        qexec("UPDATE towers SET lat=?,lng=? WHERE id=?", (lat, lng, tid))
        add_log(session.get('phone'), 'تعديل موقع برج', f"ID {tid}")
        cache_invalidate('all_data')
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 400

@app.route('/api/add_dish_to_tower', methods=['POST'])
@login_required
def add_dish_to_tower():
    try:
        d = request.json if request.is_json else request.form
        ip = (d.get('ip') or '').strip()
        name = (d.get('dish_name') or '').strip()
        loc = (d.get('location') or '').strip()
        tid = d.get('tower_id')
        if not is_valid_ip(ip):
            return jsonify(ok=False, msg='IP غير صالح'), 400
        tid_val = int(tid) if tid and str(tid).isdigit() and int(tid) != 0 else None
        if USE_PG:
            ok = qexec("INSERT INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?) ON CONFLICT (ip) DO UPDATE SET dish_name=EXCLUDED.dish_name, location=EXCLUDED.location, tower_id=EXCLUDED.tower_id", (ip, loc, name, tid_val))
        else:
            ok = qexec("INSERT OR REPLACE INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?)", (ip, loc, name, tid_val))
        if ok:
            add_log(session.get('phone'), 'إضافة صحن', name, f"IP: {ip}")
            cache_invalidate('all_data')
            cache_invalidate('counts')
        return jsonify(ok=ok)
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500

@app.route('/api/dish_detail/<int:id>')
@login_required
def dish_detail(id):
    d = qone("SELECT * FROM dish_ips WHERE id=?", (id,))
    if not d:
        return jsonify(ok=False, msg='غير موجود'), 404
    return jsonify(ok=True, dish=d)

@app.route('/api/tower_detail/<int:id>')
@login_required
def tower_detail(id):
    if id == 0:
        dishes = qall("SELECT * FROM dish_ips WHERE tower_id IS NULL ORDER BY dish_name ASC LIMIT 50")
        return jsonify(ok=True, tower=dict(id=0, name='بدون برج', area=''), dishes=dishes)
    t = qone("SELECT * FROM towers WHERE id=?", (id,))
    if not t:
        return jsonify(ok=False, msg='غير موجود'), 404
    dishes = qall("SELECT * FROM dish_ips WHERE tower_id=? ORDER BY dish_name ASC LIMIT 100", (id,))
    return jsonify(ok=True, tower=t, dishes=dishes)

@app.route('/')
def ix():
    return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login')
def login():
    return f"""
<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>OMAIA ISP FINAL</title>
<style>
*{{box-sizing:border-box;font-family:system-ui}}body{{margin:0;min-height:100vh;background:radial-gradient(120% 120% at 10% 10%,#1a2344,#0a0e2a 60%);display:flex;align-items:center;justify-content:center;color:#fff}}
.card{{background:rgba(30,36,51,0.85);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);border:1px solid rgba(255,255,255,0.12);padding:22px;border-radius:16px;width:92%;max-width:360px;box-shadow:0 20px 50px #0006}}
input{{width:100%;padding:12px;margin:7px 0;background:#0f1424;border:1px solid #ffffff22;color:#fff;border-radius:10px}}input:focus{{border-color:#ffbe4d;outline:none}}
.btn{{width:100%;padding:12px;border:0;border-radius:10px;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:800;cursor:pointer}}
.support{{margin-top:16px;padding-top:12px;border-top:1px dashed #ffffff15;text-align:center}}
.support a{{display:inline-flex;align-items:center;justify-content:center;width:32px;height:32px;border-radius:50%;margin:0 6px;text-decoration:none;font-size:14px;box-shadow:0 4px 12px #0004, inset 0 1px 0 rgba(255,255,255,0.2)}}
</style></head><body>
<div class=card>
<div style='text-align:center;font-weight:900;font-size:24px;margin-bottom:12px'>OMAIA <span style='color:#ffbe4d'>ISP FINAL</span></div>
<form id=loginForm>
<input name=userin id=userin placeholder='user' required autofocus>
<input name=password id=password type=password placeholder='password' required>
<button class=btn id=loginBtn>دخول ⚡</button>
<div id=msg style='text-align:center;color:#ff6b6b;font-size:11px;min-height:14px;margin-top:8px'></div>
</form>
<div class=support>
<div style='font-size:11px;color:#94a3b8;margin-bottom:8px'>الدعم الفني</div>
<a href="#" onclick="event.preventDefault(); window.open('{SUPPORT_WA_LINK}', '_blank')" style="background:#25D366;color:#fff">W</a>
<a href="#" onclick="event.preventDefault(); window.open('{SUPPORT_INSTA_LINK}', '_blank')" style="background:linear-gradient(45deg,#feda75,#d62976);color:#fff">I</a>
<div style='font-size:10px;color:#64748b;margin-top:8px'>+{SUPPORT_WA}<br>{SUPPORT_INSTA}</div>
</div>
</div>
<script>
document.getElementById('loginForm').addEventListener('submit', async e => {{
  e.preventDefault();
  let b = document.getElementById('loginBtn'), m = document.getElementById('msg');
  b.textContent = '...'; b.disabled = true;
  try {{
    let fd = new FormData(e.target);
    let res = await fetch('/api/login_public', {{method: 'POST', body: fd}});
    let j = await res.json();
    if(j.ok) {{ location.replace('/dash?v=home'); }} else {{ m.textContent = j.msg; b.textContent = 'دخول ⚡'; b.disabled = false; }}
  }} catch {{ m.textContent = 'خطأ شبكة'; b.textContent = 'دخول ⚡'; b.disabled = false; }}
}});
</script></body></html>
"""

@app.route('/logout')
def lo():
    session.clear()
    return redirect('/login')

@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify(ok=True)

@app.route('/dash')
@login_required
def dash():
    v = request.args.get('v', 'home')
    return layout('<div class=card>...</div>', v)

@app.route('/api/page')
@login_required
def ap():
    try:
        return page_content(request.args.get('v', 'home'))
    except Exception as e:
        traceback.print_exc()
        return f"<div class=card>خطأ {esc(str(e))}</div>", 500

@app.route('/add_dish', methods=['POST'])
@login_required
def ad():
    try:
        d = request.json if request.is_json else request.form
        ip = (d.get('ip') or '').strip()
        name = (d.get('dish_name') or '').strip()
        loc = (d.get('location') or '').strip()
        tid = d.get('tower_id')
        if not is_valid_ip(ip):
            return jsonify(ok=False, msg='IP غير صالح'), 400
        tid_val = int(tid) if tid and str(tid).isdigit() and int(tid) != 0 else None
        if USE_PG:
            ok = qexec("INSERT INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?) ON CONFLICT (ip) DO UPDATE SET dish_name=EXCLUDED.dish_name, location=EXCLUDED.location, tower_id=EXCLUDED.tower_id", (ip, loc, name, tid_val))
        else:
            ok = qexec("INSERT OR REPLACE INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?)", (ip, loc, name, tid_val))
        if ok:
            add_log(session.get('phone'), 'إضافة صحن', name, f"IP: {ip}")
            cache_invalidate('all_data')
            cache_invalidate('counts')
        return jsonify(ok=ok)
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500

@app.route('/edit_dish/<int:i>', methods=['POST'])
@login_required
def ed(i):
    if not is_manager():
        return jsonify(ok=False, msg='ممنوع'), 403
    d = request.json if request.is_json else request.form
    ok = qexec("UPDATE dish_ips SET dish_name=?,ip=?,location=?,tower_id=? WHERE id=?", (d.get('dish_name', ''), d.get('ip', ''), d.get('location', ''), d.get('tower_id') or None, i))
    if ok:
        add_log(session.get('phone'), 'تعديل صحن', f"صحن {i}")
        cache_invalidate('all_data')
    return jsonify(ok=ok)

@app.route('/del_dish/<int:i>', methods=['POST', 'GET'])
@login_required
def dd(i):
    if not is_manager():
        return jsonify(ok=False, msg='ممنوع'), 403
    info = qone("SELECT * FROM dish_ips WHERE id=?", (i,))
    ok = qexec("DELETE FROM dish_ips WHERE id=?", (i,))
    if ok:
        add_log(session.get('phone'), 'حذف صحن', info.get('dish_name', '') if info else f"صحن {i}")
        cache_invalidate('all_data')
        cache_invalidate('counts')
    return jsonify(ok=ok)

@app.route('/add_tower', methods=['POST'])
@login_required
def at():
    try:
        d = request.json if request.is_json else request.form
        la = float(d.get('lat') or 35.1318)
        ln = float(d.get('lng') or 36.7578)
        ok = qexec("INSERT INTO towers(name,area,lat,lng,created_at) VALUES(?,?,?,?,?)", (d.get('name', 'كرت'), d.get('area', ''), la, ln, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        if ok:
            add_log(session.get('phone'), 'إضافة برج', d.get('name', ''))
            cache_invalidate('all_data')
            cache_invalidate('counts')
        return jsonify(ok=ok)
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500

@app.route('/del_tower/<int:i>', methods=['POST', 'GET'])
@login_required
def dt(i):
    if not is_manager():
        return jsonify(ok=False, msg='ممنوع'), 403
    qexec("UPDATE dish_ips SET tower_id=NULL WHERE tower_id=?", (i,))
    ok = qexec("DELETE FROM towers WHERE id=?", (i,))
    if ok:
        add_log(session.get('phone'), 'حذف برج', f"برج {i}")
        cache_invalidate('all_data')
        cache_invalidate('counts')
    return jsonify(ok=ok)

@app.route('/edit_tower/<int:i>', methods=['POST'])
@login_required
def et(i):
    if not is_manager():
        return jsonify(ok=False, msg='ممنوع'), 403
    d = request.json if request.is_json else request.form
    la = float(d.get('lat') or 35.1318)
    ln = float(d.get('lng') or 36.7578)
    ok = qexec("UPDATE towers SET name=?,area=?,lat=?,lng=? WHERE id=?", (d.get('name', ''), d.get('area', ''), la, ln, i))
    if ok:
        add_log(session.get('phone'), 'تعديل برج', f"برج {i}")
        cache_invalidate('all_data')
    return jsonify(ok=ok)

@app.route('/add_sub', methods=['POST'])
@login_required
def asub():
    d = request.json if request.is_json else request.form
    ok = qexec("INSERT INTO subs(name,phone,note) VALUES(?,?,?)", (d.get('name', ''), d.get('phone', ''), d.get('note', '')))
    if ok:
        add_log(session.get('phone'), 'إضافة مشترك', d.get('name', ''))
        cache_invalidate('counts')
    return jsonify(ok=ok)

@app.route('/del_sub/<int:i>', methods=['POST', 'GET'])
@login_required
def dsub(i):
    if not is_manager():
        return jsonify(ok=False), 403
    ok = qexec("DELETE FROM subs WHERE id=?", (i,))
    if ok:
        add_log(session.get('phone'), 'حذف مشترك', f"مشترك {i}")
        cache_invalidate('counts')
    return jsonify(ok=ok)

@app.route('/edit_sub/<int:i>', methods=['POST'])
@login_required
def esub(i):
    if not is_manager():
        return jsonify(ok=False), 403
    d = request.json if request.is_json else request.form
    ok = qexec("UPDATE subs SET name=?,phone=?,note=? WHERE id=?", (d.get('name', ''), d.get('phone', ''), d.get('note', ''), i))
    if ok:
        add_log(session.get('phone'), 'تعديل مشترك', f"مشترك {i}")
    return jsonify(ok=ok)

@app.route('/add_ledger', methods=['POST'])
@login_required
def al():
    d = request.json if request.is_json else request.form
    try:
        amt = float(d.get('amount') or 0)
    except:
        amt = 0
    ok = qexec("INSERT INTO ledger(name,amount,note,currency) VALUES(?,?,?,?)", (d.get('name', ''), amt, d.get('note', ''), d.get('currency', 'USD')))
    if ok:
        add_log(session.get('phone'), 'إضافة حساب', d.get('name', ''))
        cache_invalidate('counts')
    return jsonify(ok=ok)

@app.route('/del_ledger/<int:i>', methods=['POST', 'GET'])
@login_required
def dll(i):
    if not is_manager():
        return jsonify(ok=False), 403
    ok = qexec("DELETE FROM ledger WHERE id=?", (i,))
    if ok:
        add_log(session.get('phone'), 'حذف حساب', f"حساب {i}")
        cache_invalidate('counts')
    return jsonify(ok=ok)

@app.route('/edit_ledger/<int:i>', methods=['POST'])
@login_required
def el(i):
    if not is_manager():
        return jsonify(ok=False), 403
    d = request.json if request.is_json else request.form
    try:
        amt = float(d.get('amount') or 0)
    except:
        amt = 0
    ok = qexec("UPDATE ledger SET name=?,amount=?,note=?,currency=? WHERE id=?", (d.get('name', ''), amt, d.get('note', ''), d.get('currency', 'USD'), i))
    if ok:
        add_log(session.get('phone'), 'تعديل حساب', f"حساب {i}")
    return jsonify(ok=ok)

@app.route('/api/users/add', methods=['POST'])
@app.route('/add_user', methods=['POST'])
@login_required
@role_required_manager
def au():
    ph = (request.form.get('phone') or request.form.get('user_field') or (request.json or {}).get('phone') or '').strip()
    if not ph:
        return jsonify(ok=False, msg='رقم مطلوب'), 400
    if qone("SELECT * FROM users WHERE phone=?", (ph,)):
        return jsonify(ok=False, msg='موجود مسبقاً'), 400
    pw = request.form.get('password') or (request.json or {}).get('password') or '1234'
    role = request.form.get('role') or (request.json or {}).get('role') or 'tech'
    ok = qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)", (ph, generate_password_hash(pw, method='pbkdf2:sha256:150000'), role, ph))
    if ok:
        add_log(session.get('phone'), 'إضافة يوزر', ph)
    return jsonify(ok=ok)

@app.route('/api/users/edit', methods=['POST'])
@app.route('/edit_user', methods=['POST'])
@login_required
@role_required_manager
def eu():
    d = request.json if request.is_json else request.form
    old = (d.get('old_phone') or '').strip()
    new_ph = (d.get('phone') or '').strip()
    new_role = d.get('role', 'tech')
    new_pass = (d.get('password') or '').strip()
    if not old:
        return jsonify(ok=False, msg='خطأ'), 400
    if old != new_ph and qone("SELECT * FROM users WHERE phone=?", (new_ph,)):
        return jsonify(ok=False, msg='موجود'), 400
    if new_pass:
        ok = qexec("UPDATE users SET phone=?,username=?,role=?,password=? WHERE phone=?", (new_ph, new_ph, new_role, generate_password_hash(new_pass, method='pbkdf2:sha256:150000'), old))
    else:
        ok = qexec("UPDATE users SET phone=?,username=?,role=? WHERE phone=?", (new_ph, new_ph, new_role, old))
    if ok:
        add_log(session.get('phone'), 'تعديل يوزر', new_ph)
    return jsonify(ok=ok)

@app.route('/api/users/del/<ph>', methods=['POST', 'GET'])
@app.route('/del_user/<ph>')
@login_required
@role_required_manager
def du(ph):
    if ph == '05344851045':
        return jsonify(ok=False, msg='ممنوع'), 400
    ok = qexec("DELETE FROM users WHERE phone=?", (ph,))
    if ok:
        add_log(session.get('phone'), 'حذف يوزر', ph)
    return jsonify(ok=ok)

@app.route('/change_pass', methods=['POST'])
@login_required
def cp():
    d = request.json if request.is_json else request.form
    np = (d.get('newpass') or d.get('password') or '').strip()
    if not np:
        return jsonify(ok=False, msg='فارغة'), 400
    ok = qexec("UPDATE users SET password=? WHERE phone=?", (generate_password_hash(np, method='pbkdf2:sha256:150000'), session.get('phone')))
    if ok:
        add_log(session.get('phone'), 'تغيير باسورد', session.get('phone') or '')
    return jsonify(ok=ok)

def page_content(v):
    lang = session.get('lang', 'ar')
    def L(ar, en):
        return ar if lang == 'ar' else en
    if v == 'home':
        ns, nd, nt, nl = get_counts()
        logs = qall("SELECT * FROM logs ORDER BY id DESC LIMIT 10")
        lh = "".join([f"<tr><td>{esc(l.get('time',''))}</td><td><span class=badge>{esc(l.get('action',''))}</span></td><td>{esc(l.get('user_phone',''))}</td><td>{esc(l.get('detail',''))}</td></tr>" for l in logs]) or "<tr><td colspan=4>لا يوجد سجل</td></tr>"
        return f"""
<div style="max-width:1100px;margin:0 auto">
<div class=skeleton style="display:none"></div>
<div class=grid-small>
<div class="card small stat" style="cursor:pointer;transition:transform .2s" onmouseover="this.style.transform='translateY(-3px)'" onmouseout="this.style.transform='none'" onclick="event.preventDefault(); loadPage('subs')"><div class=ico>👥</div><h4>{L("مشتركين","Subs")}</h4><h2>{ns}</h2></div>
<div class="card small stat" style="cursor:pointer;transition:transform .2s" onmouseover="this.style.transform='translateY(-3px)'" onmouseout="this.style.transform='none'" onclick="event.preventDefault(); loadPage('dishes')"><div class=ico>📡</div><h4>{L("صحون","Dishes")}</h4><h2>{nd}</h2></div>
<div class="card small stat" style="cursor:pointer;transition:transform .2s" onmouseover="this.style.transform='translateY(-3px)'" onmouseout="this.style.transform='none'" onclick="event.preventDefault(); loadPage('towers')"><div class=ico>🗼</div><h4>{L("أبراج","Towers")}</h4><h2>{nt}</h2></div>
<div class="card small stat" style="cursor:pointer;transition:transform .2s" onmouseover="this.style.transform='translateY(-3px)'" onmouseout="this.style.transform='none'" onclick="event.preventDefault(); loadPage('ledger')"><div class=ico>📒</div><h4>{L("حسابات","Acc")}</h4><h2>{nl}</h2></div>
</div>
<div class=card style="margin-top:10px"><div style="display:flex;justify-content:space-between"><b>📜 {L("السجل","Logs")}</b><a href="#" class=btn-gold onclick="event.preventDefault(); loadPage('logs')" style="text-decoration:none">{L("الكل","All")}</a></div>
<table style="width:100%;margin-top:8px"><thead><tr><th>وقت</th><th>عمل</th><th>يوزر</th><th>تفصيل</th></tr></thead><tbody>{lh}</tbody></table>
</div>
</div>
"""
    if v == 'towers':
        rs = qall("SELECT t.id,t.name,t.area,t.lat,t.lng, COUNT(d.id) as cnt FROM towers t LEFT JOIN dish_ips d ON d.tower_id=t.id GROUP BY t.id,t.name,t.area,t.lat,t.lng ORDER BY t.name ASC")
        cards = ""
        for t in rs:
            tid = t.get('id')
            tname = esc(t.get('name') or f'برج {tid}')
            tarea = esc(t.get('area') or '')
            lat = t.get('lat') or 35.1318
            lng = t.get('lng') or 36.7578
            cnt = t.get('cnt') or 0
            cards += f'<div class="card tower-card" id="tower-{tid}" data-name="{tname.lower()}" data-area="{tarea.lower()}" data-lat="{lat}" data-lng="{lng}" style="transition:transform .2s" onmouseover="this.style.transform=\'translateY(-3px)\'" onmouseout="this.style.transform=\'none\'"><div style="display:flex;justify-content:space-between;align-items:center"><div style="display:flex;gap:10px;align-items:center"><div style="width:44px;height:44px;background:linear-gradient(135deg,var(--accent,#ffbe4d),#ffb020);border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:20px">🗼</div><div><b style="font-size:14px">{tname}</b><div style="font-size:11px;color:#94a3b8;margin-top:2px">📍 {tarea}</div></div></div><span class=badge>{cnt} IP</span></div><div style="display:flex;gap:6px;margin-top:10px"><a href="#" class="sq-btn edit" onclick="event.preventDefault(); openEditTowerPage({tid})">✏ تعديل</a><a href="#" class="sq-btn del" onclick="event.preventDefault(); openDeleteModal(\'/del_tower/{tid}\',{tid},\'{tname}\')">🗑 حذف</a></div></div>'
        return f"""
<div style="max-width:1100px;margin:0 auto"><div class=card style="display:flex;justify-content:space-between;align-items:center"><b>🗼 الأبراج</b><a href="#" class=btn-gold onclick="event.preventDefault(); openNewTowerPage()" style="text-decoration:none">+ برج</a></div>
<div class=row style="margin:8px 0"><input id=filterTowerInput placeholder="بحث..." oninput="event.preventDefault(); filterCards(this.value, 'towersGrid')" style="flex:1"></div>
<div class=grid-small id=towersGrid style="display:grid;grid-template-columns:repeat(2,1fr);gap:10px">{cards}</div></div>
<script>
window.openNewTowerPage = function() {{ 
  let b = document.getElementById("editBody");
  b.innerHTML = '<input id=nt_name placeholder="اسم البرج"><input id=nt_area placeholder="المنطقة"><div class=row><input id=nt_lat value="35.1318"><input id=nt_lng value="36.7578"></div><a href="#" class=btn-gold onclick="event.preventDefault(); saveNewTowerPage()" style="width:100%;text-decoration:none;display:block;text-align:center;margin-top:8px">حفظ</a>';
  document.getElementById("editModalTitle").textContent = "إضافة برج";
  document.getElementById("editModal").classList.add("show");
}};
window.saveNewTowerPage = async function() {{
  let d = {{ name: document.getElementById("nt_name").value, area: document.getElementById("nt_area").value, lat: document.getElementById("nt_lat").value, lng: document.getElementById("nt_lng").value }};
  if(!d.name) return;
  let r = await fetch("/add_tower", {{ method: "POST", headers: {{"Content-Type": "application/json"}}, body: JSON.stringify(d) }});
  let j = await r.json();
  if(j.ok) {{ closeEditModal(); loadPage('towers', true); }}
}};
window.openEditTowerPage = async function(id) {{
  try {{
    let r = await fetch('/api/tower_detail/' + id);
    let j = await r.json();
    if(!j.ok) return;
    let t = j.tower;
    let b = document.getElementById("editBody");
    b.innerHTML = '<input id=et_name value="' + escHtml(t.name || "") + '"><input id=et_area value="' + escHtml(t.area || "") + '"><div class=row><input id=et_lat value="' + (t.lat || "") + '"><input id=et_lng value="' + (t.lng || "") + '"></div><a href="#" class=btn-gold onclick="event.preventDefault(); saveTowerPage(' + id + ')" style="width:100%;display:block;text-align:center;margin-top:8px;text-decoration:none">حفظ</a>';
    document.getElementById("editModalTitle").textContent = "تعديل برج";
    document.getElementById("editModal").classList.add("show");
  }} catch(e) {{ alert(e); }}
}};
window.saveTowerPage = async function(id) {{
  let d = {{ name: document.getElementById("et_name").value, area: document.getElementById("et_area").value, lat: document.getElementById("et_lat").value, lng: document.getElementById("et_lng").value }};
  let r = await fetch("/edit_tower/" + id, {{ method: "POST", headers: {{"Content-Type": "application/json"}}, body: JSON.stringify(d) }});
  let j = await r.json();
  if(j.ok) {{ closeEditModal(); loadPage('towers', true); }}
}};
</script>
"""
    if v == 'dishes':
        towers = qall("SELECT t.id, t.name, t.area, t.lat, t.lng, (SELECT COUNT(*) FROM dish_ips WHERE tower_id=t.id) as cnt FROM towers t ORDER BY t.name ASC")
        no_cnt = (qone("SELECT COUNT(*) as c FROM dish_ips WHERE tower_id IS NULL") or {}).get('c', 0)
        accordion_html = ""
        for t in towers:
            tid = t.get('id')
            tname = esc(t.get('name') or f'برج {tid}')
            tarea = esc(t.get('area') or '')
            cnt = t.get('cnt') or 0
            accordion_html += f'''
<div class="card tower-accordion" id="tower-acc-{tid}" data-name="{tname.lower()}" data-area="{tarea.lower()}" data-loaded="0">
 <div class="tower-accordion-header" onclick="event.preventDefault(); toggleAccordionLazy({tid})" style="padding:14px;display:flex;justify-content:space-between;align-items:center;cursor:pointer">
  <div style="display:flex;align-items:center;gap:12px;flex:1"><div style="width:44px;height:44px;background:linear-gradient(135deg,var(--accent,#ffbe4d),#ffb020);border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:20px">🗼</div><div><b style="font-size:14px">{tname}</b><div style="font-size:11px;color:#94a3b8">📍 {tarea}</div></div></div>
  <div style="display:flex;gap:8px;align-items:center"><span class=badge>{cnt} IP</span><a href="#" class="sq-btn edit" onclick="event.preventDefault(); event.stopPropagation(); openEditTowerPage({tid})" style="text-decoration:none">✏</a><a href="#" class="sq-btn del" onclick="event.preventDefault(); event.stopPropagation(); openDeleteModal('/del_tower/{tid}',{tid},'{tname}')" style="text-decoration:none">🗑</a><div id="arrow-{tid}">▼</div></div>
 </div>
 <div class="tower-accordion-body" id="tower-body-{tid}" style="display:none;background:#0f1424"><div id="tower-content-{tid}" style="padding:12px">جاري التحميل...</div></div>
</div>'''
        accordion_html += f'''
<div class="card tower-accordion" id="tower-acc-0" data-loaded="0" style="border:1px dashed #ef444488">
 <div class="tower-accordion-header" onclick="event.preventDefault(); toggleAccordionLazy(0)" style="padding:14px;display:flex;justify-content:space-between;align-items:center;cursor:pointer">
  <div style="display:flex;gap:10px;align-items:center"><div style="width:44px;height:44px;background:#ef4444;border-radius:10px;display:flex;align-items:center;justify-content:center">⚠</div><div><b>بدون برج</b><div style="font-size:11px;color:#94a3b8">{no_cnt} IP</div></div></div>
  <span style="background:#ef4444;color:#fff;padding:3px 8px;border-radius:6px;font-size:11px">{no_cnt} IP</span>
 </div>
 <div class="tower-accordion-body" id="tower-body-0" style="display:none;background:#0f1424"><div id="tower-content-0" style="padding:12px"></div></div>
</div>'''
        return f"""
<div style="max-width:1100px;margin:0 auto">
<div class=card style="display:flex;justify-content:space-between;align-items:center"><b>📡 الصحون</b><a href="#" class=btn-gold onclick="event.preventDefault(); openNewTowerAcc()" style="text-decoration:none">+ برج</a></div>
<div id=accordionContainer style="display:flex;flex-direction:column;gap:10px;margin-top:12px">{accordion_html}</div>
</div>
<div id=addDishModal style="position:fixed;inset:0;background:#000a;display:none;align-items:center;justify-content:center;z-index:2500"><div style="background:var(--card-bg);width:95%;max-width:400px;border-radius:14px;padding:18px;border:1px solid var(--border)"><b id=addDishTitle>+ صحن</b><input id=mName placeholder="اسم"><input id=mIp placeholder="IP"><input id=mLoc placeholder="موقع"><input type=hidden id=mTid><div class=row><a href="#" onclick="event.preventDefault(); closeAddDishModal()" style="flex:1;text-align:center;padding:8px;background:var(--border);border-radius:8px;text-decoration:none;color:var(--text)">إلغاء</a><a href="#" onclick="event.preventDefault(); saveDish()" class=btn-gold style="flex:1;text-align:center;text-decoration:none">حفظ</a></div></div></div>
<script>
window.DISH_CACHE = {{}};
window.openInChrome = function(ip) {{
  event.preventDefault();
  if(!ip) return;
  let url = ip;
  if(!url.startsWith('http')) url = 'http://' + url;
  window.open(url, '_blank');
}};
window.toggleAccordionLazy = async function(tid) {{
  event.preventDefault();
  let body = document.getElementById('tower-body-' + tid);
  let acc = document.getElementById('tower-acc-' + tid);
  let isHidden = !body.classList.contains('open');
  if(isHidden) {{
    body.style.display = 'block';
    body.classList.add('open');
    body.style.maxHeight = '4000px';
    body.style.opacity = '1';
    if(acc.dataset.loaded === '0') {{
      let content = document.getElementById('tower-content-' + tid);
      try {{
        let r = await fetch('/api/tower_detail/' + tid);
        let j = await r.json();
        if(j.ok) {{ DISH_CACHE[tid] = j.dishes || []; acc.dataset.loaded = '1'; renderDishes(tid); }}
      }} catch {{ content.innerHTML = 'خطأ'; }}
    }}
  }} else {{
    body.classList.remove('open');
    body.style.maxHeight = '0';
    body.style.opacity = '0';
    setTimeout(() => body.style.display = 'none', 350);
  }}
}};
window.renderDishes = function(tid) {{
  event.preventDefault();
  let dishes = DISH_CACHE[tid] || [];
  let content = document.getElementById('tower-content-' + tid);
  let h = '<div style="display:flex;flex-direction:column;gap:6px">';
  dishes.forEach(d => {{
    h += '<div class="card" style="display:flex;justify-content:space-between;align-items:center;padding:10px;transition:transform .2s" onmouseover="this.style.transform=\'translateY(-2px)\'" onmouseout="this.style.transform=\'none\'"><div><b>' + escHtml(d.dish_name) + '</b><br><span class=ip onclick="event.preventDefault(); openInChrome(\'' + d.ip + '\')">' + d.ip + '</span></div><div style="display:flex;gap:6px"><a href="#" class="sq-btn view" onclick="event.preventDefault(); openInChrome(\'' + d.ip + '\')" style="text-decoration:none">👁 عرض</a><a href="#" class="sq-btn edit" onclick="event.preventDefault(); openEditDish(' + d.id + ')" style="text-decoration:none">✏</a><a href="#" class="sq-btn del" onclick="event.preventDefault(); openDeleteModal(\'/del_dish/' + d.id + '\', ' + d.id + ', \'' + d.ip + '\')" style="text-decoration:none">🗑</a></div></div>';
  }});
  h += '<a href="#" class=btn-gold onclick="event.preventDefault(); openAddDish(' + tid + ')" style="width:100%;margin-top:8px;display:block;text-align:center;text-decoration:none">+ إضافة صحن</a></div>';
  content.innerHTML = h;
}};
window.openAddDish = function(tid) {{
  event.preventDefault();
  document.getElementById('addDishModal').style.display = 'flex';
  document.getElementById('mTid').value = tid;
}};
window.closeAddDishModal = function() {{
  event.preventDefault();
  document.getElementById('addDishModal').style.display = 'none';
}};
window.saveDish = async function() {{
  event.preventDefault();
  let name = document.getElementById('mName').value.trim();
  let ip = document.getElementById('mIp').value.trim();
  let loc = document.getElementById('mLoc').value.trim();
  let tid = document.getElementById('mTid').value;
  if(!ip) return;
  let r = await fetch('/api/add_dish_to_tower', {{method: "POST", headers: {{"Content-Type": "application/json"}}, body: JSON.stringify({{ip: ip, dish_name: name || 'صحن', location: loc, tower_id: tid}})}});
  let j = await r.json();
  if(j.ok) {{ closeAddDishModal(); document.getElementById('tower-acc-' + tid).dataset.loaded = '0'; toggleAccordionLazy(parseInt(tid)); }}
}};
window.openEditDish = async function(id) {{
  event.preventDefault();
  try {{
    let r = await fetch('/api/dish_detail/' + id);
    let j = await r.json();
    if(!j.ok) return;
    let d = j.dish;
    let b = document.getElementById("editBody");
    b.innerHTML = '<input id=ed_n value="' + escHtml(d.dish_name) + '"><input id=ed_i value="' + d.ip + '"><input id=ed_l value="' + escHtml(d.location || '') + '"><a href="#" class=btn-gold onclick="event.preventDefault(); saveEditDish(' + id + ')" style="width:100%;margin-top:8px;display:block;text-align:center;text-decoration:none">حفظ</a>';
    document.getElementById("editModalTitle").textContent = "تعديل صحن";
    document.getElementById("editModal").classList.add("show");
  }} catch(e) {{ alert(e); }}
}};
window.saveEditDish = async function(id) {{
  event.preventDefault();
  let d = {{dish_name: document.getElementById("ed_n").value, ip: document.getElementById("ed_i").value, location: document.getElementById("ed_l").value}};
  let r = await fetch("/edit_dish/" + id, {{method: "POST", headers: {{"Content-Type": "application/json"}}, body: JSON.stringify(d)}});
  let j = await r.json();
  if(j.ok) {{ closeEditModal(); loadPage('dishes', true); }}
}};
window.openNewTowerAcc = function() {{
  event.preventDefault();
  let b = document.getElementById("editBody");
  b.innerHTML = '<input id=nt_name placeholder="اسم البرج"><input id=nt_area placeholder="المنطقة"><div class=row><input id=nt_lat value="35.1318"><input id=nt_lng value="36.7578"></div><a href="#" class=btn-gold onclick="event.preventDefault(); saveNewTowerAcc()" style="width:100%;display:block;text-align:center;margin-top:8px;text-decoration:none">حفظ</a>';
  document.getElementById("editModalTitle").textContent = "إضافة برج";
  document.getElementById("editModal").classList.add("show");
}};
window.saveNewTowerAcc = async function() {{
  event.preventDefault();
  let d = {{name: document.getElementById("nt_name").value, area: document.getElementById("nt_area").value, lat: document.getElementById("nt_lat").value, lng: document.getElementById("nt_lng").value}};
  if(!d.name) return;
  let r = await fetch("/add_tower", {{method: "POST", headers: {{"Content-Type": "application/json"}}, body: JSON.stringify(d)}});
  let j = await r.json();
  if(j.ok) {{ closeEditModal(); loadPage('dishes', true); }}
}};
</script>
"""
    if v == 'map':
        return """
<div class=card><div class=row><input id=mapSearch placeholder="بحث..." oninput="event.preventDefault(); filterTable(this.value, 'mapTable')"><a href="#" class=btn-gold onclick="event.preventDefault(); loadTowersForMap()" style="text-decoration:none">تحديث</a></div><div id=map style="height:70vh;border-radius:10px;margin-top:10px;background:#0f1424;display:flex;align-items:center;justify-content:center">خريطة - سيتم تحميل الأبراج</div></div>
<script>
setTimeout(() => {
  fetch('/api/towers_list').then(r => r.json()).then(j => {
    let m = document.getElementById('map');
    let h = '<div style="padding:10px">';
    (j.towers || []).forEach(t => { h += '<div class=card style="margin:4px 0">🗼 ' + escHtml(t.name) + ' - ' + escHtml(t.area || '') + ' (' + t.lat + ',' + t.lng + ')</div>'; });
    h += '</div>';
    m.innerHTML = h;
  });
}, 300);
</script>
"""
    if v == 'ping':
        return """
<div class=card><h3>📶 البنج</h3><div class=row style="margin-top:8px"><input id=pingIp placeholder="192.168.1.1" style="flex:1"><a href="#" class=btn-gold onclick="event.preventDefault(); doPing()" style="text-decoration:none">فحص</a><a href="#" class=btn-gold onclick="event.preventDefault(); doPingBatch()" style="text-decoration:none;background:#22c55e">فحص جماعي</a></div><div id=pingResult class=pingBox style="margin-top:10px;padding:10px;background:#0f1424;border-radius:8px;min-height:40px">جاهز</div><textarea id=pingBatchInput placeholder="ضع كل IP في سطر" style="width:100%;height:100px;margin-top:8px;background:#0f1424;border:1px solid var(--border);color:#fff;border-radius:8px;padding:8px"></textarea></div>
<script>
window.doPing = async function() {
  event.preventDefault();
  let ip = document.getElementById('pingIp').value.trim();
  if(!ip) return;
  let out = document.getElementById('pingResult');
  out.textContent = 'يفحص...';
  try { let r = await fetch('/api/ping?ip=' + encodeURIComponent(ip)); let j = await r.json(); out.textContent = j.out; } catch { out.textContent = 'خطأ'; }
};
window.doPingBatch = async function() {
  event.preventDefault();
  let txt = document.getElementById('pingBatchInput').value.trim();
  let ips = txt.split('\n').map(s => s.trim()).filter(Boolean);
  if(!ips.length) { ips = [document.getElementById('pingIp').value.trim()].filter(Boolean); }
  if(!ips.length) return;
  let out = document.getElementById('pingResult');
  out.textContent = 'يفحص ' + ips.length + ' IP بـ 20 عامل...';
  try {
    let r = await fetch('/api/ping_batch', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ips: ips})});
    let j = await r.json();
    let html = '';
    for(let k in j.results) { html += k + ' => ' + j.results[k] + '\n'; }
    out.textContent = html;
  } catch { out.textContent = 'خطأ جماعي'; }
};
</script>
"""
    if v == 'logs':
        rs = qall("SELECT * FROM logs ORDER BY id DESC LIMIT 500")
        rows = "".join([f"<tr id=log-{r.get('id')}><td>{esc(r.get('time',''))}</td><td>{esc(r.get('user_phone',''))}</td><td><b style='color:var(--accent)'>{esc(r.get('username') or '')}</b></td><td><span class=badge>{esc(r.get('action',''))}</span></td><td>{esc(r.get('target',''))}</td><td>{esc(r.get('detail',''))}</td></tr>" for r in rs]) or "<tr><td colspan=6>لا يوجد سجل</td></tr>"
        return f"""
<div class=card><div class=row style="justify-content:space-between"><b>📜 السجل الكامل - 5 أعمدة + تفصيل</b><div class=row><input id=logFilter placeholder="بحث..." oninput="event.preventDefault(); filterTable(this.value, 'logsTable')" style="width:150px"><a href="#" class=btn-gold onclick="event.preventDefault(); clearLogs()" style="background:#ef4444;text-decoration:none">مسح</a><a href="#" class=btn-gold onclick="event.preventDefault(); window.open('/api/export/logs','_blank')" style="text-decoration:none">تصدير</a></div></div><div style="overflow:auto;max-height:70vh"><table id=logsTable style="width:100%;margin-top:8px"><thead><tr><th>وقت</th><th>هاتف</th><th>المستخدم</th><th>عمل</th><th>الهدف</th><th>تفصيل</th></tr></thead><tbody>{rows}</tbody></table></div></div>
<script>
window.clearLogs = async () => {{
  event.preventDefault();
  if(!confirm("مسح؟")) return;
  await fetch("/api/clear_logs", {{method: "POST"}});
  loadPage("logs", true);
}};
</script>
"""
    if v == 'subs':
        rs = qall("SELECT * FROM subs ORDER BY name ASC LIMIT 100")
        rows = "".join([f"<tr id=sub-{r.get('id')}><td>{esc(r.get('name') or '')}</td><td>{esc(r.get('phone') or '')}</td><td>{esc(r.get('note') or '')}</td><td><a href='#' class='sq-btn del' onclick="event.preventDefault(); openDeleteModal('/del_sub/{r.get('id')}',{r.get('id')},'{esc(r.get('name') or 'مشترك')}')" style='text-decoration:none'>🗑 حذف</a></td></tr>" for r in rs])
        return f"""
<div class=card><div class=row style="justify-content:space-between"><b>👥 المشتركين</b><div class=row><input id=subFilter placeholder="بحث..." oninput="event.preventDefault(); filterTable(this.value, 'subsTable')"><a href="#" class=btn-gold onclick="event.preventDefault(); document.getElementById('fSub').style.display='flex'" style="text-decoration:none">+ إضافة</a></div></div><form id=fSub class=row style="display:none;margin-top:8px"><input name=name placeholder="اسم" required style="flex:1"><input name=phone placeholder="رقم" style="flex:1"><input name=note placeholder="ملاحظة" style="flex:1"><button class=btn-gold>+</button></form><div style="overflow:auto"><table id=subsTable style="width:100%;margin-top:8px"><thead><tr><th>اسم</th><th>رقم</th><th>ملاحظة</th><th></th></tr></thead><tbody>{rows}</tbody></table></div></div>
<script>
document.getElementById("fSub").addEventListener("submit", async e => {{
  e.preventDefault();
  let r = await fetch("/add_sub", {{method: "POST", body: new FormData(e.target)}});
  let j = await r.json();
  if(j.ok) loadPage('subs', true);
}});
</script>
"""
    if v == 'ledger':
        rs = qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 100")
        rows = "".join([f"<tr id=led-{r.get('id')}><td>{esc(r.get('name') or '')}</td><td>{r.get('amount')}</td><td>{esc(r.get('note') or '')}</td><td>{esc(r.get('currency') or '')}</td><td><a href='#' class='sq-btn del' onclick="event.preventDefault(); openDeleteModal('/del_ledger/{r.get('id')}',{r.get('id')},'حساب')" style='text-decoration:none'>🗑</a></td></tr>" for r in rs])
        return f"""
<div class=card><div class=row style="justify-content:space-between"><b>📒 الحسابات</b><a href="#" class=btn-gold onclick="event.preventDefault(); document.getElementById('fLed').style.display='flex'" style="text-decoration:none">+ إضافة</a></div><form id=fLed class=row style="display:none;margin-top:8px"><input name=name placeholder="اسم" required style="flex:1"><input name=amount type=number step=0.01 placeholder="مبلغ" required style="flex:1"><input name=note placeholder="ملاحظة" style="flex:1"><select name=currency><option>USD</option><option>SYP</option></select><button class=btn-gold>+</button></form><table style="width:100%;margin-top:8px"><thead><tr><th>اسم</th><th>مبلغ</th><th>ملاحظة</th><th>عملة</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>
<script>
document.getElementById("fLed").addEventListener("submit", async e => {{
  e.preventDefault();
  let r = await fetch("/add_ledger", {{method: "POST", body: new FormData(e.target)}});
  let j = await r.json();
  if(j.ok) loadPage('ledger', true);
}});
</script>
"""
    if v == 'network':
        dishes = qall("SELECT * FROM dish_ips ORDER BY dish_name ASC LIMIT 100")
        cards = "".join([f'''<div class="card ip-card" id="net-{d.get('id')}" data-ip="{esc(d.get('ip') or '')}" style="transition:transform .2s" onmouseover="this.style.transform='translateY(-3px)'" onmouseout="this.style.transform='none'"><div style="display:flex;justify-content:space-between"><b style="font-size:12px">{esc(d.get('dish_name') or '')}</b><a href="#" class="sq-btn view" onclick="event.preventDefault(); window.open('http://{esc(d.get('ip') or '')}','_blank')" style="text-decoration:none">👁</a></div><div style="margin-top:6px;display:flex;gap:6px;align-items:center"><span class=ip onclick="event.preventDefault(); window.open('http://{esc(d.get('ip') or '')}','_blank')">{esc(d.get('ip') or '')}</span> <span class="net-out" style="font-size:10px">...</span></div><div style="margin-top:6px;display:flex;gap:6px"><a href="#" class="sq-btn edit" onclick="event.preventDefault(); openEditDish({d.get('id')})" style="text-decoration:none">✏</a><a href="#" class="sq-btn del" onclick="event.preventDefault(); openDeleteModal('/del_dish/{d.get('id')}',{d.get('id')},'{esc(d.get('ip') or '')}')" style="text-decoration:none">🗑</a></div></div>''' for d in dishes])
        return f"""
<div class=card><div class=row style="justify-content:space-between"><b>📊 الشبكة - شبكة عمودين</b><div class=row><a href="#" class=btn-gold onclick="event.preventDefault(); checkAll()" style="text-decoration:none">فحص الكل 20 worker</a><a href="#" class=btn-gold onclick="event.preventDefault(); window.open('/api/export/dishes','_blank')" style="text-decoration:none">تصدير</a></div></div><div style="display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-top:10px" id=networkGrid>{cards}</div></div>
<script>
window.checkAll = async () => {{
  event.preventDefault();
  let ips = [];
  document.querySelectorAll("[id^=net-]").forEach(c => ips.push(c.dataset.ip));
  if(!ips.length) return;
  try {{
    let r = await fetch("/api/ping_batch", {{method:"POST", headers:{{"Content-Type":"application/json"}}, body: JSON.stringify({{ips: ips}})}});
    let j = await r.json();
    for(let c of document.querySelectorAll("[id^=net-]")) {{
      let ip = c.dataset.ip;
      if(j.results && j.results[ip]) c.querySelector(".net-out").textContent = j.results[ip];
    }}
  }} catch {{
    for(let c of document.querySelectorAll("[id^=net-]")) {{
      try {{ let r = await fetch("/api/ping?ip=" + c.dataset.ip); let j = await r.json(); c.querySelector(".net-out").textContent = j.out; }} catch {{}} 
      await new Promise(r => setTimeout(r, 50));
    }}
  }}
}};
</script>
"""
    if v == 'settings':
        us = qall("SELECT * FROM users ORDER BY phone ASC")
        cards = "".join([f"<div class='card' id=user-{esc(u.get('phone') or '')}><b>{esc(u.get('username') or u.get('phone') or '')}</b><br>{esc(u.get('phone') or '')} <span class=badge>{esc(u.get('role') or '')}</span><br><div style='margin-top:6px;display:flex;gap:6px'><a href='#' class='sq-btn del' onclick="event.preventDefault(); openDeleteModal('/del_user/{esc(u.get('phone') or '')}',0,'{esc(u.get('phone') or '')}')" style='text-decoration:none'>حذف</a></div></div>" for u in us])
        return f"""
<div style="max-width:1100px;margin:0 auto"><div class=card><h4>🔑 تغيير كلمة المرور</h4><form id=formPass class=row><input name=newpass type=password placeholder="كلمة المرور الجديدة" required style="flex:1"><button class=btn-gold>حفظ</button></form></div><div class=card style="margin-top:12px"><b>👥 اليوزرات</b><div style="display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-top:8px">{cards}</div></div></div>
<script>
document.getElementById("formPass").addEventListener("submit", async e => {{
  e.preventDefault();
  let r = await fetch("/change_pass", {{method: "POST", body: new FormData(e.target)}});
  let j = await r.json();
  if(j.ok) e.target.reset();
}});
</script>
"""
    return "<div class=card>404</div>"

def layout(c, v='home'):
    th = session.get('theme', 'dark')
    is_dark = (th == 'dark')
    cur_user = qone("SELECT * FROM users WHERE phone=?", (session.get('phone') or '',)) or {}
    lang = session.get('lang', 'ar')
    tr = {
      'ar': {'home': 'الرئيسية', 'towers': 'الأبراج', 'dishes': 'الصحون', 'map': 'الخريطة', 'ping': 'البنج', 'network': 'الشبكة', 'subs': 'المشتركين', 'ledger': 'الحسابات', 'logs': 'السجل', 'settings': 'الإعدادات', 'logout': 'خروج', 'support': 'الدعم الفني'},
      'en': {'home': 'Home', 'towers': 'Towers', 'dishes': 'Dishes', 'map': 'Map', 'ping': 'Ping', 'network': 'Network', 'subs': 'Subs', 'ledger': 'Ledger', 'logs': 'Logs', 'settings': 'Settings', 'logout': 'Logout', 'support': 'Support'}
    }[lang if lang in ['ar', 'en'] else 'ar']
    return f"""
<html dir={'rtl' if lang=='ar' else 'ltr'}><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>OMAIA ISP FINAL FIXED</title>
<style>
:root{{--card-min:160px; --icon-size:44px; --accent:#ffbe4d; --card-bg-dark:rgba(30,36,51,0.85); --card-bg-light:#ffffffcc; --text-dark:#ffffff; --text-light:#0f172a; --border-dark:rgba(255,255,255,0.12); --border-light:#e2e8f0}}
*{{box-sizing:border-box;font-family:system-ui}}html,body{{margin:0;padding:0}}
body.dark{{--bg:radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 60%, #070a1f 100%); --card-bg:var(--card-bg-dark); --text:var(--text-dark); --border:var(--border-dark)}} 
body.light{{--bg:#eef2f7; --card-bg:var(--card-bg-light); --text:var(--text-light); --border:var(--border-light)}}
body{{background:var(--bg);color:var(--text);overflow-x:hidden}}
#topLoader{{position:fixed;top:0;left:0;height:3px;background:linear-gradient(90deg,var(--accent),#ffb020);width:0%;z-index:9999;transition:width .25s ease}}
.card{{background:var(--card-bg);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);color:var(--text);padding:12px;border-radius:16px;margin-bottom:10px;border:1px solid var(--border);box-shadow:0 8px 24px #0003}}
.tower-accordion{{border-radius:16px;overflow:hidden;border:1px solid #ffffff12;backdrop-filter:blur(20px)}}
.tower-accordion-body{{max-height:0;overflow:hidden;opacity:0;transition:max-height .35s ease, opacity .28s ease;background:#0f1424cc}}
.tower-accordion-body.open{{max-height:4000px;opacity:1}}
.top{{position:fixed;top:0;left:0;right:0;height:56px;background:var(--card-bg);backdrop-filter:blur(20px) saturate(180%);-webkit-backdrop-filter:blur(20px) saturate(180%);display:flex;align-items:center;justify-content:space-between;padding:0 12px;z-index:1003;border-bottom:1px solid var(--border)}}
.sidebar{{position:fixed;top:0;right:0;width:320px;height:100vh;background:var(--card-bg);backdrop-filter:blur(20px) saturate(180%);-webkit-backdrop-filter:blur(20px) saturate(180%);z-index:1002;padding-top:60px;transform:translateX(110%);transition:transform .25s ease;overflow-y:auto;border-left:1px solid var(--border);border-radius:24px 0 0 24px}}
.sidebar.active{{transform:none}}
.sidebar a{{display:flex;align-items:center;gap:12px;padding:14px 16px;margin:6px 12px;color:var(--text);text-decoration:none;border-radius:12px;background:rgba(255,255,255,0.06);font-size:14px;font-weight:600;transition:transform .2s}}
.sidebar a:hover{{transform:translateY(-2px)}}
.sidebar a.active{{background:var(--accent);color:#111}}
.menu-icon-circle{{width:34px;height:34px;border-radius:50%;background:linear-gradient(135deg,var(--accent),#ffb020);display:flex;align-items:center;justify-content:center;font-size:16px;flex-shrink:0;box-shadow:0 2px 8px #0003}}
#overlay{{position:fixed;inset:0;background:#0006;z-index:1001;display:none}} #overlay.show{{display:block}}
.main{{margin-top:62px;padding:10px;min-height:90vh}}
.row{{display:flex;gap:6px;align-items:center;flex-wrap:wrap}}
.btn-gold{{background:linear-gradient(90deg,var(--accent),#ffb020);color:#111;padding:7px 12px;border:0;border-radius:10px;font-weight:700;font-size:11px;cursor:pointer;text-decoration:none;display:inline-block}}
.sq-btn{{
  backdrop-filter:blur(20px);
  -webkit-backdrop-filter:blur(20px);
  border:1px solid rgba(255,255,255,0.18);
  padding:6px 12px;
  border-radius:20px;
  font-size:11px;
  font-weight:700;
  cursor:pointer;
  display:inline-flex;
  align-items:center;
  justify-content:center;
  box-shadow:0 4px 12px rgba(0,0,0,0.15), inset 0 1px 0 rgba(255,255,255,0.2);
  transition:all .2s cubic-bezier(0.34,1.56,0.64,1);
  text-decoration:none;
}}
.sq-btn:hover{{transform:translateY(-2px) scale(1.05)}}
.sq-btn:active{{transform:scale(0.9)}}
.sq-btn.edit{{background:rgba(245,158,11,0.18);color:#ffbe4d;border-color:rgba(245,158,11,0.35);box-shadow:0 0 15px rgba(245,158,11,0.25), inset 0 1px 0 rgba(255,255,255,0.2)}}
.sq-btn.del{{background:rgba(239,68,68,0.18);color:#ff6b6b;border-color:rgba(239,68,68,0.35);box-shadow:0 0 15px rgba(239,68,68,0.25), inset 0 1px 0 rgba(255,255,255,0.2)}}
.sq-btn.view{{background:rgba(34,197,94,0.18);color:#4ade80;border-color:rgba(34,197,94,0.35);box-shadow:0 0 15px rgba(34,197,94,0.25), inset 0 1px 0 rgba(255,255,255,0.2)}}
.ip{{background:#000;color:var(--accent);padding:2px 6px;border-radius:5px;font-family:monospace;font-size:10px;cursor:pointer}} .badge{{background:var(--accent);color:#111;padding:2px 6px;border-radius:6px;font-size:10px;font-weight:700}}
table{{width:100%;border-collapse:collapse}} th{{background:rgba(255,255,255,0.06);padding:8px;font-size:11px;text-align:right}} td{{padding:8px;border-bottom:1px solid var(--border)}}
#editModal{{position:fixed;inset:0;background:#0008;display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:opacity .25s, transform .25s;z-index:2000;transform:scale(0.96)}} #editModal.show{{opacity:1;pointer-events:auto;transform:scale(1)}} #editBox{{background:var(--card-bg);backdrop-filter:blur(20px);color:var(--text);padding:18px;border-radius:16px;width:92%;max-width:420px;border:1px solid var(--border);box-shadow:0 20px 60px #0006}}
.skeleton{{height:80px;background:linear-gradient(90deg, rgba(255,255,255,0.06) 25%, rgba(255,255,255,0.12) 50%, rgba(255,255,255,0.06) 75%);background-size:200% 100%;animation:skeleton 1.2s infinite;border-radius:12px}}
@keyframes skeleton{{0%{{background-position:200% 0}}100%{{background-position:-200% 0}}}}
input,select{{padding:9px 11px;border-radius:10px;border:1px solid var(--border);background:rgba(255,255,255,0.06);color:var(--text);font-size:12px;backdrop-filter:blur(10px)}}
.grid-small{{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}}
@media(max-width:640px){{.grid-small{{grid-template-columns:repeat(2,1fr)}}}}
.wa-float{{position:fixed;bottom:18px;left:18px;width:32px;height:32px;background:#25D366;color:#fff;border-radius:50%;display:flex;align-items:center;justify-content:center;text-decoration:none;z-index:999;font-size:14px;box-shadow:0 4px 14px #0005, 0 0 15px rgba(37,211,102,0.4);transition:transform .2s}}
.wa-float:hover{{transform:translateY(-2px) scale(1.08)}}
.stat{{text-align:center;cursor:pointer}} .ico{{font-size:20px}}
</style></head><body class="{'dark' if is_dark else 'light'}">
<div id=topLoader></div>
<div id=overlay onclick="event.preventDefault(); toggleSb(false)"></div>
<div class=sidebar id=sb>
<div style='padding:0 16px 14px;border-bottom:1px solid var(--border);display:flex;gap:10px;align-items:center'><div class=menu-icon-circle>🚀</div><div><b style="font-size:16px">OMAIA <span style='color:var(--accent)'>ISP FINAL</span></b><br><small style="font-size:11px;opacity:.7">{esc(cur_user.get('username') or '')} • {esc(cur_user.get('role') or '')}</small></div></div>
<a href="#" onclick="event.preventDefault(); loadPage('home')" id=nav-home><span class=menu-icon-circle>🏠</span><span>{tr['home']}</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('towers')" id=nav-towers><span class=menu-icon-circle>🗼</span><span>{tr['towers']}</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('dishes')" id=nav-dishes><span class=menu-icon-circle>📡</span><span>{tr['dishes']}</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('map')" id=nav-map><span class=menu-icon-circle>🗺</span><span>{tr['map']}</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('ping')" id=nav-ping><span class=menu-icon-circle>📶</span><span>{tr['ping']}</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('network')" id=nav-network><span class=menu-icon-circle>📊</span><span>{tr['network']}</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('subs')" id=nav-subs><span class=menu-icon-circle>👥</span><span>{tr['subs']}</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('ledger')" id=nav-ledger><span class=menu-icon-circle>📒</span><span>{tr['ledger']}</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('logs')" id=nav-logs><span class=menu-icon-circle>📜</span><span>{tr['logs']}</span></a>
<a href="#" onclick="event.preventDefault(); loadPage('settings')" id=nav-settings><span class=menu-icon-circle>⚙</span><span>{tr['settings']}</span></a>
<div style='padding:14px 16px;margin-top:12px;border-top:1px dashed var(--border)'>
<div style='font-size:12px;font-weight:700;margin-bottom:10px'>💬 {tr['support']}</div>
<div style='display:flex;gap:8px;justify-content:center;align-items:center'>
<a href="#" onclick="event.preventDefault(); openLink('{SUPPORT_WA_LINK}')" title="واتساب" style="width:32px;height:32px;background:#25D366;color:#fff;border-radius:50%;display:flex;align-items:center;justify-content:center;text-decoration:none;font-size:14px;box-shadow:0 4px 12px #0004, 0 0 10px rgba(37,211,102,0.35)">W</a>
<a href="#" onclick="event.preventDefault(); openLink('{SUPPORT_INSTA_LINK}')" title="انستغرام" style="width:32px;height:32px;background:linear-gradient(45deg,#feda75,#d62976);color:#fff;border-radius:50%;display:flex;align-items:center;justify-content:center;text-decoration:none;font-size:14px;box-shadow:0 4px 12px #0004">I</a>
</div>
<div style='font-size:11px;opacity:.7;margin-top:10px;text-align:center'>+{SUPPORT_WA}<br>{SUPPORT_INSTA}</div>
</div>
<a href="#" onclick="event.preventDefault(); logoutFast()" style='margin:12px;background:rgba(239,68,68,0.12);display:flex;gap:12px;border:1px solid rgba(239,68,68,0.25);padding:14px 16px;border-radius:12px;text-decoration:none;color:var(--text)'><span class=menu-icon-circle style="background:#ef4444">🚪</span><span>{tr['logout']}</span></a>
</div>

<div class=top>
<div class=row><a href="#" onclick="event.preventDefault(); toggleSb()" style='font-size:18px;cursor:pointer;padding:6px 12px;background:rgba(255,255,255,0.08);border-radius:10px;text-decoration:none;color:var(--text);backdrop-filter:blur(10px);border:1px solid var(--border)'>☰</a></div>
<b style="font-size:15px;display:flex;align-items:center;gap:8px"><span class=menu-icon-circle>🚀</span> OMAIA <span style='color:var(--accent)'>ISP FINAL FIXED</span></b>
<div class=row>
<a href="#" onclick="event.preventDefault(); toggleLangFast()" style="width:34px;height:34px;background:rgba(255,255,255,0.08);border:1px solid var(--border);color:var(--text);border-radius:50%;cursor:pointer;display:flex;align-items:center;justify-content:center;text-decoration:none;backdrop-filter:blur(10px)">🌐</a>
<a href="#" onclick="event.preventDefault(); toggleTheme()" style="width:34px;height:34px;background:rgba(255,255,255,0.08);border:1px solid var(--border);color:var(--text);border-radius:50%;cursor:pointer;display:flex;align-items:center;justify-content:center;text-decoration:none;backdrop-filter:blur(10px)">🌓</a>
</div>
</div>

<div class=main id=mn>{c}</div>

<div id=editModal><div id=editBox><div class=row style='justify-content:space-between;margin-bottom:12px'><b id=editModalTitle style='font-size:14px'>نافذة</b><a href="#" onclick="event.preventDefault(); closeEditModal()" style='width:30px;height:30px;border-radius:50%;background:rgba(255,255,255,0.08);border:1px solid var(--border);color:var(--text);display:flex;align-items:center;justify-content:center;text-decoration:none'>✕</a></div><div id=editBody></div></div></div>

<a href="#" onclick="event.preventDefault(); openLink('{SUPPORT_WA_LINK}')" class=wa-float>W</a>
<script>
let cur = '{v}';
let pageCache = {{}};
function escHtml(s) {{ return (s || '').toString().replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }}
function topLoad(p) {{
  let el = document.getElementById('topLoader');
  if(!el) return;
  el.style.width = p + '%';
  if(p >= 100) setTimeout(() => {{ el.style.width = '0%'; }}, 400);
}}
function openLink(url) {{
  event.preventDefault();
  if(!url || url.includes('PLACEHOLDER')) {{ alert('يرجى استبدال PLACEHOLDER بالرابط الحقيقي'); return; }}
  window.open(url, '_blank');
}}
function toggleSb(f) {{
  event.preventDefault();
  let sb = document.getElementById('sb'), ov = document.getElementById('overlay');
  let o = f !== undefined ? f : !sb.classList.contains('active');
  sb.classList.toggle('active', o);
  ov.classList.toggle('show', o);
}}
function filterTable(q, tableId) {{
  q = (q || '').toLowerCase();
  let tbl = document.getElementById(tableId);
  if(!tbl) return;
  tbl.querySelectorAll('tbody tr').forEach(tr => {{
    let txt = tr.textContent.toLowerCase();
    tr.style.display = txt.includes(q) ? '' : 'none';
  }});
}}
function filterCards(q, gridId) {{
  q = (q || '').toLowerCase();
  let grid = document.getElementById(gridId);
  if(!grid) return;
  grid.querySelectorAll('.card').forEach(card => {{
    let txt = (card.dataset.name || '') + ' ' + (card.dataset.area || '') + ' ' + card.textContent.toLowerCase();
    card.style.display = txt.includes(q) ? '' : 'none';
  }});
}}
async function loadPage(v, force = false) {{
  event.preventDefault();
  cur = v;
  toggleSb(false);
  document.querySelectorAll('.sidebar a').forEach(a => a.classList.remove('active'));
  let n = document.getElementById('nav-' + v);
  if(n) n.classList.add('active');
  let mn = document.getElementById('mn');
  if(pageCache[v] && !force) {{
    mn.innerHTML = pageCache[v];
    execScripts();
    return;
  }}
  mn.innerHTML = '<div class=skeleton style="height:120px"></div><div style="text-align:center;padding:20px;opacity:.6">جاري التحميل...</div>';
  topLoad(30);
  try {{
    let r = await fetch('/api/page?v=' + v, {{cache: 'no-store'}});
    topLoad(70);
    let h = await r.text();
    pageCache[v] = h;
    mn.innerHTML = h;
    topLoad(100);
    execScripts();
  }} catch {{
    mn.innerHTML = '<div class=card>خطأ بالتحميل</div>';
    topLoad(100);
  }}
}}
function execScripts() {{
  document.getElementById('mn').querySelectorAll('script').forEach(o => {{
    let s = document.createElement('script');
    s.textContent = o.textContent;
    document.body.appendChild(s);
    o.remove();
  }});
}}
window.closeEditModal = () => {{
  event.preventDefault();
  let m = document.getElementById('editModal');
  m.style.transform = 'scale(0.96)';
  m.style.opacity = '0';
  setTimeout(() => {{
    m.classList.remove('show');
    m.style.transform = 'scale(1)';
    m.style.opacity = '1';
  }}, 200);
}};
window.openDeleteModal = function(url, id, name) {{
  event.preventDefault();
  let displayName = name || 'هذا العنصر';
  let isTower = url.includes('tower');
  let label = isTower ? 'تأكيد حذف البرج: ' + escHtml(displayName) + '؟' : 'تأكيد حذف: ' + escHtml(displayName) + '؟';
  let b = document.getElementById("editBody");
  b.innerHTML = '<div style="text-align:center;padding:10px"><h3 style="font-size:14px">' + label + '</h3><div style="display:flex;gap:8px;margin-top:14px"><a href="#" onclick="event.preventDefault(); closeEditModal()" style="flex:1;padding:10px;background:transparent;border:1px solid var(--border);color:var(--text);border-radius:10px;text-align:center;text-decoration:none">تراجع</a><a href="#" id=delConfirmBtn style="flex:1;padding:10px;background:#ef4444;color:#fff;border:0;border-radius:10px;text-align:center;text-decoration:none">حذف</a></div></div>';
  document.getElementById("editModalTitle").textContent = "تأكيد الحذف";
  document.getElementById("editModal").classList.add("show");
  document.getElementById("delConfirmBtn").onclick = async (e) => {{
    e.preventDefault();
    try {{
      let r = await fetch(url, {{method: url.includes('del_') && !url.includes('/api/') ? 'GET' : 'POST'}});
      let j = await r.json();
      if(j.ok) {{
        closeEditModal();
        // DOM remove instead of full reload
        let el = document.getElementById('tower-' + id) || document.getElementById('tower-acc-' + id) || document.getElementById('net-' + id) || document.getElementById('sub-' + id) || document.getElementById('led-' + id) || document.getElementById('log-' + id);
        if(el) {{
          el.style.transform = 'scale(0.9)';
          el.style.opacity = '0';
          setTimeout(() => el.remove(), 250);
        }} else {{
          loadPage(cur, true);
        }}
        pageCache = {{}};
      }} else alert(j.msg);
    }} catch(err) {{ alert(err); }}
  }};
}};
window.toggleLangFast = async () => {{
  event.preventDefault();
  try {{ let r = await fetch('/toggle_lang'); let j = await r.json(); location.reload(); }} catch {{}}
}};
window.toggleTheme = async () => {{
  event.preventDefault();
  try {{
    let r = await fetch('/api/toggle_theme', {{method:'POST'}});
    let j = await r.json();
    document.body.className = j.theme;
    localStorage.setItem('theme', j.theme);
  }} catch {{
    let cur = document.body.classList.contains('dark') ? 'dark' : 'light';
    let nxt = cur === 'dark' ? 'light' : 'dark';
    document.body.className = nxt;
  }}
}};
window.logoutFast = async () => {{
  event.preventDefault();
  try {{ await fetch('/api/logout', {{method: 'POST'}}); }} catch {{}}
  location.replace('/login');
}};
loadPage(cur, true);
</script></body></html>
"""

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)), debug=False)
