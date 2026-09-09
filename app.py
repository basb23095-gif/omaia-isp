from flask import Flask, request, redirect, session, jsonify, Response
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, html, ipaddress, subprocess, json, socket, platform, io, csv, datetime, re, time
import psycopg2, psycopg2.extras
import sqlite3

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY","omia-sec-2026-CHANGE-ME")
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(days=30)
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
PG_URL = DATABASE_URL.replace("postgres://","postgresql://",1) if DATABASE_URL.startswith("postgres://") else DATABASE_URL
USE_PG = bool(DATABASE_URL)

_pg = None
_last_check = 0
_dish_cache = {"name": None, "ts": 0}
_cnt_cache = {}
_stats_cache = {"data": None, "ts": 0}

def esc(s): return html.escape(str(s or ''), quote=True)

def db():
    global _pg, _last_check
    if USE_PG:
        now = time.time()
        if _pg and now - _last_check < 30:
            return _pg
        if _pg:
            try:
                cur=_pg.cursor();cur.execute("SELECT 1");cur.close()
                _last_check=now
                return _pg
            except:
                try:_pg.close()
                except:pass
                _pg=None
        try:
            _pg=psycopg2.connect(PG_URL,sslmode='require',connect_timeout=3)
            _pg.autocommit=True
            _last_check=now
            return _pg
        except: pass
    try:
        c=sqlite3.connect("omia.db",check_same_thread=False,timeout=5)
        c.row_factory=sqlite3.Row
        return c
    except:
        c=sqlite3.connect(":memory:",check_same_thread=False)
        c.row_factory=sqlite3.Row
        return c

def cc(c):
    if not USE_PG:
        try:c.close()
        except:pass

def qall(q,a=()):
    c=db()
    try:
        if USE_PG:
            cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(q.replace("?","%s"),a)
            rs=[dict(r) for r in cur.fetchall()]
            cur.close()
            return rs
        else:
            rs=[dict(r) for r in c.execute(q,a).fetchall()]
            cc(c)
            return rs
    except:
        cc(c)
        return []

def qone(q,a=()):
    r=qall(q,a)
    return r[0] if r else None

def qexec(q,a=()):
    c=db()
    try:
        if USE_PG:
            cur=c.cursor()
            cur.execute(q.replace("?","%s"),a)
            cur.close()
        else:
            c.execute(q,a)
            c.commit()
            cc(c)
        _cnt_cache.clear()
        _stats_cache["ts"]=0
    except:
        cc(c)

def get_dish_table():
    now=time.time()
    if _dish_cache["name"] and now - _dish_cache["ts"] < 120:
        return _dish_cache["name"]
    if USE_PG:
        try:
            c=db(); cur=c.cursor()
            cur.execute("SELECT to_regclass('public.ips')")
            r=cur.fetchone(); cur.close()
            tbl="ips" if r and r[0] else "dish_ips"
            _dish_cache["name"]=tbl; _dish_cache["ts"]=now
            return tbl
        except: return "dish_ips"
    return "dish_ips"

def fast_count(tbl, ttl=20):
    now=time.time()
    if tbl in _cnt_cache:
        v,ts=_cnt_cache[tbl]
        if now-ts < ttl: return v
    c=(qone(f"SELECT COUNT(*) c FROM {tbl}") or {}).get('c',0)
    _cnt_cache[tbl]=(c,now)
    return c

def get_home_stats():
    now=time.time()
    if _stats_cache["data"] and now - _stats_cache["ts"] < 20:
        return _stats_cache["data"]
    tbl=get_dish_table()
    try:
        row=qone(f"SELECT (SELECT COUNT(*) FROM subs) as subs, (SELECT COUNT(*) FROM towers) as towers, (SELECT COUNT(*) FROM ledger) as ledger, (SELECT COUNT(*) FROM {tbl}) as dishes")
        if row:
            _stats_cache["data"]=row; _stats_cache["ts"]=now
            return row
    except: pass
    return {"subs":fast_count("subs"),"towers":fast_count("towers"),"ledger":fast_count("ledger"),"dishes":fast_count(tbl)}

def init():
    ss=[
    "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,username TEXT)",
    "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,note TEXT)",
    "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,amount REAL,note TEXT,currency TEXT)",
    "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,dish_name TEXT)",
    "CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,area TEXT,lat REAL,lng REAL)",
    "CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,user_phone TEXT,action TEXT,detail TEXT,time TEXT)",
    "CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,msg TEXT,time TEXT,read INTEGER DEFAULT 0)",
    "CREATE TABLE IF NOT EXISTS ips(id SERIAL PRIMARY KEY, ip TEXT, location TEXT, dish_name TEXT, created_at TIMESTAMP DEFAULT NOW())"
    ]
    if USE_PG:
        for i in range(1,7): ss[i]=ss[i].replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY")
    for s in ss: qexec(s)
    if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",('05344851045',generate_password_hash('admin2024'),'manager','admin'))
    if not qone("SELECT * FROM towers WHERE name=?",('نقطة حماة الرئيسية',)):
        qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",('نقطة حماة الرئيسية','حماة',35.1318,36.7578))
init()

def login_required(f):
    @wraps(f)
    def w(*a,**kw):
        if not session.get('phone'):return redirect('/login')
        return f(*a,**kw)
    return w
def is_manager():
    u=qone("SELECT * FROM users WHERE phone=?",(session.get('phone') or '',))
    return (u.get('role') or '').lower()=='manager' if u else False
def role_required_manager(f):
    @wraps(f)
    def w(*a,**kw):
        if not is_manager():return "ممنوع",403
        return f(*a,**kw)
    return w
def is_valid_ip(ip):
    ip=ip.strip()
    if not ip:return False
    try:ipaddress.ip_address(ip);return True
    except:return len(ip)>=7 and '.' in ip

@app.route('/ping')
@app.route('/health')
def public_ping():
    try:
        c=db();cur=c.cursor();cur.execute("SELECT 1");cur.close()
        return jsonify(ok=True, pg=True, time=datetime.datetime.now().isoformat(), table=get_dish_table())
    except Exception as e:
        return jsonify(ok=True, pg=False, error=str(e))

@app.route('/api/ping')
@login_required
def api_ping():
    ip=request.args.get('ip','').strip()
    if not ip:return jsonify(ok=False,out='لا يوجد IP')
    if not is_valid_ip(ip):return jsonify(ok=False,out='IP غير صالح')
    # نار: 3 بورتات بس ومهلة 0.5 ثانية
    for port in [80,8291,8728]:
        s=None
        try:
            s=socket.socket(socket.AF_INET,socket.SOCK_STREAM);s.settimeout(0.5)
            if s.connect_ex((ip,port))==0:
                s.close()
                return jsonify(ok=True,out=f'✅ متصل - {ip}:{port} مفتوح',port=port,method='tcp')
            s.close()
        except:
            try:
                if s: s.close()
            except: pass
    return jsonify(ok=False,out=f'❌ {ip} لا يرد')

