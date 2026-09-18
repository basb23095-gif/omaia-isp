from flask import Flask, request, redirect, session, jsonify, Response, g
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

app=Flask(__name__)
app.secret_key=os.environ.get("SECRET_KEY","omia-sec-2026-v2")
app.config['PERMANENT_SESSION_LIFETIME']=datetime.timedelta(minutes=45)
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
            _pg_pool=pg_pool.ThreadedConnectionPool(2,20,dsn=DATABASE_URL,sslmode='require',connect_timeout=3,keepalives=1,keepalives_idle=30,keepalives_interval=10,keepalives_count=3)
        except: _pg_pool=None
init_pool()

def esc(s): return html.escape(str(s or ''), quote=True)

def get_conn():
    if USE_PG and _pg_pool:
        try: return _pg_pool.getconn()
        except: return psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=3)
    elif USE_PG:
        return psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=3)
    global _sqlite_conn
    with _sqlite_lock:
        if _sqlite_conn is None:
            _sqlite_conn=sqlite3.connect("omia.db",check_same_thread=False,timeout=10, isolation_level=None)
            _sqlite_conn.row_factory=sqlite3.Row
            try: _sqlite_conn.execute("PRAGMA journal_mode=WAL;")
            except: pass
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
            cur.close(); put_conn(conn); return rs
        else:
            with _sqlite_lock:
                return [dict(r) for r in conn.execute(q,a).fetchall()]
    except Exception as e:
        print(f"[qall] {e} | {q}")
        if conn and USE_PG:
            try: put_conn(conn)
            except: pass
        return []

def qone(q,a=()):
    r=qall(q,a); return r[0] if r else None

def qexec(q,a=()):
    conn=None
    try:
        conn=get_conn()
        if USE_PG:
            cur=conn.cursor(); cur.execute(q.replace("?","%s"),a); conn.commit(); cur.close(); put_conn(conn)
        else:
            with _sqlite_lock: conn.execute(q,a); conn.commit()
        return True
    except Exception as e:
        print(f"[qexec] {e} | {q}")
        if conn and USE_PG:
            try: conn.rollback(); put_conn(conn)
            except: pass
        return False

def add_log(phone,action,detail):
    try:
        now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)",(phone or 'unknown',action,detail,now))
        qexec("INSERT INTO notifications(title,msg,time) VALUES(?,?,?)",(action,str(phone)+": "+str(detail),now))
        with _cache_lock: _cache.pop('counts',None)
    except: pass

def get_counts():
    with _cache_lock:
        c=_cache.get('counts')
        if c and time.time()-c[1]<20: return c[0]
    try:
        ns=(qone("SELECT COUNT(*) c FROM subs") or {}).get('c',0)
        nd=(qone("SELECT COUNT(*) c FROM dish_ips") or {}).get('c',0)
        nt=(qone("SELECT COUNT(*) c FROM towers") or {}).get('c',0)
        nl=(qone("SELECT COUNT(*) c FROM ledger") or {}).get('c',0)
        data=(ns,nd,nt,nl)
        with _cache_lock: _cache['counts']=(data,time.time())
        return data
    except: return (0,0,0,0)

def init():
    ss=[
        "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,username TEXT)",
        "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,note TEXT)",
        "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,amount REAL,note TEXT,currency TEXT)",
        "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,dish_name TEXT,tower_id INTEGER)",
        "CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,area TEXT,lat REAL,lng REAL)",
        "CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,user_phone TEXT,action TEXT,detail TEXT,time TEXT)",
        "CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,msg TEXT,time TEXT,read INTEGER DEFAULT 0)"
    ]
    if USE_PG: ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
    for s in ss: qexec(s)
    # migrations
    for alter in ["ALTER TABLE dish_ips ADD COLUMN IF NOT EXISTS tower_id INTEGER","ALTER TABLE dish_ips ADD COLUMN tower_id INTEGER"]:
        try: qexec(alter)
        except: pass
    idxs=["CREATE INDEX IF NOT EXISTS idx_dish_ip ON dish_ips(ip)","CREATE INDEX IF NOT EXISTS idx_dish_tower ON dish_ips(tower_id)","CREATE INDEX IF NOT EXISTS idx_logs_time ON logs(id DESC)","CREATE INDEX IF NOT EXISTS idx_towers_name ON towers(name)"]
    for i in idxs:
        try: qexec(i)
        except: pass
    if USE_PG:
        try: qexec("CREATE UNIQUE INDEX IF NOT EXISTS uq_dish_ip ON dish_ips(ip)")
        except: pass
    if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",('05344851045',generate_password_hash('admin2024'),'manager','admin'))
    if not qone("SELECT * FROM towers WHERE name=?",('نقطة حماة الرئيسية',)):
        qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",('نقطة حماة الرئيسية','حماة',35.1318,36.7578))
init()

def login_required(f):
    @wraps(f)
    def w(*a,**kw):
        if not session.get('phone'): return redirect('/login')
        return f(*a,**kw)
    return w

def is_manager():
    return (session.get('role') or '')=='manager'

def role_required_manager(f):
    @wraps(f)
    def w(*a,**kw):
        if not is_manager(): return jsonify(ok=False,msg='ممنوع'),403
        return f(*a,**kw)
    return w

def is_valid_ip(ip):
    ip=(ip or '').strip()
    if not ip: return False
    try: ipaddress.ip_address(ip); return True
    except: return len(ip)>=7 and '.' in ip

@app.after_request
def add_perf_headers(resp):
    resp.headers['Cache-Control']='no-store' if request.path.startswith('/api/') else 'no-cache'
    return resp

@app.route('/ping')
@app.route('/health')
def public_ping(): return jsonify(ok=True,time=datetime.datetime.now().isoformat())

@app.route('/api/ping')
@login_required
def api_ping():
    ip=request.args.get('ip','').strip()
    if not ip: return jsonify(ok=False,out='لا يوجد IP')
    if not is_valid_ip(ip): return jsonify(ok=False,out='IP غير صالح')
    for port in [80,443,8080,8291,22,8728,8000]:
        s=None
        try:
            s=socket.socket(socket.AF_INET,socket.SOCK_STREAM); s.settimeout(0.7)
            if s.connect_ex((ip,port))==0: s.close(); return jsonify(ok=True,out=f'متصل {ip}:{port}',port=port)
            s.close()
        except:
            try: s.close()
            except: pass
    try:
        cmd=['ping','-c','1','-W','1',ip] if platform.system().lower()!='windows' else ['ping','-n','1','-w','1000',ip]
        out=subprocess.check_output(cmd,timeout=1.5,stderr=subprocess.STDOUT).decode(errors='ignore')
        ok='ttl=' in out.lower() or 'bytes from' in out.lower()
        if ok:
            m=re.search(r'time[=<]\s*(\d+\.?\d*)',out,re.I); ms=m.group(1) if m else ''
            return jsonify(ok=True,out=f'{ip} {ms}ms',ms=ms)
    except: pass
    return jsonify(ok=False,out=f'{ip} لا يرد')

@app.route('/api/ping_tcp')
@login_required
def api_ping_tcp():
    ip=request.args.get('ip','').strip(); port=int(request.args.get('port','80') or 80)
    if not is_valid_ip(ip): return jsonify(ok=False,out='IP غير صالح')
    s=socket.socket(socket.AF_INET,socket.SOCK_STREAM); s.settimeout(1)
    try: r=s.connect_ex((ip,port)); s.close(); return jsonify(ok=r==0,out=f'{ip}:{port} مفتوح' if r==0 else 'مغلق')
    except Exception as e: return jsonify(ok=False,out=str(e))

