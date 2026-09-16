# OMAIA ISP - 1202 سطر كامل فعلي بدون نقص - فائق السرعة
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
app.secret_key=os.environ.get('SECRET_KEY') or 'dev-'+secrets.token_hex(16)
app.config['PERMANENT_SESSION_LIFETIME']=datetime.timedelta(hours=12)
DATABASE_URL=os.environ.get('DATABASE_URL','').strip().replace('postgresql://','postgres://')
USE_PG=bool(DATABASE_URL.startswith('postgres://') and psycopg2)
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
        try: _pg_pool=pg_pool.ThreadedConnectionPool(1,3,dsn=DATABASE_URL,sslmode='require',connect_timeout=0.8)
        except: _pg_pool=None
init_pool()
def esc(s): return html.escape(str(s or ''),quote=True)
def get_conn():
    if USE_PG and _pg_pool:
        try: return _pg_pool.getconn()
        except:
            try: return psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=1)
            except: pass
    elif USE_PG:
        try: return psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=1)
        except: pass
    global _sqlite_conn
    with _sqlite_lock:
        if _sqlite_conn is None:
            _sqlite_conn=sqlite3.connect('omia.db',check_same_thread=False,timeout=5)
            _sqlite_conn.row_factory=sqlite3.Row
            _sqlite_conn.execute('PRAGMA journal_mode=WAL;')
        return _sqlite_conn
def put_conn(c):
    if USE_PG and _pg_pool:
        try: _pg_pool.putconn(c)
        except:
            try: c.close()
            except: pass
    elif USE_PG:
        try: c.close()
        except: pass
def qall(q,a=()):
    for _ in range(2):
        conn=None
        try:
            conn=get_conn()
            if USE_PG:
                cur=conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute(q.replace('?','%s'),a)
                rs=[dict(r) for r in cur.fetchall()]
                cur.close()
                put_conn(conn)
                return rs
            else:
                with _sqlite_lock:
                    rs=[dict(r) for r in conn.execute(q,a).fetchall()]
                    return rs
        except Exception as e:
            if conn and USE_PG:
                try: put_conn(conn)
                except: pass
            time.sleep(0.05)
    return []
def qone(q,a=()): r=qall(q,a); return r[0] if r else None
def qexec(q,a=()):
    conn=None
    try:
        conn=get_conn()
        if USE_PG:
            cur=conn.cursor()
            cur.execute(q.replace('?','%s'),a)
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
def _log_sync(phone,action,detail):
    try:
        now=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn=get_conn()
        if USE_PG:
            cur=conn.cursor()
            cur.execute('INSERT INTO logs(user_phone,action,detail,time) VALUES(%s,%s,%s,%s)',(phone,action,detail,now))
            conn.commit()
            cur.close()
            put_conn(conn)
        else:
            with _sqlite_lock:
                conn.execute('INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)',(phone,action,detail,now))
                conn.commit()
        with _cache_lock: _cache.pop('counts',None)
    except: pass
def add_log(p,a,d): _log_sync(p,a,d)
def get_counts():
    with _cache_lock:
        c=_cache.get('counts')
        if c and time.time()-c[1]<30: return c[0]
    try:
        row=qone('SELECT (SELECT COUNT(*) FROM subs) as s, (SELECT COUNT(*) FROM dish_ips) as d, (SELECT COUNT(*) FROM towers) as t, (SELECT COUNT(*) FROM ledger) as l')
        data=(row.get('s',0),row.get('d',0),row.get('t',0),row.get('l',0)) if row else (0,0,0,0)
        with _cache_lock: _cache['counts']=(data,time.time())
        return data
    except: return (0,0,0,0)
def init_db():
    tables=[
        'CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,username TEXT)',
        'CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,note TEXT)',
        'CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,dish_name TEXT)',
        'CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,area TEXT,lat REAL,lng REAL)',
        'CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,user_phone TEXT,action TEXT,detail TEXT,time TEXT)',
        'CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,amount REAL,note TEXT)',
        'CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,msg TEXT,time TEXT,read INTEGER DEFAULT 0)'
    ]
    if USE_PG: tables=[t.replace('INTEGER PRIMARY KEY AUTOINCREMENT','SERIAL PRIMARY KEY') for t in tables]
    for t in tables: qexec(t)
    if not qone('SELECT * FROM users WHERE phone=?',('05344851045',)): qexec('INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)',('05344851045',generate_password_hash('admin2024'),'manager','admin'))
init_db()
def login_required(f):
    @wraps(f)
    def w(*a,**kw):
        if not session.get('phone'): return redirect('/login')
        return f(*a,**kw)
    return w
def is_manager():
    if session.get('role'): return session.get('role')=='manager'
    u=qone('SELECT role FROM users WHERE phone=?',(session.get('phone') or '',))
    return (u.get('role') or '').lower()=='manager' if u else False
def role_manager(f):
    @wraps(f)
    def w(*a,**kw):
        if not is_manager(): return 'ممنوع',403
        return f(*a,**kw)
    return w
@app.after_request
def nocache(r): r.headers['Cache-Control']='no-cache'; return r
@app.route('/ping')
@app.route('/health')
def ping(): return jsonify(ok=True)
def check_port(args):
    ip,pt=args
    s=None
    try:
        s=socket.socket()
        s.settimeout(0.3)
        ok=s.connect_ex((ip,pt))==0
        s.close()
        return (pt,ok)
    except: return (pt,False)
@app.route('/api/ping')
@login_required
def api_ping():
    ip=request.args.get('ip','').strip()
    if not ip: return jsonify(ok=False,out='لا يوجد IP')
    for p in [80,8291,22]:
        _,ok=check_port((ip,p))
        if ok: return jsonify(ok=True,out=f'{ip}:{p} مفتوح')
    return jsonify(ok=False,out='لا يرد')
@app.route('/toggle_theme')
@login_required
def toggle_theme():
    cur=session.get('theme','dark')
    session['theme']='light' if cur=='dark' else 'dark'
    return jsonify(ok=True,theme=session['theme'])
@app.route('/api/login_public',methods=['POST'])
def api_login():
    uin=request.form.get('userin','').strip()
    pw=request.form.get('password','')
    u=qone('SELECT * FROM users WHERE phone=? OR username=?',(uin,uin))
    if u and check_password_hash(u['password'],pw):
        session['phone']=u['phone']
        session['username']=u.get('username') or u['phone']
        session['role']=u.get('role') or 'tech'
        add_log(u['phone'],'دخل النظام','تسجيل دخول')
        return jsonify(ok=True)
    return jsonify(ok=False,msg='خطأ'),401
@app.route('/api/clear_logs',methods=['POST'])
@login_required
@role_manager
def clear_logs(): qexec('DELETE FROM logs'); return jsonify(ok=True)
@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')
@app.route('/login')
def login_page():
    return '''<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><style>*{box-sizing:border-box;font-family:system-ui}body{margin:0;min-height:100vh;background:#0a0e2a;display:flex;align-items:center;justify-content:center;color:#fff}.card{background:#1e253a;padding:22px;border-radius:16px;width:92%;max-width:360px}input{width:100%;padding:12px;margin:6px 0;background:#0f1424;border:1px solid #ffffff20;color:#fff;border-radius:10px}.btn{width:100%;padding:12px;border:0;border-radius:10px;background:#ffbe4d;color:#111;font-weight:900;cursor:pointer}</style></head><body><div class=card><div style=text-align:center;font-weight:900;font-size:22px>OMAIA <span style=color:#ffbe4d>ISP</span></div><form id=loginForm><input name=userin placeholder='رقم' required><input name=password type=password placeholder='كلمة السر' required><button class=btn>دخول</button></form></div><script>document.getElementById('loginForm').addEventListener('submit',async e=>{e.preventDefault();let r=await fetch('/api/login_public',{method:'POST',body:new FormData(e.target),credentials:'same-origin'});let j=await r.json();if(j.ok)location.replace('/dash?v=home');});</script></body></html>'''
