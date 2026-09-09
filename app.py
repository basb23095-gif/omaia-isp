from flask import Flask, request, redirect, session, jsonify, Response
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, html, ipaddress, json, socket, io, csv, datetime, time
import psycopg2, psycopg2.extras, sqlite3

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY","omia-sec-2026-CHANGE-ME")
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(days=30)

DATABASE_URL = os.environ.get("DATABASE_URL","").strip()
PG_URL = DATABASE_URL.replace("postgres://","postgresql://",1) if DATABASE_URL.startswith("postgres://") else DATABASE_URL
USE_PG = bool(DATABASE_URL)

_pg=None
def db():
    global _pg
    if USE_PG:
        try:
            if _pg:
                cur=_pg.cursor(); cur.execute("SELECT 1"); cur.close()
                return _pg
        except:
            try: _pg.close()
            except: pass
            _pg=None
        try:
            _pg=psycopg2.connect(PG_URL,sslmode='require',connect_timeout=3)
            _pg.autocommit=True
            return _pg
        except: pass
    try:
        c=sqlite3.connect("omia.db",check_same_thread=False,timeout=5)
        c.row_factory=sqlite3.Row
        return c
    except:
        c=sqlite3.connect(":memory:",check_same_thread=False)
        c.row_factory=sqlite3.Row
        return c

def cc(c):
    if not USE_PG:
        try: c.close()
        except: pass

def qall(q,a=()):
    c=db()
    try:
        if USE_PG:
            cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(q.replace("?","%s"),a)
            rs=[dict(r) for r in cur.fetchall()]; cur.close(); return rs
        else:
            rs=[dict(r) for r in c.execute(q,a).fetchall()]; cc(c); return rs
    except: cc(c); return []

def qone(q,a=()): r=qall(q,a); return r[0] if r else None
def qexec(q,a=()):
    c=db()
    try:
        if USE_PG:
            cur=c.cursor(); cur.execute(q.replace("?","%s"),a); cur.close()
        else: c.execute(q,a); c.commit(); cc(c)
    except: cc(c)

def esc(s): return html.escape(str(s or ''),quote=True)

def init():
    ss=[
    "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,username TEXT)",
    "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,note TEXT)",
    "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,amount REAL,note TEXT,currency TEXT)",
    "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,dish_name TEXT)",
    "CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,area TEXT,lat REAL,lng REAL)",
    "CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,user_phone TEXT,action TEXT,detail TEXT,time TEXT)",
    "CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,msg TEXT,time TEXT,read INTEGER DEFAULT 0)",
    "CREATE TABLE IF NOT EXISTS ips(id SERIAL PRIMARY KEY, ip TEXT, location TEXT, dish_name TEXT)"
    ]
    if USE_PG:
        for i in range(1,7): ss[i]=ss[i].replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY")
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
def is_manager():
    u=qone("SELECT * FROM users WHERE phone=?",(session.get('phone') or '',))
    return (u.get('role') or '').lower()=='manager' if u else False
def is_valid_ip(ip):
    try: ipaddress.ip_address(ip.strip()); return True
    except: return len(ip.strip())>=7 and '.' in ip

@app.route('/ping')
@app.route('/health')
def hp(): return jsonify(ok=True)

@app.route('/api/ping')
@login_required
def api_ping():
    ip=request.args.get('ip','').strip()
    if not is_valid_ip(ip): return jsonify(ok=False,out='IP غير صالح')
    for port in [80,8291,8728]:
        s=None
        try:
            s=socket.socket(socket.AF_INET,socket.SOCK_STREAM); s.settimeout(0.4)
            if s.connect_ex((ip,port))==0: s.close(); return jsonify(ok=True,out=f'✅ {ip}:{port} مفتوح')
            s.close()
        except:
            try:
                if s: s.close()
            except: pass
    return jsonify(ok=False,out=f'❌ {ip} لا يرد')

@app.route('/api/login_public',methods=['POST'])
def api_login():
    uin=request.form.get('userin','').strip(); pw=request.form.get('password','')
    u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
    if u and check_password_hash(u['password'],pw):
        session['phone']=u['phone']; session['username']=u.get('username') or u['phone']; session.permanent=True
        qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)",(u['phone'],'دخول',uin,datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        return jsonify(ok=True)
    return jsonify(ok=False,msg='خطأ'),401

