from flask import Flask, request, redirect, session, jsonify, Response
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, html, ipaddress, json, socket, io, csv, datetime, time
import psycopg2, psycopg2.extras
import sqlite3

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "omia-sec-2026-CHANGE-ME")
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(days=30)

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
PG_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1) if DATABASE_URL.startswith("postgres://") else DATABASE_URL
USE_PG = bool(DATABASE_URL)

_pg = None
_last_check = 0
_dish_cache = {"name": None, "ts": 0}
_cnt_cache = {}
_stats_cache = {"data": None, "ts": 0}

def esc(s):
    return html.escape(str(s or ''), quote=True)

def db():
    global _pg, _last_check
    if USE_PG:
        now = time.time()
        if _pg and now - _last_check < 30:
            return _pg
        if _pg:
            try:
                cur = _pg.cursor()
                cur.execute("SELECT 1")
                cur.close()
                _last_check = now
                return _pg
            except:
                try:
                    _pg.close()
                except:
                    pass
                _pg = None
        try:
            _pg = psycopg2.connect(PG_URL, sslmode='require', connect_timeout=3)
            _pg.autocommit = True
            _last_check = now
            return _pg
        except:
            pass
    try:
        c = sqlite3.connect("omia.db", check_same_thread=False, timeout=5)
        c.row_factory = sqlite3.Row
        return c
    except:
        c = sqlite3.connect(":memory:", check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c

def cc(c):
    if not USE_PG:
        try:
            c.close()
        except:
            pass

def qall(q, a=()):
    c = db()
    try:
        if USE_PG:
            cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(q.replace("?", "%s"), a)
            rs = [dict(r) for r in cur.fetchall()]
            cur.close()
            return rs
        else:
            rs = [dict(r) for r in c.execute(q, a).fetchall()]
            cc(c)
            return rs
    except:
        cc(c)
        return []

def qone(q, a=()):
    r = qall(q, a)
    return r[0] if r else None

def qexec(q, a=()):
    c = db()
    try:
        if USE_PG:
            cur = c.cursor()
            cur.execute(q.replace("?", "%s"), a)
            cur.close()
        else:
            c.execute(q, a)
            c.commit()
            cc(c)
        _cnt_cache.clear()
        _stats_cache["ts"] = 0
    except:
        cc(c)

def add_log(action, detail=""):
    try:
        phone = session.get('phone', '')
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)", (phone, action, detail, now))
    except:
        pass

def get_dish_table():
    now = time.time()
    if _dish_cache["name"] and now - _dish_cache["ts"] < 120:
        return _dish_cache["name"]
    if USE_PG:
        try:
            c = db()
            cur = c.cursor()
            cur.execute("SELECT to_regclass('public.ips')")
            r = cur.fetchone()
            cur.close()
            tbl = "ips" if r and r[0] else "dish_ips"
            _dish_cache["name"] = tbl
            _dish_cache["ts"] = now
            return tbl
        except:
            return "dish_ips"
    return "dish_ips"

def fast_count(tbl, ttl=20):
    now = time.time()
    if tbl in _cnt_cache:
        v, ts = _cnt_cache[tbl]
        if now - ts < ttl:
            return v
    c = (qone(f"SELECT COUNT(*) c FROM {tbl}") or {}).get('c', 0)
    _cnt_cache[tbl] = (c, now)
    return c

def get_home_stats():
    now = time.time()
    if _stats_cache["data"] and now - _stats_cache["ts"] < 20:
        return _stats_cache["data"]
    tbl = get_dish_table()
    try:
        row = qone(f"SELECT (SELECT COUNT(*) FROM subs) as subs,(SELECT COUNT(*) FROM towers) as towers,(SELECT COUNT(*) FROM ledger) as ledger,(SELECT COUNT(*) FROM {tbl}) as dishes")
        if row:
            _stats_cache["data"] = row
            _stats_cache["ts"] = now
            return row
    except:
        pass
    return {"subs": fast_count("subs"), "towers": fast_count("towers"), "ledger": fast_count("ledger"), "dishes": fast_count(tbl)}

def init():
    ss = [
    "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,username TEXT)",
    "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,note TEXT)",
    "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,amount REAL,note TEXT,currency TEXT)",
    "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,dish_name TEXT)",
    "CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,area TEXT,lat REAL,lng REAL)",
    "CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,user_phone TEXT,action TEXT,detail TEXT,time TEXT)",
    "CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,msg TEXT,time TEXT,read INTEGER DEFAULT 0)",
    "CREATE TABLE IF NOT EXISTS ips(id SERIAL PRIMARY KEY, ip TEXT, location TEXT, dish_name TEXT, created_at TIMESTAMP DEFAULT NOW())"
    ]
    if USE_PG:
        for i in range(1,7):
            ss[i] = ss[i].replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY")
    for s in ss:
        qexec(s)
    if not qone("SELECT * FROM users WHERE phone=?", ('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)", ('05344851045', generate_password_hash('admin2024'), 'manager', 'admin'))
    if not qone("SELECT * FROM towers WHERE name=?", ('نقطة حماة الرئيسية',)):
        qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)", ('نقطة حماة الرئيسية','حماة',35.1318,36.7578))
    try:
        db()
    except:
        pass
init()

def login_required(f):
    @wraps(f)
    def w(*a,**kw):
        if not session.get('phone'):
            return redirect('/login')
        return f(*a,**kw)
    return w

def is_manager():
    u = qone("SELECT * FROM users WHERE phone=?", (session.get('phone') or '',))
    if not u:
        return False
    return (u.get('role') or '').lower() == 'manager'

def role_required_manager(f):
    @wraps(f)
    def w(*a,**kw):
        if not is_manager():
            return "ممنوع", 403
        return f(*a,**kw)
    return w

def is_valid_ip(ip):
    ip = ip.strip()
    if not ip:
        return False
    try:
        ipaddress.ip_address(ip)
        return True
    except:
        return len(ip) >= 7 and '.' in ip

@app.route('/ping')
@app.route('/health')
def public_ping():
    return jsonify(ok=True, pg=USE_PG, table=get_dish_table())

@app.route('/api/ping')
@login_required
def api_ping():
    ip = request.args.get('ip','').strip()
    if not is_valid_ip(ip):
        return jsonify(ok=False,out='IP غير صالح')
    for port in [80,8291,8728]:
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.4)
            if s.connect_ex((ip,port)) == 0:
                s.close()
                return jsonify(ok=True,out=f'✅ {ip}:{port} مفتوح')
            s.close()
        except:
            try:
                if s: s.close()
            except:
                pass
    return jsonify(ok=False,out=f'❌ {ip} لا يرد')

