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
        qexec("INSERT INTO towers(name,lat,lng,location,area,fixed) VALUES(?,?,?,?,?,1)",('برج الحصن الرئيسي','حمص - الحصن','حماة - مركز','حماة',34.723,36.715))
        # تصحيح - حماة مركزها
        qexec("DELETE FROM towers")
        qexec("INSERT INTO towers(name,lat,lng,location,area,fixed) VALUES(?,?,?,?,?,1)",('نقطة حماة الرئيسية',35.1318,36.7578,'حماة - المركز','حماة',1))
        qexec("INSERT INTO towers(name,lat,lng,location,area,fixed) VALUES(?,?,?,?,?,1)",('برج الحصن',34.758,36.268,'تلكلخ','حمص',1))
    if not qone("SELECT * FROM notifications LIMIT 1"):
        qexec("INSERT INTO notifications(time,title,msg) VALUES(?,?,?)",(datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),"مرحباً بك","نظام OMAIA ISP جاهز"))
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

def cur_theme(): return session.get('theme','dark')
def cur_lang(): return session.get('lang','ar')

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

@app.route('/api/ping')
@login_required
def api_ping():
    ip=request.args.get('ip','').strip()
    if not ip: return jsonify(ok=False,out='لا يوجد IP')
    if not is_internal_ip(ip): return jsonify(ok=False,out='⛔ خارج الشبكة - يجب 192.168.x.x')
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.5)
        for port in [80, 8291, 8728, 22]:
            try:
                result = sock.connect_ex((ip, port))
                sock.close()
                if result == 0:
                    return jsonify(ok=True,out=f'✅ {ip}:{port} متصل (TCP)')
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
        if not out.strip():
            out = f"⚠️ ICMP ممنوع على الاستضافة لكن جرب فتح http://{ip} بالمتصفح"
        return jsonify(ok=True,out=out[:1500])
    except Exception as e: 
        return jsonify(ok=False,out=f'غير متاح: {str(e)[:200]}')