@app.route('/api/ping_tcp')
@login_required
def api_ping_tcp():
    ip=request.args.get('ip','').strip()
    try: port=int(request.args.get('port','80') or 80)
    except: port=80
    if not is_valid_ip(ip):return jsonify(ok=False,out='IP غير صالح')
    s=None
    try:
        s=socket.socket(socket.AF_INET,socket.SOCK_STREAM);s.settimeout(1);r=s.connect_ex((ip,port));s.close()
        return jsonify(ok=r==0,out=f'✅ {ip}:{port} مفتوح' if r==0 else f'❌ {ip}:{port} مغلق')
    except Exception as e:
        try:
            if s: s.close()
        except: pass
        return jsonify(ok=False,out=f'❌ {e}')

@app.route('/api/notifications')
@login_required
def api_noti():
    rows=qall("SELECT * FROM notifications ORDER BY id DESC LIMIT 20")
    unread=qone("SELECT COUNT(*) c FROM notifications WHERE read=0")
    return jsonify(rows=rows,unread=unread.get('c',0) if unread else 0)

@app.route('/api/notifications/read',methods=['POST'])
@login_required
def api_noti_read():qexec("UPDATE notifications SET read=1");return jsonify(ok=True)

@app.route('/api/network_status')
@login_required
def api_network():
    st=get_home_stats()
    return jsonify(dishes=st.get('dishes',0),towers=st.get('towers',0),subs=st.get('subs',0))

@app.route('/toggle_lang')
@login_required
def toggle_lang_route():
    cur=session.get('lang','ar');session['lang']='en' if cur=='ar' else 'ar';return jsonify(ok=True,lang=session['lang'])

@app.route('/api/login_public',methods=['POST'])
def api_login_public():
    uin=request.form.get('userin','').strip();pw=request.form.get('password','')
    u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
    if u and check_password_hash(u['password'],pw):
        session['phone']=u['phone'];session['username']=u.get('username') or u['phone'];session.permanent=True
        return jsonify(ok=True)
    return jsonify(ok=False,msg='خطأ بالدخول'),401

@app.route('/api/export/<tbl>')
@login_required
def api_export(tbl):
    output=io.StringIO();w=csv.writer(output);dish_tbl=get_dish_table()
    if tbl=='dishes':
        rows=qall(f"SELECT * FROM {dish_tbl} ORDER BY id DESC");w.writerow(['ID','اسم الصحن','IP','الموقع'])
        for r in rows:w.writerow([r['id'],r.get('dish_name',''),r.get('ip',''),r.get('location','')])
    elif tbl=='subs':
        rows=qall("SELECT * FROM subs ORDER BY id DESC");w.writerow(['ID','الاسم','رقم','ملاحظة'])
        for r in rows:w.writerow([r['id'],r.get('name',''),r.get('phone',''),r.get('note','')])
    elif tbl=='users':
        rows=qall("SELECT phone,username,role FROM users ORDER BY phone DESC");w.writerow(['يوزر/رقم','اسم المستخدم','الرتبة'])
        for r in rows:w.writerow([r.get('phone',''),r.get('username',''),r.get('role','')])
    elif tbl=='towers':
        rows=qall("SELECT * FROM towers ORDER BY id DESC");w.writerow(['ID','اسم البرج','المنطقة','lat','lng'])
        for r in rows:w.writerow([r['id'],r.get('name',''),r.get('area',''),r.get('lat',''),r.get('lng','')])
    elif tbl=='logs':
        rows=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 1000");w.writerow(['ID','المستخدم','العملية','التفاصيل','الوقت'])
        for r in rows:w.writerow([r['id'],r.get('user_phone',''),r.get('action',''),r.get('detail',''),r.get('time','')])
    else:w.writerow(['ID'])
    return Response(output.getvalue(),mimetype='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename={tbl}.csv'})

@app.route('/')
def ix():return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login')
def login():
    return """<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<style>*{box-sizing:border-box;font-family:system-ui}body{margin:0;min-height:100vh;background:radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 55%, #070a1f 100%);display:flex;flex-direction:column;align-items:center;justify-content:center;color:#fff}
.card{background:linear-gradient(180deg, #222b45cc, #1a2035cc);border:1px solid #ffffff18;padding:26px;border-radius:22px;width:92%;max-width:380px}
input{width:100%;padding:14px;margin:9px 0;background:#0f1424;border:1px solid #ffffff22;color:#fff;border-radius:14px}
.btn{width:100%;padding:14px;border:0;border-radius:14px;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:900;font-size:17px;cursor:pointer}
.support{margin-top:14px;text-align:center;font-size:13px;color:#9ca3af}.support a{color:#22c55e;text-decoration:none;font-weight:800}
</style></head><body>
<div style='font-size:30px;font-weight:900;margin-bottom:14px'>OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<div class=card><form id=loginForm><input name=userin id=userin placeholder='📱 رقم / يوزر' required><input name=password id=password type=password placeholder='🔑 كلمة السر' required><label style='display:flex;gap:8px;font-size:13px;color:#aaa;margin:8px 0'><input type=checkbox id=savePass style='width:auto'> حفظ</label><button class=btn id=loginBtn>✨ دخول فوري</button><div id=msg style='text-align:center;margin-top:8px;color:#ff6b6b;font-size:13px'></div></form>
<div class=support>🛠 الدعم الفني<br><a href='https://wa.me/905345851045' target=_blank>💬 واتساب +90 534 485 10 45</a><br><a href='https://instagram.com/af_20_1999' target=_blank>📸 Instagram: af_20_1999</a></div></div>
<script>
let u=document.getElementById('userin'), p=document.getElementById('password'), s=document.getElementById('savePass');
let su=localStorage.getItem('omaia_user'), sp=localStorage.getItem('omaia_pass');
if(su){u.value=su; if(sp){p.value=sp; s.checked=true;}}
document.getElementById('loginForm').addEventListener('submit',async e=>{
 e.preventDefault();
 let btn=document.getElementById('loginBtn'), msg=document.getElementById('msg');
 if(btn.disabled) return;
 btn.textContent='⏳ جاري الدخول...'; btn.disabled=true;
 try{
  let fd=new FormData(e.target);
  let r=await fetch('/api/login_public',{method:'POST',body:fd});
  let j=await r.json();
  if(j.ok){ if(s.checked){localStorage.setItem('omaia_user',u.value);localStorage.setItem('omaia_pass',p.value);} location.replace('/dash?v=home'); }
  else{ msg.textContent=j.msg||'خطأ'; btn.textContent='✨ دخول فوري'; btn.disabled=false; }
 }catch(err){ msg.textContent='خطأ شبكة'; btn.textContent='✨ دخول فوري'; btn.disabled=false; }
});
</script></body></html>"""

