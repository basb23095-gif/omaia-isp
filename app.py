from flask import Flask, request, redirect, render_template_string, session, Response, jsonify
import os, datetime, io, csv, time, socket
try:
    import psycopg2, psycopg2.extras
except:
    psycopg2 = None
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from colors import get_colors, get_bg_css, get_menu_css, get_logo_html

app = Flask(__name__, static_folder='static')
app.secret_key = os.environ.get("SECRET_KEY", "omia-sec-2026")
_raw_db = os.environ.get("DATABASE_URL", "") or ""
DATABASE_URL = _raw_db.strip().replace("\n","").replace("\r","").replace(" ","").replace("postgresql://","postgres://")
USE_PG = bool(DATABASE_URL.lower().startswith("postgres://") and psycopg2)
_pg=None;_pt=0
SUPPORT="905344851045"
SUPPORT_DISPLAY="+905344851045"

def T(k):
    L={'ar':{'home':'🏠 الرئيسية','subs':'👥 المشتركين','dishes':'📡 الصحون','map':'🗺️ الخريطة','ping':'📶 فحص','towers':'🗼 الأبراج','report':'📊 تقرير','notifs':'🔔 إشعارات','logs':'📝 السجل','settings':'⚙️ الإعدادات','support':'🛠️ دعم','ledger':'📒 الحسابات','logout':'🚪 خروج','menu':'☰ القائمة'}}
    return L.get(session.get('lang','ar'),{}).get(k,k)

def db():
    global _pg,_pt
    if USE_PG:
        if _pg and time.time()-_pt<300:
            try:
                _pg.cursor().execute("SELECT 1");return _pg
            except: pass
        _pg=psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=5)
        _pg.autocommit=True;_pt=time.time();return _pg
    c=sqlite3.connect("omia.db");c.row_factory=sqlite3.Row;return c

def cc(c):
    if not USE_PG:
        try:c.close()
        except:pass

def ex(c,q,a=()):
    if USE_PG:
        cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor);cur.execute(q.replace("?","%s"),a);return cur
    return c.execute(q,a)

def safe_commit(c):
    try:c.commit()
    except:pass

def fnum(v):
    try:return float(v or 0)
    except:return 0

def init():
    c=db()
    ss=["CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,username TEXT,password TEXT,role TEXT,active INT DEFAULT 1)","CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,status TEXT,balance_usd REAL DEFAULT 0,balance_syr REAL DEFAULT 0)","CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,site TEXT,area TEXT,tower TEXT,lat REAL DEFAULT 0,lng REAL DEFAULT 0)","CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,lat REAL,lng REAL,note TEXT)","CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,sub_id INT,date TEXT,usd REAL,syr REAL,type TEXT,note TEXT,by_user TEXT)","CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,msg TEXT,date TEXT,seen INT DEFAULT 0)","CREATE TABLE IF NOT EXISTS login_logs(id INTEGER PRIMARY KEY AUTOINCREMENT,phone TEXT,date TEXT,ip TEXT)"]
    if USE_PG:ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
    if USE_PG:
        cur=c.cursor()
        for s in ss:cur.execute(s)
        cur.execute("SELECT * FROM users WHERE phone='05344851045'")
        if not cur.fetchone():cur.execute("INSERT INTO users(phone,username,password,role,active) VALUES('05344851045','05344851045','admin2024','super',1)")
        for col in ["area TEXT","location TEXT","owner TEXT"]:
            try:cur.execute("ALTER TABLE towers ADD COLUMN "+col)
            except:pass
        cur.close()
    else:
        for s in ss:c.execute(s)
        if not c.execute("SELECT * FROM users WHERE phone='05344851045'").fetchone():c.execute("INSERT INTO users(phone,username,password,role,active) VALUES('05344851045','05344851045','admin2024','super',1)")
        safe_commit(c);cc(c)
init()

def ping_one(ip):
    ip=(ip or '').strip()
    if not ip:return False
    for p in (80,443):
        try:
            s=socket.create_connection((ip,p),timeout=0.7);s.close();return True
        except:continue
    return False

