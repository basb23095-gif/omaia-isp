from flask import Flask, request, redirect, session, jsonify
from colors import COLORS, logo_html
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, datetime, html, ipaddress, subprocess
try: import psycopg2, psycopg2.extras
except: psycopg2=None
import sqlite3

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY","omia-sec-2026-CHANGE-ME")
DATABASE_URL = os.environ.get("DATABASE_URL","").strip()
USE_PG = bool(DATABASE_URL and psycopg2)
_pg=None

def esc(s): return html.escape(str(s or ''), quote=True)
def db():
 global _pg
 if USE_PG:
  try:
   if _pg:
    c=_pg.cursor();c.execute("SELECT 1");c.close();return _pg
  except: _pg=None
  _pg=psycopg2.connect(DATABASE_URL,sslmode='require');_pg.autocommit=True;return _pg
 c=sqlite3.connect("omia.db",check_same_thread=False);c.row_factory=sqlite3.Row;return c
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

def init():
 ss=["CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,username TEXT)","CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT)","CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,amount REAL,note TEXT,currency TEXT)","CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,dish_name TEXT)","CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,area TEXT,lat REAL,lng REAL)"]
 if USE_PG: ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
 for s in ss: qexec(s)
 if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)):
  qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",('05344851045',generate_password_hash('admin2024'),'manager','admin'))
init()

def login_required(f):
 @wraps(f)
 def w(*a,**kw):
  if not session.get('phone'): return redirect('/login')
  return f(*a,**kw)
 return w
def me(): return qone("SELECT * FROM users WHERE phone=?",(session.get('phone'),))
def is_valid_ip(ip):
 try: ipaddress.ip_address(ip.strip());return True
 except: return False

@app.route('/api/ping')
@login_required
def api_ping():
 ip=request.args.get('ip','').strip()
 if not is_valid_ip(ip): return jsonify(ok=False,out='IP غير صالح')
 try:
  out=subprocess.check_output(['ping','-c','1','-W','2',ip],timeout=3).decode(errors='ignore')
  ok='ttl=' in out.lower()
  return jsonify(ok=ok,out='متصل' if ok else 'لا يرد')
 except: return jsonify(ok=False,out='لا يرد')

@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login',methods=['GET','POST'])
def login():
 if request.method=='POST':
  uin=request.form.get('userin','').strip();pw=request.form.get('password','')
  u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
  if u and check_password_hash(u['password'],pw):
   session['phone']=u['phone'];return redirect('/dash')
  return "<script>alert('خطأ بالدخول');location.href='/login'</script>"
 return """<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<style>body{margin:0;min-height:100vh;background:#0a0e2a;display:flex;flex-direction:column;align-items:center;justify-content:center;color:#fff;font-family:sans-serif}
.card{background:#1e2433;padding:25px;border-radius:20px;width:320px}input{width:100%;padding:12px;margin:8px 0;background:#0f1424;border:1px solid #333;color:#fff;border-radius:12px;box-sizing:border-box}
.btn{width:100%;padding:13px;border:0;border-radius:12px;background:#ffbe4d;font-weight:800;cursor:pointer}</style></head><body>
<div style='font-size:28px;font-weight:800;margin-bottom:15px'>OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<div class=card><form method=post><input name=userin placeholder='يوزر / رقم هاتف' required>
<input name=password type=password id=pw placeholder='كلمة السر' required>
<label style='font-size:13px'><input type=checkbox id=showpw style='width:auto'> حفظ / إظهار كلمة السر</label>
<button class=btn>دخول</button></form>
<div style='text-align:center;margin-top:15px'><a href='https://wa.me/905344851045' style='color:#22c55e;text-decoration:none'>📱 واتساب الدعم الفني</a></div></div>
<script>document.getElementById('showpw').onclick=function(){document.getElementById('pw').type=this.checked?'text':'password'};</script>
</body></html>"""

@app.route('/logout')
def lo(): session.clear();return redirect('/login')

@app.route('/dash')
@login_required
def dash(): return layout(page_content(request.args.get('v','home')),request.args.get('v','home'))

@app.route('/api/page')
@login_required
def ap(): return page_content(request.args.get('v','home'))

