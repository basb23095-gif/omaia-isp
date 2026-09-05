from flask import Flask, request, redirect, render_template_string, session, Response
import os, datetime, io, csv, time, socket
try:
    import psycopg2, psycopg2.extras
except:
    psycopg2 = None
import sqlite3

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "omia-sec-2026")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
USE_PG = bool(DATABASE_URL and psycopg2)
_pg = None
_pt = 0
SUPPORT = "0095344851045"

def db():
    global _pg, _pt
    if USE_PG:
        if _pg and time.time() - _pt < 300:
            try:
                _pg.cursor().execute("SELECT 1")
                return _pg
            except:
                pass
        _pg = psycopg2.connect(DATABASE_URL, sslmode='require', connect_timeout=5)
        _pg.autocommit = True
        _pt = time.time()
        return _pg
    c = sqlite3.connect("omia.db")
    c.row_factory = sqlite3.Row
    return c

def cc(c):
    if not USE_PG:
        try:
            c.close()
        except:
            pass

def ex(c, q, a=()):
    if USE_PG:
        cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(q.replace("?", "%s"), a)
        return cur
    return c.execute(q, a)

def init():
    c = db()
    ss = [
        "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,username TEXT,password TEXT,role TEXT,active INT DEFAULT 1)",
        "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,status TEXT,balance_usd REAL DEFAULT 0,balance_syr REAL DEFAULT 0)",
        "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,site TEXT,area TEXT,tower TEXT,lat REAL DEFAULT 0,lng REAL DEFAULT 0)",
        "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,sub_id INT,date TEXT,usd REAL,syr REAL,type TEXT,note TEXT,by_user TEXT)",
        "CREATE TABLE IF NOT EXISTS servers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,host TEXT,username TEXT,password TEXT)",
        "CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,msg TEXT,date TEXT,seen INT DEFAULT 0)",
        "CREATE TABLE IF NOT EXISTS login_logs(id INTEGER PRIMARY KEY AUTOINCREMENT,phone TEXT,date TEXT,ip TEXT)"
    ]
    if USE_PG:
        ss = [s.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY") for s in ss]
        cur = c.cursor()
        for s in ss:
            cur.execute(s)
        cur.execute("SELECT * FROM users WHERE phone='05344851045'")
        if not cur.fetchone():
            cur.execute("INSERT INTO users(phone,username,password,role,active) VALUES('05344851045','admin','admin2024','super',1)")
        c.commit()
        cur.close()
    else:
        for s in ss:
            c.execute(s)
        if not c.execute("SELECT * FROM users WHERE phone='05344851045'").fetchone():
            c.execute("INSERT INTO users(phone,username,password,role,active) VALUES('05344851045','admin','admin2024','super',1)")
        c.commit()
        cc(c)

init()

def ping(ip):
    try:
        socket.create_connection((ip.strip(), 80), timeout=1).close()
        return True
    except:
        try:
            socket.create_connection((ip.strip(), 22), timeout=1).close()
            return True
        except:
            return False

def notify(m):
    try:
        c = db()
        if not ex(c, "SELECT id FROM notifications WHERE msg=?", (m,)).fetchone():
            ex(c, "INSERT INTO notifications(msg,date,seen) VALUES(?,?,0)", (m, datetime.datetime.now().strftime("%Y-%m-%d %H:%M")))
            c.commit()
        cc(c)
    except:
        pass

LAYOUT = """<!DOCTYPE html><html lang="ARLANG" dir="ARDIR"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OMIA ISP</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;font-family:Tahoma;transition:.4s;animation:fd .4s ease}
@keyframes fd{from{opacity:0}to{opacity:1}}
@keyframes up{from{opacity:0;transform:translateY(18px)}to{opacity:1;transform:none}}
body.dark{background:#0b111e;color:#e2e8f0}
body.light{background:#f1f5f9;color:#0f172a}
.top{position:fixed;top:0;right:0;left:0;height:60px;display:flex;align-items:center;justify-content:space-between;padding:0 12px;z-index:1002;backdrop-filter:blur(12px)}
body.dark .top,body.dark .sb,body.dark .card{background:rgba(30,41,59,.97)}
body.light .top,body.light .sb,body.light .card{background:#fff;box-shadow:0 4px 20px #0001}
#mb{width:110px;height:42px;border-radius:20px;border:none;background:linear-gradient(135deg,#00D4FF,#0090c0);font-weight:900;cursor:grab;touch-action:none;position:absolute;color:#fff}
.sb{position:fixed;top:70px;width:260px;border-radius:18px;padding:12px;z-index:1003;transition:transform .45s cubic-bezier(.22,1,.36,1),opacity .3s;box-shadow:0 15px 40px #0006;max-height:82vh;overflow:auto}
.sb.hide{transform:translateX(120%);opacity:0;pointer-events:none}
.sb a{display:block;padding:12px;margin:6px 0;background:#8881;text-decoration:none;border-radius:12px;color:inherit;transition:.25s}
.sb a:hover{background:#00D4FF;color:#fff;transform:translateX(-5px)}
.sb a.active{border:1px solid #00D4FF;color:#00D4FF}
.mn{padding:80px 14px 20px;max-width:1100px;margin:auto}
.card{padding:14px;border-radius:18px;margin:12px 0;animation:up .45s ease;border:1px solid #00d4ff22}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{padding:10px;border-bottom:1px solid #334155;text-align:center}
th{color:#00D4FF}
input,select{width:100%;padding:11px;margin:5px 0;border-radius:12px;border:1px solid #334155;background:transparent;color:inherit}
button{padding:12px;width:100%;border:none;border-radius:12px;font-weight:900;background:linear-gradient(135deg,#00D4FF,#0090c0);color:#fff;cursor:pointer}
.row2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
#map{height:380px;border-radius:18px}
.wa{position:fixed;bottom:20px;left:20px;z-index:9999;width:62px;height:62px;border-radius:50%;background:#25D366;display:flex;align-items:center;justify-content:center;font-size:32px;text-decoration:none;animation:pl 2s infinite}
@keyframes pl{0%{box-shadow:0 0 0 0 #25d36677}70%{box-shadow:0 0 0 18px #25d36600}100%{box-shadow:0 0 0 0 #25d36600}}
.bdg{background:red;color:#fff;border-radius:10px;padding:2px 6px;font-size:11px}
@media print{.top,.sb,.wa{display:none}}
</style></head><body class="THEME">
<div class="top"><button id="mb">☰ Menu</button><b style="color:#00D4FF;margin:auto">OMIA ISP</b><div><a href="/dash?view=notifs" style="text-decoration:none">🔔<span class="bdg">NNN</span></a> <a href="/search" style="text-decoration:none">🔍</a> <a href="/lang" style="text-decoration:none">🌐</a> <a href="/theme" style="text-decoration:none">🌓</a></div></div>
<div class="sb hide" id="sb">
<a href="/dash?view=home" data-v="home">🏠 الرئيسية</a>
<a href="/dash?view=subs" data-v="subs">👥 المشتركين</a>
<a href="/dash?view=dishes_tower" data-v="dishes_tower">🗼 صحون / أبراج</a>
<a href="/dash?view=dishes_area" data-v="dishes_area">📍 صحون / مناطق</a>
LEDGERLINK
<a href="/dash?view=map" data-v="map">🗺️ خريطة</a>
<a href="/dash?view=report" data-v="report">📊 تقرير</a>
<a href="/dash?view=servers" data-v="servers">🖥️ سيرفرات</a>
<a href="/dash?view=notifs" data-v="notifs">🔔 إشعارات</a>
<a href="/dash?view=logs" data-v="logs">📝 سجل الدخول</a>
<a href="/dash?view=settings" data-v="settings">⚙️ الإعدادات</a>
<a href="/dash?view=support" data-v="support">🛠️ دعم</a>
<a href="/logout">🚪 خروج</a></div>
<div class="mn">CONTENT</div>
<a class="wa" href="https://wa.me/0095344851045" target="_blank">💬</a>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
let sb=document.getElementById('sb'),b=document.getElementById('mb');
b.onclick=e=>{e.stopPropagation();sb.classList.toggle('hide')};
let dx=0,dy=0,dg=false,sx,sy;
b.addEventListener('pointerdown',e=>{dg=true;sx=e.clientX-dx;sy=e.clientY-dy;b.setPointerCapture(e.pointerId)});
b.addEventListener('pointermove',e=>{if(!dg)return;dx=e.clientX-sx;dy=e.clientY-sy;b.style.transform='translate('+dx+'px,'+dy+'px)'});
b.addEventListener('pointerup',()=>dg=false);
document.addEventListener('click',e=>{if(!sb.classList.contains('hide')&&!sb.contains(e.target)&&e.target!==b)sb.classList.add('hide')});
let v=new URLSearchParams(location.search).get('view')||'home';
document.querySelectorAll('[data-v]').forEach(a=>{if(a.dataset.v===v)a.classList.add('active')});
</script></body></html>"""

def render(c):
    lang = session.get('lang', 'ar')
    theme = session.get('theme', 'dark')
    role = session.get('role', 'tech')
    con = db()
    try:
        nn = len(ex(con, "SELECT id FROM notifications WHERE seen=0").fetchall())
    except:
        nn = 0
    cc(con)
    h = LAYOUT.replace("ARLANG", lang).replace("ARDIR", 'rtl' if lang == 'ar' else 'ltr').replace("THEME", theme).replace("CONTENT", c)
    h = h.replace("NNN", str(nn) if nn else "")
    h = h.replace("LEDGERLINK", '<a href="/dash?view=ledger" data-v="ledger">📒 الحسابات</a>' if role in ('super', 'admin') else '')
    return render_template_string(h)

@app.route('/lang')
def lg():
    session['lang'] = 'en' if session.get('lang', 'ar') == 'ar' else 'ar'
    return redirect(request.referrer or '/dash')

@app.route('/theme')
def th():
    session['theme'] = 'light' if session.get('theme', 'dark') == 'dark' else 'dark'
    return redirect(request.referrer or '/dash')

@app.route('/')
def ix():
    return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login', methods=['GET', 'POST'])
def login():
    m = ""
    if request.method == 'POST':
        i = request.form.get('phone', '').strip()
        p = request.form.get('password', '')
        c = db()
        u = ex(c, "SELECT * FROM users WHERE phone=? OR username=?", (i, i)).fetchone()
        if u and dict(u)['password'] == p:
            d = dict(u)
            session['phone'] = d['phone']
            session['role'] = d['role']
            ex(c, "INSERT INTO login_logs(phone,date,ip) VALUES(?,?,?)", (d['phone'], datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), request.remote_addr))
            c.commit()
            cc(c)
            return redirect('/dash?view=home')
        cc(c)
        m = "<p style='color:red'>خطأ بالدخول</p>"
    return render("<div class='card' style='max-width:380px;margin:40px auto;text-align:center'><h2 style='color:#00D4FF'>OMIA ISP</h2>" + m + "<form method=post><input name=phone placeholder='مستخدم / هاتف' required><input name=password type=password placeholder='كلمة السر' required><button>دخول</button></form><p>دعم: <a href='https://wa.me/0095344851045' target=_blank>0095344851045</a></p></div>")

