from flask import Flask, request, redirect, session, jsonify
from colors import COLORS, logo_html
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, datetime, json, html, subprocess, platform, ipaddress, math, socket
try: import psycopg2, psycopg2.extras
except: psycopg2=None
import sqlite3

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY","omia-sec-2026-CHANGE-ME-IN-PROD")
DATABASE_URL = os.environ.get("DATABASE_URL","").strip().replace("postgresql://","postgres://")
USE_PG = bool(DATABASE_URL.startswith("postgres://") and psycopg2)
_pg = None

def esc(s): return html.escape(str(s or ''), quote=True)
def js_esc(s): return json.dumps(str(s or ''), ensure_ascii=False)  # يحل مشكلة علامات التنصيص

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
    c=sqlite3.connect("omia.db", check_same_thread=False)
    c.row_factory=sqlite3.Row
    return c

def cc(c):
    if not USE_PG:
        try:c.close()
        except:pass

def qall(q,a=()):
    c=db()
    try:
        if USE_PG:
            cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(q.replace("?","%s"),a)
            rs=[dict(r) for r in cur.fetchall()]
            cur.close()
            return rs
        else:
            rs=[dict(r) for r in c.execute(q,a).fetchall()]
            cc(c)
            return rs
    except Exception as e:
        print(e);cc(c);return []

def qone(q,a=()):
    r=qall(q,a)
    return r[0] if r else None

def qexec(q,a=()):
    c=db()
    try:
        if USE_PG:
            cur=c.cursor();cur.execute(q.replace("?","%s"),a);cur.close()
        else:
            c.execute(q,a);c.commit();cc(c)
    except Exception as e: print(f"qexec error: {e}");cc(c)

def fnum(v):
    try:return float(v or 0)
    except:return 0

# 4- إصلاح ترقية الجداول - يفحص العمود قبل الإضافة
def safe_alter(table, column, definition):
    try:
        if USE_PG:
            # في بوستغرس نتأكد
            qexec(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}")
        else:
            # في sqlite نفحص
            cols = qall(f"PRAGMA table_info({table})")
            if not any(c['name']==column for c in cols):
                qexec(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    except Exception as e:
        print(f"alter {table}.{column} : {e}")

def init():
    ss=[
    "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,active INT DEFAULT 1,username TEXT)",
    "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,active INT DEFAULT 1)",
    "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,sub_id INT,amount REAL,typ TEXT,dt TEXT,note TEXT)",
    "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,lat REAL DEFAULT 0,lng REAL DEFAULT 0,dish_name TEXT,tower_name TEXT)",
    "CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,lat REAL,lng REAL,location TEXT,fixed INT DEFAULT 0)",
    "CREATE TABLE IF NOT EXISTS activity_log(id INTEGER PRIMARY KEY AUTOINCREMENT,time TEXT,action TEXT,phone TEXT)",
    "CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,time TEXT,title TEXT,msg TEXT,read INT DEFAULT 0)"
    ]
    if USE_PG: ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
    for s in ss: qexec(s)
    # ترقية آمنة
    safe_alter("towers","location","TEXT")
    safe_alter("towers","fixed","INT DEFAULT 0")
    safe_alter("dish_ips","dish_name","TEXT")
    safe_alter("dish_ips","tower_name","TEXT")
    safe_alter("users","username","TEXT")
    safe_alter("ledger","note","TEXT")
    if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username,active) VALUES(?,?,?,?,?)",('05344851045',generate_password_hash('admin2024'),'manager','admin',1))
    if not qone("SELECT * FROM towers WHERE fixed=1"):
        qexec("INSERT INTO towers(name,lat,lng,location,fixed) VALUES(?,?,?,?,1)",('برج الحصن الرئيسي',34.723,36.715,'حمص - الحصن',1))
        qexec("INSERT INTO towers(name,lat,lng,location,fixed) VALUES(?,?,?,?,1)",('نقطة حمص المركزية',34.7324,36.7137,'حمص - المدينة',1))
    if not qone("SELECT * FROM notifications LIMIT 1"):
        qexec("INSERT INTO notifications(time,title,msg) VALUES(?,?,?)",(datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),"مرحباً بك","تم تحديث النظام للنسخة السريعة PRO"))
init()

def add_log(action):
    ph = session.get('phone','system')
    qexec("INSERT INTO activity_log(time,action,phone) VALUES(?,?,?)",(datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), action, ph))

def login_required(f):
    @wraps(f)
    def wrap(*a,**kw):
        if not session.get('phone'):
            if request.path.startswith('/api/'): return jsonify(ok=False,msg="unauthorized"),401
            return redirect('/login')
        return f(*a,**kw)
    return wrap

def manager_required(f):
    @wraps(f)
    def wrap(*a,**kw):
        if not session.get('phone'): return redirect('/login')
        m=qone("SELECT * FROM users WHERE phone=?",(session.get('phone'),))
        if not m or m.get('role')=='tech': return "ممنوع - للمدراء فقط",403
        return f(*a,**kw)
    return wrap

def me(): return qone("SELECT * FROM users WHERE phone=?",(session.get('phone'),))
def can_edit():
    m=me()
    if not m: return False
    return m.get('role')!='tech'

def is_internal_ip(ip):
    try:
        ip_o = ipaddress.ip_address(ip.strip())
        if not ip_o.is_private: return False
        if ip_o.is_loopback or ip_o.is_multicast or ip_o.is_reserved or ip_o.is_unspecified: return False
        return True
    except: return False

