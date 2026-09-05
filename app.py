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
    try:socket.create_connection((ip.strip(),80),timeout=1).close();return True
    except:
        try:socket.create_connection((ip.strip(),22),timeout=1).close();return True
        except:return False
def notify(m):
    try:
        c=db()
        if not ex(c,"SELECT id FROM notifications WHERE msg=?",(m,)).fetchone():
            ex(c,"INSERT INTO notifications(msg,date,seen) VALUES(?,?,0)",(m,datetime.datetime.now().strftime("%Y-%m-%d %H:%M")));c.commit()
        cc(c)
    except:pass

def base_html(content):
    col=get_colors()
    con=db()
    try:nn=len(ex(con,"SELECT id FROM notifications WHERE seen=0").fetchall())
    except:nn=0
    cc(con)
    role=session.get('role','tech')
    ledger_link='<a href="/dash?view=ledger" data-v="ledger">📒 الحسابات</a>' if role in ('super','admin') else ''
    return f"""<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OMIA ISP</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}
body{{margin:0;font-family:'Segoe UI',Tahoma;{get_bg_css()};color:{col['text']};min-height:100vh}}
.top{{position:fixed;top:0;right:0;left:0;height:62px;display:flex;align-items:center;justify-content:space-between;padding:0 14px;z-index:1002;background:{col['card']};border-bottom:2px solid {col['main']}}}
#mb{{width:110px;height:42px;border-radius:20px;border:none;background:linear-gradient(135deg,{col['main']},#0090c0);font-weight:900;cursor:grab;touch-action:none;position:absolute;color:#fff}}
.sb{{position:fixed;top:72px;width:270px;border-radius:18px;padding:12px;z-index:1003;background:{col['card']};transition:transform .45s cubic-bezier(.22,1,.36,1),opacity .3s;box-shadow:0 15px 40px #0008;max-height:84vh;overflow:auto;border:1px solid {col['main']}44}}
.sb.hide{{transform:translateX(120%);opacity:0;pointer-events:none}}
.sb a{{display:block;padding:13px;margin:6px 0;background:#ffffff08;text-decoration:none;border-radius:12px;color:{col['text']};font-weight:600}}
.sb a:hover{{background:{col['main']};color:#fff;transform:translateX(-5px)}}
.sb a.active{{border:1px solid {col['main']};color:{col['main']}}}
.mn{{padding:84px 16px 20px;max-width:1150px;margin:auto}}
.card{{background:{col['card']};padding:18px;border-radius:20px;margin:14px 0;border:1px solid {col['main']}22;box-shadow:0 8px 30px #0004}}
.stat{{background:linear-gradient(135deg,{col['main']}22,transparent);border:1px solid {col['main']}44;border-radius:18px;padding:20px;text-align:center}}
.stat h2{{font-size:36px;margin:0;color:{col['main']}}}
table{{width:100%;border-collapse:collapse;font-size:14px}}th,td{{padding:11px;border-bottom:1px solid #ffffff15;text-align:center}}th{{color:{col['main']}}}
input,select{{width:100%;padding:12px;margin:6px 0;border-radius:12px;border:1.5px solid #ffffff22;background:#ffffff08;color:{col['text']}}}
button{{padding:13px;width:100%;border:none;border-radius:12px;font-weight:900;background:linear-gradient(135deg,{col['main']},#0090c0);color:#fff;cursor:pointer}}
.row2{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}.row4{{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:12px}}
@media(max-width:700px){{.row4{{grid-template-columns:1fr 1fr}}}}
#map{{height:420px;border-radius:18px;z-index:1}}
.wa{{position:fixed;bottom:20px;left:20px;z-index:9999;width:62px;height:62px;border-radius:50%;background:#25D366;display:flex;align-items:center;justify-content:center;font-size:32px;text-decoration:none}}
.bdg{{background:red;color:#fff;border-radius:10px;padding:2px 7px;font-size:11px}}
</style></head><body>
<div class="top"><button id="mb">☰ Menu</button><b style="color:{col['main']};margin:auto;font-size:20px">✨ OMIA ISP</b><div><a href="/dash?view=notifs" style="text-decoration:none">🔔<span class="bdg">{nn if nn else ''}</span></a> <a href="/search" style="text-decoration:none">🔍</a></div></div>
<div class="sb hide" id="sb">
<a href="/dash?view=home" data-v="home">🏠 الرئيسية</a>
<a href="/dash?view=subs" data-v="subs">👥 المشتركين</a>
<a href="/dash?view=dishes" data-v="dishes">📡 الصحون</a>
<a href="/dash?view=ping" data-v="ping">📶 فحص Ping</a>
{ledger_link}
<a href="/dash?view=towers" data-v="towers">🗼 الأبراج</a>
<a href="/dash?view=map" data-v="map">🗺️ الخريطة</a>
<a href="/dash?view=report" data-v="report">📊 تقرير</a>
<a href="/dash?view=servers" data-v="servers">🖥️ سيرفرات</a>
<a href="/dash?view=notifs" data-v="notifs">🔔 إشعارات</a>
<a href="/dash?view=logs" data-v="logs">📝 سجل الدخول</a>
<a href="/dash?view=settings" data-v="settings">⚙️ الإعدادات</a>
<a href="/dash?view=support" data-v="support">🛠️ دعم</a>
<a href="/logout">🚪 خروج</a></div>
<div class="mn">{content}</div>
<a class="wa" href="https://wa.me/{SUPPORT}" target="_blank">💬</a>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
let sb=document.getElementById('sb'),b=document.getElementById('mb');
b.onclick=e=>{{e.stopPropagation();sb.classList.toggle('hide')}};
let dx=0,dy=0,dg=false,sx,sy;
b.addEventListener('pointerdown',e=>{{dg=true;sx=e.clientX-dx;sy=e.clientY-dy;b.setPointerCapture(e.pointerId)}});
b.addEventListener('pointermove',e=>{{if(!dg)return;dx=e.clientX-sx;dy=e.clientY-sy;b.style.transform=`translate(${{dx}}px,${{dy}}px)`}});
b.addEventListener('pointerup',()=>dg=false);
document.addEventListener('click',e=>{{if(!sb.classList.contains('hide')&&!sb.contains(e.target)&&e.target!==b)sb.classList.add('hide')}});
let v=new URLSearchParams(location.search).get('view')||'home';
document.querySelectorAll('[data-v]').forEach(a=>{{if(a.dataset.v===v)a.classList.add('active')}});
</script></body></html>"""

