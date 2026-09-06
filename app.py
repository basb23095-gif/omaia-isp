from flask import Flask, request, redirect, session, make_response
import os, datetime, json, html
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

@app.after_request
def add_cache(r):
    # كاش للملفات الثابتة، وبدون كاش للصفحات المتغيرة لمنع التدقير
    if request.path.startswith('/static'):
        r.headers['Cache-Control']='public,max-age=86400'
    else:
        r.headers['Cache-Control']='no-store'
    return r

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
        _pg.autocommit=True;return _pg
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
        else:
            rs=[dict(r) for r in c.execute(q,a).fetchall()];cc(c);return rs
    except:
        cc(c);return []

def qone(q,a=()):
    r=qall(q,a);return r[0] if r else None

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
def inum(v):
    try:return int(float(v))
    except:return None

def init():
    ss=[
    "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,active INT DEFAULT 1)",
    "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,active INT DEFAULT 1)",
    "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,sub_id INT,amount REAL,typ TEXT,note TEXT,dt TEXT)",
    "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,lat REAL DEFAULT 0,lng REAL DEFAULT 0)",
    "CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,lat REAL,lng REAL)",
    "CREATE TABLE IF NOT EXISTS notifs(id INTEGER PRIMARY KEY AUTOINCREMENT,txt TEXT,dt TEXT)",
    "CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,phone TEXT,act TEXT,dt TEXT)"
    ]
    if USE_PG: ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
    for s in ss: qexec(s)
    if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,active) VALUES(?,?,?,?)",('05344851045','admin2024','super',1))
init()

def L(): return session.get('lang','ar')
def T(ar,en): return ar if L()=='ar' else en
def dark(): return session.get('theme','light')

def layout(content):
    lang=L(); th=dark(); rtl='rtl' if lang=='ar' else 'ltr'
    bg='#0f172a' if th=='dark' else '#f1f5f9'
    card='#1e293b' if th=='dark' else '#ffffff'
    txt='#f1f5f9' if th=='dark' else '#0f172a'
    menu_bg='#1e3a8a'
    wa=f"https://wa.me/{SUPPORT_WA}"
    side='right' if rtl=='rtl' else 'left'
    return f"""<html dir="{rtl}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>*{{box-sizing:border-box}}body{{margin:0;font-family:sans-serif;background:{bg};color:{txt}}}
.top{{position:fixed;top:0;left:0;right:0;background:{menu_bg};color:#fff;padding:12px;display:flex;justify-content:space-between;z-index:100}}
.menu{{position:fixed;top:48px;bottom:0;{side}:0;width:210px;background:{menu_bg};padding:10px;z-index:99;overflow:auto}}
.menu a{{display:block;color:#fff;text-decoration:none;padding:11px;border-radius:8px;margin:3px 0}}
.icon{{display:inline-block;animation:fl 2s infinite}}@keyframes fl{{50%{{transform:translateY(-3px)}}}}
.main{{margin-{side}:220px;margin-top:60px;padding:10px;animation:fade.2s}}@keyframes fade{{from{{opacity:.4}}}}
.card{{background:{card};border-radius:12px;padding:12px;margin:8px 0;box-shadow:0 1px 6px #0002}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px}}
.kpi{{padding:14px;border-radius:12px;color:#fff;font-weight:bold;text-align:center}}
input,select{{width:100%;padding:9px;margin:4px 0;border-radius:8px;border:1px solid #ccc}}
button{{padding:9px 14px;border-radius:8px;border:0;background:#16a34a;color:#fff;cursor:pointer}}
@media(max-width:700px){{.menu{{width:60px}}.menu.t{{display:none}}.main{{margin-{side}:70px}}}}
</style></head><body>
<div class="top"><b>OMAIA ISP</b><div><a href="/lang" style="color:#fff;margin:0 6px;text-decoration:none">🌐 {T('EN','عربي')}</a><a href="/theme" style="color:#fff;margin:0 6px;text-decoration:none">{'🌙' if th=='light' else '☀️'}</a><a href="/logout" style="color:#fff;text-decoration:none">🚪</a></div></div>
<div class="menu">
<a href="/dash?v=home"><span class="icon">🏠</span> <span class="t">{T('الرئيسية','Home')}</span></a>
<a href="/dash?v=subs"><span class="icon">👥</span> <span class="t">{T('مشتركين','Subs')}</span></a>
<a href="/dash?v=ledger"><span class="icon">📒</span> <span class="t">{T('دفتر حسابات','Ledger')}</span></a>
<a href="/dash?v=dishes"><span class="icon">📡</span> <span class="t">{T('صحون','Dishes')}</span></a>
<a href="/dash?v=towers"><span class="icon">🗼</span> <span class="t">{T('أبراج','Towers')}</span></a>
<a href="/dash?v=map"><span class="icon">🗺️</span> <span class="t">{T('خريطة حية','Map')}</span></a>
<a href="/dash?v=notifs"><span class="icon">🔔</span> <span class="t">{T('اشعارات','Notifs')}</span></a>
<a href="/dash?v=logs"><span class="icon">📝</span> <span class="t">{T('سجل الدخول','Logs')}</span></a>
<a href="/dash?v=settings"><span class="icon">⚙️</span> <span class="t">{T('اعدادات','Settings')}</span></a>
</div>
<div class="main">{content}<div style="text-align:center;padding:18px;font-size:12px;opacity:.8">تصميم: م. عبدو عباس<br><a href="{wa}" target="_blank" style="color:#16a34a">+{SUPPORT_WA}</a><br>دعم فني: +{SUPPORT_WA}</div></div>
<a href="{wa}" target="_blank" style="position:fixed;bottom:18px;left:18px;background:#25D366;color:#fff;width:52px;height:52px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:26px;text-decoration:none;z-index:200">💬</a>
</body></html>"""