def page_content(v):
    h=""; can = can_edit(); dis_attr = "" if can else "disabled style='opacity:.4;pointer-events:none'"
    lang = cur_lang()
    if v=='home':
        ns=(qone("SELECT COUNT(*) c FROM subs") or {}).get('c',0)
        nd=(qone("SELECT COUNT(*) c FROM dish_ips") or {}).get('c',0)
        nt=(qone("SELECT COUNT(*) c FROM towers") or {}).get('c',0)
        # 2- صفحة رئيسية بالنص وشيل اخر نشاطات
        h=f"""
        <div style='text-align:center;margin:20px 0'>
          <h1 style='font-size:32px;margin:0'>{logo_html()}</h1>
          <p style='color:#94a3b8'>لوحة التحكم</p>
        </div>
        <div class=stats-grid style='max-width:600px;margin:0 auto'>
          <div class="card stat-card" style='justify-content:center;text-align:center;flex-direction:column'><div class=stat-icon>📡</div><h3>الصحون</h3><h2>{nd}</h2></div>
          <div class="card stat-card" style='justify-content:center;text-align:center;flex-direction:column'><div class=stat-icon>🗼</div><h3>الأبراج</h3><h2>{nt}</h2></div>
          <div class="card stat-card" style='justify-content:center;text-align:center;flex-direction:column'><div class=stat-icon>👥</div><h3>المشتركين</h3><h2>{ns}</h2></div>
        </div>
        <div class="card" style='max-width:600px;margin:15px auto'><h3>⚡ فحص الشبكة السريع</h3><div class=ping-box><input id=ping_ip placeholder="192.168.1.1"><button class=btn-blue onclick="doPing()">بينغ</button></div><pre id=ping_out>جاهز...</pre></div>
        <script>async function doPing(){{let i=document.getElementById("ping_ip").value;let o=document.getElementById("ping_out");if(!i){{o.textContent="ادخل IP";return}} o.textContent="⏳...";let r=await fetch("/api/ping?ip="+encodeURIComponent(i));let j=await r.json();o.textContent=j.out}}</script>
        """
        return h
    elif v=='subs':
        rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 200")
        rows=""
        for r in rs:
            name_js = js_esc(r['name'])
            phone_js = js_esc(r['phone'])
            rows+=f"<div class='card sub-card'><div><b>{esc(r['name'])}</b><br><small>📞 {esc(r['phone'])}</small></div><div class=actions><button class=btn-blue onclick='editSub({r['id']}, {name_js}, {phone_js})'>تعديل</button><a href=/del_sub/{r['id']} data-del class=btn-red {dis_attr}>حذف</a></div></div>"
        h=f"<div class=card><h3>👥 المشتركين</h3><form data-ajax method=post action=/add_sub class=form-row><input name=name required placeholder='الاسم الكامل'><input name=phone placeholder='رقم الهاتف'><button class=btn-gold>اضافة</button></form></div><div class=subs-list>{rows}</div>"
        h+="""
        <div id=editModal class=modal><div class=modal-content><h3>تعديل مشترك</h3><form id=editForm method=post><input type=hidden name=id id=edit_id><input name=name id=edit_name required placeholder='الاسم'><input name=phone id=edit_phone placeholder='الهاتف'><div style="display:flex;gap:8px;margin-top:10px"><button class=btn-gold>حفظ</button><button type=button class=btn onclick="closeModal()">الغاء</button></div></form></div></div>
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
            # 3- موقع تحت IP والضغط على IP يحول لكروم
            cards+=f"<div class='card dish-card'><div class=dish-head><b>📡 {dname}</b></div><a href='http://{ip}' target='_blank' class=ip-badge style='text-decoration:none;display:inline-block;margin:5px 0'>🌐 {ip} - فتح بكروم</a><br><small>📍 {loc}</small><div class=actions style='margin-top:8px'><button class=btn-blue onclick='pingDish(\"{ip}\")'>بينغ</button><button class=btn-blue onclick='editDish({r['id']}, {dname_js}, \"{ip}\", {loc_js})'>تعديل</button><a href=/del_dish/{r['id']} data-del class=btn-red {dis_attr}>حذف</a></div></div>"
        h=f"<div class=card><h3>📡 الصحون</h3><form data-ajax method=post action=/add_dish class=form-row><input name=dish_name required placeholder='اسم الصحن'><input name=ip required placeholder='IP داخلي'><input name=location placeholder='الموقع'><button class=btn-gold>اضافة</button></form></div><div class=dishes-grid>{cards}</div>"
        h+="""
        <div id=editDishModal class=modal><div class=modal-content><h3>تعديل صحن</h3><form id=editDishForm method=post><input name=dish_name id=edit_dish_name required placeholder='اسم الصحن'><input name=ip id=edit_dish_ip required placeholder='IP'><input name=location id=edit_dish_loc placeholder='الموقع'><div style="display:flex;gap:8px;margin-top:10px"><button class=btn-gold>حفظ</button><button type=button class=btn onclick="document.getElementById('editDishModal').style.display='none'">الغاء</button></div></form></div></div>
        <script>function editDish(id,name,ip,loc){document.getElementById('edit_dish_name').value=name;document.getElementById('edit_dish_ip').value=ip;document.getElementById('edit_dish_loc').value=loc;document.getElementById('editDishModal').style.display='flex';document.getElementById('editDishForm').action='/edit_dish/'+id}</script>
        """
        return h
    elif v=='towers':
        rs=qall("SELECT * FROM towers ORDER BY fixed DESC, id DESC LIMIT 200")
        cards=""
        for r in rs:
            is_fixed = r.get('fixed')
            badge = "<span class=fixed-badge>🔒 ثابت</span>" if is_fixed else ""
            delbtn = "" if is_fixed else f"<a href=/del_tower/{r['id']} data-del class=btn-red {dis_attr}>حذف</a>"
            tname_js = js_esc(r['name'])
            tloc_js = js_esc(r.get('location') or '')
            tarea_js = js_esc(r.get('area') or '')
            area = esc(r.get('area') or r.get('location') or '')
            # 5- برج اسم موقع منطقة
            cards+=f"<div class='card tower-card'><div><b>🗼 {esc(r['name'])} {badge}</b><br><small>📍 الموقع: {esc(r.get('location') or '')}</small><br><small>🗺 المنطقة: {area}</small></div><div class=actions>{delbtn}<button class=btn-blue onclick='editTower({r['id']}, {tname_js}, {tloc_js}, {tarea_js})'>تعديل</button></div></div>"
        h=f"<div class=card><h3>🗼 الأبراج - اسم + موقع + منطقة</h3><form data-ajax method=post action=/add_tower class=form-row><input name=name required placeholder='اسم البرج'><input name=location placeholder='الموقع'><input name=area placeholder='المنطقة - حماة/حمص'><button class=btn-gold>اضافة</button></form></div><div class=towers-list>{cards}</div>"
        h+="""
        <div id=editTowerModal class=modal><div class=modal-content><h3>تعديل برج</h3><form id=editTowerForm method=post><input name=name id=edit_tower_name required placeholder='اسم'><input name=location id=edit_tower_loc placeholder='موقع'><input name=area id=edit_tower_area placeholder='منطقة'><div style="display:flex;gap:8px;margin-top:10px"><button class=btn-gold>حفظ</button><button type=button class=btn onclick="document.getElementById('editTowerModal').style.display='none'">الغاء</button></div></form></div></div>
        <script>function editTower(id,name,loc,area){document.getElementById('edit_tower_name').value=name;document.getElementById('edit_tower_loc').value=loc;document.getElementById('edit_tower_area').value=area;document.getElementById('editTowerModal').style.display='flex';document.getElementById('editTowerForm').action='/edit_tower/'+id}</script>
        """
        return h
    elif v=='ledger':
        rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 100")
        rows_html=""
        for r in rs:
            cur_icon = "💵 $" if (r.get('currency') or 'USD')=='USD' else "💷 ل.س"
            name_js = js_esc(r.get('name') or '')
            note_js = js_esc(r.get('note') or '')
            rows_html+=f"<div class='card' style='display:flex;justify-content:space-between;align-items:center'><div><b>{esc(r.get('name') or 'بدون اسم')}</b> - {r['amount']} {cur_icon} <small>({esc(r.get('typ') or '')})</small><br><small>📝 {esc(r.get('note') or '')}</small></div><div class=actions><button class=btn-blue onclick='editLedger({r['id']}, {name_js}, \"{r['amount']}\", {note_js}, \"{r.get('currency') or 'USD'}\")'>تعديل</button><a href=/del_ledger/{r['id']} data-del class=btn-red>حذف</a></div></div>"
        # 6- دفتر حسابات اسم مبلغ ملاحظة عملة ايقونة دولار وسوري تعديل وحذف
        h=f"""
        <div class=card><h3>📒 دفتر الحسابات</h3>
        <form data-ajax method=post action=/add_ledger class=form-row style='grid-template-columns:1fr 1fr 1fr 1fr auto'>
          <input name=name required placeholder='الاسم'>
          <input name=amount type=number step=0.01 required placeholder='مبلغ'>
          <select name=currency><option value=USD>💵 دولار</option><option value=SYP>💷 سوري</option></select>
          <input name=note placeholder='ملاحظة'>
          <button class=btn-gold>اضافة</button>
        </form></div>
        <div>{rows_html if rows_html else '<div class=card>لا يوجد</div>'}</div>
        <div id=editLedgerModal class=modal><div class=modal-content><h3>تعديل حساب</h3><form id=editLedgerForm method=post><input name=name id=edit_ledger_name required placeholder='الاسم'><input name=amount id=edit_ledger_amount type=number step=0.01 required><select name=currency id=edit_ledger_cur><option value=USD>💵 دولار</option><option value=SYP>💷 سوري</option></select><input name=note id=edit_ledger_note placeholder='ملاحظة'><div style="display:flex;gap:8px;margin-top:10px"><button class=btn-gold>حفظ</button><button type=button class=btn onclick="document.getElementById('editLedgerModal').style.display='none'">الغاء</button></div></form></div></div>
        <script>function editLedger(id,name,amount,note,cur){{document.getElementById('edit_ledger_name').value=name;document.getElementById('edit_ledger_amount').value=amount;document.getElementById('edit_ledger_note').value=note;document.getElementById('edit_ledger_cur').value=cur;document.getElementById('editLedgerModal').style.display='flex';document.getElementById('editLedgerForm').action='/edit_ledger/'+id}}</script>
        """
        return h
    elif v=='map':
        towers = qall("SELECT * FROM towers")
        towers_js = json.dumps([{"id": t['id'], "name": t['name'], "lat": float(t.get('lat') or 35.13), "lng": float(t.get('lng') or 36.75), "loc": str(t.get('location') or ''), "area": str(t.get('area') or ''), "fixed": bool(t.get('fixed'))} for t in towers], ensure_ascii=False)
        # 7- الخريطة فقط + قمر صناعي دقة عالية + حماة مركز + بحث + نقاط مع اسم تعديل وحذف + شيل خطوط طول وعرض
        h=f"""
        <div class=card>
          <h3>🗺 الخريطة</h3>
          <div style='display:flex;gap:8px;margin-bottom:10px'>
            <input id=mapSearch placeholder='ابحث عن موقع... حماة، حمص' style='flex:1'>
            <button class=btn-blue onclick='searchMap()'>بحث</button>
            <button class=btn-gold onclick='calcDistMode()'>📏 قياس مسافة</button>
          </div>
          <div id=map style='height:480px;border-radius:12px'></div>
          <div id=distResult class=dist-result style='margin-top:10px'>اضغط على نقطتين بالخريطة لقياس المسافة</div>
          <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
          <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
          <script>
            let map = L.map('map').setView([35.1318, 36.7578], 10);
            // قمر صناعي دقة عالية
            let sat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}', {{ attribution: 'Esri Satellite - OMAIA', maxZoom: 19 }}).addTo(map);
            let streets = L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{ attribution: 'OMAIA ISP' }});
            L.control.layers({{"قمر صناعي": sat, "خريطة عادية": streets}}).addTo(map);
            let towers = {towers_js};
            let distPoints = [];
            let distLine = null;
            towers.forEach(t=>{{
              let m = L.marker([t.lat, t.lng]).addTo(map);
              m.bindPopup(`<b>${{t.name}}</b><br>📍 ${{t.loc}}<br>🗺 ${{t.area}}<br><div style='margin-top:6px;display:flex;gap:4px'><button onclick='editTowerMap(${{t.id}}, "${{t.name}}", "${{t.loc}}", "${{t.area}}")' style='background:#3b82f6;color:#fff;border:0;padding:4px 8px;border-radius:6px'>تعديل</button><a href='/del_tower/${{t.id}}' onclick='return confirm("حذف؟")' style='background:#ef4444;color:#fff;padding:4px 8px;border-radius:6px;text-decoration:none'>حذف</a></div>`);
            }});
            map.on('click', function(e){{
              if(window.distMode){{
                distPoints.push(e.latlng);
                L.marker(e.latlng).addTo(map);
                if(distPoints.length==2){{
                  let d = map.distance(distPoints[0], distPoints[1]);
                  document.getElementById('distResult').innerHTML = `📍 المسافة: <b style='color:{COLORS['gold']}'>${{(d/1000).toFixed(3)}} كم (${{d.toFixed(0)}} متر)</b> <button onclick='clearDist()' style='margin-right:10px'>مسح</button>`;
                  if(distLine) map.removeLayer(distLine);
                  distLine = L.polyline(distPoints, {{color: '{COLORS['gold']}', weight: 3}}).addTo(map);
                  distPoints = [];
                  window.distMode = false;
                }}
              }}
            }});
            window.calcDistMode = function(){{window.distMode=true; document.getElementById('distResult').innerHTML='📍 اضغط نقطتين على الخريطة'; distPoints=[]; if(distLine) map.removeLayer(distLine);}}
            window.clearDist = function(){{document.getElementById('distResult').innerHTML='اضغط على نقطتين بالخريطة لقياس المسافة'; distPoints=[]; window.distMode=false; if(distLine) map.removeLayer(distLine);}}
            window.searchMap = async function(){{
              let q = document.getElementById('mapSearch').value;
              if(!q) return;
              try{{let r=await fetch(`https://nominatim.openstreetmap.org/search?format=json&q=${{encodeURIComponent(q)}}`); let j=await r.json(); if(j[0]){{map.setView([j[0].lat, j[0].lon], 13); L.marker([j[0].lat, j[0].lon]).addTo(map).bindPopup(j[0].display_name).openPopup();}} }}catch(e){{alert('خطأ بحث')}}
            }}
            window.editTowerMap = function(id,name,loc,area){{ let nn=prompt('اسم البرج', name); if(!nn) return; let ll=prompt('الموقع', loc); let aa=prompt('المنطقة', area); fetch('/edit_tower/'+id, {{method:'POST', body: new URLSearchParams({{name: nn, location: ll, area: aa}})}}).then(()=>location.reload()) }}
          </script>
        </div>
        <div class=card><h3>📌 النقاط - حماة مركز</h3>
        """
        fixed = qall("SELECT * FROM towers ORDER BY id DESC")
        for t in fixed:
            h+=f"<div class=fixed-item style='display:flex;justify-content:space-between;align-items:center'><div><b>🔒 {esc(t['name'])}</b> - {esc(t['location'])} - {esc(t.get('area') or '')}</div><div class=actions><button class=btn-blue onclick='editTowerMap({t['id']}, {js_esc(t['name'])}, {js_esc(t.get('location') or '')}, {js_esc(t.get('area') or '')})'>تعديل</button><a href=/del_tower/{t['id']} data-del class=btn-red>حذف</a></div></div>"
        h+="</div>"
        return h
    elif v=='logs':
        rs=qall("SELECT * FROM activity_log ORDER BY id DESC LIMIT 200")
        rows="".join([f"<div class=log-row><span class=log-time>{esc(r['time'])}</span><span class=log-phone>👤 {esc(r['phone'])}</span><span>{esc(r['action'])}</span></div>" for r in rs])
        h=f"<div class=card><h3>📜 سجل النشاطات</h3><div class=logs-container>{rows}</div></div>"
        return h
    elif v=='notifications':
        rs=qall("SELECT * FROM notifications ORDER BY id DESC LIMIT 100")
        rows="".join([f"<div class='card notif-card'><div><b>{esc(r['title'])}</b><br><small>{esc(r['time'])}</small><p>{esc(r['msg'])}</p></div></div>" for r in rs])
        h=f"<div class=card><h3>🔔 الإشعارات</h3><button class=btn-blue onclick='fetch(\"/clear_notifs\").then(()=>loadPage(\"notifications\"))'>مسح الكل</button></div>{rows if rows else '<div class=card>لا يوجد اشعارات</div>'}"
        return h
    elif v=='support':
        # 8- دعم فني OMAIA ورقم وانستا
        h=f"""
        <div class=card style='text-align:center;border:2px solid {COLORS['gold']};max-width:500px;margin:20px auto'>
          <h2 style='margin:0'>{logo_html()}</h2>
          <p>الدعم الفني 24/7</p>
          <div style='font-size:22px;margin:12px;font-weight:bold' dir=ltr>+90 534 485 10 45</div>
          <a href='https://wa.me/905344851045' target=_blank class=btn-wa style='margin:6px'>💬 واتساب</a>
          <a href='tel:+905344851045' class=btn-blue style='margin:6px;display:inline-block;text-decoration:none;padding:10px 18px;border-radius:20px'>📞 اتصال</a>
          <div style='margin-top:18px;border-top:1px solid #334155;padding-top:12px'>
            <a href='https://instagram.com/af_20_1999' target='_blank' style='display:inline-flex;align-items:center;gap:8px;background:linear-gradient(45deg,#feda75,#fa7e1e,#d62976,#962fbf,#4f5bd5);color:#fff;padding:10px 18px;border-radius:20px;text-decoration:none;font-weight:bold'>
              <span style='font-size:20px'>📸</span> Instagram: af_20_1999
            </a>
          </div>
        </div>
        """
        return h
    elif v=='settings':
        us=qall("SELECT phone,username,role FROM users ORDER BY phone");uh=""
        for u in us: 
            ph=esc(u['phone']);un=esc(u.get('username') or u['phone']);role=esc(u.get('role') or '')
            un_js = js_esc(u.get('username') or u['phone'])
            ph_js = js_esc(u['phone'])
            uh+=f"<div class='card user-card'><div style='display:flex;align-items:center;gap:10px'><div class=avatar>{un[:1]}</div><div><b>{un}</b><br><small>📞 {ph} - {role}</small></div></div><div class=actions><button class=btn-blue onclick='editUser({ph_js}, {un_js})'>تعديل</button><a href=/del_user/{ph} data-del class=btn-red>حذف</a></div></div>"
        h=f"""
        <div class=card style='max-width:600px;margin:10px auto'><h3>⚙ إعدادات المستخدمين</h3>
        <form data-ajax method=post action=/change_pass><input name=newpass type=password required placeholder='كلمة السر الجديدة للجاري'><button class=btn-gold style='width:100%'>تغيير كلمة السر</button></form></div>
        <div class=card style='max-width:600px;margin:10px auto'><h3>➕ اضافة يوزر</h3><form data-ajax method=post action=/add_user class=form-row><input name=phone required placeholder='يوزر / رقم'><input name=password type=password required placeholder='كلمة السر'><select name=role><option value=tech>فني</option><option value=manager>مدير</option></select><button class=btn-gold>اضافة</button></form></div>
        <div style='max-width:600px;margin:10px auto'><h3>المستخدمين - تعديل وحذف</h3>{uh}</div>
        <div id=editUserModal class=modal><div class=modal-content><h3>تعديل يوزر</h3><form id=editUserForm method=post><input name=newphone id=edit_user_phone placeholder='يوزر جديد'><div style="display:flex;gap:8px;margin-top:10px"><button class=btn-gold>حفظ</button><button type=button class=btn onclick="document.getElementById('editUserModal').style.display='none'">الغاء</button></div></form></div></div>
        <script>function editUser(phone, username){{document.getElementById('edit_user_phone').value=username;document.getElementById('editUserModal').style.display='flex';document.getElementById('editUserForm').action='/edit_user/'+phone}}</script>
        """
        return h
    return "ok"

def layout(c,v='home'):
    th=cur_theme()
    bg=COLORS['bg_dark'] if th=='dark' else COLORS['bg_light']
    card=COLORS['card_dark'] if th=='dark' else COLORS['card_light']
    txt='#fff' if th=='dark' else '#0f172a'
    return f"""<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1,maximum-scale=1'>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
