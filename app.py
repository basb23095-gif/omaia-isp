from flask import Flask, request, redirect, session
import os, datetime, json, html
try:
 import psycopg2, psycopg2.extras
except: psycopg2=None
import sqlite3
app=Flask(__name__)
app.secret_key=os.environ.get("SECRET_KEY","omia-sec-2026")
DATABASE_URL=os.environ.get("DATABASE_URL","").strip().replace("postgresql://","postgres://")
USE_PG=bool(DATABASE_URL.startswith("postgres://") and psycopg2)
_pg=None
SUPPORT_WA="905344851045"
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
   cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor);cur.execute(q.replace("?","%s"),a);rs=[dict(r) for r in cur.fetchall()];cur.close();return rs
  else: rs=[dict(r) for r in c.execute(q,a).fetchall()];cc(c);return rs
 except: cc(c);return []
def qone(q,a=()):
 r=qall(q,a);return r[0] if r else None
def qexec(q,a=()):
 c=db()
 try:
  if USE_PG: cur=c.cursor();cur.execute(q.replace("?","%s"),a);cur.close()
  else: c.execute(q,a);c.commit();cc(c)
 except: cc(c)
def fnum(v):
 try:return float(v or 0)
 except:return 0
def inum(v):
 try:return int(float(v))
 except:return None
def init():
 ss=["CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,active INT DEFAULT 1)","CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,active INT DEFAULT 1)","CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,sub_id INT,amount REAL,typ TEXT,note TEXT,dt TEXT)","CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,tower TEXT,lat REAL DEFAULT 0,lng REAL DEFAULT 0)","CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,lat REAL,lng REAL)","CREATE TABLE IF NOT EXISTS notifs(id INTEGER PRIMARY KEY AUTOINCREMENT,txt TEXT,dt TEXT)","CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,phone TEXT,act TEXT,dt TEXT)"]
 if USE_PG: ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
 for s in ss: qexec(s)
 if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)): qexec("INSERT INTO users(phone,password,role,active) VALUES(?,?,?,?)",('05344851045','admin2024','super',1))
init()
def L(): return session.get('lang','ar')
def T(ar,en): return ar if L()=='ar' else en
def dark(): return session.get('theme','light')

