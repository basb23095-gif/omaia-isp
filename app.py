from flask import Flask, request, redirect, session, jsonify, Response
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, html, ipaddress, subprocess, json, socket, platform, io, csv, datetime, re, threading, time, secrets
from concurrent.futures import ThreadPoolExecutor, as_completed
try:
    import psycopg2, psycopg2.extras
    from psycopg2 import pool as pg_pool
except:
    psycopg2=None
    pg_pool=None
import sqlite3

app=Flask(__name__)
# === FIX: لا تستخدم مفتاح ثابت، و SESSION لا تكون دائمة ===
_secret = os.environ.get("SECRET_KEY")
if not _secret:
    _secret = "dev-only-" + secrets.token_hex(32)
app.secret_key=_secret
app.config['PERMANENT_SESSION_LIFETIME']=datetime.timedelta(hours=2)
app.config['SESSION_PERMANENT']=False
app.config['SESSION_COOKIE_HTTPONLY']=True
app.config['SESSION_COOKIE_SAMESITE']='Lax'

DATABASE_URL=os.environ.get("DATABASE_URL","").strip().replace("postgresql://","postgres://")
USE_PG=bool(DATABASE_URL.startswith("postgres://") and psycopg2)

_pg_pool=None
_pool_lock=threading.Lock()
_sqlite_conn=None
_sqlite_lock=threading.Lock()
_cache={}
_cache_lock=threading.Lock()

def init_pool():
    global _pg_pool
    if not USE_PG or not pg_pool: return
    with _pool_lock:
        if _pg_pool: return
        try:
            _pg_pool=pg_pool.ThreadedConnectionPool(1,20,dsn=DATABASE_URL,sslmode='require',connect_timeout=3)
        except Exception as e:
            print(f"[POOL] {e}")
            _pg_pool=None
init_pool()

def esc(s): return html.escape(str(s or ''), quote=True)

def get_conn():
    if USE_PG and _pg_pool:
        try: return _pg_pool.getconn()
        except: return psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=3)
    elif USE_PG:
        try: return psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=3)
        except: pass
    global _sqlite_conn
    with _sqlite_lock:
        if _sqlite_conn is None:
            try:
                _sqlite_conn=sqlite3.connect("omia.db",check_same_thread=False,timeout=15)
                _sqlite_conn.row_factory=sqlite3.Row
                _sqlite_conn.execute("PRAGMA journal_mode=WAL;")
            except:
                _sqlite_conn=sqlite3.connect(":memory:",check_same_thread=False)
                _sqlite_conn.row_factory=sqlite3.Row
        return _sqlite_conn

def put_conn(conn):
    if USE_PG and _pg_pool:
        try: _pg_pool.putconn(conn)
        except:
            try: conn.close()
            except: pass
    elif USE_PG:
        try: conn.close()
        except: pass

def qall(q,a=()):
    conn=None
    try:
        conn=get_conn()
        if USE_PG:
            cur=conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(q.replace("?","%s"),a)
            rs=[dict(r) for r in cur.fetchall()]
            cur.close()
            put_conn(conn)
            return rs
        else:
            with _sqlite_lock:
                rs=[dict(r) for r in conn.execute(q,a).fetchall()]
                return rs
    except Exception as e:
        print(f"[qall] {e}")
        if conn and USE_PG:
            try: put_conn(conn)
            except: pass
        return []

def qone(q,a=()):
    r=qall(q,a)
    return r[0] if r else None

def qexec(q,a=()):
    conn=None
    try:
        conn=get_conn()
        if USE_PG:
            cur=conn.cursor()
            cur.execute(q.replace("?","%s"),a)
            conn.commit()
            cur.close()
            put_conn(conn)
        else:
            with _sqlite_lock:
                conn.execute(q,a)
                conn.commit()
        return True
    except Exception as e:
        print(f"[qexec] {e}")
        if conn and USE_PG:
            try:
                conn.rollback()
                put_conn(conn)
            except: pass
        return False

# === FIX: السجل كان يشتغل بـ Thread ويخرب SQLite ===
def add_log(phone,action,detail):
    try:
        now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)",(phone or 'unknown',action,detail,now))
        qexec("INSERT INTO notifications(title,msg,time) VALUES(?,?,?)",(action,str(phone)+": "+str(detail),now))
        with _cache_lock:
            _cache.pop('counts',None)
    except Exception as e:
        print(f"[log] {e}")

def get_counts():
    with _cache_lock:
        c=_cache.get('counts')
        if c and time.time()-c[1]<20:
            return c[0]
    try:
        ns=(qone("SELECT COUNT(*) c FROM subs") or {}).get('c',0)
        nd=(qone("SELECT COUNT(*) c FROM dish_ips") or {}).get('c',0)
        nt=(qone("SELECT COUNT(*) c FROM towers") or {}).get('c',0)
        nl=(qone("SELECT COUNT(*) c FROM ledger") or {}).get('c',0)
        data=(ns,nd,nt,nl)
        with _cache_lock:
            _cache['counts']=(data,time.time())
        return data
    except:
        return (0,0,0,0)

def init():
    ss=[
        "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,username TEXT)",
        "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,note TEXT)",
        "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,amount REAL,note TEXT,currency TEXT)",
        "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,dish_name TEXT)",
        "CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,area TEXT,lat REAL,lng REAL)",
        "CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,user_phone TEXT,action TEXT,detail TEXT,time TEXT)",
        "CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,msg TEXT,time TEXT,read INTEGER DEFAULT 0)"
    ]
    if USE_PG:
        ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
    for s in ss:
        qexec(s)
    if USE_PG:
        for idx in ["CREATE INDEX IF NOT EXISTS idx_dish_ips_ip ON dish_ips(ip)", "CREATE UNIQUE INDEX IF NOT EXISTS uq_dish_ips_ip ON dish_ips(ip)", "CREATE INDEX IF NOT EXISTS idx_logs_id ON logs(id DESC)"]:
            try: qexec(idx)
            except: pass
    else:
        for idx in ["CREATE INDEX IF NOT EXISTS idx_dish_ips_ip ON dish_ips(ip)", "CREATE INDEX IF NOT EXISTS idx_towers_name ON towers(name)", "CREATE INDEX IF NOT EXISTS idx_logs_id ON logs(id DESC)"]:
            try: qexec(idx)
            except: pass
    if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",('05344851045',generate_password_hash('admin2024'),'manager','admin'))
    if not qone("SELECT * FROM towers WHERE name=?",('نقطة حماة الرئيسية',)):
        qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",('نقطة حماة الرئيسية','حماة',35.1318,36.7578))
init()

def login_required(f):
    @wraps(f)
    def w(*a,**kw):
        if not session.get('phone'):
            return redirect('/login')
        return f(*a,**kw)
    return w

def is_manager():
    if session.get('role'):
        return session.get('role')=='manager'
    u=qone("SELECT role FROM users WHERE phone=?",(session.get('phone') or '',))
    if not u:
        return False
    session['role']=u.get('role')
    return (u.get('role') or '').lower()=='manager'

def role_required_manager(f):
    @wraps(f)
    def w(*a,**kw):
        if not is_manager():
            return "ممنوع",403
        return f(*a,**kw)
    return w

# === FIX: تحقق IP صارم ===
def is_valid_ip(ip):
    ip=(ip or '').strip()
    if not ip:
        return False
    try:
        ipaddress.ip_address(ip)
        return True
    except:
        return False

@app.after_request
def add_perf_headers(resp):
    if request.path.startswith('/api/'):
        resp.headers['Cache-Control']='no-store, max-age=0'
    else:
        resp.headers['Cache-Control']='no-cache'
    return resp

@app.route('/ping')
@app.route('/health')
def public_ping():
    return jsonify(ok=True,time=datetime.datetime.now().isoformat())

# === FIX: فحص سريع متوازي ===
def _check_port(args):
    ip, port = args
    s=None
    try:
        s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        s.settimeout(0.4)
        ok = s.connect_ex((ip,port))==0
        s.close()
        return (port, ok)
    except:
        try:
            if s: s.close()
        except: pass
        return (port, False)

@app.route('/api/ping')
@login_required
def api_ping():
    ip=request.args.get('ip','').strip()
    if not ip:
        return jsonify(ok=False,out='لا يوجد IP')
    if not is_valid_ip(ip):
        return jsonify(ok=False,out='IP غير صالح')
    # فحص سريع 3 بورتات متوازي بدل 9 تسلسلي
    ports=[80,8291,22]
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures={ex.submit(_check_port,(ip,p)):p for p in ports}
        for f in as_completed(futures):
            port,ok=f.result()
            if ok:
                return jsonify(ok=True,out=f'متصل - {ip}:{port} مفتوح',port=port,method='tcp')
    try:
        cmd=['ping','-c','1','-W','1',ip] if platform.system().lower()!='windows' else ['ping','-n','1','-w','1000',ip]
        out=subprocess.check_output(cmd,timeout=2,stderr=subprocess.STDOUT).decode(errors='ignore')
        ok='ttl=' in out.lower() or 'bytes from' in out.lower() or '1 received' in out.lower()
        if ok:
            m=re.search(r'time[=<]\s*(\d+\.?\d*)',out,re.I)
            ms=m.group(1) if m else ''
            return jsonify(ok=True,out=f'متصل {ip} - {ms}ms',ms=ms,method='icmp')
    except: pass
    return jsonify(ok=False,out=f'{ip} لا يرد')

@app.route('/api/ping_tcp')
@login_required
def api_ping_tcp():
    ip=request.args.get('ip','').strip()
    port_str=request.args.get('port','80').strip()
    try:
        port=int(port_str)
    except:
        return jsonify(ok=False,out='Port غير صالح')
    if not is_valid_ip(ip):
        return jsonify(ok=False,out='IP غير صالح')
    _,ok=_check_port((ip,port))
    return jsonify(ok=ok,out=f'{ip}:{port} مفتوح' if ok else f'{ip}:{port} مغلق')

@app.route('/api/notifications')
@login_required
def api_noti():
    rows=qall("SELECT * FROM notifications ORDER BY id DESC LIMIT 30")
    unread=qone("SELECT COUNT(*) c FROM notifications WHERE read=0")
    cnt=unread.get('c',0) if unread else 0
    return jsonify(rows=rows,unread=cnt)

