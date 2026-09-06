from flask import Flask, request, redirect, session, jsonify
from colors import COLORS, logo_html
import os, datetime, json, html, subprocess, platform
try:
    import psycopg2, psycopg2.extras
except:
    psycopg2=None
import sqlite3

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY","omia-sec-2026")
DATABASE_URL = os.environ.get("DATABASE_URL","").strip().replace("postgresql://","postgres://")
USE_PG = bool(DATABASE_URL.startswith("postgres://") and psycopg2)
_pg = None

def esc(s):
    return html.escape(str(s or ''), quote=True)

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
        _pg=psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=5)
        _pg.autocommit=True
        return _pg
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
        else:
            rs=[dict(r) for r in c.execute(q,a).fetchall()];cc(c);return rs
    except Exception as e:
        print("qall err",e);cc(c);return []

def qone(q,a=()):
    r=qall(q,a);return r[0] if r else None

def qexec(q,a=()):
    c=db()
    try:
        if USE_PG: cur=c.cursor();cur.execute(q.replace("?","%s"),a);cur.close()
        else: c.execute(q,a);c.commit();cc(c)
    except Exception as e:
        print("qexec err",e);cc(c)

def fnum(v):
    try:return float(v or 0)
    except:return 0

def init():
    ss=[
    "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,active INT DEFAULT 1)",
    "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,active INT DEFAULT 1)",
    "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,sub_id INT,amount REAL,typ TEXT,dt TEXT,note TEXT)",
    "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,lat REAL DEFAULT 0,lng REAL DEFAULT 0,dish_name TEXT,tower_name TEXT)",
    "CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,lat REAL,lng REAL)"
    ]
    if USE_PG: ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
    for s in ss: qexec(s)
    for col in ["ALTER TABLE users ADD COLUMN username TEXT","ALTER TABLE dish_ips ADD COLUMN dish_name TEXT","ALTER TABLE dish_ips ADD COLUMN tower_name TEXT"]:
        try: qexec(col)
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
        is_win = platform.system().lower()=='windows'
        cmd = ['ping','-n','4',ip] if is_win else ['ping','-c','4','-W','2',ip]
        out=subprocess.run(cmd,capture_output=True,text=True,timeout=10)
        txt=(out.stdout or '')+(out.stderr or '')
        return jsonify(ok=True,out=txt[:2000])
    except Exception as e:
        return jsonify(ok=False,out=str(e))