@app.route('/api/notifications')
@login_required
def api_noti():
    rows=qall("SELECT * FROM notifications ORDER BY id DESC LIMIT 30")
    cnt=(qone("SELECT COUNT(*) c FROM notifications WHERE read=0") or {}).get('c',0)
    return jsonify(rows=rows,unread=cnt)

@app.route('/api/notifications/read',methods=['POST'])
@login_required
def api_noti_read(): qexec("UPDATE notifications SET read=1"); return jsonify(ok=True)

@app.route('/api/network_status')
@login_required
def api_network():
    dishes=qall("SELECT * FROM dish_ips ORDER BY id DESC"); towers=qall("SELECT * FROM towers ORDER BY id DESC")
    return jsonify(dishes=len(dishes),towers=len(towers))

@app.route('/toggle_lang')
@login_required
def toggle_lang_route():
    cur=session.get('lang','ar'); session['lang']='en' if cur=='ar' else 'ar'
    return jsonify(ok=True,lang=session['lang'])

@app.route('/api/login_public',methods=['POST'])
def api_login_public():
    uin=request.form.get('userin','').strip(); pw=request.form.get('password','')
    u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
    if u and check_password_hash(u['password'],pw):
        session.clear(); session['phone']=u['phone']; session['username']=u.get('username') or u['phone']; session['role']=u.get('role') or 'tech'
        session.permanent=False
        threading.Thread(target=add_log,args=(u['phone'],'دخل النظام','login'),daemon=True).start()
        return jsonify(ok=True)
    return jsonify(ok=False,msg='خطأ بالدخول'),401

@app.route('/api/export/<tbl>')
@login_required
def api_export(tbl):
    output=io.StringIO(); output.write('\ufeff'); w=csv.writer(output)
    if tbl=='dishes':
        rows=qall("SELECT * FROM dish_ips ORDER BY id DESC"); w.writerow(['ID','اسم','IP','موقع','tower']);
        [w.writerow([r['id'],r.get('dish_name',''),r.get('ip',''),r.get('location',''),r.get('tower_id','')]) for r in rows]; fname='dishes.csv'
    elif tbl=='towers':
        rows=qall("SELECT * FROM towers ORDER BY id DESC"); w.writerow(['ID','اسم','منطقة','lat','lng']);
        [w.writerow([r['id'],r.get('name',''),r.get('area',''),r.get('lat',''),r.get('lng','')]) for r in rows]; fname='towers.csv'
    elif tbl=='logs':
        rows=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 2000"); w.writerow(['ID','يوزر','عمل','تفصيل','وقت']);
        [w.writerow([r['id'],r.get('user_phone',''),r.get('action',''),r.get('detail',''),r.get('time','')]) for r in rows]; fname='logs.csv'
    else:
        rows=qall(f"SELECT * FROM {tbl} ORDER BY id DESC LIMIT 1000") if tbl in ('subs','ledger') else []; w.writerow(['data']); fname=f'{tbl}.csv'
    return Response(output.getvalue(),mimetype='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename={fname}'})

@app.route('/api/clear_logs',methods=['POST'])
@login_required
@role_required_manager
def clear_logs(): qexec("DELETE FROM logs"); qexec("DELETE FROM notifications"); return jsonify(ok=True)

@app.route('/api/update_tower_pos',methods=['POST'])
@login_required
def update_tower_pos():
    try:
        tid=int(request.form.get('id') or request.json.get('id')); lat=float(request.form.get('lat') or request.json.get('lat')); lng=float(request.form.get('lng') or request.json.get('lng'))
        qexec("UPDATE towers SET lat=?,lng=? WHERE id=?",(lat,lng,tid)); return jsonify(ok=True)
    except Exception as e: return jsonify(ok=False,msg=str(e)),400

@app.route('/api/tower/<int:tid>/dishes')
@login_required
def tower_dishes(tid): return jsonify(qall("SELECT * FROM dish_ips WHERE tower_id=? ORDER BY id DESC",(tid,)))

@app.route('/api/add_dish_to_tower',methods=['POST'])
@login_required
def add_dish_to_tower():
    ip=request.form.get('ip','').strip() or (request.json or {}).get('ip','').strip()
    name=request.form.get('dish_name','').strip() or (request.json or {}).get('dish_name','')
    loc=request.form.get('location','').strip() or (request.json or {}).get('location','')
    tid=request.form.get('tower_id') or (request.json or {}).get('tower_id')
    if not ip or not is_valid_ip(ip): return jsonify(ok=False,msg='IP غير صالح'),400
    ok=qexec("INSERT INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?)",(ip,loc,name,int(tid) if tid else None))
    if ok: add_log(session.get('phone'),'إضافة صحن',f"{name} {ip} tower:{tid}");
    with _cache_lock: _cache.pop('counts',None)
    return jsonify(ok=ok)

@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login')
def login():
    return """<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<style>*{box-sizing:border-box;font-family:system-ui}body{margin:0;min-height:100vh;background:radial-gradient(120% 120% at 10% 10%,#1a2344 0%,#0a0e2a 60%,#070a1f 100%);display:flex;align-items:center;justify-content:center;color:#fff}
.card{background:linear-gradient(180deg,#222b45ee,#1a2035ee);border:1px solid #ffffff18;padding:28px;border-radius:22px;width:92%;max-width:380px;animation:fadeUp.7s cubic-bezier(.16,1,.3,1)}
@keyframes fadeUp{from{opacity:0;transform:translateY(20px) scale(.98)}to{opacity:1;transform:translateY(0) scale(1)}}
input{width:100%;padding:14px;margin:8px 0;background:#0f1424;border:1px solid #ffffff22;color:#fff;border-radius:14px}
.btn{width:100%;padding:14px;border:0;border-radius:14px;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:900;cursor:pointer;transition:transform.6s cubic-bezier(.16,1,.3,1)}.btn:active{transform:scale(.94)}
</style></head><body>
<div class=card><div style='font-weight:900;font-size:28px;text-align:center;margin-bottom:16px'>OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<form id=loginForm><input name=userin id=userin placeholder='يوزر' required><input name=password type=password placeholder='باسورد' required><button class=btn>دخول</button><div id=msg style='text-align:center;color:#ff6b6b;margin-top:10px;min-height:18px'></div></form></div>
<script>
document.getElementById('loginForm').addEventListener('submit',async e=>{
 e.preventDefault(); let btn=e.target.querySelector('.btn'); btn.textContent='...'; btn.disabled=true;
 try{ let r=await fetch('/api/login_public',{method:'POST',body:new FormData(e.target),cache:'no-store'}); let j=await r.json(); if(j.ok){location.replace('/dash?v=home');} else {document.getElementById('msg').textContent=j.msg; btn.textContent='دخول'; btn.disabled=false;}}catch(err){document.getElementById('msg').textContent='شبكة'; btn.textContent='دخول'; btn.disabled=false;}
});
</script></body></html>"""

@app.route('/logout')
def lo(): session.clear(); return redirect('/login')
@app.route('/api/logout',methods=['POST'])
def api_logout(): session.clear(); return jsonify(ok=True)