def page_content(v):
 h=""
 if v=='home':
  ns=(qone("SELECT COUNT(*) c FROM subs") or {}).get('c',0);nd=(qone("SELECT COUNT(*) c FROM dish_ips") or {}).get('c',0);nt=(qone("SELECT COUNT(*) c FROM towers") or {}).get('c',0)
  h=f"""<div class=grid><div class="kpi" style="background:#2563eb">👥 العملاء<br>{ns}</div><div class="kpi" style="background:#16a34a">📡 الصحون<br>{nd}</div><div class="kpi" style="background:#dc2626">🗼 الأبراج<br>{nt}</div><div class="kpi" style="background:#f59e0b">✅ مفعلين<br>{ns}</div></div><div class=card><h3>مرحبا {esc(session.get('phone'))}</h3></div>"""
 elif v=='subs':
  rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 100")
  h=f"""<div class=card><h3>👥 مشتركين</h3><form data-ajax method=post action="/add_sub"><input name=name placeholder="الاسم" required><input name=phone placeholder="هاتف" required><button>اضافة</button></form></div>"""
  for r in rs: h+=f"<div class=card>{esc(r['name'])} - {esc(r['phone'])} {'✅' if r['active'] else '❌'} <a href='/toggle_sub/{r['id']}' data-ajax>🔄</a> <a href='/dash?v=edit_sub&id={r['id']}'>تعديل</a> <a href='/del_sub/{r['id']}' data-del>حذف</a></div>"
 elif v=='edit_sub':
  i=request.args.get('id');r=qone("SELECT * FROM subs WHERE id=?",(i,)) or {}
  h=f"<div class=card><h3>تعديل مشترك</h3><form data-ajax method=post action='/edit_sub/{i}'><input name=name value='{esc(r.get('name',''))}'><input name=phone value='{esc(r.get('phone',''))}'><button>حفظ</button></form></div>"
 elif v=='ledger':
  rs=qall("SELECT l.*, s.name sn FROM ledger l LEFT JOIN subs s ON s.id=l.sub_id ORDER BY l.id DESC LIMIT 100")
  subs=qall("SELECT id,name FROM subs LIMIT 200");opts="".join([f"<option value='{x['id']}'>{x['id']}-{esc(x['name'])}</option>" for x in subs])
  h=f"""<div class=card><h3>📒 دفتر حسابات</h3><form data-ajax method=post action="/add_ledger"><select name=sub_id><option value="">بدون مشترك</option>{opts}</select><input name=amount type=number step=0.01 required placeholder=مبلغ><select name=typ><option>دين</option><option>دفع</option></select><input name=note placeholder=ملاحظة><button>اضافة</button></form></div>"""
  for r in rs: h+=f"<div class=card>#{r['id']} {esc(r.get('sn') or '')} {r['amount']} {esc(r['typ'])} <a href='/del_ledger/{r['id']}' data-del>حذف</a></div>"
 elif v=='dishes':
  rs=qall("SELECT * FROM dish_ips ORDER BY id DESC LIMIT 200");tws=qall("SELECT name FROM towers LIMIT 200");two="".join([f"<option>{esc(t['name'])}</option>" for t in tws])
  h=f"""<div class=card><h3>📡 صحون</h3><form data-ajax method=post action="/add_dish"><input name=ip placeholder="IP" required><input name=location placeholder="موقع"><select name=tower><option value="">اختر برج</option>{two}</select><input name=lat id=lat placeholder=lat type=number step=any><input name=lng id=lng placeholder=lng type=number step=any><button>اضافة</button></form><button onclick="getLoc()">📍 موقعي</button></div>"""
  for r in rs:
   ip=esc(r.get('ip',''))
   h+=f"""<div class=card style="font-size:13px">🌐 <a href="http://{ip}" target="_blank">{ip}</a> | {esc(r.get('location',''))} | {esc(r.get('tower',''))}<br><button style="padding:4px 8px;font-size:12px" onclick="pingIP('{ip}',this)">Ping</button> <span class=ping></span> <a href="/dash?v=edit_dish&id={r['id']}" style="font-size:12px">تعديل</a> | <a href="/del_dish/{r['id']}" data-del style="font-size:12px;color:red">حذف</a></div>"""
 elif v=='edit_dish':
  i=request.args.get('id');r=qone("SELECT * FROM dish_ips WHERE id=?",(i,)) or {}
  h=f"<div class=card><h3>تعديل صحن</h3><form data-ajax method=post action='/edit_dish/{i}'><input name=ip value='{esc(r.get('ip',''))}'><input name=location value='{esc(r.get('location',''))}'><input name=tower value='{esc(r.get('tower',''))}'><input name=lat value='{esc(r.get('lat',''))}'><input name=lng value='{esc(r.get('lng',''))}'><button>حفظ</button></form></div>"
 elif v=='towers':
  rs=qall("SELECT * FROM towers ORDER BY id DESC LIMIT 100")
  h=f"""<div class=card><h3>🗼 أبراج</h3><form data-ajax method=post action="/add_tower"><input name=name placeholder=اسم required><input name=lat placeholder=lat type=number step=any><input name=lng placeholder=lng type=number step=any><button>اضافة</button></form></div>"""
  for r in rs: h+=f"<div class=card>{esc(r.get('name',''))} <a href='/del_tower/{r['id']}' data-del>حذف</a></div>"
 elif v=='map':
  ds=qall("SELECT id,ip,location,lat,lng FROM dish_ips WHERE lat!=0 LIMIT 300");ts=qall("SELECT name,lat,lng FROM towers WHERE lat!=0 LIMIT 300")
  ds_j=json.dumps([{"id":d["id"],"la":float(d.get("lat") or 0),"ln":float(d.get("lng") or 0),"n":str(d.get("location","")),"ip":str(d.get("ip",""))} for d in ds if d.get("lat")],ensure_ascii=False).replace("</","<\\/")
  ts_j=json.dumps([{"la":float(t.get("lat") or 0),"ln":float(t.get("lng") or 0),"n":str(t.get("name",""))} for t in ts if t.get("lat")],ensure_ascii=False).replace("</","<\\/")
  h=f'''<div class=card><h3>🗺️ خريطة</h3><button onclick="addMode()">➕ نقطة</button> <button onclick="measureMode()">📏 مسافة</button> <span id=minfo></span><div id="mp" style="height:70vh;border-radius:10px"></div></div><script>var DS={ds_j},TS={ts_j};initMap();</script>'''
 elif v=='notifs':
  rs=qall("SELECT * FROM notifs ORDER BY id DESC LIMIT 50")
  h=f"""<div class=card><h3>🔔 اشعارات</h3><form data-ajax method=post action="/add_notif"><input name=txt required placeholder=نص><button>اضافة</button></form></div>"""
  for r in rs: h+=f"<div class=card>{esc(r['txt'])} <a href='/del_notif/{r['id']}' data-del>حذف</a></div>"
 elif v=='logs':
  rs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 100");h="<div class=card><h3>📝 سجل</h3></div>"
  for r in rs: h+=f"<div class=card>{esc(r['phone'])} - {esc(r['act'])}</div>"
 elif v=='settings':
  ph=esc(session.get('phone',''))
  h=f"""<div class=card><h3>⚙️ اعدادات</h3><p>اليوزر الحالي: <b>{ph}</b></p><form data-ajax method=post action="/change_user"><input name=newphone placeholder="يوزر جديد" required><button>🔄 تغيير اليوزر الحالي</button></form><form data-ajax method=post action="/change_pass"><input name=newpass type=password placeholder="كلمة سر جديدة" required><button>🔑 تغيير كلمة السر</button></form></div>"""
 return h

