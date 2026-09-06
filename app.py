from flask import Flask, request, redirect, session, jsonify
import os, datetime, json
try:
    import psycopg2, psycopg2.extras
except: psycopg2=None
import sqlite3

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY","omia-sec-2026")
DATABASE_URL = os.environ.get("DATABASE_URL","").strip().replace("postgresql://","postgres://")
USE_PG = bool(DATABASE_URL.startswith("postgres://") and psycopg2)
_pg=None
SUPPORT_WA="905344851045"

def db():
    global _pg
    if USE_PG:
        if _pg:
            try:_pg.cursor().execute("SELECT 1");return _pg
            except:pass
        _pg=psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=5);_pg.autocommit=True;return _pg
    c=sqlite3.connect("omia.db");c.row_factory=sqlite3.Row;return c
def cc(c):
    if not USE_PG:
        try:c.close()
        except:pass
def ex(c,q,a=()):
    if USE_PG:
        cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor);cur.execute(q.replace("?","%s"),a);return cur
    return c.execute(q,a)
def sc(c):
    try:c.commit()
    except:pass
def fnum(v):
    try:return float(v or 0)
    except:return 0

def init():
    c=db()
    ss=[
    "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,active INT DEFAULT 1)",
    "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,active INT DEFAULT 1,notes TEXT)",
    "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,sub_id INT,amount REAL,typ TEXT,note TEXT,dt TEXT)",
    "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,lat REAL DEFAULT 0,lng REAL DEFAULT 0)",
    "CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,lat REAL,lng REAL)",
    "CREATE TABLE IF NOT EXISTS notifs(id INTEGER PRIMARY KEY AUTOINCREMENT,txt TEXT,dt TEXT)",
    "CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,phone TEXT,act TEXT,dt TEXT)"
    ]
    if USE_PG: ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
    if USE_PG:
        cur=c.cursor()
        for s in ss:cur.execute(s)
        cur.execute("SELECT * FROM users WHERE phone='05344851045'")
        if not cur.fetchone():cur.execute("INSERT INTO users(phone,password,role,active) VALUES('05344851045','admin2024','super',1)")
        cur.close()
    else:
        for s in ss:c.execute(s)
        if not c.execute("SELECT * FROM users WHERE phone='05344851045'").fetchone():
            c.execute("INSERT INTO users(phone,password,role,active) VALUES('05344851045','admin2024','super',1)")
        sc(c);cc(c)
init()

def L():
    return session.get('lang','ar')
def T(ar,en): return ar if L()=='ar' else en
def dark(): return session.get('theme','light')

