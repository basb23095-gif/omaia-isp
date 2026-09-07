from flask import Flask, request, redirect, session, jsonify
from colors import COLORS, logo_html
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, html, ipaddress, subprocess
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
 ss=["CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,username TEXT)",
 "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,note TEXT)",
 "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,amount REAL,note TEXT,currency TEXT)",
 "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,dish_name TEXT)",
 "CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,area TEXT,lat REAL,lng REAL)"]
 if USE_PG: ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
 for s in ss: qexec(s)
 try:
  c=db()
  if not USE_PG:
   cols=[x[1] for x in c.execute("PRAGMA table_info(subs)").fetchall()]
   if 'note' not in cols: c.execute("ALTER TABLE subs ADD COLUMN note TEXT");c.commit()
   cc(c)
 except: pass
 if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)):
  qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",('05344851045',generate_password_hash('admin2024'),'manager','admin'))
init()

def login_required(f):
 @wraps(f)
 def w(*a,**kw):
  if not session.get('phone'): return redirect('/login')
  return f(*a,**kw)
 return w
def is_valid_ip(ip):
 try: ipaddress.ip_address(ip.strip());return True
 except: return False

@app.route('/api/ping')
@login_required
def api_ping():
 ip=request.args.get('ip','').strip()
 if not is_valid_ip(ip): return jsonify(ok=False,out='IP غير صالح')
 try:
  out=subprocess.check_output(['ping','-c','1','-W','2',ip],timeout=4).decode(errors='ignore')
  ok='ttl=' in out.lower()
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
   session['phone']=u['phone'];return redirect('/dash')
  return "<script>alert('خطأ بالدخول');location.href='/login'</script>"
 return """<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<style>body{margin:0;min-height:100vh;background:#0a0e2a;display:flex;flex-direction:column;align-items:center;justify-content:center;color:#fff;font-family:sans-serif}
.card{background:#1e2433;padding:25px;border-radius:20px;width:320px}input{width:100%;padding:12px;margin:8px 0;background:#0f1424;border:1px solid #333;color:#fff;border-radius:12px;box-sizing:border-box}
.btn{width:100%;padding:13px;border:0;border-radius:12px;background:#ffbe4d;font-weight:800;cursor:pointer}</style></head><body>
<div style='font-size:28px;font-weight:800;margin-bottom:15px'>OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<div class=card><form method=post><input name=userin placeholder='يوزر / رقم هاتف' required>
<input name=password type=password placeholder='كلمة السر' required><button class=btn>دخول</button></form>
<div style='text-align:center;margin-top:15px'><a href='https://wa.me/905344851045' style='color:#22c55e;text-decoration:none'>📱 واتساب الدعم الفني</a></div></div></body></html>"""

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
 if q: return jsonify(qall("SELECT * FROM dish_ips WHERE ip LIKE? OR dish_name LIKE? OR location LIKE? ORDER BY id DESC LIMIT 30",("%"+q+"%","%"+q+"%","%"+q+"%",)))
 return jsonify(qall("SELECT * FROM dish_ips ORDER BY id DESC LIMIT 30"))
@app.route('/toggle_theme')
@login_required
def tt(): session['theme']='light' if session.get('theme','dark')=='dark' else 'dark';return "ok"

@app.route('/add_dish',methods=['POST'])
@login_required
def ad():
 ip=request.form.get('ip','').strip()
 if not is_valid_ip(ip): return "IP غير صالح",400
 qexec("INSERT INTO dish_ips(ip,location,dish_name) VALUES(?,?,?)",(ip,request.form.get('location',''),request.form.get('dish_name','')));return "ok"
@app.route('/edit_dish/<int:i>',methods=['POST'])
@login_required
def ed(i): qexec("UPDATE dish_ips SET dish_name=?,ip=?,location=? WHERE id=?",(request.form.get('dish_name',''),request.form.get('ip',''),request.form.get('location',''),i));return "ok"
@app.route('/del_dish/<int:i>')
@login_required
def dd(i): qexec("DELETE FROM dish_ips WHERE id=?",(i,));return "ok"