@app.route('/toggle_lang')
@login_required
def tl(): s=session.get('lang','ar'); session['lang']='en' if s=='ar' else 'ar'; return jsonify(ok=True)
@app.route('/toggle_theme')
@login_required
def th(): s=session.get('theme','dark'); session['theme']='light' if s=='dark' else 'dark'; return jsonify(ok=True)
@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')
@app.route('/login')
def login():
    return """<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<style>*{box-sizing:border-box;font-family:system-ui}body{margin:0;min-height:100vh;background:#0a0e2a;display:flex;align-items:center;justify-content:center;color:#fff}
.card{background:#1e2433;padding:24px;border-radius:20px;width:92%;max-width:360px}
input{width:100%;padding:12px;margin:8px 0;background:#0f1424;border:1px solid #ffffff20;color:#fff;border-radius:10px}
.btn{width:100%;padding:12px;border:0;border-radius:10px;background:#ffbe4d;color:#111;font-weight:900;cursor:pointer}
</style></head><body>
<div class=card><form id=f><input name=userin placeholder='رقم / يوزر' required><input name=password type=password placeholder='كلمة السر' required><button class=btn>دخول فوري</button></form></div>
<script>
document.getElementById('f').addEventListener('submit',async e=>{
 e.preventDefault();
 let r=await fetch('/api/login_public',{method:'POST',body:new FormData(e.target)});
 let j=await r.json();
 if(j.ok) location.replace('/dash?v=home'); else alert('خطأ');
});
</script></body></html>"""
@app.route('/logout')
def lo(): session.clear(); return redirect('/login')
@app.route('/api/logout',methods=['POST'])
def lo2(): session.clear(); return jsonify(ok=True)
@app.route('/dash')
@login_required
def dash(): v=request.args.get('v','home').split('&')[0]; return layout(page_content(v),v)
@app.route('/api/page')
@login_required
def ap(): v=request.args.get('v','home').split('&')[0]; return page_content(v)
@app.route('/api/search')
@login_required
def sr():
    q=request.args.get('q','').strip();
    if not q: return jsonify([])
    like="%"+q+"%"; rs=[]
    for r in qall("SELECT * FROM dish_ips WHERE ip LIKE? OR dish_name LIKE? LIMIT 10",(like,like)): rs.append({"title":r.get('dish_name'),"sub":r.get('ip'),"page":"dishes"})
    return jsonify(rs)
@app.route('/add_dish',methods=['POST'])
@login_required
def ad():
    ip=request.form.get('ip','').strip(); name=request.form.get('dish_name','').strip(); loc=request.form.get('location','').strip()
    if not is_valid_ip(ip): return "IP خطأ",400
    if qone("SELECT * FROM dish_ips WHERE ip=?",(ip,)): qexec("UPDATE dish_ips SET dish_name=?,location=? WHERE ip=?",(name,loc,ip))
    else: qexec("INSERT INTO dish_ips(ip,location,dish_name) VALUES(?,?,?)",(ip,loc,name))
    return "ok"