def get_view_html(v,c,role,q=""):
    col=get_colors()
    if v=='home':
        def cnt(t):
            r=ex(c,"SELECT COUNT(*) as c FROM "+t).fetchone()
            return dict(r)['c']
        ns=cnt("subs");nd=cnt("dish_ips")
        today=datetime.date.today().isoformat()
        return "<div class='card' style='text-align:center'><h2>أمية</h2><p>"+today+"</p></div><div class='igrid'><div class='icard' style='background:"+col.get('icon_ip','#333')+"'>📡<br>"+str(nd)+"</div><div class='icard' style='background:"+col.get('icon_active','#333')+"'>👥<br>"+str(ns)+"</div></div>"
    if v=='map':
        ds=[dict(r) for r in ex(c,"SELECT id,location,lat,lng FROM dish_ips WHERE lat!=0 AND lng!=0 LIMIT 500").fetchall()]
        ts=[dict(r) for r in ex(c,"SELECT id,name,lat,lng FROM towers WHERE lat!=0 AND lng!=0 LIMIT 500").fetchall()]
        import json as _js
        ds_j=_js.dumps([{"id":d.get("id"),"n":str(d.get("location","")), "la":float(d.get("lat") or 0),"ln":float(d.get("lng") or 0)} for d in ds if d.get("lat")])
        ts_j=_js.dumps([{"id":t.get("id"),"n":str(t.get("name","")), "la":float(t.get("lat") or 0),"ln":float(t.get("lng") or 0)} for t in ts if t.get("lat")])
        parts=[]
        parts.append('<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>')
        parts.append('<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css"/>')
        parts.append('<div class="card"><h3>🗺️ الخريطة السريعة - حذف وتعديل</h3>')
        parts.append('<div style="display:flex;gap:6px;margin-bottom:6px"><input id="sqm" placeholder="🔍 ابحث..." style="flex:1"><button class="abtn abtn-edit" onclick="searchMap()">بحث</button><button class="abtn abtn-toggle" onclick="myLoc()">📍 موقعي</button></div>')
        parts.append('<div id="mp" style="height:70vh;min-height:480px;border-radius:12px"></div>')
        parts.append('<div id="cd" style="margin-top:6px;font-size:12px;direction:ltr;text-align:center">اضغط على الخريطة للدقة العالية</div></div>')
        parts.append('<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>')
        parts.append('<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>')
        parts.append('<script>')
        parts.append('var m; var dishes='+ds_j+'; var towers='+ts_j+';')
        parts.append('function initMap(){ if(typeof L=="undefined"){setTimeout(initMap,300);return;} m=L.map("mp",{preferCanvas:true}).setView([35.1318,36.7578],12);')
        parts.append('var sat=L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",{maxZoom:19}); sat.addTo(m);')
        parts.append('var cl=L.markerClusterGroup({maxClusterRadius:40});')
        parts.append('dishes.forEach(function(d){ var mk=L.marker([d.la,d.ln]); mk.bindPopup("📡 "+d.n+"<br><button onclick=\\"delPoint(\\'/del_dish/"+\'"+d.id+"\'+\\"\\')\\">🗑️ حذف</button> <button onclick=\\"editDish("+d.id+")\\">✏️ تعديل</button>"); cl.addLayer(mk); });')
        parts.append('towers.forEach(function(t){ var mk=L.circleMarker([t.la,t.ln],{color:"red",radius:9}); mk.bindPopup("🗼 "+t.n+"<br><button onclick=\\"delPoint(\\'/del_tower/"+\'"+t.id+"\'+\\"\\')\\">🗑️ حذف</button> <button onclick=\\"editTower("+t.id+")\\">✏️ تعديل</button>"); cl.addLayer(mk); });')
        parts.append('m.addLayer(cl); setTimeout(function(){m.invalidateSize();},400); }')
        parts.append('function delPoint(u){ if(!confirm("حذف؟"))return; fetch(u,{headers:{"X-Requested-With":"fetch"}}).then(function(){loadView("map",true);}); }')
        parts.append('function editDish(id){ var n=prompt("اسم جديد:"); if(n==null)return; fetch("/api/edit_point",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({t:"dish",id:id,name:n})}).then(function(){loadView("map",true);}); }')
        parts.append('function editTower(id){ var n=prompt("اسم جديد:"); if(n==null)return; fetch("/api/edit_point",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({t:"tower",id:id,name:n})}).then(function(){loadView("map",true);}); }')
        parts.append('function searchMap(){ var q=document.getElementById("sqm").value; fetch("https://nominatim.openstreetmap.org/search?format=json&q="+encodeURIComponent(q)).then(function(r){return r.json();}).then(function(d){ if(d[0]) m.setView([d[0].lat,d[0].lon],16); }); }')
        parts.append('function myLoc(){ navigator.geolocation.getCurrentPosition(function(p){ m.setView([p.coords.latitude,p.coords.longitude],17); L.marker([p.coords.latitude,p.coords.longitude]).addTo(m).bindPopup("📍 أنت هنا ±"+Math.round(p.coords.accuracy)+"م").openPopup(); },function(){alert("فعل GPS");},{enableHighAccuracy:true}); }')
        parts.append('setTimeout(initMap,300);')
        parts.append('</script>')
        return "".join(parts)
    if v=='subs':
        rs=ex(c,"SELECT * FROM subs ORDER BY id DESC LIMIT 50").fetchall()
        tr="".join(['<tr><td>'+str(r['name'])+'</td><td>'+str(r['phone'])+'</td><td><a class="abtn abtn-del" href="#" onclick="return ajaxDel(\'/del_sub/'+str(r['id'])+'\',\'subs\')">حذف</a></td></tr>' for r in rs])
        return "<div class='card'><form onsubmit=\"return ajaxSubmit(this,'subs')\" method=post action=/add_sub><div class=row2><input name=name placeholder='الاسم' required><input name=phone placeholder='هاتف' required></div><button class='btn-soft' type='submit'>إضافة</button></form></div><div class='card'><table>"+tr+"</table></div>"
    if v=='dishes':
        rs=ex(c,"SELECT * FROM dish_ips ORDER BY id DESC LIMIT 100").fetchall()
        tr="".join(['<tr><td>'+str(dict(r).get('ip',''))+'</td><td>'+str(dict(r).get('location',''))+'</td><td><a class="abtn abtn-del" href="#" onclick="return ajaxDel(\'/del_dish/'+str(dict(r)['id'])+'\',\'dishes\')">حذف</a></td></tr>' for r in rs])
        return "<div class='card'><h3>📡 الصحون</h3><form onsubmit=\"return ajaxSubmit(this,'dishes')\" method=post action=/add_dish><input name=ip placeholder='IP'><input name=location placeholder='اسم'><div class=row2><input name=lat placeholder='Lat' type=number step=any><input name=lng placeholder='Lng' type=number step=any></div><button class='btn-soft' type='submit'>إضافة</button></form></div><div class='card'><table>"+tr+"</table></div>"
    if v=='towers':
        rs=ex(c,"SELECT * FROM towers ORDER BY id DESC LIMIT 100").fetchall()
        tr="".join(['<tr><td>'+str(dict(r).get('name',''))+'</td><td><a class="abtn abtn-del" href="#" onclick="return ajaxDel(\'/del_tower/'+str(dict(r)['id'])+'\',\'towers\')">حذف</a></td></tr>' for r in rs])
        return "<div class='card'><h3>🗼 برج</h3><form onsubmit=\"return ajaxSubmit(this,'towers')\" method=post action=/add_tower><input name=name placeholder='اسم' required><div class=row2><input name=lat placeholder='Lat' type=number step=any required><input name=lng placeholder='Lng' type=number step=any required></div><button class='btn-soft' type='submit'>حفظ</button></form></div><div class='card'><table>"+tr+"</table></div>"
    if v=='ping':
        rs=ex(c,"SELECT * FROM dish_ips ORDER BY id DESC LIMIT 10").fetchall()
        ips=[dict(r) for r in rs]
        with ThreadPoolExecutor(max_workers=5) as exx:results=list(exx.map(ping_one,[d.get('ip','') for d in ips]))
        tr="".join([ "<tr><td>" + ("🟢" if ok else "🔴") + "</td><td>"+d.get('ip','')+"</td></tr>" for d,ok in zip(ips,results)])
        return "<div class='card'><h3>📶 فحص</h3><button class='btn-soft' onclick=\"loadView('ping',true)\">🔄 فحص</button></div><div class='card'><table>"+tr+"</table></div>"
    return "<div class='card'>"+v+"</div>"