def page_content(v):
    try:
        h=""; dis="" if can_edit() else "style='opacity:.35;pointer-events:none'"
        if v=='home':
            ns=(qone("SELECT COUNT(*) c FROM subs") or {}).get('c',0)
            nd=(qone("SELECT COUNT(*) c FROM dish_ips") or {}).get('c',0)
            nt=(qone("SELECT COUNT(*) c FROM towers") or {}).get('c',0)
            h="<div class=grid><div class=kpi style='background:#2563eb'>👥<br>"+str(ns)+"</div><div class=kpi style='background:#16a34a'>📡<br>"+str(nd)+"</div><div class=kpi style='background:#dc2626'>🗼<br>"+str(nt)+"</div></div>"
            h+="<div class=card>مرحبا "+esc(session.get('phone'))+"</div>"
            h+='<div class=card><h3>📶 فحص Ping حقيقي</h3><div style="display:flex;gap:6px"><input id=ping_ip placeholder="اكتب IP"><button onclick="doPing()">Ping</button></div><pre id=ping_out style="background:#000;color:#0f0;padding:8px;border-radius:8px;max-height:200px;overflow:auto"></pre></div>'
            h+='<script>async function doPing(){var ip=document.getElementById("ping_ip").value;document.getElementById("ping_out").textContent="جاري الفحص...";var r=await fetch("/api/ping?ip="+encodeURIComponent(ip));var j=await r.json();document.getElementById("ping_out").textContent=j.out||"فشل"}</script>'
            return h
        elif v=='subs':
            rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 100")
            h="<div class=card><h3>👥 مشتركين</h3><form data-ajax method=post action=/add_sub><input name=name required placeholder=الاسم><input name=phone placeholder=هاتف><button>اضافة</button></form></div>"
            for r in rs:
                eid=str(r['id'])
                e='<a href="javascript:loadPage(\'edit_sub_'+eid+'\')" '+dis+'>✏️</a>' if can_edit() else ''
                h+="<div class=card>"+esc(r['name'])+" - "+esc(r['phone'])+" "+e+' <a href=/del_sub/'+eid+' data-del '+dis+' style="color:red">🗑️</a></div>'
            return h
        elif v.startswith('edit_sub_'):
            if not can_edit(): return "ممنوع"
            r=qone("SELECT * FROM subs WHERE id=?", (v.split('_')[-1],))
            if not r: return "غير موجود"
            return '<div class=card><form data-ajax method=post action=/upd_sub/'+str(r['id'])+'><input name=name value="'+esc(r['name'])+'"><input name=phone value="'+esc(r['phone'])+'"><button>💾 حفظ</button></form></div>'
        elif v=='dishes':
            rs=qall("SELECT * FROM dish_ips ORDER BY id DESC LIMIT 200")
            h="<div class=card><h3>📡 صحون</h3><form data-ajax method=post action=/add_dish><input name=dish_name required placeholder='📛 اسم صحن'><input name=ip required placeholder='🌐 IP'><input name=tower_name placeholder='🗼 برج'><div style='display:grid;grid-template-columns:1fr 1fr;gap:6px'><input name=lat placeholder='lat'><input name=lng placeholder='lng'></div><button>اضافة</button></form></div><div class=grid2>"
            for r in rs:
                eid=str(r['id']); ip=esc(r['ip'])
                e='<a href="javascript:loadPage(\'edit_dish_'+eid+'\')" '+dis+'>✏️</a>' if can_edit() else ''
                h+="<div class='card small'>📛<b>"+esc(r.get('dish_name') or '')+"</b> <span style='font-size:11px'>"+ip+"</span><br><div style='display:flex;gap:4px;margin-top:4px'><button style='padding:4px 6px;font-size:11px' onclick='pingOne(\""+ip+"\")'>Ping</button>"+e+" <a href=/del_dish/"+eid+" data-del "+dis+" style='color:red;font-size:12px'>🗑️</a></div></div>"
            h+="</div><pre id=ping_out2 style='background:#000;color:#0f0;padding:8px;border-radius:8px'></pre>"
            h+='<script>async function pingOne(ip){document.getElementById("ping_out2").textContent="يفحص "+ip+"...";var r=await fetch("/api/ping?ip="+encodeURIComponent(ip));var j=await r.json();document.getElementById("ping_out2").textContent=j.out}</script>'
            return h
        elif v.startswith('edit_dish_'):
            if not can_edit(): return "ممنوع"
            r=qone("SELECT * FROM dish_ips WHERE id=?", (v.split('_')[-1],))
            if not r: return "غير موجود"
            return '<div class=card><form data-ajax method=post action=/upd_dish/'+str(r['id'])+'><input name=dish_name value="'+esc(r.get('dish_name',''))+'"><input name=ip value="'+esc(r['ip'])+'"><input name=tower_name value="'+esc(r.get('tower_name',''))+'"><input name=lat value="'+str(r.get('lat',0))+'"><input name=lng value="'+str(r.get('lng',0))+'"><button>💾 حفظ</button></form></div>'
        elif v=='towers':
            rs=qall("SELECT * FROM towers ORDER BY id DESC LIMIT 100")
            h="<div class=card><h3>🗼 ابراج</h3><form data-ajax method=post action=/add_tower><input name=name required placeholder=اسم><input name=lat placeholder=lat><input name=lng placeholder=lng><button>اضافة</button></form></div>"
            for r in rs:
                eid=str(r['id'])
                e='<a href="javascript:loadPage(\'edit_tower_'+eid+'\')" '+dis+'>✏️</a>' if can_edit() else ''
                h+="<div class=card>🗼 "+esc(r['name'])+" "+e+' <a href=/del_tower/'+eid+' data-del '+dis+' style="color:red">حذف</a></div>'
            return h
        elif v.startswith('edit_tower_'):
            if not can_edit(): return "ممنوع"
            r=qone("SELECT * FROM towers WHERE id=?", (v.split('_')[-1],))
            return '<div class=card><form data-ajax method=post action=/upd_tower/'+str(r['id'])+'><input name=name value="'+esc(r['name'])+'"><button>حفظ</button></form></div>'
        elif v=='ledger':
            rs=qall("SELECT l.*,s.name sname FROM ledger l LEFT JOIN subs s ON s.id=l.sub_id ORDER BY l.id DESC LIMIT 200")
            ss=qall("SELECT id,name FROM subs LIMIT 200")
            o="".join(["<option value='"+str(x['id'])+"'>"+esc(x['name'])+"</option>" for x in ss])
            h="<div class=card><h3>📒 دفتر</h3><form data-ajax method=post action=/add_ledger><select name=sub_id>"+o+"</select><input name=amount type=number step=0.01 required placeholder=مبلغ><select name=typ><option>دين</option><option>دفع</option></select><input name=note placeholder=ملاحظة><button>اضافة</button></form></div>"
            for r in rs:
                h+="<div class=card>👤 "+esc(r.get('sname',''))+" 💰 "+str(r.get('amount',0))+" "+esc(r.get('typ',''))+"</div>"
            return h
        elif v=='map':
            ds=qall("SELECT id,lat,lng,dish_name,ip FROM dish_ips WHERE lat!=0 LIMIT 500")
            arr=[]
            for d in ds:
                try:
                    if d.get("lat"):
                        arr.append({"id":d["id"],"la":float(d.get("lat") or 0),"ln":float(d.get("lng") or 0),"n":str(d.get("dish_name","")),"ip":str(d.get("ip",""))})
                except: pass
            dj=json.dumps(arr).replace("</","<\\/")
            h="<div class=card><h3>🗺️ خريطة + قمر صناعي</h3><div style='margin-bottom:6px'><button onclick='setSat()'>🛰️ قمر صناعي</button> <button onclick='setNorm()'>🗺️ عادي</button> <button onclick='toggleMeasure()'>📏 قياس</button></div><div id=mp style='height:70vh;border-radius:10px'></div><div style='font-size:12px'>كلك يمين لتثبيت دبوس جديد</div></div>"
            h+="<script>var DS="+dj+";initMap();</script>"
            return h
        elif v=='settings':
            us=qall("SELECT phone,username,role FROM users ORDER BY phone")
            uh=""
            for u in us:
                ph=esc(u['phone']); un=esc(u.get('username') or u['phone']); ro=esc(u.get('role',''))
                delb=""
                if ph!='05344851045':
                    delb="<a href=/del_user/"+ph+" data-del style='color:red'>🗑️</a>"
                uh+="<div class='card user-card "+ro+"'><div class=avatar>"+esc(un[:1])+"</div><div><b>"+un+"</b><br><small>"+ph+" - "+ro+"</small></div>"+delb+"</div>"
            h="<div class=card><h3>⚙️ اعدادات</h3><form data-ajax method=post action=/change_pass><input name=newpass type=password required placeholder='كلمة جديدة'><button>💾 حفظ كلمة السر</button></form><a href=/toggle_theme data-ajax>🌙/☀️ تبديل ليل نهار</a></div>"
            h+="<div class=card><h3>➕ اضافة يوزر</h3><form data-ajax method=post action=/add_user><input name=phone required placeholder='يوزر'><input name=password type=password required placeholder='كلمة سر'><select name=role><option value=tech>🧑‍🔧 فني</option><option value=manager>👑 مدير</option></select><button>اضافة</button></form></div><div class=user-grid>"+uh+"</div>"
            return h
        return "<div class=card>صفحة</div>"
    except Exception as e:
        print("page_content err",e)
        return "<div class=card>خطأ داخلي: "+esc(str(e))+"</div>"