:root{{--gold:{COLORS['gold']};--bg:{bg};--card:{card};--text:{txt};--border:{COLORS['border_dark']};--input:{COLORS['input_dark']};--blue:{COLORS['btn_blue']};--red:{COLORS['btn_red']}}}
*{{box-sizing:border-box;font-family:'Cairo',system-ui,sans-serif}}body{{margin:0;background:var(--bg);color:var(--text);overflow-x:hidden;overscroll-behavior-y:contain}}
/* 10- نار وسريع - بدون لودر بطيء */
#loader-line{{position:fixed;top:0;left:0;height:3px;background:var(--gold);width:0;z-index:9999;transition:width .2s}}
.loader{{display:none !important}}
/* 12- قائمة يمين صغيرة */
.sidebar{{position:fixed;right:-280px;top:0;width:250px;height:100%;background:{COLORS['menu_bg']};transition:right .25s ease;z-index:1000;padding-top:60px;box-shadow:-5px 0 20px rgba(0,0,0,0.5);overflow-y:auto}}
.sidebar.active{{right:0}}
.sidebar a{{display:flex;align-items:center;gap:10px;padding:11px 14px;color:#fff;text-decoration:none;transition:all .15s;border-right:3px solid transparent;margin:2px 6px;border-radius:8px;font-size:13px}}
.sidebar a:hover{{background:#ffffff12;border-right-color:var(--gold)}}.sidebar a.active{{background:var(--gold);color:#000;font-weight:bold}}
.overlay{{position:fixed;inset:0;background:rgba(0,0,0,0.5);display:none;z-index:999;opacity:0;transition:opacity .2s}}.overlay.active{{display:block;opacity:1}}
.top{{position:fixed;top:0;left:0;right:0;background:{COLORS['top_bg']};padding:10px 14px;z-index:101;display:flex;align-items:center;justify-content:space-between;box-shadow:0 2px 10px rgba(0,0,0,0.2);border-bottom:1px solid var(--border);height:56px}}
.menu-btn{{font-size:20px;cursor:pointer;background:var(--input);width:38px;height:38px;display:flex;align-items:center;justify-content:center;border-radius:8px;transition:.15s}}
.menu-btn:hover{{background:var(--gold);color:#000}}
.main{{margin-right:250px;margin-top:56px;padding:12px;min-height:100vh;transition:margin .25s}}
.stats-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}}
.stat-card{{display:flex;align-items:center;gap:10px;padding:12px !important}}
.stat-card h3{{font-size:11px;color:#94a3b8;margin:0}} .stat-card h2{{font-size:22px;color:var(--gold);margin:2px 0 0}} .stat-icon{{font-size:22px;background:var(--input);width:40px;height:40px;display:flex;align-items:center;justify-content:center;border-radius:8px}}
.card{{background:{card};padding:14px;border-radius:12px;margin-bottom:10px;border:1px solid {COLORS['border_dark']};box-shadow:0 2px 8px rgba(0,0,0,0.15)}}
.btn{{background:var(--input);border:none;color:var(--text);padding:7px 12px;border-radius:7px;cursor:pointer;font-weight:bold;font-size:13px}}
.btn-gold{{background:var(--gold);color:#000;padding:8px 14px;border-radius:7px;border:none;font-weight:bold;cursor:pointer;font-size:13px}}
.btn-blue{{background:var(--blue);color:#fff;padding:7px 12px;border-radius:7px;border:none;cursor:pointer;font-size:13px}}
.btn-red{{background:var(--red);color:#fff;padding:7px 12px;border-radius:7px;border:none;cursor:pointer;text-decoration:none;font-size:13px}}
.btn-wa{{background:#25D366;color:#fff;padding:8px 16px;border-radius:18px;text-decoration:none;display:inline-block;font-weight:bold;font-size:13px}}
input,select{{width:100%;padding:10px;background:var(--input);border:1px solid var(--border);border-radius:8px;color:var(--text);margin:3px 0;font-size:13px}}
input:focus{{outline:none;border-color:var(--gold)}}
.form-row{{display:grid;grid-template-columns:1fr 1fr auto;gap:6px;align-items:end}}
@media(max-width:900px){{.main{{margin-right:0}}.form-row{{grid-template-columns:1fr}}.dishes-grid{{grid-template-columns:1fr !important}} .sidebar{{width:230px}}}}
.dishes-grid{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}
.dish-card{{border-right:3px solid var(--gold)}} .ip-badge{{background:#000;color:var(--gold);padding:4px 10px;border-radius:16px;font-size:12px;font-family:monospace;border:1px solid var(--gold)}}
.fixed-badge{{background:var(--gold);color:#000;padding:2px 6px;border-radius:8px;font-size:10px;font-weight:bold}} .fixed-item{{background:var(--input);padding:8px;border-radius:8px;margin:5px 0;border-right:3px solid var(--gold);font-size:13px}}
.sub-card,.tower-card{{display:flex;justify-content:space-between;align-items:center}}
.actions{{display:flex;gap:5px;flex-wrap:wrap}} .ping-box{{display:flex;gap:6px;margin:8px 0}}
pre{{background:#000;color:#0f0;padding:10px;border-radius:8px;min-height:40px;overflow:auto;font-size:11px}}
.log-row{{display:flex;gap:6px;padding:6px;border-bottom:1px solid var(--border);font-size:11px}} .log-time{{color:#94a3b8;min-width:70px}} .log-phone{{color:var(--gold);font-weight:bold;min-width:90px}}
.dist-grid{{display:grid;grid-template-columns:1fr 1fr;gap:6px}} .dist-result{{background:var(--input);padding:10px;border-radius:8px;margin-top:8px;text-align:center;border:1px dashed var(--gold);min-height:40px;font-size:13px}}
.modal{{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:2000;align-items:center;justify-content:center;backdrop-filter:blur(4px)}} .modal-content{{background:var(--card);padding:16px;border-radius:12px;width:92%;max-width:360px}}
.user-card{{display:flex;align-items:center;gap:8px;justify-content:space-between}} .avatar{{width:34px;height:34px;border-radius:50%;background:var(--gold);display:flex;align-items:center;justify-content:center;font-weight:bold;color:#000;font-size:14px}}
/* 11- زر ليل ونهار ولغة */
.top-actions{{display:flex;gap:6px;align-items:center}}
.top-actions button{{width:34px;height:34px;border-radius:8px;border:none;background:var(--input);color:var(--text);cursor:pointer;font-size:14px}}
/* 13- سحب لتحديث */
#pullHint{{position:fixed;top:56px;left:50%;transform:translateX(-50%) translateY(-50px);background:var(--gold);color:#000;padding:6px 14px;border-radius:20px;font-size:12px;font-weight:bold;transition:transform .25s;z-index:50}}
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
let currentPage='{v}';
function toggleMenu(){{let s=document.getElementById('sidebar'), o=document.getElementById('overlay');s.classList.toggle('active');o.classList.toggle('active');}}
function showLine(p){{document.getElementById('loader-line').style.width=p+'%';}}
function hideLine(){{setTimeout(()=>{{document.getElementById('loader-line').style.width='0'}},400);}}
window.loadPage=async function(v){{
  if(document.getElementById('sidebar').classList.contains('active'))toggleMenu();
  currentPage=v;
  document.querySelectorAll('.sidebar a').forEach(a=>a.classList.remove('active'));
  let nav=document.getElementById('nav-'+v);if(nav)nav.classList.add('active');
  showLine(40);
  try{{
    let r=await fetch('/api/page?v='+v);
    if(r.status==401){{location.href='/login';return}}
    let html=await r.text();
    document.getElementById('main').innerHTML=html;
    bindAjax();
    document.getElementById('main').querySelectorAll('script').forEach(s=>{{try{{eval(s.textContent)}}catch(e){{}}}});
  }}catch(e){{document.getElementById('main').innerHTML='<div class=card style=color:red>خطأ: '+e+'</div>'}}
  showLine(100); hideLine();
  window.scrollTo({{top:0,behavior:'smooth'}});
}}
function bindAjax(){{
  document.querySelectorAll('form[data-ajax]').forEach(f=>{{
    f.onsubmit=async e=>{{e.preventDefault();showLine(60);try{{let res=await fetch(f.action,{{method:'POST',body:new FormData(f)}});if(res.status==401){{location.href='/login';return}}if(!res.ok){{let t=await res.text();alert('خطأ: '+t);showLine(0);return}}loadPage(currentPage);}}catch(e){{alert('خطأ: '+e);showLine(0)}}}};
  }});
  document.querySelectorAll('a[data-del]').forEach(a=>{{
    a.onclick=async e=>{{e.preventDefault();if(!confirm('⚠ تأكيد الحذف؟'))return;showLine(60);let res=await fetch(a.href);if(res.status==401){{location.href='/login';return}}loadPage(currentPage);}};
  }});
}}
function pingDish(ip){{if(!ip){{alert('لا يوجد IP');return}}showLine(60);fetch('/api/ping?ip='+encodeURIComponent(ip)).then(r=>r.json()).then(j=>{{showLine(0);alert(j.out.slice(0,400))}}).catch(()=>showLine(0))}}
async function toggleTheme(){{showLine(40);await fetch('/toggle_theme');location.reload()}}
async function toggleLang(){{showLine(40);await fetch('/toggle_lang');location.reload()}}
document.addEventListener('keydown', e=>{{if(e.key==='Escape' && document.getElementById('sidebar').classList.contains('active'))toggleMenu()}});
// 13- سحب للأسفل لتحديث
let startY=0, pulling=false;
document.addEventListener('touchstart', e=>{{if(window.scrollY===0){{startY=e.touches[0].clientY; pulling=true;}}}});
document.addEventListener('touchmove', e=>{{
  if(!pulling) return;
  let diff = e.touches[0].clientY - startY;
  if(diff>0 && diff<120 && window.scrollY===0){{
    document.getElementById('pullHint').classList.add('show');
    if(diff>80) document.getElementById('pullHint').textContent='↻ اترك للتحديث';
    else document.getElementById('pullHint').textContent='↓ اسحب للتحديث';
  }}
}});
document.addEventListener('touchend', e=>{{
  let hint = document.getElementById('pullHint');
  if(hint.classList.contains('show') && hint.textContent.includes('اترك')){{
    loadPage(currentPage);
  }}
  hint.classList.remove('show');
  pulling=false;
}});
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
            add_log(f"تسجيل دخول: {uin}")
            return redirect('/dash')
        return f"<script>alert('بيانات خاطئة');location.href='/login'</script>",401
    # 1- صفحة تسجيل دخول OMAIA ISP + زر حفظ كلمة سر + placeholder داخل المربع فقط
    return f"""<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>OMAIA ISP - Login</title>
<style>
body{{display:flex;align-items:center;justify-content:center;background:{COLORS['bg_dark']};min-height:100vh;margin:0;font-family:'Cairo',sans-serif}}
.box{{background:#fff;padding:28px;border-radius:16px;width:92%;max-width:360px;box-shadow:0 20px 40px rgba(0,0,0,0.4)}}
input{{width:100%;padding:12px;margin:8px 0;border-radius:10px;border:1px solid #ccc;font-size:14px}}
.login-btn{{width:100%;background:{COLORS['gold']};color:#000;padding:13px;border:0;border-radius:10px;font-weight:900;font-size:16px;cursor:pointer;margin-top:12px}}
.save-row{{display:flex;align-items:center;gap:6px;margin:8px 0;font-size:13px;color:#334155}}
.save-row input{{width:auto;margin:0}}
</style>
</head><body><div class=box>
<h2 style='text-align:center;margin:0 0 6px'>{logo_html()}</h2>
<p style='text-align:center;color:#64748b;font-size:13px;margin:0 0 14px'>نظام إدارة الشبكة</p>
<form method=post>
<input name=userin placeholder='User / Phone' required autocomplete='username'>
<input name=password type=password placeholder='كلمة السر' required autocomplete='current-password'>
<label class=save-row><input type=checkbox id=savePass> حفظ كلمة السر</label>
<button class=login-btn>دخول</button>
</form>
<script>
let u=document.querySelector('input[name=userin]'), p=document.querySelector('input[name=password]'), s=document.getElementById('savePass');
let saved=localStorage.getItem('omaia_user'), savedP=localStorage.getItem('omaia_pass');
if(saved){{u.value=saved; if(savedP){{p.value=savedP; s.checked=true;}} }}
document.querySelector('form').addEventListener('submit',()=>{{if(s.checked){{localStorage.setItem('omaia_user',u.value);localStorage.setItem('omaia_pass',p.value);}}else{{localStorage.removeItem('omaia_user');localStorage.removeItem('omaia_pass');}}}});
</script>
</div></body></html>"""

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
    f=request.form
    qexec("UPDATE ledger SET name=?, amount=?, currency=?, note=? WHERE id=?",(f.get('name',''),fnum(f.get('amount')),f.get('currency','USD'),f.get('note',''),i))
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
    qexec("INSERT INTO towers(name,location,area,lat,lng,fixed) VALUES(?,?,?,?,?,?)",(f.get('name',''),f.get('location',''),f.get('area',''),35.1318,36.7578,1 if f.get('fixed') else 0))
    add_log(f"اضافة برج: {f.get('name','')}")
    return "ok"

@app.route('/edit_tower/<int:i>',methods=['POST'])
@login_required
def edit_tower(i):
    f=request.form
    qexec("UPDATE towers SET name=?, location=?, area=? WHERE id=?",(f.get('name',''),f.get('location',''),f.get('area',''),i))
    add_log(f"تعديل برج {i}")
    return "ok"

@app.route('/del_tower/<int:i>')
@manager_required
def d2(i):
    t=qone("SELECT * FROM towers WHERE id=?",(i,))
    if not t: return "غير موجود",404
    if t.get('fixed') and False: return "⛔ نقطة ثابتة لا تحذف",403
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