@app.route('/logout')
def lo():
    session.clear()
    return redirect('/login')

@app.route('/dash')
def dash():
    if not session.get('phone'):
        return redirect('/login')
    v = request.args.get('view', 'home')
    c = db()
    role = session.get('role', 'tech')
    def done(h):
        r = render(h)
        cc(c)
        return r
    if v == 'home':
        ns = len(ex(c, "SELECT id FROM subs").fetchall())
        nd = len(ex(c, "SELECT id FROM dish_ips").fetchall())
        nu = len(ex(c, "SELECT phone FROM users").fetchall())
        nl = len(ex(c, "SELECT id FROM ledger").fetchall())
        return done("<div class='row2'><div class='card'><h2>" + str(ns) + "</h2>👥 مشتركين</div><div class='card'><h2>" + str(nd) + "</h2>📡 صحون</div></div><div class='row2'><div class='card'><h2>" + str(nu) + "</h2>👤 يوزرات</div><div class='card'><h2>" + str(nl) + "</h2>📒 قيود</div></div>")
    if v == 'notifs':
        rs = ex(c, "SELECT * FROM notifications ORDER BY id DESC LIMIT 100").fetchall()
        ex(c, "UPDATE notifications SET seen=1")
        c.commit()
        t = "".join(["<div class='card'>🔔 " + r['msg'] + "<br><small>" + r['date'] + "</small></div>" for r in rs])
        return done("<h3>🔔 إشعارات</h3>" + (t or "<div class=card>لا يوجد</div>"))
    if v == 'subs':
        rs = ex(c, "SELECT * FROM subs ORDER BY id DESC").fetchall()
        tr = "".join(["<tr><td>" + r['name'] + "</td><td dir=ltr>" + r['phone'] + "</td><td>" + str(r['balance_usd']) + "$</td><td><a href='https://wa.me/" + r['phone'] + "' target=_blank>💬</a></td><td><a href='/del_sub/" + str(r['id']) + "' style='color:red'>✖</a></td></tr>" for r in rs])
        return done("<div class='card'><form method=post action=/add_sub><div class=row2><input name=name placeholder='الاسم' required><input name=phone placeholder='هاتف' required></div><button>إضافة مشترك</button></form></div><div class='card'><button onclick=\"location.href='/export_subs'\">📥 Excel</button></div><table><tr><th>اسم</th><th>هاتف</th><th>رصيد</th><th>واتساب</th><th></th></tr>" + tr + "</table>")
    if v in ('dishes_tower', 'dishes_area'):
        rs = ex(c, "SELECT * FROM dish_ips ORDER BY id DESC").fetchall()
        tr = ""
        for r in rs:
            d = dict(r)
            ok = ping(d['ip'] or 'x')
            dot = "🟢" if ok else "🔴"
            if not ok:
                notify("🔴 صحن فاصل: " + str(d.get('location')) + " " + d['ip'])
            tr += "<tr><td>" + dot + "</td><td dir=ltr><a href='http://" + d['ip'] + "' target=_blank style='color:#00D4FF'>" + d['ip'] + "</a></td><td>" + str(d.get('location','')) + "</td><td>" + str(d.get('area','')) + "</td><td>" + str(d.get('tower','')) + "</td><td><a href='/del_dish/" + str(d['id']) + "' style='color:red'>✖</a></td></tr>"
        title = "🗼 حسب البرج" if "tower" in v else "📍 حسب المنطقة"
        return done("<h3>" + title + " + Ping</h3><div class='card'><form method=post action=/add_dish><div class=row2><input name=ip placeholder='IP' dir=ltr required><input name=location placeholder='اسم الصحن' required></div><div class=row2><input name=area placeholder='المنطقة' required><input name=tower placeholder='البرج' required></div><div class=row2><input name=lat type=number step=any placeholder='lat'><input name=lng type=number step=any placeholder='lng'></div><button>إضافة صحن</button></form></div><table><tr><th>Ping</th><th>IP</th><th>اسم</th><th>منطقة</th><th>برج</th><th></th></tr>" + tr + "</table>")
    if v == 'ledger':
        if role not in ('super', 'admin'):
            return redirect('/dash?view=home')
        rs = ex(c, "SELECT l.*, s.name sn FROM ledger l LEFT JOIN subs s ON s.id=l.sub_id ORDER BY l.id DESC LIMIT 300").fetchall()
        subs = ex(c, "SELECT id,name FROM subs").fetchall()
        opts = "".join(["<option value='" + str(s['id']) + "'>" + s['name'] + "</option>" for s in subs])
        tr = "".join(["<tr><td>" + r['date'] + "</td><td>" + str(r['sn']) + "</td><td>" + str(r['type'] or '') + "</td><td>" + str(r['usd']) + "</td><td>" + str(r['syr']) + "</td><td>" + str(r['note'] or '') + "</td></tr>" for r in rs])
        return done("<div class='card'><h3>📒 دفتر احترافي</h3><form method=post action=/charge><select name=sub_id>" + opts + "</select><div class=row2><input name=amount type=number step=0.01 required placeholder='مبلغ'><select name=currency><option value=usd>$ دولار</option><option value=syr>ل.س</option></select></div><div class=row2><select name=ttype><option>قبض</option><option>صرف</option><option>دين</option><option>شحن رصيد</option></select><input name=note placeholder='بيان'></div><button>تسجيل قيد</button></form></div><div class='card'><div class=row2><button onclick=\"location.href='/export_ledger'\">📥 Excel</button><button onclick=\"window.print()\">🖨️ PDF</button></div></div><table><tr><th>تاريخ</th><th>مشترك</th><th>نوع</th><th>$</th><th>ل.س</th><th>بيان</th></tr>" + tr + "</table>")
    if v == 'report':
        today = datetime.date.today().isoformat()
        month = today[:7]
        r1 = ex(c, "SELECT SUM(usd) s1, SUM(syr) s2 FROM ledger WHERE date LIKE ?", (today + "%",)).fetchone()
        r2 = ex(c, "SELECT SUM(usd) s1, SUM(syr) s2 FROM ledger WHERE date LIKE ?", (month + "%",)).fetchone()
        a = dict(r1) if r1 else {}
        b = dict(r2) if r2 else {}
        return done("<div class='card'><h3>📊 تقرير</h3><p>اليوم " + today + ": " + str(a.get('s1') or 0) + "$ | " + str(a.get('s2') or 0) + "</p><p>الشهر " + month + ": " + str(b.get('s1') or 0) + "$ | " + str(b.get('s2') or 0) + "</p><div class=row2><button onclick=\"location.href='/export_ledger'\">📥 Excel</button><button onclick=\"window.print()\">🖨️ PDF</button></div></div>")
    if v == 'map':
        rs = ex(c, "SELECT location,lat,lng,ip FROM dish_ips WHERE lat!=0").fetchall()
        pts = ",".join(["{n:'" + r['location'] + " " + r['ip'] + "',la:" + str(r['lat']) + ",ln:" + str(r['lng']) + "}" for r in rs])
        return done("<h3>🗺️ خريطة</h3><div class='card'><div id=map></div></div><script>var m=L.map('map').setView([34.72,36.72],10);L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(m);var pts=[" + pts + "];pts.forEach(p=>L.marker([p.la,p.ln]).addTo(m).bindPopup(p.n));if(pts.length)m.fitBounds(pts.map(p=>[p.la,p.ln]))</script>")
    if v == 'servers':
        rs = ex(c, "SELECT * FROM servers").fetchall()
        tr = "".join(["<tr><td>" + r['name'] + "</td><td dir=ltr>" + r['host'] + "</td></tr>" for r in rs])
        return done("<div class='card'><form method=post action=/add_srv><div class=row2><input name=name placeholder='اسم' required><input name=host placeholder='host' dir=ltr required></div><button>إضافة</button></form></div><table>" + tr + "</table>")
    if v == 'logs':
        rs = ex(c, "SELECT * FROM login_logs ORDER BY id DESC LIMIT 150").fetchall()
        tr = "".join(["<tr><td>" + r['phone'] + "</td><td>" + r['date'] + "</td><td dir=ltr>" + r['ip'] + "</td></tr>" for r in rs])
        return done("<h3>📝 سجل الدخول</h3><table><tr><th>مستخدم</th><th>وقت</th><th>IP</th></tr>" + tr + "</table>")
    if v == 'settings':
        us = ex(c, "SELECT * FROM users").fetchall()
        tr = "".join(["<tr><td>" + u['username'] + "/" + u['phone'] + "</td><td>" + u['role'] + "</td><td>" + u['password'] + "</td></tr>" for u in us])
        return done("<div class='card'><h3>⚙️ إضافة بسطر واحد</h3><form method=post action=/add_user><input name=up placeholder='مثال: 0991234567 / ahmad' required><input name=password placeholder='باسورد' required><button>إضافة</button></form></div><table><tr><th>يوزر</th><th>دور</th><th>باس</th></tr>" + tr + "</table>")
    if v == 'support':
        return done("<div class='card' style='text-align:center'><h3>🛠️ دعم فني</h3><h2 dir=ltr>0095344851045</h2><div class=row2><button onclick=\"window.open('https://wa.me/0095344851045','_blank')\">💬 واتساب</button><button onclick=\"location.href='tel:0095344851045'\">📞 اتصال</button></div></div>")
    cc(c)
    return redirect('/dash?view=home')

