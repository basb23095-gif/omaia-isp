from flask import Flask, request, redirect, session
import os, json, datetime
try:
 import psycopg2, psycopg2.extras
except: psycopg2=None
import sqlite3
from colors import get_colors, get_bg_css, get_menu_css, get_logo_html
app=Flask(__name__)
app.secret_key=os.environ.get("SECRET_KEY","omia-sec-2026")
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
def sc(c):
 try:c.commit()
 except:pass
def fnum(v):
 try:return float(v or 0)
 except:return 0
def init():
 c=db()
 ss=["CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,active INT DEFAULT 1)","CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT)","CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,lat REAL,lng REAL)","CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,lat REAL,lng REAL)"]
 if USE_PG:
  ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
  cur=c.cursor()
  for s in ss:cur.execute(s)
  cur.execute("SELECT * FROM users WHERE phone='05344851045'")
  if not cur.fetchone():cur.execute("INSERT INTO users(phone,password,role,active) VALUES('05344851045','admin2024','super',1)")
  cur.close()
 else:
  for s in ss:c.execute(s)
  if not c.execute("SELECT * FROM users WHERE phone='05344851045'").fetchone():c.execute("INSERT INTO users(phone,password,role,active) VALUES('05344851045','admin2024','super',1)")
  sc(c);cc(c)
init()
def can_edit():return session.get('role','tech') in ('super','admin','manager')
def base(cn):
 col=get_colors();bg=get_bg_css();logo=get_logo_html()
 return "<!DOCTYPE html><html dir=rtl><head><meta charset=UTF-8><meta name=viewport content='width=device-width,initial-scale=1'><title>OMAIA</title><style>*{box-sizing:border-box}body{margin:0;font-family:sans-serif;color:"+col['text']+";"+bg+"}.top{position:fixed;top:0;right:0;left:0;height:60px;display:flex;align-items:center;justify-content:space-between;padding:0 16px;background:"+col['top_bg']+";z-index:1000;border-bottom:1px solid "+col['card_border']+"}.nav a{color:"+col['link']+";text-decoration:none;margin:0 8px;font-size:14px}.mn{padding:75px 14px;max-width:1100px;margin:auto}.card{background:"+col['card_bg']+";border:1px solid "+col['card_border']+";padding:16px;border-radius:16px;margin:10px 0}.igrid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.icard{padding:20px;border-radius:14px;text-align:center;font-weight:800;color:#fff}input{width:100%;padding:11px;margin:5px 0;border-radius:10px;border:1px solid "+col['card_border']+";background:"+col['input_bg']+";color:"+col['text']+"}.btn{width:100%;padding:12px;border:none;border-radius:12px;background:"+col['btn']+";color:#fff;font-weight:800}.abtn{padding:6px 12px;border-radius:8px;color:#fff;text-decoration:none}.del{background:"+col['del']+"}.row2{display:grid;grid-template-columns:1fr 1fr;gap:8px}table{width:100%;border-collapse:collapse}th,td{padding:8px;text-align:center;font-size:13px}</style></head><body><div class=top><b>"+logo+" OMAIA ISP</b><div class=nav><a href='/dash?v=home'>الرئيسية</a><a href='/dash?v=map'>الخريطة</a><a href='/dash?v=subs'>مشتركين</a><a href='/dash?v=dishes'>صحون</a><a href='/dash?v=towers'>ابراج</a><a href='/logout'>خروج</a></div></div><div class=mn>"+cn+"</div></body></html>"
