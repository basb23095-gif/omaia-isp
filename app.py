from flask import Flask, request, redirect, render_template_string, session, Response
import os, datetime, io, csv, time, socket
try:
    import psycopg2, psycopg2.extras
except: psycopg2=None
import sqlite3
from colors import get_colors, get_bg_css

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "omia-sec-2026")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
USE_PG = bool(DATABASE_URL and psycopg2)
_pg=None;_pt=0
SUPPORT="0095344851045"

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
    ss=[
        "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,username TEXT,password TEXT,role TEXT,active INT DEFAULT 1)",
        "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,status TEXT,balance_usd REAL DEFAULT 0,balance_syr REAL DEFAULT 0)",
        "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,site TEXT,area TEXT,tower TEXT,lat REAL DEFAULT 0,lng REAL DEFAULT 0)",
        "CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,lat REAL,lng REAL,note TEXT)",
        "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,sub_id INT,date TEXT,usd REAL,syr REAL,type TEXT,note TEXT,by_user TEXT)",
        "CREATE TABLE IF NOT EXISTS servers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,host TEXT,username TEXT,password TEXT)",
        "CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,msg TEXT,date TEXT,seen INT DEFAULT 0)",
        "CREATE TABLE IF NOT EXISTS login_logs(id INTEGER PRIMARY KEY AUTOINCREMENT,phone TEXT,date TEXT,ip TEXT)"
    ]
    if USE_PG: ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
    if USE_PG:
        cur=c.cursor()
        for s in ss:cur.execute(s)
        cur.execute("SELECT * FROM users WHERE phone='05344851045'")
        if not cur.fetchone():cur.execute("INSERT INTO users(phone,username,password,role,active) VALUES('05344851045','admin','admin2024','super',1)")
        c.commit();cur.close()
    else:
        for s in ss:c.execute(s)
        if not c.execute("SELECT * FROM users WHERE phone='05344851045'").fetchone():
            c.execute("INSERT INTO users(phone,username,password,role,active) VALUES('05344851045','admin','admin2024','super',1)")
        c.commit();cc(c)
init()