@app.route('/del_dish/<int:i>')
@login_required
def dd(i): qexec("DELETE FROM dish_ips WHERE id=?",(i,)); return "ok"
@app.route('/edit_dish/<int:i>',methods=['POST'])
@login_required
def ed(i): qexec("UPDATE dish_ips SET dish_name=?,ip=?,location=? WHERE id=?",(request.form.get('dish_name',''),request.form.get('ip',''),request.form.get('location',''),i)); return "ok"
@app.route('/add_tower',methods=['POST'])
@login_required
def at(): qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",(request.form.get('name',''),request.form.get('area',''),float(request.form.get('lat') or 35),float(request.form.get('lng') or 36))); return "ok"
@app.route('/del_tower/<int:i>')
@login_required
def dt(i): qexec("DELETE FROM towers WHERE id=?",(i,)); return "ok"
@app.route('/edit_tower/<int:i>',methods=['POST'])
@login_required
def et(i): qexec("UPDATE towers SET name=?,area=?,lat=?,lng=? WHERE id=?",(request.form.get('name',''),request.form.get('area',''),float(request.form.get('lat') or 35),float(request.form.get('lng') or 36),i)); return "ok"
@app.route('/add_sub',methods=['POST'])
@login_required
def asu(): qexec("INSERT INTO subs(name,phone,note) VALUES(?,?,?)",(request.form.get('name',''),request.form.get('phone',''),'')); return "ok"
@app.route('/del_sub/<int:i>')
@login_required
def ds(i): qexec("DELETE FROM subs WHERE id=?",(i,)); return "ok"
@app.route('/edit_sub/<int:i>',methods=['POST'])
@login_required
def es(i): qexec("UPDATE subs SET name=?,phone=? WHERE id=?",(request.form.get('name',''),request.form.get('phone',''),i)); return "ok"
@app.route('/add_ledger',methods=['POST'])
@login_required
def al(): qexec("INSERT INTO ledger(name,amount) VALUES(?,?)",(request.form.get('name',''),float(request.form.get('amount') or 0))); return "ok"
@app.route('/del_ledger/<int:i>')
@login_required
def dl(i): qexec("DELETE FROM ledger WHERE id=?",(i,)); return "ok"
@app.route('/add_user',methods=['POST'])
@login_required
def au():
    ph=request.form.get('user_field','').strip()
    if not ph: return "خطأ",400
    if qone("SELECT * FROM users WHERE phone=?",(ph,)): return "موجود",400
    qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",(ph,generate_password_hash(request.form.get('password','1234')),request.form.get('role','tech'),ph)); return "ok"
@app.route('/del_user/<ph>')
@login_required
def du(ph): qexec("DELETE FROM users WHERE phone=?",(ph,)); return "ok"
@app.route('/edit_user',methods=['POST'])
@login_required
def eu():
    old=request.form.get('old_phone','').strip(); new=request.form.get('phone','').strip()
    qexec("UPDATE users SET phone=?,username=? WHERE phone=?",(new,new,old))
    if session.get('phone')==old: session['phone']=new
    return "ok"

def page_content(v):
    if v=='home': return "<div class=card><h3>🏠 الرئيسية نار 🔥</h3>النظام شغال 100%</div>"
    if v=='dishes':
        rs=qall("SELECT * FROM dish_ips ORDER BY id DESC LIMIT 100")
        rows="".join([f'<div class="card" id="dish-{r["id"]}" data-name="{esc(r.get("dish_name") or "")}" data-ip="{esc(r.get("ip") or "")}" data-loc="{esc(r.get("location") or "")}"><b>{esc(r.get("dish_name") or "")}</b> - <a href="http://{esc(r.get("ip") or "")}" target="_blank" style="color:#ffbe4d">{esc(r.get("ip") or "")}</a> <button class=btn onclick="window.editDish({r["id"]})">✏</button> <button class=btn onclick="fetch(\'/del_dish/{r["id"]}\').then(()=>loadPage(\'dishes\',true))">🗑</button></div>' for r in rs])
        return f'''<div class=card><h3>📡 الصحون</h3><form data-ajax method=post action=/add_dish><input name=dish_name placeholder='اسم' required><input name=ip placeholder='IP' required><input name=location placeholder='موقع'><button class=btn>➕ فوري</button></form></div>{rows}<script>
        window.editDish=function(id){{let c=document.getElementById('dish-'+id); let n=prompt('اسم',c.dataset.name); let ip=prompt('IP',c.dataset.ip); if(n!=null) fetch('/edit_dish/'+id,{{method:'POST',body:new URLSearchParams({{dish_name:n,ip:ip,location:c.dataset.loc}})}}).then(()=>loadPage('dishes',true));}}
        </script>'''
    if v=='towers': return "<div class=card>🗼 الأبراج شغالة</div>"
    if v=='subs': return "<div class=card>👥 المشتركين شغال</div>"
    if v=='ledger': return "<div class=card>📒 الحسابات</div>"
    if v=='logs':
        rs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 100")
        return "<div class=card><h3>📜 السجل</h3>"+"".join([f"<div>{esc(r.get('user_phone',''))} {esc(r.get('action',''))} {esc(r.get('time',''))}</div>" for r in rs])+"</div>"
    if v=='map': return "<div class=card>🗺 الخريطة</div>"
    if v=='support': return """<div class=card><a href='https://wa.me/905345851045' target=_blank style='display:block;background:#22c55e;color:#fff;padding:12px;text-align:center;border-radius:10px;text-decoration:none'>واتساب +90 534 485 10 45</a></div>"""
    if v=='settings': return "<div class=card><button onclick='fetch(\"/toggle_lang\").then(()=>location.reload())'>🌐 لغة</button> <button onclick='fetch(\"/toggle_theme\").then(()=>location.reload())'>🌓 ليل/نهار</button></div>"
    return "<div class=card>ok</div>"

def layout(c,v='home'):
    return f"""<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<style>*{{box-sizing:border-box;font-family:system-ui}}body{{margin:0;background:#0a0e2a;color:#fff}}
.top{{position:fixed;top:0;left:0;right:0;height:56px;background:#0f172a;display:flex;justify-content:space-between;align-items:center;padding:0 12px;z-index:1000}}
.sidebar{{position:fixed;right:0;top:0;width:260px;height:100%;background:#0f172a;z-index:1001;padding-top:60px;transform:translateX(110%);transition:transform 0.45s cubic-bezier(0.4,0,0.2,1)}}
.sidebar.active{{transform:none}}
.sidebar a{{display:block;padding:10px 14px;margin:5px 10px;color:#cbd5e1;text-decoration:none;border-radius:10px;background:#ffffff06}}
.main{{margin-top:60px;padding:10px}}
.card{{background:#1e2433;padding:12px;border-radius:12px;margin-bottom:8px}}
.btn{{background:#ffbe4d;border:0;padding:6px 10px;border-radius:8px;cursor:pointer}}
#overlay{{position:fixed;inset:0;background:#0008;display:none;z-index:999}}#overlay.show{{display:block}}
#editModal{{position:fixed;inset:0;background:#0008;display:none;align-items:center;justify-content:center;z-index:2000}}#editModal.show{{display:flex}}
</style></head><body>
<div id=overlay onclick="toggleSb(false)"></div>
<div class=sidebar id=sb><a href="javascript:loadPage('home')">🏠 الرئيسية</a><a href="javascript:loadPage('dishes')">📡 الصحون</a><a href="javascript:loadPage('logs')">📜 السجل</a><a href="javascript:loadPage('settings')">⚙ الإعدادات</a><a href="javascript:loadPage('support')">🛠 الدعم</a><a href="javascript:logoutFast()">🚪 خروج</a></div>
<div class=top><span onclick="toggleSb()" style='cursor:pointer;font-size:22px'>☰</span><span>OMAIA ISP</span><div><button onclick="fetch('/toggle_theme').then(()=>location.reload())">🌓</button></div></div>
<div class=main id=mn>{c}</div>
<div id=editModal><div style='background:#1e2433;padding:16px;border-radius:12px;width:90%;max-width:360px'><div id=editBody></div><button onclick="document.getElementById('editModal').classList.remove('show')">إغلاق</button></div></div>
<script>
let cur='{v}';
function toggleSb(f){{let sb=document.getElementById('sb'),ov=document.getElementById('overlay'); let o=f!==undefined?f:!sb.classList.contains('active'); sb.classList.toggle('active',o); ov.classList.toggle('show',o);}}
async function loadPage(v,force=false){{cur=v; toggleSb(false); let mn=document.getElementById('mn'); try{{let r=await fetch('/api/page?v='+v); let h=await r.text(); mn.innerHTML=h; bind(); execScripts();}}catch(e){{mn.innerHTML='❌ '+e;}}}}
function execScripts(){{document.getElementById('mn').querySelectorAll('script').forEach(s=>{{try{{(0,eval)(s.textContent);}}catch(e){{}}}});}}
function bind(){{document.querySelectorAll('form[data-ajax]').forEach(f=>{{if(f.dataset.bound) return; f.dataset.bound='1'; f.onsubmit=async e=>{{e.preventDefault(); let r=await fetch(f.action,{{method:'POST',body:new FormData(f)}}); if(r.ok){{f.reset(); loadPage(cur,true);}} else alert(await r.text());}}}});}}
window.closeEditModal=function(){{document.getElementById('editModal').classList.remove('show');}}
window.logoutFast=async function(){{await fetch('/api/logout',{{method:'POST'}}); location.replace('/login');}}
bind(); execScripts();
</script></body></html>"""

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)),threaded=True)