@app.route('/api/ping_tcp')
@login_required
def api_ping_tcp():
    ip = request.args.get('ip','').strip()
    try:
        port = int(request.args.get('port','80') or 80)
    except:
        port = 80
    if not is_valid_ip(ip):
        return jsonify(ok=False,out='IP غير صالح')
    s=None
    try:
        s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        s.settimeout(1)
        r=s.connect_ex((ip,port))
        s.close()
        return jsonify(ok=r==0,out=f'✅ {ip}:{port} مفتوح' if r==0 else f'❌ مغلق')
    except Exception as e:
        try:
            if s: s.close()
        except:
            pass
        return jsonify(ok=False,out=str(e))

@app.route('/api/notifications')
@login_required
def api_noti():
    rows=qall("SELECT * FROM notifications ORDER BY id DESC LIMIT 20")
    unread=qone("SELECT COUNT(*) c FROM notifications WHERE read=0")
    return jsonify(rows=rows,unread=unread.get('c',0) if unread else 0)

@app.route('/api/notifications/read',methods=['POST'])
@login_required
def api_noti_read():
    qexec("UPDATE notifications SET read=1")
    return jsonify(ok=True)

@app.route('/api/network_status')
@login_required
def api_network():
    st=get_home_stats()
    return jsonify(dishes=st.get('dishes',0),towers=st.get('towers',0),subs=st.get('subs',0))

@app.route('/toggle_lang')
@login_required
def toggle_lang_route():
    cur=session.get('lang','ar')
    session['lang']='en' if cur=='ar' else 'ar'
    return jsonify(ok=True,lang=session['lang'])

@app.route('/toggle_theme')
@login_required
def toggle_theme_route():
    cur=session.get('theme','dark')
    session['theme']='light' if cur=='dark' else 'dark'
    return jsonify(ok=True)

@app.route('/api/login_public',methods=['POST'])
def api_login_public():
    uin=request.form.get('userin','').strip()
    pw=request.form.get('password','')
    u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
    if u and check_password_hash(u['password'],pw):
        session['phone']=u['phone']
        session['username']=u.get('username') or u['phone']
        session.permanent=True
        add_log("دخول",uin)
        return jsonify(ok=True)
    return jsonify(ok=False,msg='خطأ'),401

@app.route('/api/export/<tbl>')
@login_required
def api_export(tbl):
    output=io.StringIO()
    w=csv.writer(output)
    if tbl=='logs':
        rows=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 2000")
        w.writerow(['ID','مستخدم','عمل','تفاصيل','وقت'])
        for r in rows:
            w.writerow([r['id'],r.get('user_phone',''),r.get('action',''),r.get('detail',''),r.get('time','')])
    else:
        dish_tbl=get_dish_table()
        if tbl=='dishes':
            rows=qall(f"SELECT * FROM {dish_tbl} ORDER BY id DESC")
            w.writerow(['ID','اسم','IP','موقع'])
            for r in rows:
                w.writerow([r['id'],r.get('dish_name',''),r.get('ip',''),r.get('location','')])
        else:
            w.writerow(['ID'])
    return Response(output.getvalue(),mimetype='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename={tbl}.csv'})

@app.route('/')
def ix():
    return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login')
def login():
    return """<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<style>*{box-sizing:border-box;font-family:system-ui}body{margin:0;min-height:100vh;background:#0a0e2a;display:flex;flex-direction:column;align-items:center;justify-content:center;color:#fff}
.card{background:#1e2433;border:1px solid #ffffff15;padding:26px;border-radius:22px;width:92%;max-width:380px}
input{width:100%;padding:13px;margin:8px 0;background:#0f1424;border:1px solid #ffffff20;color:#fff;border-radius:12px}
.btn{width:100%;padding:13px;border:0;border-radius:12px;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:900;font-size:17px;cursor:pointer}
.support{margin-top:12px;text-align:center;font-size:12px;color:#9ca3af}.support a{color:#22c55e;text-decoration:none;font-weight:800}
</style></head><body>
<div style='font-size:28px;font-weight:900;margin-bottom:12px'>OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<div class=card><form id=loginForm><input name=userin id=userin placeholder='📱 رقم / يوزر' required><input name=password id=password type=password placeholder='🔑 كلمة السر' required><button class=btn id=loginBtn>✨ دخول فوري</button><div id=msg style='text-align:center;margin-top:8px;color:#ff6b6b;font-size:13px'></div></form>
<div class=support>🛠 الدعم<br><a href='https://wa.me/905345851045' target=_blank>واتساب +90 534 485 10 45</a> | <a href='https://instagram.com/af_20_1999' target=_blank>af_20_1999</a></div></div>
<script>
let u=document.getElementById('userin'), p=document.getElementById('password');
let su=localStorage.getItem('omaia_user');
if(su) u.value=su;
document.getElementById('loginForm').addEventListener('submit',async e=>{
 e.preventDefault();
 let btn=document.getElementById('loginBtn');
 if(btn.disabled) return;
 btn.textContent='⏳...'; btn.disabled=true;
 try{
  let fd=new FormData(e.target);
  let r=await fetch('/api/login_public',{method:'POST',body:fd});
  let j=await r.json();
  if(j.ok){ localStorage.setItem('omaia_user',u.value); location.replace('/dash?v=home'); }
  else{ document.getElementById('msg').textContent='خطأ'; btn.textContent='✨ دخول فوري'; btn.disabled=false; }
 }catch{ btn.textContent='✨ دخول فوري'; btn.disabled=false; }
});
</script></body></html>"""