def layout(c,v='home'):
    th=dark()
    bg=COLORS.get('bg_dark','#0f172a') if th=='dark' else COLORS.get('bg_light','#f1f5f9')
    card=COLORS.get('card_dark','#1e293b') if th=='dark' else COLORS.get('card_light','#ffffff')
    txt='#fff' if th=='dark' else '#000'
    top_bg=COLORS.get('top_bg','#0f172a'); menu_bg=COLORS.get('menu_bg','#1e293b'); btn=COLORS.get('btn','#2563eb')
    html_page="<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
    html_page+="<link rel=stylesheet href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'><style>"
    html_page+="*{box-sizing:border-box}body{margin:0;font-family:sans-serif;background:"+bg+";color:"+txt+"}"
    html_page+=".top{position:fixed;top:0;left:0;right:0;background:"+top_bg+";color:#fff;padding:12px;z-index:101;display:flex;gap:12px;align-items:center}"
    html_page+=".menu{position:fixed;top:48px;bottom:0;right:0;width:210px;background:"+menu_bg+";padding:10px;z-index:100;transition:.25s}.menu.hide{transform:translateX(100%)}.menu a{display:block;color:#fff;text-decoration:none;padding:11px;border-radius:8px;margin:2px 0}"
    html_page+=".main{margin-right:220px;margin-top:60px;padding:10px}.main.full{margin-right:0}.card{background:"+card+";padding:10px;border-radius:10px;margin:8px 0}.card.small{padding:8px;font-size:13px}"
    html_page+=".grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:6px}.user-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}.user-card{display:flex;gap:10px;align-items:center;border-right:4px solid #888}.user-card.manager{border-color:#f59e0b}.user-card.tech{border-color:#2563eb}.avatar{width:36px;height:36px;border-radius:50%;background:#2563eb;color:#fff;display:flex;align-items:center;justify-content:center;font-weight:bold}.kpi{padding:12px;border-radius:10px;color:#fff;text-align:center}input,select{width:100%;padding:8px;margin:4px 0;border-radius:7px;border:1px solid #ccc}button{background:"+btn+";color:#fff;border:0;padding:8px 12px;border-radius:7px;cursor:pointer}#ld{position:fixed;top:50px;left:50%;transform:translateX(-50%);background:#f59e0b;padding:4px 14px;border-radius:20px;display:none;z-index:200}@media(max-width:700px){.main{margin-right:0}.user-grid{grid-template-columns:1fr}}"
    html_page+="</style></head><body>"
    html_page+="<div class=top><span style='font-size:24px;cursor:pointer' onclick='toggleMenu()'>☰</span><div>"+logo_html()+"</div></div>"
    html_page+="<div class=menu id=mn><a href=\"javascript:loadPage('home')\">🏠 الرئيسية</a><a href=\"javascript:loadPage('subs')\">👥 مشتركين</a><a href=\"javascript:loadPage('ledger')\">📒 دفتر</a><a href=\"javascript:loadPage('dishes')\">📡 صحون</a><a href=\"javascript:loadPage('towers')\">🗼 ابراج</a><a href=\"javascript:loadPage('map')\">🗺️ خريطة</a><a href=\"javascript:loadPage('settings')\">⚙️ اعدادات</a><a href=/logout>🚪 خروج</a></div>"
    html_page+="<div class=main id=main>"+c+"</div><div id=ld>⏳ جاري التحميل...</div>"
    html_page+="<script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script><script>"
    html_page+="var curV='"+v+"';var mapObj=null;var satLayer=null;var normLayer=null;var measureMode=false;var measurePts=[];"
    html_page+="function toggleMenu(){document.getElementById('mn').classList.toggle('hide');document.getElementById('main').classList.toggle('full')}"
    html_page+="if(window.innerWidth<700){toggleMenu()}"
    html_page+="window.loadPage=async function(v){curV=v;var m=document.getElementById('mn');if(!m.classList.contains('hide')){toggleMenu()}var l=document.getElementById('ld');l.style.display='block';await new Promise(r=>setTimeout(r,350));try{var r=await fetch('/api/page?v='+v);var t=await r.text();document.getElementById('main').innerHTML=t;bindAjax();var sc=document.getElementById('main').querySelector('script');if(sc){eval(sc.innerHTML)}}catch(e){}l.style.display='none';};"
    html_page+="function setSat(){if(mapObj&&satLayer){mapObj.removeLayer(normLayer);satLayer.addTo(mapObj)}}"
    html_page+="function setNorm(){if(mapObj&&normLayer){mapObj.removeLayer(satLayer);normLayer.addTo(mapObj)}}"
    html_page+="function toggleMeasure(){measureMode=!measureMode;alert(measureMode?'اضغط نقطتين للقياس':'تم الايقاف')}"
    html_page+="function initMap(){if(typeof L=='undefined'){setTimeout(initMap,300);return}if(!document.getElementById('mp'))return;mapObj=L.map('mp').setView([35.13,36.75],12);satLayer=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{maxZoom:19});normLayer=L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19});satLayer.addTo(mapObj);"
    html_page+="if(typeof DS!='undefined'){DS.forEach(function(d){var mk=L.marker([d.la,d.ln]).addTo(mapObj);var pop='<b>'+d.n+'</b><br>'+d.ip+'<br><a href=\"javascript:loadPage(\\'edit_dish_'+\"+d.id+\"+'\\')\">✏️ تعديل</a>';mk.bindPopup(pop);});}"
    html_page+="mapObj.on('contextmenu',async function(e){var name=prompt('اسم النقطة:');if(!name)return;var fd=new FormData();fd.append('dish_name',name);fd.append('ip','0.0.0.0');fd.append('lat',e.latlng.lat);fd.append('lng',e.latlng.lng);await fetch('/add_dish',{method:'POST',body:fd});loadPage('map');});"
    html_page+="mapObj.on('click',function(e){if(!measureMode)return;measurePts.push(e.latlng);L.marker(e.latlng).addTo(mapObj);if(measurePts.length==2){var d=mapObj.distance(measurePts[0],measurePts[1]);alert('المسافة: '+Math.round(d)+' متر');measurePts=[];}});"
    html_page+="setTimeout(function(){mapObj.invalidateSize()},400);};"
    html_page+="function bindAjax(){document.querySelectorAll('form[data-ajax]').forEach(function(f){f.onsubmit=async function(e){e.preventDefault();await fetch(f.action,{method:'POST',body:new FormData(f)});alert('💾 تم الحفظ');loadPage(curV)}});document.querySelectorAll('a[data-ajax]').forEach(function(a){a.onclick=async function(e){e.preventDefault();await fetch(a.href);loadPage(curV)}});document.querySelectorAll('a[data-del]').forEach(function(a){a.onclick=async function(e){e.preventDefault();if(confirm('حذف؟')){await fetch(a.href);loadPage(curV)}}});};"
    html_page+="bindAjax();if(typeof DS!='undefined'){initMap();}"
    html_page+="</script></body></html>"
    return html_page

