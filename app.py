from flask import Flask, request, redirect, render_template_string, session, Response, jsonify
import os, datetime, io, csv, time, socket
try: import psycopg2, psycopg2.extras
except: psycopg2=None
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from colors import get_colors, get_bg_css, get_menu_css, get_logo_html
app = Flask(__name__, static_folder='static')
app.config['SEND_FILE_MAX_AGE_DEFAULT']=86400
app.secret_key=os.environ.get("SECRET_KEY","omia-sec-2026")
_raw_db = os.environ.get("DATABASE_URL","") or ""
DATABASE_URL = _raw_db.strip().replace("\n","").replace("\r","").replace(" ","")
USE_PG=bool(DATABASE_URL and psycopg2)
_pg=None;_pt=0
SUPPORT="905344851045"
SUPPORT_DISPLAY="+905344851045"
def T(k):
 L={'ar':{'home':'🏠 الرئيسية','subs':'👥 المشتركين','dishes':'📡 الصحون','map':'🗺️ الخريطة','ping':'📶 فحص','towers':'🗼 الأبراج','report':'📊 تقرير','notifs':'🔔 إشعارات','logs':'📝 السجل','settings':'⚙️ الإعدادات','support':'🛠️ دعم','ledger':'📒 الحسابات','logout':'🚪 خروج','menu':'☰ القائمة'},'en':{'home':'🏠 Home','subs':'👥 Subs','dishes':'📡 Dishes','map':'🗺️ Map','ping':'📶 Ping','towers':'🗼 Towers','report':'📊 Report','notifs':'🔔 Notifs','logs':'📝 Logs','settings':'⚙️ Settings','support':'🛠️ Support','ledger':'📒 Ledger','logout':'🚪 Logout','menu':'☰ Menu'}}
 return L.get(session.get('lang','ar'),{}).get(k,k)
def db():
 global _pg,_pt
 if USE_PG:
  if _pg and time.time()-_pt<300:
   try:
    _pg.cursor().execute("SELECT 1");return _pg
   except: pass
  _pg=psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=5)
  _pg.autocommit=True;_pt=time.time();return _pg
 c=sqlite3.connect("omia.db");c.row_factory=sqlite3.Row;return c
def cc(c):
 if not USE_PG:
  try:c.close()
  except:pass
def ex(c,q,a=()):
 if USE_PG:
  cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor);cur.execute(q.replace("?","%s"),a);return cur
 return c.execute(q,a)
def safe_commit(c):
 try: c.commit()
 except: pass
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
  cur.close()
 else:
  for s in ss:c.execute(s)
  if not c.execute("SELECT * FROM users WHERE phone='05344851045'").fetchone():c.execute("INSERT INTO users(phone,username,password,role,active) VALUES('05344851045','05344851045','admin2024','super',1)")
  for col in ["area TEXT","location TEXT","owner TEXT"]:
   try:c.execute(f"ALTER TABLE towers ADD COLUMN {col}")
   except:pass
  safe_commit(c);cc(c)
init()
def ping_one(ip):
 ip=(ip or '').strip()
 if not ip:return False
 for p in (80,443):
  try:s=socket.create_connection((ip,p),timeout=0.7);s.close();return True
  except:continue
 return False
