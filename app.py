from flask import Flask, request, redirect, render_template_string, session, Response
import os, datetime, io, csv, time, socket
try: import psycopg2, psycopg2.extras
except: psycopg2=None
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from colors import get_colors, get_bg_css, get_menu_css, get_logo_html
app = Flask(__name__, static_folder='static')
app.config['SEND_FILE_MAX_AGE_DEFAULT']=86400
app.secret_key=os.environ.get("SECRET_KEY","omia-sec-2026")
DATABASE_URL=os.environ.get("DATABASE_URL","")
USE_PG=bool(DATABASE_URL and psycopg2)
_pg=None;_pt=0
SUPPORT="905344851045"
SUPPORT_DISPLAY="+905344851045"
_cache_data={};_cache_time={}
def cached_view(k,s=60):
 now=time.time()
 if k in _cache_data and now-_cache_time.get(k,0)<s: return _cache_data[k]
 return None
def set_cache(k,h):
 _cache_data[k]=h;_cache_time[k]=time.time()
LANGS={'ar':{'home':'🏠 الرئيسية','subs':'👥 المشتركين','dishes':'📡 الصحون','map':'🗺️ الخريطة','ping':'📶 فحص','towers':'🗼 الأبراج','report':'📊 تقرير','notifs':'🔔 إشعارات','logs':'📝 السجل','settings':'⚙️ الإعدادات','support':'🛠️ دعم','ledger':'📒 الحسابات','logout':'🚪 خروج','menu':'☰ القائمة'},'en':{'home':'🏠 Home','subs':'👥 Subs','dishes':'📡 Dishes','map':'🗺️ Map','ping':'📶 Ping','towers':'🗼 Towers','report':'📊 Report','notifs':'🔔 Notifs','logs':'📝 Logs','settings':'⚙️ Settings','support':'🛠️ Support','ledger':'📒 Ledger','logout':'🚪 Logout','menu':'☰ Menu'}}
def T(k): return LANGS.get(session.get('lang','ar'),{}).get(k,k)
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
 ss=["CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,username TEXT,password TEXT,role TEXT,active INT DEFAULT 1)","CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,status TEXT,balance_usd REAL DEFAULT 0,balance_syr REAL DEFAULT 0)","CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,site TEXT,area TEXT,tower TEXT,lat REAL DEFAULT 0,lng REAL DEFAULT 0)","CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,lat REAL,lng REAL,note TEXT)","CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,sub_id INT,date TEXT,usd REAL,syr REAL,type TEXT,note TEXT,by_user TEXT)","CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,msg TEXT,date TEXT,seen INT DEFAULT 0)","CREATE TABLE IF NOT EXISTS login_logs(id INTEGER PRIMARY KEY AUTOINCREMENT,phone TEXT,date TEXT,ip TEXT)"]
 if USE_PG:ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
 if USE_PG:
  cur=c.cursor()
  for s in ss:cur.execute(s)
  cur.execute("SELECT * FROM users WHERE phone='05344851045'")
  if not cur.fetchone():cur.execute("INSERT INTO users(phone,username,password,role,active) VALUES('05344851045','05344851045','admin2024','super',1)")
  for col in ["area TEXT","location TEXT","owner TEXT"]:
   try:cur.execute(f"ALTER TABLE towers ADD COLUMN {col}")
   except:pass
  for idx in ["CREATE INDEX IF NOT EXISTS ix_subs_name ON subs(name)","CREATE INDEX IF NOT EXISTS ix_ledger_date ON ledger(date)","CREATE INDEX IF NOT EXISTS ix_dish_ip ON dish_ips(ip)"]:
   try:cur.execute(idx)
   except:pass
  c.commit();cur.close()
 else:
  for s in ss:c.execute(s)
  if not c.execute("SELECT * FROM users WHERE phone='05344851045'").fetchone():c.execute("INSERT INTO users(phone,username,password,role,active) VALUES('05344851045','05344851045','admin2024','super',1)")
  for col in ["area TEXT","location TEXT","owner TEXT"]:
   try:c.execute(f"ALTER TABLE towers ADD COLUMN {col}")
   except:pass
  for idx in ["CREATE INDEX IF NOT EXISTS ix_subs_name ON subs(name)","CREATE INDEX IF NOT EXISTS ix_ledger_date ON ledger(date)","CREATE INDEX IF NOT EXISTS ix_dish_ip ON dish_ips(ip)"]:
   try:c.execute(idx)
   except:pass
  c.commit();cc(c)
