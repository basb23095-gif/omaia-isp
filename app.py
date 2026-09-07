from flask import Flask, request, redirect, session, jsonify, Response
from colors import COLORS, logo_html
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, datetime, json, html, subprocess, platform, io, csv
try: import psycopg2, psycopg2.extras
except: psycopg2=None
import sqlite3
app=Flask(__name__)
app.secret_key=os.environ.get("SECRET_KEY","omia-sec-2026")
DATABASE_URL=os.environ.get("DATABASE_URL","").strip().replace("postgresql://","postgres://")
USE_PG=bool(DATABASE_URL.startswith("postgres://") and psycopg2)
_pg=None
def esc(s): return html.escape(str(s or ''),quote=True)
def db():
 global _pg
 if USE_PG:
  try:
   if _pg:
    c=_pg.cursor();c.execute("SELECT 1");c.close();return _pg
  except:
   try:_pg.close()
   except:pass
   _pg=None
  _pg=psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=5);_pg.autocommit=True;return _pg
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
  rs=[dict(r) for r in c.execute(q,a).fetchall()];cc(c);return rs
 except: cc(c);return []
def qone(q,a=()):
 r=qall(q,a);return r[0] if r else None
def qexec(q,a=()):
 c=db()
 try:
  if USE_PG: cur=c.cursor();cur.execute(q.replace("?","%s"),a);cur.close()
  else: c.execute(q,a);c.commit();cc(c)
 except Exception as e: print(e);cc(c)
def fnum(v):
 try: return float(v or 0)
 except: return 0
def init():
 ss=["CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,active INT DEFAULT 1,username TEXT)","CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT)","CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,note TEXT,amount REAL,currency TEXT,dt TEXT)","CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,dish_name TEXT)","CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,area TEXT,lat REAL,lng REAL)","CREATE TABLE IF NOT EXISTS activity_log(id INTEGER PRIMARY KEY AUTOINCREMENT,time TEXT,action TEXT,phone TEXT,username TEXT)","CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY,v TEXT)"]
 if USE_PG: ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
 for s in ss: qexec(s)
 if not qone("SELECT * FROM settings WHERE k='allow_edit'"): qexec("INSERT INTO settings(k,v) VALUES('allow_edit','1')")
 if not qone("SELECT * FROM settings WHERE k='allow_del'"): qexec("INSERT INTO settings(k,v) VALUES('allow_del','1')")
 if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)): qexec("INSERT INTO users(phone,password,role,username,active) VALUES(?,?,?,?,1)",('05344851045',generate_password_hash('admin2024'),'manager','admin'))
init()
def get_set(k):
 r=qone("SELECT * FROM settings WHERE k=?",(k,));return r['v'] if r else '1'
def add_log(a):
 ph=session.get('phone','system');u=qone("SELECT username FROM users WHERE phone=?",(ph,));un=u['username'] if u else ph
 qexec("INSERT INTO activity_log(time,action,phone,username) VALUES(?,?,?,?)",(datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),a,ph,un))
def login_required(f):
 @wraps(f)
 def w(*a,**kw):
  if not session.get('phone'): return redirect('/login')
  return f(*a,**kw)
 return w
def manager_required(f):
 @wraps(f)
 def w(*a,**kw):
  if not session.get('phone'): return redirect('/login')
  m=qone("SELECT * FROM users WHERE phone=?",(session.get('phone'),))
  if not m or m['role']=='tech': return "ممنوع",403
  return f(*a,**kw)
 return w
def me(): return qone("SELECT * FROM users WHERE phone=?",(session.get('phone'),))
def can_edit():
 m=me()
 return False if not m or m['role']=='tech' else get_set('allow_edit')=='1'
def can_del():
 m=me()
 return False if not m or m['role']=='tech' else get_set('allow_del')=='1'
def cur_theme(): return session.get('theme','dark')
def cur_lang(): return session.get('lang','ar')
T={'ar':{'home':'الرئيسية','dishes':'الصحون','towers':'الأبراج','subs':'المشتركين','ledger':'دفتر الحسابات','map':'الخريطة','logs':'السجل','support':'الدعم','settings':'الإعدادات','logout':'خروج','search':'بحث...','add':'اضافة'},'en':{'home':'Home','dishes':'Dishes','towers':'Towers','subs':'Subs','ledger':'Ledger','map':'Map','logs':'Logs','support':'Support','settings':'Settings','logout':'Logout','search':'Search...','add':'Add'}}
def L(k): return T[cur_lang()].get(k,k)
def do_ping(ip):
 try:
  p='-n' if platform.system().lower()=='windows' else '-c'
  o=subprocess.run(['ping',p,'1','-W','1',ip],capture_output=True,text=True,timeout=4)
  return o.returncode==0,(o.stdout+o.stderr)[:250]
 except Exception as e: return False,str(e)[:200]
