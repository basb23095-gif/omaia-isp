from flask import Flask, request, redirect, session, jsonify, Response
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, html, ipaddress, json, socket, io, csv, datetime, re
import psycopg2, psycopg2.extras
import sqlite3

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "omia-sec-2026-CHANGE-ME-STRONG")
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(days=30)

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_PG = bool(DATABASE_URL)

def esc(s): 
    return html.escape(str(s or ''), quote=True)

def get_conn():
    if USE_PG:
        return psycopg2.connect(DATABASE_URL, sslmode='require', connect_timeout=2)
    try:
        c = sqlite3.connect("omia.db", check_same_thread=False, timeout=5)
        c.row_factory = sqlite3.Row
        return c
    except:
        c = sqlite3.connect(":memory:", check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c

def qall(q, a=()):
    conn = None
    try:
        conn = get_conn()
        if USE_PG:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(q.replace("?", "%s"), a)
            rs = [dict(r) for r in cur.fetchall()]
            cur.close()
            conn.close()
            return rs
        else:
            rs = [dict(r) for r in conn.execute(q, a).fetchall()]
            conn.close()
            return rs
    except:
        try:
            if conn: conn.close()
        except: pass
        return []

def qone(q, a=()):
    r = qall(q, a)
    return r[0] if r else None

def qexec(q, a=()):
    conn = None
    try:
        conn = get_conn()
        if USE_PG:
            cur = conn.cursor()
            cur.execute(q.replace("?", "%s"), a)
            conn.commit()
            cur.close()
            conn.close()
        else:
            conn.execute(q, a)
            conn.commit()
            conn.close()
        return True
    except Exception as e:
        print(f"[DB err] {e}")
        try:
            if conn: conn.close()
        except: pass
        return False

_dish_cache = {"t": None, "ts": 0}
def get_dish_table():
    import time
    now = time.time()
    if _dish_cache["t"] and now - _dish_cache["ts"] < 120:
        return _dish_cache["t"]
    if not USE_PG:
        return "dish_ips"
    try:
        rows = qall("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name IN ('ips','dish_ips')")
        names = [r.get('table_name') for r in rows]
        tbl = "ips" if 'ips' in names else "dish_ips"
        _dish_cache["t"] = tbl
        _dish_cache["ts"] = now
        return tbl
    except:
        return "dish_ips"

def ensure_column(table, column, coltype_pg, coltype_sqlite=None):
    if coltype_sqlite is None:
        coltype_sqlite = coltype_pg
    if USE_PG:
        qexec(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {coltype_pg}")
    else:
        try:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute(f"PRAGMA table_info({table})")
            cols = [row[1] for row in cur.fetchall()]
            conn.close()
            if column not in cols:
                qexec(f"ALTER TABLE {table} ADD COLUMN {column} {coltype_sqlite}")
        except: pass

def log_action(action, detail=""):
    try:
        phone = session.get('phone','system')
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)", (phone, action, detail, now))
    except: pass

SYRIA_PLACES = [
    # حمص
    ('حمص - المركز','حمص',34.7324,36.7137),
    ('تلكلخ','تلكلخ',34.6721,36.2575),
    ('القصير','القصير',34.5086,36.5756),
    ('الرستن','الرستن',34.9275,36.7358),
    ('تلبيسة','تلبيسة',34.8333,36.7333),
    ('المخرم','المخرم',34.8167,37.0833),
    ('القريتين','القريتين',34.2314,37.2386),
    ('تدمر','تدمر',34.56,38.2672),
    ('الحولة','الحولة',34.8833,36.5667),
    ('شين','حمص',34.7667,36.4167),
    ('حديدة','حمص',34.6,36.55),
    ('الفرقلس','حمص',34.5,37.0),
    # حماة
    ('حماة - المركز','حماة',35.1318,36.7578),
    ('مصياف','مصياف',35.0647,36.34),
    ('السلمية','السلمية',35.011,37.0533),
    ('محردة','محردة',35.2486,36.5789),
    ('السقيلبية','السقيلبية',35.3675,36.3808),
    ('كفرزيتا','حماة',35.3714,36.6125),
    ('مورك','حماة',35.3708,36.6894),
    ('صوران','حماة',35.2917,36.7333),
    ('طيبة الإمام','حماة',35.2617,36.7111),
    ('قمحانة','حماة',35.1717,36.7422),
    ('خطاب','حماة',35.2,36.67),
    ('كفرنبودة','حماة',35.425,36.5022),
    ('اللطامنة','حماة',35.355,36.6194),
    # حلب
    ('حلب','حلب',36.2021,37.1343),
    ('منبج','حلب',36.5281,37.9567),
    ('الباب','حلب',36.3692,37.5145),
    ('عفرين','حلب',36.5114,36.8692),
    ('اعزاز','حلب',36.5868,37.0456),
    ('جرابلس','حلب',36.8219,38.0106),
    ('السفيرة','حلب',35.9714,37.3753),
    ('عين العرب كوباني','حلب',36.8906,38.3556),
    ('نبل','حلب',36.3753,36.9939),
    ('الزهراء','حلب',36.36,36.99),
    # دمشق وريف
    ('دمشق','دمشق',33.5138,36.2765),
    ('دوما','ريف دمشق',33.5724,36.4019),
    ('حرستا','ريف دمشق',33.5833,36.3667),
    ('داريا','ريف دمشق',33.4583,36.2333),
    ('قدسيا','ريف دمشق',33.55,36.2167),
    ('الزبداني','ريف دمشق',33.725,36.0972),
    ('القطيفة','ريف دمشق',33.7417,36.5861),
    ('النبك','ريف دمشق',34.0267,36.7267),
    ('يبرود','ريف دمشق',33.9667,36.65),
    ('التل','ريف دمشق',33.6094,36.3147),
    ('جرمانا','ريف دمشق',33.4872,36.3456),
    ('صحنايا','ريف دمشق',33.4458,36.2222),
    # درعا
    ('درعا','درعا',32.6257,36.1082),
    ('ازرع','درعا',32.8692,36.2517),
    ('الصنمين','درعا',33.0619,36.1917),
    ('جاسم','درعا',32.9872,36.0656),
    ('نوى','درعا',32.8917,36.0367),
    ('بصرى الشام','درعا',32.5186,36.48),
    ('داعل','درعا',32.7517,36.1617),
    ('خربة غزالة','درعا',32.7317,36.2017),
    # السويداء
    ('السويداء','السويداء',32.7094,36.5667),
    ('شهبا','السويداء',32.8542,36.6258),
    ('صلخد','السويداء',32.5,36.45),
    ('القريا','السويداء',32.53,36.58),
    # طرطوس
    ('طرطوس','طرطوس',34.8886,35.8914),
    ('بانياس','طرطوس',35.1828,35.9489),
    ('صافيتا','طرطوس',34.8197,36.1208),
    ('الدريكيش','طرطوس',34.9042,36.1333),
    ('الشيخ بدر','طرطوس',34.95,36.05),
    # اللاذقية
    ('اللاذقية','اللاذقية',35.5406,35.7772),
    ('جبلة','اللاذقية',35.3594,35.9217),
    ('الحفة','اللاذقية',35.5856,36.0353),
    ('القرداحة','اللاذقية',35.4581,36.0611),
    ('كسب','اللاذقية',35.9183,35.9867),
    # إدلب
    ('إدلب','إدلب',35.9306,36.6339),
    ('معرة النعمان','إدلب',35.6433,36.6692),
    ('جسر الشغور','إدلب',35.8136,36.3167),
    ('أريحا','إدلب',35.8156,36.5953),
    ('سراقب','إدلب',35.8636,36.8053),
    ('خان شيخون','إدلب',35.4422,36.6497),
    ('كفرنبل','إدلب',35.6106,36.5633),
    # دير الزور
    ('دير الزور','دير الزور',35.3333,40.15),
    ('الميادين','دير الزور',35.0197,40.4522),
    ('البوكمال','دير الزور',34.45,40.9167),
    # الرقة
    ('الرقة','الرقة',35.9500,39.0167),
    ('الطبقة','الرقة',35.8378,38.5467),
    ('تل أبيض','الرقة',36.6944,38.9542),
    # الحسكة
    ('الحسكة','الحسكة',36.5,40.75),
    ('القامشلي','الحسكة',37.05,41.2167),
    ('المالكية','الحسكة',37.1667,42.1333),
    ('رأس العين','الحسكة',36.85,40.0833),
    # دير عطية و القلمون
    ('دير عطية','ريف دمشق',34.05,36.7667),
    ('قارة','ريف دمشق',34.15,36.74),
    ('معلولا','ريف دمشق',33.8444,36.5489),
    ('صيدنايا','ريف دمشق',33.6947,36.3744),
]

def init():
    if USE_PG:
        tables = [
            "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,username TEXT)",
            "CREATE TABLE IF NOT EXISTS subs(id SERIAL PRIMARY KEY,name TEXT,phone TEXT,note TEXT)",
            "CREATE TABLE IF NOT EXISTS ledger(id SERIAL PRIMARY KEY,name TEXT,amount REAL,note TEXT,currency TEXT)",
            "CREATE TABLE IF NOT EXISTS dish_ips(id SERIAL PRIMARY KEY,ip TEXT,location TEXT,dish_name TEXT)",
            "CREATE TABLE IF NOT EXISTS towers(id SERIAL PRIMARY KEY,name TEXT,area TEXT,lat DOUBLE PRECISION,lng DOUBLE PRECISION)",
            "CREATE TABLE IF NOT EXISTS logs(id SERIAL PRIMARY KEY,user_phone TEXT,action TEXT,detail TEXT,time TEXT)",
            "CREATE TABLE IF NOT EXISTS notifications(id SERIAL PRIMARY KEY,title TEXT,msg TEXT,time TEXT,read INTEGER DEFAULT 0)",
            "CREATE TABLE IF NOT EXISTS ips(id SERIAL PRIMARY KEY, ip TEXT, location TEXT, dish_name TEXT, created_at TIMESTAMP DEFAULT NOW())"
        ]
    else:
        tables = [
            "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,username TEXT)",
            "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,note TEXT)",
            "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,amount REAL,note TEXT,currency TEXT)",
            "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,dish_name TEXT)",
            "CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,area TEXT,lat REAL,lng REAL)",
            "CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,user_phone TEXT,action TEXT,detail TEXT,time TEXT)",
            "CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,msg TEXT,time TEXT,read INTEGER DEFAULT 0)",
            "CREATE TABLE IF NOT EXISTS ips(id INTEGER PRIMARY KEY AUTOINCREMENT, ip TEXT, location TEXT, dish_name TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        ]
    for s in tables:
        qexec(s)

    ensure_column("towers", "area", "TEXT")
    ensure_column("towers", "lat", "DOUBLE PRECISION", "REAL")
    ensure_column("towers", "lng", "DOUBLE PRECISION", "REAL")
    ensure_column("towers", "name", "TEXT")
    ensure_column("users", "username", "TEXT")
    ensure_column("subs", "name", "TEXT")
    ensure_column("logs", "time", "TEXT")
    ensure_column("notifications", "read", "INTEGER", "INTEGER")

    if not qone("SELECT * FROM users WHERE phone=?", ('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",
              ('05344851045', generate_password_hash('admin2024'), 'manager', 'admin'))
    else:
        qexec("UPDATE users SET username='admin' WHERE phone=?", ('05344851045',))

    # إضافة كل مناطق سوريا إذا الجدول فاضي
    cnt = (qone("SELECT COUNT(*) as c FROM towers") or {}).get('c',0)
    if cnt < 20:
        print(f"[INIT] Adding {len(SYRIA_PLACES)} Syria places...")
        for name, area, lat, lng in SYRIA_PLACES:
            if not qone("SELECT * FROM towers WHERE name=?", (name,)):
                qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)", (name, area, lat, lng))
    
    # إضافة سجل ترحيبي و إشعار إذا فاضيين
    if not qone("SELECT * FROM logs LIMIT 1"):
        qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)", ('system','تشغيل النظام','تم تشغيل OMAIA ISP بنجاح', datetime.datetime.now().strftime("%Y-%m-%d %H:%M")))
    if not qone("SELECT * FROM notifications LIMIT 1"):
        qexec("INSERT INTO notifications(title,msg,time,read) VALUES(?,?,?,?)", ('مرحبا بك 👋','تم إصلاح النظام - ping أصبح سريع و الخريطة تبحث بكل سوريا', datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), 0))

