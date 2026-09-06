from flask import Flask, request, redirect, session
from colors import COLORS, logo_html
import os, datetime, json, html
try: import psycopg2, psycopg2.extras
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
        _pg=psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=5)
        _pg.autocommit=True
        return _pg
    c=sqlite3.connect("omia.db")
    c.row_factory=sqlite3.Row
    return c

def cc(c):
    if not USE_PG:
        try:c.close()
        except:pass

def qall(q,a=()):
    c=db()
    try:
        if USE_PG:
            cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(q.replace("?","%s"),a)
            rs=[dict(r) for r in cur.fetchall()]
            cur.close()
            return rs
        else:
            rs=[dict(r) for r in c.execute(q,a).fetchall()]
            cc(c)
            return rs
    except:
        cc(c);return []

def qone(q,a=()):
    r=qall(q,a)
    return r[0] if r else None

def qexec(q,a=()):
    c=db()
    try:
        if USE_PG:
            cur=c.cursor();cur.execute(q.replace("?","%s"),a);cur.close()
        else:
            c.execute(q,a);c.commit();cc(c)
    except: cc(c)

def fnum(v):
    try:return float(v or 0)
    except:return 0

def init():
    ss=[
    "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,active INT DEFAULT 1)",
    "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,active INT DEFAULT 1)",
    "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,sub_id INT,amount REAL,typ TEXT,dt TEXT)",
    "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,lat REAL DEFAULT 0,lng REAL DEFAULT 0)",
    "CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,lat REAL,lng REAL)"
    ]
    if USE_PG: ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
    for s in ss: qexec(s)
    try: qexec("ALTER TABLE users ADD COLUMN username TEXT")
    except: pass
    if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username,active) VALUES(?,?,?,?,?)",('05344851045','admin2024','super','admin',1))
init()

def dark(): return session.get('theme','light')

def page_content(v):
    h=""
    if v=='home':
        ns=(qone("SELECT COUNT(*) c FROM subs") or {}).get('c',0)
        nd=(qone("SELECT COUNT(*) c FROM dish_ips") or {}).get('c',0)
        nt=(qone("SELECT COUNT(*) c FROM towers") or {}).get('c',0)
        h=f"<div class=grid><div class=kpi style='background:#2563eb'>👥<br>{ns}</div><div class=kpi style='background:#16a34a'>📡<br>{nd}</div><div class=kpi style='background:#dc2626'>🗼<br>{nt}</div></div><div class=card>مرحبا {esc(session.get('phone'))}</div>"
    elif v=='subs':
        rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 100")
        h="<div class=card><h3>👥 مشتركين</h3><form data-ajax method=post action=/add_sub><input name=name required placeholder=الاسم><input name=phone placeholder=هاتف><button>اضافة</button></form></div>"
        for r in rs:
            h+=f"<div class=card>{esc(r['name'])} - {esc(r['phone'])} <a href=/del_sub/{r['id']} data-del style='color:red'>حذف</a></div>"
    elif v=='dishes':
        rs=qall("SELECT * FROM dish_ips ORDER BY id DESC LIMIT 200")
        h="<div class=card><h3>📡 صحون</h3><form data-ajax method=post action=/add_dish><input name=ip required placeholder=IP><input name=location placeholder=موقع><input name=lat placeholder=lat><input name=lng placeholder=lng><button>اضافة</button></form></div>"
        for r in rs:
            h+=f"<div class=card><a href='http://{esc(r['ip'])}' target=_blank>{esc(r['ip'])}</a> {esc(r.get('location',''))} <a href=/del_dish/{r['id']} data-del style='color:red'>حذف</a></div>"
    elif v=='towers':
        rs=qall("SELECT * FROM towers ORDER BY id DESC LIMIT 100")
        h="<div class=card><h3>🗼 ابراج</h3><form data-ajax method=post action=/add_tower><input name=name required placeholder=اسم><input name=lat placeholder=lat><input name=lng placeholder=lng><button>اضافة</button></form></div>"
        for r in rs:
            h+=f"<div class=card>{esc(r['name'])} <a href=/del_tower/{r['id']} data-del style='color:red'>حذف</a></div>"
    elif v=='ledger':
        rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 100")
        h="<div class=card><h3>📒 دفتر</h3><form data-ajax method=post action=/add_ledger><input name=amount type=number step=0.01 required placeholder=مبلغ><select name=typ><option>دين</option><option>دفع</option></select><button>اضافة</button></form></div>"
        for r in rs:
            h+=f"<div class=card>{r['amount']} {esc(r['typ'])} <a href=/del_ledger/{r['id']} data-del style='color:red'>حذف</a></div>"
    elif v=='map':
        ds=qall("SELECT lat,lng,location,ip FROM dish_ips WHERE lat!=0 LIMIT 300")
        dj=json.dumps([{"la":float(d.get("lat") or 0),"ln":float(d.get("lng") or 0),"n":str(d.get("location","")),"ip":str(d.get("ip",""))} for d in ds if d.get("lat")]).replace("</","<\\/")
        h=f"<div class=card><h3>🗺️ خريطة</h3><div id=mp style='height:70vh;border-radius:10px'></div></div><script>var DS={dj};initMap();</script>"
    elif v=='settings':
        h="<div class=card><h3>⚙️ اعدادات</h3><form data-ajax method=post action=/change_user><input name=newphone required placeholder='يوزر جديد رقم/اسم'><button>تغيير اليوزر</button></form><form data-ajax method=post action=/change_pass><input name=newpass type=password required placeholder='كلمة جديدة'><button>تغيير كلمة السر</button></form><a href=/toggle_theme data-ajax>🌙/☀️ تبديل الثيم</a></div>"
    return h

