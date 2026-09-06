from flask import Flask, request, redirect, session, Response
from colors import COLORS, logo_html
import os, datetime, json, html, csv, io
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
   cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor);cur.execute(q.replace("?","%s"),a);r=[dict(x) for x in cur.fetchall()];cur.close();return r
  r=[dict(x) for x in c.execute(q,a).fetchall()];cc(c);return r
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
def is_tech(): return session.get('role')=='tech'
def block(): return "⛔ لا يمكنك حذف وتعديل" if is_tech() else None
def init():
 ss=["CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,username TEXT)","CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT)","CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,sub_id INT,amount REAL,typ TEXT,note TEXT,dt TEXT)","CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,lat REAL DEFAULT 0,lng REAL DEFAULT 0)","CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,location TEXT,lat REAL,lng REAL)"]
 if USE_PG: ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
 for s in ss: qexec(s)
 if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)): qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",('05344851045','admin2024','super','admin'))
init()
def dark(): return session.get('theme','light')
def lang(): return session.get('lang','ar')
T={'ar':{'home':'🏠 الرئيسية','subs':'👥 المشتركين','ledger':'📒 دفتر الحسابات','dishes':'📡 الصحون','towers':'🗼 الأبراج','map':'🗺️ الخريطة','users':'⚙️ الإعدادات','logout':'🚪 تسجيل خروج','add':'➕ إضافة','save':'💾 حفظ','edit':'✏️ تعديل','delete':'🗑️ حذف'},'en':{'home':'🏠 Home','subs':'👥 Subscribers','ledger':'📒 Ledger','dishes':'📡 Dishes','towers':'🗼 Towers','map':'🗺️ Map','users':'⚙️ Settings','logout':'🚪 Logout','add':'➕ Add','save':'💾 Save','edit':'✏️ Edit','delete':'🗑️ Delete'}}
def pc(v):
 t=T[lang()];h="";dis="style='opacity:.35;pointer-events:none'" if is_tech() else ""
 if v=='home':
  ns=(qone("SELECT COUNT(*) c FROM subs") or {}).get('c',0);nd=(qone("SELECT COUNT(*) c FROM dish_ips") or {}).get('c',0);nt=(qone("SELECT COUNT(*) c FROM towers") or {}).get('c',0)
  h=f"<div class=grid><div class=kpi style='background:linear-gradient(135deg,#3b82f6,#1e40af)'>👥<br>{ns}<br><small>مشترك</small></div><div class=kpi style='background:linear-gradient(135deg,#22c55e,#15803d)'>📡<br>{nd}<br><small>صحن</small></div><div class=kpi style='background:linear-gradient(135deg,#ef4444,#991b1b)'>🗼<br>{nt}<br><small>برج</small></div></div><a href='https://wa.me/905344851045' target=_blank class=wa>💬 واتساب الدعم الفني: +905344851045</a><div class=card>🖨️ <button onclick='window.print()'>PDF</button> 📊 <a href=/export/subs>Excel مشتركين</a> | <a href=/export/ledger>Excel دفتر</a> | <a href=/export/dishes>Excel صحون</a></div>"
 elif v=='subs':
  rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 200")
  h=f"<div class=card><h3>{t['subs']}</h3><form data-ajax method=post action=/add_sub><input name=name required placeholder='👤 الاسم الكامل'><input name=phone placeholder='📞 رقم الهاتف'><button>{t['add']}</button></form></div>"
  for r in rs: h+=f"<div class=card>👤 {esc(r['name'])} <span style='color:#666'>📞 {esc(r['phone'])}</span> <a href=\"javascript:loadPage('edit_sub_{r['id']}')\" {dis}>{t['edit']}</a> <a href=/del_sub/{r['id']} data-del {dis}>{t['delete']}</a></div>"
 elif v.startswith('edit_sub_'):
  i=v.split('_')[-1];r=qone("SELECT * FROM subs WHERE id=?",(i,)) or {}
  h=f"<div class=card><h3>{t['edit']}</h3><form data-ajax method=post action=/edit_sub/{i}><input name=name value='{esc(r.get('name',''))}'><input name=phone value='{esc(r.get('phone',''))}'><button>{t['save']}</button></form></div>"
 elif v=='ledger':
  rs=qall("SELECT l.*,s.name sname FROM ledger l LEFT JOIN subs s ON s.id=l.sub_id ORDER BY l.id DESC LIMIT 200");ss=qall("SELECT id,name FROM subs LIMIT 200");o="".join([f"<option value='{x['id']}'>👤 {esc(x['name'])}</option>" for x in ss])
  h=f"<div class=card><h3>{t['ledger']}</h3><form data-ajax method=post action=/add_ledger><select name=sub_id><option value='0'>👤 اختر مشترك</option>{o}</select><input name=amount type=number step=0.01 required placeholder='💰 المبلغ'><select name=typ><option>💸 دين</option><option>💵 دفع</option></select><input name=note placeholder='📝 ملاحظة'><button>{t['add']}</button></form><button onclick='window.print()'>🖨️ PDF</button> <a href=/export/ledger>📊 Excel</a></div>"
  for r in rs: h+=f"<div class=card>👤 {esc(r.get('sname',''))} 💰 {r['amount']} {esc(r['typ'])} 📝 {esc(r.get('note',''))} <a href=\"javascript:loadPage('edit_ledger_{r['id']}')\" {dis}>{t['edit']}</a> <a href=/del_ledger/{r['id']} data-del {dis}>{t['delete']}</a></div>"
 elif v.startswith('edit_ledger_'):
  i=v.split('_')[-1];r=qone("SELECT * FROM ledger WHERE id=?",(i,)) or {}
  h=f"<div class=card><form data-ajax method=post action=/edit_ledger/{i}><input name=amount type=number step=0.01 value='{r.get('amount','')}'><input name=note value='{esc(r.get('note',''))}'><button>{t['save']}</button></form></div>"
 elif v=='dishes':
  rs=qall("SELECT * FROM dish_ips ORDER BY id DESC LIMIT 200")
  h=f"<div class=card><h3>{t['dishes']}</h3><form data-ajax method=post action=/add_dish><input name=ip required placeholder='🌐 IP'><input name=location placeholder='📍 اسم الموقع'><input name=lat placeholder='🧭 lat'><input name=lng placeholder='🧭 lng'><button>{t['add']}</button></form><button onclick='window.print()'>🖨️ PDF</button> <a href=/export/dishes>📊 Excel</a></div>"
  for r in rs: h+=f"<div class=card>📡 <a href='http://{esc(r['ip'])}' target=_blank>{esc(r['ip'])}</a> 📍 {esc(r.get('location',''))} <a href=\"javascript:loadPage('edit_dish_{r['id']}')\" {dis}>{t['edit']}</a> <a href=/del_dish/{r['id']} data-del {dis}>{t['delete']}</a></div>"
 elif v.startswith('edit_dish_'):
  i=v.split('_')[-1];r=qone("SELECT * FROM dish_ips WHERE id=?",(i,)) or {}
  h=f"<div class=card><form data-ajax method=post action=/edit_dish/{i}><input name=ip value='{esc(r.get('ip',''))}'><input name=location value='{esc(r.get('location',''))}'><input name=lat value='{r.get('lat','')}'><input name=lng value='{r.get('lng','')}'><button>{t['save']}</button></form></div>"
 elif v=='towers':
  rs=qall("SELECT * FROM towers ORDER BY id DESC LIMIT 200")
  h=f"<div class=card><h3>{t['towers']}</h3><form data-ajax method=post action=/add_tower><input name=name required placeholder='🗼 اسم البرج'><input name=location placeholder='📍 الموقع'><input name=lat placeholder='🧭 احداثي lat'><input name=lng placeholder='🧭 احداثي lng'><button>{t['add']}</button></form></div>"
  for r in rs: h+=f"<div class=card>🗼 {esc(r['name'])} 📍 {esc(r.get('location',''))} <a href=\"javascript:loadPage('edit_tower_{r['id']}')\" {dis}>{t['edit']}</a> <a href=/del_tower/{r['id']} data-del {dis}>{t['delete']}</a></div>"
 elif v.startswith('edit_tower_'):
  i=v.split('_')[-1];r=qone("SELECT * FROM towers WHERE id=?",(i,)) or {}
  h=f"<div class=card><form data-ajax method=post action=/edit_tower/{i}><input name=name value='{esc(r.get('name',''))}'><input name=location value='{esc(r.get('location',''))}'><input name=lat value='{r.get('lat','')}'><input name=lng value='{r.get('lng','')}'><button>{t['save']}</button></form></div>"
 elif v=='map':
  ds=qall("SELECT id,lat,lng,location,ip FROM dish_ips WHERE lat!=0 LIMIT 500");ts=qall("SELECT id,lat,lng,name FROM towers WHERE lat!=0 LIMIT 500")
  dj=json.dumps([{"id":d['id'],"la":float(d.get("lat") or 0),"ln":float(d.get("lng") or 0),"n":str(d.get("location","")),"ip":str(d.get("ip",""))} for d in ds if d.get("lat")]).replace("</","<\\/")
  tj=json.dumps([{"id":x['id'],"la":float(x.get("lat") or 0),"ln":float(x.get("lng") or 0),"n":str(x.get("name",""))} for x in ts if x.get("lat")]).replace("</","<\\/")
  h=f"<div class=card><h3>🗺️ خريطة عالية الوضوح</h3><button onclick='mapAdd()'>📍 ➕ إضافة نقطة</button><div id=mp style='height:75vh;border-radius:12px'></div></div><script>var DS={dj},TS={tj};initMap();</script>"
 elif v=='users':
  us=qall("SELECT phone,username,role FROM users LIMIT 100")
  h="<div class=card><h3>⚙️ الإعدادات</h3><form data-ajax method=post action=/change_pass><input name=newpass type=password required placeholder='🔑 كلمة سر جديدة'><button>💾 حفظ كلمة السر</button></form><form data-ajax method=post action=/change_user><input name=newphone required placeholder='👤 رقم / يوزر جديد'><button>💾 حفظ اليوزر</button></form><hr><h4>👥 إضافة يوزر جديد (غير محدود)</h4><form data-ajax method=post action=/add_user><input name=phone required placeholder='📞 هاتف'><input name=username placeholder='👤 يوزر'><input name=password required placeholder='🔑 باسورد'><select name=role><option value='tech'>🔧 فني</option><option value='manager'>👔 مدير</option><option value='super'>👑 سوبر</option></select><button>➕ إضافة يوزر</button></form>"
  for u in us: h+=f"<div class=card>👤 {esc(u['phone'])} / {esc(u.get('username',''))} - {esc(u.get('role',''))} <a href=/del_user/{esc(u['phone'])} data-del {dis}>🗑️ حذف</a></div>"
  h+="</div>"
 return h