def ping(ip):
    ip=(ip or '').strip()
    if not ip: return False
    for port in (80,443,22,53,8080):
        try:socket.create_connection((ip,port),timeout=1.5).close();return True
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
        return f"""<div class="card glass" style="text-align:center"><h2>👋 أهلاً بك</h2><p>📅 {today} | 💰 دخل اليوم: <b>{inc}$</b></p></div><div class="row4"><div class="stat glass"><h2>{ns}</h2><p>👥 مشتركين</p></div><div class="stat glass"><h2>{nd}</h2><p>📡 صحون</p></div><div class="stat glass"><h2>{nt}</h2><p>🗼 أبراج</p></div><div class="stat glass"><h2>{nl}</h2><p>📒 قيود</p></div></div><div class="row2"><div class="card glass"><h3>⚡ سريع</h3><div class="row2"><button onclick="loadView('subs')">+ مشترك</button><button onclick="loadView('dishes')">+ صحن</button></div><div class="row2" style="margin-top:8px"><button onclick="loadView('ping')">📶 Ping</button><button onclick="loadView('map')">🗺️ خريطة</button></div></div><div class="card glass"><h3>🛠️ الدعم الفني</h3><p dir=ltr>{SUPPORT}</p><button onclick="window.open('https://wa.me/{SUPPORT}','_blank')">💬 واتساب</button></div></div>"""
    if v=='subs':
        rs=ex(c,"SELECT * FROM subs ORDER BY id DESC").fetchall()
        tr="".join([f"<tr><td>{r['name']}</td><td dir=ltr>{r['phone']}</td><td>{r['balance_usd']}$</td><td><a href='https://wa.me/{r['phone']}' target=_blank>💬</a></td><td><a href='/del_sub/{r['id']}' style='color:red'>✖</a></td></tr>" for r in rs])
        return f"<div class='card glass'><form method=post action=/add_sub><div class=row2><input name=name placeholder='الاسم' required><input name=phone placeholder='هاتف' required></div><button>إضافة مشترك</button></form></div><div class='card glass'><button onclick=\"location.href='/export_subs'\">📥 Excel</button></div><div class='card glass'><table><tr><th>اسم</th><th>هاتف</th><th>رصيد</th><th>واتساب</th><th></th></tr>{tr}</table></div>"
    if v=='dishes':
        rs=ex(c,"SELECT * FROM dish_ips ORDER BY id DESC").fetchall()
        tr="".join([f"<tr><td dir=ltr>{dict(r)['ip'] or '-'}</td><td>{dict(r).get('location','')}</td><td>{dict(r).get('area','')}</td><td>{dict(r).get('tower','')}</td><td><a href='/del_dish/{dict(r)['id']}' style='color:red'>✖</a></td></tr>" for r in rs])
        return f"<div class='card glass'><h3>📡 الصحون - الكل اختياري</h3><form method=post action=/add_dish><div class=row2><input name=ip placeholder='IP (اختياري)' dir=ltr><input name=location placeholder='اسم الصحن (اختياري)'></div><div class=row2><input name=area placeholder='المنطقة (اختياري)'><input name=tower placeholder='البرج (اختياري)'></div><div class=row2><input name=lat type=number step=any placeholder='lat'><input name=lng type=number step=any placeholder='lng'></div><button>إضافة</button></form></div><div class='card glass'><table><tr><th>IP</th><th>اسم</th><th>منطقة</th><th>برج</th><th></th></tr>{tr}</table></div>"
    if v=='ping':
        rs=ex(c,"SELECT * FROM dish_ips ORDER BY id DESC").fetchall();tr=""
        for r in rs:
            d=dict(r);ok=ping(d['ip'] or '');dot="🟢 شغال" if ok else "🔴 فاصل"
            if not ok and d['ip']: notify(f"🔴 صحن فاصل: {d.get('location')} {d['ip']}")
            tr+=f"<tr><td>{dot}</td><td dir=ltr>{d['ip']}</td><td>{d.get('location','')}</td></tr>"
        return f"<div class='card glass'><h3>📶 Ping</h3><button onclick=\"loadView('ping',true)\">🔄 فحص</button></div><div class='card glass'><table><tr><th>حالة</th><th>IP</th><th>اسم</th></tr>{tr}</table></div>"
    if v=='towers':
        rs=ex(c,"SELECT * FROM towers ORDER BY id DESC").fetchall()
        tr="".join([f"<tr><td>{r['name']}</td><td>{r['lat']},{r['lng']}</td><td><a href='/del_tower/{r['id']}' style='color:red'>✖</a></td></tr>" for r in rs])
        return f"<div class='card glass'><h3>🗼 الأبراج</h3><form method=post action=/add_tower><input name=name placeholder='اسم البرج'><div class=row2><input name=lat type=number step=any placeholder='lat'><input name=lng type=number step=any placeholder='lng'></div><button>إضافة ويظهر بالخريطة</button></form></div><div class='card glass'><table><tr><th>اسم</th><th>إحداثيات</th><th></th></tr>{tr}</table></div>"
    if v=='map':
        dishes=ex(c,"SELECT location,lat,lng,ip FROM dish_ips WHERE lat!=0").fetchall();towers=ex(c,"SELECT name,lat,lng FROM towers").fetchall()
        pts=",".join([f"{{n:'📡 {r['location']} {r['ip']}',la:{r['lat']},ln:{r['lng']}}}" for r in dishes])
        if towers: pts+=","+",".join([f"{{n:'🗼 {r['name']}',la:{r['lat']},ln:{r['lng']}}}" for r in towers])
        pts=pts.strip(",")
        return f"<div class='card glass'><h3>🗺️ الخريطة</h3><div id=map></div></div><script>var m=L.map('map').setView([34.72,36.72],10);L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:19}}).addTo(m);var pts=[{pts}];pts.forEach(p=>L.marker([p.la,p.ln]).addTo(m).bindPopup(p.n));if(pts.length)m.fitBounds(pts.map(p=>[p.la,p.ln]));setTimeout(()=>m.invalidateSize(),500);</script>"
    if v=='ledger':
        if role not in ('super','admin'): return "<div class='card glass'>ممنوع</div>"
        rs=ex(c,"SELECT l.*,s.name sn FROM ledger l LEFT JOIN subs s ON s.id=l.sub_id ORDER BY l.id DESC LIMIT 300").fetchall()
        subs=ex(c,"SELECT id,name FROM subs").fetchall();opts="".join([f"<option value='{s['id']}'>{s['name']}</option>" for s in subs])
        tr="".join([f"<tr><td>{r['date']}</td><td>{r['sn']}</td><td>{r['type'] or ''}</td><td>{r['usd']}</td><td>{r['syr']}</td><td>{r['note'] or ''}</td></tr>" for r in rs])
        return f"<div class='card glass'><h3>📒 دفتر</h3><form method=post action=/charge><select name=sub_id>{opts}</select><div class=row2><input name=amount type=number step=0.01 required placeholder='مبلغ'><select name=currency><option value=usd>$</option><option value=syr>ل.س</option></select></div><div class=row2><select name=ttype><option>قبض</option><option>صرف</option><option>دين</option><option>شحن رصيد</option></select><input name=note placeholder='بيان'></div><button>تسجيل</button></form></div><div class='card glass'><table><tr><th>تاريخ</th><th>مشترك</th><th>نوع</th><th>$</th><th>ل.س</th><th>بيان</th></tr>{tr}</table></div>"
    if v=='report':
        today=datetime.date.today().isoformat();month=today[:7]
        r1=ex(c,"SELECT SUM(usd) s1,SUM(syr) s2 FROM ledger WHERE date LIKE?",(today+"%",)).fetchone()
        r2=ex(c,"SELECT SUM(usd) s1,SUM(syr) s2 FROM ledger WHERE date LIKE?",(month+"%",)).fetchone()
        a=dict(r1) if r1 else {};b=dict(r2) if r2 else {}
        return f"<div class='card glass'><h3>📊 تقرير</h3><p>اليوم {today}: {a.get('s1') or 0}$ | {a.get('s2') or 0}</p><p>الشهر {month}: {b.get('s1') or 0}$ | {b.get('s2') or 0}</p></div>"
    if v=='servers':
        rs=ex(c,"SELECT * FROM servers").fetchall();tr="".join([f"<tr><td>{r['name']}</td><td dir=ltr>{r['host']}</td></tr>" for r in rs])
        return f"<div class='card glass'><form method=post action=/add_srv><div class=row2><input name=name placeholder='اسم' required><input name=host placeholder='host' dir=ltr required></div><button>إضافة</button></form></div><div class='card glass'><table>{tr}</table></div>"
    if v=='notifs':
        rs=ex(c,"SELECT * FROM notifications ORDER BY id DESC LIMIT 100").fetchall();ex(c,"UPDATE notifications SET seen=1");c.commit()
        t="".join([f"<div class='card glass'>🔔 {r['msg']}<br><small>{r['date']}</small></div>" for r in rs])
        return f"<h3>🔔 إشعارات</h3>{t or '<div class=card>لا يوجد</div>'}"
    if v=='logs':
        rs=ex(c,"SELECT * FROM login_logs ORDER BY id DESC LIMIT 150").fetchall()
        tr="".join([f"<tr><td>{r['phone']}</td><td>{r['date']}</td><td dir=ltr>{r['ip']}</td></tr>" for r in rs])
        return f"<div class='card glass'><h3>📝 سجل الدخول</h3><table><tr><th>مستخدم</th><th>وقت</th><th>IP</th></tr>{tr}</table></div>"
    if v=='settings':
        us=ex(c,"SELECT * FROM users").fetchall();tr=""
        for u in us:
            st="✅ نشط" if u['active']==1 else "⛔ معطل"
            tr+=f"<tr><td>{u['phone']}<br><small>{u['username']}</small></td><td>{u['role']}</td><td>{st}</td><td><a href='/toggle_user/{u['phone']}'>⏯️</a> <a href='/del_user/{u['phone']}' style='color:red'>✖</a></td></tr>"
        return f"<div class='card glass'><h3>⚙️ إضافة مستخدم</h3><form method=post action=/add_user><div class=row2><input name=phone placeholder='رقم الهاتف' required><input name=username placeholder='اسم المستخدم' required></div><div class=row2><input name=password placeholder='كلمة السر' required><select name=role><option value='tech'>فني</option><option value='admin'>مدير</option></select></div><button>إضافة</button></form></div><div class='card glass'><table><tr><th>هاتف / يوزر</th><th>دور</th><th>حالة</th><th>تحكم</th></tr>{tr}</table></div>"
    if v=='support':
        return f"<div class='card glass' style='text-align:center'><h3>🛠️ الدعم الفني</h3><h2 dir=ltr>{SUPPORT}</h2><div class=row2><button onclick=\"window.open('https://wa.me/{SUPPORT}','_blank')\">💬 واتساب</button><button onclick=\"location.href='tel:{SUPPORT}'\">📞 اتصال</button></div></div>"
    return "<div class='card glass'>...</div>"