def get_view_html(v,c,role,q=""):
 col=get_colors()
 if v=='home':
  def cnt(t):
   r=ex(c,f"SELECT COUNT(*) as c FROM {t}").fetchone()
   try:return dict(r)['c']
   except:return r[0]
  ns=cnt("subs");nd=cnt("dish_ips");nt=cnt("towers")
  today=datetime.date.today().isoformat()
  r=ex(c,"SELECT COUNT(*) as c FROM users WHERE active=0").fetchone()
  disabled=dict(r)['c'] if r else 0
  try:
   r=ex(c,"SELECT COUNT(DISTINCT phone) as c FROM login_logs WHERE date LIKE?",(today+"%",)).fetchone()
   online=dict(r)['c'] if USE_PG else r[0]
  except:online=0
  def icard(key, emoji, title, val):
   bg=col.get(key,'#333')
   return f"""<div class="icard" style="background:{bg}"><div style="font-size:18px">{emoji}</div><div style="font-weight:700;font-size:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{title}</div><div style="font-size:16px;font-weight:800">{val}</div></div>"""
  return f"""<div class="card" style="text-align:center"><h2 style="margin:0">أمية</h2><p style="margin:4px 0;opacity:.8">📅 {today}</p></div><div class="igrid">{icard('icon_ip','📡','عدد IP',nd)}{icard('icon_disabled','⏸️','تم تعطيلهم',disabled)}{icard('icon_online','🟢','فاتحين الموقع',online)}{icard('icon_active','📶','المتصلين',ns)}{icard('icon_monqatein','❄️','المنقطعين',0)}{icard('icon_modirin','👔','المديرين',0)}{icard('icon_no_expire','⏸️','تم إيقافهم',0)}{icard('icon_expired','🔴','انتهى اشتراكهم',0)}{icard('icon_blocked','🚫','محظور',0)}</div>"""
 if v=='subs':
  rs=ex(c,"SELECT * FROM subs ORDER BY id DESC LIMIT 50").fetchall() if not q else ex(c,"SELECT * FROM subs WHERE name LIKE? OR phone LIKE? ORDER BY id DESC LIMIT 50",("%"+q+"%","%"+q+"%")).fetchall()
  tr="".join([f"<tr><td>{r['name']}</td><td dir=ltr>{r['phone']}</td><td>{r['balance_usd']}$</td><td><a class='abtn abtn-edit' href='https://wa.me/{r['phone']}' target=_blank>💬</a> <a class='abtn abtn-del' href='#' onclick=\"return ajaxDel('/del_sub/{r['id']}','subs')\">حذف</a></td></tr>" for r in rs])
  return f"<div class='card'><input id='sq' placeholder='🔍 بحث عن مشترك...' value='{q}' oninput=\"debSearch(this.value)\"><form onsubmit=\"return ajaxSubmit(this,'subs')\" method=post action=/add_sub><div class=row2><input name=name placeholder='الاسم' required><input name=phone placeholder='هاتف' required></div><button class='btn-soft'>إضافة مشترك</button></form><a class='abtn abtn-edit' href='/export_subs' style='margin-top:6px'>📥 تصدير CSV</a></div><div class='card'><table><tr><th>اسم</th><th>هاتف</th><th>رصيد</th><th>إجراءات</th></tr>{tr}</table></div>"
 if v=='dishes':
  rs=ex(c,"SELECT * FROM dish_ips ORDER BY id DESC LIMIT 100").fetchall()
  tr="".join([f"<tr><td dir=ltr><a href='http://{dict(r)['ip']}' target='_blank' style='color:#4da3ff'>{dict(r)['ip'] or '-'}</a></td><td>{dict(r).get('location','')}</td><td>{dict(r).get('area','')}</td><td><a class='abtn abtn-edit' href='/edit_dish/{dict(r)['id']}'>تعديل</a> <a class='abtn abtn-del' href='#' onclick=\"return ajaxDel('/del_dish/{dict(r)['id']}','dishes')\">حذف</a></td></tr>" for r in rs])
  return f"<div class='card'><h3>📡 الصحون</h3><form onsubmit=\"return ajaxSubmit(this,'dishes')\" method=post action=/add_dish><div class=row2><input name=ip placeholder='IP' dir=ltr><input name=location placeholder='اسم الصحن'></div><div class=row2><input name=area placeholder='المنطقة'><input name=tower placeholder='البرج'></div><div class=row2><input name=lat placeholder='Lat' type=number step=any><input name=lng placeholder='Lng' type=number step=any></div><button class='btn-soft'>إضافة</button></form></div><div class='card'><table><tr><th>IP</th><th>اسم</th><th>منطقة</th><th>إجراءات</th></tr>{tr}</table></div>"
 if v=='ping':
  rs=ex(c,"SELECT * FROM dish_ips ORDER BY id DESC LIMIT 10").fetchall()
  ips=[dict(r) for r in rs]
  with ThreadPoolExecutor(max_workers=5) as exx:results=list(exx.map(ping_one,[d.get('ip','') for d in ips]))
  tr="".join([f"<tr><td>{'🟢' if ok else '🔴'}</td><td dir=ltr>{d.get('ip','')}</td><td>{d.get('location','')}</td></tr>" for d,ok in zip(ips,results)])
  return f"<div class='card'><h3>📶 فحص Ping</h3><button class='btn-soft' onclick=\"loadView('ping',true)\">🔄 فحص الآن</button></div><div class='card'><table><tr><th>حالة</th><th>IP</th><th>اسم</th></tr>{tr}</table></div>"
 if v=='towers':
  rs=ex(c,"SELECT * FROM towers ORDER BY id DESC LIMIT 100").fetchall()
  tr="".join([f"<tr><td>{dict(r).get('name','')}</td><td>{dict(r).get('area','') or ''}</td><td>{dict(r).get('owner','') or ''}</td><td>{dict(r).get('lat',0)},{dict(r).get('lng',0)}</td><td><a class='abtn abtn-del' href='#' onclick=\"return ajaxDel('/del_tower/{dict(r)['id']}','towers')\">حذف</a></td></tr>" for r in rs])
  return f"<div class='card'><h3>🗼 إضافة برج مع إحداثيات</h3><form onsubmit=\"return ajaxSubmit(this,'towers')\" method=post action=/add_tower><input name=name placeholder='اسم برج' required><div class=row2><input name=area placeholder='منطقه'><input name=owner placeholder='لمين برج'></div><div class=row2><input name=lat placeholder='Lat' type=number step=any required><input name=lng placeholder='Lng' type=number step=any required></div><input name=location placeholder='موقع برج'><button class='btn-soft'>📍 حفظ البرج</button></form></div><div class='card'><table><tr><th>اسم</th><th>منطقه</th><th>لمين</th><th>إحداثيات</th><th></th></tr>{tr}</table></div>"
 if v=='map':
  ds=list(ex(c,"SELECT location,lat,lng FROM dish_ips WHERE lat!=0 LIMIT 200").fetchall())
  ts=list(ex(c,"SELECT name,lat,lng FROM towers WHERE lat!=0 LIMIT 200").fetchall())
  mk=""
  for r in ds:
   try:mk+=f"L.marker([{float(dict(r)['lat'])},{float(dict(r)['lng'])}]).addTo(m).bindPopup('📡 {str(dict(r).get('location','')).replace(chr(39),'')}');\n"
   except:pass
  for r in ts:
   try:mk+=f"L.marker([{float(dict(r)['lat'])},{float(dict(r)['lng'])}]).addTo(m).bindPopup('🗼 {str(dict(r).get('name','')).replace(chr(39),'')}');\n"
   except:pass
  if not mk:mk="L.marker([34.72,36.72]).addTo(m).bindPopup('حمص');"
  return f"<link rel='stylesheet' href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'/><div class='card'><h3>🗺️ الخريطة</h3><div id='mp' style='height:480px;border-radius:12px;background:#1a2332'></div><div style='margin-top:6px;font-size:10px;opacity:.7'>📡 {len(ds)} | 🗼 {len(ts)}</div></div><script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script><script>setTimeout(function(){{var m=L.map('mp').setView([34.72,36.72],11);L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:19,attribution:'© OSM'}}).addTo(m);{mk}setTimeout(function(){{m.invalidateSize()}},200);}},100);</script>"
 if v=='ledger':
  if role not in ('super','admin'):return "<div class='card'>ممنوع</div>"
  rs=ex(c,"SELECT * FROM ledger ORDER BY id DESC LIMIT 100").fetchall()
  tr="".join([f"<tr><td>{dict(r)['date']}</td><td>{dict(r).get('note','')}</td><td>{dict(r).get('usd',0)}$</td><td>{dict(r).get('syr',0)}</td><td><a class='abtn abtn-edit' href='/edit_ledger/{dict(r)['id']}'>تعديل</a> <a class='abtn abtn-del' href='#' onclick=\"return ajaxDel('/del_ledger/{dict(r)['id']}','ledger')\">حذف</a></td></tr>" for r in rs])
  return f"<div class='card'><h3>📒 دفتر حسابات</h3><form onsubmit=\"return ajaxSubmit(this,'ledger')\" method=post action=/charge><input name=cust_name placeholder='اسم الزبون' required><div class=row2><input name=amount type=number step=0.01 required placeholder='مبلغ'><select name=currency><option value=usd>$ دولار</option><option value=syr>ل.س سوري</option></select></div><button class='btn-soft'>➕ إضافة</button></form></div><div class='card'><table><tr><th>تاريخ</th><th>الاسم</th><th>$</th><th>ل.س</th><th>إجراءات</th></tr>{tr}</table></div>"
 if v=='report':
  today=datetime.date.today().isoformat()
  r1=ex(c,"SELECT SUM(usd) s1,SUM(syr) s2 FROM ledger WHERE date LIKE?",(today+"%",)).fetchone();a=dict(r1) if r1 else {}
  return f"<div class='card'><h3>📊 تقرير اليوم</h3><p>💵 $: {a.get('s1') or 0} | 💴 ل.س: {a.get('s2') or 0}</p></div>"
 if v=='notifs':
  rs=ex(c,"SELECT * FROM notifications ORDER BY id DESC LIMIT 50").fetchall();ex(c,"UPDATE notifications SET seen=1");safe_commit(c)
  t="".join([f"<div class='card'>🔔 {r['msg']}<br><small>{r['date']}</small></div>" for r in rs]) or "<div class='card'>لا إشعارات</div>"
  return f"<h3>🔔 إشعارات</h3>{t}"
 if v=='logs':
  rs=ex(c,"SELECT * FROM login_logs ORDER BY id DESC LIMIT 50").fetchall()
  tr="".join([f"<tr><td>{r['phone']}</td><td>{r['date']}</td><td>{r['ip']}</td></tr>" for r in rs])
  return f"<div class='card'><h3>📝 سجل الدخول</h3><table><tr><th>مستخدم</th><th>وقت</th><th>IP</th></tr>{tr}</table></div>"
 if v=='settings':
  us=ex(c,"SELECT * FROM users LIMIT 100").fetchall();cards=""
  for u in us:
   d=dict(u);active=d['active']==1
   stt="<span class='badge-active'>نشط</span>" if active else "<span class='badge-off'>معطل</span>"
   bt="تعطيل" if active else "تفعيل"
   cards+=f"<div class='ucard'><b dir=ltr style='font-size:14px'>{d['phone']}</b><div style='margin:6px 0'>الدور: <b>{d['role']}</b></div><div>الحالة: {stt}</div><div class='ubtns'><a class='abtn abtn-edit' href='#' onclick=\"document.getElementById('e{d['phone']}').style.display='flex';return false\">تعديل</a><a class='abtn abtn-toggle' href='#' onclick=\"return ajaxDel('/toggle_user/{d['phone']}','settings')\">{bt}</a><a class='abtn abtn-del' href='#' onclick=\"return ajaxDel('/del_user/{d['phone']}','settings')\">حذف</a></div><div id='e{d['phone']}' style='display:none;position:fixed;top:0;right:0;left:0;bottom:0;background:rgba(0,0,0,.6);z-index:2000;align-items:center;justify-content:center'><form onsubmit=\"return ajaxSubmit(this,'settings')\" method=post action='/edit_user/{d['phone']}' style='background:#1a2332;padding:16px;border-radius:14px;width:90%;max-width:300px'><h4 dir=ltr>{d['phone']}</h4><input name=password value='{d['password']}' required><select name=role><option value=tech {'selected' if d['role']=='tech' else ''}>فني</option><option value=admin {'selected' if d['role']=='admin' else ''}>مدير</option><option value=distributor {'selected' if d['role']=='distributor' else ''}>موزع</option></select><div class=row2><button class='abtn abtn-edit'>حفظ</button><button type=button class='abtn abtn-del' onclick=\"document.getElementById('e{d['phone']}').style.display='none'\">إلغاء</button></div></form></div></div>"
  return f"<div class='card'><h3>⚙️ إضافة مستخدم</h3><form onsubmit=\"return ajaxSubmit(this,'settings')\" method=post action=/add_user><input name=phone placeholder='رقم الهاتف' required dir=ltr><div class=row2><input name=password placeholder='كلمة السر' required><select name=role><option value='tech'>فني</option><option value='admin'>مدير</option><option value='distributor'>موزع</option></select></div><button class='btn-soft'>+ إضافة</button></form></div><div class='u-grid'>{cards}</div>"
 if v=='support':return f"<div class='card' style='text-align:center'><h3>🛠️ الدعم الفني</h3><a href='https://wa.me/{SUPPORT}' target='_blank' style='color:#4da3ff'><h2 dir=ltr>{SUPPORT_DISPLAY} 💬</h2></a></div>"
 return ""
