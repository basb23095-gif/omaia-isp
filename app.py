from flask import Flask, request, redirect, session
import os, json, datetime
try:
    import psycopg2, psycopg2.extras
except: psycopg2=None
import sqlite3
from colors import get_colors, get_bg_css, get_menu_css, get_logo_html

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
    ss=["CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,active INT DEFAULT 1)","CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT)","CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,area TEXT,lat REAL,lng REAL)","CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,area TEXT,lat REAL,lng REAL)"]
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

def can_edit(): return session.get('role','tech') in ('super','admin','manager')

def view_html(v,c):
    col=get_colors()
    edit=can_edit()
    if v=='home':
        today=datetime.date.today().isoformat()
        n1=list(ex(c,"SELECT COUNT(*) as c FROM subs").fetchone())[0] if not USE_PG else dict(ex(c,"SELECT COUNT(*) as c FROM subs").fetchone())['c']
        n2=list(ex(c,"SELECT COUNT(*) as c FROM dish_ips").fetchone())[0] if not USE_PG else dict(ex(c,"SELECT COUNT(*) as c FROM dish_ips").fetchone())['c']
        return f"<div class='card' style='text-align:center'><h2>أمية ISP</h2><p>{today}</p></div><div class='igrid'><div class='icard' style='background:{col.get('icon_ip','#333')}'>📡<br>{n2}<br>صحون</div><div class='icard' style='background:{col.get('icon_active','#333)}'>👥<br>{n1}<br>مشتركين</div></div>"
    if v=='map':
        ds=[dict(r) for r in ex(c,"SELECT location,lat,lng FROM dish_ips WHERE lat!=0 LIMIT 1000").fetchall()]
        ts=[dict(r) for r in ex(c,"SELECT name,lat,lng FROM towers WHERE lat!=0 LIMIT 1000").fetchall()]
        ds_j=json.dumps([{"la":float(d.get("lat") or 0),"ln":float(d.get("lng") or 0),"n":str(d.get("location",""))} for d in ds if d.get("lat")],ensure_ascii=False)
        ts_j=json.dumps([{"la":float(t.get("lat") or 0),"ln":float(t.get("lng") or 0),"n":str(t.get("name",""))} for t in ts if t.get("lat")],ensure_ascii=False)
        h='<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/><div class="card"><h3>🗺️ الخريطة HD نار 🔥</h3><div style="display:flex;gap:6px;margin-bottom:6px"><input id="sqm" placeholder="🔍 بحث..." style="flex:1"><button class="abtn abtn-edit" onclick="searchMap()">بحث</button><button class="abtn abtn-toggle" onclick="myLoc()">📍 موقعي</button></div><div id="mp" style="height:70vh;border-radius:12px"></div><div id="cd" style="text-align:center;direction:ltr"></div></div>'
        h+='<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>var DS='+ds_j+';var TS='+ts_j+';function im(){if(typeof L=="undefined"){setTimeout(im,200);return;}var m=L.map("mp",{preferCanvas:true}).setView([35.13,36.75],12);L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",{maxZoom:19}).addTo(m);DS.forEach(function(d){L.marker([d.la,d.ln]).addTo(m).bindPopup(d.n);});TS.forEach(function(t){L.circleMarker([t.la,t.ln],{color:"red",radius:9}).addTo(m).bindPopup(t.n);});m.on("click",function(e){document.getElementById("cd").innerHTML=e.latlng.lat.toFixed(6)+", "+e.latlng.lng.toFixed(6);});window.searchMap=function(){var q=document.getElementById("sqm").value;fetch("https://nominatim.openstreetmap.org/search?format=json&q="+encodeURIComponent(q)).then(function(r){return r.json();}).then(function(d){if(d[0])m.setView([d[0].lat,d[0].lon],15);});};window.myLoc=function(){navigator.geolocation.getCurrentPosition(function(p){m.setView([p.coords.latitude,p.coords.longitude],17);L.circle([p.coords.latitude,p.coords.longitude],{radius:p.coords.accuracy}).addTo(m);L.marker([p.coords.latitude,p.coords.longitude]).addTo(m).bindPopup("دقة "+Math.round(p.coords.accuracy)+"م").openPopup();},null,{enableHighAccuracy:true});};setTimeout(function(){m.invalidateSize()},400);}setTimeout(im,250);</script>'
        return h
    if v=='subs':
        rs=ex(c,"SELECT * FROM subs ORDER BY id DESC LIMIT 50").fetchall()
        rows=""
        for r in rs:
            d=dict(r); dbtn=f"<a class='abtn abtn-del' href='/del_sub/{d['id']}'>حذف</a>" if edit else "<small>عرض فقط</small>"
            rows+=f"<tr><td>{d.get('name','')}</td><td>{d.get('phone','')}</td><td>{dbtn}</td></tr>"
        return f"<div class='card'><h3>👥 المشتركين</h3><form method=post action=/add_sub><div class=row2><input name=name placeholder='الاسم' required><input name=phone placeholder='هاتف' required></div><button class='btn-soft'>إضافة</button></form></div><div class='card'><table><tr><th>اسم</th><th>هاتف</th><th>إجراء</th></tr>{rows}</table></div>"
    if v=='dishes':
        rs=ex(c,"SELECT * FROM dish_ips ORDER BY id DESC LIMIT 100").fetchall()
        rows=""
        for r in rs:
            d=dict(r); dbtn=f"<a class='abtn abtn-del' href='/del_dish/{d['id']}'>حذف</a>" if edit else ""
            rows+=f"<tr><td dir=ltr>{d.get('ip','')}</td><td>{d.get('location','')}</td><td>{dbtn}</td></tr>"
        return f"<div class='card'><h3>📡 الصحون</h3><form method=post action=/add_dish><div class=row2><input name=ip placeholder='IP'><input name=location placeholder='الاسم'></div><div class=row2><input name=lat placeholder='Lat' type=number step=any><input name=lng placeholder='Lng' type=number step=any></div><button class='btn-soft'>إضافة صحن</button></form></div><div class='card'><table><tr><th>IP</th><th>اسم</th><th></th></tr>{rows}</table></div>"
    if v=='towers':
        rs=ex(c,"SELECT * FROM towers ORDER BY id DESC LIMIT 100").fetchall()
        rows=""
        for r in rs:
            d=dict(r); dbtn=f"<a class='abtn abtn-del' href='/del_tower/{d['id']}'>حذف</a>" if edit else ""
            rows+=f"<tr><td>{d.get('name','')}</td><td>{dbtn}</td></tr>"
        return f"<div class='card'><h3>🗼 الأبراج</h3><form method=post action=/add_tower><input name=name placeholder='اسم البرج' required><div class=row2><input name=lat placeholder='Lat' type=number step=any required><input name=lng placeholder='Lng' type=number step=any required></div><button class='btn-soft'>إضافة برج</button></form></div><div class='card'><table>{rows}</table></div>"
    return "<div class=card>أهلا</div>"

