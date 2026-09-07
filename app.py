from flask import Flask, request, redirect, session, jsonify, Response
from colors import COLORS, logo_html
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, datetime, json, html, ipaddress, io, csv
try: import psycopg2, psycopg2.extras
except: psycopg2=None
import sqlite3

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY","omia-sec-2026-CHANGE-ME")
DATABASE_URL = os.environ.get("DATABASE_URL","").strip().replace("postgresql://","postgres://")
USE_PG = bool(DATABASE_URL.startswith("postgres://") and psycopg2)
_pg=None
def esc(s): return html.escape(str(s or ''), quote=True)
def db():
    global _pg
    if USE_PG:
        try:
            if _pg:
                c=_pg.cursor();c.execute("SELECT 1");c.close();return _pg
        except:
            try:_pg.close()
            except:pass
            _pg=None
        _pg=psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=5);_pg.autocommit=True;return _pg
    c=sqlite3.connect("omia.db",check_same_thread=False);c.row_factory=sqlite3.Row;return c
def cc(c):
    if not USE_PG:
        try:c.close()
        except:pass
def qall(q,a=()):
    c=db()
    try:
        if USE_PG:
            cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor);cur.execute(q.replace("?","%s"),a);rs=[dict(r) for r in cur.fetchall()];cur.close();return rs
        else: rs=[dict(r) for r in c.execute(q,a).fetchall()];cc(c);return rs
    except Exception as e: print("qall",e);cc(c);return []
def qone(q,a=()):
    r=qall(q,a);return r[0] if r else None
def qexec(q,a=()):
    c=db()
    try:
        if USE_PG: cur=c.cursor();cur.execute(q.replace("?","%s"),a);cur.close()
        else: c.execute(q,a);c.commit();cc(c)
    except Exception as e: print("qexec",e);cc(c)
def fnum(v):
    try:return float(v or 0)
    except:return 0
def init():
    ss=["CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,active INT DEFAULT 1,username TEXT)",
    "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT)",
    "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,amount REAL,typ TEXT,dt TEXT,currency TEXT)",
    "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,dish_name TEXT)",
    "CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,area TEXT,lat REAL,lng REAL)",
    "CREATE TABLE IF NOT EXISTS activity_log(id INTEGER PRIMARY KEY AUTOINCREMENT,time TEXT,action TEXT,phone TEXT,username TEXT)",
    "CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY,v TEXT)"]
    if USE_PG: ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
    for s in ss: qexec(s)
    qexec("CREATE INDEX IF NOT EXISTS idx_ip ON dish_ips(ip)")
    if not qone("SELECT * FROM settings WHERE k='allow_edit'"): qexec("INSERT INTO settings(k,v) VALUES('allow_edit','1')")
    if not qone("SELECT * FROM settings WHERE k='allow_del'"): qexec("INSERT INTO settings(k,v) VALUES('allow_del','1')")
    if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username,active) VALUES(?,?,?,?,1)",('05344851045',generate_password_hash('admin2024'),'manager','admin'))
init()
def get_set(k): r=qone("SELECT * FROM settings WHERE k=?",(k,));return r['v'] if r else '1'
def add_log(action):
    ph=session.get('phone','system');u=qone("SELECT username FROM users WHERE phone=?",(ph,));un=u['username'] if u else ph
    qexec("INSERT INTO activity_log(time,action,phone,username) VALUES(?,?,?,?)",(datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),action,ph,un))
def login_required(f):
    @wraps(f)
    def w(*a,**kw):
        if not session.get('phone'):
            if request.path.startswith('/api/'): return jsonify(ok=False),401
            return redirect('/login')
        return f(*a,**kw)
    return w
def manager_required(f):
    @wraps(f)
    def w(*a,**kw):
        if not session.get('phone'): return redirect('/login')
        m=qone("SELECT * FROM users WHERE phone=?",(session.get('phone'),))
        if not m or m['role']=='tech': return "ممنوع",403
        return f(*a,**kw)
    return w
def me(): return qone("SELECT * FROM users WHERE phone=?",(session.get('phone'),))
def can_edit():
    m=me()
    if not m: return False
    if m['role']=='tech': return False
    return get_set('allow_edit')=='1'
def can_del():
    m=me()
    if not m: return False
    if m['role']=='tech': return False
    return get_set('allow_del')=='1'