def base_html(content,curview):
    col=get_colors()
    con=db()
    try:nn=len(ex(con,"SELECT id FROM notifications WHERE seen=0").fetchall())
    except:nn=0
    cc(con)
    role=session.get('role','tech')
    ledger_link='<a href="#" data-v="ledger">📒 الحسابات</a>' if role in ('super','admin') else ''
    return f"""<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OMAIA ISP</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
*{{box-sizing:border-box}}body{{margin:0;font-family:'Segoe UI',Tahoma;{get_bg_css()};color:{col['text']};min-height:100vh;overflow-x:hidden}}
.glass{{background:rgba(255,255,255,0.07)!important;backdrop-filter:blur(22px) saturate(180%);-webkit-backdrop-filter:blur(22px) saturate(180%);border:1px solid rgba(255,255,255,0.14)!important;box-shadow:0 8px 32px #0006!important}}
.top{{position:fixed;top:0;right:0;left:0;height:62px;display:flex;align-items:center;justify-content:space-between;padding:0 14px;z-index:1002;background:rgba(20,20,30,0.65);backdrop-filter:blur(20px);border-bottom:1px solid rgba(255,255,255,0.1)}}
#mb{{width:110px;height:42px;border-radius:20px;border:none;background:linear-gradient(135deg,{col['main']},#7c3aed);font-weight:900;color:#fff}}
.sb{{position:fixed;top:72px;right:10px;width:270px;border-radius:20px;padding:12px;z-index:1003;transition:transform.55s cubic-bezier(.22,1,.36,1),opacity.4s;max-height:84vh;overflow:auto}}
.sb.hide{{transform:translateX(120%);opacity:0;pointer-events:none}}
.sb a{{display:block;padding:13px;margin:6px 0;background:rgba(255,255,255,0.05);text-decoration:none;border-radius:14px;color:{col['text']};font-weight:600;transition:all.4s cubic-bezier(.22,1,.36,1)}}
.sb a:hover,.sb a.active{{background:linear-gradient(135deg,{col['main']},#7c3aed);color:#fff;transform:translateX(-6px) scale(1.02)}}
.mn{{padding:84px 16px 20px;max-width:1150px;margin:auto;transition:opacity.35s ease,transform.45s cubic-bezier(.22,1,.36,1)}}
.mn.fade{{opacity:0;transform:translateY(14px) scale(.99)}}
.card{{padding:18px;border-radius:22px;margin:14px 0;animation:slideIn.55s cubic-bezier(.22,1,.36,1)}}
@keyframes slideIn{{from{{opacity:0;transform:translateY(20px)}}to{{opacity:1;transform:translateY(0)}}}}
.stat{{border-radius:20px;padding:20px;text-align:center}}.stat h2{{font-size:36px;margin:0;color:{col['main']}}}
table{{width:100%;border-collapse:collapse;font-size:14px}}th,td{{padding:11px;border-bottom:1px solid #ffffff15;text-align:center}}th{{color:{col['main']}}}
input,select{{width:100%;padding:12px;margin:6px 0;border-radius:14px;border:1px solid rgba(255,255,255,0.15);background:rgba(255,255,255,0.06);color:{col['text']}}}
button{{padding:13px;width:100%;border:none;border-radius:14px;font-weight:900;background:linear-gradient(135deg,{col['main']},#7c3aed);color:#fff;cursor:pointer;transition:transform.2s}}button:active{{transform:scale(.97)}}
.row2{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}.row4{{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:12px}}
@media(max-width:700px){{.row4{{grid-template-columns:1fr 1fr}}}}
#map{{height:420px;border-radius:18px;z-index:1}}
#ptr{{position:fixed;top:70px;left:50%;transform:translateX(-50%) translateY(-90px);transition:transform.35s;z-index:1005;background:rgba(255,255,255,0.15);backdrop-filter:blur(15px);padding:10px 20px;border-radius:20px}}
#loader{{position:fixed;top:62px;right:0;left:0;height:3px;z-index:1006;background:linear-gradient(90deg,{col['main']},#7c3aed);transform:scaleX(0);transform-origin:right;transition:transform.35s}}
.wa{{position:fixed;bottom:20px;left:20px;z-index:9999;width:62px;height:62px;border-radius:50%;background:#25D366;display:flex;align-items:center;justify-content:center;font-size:32px;text-decoration:none}}
</style></head><body>
<div id=loader></div><div id=ptr>⬇️ اسحب للتحديث</div>
<div class="top"><button id="mb">☰ Menu</button><b style="color:{col['main']};margin:auto;font-size:20px">✨ OMAIA ISP</b><div>🔔{nn if nn else ''}</div></div>
<div class="sb glass hide" id="sb">
<a href="#" data-v="home">🏠 الرئيسية</a>
<a href="#" data-v="subs">👥 المشتركين</a>
<a href="#" data-v="dishes">📡 الصحون</a>
<a href="#" data-v="map">🗺️ الخريطة</a>
<a href="#" data-v="ping">📶 فحص Ping</a>
{ledger_link}
<a href="#" data-v="towers">🗼 الأبراج</a>
<a href="#" data-v="report">📊 تقرير</a>
<a href="#" data-v="servers">🖥️ سيرفرات</a>
<a href="#" data-v="notifs">🔔 إشعارات</a>
<a href="#" data-v="logs">📝 سجل الدخول</a>
<a href="#" data-v="settings">⚙️ الإعدادات</a>
<a href="#" data-v="support">🛠️ دعم فني</a>
<a href="/logout">🚪 خروج</a></div>
<div class="mn" id="mn">{content}</div>
<a class="wa" href="https://wa.me/{SUPPORT}" target="_blank">💬</a>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
let cache={{}},curView="{curview}",sb=document.getElementById('sb'),mn=document.getElementById('mn'),loader=document.getElementById('loader'),ptr=document.getElementById('ptr');
document.getElementById('mb').onclick=e=>{{e.stopPropagation();sb.classList.toggle('hide')}};
document.addEventListener('click',e=>{{if(!sb.classList.contains('hide')&&!sb.contains(e.target)&&e.target.id!=='mb')sb.classList.add('hide')}});
function setActive(v){{document.querySelectorAll('[data-v]').forEach(a=>a.classList.toggle('active',a.dataset.v===v))}}
async function loadView(v,force=false){{
 if(!force&&cache[v]){{mn.innerHTML=cache[v];setActive(v);curView=v;history.replaceState(null,'','/dash#'+v);bindScripts();return}}
 loader.style.transform='scaleX(0.7)';mn.classList.add('fade');
 try{{let r=await fetch('/api/view?v='+v);let h=await r.text();cache[v]=h;mn.innerHTML=h;setActive(v);curView=v;history.replaceState(null,'','/dash#'+v);window.scrollTo({{top:0,behavior:'smooth'}});bindScripts();}}catch(e){{}}
 mn.classList.remove('fade');loader.style.transform='scaleX(1)';setTimeout(()=>loader.style.transform='scaleX(0)',400);sb.classList.add('hide');
}}
function bindScripts(){{mn.querySelectorAll('script').forEach(s=>{{let ns=document.createElement('script');ns.textContent=s.textContent;document.body.appendChild(ns);s.remove()}})}}
document.querySelectorAll('[data-v]').forEach(a=>{{a.onclick=e=>{{e.preventDefault();loadView(a.dataset.v)}}}});
let sy=0,pull=0;
document.addEventListener('touchstart',e=>{{sy=e.touches[0].clientY}},{{passive:true}});
document.addEventListener('touchmove',e=>{{if(window.scrollY==0){{pull=e.touches[0].clientY-sy;if(pull>0){{ptr.style.transform=`translateX(-50%) translateY(${{Math.min(pull-90,0)}}px)`;if(pull>130)ptr.innerHTML='🔄 اترك للتحديث'}}}}},{{passive:true}});
document.addEventListener('touchend',()=>{{if(pull>130){{delete cache[curView];loadView(curView,true)}}ptr.style.transform='translateX(-50%) translateY(-90px)';ptr.innerHTML='⬇️ اسحب للتحديث';pull=0}});
setActive(curView);
if(location.hash){{let hv=location.hash.replace('#','');if(hv)loadView(hv)}}
</script></body></html>"""

