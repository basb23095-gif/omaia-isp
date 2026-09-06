from flask import Flask, request, redirect, session, jsonify
import os, datetime, json, html, subprocess, platform, ipaddress
try:
    import psycopg2, psycopg2.extras
except: psycopg2=None
import sqlite3
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY","omia-sec-2026")
DATABASE_URL = os.environ.get("DATABASE_URL","").strip().replace("postgresql://","postgres://")
USE_PG = bool(DATABASE_URL.startswith("postgres://") and psycopg2)
_pg = None
def esc(s): return html.escape(str(s or ''), quote=True)
def db():
    global _pg
    if USE_PG:
        try:
            if _pg:
                cur=_pg.cursor();cur.execute("SELECT 1");cur.close();return _pg
        except:
            try:_pg.close()
            except:pass
            _pg=None
        _pg=psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=5);_pg.autocommit=True;return _pg
    c=sqlite3.connect("omia.db");c.row_factory=sqlite3.Row;return c
def cc(c):
    if not USE_PG:
        try:c.close()
        except:pass
def qall(q,a=()):
    c=db()
    try:
        if USE_PG:
            cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(q.replace("?","%s"),a);rs=[dict(r) for r in cur.fetchall()];cur.close();return rs
        else: rs=[dict(r) for r in c.execute(q,a).fetchall()];cc(c);return rs
    except Exception as e: print(e);cc(c);return []
def qone(q,a=()):
    r=qall(q,a);return r[0] if r else None
def qexec(q,a=()):
    c=db()
    try:
        if USE_PG: cur=c.cursor();cur.execute(q.replace("?","%s"),a);cur.close()
        else: c.execute(q,a);c.commit();cc(c)
    except Exception as e: print(e);cc(c)
def fnum(v):
    try:return float(v or 0)
    except:return 0
def init():
    ss=["CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,active INT DEFAULT 1)","CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,active INT DEFAULT 1)","CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,sub_id INT,amount REAL,typ TEXT,dt TEXT,note TEXT,currency TEXT DEFAULT 'SYP',name TEXT)","CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,lat REAL DEFAULT 0,lng REAL DEFAULT 0,dish_name TEXT,tower_name TEXT)","CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,lat REAL,lng REAL,location TEXT)"]
    if USE_PG: ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
    for s in ss: qexec(s)
    try: qexec("ALTER TABLE users ADD COLUMN username TEXT")
    except: pass
    try: qexec("ALTER TABLE towers ADD COLUMN location TEXT")
    except: pass
    try: qexec("ALTER TABLE ledger ADD COLUMN currency TEXT DEFAULT 'SYP'")
    except: pass
    try: qexec("ALTER TABLE ledger ADD COLUMN name TEXT")
    except: pass
    if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username,active) VALUES(?,?,?,?,?)",('05344851045','admin2024','manager','admin',1))
init()
def me(): return qone("SELECT * FROM users WHERE phone=?",(session.get('phone'),))
def can_edit():
    m=me(); return not (m and m.get('role')=='tech')
def dark(): return session.get('theme','light')
def is_internal_ip(ip):
    try:
        ip_o = ipaddress.ip_address(ip.strip())
        return ip_o.is_private
    except: return False

TR = {
 'ar': {'home':'الرئيسية','ping':'بينغ','subs':'مشتركين','ledger':'دفتر حسابات','dishes':'صحون','towers':'الأبراج','map':'الخريطة','settings':'الإعدادات','logout':'خروج'},
 'en': {'home':'Home','ping':'Ping','subs':'Subscribers','ledger':'Ledger','dishes':'Dishes','towers':'Towers','map':'Map','settings':'Settings','logout':'Logout'}
}
def T(k):
    lang=session.get('lang','ar')
    return TR.get(lang,TR['ar']).get(k,k)

