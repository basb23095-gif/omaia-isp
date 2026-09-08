from flask import Flask, request, redirect, session, jsonify, Response
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, html, ipaddress, subprocess, json, socket, platform, io, csv, datetime, re
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
        return psycopg2.connect(DATABASE_URL, sslmode='require', connect_timeout=5)
    try:
        c = sqlite3.connect("omia.db", check_same_thread=False, timeout=10)
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
    except Exception as e:
        print(f"[DB qall error] {e} | {q}")
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
        print(f"[DB qexec error] {e} | {q} | {a}")
        try:
            if conn: conn.close()
        except: pass
        return False

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
        except Exception as e:
            print(f"[ensure_column sqlite] {e}")

def get_dish_table():
    if not USE_PG:
        return "dish_ips"
    try:
        rows = qall("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name IN ('ips','dish_ips')")
        names = [r.get('table_name') for r in rows]
        if 'ips' in names:
            return "ips"
        return "dish_ips"
    except:
        return "dish_ips"

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

    print("[MIGRATION] Checking missing columns...")
    ensure_column("towers", "area", "TEXT")
    ensure_column("towers", "lat", "DOUBLE PRECISION", "REAL")
    ensure_column("towers", "lng", "DOUBLE PRECISION", "REAL")
    ensure_column("towers", "name", "TEXT")

    if not qone("SELECT * FROM users WHERE phone=?", ('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",
              ('05344851045', generate_password_hash('admin2024'), 'manager', 'admin'))
    if not qone("SELECT * FROM towers WHERE name=?", ('نقطة حماة الرئيسية',)):
        qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",
              ('نقطة حماة الرئيسية', 'حماة', 35.1318, 36.7578))

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
    if not u:
        return False
    return (u.get('role') or '').lower() == 'manager'

def role_required_manager(f):
    @wraps(f)
    def w(*a, **kw):
        if not is_manager():
            return "ممنوع", 403
        return f(*a, **kw)
    return w

def is_valid_ip(ip):
    ip = (ip or '').strip()
    if not ip:
        return False
    try:
        ipaddress.ip_address(ip)
        return True
    except:
        return False

@app.route('/ping')
@app.route('/health')
def public_ping():
    pg_ok = False
    err = None
    tbl = get_dish_table()
    if USE_PG:
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require', connect_timeout=3)
            conn.close()
            pg_ok = True
        except Exception as e:
            err = str(e)[:300]
    else:
        err = "Using SQLite"
    return jsonify(ok=True, pg=pg_ok, error=err, time=datetime.datetime.now().isoformat(), table=tbl)

@app.route('/fix_db')
def fix_db_route():
    ensure_column("towers", "area", "TEXT")
    ensure_column("towers", "lat", "DOUBLE PRECISION", "REAL")
    ensure_column("towers", "lng", "DOUBLE PRECISION", "REAL")
    ensure_column("towers", "name", "TEXT")
    ensure_column("subs", "name", "TEXT")
    ensure_column("subs", "phone", "TEXT")
    ensure_column("subs", "note", "TEXT")
    ensure_column("dish_ips", "ip", "TEXT")
    ensure_column("dish_ips", "location", "TEXT")
    ensure_column("dish_ips", "dish_name", "TEXT")
    ensure_column("ips", "ip", "TEXT")
    ensure_column("ips", "location", "TEXT")
    ensure_column("ips", "dish_name", "TEXT")
    return jsonify(ok=True, msg="تم إصلاح كل الجداول - towers area")

@app.route('/api/ping')
@login_required
def api_ping():
    ip = request.args.get('ip', '').strip()
    if not ip:
        return jsonify(ok=False, out='لا يوجد IP')
    if not is_valid_ip(ip):
        return jsonify(ok=False, out='IP غير صالح')
    for port in [80, 443, 8080, 8291, 22, 23, 53, 8000, 8728]:
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.9)
            if s.connect_ex((ip, port)) == 0:
                s.close()
                return jsonify(ok=True, out=f'✅ متصل - {ip}:{port} مفتوح', port=port, method='tcp')
            s.close()
        except:
            try:
                if s: s.close()
            except: pass
            continue
    try:
        cmd = ['ping', '-c', '1', '-W', '1', ip] if platform.system().lower() != 'windows' else ['ping', '-n', '1', '-w', '1000', ip]
        out = subprocess.check_output(cmd, timeout=2, stderr=subprocess.STDOUT).decode(errors='ignore')
        ok = 'ttl=' in out.lower() or 'bytes from' in out.lower() or '1 received' in out.lower()
        if ok:
            m = re.search(r'time[=<]\s*(\d+\.?\d*)', out, re.I)
            ms = m.group(1) if m else ''
            return jsonify(ok=True, out=f'✅ متصل {ip} - {ms}ms', ms=ms, method='icmp')
    except:
        pass
    return jsonify(ok=False, out=f'❌ {ip} لا يرد')

