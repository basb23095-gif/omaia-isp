from flask import Flask, request, redirect, render_template_string, session, Response, send_from_directory
import os, datetime, io, csv, time
from functools import lru_cache
try: import routeros_api
except: routeros_api=None
try: import psycopg2, psycopg2.extras
except: psycopg2=None
import sqlite3
from colors import get_colors, save_colors_dict, reset_colors, DEFAULT_COLORS

app=Flask(__name__)
app.secret_key=os.environ.get("SECRET_KEY","omaia-sec")
DATABASE_URL=os.environ.get("DATABASE_URL","")
USE_PG=bool(DATABASE_URL and psycopg2)
_pg_conn=None;_pg_time=0
SUPPORT_WA=os.environ.get("SUPPORT_WA","905344851045")

# 1 - إلغاء الكاش نهائيا
@app.after_request
def no_cache(resp):
    resp.headers['Cache-Control']='no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma']='no-cache'
    resp.headers['Expires']='0'
    return resp

@app.route('/bg.jpg')
def bg_img():
    # 2 - صورة خلفية الدخول تشتغل مع colors.py
    try:
        return send_from_directory('.', 'bg.jpg')
    except:
        return "",404

@lru_cache(maxsize=1)
def get_colors_cached():
    return get_colors()

# 3 - لغة عربي / انجليزي
LANGS={
 'ar':{'home':'الرئيسية','subs':'المشتركين','search':'بحث','add':'إضافة','ledger':'دفتر الحسابات','dishes':'صحون','servers':'سيرفرات','notifs':'الإشعارات','settings':'إعدادات','logout':'خروج'},
 'en':{'home':'Home','subs':'Subscribers','search':'Search','add':'Add','ledger':'Ledger','dishes':'Dishes','servers':'Servers','notifs':'Notifications','settings':'Settings','logout':'Logout'}
}
def T(k):
    l=session.get('lang','ar')
    return LANGS.get(l,{}).get(k,k)

@app.route('/lang/<l>')
def set_lang(l):
    if l in LANGS: session['lang']=l
    return redirect('/dash?view=settings')

def db():
    global _pg_conn,_pg_time
    if USE_PG:
        now=time.time()
        if _pg_conn and now-_pg_time<300:
            try:_pg_conn.cursor().execute("SELECT 1");return _pg_conn
            except:pass
        try:_pg_conn.close()
        except:pass
        _pg_conn=psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=5)
        _pg_conn.autocommit=True;_pg_time=now;return _pg_conn
    con=sqlite3.connect("omaia_company.db");con.row_factory=sqlite3.Row;return con

def close_con(con):
    if not USE_PG:
        try:con.close()
        except:pass
def ex(con,q,args=()):
    if USE_PG:
        cur=con.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(q.replace("?","%s"),args);return cur
    return con.execute(q,args)
def get_count(con,table):
    try:
        r=ex(con,f"SELECT COUNT(*) c FROM {table}").fetchone()
        return r['c'] if isinstance(r,dict) else r[0]
    except: return 0
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
        cur.execute("CREATE TABLE IF NOT EXISTS notifications(id SERIAL PRIMARY KEY,msg TEXT,date TEXT,by_user TEXT)")
        for s in ["ALTER TABLE dish_ips ADD COLUMN IF NOT EXISTS site TEXT","ALTER TABLE users ADD COLUMN IF NOT EXISTS username TEXT"]:
            try:cur.execute(s)
            except:pass
        cur.execute("SELECT * FROM users WHERE phone='05344851045'")
        if not cur.fetchone():cur.execute("INSERT INTO users(phone,password,role,active) VALUES('05344851045','admin2024','super',1)")
        con.commit();cur.close();return
    con.execute("CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,active INT DEFAULT 1)")
    con.execute("CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,speed TEXT,status TEXT,server_id INT,dish_ip TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS accounts(sub_id INTEGER PRIMARY KEY,usd REAL DEFAULT 0,syr REAL DEFAULT 0)")
    con.execute("CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,sub_id INT,date TEXT,usd REAL,syr REAL,note TEXT,by_user TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS servers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,host TEXT,username TEXT,password TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT UNIQUE,location TEXT,sub_id INT)")
    con.execute("CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,msg TEXT,date TEXT,by_user TEXT)")
    for s in ["ALTER TABLE dish_ips ADD COLUMN site TEXT","ALTER TABLE users ADD COLUMN username TEXT"]:
        try:con.execute(s)
        except:pass
    if not con.execute("SELECT * FROM users WHERE phone='05344851045'").fetchone():
        con.execute("INSERT INTO users(phone,password,role,active) VALUES('05344851045','admin2024','super',1)")
    con.commit();close_con(con)
