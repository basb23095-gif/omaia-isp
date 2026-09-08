from flask import Flask, request, redirect, session, jsonify, Response
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, html, ipaddress, json, socket, io, csv, datetime, re
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
            cur.close(); conn.close(); return rs
        else:
            rs=[dict(r) for r in conn.execute(q,a).fetchall()]
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
            cur=conn.cursor()
            cur.execute(q.replace("?", "%s"), a)
            conn.commit(); cur.close(); conn.close()
        else:
            conn.execute(q,a); conn.commit(); conn.close()
        return True
    except Exception as e:
        print(f"[DB] {e}")
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
            conn=get_conn(); cur=conn.cursor()
            cur.execute(f"PRAGMA table_info({table})")
            cols=[row[1] for row in cur.fetchall()]
            conn.close()
            if column not in cols: qexec(f"ALTER TABLE {table} ADD COLUMN {column} {coltype_sqlite}")
        except: pass

def log_action(action,detail=""):
    try:
        phone=session.get('phone','system')
        now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)",(phone,action,detail,now))
    except: pass

SYRIA_PLACES=[
('حمص - المركز','حمص',34.7324,36.7137),('تلكلخ','تلكلخ',34.6721,36.2575),('القصير','القصير',34.5086,36.5756),('الرستن','الرستن',34.9275,36.7358),('تلبيسة','تلبيسة',34.8333,36.7333),('المخرم','المخرم',34.8167,37.0833),('القريتين','القريتين',34.2314,37.2386),('تدمر','تدمر',34.56,38.2672),('الحولة','الحولة',34.8833,36.5667),('شين','حمص',34.7667,36.4167),
('حماة - المركز','حماة',35.1318,36.7578),('مصياف','مصياف',35.0647,36.34),('السلمية','السلمية',35.011,37.0533),('محردة','محردة',35.2486,36.5789),('السقيلبية','السقيلبية',35.3675,36.3808),('كفرزيتا','حماة',35.3714,36.6125),('مورك','حماة',35.3708,36.6894),('صوران','حماة',35.2917,36.7333),
('حلب','حلب',36.2021,37.1343),('منبج','حلب',36.5281,37.9567),('الباب','حلب',36.3692,37.5145),('عفرين','حلب',36.5114,36.8692),('اعزاز','حلب',36.5868,37.0456),('جرابلس','حلب',36.8219,38.0106),('دمشق','دمشق',33.5138,36.2765),('دوما','ريف دمشق',33.5724,36.4019),('داريا','ريف دمشق',33.4583,36.2333),('الزبداني','ريف دمشق',33.725,36.0972),('النبك','ريف دمشق',34.0267,36.7267),
('درعا','درعا',32.6257,36.1082),('ازرع','درعا',32.8692,36.2517),('السويداء','السويداء',32.7094,36.5667),('طرطوس','طرطوس',34.8886,35.8914),('بانياس','طرطوس',35.1828,35.9489),('اللاذقية','اللاذقية',35.5406,35.7772),('جبلة','اللاذقية',35.3594,35.9217),('إدلب','إدلب',35.9306,36.6339),('معرة النعمان','إدلب',35.6433,36.6692),('دير الزور','دير الزور',35.3333,40.15),('الرقة','الرقة',35.95,39.0167),('الحسكة','الحسكة',36.5,40.75),('القامشلي','الحسكة',37.05,41.2167)
]

def init():
    if USE_PG:
        tables=["CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,username TEXT)","CREATE TABLE IF NOT EXISTS subs(id SERIAL PRIMARY KEY,name TEXT,phone TEXT,note TEXT)","CREATE TABLE IF NOT EXISTS ledger(id SERIAL PRIMARY KEY,name TEXT,amount REAL,note TEXT,currency TEXT)","CREATE TABLE IF NOT EXISTS dish_ips(id SERIAL PRIMARY KEY,ip TEXT,location TEXT,dish_name TEXT)","CREATE TABLE IF NOT EXISTS towers(id SERIAL PRIMARY KEY,name TEXT,area TEXT,lat DOUBLE PRECISION,lng DOUBLE PRECISION)","CREATE TABLE IF NOT EXISTS logs(id SERIAL PRIMARY KEY,user_phone TEXT,action TEXT,detail TEXT,time TEXT)","CREATE TABLE IF NOT EXISTS notifications(id SERIAL PRIMARY KEY,title TEXT,msg TEXT,time TEXT,read INTEGER DEFAULT 0)","CREATE TABLE IF NOT EXISTS ips(id SERIAL PRIMARY KEY, ip TEXT, location TEXT, dish_name TEXT, created_at TIMESTAMP DEFAULT NOW())"]
    else:
        tables=["CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,username TEXT)","CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,note TEXT)","CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,amount REAL,note TEXT,currency TEXT)","CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,dish_name TEXT)","CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,area TEXT,lat REAL,lng REAL)","CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,user_phone TEXT,action TEXT,detail TEXT,time TEXT)","CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,msg TEXT,time TEXT,read INTEGER DEFAULT 0)","CREATE TABLE IF NOT EXISTS ips(id INTEGER PRIMARY KEY AUTOINCREMENT, ip TEXT, location TEXT, dish_name TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"]
    for s in tables: qexec(s)
    ensure_column("towers","area","TEXT"); ensure_column("towers","lat","DOUBLE PRECISION","REAL"); ensure_column("towers","lng","DOUBLE PRECISION","REAL"); ensure_column("towers","name","TEXT"); ensure_column("users","username","TEXT"); ensure_column("logs","time","TEXT")
    if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",('05344851045',generate_password_hash('admin2024'),'manager','admin'))
    cnt=(qone("SELECT COUNT(*) as c FROM towers") or {}).get('c',0)
    if cnt<20:
        for name,area,lat,lng in SYRIA_PLACES:
            if not qone("SELECT * FROM towers WHERE name=?",(name,)):
                qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",(name,area,lat,lng))
    if not qone("SELECT * FROM logs LIMIT 1"):
        qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)",('system','تشغيل النظام','OMAIA ISP نار ⚡',datetime.datetime.now().strftime("%Y-%m-%d %H:%M")))
    if not qone("SELECT * FROM notifications LIMIT 1"):
        qexec("INSERT INTO notifications(title,msg,time,read) VALUES(?,?,?,?)",('مرحبا 👋','النظام صار نار - الكاش تصلح',datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),0))
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
    ensure_column("towers","area","TEXT"); ensure_column("towers","lat","DOUBLE PRECISION","REAL"); ensure_column("towers","lng","DOUBLE PRECISION","REAL")
    added=0
    for name,area,lat,lng in SYRIA_PLACES:
        if not qone("SELECT * FROM towers WHERE name=?",(name,)):
            qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",(name,area,lat,lng)); added+=1
    return jsonify(ok=True,msg=f"تم الإصلاح + {added} منطقة ✅ - الكاش نار")