@app.route('/search')
def search():
    if not session.get('phone'):
        return redirect('/login')
    q = request.args.get('q', '')
    c = db()
    r1 = ex(c, "SELECT name,phone FROM subs WHERE name LIKE ? OR phone LIKE ?", ("%" + q + "%", "%" + q + "%")).fetchall() if q else []
    r2 = ex(c, "SELECT location,ip FROM dish_ips WHERE location LIKE ? OR ip LIKE ?", ("%" + q + "%", "%" + q + "%")).fetchall() if q else []
    cc(c)
    t = "".join(["<tr><td>👤 " + r['name'] + "</td><td>" + r['phone'] + "</td></tr>" for r in r1])
    t += "".join(["<tr><td>📡 " + r['location'] + "</td><td dir=ltr>" + r['ip'] + "</td></tr>" for r in r2])
    return render("<div class='card'><form><input name=q value='" + q + "' placeholder='بحث شامل...'><button>🔍 بحث</button></form></div><table>" + t + "</table>")

@app.route('/add_sub', methods=['POST'])
def a1():
    c = db()
    ex(c, "INSERT INTO subs(name,phone,status) VALUES(?,?,?)", (request.form['name'], request.form['phone'], 'نشط'))
    c.commit(); cc(c)
    return redirect('/dash?view=subs')

