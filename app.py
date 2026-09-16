# OMAIA ISP - 1173 سطر كامل مصحح بدون 500 - زجاجي فخم - قمر صناعي HD - Enter يبحث - دخول سلس
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
_secret = os.environ.get("SECRET_KEY") or ("dev-only-" + secrets.token_hex(32))
app.secret_key=_secret
app.config['PERMANENT_SESSION_LIFETIME']=datetime.timedelta(hours=12)
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
    if not USE_PG or not pg_pool:
        return
    with _pool_lock:
        if _pg_pool:
            return
        try:
            _pg_pool=pg_pool.ThreadedConnectionPool(2,6,dsn=DATABASE_URL,sslmode='require',connect_timeout=1)
        except Exception as e:
            print("[POOL] "+str(e))
            _pg_pool=None
init_pool()

def esc(s):
    return html.escape(str(s or ''), quote=True)

def get_conn():
    if USE_PG and _pg_pool:
        try:
            return _pg_pool.getconn()
        except:
            return psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=2)
    elif USE_PG:
        try:
            return psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=2)
        except:
            pass
    global _sqlite_conn
    with _sqlite_lock:
        if _sqlite_conn is None:
            try:
                _sqlite_conn=sqlite3.connect("omia.db",check_same_thread=False,timeout=10)
                _sqlite_conn.row_factory=sqlite3.Row
                _sqlite_conn.execute("PRAGMA journal_mode=WAL;")
                _sqlite_conn.execute("PRAGMA synchronous=NORMAL;")
            except:
                _sqlite_conn=sqlite3.connect(":memory:",check_same_thread=False)
                _sqlite_conn.row_factory=sqlite3.Row
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
                rs=[dict(r) for r in conn.execute(q,a).fetchall()]
                return rs
    except Exception as e:
        print("[qall] "+str(e))
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
        print("[qexec] "+str(e))
        if conn and USE_PG:
            try:
                conn.rollback()
                put_conn(conn)
            except:
                pass
        return False

# سجل سريع جداً - اتصال واحد واستعلامين مع بعض
def _log_sync(phone,action,detail):
    try:
        now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn=None
        try:
            conn=get_conn()
            if USE_PG:
                cur=conn.cursor()
                cur.execute("INSERT INTO logs(user_phone,action,detail,time) VALUES(%s,%s,%s,%s)",(phone or 'unknown',action,detail,now))
                cur.execute("INSERT INTO notifications(title,msg,time) VALUES(%s,%s,%s)",(action,str(phone)+": "+str(detail),now))
                conn.commit()
                cur.close()
                put_conn(conn)
            else:
                with _sqlite_lock:
                    conn.execute("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)",(phone or 'unknown',action,detail,now))
                    conn.execute("INSERT INTO notifications(title,msg,time) VALUES(?,?,?)",(action,str(phone)+": "+str(detail),now))
                    conn.commit()
        except Exception as e:
            print("[log-inner] "+str(e))
            if conn and USE_PG:
                try:
                    conn.rollback()
                    put_conn(conn)
                except:
                    pass
        with _cache_lock:
            _cache.pop('counts',None)
    except Exception as e:
        print("[log] "+str(e))

def add_log(phone,action,detail, background=False):
    _log_sync(phone,action,detail)

def get_counts():
    with _cache_lock:
        c=_cache.get('counts')
        if c and time.time()-c[1]<10:
            return c[0]
    try:
        # استعلام واحد بدل 4 - أسرع 4 مرات
        if USE_PG:
            row=qone("SELECT (SELECT COUNT(*) FROM subs) as s, (SELECT COUNT(*) FROM dish_ips) as d, (SELECT COUNT(*) FROM towers) as t, (SELECT COUNT(*) FROM ledger) as l")
            data=(row.get('s',0) if row else 0, row.get('d',0) if row else 0, row.get('t',0) if row else 0, row.get('l',0) if row else 0)
        else:
            row=qone("SELECT (SELECT COUNT(*) FROM subs) as s, (SELECT COUNT(*) FROM dish_ips) as d, (SELECT COUNT(*) FROM towers) as t, (SELECT COUNT(*) FROM ledger) as l")
            data=(row.get('s',0) if row else 0, row.get('d',0) if row else 0, row.get('t',0) if row else 0, row.get('l',0) if row else 0)
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
    for idx in ["CREATE INDEX IF NOT EXISTS idx_dish_ips_ip ON dish_ips(ip)", "CREATE INDEX IF NOT EXISTS idx_towers_name ON towers(name)", "CREATE INDEX IF NOT EXISTS idx_logs_id ON logs(id DESC)", "CREATE INDEX IF NOT EXISTS idx_logs_time ON logs(time DESC)"]:
        try:
            qexec(idx)
        except:
            pass
    if USE_PG:
        try:
            qexec("CREATE UNIQUE INDEX IF NOT EXISTS uq_dish_ips_ip ON dish_ips(ip)")
        except:
            pass
    if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",('05344851045',generate_password_hash('admin2024'),'manager','admin'))
    if not qone("SELECT * FROM towers WHERE name=?",('نقطة حماة الرئيسية',)):
        qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",('نقطة حماة الرئيسية','حماة',35.131812,36.757812))
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

def is_valid_host(h):
    h=(h or '').strip().split(':')[0]
    if not h: return False
    try: ipaddress.ip_address(h); return True
    except: pass
    if len(h)>253 or '.' not in h: return False
    if len(h)>253: return False
    if '.' not in h: return False
    if not __import__('re').match(r'^[a-zA-Z0-9.\-]+$', h): return False
    parts=h.split('.')
    for p in parts:
        if not p or len(p)>63: return False
        if p.startswith('-') or p.endswith('-'): return False
    if len(parts[-1])<2: return False
    return True

def is_valid_ip(ip):
    return is_valid_host(ip)

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

def _check_port(args):
    ip, port = args
    s=None
    try:
        s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        s.settimeout(0.35)
        ok = s.connect_ex((ip,port))==0
        s.close()
        return (port, ok)
    except:
        try:
            if s:
                s.close()
        except:
            pass
        return (port, False)

@app.route('/api/ping')
@login_required
def api_ping():
    ip=request.args.get('ip','').strip()
    if not ip:
        return jsonify(ok=False,out='لا يوجد IP')
    if not is_valid_ip(ip):
        return jsonify(ok=False,out='IP غير صالح')
    ports=[80,8291,22]
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures={ex.submit(_check_port,(ip,p)):p for p in ports}
        for f in as_completed(futures):
            port,ok=f.result()
            if ok:
                return jsonify(ok=True,out=ip+':'+str(port)+' مفتوح',port=port,method='tcp')
    try:
        cmd=['ping','-c','1','-W','1',ip] if platform.system().lower()!='windows' else ['ping','-n','1','-w','1000',ip]
        out=subprocess.check_output(cmd,timeout=1,stderr=subprocess.STDOUT).decode(errors='ignore')
        ok='ttl=' in out.lower() or 'bytes from' in out.lower() or '1 received' in out.lower()
        if ok:
            m=re.search(r'time[=<]\s*(\d+\.?\d*)',out,re.I)
            ms=m.group(1) if m else ''
            return jsonify(ok=True,out=ip+' - '+ms+'ms',ms=ms,method='icmp')
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
    _,ok=_check_port((ip,port))
    if ok:
        return jsonify(ok=True,out=ip+':'+str(port)+' مفتوح')
    else:
        return jsonify(ok=False,out=ip+':'+str(port)+' مغلق')

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

@app.route('/toggle_lang',methods=['GET','POST'])
@login_required
def toggle_lang_route():
    cur=session.get('lang','ar')
    new='en' if cur=='ar' else 'ar'
    session['lang']=new
    # حفظ فوراً
    session.modified=True
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
        session['lang']=session.get('lang','ar')
        session.permanent=False
        add_log(u['phone'],'دخل النظام','تسجيل دخول', background=True)
        return jsonify(ok=True,role=u.get('role'),lang=session.get('lang','ar'))
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
    with _cache_lock:
        _cache.clear()
    return jsonify(ok=True)

@app.route('/api/seed_log',methods=['POST'])
@login_required
def seed_log():
    now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)",(session.get('phone','test'),'إضافة صحن','192.168.1.10 - صحن تجريبي',now))
    with _cache_lock:
        _cache.clear()
    return jsonify(ok=True)

@app.route('/')
def ix():
    return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login')