@app.route('/logout')
def lo():
    session.clear()
    return redirect('/login')

@app.route('/api/logout',methods=['POST'])
def api_logout():
    session.clear()
    return jsonify(ok=True)

@app.route('/dash')
@login_required
def dash():
    v=request.args.get('v','home')
    return layout(page_content(v),v)

@app.route('/api/page')
@login_required
def ap():
    v=request.args.get('v','home').split('&')[0]
    return page_content(v)

@app.route('/api/search')
@login_required
def s():
    q=request.args.get('q','').strip()
    if not q:
        return jsonify([])
    like="%"+q+"%"
    results=[]
    dish_tbl=get_dish_table()
    try:
        for r in qall(f"SELECT * FROM {dish_tbl} WHERE ip LIKE? OR dish_name LIKE? ORDER BY id DESC LIMIT 20",(like,like)):
            results.append({"title":r.get('dish_name') or r.get('ip'),"sub":r.get('ip',''),"page":"dishes"})
        for r in qall("SELECT * FROM towers WHERE name LIKE? ORDER BY id DESC LIMIT 15",(like,)):
            results.append({"title":r.get('name',''),"sub":r.get('area',''),"page":"towers"})
        for r in qall("SELECT * FROM subs WHERE name LIKE? ORDER BY id DESC LIMIT 15",(like,)):
            results.append({"title":r.get('name',''),"sub":r.get('phone',''),"page":"subs"})
    except:
        pass
    return jsonify(results[:25])

@app.route('/add_dish',methods=['POST'])
@login_required
def ad():
    dish_tbl=get_dish_table()
    ip=request.form.get('ip','').strip()
    name=request.form.get('dish_name','').strip()
    loc=request.form.get('location','').strip()
    if not ip or not is_valid_ip(ip):
        return "IP غير صالح",400
    ex=qone(f"SELECT * FROM {dish_tbl} WHERE ip=?",(ip,))
    if ex:
        qexec(f"UPDATE {dish_tbl} SET dish_name=?,location=? WHERE ip=?",(name,loc,ip))
    else:
        qexec(f"INSERT INTO {dish_tbl}(ip,location,dish_name) VALUES(?,?,?)",(ip,loc,name))
    add_log("اضافة صحن",f"{name} {ip}")
    return "ok"

@app.route('/edit_dish/<int:i>',methods=['POST'])
@login_required
def ed(i):
    if not is_manager():
        return "ممنوع",403
    qexec(f"UPDATE {get_dish_table()} SET dish_name=?,ip=?,location=? WHERE id=?",(request.form.get('dish_name',''),request.form.get('ip',''),request.form.get('location',''),i))
    add_log("تعديل صحن",str(i))
    return "ok"

@app.route('/del_dish/<int:i>')
@login_required
def dd(i):
    if not is_manager():
        return "ممنوع",403
    qexec(f"DELETE FROM {get_dish_table()} WHERE id=?",(i,))
    add_log("حذف صحن",str(i))
    return "ok"

@app.route('/add_tower',methods=['POST'])
@login_required
def at():
    try:
        la=float(request.form.get('lat') or 35.1318)
        ln=float(request.form.get('lng') or 36.7578)
    except:
        la=35.1318
        ln=36.7578
    qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",(request.form.get('name',''),request.form.get('area',''),la,ln))
    add_log("اضافة برج",request.form.get('name',''))
    return "ok"

@app.route('/del_tower/<int:i>')
@login_required
def dt(i):
    if not is_manager():
        return "ممنوع",403
    qexec("DELETE FROM towers WHERE id=?",(i,))
    add_log("حذف برج",str(i))
    return "ok"

@app.route('/edit_tower/<int:i>',methods=['POST'])
@login_required
def et(i):
    if not is_manager():
        return "ممنوع",403
    try:
        la=float(request.form.get('lat') or 35.1318)
        ln=float(request.form.get('lng') or 36.7578)
    except:
        la=35.1318
        ln=36.7578
    qexec("UPDATE towers SET name=?,area=?,lat=?,lng=? WHERE id=?",(request.form.get('name',''),request.form.get('area',''),la,ln,i))
    add_log("تعديل برج",str(i))
    return "ok"

@app.route('/add_sub',methods=['POST'])
@login_required
def asub():
    qexec("INSERT INTO subs(name,phone,note) VALUES(?,?,?)",(request.form.get('name',''),request.form.get('phone',''),request.form.get('note','')))
    add_log("اضافة مشترك",request.form.get('name',''))
    return "ok"

@app.route('/del_sub/<int:i>')
@login_required
def dsub(i):
    if not is_manager():
        return "ممنوع",403
    qexec("DELETE FROM subs WHERE id=?",(i,))
    add_log("حذف مشترك",str(i))
    return "ok"

@app.route('/edit_sub/<int:i>',methods=['POST'])
@login_required
def esub(i):
    if not is_manager():
        return "ممنوع",403
    qexec("UPDATE subs SET name=?,phone=?,note=? WHERE id=?",(request.form.get('name',''),request.form.get('phone',''),request.form.get('note',''),i))
    add_log("تعديل مشترك",str(i))
    return "ok"