# 5- إصلاح الوضع الليلي - افتراضي غامق وثابت
def dark():
    return session.get('theme','dark')

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

# 6- إصلاح البينغ على الاستضافة - يمنع انهيار السيرفر
@app.route('/api/ping')
@login_required
def api_ping():
    ip=request.args.get('ip','').strip()
    if not ip: return jsonify(ok=False,out='لا يوجد IP')
    if not is_internal_ip(ip): return jsonify(ok=False,out='⛔ خارج الشبكة الداخلية - يجب 192.168.x.x')
    # على الاستضافة البينغ ممنوع - نجرب سوكت بدلا من بينغ
    try:
        # محاولة اتصال TCP سريعة للمنافذ الشائعة للصحون
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        # منافذ الميكروتك الشائعة
        for port in [80, 8291, 22]:
            try:
                result = sock.connect_ex((ip, port))
                sock.close()
                if result == 0:
                    return jsonify(ok=True,out=f'✅ {ip}:{port} متصل (TCP) - البينغ ممنوع على الاستضافة لكن الجهاز يرد')
            except: pass
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
        sock.close()
    except: pass

    try:
        w=platform.system().lower()=='windows'
        cmd=['ping','-n','2',ip] if w else ['ping','-c','2','-W','2',ip]
        o=subprocess.run(cmd,capture_output=True,text=True,timeout=5)
        out = (o.stdout or '')+(o.stderr or '')
        if not out.strip():
            out = "⚠️ البينغ معطل على هذه الاستضافة (Render/Railway تمنع ICMP). استخدم فحص TCP أعلاه أو جرب من شبكتك المحلية."
        return jsonify(ok=True,out=out[:2000])
    except Exception as e: 
        return jsonify(ok=False,out=f'البينغ غير متاح على الاستضافة: {str(e)[:200]} - استخدم جهازك المحلي للفحص')