@app.route('/add_tower',methods=['POST'])
@login_required
def at(): qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",(request.form.get('name',''),request.form.get('area',''),35.1312,36.7578));return "ok"
@app.route('/del_tower/<int:i>')
@login_required
def dt(i): qexec("DELETE FROM towers WHERE id=?",(i,));return "ok"
@app.route('/edit_tower/<int:i>',methods=['POST'])
@login_required
def et(i): qexec("UPDATE towers SET name=?,area=? WHERE id=?",(request.form.get('name',''),request.form.get('area',''),i));return "ok"

@app.route('/add_sub',methods=['POST'])
@login_required
def asub(): qexec("INSERT INTO subs(name,phone,note) VALUES(?,?,?)",(request.form.get('name',''),request.form.get('phone',''),request.form.get('note','')));return "ok"
@app.route('/del_sub/<int:i>')
@login_required
def dsub(i): qexec("DELETE FROM subs WHERE id=?",(i,));return "ok"
@app.route('/edit_sub/<int:i>',methods=['POST'])
@login_required
def esub(i): qexec("UPDATE subs SET name=?,phone=?,note=? WHERE id=?",(request.form.get('name',''),request.form.get('phone',''),request.form.get('note',''),i));return "ok"

@app.route('/add_ledger',methods=['POST'])
@login_required
def al(): qexec("INSERT INTO ledger(name,amount,note,currency) VALUES(?,?,?,?)",(request.form.get('name',''),float(request.form.get('amount') or 0),request.form.get('note',''),request.form.get('currency','USD')));return "ok"
@app.route('/del_ledger/<int:i>')
@login_required
def dll(i): qexec("DELETE FROM ledger WHERE id=?",(i,));return "ok"
@app.route('/edit_ledger/<int:i>',methods=['POST'])
@login_required
def el(i): qexec("UPDATE ledger SET name=?,amount=?,note=?,currency=? WHERE id=?",(request.form.get('name',''),float(request.form.get('amount') or 0),request.form.get('note',''),request.form.get('currency','USD'),i));return "ok"

@app.route('/add_user',methods=['POST'])
@login_required
def au():
 ph=request.form.get('phone','').strip()
 if qone("SELECT * FROM users WHERE phone=?",(ph,)): return "موجود مسبقاً",400
 qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",(ph,generate_password_hash(request.form.get('password','1234')),request.form.get('role','tech'),request.form.get('username',ph)));return "ok"
@app.route('/edit_user',methods=['POST'])
@login_required
def eu():
 old=request.form.get('old_phone','')
 qexec("UPDATE users SET phone=?,username=?,role=? WHERE phone=?",(request.form.get('phone','').strip(),request.form.get('username',''),request.form.get('role','tech'),old));return "ok"
@app.route('/del_user/<ph>')
@login_required
def du(ph):
 if ph=='05344851045': return "ممنوع حذف المدير",400
 qexec("DELETE FROM users WHERE phone=?",(ph,));return "ok"
@app.route('/change_pass',methods=['POST'])
@login_required
def cp(): qexec("UPDATE users SET password=? WHERE phone=?",(generate_password_hash(request.form.get('newpass','')),session.get('phone')));return "ok"

