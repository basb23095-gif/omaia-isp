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
    c=sqlite3.connect("omia.db",check_same_thread=False)
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
            c.execute(q,a);c.commit();cc(c)
    except: cc(c)

def init():
    ss=[
    "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,username TEXT)",
    "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,note TEXT)",
    "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,amount REAL,note TEXT,currency TEXT)",
    "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,dish_name TEXT)",
    "CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,area TEXT,lat REAL,lng REAL)",
    "CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,user TEXT,action TEXT,at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    ]
    if USE_PG:
        ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
    for s in ss: qexec(s)
    if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",('05344851045',generate_password_hash('admin2024'),'manager','admin'))
    if not qone("SELECT * FROM towers WHERE name=?",('نقطة حماة الرئيسية',)):
        qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",('نقطة حماة الرئيسية','حماة',35.1318,36.7578))
init()

def login_required(f):
    @wraps(f)
    def w(*a,**kw):
        if not session.get('phone'): return redirect('/login')
        return f(*a,**kw)
    return w

def role_required(r='manager'):
    def dec(f):
        @wraps(f)
        def w(*a,**kw):
            u=qone("SELECT * FROM users WHERE phone=?",(session.get('phone'),))
            if not u: return redirect('/login')
            if r=='manager' and u.get('role')!='manager': return "ممنوع: للمدير فقط",403
            return f(*a,**kw)
        return w
    return dec

def add_log(action):
    try: qexec("INSERT INTO logs(user,action) VALUES(?,?)",(session.get('phone','?'),action))
    except: pass

def is_valid_ip(ip):
    ip=ip.strip()
    if not ip: return False
    try:
        ipaddress.ip_address(ip);return True
    except: return len(ip)>=7 and '.' in ip

@app.route('/health')
def health(): return "ok",200

@app.route('/api/ping')
@login_required
def api_ping():
    ip=request.args.get('ip','').strip()
    if not ip or not is_valid_ip(ip): return jsonify(ok=False,out='IP غير صالح')
    try:
        cmd=['ping','-c','1','-W','2',ip] if platform.system().lower()!='windows' else ['ping','-n','1','-w','2000',ip]
        out=subprocess.check_output(cmd,timeout=3,stderr=subprocess.STDOUT).decode(errors='ignore')
        ok='ttl=' in out.lower() or 'bytes from' in out.lower()
        if ok: return jsonify(ok=True,out='متصل')
    except: pass
    for port in [80,443,8080,8291,22,8728]:
        try:
            s=socket.socket();s.settimeout(1.2)
            if s.connect_ex((ip,port))==0: s.close();return jsonify(ok=True,out=f'متصل منفذ {port}')
            s.close()
        except: pass
    return jsonify(ok=False,out='لا يرد')

@app.route('/api/net_status')
@login_required
def net_status():
    rows=qall("SELECT ip,dish_name FROM dish_ips")
    res=[]
    for r in rows:
        ip=r['ip']
        try:
            out=subprocess.check_output(['ping','-c','1','-W','1',ip],timeout=2).decode(errors='ignore')
            ok='ttl=' in out.lower()
        except: ok=False
        res.append({"ip":ip,"name":r.get('dish_name',''),"ok":ok})
    return jsonify(res)

@app.route('/api/login_public',methods=['POST'])
def api_login_public():
    uin=request.form.get('userin','').strip()
    pw=request.form.get('password','')
    u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
    if u and check_password_hash(u['password'],pw):
        session['phone']=u['phone'];session['username']=u.get('username') or u['phone']
        add_log('تسجيل دخول')
        return jsonify(ok=True)
    return jsonify(ok=False,msg='خطأ بالدخول'),401

@app.route('/api/export/<tbl>')
@login_required
def api_export(tbl):
    output=io.StringIO();w=csv.writer(output)
    if tbl=='dishes':
        rows=qall("SELECT * FROM dish_ips ORDER BY id DESC")
        w.writerow(['ID','اسم','IP','موقع'])
        for r in rows: w.writerow([r['id'],r.get('dish_name',''),r.get('ip',''),r.get('location','')])
    elif tbl=='subs':
        rows=qall("SELECT * FROM subs ORDER BY id DESC")
        w.writerow(['ID','الاسم','رقم','ملاحظة'])
        for r in rows: w.writerow([r['id'],r.get('name',''),r.get('phone',''),r.get('note','')])
    else:
        rows=qall("SELECT phone,username,role FROM users")
        w.writerow(['رقم','يوزر','رتبة'])
        for r in rows: w.writerow([r.get('phone',''),r.get('username',''),r.get('role','')])
    return Response(output.getvalue(),mimetype='text/csv',headers={'Content-Disposition':f'attachment;filename={tbl}.csv'})

@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login',methods=['GET','POST'])
def login():
    return """<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<style>@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@800&display=swap');
body{margin:0;min-height:100vh;background:#0a0e2a;display:flex;flex-direction:column;align-items:center;justify-content:center;color:#fff;font-family:'Cairo',system-ui}
.card{background:#1e2433cc;border:1px solid #ffffff18;padding:25px;border-radius:20px;width:92%;max-width:360px;box-shadow:0 20px 60px #0008}
input{width:100%;padding:12px;margin:8px 0;background:#0f1424;border:1px solid #ffffff20;color:#fff;border-radius:12px;box-sizing:border-box}
.btn{width:100%;padding:13px;border:0;border-radius:12px;background:linear-gradient(90deg,#ffbe4d,#ffb020);font-weight:900;font-size:16px;cursor:pointer}
#loader{position:fixed;inset:0;background:#0a0e2a;z-index:9999;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:12px;opacity:0;pointer-events:none;transition:.3s}
#loader.show{opacity:1;pointer-events:auto}.spinner{width:45px;height:45px;border:3px solid #ffffff20;border-top-color:#ffbe4d;border-radius:50%;animation:spin.8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}</style></head><body>
<div id=loader><div class=spinner></div><div>جاري التحميل...</div></div>
<div style='font-size:28px;font-weight:900;margin-bottom:12px'>🛰️ OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<div class=card><form id=f><input name=userin id=u placeholder='📱 رقم / يوزر' required><input name=password id=p type=password placeholder='🔑 كلمة السر' required><button class=btn id=b>✨ دخول</button><div id=m style='color:#ef4444;text-align:center'></div></form>
<div style='text-align:center;margin-top:10px'><a href='https://wa.me/905344851045' style='color:#22c55e;text-decoration:none;font-weight:800'>💬 واتساب الدعم</a></div></div>
<script>
document.getElementById('f').addEventListener('submit',async e=>{e.preventDefault();let b=document.getElementById('b');b.textContent='⏳ جاري التحميل...';document.getElementById('loader').classList.add('show');let r=await fetch('/api/login_public',{method:'POST',body:new FormData(e.target)});let j=await r.json();if(j.ok){location.href='/dash?v=home';}else{document.getElementById('m').textContent='خطأ';b.textContent='✨ دخول';document.getElementById('loader').classList.remove('show');}});
</script></body></html>"""

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
    if q: return jsonify(qall("SELECT * FROM dish_ips WHERE ip LIKE? OR dish_name LIKE? OR location LIKE? ORDER BY id DESC LIMIT 100",("%"+q+"%","%"+q+"%","%"+q+"%")))
    return jsonify(qall("SELECT * FROM dish_ips ORDER BY id DESC LIMIT 100"))

@app.route('/toggle_theme')
@login_required
def tt():
    session['theme']='light' if session.get('theme','dark')=='dark' else 'dark'
    return jsonify(ok=True)

@app.route('/add_dish',methods=['POST'])
@login_required
def ad():
    ip=request.form.get('ip','').strip();name=request.form.get('dish_name','').strip();loc=request.form.get('location','').strip()
    if not is_valid_ip(ip): return "IP غير صالح",400
    ex=qone("SELECT * FROM dish_ips WHERE ip=?",(ip,))
    if ex: qexec("UPDATE dish_ips SET dish_name=?,location=? WHERE ip=?",(name,loc,ip))
    else: qexec("INSERT INTO dish_ips(ip,location,dish_name) VALUES(?,?,?)",(ip,loc,name))
    add_log('اضافة/تحديث صحن '+ip);return "ok"

@app.route('/del_dish/<int:i>')
@login_required
def dd(i): qexec("DELETE FROM dish_ips WHERE id=?",(i,));add_log(f'حذف صحن {i}');return "ok"

@app.route('/edit_dish/<int:i>',methods=['POST'])
@login_required
def ed(i): qexec("UPDATE dish_ips SET dish_name=?,ip=?,location=? WHERE id=?",(request.form.get('dish_name',''),request.form.get('ip',''),request.form.get('location',''),i));return "ok"

@app.route('/add_tower',methods=['POST'])
@login_required
def at(): qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",(request.form.get('name',''),request.form.get('area',''),35.1318,36.7578));return "ok"
@app.route('/del_tower/<int:i>')
@login_required
def dt(i): qexec("DELETE FROM towers WHERE id=?",(i,));return "ok"

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
def al():
    try: amt=float(request.form.get('amount') or 0)
    except: amt=0
    qexec("INSERT INTO ledger(name,amount,note,currency) VALUES(?,?,?,?)",(request.form.get('name',''),amt,request.form.get('note',''),request.form.get('currency','USD')));return "ok"
@app.route('/del_ledger/<int:i>')
@login_required
def dll(i): qexec("DELETE FROM ledger WHERE id=?",(i,));return "ok"

@app.route('/add_user',methods=['POST'])
@login_required
@role_required('manager')
def au():
    ph=request.form.get('user_field','').strip() or request.form.get('phone','').strip()
    if not ph: return "مطلوب",400
    if qone("SELECT * FROM users WHERE phone=?",(ph,)): return "موجود",400
    qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",(ph,generate_password_hash(request.form.get('password','1234')),request.form.get('role','tech'),ph))
    add_log('اضافة يوزر '+ph);return "ok"

@app.route('/del_user/<ph>')
@login_required
@role_required('manager')
def du(ph):
    if ph=='05344851045': return "ممنوع",400
    qexec("DELETE FROM users WHERE phone=?",(ph,));return "ok"

@app.route('/edit_user',methods=['POST'])
@login_required
@role_required('manager')
def eu():
    old=request.form.get('old_phone','').strip();new=request.form.get('phone','').strip();pw=request.form.get('password','').strip()
    if pw: qexec("UPDATE users SET phone=?,username=?,role=?,password=? WHERE phone=?",(new,new,request.form.get('role','tech'),generate_password_hash(pw),old))
    else: qexec("UPDATE users SET phone=?,username=?,role=? WHERE phone=?",(new,new,request.form.get('role','tech'),old))
    return "ok"

@app.route('/change_pass',methods=['POST'])
@login_required
def cp():
    np=request.form.get('newpass','').strip()
    if not np: return "فارغة",400
    qexec("UPDATE users SET password=? WHERE phone=?",(generate_password_hash(np),session.get('phone')))
    return "ok"

def page_content(v):
    if v=='home':
        ns=(qone("SELECT COUNT(*) c FROM subs") or {}).get('c',0)
        nd=(qone("SELECT COUNT(*) c FROM dish_ips") or {}).get('c',0)
        nt=(qone("SELECT COUNT(*) c FROM towers") or {}).get('c',0)
        nl=(qone("SELECT COUNT(*) c FROM ledger") or {}).get('c',0)
        return f"""<div style='max-width:700px;margin:0 auto;text-align:center'>
<div style='display:grid;grid-template-columns:1fr 1fr;gap:12px'>
<div class='card stat' onclick="loadPage('subs')"><div style='font-size:32px'>👥</div><h3>المشتركين</h3><h2>{ns}</h2></div>
<div class='card stat' onclick="loadPage('dishes')"><div style='font-size:32px'>📡</div><h3>الصحون</h3><h2>{nd}</h2></div>
<div class='card stat' onclick="loadPage('towers')"><div style='font-size:32px'>🗼</div><h3>الأبراج</h3><h2>{nt}</h2></div>
<div class='card stat' onclick="loadPage('net')"><div style='font-size:32px'>📶</div><h3>الشبكة</h3><h2>{nl}</h2></div>
</div>
<div class='card'><h4>📊 تصدير</h4><div style='display:flex;gap:8px;overflow-x:auto;padding:5px'>
<a href='/api/export/dishes' class=btn-gold style='text-decoration:none'>📊 صحون Excel</a>
<a href='/api/export/subs' class=btn-gold style='text-decoration:none'>📊 مشتركين Excel</a>
<a href='/api/export/users' class=btn-gold style='text-decoration:none'>📊 يوزرات Excel</a>
<button onclick="window.print()" class=btn-gold>📄 PDF</button></div></div>
<div class='card'><h4>📶 حالة الشبكة الحية</h4><div id=netLive>⏳ جاري الفحص...</div></div>
</div><script>
fetch('/api/net_status').then(r=>r.json()).then(d=>{let h='';d.forEach(x=>{h+='<div style="display:flex;justify-content:space-between;padding:6px;border-bottom:1px solid #ffffff10"><span>'+x.name+' '+x.ip+'</span><span>'+(x.ok?'🟢':'🔴')+'</span></div>'});document.getElementById('netLive').innerHTML=h||'لا يوجد';});
</script>"""
    if v=='dishes':
        return """<div style='max-width:900px;margin:0 auto'><div class=card>
<div style='display:flex;justify-content:space-between;align-items:center'><h3>📡 الصحون</h3><div style='display:flex;gap:6px'><a href='/api/export/dishes' class=btn-gold style='text-decoration:none'>📊 Excel</a><button onclick="window.print()" class=btn-gold>📄 PDF</button></div></div>
<form data-ajax method=post action=/add_dish style='display:flex;gap:5px;flex-wrap:wrap;margin-top:8px'><input name=dish_name placeholder='اسم' required style='flex:1'><input name=ip placeholder='IP' required style='flex:1'><input name=location placeholder='موقع' style='flex:1'><button class=btn-gold>➕</button></form>
<input id=searchBox placeholder='🔍 بحث يعمل 100%' oninput="doSearch(this.value)" style='margin-top:8px'></div><div id=dl></div></div>
<script>
window.doSearch=async function(q){let r=await fetch('/api/search?q='+encodeURIComponent(q));let d=await r.json();renderD(d);};
function renderD(d){let h='';d.forEach(x=>{h+='<div class="card" style="display:flex;justify-content:space-between;align-items:center"><div><b>'+x.dish_name+'</b><br><a href="http://'+x.ip+'" target="_blank" style="color:#ffbe4d;font-family:monospace">'+x.ip+' ↗</a><br><small>'+(x.location||'')+'</small><br><small class="po"></small></div><div style="display:flex;gap:5px"><button class=btn-gold onclick="pingIp(\\''+x.ip+'\\',this)">📶</button><button class=btn-del onclick="askDel(\\'/del_dish/'+x.id+'\\')">🗑</button></div></div>'});document.getElementById('dl').innerHTML=h||'لا يوجد';}
window.pingIp=function(ip,btn){btn.textContent='⏳';fetch('/api/ping?ip='+ip).then(r=>r.json()).then(j=>{btn.textContent=j.ok?'🟢':'🔴';});};
window.searchDishes=window.doSearch;window.doSearch('');
</script>"""
    if v=='towers':
        rs=qall("SELECT * FROM towers ORDER BY id DESC")
        rows="".join([f"<div class='card' style='display:flex;justify-content:space-between'><div><b>🗼 {esc(r['name'])}</b><br><small>{esc(r['area'] or '')}</small></div><button class=btn-del onclick=\"askDel('/del_tower/{r['id']}')\">🗑</button></div>" for r in rs])
        return f"""<div style='max-width:700px;margin:0 auto'><div class=card><h3>🗼 الأبراج</h3><form data-ajax method=post action=/add_tower style='display:flex;gap:6px'><input name=name placeholder='اسم' required style='flex:1'><input name=area placeholder='منطقة' style='flex:1'><button class=btn-gold>➕</button></form></div>{rows}</div>"""
    if v=='subs':
        rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 200")
        rows="".join([f"<div class='card' style='display:flex;justify-content:space-between'><div><b>{esc(r['name'])}</b><br>{esc(r['phone'] or '')}</div><button class=btn-del onclick=\"askDel('/del_sub/{r['id']}')\">🗑</button></div>" for r in rs])
        return f"""<div style='max-width:700px;margin:0 auto'><div class=card><h3>👥 المشتركين</h3><form data-ajax method=post action=/add_sub style='display:flex;gap:5px'><input name=name placeholder='الاسم' required style='flex:1'><input name=phone placeholder='رقم' style='flex:1'><button class=btn-gold>➕</button></form></div>{rows}</div>"""
    if v=='ledger':
        rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 200")
        rows="".join([f"<div class='card' style='display:flex;justify-content:space-between'><div><b>{esc(r['name'])}</b> {r['amount']}</div><button class=btn-del onclick=\"askDel('/del_ledger/{r['id']}')\">🗑</button></div>" for r in rs])
        return f"""<div style='max-width:700px;margin:0 auto'><div class=card><h3>📒 الحسابات</h3><form data-ajax method=post action=/add_ledger style='display:flex;gap:5px'><input name=name placeholder='الاسم' required style='flex:1'><input name=amount type=number placeholder='مبلغ' style='flex:1'><button class=btn-gold>➕</button></form></div>{rows}</div>"""
    if v=='net':
        return """<div class=card style='max-width:700px;margin:0 auto'><h3>📶 حالة الشبكة الحية</h3><button class=btn-gold onclick="loadNet()">🔄 تحديث</button><div id=nl style='margin-top:10px'>⏳...</div></div><script>
function loadNet(){document.getElementById('nl').innerHTML='⏳ جاري الفحص...';fetch('/api/net_status').then(r=>r.json()).then(d=>{let h='';d.forEach(x=>{h+='<div style="display:flex;justify-content:space-between;padding:10px;border-bottom:1px solid #ffffff10"><b>'+x.name+'<br><small>'+x.ip+'</small></b><span style="font-size:22px">'+(x.ok?'🟢 متصل':'🔴 واقف')+'</span></div>'});document.getElementById('nl').innerHTML=h;});}
loadNet();setInterval(loadNet,30000);</script>"""
    if v=='map':
        towers=qall("SELECT * FROM towers");tj=json.dumps([{"name":t['name'],"area":t.get('area') or '',"lat":float(t.get('lat') or 35.1318),"lng":float(t.get('lng') or 36.7578)} for t in towers],ensure_ascii=False)
        return f"""<div class=card style='padding:6px'><div id=map style='height:72vh;border-radius:14px'></div></div><script>
setTimeout(()=>{{let map=L.map('map').setView([35.1318,36.7578],13);let osm=L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:19}}).addTo(map);let sat=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',{{maxZoom:19}});L.control.layers({{"عادية":osm,"قمر صناعي 🛰️ دقة عالية":sat}}).addTo(map);let ts={tj};ts.forEach(t=>{{L.marker([t.lat,t.lng]).addTo(map).bindPopup(t.name)}});setTimeout(()=>map.invalidateSize(),400);}},150);</script>"""
    if v=='logs':
        rs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 100")
        rows="".join([f"<div class='card'><small>{esc(r['at'] or '')}</small><br><b>{esc(r['user'] or '')}</b> - {esc(r['action'] or '')}</div>" for r in rs])
        return f"<div style='max-width:700px;margin:0 auto'><div class=card><h3>📝 سجل النشاطات</h3></div>{rows or '<div class=card>فارغ</div>'}</div>"
    if v=='support':
        return """<div class=card style='text-align:center;max-width:500px;margin:0 auto'><h2>🛠 الدعم</h2><a href='https://wa.me/905344851045' style='display:inline-block;background:#22c55e;color:#fff;padding:14px 24px;border-radius:12px;text-decoration:none;font-weight:800'>💬 واتساب</a><br><br><a href='tel:+905344851045' style='color:#0ea5e9'>📞 +905344851045</a></div>"""
    if v=='settings':
        us=qall("SELECT * FROM users ORDER BY phone DESC")
        uh="".join([f"<div class='card'><b>{esc(u['username'] or '')}</b> {esc(u['phone'])} <small>{esc(u['role'])}</small></div>" for u in us])
        return f"""<div style='max-width:700px;margin:0 auto'><div class=card><h3>⚙ الإعدادات</h3><button onclick="toggleLang()" id=langBtnSettings class=btn-gold>🌐 تبديل اللغة</button> <button onclick="toggleTheme()" class=btn-gold>🌓 ليل/نهار</button></div>
<div class=card><h4>🔑 كلمة السر</h4><form data-ajax method=post action=/change_pass style='display:flex;gap:6px'><input name=newpass type=password placeholder='جديدة' style='flex:1'><button class=btn-gold>💾</button></form></div>
<div class=card><h4>👤 اضافة يوزر</h4><form data-ajax method=post action=/add_user style='display:flex;flex-direction:column;gap:8px'><input name=user_field placeholder='رقم / يوزر' required><input name=password type=password placeholder='كلمة سر' required><select name=role><option value=tech>فني</option><option value=manager>مدير</option></select><button class=btn-gold>➕ اضافة</button></form></div>{uh}</div>"""
    return "<div class=card>ok</div>"

def layout(c,v='home'):
    th=session.get('theme','dark');is_dark=(th=='dark')
    bg='#0a0e2a' if is_dark else '#f1f5f9';cb='#1e2433' if is_dark else '#fff';tx='#fff' if is_dark else '#0f172a';bd='#ffffff18' if is_dark else '#e2e8f0'
    return f"""<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<link rel=stylesheet href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'>
<style>@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@700;800;900&display=swap');
*{{box-sizing:border-box;font-family:'Cairo',system-ui}}body{{margin:0;background:{bg};color:{tx}}}
.top{{position:fixed;top:0;left:0;right:0;height:64px;background:#0f1424f2;backdrop-filter:blur(12px);color:#fff;display:flex;align-items:center;justify-content:space-between;padding:0 12px;z-index:1003;border-bottom:1px solid #ffffff10}}
.sidebar{{position:fixed;right:0;top:0;width:270px;height:100%;background:#111827f5;color:#fff;z-index:1002;padding-top:74px;transform:translateX(110%);transition:.25s}}.sidebar.active{{transform:none}}
.sidebar a{{display:flex;padding:12px 16px;margin:6px 12px;color:#fff;text-decoration:none;border-radius:12px;background:#ffffff10}}.sidebar a.active{{background:#ffbe4d;color:#111;font-weight:800}}
#overlay{{position:fixed;inset:0;background:#0008;z-index:1001;display:none}}#overlay.show{{display:block}}
.main{{margin-top:74px;padding:12px;min-height:90vh;transition:.18s}}
.card{{background:linear-gradient(180deg,{cb},{cb});padding:14px;border-radius:18px;margin-bottom:10px;border:1px solid {bd};box-shadow:0 8px 24px #0005}}
.card.stat{{text-align:center;cursor:pointer}}.card.stat h2{{font-size:44px;color:#ffbe4d;margin:5px 0;font-weight:900}}.card.stat h3{{margin:0;font-size:15px}}
input,select{{padding:11px;border-radius:10px;border:1px solid {bd};width:100%;background:#ffffff08;color:{tx}}}
.btn-gold{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;padding:8px 14px;border:0;border-radius:12px;font-weight:800;cursor:pointer;white-space:nowrap}}.btn-del{{background:#ef4444;color:#fff;padding:8px 12px;border:0;border-radius:10px;cursor:pointer}}
#delModal{{position:fixed;inset:0;background:#0009;display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:.25s;z-index:2000}}#delModal.show{{opacity:1;pointer-events:auto}}
</style></head><body>
<div id=overlay onclick="toggleSb(false)"></div>
<div class=sidebar id=sb>
<a href="javascript:loadPage('home')" id=nav-home>🏠 الرئيسية</a>
<a href="javascript:loadPage('dishes')" id=nav-dishes>📡 الصحون</a>
<a href="javascript:loadPage('net')" id=nav-net>📶 حالة الشبكة</a>
<a href="javascript:loadPage('towers')" id=nav-towers>🗼 الأبراج</a>
<a href="javascript:loadPage('subs')" id=nav-subs>👥 المشتركين</a>
<a href="javascript:loadPage('ledger')" id=nav-ledger>📒 الحسابات</a>
<a href="javascript:loadPage('map')" id=nav-map>🗺 الخريطة الحية</a>
<a href="javascript:loadPage('logs')" id=nav-logs>📝 السجل</a>
<a href="javascript:loadPage('support')" id=nav-support>🛠 الدعم</a>
<a href="javascript:loadPage('settings')" id=nav-settings>⚙ الإعدادات</a>
<a href=/logout>🚪 خروج</a></div>
<div class=top><div style='display:flex;gap:8px;align-items:center'><span onclick="toggleSb()" style='font-size:24px;cursor:pointer'>☰</span><input id=topsearch placeholder='🔍 بحث سريع' oninput="if(window.searchDishes)window.searchDishes(this.value)" style='width:90px;background:#1f2937;border:1px solid #374151;color:#fff;padding:7px;border-radius:10px'></div>
<div style='font-weight:900;font-size:18px'>🛰️ OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<div><button onclick="toggleTheme()" style='background:#1f2937;color:#fff;border:0;padding:8px 10px;border-radius:10px'>🌓</button></div></div>
<div class=main id=mn>{c}</div>
<a href='https://wa.me/905344851045' target=_blank style='position:fixed;bottom:20px;left:20px;background:#22c55e;color:#fff;width:56px;height:56px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:28px;z-index:999;text-decoration:none;box-shadow:0 8px 20px #0008'>💬</a>
<div id=delModal><div style='background:{cb};padding:24px;border-radius:18px;width:90%;max-width:400px;text-align:center'><h3>تأكيد الحذف؟</h3><div style='display:flex;gap:10px'><button onclick="closeDel()" style='flex:1;padding:12px;border-radius:12px'>تراجع</button><button id=delYes style='flex:1;padding:12px;background:#ef4444;color:#fff;border:0;border-radius:12px;font-weight:800'>حذف</button></div></div></div>
<script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>
<script>
let cur='{v}';
function toggleSb(f){{let sb=document.getElementById('sb'),ov=document.getElementById('overlay');let o=f!==undefined?f:!sb.classList.contains('active');sb.classList.toggle('active',o);ov.classList.toggle('show',o);}}
async function loadPage(v){{cur=v;toggleSb(false);let mn=document.getElementById('mn');mn.style.opacity='0.4';try{{let r=await fetch('/api/page?v='+v,{{cache:'no-store'}});mn.innerHTML=await r.text();mn.style.opacity='1';bind();mn.querySelectorAll('script').forEach(s=>{{try{{eval(s.textContent)}}catch(e){{}}}});document.querySelectorAll('.sidebar a').forEach(a=>a.classList.remove('active'));let n=document.getElementById('nav-'+v);if(n)n.classList.add('active');}}catch(e){{mn.innerHTML='خطأ';mn.style.opacity='1';}}}}
function bind(){{document.querySelectorAll('form[data-ajax]').forEach(f=>{{f.onsubmit=async e=>{{e.preventDefault();let r=await fetch(f.action,{{method:'POST',body:new FormData(f)}});if(r.ok)loadPage(cur);else alert(await r.text());}}}});}}
function askDel(u){{window._d=u;document.getElementById('delModal').classList.add('show');}}
function closeDel(){{document.getElementById('delModal').classList.remove('show');}}
document.getElementById('delYes').onclick=async()=>{{await fetch(window._d);closeDel();loadPage(cur);}};
async function toggleTheme(){{await fetch('/toggle_theme');location.reload();}}
function toggleLang(){{let l=localStorage.getItem('omaia_lang')||'ar';l=l==='ar'?'en':'ar';localStorage.setItem('omaia_lang',l);alert(l==='ar'?'تم التبديل لعربي':'Switched to English');}}
bind();document.getElementById('mn').querySelectorAll('script').forEach(s=>{{try{{eval(s.textContent)}}catch(e){{}}}});
</script></body></html>"""

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