def page_content(v):
    h=""; can = can_edit(); dis_attr = "" if can else "disabled style='opacity:.4;pointer-events:none'"
    if v=='home':
        ns=(qone("SELECT COUNT(*) c FROM subs") or {}).get('c',0)
        nd=(qone("SELECT COUNT(*) c FROM dish_ips") or {}).get('c',0)
        nt=(qone("SELECT COUNT(*) c FROM towers") or {}).get('c',0)
        logs = qall("SELECT * FROM activity_log ORDER BY id DESC LIMIT 5")
        logs_html = "".join([f"<div class=log-row><span class=log-time>{esc(l['time'])}</span><span class=log-phone>👤 {esc(l['phone'])}</span><span>{esc(l['action'])}</span></div>" for l in logs])
        h=f"""
        <div class=stats-grid>
          <div class="card stat-card"><div class=stat-icon>📡</div><div><h3>عدد الصحون</h3><h2>{nd}</h2></div></div>
          <div class="card stat-card"><div class=stat-icon>🗼</div><div><h3>عدد الأبراج</h3><h2>{nt}</h2></div></div>
          <div class="card stat-card"><div class=stat-icon>👥</div><div><h3>عدد الحسابات</h3><h2>{ns}</h2></div></div>
        </div>
        <div class="card"><h3>⚡ فحص الشبكة السريع</h3><div class=ping-box><input id=ping_ip placeholder="192.168.1.1"><button class=btn-blue onclick="doPing()">بينغ</button></div><pre id=ping_out>جاهز...</pre><small style='color:#94a3b8'>على الاستضافة سيتم فحص TCP لأن ICMP ممنوع</small></div>
        <div class="card"><h3>📜 آخر النشاطات - مين داخل الموقع</h3>{logs_html}<button class=btn onclick="loadPage('logs')">عرض الكل</button></div>
        <script>async function doPing(){{let i=document.getElementById("ping_ip").value;let o=document.getElementById("ping_out");if(!i){{o.textContent="ادخل IP";return}} o.textContent="⏳ جاري الفحص...";let r=await fetch("/api/ping?ip="+encodeURIComponent(i));let j=await r.json();o.textContent=j.out}}</script>
        """
        return h
    elif v=='subs':
        rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 200")
        rows=""
        for r in rs:
            # 3- إصلاح علامات التنصيص - استخدام js_esc
            name_js = js_esc(r['name'])
            phone_js = js_esc(r['phone'])
            rows+=f"<div class='card sub-card'><div><b>{esc(r['name'])}</b><br><small>📞 {esc(r['phone'])}</small></div><div class=actions><button class=btn-blue onclick='editSub({r['id']}, {name_js}, {phone_js})'>تعديل</button><a href=/del_sub/{r['id']} data-del class=btn-red {dis_attr}>حذف</a></div></div>"
        h=f"<div class=card><h3>👥 المشتركين - عربي</h3><form data-ajax method=post action=/add_sub class=form-row><input name=name required placeholder='الاسم الكامل'><input name=phone placeholder='رقم الهاتف'><button class=btn-gold>اضافة</button></form></div><div class=subs-list>{rows}</div>"
        h+="""
        <div id=editModal class=modal><div class=modal-content><h3>تعديل مشترك</h3><form id=editForm method=post><input type=hidden name=id id=edit_id><input name=name id=edit_name required><input name=phone id=edit_phone><div style="display:flex;gap:8px;margin-top:10px"><button class=btn-gold>حفظ</button><button type=button class=btn onclick="closeModal()">الغاء</button></div></form></div></div>
        <script>
        function editSub(id,name,phone){document.getElementById('edit_id').value=id;document.getElementById('edit_name').value=name;document.getElementById('edit_phone').value=phone;document.getElementById('editModal').style.display='flex';document.getElementById('editForm').action='/edit_sub/'+id}
        function closeModal(){document.getElementById('editModal').style.display='none'}
        window.onclick=function(e){if(e.target==document.getElementById('editModal'))closeModal()}
        </script>
        """
        return h
    elif v=='dishes':
        rs=qall("SELECT * FROM dish_ips ORDER BY id DESC LIMIT 200")
        cards=""
        for r in rs:
            ip=esc(r.get('ip') or '')
            dname = esc(r.get('dish_name') or 'بدون اسم')
            dname_js = js_esc(r.get('dish_name') or '')
            loc = esc(r.get('location') or '')
            loc_js = js_esc(r.get('location') or '')
            # إصلاح التنصيص
            cards+=f"<div class='card dish-card'><div class=dish-head><b>📡 {dname}</b><span class=ip-badge>{ip}</span></div><small>📍 {loc}</small><div class=actions style='margin-top:8px'><button class=btn-blue onclick='pingDish(\"{ip}\")'>بينغ</button><button class=btn-blue onclick='editDish({r['id']}, {dname_js}, \"{ip}\", {loc_js})'>تعديل</button><a href=/del_dish/{r['id']} data-del class=btn-red {dis_attr}>حذف</a></div></div>"
        h=f"<div class=card><h3>📡 الصحون - سطرين قبال بعض (نص شاشة)</h3><form data-ajax method=post action=/add_dish class=form-row><input name=dish_name required placeholder='اسم الصحن'><input name=ip required placeholder='IP داخلي 192.168.x.x'><input name=location placeholder='الموقع'><button class=btn-gold>اضافة</button></form><small style='color:#94a3b8'>* يتم التأكد من الـ IP تلقائياً</small></div><div class=dishes-grid>{cards}</div>"
        h+="""
        <div id=editDishModal class=modal><div class=modal-content><h3>تعديل صحن</h3><form id=editDishForm method=post><input name=dish_name id=edit_dish_name required><input name=ip id=edit_dish_ip required><input name=location id=edit_dish_loc><div style="display:flex;gap:8px;margin-top:10px"><button class=btn-gold>حفظ</button><button type=button class=btn onclick="document.getElementById('editDishModal').style.display='none'">الغاء</button></div></form></div></div>
        <script>function editDish(id,name,ip,loc){document.getElementById('edit_dish_name').value=name;document.getElementById('edit_dish_ip').value=ip;document.getElementById('edit_dish_loc').value=loc;document.getElementById('editDishModal').style.display='flex';document.getElementById('editDishForm').action='/edit_dish/'+id}</script>
        """
        return h
    elif v=='towers':
        rs=qall("SELECT * FROM towers ORDER BY fixed DESC, id DESC LIMIT 200")
        cards=""
        for r in rs:
            is_fixed = r.get('fixed')
            badge = "<span class=fixed-badge>🔒 نقطة ثابتة</span>" if is_fixed else ""
            delbtn = "" if is_fixed else f"<a href=/del_tower/{r['id']} data-del class=btn-red {dis_attr}>حذف</a>"
            tname_js = js_esc(r['name'])
            tloc_js = js_esc(r.get('location') or '')
            cards+=f"<div class='card tower-card'><div><b>🗼 {esc(r['name'])} {badge}</b><br><small>📍 موقع البرج: {esc(r.get('location') or '')}</small><br><small>🌐 احداثية: {r.get('lat',0)}, {r.get('lng',0)}</small></div><div class=actions>{delbtn}<button class=btn-blue onclick='editTower({r['id']}, {tname_js}, {tloc_js}, \"{r.get('lat',0)}\", \"{r.get('lng',0)}\")'>تعديل</button></div></div>"
        h=f"<div class=card><h3>🗼 الأبراج - اسم + موقع + احداثية</h3><form data-ajax method=post action=/add_tower class=form-row><input name=name required placeholder='اسم البرج'><input name=location placeholder='موقع البرج'><input name=lat placeholder='خط العرض'><input name=lng placeholder='خط الطول'><label style='display:flex;align-items:center;gap:6px'><input type=checkbox name=fixed value=1> نقطة ثابتة</label><button class=btn-gold>اضافة</button></form></div><div class=towers-list>{cards}</div>"
        h+="""
        <div id=editTowerModal class=modal><div class=modal-content><h3>تعديل برج</h3><form id=editTowerForm method=post><input name=name id=edit_tower_name required><input name=location id=edit_tower_loc><input name=lat id=edit_tower_lat><input name=lng id=edit_tower_lng><div style="display:flex;gap:8px;margin-top:10px"><button class=btn-gold>حفظ</button><button type=button class=btn onclick="document.getElementById('editTowerModal').style.display='none'">الغاء</button></div></form></div></div>
        <script>function editTower(id,name,loc,lat,lng){document.getElementById('edit_tower_name').value=name;document.getElementById('edit_tower_loc').value=loc;document.getElementById('edit_tower_lat').value=lat;document.getElementById('edit_tower_lng').value=lng;document.getElementById('editTowerModal').style.display='flex';document.getElementById('editTowerForm').action='/edit_tower/'+id}</script>
        """
        return h
    elif v=='ledger':
        rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 100")
        h="<div class=card><h3>📒 دفتر الحسابات</h3><form data-ajax method=post action=/add_ledger><input name=amount type=number step=0.01 required placeholder=مبلغ><select name=typ><option>دين</option><option>دفع</option></select><button>اضافة</button></form></div>"
        for r in rs: h+=f"<div class=card>{r['amount']} {esc(r['typ'])} <a href=/del_ledger/{r['id']} data-del style='color:red'>حذف</a></div>"
        return h
    elif v=='map':
        towers = qall("SELECT * FROM towers")
        towers_js = json.dumps([{"name": t['name'], "lat": float(t.get('lat') or 0), "lng": float(t.get('lng') or 0), "loc": str(t.get('location') or ''), "fixed": bool(t.get('fixed'))} for t in towers], ensure_ascii=False)
        h=f"""
        <div class=card>
          <h3>📏 قياس المسافة - يطلع الرقم بدون ما تتحرك الصفحة</h3>
          <div class=dist-grid>
            <input id=lat1 placeholder='خط العرض 1 - 34.73'>
            <input id=lng1 placeholder='خط الطول 1 - 36.71'>
            <input id=lat2 placeholder='خط العرض 2'>
            <input id=lng2 placeholder='خط الطول 2'>
          </div>
          <button class=btn-gold onclick='calcDist()' style='width:100%;margin-top:10px'>احسب المسافة الآن</button>
          <div id=distResult class=dist-result>ادخل الاحداثيات واضغط احسب</div>
        </div>
        <div class=card>
          <h3>🗺 الخريطة - دقة عالية - عربي كامل</h3>
          <div id=map style='height:420px;border-radius:12px'></div>
          <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
          <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
          <script>
            let map = L.map('map').setView([34.7324, 36.7137], 11);
            L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{ attribution: 'OMAIA ISP - خريطة عربية' }}).addTo(map);
            let towers = {towers_js};
            towers.forEach(t=>{{
              let m = L.marker([t.lat, t.lng]).addTo(map);
              m.bindPopup(`<b>${{t.name}}</b><br>${{t.loc}}<br>${{t.lat}}, ${{t.lng}}<br>${{t.fixed ? '🔒 نقطة ثابتة' : ''}}`);
            }});
            window.haversine=function(lat1, lon1, lat2, lon2){{
              const R=6371; const dLat=(lat2-lat1)*Math.PI/180; const dLon=(lon2-lon1)*Math.PI/180;
              const a=Math.sin(dLat/2)**2 + Math.cos(lat1*Math.PI/180)*Math.cos(lat2*Math.PI/180)*Math.sin(dLon/2)**2;
              return R*2*Math.atan2(Math.sqrt(a),Math.sqrt(1-a));
            }}
            window.calcDist=function(){{
              let lat1=parseFloat(document.getElementById('lat1').value);
              let lng1=parseFloat(document.getElementById('lng1').value);
              let lat2=parseFloat(document.getElementById('lat2').value);
              let lng2=parseFloat(document.getElementById('lng2').value);
              let out=document.getElementById('distResult');
              if([lat1,lng1,lat2,lng2].some(isNaN)){{out.innerHTML="<span style='color:red'>⚠ ادخل الاحداثيات الأربعة</span>";return}}
              let d=haversine(lat1,lng1,lat2,lng2);
              out.innerHTML=`<div style='font-size:22px'>📍 المسافة: <b style='color:{COLORS['gold']}'>${{d.toFixed(3)}} كم</b></div><small>${{ (d*1000).toFixed(0) }} متر</small>`;
            }}
          </script>
        </div>
        <div class=card><h3>📌 النقاط الثابتة مع الاسم - ما بتنمسح</h3>
        """
        fixed = qall("SELECT * FROM towers WHERE fixed=1")
        for t in fixed:
            h+=f"<div class=fixed-item><b>🔒 {esc(t['name'])}</b> - {esc(t['location'])} <small>({t['lat']},{t['lng']})</small></div>"
        h+="</div>"
        return h
    elif v=='logs':
        rs=qall("SELECT * FROM activity_log ORDER BY id DESC LIMIT 200")
        rows="".join([f"<div class=log-row><span class=log-time>{esc(r['time'])}</span><span class=log-phone>👤 {esc(r['phone'])}</span><span>{esc(r['action'])}</span></div>" for r in rs])
        h=f"<div class=card><h3>📜 سجل النشاطات - الي داخل الموقع</h3><div class=logs-container>{rows}</div></div>"
        return h
    elif v=='notifications':
        rs=qall("SELECT * FROM notifications ORDER BY id DESC LIMIT 100")
        rows="".join([f"<div class='card notif-card'><div><b>{esc(r['title'])}</b><br><small>{esc(r['time'])}</small><p>{esc(r['msg'])}</p></div></div>" for r in rs])
        h=f"<div class=card><h3>🔔 الإشعارات</h3><button class=btn-blue onclick='fetch(\"/clear_notifs\").then(()=>loadPage(\"notifications\"))'>مسح الكل</button></div>{rows if rows else '<div class=card>لا يوجد اشعارات</div>'}"
        return h
    elif v=='support':
        h=f"""
        <div class=card style='text-align:center;border:2px solid {COLORS['gold']}'>
          <h3>🎧 الدعم الفني OMAIA</h3>
          <p>نحن هنا لمساعدتك 24/7</p>
          <div style='font-size:20px;margin:10px' dir=ltr>+90 534 485 10 45</div>
          <a href='https://wa.me/905344851045' target=_blank class=btn-wa>💬 واتساب مباشر</a>
          <a href='tel:+905344851045' class=btn-blue style='margin-top:8px;display:inline-block;text-decoration:none'>📞 اتصال</a>
        </div>
        """
        return h
    elif v=='settings':
        us=qall("SELECT phone,username,role FROM users ORDER BY phone");uh=""
        for u in us: ph=esc(u['phone']);un=esc(u.get('username') or u['phone']);role=esc(u.get('role') or '');uh+=f"<div class='card user-card'><div class=avatar>{un[:1]}</div><div><b>{un}</b><br><small>📞 {ph} - {role}</small></div><div><a href=/del_user/{ph} data-del class=btn-red>حذف</a></div></div>"
        h=f"""
        <div class=card style='max-width:600px;margin:10px auto'><h3>⚙ إعدادات - User / Phone</h3><p>الحالي: <b>{esc(session.get('phone'))}</b></p><form data-ajax method=post action=/change_pass><input name=newpass type=password required placeholder='كلمة السر الجديدة'><button class=btn-gold style='width:100%'>تغيير كلمة السر</button></form><form data-ajax method=post action=/toggle_theme style='margin-top:10px'><button class=btn style='width:100%'>🌙/☀ تبديل الثيم</button></form></div>
        <div class=card style='max-width:600px;margin:10px auto'><h3>➕ اضافة مستخدم - User / Phone</h3><form data-ajax method=post action=/add_user class=form-row><input name=phone required placeholder='يوزر / رقم'><input name=password type=password required placeholder='كلمة السر'><select name=role><option value=tech>فني</option><option value=manager>مدير</option></select><button class=btn-gold>اضافة</button></form></div>
        <div style='max-width:600px;margin:10px auto'><h3>المستخدمين</h3>{uh}</div>
        """
        return h
    return "ok"

