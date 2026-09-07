from flask import Flask, request, redirect, session, jsonify, Response
from colors import COLORS, logo_html
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, datetime, json, html, ipaddress, io, csv, subprocess
try: import psycopg2, psycopg2.extras
except: psycopg2=None
import sqlite3
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY","omia-sec-2026-CHANGE-ME")
DATABASE_URL = os.environ.get("DATABASE_URL","").strip().replace("postgresql://","postgres://")
USE_PG = bool(DATABASE_URL.startswith("postgres://") and psycopg2)
_pg=None
def esc(s): return html.escape(str(s or ''), quote=True)
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
def init():
 ss=["CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,active INT DEFAULT 1,username TEXT)","CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT)","CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,amount REAL,note TEXT,currency TEXT,dt TEXT)","CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,dish_name TEXT)","CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,area TEXT,lat REAL,lng REAL)","CREATE TABLE IF NOT EXISTS activity_log(id INTEGER PRIMARY KEY AUTOINCREMENT,time TEXT,action TEXT,phone TEXT,username TEXT)","CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY,v TEXT)"]
 if USE_PG: ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
 for s in ss: qexec(s)
 if not qone("SELECT * FROM settings WHERE k='allow_edit'"): qexec("INSERT INTO settings(k,v) VALUES('allow_edit','1')")
 if not qone("SELECT * FROM settings WHERE k='allow_del'"): qexec("INSERT INTO settings(k,v) VALUES('allow_del','1')")
 if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)): qexec("INSERT INTO users(phone,password,role,username,active) VALUES(?,?,?,?,1)",('05344851045',generate_password_hash('admin2024'),'manager','admin'))
init()
def get_set(k): r=qone("SELECT * FROM settings WHERE k=?",(k,));return r['v'] if r else '1'
def add_log(a):
 ph=session.get('phone','system');u=qone("SELECT username FROM users WHERE phone=?",(ph,));un=u['username'] if u else ph
 qexec("INSERT INTO activity_log(time,action,phone,username) VALUES(?,?,?,?)",(datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),a,ph,un))
def login_required(f):
 @wraps(f)
 def w(*a,**kw):
  if not session.get('phone'):
   if request.path.startswith('/api/'): return jsonify(ok=False),401
   return redirect('/login')
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
def can_edit(): m=me();return m and m['role']!='tech' and get_set('allow_edit')=='1'
def can_del(): m=me();return m and m['role']!='tech' and get_set('allow_del')=='1'
def is_internal_ip(ip):
 try:o=ipaddress.ip_address(ip.strip());return o.is_private and not o.is_loopback and not o.is_multicast
 except:return False
def cur_theme(): return session.get('theme','dark')
@app.route('/api/ping')
@login_required
def api_ping():
 ip=request.args.get('ip','').strip()
 if not is_internal_ip(ip): return jsonify(ok=False,out='خارج الشبكة')
 try:
  out=subprocess.check_output(['ping','-c','1','-W','2',ip],timeout=3).decode(errors='ignore')
  ok='ttl=' in out.lower() or '1 received' in out
  return jsonify(ok=ok,out='متصل ✅' if ok else 'لا يرد ❌')
 except: return jsonify(ok=False,out='لا يرد ❌')
