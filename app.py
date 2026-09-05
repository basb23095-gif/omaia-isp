from flask import Flask, request, redirect, render_template_string, session, Response
import os, datetime, io, csv, time, socket
try:
 import psycopg2, psycopg2.extras
except: psycopg2=None
import sqlite3
from colors import get_colors, get_bg_css
app = Flask(__name__, static_folder='static')
app.secret_key=os.environ.get("SECRET_KEY","omia-sec-2026")
DATABASE_URL=os.environ.get("DATABASE_URL","")
USE_PG=bool(DATABASE_URL and psycopg2)
_pg=None;_pt=0
SUPPORT="0095344851045"
LANGS={'ar':{'home':'🏠 الرئيسية','subs':'👥 المشتركين','dishes':'📡 الصحون','map':'🗺️ الخريطة','ping':'📶 فحص','towers':'🗼 الأبراج','report':'📊 تقرير','servers':'🖥️ سيرفرات','notifs':'🔔 إشعارات','logs':'📝 السجل','settings':'⚙️ الإعدادات','support':'🛠️ دعم','ledger':'📒 الحسابات','logout':'🚪 خروج','menu':'☰ القائمة'},
'en':{'home':'🏠 Home','subs':'👥 Subs','dishes':'📡 Dishes','map':'🗺️ Map','ping':'📶 Ping','towers':'🗼 Towers','report':'📊 Report','servers':'🖥️ Servers','notifs':'🔔 Notifs','logs':'📝 Logs','settings':'⚙️ Settings','support':'🛠️ Support','ledger':'📒 Ledger','logout':'🚪 Logout','menu':'☰ Menu'}}
def T(k):
 l=session.get('lang','ar')
 return LANGS.get(l,{}).get(k,k)
def db():
 global _pg,_pt
 if USE_PG:
  if _pg and time.time()-_pt<300:
   try:_pg.cursor().execute("SELECT 1");return _pg
   except:pass
  _pg=psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=5);_pg.autocommit=True;_pt=time.time();return _pg
 c=sqlite3.connect("omia.db");c.row_factory=sqlite3.Row;return c
def cc(c):
 if not USE_PG:
  try:c.close()
  except:pass
def ex(c,q,a=()):
 if USE_PG:
  cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor);cur.execute(q.replace("?","%s"),a);return cur
 return c.execute(q,a)
def init():
 c=db()
 ss=["CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,username TEXT,password TEXT,role TEXT,active INT DEFAULT 1)","CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,status TEXT,balance_usd REAL DEFAULT 0,balance_syr REAL DEFAULT 0)","CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,site TEXT,area TEXT,tower TEXT,lat REAL DEFAULT 0,lng REAL DEFAULT 0)","CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,lat REAL,lng REAL,note TEXT)","CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,sub_id INT,date TEXT,usd REAL,syr REAL,type TEXT,note TEXT,by_user TEXT)","CREATE TABLE IF NOT EXISTS servers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,host TEXT,username TEXT,password TEXT)","CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,msg TEXT,date TEXT,seen INT DEFAULT 0)","CREATE TABLE IF NOT EXISTS login_logs(id INTEGER PRIMARY KEY AUTOINCREMENT,phone TEXT,date TEXT,ip TEXT)"]
 if USE_PG:ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
 if USE_PG:
  cur=c.cursor()
  for s in ss:cur.execute(s)
  cur.execute("SELECT * FROM users WHERE phone='05344851045'")
  if not cur.fetchone():cur.execute("INSERT INTO users(phone,username,password,role,active) VALUES('05344851045','admin','admin2024','super',1)")
  for col in ["area TEXT","location TEXT","owner TEXT"]:
   try:cur.execute(f"ALTER TABLE towers ADD COLUMN {col}")
   except:pass
  c.commit();cur.close()
 else:
  for s in ss:c.execute(s)
  if not c.execute("SELECT * FROM users WHERE phone='05344851045'").fetchone():c.execute("INSERT INTO users(phone,username,password,role,active) VALUES('05344851045','admin','admin2024','super',1)")
  for col in ["area TEXT","location TEXT","owner TEXT"]:
   try:c.execute(f"ALTER TABLE towers ADD COLUMN {col}")
   except:pass
  c.commit();cc(c)