def layout(c,v='home'):
    th=dark()
    bg=COLORS['bg_dark'] if th=='dark' else COLORS['bg_light']
    card=COLORS['card_dark'] if th=='dark' else COLORS['card_light']
    txt='#fff' if th=='dark' else '#000'
    return f"""<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
:root{{--gold:{COLORS['gold']};--bg:{bg};--card:{card};--text:{txt};--border:{COLORS['border_dark']};--input:{COLORS['input_dark']};--blue:{COLORS['btn_blue']};--red:{COLORS['btn_red']}}}
*{{box-sizing:border-box;font-family:'Cairo',sans-serif}}body{{margin:0;background:var(--bg);color:var(--text);overflow-x:hidden}}
.loader{{position:fixed;inset:0;background:var(--bg);z-index:9999;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;transition:opacity .4s, visibility .4s}}
.loader.hidden{{opacity:0;visibility:hidden}}
.loader .spinner{{width:48px;height:48px;border:4px solid var(--border);border-top:4px solid var(--gold);border-radius:50%;animation:spin 1s linear infinite}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
/* 2- إصلاح مقاس القائمة الجانبية */
.sidebar{{position:fixed;right:-320px;top:0;width:300px;height:100%;background:{COLORS['menu_bg']};transition:all .4s cubic-bezier(0.4,0,0.2,1);z-index:1000;padding-top:70px;box-shadow:-10px 0 30px rgba(0,0,0,0.5);overflow-y:auto}}
.sidebar.active{{right:0}}
.sidebar a{{display:flex;align-items:center;gap:12px;padding:15px 18px;color:#fff;text-decoration:none;transition:all .25s;border-right:4px solid transparent;margin:3px 8px;border-radius:10px}}
.sidebar a:hover{{background:#ffffff15;border-right-color:var(--gold);transform:translateX(-4px)}}
.sidebar a.active{{background:linear-gradient(90deg,var(--gold) 20%, transparent 100%);color:#000;font-weight:bold;border-right-color:var(--gold)}}
.overlay{{position:fixed;inset:0;background:rgba(0,0,0,0.6);backdrop-filter:blur(5px);display:none;z-index:999;opacity:0;transition:opacity .3s}}
.overlay.active{{display:block;opacity:1}}
.top{{position:fixed;top:0;left:0;right:0;background:{COLORS['top_bg']};backdrop-filter:blur(10px);padding:12px 18px;z-index:101;display:flex;align-items:center;justify-content:space-between;box-shadow:0 4px 20px rgba(0,0,0,0.3);border-bottom:1px solid var(--border)}}
.menu-btn{{font-size:24px;cursor:pointer;background:var(--input);width:42px;height:42px;display:flex;align-items:center;justify-content:center;border-radius:10px;transition:.2s}}
.menu-btn:hover{{background:var(--gold);color:#000;transform:scale(1.05)}}
.main{{margin-right:300px;margin-top:65px;padding:14px;min-height:100vh;transition:margin .4s}}
.stats-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:12px}}
.stat-card{{display:flex;align-items:center;gap:10px;padding:14px !important}}
.stat-card h3{{font-size:12px;color:#94a3b8;margin:0}} .stat-card h2{{font-size:24px;color:var(--gold);margin:2px 0 0}} .stat-icon{{font-size:28px;background:var(--input);width:46px;height:46px;display:flex;align-items:center;justify-content:center;border-radius:10px}}
.card{{background:{card};padding:16px;border-radius:14px;margin-bottom:10px;animation:slideUp .4s;border:1px solid {COLORS['border_dark']};box-shadow:0 4px 12px rgba(0,0,0,0.2)}}
@keyframes slideUp{{from{{opacity:0;transform:translateY(12px)}}to{{opacity:1;transform:translateY(0)}}}}
.btn{{background:var(--input);border:none;color:var(--text);padding:8px 14px;border-radius:8px;cursor:pointer;font-weight:bold}}
.btn-gold{{background:var(--gold);color:#000;padding:10px 16px;border-radius:8px;border:none;font-weight:bold;cursor:pointer}}
.btn-blue{{background:var(--blue);color:#fff;padding:8px 14px;border-radius:8px;border:none;cursor:pointer}}
.btn-red{{background:var(--red);color:#fff;padding:8px 14px;border-radius:8px;border:none;cursor:pointer;text-decoration:none}}
.btn-wa{{background:#25D366;color:#fff;padding:10px 18px;border-radius:20px;text-decoration:none;display:inline-block;font-weight:bold}}
input,select{{width:100%;padding:11px;background:var(--input);border:1px solid var(--border);border-radius:10px;color:var(--text);margin:4px 0}}
input:focus{{outline:none;border-color:var(--gold)}}
.form-row{{display:grid;grid-template-columns:1fr 1fr auto;gap:8px;align-items:end}}
@media(max-width:900px){{.main{{margin-right:0}}.form-row{{grid-template-columns:1fr}}.dishes-grid{{grid-template-columns:1fr !important}}.sidebar{{width:280px}}}}
.dishes-grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
.dish-card{{border-right:4px solid var(--gold)}} .ip-badge{{background:var(--input);padding:2px 8px;border-radius:10px;font-size:11px;color:var(--gold);font-family:monospace}}
.fixed-badge{{background:var(--gold);color:#000;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:bold}} .fixed-item{{background:var(--input);padding:10px;border-radius:8px;margin:6px 0;border-right:3px solid var(--gold)}}
.sub-card,.tower-card{{display:flex;justify-content:space-between;align-items:center}}
.actions{{display:flex;gap:6px;flex-wrap:wrap}} .ping-box{{display:flex;gap:8px;margin:10px 0}}
pre{{background:#000;color:#0f0;padding:12px;border-radius:10px;min-height:50px;overflow:auto;font-size:12px}}
.log-row{{display:flex;gap:8px;padding:8px;border-bottom:1px solid var(--border);font-size:12px}} .log-time{{color:#94a3b8;min-width:80px}} .log-phone{{color:var(--gold);font-weight:bold;min-width:100px}}
.dist-grid{{display:grid;grid-template-columns:1fr 1fr;gap:8px}} .dist-result{{background:var(--input);padding:14px;border-radius:10px;margin-top:10px;text-align:center;border:2px dashed var(--gold);min-height:55px}}
.modal{{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:2000;align-items:center;justify-content:center;backdrop-filter:blur(6px)}} .modal-content{{background:var(--card);padding:20px;border-radius:14px;width:90%;max-width:380px;animation:slideUp .3s}}
.user-card{{display:flex;align-items:center;gap:10px;justify-content:space-between}} .avatar{{width:40px;height:40px;border-radius:50%;background:var(--gold);display:flex;align-items:center;justify-content:center;font-weight:bold;color:#000}}
#loader-line{{position:fixed;top:0;left:0;height:3px;background:var(--gold);width:0;z-index:200;transition:.25s}}
</style></head><body>
<div class=loader id=loader><div class=spinner></div><div>جاري التحميل...</div><small style='color:#94a3b8'>OMAIA ISP PRO</small></div>
<div id=loader-line></div>
<div class=overlay id=overlay onclick='toggleMenu()'></div>
<div class=sidebar id=sidebar>
<a href="javascript:loadPage('home')" id=nav-home>🏠 الرئيسية</a>
<a href="javascript:loadPage('subs')" id=nav-subs>👥 المشتركين</a>
<a href="javascript:loadPage('dishes')" id=nav-dishes>📡 الصحون</a>
<a href="javascript:loadPage('towers')" id=nav-towers>🗼 الأبراج</a>
<a href="javascript:loadPage('ledger')" id=nav-ledger>📒 دفتر الحسابات</a>
<a href="javascript:loadPage('map')" id=nav-map>🗺 الخريطة وقياس المسافة</a>
<a href="javascript:loadPage('logs')" id=nav-logs>📜 سجل النشاطات</a>
<a href="javascript:loadPage('notifications')" id=nav-notifications>🔔 الإشعارات</a>
<a href="javascript:loadPage('support')" id=nav-support>🎧 الدعم الفني</a>
<a href="javascript:loadPage('settings')" id=nav-settings>⚙ الإعدادات User/Phone</a>
<a href=/logout style='color:var(--red);margin-top:18px;border-top:1px solid var(--border)'>🚪 خروج</a>
</div>
<div class=top><div class=menu-btn onclick='toggleMenu()'>☰</div><div>{logo_html()}</div><div style='background:var(--gold);color:#000;padding:4px 10px;border-radius:20px;font-size:11px;font-weight:bold'>PRO</div></div>
<div class=main id=main>{c}</div>
<script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>
<script>
let currentPage='{v}';
function toggleMenu(){{let s=document.getElementById('sidebar'), o=document.getElementById('overlay');s.classList.toggle('active');o.classList.toggle('active');document.body.style.overflow=s.classList.contains('active')?'hidden':''}}
function showLoader(){{document.getElementById('loader').classList.remove('hidden');document.getElementById('loader-line').style.width='40%';}}
function hideLoader(){{document.getElementById('loader').classList.add('hidden');let l=document.getElementById('loader-line');l.style.width='100%';setTimeout(()=>l.style.width='0',300);}}
window.loadPage=async function(v){{
  if(document.getElementById('sidebar').classList.contains('active'))toggleMenu();
  currentPage=v;
  document.querySelectorAll('.sidebar a').forEach(a=>a.classList.remove('active'));
  let nav=document.getElementById('nav-'+v);if(nav)nav.classList.add('active');
  showLoader();
  try{{
    let r=await fetch('/api/page?v='+v);
    if(r.status==401){{location.href='/login';return}}
    let html=await r.text();
    document.getElementById('main').innerHTML=html;
    bindAjax();
    document.getElementById('main').querySelectorAll('script').forEach(s=>{{try{{eval(s.textContent)}}catch(e){{}}}});
  }}catch(e){{document.getElementById('main').innerHTML='<div class=card style=color:red>خطأ: '+e+'</div>'}}
  setTimeout(hideLoader, 350);
  window.scrollTo({{top:0,behavior:'smooth'}});
}}
function bindAjax(){{
  document.querySelectorAll('form[data-ajax]').forEach(f=>{{
    f.onsubmit=async e=>{{e.preventDefault();showLoader();try{{let res=await fetch(f.action,{{method:'POST',body:new FormData(f)}});if(res.status==401){{location.href='/login';return}}if(!res.ok){{let t=await res.text();alert('خطأ: '+t);hideLoader();return}}loadPage(currentPage);}}catch(e){{alert('خطأ: '+e);hideLoader()}}}};
  }});
  document.querySelectorAll('a[data-del]').forEach(a=>{{
    a.onclick=async e=>{{e.preventDefault();if(!confirm('⚠ تأكيد الحذف؟'))return;showLoader();let res=await fetch(a.href);if(res.status==401){{location.href='/login';return}}loadPage(currentPage);}};
  }});
  document.querySelectorAll('a[data-ajax]').forEach(a=>{{
    a.onclick=async e=>{{e.preventDefault();await fetch(a.href);loadPage(currentPage)}};
  }});
}}
function pingDish(ip){{if(!ip){{alert('لا يوجد IP');return}}showLoader();fetch('/api/ping?ip='+encodeURIComponent(ip)).then(r=>r.json()).then(j=>{{hideLoader();alert(j.out.slice(0,400))}}).catch(()=>hideLoader())}}
document.addEventListener('keydown', e=>{{if(e.key==='Escape' && document.getElementById('sidebar').classList.contains('active'))toggleMenu()}});
window.addEventListener('load', ()=>setTimeout(hideLoader, 500));
bindAjax();
</script></body></html>"""

