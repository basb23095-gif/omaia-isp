from flask import Flask, request, redirect, session, jsonify
from colors import COLORS, logo_html
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, datetime, json, html, subprocess, platform, ipaddress, socket
try: import psycopg2, psycopg2.extras
except: psycopg2=None
import sqlite3
app=Flask(__name__)
app.secret_key=os.environ.get("SECRET_KEY","omia-final-2026")
DATABASE_URL=os.environ.get("DATABASE_URL","").strip().replace("postgresql://","postgres://")
USE_PG=bool(DATABASE_URL.startswith("postgres://") and psycopg2)
_pg=None
WA="https://wa.me/905344851045"
INSTA="https://instagram.com/af_20_1999"
def esc(s): return html.escape(str(s or ''),quote=True)
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
            cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor);cur.execute(q.replace("?","%s"),a);r=[dict(x) for x in cur.fetchall()];cur.close();return r
        r=[dict(x) for x in c.execute(q,a).fetchall()];cc(c);return r
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
    ss=["CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,username TEXT)","CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,dish_name TEXT,location TEXT,lat REAL,lng REAL)","CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,area TEXT,lat REAL,lng REAL)","CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT)","CREATE TABLE IF NOT EXISTS activity_log(id INTEGER PRIMARY KEY AUTOINCREMENT,time TEXT,action TEXT,phone TEXT,username TEXT)","CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY,v TEXT)"]
    if USE_PG: ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
    for s in ss: qexec(s)
    if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)): qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",('05344851045',generate_password_hash('admin2024'),'manager','admin'))
    if not qone("SELECT v FROM settings WHERE k='allow_edit'"): qexec("INSERT INTO settings(k,v) VALUES('allow_edit','1')")
    if not qone("SELECT v FROM settings WHERE k='allow_delete'"): qexec("INSERT INTO settings(k,v) VALUES('allow_delete','1')")
init()
def get_set(k):
    r=qone("SELECT v FROM settings WHERE k=?",(k,));return r['v'] if r else '1'
def add_log(a):
    ph=session.get('phone','system');u=qone("SELECT username FROM users WHERE phone=?",(ph,));un=u['username'] if u else ph
    qexec("INSERT INTO activity_log(time,action,phone,username) VALUES(?,?,?,?)",(datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),a,ph,un))
def login_required(f):
    @wraps(f)
    def w(*a,**kw):
        if not session.get('phone'): return redirect('/login')
        return f(*a,**kw)
    return w
def manager_required(f):
    @wraps(f)
    def w(*a,**kw):
        m=qone("SELECT * FROM users WHERE phone=?",(session.get('phone'),))
        if not m or m.get('role')=='tech': return "ممنوع",403
        return f(*a,**kw)
    return w
def me(): return qone("SELECT * FROM users WHERE phone=?",(session.get('phone'),))
def can_edit():
    if get_set('allow_edit')=='0': return False
    m=me();return m and m['role']!='tech'
def can_del():
    if get_set('allow_delete')=='0': return False
    m=me();return m and m['role']!='tech'
def is_internal(ip):
    try: o=ipaddress.ip_address(ip.strip());return o.is_private and not o.is_loopback
    except: return False

@app.route('/api/ping')
@login_required
def api_ping():
    ip=request.args.get('ip','')
    if not is_internal(ip): return jsonify(ok=False,out='خارج الشبكة')
    try:
        w=platform.system().lower()=='windows';cmd=['ping','-n','2',ip] if w else ['ping','-c','2','-W','2',ip]
        o=subprocess.run(cmd,capture_output=True,text=True,timeout=4)
        return jsonify(ok=True,out=(o.stdout+o.stderr)[:800])
    except Exception as e: return jsonify(ok=False,out=str(e)[:200])

@app.route('/api/search')
@login_required
def api_search():
    q=request.args.get('q','');pg=int(request.args.get('page',0))
    if q: rs=qall("SELECT * FROM dish_ips WHERE ip LIKE? OR dish_name LIKE? ORDER BY id DESC LIMIT 20 OFFSET "+str(pg*20),("%"+q+"%","%"+q+"%"))
    else: rs=qall("SELECT * FROM dish_ips ORDER BY id DESC LIMIT 20 OFFSET "+str(pg*20))
    return jsonify(rs)

