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
def js_esc(s): return json.dumps(str(s or ''), ensure_ascii=False)

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

def safe_alter(table, column, definition):
    try:
        if USE_PG:
            qexec(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}")
        else:
            cols = qall(f"PRAGMA table_info({table})")
            if not any(c['name']==column for c in cols):
                qexec(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    except Exception as e:
        print(f"alter {table}.{column} : {e}")

def init():
    ss=[
    "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,active INT DEFAULT 1,username TEXT)",
    "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,active INT DEFAULT 1)",
    "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,amount REAL,typ TEXT,dt TEXT,note TEXT,currency TEXT)",
    "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,lat REAL DEFAULT 0,lng REAL DEFAULT 0,dish_name TEXT,tower_name TEXT)",
    "CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,lat REAL,lng REAL,location TEXT,fixed INT DEFAULT 0,area TEXT)",
    "CREATE TABLE IF NOT EXISTS activity_log(id INTEGER PRIMARY KEY AUTOINCREMENT,time TEXT,action TEXT,phone TEXT)",
    "CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,time TEXT,title TEXT,msg TEXT,read INT DEFAULT 0)"
    ]
    if USE_PG: ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
    for s in ss: qexec(s)
    safe_alter("towers","location","TEXT")
    safe_alter("towers","fixed","INT DEFAULT 0")
    safe_alter("towers","area","TEXT")
    safe_alter("dish_ips","dish_name","TEXT")
    safe_alter("dish_ips","tower_name","TEXT")
    safe_alter("users","username","TEXT")
    safe_alter("ledger","note","TEXT")
    safe_alter("ledger","currency","TEXT")
    safe_alter("ledger","name","TEXT")
    if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username,active) VALUES(?,?,?,?,?)",('05344851045',generate_password_hash('admin2024'),'manager','admin',1))
    if not qone("SELECT * FROM towers WHERE fixed=1"):
        qexec("INSERT INTO towers(name,lat,lng,location,area,fixed) VALUES(?,?,?,?,?,1)",('نقطة حماة الرئيسية',35.1318,36.7578,'حماة','حماة',1))
    # 7- شيل مربحا بك ونظام omaia جاهز
    # لا نضيف اشعار افتراضي
init()

def add_log(action):
    ph = session.get('phone','system')
    qexec("INSERT INTO activity_log(time,action,phone) VALUES(?,?,?)",(datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), action, ph))
    # 7- فعل الاشعارات - اضف اشعار لكل نشاط مهم
    if any(k in action for k in ["اضافة","حذف","تعديل","دخول"]):
        qexec("INSERT INTO notifications(time,title,msg) VALUES(?,?,?)",(datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),"نشاط جديد",action))

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

def is_tech():
    m=me()
    return m and m.get('role')=='tech'

def is_internal_ip(ip):
    try:
        ip_o = ipaddress.ip_address(ip.strip())
        if not ip_o.is_private: return False
        if ip_o.is_loopback or ip_o.is_multicast or ip_o.is_reserved or ip_o.is_unspecified: return False
        return True
    except: return False

def cur_theme(): return session.get('theme','dark')
def cur_lang(): return session.get('lang','ar')

@app.route('/api/ping')
@login_required
def api_ping():
    ip=request.args.get('ip','').strip()
    if not ip: return jsonify(ok=False,out='لا يوجد IP')
    if not is_internal_ip(ip): return jsonify(ok=False,out='⛔ خارج الشبكة')
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.5)
        for port in [80, 8291, 8728, 22]:
            try:
                result = sock.connect_ex((ip, port))
                sock.close()
                if result == 0:
                    return jsonify(ok=True,out=f'✅ {ip}:{port} متصل')
            except: pass
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.5)
        sock.close()
    except: pass
    try:
        w=platform.system().lower()=='windows'
        cmd=['ping','-n','2',ip] if w else ['ping','-c','2','-W','2',ip]
        o=subprocess.run(cmd,capture_output=True,text=True,timeout=4)
        out = (o.stdout or '')+(o.stderr or '')
        return jsonify(ok=True,out=out[:1500])
    except Exception as e: 
        return jsonify(ok=False,out=f'غير متاح: {str(e)[:200]}')