@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        uin=request.form.get('userin','').strip()
        pw=request.form.get('password','')
        u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
        if u and check_password_hash(u['password'], pw):
            if not u.get('active'): return "الحساب معطل",403
            session['phone']=u['phone']
            add_log(f"تسجيل دخول User/Phone: {uin}")
            return redirect('/dash')
        return f"<script>alert('بيانات خاطئة User/Phone');location.href='/login'</script>",401
    # 1- إصلاح لون زر الدخول
    return f"""<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>Login OMAIA</title>
<style>
body{{display:flex;align-items:center;justify-content:center;background:{COLORS['bg_dark']};min-height:100vh;margin:0;font-family:'Cairo',sans-serif}}
.box{{background:#fff;padding:28px;border-radius:16px;width:92%;max-width:360px;box-shadow:0 20px 40px rgba(0,0,0,0.4)}}
input{{width:100%;padding:12px;margin:8px 0;border-radius:10px;border:1px solid #ccc;font-size:14px}}
button.login-btn{{width:100%;background:{COLORS['gold']};color:#000;padding:13px;border:0;border-radius:10px;font-weight:900;font-size:16px;cursor:pointer;margin-top:12px;transition:all .2s}}
button.login-btn:hover{{background:{COLORS['gold_hover']};transform:scale(1.02)}}
</style>
</head><body><div class=box><h3 style='text-align:center'>{logo_html()}</h3><p style='text-align:center;color:#64748b;font-size:12px'>تسجيل دخول User / Phone</p>
<form method=post><input name=userin placeholder='رقم هاتف / اسم مستخدم' required><input name=password type=password placeholder='كلمة السر' required><button class=login-btn>دخول للنظام</button></form></div></body></html>"""

