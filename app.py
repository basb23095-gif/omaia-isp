from flask import Flask, request, redirect, session, jsonify, Response
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, html, ipaddress, io, csv, datetime, json
import psycopg2, psycopg2.extras
import sqlite3

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "omia-sec-2026-CHANGE-ME-STRONG")
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(days=30)

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_PG = bool(DATABASE_URL)

def esc(s): return html.escape(str(s or ''), quote=True)

def get_conn():
    if USE_PG:
        return psycopg2.connect(DATABASE_URL, sslmode='require', connect_timeout=2)
    try:
        c = sqlite3.connect("omia.db", check_same_thread=False, timeout=5)
        c.row_factory = sqlite3.Row
        return c
    except:
        c = sqlite3.connect(":memory:", check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c

def qall(q, a=()):
    conn=None
    try:
        conn=get_conn()
        if USE_PG:
            cur=conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(q.replace("?", "%s"), a)
            rs=[dict(r) for r in cur.fetchall()]
            cur.close(); conn.close()
            return rs
        rs=[dict(r) for r in conn.execute(q, a).fetchall()]
        conn.close()
        return rs
    except Exception as e:
        print(f"[DB qall] {e}")
        try:
            if conn: conn.close()
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
            cur.execute(q.replace("?", "%s"), a)
            conn.commit(); cur.close(); conn.close()
        else:
            conn.execute(q,a); conn.commit(); conn.close()
        return True
    except Exception as e:
        print(f"[DB qexec] {e} | {q}")
        try:
            if conn: conn.close()
        except: pass
        return False

_dish_cache={"t":None,"ts":0}
def get_dish_table():
    import time
    now=time.time()
    if _dish_cache["t"] and now-_dish_cache["ts"]<120:
        return _dish_cache["t"]
    if not USE_PG: return "dish_ips"
    try:
        rows=qall("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name IN ('ips','dish_ips')")
        names=[r.get('table_name') for r in rows]
        tbl="ips" if 'ips' in names else "dish_ips"
        _dish_cache["t"]=tbl; _dish_cache["ts"]=now
        return tbl
    except: return "dish_ips"

def ensure_column(table,column,coltype_pg,coltype_sqlite=None):
    if coltype_sqlite is None: coltype_sqlite=coltype_pg
    if USE_PG:
        qexec(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {coltype_pg}")
    else:
        try:
            conn=get_conn(); cur=conn.cursor()
            cur.execute(f"PRAGMA table_info({table})")
            cols=[row[1] for row in cur.fetchall()]; conn.close()
            if column not in cols:
                qexec(f"ALTER TABLE {table} ADD COLUMN {column} {coltype_sqlite}")
        except: pass

def log_action(action, detail=""):
    try:
        phone=session.get('phone','system')
        now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)",(phone,action,detail,now))
    except: pass

def init():
    if USE_PG:
        tables=[
            "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,username TEXT)",
            "CREATE TABLE IF NOT EXISTS subs(id SERIAL PRIMARY KEY,name TEXT,phone TEXT,note TEXT)",
            "CREATE TABLE IF NOT EXISTS ledger(id SERIAL PRIMARY KEY,name TEXT,amount REAL,note TEXT,currency TEXT)",
            "CREATE TABLE IF NOT EXISTS dish_ips(id SERIAL PRIMARY KEY,ip TEXT,location TEXT,dish_name TEXT)",
            "CREATE TABLE IF NOT EXISTS towers(id SERIAL PRIMARY KEY,name TEXT,area TEXT,lat DOUBLE PRECISION,lng DOUBLE PRECISION)",
            "CREATE TABLE IF NOT EXISTS logs(id SERIAL PRIMARY KEY,user_phone TEXT,action TEXT,detail TEXT,time TEXT)",
            "CREATE TABLE IF NOT EXISTS notifications(id SERIAL PRIMARY KEY,title TEXT,msg TEXT,time TEXT,read INTEGER DEFAULT 0)",
            "CREATE TABLE IF NOT EXISTS ips(id SERIAL PRIMARY KEY, ip TEXT, location TEXT, dish_name TEXT, created_at TIMESTAMP DEFAULT NOW())"
        ]
    else:
        tables=[
            "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,username TEXT)",
            "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,note TEXT)",
            "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,amount REAL,note TEXT,currency TEXT)",
            "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,dish_name TEXT)",
            "CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,area TEXT,lat REAL,lng REAL)",
            "CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,user_phone TEXT,action TEXT,detail TEXT,time TEXT)",
            "CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,msg TEXT,time TEXT,read INTEGER DEFAULT 0)",
            "CREATE TABLE IF NOT EXISTS ips(id INTEGER PRIMARY KEY AUTOINCREMENT, ip TEXT, location TEXT, dish_name TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        ]
    for s in tables: qexec(s)
    ensure_column("towers","area","TEXT")
    ensure_column("towers","name","TEXT")
    ensure_column("users","username","TEXT")
    ensure_column("logs","time","TEXT")
    ensure_column("subs","note","TEXT")
    ensure_column("ledger","currency","TEXT")
    if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",('05344851045',generate_password_hash('admin2024'),'manager','admin'))
    if not qone("SELECT * FROM logs LIMIT 1"):
        qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)",('system','تشغيل النظام','OMAIA ISP - كامل بدون خريطة وبنج',datetime.datetime.now().strftime("%Y-%m-%d %H:%M")))
    if not qone("SELECT * FROM notifications LIMIT 1"):
        qexec("INSERT INTO notifications(title,msg,time,read) VALUES(?,?,?,?)",('✅ النظام جاهز','كلشي شغال - سجل + إشعارات + واتساب',datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),0))

init()

def login_required(f):
    @wraps(f)
    def w(*a,**kw):
        if not session.get('phone'): return redirect('/login')
        return f(*a,**kw)
    return w

def is_manager():
    u=qone("SELECT * FROM users WHERE phone=?",(session.get('phone') or '',))
    return (u.get('role') or '').lower()=='manager' if u else False

def role_required_manager(f):
    @wraps(f)
    def w(*a,**kw):
        if not is_manager(): return "ممنوع - مدير فقط",403
        return f(*a,**kw)
    return w

def is_valid_ip(ip):
    try: ipaddress.ip_address((ip or '').strip()); return True
    except: return False

@app.route('/fix_db')
def fix_db(): ensure_column("towers","area","TEXT"); return jsonify(ok=True, table=get_dish_table())

@app.route('/reset_admin')
def reset_admin():
    qexec("DELETE FROM users WHERE phone=?",('05344851045',))
    qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",('05344851045',generate_password_hash('admin2024'),'manager','admin'))
    return jsonify(ok=True)

