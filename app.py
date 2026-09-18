from flask import Flask, request, redirect, session, jsonify, Response
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, html, ipaddress, subprocess, json, socket, platform, io, csv, datetime, re, threading, time, traceback, sys
try:
    import psycopg2, psycopg2.extras
    from psycopg2 import pool as pg_pool
    PG_AVAILABLE=True
except:
    psycopg2=None
    pg_pool=None
    PG_AVAILABLE=False
import sqlite3

app=Flask(__name__)
app.secret_key=os.environ.get("SECRET_KEY","omia-perfect-2026")
app.config['PERMANENT_SESSION_LIFETIME']=datetime.timedelta(minutes=30)
app.config['SESSION_PERMANENT']=False
app.config['SESSION_COOKIE_HTTPONLY']=True

DATABASE_URL=os.environ.get("DATABASE_URL","").strip()
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL=DATABASE_URL.replace("postgres://","postgresql://",1)
USE_PG=False
if DATABASE_URL.startswith("postgresql://") and PG_AVAILABLE:
    USE_PG=True

_pg_pool=None
_pool_lock=threading.Lock()
_sqlite_conn=None
_sqlite_lock=threading.Lock()
_cache={}
_cache_lock=threading.Lock()

SUPPORT_PHONE="+905345851045"
SUPPORT_WA="+905345851045"
SUPPORT_INSTA="af_20_1999"

def init_pool():
    global _pg_pool, USE_PG
    if not USE_PG or not pg_pool:
        return
    with _pool_lock:
        if _pg_pool:
            return
        try:
            _pg_pool=pg_pool.ThreadedConnectionPool(2,10,dsn=DATABASE_URL,sslmode='require',connect_timeout=4)
        except Exception as e:
            print(f"[POOL] {e}")
            _pg_pool=None
            USE_PG=False
init_pool()

def esc(s):
    return html.escape(str(s or ''), quote=True)

def get_conn():
    global USE_PG, _sqlite_conn
    if USE_PG and _pg_pool:
        try:
            c=_pg_pool.getconn()
            if getattr(c,'closed',1)==0:
                return c
        except:
            try:
                return psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=4)
            except:
                USE_PG=False
    elif USE_PG:
        try:
            return psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=4)
        except:
            USE_PG=False
    with _sqlite_lock:
        if _sqlite_conn is None:
            db_path=os.path.join(os.path.dirname(os.path.abspath(__file__)),"omia.db")
            _sqlite_conn=sqlite3.connect(db_path,check_same_thread=False,timeout=10,isolation_level=None)
            _sqlite_conn.row_factory=sqlite3.Row
            try:
                _sqlite_conn.execute("PRAGMA journal_mode=WAL;")
            except:
                pass
        return _sqlite_conn

def put_conn(conn):
    if USE_PG and _pg_pool and conn and hasattr(conn,'closed'):
        try:
            _pg_pool.putconn(conn)
        except:
            try:
                conn.close()
            except:
                pass
    elif USE_PG and conn and hasattr(conn,'closed'):
        try:
            conn.close()
        except:
            pass

def qall(q,a=()):
    conn=None
    try:
        conn=get_conn()
        if USE_PG and hasattr(conn,'cursor'):
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
        print(f"[qall] {e}")
        if conn and USE_PG and hasattr(conn,'closed'):
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
        if USE_PG and hasattr(conn,'cursor'):
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
        print(f"[qexec] {e} {q[:80]}")
        if conn and USE_PG and hasattr(conn,'closed'):
            try:
                conn.rollback()
                put_conn(conn)
            except:
                pass
        return False

def add_log(phone,action,detail):
    try:
        now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)",(phone or 'sys',action,detail,now))
        qexec("INSERT INTO notifications(title,msg,time) VALUES(?,?,?)",(action,f"{phone}: {detail}",now))
        with _cache_lock:
            _cache.pop('counts',None)
    except:
        pass

def get_counts():
    with _cache_lock:
        c=_cache.get('counts')
        if c and time.time()-c[1]<10:
            return c[0]
    try:
        ns=(qone("SELECT COUNT(*) as c FROM subs") or {}).get('c',0)
        nd=(qone("SELECT COUNT(*) as c FROM dish_ips") or {}).get('c',0)
        nt=(qone("SELECT COUNT(*) as c FROM towers") or {}).get('c',0)
        nl=(qone("SELECT COUNT(*) as c FROM ledger") or {}).get('c',0)
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
    for alter in ["ALTER TABLE dish_ips ADD COLUMN tower_id INTEGER","ALTER TABLE towers ADD COLUMN created_at TEXT"]:
        try:
            qexec(alter)
        except:
            pass
    for idx in ["CREATE INDEX IF NOT EXISTS idx_dish_ip ON dish_ips(ip)","CREATE INDEX IF NOT EXISTS idx_dish_tower ON dish_ips(tower_id)"]:
        try:
            qexec(idx)
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
    resp.headers['Cache-Control']='no-cache'
    return resp

@app.errorhandler(500)
def err500(e):
    print(traceback.format_exc())
    if request.path.startswith('/api/'):
        return jsonify(ok=False,msg=str(e)[:300]),500
    return f"<div style='padding:20px;color:red'>خطأ: {esc(str(e))}</div>",500

@app.route('/ping')
@app.route('/health')
def public_ping():
    return jsonify(ok=True,time=datetime.datetime.now().isoformat(),use_pg=USE_PG)

@app.route('/api/ping')
@login_required
def api_ping():
    ip=request.args.get('ip','').strip()
    if not ip or not is_valid_ip(ip):
        return jsonify(ok=False,out='IP غير صالح')
    for port in [80,443,8080,8291,22,8728,8000,23]:
        s=None
        try:
            s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
            s.settimeout(0.5)
            if s.connect_ex((ip,port))==0:
                s.close()
                return jsonify(ok=True,out=f'متصل {ip}:{port} مفتوح')
            s.close()
        except:
            try:
                s.close()
            except:
                pass
    try:
        cmd=['ping','-c','1','-W','1',ip] if platform.system().lower()!='windows' else ['ping','-n','1','-w','1000',ip]
        out=subprocess.check_output(cmd,timeout=1.5,stderr=subprocess.STDOUT).decode(errors='ignore')
        if 'ttl=' in out.lower() or 'bytes from' in out.lower():
            m=re.search(r'time[=<]\s*(\d+\.?\d*)',out,re.I)
            ms=m.group(1) if m else ''
            return jsonify(ok=True,out=f'{ip} {ms}ms')
    except:
        pass
    return jsonify(ok=False,out=f'{ip} لا يرد')

@app.route('/api/ping_tcp')
@login_required
def api_ping_tcp():
    ip=request.args.get('ip','').strip()
    port=request.args.get('port','80').strip()
    try:
        port=int(port)
    except:
        return jsonify(ok=False,out='Port خطأ')
    if not is_valid_ip(ip):
        return jsonify(ok=False,out='IP خطأ')
    s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    s.settimeout(0.8)
    try:
        r=s.connect_ex((ip,port))
        s.close()
        return jsonify(ok=r==0,out=f'{ip}:{port} مفتوح' if r==0 else 'مغلق')
    except Exception as e:
        try:
            s.close()
        except:
            pass
        return jsonify(ok=False,out=str(e))

@app.route('/api/notifications')
@login_required
def api_noti():
    rows=qall("SELECT * FROM notifications ORDER BY id DESC LIMIT 20")
    cnt=(qone("SELECT COUNT(*) as c FROM notifications WHERE read=0") or {}).get('c',0)
    return jsonify(rows=rows,unread=cnt)

@app.route('/api/notifications/read',methods=['POST'])
@login_required
def api_noti_read():
    qexec("UPDATE notifications SET read=1")
    return jsonify(ok=True)

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
    return jsonify(ok=True,theme=session['theme'])

@app.route('/api/login_public',methods=['POST'])
def api_login_public():
    try:
        uin=request.form.get('userin','').strip()
        pw=request.form.get('password','')
        u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
        if u and check_password_hash(u['password'],pw):
            session.clear()
            session['phone']=u['phone']
            session['username']=u.get('username') or u['phone']
            session['role']=u.get('role') or 'tech'
            session.permanent=False
            add_log(u['phone'],'دخل النظام',f'login {uin}')
            return jsonify(ok=True)
        return jsonify(ok=False,msg='خطأ بالدخول'),401
    except Exception as e:
        return jsonify(ok=False,msg=str(e)),500

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
            w.writerow([r.get('id',''),r.get('dish_name',''),r.get('ip',''),r.get('location',''),r.get('tower_id','')])
        fname='dishes.csv'
    elif tbl=='towers':
        rows=qall("SELECT * FROM towers ORDER BY id DESC")
        w.writerow(['ID','اسم','منطقة','lat','lng'])
        for r in rows:
            w.writerow([r.get('id',''),r.get('name',''),r.get('area',''),r.get('lat',''),r.get('lng','')])
        fname='towers.csv'
    else:
        rows=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 2000")
        w.writerow(['ID','يوزر','عمل','تفصيل','وقت'])
        for r in rows:
            w.writerow([r.get('id',''),r.get('user_phone',''),r.get('action',''),r.get('detail',''),r.get('time','')])
        fname='logs.csv'
    return Response(output.getvalue(),mimetype='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename={fname}'})

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
        add_log(session.get('phone'),'تعديل موقع برج',f"ID {tid} {lat},{lng}")
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False,msg=str(e)),400

@app.route('/api/add_dish_to_tower',methods=['POST'])
@login_required
def add_dish_to_tower():
    try:
        data=request.json if request.is_json else request.form
        ip=(data.get('ip') or '').strip()
        name=(data.get('dish_name') or '').strip()
        loc=(data.get('location') or '').strip()
        tid=data.get('tower_id')
        if not ip or not is_valid_ip(ip):
            return jsonify(ok=False,msg='IP غير صالح'),400
        # handle duplicate IP - use REPLACE
        if USE_PG:
            ok=qexec("INSERT INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?) ON CONFLICT (ip) DO UPDATE SET dish_name=EXCLUDED.dish_name, location=EXCLUDED.location, tower_id=EXCLUDED.tower_id",(ip,loc,name,int(tid) if tid and str(tid).isdigit() else None))
        else:
            ok=qexec("INSERT OR REPLACE INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?)",(ip,loc,name,int(tid) if tid and str(tid).isdigit() else None))
        if ok:
            add_log(session.get('phone'),'إضافة صحن للبرج',f"{name} {ip} tower:{tid}")
            with _cache_lock:
                _cache.pop('counts',None)
            return jsonify(ok=True)
        else:
            return jsonify(ok=False,msg='فشل الحفظ - قاعدة البيانات'),500
    except Exception as e:
        traceback.print_exc()
        return jsonify(ok=False,msg=str(e)),500

@app.route('/')
def ix():
    return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login')
