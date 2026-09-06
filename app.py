from flask import Flask, request, redirect, session, jsonify, render_template_string
import os, datetime, html, subprocess, platform, ipaddress, psycopg2, psycopg2.extras

app = Flask(__name__)
# مفتاح الأمان يُجلب من إعدادات البيئة في Render أو يستخدم الافتراضي آمن
app.secret_key = os.environ.get("SECRET_KEY", "omia-website-secure-key-2026")

# جلب رابط قاعدة البيانات الخاص بـ Supabase من متغيرات البيئة في Render
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip().replace("postgresql://", "postgres://")

def esc(s): 
    return html.escape(str(s or ''), quote=True)

# الاتصال الآمن والمستقر بـ Supabase PostgreSQL
def db_connect():
    if not DATABASE_URL:
        raise ValueError("خطأ: لم يتم ضبط متغير البيئة DATABASE_URL الخاص بـ Supabase في موقع Render!")
    conn = psycopg2.connect(DATABASE_URL, sslmode='require', connect_timeout=5)
    conn.autocommit = True
    return conn

def qall(q, a=()):
    conn = db_connect()
    try:
        # تحويل صيغة ? الخاصة بـ SQLite إلى صيغة %s المتوافقة مع PostgreSQL
        q_pos = q.replace("?", "%s")
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(q_pos, a)
        rs = [dict(r) for r in cur.fetchall()]
        cur.close()
        conn.close()
        return rs
    except Exception as e:
        print(f"Supabase Error: {e}")
        try: conn.close()
        except: pass
        return []

def qone(q, a=()):
    r = qall(q, a)
    return r[0] if r else None

def qexec(q, a=()):
    conn = db_connect()
    try:
        q_pos = q.replace("?", "%s")
        cur = conn.cursor()
        cur.execute(q_pos, a)
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Supabase Execute Error: {e}")
        try: conn.close()
        except: pass

# سجل الحركات والدخول الحية إلى السيرفر
def log_activity(action):
    u = session.get('username', 'زائر مجهول')
    p = session.get('phone', 'بدون هاتف')
    dt = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    qexec("INSERT INTO activity_logs (username, phone, action, dt) VALUES (?,?,?,?)", (u, p, action, dt))

# تهيئة الجداول وبنائها داخل قاعدة بيانات Supabase بشكل متوافق تماماً
def init_supabase_tables():
    # استخدام SERIAL PRIMARY KEY عوضاً عن AUTOINCREMENT لأنها مخصصة لـ PostgreSQL
    qexec("CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY, password TEXT, role TEXT, username TEXT, active INT DEFAULT 1)")
    qexec("CREATE TABLE IF NOT EXISTS subs(id SERIAL PRIMARY KEY, name TEXT, phone TEXT, active INT DEFAULT 1)")
    qexec("CREATE TABLE IF NOT EXISTS dish_ips(id SERIAL PRIMARY KEY, ip TEXT, location TEXT, lat REAL DEFAULT 0, lng REAL DEFAULT 0, dish_name TEXT, tower_name TEXT)")
    qexec("CREATE TABLE IF NOT EXISTS towers(id SERIAL PRIMARY KEY, name TEXT, lat REAL, lng REAL, location TEXT, is_fixed INT DEFAULT 0)")
    qexec("CREATE TABLE IF NOT EXISTS activity_logs(id SERIAL PRIMARY KEY, username TEXT, phone TEXT, action TEXT, dt TEXT)")
    
    # حساب المدير الافتراضي للموقع
    if not qone("SELECT * FROM users WHERE phone=?", ('05344851045',)):
        qexec("INSERT INTO users(phone, password, role, username, active) VALUES(?,?,?,?,?)", ('05344851045', 'admin2024', 'manager', 'admin', 1))
    
    # نقطة البرج الثابتة المحمية (لا يمكن حذفها وتظهر افتراضياً)
    if not qone("SELECT * FROM towers WHERE is_fixed=1"):
        qexec("INSERT INTO towers(name, lat, lng, location, is_fixed) VALUES(?,?,?,?,?)", ('البرج الرئيسي الثابت للموقع', 35.1318, 36.7578, 'حماة', 1))

# تشغيل التهيئة تلقائياً عند إقلاع السيرفر على Render
if DATABASE_URL:
    init_supabase_tables()

def is_valid_ip(ip):
    try:
        ipaddress.ip_address(ip.strip())
        return True
    except: 
        return False

# ---- مسارات السيرفر والموقع (Routing) ----

@app.route('/')
def index():
    if not session.get('phone'):
        return redirect('/login')
    return render_template_string(BASE_HTML)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form.get('username', '').strip()
        p = request.form.get('phone', '').strip()
        pwd = request.form.get('password', '')
        
        user = qone("SELECT * FROM users WHERE username=? AND phone=? AND password=?", (u, p, pwd))
        if user:
            session['phone'] = user['phone']
            session['username'] = user['username']
            log_activity("سجل دخوله إلى الموقع")
            return redirect('/')
        return render_template_string(LOGIN_HTML, error="بيانات الدخول للموقع غير صحيحة")
    return render_template_string(LOGIN_HTML, error=None)

@app.route('/logout')
def logout():
    log_activity("سجل خروجه من الموقع")
    session.clear()
    return redirect('/login')

# ---- واجهات البيانات السريعة (AJAX APIs) المستقرة لتغذية واجهة المستخدم ----