init()
def ping(ip):
 ip=(ip or '').strip()
 if not ip:return False
 for p in (80,443):
  try:socket.create_connection((ip,p),timeout=0.8).close();return True
  except:continue
 return False
def notify(m):
 try:
  c=db()
  if not ex(c,"SELECT id FROM notifications WHERE msg=?",(m,)).fetchone():
   ex(c,"INSERT INTO notifications(msg,date,seen) VALUES(?,?,0)",(m,datetime.datetime.now().strftime("%Y-%m-%d %H:%M")));c.commit()
  cc(c)
 except:pass
def get_view_html(v,c,role):
 if v=='home':
  ns=len(ex(c,"SELECT id FROM subs").fetchall());nd=len(ex(c,"SELECT id FROM dish_ips").fetchall());nt=len(ex(c,"SELECT id FROM towers").fetchall());nl=len(ex(c,"SELECT id FROM ledger").fetchall())
  today=datetime.date.today().isoformat()
  r1=ex(c,"SELECT SUM(usd) s1 FROM ledger WHERE date LIKE?",(today+"%",)).fetchone();inc=(dict(r1).get('s1') or 0) if r1 else 0
  return f"""<div class="card glass eye" style="text-align:center"><img src="/static/logo.jpg" onerror="this.style.display='none'" class="logo-sm"><h2>👋 أهلاً بك</h2><p>📅 {today} | 💰 دخل اليوم: <b>{inc}$</b></p></div><div class="row4"><div class="stat glass eye"><h2>{ns}</h2><p>👥 مشتركين</p></div><div class="stat glass eye"><h2>{nd}</h2><p>📡 صحون</p></div><div class="stat glass eye"><h2>{nt}</h2><p>🗼 أبراج</p></div><div class="stat glass eye"><h2>{nl}</h2><p>📒 قيود</p></div></div><div class="row2"><div class="card glass eye"><h3>⚡ سريع</h3><div class="row2"><button class="btn-soft" onclick="loadView('subs')">+ مشترك</button><button class="btn-soft" onclick="loadView('dishes')">+ صحن</button></div><div class="row2" style="margin-top:8px"><button class="btn-soft" onclick="loadView('ping')">📶 Ping</button><button class="btn-soft" onclick="loadView('map')">🗺️ خريطة</button></div></div><div class="card glass eye"><h3>🛠️ الدعم الفني</h3><p dir=ltr>{SUPPORT}</p><button class="btn-soft" onclick="window.open('https://wa.me/{SUPPORT}','_blank')">💬 واتساب</button></div></div>"""
 if v=='subs':
  rs=ex(c,"SELECT * FROM subs ORDER BY id DESC LIMIT 50").fetchall()
  tr="".join([f"<tr><td>{r['name']}</td><td dir=ltr style='font-size:11px'>{r['phone']}</td><td style='font-size:11px'>{r['balance_usd']}$</td><td><a class='ic' href='https://wa.me/{r['phone']}' target=_blank>💬</a></td><td><a class='ic del' href='/del_sub/{r['id']}'>✖</a></td></tr>" for r in rs])
  return f"<div class='card glass eye'><form method=post action=/add_sub><div class=row2><input name=name placeholder='الاسم' required><input name=phone placeholder='هاتف' required></div><button class='btn-soft'>إضافة مشترك</button></form></div><div class='card glass eye'><table><tr><th>اسم</th><th>هاتف</th><th>رصيد</th><th></th><th></th></tr>{tr}</table></div>"
 if v=='dishes':
  rs=ex(c,"SELECT * FROM dish_ips ORDER BY id DESC LIMIT 100").fetchall()
  tr="".join([f"<tr><td dir=ltr style='font-size:11px'>{dict(r)['ip'] or '-'}</td><td style='font-size:11px'>{dict(r).get('location','')}</td><td style='font-size:11px'>{dict(r).get('area','')}</td><td><a class='ic del' href='/del_dish/{dict(r)['id']}'>✖</a></td></tr>" for r in rs])
  return f"<div class='card glass eye'><h3>📡 الصحون</h3><form method=post action=/add_dish><div class=row2><input name=ip placeholder='IP' dir=ltr><input name=location placeholder='اسم الصحن'></div><div class=row2><input name=area placeholder='المنطقة'><input name=tower placeholder='البرج'></div><button class='btn-soft'>إضافة</button></form></div><div class='card glass eye'><table><tr><th>IP</th><th>اسم</th><th>منطقة</th><th></th></tr>{tr}</table></div>"
 if v=='ping':
  rs=ex(c,"SELECT * FROM dish_ips ORDER BY id DESC LIMIT 50").fetchall();tr=""
  for r in rs:
   d=dict(r);ok=ping(d['ip'] or '');dot="🟢" if ok else "🔴"
   if not ok and d['ip']:notify(f"🔴 صحن فاصل: {d.get('location')} {d['ip']}")
   tr+=f"<tr><td style='font-size:11px'>{dot}</td><td dir=ltr style='font-size:11px'>{d['ip']}</td><td style='font-size:11px'>{d.get('location','')}</td></tr>"
  return f"<div class='card glass eye'><h3>📶 Ping</h3><button class='btn-soft' onclick=\"loadView('ping',true)\">🔄 فحص</button></div><div class='card glass eye'><table><tr><th>حالة</th><th>IP</th><th>اسم</th></tr>{tr}</table></div>"
 if v=='towers':
  rs=ex(c,"SELECT * FROM towers ORDER BY id DESC LIMIT 100").fetchall()
  tr="".join([f"<tr><td style='font-size:11px'>{dict(r).get('name','')}</td><td style='font-size:11px'>{dict(r).get('area','') or ''}</td><td style='font-size:11px'>{dict(r).get('owner','') or ''}</td><td><a class='ic del' href='/del_tower/{dict(r)['id']}'>✖</a></td></tr>" for r in rs])
  return f"<div class='card glass eye'><h3>🗼 إضافة برج</h3><form method=post action=/add_tower><input name=name placeholder='اسم برج' required><div class=row2><input name=area placeholder='منطقه'><input name=owner placeholder='لمين برج'></div><input name=location placeholder='موقع برج'><button class='btn-soft'>حفظ البرج 📡</button></form></div><div class='card glass eye'><table><tr><th>اسم</th><th>منطقه</th><th>لمين</th><th></th></tr>{tr}</table></div>"
 if v=='map':
  dishes=ex(c,"SELECT location,lat,lng,ip FROM dish_ips WHERE lat!=0 LIMIT 200").fetchall()
  pts=",".join([f"{{n:'📡 {r['location']}',la:{r['lat']},ln:{r['lng']}}}" for r in dishes])
  return f"<div class='card glass eye'><h3>🗺️ الخريطة</h3><div id=map></div></div><script>var m=L.map('map').setView([34.72,36.72],10);L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:19}}).addTo(m);var pts=[{pts}];pts.forEach(p=>L.marker([p.la,p.ln]).addTo(m).bindPopup(p.n));if(pts.length)m.fitBounds(pts.map(p=>[p.la,p.ln]));setTimeout(()=>m.invalidateSize(),500);</script>"
 if v=='ledger':
  if role not in ('super','admin'):return "<div class='card glass eye'>ممنوع</div>"
  rs=ex(c,"SELECT l.*,s.name sn FROM ledger l LEFT JOIN subs s ON s.id=l.sub_id ORDER BY l.id DESC LIMIT 100").fetchall()
  subs=ex(c,"SELECT id,name FROM subs LIMIT 200").fetchall();opts="".join([f"<option value='{s['id']}'>{s['name']}</option>" for s in subs])
  tr="".join([f"<tr><td style='font-size:11px'>{r['date']}</td><td style='font-size:11px'>{r['sn']}</td><td style='font-size:11px'>{r['usd']}</td></tr>" for r in rs])
  return f"<div class='card glass eye'><h3>📒 دفتر</h3><form method=post action=/charge><select name=sub_id>{opts}</select><div class=row2><input name=amount type=number step=0.01 required placeholder='مبلغ'><select name=currency><option value=usd>$</option><option value=syr>ل.س</option></select></div><button class='btn-soft'>تسجيل</button></form></div><div class='card glass eye'><table><tr><th>تاريخ</th><th>مشترك</th><th>$</th></tr>{tr}</table></div>"
 if v=='report':
  today=datetime.date.today().isoformat();month=today[:7]
  r1=ex(c,"SELECT SUM(usd) s1 FROM ledger WHERE date LIKE?",(today+"%",)).fetchone()
  a=dict(r1) if r1 else {}
  return f"<div class='card glass eye'><h3>📊 تقرير</h3><p>اليوم: {a.get('s1') or 0}$</p></div>"
 if v=='servers':
  rs=ex(c,"SELECT * FROM servers LIMIT 50").fetchall();tr="".join([f"<tr><td style='font-size:11px'>{r['name']}</td><td dir=ltr style='font-size:11px'>{r['host']}</td></tr>" for r in rs])
  return f"<div class='card glass eye'><form method=post action=/add_srv><div class=row2><input name=name placeholder='اسم' required><input name=host placeholder='host' dir=ltr required></div><button class='btn-soft'>إضافة</button></form></div><div class='card glass eye'><table>{tr}</table></div>"
 if v=='notifs':
  rs=ex(c,"SELECT * FROM notifications ORDER BY id DESC LIMIT 50").fetchall();ex(c,"UPDATE notifications SET seen=1");c.commit()
  t="".join([f"<div class='card glass eye' style='font-size:12px'>🔔 {r['msg']}<br><small>{r['date']}</small></div>" for r in rs])
  return f"<h3>🔔 إشعارات</h3>{t}"
 if v=='logs':
  rs=ex(c,"SELECT * FROM login_logs ORDER BY id DESC LIMIT 50").fetchall()
  tr="".join([f"<tr><td style='font-size:11px'>{r['phone']}</td><td style='font-size:11px'>{r['date']}</td></tr>" for r in rs])
  return f"<div class='card glass eye'><h3>📝 سجل الدخول</h3><table><tr><th>مستخدم</th><th>وقت</th></tr>{tr}</table></div>"
 if v=='settings':
  us=ex(c,"SELECT * FROM users LIMIT 100").fetchall();tr=""
  for u in us:
   st="✅" if u['active']==1 else "⛔"
   tr+=f"<tr><td dir=ltr style='font-size:11px'>{u['phone']}</td><td style='font-size:11px'>{u['username']}</td><td style='font-size:11px'>{u['role']}</td><td style='font-size:11px'>{st}</td><td style='white-space:nowrap'><a class='ic' href='/toggle_user/{u['phone']}'>⏯️</a> <a class='ic del' href='/del_user/{u['phone']}'>✖</a></td></tr>"
  return f"<div class='card glass eye'><h3>⚙️ إضافة مستخدم</h3><form method=post action=/add_user><label style='font-size:12px'>رقم الهاتف</label><input name=phone placeholder='09xxxxxxxx' required><label style='font-size:12px'>اسم المستخدم</label><input name=username placeholder='username' required><div class=row2><input name=password placeholder='كلمة السر' required><select name=role><option value='tech'>فني</option><option value='admin'>مدير</option><option value='distributor'>موزع</option></select></div><button class='btn-soft'>إضافة</button></form></div><div class='card glass eye' style='overflow-x:auto'><table><tr><th>الهاتف</th><th>اليوزر</th><th>الدور</th><th>الحالة</th><th>تحكم</th></tr>{tr}</table></div>"
 if v=='support':
  return f"<div class='card glass eye' style='text-align:center'><h3>🛠️ الدعم</h3><h2 dir=ltr>{SUPPORT}</h2><button class='btn-soft' onclick=\"window.open('https://wa.me/{SUPPORT}','_blank')\">💬 واتساب</button></div>"
 return ""
