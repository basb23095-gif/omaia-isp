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
T={'ar':{'home':'الرئيسية','dishes':'الصحون','towers':'الأبراج','subs':'المشتركين','ledger':'دفتر الحسابات','map':'الخريطة','logs':'السجل','support':'الدعم','settings':'الإعدادات','logout':'خروج','search':'بحث...','add':'اضافة','ping':'فحص Ping'},'en':{'home':'Home','dishes':'Dishes','towers':'Towers','subs':'Subs','ledger':'Ledger','map':'Map','logs':'Logs','support':'Support','settings':'Settings','logout':'Logout','search':'Search...','add':'Add','ping':'Ping Check'}}
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
 return jsonify(ok=ok,out=('متصل ' if ok else 'غير متصل ')+txt[:180])

def page_content(v):
 ce=can_edit();cd=can_del()
 if v=='home':
  ns=(qone("SELECT COUNT(*) AS c FROM subs") or {}).get('c',0);nd=(qone("SELECT COUNT(*) AS c FROM dish_ips") or {}).get('c',0);nt=(qone("SELECT COUNT(*) AS c FROM towers") or {}).get('c',0)
  return f"<div style='max-width:700px;margin:0 auto;text-align:center'><div style='font-size:28px'>{logo_html()}</div><div class=card><input id=hs placeholder='{L('search')}' oninput='hSrch(this.value)' style='max-width:400px;margin:0 auto'><div id=hr></div></div><div style='display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px'><div class=card onclick=\"loadPage('subs')\" style='cursor:pointer'><h3>{L('subs')}</h3><h2>{ns}</h2></div><div class=card onclick=\"loadPage('dishes')\" style='cursor:pointer'><h3>{L('dishes')}</h3><h2>{nd}</h2></div><div class=card onclick=\"loadPage('towers')\" style='cursor:pointer'><h3>{L('towers')}</h3><h2>{nt}</h2></div><div class=card onclick=\"loadPage('map')\" style='cursor:pointer'><h3>{L('map')}</h3><h2>map</h2></div></div></div>"
 if v=='dishes':
  return f"""<div style='max-width:900px;margin:0 auto'><div class=card style='text-align:center'><h3>{L('dishes')}</h3><form id=df style='display:flex;gap:6px;flex-wrap:wrap;justify-content:center'><input name=dish_name required placeholder='اسم' style='max-width:150px'><input name=ip required placeholder='IP' style='max-width:150px'><input name=location placeholder='موقع' style='max-width:150px'><button class=btn-gold type=submit>{L('add')}</button></form></div><div id=dl style='display:flex;flex-direction:column;gap:6px'></div><div style='text-align:center'><button class=btn onclick='mD()'>المزيد</button></div><script>
let pg=0;
async function lD(){{let r=await fetch('/api/search?page='+pg);let d=await r.json();let h='';d.forEach(x=>{{
let eb="";let db="";
if("{str(ce)}"=="True") eb='<button class="icon-btn" style="background:#FF9800" data-edit="'+x.id+'">E</button>';
if("{str(cd)}"=="True") db='<button class="icon-btn" style="background:#F44336" data-del="'+x.id+'">D</button>';
h+='<div class=card style="padding:6px 10px;display:flex;justify-content:space-between;align-items:center;width:320px;max-width:100%"><div style="font-size:13px"><b>'+x.dish_name+'</b> <span class=ip-badge>'+x.ip+'</span></div><div style="display:flex;gap:4px">'+eb+db+'<button class=btn-blue data-ping="'+x.ip+'">Ping</button></div></div>'}});
let el=document.getElementById('dl');if(pg==0)el.innerHTML=h;else el.innerHTML+=h;}};function mD(){{pg++;lD()}}lD();
</script></div>"""
 if v=='ping':
  return f"<div style='max-width:500px;margin:0 auto'><div class=card style='text-align:center'><h3>{L('ping')}</h3><form id=pf><input id=pip placeholder='IP' required><button class=btn-gold>Ping</button></form><div id=pr></div></div><script>document.getElementById('pf').onsubmit=async e=>{{e.preventDefault();let r=await fetch('/api/ping?ip='+encodeURIComponent(document.getElementById('pip').value));let j=await r.json();document.getElementById('pr').innerHTML='<pre>'+j.out+'</pre>'}}</script></div>"
 if v=='map':
  tw=qall("SELECT * FROM towers");tj=json.dumps([{"name":t['name'],"lat":float(t.get('lat') or 35.1318),"lng":float(t.get('lng') or 36.7578)} for t in tw],ensure_ascii=False)
  return "<div class=card><div id=map style='height:70vh;border-radius:12px'></div><script>var _t="+tj+";var map=L.map('map').setView([35.1318,36.7578],16);L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{maxZoom:19}).addTo(map);setTimeout(()=>map.invalidateSize(),300);_t.forEach(t=>L.marker([t.lat,t.lng]).addTo(map).bindPopup(t.name));</script></div>"
 if v=='settings':
  ae=get_set('allow_edit');ad=get_set('allow_del');us=qall("SELECT * FROM users");uh=""
  for u in us:
   sel_t='selected' if u['role']=='tech' else '';sel_m='selected' if u['role']=='manager' else ''
   uh+=f"<div class=card style='display:flex;justify-content:space-between;align-items:center'><div><b>{esc(u['username'])}</b><br><small>{esc(u['phone'])}</small></div><div style='display:flex;gap:6px'><select id='r_{esc(u['phone'])}' style='width:100px'><option value=tech {sel_t}>فني</option><option value=manager {sel_m}>مدير</option></select><button class=btn-blue onclick=\"saveRole('{esc(u['phone'])}')\">حفظ</button></div></div>"
  return f"<div style='max-width:650px;margin:0 auto'><div class=card><h3>{L('settings')}</h3></div>{uh}<script>async function saveRole(ph){{await fetch('/edit_user/'+ph,{{method:'POST',body:new URLSearchParams({{role:document.getElementById('r_'+ph).value}})}});toast('تم')}}</script></div>"
 return "ok"