@app.route('/api/ping')
def api_ping():
    ip=request.args.get('ip','').strip()
    if not ip: return jsonify(ok=False,out='no ip')
    if not is_internal_ip(ip):
        return jsonify(ok=False,out='No Ping - خارج الشبكة / Outside network')
    try:
        w=platform.system().lower()=='windows'
        cmd=['ping','-n','2',ip] if w else ['ping','-c','2','-W','2',ip]
        o=subprocess.run(cmd,capture_output=True,text=True,timeout=8)
        return jsonify(ok=True,out=((o.stdout or '')+(o.stderr or ''))[:2000])
    except Exception as e: return jsonify(ok=False,out=str(e))

@app.route('/toggle_lang')
def tl(): session['lang']='en' if session.get('lang','ar')=='ar' else 'ar';return "ok"
@app.route('/toggle_theme_ajax')
def tt(): session['theme']='light' if dark()=='dark' else 'dark';return "ok"

def page_content(v):
    h=""; dis="" if can_edit() else "style='opacity:.35;pointer-events:none'"
    lang=session.get('lang','ar')
    if v=='home':
        ns=(qone("SELECT COUNT(*) c FROM subs") or {}).get('c',0);nd=(qone("SELECT COUNT(*) c FROM dish_ips") or {}).get('c',0)
        h="<div class=grid><div class=kpi style='background:#2563eb'>👥<br>"+str(ns)+"</div><div class=kpi style='background:#16a34a'>📡<br>"+str(nd)+"</div></div><div class=card>Welcome "+esc(session.get('phone'))+" - OMAIA ISP</div>"
        h+='<div class=card><h3>Ping Test (Local only)</h3><div style="display:flex;gap:6px"><input id=ping_ip placeholder="192.168.1.1"><button onclick="doPing()">Ping</button></div><pre id=ping_out style="background:#000;color:#0f0;padding:8px;border-radius:8px;min-height:60px"></pre></div><script>async function doPing(){var i=document.getElementById("ping_ip").value;document.getElementById("ping_out").textContent="...";var r=await fetch("/api/ping?ip="+encodeURIComponent(i));var j=await r.json();document.getElementById("ping_out").textContent=j.out}</script>'
        return h
    if v=='ping': return '<div class=card><h3>Ping - اكتب IP داخل الشبكة</h3><div style="display:flex;gap:6px"><input id=ping_ip2 placeholder="192.168.1.1"><button onclick="doPing2()">Ping</button></div><pre id=ping_out2 style="background:#000;color:#0f0;padding:8px;border-radius:8px;min-height:100px"></pre></div><script>async function doPing2(){var i=document.getElementById("ping_ip2").value;document.getElementById("ping_out2").textContent="...";var r=await fetch("/api/ping?ip="+encodeURIComponent(i));var j=await r.json();document.getElementById("ping_out2").textContent=j.out}</script>'
    if v=='subs':
        rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 100")
        h="<div class=card><h3>Subscribers</h3><form data-ajax method=post action=/add_sub><input name=name required placeholder='Name'><button>Add</button></form></div>"
        for r in rs: h+="<div class=card>"+esc(r['name'])+" <a href=/del_sub/"+str(r['id'])+" data-del "+dis+" style='color:red'>del</a></div>"
        return h
    if v=='dishes':
        rs=qall("SELECT * FROM dish_ips ORDER BY id DESC LIMIT 200")
        h="<div class=card><h3>Dishes</h3><form data-ajax method=post action=/add_dish><input name=dish_name required placeholder='Dish name'><input name=ip required placeholder='IP'><button>Add</button></form></div><div class=grid2>"
        for r in rs:
            ip=esc(r['ip']);h+="<div class='card small'><b>"+esc(r.get('dish_name') or '')+"</b> "+ip+"<br><button style='padding:4px;font-size:11px' onclick='fetch(\"/api/ping?ip="+ip+"\").then(r=>r.json()).then(j=>alert(j.out.slice(0,500)))'>Ping</button> <a href=/del_dish/"+str(r['id'])+" data-del "+dis+" style='color:red'>del</a></div>"
        return h+"</div>"
    if v=='towers':
        rs=qall("SELECT * FROM towers ORDER BY id DESC LIMIT 100")
        h="<div class=card><h3>Towers - اسم موقع / احداثية</h3><form data-ajax method=post action=/add_tower><input name=name required placeholder='Tower name'><input name=location placeholder='Location'><input name=lat placeholder='Lat'><input name=lng placeholder='Lng'><button>Add</button></form></div>"
        for r in rs: h+="<div class=card><b>"+esc(r['name'])+"</b> - "+esc(r.get('location',''))+" - "+str(r.get('lat',0))+","+str(r.get('lng',0))+"</div>"
        return h
    if v=='ledger':
        rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 100")
        tot_syp=(qone("SELECT SUM(amount) s FROM ledger WHERE currency='SYP'") or {}).get('s',0) or 0
        tot_usd=(qone("SELECT SUM(amount) s FROM ledger WHERE currency='USD'") or {}).get('s',0) or 0
        h=f"<div class=card><h3>Ledger - دفتر حسابات</h3><div>SYP: {tot_syp} | USD: {tot_usd}</div><form data-ajax method=post action=/add_ledger><input name=name placeholder='الاسم'><input name=amount type=number step=0.01 required placeholder='مبلغ'><input name=note placeholder='ملاحظة'><select name=currency><option value=SYP>سوري SYP</option><option value=USD>دولار USD</option></select><button>اضافة</button></form></div>"
        for r in rs: h+="<div class=card>"+esc(r.get('name',''))+" - "+str(r.get('amount',0))+" "+esc(r.get('currency',''))+" - "+esc(r.get('note',''))+"</div>"
        return h
    if v=='map':
        ds=qall("SELECT lat,lng,dish_name,ip FROM dish_ips WHERE lat!=0 LIMIT 500");arr=[]
        for d in ds:
            try:
                if d.get("lat"): arr.append({"la":float(d.get("lat") or 0),"ln":float(d.get("lng") or 0),"n":str(d.get("dish_name","")),"ip":str(d.get("ip",""))})
            except: pass
        dj=json.dumps(arr).replace("</","<\\/")
        h="<div class=card><div id=distBar style='background:#f59e0b;color:#000;padding:8px;border-radius:8px;margin-bottom:6px;display:none;font-weight:bold;text-align:center'></div><div style='display:flex;gap:6px;margin-bottom:6px'><input id=mapSearch placeholder='Search' style='flex:1'><button onclick='searchMap()'>بحث</button><button onclick='setSat()'>Sat</button><button onclick='setNorm()'>Map</button><button onclick='clearPts()'>Clear</button></div><div id=mp style='height:70vh;border-radius:10px'></div></div><script>var DS="+dj+";initMap();</script>"
        return h
    if v=='settings':
        us=qall("SELECT phone,username FROM users ORDER BY phone");uh=""
        for u in us: ph=esc(u['phone']);un=esc(u.get('username') or u['phone']);uh+="<div class='card user-card'><div class=avatar>"+esc(un[:1])+"</div><div><b>"+un+"</b><br><small>"+ph+"</small></div></div>"
        h="<div class=card style='max-width:500px;margin:10px auto;text-align:center'><form data-ajax method=post action=/change_pass><input name=newpass type=password required placeholder='new password'><button>Save</button></form></div>"
        h+="<div class=card style='max-width:500px;margin:10px auto;text-align:center'><h3>Add User</h3><form data-ajax method=post action=/add_user><input name=phone required placeholder='user'><input name=password type=password required placeholder='password'><select name=role><option value=tech>tech</option><option value=manager>manager</option></select><button>Add</button></form></div><div class=user-grid>"+uh+"</div>"
        h+="<div class=card style='text-align:center;border:2px solid #25D366;max-width:500px;margin:10px auto'><h3>Technical Support - الدعم الفني</h3><div dir=ltr>+905345851045</div><a href='https://wa.me/905345851045' target=_blank style='display:inline-block;background:#25D366;color:#fff;padding:8px 16px;border-radius:20px;text-decoration:none;margin:6px'>WhatsApp</a><br><a href='https://instagram.com/af_20_1999' target=_blank style='display:inline-block;background:#E1306C;color:#fff;padding:8px 16px;border-radius:20px;text-decoration:none'>Instagram</a></div>"
        return h
    return "ok"

