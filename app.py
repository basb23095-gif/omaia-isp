from flask import Flask, request, redirect, session, jsonify, render_template_string
import os, datetime, html, subprocess, platform, ipaddress
try:
    import psycopg2, psycopg2.extras
    HAS_PG = True
except:
    HAS_PG = False

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "omia-secure-key-2026")
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

def esc(s): return html.escape(str(s or ''), quote=True)

def db_connect():
    if not DATABASE_URL: return None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require', connect_timeout=5)
        conn.autocommit = True; return conn
    except: return None

def qall(q, a=()):
    conn = db_connect()
    if not conn: return []
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(q.replace("?", "%s"), a); rs = [dict(r) for r in cur.fetchall()]
        cur.close(); conn.close(); return rs
    except:
        if conn: conn.close()
        return []

def qone(q, a=()):
    r = qall(q, a); return r if r else None

def qexec(q, a=()):
    conn = db_connect()
    if not conn: return
    try:
        cur = conn.cursor(); cur.execute(q.replace("?", "%s"), a)
        cur.close(); conn.close()
    except:
        if conn: conn.close()

def log_activity(action):
    u, p = session.get('username', 'زائر'), session.get('phone', 'بدون هاتف')
    dt = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    qexec("INSERT INTO activity_logs (username, phone, action, dt) VALUES (?,?,?,?)", (u, p, action, dt))

def init_supabase_tables():
    if not DATABASE_URL: return
    qexec("CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY, password TEXT, role TEXT, username TEXT, active INT DEFAULT 1)")
    qexec("CREATE TABLE IF NOT EXISTS subs(id SERIAL PRIMARY KEY, name TEXT, phone TEXT, active INT DEFAULT 1)")
    qexec("CREATE TABLE IF NOT EXISTS dish_ips(id SERIAL PRIMARY KEY, ip TEXT, dish_name TEXT)")
    qexec("CREATE TABLE IF NOT EXISTS towers(id SERIAL PRIMARY KEY, name TEXT, lat REAL, lng REAL, location TEXT, is_fixed INT DEFAULT 0)")
    qexec("CREATE TABLE IF NOT EXISTS activity_logs(id SERIAL PRIMARY KEY, username TEXT, phone TEXT, action TEXT, dt TEXT)")
    if not qone("SELECT * FROM users WHERE phone=?", ('05344851045',)):
        qexec("INSERT INTO users(phone, password, role, username, active) VALUES(?,?,?,?,?)", ('05344851045', 'admin2024', 'manager', 'admin', 1))
    if not qone("SELECT * FROM towers WHERE is_fixed=1"):
        qexec("INSERT INTO towers(name, lat, lng, location, is_fixed) VALUES(?,?,?,?,?)", ('البرج الرئيسي الثابت', 35.1318, 36.7578, 'حماة', 1))

@app.before_request
def setup_tables():
    if not hasattr(app, '_tables_initialized'):
        init_supabase_tables(); app._tables_initialized = True

@app.route('/')
def index():
    if not session.get('phone'): return redirect('/login')
    return render_template_string(BASE_HTML)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form.get('username', '').strip()
        p = request.form.get('phone', '').strip()
        pwd = request.form.get('password', '')
        if not DATABASE_URL: return render_template_string(LOGIN_HTML, error="لم يتم ضبط DATABASE_URL")
        user = qone("SELECT * FROM users WHERE username=? AND phone=? AND password=?", (u, p, pwd))
        if user:
            session['phone'], session['username'] = user['phone'], user['username']
            log_activity("سجل دخوله للموقع"); return redirect('/')
        return render_template_string(LOGIN_HTML, error="بيانات الدخول غير صحيحة")
    return render_template_string(LOGIN_HTML, error=None)

@app.route('/logout')
def logout():
    log_activity("سجل خروجه من الموقع"); session.clear(); return redirect('/login')

@app.route('/api/data')
def get_site_data():
    if not session.get('phone'): return jsonify(error="Unauth"), 401
    ns = (qone("SELECT COUNT(*) as c FROM subs") or {}).get('c', 0)
    nd = (qone("SELECT COUNT(*) as c FROM dish_ips") or {}).get('c', 0)
    nt = (qone("SELECT COUNT(*) as c FROM towers") or {}).get('c', 0)
    return jsonify(kpis={'subs': ns, 'dishes': nd, 'towers': nt}, subs=qall("SELECT * FROM subs ORDER BY id DESC"), dishes=qall("SELECT * FROM dish_ips ORDER BY id DESC"), towers=qall("SELECT * FROM towers ORDER BY id DESC"), logs=qall("SELECT * FROM activity_logs ORDER BY id DESC LIMIT 50"))

@app.route('/api/subs/add', methods=['POST'])
def add_sub():
    n, p = request.form.get('name', '').strip(), request.form.get('phone', '').strip()
    if n: qexec("INSERT INTO subs (name, phone) VALUES (?,?)", (n, p)); log_activity(f"أضاف المشترك: {n}")
    return jsonify(ok=True)

@app.route('/api/subs/delete/<int:id>', methods=['POST'])
def del_sub(id):
    s = qone("SELECT name FROM subs WHERE id=?", (id,))
    if s: qexec("DELETE FROM subs WHERE id=?", (id,)); log_activity(f"حذف المشترك: {s['name']}")
    return jsonify(ok=True)