@app.route('/reset_admin')
def reset_admin():
    qexec("DELETE FROM users WHERE phone=?",('05344851045',))
    qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",('05344851045',generate_password_hash('admin2024'),'manager','admin'))
    return jsonify(ok=True)
@app.route('/ping')
@app.route('/health')
def public_ping(): return jsonify(ok=True,pg=USE_PG,table=get_dish_table(),time=datetime.datetime.now().isoformat())
@app.route('/api/ping')
@login_required
def api_ping():
    ip=request.args.get('ip','').strip()
    if not ip: return jsonify(ok=False,out='لا يوجد IP')
    if not is_valid_ip(ip): return jsonify(ok=False,out='IP غير صالح')
    if ip.startswith("192.168.") or ip.startswith("10.") or ip.startswith("172."): return jsonify(ok=False,out=f'⚠️ {ip} IP خاص داخلي - لا يمكن فحصه من Render')
    for port in [80,443,8080,8291,22,8728]:
        s=None
        try:
            s=socket.socket(socket.AF_INET,socket.SOCK_STREAM); s.settimeout(0.8)
            if s.connect_ex((ip,port))==0: s.close(); return jsonify(ok=True,out=f'✅ متصل - {ip}:{port} مفتوح',port=port)
            s.close()
        except:
            try:
                if s: s.close()
            except: pass
    return jsonify(ok=False,out=f'❌ {ip} لا يرد')
@app.route('/api/ping_tcp')
@login_required
def api_ping_tcp():
    ip=request.args.get('ip','').strip(); port_str=request.args.get('port','80').strip()
    try: port=int(port_str); 
    except: return jsonify(ok=False,out='Port غير صالح')
    if not is_valid_ip(ip): return jsonify(ok=False,out='IP غير صالح')
    s=None
    try:
        s=socket.socket(socket.AF_INET,socket.SOCK_STREAM); s.settimeout(1); r=s.connect_ex((ip,port)); s.close()
        return jsonify(ok=r==0,out=f'✅ {ip}:{port} مفتوح' if r==0 else f'❌ {ip}:{port} مغلق')
    except: return jsonify(ok=False,out='❌ خطأ')
@app.route('/api/notifications')
@login_required
def api_noti():
    rows=qall("SELECT * FROM notifications ORDER BY id DESC LIMIT 20")
    unread=qone("SELECT COUNT(*) as c FROM notifications WHERE read=0")
    cnt=unread.get('c',0) if unread else 0
    return jsonify(rows=rows,unread=cnt)
@app.route('/api/notifications/read',methods=['POST'])
@login_required
def api_noti_read(): qexec("UPDATE notifications SET read=1"); return jsonify(ok=True)
@app.route('/api/network_status')
@login_required
def api_network():
    tbl=get_dish_table()
    return jsonify(dishes=len(qall(f"SELECT * FROM {tbl}")),towers=len(qall("SELECT * FROM towers")),subs=(qone("SELECT COUNT(*) as c FROM subs") or {}).get('c',0))
@app.route('/toggle_lang')
@login_required
def toggle_lang_route():
    cur=session.get('lang','ar'); session['lang']='en' if cur=='ar' else 'ar'; return jsonify(ok=True,lang=session['lang'])
@app.route('/api/login_public',methods=['POST'])
def api_login_public():
    uin=request.form.get('userin','').strip(); pw=request.form.get('password','')
    u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
    if u and check_password_hash(u['password'],pw):
        session['phone']=u['phone']; session['username']=u.get('username') or u['phone']; session.permanent=True
        log_action("تسجيل دخول",uin)
        return jsonify(ok=True,role=u.get('role'))
    return jsonify(ok=False,msg='خطأ بالدخول'),401
