from flask import Flask, request, redirect, session, jsonify, Response
from colors import COLORS, logo_html
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, datetime, json, html, subprocess, platform, ipaddress, socket, csv, io
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
        print(f"qall error: {e} | q={q} | a={a}");cc(c);return []

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
    except Exception as e: print(f"qexec error: {e} | q={q} | a={a}");cc(c)

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
    except: pass

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
    # 1- تخزين دائم: فهرسة + safe_alter
    for tbl,col,defi in [("towers","location","TEXT"),("towers","fixed","INT DEFAULT 0"),("towers","area","TEXT"),("dish_ips","dish_name","TEXT"),("dish_ips","tower_name","TEXT"),("users","username","TEXT"),("ledger","note","TEXT"),("ledger","currency","TEXT"),("ledger","name","TEXT")]:
        safe_alter(tbl,col,defi)
    # 21- فهرسة البحث
    try:
        qexec("CREATE INDEX IF NOT EXISTS idx_dish_ip ON dish_ips(ip)")
        qexec("CREATE INDEX IF NOT EXISTS idx_dish_name ON dish_ips(dish_name)")
        qexec("CREATE INDEX IF NOT EXISTS idx_tower_name ON towers(name)")
        qexec("CREATE INDEX IF NOT EXISTS idx_subs_name ON subs(name)")
        qexec("CREATE INDEX IF NOT EXISTS idx_ledger_name ON ledger(name)")
    except: pass
    if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username,active) VALUES(?,?,?,?,?)",('05344851045',generate_password_hash('admin2024'),'manager','admin',1))
    if not qone("SELECT * FROM towers WHERE fixed=1"):
        qexec("INSERT INTO towers(name,lat,lng,location,area,fixed) VALUES(?,?,?,?,?,?)",('نقطة حماة الرئيسية',35.1318,36.7578,'حماة','حماة',1))
init()

def add_log(action):
    ph = session.get('phone','system')
    qexec("INSERT INTO activity_log(time,action,phone) VALUES(?,?,?)",(datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), action, ph))
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

@app.route('/api/ping')
@login_required
def api_ping():
    ip=request.args.get('ip','').strip()
    if not ip: return jsonify(ok=False,out='لا يوجد IP')
    if not is_internal_ip(ip): return jsonify(ok=False,out='⛔ خارج الشبكة')
    # 25- بنج حقيقي: محاولة local agent على 5001
    try:
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", 5001, timeout=2)
        conn.request("GET", f"/ping?ip={ip}")
        r = conn.getresponse()
        data = r.read().decode()[:1500]
        if r.status==200:
            return jsonify(ok=True,out=f"🖥️ Local Agent: {data}")
    except: pass
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

@app.route('/api/backup')
@login_required
def api_backup():
    # 1- نسخة احتياطية تلقائية JSON
    data = {
        "users": qall("SELECT * FROM users"),
        "subs": qall("SELECT * FROM subs"),
        "dish_ips": qall("SELECT * FROM dish_ips"),
        "towers": qall("SELECT * FROM towers"),
        "ledger": qall("SELECT * FROM ledger"),
        "logs": qall("SELECT * FROM activity_log ORDER BY id DESC LIMIT 500"),
    }
    return jsonify(data)

@app.route('/export/excel')
@login_required
def export_excel():
    # 26- تصدير Excel (CSV يفتح ب Excel)
    typ = request.args.get('t','dishes')
    output = io.StringIO()
    writer = csv.writer(output)
    if typ=='dishes':
        writer.writerow(['اسم الصحن','IP','الموقع'])
        for r in qall("SELECT * FROM dish_ips"):
            writer.writerow([r.get('dish_name',''), r.get('ip',''), r.get('location','')])
    elif typ=='towers':
        writer.writerow(['اسم البرج','المنطقة'])
        for r in qall("SELECT * FROM towers"):
            writer.writerow([r.get('name',''), r.get('area','')])
    elif typ=='subs':
        writer.writerow(['الاسم','الهاتف'])
        for r in qall("SELECT * FROM subs"):
            writer.writerow([r.get('name',''), r.get('phone','')])
    else:
        writer.writerow(['الاسم','المبلغ','النوع','العملة'])
        for r in qall("SELECT * FROM ledger"):
            writer.writerow([r.get('name',''), r.get('amount',''), r.get('typ',''), r.get('currency','')])
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment;filename={typ}.csv"})

@app.route('/export/pdf')
@login_required
def export_pdf():
    # 27- تصدير PDF بسيط HTML printable
    typ = request.args.get('t','dishes')
    rows=""
    if typ=='dishes':
        for r in qall("SELECT * FROM dish_ips"):
            rows+=f"<tr><td>{esc(r.get('dish_name',''))}</td><td>{esc(r.get('ip',''))}</td><td>{esc(r.get('location',''))}</td></tr>"
        html_content=f"<h2>الصحون</h2><table border=1 style='width:100%'><tr><th>اسم</th><th>IP</th><th>موقع</th></tr>{rows}</table>"
    else:
        for r in qall("SELECT * FROM towers"):
            rows+=f"<tr><td>{esc(r.get('name',''))}</td><td>{esc(r.get('area',''))}</td></tr>"
        html_content=f"<h2>الابراج</h2><table border=1 style='width:100%'><tr><th>اسم</th><th>منطقة</th></tr>{rows}</table>"
    return f"<html><head><meta charset=utf-8><title>Export {typ}</title></head><body dir=rtl onload=window.print()>{html_content}</body></html>"

def page_content(v):
    h=""; can = can_edit(); tech = is_tech()
    edit_btn_attr = "" if can else "disabled style='display:none'"
    # 13-15 تحسينات اداء
    if v=='home':
        ns=(qone("SELECT COUNT(*) c FROM subs") or {}).get('c',0)
        nd=(qone("SELECT COUNT(*) c FROM dish_ips") or {}).get('c',0)
        nt=(qone("SELECT COUNT(*) c FROM towers") or {}).get('c',0)
        h=f"""
        <div style='max-width:700px;margin:0 auto;text-align:center'>
          <div style='margin:20px 0'><div style='font-size:32px'>{logo_html()}</div><p style='color:{COLORS['text_muted_dark']};margin:5px 0'>OMAIA ISP - نسخة محمية DB دائم</p></div>
          <div style='display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:20px'>
            <div class=card style='padding:20px;cursor:pointer;text-align:center' onclick="loadPage('subs')"><div style='font-size:28px'>👥</div><h3 style='margin:8px 0'>المشتركين</h3><h2 style='color:{COLORS['gold']};margin:0'>{ns}</h2></div>
            <div class=card style='padding:20px;cursor:pointer;text-align:center' onclick="loadPage('dishes')"><div style='font-size:28px'>📡</div><h3 style='margin:8px 0'>الصحون</h3><h2 style='color:{COLORS['gold']};margin:0'>{nd}</h2></div>
            <div class=card style='padding:20px;cursor:pointer;text-align:center' onclick="loadPage('towers')"><div style='font-size:28px'>🗼</div><h3 style='margin:8px 0'>الأبراج</h3><h2 style='color:{COLORS['gold']};margin:0'>{nt}</h2></div>
            <div class=card style='padding:20px;cursor:pointer;text-align:center' onclick="loadPage('map')"><div style='font-size:28px'>🗺</div><h3 style='margin:8px 0'>الخريطة</h3><h2 style='color:{COLORS['gold']};margin:0'>📍</h2></div>
          </div>
          <div style='margin-top:12px;display:flex;gap:8px;justify-content:center'>
            <a href='/export/excel?t=dishes' class=btn-blue>📊 Excel صحون</a>
            <a href='/export/excel?t=towers' class=btn-blue>📊 Excel ابراج</a>
            <button class=btn-gold onclick="fetch('/api/backup').then(r=>r.json()).then(j=>{{localStorage.setItem('backup_'+Date.now(), JSON.stringify(j)); showToast('✅ نسخة احتياطية محفوظة محلياً')}})">💾 نسخ احتياطي</button>
          </div>
        </div>
        """
        return h
    elif v=='subs':
        # 14- تحميل تدريجي 20
        page = int(request.args.get('page','1') or 1)
        limit=20; offset=(page-1)*20
        q = request.args.get('q','').strip()
        if q:
            rs=qall("SELECT * FROM subs WHERE name LIKE ? OR phone LIKE ? ORDER BY id DESC LIMIT 20 OFFSET ?", (f"%{q}%", f"%{q}%", offset))
        else:
            rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 20 OFFSET ?", (offset,))
        rows=""
        for r in rs:
            name_js = js_esc(r['name']); phone_js = js_esc(r['phone'])
            # 12- مربعات ملونة بزوايا مدورة
            edit_b = f"<button class='btn-icon edit' onclick='editSub({r['id']}, {name_js}, {phone_js})' title='تعديل' {edit_btn_attr}>✏️</button>" if can else ""
            del_b = f"<button class='btn-icon del' onclick='delItem(\"/del_sub/{r['id']}\")' title='حذف'>🗑️</button>" if can else ""
            rows+=f"<div class='card list-card' data-search='{esc(r['name'])} {esc(r['phone'])}' style='display:flex;justify-content:space-between;align-items:center'><div><b>{esc(r['name'])}</b><br><small>📞 {esc(r['phone'])}</small></div><div class=actions>{edit_b}{del_b}</div></div>"
        h=f"""
        <div style='max-width:1100px;margin:0 auto'>
          <div class=card style='text-align:center'>
            <h3>👥 المشتركين</h3>
            <div style='display:flex;gap:8px;max-width:500px;margin:0 auto'><input id=searchInput placeholder='🔍 بحث فوري IP أو اسم...' oninput="liveSearch(this.value)" onkeydown="if(event.key==='Enter')liveSearch(this.value)" style='flex:1'><button class=btn-blue onclick="loadPage('subs',true)">↻</button></div>
            <form data-ajax method=post action=/add_sub style='display:flex;gap:8px;max-width:400px;margin:12px auto'><input name=name required placeholder='الاسم'><input name=phone placeholder='رقم'><button class=btn-gold>اضافة</button></form>
          </div>
          <div id=listContainer style='display:grid;grid-template-columns:1fr 1fr;gap:10px'>{rows if rows else '<div class=card>لا يوجد</div>'}</div>
          <div style='text-align:center;margin:12px'><button class=btn onclick="loadMore('subs')">تحميل 20 المزيد</button> <a href='/export/excel?t=subs' class=btn-blue>Excel</a></div>
        </div>
        <div id=editModal class=modal><div class=modal-content><h3>تعديل مشترك</h3><form id=editForm method=post><input name=name id=edit_name required><input name=phone id=edit_phone><div style="display:flex;gap:8px;margin-top:10px"><button class=btn-gold>حفظ</button><button type=button class=btn onclick="closeModal()">الغاء</button></div></form></div></div>
        <script>function editSub(id,name,phone){{document.getElementById('edit_name').value=name;document.getElementById('edit_phone').value=phone;document.getElementById('editModal').style.display='flex';document.getElementById('editForm').action='/edit_sub/'+id}}function closeModal(){{document.getElementById('editModal').style.display='none'}}</script>
        """
        return h
    elif v=='dishes':
        page = int(request.args.get('page','1') or 1); limit=20; offset=(page-1)*20
        q = request.args.get('q','').strip()
        if q:
            rs=qall("SELECT * FROM dish_ips WHERE dish_name LIKE ? OR ip LIKE ? OR location LIKE ? ORDER BY id DESC LIMIT 20 OFFSET ?", (f"%{q}%",f"%{q}%",f"%{q}%",offset))
        else:
            rs=qall("SELECT * FROM dish_ips ORDER BY id DESC LIMIT 20 OFFSET ?", (offset,))
        cards=""
        for r in rs:
            ip=esc(r.get('ip') or ''); dname = esc(r.get('dish_name') or 'بدون اسم'); dname_js = js_esc(r.get('dish_name') or ''); loc = esc(r.get('location') or ''); loc_js = js_esc(r.get('location') or '')
            edit_b = f"<button class='btn-icon edit' onclick='editDish({r['id']}, {dname_js}, \"{ip}\", {loc_js})' title='تعديل' {edit_btn_attr}>✏️</button>" if can else ""
            del_b = f"<button class='btn-icon del' onclick='delItem(\"/del_dish/{r['id']}\")' title='حذف'>🗑️</button>" if can else ""
            # 2- كروت الصحون يمين - عمودين
            cards+=f"<div class='card list-card' data-search='{dname} {ip} {loc}'><div><b>📡 {dname}</b></div><a href='http://{ip}' target='_blank' class=ip-badge>🌐 {ip}</a><br><small>📍 {loc}</small><div class=actions style='margin-top:8px'><button class=btn-blue onclick='pingDish(\"{ip}\")' style='padding:5px 10px;font-size:12px'>بينغ</button>{edit_b}{del_b}</div></div>"
        # 2- صفحة عمودين + 3- كرتين بنفس السطر
        h=f"""
        <div style='max-width:1200px;margin:0 auto'>
          <div style='display:grid;grid-template-columns:340px 1fr;gap:12px' class=dishes-layout>
            <div><div class=card style='text-align:center;position:sticky;top:70px'><h3>📡 اضافة صحن</h3>
              <input id=searchInput placeholder='🔍 بحث فوري IP أو اسم' oninput="liveSearch(this.value)" onkeydown="if(event.key==='Enter'){{loadPageWithQ('dishes', this.value)}}" style='margin-bottom:8px'>
              <form data-ajax method=post action=/add_dish style='display:flex;flex-direction:column;gap:8px'><input name=dish_name required placeholder='اسم الصحن'><input name=ip required placeholder='IP داخلي' onkeydown="if(event.key==='Enter'){{event.preventDefault(); liveSearch(this.value)}}"><input name=location placeholder='الموقع'><button class=btn-gold>اضافة</button></form>
              <div style='margin-top:10px;display:flex;gap:6px;justify-content:center'><a href='/export/excel?t=dishes' class=btn-blue>Excel</a><a href='/export/pdf?t=dishes' class=btn>PDF</a></div>
            </div></div>
            <div><div id=listContainer style='display:grid;grid-template-columns:1fr 1fr;gap:10px'>{cards if cards else '<div class=card>لا يوجد</div>'}</div><div style='text-align:center;margin:12px'><button class=btn onclick="loadMore('dishes')">تحميل 20 المزيد</button></div></div>
          </div>
        </div>
        <div id=editDishModal class=modal><div class=modal-content><h3>تعديل صحن</h3><form id=editDishForm method=post><input name=dish_name id=edit_dish_name required><input name=ip id=edit_dish_ip required><input name=location id=edit_dish_loc><div style='display:flex;gap:8px;margin-top:10px'><button class=btn-gold>حفظ</button><button type=button class=btn onclick="document.getElementById('editDishModal').style.display='none'">الغاء</button></div></form></div></div>
        <script>function editDish(id,name,ip,loc){{document.getElementById('edit_dish_name').value=name;document.getElementById('edit_dish_ip').value=ip;document.getElementById('edit_dish_loc').value=loc;document.getElementById('editDishModal').style.display='flex';document.getElementById('editDishForm').action='/edit_dish/'+id}}</script>
        """
        return h
    elif v=='towers':
        page = int(request.args.get('page','1') or 1); offset=(page-1)*20
        q = request.args.get('q','').strip()
        if q:
            rs=qall("SELECT * FROM towers WHERE name LIKE ? OR area LIKE ? ORDER BY id DESC LIMIT 20 OFFSET ?", (f"%{q}%",f"%{q}%",offset))
        else:
            rs=qall("SELECT * FROM towers ORDER BY id DESC LIMIT 20 OFFSET ?", (offset,))
        cards=""
        for r in rs:
            tname_js = js_esc(r['name']); tarea_js = js_esc(r.get('area') or ''); area = esc(r.get('area') or '')
            edit_b = f"<button class='btn-icon edit' onclick='editTower({r['id']}, {tname_js}, {tarea_js})' title='تعديل' {edit_btn_attr}>✏️</button>" if can else ""
            del_b = f"<button class='btn-icon del' onclick='delItem(\"/del_tower/{r['id']}\")' title='حذف'>🗑️</button>" if can else ""
            cards+=f"<div class='card list-card' data-search='{esc(r['name'])} {area}' style='display:flex;justify-content:space-between;align-items:center'><div><b>🗼 {esc(r['name'])}</b><br><small>🗺 {area}</small></div><div class=actions>{edit_b}{del_b}</div></div>"
        h=f"""
        <div style='max-width:1100px;margin:0 auto'>
          <div class=card style='text-align:center'><h3>🗼 الأبراج</h3><div style='display:flex;gap:8px;max-width:500px;margin:0 auto'><input id=searchInput placeholder='🔍 بحث فوري اسم أو منطقة' oninput="liveSearch(this.value)" onkeydown="if(event.key==='Enter')loadPageWithQ('towers', this.value)" style='flex:1'><button class=btn-gold onclick="loadMore('towers')">المزيد</button></div>
          <form data-ajax method=post action=/add_tower style='display:flex;gap:8px;max-width:400px;margin:12px auto'><input name=name required placeholder='اسم البرج'><input name=area required placeholder='المنطقة'><button class=btn-gold>اضافة</button></form></div>
          <div id=listContainer style='display:grid;grid-template-columns:1fr 1fr;gap:10px'>{cards}</div>
          <div style='text-align:center;margin:10px'><a href='/export/excel?t=towers' class=btn-blue>Excel</a> <a href='/export/pdf?t=towers' class=btn>PDF</a></div>
        </div>
        <div id=editTowerModal class=modal><div class=modal-content><h3>تعديل برج</h3><form id=editTowerForm method=post><input name=name id=edit_tower_name required><input name=area id=edit_tower_area required><div style="display:flex;gap:8px;margin-top:10px"><button class=btn-gold>حفظ</button><button type=button class=btn onclick="document.getElementById('editTowerModal').style.display='none'">الغاء</button></div></form></div></div>
        <script>function editTower(id,name,area){{document.getElementById('edit_tower_name').value=name;document.getElementById('edit_tower_area').value=area;document.getElementById('editTowerModal').style.display='flex';document.getElementById('editTowerForm').action='/edit_tower/'+id}}</script>
        """
        return h
    elif v=='ledger':
        rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 100")
        rows_html=""
        for r in rs:
            cur_icon = "$" if (r.get('currency') or 'USD')=='USD' else "ل.س"
            typ = esc(r.get('typ') or 'دين')
            name_js = js_esc(r.get('name') or ''); amount = r['amount']
            edit_b = f"<button class='btn-icon edit' onclick='editLedger({r['id']}, {name_js}, \"{amount}\", \"{typ}\", \"{r.get('currency') or 'USD'}\")' {edit_btn_attr}>✏️</button>" if can else ""
            del_b = f"<button class='btn-icon del' onclick='delItem(\"/del_ledger/{r['id']}\")'>🗑️</button>" if can else ""
            rows_html+=f"<div class='card list-card' data-search='{esc(r.get('name') or '')} {amount}' style='display:flex;justify-content:space-between;align-items:center'><div><b>{esc(r.get('name') or '')}</b> | <span style='color:{COLORS['gold']};font-weight:bold'>{amount} {cur_icon}</span> <span style='background:{COLORS['input_dark']};padding:2px 8px;border-radius:10px;font-size:12px'>{typ}</span></div><div class=actions>{edit_b}{del_b}</div></div>"
        h=f"""
        <div style='max-width:800px;margin:0 auto'>
          <div class=card style='text-align:center'><h3>📒 دفتر الحسابات</h3>
            <input id=searchInput placeholder='🔍 بحث فوري اسم' oninput="liveSearch(this.value)" style='max-width:300px;margin:0 auto 10px'>
            <form data-ajax method=post action=/add_ledger style='display:grid;grid-template-columns:1fr 1fr;gap:8px;max-width:450px;margin:0 auto'><input name=name required placeholder='الاسم'><input name=amount type=number step=0.01 required placeholder='مبلغ'><select name=typ><option>دين</option><option>دفع</option></select><select name=currency><option value=USD>$</option><option value=SYP>ل.س</option></select><button class=btn-gold style='grid-column:span 2'>اضافة</button></form>
          </div>
          <div id=listContainer>{rows_html}</div>
        </div>
        <div id=editLedgerModal class=modal><div class=modal-content><h3>تعديل حساب</h3><form id=editLedgerForm method=post><input name=name id=edit_ledger_name required><input name=amount id=edit_ledger_amount type=number step=0.01 required><select name=typ id=edit_ledger_typ><option>دين</option><option>دفع</option></select><select name=currency id=edit_ledger_cur><option value=USD>$</option><option value=SYP>ل.س</option></select><div style="display:flex;gap:8px;margin-top:10px"><button class=btn-gold>حفظ</button><button type=button class=btn onclick="document.getElementById('editLedgerModal').style.display='none'">الغاء</button></div></form></div></div>
        <script>function editLedger(id,name,amount,typ,cur){{document.getElementById('edit_ledger_name').value=name;document.getElementById('edit_ledger_amount').value=amount;document.getElementById('edit_ledger_typ').value=typ;document.getElementById('edit_ledger_cur').value=cur;document.getElementById('editLedgerModal').style.display='flex';document.getElementById('editLedgerForm').action='/edit_ledger/'+id}}</script>
        """
        return h
    elif v=='map':
        towers = qall("SELECT * FROM towers")
        towers_js = json.dumps([{"id": t['id'], "name": t['name'], "lat": float(t.get('lat') or 35.1318), "lng": float(t.get('lng') or 36.7578), "area": str(t.get('area') or '')} for t in towers], ensure_ascii=False)
        h=f"""
        <div style='width:100%;max-width:100%;margin:0 auto;padding:0'>
          <div class=card style='padding:6px;margin:0;width:100%'>
            <div style='display:flex;gap:8px;margin-bottom:8px'><input id=mapSearch placeholder='🔍 بحث فوري برج أو منطقة - Enter للذهاب' style='flex:1' onkeydown="if(event.key==='Enter')searchMap(this.value)"><button class=btn-blue onclick='searchMap(document.getElementById("mapSearch").value)'>بحث</button></div>
            <div id=map style='height:calc(100vh - 180px);min-height:500px;width:100%;border-radius:14px;touch-action:none;z-index:1'></div>
            <div style='margin-top:8px;display:flex;gap:8px;justify-content:center;flex-wrap:wrap'><button class=btn-blue onclick='getMyLocation()'>📍 موقعي</button><button class=btn-gold onclick='calcDistMode()'>📏 قياس</button><span id=distResult style='font-size:12px;background:{COLORS['input_dark']};padding:6px 12px;border-radius:20px'>اضغط نقطتين</span></div>
            <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
            <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
            <script>
              let map = L.map('map', {{zoomControl:true, dragging:!L.Browser.mobile, scrollWheelZoom:true, doubleClickZoom:true, boxZoom:true, keyboard:false, tap:true, touchZoom:true, bounceAtZoomLimits:false}}).setView([35.1318, 36.7578], 16);
              L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}', {{ attribution: 'OMAIA ISP - Ultra HD', maxZoom: 23, maxNativeZoom: 19, tileSize:256, detectRetina:true }}).addTo(map);
              setTimeout(()=>{{map.invalidateSize();}}, 400);
              let mapEl = document.getElementById('map');
              ['touchstart','touchmove','touchend'].forEach(ev=>{{mapEl.addEventListener(ev, e=>{{e.stopPropagation(); window.mapActive=true;}}, {{passive:false}});}});
              mapEl.addEventListener('mouseenter', ()=>{{window.mapActive=true}}); mapEl.addEventListener('mouseleave', ()=>{{window.mapActive=false}});
              let towers = {towers_js};
              let markers={{}};
              towers.forEach(t=>{{let m = L.marker([t.lat, t.lng]).addTo(map); m.bindPopup(`<div style='text-align:center'><b>${{t.name}}</b><br>🗺 ${{t.area}}</div>`); markers[t.name.toLowerCase()]=m; markers[t.area.toLowerCase()]=m;}});
              window.searchMap = function(q){{q=q.toLowerCase().trim(); if(!q)return; for(let k in markers){{if(k.includes(q)){{let m=markers[k]; map.setView(m.getLatLng(), 18); m.openPopup(); showToast('📍 '+k); return;}}}} showToast('❌ غير موجود')}};
              let userMarker=null;
              if(navigator.geolocation){{navigator.geolocation.getCurrentPosition(pos=>{{map.setView([pos.coords.latitude, pos.coords.longitude], 17); userMarker = L.marker([pos.coords.latitude, pos.coords.longitude]).addTo(map).bindPopup('📍 أنت هنا').openPopup();}}, null, {{enableHighAccuracy:true, timeout:10000, maximumAge:0}});}}
              window.getMyLocation = function(){{if(navigator.geolocation){{navigator.geolocation.getCurrentPosition(pos=>{{map.setView([pos.coords.latitude, pos.coords.longitude], 18); if(userMarker) map.removeLayer(userMarker); userMarker = L.marker([pos.coords.latitude, pos.coords.longitude]).addTo(map).bindPopup('📍 موقعك').openPopup();}}, null, {{enableHighAccuracy:true}});}}}}
              let distPoints=[], distLine=null; window.distMode=false;
              map.on('click', e=>{{if(window.distMode){{distPoints.push(e.latlng); L.marker(e.latlng).addTo(map); if(distPoints.length==2){{let d=map.distance(distPoints[0], distPoints[1]); document.getElementById('distResult').innerHTML = `📍 ${{(d/1000).toFixed(3)}} كم`; if(distLine) map.removeLayer(distLine); distLine = L.polyline(distPoints, {{color: '{COLORS['gold']}', weight:4}}).addTo(map); distPoints=[]; window.distMode=false;}}}}}});
              window.calcDistMode = function(){{window.distMode=true; document.getElementById('distResult').textContent='اضغط نقطتين'; distPoints=[]; if(distLine) map.removeLayer(distLine);}}
            </script>
          </div>
        </div>
        """
        return h
    elif v=='logs':
        rs=qall("SELECT * FROM activity_log ORDER BY id DESC LIMIT 200")
        # 5- سجل النشاطات يطلع يوزر أو رقم الشخص اللي ضاف
        rows="".join([f"<div class=log-row><span class=log-time>{esc(r['time'])}</span><span style='background:{COLORS['gold']};color:#000;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:bold'>👤 {esc(r['phone'])}</span><span>{esc(r['action'])}</span></div>" for r in rs])
        h=f"<div style='max-width:650px;margin:0 auto'><div class=card><h3 style='text-align:center'>📜 سجل النشاطات - من أضاف/عدل</h3><div class=logs-container>{rows}</div></div></div>"
        return h
    elif v=='notifications':
        rs=qall("SELECT * FROM notifications ORDER BY id DESC LIMIT 100")
        rows="".join([f"<div class='card' style='max-width:550px;margin:8px auto'><div><b>{esc(r['title'])}</b><br><small>{esc(r['time'])}</small><p>{esc(r['msg'])}</p></div></div>" for r in rs])
        h=f"<div style='max-width:600px;margin:0 auto'><div class=card style='text-align:center'><h3>🔔 الإشعارات</h3><button class=btn-blue onclick='fetch(\"/clear_notifs\").then(()=>{{showToast('تم المسح'); loadPage(\"notifications\",true)}})'>مسح الكل</button></div>{rows if rows else '<div class=card style=text-align:center>لا يوجد</div>'}</div>"
        return h
    elif v=='support':
        # 6- دعم فني واتساب + انستا af_20_1999 فقط بقائمة الدعم
        h=f"""
        <div style='max-width:500px;margin:20px auto'><div class=card style='text-align:center;border:2px solid {COLORS['gold']}'>
          <h2 style='margin:0'>{logo_html()}</h2><p>الدعم الفني</p>
          <div style='font-size:22px;margin:12px;font-weight:bold' dir=ltr>+90 534 485 10 45</div>
          <a href='https://wa.me/905344851045' target=_blank class=btn-wa style='margin:6px;display:inline-flex;align-items:center;gap:6px'>💬 واتساب</a>
          <a href='https://instagram.com/af_20_1999' target=_blank style='background:linear-gradient(45deg,#feda75,#fa7e1e,#d62976,#962fbf,#4f5bd5);color:#fff;padding:10px 18px;border-radius:20px;text-decoration:none;margin:6px;display:inline-flex;font-weight:bold'>📸 @af_20_1999 انستا</a>
          <div style='margin-top:10px;font-size:11px;color:{COLORS['text_muted_dark']}'>يظهر فقط هنا بقائمة الدعم الفني</div>
        </div></div>
        """
        return h
    elif v=='settings':
        us=qall("SELECT phone,username,role FROM users ORDER BY phone")
        uh=""
        for u in us:
            ph=esc(u['phone']); un=esc(u.get('username') or u['phone'])
            role = u.get('role') or 'tech'
            # 8- تحت الاسم رقم الهاتف أو اليوزر بس بدون tech
            # 11- بالكروت يطلع بس فني و مدير
            role_label = "👨‍💼 مدير" if role=='manager' else "🔧 فني"
            ph_js = js_esc(u['phone']); un_js = js_esc(u.get('username') or u['phone'])
            if tech:
                # 9- فني يضيف بس - اخفاء ازرار
                uh+=f"<div class='card' style='max-width:550px;margin:8px auto;display:flex;justify-content:space-between;align-items:center'><div style='display:flex;align-items:center;gap:10px'><div class=avatar>{un[:1]}</div><div><b>{un}</b><br><small>📞 {ph}</small><br><span style='font-size:11px;background:{COLORS['input_dark']};padding:2px 8px;border-radius:10px'>{role_label}</span></div></div></div>"
            else:
                # 7- تفعيل تعديل وحذف + 10- مدير كل الصلاحيات
                uh+=f"<div class='card' style='max-width:550px;margin:8px auto;display:flex;justify-content:space-between;align-items:center'><div style='display:flex;align-items:center;gap:10px'><div class=avatar>{un[:1]}</div><div><b>{un}</b><br><small>📞 {ph}</small><br><span style='font-size:11px;background:{COLORS['gold']}33;padding:2px 8px;border-radius:10px'>{role_label}</span></div></div><div class=actions><button class='btn-icon edit' onclick='editUser({ph_js}, {un_js})'>✏️</button><button class='btn-icon del' onclick='delItem(\"/del_user/{ph}\")'>🗑️</button></div></div>"
        h=f"""
        <div style='max-width:650px;margin:0 auto'>
          <div class=card style='text-align:center'><h3>⚙ إعدادات</h3>
            <div style='display:grid;grid-template-columns:1fr 1fr;gap:10px;max-width:500px;margin:0 auto'>
              <form data-ajax method=post action=/change_pass><input name=newpass type=password required placeholder='كلمة السر الجديدة'><button class=btn-gold style='width:100%'>تغيير كلمة السر</button></form>
              <div style='display:flex;flex-direction:column;gap:8px'><button class=btn onclick='toggleTheme()' style='width:100%'>🌓 ليل/نهار</button><button class=btn style='width:100%;background:{COLORS['blue']};color:#fff' onclick='toggleLang()'>🌐 اللغة</button></div>
            </div>
          </div>
          <div class=card style='text-align:center'><h3>➕ اضافة مستخدم</h3><form data-ajax method=post action=/add_user style='display:flex;flex-direction:column;gap:8px;max-width:400px;margin:0 auto'><input name=phone required placeholder='يوزر / رقم'><input name=password type=password required placeholder='كلمة السر'><select name=role><option value=tech>فني - يضيف فقط</option><option value=manager>مدير - كل الصلاحيات</option></select><button class=btn-gold>اضافة</button></form></div>
          <div><h3 style='text-align:center'>المستخدمين - يظهر فني/مدير فقط</h3>{uh}</div>
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
    return f"""<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no'>
