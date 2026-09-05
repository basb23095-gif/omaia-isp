from flask import Flask, request, redirect, render_template_string, session, send_from_directory
import os, sqlite3, time

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "omaia-sec")
DBURL = os.environ.get("DATABASE_URL", "")
USE_PG = bool(DBURL and psycopg2)

WA_DISPLAY = "0095344851045"
WA_LINK = "963544851045"
_pg = None
_pt = 0

def db():
    global _pg, _pt
    if USE_PG:
        if _pg and time.time() - _pt < 280:
            try: _pg.cursor().execute("SELECT 1"); return _pg
            except: pass
        import psycopg2 as p
        _pg = p.connect(DBURL, sslmode='require')
        _pg.autocommit = True
        _pt = time.time()
        return _pg
    c = sqlite3.connect("omaia.db", check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def ex(c, q, a=()):
    if USE_PG:
        cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(q.replace("?", "%s"), a); return cur
    return c.execute(q, a)

def init():
    c = db()
    if USE_PG:
        qs = [
            "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,username TEXT,password TEXT,role TEXT,active INT)",
            "CREATE TABLE IF NOT EXISTS subs(id SERIAL PRIMARY KEY,name TEXT,phone TEXT,status TEXT)",
            "CREATE TABLE IF NOT EXISTS dish_ips(id SERIAL PRIMARY KEY,ip TEXT,name TEXT,network TEXT,tower TEXT)",
            "CREATE TABLE IF NOT EXISTS servers(id SERIAL PRIMARY KEY,name TEXT,ip TEXT,location TEXT)",
            "CREATE TABLE IF NOT EXISTS ledger(id SERIAL PRIMARY KEY,date TEXT,sub TEXT,amount REAL,currency TEXT,note TEXT)"
        ]
        cur = c.cursor()
        for q in qs: cur.execute(q)
        cur.execute("SELECT 1 FROM users WHERE phone='05344851045'")
        if not cur.fetchone(): cur.execute("INSERT INTO users VALUES('05344851045','05344851045','admin2024','super',1)")
        cur.close(); return
    else:
        qs = [
            "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,username TEXT,password TEXT,role TEXT,active INT)",
            "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,status TEXT)",
            "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,name TEXT,network TEXT,tower TEXT)",
            "CREATE TABLE IF NOT EXISTS servers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,ip TEXT,location TEXT)",
            "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,date TEXT,sub TEXT,amount REAL,currency TEXT,note TEXT)"
        ]
        for q in qs: c.execute(q)
        c.commit(); c.close()

init()

CSS = """*{transition:.25s}body{font-family:Arial;margin:0;background:__BG__;color:__TEXT__}body.lb{background:linear-gradient(rgba(4,30,54,.55),rgba(4,30,54,.78)),url('/bg.jpg') center/cover fixed,__BG__;min-height:100vh;display:flex;align-items:center;justify-content:center}.t{position:fixed;top:0;left:0;right:0;height:56px;background:__SIDEBAR__;display:flex;align-items:center;justify-content:space-between;padding:0 12px;z-index:20;border-bottom:2px solid #00D4FF}.m{padding:66px 10px;max-width:1050px;margin:auto}.c{background:rgba(255,255,255,.08);backdrop-filter:blur(14px);border:1px solid rgba(0,212,255,.35);border-radius:16px;padding:16px;margin:12px 0}.pt{text-align:right;font-weight:bold;font-size:19px;color:#00D4FF}button{background:linear-gradient(135deg,#00D4FF,#0090c8);border:0;padding:12px;width:100%;border-radius:12px;font-weight:bold;cursor:pointer;color:#021}input,select{width:100%;padding:11px;margin:6px 0;border-radius:12px;border:1px solid #334155;background:#0f172a;color:#fff;box-sizing:border-box}table{width:100%;border-collapse:collapse}td,th{padding:9px;border-bottom:1px solid #234;text-align:center}th{color:#00D4FF}.drawer{position:fixed;top:0;right:-285px;width:265px;height:100%;background:__SIDEBAR__;z-index:30;transition:.3s;padding:62px 12px}.drawer.open{right:0}.overlay{position:fixed;inset:0;background:rgba(0,0,0,.55);display:none;z-index:25}.overlay.show{display:block}.drawer a{display:flex;gap:10px;color:#fff;text-decoration:none;padding:12px;border-radius:10px}.menuBtn{cursor:pointer;font-size:24px;color:#fff;background:#00D4FF;width:42px;height:42px;display:flex;align-items:center;justify-content:center;border-radius:10px}body.light{background:#eef6ff!important;color:#102a43!important}body.light.c{background:rgba(255,255,255,.9);color:#102a43}body.light input,body.light select{background:#fff;color:#102a43}.foot{text-align:center;color:#00D4FF;margin:18px}.wa{position:fixed;bottom:16px;left:16px;background:#25D366;width:52px;height:52px;border-radius:50%;display:flex;align-items:center;justify-content:center;text-decoration:none}"""

LAY = """<!DOCTYPE html><html dir=rtl><head><meta charset=UTF-8><meta name=viewport content='width=device-width,initial-scale=1'><title>OMAIA</title><style>""" + CSS + """</style></head><body>
<div class=t><div style=display:flex;gap:10px;align-items:center><div class=menuBtn onclick="document.getElementById('dr').classList.add('open');document.getElementById('ov').classList.add('show')">☰</div><b style=color:#00D4FF>✨ OMAIA ISP</b></div><div style=display:flex;gap:10px;align-items:center><div onclick="document.body.classList.toggle('light');" style=cursor:pointer;font-size:22px>🌙</div></div></div>
<div id=ov class=overlay onclick="document.getElementById('dr').classList.remove('open');this.classList.remove('show')"></div>
<div id=dr class=drawer><a href=/>🏠 الرئيسية</a><a href=/?view=subs>👥 المشتركين</a><a href=/?view=dishes>📡 الصحون</a><a href=/?view=servers>🖥️ السيرفرات</a><a href=/?view=ledger>📒 الحسابات</a><a href=/logout>🚪 خروج</a></div>
<div class=m>{{c|safe}}<div class=foot>💎 OMAIA ISP <br><a href='https://wa.me""" + WA_LINK + """' style=color:#00D4FF;text-decoration:none>📞 """ + WA_DISPLAY + """</a></div></div>
<a class=wa href='https://wa.me""" + WA_LINK + """' target=_blank>💬</a>
<script>function fS(v){document.querySelectorAll('table tr').forEach((r,i)=>{if(i==0)return;r.style.display=r.innerText.includes(v)?'':'none'})}</script>
</body></html>"""

def R(h, bc=""):
    s = LAY; co = {"BG": "#0f172a", "TEXT": "#ffffff", "SIDEBAR": "#1e293b"}
    for k, v in co.items(): s = s.replace("__" + k + "__", v)
    return render_template_string(s.replace("__BC__", bc), c=h)

def render_view_page(view, c):
    if view == 'subs':
        if request.method == 'POST':
            ex(c, "INSERT INTO subs(name,phone,status) VALUES(?,?,?)", (request.form.get('name'), request.form.get('phone'), request.form.get('status')))
        rows = ex(c, "SELECT * FROM subs").fetchall()
        h = "<div class=pt>👥 المشتركين</div><div class=c><form method=post><input name=name placeholder='الاسم' required><input name=phone placeholder='الهاتف'><select name=status><option>نشط</option><option>منتهي</option></select><button>➕ إضافة</button></form></div><div class=c><input placeholder='🔍 بحث...' oninput='fS(this.value)'><table><tr><th>الاسم</th><th>الهاتف</th><th>الحالة</th></tr>"
        for r in rows:
            rd = dict(r)
            h += f"<tr><td>{rd.get('name','')}</td><td>{rd.get('phone','')}</td><td>{rd.get('status','')}</td></tr>"
        return R(h + "</table></div>")

    if view == 'dishes':
        if request.method == 'POST':
            ex(c, "INSERT INTO dish_ips(ip,name,network,tower) VALUES(?,?,?,?)", (request.form.get('ip'), request.form.get('name'), request.form.get('network'), request.form.get('tower')))
        rows = ex(c, "SELECT * FROM dish_ips").fetchall()
        h = "<div class=pt>📡 الصحون و IPs</div><div class=c><form method=post><input name=ip placeholder='IP Address' required><input name=name placeholder='الاسم'><input name=network placeholder='الشبكة'><input name=tower placeholder='البرج'><button>➕ إضافة</button></form></div><div class=c><table><tr><th>IP</th><th>الاسم</th><th>الشبكة</th></tr>"
        for r in rows:
            rd = dict(r)
            h += f"<tr><td>{rd.get('ip','')}</td><td>{rd.get('name','')}</td><td>{rd.get('network','')}</td></tr>"
        return R(h + "</table></div>")

    if view == 'servers':
        if request.method == 'POST':
            ex(c, "INSERT INTO servers(name,ip,location) VALUES(?,?,?)", (request.form.get('name'), request.form.get('ip'), request.form.get('location')))
        rows = ex(c, "SELECT * FROM servers").fetchall()
        h = "<div class=pt>🖥️ السيرفرات</div><div class=c><form method=post><input name=name placeholder='الاسم' required><input name=ip placeholder='IP'><button>➕ إضافة</button></form></div><div class=c><table><tr><th>السيرفر</th><th>IP</th></tr>"
        for r in rows:
            rd = dict(r)
            h += f"<tr><td>{rd.get('name','')}</td><td>{rd.get('ip','')}</td></tr>"
        return R(h + "</table></div>")

    if view == 'ledger':
        rows = ex(c, "SELECT * FROM ledger").fetchall()
        h = "<div class=pt>📒 دفتر الحسابات</div><div class=c><table><tr><th>التاريخ</th><th>الحساب</th><th>المبلغ</th></tr>"
        for r in rows:
            rd = dict(r)
            h += f"<tr><td>{rd.get('date','')}</td><td>{rd.get('sub','')}</td><td>{rd.get('amount','')}</td></tr>"
        return R(h + "</table></div>")

    return R("<div class=pt>🏠 الرئيسية</div><div class='c'><h3>أهلاً بك في نظام إدارة أوميا (OMAIA ISP)</h3><p>استخدم القائمة الجانبية للتنقل بين الفروع بسلاسة.</p></div>")

@app.route('/', methods=['GET', 'POST'])
@app.route('/dash', methods=['GET', 'POST'])
def system_main_route():
    if 'p' in session:
        return render_view_page(request.args.get('view', 'home'), db())
    if request.method == 'POST':
        i = request.form.get('phone', '').strip()
        c = db()
        u = ex(c, "SELECT * FROM users WHERE phone=? OR username=?", (i, i))
        d = u.fetchone() if hasattr(u, 'fetchone') else (u if u else None)
        if d:
