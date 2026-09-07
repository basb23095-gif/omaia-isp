from flask import Flask, request, redirect, session, jsonify, Response
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, html, ipaddress, subprocess, json, socket, platform, io, csv
try:
    import psycopg2, psycopg2.extras
except:
    psycopg2 = None
import sqlite3

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY","omia-sec-2026-CHANGE-ME")
DATABASE_URL = os.environ.get("DATABASE_URL","").strip().replace("postgresql://","postgres://")
USE_PG = bool(DATABASE_URL.startswith("postgres://") and psycopg2)
_pg = None

def esc(s): return html.escape(str(s or ''), quote=True)

def db():
    global _pg
    if USE_PG:
        try:
            if _pg:
                try:
                    c=_pg.cursor();c.execute("SELECT 1");c.close();return _pg
                except:
                    try:_pg.close()
                    except:pass
                    _pg=None
        except: _pg=None
        try:
            _pg=psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=10)
            _pg.autocommit=True
            return _pg
        except: pass
    try:
        c=sqlite3.connect("omia.db",check_same_thread=False)
        c.row_factory=sqlite3.Row
        return c
    except:
        c=sqlite3.connect(":memory:",check_same_thread=False)
        c.row_factory=sqlite3.Row
        return c

def cc(c):
    if not USE_PG:
        try:c.close()
        except:pass

def qall(q,a=()):
    c=db()
    try:
        if USE_PG:
            cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(q.replace("?","%s"),a)
            rs=[dict(r) for r in cur.fetchall()]
            cur.close()
            return rs
        else:
            rs=[dict(r) for r in c.execute(q,a).fetchall()]
            cc(c)
            return rs
    except:
        cc(c)
        return []

def qone(q,a=()):
    r=qall(q,a)
    return r[0] if r else None

def qexec(q,a=()):
    c=db()
    try:
        if USE_PG:
            cur=c.cursor()
            cur.execute(q.replace("?","%s"),a)
            cur.close()
        else:
            c.execute(q,a)
            c.commit()
            cc(c)
    except:
        cc(c)

def init():
    ss=[
    "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,username TEXT)",
    "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,note TEXT)",
    "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,amount REAL,note TEXT,currency TEXT)",
    "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,dish_name TEXT)",
    "CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,area TEXT,lat REAL,lng REAL)"
    ]
    if USE_PG:
        ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
    for s in ss:
        qexec(s)
    if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",('05344851045',generate_password_hash('admin2024'),'manager','admin'))
    if not qone("SELECT * FROM towers WHERE name=?",('نقطة حماة الرئيسية',)):
        qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",('نقطة حماة الرئيسية','حماة',35.1318,36.7578))

init()

def login_required(f):
    @wraps(f)
    def w(*a,**kw):
        if not session.get('phone'):
            return redirect('/login')
        return f(*a,**kw)
    return w

def is_valid_ip(ip):
    ip=ip.strip()
    if not ip: return False
    try:
        ipaddress.ip_address(ip)
        return True
    except:
        return len(ip)>=7 and '.' in ip

@app.route('/api/ping')
@login_required
def api_ping():
    ip=request.args.get('ip','').strip()
    if not ip: return jsonify(ok=False,out='لا يوجد IP')
    try:
        cmd=['ping','-c','1','-W','2',ip] if platform.system().lower()!='windows' else ['ping','-n','1','-w','2000',ip]
        out=subprocess.check_output(cmd,timeout=4).decode(errors='ignore')
        ok='ttl=' in out.lower() or 'bytes from' in out.lower()
        return jsonify(ok=ok,out=('متصل ' if ok else 'لا يرد ')+out[:400])
    except Exception as e:
        return jsonify(ok=False,out=f'لا يرد {e}')

@app.route('/api/login_public',methods=['POST'])
def api_login_public():
    uin=request.form.get('userin','').strip()
    pw=request.form.get('password','')
    u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
    if u and check_password_hash(u['password'],pw):
        session['phone']=u['phone']
        session['username']=u.get('username') or u['phone']
        return jsonify(ok=True)
    return jsonify(ok=False,msg='خطأ بالدخول'),401

