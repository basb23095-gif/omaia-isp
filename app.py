from flask import Flask, request, redirect, session, jsonify, Response
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, html, ipaddress, subprocess, socket, platform, io, csv, datetime, re, threading, time, traceback, concurrent.futures
try:
    import psycopg2, psycopg2.extras
    from psycopg2 import pool as pg_pool
    PG=True
except:
    psycopg2=None; pg_pool=None; PG=False
import sqlite3

app=Flask(__name__)
app.secret_key=os.environ.get("SECRET_KEY","omia-v17-final")
app.config['PERMANENT_SESSION_LIFETIME']=datetime.timedelta(minutes=60)
DATABASE_URL=os.environ.get("DATABASE_URL","").strip().replace("postgres://","postgresql://",1)
USE_PG=bool(DATABASE_URL.startswith("postgresql://") and PG)
_pg_pool=None
_plock=threading.Lock()
_sqlite_conn=None
_slock=threading.Lock()
_cache={}
_clock=threading.Lock()

def init_pool():
    global _pg_pool
    if not USE_PG or not pg_pool: return
    with _plock:
        if _pg_pool: return
        try:
            _pg_pool=pg_pool.ThreadedConnectionPool(3,20,dsn=DATABASE_URL,sslmode='require',connect_timeout=2)
        except Exception as e:
            print("pool fail", e)

init_pool()

def esc(s):
    return html.escape(str(s or ''), quote=True)

def get_conn():
    global USE_PG, _sqlite_conn
    if USE_PG and _pg_pool:
        try:
            c=_pg_pool.getconn()
            if getattr(c,'closed',1)==0: return c
        except:
            try: return psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=2)
            except: pass
    with _slock:
        if _sqlite_conn is None:
            db_path=os.path.join(os.path.dirname(os.path.abspath(__file__)),"omia.db")
            _sqlite_conn=sqlite3.connect(db_path,check_same_thread=False,timeout=10,isolation_level=None)
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
        print("qall err", e)
        if cn and USE_PG and hasattr(cn,'closed'):
            try: put_conn(cn)
            except: pass
        return []

def qone(q,a=()):
    r=qall(q,a)
    return r[0] if r else None

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
        print("[qexec]", e)
        return False

def ping_ip_fast(ip):
    def try_port(p):
        s=None
        try:
            s=socket.socket(); s.settimeout(0.4)
            if s.connect_ex((ip,p))==0: return p
        except: pass
        finally:
            try: s.close()
            except: pass
        return None
    ports=[80,443,8080,8291,22,8728]
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(ports)) as ex:
            futs=[ex.submit(try_port, pr) for pr in ports]
            for f in concurrent.futures.as_completed(futs, timeout=1.2):
                r=f.result()
                if r is not None:
                    for ff in futs: ff.cancel()
                    return True, f"{ip}:{r} ok"
    except: pass
    try:
        cmd=['ping','-c','1','-W','1',ip] if platform.system().lower()!='windows' else ['ping','-n','1','-w','800',ip]
        out=subprocess.check_output(cmd,timeout=1,stderr=subprocess.STDOUT).decode(errors='ignore')
        if 'ttl=' in out.lower():
            m=re.search(r'time[=<]\s*(\d+\.?\d*)',out,re.I)
            ms=m.group(1) if m else ''
            return True, f"{ip} {ms}ms ok"
    except: pass
    return False, f"{ip} لا يرد"

def add_log(phone,action,detail):
    try:
        now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)",(phone or 'sys',action,detail,now))
        with _clock: _cache.pop('counts',None)
    except: pass

def get_counts():
    with _clock:
        c=_cache.get('counts')
        if c and time.time()-c[1]<5: return c[0]
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
        "CREATE TABLE IF NOT EXISTS system_config(key TEXT PRIMARY KEY,value TEXT)"
    ]
    if USE_PG: ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
    for s in ss: qexec(s)
    for al in ["ALTER TABLE dish_ips ADD COLUMN tower_id INTEGER","ALTER TABLE towers ADD COLUMN created_at TEXT"]:
        try: qexec(al)
        except: pass
    idx=[
        "CREATE INDEX IF NOT EXISTS idx_dish_tower ON dish_ips(tower_id)",
        "CREATE INDEX IF NOT EXISTS idx_dish_ip ON dish_ips(ip)",
        "CREATE INDEX IF NOT EXISTS idx_tower_name ON towers(name)"
    ]
    for iq in idx:
        try: qexec(iq)
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
def after(r):
    r.headers['Cache-Control']='no-cache'
    return r

@app.route('/ping')
def ping():
    return jsonify(ok=True)

@app.route('/api/ping')
@login_required
def api_ping():
    ip=request.args.get('ip','').strip()
    if not is_valid_ip(ip): return jsonify(ok=False,out='IP غير صالح')
    ok,out=ping_ip_fast(ip)
    return jsonify(ok=ok,out=out)

@app.route('/api/ping_batch', methods=['POST'])
@login_required
def api_ping_batch():
    d=request.json if request.is_json else {}
    ips=(d.get('ips') or [])[:50]
    ips=[i.strip() for i in ips if i and is_valid_ip(i.strip())]
    results={}
    def chk(ip):
        ok,msg=ping_ip_fast(ip)
        return ip, ok, msg
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
        futs=[ex.submit(chk, ip) for ip in ips]
        for f in concurrent.futures.as_completed(futs):
            try:
                ip,ok,msg=f.result()
                results[ip]={'ok':ok,'out':msg}
            except: pass
    return jsonify(ok=True, results=results)

