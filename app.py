from flask import Flask, request, redirect, render_template_string, session
import os, sqlite3, time
from datetime import datetime

try: import psycopg2
except ImportError: psycopg2 = None

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "omia-secure-2026")
DBURL = os.environ.get("DATABASE_URL", "")
USE_PG = bool(DBURL and psycopg2)
WA_DISPLAY, WA_LINK = "0095344851045", "963544851045"

def get_db():
    if USE_PG:
        conn = psycopg2.connect(DBURL, sslmode='require')
        conn.autocommit = True; return conn
    c = sqlite3.connect("omia.db", check_same_thread=False)
    c.row_factory = sqlite3.Row; return c

def q_db(c, q, a=()):
    cur = c.cursor()
    cur.execute(q.replace("?", "%s") if USE_PG else q, a)
    try:
        if cur.description:
            res = cur.fetchall()
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in res]
    except: pass
    return cur

def init_system():
    c = get_db()
    p, s = "id SERIAL PRIMARY KEY,", "id INTEGER PRIMARY KEY AUTOINCREMENT,"
    tbs = [
        "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,username TEXT,password TEXT,role TEXT,active INT)",
        f"CREATE TABLE IF NOT EXISTS subs({p if USE_PG else s}name TEXT,phone TEXT,status TEXT)",
        f"CREATE TABLE IF NOT EXISTS dish_ips({p if USE_PG else s}ip TEXT,name TEXT,location TEXT,tower TEXT,zone TEXT)",
        f"CREATE TABLE IF NOT EXISTS ledger({p if USE_PG else s}date TEXT,sub TEXT,amount REAL,currency TEXT,note TEXT)"
    ]
    for t in tbs: q_db(c, t)
    if not q_db(c, "SELECT 1 FROM users WHERE phone='05344851045'"):
        q_db(c, "INSERT INTO users VALUES('05344851045','admin','admin2024','super',1)")
    c.close()

init_system()

CSS = """*{transition:all 0.4s ease;box-sizing:border-box}body{font-family:Arial;margin:0;background:#0b111e;color:#e2e8f0}.t{position:fixed;top:0;inset-x:0;height:56px;background:rgba(17,24,39,0.8);backdrop-filter:blur(16px);display:flex;align-items:center;justify-content:space-between;padding:0 16px;z-index:20;border-bottom:1px solid rgba(0,212,255,0.25)}.m{padding:76px 12px 24px;max-width:1100px;margin:auto}.c{background:rgba(30,41,59,0.45);backdrop-filter:blur(12px);border:1px solid rgba(0,212,255,0.15);border-radius:16px;padding:16px;margin-bottom:16px;animation:up 0.6s ease both}@keyframes up{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}.fade-out{opacity:0;transform:translateY(-15px)}.pt{text-align:right;font-weight:bold;font-size:20px;color:#00D4FF;margin-bottom:12px}button{background:linear-gradient(135deg,#00D4FF,#0086b3);border:0;padding:11px;width:100%;border-radius:12px;font-weight:bold;cursor:pointer;color:#021}input,select{width:100%;padding:11px;margin:6px 0;border-radius:12px;border:1px solid #334155;background:#0f172a;color:#fff}table{width:100%;border-collapse:collapse;margin-top:10px}td,th{padding:10px;border-bottom:1px solid rgba(51,65,85,0.4);text-align:center}th{color:#00D4FF}.drawer{position:fixed;top:0;right:-285px;width:265px;height:100%;background:#0f172a;z-index:30;transition:0.4s;padding:62px 12px}.drawer.open{right:0}.overlay{position:fixed;inset:0;background:rgba(0,0,0,0.5);display:none;z-index:25}.overlay.show{display:block}.drawer a{display:flex;gap:10px;color:#fff;text-decoration:none;padding:11px;border-radius:10px;cursor:pointer}.drawer a:hover{background:rgba(0,212,255,0.15);color:#00D4FF}.menuBtn{cursor:pointer;font-size:22px;color:#fff;background:#00D4FF;width:38px;height:40px;display:flex;align-items:center;justify-content:center;border-radius:10px}.btn-del{background:#ef4444;color:#fff;padding:4px 8px;border-radius:6px;text-decoration:none;font-size:12px;margin:2px}.btn-edit{background:#f59e0b;color:#fff;padding:4px 8px;border-radius:6px;text-decoration:none;font-size:12px;margin:2px}.stats-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px}@media(max-width:700px){.stats-grid{grid-template-columns:1fr}}.stat-card{background:rgba(0,212,255,0.06);border:1px solid rgba(0,212,255,0.2);padding:16px;border-radius:12px;text-align:center}.stat-card h3{margin:0;font-size:26px;color:#00D4FF}.stat-card p{margin:4px 0 0;color:#94a3b8}"""

