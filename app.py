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

app = Flask(__name__)
_secret = os.environ.get("SECRET_KEY") or "dev-only-" + secrets.token_hex(32)
app.secret_key = _secret
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(hours=2)
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

DATABASE_URL = os.environ.get("DATABASE_URL","").strip().replace("postgresql://","postgres://")
USE_PG = bool(DATABASE_URL.startswith("postgres://") and psycopg2)

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
        try: _pg_pool = pg_pool.ThreadedConnectionPool(1,20,dsn=DATABASE_URL,sslmode='require',connect_timeout=3)
        except: _pg_pool=None
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
            _sqlite_conn = sqlite3.connect("omia.db", check_same_thread=False, timeout=15)
            _sqlite_conn.row_factory = sqlite3.Row
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
            cur.close()
            put_conn(conn)
            return rs
        else:
            with _sqlite_lock:
                rs=[dict(r) for r in conn.execute(q,a).fetchall()]
                return rs
    except:
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
    except:
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
        "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,dish_name TEXT)",
        "CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,area TEXT,lat REAL,lng REAL)",
        "CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,user_phone TEXT,action TEXT,detail TEXT,time TEXT)",
        "CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,msg TEXT,time TEXT,read INTEGER DEFAULT 0)"
    ]
    if USE_PG: ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
    for s in ss: qexec(s)
    for idx in ["CREATE INDEX IF NOT EXISTS idx_dish_ips_ip ON dish_ips(ip)", "CREATE INDEX IF NOT EXISTS idx_towers_name ON towers(name)", "CREATE INDEX IF NOT EXISTS idx_logs_id ON logs(id DESC)"]:
        try: qexec(idx)
        except: pass
    if USE_PG:
        try: qexec("CREATE UNIQUE INDEX IF NOT EXISTS uq_dish_ips_ip ON dish_ips(ip)")
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
    if session.get('role'): return session.get('role')=='manager'
    u=qone("SELECT role FROM users WHERE phone=?",(session.get('phone') or '',))
    if not u: return False
    session['role']=u.get('role')
    return (u.get('role') or '').lower()=='manager'

def role_required_manager(f):
    @wraps(f)
    def w(*a,**kw):
        if not is_manager(): return jsonify(ok=False,msg="ممنوع"),403
        return f(*a,**kw)
    return w

def is_valid_ip(ip):
    ip=(ip or '').strip()
    if not ip: return False
    try: ipaddress.ip_address(ip); return True
    except: return False

@app.after_request
def add_perf_headers(resp):
    resp.headers['Cache-Control']='no-store, max-age=0'
    return resp

@app.route('/health')
def public_ping(): return jsonify(ok=True,time=datetime.datetime.now().isoformat())

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
    if not ip or not is_valid_ip(ip): return jsonify(ok=False,out='IP غير صالح')
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures={ex.submit(_check_port,(ip,p)):p for p in [80,8291,22]}
        for f in as_completed(futures):
            port,ok=f.result()
            if ok: return jsonify(ok=True,out=f'{ip}:{port} مفتوح',port=port)
    try:
        cmd=['ping','-c','1','-W','1',ip] if platform.system().lower()!='windows' else ['ping','-n','1','-w','1000',ip]
        out=subprocess.check_output(cmd,timeout=2,stderr=subprocess.STDOUT).decode(errors='ignore')
        if 'ttl=' in out.lower() or 'bytes from' in out.lower():
            m=re.search(r'time[=<]\s*(\d+\.?\d*)',out,re.I)
            ms=m.group(1) if m else ''
            return jsonify(ok=True,out=f'{ip} - {ms}ms',ms=ms)
    except: pass
    return jsonify(ok=False,out=f'{ip} لا يرد')

@app.route('/api/ping_tcp')
@login_required
def api_ping_tcp():
    ip=request.args.get('ip','').strip()
    try: port=int(request.args.get('port','80').strip())
    except: return jsonify(ok=False,out='Port غير صالح')
    if not is_valid_ip(ip): return jsonify(ok=False,out='IP غير صالح')
    _,ok=_check_port((ip,port))
    return jsonify(ok=ok,out=f'{ip}:{port} مفتوح' if ok else f'{ip}:{port} مغلق')

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
    if not uin or not pw: return jsonify(ok=False,msg='املأ الحقول'),400
    u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
    if u and check_password_hash(u['password'],pw):
        session['phone']=u['phone']
        session['username']=u.get('username') or u['phone']
        session['role']=u.get('role') or 'tech'
        session.permanent=False
        add_log(u['phone'],'دخل النظام','تسجيل دخول')
        return jsonify(ok=True)
    return jsonify(ok=False,msg='خطأ بالدخول'),401

@app.route('/api/export/<tbl>')
@login_required
def api_export(tbl):
    output=io.StringIO(); output.write('\ufeff'); w=csv.writer(output)
    if tbl=='dishes':
        rows=qall("SELECT * FROM dish_ips ORDER BY id DESC")
        w.writerow(['ID','اسم الصحن','IP','الموقع'])
        for r in rows: w.writerow([r['id'],r.get('dish_name',''),r.get('ip',''),r.get('location','')])
        fname='dishes.csv'
    elif tbl=='towers':
        rows=qall("SELECT * FROM towers ORDER BY id DESC")
        w.writerow(['ID','اسم البرج','المنطقة','lat','lng'])
        for r in rows: w.writerow([r['id'],r.get('name',''),r.get('area',''),r.get('lat',''),r.get('lng','')])
        fname='towers.csv'
    elif tbl=='logs':
        rows=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 1000")
        w.writerow(['ID','المستخدم','العملية','التفاصيل','الوقت'])
        for r in rows: w.writerow([r['id'],r.get('user_phone',''),r.get('action',''),r.get('detail',''),r.get('time','')])
        fname='logs.csv'
    else: fname='export.csv'; w.writerow(['ID'])
    return Response(output.getvalue(),mimetype='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename={fname}'})

@app.route('/api/clear_logs',methods=['POST'])
@login_required
@role_required_manager
def clear_logs():
    qexec("DELETE FROM logs")
    with _cache_lock: _cache.clear()
    return jsonify(ok=True)