def base_html(content,curview):
 col=get_colors();role=session.get('role','tech');lang=session.get('lang','ar');is_ar=lang=='ar'
 ledger_link=f'<a href="#" data-v="ledger">{T("ledger")}</a>' if role in ('super','admin') else ''
 h=f"""<!DOCTYPE html><html dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1"><title>OMAIA ISP</title><style>
{get_menu_css()}
*{{box-sizing:border-box}}
body{{margin:0;font-family:'Segoe UI';{get_bg_css()};color:{col['text']};font-size:12px;line-height:1.5}}
.card{{padding:12px;border-radius:16px;margin:8px 0;background:{col['card_bg']}!important;border:1px solid rgba(255,255,255,.08)!important}}
.icard{{border-radius:12px;padding:10px 4px;color:#fff;text-align:center;display:flex;flex-direction:column;justify-content:center;min-height:78px;cursor:pointer}}
.igrid{{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:8px;margin:8px 0}}
.abtn{{padding:7px 13px;border-radius:12px;font-weight:800;font-size:11px;text-decoration:none;color:#fff!important;display:inline-block;border:none;cursor:pointer}}
.abtn-edit{{background:linear-gradient(135deg,#06b6d4,#3b82f6)}}
.abtn-toggle{{background:linear-gradient(135deg,#fbbf24,#f59e0b)}}
.abtn-del{{background:linear-gradient(135deg,#fb7185,#ef4444)}}
.badge-active{{background:linear-gradient(135deg,#34d399,#10b981);color:#fff;padding:4px 14px;border-radius:20px;font-size:10px;font-weight:800}}
.badge-off{{background:#6b7280;color:#fff;padding:4px 14px;border-radius:20px;font-size:10px;font-weight:800}}
.ucard{{background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.1);border-radius:20px;padding:14px;text-align:center}}
.u-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px}}
.ubtns{{display:flex;gap:6px;justify-content:center;margin-top:10px;flex-wrap:wrap}}
.sb{{position:fixed!important;top:64px;right:8px!important;width:240px;border-radius:16px;padding:8px;z-index:1003;max-height:84vh;overflow:auto;transition:.2s}}
.sb.hide{{transform:translateX(120%)!important;opacity:0;pointer-events:none}}
.sb a{{display:block;padding:9px;margin:4px 0;text-decoration:none;border-radius:10px}}
.mn{{padding:68px 8px 20px;max-width:1400px;margin:auto}}
table{{width:100%;border-collapse:collapse;display:block;overflow-x:auto;white-space:nowrap}}th,td{{padding:7px 5px;text-align:center;font-size:11px}}th{{color:{col['link']}}}
input,select{{width:100%;padding:10px;margin:5px 0;border-radius:10px;border:1px solid rgba(255,255,255,.12);background:rgba(255,255,255,.06);color:{col['text']};font-size:13px}}
.btn-soft{{padding:11px;width:100%;border:none;border-radius:12px;font-weight:800;background:linear-gradient(135deg,{col['main']},{col['accent']});color:#fff;cursor:pointer}}
.row2{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}
.wa{{position:fixed;bottom:14px;left:14px;width:52px;height:52px;border-radius:50%;background:#25D366;display:flex!important;align-items:center;justify-content:center;font-size:26px;text-decoration:none;z-index:9999}}
.skel{{background:linear-gradient(90deg,rgba(255,255,255,.06) 25%,rgba(255,255,255,.12) 50%,rgba(255,255,255,.06) 75%);background-size:200% 100%;animation:sh 0.8s infinite;border-radius:12px;height:60px;margin:8px 0}}
@keyframes sh{{to{{background-position:-200% 0}}}}
</style></head><body>
<div class="top" style="position:fixed;top:0;right:0;left:0;height:56px;display:flex;align-items:center;justify-content:space-between;padding:0 10px;z-index:1002;"><button id="mb" style="width:80px;height:36px;border-radius:16px;border:none;background:linear-gradient(135deg,{col['main']},{col['accent']});color:#fff;font-weight:700;cursor:pointer">{T('menu')}</button><div style="display:flex;align-items:center;gap:8px">{get_logo_html()}<b>OMAIA ISP</b></div><div style="display:flex;gap:6px"><button onclick="toggleTheme()" style="width:42px;height:30px;border-radius:10px;cursor:pointer">🌙</button><button onclick="location.href='/set_lang/{'en' if is_ar else 'ar'}'" style="width:42px;height:30px;border-radius:10px;cursor:pointer">{'EN' if is_ar else 'ع'}</button></div></div>
<div class="sb hide" id="sb"><a href="#" data-v="home">{T('home')}</a><a href="#" data-v="subs">{T('subs')}</a><a href="#" data-v="dishes">{T('dishes')}</a><a href="#" data-v="map">{T('map')}</a><a href="#" data-v="ping">{T('ping')}</a>{ledger_link}<a href="#" data-v="towers">{T('towers')}</a><a href="#" data-v="report">{T('report')}</a><a href="#" data-v="notifs">{T('notifs')}</a><a href="#" data-v="logs">{T('logs')}</a><a href="#" data-v="settings">{T('settings')}</a><a href="#" data-v="support">{T('support')}</a><a href="/logout">{T('logout')}</a></div>
<div class="mn" id="mn">{content}</div>
<div style='text-align:center;padding:20px 10px 60px;font-size:10px;opacity:.8'>تصميم م. عبدو عباس<br><a href='https://wa.me/{SUPPORT}' target='_blank' style='color:{col['link']}' dir=ltr>{SUPPORT_DISPLAY} 💬</a></div>
<a class="wa" href="https://wa.me/{SUPPORT}" target="_blank">💬</a>
<script>
function toggleTheme(){{document.body.classList.toggle('light');localStorage.setItem('th',document.body.classList.contains('light')?'l':'d')}}
if(localStorage.getItem('th')=='l')document.body.classList.add('light');
let cache={{}},sb=document.getElementById('sb'),mn=document.getElementById('mn'),curV='{curview}';
document.getElementById('mb').onclick=e=>{{e.stopPropagation();sb.classList.toggle('hide')}};
document.addEventListener('click',e=>{{if(!sb.classList.contains('hide')&&!sb.contains(e.target))sb.classList.add('hide')}});
async function loadView(v,force){{sb.classList.add('hide');curV=v;history.replaceState(null,'','#'+v);if(!force&&cache[v]){{mn.innerHTML=cache[v];bind();return}}if(cache[v]){{mn.innerHTML=cache[v]}}else{{mn.innerHTML='<div class=skel></div><div class=skel></div>'}}try{{let r=await fetch('/api/view?v='+v,{{headers:{{'X-Requested-With':'fetch'}}}});let h=await r.text();cache[v]=h;mn.innerHTML=h;bind()}}catch(e){{}}}}
function bind(){{mn.querySelectorAll('script').forEach(s=>{{let n=document.createElement('script');n.textContent=s.textContent;document.body.appendChild(n);s.remove()}})}}
async function ajaxSubmit(f,v){{if(f.dataset.sent=="1")return false;f.dataset.sent="1";let b=f.querySelector('button');let ot=b?b.innerHTML:'';if(b){{b.disabled=true;b.innerHTML='⏳...'}}try{{await fetch(f.action,{{method:'POST',body:new FormData(f),headers:{{'X-Requested-With':'fetch'}}}});delete cache[v];await loadView(v,true);f.reset()}}catch(e){{}}setTimeout(()=>{{f.dataset.sent="0";if(b){{b.disabled=false;b.innerHTML=ot}}}},1200);return false}}
async function ajaxDel(url,v){{if(!confirm('تأكيد الحذف؟'))return false;try{{await fetch(url,{{headers:{{'X-Requested-With':'fetch'}}}});delete cache[v];await loadView(v,true)}}catch(e){{}}return false}}
let debT=null;function debSearch(q){{clearTimeout(debT);debT=setTimeout(()=>{{fetch('/api/view?v=subs&q='+encodeURIComponent(q),{{headers:{{'X-Requested-With':'fetch'}}}}).then(r=>r.text()).then(h=>{{cache['subs']=h;mn.innerHTML=h;bind();let inp=document.getElementById('sq');if(inp){{inp.focus();inp.setSelectionRange(inp.value.length,inp.value.length)}}}})}},300)}}
document.querySelectorAll('[data-v]').forEach(a=>a.onclick=e=>{{e.preventDefault();loadView(a.dataset.v)}});
if(location.hash){{let vh=location.hash.replace('#','');if(cache[vh]===undefined)loadView(vh,true)}}
</script></body></html>"""
 return h