@app.route('/api/data')
def get_site_data():
    if not session.get('phone'): 
        return jsonify(error="غير مصرح لك"), 401
    
    ns = (qone("SELECT COUNT(*) as c FROM subs") or {}).get('c', 0)
    nd = (qone("SELECT COUNT(*) as c FROM dish_ips") or {}).get('c', 0)
    nt = (qone("SELECT COUNT(*) as c FROM towers") or {}).get('c', 0)
    
    subs = qall("SELECT * FROM subs ORDER BY id DESC")
    dishes = qall("SELECT * FROM dish_ips ORDER BY id DESC")
    towers = qall("SELECT * FROM towers ORDER BY id DESC")
    logs = qall("SELECT * FROM activity_logs ORDER BY id DESC LIMIT 50")
    
    return jsonify(kpis={'subs': ns, 'dishes': nd, 'towers': nt}, subs=subs, dishes=dishes, towers=towers, logs=logs)

@app.route('/api/subs/add', methods=['POST'])
def add_sub():
    name = request.form.get('name', '').strip()
    phone = request.form.get('phone', '').strip()
    if name:
        qexec("INSERT INTO subs (name, phone) VALUES (?,?)", (name, phone))
        log_activity(f"أضاف المشترك: {name}")
    return jsonify(ok=True)

@app.route('/api/subs/delete/<int:id>', methods=['POST'])
def del_sub(id):
    sub = qone("SELECT name FROM subs WHERE id=?", (id,))
    if sub:
        qexec("DELETE FROM subs WHERE id=?", (id,))
        log_activity(f"حذف المشترك: {sub['name']}")
    return jsonify(ok=True)

@app.route('/api/dishes/add', methods=['POST'])
def add_dish():
    name = request.form.get('dish_name', '').strip()
    ip = request.form.get('ip', '').strip()
    if not is_valid_ip(ip):
        return jsonify(ok=False, msg="خطأ: عنوان IP غير صالح! يرجى التحقق منه.")
    qexec("INSERT INTO dish_ips (dish_name, ip) VALUES (?,?)", (name, ip))
    log_activity(f"أضاف صحن جديد: {name} بالآي بي: {ip}")
    return jsonify(ok=True)

@app.route('/api/dishes/delete/<int:id>', methods=['POST'])
def del_dish(id):
    dish = qone("SELECT dish_name FROM dish_ips WHERE id=?", (id,))
    if dish:
        qexec("DELETE FROM dish_ips WHERE id=?", (id,))
        log_activity(f"حذف الصحن: {dish['dish_name']}")
    return jsonify(ok=True)

@app.route('/api/towers/add', methods=['POST'])
def add_tower():
    name = request.form.get('name', '').strip()
    loc = request.form.get('location', '').strip()
    lat = float(request.form.get('lat', 0) or 0)
    lng = float(request.form.get('lng', 0) or 0)
    if name:
        qexec("INSERT INTO towers (name, location, lat, lng) VALUES (?,?,?,?)", (name, loc, lat, lng))
        log_activity(f"أضاف نقطة برج جديدة للموقع: {name}")
    return jsonify(ok=True)

@app.route('/api/towers/delete/<int:id>', methods=['POST'])
def del_tower(id):
    tower = qone("SELECT * FROM towers WHERE id=?", (id,))
    if tower:
        if tower.get('is_fixed') == 1:
            return jsonify(ok=False, msg="حماية الموقع: لا يمكن حذف النقطة الثابتة الرئيسية للموقع!")
        qexec("DELETE FROM towers WHERE id=?", (id,))
        log_activity(f"حذف البرج: {tower['name']}")
    return jsonify(ok=True)

@app.route('/api/ping')
def api_ping():
    ip = request.args.get('ip', '').strip()
    if not ip or not is_valid_ip(ip): 
        return jsonify(ok=False, out='IP غير صحيح')
    try:
        w = platform.system().lower() == 'windows'
        cmd = ['ping', '-n', '2', ip] if w else ['ping', '-c', '2', '-W', '2', ip]
        o = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return jsonify(ok=True, out=((o.stdout or '') + (o.stderr or ''))[:1000])
    except Exception as e: 
        return jsonify(ok=False, out=str(e))

# ---- كود تصميم واجهة المستخدم الأمامية للهواتف والمتصفحات ----

LOGIN_HTML = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>تسجيل دخول الموقع - OMAIA</title>
    <style>
        body { font-family: 'Segoe UI', system-ui, sans-serif; background: #0f172a; color: white; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
        .login-card { background: #1e293b; padding: 35px; border-radius: 16px; width: 90%; max-width: 400px; box-shadow: 0 15px 35px rgba(0,0,0,0.4); text-align: center; }
        h2 { margin-bottom: 25px; color: #38bdf8; font-size: 24px; }
        input { width: 100%; padding: 14px; margin: 12px 0; border-radius: 8px; border: 1px solid #475569; background: #0f172a; color: white; box-sizing: border-box; font-size: 16px; }
        button { width: 100%; padding: 14px; background: #2563eb; border: none; border-radius: 8px; color: white; font-weight: bold; cursor: pointer; transition: 0.3s; font-size: 16px; }
        button:hover { background: #1d4ed8; }
        .error { background: rgba(248,113,113,0.2); padding: 10px; border-radius: 6px; color: #f87171; font-size: 14px; margin-bottom: 15px; border: 1px solid #f87171; }
    </style>
</head>
<body>
    <div class="login-card">
        <h2>لوحة تحكم الموقع (Supabase Cloud)</h2>
        {% if error %}<div class="error">{{ error }}</div>{% endif %}
        <form method="POST">