def base_html(content):
    col=get_colors()
    return f"""<!DOCTYPE html><html dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OMAIA</title><style>{get_menu_css()} *{{box-sizing:border-box}} body{{margin:0;font-family:'Segoe UI';{get_bg_css()};color:{col['text']}}}.card{{padding:12px;border-radius:16px;margin:8px 0;background:{col['card_bg']};border:1px solid rgba(255,255,255,.1)}}.igrid{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}.icard{{padding:16px;border-radius:12px;color:#fff;text-align:center}}.abtn{{padding:6px 12px;border-radius:10px;color:#fff;text-decoration:none;display:inline-block}}.abtn-edit{{background:#06b6d4}}.abtn-del{{background:#ef4444}}.abtn-toggle{{background:#f59e0b}}.btn-soft{{width:100%;padding:11px;border:none;border-radius:12px;background:linear-gradient(135deg,{col['main']},{col['accent']});color:#fff;font-weight:800}} input{{width:100%;padding:10px;margin:5px 0;border-radius:10px;border:1px solid rgba(255,255,255,.2);background:rgba(255,255,255,.06);color:{col['text']}}.row2{{display:grid;grid-template-columns:1fr 1fr;gap:8px}} table{{width:100%;border-collapse:collapse}} th,td{{padding:8px;text-align:center;font-size:12px}}.mn{{padding:70px 10px;max-width:1200px;margin:auto}}.top{{position:fixed;top:0;right:0;left:0;height:56px;display:flex;align-items:center;justify-content:space-between;padding:0 12px;z-index:1000;background:rgba(0,0,0,.3);backdrop-filter:blur(10px)}} </style></head><body><div class="top"><b>{get_logo_html()} OMAIA ISP</b><div><a href="/dash?v=home" style="color:{col['link']}">🏠</a> <a href="/dash?v=map" style="color:{col['link']}">🗺️</a> <a href="/dash?v=subs" style="color:{col['link']}">👥</a> <a href="/dash?v=dishes" style="color:{col['link']}">📡</a> <a href="/dash?v=towers" style="color:{col['link']}">🗼</a> <a href="/logout" style="color:{col['link']}">🚪</a></div></div><div class="mn">{content}</div></body></html>"""