def base_html(content,curview):
 col=get_colors();con=db()
 try:nn=len(ex(con,"SELECT id FROM notifications WHERE seen=0").fetchall())
 except:nn=0
 cc(con);role=session.get('role','tech');lang=session.get('lang','ar');is_ar=lang=='ar'
 ledger_link=f'<a href="#" data-v="ledger">{T("ledger")}</a>' if role in ('super','admin') else ''
 main_col=col['main'];text_col="#E8EAF0";bg_css=get_bg_css() if 'get_bg_css' in dir() else "background:linear-gradient(180deg,#0f1420,#121826);"
 dirv='rtl' if is_ar else 'ltr';langv='ar' if is_ar else 'en'
 h=f"""<!DOCTYPE html><html lang="{langv}" dir="{dirv}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1"><title>OMAIA ISP</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"><link rel="preload" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" as="style">
<style>
*{{box-sizing:border-box;-webkit-tap-highlight-color:transparent}}body{{margin:0;font-family:'Segoe UI';{bg_css};color:{text_col};min-height:100vh;overflow-x:hidden}}
.ic{{font-size:11px!important;text-decoration:none;padding:4px 6px;border-radius:8px;background:rgba(255,255,255,.06);display:inline-block;min-width:28px;text-align:center}}
.ic.del{{color:#ff8a8a}}.ic:active{{transform:scale(.9)}}
td a{{font-size:11px!important}}
.eye{{background:rgba(255,255,255,.05)!important;backdrop-filter:blur(20px);border:1px solid rgba(255,255,255,.08)!important}}
.top{{position:fixed;top:0;right:0;left:0;height:58px;display:flex;align-items:center;justify-content:space-between;padding:0 10px;z-index:1002;background:rgba(15,20,32,.85);backdrop-filter:blur(20px)}}
#mb{{width:84px;height:38px;border-radius:18px;border:none;background:linear-gradient(135deg,{main_col},#7c3aed);color:#fff;font-size:13px;font-weight:700}}
.langb{{width:44px;height:32px;border-radius:12px;border:1px solid rgba(255,255,255,.15);background:rgba(255,255,255,.08);color:{text_col};font-size:12px;font-weight:700}}
.sb{{position:fixed;top:66px;right:8px;width:250px;border-radius:18px;padding:10px;z-index:1003;max-height:84vh;overflow:auto;transition:transform.4s}}
.sb.hide{{transform:translateX(120%);opacity:0;pointer-events:none}}
.sb a{{display:block;padding:10px;margin:5px 0;background:rgba(255,255,255,.04);text-decoration:none;border-radius:12px;color:{text_col};font-size:13px;font-weight:600}}
.mn{{padding:70px 10px 20px;max-width:1400px;width:100%;margin:auto}}
.card{{padding:14px;border-radius:18px;margin:10px 0}}
table{{width:100%;border-collapse:collapse;font-size:11px;display:block;overflow-x:auto;white-space:nowrap}}th,td{{padding:7px 5px;text-align:center}}th{{color:{main_col}}}
input,select{{width:100%;padding:11px;margin:6px 0;border-radius:12px;border:1px solid rgba(255,255,255,.1);background:rgba(255,255,255,.05);color:{text_col};font-size:16px}}
.btn-soft{{padding:12px;width:100%;border:none;border-radius:14px;font-weight:800;background:linear-gradient(135deg,{main_col},#7c3aed);color:#fff;font-size:14px}}
.row2{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}.row4{{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:8px}}
#map{{height:320px;border-radius:14px}}
.wa{{position:fixed;bottom:16px;left:16px;width:48px;height:48px;border-radius:50%;background:#22c55e;display:flex;align-items:center;justify-content:center;font-size:22px;text-decoration:none}}
.logo-sm{{width:64px;height:64px;border-radius:18px;object-fit:cover}}
@media(max-width:480px){{.row2{{grid-template-columns:1fr}}.row4{{grid-template-columns:1fr 1fr}}.stat h2{{font-size:22px}}}}
</style></head><body>
<div class="top"><button id="mb">{T('menu')}</button><b style="color:{main_col}">OMAIA ISP</b><div style="display:flex;gap:6px;align-items:center"><span style="font-size:11px">{nn if nn else ''}</span><button class="langb" onclick="location.href='/set_lang/{'en' if is_ar else 'ar'}'">{'EN' if is_ar else 'عربي'}</button></div></div>
<div class="sb eye hide" id="sb">
<a href="#" data-v="home">{T('home')}</a><a href="#" data-v="subs">{T('subs')}</a><a href="#" data-v="dishes">{T('dishes')}</a><a href="#" data-v="map">{T('map')}</a><a href="#" data-v="ping">{T('ping')}</a>{ledger_link}<a href="#" data-v="towers">{T('towers')}</a><a href="#" data-v="report">{T('report')}</a><a href="#" data-v="servers">{T('servers')}</a><a href="#" data-v="notifs">{T('notifs')}</a><a href="#" data-v="logs">{T('logs')}</a><a href="#" data-v="settings">{T('settings')}</a><a href="#" data-v="support">{T('support')}</a><a href="/logout">{T('logout')}</a></div>
<div class="mn" id="mn">{content}</div>
<a class="wa" href="https://wa.me/{SUPPORT}" target="_blank">💬</a>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" defer></script>
<script>
let cache={{}},curView="{curview}";
let sb=document.getElementById('sb'),mn=document.getElementById('mn');
document.getElementById('mb').onclick=e=>{{e.stopPropagation();sb.classList.toggle('hide')}};
document.addEventListener('click',e=>{{if(!sb.classList.contains('hide')&&!sb.contains(e.target))sb.classList.add('hide')}});
async function loadView(v,force){{if(!force&&cache[v]){{mn.innerHTML=cache[v];curView=v;bind();return}}let r=await fetch('/api/view?v='+v);let h=await r.text();cache[v]=h;mn.innerHTML=h;curView=v;sb.classList.add('hide');window.scrollTo(0,0);bind()}}
function bind(){{mn.querySelectorAll('script').forEach(s=>{{let n=document.createElement('script');n.textContent=s.textContent;document.body.appendChild(n);s.remove()}})}}
document.querySelectorAll('[data-v]').forEach(a=>a.onclick=e=>{{e.preventDefault();loadView(a.dataset.v)}});
if(location.hash)loadView(location.hash.replace('#',''));
</script></body></html>"""
 return h
