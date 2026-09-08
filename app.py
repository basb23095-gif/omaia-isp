from flask import Flask, request, redirect, session, jsonify, Response
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, html, ipaddress, io, csv, datetime
import psycopg2, psycopg2.extras
import sqlite3

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "omia-sec-2026-CHANGE-ME-STRONG")
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(days=30)

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_PG = bool(DATABASE_URL)

def esc(s): 
    return html.escape(str(s or ''), quote=True)

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
            cur.close(); conn.close(); return rs
        else:
            rs=[dict(r) for r in conn.execute(q, a).fetchall()]
            conn.close(); return rs
    except:
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
            cur=conn.cursor(); cur.execute(q.replace("?", "%s"), a); conn.commit(); cur.close(); conn.close()
        else:
            conn.execute(q,a); conn.commit(); conn.close()
        return True
    except:
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
    if USE_PG: qexec(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {coltype_pg}")
    else:
        try:
            conn=get_conn(); cur=conn.cursor(); cur.execute(f"PRAGMA table_info({table})"); cols=[row[1] for row in cur.fetchall()]; conn.close()
            if column not in cols: qexec(f"ALTER TABLE {table} ADD COLUMN {column} {coltype_sqlite}")
        except: pass

def log_action(action,detail=""):
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
    ensure_column("towers","lat","DOUBLE PRECISION","REAL")
    ensure_column("towers","lng","DOUBLE PRECISION","REAL")
    ensure_column("towers","name","TEXT")
    ensure_column("users","username","TEXT")
    ensure_column("logs","time","TEXT")
    if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",('05344851045',generate_password_hash('admin2024'),'manager','admin'))
    if not qone("SELECT * FROM logs LIMIT 1"):
        qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)",('system','تشغيل النظام','تم تشغيل OMAIA ISP',datetime.datetime.now().strftime("%Y-%m-%d %H:%M")))
    if not qone("SELECT * FROM notifications LIMIT 1"):
        qexec("INSERT INTO notifications(title,msg,time,read) VALUES(?,?,?,?)",('مرحبا 👋','النظام شغال بدون خريطة و بدون ping',datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),0))

init()

def login_required(f):
    @wraps(f)
    def w(*a,**kw):
        if not session.get('phone'): return redirect('/login')
        return f(*a,**kw)
    return w

def is_manager():
    u=qone("SELECT * FROM users WHERE phone=?",(session.get('phone') or '',))
    if not u: return False
    return (u.get('role') or '').lower()=='manager'

def role_required_manager(f):
    @wraps(f)
    def w(*a,**kw):
        if not is_manager(): return "ممنوع",403
        return f(*a,**kw)
    return w

def is_valid_ip(ip):
    ip=(ip or '').strip()
    if not ip: return False
    try: ipaddress.ip_address(ip); return True
    except: return False

@app.route('/fix_db')
def fix_db_route():
    ensure_column("towers","area","TEXT")
    ensure_column("towers","lat","DOUBLE PRECISION","REAL")
    ensure_column("towers","lng","DOUBLE PRECISION","REAL")
    return jsonify(ok=True,msg="تم الإصلاح ✅ بدون خريطة و بدون ping")

@app.route('/reset_admin')
def reset_admin():
    qexec("DELETE FROM users WHERE phone=?",('05344851045',))
    qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",('05344851045',generate_password_hash('admin2024'),'manager','admin'))
    return jsonify(ok=True,msg="Admin reset")

@app.route('/ping')
@app.route('/health')
def public_ping():
    return jsonify(ok=True,pg=USE_PG,table=get_dish_table(),time=datetime.datetime.now().isoformat(),mode="no-map-no-ping")

@app.route('/api/notifications')
@login_required
def api_noti():
    rows=qall("SELECT * FROM notifications ORDER BY id DESC LIMIT 20")
    unread=qone("SELECT COUNT(*) as c FROM notifications WHERE read=0")
    cnt=unread.get('c',0) if unread else 0
    return jsonify(rows=rows,unread=cnt)

