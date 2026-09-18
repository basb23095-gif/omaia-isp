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
app.secret_key=os.environ.get("SECRET_KEY","omia-sec-2026-final-v3")
app.config['PERMANENT_SESSION_LIFETIME']=datetime.timedelta(minutes=45)
app.config['SESSION_PERMANENT']=False

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
        except Exception as e:
            print(e)
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
            _sqlite_conn=sqlite3.connect("omia.db",check_same_thread=False,timeout=10, isolation_level=None)
            _sqlite_conn.row_factory=sqlite3.Row
            try:
                _sqlite_conn.execute("PRAGMA journal_mode=WAL;")
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
        print("[qall]",e)
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
        print("[qexec]",e,q)
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
    except:
        pass

def get_counts():
    with _cache_lock:
        c=_cache.get('counts')
        if c and time.time()-c[1]<15:
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
        "CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,area TEXT,lat REAL,lng REAL)",
        "CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,user_phone TEXT,action TEXT,detail TEXT,time TEXT)",
        "CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,msg TEXT,time TEXT,read INTEGER DEFAULT 0)"
    ]
    if USE_PG:
        ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
    for s in ss:
        qexec(s)
    for alter in ["ALTER TABLE dish_ips ADD COLUMN tower_id INTEGER","ALTER TABLE dish_ips ADD COLUMN IF NOT EXISTS tower_id INTEGER"]:
        try:
            qexec(alter)
        except:
            pass
    for idx in ["CREATE INDEX IF NOT EXISTS idx_dish_ip ON dish_ips(ip)","CREATE INDEX IF NOT EXISTS idx_dish_tower ON dish_ips(tower_id)","CREATE INDEX IF NOT EXISTS idx_logs_id ON logs(id DESC)","CREATE INDEX IF NOT EXISTS idx_towers_name ON towers(name)"]:
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
        qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",('نقطة حماة الرئيسية','حماة',35.1318,36.7578))

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
        resp.headers['Cache-Control']='no-store'
    else:
        resp.headers['Cache-Control']='no-cache'
    return resp

@app.route('/ping')
@app.route('/health')
def public_ping():
    return jsonify(ok=True,time=datetime.datetime.now().isoformat())

@app.route('/api/ping')
@login_required
def api_ping():
    ip=request.args.get('ip','').strip()
    if not ip:
        return jsonify(ok=False,out='لا يوجد IP')
    if not is_valid_ip(ip):
        return jsonify(ok=False,out='IP غير صالح')
    for port in [80,443,8080,8291,22,8728,8000]:
        s=None
        try:
            s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
            s.settimeout(0.6)
            if s.connect_ex((ip,port))==0:
                s.close()
                return jsonify(ok=True,out='متصل '+ip+':'+str(port),port=port)
            s.close()
        except:
            try:
                if s:
                    s.close()
            except:
                pass
    try:
        cmd=['ping','-c','1','-W','1',ip] if platform.system().lower()!='windows' else ['ping','-n','1','-w','1000',ip]
        out=subprocess.check_output(cmd,timeout=1.2,stderr=subprocess.STDOUT).decode(errors='ignore')
        ok='ttl=' in out.lower() or 'bytes from' in out.lower()
        if ok:
            m=re.search(r'time[=<]\s*(\d+\.?\d*)',out,re.I)
            ms=m.group(1) if m else ''
            return jsonify(ok=True,out=ip+' '+ms+'ms',ms=ms)
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
    s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    s.settimeout(0.9)
    try:
        r=s.connect_ex((ip,port))
        s.close()
        return jsonify(ok=r==0,out=ip+':'+str(port)+' مفتوح' if r==0 else 'مغلق')
    except Exception as e:
        try:
            s.close()
        except:
            pass
        return jsonify(ok=False,out=str(e))

@app.route('/api/notifications')
@login_required
def api_noti():
    rows=qall("SELECT * FROM notifications ORDER BY id DESC LIMIT 30")
    cnt=(qone("SELECT COUNT(*) c FROM notifications WHERE read=0") or {}).get('c',0)
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
    return jsonify(dishes=len(dishes),towers=len(towers))

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
    u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
    if u and check_password_hash(u['password'],pw):
        session.clear()
        session['phone']=u['phone']
        session['username']=u.get('username') or u['phone']
        session['role']=u.get('role') or 'tech'
        session.permanent=False
        try:
            threading.Thread(target=add_log,args=(u['phone'],'دخل النظام','login'),daemon=True).start()
        except:
            pass
        return jsonify(ok=True)
    return jsonify(ok=False,msg='خطأ بالدخول'),401

