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

app=Flask(__name__)
app.secret_key=os.environ.get("SECRET_KEY","omia-sec-2026-CHANGE-ME-ULTRA")
app.config['PERMANENT_SESSION_LIFETIME']=datetime.timedelta(days=30)
app.config['SESSION_PERMANENT']=True
app.config['SESSION_COOKIE_HTTPONLY']=True
app.config['SESSION_COOKIE_SAMESITE']='Lax'

DATABASE_URL=os.environ.get("DATABASE_URL","").strip().replace("postgresql://","postgres://")
USE_PG=bool(DATABASE_URL.startswith("postgres://") and psycopg2)

# ===== FIX 1: Pool 25 بدل اتصال واحد بطيء - حل تسجيل دخول بطيء والإضافة بطيئة =====
_pg_pool=None
_pg_pool_lock=threading.Lock()
_sqlite_conn=None
_sqlite_lock=threading.Lock()
_cache={}
_cache_lock=threading.Lock()
_user_cache={}
_user_cache_lock=threading.Lock()

def init_pg_pool():
    global _pg_pool
    if not USE_PG or not pg_pool: return
    with _pg_pool_lock:
        if _pg_pool: return
        try:
            _pg_pool=pg_pool.ThreadedConnectionPool(1,25,dsn=DATABASE_URL,sslmode='require',connect_timeout=2,keepalives=1,keepalives_idle=30,keepalives_interval=10,keepalives_count=3)
            print("[POOL] 25 ULTRA FAST")
        except Exception as e:
            print(f"[POOL ERROR] {e}"); _pg_pool=None
init_pg_pool()

def esc(s): return html.escape(str(s or ''), quote=True)

def get_conn():
    if USE_PG and _pg_pool:
        try: return _pg_pool.getconn()
        except: return psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=2)
    elif USE_PG:
        try: return psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=2)
        except: pass
    global _sqlite_conn
    with _sqlite_lock:
        if _sqlite_conn is None:
            try:
                _sqlite_conn=sqlite3.connect("omia.db",check_same_thread=False,timeout=10)
                _sqlite_conn.row_factory=sqlite3.Row
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
            rs=[dict(r) for r in cur.fetchall()]; cur.close(); put_conn(conn); return rs
        else:
            with _sqlite_lock: rs=[dict(r) for r in conn.execute(q,a).fetchall()]; return rs
    except Exception as e:
        print(f"[qall] {e}")
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
        print(f"[qexec] {e}")
        if conn and USE_PG:
            try: conn.rollback(); put_conn(conn)
            except: pass
        return False

# ===== FIX 2: السجل يبين كل التعديلات =====
def add_log(user_phone,action,detail):
    try:
        now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)",(user_phone or 'unknown',action,detail,now))
        qexec("INSERT INTO notifications(title,msg,time) VALUES(?,?,?)",(action,str(user_phone)+": "+str(detail),now))
        with _cache_lock: _cache.pop('counts',None)
    except: pass

def get_dish_table():
    with _cache_lock:
        c=_cache.get('dish_table')
        if c and time.time()-c[1]<300: return c[0]
    # هذا الكود الأصلي يستخدم dish_ips فقط
    return "dish_ips"

def get_counts_cached():
    with _cache_lock:
        c=_cache.get('counts')
        if c and time.time()-c[1]<30: return c[0]
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
    ss=["CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,username TEXT)","CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,note TEXT)","CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,amount REAL,note TEXT,currency TEXT)","CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,dish_name TEXT)","CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,area TEXT,lat REAL,lng REAL)","CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,user_phone TEXT,action TEXT,detail TEXT,time TEXT)","CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,msg TEXT,time TEXT,read INTEGER DEFAULT 0)"]
    if USE_PG:
        ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
    for s in ss: qexec(s)
    if USE_PG:
        for idx in ["CREATE INDEX IF NOT EXISTS idx_dish_ips_ip ON dish_ips(ip)", "CREATE UNIQUE INDEX IF NOT EXISTS uq_dish_ips_ip ON dish_ips(ip)", "CREATE INDEX IF NOT EXISTS idx_logs_id ON logs(id DESC)"]:
            try: qexec(idx)
            except: pass
    if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)): qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",('05344851045',generate_password_hash('admin2024'),'manager','admin'))
    if not qone("SELECT * FROM towers WHERE name=?",('نقطة حماة الرئيسية',)): qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",('نقطة حماة الرئيسية','حماة',35.1318,36.7578))
    c=qone("SELECT COUNT(*) c FROM logs")
    if c and c.get('c',0)==0:
        add_log('system','تشغيل النظام','السجل شغال الآن ✅ - يبين كل التعديلات فوري')
init()

def login_required(f):
    @wraps(f)
    def w(*a,**kw):
        if not session.get('phone'):return redirect('/login')
        return f(*a,**kw)
    return w

# ===== FIX: is_manager سريع من session بدون DB =====
def is_manager():
    if session.get('role'): return session.get('role')=='manager'
    u=qone("SELECT role FROM users WHERE phone=?",(session.get('phone') or '',))
    if not u: return False
    session['role']=u.get('role')
    return (u.get('role') or '').lower()=='manager'

def role_required_manager(f):
    @wraps(f)
    def w(*a,**kw):
        if not is_manager():return "ممنوع",403
        return f(*a,**kw)
    return w

def is_valid_ip(ip):
    ip=(ip or '').strip()
    if not ip:return False
    try: ipaddress.ip_address(ip); return True
    except: return len(ip)>=7 and '.' in ip

@app.after_request
def add_perf_headers(resp):
    if request.path.startswith('/api/'): resp.headers['Cache-Control']='no-store, max-age=0'
    else: resp.headers['Cache-Control']='no-cache'
    return resp

@app.route('/ping')
@app.route('/health')
def public_ping(): return jsonify(ok=True,time=datetime.datetime.now().isoformat(),pool=bool(_pg_pool),fast=True)

@app.route('/api/ping')
@login_required
def api_ping():
    ip=request.args.get('ip','').strip()
    if not ip:return jsonify(ok=False,out='لا يوجد IP')
    if not is_valid_ip(ip):return jsonify(ok=False,out='IP غير صالح')
    for port in [80,443,8080,8291,22,23,53,8000,8728]:
        s=None
        try:
            s=socket.socket(socket.AF_INET,socket.SOCK_STREAM);s.settimeout(0.9)
            if s.connect_ex((ip,port))==0:s.close();return jsonify(ok=True,out=f'✅ متصل - {ip}:{port} مفتوح',port=port,method='tcp')
            s.close()
        except:
            try:
                if s: s.close()
            except: pass
            continue
    try:
        cmd=['ping','-c','1','-W','2',ip] if platform.system().lower()!='windows' else ['ping','-n','1','-w','2000',ip]
        out=subprocess.check_output(cmd,timeout=2,stderr=subprocess.STDOUT).decode(errors='ignore')
        ok='ttl=' in out.lower() or 'bytes from' in out.lower() or '1 received' in out.lower()
        if ok:
            m=re.search(r'time[=<]\s*(\d+\.?\d*)',out,re.I); ms=m.group(1) if m else ''
            return jsonify(ok=True,out=f'✅ متصل {ip} - {ms}ms',ms=ms,method='icmp')
    except: pass
    return jsonify(ok=False,out=f'❌ {ip} لا يرد')

@app.route('/api/ping_tcp')
@login_required
def api_ping_tcp():
    ip=request.args.get('ip','').strip()
    port_str=request.args.get('port','80').strip()
    try: port=int(port_str)
    except: return jsonify(ok=False,out='Port غير صالح')
    if not is_valid_ip(ip):return jsonify(ok=False,out='IP غير صالح')
    s=None
    try:
        s=socket.socket(socket.AF_INET,socket.SOCK_STREAM);s.settimeout(1.2);r=s.connect_ex((ip,port));s.close()
        return jsonify(ok=r==0,out=f'✅ {ip}:{port} مفتوح' if r==0 else f'❌ {ip}:{port} مغلق')
    except Exception as e:
        try:
            if s: s.close()
        except: pass
        return jsonify(ok=False,out=f'❌ {e}')

@app.route('/api/notifications')
@login_required
def api_noti():
    rows=qall("SELECT * FROM notifications ORDER BY id DESC LIMIT 30")
    unread=qone("SELECT COUNT(*) c FROM notifications WHERE read=0")
    cnt=unread.get('c',0) if unread else 0
    return jsonify(rows=rows,unread=cnt)

@app.route('/api/notifications/read',methods=['POST'])
@login_required
def api_noti_read(): qexec("UPDATE notifications SET read=1");return jsonify(ok=True)

@app.route('/api/network_status')
@login_required
def api_network():
    dishes=qall("SELECT * FROM dish_ips ORDER BY id DESC");towers=qall("SELECT * FROM towers ORDER BY id DESC");subs_cnt=(qone("SELECT COUNT(*) c FROM subs") or {}).get('c',0);return jsonify(dishes=len(dishes),towers=len(towers),subs=subs_cnt)

@app.route('/toggle_lang')
@login_required
def toggle_lang_route():
    cur=session.get('lang','ar');new='en' if cur=='ar' else 'ar';session['lang']=new;return jsonify(ok=True,lang=new)

# ===== FIX 3: تسجيل دخول فوري - كاش + تسخين سيرفر =====
@app.route('/api/login_public',methods=['POST'])
def api_login_public():
    uin=request.form.get('userin','').strip();pw=request.form.get('password','')
    with _user_cache_lock:
        cached=_user_cache.get(uin)
        if cached and time.time()-cached[1]<60:
            u=cached[0]
        else:
            u=None
    if not u:
        u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
        if u:
            with _user_cache_lock: _user_cache[uin]=(u,time.time())
    if u and check_password_hash(u['password'],pw):
        session['phone']=u['phone'];session['username']=u.get('username') or u['phone'];session['role']=u.get('role') or 'tech';session.permanent=True
        try: threading.Thread(target=add_log, args=(u['phone'],'دخل النظام','تسجيل دخول ✅'), daemon=True).start()
        except: pass
        return jsonify(ok=True,role=u.get('role'))
    return jsonify(ok=False,msg='خطأ بالدخول'),401

