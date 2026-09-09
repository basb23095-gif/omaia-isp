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
if DATABASE_URL.startswith("postgres://"):
    pass
USE_PG = bool(DATABASE_URL)

# --- تصليح البطء: connection ثابت ---
_pg_conn = None
def get_conn():
    global _pg_conn
    if USE_PG:
        if _pg_conn:
            try:
                cur = _pg_conn.cursor()
                cur.execute("SELECT 1")
                cur.close()
                return _pg_conn
            except:
                try: _pg_conn.close()
                except: pass
                _pg_conn = None
        _pg_conn = psycopg2.connect(DATABASE_URL, sslmode='require', connect_timeout=3)
        _pg_conn.autocommit = True
        return _pg_conn
    try:
        c = sqlite3.connect("omia.db", check_same_thread=False, timeout=10)
        c.row_factory = sqlite3.Row
        return c
    except:
        c = sqlite3.connect(":memory:", check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c

def esc(s):
    return html.escape(str(s or ''), quote=True)

def qall(q, a=()):
    conn = None
    try:
        conn = get_conn()
        if USE_PG:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(q.replace("?", "%s"), a)
            rs = [dict(r) for r in cur.fetchall()]
            cur.close()
            return rs
        else:
            rs = [dict(r) for r in conn.execute(q, a).fetchall()]
            conn.close()
            return rs
    except Exception as e:
        print(f"[DB qall error] {e} | {q}")
        try:
            if conn and not USE_PG: conn.close()
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
            cur.close()
        else:
            conn.execute(q, a)
            conn.commit()
            conn.close()
        return True
    except Exception as e:
        print(f"[DB qexec error] {e} | {q} | {a}")
        try:
            if conn and not USE_PG: conn.close()
        except: pass
        return False

def add_log(action, detail=""):
    try:
        ph = session.get('phone','')
        tm = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)",(ph,action,detail,tm))
    except: pass

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
        return len(ip)>=7 and '.' in ip

