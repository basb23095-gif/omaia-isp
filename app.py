from flask import Flask, request, redirect, session, jsonify
import os, datetime, json, html, subprocess, platform
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
    ss=["CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,active INT DEFAULT 1)","CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,active INT DEFAULT 1)","CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,sub_id INT,amount REAL,typ TEXT,dt TEXT,note TEXT)","CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,lat REAL DEFAULT 0,lng REAL DEFAULT 0,dish_name TEXT,tower_name TEXT)","CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,lat REAL,lng REAL)"]
    if USE_PG: ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
    for s in ss: qexec(s)
    try: qexec("ALTER TABLE users ADD COLUMN username TEXT")
    except: pass
    if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username,active) VALUES(?,?,?,?,?)",('05344851045','admin2024','manager','admin',1))
init()
def me(): return qone("SELECT * FROM users WHERE phone=?",(session.get('phone'),))
def can_edit():
    m=me(); return not (m and m.get('role')=='tech')
def dark(): return session.get('theme','light')
@app.route('/api/ping')
def api_ping():
    ip=request.args.get('ip','').strip()
    if not ip: return jsonify(ok=False,out='no ip')
    try:
        w=platform.system().lower()=='windows'
        cmd=['ping','-n','4',ip] if w else ['ping','-c','4','-W','2',ip]
        o=subprocess.run(cmd,capture_output=True,text=True,timeout=10)
        return jsonify(ok=True,out=((o.stdout or '')+(o.stderr or ''))[:2000])
    except Exception as e: return jsonify(ok=False,out=str(e))