def layout(c,v='home'):
    th=dark();bg='#0f172a' if th=='dark' else '#f1f5f9';card='#1e293b' if th=='dark' else '#fff';txt='#fff' if th=='dark' else '#000'
    p="<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><link rel=stylesheet href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'><style>"
    p+="body{margin:0;font-family:sans-serif;background:"+bg+";color:"+txt+"}.top{position:fixed;top:0;left:0;right:0;background:#0f172a;color:#D4AF37;padding:10px;z-index:101;display:flex;align-items:center;justify-content:space-between}.leftb{display:flex;gap:6px}.iconbtn{background:rgba(255,255,255,.15);border:0;color:#fff;padding:6px 10px;border-radius:8px}.menu{position:fixed;top:52px;bottom:0;right:0;width:210px;background:#1e293b;padding:10px;z-index:100;transition:.25s}.menu.hide{transform:translateX(100%)}.menu a{display:block;color:#D4AF37;text-decoration:none;padding:11px;border-radius:8px;font-weight:600}.main{margin-right:220px;margin-top:62px;padding:10px}.main.full{margin-right:0}.card{background:"+card+";padding:10px;border-radius:10px;margin:8px 0}.grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:6px}.user-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}.user-card{display:flex;gap:10px;align-items:center}.avatar{width:32px;height:32px;border-radius:50%;background:#D4AF37;color:#000;display:flex;align-items:center;justify-content:center}.kpi{padding:12px;border-radius:10px;color:#fff;text-align:center}input,select{width:100%;padding:8px;margin:4px 0;border-radius:7px;border:1px solid #ccc;box-sizing:border-box}button{background:#B8860B;color:#fff;border:0;padding:8px 12px;border-radius:7px}#ld{position:fixed;top:60px;left:50%;transform:translateX(-50%);background:#f59e0b;padding:4px 14px;border-radius:20px;display:none;z-index:200}.wa-float{position:fixed;bottom:18px;left:18px;background:#25D366;color:#fff;width:52px;height:52px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:26px;z-index:300;text-decoration:none;box-shadow:0 4px 12px rgba(0,0,0,.3)}"
    p+="</style></head><body data-theme='"+th+"'><div class=top><div style='display:flex;gap:10px;align-items:center'><span style='font-size:22px;cursor:pointer' onclick='toggleMenu()'>☰</span><span style='font-weight:800;letter-spacing:1px'>OMAIA ISP</span></div><div class=leftb><button class=iconbtn onclick=\"fetch('/toggle_lang').then(()=>location.reload())\">EN/AR</button><button class=iconbtn onclick='toggleThemeAjax()'>◐</button><button class=iconbtn onclick=\"loadPage('settings')\">⚙</button></div></div>"
    p+="<div class=menu id=mn><a href=\"javascript:loadPage('home')\">⌂ "+T('home')+"</a><a href=\"javascript:loadPage('ping')\">◉ "+T('ping')+"</a><a href=\"javascript:loadPage('subs')\">◈ "+T('subs')+"</a><a href=\"javascript:loadPage('ledger')\">✎ "+T('ledger')+"</a><a href=\"javascript:loadPage('dishes')\">⬢ "+T('dishes')+"</a><a href=\"javascript:loadPage('towers')\">⬣ "+T('towers')+"</a><a href=\"javascript:loadPage('map')\">◎ "+T('map')+"</a><a href=\"javascript:loadPage('settings')\">⚙ "+T('settings')+"</a><a href=/logout>⎋ "+T('logout')+"</a></div>"
    p+="<div class=main id=main>"+c+"</div><div id=ld>⏳ Loading...</div><a class=wa-float href='https://wa.me/905345851045' target=_blank>✆</a><script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script><script>"
    p+="var curV='"+v+"',mapObj=null,satL=null,normL=null,pts=[],line=null;"
    p+="function toggleMenu(){document.getElementById('mn').classList.toggle('hide');document.getElementById('main').classList.toggle('full')}"
    p+="if(window.innerWidth<700)toggleMenu();"
    p+="window.loadPage=async function(v){curV=v;var l=document.getElementById('ld');l.style.display='block';try{var r=await fetch('/api/page?v='+encodeURIComponent(v),{cache:'no-store'});var t=await r.text();if(t=='login'){location.href='/login';return}document.getElementById('main').innerHTML=t;bindAjax();var s=document.getElementById('main').querySelector('script');if(s){try{eval(s.innerHTML)}catch(e){console.log(e)}} }catch(e){document.getElementById('main').innerHTML='<div class=card>Error loading</div>'}finally{l.style.display='none'}};"
    p+="async function toggleThemeAjax(){await fetch('/toggle_theme_ajax');location.reload()}"
    p+="function setSat(){if(mapObj){mapObj.removeLayer(normL);satL.addTo(mapObj)}}function setNorm(){if(mapObj){mapObj.removeLayer(satL);normL.addTo(mapObj)}}"
    p+="function clearPts(){if(!mapObj)return;pts.forEach(function(x){mapObj.removeLayer(x)});pts=[];if(line){mapObj.removeLayer(line);line=null}var b=document.getElementById('distBar');if(b)b.style.display='none'}"
    p+="function updDist(){if(!mapObj||pts.length<2)return;var d=mapObj.distance(pts[0].getLatLng(),pts[1].getLatLng());var b=document.getElementById('distBar');if(b){b.style.display='block';b.textContent='Distance: '+Math.round(d)+' m'}if(line)mapObj.removeLayer(line);line=L.polyline([pts[0].getLatLng(),pts[1].getLatLng()],{color:'yellow'}).addTo(mapObj)}"
    p+="function searchMap(){if(!mapObj)return;var q=document.getElementById('mapSearch').value.trim().toLowerCase();if(!q)return;if(q.includes(',')){var ps=q.split(',');var la=parseFloat(ps[0]),ln=parseFloat(ps[1]);if(!isNaN(la)){mapObj.setView([la,ln],16);return}}for(var i=0;i<DS.length;i++){if(DS[i].n.toLowerCase().includes(q)||DS[i].ip.includes(q)){mapObj.setView([DS[i].la,DS[i].ln],16);return}}alert('not found')}"
    p+="function initMap(){if(typeof L=='undefined'){setTimeout(initMap,300);return}if(!document.getElementById('mp'))return;if(mapObj){mapObj.remove();mapObj=null;pts=[];line=null}mapObj=L.map('mp',{maxZoom:18});mapObj.setView([35.13,36.75],12);satL=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{maxZoom:18,maxNativeZoom:18});normL=L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:18,maxNativeZoom:18});satL.addTo(mapObj);if(typeof DS!='undefined'){DS.forEach(function(d){L.marker([d.la,d.ln]).addTo(mapObj).bindPopup(d.n+'<br>'+d.ip)})}mapObj.on('click',function(e){if(pts.length>=2)clearPts();var m=L.marker(e.latlng,{draggable:true}).addTo(mapObj);pts.push(m);m.on('drag',updDist);updDist()});setTimeout(function(){mapObj.invalidateSize()},400)}"
    p+="function bindAjax(){document.querySelectorAll('form[data-ajax]').forEach(function(f){f.onsubmit=async function(e){e.preventDefault();await fetch(f.action,{method:'POST',body:new FormData(f)});loadPage(curV)}});document.querySelectorAll('a[data-del]').forEach(function(a){a.onclick=async function(e){e.preventDefault();if(confirm('delete?')){await fetch(a.href);loadPage(curV)}}})};bindAjax();"
    p+="</script></body></html>"
    return p
