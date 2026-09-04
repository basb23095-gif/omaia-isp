from flask import Flask, request, redirect, render_template_string, session, url_for, flash
import sqlite3
import os

# ملاحظة لربط ميكروتك: ستحتاج لتثبيت المكتبة عبر الأمر: pip install routeros-api
try:
    import routeros_api
except ImportError:
    routeros_api = None

app = Flask(__name__)
app.secret_key = os.urandom(24) # تأمين الجلسات (Sessions)
DB = "omaia_pro.db"

# إعداد قاعدة البيانات وتحديث الجداول لتشمل الحسابات والـ IPs والمستخدمين
def init_db():
    con = sqlite3.connect(DB)
    # جدول المشتركين المطور
    con.execute("""CREATE TABLE IF NOT EXISTS subs
    (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, phone TEXT, address TEXT, speed TEXT, status TEXT)""")
    
    # جدول الحسابات (دولار وسوري)
    con.execute("""CREATE TABLE IF NOT EXISTS accounts
    (id INTEGER PRIMARY KEY AUTOINCREMENT, sub_id INTEGER, balance_usd REAL DEFAULT 0.0, balance_syr REAL DEFAULT 0.0,
    FOREIGN KEY(sub_id) REFERENCES subs(id) ON DELETE CASCADE)""")
    
    # جدول إدارة الـ IPs
    con.execute("""CREATE TABLE IF NOT EXISTS ips
    (id INTEGER PRIMARY KEY AUTOINCREMENT, ip_address TEXT UNIQUE, sub_id INTEGER, notes TEXT,
    FOREIGN KEY(sub_id) REFERENCES subs(id) ON DELETE SET NULL)""")
    
    # جدول مديرين النظام (لوحة التحكم)
    con.execute("""CREATE TABLE IF NOT EXISTS admins
    (id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT UNIQUE, password TEXT, role TEXT)""")
    
    # إضافة حساب مدير افتراضي إذا لم يكن موجوداً (رقم الهاتف: 0900000000 / كلمة السر: admin123)
    cursor = con.cursor()
    cursor.execute("SELECT * FROM admins WHERE phone='0900000000'")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO admins (phone, password, role) VALUES ('0900000000', 'admin123', 'admin')")
        
    con.commit()
    con.close()

init_db()

# دالة مساعدة للاتصال بالميكروتك وتطبيق الإجراءات (مثل قطع أو تفعيل الخدمة)
def mikrotik_action(action, ip_address, comment=""):
    if not routeros_api:
        return False "مكتبة ميكروتك غير مثبتة"
    try:
        # ضع بيانات الميكروتك الخاصة بك هنا
        connection = routeros_api.RouterOsApiPool('192.168.88.1', username='admin', password='your_password')
        api = connection.get_api()
        
        # مثال: التحكم عبر القائمة الفايروال (Address List)
        firewall = api.get_resource('/ip/firewall/address-list')
        
        if action == "block":
            firewall.add(list='Blocked_Subs', address=ip_address, comment=comment)
        elif action == "unblock":
            existing = firewall.get(address=ip_address)
            for item in existing:
                firewall.remove(id=item['id'])
                
        connection.disconnect()
        return True
    except Exception as e:
        print(f"Mikrotik Error: {e}")
        return False

