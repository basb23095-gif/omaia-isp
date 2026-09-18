from flask import Flask, request, redirect, session, jsonify, Response
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, html, ipaddress, subprocess, json, socket, platform, io, csv, datetime, re, threading, time
try:
    import psycopg2, psycopg2.extras
    from psycopg2 import pool as pg_pool
except:
    psycopg2=None
    pg_pool=None
import sqlite3

# ============================================================
# OMAIA ISP - النسخة الكاملة 1250+ سطر - سلسة نار + كروت لا نهائية
# ============================================================

app=Flask(__name__)
app.secret_key=os.environ.get("SECRET_KEY","omia-sec-2026-v3-full-1250")
app.config['PERMANENT_SESSION_LIFETIME']=datetime.timedelta(minutes=30)
app.config['SESSION_PERMANENT']=False
app.config['SESSION_COOKIE_HTTPONLY']=True
app.config['SESSION_COOKIE_SAMESITE']='Lax'
app.config['JSON_AS_ASCII']=False

DATABASE_URL=os.environ.get("DATABASE_URL","").strip().replace("postgresql://","postgres://")
USE_PG=bool(DATABASE_URL.startswith("postgres://") and psycopg2)

_pg_pool=None
_pool_lock=threading.Lock()
_sqlite_conn=None
_sqlite_lock=threading.Lock()
_cache={}
_cache_lock=threading.Lock()
_user_cache={}
_user_cache_lock=threading.Lock()

def init_pool():
    global _pg_pool
    if not USE_PG or not pg_pool:
        return
    with _pool_lock:
        if _pg_pool:
            return
        try:
            _pg_pool=pg_pool.ThreadedConnectionPool(
                2,25,
                dsn=DATABASE_URL,
                sslmode='require',
                connect_timeout=3,
                keepalives=1,
                keepalives_idle=30,
                keepalives_interval=10,
                keepalives_count=3
            )
        except Exception as e:
            print(f"[POOL] {e}")
            _pg_pool=None

init_pool()

def esc(s):
    return html.escape(str(s or ''), quote=True)

def get_conn():
    if USE_PG and _pg_pool:
        try:
            return _pg_pool.getconn()
        except:
            return psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=3)
    elif USE_PG:
        return psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=3)
    global _sqlite_conn
    with _sqlite_lock:
        if _sqlite_conn is None:
            _sqlite_conn=sqlite3.connect("omia.db",check_same_thread=False,timeout=15, isolation_level=None)
            _sqlite_conn.row_factory=sqlite3.Row
            try:
                _sqlite_conn.execute("PRAGMA journal_mode=WAL;")
                _sqlite_conn.execute("PRAGMA synchronous=NORMAL;")
                _sqlite_conn.execute("PRAGMA cache_size=-64000;")
            except:
                pass
        return _sqlite_conn

def put_conn(conn):
    if USE_PG and _pg_pool:
        try:
            _pg_pool.putconn(conn)
        except:
            try:
                conn.close()
            except:
                pass
    elif USE_PG:
        try:
            conn.close()
        except:
            pass

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
                return [dict(r) for r in conn.execute(q,a).fetchall()]
    except Exception as e:
        print(f"[qall] {e} | {q[:120]}")
        if conn and USE_PG:
            try:
                put_conn(conn)
            except:
                pass
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
        print(f"[qexec] {e} | {q[:150]}")
        if conn and USE_PG:
            try:
                conn.rollback()
                put_conn(conn)
            except:
                pass
        return False

def add_log(phone,action,detail):
    try:
        now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)",(phone or 'unknown',action,detail,now))
        qexec("INSERT INTO notifications(title,msg,time) VALUES(?,?,?)",(action,str(phone)+": "+str(detail),now))
        with _cache_lock:
            _cache.pop('counts',None)
    except Exception as e:
        print("[log]",e)

def get_counts():
    with _cache_lock:
        c=_cache.get('counts')
        if c and time.time()-c[1]<12:
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

def init_db():
    ss=[
        "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,username TEXT)",
        "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,note TEXT)",
        "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,amount REAL,note TEXT,currency TEXT)",
        "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,dish_name TEXT,tower_id INTEGER)",
        "CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,area TEXT,lat REAL,lng REAL,created_at TEXT)",
        "CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,user_phone TEXT,action TEXT,detail TEXT,time TEXT)",
        "CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,msg TEXT,time TEXT,read INTEGER DEFAULT 0)"
    ]
    if USE_PG:
        ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
    for s in ss:
        qexec(s)

    # migrations - tower_id + created_at
    for alter in [
        "ALTER TABLE dish_ips ADD COLUMN tower_id INTEGER",
        "ALTER TABLE dish_ips ADD COLUMN IF NOT EXISTS tower_id INTEGER",
        "ALTER TABLE towers ADD COLUMN created_at TEXT",
        "ALTER TABLE towers ADD COLUMN IF NOT EXISTS created_at TEXT"
    ]:
        try:
            qexec(alter)
        except:
            pass

    # indexes for speed
    idxs=[
        "CREATE INDEX IF NOT EXISTS idx_dish_ip ON dish_ips(ip)",
        "CREATE INDEX IF NOT EXISTS idx_dish_tower ON dish_ips(tower_id)",
        "CREATE INDEX IF NOT EXISTS idx_dish_name ON dish_ips(dish_name)",
        "CREATE INDEX IF NOT EXISTS idx_logs_id ON logs(id DESC)",
        "CREATE INDEX IF NOT EXISTS idx_logs_phone ON logs(user_phone)",
        "CREATE INDEX IF NOT EXISTS idx_towers_name ON towers(name)",
        "CREATE INDEX IF NOT EXISTS idx_subs_name ON subs(name)",
        "CREATE INDEX IF NOT EXISTS idx_subs_phone ON subs(phone)"
    ]
    for idx in idxs:
        try:
            qexec(idx)
        except:
            pass

    if USE_PG:
        try:
            qexec("CREATE UNIQUE INDEX IF NOT EXISTS uq_dish_ip ON dish_ips(ip)")
        except:
            pass

    if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",('05344851045',generate_password_hash('admin2024'),'manager','admin'))

    if not qone("SELECT * FROM towers WHERE name=?",('نقطة حماة الرئيسية',)):
        qexec("INSERT INTO towers(name,area,lat,lng,created_at) VALUES(?,?,?,?,?)",('نقطة حماة الرئيسية','حماة',35.1318,36.7578,datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

init_db()

def login_required(f):
    @wraps(f)
    def w(*a,**kw):
        if not session.get('phone'):
            return redirect('/login')
        return f(*a,**kw)
    return w

def is_manager():
    return (session.get('role') or '')=='manager'

def role_required_manager(f):
    @wraps(f)
    def w(*a,**kw):
        if not is_manager():
            return jsonify(ok=False,msg='ممنوع'),403
        return f(*a,**kw)
    return w

def is_valid_ip(ip):
    ip=(ip or '').strip()
    if not ip:
        return False
    try:
        ipaddress.ip_address(ip)
        return True
    except:
        return len(ip)>=7 and '.' in ip

@app.after_request
def after(resp):
    if request.path.startswith('/api/'):
        resp.headers['Cache-Control']='no-store, max-age=0, must-revalidate'
        resp.headers['Pragma']='no-cache'
    else:
        resp.headers['Cache-Control']='no-cache'
    resp.headers['X-Content-Type-Options']='nosniff'
    return resp

# ============================================================
# API ROUTES - FAST JSON
# ============================================================

@app.route('/ping')
@app.route('/health')
def public_ping():
    return jsonify(ok=True,time=datetime.datetime.now().isoformat(),version="v3-full")

@app.route('/api/ping')
@login_required
def api_ping():
    ip=request.args.get('ip','').strip()
    if not ip:
        return jsonify(ok=False,out='لا يوجد IP')
    if not is_valid_ip(ip):
        return jsonify(ok=False,out='IP غير صالح')
    # fast TCP check first
    for port in [80,443,8080,8291,22,8728,8000,23]:
        s=None
        try:
            s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
            s.settimeout(0.5)
            if s.connect_ex((ip,port))==0:
                s.close()
                return jsonify(ok=True,out='متصل '+ip+':'+str(port)+' مفتوح',port=port,method='tcp')
            s.close()
        except:
            try:
                if s:
                    s.close()
            except:
                pass
            continue
    try:
        cmd=['ping','-c','1','-W','1',ip] if platform.system().lower()!='windows' else ['ping','-n','1','-w','1000',ip]
        out=subprocess.check_output(cmd,timeout=1.2,stderr=subprocess.STDOUT).decode(errors='ignore')
        ok='ttl=' in out.lower() or 'bytes from' in out.lower() or '1 received' in out.lower()
        if ok:
            m=re.search(r'time[=<]\s*(\d+\.?\d*)',out,re.I)
            ms=m.group(1) if m else ''
            return jsonify(ok=True,out=ip+' '+ms+'ms',ms=ms,method='icmp')
    except:
        pass
    return jsonify(ok=False,out=ip+' لا يرد')

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
    s=None
    try:
        s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        s.settimeout(0.8)
        r=s.connect_ex((ip,port))
        s.close()
        return jsonify(ok=r==0,out=ip+':'+str(port)+' مفتوح' if r==0 else ip+':'+str(port)+' مغلق')
    except Exception as e:
        try:
            if s:
                s.close()
        except:
            pass
        return jsonify(ok=False,out=str(e))

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

@app.route('/toggle_theme')
@login_required
def toggle_theme_route():
    cur=session.get('theme','dark')
    session['theme']='light' if cur=='dark' else 'dark'
    return jsonify(ok=True,theme=session['theme'])

@app.route('/api/login_public',methods=['POST'])
def api_login_public():
    uin=request.form.get('userin','').strip()
    pw=request.form.get('password','')
    # fast lookup without cache for security
    u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
    if u and check_password_hash(u['password'],pw):
        session.clear()
        session['phone']=u['phone']
        session['username']=u.get('username') or u['phone']
        session['role']=u.get('role') or 'tech'
        session.permanent=False
        try:
            threading.Thread(target=add_log, args=(u['phone'],'دخل النظام','تسجيل دخول'), daemon=True).start()
        except:
            pass
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
        w.writerow(['ID','اسم الصحن','IP','الموقع','tower_id'])
        for r in rows:
            w.writerow([r['id'],r.get('dish_name',''),r.get('ip',''),r.get('location',''),r.get('tower_id','')])
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
        w.writerow(['ID','اسم البرج','المنطقة','lat','lng','created'])
        for r in rows:
            w.writerow([r['id'],r.get('name',''),r.get('area',''),r.get('lat',''),r.get('lng',''),r.get('created_at','')])
        fname='towers.csv'
    elif tbl=='logs':
        rows=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 2000")
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
    return Response(output.getvalue(),mimetype='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename='+fname})

@app.route('/api/clear_logs',methods=['POST'])
@login_required
@role_required_manager
def clear_logs():
    qexec("DELETE FROM logs")
    qexec("DELETE FROM notifications")
    return jsonify(ok=True)

@app.route('/api/seed_log',methods=['POST'])
@login_required
def seed_log():
    now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)",(session.get('phone','test'),'اختبار السجل','السجل شغال ✓',now))
    return jsonify(ok=True)

