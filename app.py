from flask import Flask, request, redirect, session, jsonify
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, html, ipaddress, subprocess
try:
    import psycopg2, psycopg2.extras
except:
    psycopg2 = None
import sqlite3

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY","omia-sec-2026-CHANGE-ME")
DATABASE_URL = os.environ.get("DATABASE_URL","").strip()
USE_PG = bool(DATABASE_URL and psycopg2)
_pg = None

def esc(s): return html.escape(str(s or ''), quote=True)

def db():
    global _pg
    if USE_PG:
        try:
            if _pg:
                c=_pg.cursor();c.execute("SELECT 1");c.close();return _pg
        except: _pg=None
        _pg=psycopg2.connect(DATABASE_URL,sslmode='require');_pg.autocommit=True;return _pg
    c=sqlite3.connect("omia.db",check_same_thread=False);c.row_factory=sqlite3.Row;return c

def cc(c):
    if not USE_PG:
        try:c.close()
        except:pass

def qall(q,a=()):
    c=db()
    try:
        if USE_PG:
            cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor);cur.execute(q.replace("?","%s"),a);rs=[dict(r) for r in cur.fetchall()];cur.close();return rs
        else: rs=[dict(r) for r in c.execute(q,a).fetchall()];cc(c);return rs
    except: cc(c);return []

def qone(q,a=()):
    r=qall(q,a);return r[0] if r else None

def qexec(q,a=()):
    c=db()
    try:
        if USE_PG: cur=c.cursor();cur.execute(q.replace("?","%s"),a);cur.close()
        else: c.execute(q,a);c.commit();cc(c)
    except: cc(c)

def init():
    ss=[
    "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,username TEXT)",
    "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,note TEXT)",
    "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,amount REAL,note TEXT,currency TEXT)",
    "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,dish_name TEXT)",
    "CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,area TEXT,lat REAL,lng REAL)"
    ]
    if USE_PG: ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
    for s in ss: qexec(s)
    if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",('05344851045',generate_password_hash('admin2024'),'manager','admin'))
init()

def login_required(f):
    @wraps(f)
    def w(*a,**kw):
        if not session.get('phone'): return redirect('/login')
        return f(*a,**kw)
    return w

def is_valid_ip(ip):
    try: ipaddress.ip_address(ip.strip());return True
    except: return False

@app.route('/api/ping')
@login_required
def api_ping():
    ip=request.args.get('ip','').strip()
    if not is_valid_ip(ip): return jsonify(ok=False,out='IP غير صالح')
    try:
        out=subprocess.check_output(['ping','-c','1','-W','2',ip],timeout=4).decode(errors='ignore')
        ok='ttl=' in out.lower()
        return jsonify(ok=ok,out='متصل ✅' if ok else 'لا يرد ❌')
    except: return jsonify(ok=False,out='لا يرد ❌')

@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        uin=request.form.get('userin','').strip();pw=request.form.get('password','')
        u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
        if u and check_password_hash(u['password'],pw):
            session['phone']=u['phone'];return redirect('/dash')
        return "<script>alert('خطأ بالدخول');location.href='/login'</script>"
    return """<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<style>body{margin:0;min-height:100vh;background:#0a0e2a;display:flex;flex-direction:column;align-items:center;justify-content:center;color:#fff;font-family:sans-serif}
.card{background:#1e2433;padding:25px;border-radius:20px;width:320px}input{width:100%;padding:12px;margin:8px 0;background:#0f1424;border:1px solid #333;color:#fff;border-radius:12px;box-sizing:border-box}
.btn{width:100%;padding:13px;border:0;border-radius:12px;background:#ffbe4d;font-weight:800;cursor:pointer}</style></head><body>
<div style='font-size:28px;font-weight:800;margin-bottom:15px'>OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<div class=card><form method=post><input name=userin placeholder='يوزر / رقم هاتف' required>
<input name=password type=password placeholder='كلمة السر' required><button class=btn>دخول</button></form>
<div style='text-align:center;margin-top:15px'><a href='https://wa.me/905344851045' style='color:#22c55e;text-decoration:none'>📱 واتساب الدعم الفني</a></div></div></body></html>"""

@app.route('/logout')
def lo(): session.clear();return redirect('/login')