@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')

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
        m="<p style='color:#ff6b6b'>خطأ بالدخول أو الحساب معطل</p>"
    col=get_colors()
    return f"""<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>دخول - OMAIA ISP</title><style>
body{{margin:0;font-family:'Segoe UI';{get_bg_css()};color:{col['text']}}}
.wrap{{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}}
.box{{background:rgba(255,255,255,0.08);backdrop-filter:blur(25px);border:1px solid rgba(255,255,255,0.15);border-radius:28px;padding:44px 32px;max-width:400px;width:100%;text-align:center}}
.box h1{{font-size:38px;margin:0;background:linear-gradient(135deg,{col['main']},#7c3aed);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
input{{width:100%;padding:14px;margin:8px 0;border-radius:14px;border:1px solid #ffffff22;background:#ffffff08;color:{col['text']}}}
button{{width:100%;padding:15px;border:none;border-radius:14px;font-weight:900;background:linear-gradient(135deg,{col['main']},#7c3aed);color:#fff}}
</style></head><body><div class="wrap"><div class="box"><div style="font-size:60px">🌐</div><h1>OMAIA ISP</h1><div style="height:14px"></div>{m}<form method=post><input name=phone placeholder="رقم الهاتف / اسم المستخدم" required><input name=password type=password placeholder="كلمة السر" required><button>✨ دخول</button></form><p>الدعم الفني <a href="https://wa.me/{SUPPORT}" style="color:{col['main']}" dir="ltr">{SUPPORT}</a></p></div></div></body></html>"""