@app.route('/del_sub/<int:i>')
def d1(i):
    c = db(); ex(c, "DELETE FROM subs WHERE id=?", (i,)); c.commit(); cc(c)
    return redirect('/dash?view=subs')

@app.route('/add_dish', methods=['POST'])
def a2():
    c = db()
    ex(c, "INSERT INTO dish_ips(ip,location,site,area,tower,lat,lng) VALUES(?,?,?,?,?,?,?)", (request.form['ip'], request.form['location'], request.form.get('tower',''), request.form.get('area',''), request.form.get('tower',''), float(request.form.get('lat') or 0), float(request.form.get('lng') or 0)))
    c.commit(); cc(c)
    return redirect(request.referrer or '/dash')

@app.route('/del_dish/<int:i>')
def d2(i):
    c = db(); ex(c, "DELETE FROM dish_ips WHERE id=?", (i,)); c.commit(); cc(c)
    return redirect(request.referrer or '/dash')

@app.route('/add_srv', methods=['POST'])
def a3():
    c = db()
    ex(c, "INSERT INTO servers(name,host,username,password) VALUES(?,?,?,?)", (request.form['name'], request.form['host'], 'u', 'p'))
    c.commit(); cc(c)
    return redirect('/dash?view=servers')

@app.route('/add_user', methods=['POST'])
def a4():
    up = request.form.get('up', '')
    ph, un = (up.split('/', 1) if '/' in up else (up, up))
    c = db()
    try:
        ex(c, "INSERT INTO users(phone,username,password,role,active) VALUES(?,?,?,?,1)", (ph.strip(), un.strip(), request.form['password'], 'tech'))
        c.commit()
    except:
        pass
    cc(c)
    return redirect('/dash?view=settings')