@app.after_request
def add_cache(r):
 if request.path.startswith('/static/'):r.cache_control.max_age=86400
 elif request.path.startswith('/api/'):r.cache_control.max_age=5
 r.headers['X-Content-Type-Options']='nosniff'
 return r
@app.route('/set_lang/<l>')
def set_lang(l):
 session['lang']='en' if l=='en' else 'ar'
 return redirect(request.referrer or '/dash')
@app.route('/')
def ix():return redirect('/dash') if session.get('phone') else redirect('/login')
@app.route('/login',methods=['GET','POST'])
def login():
 m=""
 if request.method=='POST':
  i=request.form.get('phone','').strip();p=request.form.get('password','')
  c=db();u=ex(c,"SELECT * FROM users WHERE phone=? OR username=?",(i,i)).fetchone()
  if u and dict(u)['password']==p and dict(u)['active']==1:
   d=dict(u);session['phone']=d['phone'];session['role']=d['role']
   ex(c,"INSERT INTO login_logs(phone,date,ip) VALUES(?,?,?)",(d['phone'],datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),request.remote_addr));c.commit();cc(c);return redirect('/dash')
  try:cc(c)
  except:pass
  m="<p style='color:#ff9a9a'>خطأ</p>"
 col=get_colors()
 return f"""<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>دخول</title><style>body{{margin:0;font-family:'Segoe UI';background:#0f1420;color:#fff}}.wrap{{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:16px}}.box{{background:rgba(255,255,255,.06);border-radius:24px;padding:32px 20px;max-width:360px;width:100%;text-align:center}}input{{width:100%;padding:13px;margin:7px 0;border-radius:12px;border:1px solid #333;background:#1a2332;color:#fff;font-size:16px}}button{{width:100%;padding:14px;border:none;border-radius:14px;background:linear-gradient(135deg,{col['main']},#7c3aed);color:#fff;font-weight:800}}</style></head><body><div class="wrap"><div class="box"><h2>OMAIA ISP</h2>{m}<form method=post><input name=phone placeholder="هاتف / يوزر" required><input name=password type=password placeholder="كلمة السر" required><button>دخول</button></form></div></div></body></html>"""