@app.route('/api/export/<tbl>')
@login_required
def api_export(tbl):
    output=io.StringIO()
    w=csv.writer(output)
    if tbl=='dishes':
        rows=qall("SELECT * FROM dish_ips ORDER BY id DESC")
        w.writerow(['ID','Dish','IP','Location'])
        for r in rows: w.writerow([r['id'],r.get('dish_name',''),r.get('ip',''),r.get('location','')])
        fname='dishes.csv'
    elif tbl=='subs':
        rows=qall("SELECT * FROM subs ORDER BY id DESC")
        w.writerow(['ID','Name','Phone','Note'])
        for r in rows: w.writerow([r['id'],r.get('name',''),r.get('phone',''),r.get('note','')])
        fname='subs.csv'
    else:
        rows=qall("SELECT phone,username,role FROM users ORDER BY phone DESC")
        w.writerow(['phone/user','role'])
        for r in rows: w.writerow([r.get('phone',''),r.get('role','')])
        fname='users.csv'
    return Response(output.getvalue(),mimetype='text/csv; charset=utf-8',headers={'Content-Disposition': f'attachment; filename={fname}'})

@app.route('/')
def ix():
    return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        uin=request.form.get('userin','').strip()
        pw=request.form.get('password','')
        u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
        if u and check_password_hash(u['password'],pw):
            session['phone']=u['phone']
            session['username']=u.get('username') or u['phone']
            return redirect('/dash')
        return "<script>alert('خطأ بالدخول');location.href='/login'</script>"
    return '''<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><style>body{margin:0;min-height:100vh;background:#0a0e2a;display:flex;flex-direction:column;align-items:center;justify-content:center;color:#fff;font-family:system-ui}.card{background:#1e2433cc;border:1px solid #ffffff15;padding:25px;border-radius:20px;width:92%;max-width:360px;box-shadow:0 20px 60px #0008}input{width:100%;padding:14px;margin:8px 0;background:#0f1424;border:1px solid #ffffff20;color:#fff;border-radius:12px}.btn{width:100%;padding:14px;border:0;border-radius:12px;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:900;font-size:16px;cursor:pointer;margin-top:10px}#loader{position:fixed;inset:0;background:#0a0e2a;z-index:9999;display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:opacity .3s}#loader.show{opacity:1;pointer-events:auto}.spinner{width:40px;height:40px;border:3px solid #ffffff20;border-top-color:#ffbe4d;border-radius:50%;animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}</style></head><body><div id=loader><div class=spinner></div></div><div style=font-size:28px;font-weight:900;margin-bottom:12px>OMAIA <span style=color:#ffbe4d>ISP</span></div><div class=card><form id=loginForm><input name=userin id=userin placeholder="phone / uesr" required><input name=password id=password type=password placeholder="password" required><button class=btn id=loginBtn>login</button><div id=msg style=text-align:center;margin-top:8px;color:#ef4444;font-size:13px></div></form></div><script>document.getElementById('loginForm').addEventListener('submit',async e=>{e.preventDefault();let btn=document.getElementById('loginBtn'),msg=document.getElementById('msg'),loader=document.getElementById('loader');btn.textContent='wait...';btn.disabled=true;loader.classList.add('show');try{let fd=new FormData(e.target);let r=await fetch('/api/login_public',{method:'POST',body:fd});let j=await r.json();if(j.ok){location.href='/dash?v=home';}else{msg.textContent=j.msg||'error';btn.textContent='login';btn.disabled=false;loader.classList.remove('show');}}catch(err){msg.textContent='network error';btn.textContent='login';btn.disabled=false;loader.classList.remove('show');}});</script></body></html>'''

@app.route('/logout')
def lo():
    session.clear()
    return redirect('/login')

@app.route('/dash')
@login_required
def dash():
    v=request.args.get('v','home')
    return layout(page_content(v),v)

@app.route('/api/page')
@login_required
def ap():
    return page_content(request.args.get('v','home'))

@app.route('/api/search')
@login_required
def s():
    q=request.args.get('q','').strip()
    if q:
        return jsonify(qall("SELECT * FROM dish_ips WHERE ip LIKE ? OR dish_name LIKE ? OR location LIKE ? ORDER BY id DESC LIMIT 100",("%"+q+"%","%"+q+"%","%"+q+"%")))
    return jsonify(qall("SELECT * FROM dish_ips ORDER BY id DESC LIMIT 100"))