def is_internal_ip(ip):
    try:
        o=ipaddress.ip_address(ip.strip())
        return o.is_private and not o.is_loopback and not o.is_multicast
    except: return False
def cur_theme(): return session.get('theme','dark')

@app.route('/api/ping')
@login_required
def api_ping():
    ip=request.args.get('ip','').strip()
    if not is_internal_ip(ip): return jsonify(ok=False,out='خارج الشبكة')
    return jsonify(ok=True,out=f'IP: {ip} - افتح http://{ip} للوصول')

def page_content(v):
    can_e=can_edit();can_d=can_del()
    if v=='home':
        ns=(qone("SELECT COUNT(*) AS c FROM subs") or {}).get('c',0)
        nd=(qone("SELECT COUNT(*) AS c FROM dish_ips") or {}).get('c',0)
        nt=(qone("SELECT COUNT(*) AS c FROM towers") or {}).get('c',0)
        return f"<div style='max-width:700px;margin:0 auto;text-align:center'><div style='font-size:32px'>{logo_html()}</div><div style='display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:16px'><div class=card onclick=\"loadPage('subs')\" style='cursor:pointer'><h3>المشتركين</h3><h2>{ns}</h2></div><div class=card onclick=\"loadPage('dishes')\" style='cursor:pointer'><h3>الصحون</h3><h2>{nd}</h2></div><div class=card onclick=\"loadPage('towers')\" style='cursor:pointer'><h3>الأبراج</h3><h2>{nt}</h2></div><div class=card onclick=\"loadPage('map')\" style='cursor:pointer'><h3>الخريطة</h3><h2>موقع</h2></div></div></div>"
    if v=='dishes':
        return """<div style='max-width:900px;margin:0 auto'>
        <div class=card style='text-align:center'><h3>الصحون</h3>
        <input id=searchBox placeholder='بحث IP أو اسم + Enter' oninput="instantSearch(this.value)" onkeydown="if(event.key==='Enter')instantSearch(this.value)" style='max-width:400px;margin:0 auto'>
        <form data-ajax method=post action=/add_dish style='display:flex;gap:6px;max-width:500px;margin:8px auto;flex-wrap:wrap'><input name=dish_name required placeholder='اسم الصحن' style='flex:1'><input name=ip required placeholder='IP' style='flex:1'><input name=location placeholder='موقع' style='flex:1'><button class=btn-gold>اضافة</button></form>
        <div style='display:flex;gap:6px;justify-content:center'><button class=btn-blue onclick='exportExcel()'>Excel</button><button class=btn-blue onclick="window.open('/export_pdf')">PDF</button></div></div>
        <div id=dishList style='display:flex;flex-direction:column;gap:8px;align-items:center'></div>
        <div style='text-align:center;margin:10px'><button class=btn onclick='moreDishes()'>المزيد 20</button></div>
        <script>let pg=0;async function loadD(q=""){let r=await fetch('/api/search?q='+encodeURIComponent(q)+'&page='+pg);let d=await r.json();let h="";d.forEach(x=>{h+=`<div class=card style="width:320px;max-width:95%;margin:0 auto;padding:8px 10px;display:flex;justify-content:space-between;align-items:center"><div style="font-size:13px;text-align:right"><b>${x.dish_name||''}</b> <a href="http://${x.ip}" target=_blank class=ip-badge style="text-decoration:none">${x.ip}</a><br><small>${x.location||''}</small></div><div style="display:flex;gap:4px">`+(CAN_E?`<button onclick='editDish(${x.id},"${(x.dish_name||'').replace(/"/g,'')}","${x.ip}","${(x.location||'').replace(/"/g,'')}")' style="width:52px;height:32px;background:#FF9800;border:0;border-radius:8px;font-size:12px">تعديل</button>`:'')+(CAN_D?`<button onclick='delItem("/del_dish/${x.id}")' style="width:44px;height:32px;background:#F44336;border:0;border-radius:8px;font-size:12px">حذف</button>`:'')+`</div></div>`});if(pg==0)document.getElementById('dishList').innerHTML=h;else document.getElementById('dishList').innerHTML+=h}
        async function instantSearch(q){pg=0;loadD(q)}function moreDishes(){pg++;loadD(document.getElementById('searchBox').value)}loadD();
        function editDish(id,n,ip,loc){let nn=prompt('اسم:',n);if(nn==null)return;let i2=prompt('IP:',ip);if(i2==null)return;let l2=prompt('موقع:',loc);fetch('/edit_dish/'+id,{method:'POST',body:new URLSearchParams({dish_name:nn,ip:i2,location:l2})}).then(()=>{toast('تم التعديل');loadPage('dishes',true)})}
        </script></div>""".replace("CAN_E","1" if can_e else "0").replace("CAN_D","1" if can_d else "0")
    if v=='towers':
        rs=qall("SELECT * FROM towers ORDER BY id DESC LIMIT 40")
        cards=""
        for r in rs:
            eb=f"<button onclick='editTower({r['id']})' style='width:52px;height:32px;background:#FF9800;border:0;border-radius:8px;font-size:12px'>تعديل</button>" if can_e else ""
            dbtn=f"<button onclick='delItem(\"/del_tower/{r['id']}\")' style='width:44px;height:32px;background:#F44336;border:0;border-radius:8px;font-size:12px'>حذف</button>" if can_d else ""
            cards+=f"<div class=card style='display:flex;justify-content:space-between;align-items:center'><div><b>{esc(r['name'])}</b><br><small>{esc(r['area'] or '')}</small></div><div style='display:flex;gap:6px'>{eb}{dbtn}</div></div>"
        return f"""<div style='max-width:900px;margin:0 auto'><div class=card style='text-align:center'><h3>الأبراج</h3><form data-ajax method=post action=/add_tower><input name=name required placeholder='اسم البرج'><input name=area placeholder='المنطقة'><button class=btn-gold>اضافة</button></form></div><div style='display:grid;grid-template-columns:1fr 1fr;gap:10px'>{cards}</div><script>
        function editTower(id){{ let nn=prompt('اسم جديد:'); if(nn==null||!nn) return; fetch('/edit_tower/'+id,{{method:'POST',body:new URLSearchParams({{name:nn}})}}).then(()=>loadPage('towers',true)) }}
        </script></div>"""
    if v=='subs':
        rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 20")
        rows="".join([f"<div class=card><b>{esc(r['name'])}</b> - {esc(r['phone'] or '')}</div>" for r in rs])
        return f"<div style='max-width:600px;margin:0 auto'><div class=card style='text-align:center'><h3>المشتركين</h3><form data-ajax method=post action=/add_sub><input name=name required placeholder='الاسم'><input name=phone placeholder='هاتف'><button class=btn-gold>اضافة</button></form></div>{rows}</div>"
    if v=='ledger':
        rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 20")
        rows="".join([f"<div class=card>{esc(r['name'])} - {r['amount']}</div>" for r in rs])
        return f"<div style='max-width:600px;margin:0 auto'><div class=card style='text-align:center'><h3>الحسابات</h3><form data-ajax method=post action=/add_ledger><input name=name required placeholder='الاسم'><input name=amount type=number step=0.01 required placeholder='مبلغ'><button class=btn-gold>اضافة</button></form></div>{rows}</div>"
    if v=='pingpage':
        return """<div style='max-width:500px;margin:0 auto'><div class=card style='text-align:center'><h3>فحص</h3><form onsubmit='event.preventDefault();doPing(document.getElementById("pip").value)'><input id=pip placeholder='IP داخلي مثلا 192.168.1.1' required style='max-width:300px;margin:0 auto'><button class=btn-gold style='margin-top:8px'>فتح</button></form><div id=pr style='margin-top:10px'></div></div><script>async function doPing(ip){window.open('http://'+ip,'_blank')}</script></div>"""
    if v=='map':
        towers=qall("SELECT * FROM towers");tj=json.dumps([{"name":t['name'],"lat":float(t.get('lat') or 35.13),"lng":float(t.get('lng') or 36.75)} for t in towers],ensure_ascii=False)
        dishes=qall("SELECT dish_name,ip FROM dish_ips LIMIT 500");dj=json.dumps([{"n":d['dish_name'],"ip":d['ip']} for d in dishes],ensure_ascii=False)
        return """<div class=card><div style='display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px'>
        <input id=mapSearch placeholder='ابحث برج + Enter' onkeydown='if(event.key==="Enter")mapGo(this.value)' style='max-width:200px'>
        <input id=dishSearch placeholder='ابحث صحن IP' oninput='searchDish(this.value)' style='max-width:200px'>
        <button class=btn-blue id=measBtn onclick='toggleMeasure()'>قياس مسافة</button>
        <button class=btn onclick='clearMeasure()'>مسح القياس</button>
        <span id=measOut style='background:#000;color:#ffbe4d;padding:6px 12px;border-radius:10px;font-family:monospace'></span></div>
        <div id=dishRes style='max-height:100px;overflow:auto'></div>
        <div id=map style='height:65vh;border-radius:12px'></div>
        <script>var _t="""+tj+""";var _d="""+dj+""";
        var map=L.map('map').setView([35.1318,36.7578],13);
        L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{maxZoom:22,maxNativeZoom:19}).addTo(map);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:22,opacity:0.35}).addTo(map);
        setTimeout(()=>map.invalidateSize(),400);
        _t.forEach(t=>L.marker([t.lat,t.lng]).addTo(map).bindPopup(t.name));
        window.mapGo=function(q){let f=_t.find(t=>t.name.includes(q));if(f){map.flyTo([f.lat,f.lng],18)}else toast('غير موجود')};
        window.searchDish=function(q){if(!q||q.length<2){document.getElementById('dishRes').innerHTML='';return}let f=_d.filter(d=>(d.n&&d.n.includes(q))||(d.ip&&d.ip.includes(q))).slice(0,10);document.getElementById('dishRes').innerHTML=f.map(d=>'<div style="padding:4px;border-bottom:1px solid #333">'+d.n+' - '+d.ip+'</div>').join('')};
        let measuring=false,pts=[],line=null,markers=[];
        window.toggleMeasure=function(){measuring=!measuring;document.getElementById('measBtn').textContent=measuring?'اضغط على الخريطة...':'قياس مسافة'};
        window.clearMeasure=function(){pts=[];markers.forEach(m=>map.removeLayer(m));markers=[];if(line){map.removeLayer(line);line=null}document.getElementById('measOut').textContent=''};
        map.on('click',function(e){if(!measuring)return;pts.push(e.latlng);let m=L.circleMarker(e.latlng,{radius:5,color:'#ffbe4d'}).addTo(map);markers.push(m);if(line)map.removeLayer(line);line=L.polyline(pts,{color:'#ffbe4d',weight:3,dashArray:'6 6'}).addTo(map);let total=0;for(let i=1;i<pts.length;i++)total+=map.distance(pts[i-1],pts[i]);let txt=total<1000?total.toFixed(2)+' متر':(total/1000).toFixed(4)+' كم';document.getElementById('measOut').textContent='المسافة: '+txt});
        </script></div>"""
    if v=='logs':
        rs=qall("SELECT * FROM activity_log ORDER BY id DESC LIMIT 50")
        rows="".join([f"<div class=log-row><b>{esc(r['username'] or r['phone'])}</b> - {esc(r['action'])} <small>{esc(r['time'])}</small></div>" for r in rs])
        return f"<div style='max-width:650px;margin:0 auto'><div class=card><h3>السجل</h3>{rows}</div></div>"
    if v=='support':
        return f"<div style='max-width:500px;margin:20px auto'><div class=card style='text-align:center'><h2>{logo_html()}</h2><a href='https://wa.me/905344851045' target=_blank style='background:#25D366;color:#fff;padding:12px 24px;border-radius:24px;text-decoration:none;display:inline-block;margin:6px'>واتساب</a><br><a href='https://instagram.com/af_20_1999' target=_blank style='background:#E1306C;color:#fff;padding:12px 24px;border-radius:24px;text-decoration:none;display:inline-block;margin:6px'>af_20_1999</a></div></div>"
    if v=='settings':
        ae=get_set('allow_edit');ad=get_set('allow_del')
        us=qall("SELECT * FROM users")
        uh=""
        for u in us:
            sel_t='selected' if u['role']=='tech' else ''
            sel_m='selected' if u['role']=='manager' else ''
            uh+=f"<div class=card style='text-align:center'><b>{esc(u['username'])}</b><br><small>{esc(u['phone'])}</small><div style='margin:8px 0'><select id='r_{esc(u['phone'])}' style='max-width:120px;margin:0 auto'><option value=tech {sel_t}>فني</option><option value=manager {sel_m}>مدير</option></select></div><div style='display:flex;gap:6px;justify-content:center'><button class=btn-blue onclick=\"saveRole('{esc(u['phone'])}')\">حفظ</button><button class=btn style='background:#F44336' onclick=\"delU('{esc(u['phone'])}')\">حذف</button></div></div>"
        return f"<div style='max-width:700px;margin:0 auto'><div class=card style='text-align:center'><h3>الإعدادات</h3><label>تفعيل التعديل <input type=checkbox {'checked' if ae=='1' else ''} onchange=\"fetch('/set/allow_edit/'+(this.checked?'1':'0'))\" style='width:auto'></label> <label>تفعيل الحذف <input type=checkbox {'checked' if ad=='1' else ''} onchange=\"fetch('/set/allow_del/'+(this.checked?'1':'0'))\" style='width:auto'></label><br><button class=btn onclick='toggleTheme()'>ليل/نهار</button><form data-ajax method=post action=/change_pass style='margin-top:8px;display:flex;gap:6px;justify-content:center'><input name=newpass type=password required placeholder='كلمة سر جديدة' style='max-width:200px'><button class=btn-gold>تغيير</button></form></div><div class=card style='text-align:center'><h3>اضافة مستخدم</h3><form data-ajax method=post action=/add_user style='display:flex;gap:6px;flex-wrap:wrap;justify-content:center'><input name=phone required placeholder='يوزر' style='max-width:140px'><input name=password type=password required placeholder='كلمة السر' style='max-width:140px'><select name=role style='max-width:120px'><option value=tech>فني</option><option value=manager>مدير</option></select><button class=btn-gold>اضافة</button></form></div><div style='display:grid;grid-template-columns:1fr 1fr;gap:10px'>{uh}</div><script>async function saveRole(ph){{await fetch('/edit_user/'+ph,{{method:'POST',body:new URLSearchParams({{role:document.getElementById('r_'+ph).value}})}});toast('تم الحفظ')}};async function delU(ph){{await fetch('/del_user/'+ph);toast('انحذف');loadPage('settings',true)}}</script></div>"
    return "ok"