@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')
@app.route('/login',methods=['GET','POST'])
def login():
 if request.method=='POST':
  uin=request.form.get('userin','').strip();pw=request.form.get('password','')
  u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
  if u and check_password_hash(u['password'],pw):
   session['phone']=u['phone'];add_log("دخول")
   if request.headers.get('X-Requested-With')=='fetch': return jsonify(ok=True)
   return redirect('/dash')
  if request.headers.get('X-Requested-With')=='fetch': return jsonify(ok=False)
  return "<script>alert('خطأ');location.href='/login'</script>"
 return """<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><style>
body{margin:0;min-height:100vh;background:#0a0e2a;display:flex;flex-direction:column;align-items:center;justify-content:center;color:#fff;font-family:sans-serif}
.card{background:#1e2433;padding:25px;border-radius:20px;width:320px}input{width:100%;padding:12px;margin:8px 0;background:#0f1424;border:1px solid #333;color:#fff;border-radius:12px;box-sizing:border-box}
.btn{width:100%;padding:13px;border:0;border-radius:12px;background:#ffbe4d;font-weight:800}
#loader{display:none;position:fixed;inset:0;background:#000d;z-index:9999;align-items:center;justify-content:center;flex-direction:column}.spin{width:50px;height:50px;border:5px solid #333;border-top:5px solid #ffbe4d;border-radius:50%;animation:sp 1s linear infinite}@keyframes sp{to{transform:rotate(360deg)}}
</style></head><body><div id=loader><div class=spin></div><div>جاري تحميل الموقع كلو...</div></div>
<div style='font-size:28px;font-weight:800'>OMAIA ISP</div>
<div class=card><form id=lf><input name=userin id=uin placeholder='يوزر' required><input name=password id=pw type=password placeholder='كلمة السر' required><button class=btn>دخول</button><div id=err style='color:#f88'></div></form></div>
<a href='https://wa.me/905344851045' target=_blank style='margin-top:12px;background:#25D366;color:#fff;padding:12px 20px;border-radius:30px;text-decoration:none;display:inline-flex;gap:8px;align-items:center'><svg viewBox="0 0 24 24" width="22" height="22" fill="white"><path d="M12 2a10 10 0 00-8.6 15.1L2 22l5.1-1.3A10 10 0 1012 2zm5.5 14.1c-.2.7-1.4 1.3-2 1.4-.5.1-1.1.1-1.8-.1-.5-.1-1-.3-1.7-.6-3-1.3-4.9-4.3-5.1-4.5-.1-.2-1.2-1.6-1.2-3.1 0-1.5.8-2.2 1-2.5.3-.3.6-.4.8-.4h.6c.2 0.4 0.6.5.3.6.9 2.1 1 2.2.1.2.1.3 0.5-.1.2-.1.2-.3.5-.1.2-.3.4-.4.5-.2.2-.3.3-.1.6.2.3.8 1.3 1.6 2 1.2 1 2.1 1.4 2.4 1.5.3.2.5.1.7-.1.2-.2.7-.9.9-1.1.2-.3.5-.3.7-.2.3.2.3.2.6.4.3.1.5.2.6.3.1.2.1.7-.2 1.4z"/></svg> الدعم الفني</a>
<script>document.getElementById('lf').onsubmit=async e=>{e.preventDefault();document.getElementById('loader').style.display='flex';let r=await fetch('/login',{method:'POST',headers:{'X-Requested-With':'fetch'},body:new FormData(e.target)});let j=await r.json();if(j.ok)location.href='/dash';else{document.getElementById('loader').style.display='none';document.getElementById('err').textContent='خطأ'}};</script></body></html>"""
@app.route('/logout')
def lo(): session.clear();return redirect('/login')
@app.route('/dash')
@login_required
def dash():
 v=request.args.get('v','home')
 return layout(page_content(v),v)
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
def tl(): session['lang']='en' if session.get('lang','ar')=='ar' else 'ar';return "ok"
@app.route('/set/<k>/<v>')
@manager_required
def setv(k,v): qexec("INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)",(k,v));return "ok"
@app.route('/add_dish',methods=['POST'])
@login_required
def ad():
 ip=request.form.get('ip','').strip()
 if not is_internal_ip(ip): return "IP غير داخلي",400
 qexec("INSERT INTO dish_ips(ip,location,dish_name) VALUES(?,?,?)",(ip,request.form.get('location',''),request.form.get('dish_name','')));add_log("اضافة صحن");return "ok"
@app.route('/edit_dish/<int:i>',methods=['POST'])
@login_required
def ed(i):
 if not can_edit(): return "ممنوع",403
 qexec("UPDATE dish_ips SET dish_name=?,ip=?,location=? WHERE id=?",(request.form.get('dish_name',''),request.form.get('ip',''),request.form.get('location',''),i));return "ok"