def base_html(content,curview):
    col=get_colors();role=session.get('role','tech')
    h="""<!DOCTYPE html><html dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OMAIA</title><style>"""
    h+=get_menu_css()
    h+="""*{box-sizing:border-box}body{margin:0;font-family:'Segoe UI';"""
    h+=get_bg_css()
    h+=""";color:"""+col['text']+"""}.card{padding:12px;border-radius:16px;margin:8px 0;background:"""+col['card_bg']+"""}.abtn{padding:7px 13px;border-radius:12px;color:#fff;text-decoration:none;display:inline-block}.abtn-edit{background:#06b6d4}.abtn-del{background:#ef4444}.abtn-toggle{background:#f59e0b}.mn{padding:68px 8px 20px;max-width:1400px;margin:auto} input{width:100%;padding:10px;margin:5px 0;border-radius:10px}.btn-soft{padding:11px;width:100%;border:none;border-radius:12px;background:"""+col['main']+""";color:#fff}.row2{display:grid;grid-template-columns:1fr 1fr;gap:8px}.sb{position:fixed;top:64px;right:8px;width:240px;z-index:1003}.sb.hide{display:none} </style></head><body>"""
    h+='<div class="sb hide" id="sb"><a href="#" data-v="home">🏠</a><a href="#" data-v="map">🗺️</a><a href="#" data-v="subs">👥</a><a href="#" data-v="dishes">📡</a><a href="#" data-v="towers">🗼</a><a href="/logout">🚪</a></div>'
    h+='<div class="mn" id="mn">'+content+'</div>'
    h+='<script>let cache={},sb=document.getElementById("sb"),mn=document.getElementById("mn");function loadView(v,force){fetch("/api/view?v="+v,{headers:{"X-Requested-With":"fetch"}}).then(function(r){return r.text();}).then(function(h){mn.innerHTML=h; var sc=mn.querySelectorAll("script"); sc.forEach(function(s){ var n=document.createElement("script"); if(s.src){n.src=s.src;document.head.appendChild(n);} n.textContent=s.textContent; document.body.appendChild(n); }); });} function ajaxSubmit(f,v){fetch(f.action,{method:"POST",body:new FormData(f),headers:{"X-Requested-With":"fetch"}}).then(function(){loadView(v,true);});return false;} function ajaxDel(u,v){if(!confirm("حذف؟"))return false;fetch(u,{headers:{"X-Requested-With":"fetch"}}).then(function(){loadView(v,true);});return false;} document.querySelectorAll("[data-v]").forEach(function(a){a.onclick=function(e){e.preventDefault();loadView(a.dataset.v);};});</script></body></html>'
    return h