def layout(c, v='home'):
    th = cur_theme()
    bg = COLORS.get('bg_dark' if th=='dark' else 'bg_light','#0a1938')
    card = COLORS.get('card_dark','#222')
    gold = COLORS.get('gold','#ffbe4d')
    lg = logo_html()
    tmpl = """<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<link rel='stylesheet' href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'>
<style>
*{box-sizing:border-box;font-family:'Segoe UI',Tahoma,sans-serif;transition:.2s}
body{margin:0;background:radial-gradient(1200px 600px at 80% -10%,#ff3d0022,transparent),__BG__;color:#fff;min-height:100vh}
.sidebar{position:fixed;right:0;top:0;width:270px;height:100%;background:linear-gradient(180deg,#0a0a0a 0%,#1a0f00 50%,#0a0a0a 100%);z-index:1000;padding-top:70px;transition:.3s;transform:translateX(290px);direction:rtl;border-left:2px solid #ff6a00aa}
.sidebar.active{transform:translateX(0)}
.sidebar a{display:flex;align-items:center;gap:10px;padding:14px 20px;margin:6px 12px;color:#fff;text-decoration:none;border-radius:12px;background:#ffffff08}
.sidebar a:hover{background:linear-gradient(90deg,#ff6a00,#ffbe4d);color:#000;font-weight:800;transform:translateX(-5px)}
.top{position:fixed;top:0;left:0;right:0;height:62px;background:linear-gradient(90deg,#0a0a0a,#2a1500,#0a0a0a);display:flex;align-items:center;justify-content:space-between;padding:0 15px;z-index:1001;border-bottom:2px solid #ff6a00}
.main{margin-top:70px;padding:12px}.card{background:linear-gradient(145deg,__CARD__,#1a1a1a);padding:16px;border-radius:16px;margin-bottom:12px;border:1px solid #ff6a0033;position:relative;overflow:hidden}
.card::before{content:'';position:absolute;top:0;right:0;left:0;height:3px;background:linear-gradient(90deg,#ff3d00,#ffbe4d,#ff3d00);background-size:200% 100%;animation:fire 2s linear infinite}
@keyframes fire{0%{background-position:0%}100%{background-position:200%}}
input,select{width:100%;padding:12px;margin:6px 0;background:#0f0f0f;border:1px solid #ff6a0055;color:#fff;border-radius:12px}
.btn-gold{background:linear-gradient(135deg,#ff3d00,#ffbe4d);color:#000;padding:12px 20px;border:0;border-radius:12px;font-weight:800;cursor:pointer}
.btn-blue{background:#2196F3;color:#fff;padding:10px 16px;border:0;border-radius:12px}.btn{background:#2a2a2a;color:#fff;padding:10px 16px;border:1px solid #444;border-radius:12px}
.ip-badge{background:#000;color:#ffbe4d;padding:4px 10px;border-radius:20px;font-family:monospace;border:1px solid #ffbe4d66}
#toast{position:fixed;bottom:25px;left:50%;transform:translateX(-50%);background:linear-gradient(90deg,#ff3d00,#ffbe4d);color:#000;padding:12px 25px;border-radius:30px;display:none;z-index:9999;font-weight:800}
.log-row{padding:6px;border-bottom:1px solid #333;font-size:13px}
.wa-float{position:fixed;bottom:18px;left:18px;width:58px;height:58px;background:#25D366;border-radius:50%;display:flex;align-items:center;justify-content:center;z-index:2000;box-shadow:0 8px 25px #25D36688}
</style></head><body><div id=toast></div>
<a class=wa-float href="https://wa.me/905344851045" target=_blank><svg viewBox="0 0 24 24" width="30" height="30" fill="white"><path d="M17.5 14.4c-.3-.15-1.76-.87-2.03-.97-.27-.1-.47-.15-.67.15-.2.3-.77.97-.94 1.17-.17.2-.35.22-.65.07-.3-.15-1.26-.46-2.4-1.48-.88-.79-1.48-1.76-1.65-2.06-.17-.3-.02-.46.13-.61.13-.13.3-.35.45-.52.15-.17.2-.3.3-.5.1-.2.05-.37-.02-.52-.08-.15-.67-1.62-.92-2.22-.24-.58-.49-.5-.67-.51h-.57c-.2 0-.52.07-.8.37-.27.3-1.04 1.02-1.04 2.5 0 1.47 1.07 2.9 1.22 3.1.15.2 2.1 3.2 5.1 4.49.71.31 1.27.49 1.7.63.72.23 1.37.2 1.88.12.57-.09 1.76-.72 2.01-1.42.25-.7.25-1.29.17-1.42-.07-.13-.27-.2-.57-.35M12.04 2C6.56 2 2.1 6.46 2.1 11.93c0 1.75.46 3.45 1.32 4.95L2 22l5.25-1.38a9.9 9.9 0 004.79 1.22c5.48 0 9.93-4.46 9.93-9.93 0-2.65-1.03-5.14-2.9-7.01A9.86 9.86 0 0012.04 2"/></svg></a>
<div class=sidebar id=sb dir=rtl><a href="javascript:loadPage('home')">🏠 الرئيسية</a><a href="javascript:loadPage('dishes')">📡 الصحون</a><a href="javascript:loadPage('towers')">🗼 الأبراج</a><a href="javascript:loadPage('pingpage')">📶 فحص</a><a href="javascript:loadPage('map')">🗺️ الخريطة</a><a href="javascript:loadPage('logs')">📝 السجل</a><a href="javascript:loadPage('support')">💬 الدعم</a><a href="javascript:loadPage('settings')">⚙️ الإعدادات</a><a href=/logout style="background:#ff3d0022;border:1px solid #ff3d00">🚪 خروج</a></div>
<div class=top><div onclick="document.getElementById('sb').classList.toggle('active')" style='font-size:24px;cursor:pointer'>☰</div><div>__LOGO__</div><div><button class=btn onclick="loadPage(cur,true)">🔄</button></div></div>
<div class=main id=mn>__CONTENT__</div>
<script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>
<script>
let cur='__V__';let cache={};
function toast(m){let t=document.getElementById('toast');t.textContent=m;t.style.display='block';setTimeout(()=>t.style.display='none',2000)}
async function loadPage(v,f){cur=v;document.getElementById('sb').classList.remove('active');if(cache[v]&&!f){document.getElementById('mn').innerHTML=cache[v];exe();return}let r=await fetch('/api/page?v='+v);let h=await r.text();cache[v]=h;document.getElementById('mn').innerHTML=h;exe();}
function exe(){document.getElementById('mn').querySelectorAll('script').forEach(s=>{try{eval(s.textContent)}catch(e){}});bind()}
function bind(){document.querySelectorAll('form[data-ajax]').forEach(f=>{f.onsubmit=async e=>{e.preventDefault();await fetch(f.action,{method:'POST',body:new FormData(f)});for(let k in cache)delete cache[k];toast('تم');loadPage(cur,true)}})}
window.delItem=async function(u){await fetch(u);for(let k in cache)delete cache[k];toast('انحذف');loadPage(cur,true)};
window.toggleTheme=async()=>{await fetch('/toggle_theme');location.reload()};
window.exportExcel=()=>{window.open('/export_excel')};
bind();exe();
</script></body></html>"""
    tmpl = tmpl.replace("__BG__", bg).replace("__CARD__", card).replace("__LOGO__", lg).replace("__CONTENT__", c).replace("__V__", v)
    return tmpl