@app.after_request
def add_cache(r):
 if request.path.startswith('/static/'):r.cache_control.max_age=86400
 return r
@app.route('/set_lang/<l>')
def set_lang(l):session['lang']='en' if l=='en' else 'ar';return redirect(request.referrer or '/dash')
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
   ex(c,"INSERT INTO login_logs(phone,date,ip) VALUES(?,?,?)",(d['phone'],datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),request.remote_addr));safe_commit(c);cc(c);return redirect('/dash')
  try:cc(c)
  except:pass
  m="<p style='color:#ff6b6b;text-align:center'>❌ خطأ بالدخول</p>"
 return f"""<!DOCTYPE html><html dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OMAIA</title><style>*{{box-sizing:border-box;margin:0}}body{{font-family:'Segoe UI';min-height:100vh;display:flex;align-items:center;justify-content:center;background:radial-gradient(ellipse at top,#1e293b,#0f172a);color:#fff}}.box{{background:rgba(255,255,255,.08);backdrop-filter:blur(20px);border-radius:24px;padding:32px 24px;max-width:360px;width:92%;text-align:center}}input{{width:100%;padding:13px;margin:6px 0;border-radius:12px;border:1px solid rgba(255,255,255,.15);background:rgba(255,255,255,.06);color:#fff;text-align:center}}button{{width:100%;padding:14px;border:none;border-radius:12px;background:linear-gradient(135deg,#3b82f6,#8b5cf6);color:#fff;font-weight:800;cursor:pointer}}</style></head><body><div class="box"><div style="font-size:56px">📡</div><h2>OMAIA ISP</h2>{m}<form method=post><input name=phone placeholder="📱 رقم الهاتف" required dir=ltr><input name=password type=password placeholder="🔒 كلمة السر" required><button>🚀 دخول</button></form><div style="margin-top:12px;font-size:11px;opacity:.6'>تصميم م. عبدو عباس<br><a href='https://wa.me/{SUPPORT}' style='color:#60a5fa'>💬 {SUPPORT_DISPLAY}</a></div></div></body></html>"""