def layout(content,v='home'):
 th=dark();bg='#0f172a' if th=='dark' else '#f1f5f9';card='#1e293b' if th=='dark' else '#fff';txt='#f1f5f9' if th=='dark' else '#0f172a'
 return f"""<html dir=rtl><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"><style>
*{{box-sizing:border-box}}body{{margin:0;font-family:sans-serif;background:{bg};color:{txt}}}
.top{{position:fixed;top:0;left:0;right:0;background:#1e3a8a;color:#fff;padding:12px;text-align:center;z-index:100;font-weight:bold}}
.menu{{position:fixed;top:48px;bottom:0;right:0;width:200px;background:#1e3a8a;padding:10px;z-index:99;transition:.2s}}
.menu a{{display:flex;gap:8px;color:#fff;text-decoration:none;padding:11px;border-radius:8px;margin:3px 0}}
.menu.icp{{font-size:18px;width:26px;height:26px;display:flex;align-items:center;justify-content:center;background:#ffffff20;border-radius:7px}}
.main{{margin-right:210px;margin-top:60px;padding:10px}}
.card{{background:{card};border-radius:10px;padding:10px;margin:8px 0}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px}}.kpi{{padding:12px;border-radius:10px;color:#fff;text-align:center;font-weight:bold}}
input,select{{width:100%;padding:8px;margin:4px 0;border-radius:7px;border:1px solid #ccc}}button{{padding:8px 12px;border-radius:7px;border:0;background:#16a34a;color:#fff}}
.logout-small{{background:#dc2626!important;font-size:12px!important;padding:6px 8px!important;margin-top:8px}}
@media(max-width:700px){{.menu{{width:180px;transform:translateX(100%)}}.menu.open{{transform:none}}.main{{margin-right:0}}}}
</style></head><body>
<div class=top>OMAIA ISP</div>
<div class=menu id=menu>
<a href=# data-v=home><span class=icp>🏠</span>الرئيسية</a><a href=# data-v=subs><span class=icp>👥</span>مشتركين</a><a href=# data-v=ledger><span class=icp>📒</span>دفتر</a><a href=# data-v=dishes><span class=icp>📡</span>صحون</a><a href=# data-v=towers><span class=icp>🗼</span>أبراج</a><a href=# data-v=map><span class=icp>🗺️</span>خريطة</a><a href=# data-v=notifs><span class=icp>🔔</span>اشعارات</a><a href=# data-v=logs><span class=icp>📝</span>سجل</a><a href=# data-v=settings><span class=icp>⚙️</span>اعدادات</a><a href=/logout class=logout-small><span class=icp>🚪</span>خروج</a>
</div><div class=main id=main>{content}</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
var curV="{v}",_mapMode=null,_pts=[],_line=null;
function getLoc(){{navigator.geolocation.getCurrentPosition(p=>{{document.getElementById('lat').value=p.coords.latitude.toFixed(6);document.getElementById('lng').value=p.coords.longitude.toFixed(6);}})}}
function pingIP(ip,btn){{var s=btn.parentElement.querySelector('.ping');s.textContent='⏳';var t0=Date.now();fetch('http://'+ip,{{mode:'no-cors'}}).then(()=>s.textContent='✅ '+(Date.now()-t0)+'ms').catch(()=>s.textContent='❌');setTimeout(()=>{{if(s.textContent=='⏳')s.textContent='❌ timeout'}},4000)}}
function addMode(){{_mapMode='add'}}function measureMode(){{_mapMode='measure';_pts=[]}}
function initMap(){{if(typeof L=="undefined"){{setTimeout(initMap,300);return}}var m=L.map('mp').setView([35.13,36.75],12);window._m=m;L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',{{maxZoom:18}}).addTo(m);DS.forEach(d=>L.marker([d.la,d.ln]).addTo(m).bindPopup(d.n+'<br>'+d.ip));TS.forEach(t=>L.circleMarker([t.la,t.ln],{{color:'red',radius:8}}).addTo(m).bindPopup(t.n));m.on('click',e=>{{if(_mapMode=='add'){{var ip=prompt('IP:');if(!ip)return;fetch('/api_add_dish',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{ip:ip,lat:e.latlng.lat,lng:e.latlng.lng}})}}).then(()=>loadPage('map'))}}if(_mapMode=='measure'){{_pts.push(e.latlng);if(_pts.length==2){{var d=m.distance(_pts[0],_pts[1]);document.getElementById('minfo').textContent=(d/1000).toFixed(2)+' كم';_pts=[]}}}});setTimeout(()=>m.invalidateSize(),300)}}
async function loadPage(v){{curV=v;document.getElementById('loader').style.width='40%';var r=await fetch('/api/page?v='+v);var h=await r.text();var el=document.getElementById('main');el.innerHTML=h;el.querySelectorAll('script').forEach(s=>eval(s.textContent));bindAjax();closeMenu();document.getElementById('loader').style.width='100%';setTimeout(()=>document.getElementById('loader').style.width='0',200)}}
function bindAjax(){{document.querySelectorAll('form[data-ajax]').forEach(f=>f.onsubmit=async e=>{{e.preventDefault();await fetch(f.action,{{method:'POST',body:new FormData(f)}});loadPage(curV)}});document.querySelectorAll('a[data-ajax]').forEach(a=>a.onclick=async e=>{{e.preventDefault();await fetch(a.href);loadPage(curV)}});document.querySelectorAll('a[data-del]').forEach(a=>a.onclick=async e=>{{e.preventDefault();if(!confirm('حذف؟'))return;await fetch(a.href);loadPage(curV)}})}}
document.querySelectorAll('#menu a[data-v]').forEach(a=>a.onclick=e=>{{e.preventDefault();loadPage(a.dataset.v)}});
function closeMenu(){{document.getElementById('menu').classList.remove('open')}}
document.addEventListener('click',e=>{{var m=document.getElementById('menu');if(!m.contains(e.target) && window.innerWidth<700) closeMenu()}});
bindAjax();
</script><div id=loader style="position:fixed;top:0;left:0;height:3px;background:#22c55e;width:0;z-index:200"></div></body></html>"""