@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login',methods=['GET','POST'])
def login():
    err=""
    if request.method=='POST':
        ph=request.form.get('phone','').strip();pw=request.form.get('password','')
        u=qone("SELECT * FROM users WHERE phone=?",(ph,))
        if u and u['password']==pw and int(u.get('active',1))==1:
            session['phone']=u['phone']
            qexec("INSERT INTO logs(phone,act,dt) VALUES(?,?,?)",(ph,'دخول',datetime.datetime.now().isoformat()))
            return redirect('/dash')
        err="<p style='color:red'>❌ خطأ بالدخول</p>"
    return f"""<html dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{{margin:0;font-family:sans-serif;background:linear-gradient(#0f172a,#1e3a8a);min-height:100vh;display:flex;align-items:center;justify-content:center}}.box{{background:#fff;border-radius:16px;padding:22px;width:92%;max-width:360px;text-align:center}} input{{width:100%;padding:11px;margin:7px 0;border-radius:9px;border:1px solid #ccc}} button{{width:100%;padding:11px;background:#16a34a;color:#fff;border:0;border-radius:9px}}</style></head><body>
<div class=box><h2 style="color:#1e3a8a;margin:0">OMAIA ISP</h2><h3>تسجيل الدخول</h3>{err}
<form method=post id=f><input id=ph name=phone placeholder="رقم الهاتف / اسم المستخدم" autocomplete="username">
<div style="position:relative"><input id=pw name=password type=password placeholder="كلمة المرور" autocomplete="current-password"><span id=eye style="position:absolute;left:10px;top:16px;cursor:pointer">👁️</span></div>
<label style="font-size:13px"><input type=checkbox id=rm style="width:auto"> تذكرني</label>
<button>دخول</button></form>
<p style="font-size:12px">تصميم: م. عبدو عباس<br><a href="https://wa.me/{SUPPORT_WA}">+{SUPPORT_WA}</a></p></div>
<script>
var ph=document.getElementById('ph'),pw=document.getElementById('pw'),rm=document.getElementById('rm');
ph.value=localStorage.getItem('ph')||'';pw.value=localStorage.getItem('pw')||'';
document.getElementById('eye').onclick=()=>pw.type=pw.type=='password'?'text':'password';
document.getElementById('f').onsubmit=()=>{{if(rm.checked){{localStorage.setItem('ph',ph.value);localStorage.setItem('pw',pw.value)}}else{{localStorage.removeItem('ph');localStorage.removeItem('pw')}}}};
</script></body></html>"""

@app.route('/logout')
def lo():
    ph=session.get('phone','')
    if ph: qexec("INSERT INTO logs(phone,act,dt) VALUES(?,?,?)",(ph,'خروج',datetime.datetime.now().isoformat()))
    session.clear();return redirect('/login')
@app.route('/lang')
def lg(): session['lang']='en' if L()=='ar' else 'ar';return redirect('/dash')
@app.route('/theme')
def thm(): session['theme']='dark' if dark()=='light' else 'light';return redirect(request.referrer or '/dash')