@app.route('/health')
def health(): return jsonify(ok=True, pg=USE_PG, table=get_dish_table(), mode="complete-no-map-no-ping")

@app.route('/api/notifications')
@login_required
def api_noti():
    rows=qall("SELECT * FROM notifications ORDER BY id DESC LIMIT 20")
    unread=qone("SELECT COUNT(*) as c FROM notifications WHERE read=0")
    return jsonify(rows=rows, unread=(unread.get('c',0) if unread else 0))

@app.route('/api/notifications/read', methods=['POST'])
@login_required
def api_noti_read(): qexec("UPDATE notifications SET read=1"); return jsonify(ok=True)

@app.route('/api/login_public', methods=['POST'])
def api_login_public():
    uin=request.form.get('userin','').strip()
    pw=request.form.get('password','')
    u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
    if u and check_password_hash(u['password'], pw):
        session['phone']=u['phone']; session['username']=u.get('username') or u['phone']; session.permanent=True
        log_action("تسجيل دخول", uin)
        return jsonify(ok=True, role=u.get('role'))
    return jsonify(ok=False, msg='خطأ بالدخول'),401

@app.route('/api/export/<tbl>')
@login_required
def api_export(tbl):
    output=io.StringIO(); output.write('\ufeff'); w=csv.writer(output)
    dish_tbl=get_dish_table()
    if tbl=='dishes':
        rows=qall(f"SELECT * FROM {dish_tbl} ORDER BY id DESC")
        w.writerow(['ID','اسم الصحن','IP','الموقع'])
        for r in rows: w.writerow([r.get('id',''),r.get('dish_name',''),r.get('ip',''),r.get('location','')])
        fname='dishes.csv'
    elif tbl=='subs':
        rows=qall("SELECT * FROM subs ORDER BY id DESC")
        w.writerow(['ID','الاسم','رقم','ملاحظة'])
        for r in rows: w.writerow([r.get('id',''),r.get('name',''),r.get('phone',''),r.get('note','')])
        fname='subs.csv'
    elif tbl=='towers':
        rows=qall("SELECT * FROM towers ORDER BY id DESC")
        w.writerow(['ID','اسم البرج','المنطقة'])
        for r in rows: w.writerow([r.get('id',''),r.get('name',''),r.get('area','')])
        fname='towers.csv'
    elif tbl=='logs':
        rows=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 1000")
        w.writerow(['ID','المستخدم','العملية','التفاصيل','الوقت'])
        for r in rows: w.writerow([r.get('id',''),r.get('user_phone',''),r.get('action',''),r.get('detail',''),r.get('time','')])
        fname='logs.csv'
    elif tbl=='users':
        rows=qall("SELECT phone,username,role FROM users ORDER BY phone DESC")
        w.writerow(['رقم','يوزر','رتبة'])
        for r in rows: w.writerow([r.get('phone',''),r.get('username',''),r.get('role','')])
        fname='users.csv'
    else:
        rows=qall(f"SELECT * FROM {dish_tbl} ORDER BY id DESC")
        w.writerow(['ID','اسم','IP'])
        for r in rows: w.writerow([r.get('id',''),r.get('dish_name',''),r.get('ip','')])
        fname='export.csv'
    return Response(output.getvalue(), mimetype='text/csv; charset=utf-8', headers={'Content-Disposition': f'attachment; filename={fname}'})

@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login')
def login_page():
    return """<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<style>*{box-sizing:border-box;font-family:system-ui}body{margin:0;min-height:100vh;background:radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 55%, #070a1f 100%);display:flex;flex-direction:column;align-items:center;justify-content:center;color:#fff;padding:14px}
.card{background:linear-gradient(180deg, #222b45cc, #1a2035cc);backdrop-filter:blur(16px);border:1px solid #ffffff18;padding:26px;border-radius:22px;width:92%;max-width:400px;box-shadow:0 20px 60px #0008}
input{width:100%;padding:14px;margin:8px 0;background:#0f1424;border:1px solid #ffffff22;color:#fff;border-radius:14px;font-size:15px}
.btn{width:100%;padding:14px;border:0;border-radius:14px;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:900;font-size:17px;cursor:pointer;margin-top:10px}
.support-box{margin-top:18px;background:linear-gradient(135deg,#0f172a,#1e293b);border:1px solid #22c55e33;border-radius:16px;padding:14px;text-align:center;width:92%;max-width:400px}
.wa-btn{display:inline-flex;align-items:center;gap:8px;background:linear-gradient(90deg,#22c55e,#16a34a);color:#fff;padding:10px 18px;border-radius:12px;text-decoration:none;font-weight:800;margin:6px}
</style></head><body>
<div style='font-size:30px;font-weight:900;margin-bottom:12px'>OMAIA <span style='color:#ffbe4d'>ISP</span> <small style='color:#22c55e'>⚡</small></div>
<div class=card><form id=loginForm><input name=userin id=userin placeholder='📱 رقم / يوزر - admin' required autocomplete=username><input name=password id=password type=password placeholder='🔑 كلمة السر - admin2024' required autocomplete=current-password><label style='display:flex;gap:8px;font-size:13px;color:#aaa;margin:8px 0'><input type=checkbox id=savePass style='width:auto'> حفظ كلمة السر</label><button class=btn id=loginBtn>✨ دخول فوري</button><div id=msg style='text-align:center;margin-top:8px;color:#ff6b6b;font-size:13px'></div></form></div>
<div class=support-box><div style='font-weight:800;margin-bottom:8px;color:#ffbe4d'>🛠 الدعم الفني - واتساب</div><a href='https://wa.me/905344851045' target=_blank class=wa-btn>💬 واتساب: +90 534 485 10 45</a><div style='margin-top:8px'><a href='tel:+905344851045' style='color:#0ea5e9;text-decoration:none;font-size:13px'>📞 +90 534 485 10 45</a></div><div style='margin-top:10px;font-size:11px;color:#6b7280'>✅ بدون خريطة و بدون بنج - خفيف وسريع - كلشي شغال</div></div>
<script>
let u=document.getElementById('userin'), p=document.getElementById('password'), s=document.getElementById('savePass');
let su=localStorage.getItem('omaia_user'), sp=localStorage.getItem('omaia_pass');
if(su){u.value=su; if(sp){p.value=sp; s.checked=true;}}
document.getElementById('loginForm').addEventListener('submit',async e=>{
 e.preventDefault(); let btn=document.getElementById('loginBtn'), msg=document.getElementById('msg');
 if(btn.disabled) return; btn.textContent='⏳...'; btn.disabled=true;
 try{
  let fd=new FormData(e.target);
  let r=await fetch('/api/login_public',{method:'POST',body:fd,cache:'no-store'});
  let j=await r.json();
  if(j.ok){ if(s.checked){localStorage.setItem('omaia_user',u.value);localStorage.setItem('omaia_pass',p.value);} location.replace('/dash?v=home'); }
  else{ msg.textContent=j.msg||'خطأ'; btn.textContent='✨ دخول فوري'; btn.disabled=false; }
 }catch(err){ msg.textContent='خطأ شبكة'; btn.textContent='✨ دخول فوري'; btn.disabled=false; }
});
</script></body></html>"""