@app.route('/logout')
def lo():session.clear();return redirect('/login')
@app.route('/dash')
def dash():
 if not session.get('phone'):return redirect('/login')
 v=request.args.get('view','home')
 c=db();html=get_view_html(v,c,session.get('role','tech'));cc(c)
 return render_template_string(base_html(html,v))
@app.route('/api/view')
def apiv():
 if not session.get('phone'):return "no"
 v=request.args.get('v','home');c=db();h=get_view_html(v,c,session.get('role','tech'));cc(c);return h
@app.route('/add_sub',methods=['POST'])
def a1():c=db();ex(c,"INSERT INTO subs(name,phone,status) VALUES(?,?,?)",(request.form['name'],request.form['phone'],'نشط'));c.commit();cc(c);return redirect('/dash#subs')
@app.route('/del_sub/<int:i>')
def d1(i):c=db();ex(c,"DELETE FROM subs WHERE id=?",(i,));c.commit();cc(c);return redirect('/dash#subs')
@app.route('/add_dish',methods=['POST'])
def a2():
 c=db();f=request.form
 ex(c,"INSERT INTO dish_ips(ip,location,area,tower) VALUES(?,?,?,?)",(f.get('ip') or '',f.get('location') or '',f.get('area') or '',f.get('tower') or ''));c.commit();cc(c);return redirect('/dash#dishes')