def layout(c,v='home'):
 th=cur_theme();bg=COLORS.get('bg_dark','#0a1938');card=COLORS.get('card_dark','#222');gold=COLORS.get('gold','#ffbe4d');lg=logo_html();lang=cur_lang();t=T[lang]
 return f"<html><body>{c}</body></html>"

@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')
@app.route('/login',methods=['GET','POST'])
def login():
 if session.get('phone'): return redirect('/dash')
 if request.method=='POST':
  uin=request.form.get('userin','').strip();pw=request.form.get('password','')
  u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
  if u and check_password_hash(u['password'],pw):
   session['phone']=u['phone'];add_log("دخول");return jsonify(ok=True)
  return jsonify(ok=False),401
 return """<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><style>body{margin:0;min-height:100vh;background:#0f1424;display:flex;align-items:center;justify-content:center;color:#fff;font-family:sans-serif}.card{background:#1e2433;padding:26px;border-radius:16px;width:320px}input{width:100%;padding:12px;margin:7px 0;background:#0f1424;border:1px solid #333;color:#fff;border-radius:10px;box-sizing:border-box}.btn{width:100%;padding:13px;background:#ffbe4d;border:0;border-radius:12px;font-weight:bold}</style></head><body><div class=card><h3 style='text-align:center'>تسجيل الدخول</h3><form id=lf><input id=ui name=userin placeholder='الهاتف' required><input id=pw name=password type=password placeholder='كلمة السر' required><label><input type=checkbox id=rm style='width:auto'> حفظ كلمة السر</label><button class=btn>دخول</button></form><script>if(localStorage.getItem('rm')=='1'){document.getElementById('ui').value=localStorage.getItem('u')||'';document.getElementById('pw').value=localStorage.getItem('p')||'';document.getElementById('rm').checked=true}document.getElementById('lf').onsubmit=async e=>{e.preventDefault();let r=await fetch('/login',{method:'POST',body:new FormData(e.target)});if(r.ok){if(document.getElementById('rm').checked){localStorage.setItem('rm','1');localStorage.setItem('u',document.getElementById('ui').value);localStorage.setItem('p',document.getElementById('pw').value)}location.href='/dash'}else alert('خطأ')};</script></div></body></html>"""
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
def setv(k,v): qexec("INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)",(k,v));return "ok"
@app.route('/add_dish',methods=['POST'])
@login_required
def ad():
 ip=request.form.get('ip','').strip();nm=request.form.get('dish_name','').strip()
 if not ip or not nm: return "ناقص",400
 if qone("SELECT * FROM dish_ips WHERE ip=?",(ip,)): return "موجود",400
 qexec("INSERT INTO dish_ips(ip,location,dish_name) VALUES(?,?,?)",(ip,request.form.get('location',''),nm));return "ok"
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
@app.route('/add_sub',methods=['POST'])
@login_required
def asub(): qexec("INSERT INTO subs(name,phone) VALUES(?,?)",(request.form.get('name',''),request.form.get('phone','')));return "ok"
@app.route('/add_ledger',methods=['POST'])
@login_required
def al():
 qexec("INSERT INTO ledger(name,note,amount,currency,dt) VALUES(?,?,?,?,?)",(request.form.get('name',''),request.form.get('note',''),fnum(request.form.get('amount')),request.form.get('currency','USD'),datetime.datetime.now().isoformat()));return "ok"
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
if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