@app.route('/dash')
@login_required
def dash(): return layout(page_content(request.args.get('v','home')),request.args.get('v','home'))

@app.route('/api/page')
@login_required
def ap(): return page_content(request.args.get('v','home'))

@app.route('/api/search')
@login_required
def s():
    q=request.args.get('q','').strip()
    if q: return jsonify(qall("SELECT * FROM dish_ips WHERE ip LIKE? OR dish_name LIKE? OR location LIKE? ORDER BY id DESC LIMIT 30",("%"+q+"%","%"+q+"%","%"+q+"%",)))
    return jsonify(qall("SELECT * FROM dish_ips ORDER BY id DESC LIMIT 30"))

@app.route('/toggle_theme')
@login_required
def tt(): session['theme']='light' if session.get('theme','dark')=='dark' else 'dark';return "ok"

@app.route('/add_dish',methods=['POST'])
@login_required
def ad():
    ip=request.form.get('ip','').strip()
    if not is_valid_ip(ip): return "IP غير صالح",400
    qexec("INSERT INTO dish_ips(ip,location,dish_name) VALUES(?,?,?)",(ip,request.form.get('location',''),request.form.get('dish_name','')))
    return "ok"

@app.route('/edit_dish/<int:i>',methods=['POST'])
@login_required
def ed(i): qexec("UPDATE dish_ips SET dish_name=?,ip=?,location=? WHERE id=?",(request.form.get('dish_name',''),request.form.get('ip',''),request.form.get('location',''),i));return "ok"

@app.route('/del_dish/<int:i>')
@login_required
def dd(i): qexec("DELETE FROM dish_ips WHERE id=?",(i,));return "ok"

@app.route('/add_tower',methods=['POST'])
@login_required
def at(): qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",(request.form.get('name',''),request.form.get('area',''),35.1312,36.7578));return "ok"

@app.route('/del_tower/<int:i>')
@login_required
def dt(i): qexec("DELETE FROM towers WHERE id=?",(i,));return "ok"

@app.route('/edit_tower/<int:i>',methods=['POST'])
@login_required
def et(i): qexec("UPDATE towers SET name=?,area=? WHERE id=?",(request.form.get('name',''),request.form.get('area',''),i));return "ok"

@app.route('/add_sub',methods=['POST'])
@login_required
def asub(): qexec("INSERT INTO subs(name,phone,note) VALUES(?,?,?)",(request.form.get('name',''),request.form.get('phone',''),request.form.get('note','')));return "ok"

@app.route('/del_sub/<int:i>')
@login_required
def dsub(i): qexec("DELETE FROM subs WHERE id=?",(i,));return "ok"

@app.route('/edit_sub/<int:i>',methods=['POST'])
@login_required
def esub(i): qexec("UPDATE subs SET name=?,phone=?,note=? WHERE id=?",(request.form.get('name',''),request.form.get('phone',''),request.form.get('note',''),i));return "ok"

@app.route('/add_ledger',methods=['POST'])
@login_required
def al(): qexec("INSERT INTO ledger(name,amount,note,currency) VALUES(?,?,?,?)",(request.form.get('name',''),float(request.form.get('amount') or 0),request.form.get('note',''),request.form.get('currency','USD')));return "ok"

@app.route('/del_ledger/<int:i>')
@login_required
def dll(i): qexec("DELETE FROM ledger WHERE id=?",(i,));return "ok"

@app.route('/edit_ledger/<int:i>',methods=['POST'])
@login_required
def el(i): qexec("UPDATE ledger SET name=?,amount=?,note=?,currency=? WHERE id=?",(request.form.get('name',''),float(request.form.get('amount') or 0),request.form.get('note',''),request.form.get('currency','USD'),i));return "ok"

@app.route('/add_user',methods=['POST'])
@login_required
def au():
    ph=request.form.get('phone','').strip()
    if qone("SELECT * FROM users WHERE phone=?",(ph,)): return "موجود مسبقاً",400
    qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",(ph,generate_password_hash(request.form.get('password','1234')),request.form.get('role','tech'),request.form.get('username',ph)))
    return "ok"