<meta http-equiv="Cache-Control" content="no-cache">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
:root{{--gold:{COLORS['gold']};--bg:{bg};--card:{card};--text:{txt};--border:{COLORS['border_dark']};--input:{COLORS['input_dark']};--blue:{COLORS['btn_blue']};--red:{COLORS['btn_red']};--wa:{COLORS['btn_wa']}}}
*{{box-sizing:border-box;font-family:'Cairo',system-ui,sans-serif; -webkit-tap-highlight-color:transparent}}
body{{margin:0;background:var(--bg);color:var(--text);overflow-x:hidden;overscroll-behavior:none}}
#loader-line{{position:fixed;top:0;left:0;height:3px;background:var(--gold);width:0;z-index:9999;transition:width .15s ease-out;pointer-events:none}}
.sidebar{{position:fixed;right:-300px;top:0;width:280px;height:100%;background:{COLORS['menu_bg']};transition:right .3s;z-index:1000;padding-top:70px;box-shadow:-8px 0 30px rgba(0,0,0,0.6);overflow-y:auto}}
.sidebar.active{{right:0}}
.sidebar a{{display:flex;align-items:center;gap:12px;padding:13px 16px;color:{COLORS['white']};text-decoration:none;transition:all .2s;margin:3px 8px;border-radius:12px;font-size:14px}}
.sidebar a.active{{background:var(--gold);color:{COLORS['black']};font-weight:bold}}
.overlay{{position:fixed;inset:0;background:{COLORS['black']}70;backdrop-filter:blur(3px);display:none;z-index:999}} .overlay.active{{display:block}}
.top{{position:fixed;top:0;left:0;right:0;background:{COLORS['top_bg']};padding:0 16px;z-index:101;display:flex;align-items:center;justify-content:space-between;height:60px;border-bottom:1px solid var(--border)}}
.menu-btn{{font-size:22px;cursor:pointer;background:var(--input);width:42px;height:42px;display:flex;align-items:center;justify-content:center;border-radius:12px}}
.main{{margin-right:280px;margin-top:60px;padding:12px;min-height:100vh}} @media(max-width:900px){{.main{{margin-right:0;padding:4px}} .dishes-layout{{grid-template-columns:1fr !important}}}}
.card{{background:{card};padding:16px;border-radius:14px;margin-bottom:12px;border:1px solid {COLORS['border_dark']};box-shadow:0 4px 12px {COLORS['black']}22}}
.btn{{background:var(--input);border:none;color:var(--text);padding:8px 14px;border-radius:10px;cursor:pointer;font-weight:bold;font-size:13px}}
.btn-gold{{background:var(--gold);color:{COLORS['black']};padding:10px 18px;border-radius:10px;border:none;font-weight:bold;cursor:pointer}}
.btn-blue{{background:var(--blue);color:{COLORS['white']};padding:8px 14px;border-radius:10px;border:none;cursor:pointer}}
.btn-wa{{background:var(--wa);color:{COLORS['white']};padding:10px 20px;border-radius:24px;text-decoration:none;display:inline-block;font-weight:bold}}
/* 12- مربعات ملونة بزوايا مدورة طرف الكرت */
.btn-icon{{width:38px;height:38px;border-radius:12px;border:none;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;font-size:16px;margin:0 3px;font-weight:bold;box-shadow:0 2px 6px rgba(0,0,0,.2)}}
.btn-icon.edit{{background:#f59e0b;color:#fff;}} /* برتقالي للتعديل */
.btn-icon.del{{background:#ef4444;color:#fff;}} /* احمر للحذف */
input,select{{width:100%;padding:12px;background:var(--input);border:1px solid var(--border);border-radius:10px;color:var(--text);margin:4px 0;font-size:14px}}
.ip-badge{{background:{COLORS['black']};color:var(--gold);padding:5px 12px;border-radius:20px;font-size:12px;font-family:monospace;border:1px solid var(--gold);display:inline-block}}
.actions{{display:flex;gap:6px;align-items:center}}
.modal{{display:none;position:fixed;inset:0;background:{COLORS['black']}88;backdrop-filter:blur(5px);z-index:2000;align-items:center;justify-content:center}} .modal-content{{background:var(--card);padding:20px;border-radius:16px;width:92%;max-width:400px}}
.avatar{{width:38px;height:38px;border-radius:50%;background:var(--gold);display:flex;align-items:center;justify-content:center;font-weight:bold;color:{COLORS['black']}}}
.top-actions{{display:flex;gap:8px}} .top-actions button{{width:38px;height:38px;border-radius:11px;border:none;background:var(--input);color:var(--text);cursor:pointer}}
#toast{{position:fixed;bottom:20px;left:50%;transform:translateX(-50%) translateY(100px);background:{COLORS['card_dark']};color:{COLORS['white']};padding:12px 20px;border-radius:24px;font-size:13px;box-shadow:0 8px 20px rgba(0,0,0,.4);z-index:3000;transition:transform .3s;border:1px solid var(--gold)}} #toast.show{{transform:translateX(-50%) translateY(0)}}
#pullHint{{position:fixed;top:60px;left:50%;transform:translateX(-50%) translateY(-60px);background:var(--gold);color:{COLORS['black']};padding:8px 16px;border-radius:24px;font-size:13px;font-weight:bold;transition:transform .3s;z-index:50}} #pullHint.show{{transform:translateX(-50%) translateY(10px)}}
.log-row{{display:flex;gap:6px;padding:8px;border-bottom:1px solid var(--border);font-size:12px;align-items:center}}
@media(max-width:600px){{*{transition-duration:.15s !important; animation-duration:.15s !important} .card{{padding:12px}} }}
</style></head><body>
<div id=loader-line></div><div id=toast></div><div id=pullHint>↓ اسحب للتحديث</div>
<div class=overlay id=overlay onclick='toggleMenu()'></div>
<div class=sidebar id=sidebar>
<a href="javascript:loadPage('home')" id=nav-home>◉ الرئيسية</a>
<a href="javascript:loadPage('subs')" id=nav-subs>◎ المشتركين</a>
<a href="javascript:loadPage('dishes')" id=nav-dishes>◍ الصحون</a>
<a href="javascript:loadPage('towers')" id=nav-towers>⬙ الأبراج</a>
<a href="javascript:loadPage('ledger')" id=nav-ledger>⬔ الحسابات</a>
<a href="javascript:loadPage('map')" id=nav-map>⬖ الخريطة</a>
<a href="javascript:loadPage('logs')" id=nav-logs>◫ السجل</a>
<a href="javascript:loadPage('notifications')" id=nav-notifications>⬗ الإشعارات</a>
<a href="javascript:loadPage('support')" id=nav-support>⬘ الدعم</a>
<a href="javascript:loadPage('settings')" id=nav-settings>⬙ الإعدادات</a>
<a href=/logout style='color:var(--red);margin-top:16px;border-top:1px solid var(--border)'>⎋ خروج</a>
</div>
<div class=top><div class=menu-btn onclick='toggleMenu()'>☰</div><div style='font-weight:900'>{logo_html()}</div><div class=top-actions><button onclick='toggleTheme()'>◐</button><button onclick='toggleLang()'>🌐</button><button onclick='loadPage(currentPage,true)'>↻</button></div></div>
<div class=main id=main>{c}</div>
<script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>
<script>
const pageCache = JSON.parse(localStorage.getItem('pageCache')||'{{}}');
let currentPage='{v}'; let currentPageNum={{}}; let isLoading=false; window.mapActive=false;
function saveCache(){{try{{localStorage.setItem('pageCache', JSON.stringify(pageCache))}}catch(e){{}}}}
function toggleMenu(){{let s=document.getElementById('sidebar'), o=document.getElementById('overlay');s.classList.toggle('active');o.classList.toggle('active');}}
function showLine(p){{document.getElementById('loader-line').style.width=p+'%';}} function hideLine(){{setTimeout(()=>{{document.getElementById('loader-line').style.width='0'}},250);}}
function showToast(msg){{let t=document.getElementById('toast'); t.textContent=msg; t.classList.add('show'); setTimeout(()=>t.classList.remove('show'), 2500);}}
window.loadPage=async function(v, force=false){{
  if(isLoading) return;
  if(document.getElementById('sidebar').classList.contains('active'))toggleMenu();
  if(currentPage===v && !force && pageCache[v]){{document.getElementById('main').innerHTML=pageCache[v]; bindAjax(); document.getElementById('main').querySelectorAll('script').forEach(s=>{{try{{eval(s.textContent)}}catch(e){{}}}}); isLoading=false; fetch('/api/page?v='+v, {{cache:'no-store'}}).then(r=>r.text()).then(html=>{{pageCache[v]=html; saveCache();}}); return;}}
  currentPage=v; isLoading=true;
  document.querySelectorAll('.sidebar a').forEach(a=>a.classList.remove('active')); let nav=document.getElementById('nav-'+v);if(nav)nav.classList.add('active');
  if(pageCache[v] && !force){{document.getElementById('main').innerHTML=pageCache[v]; bindAjax(); document.getElementById('main').querySelectorAll('script').forEach(s=>{{try{{eval(s.textContent)}}catch(e){{}}}}); isLoading=false; fetch('/api/page?v='+v, {{cache:'no-store'}}).then(r=>r.text()).then(html=>{{pageCache[v]=html; saveCache();}}); return;}}
  showLine(20);
  try{{
    let r=await fetch('/api/page?v='+v, {{cache:'no-store'}});
    if(r.status==401){{location.href='/login';return}}
    let html=await r.text();
    pageCache[v]=html; saveCache();
    document.getElementById('main').innerHTML=html; bindAjax();
    document.getElementById('main').querySelectorAll('script').forEach(s=>{{try{{eval(s.textContent)}}catch(e){{}}}});
  }}catch(e){{
    // 17- وضع عدم الاتصال - عرض اخر بيانات محفوظة
    if(pageCache[v]){{document.getElementById('main').innerHTML=pageCache[v]; showToast('📴 عدم اتصال - عرض بيانات محفوظة');}}
    else{{document.getElementById('main').innerHTML='<div class=card style=text-align:center>📴 لا يوجد اتصال<br><button class=btn-gold onclick=loadPage(currentPage,true)>اعادة محاولة</button></div>';}}
  }}
  showLine(100); hideLine(); isLoading=false; window.scrollTo({{top:0,behavior:'instant'}});
}}
function bindAjax(){{
  document.querySelectorAll('form[data-ajax]').forEach(f=>{{
    f.onsubmit=async e=>{{e.preventDefault();showLine(40);try{{let res=await fetch(f.action,{{method:'POST',body:new FormData(f),cache:'no-store'}});if(res.status==401){{location.href='/login';return}}if(!res.ok){{let t=await res.text();showToast('❌ '+t);showLine(0);return}} Object.keys(pageCache).forEach(k=>delete pageCache[k]); localStorage.removeItem('pageCache'); showToast('✅ تم بنجاح'); loadPage(currentPage, true);}}catch(e){{showToast('❌ '+e);showLine(0)}}}};
  }});
}}
window.delItem=async function(url){{if(!confirm('⚠ تأكيد الحذف؟'))return;showLine(40);try{{let res=await fetch(url,{{cache:'no-store'}});if(res.status==401){{location.href='/login';return}} Object.keys(pageCache).forEach(k=>delete pageCache[k]); localStorage.removeItem('pageCache'); showToast('🗑️ تم الحذف'); loadPage(currentPage, true);}}catch(e){{showToast('❌ '+e)}}}}
function pingDish(ip){{if(!ip){{showToast('لا يوجد IP');return}}showLine(40);fetch('/api/ping?ip='+encodeURIComponent(ip),{{cache:'no-store'}}).then(r=>r.json()).then(j=>{{showLine(0);showToast(j.out.slice(0,200))}}).catch(()=>{{showLine(0); showToast('❌ فشل البينغ')}})}}
async function toggleTheme(){{showLine(30);await fetch('/toggle_theme',{cache:'no-store'});location.reload()}}
async function toggleLang(){{showLine(30);try{{let r=await fetch('/toggle_lang',{{cache:'no-store', method:'POST'}});if(r.ok){{Object.keys(pageCache).forEach(k=>delete pageCache[k]); localStorage.removeItem('pageCache'); location.reload();}}else{{showToast('فشل');showLine(0);}}}}catch(e){{showToast('❌ '+e);showLine(0);}}}}
function liveSearch(q){{q=q.toLowerCase(); document.querySelectorAll('.list-card').forEach(card=>{{let txt=card.getAttribute('data-search')||card.textContent; card.style.display=txt.toLowerCase().includes(q)?'':'none';}});}}
function loadPageWithQ(v,q){{fetch('/api/page?v='+v+'&q='+encodeURIComponent(q),{{cache:'no-store'}}).then(r=>r.text()).then(html=>{{document.getElementById('main').innerHTML=html; pageCache[v]=html; saveCache(); bindAjax(); document.getElementById('main').querySelectorAll('script').forEach(s=>{{try{{eval(s.textContent)}}catch(e){{}}}});}});}}
function loadMore(type){{let n=(currentPageNum[type]||1)+1; currentPageNum[type]=n; fetch('/api/page?v='+type+'&page='+n,{{cache:'no-store'}}).then(r=>r.text()).then(html=>{{let tmp=document.createElement('div'); tmp.innerHTML=html; let newCards=tmp.querySelectorAll('.list-card'); let container=document.getElementById('listContainer'); newCards.forEach(c=>container.appendChild(c)); if(newCards.length==0)showToast('لا يوجد المزيد');}});}}
// 20- مزامنة بالخلفية
setInterval(()=>{{if(currentPage){{fetch('/api/page?v='+currentPage,{{cache:'no-store'}}).then(r=>r.text()).then(html=>{{pageCache[currentPage]=html; saveCache();}});}}}}, 60000);
document.addEventListener('keydown', e=>{{if(e.key==='Escape' && document.getElementById('sidebar').classList.contains('active'))toggleMenu()}});
let startY=0, pulling=false;
document.addEventListener('touchstart', e=>{{if(window.mapActive) return; if(window.scrollY===0){{startY=e.touches[0].clientY; pulling=true;}}}}, {{passive:true}});
document.addEventListener('touchmove', e=>{{if(window.mapActive) return; if(!pulling) return; let diff = e.touches[0].clientY - startY; if(diff>0 && diff<100 && window.scrollY===0){{let hint=document.getElementById('pullHint'); hint.classList.add('show'); hint.textContent = diff>70 ? '↻ اترك للتحديث' : '↓ اسحب للتحديث';}}}}, {{passive:true}});
document.addEventListener('touchend', e=>{{if(window.mapActive) return; let hint = document.getElementById('pullHint'); if(hint.classList.contains('show') && hint.textContent.includes('اترك')){{Object.keys(pageCache).forEach(k=>delete pageCache[k]); localStorage.removeItem('pageCache'); loadPage(currentPage, true);}} hint.classList.remove('show'); pulling=false;}});
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
    return f"""<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>OMAIA ISP - Login</title>
<style>
body{{display:flex;flex-direction:column;align-items:center;justify-content:center;background:{COLORS['bg_dark']};min-height:100vh;margin:0;font-family:'Cairo',sans-serif;padding:20px}}
.box{{background:{COLORS['white']};padding:28px;border-radius:18px;width:92%;max-width:360px;box-shadow:0 20px 40px {COLORS['black']}66}}
input{{width:100%;padding:12px;margin:8px 0;border-radius:12px;border:1px solid #ccc;font-size:14px}}
.login-btn{{width:100%;background:{COLORS['gold']};color:{COLORS['black']};padding:14px;border:0;border-radius:12px;font-weight:900;font-size:16px;cursor:pointer;margin-top:12px}}
.save-row{{display:flex;align-items:center;gap:6px;margin:8px 0;font-size:13px;color:{COLORS['input_dark']}}}
.save-row input{{width:auto;margin:0}}
.support-box{{margin-top:18px;background:{COLORS['card_dark']};padding:16px;border-radius:14px;width:92%;max-width:360px;text-align:center;border:1px solid {COLORS['gold']}33}}
.support-box a{{display:inline-flex;align-items:center;gap:8px;margin:5px;padding:10px 18px;border-radius:24px;text-decoration:none;font-weight:bold;font-size:14px}}
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
<div style='color:{COLORS['white']};font-weight:bold;margin-bottom:4px'>🎧 الدعم الفني</div>
<a href='https://wa.me/905344851045' target=_blank style='background:{COLORS['btn_wa']};color:{COLORS['white']}'>💬 واتساب</a>
<a href='https://instagram.com/af_20_1999' target=_blank style='background:linear-gradient(45deg,#feda75,#fa7e1e,#d62976,#962fbf,#4f5bd5);color:#fff'>📸 @af_20_1999</a>
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
    return jsonify(ok=True,lang=session['lang'])

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