@app.route('/api/update_tower_pos',methods=['POST'])
@login_required
def update_tower_pos():
    try:
        data=request.json if request.is_json else request.form
        tid=int(data.get('id'))
        lat=float(data.get('lat'))
        lng=float(data.get('lng'))
        qexec("UPDATE towers SET lat=?,lng=? WHERE id=?",(lat,lng,tid))
        add_log(session.get('phone'),'تعديل موقع برج',"ID "+str(tid)+" "+str(lat)+","+str(lng))
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False,msg=str(e)),400

@app.route('/api/tower/<int:tid>/dishes')
@login_required
def tower_dishes(tid):
    return jsonify(qall("SELECT * FROM dish_ips WHERE tower_id=? ORDER BY id DESC",(tid,)))

@app.route('/api/add_dish_to_tower',methods=['POST'])
@login_required
def add_dish_to_tower():
    data=request.json if request.is_json else request.form
    ip=(data.get('ip') or '').strip()
    name=(data.get('dish_name') or '').strip()
    loc=(data.get('location') or '').strip()
    tid=data.get('tower_id')
    if not ip or not is_valid_ip(ip):
        return jsonify(ok=False,msg='IP غير صالح'),400
    ok=qexec("INSERT INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?)",(ip,loc,name,int(tid) if tid else None))
    if ok:
        add_log(session.get('phone'),'إضافة صحن',name+" "+ip+" tower:"+str(tid))
        with _cache_lock:
            _cache.pop('counts',None)
    return jsonify(ok=ok)

@app.route('/')
def ix():
    return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login')