def layout(content, title="OMAIA ISP"):
    lang=L(); th=dark(); rtl='rtl' if lang=='ar' else 'ltr'
    bg='#0f172a' if th=='dark' else '#f1f5f9'
    card='#1e293b' if th=='dark' else '#ffffff'
    txt='#f1f5f9' if th=='dark' else '#0f172a'
    menu_bg='#1e3a8a' # مو شفاف ثابت
    wa=f"https://wa.me/{SUPPORT_WA}"
    return f"""<html dir="{rtl}" lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{{box-sizing:border-box;transition:all .25s ease}}
body{{margin:0;font-family:sans-serif;background:{bg};color:{txt};padding-bottom:80px}}
.top{{position:fixed;top:0;left:0;right:0;background:{menu_bg};color:#fff;padding:12px;display:flex;justify-content:space-between;align-items:center;z-index:100}}
.menu{{position:fixed;top:52px;bottom:0;{'right:0' if rtl=='rtl' else 'left:0'};width:220px;background:{menu_bg};color:#fff;padding:10px;z-index:99;overflow:auto}}
.menu a{{display:block;color:#fff;text-decoration:none;padding:12px;border-radius:10px;margin:4px 0}}
.menu a:hover{{background:#ffffff33;transform:translateX(-4px)}}
.icon{{display:inline-block;animation:float 2s infinite}}
@keyframes float{{0%,100%{{transform:translateY(0)}}50%{{transform:translateY(-4px)}}}}
.main{{margin-{'right' if rtl=='rtl' else 'left'}:230px;margin-top:65px;padding:12px}}
.card{{background:{card};border-radius:14px;padding:14px;margin:10px 0;box-shadow:0 2px 10px #0002}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}}
.kpi{{padding:16px;border-radius:14px;color:#fff;font-weight:bold}}
input,select{{width:100%;padding:10px;margin:5px 0;border-radius:8px;border:1px solid #ccc}}
button{{padding:10px 16px;border-radius:10px;border:0;background:#16a34a;color:#fff;cursor:pointer}}
.btn-del{{background:#dc2626}}.btn-edit{{background:#f59e0b}}
.footer{{text-align:center;padding:20px;font-size:13px}}
@media(max-width:700px){{.menu{{width:70px}}.menu span.t{{display:none}}.main{{margin-{'right' if rtl=='rtl' else 'left'}:80px}}}}
</style></head><body>
<div class="top"><b>OMAIA ISP</b><div>
<a href="/lang" style="color:#fff;margin:0 8px">🌐 {T('EN','عربي')}</a>
<a href="/theme" style="color:#fff;margin:0 8px">{'🌙' if th=='light' else '☀️'}</a>
<a href="/logout" style="color:#fff">🚪</a></div></div>
<div class="menu">
<a href="/dash?v=home"><span class="icon">🏠</span> <span class="t">{T('الرئيسية','Home')}</span></a>
<a href="/dash?v=subs"><span class="icon">👥</span> <span class="t">{T('مشتركين','Subs')}</span></a>
<a href="/dash?v=ledger"><span class="icon">📒</span> <span class="t">{T('دفتر حسابات','Ledger')}</span></a>
<a href="/dash?v=dishes"><span class="icon">📡</span> <span class="t">{T('صحون','Dishes')}</span></a>
<a href="/dash?v=towers"><span class="icon">🗼</span> <span class="t">{T('أبراج','Towers')}</span></a>
<a href="/dash?v=map"><span class="icon">🗺️</span> <span class="t">{T('خريطة حية','Live Map')}</span></a>
<a href="/dash?v=notifs"><span class="icon">🔔</span> <span class="t">{T('اشعارات','Notifs')}</span></a>
<a href="/dash?v=logs"><span class="icon">📝</span> <span class="t">{T('سجل الدخول','Logs')}</span></a>
<a href="/dash?v=settings"><span class="icon">⚙️</span> <span class="t">{T('اعدادات','Settings')}</span></a>
<a href="{wa}" target="_blank"><span class="icon">💬</span> <span class="t">WhatsApp</span></a>
</div>
<div class="main">{content}
<div class="footer">تصميم: م. عبدو عباس<br><a href="{wa}" target="_blank" style="color:#16a34a">+{SUPPORT_WA}</a><br>دعم فني: +{SUPPORT_WA}</div>
</div>
<a href="{wa}" target="_blank" style="position:fixed;bottom:20px;left:20px;background:#25D366;color:#fff;width:55px;height:55px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:28px;text-decoration:none;z-index:200">💬</a>
</body></html>"""