@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login')
def login():
    return """<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@700;900&display=swap" rel="stylesheet">
<style>*{box-sizing:border-box;font-family:'Cairo',system-ui}body{margin:0;min-height:100vh;background:radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 60%, #070a1f 100%);display:flex;flex-direction:column;align-items:center;justify-content:center;color:#fff}
.card{background:rgba(34,43,69,0.9);backdrop-filter:blur(14px);border:1px solid #ffffff15;padding:28px;border-radius:22px;width:92%;max-width:360px;transition:.4s cubic-bezier(0.34, 1.56, 0.64, 1)}
input{width:100%;padding:14px;margin:8px 0;background:#0f1424;border:1px solid #ffffff20;color:#fff;border-radius:14px}
input:focus{border-color:#ffbe4d;outline:none}
.btn{width:100%;padding:14px;border:0;border-radius:14px;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:900;font-size:17px;cursor:pointer;margin-top:10px;transition:.4s cubic-bezier(0.34, 1.56, 0.64, 1)}
.btn:hover{transform:scale(1.02)} .btn:active{transform:scale(0.97)}
</style></head><body>
<div style='font-size:28px;font-weight:900;margin-bottom:14px'>OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<div class=card><form id=loginForm><input name=userin placeholder='رقم / يوزر' required><input name=password type=password placeholder='كلمة السر' required><button class=btn id=loginBtn>دخول</button><div id=msg style='text-align:center;margin-top:10px;color:#ff6b6b;font-size:13px;min-height:18px'></div></form></div>
<script>
document.getElementById('loginForm').addEventListener('submit',async e=>{
 e.preventDefault();
 let btn=document.getElementById('loginBtn'), msg=document.getElementById('msg');
 if(btn.disabled) return; let o=btn.textContent; btn.textContent='جاري...'; btn.disabled=true; msg.textContent='';
 try{let r=await fetch('/api/login_public',{method:'POST',body:new FormData(e.target),cache:'no-store'}); let j=await r.json(); if(j.ok) location.replace('/dash?v=home'); else {msg.textContent=j.msg||'خطأ'; btn.textContent=o; btn.disabled=false;}}catch{msg.textContent='خطأ شبكة'; btn.textContent=o; btn.disabled=false;}
});
</script></body></html>"""

@app.route('/logout')
def lo(): session.clear(); return redirect('/login')
@app.route('/api/logout',methods=['POST'])
def api_logout(): session.clear(); return jsonify(ok=True)

@app.route('/dash')
@login_required
def dash(): return layout('<div class=card>جاري التحميل...</div>',request.args.get('v','home'))

@app.route('/api/page')
@login_required
def ap(): return page_content(request.args.get('v','home'))

@app.route('/api/search')
@login_required
def s():
    q=request.args.get('q','').strip()
    if not q: return jsonify([])
    like="%"+q+"%"
    res=[]
    try:
        for r in qall("SELECT * FROM dish_ips WHERE ip LIKE ? OR dish_name LIKE ? OR location LIKE ? ORDER BY id DESC LIMIT 20",(like,like,like)):
            res.append({"title":r.get('dish_name') or r.get('ip'),"sub":r.get('ip',''),"page":"dishes"})
        for r in qall("SELECT * FROM towers WHERE name LIKE ? OR area LIKE ? ORDER BY id DESC LIMIT 15",(like,like)):
            res.append({"title":r.get('name',''),"sub":r.get('area',''),"page":"towers"})
        for r in qall("SELECT * FROM subs WHERE name LIKE ? OR phone LIKE ? ORDER BY id DESC LIMIT 15",(like,like)):
            res.append({"title":r.get('name',''),"sub":r.get('phone',''),"page":"subs"})
    except: pass
    return jsonify(res[:25])

@app.route('/toggle_theme')
@login_required
def tt():
    cur=session.get('theme','dark'); session['theme']='light' if cur=='dark' else 'dark'
    return jsonify(ok=True)

@app.route('/add_dish',methods=['POST'])
@login_required
def ad():
    ip=request.form.get('ip','').strip(); name=request.form.get('dish_name','').strip(); loc=request.form.get('location','').strip()
    if not ip or not is_valid_ip(ip): return jsonify(ok=False,msg="IP غير صالح"),400
    if USE_PG: ok=qexec("INSERT INTO dish_ips(ip,location,dish_name) VALUES(?,?,?) ON CONFLICT (ip) DO UPDATE SET dish_name=EXCLUDED.dish_name, location=EXCLUDED.location",(ip,loc,name))
    else:
        ex=qone("SELECT id FROM dish_ips WHERE ip=?",(ip,))
        if ex: ok=qexec("UPDATE dish_ips SET dish_name=?,location=? WHERE ip=?",(name,loc,ip))
        else: ok=qexec("INSERT INTO dish_ips(ip,location,dish_name) VALUES(?,?,?)",(ip,loc,name))
    if ok: add_log(session.get('phone'),'إضافة صحن',name+" "+ip)
    return jsonify(ok=ok)

@app.route('/edit_dish/<int:i>',methods=['POST'])
@login_required
def ed(i):
    if not is_manager(): return jsonify(ok=False),403
    ok=qexec("UPDATE dish_ips SET dish_name=?,ip=?,location=? WHERE id=?",(request.form.get('dish_name',''),request.form.get('ip',''),request.form.get('location',''),i))
    if ok: add_log(session.get('phone'),'تعديل صحن',f"ID {i}")
    return jsonify(ok=ok)

@app.route('/del_dish/<int:i>')
@login_required
def dd(i):
    if not is_manager(): return jsonify(ok=False),403
    ok=qexec("DELETE FROM dish_ips WHERE id=?",(i,))
    if ok: add_log(session.get('phone'),'حذف صحن',f"ID {i}")
    return jsonify(ok=ok)

@app.route('/add_tower',methods=['POST'])
@login_required
def at():
    try:
        la=float(request.form.get('lat') or 35.1312); ln=float(request.form.get('lng') or 36.7578)
        if not (-90 <= la <= 90 and -180 <= ln <= 180): raise ValueError()
    except: return jsonify(ok=False,msg="احداثيات غير صالحة"),400
    ok=qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",(request.form.get('name',''),request.form.get('area',''),la,ln))
    if ok: add_log(session.get('phone'),'إضافة برج',request.form.get('name',''))
    return jsonify(ok=ok)

@app.route('/del_tower/<int:i>')
@login_required
def dt(i):
    if not is_manager(): return jsonify(ok=False),403
    ok=qexec("DELETE FROM towers WHERE id=?",(i,))
    if ok: add_log(session.get('phone'),'حذف برج',f"ID {i}")
    return jsonify(ok=ok)