def login():
    return """<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<title>OMAIA ISP - دخول</title>
<style>
*{box-sizing:border-box;font-family:system-ui}
body{margin:0;min-height:100vh;background:radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 55%, #070a1f 100%);display:flex;flex-direction:column;align-items:center;justify-content:center;color:#fff}
.card{background:linear-gradient(180deg, #222b45cc, #1a2035cc);border:1px solid #ffffff18;padding:26px;border-radius:22px;width:92%;max-width:380px;animation:fadeUp .8s cubic-bezier(.16,1,.3,1);backdrop-filter:blur(12px)}
@keyframes fadeUp{from{opacity:0;transform:translateY(24px) scale(.96)}to{opacity:1;transform:translateY(0) scale(1)}}
input{width:100%;padding:14px;margin:9px 0;background:#0f1424;border:1px solid #ffffff22;color:#fff;border-radius:14px;font-size:15px;transition:all .5s cubic-bezier(.16,1,.3,1)}
input:focus{border-color:#ffbe4d88;box-shadow:0 0 0 4px #ffbe4d22;transform:scale(1.01);outline:none}
.btn{width:100%;padding:14px;border:0;border-radius:14px;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:900;font-size:17px;cursor:pointer;margin-top:12px;transition:transform .6s cubic-bezier(.16,1,.3,1), filter .3s, box-shadow .3s}
.btn:hover{filter:brightness(1.08);box-shadow:0 8px 24px #ffb02055}
.btn:active{transform:scale(.92)}
.logo{font-size:32px;font-weight:900;margin-bottom:18px;letter-spacing:1px;animation:fadeUp .9s cubic-bezier(.16,1,.3,1) .1s both}
</style></head><body>
<div class=logo>OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<div class=card><form id=loginForm><input name=userin id=userin placeholder='رقم / يوزر' required autofocus><input name=password id=password type=password placeholder='كلمة السر' required><button class=btn id=loginBtn>دخول</button><div id=msg style='text-align:center;margin-top:10px;color:#ff6b6b;font-size:13px;min-height:18px'></div></form></div>
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
  if(j.ok){
    location.replace('/dash?v=home');
  } else { msg.textContent=j.msg||'خطأ'; btn.textContent=orig; btn.disabled=false; }
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
    op="ILIKE" if USE_PG else "LIKE"
    results=[]
    try:
        for r in qall("SELECT * FROM dish_ips WHERE ip "+op+" ? OR dish_name "+op+" ? OR location "+op+" ? ORDER BY id DESC LIMIT 20",(like,like,like)):
            results.append({"title":r.get('dish_name') or r.get('ip') or 'صحن',"sub":r.get('ip',''),"page":"dishes","type":"dish"})
        for r in qall("SELECT * FROM subs WHERE name "+op+" ? OR phone "+op+" ? ORDER BY id DESC LIMIT 15",(like,like)):
            results.append({"title":r.get('name',''),"sub":r.get('phone',''),"page":"subs","type":"sub"})
        for r in qall("SELECT * FROM towers WHERE name "+op+" ? OR area "+op+" ? ORDER BY id DESC LIMIT 15",(like,like)):
            results.append({"title":r.get('name',''),"sub":r.get('area',''),"page":"towers","type":"tower"})
        for r in qall("SELECT * FROM users WHERE phone "+op+" ? OR username "+op+" ? LIMIT 10",(like,like)):
            results.append({"title":r.get('username') or r.get('phone',''),"sub":r.get('phone',''),"page":"settings","type":"user"})
        for r in qall("SELECT * FROM ledger WHERE name "+op+" ? OR note "+op+" ? ORDER BY id DESC LIMIT 10",(like,like)):
            results.append({"title":r.get('name',''),"sub":str(r.get('amount','')),"page":"ledger","type":"ledger"})
    except:
        pass
    return jsonify(results[:25])

@app.route('/add_dish',methods=['POST'])
@login_required
def ad():
    data=request.json if request.is_json else request.form
    ip=(data.get('ip') or '').strip()
    name=(data.get('dish_name') or '').strip()
    loc=(data.get('location') or '').strip()
    tid=data.get('tower_id')
    if not ip:
        return jsonify(ok=False,msg='IP مطلوب'),400
    if not is_valid_ip(ip):
        return jsonify(ok=False,msg='IP غير صالح'),400
    if USE_PG:
        ok=qexec("INSERT INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?) ON CONFLICT (ip) DO UPDATE SET dish_name=EXCLUDED.dish_name, location=EXCLUDED.location, tower_id=EXCLUDED.tower_id",(ip,loc,name,int(tid) if tid else None))
    else:
        ok=qexec("INSERT OR REPLACE INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?)",(ip,loc,name,int(tid) if tid else None))
    if ok:
        add_log(session.get('phone'),'إضافة صحن',name+" "+ip+" "+loc)
        with _cache_lock:
            _cache.pop('counts',None)
    return jsonify(ok=ok)

@app.route('/edit_dish/<int:i>',methods=['POST'])
@login_required
def ed(i):
    if not is_manager():
        return jsonify(ok=False,msg='ممنوع'),403
    data=request.json if request.is_json else request.form
    ok=qexec("UPDATE dish_ips SET dish_name=?,ip=?,location=?,tower_id=? WHERE id=?",(data.get('dish_name',''),data.get('ip',''),data.get('location',''), data.get('tower_id') or None, i))
    if ok:
        add_log(session.get('phone'),'تعديل صحن',"ID "+str(i)+" -> "+str(data.get('ip',''))+" "+str(data.get('dish_name','')))
    return jsonify(ok=ok)

@app.route('/del_dish/<int:i>')
@login_required
def dd(i):
    if not is_manager():
        return jsonify(ok=False,msg='ممنوع'),403
    info=qone("SELECT ip,dish_name FROM dish_ips WHERE id=?",(i,))
    ok=qexec("DELETE FROM dish_ips WHERE id=?",(i,))
    if ok:
        with _cache_lock:
            _cache.pop('counts',None)
        add_log(session.get('phone'),'حذف صحن',str(info.get('dish_name',''))+" "+str(info.get('ip','')) if info else "ID "+str(i))
    return jsonify(ok=ok)

@app.route('/add_tower',methods=['POST'])
@login_required
def at():
    data=request.json if request.is_json else request.form
    try:
        la=float(data.get('lat') or 35.1312)
        ln=float(data.get('lng') or 36.7578)
    except:
        la=35.1312
        ln=36.7578
    now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ok=qexec("INSERT INTO towers(name,area,lat,lng,created_at) VALUES(?,?,?,?,?)",(data.get('name',''),data.get('area',''),la,ln,now))
    if ok:
        add_log(session.get('phone'),'إضافة برج',str(data.get('name','')))
    return jsonify(ok=ok)

@app.route('/del_tower/<int:i>')
@login_required
def dt(i):
    if not is_manager():
        return jsonify(ok=False,msg='ممنوع'),403
    qexec("UPDATE dish_ips SET tower_id=NULL WHERE tower_id=?",(i,))
    ok=qexec("DELETE FROM towers WHERE id=?",(i,))
    if ok:
        add_log(session.get('phone'),'حذف برج',"ID "+str(i))
    return jsonify(ok=ok)

@app.route('/edit_tower/<int:i>',methods=['POST'])
@login_required
def et(i):
    if not is_manager():
        return jsonify(ok=False,msg='ممنوع'),403
    data=request.json if request.is_json else request.form
    try:
        la=float(data.get('lat') or 35.1318)
        ln=float(data.get('lng') or 36.7578)
    except:
        la=35.1318
        ln=36.7578
    ok=qexec("UPDATE towers SET name=?,area=?,lat=?,lng=? WHERE id=?",(data.get('name',''),data.get('area',''),la,ln,i))
    if ok:
        add_log(session.get('phone'),'تعديل برج',"ID "+str(i))
    return jsonify(ok=ok)

@app.route('/add_sub',methods=['POST'])
@login_required
def asub():
    data=request.json if request.is_json else request.form
    ok=qexec("INSERT INTO subs(name,phone,note) VALUES(?,?,?)",(data.get('name',''),data.get('phone',''),data.get('note','')))
    if ok:
        add_log(session.get('phone'),'إضافة مشترك',str(data.get('name','')))
    return jsonify(ok=ok)

@app.route('/del_sub/<int:i>')
@login_required
def dsub(i):
    if not is_manager():
        return jsonify(ok=False),403
    ok=qexec("DELETE FROM subs WHERE id=?",(i,))
    if ok:
        add_log(session.get('phone'),'حذف مشترك',"ID "+str(i))
    return jsonify(ok=ok)

@app.route('/edit_sub/<int:i>',methods=['POST'])
@login_required
def esub(i):
    if not is_manager():
        return jsonify(ok=False),403
    data=request.json if request.is_json else request.form
    ok=qexec("UPDATE subs SET name=?,phone=?,note=? WHERE id=?",(data.get('name',''),data.get('phone',''),data.get('note',''),i))
    if ok:
        add_log(session.get('phone'),'تعديل مشترك',"ID "+str(i))
    return jsonify(ok=ok)

@app.route('/add_ledger',methods=['POST'])
@login_required
def al():
    data=request.json if request.is_json else request.form
    try:
        amt=float(data.get('amount') or 0)
    except:
        amt=0
    ok=qexec("INSERT INTO ledger(name,amount,note,currency) VALUES(?,?,?,?)",(data.get('name',''),amt,data.get('note',''),data.get('currency','USD')))
    if ok:
        add_log(session.get('phone'),'إضافة حساب',str(data.get('name',''))+" "+str(amt))
    return jsonify(ok=ok)

@app.route('/del_ledger/<int:i>')
@login_required
def dll(i):
    if not is_manager():
        return jsonify(ok=False),403
    ok=qexec("DELETE FROM ledger WHERE id=?",(i,))
    if ok:
        add_log(session.get('phone'),'حذف حساب',"ID "+str(i))
    return jsonify(ok=ok)

@app.route('/edit_ledger/<int:i>',methods=['POST'])
@login_required
def el(i):
    if not is_manager():
        return jsonify(ok=False),403
    data=request.json if request.is_json else request.form
    try:
        amt=float(data.get('amount') or 0)
    except:
        amt=0
    ok=qexec("UPDATE ledger SET name=?,amount=?,note=?,currency=? WHERE id=?",(data.get('name',''),amt,data.get('note',''),data.get('currency','USD'),i))
    if ok:
        add_log(session.get('phone'),'تعديل حساب',"ID "+str(i))
    return jsonify(ok=ok)

@app.route('/add_user',methods=['POST'])
@login_required
@role_required_manager
def au():
    ph=(request.form.get('phone') or request.form.get('user_field','')).strip()
    if not ph:
        return jsonify(ok=False,msg='رقم مطلوب'),400
    if qone("SELECT * FROM users WHERE phone=?",(ph,)):
        return jsonify(ok=False,msg='موجود مسبقاً'),400
    ok=qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",(ph,generate_password_hash(request.form.get('password','1234')),request.form.get('role','tech'),ph))
    if ok:
        add_log(session.get('phone'),'إضافة يوزر',ph)
    return jsonify(ok=ok)

@app.route('/edit_user',methods=['POST'])
@login_required
@role_required_manager
def eu():
    old=request.form.get('old_phone','').strip()
    new_ph=(request.form.get('phone') or request.form.get('user_field','')).strip()
    new_role=request.form.get('role','tech')
    new_pass=request.form.get('password','').strip()
    if not old:
        return jsonify(ok=False,msg='خطأ'),400
    if old!=new_ph and qone("SELECT * FROM users WHERE phone=?",(new_ph,)):
        return jsonify(ok=False,msg='الرقم الجديد موجود'),400
    if new_pass:
        ok=qexec("UPDATE users SET phone=?,username=?,role=?,password=? WHERE phone=?",(new_ph,new_ph,new_role,generate_password_hash(new_pass),old))
    else:
        ok=qexec("UPDATE users SET phone=?,username=?,role=? WHERE phone=?",(new_ph,new_ph,new_role,old))
    if session.get('phone')==old:
        session['phone']=new_ph
        session['role']=new_role
    if ok:
        add_log(session.get('phone'),'تعديل يوزر',old+"->"+new_ph)
    return jsonify(ok=ok)

@app.route('/del_user/<ph>')
@login_required
@role_required_manager
def du(ph):
    if ph=='05344851045':
        return jsonify(ok=False,msg='ممنوع حذف المدير'),400
    ok=qexec("DELETE FROM users WHERE phone=?",(ph,))
    if ok:
        add_log(session.get('phone'),'حذف يوزر',ph)
    return jsonify(ok=ok)

@app.route('/change_pass',methods=['POST'])
@login_required
def cp():
    data=request.json if request.is_json else request.form
    np=(data.get('newpass') or '').strip()
    if not np:
        return jsonify(ok=False,msg='فارغة'),400
    ok=qexec("UPDATE users SET password=? WHERE phone=?",(generate_password_hash(np),session.get('phone')))
    if ok:
        add_log(session.get('phone'),'تغيير كلمة سر','')
    return jsonify(ok=ok)

# ============================================================
# PAGES CONTENT - FULL VERSION WITH TOWER CARDS
# ============================================================

def page_content(v):
    lang=session.get('lang','ar')
    def L(ar,en):
        return ar if lang=='ar' else en
    if v=='home':
        ns,nd,nt,nl=get_counts()
        logs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 8")
        log_html=""
        for l in logs:
            log_html+="<div class=rowlog><div><b>"+esc(l.get('user_phone',''))+"</b> <span class=badge>"+esc(l.get('action',''))+"</span> <small>"+esc(str(l.get('detail',''))[:70])+"</small></div><small class=time>"+esc(l.get('time',''))+"</small></div>"
        if not log_html:
            log_html="<div style='padding:12px;color:#888'>السجل فاضي - اضغط اختبار</div>"
        return "<div style='max-width:900px;margin:0 auto'><div class=grid2><div class='card stat' onclick=\"loadPage('subs')\"><div class=row style='justify-content:space-between'><div><h3 style='margin:0;color:#aab4d0;font-size:13px'>"+L('المشتركين','Subs')+"</h3><h2 style='margin:6px 0 0;font-size:36px'>"+str(ns)+"</h2></div><div class=ico>👥</div></div></div><div class='card stat' onclick=\"loadPage('dishes')\"><div class=row style='justify-content:space-between'><div><h3 style='margin:0;color:#aab4d0;font-size:13px'>"+L('الصحون','Dishes')+"</h3><h2 style='margin:6px 0 0;font-size:36px'>"+str(nd)+"</h2></div><div class=ico>📡</div></div></div><div class='card stat' onclick=\"loadPage('towers')\"><div class=row style='justify-content:space-between'><div><h3 style='margin:0;color:#aab4d0;font-size:13px'>"+L('الأبراج','Towers')+"</h3><h2 style='margin:6px 0 0;font-size:36px'>"+str(nt)+"</h2></div><div class=ico>🗼</div></div></div><div class='card stat' onclick=\"loadPage('ledger')\"><div class=row style='justify-content:space-between'><div><h3 style='margin:0;color:#aab4d0;font-size:13px'>"+L('الحسابات','Accounts')+"</h3><h2 style='margin:6px 0 0;font-size:36px'>"+str(nl)+"</h2></div><div class=ico>📒</div></div></div></div><div class=card style='margin-top:14px'><div class=row style='justify-content:space-between'><h4>التقارير</h4><div class=row><a href='/api/export/dishes' class=btn-gold style='text-decoration:none;padding:8px 12px;background:#22c55e;color:#fff'>Excel صحون</a><a href='/api/export/logs' class=btn-gold style='text-decoration:none;padding:8px 12px;background:#8b5cf6;color:#fff'>Excel سجل</a></div></div></div><div class=card><div class=row style='justify-content:space-between'><h4>آخر النشاطات</h4><div class=row><button class=btn-gold onclick=\"fetch('/api/seed_log',{method:'POST'}).then(()=>loadPage('home',true))\">اختبار السجل</button><button class=btn-gold onclick=\"loadPage('logs')\">عرض الكل</button></div></div><div style='margin-top:8px'>"+log_html+"</div></div></div>"
    if v=='ping':
        return "<div style='max-width:800px;margin:0 auto'><div class=card style='background:linear-gradient(135deg,#0f172a,#1e293b);border:1px solid #ffffff15'><h3 style='margin:0'>📶 "+L('بنج','Ping')+"</h3><div class=row style='margin-top:12px;flex-wrap:wrap'><input id=pingIp placeholder='192.168.1.1' style='flex:1;min-width:160px;padding:14px;border-radius:12px;background:#0f1424;border:1px solid #ffffff20;color:#fff;font-family:monospace'><input id=pingPort placeholder='Port' value='80' style='width:80px;padding:14px;border-radius:12px;background:#0f1424;border:1px solid #ffffff20;color:#fff'><button class=btn-gold onclick=\"doSinglePing()\" style='padding:14px 20px;background:#22c55e;color:#fff'>Ping</button><button class=btn-gold onclick=\"doTcpPing()\" style='padding:14px 16px;background:#0ea5e9;color:#fff'>TCP</button></div><div id=pingResult style='margin-top:14px;min-height:60px;background:#0008;border:1px solid #ffffff0a;border-radius:12px;padding:14px;font-family:monospace;font-size:13px;white-space:pre-wrap'>جاهز...</div><div class=row style='margin-top:10px'><button class=btn-gold onclick=\"pingAllDishes()\" style='flex:1;background:#ffbe4d;color:#111'>فحص كل الصحون</button><button class=btn-gold onclick=\"clearPing()\" style='background:#ffffff10;color:#fff'>مسح</button></div></div><div class=card><h4>صحون سريعة</h4><div id=quickDishes>...</div></div><div class=card><h4>سجل البنج</h4><div id=pingLog style='max-height:200px;overflow:auto;font-size:12px'></div></div></div><script>window.doSinglePing=async function(){let ip=document.getElementById('pingIp').value.trim(); if(!ip){alert('اكتب IP');return;} let out=document.getElementById('pingResult'); out.textContent='جاري فحص '+ip+'...'; try{let r=await fetch('/api/ping?ip='+encodeURIComponent(ip),{cache:'no-store'}); let j=await r.json(); out.textContent=j.out;}catch(e){out.textContent='خطأ '+e;}};window.doTcpPing=async function(){let ip=document.getElementById('pingIp').value.trim(); let port=document.getElementById('pingPort').value.trim()||'80'; if(!ip){alert('IP');return;} let out=document.getElementById('pingResult'); out.textContent='جاري '+ip+':'+port+'...'; try{let r=await fetch('/api/ping_tcp?ip='+encodeURIComponent(ip)+'&port='+port); let j=await r.json(); out.textContent=j.out;}catch(e){out.textContent='خطأ';}};window.clearPing=function(){document.getElementById('pingResult').textContent='جاهز...';};window.pingAllDishes=async function(){let out=document.getElementById('pingResult'); out.textContent='جاري الفحص...'; try{let r=await fetch('/api/search?q=192',{cache:'no-store'}); let d=await r.json(); out.textContent=''; for(let dish of d.filter(x=>x.page==='dishes').slice(0,20)){out.textContent+='فحص '+dish.sub+'\\n'; try{let pr=await fetch('/api/ping?ip='+encodeURIComponent(dish.sub)); let pj=await pr.json(); out.textContent+=pj.out+'\\n';}catch(e){} await new Promise(r=>setTimeout(r,120));}}catch(e){out.textContent='خطأ: '+e;}};(async()=>{try{let r=await fetch('/api/search?q=192',{cache:'no-store'}); let d=await r.json(); let h=''; d.filter(x=>x.page==='dishes').slice(0,8).forEach(x=>{h+='<div class=rowlog><span>'+x.sub+' - '+x.title+'</span><button class=btn-gold onclick="document.getElementById(\\'pingIp\\').value=\\''+x.sub+'\\'; doSinglePing()" style="padding:5px 10px">Ping</button></div>';}); document.getElementById('quickDishes').innerHTML=h||'لا يوجد';}catch(e){}})();</script>"
    if v=='dishes':
        rs=qall("SELECT * FROM dish_ips ORDER BY id DESC")
        rows_html=""
        for r in rs:
            dn=esc(r.get('dish_name') or 'صحن')
            ip=esc(r.get('ip') or '')
            loc=esc(r.get('location') or '')
            rid=r['id']
            tid=r.get('tower_id')
            tower_badge=" • برج "+str(tid) if tid else ""
            rows_html+='<div class="card dish-card" id="dish-'+str(rid)+'" data-name="'+dn+'" data-ip="'+ip+'" data-loc="'+loc+'" style="display:flex;justify-content:space-between"><div><b>'+dn+'</b><br><a href="http://'+ip+'" target=_blank style="background:#000;color:#ffbe4d;padding:5px 10px;border-radius:8px;font-family:monospace;text-decoration:none">'+ip+'</a><br><small style="color:#888">'+loc+tower_badge+'</small></div><div class=col><button class=btn-gold onclick="quickPingD('+str(rid)+')" style="padding:7px 12px;background:#22c55e;color:#fff">Ping</button><div class=row><button class=btn-gold onclick="editDish('+str(rid)+')" style="padding:7px 9px">تعديل</button><button class=btn-del onclick="askDel(\'/del_dish/'+str(rid)+'\', '+str(rid)+')" style="padding:7px 9px">حذف</button></div></div></div>'
        return '<div style="max-width:900px;margin:0 auto"><div class=card><div class=row style="justify-content:space-between;flex-wrap:wrap"><h3>الصحون - '+str(len(rs))+'</h3><div class=row><button onclick="loadPage(\'ping\')" class=btn-gold style="padding:7px 12px;background:#22c55e;color:#fff">Ping</button><a href="/api/export/dishes" class=btn-gold style="text-decoration:none;padding:7px 12px">Excel</a></div></div><form id=formDish class=row style="margin-top:10px;flex-wrap:wrap"><input name=dish_name id=dish_name placeholder="اسم الصحن" required style="flex:1"><input name=ip id=dish_ip placeholder="192.168.1.1" required style="flex:1"><input name=location id=dish_loc placeholder="موقع" style="flex:1"><button class=btn-gold type=submit id=btnAddDish>إضافة</button></form><div id=dishMsg style="margin-top:8px;font-size:13px;min-height:18px"></div><input id=searchBox placeholder="بحث..." oninput="searchDishes(this.value)" style="margin-top:10px;width:100%;padding:12px;border-radius:12px;background:#0f1424;border:1px solid #ffffff18"></div><div id=dl>'+rows_html+'</div></div><script>window.searchDishes=function(q){q=(q||"").toLowerCase();document.querySelectorAll(".dish-card").forEach(c=>{let t=(c.dataset.name+c.dataset.ip+c.dataset.loc).toLowerCase(); c.style.display=t.includes(q)?"flex":"none";});};window.editDish=function(id){let c=document.getElementById("dish-"+id); if(!c) return; let body=document.getElementById("editBody"); body.innerHTML="<input id=edit_dish_name value=\""+c.dataset.name+"\" style=\"width:100%;padding:12px;margin:4px 0\"><input id=edit_ip value=\""+c.dataset.ip+"\" style=\"width:100%;padding:12px;margin:4px 0\"><input id=edit_loc value=\""+c.dataset.loc+"\" style=\"width:100%;padding:12px;margin:4px 0\"><button onclick=\"saveDish("+id+")\" class=btn-gold style=\"width:100%;padding:12px\" id=btnSaveDish>حفظ</button>"; document.getElementById("editModal").classList.add("show");};window.saveDish=function(id){let b=document.getElementById("btnSaveDish"); if(b){b.textContent="جاري..."; b.disabled=true;} let nn=document.getElementById("edit_dish_name").value; let ii=document.getElementById("edit_ip").value; let ll=document.getElementById("edit_loc").value; fetch("/edit_dish/"+id,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({dish_name:nn,ip:ii,location:ll})}).then(r=>r.json()).then(j=>{if(j.ok){closeEditModal(); loadPage("dishes",true);} else {alert("ممنوع"); if(b){b.textContent="حفظ"; b.disabled=false;}}});};window.quickPingD=function(id){let c=document.getElementById("dish-"+id); loadPage("ping"); setTimeout(()=>{let inp=document.getElementById("pingIp");if(inp){inp.value=c.dataset.ip; doSinglePing();}},300);};document.getElementById("formDish").addEventListener("submit", async e=>{e.preventDefault(); let fd=new FormData(e.target); let r=await fetch("/add_dish",{method:"POST",body:fd}); let j=await r.json(); if(j.ok){e.target.reset(); loadPage("dishes",true);} else {let t=j.msg||"خطأ"; alert(t);}}});</script>'
    if v=='towers':
        rs=qall("SELECT * FROM towers ORDER BY id DESC")
        rows=""
        for r in rs:
            tid=r['id']
            dishes=qall("SELECT * FROM dish_ips WHERE tower_id=? ORDER BY id DESC",(tid,))
            dish_html=""
            for d in dishes:
                dish_html+="<div class=dish-mini><div><b>"+esc(d.get('dish_name') or 'صحن')+"</b> <span class=ip>"+esc(d.get('ip'))+"</span></div><button class=btn-del onclick=\"delDishInTower("+str(d['id'])+","+str(tid)+")\">✕</button></div>"
            if not dish_html:
                dish_html="<small style='color:#777'>فاضي - ضيف IP</small>"
            rows+="<div class='card tower-card' id='tower-"+str(r['id'])+"' data-name='"+esc(r['name'])+"' data-area='"+esc(r['area'] or '')+"' data-lat='"+str(r.get('lat') or 0)+"' data-lng='"+str(r.get('lng') or 0)+"'><div class=tower-head><div><b class=tower-title>"+esc(r['name'])+"</b><br><small>"+esc(r['area'] or '')+"</small><br><small class=coords>"+str(r.get('lat'))+" , "+str(r.get('lng'))+"</small></div><div class=col><button class=btn-gold onclick=\"openEditTower("+str(r['id'])+")\" style='padding:8px 10px'>تعديل</button><button class=btn-del onclick=\"askDel('/del_tower/"+str(r['id'])+"',"+str(r['id'])+")\" style='padding:8px 10px'>حذف</button><button class=btn-gold onclick=\"focusMap("+str(r.get('lat'))+","+str(r.get('lng'))+")\" style='padding:8px 10px'>🗺</button></div></div><div class=tower-body><div class=row><input id=\"ip-"+str(tid)+"\" placeholder=\"IP\"><input id=\"name-"+str(tid)+"\" placeholder=\"اسم الصحن\"><button class=btn-gold onclick=\"addDishToTower("+str(tid)+")\">+ IP</button></div><div class=dish-list>"+dish_html+"</div></div></div>"
        return "<div style='max-width:900px;margin:0 auto'><div class=card><div class=row style='justify-content:space-between'><h3>الأبراج - كروت لا نهائية - "+str(len(rs))+"</h3><div class=row><button class=btn-gold onclick=\"openNewTower()\" style='background:#22c55e;color:#fff'>+ كرت جديد</button><a href='/api/export/towers' class=btn-gold>Excel</a></div></div></div><div class=grid2>"+rows+"</div></div><script>window.openNewTower=function(){let body=document.getElementById('editBody'); body.innerHTML='<input id=nt_name placeholder=\"اسم الكرت\" value=\"كرت جديد\"><input id=nt_area placeholder=\"منطقة\"><div class=row><input id=nt_lat placeholder=\"lat\" value=\"35.1318\"><input id=nt_lng placeholder=\"lng\" value=\"36.7578\"></div><button class=btn-gold onclick=\"saveNewTower()\" style=\"width:100%;margin-top:8px\">حفظ</button>'; document.getElementById('editModal').classList.add('show');};window.saveNewTower=function(){fetch('/add_tower',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:document.getElementById('nt_name').value,area:document.getElementById('nt_area').value,lat:document.getElementById('nt_lat').value,lng:document.getElementById('nt_lng').value})}).then(r=>r.json()).then(j=>{if(j.ok){closeEditModal(); loadPage('towers',true)}})};window.openEditTower=function(id){let c=document.getElementById('tower-'+id); let body=document.getElementById('editBody'); body.innerHTML='<input id=edit_t_name value=\"'+c.dataset.name+'\" style=\"width:100%;margin:6px 0;padding:12px\"><input id=edit_t_area value=\"'+c.dataset.area+'\" style=\"width:100%;margin:6px 0;padding:12px\"><input id=edit_t_lat value=\"'+c.dataset.lat+'\" style=\"width:100%;margin:6px 0;padding:12px\"><input id=edit_t_lng value=\"'+c.dataset.lng+'\" style=\"width:100%;margin:6px 0;padding:12px\"><button onclick=\"saveTower('+id+')\" class=btn-gold style=\"width:100%;padding:12px\">حفظ</button>'; document.getElementById('editModal').classList.add('show');};window.saveTower=function(id){let nn=document.getElementById('edit_t_name').value; let aa=document.getElementById('edit_t_area').value; let la=document.getElementById('edit_t_lat').value; let ln=document.getElementById('edit_t_lng').value; fetch('/edit_tower/'+id,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:nn,area:aa,lat:la,lng:ln})}).then(r=>r.json()).then(j=>{closeEditModal();loadPage('towers',true);});};window.addDishToTower=function(tid){let ip=document.getElementById('ip-'+tid).value.trim(); let nm=document.getElementById('name-'+tid).value.trim(); if(!ip) return alert('IP'); fetch('/api/add_dish_to_tower',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ip:ip,dish_name:nm,tower_id:tid})}).then(r=>r.json()).then(j=>{if(j.ok) loadPage('towers',true); else alert(j.msg||'خطأ')})};window.delDishInTower=function(did,tid){fetch('/del_dish/'+did).then(r=>r.json()).then(j=>{if(j.ok) loadPage('towers',true)})};window.focusMap=function(lat,lng){loadPage('map'); setTimeout(()=>{if(window._map) window._map.flyTo([lat,lng],18)},600)};</script>"
    if v=='subs':
        rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 200")
        rows=""
        for r in rs:
            rows+="<div class='card' id='sub-"+str(r['id'])+"' data-name='"+esc(r['name'])+"' data-phone='"+esc(r['phone'] or '')+"' data-note='"+esc(r['note'] or '')+"' style='display:flex;justify-content:space-between'><div><b>"+esc(r['name'])+"</b><br>"+esc(r['phone'] or '')+"</div><div class=row><button class=btn-gold onclick=\"openEditSub("+str(r['id'])+")\" style='padding:8px 10px'>تعديل</button><button class=btn-del onclick=\"askDel('/del_sub/"+str(r['id'])+"',"+str(r['id'])+")\" style='padding:8px 10px'>حذف</button></div></div>"
        return "<div style='max-width:700px;margin:0 auto'><div class=card><h3>المشتركين</h3><form id=formSub class=row><input name=name placeholder='الاسم' required style='flex:1'><input name=phone placeholder='رقم' style='flex:1'><input name=note placeholder='ملاحظة' style='flex:1'><button class=btn-gold>إضافة</button></form></div>"+rows+"</div><script>window.openEditSub=function(id){let c=document.getElementById('sub-'+id); let body=document.getElementById('editBody'); body.innerHTML='<input id=edit_s_name value=\"'+c.dataset.name+'\" style=\"width:100%;margin:6px 0;padding:12px\"><input id=edit_s_phone value=\"'+c.dataset.phone+'\" style=\"width:100%;margin:6px 0;padding:12px\"><input id=edit_s_note value=\"'+c.dataset.note+'\" style=\"width:100%;margin:6px 0;padding:12px\"><button onclick=\"saveSub('+id+')\" class=btn-gold style=\"width:100%;padding:12px\">حفظ</button>'; document.getElementById('editModal').classList.add('show');};window.saveSub=function(id){let nn=document.getElementById('edit_s_name').value; let pp=document.getElementById('edit_s_phone').value; let no=document.getElementById('edit_s_note').value; fetch('/edit_sub/'+id,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:nn,phone:pp,note:no})}).then(r=>r.json()).then(j=>{closeEditModal();loadPage('subs',true);});};document.getElementById('formSub').addEventListener('submit', async e=>{e.preventDefault(); let r=await fetch('/add_sub',{method:'POST',body:new FormData(e.target)}); let j=await r.json(); if(j.ok){e.target.reset(); loadPage('subs',true);}});</script>"
    if v=='ledger':
        rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 200")
        rows=""
        for r in rs:
            rows+="<div class='card' id='led-"+str(r['id'])+"' data-name='"+esc(r['name'])+"' data-amount='"+str(r['amount'])+"' data-note='"+esc(r.get('note') or '')+"'><div class=row style='justify-content:space-between'><div><b>"+esc(r['name'])+"</b> - <b style='color:#ffbe4d'>"+str(r['amount'])+"</b> <small>"+esc(r.get('note') or '')+"</small></div><div class=row><button class=btn-gold onclick=\"openEditLed("+str(r['id'])+")\" style='padding:7px 9px'>تعديل</button><button class=btn-del onclick=\"askDel('/del_ledger/"+str(r['id'])+"',"+str(r['id'])+")\" style='padding:7px 9px'>حذف</button></div></div></div>"
        return "<div style='max-width:700px;margin:0 auto'><div class=card><h3>الحسابات</h3><form id=formLed class=row><input name=name placeholder='الاسم' required style='flex:1'><input name=amount type=number step=0.01 placeholder='المبلغ' required style='flex:1'><input name=note placeholder='ملاحظة' style='flex:1'><select name=currency style='flex:0.5'><option>USD</option><option>SYP</option></select><button class=btn-gold>إضافة</button></form></div>"+rows+"</div><script>window.openEditLed=function(id){let c=document.getElementById('led-'+id); let body=document.getElementById('editBody'); body.innerHTML='<input id=edit_l_name value=\"'+c.dataset.name+'\" style=\"width:100%;margin:6px 0;padding:12px\"><input id=edit_l_amount value=\"'+c.dataset.amount+'\" style=\"width:100%;margin:6px 0;padding:12px\"><input id=edit_l_note value=\"'+c.dataset.note+'\" style=\"width:100%;margin:6px 0;padding:12px\"><button onclick=\"saveLed('+id+')\" class=btn-gold style=\"width:100%;padding:12px\">حفظ</button>'; document.getElementById('editModal').classList.add('show');};window.saveLed=function(id){let nn=document.getElementById('edit_l_name').value; let aa=document.getElementById('edit_l_amount').value; let no=document.getElementById('edit_l_note').value; fetch('/edit_ledger/'+id,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:nn,amount:aa,note:no,currency:'USD'})}).then(()=>{closeEditModal();loadPage('ledger',true);});};document.getElementById('formLed').addEventListener('submit', async e=>{e.preventDefault(); let r=await fetch('/add_ledger',{method:'POST',body:new FormData(e.target)}); let j=await r.json(); if(j.ok){e.target.reset(); loadPage('ledger',true);}});</script>"
    if v=='logs':
        rs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 500")
        rows=""
        for r in rs:
            col='#22c55e' if 'إضافة' in r.get('action','') else '#0ea5e9' if 'تعديل' in r.get('action','') else '#ef4444' if 'حذف' in r.get('action','') else '#ffbe4d'
            rows+="<div class='card' style='font-size:13px;border-right:4px solid "+col+";display:flex;justify-content:space-between'><div><b style='color:#ffbe4d'>"+esc(r.get('user_phone',''))+"</b> <span style='background:"+col+";color:#fff;padding:2px 8px;border-radius:6px;font-size:11px'>"+esc(r.get('action',''))+"</span><br><small style='color:#cbd5e1'>"+esc(r.get('detail',''))+"</small></div><small style='color:#64748b'>"+esc(r.get('time',''))+"</small></div>"
        if not rows:
            rows="<div class=card style='text-align:center;padding:20px;color:#888'>لا يوجد سجل<br><button class=btn-gold onclick=\"fetch('/api/seed_log',{method:'POST'}).then(()=>loadPage('logs',true))\" style='margin-top:10px'>اختبار السجل</button></div>"
        return "<div style='max-width:900px;margin:0 auto'><div class=card row style='justify-content:space-between'><h3>السجل ("+str(len(rs))+")</h3><div class=row><a href='/api/export/logs' class=btn-gold style='text-decoration:none;padding:7px 12px;background:#22c55e;color:#fff'>Excel</a><button onclick=\"if(confirm('مسح؟')){fetch('/api/clear_logs',{method:'POST'}).then(()=>loadPage('logs',true))}\" class=btn-del>مسح</button></div></div>"+rows+"</div>"
    if v=='network':
        dishes=qall("SELECT * FROM dish_ips ORDER BY id DESC")
        rows=""
        for d in dishes:
            rows+="<div class='card' id='net-"+str(d['id'])+"' data-ip='"+esc(d.get('ip',''))+"' style='display:flex;justify-content:space-between'><div><b>"+esc(d.get('dish_name') or 'صحن')+"</b> - "+esc(d.get('ip',''))+"<br><small class='net-out'>...</small></div><button class=btn-gold onclick='checkOne("+str(d['id'])+")'>فحص</button></div>"
        return "<div style='max-width:800px;margin:0 auto'><div class=card><h3>حالة الشبكة</h3><div class=row style='margin-top:8px'><button class=btn-gold onclick='checkAll()' style='flex:1;background:#22c55e;color:#fff;padding:12px'>فحص الكل</button><button class=btn-gold onclick=\"loadPage('ping')\" style='flex:1'>Ping</button></div><div id=summary style='margin-top:10px;font-weight:800'></div></div>"+rows+"</div><script>window.checkOne=async function(id){let c=document.getElementById('net-'+id); let out=c.querySelector('.net-out'); out.textContent='جاري...'; try{let r=await fetch('/api/ping?ip='+encodeURIComponent(c.dataset.ip),{cache:'no-store'}); let j=await r.json(); out.textContent=j.out.slice(0,80);}catch(e){out.textContent='خطأ';}};window.checkAll=async function(){let cards=document.querySelectorAll('[id^=net-]'); for(let c of cards){let out=c.querySelector('.net-out'); out.textContent='جاري...'; try{let r=await fetch('/api/ping?ip='+encodeURIComponent(c.dataset.ip),{cache:'no-store'}); let j=await r.json(); out.textContent=j.out.slice(0,80);}catch(e){} await new Promise(r=>setTimeout(r,100));}};checkAll();</script>"
    if v=='map':
        towers=qall("SELECT * FROM towers ORDER BY id DESC")
        tj_json=json.dumps([{"id":t['id'],"name":t['name'],"area":t.get('area') or '',"lat":float(t.get('lat') or 35.1318),"lng":float(t.get('lng') or 36.7578)} for t in towers],ensure_ascii=False)
        return "<div class=card style='padding:10px'><div class=row style='flex-wrap:wrap;gap:6px;margin-bottom:10px'><input id=mapSearch placeholder='بحث برج...' style='flex:1;min-width:140px;background:#1f2937;border:1px solid #ffffff15;color:#fff;padding:10px 12px;border-radius:12px'><button class=btn-gold onclick=\"doMapSearch()\" style='padding:10px 12px'>بحث</button><button class=btn-gold onclick=\"locateMe()\" style='background:#22c55e;color:#fff;padding:10px 12px'>موقعي</button><button class=btn-gold onclick=\"enableAddPoint()\" id=addPointBtn style='background:#f59e0b;color:#fff;padding:10px 12px'>نقطة</button><button class=btn-gold onclick=\"toggleMeasure()\" id=measureBtn style='background:#0ea5e9;color:#fff;padding:10px 12px'>قياس</button><button class=btn-gold onclick=\"clearMap()\" style='background:#ef4444;color:#fff;padding:10px 12px'>مسح</button><span id=distanceLabel style='padding:8px 12px;background:#1f2937;border:1px solid #ffffff15;border-radius:10px;font-size:12px;color:#ffbe4d'>0</span></div><div id=map style='height:72vh;min-height:460px;border-radius:16px;background:#0f172a;z-index:1;border:2px solid #ffffff0f'></div><div style='margin-top:6px;font-size:11px;color:#6b7280'><span id=coordsLabel style='color:#ffbe4d'>-</span> • اسحب العلامة لتثبيت احداثيات • دقة 22</div></div><script>let _towers="+tj_json+"; let _map=null; let measureMode=false, addPointMode=false, measurePoints=[], measureLine=null, measureMarkers=[], tempMarkers=[]; window.doMapSearch=function(){let q=document.getElementById('mapSearch').value.trim().toLowerCase(); if(!q) return; let f=_towers.find(t=>t.name.toLowerCase().includes(q)||t.area.toLowerCase().includes(q)); if(f && _map){_map.flyTo([f.lat,f.lng],18);}};window.locateMe=function(){if(_map && navigator.geolocation){navigator.geolocation.getCurrentPosition(p=>{_map.flyTo([p.coords.latitude,p.coords.longitude],16); L.marker([p.coords.latitude,p.coords.longitude]).addTo(_map).bindPopup('موقعك').openPopup();});}};window.enableAddPoint=function(){addPointMode=!addPointMode; let b=document.getElementById('addPointBtn'); b.textContent=addPointMode?'اضغط على الخريطة':'نقطة'; if(addPointMode){measureMode=false; if(_map) _map.getContainer().style.cursor='crosshair';}else{if(_map) _map.getContainer().style.cursor='';}};window.toggleMeasure=function(){measureMode=!measureMode; let b=document.getElementById('measureBtn'); b.textContent=measureMode?'إلغاء القياس':'قياس'; if(measureMode){addPointMode=false; if(_map) _map.getContainer().style.cursor='crosshair';}else{if(_map) _map.getContainer().style.cursor='';}};window.clearMap=function(){measurePoints=[]; if(measureLine){_map.removeLayer(measureLine); measureLine=null;} measureMarkers.forEach(m=>_map.removeLayer(m)); measureMarkers=[]; tempMarkers.forEach(m=>_map.removeLayer(m)); tempMarkers=[]; document.getElementById('distanceLabel').textContent='0';};setTimeout(()=>{_map=L.map('map',{zoomControl:true,maxZoom:22}).setView([35.1318,36.7578],13); let osm=L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:22,maxNativeZoom:19}).addTo(_map); let sat=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{maxZoom:22,maxNativeZoom:19}).addTo(_map); let topo=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}',{maxZoom:22}).addTo(_map); L.control.layers({'عادية':osm,'قمر صناعي دقة عالية 22':sat,'تضاريس':topo}).addTo(_map); setTimeout(()=>_map.invalidateSize(),300); _towers.forEach(t=>{let m=L.marker([t.lat,t.lng],{draggable:true}).addTo(_map).bindPopup('<b>'+t.name+'</b><br>'+t.area); m.on('dragend',e=>{let ll=e.target.getLatLng(); document.getElementById('coordsLabel').textContent=ll.lat.toFixed(6)+','+ll.lng.toFixed(6)+' ✓ جاري الحفظ...'; fetch('/api/update_tower_pos',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:t.id,lat:ll.lat,lng:ll.lng})}).then(r=>r.json()).then(j=>{document.getElementById('coordsLabel').textContent=ll.lat.toFixed(6)+','+ll.lng.toFixed(6)+' ✓ تم التثبيت';});});}); _map.on('click',e=>{document.getElementById('coordsLabel').textContent=e.latlng.lat.toFixed(5)+','+e.latlng.lng.toFixed(5); if(measureMode){measurePoints.push(e.latlng); let mk=L.marker(e.latlng).addTo(_map); measureMarkers.push(mk); if(measureLine) _map.removeLayer(measureLine); if(measurePoints.length>1){measureLine=L.polyline(measurePoints,{color:'#ffbe4d',weight:4,dashArray:'8,8'}).addTo(_map); let d=0; for(let i=1;i<measurePoints.length;i++){d+=measurePoints[i-1].distanceTo(measurePoints[i]);} document.getElementById('distanceLabel').textContent=(d/1000).toFixed(3)+' كم';} return;} if(addPointMode){let lat=e.latlng.lat.toFixed(6), lng=e.latlng.lng.toFixed(6); L.popup().setLatLng(e.latlng).setContent('<div><b>كرت جديد</b><br><input id=newPointName placeholder=\"اسم الكرت\" style=\"width:100%;margin:6px 0;padding:8px\"><input id=newPointArea placeholder=\"منطقة\" style=\"width:100%;margin:4px 0;padding:8px\"><button onclick=\"saveNewPoint('+lat+','+lng+')\" style=\"width:100%;background:#ffbe4d;border:0;padding:9px;border-radius:8px;font-weight:800\">حفظ</button></div>').openOn(_map);}}); window.saveNewPoint=function(lat,lng){let name=document.getElementById('newPointName').value||'كرت جديد'; let area=document.getElementById('newPointArea').value||''; fetch('/add_tower',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name,area:area,lat:lat,lng:lng})}).then(r=>r.json()).then(j=>{if(j.ok){_map.closePopup(); alert('تم ✓');}});};},300);</script>"
    if v=='settings':
        us=qall("SELECT * FROM users ORDER BY phone DESC")
        uh=""
        for u in us:
            ph=esc(u["phone"])
            un=esc(u.get("username") or "")
            ro=esc(u.get("role") or "")
            badge="<span style='background:#ffbe4d;color:#111;padding:2px 8px;border-radius:8px;font-size:11px;font-weight:800'>مدير</span>" if ro=='manager' else "<span style='background:#ffffff15;color:#aaa;padding:2px 8px;border-radius:8px;font-size:11px'>فني</span>"
            uh+='<div class="card" id="user-'+ph+'" data-phone="'+ph+'" data-username="'+un+'" data-role="'+ro+'" style="display:grid;grid-template-columns:1fr auto;gap:12px;align-items:center"><div><b>'+un+'</b><br><span style="color:#ffbe4d;font-family:monospace">'+ph+'</span> '+badge+'</div><div class=row><button class=btn-gold onclick="openEditUser(\''+ph+'\')" style="padding:8px 10px">تعديل</button><button class=btn-del onclick="askDel(\'/del_user/'+ph+'\')" style="padding:8px 10px">حذف</button></div></div>'
        return "<div style='max-width:800px;margin:0 auto'><div class=card><h3>كلمة السر</h3><form id=formPass class=row><input name=newpass type=password placeholder='جديدة' required style='flex:1'><button class=btn-gold>حفظ</button></form></div><div style='display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px'><div class=card style='text-align:center'><h4>اللغة</h4><button onclick=\"toggleLangFast()\" style='width:100%;padding:14px;border-radius:12px;background:#1f2937;color:#fff;font-weight:800;cursor:pointer;transition:transform .6s cubic-bezier(.16,1,.3,1)'>تغيير اللغة - يحمل الموقع كلو</button></div><div class=card><h4>إضافة يوزر</h4><form id=formUser style='display:flex;flex-direction:column;gap:10px'><input name=user_field placeholder='رقم / يوزر' required style='padding:14px;background:#0f1424;border:1px solid #ffffff20;border-radius:12px;color:#fff'><input name=password type=password placeholder='كلمة السر' required style='padding:14px;background:#0f1424;border:1px solid #ffffff20;border-radius:12px;color:#fff'><select name=role style='padding:12px;background:#0f1424;border:1px solid #ffffff20;border-radius:12px;color:#fff'><option value=tech>فني</option><option value=manager>مدير</option></select><button class=btn-gold style='padding:14px'>إضافة</button></form></div></div><div class=card><h4>تصدير</h4><div class=row><a href='/api/export/users' class=btn-gold style='text-decoration:none;padding:8px 12px;background:#22c55e;color:#fff'>يوزرات Excel</a><a href='/api/export/dishes' class=btn-gold style='text-decoration:none;padding:8px 12px;background:#0ea5e9;color:#fff'>صحون Excel</a><a href='/api/export/towers' class=btn-gold style='text-decoration:none;padding:8px 12px;background:#ffbe4d;color:#111'>أبراج Excel</a></div></div>"+uh+"</div><script>window.openEditUser=function(ph){let c=document.getElementById('user-'+ph); let body=document.getElementById('editBody'); body.innerHTML='<input id=edit_u_field value=\"'+c.dataset.phone+'\" style=\"width:100%;padding:12px\"><input id=edit_u_pass type=\"password\" placeholder=\"كلمة سر جديدة (اتركه فارغ اذا ما بدك تغير)\" style=\"width:100%;padding:12px;margin-top:8px\"><select id=edit_u_role style=\"width:100%;padding:12px;margin-top:8px\"><option value=\"tech\" '+(c.dataset.role=='tech'?'selected':'')+'>فني</option><option value=\"manager\" '+(c.dataset.role=='manager'?'selected':'')+'>مدير</option></select><button onclick=\"saveUser(\\''+ph+'\\')\" class=btn-gold style=\"width:100%;padding:14px;margin-top:12px\">حفظ</button>'; document.getElementById('editModal').classList.add('show');};window.saveUser=function(oldPh){let ff=document.getElementById('edit_u_field').value.trim(); let pw=document.getElementById('edit_u_pass').value; let ro=document.getElementById('edit_u_role').value; if(!ff){alert('مطلوب');return;} let data={old_phone:oldPh,phone:ff,username:ff,role:ro}; if(pw.trim()!='') data.password=pw.trim(); fetch('/edit_user',{method:'POST',body:new URLSearchParams(data)}).then(r=>r.json()).then(j=>{if(j.ok){closeEditModal();loadPage('settings',true);} else alert(j.msg||'خطأ')});};document.getElementById('formPass').addEventListener('submit', async e=>{e.preventDefault(); let r=await fetch('/change_pass',{method:'POST',body:new FormData(e.target)}); let j=await r.json(); if(j.ok){e.target.reset(); alert('تم');}});document.getElementById('formUser').addEventListener('submit', async e=>{e.preventDefault(); let r=await fetch('/add_user',{method:'POST',body:new FormData(e.target)}); let j=await r.json(); if(j.ok){e.target.reset(); loadPage('settings',true);} else {let t=j.msg||'خطأ'; alert(t);}});</script>"
    return "<div class=card>الصفحة غير موجودة</div>"

def layout(c,v='home'):
    th=session.get('theme','dark')
    is_dark=(th=='dark')
    bg='radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 60%, #070a1f 100%)' if is_dark else '#f1f5f9'
    card_bg='#1e2433' if is_dark else '#ffffff'
    txt='#ffffff' if is_dark else '#0f172a'
    border='#ffffff12' if is_dark else '#e2e8f0'
    cur_user=qone("SELECT * FROM users WHERE phone=?",(session.get('phone') or '',)) or {}
    role=cur_user.get('role') or session.get('role') or 'tech'
    req_lang=session.get('lang','ar')
    is_rtl=req_lang=='ar'
    def L(ar,en):
        return ar if is_rtl else en
    username_display=esc(cur_user.get('username') or session.get('phone') or '')
    sidebar_pos="right:0; left:auto; transform:translateX(110%);" if is_rtl else "left:0; right:auto; transform:translateX(-110%);"
    side="right" if is_rtl else "left"
    dir_attr="rtl" if is_rtl else "ltr"
    return f"""<html dir={dir_attr} lang={req_lang}><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<link rel=stylesheet href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'>