def page_content(v):
    h=""; can = can_edit(); tech = is_tech()
    dis_attr = "" if can else "disabled style='opacity:.3;pointer-events:none'"
    lang = cur_lang()
    # صلاحيات الفني
    edit_btn_attr = "" if can else "disabled style='opacity:.3;pointer-events:none'"
    
    if v=='home':
        # 2- صفحه الرئيسه شيل لوحه تحكم والكروت وبنج رايحات يسار خليها بالنص
        h=f"""
        <div style='display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:60vh;text-align:center'>
          <div style='font-size:48px;margin-bottom:10px'>{logo_html()}</div>
          <p style='color:{COLORS['text_muted_dark']};font-size:14px'>OMAIA ISP</p>
          <div style='margin-top:30px;display:flex;gap:10px;flex-wrap:wrap;justify-content:center'>
            <button class=btn-gold onclick="loadPage('subs')" style='padding:15px 25px'>👥 المشتركين</button>
            <button class=btn-blue onclick="loadPage('dishes')" style='padding:15px 25px'>📡 الصحون</button>
            <button class=btn-blue onclick="loadPage('map')" style='padding:15px 25px'>🗺 الخريطة</button>
          </div>
        </div>
        """
        return h
    elif v=='subs':
        rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 200")
        rows=""
        for r in rs:
            name_js = js_esc(r['name'])
            phone_js = js_esc(r['phone'])
            # 8- الفني لا يحسن يمسح ولا يعدل
            edit_b = f"<button class=btn-blue onclick='editSub({r['id']}, {name_js}, {phone_js})' {edit_btn_attr}>تعديل</button>" if can else ""
            del_b = f"<a href=/del_sub/{r['id']} data-del class=btn-red>حذف</a>" if can else ""
            # 3- مشتركين خلي مربعين فوق بعض وبنص شاشه
            rows+=f"<div class='card sub-card' style='max-width:450px;margin:8px auto;width:100%'><div><b>{esc(r['name'])}</b><br><small>📞 {esc(r['phone'])}</small></div><div class=actions>{edit_b}{del_b}</div></div>"
        h=f"""
        <div style='max-width:500px;margin:0 auto'>
          <div class=card style='text-align:center'><h3>👥 المشتركين</h3><form data-ajax method=post action=/add_sub class=form-col><input name=name required placeholder='الاسم الكامل'><input name=phone placeholder='رقم الهاتف'><button class=btn-gold>اضافة</button></form></div>
          <div style='display:flex;flex-direction:column;align-items:center'>{rows if rows else '<div class=card>لا يوجد</div>'}</div>
        </div>
        <div id=editModal class=modal><div class=modal-content><h3>تعديل مشترك</h3><form id=editForm method=post><input type=hidden name=id id=edit_id><input name=name id=edit_name required placeholder='الاسم'><input name=phone id=edit_phone placeholder='الهاتف'><div style="display:flex;gap:8px;margin-top:10px"><button class=btn-gold>حفظ</button><button type=button class=btn onclick="closeModal()">الغاء</button></div></form></div></div>
        <script>
        function editSub(id,name,phone){{document.getElementById('edit_id').value=id;document.getElementById('edit_name').value=name;document.getElementById('edit_phone').value=phone;document.getElementById('editModal').style.display='flex';document.getElementById('editForm').action='/edit_sub/'+id}}
        function closeModal(){{document.getElementById('editModal').style.display='none'}}
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
            edit_b = f"<button class=btn-blue onclick='editDish({r['id']}, {dname_js}, \"{ip}\", {loc_js})' {edit_btn_attr}>تعديل</button>" if can else ""
            del_b = f"<a href=/del_dish/{r['id']} data-del class=btn-red>حذف</a>" if can else ""
            cards+=f"<div class='card dish-card' style='max-width:500px;margin:8px auto'><div class=dish-head><b>📡 {dname}</b></div><a href='http://{ip}' target='_blank' class=ip-badge>🌐 {ip}</a><br><small>📍 {loc}</small><div class=actions style='margin-top:8px'><button class=btn-blue onclick='pingDish(\"{ip}\")'>بينغ</button>{edit_b}{del_b}</div></div>"
        h=f"<div style='max-width:550px;margin:0 auto'><div class=card><h3>📡 الصحون</h3><form data-ajax method=post action=/add_dish class=form-col><input name=dish_name required placeholder='اسم الصحن'><input name=ip required placeholder='IP داخلي'><input name=location placeholder='الموقع'><button class=btn-gold>اضافة</button></form></div><div>{cards}</div></div>"
        h+="""
        <div id=editDishModal class=modal><div class=modal-content><h3>تعديل صحن</h3><form id=editDishForm method=post><input name=dish_name id=edit_dish_name required><input name=ip id=edit_dish_ip required><input name=location id=edit_dish_loc><div style="display:flex;gap:8px;margin-top:10px"><button class=btn-gold>حفظ</button><button type=button class=btn onclick="document.getElementById('editDishModal').style.display='none'">الغاء</button></div></form></div></div>
        <script>function editDish(id,name,ip,loc){document.getElementById('edit_dish_name').value=name;document.getElementById('edit_dish_ip').value=ip;document.getElementById('edit_dish_loc').value=loc;document.getElementById('editDishModal').style.display='flex';document.getElementById('editDishForm').action='/edit_dish/'+id}</script>
        """
        return h
    elif v=='towers':
        rs=qall("SELECT * FROM towers ORDER BY id DESC LIMIT 200")
        cards=""
        for r in rs:
            tname_js = js_esc(r['name'])
            tarea_js = js_esc(r.get('area') or '')
            tloc_js = js_esc(r.get('location') or '')
            area = esc(r.get('area') or '')
            # 4- الأبراج خلي مربعين فوق بعض على يمين وخلي بس منطقه بدون محافظة وشغل زر تعديل
            edit_b = f"<button class=btn-blue onclick='editTower({r['id']}, {tname_js}, {tarea_js})' {edit_btn_attr}>تعديل</button>" if can else ""
            del_b = f"<a href=/del_tower/{r['id']} data-del class=btn-red>حذف</a>" if can else ""
            cards+=f"<div class='card tower-card' style='max-width:400px'><div><b>🗼 {esc(r['name'])}</b><br><small>🗺 المنطقة: {area}</small></div><div class=actions>{edit_b}{del_b}</div></div>"
        h=f"""
        <div style='display:flex;justify-content:flex-end'><div style='width:100%;max-width:450px'>
          <div class=card><h3>🗼 الأبراج - منطقة فقط</h3><form data-ajax method=post action=/add_tower class=form-col><input name=name required placeholder='اسم البرج'><input name=area required placeholder='المنطقة فقط'><button class=btn-gold>اضافة</button></form></div>
          <div style='display:flex;flex-direction:column;align-items:flex-end;gap:8px'>{cards}</div>
        </div></div>
        <div id=editTowerModal class=modal><div class=modal-content><h3>تعديل برج</h3><form id=editTowerForm method=post><input name=name id=edit_tower_name required placeholder='اسم'><input name=area id=edit_tower_area required placeholder='منطقة'><div style="display:flex;gap:8px;margin-top:10px"><button class=btn-gold>حفظ</button><button type=button class=btn onclick="document.getElementById('editTowerModal').style.display='none'">الغاء</button></div></form></div></div>
        <script>
        function editTower(id,name,area){{document.getElementById('edit_tower_name').value=name;document.getElementById('edit_tower_area').value=area;document.getElementById('editTowerModal').style.display='flex';document.getElementById('editTowerForm').action='/edit_tower/'+id}}
        </script>
        """
        return h
    elif v=='ledger':
        rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 100")
        rows_html=""
        for r in rs:
            cur_icon = "$" if (r.get('currency') or 'USD')=='USD' else "ل.س"
            typ = esc(r.get('typ') or 'دين')
            name_js = js_esc(r.get('name') or '')
            note_js = js_esc(r.get('note') or '')
            amount = r['amount']
            # 5- دفتر حسابات خلي مربعات فوق بعض وبنص شاشه ظغر حجم شوي وجدل منضاف اسم مبلغ نوع عمله
            edit_b = f"<button class=btn-blue style='padding:4px 8px;font-size:11px' onclick='editLedger({r['id']}, {name_js}, \"{amount}\", \"{typ}\", \"{r.get('currency') or 'USD'}\")' {edit_btn_attr}>تعديل</button>" if can else ""
            del_b = f"<a href=/del_ledger/{r['id']} data-del class=btn-red style='padding:4px 8px;font-size:11px'>حذف</a>" if can else ""
            rows_html+=f"<div class='card' style='max-width:420px;margin:6px auto;padding:10px;font-size:13px;display:flex;justify-content:space-between;align-items:center'><div><b>{esc(r.get('name') or '')}</b> | {amount} {cur_icon} | {typ}</div><div class=actions>{edit_b}{del_b}</div></div>"
        h=f"""
        <div style='max-width:500px;margin:0 auto'>
          <div class=card style='text-align:center;padding:12px'><h3 style='margin:0 0 10px'>📒 دفتر الحسابات</h3>
            <form data-ajax method=post action=/add_ledger style='display:grid;grid-template-columns:1fr 1fr 1fr 1fr auto;gap:6px'>
              <input name=name required placeholder='الاسم' style='font-size:12px'>
              <input name=amount type=number step=0.01 required placeholder='مبلغ' style='font-size:12px'>
              <select name=typ style='font-size:12px'><option>دين</option><option>دفع</option></select>
              <select name=currency style='font-size:12px'><option value=USD>$</option><option value=SYP>ل.س</option></select>
              <button class=btn-gold style='font-size:12px'>اضافة</button>
            </form>
          </div>
          <div>{rows_html if rows_html else '<div class=card style=max-width:420px;margin:6px auto>لا يوجد</div>'}</div>
        </div>
        <div id=editLedgerModal class=modal><div class=modal-content><h3>تعديل</h3><form id=editLedgerForm method=post><input name=name id=edit_ledger_name required><input name=amount id=edit_ledger_amount type=number step=0.01 required><select name=typ id=edit_ledger_typ><option>دين</option><option>دفع</option></select><select name=currency id=edit_ledger_cur><option value=USD>$ دولار</option><option value=SYP>ل.س سوري</option></select><div style="display:flex;gap:8px;margin-top:10px"><button class=btn-gold>حفظ</button><button type=button class=btn onclick="document.getElementById('editLedgerModal').style.display='none'">الغاء</button></div></form></div></div>
        <script>function editLedger(id,name,amount,typ,cur){{document.getElementById('edit_ledger_name').value=name;document.getElementById('edit_ledger_amount').value=amount;document.getElementById('edit_ledger_typ').value=typ;document.getElementById('edit_ledger_cur').value=cur;document.getElementById('editLedgerModal').style.display='flex';document.getElementById('editLedgerForm').action='/edit_ledger/'+id}}</script>
        """
        return h
    elif v=='map':
        # 6- الخرطيه رايحا كتير يسار خليها للمين ضلي تاخد موقعي من تفتح حزف لنقاط ودقه ظبطا وشلي دبوث تحت حماه مركز
        h=f"""
        <div style='display:flex;justify-content:flex-end'><div style='width:100%;max-width:650px'>
          <div class=card>
            <h3>🗺 الخريطة</h3>
            <div id=map style='height:500px;border-radius:12px'></div>
            <div style='margin-top:8px;display:flex;gap:6px'>
              <button class=btn-blue onclick='getMyLocation()'>📍 موقعي</button>
              <button class=btn-gold onclick='calcDistMode()'>📏 قياس</button>
              <span id=distResult style='margin-right:10px;font-size:12px'>اضغط نقطتين للقياس</span>
            </div>
            <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
            <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
            <script>
              let map = L.map('map').setView([35.1318, 36.7578], 12);
              L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}', {{ attribution: 'OMAIA ISP Satellite', maxZoom: 19 }}).addTo(map);
              let userMarker = null;
              // اخد موقعي تلقائي من تفتح
              if(navigator.geolocation){{
                navigator.geolocation.getCurrentPosition(pos=>{{
                  let lat=pos.coords.latitude, lng=pos.coords.longitude;
                  map.setView([lat,lng], 14);
                  if(userMarker) map.removeLayer(userMarker);
                  userMarker = L.marker([lat,lng]).addTo(map).bindPopup('📍 أنت هنا').openPopup();
                }});
              }}
              window.getMyLocation = function(){{
                if(navigator.geolocation){{
                  navigator.geolocation.getCurrentPosition(pos=>{{
                    let lat=pos.coords.latitude, lng=pos.coords.longitude;
                    map.setView([lat,lng], 15);
                    if(userMarker) map.removeLayer(userMarker);
                    userMarker = L.marker([lat,lng]).addTo(map).bindPopup('📍 موقعك الحالي').openPopup();
                  }}, err=>{{alert('فشل تحديد الموقع')}});
                }} else {{alert('المتصفح لا يدعم تحديد الموقع')}}
              }}
              let distPoints=[], distLine=null; window.distMode=false;
              map.on('click', e=>{{
                if(window.distMode){{
                  distPoints.push(e.latlng);
                  L.marker(e.latlng).addTo(map);
                  if(distPoints.length==2){{
                    let d=map.distance(distPoints[0], distPoints[1]);
                    document.getElementById('distResult').innerHTML = `📍 ${{(d/1000).toFixed(2)}} كم`;
                    if(distLine) map.removeLayer(distLine);
                    distLine = L.polyline(distPoints, {{color: '{COLORS['gold']}', weight:3}}).addTo(map);
                    distPoints=[]; window.distMode=false;
                  }}
                }}
              }});
              window.calcDistMode = function(){{window.distMode=true; document.getElementById('distResult').textContent='اضغط نقطتين'; distPoints=[]; if(distLine) map.removeLayer(distLine);}}
            </script>
          </div>
        </div></div>
        """
        return h
    elif v=='logs':
        rs=qall("SELECT * FROM activity_log ORDER BY id DESC LIMIT 200")
        rows="".join([f"<div class=log-row><span class=log-time>{esc(r['time'])}</span><span class=log-phone>👤 {esc(r['phone'])}</span><span>{esc(r['action'])}</span></div>" for r in rs])
        h=f"<div class=card style='max-width:600px;margin:0 auto'><h3>📜 سجل النشاطات</h3><div class=logs-container>{rows}</div></div>"
        return h
    elif v=='notifications':
        rs=qall("SELECT * FROM notifications ORDER BY id DESC LIMIT 100")
        rows="".join([f"<div class='card notif-card' style='max-width:500px;margin:8px auto'><div><b>{esc(r['title'])}</b><br><small>{esc(r['time'])}</small><p>{esc(r['msg'])}</p></div></div>" for r in rs])
        h=f"<div style='max-width:600px;margin:0 auto'><div class=card style='text-align:center'><h3>🔔 الإشعارات - مفعلة</h3><button class=btn-blue onclick='fetch(\"/clear_notifs\").then(()=>loadPage(\"notifications\"))'>مسح الكل</button></div>{rows if rows else '<div class=card style=max-width:500px;margin:8px auto>لا يوجد اشعارات - سيتم اشعارك عند أي نشاط</div>'}</div>"
        return h
    elif v=='support':
        h=f"""
        <div class=card style='text-align:center;border:2px solid {COLORS['gold']};max-width:500px;margin:20px auto'>
          <h2 style='margin:0'>{logo_html()}</h2>
          <p>الدعم الفني</p>
          <div style='font-size:22px;margin:12px;font-weight:bold' dir=ltr>+90 534 485 10 45</div>
          <a href='https://wa.me/905344851045' target=_blank class=btn-wa style='margin:6px'>💬 واتساب</a>
          <a href='tel:+905344851045' class=btn-blue style='margin:6px;display:inline-block;text-decoration:none;padding:10px 18px;border-radius:20px'>📞 اتصال</a>
          <div style='margin-top:18px;border-top:1px solid {COLORS['border_dark']};padding-top:12px'>
            <a href='https://instagram.com/af_20_1999' target=_blank style='display:inline-flex;align-items:center;gap:8px;background:linear-gradient(45deg,#feda75,#fa7e1e,#d62976,#962fbf,#4f5bd5);color:#fff;padding:10px 18px;border-radius:20px;text-decoration:none;font-weight:bold'>📸 Instagram: af_20_1999</a>
          </div>
        </div>
        """
        return h
    elif v=='settings':
        us=qall("SELECT phone,username,role FROM users ORDER BY phone")
        uh=""
        for u in us: 
            ph=esc(u['phone']);un=esc(u.get('username') or u['phone']);role=esc(u.get('role') or '')
            ph_js = js_esc(u['phone'])
            un_js = js_esc(u.get('username') or u['phone'])
            # 8- الاعدادات تعديل يوزر وحزف يوزر - الفني بس يضيف لا يحسن يمسح ولا يعدل شي
            if tech:
                # فني لا يرى حذف وتعديل
                uh+=f"<div class='card user-card' style='max-width:500px;margin:6px auto'><div style='display:flex;align-items:center;gap:10px'><div class=avatar>{un[:1]}</div><div><b>{un}</b><br><small>📞 {ph} - {role}</small></div></div></div>"
            else:
                uh+=f"<div class='card user-card' style='max-width:500px;margin:6px auto'><div style='display:flex;align-items:center;gap:10px'><div class=avatar>{un[:1]}</div><div><b>{un}</b><br><small>📞 {ph} - {role}</small></div></div><div class=actions><button class=btn-blue onclick='editUser({ph_js}, {un_js})'>تعديل</button><a href=/del_user/{ph} data-del class=btn-red>حذف</a></div></div>"
        # 9- زر لغه مو شغال - خطلي زر لغه بالإعدادات كمان
        h=f"""
        <div style='max-width:600px;margin:0 auto'>
          <div class=card><h3>⚙ إعدادات - User / Phone</h3>
            <div style='display:grid;grid-template-columns:1fr 1fr;gap:8px'>
              <form data-ajax method=post action=/change_pass><input name=newpass type=password required placeholder='كلمة السر الجديدة'><button class=btn-gold style='width:100%'>تغيير كلمة السر</button></form>
              <div style='display:flex;flex-direction:column;gap:6px'>
                <button class=btn onclick='toggleTheme()' style='width:100%'>🌓 ليل/نهار</button>
                <button class=btn-blue onclick='toggleLang()' style='width:100%'>🌐 تغيير اللغة (عربي/EN)</button>
              </div>
            </div>
          </div>
          {"<div class=card><h3>➕ اضافة مستخدم</h3><form data-ajax method=post action=/add_user class=form-col><input name=phone required placeholder='يوزر / رقم'><input name=password type=password required placeholder='كلمة السر'><select name=role><option value=tech>فني - يضيف فقط</option><option value=manager>مدير - كل الصلاحيات</option></select><button class=btn-gold>اضافة</button></form></div>" if not tech else "<div class=card><p>🔒 الفني لا يمكنه اضافة مستخدمين - للمدراء فقط</p></div>" if False else f"<div class=card><h3>➕ اضافة مستخدم</h3><form data-ajax method=post action=/add_user class=form-col><input name=phone required placeholder='يوزر / رقم'><input name=password type=password required placeholder='كلمة السر'><select name=role><option value=tech>فني - يضيف فقط</option><option value=manager>مدير - كل الصلاحيات</option></select><button class=btn-gold>اضافة</button></form></div>"}
          <div><h3>المستخدمين</h3>{uh}</div>
        </div>
        <div id=editUserModal class=modal><div class=modal-content><h3>تعديل يوزر</h3><form id=editUserForm method=post><input name=newphone id=edit_user_phone placeholder='يوزر جديد'><div style="display:flex;gap:8px;margin-top:10px"><button class=btn-gold>حفظ</button><button type=button class=btn onclick="document.getElementById('editUserModal').style.display='none'">الغاء</button></div></form></div></div>
        <script>function editUser(phone, username){{document.getElementById('edit_user_phone').value=username;document.getElementById('editUserModal').style.display='flex';document.getElementById('editUserForm').action='/edit_user/'+phone}}</script>
        """
        return h
    return "ok"

def layout(c,v='home'):
    th=cur_theme()
    bg=COLORS['bg_dark'] if th=='dark' else COLORS['bg_light']
    card=COLORS['card_dark'] if th=='dark' else COLORS['card_light']
    txt=COLORS['white'] if th=='dark' else COLORS['black']
    # 11- سرعه نار - كاش وتحسين
    return f"""<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1,maximum-scale=1'>
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
:root{{--gold:{COLORS['gold']};--bg:{bg};--card:{card};--text:{txt};--border:{COLORS['border_dark']};--input:{COLORS['input_dark']};--blue:{COLORS['btn_blue']};--red:{COLORS['btn_red']};--wa:{COLORS['btn_wa']}}}
*{{box-sizing:border-box;font-family:'Cairo',system-ui,sans-serif}}body{{margin:0;background:var(--bg);color:var(--text);overflow-x:hidden;overscroll-behavior-y:contain}}
#loader-line{{position:fixed;top:0;left:0;height:3px;background:var(--gold);width:0;z-index:9999;transition:width .15s ease-out}}
.sidebar{{position:fixed;right:-280px;top:0;width:250px;height:100%;background:{COLORS['menu_bg']};transition:right .2s ease;z-index:1000;padding-top:60px;box-shadow:-5px 0 20px rgba(0,0,0,0.5);overflow-y:auto}}
.sidebar.active{{right:0}}
.sidebar a{{display:flex;align-items:center;gap:10px;padding:11px 14px;color:{COLORS['white']};text-decoration:none;transition:all .1s;border-right:3px solid transparent;margin:2px 6px;border-radius:8px;font-size:13px}}
.sidebar a:hover{{background:{COLORS['input_dark']};border-right-color:var(--gold)}}.sidebar a.active{{background:var(--gold);color:{COLORS['black']};font-weight:bold}}
.overlay{{position:fixed;inset:0;background:{COLORS['black']}80;display:none;z-index:999}}.overlay.active{{display:block}}
.top{{position:fixed;top:0;left:0;right:0;background:{COLORS['top_bg']};padding:10px 14px;z-index:101;display:flex;align-items:center;justify-content:space-between;box-shadow:0 2px 10px {COLORS['black']}33;border-bottom:1px solid var(--border);height:56px}}
.menu-btn{{font-size:20px;cursor:pointer;background:var(--input);width:38px;height:38px;display:flex;align-items:center;justify-content:center;border-radius:8px}}
.main{{margin-right:250px;margin-top:56px;padding:12px;min-height:100vh;transition:margin .2s}}
.card{{background:{card};padding:14px;border-radius:12px;margin-bottom:10px;border:1px solid {COLORS['border_dark']};box-shadow:0 2px 8px {COLORS['black']}22;will-change:transform}}
.btn{{background:var(--input);border:none;color:var(--text);padding:7px 12px;border-radius:7px;cursor:pointer;font-weight:bold;font-size:13px}}
.btn-gold{{background:var(--gold);color:{COLORS['black']};padding:8px 14px;border-radius:7px;border:none;font-weight:bold;cursor:pointer;font-size:13px}}
.btn-blue{{background:var(--blue);color:{COLORS['white']};padding:7px 12px;border-radius:7px;border:none;cursor:pointer;font-size:13px}}
.btn-red{{background:var(--red);color:{COLORS['white']};padding:7px 12px;border-radius:7px;border:none;cursor:pointer;text-decoration:none;font-size:13px}}
.btn-wa{{background:var(--wa);color:{COLORS['white']};padding:8px 16px;border-radius:18px;text-decoration:none;display:inline-block;font-weight:bold;font-size:13px}}
input,select{{width:100%;padding:10px;background:var(--input);border:1px solid var(--border);border-radius:8px;color:var(--text);margin:3px 0;font-size:13px}}
.form-col{{display:flex;flex-direction:column;gap:6px}}
@media(max-width:900px){{.main{{margin-right:0}}}}
.ip-badge{{background:{COLORS['black']};color:var(--gold);padding:4px 10px;border-radius:16px;font-size:12px;font-family:monospace;border:1px solid var(--gold);display:inline-block}}
.sub-card,.tower-card{{display:flex;justify-content:space-between;align-items:center}}
.actions{{display:flex;gap:5px;flex-wrap:wrap}} .ping-box{{display:flex;gap:6px;margin:8px 0}}
pre{{background:{COLORS['black']};color:{COLORS['ping_text']};padding:10px;border-radius:8px;min-height:40px;overflow:auto;font-size:11px}}
.log-row{{display:flex;gap:6px;padding:6px;border-bottom:1px solid var(--border);font-size:11px}} .log-time{{color:{COLORS['text_muted_dark']};min-width:70px}} .log-phone{{color:var(--gold);font-weight:bold;min-width:90px}}
.dist-result{{background:var(--input);padding:8px;border-radius:8px;margin-top:8px;text-align:center;border:1px dashed var(--gold);font-size:12px}}
.modal{{display:none;position:fixed;inset:0;background:{COLORS['black']}99;z-index:2000;align-items:center;justify-content:center}} .modal-content{{background:var(--card);padding:16px;border-radius:12px;width:92%;max-width:360px}}
.user-card{{display:flex;align-items:center;gap:8px;justify-content:space-between}} .avatar{{width:34px;height:34px;border-radius:50%;background:var(--gold);display:flex;align-items:center;justify-content:center;font-weight:bold;color:{COLORS['black']};font-size:14px}}
.top-actions{{display:flex;gap:6px;align-items:center}} .top-actions button{{width:34px;height:34px;border-radius:8px;border:none;background:var(--input);color:var(--text);cursor:pointer;font-size:14px}}
#pullHint{{position:fixed;top:56px;left:50%;transform:translateX(-50%) translateY(-60px);background:var(--gold);color:{COLORS['black']};padding:6px 14px;border-radius:20px;font-size:12px;font-weight:bold;transition:transform .2s;z-index:50}}
#pullHint.show{{transform:translateX(-50%) translateY(10px)}}
</style></head><body>
<div id=loader-line></div>
<div id=pullHint>↓ اسحب للتحديث</div>
<div class=overlay id=overlay onclick='toggleMenu()'></div>
<div class=sidebar id=sidebar>
<a href="javascript:loadPage('home')" id=nav-home>🏠 الرئيسية</a>
<a href="javascript:loadPage('subs')" id=nav-subs>👥 المشتركين</a>
<a href="javascript:loadPage('dishes')" id=nav-dishes>📡 الصحون</a>
<a href="javascript:loadPage('towers')" id=nav-towers>🗼 الأبراج</a>
<a href="javascript:loadPage('ledger')" id=nav-ledger>📒 الحسابات</a>
<a href="javascript:loadPage('map')" id=nav-map>🗺 الخريطة</a>
<a href="javascript:loadPage('logs')" id=nav-logs>📜 السجل</a>
<a href="javascript:loadPage('notifications')" id=nav-notifications>🔔 الإشعارات</a>
<a href="javascript:loadPage('support')" id=nav-support>🎧 الدعم</a>
<a href="javascript:loadPage('settings')" id=nav-settings>⚙ الإعدادات</a>
<a href=/logout style='color:var(--red);margin-top:14px;border-top:1px solid var(--border)'>🚪 خروج</a>
</div>
<div class=top>
<div class=menu-btn onclick='toggleMenu()'>☰</div>
<div>{logo_html()}</div>
<div class=top-actions>
<button onclick='toggleTheme()' title='ليل/نهار'>🌓</button>
<button onclick='toggleLang()' title='لغة'>🌐</button>
<button onclick='loadPage(currentPage)' title='تحديث'>🔄</button>
</div>
</div>
<div class=main id=main>{c}</div>
<script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>
<script>
// 11- سرعه نار - كاش وتحسين
const pageCache = {{}}; // كاش الصفحات
let currentPage='{v}';
function toggleMenu(){{let s=document.getElementById('sidebar'), o=document.getElementById('overlay');s.classList.toggle('active');o.classList.toggle('active');}}
function showLine(p){{document.getElementById('loader-line').style.width=p+'%';}}
function hideLine(){{setTimeout(()=>{{document.getElementById('loader-line').style.width='0'}},200);}}
window.loadPage=async function(v, force=false){{
  if(document.getElementById('sidebar').classList.contains('active'))toggleMenu();
  currentPage=v;
  document.querySelectorAll('.sidebar a').forEach(a=>a.classList.remove('active'));
  let nav=document.getElementById('nav-'+v);if(nav)nav.classList.add('active');
  // 11- كاش - اذا موجودة بالكاش اعرضها فورا نار
  if(pageCache[v] && !force){{
    document.getElementById('main').innerHTML=pageCache[v];
    bindAjax();
    document.getElementById('main').querySelectorAll('script').forEach(s=>{{try{{eval(s.textContent)}}catch(e){{}}}});
    // تحديث بالخلفية
    fetch('/api/page?v='+v).then(r=>r.text()).then(html=>{{pageCache[v]=html}});
    return;
  }}
  showLine(30);
  try{{
    let r=await fetch('/api/page?v='+v, {{cache:'no-store'}});
    if(r.status==401){{location.href='/login';return}}
    let html=await r.text();
    pageCache[v]=html;
    document.getElementById('main').innerHTML=html;
    bindAjax();
    document.getElementById('main').querySelectorAll('script').forEach(s=>{{try{{eval(s.textContent)}}catch(e){{}}}});
  }}catch(e){{document.getElementById('main').innerHTML='<div class=card style=color:red>خطأ: '+e+'</div>'}}
  showLine(100); hideLine();
  window.scrollTo({{top:0,behavior:'smooth'}});
}}
function bindAjax(){{
  document.querySelectorAll('form[data-ajax]').forEach(f=>{{
    f.onsubmit=async e=>{{e.preventDefault();showLine(50);try{{let res=await fetch(f.action,{{method:'POST',body:new FormData(f),cache:'no-store'}});if(res.status==401){{location.href='/login';return}}if(!res.ok){{let t=await res.text();alert('خطأ: '+t);showLine(0);return}} 
      // مسح الكاش بعد التعديل
      Object.keys(pageCache).forEach(k=>delete pageCache[k]);
      loadPage(currentPage, true);
    }}catch(e){{alert('خطأ: '+e);showLine(0)}}}};
  }});
  document.querySelectorAll('a[data-del]').forEach(a=>{{
    a.onclick=async e=>{{e.preventDefault();if(!confirm('⚠ تأكيد الحذف؟'))return;showLine(50);let res=await fetch(a.href,{{cache:'no-store'}});if(res.status==401){{location.href='/login';return}} Object.keys(pageCache).forEach(k=>delete pageCache[k]); loadPage(currentPage, true);}};
  }});
}}
function pingDish(ip){{if(!ip){{alert('لا يوجد IP');return}}showLine(50);fetch('/api/ping?ip='+encodeURIComponent(ip)).then(r=>r.json()).then(j=>{{showLine(0);alert(j.out.slice(0,400))}}).catch(()=>showLine(0))}}
async function toggleTheme(){{showLine(30);await fetch('/toggle_theme',{{cache:'no-store'}});location.reload()}}
// 9- زر لغه مو شغال - صلحناه
async function toggleLang(){{showLine(30);try{{let r=await fetch('/toggle_lang',{{cache:'no-store'}});let t=await r.text(); console.log('lang toggled',t); location.reload();}}catch(e){{alert('خطأ لغة: '+e);showLine(0)}}}}
document.addEventListener('keydown', e=>{{if(e.key==='Escape' && document.getElementById('sidebar').classList.contains('active'))toggleMenu()}});
// 10- اسحب باصبعي على شاشه تحدث
let startY=0, pulling=false;
document.addEventListener('touchstart', e=>{{if(window.scrollY===0){{startY=e.touches[0].clientY; pulling=true;}}}}, {{passive:true}});
document.addEventListener('touchmove', e=>{{
  if(!pulling) return;
  let diff = e.touches[0].clientY - startY;
  if(diff>0 && diff<120 && window.scrollY===0){{
    let hint=document.getElementById('pullHint');
    hint.classList.add('show');
    hint.textContent = diff>80 ? '↻ اترك للتحديث' : '↓ اسحب للتحديث';
  }}
}}, {{passive:true}});
document.addEventListener('touchend', e=>{{
  let hint = document.getElementById('pullHint');
  if(hint.classList.contains('show') && hint.textContent.includes('اترك')){{
    Object.keys(pageCache).forEach(k=>delete pageCache[k]);
    loadPage(currentPage, true);
  }}
  hint.classList.remove('show');
  pulling=false;
}});
bindAjax();
// مسح الكاش القديم عند التحميل
if('caches' in window){{caches.keys().then(names=>names.forEach(n=>caches.delete(n)))}}
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
            add_log(f"تسجيل دخول: {uin}")
            return redirect('/dash')
        return f"<script>alert('بيانات خاطئة');location.href='/login'</script>",401
    # 1- صفحه تسجيل دخول حاطط omaia خليها omaia isp ولا نظام ادرة شبكه حطلي تحت صفحه الدعم النفي ويقونه وتساب
    return f"""<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>OMAIA ISP - Login</title>
<style>
body{{display:flex;flex-direction:column;align-items:center;justify-content:center;background:{COLORS['bg_dark']};min-height:100vh;margin:0;font-family:'Cairo',sans-serif;padding:20px}}
.box{{background:{COLORS['white']};padding:28px;border-radius:16px;width:92%;max-width:360px;box-shadow:0 20px 40px {COLORS['black']}66}}
input{{width:100%;padding:12px;margin:8px 0;border-radius:10px;border:1px solid #ccc;font-size:14px}}
.login-btn{{width:100%;background:{COLORS['gold']};color:{COLORS['black']};padding:13px;border:0;border-radius:10px;font-weight:900;font-size:16px;cursor:pointer;margin-top:12px}}
.save-row{{display:flex;align-items:center;gap:6px;margin:8px 0;font-size:13px;color:{COLORS['input_dark']}}}
.save-row input{{width:auto;margin:0}}
.support-box{{margin-top:18px;background:{COLORS['card_dark']};padding:14px;border-radius:12px;width:92%;max-width:360px;text-align:center;border:1px solid {COLORS['gold']}}}
.support-box a{{display:inline-flex;align-items:center;gap:6px;margin:5px;padding:8px 14px;border-radius:20px;text-decoration:none;font-weight:bold;font-size:13px}}
</style>
</head><body>
<div class=box>
<h2 style='text-align:center;margin:0 0 14px'>{logo_html()}</h2>
<form method=post>
<input name=userin placeholder='User / Phone' required autocomplete='username'>
<input name=password type=password placeholder='كلمة السر' required autocomplete='current-password'>
<label class=save-row><input type=checkbox id=savePass> حفظ كلمة السر</label>
<button class=login-btn>دخول</button>
</form>
</div>
<div class=support-box>
<div style='color:{COLORS['white']};font-weight:bold;margin-bottom:8px'>🎧 الدعم الفني</div>
<div style='color:{COLORS['text_muted_dark']};font-size:13px'>OMAIA ISP</div>
<div style='margin-top:10px'>
<a href='https://wa.me/905344851045' target=_blank style='background:{COLORS['btn_wa']};color:{COLORS['white']}'>💬 واتساب</a>
<a href='https://instagram.com/af_20_1999' target=_blank style='background:linear-gradient(45deg,#feda75,#fa7e1e,#d62976);color:{COLORS['white']}'>📸 Instagram</a>
</div>
</div>
<script>
let u=document.querySelector('input[name=userin]'), p=document.querySelector('input[name=password]'), s=document.getElementById('savePass');
let saved=localStorage.getItem('omaia_user'), savedP=localStorage.getItem('omaia_pass');
if(saved){{u.value=saved; if(savedP){{p.value=savedP; s.checked=true;}} }}
document.querySelector('form').addEventListener('submit',()=>{{if(s.checked){{localStorage.setItem('omaia_user',u.value);localStorage.setItem('omaia_pass',p.value);}}else{{localStorage.removeItem('omaia_user');localStorage.removeItem('omaia_pass');}}}});
</script>
</body></html>"""