@app.route('/api/export/<tbl>')
@login_required
def api_export(tbl):
    output=io.StringIO(); output.write('\ufeff'); w=csv.writer(output); dish_tbl=get_dish_table()
    if tbl=='towers':
        rows=qall("SELECT * FROM towers ORDER BY id DESC"); w.writerow(['ID','اسم','المنطقة','lat','lng'])
        for r in rows: w.writerow([r.get('id',''),r.get('name',''),r.get('area',''),r.get('lat',''),r.get('lng','')]); fname='towers.csv'
    elif tbl=='logs':
        rows=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 1000"); w.writerow(['ID','المستخدم','العملية','التفاصيل','الوقت'])
        for r in rows: w.writerow([r.get('id',''),r.get('user_phone',''),r.get('action',''),r.get('detail',''),r.get('time','')]); fname='logs.csv'
    else:
        rows=qall(f"SELECT * FROM {dish_tbl} ORDER BY id DESC"); w.writerow(['ID','اسم الصحن','IP','الموقع'])
        for r in rows: w.writerow([r.get('id',''),r.get('dish_name',''),r.get('ip',''),r.get('location','')]); fname='dishes.csv'
    return Response(output.getvalue(),mimetype='text/csv; charset=utf-8',headers={'Content-Disposition': f'attachment; filename={fname}'})
@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')
@app.route('/login')
def login():
    return """<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<style>*{box-sizing:border-box;font-family:system-ui}body{margin:0;min-height:100vh;background:radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 55%, #070a1f 100%);display:flex;flex-direction:column;align-items:center;justify-content:center;color:#fff;padding:12px}
.card{background:linear-gradient(180deg, #222b45cc, #1a2035cc);backdrop-filter:blur(16px);border:1px solid #ffffff18;padding:24px;border-radius:20px;width:92%;max-width:380px;box-shadow:0 20px 60px #0008}
input{width:100%;padding:13px;margin:7px 0;background:#0f1424;border:1px solid #ffffff22;color:#fff;border-radius:12px;font-size:14px}
.btn{width:100%;padding:13px;border:0;border-radius:12px;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:900;font-size:16px;cursor:pointer;margin-top:10px}
.support-box{margin-top:14px;background:linear-gradient(135deg,#0f172a,#1e293b);border:1px solid #22c55e33;border-radius:14px;padding:12px;text-align:center;width:92%;max-width:380px}
.wa-btn{display:inline-flex;align-items:center;gap:6px;background:linear-gradient(90deg,#22c55e,#16a34a);color:#fff;padding:9px 16px;border-radius:10px;text-decoration:none;font-weight:800;margin:4px;font-size:13px}
#loader{position:fixed;inset:0;background:#0a0e2a;z-index:9999;display:flex;flex-direction:column;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:opacity .1s}
#loader.show{opacity:1;pointer-events:auto}
.spinner{width:32px;height:32px;border:3px solid #ffffff18;border-top-color:#ffbe4d;border-radius:50%;animation:spin .5s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}</style></head><body>
<div id=loader><div class=spinner></div><div style='margin-top:8px;color:#ffbe4d;font-weight:800;font-size:12px'>⏳...</div></div>
<div style='font-size:28px;font-weight:900;margin-bottom:10px'>OMAIA <span style='color:#ffbe4d'>ISP</span> <small style='color:#22c55e'>⚡ نار</small></div>
<div class=card><form id=loginForm><input name=userin id=userin placeholder='📱 رقم / يوزر - admin' required><input name=password id=password type=password placeholder='🔑 admin2024' required><label style='display:flex;gap:6px;font-size:12px;color:#aaa;margin:6px 0'><input type=checkbox id=savePass style='width:auto'> حفظ</label><button class=btn id=loginBtn>✨ دخول فوري نار</button><div id=msg style='text-align:center;margin-top:6px;color:#ff6b6b;font-size:12px'></div></form></div>
<div class=support-box><div style='font-weight:800;margin-bottom:6px;color:#ffbe4d;font-size:13px'>🛠 الدعم الفني</div><a href='https://wa.me/905344851045' target=_blank class=wa-btn>💬 واتساب: +90 534 485 10 45</a><div style='margin-top:6px;font-size:11px;color:#6b7280'>نظام سريع ⚡ بدون بطء</div></div>
<script>
let u=document.getElementById('userin'),p=document.getElementById('password'),s=document.getElementById('savePass');
let su=localStorage.getItem('omaia_user'),sp=localStorage.getItem('omaia_pass');
if(su){u.value=su; if(sp){p.value=sp; s.checked=true;}}
document.getElementById('loginForm').addEventListener('submit',async e=>{
 e.preventDefault(); let btn=document.getElementById('loginBtn'),msg=document.getElementById('msg'),loader=document.getElementById('loader');
 if(btn.disabled) return;
 btn.textContent='⏳...'; btn.disabled=true; loader.classList.add('show');
 try{
  let fd=new FormData(e.target);
  let r=await fetch('/api/login_public',{method:'POST',body:fd,cache:'no-store'});
  let j=await r.json();
  if(j.ok){ if(s.checked){localStorage.setItem('omaia_user',u.value);localStorage.setItem('omaia_pass',p.value);} location.replace('/dash?v=ping'); }
  else{ msg.textContent=j.msg||'خطأ'; btn.textContent='✨ دخول فوري نار'; btn.disabled=false; loader.classList.remove('show'); }
 }catch(err){ msg.textContent='خطأ شبكة'; btn.textContent='✨ دخول فوري نار'; btn.disabled=false; loader.classList.remove('show'); }
});
</script></body></html>"""
@app.route('/logout')
def lo(): session.clear(); return redirect('/login')
@app.route('/api/logout',methods=['POST'])
def api_logout(): session.clear(); return jsonify(ok=True)
@app.route('/dash')
@login_required
def dash():
    v=request.args.get('v','home')
    return layout(page_content(v),v)