def login():
    return """<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@700;900&display=swap" rel="stylesheet">
<style>*{box-sizing:border-box;font-family:'Cairo',system-ui}body{margin:0;min-height:100vh;background:#0a0e2a;display:flex;flex-direction:column;align-items:center;justify-content:center;color:#fff}
.card{background:#1e253a;border:1px solid #ffffff15;padding:26px;border-radius:20px;width:92%;max-width:390px}
input{width:100%;padding:13px;margin:8px 0;background:#0f1424;border:1px solid #ffffff20;color:#fff;border-radius:12px;font-size:15px}
.btn{width:100%;padding:13px;border:0;border-radius:12px;background:#ffbe4d;color:#111;font-weight:900;font-size:16px;cursor:pointer;margin-top:10px}
.support-box{margin-top:14px;text-align:center;padding:10px;background:#ffffff06;border-radius:10px}
.support-box a{color:#ffbe4d;text-decoration:none;font-weight:700}
</style></head><body>
<div style='font-size:28px;font-weight:900;margin-bottom:4px'>OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<div style='color:#666;font-size:12px;margin-bottom:14px'>الدعم: +905344851045</div>
<div class=card>
<form id=loginForm>
<input name=userin id=userin placeholder='رقم / يوزر' required autocomplete=username>
<input name=password id=password type=password placeholder='كلمة السر' required autocomplete=current-password>
<label style='display:flex;align-items:center;gap:8px;margin:8px 0;font-size:12px;color:#aaa;cursor:pointer'><input type=checkbox id=rememberMe style='width:16px;height:16px;margin:0'> حفظ كلمة السر</label>
<button class=btn id=loginBtn>دخول</button>
<div id=msg style='text-align:center;margin-top:8px;color:#ff6b6b;font-size:12px;min-height:16px'></div>
</form>
<div class=support-box><a href='https://wa.me/905344851045' target=_blank>واتساب: +905344851045</a></div>
</div>
<script>
let u=document.getElementById('userin'), p=document.getElementById('password'), cb=document.getElementById('rememberMe');
try{ let su=localStorage.getItem('omaia_user'), sp=localStorage.getItem('omaia_pass'); if(su) u.value=su; if(sp){ p.value=sp; cb.checked=true; } }catch(e){}
document.getElementById('loginForm').addEventListener('submit',async e=>{
 e.preventDefault();
 let btn=document.getElementById('loginBtn'), msg=document.getElementById('msg');
 if(btn.disabled) return;
 btn.textContent='جاري...'; btn.disabled=true; msg.textContent='';
 try{
  let fd=new FormData(e.target);
  let r=await fetch('/api/login_public',{method:'POST',body:fd,credentials:'same-origin',cache:'no-store'});
  let j=await r.json();
  if(j.ok){
    try{ if(cb.checked){ localStorage.setItem('omaia_user',u.value); localStorage.setItem('omaia_pass',p.value); }else{ localStorage.removeItem('omaia_user'); localStorage.removeItem('omaia_pass'); } localStorage.setItem('omaia_lang',j.lang||'ar'); }catch(e){}
    location.replace('/dash?v=home');
  } else { msg.textContent=j.msg||'خطأ'; btn.textContent='دخول'; btn.disabled=false; }
 }catch(err){ msg.textContent='خطأ شبكة'; btn.textContent='دخول'; btn.disabled=false; }
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
    except:
        pass
    return jsonify(results[:25])

@app.route('/toggle_theme')
@login_required
def tt():
    cur=session.get('theme','dark')
    session['theme']='light' if cur=='dark' else 'dark'
    session.modified=True
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
        row=qone("SELECT id FROM dish_ips WHERE ip=?",(ip,))
        new_id=row['id'] if row else 0
    else:
        ex=qone("SELECT id FROM dish_ips WHERE ip=?",(ip,))
        if ex:
            ok=qexec("UPDATE dish_ips SET dish_name=?,location=? WHERE ip=?",(name,loc,ip))
            new_id=ex['id']
        else:
            ok=qexec("INSERT INTO dish_ips(ip,location,dish_name) VALUES(?,?,?)",(ip,loc,name))
            last=qone("SELECT last_insert_rowid() as id")
            new_id=last['id'] if last else 0
    if ok:
        add_log(phone,'إضافة صحن',name+" "+ip+" "+loc, background=True)
    return jsonify(ok=ok, id=new_id, ip=ip, name=name, loc=loc)

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
    old=qone("SELECT * FROM dish_ips WHERE id=?",(i,))
    ok=qexec("UPDATE dish_ips SET dish_name=?,ip=?,location=? WHERE id=?",(name,ip,loc,i))
    if ok:
        detail="ID "+str(i)+" من "+str(old.get('ip',''))+" الى "+ip+" "+name if old else "ID "+str(i)
        add_log(session.get('phone'),'تعديل صحن',detail, background=True)
    return jsonify(ok=ok)

@app.route('/del_dish/<int:i>')
@login_required
def dd(i):
    if not is_manager():
        return jsonify(ok=False,msg="ممنوع للفني"),403
    info=qone("SELECT ip,dish_name FROM dish_ips WHERE id=?",(i,))
    ok=qexec("DELETE FROM dish_ips WHERE id=?",(i,))
    if ok:
        add_log(session.get('phone'),'حذف صحن',str(info.get('dish_name',''))+" "+str(info.get('ip','')) if info else "ID "+str(i), background=True)
    return jsonify(ok=ok)

@app.route('/add_tower',methods=['POST'])
@login_required
def at():
    lat=request.form.get('lat','').strip()
    lng=request.form.get('lng','').strip()
    try:
        la=float(lat) if lat else 35.131812
        ln=float(lng) if lng else 36.757812
        if not (-90 <= la <= 90 and -180 <= ln <= 180):
            raise ValueError()
    except:
        return jsonify(ok=False,msg="احداثيات غير صالحة"),400
    name=request.form.get('name','') or 'نقطة'
    area=request.form.get('area','')
    ok=qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",(name,area,la,ln))
    if USE_PG:
        row=qone("SELECT id FROM towers WHERE name=? AND lat=? AND lng=? ORDER BY id DESC LIMIT 1",(name,la,ln))
        nid=row['id'] if row else 0
    else:
        last=qone("SELECT last_insert_rowid() as id")
        nid=last['id'] if last else 0
    if ok:
        add_log(session.get('phone'),'إضافة برج',name+" "+str(la)+","+str(ln), background=True)
    return jsonify(ok=ok, id=nid, name=name, area=area, lat=la, lng=ln)

@app.route('/del_tower/<int:i>')
@login_required
def dt(i):
    if not is_manager():
        return jsonify(ok=False,msg="ممنوع للفني"),403
    ok=qexec("DELETE FROM towers WHERE id=?",(i,))
    if ok:
        add_log(session.get('phone'),'حذف برج',"ID "+str(i), background=True)
    return jsonify(ok=ok)

@app.route('/edit_tower/<int:i>',methods=['POST'])
@login_required
def et(i):
    if not is_manager():
        return jsonify(ok=False,msg="ممنوع للفني"),403
    lat=request.form.get('lat','').strip()
    lng=request.form.get('lng','').strip()
    try:
        la=float(lat) if lat else 35.131812
        ln=float(lng) if lng else 36.757812
    except:
        la=35.131812
        ln=36.757812
    name=request.form.get('name','')
    area=request.form.get('area','')
    ok=qexec("UPDATE towers SET name=?,area=?,lat=?,lng=? WHERE id=?",(name,area,la,ln,i))
    if ok:
        add_log(session.get('phone'),'تعديل برج',"ID "+str(i)+" "+name, background=True)
    return jsonify(ok=ok)

@app.route('/add_sub',methods=['POST'])
@login_required
def asub():
    name=request.form.get('name','')
    phone=request.form.get('phone','')
    note=request.form.get('note','')
    ok=qexec("INSERT INTO subs(name,phone,note) VALUES(?,?,?)",(name,phone,note))
    if USE_PG:
        row=qone("SELECT id FROM subs ORDER BY id DESC LIMIT 1")
        nid=row['id'] if row else 0
    else:
        last=qone("SELECT last_insert_rowid() as id")
        nid=last['id'] if last else 0
    if ok:
        add_log(session.get('phone'),'إضافة مشترك',name+" "+phone, background=True)
    return jsonify(ok=ok, id=nid, name=name, phone=phone, note=note)

@app.route('/del_sub/<int:i>')
@login_required
def dsub(i):
    if not is_manager():
        return jsonify(ok=False,msg="ممنوع للفني"),403
    ok=qexec("DELETE FROM subs WHERE id=?",(i,))
    if ok:
        add_log(session.get('phone'),'حذف مشترك',"ID "+str(i), background=True)
    return jsonify(ok=ok)

@app.route('/edit_sub/<int:i>',methods=['POST'])
@login_required
def esub(i):
    if not is_manager():
        return jsonify(ok=False,msg="ممنوع للفني"),403
    name=request.form.get('name','')
    phone=request.form.get('phone','')
    note=request.form.get('note','')
    ok=qexec("UPDATE subs SET name=?,phone=?,note=? WHERE id=?",(name,phone,note,i))
    if ok:
        add_log(session.get('phone'),'تعديل مشترك',"ID "+str(i)+" -> "+name, background=True)
    return jsonify(ok=ok)

@app.route('/add_ledger',methods=['POST'])
@login_required
def al():
    try:
        amt=float(request.form.get('amount') or 0)
    except:
        amt=0
    name=request.form.get('name','')
    note=request.form.get('note','')
    cur=request.form.get('currency','USD')
    ok=qexec("INSERT INTO ledger(name,amount,note,currency) VALUES(?,?,?,?)",(name,amt,note,cur))
    if USE_PG:
        row=qone("SELECT id FROM ledger ORDER BY id DESC LIMIT 1")
        nid=row['id'] if row else 0
    else:
        last=qone("SELECT last_insert_rowid() as id")
        nid=last['id'] if last else 0
    if ok:
        add_log(session.get('phone'),'إضافة حساب',str(name)+" "+str(amt), background=True)
    return jsonify(ok=ok, id=nid, name=name, amount=amt)

@app.route('/del_ledger/<int:i>')
@login_required
def dll(i):
    if not is_manager():
        return jsonify(ok=False,msg="ممنوع للفني"),403
    ok=qexec("DELETE FROM ledger WHERE id=?",(i,))
    if ok:
        add_log(session.get('phone'),'حذف حساب',"ID "+str(i), background=True)
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
    name=request.form.get('name','')
    note=request.form.get('note','')
    cur=request.form.get('currency','USD')
    ok=qexec("UPDATE ledger SET name=?,amount=?,note=?,currency=? WHERE id=?",(name,amt,note,cur,i))
    if ok:
        add_log(session.get('phone'),'تعديل حساب',"ID "+str(i)+" -> "+name, background=True)
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
    pw=request.form.get('password','1234')
    role=request.form.get('role','tech')
    ok=qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",(ph,generate_password_hash(pw),role,ph))
    if ok:
        add_log(session.get('phone'),'إضافة يوزر',ph+" "+role, background=True)
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
        add_log(session.get('phone'),'تعديل يوزر',old+"->"+new_ph+" "+new_role, background=True)
    return jsonify(ok=ok)

@app.route('/del_user/<ph>')
@login_required
@role_required_manager
def du(ph):
    if ph=='05344851045':
        return jsonify(ok=False,msg="ممنوع حذف المدير"),400
    ok=qexec("DELETE FROM users WHERE phone=?",(ph,))
    if ok:
        add_log(session.get('phone'),'حذف يوزر',ph, background=True)
    return jsonify(ok=ok)

@app.route('/change_pass',methods=['POST'])
@login_required
def cp():
    np=request.form.get('newpass','').strip()
    if not np or len(np)<4:
        return jsonify(ok=False,msg="قصيرة"),400
    ok=qexec("UPDATE users SET password=? WHERE phone=?",(generate_password_hash(np),session.get('phone')))
    if ok:
        add_log(session.get('phone'),'تغيير كلمة سر','تم التغيير', background=True)
    return jsonify(ok=ok)

def page_content(v):
    req_lang=request.args.get('lang') or session.get('lang','ar')
    def L(ar,en):
        return ar if req_lang=='ar' else en

    if v=='home':
        ns,nd,nt,nl=get_counts()
        # السجل - لا كاش، استعلام مباشر
        logs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 10")
        log_html=""
        for l in logs:
            col='#22c55e' if 'إضافة' in l.get('action','') else '#0ea5e9' if 'تعديل' in l.get('action','') else '#ef4444' if 'حذف' in l.get('action','') else '#ffbe4d'
            log_html += "<div style='display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #ffffff08'><div><span style='display:inline-block;width:8px;height:8px;border-radius:50%;background:"+col+";margin-left:6px'></span><b style='color:#ffbe4d'>"+esc(l.get('user_phone',''))+"</b> <span style='color:"+col+"'>"+esc(l.get('action',''))+"</span> <small style='color:#aaa'>"+esc(l.get('detail',''))[:70]+"</small></div><small style='color:#555'>"+esc(l.get('time',''))[-8:]+"</small></div>"
        if not logs:
            log_html="<div style='padding:12px;text-align:center;color:#888'>السجل فاضي - اول تعديل رح يظهر هون فوراً<br><button class=btn-gold onclick=\"fetch('/api/seed_log',{method:'POST',credentials:'same-origin'}).then(()=>loadPage('home',true))\" style='margin-top:8px'>اضافة سجل تجريبي</button></div>"
        return "<div style='max-width:1000px;margin:0 auto'><div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px'><div class=card onclick=\"loadPage('subs')\" style='cursor:pointer;text-align:center'><div style='font-size:12px;color:#888'>"+L('المشتركين','Subs')+"</div><div style='font-size:28px;font-weight:900'>"+str(ns)+"</div></div><div class=card onclick=\"loadPage('dishes')\" style='cursor:pointer;text-align:center'><div style='font-size:12px;color:#888'>"+L('الصحون','Dishes')+"</div><div style='font-size:28px;font-weight:900'>"+str(nd)+"</div></div><div class=card onclick=\"loadPage('towers')\" style='cursor:pointer;text-align:center'><div style='font-size:12px;color:#888'>"+L('الأبراج','Towers')+"</div><div style='font-size:28px;font-weight:900'>"+str(nt)+"</div></div><div class=card onclick=\"loadPage('ledger')\" style='cursor:pointer;text-align:center'><div style='font-size:12px;color:#888'>"+L('الحسابات','Accounts')+"</div><div style='font-size:28px;font-weight:900'>"+str(nl)+"</div></div></div><div class=card style='margin-top:10px'><div style='display:flex;justify-content:space-between'><b>السجل الحي</b><button class=btn-gold onclick=\"loadPage('logs')\" style='padding:6px 12px'>الكل</button></div><div style='margin-top:8px'>"+log_html+"</div></div><div class=card style='text-align:center'><a href='https://wa.me/905344851045' target=_blank style='display:inline-block;background:#22c55e;color:#fff;padding:8px 16px;border-radius:8px;text-decoration:none'>واتساب الدعم: 905344851045+</a></div></div>"

    if v=='ping':
        return """