def render(c): return render_template_string(base_html(c))

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
            ex(c,"INSERT INTO login_logs(phone,date,ip) VALUES(?,?,?)",(d['phone'],datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),request.remote_addr));c.commit();cc(c);return redirect('/dash?view=home')
        try:cc(c)
        except:pass
        m="<p style='color:#ff6b6b'>خطأ بالدخول أو الحساب معطل</p>"
    col=get_colors()
    return f"""<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>دخول</title><style>
body{{margin:0;font-family:'Segoe UI',Tahoma;{get_bg_css()};color:{col['text']}}}
.wrap{{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px;background:radial-gradient(circle at 30% 20%,{col['main']}33,transparent 50%),radial-gradient(circle at 70% 80%,#7c3aed33,transparent 50%)}}
.box{{background:#ffffff0a;backdrop-filter:blur(20px);border:1px solid #ffffff22;border-radius:28px;padding:44px 32px;max-width:400px;width:100%;text-align:center;box-shadow:0 25px 60px #0008}}
.box h1{{font-size:46px;margin:0;background:linear-gradient(135deg,{col['main']},#7c3aed);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
input{{width:100%;padding:14px;margin:8px 0;border-radius:14px;border:1.5px solid #ffffff22;background:#ffffff08;color:{col['text']}}}
button{{width:100%;padding:15px;border:none;border-radius:14px;font-weight:900;background:linear-gradient(135deg,{col['main']},#7c3aed);color:#fff;cursor:pointer}}
</style></head><body><div class="wrap"><div class="box"><div style="font-size:60px">🌐</div><h1>OMIA</h1><p style="opacity:.6;letter-spacing:4px">ISP MANAGEMENT</p>{m}<form method=post><input name=phone placeholder="رقم الهاتف / اسم المستخدم" required><input name=password type=password placeholder="كلمة السر" required><button>✨ دخول</button></form><p style="opacity:.6">دعم <a href="https://wa.me/{SUPPORT}" style="color:{col['main']}">{SUPPORT}</a></p></div></div></body></html>"""

@app.route('/logout')
def lo(): session.clear();return redirect('/login')