@app.route('/logout')
def lo():
    add_log("خروج");session.clear();return redirect('/login')

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

@app.route('/toggle_lang',methods=['POST','GET'])
def toggle_lang():
    cur = session.get('lang','ar')
    session['lang'] = 'en' if cur=='ar' else 'ar'
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
    if is_tech(): return "ممنوع للفني",403
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
    qexec("INSERT INTO ledger(name,amount,currency,note,typ,dt) VALUES(?,?,?,?,?,?)",(f.get('name',''),fnum(f.get('amount')),f.get('currency','USD'),f.get('note',''),f.get('typ','دين'),datetime.datetime.now().isoformat()))
    add_log(f"اضافة حساب: {f.get('name','')}")
    return "ok"

@app.route('/edit_ledger/<int:i>',methods=['POST'])
@login_required
def edit_ledger(i):
    if is_tech(): return "ممنوع للفني",403
    f=request.form
    qexec("UPDATE ledger SET name=?, amount=?, currency=?, typ=? WHERE id=?",(f.get('name',''),fnum(f.get('amount')),f.get('currency','USD'),f.get('typ','دين'),i))
    add_log(f"تعديل حساب {i}")
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
    if is_tech(): return "ممنوع للفني",403
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
    f=request.form
    qexec("INSERT INTO towers(name,location,area,lat,lng,fixed) VALUES(?,?,?,?,?,?)",(f.get('name',''),f.get('location',''),f.get('area',''),35.1318,36.7578,0))
    add_log(f"اضافة برج: {f.get('name','')}")
    return "ok"