@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')
@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        uin=request.form.get('userin','').strip();pw=request.form.get('password','');u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
        if u and u['password']==pw:
            session['phone']=u['phone'];return redirect('/dash')
    return """<html><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><style>
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:radial-gradient(circle at 30% 20%,#1e293b,#0f172a);font-family:sans-serif;color:#fff}
.box{background:rgba(255,255,255,.06);backdrop-filter:blur(12px);padding:32px;border-radius:20px;width:92%;max-width:360px;text-align:center;border:1px solid #D4AF37}
.logo{font-size:28px;font-weight:900;color:#D4AF37;letter-spacing:3px;margin-bottom:6px}
input{width:100%;padding:12px;margin:8px 0;border-radius:10px;border:1px solid #444;background:#0f172a;color:#fff;box-sizing:border-box}
button{width:100%;background:linear-gradient(135deg,#D4AF37,#B8860B);color:#000;font-weight:800;padding:12px;border:0;border-radius:10px;cursor:pointer}
</style></head><body><div class=box><div class=logo>OMAIA ISP</div><div style='opacity:.7;margin-bottom:12px'>Golden Network Management</div><form method=post><input name=userin placeholder='Username' required><input name=password type=password placeholder='Password' required><button>LOGIN</button></form></div></body></html>"""
@app.route('/logout')
def lo(): session.clear();return redirect('/login')
@app.route('/dash')
def dash():
    if not session.get('phone'): return redirect('/login')
    return layout(page_content(request.args.get('v','home')),request.args.get('v','home'))