@app.route('/logout')
def lo():session.clear();return redirect('/login')
@app.route('/dash')
def dash():
 if not session.get('phone'):return redirect('/login')
 v=request.args.get('view','home');c=db();html=get_view_html(v,c,session.get('role','tech'),request.args.get('q',''));cc(c)
 return render_template_string(base_html(html,v))
@app.route('/api/view')
def apiv():
 if not session.get('phone'):return "no"
 v=request.args.get('v','home');q=request.args.get('q','')
 c=db();h=get_view_html(v,c,session.get('role','tech'),q);cc(c);return h
def is_ajax():return request.headers.get('X-Requested-With')=='fetch'
_last_add={}
def allow_add(key, val):
 import time as _t
 now=_t.time(); k=f"{key}:{val.strip()}"
 if k in _last_add and now-_last_add[k]<3:
  return False
 _last_add[k]=now; return True
@app.route('/add_sub',methods=['POST'])
def a1():
 if not allow_add("sub", request.form.get('phone','')): return jsonify(ok=True)
 c=db();ex(c,"INSERT INTO subs(name,phone,status) VALUES(?,?,?)",(request.form['name'],request.form['phone'],'نشط'));safe_commit(c);cc(c);return jsonify(ok=True) if is_ajax() else redirect('/dash#subs')