init()
def ping_one(ip):
 ip=(ip or '').strip()
 if not ip:return False
 for p in (80,443):
  try:
   s=socket.create_connection((ip,p),timeout=0.8);s.close();return True
  except:continue
 return False
def get_view_html(v,c,role):
 if v=='home':
  col=get_colors()
  def cnt(t):
   r=ex(c,f"SELECT COUNT(*) as c FROM {t}").fetchone()
   try:return dict(r)['c']
   except:return r[0]
  ns=cnt("subs");nd=cnt("dish_ips");nt=cnt("towers")
  today=datetime.date.today().isoformat()
  r1=ex(c,"SELECT SUM(usd) s1 FROM ledger WHERE date LIKE?",(today+"%",)).fetchone();inc=(dict(r1).get('s1') or 0) if r1 else 0
  r=ex(c,"SELECT COUNT(*) as c FROM users WHERE active=0").fetchone()
  disabled=dict(r)['c'] if r else 0
  try:
   r=ex(c,"SELECT COUNT(DISTINCT phone) as c FROM login_logs WHERE date LIKE?",(today+"%",)).fetchone()
   online=dict(r)['c'] if USE_PG else r[0]
  except: online=0
  def icard(key, emoji, title, val):
   bg=col.get(key,'#333')
   return f"""<div style="background:{bg};border-radius:12px;padding:12px 6px;color:#fff;text-align:center;min-height:130px;display:flex;flex-direction:column;justify-content:center;box-shadow:0 2px 8px {bg}44"><div style="font-size:20px">{emoji}</div><div style="font-weight:700;margin:4px 0;font-size:11px">{title}</div><div style="font-size:20px;font-weight:800">{val}</div></div>"""
  return f"""<div class="card eye" style="text-align:center"><h2>👋 أهلاً بك</h2><p>📅 {today} | 💰 دخل اليوم: <b>{inc}$</b></p></div><div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:8px;margin:10px 0">{icard('icon_ip','📡','عدد IP',nd)}{icard('icon_disabled','⏸️','تم تعطيلهم',disabled)}{icard('icon_online','🟢','فاتحين الموقع',online)}{icard('icon_active','📶','المتصلين',ns)}{icard('icon_monqatein','❄️','المنقطعين',0)}{icard('icon_modirin','👔','المديرين',0)}{icard('icon_no_expire','⏸️','تم إيقافهم',0)}{icard('icon_expired','🔴','انتهى اشتراكهم',0)}{icard('icon_blocked','🚫','محظور',0)}</div>"""
 if v=='subs':
  rs=ex(c,"SELECT * FROM subs ORDER BY id DESC LIMIT 50").fetchall()
  tr="".join([f"<tr><td>{r['name']}</td><td dir=ltr>{r['phone']}</td><td>{r['balance_usd']}$</td><td><a class='ic' href='https://wa.me/{r['phone']}' target=_blank>💬</a></td><td><a class='ic del' href='/del_sub/{r['id']}'>✖</a></td></tr>" for r in rs])
  return f"<div class='card eye'><form method=post action=/add_sub><div class=row2><input name=name placeholder='الاسم' required><input name=phone placeholder='هاتف' required></div><button class='btn-soft'>إضافة مشترك</button></form></div><div class='card eye'><table><tr><th>اسم</th><th>هاتف</th><th>رصيد</th><th></th><th></th></tr>{tr}</table></div>"
 if v=='dishes':
  rs=ex(c,"SELECT * FROM dish_ips ORDER BY id DESC LIMIT 100").fetchall()
  tr="".join([f"<tr><td dir=ltr><a href='http://{dict(r)['ip']}' target='_blank' style='color:#4da3ff;text-decoration:underline'>{dict(r)['ip'] or '-'}</a></td><td>{dict(r).get('location','')}</td><td>{dict(r).get('area','')}</td><td><a class='ic del' href='/del_dish/{dict(r)['id']}'>✖</a></td></tr>" for r in rs])
  return f"<div class='card eye'><h3>📡 الصحون</h3><form method=post action=/add_dish><div class=row2><input name=ip placeholder='IP' dir=ltr><input name=location placeholder='اسم الصحن'></div><div class=row2><input name=area placeholder='المنطقة'><input name=tower placeholder='البرج'></div><div class=row2><input name=lat placeholder='Lat' type=number step=any><input name=lng placeholder='Lng' type=number step=any></div><button class='btn-soft'>إضافة</button></form></div><div class='card eye'><table><tr><th>IP</th><th>اسم</th><th>منطقة</th><th></th></tr>{tr}</table></div>"
 if v=='ping':
  rs=ex(c,"SELECT * FROM dish_ips ORDER BY id DESC LIMIT 10").fetchall()
  ips=[dict(r) for r in rs]
  with ThreadPoolExecutor(max_workers=5) as exx:
   results=list(exx.map(ping_one,[d.get('ip','') for d in ips]))
  tr="".join([f"<tr><td>{'🟢' if ok else '🔴'}</td><td dir=ltr>{d.get('ip','')}</td><td>{d.get('location','')}</td></tr>" for d,ok in zip(ips,results)])
  return f"<div class='card eye'><h3>📶 فحص Ping</h3><button class='btn-soft' onclick=\"loadView('ping',true)\">🔄 فحص الآن</button></div><div class='card eye'><table><tr><th>حالة</th><th>IP</th><th>اسم</th></tr>{tr}</table></div>"
 if v=='towers':
  rs=ex(c,"SELECT * FROM towers ORDER BY id DESC LIMIT 100").fetchall()
  tr="".join([f"<tr><td>{dict(r).get('name','')}</td><td>{dict(r).get('area','') or ''}</td><td>{dict(r).get('owner','') or ''}</td><td>{dict(r).get('lat',0)},{dict(r).get('lng',0)}</td><td><a class='ic del' href='/del_tower/{dict(r)['id']}'>✖</a></td></tr>" for r in rs])
  return f"<div class='card eye'><h3>🗼 إضافة برج مع إحداثيات</h3><form method=post action=/add_tower><input name=name placeholder='اسم برج - مثال: برج حمص' required><div class=row2><input name=area placeholder='منطقه'><input name=owner placeholder='لمين برج'></div><div class=row2><input name=lat placeholder='Lat 34.72' type=number step=any required><input name=lng placeholder='Lng 36.72' type=number step=any required></div><input name=location placeholder='موقع برج'><button class='btn-soft'>📍 حفظ البرج مع الموقع</button></form></div><div class='card eye'><table><tr><th>اسم</th><th>منطقه</th><th>لمين</th><th>إحداثيات</th><th></th></tr>{tr}</table></div>"
 if v=='map':
  dishes=ex(c,"SELECT location,lat,lng FROM dish_ips WHERE lat!=0 LIMIT 200").fetchall()
  towers=ex(c,"SELECT name,lat,lng FROM towers WHERE lat!=0 LIMIT 200").fetchall()
  pts=",".join([f"{{n:'📡 {r['location']}',la:{r['lat']},ln:{r['lng']}}}" for r in dishes])
  pts2=",".join([f"{{n:'🗼 {r['name']}',la:{r['lat']},ln:{r['lng']}}}" for r in towers])
  allpts=(pts+","+pts2).strip(",")
  return f"<link rel='stylesheet' href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'><div class='card eye'><h3>🗺️ الخريطة</h3><div id=map style='height:400px'></div></div><script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script><script>var m=L.map('map').setView([34.72,36.72],11);L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png').addTo(m);var pts=[{allpts}];pts.forEach(p=>L.marker([p.la,p.ln]).addTo(m).bindPopup(p.n));setTimeout(()=>m.invalidateSize(),600);</script>"
 if v=='ledger':
  if role not in ('super','admin'):return "<div class='card eye'>ممنوع</div>"
  rs=ex(c,"SELECT * FROM ledger ORDER BY id DESC LIMIT 100").fetchall()
  tr="".join([f"<tr><td>{dict(r)['date']}</td><td>{dict(r).get('note','')}</td><td>{dict(r).get('usd',0)}$</td><td>{dict(r).get('syr',0)}</td></tr>" for r in rs])
  return f"<div class='card eye'><h3>📒 دفتر حسابات</h3><form method=post action=/charge><input name=cust_name placeholder='اسم الزبون' required><div class=row2><input name=amount type=number step=0.01 required placeholder='مبلغ'><select name=currency><option value=usd>$ دولار</option><option value=syr>ل.س سوري</option></select></div><button class='btn-soft'>➕ إضافة</button></form></div><div class='card eye'><table><tr><th>تاريخ</th><th>الاسم</th><th>$</th><th>ل.س</th></tr>{tr}</table></div>"
 if v=='report':
  today=datetime.date.today().isoformat()
  r1=ex(c,"SELECT SUM(usd) s1 FROM ledger WHERE date LIKE?",(today+"%",)).fetchone();a=dict(r1) if r1 else {}
  return f"<div class='card eye'><h3>📊 تقرير</h3><p>اليوم: {a.get('s1') or 0}$</p></div>"
 if v=='notifs':
  rs=ex(c,"SELECT * FROM notifications ORDER BY id DESC LIMIT 50").fetchall();ex(c,"UPDATE notifications SET seen=1");c.commit()
  t="".join([f"<div class='card eye'>🔔 {r['msg']}<br><small>{r['date']}</small></div>" for r in rs])
  return f"<h3>🔔 إشعارات</h3>{t}"
 if v=='logs':
  rs=ex(c,"SELECT * FROM login_logs ORDER BY id DESC LIMIT 50").fetchall()
  tr="".join([f"<tr><td>{r['phone']}</td><td>{r['date']}</td></tr>" for r in rs])
  return f"<div class='card eye'><h3>📝 سجل الدخول</h3><table><tr><th>مستخدم</th><th>وقت</th></tr>{tr}</table></div>"
 if v=='settings':
  us=ex(c,"SELECT * FROM users LIMIT 100").fetchall();cards=""
  for u in us:
   d=dict(u);active=d['active']==1
   stt="<span class='badge green'>نشط</span>" if active else "<span class='badge gray'>معطل</span>"
   bt="تعطيل" if active else "تفعيل"
   cards+=f"<div class='ucard'><b dir=ltr>{d['phone']}</b><div style='margin:5px 0'>الدور: <b>{d['role']}</b></div><div>الحالة: {stt}</div><div class='ubtns'><a class='mini-btn blue' href='#' onclick=\"document.getElementById('e{d['phone']}').style.display='flex';return false\">تعديل</a><a class='mini-btn orange' href='/toggle_user/{d['phone']}'>{bt}</a><a class='mini-btn red' href='/del_user/{d['phone']}'>حذف</a></div><div id='e{d['phone']}' class='modal' style='display:none'><form method=post action='/edit_user/{d['phone']}' class='modal-box'><h4 dir=ltr>{d['phone']}</h4><input name=password value='{d['password']}' required><select name=role><option value='tech' {'selected' if d['role']=='tech' else ''}>فني</option><option value='admin' {'selected' if d['role']=='admin' else ''}>مدير</option><option value='distributor' {'selected' if d['role']=='distributor' else ''}>موزع</option></select><div class=row2><button class='mini-btn blue'>حفظ</button><button type=button class='mini-btn gray' onclick=\"document.getElementById('e{d['phone']}').style.display='none'\">إلغاء</button></div></form></div></div>"
  return f"<style>.u-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}}.ucard{{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.08);border-radius:14px;padding:10px;text-align:center;font-size:10px}}.badge{{font-size:9px!important;padding:2px 8px;border-radius:20px;color:#fff}}.badge.green{{background:#22c55e}}.badge.gray{{background:#6b7280}}.ubtns{{display:flex;gap:4px;justify-content:center;margin-top:7px;flex-wrap:wrap}}.mini-btn{{font-size:10px!important;padding:5px 9px!important;border-radius:8px;text-decoration:none;color:#fff;font-weight:700;display:inline-block}}.mini-btn.blue{{background:#3b82f6}}.mini-btn.orange{{background:#f59e0b}}.mini-btn.red{{background:#ef4444}}.mini-btn.gray{{background:#6b7280}}.modal{{position:fixed;top:0;right:0;left:0;bottom:0;background:rgba(0,0,0,.6);z-index:2000;align-items:center;justify-content:center}}.modal-box{{background:#1a2332;padding:14px;border-radius:14px;width:90%;max-width:300px}}</style><div class='card eye' style='text-align:center'><h3>⚙️ الإعدادات</h3></div><div class='card eye'><h3>⚙️ إضافة مستخدم</h3><form method=post action=/add_user><input name=phone placeholder='رقم الهاتف' required dir=ltr><div class=row2><input name=password placeholder='كلمة السر' required><select name=role><option value='tech'>فني</option><option value='admin'>مدير</option><option value='distributor'>موزع</option></select></div><button class='btn-soft'>+ إضافة</button></form></div><div class='u-grid'>{cards}</div>"
 if v=='support': return f"<div class='card eye' style='text-align:center'><h3>🛠️ الدعم</h3><a href='https://wa.me/{SUPPORT}' target='_blank' style='color:#4da3ff;text-decoration:underline'><h2 dir=ltr>{SUPPORT_DISPLAY} 💬</h2></a></div>"
 return ""