def page_content(v):
    ce=can_edit(); cd=can_del()
    if v=='home':
        nd=(qone("SELECT COUNT(*) c FROM dish_ips") or {}).get('c',0); nt=(qone("SELECT COUNT(*) c FROM towers") or {}).get('c',0)
        return "<div style='max-width:700px;margin:0 auto;text-align:center'><h2>"+logo_html()+"</h2><div style='display:grid;grid-template-columns:1fr 1fr;gap:12px'><div class=card onclick=\"loadPage('dishes')\"><h3>📡 الصحون</h3><h2>"+str(nd)+"</h2></div><div class=card onclick=\"loadPage('towers')\"><h3>🗼 الأبراج</h3><h2>"+str(nt)+"</h2></div><div class=card onclick=\"loadPage('map')\"><h3>🗺 الخريطة</h3></div><div class=card onclick=\"loadPage('support')\"><h3>🛠 الدعم</h3></div></div></div>"
    if v=='dishes':
        out="<div style='max-width:900px;margin:0 auto'><div style='display:grid;grid-template-columns:1fr 1fr;gap:12px'>"
        out+="<div class=card style='text-align:center'><h3>📡 اضافة صحن</h3><form data-ajax method=post action=/add_dish><input name=dish_name required placeholder='اسم الصحن'><input name=ip required placeholder='IP'><input name=location placeholder='الموقع'><button class=btn-gold>اضافة</button></form><input id=q oninput='s()' placeholder='🔍 بحث فوري IP او اسم' style='margin-top:10px'></div>"
        out+="<div id=list></div></div><div id=toast></div>"
        out+="<script>let pg=0,qq='';async function s(){qq=document.getElementById('q').value;pg=0;load()}async function load(){let r=await fetch('/api/search?q='+encodeURIComponent(qq)+'&page='+pg);let d=await r.json();let h='';d.forEach(function(x){h+=\"<div class=card style='display:grid;grid-template-columns:1fr auto;gap:8px'><div><b>\"+x.dish_name+\"</b><br><span class=ip-badge>\"+x.ip+\"</span></div><div>\";h+=\"<button class=btn-blue onclick=pingD('\"+x.ip+\"')>بينغ</button> \";"
        if ce: out+=""
        out+="h+=\"</div></div>\"});document.getElementById('list').innerHTML=h+(d.length==20?\"<button class=btn onclick='pg++;load()'>التالي</button>\":\"\")}async function pingD(ip){let t=document.getElementById('toast');t.textContent='...';t.style.display='block';let r=await fetch('/api/ping?ip='+ip);let j=await r.json();t.textContent=j.out.slice(0,100);setTimeout(function(){t.style.display='none'},2500)}load()</script></div>"
        # add edit/del buttons via simple logic to avoid f-string issues
        return out.replace("h+=\"</div></div>\"", "h+= \"" + ("<button class=btn-icon style=background:#FF9800;color:#fff onclick=editD('+x.id+')>✏️</button> " if ce else "") + ("<button class=btn-icon style=background:#F44336;color:#fff onclick=delD('+x.id+')>🗑️</button>" if cd else "") + "\"+\"</div></div>\"") + "<script>async function delD(id){if(!confirm('حذف؟'))return;await fetch('/del_dish/'+id);load()}function editD(id){alert('تعديل '+id)}</script>"
    if v=='towers':
        rs=qall("SELECT * FROM towers ORDER BY id DESC LIMIT 20"); h=""
        for r in rs:
            h+="<div class=card style='display:grid;grid-template-columns:1fr auto;max-width:600px;margin:8px auto'><div><b>🗼 "+esc(r['name'])+"</b><br><small>"+esc(r.get('area') or '')+"</small></div><div>"
            if ce: h+="<button class=btn-icon style='background:#FF9800;color:#fff'>✏️</button> "
            if cd: h+="<a href='/del_tower/"+str(r['id'])+"'><button class=btn-icon style='background:#F44336;color:#fff'>🗑️</button></a>"
            h+="</div></div>"
        return "<div style='max-width:650px;margin:0 auto'><div class=card style='text-align:center'><h3>🗼 الابراج</h3><form data-ajax method=post action=/add_tower><input name=name required placeholder='اسم البرج'><input name=area required placeholder='المنطقة'><button class=btn-gold>اضافة</button></form></div>"+h+"</div>"
    if v=='map':
        tw=qall("SELECT * FROM towers"); tj=json.dumps([{"n":t['name'],"la":float(t.get('lat') or 35.13),"ln":float(t.get('lng') or 36.75)} for t in tw],ensure_ascii=False)
        s="<div class=card style='padding:6px'><div id=map style='height:75vh;border-radius:12px'></div><div style='display:flex;gap:8px;margin-top:8px'><input id=mq onkeydown=\"if(event.key=='Enter')goM()\" placeholder='ابحث و اضغط Enter'><button class=btn-blue onclick='myLoc()'>📍 موقعي</button></div>"
        s+="<link rel='stylesheet' href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'/><script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script><script>"
        s+="var map=L.map('map',{zoomControl:true,zoomSnap:0.5,zoomDelta:0.5,wheelPxPerZoomLevel:80}).setView([35.1318,36.7578],16);"
        s+="L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{maxZoom:22,maxNativeZoom:19,detectRetina:true}).addTo(map);"
        s+="setTimeout(function(){map.invalidateSize()},300);"
        s+="var tw="+tj+";tw.forEach(function(t){L.marker([t.la,t.ln]).addTo(map).bindPopup(t.n)});"
        s+="function myLoc(){if(navigator.geolocation)navigator.geolocation.getCurrentPosition(function(p){map.flyTo([p.coords.latitude,p.coords.longitude],18,{duration:1.2});L.marker([p.coords.latitude,p.coords.longitude]).addTo(map).bindPopup('انت هنا').openPopup()},{enableHighAccuracy:true})}"
        s+="window.goM=function(){var q=document.getElementById('mq').value;fetch('/api/search?q='+encodeURIComponent(q)).then(function(r){return r.json()}).then(function(d){if(d.length)map.flyTo([35.1318,36.7578],17,{duration:1})})};"
        s+="if(navigator.geolocation)navigator.geolocation.watchPosition(function(p){},null,{enableHighAccuracy:true});"
        s+="</script></div>"
        return s
    if v=='logs':
        rs=qall("SELECT * FROM activity_log ORDER BY id DESC LIMIT 100"); h=""
        for r in rs: h+="<div class=log-row><span>"+esc(r['time'])+"</span> <b>👤 "+esc(r.get('username') or r['phone'])+"</b> "+esc(r['action'])+"</div>"
        return "<div style='max-width:650px;margin:0 auto'><div class=card><h3 style='text-align:center'>📜 السجل</h3>"+h+"</div></div>"
    if v=='support':
        return "<div style='max-width:500px;margin:20px auto'><div class=card style='text-align:center;border:2px solid #ffbe4d'><h2>"+logo_html()+"</h2><p>الدعم الفني</p><div dir=ltr style='font-size:20px;font-weight:bold'>+90 534 485 10 45</div><div style='margin-top:12px;display:flex;gap:12px;justify-content:center'><a href='"+WA+"' target=_blank style='width:56px;height:56px;background:#25D366;border-radius:50%;display:flex;align-items:center;justify-content:center'><svg viewBox=\"0 0 32 32\" width=\"28\" height=\"28\" fill=\"white\"><path d=\"M16 3C9.4 3 4 8.4 4 15c0 2.4.7 4.7 2 6.7L4 29l7.5-2c2 1 4 1.5 6.5 1.5 6.6 0 12-5.4 12-12S22.6 3 16 3z\"/></svg></a><a href='"+INSTA+"' target=_blank style='width:56px;height:56px;background:#E1306C;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:28px;text-decoration:none'>📸</a></div><div style='color:#aaa;margin-top:8px'>af_20_1999</div></div></div>"
    if v=='settings':
        us=qall("SELECT phone,username,role FROM users"); uh=""
        for u in us:
            rl='فني' if u['role']=='tech' else 'مدير'
            uh+="<div class=card style='max-width:550px;margin:8px auto'><b>"+esc(u.get('username') or '')+"</b><br><small>"+esc(u['phone'])+"</small> - <small>"+rl+"</small></div>"
        ae=get_set('allow_edit'); ad=get_set('allow_delete')
        c1="checked" if ae=="1" else ""; c2="checked" if ad=="1" else ""
        out2="<div style='max-width:650px;margin:0 auto'><div class=card style='text-align:center'><h3>⚙ الاعدادات</h3>"
        out2+="<label><input type=checkbox "+c1+" onchange=\"fetch('/set/allow_edit/'+(this.checked?'1':'0')).then(()=>location.reload())\"> تشغيل التعديل</label><br>"
        out2+="<label><input type=checkbox "+c2+" onchange=\"fetch('/set/allow_delete/'+(this.checked?'1':'0')).then(()=>location.reload())\"> تشغيل الحذف</label>"
        out2+="</div><div class=card style='text-align:center'><h3>اضافة مستخدم</h3><form data-ajax method=post action=/add_user><input name=phone required placeholder='يوزر / رقم'><input name=password type=password required placeholder='كلمة السر'><select name=role><option value=tech>فني - اضافة فقط</option><option value=manager>مدير - كل الصلاحيات</option></select><button class=btn-gold>اضافة</button></form></div>"+uh+"</div>"
        return out2
    return "ok"