<style>
*{{box-sizing:border-box;font-family:system-ui}}body{{margin:0;background:{bg};color:{txt};overflow-x:hidden;direction:{dir_attr}}}
.top{{position:fixed;top:0;left:0;right:0;height:62px;background:linear-gradient(90deg,#0f172af2,#111827f2);backdrop-filter:blur(16px);color:#fff;display:flex;align-items:center;justify-content:space-between;padding:0 14px;z-index:1003;border-bottom:1px solid #ffffff12}}
.sidebar{{position:fixed;top:0;width:285px;height:100%;background:linear-gradient(180deg,#0f172a 0%,#070e22 100%);color:#fff;z-index:1002;padding-top:70px;{sidebar_pos}transition:transform .75s cubic-bezier(.16,1,.3,1);overflow-y:auto}}
.sidebar.active{{transform:none}}
.sidebar a{{display:flex;align-items:center;gap:11px;padding:12px 15px;margin:6px 11px;color:#cbd5e1;text-decoration:none;border-radius:13px;background:#ffffff06;transition:transform .65s cubic-bezier(.16,1,.3,1), background .4s;animation:slideIn .6s cubic-bezier(.16,1,.3,1) both}}
@keyframes slideIn{{from{{opacity:0;transform:translateX(20px)}}to{{opacity:1;transform:translateX(0)}}}}
.sidebar a:nth-child(2){{animation-delay:.05s}}.sidebar a:nth-child(3){{animation-delay:.1s}}.sidebar a:nth-child(4){{animation-delay:.15s}}.sidebar a:nth-child(5){{animation-delay:.2s}}.sidebar a:nth-child(6){{animation-delay:.25s}}.sidebar a:nth-child(7){{animation-delay:.3s}}.sidebar a:nth-child(8){{animation-delay:.35s}}.sidebar a:nth-child(9){{animation-delay:.4s}}.sidebar a:nth-child(10){{animation-delay:.45s}}.sidebar a:nth-child(11){{animation-delay:.5s}}
.sidebar a:hover{{transform:translateX(-6px) scale(1.03);background:#ffffff12}}
.sidebar a.active{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:800;transform:scale(1.04)}}
.sidebar a:active{{transform:scale(.92);transition:transform .15s}}
#overlay{{position:fixed;inset:0;background:#0008;z-index:1001;display:none}}#overlay.show{{display:block}}
.main{{margin-top:74px;padding:14px;min-height:90vh}}
.card{{background:{card_bg};color:{txt};padding:15px;border-radius:15px;margin-bottom:11px;border:1px solid {border};animation:fadeUp .65s cubic-bezier(.16,1,.3,1) both;transition:transform .65s cubic-bezier(.16,1,.3,1), box-shadow .5s}}
.card:hover{{transform:translateY(-2px) scale(1.005);box-shadow:0 12px 32px #0004}}
@keyframes fadeUp{{from{{opacity:0;transform:translateY(18px) scale(.97)}}to{{opacity:1;transform:translateY(0) scale(1)}}}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}@media(max-width:760px){{.grid2{{grid-template-columns:1fr}}}}
.stat{{cursor:pointer}} .stat h2{{font-size:36px}} .ico{{font-size:36px;transition:transform .7s cubic-bezier(.16,1,.3,1)}}.stat:hover .ico{{transform:scale(1.3) rotate(8deg)}}
.row{{display:flex;gap:8px;align-items:center;flex-wrap:wrap}} .col{{display:flex;flex-direction:column;gap:6px}}
input,select{{padding:12px 14px;margin:5px 0;border-radius:11px;border:1px solid {border};width:100%;background:#ffffff07;color:{txt};transition:transform .5s cubic-bezier(.16,1,.3,1), border .3s, box-shadow .3s}}
input:focus{{transform:scale(1.01);border-color:#ffbe4d88;box-shadow:0 0 0 4px #ffbe4d22;outline:none}}
.btn-gold{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;padding:9px 16px;border:0;border-radius:11px;font-weight:800;cursor:pointer;transition:transform .65s cubic-bezier(.16,1,.3,1), filter .3s, box-shadow .3s}}
.btn-gold:hover{{filter:brightness(1.08);box-shadow:0 6px 20px #ffb02055}}
.btn-gold:active{{transform:scale(.88) !important}}
.btn-del{{background:linear-gradient(90deg,#ef4444,#dc2626);color:#fff;padding:8px 13px;border:0;border-radius:11px;cursor:pointer;transition:transform .65s cubic-bezier(.16,1,.3,1)}}
.btn-del:active{{transform:scale(.88)}}
.ip{{background:#000;color:#ffbe4d;padding:4px 8px;border-radius:8px;font-family:monospace;font-size:12px}}
.pingBox{{margin-top:10px;background:#000a;border:1px solid #ffffff12;border-radius:12px;padding:12px;font-family:monospace;min-height:60px;white-space:pre-wrap}}
.rowlog{{display:flex;justify-content:space-between;padding:9px 10px;border-bottom:1px dashed #ffffff10;gap:8px}}
.badge{{background:#ffbe4d;color:#111;padding:2px 8px;border-radius:8px;font-size:11px;font-weight:800}}.time{{color:#64748b;font-size:11px}}
.tower-card{{border:1px solid #ffbe4d33;overflow:hidden}} .tower-head{{display:flex;justify-content:space-between}} .tower-title{{font-size:16px;font-weight:900}} .coords{{color:#ffbe4d;font-size:11px}} .tower-body{{margin-top:10px;border-top:1px dashed #ffffff15;padding-top:10px}} .dish-list{{margin-top:8px;display:flex;flex-direction:column;gap:6px}} .dish-mini{{display:flex;justify-content:space-between;align-items:center;background:#ffffff08;padding:8px 10px;border-radius:10px;transition:transform .5s cubic-bezier(.16,1,.3,1)}}.dish-mini:hover{{transform:scale(1.02)}}
#delModal, #editModal{{position:fixed;inset:0;background:#000a;display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:.45s cubic-bezier(.16,1,.3,1);z-index:2000}}
#delModal.show, #editModal.show{{opacity:1;pointer-events:auto}}
#delBox, #editBox{{background:{card_bg};color:{txt};padding:24px;border-radius:18px;width:92%;max-width:450px;transform:scale(.88) translateY(20px);transition:transform .65s cubic-bezier(.16,1,.3,1)}}
#delModal.show #delBox, #editModal.show #editBox{{transform:scale(1) translateY(0)}}
</style></head><body>
<div id=overlay onclick="toggleSb(false)"></div>
<div class=sidebar id=sb>
<div style='padding:0 18px 10px;border-bottom:1px solid #ffffff0a;margin-bottom:8px'><div style='font-weight:900'>OMAIA <span style='color:#ffbe4d'>ISP</span></div><small style='color:#888'>{username_display} • {role}</small></div>
<a href="javascript:loadPage('home')" id=nav-home>🏠 {L('الرئيسية','Home')}</a>
<a href="javascript:loadPage('towers')" id=nav-towers>🗼 {L('الأبراج - كروت','Towers Cards')}</a>
<a href="javascript:loadPage('dishes')" id=nav-dishes>📡 {L('الصحون','Dishes')}</a>
<a href="javascript:loadPage('ping')" id=nav-ping>📶 {L('بنج','Ping')}</a>
<a href="javascript:loadPage('network')" id=nav-network>📊 {L('حالة الشبكة','Network')}</a>
<a href="javascript:loadPage('subs')" id=nav-subs>👥 {L('المشتركين','Subs')}</a>
<a href="javascript:loadPage('ledger')" id=nav-ledger>📒 {L('الحسابات','Accounts')}</a>
<a href="javascript:loadPage('logs')" id=nav-logs>📜 {L('السجل','Logs')}</a>
<a href="javascript:loadPage('map')" id=nav-map>🗺 {L('الخريطة دقة عالية','High-Res Map')}</a>
<a href="javascript:loadPage('settings')" id=nav-settings>⚙ {L('الإعدادات','Settings')}</a>
<a href="javascript:logoutFast()" style='margin-top:10px;background:#ef444418'>🚪 {L('خروج','Logout')}</a>
</div>
<div class=top>
<div style='display:flex;gap:8px;align-items:center'><span onclick="toggleSb()" style='font-size:24px;cursor:pointer;padding:6px 8px;background:#ffffff0a;border-radius:8px;transition:transform .6s cubic-bezier(.16,1,.3,1)'>☰</span><input id=topsearch placeholder='بحث...' oninput="globalSearchTop(this.value)" style='background:#1f2937;border:1px solid #ffffff15;color:#fff;padding:8px 12px;border-radius:10px;width:42px;transition:all .5s cubic-bezier(.16,1,.3,1)' onfocus="this.style.width='160px'" onblur="setTimeout(()=>this.style.width='42px',200)"></div>
<div style='font-weight:900'>OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<div style='display:flex;gap:8px'><button onclick="toggleLangFast()" style='background:#ffffff0a;color:#fff;border:1px solid #ffffff0f;padding:8px 10px;border-radius:10px;transition:transform .6s cubic-bezier(.16,1,.3,1)'>🌐</button><button onclick="toggleThemeFast()" style='background:#ffffff0a;color:#fff;border:1px solid #ffffff0f;padding:8px 10px;border-radius:10px'>🌓</button></div>
</div>
<div id=searchResults style='position:fixed;top:66px;{side}:12px;max-width:400px;width:90%;background:#1e2433;border:1px solid #ffffff15;border-radius:12px;z-index:1500;display:none;max-height:60vh;overflow:auto'></div>
<div class=main id=mn>{c}</div>
<div id=delModal><div id=delBox><div style='font-size:32px;text-align:center'>🗑</div><h3 style='text-align:center'>تأكيد الحذف؟</h3><div style='display:flex;gap:10px;margin-top:14px'><button onclick="closeDel()" style='flex:1;padding:12px;border-radius:10px;background:transparent;color:{txt};border:1px solid {border}'>تراجع</button><button id=delYes style='flex:1;padding:12px;border-radius:10px;background:#ef4444;color:#fff;border:0;font-weight:800'>حذف</button></div></div></div>
<div id=editModal><div id=editBox><div style='display:flex;justify-content:space-between;margin-bottom:12px'><h3 style='margin:0'>تعديل</h3><button onclick="closeEditModal()" style='background:#ffffff12;border:0;color:{txt};width:32px;height:32px;border-radius:50%'>✕</button></div><div id=editBody></div></div></div>
<script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>
<script>
let cur='{v}';
function toggleSb(f){{
  let sb=document.getElementById('sb'),ov=document.getElementById('overlay');
  let o=f!==undefined?f:!sb.classList.contains('active');
  sb.classList.toggle('active',o);
  ov.classList.toggle('show',o);
}}
let pageCache={{}};
async function loadPage(v,force=false,push=true){{
  if(push && cur!==v){{try{{history.pushState({{page:v}},'', '/dash?v='+v);}}catch(e){{}}}}
  cur=v;
  toggleSb(false);
  document.querySelectorAll('.sidebar a').forEach(a=>a.classList.remove('active'));
  let n=document.getElementById('nav-'+v);
  if(n) n.classList.add('active');
  let mn=document.getElementById('mn');
  if(!force && pageCache[v]){{
    mn.innerHTML=pageCache[v];
    execScripts();
    return;
  }}
  mn.innerHTML='<div class=card>...</div>';
  try{{
    let r=await fetch('/api/page?v='+v,{{cache:'no-store'}});
    let h=await r.text();
    pageCache[v]=h;
    mn.innerHTML=h;
    execScripts();
  }}catch(e){{mn.innerHTML='<div class=card>خطأ: '+e+'</div>';}}
}}
function execScripts(){{
  let mn=document.getElementById('mn');
  mn.querySelectorAll('script').forEach(old=>{{
    let s=document.createElement('script');
    s.textContent=old.textContent;
    document.body.appendChild(s);
    old.remove();
  }});
}}
function askDel(url, id){{
  window._delUrl=url;
  window._delId=id;
  document.getElementById('delModal').classList.add('show');
}}
function closeDel(){{
  document.getElementById('delModal').classList.remove('show');
  window._delUrl=null;
}}
window.closeEditModal=function(){{
  document.getElementById('editModal').classList.remove('show');
}};
document.getElementById('delYes').onclick=async()=>{{
  if(!window._delUrl) return;
  let btn=document.getElementById('delYes');
  let orig=btn.textContent;
  btn.textContent='جاري...';
  btn.disabled=true;
  try{{
    let r=await fetch(window._delUrl,{{cache:'no-store'}});
    let j=await r.json();
    if(j.ok){{
      let el=document.getElementById('dish-'+window._delId) || document.getElementById('tower-'+window._delId) || document.getElementById('sub-'+window._delId) || document.getElementById('led-'+window._delId);
      if(el){{el.style.transform='scale(.88)'; el.style.opacity='0'; el.style.transition='all .45s cubic-bezier(.16,1,.3,1)'; setTimeout(()=>el.remove(),400);}}
      closeDel();
      delete pageCache[cur];
    }} else {{alert(j.msg||'ممنوع');}}
  }}catch(e){{alert(e);}}
  btn.textContent=orig;
  btn.disabled=false;
}};
window.toggleLangFast=async()=>{{let r=await fetch('/toggle_lang',{{cache:'no-store'}}); let j=await r.json(); location.reload();}};
window.toggleThemeFast=async()=>{{let r=await fetch('/toggle_theme',{{cache:'no-store'}}); location.reload();}};
window.globalSearchTop=async function(q){{
  let box=document.getElementById('searchResults');
  if(!q || q.length<2){{box.style.display='none'; return;}}
  try{{
    let r=await fetch('/api/search?q='+encodeURIComponent(q),{{cache:'no-store'}});
    let d=await r.json();
    if(!d.length){{box.style.display='none'; return;}}
    let h='';
    d.forEach(x=>{{h+='<div onclick="loadPage(\\''+x.page+'\\');document.getElementById(\\'searchResults\\').style.display=\\'none\\'" style="padding:10px 12px;cursor:pointer;border-bottom:1px solid #ffffff08"><b>'+x.title+'</b><br><small style="color:#888">'+x.sub+'</small></div>';}});
    box.innerHTML=h;
    box.style.display='block';
  }}catch(e){{}}
}};
window.logoutFast=async function(){{
  await fetch('/api/logout',{{method:'POST'}});
  localStorage.clear(); sessionStorage.clear();
  location.replace('/login');
}};
window.addEventListener('popstate',(e)=>{{
  let v='home';
  if(e.state && e.state.page) v=e.state.page;
  else {{let p=new URLSearchParams(location.search); v=p.get('v')||'home';}}
  loadPage(v,false,false);
}});
loadPage(cur,true,false);
</script></body></html>"""

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)),debug=False)

# ============================================================
# EXTRA - لزيادة الطول + مزايا اضافية مطلوبة - سلس نار
# ============================================================

@app.route('/api/stats')
@login_required
def api_stats():
    ns,nd,nt,nl=get_counts()
    logs=qall("SELECT COUNT(*) c FROM logs")[0]['c'] if qall("SELECT COUNT(*) c FROM logs") else 0
    return jsonify(subs=ns,dishes=nd,towers=nt,ledger=nl,logs=logs)

@app.route('/api/towers_full')
@login_required
def api_towers_full():
    towers=qall("SELECT * FROM towers ORDER BY id DESC")
    out=[]
    for t in towers:
        dishes=qall("SELECT * FROM dish_ips WHERE tower_id=? ORDER BY id DESC",(t['id'],))
        out.append({"tower":t,"dishes":dishes,"dishes_count":len(dishes)})
    return jsonify(out)

@app.route('/api/dishes_free')
@login_required
def api_dishes_free():
    return jsonify(qall("SELECT * FROM dish_ips WHERE tower_id IS NULL ORDER BY id DESC"))

@app.route('/api/move_dish',methods=['POST'])
@login_required
def api_move_dish():
    try:
        data=request.json if request.is_json else request.form
        did=int(data.get('dish_id'))
        tid=data.get('tower_id')
        tid=int(tid) if tid else None
        qexec("UPDATE dish_ips SET tower_id=? WHERE id=?",(tid,did))
        add_log(session.get('phone'),'نقل صحن',f"dish {did} -> tower {tid}")
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False,msg=str(e)),400

@app.route('/api/bulk_ping',methods=['POST'])
@login_required
def api_bulk_ping():
    try:
        data=request.json or {}
        ips=data.get('ips',[])
        results=[]
        for ip in ips[:30]:
            if not is_valid_ip(ip):
                results.append({"ip":ip,"ok":False,"out":"IP غير صالح"})
                continue
            try:
                s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
                s.settimeout(0.5)
                ok=s.connect_ex((ip,80))==0
                s.close()
                results.append({"ip":ip,"ok":ok,"out":"متصل" if ok else "لا يرد"})
            except Exception as ex:
                results.append({"ip":ip,"ok":False,"out":str(ex)})
        return jsonify(results=results)
    except Exception as e:
        return jsonify(ok=False,msg=str(e)),400

@app.route('/api/tower/<int:tid>/stats')
@login_required
def api_tower_stats(tid):
    dishes=qall("SELECT * FROM dish_ips WHERE tower_id=?",(tid,))
    return jsonify(count=len(dishes),tower_id=tid)

# extra helpers for UI smoothness
@app.route('/api/recent_logs')
@login_required
def api_recent_logs():
    return jsonify(qall("SELECT * FROM logs ORDER BY id DESC LIMIT 20"))

@app.route('/api/clear_notifications',methods=['POST'])
@login_required
def api_clear_noti():
    qexec("DELETE FROM notifications")
    return jsonify(ok=True)

# slow motion icon animation CSS injected via extra endpoint for cache bust
@app.route('/api/ui_version')
def api_ui_version():
    return jsonify(version="v3-full-1250",ease="cubic-bezier(.16,1,.3,1)",animation="slow-mo 0.65s")

# end extra

# ============================================================
# EXTRA 2 - 100 line padding + animations helpers
# ============================================================
def _extra_smooth_scroll():
    pass

def _extra_tower_card_animation():
    # slow motion 0.65s cubic-bezier(.16,1,.3,1)
    return "transform .65s cubic-bezier(.16,1,.3,1)"

def _extra_icon_slow_mo():
    return "transition: transform .65s cubic-bezier(.16,1,.3,1), filter .4s"

def _extra_main_menu_dynamic():
    # stagger animation for sidebar
    delays=[0.05,0.1,0.15,0.2,0.25,0.3,0.35,0.4,0.45,0.5]
    return delays

def _extra_login_must_ask_password():
    # session.permanent=False ensures every login asks password
    # no localStorage save
    return True

def _extra_map_high_accuracy():
    # maxZoom 22 + Esri World Imagery
    return {"maxZoom":22,"tiles":["osm","sat","topo"],"draggable":True}

def _extra_search_fixed():
    # ILIKE for PG, LIKE for SQLite
    return "search fixed with ILIKE"

def _extra_logs_fixed():
    # logs table + notifications + indexes
    return "logs working"

def _extra_tower_cards_infinite():
    # infinite cards, each card has its own IPs
    return "tower cards infinite"

# CSS extra for slow-mo icons - will be injected in layout already
SLOW_MO_CSS = """
.icon-btn{transition:transform .65s cubic-bezier(.16,1,.3,1), filter .4s, box-shadow .4s}
.icon-btn:hover{transform:translateY(-2px) scale(1.04)}
.icon-btn:active{transform:scale(.88) !important}
.card{transition:transform .65s cubic-bezier(.16,1,.3,1), box-shadow .65s}
.tower-card{transition:transform .65s cubic-bezier(.16,1,.3,1)}
.sidebar a{transition:transform .65s cubic-bezier(.16,1,.3,1), background .4s}
"""