def vh(v,c):
 col=get_colors();edit=can_edit()
 if v=='map':
  ds=[dict(r) for r in ex(c,"SELECT location,lat,lng FROM dish_ips WHERE lat!=0 LIMIT 500").fetchall()]
  ts=[dict(r) for r in ex(c,"SELECT name,lat,lng FROM towers WHERE lat!=0 LIMIT 500").fetchall()]
  ds_j=json.dumps([{"la":float(d.get("lat") or 0),"ln":float(d.get("lng") or 0),"n":str(d.get("location",""))} for d in ds if d.get("lat")],ensure_ascii=False)
  ts_j=json.dumps([{"la":float(t.get("lat") or 0),"ln":float(t.get("lng") or 0),"n":str(t.get("name",""))} for t in ts if t.get("lat")],ensure_ascii=False)
  h="<link rel=stylesheet href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'/><div class=card><h3>الخريطة</h3><div style='display:flex;gap:6px'><input id=sqm placeholder='بحث...' style='flex:1'><button onclick='searchMap()' class=abtn style='background:"+col['main']+"'>بحث</button><button onclick='myLoc()' class=abtn style='background:#f59e0b'>موقعي</button></div><div id=mp style='height:70vh;border-radius:12px;margin-top:8px'></div></div>"
  h+="<script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script><script>var DS="+ds_j+";var TS="+ts_j+";function im(){if(typeof L=='undefined'){setTimeout(im,200);return;}var m=L.map('mp').setView([35.13,36.75],12);L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{maxZoom:19}).addTo(m);DS.forEach(function(d){L.marker([d.la,d.ln]).addTo(m).bindPopup(d.n)});TS.forEach(function(t){L.circleMarker([t.la,t.ln],{color:'red',radius:9}).addTo(m).bindPopup(t.n)});window.searchMap=function(){var q=document.getElementById('sqm').value;fetch('https://nominatim.openstreetmap.org/search?format=json&q='+encodeURIComponent(q)).then(function(r){return r.json()}).then(function(d){if(d[0])m.setView([d[0].lat,d[0].lon],15)})};window.myLoc=function(){navigator.geolocation.getCurrentPosition(function(p){m.setView([p.coords.latitude,p.coords.longitude],16)})};setTimeout(function(){m.invalidateSize()},400)};setTimeout(im,300)</script>"
  return h
 if v=='subs':
  rs=ex(c,"SELECT * FROM subs ORDER BY id DESC LIMIT 50").fetchall();rows=""
  for r in rs:
   d=dict(r);b="<a class=abtn del href='/del_sub/"+str(d['id'])+"'>حذف</a>" if edit else ""
   b=b.replace("del","del\" style=\"background:"+col['del'])
   rows+="<tr><td>"+str(d.get('name',''))+"</td><td>"+str(d.get('phone',''))+"</td><td>"+b+"</td></tr>"
  return "<div class=card><h3>المشتركين</h3><form method=post action=/add_sub><div class=row2><input name=name placeholder='الاسم' required><input name=phone placeholder='الهاتف' required></div><button class=btn>اضافة</button></form></div><div class=card><table><tr><th>اسم</th><th>هاتف</th><th></th></tr>"+rows+"</table></div>"
 if v=='dishes':
  rs=ex(c,"SELECT * FROM dish_ips ORDER BY id DESC LIMIT 100").fetchall();rows=""
  for r in rs:
   d=dict(r);b="<a class=abtn style='background:"+col['del']+"' href='/del_dish/"+str(d['id'])+"'>حذف</a>" if edit else ""
   rows+="<tr><td dir=ltr>"+str(d.get('ip',''))+"</td><td>"+str(d.get('location',''))+"</td><td>"+b+"</td></tr>"
  return "<div class=card><h3>الصحون</h3><form method=post action=/add_dish><div class=row2><input name=ip placeholder='IP'><input name=location placeholder='الاسم'></div><div class=row2><input name=lat placeholder='Lat' type=number step=any><input name=lng placeholder='Lng' type=number step=any></div><button class=btn>اضافة</button></form></div><div class=card><table>"+rows+"</table></div>"
 if v=='towers':
  rs=ex(c,"SELECT * FROM towers ORDER BY id DESC LIMIT 100").fetchall();rows=""
  for r in rs:
   d=dict(r);b="<a class=abtn style='background:"+col['del']+"' href='/del_tower/"+str(d['id'])+"'>حذف</a>" if edit else ""
   rows+="<tr><td>"+str(d.get('name',''))+"</td><td>"+b+"</td></tr>"
  return "<div class=card><h3>الابراج</h3><form method=post action=/add_tower><input name=name placeholder='اسم البرج' required><div class=row2><input name=lat placeholder='Lat' type=number step=any required><input name=lng placeholder='Lng' type=number step=any required></div><button class=btn>اضافة</button></form></div><div class=card><table>"+rows+"</table></div>"
 n1=list(ex(c,"SELECT COUNT(*) as c FROM subs").fetchone())[0] if not USE_PG else dict(ex(c,"SELECT COUNT(*) as c FROM subs").fetchone())['c']
 n2=list(ex(c,"SELECT COUNT(*) as c FROM dish_ips").fetchone())[0] if not USE_PG else dict(ex(c,"SELECT COUNT(*) as c FROM dish_ips").fetchone())['c']
 return "<div class=card style='text-align:center'><h2>امية ISP</h2><p>"+str(datetime.date.today())+"</p></div><div class=igrid><div class=icard style='background:"+col['icon_ip']+"'>صحون<br>"+str(n2)+"</div><div class=icard style='background:"+col['icon_active']+"'>مشتركين<br>"+str(n1)+"</div></div>"