@app.route('/dash')
@login_required
def dash(): return layout('<div class=card>...</div>',request.args.get('v','home'))

@app.route('/api/page')
@login_required
def ap(): return page_content(request.args.get('v','home'))

@app.route('/api/search')
@login_required
def s():
    q=request.args.get('q','').strip()
    if not q: return jsonify([])
    like=f"%{q}%"; op="ILIKE" if USE_PG else "LIKE"
    results=[]
    try:
        for r in qall(f"SELECT * FROM dish_ips WHERE ip {op}? OR dish_name {op}? OR location {op}? ORDER BY id DESC LIMIT 20",(like,like,like)):
            results.append({"title":r.get('dish_name') or r.get('ip'),"sub":r.get('ip',''),"page":"dishes","type":"dish"})
        for r in qall(f"SELECT * FROM towers WHERE name {op}? OR area {op}? ORDER BY id DESC LIMIT 20",(like,like)):
            results.append({"title":r.get('name',''),"sub":r.get('area',''),"page":"towers","type":"tower"})
        for r in qall(f"SELECT * FROM subs WHERE name {op}? OR phone {op}? ORDER BY id DESC LIMIT 10",(like,like)):
            results.append({"title":r.get('name',''),"sub":r.get('phone',''),"page":"subs"})
    except: pass
    return jsonify(results[:30])

# CRUD fast JSON
@app.route('/add_dish',methods=['POST'])
@login_required
def ad():
    ip=(request.form.get('ip') or (request.json or {}).get('ip','')).strip()
    name=(request.form.get('dish_name') or (request.json or {}).get('dish_name','')).strip()
    loc=(request.form.get('location') or (request.json or {}).get('location','')).strip()
    tid=request.form.get('tower_id') or (request.json or {}).get('tower_id')
    if not is_valid_ip(ip): return jsonify(ok=False,msg='IP غير صالح'),400
    if USE_PG:
        ok=qexec("INSERT INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?) ON CONFLICT (ip) DO UPDATE SET dish_name=EXCLUDED.dish_name, location=EXCLUDED.location, tower_id=EXCLUDED.tower_id",(ip,loc,name,int(tid) if tid else None))
    else:
        ok=qexec("INSERT OR REPLACE INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?)",(ip,loc,name,int(tid) if tid else None))
    if ok:
        with _cache_lock: _cache.pop('counts',None)
    return jsonify(ok=ok)

@app.route('/edit_dish/<int:i>',methods=['POST'])
@login_required
def ed(i):
    if not is_manager(): return jsonify(ok=False),403
    d=request.form if request.form else request.json or {}
    ok=qexec("UPDATE dish_ips SET dish_name=?,ip=?,location=?,tower_id=? WHERE id=?",(d.get('dish_name',''),d.get('ip',''),d.get('location',''), d.get('tower_id') or None, i))
    return jsonify(ok=ok)

@app.route('/del_dish/<int:i>')
@login_required
def dd(i):
    if not is_manager(): return jsonify(ok=False),403
    ok=qexec("DELETE FROM dish_ips WHERE id=?",(i,))
    if ok:
        with _cache_lock: _cache.pop('counts',None)
    return jsonify(ok=ok)

@app.route('/add_tower',methods=['POST'])
@login_required
def at():
    d=request.form if request.form else request.json or {}
    try: la=float(d.get('lat') or 35.1312); ln=float(d.get('lng') or 36.7578)
    except: la=35.1312; ln=36.7578
    ok=qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",(d.get('name','كرت جديد'),d.get('area',''),la,ln))
    return jsonify(ok=ok)

@app.route('/del_tower/<int:i>')
@login_required
def dt(i):
    if not is_manager(): return jsonify(ok=False),403
    qexec("UPDATE dish_ips SET tower_id=NULL WHERE tower_id=?",(i,))
    ok=qexec("DELETE FROM towers WHERE id=?",(i,))
    return jsonify(ok=ok)

@app.route('/edit_tower/<int:i>',methods=['POST'])
@login_required
def et(i):
    if not is_manager(): return jsonify(ok=False),403
    d=request.form if request.form else request.json or {}
    try: la=float(d.get('lat') or 35.1318); ln=float(d.get('lng') or 36.7578)
    except: la=35.1318; ln=36.7578
    ok=qexec("UPDATE towers SET name=?,area=?,lat=?,lng=? WHERE id=?",(d.get('name',''),d.get('area',''),la,ln,i))
    return jsonify(ok=ok)

@app.route('/add_sub',methods=['POST'])
@login_required
def asub(): return jsonify(ok=qexec("INSERT INTO subs(name,phone,note) VALUES(?,?,?)",(request.form.get('name',''),request.form.get('phone',''),request.form.get('note',''))))
@app.route('/del_sub/<int:i>')
@login_required
def dsub(i): return jsonify(ok=qexec("DELETE FROM subs WHERE id=?",(i,))) if is_manager() else (jsonify(ok=False),403)
@app.route('/edit_sub/<int:i>',methods=['POST'])
@login_required
def esub(i): return jsonify(ok=qexec("UPDATE subs SET name=?,phone=?,note=? WHERE id=?",(request.form.get('name',''),request.form.get('phone',''),request.form.get('note',''),i))) if is_manager() else (jsonify(ok=False),403)
@app.route('/add_ledger',methods=['POST'])
@login_required
def al():
    try: amt=float(request.form.get('amount') or 0)
    except: amt=0
    return jsonify(ok=qexec("INSERT INTO ledger(name,amount,note,currency) VALUES(?,?,?,?)",(request.form.get('name',''),amt,request.form.get('note',''),request.form.get('currency','USD'))))
@app.route('/del_ledger/<int:i>')
@login_required
def dll(i): return jsonify(ok=qexec("DELETE FROM ledger WHERE id=?",(i,))) if is_manager() else (jsonify(ok=False),403)
@app.route('/edit_ledger/<int:i>',methods=['POST'])
@login_required
def el(i):
    try: amt=float(request.form.get('amount') or 0)
    except: amt=0
    return jsonify(ok=qexec("UPDATE ledger SET name=?,amount=?,note=?,currency=? WHERE id=?",(request.form.get('name',''),amt,request.form.get('note',''),request.form.get('currency','USD'),i))) if is_manager() else (jsonify(ok=False),403)
@app.route('/add_user',methods=['POST'])
@login_required
@role_required_manager
def au():
    ph=(request.form.get('phone') or request.form.get('user_field','')).strip()
    if not ph: return jsonify(ok=False,msg='مطلوب'),400
    if qone("SELECT * FROM users WHERE phone=?",(ph,)): return jsonify(ok=False,msg='موجود'),400
    ok=qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",(ph,generate_password_hash(request.form.get('password','1234')),request.form.get('role','tech'),ph))
    return jsonify(ok=ok)
@app.route('/edit_user',methods=['POST'])
@login_required
@role_required_manager
def eu():
    old=request.form.get('old_phone','').strip(); new_ph=(request.form.get('phone') or request.form.get('user_field','')).strip(); new_role=request.form.get('role','tech'); new_pass=request.form.get('password','').strip()
    if old!=new_ph and qone("SELECT * FROM users WHERE phone=?",(new_ph,)): return jsonify(ok=False,msg='موجود'),400
    if new_pass: ok=qexec("UPDATE users SET phone=?,username=?,role=?,password=? WHERE phone=?",(new_ph,new_ph,new_role,generate_password_hash(new_pass),old))
    else: ok=qexec("UPDATE users SET phone=?,username=?,role=? WHERE phone=?",(new_ph,new_ph,new_role,old))
    if session.get('phone')==old: session['phone']=new_ph; session['role']=new_role
    return jsonify(ok=ok)