@app.route('/toggle_lang')
def tl(): session['lang']='en' if session.get('lang','ar')=='ar' else 'ar';return "ok"
@app.route('/toggle_theme_ajax')
def tt(): session['theme']='light' if dark()=='dark' else 'dark';return "ok"
def page_content(v):
    h=""; dis="" if can_edit() else "style='opacity:.35;pointer-events:none'"
    if v=='home':
        ns=(qone("SELECT COUNT(*) c FROM subs") or {}).get('c',0);nd=(qone("SELECT COUNT(*) c FROM dish_ips") or {}).get('c',0)
        h="<div class=grid><div class=kpi style='background:#2563eb'>👥<br>"+str(ns)+"</div><div class=kpi style='background:#16a34a'>📡<br>"+str(nd)+"</div></div><div class=card>مرحبا "+esc(session.get('phone'))+"</div>"
        h+='<div class=card><h3>📶 Ping</h3><div style="display:flex;gap:6px"><input id=ping_ip placeholder="IP"><button onclick="doPing()">Ping</button></div><pre id=ping_out style="background:#000;color:#0f0;padding:8px;border-radius:8px"></pre></div><script>async function doPing(){var i=document.getElementById("ping_ip").value;document.getElementById("ping_out").textContent="...";var r=await fetch("/api/ping?ip="+encodeURIComponent(i));var j=await r.json();document.getElementById("ping_out").textContent=j.out}</script>'
        return h
    if v=='ping': return '<div class=card><h3>📶 Ping</h3><div style="display:flex;gap:6px"><input id=ping_ip2 placeholder="8.8.8.8"><button onclick="doPing2()">Ping</button></div><pre id=ping_out2 style="background:#000;color:#0f0;padding:8px;border-radius:8px;min-height:100px"></pre></div><script>async function doPing2(){var i=document.getElementById("ping_ip2").value;document.getElementById("ping_out2").textContent="...";var r=await fetch("/api/ping?ip="+encodeURIComponent(i));var j=await r.json();document.getElementById("ping_out2").textContent=j.out}</script>'
    if v=='subs':
        rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 100")
        h="<div class=card><h3>👥 مشتركين</h3><form data-ajax method=post action=/add_sub><input name=name required placeholder='الاسم'><button>اضافة</button></form></div>"
        for r in rs: h+="<div class=card>"+esc(r['name'])+" <a href=/del_sub/"+str(r['id'])+" data-del "+dis+" style='color:red'>🗑️</a></div>"
        return h
    if v=='dishes':
        rs=qall("SELECT * FROM dish_ips ORDER BY id DESC LIMIT 200")
        h="<div class=card><h3>📡 صحون</h3><form data-ajax method=post action=/add_dish><input name=dish_name required placeholder='اسم صحن'><input name=ip required placeholder='IP'><button>اضافة</button></form></div><div class=grid2>"
        for r in rs:
            ip=esc(r['ip']);h+="<div class='card small'><b>"+esc(r.get('dish_name') or '')+"</b> "+ip+"<br><button style='padding:4px;font-size:11px' onclick='fetch(\"/api/ping?ip="+ip+"\").then(r=>r.json()).then(j=>alert(j.out.slice(0,500)))'>Ping</button> <a href=/del_dish/"+str(r['id'])+" data-del "+dis+" style='color:red'>🗑️</a></div>"
        return h+"</div>"
    if v=='towers':
        rs=qall("SELECT * FROM towers ORDER BY id DESC LIMIT 100")
        h="<div class=card><h3>🗼 ابراج</h3><form data-ajax method=post action=/add_tower><input name=name required placeholder='اسم'><button>اضافة</button></form></div>"
        for r in rs: h+="<div class=card>"+esc(r['name'])+"</div>"
        return h
    if v=='ledger':
        rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 100")
        h="<div class=card><h3>📒 دفتر</h3><form data-ajax method=post action=/add_ledger><input name=amount type=number step=0.01 required placeholder='مبلغ'><input name=note placeholder='ملاحظة'><button>اضافة</button></form></div>"
        for r in rs: h+="<div class=card>"+str(r.get('amount',0))+" "+esc(r.get('note',''))+"</div>"
        return h
    if v=='map':
        ds=qall("SELECT lat,lng,dish_name,ip FROM dish_ips WHERE lat!=0 LIMIT 500");arr=[]
        for d in ds:
            try:
                if d.get("lat"): arr.append({"la":float(d.get("lat") or 0),"ln":float(d.get("lng") or 0),"n":str(d.get("dish_name","")),"ip":str(d.get("ip",""))})
            except: pass
        dj=json.dumps(arr).replace("</","<\\/")
        h="<div class=card><div id=distBar style='background:#f59e0b;color:#000;padding:8px;border-radius:8px;margin-bottom:6px;display:none;font-weight:bold;text-align:center'></div><div style='display:flex;gap:6px;margin-bottom:6px'><input id=mapSearch placeholder='🔍 اسم نقطة او احداثية' style='flex:1'><button onclick='searchMap()'>بحث</button><button onclick='setSat()'>🛰️</button><button onclick='setNorm()'>🗺️</button><button onclick='clearPts()'>🧹</button></div><div id=mp style='height:70vh;border-radius:10px'></div><div style='font-size:12px;text-align:center'>اضغط نقطة - اضغط تانية للمسافة - اسحب لتحديث</div></div><script>var DS="+dj+";initMap();</script>"
        return h
    if v=='settings':
        us=qall("SELECT phone,username FROM users ORDER BY phone");uh=""
        for u in us: ph=esc(u['phone']);un=esc(u.get('username') or u['phone']);uh+="<div class='card user-card'><div class=avatar>"+esc(un[:1])+"</div><div><b>"+un+"</b><br><small>"+ph+"</small></div></div>"
        h="<div class=card style='max-width:500px;margin:10px auto;text-align:center'><form data-ajax method=post action=/change_pass><input name=newpass type=password required placeholder='كلمة جديدة' style='text-align:center;max-width:250px'><button>💾 حفظ</button></form></div>"
        h+="<div class=card style='max-width:500px;margin:10px auto;text-align:center'><h3>➕ اضافة يوزر</h3><form data-ajax method=post action=/add_user><div style='display:grid;grid-template-columns:1fr 1fr;gap:8px;max-width:400px;margin:0 auto'><input name=phone required placeholder='اضافة يوزر' style='text-align:center'><input name=password type=password required placeholder='password' style='text-align:center'></div><select name=role style='max-width:200px;margin:8px auto'><option value=tech>فني</option><option value=manager>مدير</option></select><button>اضافة</button></form></div><div class=user-grid>"+uh+"</div>"
        h+="<div class=card style='text-align:center;border:2px solid #25D366;max-width:500px;margin:10px auto'><h3>🛠️ دعم فني</h3><div dir=ltr>+905345851045</div><a href='https://wa.me/905345851045' target=_blank style='display:inline-block;background:#25D366;color:#fff;padding:8px 16px;border-radius:20px;text-decoration:none;margin:6px'>💬 واتساب</a><br><a href='https://instagram.com/af_20_1999' target=_blank style='display:inline-block;background:#E1306C;color:#fff;padding:8px 16px;border-radius:20px;text-decoration:none'>📸 انستغرام</a></div>"
        return h
    return "ok"