@app.route('/del_sub/<int:i>')
def d1(i):c=db();ex(c,"DELETE FROM subs WHERE id=?",(i,));safe_commit(c);cc(c);return jsonify(ok=True) if is_ajax() else redirect('/dash#subs')
@app.route('/add_dish',methods=['POST'])
def a2():
 f=request.form
 ip=(f.get('ip') or '').strip()
 if ip and not allow_add("dish", ip): return jsonify(ok=True)
 c=db();ex(c,"INSERT INTO dish_ips(ip,location,area,tower,lat,lng) VALUES(?,?,?,?,?,?)",(f.get('ip') or '',f.get('location') or '',f.get('area') or '',f.get('tower') or '',float(f.get('lat') or 0),float(f.get('lng') or 0)));safe_commit(c);cc(c);return jsonify(ok=True) if is_ajax() else redirect('/dash#dishes')
@app.route('/edit_dish/<int:i>',methods=['GET','POST'])
def edit_dish(i):
 c=db()
 if request.method=='POST':
  f=request.form;ex(c,"UPDATE dish_ips SET ip=?,location=?,area=?,tower=? WHERE id=?",(f.get('ip'),f.get('location'),f.get('area'),f.get('tower'),i));safe_commit(c);cc(c);return redirect('/dash#dishes')
 r=dict(ex(c,"SELECT * FROM dish_ips WHERE id=?",(i,)).fetchone());cc(c);col=get_colors();bg=get_bg_css()
 return f"<!DOCTYPE html><html dir='rtl'><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width,initial-scale=1'><style>body{{margin:0;font-family:'Segoe UI';{bg};color:{col['text']};min-height:100vh;display:flex;align-items:center;justify-content:center}}input{{width:100%;padding:12px;margin:6px 0;border-radius:12px;border:1px solid rgba(255,255,255,.14);background:rgba(255,255,255,.06);color:{col['text']};box-sizing:border-box}}.card{{background:{col['card_bg']};border-radius:20px;padding:24px;width:92%;max-width:380px;text-align:center}}.abtn{{padding:12px 18px;border-radius:12px;font-weight:800;color:#fff;text-decoration:none;display:inline-block;border:none;cursor:pointer}}.abtn-edit{{background:linear-gradient(135deg,#06b6d4,#3b82f6)}}</style></head><body><div class='card'><h3>✏️ تعديل صحن</h3><form method=post><input name=ip value='{r['ip']}' dir=ltr placeholder='IP'><input name=location value='{r.get('location','')}' placeholder='الاسم'><input name=area value='{r.get('area','')}' placeholder='المنطقة'><input name=tower value='{r.get('tower','')}' placeholder='البرج'><button class='abtn abtn-edit' style='width:100%;font-size:14px'>💾 حفظ التعديل</button></form><a href='/dash#dishes' style='display:inline-block;margin-top:12px;color:{col['link']}'>رجوع</a></div></body></html>"