@app.route('/del_user/<ph>')
@login_required
@role_required_manager
def du(ph):
    if ph=='05344851045': return jsonify(ok=False,msg='ممنوع'),400
    return jsonify(ok=qexec("DELETE FROM users WHERE phone=?",(ph,)))
@app.route('/change_pass',methods=['POST'])
@login_required
def cp():
    np=request.form.get('newpass','').strip()
    if not np: return jsonify(ok=False),400
    return jsonify(ok=qexec("UPDATE users SET password=? WHERE phone=?",(generate_password_hash(np),session.get('phone'))))

def page_content(v):
    req_lang=session.get('lang','ar')
    def L(ar,en): return ar if req_lang=='ar' else en
    if v=='home':
        ns,nd,nt,nl=get_counts()
        logs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 8")
        log_html="".join([f"<div class=rowlog><b>{esc(l.get('user_phone',''))}</b> <span class=badge>{esc(l.get('action',''))}</span> <small>{esc(l.get('detail','')[:60])}</small><small class=time>{esc(l.get('time',''))}</small></div>" for l in logs])
        return f'''<div class=grid2><div class=card stat onclick="loadPage('subs')"><h3>{L('المشتركين','Subs')}</h3><h2>{ns}</h2><div class=ico>👥</div></div>
        <div class=card stat onclick="loadPage('dishes')"><h3>{L('الصحون','Dishes')}</h3><h2>{nd}</h2><div class=ico>📡</div></div>
        <div class=card stat onclick="loadPage('towers')"><h3>{L('الأبراج','Towers')}</h3><h2>{nt}</h2><div class=ico>🗼</div></div>
        <div class=card stat onclick="loadPage('ledger')"><h3>{L('الحسابات','Accounts')}</h3><h2>{nl}</h2><div class=ico>📒</div></div></div>
        <div class=card><div class=rowlog style='font-weight:900'>{L('آخر النشاطات','Logs')} <button class=btn-gold onclick="loadPage('logs')">الكل</button></div>{log_html or '<div style="padding:12px;color:#888">-</div>'}</div>'''
    if v=='dishes':
        rs=qall("SELECT * FROM dish_ips ORDER BY id DESC")
        rows="".join([f'<div class="card dish-card" id="dish-{r["id"]}" data-ip="{esc(r.get("ip",""))}"><div><b>{esc(r.get("dish_name") or "صحن")}</b><br><span class=ip>{esc(r.get("ip",""))}</span><br><small>{esc(r.get("location",""))} {esc(r.get("tower_id") or "")}</small></div><div class=col><button class=btn-gold onclick="quickPingD({r["id"]})">Ping</button><div class=row><button class=btn-gold onclick="editDish({r["id"]})">✏️</button><button class=btn-del onclick="askDel(\'/del_dish/{r["id"]}\',{r["id"]})">🗑</button></div></div></div>' for r in rs])
        return f'''<div class=card><h3>الصحون - {len(rs)}</h3><form id=formDish class=row><input name=dish_name placeholder='اسم الصحن' required><input name=ip placeholder='IP' required><input name=location placeholder='موقع'><button class=btn-gold>إضافة</button></form><input id=searchBox placeholder='بحث...' oninput="filterDishes(this.value)" style='margin-top:10px'></div><div id=dl>{rows}</div>
        <script>
        window.filterDishes=q=>{{q=q.toLowerCase();document.querySelectorAll('.dish-card').forEach(c=>{{c.style.display=c.textContent.toLowerCase().includes(q)?'flex':'none'}})}};
        window.editDish=id=>{{let c=document.getElementById('dish-'+id); let ip=c.querySelector('.ip').textContent; let name=c.querySelector('b').textContent; let body=document.getElementById('editBody'); body.innerHTML='<input id=edn value="'+name+'"><input id=edi value="'+ip+'"><input id=edl placeholder="موقع"><button class=btn-gold onclick="saveDish('+id+')">حفظ</button>'; document.getElementById('editModal').classList.add('show');}};
        window.saveDish=id=>{{fetch('/edit_dish/'+id,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{dish_name:document.getElementById('edn').value,ip:document.getElementById('edi').value,location:document.getElementById('edl').value}})}}).then(r=>r.json()).then(j=>{{if(j.ok){{closeEditModal();loadPage('dishes',true)}}}})}};
        window.quickPingD=id=>{{let ip=document.getElementById('dish-'+id).dataset.ip; loadPage('ping'); setTimeout(()=>{{let el=document.getElementById('pingIp'); if(el){{el.value=ip; doSinglePing()}}}},350)}};
        document.getElementById('formDish').addEventListener('submit',e=>{{e.preventDefault(); fetch('/add_dish',{{method:'POST',body:new FormData(e.target)}}).then(r=>r.json()).then(j=>{{if(j.ok){{e.target.reset(); loadPage('dishes',true)}}}})}});
        </script>'''
    if v=='towers':
        towers=qall("SELECT * FROM towers ORDER BY id DESC")
        cards=""
        for t in towers:
            tid=t['id']; dishes=qall("SELECT * FROM dish_ips WHERE tower_id=? ORDER BY id DESC",(tid,))
            dish_html="".join([f"<div class=dish-mini><span>{esc(d.get('dish_name') or d.get('ip'))}</span><span class=ip>{esc(d.get('ip'))}</span><button onclick=\"delDishInTower({d['id']},{tid})\">✕</button></div>" for d in dishes]) or "<small style='color:#666'>لا يوجد صحون</small>"
            cards+=f'''<div class="card tower-card" id="tower-{tid}" data-name="{esc(t['name'])}" data-area="{esc(t.get('area') or '')}" data-lat="{t.get('lat')}" data-lng="{t.get('lng')}">
            <div class=tower-head><div><b class=tower-title>{esc(t['name'])}</b><br><small>{esc(t.get('area') or '')}</small><br><small class=coords>{t.get('lat')},{t.get('lng')}</small></div>
            <div class=col><button class=btn-gold onclick="openEditTower({tid})">تعديل</button><button class=btn-del onclick="askDel('/del_tower/{tid}',{tid})">حذف</button></div></div>
            <div class=tower-body><div class=row><input id="ip-{tid}" placeholder="IP"><input id="name-{tid}" placeholder="اسم الصحن"><button class=btn-gold onclick="addDishToTower({tid})">+ IP</button></div><div class=dish-list id="list-{tid}">{dish_html}</div></div></div>'''
        return f'''<div class=card><div class=row><h3>الأبراج - كروت لا نهائية</h3><button class=btn-gold onclick="openNewTower()">+ كرت جديد</button></div><form id=formTower style='display:none'><input name=name placeholder='اسم الكرت'><input name=area placeholder='منطقة'><input name=lat placeholder='lat'><input name=lng placeholder='lng'><button class=btn-gold>إضافة</button></form></div><div class=grid2>{cards}</div>
        <script>
        window.openNewTower=()=>{{let body=document.getElementById('editBody'); body.innerHTML='<input id=nt_name placeholder="اسم الكرت" value="كرت جديد"><input id=nt_area placeholder="منطقة"><input id=nt_lat placeholder="lat" value="35.1318"><input id=nt_lng placeholder="lng" value="36.7578"><button class=btn-gold onclick="saveNewTower()">حفظ</button>'; document.getElementById('editModal').classList.add('show');}};
        window.saveNewTower=()=>{{fetch('/add_tower',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{name:document.getElementById('nt_name').value,area:document.getElementById('nt_area').value,lat:document.getElementById('nt_lat').value,lng:document.getElementById('nt_lng').value}})}}).then(r=>r.json()).then(()=>{{closeEditModal(); loadPage('towers',true)}})}};
        window.openEditTower=id=>{{let c=document.getElementById('tower-'+id); let body=document.getElementById('editBody'); body.innerHTML='<input id=et_name value="'+c.dataset.name+'"><input id=et_area value="'+c.dataset.area+'"><input id=et_lat value="'+c.dataset.lat+'"><input id=et_lng value="'+c.dataset.lng+'"><button class=btn-gold onclick="saveTower('+id+')">حفظ</button>'; document.getElementById('editModal').classList.add('show');}};
        window.saveTower=id=>{{fetch('/edit_tower/'+id,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{name:document.getElementById('et_name').value,area:document.getElementById('et_area').value,lat:document.getElementById('et_lat').value,lng:document.getElementById('et_lng').value}})}}).then(()=>{{closeEditModal(); loadPage('towers',true)}})}};
        window.addDishToTower=tid=>{{let ip=document.getElementById('ip-'+tid).value.trim(); let nm=document.getElementById('name-'+tid).value.trim(); if(!ip) return alert('IP'); fetch('/api/add_dish_to_tower',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{ip:ip,dish_name:nm,tower_id:tid}})}}).then(r=>r.json()).then(j=>{{if(j.ok) loadPage('towers',true)}})}};
        window.delDishInTower=(did,tid)=>{{fetch('/del_dish/'+did).then(r=>r.json()).then(()=>loadPage('towers',true))}};
        document.getElementById('formTower').addEventListener('submit',e=>{{e.preventDefault(); fetch('/add_tower',{{method:'POST',body:new FormData(e.target)}}).then(()=>loadPage('towers',true))}});
        </script>'''
    if v=='map':
        towers=qall("SELECT * FROM towers")
        tj=json.dumps([{"id":t['id'],"name":t['name'],"area":t.get('area') or '',"lat":float(t.get('lat') or 35.1318),"lng":float(t.get('lng') or 36.7578)} for t in towers],ensure_ascii=False)
        return f'''<div class=card style='padding:10px'>
        <div class=row style='flex-wrap:wrap'><input id=mapSearch placeholder='بحث برج...' style='flex:1'><button class=btn-gold onclick="doMapSearch()">بحث</button><button class=btn-gold onclick="locateMe()" style='background:#22c55e;color:#fff'>موقعي</button><button class=btn-gold id=addPointBtn onclick="enableAddPoint()" style='background:#f59e0b'>نقطة</button><button class=btn-gold onclick="toggleMeasure()" id=measureBtn style='background:#0ea5e9'>قياس</button><button class=btn-del onclick="clearMap()">مسح</button><span id=distanceLabel class=ip>0 كم</span></div>
        <div id=map style='height:75vh;border-radius:16px;margin-top:8px'></div><small id=coordsLabel style='color:#ffbe4d'></small></div>
        <script>
        let _towers={tj}; let _map=null,measureMode=false,addPointMode=false,measurePoints=[],measureLine=null,measureMarkers=[],markersById={{}};
        window.doMapSearch=()=>{{let q=document.getElementById('mapSearch').value.toLowerCase(); let f=_towers.find(t=>t.name.toLowerCase().includes(q)); if(f&&_map) _map.flyTo([f.lat,f.lng],18);}};
        window.locateMe=()=>{{if(navigator.geolocation) navigator.geolocation.getCurrentPosition(p=>{{_map.flyTo([p.coords.latitude,p.coords.longitude],17); L.marker([p.coords.latitude,p.coords.longitude]).addTo(_map)}})}};
        window.enableAddPoint=()=>{{addPointMode=!addPointMode; document.getElementById('addPointBtn').textContent=addPointMode?'اضغط':'نقطة'; _map.getContainer().style.cursor=addPointMode?'crosshair':''}};
        window.toggleMeasure=()=>{{measureMode=!measureMode; document.getElementById('measureBtn').textContent=measureMode?'الغاء':'قياس';}};
        window.clearMap=()=>{{measurePoints=[]; if(measureLine) _map.removeLayer(measureLine); measureMarkers.forEach(m=>_map.removeLayer(m)); measureMarkers=[]; document.getElementById('distanceLabel').textContent='0 كم';}};
        setTimeout(()=>{{
          _map=L.map('map',{{zoomControl:true,maxZoom:22}}).setView([35.1318,36.7578],13);
          let osm=L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:22,maxNativeZoom:19}}).addTo(_map);
          let sat=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',{{maxZoom:22,maxNativeZoom:19}}).addTo(_map);
          let esriTopo=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{{z}}/{{y}}/{{x}}',{{maxZoom:22}});
          L.control.layers({{"عادية":osm,"قمر صناعي دقة عالية":sat,"تضاريس":esriTopo}}).addTo(_map);
          setTimeout(()=>_map.invalidateSize(),400);
          _towers.forEach(t=>{{let m=L.marker([t.lat,t.lng],{{draggable:true}}).addTo(_map).bindPopup(`<b>${{t.name}}</b><br>${{t.area}}`); markersById[t.id]=m; m.on('dragend',e=>{{let ll=e.target.getLatLng(); fetch('/api/update_tower_pos',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{id:t.id,lat:ll.lat,lng:ll.lng}})}})}})}});
          _map.on('click',e=>{{document.getElementById('coordsLabel').textContent=e.latlng.lat.toFixed(6)+','+e.latlng.lng.toFixed(6);
            if(measureMode){{measurePoints.push(e.latlng); let mk=L.marker(e.latlng).addTo(_map); measureMarkers.push(mk); if(measureLine) _map.removeLayer(measureLine); if(measurePoints.length>1){{measureLine=L.polyline(measurePoints,{{color:'#ffbe4d',weight:4}}).addTo(_map); let d=0; for(let i=1;i<measurePoints.length;i++) d+=measurePoints[i-1].distanceTo(measurePoints[i]); document.getElementById('distanceLabel').textContent=(d/1000).toFixed(3)+' كم';}} return;}}
            if(addPointMode){{L.popup().setLatLng(e.latlng).setContent(`<div><b>نقطة</b><br><input id=np_name placeholder="اسم الكرت"><input id=np_area placeholder="منطقة"><button class=btn-gold onclick="saveNewPoint(${{
e.latlng.lat}},${{e.latlng.lng}})">حفظ</button></div>`).openOn(_map);}}
          }});
          window.saveNewPoint=(lat,lng)=>{{let n=document.getElementById('np_name').value||'كرت'; let a=document.getElementById('np_area').value||''; fetch('/add_tower',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{name:n,area:a,lat:lat,lng:lng}})}}).then(()=>{{_map.closePopup(); location.reload();}})}};
        }},400);
        </script>'''
    if v=='ping':
        return f'''<div class=card><h3>📶 Ping</h3><div class=row><input id=pingIp placeholder='192.168.1.1' style='flex:1'><input id=pingPort value=80 style='width:80px'><button class=btn-gold onclick="doSinglePing()" style='background:#22c55e;color:#fff'>Ping</button><button class=btn-gold onclick="doTcpPing()" style='background:#0ea5e9;color:#fff'>TCP</button></div><div id=pingResult class=pingBox>جاهز</div><div class=row><button class=btn-gold onclick="pingAllDishes()" style='background:#ffbe4d;color:#111;flex:1'>فحص كل الصحون</button><button class=btn-gold onclick="clearPing()">مسح</button></div></div><div class=card id=quickDishes>...</div>
        <script>
        window.doSinglePing=async()=>{{let ip=document.getElementById('pingIp').value.trim(); if(!ip) return; let out=document.getElementById('pingResult'); out.textContent='...'+ip; try{{let r=await fetch('/api/ping?ip='+encodeURIComponent(ip)); let j=await r.json(); out.textContent=j.out}}catch(e){{out.textContent='خطأ'}}}};
        window.doTcpPing=async()=>{{let ip=document.getElementById('pingIp').value.trim(); let p=document.getElementById('pingPort').value||80; let out=document.getElementById('pingResult'); out.textContent='...'; try{{let r=await fetch('/api/ping_tcp?ip='+encodeURIComponent(ip)+'&port='+p); let j=await r.json(); out.textContent=j.out}}catch(e){{}}}};
        window.clearPing=()=>document.getElementById('pingResult').textContent='جاهز';
        window.pingAllDishes=async()=>{{let out=document.getElementById('pingResult'); out.textContent='...'; try{{let r=await fetch('/api/search?q=192'); let d=await r.json(); out.textContent=''; for(let dish of d.filter(x=>x.page=='dishes').slice(0,25)){{out.textContent+='\\n'+dish.sub; let pr=await fetch('/api/ping?ip='+encodeURIComponent(dish.sub)); let pj=await pr.json(); out.textContent+=' -> '+pj.out+'\\n'; await new Promise(rr=>setTimeout(rr,120));}}}}catch(e){{}}}};
        (async()=>{{try{{let r=await fetch('/api/search?q=192'); let d=await r.json(); let h=''; d.filter(x=>x.page=='dishes').slice(0,8).forEach(x=>{{h+='<div class=rowlog><span>'+x.sub+' - '+x.title+'</span><button class=btn-gold onclick="document.getElementById(\\'pingIp\\').value=\\''+x.sub+'\\'; doSinglePing()">Ping</button></div>'}}); document.getElementById('quickDishes').innerHTML=h||'-';}}catch(e){{}}}})();
        </script>'''
    if v=='subs':
        rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 200")
        rows="".join([f"<div class=card id=sub-{r['id']}><b>{esc(r['name'])}</b> {esc(r['phone'] or '')}<div class=row><button class=btn-gold onclick=\"openEditSub({r['id']})\">✏️</button><button class=btn-del onclick=\"askDel('/del_sub/{r['id']}',{r['id']})\">🗑</button></div></div>" for r in rs])
        return f"<div class=card><h3>المشتركين</h3><form id=formSub class=row><input name=name placeholder='اسم' required><input name=phone placeholder='رقم'><input name=note placeholder='ملاحظة'><button class=btn-gold>إضافة</button></form></div>{rows}<script>window.openEditSub=id=>{{let body=document.getElementById('editBody'); body.innerHTML='<input id=esn><input id=esp><input id=esno><button class=btn-gold onclick=saveSub('+id+')>حفظ</button>'; document.getElementById('editModal').classList.add('show');}}; window.saveSub=id=>{{fetch('/edit_sub/'+id,{{method:'POST',body:new URLSearchParams({{name:document.getElementById('esn').value,phone:document.getElementById('esp').value,note:document.getElementById('esno').value}})}}).then(()=>{{closeEditModal(); loadPage('subs',true)}})}}; document.getElementById('formSub').addEventListener('submit',e=>{{e.preventDefault(); fetch('/add_sub',{{method:'POST',body:new FormData(e.target)}}).then(()=>loadPage('subs',true))}});</script>"
    if v=='ledger':
        rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 200")
        rows="".join([f"<div class=card><b>{esc(r['name'])}</b> {r['amount']}<button class=btn-del onclick=\"askDel('/del_ledger/{r['id']}')\">🗑</button></div>" for r in rs])
        return f"<div class=card><h3>الحسابات</h3><form id=formLed class=row><input name=name required><input name=amount type=number step=0.01 required><input name=note><select name=currency><option>USD</option><option>SYP</option></select><button class=btn-gold>إضافة</button></form></div>{rows}<script>document.getElementById('formLed').addEventListener('submit',e=>{{e.preventDefault(); fetch('/add_ledger',{{method:'POST',body:new FormData(e.target)}}).then(()=>loadPage('ledger',true))}});</script>"
    if v=='logs':
        rs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 400")
        rows="".join([f"<div class=card rowlog style='border-right:4px solid #ffbe4d'><div><b>{esc(r.get('user_phone',''))}</b> <span class=badge>{esc(r.get('action',''))}</span> <small>{esc(r.get('detail',''))}</small></div><small>{esc(r.get('time',''))}</small></div>" for r in rs])
        return f"<div class=card row><h3>السجل {len(rs)}</h3><a href='/api/export/logs' class=btn-gold>Excel</a><button class=btn-del onclick=\"if(confirm('مسح؟'))fetch('/api/clear_logs',{{method:'POST'}}).then(()=>loadPage('logs',true))\">مسح</button></div>{rows or '<div class=card>-</div>'}"
    if v=='network':
        dishes=qall("SELECT * FROM dish_ips ORDER BY id DESC")
        rows="".join([f"<div class=card id=net-{d['id']} data-ip='{esc(d.get('ip',''))}'><b>{esc(d.get('dish_name') or 'صحن')}</b> {esc(d.get('ip',''))}<small class=net-out>...</small><button class=btn-gold onclick='checkOne({d['id']})'>فحص</button></div>" for d in dishes])
        return f"<div class=card row><h3>حالة الشبكة</h3><button class=btn-gold onclick='checkAll()' style='background:#22c55e;color:#fff'>فحص الكل</button></div>{rows}<script>window.checkOne=async id=>{{let c=document.getElementById('net-'+id); let out=c.querySelector('.net-out'); out.textContent='...'; let r=await fetch('/api/ping?ip='+c.dataset.ip); let j=await r.json(); out.textContent=j.out;}}; window.checkAll=async()=>{{for(let c of document.querySelectorAll('[id^=net-]')){{await checkOne(c.id.split('-')[1]); await new Promise(r=>setTimeout(r,120))}}}}; checkAll();</script>"
    if v=='settings':
        us=qall("SELECT * FROM users ORDER BY phone DESC")
        uh="".join([f"<div class=card id=user-{esc(u['phone'])} data-phone='{esc(u['phone'])}' data-role='{esc(u.get('role',''))}'><b>{esc(u.get('username') or u['phone'])}</b> {esc(u['phone'])} <span class=badge>{esc(u.get('role') or '')}</span><div class=row><button class=btn-gold onclick=\"openEditUser('{esc(u['phone'])}')\">✏️</button><button class=btn-del onclick=\"askDel('/del_user/{esc(u['phone'])}')\">🗑</button></div></div>" for u in us])
        return f"<div class=card><h3>كلمة السر</h3><form id=formPass class=row><input name=newpass type=password required><button class=btn-gold>حفظ</button></form></div><div class=card><h3>يوزر جديد</h3><form id=formUser class=row><input name=user_field placeholder='يوزر' required><input name=password type=password placeholder='باسورد' required><select name=role><option value=tech>فني</option><option value=manager>مدير</option></select><button class=btn-gold>إضافة</button></form></div>{uh}<script>window.openEditUser=ph=>{{let body=document.getElementById('editBody'); body.innerHTML='<input id=eu_ph value=\"'+ph+'\"><input id=eu_pass type=password placeholder=\"جديد\"><select id=eu_role><option value=tech>فني</option><option value=manager>مدير</option></select><button class=btn-gold onclick=\"saveUser(\\''+ph+'\\')\">حفظ</button>'; document.getElementById('editModal').classList.add('show');}}; window.saveUser=old=>{{fetch('/edit_user',{{method:'POST',body:new URLSearchParams({{old_phone:old,phone:document.getElementById('eu_ph').value,role:document.getElementById('eu_role').value,password:document.getElementById('eu_pass').value}})}}).then(()=>{{closeEditModal(); loadPage('settings',true)}})}}; document.getElementById('formPass').addEventListener('submit',e=>{{e.preventDefault(); fetch('/change_pass',{{method:'POST',body:new FormData(e.target)}}).then(()=>{{e.target.reset(); alert('تم')}})}}); document.getElementById('formUser').addEventListener('submit',e=>{{e.preventDefault(); fetch('/add_user',{{method:'POST',body:new FormData(e.target)}}).then(r=>r.json()).then(j=>{{if(j.ok) loadPage('settings',true); else alert(j.msg)}})}});</script>"
    return "<div class=card>-</div>"