@app.route('/api/search')
@login_required
def s():
 q=request.args.get('q','').strip()
 if q: return jsonify(qall("SELECT * FROM dish_ips WHERE ip LIKE? OR dish_name LIKE? ORDER BY id DESC LIMIT 20",("%"+q+"%","%"+q+"%",)))
 return jsonify(qall("SELECT * FROM dish_ips ORDER BY id DESC LIMIT 20"))

@app.route('/toggle_theme')
@login_required
def tt(): session['theme']='light' if session.get('theme','dark')=='dark' else 'dark';return "ok"
@app.route('/toggle_lang')
@login_required
def tl(): session['lang']='en' if session.get('lang','ar')=='ar' else 'ar';return "ok"

@app.route('/add_dish',methods=['POST'])
@login_required
def ad():
 ip=request.form.get('ip','').strip()
 if not is_valid_ip(ip): return "IP غير صالح",400
 qexec("INSERT INTO dish_ips(ip,location,dish_name) VALUES(?,?,?)",(ip,request.form.get('location',''),request.form.get('dish_name','')));return "ok"
@app.route('/edit_dish/<int:i>',methods=['POST'])
@login_required
def ed(i):
 qexec("UPDATE dish_ips SET dish_name=?,ip=?,location=? WHERE id=?",(request.form.get('dish_name',''),request.form.get('ip',''),request.form.get('location',''),i));return "ok"
@app.route('/del_dish/<int:i>')
@login_required
def dd(i): qexec("DELETE FROM dish_ips WHERE id=?",(i,));return "ok"

@app.route('/add_tower',methods=['POST'])
@login_required
def at(): qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",(request.form.get('name',''),request.form.get('area',''),float(request.form.get('lat') or 35.1312),float(request.form.get('lng') or 36.7578)));return "ok"
@app.route('/del_tower/<int:i>')
@login_required
def dt(i): qexec("DELETE FROM towers WHERE id=?",(i,));return "ok"
@app.route('/edit_tower/<int:i>',methods=['POST'])
@login_required
def et(i): qexec("UPDATE towers SET name=?,area=? WHERE id=?",(request.form.get('name',''),request.form.get('area',''),i));return "ok"

@app.route('/add_sub',methods=['POST'])
@login_required
def asub(): qexec("INSERT INTO subs(name,phone) VALUES(?,?)",(request.form.get('name',''),request.form.get('phone','')));return "ok"
@app.route('/del_sub/<int:i>')
@login_required
def dsub(i): qexec("DELETE FROM subs WHERE id=?",(i,));return "ok"
@app.route('/edit_sub/<int:i>',methods=['POST'])
@login_required
def esub(i): qexec("UPDATE subs SET name=?,phone=? WHERE id=?",(request.form.get('name',''),request.form.get('phone',''),i));return "ok"

@app.route('/add_ledger',methods=['POST'])
@login_required
def al(): qexec("INSERT INTO ledger(name,amount,note,currency) VALUES(?,?,?,?)",(request.form.get('name',''),float(request.form.get('amount') or 0),request.form.get('note',''),request.form.get('currency','USD')));return "ok"
@app.route('/del_ledger/<int:i>')
@login_required
def dll(i): qexec("DELETE FROM ledger WHERE id=?",(i,));return "ok"
@app.route('/edit_ledger/<int:i>',methods=['POST'])
@login_required
def el(i): qexec("UPDATE ledger SET name=?,amount=?,note=? WHERE id=?",(request.form.get('name',''),float(request.form.get('amount') or 0),request.form.get('note',''),i));return "ok"

@app.route('/add_user',methods=['POST'])
@login_required
def au():
 ph=request.form.get('phone','').strip()
 if qone("SELECT * FROM users WHERE phone=?",(ph,)): return "موجود",400
 qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",(ph,generate_password_hash(request.form.get('password','1234')),request.form.get('role','tech'),request.form.get('username',ph)));return "ok"
@app.route('/change_pass',methods=['POST'])
@login_required
def cp(): qexec("UPDATE users SET password=? WHERE phone=?",(generate_password_hash(request.form.get('newpass','')),session.get('phone')));return "ok"