def base_html(content,curview):
 col=get_colors();role=session.get('role','tech');lang=session.get('lang','ar');is_ar=lang=='ar'
 ledger_link=f'<a href="#" data-v="ledger">{T("ledger")}</a>' if role in ('super','admin') else ''
 main_col=col['main'];text_col=col['text'];bg_css=get_bg_css()
 h=f"""<!DOCTYPE html><html lang="{'ar' if is_ar else 'en'}" dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1"><title>OMAIA ISP</title>
<style>
{get_menu_css()}
*{{box-sizing:border-box}}
.sb,.card,.btn-soft{{transition:transform.25s ease,opacity.25s ease}}
body{{margin:0;font-family:'Segoe UI';{bg_css};color:{text_col};font-size:11px!important;line-height:1.5}}
body.light{{background:#f0f2f5!important;color:#111!important}}body.light.card{{background:#fff!important;color:#111!important;border:1px solid #ddd!important}}body.light.sb,body.light.top{{background:#fff!important;color:#111!important}}body.light input,body.light select{{background:#fff!important;color:#111!important;border:1px solid #ccc!important}}
.sb{{position:fixed!important;top:64px;right:8px!important;left:auto!important;width:240px;border-radius:16px;padding:8px;z-index:1003;max-height:84vh;overflow:auto}}
.sb.hide{{transform:translateX(120%)!important;opacity:0;pointer-events:none}}
.sb a{{display:block;padding:8px;margin:4px 0;text-decoration:none;border-radius:10px;font-size:11px!important}}
.mn{{padding:68px 8px 20px;max-width:1400px;margin:auto}}
.card{{padding:10px;border-radius:16px;margin:8px 0;background:{col['card_bg']}!important;border:1px solid rgba(255,255,255,.08)!important;}}
table{{width:100%;border-collapse:collapse;display:block;overflow-x:auto;white-space:nowrap}}th,td{{padding:6px 4px;text-align:center;font-size:10px!important}}th{{color:{col['link']}}}
input,select{{width:100%;padding:9px;margin:5px 0;border-radius:10px;border:1px solid rgba(255,255,255,.1);background:rgba(255,255,255,.05);color:{text_col};font-size:13px!important}}
.btn-soft{{padding:10px;width:100%;border:none;border-radius:12px;font-weight:800;background:linear-gradient(135deg,{main_col},{col['accent']});color:#fff;font-size:11px!important;cursor:pointer}}
.row2{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}
#map{{height:400px;border-radius:12px;background:#222}}
.wa{{position:fixed;bottom:14px;left:14px;width:52px;height:52px;border-radius:50%;background:#25D366;display:flex!important;align-items:center;justify-content:center;font-size:26px;text-decoration:none;z-index:9999;}}
</style></head><body>
<div class="top" style="position:fixed;top:0;right:0;left:0;height:56px;display:flex;align-items:center;justify-content:space-between;padding:0 10px;z-index:1002;"><button id="mb" style="width:80px;height:36px;border-radius:16px;border:none;background:linear-gradient(135deg,{main_col},{col['accent']});color:#fff;font-size:11px;font-weight:700;cursor:pointer">{T('menu')}</button><div style="display:flex;align-items:center;gap:8px">{get_logo_html()}<b style="color:{text_col};font-size:13px">OMAIA ISP</b></div><div style="display:flex;gap:6px;align-items:center"><input id="q" placeholder="🔍 بحث" style="width:110px;height:30px;border-radius:10px;padding:0 8px;margin:0" onkeydown="if(event.key==='Enter')location.href='/dash?view=subs'"><button onclick="toggleTheme()" style="width:42px;height:30px;border-radius:10px;border:1px solid rgba(255,255,255,.15);background:rgba(255,255,255,.08);color:{text_col}">🌙</button><button class="langb" style="width:42px;height:30px;border-radius:10px;border:1px solid rgba(255,255,255,.15);background:rgba(255,255,255,.08);color:{text_col}" onclick="location.href='/set_lang/{'en' if is_ar else 'ar'}'">{'EN' if is_ar else 'ع'}</button></div></div>
<div class="sb hide" id="sb"><a href="#" data-v="home">{T('home')}</a><a href="#" data-v="subs">{T('subs')}</a><a href="#" data-v="dishes">{T('dishes')}</a><a href="#" data-v="map">{T('map')}</a><a href="#" data-v="ping">{T('ping')}</a>{ledger_link}<a href="#" data-v="towers">{T('towers')}</a><a href="#" data-v="report">{T('report')}</a><a href="#" data-v="notifs">{T('notifs')}</a><a href="#" data-v="logs">{T('logs')}</a><a href="#" data-v="settings">{T('settings')}</a><a href="#" data-v="support">{T('support')}</a><a href="/logout">{T('logout')}</a></div>
<div class="mn" id="mn">{content}</div>
<div style='text-align:center;padding:20px 10px 60px;font-size:10px;opacity:.9'>تصميم م. عبدو عباس<br><a href='https://wa.me/{SUPPORT}' target='_blank' style='color:{col['link']};text-decoration:underline' dir=ltr>{SUPPORT_DISPLAY} 💬</a></div>
<a class="wa" href="https://wa.me/{SUPPORT}" target="_blank">💬</a>
<script>
function toggleTheme(){{document.body.classList.toggle('light');localStorage.setItem('th',document.body.classList.contains('light')?'l':'d')}}
if(localStorage.getItem('th')=='l')document.body.classList.add('light');
let cache={{}},sb=document.getElementById('sb'),mn=document.getElementById('mn');
document.getElementById('mb').onclick=e=>{{e.stopPropagation();sb.classList.toggle('hide')}};
document.addEventListener('click',e=>{{if(!sb.classList.contains('hide')&&!sb.contains(e.target))sb.classList.add('hide')}});
async function loadView(v,force){{sb.classList.add('hide');window.scrollTo({{top:0,behavior:'smooth'}});if(!force&&cache[v]){{mn.innerHTML=cache[v];bind();return}}mn.innerHTML='<div class=card>⏳ جاري التحميل...</div>';try{{let r=await fetch('/api/view?v='+v);let h=await r.text();cache[v]=h;mn.innerHTML=h;bind()}}catch(e){{}}}}
function bind(){{mn.querySelectorAll('script').forEach(s=>{{let n=document.createElement('script');n.textContent=s.textContent;document.body.appendChild(n);s.remove()}})}}
document.querySelectorAll('[data-v]').forEach(a=>a.onclick=e=>{{e.preventDefault();loadView(a.dataset.v)}});
if(location.hash)loadView(location.hash.replace('#',''));
</script></body></html>"""
 return h
