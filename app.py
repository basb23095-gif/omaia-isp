from flask import Flask,request,redirect,render_template_string,session,send_from_directory
import os,sqlite3,time
from datetime import datetime
try: import psycopg2,psycopg2.extras
except: psycopg2=None
try: import pandas as pd
except: pd=None

# حماية استدعاء ملف الألوان لمنع انهيار التطبيق بالسيرفر
try:
 from colors import get_colors
except:
 def get_colors(): return {"BG": "#0f172a", "TEXT": "#ffffff", "SIDEBAR": "#1e293b"}

app=Flask(__name__);app.secret_key=os.environ.get("SECRET_KEY","omaia-sec")
DBURL=os.environ.get("DATABASE_URL","");USE_PG=bool(DBURL and psycopg2)
WA_DISPLAY="0095344851045";WA_LINK="963544851045"
_pg=None;_pt=0
def db():
 global _pg,_pt
 if USE_PG:
  if _pg and time.time()-_pt<280:
   try:_pg.cursor().execute("SELECT 1");return _pg
   except:pass
  import psycopg2 as p;_pg=p.connect(DBURL,sslmode='require');_pg.autocommit=True;_pt=time.time();return _pg
 c=sqlite3.connect("omaia.db",check_same_thread=False);c.row_factory=sqlite3.Row;return c
def close(c):
 if not USE_PG:
  try:c.close()
  except:pass
def ex(c,q,a=()):
 if USE_PG:
  cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor);cur.execute(q.replace("?","%s"),a);return cur
 return c.execute(q,a)