@app.route('/toggle_theme')
@login_required
def tt():
    cur=session.get('theme','dark')
    session['theme']='light' if cur=='dark' else 'dark'
    return jsonify(ok=True)

@app.route('/add_dish',methods=['POST'])
@login_required
def ad():
    ip=request.form.get('ip','').strip()
    name=request.form.get('dish_name','').strip()
    loc=request.form.get('location','').strip()
    if not ip: return "IP required",400
    if not is_valid_ip(ip): return "Invalid IP",400
    ex=qone("SELECT * FROM dish_ips WHERE ip=?",(ip,))
    if ex:
        qexec("UPDATE dish_ips SET dish_name=?,location=? WHERE ip=?",(name,loc,ip))
        return "ok updated"
    qexec("INSERT INTO dish_ips(ip,location,dish_name) VALUES(?,?,?)",(ip,loc,name))
    return "ok"

@app.route('/edit_dish/<int:i>',methods=['POST'])
@login_required
def ed(i):
    qexec("UPDATE dish_ips SET dish_name=?,ip=?,location=? WHERE id=?",(request.form.get('dish_name',''),request.form.get('ip',''),request.form.get('location',''),i))
    return "ok"

@app.route('/del_dish/<int:i>')
@login_required
def dd(i):
    qexec("DELETE FROM dish_ips WHERE id=?",(i,))
    return "ok"

@app.route('/add_tower',methods=['POST'])
@login_required
def at():
    qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",(request.form.get('name',''),request.form.get('area',''),35.1312,36.7578))
    return "ok"

@app.route('/del_tower/<int:i>')
@login_required
def dt(i):
    qexec("DELETE FROM towers WHERE id=?",(i,))
    return "ok"

@app.route('/edit_tower/<int:i>',methods=['POST'])
@login_required
def et(i):
    qexec("UPDATE towers SET name=?,area=? WHERE id=?",(request.form.get('name',''),request.form.get('area',''),i))
    return "ok"

@app.route('/add_sub',methods=['POST'])
@login_required
def asub():
    qexec("INSERT INTO subs(name,phone,note) VALUES(?,?,?)",(request.form.get('name',''),request.form.get('phone',''),request.form.get('note','')))
    return "ok"

@app.route('/del_sub/<int:i>')
@login_required
def dsub(i):
    qexec("DELETE FROM subs WHERE id=?",(i,))
    return "ok"

@app.route('/edit_sub/<int:i>',methods=['POST'])
@login_required
def esub(i):
    qexec("UPDATE subs SET name=?,phone=?,note=? WHERE id=?",(request.form.get('name',''),request.form.get('phone',''),request.form.get('note',''),i))
    return "ok"

@app.route('/add_ledger',methods=['POST'])
@login_required
def al():
    try: amt=float(request.form.get('amount') or 0)
    except: amt=0
    qexec("INSERT INTO ledger(name,amount,note,currency) VALUES(?,?,?,?)",(request.form.get('name',''),amt,request.form.get('note',''),request.form.get('currency','USD')))
    return "ok"

@app.route('/del_ledger/<int:i>')
@login_required
def dll(i):
    qexec("DELETE FROM ledger WHERE id=?",(i,))
    return "ok"

@app.route('/edit_ledger/<int:i>',methods=['POST'])
@login_required
def el(i):
    try: amt=float(request.form.get('amount') or 0)
    except: amt=0
    qexec("UPDATE ledger SET name=?,amount=?,note=?,currency=? WHERE id=?",(request.form.get('name',''),amt,request.form.get('note',''),request.form.get('currency','USD'),i))
    return "ok"

@app.route('/add_user',methods=['POST'])
@login_required
def au():
    ph=request.form.get('phone','').strip() or request.form.get('user_field','').strip() or request.form.get('username','').strip()
    if not ph: return "required",400
    if qone("SELECT * FROM users WHERE phone=?",(ph,)): return "exists",400
    qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",(ph,generate_password_hash(request.form.get('password','1234')),request.form.get('role','tech'),ph))
    return "ok"