@app.route('/api/notifications/read', methods=['POST'])
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

@app.route('/api/login_public', methods=['POST'])
def api_login_public():
    uin=request.form.get('userin','').strip()
    pw=request.form.get('password','')
    u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
    if u and check_password_hash(u['password'],pw):
        session['phone']=u['phone']; session['username']=u.get('username') or u['phone']; session.permanent=True
        log_action("تسجيل دخول",uin)
        return jsonify(ok=True,role=u.get('role'))
    return jsonify(ok=False,msg='خطأ بالدخول'),401

@app.route('/api/export/<tbl>')
@login_required
def api_export(tbl):
    output=io.StringIO(); output.write('\ufeff'); w=csv.writer(output)
    dish_tbl=get_dish_table()
    if tbl=='logs':
        rows=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 1000")
        w.writerow(['ID','المستخدم','العملية','التفاصيل','الوقت'])
        for r in rows: w.writerow([r.get('id',''),r.get('user_phone',''),r.get('action',''),r.get('detail',''),r.get('time','')])
        fname='logs.csv'
    else:
        rows=qall(f"SELECT * FROM {dish_tbl} ORDER BY id DESC")
        w.writerow(['ID','اسم الصحن','IP','الموقع'])
        for r in rows: w.writerow([r.get('id',''),r.get('dish_name',''),r.get('ip',''),r.get('location','')])
        fname='dishes.csv'
    return Response(output.getvalue(),mimetype='text/csv; charset=utf-8',headers={'Content-Disposition': f'attachment; filename={fname}'})

@app.route('/')
def ix():
    return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login')
def login():
    return """<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<style>*{box-sizing:border-box;font-family:system-ui}body{margin:0;min-height:100vh;background:radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 55%, #070a1f 100%);display:flex;flex-direction:column;align-items:center;justify-content:center;color:#fff;padding:14px}
.card{background:linear-gradient(180deg, #222b45cc, #1a2035cc);backdrop-filter:blur(16px);border:1px solid #ffffff18;padding:26px;border-radius:22px;width:92%;max-width:400px;box-shadow:0 20px 60px #0008}
input{width:100%;padding:14px;margin:8px 0;background:#0f1424;border:1px solid #ffffff22;color:#fff;border-radius:14px;font-size:15px}
.btn{width:100%;padding:14px;border:0;border-radius:14px;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:900;font-size:17px;cursor:pointer;margin-top:10px}
.support-box{margin-top:18px;background:linear-gradient(135deg,#0f172a,#1e293b);border:1px solid #22c55e33;border-radius:16px;padding:14px;text-align:center;width:92%;max-width:400px}
.wa-btn{display:inline-flex;align-items:center;gap:8px;background:linear-gradient(90deg,#22c55e,#16a34a);color:#fff;padding:10px 18px;border-radius:12px;text-decoration:none;font-weight:800;margin:6px}
#loader{position:fixed;inset:0;background:#0a0e2a;z-index:9999;display:flex;flex-direction:column;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:opacity .15s}
#loader.show{opacity:1;pointer-events:auto}
.spinner{width:36px;height:36px;border:3px solid #ffffff18;border-top-color:#ffbe4d;border-radius:50%;animation:spin .6s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}</style></head><body>
<div id=loader><div class=spinner></div><div style='margin-top:10px;color:#ffbe4d;font-weight:800;font-size:13px'>⏳ جاري التحميل...</div></div>
<div style='font-size:30px;font-weight:900;margin-bottom:12px'>OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<div class=card><form id=loginForm><input name=userin id=userin placeholder='📱 رقم / يوزر - admin' required><input name=password id=password type=password placeholder='🔑 كلمة السر - admin2024' required><label style='display:flex;gap:8px;font-size:13px;color:#aaa;margin:8px 0'><input type=checkbox id=savePass style='width:auto'> حفظ</label><button class=btn id=loginBtn>✨ دخول فوري</button><div id=msg style='text-align:center;margin-top:8px;color:#ff6b6b;font-size:13px'></div></form></div>
<div class=support-box>
<div style='font-weight:800;margin-bottom:8px;color:#ffbe4d'>🛠 الدعم الفني</div>
<a href='https://wa.me/905344851045' target=_blank class=wa-btn>💬 واتساب: +90 534 485 10 45</a>
<div style='margin-top:8px'><a href='tel:+905344851045' style='color:#0ea5e9;text-decoration:none;font-size:13px'>📞 +90 534 485 10 45</a></div>
<div style='margin-top:10px;font-size:11px;color:#6b7280'>OMAIA ISP - بدون خريطة و بدون ping - خفيف ⚡</div>
</div>
<script>
let u=document.getElementById('userin'), p=document.getElementById('password'), s=document.getElementById('savePass');
let su=localStorage.getItem('omaia_user'), sp=localStorage.getItem('omaia_pass');
if(su){u.value=su; if(sp){p.value=sp; s.checked=true;}}
document.getElementById('loginForm').addEventListener('submit',async e=>{
 e.preventDefault(); let btn=document.getElementById('loginBtn'), msg=document.getElementById('msg'), loader=document.getElementById('loader');
 if(btn.disabled) return;
 btn.textContent='⏳...'; btn.disabled=true; loader.classList.add('show');
 try{
  let fd=new FormData(e.target);
  let r=await fetch('/api/login_public',{method:'POST',body:fd,cache:'no-store'});
  let j=await r.json();
  if(j.ok){ if(s.checked){localStorage.setItem('omaia_user',u.value);localStorage.setItem('omaia_pass',p.value);} location.replace('/dash?v=home'); }
  else{ msg.textContent=j.msg||'خطأ'; btn.textContent='✨ دخول فوري'; btn.disabled=false; loader.classList.remove('show'); }
 }catch(err){ msg.textContent='خطأ شبكة'; btn.textContent='✨ دخول فوري'; btn.disabled=false; loader.classList.remove('show'); }
});
</script></body></html>"""

