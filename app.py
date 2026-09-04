from flask import Flask, request, redirect, render_template_string, session, Response, url_for
import os, datetime, io, csv, json
try: import routeros_api
except: routeros_api=None
try: import psycopg2, psycopg2.extras
except: psycopg2=None
import sqlite3

app=Flask(__name__)
app.secret_key=os.environ.get("SECRET_KEY","omaia-sec")
DATABASE_URL=os.environ.get("DATABASE_URL","")
USE_PG=bool(DATABASE_URL and psycopg2)

DEFAULT_COLORS={"main":"#d4af37","bg":"#0b0f19","card":"#1a2336"}

def db():
    if USE_PG:
        return psycopg2.connect(DATABASE_URL, sslmode='require')
    con=sqlite3.connect("omaia_company.db")
    con.row_factory=sqlite3.Row
    return con

def ex(con,q,args=()):
    if USE_PG:
        cur=con.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(q.replace("?","%s"), args)
        return cur
    return con.execute(q,args)

def get_colors():
    try:
        con=db()
        ex(con,"CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY,v TEXT)")
        con.commit()
        r=ex(con,"SELECT v FROM settings WHERE k='colors'").fetchone()
        con.close()
        if r:
            v=r['v'] if isinstance(r,dict) else r[0]
            return json.loads(v)
    except: pass
    return DEFAULT_COLORS

def init():
    con=db()
    if USE_PG:
        cur=con.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,active INT DEFAULT 1)")
        cur.execute("CREATE TABLE IF NOT EXISTS subs(id SERIAL PRIMARY KEY,name TEXT,phone TEXT,speed TEXT,status TEXT,server_id INT,dish_ip TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS accounts(sub_id INT PRIMARY KEY,usd FLOAT DEFAULT 0,syr FLOAT DEFAULT 0)")
        cur.execute("CREATE TABLE IF NOT EXISTS ledger(id SERIAL PRIMARY KEY,sub_id INT,date TEXT,usd FLOAT,syr FLOAT,note TEXT,by_user TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS servers(id SERIAL PRIMARY KEY,name TEXT,host TEXT,username TEXT,password TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS dish_ips(id SERIAL PRIMARY KEY,ip TEXT UNIQUE,location TEXT,sub_id INT)")
        cur.execute("CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY,v TEXT)")
        cur.execute("SELECT * FROM users WHERE phone='0900000000'")
        if not cur.fetchone():
            cur.execute("INSERT INTO users(phone,password,role,active) VALUES('0900000000','admin123','super',1)")
        con.commit();cur.close();con.close();return
    con.execute("CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,active INT DEFAULT 1)")
    con.execute("CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,speed TEXT,status TEXT,server_id INT,dish_ip TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS accounts(sub_id INTEGER PRIMARY KEY,usd REAL DEFAULT 0,syr REAL DEFAULT 0)")
    con.execute("CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,sub_id INT,date TEXT,usd REAL,syr REAL,note TEXT,by_user TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS servers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,host TEXT,username TEXT,password TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT UNIQUE,location TEXT,sub_id INT)")
    con.execute("CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY,v TEXT)")
    if not con.execute("SELECT * FROM users WHERE phone='0900000000'").fetchone():
        con.execute("INSERT INTO users VALUES('0900000000','admin123','super',1)")
    con.commit();con.close()
init()

def mk_action(host,user,pwd,action,ip):
    if not routeros_api: return
    try:
        pool=routeros_api.RouterOsApiPool(host,username=user,password=pwd,plaintext_login=True)
        api=pool.get_api(); lst=api.get_resource('/ip/firewall/address-list')
        if action=='block': lst.add(list='Blocked',address=ip,comment='OMAIA')
        else:
            for e in lst.get(address=ip): lst.remove(id=e['id'])
        pool.disconnect()
    except: pass

def mk_online(s):
    if not routeros_api: return []
    try:
        pool=routeros_api.RouterOsApiPool(s['host'],username=s['username'],password=s['password'],plaintext_login=True)
        api=pool.get_api(); r=api.get_resource('/ppp/active').get(); pool.disconnect(); return r
    except: return []