@app.route('/edit_user',methods=['POST'])
@login_required
def eu():
    old=request.form.get('old_phone','').strip()
    new_ph=request.form.get('phone','').strip() or request.form.get('user_field','').strip() or request.form.get('username','').strip()
    new_role=request.form.get('role','tech')
    new_pass=request.form.get('password','').strip()
    if not old or not new_ph: return "error",400
    if new_pass:
        qexec("UPDATE users SET phone=?,username=?,role=?,password=? WHERE phone=?",(new_ph,new_ph,new_role,generate_password_hash(new_pass),old))
    else:
        qexec("UPDATE users SET phone=?,username=?,role=? WHERE phone=?",(new_ph,new_ph,new_role,old))
    if session.get('phone')==old: session['phone']=new_ph
    return "ok"

@app.route('/del_user/<ph>')
@login_required
def du(ph):
    if ph=='05344851045': return "cannot delete admin",400
    qexec("DELETE FROM users WHERE phone=?",(ph,))
    return "ok"

@app.route('/change_pass',methods=['POST'])
@login_required
def cp():
    np=request.form.get('newpass','').strip()
    if not np: return "empty",400
    qexec("UPDATE users SET password=? WHERE phone=?",(generate_password_hash(np),session.get('phone')))
    return "ok"

def page_content(v):
    if v=='home':
        ns=(qone("SELECT COUNT(*) c FROM subs") or {}).get('c',0)
        nd=(qone("SELECT COUNT(*) c FROM dish_ips") or {}).get('c',0)
        nt=(qone("SELECT COUNT(*) c FROM towers") or {}).get('c',0)
        nl=(qone("SELECT COUNT(*) c FROM ledger") or {}).get('c',0)
        return f"<div style='max-width:700px;margin:0 auto;text-align:center'><div style='display:grid;grid-template-columns:1fr 1fr;gap:12px'><div class='card anim' onclick=\"loadPage('subs')\" style='cursor:pointer'><h3>subs</h3><h2>{ns}</h2></div><div class='card anim' onclick=\"loadPage('dishes')\" style='cursor:pointer'><h3>dishes</h3><h2>{nd}</h2></div><div class='card anim' onclick=\"loadPage('towers')\" style='cursor:pointer'><h3>towers</h3><h2>{nt}</h2></div><div class='card anim' onclick=\"loadPage('ledger')\" style='cursor:pointer'><h3>ledger</h3><h2>{nl}</h2></div></div><div style='margin-top:16px;display:flex;gap:8px;justify-content:center;flex-wrap:wrap'><a href='/api/export/dishes' class=btn-gold style='text-decoration:none'>Excel dishes</a><a href='/api/export/users' class=btn-gold style='text-decoration:none'>Excel users</a><button onclick=\"window.print()\" class=btn-gold>PDF</button></div></div>"
    if v=='dishes':
        return """<div style='max-width:900px;margin:0 auto'><div class=card><h3>Dishes</h3><form data-ajax method=post action=/add_dish style='display:flex;gap:5px;flex-wrap:wrap;margin-top:8px'><input name=dish_name placeholder='dish name' required style='flex:1'><input name=ip placeholder='IP' required style='flex:1'><input name=location placeholder='location' style='flex:1'><button class=btn-gold>add</button></form><input id=searchBox placeholder='search' oninput="window.searchDishes(this.value)" style='margin-top:8px'></div><div id=dl></div></div><script>window.doEditDish=function(id){let c=document.getElementById('dish-'+id);let nn=prompt('name',c.dataset.name);let ii=prompt('IP',c.dataset.ip);let ll=prompt('loc',c.dataset.loc);fetch('/edit_dish/'+id,{method:'POST',body:new URLSearchParams({dish_name:nn,ip:ii,location:ll})}).then(()=>window.ld());};window.doPing=function(id){let c=document.getElementById('dish-'+id);fetch('/api/ping?ip='+encodeURIComponent(c.dataset.ip)).then(r=>r.json()).then(j=>{alert(j.out);});};window.ld=async function(q){let r=await fetch('/api/search?q='+encodeURIComponent(q||''));let d=await r.json();let h='';d.forEach(x=>{h+='<div class="card" id="dish-'+x.id+'" data-name="'+x.dish_name+'" data-ip="'+x.ip+'" data-loc="'+x.location+'"><div><b>'+x.dish_name+'</b><br><a href="http://'+x.ip+'" target="_blank" style="color:#ffbe4d">'+x.ip+' ↗ Chrome</a></div><div><button class=btn-gold onclick="window.doPing('+x.id+')">Ping</button><button class=btn-gold onclick="window.doEditDish('+x.id+')">edit</button><button class=btn-del onclick="askDel(\'/del_dish/'+x.id+'\')">del</button></div></div>';});document.getElementById('dl').innerHTML=h;};window.ld();window.searchDishes=window.ld;</script>"""
    if v=='towers':
        rs=qall("SELECT * FROM towers ORDER BY id DESC")
        rows=""
        for r in rs:
            sn=esc(r['name']); sa=esc(r['area'] or '')
            rows+=f"<div class='card' id='tower-{r['id']}' data-name='{sn}' data-area='{sa}'><b>{sn}</b> {sa} <button class=btn-del onclick=\"askDel('/del_tower/{r['id']}')\">del</button></div>"
        return f"""<div style='max-width:700px;margin:0 auto'><div class=card><h3>Towers</h3><form data-ajax method=post action=/add_tower style='display:flex;gap:6px'><input name=name placeholder='tower' required style='flex:1'><input name=area placeholder='area' style='flex:1'><button class=btn-gold>add</button></form></div>{rows}</div>"""
    if v=='subs':
        rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 200")
        rows=""
        for r in rs:
            rows+=f"<div class='card'><b>{esc(r['name'])}</b> {esc(r['phone'] or '')} <button class=btn-del onclick=\"askDel('/del_sub/{r['id']}')\">del</button></div>"
        return f"""<div style='max-width:700px;margin:0 auto'><div class=card><h3>Subs</h3><form data-ajax method=post action=/add_sub style='display:flex;gap:5px'><input name=name placeholder='name' required style='flex:1'><input name=phone placeholder='phone' style='flex:1'><button class=btn-gold>add</button></form></div>{rows}</div>"""
    if v=='ledger':
        rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 200")
        rows=""
        for r in rs:
            rows+=f"<div class='card'>{esc(r['name'])} - {r['amount']} <button class=btn-del onclick=\"askDel('/del_ledger/{r['id']}')\">del</button></div>"
        return f"<div style='max-width:700px;margin:0 auto'><div class=card><h3>Ledger</h3><form data-ajax method=post action=/add_ledger style='display:flex;gap:5px'><input name=name placeholder='name' required style='flex:1'><input name=amount type=number step=0.01 placeholder='amount' required style='flex:1'><button class=btn-gold>add</button></form></div>{rows}</div>"
    if v=='map':
        return "<div class=card><div id=map style='height:70vh'></div></div><script>setTimeout(()=>{let map=L.map('map').setView([35.13,36.75],12);L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);},200);</script>"
    if v=='support':
        return "<div class=card style='text-align:center'><h2>Support</h2><a href='https://wa.me/905344851045' style='background:#22c55e;color:#fff;padding:12px 20px;border-radius:10px;text-decoration:none'>whatsapp</a></div>"
    if v=='settings':
        us=qall("SELECT * FROM users ORDER BY phone DESC")
        uh=""
        for u in us:
            ph=esc(u['phone']); ro=esc(u['role'])
            uh+=f"<div class='card' id='user-{ph}' data-phone='{ph}' data-role='{ro}' style='display:flex;justify-content:space-between'><div><b>phone / uesr</b><br><span style='color:#ffbe4d'>{ph}</span><br><small>{ro}</small></div><div><button class=btn-gold onclick=\"window.openEditUser('{ph}')\">edit</button> <button class=btn-del onclick=\"askDel('/del_user/{ph}')\">del</button></div></div>"
        return f"""<div style='max-width:700px;margin:0 auto'><div class=card><h3>My password</h3><form data-ajax method=post action=/change_pass style='display:flex;gap:6px'><input name=newpass type=password placeholder='new password' required style='flex:1'><button class=btn-gold>save</button></form></div><div class=card style='border:1px solid #ffbe4d30'><h4 style='text-align:center'>add uesr</h4><form data-ajax method=post action=/add_user style='display:flex;flex-direction:column;gap:10px'><input name=user_field placeholder='phone / uesr' required style='padding:14px;background:#0f1424;border:1px solid #ffffff20;border-radius:12px;color:#fff'><input name=password type=password placeholder='🔑 password' required style='padding:14px;background:#0f1424;border:1px solid #ffffff20;border-radius:12px;color:#fff'><select name=role style='padding:12px;background:#0f1424;border:1px solid #ffffff20;border-radius:12px;color:#fff'><option value=tech>فني</option><option value=manager>مدير</option></select><button class=btn-gold style='padding:14px'>add uesr</button></form></div>{uh}<script>window.openEditUser=function(ph){{let c=document.getElementById('user-'+ph);document.getElementById('editModal').classList.add('show');document.getElementById('editTitle').textContent='edit user';document.getElementById('editBody').innerHTML='<input id=edit_u_field value="'+ph+'" placeholder="phone / uesr" style="width:100%;padding:14px;border-radius:12px;background:#0f1424;border:1px solid #ffffff20;color:#fff"><input id=edit_u_pass type="password" placeholder="🔑 password" style="width:100%;padding:14px;border-radius:12px;margin-top:10px;background:#0f1424;border:1px solid #ffffff20;color:#fff"><button onclick="window.saveUser(\''+ph+'\')" class=btn-gold style="width:100%;padding:14px;margin-top:12px">save</button>';}};window.saveUser=function(oldPh){{let ff=document.getElementById('edit_u_field').value.trim();let pw=document.getElementById('edit_u_pass').value;if(!ff){{alert('required');return;}}let data={{old_phone:oldPh,phone:ff,username:ff,role:document.getElementById('user-'+oldPh).dataset.role}};if(pw.trim()!='') data.password=pw.trim();fetch('/edit_user',{{method:'POST',body:new URLSearchParams(data)}}).then(()=>{{closeEditModal(); loadPage('settings',true);}});}};</script></div>"""
    return "<div class=card>ok</div>"