<div style='max-width:900px;margin:0 auto'>
<div class=card>
<b>فحص الشبكة</b>
<div style='display:flex;gap:6px;margin-top:10px;flex-wrap:wrap'>
<input id=pingIp placeholder='192.168.1.1' onkeydown="if(event.key==='Enter'){{doSinglePing();}}" style='flex:1;min-width:140px'>
<input id=pingPort placeholder='Port' value='80' style='width:70px'>
<button class=btn-gold onclick="doSinglePing()" style='background:#22c55e;color:#fff'>Ping</button>
<button class=btn-gold onclick="doTcpPing()" style='background:#0ea5e9;color:#fff'>TCP</button>
</div>
<div id=pingResult style='margin-top:10px;background:#0006;padding:10px;border-radius:10px;font-family:monospace;font-size:12px;min-height:40px'>جاهز</div>
</div>
</div>
<script>
window.doSinglePing=async function(){
  let ip=document.getElementById('pingIp').value.trim();
  if(!ip) return;
  let out=document.getElementById('pingResult');
  out.textContent='جاري...';
  try{
    let r=await fetch('/api/ping?ip='+encodeURIComponent(ip),{credentials:'same-origin',cache:'no-store'});
    let j=await r.json();
    out.textContent=j.out;
    out.style.color=j.ok?'#22c55e':'#ef4444';
  }catch(e){ out.textContent='خطأ'; }
};
window.doTcpPing=async function(){
  let ip=document.getElementById('pingIp').value.trim();
  let port=document.getElementById('pingPort').value.trim()||'80';
  let out=document.getElementById('pingResult');
  out.textContent='جاري...';
  try{
    let r=await fetch('/api/ping_tcp?ip='+encodeURIComponent(ip)+'&port='+port,{credentials:'same-origin'});
    let j=await r.json();
    out.textContent=j.out;
  }catch(e){ out.textContent='خطأ'; }
};
</script>
"""

    if v=='dishes':
        rs=qall("SELECT * FROM dish_ips ORDER BY id DESC LIMIT 120")
        rows_html=""
        for r in rs:
            dn=esc(r.get('dish_name') or 'صحن')
            ip=esc(r.get('ip') or '')
            loc=esc(r.get('location') or '')
            rid=r['id']
                # Glass Tech + Chrome Click + بدون شرح
            rows_html += f'''
<div class="card dish-card glass-tech" id="dish-{rid}" data-name="{dn}" data-ip="{ip}" data-loc="{loc}" style="background:linear-gradient(135deg,rgba(30,36,58,0.85) 0%,rgba(18,24,42,0.9) 100%);border:1px solid rgba(100,150,255,0.18);box-shadow:0 0 0 1px rgba(100,150,255,0.08),0 8px 32px rgba(0,0,0,0.4),0 0 20px rgba(59,130,246,0.12);backdrop-filter:blur(12px);border-radius:14px;padding:12px;display:flex;justify-content:space-between;align-items:center">
<div style="flex:1;min-width:0">
<div style="display:flex;align-items:center;gap:7px"><span id="dot-{rid}" style="width:8px;height:8px;border-radius:50%;background:#555;display:inline-block;flex-shrink:0"></span><b class="dish-name" style="font-size:15px;font-weight:800;color:#fff">{dn}</b></div>
<a href="http://{ip}" target="_blank" rel="noopener" class="dish-ip" style="display:inline-block;margin-top:6px;background:#ffbe4d;color:#111;padding:4px 12px;border-radius:7px;font-family:monospace;font-size:13px;font-weight:800;text-decoration:none">{ip}</a>
</div>
<div style="display:flex;gap:5px"><button onclick="pingOneDish({rid})" style="background:#22c55e;color:#fff;border:0;padding:6px 10px;border-radius:7px;font-size:11px">Ping</button><button onclick="editDish({rid})" style="background:#1f2937;color:#fff;border:1px solid #ffffff15;padding:6px 10px;border-radius:7px;font-size:11px">تعديل</button><button onclick="askDel('/del_dish/{rid}',{rid},'dish')" style="background:#ef4444;color:#fff;border:0;padding:6px 10px;border-radius:7px;font-size:11px">حذف</button></div>
</div>'''
        return f"""