def layout(c,v='home'):
    th=dark();bg='#0f172a' if th=='dark' else '#f1f5f9';card='#1e293b' if th=='dark' else '#fff';txt='#fff' if th=='dark' else '#000'
    p="<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><link rel=stylesheet href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'><style>"
    p+="body{margin:0;font-family:sans-serif;background:"+bg+";color:"+txt+"}.top{position:fixed;top:0;left:0;right:0;background:#0f172a;color:#fff;padding:10px;z-index:101;display:flex;align-items:center;justify-content:space-between}.leftb{display:flex;gap:6px}.iconbtn{background:rgba(255,255,255,.15);border:0;color:#fff;padding:6px 10px;border-radius:8px}.menu{position:fixed;top:52px;bottom:0;right:0;width:210px;background:#1e293b;padding:10px;z-index:100;transition:.25s}.menu.hide{transform:translateX(100%)}.menu a{display:block;color:#fff;text-decoration:none;padding:11px;border-radius:8px}.main{margin-right:220px;margin-top:62px;padding:10px}.main.full{margin-right:0}.card{background:"+card+";padding:10px;border-radius:10px;margin:8px 0}.grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:6px}.user-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}.user-card{display:flex;gap:10px;align-items:center}.avatar{width:32px;height:32px;border-radius:50%;background:#2563eb;color:#fff;display:flex;align-items:center;justify-content:center}.kpi{padding:12px;border-radius:10px;color:#fff;text-align:center}input,select{width:100%;padding:8px;margin:4px 0;border-radius:7px;border:1px solid #ccc;box-sizing:border-box}button{background:#2563eb;color:#fff;border:0;padding:8px 12px;border-radius:7px}#ld{position:fixed;top:60px;left:50%;transform:translateX(-50%);background:#f59e0b;padding:4px 14px;border-radius:20px;display:none;z-index:200}"
    p+="</style></head><body data-theme='"+th+"'><div class=top><div style='display:flex;gap:10px;align-items:center'><span style='font-size:22px;cursor:pointer' onclick='toggleMenu()'>☰</span><span>📡 أوميا</span></div><div class=leftb><button class=iconbtn onclick=\"fetch('/toggle_lang').then(()=>location.reload())\">🌐</button><button class=iconbtn onclick='toggleThemeAjax()'>🌙/☀️</button><button class=iconbtn onclick=\"loadPage('settings')\">⚙️</button></div></div>"
    p+="<div class=menu id=mn><a href=\"javascript:loadPage('home')\">🏠 الرئيسية</a><a href=\"javascript:loadPage('ping')\">📶 بينغ</a><a href=\"javascript:loadPage('subs')\">👥 مشتركين</a><a href=\"javascript:loadPage('ledger')\">📒 دفتر</a><a href=\"javascript:loadPage('dishes')\">📡 صحون</a><a href=\"javascript:loadPage('towers')\">🗼 ابراج</a><a href=\"javascript:loadPage('map')\">🗺️ خريطة</a><a href=\"javascript:loadPage('settings')\">⚙️ اعدادات</a><a href=/logout>🚪 خروج</a></div>"
    p+="<div class=main id=main>"+c+"</div><div id=ld>⏳ جاري التحميل...</div><script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script><script>"
    p+="var curV='"+v+"',mapObj=null,satL=null,normL=null,pts=[],line=null;"
    p+="function toggleMenu(){document.getElementById('mn').classList.toggle('hide');document.getElementById('main').classList.toggle('full')}"
    p+="if(window.innerWidth<700)toggleMenu();"
    p+="window.loadPage=async function(v){curV=v;var l=document.getElementById('ld');l.style.display='block';try{var r=await fetch('/api/page?v='+encodeURIComponent(v),{cache:'no-store'});var t=await r.text();document.getElementById('main').innerHTML=t;bindAjax();var s=document.getElementById('main').querySelector('script');if(s){try{eval(s.innerHTML)}catch(e){}}}catch(e){}setTimeout(function(){l.style.display='none'},80)};"
    p+="async function toggleThemeAjax(){await fetch('/toggle_theme_ajax');var b=document.body;if(b.dataset.theme=='dark'){b.dataset.theme='light';b.style.background='#f1f5f9';b.style.color='#000'}else{b.dataset.theme='dark';b.style.background='#0f172a';b.style.color='#fff'}}"
    p+="function setSat(){if(mapObj){mapObj.removeLayer(normL);satL.addTo(mapObj)}}function setNorm(){if(mapObj){mapObj.removeLayer(satL);normL.addTo(mapObj)}}"
    p+="function clearPts(){if(!mapObj)return;pts.forEach(function(x){mapObj.removeLayer(x)});pts=[];if(line){mapObj.removeLayer(line);line=null}var b=document.getElementById('distBar');if(b)b.style.display='none'}"
    p+="function updDist(){if(!mapObj||pts.length<2)return;var d=mapObj.distance(pts[0].getLatLng(),pts[1].getLatLng());var b=document.getElementById('distBar');if(b){b.style.display='block';b.textContent='📏 المسافة: '+Math.round(d)+' متر'}if(line)mapObj.removeLayer(line);line=L.polyline([pts[0].getLatLng(),pts[1].getLatLng()],{color:'yellow'}).addTo(mapObj)}"
    p+="function searchMap(){if(!mapObj)return;var q=document.getElementById('mapSearch').value.trim().toLowerCase();if(!q)return;if(q.includes(',')){var ps=q.split(',');var la=parseFloat(ps[0]),ln=parseFloat(ps[1]);if(!isNaN(la)){mapObj.setView([la,ln],17);return}}for(var i=0;i<DS.length;i++){if(DS[i].n.toLowerCase().includes(q)||DS[i].ip.includes(q)){mapObj.setView([DS[i].la,DS[i].ln],17);return}}alert('ما لقيت')}"
    p+="function initMap(){if(typeof L=='undefined'){setTimeout(initMap,300);return}if(!document.getElementById('mp'))return;if(mapObj){mapObj.remove();mapObj=null;pts=[];line=null}mapObj=L.map('mp');mapObj.setView([35.13,36.75],12);satL=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{maxZoom:19});normL=L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19});satL.addTo(mapObj);if(typeof DS!='undefined'){DS.forEach(function(d){L.marker([d.la,d.ln]).addTo(mapObj).bindPopup(d.n+'<br>'+d.ip)})}mapObj.on('contextmenu',function(e){e.originalEvent.preventDefault();return false});mapObj.on('click',function(e){if(pts.length>=2)clearPts();var m=L.marker(e.latlng,{draggable:true}).addTo(mapObj);pts.push(m);m.on('drag',updDist);updDist()});setTimeout(function(){mapObj.invalidateSize()},400)}"
    p+="function bindAjax(){document.querySelectorAll('form[data-ajax]').forEach(function(f){f.onsubmit=async function(e){e.preventDefault();await fetch(f.action,{method:'POST',body:new FormData(f)});loadPage(curV)}});document.querySelectorAll('a[data-del]').forEach(function(a){a.onclick=async function(e){e.preventDefault();if(confirm('حذف؟')){await fetch(a.href);loadPage(curV)}}})};bindAjax();"
    p+="let sY=0,pl=false;document.addEventListener('touchstart',function(e){if(window.scrollY===0){sY=e.touches[0].clientY;pl=true}},{passive:true});document.addEventListener('touchmove',function(e){if(!pl)return;if(e.touches[0].clientY-sY>90){pl=false;location.reload()}},{passive:true});document.addEventListener('touchend',function(){pl=false});"
    p+="</script></body></html>"
    return p