@app.route('/api/ping')
@login_required
def api_ping():
 ip=request.args.get('ip','').strip();ok,txt=do_ping(ip)
 return jsonify(ok=ok,out=('متصل ✅ ' if ok else 'غير متصل ❌ ')+txt[:180])

def page_content(v):
 ce=can_edit();cd=can_del()
 if v=='home':
  ns=(qone("SELECT COUNT(*) AS c FROM subs") or {}).get('c',0);nd=(qone("SELECT COUNT(*) AS c FROM dish_ips") or {}).get('c',0);nt=(qone("SELECT COUNT(*) AS c FROM towers") or {}).get('c',0)
  return f"<div style='max-width:700px;margin:0 auto;text-align:center'><div style='font-size:28px'>{logo_html()}</div><div class=card><input id=hs placeholder='🔍 {L('search')}' oninput='hSrch(this.value)' style='max-width:400px;margin:0 auto'><div id=hr></div></div><div style='display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px'><div class=card onclick=\"loadPage('subs')\" style='cursor:pointer'><h3>👥 {L('subs')}</h3><h2>{ns}</h2></div><div class=card onclick=\"loadPage('dishes')\" style='cursor:pointer'><h3>📡 {L('dishes')}</h3><h2>{nd}</h2></div><div class=card onclick=\"loadPage('towers')\" style='cursor:pointer'><h3>🗼 {L('towers')}</h3><h2>{nt}</h2></div><div class=card onclick=\"loadPage('map')\" style='cursor:pointer'><h3>🗺 {L('map')}</h3><h2>📍</h2></div></div></div><script>async function hSrch(q){{if(!q){{document.getElementById('hr').innerHTML='';return}}let r=await fetch('/api/search?q='+encodeURIComponent(q));let d=await r.json();document.getElementById('hr').innerHTML=d.slice(0,5).map(x=>'<div class=card>'+x.dish_name+' - '+x.ip+'</div>').join('')}}</script>"
 if v=='dishes':
  return f"""<div style='max-width:900px;margin:0 auto'><div class=card style='text-align:center'><h3>📡 {L('dishes')}</h3><form id=df style='display:flex;gap:6px;flex-wrap:wrap;justify-content:center'><input name=dish_name required placeholder='اسم' style='max-width:150px'><input name=ip required placeholder='IP' style='max-width:150px'><input name=location placeholder='موقع' style='max-width:150px'><button class=btn-gold type=submit>{L('add')}</button></form></div><div id=dl style='display:grid;grid-template-columns:1fr 1fr;gap:10px'></div><div style='text-align:center'><button class=btn onclick='mD()'>المزيد</button></div><script>
let pg=0;
async function lD(){{let r=await fetch('/api/search?page='+pg);let d=await r.json();let h='';d.forEach(x=>{{
let eb="";let db="";
if("{str(ce)}"=="True") eb='<button class="icon-btn" style="background:#FF9800" data-edit="'+x.id+'">✏️</button>';
if("{str(cd)}"=="True") db='<button class="icon-btn" style="background:#F44336" data-del="'+x.id+'">🗑️</button>';
h+='<div class=card style="display:flex;justify-content:space-between;align-items:center"><div><b>'+x.dish_name+'</b><br><span class=ip-badge>'+x.ip+'</span><br><small>'+(x.location||'')+'</small></div><div style="display:flex;gap:6px;flex-direction:column">'+eb+db+'<button class=btn-blue data-ping="'+x.ip+'">بينغ</button></div></div>'}});
let el=document.getElementById('dl');if(pg==0)el.innerHTML=h;else el.innerHTML+=h;
el.querySelectorAll('[data-edit]').forEach(b=>b.onclick=()=>eD(b.getAttribute('data-edit')));
el.querySelectorAll('[data-del]').forEach(b=>b.onclick=()=>delItem('/del_dish/'+b.getAttribute('data-del')));
el.querySelectorAll('[data-ping]').forEach(b=>b.onclick=()=>pingDish(b.getAttribute('data-ping')));
}}
function mD(){{pg++;lD()}}lD();
document.getElementById('df').onsubmit=async e=>{{e.preventDefault();let r=await fetch('/add_dish',{{method:'POST',body:new FormData(e.target)}});if(r.ok){{toast('تم ✅');e.target.reset();pg=0;lD()}}else toast(await r.text())}};
async function eD(id){{let n=prompt('اسم جديد:');if(n==null)return;await fetch('/edit_dish/'+id,{{method:'POST',body:new URLSearchParams({{dish_name:n}})}});pg=0;lD();toast('تم')}}
</script></div>"""
 if v=='towers':
  rs=qall("SELECT * FROM towers ORDER BY id DESC LIMIT 50");cards=""
  for r in rs:
   eb=f"<button class=icon-btn style='background:#FF9800' data-et='{r['id']}'>✏️</button>" if ce else "";db=f"<button class=icon-btn style='background:#F44336' data-dt='{r['id']}'>🗑️</button>" if cd else ""
   cards+=f"<div class=card style='display:flex;justify-content:space-between;align-items:center'><div><b>🗼 {esc(r['name'])}</b><br><small>{esc(r['area'] or '')}</small></div><div style='display:flex;gap:6px'>{eb}{db}</div></div>"
  return f"<div style='max-width:900px;margin:0 auto'><div class=card style='text-align:center'><h3>🗼 {L('towers')}</h3><form data-ajax method=post action=/add_tower><input name=name required placeholder='اسم'><input name=area placeholder='منطقة'><button class=btn-gold>{L('add')}</button></form></div><div id=twl style='display:grid;grid-template-columns:1fr 1fr;gap:10px'>{cards}</div><script>document.querySelectorAll('[data-et]').forEach(b=>b.onclick=async()=>{{let n=prompt('اسم:');if(!n)return;await fetch('/edit_tower/'+b.getAttribute('data-et'),{{method:'POST',body:new URLSearchParams({{name:n}})}});loadPage('towers',true)}});document.querySelectorAll('[data-dt]').forEach(b=>b.onclick=()=>delItem('/del_tower/'+b.getAttribute('data-dt')));</script></div>"
 if v=='subs':
  rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 50");rows=""
  for r in rs:
   eb=f"<button class=icon-btn style='background:#FF9800' data-es='{r['id']}'>✏️</button>" if ce else "";db=f"<button class=icon-btn style='background:#F44336' data-ds='{r['id']}'>🗑️</button>" if cd else ""
   rows+=f"<div class=card style='display:flex;justify-content:space-between;align-items:center'><div><b>{esc(r['name'])}</b><br><small>{esc(r['phone'] or '')}</small></div><div style='display:flex;gap:6px'>{eb}{db}</div></div>"
  return f"<div style='max-width:600px;margin:0 auto'><div class=card style='text-align:center'><h3>👥 {L('subs')}</h3><form data-ajax method=post action=/add_sub><input name=name required placeholder='الاسم'><input name=phone placeholder='هاتف'><button class=btn-gold>{L('add')}</button></form></div>{rows}<script>document.querySelectorAll('[data-es]').forEach(b=>b.onclick=async()=>{{let n=prompt('اسم:');if(!n)return;await fetch('/edit_sub/'+b.getAttribute('data-es'),{{method:'POST',body:new URLSearchParams({{name:n}})}});loadPage('subs',true)}});document.querySelectorAll('[data-ds]').forEach(b=>b.onclick=()=>delItem('/del_sub/'+b.getAttribute('data-ds')));</script></div>"
 if v=='ledger':
  rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 50");rows=""
  for r in rs:
   eb=f"<button class=icon-btn style='background:#FF9800' data-el='{r['id']}'>✏️</button>" if ce else "";db=f"<button class=icon-btn style='background:#F44336' data-dl='{r['id']}'>🗑️</button>" if cd else ""
   rows+=f"<div class=card style='display:flex;justify-content:space-between'><div><b>{esc(r['name'])}</b> - {r['amount']} {esc(r['currency'] or '')}<br><small>{esc(r['note'] or '')}</small></div><div style='display:flex;gap:6px'>{eb}{db}</div></div>"
  return f"<div style='max-width:600px;margin:0 auto'><div class=card style='text-align:center'><h3>📒 {L('ledger')}</h3><form data-ajax method=post action=/add_ledger><input name=name required placeholder='الاسم'><input name=note placeholder='ملاحظة'><input name=amount type=number step=0.01 required placeholder='مبلغ'><select name=currency><option>USD $</option><option>SYP ل.س</option></select><button class=btn-gold>{L('add')}</button></form></div>{rows}<script>document.querySelectorAll('[data-el]').forEach(b=>b.onclick=async()=>{{let a=prompt('مبلغ:');if(!a)return;await fetch('/edit_ledger/'+b.getAttribute('data-el'),{{method:'POST',body:new URLSearchParams({{amount:a}})}});loadPage('ledger',true)}});document.querySelectorAll('[data-dl]').forEach(b=>b.onclick=()=>delItem('/del_ledger/'+b.getAttribute('data-dl')));</script></div>"
 if v=='map':
  tw=qall("SELECT * FROM towers");tj=json.dumps([{"name":t['name'],"lat":float(t.get('lat') or 35.1318),"lng":float(t.get('lng') or 36.7578)} for t in tw],ensure_ascii=False)
  return "<div class=card><div style='margin-bottom:6px'><small>كليك يمين: تثبيت نقطة أولى ثم ثانية لقياس المسافة</small> <button class=btn-blue onclick='clearMeasure()'>مسح القياس</button></div><div id=map style='height:70vh;border-radius:12px'></div><script>var _t="+tj+";var map=L.map('map').setView([35.1318,36.7578],16);L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{maxZoom:19,maxNativeZoom:19}).addTo(map);L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,opacity:0.35}).addTo(map);setTimeout(()=>map.invalidateSize(),300);_t.forEach(t=>L.marker([t.lat,t.lng]).addTo(map).bindPopup(t.name));var pts=[];var line=null;map.on('contextmenu',e=>{pts.push(e.latlng);L.marker(e.latlng).addTo(map);if(pts.length==2){if(line)map.removeLayer(line);line=L.polyline(pts,{color:'cyan'}).addTo(map);var d=map.distance(pts[0],pts[1]);toast('المسافة: '+d.toFixed(1)+' متر');pts=[]}});window.clearMeasure=()=>{pts=[];if(line){map.removeLayer(line);line=null}toast('تم المسح')};map.on('contextmenu',async e=>{if(e.originalEvent.shiftKey){let n=prompt('اسم البرج:');if(!n)return;await fetch('/add_tower',{method:'POST',body:new URLSearchParams({name:n,lat:e.latlng.lat,lng:e.latlng.lng})});toast('تم')}});</script></div>"
 if v=='logs':
  rs=qall("SELECT * FROM activity_log ORDER BY id DESC LIMIT 50");rows="".join([f"<div class=log-row><b>{esc(r['username'] or '')}</b> - {esc(r['action'])} <small>{esc(r['time'])}</small></div>" for r in rs])
  return f"<div style='max-width:650px;margin:0 auto'><div class=card><h3>📜 {L('logs')}</h3>{rows}</div></div>"
 if v=='support':
  return "<div style='max-width:500px;margin:20px auto'><div class=card style='text-align:center'><h3>🛠 الدعم الفني</h3><a href='https://wa.me/905344851045' target=_blank class=support-btn style='background:#25D366'>💬 واتساب</a> <a href='https://instagram.com/af_20_1999' target=_blank class=support-btn style='background:linear-gradient(45deg,#E1306C,#F77737)'>📸 انستغرام</a></div></div>"
 if v=='settings':
  ae=get_set('allow_edit');ad=get_set('allow_del');us=qall("SELECT * FROM users");uh=""
  for u in us:
   rl='فني' if u['role']=='tech' else 'مدير'
   uh+=f"<div class=card style='display:flex;justify-content:space-between;align-items:center'><div><b>{esc(u['username'])}</b><br><small>{esc(u['phone'])}</small> - {rl}</div><div style='display:flex;gap:6px'><button class=icon-btn style='background:#FF9800' data-eu=\"{esc(u['phone'])}\">✏️</button><button class=icon-btn style='background:#F44336' data-du=\"{esc(u['phone'])}\">🗑️</button></div></div>"
  return f"<div style='max-width:600px;margin:0 auto'><div class=card style='text-align:center'><h3>⚙ {L('settings')}</h3><label>تعديل <input type=checkbox {'checked' if ae=='1' else ''} onchange=\"fetch('/set/allow_edit/'+(this.checked?'1':'0')).then(()=>toast('تم'))\"></label><br><label>حذف <input type=checkbox {'checked' if ad=='1' else ''} onchange=\"fetch('/set/allow_del/'+(this.checked?'1':'0')).then(()=>toast('تم'))\"></label><br><form data-ajax method=post action=/change_pass style='margin-top:8px'><input name=newpass type=password required placeholder='جديدة'><button class=btn-gold>تغيير</button></form></div><div class=card style='text-align:center'><h3>اضافة مستخدم</h3><form data-ajax method=post action=/add_user><input name=phone required placeholder='يوزر'><input name=password type=password required placeholder='كلمة السر'><select name=role><option value=tech>فني</option><option value=manager>مدير</option></select><button class=btn-gold>اضافة</button></form></div>{uh}<script>document.querySelectorAll('[data-eu]').forEach(b=>b.onclick=async()=>{{let r=prompt('tech/manager:');if(!r)return;await fetch('/edit_user/'+b.getAttribute('data-eu'),{{method:'POST',body:new URLSearchParams({{role:r}})}});loadPage('settings',true)}});document.querySelectorAll('[data-du]').forEach(b=>b.onclick=()=>delItem('/del_user/'+b.getAttribute('data-du')));</script></div>"
 return "ok"