@app.route('/api/ping_tcp')
@login_required
def api_ping_tcp():
    ip = request.args.get('ip', '').strip()
    port_str = request.args.get('port', '80').strip()
    try:
        port = int(port_str)
        if not 1 <= port <= 65535:
            raise ValueError()
    except:
        return jsonify(ok=False, out='Port غير صالح')
    if not is_valid_ip(ip):
        return jsonify(ok=False, out='IP غير صالح')
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.5)
        r = s.connect_ex((ip, port))
        s.close()
        return jsonify(ok=r == 0, out=f'✅ {ip}:{port} مفتوح' if r == 0 else f'❌ {ip}:{port} مغلق')
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
    cnt = unread.get('c', 0) if unread else 0
    return jsonify(rows=rows, unread=cnt)

@app.route('/api/notifications/read', methods=['POST'])
@login_required
def api_noti_read():
    qexec("UPDATE notifications SET read=1")
    return jsonify(ok=True)

@app.route('/api/network_status')
@login_required
def api_network():
    tbl = get_dish_table()
    dishes = qall(f"SELECT * FROM {tbl} ORDER BY id DESC")
    towers = qall("SELECT * FROM towers ORDER BY id DESC")
    subs_cnt = (qone("SELECT COUNT(*) as c FROM subs") or {}).get('c', 0)
    return jsonify(dishes=len(dishes), towers=len(towers), subs=subs_cnt)

@app.route('/toggle_lang')
@login_required
def toggle_lang_route():
    cur = session.get('lang', 'ar')
    new = 'en' if cur == 'ar' else 'ar'
    session['lang'] = new
    return jsonify(ok=True, lang=new)

@app.route('/api/login_public', methods=['POST'])
def api_login_public():
    uin = request.form.get('userin', '').strip()
    pw = request.form.get('password', '')
    u = qone("SELECT * FROM users WHERE phone=? OR username=?", (uin, uin))
    if u and check_password_hash(u['password'], pw):
        session['phone'] = u['phone']
        session['username'] = u.get('username') or u['phone']
        session.permanent = True
        return jsonify(ok=True, role=u.get('role'))
    return jsonify(ok=False, msg='خطأ بالدخول'), 401

