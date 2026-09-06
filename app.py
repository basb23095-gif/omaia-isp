from flask import Flask, request, redirect, session
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
        else:
            rs=[dict(r) for r in c.execute(q,a).fetchall()];cc(c);return rs
    except: cc(c);return []
def qone(q,a=()):
    r=qall(q,a);return r[0] if r else None
def qexec(q,a=()):
    c=db()
    try:
        if USE_PG:
            cur=c.cursor();cur.execute(q.replace("?","%s"),a);cur.close()
        else: c.execute(q,a);c.commit();cc(c)
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
    "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,tower TEXT,lat REAL DEFAULT 0,lng REAL DEFAULT 0)",
    "CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,lat REAL,lng REAL)",
    "CREATE TABLE IF NOT EXISTS notifs(id INTEGER PRIMARY KEY AUTOINCREMENT,txt TEXT,dt TEXT)",
    "CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,phone TEXT,act TEXT,dt TEXT)"
    ]
    if USE_PG: ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
    for s in ss: qexec(s)
    # عمود tower اذا قاعدة قديمة
    try: qexec("ALTER TABLE dish_ips ADD COLUMN tower TEXT")
    except: pass
    if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,active) VALUES(?,?,?,?)",('05344851045','admin2024','super',1))
init()

def L(): return session.get('lang','ar')
def T(ar,en): return ar if L()=='ar' else en
def dark(): return session.get('theme','light')