def layout(c,v='home'):
 th=cur_theme();bg=COLORS.get('bg_dark' if th=='dark' else 'bg_light','#0a1938');card=COLORS.get('card_dark','#222');gold=COLORS.get('gold','#ffbe4d');lg=logo_html();lang=cur_lang();t=T[lang]
 tmpl="""<html dir=__DIR__><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no'><link rel='stylesheet' href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'><style>*{box-sizing:border-box;font-family:sans-serif;-webkit-tap-highlight-color:transparent}body{margin:0;background:__BG__;color:#fff;overscroll-behavior-y:contain}body.light{background:#f5f5f5;color:#111}.sidebar{position:fixed;right:-285px;top:0;width:275px;height:100%;background:rgba(17,24,39,0.82);z-index:1000;padding-top:70px;transition:right.35s cubic-bezier(.4,0,.2,1);backdrop-filter:blur(18px) saturate(1.4);-webkit-backdrop-filter:blur(18px) saturate(1.4);border-left:1px solid #ffffff18;box-shadow:-15px 0 50px #0008}.sidebar.active{right:0}.sidebar a{display:flex;gap:12px;padding:14px 18px;color:#fff;text-decoration:none;border-radius:14px;margin:5px 10px;transition:.2s}.sidebar a:hover{background:#ffffff1f;transform:translateX(-4px)}.overlay{position:fixed;inset:0;background:#0006;display:none;z-index:999;backdrop-filter:blur(3px)}.overlay.active{display:block}.top{position:fixed;top:0;left:0;right:0;height:62px;background:rgba(17,24,39,0.85);display:flex;align-items:center;justify-content:space-between;padding:0 12px;z-index:101;backdrop-filter:blur(16px)}.main{margin-top:62px;padding:10px;animation:fd.22s ease-out}@keyframes fd{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}.card{background:__CARD__;padding:14px;border-radius:18px;margin-bottom:10px;border:1px solid #ffffff12;will-change:transform}input,select{width:100%;padding:11px;margin:5px 0;background:#0f1424;border:1px solid #ffffff20;color:#fff;border-radius:12px}.btn-gold{background:__GOLD__;color:#000;padding:11px 18px;border:0;border-radius:12px;font-weight:bold;cursor:pointer}.btn-blue{background:#2196F3;color:#fff;padding:9px 14px;border:0;border-radius:10px;cursor:pointer}.btn{background:#333;color:#fff;padding:9px 14px;border:0;border-radius:10px;cursor:pointer}.icon-btn{width:38px;height:38px;border:0;border-radius:12px;cursor:pointer}.ip-badge{background:#000;color:__GOLD__;padding:4px 10px;border-radius:20px;font-family:monospace}#toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#1f2937ee;padding:12px 22px;border-radius:30px;display:none;z-index:9999;backdrop-filter:blur(10px)}.support-btn{display:inline-flex;gap:8px;color:#fff;padding:13px 26px;border-radius:30px;text-decoration:none;margin:6px;font-weight:bold}.top-left{display:flex;gap:8px}.top-btn{background:#ffffff15;border:0;color:#fff;padding:8px 12px;border-radius:20px;cursor:pointer}#ptr{position:fixed;top:0;left:50%;transform:translateX(-50%) translateY(-60px);background:#2196F3;color:#fff;padding:8px 18px;border-radius:0 0 16px 16px;transition:.3s;z-index:2000}</style></head><body><div id=ptr>↻ اسحب للتحديث</div><div id=toast></div><div class=overlay id=ov onclick="tgM(false)"></div><div class=sidebar id=sb><a href="javascript:loadPage('home')">🏠 __HOME__</a><a href="javascript:loadPage('dishes')">📡 __DISHES__</a><a href="javascript:loadPage('towers')">🗼 __TOWERS__</a><a href="javascript:loadPage('subs')">👥 __SUBS__</a><a href="javascript:loadPage('ledger')">📒 __LEDGER__</a><a href="javascript:loadPage('map')">🗺 __MAP__</a><a href="javascript:loadPage('logs')">📜 __LOGS__</a><a href="javascript:loadPage('support')">💬 __SUPPORT__</a><a href="javascript:loadPage('settings')">⚙️ __SETTINGS__</a><a href=/logout>🚪 __LOGOUT__</a></div><div class=top><div style='font-size:24px;cursor:pointer' onclick="tgM()">☰</div><div>__LOGO__</div><div class=top-left><button class=top-btn onclick="tL()">🌐 __LANG__</button><button class=top-btn onclick="tT()">🌓</button></div></div><div class=main id=mn>__CONTENT__</div><script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script><script>let cur='__V__';let cache={};function tgM(f){let sb=document.getElementById('sb');let ov=document.getElementById('ov');let o=f!==undefined?f:!sb.classList.contains('active');sb.classList.toggle('active',o);ov.classList.toggle('active',o)}function toast(m){let t=document.getElementById('toast');t.textContent=m;t.style.display='block';clearTimeout(t._h);t._h=setTimeout(()=>t.style.display='none',2200)}async function loadPage(v,f){cur=v;tgM(false);let mn=document.getElementById('mn');if(cache[v]&&!f){mn.innerHTML=cache[v];ex();return}mn.style.opacity='0.6';mn.style.transform='translateY(4px)';let r=await fetch('/api/page?v='+v);let h=await r.text();cache[v]=h;mn.innerHTML=h;mn.style.opacity='1';mn.style.transform='none';ex()}function ex(){document.getElementById('mn').querySelectorAll('script').forEach(s=>{try{eval(s.textContent)}catch(e){}});bd()}function bd(){document.querySelectorAll('form[data-ajax]').forEach(f=>{if(f._b)return;f._b=1;f.onsubmit=async e=>{e.preventDefault();await fetch(f.action,{method:'POST',body:new FormData(f)});for(let k in cache)delete cache[k];toast('تم ✅');loadPage(cur,true)}})}window.delItem=async function(u){if(!confirm('حذف؟'))return;await fetch(u);for(let k in cache)delete cache[k];toast('انحذف');loadPage(cur,true)};window.pingDish=async function(ip){toast('بينغ '+ip+'...');let r=await fetch('/api/ping?ip='+encodeURIComponent(ip));let j=await r.json();toast(j.out.slice(0,150))};window.tT=async()=>{await fetch('/toggle_theme');document.body.classList.toggle('light');toast('تم')};window.tL=async()=>{await fetch('/toggle_lang');location.reload()};let _sy=0;window.addEventListener('touchstart',e=>{_sy=e.touches[0].clientY},{passive:true});window.addEventListener('touchmove',e=>{let y=e.touches[0].clientY;let ptr=document.getElementById('ptr');if(window.scrollY==0&&y-_sy>80){ptr.style.transform='translateX(-50%) translateY(0)'}},{passive:true});window.addEventListener('touchend',async e=>{let ptr=document.getElementById('ptr');if(ptr.style.transform.includes('translateY(0)')){ptr.style.transform='translateX(-50%) translateY(-60px)';for(let k in cache)delete cache[k];await loadPage(cur,true);toast('تم التحديث')}},{});bd();ex();if('__THEME__'=='light')document.body.classList.add('light');</script></body></html>"""
 tmpl=tmpl.replace("__BG__",bg).replace("__CARD__",card).replace("__GOLD__",gold).replace("__LOGO__",lg).replace("__CONTENT__",c).replace("__V__",v).replace("__DIR__",'rtl' if lang=='ar' else 'ltr').replace("__LANG__",lang.upper()).replace("__THEME__",th).replace("__HOME__",t['home']).replace("__DISHES__",t['dishes']).replace("__TOWERS__",t['towers']).replace("__SUBS__",t['subs']).replace("__LEDGER__",t['ledger']).replace("__MAP__",t['map']).replace("__LOGS__",t['logs']).replace("__SUPPORT__",t['support']).replace("__SETTINGS__",t['settings']).replace("__LOGOUT__",t['logout'])
 return tmpl