@app.route('/edit_user',methods=['POST'])
@login_required
def eu():
    old=request.form.get('old_phone','')
    qexec("UPDATE users SET phone=?,username=?,role=? WHERE phone=?",(request.form.get('phone','').strip(),request.form.get('username',''),request.form.get('role','tech'),old))
    return "ok"

@app.route('/del_user/<ph>')
@login_required
def du(ph):
    if ph=='05344851045': return "ممنوع حذف المدير",400
    qexec("DELETE FROM users WHERE phone=?",(ph,));return "ok"

@app.route('/change_pass',methods=['POST'])
@login_required
def cp(): qexec("UPDATE users SET password=? WHERE phone=?",(generate_password_hash(request.form.get('newpass','')),session.get('phone')));return "ok"

def page_content(v):
    if v=='home':
        ns=(qone("SELECT COUNT(*) c FROM subs") or {}).get('c',0)
        nd=(qone("SELECT COUNT(*) c FROM dish_ips") or {}).get('c',0)
        nt=(qone("SELECT COUNT(*) c FROM towers") or {}).get('c',0)
        nl=(qone("SELECT COUNT(*) c FROM ledger") or {}).get('c',0)
        return f"<div style='max-width:700px;margin:0 auto;text-align:center'><div style='display:grid;grid-template-columns:1fr 1fr;gap:12px'><div class='card anim' onclick=\"loadPage('subs')\" style='cursor:pointer'><h3 data-l='subs'>المشتركين</h3><h2>{ns}</h2></div><div class='card anim' onclick=\"loadPage('dishes')\" style='cursor:pointer'><h3 data-l='dishes'>الصحون</h3><h2>{nd}</h2></div><div class='card anim' onclick=\"loadPage('towers')\" style='cursor:pointer'><h3 data-l='towers'>الأبراج</h3><h2>{nt}</h2></div><div class='card anim' onclick=\"loadPage('ledger')\" style='cursor:pointer'><h3 data-l='ledger'>الحسابات</h3><h2>{nl}</h2></div></div><a href='https://wa.me/905344851045' target=_blank class='wa-float'>💬</a></div>"
    if v=='dishes':
        return """<div style='max-width:900px;margin:0 auto'><div class=card><h3 data-l='dishes'>الصحون</h3>
<form data-ajax method=post action=/add_dish style='display:flex;gap:5px;flex-wrap:wrap'><input name=dish_name placeholder='اسم الصحن' required style='flex:1'><input name=ip placeholder='IP' required style='flex:1'><input name=location placeholder='موقع' style='flex:1'><button class=btn-gold>➕ إضافة</button></form></div><div id=dl></div>
<script>
async function ld(q=''){let r=await fetch('/api/search?q='+encodeURIComponent(q));let d=await r.json();let h='';d.forEach(x=>{h+=`<div class="card anim"><b>${x.dish_name}</b> - ${x.ip} <small>${x.location||''}</small><br><button class=btn-gold onclick="p1('${x.ip}',this)">📶 Ping</button> <span style='font-weight:800'></span> <button class=btn-gold onclick="editDish(${x.id},'${x.dish_name}','${x.ip}','${x.location||''}')">✏️ تعديل</button> <button class=btn-del onclick="askDel('/del_dish/${x.id}')">🗑️ حذف</button></div>`});document.getElementById('dl').innerHTML=h||'<div class=card>لا يوجد صحون</div>'}
async function p1(ip,b){let s=b.nextElementSibling;s.textContent='⏳...';let r=await fetch('/api/ping?ip='+ip);let j=await r.json();s.textContent=j.out}
function editDish(id,n,ip,loc){let nn=prompt('اسم:',n);if(nn==null)return;let ii=prompt('IP:',ip);if(ii==null)return;let ll=prompt('موقع:',loc);fetch('/edit_dish/'+id,{method:'POST',body:new URLSearchParams({dish_name:nn,ip:ii,location:ll||''})}).then(()=>ld())}
ld();window.searchDishes=ld;
</script></div>"""
    if v=='towers':
        rs=qall("SELECT * FROM towers ORDER BY id DESC");rows=""
        for r in rs: rows+=f"<div class='card anim'><b>🗼 {esc(r['name'])}</b> - {esc(r['area'])} <button class=btn-gold onclick=\"editTower({r['id']},'{esc(r['name'])}','{esc(r['area'])}')\">✏️ تعديل</button> <button class=btn-del onclick=\"askDel('/del_tower/{r['id']}')\">🗑️ حذف</button></div>"
        return f"<div style='max-width:700px;margin:0 auto'><div class=card><h3 data-l='towers'>الأبراج</h3><form data-ajax method=post action=/add_tower><input name=name placeholder='اسم البرج' required><input name=area placeholder='المنطقة'><button class=btn-gold>➕ إضافة</button></form></div>{rows or '<div class=card>لا يوجد أبراج</div>'}<script>function editTower(id,n,a){{let nn=prompt('اسم البرج:',n);if(nn==null)return;let aa=prompt('المنطقة:',a);if(aa==null)return;fetch('/edit_tower/'+id,{{method:'POST',body:new URLSearchParams({{name:nn,area:aa}})}}).then(()=>loadPage('towers'))}}</script></div>"
    if v=='subs':
        rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 150");rows=""
        for r in rs: rows+=f"<div class='card anim'><b>{esc(r['name'])}</b><br>📞 {esc(r['phone'])}<br><small>{esc(r['note'] or '')}</small><br><button class=btn-gold onclick='editSub({r['id']})'>✏️ تعديل</button> <button class=btn-del onclick=\"askDel('/del_sub/{r['id']}')\">🗑️ حذف</button></div>"
        return f"<div style='max-width:700px;margin:0 auto'><div class=card><h3 data-l='subs'>المشتركين</h3><form data-ajax method=post action=/add_sub><input name=name placeholder='يوزر' required><input name=phone placeholder='رقم'><input name=note placeholder='ملاحظة'><button class=btn-gold>➕ إضافة</button></form></div>{rows}<script>async function editSub(id){{let n=prompt('يوزر:');if(n==null)return;let p=prompt('رقم:');if(p==null)return;let no=prompt('ملاحظة:')||'';fetch('/edit_sub/'+id,{{method:'POST',body:new URLSearchParams({{name:n,phone:p,note:no}})}}).then(()=>loadPage('subs'))}}</script></div>"
    if v=='ledger':
        rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 150");rows=""
        for r in rs: rows+=f"<div class='card anim'><b>{esc(r['name'])}</b> - {r['amount']} {esc(r['currency'])}<br><small>{esc(r['note'])}</small><br><button class=btn-gold onclick='editL({r['id']})'>✏️ تعديل</button> <button class=btn-del onclick=\"askDel('/del_ledger/{r['id']}')\">🗑️ حذف</button></div>"
        return f"""<div style='max-width:700px;margin:0 auto'><div class=card><h3>الحسابات</h3>
<form data-ajax method=post action=/add_ledger><input name=name placeholder='الاسم' required><input name=amount type=number step=0.01 placeholder='المبلغ' required><input name=note placeholder='ملاحظة'><select name=currency><option value=USD>USD</option><option value=SYP>SYP</option></select><button class=btn-gold>➕ إضافة</button></form></div>{rows}
<script>function editL(id){{let n=prompt('الاسم:');if(n==null)return;let a=prompt('المبلغ:');if(a==null)return;fetch('/edit_ledger/'+id,{{method:'POST',body:new URLSearchParams({{name:n,amount:a,note:'',currency:'USD'}})}}).then(()=>loadPage('ledger'))}}</script></div>"""
    if v=='map':
        return """<div class=card><h3>الخريطة</h3><div id=map style='height:65vh;border-radius:12px;background:#e5e7eb'></div>
<script>
setTimeout(()=>{
let map=L.map('map').setView([35.1312,36.7578],12);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19}).addTo(map);
setTimeout(()=>{map.invalidateSize()},300);
L.marker([35.1312,36.7578]).addTo(map).bindPopup('حمص').openPopup();
},100);
</script></div>"""
    if v=='support':
        return """<div class=card style='text-align:center;max-width:500px;margin:0 auto'><h2>الدعم الفني</h2>
<a href='https://wa.me/905344851045' target=_blank style='display:inline-block;background:#22c55e;color:#fff;padding:14px 24px;border-radius:12px;text-decoration:none;margin:6px;font-weight:800'>💬 واتساب</a><br>
<a href='tel:+905344851045' style='display:inline-block;background:#0ea5e9;color:#fff;padding:12px 22px;border-radius:12px;text-decoration:none;margin:6px'>📞 اتصال</a></div>"""
    if v=='settings':
        us=qall("SELECT * FROM users ORDER BY phone DESC")
        uh="".join([f"<div class='card anim'><b>{esc(u['username'])}</b><br>📞 {esc(u['phone'])} | {esc(u['role'])}<br><button class=btn-gold onclick=\"editU('{esc(u['phone'])}','{esc(u['username'])}','{esc(u['role'])}')\">✏️ تعديل</button> <button class=btn-del onclick=\"askDel('/del_user/{esc(u['phone'])}')\">🗑️ حذف</button></div>" for u in us])
        return f"""<div style='max-width:600px;margin:0 auto'>
<div class=card><h3>كلمة السر</h3>
<form data-ajax method=post action=/change_pass><input name=newpass type=password placeholder='كلمة سر جديدة' required><button class=btn-gold>💾 حفظ</button></form></div>
<div class=card><h3>المستخدمين</h3><form data-ajax method=post action=/add_user><input name=username placeholder='يوزر' required><input name=phone placeholder='رقم' required><input name=password type=password placeholder='كلمة السر'><select name=role><option value=tech>فني</option><option value=manager>مدير</option></select><button class=btn-gold>إضافة</button></form></div>{uh}
<script>function editU(old,n,rl){{let nn=prompt('يوزر:',n);if(nn==null)return;let pp=prompt('رقم:',old);if(pp==null)return;fetch('/edit_user',{{method:'POST',body:new URLSearchParams({{old_phone:old,phone:pp,username:nn,role:rl}})}}).then(()=>loadPage('settings'))}}</script></div>"""
    return "<div class=card>ok</div>"