@app.after_request
def add_cache(r):
 if request.path.startswith('/static/'):r.cache_control.max_age=86400
 elif request.path.startswith('/api/'):r.cache_control.max_age=5
 return r
@app.route('/set_lang/<l>')
def set_lang(l): session['lang']='en' if l=='en' else 'ar';return redirect(request.referrer or '/dash')
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
 return f"""<!DOCTYPE html><html dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>دخول</title><style>body{{margin:0;font-family:'Segoe UI';{get_bg_css()};color:#fff;font-size:12px}}.wrap{{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:14px}}.box{{background:rgba(255,255,255,.06);border-radius:20px;padding:28px 18px;max-width:340px;width:100%;text-align:center}}input{{width:100%;padding:12px;margin:6px 0;border-radius:10px;border:1px solid #333;background:#1a2332;color:#fff}}button{{width:100%;padding:13px;border:none;border-radius:12px;background:linear-gradient(135deg,{col['main']},{col['accent']});color:#fff;font-weight:800}}</style></head><body><div class="wrap"><div class="box"><div style="margin-bottom:10px">{get_logo_html(60)}</div><h2>OMAIA ISP</h2>{m}<form method=post><input name=phone placeholder="رقم الهاتف" required><input name=password type=password placeholder="كلمة السر" required><button>دخول</button></form></div></div></body></html>"""