<div style='max-width:900px;margin:0 auto'>
<div class=card style='background:rgba(30,36,58,0.6);border:1px solid rgba(100,150,255,0.15);backdrop-filter:blur(10px)'>
<div style='display:flex;justify-content:space-between;align-items:center'><b>الصحون {len(rs)}</b><div style='display:flex;gap:6px'><button onclick="checkAllDishes()" class=btn-gold style='padding:6px 10px;background:#22c55e;color:#fff;font-size:11px'>فحص الكل</button><a href='/api/export/dishes' class=btn-gold style='text-decoration:none;padding:6px 10px;font-size:11px'>Excel</a></div></div>
<form id=formDish style='display:flex;gap:6px;margin-top:10px;flex-wrap:wrap'><input name=dish_name id=dish_name_input placeholder='اسم الصحن' required style='flex:1'><input name=ip id=dish_ip_input placeholder='192.168.1.1' required style='flex:1'><input name=location id=dish_loc_input placeholder='البرج / موقع' style='flex:1'><button class=btn-gold type=submit id=btnAddDish>إضافة</button></form>
<input id=searchBox placeholder='بحث...' oninput="searchDishes(this.value)" onkeydown="if(event.key==='Enter'){{searchDishes(this.value);}}" style='margin-top:10px'>
</div>
<div id=dl style='display:grid;gap:10px'>{rows_html}</div>
</div>
<script>
window.searchDishes=function(q){{ q=(q||'').toLowerCase(); document.querySelectorAll('.dish-card').forEach(c=>{{ let t=(c.dataset.name+c.dataset.ip+c.dataset.loc).toLowerCase(); c.style.display=t.includes(q)?'flex':'none'; }}); }};
window.editDish=function(id){{ let c=document.getElementById('dish-'+id); if(!c){{ alert('غير موجود'); return; }} let body=document.getElementById('editBody'); body.innerHTML=''; let i1=document.createElement('input'); i1.id='edit_dish_name'; i1.value=c.dataset.name; i1.placeholder='اسم الصحن'; i1.style.cssText='width:100%;padding:12px;margin:4px 0'; let i2=document.createElement('input'); i2.id='edit_ip'; i2.value=c.dataset.ip; i2.placeholder='IP'; i2.style.cssText='width:100%;padding:12px;margin:4px 0'; let i3=document.createElement('input'); i3.id='edit_loc'; i3.value=c.dataset.loc; i3.placeholder='البرج'; i3.style.cssText='width:100%;padding:12px;margin:4px 0'; let b=document.createElement('button'); b.textContent='حفظ'; b.className='btn-gold'; b.style.cssText='width:100%;padding:12px;margin-top:8px'; b.id='btnSaveDish'; b.onclick=function(){{ saveDish(id); }}; body.appendChild(i1); body.appendChild(i2); body.appendChild(i3); body.appendChild(b); document.getElementById('editModal').classList.add('show'); }};
window.saveDish=async function(id){{ let b=document.getElementById('btnSaveDish'); if(b){{ b.textContent='...'; b.disabled=true; }} let nn=document.getElementById('edit_dish_name').value.trim(); let ii=document.getElementById('edit_ip').value.trim(); let ll=document.getElementById('edit_loc').value.trim(); if(!ii){{ alert('IP مطلوب'); if(b){{ b.textContent='حفظ'; b.disabled=false; }} return; }} let fd=new URLSearchParams(); fd.append('dish_name',nn); fd.append('ip',ii); fd.append('location',ll); try{{ let r=await fetch('/edit_dish/'+id,{{method:'POST',body:fd,credentials:'same-origin'}}); let j=await r.json(); if(j.ok){{ let c=document.getElementById('dish-'+id); if(c){{ c.dataset.name=nn; c.dataset.ip=ii; c.dataset.loc=ll; c.querySelector('.dish-name').textContent=nn; c.querySelector('.dish-ip').textContent=ii; c.querySelector('.dish-loc').textContent=ll||'بدون موقع'; }} closeEditModal(); }}else{{ alert(j.msg||'خطأ'); if(b){{ b.textContent='حفظ'; b.disabled=false; }} }} }}catch(e){{ alert('خطأ'); if(b){{ b.textContent='حفظ'; b.disabled=false; }} }} }};
window.pingOneDish=async function(id){{ let c=document.getElementById('dish-'+id); let dot=document.getElementById('dot-'+id); if(!c||!dot) return; dot.style.background='#f59e0b'; dot.style.boxShadow='0 0 8px #f59e0b'; try{{ let r=await fetch('/api/ping?ip='+encodeURIComponent(c.dataset.ip),{{credentials:'same-origin',cache:'no-store'}}); let j=await r.json(); if(j.ok){{ dot.style.background='#22c55e'; dot.style.boxShadow='0 0 10px #22c55e'; }} else {{ dot.style.background='#ef4444'; dot.style.boxShadow='0 0 10px #ef4444'; }} }}catch(e){{ dot.style.background='#ef4444'; }} }};
window.checkAllDishes=async function(){{ for(let c of document.querySelectorAll('.dish-card')){{ let id=c.id.split('-')[1]; pingOneDish(id); await new Promise(r=>setTimeout(r,150)); }} }};
document.getElementById('formDish').addEventListener('submit', async e=>{{ e.preventDefault(); let btn=document.getElementById('btnAddDish'); btn.textContent='...'; btn.disabled=true; let fd=new FormData(e.target); try{{ let r=await fetch('/add_dish',{{method:'POST',body:fd,credentials:'same-origin'}}); let j=await r.json(); if(j.ok){{ let dl=document.getElementById('dl'); let card=document.createElement('div'); card.className='card dish-card glass-tech'; card.id='dish-'+j.id; card.dataset.name=j.name; card.dataset.ip=j.ip; card.dataset.loc=j.loc; card.style.cssText='background:linear-gradient(135deg,rgba(30,36,58,0.85) 0%,rgba(18,24,42,0.9) 100%);border:1px solid rgba(100,150,255,0.18);box-shadow:0 0 0 1px rgba(100,150,255,0.08),0 8px 32px rgba(0,0,0,0.4),0 0 20px rgba(59,130,246,0.12);border-radius:16px;padding:16px;display:flex;justify-content:space-between;align-items:center;border:1px solid #22c55e'; card.innerHTML=`<div style="flex:1"><div style="display:flex;align-items:center;gap:8px"><span class="status-dot" id="dot-${{j.id}}" style="width:10px;height:10px;border-radius:50%;background:#555;display:inline-block"></span><b class="dish-name" style="font-size:17px;font-weight:900">${{j.name}}</b></div><div style="margin:6px 0 0 18px;color:#94a3b8;font-size:12px" class="dish-loc">${{j.loc||'بدون موقع'}}</div><div style="margin-top:8px"><span class="dish-ip" style="display:inline-block;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;padding:5px 14px;border-radius:8px;font-family:monospace;font-size:13px;font-weight:800">${{j.ip}}</span></div></div><div style="display:flex;flex-direction:column;gap:6px"><button class="btn-gold" onclick="pingOneDish(${{j.id}})" style="padding:7px 14px;background:#22c55e;color:#fff;border-radius:8px;font-size:12px">Ping</button><div style="display:flex;gap:5px"><button class="btn-gold" onclick="editDish(${{j.id}})" style="padding:6px 10px;background:#1f2937;color:#fff;border:1px solid #ffffff15;border-radius:8px;font-size:11px;flex:1">تعديل</button><button class="btn-del" onclick="askDel('/del_dish/${{j.id}}',${{j.id}},'dish')" style="padding:6px 10px;border-radius:8px;font-size:11px;flex:1">حذف</button></div></div>`; dl.prepend(card); e.target.reset(); }}else alert(j.msg||'خطأ'); }}catch(e){{ alert('خطأ'); }} btn.textContent='إضافة'; btn.disabled=false; }});
// فحص تلقائي للصحون عند التحميل
// smooth - no auto ping
</script>
"""

    if v=='towers':
        rs=qall("SELECT * FROM towers ORDER BY id DESC")
        rows=""
        for r in rs:
            name=esc(r['name'])
            area=esc(r['area'] or '')
            lat=r.get('lat') or 0
            lng=r.get('lng') or 0
            rid=r['id']
            rows += f'''
<div class="card glass-tech" id="tower-{rid}" data-name="{name}" data-area="{area}" data-lat="{lat}" data-lng="{lng}" style="background:linear-gradient(135deg,rgba(30,36,58,0.8) 0%,rgba(18,24,42,0.85) 100%);border:1px solid rgba(100,150,255,0.18);box-shadow:0 0 0 1px rgba(100,150,255,0.06),0 8px 32px rgba(0,0,0,0.3),0 0 18px rgba(59,130,246,0.1);backdrop-filter:blur(10px);border-radius:16px;padding:14px;display:flex;justify-content:space-between;align-items:center">
<div style="flex:1"><b class="t-name" style="font-size:16px;font-weight:900;color:#fff">{name}</b><br><span class="t-area" style="color:#94a3b8;font-size:12px">{area}</span><br><span class="t-coord" style="color:#ffbe4d;font-family:monospace;font-size:11px;background:rgba(255,190,77,0.1);padding:2px 8px;border-radius:6px;margin-top:4px;display:inline-block">{lat},{lng}</span></div>
<div style="display:flex;gap:5px"><button class=btn-gold onclick="openEditTower({rid})" style="padding:6px 10px;background:#1f2937;color:#fff;border:1px solid #ffffff15;border-radius:8px;font-size:11px">تعديل</button><button class=btn-del onclick="askDel('/del_tower/{rid}',{rid},'tower')" style="padding:6px 10px;border-radius:8px;font-size:11px">حذف</button></div>
</div>'''
        return f"""
