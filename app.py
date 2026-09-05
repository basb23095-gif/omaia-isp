from flask import Flask, request, redirect, render_template_string, session, jsonify
import os, sqlite3, time

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "omia-secure-key-2026")
DBURL = os.environ.get("DATABASE_URL", "")
USE_PG = bool(DBURL and psycopg2)

WA_DISPLAY = "0095344851045"
WA_LINK = "963544851045"
_pg, _pt = None, 0

def db():
    global _pg, _pt
    if USE_PG:
        if _pg and time.time() - _pt < 280:
            try: _pg.cursor().execute("SELECT 1"); return _pg
            except: pass
        _pg = psycopg2.connect(DBURL, sslmode='require')
        _pg.autocommit = True; _pt = time.time(); return _pg
    c = sqlite3.connect("omia.db", check_same_thread=False)
    c.row_factory = sqlite3.Row; return c

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
            "CREATE TABLE IF NOT EXISTS dish_ips(id SERIAL PRIMARY KEY,ip TEXT,name TEXT,location TEXT,tower TEXT,zone TEXT)",
            "CREATE TABLE IF NOT EXISTS ledger(id SERIAL PRIMARY KEY,date TEXT,sub TEXT,amount REAL,currency TEXT,note TEXT)"
        ]
        cur = c.cursor()
        for q in qs: cur.execute(q)
        cur.execute("SELECT 1 FROM users WHERE phone='05344851045'")
        if not cur.fetchone(): cur.execute("INSERT INTO users VALUES('05344851045','admin','admin2024','super',1)")
        cur.close(); return
    else:
        qs = [
            "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,username TEXT,password TEXT,role TEXT,active INT)",
            "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,status TEXT)",
            "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,name TEXT,location TEXT,tower TEXT,zone TEXT)",
            "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,date TEXT,sub TEXT,amount REAL,currency TEXT,note TEXT)"
        ]
        for q in qs: c.execute(q)
        if not c.execute("SELECT 1 FROM users WHERE phone='05344851045'").fetchone():
            c.execute("INSERT INTO users VALUES('05344851045','admin','admin2024','super',1)")
        c.commit(); c.close()

init()

CSS = """*{transition:all 0.4s cubic-bezier(0.4, 0, 0.2, 1);box-sizing:border-box}
body{font-family:Arial,sans-serif;margin:0;background:#0b111e;color:#e2e8f0;overflow-x:hidden}
.t{position:fixed;top:0;left:0;right:0;height:56px;background:rgba(17,24,39,0.8);backdrop-filter:blur(16px);display:flex;align-items:center;justify-content:space-between;padding:0 16px;z-index:20;border-bottom:1px solid rgba(0,212,255,0.25)}
.m{padding:76px 12px 24px;max-width:1100px;margin:auto}
.c{background:rgba(30,41,59,0.45);backdrop-filter:blur(12px);border:1px solid rgba(0,212,255,0.15);border-radius:16px;padding:16px;margin-bottom:16px;animation:slowUp 0.6s ease both}
@keyframes slowUp{from{opacity:0;transform:translateY(25px)}to{opacity:1;transform:translateY(0)}}
.fade-out{opacity:0;transform:translateY(-15px)}
.pt{text-align:right;font-weight:bold;font-size:20px;color:#00D4FF;margin-bottom:12px}
button{background:linear-gradient(135deg,#00D4FF,#0086b3);border:0;padding:11px;width:100%;border-radius:12px;font-weight:bold;cursor:pointer;color:#021}
button:hover{transform:translateY(-1px);box-shadow:0 6px 20px rgba(0,212,255,0.3)}
input,select{width:100%;padding:11px;margin:6px 0;border-radius:12px;border:1px solid #334155;background:#0f172a;color:#fff}
input:focus{border-color:#00D4FF;outline:none}
table{width:100%;border-collapse:collapse;margin-top:10px}td,th{padding:10px;border-bottom:1px solid rgba(51,65,85,0.4);text-align:center}th{color:#00D4FF}
.drawer{position:fixed;top:0;right:-285px;width:265px;height:100%;background:#0f172a;z-index:30;transition:0.4s;padding:62px 12px;box-shadow:-5px 0 25px rgba(0,0,0,0.5)}
.drawer.open{right:0}.overlay{position:fixed;inset:0;background:rgba(0,0,0,0.5);display:none;z-index:25}.overlay.show{display:block}
.drawer a{display:flex;gap:10px;color:#fff;text-decoration:none;padding:11px;border-radius:10px;cursor:pointer}
.drawer a:hover{background:rgba(0,212,255,0.15);color:#00D4FF;transform:translateX(-5px)}
.menuBtn{cursor:pointer;font-size:22px;color:#fff;background:#00D4FF;width:38px;height:40px;display:flex;align-items:center;justify-content:center;border-radius:10px}
.btn-del{background:#ef4444;color:#fff;padding:5px 10px;border-radius:8px;text-decoration:none;font-size:12px;margin:2px}
.btn-edit{background:#f59e0b;color:#fff;padding:5px 10px;border-radius:8px;text-decoration:none;font-size:12px;margin:2px}
.stats-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px}
@media(max-width:700px){.stats-grid{grid-template-columns:1fr}}
.stat-card{background:rgba(0,212,255,0.06);border:1px solid rgba(0,212,255,0.2);padding:16px;border-radius:12px;text-align:center}
.stat-card h3{margin:0;font-size:28px;color:#00D4FF}
.stat-card p{margin:4px 0 0;color:#94a3b8}"""