@app.route('/logout')
def lo(): session.clear(); return redirect('/login')
@app.route('/api/logout', methods=['POST'])
def api_logout(): session.clear(); return jsonify(ok=True)

@app.route('/dash')
@login_required
def dash(): return layout(page_content(request.args.get('v','home')), request.args.get('v','home'))

@app.route('/api/page')
@login_required
def ap(): return page_content(request.args.get('v','home'))

@app.route('/api/search')
@login_required
def api_search():
    q=request.args.get('q','').strip()
    if not q: return jsonify([])
    like="%"+q+"%"
    results=[]
    dish_tbl=get_dish_table()
    try:
        for r in qall(f"SELECT * FROM {dish_tbl} WHERE ip LIKE ? OR dish_name LIKE ? OR location LIKE ? ORDER BY id DESC LIMIT 15",(like,like,like)):
            results.append({"title": r.get('dish_name') or r.get('ip'), "sub": r.get('ip',''), "page": "dishes", "type": "dish"})
        for r in qall("SELECT * FROM towers WHERE name LIKE ? OR area LIKE ? ORDER BY id DESC LIMIT 10",(like,like)):
            results.append({"title": r.get('name',''), "sub": r.get('area',''), "page": "towers", "type": "tower"})
        for r in qall("SELECT * FROM subs WHERE name LIKE ? OR phone LIKE ? ORDER BY id DESC LIMIT 10",(like,like)):
            results.append({"title": r.get('name',''), "sub": r.get('phone',''), "page": "subs", "type": "sub"})
        for r in qall("SELECT * FROM users WHERE phone LIKE ? OR username LIKE ? LIMIT 5",(like,like)):
            results.append({"title": r.get('username') or r.get('phone',''), "sub": r.get('phone',''), "page": "settings", "type": "user"})
    except: pass
    return jsonify(results[:20])

@app.route('/add_dish', methods=['POST'])
@login_required
def add_dish():
    dish_tbl=get_dish_table()
    ip=request.form.get('ip','').strip()
    name=request.form.get('dish_name','').strip()
    loc=request.form.get('location','').strip()
    if not ip: return "IP مطلوب",400
    if not is_valid_ip(ip): return "IP غير صالح",400
    ex=qone(f"SELECT * FROM {dish_tbl} WHERE ip=?",(ip,))
    if ex:
        qexec(f"UPDATE {dish_tbl} SET dish_name=?,location=? WHERE ip=?",(name,loc,ip))
        log_action("تعديل صحن", f"{name} - {ip}")
        return "ok updated"
    qexec(f"INSERT INTO {dish_tbl}(ip,location,dish_name) VALUES(?,?,?)",(ip,loc,name))
    log_action("إضافة صحن", f"{name} - {ip}")
    qexec("INSERT INTO notifications(title,msg,time,read) VALUES(?,?,?,0)",(f"📡 صحن {name}",f"{ip} - {loc}",datetime.datetime.now().strftime("%Y-%m-%d %H:%M")))
    return "ok"

@app.route('/edit_dish/<int:i>', methods=['POST'])
@login_required
def edit_dish(i):
    if not is_manager(): return "ممنوع",403
    qexec(f"UPDATE {get_dish_table()} SET dish_name=?,ip=?,location=? WHERE id=?",(request.form.get('dish_name',''),request.form.get('ip',''),request.form.get('location',''),i))
    log_action("تعديل صحن", str(i))
    return "ok"

@app.route('/del_dish/<int:i>')
@login_required
def del_dish(i):
    if not is_manager(): return "ممنوع",403
    qexec(f"DELETE FROM {get_dish_table()} WHERE id=?",(i,))
    log_action("حذف صحن", str(i))
    return "ok"

@app.route('/add_tower', methods=['POST'])
@login_required
def add_tower():
    name=request.form.get('name','').strip()
    area=request.form.get('area','').strip()
    if not name: return "اسم مطلوب",400
    qexec("INSERT INTO towers(name,area) VALUES(?,?)",(name,area))
    log_action("إضافة برج", f"{name} - {area}")
    qexec("INSERT INTO notifications(title,msg,time,read) VALUES(?,?,?,0)",(f"🗼 برج {name}",area,datetime.datetime.now().strftime("%Y-%m-%d %H:%M")))
    return "ok"

@app.route('/edit_tower/<int:i>', methods=['POST'])
@login_required
def edit_tower(i):
    if not is_manager(): return "ممنوع",403
    qexec("UPDATE towers SET name=?,area=? WHERE id=?",(request.form.get('name',''),request.form.get('area',''),i))
    log_action("تعديل برج", str(i))
    return "ok"

@app.route('/del_tower/<int:i>')
@login_required
def del_tower(i):
    if not is_manager(): return "ممنوع",403
    qexec("DELETE FROM towers WHERE id=?",(i,))
    log_action("حذف برج", str(i))
    return "ok"

@app.route('/add_sub', methods=['POST'])
@login_required
def add_sub():
    name=request.form.get('name','').strip()
    phone=request.form.get('phone','').strip()
    note=request.form.get('note','').strip()
    if not name: return "اسم مطلوب",400
    qexec("INSERT INTO subs(name,phone,note) VALUES(?,?,?)",(name,phone,note))
    log_action("إضافة مشترك", name)
    return "ok"

@app.route('/edit_sub/<int:i>', methods=['POST'])
@login_required
def edit_sub(i):
    if not is_manager(): return "ممنوع",403
    qexec("UPDATE subs SET name=?,phone=?,note=? WHERE id=?",(request.form.get('name',''),request.form.get('phone',''),request.form.get('note',''),i))
    return "ok"

@app.route('/del_sub/<int:i>')
@login_required
def del_sub(i):
    if not is_manager(): return "ممنوع",403
    qexec("DELETE FROM subs WHERE id=?",(i,))
    return "ok"

@app.route('/add_ledger', methods=['POST'])
@login_required
def add_ledger():
    try: amt=float(request.form.get('amount') or 0)
    except: amt=0
    qexec("INSERT INTO ledger(name,amount,note,currency) VALUES(?,?,?,?)",(request.form.get('name',''),amt,request.form.get('note',''),request.form.get('currency','USD')))
    log_action("إضافة حساب", f"{request.form.get('name','')} - {amt}")
    return "ok"

