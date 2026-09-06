from flask import Flask, request, redirect, session
import os, datetime, json, sqlite3
try:
 import psycopg2, psycopg2.extras
except: psycopg2=None
from colors import get_colors, get_bg_css, get_logo_html

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "omia-sec-2026")
DATABASE_URL = os.environ.get("DATABASE_URL","").strip().replace("postgresql://","postgres://")
USE_PG = bool(DATABASE_URL.startswith("postgres://") and psycopg2)
_pg=None

def db():
 global _pg
 if USE_PG:
  if _pg:
   try: _pg.cursor().execute("SELECT 1"); return _pg
   except: pass
  _pg=psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=5)
  _pg.autocommit=True; return _pg
 c=sqlite3.connect("omia.db",check_same_thread=False); c.row_factory=sqlite3.Row; return c

def cc(c):
 if not USE_PG:
  try: c.close()
  except: pass

def ex(c,q,a=()):
 if USE_PG:
  cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
  cur.execute(q.replace("?","%s"),a); return cur
 return c.execute(q,a)

def sc(c):
 try: c.commit()
 except: pass

def fnum(v):
 try: return float(v or 0)
 except: return 0

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
  cur.execute("SELECT 1 FROM users WHERE phone='05344851045'")
  if not cur.fetchone():
   cur.execute("INSERT INTO users(phone,password,role,active) VALUES('05344851045','admin2024','super',1)")
  cur.close()
 else:
  for s in ss: c.execute(s)
  if not c.execute("SELECT 1 FROM users WHERE phone='05344851045'").fetchone():
   c.execute("INSERT INTO users(phone,password,role,active) VALUES('05344851045','admin2024','super',1)")
  sc(c); cc(c)
init()

def get_map_html(c):
 ds=[dict(r) for r in ex(c,"SELECT location,lat,lng FROM dish_ips WHERE lat!=0 LIMIT 500").fetchall()]
 ts=[dict(r) for r in ex(c,"SELECT name,lat,lng FROM towers WHERE lat!=0 LIMIT 500").fetchall()]
 ds_j=json.dumps([{"la":float(d.get("lat") or 0),"ln":float(d.get("lng") or 0),"n":str(d.get("location",""))} for d in ds if d.get("lat")], ensure_ascii=False)
 ts_j=json.dumps([{"la":float(t.get("lat") or 0),"ln":float(t.get("lng") or 0),"n":str(t.get("name",""))} for t in ts if t.get("lat")], ensure_ascii=False)
 col=get_colors()
 h=f'<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/><div class="card"><h3>الخريطة</h3><div style="display:flex;gap:6px"><input id="sqm" placeholder="بحث..." style="flex:1"><button onclick="searchMap()" style="background:{col["main"]};color:#fff;border:0;border-radius:8px;padding:8px 12px">بحث</button><button onclick="myLoc()" style="background:{col["main"]};color:#fff;border:0;border-radius:8px;padding:8px 12px">موقعي</button></div><div id="mp" style="height:70vh;border-radius:12px;margin-top:8px"></div><div id="cd" style="margin-top:6px;color:{col["link"]}"></div></div>'
 h+='<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>'
 h+='var DS='+ds_j+';var TS='+ts_j+';'
 h+='function im(){if(typeof L=="undefined"){setTimeout(im,200);return;}'
 h+='var m=L.map("mp").setView([35.1318,36.7578],12);'
 h+='L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",{maxZoom:19}).addTo(m);'
 h+='DS.forEach(function(d){L.marker([d.la,d.ln]).addTo(m).bindPopup(d.n)});'
 h+='TS.forEach(function(t){L.circleMarker([t.la,t.ln],{color:"red",radius:8}).addTo(m).bindPopup(t.n)});'
 h+='m.on("click",function(e){document.getElementById("cd").innerHTML=e.latlng.lat.toFixed(6)+","+e.latlng.lng.toFixed(6)});'
 h+='window.searchMap=function(){var q=document.getElementById("sqm").value;fetch("https://nominatim.openstreetmap.org/search?format=json&q="+encodeURIComponent(q)).then(function(r){return r.json()}).then(function(d){if(d[0])m.setView([d[0].lat,d[0].lon],15)})};'
 h+='window.myLoc=function(){navigator.geolocation.getCurrentPosition(function(p){m.setView([p.coords.latitude,p.coords.longitude],16)})};'
 h+='setTimeout(function(){m.invalidateSize()},400)};setTimeout(im,300)</script>'
 return h