@app.route('/dash')
def dash():
    if not session.get('phone'):return redirect('/login')
    v=request.args.get('view','home');c=db();role=session.get('role','tech')
    def done(h):
        r=render(h);cc(c);return r
    if v=='home':
        ns=len(ex(c,"SELECT id FROM subs").fetchall());nd=len(ex(c,"SELECT id FROM dish_ips").fetchall());nt=len(ex(c,"SELECT id FROM towers").fetchall());nl=len(ex(c,"SELECT id FROM ledger").fetchall())
        today=datetime.date.today().isoformat()
        r1=ex(c,"SELECT SUM(usd) s1 FROM ledger WHERE date LIKE?",(today+"%",)).fetchone();inc=(dict(r1).get('s1') or 0) if r1 else 0
        return done(f"""<div class="card" style="text-align:center;background:linear-gradient(135deg,#00D4FF22,#7c3aed22)"><h2>👋 أهلاً بك</h2><p>📅 {today} | 💰 دخل اليوم: <b>{inc}$</b></p></div><div class="row4"><div class="stat"><h2>{ns}</h2><p>👥 مشتركين</p></div><div class="stat"><h2>{nd}</h2><p>📡 صحون</p></div><div class="stat"><h2>{nt}</h2><p>🗼 أبراج</p></div><div class="stat"><h2>{nl}</h2><p>📒 قيود</p></div></div><div class="row2"><div class="card"><h3>⚡ سريع</h3><div class="row2"><button onclick="location.href='/dash?view=subs'">+ مشترك</button><button onclick="location.href='/dash?view=dishes'">+ صحن</button></div><div class="row2" style="margin-top:8px"><button onclick="location.href='/dash?view=ping'">📶 Ping</button><button onclick="location.href='/dash?view=map'">🗺️ خريطة</button></div></div><div class="card"><h3>🛠️ دعم</h3><p dir=ltr>{SUPPORT}</p><button onclick="window.open('https://wa.me/{SUPPORT}','_blank')">💬 واتساب</button></div></div>""")
    if v=='subs':
        rs=ex(c,"SELECT * FROM subs ORDER BY id DESC").fetchall()
        tr="".join([f"<tr><td>{r['name']}</td><td dir=ltr>{r['phone']}</td><td>{r['balance_usd']}$</td><td><a href='https://wa.me/{r['phone']}' target=_blank>💬</a></td><td><a href='/del_sub/{r['id']}' style='color:red'>✖</a></td></tr>" for r in rs])
        return done(f"<div class='card'><form method=post action=/add_sub><div class=row2><input name=name placeholder='الاسم' required><input name=phone placeholder='هاتف' required></div><button>إضافة مشترك</button></form></div><div class='card'><button onclick=\"location.href='/export_subs'\">📥 Excel</button></div><div class='card'><table><tr><th>اسم</th><th>هاتف</th><th>رصيد</th><th>واتساب</th><th></th></tr>{tr}</table></div>")
    if v=='dishes':
        rs=ex(c,"SELECT * FROM dish_ips ORDER BY id DESC").fetchall()
        tr="".join([f"<tr><td dir=ltr><a href='http://{dict(r)['ip']}' target=_blank style='color:#00D4FF'>{dict(r)['ip']}</a></td><td>{dict(r).get('location','')}</td><td>{dict(r).get('area','')}</td><td>{dict(r).get('tower','')}</td><td><a href='/del_dish/{dict(r)['id']}' style='color:red'>✖</a></td></tr>" for r in rs])
        return done(f"<div class='card'><h3>📡 الصحون</h3><form method=post action=/add_dish><div class=row2><input name=ip placeholder='IP' dir=ltr required><input name=location placeholder='اسم الصحن' required></div><div class=row2><input name=area placeholder='المنطقة' required><input name=tower placeholder='البرج' required></div><button>إضافة</button></form></div><div class='card'><table><tr><th>IP</th><th>اسم</th><th>منطقة</th><th>برج</th><th></th></tr>{tr}</table></div>")
    if v=='ping':
        rs=ex(c,"SELECT * FROM dish_ips ORDER BY id DESC").fetchall();tr=""
        for r in rs:
            d=dict(r);ok=ping(d['ip'] or 'x');dot="🟢 شغال" if ok else "🔴 فاصل"
            if not ok:notify(f"🔴 صحن فاصل: {d.get('location')} {d['ip']}")
            tr+=f"<tr><td>{dot}</td><td dir=ltr>{d['ip']}</td><td>{d.get('location','')}</td></tr>"
        return done(f"<div class='card'><h3>📶 Ping قسم لحاله</h3><button onclick='location.reload()'>🔄 فحص</button></div><div class='card'><table><tr><th>حالة</th><th>IP</th><th>اسم</th></tr>{tr}</table></div>")
    if v=='towers':
        rs=ex(c,"SELECT * FROM towers ORDER BY id DESC").fetchall()
        tr="".join([f"<tr><td>{r['name']}</td><td>{r['lat']},{r['lng']}</td><td><a href='/del_tower/{r['id']}' style='color:red'>✖</a></td></tr>" for r in rs])
        return done(f"<div class='card'><h3>🗼 الأبراج</h3><form method=post action=/add_tower><input name=name placeholder='اسم البرج' required><div class=row2><input name=lat type=number step=any placeholder='lat' required><input name=lng type=number step=any placeholder='lng' required></div><button>إضافة ويظهر بالخريطة</button></form></div><div class='card'><table><tr><th>اسم</th><th>إحداثيات</th><th></th></tr>{tr}</table></div>")
    if v=='map':
        dishes=ex(c,"SELECT location,lat,lng,ip FROM dish_ips WHERE lat!=0").fetchall();towers=ex(c,"SELECT name,lat,lng FROM towers").fetchall()
        pts=",".join([f"{{n:'📡 {r['location']} {r['ip']}',la:{r['lat']},ln:{r['lng']}}}" for r in dishes])
        if towers: pts+=","+",".join([f"{{n:'🗼 {r['name']}',la:{r['lat']},ln:{r['lng']}}}" for r in towers])
        pts=pts.strip(",")
        return done(f"<div class='card'><h3>🗺️ الخريطة</h3><div id=map></div></div><script>var m=L.map('map').setView([34.72,36.72],10);L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:19}}).addTo(m);var pts=[{pts}];pts.forEach(p=>L.marker([p.la,p.ln]).addTo(m).bindPopup(p.n));if(pts.length)m.fitBounds(pts.map(p=>[p.la,p.ln]));setTimeout(()=>m.invalidateSize(),500);</script>")
    if v=='ledger':
        if role not in ('super','admin'):return redirect('/dash?view=home')
        rs=ex(c,"SELECT l.*,s.name sn FROM ledger l LEFT JOIN subs s ON s.id=l.sub_id ORDER BY l.id DESC LIMIT 300").fetchall()
        subs=ex(c,"SELECT id,name FROM subs").fetchall();opts="".join([f"<option value='{s['id']}'>{s['name']}</option>" for s in subs])
        tr="".join([f"<tr><td>{r['date']}</td><td>{r['sn']}</td><td>{r['type'] or ''}</td><td>{r['usd']}</td><td>{r['syr']}</td><td>{r['note'] or ''}</td></tr>" for r in rs])
        return done(f"<div class='card'><h3>📒 دفتر</h3><form method=post action=/charge><select name=sub_id>{opts}</select><div class=row2><input name=amount type=number step=0.01 required placeholder='مبلغ'><select name=currency><option value=usd>$</option><option value=syr>ل.س</option></select></div><div class=row2><select name=ttype><option>قبض</option><option>صرف</option><option>دين</option><option>شحن رصيد</option></select><input name=note placeholder='بيان'></div><button>تسجيل</button></form></div><div class='card'><div class=row2><button onclick=\"location.href='/export_ledger'\">📥 Excel</button><button onclick=\"window.print()\">🖨️ PDF</button></div></div><div class='card'><table><tr><th>تاريخ</th><th>مشترك</th><th>نوع</th><th>$</th><th>ل.س</th><th>بيان</th></tr>{tr}</table></div>")
    if v=='report':
        today=datetime.date.today().isoformat();month=today[:7]
        r1=ex(c,"SELECT SUM(usd) s1,SUM(syr) s2 FROM ledger WHERE date LIKE?",(today+"%",)).fetchone()
        r2=ex(c,"SELECT SUM(usd) s1,SUM(syr) s2 FROM ledger WHERE date LIKE?",(month+"%",)).fetchone()
        a=dict(r1) if r1 else {};b=dict(r2) if r2 else {}
        return done(f"<div class='card'><h3>📊 تقرير</h3><p>اليوم {today}: {a.get('s1') or 0}$ | {a.get('s2') or 0}</p><p>الشهر {month}: {b.get('s1') or 0}$ | {b.get('s2') or 0}</p><div class=row2><button onclick=\"location.href='/export_ledger'\">📥 Excel</button><button onclick=\"window.print()\">🖨️ PDF</button></div></div>")
    if v=='servers':
        rs=ex(c,"SELECT * FROM servers").fetchall();tr="".join([f"<tr><td>{r['name']}</td><td dir=ltr>{r['host']}</td></tr>" for r in rs])
        return done(f"<div class='card'><form method=post action=/add_srv><div class=row2><input name=name placeholder='اسم' required><input name=host placeholder='host' dir=ltr required></div><button>إضافة</button></form></div><div class='card'><table>{tr}</table></div>")
    if v=='notifs':
        rs=ex(c,"SELECT * FROM notifications ORDER BY id DESC LIMIT 100").fetchall();ex(c,"UPDATE notifications SET seen=1");c.commit()
        t="".join([f"<div class='card'>🔔 {r['msg']}<br><small>{r['date']}</small></div>" for r in rs])
        return done(f"<h3>🔔 إشعارات</h3>{t or '<div class=card>لا يوجد</div>'}")
    if v=='logs':
        rs=ex(c,"SELECT * FROM login_logs ORDER BY id DESC LIMIT 150").fetchall()
        tr="".join([f"<tr><td>{r['phone']}</td><td>{r['date']}</td><td dir=ltr>{r['ip']}</td></tr>" for r in rs])
        return done(f"<div class='card'><h3>📝 سجل الدخول</h3><table><tr><th>مستخدم</th><th>وقت</th><th>IP</th></tr>{tr}</table></div>")
    if v=='settings':
        us=ex(c,"SELECT * FROM users").fetchall();tr=""
        for u in us:
            st="✅ نشط" if u['active']==1 else "⛔ معطل"
            tr+=f"<tr><td>{u['phone']}<br><small>{u['username']}</small></td><td>{u['role']}</td><td>{st}</td><td><a href='/toggle_user/{u['phone']}'>⏯️</a> <a href='/del_user/{u['phone']}' style='color:red'>✖</a> <a href='/dash?view=settings&edit={u['phone']}'>✏️</a></td></tr>"
        edit_html=""
        ep=request.args.get('edit')
        if ep:
            eu=ex(c,"SELECT * FROM users WHERE phone=?",(ep,)).fetchone()
            if eu: edit_html=f"<div class='card'><h3>✏️ تعديل {eu['phone']}</h3><form method=post action=/edit_user/{eu['phone']}><input name=username value='{eu['username']}' required><input name=password value='{eu['password']}' required><select name=role><option value='admin' {'selected' if eu['role']=='admin' else ''}>مدير</option><option value='tech' {'selected' if eu['role']=='tech' else ''}>فني</option><option value='super' {'selected' if eu['role']=='super' else ''}>سوبر</option></select><button>حفظ</button></form></div>"
        return done(f"<div class='card'><h3>⚙️ إضافة مستخدم</h3><form method=post action=/add_user><div class=row2><input name=phone placeholder='رقم الهاتف' required><input name=username placeholder='اسم المستخدم' required></div><div class=row2><input name=password placeholder='كلمة السر' required><select name=role><option value='tech'>فني</option><option value='admin'>مدير</option></select></div><button>إضافة</button></form></div>{edit_html}<div class='card'><table><tr><th>هاتف / يوزر</th><th>دور</th><th>حالة</th><th>تحكم</th></tr>{tr}</table></div>")
    if v=='support':
        return done(f"<div class='card' style='text-align:center'><h3>🛠️ دعم</h3><h2 dir=ltr>{SUPPORT}</h2><div class=row2><button onclick=\"window.open('https://wa.me/{SUPPORT}','_blank')\">💬 واتساب</button><button onclick=\"location.href='tel:{SUPPORT}'\">📞 اتصال</button></div></div>")
    cc(c);return redirect('/dash?view=home')

