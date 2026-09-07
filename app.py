from flask import Flask, request, redirect, session, jsonify, Response
from colors import COLORS, logo_html
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, datetime, json, html, ipaddress, subprocess
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

def get_set(k):
 r=qone("SELECT * FROM settings WHERE k=?",(k,));return r['v'] if r else '1'

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

def is_valid_ip(ip):
 try: ipaddress.ip_address(ip.strip());return True
 except:return False

def cur_theme(): return session.get('theme','dark')

@app.route('/api/ping')
@login_required
def api_ping():
 ip=request.args.get('ip','').strip()
 if not is_valid_ip(ip): return jsonify(ok=False,out='IP غير صالح')
 try:
  out=subprocess.check_output(['ping','-c','1','-W','2',ip],timeout=3).decode(errors='ignore')
  ok='ttl=' in out.lower() or '1 received' in out
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
   session['phone']=u['phone'];add_log("دخول")
   if request.headers.get('X-Requested-With')=='fetch': return jsonify(ok=True)
   return redirect('/dash')
  if request.headers.get('X-Requested-With')=='fetch': return jsonify(ok=False)
  return "<script>alert('خطأ');location.href='/login'</script>"
 return "<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><style>body{margin:0;min-height:100vh;background:#0a0e2a;display:flex;flex-direction:column;align-items:center;justify-content:center;color:#fff;font-family:sans-serif}.card{background:#1e2433;padding:25px;border-radius:20px;width:320px}input{width:100%;padding:12px;margin:8px 0;background:#0f1424;border:1px solid #333;color:#fff;border-radius:12px;box-sizing:border-box}.btn{width:100%;padding:13px;border:0;border-radius:12px;background:#ffbe4d;font-weight:800}</style></head><body><div style='font-size:28px;font-weight:800'>OMAIA ISP</div><div class=card><form method=post><input name=userin placeholder='يوزر' required><input name=password type=password placeholder='كلمة السر' required><button class=btn>دخول</button></form></div></body></html>"

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
 if q: return jsonify(qall("SELECT * FROM dish_ips WHERE ip LIKE? OR dish_name LIKE? OR location LIKE? ORDER BY id DESC LIMIT 20 OFFSET "+str(off),("%"+q+"%","%"+q+"%","%"+q+"%")))
 return jsonify(qall("SELECT * FROM dish_ips ORDER BY id DESC LIMIT 20 OFFSET "+str(off)))

@app.route('/toggle_theme')
@login_required
def tt():
 session['theme']='light' if cur_theme()=='dark' else 'dark';return "ok"

@app.route('/toggle_lang')
@login_required
def tl():
 session['lang']='en' if session.get('lang','ar')=='ar' else 'ar';return "ok"

@app.route('/set/<k>/<v>')
@manager_required
def setv(k,v): qexec("INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)",(k,v));return "ok"

@app.route('/add_dish',methods=['POST'])
@login_required
def ad():
 ip=request.form.get('ip','').strip()
 if not is_valid_ip(ip): return "IP غير صالح",400
 qexec("INSERT INTO dish_ips(ip,location,dish_name) VALUES(?,?,?)",(ip,request.form.get('location',''),request.form.get('dish_name','')));return "ok"

@app.route('/edit_dish/<int:i>',methods=['POST'])
@login_required
def ed(i):
 if not can_edit(): return "ممنوع",403
 ip=request.form.get('ip','').strip()
 if not is_valid_ip(ip): return "IP غير صالح",400
 qexec("UPDATE dish_ips SET dish_name=?,ip=?,location=? WHERE id=?",(request.form.get('dish_name',''),ip,request.form.get('location',''),i));return "ok"

@app.route('/del_dish/<int:i>')
@login_required
def dd(i):
 if not can_del(): return "ممنوع",403
 qexec("DELETE FROM dish_ips WHERE id=?",(i,));return "ok"

@app.route('/add_tower',methods=['POST'])
@login_required
def at():
 lat=fnum(request.form.get('lat') or 35.13);lng=fnum(request.form.get('lng') or 36.75)
 qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",(request.form.get('name',''),request.form.get('area',''),lat,lng));return "ok"

@app.route('/edit_tower/<int:i>',methods=['POST'])
@login_required
def et(i):
 if not can_edit(): return "ممنوع",403
 qexec("UPDATE towers SET name=?,area=? WHERE id=?",(request.form.get('name',''),request.form.get('area',''),i));return "ok"

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
def esub(i):
 if not can_edit(): return "ممنوع",403
 qexec("UPDATE subs SET name=?,phone=? WHERE id=?",(request.form.get('name',''),request.form.get('phone',''),i));return "ok"

@app.route('/del_sub/<int:i>')
@login_required
def dsub(i):
 if not can_del(): return "ممنوع",403
 qexec("DELETE FROM subs WHERE id=?",(i,));return "ok"

@app.route('/add_ledger',methods=['POST'])
@login_required
def al(): qexec("INSERT INTO ledger(name,amount,note,currency,dt) VALUES(?,?,?,?,?)",(request.form.get('name',''),fnum(request.form.get('amount')),request.form.get('note',''),request.form.get('currency','USD'),datetime.datetime.now().isoformat()));return "ok"