@app.route('/del_dish/<int:i>')
def d2(i):c=db();ex(c,"DELETE FROM dish_ips WHERE id=?",(i,));safe_commit(c);cc(c);return jsonify(ok=True) if is_ajax() else redirect('/dash#dishes')
@app.route('/add_tower',methods=['POST'])
def at():
 f=request.form
 nm=(f.get('name') or '').strip()
 if nm and not allow_add("tower", nm): return jsonify(ok=True)
 c=db();ex(c,"INSERT INTO towers(name,area,location,owner,lat,lng) VALUES(?,?,?,?,?,?)",(f.get('name') or '',f.get('area') or '',f.get('location') or '',f.get('owner') or '',float(f.get('lat') or 0),float(f.get('lng') or 0)));safe_commit(c);cc(c);return jsonify(ok=True) if is_ajax() else redirect('/dash#towers')
@app.route('/del_tower/<int:i>')
def dt(i):c=db();ex(c,"DELETE FROM towers WHERE id=?",(i,));safe_commit(c);cc(c);return jsonify(ok=True) if is_ajax() else redirect('/dash#towers')
@app.route('/add_user',methods=['POST'])
def a4():
 c=db();ph=request.form['phone'].strip()
 try:ex(c,"INSERT INTO users(phone,username,password,role,active) VALUES(?,?,?,?,1)",(ph,ph,request.form['password'],request.form.get('role','tech')));safe_commit(c)
 except:pass
 cc(c);return jsonify(ok=True) if is_ajax() else redirect('/dash#settings')