<div style='max-width:800px;margin:0 auto'>
<div class=card style='background:rgba(30,36,58,0.6);border:1px solid rgba(100,150,255,0.15);backdrop-filter:blur(10px)'>
<b>الابراج {len(rs)}</b>
<form id=formTower style='display:flex;gap:6px;margin-top:8px;flex-wrap:wrap'><input name=name placeholder='اسم البرج' required style='flex:1'><input name=area placeholder='المنطقة' style='flex:1'><input name=lat placeholder='35.131812' style='flex:0.6'><input name=lng placeholder='36.757812' style='flex:0.6'><button class=btn-gold>إضافة</button></form>
<input id=towerSearch placeholder='بحث...' oninput="searchTowers(this.value)" style='margin-top:8px'>
</div>
<div id=towerList style='display:grid;gap:10px'>{rows}</div>
</div>
<script>
window.searchTowers=function(q){{ q=(q||'').toLowerCase(); document.querySelectorAll('[id^=tower-]').forEach(c=>{{ let t=(c.dataset.name+c.dataset.area).toLowerCase(); c.style.display=t.includes(q)?'':'none'; }}); }};
window.openEditTower=function(id){{ let c=document.getElementById('tower-'+id); let body=document.getElementById('editBody'); body.innerHTML=''; let i1=document.createElement('input'); i1.id='edit_t_name'; i1.value=c.dataset.name; i1.style.cssText='width:100%;padding:10px;margin:4px 0'; let i2=document.createElement('input'); i2.id='edit_t_area'; i2.value=c.dataset.area; i2.style.cssText='width:100%;padding:10px;margin:4px 0'; let i3=document.createElement('input'); i3.id='edit_t_lat'; i3.value=c.dataset.lat; i3.style.cssText='width:100%;padding:10px;margin:4px 0'; let i4=document.createElement('input'); i4.id='edit_t_lng'; i4.value=c.dataset.lng; i4.style.cssText='width:100%;padding:10px;margin:4px 0'; let b=document.createElement('button'); b.textContent='حفظ'; b.className='btn-gold'; b.style.cssText='width:100%;padding:12px'; b.onclick=function(){{ saveTower(id); }}; body.append(i1,i2,i3,i4,b); document.getElementById('editModal').classList.add('show'); }};
window.saveTower=async function(id){{ let nn=document.getElementById('edit_t_name').value; let aa=document.getElementById('edit_t_area').value; let la=document.getElementById('edit_t_lat').value; let ln=document.getElementById('edit_t_lng').value; let fd=new URLSearchParams(); fd.append('name',nn); fd.append('area',aa); fd.append('lat',la); fd.append('lng',ln); let r=await fetch('/edit_tower/'+id,{{method:'POST',body:fd,credentials:'same-origin'}}); let j=await r.json(); if(j.ok){{ let c=document.getElementById('tower-'+id); c.dataset.name=nn; c.dataset.area=aa; c.dataset.lat=la; c.dataset.lng=ln; c.querySelector('.t-name').textContent=nn; c.querySelector('.t-area').textContent=''+(aa||'بدون منطقة'); c.querySelector('.t-coord').textContent=la+','+ln; closeEditModal(); }} }};
document.getElementById('formTower').addEventListener('submit', async e=>{{ e.preventDefault(); let fd=new FormData(e.target); let r=await fetch('/add_tower',{{method:'POST',body:fd,credentials:'same-origin'}}); let j=await r.json(); if(j.ok){{ let list=document.getElementById('towerList'); let card=document.createElement('div'); card.className='card glass-tech'; card.id='tower-'+j.id; card.dataset.name=j.name; card.dataset.area=j.area; card.dataset.lat=j.lat; card.dataset.lng=j.lng; card.style.cssText='background:linear-gradient(135deg,rgba(30,36,58,0.8) 0%,rgba(18,24,42,0.85) 100%);border:1px solid rgba(100,150,255,0.18);border-radius:16px;padding:14px;display:flex;justify-content:space-between;border:1px solid #22c55e'; card.innerHTML=`<div style="flex:1"><b class="t-name" style="font-size:16px;font-weight:900">${{j.name}}</b><br><span class="t-area" style="color:#94a3b8;font-size:12px">${{j.area||'بدون منطقة'}}</span><br><span class="t-coord" style="color:#ffbe4d;font-family:monospace;font-size:11px">${{j.lat}},${{j.lng}}</span></div><div style="display:flex;gap:5px"><button class="btn-gold" onclick="openEditTower(${{j.id}})" style="padding:6px 10px;background:#1f2937;color:#fff;border:1px solid #ffffff15;border-radius:8px;font-size:11px">تعديل</button><button class="btn-del" onclick="askDel('/del_tower/${{j.id}}',${{j.id}},'tower')" style="padding:6px 10px;border-radius:8px;font-size:11px">حذف</button></div>`; list.prepend(card); e.target.reset(); }} else alert(j.msg||'خطأ'); }});
</script>
"""

    if v=='subs':
        rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 200")
        rows=""
        for r in rs:
            rows += "<div class='card' id='sub-"+str(r['id'])+"' data-name='"+esc(r['name'])+"' data-phone='"+esc(r['phone'] or '')+"' data-note='"+esc(r['note'] or '')+"' style='display:flex;justify-content:space-between'><div><b class='s-name'>"+esc(r['name'])+"</b><br><span class='s-phone'>"+esc(r['phone'] or '')+"</span></div><div><button class=btn-gold onclick=\"openEditSub("+str(r['id'])+")\">تعديل</button> <button class=btn-del onclick=\"askDel('/del_sub/"+str(r['id'])+"',"+str(r['id'])+",'sub')\">حذف</button></div></div>"
        return "<div style='max-width:700px;margin:0 auto'><div class=card><b>المشتركين</b><form id=formSub style='display:flex;gap:5px;margin-top:8px;flex-wrap:wrap'><input name=name placeholder='الاسم' required style='flex:1'><input name=phone placeholder='رقم' style='flex:1'><input name=note placeholder='ملاحظة' style='flex:1'><button class=btn-gold>إضافة</button></form></div><div id=subList style='display:grid;gap:8px'>"+rows+"</div><script>window.openEditSub=function(id){ let c=document.getElementById('sub-'+id); let body=document.getElementById('editBody'); body.innerHTML=''; let i1=document.createElement('input'); i1.id='edit_s_name'; i1.value=c.dataset.name; i1.style.cssText='width:100%;padding:10px;margin:4px 0'; let i2=document.createElement('input'); i2.id='edit_s_phone'; i2.value=c.dataset.phone; i2.style.cssText='width:100%;padding:10px;margin:4px 0'; let i3=document.createElement('input'); i3.id='edit_s_note'; i3.value=c.dataset.note; i3.style.cssText='width:100%;padding:10px;margin:4px 0'; let b=document.createElement('button'); b.textContent='حفظ'; b.className='btn-gold'; b.style.cssText='width:100%;padding:12px;margin-top:8px'; b.onclick=function(){ saveSub(id); }; body.append(i1,i2,i3,b); document.getElementById('editModal').classList.add('show'); }; window.saveSub=async function(id){ let nn=document.getElementById('edit_s_name').value; let pp=document.getElementById('edit_s_phone').value; let no=document.getElementById('edit_s_note').value; let fd=new URLSearchParams(); fd.append('name',nn); fd.append('phone',pp); fd.append('note',no); let r=await fetch('/edit_sub/'+id,{method:'POST',body:fd,credentials:'same-origin'}); let j=await r.json(); if(j.ok){ let c=document.getElementById('sub-'+id); c.dataset.name=nn; c.dataset.phone=pp; c.dataset.note=no; c.querySelector('.s-name').textContent=nn; c.querySelector('.s-phone').textContent=pp; closeEditModal(); } }; document.getElementById('formSub').addEventListener('submit', async e=>{ e.preventDefault(); let r=await fetch('/add_sub',{method:'POST',body:new FormData(e.target),credentials:'same-origin'}); let j=await r.json(); if(j.ok){ let list=document.getElementById('subList'); let card=document.createElement('div'); card.className='card'; card.id='sub-'+j.id; card.dataset.name=j.name; card.dataset.phone=j.phone; card.dataset.note=j.note; card.style.cssText='display:flex;justify-content:space-between;border:1px solid #22c55e'; card.innerHTML='<div><b class=\"s-name\">'+j.name+'</b><br><span class=\"s-phone\">'+j.phone+'</span></div><div><button class=\"btn-gold\" onclick=\"openEditSub('+j.id+')\">تعديل</button> <button class=\"btn-del\" onclick=\"askDel(\\'/del_sub/'+j.id+'\\','+j.id+',\\'sub\\')\">حذف</button></div>'; list.prepend(card); e.target.reset(); } });</script></div>"

    if v=='ledger':
        rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 200")
        rows=""
        for r in rs:
            rows += "<div class='card' id='led-"+str(r['id'])+"' data-name='"+esc(r['name'])+"' data-amount='"+str(r['amount'])+"' data-note='"+esc(r.get('note') or '')+"'><div style='display:flex;justify-content:space-between'><div><b class='l-name'>"+esc(r['name'])+"</b> - <b class='l-amount' style='color:#ffbe4d'>"+str(r['amount'])+"</b></div><div><button class=btn-gold onclick=\"openEditLed("+str(r['id'])+")\">تعديل</button> <button class=btn-del onclick=\"askDel('/del_ledger/"+str(r['id'])+"',"+str(r['id'])+",'led')\">حذف</button></div></div></div>"
        return "<div style='max-width:700px;margin:0 auto'><div class=card><b>الحسابات</b><form id=formLed style='display:flex;gap:5px;margin-top:8px;flex-wrap:wrap'><input name=name placeholder='الاسم' required style='flex:1'><input name=amount type=number step=0.01 placeholder='المبلغ' required style='flex:1'><input name=note placeholder='ملاحظة' style='flex:1'><select name=currency style='flex:0.5'><option>USD</option><option>SYP</option></select><button class=btn-gold>إضافة</button></form></div><div id=ledList style='display:grid;gap:8px'>"+rows+"</div><script>window.openEditLed=function(id){ let c=document.getElementById('led-'+id); let body=document.getElementById('editBody'); body.innerHTML=''; let i1=document.createElement('input'); i1.id='edit_l_name'; i1.value=c.dataset.name; i1.style.cssText='width:100%;padding:10px;margin:4px 0'; let i2=document.createElement('input'); i2.id='edit_l_amount'; i2.value=c.dataset.amount; i2.type='number'; i2.style.cssText='width:100%;padding:10px;margin:4px 0'; let b=document.createElement('button'); b.textContent='حفظ'; b.className='btn-gold'; b.style.cssText='width:100%;padding:12px'; b.onclick=function(){ saveLed(id); }; body.append(i1,i2,b); document.getElementById('editModal').classList.add('show'); }; window.saveLed=async function(id){ let nn=document.getElementById('edit_l_name').value; let aa=document.getElementById('edit_l_amount').value; let fd=new URLSearchParams(); fd.append('name',nn); fd.append('amount',aa); fd.append('note',''); fd.append('currency','USD'); let r=await fetch('/edit_ledger/'+id,{method:'POST',body:fd,credentials:'same-origin'}); let j=await r.json(); if(j.ok){ let c=document.getElementById('led-'+id); c.dataset.name=nn; c.dataset.amount=aa; c.querySelector('.l-name').textContent=nn; c.querySelector('.l-amount').textContent=aa; closeEditModal(); } }; document.getElementById('formLed').addEventListener('submit', async e=>{ e.preventDefault(); let r=await fetch('/add_ledger',{method:'POST',body:new FormData(e.target),credentials:'same-origin'}); let j=await r.json(); if(j.ok){ let list=document.getElementById('ledList'); let card=document.createElement('div'); card.className='card'; card.id='led-'+j.id; card.dataset.name=j.name; card.dataset.amount=j.amount; card.style.cssText='display:flex;justify-content:space-between;border:1px solid #22c55e'; card.innerHTML='<div><b class=\"l-name\">'+j.name+'</b> - <b class=\"l-amount\">'+j.amount+'</b></div><div><button class=\"btn-gold\" onclick=\"openEditLed('+j.id+')\">تعديل</button> <button class=\"btn-del\" onclick=\"askDel(\\'/del_ledger/'+j.id+'\\','+j.id+',\\'led\\')\">حذف</button></div>'; list.prepend(card); e.target.reset(); } });</script></div>"

    if v=='logs':
        rs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 1000")
        rows=""
        for r in rs:
            col='#22c55e' if 'إضافة' in r.get('action','') else '#0ea5e9' if 'تعديل' in r.get('action','') else '#ef4444' if 'حذف' in r.get('action','') else '#ffbe4d'
            rows += "<div class='card' style='font-size:12px;border-right:3px solid "+col+";display:flex;justify-content:space-between'><div><b style='color:#ffbe4d'>"+esc(r.get('user_phone',''))+"</b> <span style='background:"+col+";color:#fff;padding:1px 6px;border-radius:5px;font-size:10px'>"+esc(r.get('action',''))+"</span> <small style='color:#aaa'>"+esc(r.get('detail',''))[:120]+"</small></div><small style='color:#555'>"+esc(r.get('time',''))+"</small></div>"
        if not rows:
            rows="<div class=card style='text-align:center;padding:20px'>السجل فاضي<br><button class=btn-gold onclick=\"fetch('/api/seed_log',{method:'POST',credentials:'same-origin'}).then(()=>loadPage('logs',true))\" style='margin-top:8px'>اضافة سجل تجريبي</button></div>"
        return "<div style='max-width:1000px;margin:0 auto'><div class=card style='display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px'><b>السجل الكامل ("+str(len(rs))+")</b><div style='display:flex;gap:6px'><input id=logSearch placeholder='بحث...' oninput=\"searchLogs(this.value)\" style='width:140px'><a href='/api/export/logs' class=btn-gold style='text-decoration:none;padding:6px 10px;background:#22c55e;color:#fff'>Excel</a><button onclick=\"if(confirm('مسح؟')){ fetch('/api/clear_logs',{method:'POST',credentials:'same-origin'}).then(r=>r.json()).then(j=>{ if(j.ok) loadPage('logs',true); }) }\" class=btn-del>مسح</button></div></div><div id=logList style='display:grid;gap:6px'>"+rows+"</div><script>window.searchLogs=function(q){ q=(q||'').toLowerCase(); document.querySelectorAll('#logList .card').forEach(c=>{ c.style.display=c.textContent.toLowerCase().includes(q)?'':'none'; }); }</script></div>"

    if v=='map':
        towers=qall("SELECT * FROM towers")
        tj_json=json.dumps([{"name":t['name'],"area":t.get('area') or '',"lat":float(t.get('lat') or 35.131812),"lng":float(t.get('lng') or 36.757812)} for t in towers],ensure_ascii=False)
        return """