@app.route('/edit_ledger/<int:i>', methods=['POST'])
@login_required
def edit_ledger(i):
    if not is_manager(): return "ممنوع",403
    try: amt=float(request.form.get('amount') or 0)
    except: amt=0
    qexec("UPDATE ledger SET name=?,amount=?,note=?,currency=? WHERE id=?",(request.form.get('name',''),amt,request.form.get('note',''),request.form.get('currency','USD'),i))
    return "ok"

@app.route('/del_ledger/<int:i>')
@login_required
def del_ledger(i):
    if not is_manager(): return "ممنوع",403
    qexec("DELETE FROM ledger WHERE id=?",(i,))
    return "ok"

@app.route('/add_user', methods=['POST'])
@login_required
@role_required_manager
def add_user():
    ph=request.form.get('phone','').strip() or request.form.get('user_field','').strip()
    if not ph: return "رقم مطلوب",400
    if qone("SELECT * FROM users WHERE phone=?",(ph,)): return "موجود مسبقاً",400
    qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",(ph,generate_password_hash(request.form.get('password','1234')),request.form.get('role','tech'),ph))
    log_action("إضافة يوزر", ph)
    return "ok"

@app.route('/edit_user', methods=['POST'])
@login_required
@role_required_manager
def edit_user():
    old=request.form.get('old_phone','').strip()
    new_ph=request.form.get('phone','').strip() or request.form.get('user_field','').strip()
    new_role=request.form.get('role','tech')
    new_pass=request.form.get('password','').strip()
    if not old: return "خطأ",400
    if old!=new_ph and qone("SELECT * FROM users WHERE phone=?",(new_ph,)): return "الرقم موجود",400
    if new_pass:
        qexec("UPDATE users SET phone=?,username=?,role=?,password=? WHERE phone=?",(new_ph,new_ph,new_role,generate_password_hash(new_pass),old))
    else:
        qexec("UPDATE users SET phone=?,username=?,role=? WHERE phone=?",(new_ph,new_ph,new_role,old))
    if session.get('phone')==old: session['phone']=new_ph
    return "ok"

@app.route('/del_user/<ph>')
@login_required
@role_required_manager
def del_user(ph):
    if ph=='05344851045': return "ممنوع حذف المدير",400
    qexec("DELETE FROM users WHERE phone=?",(ph,))
    return "ok"

@app.route('/change_pass', methods=['POST'])
@login_required
def change_pass():
    np=request.form.get('newpass','').strip()
    if not np: return "فارغة",400
    qexec("UPDATE users SET password=? WHERE phone=?",(generate_password_hash(np),session.get('phone')))
    log_action("تغيير كلمة سر", "")
    return "ok"