@app.route('/api/export/<tbl>')
@login_required
def api_export(tbl):
    output=io.StringIO(); output.write('\ufeff'); w=csv.writer(output)
    if tbl=='dishes':
        rows=qall("SELECT * FROM dish_ips ORDER BY id DESC");w.writerow(['ID','اسم الصحن','IP','الموقع'])
        for r in rows:w.writerow([r['id'],r.get('dish_name',''),r.get('ip',''),r.get('location','')]);fname='dishes.csv'
    elif tbl=='subs':
        rows=qall("SELECT * FROM subs ORDER BY id DESC");w.writerow(['ID','الاسم','رقم','ملاحظة'])
        for r in rows:w.writerow([r['id'],r.get('name',''),r.get('phone',''),r.get('note','')]);fname='subs.csv'
    elif tbl=='users':
        rows=qall("SELECT phone,username,role FROM users ORDER BY phone DESC");w.writerow(['يوزر/رقم','اسم المستخدم','الرتبة'])
        for r in rows:w.writerow([r.get('phone',''),r.get('username',''),r.get('role','')]);fname='users.csv'
    elif tbl=='towers':
        rows=qall("SELECT * FROM towers ORDER BY id DESC");w.writerow(['ID','اسم البرج','المنطقة','lat','lng'])
        for r in rows:w.writerow([r['id'],r.get('name',''),r.get('area',''),r.get('lat',''),r.get('lng','')]);fname='towers.csv'
    elif tbl=='logs':
        rows=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 1000");w.writerow(['ID','المستخدم','العملية','التفاصيل','الوقت'])
        for r in rows:w.writerow([r['id'],r.get('user_phone',''),r.get('action',''),r.get('detail',''),r.get('time','')]);fname='logs.csv'
    else:w.writerow(['ID']);fname='export.csv'
    return Response(output.getvalue(),mimetype='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename={fname}'})

@app.route('/api/clear_logs',methods=['POST'])
@login_required
@role_required_manager
def clear_logs(): qexec("DELETE FROM logs"); return jsonify(ok=True)

@app.route('/api/seed_log',methods=['POST'])
@login_required
def seed_log():
    now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)",(session.get('phone','test'),'إضافة صحن','192.168.1.10 - صحن تجريبي',now))
    qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)",(session.get('phone','test'),'تعديل صحن','تعديل موقع الصحن',now))
    qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)",(session.get('phone','test'),'حذف صحن','حذف 192.168.1.11',now))
    return jsonify(ok=True)

@app.route('/')
def ix():return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login')
def login():
    return """<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<style>*{box-sizing:border-box;font-family:system-ui}body{margin:0;min-height:100vh;background:radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 55%, #070a1f 100%);display:flex;flex-direction:column;align-items:center;justify-content:center;color:#fff}
.card{background:linear-gradient(180deg, #222b45cc, #1a2035cc);backdrop-filter:blur(16px);border:1px solid #ffffff18;padding:26px;border-radius:22px;width:92%;max-width:380px;box-shadow:0 20px 60px #0008}
input{width:100%;padding:14px;margin:9px 0;background:#0f1424;border:1px solid #ffffff22;color:#fff;border-radius:14px;font-size:15px}
.btn{width:100%;padding:14px;border:0;border-radius:14px;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:900;font-size:17px;cursor:pointer;margin-top:12px}
.spinner{display:inline-block;width:16px;height:16px;border:2px solid #1115;border-top-color:#111;border-radius:50%;animation:spin .6s linear infinite;vertical-align:middle;margin-left:6px}
@keyframes spin{to{transform:rotate(360deg)}}</style></head><body>
<div style='font-size:30px;font-weight:900;margin-bottom:14px'>OMAIA <span style='color:#ffbe4d'>ISP</span> <small style='color:#22c55e'>⚡ ULTRA</small></div>
<div class=card><form id=loginForm><input name=userin id=userin placeholder='📱 رقم / يوزر' required autocomplete=username><input name=password id=password type=password placeholder='🔑 كلمة السر' required autocomplete=current-password><label style='display:flex;gap:8px;font-size:13px;color:#aaa;margin:8px 0'><input type=checkbox id=savePass style='width:auto'> حفظ</label><button class=btn id=loginBtn>✨ دخول فوري</button><div id=msg style='text-align:center;margin-top:10px;color:#ff6b6b;font-size:13px;min-height:18px'></div></form></div>
<script>
fetch('/ping',{cache:'no-store'}).catch(()=>{});
let u=document.getElementById('userin'), p=document.getElementById('password'), s=document.getElementById('savePass');
let su=localStorage.getItem('omaia_user'), sp=localStorage.getItem('omaia_pass');
if(su){u.value=su; if(sp){p.value=sp; s.checked=true;}}
document.getElementById('loginForm').addEventListener('submit',async e=>{
 e.preventDefault(); let btn=document.getElementById('loginBtn'), msg=document.getElementById('msg');
 if(btn.disabled) return;
 let orig=btn.innerHTML; btn.innerHTML='<span class=spinner></span> جاري...'; btn.disabled=true; msg.textContent='';
 try{
  let fd=new FormData(e.target);
  let r=await fetch('/api/login_public',{method:'POST',body:fd,cache:'no-store'});
  let j=await r.json();
  if(j.ok){
    if(s.checked){localStorage.setItem('omaia_user',u.value);localStorage.setItem('omaia_pass',p.value);}
    msg.style.color='#22c55e'; msg.textContent='✅ تم';
    location.replace('/dash?v=home');
  } else { msg.style.color='#ff6b6b'; msg.textContent=j.msg||'خطأ'; btn.innerHTML=orig; btn.disabled=false; }
 }catch(err){ msg.textContent='خطأ شبكة'; btn.innerHTML=orig; btn.disabled=false; }
});
</script></body></html>"""

@app.route('/logout')
def lo():session.clear();return redirect('/login')
@app.route('/api/logout',methods=['POST'])
def api_logout():session.clear();return jsonify(ok=True)

# ===== FIX: dash سريع بدون DB - حل يحمل موقع من جديد =====
@app.route('/dash')
@login_required
def dash():
    v=request.args.get('v','home')
    return layout('<div class=card><div style="height:22px;width:40%;background:linear-gradient(90deg,#1a2035 25%,#222b45 50%,#1a2035 75%);background-size:200% 100%;animation:shimmer 1s infinite;border-radius:8px;margin-bottom:10px"></div><div style="height:14px;background:linear-gradient(90deg,#1a2035 25%,#222b45 50%,#1a2035 75%);background-size:200% 100%;animation:shimmer 1s infinite;border-radius:6px"></div></div>',v,fast=True)

@app.route('/api/page')
@login_required
def ap():return page_content(request.args.get('v','home'))

@app.route('/api/search')
@login_required
def s():
    q=request.args.get('q','').strip()
    if not q:return jsonify([])
    like="%"+q+"%";results=[]
    try:
        for r in qall("SELECT * FROM dish_ips WHERE ip LIKE ? OR dish_name LIKE ? OR location LIKE ? ORDER BY id DESC LIMIT 20",(like,like,like)):results.append({"title":r.get('dish_name') or r.get('ip') or 'صحن',"sub":r.get('ip',''),"page":"dishes","type":"dish"})
        for r in qall("SELECT * FROM subs WHERE name LIKE ? OR phone LIKE ? ORDER BY id DESC LIMIT 15",(like,like)):results.append({"title":r.get('name',''),"sub":r.get('phone',''),"page":"subs","type":"sub"})
        for r in qall("SELECT * FROM towers WHERE name LIKE ? OR area LIKE ? ORDER BY id DESC LIMIT 15",(like,like)):results.append({"title":r.get('name',''),"sub":r.get('area',''),"page":"towers","type":"tower"})
        for r in qall("SELECT * FROM users WHERE phone LIKE ? OR username LIKE ? LIMIT 10",(like,like)):results.append({"title":r.get('username') or r.get('phone',''),"sub":r.get('phone',''),"page":"settings","type":"user"})
        for r in qall("SELECT * FROM ledger WHERE name LIKE ? OR note LIKE ? ORDER BY id DESC LIMIT 10",(like,like)):results.append({"title":r.get('name',''),"sub":str(r.get('amount','')),"page":"ledger","type":"ledger"})
    except:pass
    return jsonify(results[:25])

@app.route('/toggle_theme')
@login_required
def tt():cur=session.get('theme','dark');session['theme']='light' if cur=='dark' else 'dark';return jsonify(ok=True)

# ===== FIX: إضافة وحذف فوري بدون SELECT بطيء =====
@app.route('/add_dish',methods=['POST'])
@login_required
def ad():
    ip=request.form.get('ip','').strip();name=request.form.get('dish_name','').strip();loc=request.form.get('location','').strip()
    if not ip:return "IP مطلوب",400
    if not is_valid_ip(ip):return "IP غير صالح",400
    phone=session.get('phone','')
    if USE_PG:
        ok=qexec("INSERT INTO dish_ips(ip,location,dish_name) VALUES(?,?,?) ON CONFLICT (ip) DO UPDATE SET dish_name=EXCLUDED.dish_name, location=EXCLUDED.location",(ip,loc,name))
    else:
        ok=qexec("INSERT OR REPLACE INTO dish_ips(ip,location,dish_name) VALUES(?,?,?)",(ip,loc,name))
    if ok:
        add_log(phone,'إضافة/تعديل صحن',name+" "+ip+" "+loc)
        with _cache_lock: _cache.pop('counts',None)
    return "ok" if ok else "خطأ",200 if ok else 400