@app.route('/logout')
def lo(): session.clear();return redirect('/login')

@app.route('/dash')
def dash():
    if not session.get('phone'):return redirect('/login')
    v=request.args.get('view','home')
    if '#' in v: v=v.split('#')[0]
    # دعم الهاش
    c=db();html=get_view_html(v,c,session.get('role','tech'));cc(c)
    return render_template_string(base_html(html,v))

@app.route('/api/view')
def apiv():
    if not session.get('phone'):return "no"
    v=request.args.get('v','home');c=db();h=get_view_html(v,c,session.get('role','tech'));cc(c);return h

@app.route('/search')
def search():
    if not session.get('phone'):return redirect('/login')
    q=request.args.get('q','');c=db()
    r1=ex(c,"SELECT name,phone FROM subs WHERE name LIKE? OR phone LIKE?",(f"%{q}%",f"%{q}%")).fetchall() if q else []
    r2=ex(c,"SELECT location,ip FROM dish_ips WHERE location LIKE? OR ip LIKE?",(f"%{q}%",f"%{q}%")).fetchall() if q else []
    cc(c)
    t="".join([f"<tr><td>👤 {r['name']}</td><td>{r['phone']}</td></tr>" for r in r1])
    t+="".join([f"<tr><td>📡 {r['location']}</td><td dir=ltr>{r['ip']}</td></tr>" for r in r2])
    col=get_colors()
    return f"<div class='card glass'><form><input name=q value='{q}' placeholder='بحث...'><button>🔍</button></form></div><div class='card glass'><table>{t}</table></div>"

