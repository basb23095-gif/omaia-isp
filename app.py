from flask import Flask, request, redirect, render_template_string, session, url_for, flash
import sqlite3
import os

try:
    import routeros_api
except ImportError:
    routeros_api = None

app = Flask(__name__)
app.secret_key = os.urandom(24) 
DB = "omaia_pro_v3.db" # تم تحديث النسخة لتجنب أي مشاكل سابقة

def init_db():
    con = sqlite3.connect(DB)
    # 1. جدول المشتركين
    con.execute("""CREATE TABLE IF NOT EXISTS subs
    (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, phone TEXT, address TEXT, speed TEXT, status TEXT)""")
    
    # 2. جدول الحسابات
    con.execute("""CREATE TABLE IF NOT EXISTS accounts
    (id INTEGER PRIMARY KEY AUTOINCREMENT, sub_id INTEGER, balance_usd REAL DEFAULT 0.0, balance_syr REAL DEFAULT 0.0,
    FOREIGN KEY(sub_id) REFERENCES subs(id) ON DELETE CASCADE)""")
    
    # 3. جدول الـ IPs
    con.execute("""CREATE TABLE IF NOT EXISTS ips
    (id INTEGER PRIMARY KEY AUTOINCREMENT, ip_address TEXT UNIQUE, sub_id INTEGER, notes TEXT,
    FOREIGN KEY(sub_id) REFERENCES subs(id) ON DELETE SET NULL)""")
    
    # 4. جدول الإدارة
    con.execute("""CREATE TABLE IF NOT EXISTS admins
    (id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT UNIQUE, password TEXT, role TEXT)""")
    
    cursor = con.cursor()
    cursor.execute("SELECT * FROM admins WHERE phone='0900000000'")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO admins (phone, password, role) VALUES ('0900000000', 'admin123', 'admin')")
        
    con.commit()
    con.close()

init_db()

def mikrotik_action(action, ip_address, comment=""):
    if not routeros_api:
        return False
    try:
        connection = routeros_api.RouterOsApiPool('192.168.88.1', username='admin', password='your_password')
        api = connection.get_api()
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