@app.route('/logout')
def lo():
    session.clear()
    return redirect('/login')

@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify(ok=True)

@app.route('/dash')
@login_required
def dash():
    v=request.args.get('v','home')
    return layout(page_content(v),v)

@app.route('/api/page')
@login_required
def ap():
    return page_content(request.args.get('v','home'))

@app.route('/api/search')
@login_required
def s():
    q=request.args.get('q','').strip()
    if not q: return jsonify([])
    like="%"+q+"%"
    results=[]
    dish_tbl=get_dish_table()
    try:
        for r in qall(f"SELECT * FROM {dish_tbl} WHERE ip LIKE ? OR dish_name LIKE ? OR location LIKE ? ORDER BY id DESC LIMIT 10",(like,like,like)):
            results.append({"title": r.get('dish_name') or r.get('ip') or 'صحن', "sub": r.get('ip',''), "page": "dishes"})
        for r in qall("SELECT * FROM towers WHERE name LIKE ? OR area LIKE ? ORDER BY id DESC LIMIT 10",(like,like)):
            results.append({"title": r.get('name',''), "sub": r.get('area',''), "page": "towers"})
    except: pass
    return jsonify(results[:15])

@app.route('/toggle_theme')
@login_required
def tt():
    cur=session.get('theme','dark')
    session['theme']='light' if cur=='dark' else 'dark'
    return jsonify(ok=True)