@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        uin=request.form.get('userin','').strip();pw=request.form.get('password','')
        u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
        if u and u['password']==pw:
            session['phone']=u['phone'];return redirect('/dash')
    return "<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><style>@keyframes bgMove{0%{background-position:0% 50%}50%{background-position:100% 50%}100%{background-position:0% 50%}}@keyframes fadeUp{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;font-family:sans-serif;background:linear-gradient(135deg,#0f172a,#2563eb,#06b6d4,#0f172a);background-size:300% 300%;animation:bgMove 12s ease infinite}.box{background:rgba(255,255,255,.95);padding:28px;border-radius:20px;width:92%;max-width:360px;box-shadow:0 20px 60px rgba(0,0,0,.3);animation:fadeUp.8s ease;text-align:center}.logo{font-size:42px}input{width:100%;padding:12px;margin:8px 0;border-radius:12px;border:1px solid #ddd}button{width:100%;background:linear-gradient(90deg,#2563eb,#06b6d4);color:#fff;padding:12px;border:0;border-radius:12px;font-size:16px;cursor:pointer}.design{margin-top:16px;font-size:13px;color:#555}.wa{display:inline-flex;align-items:center;gap:6px;margin-top:8px;background:#25D366;color:#fff;padding:8px 14px;border-radius:20px;text-decoration:none;font-size:14px}</style></head><body><div class=box><div class=logo>📡</div><h2>"+logo_html()+"</h2><form method=post><input name=userin placeholder='رقم هاتف / اسم مستخدم' required><input name=password type=password placeholder='كلمة السر' required><button>دخول 🚀</button></form><div class=design>تصميم عبدو عباس<br><span dir=ltr>+905344851045</span></div><a class=wa href='https://wa.me/905344851045' target=_blank>💬 واتساب</a></div></body></html>"

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

