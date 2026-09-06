from flask import Flask, request, redirect, session, jsonify, render_template_string
import os, datetime, json, html, subprocess, platform, ipaddress
try:
    import psycopg2, psycopg2.extras
except: psycopg2=None
import sqlite3

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY","omia-sec-2026")
DATABASE_URL = os.environ.get("DATABASE_URL","").strip().replace("postgresql://","postgres://")
USE_PG = bool(DATABASE_URL.startswith("postgres://") and psycopg2)
_pg = None

def esc(s): return html.escape(str(s or ''), quote=True)

def db():
    global _pg
    if USE_PG:
        try:
            if _pg:
                cur=_pg.cursor();cur.execute("SELECT 1");cur.close();return _pg
        except:
            try:_pg.close()
            except:pass
            _pg=None
        _pg=psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=5);_pg.autocommit=True;return _pg
    c=sqlite3.connect("omia.db");c.row_factory=sqlite3.Row;return c

def cc(c):
    if not USE_PG:
        try:c.close()
        except:pass

def qall(q,a=()):
    c=db()
    try:
        if USE_PG:
            cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(q.replace("?","%s"),a);rs=[dict(r) for r in cur.fetchall()];cur.close();return rs
        else: rs=[dict(r) for r in c.execute(q,a).fetchall()];cc(c);return rs
    except Exception as e: print(e);cc(c);return []

def qone(q,a=()):
    r=qall(q,a);return r[0] if r else None

def qexec(q,a=()):
    c=db()
    try:
        if USE_PG: cur=c.cursor();cur.execute(q.replace("?","%s"),a);cur.close()
        else: c.execute(q,a);c.commit();cc(c)
    except Exception as e: print(e);cc(c)

def log_activity(action):
    u = session.get('username', 'مجهول')
    p = session.get('phone', 'بدون هاتف')
    dt = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    qexec("INSERT INTO activity_logs (username, phone, action, dt) VALUES (?,?,?,?)", (u, p, action, dt))

def init():
    ss=[
        "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,username TEXT,active INT DEFAULT 1)",
        "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,active INT DEFAULT 1)",
        "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,lat REAL DEFAULT 0,lng REAL DEFAULT 0,dish_name TEXT,tower_name TEXT)",
        "CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,lat REAL,lng REAL,location TEXT,is_fixed INT DEFAULT 0)",
        "CREATE TABLE IF NOT EXISTS activity_logs(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT,phone TEXT,action TEXT,dt TEXT)"
    ]
    if USE_PG: ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
    for s in ss: qexec(s)
    
    if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username,active) VALUES(?,?,?,?,?)",('05344851045','admin2024','manager','admin',1))
    
    # إضافة نقطة برج افتراضية ثابتة لا تحذف
    if not qone("SELECT * FROM towers WHERE is_fixed=1"):
        qexec("INSERT INTO towers(name,lat,lng,location,is_fixed) VALUES(?,?,?,?,?)", ('البرج الرئيسي الثابت', 35.1318, 36.7578, 'حماة', 1))

init()

def is_valid_ip(ip):
    try:
        ipaddress.ip_address(ip.strip())
        return True
    except: return False

@app.route('/')
def main_page():
    if not session.get('phone'):
        return redirect('/login')
    return render_template_string(BASE_HTML)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form.get('username','')
        p = request.form.get('phone','')
        pwd = request.form.get('password','')
        user = qone("SELECT * FROM users WHERE username=? AND phone=? AND password=?", (u, p, pwd))
        if user:
            session['phone'] = user['phone']
            session['username'] = user['username']
            log_activity("سجل دخوله إلى النظام")
            return redirect('/')
        return render_template_string(LOGIN_HTML, error="بيانات الدخول غير صحيحة")
    return render_template_string(LOGIN_HTML, error=None)

@app.route('/logout')
def logout():
    log_activity("سجل خروجه من النظام")
    session.clear()
    return redirect('/login')