def login():
    return f"""<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>OMAIA ISP</title>
<style>*{{box-sizing:border-box;font-family:system-ui}}body{{margin:0;min-height:100vh;background:radial-gradient(120% 120% at 10% 10%,#1a2344 0%,#0a0e2a 55%,#070a1f 100%);display:flex;flex-direction:column;align-items:center;justify-content:center;color:#fff}}
.card{{background:linear-gradient(180deg,#222b45cc,#1a2035cc);border:1px solid #ffffff18;padding:20px;border-radius:16px;width:92%;max-width:360px;animation:fadeUp .6s cubic-bezier(.16,1,.3,1)}}
@keyframes fadeUp{{from{{opacity:0;transform:translateY(20px)}}to{{opacity:1;transform:translateY(0)}}}}
input{{width:100%;padding:12px;margin:7px 0;background:#0f1424;border:1px solid #ffffff22;color:#fff;border-radius:10px;transition:.3s}}input:focus{{border-color:#ffbe4d;outline:none;box-shadow:0 0 0 3px #ffbe4d22}}
.btn{{width:100%;padding:12px;border:0;border-radius:10px;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:900;font-size:15px;cursor:pointer;transition:.4s}} .btn:active{{transform:scale(.96)}}
.small{{font-size:11px;color:#94a3b8}} .wa{{background:#25D366;color:#fff;padding:10px;border-radius:10px;text-decoration:none;display:flex;align-items:center;justify-content:center;gap:8px;font-weight:800;margin-top:10px}}
</style></head><body>
<div style='font-size:28px;font-weight:900;margin-bottom:12px'>OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<div class=card>
<form id=loginForm>
<input name=userin id=userin placeholder='رقم / يوزر' required autofocus>
<input name=password id=password type=password placeholder='كلمة السر' required>
<label style='display:flex;align-items:center;gap:6px;margin:8px 0;font-size:13px'><input type=checkbox id=remember style='width:16px;height:16px;margin:0'> حفظ كلمة السر</label>
<button class=btn id=loginBtn>دخول</button>
<div id=msg style='text-align:center;margin-top:8px;color:#ff6b6b;font-size:12px;min-height:16px'></div>
</form>
<div style='margin-top:14px;border-top:1px dashed #ffffff15;padding-top:10px;text-align:center'>
<small class=small>الدعم الفني</small><br>
<b style='color:#ffbe4d'>{SUPPORT_PHONE}</b><br>
<small class=small>انستا: {SUPPORT_INSTA}</small><br>
<a href='https://wa.me/{SUPPORT_WA.replace("+","")}' target=_blank class=wa>💬 واتساب الدعم</a>
</div>
</div>
<script>
const userIn=document.getElementById('userin');
const passIn=document.getElementById('password');
const rem=document.getElementById('remember');
if(localStorage.getItem('saved_user')){{userIn.value=localStorage.getItem('saved_user');}}
if(localStorage.getItem('saved_pass')){{passIn.value=localStorage.getItem('saved_pass'); rem.checked=true;}}
document.getElementById('loginForm').addEventListener('submit',async e=>{{
 e.preventDefault();
 let btn=document.getElementById('loginBtn'), msg=document.getElementById('msg');
 if(btn.disabled) return;
 btn.textContent='جاري...'; btn.disabled=true; msg.textContent='';
 try{{
  let fd=new FormData(e.target);
  let r=await fetch('/api/login_public',{{method:'POST',body:fd,cache:'no-store'}});
  let j=await r.json();
  if(j.ok){{
   if(rem.checked){{localStorage.setItem('saved_user',userIn.value); localStorage.setItem('saved_pass',passIn.value);}} else {{localStorage.removeItem('saved_user'); localStorage.removeItem('saved_pass');}}
   location.replace('/dash?v=home');
  }} else {{msg.textContent=j.msg||'خطأ'; btn.textContent='دخول'; btn.disabled=false;}}
 }}catch(err){{msg.textContent='خطأ شبكة'; btn.textContent='دخول'; btn.disabled=false;}}
}});
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
    try:
        return page_content(request.args.get('v','home'))
    except Exception as e:
        traceback.print_exc()
        return f"<div class=card style='background:#ef4444;color:#fff'>خطأ: {esc(str(e))}<br><pre style='font-size:10px;white-space:pre-wrap'>{esc(traceback.format_exc()[:1500])}</pre></div>",500

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
        for r in qall(f"SELECT * FROM dish_ips WHERE ip {op} ? OR dish_name {op} ? OR location {op} ? ORDER BY id DESC LIMIT 20",(like,like,like)):
            results.append({"title":r.get('dish_name') or r.get('ip') or 'صحن',"sub":r.get('ip',''),"page":"dishes"})
        for r in qall(f"SELECT * FROM towers WHERE name {op} ? OR area {op} ? ORDER BY id DESC LIMIT 15",(like,like)):
            results.append({"title":r.get('name',''),"sub":r.get('area',''),"page":"towers"})
        for r in qall(f"SELECT * FROM subs WHERE name {op} ? OR phone {op} ? ORDER BY id DESC LIMIT 15",(like,like)):
            results.append({"title":r.get('name',''),"sub":r.get('phone',''),"page":"subs"})
    except:
        pass
    return jsonify(results[:30])

@app.route('/add_dish',methods=['POST'])
@login_required
def ad():
    try:
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
            ok=qexec("INSERT INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?) ON CONFLICT (ip) DO UPDATE SET dish_name=EXCLUDED.dish_name, location=EXCLUDED.location, tower_id=EXCLUDED.tower_id",(ip,loc,name,int(tid) if tid and str(tid).isdigit() else None))
        else:
            ok=qexec("INSERT OR REPLACE INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?)",(ip,loc,name,int(tid) if tid and str(tid).isdigit() else None))
        if ok:
            add_log(session.get('phone'),'إضافة صحن',name+" "+ip)
            with _cache_lock:
                _cache.pop('counts',None)
        return jsonify(ok=ok)
    except Exception as e:
        return jsonify(ok=False,msg=str(e)),500

@app.route('/edit_dish/<int:i>',methods=['POST'])
@login_required
def ed(i):
    if not is_manager():
        return jsonify(ok=False,msg='ممنوع'),403
    try:
        data=request.json if request.is_json else request.form
        ok=qexec("UPDATE dish_ips SET dish_name=?,ip=?,location=?,tower_id=? WHERE id=?",(data.get('dish_name',''),data.get('ip',''),data.get('location',''), data.get('tower_id') or None, i))
        if ok:
            add_log(session.get('phone'),'تعديل صحن',f"ID {i}")
        return jsonify(ok=ok)
    except Exception as e:
        return jsonify(ok=False,msg=str(e)),500

@app.route('/del_dish/<int:i>')
@login_required
def dd(i):
    if not is_manager():
        return jsonify(ok=False,msg='ممنوع'),403
    try:
        info=qone("SELECT ip,dish_name FROM dish_ips WHERE id=?",(i,))
        ok=qexec("DELETE FROM dish_ips WHERE id=?",(i,))
        if ok:
            with _cache_lock:
                _cache.pop('counts',None)
            add_log(session.get('phone'),'حذف صحن',str(info.get('dish_name',''))+" "+str(info.get('ip','')) if info else f"ID {i}")
        return jsonify(ok=ok)
    except Exception as e:
        return jsonify(ok=False,msg=str(e)),500

@app.route('/add_tower',methods=['POST'])
@login_required
def at():
    try:
        data=request.json if request.is_json else request.form
        try:
            la=float(data.get('lat') or 35.1312)
            ln=float(data.get('lng') or 36.7578)
        except:
            la=35.1312
            ln=36.7578
        now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ok=qexec("INSERT INTO towers(name,area,lat,lng,created_at) VALUES(?,?,?,?,?)",(data.get('name','كرت جديد'),data.get('area',''),la,ln,now))
        if ok:
            add_log(session.get('phone'),'إضافة برج',str(data.get('name','')))
        return jsonify(ok=ok)
    except Exception as e:
        return jsonify(ok=False,msg=str(e)),500

@app.route('/del_tower/<int:i>')
@login_required
def dt(i):
    if not is_manager():
        return jsonify(ok=False,msg='ممنوع'),403
    try:
        qexec("UPDATE dish_ips SET tower_id=NULL WHERE tower_id=?",(i,))
        ok=qexec("DELETE FROM towers WHERE id=?",(i,))
        if ok:
            add_log(session.get('phone'),'حذف برج',f"ID {i}")
        return jsonify(ok=ok)
    except Exception as e:
        return jsonify(ok=False,msg=str(e)),500

@app.route('/edit_tower/<int:i>',methods=['POST'])
@login_required
def et(i):
    if not is_manager():
        return jsonify(ok=False,msg='ممنوع'),403
    try:
        data=request.json if request.is_json else request.form
        try:
            la=float(data.get('lat') or 35.1318)
            ln=float(data.get('lng') or 36.7578)
        except:
            la=35.1318
            ln=36.7578
        ok=qexec("UPDATE towers SET name=?,area=?,lat=?,lng=? WHERE id=?",(data.get('name',''),data.get('area',''),la,ln,i))
        if ok:
            add_log(session.get('phone'),'تعديل برج',f"ID {i}")
        return jsonify(ok=ok)
    except Exception as e:
        return jsonify(ok=False,msg=str(e)),500

@app.route('/add_sub',methods=['POST'])
@login_required
def asub():
    try:
        data=request.json if request.is_json else request.form
        ok=qexec("INSERT INTO subs(name,phone,note) VALUES(?,?,?)",(data.get('name',''),data.get('phone',''),data.get('note','')))
        if ok:
            add_log(session.get('phone'),'إضافة مشترك',str(data.get('name','')))
        return jsonify(ok=ok)
    except Exception as e:
        return jsonify(ok=False,msg=str(e)),500

@app.route('/del_sub/<int:i>')
@login_required
def dsub(i):
    if not is_manager():
        return jsonify(ok=False),403
    try:
        ok=qexec("DELETE FROM subs WHERE id=?",(i,))
        if ok:
            add_log(session.get('phone'),'حذف مشترك',f"ID {i}")
        return jsonify(ok=ok)
    except Exception as e:
        return jsonify(ok=False,msg=str(e)),500

@app.route('/edit_sub/<int:i>',methods=['POST'])
@login_required
def esub(i):
    if not is_manager():
        return jsonify(ok=False),403
    try:
        data=request.json if request.is_json else request.form
        ok=qexec("UPDATE subs SET name=?,phone=?,note=? WHERE id=?",(data.get('name',''),data.get('phone',''),data.get('note',''),i))
        if ok:
            add_log(session.get('phone'),'تعديل مشترك',f"ID {i}")
        return jsonify(ok=ok)
    except Exception as e:
        return jsonify(ok=False,msg=str(e)),500

@app.route('/add_ledger',methods=['POST'])
@login_required
def al():
    try:
        data=request.json if request.is_json else request.form
        try:
            amt=float(data.get('amount') or 0)
        except:
            amt=0
        ok=qexec("INSERT INTO ledger(name,amount,note,currency) VALUES(?,?,?,?)",(data.get('name',''),amt,data.get('note',''),data.get('currency','USD')))
        if ok:
            add_log(session.get('phone'),'إضافة حساب',str(data.get('name',''))+" "+str(amt))
        return jsonify(ok=ok)
    except Exception as e:
        return jsonify(ok=False,msg=str(e)),500

@app.route('/del_ledger/<int:i>')
@login_required
def dll(i):
    if not is_manager():
        return jsonify(ok=False),403
    try:
        ok=qexec("DELETE FROM ledger WHERE id=?",(i,))
        if ok:
            add_log(session.get('phone'),'حذف حساب',f"ID {i}")
        return jsonify(ok=ok)
    except Exception as e:
        return jsonify(ok=False,msg=str(e)),500

@app.route('/edit_ledger/<int:i>',methods=['POST'])
@login_required
def el(i):
    if not is_manager():
        return jsonify(ok=False),403
    try:
        data=request.json if request.is_json else request.form
        try:
            amt=float(data.get('amount') or 0)
        except:
            amt=0
        ok=qexec("UPDATE ledger SET name=?,amount=?,note=?,currency=? WHERE id=?",(data.get('name',''),amt,data.get('note',''),data.get('currency','USD'),i))
        if ok:
            add_log(session.get('phone'),'تعديل حساب',f"ID {i}")
        return jsonify(ok=ok)
    except Exception as e:
        return jsonify(ok=False,msg=str(e)),500

@app.route('/add_user',methods=['POST'])
@login_required
@role_required_manager
def au():
    try:
        ph=(request.form.get('phone') or request.form.get('user_field','')).strip()
        if not ph:
            return jsonify(ok=False,msg='رقم مطلوب'),400
        if qone("SELECT * FROM users WHERE phone=?",(ph,)):
            return jsonify(ok=False,msg='موجود'),400
        ok=qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",(ph,generate_password_hash(request.form.get('password','1234')),request.form.get('role','tech'),ph))
        if ok:
            add_log(session.get('phone'),'إضافة يوزر',ph)
        return jsonify(ok=ok)
    except Exception as e:
        return jsonify(ok=False,msg=str(e)),500

@app.route('/edit_user',methods=['POST'])
@login_required
@role_required_manager
def eu():
    try:
        old=request.form.get('old_phone','').strip()
        new_ph=(request.form.get('phone') or request.form.get('user_field','')).strip()
        new_role=request.form.get('role','tech')
        new_pass=request.form.get('password','').strip()
        if not old:
            return jsonify(ok=False,msg='خطأ'),400
        if old!=new_ph and qone("SELECT * FROM users WHERE phone=?",(new_ph,)):
            return jsonify(ok=False,msg='الرقم موجود'),400
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
    except Exception as e:
        return jsonify(ok=False,msg=str(e)),500

@app.route('/del_user/<ph>')
@login_required
@role_required_manager
def du(ph):
    if ph=='05344851045':
        return jsonify(ok=False,msg='ممنوع حذف المدير'),400
    try:
        ok=qexec("DELETE FROM users WHERE phone=?",(ph,))
        if ok:
            add_log(session.get('phone'),'حذف يوزر',ph)
        return jsonify(ok=ok)
    except Exception as e:
        return jsonify(ok=False,msg=str(e)),500

@app.route('/change_pass',methods=['POST'])
@login_required
def cp():
    try:
        data=request.json if request.is_json else request.form
        np=(data.get('newpass') or '').strip()
        if not np:
            return jsonify(ok=False,msg='فارغة'),400
        ok=qexec("UPDATE users SET password=? WHERE phone=?",(generate_password_hash(np),session.get('phone')))
        if ok:
            add_log(session.get('phone'),'تغيير كلمة سر','')
        return jsonify(ok=ok)
    except Exception as e:
        return jsonify(ok=False,msg=str(e)),500

def page_content(v):
    try:
        lang=session.get('lang','ar')
        def L(ar,en):
            return ar if lang=='ar' else en
        # HOME - كروت صغيرة + واتساب
        if v=='home':
            ns,nd,nt,nl=get_counts()
            logs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 6")
            log_html=""
            for l in logs:
                log_html+=f'<div class=rowlog><div><b>{esc(l.get("user_phone",""))}</b> <span class=badge>{esc(l.get("action",""))}</span><br><small>{esc(str(l.get("detail",""))[:60])}</small></div><small class=time>{esc(l.get("time",""))}</small></div>'
            if not log_html:
                log_html='<div style="padding:10px;color:#888;font-size:12px">فاضي - السجل شغال</div>'
            return f'''
<div style="max-width:1000px;margin:0 auto">
<div class=grid-small>
<div class="card small stat" onclick="loadPage('subs')"><div class=ico>👥</div><h4>{L("مشتركين","Subs")}</h4><h2>{ns}</h2></div>
<div class="card small stat" onclick="loadPage('dishes')"><div class=ico>📡</div><h4>{L("صحون","Dishes")}</h4><h2>{nd}</h2></div>
<div class="card small stat" onclick="loadPage('towers')"><div class=ico>🗼</div><h4>{L("أبراج","Towers")}</h4><h2>{nt}</h2></div>
<div class="card small stat" onclick="loadPage('ledger')"><div class=ico>📒</div><h4>{L("حسابات","Accounts")}</h4><h2>{nl}</h2></div>
</div>
<div class="card small" style="margin-top:8px;border:1px solid #25D36655">
<div class=row style="justify-content:space-between">
<div><b>💬 واتساب الدعم</b><br><small>{SUPPORT_PHONE} • {SUPPORT_INSTA}</small></div>
<a href="https://wa.me/{SUPPORT_WA.replace("+","")}" target="_blank" class=btn-gold style="background:#25D366;color:#fff;text-decoration:none">واتساب</a>
</div>
</div>
<div class=card small style="margin-top:8px"><div class=row style="justify-content:space-between"><b>آخر النشاطات - السجل يسجل كلشي</b><div class=row><button class=btn-gold onclick="fetch('/api/seed_log',{{method:'POST'}}).then(()=>loadPage('home',true))" style="padding:4px 8px;font-size:11px">اختبار</button><button class=btn-gold onclick="loadPage('logs')" style="padding:4px 8px;font-size:11px">الكل</button></div></div><div style="margin-top:6px">{log_html}</div></div>
<a href="https://wa.me/{SUPPORT_WA.replace("+","")}" target="_blank" class=wa-float>💬</a>
</div>'''
        # TOWERS - كروت صغيرة + اضافة IP شغال بدون خطأ
        if v=='towers':
            rs=qall("SELECT * FROM towers ORDER BY id DESC")
            cards=""
            for t in rs:
                tid=t.get('id')
                dishes=qall("SELECT * FROM dish_ips WHERE tower_id=? ORDER BY id DESC",(tid,))
                dish_html=""
                for d in dishes:
                    ip=esc(d.get('ip') or '')
                    dish_html+=f'<div class="dish-mini small"><div><b>{esc(d.get("dish_name") or "صحن")}</b> <a href="http://{ip}" target="_blank" class=ip>{ip}</a></div><div class=row><a href="http://{ip}" target="_blank" class=btn-gold style="padding:3px 6px;font-size:10px;text-decoration:none">🌐</a><button class=btn-del style="padding:3px 6px;font-size:10px" onclick="delDishInTower({d.get("id")},{tid})">✕</button></div></div>'
                if not dish_html:
                    dish_html='<small style="color:#777;font-size:11px">فاضي - ضيف IP</small>'
                cards+=f'<div class="card small tower-card" id="tower-{tid}" data-name="{esc(t.get("name") or "")}" data-area="{esc(t.get("area") or "")}" data-lat="{t.get("lat")}" data-lng="{t.get("lng")}"><div class=tower-head><div><b class=tower-title style="font-size:13px">{esc(t.get("name") or "")}</b><br><small style="font-size:10px">{esc(t.get("area") or "")}</small><br><small class=coords style="font-size:9px">{t.get("lat")} , {t.get("lng")}</small></div><div class=col><button class=btn-gold style="padding:4px 6px;font-size:10px" onclick="openEditTower({tid})">✏️</button><button class=btn-del style="padding:4px 6px;font-size:10px" onclick="askDel(\'/del_tower/{tid}\',{tid})">🗑</button><button class=btn-gold style="padding:4px 6px;font-size:10px" onclick="focusMap({t.get("lat")},{t.get("lng")})">🗺</button></div></div><div class=tower-body><div class=row><input id="ip-{tid}" placeholder="IP" style="flex:1;padding:6px;font-size:11px"><input id="name-{tid}" placeholder="اسم" style="flex:1;padding:6px;font-size:11px"><button class=btn-gold style="padding:6px 8px;font-size:11px" onclick="addDishToTower({tid})">+ IP</button></div><div class=dish-list>{dish_html}</div><div id=msg-{tid} style="font-size:10px;color:#ff6b6b;margin-top:4px"></div></div></div>'
            return f'<div style="max-width:1000px;margin:0 auto"><div class=card small><div class=row style="justify-content:space-between"><h3 style="margin:0;font-size:14px">الأبراج - كروت صغيرة - {len(rs)}</h3><div class=row><button class=btn-gold onclick="openNewTower()" style="background:#22c55e;color:#fff;padding:6px 10px;font-size:11px">+ كرت جديد</button><a href="/api/export/towers" class=btn-gold style="padding:6px 10px;font-size:11px">Excel</a></div></div></div><div class=grid-small>{cards}</div></div><script>window.openNewTower=function(){{let b=document.getElementById("editBody"); b.innerHTML=\'<input id=nt_name placeholder="اسم الكرت" value="كرت جديد"><input id=nt_area placeholder="منطقة"><div class=row><input id=nt_lat placeholder="lat" value="35.1318"><input id=nt_lng placeholder="lng" value="36.7578"></div><button class=btn-gold onclick="saveNewTower()" style="width:100%;margin-top:6px">حفظ</button>\'; document.getElementById("editModal").classList.add("show");}};window.saveNewTower=function(){{let d={{name:document.getElementById("nt_name").value,area:document.getElementById("nt_area").value,lat:document.getElementById("nt_lat").value,lng:document.getElementById("nt_lng").value}}; fetch("/add_tower",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify(d)}}).then(r=>r.json()).then(j=>{{if(j.ok){{closeEditModal(); loadPage("towers",true);}} else alert(j.msg||"خطأ");}})}};window.openEditTower=function(id){{let c=document.getElementById("tower-"+id); let b=document.getElementById("editBody"); b.innerHTML=\'<input id=et_name value="\'+c.dataset.name+\'"><input id=et_area value="\'+c.dataset.area+\'"><div class=row><input id=et_lat value="\'+c.dataset.lat+\'"><input id=et_lng value="\'+c.dataset.lng+\'"></div><button class=btn-gold onclick="saveTower(\'+id+\')" style="width:100%">حفظ</button>\'; document.getElementById("editModal").classList.add("show");}};window.saveTower=function(id){{let d={{name:document.getElementById("et_name").value,area:document.getElementById("et_area").value,lat:document.getElementById("et_lat").value,lng:document.getElementById("et_lng").value}}; fetch("/edit_tower/"+id,{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify(d)}}).then(()=>{{closeEditModal(); loadPage("towers",true);}})}};window.addDishToTower=function(tid){{let ip=document.getElementById("ip-"+tid).value.trim(); let nm=document.getElementById("name-"+tid).value.trim(); let msg=document.getElementById("msg-"+tid); if(!ip){{msg.textContent="اكتب IP"; return;}} msg.textContent="جاري..."; fetch("/api/add_dish_to_tower",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{ip:ip,dish_name:nm,tower_id:tid}})}}).then(r=>r.json()).then(j=>{{if(j.ok){{msg.textContent="✓ تم"; loadPage("towers",true);}} else {{msg.textContent=j.msg||"خطأ";}}}}).catch(e=>{{msg.textContent="خطأ شبكة";}});}};window.delDishInTower=function(did,tid){{fetch("/del_dish/"+did).then(r=>r.json()).then(j=>{{if(j.ok) loadPage("towers",true);}})}};window.focusMap=function(lat,lng){{loadPage("map"); setTimeout(()=>{{if(window._map) window._map.flyTo([lat,lng],18);}},600);}};</script>'
        # DISHES - كروت صغيرة جدا + كروت داخل كروت + IP يفتح كروم
        if v=='dishes':
            rs=qall("SELECT * FROM dish_ips ORDER BY id DESC")
            rows=""
            for r in rs:
                rid=r.get('id')
                dn=esc(r.get('dish_name') or 'صحن')
                ip=esc(r.get('ip') or '')
                loc=esc(r.get('location') or '')
                tid=r.get('tower_id')
                badge=f"برج {tid}" if tid else "بدون برج"
                rows+=f'''
<div class="card small dish-card" id="dish-{rid}" data-name="{dn}" data-ip="{ip}" data-loc="{loc}" style="padding:8px">
<div style="display:flex;justify-content:space-between;align-items:center">
<div style="flex:1">
<b style="font-size:12px">{dn}</b><br>
<a href="http://{ip}" target="_blank" class=ip style="font-size:10px">{ip}</a><br>
<small style="font-size:10px;color:#888">{loc}</small>
<div class="card small" style="margin:4px 0;padding:4px;background:#ffffff05;border:1px dashed #ffffff10"><small style="font-size:9px">📍 {badge}</small> <small style="font-size:9px" class=badge>{loc or "بدون موقع"}</small></div>
</div>
<div class=col style="gap:4px">
<a href="http://{ip}" target="_blank" class=btn-gold style="padding:4px 6px;font-size:10px;text-decoration:none;text-align:center">🌐 فتح</a>
<button class=btn-gold onclick="quickPingD({rid})" style="padding:4px 6px;font-size:10px">Ping</button>
<div class=row style="gap:2px"><button class=btn-gold onclick="editDish({rid})" style="padding:3px 5px;font-size:10px">✏️</button><button class=btn-del onclick="askDel('/del_dish/{rid}',{rid})" style="padding:3px 5px;font-size:10px">🗑</button></div>
</div>
</div>
</div>'''
            return f'<div style="max-width:1000px;margin:0 auto"><div class=card small><div class=row style="justify-content:space-between"><h3 style="margin:0;font-size:13px">الصحون - كروت صغيرة - {len(rs)}</h3><a href="/api/export/dishes" class=btn-gold style="padding:5px 8px;font-size:10px">Excel</a></div><form id=formDish class=row style="margin-top:6px;flex-wrap:wrap"><input name=dish_name placeholder="اسم" required style="flex:1;min-width:70px;padding:6px;font-size:11px"><input name=ip placeholder="IP" required style="flex:1;min-width:80px;padding:6px;font-size:11px"><input name=location placeholder="موقع" style="flex:1;min-width:70px;padding:6px;font-size:11px"><button class=btn-gold style="padding:6px 10px;font-size:11px">+ إضافة</button></form></div><div class=grid-small>{rows}</div></div><script>window.editDish=function(id){{let c=document.getElementById("dish-"+id); let b=document.getElementById("editBody"); b.innerHTML="<input id=edn value=\\""+c.dataset.name+"\\"><input id=edi value=\\""+c.dataset.ip+"\\"><input id=edl value=\\""+c.dataset.loc+"\\"><button class=btn-gold onclick=\\"saveDish("+id+")\\" style=\\"width:100%\\">حفظ</button>"; document.getElementById("editModal").classList.add("show");}};window.saveDish=function(id){{fetch("/edit_dish/"+id,{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{dish_name:document.getElementById("edn").value,ip:document.getElementById("edi").value,location:document.getElementById("edl").value}})}}).then(r=>r.json()).then(j=>{{if(j.ok){{closeEditModal(); loadPage("dishes",true);}}}})}};window.quickPingD=function(id){{let ip=document.getElementById("dish-"+id).dataset.ip; window.open("http://"+ip,"_blank"); loadPage("ping"); setTimeout(()=>{{let el=document.getElementById("pingIp"); if(el){{el.value=ip; doSinglePing();}}}},400);}};document.getElementById("formDish").addEventListener("submit",e=>{{e.preventDefault(); fetch("/add_dish",{{method:"POST",body:new FormData(e.target)}}).then(r=>r.json()).then(j=>{{if(j.ok){{e.target.reset(); loadPage("dishes",true);}} else alert(j.msg||"خطأ");}})}});</script>'
        # MAP - بحث شغال 100%
        if v=='map':
            towers=qall("SELECT * FROM towers ORDER BY id DESC")
            tj=json.dumps([{"id":t.get('id'),"name":t.get('name') or '',"area":t.get('area') or '',"lat":float(t.get('lat') or 35.1318),"lng":float(t.get('lng') or 36.7578)} for t in towers],ensure_ascii=False)
            return f'<div class=card small style="padding:8px"><div class=row style="flex-wrap:wrap;gap:4px"><input id=mapSearch placeholder="بحث برج..." style="flex:1;min-width:100px;padding:6px;font-size:11px"><button class=btn-gold onclick="doMapSearch()" style="padding:6px 8px;font-size:11px">بحث</button><button class=btn-gold onclick="locateMe()" style="background:#22c55e;color:#fff;padding:6px 8px;font-size:11px">موقعي</button><button class=btn-gold id=addPointBtn onclick="enableAddPoint()" style="background:#f59e0b;padding:6px 8px;font-size:11px">نقطة</button><button class=btn-gold onclick="toggleMeasure()" id=measureBtn style="background:#0ea5e9;padding:6px 8px;font-size:11px">قياس</button><button class=btn-del onclick="clearMap()" style="padding:6px 8px;font-size:11px">مسح</button><span id=distanceLabel class=ip style="font-size:10px">0 كم</span><span id=searchCount style="font-size:10px;color:#888"></span></div><div id=map style="height:72vh;border-radius:10px;margin-top:6px;z-index:1"></div><div class=row style="margin-top:4px"><small id=coordsLabel style="color:#ffbe4d;font-size:10px">-</small><small style="color:#666;font-size:9px">اسحب العلامة • زوم 22 • بحث فوري</small></div></div><script>let _towers={tj}; let _allMarkers=[]; window._map=null; let measureMode=false,addPointMode=false,measurePoints=[],measureLine=null,measureMarkers=[];window.doMapSearch=function(){{let q=document.getElementById("mapSearch").value.trim().toLowerCase(); let cnt=document.getElementById("searchCount"); if(!q){{_allMarkers.forEach(m=>m.setOpacity(1)); if(cnt) cnt.textContent=""; return;}} let found=_towers.filter(t=>t.name.toLowerCase().includes(q)||t.area.toLowerCase().includes(q)); if(cnt) cnt.textContent=found.length+" نتيجة"; _allMarkers.forEach((mm,idx)=>{{let t=_towers[idx]; let visible=t.name.toLowerCase().includes(q)||t.area.toLowerCase().includes(q); mm.setOpacity(visible?1:0.2);}}); let f=found[0]; if(f&&window._map) window._map.flyTo([f.lat,f.lng],17);}};document.getElementById("mapSearch").addEventListener("input",doMapSearch);window.locateMe=function(){{if(navigator.geolocation) navigator.geolocation.getCurrentPosition(p=>{{window._map.flyTo([p.coords.latitude,p.coords.longitude],17); L.marker([p.coords.latitude,p.coords.longitude]).addTo(window._map).bindPopup("موقعك").openPopup();}});}};window.enableAddPoint=function(){{addPointMode=!addPointMode; document.getElementById("addPointBtn").textContent=addPointMode?"اضغط على الخريطة":"نقطة"; window._map.getContainer().style.cursor=addPointMode?"crosshair":""; if(addPointMode) measureMode=false;}};window.toggleMeasure=function(){{measureMode=!measureMode; document.getElementById("measureBtn").textContent=measureMode?"إلغاء":"قياس"; window._map.getContainer().style.cursor=measureMode?"crosshair":""; if(measureMode) addPointMode=false;}};window.clearMap=function(){{measurePoints=[]; if(measureLine) window._map.removeLayer(measureLine); measureMarkers.forEach(m=>window._map.removeLayer(m)); measureMarkers=[]; document.getElementById("distanceLabel").textContent="0 كم";}};setTimeout(()=>{{window._map=L.map("map",{{zoomControl:true,maxZoom:22}}).setView([35.1318,36.7578],13); let osm=L.tileLayer("https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png",{{maxZoom:22,maxNativeZoom:19}}).addTo(window._map); let sat=L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}",{{maxZoom:22,maxNativeZoom:19}}).addTo(window._map); L.control.layers({{"عادية":osm,"قمر صناعي 22":sat}}).addTo(window._map); setTimeout(()=>window._map.invalidateSize(),300); _towers.forEach(t=>{{let m=L.marker([t.lat,t.lng],{{draggable:true}}).addTo(window._map).bindPopup("<b>"+t.name+"</b><br>"+t.area+"<br><a href=\'https://www.google.com/maps?q="+t.lat+","+t.lng+"\' target=\'_blank\'>فتح بجوجل</a>"); _allMarkers.push(m); m.on("dragend",e=>{{let ll=e.target.getLatLng(); document.getElementById("coordsLabel").textContent=ll.lat.toFixed(6)+","+ll.lng.toFixed(6)+" حفظ..."; fetch("/api/update_tower_pos",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{id:t.id,lat:ll.lat,lng:ll.lng}})}}).then(r=>r.json()).then(j=>{{document.getElementById("coordsLabel").textContent=ll.lat.toFixed(6)+","+ll.lng.toFixed(6)+" ✓";}});}});}}); window._map.on("click",e=>{{document.getElementById("coordsLabel").textContent=e.latlng.lat.toFixed(6)+","+e.latlng.lng.toFixed(6); if(measureMode){{measurePoints.push(e.latlng); let mk=L.marker(e.latlng).addTo(window._map); measureMarkers.push(mk); if(measureLine) window._map.removeLayer(measureLine); if(measurePoints.length>1){{measureLine=L.polyline(measurePoints,{{color:"#ffbe4d",weight:3,dashArray:"6,6"}}).addTo(window._map); let d=0; for(let i=1;i<measurePoints.length;i++) d+=measurePoints[i-1].distanceTo(measurePoints[i]); document.getElementById("distanceLabel").textContent=(d/1000).toFixed(3)+" كم";}} return;}} if(addPointMode){{let lat=e.latlng.lat, lng=e.latlng.lng; L.popup().setLatLng(e.latlng).setContent("<div><b>كرت جديد</b><br><input id=np_name placeholder=\\"اسم\\" style=\\"width:100%;margin:3px 0;padding:5px\\"><input id=np_area placeholder=\\"منطقة\\" style=\\"width:100%;margin:3px 0;padding:5px\\"><button class=btn-gold onclick=\\"saveNewPoint("+lat+","+lng+")\\" style=\\"width:100%\\">حفظ</button></div>").openOn(window._map);}}}}); window.saveNewPoint=function(lat,lng){{let n=document.getElementById("np_name").value||"كرت جديد"; let a=document.getElementById("np_area").value||""; fetch("/add_tower",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{name:n,area:a,lat:lat,lng:lng}})}}).then(r=>r.json()).then(j=>{{window._map.closePopup(); if(j.ok){{let m=L.marker([lat,lng],{{draggable:true}}).addTo(window._map).bindPopup(n); _allMarkers.push(m); _towers.push({{id:Date.now(),name:n,area:a,lat:lat,lng:lng}});}} alert("تم");}});}};}},300);</script>'
        if v=='ping':
            return '''<div class=card small><h3 style="margin:0 0 6px;font-size:13px">📶 Ping</h3><div class=row style="gap:4px"><input id=pingIp placeholder="192.168.1.1" style="flex:1;padding:6px;font-size:11px"><input id=pingPort value="80" style="width:60px;padding:6px;font-size:11px"><button class=btn-gold onclick="doSinglePing()" style="background:#22c55e;color:#fff;padding:6px 8px;font-size:11px">Ping</button><button class=btn-gold onclick="doTcpPing()" style="background:#0ea5e9;padding:6px 8px;font-size:11px">TCP</button><button class=btn-gold onclick="openInChrome()" style="background:#ffbe4d;padding:6px 8px;font-size:11px">🌐 كروم</button></div><div id=pingResult class=pingBox style="font-size:11px;min-height:40px">جاهز</div><div class=row style="margin-top:6px"><button class=btn-gold onclick="pingAllDishes()" style="flex:1;background:#ffbe4d;color:#111;padding:6px;font-size:11px">فحص كل الصحون</button><button class=btn-gold onclick="clearPing()" style="padding:6px;font-size:11px">مسح</button></div></div><div class=card small><h4 style="margin:0 0 6px;font-size:12px">صحون سريعة - اضغط يفتح كروم</h4><div id=quickDishes style="font-size:11px">...</div></div><script>
            window.openInChrome=function(){let ip=document.getElementById('pingIp').value.trim(); if(!ip) return; window.open('http://'+ip,'_blank');};
            window.doSinglePing=async function(){let ip=document.getElementById('pingIp').value.trim(); if(!ip)return; let out=document.getElementById('pingResult'); out.textContent='جاري '+ip+'...'; try{let r=await fetch('/api/ping?ip='+encodeURIComponent(ip),{cache:'no-store'}); let j=await r.json(); out.textContent=j.out;}catch(e){out.textContent='خطأ';}};
            window.doTcpPing=async function(){let ip=document.getElementById('pingIp').value.trim(); let p=document.getElementById('pingPort').value||'80'; let out=document.getElementById('pingResult'); try{let r=await fetch('/api/ping_tcp?ip='+encodeURIComponent(ip)+'&port='+p); let j=await r.json(); out.textContent=j.out;}catch(e){out.textContent='خطأ';}};
            window.clearPing=function(){document.getElementById('pingResult').textContent='جاهز';};
            window.pingAllDishes=async function(){let out=document.getElementById('pingResult'); out.textContent='جاري...\\n'; try{let r=await fetch('/api/search?q=192',{cache:'no-store'}); let d=await r.json(); for(let dish of d.filter(x=>x.page=='dishes').slice(0,15)){out.textContent+='فحص '+dish.sub+'\\n'; try{let pr=await fetch('/api/ping?ip='+encodeURIComponent(dish.sub)); let pj=await pr.json(); out.textContent+=pj.out+'\\n';}catch(e){} await new Promise(r=>setTimeout(r,100));}}catch(e){out.textContent='خطأ';}};
            (async()=>{try{let r=await fetch('/api/search?q=192',{cache:'no-store'}); let d=await r.json(); let h=''; d.filter(x=>x.page=='dishes').slice(0,10).forEach(x=>{h+='<div class=rowlog style="padding:4px"><span style="font-size:11px">'+x.sub+' - '+x.title+'</span><div class=row><a href="http://'+x.sub+'" target="_blank" class=btn-gold style="padding:3px 6px;font-size:10px;text-decoration:none">🌐</a><button class=btn-gold onclick="document.getElementById(\\'pingIp\\').value=\\''+x.sub+'\\'; doSinglePing()" style="padding:3px 6px;font-size:10px">Ping</button></div></div>';}); document.getElementById('quickDishes').innerHTML=h||'لا يوجد';}catch(e){}})();
            </script>'''
        if v=='logs':
            try:
                rs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 300")
                rows="".join([f"<div class=card small rowlog style='border-right:3px solid #ffbe4d;padding:6px'><div><b style='font-size:11px'>{esc(r.get('user_phone',''))}</b> <span class=badge style='font-size:9px'>{esc(r.get('action',''))}</span><br><small style='font-size:10px'>{esc(r.get('detail',''))}</small></div><small class=time style='font-size:9px'>{esc(r.get('time',''))}</small></div>" for r in rs])
                if not rows:
                    rows='<div class=card small style="text-align:center;padding:10px;font-size:11px">السجل فاضي - يسجل كلشي تلقائيا<br><button class=btn-gold onclick="fetch(\'/api/seed_log\',{method:\'POST\'}).then(()=>loadPage(\'logs\',true))" style="padding:4px 8px;font-size:10px">اختبار</button></div>'
                return f'<div class=card small row style="justify-content:space-between"><h3 style="margin:0;font-size:12px">السجل - يسجل كل العمليات - {len(rs)}</h3><div class=row style="gap:4px"><a href="/api/export/logs" class=btn-gold style="text-decoration:none;background:#22c55e;color:#fff;padding:4px 8px;font-size:10px">Excel</a><button class=btn-gold onclick="fetch(\'/api/seed_log\',{method:\'POST\'}).then(()=>loadPage(\'logs\',true))" style="padding:4px 8px;font-size:10px">اختبار</button><button class=btn-del onclick="if(confirm(\'مسح؟\'))fetch(\'/api/clear_logs\',{method:\'POST\'}).then(()=>loadPage(\'logs\',true))" style="padding:4px 8px;font-size:10px">مسح</button></div></div>{rows}'
            except Exception as e:
                return f"<div class=card small>خطأ بالسجل: {esc(str(e))}<br><button class=btn-gold onclick=\"fetch('/api/seed_log',{{method:'POST'}}).then(()=>loadPage('logs',true))\">اصلاح</button></div>"
        if v=='subs':
            rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 200")
            rows="".join([f"<div class=card small id=sub-{r.get('id')} data-name='{esc(r.get('name') or '')}' data-phone='{esc(r.get('phone') or '')}' data-note='{esc(r.get('note') or '')}' style='padding:6px'><div class=row style='justify-content:space-between'><div><b style='font-size:11px'>{esc(r.get('name') or '')}</b><br><small style='font-size:10px'>{esc(r.get('phone') or '')}</small></div><div class=row style='gap:2px'><button class=btn-gold onclick=\"openEditSub({r.get('id')})\" style='padding:3px 6px;font-size:10px'>✏️</button><button class=btn-del onclick=\"askDel('/del_sub/{r.get('id')}',{r.get('id')})\" style='padding:3px 6px;font-size:10px'>🗑</button></div></div></div>" for r in rs])
            return f'<div class=card small><h3 style="margin:0 0 6px;font-size:12px">المشتركين - {len(rs)}</h3><form id=formSub class=row style="flex-wrap:wrap;gap:4px"><input name=name placeholder="اسم" required style="flex:1;min-width:60px;padding:5px;font-size:11px"><input name=phone placeholder="رقم" style="flex:1;min-width:70px;padding:5px;font-size:11px"><input name=note placeholder="ملاحظة" style="flex:1;min-width:60px;padding:5px;font-size:11px"><button class=btn-gold style="padding:5px 10px;font-size:11px">+ إضافة</button></form></div><div class=grid-small>{rows}</div><script>window.openEditSub=id=>{{let c=document.getElementById("sub-"+id); let b=document.getElementById("editBody"); b.innerHTML=\'<input id=esn value="\'+c.dataset.name+\'"><input id=esp value="\'+c.dataset.phone+\'"><input id=esno value="\'+c.dataset.note+\'"><button class=btn-gold onclick="saveSub(\'+id+\')" style="width:100%">حفظ</button>\'; document.getElementById("editModal").classList.add("show");}}; window.saveSub=id=>{{fetch("/edit_sub/"+id,{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{name:document.getElementById("esn").value,phone:document.getElementById("esp").value,note:document.getElementById("esno").value}})}}).then(r=>r.json()).then(()=>{{closeEditModal(); loadPage("subs",true);}})}}; document.getElementById("formSub").addEventListener("submit",e=>{{e.preventDefault(); fetch("/add_sub",{{method:"POST",body:new FormData(e.target)}}).then(r=>r.json()).then(j=>{{if(j.ok){{e.target.reset(); loadPage("subs",true);}}}})}});</script>'
        if v=='ledger':
            rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 200")
            rows="".join([f"<div class=card small id=led-{r.get('id')} data-name='{esc(r.get('name') or '')}' data-amount='{r.get('amount')}' data-note='{esc(r.get('note') or '')}' style='padding:6px'><div class=row style='justify-content:space-between'><div><b style='font-size:11px'>{esc(r.get('name') or '')}</b> <span class=ip style='font-size:10px'>{r.get('amount')}</span></div><div class=row style='gap:2px'><button class=btn-gold onclick=\"openEditLed({r.get('id')})\" style='padding:3px 5px;font-size:10px'>✏️</button><button class=btn-del onclick=\"askDel('/del_ledger/{r.get('id')}',{r.get('id')})\" style='padding:3px 5px;font-size:10px'>🗑</button></div></div></div>" for r in rs])
            return f'<div class=card small><h3 style="margin:0 0 6px;font-size:12px">الحسابات - {len(rs)}</h3><form id=formLed class=row style="flex-wrap:wrap;gap:4px"><input name=name placeholder="اسم" required style="flex:1;min-width:60px;padding:5px;font-size:11px"><input name=amount type=number step=0.01 placeholder="مبلغ" required style="flex:1;min-width:60px;padding:5px;font-size:11px"><input name=note placeholder="ملاحظة" style="flex:1;min-width:60px;padding:5px;font-size:11px"><select name=currency style="flex:0.4;padding:5px;font-size:11px"><option>USD</option><option>SYP</option></select><button class=btn-gold style="padding:5px 8px;font-size:11px">+ إضافة</button></form></div><div class=grid-small>{rows}</div><script>window.openEditLed=id=>{{let c=document.getElementById("led-"+id); let b=document.getElementById("editBody"); b.innerHTML=\'<input id=eln value="\'+c.dataset.name+\'"><input id=ela value="\'+c.dataset.amount+\'"><button class=btn-gold onclick="saveLed(\'+id+\')" style="width:100%">حفظ</button>\'; document.getElementById("editModal").classList.add("show");}}; window.saveLed=id=>{{fetch("/edit_ledger/"+id,{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{name:document.getElementById("eln").value,amount:document.getElementById("ela").value,note:"",currency:"USD"}})}}).then(()=>{{closeEditModal(); loadPage("ledger",true);}})}}; document.getElementById("formLed").addEventListener("submit",e=>{{e.preventDefault(); fetch("/add_ledger",{{method:"POST",body:new FormData(e.target)}}).then(r=>r.json()).then(j=>{{if(j.ok){{e.target.reset(); loadPage("ledger",true);}}}})}});</script>'
        if v=='network':
            dishes=qall("SELECT * FROM dish_ips ORDER BY id DESC")
            rows="".join([f"<div class=card small id=net-{d.get('id')} data-ip='{esc(d.get('ip',''))}' style='padding:6px'><div class=row style='justify-content:space-between'><div><b style='font-size:11px'>{esc(d.get('dish_name') or 'صحن')}</b> <a href=\"http://{esc(d.get('ip',''))}\" target=\"_blank\" class=ip style='font-size:10px'>{esc(d.get('ip',''))}</a><br><small class=net-out style='font-size:10px;color:#888'>...</small></div><div class=row style='gap:2px'><a href=\"http://{esc(d.get('ip',''))}\" target=\"_blank\" class=btn-gold style='padding:4px 6px;font-size:10px;text-decoration:none'>🌐</a><button class=btn-gold onclick='checkOne({d.get('id')})' style='padding:4px 6px;font-size:10px'>فحص</button></div></div></div>" for d in dishes])
            return f'<div class=card small row style="justify-content:space-between"><h3 style="margin:0;font-size:12px">حالة الشبكة - {len(dishes)}</h3><div class=row style="gap:4px"><button class=btn-gold onclick="checkAll()" style="background:#22c55e;color:#fff;padding:4px 8px;font-size:10px">فحص الكل</button><button class=btn-gold onclick="loadPage(\'ping\')" style="padding:4px 8px;font-size:10px">Ping</button></div></div><div class=grid-small>{rows}</div><script>window.checkOne=async id=>{{let c=document.getElementById("net-"+id); if(!c) return; let out=c.querySelector(".net-out"); out.textContent="جاري..."; try{{let r=await fetch("/api/ping?ip="+encodeURIComponent(c.dataset.ip),{{cache:"no-store"}}); let j=await r.json(); out.textContent=j.out; out.style.color=j.ok?"#22c55e":"#ef4444";}}catch(e){{out.textContent="خطأ";}}}}; window.checkAll=async()=>{{for(let c of document.querySelectorAll("[id^=net-]")){{await checkOne(c.id.split("-")[1]); await new Promise(r=>setTimeout(r,150));}}}}; checkAll();</script>'
        if v=='settings':
            us=qall("SELECT * FROM users ORDER BY phone DESC")
            uh="".join([f"<div class=card small id=user-{esc(u.get('phone') or '')} data-phone='{esc(u.get('phone') or '')}' data-username='{esc(u.get('username') or '')}' data-role='{esc(u.get('role') or '')}' style='padding:6px;display:inline-block;width:160px;margin:4px'><div style='text-align:center'><b style='font-size:11px'>{esc(u.get('username') or u.get('phone') or '')}</b><br><span class=ip style='font-size:9px'>{esc(u.get('phone') or '')}</span><br><span class=badge style='font-size:8px'>{esc(u.get('role') or '')}</span><br><div class=row style='justify-content:center;margin-top:4px;gap:2px'><button class=btn-gold onclick=\"openEditUser('{esc(u.get('phone') or '')}')\" style='padding:2px 6px;font-size:10px'>✏️</button><button class=btn-del onclick=\"askDel('/del_user/{esc(u.get('phone') or '')}')\" style='padding:2px 6px;font-size:10px'>🗑</button></div></div></div>" for u in us])
            return f'''
<div style="max-width:1000px;margin:0 auto">
<div class=grid-small>
<div class=card small><h4 style="margin:0 0 6px;font-size:11px">🔑 كلمة السر</h4><form id=formPass class=row style="gap:4px"><input name=newpass type=password placeholder="جديدة" required style="flex:1;padding:5px;font-size:11px"><button class=btn-gold style="padding:5px 8px;font-size:10px">حفظ</button></form></div>
<div class=card small><h4 style="margin:0 0 6px;font-size:11px">👤 يوزر جديد</h4><form id=formUser class=row style="flex-wrap:wrap;gap:4px"><input name=user_field placeholder="يوزر" required style="flex:1;padding:5px;font-size:11px"><input name=password type=password placeholder="باسورد" required style="flex:1;padding:5px;font-size:11px"><select name=role style="flex:0.5;padding:5px;font-size:11px"><option value=tech>فني</option><option value=manager>مدير</option></select><button class=btn-gold style="padding:5px 8px;font-size:10px">+ إضافة</button></form></div>
<div class=card small><h4 style="margin:0 0 6px;font-size:11px">⚙ إعدادات سريعة - بدون تحميل</h4><div class=row style="gap:4px"><button class=btn-gold onclick="toggleLangFast()" style="padding:6px 10px;font-size:11px">🌐 لغة فوري</button><button class=btn-gold onclick="toggleThemeFast()" style="padding:6px 10px;font-size:11px">🌓 ليل/نهار فوري</button><button class=btn-gold onclick="location.reload()" style="padding:6px 8px;font-size:10px">تحديث</button></div><small style="font-size:9px;color:#888">تغيير فوري بدون تحميل كامل الموقع</small></div>
<div class=card small style="border:1px solid #25D36655"><h4 style="margin:0 0 4px;font-size:11px">📞 الدعم الفني</h4><b style="font-size:12px;color:#ffbe4d">{SUPPORT_PHONE}</b><br><small style="font-size:10px">انستا: {SUPPORT_INSTA}</small><br><a href="https://wa.me/{SUPPORT_WA.replace("+","")}" target="_blank" style="display:inline-block;margin-top:4px;background:#25D366;color:#fff;padding:4px 8px;border-radius:6px;text-decoration:none;font-size:10px">💬 واتساب</a></div>
</div>
<div style="margin-top:8px"><h4 style="font-size:12px;margin:0 0 6px">اليوزرات - كروت صغيرة على طرف - {len(us)}</h4><div style="display:flex;flex-wrap:wrap">{uh}</div></div>
</div>
<script>
window.openEditUser=ph=>{{let c=document.getElementById("user-"+ph); let b=document.getElementById("editBody"); b.innerHTML='<input id=eu_ph value="'+c.dataset.phone+'"><input id=eu_pass type=password placeholder="باسورد جديد فارغ = بدون تغيير"><select id=eu_role><option value=tech>فني</option><option value=manager>مدير</option></select><button class=btn-gold onclick="saveUser(\\''+ph+'\\')" style="width:100%">حفظ</button>'; document.getElementById("eu_role").value=c.dataset.role; document.getElementById("editModal").classList.add("show");}};
window.saveUser=old=>{{let fd=new URLSearchParams({{old_phone:old,phone:document.getElementById("eu_ph").value,role:document.getElementById("eu_role").value,password:document.getElementById("eu_pass").value}}); fetch("/edit_user",{{method:"POST",body:fd}}).then(r=>r.json()).then(j=>{{if(j.ok){{closeEditModal(); loadPage("settings",true);}} else alert(j.msg||"خطأ");}})}};
document.getElementById("formPass").addEventListener("submit",e=>{{e.preventDefault(); fetch("/change_pass",{{method:"POST",body:new FormData(e.target)}}).then(r=>r.json()).then(j=>{{if(j.ok){{e.target.reset(); alert("تم");}}}})}});
document.getElementById("formUser").addEventListener("submit",e=>{{e.preventDefault(); fetch("/add_user",{{method:"POST",body:new FormData(e.target)}}).then(r=>r.json()).then(j=>{{if(j.ok){{e.target.reset(); loadPage("settings",true);}} else alert(j.msg||"خطأ");}})}});
</script>'''
        return "<div class=card small>404</div>"
    except Exception as e:
        traceback.print_exc()
        return f"<div class=card small style='background:#ef4444;color:#fff'>خطأ: {esc(str(e))}<br><pre style='font-size:10px'>{esc(traceback.format_exc()[:1000])}</pre></div>"

def layout(c,v='home'):
    try:
        th=session.get('theme','dark')
        is_dark=(th=='dark')
        bg='radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 60%, #070a1f 100%)' if is_dark else '#f1f5f9'
        card_bg='#1e2433f2' if is_dark else '#ffffff'
        txt='#ffffff' if is_dark else '#0f172a'
        border='#ffffff14' if is_dark else '#e2e8f0'
        cur_user=qone("SELECT * FROM users WHERE phone=?",(session.get('phone') or '',)) or {}
        role=cur_user.get('role') or session.get('role') or 'tech'
        lang=session.get('lang','ar')
        dir_attr='rtl' if lang=='ar' else 'ltr'
        return f"""<html dir={dir_attr}><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>OMAIA ISP - {SUPPORT_PHONE}</title>