@app.route('/api/notifications/read',methods=['POST'])
@login_required
def api_noti_read():
    qexec("UPDATE notifications SET read=1")
    return jsonify(ok=True)

@app.route('/api/network_status')
@login_required
def api_network():
    dishes=qall("SELECT * FROM dish_ips ORDER BY id DESC")
    towers=qall("SELECT * FROM towers ORDER BY id DESC")
    subs_cnt=(qone("SELECT COUNT(*) c FROM subs") or {}).get('c',0)
    return jsonify(dishes=len(dishes),towers=len(towers),subs=subs_cnt)

@app.route('/toggle_lang')
@login_required
def toggle_lang_route():
    cur=session.get('lang','ar')
    new='en' if cur=='ar' else 'ar'
    session['lang']=new
    return jsonify(ok=True,lang=new)

@app.route('/api/login_public',methods=['POST'])
def api_login_public():
    uin=request.form.get('userin','').strip()
    pw=request.form.get('password','')
    u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
    if u and check_password_hash(u['password'],pw):
        session['phone']=u['phone']
        session['username']=u.get('username') or u['phone']
        session['role']=u.get('role') or 'tech'
        session.permanent=False
        add_log(u['phone'],'دخل النظام','تسجيل دخول')
        return jsonify(ok=True,role=u.get('role'))
    return jsonify(ok=False,msg='خطأ بالدخول'),401

@app.route('/api/export/<tbl>')
@login_required
def api_export(tbl):
    output=io.StringIO()
    output.write('\ufeff')
    w=csv.writer(output)
    if tbl=='dishes':
        rows=qall("SELECT * FROM dish_ips ORDER BY id DESC")
        w.writerow(['ID','اسم الصحن','IP','الموقع'])
        for r in rows:
            w.writerow([r['id'],r.get('dish_name',''),r.get('ip',''),r.get('location','')])
        fname='dishes.csv'
    elif tbl=='subs':
        rows=qall("SELECT * FROM subs ORDER BY id DESC")
        w.writerow(['ID','الاسم','رقم','ملاحظة'])
        for r in rows:
            w.writerow([r['id'],r.get('name',''),r.get('phone',''),r.get('note','')])
        fname='subs.csv'
    elif tbl=='users':
        rows=qall("SELECT phone,username,role FROM users ORDER BY phone DESC")
        w.writerow(['يوزر/رقم','اسم المستخدم','الرتبة'])
        for r in rows:
            w.writerow([r.get('phone',''),r.get('username',''),r.get('role','')])
        fname='users.csv'
    elif tbl=='towers':
        rows=qall("SELECT * FROM towers ORDER BY id DESC")
        w.writerow(['ID','اسم البرج','المنطقة','lat','lng'])
        for r in rows:
            w.writerow([r['id'],r.get('name',''),r.get('area',''),r.get('lat',''),r.get('lng','')])
        fname='towers.csv'
    elif tbl=='logs':
        rows=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 1000")
        w.writerow(['ID','المستخدم','العملية','التفاصيل','الوقت'])
        for r in rows:
            w.writerow([r['id'],r.get('user_phone',''),r.get('action',''),r.get('detail',''),r.get('time','')])
        fname='logs.csv'
    elif tbl=='ledger':
        rows=qall("SELECT * FROM ledger ORDER BY id DESC")
        w.writerow(['ID','الاسم','المبلغ','ملاحظة','عملة'])
        for r in rows:
            w.writerow([r['id'],r.get('name',''),r.get('amount',''),r.get('note',''),r.get('currency','')])
        fname='ledger.csv'
    else:
        w.writerow(['ID'])
        fname='export.csv'
    return Response(output.getvalue(),mimetype='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename={fname}'})

@app.route('/api/clear_logs',methods=['POST'])
@login_required
@role_required_manager
def clear_logs():
    qexec("DELETE FROM logs")
    with _cache_lock:
        _cache.clear()
    return jsonify(ok=True)

@app.route('/api/seed_log',methods=['POST'])
@login_required
def seed_log():
    now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)",(session.get('phone','test'),'إضافة صحن','192.168.1.10 - صحن تجريبي',now))
    return jsonify(ok=True)

@app.route('/')
def ix():
    return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login')