def page_content(v):
 if v=='home':
  ns=(qone("SELECT COUNT(*) c FROM subs") or {}).get('c',0);nd=(qone("SELECT COUNT(*) c FROM dish_ips") or {}).get('c',0);nt=(qone("SELECT COUNT(*) c FROM towers") or {}).get('c',0);nl=(qone("SELECT COUNT(*) c FROM ledger") or {}).get('c',0)
  return f"<div style='max-width:700px;margin:0 auto;text-align:center'><div style='display:grid;grid-template-columns:1fr 1fr;gap:12px'><div class='card anim icon' onclick=\"loadPage('subs')\" style='cursor:pointer'><h3>👥 المشتركين</h3><h2>{ns}</h2></div><div class='card anim icon' onclick=\"loadPage('dishes')\" style='cursor:pointer'><h3>📡 الصحون</h3><h2>{nd}</h2></div><div class='card anim icon' onclick=\"loadPage('towers')\" style='cursor:pointer'><h3>🗼 الأبراج</h3><h2>{nt}</h2></div><div class='card anim icon' onclick=\"loadPage('ledger')\" style='cursor:pointer'><h3>📒 الحسابات</h3><h2>{nl}</h2></div></div><a href='https://wa.me/905344851045' target=_blank class='wa-float'>💬</a></div>"
 if v=='dishes':
  return """<div style='max-width:900px;margin:0 auto'><div class=card><h3>📡 الصحون - إضافة</h3>
  <form data-ajax method=post action=/add_dish style='display:flex;gap:5px;flex-wrap:wrap'><input name=dish_name placeholder='اسم الصحن' required style='flex:1'><input name=ip placeholder='IP' required style='flex:1'><input name=location placeholder='موقع' style='flex:1'><button class=btn-gold>➕ إضافة</button></form></div><div id=dl></div>
  <script>async function ld(q=''){let r=await fetch('/api/search?q='+encodeURIComponent(q));let d=await r.json();let h='';d.forEach(x=>{h+=`<div class="card anim"><b>${x.dish_name}</b> - ${x.ip} <small>${x.location||''}</small><br><button class=btn-gold onclick="p1('${x.ip}',this)">📶 بنج</button> <span style='font-weight:800'></span> <button class=btn-gold onclick="editDish(${x.id},'${x.dish_name}','${x.ip}','${x.location||''}')">✏️ تعديل</button> <button class=btn-del onclick="askDel('/del_dish/${x.id}')">🗑️ حذف</button></div>`});document.getElementById('dl').innerHTML=h||'<div class=card>لا يوجد صحون</div>'}
  async function p1(ip,b){let s=b.nextElementSibling;s.textContent='⏳...';let r=await fetch('/api/ping?ip='+ip);let j=await r.json();s.textContent=j.out}
  function editDish(id,n,ip,loc){let nn=prompt('اسم:',n);if(nn==null)return;let ii=prompt('IP:',ip);if(ii==null)return;let ll=prompt('موقع:',loc);fetch('/edit_dish/'+id,{method:'POST',body:new URLSearchParams({dish_name:nn,ip:ii,location:ll||''})}).then(()=>ld())}ld();window.searchDishes=ld;</script></div>"""
 if v=='towers':
  rs=qall("SELECT * FROM towers ORDER BY id DESC");rows=""
  for r in rs: rows+=f"<div class='card anim'><b>🗼 {esc(r['name'])}</b> - 📍 {esc(r['area'])} <button class=btn-gold onclick=\"editTower({r['id']},'{esc(r['name'])}','{esc(r['area'])}')\">✏️ تعديل</button> <button class=btn-del onclick=\"askDel('/del_tower/{r['id']}')\">🗑️ حذف</button></div>"
  return f"<div style='max-width:700px;margin:0 auto'><div class=card><h3>🗼 الأبراج - إضافة</h3><form data-ajax method=post action=/add_tower><input name=name placeholder='اسم البرج' required><input name=area placeholder='الموقع / المنطقة'><button class=btn-gold>➕ إضافة</button></form></div>{rows or '<div class=card>لا يوجد أبراج</div>'}<script>function editTower(id,n,a){{let nn=prompt('اسم البرج:',n);if(nn==null)return;let aa=prompt('الموقع:',a);if(aa==null)return;fetch('/edit_tower/'+id,{{method:'POST',body:new URLSearchParams({{name:nn,area:aa}})}}).then(()=>loadPage('towers'))}}</script></div>"
 if v=='subs':
  rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 150");rows=""
  for r in rs: rows+=f"<div class='card anim'><b>👤 {esc(r['name'])}</b><br>📞 {esc(r['phone'])}<br>📝 <small>{esc(r['note'] or '')}</small><br><button class=btn-gold onclick='editSub({r['id']})'>✏️ تعديل</button> <button class=btn-del onclick=\"askDel('/del_sub/{r['id']}')\">🗑️ حذف</button></div>"
  return f"<div style='max-width:700px;margin:0 auto'><div class=card><h3>👥 المشتركين - يوزر / رقم / ملاحظة بكرت واحد</h3><form data-ajax method=post action=/add_sub><input name=name placeholder='الاسم / يوزر' required><input name=phone placeholder='رقم الهاتف'><input name=note placeholder='ملاحظة'><button class=btn-gold>➕ إضافة</button></form></div>{rows}<script>async function editSub(id){{let n=prompt('الاسم:');if(n==null)return;let p=prompt('رقم الهاتف:');if(p==null)return;let no=prompt('ملاحظة:');if(no==null)no='';fetch('/edit_sub/'+id,{{method:'POST',body:new URLSearchParams({{name:n,phone:p,note:no}})}}).then(()=>loadPage('subs'))}}</script></div>"
 if v=='ledger':
  rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 150");rows=""
  for r in rs: rows+=f"<div class='card anim'><b>{esc(r['name'])}</b> - 💰 {r['amount']} {esc(r['currency'])}<br><small>📝 {esc(r['note'])}</small><br><button class=btn-gold onclick='editL({r['id']})'>✏️ تعديل</button> <button class=btn-del onclick=\"askDel('/del_ledger/{r['id']}')\">🗑️ حذف</button></div>"
  return f"""<div style='max-width:700px;margin:0 auto'><div class=card><h3>📒 دفتر حسابات</h3>
  <form data-ajax method=post action=/add_ledger><input name=name placeholder='الاسم' required><input name=amount type=number step=0.01 placeholder='المبلغ' required><input name=note placeholder='ملاحظة'><select name=currency><option value=USD>💵 دولار</option><option value=SYP>🇸🇾 ليرة سورية</option></select><button class=btn-gold>➕ إضافة</button></form></div>{rows}
  <script>function editL(id){{let n=prompt('الاسم:');if(n==null)return;let a=prompt('المبلغ:');if(a==null)return;let no=prompt('ملاحظة:');fetch('/edit_ledger/'+id,{{method:'POST',body:new URLSearchParams({{name:n,amount:a,note:no||''}})}}).then(()=>loadPage('ledger'))}}</script></div>"""
 if v=='map':
  return """<div class=card><h3>🗺️ خريطة حماة</h3><div id=map style='height:65vh;border-radius:12px;background:#e5e7eb;z-index:1'></div>
  <script>setTimeout(()=>{var map=L.map('map').setView([35.1312,36.7578],13);L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© OpenStreetMap'}).addTo(map);setTimeout(()=>map.invalidateSize(),400);L.marker([35.1312,36.7578]).addTo(map).bindPopup('حماة').openPopup();},150);</script></div>"""
 if v=='support':
  return """<div class=card style='text-align:center;max-width:500px;margin:0 auto'><h2>🛠️ الدعم الفني</h2>
  <a href='https://wa.me/905344851045' target=_blank style='display:inline-block;background:#22c55e;color:#fff;padding:14px 24px;border-radius:12px;text-decoration:none;margin:6px;font-weight:800;font-size:17px'>💬 واتساب</a><br>
  <a href='https://instagram.com/af_20_1999' target=_blank style='display:inline-block;background:#E1306C;color:#fff;padding:12px 22px;border-radius:12px;text-decoration:none;margin:6px;font-weight:700'>📸 انستغرام</a><br>
  <a href='tel:+905344851045' style='display:inline-block;background:#0ea5e9;color:#fff;padding:12px 22px;border-radius:12px;text-decoration:none;margin:6px;font-weight:700'>📞 اتصال مباشر</a>
  <div class=card style='margin-top:16px;background:#ffffff10'><h3>🔔 الإشعارات</h3><p>لا توجد إشعارات جديدة حالياً</p></div></div>"""
 if v=='settings':
  us=qall("SELECT * FROM users ORDER BY phone DESC")
  uh="".join([f"<div class='card anim'>👤 <b>{esc(u['username'])}</b><br>📞 {esc(u['phone'])} | 🔑 {esc(u['role'])}<br><button class=btn-gold onclick=\"editU('{esc(u['phone'])}','{esc(u['username'])}','{esc(u['role'])}')\">✏️ تعديل</button> <button class=btn-del onclick=\"askDel('/del_user/{esc(u['phone'])}')\">🗑️ حذف</button></div>" for u in us])
  return f"""<div style='max-width:600px;margin:0 auto'><div class=card><h3>⚙️ الإعدادات</h3>
  <button class=btn-gold onclick="fetch('/toggle_theme').then(()=>location.reload())">🌙 تبديل ليل / نهار</button>
  <form data-ajax method=post action=/change_pass style='margin-top:10px'><input name=newpass type=password placeholder='كلمة سر جديدة لحسابي' required><button class=btn-gold>🔑 تغيير كلمة السر</button></form></div>
  <div class=card><h3>➕ إضافة مستخدم - بكرت واحد</h3><form data-ajax method=post action=/add_user><input name=username placeholder='الاسم / يوزر' required><input name=phone placeholder='رقم الهاتف' required><input name=password type=password placeholder='كلمة السر'><select name=role><option value=tech>🔧 فني</option><option value=manager>👑 مدير</option></select><button class=btn-gold>إضافة</button></form></div>{uh}
  <script>function editU(old,n,rl){{let nn=prompt('الاسم / يوزر:',n);if(nn==null)return;let pp=prompt('رقم الهاتف:',old);if(pp==null)return;fetch('/edit_user',{{method:'POST',body:new URLSearchParams({{old_phone:old,phone:pp,username:nn,role:rl}})}}).then(()=>loadPage('settings'))}}</script></div>"""
 return "<div class=card>ok</div>"