def layout(c,v):
    return "<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><style>*{box-sizing:border-box;font-family:sans-serif}body{margin:0;background:#0a1938;color:#fff} @media(max-width:768px){*{animation:none!important;transition:none!important}}.sidebar{position:fixed;right:-300px;top:0;width:280px;height:100%;background:#111;z-index:1000;padding-top:70px;transition:.25s}.sidebar.active{right:0}.sidebar a{display:block;padding:12px;color:#fff;text-decoration:none}.top{position:fixed;top:0;left:0;right:0;height:60px;background:#1a1a1a;display:flex;align-items:center;justify-content:space-between;padding:0 12px;z-index:101}.main{margin-top:60px;padding:10px}.card{background:#1e1e1e;padding:14px;border-radius:12px;margin-bottom:10px;border:1px solid #333}.btn{background:#333;color:#fff;padding:8px 14px;border:0;border-radius:8px}.btn-gold{background:#ffbe4d;color:#000;padding:10px;border:0;border-radius:8px;font-weight:bold}.btn-blue{background:#2196F3;color:#fff;padding:6px 12px;border:0;border-radius:8px}input,select{width:100%;padding:10px;margin:4px 0;background:#111;border:1px solid #444;color:#fff;border-radius:8px}.ip-badge{background:#000;color:#ffbe4d;padding:4px 10px;border-radius:12px;font-family:monospace}#toast{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:#333;padding:10px 20px;border-radius:20px;display:none;z-index:9999}.log-row{padding:6px;border-bottom:1px solid #333;font-size:13px}.btn-icon{width:36px;height:36px;border-radius:10px;border:0;font-size:16px}</style></head><body><div class=sidebar id=sb><a href=\"javascript:loadPage('home')\">🏠 الرئيسية</a><a href=\"javascript:loadPage('dishes')\">📡 الصحون</a><a href=\"javascript:loadPage('towers')\">🗼 الابراج</a><a href=\"javascript:loadPage('map')\">🗺 الخريطة</a><a href=\"javascript:loadPage('logs')\">📜 السجل</a><a href=\"javascript:loadPage('support')\">🛠 الدعم</a><a href=\"javascript:loadPage('settings')\">⚙ الاعدادات</a><a href=/logout>🚪 خروج</a></div><div class=top><div onclick=\"document.getElementById('sb').classList.toggle('active')\" style='font-size:22px'>☰</div><div>"+logo_html()+"</div><div><button class=btn onclick=\"loadPage(cur,true)\">↻</button></div></div><div class=main id=mn>"+c+"</div><script>let cur='"+v+"';const cache={};async function loadPage(v,f){cur=v;document.getElementById('sb').classList.remove('active');if(cache[v]&&!f){document.getElementById('mn').innerHTML=cache[v];bind();exe();return}let r=await fetch('/api/page?v='+v);let h=await r.text();cache[v]=h;document.getElementById('mn').innerHTML=h;bind();exe()}function bind(){document.querySelectorAll('form[data-ajax]').forEach(function(f){f.onsubmit=async function(e){e.preventDefault();await fetch(f.action,{method:'POST',body:new FormData(f)});Object.keys(cache).forEach(function(k){delete cache[k]});loadPage(cur,true)}})}function exe(){document.getElementById('mn').querySelectorAll('script').forEach(function(s){try{eval(s.textContent)}catch(e){}})}bind();exe();</script></body></html>"