@app.route('/api/stats')
@login_required
def api_stats():
    ns,nd,nt,nl=get_counts()
    logs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 10")
    return jsonify(ok=True,stats=dict(subs=ns,dishes=nd,towers=nt,ledger=nl),logs=logs)

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
            session.clear(); session['phone']=u['phone']; session['username']=u.get('username') or u['phone']; session['role']=u.get('role') or 'tech'; session.permanent=True
            add_log(u['phone'],'دخول',uin)
            return jsonify(ok=True)
        return jsonify(ok=False,msg='خطأ'),401
    except Exception as e:
        traceback.print_exc()
        return jsonify(ok=False,msg=str(e)),500

@app.route('/api/tower_detail/<int:id>')
@login_required
def tower_detail(id):
    if id==0:
        dishes=qall("SELECT * FROM dish_ips WHERE tower_id IS NULL ORDER BY dish_name ASC")
        return jsonify(ok=True,tower=dict(id=0,name='بدون برج',area=''),dishes=dishes)
    t=qone("SELECT * FROM towers WHERE id=?",(id,))
    if not t: return jsonify(ok=False,msg='غير موجود'),404
    dishes=qall("SELECT * FROM dish_ips WHERE tower_id=? ORDER BY dish_name ASC",(id,))
    return jsonify(ok=True,tower=t,dishes=dishes)

@app.route('/api/dish_detail/<int:id>')
@login_required
def dish_detail(id):
    d=qone("SELECT * FROM dish_ips WHERE id=?",(id,))
    if not d: return jsonify(ok=False,msg='غير موجود'),404
    return jsonify(ok=True,dish=d)

@app.route('/api/add_dish_to_tower',methods=['POST'])
@login_required
def add_dish_to_tower():
    try:
        d=request.json if request.is_json else request.form
        ip=(d.get('ip') or '').strip(); name=(d.get('dish_name') or '').strip(); loc=(d.get('location') or '').strip(); tid=d.get('tower_id')
        if not is_valid_ip(ip): return jsonify(ok=False,msg='IP غير صالح'),400
        tid_val=int(tid) if tid and str(tid).isdigit() and int(tid)!=0 else None
        if USE_PG: ok=qexec("INSERT INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?) ON CONFLICT (ip) DO UPDATE SET dish_name=EXCLUDED.dish_name, location=EXCLUDED.location, tower_id=EXCLUDED.tower_id",(ip,loc,name,tid_val))
        else: ok=qexec("INSERT OR REPLACE INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?)",(ip,loc,name,tid_val))
        with _clock: _cache.pop('counts',None)
        dish=qone("SELECT * FROM dish_ips WHERE ip=? ORDER BY id DESC LIMIT 1",(ip,))
        return jsonify(ok=ok, dish=dish)
    except Exception as e: return jsonify(ok=False,msg=str(e)),500

@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login')
def login_page():
    return """<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>OMAIA</title><style>*{box-sizing:border-box;font-family:system-ui}body{margin:0;min-height:100vh;background:radial-gradient(120% 120% at 10% 10%,#1a2344,#0a0e2a 60%);display:flex;align-items:center;justify-content:center;color:#fff}.card{background:#1e2433ee;border:1px solid #ffffff18;padding:22px;border-radius:16px;width:92%;max-width:360px;box-shadow:0 20px 50px #0006;transition:transform .25s ease}.card:hover{transform:translateY(-2px)}input{width:100%;padding:12px;margin:7px 0;background:#0f1424;border:1px solid #ffffff22;color:#fff;border-radius:10px}.btn{width:100%;padding:12px;border:0;border-radius:10px;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:800;cursor:pointer}</style></head><body><div class=card><div style='text-align:center;font-weight:900;font-size:24px;margin-bottom:12px'>OMAIA <span style='color:#ffbe4d'>ISP</span></div><form id=loginForm><input name=userin id=userin placeholder='user' required autofocus><input name=password id=password type=password placeholder='password' required><button class=btn id=loginBtn>دخول</button><div id=msg style='text-align:center;color:#ff6b6b;font-size:11px;margin-top:8px'></div></form></div><script>document.getElementById('loginForm').addEventListener('submit', async function(e){e.preventDefault(); let b=document.getElementById('loginBtn'); b.textContent='...'; b.disabled=true; try{let fd=new FormData(e.target); let res=await fetch('/api/login_public',{method:'POST',body:fd}); let j=await res.json(); if(j.ok){ location.replace('/dash?v=home'); } else { document.getElementById('msg').textContent=j.msg; b.textContent='دخول'; b.disabled=false; }}catch(err){ document.getElementById('msg').textContent='شبكة'; b.textContent='دخول'; b.disabled=false; }});</script></body></html>"""

@app.route('/logout')
def lo(): session.clear(); return redirect('/login')
@app.route('/api/logout',methods=['POST'])
def api_logout(): session.clear(); return jsonify(ok=True)

@app.route('/dash')
@login_required
def dash():
    v=request.args.get('v','home')
    return layout(v)

@app.route('/api/page')
@login_required
def ap():
    try: return page_content(request.args.get('v','home'))
    except Exception as e:
        traceback.print_exc()
        return "<div class=card>خطأ "+esc(str(e))+"</div>",500