def layout(c,v='home'):
    th=dark()
    bg=COLORS['bg_dark'] if th=='dark' else COLORS['bg_light']
    card=COLORS['card_dark'] if th=='dark' else COLORS['card_light']
    txt='#fff' if th=='dark' else '#000'
    return f"""<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<link rel=stylesheet href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'>
<style>
*{{box-sizing:border-box}}body{{margin:0;font-family:sans-serif;background:{bg};color:{txt}}}
.top{{position:fixed;top:0;left:0;right:0;background:{COLORS['top_bg']};color:#fff;padding:12px;text-align:center;z-index:100;font-weight:bold}}
.menu{{position:fixed;top:48px;bottom:0;right:0;width:200px;background:{COLORS['menu_bg']};padding:10px;z-index:99}}
.menu a{{display:block;color:#fff;text-decoration:none;padding:11px;border-radius:8px;margin:2px 0}}
.menu a:hover{{background:#ffffff20}}
.main{{margin-right:210px;margin-top:60px;padding:10px}}
.card{{background:{card};padding:10px;border-radius:10px;margin:8px 0}}
.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}}
.kpi{{padding:12px;border-radius:10px;color:#fff;text-align:center;font-weight:bold}}
input,select{{width:100%;padding:8px;margin:4px 0;border-radius:7px;border:1px solid #ccc}}
button{{background:{COLORS['btn']};color:#fff;border:0;padding:8px 12px;border-radius:7px;cursor:pointer}}
@media(max-width:700px){{.menu{{width:180px}}.main{{margin-right:0}}}}
</style></head><body>
<div class=top>{logo_html()}</div>
<div class=menu>
<a href="javascript:loadPage('home')">🏠 الرئيسية</a>
<a href="javascript:loadPage('subs')">👥 مشتركين</a>
<a href="javascript:loadPage('ledger')">📒 دفتر</a>
<a href="javascript:loadPage('dishes')">📡 صحون</a>
<a href="javascript:loadPage('towers')">🗼 ابراج</a>
<a href="javascript:loadPage('map')">🗺️ خريطة</a>
<a href="javascript:loadPage('settings')">⚙️ اعدادات</a>
<a href=/logout>🚪 خروج</a>
</div>
<div class=main id=main>{c}</div>
<div id=loader style='position:fixed;top:0;left:0;height:3px;background:#22c55e;width:0;z-index:200;transition:.2s'></div>
<script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>
<script>
var curV='{v}';
window.loadPage=async function(v){{
curV=v;
var L1=document.getElementById('loader');L1.style.width='40%';
try{{
var r=await fetch('/api/page?v='+v);
var h=await r.text();
var m=document.getElementById('main');
m.innerHTML=h;
m.querySelectorAll('script').forEach(s=>{{try{{eval(s.textContent)}}catch(e){{}}}});
bindAjax();
}}catch(e){{}}
L1.style.width='100%';setTimeout(()=>L1.style.width='0',250);
window.scrollTo({{top:0,behavior:'smooth'}});
}};
function initMap(){{
if(typeof L=='undefined'){{setTimeout(initMap,300);return}}
var m=L.map('mp').setView([35.13,36.75],12);
L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',{{maxZoom:18}}).addTo(m);
if(typeof DS!='undefined')DS.forEach(d=>L.marker([d.la,d.ln]).addTo(m).bindPopup(d.n+'<br>'+d.ip));
setTimeout(()=>m.invalidateSize(),300);
}};
function bindAjax(){{
document.querySelectorAll('form[data-ajax]').forEach(f=>{{
f.onsubmit=async e=>{{e.preventDefault();await fetch(f.action,{{method:'POST',body:new FormData(f)}});loadPage(curV)}};
}});
document.querySelectorAll('a[data-ajax]').forEach(a=>{{
a.onclick=async e=>{{e.preventDefault();await fetch(a.href);loadPage(curV)}};
}});
document.querySelectorAll('a[data-del]').forEach(a=>{{
a.onclick=async e=>{{e.preventDefault();if(confirm('حذف؟')){{await fetch(a.href);loadPage(curV)}}}};
}});
}};
bindAjax();
</script></body></html>"""

@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        uin=request.form.get('userin','').strip()
        pw=request.form.get('password','')
        u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
        if u and u['password']==pw:
            session['phone']=u['phone']
            return redirect('/dash')
    return f"""<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<style>body{{display:flex;align-items:center;justify-content:center;background:{COLORS['bg_dark']};min-height:100vh;margin:0;font-family:sans-serif}}.box{{background:#fff;padding:20px;border-radius:12px;width:92%;max-width:340px}}input{{width:100%;padding:10px;margin:6px 0;border-radius:8px;border:1px solid #ccc}}button{{width:100%;background:{COLORS['btn']};color:#fff;padding:10px;border:0;border-radius:8px}}</style>
</head><body><div class=box><h3 style='text-align:center'>{logo_html()}</h3>
<form method=post><input name=userin placeholder='رقم هاتف / اسم مستخدم' required><input name=password type=password placeholder='كلمة السر' required><button>دخول</button></form>
</div></body></html>"""

@app.route('/logout')
def lo():
    session.clear()
    return redirect('/login')

@app.route('/dash')
def dash():
    if not session.get('phone'): return redirect('/login')
    v=request.args.get('v','home')
    return layout(page_content(v),v)

@app.route('/api/page')
def ap():
    if not session.get('phone'): return "login"
    return page_content(request.args.get('v','home'))

@app.route('/toggle_theme')
def tt():
    session['theme']='dark' if dark()!='dark' else 'light'
    return "ok"

@app.route('/add_sub',methods=['POST'])
def a1():
    qexec("INSERT INTO subs(name,phone) VALUES(?,?)",(request.form.get('name',''),request.form.get('phone','')))
    return "ok"

@app.route('/del_sub/<int:i>')
def a4(i):
    qexec("DELETE FROM subs WHERE id=?",(i,))
    return "ok"

@app.route('/add_ledger',methods=['POST'])
def b1():
    f=request.form
    qexec("INSERT INTO ledger(amount,typ,dt) VALUES(?,?,?)",(fnum(f.get('amount')),f.get('typ','دين'),datetime.datetime.now().isoformat()))
    return "ok"

@app.route('/del_ledger/<int:i>')
def b2(i):
    qexec("DELETE FROM ledger WHERE id=?",(i,))
    return "ok"

@app.route('/add_dish',methods=['POST'])
def c1():
    f=request.form
    qexec("INSERT INTO dish_ips(ip,location,lat,lng) VALUES(?,?,?,?)",(f.get('ip',''),f.get('location',''),fnum(f.get('lat')),fnum(f.get('lng'))))
    return "ok"

@app.route('/del_dish/<int:i>')
def c2(i):
    qexec("DELETE FROM dish_ips WHERE id=?",(i,))
    return "ok"

@app.route('/add_tower',methods=['POST'])
def d1():
    f=request.form
    qexec("INSERT INTO towers(name,lat,lng) VALUES(?,?,?)",(f.get('name',''),fnum(f.get('lat')),fnum(f.get('lng'))))
    return "ok"

@app.route('/del_tower/<int:i>')
def d2(i):
    qexec("DELETE FROM towers WHERE id=?",(i,))
    return "ok"

@app.route('/change_user',methods=['POST'])
def e1():
    o=session.get('phone')
    n=request.form.get('newphone','').strip()
    if n.isdigit():
        qexec("UPDATE users SET phone=? WHERE phone=?",(n,o))
        session['phone']=n
    else:
        qexec("UPDATE users SET username=? WHERE phone=?",(n,o))
    return "ok"

@app.route('/change_pass',methods=['POST'])
def e2():
    qexec("UPDATE users SET password=? WHERE phone=?",(request.form.get('newpass',''),session.get('phone')))
    return "ok"

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