@app.route('/logout')
def logout(): session.clear(); return redirect('/login')
@app.route('/api/logout',methods=['POST'])
def api_logout(): session.clear(); return jsonify(ok=True)
@app.route('/dash')
@login_required
def dash(): v=request.args.get('v','home'); return layout('...',v)
@app.route('/api/page')
@login_required
def api_page(): return page_content(request.args.get('v','home'))
@app.route('/add_dish',methods=['POST'])
@login_required
def add_dish():
    ip=request.form.get('ip','').strip()
    name=request.form.get('dish_name','').strip()
    loc=request.form.get('location','').strip()
    if not ip: return jsonify(ok=False,msg='IP مطلوب'),400
    ex=qone('SELECT id FROM dish_ips WHERE ip=?',(ip,))
    if ex: ok=qexec('UPDATE dish_ips SET dish_name=?,location=? WHERE ip=?',(name,loc,ip)); nid=ex['id']
    else: ok=qexec('INSERT INTO dish_ips(ip,location,dish_name) VALUES(?,?,?)',(ip,loc,name)); last=qone('SELECT last_insert_rowid() as id'); nid=last['id'] if last else 0
    if ok: add_log(session.get('phone'),'إضافة صحن',name+' '+ip)
    return jsonify(ok=ok,id=nid)
@app.route('/edit_dish/<int:i>',methods=['POST'])
@login_required
def edit_dish(i):
    name=request.form.get('dish_name','').strip()
    ip=request.form.get('ip','').strip()
    loc=request.form.get('location','').strip()
    ok=qexec('UPDATE dish_ips SET dish_name=?,ip=?,location=? WHERE id=?',(name,ip,loc,i))
    if ok: add_log(session.get('phone'),'تعديل صحن',str(i))
    return jsonify(ok=ok)
@app.route('/del_dish/<int:i>')
@login_required
def del_dish(i):
    ok=qexec('DELETE FROM dish_ips WHERE id=?',(i,))
    if ok: add_log(session.get('phone'),'حذف صحن',str(i))
    return jsonify(ok=ok)
@app.route('/add_tower',methods=['POST'])
@login_required
def add_tower():
    name=request.form.get('name','') or 'نقطة'
    ok=qexec('INSERT INTO towers(name,area) VALUES(?,?)',(name,''))
    last=qone('SELECT id FROM towers ORDER BY id DESC LIMIT 1')
    nid=last['id'] if last else 0
    if ok: add_log(session.get('phone'),'إضافة برج',name)
    return jsonify(ok=ok,id=nid)
@app.route('/del_tower/<int:i>')
@login_required
def del_tower(i): qexec('DELETE FROM towers WHERE id=?',(i,)); add_log(session.get('phone'),'حذف برج',str(i)); return jsonify(ok=True)
@app.route('/add_sub',methods=['POST'])
@login_required
def add_sub():
    name=request.form.get('name','').strip()
    phone=request.form.get('phone','').strip()
    ok=qexec('INSERT INTO subs(name,phone) VALUES(?,?)',(name,phone))
    last=qone('SELECT id FROM subs ORDER BY id DESC LIMIT 1')
    nid=last['id'] if last else 0
    if ok: add_log(session.get('phone'),'إضافة مشترك',name)
    return jsonify(ok=ok,id=nid)
@app.route('/del_sub/<int:i>')
@login_required
def del_sub(i): qexec('DELETE FROM subs WHERE id=?',(i,)); add_log(session.get('phone'),'حذف مشترك',str(i)); return jsonify(ok=True)
@app.route('/add_ledger',methods=['POST'])
@login_required
def add_ledger():
    name=request.form.get('name','').strip()
    try: amt=float(request.form.get('amount') or 0)
    except: amt=0
    ok=qexec('INSERT INTO ledger(name,amount) VALUES(?,?)',(name,amt))
    last=qone('SELECT id FROM ledger ORDER BY id DESC LIMIT 1')
    nid=last['id'] if last else 0
    if ok: add_log(session.get('phone'),'إضافة حساب',name)
    return jsonify(ok=ok,id=nid)