# تصميم الواجهة المميزة (تنسيق احترافي باللون الذهبي الفخم والأسود الداكن)
HTML_LAYOUT = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OMAIA ISP PRO</title>
    <style>
        :root { --main-bg: #0b0f19; --card-bg: #111827; --gold: #d4af37; --gold-hover: #f3e5ab; --text: #f9fafb; }
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: var(--main-bg); color: var(--text); margin: 0; padding-bottom: 50px; }
        nav { background: linear-gradient(135deg, #1e1b4b, #111827); border-bottom: 2px solid var(--gold); padding: 20px; text-align: center; font-size: 24px; font-weight: bold; color: var(--gold); letter-spacing: 1px; }
        .container { max-width: 1000px; margin: 30px auto; background: var(--card-bg); padding: 30px; border-radius: 16px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); border: 1px solid #1f2937; }
        .menu { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 25px; border-bottom: 1px solid #374151; padding-bottom: 15px; }
        .menu a { flex: 1; min-width: 120px; text-align: center; background: #1f2937; padding: 12px; border-radius: 8px; text-decoration: none; color: var(--text); font-weight: 500; border: 1px solid transparent; transition: 0.3s; }
        .menu a:hover, .menu a.active { background: #2d3748; border-color: var(--gold); color: var(--gold); }
        .btn-logout { background: #991b1b !important; color: white !important; }
        input, select, textarea { width: 100%; padding: 12px; margin: 10px 0; border: 1px solid #374151; border-radius: 8px; background: #1f2937; color: #fff; box-sizing: border-box; }
        input:focus, select:focus { border-color: var(--gold); outline: none; }
        button { background: linear-gradient(135deg, var(--gold), #aa8010); color: #000; padding: 14px; border: none; border-radius: 8px; width: 100%; font-size: 16px; font-weight: bold; cursor: pointer; transition: 0.3s; }
        button:hover { background: var(--gold-hover); }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; background: #151f32; border-radius: 8px; overflow: hidden; }
        th, td { padding: 14px; text-align: center; border-bottom: 1px solid #23324c; }
        th { background: #1e293b; color: var(--gold); font-weight: 600; }
        tr:hover { background: #1c273a; }
        .badge { padding: 4px 8px; border-radius: 6px; font-size: 12px; font-weight: bold; }
        .badge-active { background: #065f46; color: #34d399; }
        .badge-suspended { background: #991b1b; color: #f87171; }
        .alert { background: #7f1d1d; color: #fca5a5; padding: 12px; border-radius: 8px; margin-bottom: 15px; text-align: center; }
        .currency-box { display: flex; gap: 10px; }
    </style>
</head>
<body>
    <nav>✨ OMAIA ISP - لوحة التحكم الاحترافية ✨</nav>
    <div class="container">
        {% with messages = get_flashed_messages() %}
          {% if messages %}
            {% for msg in messages %}<div class="alert">{{ msg }}</div>{% endfor %}
          {% endif %}
        {% endwith %}
        
        {% if session.get('logged_in') %}
        <div class="menu">
            <a href="{{ url_for('dashboard', view='subs') }}">المشتركون</a>
            <a href="{{ url_for('dashboard', view='add_sub') }}">إضافة مشترك</a>
            <a href="{{ url_for('dashboard', view='accounts') }}">دفتر الحسابات</a>
            <a href="{{ url_for('dashboard', view='ips') }}">إدارة الـ IPs</a>
            <a href="{{ url_for('logout') }}" class="btn-logout">تسجيل الخروج</a>
        </div>
        {% endif %}
        
        {{ content|safe }}
    </div>
</body>
</html>
"""

# --- المسارات والتحكم ---

@app.route('/')
def index():
    if session.get('logged_in'):
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

# صفحة الدخول برقم الهاتف وكلمة السر
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        phone = request.form['phone']
        password = request.form['password']
        
        con = sqlite3.connect(DB)
        admin = con.execute("SELECT * FROM admins WHERE phone=? AND password=?", (phone, password)).fetchone()
        con.close()
        
        if admin:
            session['logged_in'] = True
            session['admin_phone'] = admin[1]
            return redirect(url_for('dashboard'))
            
        flash("رقم الهاتف أو كلمة السر غير صحيحة!")
        return redirect(url_for('login'))
        
    login_form = """
    <div style="max-width: 400px; margin: 40px auto;">
        <h3 style="text-align: center; color: var(--gold);">تسجيل الدخول للنظام</h3>
        <form method="post">
            <input type="text" name="phone" placeholder="رقم الهاتف (مثال: 0900000000)" required>
            <input type="password" name="password" placeholder="كلمة السر" required>
            <button type="submit">دخول</button>
        </form>
    </div>
    """
    return render_template_string(HTML_LAYOUT, content=login_form)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# لوحة التحكم الكاملة (تتغير بناءً على الـ view المطلوب)
@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    view = request.args.get('view', 'subs')
    con = sqlite3.connect(DB)
    
    if view == 'subs':
        # عرض المشتركين مع حساباتهم والـ IP الخاص بهم
        query = """
            SELECT s.id, s.name, s.phone, s.speed, s.status, a.balance_usd, a.balance_syr, i.ip_address 
            FROM subs s
            LEFT JOIN accounts a ON s.id = a.sub_id
            LEFT JOIN ips i ON s.id = i.sub_id
        """
        subs = con.execute(query).fetchall()
        con.close()
        
        rows = ""
        for s in subs:
            status_badge = f'<span class="badge badge-active">نشط</span>' if s[4] == 'نشط' else f'<span class="badge badge-suspended">موقوف</span>'
            rows += f"""
            <tr>
                <td>{s[1]}</td><td>{s[2]}</td><td>{s[3] or '-'}</td>
                <td>{s[7] or 'غير معين'}</td>
                <td style="color: #34d399;">${s[5] or 0}</td><td style="color: #fbbf24;">{s[6] or 0} ل.س</td>
                <td>{status_badge}</td>
                <td>
                    <a href="/toggle_status/{s[0]}" style="color:var(--gold); text-decoration:none; margin-right:10px;">تغيير الحالة</a> | 
                    <a href="/del_sub/{s[0]}" style="color:#f87171; text-decoration:none;" onclick="return confirm('هل أنت متأكد؟')">حذف</a>
                </td>
            </tr>
            """
        
        content = f"""
        <h3>قائمة المشتركين الحالية</h3>
        <table>
            <tr><th>الاسم</th><th>الهاتف</th><th>السرعة</th><th>الـ IP</th><th>رصيد ($)</th><th>رصيد (سوري)</th><th>الحالة</th><th>التحكم</th></tr>
            {rows}
        </table>"""
        
    elif view == 'add_sub':
        con.close()
        content = """
        <h3>إضافة مشترك جديد وتعيين حسابه</h3>
        <form method="post" action="/add_sub">