@app.route('/edit_dish/<int:i>',methods=['POST'])
@login_required
def ed(i):
    if not is_manager():return "ممنوع للفني",403
    name=request.form.get('dish_name','').strip(); ip=request.form.get('ip','').strip(); loc=request.form.get('location','').strip()
    ok=qexec("UPDATE dish_ips SET dish_name=?,ip=?,location=? WHERE id=?",(name,ip,loc,i))
    if ok: add_log(session.get('phone'),'تعديل صحن',f"ID {i} -> {ip} {name}")
    return "ok" if ok else "خطأ",200 if ok else 400

@app.route('/del_dish/<int:i>')
@login_required
def dd(i):
    if not is_manager():return "ممنوع للفني",403
    info=qone("SELECT ip,dish_name FROM dish_ips WHERE id=?",(i,))
    ok=qexec("DELETE FROM dish_ips WHERE id=?",(i,))
    if ok:
        with _cache_lock: _cache.pop('counts',None)
        add_log(session.get('phone'),'حذف صحن',f"{info.get('dish_name','')} {info.get('ip','')}" if info else f"ID {i}")
    return "ok" if ok else "خطأ",200 if ok else 400

@app.route('/add_tower',methods=['POST'])
@login_required
def at():
    lat=request.form.get('lat','').strip();lng=request.form.get('lng','').strip()
    try:la=float(lat) if lat else 35.1312;ln=float(lng) if lng else 36.7578
    except:la=35.1312;ln=36.7578
    ok=qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",(request.form.get('name',''),request.form.get('area',''),la,ln))
    if ok: add_log(session.get('phone'),'إضافة برج',request.form.get('name',''))
    return "ok" if ok else "خطأ",200 if ok else 400

@app.route('/del_tower/<int:i>')
@login_required
def dt(i):
    if not is_manager():return "ممنوع للفني",403
    ok=qexec("DELETE FROM towers WHERE id=?",(i,))
    if ok: add_log(session.get('phone'),'حذف برج',f"ID {i}")
    return "ok" if ok else "خطأ",200 if ok else 400

@app.route('/edit_tower/<int:i>',methods=['POST'])
@login_required
def et(i):
    if not is_manager():return "ممنوع للفني",403
    lat=request.form.get('lat','').strip();lng=request.form.get('lng','').strip()
    try:la=float(lat) if lat else 35.1318;ln=float(lng) if lng else 36.7578
    except:la=35.1318;ln=36.7578
    ok=qexec("UPDATE towers SET name=?,area=?,lat=?,lng=? WHERE id=?",(request.form.get('name',''),request.form.get('area',''),la,ln,i))
    if ok: add_log(session.get('phone'),'تعديل برج',f"ID {i}")
    return "ok" if ok else "خطأ",200 if ok else 400

@app.route('/add_sub',methods=['POST'])
@login_required
def asub():
    ok=qexec("INSERT INTO subs(name,phone,note) VALUES(?,?,?)",(request.form.get('name',''),request.form.get('phone',''),request.form.get('note','')))
    if ok: add_log(session.get('phone'),'إضافة مشترك',request.form.get('name',''))
    return "ok" if ok else "خطأ",200 if ok else 400

@app.route('/del_sub/<int:i>')
@login_required
def dsub(i):
    if not is_manager():return "ممنوع للفني",403
    ok=qexec("DELETE FROM subs WHERE id=?",(i,))
    if ok: add_log(session.get('phone'),'حذف مشترك',f"ID {i}")
    return "ok" if ok else "خطأ",200 if ok else 400

@app.route('/edit_sub/<int:i>',methods=['POST'])
@login_required
def esub(i):
    if not is_manager():return "ممنوع للفني",403
    ok=qexec("UPDATE subs SET name=?,phone=?,note=? WHERE id=?",(request.form.get('name',''),request.form.get('phone',''),request.form.get('note',''),i))
    if ok: add_log(session.get('phone'),'تعديل مشترك',f"ID {i}")
    return "ok" if ok else "خطأ",200 if ok else 400

@app.route('/add_ledger',methods=['POST'])
@login_required
def al():
    try:amt=float(request.form.get('amount') or 0)
    except:amt=0
    ok=qexec("INSERT INTO ledger(name,amount,note,currency) VALUES(?,?,?,?)",(request.form.get('name',''),amt,request.form.get('note',''),request.form.get('currency','USD')))
    if ok: add_log(session.get('phone'),'إضافة حساب',f"{request.form.get('name','')} {amt}")
    return "ok" if ok else "خطأ",200 if ok else 400

@app.route('/del_ledger/<int:i>')
@login_required
def dll(i):
    if not is_manager():return "ممنوع للفني",403
    ok=qexec("DELETE FROM ledger WHERE id=?",(i,))
    if ok: add_log(session.get('phone'),'حذف حساب',f"ID {i}")
    return "ok" if ok else "خطأ",200 if ok else 400

@app.route('/edit_ledger/<int:i>',methods=['POST'])
@login_required
def el(i):
    if not is_manager():return "ممنوع للفني",403
    try:amt=float(request.form.get('amount') or 0)
    except:amt=0
    ok=qexec("UPDATE ledger SET name=?,amount=?,note=?,currency=? WHERE id=?",(request.form.get('name',''),amt,request.form.get('note',''),request.form.get('currency','USD'),i))
    if ok: add_log(session.get('phone'),'تعديل حساب',f"ID {i}")
    return "ok" if ok else "خطأ",200 if ok else 400

@app.route('/add_user',methods=['POST'])
@login_required
@role_required_manager
def au():
    ph=request.form.get('phone','').strip() or request.form.get('user_field','').strip()
    if not ph:return "رقم مطلوب",400
    if qone("SELECT * FROM users WHERE phone=?",(ph,)):return "موجود مسبقاً",400
    ok=qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",(ph,generate_password_hash(request.form.get('password','1234')),request.form.get('role','tech'),ph))
    if ok: add_log(session.get('phone'),'إضافة يوزر',ph)
    return "ok" if ok else "خطأ",200 if ok else 400

@app.route('/edit_user',methods=['POST'])
@login_required
@role_required_manager
def eu():
    old=request.form.get('old_phone','').strip();new_ph=request.form.get('phone','').strip() or request.form.get('user_field','').strip()
    new_role=request.form.get('role','tech');new_pass=request.form.get('password','').strip()
    if not old:return "خطأ",400
    if old!=new_ph and qone("SELECT * FROM users WHERE phone=?",(new_ph,)): return "الرقم الجديد موجود",400
    if new_pass:ok=qexec("UPDATE users SET phone=?,username=?,role=?,password=? WHERE phone=?",(new_ph,new_ph,new_role,generate_password_hash(new_pass),old))
    else:ok=qexec("UPDATE users SET phone=?,username=?,role=? WHERE phone=?",(new_ph,new_ph,new_role,old))
    if session.get('phone')==old: session['phone']=new_ph; session['role']=new_role
    if ok: add_log(session.get('phone'),'تعديل يوزر',f"{old}->{new_ph}")
    return "ok" if ok else "خطأ",200 if ok else 400

@app.route('/del_user/<ph>')
@login_required
@role_required_manager
def du(ph):
    if ph=='05344851045':return "ممنوع حذف المدير",400
    ok=qexec("DELETE FROM users WHERE phone=?",(ph,))
    if ok: add_log(session.get('phone'),'حذف يوزر',ph)
    return "ok" if ok else "خطأ",200 if ok else 400

@app.route('/change_pass',methods=['POST'])
@login_required
def cp():
    np=request.form.get('newpass','').strip()
    if not np:return "فارغة",400
    ok=qexec("UPDATE users SET password=? WHERE phone=?",(generate_password_hash(np),session.get('phone')))
    if ok: add_log(session.get('phone'),'تغيير كلمة سر','')
    return "ok" if ok else "خطأ",200 if ok else 400