@app.route('/edit_ledger/<int:i>',methods=['POST'])
@login_required
def el(i):
 if not can_edit(): return "ممنوع",403
 qexec("UPDATE ledger SET name=?,amount=?,note=? WHERE id=?",(request.form.get('name',''),fnum(request.form.get('amount')),request.form.get('note',''),i));return "ok"

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
def cp():
 np=request.form.get('newpass','').strip()
 if len(np)<4: return "قصيرة",400
 qexec("UPDATE users SET password=? WHERE phone=?",(generate_password_hash(np),session.get('phone')));return "ok"

def page_content(v):
 ce=can_edit();cd=can_del()
 if v=='home':
  ns=(qone("SELECT COUNT(*) c FROM subs") or {}).get('c',0);nd=(qone("SELECT COUNT(*) c FROM dish_ips") or {}).get('c',0);nt=(qone("SELECT COUNT(*) c FROM towers") or {}).get('c',0)
  return f"<div style='max-width:700px;margin:0 auto;text-align:center'><h2>{logo_html()}</h2><div style='display:grid;grid-template-columns:1fr 1fr;gap:12px'><div class=card onclick=\"saveAndLoad('subs')\" style='cursor:pointer'><h3>المشتركين</h3><h2>{ns}</h2></div><div class=card onclick=\"saveAndLoad('dishes')\" style='cursor:pointer'><h3>الصحون</h3><h2>{nd}</h2></div><div class=card onclick=\"saveAndLoad('towers')\" style='cursor:pointer'><h3>الأبراج</h3><h2>{nt}</h2></div><div class=card onclick=\"saveAndLoad('map')\" style='cursor:pointer'><h3>الخريطة</h3><h2>📍</h2></div></div></div>"

 if v=='towers':
  rs=qall("SELECT * FROM towers ORDER BY id DESC")
  rows=""
  for r in rs:
   eb="<button onclick='eT("+str(r['id'])+")'>تعديل</button>" if ce else ""
   db="<button onclick='delItem(\"/del_tower/"+str(r['id'])+"\")'>حذف</button>" if cd else ""
   rows+=f"<div class=card><b>{esc(r['name'])}</b> - {esc(r['area'] or '')} {eb} {db}</div>"
  return f"<div style='max-width:700px;margin:0 auto'><div class=card><h3>الابراج</h3><form data-ajax method=post action=/add_tower><input name=name placeholder='اسم' required><input name=area placeholder='منطقة'><button class=btn-gold>اضافة</button></form></div>{rows}<script>function eT(id){{let n=prompt('اسم:');if(n==null)return;fetch('/edit_tower/'+id,{{method:'POST',body:new URLSearchParams({{name:n}})}}).then(()=>loadPage('towers',true))}}</script></div>"

 if v=='subs':
  rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 100")
  rows=""
  for r in rs:
   eb="<button onclick='eS("+str(r['id'])+")'>تعديل</button>" if ce else ""
   db="<button onclick='delItem(\"/del_sub/"+str(r['id'])+"\")'>حذف</button>" if cd else ""
   rows+=f"<div class=card><b>{esc(r['name'])}</b> - {esc(r['phone'] or '')} {eb} {db}</div>"
  return f"<div style='max-width:700px;margin:0 auto'><div class=card><h3>المشتركين</h3><form data-ajax method=post action=/add_sub><input name=name placeholder='اسم' required><input name=phone placeholder='هاتف'><button class=btn-gold>اضافة</button></form></div>{rows}<script>function eS(id){{let n=prompt('اسم:');if(n==null)return;fetch('/edit_sub/'+id,{{method:'POST',body:new URLSearchParams({{name:n}})}}).then(()=>loadPage('subs',true))}}</script></div>"

 if v=='ledger':
  rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 50")
  rows=""
  for r in rs:
   eb="<button onclick='eL("+str(r['id'])+")'>تعديل</button>" if ce else ""
   db="<button onclick='delItem(\"/del_ledger/"+str(r['id'])+"\")'>حذف</button>" if cd else ""
   rows+=f"<div class=card><b>{esc(r['name'])}</b> {r['amount']} {esc(r['currency'] or '')} {eb} {db}</div>"
  return f"<div style='max-width:600px;margin:0 auto'><div class=card><h3>دفتر حسابات</h3><form data-ajax method=post action=/add_ledger><input name=name placeholder='اسم' required><input name=amount type=number step=0.01 placeholder='مبلغ' required><button class=btn-gold>اضافة</button></form></div>{rows}<script>function eL(id){{let n=prompt('اسم:');if(n==null)return;fetch('/edit_ledger/'+id,{{method:'POST',body:new URLSearchParams({{name:n}})}}).then(()=>loadPage('ledger',true))}}</script></div>"

 if v=='dishes':
  return "<div style='max-width:900px;margin:0 auto'><div class=card><h3>الصحون</h3><form data-ajax method=post action=/add_dish><input name=dish_name placeholder='اسم' required><input name=ip placeholder='IP' required><input name=location placeholder='موقع'><button class=btn-gold>اضافة</button></form></div><div id=dl></div><script>async function ld(){let r=await fetch('/api/search');let d=await r.json();let h='';d.forEach(x=>{h+='<div class=card>'+x.dish_name+' '+x.ip+' <button onclick=\"p1(\\''+x.ip+'\\',this)\">بينغ</button><span></span></div>'});document.getElementById('dl').innerHTML=h}async function p1(ip,b){let s=b.nextElementSibling;s.textContent='...';let r=await fetch('/api/ping?ip='+ip);let j=await r.json();s.textContent=j.out}ld();</script></div>"

 if v=='map':
  return "<div class=card><div id=map style='height:60vh'></div><script>var map=L.map('map').setView([35.13,36.75],13);L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);setTimeout(()=>map.invalidateSize(),400);</script></div>"

 if v=='support':
  return f"<div class=card style='text-align:center'><h2>{logo_html()}</h2><a href='https://wa.me/905344851045' target=_blank>واتساب</a> | <a href='https://instagram.com/af_20_1999' target=_blank>انستغرام</a></div>"

 if v=='settings':
  return f"<div class=card><h3>الاعدادات</h3><button onclick='toggleTheme()'>ليل/نهار</button> <button onclick='toggleLang()'>لغة</button><form data-ajax method=post action=/change_pass><input name=newpass type=password placeholder='كلمة جديدة' required><button>حفظ كلمة السر</button></form></div>"

 return "<div class=card>ok</div>"