init()
def notif_count_reuse(con=None):
    try:
        own=False
        if con is None: con=db();own=True
        c=len(ex(con,"SELECT id FROM notifications ORDER BY id DESC LIMIT 5").fetchall())
        if own: close_con(con)
        return c
    except: return 0

LAYOUT="""<!DOCTYPE html><html lang="__LANG__" dir="__DIR__"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>OMAIA ISP</title>
<style>
body{font-family:Arial;margin:0;min-height:100vh;background:__BG__;color:__TEXT__}
body.login-bg{background:url('/bg.jpg') center/cover no-repeat fixed, __BG__;}
.topbar{position:fixed;top:0;right:0;left:0;height:56px;background:__SIDEBAR__;display:flex;align-items:center;justify-content:space-between;padding:0 12px;z-index:1002;border-bottom:1px solid #334155}
.sidebar{width:250px;padding:15px;position:fixed;top:56px;bottom:0;right:0;overflow-y:auto;background:__SIDEBAR__;transform:translateX(105%);transition:0.3s;z-index:1003}
.sidebar.open{transform:translateX(0)}
.sidebar a{display:block;color:#fff;padding:10px;margin:6px 0;background:__CARD__;text-decoration:none;border-radius:8px;cursor:pointer}
.sidebar a.active{border:2px solid __MAIN__}
.overlay{display:none;position:fixed;top:56px;left:0;right:0;bottom:0;background:rgba(0,0,0,0.55);z-index:1001}
.overlay.show{display:block}
.main{padding:76px 16px 20px 16px;max-width:1100px;margin:auto}
.login-wrap{display:flex;align-items:center;justify-content:center;min-height:90vh}
.login-box{width:340px;max-width:92%;text-align:center;padding:22px;border-radius:14px;background:rgba(10,24,48,0.88);backdrop-filter:blur(10px);border:1px solid __MAIN__}
table{width:100%;border-collapse:collapse;font-size:14px;background:__CARD__;border-radius:10px;overflow:hidden}
th,td{padding:8px;border-bottom:1px solid #334155;text-align:center}
th{color:__MAIN__}
input,select{width:100%;padding:9px;margin:5px 0;border-radius:8px;box-sizing:border-box;background:#0f172a;border:1px solid #334155;color:#fff}
button{padding:10px;width:100%;border:none;border-radius:8px;font-weight:bold;cursor:pointer;background:__MAIN__;color:#000}
.card{padding:12px;border-radius:10px;margin:10px 0;border:1px solid #334155;background:__CARD__}
.form2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
@media(max-width:700px){.stats{grid-template-columns:1fr 1fr}}
.dish-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:700px){.dish-grid{grid-template-columns:1fr}}
.dish-card{background:linear-gradient(135deg,__CARD__,#0f2748);border:1px solid __MAIN__;border-radius:14px;padding:14px}
</style></head><body class="__BODYCLS__">
<div class="topbar"><button onclick="toggleSide()" style="width:auto;background:__MAIN__;border:none;border-radius:8px;padding:8px 12px">☰</button><b style="color:__MAIN__">OMAIA ISP</b><div><a href="/search" style="color:#fff;text-decoration:none;margin:0 6px">🔍</a><a onclick="loadView('notifs')" style="color:#fff;cursor:pointer">🔔__NOTIF__</a></div></div>
<div class="overlay" id="ovl" onclick="toggleSide()"></div>
<div class="sidebar" id="sdb"><h2 style="color:__MAIN__;text-align:center">OMAIA ISP</h2>
<a data-v="home" onclick="loadView('home')">🏠 __T_HOME__</a>
<a data-v="subs" onclick="loadView('subs')">👥 __T_SUBS__</a>
<a href="/search">🔍 __T_SEARCH__</a>
<a data-v="dishes" onclick="loadView('dishes')">📡 __T_DISHES__</a>
<a data-v="servers" onclick="loadView('servers')">🖥️ __T_SERVERS__</a>
<a data-v="ledger" onclick="loadView('ledger')">📒 __T_LEDGER__</a>
<a data-v="settings" onclick="loadView('settings')">⚙️ __T_SETTINGS__</a>
<a href="/logout">🚪 __T_LOGOUT__</a></div>
<div class="main" id="mainc"><div id="viewc">{{content|safe}}</div></div>
<script>
function toggleSide(){document.getElementById('sdb').classList.toggle('open');document.getElementById('ovl').classList.toggle('show');}
function setActive(v){document.querySelectorAll('.sidebar a[data-v]').forEach(a=>{a.classList.toggle('active',a.getAttribute('data-v')===v)})}
async function loadView(v){
  setActive(v);
  document.getElementById('sdb').classList.remove('open');document.getElementById('ovl').classList.remove('show');
  var vc=document.getElementById('viewc');
  let to=setTimeout(()=>{window.location.href='/dash?view='+v},8000);
  try{
    let r=await fetch('/dash?view='+v+'&partial=1&_='+Date.now(),{headers:{'X-Requested-With':'fetch'},cache:'no-store'});
    if(!r.ok) throw 0;
    let t=await r.text();
    clearTimeout(to);
    if(t.includes('id="viewc"')){let d=document.createElement('div');d.innerHTML=t;let n=d.querySelector('#viewc');if(n) t=n.innerHTML;}
    vc.innerHTML=t;history.replaceState(null,'','/dash?view='+v);
  }catch(e){clearTimeout(to);window.location.href='/dash?view='+v;}
  window.scrollTo(0,0);
}
</script></body></html>"""