LAY = """<!DOCTYPE html><html dir=rtl><head><meta charset=UTF-8><meta name=viewport content='width=device-width,initial-scale=1'><title>OMIA ISP</title><style>""" + CSS + """</style></head><body>
<div class=t><div style=display:flex;gap:10px;align-items:center><div class=menuBtn onclick="document.getElementById('dr').classList.add('open');document.getElementById('ov').classList.add('show')">☰</div><b style=color:#00D4FF>✨ OMIA ISP</b></div></div>
<div id=ov class=overlay onclick="document.getElementById('dr').classList.remove('open');this.classList.remove('show')"></div>
<div id=dr class=drawer><a onclick="go('/')">🏠 الرئيسية</a><a onclick="go('/?view=subs')">👥 المشتركين</a><a onclick="go('/?view=dishes')">📡 الصحون</a><a onclick="go('/?view=ledger')">📒 الحسابات</a><a onclick="go('/?view=settings')">⚙️ الإعدادات</a><a href=/logout>🚪 خروج</a></div>
<div class=m id=panel_content>{{c|safe}}</div>
<script>
function fS(v){document.querySelectorAll('table tr').forEach((r,i)=>{if(i==0)return;r.style.display=r.innerText.includes(v)?'':'none'})}
async function go(url) {
    document.getElementById('dr').classList.remove('open');
    document.getElementById('ov').classList.remove('show');
    let panel = document.getElementById('panel_content');
    panel.classList.add('fade-out');
    setTimeout(async () => {
        let res = await fetch(url, { headers: {'X-Requested-With': 'Fetch'} });
        panel.innerHTML = await res.text();
        panel.classList.remove('fade-out');
        window.history.pushState({}, '', url);
    }, 250);
}
</script>
</body></html>"""

def R(h):
    if request.headers.get('X-Requested-With') == 'Fetch': return h
    return render_template_string(LAY, c=h)

@app.route('/', methods=['GET', 'POST'])
@app.route('/dash', methods=['GET', 'POST'])
def system_main_route():
    if 'p' in session:
        c = db(); view = request.args.get('view', 'home')
        
        # 1. الصفحة الرئيسية والعدادات الذكية
        if view == 'home':
            n_subs = ex(c, "SELECT COUNT(*) FROM subs").fetchone()
            n_dishes = ex(c, "SELECT COUNT(*) FROM dish_ips").fetchone()
            n_users = ex(c, "SELECT COUNT(*) FROM users").fetchone()
            v_subs = list(dict(n_subs).values())[0] if n_subs else 0
            v_dishes = list(dict(n_dishes).values())[0] if n_dishes else 0
            v_users = list(dict(n_users).values())[0] if n_users else 0
            
            h = f"""<div class=pt>🏠 لوحة التحكم والإحصائيات</div>
            <div class=stats-grid>
                <div class=stat-card><h3>{v_subs}</h3><p>إجمالي المشتركين</p></div>
                <div class=stat-card><h3>{v_dishes}</h3><p>إجمالي الصحون والـ IPs</p></div>
                <div class=stat-card><h3>{v_users}</h3><p>الفنيين والمستخدمين</p></div>
            </div>
            <div class=c style='text-align:center'><h3>مرحباً بك في نظام إدارة OMIA ISP</h3><p style='color:#94a3b8'>نظام تصفح سريع بحركات ناعمة وسلاسة تحكم فائقة.</p></div>"""
            return R(h)

        # 2. إدارة وتعديل المشتركين
        if view == 'subs':
            if request.method == 'POST':
                if request.form.get('action') == 'add':
                    ex(c, "INSERT INTO subs(name,phone,status) VALUES(?,?,?)", (request.form.get('name'), request.form.get('phone'), request.form.get('status')))
                elif request.form.get('action') == 'edit':
                    ex(c, "UPDATE subs SET name=?, phone=?, status=? WHERE id=?", (request.form.get('name'), request.form.get('phone'), request.form.get('status'), request.form.get('id')))
            rows = ex(c, "SELECT * FROM subs").fetchall()
            
            edit_id = request.args.get('edit')
            sub_row = {"id": "", "name": "", "phone": "", "status": "نشط", "action": "add"}
            if edit_id:
                curr = ex(c, "SELECT * FROM subs WHERE id=?", (edit_id,)).fetchone()
                if curr: sub_row = dict(curr); sub_row['action'] = 'edit'

            h = f"""<div class=pt>👥 إدارة المشتركين</div>
            <div class=c>
                <form method=post action='/?view=subs'>
                    <input type=hidden name=action value='{sub_row['action']}'>
                    <input type=hidden name=id value='{sub_row['id']}'>
                    <input name=name value='{sub_row['name']}' placeholder='اسم المشترك' required>
                    <input name=phone value='{sub_row['phone']}' placeholder='رقم الهاتف'>