@app.route('/add_dish', methods=['POST'])
@login_required
def ad():
    dish_tbl=get_dish_table()
    ip=request.form.get('ip','').strip()
    name=request.form.get('dish_name','').strip()
    loc=request.form.get('location','').strip()
    if not ip: return "IP مطلوب",400
    if not is_valid_ip(ip): return "IP غير صالح",400
    ex=qone(f"SELECT * FROM {dish_tbl} WHERE ip=?",(ip,))
    if ex:
        qexec(f"UPDATE {dish_tbl} SET dish_name=?,location=? WHERE ip=?",(name,loc,ip))
        log_action("تعديل صحن",f"{name} - {ip}")
        return "ok updated"
    qexec(f"INSERT INTO {dish_tbl}(ip,location,dish_name) VALUES(?,?,?)",(ip,loc,name))
    log_action("إضافة صحن",f"{name} - {ip}")
    qexec("INSERT INTO notifications(title,msg,time,read) VALUES(?,?,?,0)",(f"📡 صحن جديد {name}",f"{ip} - {loc}",datetime.datetime.now().strftime("%Y-%m-%d %H:%M")))
    return "ok"

@app.route('/del_dish/<int:i>')
@login_required
def dd(i):
    if not is_manager(): return "ممنوع",403
    qexec(f"DELETE FROM {get_dish_table()} WHERE id=?",(i,))
    log_action("حذف صحن",str(i))
    return "ok"

@app.route('/add_tower', methods=['POST'])
@login_required
def at():
    try: la=float(request.form.get('lat','') or 35.13); ln=float(request.form.get('lng','') or 36.75)
    except: la=35.13; ln=36.75
    name=request.form.get('name',''); area=request.form.get('area','')
    qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",(name,area,la,ln))
    log_action("إضافة برج",f"{name} - {area}")
    return "ok"

@app.route('/del_tower/<int:i>')
@login_required
def dt(i):
    if not is_manager(): return "ممنوع",403
    qexec("DELETE FROM towers WHERE id=?",(i,))
    log_action("حذف برج",str(i))
    return "ok"

@app.route('/add_sub', methods=['POST'])
@login_required
def asub():
    qexec("INSERT INTO subs(name,phone,note) VALUES(?,?,?)",(request.form.get('name',''),request.form.get('phone',''),request.form.get('note','')))
    log_action("إضافة مشترك",request.form.get('name',''))
    return "ok"

@app.route('/del_sub/<int:i>')
@login_required
def dsub(i):
    if not is_manager(): return "ممنوع",403
    qexec("DELETE FROM subs WHERE id=?",(i,))
    return "ok"

@app.route('/add_user', methods=['POST'])
@login_required
@role_required_manager
def au():
    ph=request.form.get('phone','').strip() or request.form.get('user_field','').strip()
    if not ph: return "رقم مطلوب",400
    if qone("SELECT * FROM users WHERE phone=?",(ph,)): return "موجود",400
    qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",(ph,generate_password_hash(request.form.get('password','1234')),request.form.get('role','tech'),ph))
    log_action("إضافة يوزر",ph)
    return "ok"

@app.route('/change_pass', methods=['POST'])
@login_required
def cp():
    np=request.form.get('newpass','').strip()
    if not np: return "فارغة",400
    qexec("UPDATE users SET password=? WHERE phone=?",(generate_password_hash(np),session.get('phone')))
    return "ok"