# ---------- صفحات المحتوى للتنقل السريع ----------
def page_content(v):
    h=""
    if v=='home':
        ns=(qone("SELECT COUNT(*) c FROM subs") or {}).get('c',0)
        nd=(qone("SELECT COUNT(*) c FROM dish_ips") or {}).get('c',0)
        nt=(qone("SELECT COUNT(*) c FROM towers") or {}).get('c',0)
        h=f"""<div class=grid>
<div class="kpi" style="background:#2563eb">👥 {T('العملاء','Clients')}<br>{ns}</div>
<div class="kpi" style="background:#16a34a">📡 {T('الصحون','Dishes')}<br>{nd}</div>
<div class="kpi" style="background:#dc2626">🗼 {T('الأبراج','Towers')}<br>{nt}</div>
<div class="kpi" style="background:#f59e0b">✅ {T('مفعلين','Active')}<br>{ns}</div>
</div><div class=card><h3>{T('مرحبا','Hello')} {esc(session.get('phone'))}</h3><p>OMAIA ISP - نار 🔥</p></div>"""
    elif v=='subs':
        rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 100")
        h=f"""<div class=card><h3>👥 {T('مشتركين','Subs')}</h3><form data-ajax method=post action="/add_sub"><input name=name placeholder="{T('الاسم','Name')}" required><input name=phone placeholder="{T('هاتف','Phone')}" required><button>{T('اضافة','Add')}</button></form></div>"""
        for r in rs:
            h+=f"<div class=card>{esc(r['name'])} - {esc(r['phone'])} {'✅' if r['active'] else '❌'} <a class=ic href='/toggle_sub/{r['id']}' data-ajax>🔄</a> <a class=ic href='/edit_sub/{r['id']}'>✏️</a> <a class=ic href='/del_sub/{r['id']}' data-del>🗑️</a></div>"
    elif v=='ledger':
        rs=qall("SELECT l.*, s.name sn FROM ledger l LEFT JOIN subs s ON s.id=l.sub_id ORDER BY l.id DESC LIMIT 100")
        subs=qall("SELECT id,name FROM subs ORDER BY id DESC LIMIT 200")
        opts="".join([f"<option value='{r['id']}'>{r['id']}-{esc(r['name'])}</option>" for r in subs])
        tot=(qone("SELECT SUM(CASE WHEN typ='دفع' THEN amount ELSE -amount END) c FROM ledger") or {}).get('c',0)
        h=f"""<div class=card><h3>📒 {T('دفتر حسابات','Ledger')} - الرصيد: {tot}</h3>
<form data-ajax method=post action="/add_ledger"><select name=sub_id><option value="">بدون مشترك</option>{opts}</select><input name=amount placeholder="مبلغ" type=number step=0.01 required><select name=typ><option>دين</option><option>دفع</option></select><input name=note placeholder="ملاحظة"><button>اضافة</button></form></div>"""
        for r in rs:
            h+=f"<div class=card>#{r['id']} {esc(r.get('sn',''))} | {esc(r['amount'])} - {esc(r['typ'])} - {esc(r.get('note',''))} <a class=ic href='/del_ledger/{r['id']}' data-del>🗑️</a></div>"
    elif v=='dishes':
        rs=qall("SELECT * FROM dish_ips ORDER BY id DESC LIMIT 200")
        tws=qall("SELECT name FROM towers ORDER BY id DESC LIMIT 200")
        twopts="".join([f"<option>{esc(t['name'])}</option>" for t in tws])
        h=f"""<div class=card><h3>📡 صحون - IP / موقع / برج</h3>
<form data-ajax method=post action="/add_dish"><input name=ip placeholder="IP مثلا 192.168.1.20" required><input name=location placeholder="موقع"><select name=tower><option value="">اختر برج</option>{twopts}</select><input name=lat id=lat placeholder="lat" type=number step=any><input name=lng id=lng placeholder="lng" type=number step=any><button>➕ اضافة</button></form>
<button onclick="getLoc()">📍 موقعي الحالي</button></div>
<script>function getLoc(){{navigator.geolocation.getCurrentPosition(p=>{{document.getElementById('lat').value=p.coords.latitude.toFixed(6);document.getElementById('lng').value=p.coords.longitude.toFixed(6);}})}}</script>"""
        for r in rs:
            ip=esc(r.get('ip',''))
            h+=f"""<div class=card>🌐 <a href="http://{ip}" target="_blank" style="color:#2563eb;font-weight:bold">{ip}</a> | 📍 {esc(r.get('location',''))} | 🗼 {esc(r.get('tower',''))}
<br><button onclick="pingIP('{ip}',this)">📶 Ping</button> <span class=ping></span>
<a class=ic href="/edit_dish/{r['id']}">✏️</a> <a class=ic href="/del_dish/{r['id']}" data-del>🗑️</a></div>"""
        h+="""<script>
function pingIP(ip,btn){var s=btn.parentElement.querySelector('.ping');s.textContent='⏳...';var t0=Date.now();
fetch('http://'+ip,{mode:'no-cors',cache:'no-store'}).then(()=>{s.textContent='✅ شغال '+(Date.now()-t0)+'ms'}).catch(()=>{s.textContent='❌ لا يوجد اتصال'});
setTimeout(()=>{if(s.textContent.includes('...'))s.textContent='❌ timeout (لا بنج)';},5000);}
</script>"""
    elif v=='towers':
        rs=qall("SELECT * FROM towers ORDER BY id DESC LIMIT 100")
        h=f"""<div class=card><h3>🗼 أبراج</h3><form data-ajax method=post action="/add_tower"><input name=name placeholder=اسم required><input name=lat placeholder=lat type=number step=any><input name=lng placeholder=lng type=number step=any><button>اضافة</button></form></div>"""
        for r in rs: h+=f"<div class=card>🗼 {esc(r.get('name',''))} <a class=ic href='/del_tower/{r['id']}' data-del>🗑️</a></div>"
    elif v=='map':
        h=get_map_html()
    elif v=='notifs':
        rs=qall("SELECT * FROM notifs ORDER BY id DESC LIMIT 50")
        h=f"""<div class=card><h3>🔔 اشعارات</h3><form data-ajax method=post action="/add_notif"><input name=txt placeholder="نص الاشعار" required><button>اضافة</button></form></div>"""
        for r in rs: h+=f"<div class=card>{esc(r['txt'])} <small>{esc(r.get('dt',''))}</small> <a class=ic href='/del_notif/{r['id']}' data-del>🗑️</a></div>"
    elif v=='logs':
        rs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 100")
        h="<div class=card><h3>📝 سجل الدخول / الخروج</h3></div>"
        for r in rs: h+=f"<div class=card>{esc(r['phone'])} - {esc(r['act'])} - {esc(r['dt'])}</div>"
    elif v=='settings':
        ph=esc(session.get('phone',''))
        h=f"""<div class=card><h3>⚙️ اعدادات</h3>
<p>المستخدم الحالي: <b>{ph}</b></p>
<form data-ajax method=post action="/change_user"><input name=newphone placeholder="يوزر جديد" required><button>🔄 تغيير اليوزر</button></form>
<form data-ajax method=post action="/change_pass"><input name=newpass placeholder="كلمة سر جديدة" type=password required><button>🔑 تغيير كلمة السر</button></form>
<hr><a href="/lang"><button>🌐 لغة</button></a> <a href="/theme"><button>🌙 ليل/نهار</button></a>
<hr><a href="/logout" style="background:#dc2626;color:#fff;padding:10px 16px;border-radius:8px;text-decoration:none;display:inline-block">🚪 تسجيل خروج</a>
</div>"""
    return h

