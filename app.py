from flask import Flask, request, redirect, session
import os, json
try:
    import psycopg2, psycopg2.extras
except: psycopg2=None
import sqlite3
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY","omia-sec-2026")
DATABASE_URL=os.environ.get("DATABASE_URL","").strip().replace("postgresql://","postgres://")
USE_PG=bool(DATABASE_URL.startswith("postgres://") and psycopg2)
_pg=None
def db():
    global _pg
    if USE_PG:
        if _pg:
            try:_pg.cursor().execute("SELECT 1");return _pg
            except:pass
        _pg=psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=5);_pg.autocommit=True;return _pg
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
    ss=["CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,active INT DEFAULT 1)","CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,lat REAL,lng REAL)","CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,lat REAL,lng REAL)"]
    if USE_PG:ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
    if USE_PG:
        cur=c.cursor()
        for s in ss:cur.execute(s)
        cur.execute("SELECT * FROM users WHERE phone='05344851045'")
        if not cur.fetchone():cur.execute("INSERT INTO users(phone,password,role,active) VALUES('05344851045','admin2024','super',1)")
        cur.close()
    else:
        for s in ss:c.execute(s)
        if not c.execute("SELECT * FROM users WHERE phone='05344851045'").fetchone():c.execute("INSERT INTO users(phone,password,role,active) VALUES('05344851045','admin2024','super',1)")
        safe_commit(c);cc(c)
init()
def can_edit():
    return session.get('role','tech') in ('super','admin','manager')
def get_map(c):
    ds=[dict(r) for r in ex(c,"SELECT location,lat,lng FROM dish_ips WHERE lat!=0 LIMIT 1000").fetchall()]
    ts=[dict(r) for r in ex(c,"SELECT name,lat,lng FROM towers WHERE lat!=0 LIMIT 1000").fetchall()]
    ds_j=json.dumps([{"la":float(d.get("lat") or 0),"ln":float(d.get("lng") or 0),"n":str(d.get("location",""))} for d in ds if d.get("lat")],ensure_ascii=False)
    ts_j=json.dumps([{"la":float(t.get("lat") or 0),"ln":float(t.get("lng") or 0),"n":str(t.get("name",""))} for t in ts if t.get("lat")],ensure_ascii=False)
    h='<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/><div class="card"><h3>الخريطة نار 🔥</h3><div style="display:flex;gap:6px"><input id="sqm" placeholder="بحث..." style="flex:1"><button onclick="searchMap()">بحث</button><button onclick="myLoc()">📍 موقعي</button></div><div id="mp" style="height:70vh"></div><div id="cd"></div></div>'
    h+='<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>var DS='+ds_j+';var TS='+ts_j+';function im(){if(typeof L=="undefined"){setTimeout(im,200);return;}var m=L.map("mp",{preferCanvas:true}).setView([35.13,36.75],12);L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",{maxZoom:19}).addTo(m);DS.forEach(function(d){L.marker([d.la,d.ln]).addTo(m).bindPopup(d.n);});TS.forEach(function(t){L.circleMarker([t.la,t.ln],{color:"red",radius:8}).addTo(m).bindPopup(t.n);});m.on("click",function(e){document.getElementById("cd").innerHTML=e.latlng.lat.toFixed(6)+","+e.latlng.lng.toFixed(6);});window.searchMap=function(){var q=document.getElementById("sqm").value;fetch("https://nominatim.openstreetmap.org/search?format=json&q="+encodeURIComponent(q)).then(function(r){return r.json();}).then(function(d){if(d[0])m.setView([d[0].lat,d[0].lon],15);});};window.myLoc=function(){navigator.geolocation.getCurrentPosition(function(p){m.setView([p.coords.latitude,p.coords.longitude],16);L.marker([p.coords.latitude,p.coords.longitude]).addTo(m).bindPopup("دقة "+Math.round(p.coords.accuracy)+"م").openPopup();},null,{enableHighAccuracy:true});};setTimeout(function(){m.invalidateSize()},300);}setTimeout(im,200);</script>'
    return h
def base(cn):
    r=session.get('role','tech')
    return '<html dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0;padding:50px 8px;font-family:sans-serif}.card{border:1px solid #ddd;padding:10px;border-radius:10px;margin:8px 0}input{padding:8px;width:100%;margin:4px 0;box-sizing:border-box}</style></head><body><a href="/dash?v=home">رئيسية</a> | <a href="/dash?v=map">خريطة</a> | <a href="/dash?v=dishes">صحون</a> | <a href="/dash?v=towers">ابراج</a> ('+r+') <a href="/logout">خروج</a><div>'+cn+'</div></body></html>'