@app.route('/charge', methods=['POST'])
def ch():
    sid = request.form['sub_id']
    amt = float(request.form['amount'])
    cur = request.form['currency']
    typ = request.form.get('ttype', 'قبض')
    note = request.form.get('note', '')
    usd = amt if cur == 'usd' else 0
    syr = amt if cur == 'syr' else 0
    c = db()
    ex(c, "INSERT INTO ledger(sub_id,date,usd,syr,type,note,by_user) VALUES(?,?,?,?,?,?,?)", (sid, datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), usd, syr, typ, note, session.get('phone')))
    if typ in ('قبض', 'شحن رصيد'):
        ex(c, "UPDATE subs SET balance_usd=balance_usd+?, balance_syr=balance_syr+? WHERE id=?", (usd, syr, sid))
    else:
        ex(c, "UPDATE subs SET balance_usd=balance_usd-?, balance_syr=balance_syr-? WHERE id=?", (usd, syr, sid))
    c.commit(); cc(c)
    return redirect('/dash?view=ledger')

@app.route('/export_subs')
def es():
    c = db()
    rs = ex(c, "SELECT name,phone,balance_usd,balance_syr FROM subs").fetchall()
    cc(c)
    o = io.StringIO()
    w = csv.writer(o)
    w.writerow(['name', 'phone', 'usd', 'syr'])
    for r in rs:
        w.writerow([r['name'], r['phone'], r['balance_usd'], r['balance_syr']])
    return Response(o.getvalue().encode('utf-8-sig'), mimetype='text/csv', headers={'Content-Disposition': 'attachment;filename=subs.csv'})

@app.route('/export_ledger')
def el():
    c = db()
    rs = ex(c, "SELECT date,usd,syr,type,note FROM ledger").fetchall()
    cc(c)
    o = io.StringIO()
    w = csv.writer(o)
    w.writerow(['date', 'usd', 'syr', 'type', 'note'])
    for r in rs:
        w.writerow([r['date'], r['usd'], r['syr'], r['type'], r['note']])
    return Response(o.getvalue().encode('utf-8-sig'), mimetype='text/csv', headers={'Content-Disposition': 'attachment;filename=ledger.csv'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