def page_content(v):
    dish_tbl=get_dish_table()
    if v=='home':
        ns=(qone("SELECT COUNT(*) as c FROM subs") or {}).get('c',0)
        nd=(qone(f"SELECT COUNT(*) as c FROM {dish_tbl}") or {}).get('c',0)
        nt=(qone("SELECT COUNT(*) as c FROM towers") or {}).get('c',0)
        logs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 5")
        log_html="".join([f"<div style='display:flex;justify-content:space-between;padding:6px 8px;border-bottom:1px dashed #ffffff10;font-size:12px'><div><b style='color:#ffbe4d'>{esc(l.get('user_phone',''))}</b> {esc(l.get('action',''))} <small style='color:#aaa'>{esc(l.get('detail',''))}</small></div><small style='color:#666'>{esc(l.get('time',''))}</small></div>" for l in logs])
        return f'''<div style='max-width:900px;margin:0 auto'>
        <div style='display:grid;grid-template-columns:1fr 1fr;gap:10px'>
        <div class='card anim' onclick="loadPage('dishes')" style='cursor:pointer;background:linear-gradient(135deg,#1e2f4a,#162040)'><h3 style='margin:0'>📡 {nd} صحن</h3><small style='color:#22c55e'>بدون ping</small></div>
        <div class='card anim' onclick="loadPage('towers')" style='cursor:pointer'><h3 style='margin:0'>🗼 {nt} برج</h3><small>بدون خريطة</small></div>
        <div class='card anim' onclick="loadPage('subs')" style='cursor:pointer'><h3 style='margin:0'>👥 {ns} مشترك</h3></div>
        <div class='card anim' onclick="loadPage('logs')" style='cursor:pointer'><h3 style='margin:0'>📜 السجل</h3><small>{len(logs)} عملية</small></div>
        </div>
        <div class=card style='margin-top:10px'><h4>📜 آخر النشاطات - السجل شغال ✅</h4>{log_html or 'لا يوجد'}<button class=btn-gold onclick="loadPage('logs')" style='width:100%;margin-top:8px'>عرض كل السجل</button></div>
        <div class=card style='text-align:center;background:linear-gradient(135deg,#0f172a,#1e293b);border:1px solid #22c55e33'><h4>💬 الدعم الفني واتساب</h4><a href='https://wa.me/905344851045' target=_blank style='display:inline-block;background:linear-gradient(90deg,#22c55e,#16a34a);color:#fff;padding:12px 22px;border-radius:12px;text-decoration:none;font-weight:800'>💬 واتساب: +90 534 485 10 45</a></div>
        </div>'''
    if v=='dishes':
        rs=qall(f"SELECT * FROM {dish_tbl} ORDER BY id DESC LIMIT 100")
        rows_html="".join([f'<div class="card anim" style="display:flex;justify-content:space-between"><div><b>{esc(r.get("dish_name") or "صحن")}</b><br><small style="color:#ffbe4d">{esc(r.get("ip") or "")}</small></div><div><button class=btn-del onclick="askDel(\'/del_dish/{r["id"]}\')" style="padding:6px 8px">🗑</button></div></div>' for r in rs])
        return f'''<div style='max-width:800px;margin:0 auto'><div class=card><h3>📡 الصحون - {len(rs)} (بدون ping)</h3><form data-ajax method=post action=/add_dish style='display:flex;gap:6px'><input name=dish_name placeholder='اسم الصحن' required style='flex:1'><input name=ip placeholder='IP' required style='flex:1'><button class=btn-gold>➕</button></form></div>{rows_html}</div>'''
    if v=='towers':
        rs=qall("SELECT * FROM towers ORDER BY id DESC")
        rows="".join([f"<div class='card anim' style='display:flex;justify-content:space-between'><div><b>🗼 {esc(r['name'])}</b><br><small>{esc(r['area'] or '')}</small></div><div><button class=btn-del onclick=\"askDel('/del_tower/{r['id']}')\" style='padding:6px 8px'>🗑</button></div></div>" for r in rs])
        return f'''<div style='max-width:700px;margin:0 auto'><div class=card><h3>🗼 الأبراج - {len(rs)} (بدون خريطة)</h3><form data-ajax method=post action=/add_tower style='display:flex;gap:4px'><input name=name placeholder='اسم البرج' required style='flex:1'><input name=area placeholder='المنطقة' style='flex:1'><button class=btn-gold>➕</button></form></div>{rows}</div>'''
    if v=='subs':
        rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 200")
        rows="".join([f"<div class='card anim' style='display:flex;justify-content:space-between'><div><b>{esc(r['name'])}</b><br>📞 {esc(r['phone'] or '')}</div><div><button class=btn-del onclick=\"askDel('/del_sub/{r['id']}')\" style='padding:6px 8px'>🗑</button></div></div>" for r in rs])
        return f'''<div style='max-width:700px;margin:0 auto'><div class=card><h3>👥 المشتركين</h3><form data-ajax method=post action=/add_sub style='display:flex;gap:4px'><input name=name placeholder='الاسم' required style='flex:1'><input name=phone placeholder='رقم' style='flex:1'><button class=btn-gold>➕</button></form></div>{rows}</div>'''
    if v=='logs':
        rs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 100")
        rows="".join([f"<div class='card anim' style='font-size:12px;border-right:3px solid #ffbe4d'><div><b style='color:#ffbe4d'>{esc(r.get('user_phone',''))}</b> - {esc(r.get('action',''))}<br><small style='color:#aaa'>{esc(r.get('detail',''))}</small></div><small style='color:#666'>{esc(r.get('time',''))}</small></div>" for r in rs])
        return f"<div style='max-width:900px;margin:0 auto'><div class=card><h3>📜 السجل - شغال ✅ - {len(rs)} عملية</h3></div>{rows or '<div class=card>لا يوجد</div>'}</div>"
    if v=='settings':
        us=qall("SELECT * FROM users ORDER BY phone DESC")
        uh="".join([f'<div class="card anim"><b>{esc(u.get("username") or u["phone"])}</b> - {esc(u["phone"])} - {esc(u.get("role") or "")}</div>' for u in us])
        return f'''<div style='max-width:700px;margin:0 auto'><div class=card><h3>⚙ الإعدادات - بدون خريطة و بدون ping</h3><form data-ajax method=post action=/change_pass style='display:flex;gap:6px'><input name=newpass type=password placeholder='كلمة سر جديدة' required style='flex:1'><button class=btn-gold>💾</button></form></div>{uh}</div>'''
    return "<div class=card>✅ شغال بدون خريطة و بدون ping - خفيف وسريع ⚡</div>"