@app.route('/del_dish/<int:i>')
def d2(i):c=db();ex(c,"DELETE FROM dish_ips WHERE id=?",(i,));c.commit();cc(c);return redirect('/dash#dishes')
@app.route('/add_tower',methods=['POST'])
def at():
 c=db();f=request.form
 ex(c,"INSERT INTO towers(name,area,location,owner) VALUES(?,?,?,?)",(f.get('name') or '',f.get('area') or '',f.get('location') or '',f.get('owner') or ''))
 c.commit();cc(c);return redirect('/dash#towers')
@app.route('/del_tower/<int:i>')
def dt(i):c=db();ex(c,"DELETE FROM towers WHERE id=?",(i,));c.commit();cc(c);return redirect('/dash#towers')
@app.route('/add_srv',methods=['POST'])
def a3():c=db();ex(c,"INSERT INTO servers(name,host,username,password) VALUES(?,?,?,?)",(request.form['name'],request.form['host'],'u','p'));c.commit();cc(c);return redirect('/dash#servers')
@app.route('/add_user',methods=['POST'])
def a4():
 c=db()
 try:ex(c,"INSERT INTO users(phone,username,password,role,active) VALUES(?,?,?,?,1)",(request.form['phone'].strip(),request.form['username'].strip(),request.form['password'],request.form.get('role','tech')));c.commit()
 except:pass
 cc(c);return redirect('/dash#settings')
@app.route('/del_user/<ph>')
def du(ph):
 if ph=='05344851045':return redirect('/dash#settings')
 c=db();ex(c,"DELETE FROM users WHERE phone=?",(ph,));c.commit();cc(c);return redirect('/dash#settings')
@app.route('/toggle_user/<ph>')
def tu(ph):c=db();u=ex(c,"SELECT active FROM users WHERE phone=?",(ph,)).fetchone();na=0 if dict(u)['active']==1 else 1;ex(c,"UPDATE users SET active=? WHERE phone=?",(na,ph));c.commit();cc(c);return redirect('/dash#settings')
@app.route('/charge',methods=['POST'])
def ch():
 sid=request.form['sub_id'];amt=float(request.form['amount']);cur=request.form['currency']
 usd=amt if cur=='usd' else 0;c=db()
 ex(c,"INSERT INTO ledger(sub_id,date,usd,syr,type,note,by_user) VALUES(?,?,?,?,?,?,?)",(sid,datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),usd,0,'قبض','',session.get('phone')))
 ex(c,"UPDATE subs SET balance_usd=balance_usd+? WHERE id=?",(usd,sid))
 c.commit();cc(c);return redirect('/dash#ledger')
if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