LAY = """<!DOCTYPE html><html dir=rtl><head><meta charset=UTF-8><meta name=viewport content='width=device-width,initial-scale=1'><title>OMIA ISP</title><style>""" + CSS + """</style></head><body><div class=t><div style=display:flex;gap:10px;align-items:center><div class=menuBtn onclick="document.getElementById('dr').classList.add('open');document.getElementById('ov').classList.add('show')">☰</div><b style=color:#00D4FF>✨ OMIA ISP</b></div></div><div id=ov class=overlay onclick="document.getElementById('dr').classList.remove('open');this.classList.remove('show')"></div><div id=dr class=drawer><a href=/>🏠 الرئيسية</a><a onclick="go('/?view=subs')">👥 المشتركين</a><a onclick="go('/?view=dishes')">📡 الصحون</a><a onclick="go('/?view=ledger')">📒 الحسابات</a><a onclick="go('/?view=settings')">⚙️ الإعدادات</a><a href=/logout>🚪 خروج</a></div><div class=m id=panel_content>{{c|safe}}</div><script>function fS(v){document.querySelectorAll('table tr').forEach((r,i)=>{if(i==0)return;r.style.display=r.innerText.includes(v)?'':'none'})}async function go(url){document.getElementById('dr').classList.remove('open');document.getElementById('ov').classList.remove('show');let panel=document.getElementById('panel_content');panel.classList.add('fade-out');setTimeout(async()=>{let res=await fetch(url,{headers:{'X-Requested-With':'Fetch'}});panel.innerHTML=await res.text();panel.classList.remove('fade-out');window.history.pushState({},'',url)},250)}</script></body></html>"""

def R(h):
    if request.headers.get('X-Requested-With') == 'Fetch': return h
    return render_template_string(LAY, c=h)

@app.route('/', methods=['GET', 'POST'])
@app.route('/dash', methods=['GET', 'POST'])
def system_main_route():
    if 'p' in session:
        c = get_db(); view = request.args.get('view', 'home')
        if view == 'home':
            s_res, d_res, u_res = q_db(c, "SELECT COUNT(*) as c FROM subs"), q_db(c, "SELECT COUNT(*) as c FROM dish_ips"), q_db(c, "SELECT COUNT(*) as c FROM users")
            v_subs = s_res[0]['c'] if s_res else 0
            v_dishes = d_res[0]['c'] if d_res else 0
            v_users = u_res[0]['c'] if u_res else 0
            c.close()
            return R(f"<div class=pt>🏠 الإحصائيات</div><div class=stats-grid><div class=stat-card><h3>{v_subs}</h3><p>المشتركين</p></div><div class=stat-card><h3>{v_dishes}</h3><p>الصحون والـ IPs</p></div><div class=stat-card><h3>{v_users}</h3><p>المستخدمين</p></div></div><div class=c style='text-align:center'><h3>مرحباً بك في نظام إدارة OMIA ISP</h3><p style='color:#94a3b8'>تصفح سريع وسلس بجودة عالية.</p></div>")
        if view == 'subs':
            if request.method == 'POST':
                if request.form.get('action') == 'add': q_db(c, "INSERT INTO subs(name,phone,status) VALUES(?,?,?)", (request.form.get('name'), request.form.get('phone'), request.form.get('status')))
                elif request.form.get('action') == 'edit': q_db(c, "UPDATE subs SET name=?,phone=?,status=? WHERE id=?", (request.form.get('name'), request.form.get('phone'), request.form.get('status'), request.form.get('id')))
            rows = q_db(c, "SELECT * FROM subs") or []
            edit_id = request.args.get('edit')
            s_row = {"id": "", "name": "", "phone": "", "status": "نشط", "action": "add"}
            if edit_id:
                curr = q_db(c, "SELECT * FROM subs WHERE id=?", (edit_id,))
                if curr: s_row = curr[0]; s_row['action'] = 'edit'
            c.close()
            h = f"""<div class=pt>👥 المشتركين</div><div class=c><form method=post action='/?view=subs'><input type=hidden name=action value='{s_row['action']}'><input type=hidden name=id value='{s_row['id']}'><input name=name value='{s_row['name']}' placeholder='الاسم' required><input name=phone value='{s_row['phone']}' placeholder='الهاتف'><select name=status><option {'selected' if s_row['status']=='نشط' else ''}>نشط</option><option {'selected' if s_row['status']=='منتهي' else ''}>منتهي</option></select><button>💾 حفظ</button></form></div><div class=c><input placeholder='🔍 بحث...' oninput='fS(this.value)'><table><tr><th>الاسم</th><th>الهاتف</th><th>الحالة</th><th>التحكم</th></tr>"""
            for rd in rows: h += f"<tr><td>{rd['name']}</td><td>{rd['phone']}</td><td>{rd['status']}</td><td><a class=btn-edit href='/?view=subs&edit={rd['id']}'>📝</a><a class=btn-del href='/del?t=subs&id={rd['id']}'>🗑️</a></td></tr>"
            return R(h + "</table></div>")
        if view == 'dishes':
            if request.method == 'POST':
                if request.form.get('action') == 'add': q_db(c, "INSERT INTO dish_ips(ip,name,location,tower,zone) VALUES(?,?,?,?,?)", (request.form.get('ip'), request.form.get('name'), request.form.get('location'), request.form.get('tower'), request.form.get('zone')))
                elif request.form.get('action') == 'edit': q_db(c, "UPDATE dish_ips SET ip=?,name=?,location=?,tower=?,zone=? WHERE id=?", (request.form.get('ip'), request.form.get('name'), request.form.get('location'), request.form.get('tower'), request.form.get('zone'), request.form.get('id')))
            rows = q_db(c, "SELECT * FROM dish_ips") or []
            edit_id = request.args.get('edit')
            d_row = {"id": "", "ip": "", "name": "", "location": "", "tower": "", "zone": "", "action": "add"}
            if edit_id:
                curr = q_db(c, "SELECT * FROM dish_ips WHERE id=?", (edit_id,))
                if curr: d_row = curr[0]; d_row['action'] = 'edit'
            c.close()