@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        uin=request.form.get('userin','').strip() or request.form.get('phone','').strip()
        pw=request.form.get('password','')
        u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
        if u and check_password_hash(u['password'],pw):
            session['phone']=u['phone'];session['role']=u['role'];add_log("دخول")
            if request.headers.get('X-Requested-With')=='fetch':
                return jsonify(ok=True)
            return redirect('/dash')
        if request.headers.get('X-Requested-With')=='fetch':
            return jsonify(ok=False)
        return "<script>alert('خطأ بالدخول');location.href='/login'</script>"
    return """<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><style>
body{margin:0;min-height:100vh;background:#0a0e2a;display:flex;flex-direction:column;align-items:center;justify-content:center;font-family:sans-serif;color:#fff}
.title{font-size:24px;font-weight:800;margin:10px 0 5px;color:#fff}.sub{color:#aaa;font-size:13px;margin-bottom:20px}.card{background:#1e2433;border:1px solid #ffffff15;padding:25px;border-radius:20px;width:320px}
input{width:100%;padding:12px;margin:8px 0;background:#0f1424;border:1px solid #ffffff20;color:#fff;border-radius:12px;box-sizing:border-box}
.btn{width:100%;padding:13px;border:0;border-radius:12px;background:linear-gradient(135deg,#ff3d00,#ffbe4d);color:#000;font-weight:800;font-size:16px;margin-top:10px;cursor:pointer}
label{font-size:13px;color:#aaa;display:flex;align-items:center;gap:6px}label input{width:auto}
.wa{margin-top:20px;background:#25D366;color:#fff;padding:12px 25px;border-radius:30px;text-decoration:none;display:inline-flex;align-items:center;gap:8px;font-weight:700}
</style></head><body>
<div class=title>شركة أمية للإنترنت 🔥</div><div class=sub>نظام إدارة المشتركين</div>
<div class=card><h3 style="text-align:center">تسجيل الدخول</h3><form id=lf>
<input name=userin id=uin placeholder='رقم الهاتف / اسم المستخدم' required>
<input name=password id=pw type=password placeholder='كلمة السر' required>
<label><input type=checkbox id=rem> حفظ كلمة السر (تذكرني)</label>
<button class=btn>دخول</button><div id=err style="color:#ff8080;text-align:center"></div></form></div>
<a class=wa href="https://wa.me/905344851045" target="_blank">💬 الدعم الفني واتساب</a>
<div style="color:#888;font-size:12px;margin-top:6px">اضغط للتواصل عند مشكلة بالدخول</div>
<script>
uin.value=localStorage.getItem('uin')||'';pw.value=localStorage.getItem('pw')||'';rem.checked=!!localStorage.getItem('uin');
document.getElementById('lf').onsubmit=async e=>{e.preventDefault();if(rem.checked){localStorage.setItem('uin',uin.value);localStorage.setItem('pw',pw.value)}else{localStorage.removeItem('uin');localStorage.removeItem('pw')}
let r=await fetch('/login',{method:'POST',headers:{'X-Requested-With':'fetch'},body:new FormData(e.target)});let j=await r.json();if(j.ok)location.href='/dash';else document.getElementById('err').textContent='خطأ بالدخول'};
</script></body></html>"""