<link rel=stylesheet href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'>
<style>
:root{{--ease:cubic-bezier(.16,1,.3,1);}}
*{{box-sizing:border-box;font-family:system-ui}}body{{margin:0;background:{bg};color:{txt};overflow-x:hidden;transition:background .4s var(--ease),color .4s var(--ease)}}body.light{{background:#f1f5f9;color:#0f172a}}
.top{{position:fixed;top:0;left:0;right:0;height:54px;background:#0f172af0;backdrop-filter:blur(16px);display:flex;align-items:center;justify-content:space-between;padding:0 10px;z-index:1003;border-bottom:1px solid #ffffff12}}
.sidebar{{position:fixed;top:0;right:0;width:260px;height:100%;background:linear-gradient(180deg,#0f172a 0%,#070e22 100%);z-index:1002;padding-top:62px;transform:translateX(110%);transition:transform .5s var(--ease);overflow-y:auto;box-shadow:-8px 0 24px #0005}}
.sidebar.active{{transform:none}}
.sidebar a{{display:flex;gap:10px;padding:10px 14px;margin:5px 10px;color:#cbd5e1;text-decoration:none;border-radius:10px;background:#ffffff08;font-size:13px;transition:.3s}} .sidebar a:hover{{background:#ffffff14;transform:translateX(-4px)}} .sidebar a.active{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:800}}
#overlay{{position:fixed;inset:0;background:#0006;z-index:1001;display:none}} #overlay.show{{display:block}}
.main{{margin-top:62px;padding:8px;min-height:90vh}}
.card{{background:{card_bg};color:{txt};padding:10px;border-radius:12px;margin-bottom:8px;border:1px solid {border};animation:fadeUp .4s var(--ease) both;transition:transform .3s var(--ease),box-shadow .3s}} .card.small{{padding:8px;border-radius:10px;font-size:12px}} .card:hover{{transform:translateY(-2px);box-shadow:0 6px 16px #0002}}
@keyframes fadeUp{{from{{opacity:0;transform:translateY(10px)}}to{{opacity:1;transform:translateY(0)}}}}
.grid-small{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}} @media(max-width:600px){{.grid-small{{grid-template-columns:repeat(auto-fill,minmax(130px,1fr))}}}}
.stat{{cursor:pointer;text-align:center}} .stat h4{{margin:2px 0;font-size:11px;color:#94a3b8}} .stat h2{{margin:2px 0;font-size:20px}} .ico{{font-size:18px;margin-bottom:4px}}
.row{{display:flex;gap:6px;align-items:center;flex-wrap:wrap}} .col{{display:flex;flex-direction:column;gap:4px}}
.btn-gold{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;padding:6px 10px;border:0;border-radius:8px;font-weight:700;font-size:11px;cursor:pointer;transition:.3s}} .btn-gold:active{{transform:scale(.94)}}
.btn-del{{background:#ef4444;color:#fff;padding:5px 8px;border:0;border-radius:8px;font-size:11px;cursor:pointer}} 
.ip{{background:#000;color:#ffbe4d;padding:2px 6px;border-radius:6px;font-family:monospace;font-size:10px;text-decoration:none}} .ip:hover{{background:#ffbe4d;color:#000}}
.pingBox{{margin-top:6px;background:#000a;border:1px solid #ffffff12;border-radius:8px;padding:8px;font-family:monospace;min-height:36px;white-space:pre-wrap;font-size:11px;color:#22c55e}}
.rowlog{{display:flex;justify-content:space-between;padding:6px 8px;border-bottom:1px dashed #ffffff10;gap:6px;font-size:11px}} .badge{{background:#ffbe4d;color:#111;padding:1px 6px;border-radius:6px;font-size:9px;font-weight:700}} .time{{color:#64748b;font-size:9px}}
.tower-card{{border:1px solid #ffbe4d22}} .tower-head{{display:flex;justify-content:space-between}} .tower-title{{font-weight:700}} .coords{{color:#ffbe4d;font-size:9px}} .tower-body{{margin-top:6px;border-top:1px dashed #ffffff10;padding-top:6px}} .dish-list{{margin-top:6px;display:flex;flex-direction:column;gap:4px}} .dish-mini{{display:flex;justify-content:space-between;align-items:center;background:#ffffff06;padding:6px 8px;border-radius:8px;font-size:11px}} .dish-mini.small{{padding:4px 6px}}
#delModal,#editModal{{position:fixed;inset:0;background:#000a;display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:.3s;z-index:2000}} #delModal.show,#editModal.show{{opacity:1;pointer-events:auto}} #delBox,#editBox{{background:{card_bg};color:{txt};padding:16px;border-radius:12px;width:92%;max-width:400px;transform:scale(.9);transition:.3s}} #delModal.show #delBox,#editModal.show #editBox{{transform:scale(1)}}
input,select{{padding:6px 8px;border-radius:8px;border:1px solid {border};background:#ffffff07;color:{txt};font-size:11px}} input:focus{{border-color:#ffbe4d88;outline:none}}
.wa-float{{position:fixed;bottom:16px;left:16px;width:48px;height:48px;background:#25D366;color:#fff;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:22px;text-decoration:none;z-index:999;box-shadow:0 4px 12px #0004;animation:pulse 2s infinite}} @keyframes pulse{{0%{{box-shadow:0 0 0 0 #25D36688}}70%{{box-shadow:0 0 0 12px #25D36600}}100%{{box-shadow:0 0 0 0 #25D36600}}}}
</style></head><body class="{'dark' if is_dark else 'light'}">
<div id=overlay onclick="toggleSb(false)"></div>
<div class=sidebar id=sb><div style='padding:0 12px 8px;border-bottom:1px solid #ffffff0a'><b style="font-size:14px">OMAIA <span style='color:#ffbe4d'>ISP</span></b><br><small style="font-size:10px">{esc(cur_user.get('username') or session.get('phone') or '')} • {role}</small><br><small style="font-size:9px;color:#25D366">📞 {SUPPORT_PHONE} • {SUPPORT_INSTA}</small></div>
<a href="javascript:loadPage('home')" id=nav-home>🏠 الرئيسية</a>
<a href="javascript:loadPage('towers')" id=nav-towers>🗼 الأبراج</a>
<a href="javascript:loadPage('dishes')" id=nav-dishes>📡 الصحون صغيرة</a>
<a href="javascript:loadPage('map')" id=nav-map>🗺 الخريطة</a>
<a href="javascript:loadPage('ping')" id=nav-ping>📶 بنج + كروم</a>
<a href="javascript:loadPage('network')" id=nav-network>📊 الشبكة</a>
<a href="javascript:loadPage('subs')" id=nav-subs>👥 مشتركين</a>
<a href="javascript:loadPage('ledger')" id=nav-ledger>📒 حسابات</a>
<a href="javascript:loadPage('logs')" id=nav-logs>📜 السجل شغال</a>
<a href="javascript:loadPage('settings')" id=nav-settings>⚙ إعدادات صغيرة</a>
<div style='padding:8px 12px;margin-top:8px;border-top:1px dashed #ffffff10'><small style="font-size:9px">الدعم: {SUPPORT_PHONE}<br>انستا: {SUPPORT_INSTA}<br><a href="https://wa.me/{SUPPORT_WA.replace("+","")}" target="_blank" style="color:#25D366">واتساب</a></small></div>
<a href="javascript:logoutFast()" style='margin-top:6px;background:#ef444418;font-size:11px'>🚪 خروج</a></div>
<div class=top><div class=row><span onclick="toggleSb()" style='font-size:20px;cursor:pointer;padding:4px 8px;background:#ffffff0a;border-radius:8px'>☰</span><input id=topsearch placeholder='بحث سريع...' oninput="globalSearchTop(this.value)" style='width:36px;transition:.4s;background:#1f2937;border:1px solid #ffffff15;color:#fff;padding:6px 8px;border-radius:8px;font-size:11px' onfocus="this.style.width='140px'" onblur="setTimeout(()=>this.style.width='36px',200)"></div><b style="font-size:14px">OMAIA <span style='color:#ffbe4d'>ISP</span></b><div class=row style="gap:4px"><button onclick="toggleLangFast()" title="لغة فوري بدون تحميل" style='background:#ffffff0a;color:#fff;border:1px solid #ffffff14;padding:6px 8px;border-radius:8px;font-size:11px'>🌐</button><button onclick="toggleThemeFast()" title="ليل/نهار فوري" style='background:#ffffff0a;color:#fff;border:1px solid #ffffff14;padding:6px 8px;border-radius:8px;font-size:11px'>🌓</button></div></div>
<div id=searchResults style='position:fixed;top:58px;right:8px;max-width:300px;width:90%;background:#1e2433;border:1px solid #ffffff15;border-radius:10px;z-index:1500;display:none;max-height:50vh;overflow:auto;font-size:11px'></div>
<div class=main id=mn>{c}</div>
<div id=delModal><div id=delBox><div style='text-align:center;font-size:24px'>🗑</div><h3 style='text-align:center;margin:6px 0;font-size:13px'>تأكيد الحذف؟</h3><div class=row style='margin-top:10px'><button onclick="closeDel()" style='flex:1;padding:8px;border-radius:8px;background:transparent;color:{txt};border:1px solid {border};font-size:11px'>تراجع</button><button id=delYes style='flex:1;padding:8px;border-radius:8px;background:#ef4444;color:#fff;border:0;font-weight:700;font-size:11px'>حذف</button></div></div></div>
<div id=editModal><div id=editBox><div class=row style='justify-content:space-between'><h3 style='margin:0;font-size:12px'>تعديل</h3><button onclick="closeEditModal()" style='width:26px;height:26px;border-radius:50%;background:#ffffff12;border:0;color:{txt}'>✕</button></div><div id=editBody style='margin-top:8px'></div></div></div>
<a href="https://wa.me/{SUPPORT_WA.replace("+","")}" target="_blank" class=wa-float>💬</a>
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
 mn.innerHTML='<div class=card small>جاري التحميل...</div>';
 try{{let r=await fetch('/api/page?v='+v,{{cache:'no-store'}}); if(!r.ok){{let txt=await r.text(); mn.innerHTML=txt; execScripts(); return;}} let h=await r.text(); pageCache[v]=h; mn.innerHTML=h; execScripts();}}catch(e){{mn.innerHTML='<div class=card small>خطأ '+e+'</div>';}}
}}
function execScripts(){{let mn=document.getElementById('mn'); mn.querySelectorAll('script').forEach(old=>{{let s=document.createElement('script'); s.textContent=old.textContent; document.body.appendChild(s); old.remove();}});}}
function askDel(url,id){{window._delUrl=url; window._delId=id; document.getElementById('delModal').classList.add('show');}}
function closeDel(){{document.getElementById('delModal').classList.remove('show'); window._delUrl=null;}}
window.closeEditModal=()=>document.getElementById('editModal').classList.remove('show');
document.getElementById('delYes').onclick=async()=>{{
 if(!window._delUrl) return; let btn=document.getElementById('delYes'); btn.textContent='...'; btn.disabled=true;
 try{{let r=await fetch(window._delUrl,{{cache:'no-store'}}); let j=await r.json(); if(j.ok){{let el=document.getElementById('dish-'+window._delId)||document.getElementById('tower-'+window._delId)||document.getElementById('sub-'+window._delId)||document.getElementById('led-'+window._delId)||document.getElementById('net-'+window._delId)||document.getElementById('user-'+window._delId); if(el){{el.style.transform='scale(.9)'; el.style.opacity='0'; setTimeout(()=>{{el.remove(); delete pageCache[cur];}},250);}} closeDel();}} else alert(j.msg||'ممنوع');}}catch(e){{alert(e);}} btn.textContent='حذف'; btn.disabled=false;
}};
window.toggleLangFast=async()=>{{
 try{{
  let r=await fetch('/toggle_lang',{{cache:'no-store'}}); let j=await r.json();
  let lang=j.lang||'ar';
  document.documentElement.dir=lang==='ar'?'rtl':'ltr';
  localStorage.setItem('lang',lang);
  // تحديث فوري بدون تحميل كامل
  document.querySelectorAll('[data-ar]').forEach(el=>{{el.textContent=lang==='ar'?el.dataset.ar:el.dataset.en;}});
  let t=document.createElement('div'); t.textContent=lang==='ar'?'تم التحويل للعربية':'Switched to English'; t.style='position:fixed;top:60px;left:50%;transform:translateX(-50%);background:#ffbe4d;color:#111;padding:6px 12px;border-radius:8px;z-index:9999;font-size:11px'; document.body.appendChild(t); setTimeout(()=>t.remove(),1500);
 }}catch(e){{console.log(e);}}
}};
window.toggleThemeFast=async()=>{{
 try{{
  let r=await fetch('/toggle_theme',{{cache:'no-store'}}); let j=await r.json();
  let theme=j.theme||'dark';
  document.body.className=theme;
  document.body.style.background=theme==='dark'?'radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 60%, #070a1f 100%)':'#f1f5f9';
  localStorage.setItem('theme',theme);
 }}catch(e){{document.body.classList.toggle('light'); document.body.classList.toggle('dark');}}
}};
window.globalSearchTop=async q=>{{let box=document.getElementById('searchResults'); if(!q||q.length<2){{box.style.display='none'; return;}} try{{let r=await fetch('/api/search?q='+encodeURIComponent(q),{{cache:'no-store'}}); let d=await r.json(); if(!d.length){{box.style.display='none'; return;}} let h=''; d.forEach(x=>{{h+='<div onclick="loadPage(\\''+x.page+'\\');document.getElementById(\\'searchResults\\').style.display=\\'none\\'" style="padding:8px 10px;cursor:pointer;border-bottom:1px solid #ffffff08"><b style="font-size:11px">'+x.title+'</b><br><small style="color:#888;font-size:10px">'+x.sub+'</small></div>';}}); box.innerHTML=h; box.style.display='block';}}catch(e){{}}}};
window.logoutFast=async()=>{{try{{await fetch('/api/logout',{{method:'POST'}});}}catch(e){{}} localStorage.clear(); sessionStorage.clear(); location.replace('/login');}};
window.addEventListener('popstate',e=>{{let v='home'; if(e.state&&e.state.page) v=e.state.page; else {{let p=new URLSearchParams(location.search); v=p.get('v')||'home';}} loadPage(v,false,false);}});
loadPage(cur,true,false);
</script></body></html>"""
    except Exception as e:
        traceback.print_exc()
        return f"Layout error {e}"

if __name__=='__main__':
    port=int(os.environ.get("PORT","10000"))
    print(f"OMAIA PERFECT running on {port}")
    app.run(host='0.0.0.0',port=port,debug=False)

@app.route('/api/stats')
@login_required
def api_stats():
    ns,nd,nt,nl=get_counts()
    return jsonify(subs=ns,dishes=nd,towers=nt,ledger=nl)

@app.route('/debug')
def debug_route():
    return jsonify(use_pg=USE_PG,counts=get_counts(),support=SUPPORT_PHONE)