@app.route('/logout')
def lo():session.clear();return redirect('/login')
@app.route('/dash')
def dash():
 if not session.get('phone'):return redirect('/login')
 v=request.args.get('view','home');c=db();html=get_view_html(v,c,session.get('role','tech'));cc(c)
 return render_template_string(base_html(html,v))
@app.route('/api/view')
def apiv():
 if not session.get('phone'):return "no"
 v=request.args.get('v','home')
 if v!='ping':
  ch=cached_view("view_"+v,60)
  if ch: return ch
 c=db();h=get_view_html(v,c,session.get('role','tech'));cc(c)
 if v!='ping': set_cache("view_"+v,h)
 return h
@app.route('/add_sub',methods=['POST'])
def a1():c=db();ex(c,"INSERT INTO subs(name,phone,status) VALUES(?,?,?)",(request.form['name'],request.form['phone'],'نشط'));c.commit();cc(c);_cache_data.clear();return redirect('/dash#subs')
@app.route('/del_sub/<int:i>')
def d1(i):c=db();ex(c,"DELETE FROM subs WHERE id=?",(i,));c.commit();cc(c);_cache_data.clear();return redirect('/dash#dishes')
@app.route('/add_dish',methods=['POST'])
def a2():c=db();f=request.form;ex(c,"INSERT INTO dish_ips(ip,location,area,tower,lat,lng) VALUES(?,?,?,?,?,?)",(f.get('ip') or '',f.get('location') or '',f.get('area') or '',f.get('tower') or '',float(f.get('lat') or 0),float(f.get('lng') or 0)));c.commit();cc(c);_cache_data.clear();return redirect('/dash#dishes')
@app.route('/del_dish/<int:i>')
def d2(i):c=db();ex(c,"DELETE FROM dish_ips WHERE id=?",(i,));c.commit();cc(c);_cache_data.clear();return redirect('/dash#dishes')
@app.route('/add_tower',methods=['POST'])
def at():c=db();f=request.form;ex(c,"INSERT INTO towers(name,area,location,owner,lat,lng) VALUES(?,?,?,?,?,?)",(f.get('name') or '',f.get('area') or '',f.get('location') or '',f.get('owner') or '',float(f.get('lat') or 0),float(f.get('lng') or 0)));c.commit();cc(c);_cache_data.clear();return redirect('/dash#towers')
@app.route('/del_tower/<int:i>')
def dt(i):c=db();ex(c,"DELETE FROM towers WHERE id=?",(i,));c.commit();cc(c);_cache_data.clear();return redirect('/dash#towers')
@app.route('/add_user',methods=['POST'])
def a4():
 c=db();ph=request.form['phone'].strip()
 try:ex(c,"INSERT INTO users(phone,username,password,role,active) VALUES(?,?,?,?,1)",(ph,ph,request.form['password'],request.form.get('role','tech')));c.commit()
 except:pass
 cc(c);return redirect('/dash#settings')