@app.route('/add_ledger',methods=['POST'])
@login_required
def al():
    try:
        amt=float(request.form.get('amount') or 0)
    except:
        amt=0
    qexec("INSERT INTO ledger(name,amount,note,currency) VALUES(?,?,?,?)",(request.form.get('name',''),amt,request.form.get('note',''),request.form.get('currency','USD')))
    add_log("اضافة حساب",request.form.get('name',''))
    return "ok"

@app.route('/del_ledger/<int:i>')
@login_required
def dll(i):
    if not is_manager():
        return "ممنوع",403
    qexec("DELETE FROM ledger WHERE id=?",(i,))
    return "ok"

@app.route('/edit_ledger/<int:i>',methods=['POST'])
@login_required
def el(i):
    if not is_manager():
        return "ممنوع",403
    try:
        amt=float(request.form.get('amount') or 0)
    except:
        amt=0
    qexec("UPDATE ledger SET name=?,amount=?,note=?,currency=? WHERE id=?",(request.form.get('name',''),amt,request.form.get('note',''),request.form.get('currency','USD'),i))
    return "ok"

@app.route('/add_user',methods=['POST'])
@login_required
@role_required_manager
def au():
    ph=request.form.get('phone','').strip() or request.form.get('user_field','').strip()
    if not ph or qone("SELECT * FROM users WHERE phone=?",(ph,)):
        return "موجود",400
    qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",(ph,generate_password_hash(request.form.get('password','1234')),request.form.get('role','tech'),ph))
    add_log("اضافة يوزر",ph)
    return "ok"

@app.route('/edit_user',methods=['POST'])
@login_required
@role_required_manager
def eu():
    old=request.form.get('old_phone','').strip()
    new_ph=request.form.get('phone','').strip() or request.form.get('user_field','').strip()
    new_role=request.form.get('role','tech')
    new_pass=request.form.get('password','').strip()
    if not old:
        return "خطأ",400
    if new_pass:
        qexec("UPDATE users SET phone=?,username=?,role=?,password=? WHERE phone=?",(new_ph,new_ph,new_role,generate_password_hash(new_pass),old))
    else:
        qexec("UPDATE users SET phone=?,username=?,role=? WHERE phone=?",(new_ph,new_ph,new_role,old))
    if session.get('phone')==old:
        session['phone']=new_ph
    add_log("تعديل يوزر",new_ph)
    return "ok"

@app.route('/del_user/<ph>')
@login_required
@role_required_manager
def du(ph):
    if ph=='05344851045':
        return "ممنوع",400
    qexec("DELETE FROM users WHERE phone=?",(ph,))
    add_log("حذف يوزر",ph)
    return "ok"

@app.route('/change_pass',methods=['POST'])
@login_required
def cp():
    np=request.form.get('newpass','').strip()
    if not np:
        return "فارغة",400
    qexec("UPDATE users SET password=? WHERE phone=?",(generate_password_hash(np),session.get('phone')))
    return "ok"