# ---- واجهات برمجية ذكية (AJAX APIs) لتفادي تحميل الصفحة ----
@app.route('/api/data')
def get_data():
    if not session.get('phone'): return jsonify(error="Unauth"), 401
    
    ns = qone("SELECT COUNT(*) c FROM subs")['c']
    nd = qone("SELECT COUNT(*) c FROM dish_ips")['c']
    nt = qone("SELECT COUNT(*) c FROM towers")['c']
    
    subs = qall("SELECT * FROM subs ORDER BY id DESC")
    dishes = qall("SELECT * FROM dish_ips ORDER BY id DESC")
    towers = qall("SELECT * FROM towers ORDER BY id DESC")
    logs = qall("SELECT * FROM activity_logs ORDER BY id DESC LIMIT 50")
    
    return jsonify(kpis={'subs': ns, 'dishes': nd, 'towers': nt}, subs=subs, dishes=dishes, towers=towers, logs=logs)

@app.route('/api/subs/add', methods=['POST'])
def add_sub():
    name = request.form.get('name','')
    phone = request.form.get('phone','')
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
    name = request.form.get('dish_name','')
    ip = request.form.get('ip','').strip()
    if not is_valid_ip(ip):
        return jsonify(ok=False, msg="عنوان IP غير صالح! يرجى التحقق منه.")
    qexec("INSERT INTO dish_ips (dish_name, ip) VALUES (?,?)", (name, ip))
    log_activity(f"أضاف الصحن: {name} بـ IP: {ip}")
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
    name = request.form.get('name','')
    loc = request.form.get('location','')
    lat = float(request.form.get('lat', 0) or 0)
    lng = float(request.form.get('lng', 0) or 0)
    if name:
        qexec("INSERT INTO towers (name, location, lat, lng) VALUES (?,?,?,?)", (name, loc, lat, lng))
        log_activity(f"أضاف برجاً جديداً: {name}")
    return jsonify(ok=True)

@app.route('/api/towers/delete/<int:id>', methods=['POST'])
def del_tower(id):
    tower = qone("SELECT * FROM towers WHERE id=?", (id,))
    if tower:
        if tower.get('is_fixed') == 1:
            return jsonify(ok=False, msg="لا يمكن حذف النقاط الثابتة الرئيسية!")
        qexec("DELETE FROM towers WHERE id=?", (id,))
        log_activity(f"حذف البرج: {tower['name']}")
    return jsonify(ok=True)

@app.route('/api/ping')
def api_ping():
    ip=request.args.get('ip','').strip()
    if not ip or not is_valid_ip(ip): return jsonify(ok=False,out='IP غير صحيح')
    try:
        w=platform.system().lower()=='windows'
        cmd=['ping','-n','2',ip] if w else ['ping','-c','2','-W','2',ip]
        o=subprocess.run(cmd,capture_output=True,text=True,timeout=5)
        return jsonify(ok=True,out=((o.stdout or '')+(o.stderr or ''))[:1000])
    except Exception as e: return jsonify(ok=False,out=str(e))


# ---------------- التصميم والواجهات الأمامية ----------------

LOGIN_HTML = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>تسجيل الدخول - OMAIA</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #0f172a; color: white; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
        .login-card { background: #1e293b; padding: 30px; border-radius: 12px; width: 100%; max-width: 400px; box-shadow: 0 10px 25px rgba(0,0,0,0.3); text-align: center; }
        h2 { margin-bottom: 20px; color: #38bdf8; }
        input { width: 100%; padding: 12px; margin: 10px 0; border-radius: 6px; border: 1px solid #475569; background: #0f172a; color: white; box-sizing: border-box; }
        button { width: 100%; padding: 12px; background: #2563eb; border: none; border-radius: 6px; color: white; font-weight: bold; cursor: pointer; transition: 0.3s; }
        button:hover { background: #1d4ed8; }
        .error { color: #f87171; font-size: 14px; margin-bottom: 10px; }
    </style>
</head>
<body>
    <div class="login-card">
        <h2>بوابة تسجيل الدخول</h2>
        {% if error %}<div class="error">{{ error }}</div>{% endif %}
        <form method="POST">
            <input type="text" name="username" placeholder="اسم المستخدم (User)" required>
            <input type="text" name="phone" placeholder="رقم الهاتف (Phone)" required>
            <input type="password" name="password" placeholder="كلمة المرور" required>
            <button type="submit">دخول</button>
        </form>
    </div>
</body>
</html>
"""

BASE_HTML = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>لوحة التحكم الذكية</title>
    <!-- Leaflet CSS الخرائط -->
    <link rel="stylesheet" href="https://unpkg.com" />
    <style>
        :root { --bg-main: #0f172a; --bg-card: #1e293b; --text: #f8fafc; --primary: #38bdf8; }