HTML_LAYOUT = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OMAIA ISP PRO</title>
    <style>
        :root { --main-bg: #0b0f19; --card-bg: #111827; --gold: #d4af37; --gold-hover: #f3e5ab; --text: #f9fafb; }
        body { font-family: Arial, sans-serif; background: var(--main-bg); color: var(--text); margin: 0; padding-bottom: 50px; }
        nav { background: linear-gradient(135deg, #1e1b4b, #111827); border-bottom: 2px solid var(--gold); padding: 20px; text-align: center; font-size: 24px; font-weight: bold; color: var(--gold); }
        .container { max-width: 1000px; margin: 30px auto; background: var(--card-bg); padding: 30px; border-radius: 16px; border: 1px solid #1f2937; }
        .menu { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 25px; border-bottom: 1px solid #374151; padding-bottom: 15px; }
        .menu a { flex: 1; min-width: 120px; text-align: center; background: #1f2937; padding: 12px; border-radius: 8px; text-decoration: none; color: var(--text); font-weight: bold; border: 1px solid transparent; transition: 0.3s; }
        .menu a:hover { background: #2d3748; border-color: var(--gold); color: var(--gold); }
        .btn-logout { background: #991b1b !important; color: white !important; }
        input, select, textarea { width: 100%; padding: 12px; margin: 10px 0; border: 1px solid #374151; border-radius: 8px; background: #1f2937; color: #fff; box-sizing: border-box; }
        button { background: linear-gradient(135deg, var(--gold), #aa8010); color: #000; padding: 14px; border: none; border-radius: 8px; width: 100%; font-size: 16px; font-weight: bold; cursor: pointer; }
        button:hover { background: var(--gold-hover); }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; background: #151f32; border-radius: 8px; overflow: hidden; }
        th, td { padding: 14px; text-align: center; border-bottom: 1px solid #23324c; }
        th { background: #1e293b; color: var(--gold); }
        .badge { padding: 4px 8px; border-radius: 6px; font-size: 12px; font-weight: bold; }
        .badge-active { background: #065f46; color: #34d399; }
        .badge-suspended { background: #991b1b; color: #f87171; }
        .alert { background: #7f1d1d; color: #fca5a5; padding: 12px; border-radius: 8px; margin-bottom: 15px; text-align: center; }
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
            <a href="/dashboard?view=subs">المشتركون</a>
            <a href="/dashboard?view=add_sub">إضافة مشترك</a>
            <a href="/dashboard?view=accounts">دفتر الحسابات</a>
            <a href="/dashboard?view=ips">إدارة الـ IPs</a>
            <a href="/logout" class="btn-logout">تسجيل الخروج</a>
        </div>
        {% endif %}
        
        {{ content|safe }}
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    if session.get('logged_in'):
        return redirect('/dashboard')
    return redirect('/login')

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
            session['admin_phone'] = phone
            return redirect('/dashboard')
            
        flash("رقم الهاتف أو كلمة السر غير صحيحة!")
        return redirect('/login')
        
    login_form = """
    <div style="max-width: 400px; margin: 40px auto;">
        <h3 style="text-align: center; color: var(--gold);">تسجيل الدخول للنظام</h3>
        <form method="post">
            <input type="text" name="phone" placeholder="رقم الهاتف" required>
            <input type="password" name="password" placeholder="كلمة السر" required>
            <button type="submit">دخول</button>
        </form>
    </div>
    """
    return render_template_string(HTML_LAYOUT, content=login_form)

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect('/login')
        
    view = request.args.get('view', 'subs')
    con = sqlite3.connect(DB)
    content = ""
    
    if view == 'subs':
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
            sub_id = s[0]
            name = s[1]
            phone = s[2]
            speed = s[3]
            status = s[4]
            usd_val = s[5] if s[5] is not None else 0.0
            syr_val = s[6] if s[6] is not None else 0.0
            ip_val = s[7] if s[7] else 'غير معين'
            
            status_badge = f'<span class="badge badge-active">نشط</span>' if status == "نشط" else f'<span class="badge badge-suspended">موقوف</span>'
            
            rows += f"""
            <tr>
                <td>{name}</td><td>{phone}</td><td>{speed}</td>
                <td>{ip_val}</td>
                <td style="color: #34d399;">${usd_val}</td><td style="color: #fbbf24;">{syr_val} ل.س</td>
                <td>{status_badge}</td>
                <td>
                    <a href="/toggle_status/{sub_id}" style="color:var(--gold); text-decoration:none; margin-right:10px;">تغيير الحالة</a> | 
                    <a href="/del_sub/{sub_id}" style="color:#f87171; text-decoration:none;" onclick="return confirm('هل أنت متأكد؟')">حذف</a>
                </td>
            </tr>
            """
        content = f"""<h3>قائمة المشتركين</h3><table>
            <tr><th>الاسم</th><th>الهاتف</th><th>السرعة</th><th>الـ IP</th><th>رصيد ($)</th><th>رصيد (سوري)</th><th>الحالة</th><th>التحكم</th></tr>
            {rows}</table>"""
        
    elif view == 'add_sub':
        con.close()
        content = """
        <h3>إضافة مشترك جديد</h3>
        <form method="post" action="/add_sub">
            <input name="name" placeholder="اسم المشترك" required>
            <input name="phone" placeholder="رقم الهاتف" required>
            <input name="address" placeholder="العنوان">
            <input name="speed" placeholder="السرعة (مثال: 10 Mbps)">
            <div style="display:flex; gap:10px;">
                <input type="number" step="0.01" name="usd" placeholder="رصيد بالدولار ($)">
                <input type="number" name="syr" placeholder="رصيد بالليرة السورية">
            </div>
            <select name="status"><option>نشط</option><option>موقوف</option></select>
            <button type="submit">حفظ وإضافة</button>
        </form>
        """
        
    elif view == 'accounts':
        query = "SELECT s.id, s.name, a.balance_usd, a.balance_syr FROM subs s JOIN accounts a ON s.id = a.sub_id"
        accounts = con.execute(query).fetchall()
        con.close()
        
        rows = ""
        for acc in accounts:
            sub_id = acc[0]
            name = acc[1]