@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')
@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        uin=request.form.get('userin','').strip();pw=request.form.get('password','');u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
        if u and u['password']==pw:
            session['phone']=u['phone'];r=redirect('/dash')
            if request.form.get('remember'): r.set_cookie('remember_user',uin,max_age=30*24*3600)
            return r
    sv=request.cookies.get('remember_user','')
    return "<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><style>body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#0f172a;font-family:sans-serif}.box{background:#fff;padding:24px;border-radius:18px;width:92%;max-width:340px;text-align:center}input{width:100%;padding:11px;margin:7px 0;border-radius:10px;border:1px solid #ddd;box-sizing:border-box}button{width:100%;background:#2563eb;color:#fff;padding:11px;border:0;border-radius:10px}</style></head><body><div class=box><h3>📡 أوميا</h3><form method=post><input name=userin placeholder='يوزر' value='"+esc(sv)+"' required><input name=password id=pw type=password placeholder='كلمة السر' required><label style='display:flex;gap:6px;justify-content:center;font-size:13px'><input type=checkbox name=remember value=1 style='width:auto'>💾 حفظ كلمة السر</label><button>دخول</button></form></div><script>var s='"+esc(sv)+"';if(s){var p=localStorage.getItem('pw_'+s);if(p)document.getElementById('pw').value=p}document.querySelector('form').onsubmit=function(){var u=document.querySelector('[name=userin]').value;var pw=document.getElementById('pw').value;if(document.querySelector('[name=remember]').checked)localStorage.setItem('pw_'+u,pw)};</script></body></html>"
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
    f=request.form;qexec("INSERT INTO ledger(sub_id,amount,typ,dt,note) VALUES(?,?,?,?,?)",(0,fnum(f.get('amount')),'دين',datetime.datetime.now().isoformat(),f.get('note','')));return "ok"
@app.route('/add_dish',methods=['POST'])
def c1():
    f=request.form;qexec("INSERT INTO dish_ips(ip,location,lat,lng,dish_name,tower_name) VALUES(?,?,?,?,?,?)",(f.get('ip',''),'',fnum(f.get('lat')),fnum(f.get('lng')),f.get('dish_name',''),''));return "ok"
@app.route('/del_dish/<int:i>')
def c2(i):
    if not can_edit(): return "no"
    qexec("DELETE FROM dish_ips WHERE id=?",(i,));return "ok"
@app.route('/add_tower',methods=['POST'])
def d1(): qexec("INSERT INTO towers(name,lat,lng) VALUES(?,?,?)",(request.form.get('name',''),0,0));return "ok"
@app.route('/add_user',methods=['POST'])
def addu():
    if not can_edit(): return "no"
    f=request.form;ph=f.get('phone','').strip();qexec("INSERT INTO users(phone,password,role,username,active) VALUES(?,?,?,?,1)",(ph,f.get('password',''),f.get('role','tech'),ph));return "ok"
@app.route('/change_pass',methods=['POST'])
def e2(): qexec("UPDATE users SET password=? WHERE phone=?",(request.form.get('newpass',''),session.get('phone')));return "ok"
if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