def get_map():
    ds=qall("SELECT location,lat,lng FROM dish_ips WHERE lat!=0 LIMIT 500")
    ts=qall("SELECT name,lat,lng FROM towers WHERE lat!=0 LIMIT 500")
    ds_j=json.dumps([{"la":float(d.get("lat") or 0),"ln":float(d.get("lng") or 0),"n":str(d.get("location",""))} for d in ds if d.get("lat")],ensure_ascii=False).replace("</","<\\/")
    ts_j=json.dumps([{"la":float(t.get("lat") or 0),"ln":float(t.get("lng") or 0),"n":str(t.get("name",""))} for t in ts if t.get("lat")],ensure_ascii=False).replace("</","<\\/")
    return f'''<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<div class="card"><h3>🗺️ خريطة حية - حماة قمر صناعي</h3><div id="mp" style="height:68vh;border-radius:10px;background:#000"></div><div id="cd" style="font-size:12px"></div></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>
var DS={ds_j},TS={ts_j};
function initM(a){{if(typeof L=="undefined"){{if(a<20)setTimeout(()=>initM(a+1),300);return;}}
var m=L.map("mp").setView([35.1318,36.7578],12);
L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}",{{maxZoom:19}}).addTo(m);
DS.forEach(d=>L.marker([d.la,d.ln]).addTo(m).bindPopup(d.n));
TS.forEach(t=>L.circleMarker([t.la,t.ln],{{color:"red",radius:8}}).addTo(m).bindPopup(t.n));
m.on("click",e=>document.getElementById("cd").innerText=e.latlng.lat.toFixed(6)+","+e.latlng.lng.toFixed(6));
setTimeout(()=>m.invalidateSize(),300);}}
initM(0);</script>'''

@app.route('/dash')
def dash():
    if not session.get('phone'):return redirect('/login')
    v=request.args.get('v','home');h=""
    if v=='home':
        ns=(qone("SELECT COUNT(*) c FROM subs") or {}).get('c',0)
        nd=(qone("SELECT COUNT(*) c FROM dish_ips") or {}).get('c',0)
        nt=(qone("SELECT COUNT(*) c FROM towers") or {}).get('c',0)
        h=f"""<div class=grid>
<div class="kpi" style="background:#2563eb">👥 {T('العملاء','Clients')}<br>{ns}</div>
<div class="kpi" style="background:#16a34a">📡 {T('الصحون','Dishes')}<br>{nd}</div>
<div class="kpi" style="background:#dc2626">🗼 {T('الأبراج','Towers')}<br>{nt}</div>
<div class="kpi" style="background:#f59e0b">✅ {T('مفعلين','Active')}<br>{ns}</div>
</div><div class=card><h3>{T('مرحبا','Hello')} {esc(session.get('phone'))}</h3><p>OMAIA ISP</p></div>"""
    elif v=='subs':
        rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 100")
        h=f"""<div class=card><h3>👥 {T('مشتركين','Subs')}</h3><form method=post action="/add_sub"><input name=name placeholder="{T('الاسم','Name')}" required><input name=phone placeholder="{T('هاتف','Phone')}" required><button>{T('اضافة','Add')}</button></form></div>"""
        for r in rs: h+=f"<div class=card>{esc(r['name'])} - {esc(r['phone'])} {'✅' if r['active'] else '❌'} <a href='/toggle_sub/{r['id']}'>تعطيل/تفعيل</a> | <a href='/del_sub/{r['id']}' style='color:red' onclick=\"return confirm('حذف؟')\">حذف</a></div>"
    elif v=='ledger':
        rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 100")
        h=f"""<div class=card><h3>📒 {T('دفتر حسابات','Ledger')}</h3><form method=post action="/add_ledger"><input name=sub_id placeholder="ID مشترك" type=number><input name=amount placeholder="مبلغ" type=number step=0.01 required><select name=typ><option>دين</option><option>دفع</option></select><input name=note placeholder="ملاحظة"><button>اضافة</button></form></div>"""
        for r in rs: h+=f"<div class=card>{esc(r['amount'])} - {esc(r['typ'])} - {esc(r.get('note',''))} <a href='/del_ledger/{r['id']}' style='color:red'>حذف</a></div>"
    elif v=='dishes':
        rs=qall("SELECT * FROM dish_ips ORDER BY id DESC LIMIT 100")
        h=f"""<div class=card><h3>📡 صحون</h3><form method=post action="/add_dish"><input name=ip placeholder=IP required><input name=location placeholder=موقع><input name=lat placeholder=lat type=number step=any><input name=lng placeholder=lng type=number step=any><button>اضافة</button></form></div>"""
        for r in rs: h+=f"<div class=card>{esc(r.get('ip',''))} {esc(r.get('location',''))} <a href='/edit_dish/{r['id']}'>تعديل</a> | <a href='/del_dish/{r['id']}' style='color:red'>حذف</a></div>"
    elif v=='towers':
        rs=qall("SELECT * FROM towers ORDER BY id DESC LIMIT 100")
        h=f"""<div class=card><h3>🗼 أبراج</h3><form method=post action="/add_tower"><input name=name placeholder=اسم required><input name=lat placeholder=lat type=number step=any><input name=lng placeholder=lng type=number step=any><button>اضافة</button></form></div>"""
        for r in rs: h+=f"<div class=card>{esc(r.get('name',''))} <a href='/del_tower/{r['id']}' style='color:red'>حذف</a></div>"
    elif v=='map': h=get_map()
    elif v=='notifs':
        rs=qall("SELECT * FROM notifs ORDER BY id DESC LIMIT 50")
        h=f"""<div class=card><h3>🔔 اشعارات</h3><form method=post action="/add_notif"><input name=txt placeholder="نص الاشعار" required><button>اضافة</button></form></div>"""
        for r in rs: h+=f"<div class=card>{esc(r['txt'])} <small>{esc(r.get('dt',''))}</small></div>"
    elif v=='logs':
        rs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 100")
        h="<div class=card><h3>📝 سجل الدخول / الخروج</h3></div>"
        for r in rs: h+=f"<div class=card>{esc(r['phone'])} - {esc(r['act'])} - {esc(r['dt'])}</div>"
    elif v=='settings':
        h=f"""<div class=card><h3>⚙️ اعدادات</h3><p>OMAIA ISP</p><a href="/lang"><button>🌐 لغة</button></a> <a href="/theme"><button>🌙 ليل/نهار</button></a></div>"""
    return layout(h)

