from flask import Flask, request, redirect, render_template_string, session
import os, sqlite3
from datetime import datetime

try: import psycopg2
except ImportError: psycopg2 = None

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "omia-sec-2026")
DBURL = os.environ.get("DATABASE_URL", "")
USE_PG = bool(DBURL and psycopg2)

# ---------- DB ----------
def get_db():
    if USE_PG:
        conn = psycopg2.connect(DBURL, sslmode='require')
        conn.autocommit = True
        return conn
    c = sqlite3.connect("omia.db", check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def q_db(c, q, a=()):
    cur = c.cursor()
    cur.execute(q.replace("?", "%s") if USE_PG else q, a)
    try:
        if cur.description:
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
    except: pass
    return cur

def init_system():
    c = get_db()
    pk = "id SERIAL PRIMARY KEY," if USE_PG else "id INTEGER PRIMARY KEY AUTOINCREMENT,"
    for t in [
        "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,username TEXT,password TEXT,role TEXT,active INT)",
        f"CREATE TABLE IF NOT EXISTS subs({pk}name TEXT,phone TEXT,status TEXT)",
        f"CREATE TABLE IF NOT EXISTS dish_ips({pk}ip TEXT,name TEXT,location TEXT,tower TEXT,zone TEXT)",
        f"CREATE TABLE IF NOT EXISTS ledger({pk}date TEXT,person TEXT,amount REAL,currency TEXT,note TEXT)"
    ]: q_db(c, t)
    if not q_db(c, "SELECT 1 FROM users WHERE phone='05344851045'"):
        q_db(c, "INSERT INTO users VALUES('05344851045','admin','admin2024','super',1)")
    c.close()
init_system()

# ---------- ملف الألوان لحال ----------
COLORS_CSS = """
:root{--main:#00D4FF;--bg:#0b111e;--card:rgba(30,41,59,.5)}
*{transition:all.35s cubic-bezier(.4,0,.2,1);box-sizing:border-box}
body{font-family:Tahoma,Arial;margin:0;background:var(--bg);color:#e2e8f0}
.t{position:fixed;top:0;right:0;left:0;height:56px;background:rgba(17,24,39,.85);backdrop-filter:blur(16px);display:flex;align-items:center;justify-content:space-between;padding:0 16px;z-index:20;border-bottom:1px solid rgba(0,212,255,.25)}
.m{padding:76px 12px 24px;max-width:1100px;margin:auto}
.c{background:var(--card);backdrop-filter:blur(14px);border:1px solid rgba(0,212,255,.15);border-radius:16px;padding:16px;margin-bottom:16px;animation:up.5s ease both}
@keyframes up{from{opacity:0;transform:translateY(18px)}to{opacity:1;transform:none}}
.fade-out{opacity:0;transform:translateY(-12px) scale(.99)}
.pt{text-align:right;font-weight:bold;font-size:20px;color:var(--main);margin-bottom:12px}
button{background:linear-gradient(135deg,var(--main),#0086b3);border:0;padding:11px;width:100%;border-radius:12px;font-weight:bold;cursor:pointer;color:#02131a}
input,select{width:100%;padding:11px;margin:6px 0;border-radius:12px;border:1px solid #334155;background:#0f172a;color:#fff}
table{width:100%;border-collapse:collapse;margin-top:10px}
td,th{padding:10px;border-bottom:1px solid rgba(51,65,85,.4);text-align:center}
th{color:var(--main)}
.drawer{position:fixed;top:0;right:-285px;width:265px;height:100%;background:#0f172a;z-index:30;transition:right.4s ease;padding:62px 12px}
.drawer.open{right:0}
.overlay{position:fixed;inset:0;background:rgba(0,0,0,.55);display:none;z-index:25}
.overlay.show{display:block}
.drawer a{display:flex;gap:10px;color:#cbd5e1;text-decoration:none;padding:12px;border-radius:10px;cursor:pointer;margin-bottom:4px}
.drawer a.active{background:linear-gradient(135deg,rgba(0,212,255,.25),rgba(0,212,255,.1));color:var(--main);font-weight:bold;border:1px solid rgba(0,212,255,.3)}
.menuBtn{cursor:pointer;font-size:22px;color:#fff;background:linear-gradient(135deg,var(--main),#0090c0);width:40px;height:40px;display:flex;align-items:center;justify-content:center;border-radius:10px}
.btn-del{background:#ef4444;color:#fff;padding:5px 10px;border-radius:8px;text-decoration:none;font-size:13px;margin:2px;display:inline-block}
.btn-edit{background:#f59e0b;color:#fff;padding:5px 10px;border-radius:8px;text-decoration:none;font-size:13px;margin:2px;display:inline-block}
.stats-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px}
.stat-card{background:rgba(0,212,255,.06);border:1px solid rgba(0,212,255,.2);padding:18px;border-radius:14px;text-align:center}
.stat-card h3{margin:0;font-size:28px;color:var(--main)}
.ip-link{color:var(--main);text-decoration:underline}
@media(max-width:700px){.stats-grid{grid-template-columns:1fr}}
"""

LAY = """<!DOCTYPE html><html dir=rtl><head><meta charset=UTF-8><meta name=viewport content='width=device-width,initial-scale=1'>
<title>OMIA ISP</title><style>__CSS__</style></head><body>
<div class=t><div style=display:flex;gap:10px;align-items:center><div class=menuBtn onclick="openDr()">☰</div><b style=color:#00D4FF>✨ OMIA ISP</b></div></div>
<div id=ov class=overlay onclick="closeDr()"></div>
<div id=dr class=drawer>
<a href=/?view=home data-v=home>🏠 الرئيسية</a>
<a href=/?view=subs data-v=subs>👥 المشتركين</a>
<a href=/?view=dishes data-v=dishes>📡 الصحون</a>
<a href=/?view=ledger data-v=ledger>📒 دفتر الحسابات</a>
<a href=/?view=settings data-v=settings>⚙️ الإعدادات</a>
<a href=/logout>🚪 خروج</a>
</div>
<div class=m id=panel_content>{{c|safe}}</div>
<script>
function openDr(){document.getElementById('dr').classList.add('open');document.getElementById('ov').classList.add('show')}
function closeDr(){document.getElementById('dr').classList.remove('open');document.getElementById('ov').classList.remove('show')}
document.addEventListener('click',e=>{let d=document.getElementById('dr');if(d.classList.contains('open')&&!d.contains(e.target)&&!e.target.closest('.menuBtn'))closeDr();});
function setActive(){let v=new URLSearchParams(location.search).get('view')||'home';document.querySelectorAll('.drawer a[data-v]').forEach(a=>a.classList.toggle('active',a.dataset.v===v));}
setActive();
function fS(v){document.querySelectorAll('table tr').forEach((r,i)=>{if(i==0)return;r.style.display=r.innerText.includes(v)?'':'none'})}
async function go(url){closeDr();let p=document.getElementById('panel_content');p.classList.add('fade-out');setTimeout(async()=>{let r=await fetch(url,{headers:{'X-Requested-With':'Fetch'}});p.innerHTML=await r.text();p.classList.remove('fade-out');window.history.pushState({},'',url);setActive();},220);}
document.querySelectorAll('.drawer a[data-v]').forEach(a=>a.addEventListener('click',e=>{e.preventDefault();go(a.href)}));
</script></body></html>""".replace("__CSS__", COLORS_CSS)

def R(h):
    if request.headers.get('X-Requested-With') == 'Fetch': return h
    return render_template_string(LAY, c=h)

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        ident=request.form.get('ident','').strip(); pwd=request.form.get('password','').strip()
        c=get_db(); u=q_db(c,"SELECT * FROM users WHERE (phone=? OR username=?) AND password=?",(ident,ident,pwd)); c.close()
        if u:
            session['p']=u[0]['phone']; return redirect('/')
        return R("<div class=c><p style=color:red>بيانات خاطئة</p><a href=/login style=color:#00D4FF>رجوع</a></div>")
    return render_template_string("<html dir=rtl><head><meta charset=UTF-8><meta name=viewport content='width=device-width,initial-scale=1'><title>OMIA ISP</title><style>"+COLORS_CSS+"</style></head><body><div class=m style='max-width:400px;padding-top:100px'><div class=c><div class=pt style=text-align:center>✨ OMIA ISP</div><form method=post><input name=ident placeholder='اسم المستخدم / رقم الهاتف' required><input name=password type=password placeholder='كلمة السر' required><button>دخول</button></form></div></div></body></html>")

@app.route('/logout')
def lo(): session.clear(); return redirect('/login')

@app.route('/', methods=['GET','POST'])
def main():
    if 'p' not in session: return redirect('/login')
    c=get_db(); view=request.args.get('view','home')

    if view=='home':
        s=q_db(c,"SELECT COUNT(*) as c FROM subs")[0]['c']
        d=q_db(c,"SELECT COUNT(*) as c FROM dish_ips")[0]['c']
        u=q_db(c,"SELECT COUNT(*) as c FROM users")[0]['c']
        c.close()
        return R(f"<div class=pt>🏠 الرئيسية</div><div class=stats-grid><div class=stat-card><h3>{s}</h3><p>عدد المشتركين</p></div><div class=stat-card><h3>{d}</h3><p>عدد الصحون</p></div><div class=stat-card><h3>{u}</h3><p>عدد المستخدمين</p></div></div><div class=c><input placeholder='🔍 بحث سريع...' oninput='fS(this.value)'></div>")

    if view=='subs':
        if request.method=='POST':
            if request.form.get('action')=='add': q_db(c,"INSERT INTO subs(name,phone,status) VALUES(?,?,?)",(request.form.get('name'),request.form.get('phone'),request.form.get('status')))
            else: q_db(c,"UPDATE subs SET name=?,phone=?,status=? WHERE id=?",(request.form.get('name'),request.form.get('phone'),request.form.get('status'),request.form.get('id')))
        rows=q_db(c,"SELECT * FROM subs") or []
        eid=request.args.get('edit'); er={"id":"","name":"","phone":"","status":"نشط","action":"add"}
        if eid:
            cur=q_db(c,"SELECT * FROM subs WHERE id=?",(eid,))
            if cur: er=cur[0]; er['action']='edit'
        c.close()
        h=f"<div class=pt>👥 المشتركين</div><div class=c><form method=post action='/?view=subs'><input type=hidden name=action value='{er['action']}'><input type=hidden name=id value='{er['id']}'><input name=name value='{er['name']}' placeholder='الاسم' required><input name=phone value='{er['phone']}' placeholder='الهاتف'><select name=status><option {'selected' if er['status']=='نشط' else ''}>نشط</option><option {'selected' if er['status']=='منتهي' else ''}>منتهي</option></select><button>💾 حفظ</button></form></div><div class=c><table><tr><th>الاسم</th><th>الهاتف</th><th>الحالة</th><th>تحكم</th></tr>"
        for r in rows: h+=f"<tr><td>{r['name']}</td><td>{r['phone']}</td><td>{r['status']}</td><td><a class=btn-edit href='/?view=subs&edit={r['id']}'>تعديل</a><a class=btn-del href='/del?t=subs&id={r['id']}'>حذف</a></td></tr>"
        return R(h+"</table></div>")

    if view=='dishes':
        if request.method=='POST':
            if request.form.get('action')=='add': q_db(c,"INSERT INTO dish_ips(ip,name,location,tower,zone) VALUES(?,?,?,?,?)",(request.form.get('ip'),request.form.get('name'),request.form.get('location'),request.form.get('tower'),request.form.get('zone')))
            else: q_db(c,"UPDATE dish_ips SET ip=?,name=?,location=?,tower=?,zone=? WHERE id=?",(request.form.get('ip'),request.form.get('name'),request.form.get('location'),request.form.get('tower'),request.form.get('zone'),request.form.get('id')))
        rows=q_db(c,"SELECT * FROM dish_ips") or []
        eid=request.args.get('edit'); er={"id":"","ip":"","name":"","location":"","tower":"","zone":"","action":"add"}
        if eid:
            cur=q_db(c,"SELECT * FROM dish_ips WHERE id=?",(eid,))
            if cur: er=cur[0]; er['action']='edit'
        c.close()
        h=f"<div class=pt>📡 الصحون</div><div class=c><form method=post action='/?view=dishes'><input type=hidden name=action value='{er['action']}'><input type=hidden name=id value='{er['id']}'><input name=ip value='{er['ip']}' placeholder='IP' dir=ltr required><input name=name value='{er['name']}' placeholder='اسم الموقع'><input name=location value='{er['location']}' placeholder='الموقع'><input name=tower value='{er['tower']}' placeholder='البرج'><input name=zone value='{er['zone']}' placeholder='المنطقة'><button>💾 حفظ</button></form></div><div class=c><input placeholder='🔍 بحث مع الصحون...' oninput='fS(this.value)'><table><tr><th>IP</th><th>الموقع</th><th>البرج</th><th>المنطقة</th><th>تحكم</th></tr>"
        for r in rows: h+=f"<tr><td><a class=ip-link href='http://{r['ip']}' target=_blank>{r['ip']}</a></td><td>{r['name']}</td><td>{r['tower']}</td><td>{r['zone']}</td><td><a class=btn-edit href='/?view=dishes&edit={r['id']}'>تعديل</a><a class=btn-del href='/del?t=dishes&id={r['id']}'>حذف</a></td></tr>"
        return R(h+"</table></div>")

    if view=='ledger':
        if request.method=='POST':
            if request.form.get('action')=='add': q_db(c,"INSERT INTO ledger(date,person,amount,currency,note) VALUES(?,?,?,?,?)",(datetime.now().strftime("%Y-%m-%d %H:%M"),request.form.get('person'),request.form.get('amount'),request.form.get('currency'),request.form.get('note')))
            else: q_db(c,"UPDATE ledger SET person=?,amount=?,currency=?,note=? WHERE id=?",(request.form.get('person'),request.form.get('amount'),request.form.get('currency'),request.form.get('note'),request.form.get('id')))
        rows=q_db(c,"SELECT * FROM ledger ORDER BY id DESC") or []
        eid=request.args.get('edit'); er={"id":"","person":"","amount":"","currency":"$","note":"","action":"add"}
        if eid:
            cur=q_db(c,"SELECT * FROM ledger WHERE id=?",(eid,))
            if cur: er=cur[0]; er['action']='edit'
        c.close()
        sd="selected" if er['currency']=="$" else ""; ss="selected" if er['currency']=="ل.س" else ""
        h=f"<div class=pt>📒 دفتر الحسابات</div><div class=c><form method=post action='/?view=ledger'><input type=hidden name=action value='{er['action']}'><input type=hidden name=id value='{er['id']}'><input name=person value='{er['person']}' placeholder='اسم الشخص' required><input name=amount type=number step=0.01 value='{er['amount']}' placeholder='المبلغ' required><select name=currency><option value='$' {sd}>دولار $</option><option value='ل.س' {ss}>سوري ل.س</option></select><input name=note value='{er['note']}' placeholder='ملاحظة'><button>⚡ شحن</button></form></div><div class=c><table><tr><th>اسم الشخص</th><th>المبلغ</th><th>العملة</th><th>التاريخ</th><th>تحكم</th></tr>"
        for r in rows: h+=f"<tr><td>{r['person']}</td><td>{r['amount']}</td><td>{r['currency']}</td><td>{r['date']}</td><td><a class=btn-edit href='/?view=ledger&edit={r['id']}'>تعديل</a><a class=btn-del href='/del?t=ledger&id={r['id']}'>حذف</a></td></tr>"
        return R(h+"</table></div>")

    if view=='settings':
        if request.method=='POST':
            if request.form.get('action')=='add': q_db(c,"INSERT INTO users(phone,username,password,role,active) VALUES(?,?,?,?,1)",(request.form.get('phone'),request.form.get('username'),request.form.get('password'),'user'))
            else: q_db(c,"UPDATE users SET username=?,password=?,phone=? WHERE phone=?",(request.form.get('username'),request.form.get('password'),request.form.get('phone'),request.form.get('id')))
        rows=q_db(c,"SELECT * FROM users") or []
        eid=request.args.get('edit'); er={"phone":"","username":"","password":"","action":"add"}; er['id']=""
        if eid:
            cur=q_db(c,"SELECT * FROM users WHERE phone=?",(eid,))
            if cur: er=cur[0]; er['action']='edit'; er['id']=eid
        c.close()
        h=f"<div class=pt>⚙️ الإعدادات</div><div class=c><form method=post action='/?view=settings'><input type=hidden name=action value='{er['action']}'><input type=hidden name=id value='{er['id'] or er['phone']}'><input name=username value='{er['username']}' placeholder='اسم المستخدم' required><input name=phone value='{er['phone']}' placeholder='رقم الهاتف' required><input name=password value='{er['password']}' placeholder='كلمة السر' required><button>💾 حفظ المستخدم</button></form></div><div class=c><table><tr><th>المستخدم</th><th>الهاتف</th><th>تحكم</th></tr>"
        for r in rows: h+=f"<tr><td>{r['username']}</td><td>{r['phone']}</td><td><a class=btn-edit href='/?view=settings&edit={r['phone']}'>تعديل</a> <a class=btn-del href='/del?t=users&id={r['phone']}'>حذف</a></td></tr>"
        return R(h+"</table></div>")

    c.close(); return redirect('/?view=home')

@app.route('/del')
def delete():
    if 'p' not in session: return redirect('/login')
    t=request.args.get('t'); i=request.args.get('id')
    mp={'subs':("subs","id"),'dishes':("dish_ips","id"),'ledger':("ledger","id"),'users':("users","phone")}
    if t in mp:
        tbl,col=mp[t]
        if not (t=='users' and i=='05344851045'):
            c=get_db(); q_db(c,f"DELETE FROM {tbl} WHERE {col}=?",(i,)); c.close()
    return redirect(request.referrer or '/')

if __name__=='__main__':
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT",5000)))