@app.route('/toggle_theme')
def tt(): session['theme']='dark' if dark()!='dark' else 'light';return "ok"

@app.route('/add_sub',methods=['POST'])
def a1(): qexec("INSERT INTO subs(name,phone) VALUES(?,?)",(request.form.get('name',''),request.form.get('phone','')));return "ok"

@app.route('/upd_sub/<int:i>',methods=['POST'])
def au1(i):
    if not can_edit(): return "no"
    qexec("UPDATE subs SET name=?,phone=? WHERE id=?",(request.form.get('name'),request.form.get('phone'),i));return "ok"

@app.route('/del_sub/<int:i>')
def a4(i):
    if not can_edit(): return "no"
    qexec("DELETE FROM subs WHERE id=?",(i,));return "ok"

@app.route('/add_ledger',methods=['POST'])
def b1():
    f=request.form
    qexec("INSERT INTO ledger(sub_id,amount,typ,dt,note) VALUES(?,?,?,?,?)",(int(f.get('sub_id') or 0),fnum(f.get('amount')),f.get('typ','دين'),datetime.datetime.now().isoformat(),f.get('note','')))
    return "ok"

@app.route('/add_dish',methods=['POST'])
def c1():
    f=request.form
    qexec("INSERT INTO dish_ips(ip,location,lat,lng,dish_name,tower_name) VALUES(?,?,?,?,?,?)",(f.get('ip',''),f.get('location',''),fnum(f.get('lat')),fnum(f.get('lng')),f.get('dish_name',''),f.get('tower_name','')))
    return "ok"