@app.route('/add_sub',methods=['POST'])
def asb(): qexec("INSERT INTO subs(name,phone) VALUES(?,?)",(request.form.get('name','')[:100],request.form.get('phone','')[:50]));return redirect('/dash?v=subs')
@app.route('/toggle_sub/<int:i>')
def tsb(i): qexec("UPDATE subs SET active=1-active WHERE id=?",(i,));return redirect('/dash?v=subs')
@app.route('/del_sub/<int:i>')
def dsb(i): qexec("DELETE FROM subs WHERE id=?",(i,));return redirect('/dash?v=subs')
@app.route('/add_ledger',methods=['POST'])
def alb():
    f=request.form;sid=inum(f.get('sub_id'))
    qexec("INSERT INTO ledger(sub_id,amount,typ,note,dt) VALUES(?,?,?,?,?)",(sid,fnum(f.get('amount')),f.get('typ','دين')[:20],f.get('note','')[:200],datetime.datetime.now().isoformat()))
    return redirect('/dash?v=ledger')
@app.route('/del_ledger/<int:i>')
def dlb(i): qexec("DELETE FROM ledger WHERE id=?",(i,));return redirect('/dash?v=ledger')
@app.route('/add_dish',methods=['POST'])
def adh():
    f=request.form;qexec("INSERT INTO dish_ips(ip,location,lat,lng) VALUES(?,?,?,?)",(f.get('ip','')[:50],f.get('location','')[:100],fnum(f.get('lat')),fnum(f.get('lng'))));return redirect('/dash?v=dishes')
@app.route('/del_dish/<int:i>')
def ddh(i): qexec("DELETE FROM dish_ips WHERE id=?",(i,));return redirect('/dash?v=dishes')
@app.route('/edit_dish/<int:i>',methods=['GET','POST'])
def edh(i):
    if request.method=='POST':
        f=request.form;qexec("UPDATE dish_ips SET ip=?,location=?,lat=?,lng=? WHERE id=?",(f.get('ip','')[:50],f.get('location','')[:100],fnum(f.get('lat')),fnum(f.get('lng')),i));return redirect('/dash?v=dishes')
    r=qone("SELECT * FROM dish_ips WHERE id=?",(i,)) or {}
    return layout(f"<div class=card><form method=post><input name=ip value='{esc(r.get('ip',''))}'><input name=location value='{esc(r.get('location',''))}'><input name=lat value='{esc(r.get('lat',''))}'><input name=lng value='{esc(r.get('lng',''))}'><button>حفظ</button></form></div>")
@app.route('/add_tower',methods=['POST'])
def atw():
    f=request.form;qexec("INSERT INTO towers(name,lat,lng) VALUES(?,?,?)",(f.get('name','')[:100],fnum(f.get('lat')),fnum(f.get('lng'))));return redirect('/dash?v=towers')
@app.route('/del_tower/<int:i>')
def dtw(i): qexec("DELETE FROM towers WHERE id=?",(i,));return redirect('/dash?v=towers')
@app.route('/add_notif',methods=['POST'])
def anf(): qexec("INSERT INTO notifs(txt,dt) VALUES(?,?)",(request.form.get('txt','')[:500],datetime.datetime.now().isoformat()));return redirect('/dash?v=notifs')

if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