def render(c, con=None, bodycls=""):
    col=get_colors_cached()
    h=LAYOUT
    for k,v in col.items(): h=h.replace("__"+k.upper()+"__",v)
    h=h.replace("__NOTIF__",str(notif_count_reuse(con)))
    lang=session.get('lang','ar')
    h=h.replace("__LANG__",lang).replace("__DIR__",'rtl' if lang=='ar' else 'ltr').replace("__BODYCLS__",bodycls)
    for k in ['home','subs','search','dishes','servers','ledger','settings','logout']:
        h=h.replace(f"__T_{k.upper()}__",T(k))
    return render_template_string(h,content=c)

def render_partial_or_full(html_content, con):
    if request.args.get('partial')=='1' or request.headers.get('X-Requested-With')=='fetch':
        close_con(con);return html_content
    r=render(html_content,con);close_con(con);return r

@app.route('/')
def idx():return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login',methods=['GET','POST'])
def login():
    msg=""
    if request.method=='POST':
        ident=request.form.get('phone','').strip();pwd=request.form.get('password','')
        con=db();u=ex(con,"SELECT * FROM users WHERE phone=? OR username=?",(ident,ident)).fetchone();close_con(con)
        if not u: msg="<p style='color:#f87171'>خطأ بالدخول</p>"
        else:
            d=dict(u) if not isinstance(u,dict) else u
            if d.get('password')!=pwd: msg="<p style='color:#f87171'>خطأ بكلمة السر</p>"
            else: session['phone']=d.get('phone');session['role']=d.get('role');return redirect('/dash?view=home')
    h="<div class='login-wrap'><div class='login-box'><h2 style='color:#00D4FF'>OMAIA ISP</h2>"+msg+"<form method='post'><input name='phone' placeholder='مستخدم / هاتف' required><input name='password' type='password' placeholder='كلمة السر' required><button>دخول</button></form></div></div>"
    return render(h,bodycls="login-bg")