def page_content(v):
 if v=='home':
  ns=(qone("SELECT COUNT(*) c FROM subs") or {}).get('c',0);nd=(qone("SELECT COUNT(*) c FROM dish_ips") or {}).get('c',0);nt=(qone("SELECT COUNT(*) c FROM towers") or {}).get('c',0);nl=(qone("SELECT COUNT(*) c FROM ledger") or {}).get('c',0)
  return f"<div style='max-width:700px;margin:0 auto;text-align:center'><div style='display:grid;grid-template-columns:1fr 1fr;gap:12px'><div class=card onclick=\"loadPage('subs')\" style='cursor:pointer'><h3>المشتركين</h3><h2>{ns}</h2></div><div class=card onclick=\"loadPage('dishes')\" style='cursor:pointer'><h3>الصحون</h3><h2>{nd}</h2></div><div class=card onclick=\"loadPage('towers')\" style='cursor:pointer'><h3>الأبراج</h3><h2>{nt}</h2></div><div class=card onclick=\"loadPage('ledger')\" style='cursor:pointer'><h3>الحسابات</h3><h2>{nl}</h2></div></div></div>"
 if v=='dishes':
  return """<div style='max-width:900px;margin:0 auto'><div class=card><h3>الصحون - إضافة IP / اسم</h3>
  <form data-ajax method=post action=/add_dish style='display:flex;gap:5px;flex-wrap:wrap'><input name=dish_name placeholder='اسم' required style='flex:1'><input name=ip placeholder='IP' required style='flex:1'><input name=location placeholder='موقع' style='flex:1'><button class=btn-gold>إضافة</button></form></div><div id=dl></div>
  <script>async function ld(q=''){let r=await fetch('/api/search?q='+encodeURIComponent(q));let d=await r.json();let h='';d.forEach(x=>{h+=`<div class=card><b>${x.dish_name}</b> - ${x.ip} (${x.location||''}) <button onclick="p1('${x.ip}',this)">بينغ</button><span></span> <button onclick="editDish(${x.id})">تعديل</button> <button onclick="delItem('/del_dish/${x.id}')">حذف</button></div>`});document.getElementById('dl').innerHTML=h}
  async function p1(ip,b){let s=b.nextElementSibling;s.textContent='...';let r=await fetch('/api/ping?ip='+ip);let j=await r.json();s.textContent=j.out}
  function editDish(id){let n=prompt('اسم جديد:');if(n==null)return;let ip=prompt('IP جديد:');fetch('/edit_dish/'+id,{method:'POST',body:new URLSearchParams({dish_name:n,ip:ip||''})}).then(()=>ld())}ld();window.searchDishes=ld;</script></div>"""
 if v=='towers':
  rs=qall("SELECT * FROM towers ORDER BY id DESC");rows=""
  for r in rs: rows+=f"<div class=card><b>{esc(r['name'])}</b> - {esc(r['area'])} <button onclick='editTower({r['id']})'>تعديل</button> <button onclick=\"delItem('/del_tower/{r['id']}')\">حذف</button></div>"
  return f"<div style='max-width:700px;margin:0 auto'><div class=card><h3>الأبراج - إضافة برج / اسم / موقع</h3><form data-ajax method=post action=/add_tower><input name=name placeholder='اسم البرج' required><input name=area placeholder='الموقع'><button class=btn-gold>إضافة</button></form></div>{rows}<script>function editTower(id){{let n=prompt('اسم:');if(n==null)return;fetch('/edit_tower/'+id,{{method:'POST',body:new URLSearchParams({{name:n}})}}).then(()=>loadPage('towers'))}}</script></div>"
 if v=='subs':
  rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 100");rows=""
  for r in rs: rows+=f"<div class=card><b>{esc(r['name'])}</b> - {esc(r['phone'])} <button onclick='editSub({r['id']})'>تعديل</button> <button onclick=\"delItem('/del_sub/{r['id']}')\">حذف</button></div>"
  return f"<div style='max-width:700px;margin:0 auto'><div class=card><h3>إضافات - يوزر / رقم هاتف بكرت واحد</h3><form data-ajax method=post action=/add_sub><input name=name placeholder='يوزر' required><input name=phone placeholder='رقم هاتف'><button class=btn-gold>إضافة</button></form></div>{rows}<script>function editSub(id){{let n=prompt('يوزر:');if(n==null)return;fetch('/edit_sub/'+id,{{method:'POST',body:new URLSearchParams({{name:n}})}}).then(()=>loadPage('subs'))}}</script></div>"
 if v=='ledger':
  rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 100");rows=""
  for r in rs: rows+=f"<div class=card><b>{esc(r['name'])}</b> {r['amount']} {esc(r['currency'])} - {esc(r['note'])} <button onclick='editL({r['id']})'>تعديل</button> <button onclick=\"delItem('/del_ledger/{r['id']}')\">حذف</button></div>"
  return f"""<div style='max-width:700px;margin:0 auto'><div class=card><h3>دفتر حسابات</h3>
  <form data-ajax method=post action=/add_ledger><input name=name placeholder='اسم' required><input name=amount type=number step=0.01 placeholder='مبلغ' required><input name=note placeholder='ملاحظة'><select name=currency><option value=USD>دولار</option><option value=SYP>سوري</option></select><button class=btn-gold>إضافة</button></form></div>{rows}
  <script>function editL(id){{let n=prompt('اسم:');if(n==null)return;fetch('/edit_ledger/'+id,{{method:'POST',body:new URLSearchParams({{name:n}})}}).then(()=>loadPage('ledger'))}}</script></div>"""
 if v=='map':
  return """<div class=card><h3>خريطة حماة - دقة عالية</h3><input id=mapsearch placeholder='بحث بالخريطة...' style='margin-bottom:8px'>
  <div id=map style='height:65vh;border-radius:12px'></div><div style='margin-top:8px'><button class=btn-gold onclick='addPin()'>إضافة دبوس</button> <button class=btn-gold onclick='measure()'>قياس مسافة</button></div>
  <script>var map=L.map('map',{tap:true,dragging:true}).setView([35.1312,36.7578],14);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19}).addTo(map);
  setTimeout(()=>map.invalidateSize(),500);
  var pins=[];
  function addPin(){var c=map.getCenter();var m=L.marker(c,{draggable:true}).addTo(map).bindPopup('دبوس جديد').openPopup();pins.push(m)}
  var mLine=null,pts=[];
  function measure(){alert('اضغط على الخريطة لنقطتين لقياس المسافة');map.on('click',function(e){pts.push(e.latlng);if(pts.length==2){var d=map.distance(pts[0],pts[1]);alert('المسافة: '+Math.round(d)+' متر');pts=[];if(mLine)map.removeLayer(mLine);}})}
  document.getElementById('mapsearch').addEventListener('change',async function(){let q=this.value;let r=await fetch(`https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(q)}`);let j=await r.json();if(j[0]){map.setView([j[0].lat,j[0].lon],15);L.marker([j[0].lat,j[0].lon]).addTo(map)}});
  </script></div>"""
 if v=='support':
  return f"<div class=card style='text-align:center;max-width:500px;margin:0 auto'><h2>{logo_html()}</h2><p>الدعم الفني</p><a href='https://wa.me/905344851045' target=_blank style='display:inline-block;background:#22c55e;color:#fff;padding:12px 20px;border-radius:10px;text-decoration:none;margin:5px'>📱 واتساب: +905344851045</a><br><a href='https://instagram.com/af_20_1999' target=_blank style='color:#ffbe4d'>انستغرام: af_20_1999</a></div>"
 if v=='settings':
  us=qall("SELECT * FROM users ORDER BY phone DESC")
  uh="".join([f"<div class=card>{esc(u['username'])} - {esc(u['phone'])} ({esc(u['role'])})</div>" for u in us])
  return f"""<div style='max-width:600px;margin:0 auto'><div class=card><h3>الإعدادات</h3>
  <button class=btn-gold onclick="fetch('/toggle_theme').then(()=>location.reload())">🌙 ليل / نهار</button>
  <button class=btn-gold onclick="fetch('/toggle_lang').then(()=>location.reload())">🌐 عربي / English</button>
  <form data-ajax method=post action=/change_pass style='margin-top:10px'><input name=newpass type=password placeholder='كلمة سر جديدة' required><button class=btn-gold>تغيير كلمة السر</button></form></div>
  <div class=card><h3>المستخدمين - تسجيل وتعديل</h3><form data-ajax method=post action=/add_user><input name=username placeholder='يوزر' required><input name=phone placeholder='رقم هاتف' required><input name=password placeholder='كلمة السر'><select name=role><option value=tech>فني</option><option value=manager>مدير</option></select><button class=btn-gold>إضافة يوزر</button></form></div>{uh}
  <div class=card><h3>الإشعارات</h3><p>لا توجد إشعارات جديدة</p></div></div>"""
 return "<div class=card>ok</div>"