@app.route('/edit_tower/<int:i>',methods=['POST'])
@login_required
def et(i):
    if not is_manager(): return jsonify(ok=False),403
    try: la=float(request.form.get('lat') or 35.1318)
    except: la=35.1318
    try: ln=float(request.form.get('lng') or 36.7578)
    except: ln=36.7578
    ok=qexec("UPDATE towers SET name=?,area=?,lat=?,lng=? WHERE id=?",(request.form.get('name',''),request.form.get('area',''),la,ln,i))
    if ok: add_log(session.get('phone'),'تعديل برج',f"ID {i}")
    return jsonify(ok=ok)

@app.route('/add_sub',methods=['POST'])
@login_required
def asub():
    ok=qexec("INSERT INTO subs(name,phone,note) VALUES(?,?,?)",(request.form.get('name',''),request.form.get('phone',''),request.form.get('note','')))
    if ok: add_log(session.get('phone'),'إضافة مشترك',request.form.get('name',''))
    return jsonify(ok=ok)

@app.route('/del_sub/<int:i>')
@login_required
def dsub(i):
    if not is_manager(): return jsonify(ok=False),403
    ok=qexec("DELETE FROM subs WHERE id=?",(i,))
    if ok: add_log(session.get('phone'),'حذف مشترك',f"ID {i}")
    return jsonify(ok=ok)

@app.route('/edit_sub/<int:i>',methods=['POST'])
@login_required
def esub(i):
    if not is_manager(): return jsonify(ok=False),403
    ok=qexec("UPDATE subs SET name=?,phone=?,note=? WHERE id=?",(request.form.get('name',''),request.form.get('phone',''),request.form.get('note',''),i))
    if ok: add_log(session.get('phone'),'تعديل مشترك',f"ID {i}")
    return jsonify(ok=ok)

@app.route('/add_ledger',methods=['POST'])
@login_required
def al():
    try: amt=float(request.form.get('amount') or 0)
    except: amt=0
    ok=qexec("INSERT INTO ledger(name,amount,note,currency) VALUES(?,?,?,?)",(request.form.get('name',''),amt,request.form.get('note',''),request.form.get('currency','USD')))
    if ok: add_log(session.get('phone'),'إضافة حساب',f"{request.form.get('name','')} {amt}")
    return jsonify(ok=ok)

@app.route('/del_ledger/<int:i>')
@login_required
def dll(i):
    if not is_manager(): return jsonify(ok=False),403
    ok=qexec("DELETE FROM ledger WHERE id=?",(i,))
    if ok: add_log(session.get('phone'),'حذف حساب',f"ID {i}")
    return jsonify(ok=ok)

@app.route('/edit_ledger/<int:i>',methods=['POST'])
@login_required
def el(i):
    if not is_manager(): return jsonify(ok=False),403
    try: amt=float(request.form.get('amount') or 0)
    except: amt=0
    ok=qexec("UPDATE ledger SET name=?,amount=?,note=?,currency=? WHERE id=?",(request.form.get('name',''),amt,request.form.get('note',''),request.form.get('currency','USD'),i))
    if ok: add_log(session.get('phone'),'تعديل حساب',f"ID {i}")
    return jsonify(ok=ok)

@app.route('/add_user',methods=['POST'])
@login_required
@role_required_manager
def au():
    ph=request.form.get('phone','').strip() or request.form.get('user_field','').strip()
    if not ph or qone("SELECT * FROM users WHERE phone=?",(ph,)): return jsonify(ok=False,msg="موجود"),400
    ok=qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",(ph,generate_password_hash(request.form.get('password','1234')),request.form.get('role','tech'),ph))
    if ok: add_log(session.get('phone'),'إضافة يوزر',ph)
    return jsonify(ok=ok)

@app.route('/edit_user',methods=['POST'])
@login_required
@role_required_manager
def eu():
    old=request.form.get('old_phone','').strip(); new_ph=request.form.get('phone','').strip() or request.form.get('user_field','').strip()
    new_role=request.form.get('role','tech'); new_pass=request.form.get('password','').strip()
    if not old: return jsonify(ok=False),400
    if old!=new_ph and qone("SELECT * FROM users WHERE phone=?",(new_ph,)): return jsonify(ok=False,msg="موجود"),400
    if new_pass: ok=qexec("UPDATE users SET phone=?,username=?,role=?,password=? WHERE phone=?",(new_ph,new_ph,new_role,generate_password_hash(new_pass),old))
    else: ok=qexec("UPDATE users SET phone=?,username=?,role=? WHERE phone=?",(new_ph,new_ph,new_role,old))
    if session.get('phone')==old: session['phone']=new_ph; session['role']=new_role
    if ok: add_log(session.get('phone'),'تعديل يوزر',f"{old}->{new_ph}")
    return jsonify(ok=ok)

@app.route('/del_user/<ph>')
@login_required
@role_required_manager
def du(ph):
    if ph=='05344851045': return jsonify(ok=False,msg="ممنوع"),400
    ok=qexec("DELETE FROM users WHERE phone=?",(ph,))
    if ok: add_log(session.get('phone'),'حذف يوزر',ph)
    return jsonify(ok=ok)

@app.route('/change_pass',methods=['POST'])
@login_required
def cp():
    np=request.form.get('newpass','').strip()
    if not np or len(np)<4: return jsonify(ok=False,msg="قصيرة"),400
    ok=qexec("UPDATE users SET password=? WHERE phone=?",(generate_password_hash(np),session.get('phone')))
    if ok: add_log(session.get('phone'),'تغيير كلمة سر','')
    return jsonify(ok=ok)