@app.route('/api/page')
@login_required
def ap(): return page_content(request.args.get('v','home'))
@app.route('/api/search')
@login_required
def s():
    q=request.args.get('q','').strip()
    if not q: return jsonify([])
    like="%"+q+"%"; results=[]; dish_tbl=get_dish_table()
    try:
        for r in qall(f"SELECT * FROM {dish_tbl} WHERE ip LIKE ? OR dish_name LIKE ? OR location LIKE ? ORDER BY id DESC LIMIT 8",(like,like,like)):
            results.append({"title":r.get('dish_name') or r.get('ip') or 'صحن',"sub":r.get('ip',''),"page":"dishes"})
        for r in qall("SELECT * FROM towers WHERE name LIKE ? OR area LIKE ? ORDER BY id DESC LIMIT 12",(like,like)):
            results.append({"title":r.get('name',''),"sub":r.get('area',''),"page":"towers"})
    except: pass
    return jsonify(results[:15])
@app.route('/toggle_theme')
@login_required
def tt(): cur=session.get('theme','dark'); session['theme']='light' if cur=='dark' else 'dark'; return jsonify(ok=True)
@app.route('/add_dish',methods=['POST'])
@login_required
def ad():
    dish_tbl=get_dish_table(); ip=request.form.get('ip','').strip(); name=request.form.get('dish_name','').strip(); loc=request.form.get('location','').strip()
    if not ip: return "IP مطلوب",400
    if not is_valid_ip(ip): return "IP غير صالح",400
    ex=qone(f"SELECT * FROM {dish_tbl} WHERE ip=?",(ip,))
    if ex: qexec(f"UPDATE {dish_tbl} SET dish_name=?,location=? WHERE ip=?",(name,loc,ip)); log_action("تعديل صحن",f"{name}-{ip}"); return "ok"
    qexec(f"INSERT INTO {dish_tbl}(ip,location,dish_name) VALUES(?,?,?)",(ip,loc,name)); log_action("إضافة صحن",f"{name}-{ip}"); qexec("INSERT INTO notifications(title,msg,time,read) VALUES(?,?,?,0)",(f"📡 صحن {name}",f"{ip}",datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))); return "ok"
@app.route('/del_dish/<int:i>')
@login_required
def dd(i):
    if not is_manager(): return "ممنوع",403
    qexec(f"DELETE FROM {get_dish_table()} WHERE id=?",(i,)); log_action("حذف صحن",str(i)); return "ok"
@app.route('/add_tower',methods=['POST'])
@login_required
def at():
    try: la=float(request.form.get('lat','') or 35.13); ln=float(request.form.get('lng','') or 36.75)
    except: la=35.13; ln=36.75
    name=request.form.get('name',''); area=request.form.get('area','')
    qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",(name,area,la,ln)); log_action("إضافة ضيعة/برج",f"{name}-{area}"); return "ok"
@app.route('/del_tower/<int:i>')
@login_required
def dt(i):
    if not is_manager(): return "ممنوع",403
    qexec("DELETE FROM towers WHERE id=?",(i,)); log_action("حذف برج",str(i)); return "ok"
@app.route('/edit_tower/<int:i>',methods=['POST'])
@login_required
def et(i):
    if not is_manager(): return "ممنوع",403
    try: la=float(request.form.get('lat','') or 35.13); ln=float(request.form.get('lng','') or 36.75)
    except: la=35.13; ln=36.75
    qexec("UPDATE towers SET name=?,area=?,lat=?,lng=? WHERE id=?",(request.form.get('name',''),request.form.get('area',''),la,ln,i)); log_action("تعديل برج",str(i)); return "ok"
@app.route('/add_sub',methods=['POST'])
@login_required
def asub(): qexec("INSERT INTO subs(name,phone,note) VALUES(?,?,?)",(request.form.get('name',''),request.form.get('phone',''),request.form.get('note',''))); log_action("إضافة مشترك",request.form.get('name','')); return "ok"
@app.route('/del_sub/<int:i>')
@login_required
def dsub(i):
    if not is_manager(): return "ممنوع",403
    qexec("DELETE FROM subs WHERE id=?",(i,)); return "ok"
@app.route('/add_user',methods=['POST'])
@login_required
@role_required_manager
def au():
    ph=request.form.get('phone','').strip() or request.form.get('user_field','').strip()
    if not ph: return "رقم مطلوب",400
    if qone("SELECT * FROM users WHERE phone=?",(ph,)): return "موجود",400
    qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",(ph,generate_password_hash(request.form.get('password','1234')),request.form.get('role','tech'),ph)); log_action("إضافة يوزر",ph); return "ok"
@app.route('/change_pass',methods=['POST'])
@login_required
def cp():
    np=request.form.get('newpass','').strip()
    if not np: return "فارغة",400
    qexec("UPDATE users SET password=? WHERE phone=?",(generate_password_hash(np),session.get('phone'))); return "ok"