def page_content(v):
    dish_tbl=get_dish_table()
    if v=='home':
        ns=(qone("SELECT COUNT(*) as c FROM subs") or {}).get('c',0)
        nd=(qone(f"SELECT COUNT(*) as c FROM {dish_tbl}") or {}).get('c',0)
        nt=(qone("SELECT COUNT(*) as c FROM towers") or {}).get('c',0)
        nl=(qone("SELECT COUNT(*) as c FROM ledger") or {}).get('c',0)
        logs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 6")
        log_html="".join([f"<div style='display:flex;justify-content:space-between;padding:6px 8px;border-bottom:1px dashed #ffffff10;font-size:12px'><div><b style='color:#ffbe4d'>{esc(l.get('user_phone',''))}</b> {esc(l.get('action',''))} <small style='color:#aaa'>{esc(l.get('detail',''))}</small></div><small style='color:#666'>{esc(l.get('time',''))}</small></div>" for l in logs])
        return f'''<div style='max-width:900px;margin:0 auto'>
        <div style='display:grid;grid-template-columns:1fr 1fr;gap:10px'>
        <div class='card anim' onclick="loadPage('subs')" style='cursor:pointer;background:linear-gradient(135deg,#1e2a4a,#162040)'><div style='display:flex;justify-content:space-between'><div><h3 style='margin:0;color:#aab4d0;font-size:12px'>المشتركين</h3><h2 style='margin:4px 0 0;font-size:28px'>{ns}</h2></div><div style='font-size:28px'>👥</div></div></div>
        <div class='card anim' onclick="loadPage('dishes')" style='cursor:pointer;background:linear-gradient(135deg,#1e2f4a,#162840)'><div style='display:flex;justify-content:space-between'><div><h3 style='margin:0;color:#aab4d0;font-size:12px'>الصحون</h3><h2 style='margin:4px 0 0;font-size:28px'>{nd}</h2><small style='color:#22c55e'>بدون بنج</small></div><div style='font-size:28px'>📡</div></div></div>
        <div class='card anim' onclick="loadPage('towers')" style='cursor:pointer;background:linear-gradient(135deg,#2a1e4a,#201640)'><div style='display:flex;justify-content:space-between'><div><h3 style='margin:0;color:#aab4d0;font-size:12px'>الأبراج</h3><h2 style='margin:4px 0 0;font-size:28px'>{nt}</h2><small>بدون خريطة</small></div><div style='font-size:28px'>🗼</div></div></div>
        <div class='card anim' onclick="loadPage('ledger')" style='cursor:pointer;background:linear-gradient(135deg,#4a2a1e,#402016)'><div style='display:flex;justify-content:space-between'><div><h3 style='margin:0;color:#aab4d0;font-size:12px'>الحسابات</h3><h2 style='margin:4px 0 0;font-size:28px'>{nl}</h2></div><div style='font-size:28px'>📒</div></div></div>
        </div>
        <div class=card style='margin-top:10px'><div style='display:flex;justify-content:space-between;flex-wrap:wrap'><h4 style='margin:0'>📊 التقارير</h4><div style='display:flex;gap:6px'><a href='/api/export/dishes' class=btn-gold style='text-decoration:none;padding:6px 10px;font-size:12px;background:#22c55e;color:#fff'>📗 صحون Excel</a><a href='/api/export/logs' class=btn-gold style='text-decoration:none;padding:6px 10px;font-size:12px;background:#8b5cf6;color:#fff'>📜 سجل Excel</a></div></div></div>
        <div class=card><h4>📜 آخر النشاطات - السجل شغال ✅</h4>{log_html or 'لا يوجد'}<button class=btn-gold onclick="loadPage('logs')" style='width:100%;margin-top:8px'>عرض كل السجل</button></div>
        <div class=card style='text-align:center;background:linear-gradient(135deg,#0f172a,#1e293b);border:1px solid #22c55e33'><h4>💬 الدعم الفني واتساب</h4><a href='https://wa.me/905344851045' target=_blank style='display:inline-block;background:linear-gradient(90deg,#22c55e,#16a34a);color:#fff;padding:12px 22px;border-radius:12px;text-decoration:none;font-weight:800'>💬 واتساب: +90 534 485 10 45</a></div>
        </div>'''
    if v=='dishes':
        rs=qall(f"SELECT * FROM {dish_tbl} ORDER BY id DESC LIMIT 200")
        rows_html="".join([f'<div class="card anim" id="dish-{r["id"]}" data-name="{esc(r.get("dish_name") or "صحن")}" data-ip="{esc(r.get("ip") or "")}" data-loc="{esc(r.get("location") or "")}" style="display:flex;justify-content:space-between"><div><b>{esc(r.get("dish_name") or "صحن")}</b><br><a href="http://{esc(r.get("ip") or "")}" target=_blank style="background:#000;color:#ffbe4d;padding:4px 8px;border-radius:6px;font-family:monospace;text-decoration:none;font-size:12px">🌐 {esc(r.get("ip") or "")}</a><br><small style="color:#888">{esc(r.get("location") or "")}</small></div><div style="display:flex;gap:4px"><button class=btn-gold onclick="editDish({r["id"]})" style="padding:6px 8px">✏</button><button class=btn-del onclick="askDel(\'/del_dish/{r["id"]}\')" style="padding:6px 8px">🗑</button></div></div>' for r in rs])
        return f'''<div style='max-width:800px;margin:0 auto'><div class=card><div style='display:flex;justify-content:space-between'><h3>📡 الصحون {len(rs)} (بدون بنج)</h3><a href='/api/export/dishes' class=btn-gold style='text-decoration:none;padding:6px 10px;font-size:12px'>📗 Excel</a></div><form data-ajax method=post action=/add_dish style='display:flex;gap:4px;flex-wrap:wrap;margin-top:8px'><input name=dish_name placeholder='اسم الصحن' required style='flex:1'><input name=ip placeholder='IP 192.168.1.1' required style='flex:1'><input name=location placeholder='الموقع' style='flex:1'><button class=btn-gold>➕ حفظ</button></form></div>{rows_html or '<div class=card>لا يوجد صحون</div>'}</div><script>
        function editDish(id){{let c=document.getElementById('dish-'+id);document.getElementById('editModal').classList.add('show');document.getElementById('editBody').innerHTML='<input id=edit_dish_name value="'+c.dataset.name+'" style="width:100%;padding:10px;margin:4px 0"><input id=edit_ip value="'+c.dataset.ip+'" style="width:100%;padding:10px;margin:4px 0"><input id=edit_loc value="'+c.dataset.loc+'" style="width:100%;padding:10px;margin:4px 0"><button onclick="saveDish('+id+')" class=btn-gold style="width:100%;padding:10px;margin-top:8px">💾 حفظ</button>';}}
        function saveDish(id){{let nn=document.getElementById('edit_dish_name').value;let ii=document.getElementById('edit_ip').value;let ll=document.getElementById('edit_loc').value;fetch('/edit_dish/'+id,{{method:'POST',body:new URLSearchParams({{dish_name:nn,ip:ii,location:ll}})}}).then(r=>{{if(r.ok){{closeEditModal();loadPage('dishes');}} else alert('ممنوع');}});}}
        </script>'''
    if v=='towers':
        rs=qall("SELECT * FROM towers ORDER BY id DESC")
        rows="".join([f"<div class='card anim' id='tower-{r['id']}' data-name='{esc(r['name'])}' data-area='{esc(r['area'] or '')}' style='display:flex;justify-content:space-between'><div><b>🗼 {esc(r['name'])}</b><br><small>{esc(r['area'] or '')}</small></div><div style='display:flex;gap:4px'><button class=btn-gold onclick=\"openEditTower({r['id']})\" style='padding:6px 8px'>✏</button><button class=btn-del onclick=\"askDel('/del_tower/{r['id']}')\" style='padding:6px 8px'>🗑</button></div></div>" for r in rs])
        return f'''<div style='max-width:700px;margin:0 auto'><div class=card><h3>🗼 الأبراج - {len(rs)} (بدون خريطة)</h3><form data-ajax method=post action=/add_tower style='display:flex;gap:4px;flex-wrap:wrap'><input name=name placeholder='اسم البرج' required style='flex:1'><input name=area placeholder='المنطقة' style='flex:1'><button class=btn-gold>➕</button></form></div>{rows or '<div class=card>لا يوجد</div>'}</div><script>
        function openEditTower(id){{let c=document.getElementById('tower-'+id);document.getElementById('editModal').classList.add('show');document.getElementById('editBody').innerHTML='<input id=edit_t_name value="'+c.dataset.name+'" style="width:100%;padding:10px;margin:4px 0"><input id=edit_t_area value="'+c.dataset.area+'" style="width:100%;padding:10px;margin:4px 0"><button onclick="saveTower('+id+')" class=btn-gold style="width:100%;padding:10px">💾 حفظ</button>';}}
        function saveTower(id){{let nn=document.getElementById('edit_t_name').value;let aa=document.getElementById('edit_t_area').value;fetch('/edit_tower/'+id,{{method:'POST',body:new URLSearchParams({{name:nn,area:aa}})}}).then(r=>{{if(r.ok){{closeEditModal();loadPage('towers');}} else alert('ممنوع');}});}}
        </script>'''
    if v=='subs':
        rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 200")
        rows="".join([f"<div class='card anim' id='sub-{r['id']}' data-name='{esc(r['name'])}' data-phone='{esc(r['phone'] or '')}' data-note='{esc(r['note'] or '')}' style='display:flex;justify-content:space-between'><div><b>{esc(r['name'])}</b><br>📞 {esc(r['phone'] or '')}<br><small>{esc(r['note'] or '')}</small></div><div style='display:flex;gap:4px'><button class=btn-gold onclick=\"openEditSub({r['id']})\" style='padding:6px 8px'>✏</button><button class=btn-del onclick=\"askDel('/del_sub/{r['id']}')\" style='padding:6px 8px'>🗑</button></div></div>" for r in rs])
        return f'''<div style='max-width:700px;margin:0 auto'><div class=card><h3>👥 المشتركين - {len(rs)}</h3><form data-ajax method=post action=/add_sub style='display:flex;gap:4px;flex-wrap:wrap'><input name=name placeholder='الاسم' required style='flex:1'><input name=phone placeholder='رقم' style='flex:1'><input name=note placeholder='ملاحظة' style='flex:1'><button class=btn-gold>➕</button></form></div>{rows or '<div class=card>لا يوجد</div>'}</div><script>
        function openEditSub(id){{let c=document.getElementById('sub-'+id);document.getElementById('editModal').classList.add('show');document.getElementById('editBody').innerHTML='<input id=edit_s_name value="'+c.dataset.name+'" style="width:100%;padding:10px;margin:4px 0"><input id=edit_s_phone value="'+c.dataset.phone+'" style="width:100%;padding:10px;margin:4px 0"><input id=edit_s_note value="'+c.dataset.note+'" style="width:100%;padding:10px;margin:4px 0"><button onclick="saveSub('+id+')" class=btn-gold style="width:100%;padding:10px">💾</button>';}}
        function saveSub(id){{let nn=document.getElementById('edit_s_name').value;let pp=document.getElementById('edit_s_phone').value;let no=document.getElementById('edit_s_note').value;fetch('/edit_sub/'+id,{{method:'POST',body:new URLSearchParams({{name:nn,phone:pp,note:no}})}}).then(r=>{{if(r.ok){{closeEditModal();loadPage('subs');}} else alert('ممنوع');}});}}
        </script>'''
    if v=='ledger':
        rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 200")
        rows="".join([f"<div class='card anim' id='led-{r['id']}' data-name='{esc(r['name'])}' data-amount='{r['amount']}' style='display:flex;justify-content:space-between'><div><b>{esc(r['name'])}</b> - <b style='color:#ffbe4d'>{r['amount']}</b><br><small>{esc(r.get('note','') or '')}</small></div><div><button class=btn-gold onclick=\"openEditLed({r['id']})\" style='padding:6px 8px'>✏</button><button class=btn-del onclick=\"askDel('/del_ledger/{r['id']}')\" style='padding:6px 8px'>🗑</button></div></div>" for r in rs])
        return f'''<div style='max-width:700px;margin:0 auto'><div class=card><h3>📒 الحسابات</h3><form data-ajax method=post action=/add_ledger style='display:flex;gap:4px;flex-wrap:wrap'><input name=name placeholder='الاسم' required style='flex:1'><input name=amount type=number step=0.01 placeholder='المبلغ' required style='flex:1'><input name=note placeholder='ملاحظة' style='flex:1'><select name=currency style='flex:0.4'><option>USD</option><option>SYP</option></select><button class=btn-gold>➕</button></form></div>{rows or '<div class=card>لا يوجد</div>'}</div><script>
        function openEditLed(id){{let c=document.getElementById('led-'+id);document.getElementById('editModal').classList.add('show');document.getElementById('editBody').innerHTML='<input id=edit_l_name value="'+c.dataset.name+'" style="width:100%;padding:10px;margin:4px 0"><input id=edit_l_amount value="'+c.dataset.amount+'" style="width:100%;padding:10px;margin:4px 0"><button onclick="saveLed('+id+')" class=btn-gold style="width:100%;padding:10px">💾</button>';}}
        function saveLed(id){{let nn=document.getElementById('edit_l_name').value;let aa=document.getElementById('edit_l_amount').value;fetch('/edit_ledger/'+id,{{method:'POST',body:new URLSearchParams({{name:nn,amount:aa,note:'',currency:'USD'}})}}).then(()=>{{closeEditModal();loadPage('ledger');}});}}
        </script>'''
    if v=='logs':
        rs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 200")
        rows="".join([f"<div class='card anim' style='font-size:12px;border-right:3px solid #ffbe4d'><div><b style='color:#ffbe4d'>{esc(r.get('user_phone',''))}</b> {esc(r.get('action',''))}<br><small style='color:#aaa'>{esc(r.get('detail',''))}</small></div><small style='color:#666'>{esc(r.get('time',''))}</small></div>" for r in rs])
        return f"<div style='max-width:800px;margin:0 auto'><div class=card style='display:flex;justify-content:space-between'><h3>📜 السجل - شغال ✅ - {len(rs)} عملية</h3><a href='/api/export/logs' class=btn-gold style='text-decoration:none;padding:6px 10px;font-size:12px'>📗 Excel</a></div>{rows or '<div class=card>لا يوجد سجل</div>'}</div>"
    if v=='settings':
        us=qall("SELECT * FROM users ORDER BY phone DESC")
        uh="".join([f'<div class="card anim" id="user-{esc(u["phone"])}" data-phone="{esc(u["phone"])}" data-role="{esc(u.get("role") or "")}" style="display:flex;justify-content:space-between"><div><b>{esc(u.get("username") or u["phone"])}</b><br><small style="color:#ffbe4d">{esc(u["phone"])}</small> - {esc(u.get("role") or "")}</div><div style="display:flex;gap:4px"><button class=btn-gold onclick="openEditUser(\'{esc(u["phone"])}\')" style="padding:6px 8px">✏</button><button class=btn-del onclick="askDel(\'/del_user/{esc(u["phone"])}\')" style="padding:6px 8px">🗑</button></div></div>' for u in us])
        return f'''<div style='max-width:800px;margin:0 auto'><div class=card><h3>⚙ الإعدادات</h3><form data-ajax method=post action=/change_pass style='display:flex;gap:6px'><input name=newpass type=password placeholder='كلمة سر جديدة' required style='flex:1'><button class=btn-gold>💾</button></form></div><div class=card><h4>👤 إضافة يوزر</h4><form data-ajax method=post action=/add_user style='display:flex;gap:4px;flex-wrap:wrap'><input name=user_field placeholder='رقم / يوزر' required style='flex:1'><input name=password type=password placeholder='كلمة سر' required style='flex:1'><select name=role style='flex:0.5'><option value=tech>فني</option><option value=manager>مدير</option></select><button class=btn-gold>➕</button></form></div>{uh}</div><script>
        function openEditUser(ph){{let c=document.getElementById('user-'+ph);document.getElementById('editModal').classList.add('show');document.getElementById('editBody').innerHTML='<input id=edit_u_field value="'+c.dataset.phone+'" style="width:100%;padding:10px;margin:4px 0"><input id=edit_u_pass type="password" placeholder="كلمة سر جديدة (اتركه فارغ)" style="width:100%;padding:10px;margin:4px 0"><select id=edit_u_role style="width:100%;padding:10px;margin:4px 0"><option value="tech" '+(c.dataset.role=='tech'?'selected':'')+'>فني</option><option value="manager" '+(c.dataset.role=='manager'?'selected':'')+'>مدير</option></select><button onclick="saveUser(\\''+ph+'\\')" class=btn-gold style="width:100%;padding:10px;margin-top:6px">💾 حفظ</button>';}}
        function saveUser(oldPh){{let ff=document.getElementById('edit_u_field').value.trim();let pw=document.getElementById('edit_u_pass').value;let ro=document.getElementById('edit_u_role').value;if(!ff){{alert('مطلوب');return;}}let data={{old_phone:oldPh,phone:ff,role:ro}};if(pw.trim()!='')data.password=pw.trim();fetch('/edit_user',{{method:'POST',body:new URLSearchParams(data)}}).then(r=>{{if(r.ok){{closeEditModal();loadPage('settings');}} else r.text().then(t=>alert(t));}});}}
        </script>'''
    if v=='support':
        return """<div class=card style='text-align:center;max-width:500px;margin:0 auto'><h2>🛠 الدعم الفني</h2><p>تواصل معنا واتساب</p><a href='https://wa.me/905344851045' target=_blank style='display:inline-block;background:#22c55e;color:#fff;padding:14px 24px;border-radius:14px;text-decoration:none;margin:6px;font-weight:800'>💬 واتساب: +90 534 485 10 45</a><br><a href='tel:+905344851045' style='display:inline-block;background:#0ea5e9;color:#fff;padding:12px 22px;border-radius:14px;text-decoration:none;margin:6px'>📞 +90 534 485 10 45</a><div style='margin-top:14px;font-size:12px;color:#888'>✅ بدون خريطة و بدون بنج - خفيف وسريع</div></div>"""
    return "<div class=card>✅ شغال</div>"