@app.route('/add_sub',methods=['POST'])
def a1():c=db();ex(c,"INSERT INTO subs(name,phone,status) VALUES(?,?,?)",(request.form['name'],request.form['phone'],'نشط'));c.commit();cc(c);return redirect('/dash#subs')
@app.route('/del_sub/<int:i>')
def d1(i):c=db();ex(c,"DELETE FROM subs WHERE id=?",(i,));c.commit();cc(c);return redirect('/dash#subs')
@app.route('/add_dish',methods=['POST'])
def a2():
    c=db();f=request.form
    try:lat=float(f.get('lat') or 0)
    except:lat=0
    try:lng=float(f.get('lng') or 0)
    except:lng=0
    ex(c,"INSERT INTO dish_ips(ip,location,site,area,tower,lat,lng) VALUES(?,?,?,?,?,?,?)",(f.get('ip') or '',f.get('location') or '',f.get('tower') or '',f.get('area') or '',f.get('tower') or '',lat,lng));c.commit();cc(c);return redirect('/dash#dishes')
@app.route('/del_dish/<int:i>')
def d2(i):c=db();ex(c,"DELETE FROM dish_ips WHERE id=?",(i,));c.commit();cc(c);return redirect('/dash#dishes')
@app.route('/add_tower',methods=['POST'])
def at():c=db();ex(c,"INSERT INTO towers(name,lat,lng,note) VALUES(?,?,?,?)",(request.form.get('name') or '',float(request.form.get('lat') or 0),float(request.form.get('lng') or 0),''));c.commit();cc(c);return redirect('/dash#towers')
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
@app.route('/edit_user/<ph>',methods=['POST'])
def eu(ph):c=db();ex(c,"UPDATE users SET username=?,password=?,role=? WHERE phone=?",(request.form['username'],request.form['password'],request.form['role'],ph));c.commit();cc(c);return redirect('/dash#settings')
@app.route('/del_user/<ph>')
def du(ph):
    if ph=='05344851045':return redirect('/dash#settings')
    c=db();ex(c,"DELETE FROM users WHERE phone=?",(ph,));c.commit();cc(c);return redirect('/dash#settings')