init()

def login_required(f):
    @wraps(f)
    def w(*a, **kw):
        if not session.get('phone'):
            return redirect('/login')
        return f(*a, **kw)
    return w

def is_manager():
    u = qone("SELECT * FROM users WHERE phone=?", (session.get('phone') or '',))
    if not u: return False
    return (u.get('role') or '').lower() == 'manager'

def role_required_manager(f):
    @wraps(f)
    def w(*a, **kw):
        if not is_manager(): return "ممنوع", 403
        return f(*a, **kw)
    return w

def is_valid_ip(ip):
    ip = (ip or '').strip()
    if not ip: return False
    try: ipaddress.ip_address(ip); return True
    except: return False

@app.route('/fix_db')
def fix_db_route():
    ensure_column("towers", "area", "TEXT")
    ensure_column("towers", "lat", "DOUBLE PRECISION", "REAL")
    ensure_column("towers", "lng", "DOUBLE PRECISION", "REAL")
    ensure_column("users", "username", "TEXT")
    ensure_column("logs", "time", "TEXT")
    # إعادة إضافة الضيع
    added=0
    for name, area, lat, lng in SYRIA_PLACES:
        if not qone("SELECT * FROM towers WHERE name=?", (name,)):
            qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)", (name, area, lat, lng))
            added+=1
    return jsonify(ok=True, msg=f"تم الإصلاح + إضافة {added} منطقة جديدة ✅")

@app.route('/reset_admin')
def reset_admin():
    qexec("DELETE FROM users WHERE phone=?", ('05344851045',))
    qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",
          ('05344851045', generate_password_hash('admin2024'), 'manager', 'admin'))
    log_action("إعادة ضبط الأدمن","تم")
    return jsonify(ok=True, msg="Admin: admin / admin2024")

@app.route('/ping')
@app.route('/health')
def public_ping():
    return jsonify(ok=True, pg=USE_PG, table=get_dish_table(), time=datetime.datetime.now().isoformat())