@app.route('/add_tower',methods=['POST'])
@login_required
def add_tower():
    try:
        d=request.json if request.is_json else request.form
        name=(d.get('name') or 'برج').strip(); area=(d.get('area') or '').strip()
        ok=qexec("INSERT INTO towers(name,area,lat,lng,created_at) VALUES(?,?,?,?,?)",(name,area,35.1318,36.7578,datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        with _clock: _cache.pop('counts',None)
        tower=qone("SELECT * FROM towers WHERE name=? ORDER BY id DESC LIMIT 1",(name,))
        return jsonify(ok=ok, tower=tower)
    except Exception as e: return jsonify(ok=False,msg=str(e)),500

@app.route('/del_tower/<int:i>')
@login_required
def del_tower(i):
    if not is_manager(): return jsonify(ok=False,msg='ممنوع'),403
    qexec("UPDATE dish_ips SET tower_id=NULL WHERE tower_id=?",(i,))
    ok=qexec("DELETE FROM towers WHERE id=?",(i,))
    with _clock: _cache.pop('counts',None)
    return jsonify(ok=ok)

@app.route('/edit_tower/<int:i>',methods=['POST'])
@login_required
def edit_tower(i):
    if not is_manager(): return jsonify(ok=False,msg='ممنوع'),403
    d=request.json if request.is_json else request.form
    name=(d.get('name') or '').strip(); area=(d.get('area') or '').strip()
    ok=qexec("UPDATE towers SET name=?,area=? WHERE id=?",(name,area,i))
    tower=qone("SELECT * FROM towers WHERE id=?",(i,))
    return jsonify(ok=ok, tower=tower)

@app.route('/add_dish',methods=['POST'])
@login_required
def add_dish():
    try:
        d=request.json if request.is_json else request.form
        ip=(d.get('ip') or '').strip(); name=(d.get('dish_name') or '').strip(); loc=(d.get('location') or '').strip(); tid=d.get('tower_id')
        if not is_valid_ip(ip): return jsonify(ok=False,msg='IP غير صالح'),400
        tid_val=int(tid) if tid and str(tid).isdigit() and int(tid)!=0 else None
        if USE_PG: ok=qexec("INSERT INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?) ON CONFLICT (ip) DO UPDATE SET dish_name=EXCLUDED.dish_name, location=EXCLUDED.location, tower_id=EXCLUDED.tower_id",(ip,loc,name,tid_val))
        else: ok=qexec("INSERT OR REPLACE INTO dish_ips(ip,location,dish_name,tower_id) VALUES(?,?,?,?)",(ip,loc,name,tid_val))
        with _clock: _cache.pop('counts',None)
        dish=qone("SELECT * FROM dish_ips WHERE ip=? ORDER BY id DESC LIMIT 1",(ip,))
        return jsonify(ok=ok, dish=dish)
    except Exception as e: return jsonify(ok=False,msg=str(e)),500

@app.route('/edit_dish/<int:i>',methods=['POST'])
@login_required
def edit_dish(i):
    if not is_manager(): return jsonify(ok=False,msg='ممنوع'),403
    d=request.json if request.is_json else request.form
    ok=qexec("UPDATE dish_ips SET dish_name=?,ip=?,location=? WHERE id=?",(d.get('dish_name',''),d.get('ip',''),d.get('location',''),i))
    dish=qone("SELECT * FROM dish_ips WHERE id=?",(i,))
    return jsonify(ok=ok, dish=dish)

@app.route('/del_dish/<int:i>')
@login_required
def del_dish(i):
    if not is_manager(): return jsonify(ok=False,msg='ممنوع'),403
    ok=qexec("DELETE FROM dish_ips WHERE id=?",(i,))
    with _clock: _cache.pop('counts',None)
    return jsonify(ok=ok)

@app.route('/add_sub',methods=['POST'])
@login_required
def add_sub():
    d=request.json if request.is_json else request.form
    ok=qexec("INSERT INTO subs(name,phone,note) VALUES(?,?,?)",(d.get('name',''),d.get('phone',''),d.get('note','')))
    sub=qone("SELECT * FROM subs ORDER BY id DESC LIMIT 1") if ok else None
    return jsonify(ok=ok, sub=sub)

@app.route('/del_sub/<int:i>')
@login_required
def del_sub(i):
    ok=qexec("DELETE FROM subs WHERE id=?",(i,))
    return jsonify(ok=ok)

@app.route('/edit_sub/<int:i>',methods=['POST'])
@login_required
def edit_sub(i):
    d=request.json if request.is_json else request.form
    ok=qexec("UPDATE subs SET name=?,phone=?,note=? WHERE id=?",(d.get('name',''),d.get('phone',''),d.get('note',''),i))
    sub=qone("SELECT * FROM subs WHERE id=?",(i,))
    return jsonify(ok=ok, sub=sub)

def page_content(v):
    if v=='home':
        return """<div style="max-width:1100px;margin:0 auto"><div class=grid-small id=statsGrid><div class="card stat" onclick="loadPage('towers')"><h4>أبراج</h4><h2 id=stat-towers>...</h2></div><div class="card stat" onclick="loadPage('dishes')"><h4>صحون</h4><h2 id=stat-dishes>...</h2></div></div><div class=card style="margin-top:10px"><b>السجل</b><div id=logsPreview>...</div></div></div><script>(async function(){let r=await fetch('/api/stats'); let j=await r.json(); if(j.ok){document.getElementById('stat-towers').textContent=j.stats.towers; document.getElementById('stat-dishes').textContent=j.stats.dishes; let lh=j.logs.map(function(l){return '<tr><td>'+(l.time||'')+'</td><td>'+(l.action||'')+'</td><td>'+(l.detail||'')+'</td></tr>';}).join(''); document.getElementById('logsPreview').innerHTML='<table style="width:100%"><tbody>'+lh+'</tbody></table>';}})();</script>"""

    if v=='towers':
        rs=qall("SELECT t.id,t.name,t.area,(SELECT COUNT(*) FROM dish_ips WHERE tower_id=t.id) as cnt FROM towers t ORDER BY t.name ASC")
        html_cards=""
        for t in rs:
            tid=t.get('id'); tname=esc(t.get('name') or ''); tarea=esc(t.get('area') or ''); cnt=t.get('cnt') or 0
            html_cards+="<div class='card tower-card' id='tower-"+str(tid)+"' data-name='"+tname+"' data-area='"+tarea+"'><div style='display:flex;justify-content:space-between'><div><b class='tower-name'>"+tname+"</b><div class='tower-area' style='font-size:11px;color:#94a3b8'>"+tarea+"</div></div><span class='badge'>"+str(cnt)+" IP</span></div><div style='display:flex;gap:6px;margin-top:8px'><button class='mini-btn' onclick='openEditTowerPage("+str(tid)+")'>تعديل</button><button class='mini-btn-del' onclick='openDeleteModal(\"/del_tower/"+str(tid)+"\","+str(tid)+")'>حذف</button></div></div>"
        return "<div style='max-width:1100px;margin:0 auto'><div class='card' style='display:flex;justify-content:space-between'><b>الأبراج</b><button class='btn-gold' onclick='openNewTowerPage()'>+ برج</button></div><div class='grid-small' id='towersGrid'>"+html_cards+"</div></div><script>window.openNewTowerPage=function(){let b=document.getElementById('editBody'); b.innerHTML=\"<input id='nt_name' placeholder='اسم البرج'><input id='nt_area' placeholder='المنطقة'><button class='btn-gold' onclick='saveNewTowerPage()' style='width:100%'>حفظ</button>\"; document.getElementById('editModalTitle').textContent='إضافة برج'; document.getElementById('editModal').classList.add('show');}; window.saveNewTowerPage=async function(){let d={name:document.getElementById('nt_name').value,area:document.getElementById('nt_area').value}; if(!d.name) return; let r=await fetch('/add_tower',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)}); let j=await r.json(); if(j.ok){closeEditModal(); loadPage('towers',true);}}; window.openEditTowerPage=function(id){let card=document.getElementById('tower-'+id); let b=document.getElementById('editBody'); b.innerHTML=\"<input id='et_name' value='\"+(card?card.dataset.name:'')+\"'><input id='et_area' value='\"+(card?card.dataset.area:'')+\"'><button class='btn-gold' onclick='saveTowerPage(\"+id+\")' style='width:100%'>حفظ</button>\"; document.getElementById('editModalTitle').textContent='تعديل'; document.getElementById('editModal').classList.add('show');}; window.saveTowerPage=async function(id){let d={name:document.getElementById('et_name').value,area:document.getElementById('et_area').value}; let r=await fetch('/edit_tower/'+id,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)}); let j=await r.json(); if(j.ok){closeEditModal(); let card=document.getElementById('tower-'+id); if(card && j.tower){card.querySelector('.tower-name').textContent=j.tower.name; card.querySelector('.tower-area').textContent=j.tower.area; card.style.transform='translateY(-2px)'; setTimeout(function(){card.style.transform='';},300);}}}; </script>"

    if v=='dishes':
        towers=qall("SELECT t.id, t.name, t.area, (SELECT COUNT(*) FROM dish_ips WHERE tower_id=t.id) as cnt FROM towers t ORDER BY t.name ASC")
        no_cnt=(qone("SELECT COUNT(*) as c FROM dish_ips WHERE tower_id IS NULL") or {}).get('c',0)
        acc=""
        for t in towers:
            tid=t.get('id'); tname=esc(t.get('name') or ''); tarea=esc(t.get('area') or ''); cnt=t.get('cnt') or 0
            acc+="<div class='card tower-accordion' id='tower-acc-"+str(tid)+"' data-name='"+tname.lower()+"' data-loaded='0'><div class='tower-accordion-header' onclick='toggleAccordionLazy("+str(tid)+")' style='padding:14px;display:flex;justify-content:space-between;align-items:center;cursor:pointer'><div style='display:flex;gap:10px;align-items:center'><div style='width:44px;height:44px;background:linear-gradient(135deg,var(--accent),#ffb020);border-radius:10px;display:flex;align-items:center;justify-content:center'>T</div><div><b>"+tname+"</b><div style='font-size:11px;color:#94a3b8'>"+tarea+" - <span class='cnt-badge'>"+str(cnt)+" IP</span></div></div></div><div id='arrow-"+str(tid)+"' style='transition:transform .3s'>V</div></div><div class='tower-accordion-body' id='tower-body-"+str(tid)+"' style='display:none'><div id='tower-content-"+str(tid)+"' style='padding:12px'></div></div></div>"
        acc+="<div class='card tower-accordion' id='tower-acc-0' data-loaded='0' style='border:1px dashed #ef444488'><div class='tower-accordion-header' onclick='toggleAccordionLazy(0)' style='padding:14px;display:flex;justify-content:space-between'><div><b>بدون برج</b><div style='font-size:11px;color:#94a3b8'>"+str(no_cnt)+" IP</div></div><div id='arrow-0'>V</div></div><div class='tower-accordion-body' id='tower-body-0' style='display:none'><div id='tower-content-0' style='padding:12px'></div></div></div>"
        return "<div style='max-width:1100px;margin:0 auto'><div class='card' style='display:flex;justify-content:space-between'><b>الصحون - انتقال ناعم 0.35s</b><div class='row'><input id='dishTowerSearch' placeholder='بحث برج' oninput='filterTowerAccordion(this.value)' style='padding:8px 12px;border-radius:8px'></div></div><div id='accordionContainer' style='display:flex;flex-direction:column;gap:10px;margin-top:12px'>"+acc+"</div></div><div id='addDishTowerModal' style='position:fixed;inset:0;background:#000a;display:none;align-items:center;justify-content:center;z-index:2500'><div style='background:var(--card-bg);width:95%;max-width:400px;border-radius:14px;padding:18px'><div style='display:flex;justify-content:space-between;margin-bottom:12px'><b>+ إضافة صحن</b><button onclick='closeAddDishModal()'>X</button></div><input id='modalDishName' placeholder='اسم الصحن' style='width:100%;padding:10px;margin-bottom:8px'><input id='modalDishIp' placeholder='IP' style='width:100%;padding:10px;margin-bottom:8px'><input id='modalDishLoc' placeholder='موقع' style='width:100%;padding:10px;margin-bottom:8px'><input type='hidden' id='modalDishTowerId'><div class='row' style='gap:8px'><button onclick='closeAddDishModal()' style='flex:1'>إلغاء</button><button onclick='saveDishToTower()' class='btn-gold' style='flex:1'>حفظ بدون تحديث</button></div></div></div><script>var DISH_CACHE={}; function escHtml(s){return (s||'').toString().replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');} function filterTowerAccordion(q){q=q.toLowerCase(); document.querySelectorAll('.tower-accordion').forEach(function(c){var n=(c.dataset.name||''); c.style.display=n.indexOf(q)!==-1||q===''?'block':'none';});} async function toggleAccordionLazy(tid){var body=document.getElementById('tower-body-'+tid); var arrow=document.getElementById('arrow-'+tid); var acc=document.getElementById('tower-acc-'+tid); var isOpen=body.classList.contains('open'); if(isOpen){body.classList.remove('open'); if(arrow) arrow.style.transform='rotate(0deg)'; setTimeout(function(){ if(!body.classList.contains('open')) body.style.display='none'; }, 350);} else {body.style.display='block'; void body.offsetWidth; body.classList.add('open'); if(arrow) arrow.style.transform='rotate(180deg)'; if(acc.dataset.loaded==='0'){var content=document.getElementById('tower-content-'+tid); content.innerHTML='<div style=\"text-align:center;padding:20px;color:#888\">تحميل...</div>'; try{let r=await fetch('/api/tower_detail/'+tid); let j=await r.json(); if(j.ok){DISH_CACHE[tid]=j.dishes||[]; acc.dataset.loaded='1'; var b=acc.querySelector('.cnt-badge'); if(b) b.textContent=j.dishes.length+' IP'; renderDishesBatch(tid,0);} }catch(e){content.innerHTML='خطأ';}}}} function renderDishesBatch(tid,start){var dishes=DISH_CACHE[tid]||[]; var content=document.getElementById('tower-content-'+tid); if(!content) return; if(start===0){content.innerHTML='<div id=\"dish-list-'+tid+'\" style=\"display:flex;flex-direction:column;gap:8px\"></div><div id=\"dish-more-'+tid+'\"></div><button class=\"btn-gold\" onclick=\"openAddDishModal('+tid+')\" style=\"width:100%;margin-top:12px\">+ إضافة صحن</button>';} var list=document.getElementById('dish-list-'+tid); var more=document.getElementById('dish-more-'+tid); var end=Math.min(start+10,dishes.length); var frag=document.createDocumentFragment(); for(var i=start;i<end;i++){var d=dishes[i]; var row=document.createElement('div'); row.id='dish-'+d.id; row.className='dish-row'; row.style.cssText='display:grid;grid-template-columns:1fr auto;gap:8px;align-items:center;background:#ffffff06;border:1px solid #ffffff14;border-radius:10px;padding:10px'; var ip=d.ip||''; row.innerHTML='<div><b class=\"dish-name\">'+escHtml(d.dish_name||'صحن')+'</b><span style=\"background:#000;color:#ffbe4d;padding:2px 8px;border-radius:6px;font-family:monospace;font-size:11px;margin-left:6px\">'+escHtml(ip)+'</span><div class=\"dish-loc\" style=\"font-size:11px;color:#94a3b8\">'+escHtml(d.location||'')+'</div></div><div style=\"display:flex;gap:4px\"><button onclick=\"openEditDishAcc('+d.id+')\">تعديل</button><button onclick=\"openDeleteModal(\\'/del_dish/'+d.id+'\\','+d.id+')\">حذف</button></div>'; frag.appendChild(row);} list.appendChild(frag); if(end < dishes.length){more.innerHTML='<button onclick=\"renderDishesBatch('+tid+','+end+')\" class=\"btn-gold\" style=\"width:100%\">عرض المزيد ('+(dishes.length-end)+') ↓</button>';} else {more.innerHTML='<div style=\"text-align:center;font-size:10px;color:#666\">تم '+dishes.length+' ✓</div>';}} function openAddDishModal(tid){document.getElementById('addDishTowerModal').style.display='flex'; document.getElementById('modalDishTowerId').value=tid;} function closeAddDishModal(){document.getElementById('addDishTowerModal').style.display='none';} async function saveDishToTower(){var name=document.getElementById('modalDishName').value.trim(); var ip=document.getElementById('modalDishIp').value.trim(); var loc=document.getElementById('modalDishLoc').value.trim(); var tid=document.getElementById('modalDishTowerId').value; if(!ip){alert('IP مطلوب'); return;} if(!name) name='صحن '+ip; let r=await fetch('/api/add_dish_to_tower',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ip:ip,dish_name:name,location:loc,tower_id:tid})}); let j=await r.json(); if(j.ok){closeAddDishModal(); var acc=document.getElementById('tower-acc-'+tid); if(acc) acc.dataset.loaded='0'; var body=document.getElementById('tower-body-'+tid); if(body && body.classList.contains('open')){body.classList.remove('open'); setTimeout(function(){toggleAccordionLazy(parseInt(tid));},360);} else {toggleAccordionLazy(parseInt(tid));}}} async function openEditDishAcc(did){let r=await fetch('/api/dish_detail/'+did); let j=await r.json(); if(!j.ok) return; let d=j.dish; let b=document.getElementById('editBody'); b.innerHTML=\"<input id='ed_name' value='\"+(d.dish_name||'')+\"'><input id='ed_ip' value='\"+(d.ip||'')+\"'><input id='ed_loc' value='\"+(d.location||'')+\"'><button class='btn-gold' onclick='saveDishAcc(\"+did+\")' style='width:100%'>حفظ</button>\"; document.getElementById('editModalTitle').textContent='تعديل'; document.getElementById('editModal').classList.add('show');} async function saveDishAcc(id){var d={dish_name:document.getElementById('ed_name').value,ip:document.getElementById('ed_ip').value,location:document.getElementById('ed_loc').value}; let r=await fetch('/edit_dish/'+id,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)}); let j=await r.json(); if(j.ok){closeEditModal(); var row=document.getElementById('dish-'+id); if(row && j.dish){row.querySelector('.dish-name').textContent=j.dish.dish_name; row.querySelector('.dish-loc').textContent=j.dish.location;}}}</script>"

    if v=='network':
        dishes=qall("SELECT * FROM dish_ips ORDER BY dish_name ASC")
        rows=""
        for d in dishes:
            rows+="<tr id='net-"+str(d.get('id'))+"' data-ip='"+esc(d.get('ip') or '')+"'><td>"+esc(d.get('dish_name') or '')+"</td><td><span class='ip'>"+esc(d.get('ip') or '')+"</span></td><td class='net-out'>...</td><td><button onclick='checkOne("+str(d.get('id'))+")'>فحص</button></td></tr>"
        return "<div class='card'><div class='row' style='justify-content:space-between'><b>الشبكة - فحص متوازي 20 IP</b><button class='btn-gold' onclick='checkAll()'>فحص الكل بسرعة</button></div><table style='width:100%;margin-top:8px'><thead><tr><th>اسم</th><th>IP</th><th>حالة</th><th></th></tr></thead><tbody>"+rows+"</tbody></table></div><script>window.checkOne=async function(id){let c=document.getElementById('net-'+id); let out=c.querySelector('.net-out'); out.textContent='...'; try{let r=await fetch('/api/ping?ip='+c.dataset.ip); let j=await r.json(); out.textContent=j.out; out.style.color=j.ok?'#22c55e':'#ef4444';}catch{out.textContent='خطأ';}}; window.checkAll=async function(){let all=document.querySelectorAll('[id^=net-]'); let ips=[]; all.forEach(function(c){ips.push(c.dataset.ip); c.querySelector('.net-out').textContent='...';}); try{let r=await fetch('/api/ping_batch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ips:ips})}); let j=await r.json(); if(j.ok){for(let ip in j.results){let el=document.querySelector('[data-ip=\"'+ip+'\"] .net-out'); if(!el){ el=document.querySelector('[data-ip=\"'+ip+'\"]'); if(el) el=document.getElementById('net-'+Object.keys(j.results).indexOf(ip));} } for(let ip in j.results){let rows=document.querySelectorAll('[data-ip]'); rows.forEach(function(row){if(row.dataset.ip===ip){let out=row.querySelector('.net-out'); if(out){out.textContent=j.results[ip].out; out.style.color=j.results[ip].ok?'#22c55e':'#ef4444';}}});} } }catch(e){console.log(e);}}; </script>"

    return "<div class='card'>404</div>"

def layout(v='home'):
    th=session.get('theme','dark')
    theme_class="dark" if th=='dark' else "light"
    cur_user=qone("SELECT * FROM users WHERE phone=?",(session.get('phone') or '',)) or {}
    username=esc(cur_user.get('username') or '')
    role=esc(cur_user.get('role') or '')
    css_vars=":root{--card-min:160px; --icon-size:44px; --accent:#ffbe4d; --card-bg-dark:#1e2433f2; --card-bg-light:#ffffff; --text-dark:#ffffff; --text-light:#0f172a; --border-dark:#ffffff14; --border-light:#e2e8f0}"
    html_page="""<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>OMAIA ISP</title><style>__CSS__*{box-sizing:border-box;font-family:system-ui}html,body{margin:0;padding:0}body.dark{--bg:radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 60%, #070a1f 100%); --card-bg:var(--card-bg-dark); --text:var(--text-dark); --border:var(--border-dark)}body.light{--bg:#eef2f7; --card-bg:var(--card-bg-light); --text:var(--text-light); --border:var(--border-light)}body{background:var(--bg);color:var(--text)} .card{background:var(--card-bg);color:var(--text);padding:10px;border-radius:12px;margin-bottom:8px;border:1px solid var(--border);transition:transform .28s cubic-bezier(0.4,0,0.2,1), box-shadow .28s ease, border-color .2s ease; will-change:transform} .card:hover{transform:translateY(-2px);box-shadow:0 10px 30px rgba(0,0,0,0.18), 0 4px 12px rgba(255,190,77,0.12)} .tower-accordion{border-radius:12px;overflow:hidden;border:1px solid #ffffff10;transition:transform .25s ease, box-shadow .25s ease} .tower-accordion:hover{transform:translateY(-1px);box-shadow:0 6px 20px rgba(0,0,0,0.12)} .tower-accordion-body{max-height:0;overflow:hidden;opacity:0;transition:max-height .35s cubic-bezier(0.4,0,0.2,1), opacity .28s ease;background:#0f1424} .tower-accordion-body.open{max-height:4000px;opacity:1} .tower-accordion-header{transition:background .2s ease} .tower-accordion-header:hover{background:rgba(255,190,77,0.04)} .grid-small{display:grid;grid-template-columns:repeat(auto-fill,minmax(var(--card-min),1fr));gap:8px} .top{position:fixed;top:0;left:0;right:0;height:56px;background:var(--card-bg);display:flex;align-items:center;justify-content:space-between;padding:0 12px;z-index:1003;border-bottom:1px solid var(--border)} .sidebar{position:fixed;top:0;right:0;width:320px;height:100vh;background:var(--card-bg);z-index:1002;padding-top:60px;transform:translateX(110%);transition:transform .32s cubic-bezier(0.4,0,0.2,1);overflow-y:auto;border-left:1px solid var(--border)} .sidebar.active{transform:none} .sidebar a{display:flex;align-items:center;gap:12px;padding:14px 16px;margin:6px 12px;color:var(--text);text-decoration:none;border-radius:10px;background:var(--border);font-weight:600;position:relative;overflow:hidden;transition:transform .28s cubic-bezier(0.4,0,0.2,1)} .sidebar a::after{content:'';position:absolute;inset:0;background:linear-gradient(90deg,var(--accent),#ffb020);transform:translateX(-105%);transition:transform .38s ease;z-index:-1;border-radius:inherit} .sidebar a.active::after{transform:translateX(0)} .sidebar a.active{color:#111;box-shadow:0 4px 14px rgba(255,190,77,0.25);transform:translateX(2px)} #overlay{position:fixed;inset:0;background:#0006;z-index:1001;display:none;opacity:0;transition:opacity .25s} #overlay.show{display:block;opacity:1} .main{margin-top:62px;padding:10px;min-height:90vh} #mn{animation:pageEnter .38s cubic-bezier(0.4,0,0.2,1)} @keyframes pageEnter{from{opacity:0;transform:translateY(8px) scale(0.98)} to{opacity:1;transform:translateY(0) scale(1)}} .row{display:flex;gap:6px;align-items:center;flex-wrap:wrap} .btn-gold{background:linear-gradient(90deg,var(--accent),#ffb020);color:#111;padding:7px 12px;border:0;border-radius:8px;font-weight:700;font-size:11px;cursor:pointer;transition:transform .18s ease, box-shadow .18s ease} .btn-gold:hover{transform:translateY(-1px);box-shadow:0 4px 12px rgba(255,190,77,0.3)} .mini-btn{background:var(--border);color:var(--text);border:0;padding:5px 8px;border-radius:6px;font-size:11px} .mini-btn-del{background:#ef4444;color:#fff;border:0;padding:5px 8px;border-radius:6px;font-size:11px} .ip{background:#000;color:var(--accent);padding:2px 6px;border-radius:5px;font-family:monospace;font-size:10px}.badge{background:var(--accent);color:#111;padding:2px 6px;border-radius:5px;font-size:10px} #editModal{position:fixed;inset:0;background:#0008;display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:.25s;z-index:2000} #editModal.show{opacity:1;pointer-events:auto} #editBox{background:var(--card-bg);color:var(--text);padding:18px;border-radius:14px;width:92%;max-width:420px;transform:scale(.95);transition:.32s;border:1px solid var(--border)} #editModal.show #editBox{transform:scale(1)} input,select{padding:9px 11px;border-radius:8px;border:1px solid var(--border);background:var(--border);color:var(--text);font-size:12px} .dish-row{transition:transform .22s ease, box-shadow .22s ease !important} .dish-row:hover{transform:translateY(-1.5px) !important;box-shadow:0 6px 18px rgba(0,0,0,0.12) !important;border-color:var(--accent) !important} </style></head><body class="__THEME__"><div id=overlay onclick="toggleSb(false)"></div><div class=sidebar id=sb><div style='padding:0 16px 14px;border-bottom:1px solid var(--border)'><b>OMAIA <span style='color:var(--accent)'>ISP</span></b><br><small>__USERNAME__ • __ROLE__</small></div><a href="javascript:loadPage('home')" id=nav-home>الرئيسية</a><a href="javascript:loadPage('towers')" id=nav-towers>الأبراج</a><a href="javascript:loadPage('dishes')" id=nav-dishes>الصحون</a><a href="javascript:loadPage('network')" id=nav-network>الشبكة</a><a href="javascript:loadPage('subs')" id=nav-subs>المشتركين</a><a href="javascript:logoutFast()" style='margin:12px;background:#ef444422'>خروج</a></div><div class=top><div class=row><span onclick="toggleSb()" style='font-size:24px;cursor:pointer;padding:6px 12px;background:var(--border);border-radius:8px'>☰</span></div><b>OMAIA <span style='color:var(--accent)'>ISP</span></b><div class=row><button onclick="toggleThemeFast()" style="width:38px;height:38px;background:var(--border);border:1px solid var(--border);color:var(--text);border-radius:8px">🌓</button></div></div><div class=main id=mn>__CONTENT__</div><div id=editModal><div id=editBox><div class=row style='justify-content:space-between;margin-bottom:12px'><b id=editModalTitle>نافذة</b><button onclick="closeEditModal()" style='width:30px;height:30px;border-radius:50%;background:var(--border);border:0;color:var(--text)'>X</button></div><div id=editBody></div></div></div><script>var cur='__V__'; function toggleSb(f){var sb=document.getElementById('sb'),ov=document.getElementById('overlay'); var o=f!==undefined?f:!sb.classList.contains('active'); sb.classList.toggle('active',o); ov.classList.toggle('show',o);} async function loadPage(v,push=true){ if(push && cur!==v){try{history.pushState({page:v},'', '/dash?v='+v)}catch(e){}} cur=v; toggleSb(false); document.querySelectorAll('.sidebar a').forEach(function(a){a.classList.remove('active');}); var n=document.getElementById('nav-'+v); if(n) n.classList.add('active'); var mn=document.getElementById('mn'); mn.style.animation='none'; mn.offsetHeight; mn.style.animation='pageEnter .38s cubic-bezier(0.4,0,0.2,1)'; mn.innerHTML='<div class=card style="text-align:center;padding:20px">تحميل...</div>'; try{let r=await fetch('/api/page?v='+v,{cache:'no-store'}); let h=await r.text(); mn.innerHTML=h; execScripts();}catch(e){mn.innerHTML='<div class=card>خطأ</div>';}} function execScripts(){document.getElementById('mn').querySelectorAll('script').forEach(function(o){var s=document.createElement('script'); s.textContent=o.textContent; document.body.appendChild(s); o.remove();});} window.closeEditModal=function(){document.getElementById('editModal').classList.remove('show');}; window.openDeleteModal=function(url,id){ var b=document.getElementById("editBody"); b.innerHTML='<div style="text-align:center;padding:10px"><h3>تأكيد الحذف؟</h3><div style="display:flex;gap:8px;margin-top:14px"><button onclick="closeEditModal()" style="flex:1;padding:10px;border-radius:8px;background:transparent;border:1px solid var(--border);color:var(--text)">تراجع</button><button id="delConfirmBtn" style="flex:1;padding:10px;border-radius:8px;background:#ef4444;color:#fff;border:0">حذف</button></div></div>'; document.getElementById("editModalTitle").textContent="تأكيد الحذف"; document.getElementById("editModal").classList.add("show"); document.getElementById("delConfirmBtn").onclick=async function(){ var el=document.getElementById('tower-'+id)||document.getElementById('dish-'+id)||document.getElementById('tower-acc-'+id); if(el){el.style.transition='transform .3s, opacity .3s'; el.style.transform='scale(.92)'; el.style.opacity='0';} try{let r=await fetch(url); let j=await r.json(); if(j.ok){if(el) setTimeout(function(){el.remove();},300); closeEditModal();} else {if(el){el.style.transform='scale(1)'; el.style.opacity='1';}}}catch(e){if(el){el.style.transform='scale(1)'; el.style.opacity='1';}}};}; window.toggleThemeFast=async function(){try{let r=await fetch('/toggle_theme'); let j=await r.json(); document.body.className=j.theme; localStorage.setItem('theme',j.theme);}catch(e){var cur=document.body.classList.contains('dark')?'dark':'light'; var nxt=cur==='dark'?'light':'dark'; document.body.className=nxt; localStorage.setItem('theme',nxt);}}; window.logoutFast=async function(){try{await fetch('/api/logout',{method:'POST'});}catch{} location.replace('/login');}; (function(){var th=localStorage.getItem('theme'); if(th) document.body.className=th;})(); loadPage(cur,true,false);</script></body></html>"""
    html_page=html_page.replace("__CSS__",css_vars)
    html_page=html_page.replace("__THEME__",theme_class)
    html_page=html_page.replace("__USERNAME__",username)
    html_page=html_page.replace("__ROLE__",role)
    html_page=html_page.replace("__V__",v)
    html_page=html_page.replace("__CONTENT__","<div class=card>...</div>")
    return html_page

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)),debug=False)