@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')
@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        c=db();u=ex(c,"SELECT * FROM users WHERE phone=?",(request.form.get('phone','').strip(),)).fetchone()
        if u and dict(u)['password']==request.form.get('password',''):
            d=dict(u);session['phone']=d['phone'];session['role']=d.get('role','tech');cc(c);return redirect('/dash')
        cc(c)
    return '<html dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body style="display:flex;align-items:center;justify-content:center;height:100vh;background:#0f172a;color:#fff;font-family:sans-serif"><div style="background:rgba(255,255,255,.08);padding:24px;border-radius:16px;width:320px;text-align:center"><div style="font-size:48px">📡</div><h3>OMAIA ISP</h3><form method="post" autocomplete="on"><input name="phone" placeholder="📱 رقم الهاتف" required dir="ltr" autocomplete="username" style="width:100%;padding:12px;margin:6px 0;border-radius:10px;border:none;box-sizing:border-box"><input name="password" type="password" placeholder="🔒 كلمة السر" required autocomplete="current-password" style="width:100%;padding:12px;margin:6px 0;border-radius:10px;border:none;box-sizing:border-box"><label style="font-size:12px"><input type="checkbox" checked style="width:auto"> حفظ كلمة السر</label><br><br><button style="width:100%;padding:13px;border:none;border-radius:10px;background:#3b82f6;color:#fff;font-weight:800">دخول</button></form></div></body></html>'
@app.route('/logout')
def lo(): session.clear();return redirect('/login')
@app.route('/dash')
def dash():
    if not session.get('phone'):return redirect('/login')
    v=request.args.get('v','home');c=db();h=view_html(v,c);cc(c);return base_html(h)
@app.route('/add_sub',methods=['POST'])
def a1():c=db();ex(c,"INSERT INTO subs(name,phone) VALUES(?,?)",(request.form.get('name',''),request.form.get('phone','')));safe_commit(c);cc(c);return redirect('/dash?v=subs')
@app.route('/del_sub/<int:i>')
def d1(i):
    if not can_edit():return "ممنوع",403
    c=db();ex(c,"DELETE FROM subs WHERE id=?",(i,));safe_commit(c);cc(c);return redirect('/dash?v=subs')
@app.route('/add_dish',methods=['POST'])
def a2():f=request.form;c=db();ex(c,"INSERT INTO dish_ips(ip,location,lat,lng) VALUES(?,?,?,?)",(f.get('ip',''),f.get('location',''),fnum(f.get('lat')),fnum(f.get('lng'))));safe_commit(c);cc(c);return redirect('/dash?v=dishes')
@app.route('/del_dish/<int:i>')
def d2(i):
    if not can_edit():return "ممنوع",403
    c=db();ex(c,"DELETE FROM dish_ips WHERE id=?",(i,));safe_commit(c);cc(c);return redirect('/dash?v=dishes')
@app.route('/add_tower',methods=['POST'])
def a3():f=request.form;c=db();ex(c,"INSERT INTO towers(name,lat,lng) VALUES(?,?,?)",(f.get('name',''),fnum(f.get('lat')),fnum(f.get('lng'))));safe_commit(c);cc(c);return redirect('/dash?v=towers')
@app.route('/del_tower/<int:i>')
def d3(i):
    if not can_edit():return "ممنوع",403
    c=db();ex(c,"DELETE FROM towers WHERE id=?",(i,));safe_commit(c);cc(c);return redirect('/dash?v=towers')
@app.route('/debug_db')
def dbg():return 'OK '+str(USE_PG)
if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