@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')
@app.route('/login',methods=['GET','POST'])
def login():
 if session.get('phone'): return redirect('/dash')
 if request.method=='POST':
  uin=request.form.get('userin','').strip();pw=request.form.get('password','')
  u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
  if u and check_password_hash(u['password'],pw): session['phone']=u['phone'];add_log("دخول");return redirect('/dash?v=home')
  return "<script>alert('خطأ');location.href='/login'</script>"
 return """<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><style>body{margin:0;min-height:100vh;background:linear-gradient(180deg,#0a0e2a,#1a1446);display:flex;flex-direction:column;align-items:center;justify-content:center;font-family:sans-serif;color:#fff}.card{background:#1e2433ee;padding:28px;border-radius:22px;width:330px;border:1px solid #ffffff15}input{width:100%;padding:13px;margin:8px 0;background:#0f1424;border:1px solid #ffffff20;color:#fff;border-radius:12px;box-sizing:border-box}.btn{width:100%;padding:14px;border:0;border-radius:14px;background:linear-gradient(90deg,#3b9dff,#8b5cf6);color:#fff;font-weight:bold;font-size:17px;margin-top:10px;cursor:pointer}</style></head><body><div style='font-size:52px'>🌐</div><div style='font-size:26px;font-weight:800;background:linear-gradient(90deg,#5aa9ff,#c084fc);-webkit-background-clip:text;-webkit-text-fill-color:transparent'>شركة أمية للإنترنت</div><div class=card><h3 style='text-align:center;color:#5aa9ff'>🔐 تسجيل الدخول</h3><form method=post><input name=userin placeholder='📱 الهاتف / المستخدم' required><input name=password type=password placeholder='🔑 كلمة السر' required><button class=btn>✨ دخول مباشر</button></form></div></body></html>"""
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
 q=request.args.get('q','').strip();pg=int(request.args.get('page',0));off=pg*20
 if q: return jsonify(qall(f"SELECT * FROM dish_ips WHERE ip LIKE? OR dish_name LIKE? ORDER BY id DESC LIMIT 20 OFFSET {off}",("%"+q+"%","%"+q+"%")))
 return jsonify(qall(f"SELECT * FROM dish_ips ORDER BY id DESC LIMIT 20 OFFSET {off}"))