@app.route('/api/export/<tbl>')
@login_required
def api_export(tbl):
    output=io.StringIO()
    output.write('\ufeff')
    w=csv.writer(output)
    if tbl=='dishes':
        rows=qall("SELECT * FROM dish_ips ORDER BY id DESC")
        w.writerow(['ID','اسم','IP','موقع','tower_id'])
        for r in rows:
            w.writerow([r['id'],r.get('dish_name',''),r.get('ip',''),r.get('location',''),r.get('tower_id','')])
        fname='dishes.csv'
    elif tbl=='towers':
        rows=qall("SELECT * FROM towers ORDER BY id DESC")
        w.writerow(['ID','اسم','منطقة','lat','lng'])
        for r in rows:
            w.writerow([r['id'],r.get('name',''),r.get('area',''),r.get('lat',''),r.get('lng','')])
        fname='towers.csv'
    elif tbl=='logs':
        rows=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 2000")
        w.writerow(['ID','يوزر','عمل','تفصيل','وقت'])
        for r in rows:
            w.writerow([r['id'],r.get('user_phone',''),r.get('action',''),r.get('detail',''),r.get('time','')])
        fname='logs.csv'
    elif tbl=='subs':
        rows=qall("SELECT * FROM subs ORDER BY id DESC")
        w.writerow(['ID','اسم','رقم','ملاحظة'])
        for r in rows:
            w.writerow([r['id'],r.get('name',''),r.get('phone',''),r.get('note','')])
        fname='subs.csv'
    elif tbl=='ledger':
        rows=qall("SELECT * FROM ledger ORDER BY id DESC")
        w.writerow(['ID','اسم','مبلغ','ملاحظة'])
        for r in rows:
            w.writerow([r['id'],r.get('name',''),r.get('amount',''),r.get('note','')])
        fname='ledger.csv'
    elif tbl=='users':
        rows=qall("SELECT phone,username,role FROM users ORDER BY phone DESC")
        w.writerow(['يوزر','اسم','رتبة'])
        for r in rows:
            w.writerow([r.get('phone',''),r.get('username',''),r.get('role','')])
        fname='users.csv'
    else:
        w.writerow(['data'])
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
    qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)",(session.get('phone','test'),'اختبار','سجل شغال',now))
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
<style>*{box-sizing:border-box;font-family:system-ui}body{margin:0;min-height:100vh;background:radial-gradient(120% 120% at 10% 10%,#1a2344 0%,#0a0e2a 60%,#070a1f 100%);display:flex;align-items:center;justify-content:center;color:#fff}
.card{background:linear-gradient(180deg,#222b45ee,#1a2035ee);border:1px solid #ffffff18;padding:28px;border-radius:22px;width:92%;max-width:380px;animation:fadeUp .7s cubic-bezier(.16,1,.3,1)}
@keyframes fadeUp{from{opacity:0;transform:translateY(20px) scale(.98)}to{opacity:1;transform:translateY(0) scale(1)}}
input{width:100%;padding:14px;margin:8px 0;background:#0f1424;border:1px solid #ffffff22;color:#fff;border-radius:14px}
.btn{width:100%;padding:14px;border:0;border-radius:14px;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:900;cursor:pointer;transition:transform .6s cubic-bezier(.16,1,.3,1)}.btn:active{transform:scale(.94)}
</style></head><body>
<div class=card><div style='font-weight:900;font-size:28px;text-align:center;margin-bottom:16px'>OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<form id=loginForm><input name=userin id=userin placeholder='يوزر / رقم' required autofocus><input name=password type=password placeholder='باسورد' required><button class=btn>دخول</button><div id=msg style='text-align:center;color:#ff6b6b;margin-top:10px;min-height:18px'></div></form></div>
<script>
document.getElementById('loginForm').addEventListener('submit',async e=>{
 e.preventDefault(); let btn=e.target.querySelector('.btn'); let orig=btn.textContent; btn.textContent='...'; btn.disabled=true;
 try{ let r=await fetch('/api/login_public',{method:'POST',body:new FormData(e.target),cache:'no-store'}); let j=await r.json(); if(j.ok){location.replace('/dash?v=home');} else {document.getElementById('msg').textContent=j.msg||'خطأ'; btn.textContent=orig; btn.disabled=false;}}catch(err){document.getElementById('msg').textContent='شبكة'; btn.textContent=orig; btn.disabled=false;}
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
    return layout('<div class=card>...</div>',v)

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
            results.append({"title":r.get('dish_name') or r.get('ip'),"sub":r.get('ip',''),"page":"dishes","type":"dish"})
        for r in qall("SELECT * FROM towers WHERE name "+op+" ? OR area "+op+" ? ORDER BY id DESC LIMIT 20",(like,like)):
            results.append({"title":r.get('name',''),"sub":r.get('area',''),"page":"towers","type":"tower"})
        for r in qall("SELECT * FROM subs WHERE name "+op+" ? OR phone "+op+" ? ORDER BY id DESC LIMIT 10",(like,like)):
            results.append({"title":r.get('name',''),"sub":r.get('phone',''),"page":"subs"})
        for r in qall("SELECT * FROM users WHERE phone "+op+" ? OR username "+op+" ? LIMIT 10",(like,like)):
            results.append({"title":r.get('username') or r.get('phone',''),"sub":r.get('phone',''),"page":"settings"})
    except:
        pass
    return jsonify(results[:30])

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
        add_log(session.get('phone'),'إضافة صحن',name+" "+ip)
        with _cache_lock:
            _cache.pop('counts',None)
    return jsonify(ok=ok)

@app.route('/edit_dish/<int:i>',methods=['POST'])
@login_required
def ed(i):
    if not is_manager():
        return jsonify(ok=False),403
    data=request.json if request.is_json else request.form
    ok=qexec("UPDATE dish_ips SET dish_name=?,ip=?,location=?,tower_id=? WHERE id=?",(data.get('dish_name',''),data.get('ip',''),data.get('location',''), data.get('tower_id') or None, i))
    if ok:
        add_log(session.get('phone'),'تعديل صحن',"ID "+str(i))
    return jsonify(ok=ok)

@app.route('/del_dish/<int:i>')
@login_required
def dd(i):
    if not is_manager():
        return jsonify(ok=False),403
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
    ok=qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",(data.get('name','كرت جديد'),data.get('area',''),la,ln))
    if ok:
        add_log(session.get('phone'),'إضافة برج',str(data.get('name','')))
    return jsonify(ok=ok)

@app.route('/del_tower/<int:i>')
@login_required
def dt(i):
    if not is_manager():
        return jsonify(ok=False),403
    qexec("UPDATE dish_ips SET tower_id=NULL WHERE tower_id=?",(i,))
    ok=qexec("DELETE FROM towers WHERE id=?",(i,))
    if ok:
        add_log(session.get('phone'),'حذف برج',"ID "+str(i))
    return jsonify(ok=ok)

@app.route('/edit_tower/<int:i>',methods=['POST'])
@login_required
def et(i):
    if not is_manager():
        return jsonify(ok=False),403
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
    ok=qexec("INSERT INTO subs(name,phone,note) VALUES(?,?,?)",(request.form.get('name',''),request.form.get('phone',''),request.form.get('note','')))
    if ok:
        add_log(session.get('phone'),'إضافة مشترك',request.form.get('name',''))
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
    data=request.form if request.form else request.json or {}
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
        return jsonify(ok=False,msg='مطلوب'),400
    if qone("SELECT * FROM users WHERE phone=?",(ph,)):
        return jsonify(ok=False,msg='موجود'),400
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
        return jsonify(ok=False),400
    if old!=new_ph and qone("SELECT * FROM users WHERE phone=?",(new_ph,)):
        return jsonify(ok=False,msg='موجود'),400
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
        return jsonify(ok=False,msg='ممنوع'),400
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
        return jsonify(ok=False),400
    ok=qexec("UPDATE users SET password=? WHERE phone=?",(generate_password_hash(np),session.get('phone')))
    if ok:
        add_log(session.get('phone'),'تغيير كلمة سر','')
    return jsonify(ok=ok)

def page_content(v):
    lang=session.get('lang','ar')
    def L(ar,en):
        return ar if lang=='ar' else en
    if v=='home':
        ns,nd,nt,nl=get_counts()
        logs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 10")
        log_html=""
        for l in logs:
            log_html+="<div class=rowlog><div><b>"+esc(l.get('user_phone',''))+"</b> <span class=badge>"+esc(l.get('action',''))+"</span> <small>"+esc(str(l.get('detail',''))[:80])+"</small></div><small class=time>"+esc(l.get('time',''))+"</small></div>"
        return "<div class=grid2><div class='card stat' onclick=\"loadPage('subs')\"><h3>"+L('المشتركين','Subs')+"</h3><h2>"+str(ns)+"</h2><div class=ico>👥</div></div><div class='card stat' onclick=\"loadPage('dishes')\"><h3>"+L('الصحون','Dishes')+"</h3><h2>"+str(nd)+"</h2><div class=ico>📡</div></div><div class='card stat' onclick=\"loadPage('towers')\"><h3>"+L('الأبراج','Towers')+"</h3><h2>"+str(nt)+"</h2><div class=ico>🗼</div></div><div class='card stat' onclick=\"loadPage('ledger')\"><h3>"+L('الحسابات','Accounts')+"</h3><h2>"+str(nl)+"</h2><div class=ico>📒</div></div></div><div class=card><div class=row style='justify-content:space-between'><b>"+L('آخر النشاطات','Activity')+"</b><div class=row><button class=btn-gold onclick=\"fetch('/api/seed_log',{method:'POST'}).then(()=>loadPage('home',true))\">اختبار</button><button class=btn-gold onclick=\"loadPage('logs')\">الكل</button></div></div><div style='margin-top:8px'>"+(log_html or "<small>-</small>")+"</div></div>"
    if v=='dishes':
        rs=qall("SELECT * FROM dish_ips ORDER BY id DESC")
        rows=""
        for r in rs:
            tower_info=" • برج "+str(r.get('tower_id')) if r.get('tower_id') else ""
            rows+='<div class="card dish-card" id="dish-'+str(r['id'])+'" data-ip="'+esc(r.get('ip',''))+'" data-name="'+esc(r.get('dish_name') or '')+'" data-loc="'+esc(r.get('location') or '')+'"><div><b>'+esc(r.get('dish_name') or 'صحن')+'</b><br><span class=ip>'+esc(r.get('ip',''))+'</span><br><small>'+esc(r.get('location',''))+esc(tower_info)+'</small></div><div class=col><button class=btn-gold onclick="quickPingD('+str(r['id'])+')">Ping</button><div class=row><button class=btn-gold onclick="editDish('+str(r['id'])+')">✏️</button><button class=btn-del onclick="askDel(\'/del_dish/'+str(r['id'])+'\','+str(r['id'])+')">🗑</button></div></div></div>'
        return '<div class=card><div class=row style="justify-content:space-between"><h3>الصحون - '+str(len(rs))+'</h3><a href="/api/export/dishes" class=btn-gold>Excel</a></div><form id=formDish class=row style="margin-top:8px"><input name=dish_name placeholder="اسم الصحن" required style="flex:1"><input name=ip placeholder="IP" required style="flex:1"><input name=location placeholder="موقع" style="flex:1"><button class=btn-gold>إضافة</button></form><input id=searchBox placeholder="بحث..." oninput="filterDishes(this.value)" style="margin-top:10px"></div><div id=dl>'+rows+'</div><script>window.filterDishes=q=>{q=q.toLowerCase();document.querySelectorAll(".dish-card").forEach(c=>{c.style.display=c.textContent.toLowerCase().includes(q)?"flex":"none"})};window.editDish=id=>{let c=document.getElementById("dish-"+id); let body=document.getElementById("editBody"); body.innerHTML="<input id=edn value=\""+c.dataset.name+"\"><input id=edi value=\""+c.dataset.ip+"\"><input id=edl value=\""+c.dataset.loc+"\"><button class=btn-gold onclick=\"saveDish("+id+")\">حفظ</button>"; document.getElementById("editModal").classList.add("show");};window.saveDish=id=>{fetch("/edit_dish/"+id,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({dish_name:document.getElementById("edn").value,ip:document.getElementById("edi").value,location:document.getElementById("edl").value})}).then(r=>r.json()).then(j=>{if(j.ok){closeEditModal(); loadPage("dishes",true)}})};window.quickPingD=id=>{let ip=document.getElementById("dish-"+id).dataset.ip; loadPage("ping"); setTimeout(()=>{let el=document.getElementById("pingIp"); if(el){el.value=ip; doSinglePing()}},350)};document.getElementById("formDish").addEventListener("submit",e=>{e.preventDefault(); let fd=new FormData(e.target); fetch("/add_dish",{method:"POST",body:fd}).then(r=>r.json()).then(j=>{if(j.ok){e.target.reset(); loadPage("dishes",true)} else alert(j.msg||"خطأ")})});</script>'
    if v=='towers':
        towers=qall("SELECT * FROM towers ORDER BY id DESC")
        cards=""
        for t in towers:
            tid=t['id']
            dishes=qall("SELECT * FROM dish_ips WHERE tower_id=? ORDER BY id DESC",(tid,))
            dish_html=""
            for d in dishes:
                dish_html+="<div class=dish-mini><div><b>"+esc(d.get('dish_name') or 'صحن')+"</b> <span class=ip>"+esc(d.get('ip'))+"</span><br><small>"+esc(d.get('location') or '')+"</small></div><button class=btn-del onclick=\"delDishInTower("+str(d['id'])+","+str(tid)+")\">✕</button></div>"
            if not dish_html:
                dish_html="<small style='color:#777'>فاضي - ضيف IP</small>"
            cards+='<div class="card tower-card" id="tower-'+str(tid)+'" data-name="'+esc(t['name'])+'" data-area="'+esc(t.get('area') or '')+'" data-lat="'+str(t.get('lat'))+'" data-lng="'+str(t.get('lng'))+'"><div class=tower-head><div><b class=tower-title>'+esc(t['name'])+'</b><br><small>'+esc(t.get('area') or '')+'</small><br><small class=coords>'+str(t.get('lat'))+','+str(t.get('lng'))+'</small></div><div class=col><button class=btn-gold onclick="openEditTower('+str(tid)+')">✏️</button><button class=btn-del onclick="askDel(\'/del_tower/'+str(tid)+'\','+str(tid)+')">🗑</button><button class=btn-gold onclick="focusMap('+str(t.get('lat'))+','+str(t.get('lng'))+')">🗺</button></div></div><div class=tower-body><div class=row><input id="ip-'+str(tid)+'" placeholder="IP"><input id="name-'+str(tid)+'" placeholder="اسم الصحن"><button class=btn-gold onclick="addDishToTower('+str(tid)+')">+ IP</button></div><div class=dish-list id="list-'+str(tid)+'">'+dish_html+'</div></div></div>'
        return '<div class=card><div class=row style="justify-content:space-between"><h3>الأبراج - كروت لا نهائية - '+str(len(towers))+'</h3><div class=row><button class=btn-gold onclick="openNewTower()" style="background:#22c55e;color:#fff">+ كرت جديد</button><a href="/api/export/towers" class=btn-gold>Excel</a></div></div></div><div class=grid2>'+cards+'</div><script>window.openNewTower=()=>{let body=document.getElementById("editBody"); body.innerHTML="<input id=nt_name placeholder=\"اسم الكرت\" value=\"كرت جديد\"><input id=nt_area placeholder=\"منطقة\"><div class=row><input id=nt_lat placeholder=\"lat\" value=\"35.1318\"><input id=nt_lng placeholder=\"lng\" value=\"36.7578\"></div><button class=btn-gold onclick=\"saveNewTower()\" style=\"width:100%;margin-top:8px\">حفظ</button>"; document.getElementById("editModal").classList.add("show");};window.saveNewTower=()=>{fetch("/add_tower",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:document.getElementById("nt_name").value,area:document.getElementById("nt_area").value,lat:document.getElementById("nt_lat").value,lng:document.getElementById("nt_lng").value})}).then(r=>r.json()).then(j=>{if(j.ok){closeEditModal(); loadPage("towers",true)}})};window.openEditTower=id=>{let c=document.getElementById("tower-"+id); let body=document.getElementById("editBody"); body.innerHTML="<input id=et_name value=\""+c.dataset.name+"\"><input id=et_area value=\""+c.dataset.area+"\"><div class=row><input id=et_lat value=\""+c.dataset.lat+"\"><input id=et_lng value=\""+c.dataset.lng+"\"></div><button class=btn-gold onclick=\"saveTower("+id+")\" style=\"width:100%\">حفظ</button>"; document.getElementById("editModal").classList.add("show");};window.saveTower=id=>{fetch("/edit_tower/"+id,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:document.getElementById("et_name").value,area:document.getElementById("et_area").value,lat:document.getElementById("et_lat").value,lng:document.getElementById("et_lng").value})}).then(()=>{closeEditModal(); loadPage("towers",true)})};window.addDishToTower=tid=>{let ip=document.getElementById("ip-"+tid).value.trim(); let nm=document.getElementById("name-"+tid).value.trim(); if(!ip) return alert("IP"); fetch("/api/add_dish_to_tower",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({ip:ip,dish_name:nm,tower_id:tid})}).then(r=>r.json()).then(j=>{if(j.ok) loadPage("towers",true); else alert(j.msg||"خطأ")})};window.delDishInTower=(did,tid)=>{fetch("/del_dish/"+did).then(r=>r.json()).then(j=>{if(j.ok) loadPage("towers",true)})};window.focusMap=(lat,lng)=>{loadPage("map"); setTimeout(()=>{if(window._map) window._map.flyTo([lat,lng],18)},600)};</script>'
    if v=='map':
        towers=qall("SELECT * FROM towers ORDER BY id DESC")
        tj=json.dumps([{"id":t['id'],"name":t['name'],"area":t.get('area') or '',"lat":float(t.get('lat') or 35.1318),"lng":float(t.get('lng') or 36.7578)} for t in towers],ensure_ascii=False)
        return '<div class=card style="padding:10px"><div class=row style="flex-wrap:wrap"><input id=mapSearch placeholder="بحث برج..." style="flex:1;min-width:140px"><button class=btn-gold onclick="doMapSearch()">بحث</button><button class=btn-gold onclick="locateMe()" style="background:#22c55e;color:#fff">موقعي</button><button class=btn-gold id=addPointBtn onclick="enableAddPoint()" style="background:#f59e0b">نقطة</button><button class=btn-gold onclick="toggleMeasure()" id=measureBtn style="background:#0ea5e9">قياس</button><button class=btn-del onclick="clearMap()">مسح</button><span id=distanceLabel class=ip>0 كم</span></div><div id=map style="height:76vh;border-radius:16px;margin-top:10px;z-index:1"></div><div class=row style="margin-top:6px"><small id=coordsLabel style="color:#ffbe4d">-</small><small style="color:#666">اسحب العلامة لتثبيت احداثيات • دقة عالية حتى زوم 22</small></div></div><script>let _towers='+tj+'; window._map=null; let measureMode=false,addPointMode=false,measurePoints=[],measureLine=null,measureMarkers=[],markersById={};window.doMapSearch=()=>{let q=document.getElementById("mapSearch").value.trim().toLowerCase(); if(!q) return; let f=_towers.find(t=>t.name.toLowerCase().includes(q)||t.area.toLowerCase().includes(q)); if(f&&window._map) window._map.flyTo([f.lat,f.lng],18);};window.locateMe=()=>{if(navigator.geolocation) navigator.geolocation.getCurrentPosition(p=>{window._map.flyTo([p.coords.latitude,p.coords.longitude],17); L.marker([p.coords.latitude,p.coords.longitude]).addTo(window._map).bindPopup("موقعك").openPopup();});};window.enableAddPoint=()=>{addPointMode=!addPointMode; document.getElementById("addPointBtn").textContent=addPointMode?"اضغط على الخريطة":"نقطة"; window._map.getContainer().style.cursor=addPointMode?"crosshair":""; if(addPointMode) measureMode=false;};window.toggleMeasure=()=>{measureMode=!measureMode; document.getElementById("measureBtn").textContent=measureMode?"إلغاء القياس":"قياس"; window._map.getContainer().style.cursor=measureMode?"crosshair":""; if(measureMode) addPointMode=false;};window.clearMap=()=>{measurePoints=[]; if(measureLine) window._map.removeLayer(measureLine); measureMarkers.forEach(m=>window._map.removeLayer(m)); measureMarkers=[]; document.getElementById("distanceLabel").textContent="0 كم";};setTimeout(()=>{window._map=L.map("map",{zoomControl:true,maxZoom:22}).setView([35.1318,36.7578],13); let osm=L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",{maxZoom:22,maxNativeZoom:19}).addTo(window._map); let sat=L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",{maxZoom:22,maxNativeZoom:19,attribution:"Esri High-Res"}).addTo(window._map); let topo=L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",{maxZoom:22}); L.control.layers({"عادية":osm,"قمر صناعي دقة عالية 22":sat,"تضاريس":topo}).addTo(window._map); setTimeout(()=>window._map.invalidateSize(),400); _towers.forEach(t=>{let m=L.marker([t.lat,t.lng],{draggable:true}).addTo(window._map).bindPopup("<b>"+t.name+"</b><br>"+t.area+"<br><small>"+t.lat+","+t.lng+"</small>"); markersById[t.id]=m; m.on("dragend",e=>{let ll=e.target.getLatLng(); document.getElementById("coordsLabel").textContent=ll.lat.toFixed(6)+","+ll.lng.toFixed(6)+" - جاري الحفظ..."; fetch("/api/update_tower_pos",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:t.id,lat:ll.lat,lng:ll.lng})}).then(r=>r.json()).then(j=>{document.getElementById("coordsLabel").textContent=ll.lat.toFixed(6)+","+ll.lng.toFixed(6)+" ✓ تم التثبيت";});});}); window._map.on("click",e=>{document.getElementById("coordsLabel").textContent=e.latlng.lat.toFixed(6)+","+e.latlng.lng.toFixed(6); if(measureMode){measurePoints.push(e.latlng); let mk=L.marker(e.latlng).addTo(window._map); measureMarkers.push(mk); if(measureLine) window._map.removeLayer(measureLine); if(measurePoints.length>1){measureLine=L.polyline(measurePoints,{color:"#ffbe4d",weight:4,dashArray:"8,8"}).addTo(window._map); let d=0; for(let i=1;i<measurePoints.length;i++) d+=measurePoints[i-1].distanceTo(measurePoints[i]); document.getElementById("distanceLabel").textContent=(d/1000).toFixed(3)+" كم";} return;} if(addPointMode){let lat=e.latlng.lat, lng=e.latlng.lng; L.popup().setLatLng(e.latlng).setContent("<div><b>كرت جديد</b><br><input id=np_name placeholder=\"اسم الكرت\" style=\"width:100%;margin:4px 0\"><input id=np_area placeholder=\"منطقة\" style=\"width:100%;margin:4px 0\"><button class=btn-gold onclick=\"saveNewPoint("+lat+","+lng+")\" style=\"width:100%\">حفظ</button></div>").openOn(window._map);}}); window.saveNewPoint=(lat,lng)=>{let n=document.getElementById("np_name").value||"كرت جديد"; let a=document.getElementById("np_area").value||""; fetch("/add_tower",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:n,area:a,lat:lat,lng:lng})}).then(r=>r.json()).then(j=>{window._map.closePopup(); if(j.ok){let m=L.marker([lat,lng],{draggable:true}).addTo(window._map).bindPopup(n);} alert("تم ✓");});};},350);</script>'
    if v=='ping':
        return '''<div class=card><h3>📶 Ping</h3><div class=row><input id=pingIp placeholder='192.168.1.1' style='flex:1'><input id=pingPort value=80 style='width:80px'><button class=btn-gold onclick="doSinglePing()" style='background:#22c55e;color:#fff'>Ping</button><button class=btn-gold onclick="doTcpPing()" style='background:#0ea5e9;color:#fff'>TCP</button></div><div id=pingResult class=pingBox>جاهز</div><div class=row style='margin-top:8px'><button class=btn-gold onclick="pingAllDishes()" style='background:#ffbe4d;color:#111;flex:1'>فحص كل الصحون</button><button class=btn-gold onclick="clearPing()">مسح</button></div></div><div class=card id=quickDishes>...</div><script>window.doSinglePing=async()=>{let ip=document.getElementById("pingIp").value.trim(); if(!ip) return; let out=document.getElementById("pingResult"); out.textContent="جاري "+ip+"..."; try{let r=await fetch("/api/ping?ip="+encodeURIComponent(ip),{cache:"no-store"}); let j=await r.json(); out.textContent=j.out;}catch(e){out.textContent="خطأ"}};window.doTcpPing=async()=>{let ip=document.getElementById("pingIp").value.trim(); let p=document.getElementById("pingPort").value||80; let out=document.getElementById("pingResult"); out.textContent="..."; try{let r=await fetch("/api/ping_tcp?ip="+encodeURIComponent(ip)+"&port="+p); let j=await r.json(); out.textContent=j.out;}catch(e){out.textContent="خطأ"}};window.clearPing=()=>document.getElementById("pingResult").textContent="جاهز";window.pingAllDishes=async()=>{let out=document.getElementById("pingResult"); out.textContent="جاري الفحص..."; try{let r=await fetch("/api/search?q=192",{cache:"no-store"}); let d=await r.json(); out.textContent=""; for(let dish of d.filter(x=>x.page=="dishes").slice(0,25)){out.textContent+="فحص "+dish.sub+"\\n"; try{let pr=await fetch("/api/ping?ip="+encodeURIComponent(dish.sub),{cache:"no-store"}); let pj=await pr.json(); out.textContent+=pj.out+"\\n";}catch(e){} await new Promise(rr=>setTimeout(rr,120));}}catch(e){out.textContent="خطأ"}};(async()=>{try{let r=await fetch("/api/search?q=192",{cache:"no-store"}); let d=await r.json(); let h=""; d.filter(x=>x.page=="dishes").slice(0,8).forEach(x=>{h+="<div class=rowlog><span>"+x.sub+" - "+x.title+"</span><button class=btn-gold onclick=\"document.getElementById('pingIp').value='"+x.sub+"'; doSinglePing()\">Ping</button></div>"}); document.getElementById("quickDishes").innerHTML=h||"-";}catch(e){}})();</script>'''
    if v=='subs':
        rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 200")
        rows=""
        for r in rs:
            rows+="<div class=card id=sub-"+str(r['id'])+" data-name='"+esc(r['name'])+"' data-phone='"+esc(r['phone'] or '')+"' data-note='"+esc(r['note'] or '')+"'><div class=row style='justify-content:space-between'><div><b>"+esc(r['name'])+"</b><br><small>"+esc(r['phone'] or '')+" "+esc(r['note'] or '')+"</small></div><div class=row><button class=btn-gold onclick=\"openEditSub("+str(r['id'])+")\">✏️</button><button class=btn-del onclick=\"askDel('/del_sub/"+str(r['id'])+"',"+str(r['id'])+")\">🗑</button></div></div></div>"
        return '<div class=card><h3>المشتركين - '+str(len(rs))+'</h3><form id=formSub class=row><input name=name placeholder="اسم" required style="flex:1"><input name=phone placeholder="رقم" style="flex:1"><input name=note placeholder="ملاحظة" style="flex:1"><button class=btn-gold>إضافة</button></form></div>'+rows+'<script>window.openEditSub=id=>{let c=document.getElementById("sub-"+id); let body=document.getElementById("editBody"); body.innerHTML="<input id=esn value=\""+c.dataset.name+"\"><input id=esp value=\""+c.dataset.phone+"\"><input id=esno value=\""+c.dataset.note+"\"><button class=btn-gold onclick=\"saveSub("+id+")\" style=\"width:100%\">حفظ</button>"; document.getElementById("editModal").classList.add("show");};window.saveSub=id=>{fetch("/edit_sub/"+id,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:document.getElementById("esn").value,phone:document.getElementById("esp").value,note:document.getElementById("esno").value})}).then(r=>r.json()).then(()=>{closeEditModal(); loadPage("subs",true)})};document.getElementById("formSub").addEventListener("submit",e=>{e.preventDefault(); fetch("/add_sub",{method:"POST",body:new FormData(e.target)}).then(r=>r.json()).then(()=>{e.target.reset(); loadPage("subs",true)})});</script>'
    if v=='ledger':
        rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 200")
        rows=""
        for r in rs:
            rows+="<div class=card id=led-"+str(r['id'])+" data-name='"+esc(r['name'])+"' data-amount='"+str(r['amount'])+"' data-note='"+esc(r.get('note') or '')+"'><div class=row style='justify-content:space-between'><div><b>"+esc(r['name'])+"</b> <span class=ip>"+str(r['amount'])+"</span> <small>"+esc(r.get('note') or '')+"</small></div><div class=row><button class=btn-gold onclick=\"openEditLed("+str(r['id'])+")\">✏️</button><button class=btn-del onclick=\"askDel('/del_ledger/"+str(r['id'])+"',"+str(r['id'])+")\">🗑</button></div></div></div>"
        return '<div class=card><h3>الحسابات - '+str(len(rs))+'</h3><form id=formLed class=row><input name=name placeholder="اسم" required style="flex:1"><input name=amount type=number step=0.01 placeholder="مبلغ" required style="flex:1"><input name=note placeholder="ملاحظة" style="flex:1"><select name=currency><option>USD</option><option>SYP</option></select><button class=btn-gold>إضافة</button></form></div>'+rows+'<script>window.openEditLed=id=>{let c=document.getElementById("led-"+id); let body=document.getElementById("editBody"); body.innerHTML="<input id=eln value=\""+c.dataset.name+"\"><input id=ela value=\""+c.dataset.amount+"\"><input id=elnote value=\""+c.dataset.note+"\"><button class=btn-gold onclick=\"saveLed("+id+")\" style=\"width:100%\">حفظ</button>"; document.getElementById("editModal").classList.add("show");};window.saveLed=id=>{fetch("/edit_ledger/"+id,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:document.getElementById("eln").value,amount:document.getElementById("ela").value,note:document.getElementById("elnote").value,currency:"USD"})}).then(()=>{closeEditModal(); loadPage("ledger",true)})};document.getElementById("formLed").addEventListener("submit",e=>{e.preventDefault(); fetch("/add_ledger",{method:"POST",body:new FormData(e.target)}).then(r=>r.json()).then(()=>{e.target.reset(); loadPage("ledger",true)})});</script>'
    if v=='logs':
        rs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 500")
        rows=""
        for r in rs:
            rows+="<div class=card rowlog style='border-right:4px solid #ffbe4d'><div><b>"+esc(r.get('user_phone',''))+"</b> <span class=badge>"+esc(r.get('action',''))+"</span><br><small>"+esc(r.get('detail',''))+"</small></div><small class=time>"+esc(r.get('time',''))+"</small></div>"
        return '<div class=card row style="justify-content:space-between"><h3>السجل - '+str(len(rs))+'</h3><div class=row><a href="/api/export/logs" class=btn-gold style="text-decoration:none;background:#22c55e;color:#fff">Excel</a><button class=btn-gold onclick="fetch(\'/api/seed_log\',{method:\'POST\'}).then(()=>loadPage(\'logs\',true))">اختبار السجل</button><button class=btn-del onclick="if(confirm(\'مسح؟\'))fetch(\'/api/clear_logs\',{method:\'POST\'}).then(()=>loadPage(\'logs\',true))">مسح</button></div></div>'+(rows or '<div class=card>-</div>')
    if v=='network':
        dishes=qall("SELECT * FROM dish_ips ORDER BY id DESC")
        rows=""
        for d in dishes:
            rows+="<div class=card id=net-"+str(d['id'])+" data-ip='"+esc(d.get('ip',''))+"'><div class=row style='justify-content:space-between'><div><b>"+esc(d.get('dish_name') or 'صحن')+"</b> <span class=ip>"+esc(d.get('ip',''))+"</span><br><small class=net-out>...</small></div><button class=btn-gold onclick='checkOne("+str(d['id'])+")'>فحص</button></div></div>"
        return '<div class=card row style="justify-content:space-between"><h3>حالة الشبكة</h3><div class=row><button class=btn-gold onclick="checkAll()" style="background:#22c55e;color:#fff">فحص الكل</button><button class=btn-gold onclick="loadPage(\'ping\')">Ping</button></div></div>'+rows+'<script>window.checkOne=async id=>{let c=document.getElementById("net-"+id); let out=c.querySelector(".net-out"); out.textContent="..."; try{let r=await fetch("/api/ping?ip="+encodeURIComponent(c.dataset.ip),{cache:"no-store"}); let j=await r.json(); out.textContent=j.out;}catch(e){out.textContent="خطأ"}};window.checkAll=async()=>{for(let c of document.querySelectorAll("[id^=net-]")){await checkOne(c.id.split("-")[1]); await new Promise(r=>setTimeout(r,100))}};checkAll();</script>'
    if v=='settings':
        us=qall("SELECT * FROM users ORDER BY phone DESC")
        uh=""
        for u in us:
            uh+="<div class=card id=user-"+esc(u['phone'])+" data-phone='"+esc(u['phone'])+"' data-username='"+esc(u.get('username') or '')+"' data-role='"+esc(u.get('role') or '')+"'><div class=row style='justify-content:space-between'><div><b>"+esc(u.get('username') or u['phone'])+"</b><br><span class=ip>"+esc(u['phone'])+"</span> <span class=badge>"+esc(u.get('role') or '')+"</span></div><div class=row><button class=btn-gold onclick=\"openEditUser('"+esc(u['phone'])+"')\">✏️</button><button class=btn-del onclick=\"askDel('/del_user/"+esc(u['phone'])+"')\">🗑</button></div></div></div>"
        return '<div class=card><h3>كلمة السر</h3><form id=formPass class=row><input name=newpass type=password placeholder="جديدة" required style="flex:1"><button class=btn-gold>حفظ</button></form></div><div class=card><h3>يوزر جديد</h3><form id=formUser class=row><input name=user_field placeholder="يوزر" required style="flex:1"><input name=password type=password placeholder="باسورد" required style="flex:1"><select name=role style="flex:0.6"><option value=tech>فني</option><option value=manager>مدير</option></select><button class=btn-gold>إضافة</button></form></div><div class=card row style="justify-content:space-between"><h3>يوزرات - '+str(len(us))+'</h3><div class=row><a href="/api/export/users" class=btn-gold style="text-decoration:none;background:#22c55e;color:#fff">Excel</a><button class=btn-gold onclick="toggleLangFast()">تغيير لغة</button><button class=btn-gold onclick="toggleThemeFast()">ثيم</button></div></div>'+uh+'<script>window.openEditUser=ph=>{let c=document.getElementById("user-"+ph); let body=document.getElementById("editBody"); body.innerHTML="<input id=eu_ph value=\""+c.dataset.phone+"\"><input id=eu_pass type=password placeholder=\"باسورد جديد فارغ = بدون تغيير\"><select id=eu_role><option value=tech>فني</option><option value=manager>مدير</option></select><button class=btn-gold onclick=\"saveUser(\\'"+ph+"\\')\" style=\"width:100%\">حفظ</button>"; document.getElementById("eu_role").value=c.dataset.role; document.getElementById("editModal").classList.add("show");};window.saveUser=old=>{let fd=new URLSearchParams({old_phone:old,phone:document.getElementById("eu_ph").value,role:document.getElementById("eu_role").value,password:document.getElementById("eu_pass").value}); fetch("/edit_user",{method:"POST",body:fd}).then(r=>r.json()).then(j=>{if(j.ok){closeEditModal(); loadPage("settings",true)} else alert(j.msg||"خطأ")})};document.getElementById("formPass").addEventListener("submit",e=>{e.preventDefault(); fetch("/change_pass",{method:"POST",body:new FormData(e.target)}).then(r=>r.json()).then(j=>{if(j.ok){e.target.reset(); alert("تم ✓")}})});document.getElementById("formUser").addEventListener("submit",e=>{e.preventDefault(); fetch("/add_user",{method:"POST",body:new FormData(e.target)}).then(r=>r.json()).then(j=>{if(j.ok){e.target.reset(); loadPage("settings",true)} else alert(j.msg||"خطأ")})});</script>'
    return "<div class=card>404</div>"

def layout(c,v='home'):
    th=session.get('theme','dark')
    is_dark=(th=='dark')
    bg='radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 60%, #070a1f 100%)' if is_dark else '#eef2f7'
    card_bg='#1e2433f2' if is_dark else '#ffffff'
    txt='#ffffff' if is_dark else '#0f172a'
    border='#ffffff14' if is_dark else '#e2e8f0'
    cur_user=qone("SELECT * FROM users WHERE phone=?",(session.get('phone') or '',)) or {}
    role=cur_user.get('role') or session.get('role') or 'tech'
    lang=session.get('lang','ar')
    dir_attr='rtl' if lang=='ar' else 'ltr'
    return f"""<html dir={dir_attr}><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<link rel=stylesheet href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'>
<style>
:root{{--ease:cubic-bezier(.16,1,.3,1);}}
*{{box-sizing:border-box;font-family:system-ui}}body{{margin:0;background:{bg};color:{txt};overflow-x:hidden}}
.top{{position:fixed;top:0;left:0;right:0;height:62px;background:#0f172af0;backdrop-filter:blur(18px);display:flex;align-items:center;justify-content:space-between;padding:0 14px;z-index:1003;border-bottom:1px solid #ffffff12}}
.sidebar{{position:fixed;top:0;right:0;width:295px;height:100%;background:linear-gradient(180deg,#0f172a 0%,#070e22 100%);z-index:1002;padding-top:70px;transform:translateX(110%);transition:transform .75s var(--ease);overflow-y:auto}}
.sidebar.active{{transform:none}}.sidebar a{{display:flex;gap:12px;padding:14px 16px;margin:7px 12px;color:#cbd5e1;text-decoration:none;border-radius:14px;background:#ffffff08;transition:transform .65s var(--ease), background .4s, color .4s; will-change:transform; animation:slideIn .6s var(--ease) both}}
@keyframes slideIn{{from{{opacity:0;transform:translateX(30px)}}to{{opacity:1;transform:translateX(0)}}}}
.sidebar a:nth-child(1){{animation-delay:.05s}}.sidebar a:nth-child(2){{animation-delay:.1s}}.sidebar a:nth-child(3){{animation-delay:.15s}}.sidebar a:nth-child(4){{animation-delay:.2s}}.sidebar a:nth-child(5){{animation-delay:.25s}}.sidebar a:nth-child(6){{animation-delay:.3s}}.sidebar a:nth-child(7){{animation-delay:.35s}}.sidebar a:nth-child(8){{animation-delay:.4s}}.sidebar a:nth-child(9){{animation-delay:.45s}}
.sidebar a:hover{{transform:translateX(-8px) scale(1.03); background:#ffffff14}}.sidebar a.active{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:900; transform:scale(1.04)}}.sidebar a:active{{transform:scale(.95); transition:transform .15s}}
#overlay{{position:fixed;inset:0;background:#0008;z-index:1001;display:none}} #overlay.show{{display:block}}
.main{{margin-top:74px;padding:14px;min-height:90vh}}
.card{{background:{card_bg};color:{txt};padding:14px;border-radius:16px;margin-bottom:12px;border:1px solid {border}; animation:fadeUp .65s var(--ease) both; transition:transform .65s var(--ease), box-shadow .65s var(--ease), filter .4s}}
.card:hover{{transform:translateY(-3px) scale(1.006); box-shadow:0 10px 30px #0003}}
@keyframes fadeUp{{from{{opacity:0;transform:translateY(20px) scale(.98)}}to{{opacity:1;transform:translateY(0) scale(1)}}}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:12px}} @media(max-width:760px){{.grid2{{grid-template-columns:1fr}}}}
.stat{{cursor:pointer;position:relative;overflow:hidden}}.stat h2{{font-size:34px;margin:6px 0}}.ico{{position:absolute;left:14px;top:14px;font-size:32px;transition:transform .75s var(--ease)}}.stat:hover .ico{{transform:scale(1.25) rotate(8deg)}}
.row{{display:flex;gap:8px;align-items:center;flex-wrap:wrap}}.col{{display:flex;flex-direction:column;gap:6px}}
.btn-gold{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;padding:9px 14px;border:0;border-radius:11px;font-weight:800;cursor:pointer;transition:transform .65s var(--ease), filter .3s, box-shadow .3s}}.btn-gold:hover{{filter:brightness(1.08); box-shadow:0 4px 18px #ffb02044}}.btn-gold:active{{transform:scale(.88) !important; transition:transform .15s}}
.btn-del{{background:#ef4444;color:#fff;padding:8px 12px;border:0;border-radius:11px;cursor:pointer;transition:transform .65s var(--ease)}}.btn-del:active{{transform:scale(.88)}}
.ip{{background:#000;color:#ffbe4d;padding:4px 8px;border-radius:8px;font-family:monospace;font-size:12px}}
.pingBox{{margin-top:10px;background:#000a;border:1px solid #ffffff12;border-radius:12px;padding:12px;font-family:monospace;min-height:60px;white-space:pre-wrap}}
.rowlog{{display:flex;justify-content:space-between;padding:9px 10px;border-bottom:1px dashed #ffffff10;gap:8px;animation:fadeUp .5s var(--ease)}}.badge{{background:#ffbe4d;color:#111;padding:2px 8px;border-radius:8px;font-size:11px;font-weight:800}}.time{{color:#64748b;font-size:11px}}
.tower-card{{border:1px solid #ffbe4d22; overflow:hidden}}.tower-head{{display:flex;justify-content:space-between;align-items:flex-start}}.tower-title{{font-size:17px;font-weight:900}}.coords{{color:#ffbe4d;font-size:11px}}.tower-body{{margin-top:10px;border-top:1px dashed #ffffff10;padding-top:10px}}.dish-list{{margin-top:8px;display:flex;flex-direction:column;gap:6px}}.dish-mini{{display:flex;justify-content:space-between;align-items:center;background:#ffffff06;padding:8px 10px;border-radius:10px;transition:transform .55s var(--ease), background .3s}}.dish-mini:hover{{transform:scale(1.01); background:#ffffff0a}}
#delModal,#editModal{{position:fixed;inset:0;background:#000a;display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:.45s var(--ease);z-index:2000}} #delModal.show,#editModal.show{{opacity:1;pointer-events:auto}} #delBox,#editBox{{background:{card_bg};color:{txt};padding:22px;border-radius:18px;width:92%;max-width:460px;transform:scale(.88) translateY(30px);transition:transform .65s var(--ease)}} #delModal.show #delBox,#editModal.show #editBox{{transform:scale(1) translateY(0)}}
input,select{{padding:12px;border-radius:11px;border:1px solid {border};background:#ffffff07;color:{txt};transition:transform .45s var(--ease), border .3s, box-shadow .3s}} input:focus{{transform:scale(1.01); border-color:#ffbe4d88; box-shadow:0 0 0 3px #ffbe4d22; outline:none}}
</style></head><body>
<div id=overlay onclick="toggleSb(false)"></div>
<div class=sidebar id=sb><div style='padding:0 18px 12px;border-bottom:1px solid #ffffff0a'><b>OMAIA <span style='color:#ffbe4d'>ISP</span></b><br><small>{esc(cur_user.get('username') or session.get('phone') or '')} • {role}</small></div>
<a href="javascript:loadPage('home')" id=nav-home>🏠 الرئيسية</a>
<a href="javascript:loadPage('towers')" id=nav-towers>🗼 الأبراج - كروت</a>
<a href="javascript:loadPage('dishes')" id=nav-dishes>📡 الصحون</a>
<a href="javascript:loadPage('map')" id=nav-map>🗺 الخريطة عالية الدقة</a>
<a href="javascript:loadPage('ping')" id=nav-ping>📶 بنج</a>
<a href="javascript:loadPage('network')" id=nav-network>📊 الشبكة</a>
<a href="javascript:loadPage('subs')" id=nav-subs>👥 مشتركين</a>
<a href="javascript:loadPage('ledger')" id=nav-ledger>📒 حسابات</a>
<a href="javascript:loadPage('logs')" id=nav-logs>📜 السجل</a>
<a href="javascript:loadPage('settings')" id=nav-settings>⚙ إعدادات</a>
<a href="javascript:logoutFast()" style='margin-top:12px;background:#ef444418'>🚪 خروج</a></div>
<div class=top><div class=row><span onclick="toggleSb()" style='font-size:24px;cursor:pointer;padding:6px 10px;background:#ffffff0a;border-radius:10px;transition:transform .65s var(--ease)'>☰</span><input id=topsearch placeholder='بحث...' oninput="globalSearchTop(this.value)" style='width:44px;transition:all .5s var(--ease);background:#1f2937;border:1px solid #ffffff15;color:#fff;padding:8px 12px;border-radius:10px' onfocus="this.style.width='170px'" onblur="setTimeout(()=>this.style.width='44px',200)"></div><b>OMAIA <span style='color:#ffbe4d'>ISP</span></b><div class=row><button onclick="toggleLangFast()" style='background:#ffffff0a;color:#fff;border:1px solid #ffffff14;padding:8px 10px;border-radius:10px;transition:transform .6s var(--ease)'>🌐</button><button onclick="toggleThemeFast()" style='background:#ffffff0a;color:#fff;border:1px solid #ffffff14;padding:8px 10px;border-radius:10px'>🌓</button></div></div>
<div id=searchResults style='position:fixed;top:66px;right:12px;max-width:380px;width:90%;background:#1e2433;border:1px solid #ffffff15;border-radius:12px;z-index:1500;display:none;max-height:60vh;overflow:auto'></div>
<div class=main id=mn>{c}</div>
<div id=delModal><div id=delBox><div style='text-align:center;font-size:32px'>🗑</div><h3 style='text-align:center'>تأكيد الحذف؟</h3><div class=row style='margin-top:14px'><button onclick="closeDel()" style='flex:1;padding:12px;border-radius:10px;background:transparent;color:{txt};border:1px solid {border}'>تراجع</button><button id=delYes style='flex:1;padding:12px;border-radius:10px;background:#ef4444;color:#fff;border:0;font-weight:800'>حذف</button></div></div></div>
<div id=editModal><div id=editBox><div class=row style='justify-content:space-between'><h3 style='margin:0'>تعديل</h3><button onclick="closeEditModal()" style='width:32px;height:32px;border-radius:50%;background:#ffffff12;border:0;color:{txt}'>✕</button></div><div id=editBody style='margin-top:12px'></div></div></div>
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
function closeDel(){{document.getElementById('delModal').classList.remove('show'); window._delUrl=null;}}
window.closeEditModal=()=>document.getElementById('editModal').classList.remove('show');
document.getElementById('delYes').onclick=async()=>{{
 if(!window._delUrl) return; let btn=document.getElementById('delYes'); let orig=btn.textContent; btn.textContent='...'; btn.disabled=true;
 try{{let r=await fetch(window._delUrl,{{cache:'no-store'}}); let j=await r.json(); if(j.ok){{
   let el=document.getElementById('dish-'+window._delId) || document.getElementById('tower-'+window._delId) || document.getElementById('sub-'+window._delId) || document.getElementById('led-'+window._delId) || document.getElementById('net-'+window._delId) || document.getElementById('user-'+window._delId);
   if(el){{el.style.transform='scale(.85)'; el.style.opacity='0'; el.style.transition='all .4s var(--ease)'; setTimeout(()=>{{el.remove(); delete pageCache[cur];}},350);}}
   closeDel();
 }} else {{alert(j.msg||'ممنوع');}}}}catch(e){{alert(e);}}
 btn.textContent=orig; btn.disabled=false;
}};
window.toggleLangFast=async()=>{{let r=await fetch('/toggle_lang',{{cache:'no-store'}}); let j=await r.json(); loadPage(cur,true,false);}};
window.toggleThemeFast=async()=>{{let r=await fetch('/toggle_theme',{{cache:'no-store'}}); location.reload();}};
window.globalSearchTop=async q=>{{let box=document.getElementById('searchResults'); if(!q||q.length<2){{box.style.display='none'; return;}} try{{let r=await fetch('/api/search?q='+encodeURIComponent(q),{{cache:'no-store'}}); let d=await r.json(); if(!d.length){{box.style.display='none'; return;}} let h=''; d.forEach(x=>{{h+='<div onclick="loadPage(\\''+x.page+'\\');document.getElementById(\\'searchResults\\').style.display=\\'none\\'" style="padding:11px 12px;cursor:pointer;border-bottom:1px solid #ffffff08;transition:background .3s"><b>'+x.title+'</b><br><small style="color:#888">'+x.sub+'</small></div>';}}); box.innerHTML=h; box.style.display='block';}}catch(e){{}}}};
window.logoutFast=async()=>{{await fetch('/api/logout',{{method:'POST'}}); localStorage.clear(); sessionStorage.clear(); location.replace('/login');}};
window.addEventListener('popstate',e=>{{let v='home'; if(e.state&&e.state.page) v=e.state.page; else {{let p=new URLSearchParams(location.search); v=p.get('v')||'home';}} loadPage(v,false,false);}});
loadPage(cur,true,false);
</script></body></html>"""

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)),debug=False)