<div class=card style='padding:8px'>
<div style='display:flex;gap:6px;margin-bottom:8px;flex-wrap:wrap'>
<input id=mapSearch placeholder='بحث برج...' style='flex:1'>
<button class=btn-gold onclick="doMapSearch()">بحث</button>
<button class=btn-gold onclick="locateMe()" style='background:#22c55e;color:#fff'>موقعي</button>
<button class=btn-gold onclick="enableAddPoint()" id=addPointBtn style='background:#f59e0b'>نقطة</button>
<span id=coordsLabel style='color:#ffbe4d;font-family:monospace'>-</span>
</div>
<div id=map style='height:70vh;border-radius:12px;background:#111'></div>
</div>
<script>
(function(){ if(window._leafletLoaded) return Promise.resolve(); return new Promise(res=>{ let l=document.createElement('link'); l.rel='stylesheet'; l.href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'; document.head.appendChild(l); let s=document.createElement('script'); s.src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'; s.onload=()=>{window._leafletLoaded=true; res();}; document.head.appendChild(s); }); })()
let _towers="""+tj_json+""";
let _map=null; let addPointMode=false;
window.doMapSearch=function(){ let q=document.getElementById('mapSearch').value.trim().toLowerCase(); if(!q) return; let f=_towers.find(t=>t.name.toLowerCase().includes(q)||t.area.toLowerCase().includes(q)); if(f&&_map) _map.flyTo([f.lat,f.lng],17); };
window.locateMe=function(){ if(_map&&navigator.geolocation) navigator.geolocation.getCurrentPosition(p=>{ _map.flyTo([p.coords.latitude,p.coords.longitude],17); L.marker([p.coords.latitude,p.coords.longitude]).addTo(_map).bindPopup(p.coords.latitude.toFixed(6)+','+p.coords.longitude.toFixed(6)).openPopup(); },null,{enableHighAccuracy:true}); };
window.enableAddPoint=function(){ addPointMode=!addPointMode; let b=document.getElementById('addPointBtn'); b.textContent=addPointMode?'اضغط الخريطة':'نقطة'; b.style.background=addPointMode?'#ef4444':'#f59e0b'; };
setTimeout(()=>{
  _map=L.map('map').setView([35.131812,36.757812],13);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19}).addTo(_map);
  _towers.forEach(t=>{ L.marker([t.lat,t.lng]).addTo(_map).bindPopup('<b>'+t.name+'</b><br>'+t.lat.toFixed(6)+','+t.lng.toFixed(6)); });
  _map.on('mousemove',e=>{ document.getElementById('coordsLabel').textContent=e.latlng.lat.toFixed(6)+','+e.latlng.lng.toFixed(6); });
  _map.on('click',e=>{
    document.getElementById('coordsLabel').textContent=e.latlng.lat.toFixed(6)+','+e.latlng.lng.toFixed(6);
    if(addPointMode){
      let name=prompt('اسم البرج؟')||'نقطة';
      let fd=new URLSearchParams();
      fd.append('name',name); fd.append('lat',e.latlng.lat.toFixed(6)); fd.append('lng',e.latlng.lng.toFixed(6));
      fetch('/add_tower',{method:'POST',body:fd,credentials:'same-origin'}).then(r=>r.json()).then(j=>{ if(j.ok){ L.marker([e.latlng.lat,e.latlng.lng]).addTo(_map).bindPopup(name).openPopup(); } });
    }
  });
},400);
</script>
"""

    if v=='network':
        dishes=qall("SELECT * FROM dish_ips ORDER BY id DESC LIMIT 100")
        rows=""
        for d in dishes:
            rows += "<div class='card glass-tech' id='net-"+str(d['id'])+"' data-ip='"+esc(d.get('ip',''))+"' style='display:flex;justify-content:space-between;align-items:center'><div><div style='display:flex;align-items:center;gap:6px'><span class='net-dot' style='width:8px;height:8px;border-radius:50%;background:#555;display:inline-block'></span><b>"+esc(d.get('dish_name') or 'صحن')+"</b> - "+esc(d.get('ip',''))+"</div><small class='net-out' style='color:#666'>...</small></div><button class=btn-gold onclick='checkOne("+str(d['id'])+")'>فحص</button></div>"
        return "<div style='max-width:800px;margin:0 auto'><div class=card><b>حالة الشبكة</b><button class=btn-gold onclick='checkAll()' style='width:100%;margin-top:8px;background:#22c55e;color:#fff'>فحص الكل</button></div>"+rows+"<script>window.checkOne=async function(id){ let c=document.getElementById('net-'+id); let out=c.querySelector('.net-out'); let dot=c.querySelector('.net-dot'); out.textContent='...'; dot.style.background='#f59e0b'; try{ let r=await fetch('/api/ping?ip='+encodeURIComponent(c.dataset.ip),{credentials:'same-origin'}); let j=await r.json(); out.textContent=j.out.slice(0,80); out.style.color=j.ok?'#22c55e':'#ef4444'; dot.style.background=j.ok?'#22c55e':'#ef4444'; dot.style.boxShadow=j.ok?'0 0 8px #22c55e':'0 0 8px #ef4444'; }catch(e){ out.textContent='خطأ'; dot.style.background='#ef4444'; } }; window.checkAll=async function(){ for(let c of document.querySelectorAll('[id^=net-]')){ await checkOne(c.id.split('-')[1]); await new Promise(r=>setTimeout(r,120)); } }; // smooth - no auto</script></div>"

    if v=='settings':
        us=qall("SELECT * FROM users ORDER BY phone DESC")
        uh=""
        for u in us:
            badge = "<span style='background:#ffbe4d;color:#111;padding:2px 6px;border-radius:6px;font-size:10px'>مدير</span>" if u.get("role")=="manager" else "<span style='background:#ffffff15;padding:2px 6px;border-radius:6px;font-size:10px'>فني</span>"
            uh += '<div class="card" id="user-'+esc(u["phone"])+'" data-phone="'+esc(u["phone"])+'" data-username="'+esc(u.get("username") or "")+'" data-role="'+esc(u.get("role") or "")+'" style="display:flex;justify-content:space-between"><div><b>'+esc(u.get("username") or "")+'</b><br><span style="color:#ffbe4d">'+esc(u["phone"])+'</span> '+badge+'</div><div style="display:flex;gap:4px"><button class=btn-gold onclick="openEditUser(\''+esc(u["phone"])+'\')">تعديل</button><button class=btn-del onclick="askDel(\'/del_user/'+esc(u["phone"])+'\',\''+esc(u["phone"])+'\',\'user\')">حذف</button></div></div>'
        return "<div style='max-width:800px;margin:0 auto'><div class=card><b>كلمة السر الخاصة بك</b><form id=formPass style='display:flex;gap:6px;margin-top:8px'><input name=newpass type=password placeholder='جديدة' required style='flex:1'><button class=btn-gold>حفظ</button></form></div><div style='display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px'><div class=card style='text-align:center'><b>اللغة والثيم</b><br><button onclick=\"toggleLangInstant()\" class=btn-gold style='width:100%;margin-top:8px;background:#1f2937;color:#fff'>🌐 تغيير اللغة فوري</button><button onclick=\"toggleThemeNoReload()\" class=btn-gold style='width:100%;margin-top:6px'>تغيير الثيم</button></div><div class=card><b>إضافة يوزر</b><form id=formUser style='display:flex;flex-direction:column;gap:6px;margin-top:8px'><input name=user_field placeholder='رقم / يوزر' required><input name=password type=password placeholder='كلمة السر' required><select name=role><option value=tech>فني</option><option value=manager>مدير</option></select><button class=btn-gold id=btnAddUser>إضافة فوري</button></form></div></div><div class=card><b>تصدير</b><div style='display:flex;gap:6px;flex-wrap:wrap;margin-top:6px'><a href='/api/export/users' class=btn-gold style='text-decoration:none;padding:6px 10px;background:#22c55e;color:#fff'>يوزرات</a><a href='/api/export/dishes' class=btn-gold style='text-decoration:none;padding:6px 10px;background:#0ea5e9;color:#fff'>صحون</a><a href='/api/export/towers' class=btn-gold style='text-decoration:none;padding:6px 10px;background:#ffbe4d;color:#111'>أبراج</a><a href='/api/export/logs' class=btn-gold style='text-decoration:none;padding:6px 10px;background:#8b5cf6;color:#fff'>سجل</a></div></div><div id=userList style='display:grid;gap:6px'>"+uh+"</div></div><script>window.openEditUser=function(ph){ let c=document.getElementById('user-'+ph); let body=document.getElementById('editBody'); body.innerHTML=''; let i1=document.createElement('input'); i1.id='edit_u_field'; i1.value=c.dataset.phone; i1.style.cssText='width:100%;padding:10px;margin:4px 0'; let i2=document.createElement('input'); i2.id='edit_u_pass'; i2.type='password'; i2.placeholder='باسورد جديدة (فارغ)'; i2.style.cssText='width:100%;padding:10px;margin:4px 0'; let s=document.createElement('select'); s.id='edit_u_role'; s.style.cssText='width:100%;padding:10px;margin:4px 0'; s.innerHTML='<option value=\"tech\">فني</option><option value=\"manager\">مدير</option>'; s.value=c.dataset.role; let b=document.createElement('button'); b.textContent='حفظ'; b.className='btn-gold'; b.style.cssText='width:100%;padding:12px;margin-top:8px'; b.id='btnSaveUserEdit'; b.onclick=function(){ saveUser(ph); }; body.append(i1,i2,s,b); document.getElementById('editModal').classList.add('show'); }; window.saveUser=async function(oldPh){ let b=document.getElementById('btnSaveUserEdit'); b.textContent='...'; b.disabled=true; let ff=document.getElementById('edit_u_field').value.trim(); let pw=document.getElementById('edit_u_pass').value; let ro=document.getElementById('edit_u_role').value; if(!ff){ alert('مطلوب'); b.textContent='حفظ'; b.disabled=false; return; } let fd=new URLSearchParams(); fd.append('old_phone',oldPh); fd.append('phone',ff); fd.append('username',ff); fd.append('role',ro); if(pw.trim()!=''){ fd.append('password',pw.trim()); } let r=await fetch('/edit_user',{method:'POST',body:fd,credentials:'same-origin'}); let j=await r.json(); if(!j.ok){ alert(j.msg||'خطأ'); b.textContent='حفظ'; b.disabled=false; } else { let c=document.getElementById('user-'+oldPh); if(c){ c.id='user-'+ff; c.dataset.phone=ff; c.dataset.role=ro; } closeEditModal(); } }; document.getElementById('formPass').addEventListener('submit', async e=>{ e.preventDefault(); let fd=new FormData(e.target); let r=await fetch('/change_pass',{method:'POST',body:fd,credentials:'same-origin'}); let j=await r.json(); if(j.ok){ e.target.reset(); alert('تم'); } else alert(j.msg||'خطأ'); }); document.getElementById('formUser').addEventListener('submit', async e=>{ e.preventDefault(); let btn=document.getElementById('btnAddUser'); btn.textContent='...'; btn.disabled=true; let r=await fetch('/add_user',{method:'POST',body:new FormData(e.target),credentials:'same-origin'}); let j=await r.json(); if(j.ok){ let ph=e.target.user_field.value; let role=e.target.role.value; let list=document.getElementById('userList'); let card=document.createElement('div'); card.className='card'; card.id='user-'+ph; card.dataset.phone=ph; card.dataset.role=role; card.style.cssText='display:flex;justify-content:space-between;border:1px solid #22c55e'; card.innerHTML='<div><b>'+ph+'</b><br><span style=\"color:#ffbe4d\">'+ph+'</span></div><div><button class=\"btn-gold\" onclick=\"openEditUser(\\''+ph+'\\')\">تعديل</button> <button class=\"btn-del\" onclick=\"askDel(\\'/del_user/'+ph+'\\',\\''+ph+'\\',\\'user\\')\">حذف</button></div>'; list.prepend(card); e.target.reset(); } else alert(j.msg||'خطأ'); btn.textContent='إضافة فوري'; btn.disabled=false; });</script>"

    if v=='support':
        return """<div style='max-width:500px;margin:0 auto'>