def layout(c,v='home'):
 th=session.get('theme','dark');is_dark=(th=='dark')
 bg=COLORS['bg_dark'] if is_dark else COLORS['bg_light']
 card_bg=COLORS['card_dark'] if is_dark else COLORS['card_light']
 txt=COLORS['text_dark'] if is_dark else COLORS['text_light']
 return f"""<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<link rel=stylesheet href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'>
<style>*{{box-sizing:border-box;font-family:sans-serif}}body{{margin:0;background:{bg};color:{txt}}}
.top{{position:fixed;top:0;left:0;right:0;height:60px;background:#111827;color:#fff;display:flex;align-items:center;justify-content:space-between;padding:0 12px;z-index:1003}}
.top.logo{{position:absolute;left:50%;transform:translateX(-50%);font-weight:800}}
.searchbox{{background:#1f2937;border:1px solid #374151;color:#fff;padding:8px 12px;border-radius:10px;width:180px}}
.sidebar{{position:fixed;right:0;top:0;width:270px;height:100%;background:#111827;color:#fff;z-index:1002;padding-top:70px;transform:translateX(300px);transition:.25s}}
.sidebar.active{{transform:translateX(0)}}.sidebar a{{display:block;padding:12px 18px;margin:4px 8px;color:#fff;text-decoration:none;border-radius:8px}}.sidebar a:hover{{background:#1f2937}}
#overlay{{position:fixed;inset:0;background:#0007;z-index:1001;display:none}}#overlay.show{{display:block}}
.main{{margin-top:70px;padding:12px;min-height:90vh}}
.card{{background:{card_bg};color:{txt};padding:14px;border-radius:12px;margin-bottom:10px;box-shadow:0 2px 8px #0002}}
input,select{{padding:10px;margin:5px 0;border-radius:8px;border:1px solid #ddd;width:100%}}
.btn-gold{{background:{COLORS['gold']};padding:9px 14px;border:0;border-radius:8px;font-weight:700;cursor:pointer;margin:2px}}</style></head>
<body><div id=overlay onclick="toggleSb(false)"></div>
<div class=sidebar id=sb>
<a href="javascript:loadPage('home')">🏠 الرئيسية</a><a href="javascript:loadPage('dishes')">📡 الصحون</a>
<a href="javascript:loadPage('towers')">🗼 الأبراج</a><a href="javascript:loadPage('subs')">👥 المشتركين</a>
<a href="javascript:loadPage('ledger')">📒 دفتر حسابات</a><a href="javascript:loadPage('map')">🗺️ الخريطة</a>
<a href="javascript:loadPage('support')">🛠️ الدعم الفني</a><a href="javascript:loadPage('settings')">⚙️ الإعدادات</a>
<a href=/logout>🚪 خروج</a></div>
<div class=top><div style='display:flex;gap:10px;align-items:center'><span onclick="toggleSb()" style='font-size:22px;cursor:pointer'>☰</span>
<input class=searchbox id=topsearch placeholder='بحث...' oninput="if(cur==\"dishes\"&&window.searchDishes)searchDishes(this.value)"></div>
<div class=logo>{logo_html()}</div><div><button onclick="loadPage(cur)" style='background:#1f2937;color:#fff;border:0;padding:8px 12px;border-radius:8px'>↻</button></div></div>
<div class=main id=mn>{c}</div>
<script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>
<script>let cur='{v}';
function toggleSb(f){{let sb=document.getElementById('sb'),ov=document.getElementById('overlay');let o=f!==undefined?f:!sb.classList.contains('active');sb.classList.toggle('active',o);ov.classList.toggle('show',o)}}
async function loadPage(v){{cur=v;toggleSb(false);document.getElementById('mn').innerHTML='<div class=card>جاري التحميل...</div>';let r=await fetch('/api/page?v='+v);document.getElementById('mn').innerHTML=await r.text();bind()}}
function bind(){{document.querySelectorAll('form[data-ajax]').forEach(f=>{{f.onsubmit=async e=>{{e.preventDefault();let r=await fetch(f.action,{{method:'POST',body:new FormData(f)}});if(r.ok)loadPage(cur);else alert(await r.text())}}}})}}
window.delItem=async u=>{{if(!confirm('حذف؟'))return;await fetch(u);loadPage(cur)}};bind();</script></body></html>"""

if __name__=='__main__':
 app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