def page_content(v):
    req_lang=request.args.get('lang') or session.get('lang','ar'); dish_tbl=get_dish_table()
    def L(ar,en): return ar if req_lang=='ar' else en
    if v=='home':
        ns=(qone("SELECT COUNT(*) as c FROM subs") or {}).get('c',0); nd=(qone(f"SELECT COUNT(*) as c FROM {dish_tbl}") or {}).get('c',0); nt=(qone("SELECT COUNT(*) as c FROM towers") or {}).get('c',0)
        logs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 5")
        log_html="".join([f"<div style='display:flex;justify-content:space-between;padding:5px 7px;border-bottom:1px dashed #ffffff10;font-size:11px'><div><b style='color:#ffbe4d'>{esc(l.get('user_phone',''))}</b> {esc(l.get('action',''))} <small>{esc(l.get('detail',''))}</small></div><small style='color:#666'>{esc(l.get('time',''))}</small></div>" for l in logs])
        return f'''<div style='max-width:900px;margin:0 auto'><div style='display:grid;grid-template-columns:1fr 1fr;gap:8px'>
        <div class='card anim' onclick="loadPage('ping')" style='cursor:pointer;background:linear-gradient(135deg,#1e2a4a,#162040)'><h3 style='margin:0;font-size:12px'>ping</h3><h2 style='margin:4px 0 0;font-size:24px'>{nd}</h2><small style='color:#22c55e'>⚡ نار - كاش سريع</small></div>
        <div class='card anim' onclick="loadPage('towers')" style='cursor:pointer'><h3 style='margin:0'>🗼 {nt} منطقة</h3><small>كل سوريا</small></div>
        <div class='card anim' onclick="loadPage('map')" style='cursor:pointer'><h3 style='margin:0'>🗺 الخريطة</h3><small>بحث عالمي</small></div>
        <div class='card anim' onclick="loadPage('logs')" style='cursor:pointer'><h3 style='margin:0'>📜 السجل</h3><small>شغال ✅</small></div></div>
        <div class=card style='margin-top:8px'><h4 style='margin:0 0 6px'>📜 آخر النشاطات</h4>{log_html or 'لا يوجد'}<button class=btn-gold onclick="loadPage('logs')" style='width:100%;margin-top:6px'>عرض السجل</button></div>
        <div class=card style='text-align:center;background:linear-gradient(135deg,#0f172a,#1e293b);border:1px solid #22c55e33'><a href='https://wa.me/905344851045' target=_blank style='display:inline-block;background:#22c55e;color:#fff;padding:10px 18px;border-radius:10px;text-decoration:none;font-weight:800;font-size:13px'>💬 واتساب: +90 534 485 10 45</a></div></div>'''
    if v=='ping':
        return f'''<div style='max-width:800px;margin:0 auto'><div class=card style='background:linear-gradient(135deg,#0f172a,#1e293b);border:1px solid #22c55e33'><h3 style='margin:0'>📶 ping - نار ⚡ كاش سريع</h3><div style='display:flex;gap:6px;margin-top:8px;flex-wrap:wrap'><input id=pingIp placeholder='8.8.8.8' style='flex:1;min-width:160px;padding:10px;border-radius:8px;background:#0f1424;border:1px solid #ffffff20;color:#fff;font-family:monospace'><input id=pingPort placeholder='80' value='80' style='width:60px;padding:10px;border-radius:8px;background:#0f1424;border:1px solid #ffffff20;color:#fff'><button class=btn-gold onclick="doSinglePing()" style='padding:10px 14px;background:#22c55e;color:#fff'>ping</button></div><div id=pingResult style='margin-top:8px;min-height:40px;background:#0008;border-radius:8px;padding:10px;font-family:monospace;font-size:11px'>جاهز...</div></div></div><script>
        async function doSinglePing(){{let ip=document.getElementById('pingIp').value.trim(); if(!ip){{alert('IP');return;}} let out=document.getElementById('pingResult'); out.textContent='⏳ '+ip+'...'; out.style.color='#ffbe4d'; try{{let r=await fetch('/api/ping?ip='+encodeURIComponent(ip),{{cache:'no-store'}}); let j=await r.json(); out.textContent=j.out; out.style.color=j.ok?'#22c55e':'#ef4444';}}catch(e){{out.textContent='❌ '+e;}}}}
        </script>'''
    if v=='towers':
        rs=qall("SELECT * FROM towers ORDER BY area, name LIMIT 200")
        rows="".join([f"<div class='card anim' id='tower-{r['id']}' data-name='{esc(r['name'])}' data-area='{esc(r['area'] or '')}' style='display:flex;justify-content:space-between'><div><b>🗼 {esc(r['name'])}</b><br><small>{esc(r['area'] or '')}</small></div><div><button class=btn-del onclick=\"askDel('/del_tower/{r['id']}')\" style='padding:5px 7px'>🗑</button></div></div>" for r in rs])
        return f'''<div style='max-width:700px;margin:0 auto'><div class=card><h3>🗼 كل سوريا - {len(rs)} منطقة</h3><form data-ajax method=post action=/add_tower style='display:flex;gap:4px'><input name=name placeholder='اسم ضيعة' required style='flex:1'><input name=area placeholder='محافظة' style='flex:1'><button class=btn-gold>➕</button></form><input id=towerSearch placeholder='🔍 بحث...' oninput="searchTowers(this.value)" style='margin-top:6px'></div>{rows}<script>function searchTowers(q){{q=(q||'').toLowerCase();document.querySelectorAll('[id^=tower-]').forEach(c=>{{let t=(c.dataset.name+c.dataset.area).toLowerCase();c.style.display=t.includes(q)?'flex':'none';}});}}</script></div>'''
    if v=='map':
        towers=qall("SELECT * FROM towers")
        tj_json=json.dumps([{"name":t['name'],"area":t.get('area') or '',"lat":float(t.get('lat') or 35.13),"lng":float(t.get('lng') or 36.75)} for t in towers],ensure_ascii=False)
        return f'''<div class=card style='padding:8px'><div style='display:flex;gap:4px;margin-bottom:8px;flex-wrap:wrap'><input id=mapSearch placeholder='🔍 بحث بأي ضيعة بسوريا...' style='flex:1;min-width:200px;background:#1f2937;border:1px solid #22c55e33;color:#fff;padding:10px;border-radius:10px'><button class=btn-gold onclick="doMapSearch()" style='padding:10px'>🔍 بحث محلي</button><button class=btn-gold onclick="doGlobalSearch()" style='background:#8b5cf6;color:#fff;padding:10px'>🌍 بحث عالمي</button><button class=btn-gold onclick="locateMe()" style='background:#22c55e;color:#fff;padding:10px'>📍 موقعي</button></div><div id=map style='height:65vh;min-height:400px;border-radius:12px;background:#0f172a'></div><div id=mapResults style='margin-top:6px;max-height:120px;overflow:auto;background:#0f1424;border-radius:8px;padding:4px;font-size:12px'></div></div><script>
        let _towers={tj_json}; let _map=null;
        window.doMapSearch=function(){{let q=document.getElementById('mapSearch').value.trim().toLowerCase(); if(!q) return; let f=_towers.filter(t=>t.name.toLowerCase().includes(q)||t.area.toLowerCase().includes(q)); let res=document.getElementById('mapResults'); if(f.length>0){{_map.flyTo([f[0].lat,f[0].lng],13); res.innerHTML='<b>وجد '+f.length+'</b><br>'+f.slice(0,10).map(t=>'<div style="padding:6px;border-bottom:1px solid #ffffff10;cursor:pointer" onclick="_map.flyTo(['+t.lat+','+t.lng+'],15)">🗼 '+t.name+'</div>').join('');}} else {{res.innerHTML='لا يوجد محليا - جرب العالمي'; doGlobalSearch();}}}}
        window.doGlobalSearch=async function(){{let q=document.getElementById('mapSearch').value.trim(); if(!q) return; let res=document.getElementById('mapResults'); res.innerHTML='⏳ بحث عالمي...'; try{{let r=await fetch('https://nominatim.openstreetmap.org/search?format=json&q='+encodeURIComponent(q+' Syria')+'&limit=6'); let data=await r.json(); if(data.length==0){{let r2=await fetch('https://nominatim.openstreetmap.org/search?format=json&q='+encodeURIComponent(q)+'&limit=6'); data=await r2.json();}} if(data.length==0){{res.innerHTML='❌ لا يوجد'; return;}} res.innerHTML=data.map(p=>'<div style="padding:6px;border-bottom:1px solid #ffffff10;cursor:pointer" onclick="_map.flyTo(['+p.lat+','+p.lon+'],12)">📍 '+p.display_name.substring(0,60)+'</div>').join(''); _map.flyTo([data[0].lat,data[0].lon],11);}}catch(e){{res.innerHTML='❌ '+e;}}}}
        window.locateMe=function(){{if(navigator.geolocation){{navigator.geolocation.getCurrentPosition(p=>{{_map.flyTo([p.coords.latitude,p.coords.longitude],15);}});}}}}
        setTimeout(()=>{{_map=L.map('map').setView([34.8,38.2],7); let osm=L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:19}}).addTo(_map); let sat=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',{{maxZoom:19}}); L.control.layers({{"عادية":osm,"قمر":sat}}).addTo(_map); _towers.forEach(t=>{{L.marker([t.lat,t.lng]).addTo(_map).bindPopup('<b>'+t.name+'</b><br>'+t.area);}});}},200);
        document.getElementById('mapSearch').addEventListener('keydown',e=>{{if(e.key==='Enter'){{e.preventDefault(); doMapSearch();}}}});
        </script>'''
    if v=='logs':
        rs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 80")
        rows="".join([f"<div class='card anim' style='font-size:11px;border-right:3px solid #ffbe4d'><div><b style='color:#ffbe4d'>{esc(r.get('user_phone',''))}</b> {esc(r.get('action',''))} <small>{esc(r.get('detail',''))}</small></div><small style='color:#666'>{esc(r.get('time',''))}</small></div>" for r in rs])
        return f"<div style='max-width:800px;margin:0 auto'><div class=card><h3>📜 السجل ✅ {len(rs)}</h3></div>{rows or 'لا يوجد'}</div>"
    if v=='dishes':
        rs=qall(f"SELECT * FROM {get_dish_table()} ORDER BY id DESC LIMIT 80")
        rows_html="".join([f'<div class="card anim" style="display:flex;justify-content:space-between"><div><b>{esc(r.get("dish_name") or "صحن")}</b><br><small style="color:#ffbe4d">{esc(r.get("ip") or "")}</small></div><div><button class=btn-del onclick="askDel(\'/del_dish/{r["id"]}\')" style="padding:5px 7px">🗑</button></div></div>' for r in rs])
        return f'''<div style='max-width:800px;margin:0 auto'><div class=card><h3>📡 الصحون - {len(rs)}</h3><form data-ajax method=post action=/add_dish style='display:flex;gap:4px'><input name=dish_name placeholder='اسم' required style='flex:1'><input name=ip placeholder='IP' required style='flex:1'><button class=btn-gold>➕</button></form></div>{rows_html}</div>'''
    return "<div class=card>✅ نار ⚡ كاش سريع</div>"