<div class=card style='text-align:center;padding:24px;background:linear-gradient(135deg,rgba(30,36,58,0.8),rgba(18,24,42,0.9));border:1px solid rgba(100,150,255,0.15)'>
<b>الدعم الفني OMAIA ISP</b>
<div style='font-size:22px;color:#ffbe4d;margin:12px 0' dir=ltr>+90 534 485 10 45</div>
<div style='display:flex;gap:8px;justify-content:center;flex-wrap:wrap'>
<a href='https://wa.me/905344851045' target=_blank style='display:inline-block;background:#22c55e;color:#fff;padding:10px 20px;border-radius:10px;text-decoration:none'>واتساب</a>
<a href='tel:+905344851045' style='display:inline-block;background:#0ea5e9;color:#fff;padding:10px 20px;border-radius:10px;text-decoration:none'>اتصال</a>
</div>
</div>
</div>"""

    return "<div class=card>غير موجود</div>"

def layout(c,v='home'):
    role=session.get('role') or 'tech'
    username_display=esc(session.get('username') or session.get('phone') or '')
    req_lang=session.get('lang','ar')
    return f"""<html dir=rtl lang={req_lang}><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<link rel=preconnect href='https://fonts.gstatic.com'>
<style>
*{{box-sizing:border-box;font-family:'Cairo',system-ui}}body{{margin:0;background:radial-gradient(1200px 600px at 20% -10%, #1a2a5a 0%, #0a0e2a 55%),radial-gradient(1000px 500px at 90% 0%, #1e3a5f 0%, transparent 60%),#0a0e2a;color:#fff;direction:rtl;overflow-x:hidden}}
.top{{position:fixed;top:0;left:0;right:0;height:56px;background:#0f172a;display:flex;align-items:center;justify-content:space-between;padding:0 12px;z-index:1003;border-bottom:1px solid #ffffff10}}
.sidebar{{position:fixed;top:0;right:0;width:260px;height:100%;background:#0f172a;color:#fff;z-index:1002;padding-top:64px;transform:translateX(110%);transition:transform .22s ease;overflow-y:auto;border-left:1px solid #ffffff10}}
.sidebar.active{{transform:none}}
.sidebar a{{display:block;padding:10px 14px;margin:4px 8px;color:#cbd5e1;text-decoration:none;border-radius:10px;background:#ffffff05}}
.sidebar a.active{{background:#ffbe4d;color:#111;font-weight:800}}
#overlay{{position:fixed;inset:0;background:#0006;z-index:1001;display:none}}#overlay.show{{display:block}}
.main{{margin-top:64px;padding:12px}}
.card{{background:#1e253a;padding:12px;border-radius:14px;margin-bottom:10px;border:1px solid #ffffff0f}}
.glass-tech{{background:linear-gradient(135deg,rgba(30,36,58,0.8) 0%,rgba(18,24,42,0.85) 100%)!important;border:1px solid rgba(100,150,255,0.18)!important;box-shadow:0 0 0 1px rgba(100,150,255,0.06),0 8px 32px rgba(0,0,0,0.3),0 0 18px rgba(59,130,246,0.1)!important;backdrop-filter:blur(12px)!important}}
input,select{{padding:10px;margin:4px 0;border-radius:10px;border:1px solid #ffffff15;width:100%;background:#0f1424;color:#fff}}
.btn-gold{{background:#ffbe4d;color:#111;padding:8px 14px;border:0;border-radius:10px;font-weight:700;cursor:pointer}}
.btn-del{{background:#ef4444;color:#fff;padding:7px 12px;border:0;border-radius:10px;cursor:pointer}}
#delModal,#editModal{{position:fixed;inset:0;background:#0008;display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:.2s;z-index:2000}}
#delModal.show,#editModal.show{{opacity:1;pointer-events:auto}}
#delBox,#editBox{{background:#1e253a;padding:20px;border-radius:16px;width:92%;max-width:420px;border:1px solid #ffffff15}}
</style></head><body>
<div id=overlay onclick="toggleSb(false)"></div>
<div class=sidebar id=sb>
<div style='padding:0 14px 10px;border-bottom:1px solid #ffffff10;margin-bottom:8px'>
<div style='font-weight:900'>OMAIA <span style='color:#ffbe4d'>ISP</span></div><small style='color:#666'>{username_display} • {role}</small><br><small style='color:#ffbe4d'>+905344851045</small></div>
<a href="javascript:loadPage('home')" id=nav-home>الرئيسية</a>
<a href="javascript:loadPage('dishes')" id=nav-dishes>الصحون</a>
<a href="javascript:loadPage('ping')" id=nav-ping>بنج</a>
<a href="javascript:loadPage('network')" id=nav-network>حالة الشبكة</a>
<a href="javascript:loadPage('towers')" id=nav-towers>الأبراج</a>
<a href="javascript:loadPage('subs')" id=nav-subs>المشتركين</a>
<a href="javascript:loadPage('ledger')" id=nav-ledger>الحسابات</a>
<a href="javascript:loadPage('logs')" id=nav-logs>السجل</a>
<a href="javascript:loadPage('map')" id=nav-map>الخريطة</a>
<a href="javascript:loadPage('settings')" id=nav-settings>الإعدادات</a>
<a href="javascript:loadPage('support')" id=nav-support style='color:#22c55e;background:#22c55e15'>الدعم - 905344851045+</a>
<a href="javascript:logoutFast()" style='margin-top:12px;color:#ef4444;background:#ef444415'>خروج</a>
</div>
<div class=top>
<div style='display:flex;gap:8px;align-items:center'><span onclick="toggleSb()" style='font-size:20px;cursor:pointer;padding:6px 10px;background:#ffffff0a;border-radius:10px'>☰</span><input id=topsearch placeholder='بحث...' oninput="globalSearchTop(this.value)" style='width:40px;padding:7px 10px'></div>
<div style='font-weight:900'>OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<div style='display:flex;gap:6px'><button onclick="toggleThemeNoReload()" style='background:#ffffff0a;color:#fff;border:1px solid #ffffff10;padding:6px 10px;border-radius:10px'>🌓</button><button onclick="toggleLangInstant()" id=langBtn style='background:#ffffff0a;color:#fff;border:1px solid #ffffff10;padding:6px 10px;border-radius:10px'>🌐 {req_lang}</button></div>
</div>
<div id=searchResults style='position:fixed;top:60px;right:10px;max-width:400px;width:92%;background:#1e253a;border:1px solid #ffffff15;border-radius:12px;z-index:1500;display:none;max-height:50vh;overflow:auto'></div>
<div class=main id=mn>{c}</div>
<div id=delModal><div id=delBox><h3 style='text-align:center'>تأكيد الحذف؟</h3><div style='display:flex;gap:10px;margin-top:14px'><button onclick="closeDel()" style='flex:1;padding:10px;border-radius:10px;background:transparent;color:#fff;border:1px solid #ffffff20'>تراجع</button><button id=delYes style='flex:1;padding:10px;border-radius:10px;background:#ef4444;color:#fff;border:0;font-weight:700'>حذف</button></div></div></div>
<div id=editModal><div id=editBox><div style='display:flex;justify-content:space-between;margin-bottom:12px'><b>تعديل</b><button onclick="closeEditModal()" style='background:#ffffff15;border:0;color:#fff;width:30px;height:30px;border-radius:50%'>✕</button></div><div id=editBody></div></div></div>
<script>window._leafletLoaded=false; window._leafletLoading=false;</script>
<script>
let cur='{v}';
function toggleSb(f){{ let sb=document.getElementById('sb'),ov=document.getElementById('overlay'); let o=f!==undefined?f:!sb.classList.contains('active'); sb.classList.toggle('active',o); ov.classList.toggle('show',o); }}
let pageCache={{}};
function saveCache(){{}}

async function loadPage(v,force=false,push=true){{
  if(push&&cur!==v){{ try{{ history.pushState({{page:v}},'', '/dash?v='+v); }}catch(e){{}} }}
  cur=v; toggleSb(false);
  document.querySelectorAll('.sidebar a').forEach(a=>a.classList.remove('active'));
  let n=document.getElementById('nav-'+v); if(n) n.classList.add('active');
  let mn=document.getElementById('mn');
  let lang=localStorage.getItem('omaia_lang')||'{req_lang}';
  let cacheKey=v+'_'+lang;
  // السجل والرئيسية لا كاش - دائما فريش
  let noCache = (v==='logs' || v==='home');
  if(!force&&!noCache&&pageCache[cacheKey]){{
    mn.innerHTML=pageCache[cacheKey];
    execScripts();
    fetch('/api/page?v='+v,{{credentials:'same-origin',cache:'no-store'}}).then(r=>r.text()).then(h=>{{ pageCache[cacheKey]=h; }}).catch(()=>{{}});
    return;
  }}
  if(!noCache && pageCache[cacheKey] && !force){{
    mn.innerHTML=pageCache[cacheKey];
    execScripts();
  }} else if(noCache || !pageCache[cacheKey]) {{
    mn.innerHTML='<div class=card style="text-align:center;padding:16px">...</div>';
  }}
  try{{
    let r=await fetch('/api/page?v='+v,{{credentials:'same-origin',cache:'no-store'}});
    let h=await r.text();
    if(!noCache){{ pageCache[cacheKey]=h; }}
    mn.innerHTML=h;
    execScripts();
  }}catch(e){{ mn.innerHTML='<div class=card>خطأ: '+e+'</div>'; }}
}}
function execScripts(){{ let mn=document.getElementById('mn'); mn.querySelectorAll('script').forEach(old=>{{ let s=document.createElement('script'); s.textContent=old.textContent; document.body.appendChild(s); s.remove(); }}); }}
function askDel(url,id,type){{ window._delUrl=url; window._delId=id; window._delType=type; document.getElementById('delModal').classList.add('show'); }}
function closeDel(){{ document.getElementById('delModal').classList.remove('show'); window._delUrl=null; }}
window.closeEditModal=function(){{ document.getElementById('editModal').classList.remove('show'); }};
document.getElementById('delYes').onclick=async()=>{{
  if(!window._delUrl) return;
  let el=document.getElementById((window._delType||'dish')+'-'+window._delId);
  if(el) el.style.opacity='0.4';
  document.getElementById('delModal').classList.remove('show');
  try{{
    let r=await fetch(window._delUrl,{{credentials:'same-origin'}});
    let j=await r.json();
    if(j.ok){{
      if(el) el.style.display='none';
      let lang=localStorage.getItem('omaia_lang')||'{req_lang}';
      delete pageCache[cur+'_'+lang];

    }}else{{
      if(el) el.style.opacity='1';
      alert(j.msg||'خطأ');
    }}
  }}catch(e){{ if(el) el.style.opacity='1'; alert(e); }}
}};
async function toggleThemeNoReload(){{
  let r=await fetch('/toggle_theme',{{credentials:'same-origin'}});
  await r.json();
}}
window.toggleLangInstant=async function(){{
  let btn=document.getElementById('langBtn');
  btn.textContent='...';
  try{{ let r=await fetch('/toggle_lang',{{method:'GET',credentials:'same-origin',cache:'no-store'}}); let j=await r.json(); if(j.ok){{ localStorage.setItem('omaia_lang',j.lang); location.reload(); }} }}catch(e){{ btn.textContent='🌐'; }}
}};
window.globalSearchTop=async function(q){{
  let box=document.getElementById('searchResults');
  if(!q||q.length<2){{ box.style.display='none'; return; }}
  let r=await fetch('/api/search?q='+encodeURIComponent(q),{{credentials:'same-origin'}});
  let d=await r.json();
  if(!d.length){{ box.style.display='none'; return; }}
  let h='';
  d.forEach(x=>{{
    h+='<div onclick="loadPage(\\''+x.page+'\\');document.getElementById(\\'searchResults\\').style.display=\\'none\\'" style="padding:10px 12px;cursor:pointer;border-bottom:1px solid #ffffff08"><b>'+x.title+'</b><br><small style="color:#666">'+x.sub+'</small></div>';
  }});
  box.innerHTML=h; box.style.display='block';
}};
window.logoutFast=async function(){{ await fetch('/api/logout',{{method:'POST',credentials:'same-origin'}}); location.replace('/login'); }};
window.addEventListener('popstate',(e)=>{{ let v='home'; if(e.state&&e.state.page) v=e.state.page; else {{ let p=new URLSearchParams(location.search); v=p.get('v')||'home'; }} loadPage(v,false,false); }});
loadPage(cur,true,false);
</script></body></html>"""

if __name__=='__main__':
    port=int(os.environ.get("PORT",10000))
    print("OMAIA GLASS TECH - fast - "+str(port))
    app.run(host='0.0.0.0',port=port,debug=False)