def page_content(v):
    is_mgr=is_manager()
    req_lang=request.args.get('lang') or session.get('lang','ar')
    def L(ar,en):return ar if req_lang=='ar' else en
    if v=='home':
        ns,nd,nt,nl=get_counts_cached()
        logs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 6")
        log_html="".join([f"<div style='display:flex;justify-content:space-between;padding:8px 10px;border-bottom:1px dashed #ffffff10'><div><b style='color:#ffbe4d'>{esc(l.get('user_phone',''))}</b> <span style='color:#22c55e;font-weight:800'>{esc(l.get('action',''))}</span> <small style='color:#cbd5e1'>{esc(l.get('detail',''))}</small></div><small style='color:#64748b'>{esc(l.get('time',''))}</small></div>" for l in logs])
        if not logs: log_html="<div style='padding:12px;color:#64748b'>السجل فاضي - اضف صحن وسيظهر هنا ✅</div>"
        return f'''<div style='max-width:900px;margin:0 auto'><div style='display:grid;grid-template-columns:1fr 1fr;gap:14px'>
        <div class='card anim' onclick="loadPage('subs')" style='cursor:pointer;background:linear-gradient(135deg,#1e2a4a 0%,#162040 100%)'><div style='display:flex;justify-content:space-between'><div><h3 style='margin:0;color:#aab4d0;font-size:13px'>{L('المشتركين','Subs')}</h3><h2 style='margin:6px 0 0;font-size:36px'>{ns}</h2></div><div style='font-size:36px'>👥</div></div></div>
        <div class='card anim' onclick="loadPage('dishes')" style='cursor:pointer;background:linear-gradient(135deg,#1e2f4a 0%,#162840 100%)'><div style='display:flex;justify-content:space-between'><div><h3 style='margin:0;color:#aab4d0;font-size:13px'>{L('الصحون','Dishes')}</h3><h2 style='margin:6px 0 0;font-size:36px'>{nd}</h2><small style='color:#22c55e'>⚡ فوري Pool 25</small></div><div style='font-size:36px'>📡</div></div></div>
        <div class='card anim' onclick="loadPage('towers')" style='cursor:pointer;background:linear-gradient(135deg,#2a1e4a 0%,#201640 100%)'><div style='display:flex;justify-content:space-between'><div><h3 style='margin:0;color:#aab4d0;font-size:13px'>{L('الأبراج','Towers')}</h3><h2 style='margin:6px 0 0;font-size:36px'>{nt}</h2></div><div style='font-size:36px'>🗼</div></div></div>
        <div class='card anim' onclick="loadPage('ledger')" style='cursor:pointer;background:linear-gradient(135deg,#4a2a1e 0%,#402016 100%)'><div style='display:flex;justify-content:space-between'><div><h3 style='margin:0;color:#aab4d0;font-size:13px'>{L('الحسابات','Accounts')}</h3><h2 style='margin:6px 0 0;font-size:36px'>{nl}</h2></div><div style='font-size:36px'>📒</div></div></div></div>
        <div class=card style='margin-top:14px'><div style='display:flex;justify-content:space-between;flex-wrap:wrap'><h4>📊 التقارير - Pool 25 ⚡</h4><div style='display:flex;gap:8px'><a href='/api/export/dishes' class=btn-gold style='text-decoration:none;padding:8px 12px;background:linear-gradient(90deg,#22c55e,#16a34a);color:#fff'>📗 Excel</a><a href='/api/export/logs' class=btn-gold style='text-decoration:none;padding:8px 12px;background:linear-gradient(90deg,#8b5cf6,#7c3aed);color:#fff'>📜 سجل</a></div></div></div>
        <div class=card><div style='display:flex;justify-content:space-between'><h4>📜 آخر النشاطات - السجل شغال ✅ يبين كل التعديلات</h4><button class=btn-gold onclick="loadPage('logs')">عرض الكل</button></div>{log_html}</div></div>'''
    if v=='ping':
        return f'''<div style='max-width:800px;margin:0 auto'>
        <div class=card style='background:linear-gradient(135deg,#0f172a,#1e293b);border:1px solid #22c55e33'>
        <h3 style='margin:0'>📶 {L('بنج منفصل','Separate Ping')} ⚡ ULTRA FAST</h3>
        <p style='color:#9ca3af;font-size:12px;margin:6px 0'>Pool 25 • فوري • بدون تعليق</p>
        <div style='display:flex;gap:8px;margin-top:12px;flex-wrap:wrap'>
        <input id=pingIp placeholder='192.168.1.1' style='flex:1;min-width:160px;padding:14px;border-radius:12px;background:#0f1424;border:1px solid #ffffff20;color:#fff;font-family:monospace'>
        <input id=pingPort placeholder='Port' value='80' style='width:80px;padding:14px;border-radius:12px;background:#0f1424;border:1px solid #ffffff20;color:#fff'>
        <button class=btn-gold onclick="doSinglePing()" style='padding:14px 20px;background:linear-gradient(90deg,#22c55e,#16a34a);color:#fff'>📶 Ping</button>
        <button class=btn-gold onclick="doTcpPing()" style='padding:14px 16px;background:linear-gradient(90deg,#0ea5e9,#0284c7);color:#fff'>TCP</button>
        </div>
        <div id=pingResult style='margin-top:14px;min-height:60px;background:#0008;border:1px solid #ffffff0a;border-radius:12px;padding:14px;font-family:monospace;font-size:13px;white-space:pre-wrap'>جاهز...</div>
        <div style='display:flex;gap:8px;margin-top:10px'><button class=btn-gold onclick="pingAllDishes()" style='flex:1;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111'>🚀 فحص كل الصحون</button><button class=btn-gold onclick="clearPing()" style='background:#ffffff10;color:#fff'>🗑</button></div>
        </div>
        <div class=card><h4>⚡ صحون سريعة</h4><div id=quickDishes>⏳...</div></div>
        <div class=card><h4>📜 سجل البنج</h4><div id=pingLog style='max-height:200px;overflow:auto;font-size:12px'></div></div>
        </div><script>
        async function doSinglePing(){{let ip=document.getElementById('pingIp').value.trim(); if(!ip){{alert('اكتب IP');return;}} let out=document.getElementById('pingResult'); out.textContent='⏳ فحص '+ip+'...'; out.style.color='#ffbe4d'; try{{let r=await fetch('/api/ping?ip='+encodeURIComponent(ip),{{cache:'no-store'}}); let j=await r.json(); out.textContent=j.out; out.style.color=j.ok?'#22c55e':'#ef4444'; addLog(ip,j.ok?'✅':'❌',j.out.slice(0,60));}}catch(e){{out.textContent='❌ '+e;}}}}
        async function doTcpPing(){{let ip=document.getElementById('pingIp').value.trim(); let port=document.getElementById('pingPort').value.trim()||'80'; if(!ip){{alert('IP');return;}} let out=document.getElementById('pingResult'); out.textContent='⏳ '+ip+':'+port+'...'; try{{let r=await fetch('/api/ping_tcp?ip='+encodeURIComponent(ip)+'&port='+port); let j=await r.json(); out.textContent=j.out; out.style.color=j.ok?'#22c55e':'#ef4444';}}catch(e){{out.textContent='خطأ';}}}}
        function clearPing(){{document.getElementById('pingResult').textContent='جاهز...';}}
        function addLog(ip,status,msg){{let l=document.getElementById('pingLog'); let d=new Date().toLocaleTimeString(); l.innerHTML='<div style="padding:6px 8px;border-bottom:1px solid #ffffff08"><span>'+status+' '+ip+' - '+msg.slice(0,50)+'</span><small style="color:#666">'+d+'</small></div>'+l.innerHTML;}}
        async function pingAllDishes(){{let out=document.getElementById('pingResult'); out.textContent='🚀 فحص...'; try{{let r=await fetch('/api/search?q=192',{{cache:'no-store'}}); let d=await r.json(); out.textContent=''; for(let dish of d.filter(x=>x.page==='dishes').slice(0,20)){{out.textContent+='⏳ '+dish.sub+'\\n'; try{{let pr=await fetch('/api/ping?ip='+encodeURIComponent(dish.sub)); let pj=await pr.json(); out.textContent+= (pj.ok?'✅ ':'❌ ')+dish.sub+' -> '+pj.out.slice(0,60)+'\\n'; addLog(dish.sub,pj.ok?'✅':'❌',pj.out.slice(0,40));}}catch(e){{}} await new Promise(r=>setTimeout(r,250));}}}}catch(e){{out.textContent='خطأ: '+e;}}}}
        (async()=>{{try{{let r=await fetch('/api/search?q=192',{{cache:'no-store'}}); let d=await r.json(); let h=''; d.filter(x=>x.page==='dishes').slice(0,8).forEach(x=>{{h+='<div style="display:flex;justify-content:space-between;padding:8px 10px;border-bottom:1px solid #ffffff08"><span>🌐 '+x.sub+' - '+x.title+'</span><button class=btn-gold onclick="document.getElementById(\\'pingIp\\').value=\\''+x.sub+'\\'; doSinglePing()" style="padding:5px 10px">Ping</button></div>';}}); document.getElementById('quickDishes').innerHTML=h||'لا يوجد';}}catch(e){{}}}})();
        </script>'''
    if v=='dishes':
        rs=qall("SELECT * FROM dish_ips ORDER BY id DESC")
        rows_html=""
        for r in rs:
            dn=esc(r.get('dish_name') or 'صحن');ip=esc(r.get('ip') or '');loc=esc(r.get('location') or '');rid=r['id']
            rows_html+=f'<div class="card anim dish-card" id="dish-{rid}" data-name="{dn}" data-ip="{ip}" data-loc="{loc}" style="display:flex;justify-content:space-between"><div><b>{dn}</b><br><a href="http://{ip}" target=_blank style="background:#000;color:#ffbe4d;padding:5px 10px;border-radius:8px;font-family:monospace;text-decoration:none">🌐 {ip}</a><br><small style="color:#888">{loc}</small><br><small style="color:#22c55e">⚡ فوري</small></div><div style="display:flex;flex-direction:column;gap:6px"><button class=btn-gold onclick="quickPingD({rid})" style="padding:7px 12px;background:linear-gradient(90deg,#22c55e,#16a34a);color:#fff">📶</button><div style="display:flex;gap:4px"><button class=btn-gold onclick="editDish({rid})" style="padding:7px 9px">✏</button><button class=btn-del onclick="askDel(\'/del_dish/{rid}\', {rid})" style="padding:7px 9px">🗑</button></div></div></div>'
        return f'''<div style='max-width:900px;margin:0 auto'><div class=card><div style='display:flex;justify-content:space-between;flex-wrap:wrap'><h3>📡 {L('الصحون','Dishes')} - {len(rs)} ⚡ فوري بدون تعليق</h3><div style='display:flex;gap:6px'><button onclick="loadPage('ping')" class=btn-gold style='padding:7px 12px;background:linear-gradient(90deg,#22c55e,#16a34a);color:#fff'>📶 Ping</button><a href='/api/export/dishes' class=btn-gold style='text-decoration:none;padding:7px 12px'>📗 Excel</a></div></div><form id=formDish style='display:flex;gap:6px;flex-wrap:wrap;margin-top:10px'><input name=dish_name id=dish_name placeholder='اسم الصحن' required style='flex:1'><input name=ip id=dish_ip placeholder='192.168.1.1' required style='flex:1'><input name=location id=dish_loc placeholder='موقع' style='flex:1'><button class=btn-gold type=submit id=btnAddDish>➕ حفظ فوري ⚡</button></form><div id=dishMsg style='margin-top:8px;font-size:13px;min-height:18px'></div><input id=searchBox placeholder='🔍 بحث فوري...' oninput="searchDishes(this.value)" style='margin-top:10px;width:100%;padding:12px;border-radius:12px;background:#0f1424;border:1px solid #ffffff18'></div><div id=dl>{rows_html}</div></div><script>
        function searchDishes(q){{q=(q||'').toLowerCase();document.querySelectorAll('.dish-card').forEach(c=>{{let t=(c.dataset.name+c.dataset.ip+c.dataset.loc).toLowerCase(); c.style.display=t.includes(q)?'flex':'none';}});}}
        function editDish(id){{let c=document.getElementById('dish-'+id);document.getElementById('editModal').classList.add('show');document.getElementById('editBody').innerHTML='<input id=edit_dish_name value="'+c.dataset.name+'" style="width:100%;padding:12px;margin:4px 0"><input id=edit_ip value="'+c.dataset.ip+'" style="width:100%;padding:12px;margin:4px 0"><input id=edit_loc value="'+c.dataset.loc+'" style="width:100%;padding:12px;margin:4px 0"><button onclick="saveDish('+id+')" class=btn-gold style="width:100%;padding:12px" id=btnSaveDish>💾 حفظ فوري</button>';}}
        function saveDish(id){{let b=document.getElementById('btnSaveDish'); b.innerHTML='⏳...'; b.disabled=true; let nn=document.getElementById('edit_dish_name').value;let ii=document.getElementById('edit_ip').value;let ll=document.getElementById('edit_loc').value;fetch('/edit_dish/'+id,{{method:'POST',body:new URLSearchParams({{dish_name:nn,ip:ii,location:ll}})}}).then(r=>{{if(r.ok){{closeEditModal(); loadPage('dishes',true);}} else {{alert('ممنوع'); b.innerHTML='💾'; b.disabled=false;}}}});}}
        function quickPingD(id){{let c=document.getElementById('dish-'+id);loadPage('ping');setTimeout(()=>{{let inp=document.getElementById('pingIp');if(inp){{inp.value=c.dataset.ip; doSinglePing();}}}},300);}}
        document.getElementById('formDish').addEventListener('submit', async e=>{{
          e.preventDefault(); let btn=document.getElementById('btnAddDish'); let msg=document.getElementById('dishMsg');
          let orig=btn.innerHTML; btn.innerHTML='⏳ فوري...'; btn.disabled=true; msg.textContent=''; msg.style.color='#ffbe4d';
          let fd=new FormData(e.target);
          try{{
            let r=await fetch('/add_dish',{{method:'POST',body:fd}});
            if(r.ok){{
              msg.style.color='#22c55e'; msg.textContent='✅ تمت الإضافة فورياً - السجل تحدث - بدون تعليق';
              e.target.reset();
              setTimeout(()=>{{delete pageCache['dishes']; loadPage('dishes',true,false); msg.textContent='';}},400);
            }} else {{ let t=await r.text(); msg.style.color='#ef4444'; msg.textContent=t||'خطأ'; }}
          }}catch(err){{ msg.textContent='خطأ شبكة'; }}
          btn.innerHTML=orig; btn.disabled=false;
        }});
        </script>'''
    if v=='towers':
        rs=qall("SELECT * FROM towers ORDER BY id DESC")
        rows="".join([f"<div class='card anim' id='tower-{r['id']}' data-name='{esc(r['name'])}' data-area='{esc(r['area'] or '')}' data-lat='{r.get('lat') or 0}' data-lng='{r.get('lng') or 0}'><div style='display:flex;justify-content:space-between'><div><b>🗼 {esc(r['name'])}</b><br><small>{esc(r['area'] or '')}</small><br><small style='color:#ffbe4d'>📍 {r.get('lat')} , {r.get('lng')}</small></div><div style='display:flex;gap:5px'><button class=btn-gold onclick=\"openEditTower({r['id']})\" style='padding:8px 10px'>✏</button><button class=btn-del onclick=\"askDel('/del_tower/{r['id']}')\" style='padding:8px 10px'>🗑</button></div></div></div>" for r in rs])
        return f'''<div style='max-width:700px;margin:0 auto'><div class=card><h3>🗼 {L('الأبراج','Towers')} ⚡ فوري</h3><form data-ajax method=post action=/add_tower style='display:flex;gap:6px;flex-wrap:wrap;margin-top:8px'><input name=name placeholder='اسم البرج' required style='flex:1'><input name=area placeholder='المنطقة' style='flex:1'><input name=lat placeholder='lat' style='flex:0.6'><input name=lng placeholder='lng' style='flex:0.6'><button class=btn-gold>➕ فوري ⚡</button></form></div>{rows}<script>
        function openEditTower(id){{let c=document.getElementById('tower-'+id);document.getElementById('editModal').classList.add('show');document.getElementById('editBody').innerHTML='<input id=edit_t_name value="'+c.dataset.name+'" style="width:100%;margin:6px 0;padding:12px"><input id=edit_t_area value="'+c.dataset.area+'" style="width:100%;margin:6px 0;padding:12px"><input id=edit_t_lat value="'+c.dataset.lat+'" style="width:100%;margin:6px 0;padding:12px"><input id=edit_t_lng value="'+c.dataset.lng+'" style="width:100%;margin:6px 0;padding:12px"><button onclick="saveTower('+id+')" class=btn-gold style="width:100%;padding:12px">💾 فوري</button>';}}
        function saveTower(id){{let nn=document.getElementById('edit_t_name').value;let aa=document.getElementById('edit_t_area').value;let la=document.getElementById('edit_t_lat').value;let ln=document.getElementById('edit_t_lng').value;fetch('/edit_tower/'+id,{{method:'POST',body:new URLSearchParams({{name:nn,area:aa,lat:la,lng:ln}})}}).then(r=>{{if(!r.ok)alert('ممنوع');else{{closeEditModal();loadPage('towers',true);}}}});}}
        </script></div>'''
    if v=='subs':
        rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 200")
        rows="".join([f"<div class='card anim' id='sub-{r['id']}' data-name='{esc(r['name'])}' data-phone='{esc(r['phone'] or '')}' data-note='{esc(r['note'] or '')}' style='display:flex;justify-content:space-between'><div><b>{esc(r['name'])}</b><br>📞 {esc(r['phone'] or '')}</div><div style='display:flex;gap:5px'><button class=btn-gold onclick=\"openEditSub({r['id']})\" style='padding:8px 10px'>✏</button><button class=btn-del onclick=\"askDel('/del_sub/{r['id']}')\" style='padding:8px 10px'>🗑</button></div></div>" for r in rs])
        return f'''<div style='max-width:700px;margin:0 auto'><div class=card><h3>👥 {L('المشتركين','Subs')} ⚡ فوري</h3><form data-ajax method=post action=/add_sub style='display:flex;gap:5px;flex-wrap:wrap'><input name=name placeholder='الاسم' required style='flex:1'><input name=phone placeholder='رقم' style='flex:1'><input name=note placeholder='ملاحظة' style='flex:1'><button class=btn-gold>➕ فوري</button></form></div>{rows}<script>
        function openEditSub(id){{let c=document.getElementById('sub-'+id);document.getElementById('editModal').classList.add('show');document.getElementById('editBody').innerHTML='<input id=edit_s_name value="'+c.dataset.name+'" style="width:100%;margin:6px 0;padding:12px"><input id=edit_s_phone value="'+c.dataset.phone+'" style="width:100%;margin:6px 0;padding:12px"><input id=edit_s_note value="'+c.dataset.note+'" style="width:100%;margin:6px 0;padding:12px"><button onclick="saveSub('+id+')" class=btn-gold style="width:100%;padding:12px">💾 فوري</button>';}}
        function saveSub(id){{let nn=document.getElementById('edit_s_name').value;let pp=document.getElementById('edit_s_phone').value;let no=document.getElementById('edit_s_note').value;fetch('/edit_sub/'+id,{{method:'POST',body:new URLSearchParams({{name:nn,phone:pp,note:no}})}}).then(r=>{{if(!r.ok)alert('ممنوع');else{{closeEditModal();loadPage('subs',true);}}}});}}
        </script></div>'''
    if v=='ledger':
        rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 200")
        rows="".join([f"<div class='card anim' id='led-{r['id']}' data-name='{esc(r['name'])}' data-amount='{r['amount']}'><div style='display:flex;justify-content:space-between'><div><b>{esc(r['name'])}</b> - <b style='color:#ffbe4d'>{r['amount']}</b></div><div><button class=btn-gold onclick=\"openEditLed({r['id']})\" style='padding:7px 9px'>✏</button><button class=btn-del onclick=\"askDel('/del_ledger/{r['id']}')\" style='padding:7px 9px'>🗑</button></div></div></div>" for r in rs])
        return f'''<div style='max-width:700px;margin:0 auto'><div class=card><h3>📒 {L('الحسابات','Accounts')} ⚡ فوري</h3><form data-ajax method=post action=/add_ledger style='display:flex;gap:5px;flex-wrap:wrap'><input name=name placeholder='الاسم' required style='flex:1'><input name=amount type=number step=0.01 placeholder='المبلغ' required style='flex:1'><input name=note placeholder='ملاحظة' style='flex:1'><select name=currency style='flex:0.5'><option>USD</option><option>SYP</option></select><button class=btn-gold>➕ فوري</button></form></div>{rows}<script>
        function openEditLed(id){{let c=document.getElementById('led-'+id);document.getElementById('editModal').classList.add('show');document.getElementById('editBody').innerHTML='<input id=edit_l_name value="'+c.dataset.name+'" style="width:100%;margin:6px 0;padding:12px"><input id=edit_l_amount value="'+c.dataset.amount+'" style="width:100%;margin:6px 0;padding:12px"><button onclick="saveLed('+id+')" class=btn-gold style="width:100%;padding:12px">💾 فوري</button>';}}
        function saveLed(id){{let nn=document.getElementById('edit_l_name').value;let aa=document.getElementById('edit_l_amount').value;fetch('/edit_ledger/'+id,{{method:'POST',body:new URLSearchParams({{name:nn,amount:aa,note:'',currency:'USD'}})}}).then(()=>{{closeEditModal();loadPage('ledger',true);}});}}
        </script></div>'''
    if v=='logs':
        rs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 300")
        rows="".join([f"<div class='card anim' style='font-size:13px;border-right:4px solid #ffbe4d;display:flex;justify-content:space-between'><div><b style='color:#ffbe4d'>{esc(r.get('user_phone',''))}</b> <span style='background:{'#22c55e' if 'إضافة' in r.get('action','') else '#0ea5e9' if 'تعديل' in r.get('action','') else '#ef4444' if 'حذف' in r.get('action','') else '#ffbe4d'};color:#fff;padding:2px 8px;border-radius:6px;font-size:11px'>{esc(r.get('action',''))}</span><br><small style='color:#cbd5e1'>{esc(r.get('detail',''))}</small></div><small style='color:#64748b'>{esc(r.get('time',''))}</small></div>" for r in rs])
        if not rs: rows="<div class=card style='text-align:center;padding:20px;color:#94a3b8'>📭 السجل فاضي - اضف صحن وسيظهر هنا فوراً<br><button class=btn-gold onclick=\"fetch('/api/seed_log',{method:'POST'}).then(()=>loadPage('logs',true))\" style='margin-top:10px'>🧪 اختبار السجل</button></div>"
        return f"<div style='max-width:900px;margin:0 auto'><div class=card style='display:flex;justify-content:space-between'><h3>📜 السجل - شغال ✅ يبين كل التعديلات ({len(rs)}) ⚡</h3><div style='display:flex;gap:6px'><a href='/api/export/logs' class=btn-gold style='text-decoration:none;padding:7px 12px;background:#22c55e;color:#fff'>📗 Excel</a><button onclick=\"if(confirm('مسح؟')){{fetch('/api/clear_logs',{method:'POST'}).then(()=>loadPage('logs',true))}}\" class=btn-del>🗑 مسح</button></div></div>{rows}</div>"
    if v=='network':
        dishes=qall("SELECT * FROM dish_ips ORDER BY id DESC")
        rows="".join([f"<div class='card anim' id='net-{d['id']}' data-ip='{esc(d.get('ip',''))}' style='display:flex;justify-content:space-between'><div><b>{esc(d.get('dish_name') or 'صحن')}</b> - {esc(d.get('ip',''))}<br><small class='net-out'>⏳...</small></div><button class=btn-gold onclick='checkOne({d['id']})'>📶</button></div>" for d in dishes])
        return f'''<div style='max-width:800px;margin:0 auto'><div class=card style='background:linear-gradient(135deg,#0f172a,#1e293b);border:1px solid #ffbe4d33'><h3>📊 حالة الشبكة LIVE ⚡ فوري</h3><div style='display:flex;gap:8px;margin-top:8px'><button class=btn-gold onclick='checkAll()' style='flex:1;background:linear-gradient(90deg,#22c55e,#16a34a);color:#fff;padding:12px'>🚀 فحص الكل</button><button class=btn-gold onclick="loadPage('ping')" style='flex:1'>📶 Ping</button></div><div id=summary style='margin-top:10px;font-weight:800'></div></div>{rows}<script>
        async function checkOne(id){{let c=document.getElementById('net-'+id);let out=c.querySelector('.net-out');out.textContent='⏳...';try{{let r=await fetch('/api/ping?ip='+encodeURIComponent(c.dataset.ip));let j=await r.json();out.textContent=j.out.slice(0,80);out.style.color=j.ok?'#22c55e':'#ef4444';}}catch(e){{out.textContent='❌';}}}}
        async function checkAll(){{let cards=document.querySelectorAll('[id^=net-]');let on=0,off=0;for(let c of cards){{let out=c.querySelector('.net-out');out.textContent='⏳...';try{{let r=await fetch('/api/ping?ip='+encodeURIComponent(c.dataset.ip));let j=await r.json();out.textContent=j.ok?'✅ '+j.out.slice(0,50):'❌ '+j.out.slice(0,50);out.style.color=j.ok?'#22c55e':'#ef4444'; if(j.ok)on++; else off++;}}catch(e){{off++;}} document.getElementById('summary').innerHTML='✅ '+on+' | ❌ '+off; await new Promise(r=>setTimeout(r,200));}}}}
        checkAll();
        </script></div>'''
    if v=='map':
        towers=qall("SELECT * FROM towers")
        tj_json=json.dumps([{"name":t['name'],"area":t.get('area') or '',"lat":float(t.get('lat') or 35.1318),"lng":float(t.get('lng') or 36.7578)} for t in towers],ensure_ascii=False)
        return f'''<div class=card style='padding:10px;background:linear-gradient(180deg,#0f172a,#111827);border:1px solid #ffffff12'>
        <div style='display:flex;gap:6px;margin-bottom:10px;flex-wrap:wrap'>
        <input id=mapSearch placeholder='🔍 بحث برج...' onkeydown="if(event.key==='Enter'){{event.preventDefault(); doMapSearch();}}" style='flex:1;min-width:140px;background:#1f2937;border:1px solid #ffffff15;color:#fff;padding:10px 12px;border-radius:12px'>
        <button class=btn-gold onclick="doMapSearch()" style='padding:10px 12px'>🔍 بحث</button>
        <button class=btn-gold onclick="locateMe()" style='background:linear-gradient(90deg,#22c55e,#16a34a);color:#fff;padding:10px 12px'>📍 موقعي</button>
        <button class=btn-gold onclick="enableAddPoint()" id=addPointBtn style='background:linear-gradient(90deg,#f59e0b,#d97706);color:#fff;padding:10px 12px'>➕ نقطة</button>
        <button class=btn-gold onclick="toggleMeasure()" id=measureBtn style='background:linear-gradient(90deg,#0ea5e9,#0284c7);color:#fff;padding:10px 12px'>📏 قياس</button>
        <button class=btn-gold onclick="clearMap()" style='background:#ef4444;color:#fff;padding:10px 12px'>🗑</button>
        <span id=distanceLabel style='padding:8px 12px;background:#1f2937;border:1px solid #ffbe4d33;border-radius:10px;font-size:12px;color:#ffbe4d'>📏 0</span>
        </div>
        <div id=map style='height:72vh;min-height:460px;border-radius:16px;background:#0f172a;z-index:1;border:2px solid #ffffff0f'></div>
        <div style='margin-top:6px;font-size:11px;color:#6b7280'><span id=coordsLabel style='color:#ffbe4d'>📍 -</span></div>
        </div><script>
        let _towers={tj_json};
        let _map=null; let measureMode=false, addPointMode=false, measurePoints=[], measureLine=null, measureMarkers=[], tempMarkers=[];
        window.doMapSearch=function(){{let q=document.getElementById('mapSearch').value.trim().toLowerCase(); if(!q) return; let f=_towers.find(t=>t.name.toLowerCase().includes(q)||t.area.toLowerCase().includes(q)); if(f && _map){{_map.flyTo([f.lat,f.lng],17);}}}}
        window.locateMe=function(){{if(_map && navigator.geolocation){{navigator.geolocation.getCurrentPosition(p=>{{_map.flyTo([p.coords.latitude,p.coords.longitude],16); L.marker([p.coords.latitude,p.coords.longitude]).addTo(_map).bindPopup('📍 موقعك').openPopup();}});}}}}
        window.enableAddPoint=function(){{addPointMode=!addPointMode; let b=document.getElementById('addPointBtn'); b.textContent=addPointMode?'✅ اضغط':'➕ نقطة'; if(addPointMode){{measureMode=false; _map.getContainer().style.cursor='crosshair';}}else{{_map.getContainer().style.cursor='';}}}}
        window.toggleMeasure=function(){{measureMode=!measureMode; let b=document.getElementById('measureBtn'); b.textContent=measureMode?'✅':'📏'; if(measureMode){{addPointMode=false; _map.getContainer().style.cursor='crosshair';}}else{{_map.getContainer().style.cursor='';}}}}
        window.clearMap=function(){{measurePoints=[]; if(measureLine){{_map.removeLayer(measureLine); measureLine=null;}}measureMarkers.forEach(m=>_map.removeLayer(m)); measureMarkers=[]; tempMarkers.forEach(m=>_map.removeLayer(m)); tempMarkers=[]; document.getElementById('distanceLabel').textContent='📏 0';}};
        setTimeout(()=>{{
          _map=L.map('map').setView([35.1318,36.7578],13);
          let osm=L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png').addTo(_map);
          let sat=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}').addTo(_map);
          L.control.layers({{"عادية":osm,"قمر":sat}}).addTo(_map);
          setTimeout(()=>_map.invalidateSize(),300);
          _towers.forEach(t=>{{L.marker([t.lat,t.lng]).addTo(_map).bindPopup(t.name);}});
          _map.on('click',e=>{{
            document.getElementById('coordsLabel').textContent='📍 '+e.latlng.lat.toFixed(5)+','+e.latlng.lng.toFixed(5);
            if(measureMode){{
              measurePoints.push(e.latlng);
              let mk=L.marker(e.latlng).addTo(_map); measureMarkers.push(mk);
              if(measureLine) _map.removeLayer(measureLine);
              if(measurePoints.length>1){{
                measureLine=L.polyline(measurePoints,{{color:'#ffbe4d',weight:4,dashArray:'8,8'}}).addTo(_map);
                let d=0; for(let i=1;i<measurePoints.length;i++){{d+=measurePoints[i-1].distanceTo(measurePoints[i]);}}
                document.getElementById('distanceLabel').textContent='📏 '+(d/1000).toFixed(3)+' كم';
              }}
              return;
            }}
            if(addPointMode){{
              let lat=e.latlng.lat.toFixed(6), lng=e.latlng.lng.toFixed(6);
              L.popup().setLatLng(e.latlng).setContent('<div><b>➕ نقطة</b><br><input id="newPointName" placeholder="اسم" style="width:100%;margin:6px 0;padding:8px"><input id="newPointArea" placeholder="منطقة" style="width:100%;margin:4px 0;padding:8px"><button onclick="saveNewPoint('+lat+','+lng+')" style="width:100%;background:#ffbe4d;border:0;padding:9px;border-radius:8px;font-weight:800">💾 حفظ</button></div>').openOn(_map);
            }}
          }});
          window.saveNewPoint=function(lat,lng){{let name=document.getElementById('newPointName').value||'نقطة'; let area=document.getElementById('newPointArea').value||''; fetch('/add_tower',{{method:'POST',body:new URLSearchParams({{name:name,area:area,lat:lat,lng:lng}})}}).then(r=>{{if(r.ok){{_map.closePopup(); alert('✅ تمت إضافة '+name);}}}});}};
        }},300);
        </script>'''
    if v=='support':
        return """<div class=card style='text-align:center;max-width:500px;margin:0 auto'><h2>🛠 الدعم</h2><a href='https://wa.me/905344851045' target=_blank style='display:inline-block;background:#22c55e;color:#fff;padding:14px 24px;border-radius:14px;text-decoration:none;margin:6px;font-weight:800'>💬 واتساب</a><br><a href='tel:+905344851045' style='display:inline-block;background:#0ea5e9;color:#fff;padding:12px 22px;border-radius:14px;text-decoration:none;margin:6px'>📞 +90 534 485 10 45</a></div>"""
    if v=='settings':
        us=qall("SELECT * FROM users ORDER BY phone DESC"); uh=""
        for u in us:
            ph=esc(u["phone"]);un=esc(u.get("username") or "");ro=esc(u.get("role") or "")
            badge="<span style='background:#ffbe4d;color:#111;padding:2px 8px;border-radius:8px;font-size:11px;font-weight:800'>مدير</span>" if ro=='manager' else "<span style='background:#ffffff15;color:#aaa;padding:2px 8px;border-radius:8px;font-size:11px'>فني</span>"
            uh+=f'<div class="card anim" id="user-{ph}" data-phone="{ph}" data-username="{un}" data-role="{ro}" style="display:grid;grid-template-columns:1fr auto;gap:12px;align-items:center"><div><b>{un}</b><br><span style="color:#ffbe4d;font-family:monospace">{ph}</span> {badge}</div><div style="display:flex;gap:6px"><button class=btn-gold onclick="openEditUser(\'{ph}\')" style="padding:8px 10px">✏</button><button class=btn-del onclick="askDel(\'/del_user/{ph}\')" style="padding:8px 10px">🗑</button></div></div>'
        return f'''<div style='max-width:800px;margin:0 auto'><div class=card><h3>🔑 كلمة السر - فوري</h3><form data-ajax method=post action=/change_pass style='display:flex;gap:8px'><input name=newpass type=password placeholder='جديدة' required style='flex:1'><button class=btn-gold>💾 فوري</button></form></div><div style='display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:12px'><div class=card style='text-align:center'><h4>🌐 اللغة</h4><button onclick="toggleLang()" style='width:100%;padding:14px;border-radius:12px;background:#1f2937;color:#fff;font-weight:800;cursor:pointer'>🌐 عربي</button><small style='color:#22c55e'>Pool 25 • فوري</small></div><div class=card><h4>👤 اضافة يوزر</h4><form data-ajax method=post action=/add_user style='display:flex;flex-direction:column;gap:10px'><input name=user_field placeholder='📱 رقم / يوزر' required style='padding:14px;background:#0f1424;border:1px solid #ffffff20;border-radius:12px;color:#fff'><input name=password type=password placeholder='🔑 password' required style='padding:14px;background:#0f1424;border:1px solid #ffffff20;border-radius:12px;color:#fff'><select name=role style='padding:12px;background:#0f1424;border:1px solid #ffffff20;border-radius:12px;color:#fff'><option value=tech>فني</option><option value=manager>مدير</option></select><button class=btn-gold style='padding:14px'>➕ فوري</button></form></div><div class=card><h4>📊 تصدير</h4><a href='/api/export/users' class=btn-gold style='text-decoration:none;padding:10px;text-align:center;background:#22c55e;color:#fff;border-radius:10px;display:block;margin-bottom:6px'>📗 يوزرات</a><a href='/api/export/dishes' class=btn-gold style='text-decoration:none;padding:10px;text-align:center;background:#0ea5e9;color:#fff;border-radius:10px;display:block'>📘 صحون</a></div></div>{uh}<script>
        function openEditUser(ph){{let c=document.getElementById('user-'+ph);document.getElementById('editModal').classList.add('show');document.getElementById('editBody').innerHTML='<input id=edit_u_field value="'+c.dataset.phone+'" style="width:100%;padding:12px"><input id=edit_u_pass type="password" placeholder="كلمة سر جديدة" style="width:100%;padding:12px;margin-top:8px"><select id=edit_u_role style="width:100%;padding:12px;margin-top:8px"><option value="tech" '+(c.dataset.role=='tech'?'selected':'')+'>فني</option><option value="manager" '+(c.dataset.role=='manager'?'selected':'')+'>مدير</option></select><button onclick="saveUser(\\''+ph+'\\')" class=btn-gold style="width:100%;padding:14px;margin-top:12px">💾 فوري</button>';}}
        function saveUser(oldPh){{let ff=document.getElementById('edit_u_field').value.trim();let pw=document.getElementById('edit_u_pass').value;let ro=document.getElementById('edit_u_role').value;if(!ff){{alert('مطلوب');return;}}let data={{old_phone:oldPh,phone:ff,username:ff,role:ro}};if(pw.trim()!='')data.password=pw.trim();fetch('/edit_user',{{method:'POST',body:new URLSearchParams(data)}}).then(r=>{{if(!r.ok)r.text().then(t=>alert(t));else{{closeEditModal();loadPage('settings',true);}}}});}}
        </script></div>'''
    return "<div class=card>ok</div>"