def init():
 c=db()
 qs=["CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,username TEXT,password TEXT,role TEXT,active INT)","CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,status TEXT)","CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,name TEXT,network TEXT,tower TEXT)","CREATE TABLE IF NOT EXISTS servers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,ip TEXT,location TEXT)","CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,date TEXT,sub TEXT,amount REAL,currency TEXT,note TEXT)"]
 if USE_PG:
  cur=c.cursor()
  for q in qs:cur.execute(q.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY"))
  cur.execute("SELECT 1 FROM users WHERE phone='05344851045'")
  if not cur.fetchone():cur.execute("INSERT INTO users VALUES('05344851045','05344851045','admin2024','super',1)")
  c.commit();cur.close();return
 for q in qs:c.execute(q)
 for t,col in [("dish_ips","name"),("dish_ips","network"),("dish_ips","tower"),("ledger","amount"),("ledger","currency")]:
  try:c.execute(f"SELECT {col} FROM {t} LIMIT 1")
  except:
   try:c.execute(f"ALTER TABLE {t} ADD COLUMN {col} TEXT");c.commit()
   except:pass
 if not c.execute("SELECT 1 FROM users WHERE phone='05344851045'").fetchone():
  c.execute("INSERT INTO users VALUES('05344851045','05344851045','admin2024','super',1)");c.commit()
 close(c)
init()
@app.after_request
def hdr(r):
 r.headers['Cache-Control']='public,max-age=86400' if request.path.endswith('bg.jpg') else 'no-store'
 return r
@app.route('/bg.jpg')
def bg():
 try:return send_from_directory('static','bg.jpg')
 except:return send_from_directory('.','bg.jpg')

CSS="*{transition:.25s}body{font-family:Arial;margin:0;background:__BG__;color:__TEXT__;animation:fadeIn.4s ease}@keyframes fadeIn{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}@keyframes logoPulse{0%,100%{transform:scale(1)}50%{transform:scale(1.12)}}.logoA{animation:logoPulse 2s infinite;display:inline-block}body.lb{background:linear-gradient(rgba(4,30,54,.55),rgba(4,30,54,.78)),url('/bg.jpg') center/cover fixed,__BG__;min-height:100vh;display:flex;align-items:center;justify-content:center}.t{position:fixed;top:0;left:0;right:0;height:56px;background:__SIDEBAR__;backdrop-filter:blur(12px);display:flex;align-items:center;justify-content:space-between;padding:0 12px;z-index:20;border-bottom:2px solid #00D4FF}.m{padding:66px 10px;max-width:1050px;margin:auto;animation:slideIn.3s ease}@keyframes slideIn{from{opacity:0;transform:translateX(-18px)}to{opacity:1;transform:none}}.c{background:rgba(255,255,255,.08);backdrop-filter:blur(14px);border:1px solid rgba(0,212,255,.35);border-radius:16px;padding:16px;margin:12px 0;box-shadow:0 8px 24px rgba(0,0,0,.3)}.pt{text-align:right;font-weight:bold;font-size:19px;color:#00D4FF;margin:8px 2px}.ic{display:flex;align-items:center;gap:8px}button{background:linear-gradient(135deg,#00D4FF,#0090c8);border:0;padding:12px;width:100%;border-radius:12px;font-weight:bold;cursor:pointer;color:#021;font-size:16px}button:active{transform:scale(.96)}input,select{width:100%;padding:11px;margin:6px 0;border-radius:12px;border:1px solid #334155;background:#0f172a;color:#fff;box-sizing:border-box}.searchB{position:sticky;top:62px;z-index:10;background:rgba(0,212,255,.15);border:1px solid #00D4FF}table{width:100%;border-collapse:collapse}td,th{padding:9px;border-bottom:1px solid #234;text-align:center;font-size:14px}th{color:#00D4FF}.late{color:#ff5555!important;font-weight:bold}.g4{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.g2{display:grid;grid-template-columns:1fr 1fr;gap:10px}@media(max-width:700px){.g4{grid-template-columns:1fr 1fr}.g2{grid-template-columns:1fr}}.drawer{position:fixed;top:0;right:-285px;width:265px;height:100%;background:__SIDEBAR__;z-index:30;transition:.3s;padding:62px 12px}.drawer.open{right:0}.overlay{position:fixed;inset:0;background:rgba(0,0,0,.55);display:none;z-index:25}.overlay.show{display:block}.drawer a{display:flex;gap:10px;color:#fff;text-decoration:none;padding:12px;border-radius:10px}.drawer a:hover{background:#123;transform:translateX(-4px)}.menuBtn{cursor:pointer;font-size:24px;color:#fff;background:#00D4FF;width:42px;height:42px;display:flex;align-items:center;justify-content:center;border-radius:10px}body.light{background:#eef6ff!important;color:#102a43!important}body.light.c{background:rgba(255,255,255,.9);color:#102a43}body.light input,body.light select{background:#fff;color:#102a43}.foot{text-align:center;color:#00D4FF;font-weight:bold;margin:18px}.wa{position:fixed;bottom:16px;left:16px;background:#25D366;width:52px;height:52px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:26px;z-index:22;text-decoration:none}"
LAY= """<!DOCTYPE html><html dir=rtl><head><meta charset=UTF-8><meta name=viewport content='width=device-width,initial-scale=1'><title>OMAIA</title><style>"""+CSS+"""</style></head><body class=__BC__>
<div class=t><div style=display:flex;gap:10px;align-items:center><div class=menuBtn onclick="document.getElementById('dr').classList.add('open');document.getElementById('ov').classList.add('show')">☰</div><b style=color:#00D4FF><span class=logoA>✨</span> OMAIA ISP</b></div><div style=display:flex;gap:10px;align-items:center><span style=color:#fff;font-size:12px>أهلاً بشركة OMAIA</span><div onclick="document.body.classList.toggle('light');localStorage.setItem('th',document.body.classList.contains('light')?'l':'d')" style=cursor:pointer;font-size:22px>🌙</div><a href=/lang/toggle style='color:#fff;text-decoration:none;font-size:20px'>🌐</a></div></div>
<div id=ov class=overlay onclick="document.getElementById('dr').classList.remove('open');this.classList.remove('show')"></div>
<div id=dr class=drawer><a href=/dash>🏠 الرئيسية</a><a href=/dash?view=subs>👥 المشتركين</a><a href=/dash?view=dishes>📡 الصحون</a><a href=/dash?view=servers>🖥️ السيرفرات</a><a href=/dash?view=ledger>📒 دفتر الحسابات</a><a href=/dash?view=settings>⚙️ الإعدادات</a><a href=/logout>🚪 خروج</a><hr style=border-color:#1e3a5f><a href='https://wa.me/"""+WA_LINK+"""' target=_blank>💬 دعم """+WA_DISPLAY+"""</a></div>
<div class=m>{{c|safe}}<div class=foot>💎 تصميم م. عبدو عباس 💎<br>OMAIA ISP - أزرق سماوي<br><a href='https://wa.me/"""+WA_LINK+"""' style=color:#00D4FF;text-decoration:none>📞 """+WA_DISPLAY+"""</a></div></div>
<a class=wa href='https://wa.me/"""+WA_LINK+"""' target=_blank>💬</a>
<script>if(localStorage.getItem('th')=='l')document.body.classList.add('light');function fS(v){document.querySelectorAll('table tr').forEach((r,i)=>{if(i==0)return;r.style.display=r.innerText.includes(v)?'':'none'})}function cIP(ip){navigator.clipboard.writeText(ip);alert('تم نسخ '+ip)}</script>
</body></html>"""

def R(h,bc=""):
 s=LAY;co=get_colors()
 for k,v in co.items():s=s.replace("__"+k+"__",v)
 return render_template_string(s.replace("__BC__",bc),c=h)

def gv(r):
 try:
  d = r.fetchone() if hasattr(r, 'fetchone') else (r if r else None)
  return list(dict(d).values())[0] if d else 0
 except: return r[0] if r else 0

def title(t,icon): return f"<div class=pt>{icon} {t}</div>"

@app.route('/',methods=['GET','POST'])
def login():
 if 'p' in session: return redirect('/dash')
 if request.method == 'POST':
  i = request.form.get('phone', '').strip()
  c = db()
  u = ex(c, "SELECT * FROM users WHERE phone=? OR username=?", (i, i))
  d = u.fetchone() if hasattr(u, 'fetchone') else (u if u else None)
  if d and d['password'] == request.form.get('password') and d['active']:
   session['p'] = d['phone']
   return redirect('/dash')
  return R("<div class='c' style='width:320px;text-align:center'><p style='color:red'>خطأ في اسم المستخدم أو كلمة المرور</p><a href='/'>إعادة المحاولة</a></div>", "lb")
 return R("<div class='c' style='width:330px;text-align:center'><h2 style='color:#00D4FF'>OMAIA ISP</h2><form method='post'><input name='phone' placeholder='اسم / رقم هاتف' required><input name='password' type='password' placeholder='كلمة المرور' required><button>دخول</button></form></div>", "lb")

@app.route('/dash', methods=['GET', 'POST'])
def dash():
 if 'p' not in session: return redirect('/')
 c = db(); view = request.args.get('view', 'home')
 
 if view == 'subs':
  if request.method == 'POST':
   ex(c, "INSERT INTO subs(name,phone,status) VALUES(?,?,?)", (request.form.get('name'), request.form.get('phone'), request.form.get('status')))
  rows = ex(c, "SELECT * FROM subs").fetchall()