@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')
@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        uin=request.form.get('userin','').strip();pw=request.form.get('password','')
        u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
        if u and check_password_hash(u['password'],pw):
            session['phone']=u['phone'];add_log("دخول "+uin);return redirect('/dash')
        return "<script>alert('خطأ');location.href='/login'</script>"
    return "<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><style>body{background:#0a1938;color:#fff;text-align:center;padding:30px;font-family:sans-serif}input{padding:12px;margin:6px;width:280px;border-radius:10px;border:1px solid #ffbe4d;background:#1e1e1e;color:#fff;text-align:center}button{background:#ffbe4d;padding:12px 40px;border:0;border-radius:10px;font-weight:bold}</style></head><body>"+logo_html()+"<h2>OMAIA ISP</h2><form method=post id=lf><input id=uin name=userin placeholder='يوزر / هاتف'><br><input id=pw name=password type=password placeholder='كلمة السر'><br><label><input type=checkbox id=rm style='width:18px'> حفظ كلمة السر</label><br><button>دخول</button></form><div style='margin-top:15px'><a href='"+WA+"' target=_blank style='display:inline-block;width:56px;height:56px;background:#25D366;border-radius:50%'><svg viewBox=\"0 0 32 32\" width=\"30\" height=\"30\" style=\"margin-top:13px\" fill=\"white\"><path d=\"M16 3C9.4 3 4 8.4 4 15c0 2.4.7 4.7 2 6.7L4 29l7.5-2c2 1 4 1.5 6.5 1.5 6.6 0 12-5.4 12-12S22.6 3 16 3z\"/></svg></a></div><script>window.onload=function(){var u=localStorage.getItem('u'),p=localStorage.getItem('p');if(u)document.getElementById('uin').value=u;if(p){document.getElementById('pw').value=p;document.getElementById('rm').checked=true}};document.getElementById('lf').onsubmit=function(){if(document.getElementById('rm').checked){localStorage.setItem('u',document.getElementById('uin').value);localStorage.setItem('p',document.getElementById('pw').value)}else{localStorage.removeItem('u');localStorage.removeItem('p')}}<\/script></body></html>"