@app.route('/toggle_user/<ph>')
def tu(ph):c=db();u=ex(c,"SELECT active FROM users WHERE phone=?",(ph,)).fetchone();na=0 if dict(u)['active']==1 else 1;ex(c,"UPDATE users SET active=? WHERE phone=?",(na,ph));c.commit();cc(c);return redirect('/dash#settings')
@app.route('/charge',methods=['POST'])
def ch():
    sid=request.form['sub_id'];amt=float(request.form['amount']);cur=request.form['currency'];typ=request.form.get('ttype','قبض');note=request.form.get('note','')
    usd=amt if cur=='usd' else 0;syr=amt if cur=='syr' else 0;c=db()
    ex(c,"INSERT INTO ledger(sub_id,date,usd,syr,type,note,by_user) VALUES(?,?,?,?,?,?,?)",(sid,datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),usd,syr,typ,note,session.get('phone')))
    if typ in ('قبض','شحن رصيد'):ex(c,"UPDATE subs SET balance_usd=balance_usd+?,balance_syr=balance_syr+? WHERE id=?",(usd,syr,sid))
    else:ex(c,"UPDATE subs SET balance_usd=balance_usd-?,balance_syr=balance_syr-? WHERE id=?",(usd,syr,sid))
    c.commit();cc(c);return redirect('/dash#ledger')
@app.route('/export_subs')
def es():
    c=db();rs=ex(c,"SELECT name,phone,balance_usd,balance_syr FROM subs").fetchall();cc(c)
    o=io.StringIO();w=csv.writer(o);w.writerow(['name','phone','usd','syr'])
    for r in rs:w.writerow([r['name'],r['phone'],r['balance_usd'],r['balance_syr']])
    return Response(o.getvalue().encode('utf-8-sig'),mimetype='text/csv',headers={'Content-Disposition':'attachment;filename=subs.csv'})
@app.route('/export_ledger')
def el():
    c=db();rs=ex(c,"SELECT date,usd,syr,type,note FROM ledger").fetchall();cc(c)
    o=io.StringIO();w=csv.writer(o);w.writerow(['date','usd','syr','type','note'])
    for r in rs:w.writerow([r['date'],r['usd'],r['syr'],r['type'],r['note']])
    return Response(o.getvalue().encode('utf-8-sig'),mimetype='text/csv',headers={'Content-Disposition':'attachment;filename=ledger.csv'})
if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