@app.route('/logout')
def lo():session.clear();return redirect('/login')
@app.route('/api/logout',methods=['POST'])
def api_logout():session.clear();return jsonify(ok=True)
@app.route('/dash')
@login_required
def dash():v=request.args.get('v','home');return layout(page_content(v),v)
@app.route('/api/page')
@login_required
def ap():return page_content(request.args.get('v','home'))
@app.route('/api/search')
@login_required
def s():
    q=request.args.get('q','').strip()
    if not q:return jsonify([])
    like="%"+q+"%";results=[];dish_tbl=get_dish_table()
    try:
        for r in qall(f"SELECT * FROM {dish_tbl} WHERE ip LIKE? OR dish_name LIKE? OR location LIKE? ORDER BY id DESC LIMIT 20",(like,like,like)):results.append({"title":r.get('dish_name') or r.get('ip') or 'صحن',"sub":r.get('ip',''),"page":"dishes"})
        for r in qall("SELECT * FROM subs WHERE name LIKE? OR phone LIKE? ORDER BY id DESC LIMIT 15",(like,like)):results.append({"title":r.get('name',''),"sub":r.get('phone',''),"page":"subs"})
        for r in qall("SELECT * FROM towers WHERE name LIKE? OR area LIKE? ORDER BY id DESC LIMIT 15",(like,like)):results.append({"title":r.get('name',''),"sub":r.get('area',''),"page":"towers"})
        for r in qall("SELECT * FROM users WHERE phone LIKE? OR username LIKE? LIMIT 10",(like,like)):results.append({"title":r.get('username') or r.get('phone',''),"sub":r.get('phone',''),"page":"settings"})
        for r in qall("SELECT * FROM ledger WHERE name LIKE? OR note LIKE? ORDER BY id DESC LIMIT 10",(like,like)):results.append({"title":r.get('name',''),"sub":str(r.get('amount','')),"page":"ledger"})
    except:pass
    return jsonify(results[:25])

@app.route('/toggle_theme')
@login_required
def tt():cur=session.get('theme','dark');session['theme']='light' if cur=='dark' else 'dark';return jsonify(ok=True)
@app.route('/add_dish',methods=['POST'])
@login_required
def ad():
    dish_tbl=get_dish_table();ip=request.form.get('ip','').strip();name=request.form.get('dish_name','').strip();loc=request.form.get('location','').strip()
    if not ip:return "IP مطلوب",400
    if not is_valid_ip(ip):return "IP غير صالح",400
    ex=qone(f"SELECT * FROM {dish_tbl} WHERE ip=?",(ip,))
    if ex:
        qexec(f"UPDATE {dish_tbl} SET dish_name=?,location=? WHERE ip=?",(name,loc,ip))
        return "ok updated"
    qexec(f"INSERT INTO {dish_tbl}(ip,location,dish_name) VALUES(?,?,?)",(ip,loc,name))
    return "ok"
@app.route('/edit_dish/<int:i>',methods=['POST'])
@login_required
def ed(i):
    if not is_manager():return "ممنوع",403
    qexec(f"UPDATE {get_dish_table()} SET dish_name=?,ip=?,location=? WHERE id=?",(request.form.get('dish_name',''),request.form.get('ip',''),request.form.get('location',''),i));return "ok"
@app.route('/del_dish/<int:i>')
@login_required
def dd(i):
    if not is_manager():return "ممنوع",403
    qexec(f"DELETE FROM {get_dish_table()} WHERE id=?",(i,));return "ok"
@app.route('/add_tower',methods=['POST'])
@login_required
def at():
    try:la=float(request.form.get('lat') or 35.1318);ln=float(request.form.get('lng') or 36.7578)
    except:la=35.1318;ln=36.7578
    qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",(request.form.get('name',''),request.form.get('area',''),la,ln));return "ok"
@app.route('/del_tower/<int:i>')
@login_required
def dt(i):
    if not is_manager():return "ممنوع",403
    qexec("DELETE FROM towers WHERE id=?",(i,));return "ok"
@app.route('/edit_tower/<int:i>',methods=['POST'])
@login_required
def et(i):
    if not is_manager():return "ممنوع",403
    try:la=float(request.form.get('lat') or 35.1318);ln=float(request.form.get('lng') or 36.7578)
    except:la=35.1318;ln=36.7578
    qexec("UPDATE towers SET name=?,area=?,lat=?,lng=? WHERE id=?",(request.form.get('name',''),request.form.get('area',''),la,ln,i));return "ok"
@app.route('/add_sub',methods=['POST'])
@login_required
def asub():qexec("INSERT INTO subs(name,phone,note) VALUES(?,?,?)",(request.form.get('name',''),request.form.get('phone',''),request.form.get('note','')));return "ok"
@app.route('/del_sub/<int:i>')
@login_required
def dsub(i):
    if not is_manager():return "ممنوع",403
    qexec("DELETE FROM subs WHERE id=?",(i,));return "ok"
@app.route('/edit_sub/<int:i>',methods=['POST'])
@login_required
def esub(i):
    if not is_manager():return "ممنوع",403
    qexec("UPDATE subs SET name=?,phone=?,note=? WHERE id=?",(request.form.get('name',''),request.form.get('phone',''),request.form.get('note',''),i));return "ok"
@app.route('/add_ledger',methods=['POST'])
@login_required
def al():
    try:amt=float(request.form.get('amount') or 0)
    except:amt=0
    qexec("INSERT INTO ledger(name,amount,note,currency) VALUES(?,?,?,?)",(request.form.get('name',''),amt,request.form.get('note',''),request.form.get('currency','USD')));return "ok"
@app.route('/del_ledger/<int:i>')
@login_required
def dll(i):
    if not is_manager():return "ممنوع",403
    qexec("DELETE FROM ledger WHERE id=?",(i,));return "ok"
@app.route('/edit_ledger/<int:i>',methods=['POST'])
@login_required
def el(i):
    if not is_manager():return "ممنوع",403
    try:amt=float(request.form.get('amount') or 0)
    except:amt=0
    qexec("UPDATE ledger SET name=?,amount=?,note=?,currency=? WHERE id=?",(request.form.get('name',''),amt,request.form.get('note',''),request.form.get('currency','USD'),i));return "ok"
@app.route('/add_user',methods=['POST'])
@login_required
@role_required_manager
def au():
    ph=request.form.get('phone','').strip() or request.form.get('user_field','').strip()
    if not ph:return "رقم مطلوب",400
    if qone("SELECT * FROM users WHERE phone=?",(ph,)):return "موجود مسبقاً",400
    qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",(ph,generate_password_hash(request.form.get('password','1234')),request.form.get('role','tech'),ph));return "ok"
@app.route('/edit_user',methods=['POST'])
@login_required
@role_required_manager
def eu():
    old=request.form.get('old_phone','').strip();new_ph=request.form.get('phone','').strip() or request.form.get('user_field','').strip()
    new_role=request.form.get('role','tech');new_pass=request.form.get('password','').strip()
    if not old:return "خطأ",400
    if new_pass:qexec("UPDATE users SET phone=?,username=?,role=?,password=? WHERE phone=?",(new_ph,new_ph,new_role,generate_password_hash(new_pass),old))
    else:qexec("UPDATE users SET phone=?,username=?,role=? WHERE phone=?",(new_ph,new_ph,new_role,old))
    if session.get('phone')==old:session['phone']=new_ph
    return "ok"
@app.route('/del_user/<ph>')
@login_required
@role_required_manager
def du(ph):
    if ph=='05344851045':return "ممنوع حذف المدير",400
    qexec("DELETE FROM users WHERE phone=?",(ph,));return "ok"