@app.route('/del_dish/<int:i>')
@login_required
def dd(i):
 if not can_del(): return "ممنوع",403
 qexec("DELETE FROM dish_ips WHERE id=?",(i,));return "ok"
@app.route('/add_tower',methods=['POST'])
@login_required
def at(): qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",(request.form.get('name',''),request.form.get('area',''),35.13,36.75));return "ok"
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
@app.route('/add_ledger',methods=['POST'])
@login_required
def al(): qexec("INSERT INTO ledger(name,amount,note,currency,dt) VALUES(?,?,?,?,?)",(request.form.get('name',''),fnum(request.form.get('amount')),request.form.get('note',''),request.form.get('currency','USD'),datetime.datetime.now().isoformat()));return "ok"
@app.route('/del_ledger/<int:i>')
@login_required
def dll(i):
 if not can_del(): return "ممنوع",403
 qexec("DELETE FROM ledger WHERE id=?",(i,));return "ok"
@app.route('/add_user',methods=['POST'])
@manager_required
def au():
 ph=request.form.get('phone','').strip()
 if qone("SELECT * FROM users WHERE phone=?",(ph,)): return "موجود",400
 qexec("INSERT INTO users(phone,password,role,username,active) VALUES(?,?,?,?,1)",(ph,generate_password_hash(request.form.get('password','')),request.form.get('role','tech'),request.form.get('username',ph)));return "ok"
@app.route('/edit_user/<ph>',methods=['POST'])
@manager_required
def eu(ph): qexec("UPDATE users SET role=?,username=? WHERE phone=?",(request.form.get('role','tech'),request.form.get('username',ph),ph));return "ok"
@app.route('/del_user/<ph>')
@manager_required
def du(ph):
 if ph=='05344851045': return "ممنوع",403
 qexec("DELETE FROM users WHERE phone=?",(ph,));return "ok"
@app.route('/change_pass',methods=['POST'])
@login_required
def cp(): qexec("UPDATE users SET password=? WHERE phone=?",(generate_password_hash(request.form.get('newpass','')),session.get('phone')));return "ok"