@app.route('/logout')
def lo(): session.clear();return redirect('/login')
@app.route('/dash')
@login_required
def dash():
    v=request.args.get('v','home')
    return layout(page_content(v),v)
@app.route('/api/page')
@login_required
def ap(): return page_content(request.args.get('v','home'))
@app.route('/api/search')
@login_required
def s():
    q=request.args.get('q','').strip();pg=int(request.args.get('page',0));off=pg*20
    if q: return jsonify(qall(f"SELECT * FROM dish_ips WHERE ip LIKE? OR dish_name LIKE? ORDER BY id DESC LIMIT 20 OFFSET {off}",("%"+q+"%","%"+q+"%")))
    return jsonify(qall(f"SELECT * FROM dish_ips ORDER BY id DESC LIMIT 20 OFFSET {off}"))
@app.route('/toggle_theme')
@login_required
def tt(): session['theme']='light' if cur_theme()=='dark' else 'dark';return "ok"
@app.route('/set/<k>/<v>')
@manager_required
def setv(k,v): qexec("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v" if USE_PG else "INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)",(k,v));return "ok"
@app.route('/add_dish',methods=['POST'])
@login_required
def ad():
    ip=request.form.get('ip','').strip()
    if not is_internal_ip(ip): return "IP غير داخلي",400
    qexec("INSERT INTO dish_ips(ip,location,dish_name) VALUES(?,?,?)",(ip,request.form.get('location',''),request.form.get('dish_name','')));add_log("اضافة صحن "+ip);return "ok"