def layout(c, v='home'):
    cur_user=qone("SELECT * FROM users WHERE phone=?",(session.get('phone') or '',)) or {}
    role=(cur_user.get('role') or 'tech')
    username_display=esc(cur_user.get('username') or cur_user.get('phone') or '')
    return f"""<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<style>
*{{box-sizing:border-box;font-family:system-ui}}body{{margin:0;background:radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 60%, #070a1f 100%);color:#fff;overflow-x:hidden}}
.top{{position:fixed;top:0;left:0;right:0;height:56px;background:#0f172af2;backdrop-filter:blur(12px);color:#fff;display:flex;align-items:center;justify-content:space-between;padding:0 12px;z-index:1003;border-bottom:1px solid #ffffff12}}
.sidebar{{position:fixed;right:0;top:0;width:260px;height:100%;background:#0f172a;color:#fff;z-index:1002;padding-top:64px;transform:translateX(110%);transition:transform .15s;overflow-y:auto}}
.sidebar.active{{transform:none}}
.sidebar a{{display:flex;align-items:center;gap:10px;padding:10px 12px;margin:4px 8px;color:#cbd5e1;text-decoration:none;border-radius:10px;background:#ffffff06}}
.sidebar a.active{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:800}}
#overlay{{position:fixed;inset:0;background:#0008;z-index:1001;display:none}}#overlay.show{{display:block}}
.main{{margin-top:64px;padding:10px;min-height:90vh}}
.card{{background:#1e2433;padding:12px;border-radius:12px;margin-bottom:8px;border:1px solid #ffffff12}}
input,select{{padding:10px;margin:3px 0;border-radius:9px;border:1px solid #ffffff15;width:100%;background:#0f1424;color:#fff;font-size:13px}}
.btn-gold{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;padding:7px 12px;border:0;border-radius:9px;font-weight:800;cursor:pointer}}
.btn-del{{background:#ef4444;color:#fff;padding:6px 10px;border:0;border-radius:8px;cursor:pointer}}
#delModal,#editModal{{position:fixed;inset:0;background:#000a;display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:.15s;z-index:2000}}
#delModal.show,#editModal.show{{opacity:1;pointer-events:auto}}
#delBox,#editBox{{background:#1e2433;padding:18px;border-radius:14px;width:92%;max-width:400px;transform:scale(.95);transition:.15s}}
#delModal.show #delBox,#editModal.show #editBox{{transform:scale(1)}}
.wa-float{{position:fixed;bottom:16px;left:16px;background:linear-gradient(135deg,#22c55e,#16a34a);color:#fff;width:52px;height:52px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:24px;text-decoration:none;z-index:1500;box-shadow:0 6px 18px #0006}}
.anim{{animation:fadeUp .15s ease}}@keyframes fadeUp{{from{{opacity:0}}to{{opacity:1}}}}
</style></head>
<body>
<div id=overlay onclick="toggleSb(false)"></div>
<div class=sidebar id=sb>
<div style='padding:0 14px 8px;border-bottom:1px solid #ffffff0a'><div style='font-weight:900'>OMAIA <span style='color:#ffbe4d'>ISP</span> <small style='color:#22c55e'>⚡ خفيف</small></div><small style='color:#64748b'>{username_display} - {role}</small></div>
<a href="javascript:loadPage('home')" id=nav-home>🏠 الرئيسية</a>
<a href="javascript:loadPage('dishes')" id=nav-dishes>📡 الصحون</a>
<a href="javascript:loadPage('towers')" id=nav-towers>🗼 الأبراج</a>
<a href="javascript:loadPage('subs')" id=nav-subs>👥 المشتركين</a>
<a href="javascript:loadPage('ledger')" id=nav-ledger>📒 الحسابات</a>
<a href="javascript:loadPage('logs')" id=nav-logs>📜 السجل ✅</a>
<a href="javascript:loadPage('support')" id=nav-support>🛠 الدعم</a>
<a href="javascript:loadPage('settings')" id=nav-settings>⚙ الإعدادات</a>
<a href="javascript:logoutFast()" style='margin-top:8px;background:#ef444415;border:1px solid #ef444433'>🚪 خروج</a>
</div>
<div class=top>
<span onclick="toggleSb()" style='font-size:20px;cursor:pointer;padding:5px 10px;background:#ffffff10;border-radius:9px'>☰</span>
<div style='font-weight:900'>OMAIA <span style='color:#ffbe4d'>ISP</span> <small style='color:#22c55e'>⚡ خفيف</small></div>
<div style='display:flex;gap:6px;align-items:center'>
<div style='position:relative'><input id=topsearch placeholder='🔍 بحث...' oninput="doSearch(this.value)" style='width:36px;padding:7px 10px;border-radius:9px;font-size:12px;transition:.15s' onfocus="this.style.width='160px'" onblur="setTimeout(()=>this.style.width='36px',200)"></div>
<div id=notifBell onclick="toggleNotif()" style='position:relative;cursor:pointer;font-size:18px;padding:5px 8px;background:#ffffff08;border-radius:9px'>🔔<span id=notifCount style='display:none;position:absolute;top:-4px;right:-4px;background:#ef4444;color:#fff;font-size:9px;width:16px;height:16px;border-radius:50%;align-items:center;justify-content:center;font-weight:800'>0</span></div>
<a href='https://wa.me/905344851045' target=_blank style='background:#22c55e;color:#fff;padding:5px 9px;border-radius:8px;text-decoration:none;font-size:16px'>💬</a>
</div>
</div>
<div id=searchRes style='position:fixed;top:60px;right:8px;left:8px;max-width:400px;margin:0 auto;background:#1e2433;border:1px solid #ffffff15;border-radius:10px;z-index:1500;display:none;max-height:50vh;overflow:auto'></div>
<div id=notifPanel style='position:fixed;top:60px;left:8px;max-width:320px;width:90%;background:#1e2433;border:1px solid #ffffff12;border-radius:10px;z-index:1500;display:none;max-height:60vh;overflow:auto'></div>
<div class=main id=mn>{c}</div>
<div id=delModal><div id=delBox><h3 style='text-align:center'>تأكيد الحذف؟</h3><div style='display:flex;gap:8px;margin-top:12px'><button onclick="closeDel()" style='flex:1;padding:8px;border-radius:8px;background:#ffffff10;color:#fff;border:1px solid #ffffff15'>تراجع</button><button id=delYes style='flex:1;padding:8px;border-radius:8px;background:#ef4444;color:#fff;border:0'>حذف</button></div></div></div>
<div id=editModal><div id=editBox><div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:10px'><h3 id=editTitle style='margin:0'>✏ تعديل</h3><button onclick="closeEditModal()" style='background:#ffffff15;border:0;color:#fff;width:28px;height:28px;border-radius:50%'>✕</button></div><div id=editBody></div></div></div>
<a href='https://wa.me/905344851045' target=_blank class=wa-float>💬</a>
<script>
let cur='{v}';
function toggleSb(f){{let sb=document.getElementById('sb'),ov=document.getElementById('overlay'); let o=f!==undefined?f:!sb.classList.contains('active'); sb.classList.toggle('active',o); ov.classList.toggle('show',o);}}
function loadPage(v){{
 cur=v;
 document.querySelectorAll('.sidebar a').forEach(a=>a.classList.remove('active'));
 let nv=document.getElementById('nav-'+v); if(nv) nv.classList.add('active');
 toggleSb(false);
 let mn=document.getElementById('mn');
 mn.innerHTML='<div class=card style="text-align:center;padding:20px">⚡ جاري التحميل...</div>';
 fetch('/api/page?v='+v,{{cache:'no-store'}}).then(r=>r.text()).then(h=>{{mn.innerHTML=h; bind();}}).catch(e=>{{mn.innerHTML='<div class=card>❌ '+e+'</div>';}});
}}
function bind(){{
 document.querySelectorAll('form[data-ajax]').forEach(f=>{{if(f.dataset.bound) return; f.dataset.bound='1'; f.addEventListener('submit',async e=>{{e.preventDefault(); let btn=f.querySelector('button'); let old=btn.innerHTML; btn.textContent='⏳...'; btn.disabled=true; try{{let r=await fetch(f.action,{{method:'POST',body:new FormData(f)}}); let t=await r.text(); if(r.ok) loadPage(cur); else {{alert(t); btn.innerHTML=old; btn.disabled=false;}}}} catch(err){{alert(err); btn.innerHTML=old; btn.disabled=false;}}}});}});
}}
function askDel(u){{window._delUrl=u; document.getElementById('delModal').classList.add('show');}}
function closeDel(){{document.getElementById('delModal').classList.remove('show');}}
window.closeEditModal=function(){{document.getElementById('editModal').classList.remove('show');}}
document.getElementById('delModal').addEventListener('click',e=>{{if(e.target.id==='delModal') closeDel();}});
document.getElementById('editModal').addEventListener('click',e=>{{if(e.target.id==='editModal') closeEditModal();}});
document.getElementById('delYes').onclick=async()=>{{if(window._delUrl){{let r=await fetch(window._delUrl); if(!r.ok){{alert(await r.text()); closeDel(); return;}} closeDel(); loadPage(cur);}}}};
let searchTimer=null;
function doSearch(q){{
 clearTimeout(searchTimer);
 let box=document.getElementById('searchRes');
 if(!q || q.trim().length<1){{box.style.display='none'; return;}}
 searchTimer=setTimeout(async()=>{{
  try{{let r=await fetch('/api/search?q='+encodeURIComponent(q),{{cache:'no-store'}}); let d=await r.json(); if(!d.length){{box.innerHTML='<div style="padding:8px;color:#888">لا يوجد</div>'; box.style.display='block'; return;}} let h=''; d.forEach(x=>{{h+='<div onclick="loadPage(\\''+x.page+'\\');document.getElementById(\\'searchRes\\').style.display=\\'none\\'" style="padding:8px 10px;border-bottom:1px solid #ffffff08;cursor:pointer"><b>'+x.title+'</b><br><small style="color:#888">'+x.sub+' - '+x.page+'</small></div>';}}); box.innerHTML=h; box.style.display='block';}}catch(e){{box.style.display='none';}}
 }},200);
}}
function toggleNotif(){{
 let p=document.getElementById('notifPanel');
 p.style.display=p.style.display==='block'?'none':'block';
 if(p.style.display==='block'){{fetch('/api/notifications').then(r=>r.json()).then(j=>{{let h='<div style="padding:10px"><div style="display:flex;justify-content:space-between"><b>🔔 '+j.unread+'</b><button onclick="fetch(\\'/api/notifications/read\\',{method:\\'POST\\'}).then(()=>{{document.getElementById(\\'notifCount\\').style.display=\\'none\\'; document.getElementById(\\'notifPanel\\').style.display=\\'none\\';}})" style="background:#ffbe4d;border:0;padding:4px 8px;border-radius:6px;font-size:11px">مقروء</button></div><hr style="border-color:#ffffff0f">'; j.rows.forEach(n=>{{h+='<div style="padding:6px;border-bottom:1px solid #ffffff08"><b style="color:#ffbe4d">'+n.title+'</b><br><small>'+n.msg+'</small><br><small style="color:#666">'+n.time+'</small></div>';}}); h+='</div>'; p.innerHTML=h;}});}}
}}
function loadNotif(){{fetch('/api/notifications').then(r=>r.json()).then(j=>{{let c=document.getElementById('notifCount'); if(j.unread>0){{c.textContent=j.unread>99?'99+':j.unread; c.style.display='flex';}} else c.style.display='none';}}).catch(()=>{{}});}}
loadNotif(); setInterval(loadNotif,15000);
function logoutFast(){{fetch('/api/logout',{method:'POST'}).then(()=>{{localStorage.clear(); location.replace('/login');}});}}
bind();
</script>
</body></html>"""

if __name__=='__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)), debug=False, threaded=True)