@app.route('/ping')
@app.route('/health')
def public_ping():
    pg_ok = False
    err = None
    tbl = get_dish_table()
    if USE_PG:
        try:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
            pg_ok = True
        except Exception as e:
            err = str(e)[:300]
    else:
        err = "Using SQLite"
    return jsonify(ok=True, pg=pg_ok, error=err, time=datetime.datetime.now().isoformat(), table=tbl)

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
        cmd = ['ping', '-c', '1', '-W', '1', ip] if platform.system().lower()!= 'windows' else ['ping', '-n', '1', '-w', '1000', ip]
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
        add_log("دخول", uin)
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
.btn{width:100%;padding:14px;border:0;border-radius:14px;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:900;font-size:17px;cursor:pointer;margin-top:12px;transition:all.15s}
.btn:active{transform:scale(0.97)}
#loader{position:fixed;inset:0;background:#0a0e2a;z-index:9999;display:flex;flex-direction:column;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:opacity.2s}
#loader.show{opacity:1;pointer-events:auto}
.spinner{width:42px;height:42px;border:4px solid #ffffff18;border-top-color:#ffbe4d;border-radius:50%;animation:spin.7s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}</style></head><body>
<div id=loader><div class=spinner></div><div style='margin-top:12px;color:#ffbe4d;font-weight:800'>⏳ جاري التحميل...</div></div>
<div style='font-size:30px;font-weight:900;margin-bottom:14px'>OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<div class=card><form id=loginForm><input name=userin id=userin placeholder='📱 رقم / يوزر' required autocomplete=username><input name=password id=password type=password placeholder='🔑 كلمة السر' required autocomplete=current-password><label style='display:flex;gap:8px;font-size:13px;color:#aaa;margin:8px 0'><input type=checkbox id=savePass style='width:auto'> حفظ</label><button class=btn id=loginBtn>✨ دخول فوري</button><div id=msg style='text-align:center;margin-top:8px;color:#ff6b6b;font-size:13px'></div></form></div>
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
        for r in qall(f"SELECT * FROM {dish_tbl} WHERE ip LIKE? OR dish_name LIKE? OR location LIKE? ORDER BY id DESC LIMIT 20", (like, like, like)):
            results.append({"title": r.get('dish_name') or r.get('ip') or 'صحن', "sub": r.get('ip',''), "page": "dishes", "type": "dish"})
        for r in qall("SELECT * FROM subs WHERE name LIKE? OR phone LIKE? ORDER BY id DESC LIMIT 15", (like, like)):
            results.append({"title": r.get('name',''), "sub": r.get('phone',''), "page": "subs", "type": "sub"})
        for r in qall("SELECT * FROM towers WHERE name LIKE? OR area LIKE? ORDER BY id DESC LIMIT 15", (like, like)):
            results.append({"title": r.get('name',''), "sub": r.get('area',''), "page": "towers", "type": "tower"})
        for r in qall("SELECT * FROM users WHERE phone LIKE? OR username LIKE? LIMIT 10", (like, like)):
            results.append({"title": r.get('username') or r.get('phone',''), "sub": r.get('phone',''), "page": "settings", "type": "user"})
        for r in qall("SELECT * FROM ledger WHERE name LIKE? OR note LIKE? ORDER BY id DESC LIMIT 10", (like, like)):
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
        other = "dish_ips" if dish_tbl == "ips" else "ips"
        try: qexec(f"UPDATE {other} SET dish_name=?,location=? WHERE ip=?", (name, loc, ip))
        except: pass
        add_log("تعديل صحن", f"{name} {ip}")
        return "ok updated"
    qexec(f"INSERT INTO {dish_tbl}(ip,location,dish_name) VALUES(?,?,?)", (ip, loc, name))
    other = "dish_ips" if dish_tbl == "ips" else "ips"
    try: qexec(f"INSERT INTO {other}(ip,location,dish_name) VALUES(?,?,?)", (ip, loc, name))
    except: pass
    add_log("اضافة صحن", f"{name} {ip}")
    return "ok"

@app.route('/edit_dish/<int:i>', methods=['POST'])
@login_required
def ed(i):
    if not is_manager():
        return "ممنوع للفني", 403
    dish_tbl = get_dish_table()
    qexec(f"UPDATE {dish_tbl} SET dish_name=?,ip=?,location=? WHERE id=?",
          (request.form.get('dish_name',''), request.form.get('ip',''), request.form.get('location',''), i))
    add_log("تعديل صحن", str(i))
    return "ok"

@app.route('/del_dish/<int:i>')
@login_required
def dd(i):
    if not is_manager():
        return "ممنوع للفني", 403
    dish_tbl = get_dish_table()
    qexec(f"DELETE FROM {dish_tbl} WHERE id=?", (i,))
    add_log("حذف صحن", str(i))
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
    add_log("اضافة برج", request.form.get('name',''))
    return "ok"

@app.route('/del_tower/<int:i>')
@login_required
def dt(i):
    if not is_manager():
        return "ممنوع للفني", 403
    qexec("DELETE FROM towers WHERE id=?", (i,))
    add_log("حذف برج", str(i))
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
    add_log("تعديل برج", str(i))
    return "ok"

@app.route('/add_sub', methods=['POST'])
@login_required
def asub():
    qexec("INSERT INTO subs(name,phone,note) VALUES(?,?,?)",
          (request.form.get('name',''), request.form.get('phone',''), request.form.get('note','')))
    add_log("اضافة مشترك", request.form.get('name',''))
    return "ok"

@app.route('/del_sub/<int:i>')
@login_required
def dsub(i):
    if not is_manager():
        return "ممنوع للفني", 403
    qexec("DELETE FROM subs WHERE id=?", (i,))
    add_log("حذف مشترك", str(i))
    return "ok"

@app.route('/edit_sub/<int:i>', methods=['POST'])
@login_required
def esub(i):
    if not is_manager():
        return "ممنوع للفني", 403
    qexec("UPDATE subs SET name=?,phone=?,note=? WHERE id=?",
          (request.form.get('name',''), request.form.get('phone',''), request.form.get('note',''), i))
    add_log("تعديل مشترك", str(i))
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
    add_log("اضافة حساب", request.form.get('name',''))
    return "ok"

@app.route('/del_ledger/<int:i>')
@login_required
def dll(i):
    if not is_manager():
        return "ممنوع للفني", 403
    qexec("DELETE FROM ledger WHERE id=?", (i,))
    add_log("حذف حساب", str(i))
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
    add_log("تعديل حساب", str(i))
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
    add_log("اضافة يوزر", ph)
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
    if old!= new_ph and qone("SELECT * FROM users WHERE phone=?", (new_ph,)):
        return "الرقم الجديد موجود", 400
    if new_pass:
        qexec("UPDATE users SET phone=?,username=?,role=?,password=? WHERE phone=?",
              (new_ph, new_ph, new_role, generate_password_hash(new_pass), old))
    else:
        qexec("UPDATE users SET phone=?,username=?,role=? WHERE phone=?",
              (new_ph, new_ph, new_role, old))
    if session.get('phone') == old:
        session['phone'] = new_ph
    add_log("تعديل يوزر", new_ph)
    return "ok"

@app.route('/del_user/<ph>')
@login_required
@role_required_manager
def du(ph):
    if ph == '05344851045':
        return "ممنوع حذف المدير", 400
    qexec("DELETE FROM users WHERE phone=?", (ph,))
    add_log("حذف يوزر", ph)
    return "ok"

@app.route('/change_pass', methods=['POST'])
@login_required
def cp():
    np = request.form.get('newpass','').strip()
    if not np:
        return "فارغة", 400
    qexec("UPDATE users SET password=? WHERE phone=?",
          (generate_password_hash(np), session.get('phone')))
    add_log("تغيير باسورد", "")
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
        logs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 4")
        log_html="".join([f"<div style='display:flex;justify-content:space-between;padding:7px 10px;border-bottom:1px dashed #ffffff10'><div><b style='color:#ffbe4d'>{esc(l.get('user_phone',''))}</b> {esc(l.get('action',''))}</div><small style='color:#777'>{esc(l.get('time',''))}</small></div>" for l in logs])
        return f'''<div style='max-width:900px;margin:0 auto'><div style='display:grid;grid-template-columns:1fr 1fr;gap:14px'>
        <div class='card anim' onclick="loadPage('subs')" style='cursor:pointer;background:linear-gradient(135deg,#1e2a4a 0%,#162040 100%)'><div style='display:flex;justify-content:space-between'><div><h3 style='margin:0;color:#aab4d0;font-size:13px'>{L('المشتركين','Subs')}</h3><h2 style='margin:6px 0 0;font-size:36px'>{ns}</h2></div><div style='font-size:36px'>👥</div></div></div>
        <div class='card anim' onclick="loadPage('dishes')" style='cursor:pointer;background:linear-gradient(135deg,#1e2f4a 0%,#162840 100%)'><div style='display:flex;justify-content:space-between'><div><h3 style='margin:0;color:#aab4d0;font-size:13px'>{L('الصحون','Dishes')}</h3><h2 style='margin:6px 0 0;font-size:36px'>{nd}</h2><small style='color:#22c55e'>☁ {dish_tbl}</small></div><div style='font-size:36px'>📡</div></div></div>
        <div class='card anim' onclick="loadPage('towers')" style='cursor:pointer;background:linear-gradient(135deg,#2a1e4a 0%,#201640 100%)'><div style='display:flex;justify-content:space-between'><div><h3 style='margin:0;color:#aab4d0;font-size:13px'>{L('الأبراج','Towers')}</h3><h2 style='margin:6px 0 0;font-size:36px'>{nt}</h2></div><div style='font-size:36px'>🗼</div></div></div>
        <div class='card anim' onclick="loadPage('ledger')" style='cursor:pointer;background:linear-gradient(135deg,#4a2a1e 0%,#402016 100%)'><div style='display:flex;justify-content:space-between'><div><h3 style='margin:0;color:#aab4d0;font-size:13px'>{L('الحسابات','Accounts')}</h3><h2 style='margin:6px 0 0;font-size:36px'>{nl}</h2></div><div style='font-size:36px'>📒</div></div></div></div>
        <div class=card style='margin-top:14px'><div style='display:flex;justify-content:space-between;flex-wrap:wrap'><h4>📊 {L('التقارير','Reports')} - <small style='color:#22c55e'>☁ Supabase: {dish_tbl}</small></h4><div style='display:flex;gap:8px'><a href='/api/export/dishes' class=btn-gold style='text-decoration:none;padding:8px 12px;background:linear-gradient(90deg,#22c55e,#16a34a);color:#fff'>📗 Excel</a><a href='/api/export/logs' class=btn-gold style='text-decoration:none;padding:8px 12px;background:linear-gradient(90deg,#8b5cf6,#7c3aed);color:#fff'>📜 Excel</a></div></div></div>
        <div class=card><h4>📜 {L('آخر النشاطات','Recent')}</h4>{log_html or 'لا يوجد'}<button class=btn-gold onclick="loadPage('logs')" style='width:100%;margin-top:8px'>عرض السجل</button></div></div>'''
    if v=='ping':
        return f'''<div style='max-width:800px;margin:0 auto'>
        <div class=card style='background:linear-gradient(135deg,#0f172a,#1e293b);border:1px solid #22c55e33'>
        <h3 style='margin:0'>📶 {L('بنج منفصل','Separate Ping')} 🔥 FIXED</h3>
        <p style='color:#9ca3af;font-size:12px;margin:6px 0'>✅ TCP أولا (شغال على Render) - {dish_tbl} ☁</p>
        <div style='display:flex;gap:8px;margin-top:12px;flex-wrap:wrap'>
        <input id=pingIp placeholder='192.168.1.1' style='flex:1;min-width:160px;padding:14px;border-radius:12px;background:#0f1424;border:1px solid #ffffff20;color:#fff;font-family:monospace'>
        <input id=pingPort placeholder='Port' value='80' style='width:80px;padding:14px;border-radius:12px;background:#0f1424;border:1px solid #ffffff20;color:#fff'>
        <button class=btn-gold onclick="window.doSinglePing()" style='padding:14px 20px;background:linear-gradient(90deg,#22c55e,#16a34a);color:#fff'>📶 Ping</button>
        <button class=btn-gold onclick="window.doTcpPing()" style='padding:14px 16px;background:linear-gradient(90deg,#0ea5e9,#0284c7);color:#fff'>TCP</button>
        </div>
        <div id=pingResult style='margin-top:14px;min-height:60px;background:#0008;border:1px solid #ffffff0a;border-radius:12px;padding:14px;font-family:monospace;font-size:13px;white-space:pre-wrap'>جاهز...</div>
        <div style='display:flex;gap:8px;margin-top:10px'><button class=btn-gold onclick="window.pingAllDishes()" style='flex:1;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111'>🚀 {L('فحص كل الصحون','Check All')}</button><button class=btn-gold onclick="window.clearPing()" style='background:#ffffff10;color:#fff'>🗑</button></div>
        </div>
        <div class=card><h4>⚡ {L('صحون سريعة','Quick')} - <small style='color:#22c55e'>{dish_tbl}</small></h4><div id=quickDishes>⏳...</div></div>
        <div class=card><h4>📜 {L('سجل البنج','Ping Log')}</h4><div id=pingLog style='max-height:200px;overflow:auto;font-size:12px'></div></div>
        </div><script>
        window.doSinglePing=async function(){{
        let ip=document.getElementById('pingIp').value.trim(); if(!ip){{alert('اكتب IP');return;}}
        let out=document.getElementById('pingResult'); out.textContent='⏳ فحص '+ip+'...'; out.style.color='#ffbe4d';
        try{{let r=await fetch('/api/ping?ip='+encodeURIComponent(ip),{{cache:'no-store'}}); let j=await r.json(); out.textContent=j.out + (j.method? ' ['+j.method+']' : ''); out.style.color=j.ok?'#22c55e':'#ef4444'; window.addLog(ip,j.ok?'✅':'❌',j.out.slice(0,60));}}catch(e){{out.textContent='❌ '+e;}}
        }}
        window.doTcpPing=async function(){{
        let ip=document.getElementById('pingIp').value.trim(); let port=document.getElementById('pingPort').value.trim()||'80'; if(!ip){{alert('IP');return;}}
        let out=document.getElementById('pingResult'); out.textContent='⏳ '+ip+':'+port+'...';
        try{{let r=await fetch('/api/ping_tcp?ip='+encodeURIComponent(ip)+'&port='+port); let j=await r.json(); out.textContent=j.out; out.style.color=j.ok?'#22c55e':'#ef4444';}}catch(e){{out.textContent='خطأ';}}
        }}
        window.clearPing=function(){{document.getElementById('pingResult').textContent='جاهز...';}}
        window.addLog=function(ip,status,msg){{let l=document.getElementById('pingLog'); let d=new Date().toLocaleTimeString(); l.innerHTML='<div style="padding:6px 8px;border-bottom:1px solid #ffffff08"><span>'+status+' '+ip+' - '+msg.slice(0,50)+'</span><small style="color:#666">'+d+'</small></div>'+l.innerHTML;}}
        window.pingAllDishes=async function(){{
        let out=document.getElementById('pingResult'); out.textContent='🚀 فحص...';
        try{{let r=await fetch('/api/search?q=192',{{cache:'no-store'}}); let d=await r.json(); out.textContent=''; for(let dish of d.filter(x=>x.page==='dishes').slice(0,20)){{out.textContent+='⏳ '+dish.sub+'\\n'; try{{let pr=await fetch('/api/ping?ip='+encodeURIComponent(dish.sub)); let pj=await pr.json(); out.textContent+= (pj.ok?'✅ ':'❌ ')+dish.sub+' -> '+pj.out.slice(0,60)+'\\n'; window.addLog(dish.sub,pj.ok?'✅':'❌',pj.out.slice(0,40));}}catch(e){{}} await new Promise(r=>setTimeout(r,250));}}}}catch(e){{out.textContent='خطأ: '+e;}}
        }}
        (async()=>{{try{{let r=await fetch('/api/search?q=192',{{cache:'no-store'}}); let d=await r.json(); let h=''; d.filter(x=>x.page==='dishes').slice(0,8).forEach(x=>{{h+='<div style="display:flex;justify-content:space-between;padding:8px 10px;border-bottom:1px solid #ffffff08"><span>🌐 '+x.sub+' - '+x.title+'</span><button class=btn-gold onclick="document.getElementById(\\'pingIp\\').value=\\''+x.sub+'\\'; window.doSinglePing()" style="padding:5px 10px">Ping</button></div>';}}); document.getElementById('quickDishes').innerHTML=h||'لا يوجد';}}catch(e){{}}}})();
        document.getElementById('pingIp').addEventListener('keydown',e=>{{if(e.key==='Enter'){{e.preventDefault(); window.doSinglePing();}}}});
        </script>'''
    if v=='dishes':
        rs=qall(f"SELECT * FROM {dish_tbl} ORDER BY id DESC")
        rows_html=""
        for r in rs:
            dn=esc(r.get('dish_name') or 'صحن');ip=esc(r.get('ip') or '');loc=esc(r.get('location') or '');rid=r['id']
            rows_html+=f'<div class="card anim" id="dish-{rid}" data-name="{dn}" data-ip="{ip}" data-loc="{loc}" style="display:flex;justify-content:space-between"><div><b>{dn}</b><br><a href="http://{ip}" target=_blank style="background:#000;color:#ffbe4d;padding:5px 10px;border-radius:8px;font-family:monospace;text-decoration:none">🌐 {ip}</a><br><small style="color:#888">{loc}</small><br><small style="color:#22c55e">☁ {dish_tbl}</small></div><div style="display:flex;flex-direction:column;gap:6px"><button class=btn-gold onclick="window.quickPingD({rid})" style="padding:7px 12px;background:linear-gradient(90deg,#22c55e,#16a34a);color:#fff">📶</button><div style="display:flex;gap:4px"><button class=btn-gold onclick="window.editDish({rid})" style="padding:7px 9px">✏</button><button class=btn-del onclick="window.askDel(\'/del_dish/{rid}\')" style="padding:7px 9px">🗑</button></div></div></div>'
        return f'''<div style='max-width:900px;margin:0 auto'><div class=card><div style='display:flex;justify-content:space-between;flex-wrap:wrap'><h3>📡 {L('الصحون','Dishes')} - {len(rs)} <small style='color:#22c55e'>☁ {dish_tbl}</small></h3><div style='display:flex;gap:6px'><button onclick="loadPage('ping')" class=btn-gold style='padding:7px 12px;background:linear-gradient(90deg,#22c55e,#16a34a);color:#fff'>📶 Ping FIXED</button><a href='/api/export/dishes' class=btn-gold style='text-decoration:none;padding:7px 12px'>📗 Excel</a></div></div><form data-ajax method=post action=/add_dish style='display:flex;gap:6px;flex-wrap:wrap;margin-top:10px'><input name=dish_name placeholder='{L('اسم الصحن','Name')}' required style='flex:1'><input name=ip placeholder='192.168.1.1' required style='flex:1'><input name=location placeholder='{L('موقع','Location')}' style='flex:1'><button class=btn-gold>➕ حفظ ☁</button></form><input id=searchBox placeholder='🔍 بحث فوري...' oninput="window.searchDishes(this.value)" style='margin-top:10px;width:100%;padding:12px;border-radius:12px;background:#0f1424;border:1px solid #ffffff18'></div><div id=dl>{rows_html}</div></div><script>
        window.editDish=function(id){{let c=document.getElementById('dish-'+id);document.getElementById('editModal').classList.add('show');document.getElementById('editBody').innerHTML='<input id=edit_dish_name value="'+c.dataset.name+'" style="width:100%;padding:12px;margin:4px 0"><input id=edit_ip value="'+c.dataset.ip+'" style="width:100%;padding:12px;margin:4px 0"><input id=edit_loc value="'+c.dataset.loc+'" style="width:100%;padding:12px;margin:4px 0"><button onclick="window.saveDish('+id+')" class=btn-gold style="width:100%;padding:12px">💾 حفظ</button>';}}
        window.saveDish=function(id){{let nn=document.getElementById('edit_dish_name').value;let ii=document.getElementById('edit_ip').value;let ll=document.getElementById('edit_loc').value;fetch('/edit_dish/'+id,{{method:'POST',body:new URLSearchParams({{dish_name:nn,ip:ii,location:ll}})}}).then(r=>{{if(!r.ok)alert('ممنوع');else{{window.closeEditModal();loadPage('dishes',true);}}}});}}
        window.quickPingD=function(id){{let c=document.getElementById('dish-'+id);loadPage('ping');setTimeout(()=>{{let inp=document.getElementById('pingIp');if(inp){{inp.value=c.dataset.ip;window.doSinglePing();}}}},500);}}
        window.searchDishes=function(q){{q=(q||'').toLowerCase();document.querySelectorAll('[id^=dish-]').forEach(card=>{{let txt=(card.dataset.name+card.dataset.ip+card.dataset.loc).toLowerCase();card.style.display=txt.includes(q)?'flex':'none';}});}}
        </script>'''
    if v=='towers':
        rs=qall("SELECT * FROM towers ORDER BY id DESC")
        rows=""
        for r in rs:
            rows+=f"<div class='card anim' id='tower-{r['id']}' data-name='{esc(r['name'])}' data-area='{esc(r['area'] or '')}' data-lat='{r.get('lat') or 0}' data-lng='{r.get('lng') or 0}'><div style='display:flex;justify-content:space-between'><div><b>🗼 {esc(r['name'])}</b><br><small>{esc(r['area'] or '')}</small><br><small style='color:#ffbe4d'>📍 {r.get('lat')}, {r.get('lng')}</small></div><div style='display:flex;gap:5px'><button class=btn-gold onclick=\"window.openEditTower({r['id']})\" style='padding:8px 10px'>✏</button><button class=btn-del onclick=\"window.askDel('/del_tower/{r['id']}')\" style='padding:8px 10px'>🗑</button></div></div></div>"
        return f'''<div style='max-width:700px;margin:0 auto'><div class=card><h3>🗼 {L('الأبراج','Towers')}</h3><form data-ajax method=post action=/add_tower style='display:flex;gap:6px;flex-wrap:wrap;margin-top:8px'><input name=name placeholder='{L('اسم البرج','Tower')}' required style='flex:1'><input name=area placeholder='{L('المنطقة','Area')}' style='flex:1'><input name=lat placeholder='lat' style='flex:0.6'><input name=lng placeholder='lng' style='flex:0.6'><button class=btn-gold>➕ فوري</button></form></div>{rows or '<div class=card>لا يوجد</div>'}<script>
        window.openEditTower=function(id){{let c=document.getElementById('tower-'+id);document.getElementById('editModal').classList.add('show');document.getElementById('editBody').innerHTML='<input id=edit_t_name value="'+c.dataset.name+'" style="width:100%;margin:6px 0;padding:12px"><input id=edit_t_area value="'+c.dataset.area+'" style="width:100%;margin:6px 0;padding:12px"><input id=edit_t_lat value="'+c.dataset.lat+'" style="width:100%;margin:6px 0;padding:12px"><input id=edit_t_lng value="'+c.dataset.lng+'" style="width:100%;margin:6px 0;padding:12px"><button onclick="window.saveTower('+id+')" class=btn-gold style="width:100%;padding:12px">💾 حفظ</button>';}}
        window.saveTower=function(id){{let nn=document.getElementById('edit_t_name').value;let aa=document.getElementById('edit_t_area').value;let la=document.getElementById('edit_t_lat').value;let ln=document.getElementById('edit_t_lng').value;fetch('/edit_tower/'+id,{{method:'POST',body:new URLSearchParams({{name:nn,area:aa,lat:la,lng:ln}})}}).then(r=>{{if(!r.ok)alert('ممنوع');else{{window.closeEditModal();loadPage('towers',true);}}}});}}
        </script></div>'''
    if v=='subs':
        rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 200")
        rows=""
        for r in rs:
            rows+=f"<div class='card anim' id='sub-{r['id']}' data-name='{esc(r['name'])}' data-phone='{esc(r['phone'] or '')}' data-note='{esc(r['note'] or '')}' style='display:flex;justify-content:space-between'><div><b>{esc(r['name'])}</b><br>📞 {esc(r['phone'] or '')}</div><div style='display:flex;gap:5px'><button class=btn-gold onclick=\"window.openEditSub({r['id']})\" style='padding:8px 10px'>✏</button><button class=btn-del onclick=\"window.askDel('/del_sub/{r['id']}')\" style='padding:8px 10px'>🗑</button></div></div>"
        return f'''<div style='max-width:700px;margin:0 auto'><div class=card><h3>👥 {L('المشتركين','Subs')}</h3><form data-ajax method=post action=/add_sub style='display:flex;gap:5px;flex-wrap:wrap'><input name=name placeholder='الاسم' required style='flex:1'><input name=phone placeholder='رقم' style='flex:1'><input name=note placeholder='ملاحظة' style='flex:1'><button class=btn-gold>➕ فوري</button></form></div>{rows}<script>
        window.openEditSub=function(id){{let c=document.getElementById('sub-'+id);document.getElementById('editModal').classList.add('show');document.getElementById('editBody').innerHTML='<input id=edit_s_name value="'+c.dataset.name+'" style="width:100%;margin:6px 0;padding:12px"><input id=edit_s_phone value="'+c.dataset.phone+'" style="width:100%;margin:6px 0;padding:12px"><input id=edit_s_note value="'+c.dataset.note+'" style="width:100%;margin:6px 0;padding:12px"><button onclick="window.saveSub('+id+')" class=btn-gold style="width:100%;padding:12px">💾</button>';}}
        window.saveSub=function(id){{let nn=document.getElementById('edit_s_name').value;let pp=document.getElementById('edit_s_phone').value;let no=document.getElementById('edit_s_note').value;fetch('/edit_sub/'+id,{{method:'POST',body:new URLSearchParams({{name:nn,phone:pp,note:no}})}}).then(r=>{{if(!r.ok)alert('ممنوع');else{{window.closeEditModal();loadPage('subs',true);}}}});}}
        </script></div>'''
    if v=='ledger':
        rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 200")
        rows=""
        for r in rs:
            rows+=f"<div class='card anim' id='led-{r['id']}' data-name='{esc(r['name'])}' data-amount='{r['amount']}'><div style='display:flex;justify-content:space-between'><div><b>{esc(r['name'])}</b> - <b style='color:#ffbe4d'>{r['amount']}</b></div><div><button class=btn-gold onclick=\"window.openEditLed({r['id']})\" style='padding:7px 9px'>✏</button><button class=btn-del onclick=\"window.askDel('/del_ledger/{r['id']}')\" style='padding:7px 9px'>🗑</button></div></div></div>"
        return f'''<div style='max-width:700px;margin:0 auto'><div class=card><h3>📒 {L('الحسابات','Accounts')}</h3><form data-ajax method=post action=/add_ledger style='display:flex;gap:5px;flex-wrap:wrap'><input name=name placeholder='الاسم' required style='flex:1'><input name=amount type=number step=0.01 placeholder='المبلغ' required style='flex:1'><input name=note placeholder='ملاحظة' style='flex:1'><select name=currency style='flex:0.5'><option>USD</option><option>SYP</option></select><button class=btn-gold>➕ فوري</button></form></div>{rows}<script>
        window.openEditLed=function(id){{let c=document.getElementById('led-'+id);document.getElementById('editModal').classList.add('show');document.getElementById('editBody').innerHTML='<input id=edit_l_name value="'+c.dataset.name+'" style="width:100%;margin:6px 0;padding:12px"><input id=edit_l_amount value="'+c.dataset.amount+'" style="width:100%;margin:6px 0;padding:12px"><button onclick="window.saveLed('+id+')" class=btn-gold style="width:100%;padding:12px">💾</button>';}}
        window.saveLed=function(id){{let nn=document.getElementById('edit_l_name').value;let aa=document.getElementById('edit_l_amount').value;fetch('/edit_ledger/'+id,{{method:'POST',body:new URLSearchParams({{name:nn,amount:aa,note:'',currency:'USD'}})}}).then(()=>{{window.closeEditModal();loadPage('ledger',true);}});}}
        </script></div>'''
    if v=='logs':
        rs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 200")
        rows="".join([f"<div class='card anim' style='font-size:13px;border-left:3px solid #ffbe4d'><b style='color:#ffbe4d'>{esc(r['user_phone'])}</b> {esc(r['action'])} - {esc(r['detail'])}<br><small style='color:#777'>{esc(r['time'])}</small></div>" for r in rs])
        return f"<div style='max-width:900px;margin:0 auto'><div class=card style='display:flex;justify-content:space-between'><h3>📜 {L('السجل','Logs')} - {len(rs)}</h3><a href='/api/export/logs' class=btn-gold style='text-decoration:none;padding:7px 12px'>📗 Excel</a></div>{rows or '<div class=card>لا يوجد سجل - سيظهر بعد أي عملية</div>'}</div>"
    if v=='network':
        dish_tbl=get_dish_table()
        dishes=qall(f"SELECT * FROM {dish_tbl} ORDER BY id DESC")
        rows="".join([f"<div class='card anim' id='net-{d['id']}' data-ip='{esc(d.get('ip',''))}' style='display:flex;justify-content:space-between'><div><b>{esc(d.get('dish_name') or 'صحن')}</b> - <a href='http://{esc(d.get('ip',''))}' target=_blank style='color:#ffbe4d'>🌐 {esc(d.get('ip',''))}</a><br><small class='net-out'>⏳...</small></div><button class=btn-gold onclick='window.checkOne({d['id']})'>📶</button></div>" for d in dishes])
        return f'''<div style='max-width:800px;margin:0 auto'><div class=card style='background:linear-gradient(135deg,#0f172a,#1e293b);border:1px solid #ffbe4d33'><h3>📊 {L('حالة الشبكة','Network')} LIVE - ☁ {dish_tbl}</h3><div style='display:flex;gap:8px;margin-top:8px'><button class=btn-gold onclick='window.checkAll()' style='flex:1;background:linear-gradient(90deg,#22c55e,#16a34a);color:#fff;padding:12px'>🚀 {L('فحص الكل','Check All')}</button><button class=btn-gold onclick="loadPage('ping')" style='flex:1'>📶 Ping FIXED</button></div><div id=summary style='margin-top:10px;font-weight:800'></div></div>{rows}<script>
        window.checkOne=async function(id){{let c=document.getElementById('net-'+id);let out=c.querySelector('.net-out');out.textContent='⏳...';try{{let r=await fetch('/api/ping?ip='+encodeURIComponent(c.dataset.ip));let j=await r.json();out.textContent=j.out.slice(0,80);out.style.color=j.ok?'#22c55e':'#ef4444';}}catch(e){{out.textContent='❌';}}}}
        window.checkAll=async function(){{let cards=document.querySelectorAll('[id^=net-]');let on=0,off=0;for(let c of cards){{let out=c.querySelector('.net-out');out.textContent='⏳...';try{{let r=await fetch('/api/ping?ip='+encodeURIComponent(c.dataset.ip));let j=await r.json();out.textContent=j.ok?'✅ '+j.out.slice(0,50):'❌ '+j.out.slice(0,50);out.style.color=j.ok?'#22c55e':'#ef4444'; if(j.ok)on++; else off++;}}catch(e){{off++;}} document.getElementById('summary').innerHTML='✅ '+on+' | ❌ '+off; await new Promise(r=>setTimeout(r,200));}}}}
        window.checkAll();
        </script></div>'''
    if v=='map':
        towers=qall("SELECT * FROM towers")
        tj_json=json.dumps([{"name":t['name'],"area":t.get('area') or '',"lat":float(t.get('lat') or 35.1318),"lng":float(t.get('lng') or 36.7578)} for t in towers],ensure_ascii=False)
        return f'''<div class=card style='padding:10px;background:linear-gradient(180deg,#0f172a,#111827);border:1px solid #ffffff12'>
        <div style='display:flex;gap:6px;margin-bottom:10px;flex-wrap:wrap'>
        <input id=mapSearch placeholder='🔍 {L('بحث برج...','Search tower...')}' onkeydown="if(event.key==='Enter'){{event.preventDefault(); window.doMapSearch();}}" style='flex:1;min-width:140px;background:#1f2937;border:1px solid #ffffff15;color:#fff;padding:10px 12px;border-radius:12px'>
        <button class=btn-gold onclick="window.doMapSearch()" style='padding:10px 12px'>🔍 {L('بحث','Search')}</button>
        <button class=btn-gold onclick="window.locateMe()" style='background:linear-gradient(90deg,#22c55e,#16a34a);color:#fff;padding:10px 12px'>📍 {L('موقعي','My Loc')}</button>
        <button class=btn-gold onclick="window.enableAddPoint()" id=addPointBtn style='background:linear-gradient(90deg,#f59e0b,#d97706);color:#fff;padding:10px 12px'>➕ {L('نقطة','Point')}</button>
        <span id=coordsLabel style='color:#ffbe4d;font-size:12px'>📍 -</span></div>
        <div id=map style='height:72vh;min-height:460px;border-radius:16px;background:#0f172a;z-index:1;border:2px solid #ffffff0f'></div></div><script>
        let _towers={tj_json}; let _map=null; let addPointMode=false;
        window.doMapSearch=function(){{let q=document.getElementById('mapSearch').value.trim().toLowerCase(); if(!q) return; let f=_towers.find(t=>t.name.toLowerCase().includes(q)||t.area.toLowerCase().includes(q)); if(f && _map){{_map.flyTo([f.lat,f.lng],17,{{duration:1}});}}}}
        window.locateMe=function(){{if(_map && navigator.geolocation){{navigator.geolocation.getCurrentPosition(p=>{{_map.flyTo([p.coords.latitude,p.coords.longitude],16);}});}}}}
        window.enableAddPoint=function(){{addPointMode=!addPointMode; let b=document.getElementById('addPointBtn'); b.textContent=addPointMode?'✅ اضغط الخريطة':'➕ نقطة'; if(addPointMode) _map.getContainer().style.cursor='crosshair'; else _map.getContainer().style.cursor='';}}
        setTimeout(()=>{{if(typeof L==='undefined') return; _map=L.map('map').setView([35.1318,36.7578],13); let osm=L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png').addTo(_map); let sat=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}').addTo(_map); L.control.layers({{"عادية":osm,"قمر صناعي":sat}}).addTo(_map); _towers.forEach(t=>L.marker([t.lat,t.lng]).addTo(_map).bindPopup(t.name)); setTimeout(()=>_map.invalidateSize(),300); _map.on('click',e=>{{document.getElementById('coordsLabel').textContent='📍 '+e.latlng.lat.toFixed(5)+','+e.latlng.lng.toFixed(5); if(addPointMode){{let lat=e.latlng.lat.toFixed(6), lng=e.latlng.lng.toFixed(6); let name=prompt('اسم النقطة؟')||'نقطة'; if(name){{fetch('/add_tower',{{method:'POST',body:new URLSearchParams({{name:name,area:'',lat:lat,lng:lng}})}}).then(()=>loadPage('map',true));}}}});}},200);
        </script>'''
    if v=='support':
        return """<div class=card style='text-align:center;max-width:500px;margin:0 auto'><h2>🛠 الدعم</h2><a href='https://wa.me/905344851045' target=_blank style='display:inline-block;background:#22c55e;color:#fff;padding:14px 24px;border-radius:14px;text-decoration:none;margin:6px;font-weight:800'>💬 واتساب</a></div>"""
    if v=='settings':
        us=qall("SELECT * FROM users ORDER BY phone DESC")
        uh=""
        for u in us:
            ph=esc(u["phone"]);un=esc(u.get("username") or "");ro=esc(u.get("role") or "")
            uh+=f'<div class="card anim" id="user-{ph}" data-phone="{ph}" data-username="{un}" data-role="{ro}" style="display:grid;grid-template-columns:1fr auto;gap:12px;align-items:center"><div><b>{un}</b><br><span style="color:#ffbe4d;font-family:monospace">{ph}</span> {ro}</div><div style="display:flex;gap:6px"><button class=btn-gold onclick="window.openEditUser(\'{ph}\')" style="padding:8px 10px">✏</button><button class=btn-del onclick="window.askDel(\'/del_user/{ph}\')" style="padding:8px 10px">🗑</button></div></div>'
        return f'''<div style='max-width:800px;margin:0 auto'><div class=card><h3>🔑 كلمة السر</h3><form data-ajax method=post action=/change_pass style='display:flex;gap:8px'><input name=newpass type=password placeholder='جديدة' required style='flex:1'><button class=btn-gold>💾</button></form></div><div style='display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px'><div class=card style='text-align:center'><h4>🌐 اللغة</h4><button onclick="window.toggleLang()" style='width:100%;padding:14px;border-radius:12px;border:1px solid #ffffff15;background:#1f2937;color:#fff;font-weight:800;cursor:pointer'>🌐 عربي / EN</button></div><div class=card style='text-align:center'><h4>🎨 المظهر</h4><button onclick="window.toggleTheme()" style='width:100%;padding:14px;border-radius:12px;background:#1f2937;color:#fff'>🌓 ليل/نهار</button></div></div><div class=card><h4>👤 اضافة يوزر</h4><form data-ajax method=post action=/add_user style='display:flex;flex-direction:column;gap:10px'><input name=user_field placeholder='📱 رقم / يوزر' required><input name=password type=password placeholder='🔑 password' required><select name=role><option value=tech>فني</option><option value=manager>مدير</option></select><button class=btn-gold>➕ فوري</button></form></div>{uh}<script>
        window.openEditUser=function(ph){{let c=document.getElementById('user-'+ph);document.getElementById('editModal').classList.add('show');document.getElementById('editBody').innerHTML='<input id=edit_u_field value="'+c.dataset.phone+'" style="width:100%;padding:12px"><input id=edit_u_pass type="password" placeholder="باسورد جديد" style="width:100%;padding:12px;margin-top:8px"><select id=edit_u_role style="width:100%;padding:12px;margin-top:8px"><option value="tech">فني</option><option value="manager">مدير</option></select><button onclick="window.saveUser(\\''+ph+'\\')" class=btn-gold style="width:100%;padding:14px;margin-top:12px">💾 حفظ</button>'; document.getElementById('edit_u_role').value=c.dataset.role;}}
        window.saveUser=function(oldPh){{let ff=document.getElementById('edit_u_field').value.trim();let pw=document.getElementById('edit_u_pass').value;let ro=document.getElementById('edit_u_role').value;if(!ff){{alert('مطلوب');return;}}let data={{old_phone:oldPh,phone:ff,username:ff,role:ro}};if(pw.trim()!='')data.password=pw.trim();fetch('/edit_user',{{method:'POST',body:new URLSearchParams(data)}}).then(r=>{{if(!r.ok)r.text().then(t=>alert(t));else{{window.closeEditModal();loadPage('settings',true);}}}});}}
        </script></div>'''
    return "<div class=card>ok</div>"

def layout(c, v='home'):
    th = session.get('theme', 'dark')
    is_dark = (th == 'dark')
    bg = 'radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 60%, #070a1f 100%)' if is_dark else '#f1f5f9'
    card_bg = '#1e2433' if is_dark else '#ffffff'
    txt = '#ffffff' if is_dark else '#0f172a'
    border = '#ffffff12' if is_dark else '#e2e8f0'
    cur_user = qone("SELECT * FROM users WHERE phone=?", (session.get('phone') or '',))
    if not cur_user:
        cur_user = {}
    role = (cur_user.get('role') or 'tech')
    req_lang = session.get('lang','ar')
    def L(ar,en): return ar if req_lang=='ar' else en
    username_display = esc(cur_user.get('username') or cur_user.get('phone') or session.get('phone') or '')
    return f"""<html dir=rtl lang=ar><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1,maximum-scale=1'>
<link rel=stylesheet href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'>
<style>
*{{box-sizing:border-box;font-family:system-ui}}body{{margin:0;background:{bg};color:{txt};overflow-x:hidden;direction:rtl}}
.top{{position:fixed;top:0;left:0;right:0;height:62px;background:linear-gradient(90deg,#0f172af2,#111827f2);backdrop-filter:blur(16px);color:#fff;display:flex;align-items:center;justify-content:space-between;padding:0 14px;z-index:1003;border-bottom:1px solid #ffffff12;box-shadow:0 4px 24px #0006}}
.sidebar{{position:fixed;right:0!important;top:0;width:285px;height:100%;background:linear-gradient(180deg,#0f172a 0%,#070e22 100%);color:#fff;z-index:1002;padding-top:70px;transform:translateX(110%);transition:transform 0.45s cubic-bezier(0.4,0,0.2,1);overflow-y:auto;box-shadow:-10px 0 40px #0008;border-left:1px solid #ffffff0f}}
.sidebar.active{{transform:none}}
.sidebar a{{display:flex;align-items:center;gap:11px;padding:12px 15px;margin:6px 11px;color:#cbd5e1;text-decoration:none;border-radius:13px;background:linear-gradient(90deg,#ffffff06,#ffffff03);border:1px solid #ffffff06;transition:all.35s cubic-bezier(0.4,0,0.2,1)}}
.sidebar a:hover{{background:#ffffff12;transform:translateX(-4px);color:#fff}}
.sidebar a.active{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:800;box-shadow:0 6px 18px #ffbe4d44}}
#overlay{{position:fixed;inset:0;background:#0009;backdrop-filter:blur(4px);z-index:1001;display:none;opacity:0;transition:opacity 0.45s}}#overlay.show{{display:block;opacity:1}}
.main{{margin-top:74px;padding:14px;min-height:90vh}}
.card{{background:linear-gradient(180deg,{card_bg},{card_bg});color:{txt};padding:15px;border-radius:15px;margin-bottom:11px;border:1px solid {border};transition:all.22s;box-shadow:0 4px 14px #0002}}
.card:hover{{transform:translateY(-2px);box-shadow:0 10px 28px #0005}}
input,select{{padding:12px 14px;margin:5px 0;border-radius:11px;border:1px solid {border};width:100%;background:#ffffff07;color:{txt};font-size:14px}}
.btn-gold{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;padding:9px 16px;border:0;border-radius:11px;font-weight:800;cursor:pointer}}
.btn-del{{background:linear-gradient(90deg,#ef4444,#dc2626);color:#fff;padding:8px 13px;border:0;border-radius:11px;cursor:pointer}}
#delModal, #editModal{{position:fixed;inset:0;background:#000a;backdrop-filter:blur(10px);display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:opacity 0.35s;z-index:2000}}
#delModal.show, #editModal.show{{opacity:1;pointer-events:auto}}
#delBox, #editBox{{background:linear-gradient(180deg,{card_bg},#0f1424);color:{txt};padding:24px;border-radius:18px;width:92%;max-width:450px;transform:scale(.92) translateY(18px);transition:transform 0.45s cubic-bezier(0.4,0,0.2,1)}}
#delModal.show #delBox, #editModal.show #editBox{{transform:scale(1) translateY(0)}}
</style></head>
<body>
<div id=overlay onclick="toggleSb(false)"></div>
<div class=sidebar id=sb>
<div style='padding:0 18px 10px;border-bottom:1px solid #ffffff0a;margin-bottom:8px'><div style='font-weight:900;font-size:17px'>OMAIA <span style='color:#ffbe4d'>ISP</span> <small style='color:#22c55e'>☁</small></div><small style='color:#64748b'>{username_display} • {role} • {get_dish_table()}</small></div>
<a href="javascript:loadPage('home')" id=nav-home>🏠 {L('الرئيسية','Home')}</a>
<a href="javascript:loadPage('ping')" id=nav-ping style='background:linear-gradient(90deg,#22c55e18,#16a34a18);border:1px solid #22c55e33'>📶 {L('بنج منفصل','Separate Ping')} <span style='background:#22c55e;color:#fff;padding:2px 6px;border-radius:8px;font-size:10px;margin-right:auto'>FIXED</span></a>
<a href="javascript:loadPage('network')" id=nav-network>📊 {L('حالة الشبكة','Network')} <span style='background:#0ea5e9;color:#fff;padding:2px 6px;border-radius:8px;font-size:10px;margin-right:auto'>LIVE</span></a>
<a href="javascript:loadPage('dishes')" id=nav-dishes>📡 {L('الصحون','Dishes')} <span style='background:#22c55e;color:#fff;padding:2px 6px;border-radius:6px;font-size:9px'>☁</span></a>
<a href="javascript:loadPage('towers')" id=nav-towers>🗼 {L('الأبراج','Towers')}</a>
<a href="javascript:loadPage('subs')" id=nav-subs>👥 {L('المشتركين','Subs')}</a>
<a href="javascript:loadPage('ledger')" id=nav-ledger>📒 {L('الحسابات','Ledger')}</a>
<a href="javascript:loadPage('logs')" id=nav-logs>📜 {L('السجل','Logs')}</a>
<a href="javascript:loadPage('map')" id=nav-map>🗺 {L('الخريطة الحية','Live Map')} <span style='background:#f59e0b;color:#fff;padding:2px 6px;border-radius:8px;font-size:10px;margin-right:auto'>HD</span></a>
<a href="javascript:loadPage('support')" id=nav-support>🛠 {L('الدعم','Support')}</a>
<a href="javascript:loadPage('settings')" id=nav-settings>⚙ {L('الإعدادات','Settings')}</a>
<a href="javascript:logoutFast()" style='margin-top:10px;background:linear-gradient(90deg,#ef444418,#dc262618);border:1px solid #ef444433'>🚪 {L('خروج','Logout')}</a>
</div>
<div class=top>
<div style='display:flex;gap:8px;align-items:center'>
<span onclick="toggleSb()" style='font-size:24px;cursor:pointer;padding:6px 8px;border-radius:10px;background:#ffffff0a'>☰</span>
<input id=topsearch placeholder='🔍 {L('بحث','Search')}...' onkeydown="if(event.key==='Enter'){{event.preventDefault(); window.doTopSearch(this.value);}}" style='background:#1f2937;border:1px solid #ffffff15;color:#fff;padding:9px 14px;border-radius:12px;width:160px;font-size:13px'>
</div>
<div style='font-weight:900;font-size:16px'>OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<div style='display:flex;gap:8px;align-items:center'>
<button onclick="window.toggleTheme()" style='background:#ffffff0a;color:#fff;border:1px solid #ffffff0f;padding:8px 11px;border-radius:11px;cursor:pointer'>🌓</button>
</div>
</div>
<div id=searchResults style='position:fixed;top:66px;right:12px;left:12px;max-width:480px;margin:0 auto;background:linear-gradient(180deg,#1e2433,#171e2f);border:1px solid #ffffff15;border-radius:14px;z-index:1500;display:none;max-height:60vh;overflow:auto;box-shadow:0 16px 40px #000a'></div>
<div class=main id=mn>{c}</div>
<div id=delModal><div id=delBox><h3 style='text-align:center'>تأكيد الحذف؟</h3><div style='display:flex;gap:10px;margin-top:14px'><button onclick="window.closeDel()" style='flex:1;padding:12px;border-radius:12px'>تراجع</button><button id=delYes style='flex:1;padding:12px;border-radius:12px;background:#ef4444;color:#fff;border:0'>حذف</button></div></div></div>
<div id=editModal><div id=editBox><div style='display:flex;justify-content:space-between'><h3>✏ تعديل</h3><button onclick="window.closeEditModal()" style='background:#ffffff12;border:0;width:32px;height:32px;border-radius:50%;cursor:pointer'>✕</button></div><div id=editBody></div></div></div>
<script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>
<script>
let cur='{v}';
function toggleSb(force){{
  let sb=document.getElementById('sb'),ov=document.getElementById('overlay');
  let open=force!==undefined?force:!sb.classList.contains('active');
  sb.classList.toggle('active',open);
  ov.classList.toggle('show',open);
  if(open){{ov.style.display='block'; setTimeout(()=>ov.style.opacity='1',10);}} else {{ov.style.opacity='0'; setTimeout(()=>ov.style.display='none',450);}}
}}
async function loadPage(v,force=false,push=true){{
  if(push && cur!==v){{ try{{history.pushState({{page:v}}, '', '/dash?v='+v);}}catch(e){{}} }}
  cur=v;
  toggleSb(false);
  document.querySelectorAll('.sidebar a').forEach(a=>a.classList.remove('active'));
  let nav=document.getElementById('nav-'+v); if(nav)nav.classList.add('active');
  let mn=document.getElementById('mn');
  try{{
    let r=await fetch('/api/page?v='+v,{{cache:'no-store'}});
    let h=await r.text();
    mn.innerHTML=h;
    bind(); execScripts();
  }}catch(e){{ mn.innerHTML='<div class=card>❌ '+e+'</div>'; }}
}}
function execScripts(){{document.getElementById('mn').querySelectorAll('script').forEach(s=>{{try{{(0,eval)(s.textContent)}}catch(e){{console.error(e)}}}});}}
function bind(){{
  document.querySelectorAll('form[data-ajax]').forEach(f=>{{
    if(f.dataset.bound) return;
    f.dataset.bound='1';
    f.onsubmit=async e=>{{
      e.preventDefault();
      let btn=f.querySelector('button');
      let old=btn?btn.innerHTML:'';
      if(btn){{btn.innerHTML='⏳...'; btn.disabled=true;}}
      try{{
        let r=await fetch(f.action,{{method:'POST',body:new FormData(f),cache:'no-store'}});
        let txt=await r.text();
        if(r.ok){{f.reset(); await loadPage(cur,true);}}
        else{{alert(txt);}}
      }}catch(err){{alert(err);}} finally{{if(btn){{btn.innerHTML=old; btn.disabled=false;}}}}
    }};
  }});
}}
window.askDel=function(u){{window._delUrl=u;document.getElementById('delModal').classList.add('show');}}
window.closeDel=function(){{document.getElementById('delModal').classList.remove('show');window._delUrl=null;}}
window.closeEditModal=function(){{document.getElementById('editModal').classList.remove('show');}}
document.getElementById('delYes').onclick=async()=>{{if(window._delUrl){{let r=await fetch(window._delUrl); if(!r.ok){{let t=await r.text(); alert(t); window.closeDel(); return;}} window.closeDel(); loadPage(cur,true);}}}};
window.toggleLang=async function(){{
  await fetch('/toggle_lang');
  let lang=localStorage.getItem('omaia_lang')||'ar';
  lang=lang==='ar'?'en':'ar';
  localStorage.setItem('omaia_lang',lang);
  await loadPage(cur,true);
}}
window.toggleTheme=async function(){{
  await fetch('/toggle_theme');
  await loadPage(cur,true);
}}
window.doTopSearch=function(q){{if(!q||!q.trim()) return; loadPage('search&q='+encodeURIComponent(q.trim()),true);}}
window.logoutFast=async function(){{ try{{await fetch('/api/logout',{{method:'POST'}});}}catch(e){{}} localStorage.clear(); location.replace('/login'); }};
bind(); execScripts();
</script>
</body></html>"""

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)), debug=False)