@app.route('/toggle_theme')
@login_required
def tt(): session['theme']='light' if cur_theme()=='dark' else 'dark';return "ok"
@app.route('/toggle_lang')
@login_required
def tl(): session['lang']='en' if cur_lang()=='ar' else 'ar';return "ok"
@app.route('/set/<k>/<v>')
@manager_required
def setv(k,v): qexec("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v" if USE_PG else "INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)",(k,v));return "ok"
@app.route('/add_dish',methods=['POST'])
@login_required
def ad():
 ip=request.form.get('ip','').strip();nm=request.form.get('dish_name','').strip()
 if not ip or not nm: return "ناقص",400
 if qone("SELECT * FROM dish_ips WHERE ip=?",(ip,)): return "موجود",400
 qexec("INSERT INTO dish_ips(ip,location,dish_name) VALUES(?,?,?)",(ip,request.form.get('location',''),nm));add_log("اضافة "+ip);return "ok"
@app.route('/edit_dish/<int:i>',methods=['POST'])
@login_required
def ed(i):
 if not can_edit(): return "ممنوع",403
 qexec("UPDATE dish_ips SET dish_name=? WHERE id=?",(request.form.get('dish_name',''),i));return "ok"
@app.route('/del_dish/<int:i>')
@login_required
def dd(i):
 if not can_del(): return "ممنوع",403
 qexec("DELETE FROM dish_ips WHERE id=?",(i,));return "ok"