@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        ph=request.form.get('phone','').strip();pw=request.form.get('password','')
        c=db();u=ex(c,"SELECT * FROM users WHERE phone=?",(ph,)).fetchone()
        d=dict(u) if u else None;cc(c)
        if d and d['password']==pw and d.get('active',1)==1:
            session['phone']=d['phone']
            c=db();ex(c,"INSERT INTO logs(phone,act,dt) VALUES(?,?,?)",(ph,'دخول',datetime.datetime.now().isoformat()));sc(c);cc(c)
            return redirect('/dash')
        return layout(f"<div class=card><h3>❌ خطأ بالدخول</h3><a href=/login>رجوع</a></div>")
    return f"""<html dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{{margin:0;font-family:sans-serif;background:linear-gradient(#0f172a,#1e3a8a);min-height:100vh;display:flex;align-items:center;justify-content:center}} .box{{background:#fff;border-radius:18px;padding:24px;width:92%;max-width:380px;text-align:center}} input{{width:100%;padding:12px;margin:8px 0;border-radius:10px;border:1px solid #ccc}} button{{width:100%;padding:12px;background:#16a34a;color:#fff;border:0;border-radius:10px;font-size:16px}}</style></head><body>
<div class=box><h2 style="color:#1e3a8a">OMNIA ISP</h2><h3>تسجيل الدخول</h3>
<form method=post><input id=ph name=phone placeholder="رقم الهاتف / اسم المستخدم">
<div style="position:relative"><input id=pw name=password type=password placeholder="كلمة المرور"><span onclick="pw.type=pw.type=='password'?'text':'password'" style="position:absolute;left:10px;top:18px;cursor:pointer">👁️</span></div>
<label><input type=checkbox id=rm> تذكرني</label>
<button>دخول</button></form>
<p>تصميم: م. عبدو عباس<br><a href="https://wa.me/{SUPPORT_WA}">+{SUPPORT_WA}</a></p><p>الدعم الفني: +{SUPPORT_WA}</p></div>
<script>
ph.value=localStorage.getItem('ph')||'';pw.value=localStorage.getItem('pw')||'';
document.querySelector('form').onsubmit=()=>{{if(rm.checked){{localStorage.setItem('ph',ph.value);localStorage.setItem('pw',pw.value)}}else{{localStorage.removeItem('ph');localStorage.removeItem('pw')}}}}
</script></body></html>"""

@app.route('/logout')
def lo():
    ph=session.get('phone','')
    if ph:
        c=db();ex(c,"INSERT INTO logs(phone,act,dt) VALUES(?,?,?)",(ph,'خروج',datetime.datetime.now().isoformat()));sc(c);cc(c)
    session.clear();return redirect('/login')

@app.route('/lang')
def lg(): session['lang']='en' if L()=='ar' else 'ar';return redirect(request.referrer or '/dash')
@app.route('/theme')
def thm(): session['theme']='dark' if dark()=='light' else 'light';return redirect(request.referrer or '/dash')

def get_map(c):
    ds=[dict(r) for r in ex(c,"SELECT location,lat,lng FROM dish_ips WHERE lat!=0 LIMIT 500").fetchall()]
    ts=[dict(r) for r in ex(c,"SELECT name,lat,lng FROM towers WHERE lat!=0 LIMIT 500").fetchall()]
    ds_j=json.dumps([{"la":float(d.get("lat") or 0),"ln":float(d.get("lng") or 0),"n":d.get("location","")} for d in ds if d.get("lat")],ensure_ascii=False)
    ts_j=json.dumps([{"la":float(t.get("lat") or 0),"ln":float(t.get("lng") or 0),"n":t.get("name","")} for t in ts if t.get("lat")],ensure_ascii=False)
    return f'''<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<div class="card"><h3>🗺️ خريطة حية - حماة قمر صناعي</h3><div id="mp" style="height:70vh;border-radius:12px"></div><div id="cd"></div></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>
var DS={ds_j},TS={ts_j};
setTimeout(()=>{{var m=L.map("mp").setView([35.1318,36.7578],12);
L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}",{{maxZoom:19}}).addTo(m);
DS.forEach(d=>L.marker([d.la,d.ln]).addTo(m).bindPopup(d.n));
TS.forEach(t=>L.circleMarker([t.la,t.ln],{{color:"red",radius:8}}).addTo(m).bindPopup(t.n));
m.on("click",e=>document.getElementById("cd").innerText=e.latlng.lat.toFixed(6)+","+e.latlng.lng.toFixed(6));
setTimeout(()=>m.invalidateSize(),500);}},400)</script>'''