LAYOUT="""<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OMAIA</title>
<style>
body{font-family:Arial;background:__BG__;color:#fff;margin:0;display:flex;min-height:100vh}
.sidebar{width:230px;background:#111827;border-left:2px solid __MAIN__;padding:15px;position:fixed;left:0;top:0;bottom:0;overflow-y:auto;right:0}
.sidebar h2{color:__MAIN__;text-align:center;font-size:18px;border-bottom:1px solid #2a344a;padding-bottom:10px}
.sidebar a{display:block;background:#1f2937;color:#fff;padding:12px;margin:8px 0;border-radius:10px;text-decoration:none;font-size:14px;font-weight:bold}
.sidebar a:hover,.sidebar a.active{background:__MAIN__;color:#000}
.main{margin-right:230px;flex:1;padding:20px;width:calc(100% - 230px)}
.topbar{background:#111827;color:__MAIN__;padding:14px;border-radius:12px;margin-bottom:15px;text-align:center;border:1px solid __MAIN__}
table{width:100%;border-collapse:collapse;font-size:14px;margin-top:10px}th,td{padding:10px;border-bottom:1px solid #2a344a;text-align:center}th{color:__MAIN__;background:__CARD__}
input,select,textarea{width:100%;padding:9px;margin:5px 0;background:#1f2937;border:1px solid #374151;color:#fff;border-radius:8px;box-sizing:border-box}
button{background:__MAIN__;color:#000;padding:10px;width:100%;border:none;border-radius:8px;font-weight:bold;cursor:pointer;margin-top:5px}
button:hover{opacity:0.9}
.card{background:__CARD__;padding:15px;border-radius:10px;margin:10px 0;border:1px solid #2a344a}
.badge{padding:3px 10px;border-radius:20px;font-size:12px}.on{background:#065f46;color:#34d399}.off{background:#7f1d1d;color:#fca5a5}
.flex-grid{display:flex;gap:15px;flex-wrap:wrap}
.flex-col{flex:1;min-width:250px}
@media(max-width:768px){.sidebar{width:70px}.sidebar a{font-size:11px;padding:8px;text-align:center}.sidebar h2{font-size:12px}.main{margin-right:70px;width:calc(100% - 70px)}}
</style></head><body>
<div class="sidebar"><h2>🏢 OMAIA</h2>
{% if sess %}
<a href="/dash?view=subs">🏠 المشتركين</a>
<a href="/search">🔍 بحث سريع</a>
<a href="/dash?view=add">➕ إضافة مشترك</a>
<a href="/dash?view=ledger">💰 الحسابات والمالية</a>
<a href="/dash?view=dishes">📡 إدارة الصحون</a>
<a href="/dash?view=servers">🖥️ السيرفرات</a>
{% if role=='super' %}<a href="/dash?view=users">👥 المستخدمين</a><a href="/dash?view=settings">⚙️ إعدادات</a>{% endif %}
<a href="/logout" style="background:#7f1d1d;color:#fff;margin-top:20px">خروج</a>
{% endif %}</div>
<div class="main"><div class="topbar">نظام إدارة شركة الإنترنت والاتصالات - OMAIA</div>{{content|safe}}</div>
</body></html>"""

def render(c):
    col=get_colors()
    html=LAYOUT.replace("__MAIN__",col["main"]).replace("__BG__",col["bg"]).replace("__CARD__",col["card"])
    return render_template_string(html,content=c,sess=session.get('phone'),role=session.get('role'))

@app.route('/')
def idx(): return redirect('/dash') if session.get('phone') else redirect('/login')
@app.route('/dashboard')
def old(): return redirect('/dash')

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        con=db(); u=ex(con,"SELECT * FROM users WHERE phone=? AND password=? AND active=1",(request.form['phone'],request.form['password'])).fetchone(); con.close()
        if u:
            session['phone']=u['phone'] if isinstance(u,dict) else u[0]
            session['role']=u['role'] if isinstance(u,dict) else u[2]
            return redirect('/dash')
        return render("<div style='max-width:360px;margin:30px auto;'><p style='color:red;text-align:center'>بيانات الدخول خاطئة أو الحساب غير نشط</p><form method='post'><input name='phone' required placeholder='الهاتف'><input type='password' name='password' required placeholder='كلمة السر'><button>دخول</button></form></div>")
    return render("<div style='max-width:360px;margin:30px auto'><h3 style='text-align:center'>تسجيل الدخول للنظام</h3><form method='post'><input name='phone' required placeholder='الهاتف'><input type='password' name='password' required placeholder='كلمة السر'><button>دخول</button></form></div>")

@app.route('/logout')
def logout(): session.clear(); return redirect('/login')

@app.route('/dash', methods=['GET', 'POST'])
def dash():
    if not session.get('phone'): return redirect('/login')
    v = request.args.get('view', 'subs')
    con = db()
    out = ""

    # 1. VIEW SUB-LIST
    if v == 'subs':
        out += "<h3>👥 قائمة المشتركين</h3>"
        out += "<table style='width:100%'><tr><th>المعرف</th><th>الاسم</th><th>الهاتف</th><th>السرعة</th><th>الحالة</th><th>IP الصحن</th><th>العمليات</th></tr>"
        rows = ex(con, "SELECT * FROM subs").fetchall()
        for r in rows:
            st_class = "on" if r['status'] == 'active' else "off"
            st_text = "نشط" if r['status'] == 'active' else "محظور"
            out += f"""<tr>
                <td>{r['id']}</td>
                <td><b>{r['name']}</b></td>
                <td>{r['phone']}</td>
                <td>{r['speed']}</td>
                <td><span class='badge {st_class}'>{st_text}</span></td>
                <td>{r['dish_ip'] or '-'}</td>
                <td>
                    <a href="/action?ac=toggle&id={r['id']}" style='color:#d4af37; text-decoration:none;'>🔄 تغيير الحالة</a> | 
                    <a href="/dash?view=ledger&sub_id={r['id']}" style='color:#34d399; text-decoration:none;'>💰 الحساب</a>
                </td>
            </tr>"""
        out += "</table>"

    # 2. ADD SUBSCRIBER
    elif v == 'add':
        if request.method == 'POST':