@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')
@app.route('/login',methods=['GET','POST'])
def login():
 err=""
 if request.method=='POST':
  ph=request.form.get('phone','').strip();pw=request.form.get('password','')
  u=qone("SELECT * FROM users WHERE phone=?",(ph,))
  if u and u['password']==pw: session['phone']=u['phone'];qexec("INSERT INTO logs(phone,act,dt) VALUES(?,?,?)",(ph,'دخول',datetime.datetime.now().isoformat()));return redirect('/dash')
  err="<p style=color:red>❌ خطأ</p>"
 return f"""<html dir=rtl><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><style>body{{margin:0;font-family:sans-serif;background:#0f172a;display:flex;align-items:center;justify-content:center;min-height:100vh}}.box{{background:#fff;padding:20px;border-radius:12px;width:92%;max-width:340px}}input{{width:100%;padding:10px;margin:6px 0;border-radius:8px;border:1px solid #ccc}}button{{width:100%;padding:10px;background:#16a34a;color:#fff;border:0;border-radius:8px}}</style></head><body><div class=box><h3>OMAIA ISP</h3>{err}<form method=post id=f><input id=ph name=phone placeholder="يوزر"><input id=pw name=password type=password placeholder="كلمة السر"><label><input type=checkbox id=rm style="width:auto"> حفظ كلمة السر</label><button>دخول</button></form></div><script>var ph=document.getElementById('ph'),pw=document.getElementById('pw'),rm=document.getElementById('rm');ph.value=localStorage.getItem('ph')||'';pw.value=localStorage.getItem('pw')||'';if(ph.value)rm.checked=true;document.getElementById('f').onsubmit=()=>{{if(rm.checked){{localStorage.setItem('ph',ph.value);localStorage.setItem('pw',pw.value)}}else{{localStorage.removeItem('ph');localStorage.removeItem('pw')}}}};</script></body></html>"""