def layout(c,v='home'):
 th=dark();t=T[lang()];bg=COLORS['bg_dark'] if th=='dark' else COLORS['bg_light'];card=COLORS['card_dark'] if th=='dark' else COLORS['card_light'];txt='#fff' if th=='dark' else '#000'
 return f"""<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><link rel=stylesheet href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'><style>*{{box-sizing:border-box}}body{{margin:0;font-family:sans-serif;background:{bg};color:{txt}}}.top{{position:fixed;top:0;left:0;right:0;background:{COLORS['top_bg']};color:#fff;padding:10px;display:flex;justify-content:space-between;align-items:center;z-index:100}}.menu{{position:fixed;top:52px;bottom:0;right:0;width:210px;background:{COLORS['menu_bg']};padding:10px;z-index:99;transition:.25s}}.menu.hide{{transform:translateX(110%)}}.menu a{{display:block;color:#fff;text-decoration:none;padding:12px;border-radius:10px;margin:3px 0}}.menu a:hover{{background:#ffffff22}}.main{{margin-right:220px;margin-top:62px;padding:10px;transition:.25s}}.main.full{{margin-right:0}}.card{{background:{card};padding:11px;border-radius:11px;margin:8px 0}}.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}}.kpi{{padding:14px;border-radius:12px;color:#fff;text-align:center;font-weight:bold}}.wa{{display:block;background:#25D366;color:#fff;padding:13px;text-align:center;border-radius:11px;margin:10px 0;text-decoration:none;font-weight:bold}}input,select{{width:100%;padding:9px;margin:4px 0;border-radius:8px;border:1px solid #ccc}}button{{background:{COLORS['btn']};color:#fff;border:0;padding:9px 13px;border-radius:8px;cursor:pointer}}.tb{{background:#ffffff2e;border:0;color:#fff;padding:7px 11px;border-radius:8px;margin:0 2px}}</style></head><body><div class=top><button class=tb onclick="tg()">☰</button><span>{logo_html()}</span><span><button class=tb onclick="fetch('/toggle_theme').then(()=>location.reload())">🌙</button><button class=tb onclick="fetch('/toggle_lang').then(()=>location.reload())">🌐 {lang()}</button></span></div><div class=menu id=m><a href="javascript:loadPage('home')">{t['home']}</a><a href="javascript:loadPage('subs')">{t['subs']}</a><a href="javascript:loadPage('ledger')">{t['ledger']}</a><a href="javascript:loadPage('dishes')">{t['dishes']}</a><a href="javascript:loadPage('towers')">{t['towers']}</a><a href="javascript:loadPage('map')">{t['map']}</a><a href="javascript:loadPage('users')">{t['users']}</a><a href=/logout>{t['logout']}</a></div><div class=main id=main>{c}</div><script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script><script>var curV='{v}';function tg(){{document.getElementById('m').classList.toggle('hide');document.getElementById('main').classList.toggle('full')}};document.addEventListener('click',e=>{{if(innerWidth<700&&!e.target.closest('#m')&&!e.target.closest('.top'))document.getElementById('m').classList.add('hide')}});window.loadPage=async function(v){{curV=v;var r=await fetch('/api/page?v='+v);document.getElementById('main').innerHTML=await r.text();bindAjax();document.querySelectorAll('#main script').forEach(s=>{{try{{eval(s.textContent)}}catch(e){{}}}});scrollTo(0,0)}};function initMap(){{if(typeof L=='undefined'){{setTimeout(initMap,300);return}}var m=L.map('mp').setView([35.13,36.75],13);L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',{{maxZoom:19}}).addTo(m);L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{opacity:.32}}).addTo(m);DS.forEach(d=>L.marker([d.la,d.ln]).addTo(m).bindPopup('📡 '+d.n+'<br>🌐 '+d.ip+`<br><a href="javascript:loadPage(\\'edit_dish_${{d.id}}\\')">✏️ تعديل</a>`));TS.forEach(x=>L.circleMarker([x.la,x.ln],{{radius:11,color:'#ef4444',fillOpacity:.9}}).addTo(m).bindPopup('🗼 '+x.n));setTimeout(()=>m.invalidateSize(),300);window._m=m}};function mapAdd(){{var m=window._m;alert('📍 اضغط على الخريطة');m.on('click',async e=>{{var n=prompt('📍 اسم النقطة:');if(!n)return;await fetch('/api_add_dish',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{location:n,lat:e.latlng.lat,lng:e.latlng.lng,ip:'0.0.0.0'}})}});loadPage('map')}})}};function bindAjax(){{document.querySelectorAll('form[data-ajax]').forEach(f=>{{f.onsubmit=async e=>{{e.preventDefault();var r=await fetch(f.action,{{method:'POST',body:new FormData(f)}});var x=await r.text();if(x.includes('لا يمكنك'))alert(x);loadPage(curV)}}}});document.querySelectorAll('a[data-del]').forEach(a=>{{a.onclick=async e=>{{e.preventDefault();if(!confirm('🗑️ حذف؟'))return;var r=await fetch(a.href);if((await r.text()).includes('لا يمكنك')){{alert('⛔ لا يمكنك حذف وتعديل');return}}loadPage(curV)}}}})}};bindAjax();</script></body></html>"""