@app.route('/edit_user/<ph>',methods=['POST'])
def eu(ph):c=db();ex(c,"UPDATE users SET password=?,role=? WHERE phone=?",(request.form['password'],request.form['role'],ph));safe_commit(c);cc(c);return jsonify(ok=True) if is_ajax() else redirect('/dash#settings')
@app.route('/del_user/<ph>')
def du(ph):
 if ph=='05344851045':return jsonify(ok=False) if is_ajax() else redirect('/dash#settings')
 c=db();ex(c,"DELETE FROM users WHERE phone=?",(ph,));safe_commit(c);cc(c);return jsonify(ok=True) if is_ajax() else redirect('/dash#settings')
@app.route('/toggle_user/<ph>')
def tu(ph):c=db();u=ex(c,"SELECT active FROM users WHERE phone=?",(ph,)).fetchone();na=0 if dict(u)['active']==1 else 1;ex(c,"UPDATE users SET active=? WHERE phone=?",(na,ph));safe_commit(c);cc(c);return jsonify(ok=True) if is_ajax() else redirect('/dash#settings')
@app.route('/charge',methods=['POST'])
def ch():
 if not allow_add("charge", request.form.get('cust_name','')+request.form.get('amount','')): return jsonify(ok=True)
 amt=float(request.form['amount']);cur=request.form.get('currency','usd');cust_name=request.form.get('cust_name','')
 usd=amt if cur=='usd' else 0;syr=amt if cur=='syr' else 0;c=db()
 ex(c,"INSERT INTO ledger(date,usd,syr,type,note,by_user) VALUES(?,?,?,?,?,?)",(datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),usd,syr,'قبض',cust_name,session.get('phone')))
 safe_commit(c);cc(c);return jsonify(ok=True) if is_ajax() else redirect('/dash#ledger')
@app.route('/edit_ledger/<int:i>',methods=['GET','POST'])
def edit_ledger(i):
 c=db()
 if request.method=='POST':
  ex(c,"UPDATE ledger SET note=?,usd=?,syr=? WHERE id=?",(request.form.get('note'),float(request.form.get('usd') or 0),float(request.form.get('syr') or 0),i));safe_commit(c);cc(c);return redirect('/dash#ledger')
 r=dict(ex(c,"SELECT * FROM ledger WHERE id=?",(i,)).fetchone());cc(c);col=get_colors();bg=get_bg_css()
 return f"<!DOCTYPE html><html dir='rtl'><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width,initial-scale=1'><style>body{{margin:0;font-family:'Segoe UI';{bg};color:{col['text']};min-height:100vh;display:flex;align-items:center;justify-content:center}}input{{width:100%;padding:12px;margin:6px 0;border-radius:12px;border:1px solid rgba(255,255,255,.14);background:rgba(255,255,255,.06);color:{col['text']};box-sizing:border-box}}.card{{background:{col['card_bg']};border-radius:20px;padding:24px;width:92%;max-width:380px;text-align:center}}.abtn{{padding:12px 18px;border-radius:12px;font-weight:800;color:#fff;border:none;cursor:pointer}}.abtn-edit{{background:linear-gradient(135deg,#06b6d4,#3b82f6)}}</style></head><body><div class='card'><h3>✏️ تعديل قيد</h3><form method=post><input name=note value='{r.get('note','')}' placeholder='البيان'><input name=usd value='{r.get('usd',0)}' type=number step=0.01><input name=syr value='{r.get('syr',0)}' type=number step=0.01><button class='abtn abtn-edit' style='width:100%;font-size:14px'>💾 حفظ التعديل</button></form><a href='/dash#ledger' style='display:inline-block;margin-top:12px;color:{col['link']}'>رجوع</a></div></body></html>"
@app.route('/del_ledger/<int:i>')
def del_ledger(i):c=db();ex(c,"DELETE FROM ledger WHERE id=?",(i,));safe_commit(c);cc(c);return jsonify(ok=True) if is_ajax() else redirect('/dash#ledger')
@app.route('/export_subs')
def es():
 c=db();rs=ex(c,"SELECT name,phone,balance_usd FROM subs").fetchall();cc(c)
 o=io.StringIO();w=csv.writer(o);w.writerow(['name','phone','usd'])
 for r in rs:w.writerow([r['name'],r['phone'],r['balance_usd']])
 return Response(o.getvalue().encode('utf-8-sig'),mimetype='text/csv',headers={'Content-Disposition':'attachment;filename=subs.csv'})
@app.route('/debug_db')
def debug_db():
 return f"USE_PG={USE_PG} LEN={len(DATABASE_URL)}"
if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