@app.route('/logout')
def lo():
 ph=session.get('phone','')
 if ph: qexec("INSERT INTO logs(phone,act,dt) VALUES(?,?,?)",(ph,'خروج',datetime.datetime.now().isoformat()))
 session.clear();return redirect('/login')
@app.route('/dash')
def dash():
 if not session.get('phone'):return redirect('/login')
 v=request.args.get('v','home');return layout(page_content(v),v)
@app.route('/api/page')
def apip():
 if not session.get('phone'):return "login"
 return page_content(request.args.get('v','home'))
@app.route('/api_add_dish',methods=['POST'])
def apiadd():
 if not session.get('phone'):return "no"
 d=request.get_json(force=True);qexec("INSERT INTO dish_ips(ip,location,tower,lat,lng) VALUES(?,?,?,?,?)",(d.get('ip','')[:50],d.get('location','')[:100],'',fnum(d.get('lat')),fnum(d.get('lng'))));return "ok"
@app.route('/add_sub',methods=['POST'])
def a1(): qexec("INSERT INTO subs(name,phone) VALUES(?,?)",(request.form.get('name','')[:100],request.form.get('phone','')[:50]));return "ok"
@app.route('/toggle_sub/<int:i>')
def a2(i): qexec("UPDATE subs SET active=1-active WHERE id=?",(i,));return "ok"
@app.route('/edit_sub/<int:i>',methods=['POST'])
def a3(i): qexec("UPDATE subs SET name=?,phone=? WHERE id=?",(request.form.get('name',''),request.form.get('phone',''),i));return "ok"
@app.route('/del_sub/<int:i>')
def a4(i): qexec("DELETE FROM subs WHERE id=?",(i,));return "ok"
@app.route('/add_ledger',methods=['POST'])
def b1(): f=request.form;qexec("INSERT INTO ledger(sub_id,amount,typ,note,dt) VALUES(?,?,?,?,?)",(inum(f.get('sub_id')),fnum(f.get('amount')),f.get('typ','دين'),f.get('note','')[:200],datetime.datetime.now().isoformat()));return "ok"
@app.route('/del_ledger/<int:i>')
def b2(i): qexec("DELETE FROM ledger WHERE id=?",(i,));return "ok"
@app.route('/add_dish',methods=['POST'])
def c1(): f=request.form;qexec("INSERT INTO dish_ips(ip,location,tower,lat,lng) VALUES(?,?,?,?,?)",(f.get('ip','')[:50],f.get('location','')[:100],f.get('tower','')[:100],fnum(f.get('lat')),fnum(f.get('lng'))));return "ok"
@app.route('/del_dish/<int:i>')
def c2(i): qexec("DELETE FROM dish_ips WHERE id=?",(i,));return "ok"
@app.route('/edit_dish/<int:i>',methods=['POST'])
def c3(i): f=request.form;qexec("UPDATE dish_ips SET ip=?,location=?,tower=?,lat=?,lng=? WHERE id=?",(f.get('ip','')[:50],f.get('location','')[:100],f.get('tower','')[:100],fnum(f.get('lat')),fnum(f.get('lng')),i));return "ok"
@app.route('/add_tower',methods=['POST'])
def d1(): f=request.form;qexec("INSERT INTO towers(name,lat,lng) VALUES(?,?,?)",(f.get('name','')[:100],fnum(f.get('lat')),fnum(f.get('lng'))));return "ok"
@app.route('/del_tower/<int:i>')
def d2(i): qexec("DELETE FROM towers WHERE id=?",(i,));return "ok"
@app.route('/add_notif',methods=['POST'])
def e1(): qexec("INSERT INTO notifs(txt,dt) VALUES(?,?)",(request.form.get('txt','')[:500],datetime.datetime.now().isoformat()));return "ok"
@app.route('/del_notif/<int:i>')
def e2(i): qexec("DELETE FROM notifs WHERE id=?",(i,));return "ok"
@app.route('/change_user',methods=['POST'])
def f1(): old=session.get('phone');new=request.form.get('newphone','').strip();qexec("UPDATE users SET phone=? WHERE phone=?",(new,old));session['phone']=new;return "ok"
@app.route('/change_pass',methods=['POST'])
def f2(): qexec("UPDATE users SET password=? WHERE phone=?",(request.form.get('newpass','')[:100],session.get('phone')));return "ok"
if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