@app.route('/change_pass',methods=['POST'])
@login_required
def cp():
    np=request.form.get('newpass','').strip()
    if not np:return "فارغة",400
    qexec("UPDATE users SET password=? WHERE phone=?",(generate_password_hash(np),session.get('phone')));return "ok"

def page_content(v):
    req_lang=request.args.get('lang') or session.get('lang','ar')
    dish_tbl=get_dish_table()
    def L(ar,en): return ar if req_lang=='ar' else en
    if v=='home':
        st=get_home_stats(); ns=st.get('subs',0);nd=st.get('dishes',0);nt=st.get('towers',0);nl=st.get('ledger',0)
        logs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 4")
        log_html="".join([f"<div style='display:flex;justify-content:space-between;padding:7px 10px;border-bottom:1px dashed #ffffff10'><div><b style='color:#ffbe4d'>{esc(l.get('user_phone',''))}</b> {esc(l.get('action',''))}</div><small style='color:#777'>{esc(l.get('time',''))}</small></div>" for l in logs])
        return f'''<div style='max-width:900px;margin:0 auto'><div style='display:grid;grid-template-columns:1fr 1fr;gap:14px'>
        <div class='card' onclick="loadPage('subs')" style='cursor:pointer'><h3 style='margin:0;color:#aab4d0;font-size:13px'>{L('المشتركين','Subs')}</h3><h2 style='margin:6px 0 0;font-size:36px'>{ns}</h2></div>
        <div class='card' onclick="loadPage('dishes')" style='cursor:pointer'><h3 style='margin:0;color:#aab4d0;font-size:13px'>{L('الصحون','Dishes')}</h3><h2 style='margin:6px 0 0;font-size:36px'>{nd}</h2></div>
        <div class='card' onclick="loadPage('towers')" style='cursor:pointer'><h3 style='margin:0;color:#aab4d0;font-size:13px'>{L('الأبراج','Towers')}</h3><h2 style='margin:6px 0 0;font-size:36px'>{nt}</h2></div>
        <div class='card' onclick="loadPage('ledger')" style='cursor:pointer'><h3 style='margin:0;color:#aab4d0;font-size:13px'>{L('الحسابات','Accounts')}</h3><h2 style='margin:6px 0 0;font-size:36px'>{nl}</h2></div></div>
        <div class=card style='margin-top:14px'><h4>📊 التقارير - ☁ {dish_tbl}</h4><a href='/api/export/dishes' class=btn-gold style='text-decoration:none;padding:8px 12px;background:#22c55e;color:#fff'>📗 Excel</a></div>
        <div class=card><h4>📜 آخر النشاطات</h4>{log_html or 'لا يوجد'}<button class=btn-gold onclick="loadPage('logs')" style='width:100%;margin-top:8px'>عرض السجل</button></div></div>'''
    if v=='ping':
        return f'''<div style='max-width:800px;margin:0 auto'><div class=card><h3>📶 بنج - نار 🔥 - {dish_tbl}</h3>
        <div style='display:flex;gap:8px;margin-top:10px'><input id=pingIp placeholder='192.168.1.1' style='flex:1;padding:12px;background:#0f1424;border:1px solid #ffffff20;color:#fff;border-radius:10px'><button class=btn-gold onclick="doSinglePing()">Ping</button></div>
        <div id=pingResult style='margin-top:10px;padding:12px;background:#0008;border-radius:10px;min-height:50px'>جاهز...</div>
        </div><div class=card><h4>صحون سريعة</h4><div id=quickDishes>⏳</div></div></div><script>
        async function doSinglePing(){{let ip=document.getElementById('pingIp').value.trim(); if(!ip) return; let o=document.getElementById('pingResult'); o.textContent='⏳ '+ip+'...'; try{{let r=await fetch('/api/ping?ip='+encodeURIComponent(ip)); let j=await r.json(); o.textContent=j.out; o.style.color=j.ok?'#22c55e':'#ef4444';}}catch(e){{o.textContent='❌ '+e;}}}}
        (async()=>{{try{{let r=await fetch('/api/search?q=192'); let d=await r.json(); let h=''; d.filter(x=>x.page==='dishes').slice(0,6).forEach(x=>{{h+='<div style="display:flex;justify-content:space-between;padding:8px;border-bottom:1px solid #ffffff08"><span>'+x.sub+'</span><button class=btn-gold onclick="document.getElementById(\\'pingIp\\').value=\\''+x.sub+'\\';doSinglePing()">Ping</button></div>';}}); document.getElementById('quickDishes').innerHTML=h;}}catch(e){{}}}})();
        </script>'''
    if v=='dishes':
        rs=qall(f"SELECT * FROM {dish_tbl} ORDER BY id DESC LIMIT 300")
        rows=""
        for r in rs:
            dn=esc(r.get('dish_name') or 'صحن'); ip=esc(r.get('ip') or ''); loc=esc(r.get('location') or ''); rid=r['id']
            rows+=f'<div class="card" id="dish-{rid}" data-name="{dn}" data-ip="{ip}" data-loc="{loc}" style="display:flex;justify-content:space-between"><div><b>{dn}</b><br><span style="color:#ffbe4d;font-family:monospace">🌐 {ip}</span><br><small style="color:#888">{loc}</small></div><div style="display:flex;gap:6px"><button class=btn-gold onclick="quickPingD({rid})" style="padding:7px 10px">📶</button><button class=btn-gold onclick="editDish({rid})" style="padding:7px 9px">✏</button><button class=btn-del onclick="askDel(\'/del_dish/{rid}\')" style="padding:7px 9px">🗑</button></div></div>'
        return f'''<div style='max-width:900px;margin:0 auto'><div class=card><h3>📡 الصحون - {len(rs)}</h3><form data-ajax method=post action=/add_dish style='display:flex;gap:6px;flex-wrap:wrap'><input name=dish_name placeholder='اسم' required style='flex:1'><input name=ip placeholder='IP' required style='flex:1'><input name=location placeholder='موقع' style='flex:1'><button class=btn-gold>➕ حفظ</button></form><input id=searchBox placeholder='🔍 بحث...' oninput="searchDishes(this.value)" style='margin-top:10px;width:100%;padding:12px;border-radius:12px;background:#0f1424;border:1px solid #ffffff18'></div><div id=dl>{rows}</div></div><script>
        function editDish(id){{let c=document.getElementById('dish-'+id); let m=document.getElementById('editModal'); m.classList.add('show'); document.getElementById('editBody').innerHTML='<input id=ed_n value="'+c.dataset.name+'" style="width:100%;padding:10px;margin:4px 0"><input id=ed_ip value="'+c.dataset.ip+'" style="width:100%;padding:10px;margin:4px 0"><input id=ed_l value="'+c.dataset.loc+'" style="width:100%;padding:10px;margin:4px 0"><button onclick="saveDish('+id+')" class=btn-gold style="width:100%;padding:10px">💾 حفظ</button>';}}
        function saveDish(id){{let nn=document.getElementById('ed_n').value; let ii=document.getElementById('ed_ip').value; let ll=document.getElementById('ed_l').value; fetch('/edit_dish/'+id,{{method:'POST',body:new URLSearchParams({{dish_name:nn,ip:ii,location:ll}})}}).then(()=>{{closeEditModal();loadPage('dishes',true);}});}}
        function quickPingD(id){{let c=document.getElementById('dish-'+id); loadPage('ping'); setTimeout(()=>{{let i=document.getElementById('pingIp'); if(i){{i.value=c.dataset.ip; doSinglePing();}}}},300);}}
        function searchDishes(q){{q=(q||'').toLowerCase(); document.querySelectorAll('[id^=dish-]').forEach(card=>{{let t=(card.dataset.name+card.dataset.ip+card.dataset.loc).toLowerCase(); card.style.display=t.includes(q)?'flex':'none';}});}}
        </script>'''
    if v=='towers':
        rs=qall("SELECT * FROM towers ORDER BY id DESC")
        rows="".join([f'<div class="card" id="tower-{r["id"]}" data-name="{esc(r["name"])}" data-area="{esc(r["area"] or "")}" data-lat="{r.get("lat") or 0}" data-lng="{r.get("lng") or 0}" style="display:flex;justify-content:space-between"><div><b>🗼 {esc(r["name"])}</b><br><small>{esc(r["area"] or "")}</small><br><small style="color:#ffbe4d">{r.get("lat")},{r.get("lng")}</small></div><div><button class=btn-gold onclick="openEditTower({r["id"]})">✏</button> <button class=btn-del onclick="askDel(\'/del_tower/{r["id"]}\')">🗑</button></div></div>' for r in rs])
        return f'''<div style='max-width:700px;margin:0 auto'><div class=card><h3>🗼 الأبراج</h3><form data-ajax method=post action=/add_tower style='display:flex;gap:6px;flex-wrap:wrap'><input name=name placeholder='اسم' required style='flex:1'><input name=area placeholder='منطقة' style='flex:1'><input name=lat placeholder='lat' style='width:90px'><input name=lng placeholder='lng' style='width:90px'><button class=btn-gold>➕</button></form></div>{rows}</div><script>
        function openEditTower(id){{let c=document.getElementById('tower-'+id); let m=document.getElementById('editModal'); m.classList.add('show'); document.getElementById('editBody').innerHTML='<input id=et_n value="'+c.dataset.name+'" style="width:100%;padding:10px"><input id=et_a value="'+c.dataset.area+'" style="width:100%;padding:10px;margin-top:6px"><input id=et_lat value="'+c.dataset.lat+'" style="width:100%;padding:10px;margin-top:6px"><input id=et_lng value="'+c.dataset.lng+'" style="width:100%;padding:10px;margin-top:6px"><button onclick="saveTower('+id+')" class=btn-gold style="width:100%;margin-top:8px">حفظ</button>';}}
        function saveTower(id){{let n=document.getElementById('et_n').value; let a=document.getElementById('et_a').value; let la=document.getElementById('et_lat').value; let ln=document.getElementById('et_lng').value; fetch('/edit_tower/'+id,{{method:'POST',body:new URLSearchParams({{name:n,area:a,lat:la,lng:ln}})}}).then(()=>{{closeEditModal();loadPage('towers',true);}});}}
        </script>'''
    if v=='subs':
        rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 200")
        rows="".join([f'<div class="card" id="sub-{r["id"]}" data-name="{esc(r["name"])}" data-phone="{esc(r["phone"] or "")}" data-note="{esc(r["note"] or "")}" style="display:flex;justify-content:space-between"><div><b>{esc(r["name"])}</b><br>📞 {esc(r["phone"] or "")}</div><div><button class=btn-gold onclick="openEditSub({r["id"]})">✏</button> <button class=btn-del onclick="askDel(\'/del_sub/{r["id"]}\')">🗑</button></div></div>' for r in rs])
        return f'''<div style='max-width:700px;margin:0 auto'><div class=card><h3>👥 المشتركين</h3><form data-ajax method=post action=/add_sub style='display:flex;gap:5px'><input name=name placeholder='الاسم' required style='flex:1'><input name=phone placeholder='رقم' style='flex:1'><button class=btn-gold>➕</button></form></div>{rows}</div><script>
        function openEditSub(id){{let c=document.getElementById('sub-'+id); let m=document.getElementById('editModal'); m.classList.add('show'); document.getElementById('editBody').innerHTML='<input id=es_n value="'+c.dataset.name+'" style="width:100%;padding:10px"><input id=es_p value="'+c.dataset.phone+'" style="width:100%;padding:10px;margin-top:6px"><input id=es_no value="'+c.dataset.note+'" style="width:100%;padding:10px;margin-top:6px"><button onclick="saveSub('+id+')" class=btn-gold style="width:100%;margin-top:8px">حفظ</button>';}}
        function saveSub(id){{let n=document.getElementById('es_n').value; let p=document.getElementById('es_p').value; let no=document.getElementById('es_no').value; fetch('/edit_sub/'+id,{{method:'POST',body:new URLSearchParams({{name:n,phone:p,note:no}})}}).then(()=>{{closeEditModal();loadPage('subs',true);}});}}
        </script>'''
    if v=='ledger':
        rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 200")
        rows="".join([f'<div class="card" id="led-{r["id"]}" data-name="{esc(r["name"])}" data-amount="{r["amount"]}" style="display:flex;justify-content:space-between"><div><b>{esc(r["name"])}</b> - <b style="color:#ffbe4d">{r["amount"]}</b></div><div><button class=btn-gold onclick="openEditLed({r["id"]})">✏</button> <button class=btn-del onclick="askDel(\'/del_ledger/{r["id"]}\')">🗑</button></div></div>' for r in rs])
        return f'''<div style='max-width:700px;margin:0 auto'><div class=card><h3>📒 الحسابات</h3><form data-ajax method=post action=/add_ledger style='display:flex;gap:5px'><input name=name placeholder='الاسم' required style='flex:1'><input name=amount type=number step=0.01 placeholder='المبلغ' required style='flex:1'><button class=btn-gold>➕</button></form></div>{rows}</div><script>
        function openEditLed(id){{let c=document.getElementById('led-'+id); let m=document.getElementById('editModal'); m.classList.add('show'); document.getElementById('editBody').innerHTML='<input id=el_n value="'+c.dataset.name+'" style="width:100%;padding:10px"><input id=el_a value="'+c.dataset.amount+'" style="width:100%;padding:10px;margin-top:6px"><button onclick="saveLed('+id+')" class=btn-gold style="width:100%;margin-top:8px">حفظ</button>';}}
        function saveLed(id){{let n=document.getElementById('el_n').value; let a=document.getElementById('el_a').value; fetch('/edit_ledger/'+id,{{method:'POST',body:new URLSearchParams({{name:n,amount:a,note:'',currency:'USD'}})}}).then(()=>{{closeEditModal();loadPage('ledger',true);}});}}
        </script>'''
    if v=='logs':
        rs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 500")
        rows="".join([f"<div class='card' style='font-size:13px;border-right:3px solid #ffbe4d'><b style='color:#ffbe4d'>{esc(r.get('user_phone',''))}</b> {esc(r.get('action',''))} - {esc(r.get('detail',''))}<br><small style='color:#777'>{esc(r.get('time',''))}</small></div>" for r in rs])
        return f"<div style='max-width:900px;margin:0 auto'><div class=card style='display:flex;justify-content:space-between'><h3>📜 السجل الكامل - {len(rs)}</h3><a href='/api/export/logs' class=btn-gold style='text-decoration:none;padding:7px 12px'>📗 Excel</a></div>{rows or '<div class=card>لا يوجد سجل</div>'}</div>"
    if v=='network':
        dishes=qall(f"SELECT * FROM {get_dish_table()} ORDER BY id DESC LIMIT 100")
        rows="".join([f"<div class='card' id='net-{d['id']}' data-ip='{esc(d.get('ip',''))}' style='display:flex;justify-content:space-between'><div><b>{esc(d.get('dish_name') or 'صحن')}</b> - {esc(d.get('ip',''))}<br><small class='net-out'>⏳</small></div><button class=btn-gold onclick='checkOne({d['id']})'>📶</button></div>" for d in dishes])
        return f'''<div style='max-width:800px;margin:0 auto'><div class=card><h3>📊 حالة الشبكة LIVE</h3><button class=btn-gold onclick='checkAll()' style='width:100%;background:#22c55e;color:#fff;padding:12px'>🚀 فحص الكل</button><div id=summary style='margin-top:8px'></div></div>{rows}<script>
        async function checkOne(id){{let c=document.getElementById('net-'+id); let o=c.querySelector('.net-out'); o.textContent='⏳'; try{{let r=await fetch('/api/ping?ip='+c.dataset.ip); let j=await r.json(); o.textContent=j.out; o.style.color=j.ok?'#22c55e':'#ef4444';}}catch(e){{o.textContent='❌';}}}}
        async function checkAll(){{for(let c of document.querySelectorAll('[id^=net-]')){{checkOne(c.id.split('-')[1]); await new Promise(r=>setTimeout(r,150));}}}}
        </script></div>'''
    if v=='map':
        towers=qall("SELECT * FROM towers")
        tj=json.dumps([{"name":t['name'],"area":t.get('area') or '',"lat":float(t.get('lat') or 35.1318),"lng":float(t.get('lng') or 36.7578)} for t in towers], ensure_ascii=False)
        return f'''<div class=card style='padding:10px'><div style='display:flex;gap:6px;margin-bottom:8px;flex-wrap:wrap'>
        <input id=mapSearch placeholder='🔍 بحث برج...' style='flex:1;min-width:140px;padding:10px;border-radius:10px;background:#1f2937;border:1px solid #ffffff15;color:#fff'>
        <button class=btn-gold onclick="doMapSearch()">🔍 بحث</button>
        <button class=btn-gold onclick="locateMe()" style='background:#22c55e;color:#fff'>📍 موقعي</button>
        <button class=btn-gold onclick="toggleAddPoint()" id=addPointBtn style='background:#f59e0b;color:#fff'>➕ نقطة</button>
        <span id=coordsLabel style='color:#ffbe4d;font-size:12px'>📍 -</span></div>
        <div id=map style='height:75vh;min-height:500px;border-radius:14px;background:#0f172a'></div></div><script>
        let _towers={tj}; let _map=null; let addPointMode=false;
        window.doMapSearch=function(){{let q=document.getElementById('mapSearch').value.trim().toLowerCase(); if(!q) return; let f=_towers.find(t=>t.name.toLowerCase().includes(q)||t.area.toLowerCase().includes(q)); if(f && _map){{_map.flyTo([f.lat,f.lng],17); L.popup().setLatLng([f.lat,f.lng]).setContent('<b>🗼 '+f.name+'</b>').openOn(_map);}} else alert('لا يوجد');}}
        window.locateMe=function(){{if(_map && navigator.geolocation) navigator.geolocation.getCurrentPosition(p=>{{_map.flyTo([p.coords.latitude,p.coords.longitude],16); L.marker([p.coords.latitude,p.coords.longitude]).addTo(_map).bindPopup('📍 موقعك').openPopup();}});}}
        window.toggleAddPoint=function(){{addPointMode=!addPointMode; let b=document.getElementById('addPointBtn'); b.textContent=addPointMode?'✅ اضغط الخريطة':'➕ نقطة'; b.style.background=addPointMode?'#22c55e':'#f59e0b'; if(_map) _map.getContainer().style.cursor=addPointMode?'crosshair':'';}}
        function initMap(){{if(typeof L==='undefined'){{setTimeout(initMap,200);return;}}
        _map=L.map('map').setView([35.1318,36.7578],13);
        let osm=L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:19}}).addTo(_map);
        let sat=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',{{maxZoom:20}});
        let topo=L.tileLayer('https://{{s}}.tile.opentopomap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:17}});
        L.control.layers({{"عادية":osm,"قمر صناعي HD":sat,"تضاريس":topo}}).addTo(_map);
        L.control.scale().addTo(_map);
        _towers.forEach(t=>{{L.marker([t.lat,t.lng]).addTo(_map).bindPopup('<b>'+t.name+'</b><br>'+t.area);}});
        _map.on('click',e=>{{
          document.getElementById('coordsLabel').textContent='📍 '+e.latlng.lat.toFixed(5)+','+e.latlng.lng.toFixed(5);
          if(addPointMode){{
            let lat=e.latlng.lat.toFixed(6), lng=e.latlng.lng.toFixed(6);
            L.popup().setLatLng(e.latlng).setContent('<div style="min-width:180px"><b>➕ نقطة جديدة</b><br><small>'+lat+','+lng+'</small><br><input id="np_name" placeholder="اسم البرج" style="width:100%;margin:6px 0;padding:8px"><input id="np_area" placeholder="منطقة" style="width:100%;margin:4px 0;padding:8px"><button onclick="saveNewPoint('+lat+','+lng+')" style="width:100%;background:#ffbe4d;border:0;padding:8px;border-radius:8px;font-weight:800">💾 حفظ</button></div>').openOn(_map);
          }}
        }});
        window.saveNewPoint=function(lat,lng){{
          let name=document.getElementById('np_name').value.trim()||'نقطة جديدة';
          let area=document.getElementById('np_area').value.trim()||'';
          fetch('/add_tower',{{method:'POST',body:new URLSearchParams({{name:name,area:area,lat:lat,lng:lng}})}}).then(r=>{{if(r.ok){{alert('✅ تمت الاضافة'); _map.closePopup(); addPointMode=false; document.getElementById('addPointBtn').textContent='➕ نقطة';}}}});
        }};
        setTimeout(()=>_map.invalidateSize(),300);
        }}
        initMap();
        </script>'''
    if v=='support':
        return """<div style='max-width:600px;margin:0 auto;text-align:center'><div class=card><h2>🛠 الدعم الفني</h2><p style='color:#9ca3af'>تواصل معنا مباشرة</p>
        <a href='https://wa.me/905345851045' target=_blank style='display:block;background:linear-gradient(90deg,#22c55e,#16a34a);color:#fff;padding:16px;border-radius:14px;text-decoration:none;margin:10px 0;font-weight:900;font-size:18px'>💬 واتساب: +90 534 485 10 45</a>
        <a href='https://instagram.com/af_20_1999' target=_blank style='display:block;background:linear-gradient(90deg,#e1306c,#f77737);color:#fff;padding:14px;border-radius:14px;text-decoration:none;margin:10px 0;font-weight:800'>📸 Instagram: af_20_1999</a>
        <a href='tel:+905345851045' style='display:block;background:#0ea5e9;color:#fff;padding:12px;border-radius:14px;text-decoration:none;margin:10px 0'>📞 اتصال مباشر</a>
        </div></div>"""
    if v=='settings':
        us=qall("SELECT * FROM users ORDER BY phone DESC")
        uh="".join([f'<div class="card" id="user-{esc(u["phone"])}" data-phone="{esc(u["phone"])}" data-username="{esc(u.get("username") or "")}" data-role="{esc(u.get("role") or "")}" style="display:flex;justify-content:space-between"><div><b>{esc(u.get("username") or "")}</b><br><span style="color:#ffbe4d">{esc(u["phone"])}</span></div><div><button class=btn-gold onclick="openEditUser(\'{esc(u["phone"])}\')">✏</button> <button class=btn-del onclick="askDel(\'/del_user/{esc(u["phone"])}\')">🗑</button></div></div>' for u in us])
        return f'''<div style='max-width:800px;margin:0 auto'>
        <div style='display:grid;grid-template-columns:1fr 1fr;gap:10px'>
        <div class=card><h4>🌐 اللغة</h4><button onclick="toggleLang()" class=btn-gold style='width:100%;padding:12px'>🌐 تبديل عربي / English</button><small style='color:#9ca3af'>شغال نظامي</small></div>
        <div class=card><h4>🎨 المظهر</h4><button onclick="toggleTheme()" class=btn-gold style='width:100%;padding:12px'>🌓 ليل / نهار</button></div>
        </div>
        <div class=card><h3>👤 اضافة يوزر</h3><form data-ajax method=post action=/add_user style='display:flex;gap:8px;flex-wrap:wrap'><input name=user_field placeholder='رقم / يوزر' required style='flex:1'><input name=password type=password placeholder='باسورد' required style='flex:1'><select name=role style='width:100px'><option value=tech>فني</option><option value=manager>مدير</option></select><button class=btn-gold>➕</button></form></div>
        <div class=card><h3>🔑 كلمة السر</h3><form data-ajax method=post action=/change_pass style='display:flex;gap:8px'><input name=newpass type=password placeholder='جديدة' required style='flex:1'><button class=btn-gold>💾 حفظ</button></form></div>
        {uh}
        </div><script>
        function openEditUser(ph){{let c=document.getElementById('user-'+ph); let m=document.getElementById('editModal'); m.classList.add('show'); document.getElementById('editBody').innerHTML='<input id=eu_p value="'+c.dataset.phone+'" style="width:100%;padding:10px"><input id=eu_pass type="password" placeholder="باسورد جديد (اتركه فاضي اذا ما بدك تغير)" style="width:100%;padding:10px;margin-top:6px"><select id=eu_r style="width:100%;padding:10px;margin-top:6px"><option value="tech">فني</option><option value="manager">مدير</option></select><button onclick="saveU(\\''+ph+'\\')" class=btn-gold style="width:100%;margin-top:8px">حفظ</button>'; document.getElementById('eu_r').value=c.dataset.role;}}
        function saveU(oldPh){{let np=document.getElementById('eu_p').value.trim(); let pw=document.getElementById('eu_pass').value.trim(); let r=document.getElementById('eu_r').value; let d={{old_phone:oldPh,phone:np,role:r}}; if(pw) d.password=pw; fetch('/edit_user',{{method:'POST',body:new URLSearchParams(d)}}).then(()=>{{closeEditModal(); loadPage('settings',true);}});}}
        </script>'''
    return "<div class=card>ok</div>"

