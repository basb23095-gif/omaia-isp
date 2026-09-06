from flask import Flask, request, redirect, render_template_string, session, jsonify
import os, datetime, time, socket, json
try:
    import psycopg2, psycopg2.extras
except:
    psycopg2 = None
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from colors import get_colors, get_bg_css, get_menu_css, get_logo_html

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "omia-sec-2026")
DATABASE_URL = os.environ.get("DATABASE_URL","").strip().replace("postgresql://","postgres://")
USE_PG = bool(DATABASE_URL.startswith("postgres://") and psycopg2)
_pg=None

def db():
    global _pg
    if USE_PG:
        if _pg:
            try:
                _pg.cursor().execute("SELECT 1");return _pg
            except: pass
        _pg=psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=5)
        _pg.autocommit=True;return _pg
    c=sqlite3.connect("omia.db");c.row_factory=sqlite3.Row;return c

def cc(c):
    if not USE_PG:
        try:c.close()
        except:pass

def ex(c,q,a=()):
    if USE_PG:
        cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(q.replace("?","%s"),a);return cur
    return c.execute(q,a)

def safe_commit(c):
    try:c.commit()
    except:pass

def fnum(v):
    try:return float(v or 0)
    except:return 0

def init():
    c=db()
    ss=[
    "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,active INT DEFAULT 1)",
    "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,lat REAL DEFAULT 0,lng REAL DEFAULT 0)",
    "CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,lat REAL,lng REAL)"
    ]
    if USE_PG: ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
    if USE_PG:
        cur=c.cursor()
        for s in ss: cur.execute(s)
        cur.execute("SELECT * FROM users WHERE phone='05344851045'")
        if not cur.fetchone():
            cur.execute("INSERT INTO users(phone,password,role,active) VALUES('05344851045','admin2024','super',1)")
        cur.close()
    else:
        for s in ss: c.execute(s)
        if not c.execute("SELECT * FROM users WHERE phone='05344851045'").fetchone():
            c.execute("INSERT INTO users(phone,password,role,active) VALUES('05344851045','admin2024','super',1)")
        safe_commit(c);cc(c)
init()

def get_map_html(c):
    ds=[dict(r) for r in ex(c,"SELECT location,lat,lng FROM dish_ips WHERE lat!=0 LIMIT 500").fetchall()]
    ts=[dict(r) for r in ex(c,"SELECT name,lat,lng FROM towers WHERE lat!=0 LIMIT 500").fetchall()]
    ds_j=json.dumps([{"la":float(d.get("lat") or 0),"ln":float(d.get("lng") or 0),"n":str(d.get("location",""))} for d in ds if d.get("lat")], ensure_ascii=False)
    ts_j=json.dumps([{"la":float(t.get("lat") or 0),"ln":float(t.get("lng") or 0),"n":str(t.get("name",""))} for t in ts if t.get("lat")], ensure_ascii=False)
    html = '<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>'
    html += '<div class="card"><h3>🗺️ الخريطة - سريعة ودقيقة</h3><div style="display:flex;gap:6px;margin-bottom:6px"><input id="sqm" placeholder="بحث..." style="flex:1"><button onclick="searchMap()">بحث</button><button onclick="myLoc()">موقعي</button></div><div id="mp" style="height:70vh"></div><div id="cd"></div></div>'
    html += '<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>'
    html += 'var DS=' + ds_j + ';var TS=' + ts_j + ';'
    html += 'function im(){if(typeof L=="undefined"){setTimeout(im,300);return;}'
    html += 'var m=L.map("mp").setView([35.1318,36.7578],12);'
    html += 'L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",{maxZoom:19}).addTo(m);'
    html += 'DS.forEach(function(d){L.marker([d.la,d.ln]).addTo(m).bindPopup(d.n);});'
    html += 'TS.forEach(function(t){L.circleMarker([t.la,t.ln],{color:"red",radius:8}).addTo(m).bindPopup(t.n);});'
    html += 'm.on("click",function(e){document.getElementById("cd").innerHTML=e.latlng.lat.toFixed(6)+","+e.latlng.lng.toFixed(6);});'
    html += 'window.searchMap=function(){var q=document.getElementById("sqm").value;fetch("https://nominatim.openstreetmap.org/search?format=json&q="+encodeURIComponent(q)).then(r=>r.json()).then(d=>{if(d[0])m.setView([d[0].lat,d[0].lon],15)});};'
    html += 'window.myLoc=function(){navigator.geolocation.getCurrentPosition(p=>{var la=p.coords.latitude,ln=p.coords.longitude;m.setView([la,ln],16);L.marker([la,ln]).addTo(m).bindPopup("انت هنا دقة "+Math.round(p.coords.accuracy)+"م").openPopup();},{},{enableHighAccuracy:true});};'
    html += 'setTimeout(function(){m.invalidateSize()},500);}'
    html += 'setTimeout(im,300);</script>'
    return html