@app.route('/')
def ix():return redirect('/dash') if session.get('phone') else redirect('/login')
@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        c=db();u=ex(c,"SELECT * FROM users WHERE phone=?",(request.form.get('phone','').strip(),)).fetchone()
        if u and dict(u)['password']==request.form.get('password',''):
            d=dict(u);session['phone']=d['phone'];session['role']=d.get('role','tech');cc(c);return redirect('/dash')
        cc(c)
    return '<html dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body style="display:flex;align-items:center;justify-content:center;height:100vh;font-family:sans-serif;margin:0"><div style="border:1px solid #ddd;padding:20px;border-radius:12px;width:300px;text-align:center"><h3>OMAIA ISP</h3><form method="post" autocomplete="on"><input name="phone" placeholder="رقم الهاتف" required dir="ltr" autocomplete="username" style="width:100%;padding:10px;margin:6px 0;box-sizing:border-box"><input name="password" type="password" placeholder="كلمة السر" required autocomplete="current-password" style="width:100%;padding:10px;margin:6px 0;box-sizing:border-box"><label style="font-size:12px"><input type="checkbox" checked style="width:auto"> حفظ كلمة السر</label><br><br><button style="width:100%;padding:12px;background:#2563eb;color:#fff;border:none;border-radius:8px">دخول</button></form></div></body></html>'
@app.route('/logout')
def lo():session.clear();return redirect('/login')
@app.route('/dash')
def dash():
    if not session.get('phone'):return redirect('/login')
    v=request.args.get('v','home');c=db();edit=can_edit()
    if v=='map':h=get_map(c)
    elif v=='dishes':
        rs=ex(c,"SELECT * FROM dish_ips ORDER BY id DESC LIMIT 100").fetchall();h='<div class=card><form method=post action="/add_dish"><input name=ip placeholder=IP><input name=location placeholder=اسم><input name=lat placeholder=lat><input name=lng placeholder=lng><button>اضافة</button></form></div>'
        for r in rs:
            dr=dict(r);delb=' <a href="/del_dish/'+str(dr['id'])+'">حذف</a>' if edit else ' <small>عرض فقط</small>'
            h+='<div class=card>'+str(dr.get('ip',''))+' '+str(dr.get('location',''))+delb+'</div>'
    elif v=='towers':
        rs=ex(c,"SELECT * FROM towers ORDER BY id DESC LIMIT 100").fetchall();h='<div class=card><form method=post action="/add_tower"><input name=name placeholder=اسم><input name=lat placeholder=lat><input name=lng placeholder=lng><button>اضافة</button></form></div>'
        for r in rs:
            dr=dict(r);delb=' <a href="/del_tower/'+str(dr['id'])+'">حذف</a>' if edit else ''
            h+='<div class=card>'+str(dr.get('name',''))+delb+'</div>'
    else:h='<div class=card>اهلا '+session.get('phone','')+' صلاحيتك: '+session.get('role','')+'</div>'
    cc(c);return base(h)
@app.route('/add_dish',methods=['POST'])
def ad():
    f=request.form;c=db();ex(c,"INSERT INTO dish_ips(ip,location,lat,lng) VALUES(?,?,?,?)",(f.get('ip',''),f.get('location',''),fnum(f.get('lat')),fnum(f.get('lng'))));safe_commit(c);cc(c);return redirect('/dash?v=dishes')
@app.route('/del_dish/<int:i>')
def dd(i):
    if not can_edit():return "ممنوع للفني",403
    c=db();ex(c,"DELETE FROM dish_ips WHERE id=?",(i,));safe_commit(c);cc(c);return redirect('/dash?v=dishes')
@app.route('/add_tower',methods=['POST'])
def atw():
    f=request.form;c=db();ex(c,"INSERT INTO towers(name,lat,lng) VALUES(?,?,?)",(f.get('name',''),fnum(f.get('lat')),fnum(f.get('lng'))));safe_commit(c);cc(c);return redirect('/dash?v=towers')
@app.route('/del_tower/<int:i>')
def dtw(i):
    if not can_edit():return "ممنوع للفني",403
    c=db();ex(c,"DELETE FROM towers WHERE id=?",(i,));safe_commit(c);cc(c);return redirect('/dash?v=towers')
@app.route('/debug_db')
def dbg():return 'USE_PG='+str(USE_PG)
if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