@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')
@app.route('/login',methods=['GET','POST'])
def login():
 if request.method=='POST':
  uin=request.form.get('userin','').strip();u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
  if u and u['password']==request.form.get('password',''): session['phone']=u['phone'];session['role']=u['role'];return "ok"
  return "err"
 return f"""<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><style>body{{display:flex;align-items:center;justify-content:center;background:{COLORS['bg_dark']};min-height:100vh;margin:0;font-family:sans-serif}}.b{{background:#fff;padding:22px;border-radius:14px;width:92%;max-width:340px;animation:a.25s}}@keyframes a{{from{{transform:scale(.92);opacity:0}}}}input{{width:100%;padding:11px;margin:6px 0;border-radius:9px;border:1px solid #ccc}}button{{width:100%;background:{COLORS['btn']};color:#fff;padding:11px;border:0;border-radius:9px;font-weight:bold}}</style></head><body><div class=b><h3 style='text-align:center'>{logo_html()}</h3><form id=f method=post><input name=userin placeholder='👤 رقم / يوزر' required><input name=password type=password placeholder='🔑 كلمة السر' required><button>⚡ دخول سريع</button></form></div><script>document.getElementById('f').onsubmit=async e=>{{e.preventDefault();var r=await fetch('/login',{{method:'POST',body:new FormData(e.target)}});if(await r.text()=='ok')location.href='/dash';else alert('❌ خطأ بالدخول')}};</script></body></html>"""