def layout(c,v='home'):
    cur_user=qone("SELECT * FROM users WHERE phone=?",(session.get('phone') or '',)) or {}
    username_display=esc(cur_user.get('username') or cur_user.get('phone') or '')
    return f"""<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<link rel=stylesheet href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'>
<style>
*{{box-sizing:border-box;font-family:system-ui}}body{{margin:0;background:radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 60%, #070a1f 100%);color:#fff;overflow-x:hidden}}
.anim{{animation:fadeUp .12s ease}}@keyframes fadeUp{{from{{opacity:0}}to{{opacity:1}}}}
.top{{position:fixed;top:0;left:0;right:0;height:54px;background:#0f172af2;backdrop-filter:blur(10px);color:#fff;display:flex;align-items:center;justify-content:space-between;padding:0 10px;z-index:1003;border-bottom:1px solid #ffffff12}}
.sidebar{{position:fixed;right:0;top:0;width:265px;height:100%;background:#0f172a;color:#fff;z-index:1002;padding-top:60px;transform:translateX(110%);transition:transform .15s;overflow-y:auto}}
.sidebar.active{{transform:none}}
.sidebar a{{display:flex;gap:8px;padding:10px 12px;margin:3px 8px;color:#cbd5e1;text-decoration:none;border-radius:10px;background:#ffffff06}}
.sidebar a.active{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:800}}
#overlay{{position:fixed;inset:0;background:#0007;z-index:1001;display:none}}#overlay.show{{display:block}}
.main{{margin-top:60px;padding:8px;min-height:90vh}}
.card{{background:#1e2433;padding:10px;border-radius:10px;margin-bottom:6px;border:1px solid #ffffff12}}
input{{padding:10px;margin:2px 0;border-radius:8px;border:1px solid #ffffff12;width:100%;background:#ffffff07;color:#fff}}
.btn-gold{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;padding:6px 10px;border:0;border-radius:8px;font-weight:800;cursor:pointer}}
.btn-del{{background:#ef4444;color:#fff;padding:5px 8px;border:0;border-radius:7px}}
#delModal{{position:fixed;inset:0;background:#000a;backdrop-filter:blur(4px);display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:.12s;z-index:2000}}
#delModal.show{{opacity:1;pointer-events:auto}}
#delBox{{background:#1e2433;padding:16px;border-radius:12px;width:90%;max-width:360px}}
.wa-float{{position:fixed;bottom:14px;left:14px;z-index:1500;background:linear-gradient(135deg,#22c55e,#16a34a);color:#fff;width:50px;height:50px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:22px;box-shadow:0 4px 16px #0006;text-decoration:none}}
</style></head><body>
<div id=overlay onclick="toggleSb(false)"></div>
<div class=sidebar id=sb>
<div style='padding:0 12px 6px;border-bottom:1px solid #ffffff0a'><div style='font-weight:900;font-size:14px'>OMAIA <span style='color:#ffbe4d'>ISP</span> <small style='color:#22c55e'>⚡ نار</small></div><small style='color:#64748b'>{username_display}</small></div>
<a href="javascript:loadPage('home')" id=nav-home>🏠 الرئيسية</a>
<a href="javascript:loadPage('ping')" id=nav-ping style='background:#22c55e18;border:1px solid #22c55e33'>📶 ping <span style='background:#22c55e;color:#fff;padding:1px 5px;border-radius:5px;font-size:8px;margin-right:auto'>نار</span></a>
<a href="javascript:loadPage('towers')" id=nav-towers>🗼 </a>
<a href="javascript:loadPage('dishes')" id=nav-dishes>📡 الصحون</a>
<a href="javascript:loadPage('logs')" id=nav-logs>📜 السجل ✅</a>
<a href="javascript:logoutFast()">🚪 خروج</a>
</div>
<div class=top>
<span onclick="toggleSb()" style='font-size:20px;cursor:pointer;padding:4px 8px;background:#ffffff10;border-radius:8px'>☰</span>
<div style='font-weight:900;font-size:13px'>OMAIA <span style='color:#ffbe4d'>ISP</span> <small style='color:#22c55e'>⚡ كاش نار</small></div>
<div style='display:flex;gap:5px;align-items:center'>
<div id=notifBell onclick="toggleNotif()" style='position:relative;cursor:pointer;font-size:16px;padding:4px 7px;background:#ffffff08;border-radius:8px'>🔔<span id=notifCount style='display:none;position:absolute;top:-2px;right:-2px;background:#ef4444;color:#fff;font-size:8px;width:14px;height:14px;border-radius:50%;align-items:center;justify-content:center'>0</span></div>
<a href='https://wa.me/905344851045' target=_blank style='background:#22c55e;color:#fff;padding:5px 9px;border-radius:8px;text-decoration:none;font-size:13px'>💬</a>
</div>
</div>
<div id=notifPanel style='position:fixed;top:58px;left:8px;max-width:320px;width:88%;background:#1e2433;border:1px solid #ffffff12;border-radius:10px;z-index:2000;display:none;max-height:60vh;overflow:auto'></div>
<div class=main id=mn>{c}</div>
<div id=delModal><div id=delBox><h3 style='text-align:center;margin:0'>حذف؟</h3><div style='display:flex;gap:6px;margin-top:10px'><button onclick="closeDel()" style='flex:1;padding:7px;border-radius:7px'>لا</button><button id=delYes style='flex:1;padding:7px;border-radius:7px;background:#ef4444;color:#fff;border:0'>نعم</button></div></div></div>
<a href='https://wa.me/905344851045' target=_blank class=wa-float>💬</a>
<script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>
<script>
let cur='{v}';
// كاش خارق السرعة - نار ⚡
const CACHE_KEY='omaia_ultra_fast_v4';
let pageCache={{}};
try{{pageCache=JSON.parse(localStorage.getItem(CACHE_KEY)||'{{}}');}}catch(e){{pageCache={{}};}}
function saveCache(){{try{{localStorage.setItem(CACHE_KEY,JSON.stringify(pageCache));}}catch(e){{}}}}

function toggleSb(f){{let sb=document.getElementById('sb'),ov=document.getElementById('overlay'); let o=f!==undefined?f:!sb.classList.contains('active'); sb.classList.toggle('active',o); ov.classList.toggle('show',o);}}

async function loadPage(v,force=false,push=true){{
  if(push && cur!==v){{try{{history.pushState({{page:v}},'', '/dash?v='+v);}}catch(e){{}}}}
  cur=v;
  let mn=document.getElementById('mn');
  document.querySelectorAll('.sidebar a').forEach(a=>a.classList.remove('active'));
  let nv=document.getElementById('nav-'+v); if(nv) nv.classList.add('active');
  toggleSb(false);

  // عرض فوري من الكاش - 0 ثانية
  if(!force && pageCache[v]){{
    mn.innerHTML=pageCache[v];
    bind(); execScripts();
    // تحديث خفيف بالخلفية بدون ما يعلق الواجهة
    fetch('/api/page?v='+v,{{cache:'no-store'}}).then(r=>r.text()).then(h=>{{if(h && h.length>50){{pageCache[v]=h; saveCache();}}}}).catch(()=>{{}});
    return;
  }}

  // لا يوجد كاش - حمل فوري
  mn.innerHTML='<div class=card style="text-align:center;padding:16px;font-size:13px"> جاري التحميل ...</div>';
  try{{
    let r=await fetch('/api/page?v='+v,{{cache:'no-store'}});
    let h=await r.text();
    pageCache[v]=h; saveCache();
    mn.innerHTML=h; bind(); execScripts();
  }}catch(e){{mn.innerHTML='<div class=card>❌ '+e+'<br><button class=btn-gold onclick="loadPage(\\''+v+'\\',true)">↻</button></div>';}}
}}

function execScripts(){{document.getElementById('mn').querySelectorAll('script').forEach(s=>{{try{{(0,eval)(s.textContent)}}catch(e){{}}}});}}
function bind(){{
  document.querySelectorAll('form[data-ajax]').forEach(f=>{{
    if(f.dataset.bound) return;
    f.dataset.bound='1';
    f.onsubmit=async e=>{{
      e.preventDefault();
      let btn=f.querySelector('button'); if(btn){{btn.textContent='⏳'; btn.disabled=true;}}
      try{{let r=await fetch(f.action,{{method:'POST',body:new FormData(f)}}); if(r.ok){{delete pageCache[cur]; await loadPage(cur,true);}} else {{let t=await r.text(); alert(t); if(btn){{btn.textContent='➕'; btn.disabled=false;}}}}}}catch(err){{alert(err);}}
    }};
  }});
}}
function askDel(u){{window._delUrl=u;document.getElementById('delModal').classList.add('show');}}
function closeDel(){{document.getElementById('delModal').classList.remove('show');}}
document.getElementById('delYes').onclick=async()=>{{if(window._delUrl){{await fetch(window._delUrl); delete pageCache[cur]; closeDel(); loadPage(cur,true);}}}};
window.toggleNotif=async function(){{
  let p=document.getElementById('notifPanel'); p.style.display=p.style.display==='block'?'none':'block';
  if(p.style.display==='block'){{
    try{{let r=await fetch('/api/notifications'); let j=await r.json(); let h='<div style="padding:8px"><div style="display:flex;justify-content:space-between"><b>🔔 '+j.unread+'</b><button onclick="readAllNotif()" style="background:#ffbe4d;border:0;padding:3px 7px;border-radius:5px;font-size:10px">مقروء</button></div><hr style="border-color:#ffffff0f;margin:4px 0">'; j.rows.forEach(n=>{{h+='<div style="padding:5px;border-bottom:1px solid #ffffff08"><b style="color:#ffbe4d;font-size:11px">'+n.title+'</b><br><small style="color:#ccc;font-size:11px">'+n.msg+'</small><br><small style="color:#666;font-size:10px">'+n.time+'</small></div>';}}); h+='</div>'; p.innerHTML=h;}}catch(e){{}}
  }}
}}
window.readAllNotif=async function(){{try{{await fetch('/api/notifications/read',{{method:'POST'}});}}catch(e){{}} document.getElementById('notifCount').style.display='none'; document.getElementById('notifPanel').style.display='none';}}
async function loadNotif(){{try{{let r=await fetch('/api/notifications'); let j=await r.json(); let c=document.getElementById('notifCount'); if(j.unread>0){{c.textContent=j.unread>99?'99+':j.unread; c.style.display='flex';}} else {{c.style.display='none';}}}}catch(e){{}}}}
loadNotif(); setInterval(loadNotif,25000);
window.logoutFast=async function(){{try{{await fetch('/api/logout',{{method:'POST'}});}}catch(e){{}} localStorage.removeItem(CACHE_KEY); localStorage.clear(); location.replace('/login');}};
bind(); execScripts();
</script>
</body></html>"""

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)), debug=False, threaded=True)