@app.route('/logout')
def lo():
    add_log("تسجيل خروج");session.clear();return redirect('/login')

@app.route('/dash')
def dash():
    if not session.get('phone'): return redirect('/login')
    v=request.args.get('v','home')
    return layout(page_content(v),v)

@app.route('/api/page')
def ap():
    if not session.get('phone'): return "login"
    return page_content(request.args.get('v','home'))

@app.route('/toggle_theme',methods=['POST','GET'])
def toggle_theme():
    cur = session.get('theme','dark')
    session['theme'] = 'light' if cur=='dark' else 'dark'
    return "ok"

@app.route('/add_sub',methods=['POST'])
@login_required
def a1():
    qexec("INSERT INTO subs(name,phone) VALUES(?,?)",(request.form.get('name',''),request.form.get('phone','')))
    add_log(f"اضافة مشترك: {request.form.get('name','')}")
    return "ok"

@app.route('/edit_sub/<int:i>',methods=['POST'])
@login_required
def edit_sub(i):
    qexec("UPDATE subs SET name=?, phone=? WHERE id=?",(request.form.get('name',''),request.form.get('phone',''),i))
    add_log(f"تعديل مشترك {i}")
    return "ok"

@app.route('/del_sub/<int:i>')
@manager_required
def a4(i):
    qexec("DELETE FROM subs WHERE id=?",(i,))
    add_log(f"حذف مشترك {i}")
    return "ok"