def page_content(v):
    dish_tbl=get_dish_table()
    if v=='home':
        st=get_home_stats()
        logs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 5")
        log_html="".join([f"<div style='padding:6px 8px;border-bottom:1px dashed #ffffff10'><b style='color:#ffbe4d'>{esc(l.get('user_phone',''))}</b> {esc(l.get('action',''))} <small style='color:#777'>{esc(l.get('time',''))}</small></div>" for l in logs])
        return f'''<div style='max-width:900px;margin:0 auto'><div style='display:grid;grid-template-columns:1fr 1fr;gap:12px'>
        <div class='card' onclick="loadPage('subs')" style='cursor:pointer'><h3 style='margin:0;color:#aab4d0;font-size:12px'>المشتركين</h3><h2 style='margin:4px 0;font-size:32px'>{st.get('subs',0)}</h2></div>
        <div class='card' onclick="loadPage('dishes')" style='cursor:pointer'><h3 style='margin:0;color:#aab4d0;font-size:12px'>الصحون</h3><h2 style='margin:4px 0;font-size:32px'>{st.get('dishes',0)}</h2></div>
        <div class='card' onclick="loadPage('towers')" style='cursor:pointer'><h3 style='margin:0;color:#aab4d0;font-size:12px'>الأبراج</h3><h2 style='margin:4px 0;font-size:32px'>{st.get('towers',0)}</h2></div>
        <div class='card' onclick="loadPage('ledger')" style='cursor:pointer'><h3 style='margin:0;color:#aab4d0;font-size:12px'>الحسابات</h3><h2 style='margin:4px 0;font-size:32px'>{st.get('ledger',0)}</h2></div></div>
        <div class=card><h4>📜 آخر النشاطات</h4>{log_html or 'لا يوجد'}<button class=btn-gold onclick="loadPage('logs')" style='width:100%;margin-top:8px'>عرض السجل</button></div></div>'''
    if v=='ping':
        return f'''<div style='max-width:800px;margin:0 auto'><div class=card><h3>📶 بنج نار - {dish_tbl}</h3>
        <div style='display:flex;gap:8px'><input id=pingIp placeholder='192.168.1.1' style='flex:1;padding:12px;background:#0f1424;border:1px solid #ffffff20;color:#fff;border-radius:10px'><button class=btn-gold onclick="window.doSinglePing()">Ping</button></div>
        <div id=pingResult style='margin-top:10px;padding:12px;background:#0008;border-radius:10px'>جاهز...</div></div>
        <div class=card><h4>صحون سريعة - اضغط IP يفتح بكروم</h4><div id=quickDishes>⏳</div></div></div><script>
        window.doSinglePing=async function(){{let ip=document.getElementById('pingIp').value.trim(); if(!ip) return; let o=document.getElementById('pingResult'); o.textContent='⏳ '+ip; try{{let r=await fetch('/api/ping?ip='+encodeURIComponent(ip)); let j=await r.json(); o.textContent=j.out; o.style.color=j.ok?'#22c55e':'#ef4444';}}catch(e){{o.textContent='❌ '+e;}}}}
        (async()=>{{try{{let r=await fetch('/api/search?q=192'); let d=await r.json(); let h=''; d.filter(x=>x.page==='dishes').slice(0,8).forEach(x=>{{h+='<div style="display:flex;justify-content:space-between;padding:8px;border-bottom:1px solid #ffffff08"><a href="http://'+x.sub+'" target="_blank" style="color:#ffbe4d;text-decoration:none">🌐 '+x.sub+'</a><button class=btn-gold onclick="document.getElementById(\\'pingIp\\').value=\\''+x.sub+'\\';window.doSinglePing()">Ping</button></div>';}}); document.getElementById('quickDishes').innerHTML=h;}}catch(e){{}}}})();
        </script>'''
    if v=='dishes':
        rs=qall(f"SELECT * FROM {dish_tbl} ORDER BY id DESC LIMIT 100")
        rows=""
        for r in rs:
            dn=esc(r.get('dish_name') or 'صحن')
            ip=esc(r.get('ip') or '')
            loc=esc(r.get('location') or '')
            rid=r['id']
            rows+=f'<div class="card" id="dish-{rid}" data-name="{dn}" data-ip="{ip}" data-loc="{loc}" style="display:flex;justify-content:space-between"><div><b>{dn}</b><br><a href="http://{ip}" target="_blank" style="color:#ffbe4d;text-decoration:none;background:#000;padding:4px 8px;border-radius:8px">🌐 {ip}</a><br><small style="color:#888">{loc}</small></div><div style="display:flex;gap:6px"><button class=btn-gold onclick="window.editDish({rid})">✏</button><button class=btn-del onclick="askDel(\'/del_dish/{rid}\')">🗑</button></div></div>'
        return f'''<div style='max-width:900px;margin:0 auto'><div class=card><h3>📡 الصحون - {len(rs)}</h3><form data-ajax method=post action=/add_dish style='display:flex;gap:6px;flex-wrap:wrap'><input name=dish_name placeholder='اسم' required style='flex:1'><input name=ip placeholder='IP' required style='flex:1'><input name=location placeholder='موقع' style='flex:1'><button class=btn-gold>➕ فوري</button></form><input id=searchBox placeholder='🔍 بحث فوري...' oninput="window.searchDishes(this.value)" style='margin-top:10px;width:100%;padding:12px;border-radius:12px;background:#0f1424;border:1px solid #ffffff18'></div><div id=dl>{rows}</div></div><script>
        window.editDish=function(id){{let c=document.getElementById('dish-'+id); let m=document.getElementById('editModal'); m.classList.add('show'); document.getElementById('editBody').innerHTML='<input id=ed_n value="'+c.dataset.name+'" style="width:100%;padding:10px;margin:4px 0"><input id=ed_ip value="'+c.dataset.ip+'" style="width:100%;padding:10px;margin:4px 0"><input id=ed_l value="'+c.dataset.loc+'" style="width:100%;padding:10px;margin:4px 0"><button onclick="window.saveDish('+id+')" class=btn-gold style="width:100%;padding:10px">💾 حفظ</button>';}}
        window.saveDish=function(id){{let nn=document.getElementById('ed_n').value; let ii=document.getElementById('ed_ip').value; let ll=document.getElementById('ed_l').value; fetch('/edit_dish/'+id,{{method:'POST',body:new URLSearchParams({{dish_name:nn,ip:ii,location:ll}})}}).then(()=>{{window.closeEditModal(); loadPage('dishes',true);}});}}
        window.searchDishes=function(q){{q=(q||'').toLowerCase(); document.querySelectorAll('[id^=dish-]').forEach(card=>{{let t=(card.dataset.name+card.dataset.ip+card.dataset.loc).toLowerCase(); card.style.display=t.includes(q)?'flex':'none';}});}}
        </script>'''
    if v=='towers':
        rs=qall("SELECT * FROM towers ORDER BY id DESC LIMIT 100")
        rows="".join([f'<div class="card" id="tower-{r["id"]}" data-name="{esc(r["name"])}" data-area="{esc(r["area"] or "")}" data-lat="{r.get("lat") or 0}" data-lng="{r.get("lng") or 0}" style="display:flex;justify-content:space-between"><div><b>🗼 {esc(r["name"])}</b><br><small>{esc(r["area"] or "")}</small></div><div><button class=btn-gold onclick="window.openEditTower({r["id"]})">✏</button> <button class=btn-del onclick="askDel(\'/del_tower/{r["id"]}\')">🗑</button></div></div>' for r in rs])
        return f'''<div style='max-width:700px;margin:0 auto'><div class=card><h3>🗼 الأبراج</h3><form data-ajax method=post action=/add_tower style='display:flex;gap:6px;flex-wrap:wrap'><input name=name placeholder='اسم' required style='flex:1'><input name=area placeholder='منطقة' style='flex:1'><input name=lat placeholder='lat' style='width:80px'><input name=lng placeholder='lng' style='width:80px'><button class=btn-gold>➕ فوري</button></form></div>{rows}</div><script>
        window.openEditTower=function(id){{let c=document.getElementById('tower-'+id); let m=document.getElementById('editModal'); m.classList.add('show'); document.getElementById('editBody').innerHTML='<input id=et_n value="'+c.dataset.name+'" style="width:100%;padding:10px"><input id=et_a value="'+c.dataset.area+'" style="width:100%;padding:10px;margin-top:6px"><input id=et_lat value="'+c.dataset.lat+'" style="width:100%;padding:10px;margin-top:6px"><input id=et_lng value="'+c.dataset.lng+'" style="width:100%;padding:10px;margin-top:6px"><button onclick="window.saveTower('+id+')" class=btn-gold style="width:100%;margin-top:8px">حفظ</button>';}}
        window.saveTower=function(id){{let n=document.getElementById('et_n').value; let a=document.getElementById('et_a').value; let la=document.getElementById('et_lat').value; let ln=document.getElementById('et_lng').value; fetch('/edit_tower/'+id,{{method:'POST',body:new URLSearchParams({{name:n,area:a,lat:la,lng:ln}})}}).then(()=>{{window.closeEditModal(); loadPage('towers',true);}});}}
        </script>'''
    if v=='subs':
        rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 100")
        rows="".join([f'<div class="card" id="sub-{r["id"]}" data-name="{esc(r["name"])}" data-phone="{esc(r["phone"] or "")}" style="display:flex;justify-content:space-between"><div><b>{esc(r["name"])}</b><br>{esc(r["phone"] or "")}</div><div><button class=btn-gold onclick="window.openEditSub({r["id"]})">✏</button> <button class=btn-del onclick="askDel(\'/del_sub/{r["id"]}\')">🗑</button></div></div>' for r in rs])
        return f'''<div style='max-width:700px;margin:0 auto'><div class=card><h3>👥 المشتركين</h3><form data-ajax method=post action=/add_sub style='display:flex;gap:5px'><input name=name placeholder='الاسم' required style='flex:1'><input name=phone placeholder='رقم' style='flex:1'><button class=btn-gold>➕ فوري</button></form></div>{rows}</div><script>
        window.openEditSub=function(id){{let c=document.getElementById('sub-'+id); let m=document.getElementById('editModal'); m.classList.add('show'); document.getElementById('editBody').innerHTML='<input id=es_n value="'+c.dataset.name+'" style="width:100%;padding:10px"><input id=es_p value="'+c.dataset.phone+'" style="width:100%;padding:10px;margin-top:6px"><button onclick="window.saveSub('+id+')" class=btn-gold style="width:100%;margin-top:8px">حفظ</button>';}}
        window.saveSub=function(id){{let n=document.getElementById('es_n').value; let p=document.getElementById('es_p').value; fetch('/edit_sub/'+id,{{method:'POST',body:new URLSearchParams({{name:n,phone:p,note:''}})}}).then(()=>{{window.closeEditModal(); loadPage('subs',true);}});}}
        </script>'''
    if v=='ledger':
        rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 100")
        rows="".join([f'<div class="card" id="led-{r["id"]}" data-name="{esc(r["name"])}" data-amount="{r["amount"]}" style="display:flex;justify-content:space-between"><div>{esc(r["name"])} - <b style="color:#ffbe4d">{r["amount"]}</b></div><div><button class=btn-gold onclick="window.openEditLed({r["id"]})">✏</button> <button class=btn-del onclick="askDel(\'/del_ledger/{r["id"]}\')">🗑</button></div></div>' for r in rs])
        return f'''<div style='max-width:700px;margin:0 auto'><div class=card><h3>📒 الحسابات</h3><form data-ajax method=post action=/add_ledger style='display:flex;gap:5px'><input name=name placeholder='الاسم' required style='flex:1'><input name=amount type=number step=0.01 placeholder='المبلغ' required style='flex:1'><button class=btn-gold>➕ فوري</button></form></div>{rows}</div><script>
        window.openEditLed=function(id){{let c=document.getElementById('led-'+id); let m=document.getElementById('editModal'); m.classList.add('show'); document.getElementById('editBody').innerHTML='<input id=el_n value="'+c.dataset.name+'" style="width:100%;padding:10px"><input id=el_a value="'+c.dataset.amount+'" style="width:100%;padding:10px;margin-top:6px"><button onclick="window.saveLed('+id+')" class=btn-gold style="width:100%;margin-top:8px">حفظ</button>';}}
        window.saveLed=function(id){{let n=document.getElementById('el_n').value; let a=document.getElementById('el_a').value; fetch('/edit_ledger/'+id,{{method:'POST',body:new URLSearchParams({{name:n,amount:a,note:'',currency:'USD'}})}}).then(()=>{{window.closeEditModal(); loadPage('ledger',true);}});}}
        </script>'''
    if v=='logs':
        rs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 500")
        rows="".join([f"<div class='card' style='font-size:13px;border-right:3px solid #ffbe4d'><b style='color:#ffbe4d'>{esc(r.get('user_phone',''))}</b> {esc(r.get('action',''))} - {esc(r.get('detail',''))}<br><small style='color:#777'>{esc(r.get('time',''))}</small></div>" for r in rs])
        return f"<div style='max-width:900px;margin:0 auto'><div class=card style='display:flex;justify-content:space-between'><h3>📜 السجل الكامل - {len(rs)}</h3><a href='/api/export/logs' class=btn-gold style='text-decoration:none'>📗 Excel</a></div>{rows or '<div class=card>لا يوجد سجل - سيظهر هنا بعد أي عملية</div>'}</div>"
    if v=='network':
        dishes=qall(f"SELECT * FROM {get_dish_table()} ORDER BY id DESC LIMIT 80")
        rows="".join([f"<div class='card' id='net-{d['id']}' data-ip='{esc(d.get('ip',''))}' style='display:flex;justify-content:space-between'><div><b>{esc(d.get('dish_name') or 'صحن')}</b> - <a href='http://{esc(d.get('ip',''))}' target='_blank' style='color:#ffbe4d'>{esc(d.get('ip',''))}</a><br><small class='net-out'>⏳</small></div><button class=btn-gold onclick='window.checkOne({d['id']})'>📶</button></div>" for d in dishes])
        return f'''<div style='max-width:800px;margin:0 auto'><div class=card><h3>📊 الشبكة LIVE</h3><button class=btn-gold onclick='window.checkAll()' style='width:100%;background:#22c55e;color:#fff;padding:12px'>🚀 فحص الكل</button></div>{rows}<script>
        window.checkOne=async function(id){{let c=document.getElementById('net-'+id); let o=c.querySelector('.net-out'); o.textContent='⏳'; try{{let r=await fetch('/api/ping?ip='+c.dataset.ip); let j=await r.json(); o.textContent=j.out; o.style.color=j.ok?'#22c55e':'#ef4444';}}catch(e){{o.textContent='❌';}}}}
        window.checkAll=async function(){{for(let c of document.querySelectorAll('[id^=net-]')){{window.checkOne(c.id.split('-')[1]); await new Promise(r=>setTimeout(r,120));}}}}
        </script></div>'''
    if v=='map':
        towers=qall("SELECT * FROM towers")
        tj=json.dumps([{"name":t['name'],"area":t.get('area') or '',"lat":float(t.get('lat') or 35.1318),"lng":float(t.get('lng') or 36.7578)} for t in towers],ensure_ascii=False)
        return f'''<div class=card style='padding:10px'><div style='display:flex;gap:6px;margin-bottom:8px;flex-wrap:wrap'>
        <input id=mapSearch placeholder='🔍 بحث برج...' style='flex:1;min-width:140px;padding:10px;border-radius:10px;background:#1f2937;border:1px solid #ffffff15;color:#fff'>
        <button class=btn-gold onclick="window.doMapSearch()">🔍 بحث</button>
        <button class=btn-gold onclick="window.locateMe()" style='background:#22c55e;color:#fff'>📍 موقعي</button>
        <button class=btn-gold onclick="window.toggleAddPoint()" id=addPointBtn style='background:#f59e0b;color:#fff'>➕ نقطة</button>
        <span id=coordsLabel style='color:#ffbe4d;font-size:12px'>📍 -</span></div><div id=map style='height:75vh;min-height:500px;border-radius:14px;background:#0f172a'></div></div><script>
        let _towers={tj}; let _map=null; let addPointMode=false;
        window.doMapSearch=function(){{let q=document.getElementById('mapSearch').value.trim().toLowerCase(); if(!q) return; let f=_towers.find(t=>t.name.toLowerCase().includes(q)); if(f && _map){{_map.flyTo([f.lat,f.lng],17);}}}}
        window.locateMe=function(){{if(_map && navigator.geolocation) navigator.geolocation.getCurrentPosition(p=>{{_map.flyTo([p.coords.latitude,p.coords.longitude],16);}});}}
        window.toggleAddPoint=function(){{addPointMode=!addPointMode; let b=document.getElementById('addPointBtn'); b.textContent=addPointMode?'✅ اضغط الخريطة':'➕ نقطة';}}
        function initMap(){{if(typeof L==='undefined'){{setTimeout(initMap,200);return;}} _map=L.map('map').setView([35.1318,36.7578],13); let osm=L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png').addTo(_map); let sat=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}').addTo(_map); L.control.layers({{"عادية":osm,"قمر صناعي":sat}}).addTo(_map); _towers.forEach(t=>{{L.marker([t.lat,t.lng]).addTo(_map).bindPopup(t.name);}}); _map.on('click',e=>{{document.getElementById('coordsLabel').textContent='📍 '+e.latlng.lat.toFixed(4)+','+e.latlng.lng.toFixed(4); if(addPointMode){{let lat=e.latlng.lat.toFixed(6), lng=e.latlng.lng.toFixed(6); let name=prompt('اسم النقطة؟')||'نقطة'; if(name){{fetch('/add_tower',{{method:'POST',body:new URLSearchParams({{name:name,area:'',lat:lat,lng:lng}})}}).then(()=>{{loadPage('map',true);}});}}}}}}); setTimeout(()=>_map.invalidateSize(),300);}}
        initMap();
        </script>'''
    if v=='support':
        return """<div style='max-width:600px;margin:0 auto;text-align:center'><div class=card><h2>🛠 الدعم الفني</h2>
        <a href='https://wa.me/905345851045' target=_blank style='display:block;background:#22c55e;color:#fff;padding:14px;border-radius:12px;text-decoration:none;margin:8px 0;font-weight:800'>💬 واتساب +90 534 485 10 45</a>
        <a href='https://instagram.com/af_20_1999' target=_blank style='display:block;background:linear-gradient(90deg,#e1306c,#f77737);color:#fff;padding:12px;border-radius:12px;text-decoration:none;margin:8px 0'>📸 af_20_1999</a>
        </div></div>"""
    if v=='settings':
        us=qall("SELECT * FROM users ORDER BY phone DESC")
        uh="".join([f'<div class="card" id="user-{esc(u["phone"])}" data-phone="{esc(u["phone"])}" data-role="{esc(u.get("role") or "")}" style="display:flex;justify-content:space-between"><div>{esc(u.get("username") or "")} - {esc(u["phone"])}</div><div><button class=btn-gold onclick="window.openEditUser(\'{esc(u["phone"])}\')">✏</button> <button class=btn-del onclick="askDel(\'/del_user/{esc(u["phone"])}\')">🗑</button></div></div>' for u in us])
        return f'''<div style='max-width:800px;margin:0 auto'><div style='display:grid;grid-template-columns:1fr 1fr;gap:10px'>
        <div class=card><h4>🌐 اللغة</h4><button onclick="window.toggleLang()" class=btn-gold style='width:100%'>🌐 تبديل لغة</button></div>
        <div class=card><h4>🎨 المظهر</h4><button onclick="window.toggleTheme()" class=btn-gold style='width:100%'>🌓 ليل/نهار</button></div></div>
        <div class=card><h3>👤 اضافة يوزر</h3><form data-ajax method=post action=/add_user style='display:flex;gap:6px'><input name=user_field placeholder='رقم' required style='flex:1'><input name=password type=password placeholder='باسورد' required style='flex:1'><select name=role style='width:90px'><option value=tech>فني</option><option value=manager>مدير</option></select><button class=btn-gold>➕ فوري</button></form></div>{uh}</div><script>
        window.openEditUser=function(ph){{let c=document.getElementById('user-'+ph); let m=document.getElementById('editModal'); m.classList.add('show'); document.getElementById('editBody').innerHTML='<input id=eu_p value="'+c.dataset.phone+'" style="width:100%;padding:10px"><input id=eu_pass type="password" placeholder="باسورد جديد" style="width:100%;padding:10px;margin-top:6px"><select id=eu_r style="width:100%;padding:10px;margin-top:6px"><option value="tech">فني</option><option value="manager">مدير</option></select><button onclick="window.saveU(\\''+ph+'\\')" class=btn-gold style="width:100%;margin-top:8px">حفظ</button>'; document.getElementById('eu_r').value=c.dataset.role;}}
        window.saveU=function(oldPh){{let np=document.getElementById('eu_p').value.trim(); let pw=document.getElementById('eu_pass').value.trim(); let r=document.getElementById('eu_r').value; let d={{old_phone:oldPh,phone:np,role:r}}; if(pw) d.password=pw; fetch('/edit_user',{{method:'POST',body:new URLSearchParams(d)}}).then(()=>{{window.closeEditModal(); loadPage('settings',true);}});}}
        </script>'''
    if v=='search':
        q=request.args.get('q','').strip()
        if not q:
            return "<div class=card>اكتب كلمة بحث</div>"
        like="%"+q+"%"
        results=[]
        dish_tbl=get_dish_table()
        for r in qall(f"SELECT * FROM {dish_tbl} WHERE ip LIKE? OR dish_name LIKE? LIMIT 20",(like,like)):
            results.append(f"<div class=card><b>{esc(r.get('dish_name') or '')}</b> - <a href='http://{esc(r.get('ip') or '')}' target='_blank' style='color:#ffbe4d'>{esc(r.get('ip') or '')}</a></div>")
        for r in qall("SELECT * FROM towers WHERE name LIKE? LIMIT 20",(like,)):
            results.append(f"<div class=card>🗼 {esc(r['name'])} - {esc(r.get('area') or '')}</div>")
        return f"<div style='max-width:800px;margin:0 auto'><div class=card><h3>🔍 نتائج: {esc(q)} ({len(results)})</h3></div>{''.join(results) or '<div class=card>لا يوجد</div>'}</div>"
    return "<div class=card>ok</div>"