@app.route('/')
def ix():return redirect('/dash') if session.get('phone') else redirect('/login')
@app.route('/login',methods=['GET','POST'])
def login():
 if request.method=='POST':
  c=db();u=ex(c,"SELECT * FROM users WHERE phone=?",(request.form.get('phone','').strip(),)).fetchone()
  if u and dict(u)['password']==request.form.get('password',''):
   d=dict(u);session['phone']=d['phone'];session['role']=d.get('role','tech');cc(c);return redirect('/dash')
  cc(c)
 col=get_colors()
 return "<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'></head><body style='display:flex;align-items:center;justify-content:center;height:100vh;margin:0;color:"+col['text']+";"+get_bg_css()+"'><div style='padding:24px;border-radius:16px;width:320px;text-align:center;background:"+col['card_bg']+"'><h3>OMAIA ISP</h3><form method=post><input name=phone placeholder='رقم الهاتف' required dir=ltr style='width:100%;padding:12px;margin:6px 0;border-radius:10px;border:none'><input name=password type=password placeholder='كلمة السر' required style='width:100%;padding:12px;margin:6px 0;border-radius:10px;border:none'><button style='width:100%;padding:13px;border:none;border-radius:10px;background:"+col['btn']+";color:#fff;font-weight:800'>دخول</button></form></div></body></html>"
@app.route('/logout')
def lo():session.clear();return redirect('/login')
@app.route('/dash')
def dash():
 if not session.get('phone'):return redirect('/login')
 v=request.args.get('v','home');c=db();h=vh(v,c);cc(c);return base(h)
@app.route('/add_sub',methods=['POST'])
def a1():c=db();ex(c,"INSERT INTO subs(name,phone) VALUES(?,?)",(request.form.get('name',''),request.form.get('phone','')));sc(c);cc(c);return redirect('/dash?v=subs')
@app.route('/del_sub/<int:i>')
def d1(i):
 if not can_edit():return "ممنوع",403
 c=db();ex(c,"DELETE FROM subs WHERE id=?",(i,));sc(c);cc(c);return redirect('/dash?v=subs')
@app.route('/add_dish',methods=['POST'])
def a2():f=request.form;c=db();ex(c,"INSERT INTO dish_ips(ip,location,lat,lng) VALUES(?,?,?,?)",(f.get('ip',''),f.get('location',''),fnum(f.get('lat')),fnum(f.get('lng'))));sc(c);cc(c);return redirect('/dash?v=dishes')
@app.route('/del_dish/<int:i>')
def d2(i):
 if not can_edit():return "ممنوع",403
 c=db();ex(c,"DELETE FROM dish_ips WHERE id=?",(i,));sc(c);cc(c);return redirect('/dash?v=dishes')
@app.route('/add_tower',methods=['POST'])
def a3():f=request.form;c=db();ex(c,"INSERT INTO towers(name,lat,lng) VALUES(?,?,?)",(f.get('name',''),fnum(f.get('lat')),fnum(f.get('lng'))));sc(c);cc(c);return redirect('/dash?v=towers')
@app.route('/del_tower/<int:i>')
def d3(i):
 if not can_edit():return "ممنوع",403
 c=db();ex(c,"DELETE FROM towers WHERE id=?",(i,));sc(c);cc(c);return redirect('/dash?v=towers')
if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