@app.route('/add_tower',methods=['POST'])
@login_required
def at(): qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",(request.form.get('name',''),request.form.get('area',''),float(request.form.get('lat') or 35.1318),float(request.form.get('lng') or 36.7578)));return "ok"
@app.route('/edit_tower/<int:i>',methods=['POST'])
@login_required
def et(i):
 if not can_edit(): return "ممنوع",403
 qexec("UPDATE towers SET name=? WHERE id=?",(request.form.get('name',''),i));return "ok"
@app.route('/del_tower/<int:i>')
@login_required
def dt(i):
 if not can_del(): return "ممنوع",403
 qexec("DELETE FROM towers WHERE id=?",(i,));return "ok"
@app.route('/add_sub',methods=['POST'])
@login_required
def asub(): qexec("INSERT INTO subs(name,phone) VALUES(?,?)",(request.form.get('name',''),request.form.get('phone','')));return "ok"
@app.route('/edit_sub/<int:i>',methods=['POST'])
@login_required
def es(i):
 if not can_edit(): return "ممنوع",403
 qexec("UPDATE subs SET name=? WHERE id=?",(request.form.get('name',''),i));return "ok"
@app.route('/del_sub/<int:i>')
@login_required
def ds(i):
 if not can_del(): return "ممنوع",403
 qexec("DELETE FROM subs WHERE id=?",(i,));return "ok"
