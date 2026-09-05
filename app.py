from flask import Flask,request,redirect,render_template_string,session,send_from_directory
import os,sqlite3,time
from datetime import datetime
try: import psycopg2,psycopg2.extras
except: psycopg2=None
try: import pandas as pd
except: pd=None
from colors import get_colors
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
  if not cur.fetchone():
   cur.execute("INSERT INTO users VALUES('05344851045','05344851045','admin2024','super',1)")
  else:
   cur.execute("UPDATE users SET password='admin2024', active=1, username='05344851045' WHERE phone='05344851045'")
  c.commit();cur.close();return
 for q in qs:c.execute(q)
 for t,col in [("dish_ips","name"),("dish_ips","network"),("dish_ips","tower"),("ledger","amount"),("ledger","currency")]:
  try:c.execute(f"SELECT {col} FROM {t} LIMIT 1")
  except:
   try:c.execute(f"ALTER TABLE {t} ADD COLUMN {col} TEXT");c.commit()
   except:pass
 if not c.execute("SELECT 1 FROM users WHERE phone='05344851045'").fetchone():
  c.execute("INSERT INTO users VALUES('05344851045','05344851045','admin2024','super',1)")
 else:
  c.execute("UPDATE users SET password='admin2024', active=1, username='05344851045' WHERE phone='05344851045'")
 c.commit()
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

TR={"ar":{"":"الرئيسية","subs":"المشتركين","dishes":"الصحون","servers":"السيرفرات","ledger":"دفتر الحسابات","settings":"الإعدادات"},"en":{"":"","subs":"Subscribers","dishes":"Dishes","servers":"Servers","ledger":"Ledger","settings":"Settings"}}
def T(k):
 return TR.get(session.get('lang','ar'),TR['ar']).get(k,k)