@app.route('/api/ping')
@login_required
def api_ping():
    ip = request.args.get('ip', '').strip()
    if not ip: return jsonify(ok=False, out='لا يوجد IP')
    if not is_valid_ip(ip): return jsonify(ok=False, out='IP غير صالح')
    if ip.startswith("192.168.") or ip.startswith("10.") or ip.startswith("172."):
        return jsonify(ok=False, out=f'⚠️ {ip} IP خاص داخلي - لا يمكن فحصه من Render. هذا طبيعي. افحصه من الراوتر المحلي.')
    for port in [80, 443, 8080, 8291, 22, 8728, 8000]:
        s=None
        try:
            s=socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            if s.connect_ex((ip, port))==0:
                s.close()
                log_action("ping ناجح", ip)
                return jsonify(ok=True, out=f'✅ متصل - {ip}:{port} مفتوح', port=port, method='tcp')
            s.close()
        except:
            try:
                if s: s.close()
            except: pass
    log_action("ping فشل", ip)
    return jsonify(ok=False, out=f'❌ {ip} لا يرد')

@app.route('/api/ping_tcp')
@login_required
def api_ping_tcp():
    ip = request.args.get('ip','').strip()
    port_str = request.args.get('port','80').strip()
    try:
        port=int(port_str)
        if not 1<=port<=65535: raise ValueError()
    except: return jsonify(ok=False, out='Port غير صالح')
    if not is_valid_ip(ip): return jsonify(ok=False, out='IP غير صالح')
    s=None
    try:
        s=socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.5)
        r=s.connect_ex((ip,port))
        s.close()
        return jsonify(ok=r==0, out=f'✅ {ip}:{port} مفتوح' if r==0 else f'❌ {ip}:{port} مغلق')
    except Exception as e:
        try:
            if s: s.close()
        except: pass
        return jsonify(ok=False, out=f'❌ {e}')

@app.route('/api/notifications')
@login_required
def api_noti():
    rows = qall("SELECT * FROM notifications ORDER BY id DESC LIMIT 20")
    unread = qone("SELECT COUNT(*) as c FROM notifications WHERE read=0")
    cnt = unread.get('c',0) if unread else 0
    return jsonify(rows=rows, unread=cnt)

@app.route('/api/notifications/read', methods=['POST'])
@login_required
def api_noti_read():
    qexec("UPDATE notifications SET read=1")
    return jsonify(ok=True)

@app.route('/api/add_notification', methods=['POST'])
@login_required
def api_add_noti():
    title=request.form.get('title','تنبيه')[:100]
    msg=request.form.get('msg','')[:500]
    now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    qexec("INSERT INTO notifications(title,msg,time,read) VALUES(?,?,?,0)", (title,msg,now))
    return jsonify(ok=True)

@app.route('/toggle_lang')
@login_required
def toggle_lang_route():
    cur=session.get('lang','ar')
    session['lang']='en' if cur=='ar' else 'ar'
    return jsonify(ok=True, lang=session['lang'])

@app.route('/api/login_public', methods=['POST'])
def api_login_public():
    uin=request.form.get('userin','').strip()
    pw=request.form.get('password','')
    u=qone("SELECT * FROM users WHERE phone=? OR username=?", (uin,uin))
    if u and check_password_hash(u['password'], pw):
        session['phone']=u['phone']
        session['username']=u.get('username') or u['phone']
        session.permanent=True
        log_action("تسجيل دخول", uin)
        return jsonify(ok=True, role=u.get('role'))
    return jsonify(ok=False, msg='خطأ بالدخول'), 401

@app.route('/api/export/<tbl>')
@login_required
def api_export(tbl):
    output=io.StringIO()
    output.write('\ufeff')
    w=csv.writer(output)
    dish_tbl=get_dish_table()
    if tbl=='towers':
        rows=qall("SELECT * FROM towers ORDER BY id DESC")
        w.writerow(['ID','اسم','المنطقة','lat','lng'])
        for r in rows: w.writerow([r.get('id',''),r.get('name',''),r.get('area',''),r.get('lat',''),r.get('lng','')])
        fname='towers.csv'
    elif tbl=='logs':
        rows=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 1000")
        w.writerow(['ID','المستخدم','العملية','التفاصيل','الوقت'])
        for r in rows: w.writerow([r.get('id',''),r.get('user_phone',''),r.get('action',''),r.get('detail',''),r.get('time','')])
        fname='logs.csv'
    else:
        rows=qall(f"SELECT * FROM {dish_tbl} ORDER BY id DESC")
        w.writerow(['ID','اسم الصحن','IP','الموقع'])
        for r in rows: w.writerow([r.get('id',''),r.get('dish_name',''),r.get('ip',''),r.get('location','')])
        fname='dishes.csv'
    return Response(output.getvalue(), mimetype='text/csv; charset=utf-8', headers={'Content-Disposition': f'attachment; filename={fname}'})

@app.route('/')
def ix():
    return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login')
def login():
    return """<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<style>*{box-sizing:border-box;font-family:system-ui}body{margin:0;min-height:100vh;background:radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 55%, #070a1f 100%);display:flex;flex-direction:column;align-items:center;justify-content:center;color:#fff;padding:14px}
.card{background:linear-gradient(180deg, #222b45cc, #1a2035cc);backdrop-filter:blur(16px);border:1px solid #ffffff18;padding:26px;border-radius:22px;width:92%;max-width:400px;box-shadow:0 20px 60px #0008}
input{width:100%;padding:14px;margin:8px 0;background:#0f1424;border:1px solid #ffffff22;color:#fff;border-radius:14px;font-size:15px}
.btn{width:100%;padding:14px;border:0;border-radius:14px;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:900;font-size:17px;cursor:pointer;margin-top:10px}
.support-box{margin-top:18px;background:linear-gradient(135deg,#0f172a,#1e293b);border:1px solid #22c55e33;border-radius:16px;padding:14px;text-align:center;width:92%;max-width:400px}
.wa-btn{display:inline-flex;align-items:center;gap:8px;background:linear-gradient(90deg,#22c55e,#16a34a);color:#fff;padding:10px 18px;border-radius:12px;text-decoration:none;font-weight:800;margin:6px;transition:transform .15s}
.wa-btn:hover{transform:translateY(-1px)}
#loader{position:fixed;inset:0;background:#0a0e2a;z-index:9999;display:flex;flex-direction:column;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:opacity .15s}
#loader.show{opacity:1;pointer-events:auto}
.spinner{width:36px;height:36px;border:3px solid #ffffff18;border-top-color:#ffbe4d;border-radius:50%;animation:spin .6s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}</style></head><body>
<div id=loader><div class=spinner></div><div style='margin-top:10px;color:#ffbe4d;font-weight:800;font-size:13px'>⏳ جاري التحميل...</div></div>
<div style='font-size:30px;font-weight:900;margin-bottom:12px'>OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<div class=card><form id=loginForm><input name=userin id=userin placeholder='📱 رقم / يوزر - admin' required autocomplete=username><input name=password id=password type=password placeholder='🔑 كلمة السر - admin2024' required autocomplete=current-password><label style='display:flex;gap:8px;font-size:13px;color:#aaa;margin:8px 0'><input type=checkbox id=savePass style='width:auto'> حفظ</label><button class=btn id=loginBtn>✨ دخول فوري</button><div id=msg style='text-align:center;margin-top:8px;color:#ff6b6b;font-size:13px'></div></form></div>
<div class=support-box>
<div style='font-weight:800;margin-bottom:8px;color:#ffbe4d'>🛠 الدعم الفني</div>
<div style='font-size:13px;color:#aab4d0;margin-bottom:10px'>للمساعدة تواصل معنا واتساب</div>
<a href='https://wa.me/905344851045' target=_blank class=wa-btn><span style='font-size:18px'>💬</span> واتساب: +90 534 485 10 45</a>
<div style='margin-top:8px'><a href='tel:+905344851045' style='color:#0ea5e9;text-decoration:none;font-size:13px'>📞 اتصال مباشر: +90 534 485 10 45</a></div>
<div style='margin-top:10px;font-size:11px;color:#6b7280'>OMAIA ISP - نظام إدارة الشبكات - سريع ⚡</div>
</div>
<script>
let u=document.getElementById('userin'), p=document.getElementById('password'), s=document.getElementById('savePass');
let su=localStorage.getItem('omaia_user'), sp=localStorage.getItem('omaia_pass');
if(su){u.value=su; if(sp){p.value=sp; s.checked=true;}}
document.getElementById('loginForm').addEventListener('submit',async e=>{
 e.preventDefault(); let btn=document.getElementById('loginBtn'), msg=document.getElementById('msg'), loader=document.getElementById('loader');
 if(btn.disabled) return;
 btn.textContent='⏳...'; btn.disabled=true; loader.classList.add('show');
 try{
  let fd=new FormData(e.target);
  let r=await fetch('/api/login_public',{method:'POST',body:fd,cache:'no-store'});
  let j=await r.json();
  if(j.ok){ if(s.checked){localStorage.setItem('omaia_user',u.value);localStorage.setItem('omaia_pass',p.value);} location.replace('/dash?v=ping'); }
  else{ msg.textContent=j.msg||'خطأ'; btn.textContent='✨ دخول فوري'; btn.disabled=false; loader.classList.remove('show'); }
 }catch(err){ msg.textContent='خطأ شبكة'; btn.textContent='✨ دخول فوري'; btn.disabled=false; loader.classList.remove('show'); }
});
</script></body></html>"""