def layout(c,v='home',fast=False):
    th=session.get('theme','dark');is_dark=(th=='dark')
    bg='radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 60%, #070a1f 100%)' if is_dark else '#f1f5f9'
    card_bg='#1e2433' if is_dark else '#ffffff';txt='#ffffff' if is_dark else '#0f172a';border='#ffffff12' if is_dark else '#e2e8f0'
    cur_user=qone("SELECT * FROM users WHERE phone=?",(session.get('phone') or '',)) or {}; role=(cur_user.get('role') or session.get('role') or 'tech')
    req_lang=session.get('lang','ar'); is_rtl=req_lang=='ar'
    def L(ar,en): return ar if is_rtl else en
    username_display=esc(cur_user.get('username') or session.get('phone') or '')
    sidebar_pos="right:0; left:auto; transform:translateX(110%);" if is_rtl else "left:0; right:auto; transform:translateX(-110%);"
    side="right" if is_rtl else "left"
    dir_attr="rtl" if is_rtl else "ltr"
    return f"""<html dir={dir_attr} lang={req_lang}><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1,maximum-scale=1'>
<link rel=stylesheet href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'>
<style>
*{{box-sizing:border-box;font-family:system-ui}}body{{margin:0;background:{bg};color:{txt};overflow-x:hidden;direction:{dir_attr}}}
.anim{{animation:fadeUp .22s ease both}}@keyframes fadeUp{{from{{opacity:0;transform:translateY(8px)}}to{{opacity:1;transform:none}}}}
.top{{position:fixed;top:0;left:0;right:0;height:62px;background:linear-gradient(90deg,#0f172af2,#111827f2);backdrop-filter:blur(16px);color:#fff;display:flex;align-items:center;justify-content:space-between;padding:0 14px;z-index:1003;border-bottom:1px solid #ffffff12}}
.sidebar{{position:fixed;top:0;width:285px;height:100%;background:linear-gradient(180deg,#0f172a 0%,#070e22 100%);color:#fff;z-index:1002;padding-top:70px;{sidebar_pos}transition:transform .28s cubic-bezier(.4,0,.2,1);overflow-y:auto}}
.sidebar.active{{transform:none}}
.sidebar a{{display:flex;align-items:center;gap:11px;padding:12px 15px;margin:6px 11px;color:#cbd5e1;text-decoration:none;border-radius:13px;background:#ffffff06}}
.sidebar a.active{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:800}}
#overlay{{position:fixed;inset:0;background:#0008;z-index:1001;display:none}}#overlay.show{{display:block}}
.main{{margin-top:74px;padding:14px;min-height:90vh}}
.card{{background:{card_bg};color:{txt};padding:15px;border-radius:15px;margin-bottom:11px;border:1px solid {border}}}
input,select{{padding:12px 14px;margin:5px 0;border-radius:11px;border:1px solid {border};width:100%;background:#ffffff07;color:{txt}}}
.btn-gold{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;padding:9px 16px;border:0;border-radius:11px;font-weight:800;cursor:pointer}}
.btn-del{{background:linear-gradient(90deg,#ef4444,#dc2626);color:#fff;padding:8px 13px;border:0;border-radius:11px;cursor:pointer}}
#delModal, #editModal{{position:fixed;inset:0;background:#000a;display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:.28s;z-index:2000}}
#delModal.show, #editModal.show{{opacity:1;pointer-events:auto}}
#delBox, #editBox{{background:{card_bg};color:{txt};padding:24px;border-radius:18px;width:92%;max-width:450px}}
.skeleton{{background:linear-gradient(90deg,#1a2035 25%,#222b45 50%,#1a2035 75%);background-size:200% 100%;animation:shimmer .9s infinite}}
@keyframes shimmer{{0%{{background-position:-200% 0}}100%{{background-position:200% 0}}}}
</style></head><body>
<div id=overlay onclick="toggleSb(false)"></div>
<div class=sidebar id=sb>
<div style='padding:0 18px 10px;border-bottom:1px solid #ffffff0a;margin-bottom:8px'><div style='font-weight:900'>OMAIA <span style='color:#ffbe4d'>ISP</span> <small style='color:#22c55e'>⚡ ULTRA</small></div><small style='color:#64748b'>{username_display} • {role} • Pool 25</small><br><small style='color:#22c55e'>✅ فوري • بدون تعليق • بدون تحميل كامل</small></div>
<a href="javascript:loadPage('home')" id=nav-home onmouseenter="prefetchPage('home')">🏠 {L('الرئيسية','Home')}</a>
<a href="javascript:loadPage('dishes')" id=nav-dishes onmouseenter="prefetchPage('dishes')">📡 {L('الصحون','Dishes')} <span style='background:#22c55e;color:#fff;padding:2px 6px;border-radius:6px;font-size:9px'>⚡ فوري</span></a>
<a href="javascript:loadPage('ping')" id=nav-ping onmouseenter="prefetchPage('ping')">📶 Ping <span style='background:#22c55e;color:#fff;padding:2px 6px;border-radius:6px;font-size:9px'>⚡</span></a>
<a href="javascript:loadPage('network')" id=nav-network onmouseenter="prefetchPage('network')">📊 حالة الشبكة LIVE</a>
<a href="javascript:loadPage('logs')" id=nav-logs onmouseenter="prefetchPage('logs')">📜 السجل <span style='background:#22c55e;color:#fff;padding:2px 6px;border-radius:6px;font-size:9px'>شغال</span></a>
<a href="javascript:loadPage('towers')" id=nav-towers onmouseenter="prefetchPage('towers')">🗼 الأبراج</a>
<a href="javascript:loadPage('subs')" id=nav-subs onmouseenter="prefetchPage('subs')">👥 المشتركين</a>
<a href="javascript:loadPage('ledger')" id=nav-ledger onmouseenter="prefetchPage('ledger')">📒 الحسابات</a>
<a href="javascript:loadPage('map')" id=nav-map onmouseenter="prefetchPage('map')">🗺 الخريطة HD</a>
<a href="javascript:loadPage('settings')" id=nav-settings onmouseenter="prefetchPage('settings')">⚙ الإعدادات</a>
<a href="javascript:logoutFast()" style='margin-top:10px;background:#ef444418'>🚪 خروج</a>
</div>
<div class=top>
<div style='display:flex;gap:8px;align-items:center'><span onclick="toggleSb()" style='font-size:24px;cursor:pointer;padding:6px 8px;background:#ffffff0a;border-radius:8px'>☰</span><input id=topsearch placeholder='🔍 بحث فوري...' oninput="globalSearchTop(this.value)" style='background:#1f2937;border:1px solid #ffffff15;color:#fff;padding:8px 12px;border-radius:10px;width:42px;transition:all .22s' onfocus="this.style.width='160px'" onblur="setTimeout(()=>this.style.width='42px',200)"></div>
<div style='font-weight:900'>OMAIA <span style='color:#ffbe4d'>ISP</span> <span style='color:#22c55e;font-size:10px'>ULTRA • Pool 25</span></div>
<div style='display:flex;gap:8px'><button onclick="toggleTheme()" style='background:#ffffff0a;color:#fff;border:1px solid #ffffff0f;padding:8px 10px;border-radius:10px'>🌓</button></div>
</div>
<div id=searchResults style='position:fixed;top:66px;{side}:12px;max-width:400px;width:90%;background:#1e2433;border:1px solid #ffffff15;border-radius:12px;z-index:1500;display:none;max-height:60vh;overflow:auto'></div>
<div class=main id=mn>{c}</div>
<div id=delModal><div id=delBox><div style='font-size:36px;text-align:center'>🗑</div><h3 style='text-align:center'>حذف فوري؟</h3><p style='text-align:center;color:#94a3b8;font-size:13px'>سيتم الحذف فورياً ويظهر في السجل - بدون تعليق</p><div style='display:flex;gap:10px;margin-top:14px'><button onclick="closeDel()" style='flex:1;padding:12px;border-radius:10px;background:transparent;color:{txt};border:1px solid {border}'>تراجع</button><button id=delYes style='flex:1;padding:12px;border-radius:10px;background:#ef4444;color:#fff;border:0;font-weight:800'>حذف فوري ⚡</button></div></div></div>
<div id=editModal><div id=editBox><div style='display:flex;justify-content:space-between;margin-bottom:12px'><h3 style='margin:0'>✏ تعديل فوري</h3><button onclick="closeEditModal()" style='background:#ffffff12;border:0;color:{txt};width:32px;height:32px;border-radius:50%'>✕</button></div><div id=editBody></div></div></div>
<script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>
<script>
let cur='{v}'; let lang='{req_lang}';
function toggleSb(f){{let sb=document.getElementById('sb'),ov=document.getElementById('overlay'); let o=f!==undefined?f:!sb.classList.contains('active'); sb.classList.toggle('active',o); ov.classList.toggle('show',o);}}
let pageCache={{}}; try{{pageCache=JSON.parse(localStorage.getItem('omaia_cache_ultra_v4')||'{{}}');}}catch(e){{pageCache={{}};}}
function saveCache(){{try{{localStorage.setItem('omaia_cache_ultra_v4',JSON.stringify(pageCache));}}catch(e){{}}}}
function prefetchPage(v){{ if(pageCache[v]) return; fetch('/api/page?v='+v,{{cache:'no-store'}}).then(r=>r.text()).then(h=>{{ if(h && h.length>100){{ pageCache[v]=h; saveCache(); }} }}).catch(()=>{{}}); }}
async function loadPage(v,force=false,push=true){{
  if(push && cur!==v){{try{{history.pushState({{page:v}},'', '/dash?v='+v);}}catch(e){{}}}}
  cur=v; toggleSb(false);
  document.querySelectorAll('.sidebar a').forEach(a=>a.classList.remove('active')); let n=document.getElementById('nav-'+v); if(n) n.classList.add('active');
  let mn=document.getElementById('mn');
  if(!force && pageCache[v]){{
    mn.innerHTML=pageCache[v]; bind(); execScripts();
    fetch('/api/page?v='+v,{{cache:'no-store'}}).then(r=>r.text()).then(h=>{{ if(h && h.length>100){{ pageCache[v]=h; saveCache(); }} }}).catch(()=>{{}});
    return;
  }}
  mn.innerHTML='<div class=card><div class="skeleton" style="height:20px;width:40%;border-radius:8px;margin-bottom:10px"></div><div class="skeleton" style="height:14px;border-radius:6px"></div></div>';
  try{{let r=await fetch('/api/page?v='+v,{{cache:'no-store'}}); let h=await r.text(); pageCache[v]=h; saveCache(); mn.innerHTML=h; bind(); execScripts();}}catch(e){{mn.innerHTML='<div class=card>❌ '+e+'</div>';}}
}}
function execScripts(){{document.getElementById('mn').querySelectorAll('script').forEach(s=>{{try{{eval(s.textContent)}}catch(e){{}}}});}}
function bind(){{
  document.querySelectorAll('form[data-ajax]').forEach(f=>{{
    if(f.dataset.bound) return; f.dataset.bound='1';
    f.onsubmit=async e=>{{
      e.preventDefault(); let btn=f.querySelector('button'); let old=btn.innerHTML; btn.innerHTML='⏳ فوري...'; btn.disabled=true;
      try{{let r=await fetch(f.action,{{method:'POST',body:new FormData(f)}}); if(r.ok){{ delete pageCache[cur]; await loadPage(cur,true,false); }} else {{ let t=await r.text(); alert(t); btn.innerHTML=old; btn.disabled=false; }} }}catch(err){{ alert(err); btn.innerHTML=old; btn.disabled=false; }}
    }};
  }});
}}
function askDel(url, id){{window._delUrl=url; window._delId=id; document.getElementById('delModal').classList.add('show');}}
function closeDel(){{document.getElementById('delModal').classList.remove('show'); window._delUrl=null;}}
window.closeEditModal=function(){{document.getElementById('editModal').classList.remove('show');}}
document.getElementById('delYes').onclick=async()=>{{
  if(!window._delUrl) return;
  let btn=document.getElementById('delYes'); let o=btn.innerHTML; btn.innerHTML='⏳ فوري...'; btn.disabled=true;
  try{{
    let r=await fetch(window._delUrl);
    if(r.ok){{
      if(window._delId){{let el=document.getElementById('dish-'+window._delId); if(el) el.style.display='none';}}
      closeDel();
      setTimeout(()=>{{delete pageCache[cur]; loadPage(cur,true,false);}},300);
   }} else {{let t=await r.text(); alert(t);}}
  }}catch(e){{alert(e);}}
  btn.innerHTML=o; btn.disabled=false;
}};
async function toggleTheme(){{await fetch('/toggle_theme'); location.reload();}}
window.globalSearchTop=async function(q){{let box=document.getElementById('searchResults'); if(!q || q.length<2){{box.style.display='none'; return;}} let r=await fetch('/api/search?q='+encodeURIComponent(q)); let d=await r.json(); if(!d.length){{box.style.display='none'; return;}} let h=''; d.forEach(x=>{{h+='<div onclick="loadPage(\\''+x.page+'\\');document.getElementById(\\'searchResults\\').style.display=\\'none\\'" style="padding:10px 12px;cursor:pointer;border-bottom:1px solid #ffffff08"><b>'+x.title+'</b><br><small style="color:#888">'+x.sub+'</small></div>';}}); box.innerHTML=h; box.style.display='block';}}
window.logoutFast=async function(){{await fetch('/api/logout',{{method:'POST'}}); try{{localStorage.clear();}}catch(e){{}} location.replace('/login');}}
window.addEventListener('popstate',(e)=>{{let v='home'; if(e.state && e.state.page) v=e.state.page; else {{let p=new URLSearchParams(location.search); v=p.get('v')||'home';}} loadPage(v,false,false);}});
bind(); execScripts();
loadPage(cur,true,false);
if(!history.state){{try{{history.replaceState({{page:cur}},'', '/dash?v='+cur);}}catch(e){{}}}}
setTimeout(()=>{{['home','dishes','ping','logs','towers'].forEach(p=>prefetchPage(p));}},800);
</script></body></html>"""

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)),debug=False)