@app.route('/add_ledger',methods=['POST'])
@login_required
def b1():
    f=request.form
    qexec("INSERT INTO ledger(amount,typ,dt) VALUES(?,?,?)",(fnum(f.get('amount')),f.get('typ','دين'),datetime.datetime.now().isoformat()))
    return "ok"

@app.route('/del_ledger/<int:i>')
@manager_required
def b2(i):
    qexec("DELETE FROM ledger WHERE id=?",(i,))
    return "ok"

@app.route('/add_dish',methods=['POST'])
@login_required
def c1():
    f=request.form; ip=f.get('ip','').strip()
    if not is_internal_ip(ip): return f"IP {ip} غير داخلي",400
    if qone("SELECT * FROM dish_ips WHERE ip=?",(ip,)): return "IP موجود مسبقاً",400
    qexec("INSERT INTO dish_ips(ip,location,lat,lng,dish_name) VALUES(?,?,?,?,?)",(ip,f.get('location',''),fnum(f.get('lat')),fnum(f.get('lng')),f.get('dish_name','')))
    add_log(f"اضافة صحن: {f.get('dish_name','')} {ip}")
    return "ok"

@app.route('/edit_dish/<int:i>',methods=['POST'])
@login_required
def edit_dish(i):
    f=request.form; ip=f.get('ip','').strip()
    if not is_internal_ip(ip): return "IP غير داخلي",400
    qexec("UPDATE dish_ips SET ip=?, location=?, dish_name=? WHERE id=?",(ip,f.get('location',''),f.get('dish_name',''),i))
    add_log(f"تعديل صحن {i}")
    return "ok"