def login():
    return """<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@700;900&display=swap" rel="stylesheet">
<style>*{box-sizing:border-box;font-family:'Cairo',system-ui}body{margin:0;min-height:100vh;background:radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 55%, #070a1f 100%);display:flex;flex-direction:column;align-items:center;justify-content:center;color:#fff}
.card{background:rgba(34,43,69,0.9);backdrop-filter:blur(14px);border:1px solid #ffffff18;padding:26px;border-radius:22px;width:92%;max-width:380px;transition:all .4s cubic-bezier(0.34, 1.56, 0.64, 1)}
input{width:100%;padding:14px;margin:9px 0;background:#0f1424;border:1px solid #ffffff22;color:#fff;border-radius:14px;font-size:15px;transition:.3s}
input:focus{border-color:#ffbe4d;box-shadow:0 0 0 3px #ffbe4d22;outline:none}
.btn{width:100%;padding:14px;border:0;border-radius:14px;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:900;font-size:17px;cursor:pointer;margin-top:12px;transition:all .4s cubic-bezier(0.34, 1.56, 0.64, 1)}
.btn:hover{transform:scale(1.02)} .btn:active{transform:scale(0.97)}
</style></head><body>
<div style='font-size:28px;font-weight:900;margin-bottom:14px'>OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<div class=card><form id=loginForm><input name=userin id=userin placeholder='رقم / يوزر' required autocomplete=username><input name=password id=password type=password placeholder='كلمة السر' required autocomplete=current-password><button class=btn id=loginBtn>دخول</button><div id=msg style='text-align:center;margin-top:10px;color:#ff6b6b;font-size:13px;min-height:18px'></div></form></div>
<script>
document.getElementById('loginForm').addEventListener('submit',async e=>{
 e.preventDefault();
 let btn=document.getElementById('loginBtn'), msg=document.getElementById('msg');
 if(btn.disabled) return;
 let orig=btn.textContent; btn.textContent='جاري...'; btn.disabled=true; msg.textContent='';
 try{
  let fd=new FormData(e.target);
  let r=await fetch('/api/login_public',{method:'POST',body:fd,cache:'no-store'});
  let j=await r.json();
  if(j.ok){ location.replace('/dash?v=home'); }
  else { msg.textContent=j.msg||'خطأ'; btn.textContent=orig; btn.disabled=false; }
 }catch(err){ msg.textContent='خطأ شبكة'; btn.textContent=orig; btn.disabled=false; }
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
    return layout('<div class=card>جاري التحميل...</div>',v)

@app.route('/api/page')
@login_required
def ap():
    return page_content(request.args.get('v','home'))

@app.route('/api/search')
@login_required
def s():
    q=request.args.get('q','').strip()
    if not q:
        return jsonify([])
    like="%"+q+"%"
    results=[]
    try:
        for r in qall("SELECT * FROM dish_ips WHERE ip LIKE ? OR dish_name LIKE ? OR location LIKE ? ORDER BY id DESC LIMIT 20",(like,like,like)):
            results.append({"title":r.get('dish_name') or r.get('ip') or 'صحن',"sub":r.get('ip',''),"page":"dishes","type":"dish"})
        for r in qall("SELECT * FROM subs WHERE name LIKE ? OR phone LIKE ? ORDER BY id DESC LIMIT 15",(like,like)):
            results.append({"title":r.get('name',''),"sub":r.get('phone',''),"page":"subs","type":"sub"})
        for r in qall("SELECT * FROM towers WHERE name LIKE ? OR area LIKE ? ORDER BY id DESC LIMIT 15",(like,like)):
            results.append({"title":r.get('name',''),"sub":r.get('area',''),"page":"towers","type":"tower"})
        for r in qall("SELECT * FROM users WHERE phone LIKE ? OR username LIKE ? LIMIT 10",(like,like)):
            results.append({"title":r.get('username') or r.get('phone',''),"sub":r.get('phone',''),"page":"settings","type":"user"})
        for r in qall("SELECT * FROM ledger WHERE name LIKE ? OR note LIKE ? ORDER BY id DESC LIMIT 10",(like,like)):
            results.append({"title":r.get('name',''),"sub":str(r.get('amount','')),"page":"ledger","type":"ledger"})
    except: pass
    return jsonify(results[:25])

@app.route('/toggle_theme')
@login_required
def tt():
    cur=session.get('theme','dark')
    session['theme']='light' if cur=='dark' else 'dark'
    return jsonify(ok=True, theme=session['theme'])

@app.route('/add_dish',methods=['POST'])
@login_required
def ad():
    ip=request.form.get('ip','').strip()
    name=request.form.get('dish_name','').strip()
    loc=request.form.get('location','').strip()
    if not ip:
        return jsonify(ok=False,msg="IP مطلوب"),400
    if not is_valid_ip(ip):
        return jsonify(ok=False,msg="IP غير صالح"),400
    phone=session.get('phone','')
    if USE_PG:
        ok=qexec("INSERT INTO dish_ips(ip,location,dish_name) VALUES(?,?,?) ON CONFLICT (ip) DO UPDATE SET dish_name=EXCLUDED.dish_name, location=EXCLUDED.location",(ip,loc,name))
    else:
        ex=qone("SELECT id FROM dish_ips WHERE ip=?",(ip,))
        if ex:
            ok=qexec("UPDATE dish_ips SET dish_name=?,location=? WHERE ip=?",(name,loc,ip))
        else:
            ok=qexec("INSERT INTO dish_ips(ip,location,dish_name) VALUES(?,?,?)",(ip,loc,name))
    if ok:
        add_log(phone,'إضافة صحن',name+" "+ip)
    return jsonify(ok=ok)

@app.route('/edit_dish/<int:i>',methods=['POST'])
@login_required
def ed(i):
    if not is_manager():
        return jsonify(ok=False,msg="ممنوع للفني"),403
    name=request.form.get('dish_name','').strip()
    ip=request.form.get('ip','').strip()
    loc=request.form.get('location','').strip()
    if ip and not is_valid_ip(ip):
        return jsonify(ok=False,msg="IP غير صالح"),400
    ok=qexec("UPDATE dish_ips SET dish_name=?,ip=?,location=? WHERE id=?",(name,ip,loc,i))
    if ok:
        add_log(session.get('phone'),'تعديل صحن',f"ID {i} -> {ip} {name}")
    return jsonify(ok=ok)

@app.route('/del_dish/<int:i>')
@login_required
def dd(i):
    if not is_manager():
        return jsonify(ok=False,msg="ممنوع للفني"),403
    info=qone("SELECT ip,dish_name FROM dish_ips WHERE id=?",(i,))
    ok=qexec("DELETE FROM dish_ips WHERE id=?",(i,))
    if ok:
        add_log(session.get('phone'),'حذف صحن',f"{info.get('dish_name','')} {info.get('ip','')}" if info else f"ID {i}")
    return jsonify(ok=ok)

@app.route('/add_tower',methods=['POST'])
@login_required
def at():
    lat=request.form.get('lat','').strip()
    lng=request.form.get('lng','').strip()
    try:
        la=float(lat) if lat else 35.1312
        ln=float(lng) if lng else 36.7578
        if not (-90 <= la <= 90 and -180 <= ln <= 180):
            raise ValueError()
    except:
        return jsonify(ok=False,msg="احداثيات غير صالحة - استخدم 6 ارقام مثل 35.131812"),400
    ok=qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",(request.form.get('name',''),request.form.get('area',''),la,ln))
    if ok:
        add_log(session.get('phone'),'إضافة برج',request.form.get('name',''))
    return jsonify(ok=ok)

@app.route('/del_tower/<int:i>')
@login_required
def dt(i):
    if not is_manager():
        return jsonify(ok=False,msg="ممنوع للفني"),403
    ok=qexec("DELETE FROM towers WHERE id=?",(i,))
    if ok:
        add_log(session.get('phone'),'حذف برج',f"ID {i}")
    return jsonify(ok=ok)

@app.route('/edit_tower/<int:i>',methods=['POST'])
@login_required
def et(i):
    if not is_manager():
        return jsonify(ok=False,msg="ممنوع للفني"),403
    lat=request.form.get('lat','').strip()
    lng=request.form.get('lng','').strip()
    try:
        la=float(lat) if lat else 35.1318
        ln=float(lng) if lng else 36.7578
    except:
        la=35.1318
        ln=36.7578
    ok=qexec("UPDATE towers SET name=?,area=?,lat=?,lng=? WHERE id=?",(request.form.get('name',''),request.form.get('area',''),la,ln,i))
    if ok:
        add_log(session.get('phone'),'تعديل برج',f"ID {i}")
    return jsonify(ok=ok)

@app.route('/add_sub',methods=['POST'])
@login_required
def asub():
    ok=qexec("INSERT INTO subs(name,phone,note) VALUES(?,?,?)",(request.form.get('name',''),request.form.get('phone',''),request.form.get('note','')))
    if ok:
        add_log(session.get('phone'),'إضافة مشترك',request.form.get('name',''))
    return jsonify(ok=ok)

@app.route('/del_sub/<int:i>')
@login_required
def dsub(i):
    if not is_manager():
        return jsonify(ok=False,msg="ممنوع للفني"),403
    ok=qexec("DELETE FROM subs WHERE id=?",(i,))
    if ok:
        add_log(session.get('phone'),'حذف مشترك',f"ID {i}")
    return jsonify(ok=ok)

@app.route('/edit_sub/<int:i>',methods=['POST'])
@login_required
def esub(i):
    if not is_manager():
        return jsonify(ok=False,msg="ممنوع للفني"),403
    ok=qexec("UPDATE subs SET name=?,phone=?,note=? WHERE id=?",(request.form.get('name',''),request.form.get('phone',''),request.form.get('note',''),i))
    if ok:
        add_log(session.get('phone'),'تعديل مشترك',f"ID {i}")
    return jsonify(ok=ok)

@app.route('/add_ledger',methods=['POST'])
@login_required
def al():
    try:
        amt=float(request.form.get('amount') or 0)
    except:
        amt=0
    ok=qexec("INSERT INTO ledger(name,amount,note,currency) VALUES(?,?,?,?)",(request.form.get('name',''),amt,request.form.get('note',''),request.form.get('currency','USD')))
    if ok:
        add_log(session.get('phone'),'إضافة حساب',f"{request.form.get('name','')} {amt}")
    return jsonify(ok=ok)

@app.route('/del_ledger/<int:i>')
@login_required
def dll(i):
    if not is_manager():
        return jsonify(ok=False,msg="ممنوع للفني"),403
    ok=qexec("DELETE FROM ledger WHERE id=?",(i,))
    if ok:
        add_log(session.get('phone'),'حذف حساب',f"ID {i}")
    return jsonify(ok=ok)

@app.route('/edit_ledger/<int:i>',methods=['POST'])
@login_required
def el(i):
    if not is_manager():
        return jsonify(ok=False,msg="ممنوع للفني"),403
    try:
        amt=float(request.form.get('amount') or 0)
    except:
        amt=0
    ok=qexec("UPDATE ledger SET name=?,amount=?,note=?,currency=? WHERE id=?",(request.form.get('name',''),amt,request.form.get('note',''),request.form.get('currency','USD'),i))
    if ok:
        add_log(session.get('phone'),'تعديل حساب',f"ID {i}")
    return jsonify(ok=ok)

@app.route('/add_user',methods=['POST'])
@login_required
@role_required_manager
def au():
    ph=request.form.get('phone','').strip() or request.form.get('user_field','').strip()
    if not ph:
        return jsonify(ok=False,msg="رقم مطلوب"),400
    if qone("SELECT * FROM users WHERE phone=?",(ph,)):
        return jsonify(ok=False,msg="موجود مسبقاً"),400
    ok=qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",(ph,generate_password_hash(request.form.get('password','1234')),request.form.get('role','tech'),ph))
    if ok:
        add_log(session.get('phone'),'إضافة يوزر',ph)
    return jsonify(ok=ok)

@app.route('/edit_user',methods=['POST'])
@login_required
@role_required_manager
def eu():
    old=request.form.get('old_phone','').strip()
    new_ph=request.form.get('phone','').strip() or request.form.get('user_field','').strip()
    new_role=request.form.get('role','tech')
    new_pass=request.form.get('password','').strip()
    if not old:
        return jsonify(ok=False,msg="خطأ"),400
    if old!=new_ph and qone("SELECT * FROM users WHERE phone=?",(new_ph,)):
        return jsonify(ok=False,msg="الرقم الجديد موجود"),400
    if new_pass:
        ok=qexec("UPDATE users SET phone=?,username=?,role=?,password=? WHERE phone=?",(new_ph,new_ph,new_role,generate_password_hash(new_pass),old))
    else:
        ok=qexec("UPDATE users SET phone=?,username=?,role=? WHERE phone=?",(new_ph,new_ph,new_role,old))
    if session.get('phone')==old:
        session['phone']=new_ph
        session['role']=new_role
    if ok:
        add_log(session.get('phone'),'تعديل يوزر',f"{old}->{new_ph}")
    return jsonify(ok=ok)

@app.route('/del_user/<ph>')
@login_required
@role_required_manager
def du(ph):
    if ph=='05344851045':
        return jsonify(ok=False,msg="ممنوع حذف المدير"),400
    ok=qexec("DELETE FROM users WHERE phone=?",(ph,))
    if ok:
        add_log(session.get('phone'),'حذف يوزر',ph)
    return jsonify(ok=ok)

@app.route('/change_pass',methods=['POST'])
@login_required
def cp():
    np=request.form.get('newpass','').strip()
    if not np or len(np)<4:
        return jsonify(ok=False,msg="قصيرة"),400
    ok=qexec("UPDATE users SET password=? WHERE phone=?",(generate_password_hash(np),session.get('phone')))
    if ok:
        add_log(session.get('phone'),'تغيير كلمة سر','')
    return jsonify(ok=ok)

def page_content(v):
    req_lang=request.args.get('lang') or session.get('lang','ar')
    def L(ar,en):
        return ar if req_lang=='ar' else en
    if v=='home':
        ns,nd,nt,nl=get_counts()
        logs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 8")
        log_html=""
        for l in logs:
            log_html+=f"<div style='display:flex;justify-content:space-between;padding:10px;border-bottom:1px dashed #ffffff10'><div><b style='color:#ffbe4d'>{esc(l.get('user_phone',''))}</b> <span style='color:#22c55e;font-weight:800'>{esc(l.get('action',''))}</span> <small style='color:#cbd5e1'>{esc(l.get('detail',''))}</small></div><small style='color:#64748b'>{esc(l.get('time',''))}</small></div>"
        if not logs:
            log_html="<div style='padding:12px;color:#888'>السجل فاضي</div>"
        return f'''<div style='max-width:1000px;margin:0 auto'><div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px'>
        <div class='card stat-card' onclick="loadPage('subs')" style='cursor:pointer'><div style='display:flex;justify-content:space-between'><div><h3 style='margin:0;color:#aab4d0;font-size:13px'>{L('المشتركين','Subs')}</h3><h2 style='margin:6px 0 0;font-size:32px'>{ns}</h2></div><div style='font-size:32px' class=icon-anim>👥</div></div></div>
        <div class='card stat-card' onclick="loadPage('dishes')" style='cursor:pointer'><div style='display:flex;justify-content:space-between'><div><h3 style='margin:0;color:#aab4d0;font-size:13px'>{L('الصحون','Dishes')}</h3><h2 style='margin:6px 0 0;font-size:32px'>{nd}</h2></div><div style='font-size:32px' class=icon-anim>📡</div></div></div>
        <div class='card stat-card' onclick="loadPage('towers')" style='cursor:pointer'><div style='display:flex;justify-content:space-between'><div><h3 style='margin:0;color:#aab4d0;font-size:13px'>{L('الأبراج','Towers')}</h3><h2 style='margin:6px 0 0;font-size:32px'>{nt}</h2></div><div style='font-size:32px' class=icon-anim>🗼</div></div></div>
        <div class='card stat-card' onclick="loadPage('ledger')" style='cursor:pointer'><div style='display:flex;justify-content:space-between'><div><h3 style='margin:0;color:#aab4d0;font-size:13px'>{L('الحسابات','Accounts')}</h3><h2 style='margin:6px 0 0;font-size:32px'>{nl}</h2></div><div style='font-size:32px' class=icon-anim>📒</div></div></div></div>
        <div class=card style='margin-top:14px'><div style='display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px'><h4>التقارير</h4><div style='display:flex;gap:8px'><a href='/api/export/dishes' class=btn-gold style='text-decoration:none;padding:8px 12px;background:#22c55e;color:#fff;border-radius:10px'>Excel صحون</a><a href='/api/export/logs' class=btn-gold style='text-decoration:none;padding:8px 12px;background:#8b5cf6;color:#fff;border-radius:10px'>Excel سجل</a></div></div></div>
        <div class=card><div style='display:flex;justify-content:space-between'><h4>آخر النشاطات</h4><button class=btn-gold onclick="loadPage('logs')">عرض الكل</button></div><div style='margin-top:10px'>{log_html}</div></div></div>'''

    if v=='ping':
        return f'''<div style='max-width:900px;margin:0 auto'>
        <div class=card style='background:linear-gradient(135deg,#0f172a,#1e293b)'>
        <h3 style='margin:0'>📶 {L('فحص الشبكة','Ping')}</h3>
        <div style='display:flex;gap:8px;margin-top:12px;flex-wrap:wrap'>
        <input id=pingIp placeholder='192.168.1.1' style='flex:1;min-width:160px;padding:14px;border-radius:12px;background:#0f1424;border:1px solid #ffffff20;color:#fff;font-family:monospace'>
        <input id=pingPort placeholder='Port' value='80' style='width:80px;padding:14px;border-radius:12px;background:#0f1424;border:1px solid #ffffff20;color:#fff'>
        <button class=btn-gold onclick="doSinglePing()" style='padding:14px 20px;background:#22c55e;color:#fff'>Ping</button>
        <button class=btn-gold onclick="doTcpPing()" style='padding:14px 16px;background:#0ea5e9;color:#fff'>TCP</button>
        </div>
        <div id=pingResult style='margin-top:14px;min-height:60px;background:#0008;border-radius:12px;padding:14px;font-family:monospace;font-size:13px;white-space:pre-wrap'>جاهز</div>
        <div style='display:flex;gap:8px;margin-top:10px'><button class=btn-gold onclick="pingAllDishes()" style='flex:1;background:#ffbe4d;color:#111'>فحص كل الصحون</button><button class=btn-gold onclick="clearPing()" style='background:#ffffff10;color:#fff'>مسح</button></div>
        </div>
        <div class=card><h4>صحون سريعة</h4><div id=quickDishes>...</div></div>
        </div><script>
        window.doSinglePing=async function(){{
          let ip=document.getElementById('pingIp').value.trim();
          if(!ip) return;
          let out=document.getElementById('pingResult');
          out.textContent='جاري فحص '+ip+'...';
          try{{let r=await fetch('/api/ping?ip='+encodeURIComponent(ip),{{cache:'no-store'}}); let j=await r.json(); out.textContent=j.out; out.style.color=j.ok?'#22c55e':'#ef4444';}}catch(e){{out.textContent='خطأ '+e;}}
        }};
        window.doTcpPing=async function(){{
          let ip=document.getElementById('pingIp').value.trim();
          let port=document.getElementById('pingPort').value.trim()||'80';
          let out=document.getElementById('pingResult');
          out.textContent='جاري '+ip+':'+port+'...';
          try{{let r=await fetch('/api/ping_tcp?ip='+encodeURIComponent(ip)+'&port='+port); let j=await r.json(); out.textContent=j.out;}}catch(e){{out.textContent='خطأ';}}
        }};
        window.clearPing=function(){{document.getElementById('pingResult').textContent='جاهز';}};
        window.pingAllDishes=async function(){{
          let out=document.getElementById('pingResult');
          out.textContent='جاري فحص كل الصحون...\\n';
          try{{let sr=await fetch('/api/search?q=.',{{cache:'no-store'}}); let d=await sr.json(); let dishes=d.filter(x=>x.page==='dishes').slice(0,15); for(let dish of dishes){{out.textContent+='فحص '+dish.sub+' -> '; try{{let pr=await fetch('/api/ping?ip='+encodeURIComponent(dish.sub)); let pj=await pr.json(); out.textContent+=pj.out+'\\n';}}catch{{out.textContent+='خطأ\\n'}}}} }}catch(e){{out.textContent='خطأ: '+e;}}
        }};
        (async()=>{{try{{let r=await fetch('/api/search?q=.',{{cache:'no-store'}}); let d=await r.json(); let h=''; d.filter(x=>x.page==='dishes').slice(0,8).forEach(x=>{{h+='<div style="display:flex;justify-content:space-between;padding:8px 10px;border-bottom:1px solid #ffffff08"><span>'+x.sub+' - '+x.title+'</span><button class=btn-gold onclick="document.getElementById(\\'pingIp\\').value=\\''+x.sub+'\\'; doSinglePing()" style="padding:5px 10px">Ping</button></div>';}}); document.getElementById('quickDishes').innerHTML=h||'لا يوجد';}}catch{{}}}})();
        </script>'''

    if v=='dishes':
        rs=qall("SELECT * FROM dish_ips ORDER BY id DESC LIMIT 200")
        rows_html=""
        for r in rs:
            dn=esc(r.get('dish_name') or 'صحن')
            ip=esc(r.get('ip') or '')
            loc=esc(r.get('location') or '')
            rid=r['id']
            rows_html+=f'<div class="card dish-card card-anim" id="dish-{rid}" data-name="{dn}" data-ip="{ip}" data-loc="{loc}" style="display:flex;justify-content:space-between;align-items:center"><div><b>{dn}</b><br><a href="http://{ip}" target=_blank style="background:#000;color:#ffbe4d;padding:4px 10px;border-radius:8px;font-family:monospace;text-decoration:none;display:inline-block;margin:4px 0">{ip}</a><br><small style="color:#888">{loc}</small></div><div style="display:flex;flex-direction:column;gap:6px"><button class="btn-gold icon-anim" onclick="quickPingD({rid})" style="padding:7px 12px;background:#22c55e;color:#fff">Ping</button><div style="display:flex;gap:4px"><button class="btn-gold icon-anim" onclick="editDish({rid})" style="padding:7px 9px">تعديل</button><button class="btn-del icon-anim" onclick="askDel(\'/del_dish/{rid}\', {rid}, \'dish\')" style="padding:7px 9px">حذف</button></div></div></div>'
        return f'''<div style='max-width:900px;margin:0 auto'><div class=card><div style='display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px'><h3 style='margin:0'>الصحون - {len(rs)}</h3><div style='display:flex;gap:6px'><button onclick="loadPage('ping')" class=btn-gold style='padding:7px 12px;background:#22c55e;color:#fff'>Ping</button><a href='/api/export/dishes' class=btn-gold style='text-decoration:none;padding:7px 12px'>Excel</a></div></div>
        <form id=formDish style='display:flex;gap:6px;flex-wrap:wrap;margin-top:12px'><input name=dish_name placeholder='اسم الصحن' required style='flex:1;min-width:120px'><input name=ip placeholder='192.168.1.1' required style='flex:1;min-width:120px'><input name=location placeholder='موقع' style='flex:1;min-width:100px'><button class="btn-gold icon-anim" type=submit id=btnAddDish>إضافة</button></form>
        <input id=searchBox placeholder='بحث...' oninput="searchDishes(this.value)" style='margin-top:12px;width:100%;padding:12px;border-radius:12px;background:#0f1424;border:1px solid #ffffff18'></div><div id=dl style='display:grid;gap:10px'>{rows_html}</div></div><script>
        window.searchDishes=function(q){{q=(q||'').toLowerCase();document.querySelectorAll('.dish-card').forEach(c=>{{let t=(c.dataset.name+c.dataset.ip+c.dataset.loc).toLowerCase(); c.style.display=t.includes(q)?'flex':'none';}});}};
        window.editDish=function(id){{let c=document.getElementById('dish-'+id);let body=document.getElementById('editBody');body.innerHTML='<input id=edit_dish_name value="'+c.dataset.name.replace(/"/g,'&quot;')+'" style="width:100%;padding:12px;margin:4px 0"><input id=edit_ip value="'+c.dataset.ip+'" style="width:100%;padding:12px;margin:4px 0"><input id=edit_loc value="'+c.dataset.loc.replace(/"/g,'&quot;')+'" style="width:100%;padding:12px;margin:4px 0"><button onclick="saveDish('+id+')" class=btn-gold style="width:100%;padding:12px" id=btnSaveDish>حفظ</button>';document.getElementById('editModal').classList.add('show');}};
        window.saveDish=async function(id){{let b=document.getElementById('btnSaveDish'); b.textContent='جاري...'; b.disabled=true; let nn=document.getElementById('edit_dish_name').value;let ii=document.getElementById('edit_ip').value;let ll=document.getElementById('edit_loc').value;let r=await fetch('/edit_dish/'+id,{{method:'POST',body:new URLSearchParams({{dish_name:nn,ip:ii,location:ll}})}});let j=await r.json();if(j.ok){{closeEditModal(); loadPage('dishes',true);}} else {{alert(j.msg||'ممنوع'); b.textContent='حفظ'; b.disabled=false;}}}};
        window.quickPingD=function(id){{let c=document.getElementById('dish-'+id); loadPage('ping'); setTimeout(()=>{{let inp=document.getElementById('pingIp');if(inp){{inp.value=c.dataset.ip; doSinglePing();}}}},400);}};
        document.getElementById('formDish').addEventListener('submit', async e=>{{e.preventDefault();let btn=document.getElementById('btnAddDish'); btn.textContent='جاري...'; btn.disabled=true; let r=await fetch('/add_dish',{{method:'POST',body:new FormData(e.target)}});let j=await r.json();if(j.ok){{e.target.reset(); loadPage('dishes',true);}} else {{alert(j.msg||'خطأ'); btn.textContent='إضافة'; btn.disabled=false;}}}});
        </script>'''

    if v=='towers':
        rs=qall("SELECT * FROM towers ORDER BY id DESC")
        rows="".join([f"<div class='card card-anim' id='tower-{r['id']}' data-name='{esc(r['name'])}' data-area='{esc(r['area'] or '')}' data-lat='{r.get('lat') or 0}' data-lng='{r.get('lng') or 0}'><div style='display:flex;justify-content:space-between'><div><b>{esc(r['name'])}</b><br><small>{esc(r['area'] or '')}</small><br><small style='color:#ffbe4d;font-family:monospace'>{r.get('lat')},{r.get('lng')}</small></div><div><button class='btn-gold icon-anim' onclick=\"openEditTower({r['id']})\" style='padding:8px 10px'>تعديل</button> <button class='btn-del icon-anim' onclick=\"askDel('/del_tower/{r['id']}',{r['id']},'tower')\" style='padding:8px 10px'>حذف</button></div></div></div>" for r in rs])
        return f'''<div style='max-width:800px;margin:0 auto'><div class=card><h3>الأبراج - {len(rs)}</h3>
        <form id=formTower style='display:flex;gap:6px;flex-wrap:wrap;margin-top:10px'><input name=name placeholder='اسم البرج' required style='flex:1;min-width:120px'><input name=area placeholder='المنطقة' style='flex:1'><input name=lat placeholder='lat 35.131812' style='flex:0.7'><input name=lng placeholder='lng 36.757812' style='flex:0.7'><button class="btn-gold icon-anim">إضافة بدقة 6</button></form>
        <input id=towerSearch placeholder='بحث برج...' oninput="searchTowers(this.value)" style='margin-top:10px;width:100%;padding:11px;border-radius:11px;background:#0f1424;border:1px solid #ffffff18'>
        </div><div style='display:grid;gap:10px'>{rows}</div><script>
        window.searchTowers=function(q){{q=(q||'').toLowerCase();document.querySelectorAll('[id^=tower-]').forEach(c=>{{let t=(c.dataset.name+c.dataset.area).toLowerCase();c.style.display=t.includes(q)?'':'none';}});}};
        window.openEditTower=function(id){{let c=document.getElementById('tower-'+id);let body=document.getElementById('editBody');body.innerHTML='<input id=edit_t_name value="'+c.dataset.name.replace(/"/g,'&quot;')+'" style="width:100%;margin:6px 0;padding:12px"><input id=edit_t_area value="'+c.dataset.area.replace(/"/g,'&quot;')+'" style="width:100%;margin:6px 0;padding:12px"><input id=edit_t_lat value="'+c.dataset.lat+'" style="width:100%;margin:6px 0;padding:12px" placeholder="lat 6 أرقام"><input id=edit_t_lng value="'+c.dataset.lng+'" style="width:100%;margin:6px 0;padding:12px" placeholder="lng 6 أرقام"><button onclick="saveTower('+id+')" class=btn-gold style="width:100%;padding:12px">حفظ بدقة عالية</button>';document.getElementById('editModal').classList.add('show');}};
        window.saveTower=async function(id){{let nn=document.getElementById('edit_t_name').value;let aa=document.getElementById('edit_t_area').value;let la=document.getElementById('edit_t_lat').value;let ln=document.getElementById('edit_t_lng').value;let r=await fetch('/edit_tower/'+id,{{method:'POST',body:new URLSearchParams({{name:nn,area:aa,lat:la,lng:ln}})}});let j=await r.json();if(j.ok){{closeEditModal();loadPage('towers',true);}}else alert(j.msg||'خطأ');}};
        document.getElementById('formTower').addEventListener('submit', async e=>{{e.preventDefault();let r=await fetch('/add_tower',{{method:'POST',body:new FormData(e.target)}});let j=await r.json();if(j.ok){{e.target.reset();loadPage('towers',true);}}else alert(j.msg||'خطأ');}});
        </script></div>'''

    if v=='subs':
        rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 200")
        rows="".join([f"<div class='card card-anim' id='sub-{r['id']}' data-name='{esc(r['name'])}' data-phone='{esc(r['phone'] or '')}' data-note='{esc(r['note'] or '')}' style='display:flex;justify-content:space-between'><div><b>{esc(r['name'])}</b><br>{esc(r['phone'] or '')}</div><div><button class='btn-gold icon-anim' onclick=\"openEditSub({r['id']})\">تعديل</button> <button class='btn-del icon-anim' onclick=\"askDel('/del_sub/{r['id']}',{r['id']},'sub')\">حذف</button></div></div>" for r in rs])
        return f'''<div style='max-width:700px;margin:0 auto'><div class=card><h3>المشتركين</h3><form id=formSub style='display:flex;gap:5px;flex-wrap:wrap'><input name=name placeholder='الاسم' required style='flex:1'><input name=phone placeholder='رقم' style='flex:1'><input name=note placeholder='ملاحظة' style='flex:1'><button class="btn-gold icon-anim">إضافة</button></form></div><div style='display:grid;gap:8px'>{rows}</div><script>
        window.openEditSub=function(id){{let c=document.getElementById('sub-'+id);let body=document.getElementById('editBody');body.innerHTML='<input id=edit_s_name value="'+c.dataset.name.replace(/"/g,'&quot;')+'" style="width:100%;margin:6px 0;padding:12px"><input id=edit_s_phone value="'+c.dataset.phone+'" style="width:100%;margin:6px 0;padding:12px"><input id=edit_s_note value="'+c.dataset.note.replace(/"/g,'&quot;')+'" style="width:100%;margin:6px 0;padding:12px"><button onclick="saveSub('+id+')" class=btn-gold style="width:100%;padding:12px">حفظ</button>';document.getElementById('editModal').classList.add('show');}};
        window.saveSub=async function(id){{let nn=document.getElementById('edit_s_name').value;let pp=document.getElementById('edit_s_phone').value;let no=document.getElementById('edit_s_note').value;let r=await fetch('/edit_sub/'+id,{{method:'POST',body:new URLSearchParams({{name:nn,phone:pp,note:no}})}});let j=await r.json();if(j.ok){{closeEditModal();loadPage('subs',true);}}}};
        document.getElementById('formSub').addEventListener('submit', async e=>{{e.preventDefault();let r=await fetch('/add_sub',{{method:'POST',body:new FormData(e.target)}});let j=await r.json();if(j.ok){{e.target.reset();loadPage('subs',true);}}}});
        </script></div>'''

    if v=='ledger':
        rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 200")
        rows="".join([f"<div class='card card-anim' id='led-{r['id']}' data-name='{esc(r['name'])}' data-amount='{r['amount']}'><div style='display:flex;justify-content:space-between'><div><b>{esc(r['name'])}</b> - <b style='color:#ffbe4d'>{r['amount']}</b></div><div><button class='btn-gold icon-anim' onclick=\"openEditLed({r['id']})\">تعديل</button> <button class='btn-del icon-anim' onclick=\"askDel('/del_ledger/{r['id']}',{r['id']},'led')\">حذف</button></div></div></div>" for r in rs])
        return f'''<div style='max-width:700px;margin:0 auto'><div class=card><h3>الحسابات</h3><form id=formLed style='display:flex;gap:5px;flex-wrap:wrap'><input name=name placeholder='الاسم' required style='flex:1'><input name=amount type=number step=0.01 placeholder='المبلغ' required style='flex:1'><input name=note placeholder='ملاحظة' style='flex:1'><select name=currency style='flex:0.5'><option>USD</option><option>SYP</option></select><button class="btn-gold icon-anim">إضافة</button></form></div><div style='display:grid;gap:8px'>{rows}</div><script>
        window.openEditLed=function(id){{let c=document.getElementById('led-'+id);let body=document.getElementById('editBody');body.innerHTML='<input id=edit_l_name value="'+c.dataset.name.replace(/"/g,'&quot;')+'" style="width:100%;margin:6px 0;padding:12px"><input id=edit_l_amount value="'+c.dataset.amount+'" style="width:100%;margin:6px 0;padding:12px"><button onclick="saveLed('+id+')" class=btn-gold style="width:100%;padding:12px">حفظ</button>';document.getElementById('editModal').classList.add('show');}};
        window.saveLed=async function(id){{let nn=document.getElementById('edit_l_name').value;let aa=document.getElementById('edit_l_amount').value;let r=await fetch('/edit_ledger/'+id,{{method:'POST',body:new URLSearchParams({{name:nn,amount:aa,note:'',currency:'USD'}})}});let j=await r.json();if(j.ok){{closeEditModal();loadPage('ledger',true);}}}};
        document.getElementById('formLed').addEventListener('submit', async e=>{{e.preventDefault();let r=await fetch('/add_ledger',{{method:'POST',body:new FormData(e.target)}});let j=await r.json();if(j.ok){{e.target.reset();loadPage('ledger',true);}}}});
        </script></div>'''

    if v=='logs':
        rs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 300")
        rows=""
        for r in rs:
            col='#22c55e' if 'إضافة' in r.get('action','') else '#0ea5e9' if 'تعديل' in r.get('action','') else '#ef4444' if 'حذف' in r.get('action','') else '#ffbe4d'
            rows+=f"<div class='card card-anim' style='font-size:13px;border-right:4px solid {col};display:flex;justify-content:space-between'><div><b style='color:#ffbe4d'>{esc(r.get('user_phone',''))}</b> <span style='background:{col};color:#fff;padding:2px 8px;border-radius:6px;font-size:11px'>{esc(r.get('action',''))}</span><br><small style='color:#cbd5e1'>{esc(r.get('detail',''))}</small></div><small style='color:#64748b'>{esc(r.get('time',''))}</small></div>"
        if not rows:
            rows="<div class=card style='text-align:center;padding:20px'>لا يوجد سجل</div>"
        return f"<div style='max-width:900px;margin:0 auto'><div class=card style='display:flex;justify-content:space-between;align-items:center'><h3 style='margin:0'>السجل ({len(rs)})</h3><div style='display:flex;gap:6px'><a href='/api/export/logs' class=btn-gold style='text-decoration:none;padding:7px 12px;background:#22c55e;color:#fff;border-radius:8px'>Excel</a><button onclick=\"if(confirm('مسح؟')){{fetch('/api/clear_logs',{method:'POST'}}).then(()=>loadPage('logs',true))}}\" class=btn-del>مسح</button></div></div><div style='display:grid;gap:8px'>{rows}</div></div>"

    if v=='map':
        towers=qall("SELECT * FROM towers")
        tj_json=json.dumps([{"name":t['name'],"area":t.get('area') or '',"lat":float(t.get('lat') or 35.1318),"lng":float(t.get('lng') or 36.7578)} for t in towers],ensure_ascii=False)
        return f'''<div class=card style='padding:10px'>
        <div style='display:flex;gap:6px;margin-bottom:10px;flex-wrap:wrap;align-items:center'>
        <input id=mapSearch placeholder='بحث برج...' style='flex:1;min-width:140px;background:#0f1424;border:1px solid #ffffff15;color:#fff;padding:10px 12px;border-radius:12px'>
        <button class="btn-gold icon-anim" onclick="doMapSearch()" style='padding:10px 12px'>بحث</button>
        <button class="btn-gold icon-anim" onclick="locateMe()" style='background:#22c55e;color:#fff;padding:10px 12px'>موقعي</button>
        <button class="btn-gold icon-anim" onclick="enableAddPoint()" id=addPointBtn style='background:#f59e0b;color:#fff;padding:10px 12px'>نقطة بدقة 6</button>
        <span id=coordsLabel style='color:#ffbe4d;font-family:monospace;background:#0f1424;padding:4px 8px;border-radius:6px'>-</span>
        </div>
        <div id=map style='height:72vh;min-height:460px;border-radius:16px;background:#0f172a;z-index:1;border:2px solid #ffffff0f'></div>
        </div><script>
        let _towers={tj_json};
        let _map=null; let addPointMode=false;
        window.doMapSearch=function(){{let q=document.getElementById('mapSearch').value.trim().toLowerCase();if(!q) return;let f=_towers.find(t=>t.name.toLowerCase().includes(q)||t.area.toLowerCase().includes(q));if(f&&_map) _map.flyTo([f.lat,f.lng],18);}};
        window.locateMe=function(){{if(_map&&navigator.geolocation) navigator.geolocation.getCurrentPosition(p=>{{_map.flyTo([p.coords.latitude,p.coords.longitude],16);L.marker([p.coords.latitude,p.coords.longitude]).addTo(_map).bindPopup('موقعك').openPopup();}},null,{{enableHighAccuracy:true}});}};
        window.enableAddPoint=function(){{addPointMode=!addPointMode;let b=document.getElementById('addPointBtn');b.textContent=addPointMode?'اضغط على الخريطة':'نقطة بدقة 6';b.style.background=addPointMode?'#ef4444':'#f59e0b';if(_map) _map.getContainer().style.cursor=addPointMode?'crosshair':'';}};
        setTimeout(()=>{{
          _map=L.map('map').setView([35.1318,36.7578],13);
          L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:19}}).addTo(_map);
          L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',{{maxZoom:19}}).addTo(_map);
          _towers.forEach(t=>{{L.marker([t.lat,t.lng]).addTo(_map).bindPopup('<b>'+t.name+'</b><br><small style="font-family:monospace">'+t.lat.toFixed(6)+','+t.lng.toFixed(6)+'</small>');}});
          _map.on('mousemove',e=>{{document.getElementById('coordsLabel').textContent=e.latlng.lat.toFixed(6)+','+e.latlng.lng.toFixed(6);}});
          _map.on('click',e=>{{
            let lat6=e.latlng.lat.toFixed(6),lng6=e.latlng.lng.toFixed(6);
            document.getElementById('coordsLabel').textContent=lat6+','+lng6;
            if(addPointMode){{
              L.popup().setLatLng(e.latlng).setContent('<div style="min-width:200px"><b>📍 '+lat6+','+lng6+'</b><br><input id="newPointName" placeholder="اسم البرج" style="width:100%;margin:6px 0;padding:8px;border-radius:8px"><input id="newPointArea" placeholder="المنطقة" style="width:100%;margin:4px 0;padding:8px;border-radius:8px"><button onclick="saveNewPoint('+e.latlng.lat+','+e.latlng.lng+')" style="width:100%;background:linear-gradient(90deg,#ffbe4d,#ffb020);border:0;padding:10px;border-radius:8px;font-weight:800">حفظ بدقة 6</button></div>').openOn(_map);
            }}
          }});
          window.saveNewPoint=async function(lat,lng){{let name=document.getElementById('newPointName').value||'نقطة';let area=document.getElementById('newPointArea')?.value||'';let r=await fetch('/add_tower',{{method:'POST',body:new URLSearchParams({{name:name,area:area,lat:lat.toFixed(6),lng:lng.toFixed(6)}})}});let j=await r.json();if(j.ok){{_map.closePopup(); loadPage('towers',true);}}}};
        }},400);
        </script>'''

    if v=='network':
        dishes=qall("SELECT * FROM dish_ips ORDER BY id DESC LIMIT 100")
        rows="".join([f"<div class='card card-anim' id='net-{d['id']}' data-ip='{esc(d.get('ip',''))}' style='display:flex;justify-content:space-between'><div><b>{esc(d.get('dish_name') or 'صحن')}</b> - {esc(d.get('ip',''))}<br><small class='net-out' style='color:#888'>...</small></div><button class=btn-gold onclick='checkOne({d['id']})'>فحص</button></div>" for d in dishes])
        return f'''<div style='max-width:800px;margin:0 auto'><div class=card><h3>حالة الشبكة</h3><button class=btn-gold onclick='checkAll()' style='width:100%;background:#22c55e;color:#fff;padding:12px'>فحص الكل</button><div id=summary style='margin-top:10px'></div></div>{rows}<script>
        window.checkOne=async function(id){{let c=document.getElementById('net-'+id);let out=c.querySelector('.net-out');out.textContent='جاري...';try{{let r=await fetch('/api/ping?ip='+encodeURIComponent(c.dataset.ip));let j=await r.json();out.textContent=j.out.slice(0,80);out.style.color=j.ok?'#22c55e':'#ef4444';}}catch(e){{out.textContent='خطأ';}}}};
        window.checkAll=async function(){{for(let c of document.querySelectorAll('[id^=net-]')){{let out=c.querySelector('.net-out');out.textContent='جاري...';try{{let r=await fetch('/api/ping?ip='+encodeURIComponent(c.dataset.ip));let j=await r.json();out.textContent=j.out.slice(0,80);out.style.color=j.ok?'#22c55e':'#ef4444';}}catch(e){{}}await new Promise(r=>setTimeout(r,150));}}}};
        checkAll();
        </script></div>'''

    if v=='settings':
        us=qall("SELECT * FROM users ORDER BY phone DESC")
        uh="".join([f'<div class="card card-anim" id="user-{esc(u["phone"])}" data-phone="{esc(u["phone"])}" data-username="{esc(u.get("username") or "")}" data-role="{esc(u.get("role") or "")}" style="display:grid;grid-template-columns:1fr auto;gap:12px"><div><b>{esc(u.get("username") or "")}</b><br><span style="color:#ffbe4d;font-family:monospace">{esc(u["phone"])}</span> {"<span style=\'background:#ffbe4d;color:#111;padding:2px 8px;border-radius:8px;font-size:11px\'>مدير</span>" if u.get("role")=="manager" else "<span style=\'background:#ffffff15;padding:2px 8px;border-radius:8px;font-size:11px\'>فني</span>"}</div><div style="display:flex;gap:6px"><button class="btn-gold icon-anim" onclick="openEditUser(\'{esc(u["phone"])}\')" style="padding:8px 10px">تعديل</button><button class="btn-del icon-anim" onclick="askDel(\'/del_user/{esc(u["phone"])}\',\'{esc(u["phone"])}\',\'user\')" style="padding:8px 10px">حذف</button></div></div>' for u in us])
        return f'''<div style='max-width:800px;margin:0 auto'><div class=card><h3>كلمة السر</h3><form id=formPass style='display:flex;gap:8px'><input name=newpass type=password placeholder='جديدة' required style='flex:1'><button class="btn-gold icon-anim">حفظ</button></form></div>
        <div style='display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px'><div class=card style='text-align:center'><h4>اللغة والثيم</h4><button onclick="toggleLangNoReload()" class="btn-gold icon-anim" style='width:100%;padding:12px;background:#1f2937;color:#fff'>تغيير اللغة بدون تحميل</button><button onclick="toggleThemeNoReload()" class="btn-gold icon-anim" style='width:100%;padding:12px;margin-top:8px'>ثيم</button></div>
        <div class=card><h4>إضافة يوزر</h4><form id=formUser style='display:flex;flex-direction:column;gap:8px'><input name=user_field placeholder='رقم / يوزر' required style='padding:12px;background:#0f1424;border:1px solid #ffffff20;border-radius:12px;color:#fff'><input name=password type=password placeholder='كلمة السر' required style='padding:12px;background:#0f1424;border:1px solid #ffffff20;border-radius:12px;color:#fff'><select name=role style='padding:12px;background:#0f1424;border:1px solid #ffffff20;border-radius:12px;color:#fff'><option value=tech>فني</option><option value=manager>مدير</option></select><button class="btn-gold icon-anim" style='padding:12px'>إضافة</button></form></div></div>
        <div class=card><h4>تصدير</h4><div style='display:flex;gap:8px;flex-wrap:wrap'><a href='/api/export/users' class=btn-gold style='text-decoration:none;padding:8px 12px;background:#22c55e;color:#fff;border-radius:8px'>يوزرات</a><a href='/api/export/dishes' class=btn-gold style='text-decoration:none;padding:8px 12px;background:#0ea5e9;color:#fff;border-radius:8px'>صحون</a><a href='/api/export/towers' class=btn-gold style='text-decoration:none;padding:8px 12px;background:#ffbe4d;color:#111;border-radius:8px'>أبراج</a><a href='/api/export/logs' class=btn-gold style='text-decoration:none;padding:8px 12px;background:#8b5cf6;color:#fff;border-radius:8px'>سجل</a></div></div>
        <div style='display:grid;gap:8px'>{uh}</div></div><script>
        window.openEditUser=function(ph){{let c=document.getElementById('user-'+ph);let body=document.getElementById('editBody');body.innerHTML='<input id=edit_u_field value="'+c.dataset.phone+'" style="width:100%;padding:12px"><input id=edit_u_pass type="password" placeholder="كلمة سر جديدة" style="width:100%;padding:12px;margin-top:8px"><select id=edit_u_role style="width:100%;padding:12px;margin-top:8px"><option value="tech" '+(c.dataset.role=='tech'?'selected':'')+'>فني</option><option value="manager" '+(c.dataset.role=='manager'?'selected':'')+'>مدير</option></select><button onclick="saveUser(\\''+ph+'\\')" class=btn-gold style="width:100%;padding:14px;margin-top:12px">حفظ</button>';document.getElementById('editModal').classList.add('show');}};
        window.saveUser=async function(oldPh){{let ff=document.getElementById('edit_u_field').value.trim();let pw=document.getElementById('edit_u_pass').value;let ro=document.getElementById('edit_u_role').value;if(!ff){{alert('مطلوب');return;}}let data={{old_phone:oldPh,phone:ff,username:ff,role:ro}};if(pw.trim()!='') data.password=pw.trim();let r=await fetch('/edit_user',{{method:'POST',body:new URLSearchParams(data)}});let j=await r.json();if(!j.ok) alert(j.msg||'خطأ'); else {{closeEditModal();loadPage('settings',true);}}}};
        document.getElementById('formPass').addEventListener('submit', async e=>{{e.preventDefault();let r=await fetch('/change_pass',{{method:'POST',body:new FormData(e.target)}});let j=await r.json();if(j.ok){{e.target.reset();}} else alert(j.msg||'خطأ');}});
        document.getElementById('formUser').addEventListener('submit', async e=>{{e.preventDefault();let r=await fetch('/add_user',{{method:'POST',body:new FormData(e.target)}});let j=await r.json();if(j.ok){{e.target.reset(); loadPage('settings',true);}} else alert(j.msg||'خطأ');}});
        </script>'''

    if v=='support':
        return """<div class=card style='text-align:center;max-width:500px;margin:0 auto'><h2>الدعم</h2><a href='https://wa.me/905344851045' target=_blank style='display:inline-block;background:#22c55e;color:#fff;padding:14px 24px;border-radius:14px;text-decoration:none;margin:6px;font-weight:800'>واتساب</a><br><a href='tel:+905344851045' style='display:inline-block;background:#0ea5e9;color:#fff;padding:12px 22px;border-radius:14px;text-decoration:none;margin:6px'>اتصال</a></div>"""

    return "<div class=card>الصفحة غير موجودة</div>"

def layout(c,v='home'):
    th=session.get('theme','dark')
    is_dark=(th=='dark')
    bg='radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 60%, #070a1f 100%)' if is_dark else '#f1f5f9'
    card_bg='rgba(30,36,51,0.88)' if is_dark else '#ffffff'
    txt='#ffffff' if is_dark else '#0f172a'
    border='#ffffff12' if is_dark else '#e2e8f0'
    cur_user=qone("SELECT * FROM users WHERE phone=?",(session.get('phone') or '',)) or {}
    role=cur_user.get('role') or session.get('role') or 'tech'
    req_lang=session.get('lang','ar')
    is_rtl=req_lang=='ar'
    def L(ar,en): return ar if is_rtl else en
    username_display=esc(cur_user.get('username') or session.get('phone') or '')
    sidebar_pos="right:0; left:auto; transform:translateX(110%);" if is_rtl else "left:0; right:auto; transform:translateX(-110%);"
    side="right" if is_rtl else "left"
    dir_attr="rtl" if is_rtl else "ltr"
    return f"""<html dir={dir_attr} lang={req_lang}><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<link rel=stylesheet href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'>
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;700;900&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;font-family:'Cairo',system-ui}}body{{margin:0;background:{bg};color:{txt};overflow-x:hidden;direction:{dir_attr}}}
.top{{position:fixed;top:0;left:0;right:0;height:62px;background:rgba(15,23,42,0.88);backdrop-filter:blur(16px) saturate(180%);color:#fff;display:flex;align-items:center;justify-content:space-between;padding:0 14px;z-index:1003;border-bottom:1px solid #ffffff12}}
.sidebar{{position:fixed;top:0;width:285px;height:100%;background:linear-gradient(180deg,rgba(15,23,42,0.97) 0%,rgba(7,14,34,1) 100%);backdrop-filter:blur(22px) saturate(180%);color:#fff;z-index:1002;padding-top:70px;{sidebar_pos}transition:transform .42s cubic-bezier(0.34, 1.56, 0.64, 1);overflow-y:auto;border-{"left" if is_rtl else "right"}:1px solid #ffffff0f;box-shadow:0 0 50px #0009}}
.sidebar.collapsed{{width:82px}} .sidebar.collapsed a span.text{{display:none}} .sidebar.collapsed a{{justify-content:center}}
.sidebar.active{{transform:none}}
.sidebar a{{display:flex;align-items:center;gap:11px;padding:12px 15px;margin:6px 11px;color:#cbd5e1;text-decoration:none;border-radius:13px;background:rgba(255,255,255,0.04);transition:all .42s cubic-bezier(0.34, 1.56, 0.64, 1);border:1px solid transparent}}
.sidebar a:hover{{background:rgba(255,255,255,0.09);transform:translateX(-3px) scale(1.02);border-color:#ffffff18;box-shadow:0 6px 20px #0005}}
.sidebar a.active{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:800;box-shadow:0 6px 24px #ffbe4d55;transform:scale(1.03)}}
.sidebar a:active{{transform:scale(0.94)}}
#overlay{{position:fixed;inset:0;background:#0008;backdrop-filter:blur(3px);z-index:1001;display:none;opacity:0;transition:.3s}}#overlay.show{{display:block;opacity:1}}
.main{{margin-top:74px;padding:14px;min-height:90vh;transition:all .42s}}
.card{{background:{card_bg};backdrop-filter:blur(14px);color:{txt};padding:15px;border-radius:18px;margin-bottom:12px;border:1px solid {border};transition:all .42s cubic-bezier(0.34, 1.56, 0.64, 1);box-shadow:0 4px 20px #0002}}
.card:hover{{transform:translateY(-3px);box-shadow:0 10px 30px #0004;border-color:#ffffff22}}
.card-anim{{animation:cardIn .6s cubic-bezier(0.34, 1.56, 0.64, 1)}} @keyframes cardIn{{from{{opacity:0;transform:translateY(14px) scale(0.96)}} to{{opacity:1;transform:translateY(0) scale(1)}}}}
.stat-card{{cursor:pointer}} .stat-card:hover{{transform:translateY(-5px) scale(1.03)}} .stat-card:active{{transform:scale(0.96)}}
.icon-anim{{transition:all .42s cubic-bezier(0.34, 1.56, 0.64, 1);display:inline-block}} .icon-anim:hover{{transform:scale(1.18) rotate(3deg);filter:drop-shadow(0 0 10px #ffbe4d)}} .icon-anim:active{{transform:scale(0.82)}}
input,select{{padding:12px 14px;margin:5px 0;border-radius:12px;border:1px solid {border};width:100%;background:#ffffff07;color:{txt};transition:all .3s}} input:focus,select:focus{{border-color:#ffbe4d;box-shadow:0 0 0 3px #ffbe4d22;outline:none}}
.btn-gold{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;padding:9px 16px;border:0;border-radius:12px;font-weight:800;cursor:pointer;transition:all .42s cubic-bezier(0.34, 1.56, 0.64, 1)}} .btn-gold:hover{{transform:scale(1.06);box-shadow:0 8px 24px #ffbe4d55}} .btn-gold:active{{transform:scale(0.9)}}
.btn-del{{background:linear-gradient(90deg,#ef4444,#dc2626);color:#fff;padding:8px 13px;border:0;border-radius:12px;cursor:pointer;transition:all .42s cubic-bezier(0.34, 1.56, 0.64, 1)}} .btn-del:hover{{transform:scale(1.06)}} .btn-del:active{{transform:scale(0.88)}}
#delModal, #editModal{{position:fixed;inset:0;background:#000a;backdrop-filter:blur(8px);display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:.4s cubic-bezier(0.34, 1.56, 0.64, 1);z-index:2000}} #delModal.show, #editModal.show{{opacity:1;pointer-events:auto}}
#delBox, #editBox{{background:{card_bg};backdrop-filter:blur(24px);color:{txt};padding:26px;border-radius:22px;width:92%;max-width:480px;transform:scale(0.85) translateY(30px);transition:.45s cubic-bezier(0.34, 1.56, 0.64, 1);border:1px solid #ffffff1a;box-shadow:0 20px 60px #0008}} #delModal.show #delBox, #editModal.show #editBox{{transform:scale(1) translateY(0)}}
</style></head><body>
<div id=overlay onclick="toggleSb(false)"></div>
<div class=sidebar id=sb>
<div style='padding:0 18px 14px;border-bottom:1px solid #ffffff0a;margin-bottom:10px;display:flex;justify-content:space-between;align-items:center'>
<div><div style='font-weight:900;font-size:18px'>OMAIA <span style='color:#ffbe4d'>ISP</span></div><small style='color:#888'>{username_display} • {role}</small></div>
<button onclick="toggleCollapse()" id=collapseBtn style='background:#ffffff10;border:1px solid #ffffff15;color:#fff;width:34px;height:34px;border-radius:10px;cursor:pointer' class=icon-anim>◀</button>
</div>
<a href="javascript:loadPage('home')" id=nav-home class=icon-anim>🏠 <span class=text>{L('الرئيسية','Home')}</span></a>
<a href="javascript:loadPage('dishes')" id=nav-dishes class=icon-anim>📡 <span class=text>{L('الصحون','Dishes')}</span></a>
<a href="javascript:loadPage('ping')" id=nav-ping class=icon-anim>📶 <span class=text>{L('بنج','Ping')}</span></a>
<a href="javascript:loadPage('network')" id=nav-network class=icon-anim>📊 <span class=text>{L('حالة الشبكة','Network')}</span></a>
<a href="javascript:loadPage('towers')" id=nav-towers class=icon-anim>🗼 <span class=text>{L('الأبراج','Towers')}</span></a>
<a href="javascript:loadPage('subs')" id=nav-subs class=icon-anim>👥 <span class=text>{L('المشتركين','Subs')}</span></a>
<a href="javascript:loadPage('ledger')" id=nav-ledger class=icon-anim>📒 <span class=text>{L('الحسابات','Accounts')}</span></a>
<a href="javascript:loadPage('logs')" id=nav-logs class=icon-anim>📜 <span class=text>{L('السجل','Logs')}</span></a>
<a href="javascript:loadPage('map')" id=nav-map class=icon-anim>🗺 <span class=text>{L('الخريطة','Map')}</span></a>
<a href="javascript:loadPage('settings')" id=nav-settings class=icon-anim>⚙ <span class=text>{L('الإعدادات','Settings')}</span></a>
<a href="javascript:logoutFast()" style='margin-top:14px;background:#ef444418;border:1px solid #ef444422' class=icon-anim>🚪 <span class=text>{L('خروج','Logout')}</span></a>
</div>
<div class=top>
<div style='display:flex;gap:8px;align-items:center'><span onclick="toggleSb()" style='font-size:22px;cursor:pointer;padding:7px 10px;background:#ffffff0a;border-radius:12px;border:1px solid #ffffff10' class=icon-anim>☰</span><input id=topsearch placeholder='بحث...' oninput="globalSearchTop(this.value)" style='background:#0f1424;border:1px solid #ffffff15;color:#fff;padding:8px 12px;border-radius:12px;width:42px;transition:all .42s cubic-bezier(0.34, 1.56, 0.64, 1)' onfocus="this.style.width='190px'" onblur="setTimeout(()=>this.style.width='42px',300)"></div>
<div style='font-weight:900;letter-spacing:1px' class=icon-anim>OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<div style='display:flex;gap:8px'><button onclick="toggleThemeNoReload()" style='background:#ffffff0a;color:#fff;border:1px solid #ffffff0f;padding:8px 10px;border-radius:12px' class=icon-anim>🌓</button><button onclick="toggleLangNoReload()" style='background:#ffffff0a;color:#fff;border:1px solid #ffffff0f;padding:8px 10px;border-radius:12px' class=icon-anim>🌐</button></div>
</div>
<div id=searchResults style='position:fixed;top:66px;{side}:12px;max-width:430px;width:92%;background:rgba(30,36,51,0.96);backdrop-filter:blur(18px);border:1px solid #ffffff18;border-radius:16px;z-index:1500;display:none;max-height:60vh;overflow:auto;box-shadow:0 16px 50px #000a'></div>
<div class=main id=mn>{c}</div>
<div id=delModal><div id=delBox><div style='font-size:40px;text-align:center' class=icon-anim>🗑️</div><h3 style='text-align:center;margin:12px 0'>تأكيد الحذف؟</h3><p style='text-align:center;color:#888;font-size:13px'>رح ينحذف بأنيميشن سلس بدون تحميل</p><div style='display:flex;gap:12px;margin-top:18px'><button onclick="closeDel()" style='flex:1;padding:13px;border-radius:14px;background:transparent;color:{txt};border:1px solid {border};cursor:pointer' class=icon-anim>تراجع</button><button id=delYes style='flex:1;padding:13px;border-radius:14px;background:linear-gradient(90deg,#ef4444,#dc2626);color:#fff;border:0;font-weight:800;cursor:pointer' class=icon-anim>حذف فوري</button></div></div></div>
<div id=editModal><div id=editBox><div style='display:flex;justify-content:space-between;margin-bottom:16px;align-items:center'><h3 style='margin:0'>تعديل</h3><button onclick="closeEditModal()" style='background:#ffffff12;border:0;color:{txt};width:36px;height:36px;border-radius:50%;cursor:pointer' class=icon-anim>✕</button></div><div id=editBody></div></div></div>
<script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>
<script>
let cur='{v}';
let sidebarCollapsed = localStorage.getItem('omaia_collapsed')==='1';
function applyCollapse(){{let sb=document.getElementById('sb'); if(sidebarCollapsed) sb.classList.add('collapsed'); else sb.classList.remove('collapsed'); let btn=document.getElementById('collapseBtn'); if(btn) btn.textContent=sidebarCollapsed?'▶':'◀';}}
applyCollapse();
function toggleCollapse(){{
  sidebarCollapsed=!sidebarCollapsed;
  localStorage.setItem('omaia_collapsed', sidebarCollapsed?'1':'0');
  applyCollapse();
}}
function toggleSb(f){{
  let sb=document.getElementById('sb'),ov=document.getElementById('overlay');
  let o=f!==undefined?f:!sb.classList.contains('active');
  sb.classList.toggle('active',o);
  ov.classList.toggle('show',o);
}}
let pageCache={{}};
try{{pageCache=JSON.parse(localStorage.getItem('omaia_cache_final')||'{{}}');}}catch(e){{pageCache={{}};}}
function saveCache(){{try{{localStorage.setItem('omaia_cache_final',JSON.stringify(pageCache));}}catch(e){{}}}}
async function loadPage(v,force=false,push=true){{
  if(push&&cur!==v){{try{{history.pushState({{page:v}},'', '/dash?v='+v);}}catch(e){{}}}}
  cur=v;toggleSb(false);
  document.querySelectorAll('.sidebar a').forEach(a=>a.classList.remove('active'));
  let n=document.getElementById('nav-'+v); if(n) n.classList.add('active');
  let mn=document.getElementById('mn');
  if(!force&&pageCache[v]){{mn.innerHTML=pageCache[v];execScripts();fetch('/api/page?v='+v,{{cache:'no-store'}}).then(r=>r.text()).then(h=>{{if(h.length>100){{pageCache[v]=h;saveCache();}}}}).catch(()=>{{}});return;}}
  mn.innerHTML='<div class=card style="text-align:center;padding:36px"><div style="font-size:32px" class=icon-anim>⏳</div><br>جاري التحميل...</div>';
  try{{let r=await fetch('/api/page?v='+v,{{cache:'no-store'}});let h=await r.text();pageCache[v]=h;saveCache();mn.innerHTML=h;execScripts();}}catch(e){{mn.innerHTML='<div class=card>خطأ: '+e+'</div>';}}
}}
function execScripts(){{let mn=document.getElementById('mn');mn.querySelectorAll('script').forEach(old=>{{let s=document.createElement('script');s.textContent=old.textContent;document.body.appendChild(s);s.remove();}});}}
function askDel(url,id,type){{window._delUrl=url;window._delId=id;window._delType=type;document.getElementById('delModal').classList.add('show');}}
function closeDel(){{document.getElementById('delModal').classList.remove('show');window._delUrl=null;}}
window.closeEditModal=function(){{document.getElementById('editModal').classList.remove('show');}};
document.getElementById('delYes').onclick=async()=>{{
  if(!window._delUrl) return;
  let btn=document.getElementById('delYes'); let orig=btn.textContent; btn.textContent='جاري...'; btn.disabled=true;
  try{{
    if(window._delId){{let el=document.getElementById((window._delType||'dish')+'-'+window._delId); if(el){{el.style.transition='all .42s cubic-bezier(0.34, 1.56, 0.64, 1)'; el.style.transform='scale(0.85) translateX(30px)'; el.style.opacity='0'; setTimeout(()=>el.style.display='none',420);}}}}
    document.getElementById('delModal').classList.remove('show');
    let r=await fetch(window._delUrl); let j=await r.json();
    if(!j.ok){{alert(j.msg||'خطأ'); location.reload();}} else {{delete pageCache[cur];}}
  }}catch(e){{alert(e);}} btn.textContent=orig; btn.disabled=false;
}};
async function toggleThemeNoReload(){{await fetch('/toggle_theme'); location.reload();}}
async function toggleLangNoReload(){{let r=await fetch('/toggle_lang'); let j=await r.json(); loadPage(cur,true,false); document.documentElement.dir=j.lang==='ar'?'rtl':'ltr';}}
window.globalSearchTop=async function(q){{let box=document.getElementById('searchResults'); if(!q||q.length<2){{box.style.display='none'; return;}} let r=await fetch('/api/search?q='+encodeURIComponent(q)); let d=await r.json(); if(!d.length){{box.style.display='none'; return;}} let h=''; d.forEach(x=>{{h+='<div onclick="loadPage(\\''+x.page+'\\');document.getElementById(\\'searchResults\\').style.display=\\'none\\'" style="padding:12px 14px;cursor:pointer;border-bottom:1px solid #ffffff08;transition:.3s" onmouseenter="this.style.background='#ffffff08'" onmouseleave="this.style.background='transparent'"><b>'+x.title+'</b><br><small style="color:#888">'+x.sub+'</small></div>';}}); box.innerHTML=h; box.style.display='block';}};
window.logoutFast=async function(){{await fetch('/api/logout',{{method:'POST'}}); try{{localStorage.removeItem('omaia_cache_final');}}catch(e){{}} location.replace('/login');}};
window.addEventListener('popstate',(e)=>{{let v='home'; if(e.state&&e.state.page) v=e.state.page; else {{let p=new URLSearchParams(location.search); v=p.get('v')||'home';}} loadPage(v,false,false);}});
loadPage(cur,true,false);
setTimeout(()=>{{['home','dishes','towers','map','logs','ping','network','subs','ledger','settings'].forEach(p=>{{fetch('/api/page?v='+p,{{cache:'no-store'}}).then(r=>r.text()).then(h=>{{pageCache[p]=h;saveCache();}}).catch(()=>{{}});}});}},800);
</script></body></html>"""

if __name__=='__main__':
    port=int(os.environ.get("PORT",10000))
    print(f"OMAIA ISP - مصلح بدون نقصان - running on 0.0.0.0:{port}")
    app.run(host='0.0.0.0',port=port,debug=False)