def page_content(v):
 ce=can_edit();cd=can_del()
 if v=='home':
  ns=(qone("SELECT COUNT(*) c FROM subs") or {}).get('c',0);nd=(qone("SELECT COUNT(*) c FROM dish_ips") or {}).get('c',0);nt=(qone("SELECT COUNT(*) c FROM towers") or {}).get('c',0)
  return f"<div style='max-width:700px;margin:0 auto;text-align:center'><h2>{logo_html()}</h2><div style='display:grid;grid-template-columns:1fr 1fr;gap:12px'><div class=card onclick=\"saveAndLoad('subs')\" style='cursor:pointer'><h3>المشتركين</h3><h2>{ns}</h2></div><div class=card onclick=\"saveAndLoad('dishes')\" style='cursor:pointer'><h3>الصحون</h3><h2>{nd}</h2></div><div class=card onclick=\"saveAndLoad('towers')\" style='cursor:pointer'><h3>الأبراج</h3><h2>{nt}</h2></div><div class=card onclick=\"saveAndLoad('map')\" style='cursor:pointer'><h3>الخريطة</h3><h2>📍</h2></div></div></div>"
 if v=='dishes':
  return f"""<div style='max-width:900px;margin:0 auto'><div class=card style='text-align:center'><h3>الصحون</h3><input id=searchBox placeholder='بحث' oninput="pg=0;loadD(this.value)" style='max-width:400px;margin:0 auto'><form data-ajax method=post action=/add_dish style='display:flex;gap:6px;flex-wrap:wrap;justify-content:center'><input name=dish_name required placeholder='اسم' style='flex:1'><input name=ip required placeholder='IP' style='flex:1'><input name=location placeholder='موقع' style='flex:1'><button class=btn-gold>اضافة</button></form></div><div id=dishList></div><div style='text-align:center'><button class=btn onclick='pg++;loadD(document.getElementById("searchBox").value)'>المزيد</button></div><script>let pg=0;async function loadD(q=""){{let r=await fetch('/api/search?q='+encodeURIComponent(q)+'&page='+pg);let d=await r.json();let h="";d.forEach(x=>{{h+=`<div class=card style="display:flex;justify-content:space-between;align-items:center"><div><b>${{x.dish_name}}</b> <a href="http://${{x.ip}}" target=_blank>${{x.ip}}</a><br><small>${{x.location||''}}</small><br><button onclick="p1('${{x.ip}}',this)">بينغ</button> <span></span></div><div>`+('{"1" if ce else "0"}'=="1"?`<button onclick='eD(${{x.id}},"${{(x.dish_name||'').replace(/"/g,'')}}","${{x.ip}}")'>تعديل</button>`:'')+('{"1" if cd else "0"}'=="1"?`<button onclick='delItem("/del_dish/${{x.id}}")'>حذف</button>`:'')+`</div></div>`}});document.getElementById('dishList').innerHTML=pg==0?h:document.getElementById('dishList').innerHTML+h}}async function p1(ip,b){{let s=b.nextElementSibling;s.textContent='...';let r=await fetch('/api/ping?ip='+ip);let j=await r.json();s.textContent=j.out}}function eD(id,n,ip){{let nn=prompt('اسم:',n);if(nn==null)return;let ii=prompt('IP:',ip);if(ii==null)return;fetch('/edit_dish/'+id,{{method:'POST',body:new URLSearchParams({{dish_name:nn,ip:ii}})}}).then(()=>loadPage('dishes',true))}}loadD();</script></div>"""
 if v=='ledger':
  rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 50")
  rows="".join([f"<div class=card style='display:flex;justify-content:space-between'><div><b>{esc(r['name'])}</b> {r['amount']} {esc(r['currency'] or '')}<br><small>{esc(r['note'] or '')}</small></div><button onclick='delItem(\"/del_ledger/{r['id']}\")'>حذف</button></div>" for r in rs])
  return f"""<div style='max-width:600px;margin:0 auto'><div class=card style='text-align:center'><h3>دفتر حسابات</h3><form data-ajax method=post action=/add_ledger style='display:flex;gap:6px;flex-wrap:wrap'><input name=name required placeholder='الاسم'><input name=amount type=number step=0.01 required placeholder='مبلغ'><input name=note placeholder='ملاحظة'><select name=currency><option value=USD>دولار</option><option value=SYP>سوري</option></select><button class=btn-gold>اضافة</button></form></div>{rows}</div>"""
 if v=='map':
  tj=json.dumps([{"name":t['name'],"lat":float(t.get('lat') or 35.13),"lng":float(t.get('lng') or 36.75)} for t in qall("SELECT * FROM towers")],ensure_ascii=False)
  return f"""<div class=card><button id=mb onclick='tm()'>قياس مسافة</button><button onclick='cm()'>مسح</button><span id=mo></span><div id=map style='height:65vh'></div><script>var _t={tj};var map=L.map('map').setView([35.13,36.75],13);L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',{{maxZoom:19}}).addTo(map);setTimeout(()=>map.invalidateSize(),400);_t.forEach(t=>L.marker([t.lat,t.lng],{{draggable:true}}).addTo(map).bindPopup(t.name));let ms=false,pts=[],ln=null,mks=[];window.tm=function(){{ms=!ms;document.getElementById('mb').textContent=ms?'اضغط...':'قياس مسافة'}};window.cm=function(){{pts=[];mks.forEach(m=>map.removeLayer(m));mks=[];if(ln)map.removeLayer(ln);document.getElementById('mo').textContent=''}};map.on('click',e=>{{if(!ms)return;pts.push(e.latlng);let mk=L.marker(e.latlng,{{draggable:true}}).addTo(map);mk.on('dragend',()=>{{pts[mks.indexOf(mk)]=mk.getLatLng();up()}});mks.push(mk);up()}});function up(){{if(ln)map.removeLayer(ln);ln=L.polyline(pts,{{color:'red'}}).addTo(map);let t=0;for(let i=1;i<pts.length;i++)t+=map.distance(pts[i-1],pts[i]);document.getElementById('mo').textContent=t.toFixed(2)+' م'}};</script></div>"""
 if v=='support':
  return f"""<div style='max-width:500px;margin:20px auto'><div class=card style='text-align:center'><h2>{logo_html()}</h2>
  <a href='https://wa.me/905344851045' target=_blank style='background:{COLORS['green']};padding:14px;border-radius:50%;display:inline-flex;margin:6px'><svg viewBox="0 0 24 24" width="28" height="28" fill="white"><path d="M12 2a10 10 0 00-8.6 15.1L2 22l5.1-1.3A10 10 0 1012 2z"/></svg></a>
  <a href='https://instagram.com/af_20_1999' target=_blank style='background:{COLORS['pink']};padding:14px;border-radius:50%;display:inline-flex;margin:6px'><svg viewBox="0 0 24 24" width="28" height="28" fill="white"><path d="M12 2.2c3.2 0 3.6 0 4.9.1 3.2.1 4.7 1.7 4.9 4.9.1 1.3.1 1.6.1 4.8s0 3.6-.1 4.8c-.2 3.2-1.7 4.8-4.9 4.9-1.3.1-1.6.1-4.9.1s-3.6 0-4.8-.1c-3.2-.2-4.8-1.7-4.9-4.9C2.2 15.6 2.2 15.2 2.2 12s0-3.6.1-4.8C2.5 4 2.4 7.2 2.3 8.4 2.2 8.8 2.2 12 2.2z"/></svg></a>
  </div></div>"""
 if v=='settings':
  ae=get_set('allow_edit');ad=get_set('allow_del');us=qall("SELECT * FROM users");uh=""
  for u in us: uh+=f"<div class=card style='text-align:center'><b>{esc(u['username'])}</b><br><input id='un_{u['phone']}' value='{esc(u['username'])}' style='max-width:140px;margin:4px auto'><select id='r_{u['phone']}'><option value=tech {'selected' if u['role']=='tech' else ''}>فني</option><option value=manager {'selected' if u['role']=='manager' else ''}>مدير</option></select><br><button onclick=\"saveU('{u['phone']}')\">حفظ</button> <button onclick=\"delU('{u['phone']}')\">حذف</button></div>"
  return f"""<div style='max-width:700px;margin:0 auto'><div class=card style='text-align:center'><h3>الإعدادات</h3><label>تعديل <input type=checkbox {'checked' if ae=='1' else ''} onchange="fetch('/set/allow_edit/'+(this.checked?'1':'0'))" style='width:auto'></label><label>حذف <input type=checkbox {'checked' if ad=='1' else ''} onchange="fetch('/set/allow_del/'+(this.checked?'1':'0'))" style='width:auto'></label><br><button onclick='toggleTheme()'>ليل/نهار</button> <button onclick='toggleLang()'>ع/EN</button><form data-ajax method=post action=/change_pass><input name=newpass type=password required placeholder='كلمة سر جديدة' style='max-width:200px;margin:0 auto'><button>تغيير</button></form></div><div class=card style='text-align:center'><form data-ajax method=post action=/add_user><input name=phone required placeholder='يوزر'><input name=username placeholder='اسم'><input name=password type=password required placeholder='باس'><select name=role><option value=tech>فني</option><option value=manager>مدير</option></select><button>اضافة</button></form></div><div style='display:grid;grid-template-columns:1fr 1fr;gap:10px'>{uh}</div><script>async function saveU(p){{await fetch('/edit_user/'+p,{{method:'POST',body:new URLSearchParams({{username:document.getElementById('un_'+p).value,role:document.getElementById('r_'+p).value}})}});toast('تم')}}async function delU(p){{if(!confirm('تأكيد؟'))return;await fetch('/del_user/'+p);loadPage('settings',true)}}</script></div>"""
 return "<div class=card>ok</div>"

def layout(c,v='home'):
 th=cur_theme();bg=COLORS['bg_dark'] if th=='dark' else COLORS['bg_light']
 return f"""<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><link rel=stylesheet href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'><style>
*{ {f"font-family:sans-serif;box-sizing:border-box"}}body{{margin:0;background:{bg};color:#fff}}.sidebar{{position:fixed;right:0;top:0;width:270px;height:100%;background:#111;z-index:1000;padding-top:70px;transform:translateX(290px);transition:.3s}}.sidebar.active{{transform:translateX(0)}}.sidebar a{{display:block;padding:12px;margin:6px 12px;color:#fff;text-decoration:none;background:#ffffff10;border-radius:12px}}.top{{position:fixed;top:0;left:0;right:0;height:62px;background:#111;display:flex;align-items:center;justify-content:space-between;padding:0 15px;z-index:1001}}.main{{margin-top:70px;padding:12px}}.card{{background:{COLORS['card_dark']};padding:16px;border-radius:16px;margin-bottom:12px}}input,select{{width:100%;padding:12px;margin:6px 0;background:#0f0f0f;border:1px solid #555;color:#fff;border-radius:12px}}.btn-gold{{background:{COLORS['gold']};padding:10px 16px;border:0;border-radius:12px;font-weight:800}}#toast{{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:{COLORS['gold']};color:#000;padding:10px 20px;border-radius:20px;display:none}}</style></head><body><div id=toast></div>
<div class=sidebar id=sb><a href="javascript:saveAndLoad('home')">🏠 الرئيسية</a><a href="javascript:saveAndLoad('dishes')">📡 الصحون</a><a href="javascript:saveAndLoad('ledger')">📒 حسابات</a><a href="javascript:saveAndLoad('map')">🗺️ الخريطة</a><a href="javascript:saveAndLoad('support')">💬 الدعم</a><a href="javascript:saveAndLoad('settings')">⚙️ الإعدادات</a><a href=/logout>🚪 خروج</a></div>
<div class=top><div onclick="document.getElementById('sb').classList.toggle('active')" style='cursor:pointer'>☰</div><div>{logo_html()}</div><div><button onclick="saveAndLoad(cur,true)">🔄</button> <button onclick='toggleLang()'>ع/EN</button></div></div>
<div class=main id=mn>{c}</div><script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script><script>
let cur='{v}';let cache={{}};try{{cur=localStorage.getItem('lastPage')||'{v}'}}catch(e){{}}
function toast(m){{let t=document.getElementById('toast');t.textContent=m;t.style.display='block';setTimeout(()=>t.style.display='none',2000)}}
function saveAndLoad(v,f){{try{{localStorage.setItem('lastPage',v)}}catch(e){{}}loadPage(v,f)}}
async function loadPage(v,f){{cur=v;try{{localStorage.setItem('lastPage',v)}}catch(e){{}}document.getElementById('sb').classList.remove('active');if(cache[v]&&!f){{document.getElementById('mn').innerHTML=cache[v];exe();return}}let r=await fetch('/api/page?v='+v);let h=await r.text();cache[v]=h;document.getElementById('mn').innerHTML=h;exe()}}
function exe(){{document.getElementById('mn').querySelectorAll('script').forEach(s=>{{try{{eval(s.textContent)}}catch(e){{}}}});bind()}}
function bind(){{document.querySelectorAll('form[data-ajax]').forEach(f=>{{f.onsubmit=async e=>{{e.preventDefault();await fetch(f.action,{{method:'POST',body:new FormData(f)}});for(let k in cache)delete cache[k];toast('تم');loadPage(cur,true)}}}})}}
window.delItem=async u=>{{if(!confirm('تأكيد الحذف؟'))return;await fetch(u);for(let k in cache)delete cache[k];toast('انحذف');loadPage(cur,true)}};
window.toggleTheme=async()=>{{await fetch('/toggle_theme');let r=await fetch('/api/page?v='+cur);let h=await r.text();cache[cur]=h;document.getElementById('mn').innerHTML=h;exe()}};
window.toggleLang=async()=>{{await fetch('/toggle_lang');loadPage(cur,true)}};
bind();exe();if(cur!='{v}')loadPage(cur,true);
</script></body></html>"""
if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