@app.route('/edit_user/<ph>',methods=['POST'])
def eu(ph):c=db();ex(c,"UPDATE users SET password=?,role=? WHERE phone=?",(request.form['password'],request.form['role'],ph));c.commit();cc(c);return redirect('/dash#settings')
@app.route('/del_user/<ph>')
def du(ph):
 if ph=='05344851045':return redirect('/dash#settings')
 c=db();ex(c,"DELETE FROM users WHERE phone=?",(ph,));c.commit();cc(c);return redirect('/dash#settings')
@app.route('/toggle_user/<ph>')
def tu(ph):c=db();u=ex(c,"SELECT active FROM users WHERE phone=?",(ph,)).fetchone();na=0 if dict(u)['active']==1 else 1;ex(c,"UPDATE users SET active=? WHERE phone=?",(na,ph));c.commit();cc(c);return redirect('/dash#settings')
@app.route('/charge',methods=['POST'])
def ch():
 amt=float(request.form['amount']);cur=request.form.get('currency','usd');cust_name=request.form.get('cust_name','')
 usd=amt if cur=='usd' else 0;syr=amt if cur=='syr' else 0;c=db()
 ex(c,"INSERT INTO ledger(date,usd,syr,type,note,by_user) VALUES(?,?,?,?,?,?)",(datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),usd,syr,'قبض',cust_name,session.get('phone')))
 c.commit();cc(c);_cache_data.clear();return redirect('/dash#ledger')
@app.route('/export_subs')
def es():
 c=db();rs=ex(c,"SELECT name,phone,balance_usd FROM subs").fetchall();cc(c)
 o=io.StringIO();w=csv.writer(o);w.writerow(['name','phone','usd'])
 for r in rs:w.writerow([r['name'],r['phone'],r['balance_usd']])
 return Response(o.getvalue().encode('utf-8-sig'),mimetype='text/csv',headers={'Content-Disposition':'attachment;filename=subs.csv'})
if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