@app.route('/add_ledger',methods=['POST'])
@login_required
def al():
 nm=request.form.get('name','').strip();amt=fnum(request.form.get('amount'))
 if qone("SELECT * FROM ledger WHERE name=? AND amount=?",(nm,amt)): return "مكرر",400
 qexec("INSERT INTO ledger(name,note,amount,currency,dt) VALUES(?,?,?,?,?)",(nm,request.form.get('note',''),amt,request.form.get('currency','USD'),datetime.datetime.now().isoformat()));return "ok"
@app.route('/edit_ledger/<int:i>',methods=['POST'])
@login_required
def el(i):
 if not can_edit(): return "ممنوع",403
 qexec("UPDATE ledger SET amount=? WHERE id=?",(fnum(request.form.get('amount')),i));return "ok"
@app.route('/del_ledger/<int:i>')
@login_required
def dl(i):
 if not can_del(): return "ممنوع",403
 qexec("DELETE FROM ledger WHERE id=?",(i,));return "ok"
@app.route('/add_user',methods=['POST'])
@manager_required
def au():
 ph=request.form.get('phone','').strip()
 if qone("SELECT * FROM users WHERE phone=?",(ph,)): return "موجود",400
 qexec("INSERT INTO users(phone,password,role,username,active) VALUES(?,?,?,?,1)",(ph,generate_password_hash(request.form.get('password','')),request.form.get('role','tech'),ph));return "ok"
@app.route('/edit_user/<ph>',methods=['POST'])
@manager_required
def eu(ph): qexec("UPDATE users SET role=? WHERE phone=?",(request.form.get('role','tech'),ph));return "ok"
@app.route('/del_user/<ph>')
@manager_required
def du(ph): qexec("DELETE FROM users WHERE phone=?",(ph,));return "ok"
@app.route('/change_pass',methods=['POST'])
@login_required
def cp(): qexec("UPDATE users SET password=? WHERE phone=?",(generate_password_hash(request.form.get('newpass','')),session.get('phone')));return "ok"
@app.route('/export_excel')
@manager_required
def ee():
 rs=qall("SELECT * FROM dish_ips");out=io.StringIO();w=csv.writer(out);w.writerow(['name','ip','location'])
 for r in rs: w.writerow([r['dish_name'],r['ip'],r['location']])
 return Response(out.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment;filename=dishes.csv'})
@app.route('/export_pdf')
@manager_required
def ep():
 rs=qall("SELECT * FROM dish_ips");h="<h1>Dishes</h1><table border=1>"+"".join([f"<tr><td>{esc(r['dish_name'])}</td><td>{esc(r['ip'])}</td></tr>" for r in rs])+"</table>";return h
if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