@app.route('/logout')
def lo(): session.clear();return redirect('/login')
@app.route('/dash')
def dash():
 if not session.get('phone'): return redirect('/login')
 v=request.args.get('v','home');return layout(pc(v),v)
@app.route('/api/page')
def ap():
 if not session.get('phone'): return "login"
 return pc(request.args.get('v','home'))
@app.route('/toggle_theme')
def tt(): session['theme']='dark' if dark()!='dark' else 'light';return "ok"
@app.route('/toggle_lang')
def tl(): session['lang']='en' if lang()!='en' else 'ar';return "ok"
@app.route('/api_add_dish',methods=['POST'])
def ad(): d=request.get_json(force=True);qexec("INSERT INTO dish_ips(ip,location,lat,lng) VALUES(?,?,?,?)",(d.get('ip','0.0.0.0'),d.get('location',''),fnum(d.get('lat')),fnum(d.get('lng'))));return "ok"
def ce(rows,hd):
 s=io.StringIO();w=csv.writer(s);w.writerow(hd)
 for r in rows: w.writerow([r.get(k,'') for k in hd])
 return Response(s.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment;filename=export.csv'})
@app.route('/export/subs')
def e1(): return ce(qall("SELECT * FROM subs"),['id','name','phone'])
@app.route('/export/ledger')
def e2(): return ce(qall("SELECT * FROM ledger"),['id','sub_id','amount','typ','note'])
@app.route('/export/dishes')
def e3(): return ce(qall("SELECT * FROM dish_ips"),['id','ip','location','lat','lng'])
@app.route('/add_sub',methods=['POST'])
def s1(): qexec("INSERT INTO subs(name,phone) VALUES(?,?)",(request.form.get('name',''),request.form.get('phone','')));return "ok"
@app.route('/edit_sub/<int:i>',methods=['POST'])
def s2(i):
 x=block();return x if x else (qexec("UPDATE subs SET name=?,phone=? WHERE id=?",(request.form.get('name',''),request.form.get('phone',''),i)),"ok")[1]
@app.route('/del_sub/<int:i>')
def s3(i):
 x=block();return x if x else (qexec("DELETE FROM subs WHERE id=?",(i,)),"ok")[1]
@app.route('/add_ledger',methods=['POST'])
def l1(): f=request.form;qexec("INSERT INTO ledger(sub_id,amount,typ,note,dt) VALUES(?,?,?,?,?)",(int(f.get('sub_id') or 0),fnum(f.get('amount')),f.get('typ','دين'),f.get('note',''),datetime.datetime.now().isoformat()));return "ok"
@app.route('/edit_ledger/<int:i>',methods=['POST'])
def l2(i):
 x=block();return x if x else (qexec("UPDATE ledger SET amount=?,note=? WHERE id=?",(fnum(request.form.get('amount')),request.form.get('note',''),i)),"ok")[1]
@app.route('/del_ledger/<int:i>')
def l3(i):
 x=block();return x if x else (qexec("DELETE FROM ledger WHERE id=?",(i,)),"ok")[1]
@app.route('/add_dish',methods=['POST'])
def d1(): f=request.form;qexec("INSERT INTO dish_ips(ip,location,lat,lng) VALUES(?,?,?,?)",(f.get('ip',''),f.get('location',''),fnum(f.get('lat')),fnum(f.get('lng'))));return "ok"
@app.route('/edit_dish/<int:i>',methods=['POST'])
def d2(i):
 x=block();return x if x else (qexec("UPDATE dish_ips SET ip=?,location=?,lat=?,lng=? WHERE id=?",(request.form.get('ip',''),request.form.get('location',''),fnum(request.form.get('lat')),fnum(request.form.get('lng')),i)),"ok")[1]
@app.route('/del_dish/<int:i>')
def d3(i):
 x=block();return x if x else (qexec("DELETE FROM dish_ips WHERE id=?",(i,)),"ok")[1]
@app.route('/add_tower',methods=['POST'])
def t1(): f=request.form;qexec("INSERT INTO towers(name,location,lat,lng) VALUES(?,?,?,?)",(f.get('name',''),f.get('location',''),fnum(f.get('lat')),fnum(f.get('lng'))));return "ok"
@app.route('/edit_tower/<int:i>',methods=['POST'])
def t2(i):
 x=block();return x if x else (qexec("UPDATE towers SET name=?,location=?,lat=?,lng=? WHERE id=?",(request.form.get('name',''),request.form.get('location',''),fnum(request.form.get('lat')),fnum(request.form.get('lng')),i)),"ok")[1]
@app.route('/del_tower/<int:i>')
def t3(i):
 x=block();return x if x else (qexec("DELETE FROM towers WHERE id=?",(i,)),"ok")[1]
@app.route('/add_user',methods=['POST'])
def u1(): f=request.form;qexec("INSERT INTO users(phone,username,password,role) VALUES(?,?,?,?)",(f.get('phone',''),f.get('username',''),f.get('password',''),f.get('role','tech')));return "ok"
@app.route('/del_user/<p>')
def u2(p):
 x=block();return x if x else (qexec("DELETE FROM users WHERE phone=?",(p,)),"ok")[1]
@app.route('/change_user',methods=['POST'])
def c1():
 o=session.get('phone');n=request.form.get('newphone','').strip()
 qexec("UPDATE users SET phone=? WHERE phone=?",(n,o)) if n.isdigit() else qexec("UPDATE users SET username=? WHERE phone=?",(n,o))
 if n.isdigit(): session['phone']=n
 return "ok"
@app.route('/change_pass',methods=['POST'])
def c2(): qexec("UPDATE users SET password=? WHERE phone=?",(request.form.get('newpass',''),session.get('phone')));return "ok"
if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