@app.route('/edit_dish/<int:i>',methods=['POST'])
@login_required
def ed(i):
    if not can_edit(): return "ممنوع",403
    qexec("UPDATE dish_ips SET dish_name=?,ip=?,location=? WHERE id=?",(request.form.get('dish_name',''),request.form.get('ip','').strip(),request.form.get('location',''),i));add_log("تعديل صحن");return "ok"
@app.route('/del_dish/<int:i>')
@login_required
def dd(i):
    if not can_del(): return "ممنوع",403
    qexec("DELETE FROM dish_ips WHERE id=?",(i,));add_log("حذف صحن");return "ok"
@app.route('/add_tower',methods=['POST'])
@login_required
def at():
    qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",(request.form.get('name',''),request.form.get('area',''),35.1318,36.7578));add_log("اضافة برج");return "ok"
@app.route('/edit_tower/<int:i>',methods=['POST'])
@login_required
def et(i):
    if not can_edit(): return "ممنوع",403
    qexec("UPDATE towers SET name=? WHERE id=?",(request.form.get('name',''),i));return "ok"
@app.route('/del_tower/<int:i>')
@login_required
def dt(i):
    if not can_del(): return "ممنوع",403
    qexec("DELETE FROM towers WHERE id=?",(i,));return "ok"