@app.route('/upd_dish/<int:i>',methods=['POST'])
def cu(i):
    if not can_edit(): return "no"
    f=request.form;qexec("UPDATE dish_ips SET ip=?,dish_name=?,tower_name=?,lat=?,lng=? WHERE id=?",(f.get('ip'),f.get('dish_name'),f.get('tower_name'),fnum(f.get('lat')),fnum(f.get('lng')),i));return "ok"

@app.route('/del_dish/<int:i>')
def c2(i):
    if not can_edit(): return "no"
    qexec("DELETE FROM dish_ips WHERE id=?",(i,));return "ok"

@app.route('/add_tower',methods=['POST'])
def d1():
    f=request.form;qexec("INSERT INTO towers(name,lat,lng) VALUES(?,?,?)",(f.get('name',''),fnum(f.get('lat')),fnum(f.get('lng'))));return "ok"

@app.route('/upd_tower/<int:i>',methods=['POST'])
def du2(i):
    if not can_edit(): return "no"
    f=request.form;qexec("UPDATE towers SET name=?,lat=?,lng=? WHERE id=?",(f.get('name'),fnum(f.get('lat')),fnum(f.get('lng')),i));return "ok"

@app.route('/del_tower/<int:i>')
def d2(i):
    if not can_edit(): return "no"
    qexec("DELETE FROM towers WHERE id=?",(i,));return "ok"

@app.route('/add_user',methods=['POST'])
def addu():
    if not can_edit(): return "no"
    f=request.form;ph=f.get('phone','').strip()
    qexec("INSERT INTO users(phone,password,role,username,active) VALUES(?,?,?,?,1)",(ph,f.get('password',''),f.get('role','tech'),ph))
    return "ok"

@app.route('/del_user/<ph>')
def delu(ph):
    if not can_edit(): return "no"
    if ph!='05344851045': qexec("DELETE FROM users WHERE phone=?",(ph,))
    return "ok"

@app.route('/change_pass',methods=['POST'])
def e2(): qexec("UPDATE users SET password=? WHERE phone=?",(request.form.get('newpass',''),session.get('phone')));return "ok"

if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