@app.route('/logout')
def lo():
    session.clear()
    return redirect('/login')

@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify(ok=True)

@app.route('/dash')
@login_required
def dash():
    v=request.args.get('v','home')
    return layout(page_content(v), v)

@app.route('/api/page')
@login_required
def ap():
    v=request.args.get('v','home')
    return page_content(v)

@app.route('/api/search')
@login_required
def s():
    q=request.args.get('q','').strip()
    if not q: return jsonify([])
    like="%"+q+"%"
    results=[]
    dish_tbl=get_dish_table()
    try:
        for r in qall(f"SELECT * FROM {dish_tbl} WHERE ip LIKE ? OR dish_name LIKE ? OR location LIKE ? ORDER BY id DESC LIMIT 10", (like,like,like)):
            results.append({"title": r.get('dish_name') or r.get('ip') or 'صحن', "sub": r.get('ip',''), "page": "dishes", "type": "dish"})
        for r in qall("SELECT * FROM towers WHERE name LIKE ? OR area LIKE ? ORDER BY id DESC LIMIT 15", (like,like)):
            results.append({"title": r.get('name',''), "sub": r.get('area',''), "page": "towers", "type": "tower"})
        for r in qall("SELECT * FROM towers WHERE area LIKE ? LIMIT 15", (like,)):
            results.append({"title": r.get('name',''), "sub": r.get('area',''), "page": "map", "type": "map"})
    except: pass
    return jsonify(results[:20])

@app.route('/toggle_theme')
@login_required
def tt():
    cur=session.get('theme','dark')
    session['theme']='light' if cur=='dark' else 'dark'
    return jsonify(ok=True)

@app.route('/add_dish', methods=['POST'])
@login_required
def ad():
    dish_tbl=get_dish_table()
    ip=request.form.get('ip','').strip()
    name=request.form.get('dish_name','').strip()
    loc=request.form.get('location','').strip()
    if not ip: return "IP مطلوب",400
    if not is_valid_ip(ip): return "IP غير صالح",400
    ex=qone(f"SELECT * FROM {dish_tbl} WHERE ip=?", (ip,))
    if ex:
        qexec(f"UPDATE {dish_tbl} SET dish_name=?,location=? WHERE ip=?", (name,loc,ip))
        log_action("تعديل صحن", f"{name} - {ip}")
        return "ok updated"
    qexec(f"INSERT INTO {dish_tbl}(ip,location,dish_name) VALUES(?,?,?)", (ip,loc,name))
    log_action("إضافة صحن", f"{name} - {ip}")
    qexec("INSERT INTO notifications(title,msg,time,read) VALUES(?,?,?,0)", (f"📡 صحن جديد {name}", f"تمت إضافة {ip} - {loc}", datetime.datetime.now().strftime("%Y-%m-%d %H:%M")))
    return "ok"

@app.route('/del_dish/<int:i>')
@login_required
def dd(i):
    if not is_manager(): return "ممنوع",403
    qexec(f"DELETE FROM {get_dish_table()} WHERE id=?", (i,))
    log_action("حذف صحن", str(i))
    return "ok"

@app.route('/add_tower', methods=['POST'])
@login_required
def at():
    try:
        la=float(request.form.get('lat','') or 35.13)
        ln=float(request.form.get('lng','') or 36.75)
    except: la=35.13; ln=36.75
    name=request.form.get('name','')
    area=request.form.get('area','')
    qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)", (name,area,la,ln))
    log_action("إضافة برج/ضيعة", f"{name} - {area}")
    qexec("INSERT INTO notifications(title,msg,time,read) VALUES(?,?,?,0)", (f"🗼 برج جديد {name}", f"{area} - {la},{ln}", datetime.datetime.now().strftime("%Y-%m-%d %H:%M")))
    return "ok"

@app.route('/del_tower/<int:i>')
@login_required
def dt(i):
    if not is_manager(): return "ممنوع",403
    qexec("DELETE FROM towers WHERE id=?", (i,))
    log_action("حذف برج", str(i))
    return "ok"

@app.route('/edit_tower/<int:i>', methods=['POST'])
@login_required
def et(i):
    if not is_manager(): return "ممنوع",403
    try:
        la=float(request.form.get('lat','') or 35.13)
        ln=float(request.form.get('lng','') or 36.75)
    except: la=35.13; ln=36.75
    qexec("UPDATE towers SET name=?,area=?,lat=?,lng=? WHERE id=?", (request.form.get('name',''), request.form.get('area',''), la, ln, i))
    log_action("تعديل برج", str(i))
    return "ok"

@app.route('/add_sub', methods=['POST'])
@login_required
def asub():
    qexec("INSERT INTO subs(name,phone,note) VALUES(?,?,?)", (request.form.get('name',''), request.form.get('phone',''), request.form.get('note','')))
    log_action("إضافة مشترك", request.form.get('name',''))
    return "ok"

@app.route('/del_sub/<int:i>')
@login_required
def dsub(i):
    if not is_manager(): return "ممنوع",403
    qexec("DELETE FROM subs WHERE id=?", (i,))
    return "ok"