def layout(c,v='home'):
    cur_user=qone("SELECT * FROM users WHERE phone=?",(session.get('phone') or '',))
    role=(cur_user.get('role') or 'tech') if cur_user else 'tech'
    return f"""<html dir=rtl lang=ar><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<link rel=stylesheet href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'>
<style>
*{{box-sizing:border-box;font-family:system-ui}}body{{margin:0;background:#0a0e2a;color:#fff}}
.top{{position:fixed;top:0;left:0;right:0;height:60px;background:#0f172a;color:#fff;display:flex;align-items:center;justify-content:space-between;padding:0 12px;z-index:1003;border-bottom:1px solid #ffffff12}}
.top-left{{display:flex;gap:8px;align-items:center}}
.top-center{{font-weight:900}}
.top-right{{display:flex;gap:8px;align-items:center}}
.sidebar{{position:fixed;right:0;top:0;width:270px;height:100%;background:#0f172a;z-index:1002;padding-top:70px;transform:translateX(110%);transition:transform.18s;overflow-y:auto}}
.sidebar.active{{transform:none}}
.sidebar a{{display:flex;gap:10px;padding:11px 14px;margin:5px 10px;color:#cbd5e1;text-decoration:none;border-radius:10px;background:#ffffff06}}
.sidebar a.active{{background:#ffbe4d;color:#111;font-weight:800}}
#overlay{{position:fixed;inset:0;background:#0008;z-index:1001;display:none}}#overlay.show{{display:block}}
.main{{margin-top:70px;padding:12px}}
.card{{background:#1e2433;padding:14px;border-radius:14px;margin-bottom:10px;border:1px solid #ffffff12}}
input,select{{padding:11px;margin:5px 0;border-radius:10px;border:1px solid #ffffff12;width:100%;background:#ffffff07;color:#fff}}
.btn-gold{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;padding:8px 14px;border:0;border-radius:10px;font-weight:800;cursor:pointer}}
.btn-del{{background:#ef4444;color:#fff;padding:7px 11px;border:0;border-radius:10px}}
#delModal,#editModal{{position:fixed;inset:0;background:#000a;display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;z-index:2000}}#delModal.show,#editModal.show{{opacity:1;pointer-events:auto}}
#delBox,#editBox{{background:#1e2433;padding:20px;border-radius:16px;width:92%;max-width:400px}}
#notifPanel{{position:fixed;top:64px;left:10px;width:320px;max-height:70vh;overflow:auto;background:#1e2433;border:1px solid #ffffff12;border-radius:12px;display:none;z-index:2000}}
</style></head><body>
<div id=overlay onclick="toggleSb(false)"></div>
<div class=sidebar id=sb>
<div style='padding:0 16px 8px;border-bottom:1px solid #ffffff0a'><b>OMAIA <span style='color:#ffbe4d'>ISP</span> <small style='color:#22c55e'>نار</small></b><br><small style='color:#64748b'>{esc(cur_user.get('username') or '')} • {role}</small></div>
<a href="javascript:loadPage('home')" id=nav-home>🏠 الرئيسية</a>
<a href="javascript:loadPage('ping')" id=nav-ping>📶 Ping</a>
<a href="javascript:loadPage('network')" id=nav-network>📊 الشبكة</a>
<a href="javascript:loadPage('dishes')" id=nav-dishes>📡 الصحون</a>
<a href="javascript:loadPage('towers')" id=nav-towers>🗼 الأبراج</a>
<a href="javascript:loadPage('subs')" id=nav-subs>👥 المشتركين</a>
<a href="javascript:loadPage('ledger')" id=nav-ledger>📒 الحسابات</a>
<a href="javascript:loadPage('logs')" id=nav-logs>📜 السجل</a>
<a href="javascript:loadPage('map')" id=nav-map>🗺 الخريطة HD</a>
<a href="javascript:loadPage('support')" id=nav-support>🛠 الدعم الفني</a>
<a href="javascript:loadPage('settings')" id=nav-settings>⚙ الإعدادات</a>
<a href="javascript:logoutFast()" style='margin-top:10px;background:#ef444422'>🚪 خروج</a>
</div>
<div class=top>
<div class=top-right><span onclick="toggleSb()" style='font-size:24px;cursor:pointer'>☰</span><input id=topsearch placeholder='🔍 بحث...' oninput="globalSearchTop(this.value)" style='background:#1f2937;border:1px solid #ffffff15;color:#fff;padding:8px 12px;border-radius:10px;width:42px;transition:width.2s' onfocus="this.style.width='160px'" onblur="setTimeout(()=>this.style.width='42px',200)"></div>
<div class=top-center>OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<div class=top-left><div id=notifBell onclick="toggleNotif()" style='position:relative;cursor:pointer;font-size:20px'>🔔<span id=notifCount style='display:none;position:absolute;top:-6px;right:-6px;background:#ef4444;color:#fff;font-size:10px;width:16px;height:16px;border-radius:50%;align-items:center;justify-content:center'>0</span></div><button onclick="toggleTheme()" title='ليل/نهار' style='background:#ffffff12;border:1px solid #ffffff15;color:#fff;padding:6px 10px;border-radius:10px'>🌓</button></div>
</div>
<div id=searchResults style='position:fixed;top:64px;right:10px;left:10px;max-width:420px;margin:0 auto;background:#1e2433;border:1px solid #ffffff15;border-radius:12px;z-index:1500;display:none;max-height:50vh;overflow:auto'></div>
<div id=notifPanel></div>
<div class=main id=mn>{c}</div>
<div id=delModal><div id=delBox><h3 style='text-align:center'>تأكيد الحذف؟</h3><div style='display:flex;gap:10px;margin-top:12px'><button onclick="closeDel()" style='flex:1;padding:10px;border-radius:10px'>تراجع</button><button id=delYes style='flex:1;padding:10px;border-radius:10px;background:#ef4444;color:#fff;border:0'>حذف</button></div></div></div>
<div id=editModal><div id=editBox><div style='display:flex;justify-content:space-between'><h3>✏ تعديل</h3><button onclick="closeEditModal()" style='background:#ffffff12;border:0;width:28px;height:28px;border-radius:50%'>✕</button></div><div id=editBody style='margin-top:10px'></div></div></div>
<script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>
<script>
let cur='{v}'; let pageCache={{}};
function toggleSb(f){{let sb=document.getElementById('sb'),ov=document.getElementById('overlay'); let o=f!==undefined?f:!sb.classList.contains('active'); sb.classList.toggle('active',o); ov.classList.toggle('show',o); ov.style.display=o?'block':'none';}}
async function loadPage(v,force=false){{cur=v; toggleSb(false); document.querySelectorAll('.sidebar a').forEach(a=>a.classList.remove('active')); let n=document.getElementById('nav-'+v); if(n) n.classList.add('active'); let mn=document.getElementById('mn'); if(!force && pageCache[v]){{mn.innerHTML=pageCache[v]; bind(); execScripts(); return;}} try{{let r=await fetch('/api/page?v='+v); let h=await r.text(); pageCache[v]=h; mn.innerHTML=h; bind(); execScripts();}}catch(e){{mn.innerHTML='<div class=card>❌ '+e+'</div>';}}}}
function execScripts(){{document.getElementById('mn').querySelectorAll('script').forEach(s=>{{try{{eval(s.textContent)}}catch(e){{}}}});}}
function bind(){{document.querySelectorAll('form[data-ajax]').forEach(f=>{{if(f.dataset.bound) return; f.dataset.bound='1'; f.onsubmit=async e=>{{e.preventDefault(); let r=await fetch(f.action,{{method:'POST',body:new FormData(f)}}); if(r.ok){{delete pageCache[cur]; loadPage(cur,true);}} else alert(await r.text());}};}});}}
function askDel(u){{window._delUrl=u; document.getElementById('delModal').classList.add('show');}}
function closeDel(){{document.getElementById('delModal').classList.remove('show');}}
window.closeEditModal=function(){{document.getElementById('editModal').classList.remove('show');}}
document.getElementById('delYes').onclick=async()=>{{if(window._delUrl){{await fetch(window._delUrl); delete pageCache[cur]; closeDel(); loadPage(cur,true);}}}};
window.toggleLang=async function(){{await fetch('/toggle_lang'); loadPage(cur,true);}};
window.toggleTheme=async function(){{await fetch('/toggle_theme'); location.reload();}};
window.globalSearchTop=async function(q){{let b=document.getElementById('searchResults'); if(!q){{b.style.display='none'; return;}} try{{let r=await fetch('/api/search?q='+encodeURIComponent(q)); let d=await r.json(); if(!d.length){{b.style.display='none'; return;}} let h=''; d.forEach(x=>{{h+='<div onclick="loadPage(\\''+x.page+'\\');b.style.display=\\'none\\'" style="padding:9px 12px;border-top:1px solid #ffffff08;cursor:pointer"><b>'+x.title+'</b> <small style="color:#888">'+x.sub+'</small></div>';}}); b.innerHTML=h; b.style.display='block';}}catch(e){{}}}};
window.toggleNotif=async function(){{let p=document.getElementById('notifPanel'); p.style.display=p.style.display==='block'?'none':'block'; if(p.style.display==='block'){{let r=await fetch('/api/notifications'); let j=await r.json(); let h='<div style="padding:12px"><div style="display:flex;justify-content:space-between"><b>🔔 الاشعارات ('+j.unread+')</b><button onclick="readAll()" style="background:#ffbe4d;border:0;padding:4px 8px;border-radius:8px">مقروء</button></div><hr>'; j.rows.forEach(n=>{{h+='<div style="padding:8px;border-bottom:1px solid #ffffff08"><b style="color:#ffbe4d">'+n.title+'</b><br><small>'+n.msg+'</small><br><small style="color:#777">'+n.time+'</small></div>';}}); h+='</div>'; p.innerHTML=h;}}}}
window.readAll=async function(){{await fetch('/api/notifications/read',{{method:'POST'}}); document.getElementById('notifCount').style.display='none'; document.getElementById('notifPanel').style.display='none';}};
async function loadNotif(){{try{{let r=await fetch('/api/notifications'); let j=await r.json(); let c=document.getElementById('notifCount'); if(j.unread>0){{c.textContent=j.unread; c.style.display='flex';}} else c.style.display='none';}}catch(e){{}}}}
loadNotif(); setInterval(loadNotif,15000);
window.logoutFast=async function(){{await fetch('/api/logout',{{method:'POST'}}); location.replace('/login');}};
bind(); execScripts();
</script></body></html>"""

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)),threaded=True)