def get_map_html():
    ds=qall("SELECT id,ip,location,tower,lat,lng FROM dish_ips WHERE lat!=0 LIMIT 500")
    ts=qall("SELECT name,lat,lng FROM towers WHERE lat!=0 LIMIT 500")
    ds_j=json.dumps([{"id":d["id"],"la":float(d.get("lat") or 0),"ln":float(d.get("lng") or 0),"n":str(d.get("location","")),"ip":str(d.get("ip",""))} for d in ds if d.get("lat")],ensure_ascii=False).replace("</","<\\/")
    ts_j=json.dumps([{"la":float(t.get("lat") or 0),"ln":float(t.get("lng") or 0),"n":str(t.get("name",""))} for t in ts if t.get("lat")],ensure_ascii=False).replace("</","<\\/")
    return f'''
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<div class="card"><h3>🗺️ خريطة حية فقط</h3>
<div style="margin:6px 0"><button onclick="addMode()">➕ ضيف نقطة</button> <button onclick="measureMode()">📏 قيس مسافة</button> <button onclick="stopMode()">✋ ايقاف</button> <span id=minfo></span></div>
<div id="mp" style="height:70vh;border-radius:10px;background:#111"></div><div id="cd"></div></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
var DS={ds_j},TS={ts_j},mode=null,pts=[],line=null;
function initM(a){{if(typeof L=="undefined"){{if(a<25)setTimeout(()=>initM(a+1),200);return;}}
window._m=L.map("mp",{{preferCanvas:true}}).setView([35.1318,36.7578],12);
L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}",{{maxZoom:19}}).addTo(window._m);
DS.forEach(d=>{{var mk=L.marker([d.la,d.ln]).addTo(window._m).bindPopup(d.n+"<br>"+d.ip+"<br><a href='/edit_dish/"+d.id+"'>✏️ تعديل</a> | <a href=\"#\" onclick=\"delP("+d.id+")\">🗑️ حذف</a>");}});
TS.forEach(t=>L.circleMarker([t.la,t.ln],{{color:"red",radius:9}}).addTo(window._m).bindPopup(t.n));
window._m.on("click",e=>{{
document.getElementById("cd").innerText=e.latlng.lat.toFixed(6)+","+e.latlng.lng.toFixed(6);
if(mode=="add"){{var ip=prompt("IP الصحن:");if(!ip)return;var loc=prompt("الموقع:")||"";fetch("/api_add_dish",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{ip:ip,location:loc,lat:e.latlng.lat,lng:e.latlng.lng}})}}).then(()=>loadPage("map"));}}
if(mode=="measure"){{pts.push(e.latlng);if(pts.length==2){{var d=window._m.distance(pts[0],pts[1]);document.getElementById("minfo").innerText="📏 المسافة: "+(d/1000).toFixed(3)+" كم";pts=[];if(line)window._m.removeLayer(line);}}else{{if(line)window._m.removeLayer(line);line=L.polyline(pts,{{color:"yellow"}}).addTo(window._m);}}
}});
setTimeout(()=>window._m.invalidateSize(),300);}}
function addMode(){{mode="add";document.getElementById("minfo").innerText="اضغط على الخريطة لإضافة نقطة";}}
function measureMode(){{mode="measure";pts=[];document.getElementById("minfo").innerText="اضغط نقطتين لقياس المسافة";}}
function stopMode(){{mode=null;pts=[];document.getElementById("minfo").innerText="";}}
function delP(id){{if(confirm("حذف النقطة؟"))fetch("/del_dish/"+id).then(()=>loadPage("map"));}}
initM(0);
</script>'''