@app.route('/del_dish/<int:i>')
@manager_required
def c2(i):
    qexec("DELETE FROM dish_ips WHERE id=?",(i,))
    add_log(f"حذف صحن {i}")
    return "ok"

@app.route('/add_tower',methods=['POST'])
@login_required
def d1():
    f=request.form; fixed=1 if f.get('fixed') else 0
    qexec("INSERT INTO towers(name,lat,lng,location,fixed) VALUES(?,?,?,?,?)",(f.get('name',''),fnum(f.get('lat')),fnum(f.get('lng')),f.get('location',''),fixed))
    add_log(f"اضافة برج: {f.get('name','')} {'ثابت' if fixed else ''}")
    return "ok"

@app.route('/edit_tower/<int:i>',methods=['POST'])
@login_required
def edit_tower(i):
    f=request.form
    qexec("UPDATE towers SET name=?, lat=?, lng=?, location=? WHERE id=?",(f.get('name',''),fnum(f.get('lat')),fnum(f.get('lng')),f.get('location',''),i))
    add_log(f"تعديل برج {i}")
    return "ok"

@app.route('/del_tower/<int:i>')
@manager_required
def d2(i):
    t=qone("SELECT * FROM towers WHERE id=?",(i,))
    if not t: return "غير موجود",404
    if t.get('fixed'): return "⛔ نقطة ثابتة لا تحذف",403
    qexec("DELETE FROM towers WHERE id=?",(i,))
    add_log(f"حذف برج {t['name']}")
    return "ok"

@app.route('/change_user',methods=['POST'])
@login_required
def e1():
    o=session.get('phone')
    n=request.form.get('newphone','').strip()
    if n.isdigit():
        qexec("UPDATE users SET phone=? WHERE phone=?",(n,o))
        session['phone']=n
    else:
        qexec("UPDATE users SET username=? WHERE phone=?",(n,o))
    add_log(f"تغيير User/Phone الى {n}")
    return "ok"

@app.route('/change_pass',methods=['POST'])
@login_required
def e2():
    qexec("UPDATE users SET password=? WHERE phone=?",(generate_password_hash(request.form.get('newpass','')),session.get('phone')))
    add_log("تغيير كلمة السر")
    return "ok"

@app.route('/add_user',methods=['POST'])
@manager_required
def add_user():
    f=request.form; ph=f.get('phone','').strip()
    if qone("SELECT * FROM users WHERE phone=?",(ph,)): return "موجود",400
    qexec("INSERT INTO users(phone,password,role,username,active) VALUES(?,?,?,?,1)",(ph,generate_password_hash(f.get('password','')),f.get('role','tech'),ph))
    add_log(f"اضافة مستخدم User/Phone: {ph}")
    return "ok"

@app.route('/del_user/<ph>')
@manager_required
def del_user(ph):
    if ph=='05344851045': return "لا يمكن حذف الادمن الرئيسي",403
    if ph==session.get('phone'): return "لا يمكن حذف نفسك",400
    qexec("DELETE FROM users WHERE phone=?",(ph,))
    add_log(f"حذف مستخدم {ph}")
    return "ok"

@app.route('/clear_notifs')
@login_required
def clear_notifs():
    qexec("DELETE FROM notifications")
    return "ok"

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