@app.route('/api/page')
def ap():
    if not session.get('phone'): return "login"
    return page_content(request.args.get('v','home'))
@app.route('/add_sub',methods=['POST'])
def a1(): qexec("INSERT INTO subs(name,phone) VALUES(?,?)",(request.form.get('name',''),''));return "ok"
@app.route('/del_sub/<int:i>')
def a4(i):
    if not can_edit(): return "no"
    qexec("DELETE FROM subs WHERE id=?",(i,));return "ok"
@app.route('/add_ledger',methods=['POST'])
def b1():
    f=request.form;qexec("INSERT INTO ledger(sub_id,amount,typ,dt,note,currency,name) VALUES(?,?,?,?,?,?,?)",(0,fnum(f.get('amount')),'دين',datetime.datetime.now().isoformat(),f.get('note',''),f.get('currency','SYP'),f.get('name','')));return "ok"
@app.route('/add_dish',methods=['POST'])
def c1():
    f=request.form;qexec("INSERT INTO dish_ips(ip,location,lat,lng,dish_name,tower_name) VALUES(?,?,?,?,?,?)",(f.get('ip',''),'',fnum(f.get('lat')),fnum(f.get('lng')),f.get('dish_name',''),''));return "ok"
@app.route('/del_dish/<int:i>')
def c2(i):
    if not can_edit(): return "no"
    qexec("DELETE FROM dish_ips WHERE id=?",(i,));return "ok"
@app.route('/add_tower',methods=['POST'])
def d1(): f=request.form;qexec("INSERT INTO towers(name,lat,lng,location) VALUES(?,?,?,?)",(f.get('name',''),fnum(f.get('lat')),fnum(f.get('lng')),f.get('location','')));return "ok"
@app.route('/add_user',methods=['POST'])
def addu():
    if not can_edit(): return "no"
    f=request.form;ph=f.get('phone','').strip();qexec("INSERT INTO users(phone,password,role,username,active) VALUES(?,?,?,?,1)",(ph,f.get('password',''),f.get('role','tech'),ph));return "ok"
@app.route('/change_pass',methods=['POST'])
def e2(): qexec("UPDATE users SET password=? WHERE phone=?",(request.form.get('newpass',''),session.get('phone')));return "ok"
if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