def layout(c,v='home'):
 th=session.get('theme','dark');is_dark=(th=='dark')
 bg='#0a0e2a' if is_dark else '#f1f5f9'
 card_bg='#1e2433' if is_dark else '#ffffff'
 txt='#ffffff' if is_dark else '#0f172a'
 return f"""<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<link rel=stylesheet href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'>
<style>
*{{box-sizing:border-box;font-family:system-ui,sans-serif}}body{{margin:0;background:{bg};color:{txt};-webkit-tap-highlight-color:transparent}}
@keyframes fadeUp{{from{{opacity:0;transform:translateY(22px) scale(.98)}}to{{opacity:1;transform:none}}}}
.anim{{animation:fadeUp.45s ease both}}
.icon{{transition:transform.25s}}.icon:hover{{transform:translateY(-3px)}}
.top{{position:fixed;top:0;left:0;right:0;height:60px;background:rgba(17,24,39,.82);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);color:#fff;display:flex;align-items:center;justify-content:space-between;padding:0 12px;z-index:1003;border-bottom:1px solid #ffffff1a}}
.sidebar{{position:fixed;right:0;top:0;width:285px;height:100%;background:rgba(17,24,39,.72);backdrop-filter:blur(22px) saturate(1.4);-webkit-backdrop-filter:blur(22px) saturate(1.4);color:#fff;z-index:1002;padding-top:72px;transform:translateX(110%);transition:transform.42s cubic-bezier(.32,.72,.24,1);border-left:1px solid #ffffff22;box-shadow:-10px 0 30px #0005}}
.sidebar.active{{transform:translateX(0)}}
.sidebar a{{display:flex;align-items:center;gap:12px;padding:13px 18px;margin:6px 12px;color:#fff;text-decoration:none;border-radius:14px;transition:.25s;font-weight:600;background:#ffffff08}}
.sidebar a:hover,.sidebar a:active{{background:#ffbe4d33;transform:translateX(-5px)}}
#overlay{{position:fixed;inset:0;background:#0009;backdrop-filter:blur(3px);z-index:1001;display:none;opacity:0;transition:.3s}}#overlay.show{{display:block;opacity:1}}
.main{{margin-top:70px;padding:12px;min-height:90vh}}
.card{{background:{card_bg};color:{txt};padding:14px;border-radius:16px;margin-bottom:10px;box-shadow:0 6px 18px #0004;border:1px solid #ffffff10}}
input,select{{padding:11px;margin:5px 0;border-radius:10px;border:1px solid #ffffff22;width:100%;background:#ffffff08;color:inherit}}
.btn-gold{{background:#ffbe4d;color:#111;padding:10px 16px;border:0;border-radius:10px;font-weight:800;cursor:pointer;margin:3px;transition:.2s}}
.btn-gold:active{{transform:scale(.93)}}
.btn-del{{background:#ef4444;color:#fff;padding:10px 16px;border:0;border-radius:10px;cursor:pointer;margin:3px;font-weight:700;transition:.2s}}
.btn-del:active{{transform:scale(.93)}}
.wa-float{{position:fixed;bottom:22px;left:22px;background:#22c55e;width:60px;height:60px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:30px;text-decoration:none;box-shadow:0 10px 25px #0006;z-index:999;animation:fadeUp.6s}}
.skel{{background:linear-gradient(90deg,#ffffff12 25%,#ffffff2a 50%,#ffffff12 75%);background-size:200% 100%;animation:sh 1s infinite linear;border-radius:14px;height:70px;margin-bottom:10px}}
@keyframes sh{{to{{background-position:-200% 0}}}}
#delModal{{position:fixed;inset:0;background:#0008;backdrop-filter:blur(6px);display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:.32s;z-index:2000}}
#delModal.show{{opacity:1;pointer-events:auto}}
#delBox{{background:{card_bg};color:{txt};padding:26px;border-radius:22px;width:90%;max-width:330px;text-align:center;transform:scale(.65) translateY(20px);transition:.35s cubic-bezier(.34,1.56,.64,1);box-shadow:0 25px 50px #0008}}
#delModal.show #delBox{{transform:scale(1) translateY(0)}}
</style></head>
<body><div id=overlay onclick="toggleSb(false)"></div>
<div class=sidebar id=sb>
<a href="javascript:loadPage('home')">🏠 الرئيسية</a><a href="javascript:loadPage('dishes')">📡 الصحون</a>
<a href="javascript:loadPage('towers')">🗼 الأبراج</a><a href="javascript:loadPage('subs')">👥 المشتركين</a>
<a href="javascript:loadPage('ledger')">📒 دفتر حسابات</a><a href="javascript:loadPage('map')">🗺️ الخريطة</a>
<a href="javascript:loadPage('support')">🛠️ الدعم الفني</a><a href="javascript:loadPage('settings')">⚙️ الإعدادات</a>
<a href=/logout>🚪 خروج</a></div>
<div class=top><div style='display:flex;gap:10px;align-items:center'><span onclick="toggleSb()" style='font-size:26px;cursor:pointer'>☰</span>
<input id=topsearch placeholder='🔍 بحث...' oninput="if(cur=='dishes'&&window.searchDishes)searchDishes(this.value)" style='background:#1f2937;border:1px solid #374151;color:#fff;padding:8px 12px;border-radius:10px;width:140px'></div>
<div style='font-weight:800'>{logo_html()}</div><div><button onclick="loadPage(cur)" style='background:#1f2937;color:#fff;border:0;padding:9px 13px;border-radius:10px;cursor:pointer'>↻</button></div></div>
<div class=main id=mn>{c}</div>
<div id=delModal><div id=delBox><div style='font-size:52px'>🗑️</div><h3 style='margin:10px 0'>تأكيد الحذف</h3><p style='opacity:.7;margin:0 0 18px'>متأكد بدك تحذف هاد العنصر؟</p><div style='display:flex;gap:10px'><button onclick="closeDel()" style='flex:1;padding:13px;border-radius:12px;border:1px solid #ffffff33;background:transparent;color:inherit;cursor:pointer;font-weight:700'>تراجع</button><button id=delYes style='flex:1;padding:13px;border-radius:12px;border:0;background:#ef4444;color:#fff;font-weight:800;cursor:pointer'>نعم، احذف</button></div></div></div>
<script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>
<script>let cur='{v}';let delUrl=null;
function toggleSb(f){{let sb=document.getElementById('sb'),ov=document.getElementById('overlay');let o=f!==undefined?f:!sb.classList.contains('active');sb.classList.toggle('active',o);ov.classList.toggle('show',o)}}
async function loadPage(v){{cur=v;toggleSb(false);let mn=document.getElementById('mn');mn.innerHTML='<div class=skel></div><div class=skel></div><div class=skel></div>';try{{let r=await fetch('/api/page?v='+v);if(!r.ok)throw 0;mn.innerHTML=await r.text();}}catch(e){{mn.innerHTML='<div class=card>⚠️ خطأ بالتحميل، حاول مرة ثانية</div>'}}bind()}}
function bind(){{document.querySelectorAll('form[data-ajax]').forEach(f=>{{f.onsubmit=async e=>{{e.preventDefault();let b=f.querySelector('button');let t=b?b.textContent:'';if(b)b.textContent='⏳...';let r=await fetch(f.action,{{method:'POST',body:new FormData(f)}});if(b)b.textContent=t;if(r.ok)loadPage(cur);else alert(await r.text())}}}})}}
function askDel(u){{delUrl=u;document.getElementById('delModal').classList.add('show')}}
function closeDel(){{document.getElementById('delModal').classList.remove('show');delUrl=null}}
document.getElementById('delYes').onclick=async()=>{{if(delUrl)await fetch(delUrl);closeDel();loadPage(cur)}};
document.getElementById('delModal').onclick=e=>{{if(e.target.id=='delModal')closeDel()}};
bind();</script></body></html>"""

if __name__=='__main__':
 app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