def layout(content, v='home'):
    lang=L(); th=dark()
    bg='#0f172a' if th=='dark' else '#f1f5f9'
    card='#1e293b' if th=='dark' else '#ffffff'
    txt='#f1f5f9' if th=='dark' else '#0f172a'
    wa=f"https://wa.me/{SUPPORT_WA}"
    # القائمة دائما يمين
    return f"""<html dir="rtl" lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{{box-sizing:border-box}}body{{margin:0;font-family:sans-serif;background:{bg};color:{txt}}}
.top{{position:fixed;top:0;left:0;right:0;background:#1e3a8a;color:#fff;padding:12px;display:flex;justify-content:space-between;z-index:100}}
.menu{{position:fixed;top:48px;bottom:0;right:0;width:200px;background:linear-gradient(180deg,#1e3a8a,#1e40af);padding:10px;z-index:99;overflow:auto}}
.menu a{{display:flex;align-items:center;gap:10px;color:#fff;text-decoration:none;padding:12px;border-radius:10px;margin:4px 0;font-weight:600}}
.menu a.active,.menu a:hover{{background:#ffffff22;transform:translateX(-3px)}}
.menu.icp{{font-size:20px;width:28px;height:28px;display:flex;align-items:center;justify-content:center;background:#ffffff18;border-radius:8px}}
.main{{margin-right:210px;margin-top:58px;padding:10px;min-height:90vh}}
.card{{background:{card};border-radius:12px;padding:12px;margin:8px 0;box-shadow:0 1px 6px #0002}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px}}
.kpi{{padding:14px;border-radius:12px;color:#fff;font-weight:bold;text-align:center}}
input,select{{width:100%;padding:9px;margin:4px 0;border-radius:8px;border:1px solid #ccc}}
button{{padding:9px 14px;border-radius:8px;border:0;background:#16a34a;color:#fff;cursor:pointer}}
.ic{{font-size:18px;text-decoration:none;margin:0 4px}}
#loader{{position:fixed;top:0;left:0;right:0;height:3px;background:#22c55e;width:0;z-index:200;transition:width.2s}}
@media(max-width:700px){{.menu{{width:62px}}.menu.t{{display:none}}.main{{margin-right:70px}}}}
</style></head><body>
<div id=loader></div>
<div class="top"><b>⚡ OMAIA ISP</b><div><a href="/lang" style="color:#fff;margin:0 6px;text-decoration:none">🌐</a><a href="/theme" style="color:#fff;margin:0 6px;text-decoration:none">{'🌙' if th=='light' else '☀️'}</a><a href="/logout" style="color:#fff;text-decoration:none;font-weight:bold">🚪 خروج</a></div></div>
<div class="menu" id=menu>
<a href="#" data-v=home><span class=icp>🏠</span><span class=t>{T('الرئيسية','Home')}</span></a>
<a href="#" data-v=subs><span class=icp>👥</span><span class=t>{T('مشتركين','Subs')}</span></a>
<a href="#" data-v=ledger><span class=icp>📒</span><span class=t>{T('دفتر','Ledger')}</span></a>
<a href="#" data-v=dishes><span class=icp>📡</span><span class=t>{T('صحون','Dishes')}</span></a>
<a href="#" data-v=towers><span class=icp>🗼</span><span class=t>{T('أبراج','Towers')}</span></a>
<a href="#" data-v=map><span class=icp>🗺️</span><span class=t>{T('خريطة','Map')}</span></a>
<a href="#" data-v=notifs><span class=icp>🔔</span><span class=t>{T('اشعارات','Notifs')}</span></a>
<a href="#" data-v=logs><span class=icp>📝</span><span class=t>{T('سجل','Logs')}</span></a>
<a href="#" data-v=settings><span class=icp>⚙️</span><span class=t>{T('اعدادات','Settings')}</span></a>
<a href="/logout" style="background:#dc2626;margin-top:10px"><span class=icp>🚪</span><span class=t>خروج</span></a>
</div>
<div class="main" id=main>{content}</div>
<a href="{wa}" target="_blank" style="position:fixed;bottom:18px;left:18px;background:#25D366;color:#fff;width:52px;height:52px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:26px;text-decoration:none;z-index:200">💬</a>
<script>
// تنقل نار بدون تحميل
var curV="{v}";
function setActive(){{document.querySelectorAll('#menu a[data-v]').forEach(a=>a.classList.toggle('active',a.dataset.v==curV));}}
setActive();
async function loadPage(v){{curV=v;setActive();var l=document.getElementById('loader');l.style.width='30%';
try{{var r=await fetch('/api/page?v='+v);var h=await r.text();document.getElementById('main').innerHTML=h;window.scrollTo(0,0);history.replaceState(null,'','/dash?v='+v);bindAjax();}}catch(e){{}}
l.style.width='100%';setTimeout(()=>l.style.width='0',200);}}
document.querySelectorAll('#menu a[data-v]').forEach(a=>a.onclick=e=>{{e.preventDefault();loadPage(a.dataset.v);}});
function bindAjax(){{
document.querySelectorAll('form[data-ajax]').forEach(f=>{{f.onsubmit=async e=>{{e.preventDefault();var fd=new FormData(f);await fetch(f.action,{{method:'POST',body:fd}});loadPage(curV);}}}});
document.querySelectorAll('a[data-ajax]').forEach(a=>{{a.onclick=async e=>{{e.preventDefault();await fetch(a.href);loadPage(curV);}}}});
document.querySelectorAll('a[data-del]').forEach(a=>{{a.onclick=async e=>{{e.preventDefault();if(!confirm('حذف؟'))return;await fetch(a.href);loadPage(curV);}}}});
}}
bindAjax();
</script>
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
            session['phone']=u['phone'];qexec("INSERT INTO logs(phone,act,dt) VALUES(?,?,?)",(ph,'دخول',datetime.datetime.now().isoformat()));return redirect('/dash')
        err="<p style='color:red'>❌ خطأ بالدخول</p>"
    return f"""<html dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{{margin:0;font-family:sans-serif;background:linear-gradient(#0f172a,#1e3a8a);min-height:100vh;display:flex;align-items:center;justify-content:center}}.box{{background:#fff;border-radius:16px;padding:22px;width:92%;max-width:360px;text-align:center}}input{{width:100%;padding:11px;margin:7px 0;border-radius:9px;border:1px solid #ccc}}button{{width:100%;padding:11px;background:#16a34a;color:#fff;border:0;border-radius:9px}}</style></head><body>
<div class=box><h2 style="color:#1e3a8a;margin:0">OMAIA ISP</h2><h3>تسجيل الدخول</h3>{err}
<form method=post id=f><input id=ph name=phone placeholder="رقم الهاتف"><input id=pw name=password type=password placeholder="كلمة المرور"><button>دخول</button></form>
<p style="font-size:12px">تصميم: م. عبدو عباس<br><a href="https://wa.me/{SUPPORT_WA}">+{SUPPORT_WA}</a></p></div></body></html>"""
@app.route('/logout')
def lo():
    ph=session.get('phone','')
    if ph: qexec("INSERT INTO logs(phone,act,dt) VALUES(?,?,?)",(ph,'خروج',datetime.datetime.now().isoformat()))
    session.clear();return redirect('/login')
@app.route('/lang')
def lg(): session['lang']='en' if L()=='ar' else 'ar';return redirect('/dash')
@app.route('/theme')
def thm(): session['theme']='dark' if dark()=='light' else 'light';return redirect(request.referrer or '/dash')

@app.route('/dash')
def dash():
    if not session.get('phone'):return redirect('/login')
    v=request.args.get('v','home')
    return layout(page_content(v),v)

@app.route('/api/page')
def apipage():
    if not session.get('phone'):return "login"
    return page_content(request.args.get('v','home'))

@app.route('/api_add_dish',methods=['POST'])
def api_add_dish():
    d=request.get_json(force=True)
    qexec("INSERT INTO dish_ips(ip,location,tower,lat,lng) VALUES(?,?,?,?,?)",(d.get('ip','')[:50],d.get('location','')[:100],d.get('tower','')[:100],fnum(d.get('lat')),fnum(d.get('lng'))))
    return "ok"

# actions
@app.route('/add_sub',methods=['POST'])
def asb(): qexec("INSERT INTO subs(name,phone) VALUES(?,?)",(request.form.get('name','')[:100],request.form.get('phone','')[:50]));return redirect('/dash?v=subs')
@app.route('/toggle_sub/<int:i>')
def tsb(i): qexec("UPDATE subs SET active=1-active WHERE id=?",(i,));return "ok"
@app.route('/edit_sub/<int:i>',methods=['GET','POST'])
def esb(i):
    if request.method=='POST':
        qexec("UPDATE subs SET name=?,phone=? WHERE id=?",(request.form.get('name',''),request.form.get('phone',''),i));return redirect('/dash?v=subs')
    r=qone("SELECT * FROM subs WHERE id=?",(i,)) or {}
    return layout(f"<div class=card><form method=post><input name=name value='{esc(r.get('name',''))}'><input name=phone value='{esc(r.get('phone',''))}'><button>حفظ</button></form></div>",'subs')
@app.route('/del_sub/<int:i>')
def dsb(i): qexec("DELETE FROM subs WHERE id=?",(i,));return "ok"
@app.route('/add_ledger',methods=['POST'])
def alb():
    f=request.form;sid=inum(f.get('sub_id'))
    qexec("INSERT INTO ledger(sub_id,amount,typ,note,dt) VALUES(?,?,?,?,?)",(sid,fnum(f.get('amount')),f.get('typ','دين')[:20],f.get('note','')[:200],datetime.datetime.now().isoformat()));return "ok"
@app.route('/del_ledger/<int:i>')
def dlb(i): qexec("DELETE FROM ledger WHERE id=?",(i,));return "ok"
@app.route('/add_dish',methods=['POST'])
def adh():
    f=request.form;qexec("INSERT INTO dish_ips(ip,location,tower,lat,lng) VALUES(?,?,?,?,?)",(f.get('ip','')[:50],f.get('location','')[:100],f.get('tower','')[:100],fnum(f.get('lat')),fnum(f.get('lng'))));return "ok"
@app.route('/del_dish/<int:i>')
def ddh(i): qexec("DELETE FROM dish_ips WHERE id=?",(i,));return "ok"
@app.route('/edit_dish/<int:i>',methods=['GET','POST'])
def edh(i):
    if request.method=='POST':
        f=request.form;qexec("UPDATE dish_ips SET ip=?,location=?,tower=?,lat=?,lng=? WHERE id=?",(f.get('ip','')[:50],f.get('location','')[:100],f.get('tower','')[:100],fnum(f.get('lat')),fnum(f.get('lng')),i));return redirect('/dash?v=dishes')
    r=qone("SELECT * FROM dish_ips WHERE id=?",(i,)) or {}
    tws=qall("SELECT name FROM towers LIMIT 200")
    opts="".join([f"<option {'selected' if t['name']==r.get('tower') else ''}>{esc(t['name'])}</option>" for t in tws])
    return layout(f"<div class=card><h3>✏️ تعديل صحن</h3><form method=post><input name=ip value='{esc(r.get('ip',''))}' placeholder=IP><input name=location value='{esc(r.get('location',''))}' placeholder=موقع><select name=tower><option>{esc(r.get('tower',''))}</option>{opts}</select><input name=lat value='{esc(r.get('lat',''))}'><input name=lng value='{esc(r.get('lng',''))}'><button>💾 حفظ</button></form></div>",'dishes')
@app.route('/add_tower',methods=['POST'])
def atw(): f=request.form;qexec("INSERT INTO towers(name,lat,lng) VALUES(?,?,?)",(f.get('name','')[:100],fnum(f.get('lat')),fnum(f.get('lng'))));return "ok"
@app.route('/del_tower/<int:i>')
def dtw(i): qexec("DELETE FROM towers WHERE id=?",(i,));return "ok"
@app.route('/add_notif',methods=['POST'])
def anf(): qexec("INSERT INTO notifs(txt,dt) VALUES(?,?)",(request.form.get('txt','')[:500],datetime.datetime.now().isoformat()));return "ok"
@app.route('/del_notif/<int:i>')
def dnf(i): qexec("DELETE FROM notifs WHERE id=?",(i,));return "ok"
@app.route('/change_user',methods=['POST'])
def chu():
    old=session.get('phone');new=request.form.get('newphone','').strip()
    if new:
        qexec("UPDATE users SET phone=? WHERE phone=?",(new,old));session['phone']=new
    return "ok"
@app.route('/change_pass',methods=['POST'])
def chp():
    qexec("UPDATE users SET password=? WHERE phone=?",(request.form.get('newpass','')[:100],session.get('phone')));return "ok"

if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