@app.route('/dash')
def dash():
    if not session.get('phone'):return redirect('/login')
    v=request.args.get('v','home');c=db();h=""
    if v=='home':
        nsubs=ex(c,"SELECT COUNT(*) c FROM subs").fetchone();nsubs=dict(nsubs)['c'] if nsubs else 0
        nd=ex(c,"SELECT COUNT(*) c FROM dish_ips").fetchone();nd=dict(nd)['c'] if nd else 0
        nt=ex(c,"SELECT COUNT(*) c FROM towers").fetchone();nt=dict(nt)['c'] if nt else 0
        h=f"""<div class=grid>
<div class="kpi" style="background:#2563eb">👥 {T('العملاء','Clients')}<br>{nsubs}</div>
<div class="kpi" style="background:#16a34a">📡 {T('الصحون','Dishes')}<br>{nd}</div>
<div class="kpi" style="background:#dc2626">🗼 {T('الأبراج','Towers')}<br>{nt}</div>
<div class="kpi" style="background:#f59e0b">✅ {T('مفعلين','Active')}<br>{nsubs}</div>
</div><div class=card><h3>{T('مرحبا','Hello')} {session.get('phone')}</h3><p>OMAIA ISP - {T('نظام الإدارة','Management')}</p></div>"""
    elif v=='subs':
        rs=[dict(r) for r in ex(c,"SELECT * FROM subs ORDER BY id DESC LIMIT 100").fetchall()]
        h=f"""<div class=card><h3>👥 {T('مشتركين','Subs')}</h3><form method=post action="/add_sub"><input name=name placeholder="{T('الاسم','Name')}"><input name=phone placeholder="{T('هاتف','Phone')}"><button>{T('اضافة','Add')}</button></form></div>"""
        for r in rs:
            h+=f"<div class=card>{r['name']} - {r['phone']} {'✅' if r['active'] else '❌'} <a href='/toggle_sub/{r['id']}'>تعطيل/تفعيل</a> <a href='/del_sub/{r['id']}' style='color:red'>حذف</a></div>"
    elif v=='ledger':
        rs=[dict(r) for r in ex(c,"SELECT * FROM ledger ORDER BY id DESC LIMIT 100").fetchall()]
        h=f"""<div class=card><h3>📒 {T('دفتر حسابات','Ledger')}</h3><form method=post action="/add_ledger"><input name=sub_id placeholder="ID مشترك"><input name=amount placeholder="مبلغ"><select name=typ><option>دين</option><option>دفع</option></select><input name=note placeholder="ملاحظة"><button>اضافة</button></form></div>"""
        for r in rs: h+=f"<div class=card>{r['amount']} - {r['typ']} - {r.get('note','')} <a href='/del_ledger/{r['id']}' style='color:red'>حذف</a></div>"
    elif v=='dishes':
        rs=[dict(r) for r in ex(c,"SELECT * FROM dish_ips ORDER BY id DESC LIMIT 100").fetchall()]
        h=f"""<div class=card><h3>📡 صحون</h3><form method=post action="/add_dish"><input name=ip placeholder=IP><input name=location placeholder=موقع><input name=lat placeholder=lat><input name=lng placeholder=lng><button>اضافة</button></form></div>"""
        for r in rs: h+=f"<div class=card>{r.get('ip','')} {r.get('location','')} <a href='/edit_dish/{r['id']}'>تعديل</a> <a href='/del_dish/{r['id']}' style='color:red'>حذف</a></div>"
    elif v=='towers':
        rs=[dict(r) for r in ex(c,"SELECT * FROM towers ORDER BY id DESC LIMIT 100").fetchall()]
        h=f"""<div class=card><h3>🗼 أبراج</h3><form method=post action="/add_tower"><input name=name placeholder=اسم><input name=lat placeholder=lat><input name=lng placeholder=lng><button>اضافة</button></form></div>"""
        for r in rs: h+=f"<div class=card>{r.get('name','')} <a href='/del_tower/{r['id']}' style='color:red'>حذف</a></div>"
    elif v=='map': h=get_map(c)
    elif v=='notifs':
        rs=[dict(r) for r in ex(c,"SELECT * FROM notifs ORDER BY id DESC LIMIT 50").fetchall()]
        h=f"""<div class=card><h3>🔔 اشعارات</h3><form method=post action="/add_notif"><input name=txt placeholder="نص الاشعار"><button>اضافة</button></form></div>"""
        for r in rs: h+=f"<div class=card>{r['txt']} <small>{r.get('dt','')}</small></div>"
    elif v=='logs':
        rs=[dict(r) for r in ex(c,"SELECT * FROM logs ORDER BY id DESC LIMIT 100").fetchall()]
        h="<div class=card><h3>📝 سجل الدخول / الخروج</h3></div>"
        for r in rs: h+=f"<div class=card>{r['phone']} - {r['act']} - {r['dt']}</div>"
    elif v=='settings':
        h=f"""<div class=card><h3>⚙️ اعدادات</h3><p>OMAIA ISP</p><a href="/lang"><button>🌐 لغة</button></a> <a href="/theme"><button>🌙 ليل/نهار</button></a></div>"""
    cc(c);return layout(h)