@app.route('/search')
def search():
    if not session.get('phone'):return redirect('/login')
    q=request.args.get('q','');c=db()
    r1=ex(c,"SELECT name,phone FROM subs WHERE name LIKE? OR phone LIKE?",(f"%{q}%",f"%{q}%")).fetchall() if q else []
    r2=ex(c,"SELECT location,ip FROM dish_ips WHERE location LIKE? OR ip LIKE?",(f"%{q}%",f"%{q}%")).fetchall() if q else []
    cc(c)
    t="".join([f"<tr><td>👤 {r['name']}</td><td>{r['phone']}</td></tr>" for r in r1])
    t+="".join([f"<tr><td>📡 {r['location']}</td><td dir=ltr>{r['ip']}</td></tr>" for r in r2])
    return render(f"<div class='card'><form><input name=q value='{q}' placeholder='بحث...'><button>🔍</button></form></div><div class='card'><table>{t}</table></div>")

@app.route('/add_sub',methods=['POST'])
def a1():c=db();ex(c,"INSERT INTO subs(name,phone,status) VALUES(?,?,?)",(request.form['name'],request.form['phone'],'نشط'));c.commit();cc(c);return redirect('/dash?view=subs')
@app.route('/del_sub/<int:i>')
def d1(i):c=db();ex(c,"DELETE FROM subs WHERE id=?",(i,));c.commit();cc(c);return redirect('/dash?view=subs')
@app.route('/add_dish',methods=['POST'])
def a2():c=db();ex(c,"INSERT INTO dish_ips(ip,location,site,area,tower,lat,lng) VALUES(?,?,?,?,?,?,?)",(request.form['ip'],request.form['location'],request.form.get('tower',''),request.form.get('area',''),request.form.get('tower',''),float(request.form.get('lat') or 0),float(request.form.get('lng') or 0)));c.commit();cc(c);return redirect('/dash?view=dishes')
@app.route('/del_dish/<int:i>')
def d2(i):c=db();ex(c,"DELETE FROM dish_ips WHERE id=?",(i,));c.commit();cc(c);return redirect('/dash?view=dishes')
@app.route('/add_tower',methods=['POST'])
def at():c=db();ex(c,"INSERT INTO towers(name,lat,lng,note) VALUES(?,?,?,?)",(request.form['name'],float(request.form['lat']),float(request.form['lng']),''));c.commit();cc(c);return redirect('/dash?view=towers')
@app.route('/del_tower/<int:i>')
def dt(i):c=db();ex(c,"DELETE FROM towers WHERE id=?",(i,));c.commit();cc(c);return redirect('/dash?view=towers')
@app.route('/add_srv',methods=['POST'])
def a3():c=db();ex(c,"INSERT INTO servers(name,host,username,password) VALUES(?,?,?,?)",(request.form['name'],request.form['host'],'u','p'));c.commit();cc(c);return redirect('/dash?view=servers')
@app.route('/add_user',methods=['POST'])
def a4():
    c=db()
    try:ex(c,"INSERT INTO users(phone,username,password,role,active) VALUES(?,?,?,?,1)",(request.form['phone'].strip(),request.form['username'].strip(),request.form['password'],request.form.get('role','tech')));c.commit()
    except:pass
    cc(c);return redirect('/dash?view=settings')