CSS="""*{box-sizing:border-box}html{scroll-behavior:smooth}body{font-family:'Segoe UI',Arial;margin:0;background:__BG__;color:__TEXT__;animation:pageIn 1s cubic-bezier(.22,1,.36,1);overflow-x:hidden}body.lb.t{display:none!important}body.lb.drawer{display:none!important}body.lb.wa{display:none!important}body.lb #loader{display:none!important}@keyframes pageIn{from{opacity:0;transform:scale(.98)}to{opacity:1;transform:scale(1)}}@keyframes slowUp{from{opacity:0;transform:translateY(40px) scale(.98)}to{opacity:1;transform:translateY(0) scale(1)}}@keyframes fadeSlow{from{opacity:0}to{opacity:1}}@keyframes logoPulse{0%,100%{transform:scale(1)}50%{transform:scale(1.12)}}.logoA{animation:logoPulse 2s infinite;display:inline-block}body.lb{background:linear-gradient(rgba(4,30,54,.55),rgba(4,30,54,.78)),url('/bg.jpg') center/cover fixed,__BG__;min-height:100vh;display:flex;align-items:center;justify-content:center}.t{background:rgba(10,20,35,.8);backdrop-filter:blur(20px);color:#fff;padding:14px 12px;display:flex;align-items:center;justify-content:space-between;position:fixed;top:0;left:0;right:0;height:56px;z-index:20;border-bottom:2px solid #00D4FF;animation:fadeSlow.8s ease}.m{padding:66px 10px;max-width:1050px;margin:auto}body.lb.m{padding:10px;display:flex;align-items:center;justify-content:center;min-height:100vh}.c{background:rgba(255,255,255,.08);backdrop-filter:blur(14px);border:1px solid rgba(0,212,255,.35);border-radius:20px;padding:18px;margin:12px 0;box-shadow:0 10px 40px rgba(0,0,0,.3);animation:slowUp.9s cubic-bezier(.22,1,.36,1);animation-fill-mode:both;transition:transform.6s cubic-bezier(.22,1,.36,1),box-shadow.6s ease}.c:nth-child(2){animation-delay:.08s}.c:nth-child(3){animation-delay:.16s}.pt{text-align:right;font-weight:bold;font-size:19px;color:#00D4FF;margin:8px 2px}.ic{display:flex;align-items:center;gap:8px}button{background:linear-gradient(135deg,#00D4FF,#0090c8);border:0;padding:12px;width:100%;border-radius:14px;font-weight:bold;cursor:pointer;color:#021;font-size:15px;transition:all.5s cubic-bezier(.22,1,.36,1);box-shadow:0 6px 20px rgba(0,212,255,.25)}button:hover{transform:translateY(-2px);box-shadow:0 12px 35px rgba(0,212,255,.35)}button:active{transform:scale(.96);transition:.15s}input,select{width:100%;padding:12px;margin:6px 0;border-radius:14px;border:1px solid #334155;background:#0f172a;color:#fff;box-sizing:border-box;transition:all.5s ease}input:focus{border-color:#00D4FF;box-shadow:0 0 0 4px rgba(0,212,255,.12);outline:none;transform:translateY(-2px)}.searchB{position:sticky;top:62px;z-index:10;background:rgba(0,212,255,.15);border:1px solid #00D4FF}table{width:100%;border-collapse:separate;border-spacing:0}td,th{padding:9px;border-bottom:1px solid #234;text-align:center;font-size:14px;transition:background.4s ease}th{color:#00D4FF}tr{animation:fadeSlow.8s ease}tr:hover td{background:rgba(0,212,255,.06)}.late{color:#ff5555!important;font-weight:bold}.g4{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.g2{display:grid;grid-template-columns:1fr 1fr;gap:10px}@media(max-width:700px){.g4{grid-template-columns:1fr 1fr}.g2{grid-template-columns:1fr}}.drawer{position:fixed;top:0;right:-320px;width:300px;height:100%;background:__SIDEBAR__;backdrop-filter:blur(25px);z-index:30;transition:right.7s cubic-bezier(.22,1,.36,1);padding:62px 12px;box-shadow:-15px 0 50px rgba(0,0,0,.6)}.drawer.open{right:0}.overlay{position:fixed;inset:0;background:rgba(0,0,0,.55);display:none;z-index:25;transition:opacity.6s ease}.overlay.show{display:block}.drawer a{display:flex;gap:10px;color:#fff;text-decoration:none;padding:13px;border-radius:12px;cursor:pointer;transition:all.5s cubic-bezier(.22,1,.36,1)}.drawer a:hover{background:#123;transform:translateX(-6px)}.drawer.open a{animation:fadeSlow.6s ease backwards}.drawer.open a:nth-child(2){animation-delay:.05s}.drawer.open a:nth-child(3){animation-delay:.1s}.drawer.open a:nth-child(4){animation-delay:.15s}.menuBtn{cursor:pointer;font-size:24px;color:#fff;background:#00D4FF;width:42px;height:42px;display:flex;align-items:center;justify-content:center;border-radius:10px;transition:.4s}.menuBtn:hover{transform:scale(1.08)}body.light{background:#eef6ff!important;color:#102a43!important}body.light.c{background:rgba(255,255,255,.9);color:#102a43}body.light input,body.light select{background:#fff;color:#102a43}.foot{text-align:center;color:#00D4FF;font-weight:bold;margin:18px}.wa{position:fixed;bottom:16px;left:16px;background:#25D366;width:52px;height:52px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:26px;z-index:22;text-decoration:none;transition:all.6s cubic-bezier(.22,1,.36,1)}.wa:hover{transform:scale(1.12) rotate(8deg)}#loader{position:fixed;top:56px;left:0;right:0;height:3px;background:linear-gradient(90deg,#00D4FF,transparent);transform:scaleX(0);transform-origin:right;transition:.25s;z-index:50}#loader.on{transform:scaleX(1)}.ip-small{font-size:11px!important;font-weight:normal!important}.home-search{display:flex;justify-content:flex-start;margin:8px 2px}.home-search input{width:220px;max-width:60%}"""
LAY="""
LAY="""<!DOCTYPE html><html dir=rtl><head><meta charset=UTF-8><meta name=viewport content='width=device-width,initial-scale=1'><title>OMAIA</title><style>"""+CSS+"""</style></head><body class=__BC__><div id=loader></div>
<div class=t><div style=display:flex;gap:10px;align-items:center><div class=menuBtn onclick="document.getElementById('dr').classList.add('open');document.getElementById('ov').classList.add('show')">☰</div><b style=color:#00D4FF><span class=logoA>✨</span> OMAIA ISP</b></div><div style=display:flex;gap:10px;align-items:center><span style=color:#fff;font-size:12px>أهلاً بشركة OMAIA __LANGCUR__</span><div onclick="document.body.classList.toggle('light');localStorage.setItem('th',document.body.classList.contains('light')?'l':'d')" style=cursor:pointer;font-size:22px>🌙</div><a href=/lang/toggle style='color:#fff;text-decoration:none;font-size:20px'>🌐</a></div></div>
<div id=ov class=overlay onclick="document.getElementById('dr').classList.remove('open');this.classList.remove('show')"></div>
<div id=dr class=drawer><a onclick="go('/dash?view=home')">🏠 __HOME__</a><a onclick="go('/dash?view=subs')">👥 __SUBS__</a><a onclick="go('/dash?view=dishes')">📡 __DISHES__</a><a onclick="go('/dash?view=servers')">🖥️ __SERVERS__</a><a onclick="go('/dash?view=ledger')">📒 __LEDGER__</a><a onclick="go('/dash?view=settings')">⚙️ __SETTINGS__</a><a href=/logout>🚪 خروج</a><hr style=border-color:#1e3a5f><a href='https://wa.me/"""+WA_LINK+"""' target=_blank>💬 دعم """+WA_DISPLAY+"""</a></div>
<div class=m id=main>{{c|safe}}<div class=foot> تصميم م.عبدو عباس <br><a href='https://wa.me/"""+WA_LINK+"""' style=color:#00D4FF;text-decoration:none>📞 """+WA_DISPLAY+"""</a></div></div>
<a class=wa href='https://wa.me/"""+WA_LINK+"""' target=_blank>💬</a>
<script>if(localStorage.getItem('th')=='l')document.body.classList.add('light');async function go(u){document.getElementById('dr').classList.remove('open');document.getElementById('ov').classList.remove('show');let l=document.getElementById('loader');l.classList.add('on');try{let r=await fetch(u,{headers:{'X-Requested-With':'fetch'}});let h=await r.text();document.getElementById('main').innerHTML=h+`<div class=foot>💎 تصميم م. عبدو عباس 💎<br><a href='https://wa.me/"""+WA_LINK+"""' style=color:#00D4FF;text-decoration:none>📞 """+WA_DISPLAY+"""</a></div>`;history.pushState(null,'',u);window.scrollTo({top:0,behavior:'smooth'})}catch(e){location.href=u}l.classList.remove('on')}function fS(v){document.querySelectorAll('table tr').forEach((r,i)=>{if(i==0)return;r.style.display=r.innerText.includes(v)?'':'none'});document.querySelectorAll('.g4.c').forEach((el)=>{el.style.display=el.innerText.includes(v)?'':'none'})}function cIP(ip){navigator.clipboard.writeText(ip);alert('تم نسخ '+ip)}</script>
</body></html>"""
def R(h,bc=""):
 s=LAY;co=get_colors()
 for k,v in co.items():s=s.replace("__"+k+"__",v)
 s=s.replace("__HOME__",T("home")).replace("__SUBS__",T("subs")).replace("__DISHES__",T("dishes")).replace("__SERVERS__",T("servers")).replace("__LEDGER__",T("ledger")).replace("__SETTINGS__",T("settings")).replace("__LANGCUR__",session.get('lang','ar').upper()).replace("__BC__",bc)
 if request.headers.get('X-Requested-With')=='fetch':
  return render_template_string(h)
 return render_template_string(s,c=h)
def gv(r):
 try:return list(dict(r).values())[0]
 except:return r[0] if r else 0
def title(t,icon): return f"<div class=pt>{icon} {t}</div>"
@app.route('/',methods=['GET','POST'])
def login():
 if request.method=='POST':
  i=request.form.get('phone','').strip();c=db();u=ex(c,"SELECT * FROM users WHERE phone=? OR username=?",(i,i)).fetchone();d=dict(u) if u else None;close(c)
  if d and d['password']==request.form.get('password') and d['active']:
   session['p']=d['phone'];return redirect('/dash')
  return R("<div class=c style='width:320px;text-align:center'><p style=color:red>خطأ</p><a href=/>رجوع</a></div>","lb")
 return R("<div class=c style='width:330px;text-align:center'><h2 style=color:#00D4FF><span class=logoA>✨</span> OMAIA ISP</h2><form method=post><input name=phone placeholder='رقم هاتف / اسم مستخدم' required><input name=password type=password placeholder='باسورد' required><button>دخول 🚀</button></form><p style=font-size:12px;color:#00D4FF>تصميم م. عبدو عباس</p></div>","lb")
@app.route('/logout')
def lo():session.clear();return redirect('/')
@app.route('/lang/toggle')
def lt():
 cur=session.get('lang','ar')
 session['lang']='en' if cur=='ar' else 'ar'
 session.modified=True
 return redirect(request.referrer or '/dash')
@app.route('/reset')
def reset():
 c=db();ex(c,"UPDATE users SET password='admin2024', active=1 WHERE phone='05344851045'");c.commit();close(c)
 return "تم التصفير: 05344851045 / admin2024"
@app.route('/dash')
def dash():
 if 'p' not in session:return redirect('/')
 v=request.args.get('view','home');c=db();M="#00D4FF"
 def F(h):r=R(h);close(c);return r
 if v=='home':
  ns=gv(ex(c,"SELECT COUNT(*)k FROM subs").fetchone());nd=gv(ex(c,"SELECT COUNT(*)k FROM dish_ips").fetchone());nl=gv(ex(c,"SELECT COUNT(*)k FROM ledger").fetchone());nu=gv(ex(c,"SELECT COUNT(*)k FROM users").fetchone())
  rows=ex(c,"SELECT * FROM dish_ips ORDER BY id DESC").fetchall()
  ip_html="".join(f"<div style='display:flex;justify-content:space-between;align-items:center;padding:9px;border-bottom:1px solid #234;font-size:13px;animation:fadeSlow.6s ease'><span>📛 {dict(x).get('name') or ''} - 📶 {dict(x).get('network') or ''} - 🗼 {dict(x).get('tower') or ''}</span><a href='http://{dict(x).get('ip')}' target=_blank style='color:{M};text-decoration:none' dir=ltr>🌐 {dict(x).get('ip')} ↗</a></div>" for x in rows)
  if not ip_html: ip_html="<p style='text-align:center;color:#888'>لا يوجد صحون بعد</p>"
  return F(title(T("home"),"🏠")+f"""<div class=home-search><input placeholder='🔍 بحث...' oninput=fS(this.value) style='text-align:left'></div><div class=g4><div class=c style=text-align:center><div style=font-size:28px>👥</div><h2 style=color:{M}>{ns}</h2>مشتركين</div><div class=c style=text-align:center><div style=font-size:28px>📡</div><h2 style=color:{M}>{nd}</h2>صحون</div><div class=c style=text-align:center><div style=font-size:28px>📒</div><h2 style=color:{M}>{nl}</h2>قيود</div><div class=c style=text-align:center><div style=font-size:28px>👤</div><h2 style=color:{M}>{nu}</h2>يوزرات</div></div><div class=c><div class=pt>📡 الآيبيات</div>{ip_html}</div>""")
 if v=='subs':
  rows=ex(c,"SELECT * FROM subs ORDER BY id DESC LIMIT 100").fetchall()
  tr="".join(f"<tr><td>{dict(x).get('name')}</td><td>{dict(x).get('phone')}</td><td><a href=/edit_sub/{dict(x)['id']}>✏️</a></td></tr>" for x in rows)
  return F(title(T("subs"),"👥")+f"<div class=c><form method=post action=/add_sub><input name=name placeholder='👤 اسم' required><input name=phone placeholder='📞 هاتف'><button>➕ إضافة</button></form></div><input class=searchB placeholder='🔍 بحث فوري...' oninput=fS(this.value)><div class=c><table><tr><th>اسم</th><th>هاتف</th><th>✏️</th></tr>{tr}</table></div>")
 if v=='dishes':
  rows=ex(c,"SELECT * FROM dish_ips ORDER BY id DESC LIMIT 100").fetchall();tr=""
  for x in rows:
   d=dict(x);ip=d.get('ip') or ''
   tr+=f"<tr style='height:32px'><td dir=ltr style='font-size:11px;padding:4px'><button onclick=cIP('{ip}') style='width:auto;padding:2px 6px;font-size:11px;margin:0'>📋 نسخ</button><br><a href='http://{ip}' target=_blank class=ip-small style=color:{M};text-decoration:none;font-size:11px>🌐 {ip} ↗</a></td><td style='font-size:11px;padding:4px'>📛 {d.get('name') or ''}</td><td style='font-size:11px;padding:4px'>📶 {d.get('network') or ''}</td><td style='font-size:11px;padding:4px'>🗼 {d.get('tower') or ''}</td><td style='font-size:11px;padding:4px'><a href=/edit_dish/{d['id']}>✏️</a> <a href=/del_dish/{d['id']}>🗑️</a></td></tr>"
  return F(title(T("dishes"),"📡")+f"<div class=c><div class=g2><div><div class=ic>🔧 الأساسي</div><form method=post action=/add_dish><input name=ip placeholder='🌐 IP' dir=ltr required><input name=name placeholder='📛 الاسم' required></div><div><div class=ic>📍 الموقع</div><input name=network placeholder='📶 الشبكة'><input name=tower placeholder='🗼 البرج'></div></div><button>➕ إضافة صحن</button></form></div><input class=searchB placeholder='🔍 بحث فوري...' oninput=fS(this.value)><div class=c><table><tr><th>IP</th><th>الاسم</th><th>الشبكة</th><th>البرج</th><th></th></tr>{tr}</table></div>")
 if v=='servers':
  rows=ex(c,"SELECT * FROM servers ORDER BY id DESC LIMIT 100").fetchall();tr=""
  for x in rows:
   d=dict(x);tr+=f"<tr><td>🖥️ {d.get('name')}</td><td dir=ltr><a href='http://{d.get('ip')}' target=_blank style=color:{M}>{d.get('ip')} ↗</a></td><td>📍 {d.get('location','')}</td><td><a href=/edit_server/{d['id']}>✏️</a> <a href=/del_server/{d['id']}>🗑️</a></td></tr>"
  return F(title(T("servers"),"🖥️")+f"<div class=c><form method=post action=/add_server><input name=name placeholder='🖥️ اسم السيرفر' required><input name=ip placeholder='🌐 IP' dir=ltr required><input name=location placeholder='📍 الموقع'><button>➕ إضافة سيرفر</button></form></div><input class=searchB placeholder='🔍 بحث فوري...' oninput=fS(this.value)><div class=c><table><tr><th>الاسم</th><th>IP</th><th>الموقع</th><th>تحكم</th></tr>{tr}</table></div>")
 if v=='ledger':
  rows=ex(c,"SELECT * FROM ledger ORDER BY id DESC LIMIT 100").fetchall();tr=""
  for x in rows:
   d=dict(x);cur=d.get('currency','USD') or 'USD';late=""
   try:
    dd=datetime.strptime(d.get('date')[:10],'%Y-%m-%d')
    if (datetime.now()-dd).days>30:late="class=late"
   except:pass
   tr+=f"<tr><td {late}>{d.get('date')}</td><td>{d.get('sub')}</td><td>{d.get('amount')} {'💵 $' if cur=='USD' else '💶 ل.س'}</td><td>{d.get('note','')}</td><td><a href=/edit_ledger/{d['id']}>✏️</a> <a href=/del_ledger/{d['id']}>🗑️</a></td></tr>"
  return F(title("دفتر الحسابات","📒")+f"""<div class=c><form method=post action=/add_ledger><input name=sub placeholder='👤 الاسم' required><div style=display:flex;gap:6px><input name=amount type=number step=0.01 placeholder='💰 المبلغ' required><button type=button onclick="let s=document.getElementById('cur');s.value=s.value=='USD'?'SYR':'USD';this.textContent=s.value=='USD'?'💵 $':'💶 ل.س'" style=width:110px>💵 $</button><input type=hidden name=currency id=cur value=USD></div><input name=note placeholder='📝 ملاحظة'><button>💾 حفظ</button></form></div><input class=searchB placeholder='🔍 بحث فوري...' oninput=fS(this.value)><div class=c><table><tr><th>تاريخ</th><th>اسم</th><th>مبلغ</th><th>ملاحظة</th><th>تحكم</th></tr>{tr}</table></div>""")
 if v=='settings':
  us=ex(c,"SELECT * FROM users LIMIT 100").fetchall()
  tr="".join(f"<tr><td dir=ltr>👤 {dict(x).get('username')}</td><td><a href=/edit_user/{dict(x)['phone']}>✏️</a> <a href=/toggle_user/{dict(x)['phone']}>🔄</a></td></tr>" for x in us)
  return F(title("الإعدادات","⚙️")+f"<div class=c><div class=ic>🌐 اللغة</div><div class=g2><a href=/lang/toggle><button>🔄 تبديل AR / EN</button></a><a href='https://wa.me/{WA_LINK}' target=_blank><button style=background:#25D366>💬 واتساب {WA_DISPLAY}</button></a></div><p>اللغة الحالية: {session.get('lang','ar').upper()}</p></div><div class=c><div class=ic>👥 اليوزرات</div><form method=post action=/add_user><input name=ident placeholder='📱 هاتف / مستخدم' required><input name=password placeholder='🔑 باسورد' required><button>➕ إضافة يوزر</button></form><table>{tr}</table></div>")
 return F("")
@app.route('/add_sub',methods=['POST'])
def a1():c=db();ex(c,"INSERT INTO subs(name,phone,status)VALUES(?,?,'active')",(request.form.get('name'),request.form.get('phone')));c.commit();close(c);return redirect('/dash?view=subs')
@app.route('/edit_sub/<int:i>',methods=['GET','POST'])
def e1(i):
 c=db()
 if request.method=='POST':ex(c,"UPDATE subs SET name=?,phone=? WHERE id=?",(request.form.get('name'),request.form.get('phone'),i));c.commit();close(c);return redirect('/dash?view=subs')
 r=dict(ex(c,"SELECT * FROM subs WHERE id=?",(i,)).fetchone());close(c)
 return R(title("تعديل مشترك","✏️")+f"<div class=c><form method=post><input name=name value='{r['name']}'><input name=phone value='{r['phone']}'><button>💾 حفظ</button></form></div>")
@app.route('/add_dish',methods=['POST'])
def a2():c=db();ex(c,"INSERT INTO dish_ips(ip,name,network,tower)VALUES(?,?,?,?)",(request.form.get('ip'),request.form.get('name'),request.form.get('network'),request.form.get('tower')));c.commit();close(c);return redirect('/dash?view=dishes')
@app.route('/del_dish/<int:i>')
def d2(i):c=db();ex(c,"DELETE FROM dish_ips WHERE id=?",(i,));c.commit();close(c);return redirect('/dash?view=dishes')
@app.route('/edit_dish/<int:i>',methods=['GET','POST'])
def ed(i):
 c=db()
 if request.method=='POST':
  ex(c,"UPDATE dish_ips SET ip=?,name=?,network=?,tower=? WHERE id=?",(request.form.get('ip'),request.form.get('name'),request.form.get('network'),request.form.get('tower'),i));c.commit();close(c);return redirect('/dash?view=dishes')
 r=dict(ex(c,"SELECT * FROM dish_ips WHERE id=?",(i,)).fetchone());close(c)
 return R(title("تعديل صحن","✏️")+f"<div class=c><form method=post><input name=ip value='{r.get('ip','')}' dir=ltr required><input name=name value='{r.get('name') or ''}' placeholder='📛 الاسم'><input name=network value='{r.get('network') or ''}' placeholder='📶 الشبكة'><input name=tower value='{r.get('tower') or ''}' placeholder='🗼 البرج'><button>💾 حفظ</button></form></div>")
@app.route('/add_server',methods=['POST'])
def asv():c=db();ex(c,"INSERT INTO servers(name,ip,location)VALUES(?,?,?)",(request.form.get('name'),request.form.get('ip'),request.form.get('location','')));c.commit();close(c);return redirect('/dash?view=servers')
@app.route('/edit_server/<int:i>',methods=['GET','POST'])
def esv(i):
 c=db()
 if request.method=='POST':ex(c,"UPDATE servers SET name=?,ip=?,location=? WHERE id=?",(request.form.get('name'),request.form.get('ip'),request.form.get('location',''),i));c.commit();close(c);return redirect('/dash?view=servers')
 r=dict(ex(c,"SELECT * FROM servers WHERE id=?",(i,)).fetchone());close(c)
 return R(title("تعديل سيرفر","✏️")+f"<div class=c><form method=post><input name=name value='{r.get('name','')}' required><input name=ip value='{r.get('ip','')}' dir=ltr required><input name=location value='{r.get('location','')}'><button>💾 حفظ</button></form></div>")
@app.route('/del_server/<int:i>')
def dsv(i):c=db();ex(c,"DELETE FROM servers WHERE id=?",(i,));c.commit();close(c);return redirect('/dash?view=servers')
@app.route('/add_ledger',methods=['POST'])
def a3():c=db();d=datetime.now().strftime('%Y-%m-%d %H:%M');ex(c,"INSERT INTO ledger(date,sub,amount,currency,note)VALUES(?,?,?,?,?)",(d,request.form.get('sub'),float(request.form.get('amount') or 0),request.form.get('currency','USD'),request.form.get('note')));c.commit();close(c);return redirect('/dash?view=ledger')
@app.route('/edit_ledger/<int:i>',methods=['GET','POST'])
def el(i):
 c=db()
 if request.method=='POST':ex(c,"UPDATE ledger SET sub=?,amount=?,currency=?,note=? WHERE id=?",(request.form.get('sub'),float(request.form.get('amount') or 0),request.form.get('currency'),request.form.get('note'),i));c.commit();close(c);return redirect('/dash?view=ledger')
 r=dict(ex(c,"SELECT * FROM ledger WHERE id=?",(i,)).fetchone());close(c);cur=r.get('currency','USD') or 'USD';lbl='💵 $' if cur=='USD' else '💶 ل.س'
 return R(f"<div class=c><form method=post><input name=sub value='{r.get('sub','')}'><div style=display:flex;gap:6px><input name=amount type=number step=0.01 value='{r.get('amount') or 0}'><button type=button onclick=\"let s=document.getElementById('cur');s.value=s.value=='USD'?'SYR':'USD';this.textContent=s.value=='USD'?'💵 $':'💶 ل.س'\" style=width:110px>{lbl}</button><input type=hidden name=currency id=cur value={cur}></div><input name=note value='{r.get('note','')}'><button>💾 حفظ</button></form></div>")
@app.route('/del_ledger/<int:i>')
def d3(i):c=db();ex(c,"DELETE FROM ledger WHERE id=?",(i,));c.commit();close(c);return redirect('/dash?view=ledger')
@app.route('/upload_ledger',methods=['POST'])
def u3():
 if not pd:return "ثبت pandas"
 f=request.files.get('file')
 if f:
  df=pd.read_excel(f);c=db()
  for _,r in df.iterrows():ex(c,"INSERT INTO ledger(date,sub,amount,currency,note)VALUES(?,?,?,?,?)",(str(r.get('date','')),str(r.get('sub','')),float(r.get('amount',0) or 0),str(r.get('currency','USD')),str(r.get('note',''))))
  c.commit();close(c)
 return redirect('/dash?view=ledger')
@app.route('/add_user',methods=['POST'])
def a4():
 c=db();i=request.form.get('ident','').strip()
 if i:
  try:ex(c,"INSERT INTO users(phone,username,password,role,active)VALUES(?,?,?,?,1)",(i,i,request.form.get('password'),'tech'));c.commit()
  except:pass
 close(c);return redirect('/dash?view=settings')
@app.route('/edit_user/<p>',methods=['GET','POST'])
def e4(p):
 c=db()
 if request.method=='POST':ni=request.form.get('ident','').strip();ex(c,"UPDATE users SET phone=?,username=?,password=? WHERE phone=?",(ni,ni,request.form.get('password'),p));c.commit();close(c);return redirect('/dash?view=settings')
 u=dict(ex(c,"SELECT * FROM users WHERE phone=?",(p,)).fetchone());close(c)
 return R(f"<div class=c><form method=post><input name=ident value='{u['username']}' required><input name=password value='{u['password']}' required><button>💾 حفظ</button></form></div>")
@app.route('/toggle_user/<p>')
def t4(p):c=db();u=dict(ex(c,"SELECT * FROM users WHERE phone=?",(p,)).fetchone());ex(c,"UPDATE users SET active=? WHERE phone=?",(0 if u['active'] else 1,p));c.commit();close(c);return redirect('/dash?view=settings')
if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.environ.get('PORT',10000)))
