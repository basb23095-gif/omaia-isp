from flask import Flask, request, redirect, session, jsonify, Response
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, html, ipaddress, subprocess, json, socket, platform, io, csv, datetime, re, threading, time, traceback
try:
    import psycopg2, psycopg2.extras
    from psycopg2 import pool as pg_pool
    PG=True
except:
    psycopg2=None; pg_pool=None; PG=False
import sqlite3
from collections import defaultdict
app=Flask(__name__)
app.secret_key=os.environ.get("SECRET_KEY","omia-v11-fast-2026")
app.config['PERMANENT_SESSION_LIFETIME']=datetime.timedelta(minutes=30)
DATABASE_URL=os.environ.get("DATABASE_URL","").strip().replace("postgres://","postgresql://",1)
USE_PG=bool(DATABASE_URL.startswith("postgresql://") and PG)
_pg_pool=None
_plock=threading.Lock()
_sqlite_conn=None
_slock=threading.Lock()
_cache={}
_clock=threading.Lock()
SUPPORT_WA="905345851045"
SUPPORT_INSTA="af_20_1999"
def init_pool():
    global _pg_pool, USE_PG
    if not USE_PG or not pg_pool: return
    with _plock:
        if _pg_pool: return
        try:
            _pg_pool=pg_pool.ThreadedConnectionPool(1,5,dsn=DATABASE_URL,sslmode='require',connect_timeout=2)
        except:
            _pg_pool=None; USE_PG=False
init_pool()
def esc(s): return html.escape(str(s or ''), quote=True)
def get_conn():
    global USE_PG, _sqlite_conn
    if USE_PG and _pg_pool:
        try:
            c=_pg_pool.getconn()
            if getattr(c,'closed',1)==0: return c
        except:
            try: return psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=2)
            except: USE_PG=False
    elif USE_PG:
        try: return psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=2)
        except: USE_PG=False
    with _slock:
        if _sqlite_conn is None:
            _sqlite_conn=sqlite3.connect(os.path.join(os.path.dirname(__file__),"omia.db"),check_same_thread=False,timeout=5,isolation_level=None)
            _sqlite_conn.row_factory=sqlite3.Row
            try: _sqlite_conn.execute("PRAGMA journal_mode=WAL;")
            except: pass
        return _sqlite_conn
def put_conn(c):
    if USE_PG and _pg_pool and c and hasattr(c,'closed'):
        try: _pg_pool.putconn(c)
        except:
            try: c.close()
            except: pass
    elif USE_PG and c and hasattr(c,'closed'):
        try: c.close()
        except: pass
def qall(q,a=()):
    cn=None
    try:
        cn=get_conn()
        if USE_PG and hasattr(cn,'cursor'):
            cur=cn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(q.replace("?","%s"),a)
            r=[dict(x) for x in cur.fetchall()]; cur.close(); put_conn(cn); return r
        else:
            with _slock: return [dict(x) for x in cn.execute(q,a).fetchall()]
    except Exception as e:
        print(f"[qall]{e}"); 
        if cn and USE_PG and hasattr(cn,'closed'):
            try: put_conn(cn)
            except: pass
        return []
def qone(q,a=()): 
    r=qall(q,a); return r[0] if r else None
def qexec(q,a=()):
    cn=None
    try:
        cn=get_conn()
        if USE_PG and hasattr(cn,'cursor'):
            cur=cn.cursor(); cur.execute(q.replace("?","%s"),a); cn.commit(); cur.close(); put_conn(cn)
        else:
            with _slock: cn.execute(q,a); cn.commit()
        return True
    except Exception as e:
        print(f"[qexec]{e}"); 
        if cn and USE_PG and hasattr(cn,'closed'):
            try: cn.rollback(); put_conn(cn)
            except: pass
        return False
def add_log_async(phone,action,detail):
    def _run():
        try:
            now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)",(phone or 'sys',action,detail,now))
            qexec("INSERT INTO notifications(title,msg,time) VALUES(?,?,?)",(action,f"{phone}: {detail}",now))
            with _clock: _cache.pop('counts',None)
        except: pass
    threading.Thread(target=_run,daemon=True).start()