@app.route('/api/dishes/add', methods=['POST'])
def add_dish():
    n, ip = request.form.get('dish_name', '').strip(), request.form.get('ip', '').strip()
    try:
        ipaddress.ip_address(ip)
        qexec("INSERT INTO dish_ips (dish_name, ip) VALUES (?,?)", (n, ip)); log_activity(f"أضاف صحن: {n}")
        return jsonify(ok=True)
    except: return jsonify(ok=False, msg="عنوان IP غير صالح!")

@app.route('/api/dishes/delete/<int:id>', methods=['POST'])
def del_dish(id):
    d = qone("SELECT dish_name FROM dish_ips WHERE id=?", (id,))
    if d: qexec("DELETE FROM dish_ips WHERE id=?", (id,)); log_activity(f"حذف الصحن: {d['dish_name']}")
    return jsonify(ok=True)

@app.route('/api/towers/add', methods=['POST'])
def add_tower():
    n, l = request.form.get('name', '').strip(), request.form.get('location', '').strip()
    lat, lng = float(request.form.get('lat', 0) or 0), float(request.form.get('lng', 0) or 0)
    if n: qexec("INSERT INTO towers (name, location, lat, lng) VALUES (?,?,?,?)", (n, l, lat, lng)); log_activity(f"أضاف برج: {n}")
    return jsonify(ok=True)

@app.route('/api/towers/delete/<int:id>', methods=['POST'])
def del_tower(id):
    t = qone("SELECT * FROM towers WHERE id=?", (id,))
    if t:
        if t.get('is_fixed') == 1: return jsonify(ok=False, msg="لا يمكن حذف النقطة الثابتة!")
        qexec("DELETE FROM towers WHERE id=?", (id,)); log_activity(f"حذف البرج: {t['name']}")
    return jsonify(ok=True)

@app.route('/api/ping')
def api_ping():
    ip = request.args.get('ip', '').strip()
    try:
        ipaddress.ip_address(ip)
        w = platform.system().lower() == 'windows'
        cmd = ['ping', '-n', '2', ip] if w else ['ping', '-c', '2', '-W', '2', ip]
        o = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return jsonify(ok=True, out=((o.stdout or '') + (o.stderr or ''))[:1000])
    except: return jsonify(ok=False, out='IP غير صحيح')

LOGIN_HTML = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head><meta charset="UTF-8"><title>Login</title><link rel="stylesheet" href="https://jsdelivr.net"></head>
<body style="background:#0f172a; display:flex; justify-content:center; align-items:center; height:100vh; margin:0;">
    <article style="background:#1e293b; width:100%; max-width:360px; border:none; padding:25px;">
        <h3 style="color:#38bdf8; text-align:center;">دخول لوحة التحكم</h3>
        {% if error %} <p style="color:#f87171; text-align:center;">{{ error }}</p> {% endif %}
        <form method="POST">
            <input type="text" name="username" placeholder="User" required style="background:#0f172a; color:white;">
            <input type="text" name="phone" placeholder="Phone" required style="background:#0f172a; color:white;">
            <input type="password" name="password" placeholder="Password" required style="background:#0f172a; color:white;">
            <button type="submit" style="background:#2563eb; border:none;">دخول</button>
        </form>
    </article>
</body>
</html>
"""

BASE_HTML = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8"><title>لوحة التحكم</title>
    <link rel="stylesheet" href="https://jsdelivr.net">
    <link rel="stylesheet" href="https://unpkg.com" />
    <style>
        body { background:#0f172a; color:#f8fafc; } header, article { background:#1e293b !important; border:none !important; }
        .sidebar { position:fixed; top:0; right:-280px; width:280px; height:100%; background:#1e293b; z-index:1000; transition:0.3s; padding-top:60px; }
        .sidebar.open { right:0; } .sidebar a { display:block; padding:15px; color:white; cursor:pointer; border-bottom:1px solid #334155; }
        .overlay { position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.6); display:none; z-index:999; }
        .overlay.active { display:block; } .page-section { display:none; } .page-section.active { display:block; }
        #map { height:380px; border-radius:12px; margin-top:15px; }
    </style>
</head>
<body>
    <div id="overlay" onclick="toggleMenu()" class="overlay"></div>
    <header class="container-fluid" style="display:flex; justify-content:space-between; align-items:center;">
        <button onclick="toggleMenu()" style="background:none; border:none; color:white; font-size:24px; width:auto; margin:0;">☰ القائمة</button>
        <h3 style="margin:0; color:#38bdf8;">لوحة تحكم الموقع</h3>
        <a href="/logout" style="color:#f87171; background:#334155; padding:8px 16px; border-radius:6px; text-decoration:none;">خروج</a>
    </header>
    <div class="sidebar" id="sidebar">
        <a onclick="showPage('home')">🏠 الرئيسية</a> <a onclick="showPage('subs')">👥 المشتركين</a>
        <a onclick="showPage('dishes')">📡 الصحون</a> <a onclick="showPage('towers')">🗼 الأبراج والخرائط</a>