def layout(c,v='home'):
    th=session.get('theme','dark');is_dark=(th=='dark')
    bg='#0a0e2a' if is_dark else '#f1f5f9'
    card_bg='#1e2433' if is_dark else '#ffffff'
    txt='#ffffff' if is_dark else '#0f172a'
    return f"""<html dir=rtl lang=ar><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<link rel=stylesheet href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'>
<style>
*{{box-sizing:border-box;font-family:system-ui}}body{{margin:0;background:{bg};color:{txt}}}
.anim{{animation:fadeUp.35s ease both}}@keyframes fadeUp{{from{{opacity:0;transform:translateY(15px)}}to{{opacity:1;transform:none}}}}
.top{{position:fixed;top:0;left:0;right:0;height:60px;background:#111827d9;backdrop-filter:blur(12px);color:#fff;display:flex;align-items:center;justify-content:space-between;padding:0 12px;z-index:1003}}
.sidebar{{position:fixed;right:0;top:0;width:270px;height:100%;background:#111827f2;color:#fff;z-index:1002;padding-top:70px;transform:translateX(110%);transition:.3s}}
.sidebar.active{{transform:none}}
.sidebar a{{display:block;padding:12px 18px;margin:6px 12px;color:#fff;text-decoration:none;border-radius:12px;background:#ffffff10}}
#overlay{{position:fixed;inset:0;background:#0008;z-index:1001;display:none}}#overlay.show{{display:block}}
.main{{margin-top:70px;padding:12px;min-height:90vh}}
.card{{background:{card_bg};color:{txt};padding:14px;border-radius:14px;margin-bottom:10px;border:1px solid #ffffff15}}
input,select{{padding:10px;margin:5px 0;border-radius:10px;border:1px solid #ffffff22;width:100%;background:#ffffff08;color:inherit}}
.btn-gold{{background:#ffbe4d;color:#111;padding:9px 14px;border:0;border-radius:10px;font-weight:800;cursor:pointer;margin:3px}}
.btn-del{{background:#ef4444;color:#fff;padding:9px 14px;border:0;border-radius:10px;cursor:pointer;margin:3px}}
.wa-float{{position:fixed;bottom:20px;left:20px;background:#22c55e;width:55px;height:55px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:28px;text-decoration:none;z-index:999}}
#delModal{{position:fixed;inset:0;background:#0008;display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:.25s;z-index:2000}}
#delModal.show{{opacity:1;pointer-events:auto}}
#delBox{{background:{card_bg};color:{txt};padding:22px;border-radius:18px;width:90%;max-width:320px;text-align:center}}
</style></head>
<body><div id=overlay onclick="toggleSb(false)"></div>
<div class=sidebar id=sb>
<a href="javascript:loadPage('home')">🏠 الرئيسية</a><a href="javascript:loadPage('dishes')">📡 الصحون</a>
<a href="javascript:loadPage('towers')">🗼 الأبراج</a><a href="javascript:loadPage('subs')">👥 المشتركين</a>
<a href="javascript:loadPage('ledger')">📒 الحسابات</a><a href="javascript:loadPage('map')">🗺️ الخريطة</a>
<a href="javascript:loadPage('support')">🛠️ الدعم</a><a href="javascript:loadPage('settings')">⚙️ الإعدادات</a>
<a href=/logout>🚪 خروج</a></div>
<div class=top><div style='display:flex;gap:8px;align-items:center'><span onclick="toggleSb()" style='font-size:24px;cursor:pointer'>☰</span>
<input id=topsearch placeholder='🔍 بحث' oninput="if(cur=='dishes'&&window.searchDishes)searchDishes(this.value)" style='background:#1f2937;border:1px solid #374151;color:#fff;padding:7px 10px;border-radius:10px;width:120px'></div>
<div style='font-weight:800'>OMAIA ISP</div><div style='display:flex;gap:6px'><button onclick="toggleLang()" style='background:#1f2937;color:#fff;border:0;padding:8px 10px;border-radius:10px'>🌐 ع/En</button><button onclick="loadPage(cur)" style='background:#1f2937;color:#fff;border:0;padding:8px 10px;border-radius:10px'>↻</button></div></div>
<div class=main id=mn>{c}</div>
<div id=delModal><div id=delBox><div style='font-size:45px'>🗑️</div><h3>تأكيد الحذف</h3><div style='display:flex;gap:8px'><button onclick="closeDel()" style='flex:1;padding:12px;border-radius:10px'>تراجع</button><button id=delYes style='flex:1;padding:12px;border-radius:10px;background:#ef4444;color:#fff;border:0'>حذف</button></div></div></div>
<script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>
<script>
let cur='{v}';let delUrl=null;let lang='ar';
const T={{ar:{{subs:'المشتركين',dishes:'الصحون',towers:'الأبراج',ledger:'الحسابات'}},en:{{subs:'Subscribers',dishes:'Dishes',towers:'Towers',ledger:'Ledger'}}}};
function toggleLang(){{lang=lang=='ar'?'en':'ar';document.querySelectorAll('[data-l]').forEach(e=>{{let k=e.getAttribute('data-l');if(T[lang][k])e.textContent=T[lang][k]}});document.documentElement.lang=lang;document.dir=lang=='ar'?'rtl':'ltr'}}
function toggleSb(f){{let sb=document.getElementById('sb'),ov=document.getElementById('overlay');let o=f!==undefined?f:!sb.classList.contains('active');sb.classList.toggle('active',o);ov.classList.toggle('show',o)}}
async function loadPage(v){{cur=v;toggleSb(false);let mn=document.getElementById('mn');mn.innerHTML='<div class=card>⏳...</div>';try{{let r=await fetch('/api/page?v='+v);mn.innerHTML=await r.text();}}catch(e){{mn.innerHTML='<div class=card>خطأ بالتحميل</div>'}}bind()}}
function bind(){{document.querySelectorAll('form[data-ajax]').forEach(f=>{{f.onsubmit=async e=>{{e.preventDefault();let r=await fetch(f.action,{{method:'POST',body:new FormData(f)}});if(r.ok)loadPage(cur);else alert(await r.text())}}}})}}
function askDel(u){{delUrl=u;document.getElementById('delModal').classList.add('show')}}
function closeDel(){{document.getElementById('delModal').classList.remove('show');delUrl=null}}
document.getElementById('delYes').onclick=async()=>{{if(delUrl)await fetch(delUrl);closeDel();loadPage(cur)}};
bind();
</script></body></html>"""

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