@app.route('/add_sub',methods=['POST'])
def asb():
    c=db();ex(c,"INSERT INTO subs(name,phone) VALUES(?,?)",(request.form.get('name',''),request.form.get('phone','')));sc(c);cc(c);return redirect('/dash?v=subs')
@app.route('/toggle_sub/<int:i>')
def tsb(i):
    c=db();ex(c,"UPDATE subs SET active=1-active WHERE id=?",(i,));sc(c);cc(c);return redirect('/dash?v=subs')
@app.route('/del_sub/<int:i>')
def dsb(i):
    c=db();ex(c,"DELETE FROM subs WHERE id=?",(i,));sc(c);cc(c);return redirect('/dash?v=subs')
@app.route('/add_ledger',methods=['POST'])
def alb():
    f=request.form;c=db();ex(c,"INSERT INTO ledger(sub_id,amount,typ,note,dt) VALUES(?,?,?,?,?)",(f.get('sub_id'),fnum(f.get('amount')),f.get('typ'),f.get('note'),datetime.datetime.now().isoformat()));sc(c);cc(c);return redirect('/dash?v=ledger')
@app.route('/del_ledger/<int:i>')
def dlb(i):
    c=db();ex(c,"DELETE FROM ledger WHERE id=?",(i,));sc(c);cc(c);return redirect('/dash?v=ledger')
@app.route('/add_dish',methods=['POST'])
def adh():
    f=request.form;c=db();ex(c,"INSERT INTO dish_ips(ip,location,lat,lng) VALUES(?,?,?,?)",(f.get('ip',''),f.get('location',''),fnum(f.get('lat')),fnum(f.get('lng'))));sc(c);cc(c);return redirect('/dash?v=dishes')
@app.route('/del_dish/<int:i>')
def ddh(i):
    c=db();ex(c,"DELETE FROM dish_ips WHERE id=?",(i,));sc(c);cc(c);return redirect('/dash?v=dishes')
@app.route('/edit_dish/<int:i>',methods=['GET','POST'])
def edh(i):
    c=db()
    if request.method=='POST':
        f=request.form;ex(c,"UPDATE dish_ips SET ip=?,location=?,lat=?,lng=? WHERE id=?",(f.get('ip'),f.get('location'),fnum(f.get('lat')),fnum(f.get('lng')),i));sc(c);cc(c);return redirect('/dash?v=dishes')
    r=dict(ex(c,"SELECT * FROM dish_ips WHERE id=?",(i,)).fetchone());cc(c)
    return layout(f"<div class=card><form method=post><input name=ip value='{r.get('ip','')}'><input name=location value='{r.get('location','')}'><input name=lat value='{r.get('lat','')}'><input name=lng value='{r.get('lng','')}'><button>حفظ</button></form></div>")
@app.route('/add_tower',methods=['POST'])
def atw():
    f=request.form;c=db();ex(c,"INSERT INTO towers(name,lat,lng) VALUES(?,?,?)",(f.get('name',''),fnum(f.get('lat')),fnum(f.get('lng'))));sc(c);cc(c);return redirect('/dash?v=towers')
@app.route('/del_tower/<int:i>')
def dtw(i):
    c=db();ex(c,"DELETE FROM towers WHERE id=?",(i,));sc(c);cc(c);return redirect('/dash?v=towers')
@app.route('/add_notif',methods=['POST'])
def anf():
    c=db();ex(c,"INSERT INTO notifs(txt,dt) VALUES(?,?)",(request.form.get('txt',''),datetime.datetime.now().isoformat()));sc(c);cc(c);return redirect('/dash?v=notifs')

if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