@app.route('/edit_user/<ph>',methods=['POST'])
def eu(ph):c=db();ex(c,"UPDATE users SET username=?,password=?,role=? WHERE phone=?",(request.form['username'],request.form['password'],request.form['role'],ph));c.commit();cc(c);return redirect('/dash?view=settings')
@app.route('/del_user/<ph>')
def du(ph):
    if ph=='05344851045':return redirect('/dash?view=settings')
    c=db();ex(c,"DELETE FROM users WHERE phone=?",(ph,));c.commit();cc(c);return redirect('/dash?view=settings')
@app.route('/toggle_user/<ph>')
def tu(ph):c=db();u=ex(c,"SELECT active FROM users WHERE phone=?",(ph,)).fetchone();na=0 if dict(u)['active']==1 else 1;ex(c,"UPDATE users SET active=? WHERE phone=?",(na,ph));c.commit();cc(c);return redirect('/dash?view=settings')
@app.route('/charge',methods=['POST'])
def ch():
    sid=request.form['sub_id'];amt=float(request.form['amount']);cur=request.form['currency'];typ=request.form.get('ttype','قبض');note=request.form.get('note','')
    usd=amt if cur=='usd' else 0;syr=amt if cur=='syr' else 0;c=db()
    ex(c,"INSERT INTO ledger(sub_id,date,usd,syr,type,note,by_user) VALUES(?,?,?,?,?,?,?)",(sid,datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),usd,syr,typ,note,session.get('phone')))
    if typ in ('قبض','شحن رصيد'):ex(c,"UPDATE subs SET balance_usd=balance_usd+?,balance_syr=balance_syr+? WHERE id=?",(usd,syr,sid))
    else:ex(c,"UPDATE subs SET balance_usd=balance_usd-?,balance_syr=balance_syr-? WHERE id=?",(usd,syr,sid))
    c.commit();cc(c);return redirect('/dash?view=ledger')
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