def layout(c,v='home'):
 th=cur_theme();is_dark=(th=='dark')
 bg=COLORS['bg_dark'] if is_dark else COLORS['bg_light']
 card_bg=COLORS['card_dark'] if is_dark else COLORS['card_light']
 txt="#fff" if is_dark else "#111"
 return f"<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><link rel=stylesheet href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'><style>*{{font-family:sans-serif;box-sizing:border-box}}body{{margin:0;background:{bg};color:{txt}}}.sidebar{{position:fixed;right:0;top:0;width:280px;height:100%;background:#111;color:#fff;z-index:1002;padding-top:70px;transform:translateX(300px);transition:.3s}}.sidebar.active{{transform:translateX(0)}}.sidebar a{{display:block;padding:12px;margin:6px;color:#fff;text-decoration:none}}#overlay{{position:fixed;inset:0;background:#0007;z-index:1001;display:none}}#overlay.show{{display:block}}.top{{position:fixed;top:0;left:0;right:0;height:60px;background:#111;color:#fff;display:flex;align-items:center;justify-content:space-between;padding:0 12px;z-index:1003}}.main{{margin-top:70px;padding:12px}}.card{{background:{card_bg};color:{txt};padding:14px;border-radius:12px;margin-bottom:10px}}input,select{{width:100%;padding:10px;margin:5px 0;border-radius:8px}}.btn-gold{{background:{COLORS['gold']};padding:8px 14px;border:0;border-radius:8px}}</style></head><body><div id=overlay onclick=\"toggleSb(false)\"></div><div class=sidebar id=sb><a href=\"javascript:saveAndLoad('home')\">الرئيسية</a><a href=\"javascript:saveAndLoad('dishes')\">الصحون</a><a href=\"javascript:saveAndLoad('towers')\">الابراج</a><a href=\"javascript:saveAndLoad('subs')\">المشتركين</a><a href=\"javascript:saveAndLoad('ledger')\">حسابات</a><a href=\"javascript:saveAndLoad('map')\">الخريطة</a><a href=\"javascript:saveAndLoad('support')\">الدعم</a><a href=\"javascript:saveAndLoad('settings')\">الاعدادات</a><a href=/logout>خروج</a></div><div class=top><div onclick=\"toggleSb()\">☰</div><div>{logo_html()}</div><div><button onclick=\"saveAndLoad(cur,true)\">تحديث</button></div></div><div class=main id=mn>{c}</div><script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script><script>let cur='{v}';function toggleSb(f){{let sb=document.getElementById('sb');let ov=document.getElementById('overlay');let o=f!==undefined?f:!sb.classList.contains('active');sb.classList.toggle('active',o);ov.classList.toggle('show',o)}}async function loadPage(v){{cur=v;toggleSb(false);let r=await fetch('/api/page?v='+v);document.getElementById('mn').innerHTML=await r.text();bind()}}function saveAndLoad(v){{loadPage(v)}}function bind(){{document.querySelectorAll('form[data-ajax]').forEach(f=>{{f.onsubmit=async e=>{{e.preventDefault();await fetch(f.action,{{method:'POST',body:new FormData(f)}});loadPage(cur)}}}})}}window.delItem=async u=>{{if(!confirm('حذف؟'))return;await fetch(u);loadPage(cur)}};window.toggleTheme=async()=>{{await fetch('/toggle_theme');location.reload()}};window.toggleLang=async()=>{{await fetch('/toggle_lang');location.reload()}};bind();</script></body></html>"

if __name__=='__main__':
 app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