def layout(c,v='home'):
    bg='radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 60%, #070a1f 100%)'
    card_bg='#1e2433'; txt='#ffffff'; border='#ffffff12'
    cur_user=qone("SELECT * FROM users WHERE phone=?",(session.get('phone') or '',)) or {}
    role=(cur_user.get('role') or 'tech')
    username_display=esc(cur_user.get('username') or cur_user.get('phone') or '')
    return f"""<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<style>
*{{box-sizing:border-box;font-family:system-ui}}body{{margin:0;background:{bg};color:{txt};overflow-x:hidden}}
.anim{{animation:fadeUp .15s ease}}@keyframes fadeUp{{from{{opacity:0}}to{{opacity:1}}}}
.top{{position:fixed;top:0;left:0;right:0;height:58px;background:#0f172af2;backdrop-filter:blur(12px);color:#fff;display:flex;align-items:center;justify-content:space-between;padding:0 12px;z-index:1003;border-bottom:1px solid #ffffff12}}
.sidebar{{position:fixed;right:0;top:0;width:270px;height:100%;background:#0f172a;color:#fff;z-index:1002;padding-top:65px;transform:translateX(110%);transition:transform .2s;overflow-y:auto}}
.sidebar.active{{transform:none}}
.sidebar a{{display:flex;align-items:center;gap:10px;padding:11px 13px;margin:4px 9px;color:#cbd5e1;text-decoration:none;border-radius:11px;background:#ffffff06}}
.sidebar a.active{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:800}}
#overlay{{position:fixed;inset:0;background:#0008;z-index:1001;display:none}}#overlay.show{{display:block}}
.main{{margin-top:65px;padding:10px;min-height:90vh}}
.card{{background:{card_bg};padding:12px;border-radius:12px;margin-bottom:8px;border:1px solid {border}}}
input{{padding:11px;margin:3px 0;border-radius:9px;border:1px solid {border};width:100%;background:#ffffff07;color:{txt}}}
.btn-gold{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;padding:7px 12px;border:0;border-radius:9px;font-weight:800;cursor:pointer}}
.btn-del{{background:#ef4444;color:#fff;padding:6px 10px;border:0;border-radius:8px}}
#delModal{{position:fixed;inset:0;background:#000a;display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:.15s;z-index:2000}}
#delModal.show{{opacity:1;pointer-events:auto}}
#delBox{{background:{card_bg};padding:18px;border-radius:14px;width:92%;max-width:400px}}
.wa-float{{position:fixed;bottom:18px;left:18px;z-index:1500;background:linear-gradient(135deg,#22c55e,#16a34a);color:#fff;width:54px;height:54px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:26px;box-shadow:0 6px 20px #0006;text-decoration:none}}
</style></head>
<body>
<div id=overlay onclick="toggleSb(false)"></div>
<div class=sidebar id=sb>
<div style='padding:0 14px 8px;border-bottom:1px solid #ffffff0a'><div style='font-weight:900'>OMAIA <span style='color:#ffbe4d'>ISP</span> <small style='color:#22c55e'>⚡ بدون ping/map</small></div><small style='color:#64748b'>{username_display}</small></div>
<a href="javascript:loadPage('home')" id=nav-home>🏠 الرئيسية</a>
<a href="javascript:loadPage('dishes')" id=nav-dishes>📡 الصحون</a>
<a href="javascript:loadPage('towers')" id=nav-towers>🗼 الأبراج</a>
<a href="javascript:loadPage('subs')" id=nav-subs>👥 المشتركين</a>
<a href="javascript:loadPage('logs')" id=nav-logs>📜 السجل ✅</a>
<a href="javascript:loadPage('settings')" id=nav-settings>⚙ الإعدادات</a>
<a href="javascript:logoutFast()">🚪 خروج</a>
</div>
<div class=top>
<span onclick="toggleSb()" style='font-size:22px;cursor:pointer;padding:5px 9px;background:#ffffff10;border-radius:9px'>☰</span>
<div style='font-weight:900;font-size:14px'>OMAIA <span style='color:#ffbe4d'>ISP</span> <small style='color:#22c55e'>⚡ خفيف</small></div>
<div style='display:flex;gap:6px;align-items:center'>
<div id=notifBell onclick="toggleNotif()" style='position:relative;cursor:pointer;font-size:18px;padding:5px 8px;background:#ffffff08;border-radius:9px'>🔔<span id=notifCount style='display:none;position:absolute;top:-3px;right:-3px;background:#ef4444;color:#fff;font-size:9px;width:16px;height:16px;border-radius:50%;align-items:center;justify-content:center;font-weight:800'>0</span></div>
<a href='https://wa.me/905344851045' target=_blank style='background:#22c55e;color:#fff;padding:6px 10px;border-radius:9px;text-decoration:none;font-size:14px'>💬</a>
</div>
</div>
<div id=notifPanel style='position:fixed;top:62px;left:10px;max-width:340px;width:90%;background:#1e2433;border:1px solid #ffffff12;border-radius:12px;z-index:2000;display:none;max-height:65vh;overflow:auto'></div>
<div class=main id=mn>{c}</div>
<div id=delModal><div id=delBox><h3 style='text-align:center'>حذف؟</h3><div style='display:flex;gap:6px;margin-top:10px'><button onclick="closeDel()" style='flex:1;padding:8px;border-radius:8px'>لا</button><button id=delYes style='flex:1;padding:8px;border-radius:8px;background:#ef4444;color:#fff;border:0'>نعم</button></div></div></div>
<a href='https://wa.me/905344851045' target=_blank class=wa-float title='دعم فني'>💬</a>
<script>
let cur='{v}';
function toggleSb(f){{let sb=document.getElementById('sb'),ov=document.getElementById('overlay'); let o=f!==undefined?f:!sb.classList.contains('active'); sb.classList.toggle('active',o); ov.classList.toggle('show',o);}}
let pageCache={{}}; try{{pageCache=JSON.parse(localStorage.getItem('omaia_nar_light')||'{{}}');}}catch(e){{}}
function saveCache(){{try{{localStorage.setItem('omaia_nar_light',JSON.stringify(pageCache));}}catch(e){{}}}}
async function loadPage(v,force=false,push=true){{
  if(push && cur!==v){{try{{history.pushState({{page:v}}, '', '/dash?v='+v);}}catch(e){{}}}}
  cur=v; let mn=document.getElementById('mn');
  if(!force && pageCache[v]){{mn.innerHTML=pageCache[v]; bind(); document.querySelectorAll('.sidebar a').forEach(a=>a.classList.remove('active')); let nv=document.getElementById('nav-'+v); if(nv) nv.classList.add('active'); toggleSb(false); fetch('/api/page?v='+v,{{cache:'no-store'}}).then(r=>r.text()).then(h=>{{pageCache[v]=h; saveCache();}}).catch(()=>{{}}); return;}}
  mn.innerHTML='<div class=card style="text-align:center;padding:20px">⚡ جاري التحميل...</div>'; toggleSb(false);
  try{{let r=await fetch('/api/page?v='+v,{{cache:'no-store'}}); let h=await r.text(); pageCache[v]=h; saveCache(); mn.innerHTML=h; bind(); document.querySelectorAll('.sidebar a').forEach(a=>a.classList.remove('active')); let nv=document.getElementById('nav-'+v); if(nv) nv.classList.add('active');}}catch(e){{mn.innerHTML='<div class=card>❌ '+e+'</div>';}}
}}
function bind(){{
  document.querySelectorAll('form[data-ajax]').forEach(f=>{{if(f.dataset.bound) return; f.dataset.bound='1'; f.onsubmit=async e=>{{e.preventDefault(); let btn=f.querySelector('button'); if(btn){{btn.textContent='⏳'; btn.disabled=true;}} try{{let r=await fetch(f.action,{{method:'POST',body:new FormData(f)}}); if(r.ok){{delete pageCache[cur]; await loadPage(cur,true);}} else {{let t=await r.text(); alert(t); if(btn){{btn.textContent='➕'; btn.disabled=false;}}}}}}catch(err){{alert(err);}}}};}});
}}
function askDel(u){{window._delUrl=u;document.getElementById('delModal').classList.add('show');}}
function closeDel(){{document.getElementById('delModal').classList.remove('show');}}
document.getElementById('delYes').onclick=async()=>{{if(window._delUrl){{await fetch(window._delUrl); delete pageCache[cur]; closeDel(); loadPage(cur,true);}}}};
window.toggleNotif=async function(){{
  let p=document.getElementById('notifPanel'); p.style.display=p.style.display==='block'?'none':'block';
  if(p.style.display==='block'){{try{{let r=await fetch('/api/notifications'); let j=await r.json(); let h='<div style="padding:10px"><div style="display:flex;justify-content:space-between"><b>🔔 '+j.unread+'</b><button onclick="readAllNotif()" style="background:#ffbe4d;border:0;padding:4px 8px;border-radius:6px;font-size:11px">مقروء</button></div><hr style="border-color:#ffffff0f;margin:6px 0">'; j.rows.forEach(n=>{{h+='<div style="padding:6px;border-bottom:1px solid #ffffff08"><b style="color:#ffbe4d;font-size:12px">'+n.title+'</b><br><small style="color:#ccc">'+n.msg+'</small><br><small style="color:#666">'+n.time+'</small></div>';}}); h+='</div>'; p.innerHTML=h;}}catch(e){{}}}}
}}
window.readAllNotif=async function(){{try{{await fetch('/api/notifications/read',{{method:'POST'}});}}catch(e){{}} document.getElementById('notifCount').style.display='none'; document.getElementById('notifPanel').style.display='none';}}
async function loadNotif(){{try{{let r=await fetch('/api/notifications'); let j=await r.json(); let c=document.getElementById('notifCount'); if(j.unread>0){{c.textContent=j.unread>99?'99+':j.unread; c.style.display='flex';}} else {{c.style.display='none';}}}}catch(e){{}}}}
loadNotif(); setInterval(loadNotif,20000);
window.logoutFast=async function(){{try{{await fetch('/api/logout',{{method:'POST'}});}}catch(e){{}} localStorage.clear(); location.replace('/login');}};
bind();
</script>
</body></html>"""

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)), debug=False, threaded=True)