@app.route('/logout')
def lo(): session.clear();return redirect('/login')
@app.route('/dash')
@login_required
def dash(): return layout(page_content(request.args.get('v','home')),request.args.get('v','home'))
@app.route('/api/page')
@login_required
def ap(): return page_content(request.args.get('v','home'))
@app.route('/set/<k>/<vv>')
@manager_required
def st(k,vv): qexec("INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)",(k,vv));return "ok"
@app.route('/add_dish',methods=['POST'])
@login_required
def ad():
    ip=request.form.get('ip','').strip()
    if not is_internal(ip): return "IP غير داخلي",400
    qexec("INSERT INTO dish_ips(ip,dish_name,location,lat,lng) VALUES(?,?,?,?,?)",(ip,request.form.get('dish_name'),request.form.get('location'),0,0));add_log("اضافة صحن "+request.form.get('dish_name',''));return "ok"
@app.route('/del_dish/<int:i>')
@login_required
def dd(i):
    if not can_del(): return "ممنوع",403
    qexec("DELETE FROM dish_ips WHERE id=?",(i,));return "ok"
@app.route('/add_tower',methods=['POST'])
@login_required
def at(): qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",(request.form.get('name'),request.form.get('area'),35.1318,36.7578));add_log("اضافة برج");return "ok"
@app.route('/del_tower/<int:i>')
@login_required
def dt(i):
    if not can_del(): return "ممنوع",403
    qexec("DELETE FROM towers WHERE id=?",(i,));return "ok"
@app.route('/add_user',methods=['POST'])
@manager_required
def au():
    ph=request.form.get('phone','').strip()
    if qone("SELECT * FROM users WHERE phone=?",(ph,)): return "موجود",400
    qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",(ph,generate_password_hash(request.form.get('password')),request.form.get('role','tech'),ph));return "ok"
if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