@app.route('/add_user', methods=['POST'])
@login_required
@role_required_manager
def au():
    ph=request.form.get('phone','').strip() or request.form.get('user_field','').strip()
    if not ph: return "رقم مطلوب",400
    if qone("SELECT * FROM users WHERE phone=?", (ph,)): return "موجود",400
    qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)", (ph, generate_password_hash(request.form.get('password','1234')), request.form.get('role','tech'), ph))
    log_action("إضافة يوزر", ph)
    return "ok"

@app.route('/change_pass', methods=['POST'])
@login_required
def cp():
    np=request.form.get('newpass','').strip()
    if not np: return "فارغة",400
    qexec("UPDATE users SET password=? WHERE phone=?", (generate_password_hash(np), session.get('phone')))
    log_action("تغيير كلمة سر","")
    return "ok"

def page_content(v):
    req_lang=request.args.get('lang') or session.get('lang','ar')
    dish_tbl=get_dish_table()
    def L(ar,en): return ar if req_lang=='ar' else en

    if v=='home':
        ns=(qone("SELECT COUNT(*) as c FROM subs") or {}).get('c',0)
        nd=(qone(f"SELECT COUNT(*) as c FROM {dish_tbl}") or {}).get('c',0)
        nt=(qone("SELECT COUNT(*) as c FROM towers") or {}).get('c',0)
        logs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 5")
        log_html="".join([f"<div style='display:flex;justify-content:space-between;padding:6px 8px;border-bottom:1px dashed #ffffff10;font-size:12px'><div><b style='color:#ffbe4d'>{esc(l.get('user_phone',''))}</b> {esc(l.get('action',''))} <small style='color:#aaa'>{esc(l.get('detail',''))}</small></div><small style='color:#666'>{esc(l.get('time',''))}</small></div>" for l in logs])
        return f'''<div style='max-width:900px;margin:0 auto'>
        <div style='display:grid;grid-template-columns:1fr 1fr;gap:10px'>
        <div class='card anim' onclick="loadPage('ping')" style='cursor:pointer;background:linear-gradient(135deg,#1e2a4a,#162040)'><div style='display:flex;justify-content:space-between'><div><h3 style='margin:0;color:#aab4d0;font-size:12px'>ping</h3><h2 style='margin:4px 0 0;font-size:28px'>{nd}</h2></div><div style='font-size:28px'>📶</div></div><small style='color:#22c55e'>⚡ سريع نار</small></div>
        <div class='card anim' onclick="loadPage('towers')" style='cursor:pointer'><h3 style='margin:0'>🗼 {nt} منطقة</h3><small>كل سوريا</small></div>
        <div class='card anim' onclick="loadPage('map')" style='cursor:pointer;background:linear-gradient(135deg,#1e2f4a,#162040)'><h3 style='margin:0'>🗺 الخريطة</h3><small>بحث عالمي</small></div>
        <div class='card anim' onclick="loadPage('logs')" style='cursor:pointer'><h3 style='margin:0'>📜 السجل</h3><small>{len(logs)} عملية</small></div>
        </div>
        <div class=card style='margin-top:10px'><h4>📜 آخر النشاطات - السجل شغال ✅</h4>{log_html or '<div style="color:#888">لا يوجد سجل بعد - سيظهر هنا كل العمليات</div>'}<button class=btn-gold onclick="loadPage('logs')" style='width:100%;margin-top:8px'>عرض كل السجل</button></div>
        <div class=card style='text-align:center;background:linear-gradient(135deg,#0f172a,#1e293b);border:1px solid #22c55e33'><h4>💬 الدعم الفني واتساب</h4><a href='https://wa.me/905344851045' target=_blank style='display:inline-block;background:linear-gradient(90deg,#22c55e,#16a34a);color:#fff;padding:12px 22px;border-radius:12px;text-decoration:none;font-weight:800'>💬 واتساب: +90 534 485 10 45</a></div>
        </div>'''

    if v=='ping':
        return f'''<div style='max-width:800px;margin:0 auto'>
        <div class=card style='background:linear-gradient(135deg,#0f172a,#1e293b);border:1px solid #22c55e33'>
        <h3 style='margin:0'>📶 ping - سريع نار ⚡</h3>
        <p style='color:#9ca3af;font-size:11px;margin:4px 0'>تم إصلاحه - اسمه صار ping فقط - سريع جداً</p>
        <div style='display:flex;gap:6px;margin-top:10px;flex-wrap:wrap'>
        <input id=pingIp placeholder='8.8.8.8 أو IP عام (192.168 ما يشتغل من Render)' style='flex:1;min-width:180px;padding:12px;border-radius:10px;background:#0f1424;border:1px solid #ffffff20;color:#fff;font-family:monospace'>
        <input id=pingPort placeholder='80' value='80' style='width:70px;padding:12px;border-radius:10px;background:#0f1424;border:1px solid #ffffff20;color:#fff'>
        <button class=btn-gold onclick="doSinglePing()" style='padding:12px 18px;background:#22c55e;color:#fff'>ping</button>
        </div>
        <div id=pingResult style='margin-top:10px;min-height:50px;background:#0008;border-radius:10px;padding:12px;font-family:monospace;font-size:12px;white-space:pre-wrap'>جاهز...</div>
        </div>
        <div class=card><h4>⚡ صحون سريعة</h4><div id=quickDishes>⏳...</div></div>
        </div><script>
        async function doSinglePing(){{
        let ip=document.getElementById('pingIp').value.trim(); if(!ip){{alert('اكتب IP');return;}}
        let out=document.getElementById('pingResult'); out.textContent='⏳ فحص '+ip+'...'; out.style.color='#ffbe4d';
        try{{let r=await fetch('/api/ping?ip='+encodeURIComponent(ip),{{cache:'no-store'}}); let j=await r.json(); out.textContent=j.out; out.style.color=j.ok?'#22c55e':'#ef4444';}}catch(e){{out.textContent='❌ '+e;}}
        }}
        (async()=>{{try{{let r=await fetch('/api/search?q=192',{{cache:'no-store'}}); let d=await r.json(); let h=''; d.slice(0,6).forEach(x=>{{h+='<div style="display:flex;justify-content:space-between;padding:6px;border-bottom:1px solid #ffffff08"><span>🌐 '+x.sub+'</span><button class=btn-gold onclick="document.getElementById(\\'pingIp\\').value=\\''+x.sub+'\\'; doSinglePing()" style="padding:4px 8px">ping</button></div>';}}); document.getElementById('quickDishes').innerHTML=h||'لا يوجد';}}catch(e){{}}}})();
        </script>'''

    if v=='towers':
        rs=qall("SELECT * FROM towers ORDER BY area, name")
        rows="".join([f"<div class='card anim' id='tower-{r['id']}' data-name='{esc(r['name'])}' data-area='{esc(r['area'] or '')}' style='display:flex;justify-content:space-between'><div><b>🗼 {esc(r['name'])}</b><br><small>{esc(r['area'] or '')}</small></div><div><button class=btn-del onclick=\"askDel('/del_tower/{r['id']}')\" style='padding:6px 8px'>🗑</button></div></div>" for r in rs])
        return f'''<div style='max-width:700px;margin:0 auto'><div class=card><h3>🗼 كل مناطق وضيع سوريا - {len(rs)} منطقة ✅</h3><form data-ajax method=post action=/add_tower style='display:flex;gap:4px;flex-wrap:wrap'><input name=name placeholder='اسم ضيعة/منطقة جديدة' required style='flex:1'><input name=area placeholder='المحافظة' style='flex:1'><input name=lat placeholder='lat' style='flex:0.5'><input name=lng placeholder='lng' style='flex:0.5'><button class=btn-gold>➕</button></form><input id=towerSearch placeholder='🔍 بحث بكل سوريا...' oninput="searchTowers(this.value)" style='margin-top:8px'></div>{rows}<script>
        function searchTowers(q){{q=(q||'').toLowerCase();document.querySelectorAll('[id^=tower-]').forEach(c=>{{let t=(c.dataset.name+c.dataset.area).toLowerCase();c.style.display=t.includes(q)?'flex':'none';}});}}
        </script></div>'''

    if v=='map':
        towers=qall("SELECT * FROM towers")
        tj_json=json.dumps([{"name":t['name'],"area":t.get('area') or '',"lat":float(t.get('lat') or 35.13),"lng":float(t.get('lng') or 36.75)} for t in towers],ensure_ascii=False)
        return f'''<div class=card style='padding:10px'>
        <div style='display:flex;gap:6px;margin-bottom:10px;flex-wrap:wrap'>
        <input id=mapSearch placeholder='🔍 بحث بأي ضيعة بسوريا - اكتب مثلا: حمص، تلكلخ، حلب، درعا...' style='flex:1;min-width:220px;background:#1f2937;border:1px solid #22c55e33;color:#fff;padding:12px;border-radius:12px'>
        <button class=btn-gold onclick="doMapSearch()" style='padding:12px'>🔍 بحث محلي</button>
        <button class=btn-gold onclick="doGlobalSearch()" style='background:linear-gradient(90deg,#8b5cf6,#7c3aed);color:#fff;padding:12px'>🌍 بحث سوريا و العالم</button>
        <button class=btn-gold onclick="locateMe()" style='background:#22c55e;color:#fff;padding:12px'>📍 موقعي</button>
        <button class=btn-gold onclick="enableAddPoint()" id=addPointBtn style='background:#f59e0b;color:#fff;padding:12px'>➕ إضافة ضيعة</button>
        </div>
        <div id=map style='height:70vh;min-height:450px;border-radius:16px;background:#0f172a;z-index:1'></div>
        <div id=mapResults style='margin-top:8px;max-height:160px;overflow:auto;background:#0f1424;border-radius:10px;padding:6px'></div>
        <div style='margin-top:6px;font-size:11px;color:#6b7280'>💡 البحث صار يبحث بكل سوريا + العالم - اكتب اسم أي ضيعة</div>
        </div><script>
        let _towers={tj_json};
        let _map=null; let addPointMode=false;
        window.doMapSearch=function(){{
          let q=document.getElementById('mapSearch').value.trim().toLowerCase(); if(!q) return;
          let f=_towers.filter(t=>t.name.toLowerCase().includes(q)||t.area.toLowerCase().includes(q));
          let res=document.getElementById('mapResults');
          if(f.length>0){{
            _map.flyTo([f[0].lat,f[0].lng],13);
            let h='<b>🔍 وجد '+f.length+' نتيجة بضيعك:</b><br>';
            f.slice(0,20).forEach(t=>{{h+='<div style="padding:8px;border-bottom:1px solid #ffffff10;cursor:pointer" onclick="_map.flyTo(['+t.lat+','+t.lng+'],15); L.popup().setLatLng(['+t.lat+','+t.lng+']).setContent(\\'<b>'+t.name+'</b>\\').openOn(_map);">🗼 '+t.name+' - '+t.area+'</div>';}});
            res.innerHTML=h;
          }} else {{ res.innerHTML='⏳ لا يوجد محليا، جرب البحث العالمي...'; doGlobalSearch(); }}
        }}
        window.doGlobalSearch=async function(){{
          let q=document.getElementById('mapSearch').value.trim(); if(!q) return;
          let res=document.getElementById('mapResults');
          res.innerHTML='⏳ بحث عالمي عن '+q+' بكل سوريا...';
          try{{
            let r=await fetch('https://nominatim.openstreetmap.org/search?format=json&q='+encodeURIComponent(q+' Syria')+'&limit=8');
            let data=await r.json();
            if(data.length==0){{let r2=await fetch('https://nominatim.openstreetmap.org/search?format=json&q='+encodeURIComponent(q)+'&limit=8'); data=await r2.json();}}
            if(data.length==0){{res.innerHTML='❌ لا يوجد نتائج لـ '+q; return;}}
            let h='<b>🌍 نتائج البحث بكل سوريا والعالم:</b><br>';
            data.forEach(p=>{{h+='<div style="padding:8px;border-bottom:1px solid #ffffff10;cursor:pointer;background:#ffffff05;margin:3px 0;border-radius:8px" onclick="_map.flyTo(['+p.lat+','+p.lon+'],14); L.marker(['+p.lat+','+p.lon+']).addTo(_map).bindPopup(\\''+p.display_name.substring(0,50)+'\\').openPopup();">📍 '+p.display_name.substring(0,80)+'<br><small style=color:#ffbe4d>اضغط للانتقال + حفظ كضيعة جديدة</small></div>';}});
            res.innerHTML=h;
            _map.flyTo([data[0].lat,data[0].lon],12);
          }}catch(e){{res.innerHTML='❌ خطأ: '+e;}}
        }}
        window.locateMe=function(){{if(_map && navigator.geolocation){{navigator.geolocation.getCurrentPosition(p=>{{_map.flyTo([p.coords.latitude,p.coords.longitude],15); L.marker([p.coords.latitude,p.coords.longitude]).addTo(_map).bindPopup('📍 موقعك').openPopup();}});}}}}
        window.enableAddPoint=function(){{addPointMode=!addPointMode; document.getElementById('addPointBtn').textContent=addPointMode?'✅ اضغط على الخريطة لإضافة ضيعة':'➕ إضافة ضيعة'; _map.getContainer().style.cursor=addPointMode?'crosshair':'';}}
        setTimeout(()=>{{
          _map=L.map('map').setView([34.8,38.0],7);
          let osm=L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:19}}).addTo(_map);
          let sat=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',{{maxZoom:19}});
          L.control.layers({{"عادية":osm,"قمر صناعي":sat}}).addTo(_map);
          _towers.forEach(t=>{{L.marker([t.lat,t.lng]).addTo(_map).bindPopup('<b>'+t.name+'</b><br>'+t.area);}});
          _map.on('click',e=>{{
            if(addPointMode){{
              let lat=e.latlng.lat.toFixed(6), lng=e.latlng.lng.toFixed(6);
              L.popup().setLatLng(e.latlng).setContent('<div style="min-width:230px;text-align:right"><b>➕ إضافة ضيعة جديدة</b><br><small style="color:#ffbe4d">'+lat+','+lng+'</small><br><input id="newPointName" placeholder="اسم الضيعة - مثلا: تلدو" style="width:100%;margin:6px 0;padding:10px;border-radius:8px;background:#111827;color:#fff"><input id="newPointArea" placeholder="المحافظة - مثلا: حمص" style="width:100%;margin:4px 0;padding:10px;border-radius:8px;background:#111827;color:#fff"><button onclick="saveNewPoint('+lat+','+lng+')" style="width:100%;background:linear-gradient(90deg,#ffbe4d,#ffb020);border:0;padding:10px;border-radius:10px;font-weight:800;margin-top:6px">💾 حفظ الضيعة</button></div>').openOn(_map);
            }}
          }});
          window.saveNewPoint=function(lat,lng){{
            let name=document.getElementById('newPointName').value.trim()||'ضيعة جديدة';
            let area=document.getElementById('newPointArea').value.trim()||'سوريا';
            fetch('/add_tower',{{method:'POST',body:new URLSearchParams({{name:name,area:area,lat:lat,lng:lng}})}}).then(()=>{{alert('✅ تمت إضافة '+name+' - '+area); _map.closePopup(); addPointMode=false; document.getElementById('addPointBtn').textContent='➕ إضافة ضيعة'; _map.getContainer().style.cursor='';}});
          }};
        }},300);
        document.getElementById('mapSearch').addEventListener('keydown',e=>{{if(e.key==='Enter'){{e.preventDefault(); doMapSearch();}}}});
        </script>'''

    if v=='logs':
        rs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 100")
        rows="".join([f"<div class='card anim' style='font-size:12px;border-right:3px solid #ffbe4d'><div><b style='color:#ffbe4d'>{esc(r.get('user_phone',''))}</b> - {esc(r.get('action',''))}<br><small style='color:#aaa'>{esc(r.get('detail',''))}</small></div><small style='color:#666'>{esc(r.get('time',''))}</small></div>" for r in rs])
        return f"<div style='max-width:900px;margin:0 auto'><div class=card style='display:flex;justify-content:space-between;flex-wrap:wrap'><h3>📜 السجل - شغال ✅ - {len(rs)} عملية</h3><a href='/api/export/logs' class=btn-gold style='text-decoration:none;padding:7px 12px'>📗 Excel</a></div>{rows or '<div class=card>لا يوجد سجل بعد</div>'}</div>"

    if v=='dishes':
        rs=qall(f"SELECT * FROM {get_dish_table()} ORDER BY id DESC LIMIT 100")
        rows_html="".join([f'<div class="card anim" style="display:flex;justify-content:space-between"><div><b>{esc(r.get("dish_name") or "صحن")}</b><br><small style="color:#ffbe4d">{esc(r.get("ip") or "")}</small></div><div><button class=btn-del onclick="askDel(\'/del_dish/{r["id"]}\')" style="padding:6px 8px">🗑</button></div></div>' for r in rs])
        return f'''<div style='max-width:800px;margin:0 auto'><div class=card><h3>📡 الصحون - {len(rs)}</h3><form data-ajax method=post action=/add_dish style='display:flex;gap:6px'><input name=dish_name placeholder='اسم الصحن' required style='flex:1'><input name=ip placeholder='IP' required style='flex:1'><button class=btn-gold>➕</button></form></div>{rows_html}</div>'''

    return "<div class=card>✅ كلشي شغال - ping + خريطة كل سوريا + سجل + إشعارات</div>"

