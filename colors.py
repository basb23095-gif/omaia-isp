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

# --- نظام الألوان الجديد: أزرق غامق مع لمسات وعناصر باللون البني والأيقونات البنية ---
DEFAULT_COLORS = {
    "BG": "linear-gradient(180deg, #0a1128 0%, #101f42 60%, #060b18 100%)", # أزرق داكن فاخر
    "SIDEBAR": "#0d1b3e",                                                  # أزرق غامق متناسق للقائمة
    "CARD": "#16264f",                                                     # بطاقات وجداول بلون أزرق مائل للعمق
    "MAIN": "#cd9a62",                                                     # البني الذهبي/الترابي الأنيق للأزرار والأيقونات والحدود
    "TEXT": "#e6ecf8",                                                     # خط مقروء وواضح جداً مائل للبياض الأزرق
    "LOGIN_BG": "linear-gradient(180deg, #0a1128 0%, #101f42 100%)"
}
_colors = DEFAULT_COLORS.copy()

def get_colors(): 
    try:
        con=db()
        ex(con,"CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY,v TEXT)")
        con.commit()
        r=ex(con,"SELECT v FROM settings WHERE k='colors'").fetchone()
        con.close()
        if r:
            v=r['v'] if isinstance(r,dict) else r
            db_cols = json.loads(v)
            _colors.update(db_cols)
            return _colors.copy()
    except: pass
    return _colors.copy()

def save_colors_dict(d):
    global _colors; _colors.update(d)
    try:
        con=db()
        js = json.dumps(_colors)
        if USE_PG:
            ex(con, "INSERT INTO settings (k, v) VALUES ('colors', %s) ON CONFLICT (k) DO UPDATE SET v = %s", (js, js))
        else:
            con.execute("INSERT OR REPLACE INTO settings (k, v) VALUES ('colors', ?)", (js,))
        con.commit(); con.close()
    except: pass

def reset_colors():
    global _colors; _colors = DEFAULT_COLORS.copy()
    try:
        con=db()
        ex(con, "DELETE FROM settings WHERE k='colors'")
        con.commit(); con.close()
    except: pass

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

LAYOUT="""<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OMAIA</title>
<style>
body{{font-family:Arial;background:__BG__;background-attachment:fixed;color:__TEXT__;margin:0;display:flex;min-height:100vh}}
.sidebar{{width:230px;background:__SIDEBAR__;border-left:2px solid __MAIN__;padding:15px;position:fixed;right:0;top:0;bottom:0;overflow-y:auto}}
.sidebar h2{{color:__MAIN__;text-align:center;font-size:18px;border-bottom:1px solid rgba(255,255,255,0.1);padding-bottom:10px}}
.sidebar a{{display:block;background:rgba(255,255,255,0.03);color:__TEXT__;padding:12px;margin:8px 0;border-radius:10px;text-decoration:none;font-size:14px;font-weight:bold;border:1px solid rgba(255,255,255,0.05)}}
.sidebar a:hover,.sidebar a.active{{background:__MAIN__;color:#101f42}}
.main{{margin-right:230px;flex:1;padding:20px;width:calc(100% - 230px)}}
.topbar{{background:__SIDEBAR__;color:__MAIN__;padding:14px;border-radius:12px;margin-bottom:15px;text-align:center;border:1px solid __MAIN__}}
table{{width:100%;border-collapse:collapse;font-size:14px;margin-top:10px}}th,td{{padding:10px;border-bottom:1px solid rgba(255,255,255,0.08);text-align:center}}th{{color:__MAIN__;background:__CARD__}}
input,select,textarea{{width:100%;padding:9px;margin:5px 0;background:rgba(0,0,0,0.2);border:1px solid rgba(255,255,255,0.1);color:#fff;border-radius:8px;box-sizing:border-box}}
input:focus,select:focus,textarea:focus{{border-color:__MAIN__;outline:none}}
button{{background:__MAIN__;color:#101f42;padding:10px;width:100%;border:none;border-radius:8px;font-weight:bold;cursor:pointer;margin-top:5px}}
button:hover{{opacity:0.9}}
.card{{background:__CARD__;padding:15px;border-radius:10px;margin:10px 0;border:1px solid rgba(255,255,255,0.05)}}
.badge{{padding:3px 10px;border-radius:20px;font-size:12px}}.on{{background:#065f46;color:#34d399}}.off{{background:#7f1d1d;color:#fca5a5}}
.flex-grid{{display:flex;gap:15px;flex-wrap:wrap}}
.flex-col{{flex:1;min-width:250px}}
.icon-style{{color:__MAIN__;margin-left:5px}} /* تنسيق الأيقونات البنية */
@media(max-width:768px){{.sidebar{{width:70px}}.sidebar a{{font-size:11px;padding:8px;text-align:center}}.sidebar h2{{font-size:12px}}.main{{margin-right:70px;width:calc(100% - 70px)}}}}
</style></head><body>
<div class="sidebar"><h2>🏢 OMAIA</h2>
{% if sess %}
<a href="/dash?view=subs"><span class="icon-style">🟫</span> المشتركين</a>
<a href="/search"><span class="icon-style">🟫</span> بحث سريع</a>
<a href="/dash?view=add"><span class="icon-style">🟫</span> إضافة مشترك</a>
<a href="/dash?view=ledger"><span class="icon-style">🟫</span> الحسابات والمالية</a>
<a href="/dash?view=dishes"><span class="icon-style">🟫</span> إدارة الصحون</a>
<a href="/dash?view=servers"><span class="icon-style">🟫</span> السيرفرات</a>
{% if role=='super' %}<a href="/dash?view=users"><span class="icon-style">🟫</span> المستخدمين</a><a href="/dash?view=settings"><span class="icon-style">🟫</span> إعدادات</a>{% endif %}
<a href="/logout" style="background:#7f1d1d;color:#fff;margin-top:20px">خروج</a>
{% endif %}</div>
<div class="main"><div class="topbar">نظام إدارة شركة الإنترنت والاتصالات - OMAIA</div>{{content|safe}}</div>
</body></html>"""

def render(c, is_login=False):
    col = get_colors()
    bg_style = col["LOGIN_BG"] if is_login else col["BG"]
    
    html = LAYOUT.replace("__BG__", bg_style)\
                 .replace("__SIDEBAR__", col["SIDEBAR"])\
                 .replace("__CARD__", col["CARD"])\
                 .replace("__MAIN__", col["MAIN"])\
                 .replace("__TEXT__", col["TEXT"])
    return render_template_string(html, content=c, sess=session.get('phone'), role=session.get('role'))

@app.route('/')
def idx(): return redirect('/dash') if session.get('phone') else redirect('/login')
@app.route('/dashboard')
def old(): return redirect('/dash')

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        con=db(); u=ex(con,"SELECT * FROM users WHERE phone=? AND password=? AND active=1",(request.form['phone'],request.form['password'])).fetchone(); con.close()
        if u:
            session['phone']=u['phone'] if isinstance(u,dict) else u
            session['role']=u['role'] if isinstance(u,dict) else u
            return redirect('/dash')