def page_content(v):
    req_lang=request.args.get('lang') or session.get('lang','ar')
    def L(ar,en): return ar if req_lang=='ar' else en
    if v=='home':
        ns,nd,nt,nl=get_counts()
        logs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 8")
        log_html="".join([f"<div style='display:flex;justify-content:space-between;padding:10px;border-bottom:1px dashed #ffffff10'><div><b style='color:#ffbe4d'>{esc(l.get('user_phone',''))}</b> <span style='color:#cbd5e1'>{esc(l.get('action',''))}</span> <small style='color:#888'>{esc(l.get('detail',''))}</small></div><small style='color:#64748b'>{esc(l.get('time',''))}</small></div>" for l in logs]) or "<div style='padding:12px;color:#888'>لا يوجد سجل</div>"
        return f'''<div style='max-width:1000px;margin:0 auto'><div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px'>
        <div class='card stat-card' onclick="loadPage('subs')" style='cursor:pointer'><h3 style='margin:0;color:#aab4d0;font-size:13px'>{L('المشتركين','Subs')}</h3><h2 style='margin:6px 0 0'>{ns}</h2></div>
        <div class='card stat-card' onclick="loadPage('dishes')" style='cursor:pointer'><h3 style='margin:0;color:#aab4d0;font-size:13px'>{L('الصحون','Dishes')}</h3><h2 style='margin:6px 0 0'>{nd}</h2></div>
        <div class='card stat-card' onclick="loadPage('towers')" style='cursor:pointer'><h3 style='margin:0;color:#aab4d0;font-size:13px'>{L('الأبراج','Towers')}</h3><h2 style='margin:6px 0 0'>{nt}</h2></div>
        <div class='card stat-card' onclick="loadPage('ledger')" style='cursor:pointer'><h3 style='margin:0;color:#aab4d0;font-size:13px'>{L('الحسابات','Accounts')}</h3><h2 style='margin:6px 0 0'>{nl}</h2></div></div>
        <div class=card style='margin-top:14px'><div style='display:flex;justify-content:space-between'><h4 style='margin:0'>آخر النشاطات</h4><button class=btn-gold onclick="loadPage('logs')">عرض الكل</button></div><div style='margin-top:10px'>{log_html}</div></div></div>'''
    if v=='dishes':
        rs=qall("SELECT * FROM dish_ips ORDER BY id DESC LIMIT 200")
        rows="".join([f"<div class='card dish-card' id='dish-{r['id']}' data-name='{esc(r.get('dish_name') or '')}' data-ip='{esc(r.get('ip') or '')}' data-loc='{esc(r.get('location') or '')}' style='display:flex;justify-content:space-between;align-items:center'><div><b>{esc(r.get('dish_name') or 'صحن')}</b><br><span style='font-family:monospace;color:#ffbe4d'>{esc(r.get('ip') or '')}</span><br><small style='color:#888'>{esc(r.get('location') or '')}</small></div><div style='display:flex;gap:6px'><button class='btn-gold icon-anim' onclick=\"editDish({r['id']})\" style='padding:8px 10px'>تعديل</button><button class='btn-del icon-anim' onclick=\"askDel('/del_dish/{r['id']}',{r['id']},'dish')\" style='padding:8px 10px'>حذف</button></div></div>" for r in rs])
        return f'''<div style='max-width:900px;margin:0 auto'><div class=card><div style='display:flex;justify-content:space-between'><h3 style='margin:0'>الصحون ({len(rs)})</h3><a href='/api/export/dishes' class=btn-gold style='text-decoration:none;padding:7px 12px'>Excel</a></div>
        <form id=formDish style='display:flex;gap:6px;flex-wrap:wrap;margin-top:12px'><input name=dish_name placeholder='اسم الصحن' required style='flex:1'><input name=ip placeholder='192.168.1.1' required style='flex:1'><input name=location placeholder='موقع' style='flex:1'><button class="btn-gold icon-anim" type=submit>إضافة</button></form>
        <input id=searchBox placeholder='بحث...' oninput="searchDishes(this.value)" style='margin-top:12px;width:100%;padding:11px;border-radius:12px;background:#0f1424;border:1px solid #ffffff18'></div><div style='display:grid;gap:10px'>{rows}</div></div><script>
        window.searchDishes=function(q){{q=(q||'').toLowerCase();document.querySelectorAll('.dish-card').forEach(c=>{{let t=(c.dataset.name+c.dataset.ip+c.dataset.loc).toLowerCase(); c.style.display=t.includes(q)?'flex':'none';}});}};
        window.editDish=function(id){{let c=document.getElementById('dish-'+id);let b=document.getElementById('editBody');b.innerHTML='<input id=edit_dish_name value="'+c.dataset.name+'" style="width:100%;padding:12px;margin:4px 0"><input id=edit_ip value="'+c.dataset.ip+'" style="width:100%;padding:12px;margin:4px 0"><input id=edit_loc value="'+c.dataset.loc+'" style="width:100%;padding:12px;margin:4px 0"><button onclick="saveDish('+id+')" class=btn-gold style="width:100%;padding:12px">حفظ</button>';document.getElementById('editModal').classList.add('show');}};
        window.saveDish=async function(id){{let nn=document.getElementById('edit_dish_name').value;let ii=document.getElementById('edit_ip').value;let ll=document.getElementById('edit_loc').value;let r=await fetch('/edit_dish/'+id,{{method:'POST',body:new URLSearchParams({{dish_name:nn,ip:ii,location:ll}})}});let j=await r.json();if(j.ok){{closeEditModal();loadPage('dishes',true);}}else alert(j.msg||'خطأ');}};
        document.getElementById('formDish').addEventListener('submit', async e=>{{e.preventDefault();let r=await fetch('/add_dish',{{method:'POST',body:new FormData(e.target)}});let j=await r.json();if(j.ok){{e.target.reset();loadPage('dishes',true);}}else alert(j.msg||'خطأ');}});
        </script>'''
    if v=='towers':
        rs=qall("SELECT * FROM towers ORDER BY id DESC")
        rows="".join([f"<div class='card' id='tower-{r['id']}' data-name='{esc(r['name'])}' data-area='{esc(r['area'] or '')}' data-lat='{r.get('lat') or 0}' data-lng='{r.get('lng') or 0}'><div style='display:flex;justify-content:space-between'><div><b>{esc(r['name'])}</b><br><small style='font-family:monospace;color:#ffbe4d'>{r.get('lat')},{r.get('lng')}</small><br><small>{esc(r['area'] or '')}</small></div><div><button class='btn-gold icon-anim' onclick=\"openEditTower({r['id']})\" style='padding:8px 10px'>تعديل</button> <button class='btn-del icon-anim' onclick=\"askDel('/del_tower/{r['id']}',{r['id']},'tower')\" style='padding:8px 10px'>حذف</button></div></div></div>" for r in rs])
        return f'''<div style='max-width:800px;margin:0 auto'><div class=card><h3>الأبراج ({len(rs)})</h3><form id=formTower style='display:flex;gap:6px;flex-wrap:wrap;margin-top:10px'><input name=name placeholder='اسم البرج' required style='flex:1'><input name=area placeholder='المنطقة' style='flex:1'><input name=lat placeholder='lat' style='flex:0.6'><input name=lng placeholder='lng' style='flex:0.6'><button class="btn-gold icon-anim">إضافة</button></form><input id=towerSearch placeholder='بحث...' oninput="searchTowers(this.value)" style='margin-top:8px;width:100%;padding:11px;border-radius:11px;background:#0f1424;border:1px solid #ffffff18'></div><div style='display:grid;gap:10px'>{rows}</div><script>
        window.searchTowers=function(q){{q=(q||'').toLowerCase();document.querySelectorAll('[id^=tower-]').forEach(c=>{{let t=(c.dataset.name+c.dataset.area).toLowerCase();c.style.display=t.includes(q)?'':'none';}});}};
        window.openEditTower=function(id){{let c=document.getElementById('tower-'+id);let b=document.getElementById('editBody');b.innerHTML='<input id=edit_t_name value="'+c.dataset.name+'" style="width:100%;margin:6px 0;padding:12px"><input id=edit_t_area value="'+c.dataset.area+'" style="width:100%;margin:6px 0;padding:12px"><input id=edit_t_lat value="'+c.dataset.lat+'" style="width:100%;margin:6px 0;padding:12px"><input id=edit_t_lng value="'+c.dataset.lng+'" style="width:100%;margin:6px 0;padding:12px"><button onclick="saveTower('+id+')" class=btn-gold style="width:100%;padding:12px">حفظ</button>';document.getElementById('editModal').classList.add('show');}};
        window.saveTower=async function(id){{let nn=document.getElementById('edit_t_name').value;let aa=document.getElementById('edit_t_area').value;let la=document.getElementById('edit_t_lat').value;let ln=document.getElementById('edit_t_lng').value;let r=await fetch('/edit_tower/'+id,{{method:'POST',body:new URLSearchParams({{name:nn,area:aa,lat:la,lng:ln}})}});let j=await r.json();if(j.ok){{closeEditModal();loadPage('towers',true);}}}};
        document.getElementById('formTower').addEventListener('submit', async e=>{{e.preventDefault();let r=await fetch('/add_tower',{{method:'POST',body:new FormData(e.target)}});let j=await r.json();if(j.ok){{e.target.reset();loadPage('towers',true);}}else alert(j.msg||'خطأ');}});
        </script></div>'''
    if v=='logs':
        rs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 300")
        rows="".join([f"<div class='card' style='display:flex;justify-content:space-between;font-size:13px'><div><b style='color:#ffbe4d'>{esc(r.get('user_phone',''))}</b> {esc(r.get('action',''))} <small style='color:#888'>{esc(r.get('detail',''))}</small></div><small style='color:#64748b'>{esc(r.get('time',''))}</small></div>" for r in rs]) or "<div class=card>لا يوجد سجل</div>"
        return f"<div style='max-width:900px;margin:0 auto'><div class=card style='display:flex;justify-content:space-between'><h3 style='margin:0'>السجل ({len(rs)})</h3><div style='display:flex;gap:6px'><a href='/api/export/logs' class=btn-gold style='text-decoration:none;padding:7px 12px;background:#22c55e;color:#fff;border-radius:8px'>Excel</a><button onclick=\"if(confirm('مسح؟'))fetch('/api/clear_logs',{{method:'POST'}}).then(()=>loadPage('logs',true))\" class=btn-del>مسح</button></div></div><div style='display:grid;gap:8px'>{rows}</div></div>"
    if v=='map':
        towers=qall("SELECT * FROM towers")
        tj=json.dumps([{"name":t['name'],"area":t.get('area') or '',"lat":float(t.get('lat') or 35.1318),"lng":float(t.get('lng') or 36.7578)} for t in towers],ensure_ascii=False)
        return f'''<div class=card style='padding:10px'><div style='display:flex;gap:6px;margin-bottom:10px;flex-wrap:wrap'><input id=mapSearch placeholder='بحث...' style='flex:1;min-width:140px;background:#0f1424;border:1px solid #ffffff15;color:#fff;padding:10px 12px;border-radius:12px'><button class=btn-gold onclick="doMapSearch()" style='padding:10px 12px'>بحث</button><button class=btn-gold onclick="locateMe()" style='background:#22c55e;color:#fff;padding:10px 12px'>موقعي</button><button class=btn-gold onclick="enableAddPoint()" id=addPointBtn style='background:#f59e0b;color:#fff;padding:10px 12px'>نقطة</button><span id=coordsLabel style='color:#ffbe4d;font-family:monospace'>-</span></div><div id=map style='height:70vh;min-height:420px;border-radius:16px;background:#0f172a'></div></div><script>
        let _towers={tj}; let _map=null; let addPointMode=false;
        window.doMapSearch=function(){{let q=document.getElementById('mapSearch').value.trim().toLowerCase(); if(!q) return; let f=_towers.find(t=>t.name.toLowerCase().includes(q)||t.area.toLowerCase().includes(q)); if(f&&_map) _map.flyTo([f.lat,f.lng],18);}};
        window.locateMe=function(){{if(_map&&navigator.geolocation) navigator.geolocation.getCurrentPosition(p=>{{_map.flyTo([p.coords.latitude,p.coords.longitude],16); L.marker([p.coords.latitude,p.coords.longitude]).addTo(_map).bindPopup('موقعك').openPopup();}},null,{{enableHighAccuracy:true}});}};
        window.enableAddPoint=function(){{addPointMode=!addPointMode; let b=document.getElementById('addPointBtn'); b.textContent=addPointMode?'اضغط على الخريطة':'نقطة'; if(_map) _map.getContainer().style.cursor=addPointMode?'crosshair':'';}};
        setTimeout(()=>{{_map=L.map('map').setView([35.1318,36.7578],13); L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:19}}).addTo(_map); L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',{{maxZoom:19}}).addTo(_map); _towers.forEach(t=>{{L.marker([t.lat,t.lng]).addTo(_map).bindPopup(t.name+'<br><small>'+t.lat.toFixed(6)+','+t.lng.toFixed(6)+'</small>');}}); _map.on('click',e=>{{let lat6=e.latlng.lat.toFixed(6), lng6=e.latlng.lng.toFixed(6); document.getElementById('coordsLabel').textContent=lat6+','+lng6; if(addPointMode){{L.popup().setLatLng(e.latlng).setContent('<div><b>'+lat6+','+lng6+'</b><br><input id="newPointName" placeholder="اسم" style="width:100%;margin:6px 0;padding:8px"><button onclick="saveNewPoint('+e.latlng.lat+','+e.latlng.lng+')" style="width:100%;background:#ffbe4d;border:0;padding:9px;border-radius:8px;font-weight:800">حفظ</button></div>').openOn(_map);}}}); window.saveNewPoint=async function(lat,lng){{let name=document.getElementById('newPointName').value||'نقطة'; let r=await fetch('/add_tower',{{method:'POST',body:new URLSearchParams({{name:name,area:'',lat:lat.toFixed(6),lng:lng.toFixed(6)}})}}); let j=await r.json(); if(j.ok){{_map.closePopup(); loadPage('towers',true);}}}};}},400);
        </script>'''
    if v=='subs':
        rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 200")
        rows="".join([f"<div class='card' id='sub-{r['id']}' data-name='{esc(r['name'])}' data-phone='{esc(r['phone'] or '')}'><div style='display:flex;justify-content:space-between'><div><b>{esc(r['name'])}</b><br>{esc(r['phone'] or '')}</div><div><button class='btn-gold' onclick=\"openEditSub({r['id']})\">تعديل</button> <button class='btn-del' onclick=\"askDel('/del_sub/{r['id']}',{r['id']},'sub')\">حذف</button></div></div></div>" for r in rs])
        return f"<div style='max-width:700px;margin:0 auto'><div class=card><h3>المشتركين</h3><form id=formSub style='display:flex;gap:6px;flex-wrap:wrap'><input name=name placeholder='الاسم' required style='flex:1'><input name=phone placeholder='رقم' style='flex:1'><input name=note placeholder='ملاحظة' style='flex:1'><button class=btn-gold>إضافة</button></form></div><div style='display:grid;gap:8px'>{rows}</div></div><script>window.openEditSub=function(id){{let c=document.getElementById('sub-'+id);let b=document.getElementById('editBody');b.innerHTML='<input id=edit_s_name value="'+c.dataset.name+'" style="width:100%;padding:12px;margin:6px 0"><input id=edit_s_phone value="'+c.dataset.phone+'" style="width:100%;padding:12px;margin:6px 0"><button onclick="saveSub('+id+')" class=btn-gold style="width:100%;padding:12px">حفظ</button>';document.getElementById('editModal').classList.add('show');}};window.saveSub=async function(id){{let nn=document.getElementById('edit_s_name').value;let pp=document.getElementById('edit_s_phone').value;let r=await fetch('/edit_sub/'+id,{{method:'POST',body:new URLSearchParams({{name:nn,phone:pp,note:''}})}});let j=await r.json();if(j.ok){{closeEditModal();loadPage('subs',true);}}}};document.getElementById('formSub').addEventListener('submit',async e=>{{e.preventDefault();let r=await fetch('/add_sub',{{method:'POST',body:new FormData(e.target)}});let j=await r.json();if(j.ok){{e.target.reset();loadPage('subs',true);}}}});</script>"
    if v=='settings':
        us=qall("SELECT * FROM users ORDER BY phone DESC")
        uh="".join([f'<div class="card" id="user-{esc(u["phone"])}" data-phone="{esc(u["phone"])}" data-role="{esc(u.get("role") or "")}"><div style="display:flex;justify-content:space-between"><div><b>{esc(u.get("username") or "")}</b><br><span style="color:#ffbe4d">{esc(u["phone"])}</span></div><div><button class="btn-gold" onclick="openEditUser(\'{esc(u["phone"])}\')">تعديل</button> <button class="btn-del" onclick="askDel(\'/del_user/{esc(u["phone"])}\',\'{esc(u["phone"])}\',\'user\')">حذف</button></div></div></div>' for u in us])
        return f"<div style='max-width:800px;margin:0 auto'><div class=card><h3>كلمة السر</h3><form id=formPass style='display:flex;gap:8px'><input name=newpass type=password placeholder='جديدة' required style='flex:1'><button class=btn-gold>حفظ</button></form></div><div class=card><h3>إضافة يوزر</h3><form id=formUser style='display:flex;gap:6px;flex-wrap:wrap'><input name=user_field placeholder='رقم / يوزر' required style='flex:1'><input name=password type=password placeholder='كلمة السر' required style='flex:1'><select name=role style='flex:0.5'><option value=tech>فني</option><option value=manager>مدير</option></select><button class=btn-gold>إضافة</button></form></div>{uh}</div><script>window.openEditUser=function(ph){{let c=document.getElementById('user-'+ph);let b=document.getElementById('editBody');b.innerHTML='<input id=edit_u_field value="'+c.dataset.phone+'" style="width:100%;padding:12px"><input id=edit_u_pass type=password placeholder=\"جديدة\" style=\"width:100%;padding:12px;margin-top:8px\"><select id=edit_u_role style=\"width:100%;padding:12px;margin-top:8px\"><option value=tech '+(c.dataset.role=='tech'?'selected':'')+'>فني</option><option value=manager '+(c.dataset.role=='manager'?'selected':'')+'>مدير</option></select><button onclick=\"saveUser(\\''+ph+'\\')\" class=btn-gold style=\"width:100%;padding:12px;margin-top:8px\">حفظ</button>';document.getElementById('editModal').classList.add('show');}};window.saveUser=async function(o){{let f=document.getElementById('edit_u_field').value;let p=document.getElementById('edit_u_pass').value;let r=document.getElementById('edit_u_role').value;let d={{old_phone:o,phone:f,username:f,role:r}}; if(p) d.password=p; let res=await fetch('/edit_user',{{method:'POST',body:new URLSearchParams(d)}}); let j=await res.json(); if(j.ok){{closeEditModal();loadPage('settings',true);}}else alert(j.msg||'خطأ');}};document.getElementById('formPass').addEventListener('submit',async e=>{{e.preventDefault();let r=await fetch('/change_pass',{{method:'POST',body:new FormData(e.target)}});let j=await r.json(); if(j.ok){{e.target.reset();}} else alert(j.msg||'خطأ');}});document.getElementById('formUser').addEventListener('submit',async e=>{{e.preventDefault();let r=await fetch('/add_user',{{method:'POST',body:new FormData(e.target)}});let j=await r.json(); if(j.ok){{e.target.reset();loadPage('settings',true);}} else alert(j.msg||'خطأ');}});</script>"
    return "<div class=card>الصفحة غير موجودة</div>"