def layout(c,v='home'):
    cur_user=qone("SELECT * FROM users WHERE phone=?",(session.get('phone') or '',))
    role=(cur_user.get('role') or 'tech') if cur_user else 'tech'
    return f"""<html dir=rtl lang=ar><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<link rel=stylesheet href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'>
<style>
*{{box-sizing:border-box;font-family:system-ui}}body{{margin:0;background:#0a0e2a;color:#fff;overflow-x:hidden}}
.top{{position:fixed;top:0;left:0;right:0;height:60px;background:rgba(15,23,42,0.92);backdrop-filter:blur(12px);color:#fff;display:flex;align-items:center;justify-content:space-between;padding:0 12px;z-index:1003;border-bottom:1px solid #ffffff12}}
.top-left{{display:flex;gap:8px;align-items:center}}
.top-center{{font-weight:900}}
.top-right{{display:flex;gap:8px;align-items:center}}
.sidebar{{position:fixed;right:0;top:0;width:280px;height:100%;background:linear-gradient(180deg,#0f172a 0%,#0a1220 100%);z-index:1002;padding-top:70px;transform:translateX(110%);transition:transform 0.45s cubic-bezier(0.4,0,0.2,1);overflow-y:auto}}
.sidebar.active{{transform:none;box-shadow:-12px 0 50px #0008}}
.sidebar a{{display:flex;gap:10px;padding:12px 14px;margin:6px 10px;color:#cbd5e1;text-decoration:none;border-radius:12px;background:#ffffff06;transition:all 0.35s cubic-bezier(0.4,0,0.2,1)}}
.sidebar a:hover{{background:#ffffff12;transform:translateX(-6px)}}
.sidebar a.active{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:800}}
#overlay{{position:fixed;inset:0;background:#0009;z-index:1001;display:none;opacity:0;transition:opacity 0.4s}}#overlay.show{{display:block;opacity:1}}
.main{{margin-top:70px;padding:12px;transition:opacity 0.25s}}
.card{{background:#1e2433;padding:14px;border-radius:14px;margin-bottom:10px;border:1px solid #ffffff12;transition:transform 0.3s cubic-bezier(0.4,0,0.2,1), box-shadow 0.3s}}
.card:hover{{transform:translateY(-2px);box-shadow:0 8px 24px #0004}}
input,select{{padding:11px;margin:5px 0;border-radius:10px;border:1px solid #ffffff12;width:100%;background:#ffffff07;color:#fff}}
.btn-gold{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;padding:8px 14px;border:0;border-radius:10px;font-weight:800;cursor:pointer;transition:all 0.25s}}
.btn-del{{background:#ef4444;color:#fff;padding:7px 11px;border:0;border-radius:10px}}
#delModal,#editModal{{position:fixed;inset:0;background:#000a;backdrop-filter:blur(8px);display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:opacity 0.35s;z-index:2000}}#delModal.show,#editModal.show{{opacity:1;pointer-events:auto}}
#delBox,#editBox{{background:#1e2433;padding:20px;border-radius:16px;width:
