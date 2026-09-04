from flask import Flask, request, redirect, render_template_string, session
import sqlite3
import os

app = Flask(__name__)
app.secret_key = os.urandom(24)
DB = "omaia_isp_v4_stable.db"

def init_db():
    con = sqlite3.connect(DB)
    con.execute("CREATE TABLE IF NOT EXISTS subs (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, phone TEXT, address TEXT, speed TEXT, status TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS accounts (id INTEGER PRIMARY KEY AUTOINCREMENT, sub_id INTEGER, balance_usd REAL DEFAULT 0.0, balance_syr REAL DEFAULT 0.0)")
    con.execute("CREATE TABLE IF NOT EXISTS ips (id INTEGER PRIMARY KEY AUTOINCREMENT, ip_address TEXT UNIQUE, sub_id INTEGER, notes TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS admins (id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT UNIQUE, password TEXT, role TEXT)")
    cur = con.cursor()
    cur.execute("SELECT * FROM admins WHERE phone='0900000000'")
    if not cur.fetchone():
        cur.execute("INSERT INTO admins (phone, password, role) VALUES ('0900000000','admin123','admin')")
    con.commit(); con.close()

init_db()

HTML_LAYOUT = """<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>OMAIA ISP</title>
<style>body{font-family:Arial;background:#0b0f19;color:#fff;margin:0}nav{background:#111827;padding:20px;text-align:center;color:#d4af37;font-size:22px;border-bottom:2px solid #d4af37}.container{max-width:1000px;margin:20px auto;background:#111827;padding:20px;border-radius:12px}.menu{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:15px}.menu a{background:#1f2937;color:#fff;padding:10px;border-radius:8px;text-decoration:none}table{width:100%;border-collapse:collapse}th,td{padding:10px;border-bottom:1px solid #333;text-align:center}input,select{width:100%;padding:10px;margin:8px 0;background:#1f2937;border:1px solid #444;color:#fff;border-radius:8px}button{background:#d4af37;padding:12px;width:100%;border:none;border-radius:8px;font-weight:bold}</style>
</head><body><nav>OMAIA ISP</nav><div class="container">{% if is_logged %}<div class="menu"><a href="/dashboard?view=subs">المشتركون</a><a href="/dashboard?view=add_sub">اضافة</a><a href="/logout">خروج</a></div>{% endif %}{{content|safe}}</div></body></html>"""

@app.route('/')
def index():
    return redirect('/dashboard') if session.get('logged_in') else redirect('/login')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        con=sqlite3.connect(DB)
        admin=con.execute("SELECT * FROM admins WHERE phone=? AND password=?",(request.form['phone'],request.form['password'])).fetchone()
        con.close()
        if admin:
            session['logged_in']=True
            return redirect('/dashboard')
        return render_template_string(HTML_LAYOUT,is_logged=False,content="<p style='color:red;text-align:center'>خطأ بالدخول</p><form method='post'><input name='phone' placeholder='هاتف'><input type='password' name='password' placeholder='كلمة السر'><button>دخول</button></form>")
    return render_template_string(HTML_LAYOUT,is_logged=False,content="<form method='post'><input name='phone' placeholder='هاتف' required><input type='password' name='password' placeholder='كلمة السر' required><button>دخول</button></form>")

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect('/login')
    view=request.args.get('view','subs')
    con=sqlite3.connect(DB)
    content=""
    if view=='subs':
        subs=con.execute("SELECT id,name,phone,speed,status FROM subs").fetchall()
        con.close()
        rows=""
        for sid,name,phone,speed,status in subs:
            rows+=f"<tr><td>{name}</td><td>{phone}</td><td>{speed or '-'}</td><td>{status}</td><td><a href='/toggle_status/{sid}' style='color:#d4af37'>تغيير</a> | <a href='/del_sub/{sid}' style='color:red' onclick='return confirm(\"حذف؟\")'>حذف</a></td></tr>"
        content=f"<h3>المشتركون ({len(subs)})</h3><table><tr><th>الاسم</th><th>هاتف</th><th>سرعة</th><th>حالة</th><th>تحكم</th></tr>{rows}</table>"
    elif view=='add_sub':
        con.close()
        content="<h3>اضافة مشترك</h3><form method='post' action='/add_sub'><input name='name' placeholder='الاسم' required><input name='phone' placeholder='الهاتف' required><input name='speed' placeholder='السرعة'><select name='status'><option>نشط</option><option>موقوف</option></select><button>حفظ</button></form>"
    else:
        con.close()
        content="<h3>مرحبا</h3>"
    return render_template_string(HTML_LAYOUT,is_logged=True,content=content)

@app.route('/add_sub',methods=['POST'])
def add_sub():
    if not session.get('logged_in'): return redirect('/login')
    con=sqlite3.connect(DB)
    cur=con.cursor()
    cur.execute("INSERT INTO subs (name,phone,speed,status) VALUES (?,?,?,?)",(request.form['name'],request.form['phone'],request.form.get('speed',''),request.form.get('status','نشط')))
    sid=cur.lastrowid
    cur.execute("INSERT INTO accounts (sub_id) VALUES (?)",(sid,))
    con.commit();con.close()
    return redirect('/dashboard?view=subs')

@app.route('/toggle_status/<int:sid>')
def toggle_status(sid):
    if not session.get('logged_in'): return redirect('/login')
    con=sqlite3.connect(DB)
    cur=con.execute("SELECT status FROM subs WHERE id=?",(sid,)).fetchone()
    if cur:
        new='موقوف' if cur[0]=='نشط' else 'نشط'
        con.execute("UPDATE subs SET status=? WHERE id=?",(new,sid))
        con.commit()
    con.close()
    return redirect('/dashboard?view=subs')

@app.route('/del_sub/<int:sid>')
def del_sub(sid):
    if not session.get('logged_in'): return redirect('/login')
    con=sqlite3.connect(DB)
    con.execute("DELETE FROM subs WHERE id=?",(sid,))
    con.commit();con.close()
    return redirect('/dashboard?view=subs')

if __name__=='__main__':
    port=int(os.environ.get('PORT',10000))
    app.run(host='0.0.0.0',port=port)