def layout(c, v='home'):
    th=session.get('theme','dark')
    bg='radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 60%, #070a1f 100%)'
    card_bg='#1e2433'
    txt='#ffffff'
    border='#ffffff12'
    cur_user=qone("SELECT * FROM users WHERE phone=?", (session.get('phone') or '',)) or {}
    role=(cur_user.get('role') or 'tech')
    req_lang=session.get('lang','ar')
    def L(ar,en): return ar if req_lang=='ar' else en
    username_display=esc(cur_user.get('username') or cur_user.get('phone') or '')
    return f"""<html dir=rtl lang=ar><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1,maximum-scale=1'>
<link rel=stylesheet href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'>
<style>
*{{box-sizing:border-box;font-family:system-ui}}body{{margin:0;background:{bg};color:{txt};overflow-x:hidden}}
.anim{{animation:fadeUp .15s ease}}@keyframes fadeUp{{from{{opacity:0}}to{{opacity:1}}}}
.top{{position:fixed;top:0;left:0;right:0;height:58px;background:#0f172af2;backdrop-filter:blur(12px);color:#fff;display:flex;align-items:center;justify-content:space-between;padding:0 12px;z-index:1003;border-bottom:1px solid #ffffff12}}
.sidebar{{position:fixed;right:0;top:0;width:275px;height:100%;background:#0f172a;color:#fff;z-index:1002;padding-top:65px;transform:translateX(110%);transition:transform .2s;overflow-y:auto}}
.sidebar.active{{transform:none}}
.sidebar a{{display:flex;align-items:center;gap:10px;padding:11px 13px;margin:4px 9px;color:#cbd5e1;text-decoration:none;border-radius:11px;background:#ffffff06}}
.sidebar a.active{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:800}}
#overlay{{position:fixed;inset:0;background:#0008;z-index:1001;display:none}}#overlay.show{{display:block}}
.main{{margin-top:65px;padding:10px;min-height:90vh}}
.card{{background:{card_bg};padding:12px;border-radius:12px;margin-bottom:8px;border:1px solid {border}}}
input{{padding:11px;margin:3px 0;border-radius:9px;border:1px solid {border};width:100%;background:#ffffff07;color:{txt}}}
.btn-gold{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;padding:7px 12px;border:0;border-radius:9px;font-weight:800;cursor:pointer}}
.btn-del{{background:#ef4444;color:#fff;padding:6px 10px;border:0;border-radius:8px}}
#delModal, #editModal{{position:fixed;inset:0;background:#000a;backdrop-filter:blur(6px);display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:.15s;z-index:2000}}
#delModal.show, #editModal.show{{opacity:1;pointer-events:auto}}
#delBox, #editBox{{background:{card_bg};padding:18px;border-radius:14px;width:92%;max-width:400px}}
.wa-float{{position:fixed;bottom:18px;left:18px;z-index:1500;background:linear-gradient(135deg,#22c55e,#16a34a);color:#fff;width:54px;height:54px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:26px;box-shadow:0 6px 20px #0006;text-decoration:none;transition:transform .15s}}
.wa-float:hover{{transform:scale(1.08)}}
</style></head>
<body>
<div id=overlay onclick="toggleSb(false)"></div>
<div class=sidebar id=sb>
<div style='padding:0 14px 8px;border-bottom:1px solid #ffffff0a'><div style='font-weight:900'>OMAIA <span style='color:#ffbe4d'>ISP</span> <small style='color:#22c55e'>⚡ نار</small></div><small style='color:#64748b'>{username_display}</small></div>
<a href="javascript:loadPage('home')" id=nav-home>🏠 الرئيسية</a>
<a href="javascript:loadPage('ping')" id=nav-ping style='background:#22c55e18;border:1px solid #22c55e33'>📶 ping <span style='background:#22c55e;color:#fff;padding:2px 6px;border-radius:6px;font-size:9px;margin-right:auto'>نار</span></a>
<a href="javascript:loadPage('towers')" id=nav-towers>🗼 كل سوريا - ضيع</a>
<a href="javascript:loadPage('map')" id=nav-map>🗺 خريطة سوريا 🌍</a>
<a href="javascript:loadPage('dishes')" id=nav-dishes>📡 الصحون</a>
<a href="javascript:loadPage('logs')" id=nav-logs>📜 السجل ✅</a>
<a href="javascript:logoutFast()">🚪 خروج</a>
</div>
<div class=top>
<span onclick="toggleSb()" style='font-size:22px;cursor:pointer;padding:5px 9px;background:#ffffff10;border-radius:9px'>☰</span>
<div style='font-weight:900;font-size:14px'>OMAIA <span style='color:#ffbe4d'>ISP</span> <small style='color:#22c55e'>⚡ نار</small></div>
<div style='display:flex;gap:6px;align-items:center'>
<div id=notifBell onclick="toggleNotif()" style='position:relative;cursor:pointer;font-size:18px;padding:5px 8px;background:#ffffff08;border-radius:9px'>🔔<span id=notifCount style='display:none;position:absolute;top:-3px;right:-3px;background:#ef4444;color:#fff;font-size:9px;width:16px;height:16px;border-radius:50%;align-items:center;justify-content:center;font-weight:800'>0</span></div>
<a href='https://wa.me/905344851045' target=_blank style='background:#22c55e;color:#fff;padding:6px 10px;border-radius:9px;text-decoration:none;font-size:14px'>💬</a>
</div>
</div>
<div id=notifPanel style='position:fixed;top:62px;left:10px;max-width:340px;width:90%;background:#1e2433;border:1px solid #ffffff12;border-radius:12px;z-index:2000;display:none;max-height:65vh;overflow:auto'></div>
<div class=main id=mn>{c}</div>
<div id=delModal><div id=delBox><h3 style='text-align:center'>حذف؟</h3><div style='display:flex;gap:6px;margin-top:10px'><button onclick="closeDel()" style='flex:1;padding:8px;border-radius:8px'>لا</button><button id=delYes style='flex:1;padding:8px;border-radius:8px;background:#ef4444;color:#fff;border:0'>نعم</button></div></div></div>
<div id=editModal><div id=editBox><div style='display:flex;justify-content:space-between'><h3 id=editTitle>تعديل</h3><button onclick="closeEditModal()" style='background:#ffffff15;border:0;color:#fff;width:26px;height:26px;border-radius:50%'>✕</button></div><div id=editBody></div></div></div>
<a href='https://wa.me/905344851045' target=_blank class=wa-float title='دعم فني واتساب'>💬</a>
<script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>
<script>
let cur='{v}';
function toggleSb(f){{let sb=document.getElementById('sb'),ov=document.getElementById('overlay'); let o=f!==undefined?f:!sb.classList.contains('active'); sb.classList.toggle('active',o); ov.classList.toggle('show',o);}}
let pageCache={{}};
try{{pageCache=JSON.parse(localStorage.getItem('omaia_nar')||'{{}}');}}catch(e){{}}
function saveCache(){{try{{localStorage.setItem('omaia_nar',JSON.stringify(pageCache));}}catch(e){{}}}}
async function loadPage(v,force=false,push=true){{
  if(push && cur!==v){{try{{history.pushState({{page:v}}, '', '/dash?v='+v);}}catch(e){{}}}}
  cur=v;
  let mn=document.getElementById('mn');
  // عرض فوري نار - بدون انتظار 10 ثواني
  if(!force && pageCache[v]){{
    mn.innerHTML=pageCache[v];
    bind(); execScripts();
    document.querySelectorAll('.sidebar a').forEach(a=>a.classList.remove('active'));
    let nv=document.getElementById('nav-'+v); if(nv) nv.classList.add('active');
    toggleSb(false);
    // تحديث خلفية سريع
    fetch('/api/page?v='+v,{{cache:'no-store'}}).then(r=>r.text()).then(h=>{{pageCache[v]=h; saveCache();}}).catch(()=>{{}});
    return;
  }}
  mn.innerHTML='<div class=card style="text-align:center;padding:20px">⚡ جاري التحميل نار...</div>';
  toggleSb(false);
  try{{
    let r=await fetch('/api/page?v='+v,{{cache:'no-store'}});
    let h=await r.text();
    pageCache[v]=h; saveCache();
    mn.innerHTML=h;
    bind(); execScripts();
    document.querySelectorAll('.sidebar a').forEach(a=>a.classList.remove('active'));
    let nv=document.getElementById('nav-'+v); if(nv) nv.classList.add('active');
  }}catch(e){{mn.innerHTML='<div class=card>❌ '+e+'</div>';}}
}}
function execScripts(){{document.getElementById('mn').querySelectorAll('script').forEach(s=>{{try{{(0,eval)(s.textContent)}}catch(e){{}}}});}}
function bind(){{
  document.querySelectorAll('form[data-ajax]').forEach(f=>{{
    if(f.dataset.bound) return;
    f.dataset.bound='1';
    f.onsubmit=async e=>{{
      e.preventDefault();
      let btn=f.querySelector('button'); if(btn){{btn.textContent='⏳'; btn.disabled=true;}}
      try{{let r=await fetch(f.action,{{method:'POST',body:new FormData(f)}}); if(r.ok){{delete pageCache[cur]; await loadPage(cur,true);}} else {{let t=await r.text(); alert(t); if(btn){{btn.textContent='➕'; btn.disabled=false;}}}}}}catch(err){{alert(err);}}
    }};
  }});
}}
function askDel(u){{window._delUrl=u;document.getElementById('delModal').classList.add('show');}}
function closeDel(){{document.getElementById('delModal').classList.remove('show');}}
window.closeEditModal=function(){{document.getElementById('editModal').classList.remove('show');}}
document.getElementById('delYes').onclick=async()=>{{if(window._delUrl){{await fetch(window._delUrl); delete pageCache[cur]; closeDel(); loadPage(cur,true);}}}};
window.toggleNotif=async function(){{
  let p=document.getElementById('notifPanel');
  p.style.display=p.style.display==='block'?'none':'block';
  if(p.style.display==='block'){{
    try{{let r=await fetch('/api/notifications'); let j=await r.json(); let h='<div style="padding:10px"><div style="display:flex;justify-content:space-between"><b>🔔 '+j.unread+' إشعارات</b><button onclick="readAllNotif()" style="background:#ffbe4d;border:0;padding:4px 8px;border-radius:6px;font-size:11px">مقروء</button></div><hr style="border-color:#ffffff0f;margin:6px 0">'; j.rows.forEach(n=>{{h+='<div style="padding:6px;border-bottom:1px solid #ffffff08"><b style="color:#ffbe4d;font-size:12px">'+n.title+'</b><br><small style="color:#ccc">'+n.msg+'</small><br><small style="color:#666">'+n.time+'</small></div>';}}); h+='</div>'; p.innerHTML=h;}}catch(e){{}}
  }}
}}
window.readAllNotif=async function(){{try{{await fetch('/api/notifications/read',{{method:'POST'}});}}catch(e){{}} document.getElementById('notifCount').style.display='none'; document.getElementById('notifPanel').style.display='none';}}
async function loadNotif(){{try{{let r=await fetch('/api/notifications'); let j=await r.json(); let c=document.getElementById('notifCount'); if(j.unread>0){{c.textContent=j.unread>99?'99+':j.unread; c.style.display='flex';}} else {{c.style.display='none';}}}}catch(e){{}}}}
loadNotif(); setInterval(loadNotif,20000);
window.logoutFast=async function(){{try{{await fetch('/api/logout',{{method:'POST'}});}}catch(e){{}} localStorage.clear(); location.replace('/login');}};
bind(); execScripts();
</script>
</body></html>"""

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)), debug=False, threaded=True)