@app.route('/edit_tower/<int:i>',methods=['POST'])
@login_required
def edit_tower(i):
    if is_tech(): return "ممنوع للفني",403
    f=request.form
    qexec("UPDATE towers SET name=?, location=?, area=? WHERE id=?",(f.get('name',''),f.get('location',''),f.get('area',''),i))
    add_log(f"تعديل برج {i}")
    return "ok"

@app.route('/del_tower/<int:i>')
@manager_required
def d2(i):
    t=qone("SELECT * FROM towers WHERE id=?",(i,))
    if not t: return "غير موجود",404
    qexec("DELETE FROM towers WHERE id=?",(i,))
    add_log(f"حذف برج {t['name']}")
    return "ok"

@app.route('/edit_user/<ph>',methods=['POST'])
@manager_required
def edit_user(ph):
    n=request.form.get('newphone','').strip()
    if not n: return "فارغ",400
    if qone("SELECT * FROM users WHERE phone=?",(n,)) and n!=ph: return "موجود",400
    qexec("UPDATE users SET phone=?, username=? WHERE phone=?",(n,n,ph))
    if session.get('phone')==ph:
        session['phone']=n
    add_log(f"تعديل يوزر {ph} الى {n}")
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
    add_log(f"اضافة مستخدم: {ph}")
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