def get_counts():
    with _clock:
        c=_cache.get('counts')
        if c and time.time()-c[1]<8: return c[0]
    try:
        ns=(qone("SELECT COUNT(*) as c FROM subs") or {}).get('c',0)
        nd=(qone("SELECT COUNT(*) as c FROM dish_ips") or {}).get('c',0)
        nt=(qone("SELECT COUNT(*) as c FROM towers") or {}).get('c',0)
        nl=(qone("SELECT COUNT(*) as c FROM ledger") or {}).get('c',0)
        d=(ns,nd,nt,nl)
        with _clock: _cache['counts']=(d,time.time())
        return d
    except: return (0,0,0,0)
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
    if USE_PG: ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
    for s in ss: qexec(s)
    for al in ["ALTER TABLE dish_ips ADD COLUMN tower_id INTEGER","ALTER TABLE towers ADD COLUMN created_at TEXT"]:
        try: qexec(al)
        except: pass
    if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",('05344851045',generate_password_hash('admin2024'),'manager','admin'))
    if not qone("SELECT * FROM towers WHERE name=?",('نقطة حماة الرئيسية',)):
        qexec("INSERT INTO towers(name,area,lat,lng,created_at) VALUES(?,?,?,?,?)",('نقطة حماة الرئيسية','حماة',35.1318,36.7578,datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
init_db()
def login_required(f):
    @wraps(f)
    def w(*a,**kw):
        if not session.get('phone'): return redirect('/login')
        return f(*a,**kw)
    return w
def is_manager(): return (session.get('role') or '')=='manager'
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
def after(r): r.headers['Cache-Control']='no-cache'; return r
@app.route('/ping')
def ping(): return jsonify(ok=True,use_pg=USE_PG)
@app.route('/api/ping')
@login_required
def api_ping():
    ip=request.args.get('ip','').strip()
    if not is_valid_ip(ip): return jsonify(ok=False,out='IP غير صالح')
    for port in [80,443,8080,8291,22,8728]:
        s=None
        try:
            s=socket.socket(); s.settimeout(0.4)
            if s.connect_ex((ip,port))==0:
                s.close(); add_log_async(session.get('phone'),'Ping',f'{ip}:{port} مفتوح'); return jsonify(ok=True,out=f'{ip}:{port} ✓ مفتوح')
            s.close()
        except:
            try: s.close()
            except: pass
    try:
        cmd=['ping','-c','1','-W','1',ip] if platform.system().lower()!='windows' else ['ping','-n','1','-w','800',ip]
        out=subprocess.check_output(cmd,timeout=1,stderr=subprocess.STDOUT).decode(errors='ignore')
        if 'ttl=' in out.lower():
            m=re.search(r'time[=<]\s*(\d+\.?\d*)',out,re.I); ms=m.group(1) if m else ''
            add_log_async(session.get('phone'),'Ping',f'{ip} {ms}ms'); return jsonify(ok=True,out=f'{ip} {ms}ms ✓')
    except: pass
    return jsonify(ok=False,out=f'{ip} لا يرد')
@app.route('/toggle_lang')
@login_required
def toggle_lang():
    cur=session.get('lang','ar'); session['lang']='en' if cur=='ar' else 'ar'
    add_log_async(session.get('phone'),'تغيير لغة',session['lang'])
    return jsonify(ok=True,lang=session['lang'])
@app.route('/toggle_theme')
@login_required
def toggle_theme():
    cur=session.get('theme','dark'); session['theme']='light' if cur=='dark' else 'dark'
    return jsonify(ok=True,theme=session['theme'])
@app.route('/api/login_public',methods=['POST'])
def api_login_public():
    try:
        uin=request.form.get('userin','').strip(); pw=request.form.get('password','')
        u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
        if u and check_password_hash(u['password'],pw):
            session.clear(); session['phone']=u['phone']; session['username']=u.get('username') or u['phone']; session['role']=u.get('role') or 'tech'; session.permanent=False
            add_log_async(u['phone'],'دخول',f'login {uin}')
            return jsonify(ok=True)
        return jsonify(ok=False,msg='خطأ بالدخول'),401
    except Exception as e: return jsonify(ok=False,msg=str(e)),500
@app.route('/api/export/<tbl>')
@login_required
def api_export(tbl):
    add_log_async(session.get('phone'),'تصدير',tbl)
    output=io.StringIO(); output.write('\ufeff'); w=csv.writer(output)
    if tbl=='dishes':
        rows=qall("SELECT * FROM dish_ips ORDER BY id DESC"); w.writerow(['ID','اسم','IP','موقع','tower_id'])
        for r in rows: w.writerow([r.get('id',''),r.get('dish_name',''),r.get('ip',''),r.get('location',''),r.get('tower_id','')]); fname='dishes.csv'
    elif tbl=='towers':
        rows=qall("SELECT * FROM towers ORDER BY id DESC"); w.writerow(['ID','اسم','منطقة','lat','lng'])
        for r in rows: w.writerow([r.get('id',''),r.get('name',''),r.get('area',''),r.get('lat',''),r.get('lng','')]); fname='towers.csv'
    else:
        rows=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 2000"); w.writerow(['ID','يوزر','عمل','تفصيل','وقت'])
        for r in rows: w.writerow([r.get('id',''),r.get('user_phone',''),r.get('action',''),r.get('detail',''),r.get('time','')]); fname='logs.csv'
    return Response(output.getvalue(),mimetype='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename={fname}'})
@app.route('/api/clear_logs',methods=['POST'])
@login_required
@role_required_manager
def clear_logs(): qexec("DELETE FROM logs"); qexec("DELETE FROM notifications"); return jsonify(ok=True)
@app.route('/api/update_tower_pos',methods=['POST'])
@login_required
def update_tower_pos():
    try:
        d=request.json if request.is_json else request.form; tid=int(d.get('id')); lat=float(d.get('lat')); lng=float(d.get('lng'))
        qexec("UPDATE towers SET lat=?,lng=? WHERE id=?",(lat,lng,tid)); add_log_async(session.get('phone'),'تعديل موقع برج',f"ID {tid}")
        return jsonify(ok=True)
    except Exception as e: return jsonify(ok=False,msg=str(e)),400
@app.route('/api/add_dish_to_tower',methods=['POST'])
@login_required
def add_dish_to_tower():
    try:
        d=request.json if request.is_json else request.form; ip=(d.get('ip') or '').strip(); name=(d.get('dish_name') or '').strip(); loc=(d.get('location') or '').strip(); tid=d.get('tower_id')
        if not is_valid_ip(ip): return jsonify(ok=False,msg='IP غير صالح'),400
        if USE_PG: ok=qexec("INSERT INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?) ON CONFLICT (ip) DO UPDATE SET dish_name=EXCLUDED.dish_name, location=EXCLUDED.location, tower_id=EXCLUDED.tower_id",(ip,loc,name,int(tid) if tid and str(tid).isdigit() else None))
        else: ok=qexec("INSERT OR REPLACE INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?)",(ip,loc,name,int(tid) if tid and str(tid).isdigit() else None))
        if ok: add_log_async(session.get('phone'),'إضافة صحن للبرج',f"{name} {ip}"); 
        with _clock: _cache.pop('counts',None)
        return jsonify(ok=ok)
    except Exception as e: return jsonify(ok=False,msg=str(e)),500
@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')
@app.route('/login')
def login():
    return f"""<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>OMAIA</title>
<style>*{{box-sizing:border-box;font-family:system-ui}}body{{margin:0;min-height:100vh;background:radial-gradient(120% 120% at 10% 10%,#1a2344,#0a0e2a 60%);display:flex;align-items:center;justify-content:center;color:#fff}}
.card{{background:#222b45ee;border:1px solid #ffffff18;padding:18px;border-radius:14px;width:92%;max-width:340px}}
input{{width:100%;padding:11px;margin:6px 0;background:#0f1424;border:1px solid #ffffff22;color:#fff;border-radius:9px}}input:focus{{border-color:#ffbe4d;outline:none}}
.btn{{width:100%;padding:11px;border:0;border-radius:9px;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:800;cursor:pointer}}
</style></head><body>
<div class=card>
<div style='text-align:center;font-weight:900;font-size:22px;margin-bottom:8px'>OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<form id=loginForm>
<input name=userin id=userin placeholder='يوزر' required autofocus>
<input name=password id=password type=password placeholder='كلمة السر' required>
<label style='display:flex;gap:6px;font-size:12px;margin:6px 0'><input type=checkbox id=remember style='width:14px'> حفظ كلمة السر</label>
<button class=btn id=loginBtn>دخول</button>
<div id=msg style='text-align:center;color:#ff6b6b;font-size:11px;min-height:14px;margin-top:6px'></div>
</form>
<div style='margin-top:10px;border-top:1px dashed #ffffff15;padding-top:8px;text-align:center'>
<div style='display:flex;gap:8px;justify-content:center;margin-top:6px'>
<a href='https://wa.me/{SUPPORT_WA}' target=_blank style='width:36px;height:36px;background:#25D366;border-radius:50%;display:flex;align-items:center;justify-content:center;text-decoration:none'>💬</a>
<a href='https://instagram.com/{SUPPORT_INSTA}' target=_blank style='width:36px;height:36px;background:linear-gradient(45deg,#feda75,#fa7e1e,#d62976,#962fbf,#4f5bd5);border-radius:50%;display:flex;align-items:center;justify-content:center;text-decoration:none'>📷</a>
<a href='tel:+{SUPPORT_WA}' style='width:36px;height:36px;background:#0ea5e9;border-radius:50%;display:flex;align-items:center;justify-content:center;text-decoration:none'>📞</a>
</div>
<small style='font-size:10px;color:#94a3b8'>+{SUPPORT_WA} • {SUPPORT_INSTA}</small>
</div>
</div>
<script>
const u=document.getElementById('userin'),p=document.getElementById('password'),r=document.getElementById('remember');
if(localStorage.getItem('su'))u.value=localStorage.getItem('su');
if(localStorage.getItem('sp')){{p.value=localStorage.getItem('sp'); r.checked=true;}}
document.getElementById('loginForm').addEventListener('submit',async e=>{{
 e.preventDefault(); let b=document.getElementById('loginBtn'),m=document.getElementById('msg'); b.textContent='...'; b.disabled=true;
 try{{let fd=new FormData(e.target); let res=await fetch('/api/login_public',{{method:'POST',body:fd}}); let j=await res.json();
 if(j.ok){{if(r.checked){{localStorage.setItem('su',u.value); localStorage.setItem('sp',p.value);}}else{{localStorage.removeItem('su'); localStorage.removeItem('sp');}} location.replace('/dash?v=home');}}else{{m.textContent=j.msg; b.textContent='دخول'; b.disabled=false;}}
 }}catch{{m.textContent='شبكة'; b.textContent='دخول'; b.disabled=false;}}
}});
</script></body></html>"""
@app.route('/logout')
def lo(): session.clear(); return redirect('/login')
@app.route('/api/logout',methods=['POST'])
def api_logout(): session.clear(); return jsonify(ok=True)
@app.route('/dash')
@login_required
def dash(): v=request.args.get('v','home'); return layout('<div class=card small>...</div>',v)
@app.route('/api/page')
@login_required
def ap(): 
    try: return page_content(request.args.get('v','home'))
    except Exception as e: traceback.print_exc(); return f"<div class=card>خطأ {esc(str(e))}</div>",500
@app.route('/api/search')
@login_required
def s():
    q=request.args.get('q','').strip()
    if not q: return jsonify([])
    like="%"+q+"%"; op="ILIKE" if USE_PG else "LIKE"; res=[]
    try:
        for r in qall(f"SELECT * FROM dish_ips WHERE ip {op} ? OR dish_name {op} ? LIMIT 15",(like,like)):
            res.append({"title":r.get('dish_name') or r['ip'],"sub":r['ip'],"page":"dishes"})
        for r in qall(f"SELECT * FROM towers WHERE name {op} ? LIMIT 10",(like,)):
            res.append({"title":r['name'],"sub":r.get('area',''),"page":"towers"})
    except: pass
    return jsonify(res)
@app.route('/add_dish',methods=['POST'])
@login_required
def ad():
    try:
        d=request.json if request.is_json else request.form; ip=(d.get('ip') or '').strip(); name=(d.get('dish_name') or '').strip(); loc=(d.get('location') or '').strip(); tid=d.get('tower_id')
        if not is_valid_ip(ip): return jsonify(ok=False,msg='IP غير صالح'),400
        if USE_PG: ok=qexec("INSERT INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?) ON CONFLICT (ip) DO UPDATE SET dish_name=EXCLUDED.dish_name, location=EXCLUDED.location, tower_id=EXCLUDED.tower_id",(ip,loc,name,int(tid) if tid and str(tid).isdigit() else None))
        else: ok=qexec("INSERT OR REPLACE INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?)",(ip,loc,name,int(tid) if tid and str(tid).isdigit() else None))
        if ok: add_log_async(session.get('phone'),'إضافة صحن',f"{name} {ip}"); 
        with _clock: _cache.pop('counts',None)
        return jsonify(ok=ok)
    except Exception as e: return jsonify(ok=False,msg=str(e)),500
@app.route('/edit_dish/<int:i>',methods=['POST'])
@login_required
def ed(i):
    if not is_manager(): return jsonify(ok=False,msg='ممنوع'),403
    d=request.json if request.is_json else request.form
    ok=qexec("UPDATE dish_ips SET dish_name=?,ip=?,location=?,tower_id=? WHERE id=?",(d.get('dish_name',''),d.get('ip',''),d.get('location',''),d.get('tower_id') or None,i))
    if ok: add_log_async(session.get('phone'),'تعديل صحن',f"ID {i}")
    return jsonify(ok=ok)
@app.route('/del_dish/<int:i>')
@login_required
def dd(i):
    if not is_manager(): return jsonify(ok=False,msg='ممنوع'),403
    info=qone("SELECT * FROM dish_ips WHERE id=?",(i,)); ok=qexec("DELETE FROM dish_ips WHERE id=?",(i,))
    if ok: 
        with _clock: _cache.pop('counts',None)
        add_log_async(session.get('phone'),'حذف صحن',f"{info.get('dish_name','')} {info.get('ip','')}" if info else f"ID {i}")
    return jsonify(ok=ok)
@app.route('/add_tower',methods=['POST'])
@login_required
def at():
    try:
        d=request.json if request.is_json else request.form; la=float(d.get('lat') or 35.1318); ln=float(d.get('lng') or 36.7578)
        ok=qexec("INSERT INTO towers(name,area,lat,lng,created_at) VALUES(?,?,?,?,?)",(d.get('name','كرت'),d.get('area',''),la,ln,datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        if ok: add_log_async(session.get('phone'),'إضافة برج',d.get('name',''))
        return jsonify(ok=ok)
    except Exception as e: return jsonify(ok=False,msg=str(e)),500
@app.route('/del_tower/<int:i>')
@login_required
def dt(i):
    if not is_manager(): return jsonify(ok=False,msg='ممنوع'),403
    qexec("UPDATE dish_ips SET tower_id=NULL WHERE tower_id=?",(i,)); ok=qexec("DELETE FROM towers WHERE id=?",(i,))
    if ok: add_log_async(session.get('phone'),'حذف برج',f"ID {i}")
    return jsonify(ok=ok)
@app.route('/edit_tower/<int:i>',methods=['POST'])
@login_required
def et(i):
    if not is_manager(): return jsonify(ok=False,msg='ممنوع'),403
    d=request.json if request.is_json else request.form; la=float(d.get('lat') or 35.1318); ln=float(d.get('lng') or 36.7578)
    ok=qexec("UPDATE towers SET name=?,area=?,lat=?,lng=? WHERE id=?",(d.get('name',''),d.get('area',''),la,ln,i))
    if ok: add_log_async(session.get('phone'),'تعديل برج',f"ID {i}")
    return jsonify(ok=ok)
@app.route('/add_sub',methods=['POST'])
@login_required
def asub():
    d=request.json if request.is_json else request.form; ok=qexec("INSERT INTO subs(name,phone,note) VALUES(?,?,?)",(d.get('name',''),d.get('phone',''),d.get('note','')))
    if ok: add_log_async(session.get('phone'),'إضافة مشترك',d.get('name',''))
    return jsonify(ok=ok)
@app.route('/del_sub/<int:i>')
@login_required
def dsub(i):
    if not is_manager(): return jsonify(ok=False),403
    ok=qexec("DELETE FROM subs WHERE id=?",(i,))
    if ok: add_log_async(session.get('phone'),'حذف مشترك',f"ID {i}")
    return jsonify(ok=ok)
@app.route('/edit_sub/<int:i>',methods=['POST'])
@login_required
def esub(i):
    if not is_manager(): return jsonify(ok=False),403
    d=request.json if request.is_json else request.form; ok=qexec("UPDATE subs SET name=?,phone=?,note=? WHERE id=?",(d.get('name',''),d.get('phone',''),d.get('note',''),i))
    if ok: add_log_async(session.get('phone'),'تعديل مشترك',f"ID {i}")
    return jsonify(ok=ok)
@app.route('/add_ledger',methods=['POST'])
@login_required
def al():
    d=request.json if request.is_json else request.form
    try: amt=float(d.get('amount') or 0)
    except: amt=0
    ok=qexec("INSERT INTO ledger(name,amount,note,currency) VALUES(?,?,?,?)",(d.get('name',''),amt,d.get('note',''),d.get('currency','USD')))
    if ok: add_log_async(session.get('phone'),'إضافة حساب',f"{d.get('name','')} {amt}")
    return jsonify(ok=ok)
@app.route('/del_ledger/<int:i>')
@login_required
def dll(i):
    if not is_manager(): return jsonify(ok=False),403
    ok=qexec("DELETE FROM ledger WHERE id=?",(i,))
    if ok: add_log_async(session.get('phone'),'حذف حساب',f"ID {i}")
    return jsonify(ok=ok)
@app.route('/edit_ledger/<int:i>',methods=['POST'])
@login_required
def el(i):
    if not is_manager(): return jsonify(ok=False),403
    d=request.json if request.is_json else request.form
    try: amt=float(d.get('amount') or 0)
    except: amt=0
    ok=qexec("UPDATE ledger SET name=?,amount=?,note=?,currency=? WHERE id=?",(d.get('name',''),amt,d.get('note',''),d.get('currency','USD'),i))
    if ok: add_log_async(session.get('phone'),'تعديل حساب',f"ID {i}")
    return jsonify(ok=ok)
@app.route('/add_user',methods=['POST'])
@login_required
@role_required_manager
def au():
    ph=(request.form.get('phone') or request.form.get('user_field','')).strip()
    if not ph: return jsonify(ok=False,msg='رقم مطلوب'),400
    if qone("SELECT * FROM users WHERE phone=?",(ph,)): return jsonify(ok=False,msg='موجود'),400
    ok=qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",(ph,generate_password_hash(request.form.get('password','1234')),request.form.get('role','tech'),ph))
    if ok: add_log_async(session.get('phone'),'إضافة يوزر',ph)
    return jsonify(ok=ok)
@app.route('/edit_user',methods=['POST'])
@login_required
@role_required_manager
def eu():
    old=request.form.get('old_phone','').strip(); new_ph=(request.form.get('phone') or '').strip(); new_role=request.form.get('role','tech'); new_pass=request.form.get('password','').strip()
    if not old: return jsonify(ok=False,msg='خطأ'),400
    if old!=new_ph and qone("SELECT * FROM users WHERE phone=?",(new_ph,)): return jsonify(ok=False,msg='موجود'),400
    if new_pass: ok=qexec("UPDATE users SET phone=?,username=?,role=?,password=? WHERE phone=?",(new_ph,new_ph,new_role,generate_password_hash(new_pass),old))
    else: ok=qexec("UPDATE users SET phone=?,username=?,role=? WHERE phone=?",(new_ph,new_ph,new_role,old))
    if session.get('phone')==old: session['phone']=new_ph; session['role']=new_role
    if ok: add_log_async(session.get('phone'),'تعديل يوزر',old+"->"+new_ph)
    return jsonify(ok=ok)
@app.route('/del_user/<ph>')
@login_required
@role_required_manager
def du(ph):
    if ph=='05344851045': return jsonify(ok=False,msg='ممنوع'),400
    ok=qexec("DELETE FROM users WHERE phone=?",(ph,))
    if ok: add_log_async(session.get('phone'),'حذف يوزر',ph)
    return jsonify(ok=ok)
@app.route('/change_pass',methods=['POST'])
@login_required
def cp():
    d=request.json if request.is_json else request.form; np=(d.get('newpass') or '').strip()
    if not np: return jsonify(ok=False,msg='فارغة'),400
    ok=qexec("UPDATE users SET password=? WHERE phone=?",(generate_password_hash(np),session.get('phone')))
    if ok: add_log_async(session.get('phone'),'تغيير باسورد','')
    return jsonify(ok=ok)
def page_content(v):
    try:
        lang=session.get('lang','ar')
        def L(ar,en): return ar if lang=='ar' else en
        if v=='home':
            ns,nd,nt,nl=get_counts()
            logs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 8")
            lh="".join([f"<tr><td style='font-size:11px'>{esc(l.get('time',''))}</td><td style='font-size:11px'><span class=badge>{esc(l.get('action',''))}</span></td><td style='font-size:11px'>{esc(l.get('user_phone',''))}</td><td style='font-size:10px'>{esc(str(l.get('detail',''))[:50])}</td></tr>" for l in logs]) or "<tr><td colspan=4 style='font-size:11px'>فاضي - السجل شغال</td></tr>"
            return f'''
<div style="max-width:1000px;margin:0 auto">
<div class=grid-small>
<div class="card small stat" onclick="loadPage('subs')"><div class=ico>👥</div><h4>{L("مشتركين","Subs")}</h4><h2>{ns}</h2></div>
<div class="card small stat" onclick="loadPage('dishes')"><div class=ico>📡</div><h4>{L("صحون","Dishes")}</h4><h2>{nd}</h2></div>
<div class="card small stat" onclick="loadPage('towers')"><div class=ico>🗼</div><h4>{L("أبراج","Towers")}</h4><h2>{nt}</h2></div>
<div class="card small stat" onclick="loadPage('ledger')"><div class=ico>📒</div><h4>{L("حسابات","Acc")}</h4><h2>{nl}</h2></div>
</div>
<div class=card small style="margin-top:8px"><div style="display:flex;justify-content:space-between;align-items:center"><b style="font-size:12px">📜 آخر السجل - يسجل كلشي</b><button class=btn-gold onclick="loadPage('logs')" style="padding:4px 8px;font-size:10px">الكل</button></div>
<table style="width:100%;margin-top:6px;border-collapse:collapse"><thead><tr><th style="font-size:10px;text-align:right">وقت</th><th style="font-size:10px">عمل</th><th style="font-size:10px">يوزر</th><th style="font-size:10px">تفصيل</th></tr></thead><tbody>{lh}</tbody></table>
</div>
<div style="display:flex;gap:8px;justify-content:center;margin-top:10px">
<a href="https://wa.me/{SUPPORT_WA}" target="_blank" style="width:44px;height:44px;background:#25D366;border-radius:50%;display:flex;align-items:center;justify-content:center;text-decoration:none;font-size:20px">💬</a>
<a href="https://instagram.com/{SUPPORT_INSTA}" target="_blank" style="width:44px;height:44px;background:linear-gradient(45deg,#feda75,#d62976);border-radius:50%;display:flex;align-items:center;justify-content:center;text-decoration:none;font-size:18px">📷</a>
<a href="tel:+{SUPPORT_WA}" style="width:44px;height:44px;background:#0ea5e9;border-radius:50%;display:flex;align-items:center;justify-content:center;text-decoration:none;font-size:18px">📞</a>
</div>
</div>'''
        if v=='towers':
            rs=qall("SELECT * FROM towers ORDER BY id DESC")
            cards=""
            for t in rs:
                tid=t.get('id')
                dishes=qall("SELECT * FROM dish_ips WHERE tower_id=? ORDER BY id DESC",(tid,))
                dhtml="".join([f'<div class="inner-card"><span>{esc(d.get("dish_name") or d.get("ip") or "صحن")}</span><a href="http://{esc(d.get("ip") or "")}" target="_blank" class=mini-btn>🌐</a><button class=mini-btn onclick="delDishInTower({d.get("id")},{tid})">✕</button></div>' for d in dishes]) or '<small style="font-size:10px;color:#777">فاضي</small>'
                cards+=f'<div class="card small tower-card" id="tower-{tid}" data-name="{esc(t.get("name") or "")}" data-area="{esc(t.get("area") or "")}" data-lat="{t.get("lat")}" data-lng="{t.get("lng")}"><div style="display:flex;justify-content:space-between"><b style="font-size:12px">{esc(t.get("name") or "")}</b><div style="display:flex;gap:3px"><button class=mini-btn onclick="openEditTower({tid})">✏</button><button class=mini-btn-del onclick="askDel(\'/del_tower/{tid}\',{tid})">🗑</button></div></div><div class=area-body>{dhtml}</div><div class=row style="margin-top:6px"><input id="ip-{tid}" placeholder="IP" style="flex:1;padding:5px;font-size:10px"><input id="name-{tid}" placeholder="اسم" style="flex:1;padding:5px;font-size:10px"><button class=mini-btn-gold onclick="addDishToTower({tid})">+</button></div></div>'
            return f'<div style="max-width:1000px;margin:0 auto"><div class=card small row style="justify-content:space-between"><b style="font-size:13px">{L("الأبراج","Towers")} - {len(rs)}</b><button class=btn-gold onclick="openNewTower()" style="padding:5px 8px;font-size:10px">+ {L("كرت","Card")}</button></div><div class=grid-small>{cards}</div></div><script>window.openNewTower=function(){{let b=document.getElementById("editBody"); b.innerHTML=\'<input id=nt_name placeholder="اسم"><input id=nt_area placeholder="منطقة"><div class=row><input id=nt_lat value="35.1318"><input id=nt_lng value="36.7578"></div><button class=btn-gold onclick="saveNewTower()" style="width:100%">حفظ</button>\'; document.getElementById("editModal").classList.add("show");}};window.saveNewTower=function(){{fetch("/add_tower",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{name:document.getElementById("nt_name").value,area:document.getElementById("nt_area").value,lat:document.getElementById("nt_lat").value,lng:document.getElementById("nt_lng").value}})}}).then(r=>r.json()).then(j=>{{closeEditModal(); loadPage("towers",true);}})}};window.openEditTower=function(id){{let c=document.getElementById("tower-"+id); let b=document.getElementById("editBody"); b.innerHTML=\'<input id=et_name value="\'+c.dataset.name+\'"><input id=et_area value="\'+c.dataset.area+\'"><div class=row><input id=et_lat value="\'+c.dataset.lat+\'"><input id=et_lng value="\'+c.dataset.lng+\'"></div><button class=btn-gold onclick="saveTower(\'+id+\')" style="width:100%">حفظ</button>\'; document.getElementById("editModal").classList.add("show");}};window.saveTower=function(id){{fetch("/edit_tower/"+id,{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{name:document.getElementById("et_name").value,area:document.getElementById("et_area").value,lat:document.getElementById("et_lat").value,lng:document.getElementById("et_lng").value}})}}).then(()=>{{closeEditModal(); loadPage("towers",true);}})}};window.addDishToTower=function(tid){{let ip=document.getElementById("ip-"+tid).value.trim(); let nm=document.getElementById("name-"+tid).value.trim(); if(!ip)return; fetch("/api/add_dish_to_tower",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{ip:ip,dish_name:nm,tower_id:tid}})}}).then(r=>r.json()).then(j=>{{if(j.ok)loadPage("towers",true);}})}};window.delDishInTower=function(did,tid){{fetch("/del_dish/"+did).then(r=>r.json()).then(j=>{{if(j.ok)loadPage("towers",true);}})}};</script>'
        if v=='dishes':
            rs=qall("SELECT * FROM dish_ips ORDER BY id DESC")
            groups=defaultdict(list)
            for r in rs:
                key=(r.get('location') or '').strip() or 'بدون منطقة'
                groups[key].append(r)
            html_groups=""
            for area, items in groups.items():
                inner="".join([f'<div class="inner-card"><span style="font-size:11px">{esc(it.get("dish_name") or it.get("ip") or "")}</span><a href="http://{esc(it.get("ip") or "")}" target="_blank" class=mini-btn>🌐</a><button class=mini-btn onclick="quickPing(\'{esc(it.get("ip") or "")}\')">📶</button><button class=mini-btn onclick="editDish({it.get("id")})">✏</button><button class=mini-btn-del onclick="askDel(\'/del_dish/{it.get("id")}\',{it.get("id")})">🗑</button></div>' for it in items])
                html_groups+=f'<div class="card small region-card"><div style="display:flex;justify-content:space-between;align-items:center"><b style="font-size:12px">📍 {esc(area)}</b><span class=badge>{len(items)} IP</span></div><div style="margin-top:6px;display:flex;flex-direction:column;gap:4px">{inner}</div><div class=row style="margin-top:6px"><input id="addip-{esc(area)}" placeholder="IP جديد" style="flex:1;padding:4px;font-size:10px"><input id="addname-{esc(area)}" placeholder="اسم" style="flex:1;padding:4px;font-size:10px"><button class=mini-btn-gold onclick="addToArea(\'{esc(area)}\')">+</button></div></div>'
            return f'<div style="max-width:1000px;margin:0 auto"><div class=card small row style="justify-content:space-between"><b style="font-size:13px">{L("الصحون","Dishes")} - كل منطقة كرت - {len(rs)}</b><button class=btn-gold onclick="document.getElementById(\'newDishForm\').style.display=document.getElementById(\'newDishForm\').style.display==\'none\'?\'flex\':\'none\'" style="padding:4px 8px;font-size:10px">+ كرت</button></div><div id=newDishForm class=row style="display:none;gap:4px;margin-bottom:8px"><input id=nd_name placeholder="اسم" style="flex:1;padding:5px;font-size:11px"><input id=nd_ip placeholder="IP" style="flex:1;padding:5px;font-size:11px"><input id=nd_loc placeholder="منطقة" style="flex:1;padding:5px;font-size:11px"><button class=btn-gold onclick="addDishGlobal()" style="padding:5px 10px">+</button></div><div class=grid-small>{html_groups}</div></div><script>window.addDishGlobal=function(){{let n=document.getElementById("nd_name").value,ip=document.getElementById("nd_ip").value,loc=document.getElementById("nd_loc").value; if(!ip)return alert("IP"); fetch("/add_dish",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{dish_name:n,ip:ip,location:loc}})}}).then(r=>r.json()).then(j=>{{if(j.ok)loadPage("dishes",true);}})}};window.addToArea=function(area){{let ip=document.getElementById("addip-"+area).value.trim(); let nm=document.getElementById("addname-"+area).value.trim(); if(!ip)return; fetch("/add_dish",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{dish_name:nm,ip:ip,location:area}})}}).then(r=>r.json()).then(j=>{{if(j.ok)loadPage("dishes",true);}})}};window.editDish=function(id){{let b=document.getElementById("editBody"); b.innerHTML=\'<input id=ed_ip placeholder="IP"><input id=ed_name placeholder="اسم"><input id=ed_loc placeholder="منطقة"><button class=btn-gold onclick="saveDish(\'+id+\')" style="width:100%">حفظ</button>\'; document.getElementById("editModal").classList.add("show");}};window.saveDish=function(id){{fetch("/edit_dish/"+id,{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{ip:document.getElementById("ed_ip").value,dish_name:document.getElementById("ed_name").value,location:document.getElementById("ed_loc").value}})}}).then(r=>r.json()).then(j=>{{closeEditModal(); if(j.ok)loadPage("dishes",true);}})}};window.quickPing=function(ip){{loadPage("ping"); setTimeout(()=>{{let el=document.getElementById("pingIp"); if(el){{el.value=ip; doSinglePing();}}}},400);}};</script>'
        if v=='map':
            towers=qall("SELECT * FROM towers ORDER BY id DESC")
            tj=json.dumps([{"id":t.get('id'),"name":t.get('name') or '',"area":t.get('area') or '',"lat":float(t.get('lat') or 35.1318),"lng":float(t.get('lng') or 36.7578)} for t in towers],ensure_ascii=False)
            return f'<div class=card small><div class=row style="gap:4px"><input id=mapSearch placeholder="بحث" style="flex:1;padding:5px;font-size:11px"><button class=mini-btn-gold onclick="doMapSearch()">بحث</button><button class=mini-btn onclick="locateMe()" style="background:#22c55e;color:#fff">📍</button><span id=searchCount style="font-size:10px"></span></div><div id=map style="height:70vh;border-radius:10px;margin-top:6px"></div></div><script>let _towers={tj}; let _markers=[]; window._map=null; window.doMapSearch=function(){{let q=document.getElementById("mapSearch").value.toLowerCase(); let cnt=document.getElementById("searchCount"); if(!q){{_markers.forEach(m=>m.setOpacity(1)); cnt.textContent=""; return;}} let f=_towers.filter(t=>t.name.toLowerCase().includes(q)); cnt.textContent=f.length+" نتيجة"; _markers.forEach((m,i)=>{{m.setOpacity(_towers[i].name.toLowerCase().includes(q)?1:0.2);}}); if(f[0]&&window._map)window._map.flyTo([f[0].lat,f[0].lng],16);}};document.getElementById("mapSearch").addEventListener("input",doMapSearch);window.locateMe=function(){{if(navigator.geolocation)navigator.geolocation.getCurrentPosition(p=>{{window._map.flyTo([p.coords.latitude,p.coords.longitude],16); L.marker([p.coords.latitude,p.coords.longitude]).addTo(window._map).bindPopup("موقعك");}});}};setTimeout(()=>{{window._map=L.map("map").setView([35.1318,36.7578],13); let osm=L.tileLayer("https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png",{{maxZoom:19}}).addTo(window._map); let sat=L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}",{{maxZoom:19}}).addTo(window._map); L.control.layers({{"عادية":osm,"قمر":sat}}).addTo(window._map); _towers.forEach(t=>{{let m=L.marker([t.lat,t.lng],{{draggable:true}}).addTo(window._map).bindPopup("<b>"+t.name+"</b><br><a href=\'https://www.google.com/maps?q="+t.lat+","+t.lng+"\' target=_blank>جوجل</a>"); _markers.push(m); m.on("dragend",e=>{{let ll=e.target.getLatLng(); fetch("/api/update_tower_pos",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{id:t.id,lat:ll.lat,lng:ll.lng}})}});}});}});}},300);</script>'
        if v=='ping':
            return '''<div class=card small><h3 style="margin:0;font-size:12px">📶 Ping - يرد من نفس الشبكة</h3><div class=row style="gap:4px;margin-top:6px"><input id=pingIp placeholder="192.168.1.1" style="flex:1;padding:6px;font-size:11px"><button class=btn-gold onclick="doSinglePing()" style="padding:6px">Ping سيرفر</button><button class=btn-gold onclick="doClientPing()" style="background:#0ea5e9;padding:6px">Ping جهازي</button><button class=btn-gold onclick="openInChrome()" style="padding:6px">🌐 كروم</button></div><div id=pingResult class=pingBox>جاهز - سيرفر + جهازك</div></div><script>
            window.openInChrome=function(){let ip=document.getElementById('pingIp').value.trim(); if(ip) window.open('http://'+ip,'_blank');};
            window.doSinglePing=async function(){let ip=document.getElementById('pingIp').value.trim(); if(!ip)return; let out=document.getElementById('pingResult'); out.textContent='سيرفر يفحص '+ip+'...'; try{let r=await fetch('/api/ping?ip='+encodeURIComponent(ip)); let j=await r.json(); out.textContent='سيرفر: '+j.out;}catch(e){out.textContent='خطأ';}};
            window.doClientPing=async function(){let ip=document.getElementById('pingIp').value.trim(); if(!ip)return; let out=document.getElementById('pingResult'); out.textContent='جهازك (لابتوب/هاتف) يفحص '+ip+'...'; try{let ctrl=new AbortController(); setTimeout(()=>ctrl.abort(),2500); let start=Date.now(); await fetch('http://'+ip,{mode:'no-cors',signal:ctrl.signal}); let ms=Date.now()-start; out.textContent='جهازك: '+ip+' يرد ✓ '+ms+'ms (نفس الشبكة)';}catch(e){out.textContent='جهازك: '+ip+' لا يرد من هاتفك/لابتوب - جرب سيرفر Ping';}};
            </script>'''
        if v=='logs':
            rs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 500")
            rows="".join([f"<tr><td style='font-size:10px'>{esc(r.get('time',''))}</td><td><span class=badge style='font-size:9px'>{esc(r.get('action',''))}</span></td><td style='font-size:10px'>{esc(r.get('user_phone',''))}</td><td style='font-size:10px'>{esc(r.get('detail',''))}</td></tr>" for r in rs]) or "<tr><td colspan=4>فاضي</td></tr>"
            return f'<div class=card small><div class=row style="justify-content:space-between"><b style="font-size:12px">📜 السجل - كل العمليات</b><div class=row><a href="/api/export/logs" class=mini-btn-gold style="text-decoration:none">Excel</a><button class=mini-btn-del onclick="if(confirm(\'مسح؟\'))fetch(\'/api/clear_logs\',{method:\'POST\'}).then(()=>loadPage(\'logs\',true))">مسح</button></div></div><table style="width:100%;border-collapse:collapse;margin-top:6px"><thead><tr><th style="font-size:10px">وقت</th><th style="font-size:10px">عمل</th><th style="font-size:10px">يوزر</th><th style="font-size:10px">تفصيل</th></tr></thead><tbody>{rows}</tbody></table></div>'
        if v=='subs':
            rs=qall("SELECT * FROM subs ORDER BY id DESC")
            rows="".join([f"<tr id=sub-{r.get('id')} data-name='{esc(r.get('name') or '')}' data-phone='{esc(r.get('phone') or '')}' data-note='{esc(r.get('note') or '')}'><td style='font-size:11px'>{esc(r.get('name') or '')}</td><td style='font-size:11px'>{esc(r.get('phone') or '')}</td><td style='font-size:10px'>{esc(r.get('note') or '')}</td><td><button class=mini-btn onclick=\"openEditSub({r.get('id')})\">✏</button><button class=mini-btn-del onclick=\"askDel('/del_sub/{r.get('id')}',{r.get('id')})\">🗑</button></td></tr>" for r in rs])
            return f'<div class=card small><div class=row style="justify-content:space-between"><b style="font-size:12px">👥 المشتركين - جدول - {len(rs)}</b><button class=btn-gold onclick="document.getElementById(\'fSub\').style.display=\'flex\'" style="padding:4px 8px;font-size:10px">+ إضافة</button></div><form id=fSub class=row style="display:none;gap:4px;margin-top:6px"><input name=name placeholder="اسم" required style="flex:1;padding:5px;font-size:11px"><input name=phone placeholder="رقم" style="flex:1;padding:5px;font-size:11px"><input name=note placeholder="ملاحظة" style="flex:1;padding:5px;font-size:11px"><button class=mini-btn-gold>+</button></form><table style="width:100%;border-collapse:collapse;margin-top:8px"><thead><tr><th style="font-size:11px;text-align:right">اسم</th><th style="font-size:11px">رقم</th><th style="font-size:11px">ملاحظة</th><th></th></tr></thead><tbody>{rows}</tbody></table></div><script>document.getElementById("fSub").addEventListener("submit",e=>{{e.preventDefault(); fetch("/add_sub",{{method:"POST",body:new FormData(e.target)}}).then(r=>r.json()).then(j=>{{if(j.ok)loadPage("subs",true);}})}});window.openEditSub=id=>{{let c=document.getElementById("sub-"+id); let b=document.getElementById("editBody"); b.innerHTML=\'<input id=esn value="\'+c.dataset.name+\'"><input id=esp value="\'+c.dataset.phone+\'"><input id=esno value="\'+c.dataset.note+\'"><button class=btn-gold onclick="saveSub(\'+id+\')" style="width:100%">حفظ</button>\'; document.getElementById("editModal").classList.add("show");}};window.saveSub=id=>{{fetch("/edit_sub/"+id,{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{name:document.getElementById("esn").value,phone:document.getElementById("esp").value,note:document.getElementById("esno").value}})}}).then(()=>{{closeEditModal(); loadPage("subs",true);}})}};</script>'
        if v=='ledger':
            rs=qall("SELECT * FROM ledger ORDER BY id DESC")
            rows="".join([f"<tr id=led-{r.get('id')} data-name='{esc(r.get('name') or '')}' data-amount='{r.get('amount')}'><td style='font-size:11px'>{esc(r.get('name') or '')}</td><td><span class=ip>{r.get('amount')}</span></td><td style='font-size:10px'>{esc(r.get('note') or '')}</td><td>{esc(r.get('currency') or '')}</td><td><button class=mini-btn onclick=\"openEditLed({r.get('id')})\">✏</button><button class=mini-btn-del onclick=\"askDel('/del_ledger/{r.get('id')}',{r.get('id')})\">🗑</button></td></tr>" for r in rs])
            return f'<div class=card small><div class=row style="justify-content:space-between"><b style="font-size:12px">📒 حسابات - جدول واضح - {len(rs)}</b><button class=btn-gold onclick="document.getElementById(\'fLed\').style.display=\'flex\'" style="padding:4px 8px;font-size:10px">+ إضافة</button></div><form id=fLed class=row style="display:none;gap:4px;margin-top:6px"><input name=name placeholder="اسم" required style="flex:1;padding:5px;font-size:11px"><input name=amount type=number step=0.01 placeholder="مبلغ" required style="flex:1;padding:5px;font-size:11px"><input name=note placeholder="ملاحظة" style="flex:1;padding:5px;font-size:11px"><select name=currency style="padding:5px"><option>USD</option><option>SYP</option></select><button class=mini-btn-gold>+</button></form><table style="width:100%;border-collapse:collapse;margin-top:8px"><thead><tr><th style="font-size:11px;text-align:right">اسم</th><th style="font-size:11px">مبلغ</th><th style="font-size:11px">ملاحظة</th><th style="font-size:11px">عملة</th><th></th></tr></thead><tbody>{rows}</tbody></table></div><script>document.getElementById("fLed").addEventListener("submit",e=>{{e.preventDefault(); fetch("/add_ledger",{{method:"POST",body:new FormData(e.target)}}).then(r=>r.json()).then(j=>{{if(j.ok)loadPage("ledger",true);}})}});window.openEditLed=id=>{{let c=document.getElementById("led-"+id); let b=document.getElementById("editBody"); b.innerHTML=\'<input id=eln value="\'+c.dataset.name+\'"><input id=ela value="\'+c.dataset.amount+\'"><button class=btn-gold onclick="saveLed(\'+id+\')" style="width:100%">حفظ</button>\'; document.getElementById("editModal").classList.add("show");}};window.saveLed=id=>{{fetch("/edit_ledger/"+id,{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{name:document.getElementById("eln").value,amount:document.getElementById("ela").value}})}}).then(()=>{{closeEditModal(); loadPage("ledger",true);}})}};</script>'
        if v=='network':
            dishes=qall("SELECT * FROM dish_ips ORDER BY id DESC")
            rows="".join([f"<tr id=net-{d.get('id')} data-ip='{esc(d.get('ip') or '')}'><td style='font-size:11px'>{esc(d.get('dish_name') or '')}</td><td><a href='http://{esc(d.get('ip') or '')}' target=_blank class=ip>{esc(d.get('ip') or '')}</a></td><td class=net-out style='font-size:10px'>...</td><td><a href='http://{esc(d.get('ip') or '')}' target=_blank class=mini-btn>🌐</a><button class=mini-btn onclick='checkOne({d.get('id')})'>فحص</button></td></tr>" for d in dishes])
            return f'<div class=card small><div class=row style="justify-content:space-between"><b style="font-size:12px">📊 الشبكة</b><button class=btn-gold onclick="checkAll()" style="padding:4px 8px;font-size:10px">فحص الكل</button></div><table style="width:100%;border-collapse:collapse;margin-top:6px"><thead><tr><th style="font-size:11px;text-align:right">اسم</th><th style="font-size:11px">IP</th><th style="font-size:11px">حالة</th><th></th></tr></thead><tbody>{rows}</tbody></table></div><script>window.checkOne=async id=>{{let c=document.getElementById("net-"+id); let out=c.querySelector(".net-out"); out.textContent="..."; try{{let r=await fetch("/api/ping?ip="+c.dataset.ip); let j=await r.json(); out.textContent=j.out;}}catch{{out.textContent="خطأ";}}}};window.checkAll=async()=>{{for(let c of document.querySelectorAll("[id^=net-]")){{await checkOne(c.id.split("-")[1]); await new Promise(r=>setTimeout(r,120));}}}};</script>'
        if v=='settings':
            us=qall("SELECT * FROM users ORDER BY id DESC")
            cards="".join([f"<div class='card small user-card' id=user-{esc(u.get('phone') or '')} data-phone='{esc(u.get('phone') or '')}' data-role='{esc(u.get('role') or '')}'><div style='text-align:center'><b style='font-size:13px'>{esc(u.get('username') or u.get('phone') or '')}</b><br><span class=ip style='font-size:11px'>{esc(u.get('phone') or '')}</span><br><span class=badge>{esc(u.get('role') or '')}</span><div style='display:flex;gap:6px;justify-content:center;margin-top:8px'><button class=mini-btn onclick=\"openEditUser('{esc(u.get('phone') or '')}')\">✏ تعديل</button><button class=mini-btn-del onclick=\"askDel('/del_user/{esc(u.get('phone') or '')}','{esc(u.get('phone') or '')}')\">🗑 حذف</button></div></div></div>" for u in us])
            return f'''
<div style="max-width:1000px;margin:0 auto">
<div class=grid-small>
<div class=card small><h4 style="margin:0 0 6px;font-size:11px">🔑 باسورد</h4><form id=formPass class=row><input name=newpass type=password placeholder="جديدة" required style="flex:1;padding:6px"><button class=mini-btn-gold>حفظ</button></form></div>
<div class=card small><h4 style="margin:0 0 6px;font-size:11px">👤 يوزر</h4><form id=formUser class=row style="flex-wrap:wrap;gap:4px"><input name=user_field placeholder="يوزر" required style="flex:1;padding:6px"><input name=password type=password placeholder="باس" required style="flex:1;padding:6px"><select name=role style="padding:6px"><option value=tech>فني</option><option value=manager>مدير</option></select><button class=mini-btn-gold>إضافة</button></form></div>
<div class=card small><h4 style="margin:0 0 6px;font-size:11px">⚙ سريع بدون تحميل</h4><div class=row><button class=btn-gold onclick="toggleLangFast()" style="padding:6px 10px">🌐 لغة</button><button class=btn-gold onclick="toggleThemeFast()" style="padding:6px 10px">🌓 نهار/ليل</button></div></div>
</div>
<div style="margin-top:12px"><b style="font-size:13px">👥 يوزرات - أكبر ومرتبة - {len(us)}</b><div class=user-grid>{cards}</div></div>
</div>
<script>
window.openEditUser=ph=>{{let c=document.getElementById("user-"+ph); let b=document.getElementById("editBody"); b.innerHTML='<input id=eu_ph value="'+c.dataset.phone+'"><select id=eu_role><option value=tech>فني</option><option value=manager>مدير</option></select><input id=eu_pass type=password placeholder="باسورد جديد"><button class=btn-gold onclick="saveUser(\\''+ph+'\\')" style="width:100%">حفظ</button>'; document.getElementById("eu_role").value=c.dataset.role; document.getElementById("editModal").classList.add("show");}};
window.saveUser=old=>{{let fd=new URLSearchParams({{old_phone:old,phone:document.getElementById("eu_ph").value,role:document.getElementById("eu_role").value,password:document.getElementById("eu_pass").value}}); fetch("/edit_user",{{method:"POST",body:fd}}).then(r=>r.json()).then(j=>{{if(j.ok){{closeEditModal(); loadPage("settings",true);}}}})}};
document.getElementById("formPass").addEventListener("submit",e=>{{e.preventDefault(); fetch("/change_pass",{{method:"POST",body:new FormData(e.target)}}).then(r=>r.json()).then(j=>{{if(j.ok){{e.target.reset(); alert("تم");}}}})}});
document.getElementById("formUser").addEventListener("submit",e=>{{e.preventDefault(); fetch("/add_user",{{method:"POST",body:new FormData(e.target)}}).then(r=>r.json()).then(j=>{{if(j.ok){{e.target.reset(); loadPage("settings",true);}}}})}});
</script>'''
        return "<div class=card>404</div>"
    except Exception as e:
        traceback.print_exc()
        return f"<div class=card>خطأ {esc(str(e))}</div>"
def layout(c,v='home'):
    th=session.get('theme','dark'); is_dark=(th=='dark')
    bg='radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 60%, #070a1f 100%)' if is_dark else '#eef2f7'
    card_bg='#1e2433f2' if is_dark else '#ffffff'; txt='#ffffff' if is_dark else '#0f172a'; border='#ffffff14' if is_dark else '#e2e8f0'
    cur_user=qone("SELECT * FROM users WHERE phone=?",(session.get('phone') or '',)) or {}
    lang=session.get('lang','ar'); dir_attr='rtl' if lang=='ar' else 'ltr'
    tr_json=json.dumps({"ar":{"home":"الرئيسية","towers":"الأبراج","dishes":"الصحون","map":"الخريطة","ping":"بنج","network":"الشبكة","subs":"مشتركين","ledger":"حسابات","logs":"السجل","settings":"إعدادات","logout":"خروج"},"en":{"home":"Home","towers":"Towers","dishes":"Dishes","map":"Map","ping":"Ping","network":"Network","subs":"Subs","ledger":"Ledger","logs":"Logs","settings":"Settings","logout":"Logout"}},ensure_ascii=False)
    return f"""<html dir={dir_attr}><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>OMAIA</title>
<link rel=stylesheet href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'>
<style>
*{{box-sizing:border-box;font-family:system-ui}}
body{{margin:0;background:{bg};color:{txt};overflow-x:hidden;transition:.3s}}
.top{{position:fixed;top:0;left:0;right:0;height:50px;background:#0f172ae0;backdrop-filter:blur(12px);display:flex;align-items:center;justify-content:space-between;padding:0 10px;z-index:1003;border-bottom:1px solid #ffffff12}}
body.light .top{{background:#ffffffee;color:#0f172a;border-bottom:1px solid #e2e8f0}}
.sidebar{{position:fixed;top:0;right:0;width:250px;height:100%;background:linear-gradient(180deg,#0f172a,#070e22);z-index:1002;padding-top:58px;transform:translateX(110%);transition:.4s;overflow-y:auto}}
body.light .sidebar{{background:#ffffff;border-left:1px solid #e2e8f0;box-shadow:-4px 0 12px #0001}}
.sidebar.active{{transform:none}}
.sidebar a{{display:flex;gap:8px;padding:9px 12px;margin:4px 8px;color:#cbd5e1;text-decoration:none;border-radius:9px;background:#ffffff08;font-size:12px}}
body.light .sidebar a{{color:#334155;background:#f1f5f9}}
.sidebar a.active{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:800}}
#overlay{{position:fixed;inset:0;background:#0005;z-index:1001;display:none}} #overlay.show{{display:block}}
.main{{margin-top:58px;padding:6px;min-height:90vh}}
.card{{background:{card_bg};color:{txt};padding:8px;border-radius:10px;margin-bottom:6px;border:1px solid {border}}}
.card.small{{padding:7px}} .grid-small{{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:6px}}
.stat{{text-align:center;cursor:pointer}} .stat h4{{margin:2px 0;font-size:10px;color:#94a3b8}} .stat h2{{margin:2px 0;font-size:18px}} .ico{{font-size:16px}}
.row{{display:flex;gap:5px;align-items:center;flex-wrap:wrap}}
.btn-gold{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;padding:5px 9px;border:0;border-radius:7px;font-weight:700;font-size:11px;cursor:pointer}}
.mini-btn{{background:#ffffff12;color:{txt};border:0;padding:3px 6px;border-radius:6px;font-size:10px;cursor:pointer}} .mini-btn-del{{background:#ef4444;color:#fff;border:0;padding:3px 6px;border-radius:6px;font-size:10px;cursor:pointer}} .mini-btn-gold{{background:#ffbe4d;color:#111;border:0;padding:4px 8px;border-radius:6px;font-size:11px;font-weight:700;cursor:pointer}}
.ip{{background:#000;color:#ffbe4d;padding:2px 5px;border-radius:5px;font-family:monospace;font-size:10px;text-decoration:none}} .badge{{background:#ffbe4d;color:#111;padding:1px 5px;border-radius:5px;font-size:9px;font-weight:700}}
.pingBox{{margin-top:6px;background:#000a;border:1px solid #ffffff12;border-radius:8px;padding:8px;font-family:monospace;min-height:32px;white-space:pre-wrap;font-size:11px;color:#22c55e}}
.inner-card{{display:flex;justify-content:space-between;align-items:center;background:#ffffff06;padding:5px 6px;border-radius:7px;font-size:11px}}
.region-card{{border:1px solid #ffbe4d22}} .user-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:8px;margin-top:8px}} .user-card{{padding:12px!important;border-radius:12px!important}}
table th{{background:#ffffff08;padding:6px 8px;font-size:11px;text-align:right}} table td{{padding:6px 8px;border-bottom:1px solid #ffffff08}}
body.light table th{{background:#f1f5f9}} body.light table td{{border-bottom:1px solid #e2e8f0}}
#delModal,#editModal{{position:fixed;inset:0;background:#0008;display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:.2s;z-index:2000}} #delModal.show,#editModal.show{{opacity:1;pointer-events:auto}} #delBox,#editBox{{background:{card_bg};color:{txt};padding:14px;border-radius:10px;width:90%;max-width:380px}}
input,select{{padding:6px 8px;border-radius:7px;border:1px solid {border};background:#ffffff07;color:{txt};font-size:11px}}
.wa-float{{position:fixed;bottom:14px;left:14px;width:46px;height:46px;background:#25D366;color:#fff;border-radius:50%;display:flex;align-items:center;justify-content:center;text-decoration:none;z-index:999;font-size:20px}}
</style></head><body class="{'dark' if is_dark else 'light'}">
<div id=overlay onclick="toggleSb(false)"></div>
<div class=sidebar id=sb>
<div style='padding:0 10px 8px;border-bottom:1px solid #ffffff0a'><b style="font-size:13px">OMAIA <span style='color:#ffbe4d'>ISP</span></b><br><small style="font-size:9px">{esc(cur_user.get('username') or '')}</small></div>
<a href="javascript:loadPage('home')" id=nav-home data-i18n="home">🏠 الرئيسية</a>
<a href="javascript:loadPage('towers')" id=nav-towers data-i18n="towers">🗼 الأبراج</a>
<a href="javascript:loadPage('dishes')" id=nav-dishes data-i18n="dishes">📡 الصحون</a>
<a href="javascript:loadPage('map')" id=nav-map data-i18n="map">🗺 الخريطة</a>
<a href="javascript:loadPage('ping')" id=nav-ping data-i18n="ping">📶 بنج</a>
<a href="javascript:loadPage('network')" id=nav-network data-i18n="network">📊 الشبكة</a>
<a href="javascript:loadPage('subs')" id=nav-subs data-i18n="subs">👥 مشتركين</a>
<a href="javascript:loadPage('ledger')" id=nav-ledger data-i18n="ledger">📒 حسابات</a>
<a href="javascript:loadPage('logs')" id=nav-logs data-i18n="logs">📜 السجل</a>
<a href="javascript:loadPage('settings')" id=nav-settings data-i18n="settings">⚙ إعدادات</a>
<div style='padding:8px 10px;margin-top:6px;border-top:1px dashed #ffffff10;display:flex;gap:8px;justify-content:center'>
<a href="https://wa.me/{SUPPORT_WA}" target="_blank" style="width:32px;height:32px;background:#25D366;border-radius:50%;display:flex;align-items:center;justify-content:center;text-decoration:none">💬</a>
<a href="https://instagram.com/{SUPPORT_INSTA}" target="_blank" style="width:32px;height:32px;background:linear-gradient(45deg,#feda75,#d62976);border-radius:50%;display:flex;align-items:center;justify-content:center;text-decoration:none">📷</a>
<a href="tel:+{SUPPORT_WA}" style="width:32px;height:32px;background:#0ea5e9;border-radius:50%;display:flex;align-items:center;justify-content:center;text-decoration:none">📞</a>
</div>
<a href="javascript:logoutFast()" style='margin-top:6px;background:#ef444418' data-i18n="logout">🚪 خروج</a>
</div>
<div class=top><div class=row><span onclick="toggleSb()" style='font-size:18px;cursor:pointer;padding:4px 8px;background:#ffffff0a;border-radius:7px'>☰</span><input id=topsearch placeholder='بحث...' oninput="globalSearchTop(this.value)" style='width:32px;transition:.3s;background:#1f2937;border:1px solid #ffffff15;color:#fff;padding:5px 8px;border-radius:7px;font-size:11px' onfocus="this.style.width='120px'" onblur="setTimeout(()=>this.style.width='32px',200)"></div><b style="font-size:13px">OMAIA <span style='color:#ffbe4d'>ISP</span></b><div class=row style="gap:4px"><button onclick="toggleLangFast()" style='background:#ffffff0a;color:#fff;border:1px solid #ffffff14;padding:5px 7px;border-radius:7px;font-size:11px'>🌐</button><button onclick="toggleThemeFast()" style='background:#ffffff0a;color:#fff;border:1px solid #ffffff14;padding:5px 7px;border-radius:7px;font-size:11px'>🌓</button></div></div>
<div id=searchResults style='position:fixed;top:54px;right:8px;max-width:280px;width:90%;background:#1e2433;border:1px solid #ffffff15;border-radius:9px;z-index:1500;display:none;max-height:50vh;overflow:auto;font-size:11px'></div>
<div class=main id=mn>{c}</div>
<div id=delModal><div id=delBox><div style='text-align:center;font-size:20px'>🗑</div><h3 style='text-align:center;font-size:12px'>تأكيد؟</h3><div class=row style="margin-top:8px"><button onclick="closeDel()" style='flex:1;padding:7px;border-radius:7px;background:transparent;color:{txt};border:1px solid {border}'>تراجع</button><button id=delYes style='flex:1;padding:7px;border-radius:7px;background:#ef4444;color:#fff;border:0'>حذف</button></div></div></div>
<div id=editModal><div id=editBox><div class=row style='justify-content:space-between'><b style='font-size:12px'>تعديل</b><button onclick="closeEditModal()" style='width:24px;height:24px;border-radius:50%;background:#ffffff12;border:0;color:{txt}'>✕</button></div><div id=editBody style='margin-top:8px'></div></div></div>
<a href="https://wa.me/{SUPPORT_WA}" target="_blank" class=wa-float>💬</a>
<script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>
<script>
let cur='{v}'; let TR={tr_json}; let pageCache={{}};
function toggleSb(f){{let sb=document.getElementById('sb'),ov=document.getElementById('overlay'); let o=f!==undefined?f:!sb.classList.contains('active'); sb.classList.toggle('active',o); ov.classList.toggle('show',o);}}
async function loadPage(v,force=false,push=true){{
 if(push&&cur!==v){{try{{history.pushState({{page:v}},'', '/dash?v='+v)}}catch(e){{}}}}
 cur=v; toggleSb(false); document.querySelectorAll('.sidebar a').forEach(a=>a.classList.remove('active')); let n=document.getElementById('nav-'+v); if(n) n.classList.add('active');
 let mn=document.getElementById('mn'); if(!force&&pageCache[v]){{mn.innerHTML=pageCache[v]; execScripts(); return;}}
 mn.innerHTML='<div class=card small>...</div>';
 try{{let r=await fetch('/api/page?v='+v,{{cache:'no-store'}}); let h=await r.text(); pageCache[v]=h; mn.innerHTML=h; execScripts();}}catch(e){{mn.innerHTML='<div class=card>خطأ</div>';}}
}}
function execScripts(){{document.getElementById('mn').querySelectorAll('script').forEach(o=>{{let s=document.createElement('script'); s.textContent=o.textContent; document.body.appendChild(s); o.remove();}});}}
function askDel(url,id){{window._delUrl=url; window._delId=id; document.getElementById('delModal').classList.add('show');}}
function closeDel(){{document.getElementById('delModal').classList.remove('show');}}
window.closeEditModal=()=>document.getElementById('editModal').classList.remove('show');
document.getElementById('delYes').onclick=async()=>{{if(!window._delUrl)return; let b=document.getElementById('delYes'); b.textContent='...'; b.disabled=true; try{{let r=await fetch(window._delUrl); let j=await r.json(); if(j.ok){{let el=document.getElementById('tower-'+window._delId)||document.getElementById('dish-'+window._delId)||document.getElementById('sub-'+window._delId)||document.getElementById('led-'+window._delId)||document.getElementById('net-'+window._delId)||document.getElementById('user-'+window._delId); if(el)el.remove(); delete pageCache[cur]; closeDel();}}else alert(j.msg);}}catch(e){{alert(e);}} b.textContent='حذف'; b.disabled=false;}};
window.toggleLangFast=async()=>{{try{{let r=await fetch('/toggle_lang'); let j=await r.json(); let lang=j.lang; document.documentElement.dir=lang==='ar'?'rtl':'ltr'; localStorage.setItem('lang',lang);
 document.querySelectorAll('[data-i18n]').forEach(el=>{{let k=el.dataset.i18n; if(TR[lang]&&TR[lang][k]){{let icon=el.textContent.trim().split(' ')[0]; el.textContent=icon+' '+TR[lang][k];}}}});
 loadPage(cur,true,false);}}catch(e){{console.log(e);}}}};
window.toggleThemeFast=async()=>{{try{{let r=await fetch('/toggle_theme'); let j=await r.json(); let th=j.theme; document.body.className=th; if(th==='light'){{document.body.style.background='#eef2f7';}} else {{document.body.style.background='radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 60%, #070a1f 100%)';}} localStorage.setItem('theme',th);}}catch{{document.body.classList.toggle('light'); document.body.classList.toggle('dark');}}}};
window.globalSearchTop=async q=>{{let box=document.getElementById('searchResults'); if(!q||q.length<2){{box.style.display='none'; return;}} try{{let r=await fetch('/api/search?q='+encodeURIComponent(q)); let d=await r.json(); if(!d.length){{box.style.display='none'; return;}} let h=''; d.forEach(x=>{{h+='<div onclick="loadPage(\\''+x.page+'\\');box.style.display=\\'none\\'" style="padding:7px 9px;cursor:pointer;border-bottom:1px solid #ffffff08"><b>'+x.title+'</b><br><small style="color:#888">'+x.sub+'</small></div>';}}); box.innerHTML=h; box.style.display='block';}}catch{{}}}};
window.logoutFast=async()=>{{try{{await fetch('/api/logout',{{method:'POST'}});}}catch{{}} localStorage.clear(); location.replace('/login');}};
window.addEventListener('popstate',e=>{{let v='home'; if(e.state&&e.state.page) v=e.state.page; else {{let p=new URLSearchParams(location.search); v=p.get('v')||'home';}} loadPage(v,false,false);}});
loadPage(cur,true,false);
</script></body></html>"""
if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)),debug=False)