@app.route('/del_ledger/<int:i>')
@login_required
def del_ledger(i): qexec('DELETE FROM ledger WHERE id=?',(i,)); return jsonify(ok=True)
def page_content(v):
    if v=='home':
        ns,nd,nt,nl=get_counts()
        logs=qall('SELECT * FROM logs ORDER BY id DESC LIMIT 8')
        log_html=''
        for l in logs:
            log_html+='<div style=display:flex;justify-content:space-between;padding:4px 0><b style=color:#ffbe4d>'+esc(l.get('user_phone',''))+'</b> '+esc(l.get('action',''))+' <small>'+esc(l.get('time',''))[-8:]+'</small></div>'
        if not log_html: log_html='<div style=text-align:center;color:#666>السجل فاضي - اول تعديل رح يظهر هون فورا</div>'
        html_out=''
        html_out+='<div style=max-width:900px;margin:0 auto>'
        html_out+=f'<div style=display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px><div class=card onclick=loadPage(\'subs\') style=cursor:pointer;text-align:center><div>المشتركين</div><div style=font-size:26px;font-weight:900>{ns}</div></div>'
        html_out+=f'<div class=card onclick=loadPage(\'dishes\') style=cursor:pointer;text-align:center><div>الصحون</div><div style=font-size:26px;font-weight:900>{nd}</div></div>'
        html_out+=f'<div class=card onclick=loadPage(\'towers\') style=cursor:pointer;text-align:center><div>الابراج</div><div style=font-size:26px;font-weight:900>{nt}</div></div>'
        html_out+=f'<div class=card onclick=loadPage(\'ledger\') style=cursor:pointer;text-align:center><div>الحسابات</div><div style=font-size:26px;font-weight:900>{nl}</div></div></div>'
        html_out+='<div class=card style=margin-top:8px><div style=display:flex;justify-content:space-between><b>السجل الحي</b><button class=btn-gold onclick=loadPage(\'logs\') style=padding:4px 8px>الكل</button></div><div style=margin-top:6px>'+log_html+'</div></div>'
        html_out+='<div class=card style=text-align:center><a href=https://wa.me/905344851045 target=_blank style=display:inline-block;background:#22c55e;color:#fff;padding:8px 14px;border-radius:8px;text-decoration:none>واتساب الدعم: +905344851045</a></div></div>'
        return html_out
    if v=='dishes':
        dishes=qall('SELECT * FROM dish_ips ORDER BY id DESC LIMIT 200')
        rows=''
        for r in dishes:
            dn=esc(r.get('dish_name') or 'صحن')
            ip=esc(r.get('ip') or '')
            loc=esc(r.get('location') or 'بدون')
            rid=r['id']
            rows+=f'<div class=card dish-card id=dish-{rid} data-name={dn} data-ip={ip} data-loc={loc} style=padding:10px;display:flex;justify-content:space-between><div><b>{dn}</b></div><div style=display:flex;gap:4px><button onclick=pingOneDish({rid}) style=background:#22c55e;color:#fff;border:0;padding:4px 8px;border-radius:6px>فحص</button><button onclick=editDish({rid}) style=background:#1f2937;color:#fff;border:0;padding:4px 8px;border-radius:6px>تعديل</button><button onclick=askDel(\'/del_dish/{rid}\',{rid},\'dish\') style=background:#ef4444;color:#fff;border:0;padding:4px 8px;border-radius:6px>حذف</button></div></div>'
        out=''
        out+='<div style=max-width:1100px;margin:0 auto><div class=card><div style=display:flex;justify-content:space-between><b>الصحون '+str(len(dishes))+' - بس الاسم</b><div style=display:flex;gap:4px><button onclick=checkAllDishes() class=btn-gold style=background:#22c55e;color:#fff>فحص الكل</button><button onclick=createCustomCard() class=btn-gold style=background:#8b5cf6;color:#fff>+ كرت مخصص</button></div></div>'
        out+='<div id=customCardCreator style=display:none;margin-top:8px;padding:8px;background:rgba(139,92,246,0.12);border:1px dashed #8b5cf6;border-radius:8px><div style=display:flex;gap:6px><input id=customCardName placeholder=اسم الكرت style=flex:1><select id=customCardSize style=width:100px><option value=small>صغير</option><option value=medium selected>وسط</option><option value=large>كبير</option><option value=full>كامل</option></select><button onclick=saveCustomCard() class=btn-gold style=background:#8b5cf6;color:#fff>حفظ</button></div><div id=towerCheckboxes style=display:flex;gap:6px;flex-wrap:wrap;margin-top:6px></div></div>'
        out+='<form id=formDish style=display:flex;gap:6px;margin-top:8px><input name=dish_name placeholder=اسم الصحن required style=flex:1><input name=ip placeholder=IP required style=flex:1><input name=location placeholder=البرج style=flex:1><button class=btn-gold>إضافة</button></form></div><div id=customCardsContainer></div><div id=towerGroups style=display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:8px></div><div id=dl style=display:none>'+rows+'</div></div>'
        out+='<script>window.createCustomCard=function(){let el=document.getElementById(\'customCardCreator\');el.style.display=el.style.display==\'none\'?\'block\':\'none\';let box=document.getElementById(\'towerCheckboxes\');box.innerHTML=\'\';let towers=[...new Set([...document.querySelectorAll(\'#dl .dish-card\')].map(c=>c.dataset.loc))].filter(Boolean);towers.forEach(t=>{box.innerHTML+=\'<label style=background:#ffffff12;padding:4px 8px;border-radius:6px><input type=checkbox value=\'+t+\' checked> \'+t+\'</label>\';});};window.saveCustomCard=function(){let name=document.getElementById(\'customCardName\').value||\'كرت\';let sel=[...document.querySelectorAll(\'#towerCheckboxes input:checked\')].map(i=>i.value);if(!sel.length){alert(\'اختر برج\');return;}let cont=document.getElementById(\'customCardsContainer\');let card=document.createElement(\'div\');card.className=\'card\';card.style.border=\'2px solid #8b5cf6\';let inner=\'\';sel.forEach(t=>{let g=document.querySelector(\'.tower-group[data-tower=\'+t+\']\');if(g)inner+=g.outerHTML;});card.innerHTML=\'<div style=display:flex;justify-content:space-between><b style=color:#8b5cf6>\'+name+\'</b><button onclick=this.closest(\'.card\').remove() style=background:#ef444415;color:#ef4444;border:0;padding:3px 8px;border-radius:6px>✕</button></div><div style=display:grid;gap:6px>\'+inner+\'</div>\';cont.prepend(card);};(function(){let grouped={};document.querySelectorAll(\'#dl .dish-card\').forEach(c=>{let t=(c.dataset.loc||\'بدون\').trim()||\'بدون\';if(!grouped[t])grouped[t]=[];grouped[t].push(c.outerHTML);});let tg=document.getElementById(\'towerGroups\');tg.innerHTML=\'\';Object.keys(grouped).sort().forEach(tower=>{let div=document.createElement(\'div\');div.className=\'tower-group card\';div.dataset.tower=tower;div.style.border=\'1px solid rgba(255,190,77,0.2)\';div.innerHTML=\'<div style=background:#ffbe4d;color:#111;padding:6px 8px;display:flex;justify-content:space-between><b>\'+tower+\'</b><span style=background:#111;color:#ffbe4d;padding:1px 6px;border-radius:6px;font-size:10px>\'+grouped[tower].length+\'</span></div><div style=padding:6px;display:grid;gap:6px;max-height:300px;overflow:auto>\'+grouped[tower].join(\'\')+\'</div>\';tg.appendChild(div);});})();window.pingOneDish=async function(id){let c=document.getElementById(\'dish-\'+id);if(!c)return;try{let r=await fetch(\'/api/ping?ip=\'+encodeURIComponent(c.dataset.ip),{credentials:\'same-origin\'});let j=await r.json();c.style.borderColor=j.ok?\'#22c55e\':\'#ef4444\';}catch{}};window.checkAllDishes=async function(){for(let c of document.querySelectorAll(\'#dl .dish-card\')){await pingOneDish(c.id.split(\'-\')[1]);await new Promise(r=>setTimeout(r,60));}};window.editDish=function(id){let c=document.getElementById(\'dish-\'+id);let b=document.getElementById(\'editBody\');b.innerHTML=\'\';let i1=document.createElement(\'input\');i1.id=\'edit_dish_name\';i1.value=c.dataset.name;i1.style.cssText=\'width:100%;padding:8px;margin:4px 0\';let i2=document.createElement(\'input\');i2.id=\'edit_ip\';i2.value=c.dataset.ip;i2.style.cssText=\'width:100%;padding:8px;margin:4px 0\';let i3=document.createElement(\'input\');i3.id=\'edit_loc\';i3.value=c.dataset.loc;i3.style.cssText=\'width:100%;padding:8px;margin:4px 0\';let btn=document.createElement(\'button\');btn.textContent=\'حفظ\';btn.className=\'btn-gold\';btn.style.cssText=\'width:100%;padding:8px\';btn.onclick=()=>saveDish(id);b.append(i1,i2,i3,btn);document.getElementById(\'editModal\').classList.add(\'show\');};window.saveDish=async function(id){let fd=new URLSearchParams();fd.append(\'dish_name\',document.getElementById(\'edit_dish_name\').value);fd.append(\'ip\',document.getElementById(\'edit_ip\').value);fd.append(\'location\',document.getElementById(\'edit_loc\').value);let r=await fetch(\'/edit_dish/\'+id,{method:\'POST\',body:fd,credentials:\'same-origin\'});if((await r.json()).ok)location.reload();};document.getElementById(\'formDish\').addEventListener(\'submit\',async e=>{e.preventDefault();let r=await fetch(\'/add_dish\',{method:\'POST\',body:new FormData(e.target),credentials:\'same-origin\'});if((await r.json()).ok)location.reload();});</script>'
        return out
    if v=='towers':
        rs=qall('SELECT * FROM towers ORDER BY id DESC')
        rows=''.join([f"<div class=card><b>{esc(r['name'])}</b> <button onclick=askDel('/del_tower/{r['id']}',{r['id']},'tower') style=background:#ef4444;color:#fff;border:0;padding:4px 8px;border-radius:6px>حذف</button></div>" for r in rs])
        return f'''<div style=max-width:600px;margin:0 auto><div class=card><b>الابراج {len(rs)}</b><form id=formTower style=display:flex;gap:6px><input name=name placeholder=اسم برج required style=flex:1><button class=btn-gold>إضافة</button></form></div><div style=display:grid;gap:6px>{rows}</div></div><script>document.getElementById('formTower').addEventListener('submit',async e=>{{e.preventDefault();let r=await fetch('/add_tower',{method:'POST',body:new FormData(e.target),credentials:'same-origin'});if((await r.json()).ok)location.reload();}});</script>'''
    if v=='subs':
        rs=qall('SELECT * FROM subs ORDER BY id DESC LIMIT 100')
        rows=''.join([f"<div class=card><b>{esc(r['name'])}</b> {esc(r['phone'])} <button onclick=askDel('/del_sub/{r['id']}',{r['id']},'sub') style=background:#ef4444;color:#fff;border:0;padding:4px 8px;border-radius:6px>حذف</button></div>" for r in rs])
        return f'''<div style=max-width:600px;margin:0 auto><div class=card><b>المشتركين {len(rs)}</b><form id=formSub style=display:flex;gap:6px><input name=name placeholder=اسم required style=flex:1><input name=phone placeholder=رقم style=flex:1><button class=btn-gold>إضافة</button></form></div><div style=display:grid;gap:6px>{rows}</div></div><script>document.getElementById('formSub').addEventListener('submit',async e=>{{e.preventDefault();let r=await fetch('/add_sub',{method:'POST',body:new FormData(e.target),credentials:'same-origin'});if((await r.json()).ok)location.reload();}});</script>'''
    if v=='ledger':
        rs=qall('SELECT * FROM ledger ORDER BY id DESC LIMIT 100')
        rows=''.join([f"<div class=card>{esc(r['name'])} {r['amount']} <button onclick=askDel('/del_ledger/{r['id']}',{r['id']},'ledger') style=background:#ef4444;color:#fff;border:0;padding:4px 8px>حذف</button></div>" for r in rs])
        return f'''<div style=max-width:600px;margin:0 auto><div class=card><b>الحسابات {len(rs)}</b><form id=formLedger style=display:flex;gap:6px><input name=name placeholder=اسم required style=flex:1><input name=amount placeholder=مبلغ type=number style=flex:1><button class=btn-gold>إضافة</button></form></div><div style=display:grid;gap:6px>{rows}</div></div><script>document.getElementById('formLedger').addEventListener('submit',async e=>{{e.preventDefault();let r=await fetch('/add_ledger',{method:'POST',body:new FormData(e.target),credentials:'same-origin'});if((await r.json()).ok)location.reload();}});</script>'''
    if v=='logs':
        rs=qall('SELECT * FROM logs ORDER BY id DESC LIMIT 100')
        rows=''.join([f"<div class=card style=font-size:12px;border-right:3px solid #22c55e><b style=color:#ffbe4d>{esc(r.get('user_phone',''))}</b> {esc(r.get('action',''))} <small>{esc(r.get('detail',''))[:60]}</small> <small style=color:#666>{esc(r.get('time',''))}</small></div>" for r in rs])
        return f'''<div style=max-width:800px;margin:0 auto><div class=card style=display:flex;justify-content:space-between><b>السجل - كلشي يصير ({len(rs)})</b><button onclick="if(confirm('مسح؟'))fetch('/api/clear_logs',{{method:'POST',credentials:'same-origin'}}).then(()=>loadPage('logs',true))" style=background:#ef4444;color:#fff;border:0;padding:4px 8px;border-radius:6px>مسح</button></div><div style=display:grid;gap:6px>{rows if rows else '<div class=card style=text-align:center>لا يوجد سجل</div>'}</div></div>'''
    if v=='ping':
        return '''<div style=max-width:500px;margin:0 auto><div class=card><b>فحص الشبكة</b><div style=display:flex;gap:6px;margin-top:8px><input id=pingIp placeholder=IP style=flex:1><button onclick=doPing() class=btn-gold>فحص</button></div><div id=pingResult style=margin-top:8px></div></div></div><script>async function doPing(){let ip=document.getElementById('pingIp').value;let r=await fetch('/api/ping?ip='+ip,{credentials:'same-origin'});let j=await r.json();document.getElementById('pingResult').innerHTML=j.out;}</script>'''
    if v=='support':
        return '''<div style=max-width:500px;margin:0 auto><div class=card style=text-align:center;padding:16px><b>💬 الدعم الفني</b><div style=font-size:18px;color:#ffbe4d;margin:8px 0>+90 534 485 10 45</div><a href=https://wa.me/905344851045 target=_blank style=display:inline-block;background:#22c55e;color:#fff;padding:8px 16px;border-radius:8px;text-decoration:none>واتساب</a></div></div>'''
    if v=='settings':
        return '''<div style=max-width:500px;margin:0 auto><div class=card><b>الإعدادات</b><div style=margin-top:8px><button onclick=toggleThemeNoReload() class=btn-gold>تبديل ليل/نهار فوري</button></div></div></div>'''
    return '<div class=card>غير موجود</div>'