@app.route('/add_sub',methods=['POST'])
@login_required
def asub(): qexec("INSERT INTO subs(name,phone) VALUES(?,?)",(request.form.get('name',''),request.form.get('phone','')));return "ok"
@app.route('/add_ledger',methods=['POST'])
@login_required
def al(): qexec("INSERT INTO ledger(name,amount,typ,dt,currency) VALUES(?,?,?,?,?)",(request.form.get('name',''),fnum(request.form.get('amount')), 'دين', datetime.datetime.now().isoformat(),'USD'));return "ok"
@app.route('/add_user',methods=['POST'])
@manager_required
def au():
    ph=request.form.get('phone','').strip()
    if qone("SELECT * FROM users WHERE phone=?",(ph,)): return "موجود",400
    qexec("INSERT INTO users(phone,password,role,username,active) VALUES(?,?,?,?,1)",(ph,generate_password_hash(request.form.get('password','')),request.form.get('role','tech'),ph));return "ok"
@app.route('/edit_user/<ph>',methods=['POST'])
@manager_required
def eu(ph):
    qexec("UPDATE users SET role=? WHERE phone=?",(request.form.get('role','tech'),ph));return "ok"
@app.route('/del_user/<ph>')
@manager_required
def du(ph):
    if ph=='05344851045': return "ممنوع",403
    qexec("DELETE FROM users WHERE phone=?",(ph,));return "ok"
@app.route('/change_pass',methods=['POST'])
@login_required
def cp(): qexec("UPDATE users SET password=? WHERE phone=?",(generate_password_hash(request.form.get('newpass','')),session.get('phone')));return "ok"
@app.route('/export_excel')
@manager_required
def ee():
    rs=qall("SELECT * FROM dish_ips");out=io.StringIO();w=csv.writer(out);w.writerow(['name','ip','location'])
    for r in rs: w.writerow([r['dish_name'],r['ip'],r['location']])
    return Response(out.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment;filename=dishes.csv'})
@app.route('/export_pdf')
@manager_required
def ep():
    rs=qall("SELECT * FROM dish_ips")
    h="<h1>Dishes</h1><table border=1>"+"".join([f"<tr><td>{esc(r['dish_name'])}</td><td>{esc(r['ip'])}</td></tr>" for r in rs])+"</table>"
    return h

if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