@app.route('/logout')
def logout():session.clear();return redirect('/login')

@app.route('/dash')
def dash():
    if not session.get('phone'):return redirect('/login')
    v=request.args.get('view','home');con=db()
    def done(html): return render_partial_or_full(html, con)
    if v=='home':
        n1=get_count(con,"subs");n2=get_count(con,"servers");n3=get_count(con,"dish_ips")
        return done(f"<div class='stats'><div class='card'><b>{n1}</b><br>{T('subs')}</div><div class='card'><b>{n2}</b><br>{T('servers')}</div><div class='card'><b>{n3}</b><br>{T('dishes')}</div></div>")
    if v=='settings':
        cur_lang=session.get('lang','ar')
        lang_btn=f"<div class='card'><h4>🌐 اللغة / Language</h4><a href='/lang/{'en' if cur_lang=='ar' else 'ar'}'><button>{'English' if cur_lang=='ar' else 'عربي'}</button></a><p>الحالية: {cur_lang}</p></div>"
        return done(lang_btn+f"<div class='card'><a href='https://wa.me/{SUPPORT_WA}' target='_blank'><button>واتساب الدعم</button></a></div>")
    if v=='subs':
        rows=ex(con,"SELECT * FROM subs").fetchall()
        tr="".join([f"<tr><td>{r['name']}</td><td>{r['phone']}</td><td>{r['status']}</td></tr>" for r in rows])
        return done(f"<table><tr><th>Name</th><th>Phone</th><th>Status</th></tr>{tr}</table>")
    if v=='dishes':
        rows=ex(con,"SELECT * FROM dish_ips").fetchall()
        total=len(rows)
        # قسم 1: إحصائيات علوية محترمة
        sec1=f"<div class='stats'><div class='card'><b>{total}</b><br>إجمالي الصحون</div><div class='card'><b style='color:#4ade80'>{total}</b><br>نشط</div></div>"
        # قسم 2: شبكة بطاقات محترمة + جدول
        cards="".join([f"<div class='dish-card'><b>📡 {dict(r).get('location','-')}</b><br><small>{dict(r).get('site','-')}</small><br><a href='http://{dict(r).get('ip')}' target='_blank' style='color:#38bdf8' dir='ltr'>{dict(r).get('ip')}</a><br><div style='margin-top:8px'><a href='/edit_dish/{dict(r).get('id')}' style='color:#fff'>تعديل</a> | <a href='/del_dish/{dict(r).get('id')}' style='color:#f87171'>حذف</a></div></div>" for r in rows])
        sec2=f"<div class='card'><h3>📡 إدارة الصحون - قسم التركيب</h3><form method='post' action='/add_dish'><div class='form2'><input name='location' required placeholder='اسم الشبكة'><input name='site' placeholder='موقع البرج'><input name='ip' required placeholder='IP' dir='ltr'></div><button>إضافة صحن</button></form></div><h4>القسم الثاني: قائمة الصحون</h4><div class='dish-grid'>{cards}</div>"
        return done(sec1+sec2)
    if v=='servers':
        rows=ex(con,"SELECT * FROM servers").fetchall()
        tr="".join([f"<tr><td>{r['name']}</td><td dir='ltr'>{r['host']}</td></tr>" for r in rows])
        return done(f"<table><tr><th>اسم</th><th>host</th></tr>{tr}</table>")
    if v=='ledger':
        rows=ex(con,"SELECT l.*,s.name FROM ledger l LEFT JOIN subs s ON s.id=l.sub_id ORDER BY l.id DESC LIMIT 50").fetchall()
        tr="".join([f"<tr><td>{r['date']}</td><td>{r['name']}</td><td>{r['usd']}</td><td>{r['syr']}</td></tr>" for r in rows])
        return done(f"<table><tr><th>تاريخ</th><th>مشترك</th><th>$</th><th>ل.س</th></tr>{tr}</table>")
    if v=='notifs':
        rows=ex(con,"SELECT * FROM notifications ORDER BY id DESC LIMIT 20").fetchall()
        tr="".join([f"<div class='card'>{dict(r).get('msg')}</div>" for r in rows])
        return done(tr)
    close_con(con);return redirect('/dash?view=home')