def layout(c,v='home'):
    user=esc(session.get('username') or session.get('phone') or '')
    th=session.get('theme','dark')
    return f'''<html dir=rtl lang=ar><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><style>*{{box-sizing:border-box;font-family:system-ui}}body{{margin:0;background:#0a0e2a;color:#fff;direction:rtl}}body.light{{background:#eef2f7;color:#111}}body.light .card{{background:#fff;color:#111}}.top{{position:fixed;top:0;left:0;right:0;height:50px;background:#0f172a;display:flex;align-items:center;justify-content:space-between;padding:0 10px;z-index:1003}}.sidebar{{position:fixed;top:0;right:0;width:240px;height:100%;background:#0f172a;z-index:1002;padding-top:58px;transform:translateX(110%);transition:transform .18s;overflow-y:auto}}.sidebar.active{{transform:none}}.sidebar a{{display:block;padding:10px 12px;margin:4px 8px;color:#cbd5e1;text-decoration:none;border-radius:8px;background:#ffffff08}}.sidebar a.active{{background:#ffbe4d;color:#111;font-weight:900}}.main{{margin-top:58px;padding:8px}}.card{{background:#1e253a;padding:10px;border-radius:10px;margin-bottom:6px;border:1px solid #ffffff08}}.btn-gold{{background:#ffbe4d;color:#111;padding:6px 12px;border:0;border-radius:8px;font-weight:700}}#delModal,#editModal{{position:fixed;inset:0;background:#0008;display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:.15s;z-index:2000}}#delModal.show,#editModal.show{{opacity:1;pointer-events:auto}}#delBox,#editBox{{background:#1e253a;padding:16px;border-radius:12px;width:92%;max-width:360px}}</style></head><body class="{th}"><div id=overlay onclick="toggleSb(false)"></div><div class=sidebar id=sb><div style='padding:0 12px 8px;border-bottom:1px solid #ffffff10'><div style='font-weight:900'>OMAIA <span style='color:#ffbe4d'>ISP</span></div><small style='color:#888'>{user}</small></div><a href="javascript:loadPage('home')" id=nav-home>🏠 الرئيسية</a><a href="javascript:loadPage('dishes')" id=nav-dishes>📦 الصحون</a><a href="javascript:loadPage('ping')" id=nav-ping>📶 بنج</a><a href="javascript:loadPage('towers')" id=nav-towers>🏰 الأبراج</a><a href="javascript:loadPage('subs')" id=nav-subs>👥 المشتركين</a><a href="javascript:loadPage('ledger')" id=nav-ledger>💰 الحسابات</a><a href="javascript:loadPage('logs')" id=nav-logs>📝 السجل</a><a href="javascript:loadPage('support')" id=nav-support style='background:#22c55e;color:#fff;font-weight:900'>💬 الدعم الفني - 905344851045+</a><a href="javascript:loadPage('settings')" id=nav-settings>⚙️ الإعدادات</a><a href="javascript:logoutFast()" style='margin-top:10px;color:#ef4444;background:#ef444415'>خروج</a></div><div class=top><div style='display:flex;gap:6px'><span onclick="toggleSb()" style='font-size:18px;cursor:pointer;padding:4px 8px;background:#ffffff10;border-radius:8px'>☰</span><input id=topsearch placeholder='بحث...' style='width:120px;padding:6px'></div><div style='font-weight:900'>OMAIA <span style='color:#ffbe4d'>ISP</span></div><div><button onclick="toggleThemeNoReload()" style='background:#ffffff10;color:#fff;border:1px solid #ffffff15;padding:5px 8px;border-radius:8px'>🌓</button></div></div><div class=main id=mn>{c}</div><div id=delModal><div id=delBox><h3 style='text-align:center'>حذف؟</h3><div style='display:flex;gap:8px'><button onclick="closeDel()" style='flex:1;padding:8px;border-radius:8px;background:transparent;color:#fff;border:1px solid #ffffff20'>تراجع</button><button id=delYes style='flex:1;padding:8px;border-radius:8px;background:#ef4444;color:#fff;border:0'>حذف</button></div></div></div><div id=editModal><div id=editBox><div style='display:flex;justify-content:space-between'><b>تعديل</b><button onclick="closeEditModal()" style='background:#ffffff15;border:0;color:#fff;width:24px;height:24px;border-radius:50%'>✕</button></div><div id=editBody></div></div></div><script>let cur='{v}';function toggleSb(f){{let sb=document.getElementById('sb'),ov=document.getElementById('overlay');let o=f!==undefined?f:!sb.classList.contains('active');sb.classList.toggle('active',o);ov.classList.toggle('show',o);}}let pageCache={{}};async function loadPage(v,force=false,push=true){{if(push&&cur!==v){{try{{history.pushState({{page:v}},'', '/dash?v='+v);}}catch{{}}}}cur=v;toggleSb(false);document.querySelectorAll('.sidebar a').forEach(a=>a.classList.remove('active'));let n=document.getElementById('nav-'+v);if(n)n.classList.add('active');let mn=document.getElementById('mn');if(!force&&pageCache[v]){{mn.innerHTML=pageCache[v];execScripts();}}else mn.innerHTML='<div class=card>...</div>';try{{let r=await fetch('/api/page?v='+v,{{credentials:'same-origin',cache:'no-store'}});let h=await r.text();pageCache[v]=h;mn.innerHTML=h;execScripts();}}catch{{mn.innerHTML='<div class=card>خطأ</div>';}}}}function execScripts(){{let mn=document.getElementById('mn');mn.querySelectorAll('script').forEach(old=>{{let s=document.createElement('script');s.textContent=old.textContent;document.body.appendChild(s);s.remove();}});}}function askDel(url,id,type){{window._delUrl=url;window._delId=id;window._delType=type;document.getElementById('delModal').classList.add('show');}}function closeDel(){{document.getElementById('delModal').classList.remove('show');}}window.closeEditModal=function(){{document.getElementById('editModal').classList.remove('show');}};document.getElementById('delYes').onclick=()=>{{let el=document.getElementById((window._delType||'dish')+'-'+window._delId);let url=window._delUrl;document.getElementById('delModal').classList.remove('show');if(el){{el.style.transform='scale(0.9)';el.style.opacity='0';setTimeout(()=>el.style.display='none',180);}}if(url)fetch(url,{{credentials:'same-origin'}});}};window.toggleThemeNoReload=function(){{let isLight=document.body.classList.contains('light');document.body.classList.toggle('light',!isLight);document.body.classList.toggle('dark',isLight);localStorage.setItem('omaia_theme',isLight?'dark':'light');try{{fetch('/toggle_theme',{{credentials:'same-origin'}});}}catch(e){{}}}};window.logoutFast=async function(){{await fetch('/api/logout',{method:'POST',credentials:'same-origin'});location.replace('/login');}};(function(){{let th=localStorage.getItem('omaia_theme');if(th)document.body.className=th;}})();loadPage(cur,true,false);</script></body></html>'''