@app.route('/api/edit_point',methods=['POST'])
def edit_point():
    d=request.get_json(force=True);c=db()
    try:
        if d.get('t')=='dish':ex(c,"UPDATE dish_ips SET location=? WHERE id=?",(d.get('name',''),int(d.get('id'))))
        else:ex(c,"UPDATE towers SET name=? WHERE id=?",(d.get('name',''),int(d.get('id'))))
        safe_commit(c)
    except:pass
    cc(c);return jsonify(ok=True)

@app.route('/dash')
def dash():
    if not session.get('phone'):return redirect('/login')
    v=request.args.get('view','home');c=db();html=get_view_html(v,c,session.get('role','tech'),request.args.get('q',''));cc(c)
    return render_template_string(base_html(html,v))

@app.route('/api/view')
def apiv():
    if not session.get('phone'):return "no"
    v=request.args.get('v','home');c=db();h=get_view_html(v,c,session.get('role','tech'),"");cc(c);return h

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        i=request.form.get('phone','').strip();p=request.form.get('password','')
        c=db();u=ex(c,"SELECT * FROM users WHERE phone=?",(i,)).fetchone()
        if u and dict(u)['password']==p:
            d=dict(u);session['phone']=d['phone'];session['role']=d['role'];cc(c);return redirect('/dash')
        cc(c)
    return '<form method=post><input name=phone><input name=password type=password><button>دخول</button></form>'

@app.route('/logout')
def lo():session.clear();return redirect('/login')

@app.route('/add_sub',methods=['POST'])
def a1():c=db();ex(c,"INSERT INTO subs(name,phone) VALUES(?,?)",(request.form.get('name',''),request.form.get('phone','')));safe_commit(c);cc(c);return jsonify(ok=True)
@app.route('/del_sub/<int:i>')
def d1(i):c=db();ex(c,"DELETE FROM subs WHERE id=?",(i,));safe_commit(c);cc(c);return jsonify(ok=True)
@app.route('/add_dish',methods=['POST'])
def a2():f=request.form;c=db();ex(c,"INSERT INTO dish_ips(ip,location,lat,lng) VALUES(?,?,?,?)",(f.get('ip',''),f.get('location',''),fnum(f.get('lat')),fnum(f.get('lng'))));safe_commit(c);cc(c);return jsonify(ok=True)
@app.route('/del_dish/<int:i>')
def d2(i):c=db();ex(c,"DELETE FROM dish_ips WHERE id=?",(i,));safe_commit(c);cc(c);return jsonify(ok=True)
@app.route('/add_tower',methods=['POST'])
def at():f=request.form;c=db();ex(c,"INSERT INTO towers(name,lat,lng) VALUES(?,?,?)",(f.get('name',''),fnum(f.get('lat')),fnum(f.get('lng'))));safe_commit(c);cc(c);return jsonify(ok=True)
@app.route('/del_tower/<int:i>')
def dt(i):c=db();ex(c,"DELETE FROM towers WHERE id=?",(i,));safe_commit(c);cc(c);return jsonify(ok=True)
@app.route('/debug_db')
def debug_db():return "USE_PG="+str(USE_PG)+" LEN="+str(len(DATABASE_URL))
@app.route('/')
def ix():return redirect('/dash') if session.get('phone') else redirect('/login')
if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