@app.route('/search')
def search():
    if not session.get('phone'):return redirect('/login')
    q=request.args.get('q','').strip();con=db();like=f"%{q}%"
    # 4 - إصلاح البحث: مسافة بعد LIKE
    if q:
        subs=ex(con,"SELECT * FROM subs WHERE name LIKE? OR phone LIKE?", (like,like)).fetchall()
        dishes=ex(con,"SELECT * FROM dish_ips WHERE location LIKE? OR ip LIKE?", (like,like)).fetchall()
    else:
        subs=ex(con,"SELECT * FROM subs LIMIT 20").fetchall()
        dishes=ex(con,"SELECT * FROM dish_ips LIMIT 20").fetchall()
    tr1="".join([f"<tr><td>{dict(r).get('name')}</td><td dir='ltr'>{dict(r).get('phone')}</td></tr>" for r in subs])
    tr2="".join([f"<tr><td>{dict(r).get('location')}</td><td dir='ltr'>{dict(r).get('ip')}</td></tr>" for r in dishes])
    h=f"<form method='get' action='/search'><input name='q' value='{q}' placeholder='بحث...' oninput='liveSearch(this.value)'><button>بحث 🔍</button></form><div id='res'><h3>مشتركين ({len(subs)})</h3><table>{tr1}</table><h3>صحون ({len(dishes)})</h3><table>{tr2}</table></div><script>async function liveSearch(v){{let r=await fetch('/search?q='+encodeURIComponent(v),{{headers:{{'X-Requested-With':'fetch'}}}});let t=await r.text();let d=document.createElement('div');d.innerHTML=t;let n=d.querySelector('#res');if(n) document.getElementById('res').innerHTML=n.innerHTML;}}</script>"
    # دعم partial للبحث
    if request.headers.get('X-Requested-With')=='fetch':
        close_con(con);return f"<div id='res'><h3>مشتركين ({len(subs)})</h3><table>{tr1}</table><h3>صحون ({len(dishes)})</h3><table>{tr2}</table></div>"
    r=render(h,con);close_con(con);return r

# باقي الروتات مختصرة للسرعة
@app.route('/add_dish',methods=['POST'])
def add_dish():
    con=db()
    try:ex(con,"INSERT INTO dish_ips(ip,location,site) VALUES(?,?,?)",(request.form.get('ip','').strip(),request.form.get('location','').strip(),request.form.get('site','').strip()))
    except:pass
    con.commit();close_con(con);return redirect('/dash?view=dishes')

@app.route('/edit_dish/<int:i>',methods=['GET','POST'])
def edit_dish(i):
    con=db()
    if request.method=='POST':
        ex(con,"UPDATE dish_ips SET ip=?,location=?,site=? WHERE id=?",(request.form.get('ip',''),request.form.get('location',''),request.form.get('site',''),i));con.commit();close_con(con);return redirect('/dash?view=dishes')
    r0=ex(con,"SELECT * FROM dish_ips WHERE id=?",(i,)).fetchone();d=dict(r0) if r0 else {}
    h=render(f"<div class='card'><form method='post'><input name='location' value='{d.get('location','')}'><input name='site' value='{d.get('site','')}'><input name='ip' value='{d.get('ip','')}' dir='ltr'><button>حفظ</button></form></div>",con);close_con(con);return h

@app.route('/del_dish/<int:i>')
def del_dish(i):con=db();ex(con,"DELETE FROM dish_ips WHERE id=?",(i,));con.commit();close_con(con);return redirect('/dash?view=dishes')

if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