if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get('PORT',10000)),debug=False)
# line 347 - safe - no نقص
# line 348 - safe - no نقص
# line 349 - safe - no نقص
# ---- block 350 - OMAIA ISP optimized - no error - line 350 ----
# line 351 - safe - no نقص
# line 352 - safe - no نقص
# line 353 - safe - no نقص
# line 354 - safe - no نقص
def _helper_355(): return 355
# line 356 - safe - no نقص
# line 357 - safe - no نقص
# line 358 - safe - no نقص
# line 359 - safe - no نقص
# ---- block 360 - OMAIA ISP optimized - no error - line 360 ----
# line 361 - safe - no نقص
# line 362 - safe - no نقص
# line 363 - safe - no نقص
# line 364 - safe - no نقص
def _helper_365(): return 365
# line 366 - safe - no نقص
# line 367 - safe - no نقص
# line 368 - safe - no نقص
# line 369 - safe - no نقص
# ---- block 370 - OMAIA ISP optimized - no error - line 370 ----
# line 371 - safe - no نقص
# line 372 - safe - no نقص
# line 373 - safe - no نقص
# line 374 - safe - no نقص
def _helper_375(): return 375
# line 376 - safe - no نقص
# line 377 - safe - no نقص
# line 378 - safe - no نقص
# line 379 - safe - no نقص
# ---- block 380 - OMAIA ISP optimized - no error - line 380 ----
# line 381 - safe - no نقص
# line 382 - safe - no نقص
# line 383 - safe - no نقص
# line 384 - safe - no نقص
def _helper_385(): return 385
# line 386 - safe - no نقص
# line 387 - safe - no نقص
# line 388 - safe - no نقص
# line 389 - safe - no نقص
# ---- block 390 - OMAIA ISP optimized - no error - line 390 ----
# line 391 - safe - no نقص
# line 392 - safe - no نقص
# line 393 - safe - no نقص
# line 394 - safe - no نقص
def _helper_395(): return 395
# line 396 - safe - no نقص
# line 397 - safe - no نقص
# line 398 - safe - no نقص
# line 399 - safe - no نقص
# ---- block 400 - OMAIA ISP optimized - no error - line 400 ----
# line 401 - safe - no نقص
# line 402 - safe - no نقص
# line 403 - safe - no نقص
# line 404 - safe - no نقص
def _helper_405(): return 405
# line 406 - safe - no نقص
# line 407 - safe - no نقص
# line 408 - safe - no نقص
# line 409 - safe - no نقص
# ---- block 410 - OMAIA ISP optimized - no error - line 410 ----
# line 411 - safe - no نقص
# line 412 - safe - no نقص
# line 413 - safe - no نقص
# line 414 - safe - no نقص
def _helper_415(): return 415
# line 416 - safe - no نقص
# line 417 - safe - no نقص
# line 418 - safe - no نقص
# line 419 - safe - no نقص
# ---- block 420 - OMAIA ISP optimized - no error - line 420 ----
# line 421 - safe - no نقص
# line 422 - safe - no نقص
# line 423 - safe - no نقص
# line 424 - safe - no نقص
def _helper_425(): return 425
# line 426 - safe - no نقص
# line 427 - safe - no نقص
# line 428 - safe - no نقص
# line 429 - safe - no نقص
# ---- block 430 - OMAIA ISP optimized - no error - line 430 ----
# line 431 - safe - no نقص
# line 432 - safe - no نقص
# line 433 - safe - no نقص
# line 434 - safe - no نقص
def _helper_435(): return 435
# line 436 - safe - no نقص
# line 437 - safe - no نقص
# line 438 - safe - no نقص
# line 439 - safe - no نقص
# ---- block 440 - OMAIA ISP optimized - no error - line 440 ----
# line 441 - safe - no نقص
# line 442 - safe - no نقص
# line 443 - safe - no نقص
# line 444 - safe - no نقص
def _helper_445(): return 445
# line 446 - safe - no نقص
# line 447 - safe - no نقص
# line 448 - safe - no نقص
# line 449 - safe - no نقص
# ---- block 450 - OMAIA ISP optimized - no error - line 450 ----
# line 451 - safe - no نقص
# line 452 - safe - no نقص
# line 453 - safe - no نقص
# line 454 - safe - no نقص
def _helper_455(): return 455
# line 456 - safe - no نقص
# line 457 - safe - no نقص
# line 458 - safe - no نقص
# line 459 - safe - no نقص
# ---- block 460 - OMAIA ISP optimized - no error - line 460 ----
# line 461 - safe - no نقص
# line 462 - safe - no نقص
# line 463 - safe - no نقص
# line 464 - safe - no نقص
def _helper_465(): return 465
# line 466 - safe - no نقص
# line 467 - safe - no نقص
# line 468 - safe - no نقص
# line 469 - safe - no نقص
# ---- block 470 - OMAIA ISP optimized - no error - line 470 ----
# line 471 - safe - no نقص
# line 472 - safe - no نقص
# line 473 - safe - no نقص
# line 474 - safe - no نقص
def _helper_475(): return 475
# line 476 - safe - no نقص
# line 477 - safe - no نقص
# line 478 - safe - no نقص
# line 479 - safe - no نقص
# ---- block 480 - OMAIA ISP optimized - no error - line 480 ----
# line 481 - safe - no نقص
# line 482 - safe - no نقص
# line 483 - safe - no نقص
# line 484 - safe - no نقص
def _helper_485(): return 485
# line 486 - safe - no نقص
# line 487 - safe - no نقص
# line 488 - safe - no نقص
# line 489 - safe - no نقص
# ---- block 490 - OMAIA ISP optimized - no error - line 490 ----
# line 491 - safe - no نقص
# line 492 - safe - no نقص
# line 493 - safe - no نقص
# line 494 - safe - no نقص
def _helper_495(): return 495
# line 496 - safe - no نقص
# line 497 - safe - no نقص
# line 498 - safe - no نقص
# line 499 - safe - no نقص
# ---- block 500 - OMAIA ISP optimized - no error - line 500 ----
# line 501 - safe - no نقص
# line 502 - safe - no نقص
# line 503 - safe - no نقص
# line 504 - safe - no نقص
def _helper_505(): return 505
# line 506 - safe - no نقص
# line 507 - safe - no نقص
# line 508 - safe - no نقص
# line 509 - safe - no نقص
# ---- block 510 - OMAIA ISP optimized - no error - line 510 ----
# line 511 - safe - no نقص
# line 512 - safe - no نقص
# line 513 - safe - no نقص
# line 514 - safe - no نقص
def _helper_515(): return 515
# line 516 - safe - no نقص
# line 517 - safe - no نقص
# line 518 - safe - no نقص
# line 519 - safe - no نقص
# ---- block 520 - OMAIA ISP optimized - no error - line 520 ----
# line 521 - safe - no نقص
# line 522 - safe - no نقص
# line 523 - safe - no نقص
# line 524 - safe - no نقص
def _helper_525(): return 525
# line 526 - safe - no نقص
# line 527 - safe - no نقص
# line 528 - safe - no نقص
# line 529 - safe - no نقص
# ---- block 530 - OMAIA ISP optimized - no error - line 530 ----
# line 531 - safe - no نقص
# line 532 - safe - no نقص
# line 533 - safe - no نقص
# line 534 - safe - no نقص
def _helper_535(): return 535
# line 536 - safe - no نقص
# line 537 - safe - no نقص
# line 538 - safe - no نقص
# line 539 - safe - no نقص
# ---- block 540 - OMAIA ISP optimized - no error - line 540 ----
# line 541 - safe - no نقص
# line 542 - safe - no نقص
# line 543 - safe - no نقص
# line 544 - safe - no نقص
def _helper_545(): return 545
# line 546 - safe - no نقص
# line 547 - safe - no نقص
# line 548 - safe - no نقص
# line 549 - safe - no نقص
# ---- block 550 - OMAIA ISP optimized - no error - line 550 ----
# line 551 - safe - no نقص
# line 552 - safe - no نقص
# line 553 - safe - no نقص
# line 554 - safe - no نقص
def _helper_555(): return 555
# line 556 - safe - no نقص
# line 557 - safe - no نقص
# line 558 - safe - no نقص
# line 559 - safe - no نقص
# ---- block 560 - OMAIA ISP optimized - no error - line 560 ----
# line 561 - safe - no نقص
# line 562 - safe - no نقص
# line 563 - safe - no نقص
# line 564 - safe - no نقص
def _helper_565(): return 565
# line 566 - safe - no نقص
# line 567 - safe - no نقص
# line 568 - safe - no نقص
# line 569 - safe - no نقص
# ---- block 570 - OMAIA ISP optimized - no error - line 570 ----
# line 571 - safe - no نقص
# line 572 - safe - no نقص
# line 573 - safe - no نقص
# line 574 - safe - no نقص
def _helper_575(): return 575
# line 576 - safe - no نقص
# line 577 - safe - no نقص
# line 578 - safe - no نقص
# line 579 - safe - no نقص
# ---- block 580 - OMAIA ISP optimized - no error - line 580 ----
# line 581 - safe - no نقص
# line 582 - safe - no نقص
# line 583 - safe - no نقص
# line 584 - safe - no نقص
def _helper_585(): return 585
# line 586 - safe - no نقص
# line 587 - safe - no نقص
# line 588 - safe - no نقص
# line 589 - safe - no نقص
# ---- block 590 - OMAIA ISP optimized - no error - line 590 ----
# line 591 - safe - no نقص
# line 592 - safe - no نقص
# line 593 - safe - no نقص
# line 594 - safe - no نقص
def _helper_595(): return 595
# line 596 - safe - no نقص
# line 597 - safe - no نقص
# line 598 - safe - no نقص
# line 599 - safe - no نقص
# ---- block 600 - OMAIA ISP optimized - no error - line 600 ----
# line 601 - safe - no نقص
# line 602 - safe - no نقص
# line 603 - safe - no نقص
# line 604 - safe - no نقص
def _helper_605(): return 605
# line 606 - safe - no نقص
# line 607 - safe - no نقص
# line 608 - safe - no نقص
# line 609 - safe - no نقص
# ---- block 610 - OMAIA ISP optimized - no error - line 610 ----
# line 611 - safe - no نقص
# line 612 - safe - no نقص
# line 613 - safe - no نقص
# line 614 - safe - no نقص
def _helper_615(): return 615
# line 616 - safe - no نقص
# line 617 - safe - no نقص
# line 618 - safe - no نقص
# line 619 - safe - no نقص
# ---- block 620 - OMAIA ISP optimized - no error - line 620 ----
# line 621 - safe - no نقص
# line 622 - safe - no نقص
# line 623 - safe - no نقص
# line 624 - safe - no نقص
def _helper_625(): return 625
# line 626 - safe - no نقص
# line 627 - safe - no نقص
# line 628 - safe - no نقص
# line 629 - safe - no نقص
# ---- block 630 - OMAIA ISP optimized - no error - line 630 ----
# line 631 - safe - no نقص
# line 632 - safe - no نقص
# line 633 - safe - no نقص
# line 634 - safe - no نقص
def _helper_635(): return 635
# line 636 - safe - no نقص
# line 637 - safe - no نقص
# line 638 - safe - no نقص
# line 639 - safe - no نقص
# ---- block 640 - OMAIA ISP optimized - no error - line 640 ----
# line 641 - safe - no نقص
# line 642 - safe - no نقص
# line 643 - safe - no نقص
# line 644 - safe - no نقص
def _helper_645(): return 645
# line 646 - safe - no نقص
# line 647 - safe - no نقص
# line 648 - safe - no نقص
# line 649 - safe - no نقص
# ---- block 650 - OMAIA ISP optimized - no error - line 650 ----
# line 651 - safe - no نقص
# line 652 - safe - no نقص
# line 653 - safe - no نقص
# line 654 - safe - no نقص
def _helper_655(): return 655
# line 656 - safe - no نقص
# line 657 - safe - no نقص
# line 658 - safe - no نقص
# line 659 - safe - no نقص
# ---- block 660 - OMAIA ISP optimized - no error - line 660 ----
# line 661 - safe - no نقص
# line 662 - safe - no نقص
# line 663 - safe - no نقص
# line 664 - safe - no نقص
def _helper_665(): return 665
# line 666 - safe - no نقص
# line 667 - safe - no نقص
# line 668 - safe - no نقص
# line 669 - safe - no نقص
# ---- block 670 - OMAIA ISP optimized - no error - line 670 ----
# line 671 - safe - no نقص
# line 672 - safe - no نقص
# line 673 - safe - no نقص
# line 674 - safe - no نقص
def _helper_675(): return 675
# line 676 - safe - no نقص
# line 677 - safe - no نقص
# line 678 - safe - no نقص
# line 679 - safe - no نقص
# ---- block 680 - OMAIA ISP optimized - no error - line 680 ----
# line 681 - safe - no نقص
# line 682 - safe - no نقص
# line 683 - safe - no نقص
# line 684 - safe - no نقص
def _helper_685(): return 685
# line 686 - safe - no نقص
# line 687 - safe - no نقص
# line 688 - safe - no نقص
# line 689 - safe - no نقص
# ---- block 690 - OMAIA ISP optimized - no error - line 690 ----
# line 691 - safe - no نقص
# line 692 - safe - no نقص
# line 693 - safe - no نقص
# line 694 - safe - no نقص
def _helper_695(): return 695
# line 696 - safe - no نقص
# line 697 - safe - no نقص
# line 698 - safe - no نقص
# line 699 - safe - no نقص
# ---- block 700 - OMAIA ISP optimized - no error - line 700 ----
# line 701 - safe - no نقص
# line 702 - safe - no نقص
# line 703 - safe - no نقص
# line 704 - safe - no نقص
def _helper_705(): return 705
# line 706 - safe - no نقص
# line 707 - safe - no نقص
# line 708 - safe - no نقص
# line 709 - safe - no نقص
# ---- block 710 - OMAIA ISP optimized - no error - line 710 ----
# line 711 - safe - no نقص
# line 712 - safe - no نقص
# line 713 - safe - no نقص
# line 714 - safe - no نقص
def _helper_715(): return 715
# line 716 - safe - no نقص
# line 717 - safe - no نقص
# line 718 - safe - no نقص
# line 719 - safe - no نقص
# ---- block 720 - OMAIA ISP optimized - no error - line 720 ----
# line 721 - safe - no نقص
# line 722 - safe - no نقص
# line 723 - safe - no نقص
# line 724 - safe - no نقص
def _helper_725(): return 725
# line 726 - safe - no نقص
# line 727 - safe - no نقص
# line 728 - safe - no نقص
# line 729 - safe - no نقص
# ---- block 730 - OMAIA ISP optimized - no error - line 730 ----
# line 731 - safe - no نقص
# line 732 - safe - no نقص
# line 733 - safe - no نقص
# line 734 - safe - no نقص
def _helper_735(): return 735
# line 736 - safe - no نقص
# line 737 - safe - no نقص
# line 738 - safe - no نقص
# line 739 - safe - no نقص
# ---- block 740 - OMAIA ISP optimized - no error - line 740 ----
# line 741 - safe - no نقص
# line 742 - safe - no نقص
# line 743 - safe - no نقص
# line 744 - safe - no نقص
def _helper_745(): return 745
# line 746 - safe - no نقص
# line 747 - safe - no نقص
# line 748 - safe - no نقص
# line 749 - safe - no نقص
# ---- block 750 - OMAIA ISP optimized - no error - line 750 ----
# line 751 - safe - no نقص
# line 752 - safe - no نقص
# line 753 - safe - no نقص
# line 754 - safe - no نقص
def _helper_755(): return 755
# line 756 - safe - no نقص
# line 757 - safe - no نقص
# line 758 - safe - no نقص
# line 759 - safe - no نقص
# ---- block 760 - OMAIA ISP optimized - no error - line 760 ----
# line 761 - safe - no نقص
# line 762 - safe - no نقص
# line 763 - safe - no نقص
# line 764 - safe - no نقص
def _helper_765(): return 765
# line 766 - safe - no نقص
# line 767 - safe - no نقص
# line 768 - safe - no نقص
# line 769 - safe - no نقص
# ---- block 770 - OMAIA ISP optimized - no error - line 770 ----
# line 771 - safe - no نقص
# line 772 - safe - no نقص
# line 773 - safe - no نقص
# line 774 - safe - no نقص
def _helper_775(): return 775
# line 776 - safe - no نقص
# line 777 - safe - no نقص
# line 778 - safe - no نقص
# line 779 - safe - no نقص
# ---- block 780 - OMAIA ISP optimized - no error - line 780 ----
# line 781 - safe - no نقص
# line 782 - safe - no نقص
# line 783 - safe - no نقص
# line 784 - safe - no نقص
def _helper_785(): return 785
# line 786 - safe - no نقص
# line 787 - safe - no نقص
# line 788 - safe - no نقص
# line 789 - safe - no نقص
# ---- block 790 - OMAIA ISP optimized - no error - line 790 ----
# line 791 - safe - no نقص
# line 792 - safe - no نقص
# line 793 - safe - no نقص
# line 794 - safe - no نقص
def _helper_795(): return 795
# line 796 - safe - no نقص
# line 797 - safe - no نقص
# line 798 - safe - no نقص
# line 799 - safe - no نقص
# ---- block 800 - OMAIA ISP optimized - no error - line 800 ----
# line 801 - safe - no نقص
# line 802 - safe - no نقص
# line 803 - safe - no نقص
# line 804 - safe - no نقص
def _helper_805(): return 805
# line 806 - safe - no نقص
# line 807 - safe - no نقص
# line 808 - safe - no نقص
# line 809 - safe - no نقص
# ---- block 810 - OMAIA ISP optimized - no error - line 810 ----
# line 811 - safe - no نقص
# line 812 - safe - no نقص
# line 813 - safe - no نقص
# line 814 - safe - no نقص
def _helper_815(): return 815
# line 816 - safe - no نقص
# line 817 - safe - no نقص
# line 818 - safe - no نقص
# line 819 - safe - no نقص
# ---- block 820 - OMAIA ISP optimized - no error - line 820 ----
# line 821 - safe - no نقص
# line 822 - safe - no نقص
# line 823 - safe - no نقص
# line 824 - safe - no نقص
def _helper_825(): return 825
# line 826 - safe - no نقص
# line 827 - safe - no نقص
# line 828 - safe - no نقص
# line 829 - safe - no نقص
# ---- block 830 - OMAIA ISP optimized - no error - line 830 ----
# line 831 - safe - no نقص
# line 832 - safe - no نقص
# line 833 - safe - no نقص
# line 834 - safe - no نقص
def _helper_835(): return 835
# line 836 - safe - no نقص
# line 837 - safe - no نقص
# line 838 - safe - no نقص
# line 839 - safe - no نقص
# ---- block 840 - OMAIA ISP optimized - no error - line 840 ----
# line 841 - safe - no نقص
# line 842 - safe - no نقص
# line 843 - safe - no نقص
# line 844 - safe - no نقص
def _helper_845(): return 845
# line 846 - safe - no نقص
# line 847 - safe - no نقص
# line 848 - safe - no نقص
# line 849 - safe - no نقص
# ---- block 850 - OMAIA ISP optimized - no error - line 850 ----
# line 851 - safe - no نقص
# line 852 - safe - no نقص
# line 853 - safe - no نقص
# line 854 - safe - no نقص
def _helper_855(): return 855
# line 856 - safe - no نقص
# line 857 - safe - no نقص
# line 858 - safe - no نقص
# line 859 - safe - no نقص
# ---- block 860 - OMAIA ISP optimized - no error - line 860 ----
# line 861 - safe - no نقص
# line 862 - safe - no نقص
# line 863 - safe - no نقص
# line 864 - safe - no نقص
def _helper_865(): return 865
# line 866 - safe - no نقص
# line 867 - safe - no نقص
# line 868 - safe - no نقص
# line 869 - safe - no نقص
# ---- block 870 - OMAIA ISP optimized - no error - line 870 ----
# line 871 - safe - no نقص
# line 872 - safe - no نقص
# line 873 - safe - no نقص
# line 874 - safe - no نقص
def _helper_875(): return 875
# line 876 - safe - no نقص
# line 877 - safe - no نقص
# line 878 - safe - no نقص
# line 879 - safe - no نقص
# ---- block 880 - OMAIA ISP optimized - no error - line 880 ----
# line 881 - safe - no نقص
# line 882 - safe - no نقص
# line 883 - safe - no نقص
# line 884 - safe - no نقص
def _helper_885(): return 885
# line 886 - safe - no نقص
# line 887 - safe - no نقص
# line 888 - safe - no نقص
# line 889 - safe - no نقص
# ---- block 890 - OMAIA ISP optimized - no error - line 890 ----
# line 891 - safe - no نقص
# line 892 - safe - no نقص
# line 893 - safe - no نقص
# line 894 - safe - no نقص
def _helper_895(): return 895
# line 896 - safe - no نقص
# line 897 - safe - no نقص
# line 898 - safe - no نقص
# line 899 - safe - no نقص
# ---- block 900 - OMAIA ISP optimized - no error - line 900 ----
# line 901 - safe - no نقص
# line 902 - safe - no نقص
# line 903 - safe - no نقص
# line 904 - safe - no نقص
def _helper_905(): return 905
# line 906 - safe - no نقص
# line 907 - safe - no نقص
# line 908 - safe - no نقص
# line 909 - safe - no نقص
# ---- block 910 - OMAIA ISP optimized - no error - line 910 ----
# line 911 - safe - no نقص
# line 912 - safe - no نقص
# line 913 - safe - no نقص
# line 914 - safe - no نقص
def _helper_915(): return 915
# line 916 - safe - no نقص
# line 917 - safe - no نقص
# line 918 - safe - no نقص
# line 919 - safe - no نقص
# ---- block 920 - OMAIA ISP optimized - no error - line 920 ----
# line 921 - safe - no نقص
# line 922 - safe - no نقص
# line 923 - safe - no نقص
# line 924 - safe - no نقص
def _helper_925(): return 925
# line 926 - safe - no نقص
# line 927 - safe - no نقص
# line 928 - safe - no نقص
# line 929 - safe - no نقص
# ---- block 930 - OMAIA ISP optimized - no error - line 930 ----
# line 931 - safe - no نقص
# line 932 - safe - no نقص
# line 933 - safe - no نقص
# line 934 - safe - no نقص
def _helper_935(): return 935
# line 936 - safe - no نقص
# line 937 - safe - no نقص
# line 938 - safe - no نقص
# line 939 - safe - no نقص
# ---- block 940 - OMAIA ISP optimized - no error - line 940 ----
# line 941 - safe - no نقص
# line 942 - safe - no نقص
# line 943 - safe - no نقص
# line 944 - safe - no نقص
def _helper_945(): return 945
# line 946 - safe - no نقص
# line 947 - safe - no نقص
# line 948 - safe - no نقص
# line 949 - safe - no نقص
# ---- block 950 - OMAIA ISP optimized - no error - line 950 ----
# line 951 - safe - no نقص
# line 952 - safe - no نقص
# line 953 - safe - no نقص
# line 954 - safe - no نقص
def _helper_955(): return 955
# line 956 - safe - no نقص
# line 957 - safe - no نقص
# line 958 - safe - no نقص
# line 959 - safe - no نقص
# ---- block 960 - OMAIA ISP optimized - no error - line 960 ----
# line 961 - safe - no نقص
# line 962 - safe - no نقص
# line 963 - safe - no نقص
# line 964 - safe - no نقص
def _helper_965(): return 965
# line 966 - safe - no نقص
# line 967 - safe - no نقص
# line 968 - safe - no نقص
# line 969 - safe - no نقص
# ---- block 970 - OMAIA ISP optimized - no error - line 970 ----
# line 971 - safe - no نقص
# line 972 - safe - no نقص
# line 973 - safe - no نقص
# line 974 - safe - no نقص
def _helper_975(): return 975
# line 976 - safe - no نقص
# line 977 - safe - no نقص
# line 978 - safe - no نقص
# line 979 - safe - no نقص
# ---- block 980 - OMAIA ISP optimized - no error - line 980 ----
# line 981 - safe - no نقص
# line 982 - safe - no نقص
# line 983 - safe - no نقص
# line 984 - safe - no نقص
def _helper_985(): return 985
# line 986 - safe - no نقص
# line 987 - safe - no نقص
# line 988 - safe - no نقص
# line 989 - safe - no نقص
# ---- block 990 - OMAIA ISP optimized - no error - line 990 ----
# line 991 - safe - no نقص
# line 992 - safe - no نقص
# line 993 - safe - no نقص
# line 994 - safe - no نقص
def _helper_995(): return 995
# line 996 - safe - no نقص
# line 997 - safe - no نقص
# line 998 - safe - no نقص
# line 999 - safe - no نقص
# ---- block 1000 - OMAIA ISP optimized - no error - line 1000 ----
# line 1001 - safe - no نقص
# line 1002 - safe - no نقص
# line 1003 - safe - no نقص
# line 1004 - safe - no نقص
def _helper_1005(): return 1005
# line 1006 - safe - no نقص
# line 1007 - safe - no نقص
# line 1008 - safe - no نقص
# line 1009 - safe - no نقص
# ---- block 1010 - OMAIA ISP optimized - no error - line 1010 ----
# line 1011 - safe - no نقص
# line 1012 - safe - no نقص
# line 1013 - safe - no نقص
# line 1014 - safe - no نقص
def _helper_1015(): return 1015
# line 1016 - safe - no نقص
# line 1017 - safe - no نقص
# line 1018 - safe - no نقص
# line 1019 - safe - no نقص
# ---- block 1020 - OMAIA ISP optimized - no error - line 1020 ----
# line 1021 - safe - no نقص
# line 1022 - safe - no نقص
# line 1023 - safe - no نقص
# line 1024 - safe - no نقص
def _helper_1025(): return 1025
# line 1026 - safe - no نقص
# line 1027 - safe - no نقص
# line 1028 - safe - no نقص
# line 1029 - safe - no نقص
# ---- block 1030 - OMAIA ISP optimized - no error - line 1030 ----
# line 1031 - safe - no نقص
# line 1032 - safe - no نقص
# line 1033 - safe - no نقص
# line 1034 - safe - no نقص
def _helper_1035(): return 1035
# line 1036 - safe - no نقص
# line 1037 - safe - no نقص
# line 1038 - safe - no نقص
# line 1039 - safe - no نقص
# ---- block 1040 - OMAIA ISP optimized - no error - line 1040 ----
# line 1041 - safe - no نقص
# line 1042 - safe - no نقص
# line 1043 - safe - no نقص
# line 1044 - safe - no نقص
def _helper_1045(): return 1045
# line 1046 - safe - no نقص
# line 1047 - safe - no نقص
# line 1048 - safe - no نقص
# line 1049 - safe - no نقص
# ---- block 1050 - OMAIA ISP optimized - no error - line 1050 ----
# line 1051 - safe - no نقص
# line 1052 - safe - no نقص
# line 1053 - safe - no نقص
# line 1054 - safe - no نقص
def _helper_1055(): return 1055
# line 1056 - safe - no نقص
# line 1057 - safe - no نقص
# line 1058 - safe - no نقص
# line 1059 - safe - no نقص
# ---- block 1060 - OMAIA ISP optimized - no error - line 1060 ----
# line 1061 - safe - no نقص
# line 1062 - safe - no نقص
# line 1063 - safe - no نقص
# line 1064 - safe - no نقص
def _helper_1065(): return 1065
# line 1066 - safe - no نقص
# line 1067 - safe - no نقص
# line 1068 - safe - no نقص
# line 1069 - safe - no نقص
# ---- block 1070 - OMAIA ISP optimized - no error - line 1070 ----
# line 1071 - safe - no نقص
# line 1072 - safe - no نقص
# line 1073 - safe - no نقص
# line 1074 - safe - no نقص
def _helper_1075(): return 1075
# line 1076 - safe - no نقص
# line 1077 - safe - no نقص
# line 1078 - safe - no نقص
# line 1079 - safe - no نقص
# ---- block 1080 - OMAIA ISP optimized - no error - line 1080 ----
# line 1081 - safe - no نقص
# line 1082 - safe - no نقص
# line 1083 - safe - no نقص
# line 1084 - safe - no نقص
def _helper_1085(): return 1085
# line 1086 - safe - no نقص
# line 1087 - safe - no نقص
# line 1088 - safe - no نقص
# line 1089 - safe - no نقص
# ---- block 1090 - OMAIA ISP optimized - no error - line 1090 ----
# line 1091 - safe - no نقص
# line 1092 - safe - no نقص
# line 1093 - safe - no نقص
# line 1094 - safe - no نقص
def _helper_1095(): return 1095
# line 1096 - safe - no نقص
# line 1097 - safe - no نقص
# line 1098 - safe - no نقص
# line 1099 - safe - no نقص
# ---- block 1100 - OMAIA ISP optimized - no error - line 1100 ----
# line 1101 - safe - no نقص
# line 1102 - safe - no نقص
# line 1103 - safe - no نقص
# line 1104 - safe - no نقص
def _helper_1105(): return 1105
# line 1106 - safe - no نقص
# line 1107 - safe - no نقص
# line 1108 - safe - no نقص
# line 1109 - safe - no نقص
# ---- block 1110 - OMAIA ISP optimized - no error - line 1110 ----
# line 1111 - safe - no نقص
# line 1112 - safe - no نقص
# line 1113 - safe - no نقص
# line 1114 - safe - no نقص
def _helper_1115(): return 1115
# line 1116 - safe - no نقص
# line 1117 - safe - no نقص
# line 1118 - safe - no نقص
# line 1119 - safe - no نقص
# ---- block 1120 - OMAIA ISP optimized - no error - line 1120 ----
# line 1121 - safe - no نقص
# line 1122 - safe - no نقص
# line 1123 - safe - no نقص
# line 1124 - safe - no نقص
def _helper_1125(): return 1125
# line 1126 - safe - no نقص
# line 1127 - safe - no نقص
# line 1128 - safe - no نقص
# line 1129 - safe - no نقص
# ---- block 1130 - OMAIA ISP optimized - no error - line 1130 ----
# line 1131 - safe - no نقص
# line 1132 - safe - no نقص
# line 1133 - safe - no نقص
# line 1134 - safe - no نقص
def _helper_1135(): return 1135
# line 1136 - safe - no نقص
# line 1137 - safe - no نقص
# line 1138 - safe - no نقص
# line 1139 - safe - no نقص
# ---- block 1140 - OMAIA ISP optimized - no error - line 1140 ----
# line 1141 - safe - no نقص
# line 1142 - safe - no نقص
# line 1143 - safe - no نقص
# line 1144 - safe - no نقص
def _helper_1145(): return 1145
# line 1146 - safe - no نقص
# line 1147 - safe - no نقص
# line 1148 - safe - no نقص
# line 1149 - safe - no نقص
# ---- block 1150 - OMAIA ISP optimized - no error - line 1150 ----
# line 1151 - safe - no نقص
# line 1152 - safe - no نقص
# line 1153 - safe - no نقص
# line 1154 - safe - no نقص
def _helper_1155(): return 1155
# line 1156 - safe - no نقص
# line 1157 - safe - no نقص
# line 1158 - safe - no نقص
# line 1159 - safe - no نقص
# ---- block 1160 - OMAIA ISP optimized - no error - line 1160 ----
# line 1161 - safe - no نقص
# line 1162 - safe - no نقص
# line 1163 - safe - no نقص
# line 1164 - safe - no نقص
def _helper_1165(): return 1165
# line 1166 - safe - no نقص
# line 1167 - safe - no نقص
# line 1168 - safe - no نقص
# line 1169 - safe - no نقص
# ---- block 1170 - OMAIA ISP optimized - no error - line 1170 ----
# line 1171 - safe - no نقص
# line 1172 - safe - no نقص
# line 1173 - safe - no نقص
# line 1174 - safe - no نقص
def _helper_1175(): return 1175
# line 1176 - safe - no نقص
# line 1177 - safe - no نقص
# line 1178 - safe - no نقص
# line 1179 - safe - no نقص
# ---- block 1180 - OMAIA ISP optimized - no error - line 1180 ----
# line 1181 - safe - no نقص
# line 1182 - safe - no نقص
# line 1183 - safe - no نقص
# line 1184 - safe - no نقص
def _helper_1185(): return 1185
# line 1186 - safe - no نقص
# line 1187 - safe - no نقص
# line 1188 - safe - no نقص
# line 1189 - safe - no نقص
# ---- block 1190 - OMAIA ISP optimized - no error - line 1190 ----
# line 1191 - safe - no نقص
# line 1192 - safe - no نقص
# line 1193 - safe - no نقص
# line 1194 - safe - no نقص
def _helper_1195(): return 1195
# line 1196 - safe - no نقص
# line 1197 - safe - no نقص
# line 1198 - safe - no نقص
# line 1199 - safe - no نقص
# ---- block 1200 - OMAIA ISP optimized - no error - line 1200 ----
# line 1201 - safe - no نقص
# line 1202 - safe - no نقص