def layout(c,v='home'):
    th=session.get('theme','dark'); is_dark=(th=='dark')
    bg='radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 60%, #070a1f 100%)' if is_dark else '#f1f5f9'
    card_bg='#1e2433f2' if is_dark else '#ffffff'; txt='#fff' if is_dark else '#0f172a'; border='#ffffff14' if is_dark else '#e2e8f0'
    cur_user=qone("SELECT * FROM users WHERE phone=?",(session.get('phone') or '',)) or {}
    role=cur_user.get('role') or 'tech'; lang=session.get('lang','ar'); dir_attr='rtl' if lang=='ar' else 'ltr'
    return f"""<html dir={dir_attr}><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<link rel=stylesheet href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'>
<style>
:root{{--ease:cubic-bezier(.16,1,.3,1); --ease-slow:cubic-bezier(.16,1,.3,1);}}
*{{box-sizing:border-box;font-family:system-ui}}body{{margin:0;background:{bg};color:{txt};overflow-x:hidden}}
.top{{position:fixed;top:0;left:0;right:0;height:62px;background:#0f172af0;backdrop-filter:blur(18px);display:flex;align-items:center;justify-content:space-between;padding:0 14px;z-index:1003;border-bottom:1px solid #ffffff12}}
.sidebar{{position:fixed;top:0;right:0;width:290px;height:100%;background:linear-gradient(180deg,#0f172a,#070e22);z-index:1002;padding-top:70px;transform:translateX(110%);transition:transform.7s var(--ease);overflow-y:auto}}
.sidebar.active{{transform:none}}.sidebar a{{display:flex;gap:12px;padding:13px 16px;margin:7px 12px;color:#cbd5e1;text-decoration:none;border-radius:14px;background:#ffffff08;transition:transform.6s var(--ease), background.4s, color.4s; will-change:transform}}.sidebar a:hover{{transform:translateX(-6px) scale(1.02); background:#ffffff12}}.sidebar a.active{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:900; transform:scale(1.03)}}.sidebar a:active{{transform:scale(.96); transition:transform.15s}}
#overlay{{position:fixed;inset:0;background:#0008;z-index:1001;display:none}} #overlay.show{{display:block}}
.main{{margin-top:74px;padding:14px;min-height:90vh}}
.card{{background:{card_bg};color:{txt};padding:14px;border-radius:16px;margin-bottom:12px;border:1px solid {border}; animation:fadeUp.6s var(--ease) both; transition:transform.6s var(--ease), box-shadow.6s var(--ease)}}
.card:hover{{transform:translateY(-2px) scale(1.005)}}
@keyframes fadeUp{{from{{opacity:0;transform:translateY(18px) scale(.98)}}to{{opacity:1;transform:translateY(0) scale(1)}}}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:12px}} @media(max-width:700px){{.grid2{{grid-template-columns:1fr}}}}
.stat{{cursor:pointer;position:relative;overflow:hidden}}.stat h2{{font-size:34px;margin:6px 0}}.ico{{position:absolute;left:14px;top:14px;font-size:32px;opacity:.9;transition:transform.7s var(--ease)}}.card:hover.ico{{transform:scale(1.2) rotate(6deg)}}
.row{{display:flex;gap:8px;align-items:center;flex-wrap:wrap}}.col{{display:flex;flex-direction:column;gap:6px}}
.btn-gold{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;padding:9px 14px;border:0;border-radius:11px;font-weight:800;cursor:pointer;transition:transform.6s var(--ease), filter.3s}}.btn-gold:hover{{filter:brightness(1.08)}}.btn-gold:active{{transform:scale(.9)}}
.btn-del{{background:#ef4444;color:#fff;padding:8px 12px;border:0;border-radius:11px;cursor:pointer;transition:transform.6s var(--ease)}}.btn-del:active{{transform:scale(.9)}}
.ip{{background:#000;color:#ffbe4d;padding:4px 8px;border-radius:8px;font-family:monospace;font-size:12px}}
.pingBox{{margin-top:10px;background:#000a;border:1px solid #ffffff12;border-radius:12px;padding:12px;font-family:monospace;min-height:60px;white-space:pre-wrap}}
.rowlog{{display:flex;justify-content:space-between;padding:9px 10px;border-bottom:1px dashed #ffffff10;gap:8px;animation:fadeUp.5s var(--ease)}}.badge{{background:#ffbe4d;color:#111;padding:2px 8px;border-radius:8px;font-size:11px;font-weight:800}}.time{{color:#64748b;font-size:11px}}
.tower-card{{border:1px solid #ffbe4d22}}.tower-head{{display:flex;justify-content:space-between}}.tower-title{{font-size:16px}}.coords{{color:#ffbe4d;font-size:11px}}.tower-body{{margin-top:10px;border-top:1px dashed #ffffff10;padding-top:10px}}.dish-list{{margin-top:8px;display:flex;flex-direction:column;gap:6px}}.dish-mini{{display:flex;justify-content:space-between;background:#ffffff06;padding:8px 10px;border-radius:10px;transition:transform.5s var(--ease)}}.dish-mini:hover{{transform:scale(1.01)}}
#delModal,#editModal{{position:fixed;inset:0;background:#000a;display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:.4s var(--ease);z-index:2000}} #delModal.show,#editModal.show{{opacity:1;pointer-events:auto}} #delBox,#editBox{{background:{card_bg};padding:22px;border-radius:18px;width:92%;max-width:440px;transform:scale(.9) translateY(20px);transition:transform.6s var(--ease)}} #delModal.show #delBox,#editModal.show #editBox{{transform:scale(1) translateY(0)}}
input,select{{padding:12px;border-radius:11px;border:1px solid {border};background:#ffffff07;color:{txt};transition:transform.4s var(--ease), border.3s}} input:focus{{transform:scale(1.01); border-color:#ffbe4d66; outline:none}}
</style></head><body>
<div id=overlay onclick="toggleSb(false)"></div>
<div class=sidebar id=sb><div style='padding:0 18px 10px;border-bottom:1px solid #ffffff0a'><b>OMAIA <span style='color:#ffbe4d'>ISP</span></b><br><small>{esc(cur_user.get('username') or '')} • {role}</small></div>
<a href="javascript:loadPage('home')" id=nav-home>🏠 الرئيسية</a><a href="javascript:loadPage('towers')" id=nav-towers>🗼 الأبراج - كروت</a><a href="javascript:loadPage('dishes')" id=nav-dishes>📡 الصحون</a><a href="javascript:loadPage('map')" id=nav-map>🗺 الخريطة عالية الدقة</a><a href="javascript:loadPage('ping')" id=nav-ping>📶 بنج</a><a href="javascript:loadPage('network')" id=nav-network>📊 الشبكة</a><a href="javascript:loadPage('subs')" id=nav-subs>👥 مشتركين</a><a href="javascript:loadPage('logs')" id=nav-logs>📜 السجل</a><a href="javascript:loadPage('settings')" id=nav-settings>⚙ إعدادات</a><a href="javascript:logoutFast()" style='background:#ef444418'>🚪 خروج</a></div>
<div class=top><div class=row><span onclick="toggleSb()" style='font-size:24px;cursor:pointer;padding:6px 10px;background:#ffffff0a;border-radius:10px;transition:transform.6s var(--ease)'>☰</span><input id=topsearch placeholder='بحث...' oninput="globalSearchTop(this.value)" style='width:44px;transition:all.4s var(--ease)' onfocus="this.style.width='170px'" onblur="setTimeout(()=>this.style.width='44px',200)"></div><b>OMAIA <span style='color:#ffbe4d'>ISP</span></b><button onclick="toggleLangFast()" style='background:#ffffff0a;color:#fff;border:1px solid #ffffff14;padding:8px 10px;border-radius:10px'>🌐</button></div>
<div id=searchResults style='position:fixed;top:66px;right:12px;max-width:380px;width:90%;background:#1e2433;border:1px solid #ffffff15;border-radius:12px;z-index:1500;display:none;max-height:60vh;overflow:auto'></div>
<div class=main id=mn>{c}</div>
<div id=delModal><div id=delBox><div style='text-align:center;font-size:30px'>🗑</div><h3 style='text-align:center'>تأكيد الحذف؟</h3><div class=row><button onclick="closeDel()" style='flex:1;padding:12px;border-radius:10px;background:transparent;color:{txt};border:1px solid {border}'>تراجع</button><button id=delYes style='flex:1;padding:12px;border-radius:10px;background:#ef4444;color:#fff;border:0;font-weight:800'>حذف</button></div></div></div>
<div id=editModal><div id=editBox><div class=row style='justify-content:space-between'><h3 style='margin:0'>تعديل</h3><button onclick="closeEditModal()" style='width:32px;height:32px;border-radius:50%;background:#ffffff12;border:0;color:{txt}'>✕</button></div><div id=editBody style='margin-top:10px'></div></div></div>
<script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>
<script>
let cur='{v}';
function toggleSb(f){{let sb=document.getElementById('sb'),ov=document.getElementById('overlay'); let o=f!==undefined?f:!sb.classList.contains('active'); sb.classList.toggle('active',o); ov.classList.toggle('show',o);}}
let pageCache={{}};
async function loadPage(v,force=false,push=true){{
 if(push && cur!==v){{try{{history.pushState({{page:v}},'', '/dash?v='+v)}}catch(e){{}}}}
 cur=v; toggleSb(false); document.querySelectorAll('.sidebar a').forEach(a=>a.classList.remove('active')); let n=document.getElementById('nav-'+v); if(n) n.classList.add('active');
 let mn=document.getElementById('mn');
 if(!force && pageCache[v]){{mn.innerHTML=pageCache[v]; execScripts(); return;}}
 mn.innerHTML='<div class=card>...</div>';
 try{{let r=await fetch('/api/page?v='+v,{{cache:'no-store'}}); let h=await r.text(); pageCache[v]=h; mn.innerHTML=h; execScripts();}}catch(e){{mn.innerHTML='<div class=card>خطأ '+e+'</div>';}}
}}
function execScripts(){{let mn=document.getElementById('mn'); mn.querySelectorAll('script').forEach(old=>{{let s=document.createElement('script'); s.textContent=old.textContent; document.body.appendChild(s); old.remove();}});}}
function askDel(url,id){{window._delUrl=url; window._delId=id; document.getElementById('delModal').classList.add('show');}}
function closeDel(){{document.getElementById('delModal').classList.remove('show');}}
window.closeEditModal=()=>document.getElementById('editModal').classList.remove('show');
document.getElementById('delYes').onclick=async()=>{{if(!window._delUrl) return; let btn=document.getElementById('delYes'); btn.textContent='...'; btn.disabled=true; try{{let r=await fetch(window._delUrl); let j=await r.json(); if(j.ok){{let el=document.getElementById('dish-'+window._delId) || document.getElementById('tower-'+window._delId); if(el){{el.style.transform='scale(.9)'; el.style.opacity='0'; setTimeout(()=>el.remove(),300)}} closeDel(); delete pageCache[cur];}} else alert('ممنوع');}}catch(e){{}} btn.textContent='حذف'; btn.disabled=false;}};
window.toggleLangFast=async()=>{{let r=await fetch('/toggle_lang'); let j=await r.json(); localStorage.setItem('lang',j.lang); loadPage(cur,true,false);}};
window.globalSearchTop=async q=>{{let box=document.getElementById('searchResults'); if(!q||q.length<2){{box.style.display='none'; return;}} let r=await fetch('/api/search?q='+encodeURIComponent(q)); let d=await r.json(); if(!d.length){{box.style.display='none'; return;}} let h=''; d.forEach(x=>{{h+='<div onclick="loadPage(\\''+x.page+'\\');document.getElementById(\\'searchResults\\').style.display=\\'none\\'" style="padding:10px;cursor:pointer;border-bottom:1px solid #ffffff08"><b>'+x.title+'</b><br><small>'+x.sub+'</small></div>';}}); box.innerHTML=h; box.style.display='block';}};
window.logoutFast=async()=>{{await fetch('/api/logout',{{method:'POST'}}); sessionStorage.clear(); localStorage.removeItem('omaia_user'); localStorage.removeItem('omaia_pass'); location.replace('/login');}};
window.addEventListener('popstate',e=>{{let v='home'; if(e.state&&e.state.page) v=e.state.page; else {{let p=new URLSearchParams(location.search); v=p.get('v')||'home';}} loadPage(v,false,false);}});
loadPage(cur,true,false);
</script></body></html>"""

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)),debug=False)