def base(cn):
    return '<html dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{font-family:sans-serif;margin:0;padding:60px 8px}.card{border:1px solid #ccc;padding:10px;border-radius:12px;margin:8px 0} input{padding:8px;width:100%;margin:4px 0}</style></head><body><a href="/dash?v=home">رئيسية</a> | <a href="/dash?v=map">خريطة</a> | <a href="/dash?v=dishes">صحون</a> | <a href="/dash?v=towers">ابراج</a> | <a href="/logout">خروج</a><div>'+cn+'</div><script>function loadV(v){fetch("/api/view?v="+v).then(r=>r.text()).then(h=>{document.body.innerHTML=h;});}</script></body></html>'

@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        c=db();u=ex(c,"SELECT * FROM users WHERE phone=?",(request.form.get('phone','').strip(),)).fetchone()
        if u and dict(u)['password']==request.form.get('password',''):
            session['phone']=dict(u)['phone'];cc(c);return redirect('/dash')
        cc(c)
    return '<form method=post><input name=phone placeholder=هاتف><input name=password type=password placeholder=كلمة><button>دخول</button></form>'

@app.route('/logout')
def lo(): session.clear();return redirect('/login')

@app.route('/dash')
def dash():
    if not session.get('phone'): return redirect('/login')
    v=request.args.get('v','home');c=db()
    if v=='map': h=get_map_html(c)
    elif v=='dishes':
        rs=ex(c,"SELECT * FROM dish_ips ORDER BY id DESC LIMIT 50").fetchall()
        h='<div class=card><form method=post action="/add_dish"><input name=ip placeholder=IP><input name=location placeholder=اسم><input name=lat placeholder=lat><input name=lng placeholder=lng><button>اضافة</button></form></div>'
        for r in rs: h+='<div class=card>'+str(dict(r).get('ip',''))+' '+str(dict(r).get('location',''))+' <a href="/del_dish/'+str(dict(r)['id'])+'">حذف</a></div>'
    elif v=='towers':
        rs=ex(c,"SELECT * FROM towers ORDER BY id DESC LIMIT 50").fetchall()
        h='<div class=card><form method=post action="/add_tower"><input name=name placeholder=اسم><input name=lat placeholder=lat><input name=lng placeholder=lng><button>اضافة</button></form></div>'
        for r in rs: h+='<div class=card>'+str(dict(r).get('name',''))+' <a href="/del_tower/'+str(dict(r)['id'])+'">حذف</a></div>'
    else: h='<div class=card><h2>أمية ISP</h2><p>مرحبا '+session.get('phone','')+'</p></div>'
    cc(c);return base(h)

@app.route('/api/view')
def av():
    if not session.get('phone'): return 'no'
    c=db();h=get_map_html(c) if request.args.get('v')=='map' else 'ok';cc(c);return h

@app.route('/add_dish',methods=['POST'])
def ad():
    f=request.form;c=db();ex(c,"INSERT INTO dish_ips(ip,location,lat,lng) VALUES(?,?,?,?)",(f.get('ip',''),f.get('location',''),fnum(f.get('lat')),fnum(f.get('lng'))));safe_commit(c);cc(c);return redirect('/dash?v=dishes')

@app.route('/del_dish/<int:i>')
def dd(i): c=db();ex(c,"DELETE FROM dish_ips WHERE id=?",(i,));safe_commit(c);cc(c);return redirect('/dash?v=dishes')

@app.route('/add_tower',methods=['POST'])
def atw():
    f=request.form;c=db();ex(c,"INSERT INTO towers(name,lat,lng) VALUES(?,?,?)",(f.get('name',''),fnum(f.get('lat')),fnum(f.get('lng'))));safe_commit(c);cc(c);return redirect('/dash?v=towers')

@app.route('/del_tower/<int:i>')
def dtw(i): c=db();ex(c,"DELETE FROM towers WHERE id=?",(i,));safe_commit(c);cc(c);return redirect('/dash?v=towers')

@app.route('/debug_db')
def dbg(): return 'USE_PG='+str(USE_PG)+' LEN='+str(len(DATABASE_URL))

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