def layout(c,v='home'):
    th=session.get('theme','dark'); is_dark=(th=='dark')
    bg='radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 60%, #070a1f 100%)' if is_dark else '#f1f5f9'
    card_bg='rgba(30,36,51,0.9)' if is_dark else '#ffffff'; txt='#ffffff' if is_dark else '#0f172a'; border='#ffffff12' if is_dark else '#e2e8f0'
    cur_user=qone("SELECT * FROM users WHERE phone=?",(session.get('phone') or '',)) or {}
    role=cur_user.get('role') or session.get('role') or 'tech'
    req_lang=session.get('lang','ar'); is_rtl=req_lang=='ar'
    username_display=esc(cur_user.get('username') or session.get('phone') or '')
    sidebar_pos="right:0; left:auto; transform:translateX(110%);" if is_rtl else "left:0; right:auto; transform:translateX(-110%);"
    side="right" if is_rtl else "left"; dir_attr="rtl" if is_rtl else "ltr"
    return f"""<html dir={dir_attr} lang={req_lang}><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<link rel=stylesheet href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'>
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;700;900&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;font-family:'Cairo',system-ui}}body{{margin:0;background:{bg};color:{txt};overflow-x:hidden;direction:{dir_attr}}}
.top{{position:fixed;top:0;left:0;right:0;height:60px;background:rgba(15,23,42,0.92);backdrop-filter:blur(16px);color:#fff;display:flex;align-items:center;justify-content:space-between;padding:0 12px;z-index:1003;border-bottom:1px solid #ffffff12}}
.sidebar{{position:fixed;top:0;width:280px;height:100%;background:linear-gradient(180deg,rgba(15,23,42,0.98) 0%,rgba(7,14,34,1) 100%);backdrop-filter:blur(20px);color:#fff;z-index:1002;padding-top:68px;{sidebar_pos}transition:transform .38s cubic-bezier(0.34, 1.56, 0.64, 1);overflow-y:auto;border-{"left" if is_rtl else "right"}:1px solid #ffffff0f}}
.sidebar.collapsed{{width:78px}} .sidebar.collapsed a span.text{{display:none}} .sidebar.collapsed a{{justify-content:center}}
.sidebar.active{{transform:none}}
.sidebar a{{display:flex;align-items:center;gap:10px;padding:11px 14px;margin:5px 10px;color:#cbd5e1;text-decoration:none;border-radius:12px;background:rgba(255,255,255,0.04);transition:all .38s cubic-bezier(0.34, 1.56, 0.64, 1)}}
.sidebar a.active{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:800}}
.sidebar a:hover{{background:rgba(255,255,255,0.08);transform:translateX(-2px) scale(1.02)}}
.sidebar a:active{{transform:scale(0.95)}}
#overlay{{position:fixed;inset:0;background:#0007;z-index:1001;display:none}}#overlay.show{{display:block}}
.main{{margin-top:70px;padding:12px}}
.card{{background:{card_bg};backdrop-filter:blur(12px);color:{txt};padding:14px;border-radius:16px;margin-bottom:10px;border:1px solid {border};transition:all .38s cubic-bezier(0.34, 1.56, 0.64, 1)}}
.card:hover{{transform:translateY(-2px)}}
.btn-gold{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;padding:8px 14px;border:0;border-radius:10px;font-weight:800;cursor:pointer;transition:.38s cubic-bezier(0.34, 1.56, 0.64, 1)}}
.btn-gold:hover{{transform:scale(1.05)}} .btn-gold:active{{transform:scale(0.9)}}
.btn-del{{background:#ef4444;color:#fff;padding:8px 12px;border:0;border-radius:10px;cursor:pointer;transition:.3s}}
.btn-del:hover{{transform:scale(1.05)}}
#delModal, #editModal{{position:fixed;inset:0;background:#0008;backdrop-filter:blur(6px);display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:.35s;z-index:2000}}
#delModal.show, #editModal.show{{opacity:1;pointer-events:auto}}
#delBox, #editBox{{background:{card_bg};color:{txt};padding:22px;border-radius:18px;width:92%;max-width:440px;transform:scale(0.9);transition:.38s cubic-bezier(0.34, 1.56, 0.64, 1)}}
#delModal.show #delBox, #editModal.show #editBox{{transform:scale(1)}}
.icon-anim{{transition:.38s cubic-bezier(0.34, 1.56, 0.64, 1)}} .icon-anim:active{{transform:scale(0.85)}}
</style></head><body>
<div id=overlay onclick="toggleSb(false)"></div>
<div class=sidebar id=sb>
<div style='padding:0 16px 12px;border-bottom:1px solid #ffffff0a;display:flex;justify-content:space-between;align-items:center'><div><div style='font-weight:900'>OMAIA <span style='color:#ffbe4d'>ISP</span></div><small style='color:#888'>{username_display}</small></div><button onclick="toggleCollapse()" id=collapseBtn style='background:#ffffff10;border:1px solid #ffffff15;color:#fff;width:32px;height:32px;border-radius:8px;cursor:pointer' class=icon-anim>◀</button></div>
<a href="javascript:loadPage('home')" id=nav-home>🏠 <span class=text>الرئيسية</span></a>
<a href="javascript:loadPage('dishes')" id=nav-dishes>📡 <span class=text>الصحون</span></a>
<a href="javascript:loadPage('towers')" id=nav-towers>🗼 <span class=text>الأبراج</span></a>
<a href="javascript:loadPage('map')" id=nav-map>🗺 <span class=text>الخريطة</span></a>
<a href="javascript:loadPage('subs')" id=nav-subs>👥 <span class=text>المشتركين</span></a>
<a href="javascript:loadPage('logs')" id=nav-logs>📜 <span class=text>السجل</span></a>
<a href="javascript:loadPage('settings')" id=nav-settings>⚙ <span class=text>الإعدادات</span></a>
<a href="javascript:logoutFast()" style='margin-top:12px;background:#ef444418'>🚪 <span class=text>خروج</span></a>
</div>
<div class=top>
<div style='display:flex;gap:8px;align-items:center'><span onclick="toggleSb()" style='font-size:20px;cursor:pointer;padding:6px 9px;background:#ffffff0a;border-radius:10px' class=icon-anim>☰</span><input id=topsearch placeholder='بحث...' oninput="globalSearchTop(this.value)" style='background:#1f2937;border:1px solid #ffffff15;color:#fff;padding:7px 11px;border-radius:10px;width:42px;transition:.38s' onfocus="this.style.width='180px'"></div>
<div style='font-weight:900'>OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<div style='display:flex;gap:6px'><button onclick="toggleThemeNoReload()" style='background:#ffffff0a;color:#fff;border:1px solid #ffffff0f;padding:7px 10px;border-radius:10px' class=icon-anim>🌓</button><button onclick="toggleLangNoReload()" style='background:#ffffff0a;color:#fff;border:1px solid #ffffff0f;padding:7px 10px;border-radius:10px' class=icon-anim>🌐</button></div>
</div>
<div id=searchResults style='position:fixed;top:64px;{side}:10px;max-width:400px;width:92%;background:rgba(30,36,51,0.96);backdrop-filter:blur(16px);border:1px solid #ffffff15;border-radius:14px;z-index:1500;display:none;max-height:60vh;overflow:auto'></div>
<div class=main id=mn>{c}</div>
<div id=delModal><div id=delBox><div style='font-size:32px;text-align:center'>🗑️</div><h3 style='text-align:center;margin:10px 0'>تأكيد الحذف؟</h3><div style='display:flex;gap:10px;margin-top:14px'><button onclick="closeDel()" style='flex:1;padding:11px;border-radius:12px;background:transparent;color:{txt};border:1px solid {border}'>تراجع</button><button id=delYes style='flex:1;padding:11px;border-radius:12px;background:#ef4444;color:#fff;border:0;font-weight:800'>حذف</button></div></div></div>
<div id=editModal><div id=editBox><div style='display:flex;justify-content:space-between;margin-bottom:12px'><h3 style='margin:0'>تعديل</h3><button onclick="closeEditModal()" style='background:#ffffff12;border:0;color:{txt};width:32px;height:32px;border-radius:50%'>✕</button></div><div id=editBody></div></div></div>
<script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>
<script>
let cur='{v}';
let sidebarCollapsed = localStorage.getItem('omaia_collapsed')==='1';
function applyCollapse(){{let sb=document.getElementById('sb'); if(sidebarCollapsed) sb.classList.add('collapsed'); else sb.classList.remove('collapsed'); let b=document.getElementById('collapseBtn'); if(b) b.textContent=sidebarCollapsed?'▶':'◀';}}
applyCollapse();
function toggleCollapse(){{sidebarCollapsed=!sidebarCollapsed; localStorage.setItem('omaia_collapsed', sidebarCollapsed?'1':'0'); applyCollapse();}}
function toggleSb(f){{let sb=document.getElementById('sb'),ov=document.getElementById('overlay'); let o=f!==undefined?f:!sb.classList.contains('active'); sb.classList.toggle('active',o); ov.classList.toggle('show',o);}}
let pageCache={{}}; try{{pageCache=JSON.parse(localStorage.getItem('omaia_cache_clean')||'{{}}');}}catch(e){{pageCache={{}};}}
function saveCache(){{try{{localStorage.setItem('omaia_cache_clean',JSON.stringify(pageCache));}}catch(e){{}}}}
async function loadPage(v,force=false,push=true){{
  if(push&&cur!==v){{try{{history.pushState({{page:v}},'', '/dash?v='+v);}}catch(e){{}}}}
  cur=v; toggleSb(false); document.querySelectorAll('.sidebar a').forEach(a=>a.classList.remove('active')); let n=document.getElementById('nav-'+v); if(n) n.classList.add('active');
  let mn=document.getElementById('mn');
  if(!force&&pageCache[v]){{mn.innerHTML=pageCache[v]; execScripts(); fetch('/api/page?v='+v,{{cache:'no-store'}}).then(r=>r.text()).then(h=>{{pageCache[v]=h; saveCache();}}).catch(()=>{{}}); return;}}
  mn.innerHTML='<div class=card style="text-align:center;padding:24px">جاري التحميل...</div>';
  try{{let r=await fetch('/api/page?v='+v,{{cache:'no-store'}}); let h=await r.text(); pageCache[v]=h; saveCache(); mn.innerHTML=h; execScripts();}}catch(e){{mn.innerHTML='<div class=card>خطأ: '+e+'</div>';}}
}}
function execScripts(){{let mn=document.getElementById('mn'); mn.querySelectorAll('script').forEach(old=>{{let s=document.createElement('script'); s.textContent=old.textContent; document.body.appendChild(s); s.remove();}});}}
function askDel(url,id,type){{window._delUrl=url; window._delId=id; window._delType=type; document.getElementById('delModal').classList.add('show');}}
function closeDel(){{document.getElementById('delModal').classList.remove('show'); window._delUrl=null;}}
window.closeEditModal=function(){{document.getElementById('editModal').classList.remove('show');}};
document.getElementById('delYes').onclick=async()=>{{
  if(!window._delUrl) return; let btn=document.getElementById('delYes'); let o=btn.textContent; btn.textContent='جاري...'; btn.disabled=true;
  try{{if(window._delId){{let el=document.getElementById((window._delType||'dish')+'-'+window._delId); if(el){{el.style.transform='scale(0.9)'; el.style.opacity='0'; setTimeout(()=>el.style.display='none',350);}}}} document.getElementById('delModal').classList.remove('show'); let r=await fetch(window._delUrl); let j=await r.json(); if(!j.ok){{alert(j.msg||'خطأ'); location.reload();}} else {{delete pageCache[cur];}}}}catch(e){{alert(e);}} btn.textContent=o; btn.disabled=false;
}};
async function toggleThemeNoReload(){{await fetch('/toggle_theme'); location.reload();}}
async function toggleLangNoReload(){{let r=await fetch('/toggle_lang'); let j=await r.json(); loadPage(cur,true,false); document.documentElement.dir=j.lang==='ar'?'rtl':'ltr';}}
window.globalSearchTop=async function(q){{let box=document.getElementById('searchResults'); if(!q||q.length<2){{box.style.display='none'; return;}} let r=await fetch('/api/search?q='+encodeURIComponent(q)); let d=await r.json(); if(!d.length){{box.style.display='none'; return;}} let h=''; d.forEach(x=>{{h+='<div onclick="loadPage(\\''+x.page+'\\');document.getElementById(\\'searchResults\\').style.display=\\'none\\'" style="padding:10px 12px;cursor:pointer;border-bottom:1px solid #ffffff08"><b>'+x.title+'</b><br><small style="color:#888">'+x.sub+'</small></div>';}}); box.innerHTML=h; box.style.display='block';}};
window.logoutFast=async function(){{await fetch('/api/logout',{{method:'POST'}}); try{{localStorage.removeItem('omaia_cache_clean');}}catch(e){{}} location.replace('/login');}};
loadPage(cur,true,false);
</script></body></html>"""

if __name__=='__main__':
    port=int(os.environ.get("PORT",10000))
    print(f"OMAIA ISP CLEAN running on {port}")
    app.run(host='0.0.0.0',port=port,debug=False)