def base(cn):
 col=get_colors()
 return f'<!DOCTYPE html><html dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OMAIA</title><style>body{{margin:0;font-family:sans-serif;color:{col["text"]};{get_bg_css()}}}.top{{position:fixed;top:0;right:0;left:0;height:58px;background:{col["top"]};display:flex;align-items:center;justify-content:space-between;padding:0 12px;z-index:1000}}.top a{{color:{col["link"]};margin:0 6px;text-decoration:none;font-size:14px}}.mn{{padding:70px 10px;max-width:1100px;margin:auto}}.card{{background:{col["card"]};padding:14px;border-radius:14px;margin:10px 0}}input{{width:100%;padding:10px;margin:5px 0;border-radius:10px;border:1px solid rgba(255,255,255,.15);box-sizing:border-box}}button{{padding:10px 14px;border:0;border-radius:10px;background:{col["main"]};color:#fff;font-weight:700}}</style></head><body><div class="top"><b>{get_logo_html()} OMAIA ISP</b><div><a href="/dash?v=home">رئيسية</a><a href="/dash?v=map">خريطة</a><a href="/dash?v=dishes">صحون</a><a href="/dash?v=towers">ابراج</a><a href="/logout">خروج</a></div></div><div class="mn">'+cn+'</div></body></html>'

@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login',methods=['GET','POST'])
def login():
 col=get_colors()
 if request.method=='POST':
  c=db(); u=ex(c,"SELECT * FROM users WHERE phone=?",(request.form.get('phone','').strip(),)).fetchone()
  if u and dict(u)['password']==request.form.get('password',''):
   session['phone']=dict(u)['phone']; cc(c); return redirect('/dash')
  cc(c)
 return f'<html dir="rtl"><body style="{get_bg_css()};display:flex;align-items:center;justify-content:center;height:100vh;margin:0;color:{col["text"]}"><form method="post" style="background:{col["card"]};padding:20px;border-radius:14px;width:300px"><h3>OMAIA ISP</h3><input name="phone" placeholder="هاتف" required><input name="password" type="password" placeholder="كلمة السر" required><button style="width:100%">دخول</button></form></body></html>'

@app.route('/logout')
def lo(): session.clear(); return redirect('/login')

@app.route('/dash')
def dash():
 if not session.get('phone'): return redirect('/login')
 v=request.args.get('v','home'); c=db()
 if v=='map': h=get_map_html(c)
 elif v=='dishes':
  rs=[dict(r) for r in ex(c,"SELECT * FROM dish_ips ORDER BY id DESC LIMIT 100").fetchall()]
  rows="".join([f'<div class="card"><span dir="ltr">{r.get("ip","")}</span> {r.get("location","")} <a href="/del_dish/{r["id"]}" style="color:#fca5a5">حذف</a></div>' for r in rs])
  h='<div class="card"><form method="post" action="/add_dish"><input name="ip" placeholder="IP"><input name="location" placeholder="اسم"><div style="display:grid;grid-template-columns:1fr 1fr;gap:6px"><input name="lat" placeholder="lat" type="number" step="any"><input name="lng" placeholder="lng" type="number" step="any"></div><button>اضافة صحن</button></form></div>'+rows
 elif v=='towers':
  rs=[dict(r) for r in ex(c,"SELECT * FROM towers ORDER BY id DESC LIMIT 100").fetchall()]
  rows="".join([f'<div class="card">{r.get("name","")} <a href="/del_tower/{r["id"]}" style="color:#fca5a5">حذف</a></div>' for r in rs])
  h='<div class="card"><form method="post" action="/add_tower"><input name="name" placeholder="اسم البرج" required><div style="display:grid;grid-template-columns:1fr 1fr;gap:6px"><input name="lat" placeholder="lat" type="number" step="any" required><input name="lng" placeholder="lng" type="number" step="any" required></div><button>اضافة برج</button></form></div>'+rows
 else:
  h=f'<div class="card"><h2>امية ISP</h2><p>مرحبا {session.get("phone","")} - {datetime.date.today()}</p></div>'
 cc(c); return base(h)

@app.route('/add_dish',methods=['POST'])
def ad():
 f=request.form; c=db()
 ex(c,"INSERT INTO dish_ips(ip,location,lat,lng) VALUES(?,?,?,?)",(f.get('ip',''),f.get('location',''),fnum(f.get('lat')),fnum(f.get('lng'))))
 sc(c); cc(c); return redirect('/dash?v=dishes')

@app.route('/del_dish/<int:i>')
def dd(i): c=db(); ex(c,"DELETE FROM dish_ips WHERE id=?",(i,)); sc(c); cc(c); return redirect('/dash?v=dishes')

@app.route('/add_tower',methods=['POST'])
def atw():
 f=request.form; c=db()
 ex(c,"INSERT INTO towers(name,lat,lng) VALUES(?,?,?)",(f.get('name',''),fnum(f.get('lat')),fnum(f.get('lng'))))
 sc(c); cc(c); return redirect('/dash?v=towers')

@app.route('/del_tower/<int:i>')
def dtw(i): c=db(); ex(c,"DELETE FROM towers WHERE id=?",(i,)); sc(c); cc(c); return redirect('/dash?v=towers')

if __name__=='__main__':
 app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