@app.route('/api/export/<tbl>')
@login_required
def api_export(tbl):
    output = io.StringIO()
    output.write('\ufeff')
    w = csv.writer(output)
    dish_tbl = get_dish_table()
    if tbl == 'dishes':
        rows = qall(f"SELECT * FROM {dish_tbl} ORDER BY id DESC")
        w.writerow(['ID', 'اسم الصحن', 'IP', 'الموقع'])
        for r in rows:
            w.writerow([r.get('id',''), r.get('dish_name',''), r.get('ip',''), r.get('location','')])
        fname = 'dishes.csv'
    elif tbl == 'subs':
        rows = qall("SELECT * FROM subs ORDER BY id DESC")
        w.writerow(['ID', 'الاسم', 'رقم', 'ملاحظة'])
        for r in rows:
            w.writerow([r.get('id',''), r.get('name',''), r.get('phone',''), r.get('note','')])
        fname = 'subs.csv'
    elif tbl == 'users':
        rows = qall("SELECT phone,username,role FROM users ORDER BY phone DESC")
        w.writerow(['يوزر/رقم', 'اسم المستخدم', 'الرتبة'])
        for r in rows:
            w.writerow([r.get('phone',''), r.get('username',''), r.get('role','')])
        fname = 'users.csv'
    elif tbl == 'towers':
        rows = qall("SELECT * FROM towers ORDER BY id DESC")
        w.writerow(['ID', 'اسم البرج', 'المنطقة', 'lat', 'lng'])
        for r in rows:
            w.writerow([r.get('id',''), r.get('name',''), r.get('area',''), r.get('lat',''), r.get('lng','')])
        fname = 'towers.csv'
    elif tbl == 'logs':
        rows = qall("SELECT * FROM logs ORDER BY id DESC LIMIT 1000")
        w.writerow(['ID', 'المستخدم', 'العملية', 'التفاصيل', 'الوقت'])
        for r in rows:
            w.writerow([r.get('id',''), r.get('user_phone',''), r.get('action',''), r.get('detail',''), r.get('time','')])
        fname = 'logs.csv'
    else:
        w.writerow(['ID'])
        fname = 'export.csv'
    return Response(output.getvalue(), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename={fname}'})

@app.route('/')
def ix():
    return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login')
def login():
    return """<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<style>*{box-sizing:border-box;font-family:system-ui}body{margin:0;min-height:100vh;background:radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 55%, #070a1f 100%);display:flex;flex-direction:column;align-items:center;justify-content:center;color:#fff}
.card{background:linear-gradient(180deg, #222b45cc, #1a2035cc);backdrop-filter:blur(16px);border:1px solid #ffffff18;padding:26px;border-radius:22px;width:92%;max-width:380px;box-shadow:0 20px 60px #0008}
input{width:100%;padding:14px;margin:9px 0;background:#0f1424;border:1px solid #ffffff22;color:#fff;border-radius:14px;font-size:15px}
.btn{width:100%;padding:14px;border:0;border-radius:14px;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:900;font-size:17px;cursor:pointer;margin-top:12px}
#loader{position:fixed;inset:0;background:#0a0e2a;z-index:9999;display:flex;flex-direction:column;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:opacity .2s}
#loader.show{opacity:1;pointer-events:auto}
.spinner{width:42px;height:42px;border:4px solid #ffffff18;border-top-color:#ffbe4d;border-radius:50%;animation:spin .7s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}</style></head><body>
<div id=loader><div class=spinner></div><div style='margin-top:12px;color:#ffbe4d;font-weight:800'>⏳ جاري التحميل...</div></div>
<div style='font-size:30px;font-weight:900;margin-bottom:14px'>OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<div class=card><form id=loginForm><input name=userin id=userin placeholder='📱 رقم / يوزر' required><input name=password id=password type=password placeholder='🔑 كلمة السر' required><label style='display:flex;gap:8px;font-size:13px;color:#aaa;margin:8px 0'><input type=checkbox id=savePass style='width:auto'> حفظ</label><button class=btn id=loginBtn>✨ دخول فوري</button><div id=msg style='text-align:center;margin-top:8px;color:#ff6b6b;font-size:13px'></div></form></div>
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
  if(j.ok){ if(s.checked){localStorage.setItem('omaia_user',u.value);localStorage.setItem('omaia_pass',p.value);} location.replace('/dash?v=home'); }
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
    v = request.args.get('v', 'home')
    return layout(page_content(v), v)

@app.route('/api/page')
@login_required
def ap():
    return page_content(request.args.get('v', 'home'))

@app.route('/api/search')
@login_required
def s():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])
    like = "%" + q + "%"
    results = []
    dish_tbl = get_dish_table()
    try:
        for r in qall(f"SELECT * FROM {dish_tbl} WHERE ip LIKE ? OR dish_name LIKE ? OR location LIKE ? ORDER BY id DESC LIMIT 20", (like, like, like)):
            results.append({"title": r.get('dish_name') or r.get('ip') or 'صحن', "sub": r.get('ip',''), "page": "dishes", "type": "dish"})
        for r in qall("SELECT * FROM subs WHERE name LIKE ? OR phone LIKE ? ORDER BY id DESC LIMIT 15", (like, like)):
            results.append({"title": r.get('name',''), "sub": r.get('phone',''), "page": "subs", "type": "sub"})
        for r in qall("SELECT * FROM towers WHERE name LIKE ? OR area LIKE ? ORDER BY id DESC LIMIT 15", (like, like)):
            results.append({"title": r.get('name',''), "sub": r.get('area',''), "page": "towers", "type": "tower"})
        for r in qall("SELECT * FROM users WHERE phone LIKE ? OR username LIKE ? LIMIT 10", (like, like)):
            results.append({"title": r.get('username') or r.get('phone',''), "sub": r.get('phone',''), "page": "settings", "type": "user"})
        for r in qall("SELECT * FROM ledger WHERE name LIKE ? OR note LIKE ? ORDER BY id DESC LIMIT 10", (like, like)):
            results.append({"title": r.get('name',''), "sub": str(r.get('amount','')), "page": "ledger", "type": "ledger"})
    except:
        pass
    return jsonify(results[:25])

@app.route('/toggle_theme')
@login_required
def tt():
    cur = session.get('theme', 'dark')
    session['theme'] = 'light' if cur == 'dark' else 'dark'
    return jsonify(ok=True)

@app.route('/add_dish', methods=['POST'])
@login_required
def ad():
    dish_tbl = get_dish_table()
    ip = request.form.get('ip', '').strip()
    name = request.form.get('dish_name', '').strip()
    loc = request.form.get('location', '').strip()
    if not ip:
        return "IP مطلوب", 400
    if not is_valid_ip(ip):
        return "IP غير صالح", 400
    ex = qone(f"SELECT * FROM {dish_tbl} WHERE ip=?", (ip,))
    if ex:
        qexec(f"UPDATE {dish_tbl} SET dish_name=?,location=? WHERE ip=?", (name, loc, ip))
        return "ok updated"
    qexec(f"INSERT INTO {dish_tbl}(ip,location,dish_name) VALUES(?,?,?)", (ip, loc, name))
    return "ok"

@app.route('/edit_dish/<int:i>', methods=['POST'])
@login_required
def ed(i):
    if not is_manager():
        return "ممنوع للفني", 403
    dish_tbl = get_dish_table()
    qexec(f"UPDATE {dish_tbl} SET dish_name=?,ip=?,location=? WHERE id=?",
          (request.form.get('dish_name',''), request.form.get('ip',''), request.form.get('location',''), i))
    return "ok"

@app.route('/del_dish/<int:i>')
@login_required
def dd(i):
    if not is_manager():
        return "ممنوع للفني", 403
    dish_tbl = get_dish_table()
    qexec(f"DELETE FROM {dish_tbl} WHERE id=?", (i,))
    return "ok"

@app.route('/add_tower', methods=['POST'])
@login_required
def at():
    lat = request.form.get('lat','').strip()
    lng = request.form.get('lng','').strip()
    try:
        la = float(lat) if lat else 35.1312
        ln = float(lng) if lng else 36.7578
    except:
        la = 35.1312; ln = 36.7578
    qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",
          (request.form.get('name',''), request.form.get('area',''), la, ln))
    return "ok"

@app.route('/del_tower/<int:i>')
@login_required
def dt(i):
    if not is_manager():
        return "ممنوع للفني", 403
    qexec("DELETE FROM towers WHERE id=?", (i,))
    return "ok"

@app.route('/edit_tower/<int:i>', methods=['POST'])
@login_required
def et(i):
    if not is_manager():
        return "ممنوع للفني", 403
    lat = request.form.get('lat','').strip()
    lng = request.form.get('lng','').strip()
    try:
        la = float(lat) if lat else 35.1318
        ln = float(lng) if lng else 36.7578
    except:
        la = 35.1318; ln = 36.7578
    qexec("UPDATE towers SET name=?,area=?,lat=?,lng=? WHERE id=?",
          (request.form.get('name',''), request.form.get('area',''), la, ln, i))
    return "ok"

@app.route('/add_sub', methods=['POST'])
@login_required
def asub():
    qexec("INSERT INTO subs(name,phone,note) VALUES(?,?,?)",
          (request.form.get('name',''), request.form.get('phone',''), request.form.get('note','')))
    return "ok"

@app.route('/del_sub/<int:i>')
@login_required
def dsub(i):
    if not is_manager():
        return "ممنوع للفني", 403
    qexec("DELETE FROM subs WHERE id=?", (i,))
    return "ok"

@app.route('/edit_sub/<int:i>', methods=['POST'])
@login_required
def esub(i):
    if not is_manager():
        return "ممنوع للفني", 403
    qexec("UPDATE subs SET name=?,phone=?,note=? WHERE id=?",
          (request.form.get('name',''), request.form.get('phone',''), request.form.get('note',''), i))
    return "ok"

@app.route('/add_ledger', methods=['POST'])
@login_required
def al():
    try:
        amt = float(request.form.get('amount') or 0)
    except:
        amt = 0
    qexec("INSERT INTO ledger(name,amount,note,currency) VALUES(?,?,?,?)",
          (request.form.get('name',''), amt, request.form.get('note',''), request.form.get('currency','USD')))
    return "ok"

@app.route('/del_ledger/<int:i>')
@login_required
def dll(i):
    if not is_manager():
        return "ممنوع للفني", 403
    qexec("DELETE FROM ledger WHERE id=?", (i,))
    return "ok"

@app.route('/edit_ledger/<int:i>', methods=['POST'])
@login_required
def el(i):
    if not is_manager():
        return "ممنوع للفني", 403
    try:
        amt = float(request.form.get('amount') or 0)
    except:
        amt = 0
    qexec("UPDATE ledger SET name=?,amount=?,note=?,currency=? WHERE id=?",
          (request.form.get('name',''), amt, request.form.get('note',''), request.form.get('currency','USD'), i))
    return "ok"

@app.route('/add_user', methods=['POST'])
@login_required
@role_required_manager
def au():
    ph = request.form.get('phone','').strip() or request.form.get('user_field','').strip()
    if not ph:
        return "رقم مطلوب", 400
    if qone("SELECT * FROM users WHERE phone=?", (ph,)):
        return "موجود مسبقاً", 400
    qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",
          (ph, generate_password_hash(request.form.get('password','1234')), request.form.get('role','tech'), ph))
    return "ok"

@app.route('/edit_user', methods=['POST'])
@login_required
@role_required_manager
def eu():
    old = request.form.get('old_phone','').strip()
    new_ph = request.form.get('phone','').strip() or request.form.get('user_field','').strip()
    new_role = request.form.get('role','tech')
    new_pass = request.form.get('password','').strip()
    if not old:
        return "خطأ", 400
    if old != new_ph and qone("SELECT * FROM users WHERE phone=?", (new_ph,)):
        return "الرقم الجديد موجود", 400
    if new_pass:
        qexec("UPDATE users SET phone=?,username=?,role=?,password=? WHERE phone=?",
              (new_ph, new_ph, new_role, generate_password_hash(new_pass), old))
    else:
        qexec("UPDATE users SET phone=?,username=?,role=? WHERE phone=?",
              (new_ph, new_ph, new_role, old))
    if session.get('phone') == old:
        session['phone'] = new_ph
    return "ok"

@app.route('/del_user/<ph>')
@login_required
@role_required_manager
def du(ph):
    if ph == '05344851045':
        return "ممنوع حذف المدير", 400
    qexec("DELETE FROM users WHERE phone=?", (ph,))
    return "ok"

@app.route('/change_pass', methods=['POST'])
@login_required
def cp():
    np = request.form.get('newpass','').strip()
    if not np:
        return "فارغة", 400
    qexec("UPDATE users SET password=? WHERE phone=?",
          (generate_password_hash(np), session.get('phone')))
    return "ok"

def page_content(v):
    req_lang = request.args.get('lang') or session.get('lang','ar')
    dish_tbl = get_dish_table()
    def L(ar,en): return ar if req_lang=='ar' else en
    if v=='home':
        ns=(qone("SELECT COUNT(*) as c FROM subs") or {}).get('c',0)
        nd=(qone(f"SELECT COUNT(*) as c FROM {dish_tbl}") or {}).get('c',0)
        nt=(qone("SELECT COUNT(*) as c FROM towers") or {}).get('c',0)
        nl=(qone("SELECT COUNT(*) as c FROM ledger") or {}).get('c',0)
        return f'''<div style='max-width:900px;margin:0 auto'><div style='display:grid;grid-template-columns:1fr 1fr;gap:14px'>
        <div class='card anim'><h3>👥 {ns}</h3></div>
        <div class='card anim'><h3>📡 {nd} - {dish_tbl}</h3></div>
        <div class='card anim'><h3>🗼 {nt}</h3></div>
        <div class='card anim'><h3>📒 {nl}</h3></div></div></div>'''
    if v=='towers':
        rs=qall("SELECT * FROM towers ORDER BY id DESC")
        rows=""
        for r in rs:
            rows+=f"<div class='card anim'><b>🗼 {esc(r['name'])}</b> - {esc(r['area'] or '')} - {r.get('lat')} , {r.get('lng')}</div>"
        return f'''<div style='max-width:700px;margin:0 auto'><div class=card><h3>🗼 {L('الأبراج','Towers')}</h3><form data-ajax method=post action=/add_tower style='display:flex;gap:6px'><input name=name placeholder='اسم' required><input name=area placeholder='منطقة'><input name=lat placeholder='lat'><input name=lng placeholder='lng'><button class=btn-gold>➕</button></form></div>{rows}</div>'''
    return "<div class=card>تم الإصلاح - افتح towers</div>"

def layout(c, v='home'):
    th = session.get('theme', 'dark')
    bg = '#0a0e2a'
    card_bg = '#1e2433'
    txt = '#ffffff'
    border = '#ffffff12'
    cur_user = qone("SELECT * FROM users WHERE phone=?", (session.get('phone') or '',)) or {}
    role = (cur_user.get('role') or 'tech')
    username_display = esc(cur_user.get('username') or cur_user.get('phone') or '')
    return f"""<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<style>body{{background:{bg};color:{txt}}} .card{{background:{card_bg};padding:15px;border-radius:15px;margin-bottom:11px;border:1px solid {border}}}</style></head><body><div style='padding:20px'>{c}<br><a href='/fix_db' style='background:#22c55e;color:#fff;padding:10px 14px;border-radius:10px;text-decoration:none'>🔧 إصلاح DB الآن - اضغط هنا</a></div></body></html>"""

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)), debug=False)