def layout(c,v='home'):
    bg='#0a0e2a'; card_bg='#1e2433'; txt='#ffffff'; border='#ffffff15'
    return f"""<html dir=rtl lang=ar><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><link rel=stylesheet href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'><style>*{{box-sizing:border-box;font-family:system-ui}}body{{margin:0;background:{bg};color:{txt};overflow-x:hidden}}.top{{position:fixed;top:0;left:0;right:0;height:60px;background:#111827ee;display:flex;align-items:center;justify-content:space-between;padding:0 12px;z-index:1003}}.sidebar{{position:fixed;right:0;top:0;width:270px;height:100%;background:#111827f5;z-index:1002;padding-top:70px;transform:translateX(110%);transition:transform .26s;overflow-y:auto}}.sidebar.active{{transform:none}}.sidebar a{{display:flex;padding:12px 16px;margin:6px 12px;color:#fff;text-decoration:none;border-radius:12px;background:#ffffff10}}.sidebar a.active{{background:#ffbe4d;color:#111;font-weight:800}}#overlay{{position:fixed;inset:0;background:#0008;z-index:1001;display:none}}#overlay.show{{display:block}}.main{{margin-top:70px;padding:12px}}.card{{background:{card_bg};color:{txt};padding:14px;border-radius:14px;margin-bottom:10px;border:1px solid {border}}}.btn-gold{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;padding:10px 16px;border:0;border-radius:10px;font-weight:800;cursor:pointer}}.btn-del{{background:#ef4444;color:#fff;padding:9px 14px;border:0;border-radius:10px;cursor:pointer}}#delModal,#editModal{{position:fixed;inset:0;background:#0009;display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:.25s;z-index:2000}}#delModal.show,#editModal.show{{opacity:1;pointer-events:auto}}#delBox,#editBox{{background:{card_bg};padding:24px;border-radius:18px;width:92%;max-width:440px;transform:scale(.92);transition:.28s}}#delModal.show #delBox,#editModal.show #editBox{{transform:scale(1)}}</style></head><body><div id=overlay onclick="toggleSb(false)"></div><div class=sidebar id=sb><a href="javascript:loadPage('home')" id=nav-home>Home</a><a href="javascript:loadPage('dishes')" id=nav-dishes>Dishes</a><a href="javascript:loadPage('towers')" id=nav-towers>Towers</a><a href="javascript:loadPage('subs')" id=nav-subs>Subs</a><a href="javascript:loadPage('ledger')" id=nav-ledger>Ledger</a><a href="javascript:loadPage('map')" id=nav-map>Map</a><a href="javascript:loadPage('support')" id=nav-support>Support</a><a href="javascript:loadPage('settings')" id=nav-settings>Settings</a><a href=/logout>Logout</a></div><div class=top><div style='display:flex;gap:8px'><span onclick="toggleSb()" style='font-size:24px;cursor:pointer'>☰</span></div><div style='font-weight:900'>OMAIA <span style='color:#ffbe4d'>ISP</span></div><div style='display:flex;gap:6px'><button onclick="toggleLang()" id=langBtn style='background:#1f2937;color:#fff;border:0;padding:8px 10px;border-radius:10px'>🌐</button><button onclick="loadPage(cur,true)" style='background:#1f2937;color:#fff;border:0;padding:8px 10px;border-radius:10px'>↻</button></div></div><div class=main id=mn>{c}</div><div id=delModal><div id=delBox><h3>Delete?</h3><div style='display:flex;gap:10px;margin-top:12px'><button onclick="closeDel()" style='flex:1;padding:12px'>Cancel</button><button id=delYes style='flex:1;padding:12px;background:#ef4444;color:#fff;border:0'>Delete</button></div></div></div><div id=editModal><div id=editBox><div style='display:flex;justify-content:space-between'><h3 id=editTitle>Edit</h3><button onclick="closeEditModal()">x</button></div><div id=editBody></div></div></div><script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script><script>let cur='{v}';let pageCache=JSON.parse(localStorage.getItem('omaia_cache')||'{{}}');let lang=localStorage.getItem('omaia_lang')||'en';function saveCache(){{try{{localStorage.setItem('omaia_cache',JSON.stringify(pageCache))}}catch(e){{}}}}function applyLang(){{document.getElementById('langBtn').textContent=lang==='ar'?'🌐 ع':'🌐 En';localStorage.setItem('omaia_lang',lang);}}window.toggleLang=function(){{lang=lang==='ar'?'en':'ar';applyLang();delete pageCache[cur];saveCache();loadPage(cur,true);}};applyLang();function toggleSb(force){{let sb=document.getElementById('sb'),ov=document.getElementById('overlay');let open=force!==undefined?force:!sb.classList.contains('active');sb.classList.toggle('active',open);ov.classList.toggle('show',open);}}async function loadPage(v,force=false){{cur=v;localStorage.setItem('omaia_last_page',v);toggleSb(false);document.querySelectorAll('.sidebar a').forEach(a=>a.classList.remove('active'));let nav=document.getElementById('nav-'+v);if(nav)nav.classList.add('active');let mn=document.getElementById('mn');if(pageCache[v] && !force){{mn.style.opacity='0.5';setTimeout(()=>{{mn.innerHTML=pageCache[v];mn.style.opacity='1';bind();execScripts();}},80);fetch('/api/page?v='+v).then(r=>r.text()).then(h=>{{pageCache[v]=h;saveCache();}});return;}}mn.style.opacity='0.6';try{{let r=await fetch('/api/page?v='+v,{{cache:'no-store'}});let h=await r.text();pageCache[v]=h;saveCache();mn.innerHTML=h;mn.style.opacity='1';bind();execScripts();}}catch(e){{mn.innerHTML='<div class=card>error</div>';mn.style.opacity='1';}}}}function execScripts(){{document.getElementById('mn').querySelectorAll('script').forEach(s=>{{try{{eval(s.textContent)}}catch(e){{}}}});}}function bind(){{document.querySelectorAll('form[data-ajax]').forEach(f=>{{f.onsubmit=async e=>{{e.preventDefault();let btn=f.querySelector('button');let old=btn?btn.textContent:'';if(btn){{btn.textContent='...';btn.disabled=true;}}try{{let r=await fetch(f.action,{{method:'POST',body:new FormData(f)}});if(r.ok){{delete pageCache[cur];await loadPage(cur,true);}}else{{alert(await r.text());}}}}catch(err){{alert(err);}}if(btn){{btn.textContent=old;btn.disabled=false;}}}});}}function askDel(u){{window._delUrl=u;document.getElementById('delModal').classList.add('show');}}function closeDel(){{document.getElementById('delModal').classList.remove('show');window._delUrl=null;}}window.closeEditModal=function(){{document.getElementById('editModal').classList.remove('show');}}document.getElementById('delYes').onclick=async()=>{{if(window._delUrl){{await fetch(window._delUrl);delete pageCache[cur];closeDel();loadPage(cur,true);}}}};bind();execScripts();</script></body></html>"""

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
