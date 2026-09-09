from flask import Flask, request, redirect, session, jsonify, Response
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, html, ipaddress, subprocess, json, socket, platform, io, csv, datetime, re, time
import psycopg2, psycopg2.extras
import sqlite3

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY","omia-sec-2026-CHANGE-ME")
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
# ندعم postgres:// و postgresql:// الاتنين
PG_URL = DATABASE_URL.replace("postgres://","postgresql://",1) if DATABASE_URL.startswith("postgres://") else DATABASE_URL
USE_PG = bool(DATABASE_URL)

_pg = None
_last_check = 0
_dish_cache = {"name": None, "ts": 0}
_cnt_cache = {} # tbl -> (val, ts)
_stats_cache = {"data": None, "ts": 0}

def esc(s): return html.escape(str(s or ''), quote=True)

def db():
    global _pg, _last_check
    if USE_PG:
        now = time.time()
        if _pg:
            # فحص الاتصال مرة كل 30 ثانية بس، مو بكل استعلام
            if now - _last_check < 30:
                return _pg
            try:
                cur=_pg.cursor();cur.execute("SELECT 1");cur.close()
                _last_check = now
                return _pg
            except:
                try:_pg.close()
                except:pass
                _pg=None
        try:
            _pg=psycopg2.connect(PG_URL,sslmode='require',connect_timeout=3)
            _pg.autocommit=True
            _last_check = now
            return _pg
        except:
            pass
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
        # امسح كاش العد
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
            c=db()
            cur=c.cursor()
            cur.execute("SELECT to_regclass('public.ips')")
            r=cur.fetchone()
            cur.close()
            tbl = "ips" if r and r[0] else "dish_ips"
            _dish_cache["name"]=tbl
            _dish_cache["ts"]=now
            return tbl
        except:
            pass
        return "dish_ips"
    return "dish_ips"

def fast_count(tbl, ttl=20):
    now=time.time()
    if tbl in _cnt_cache:
        v, ts = _cnt_cache[tbl]
        if now - ts < ttl:
            return v
    c = (qone(f"SELECT COUNT(*) c FROM {tbl}") or {}).get('c',0)
    _cnt_cache[tbl]=(c, now)
    return c

def get_home_stats():
    now=time.time()
    if _stats_cache["data"] and now - _stats_cache["ts"] < 20:
        return _stats_cache["data"]
    tbl=get_dish_table()
    try:
        row=qone(f"SELECT (SELECT COUNT(*) FROM subs) as subs, (SELECT COUNT(*) FROM towers) as towers, (SELECT COUNT(*) FROM ledger) as ledger, (SELECT COUNT(*) FROM {tbl}) as dishes")
        if row:
            _stats_cache["data"]=row
            _stats_cache["ts"]=now
            return row
    except:
        pass
    return {"subs":fast_count("subs"), "towers":fast_count("towers"), "ledger":fast_count("ledger"), "dishes":fast_count(tbl)}

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
        ss[0]="CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,username TEXT)"
        for i in range(1,7):
            ss[i]=ss[i].replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY")
    for s in ss:qexec(s)
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
    if not u:return False
    return (u.get('role') or '').lower()=='manager'
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
        c=db()
        cur=c.cursor()
        cur.execute("SELECT 1")
        cur.close()
        return jsonify(ok=True, pg=True, time=datetime.datetime.now().isoformat(), table=get_dish_table())
    except Exception as e:
        return jsonify(ok=True, pg=False, error=str(e), time=datetime.datetime.now().isoformat())

@app.route('/api/ping')
@login_required
def api_ping():
    ip=request.args.get('ip','').strip()
    if not ip:return jsonify(ok=False,out='لا يوجد IP')
    if not is_valid_ip(ip):return jsonify(ok=False,out='IP غير صالح')
    for port in [80,443,8080,8291,22,23,53,8000,8728]:
        try:
            s=socket.socket(socket.AF_INET,socket.SOCK_STREAM);s.settimeout(0.9)
            if s.connect_ex((ip,port))==0:
                s.close()
                return jsonify(ok=True,out=f'✅ متصل - {ip}:{port} مفتوح',port=port,method='tcp')
            s.close()
        except:continue
    try:
        cmd=['ping','-c','1','-W','1',ip] if platform.system().lower()!='windows' else ['ping','-n','1','-w','1000',ip]
        out=subprocess.check_output(cmd,timeout=2,stderr=subprocess.STDOUT).decode(errors='ignore')
        ok='ttl=' in out.lower() or 'bytes from' in out.lower() or '1 received' in out.lower()
        if ok:
            m=re.search(r'time[=<]\s*(\d+\.?\d*)',out,re.I)
            ms=m.group(1) if m else ''
            return jsonify(ok=True,out=f'✅ متصل {ip} - {ms}ms',ms=ms,method='icmp')
    except:pass
    return jsonify(ok=False,out=f'❌ {ip} لا يرد')

@app.route('/api/ping_tcp')
@login_required
def api_ping_tcp():
    ip=request.args.get('ip','').strip()
    port=int(request.args.get('port','80') or 80)
    if not is_valid_ip(ip):return jsonify(ok=False,out='IP غير صالح')
    try:
        s=socket.socket(socket.AF_INET,socket.SOCK_STREAM);s.settimeout(1.5);r=s.connect_ex((ip,port));s.close()
        return jsonify(ok=r==0,out=f'✅ {ip}:{port} مفتوح' if r==0 else f'❌ {ip}:{port} مغلق')
    except Exception as e:return jsonify(ok=False,out=f'❌ {e}')

@app.route('/api/notifications')
@login_required
def api_noti():
    rows=qall("SELECT * FROM notifications ORDER BY id DESC LIMIT 20")
    unread=qone("SELECT COUNT(*) c FROM notifications WHERE read=0")
    cnt=unread.get('c',0) if unread else 0
    return jsonify(rows=rows,unread=cnt)

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
    cur=session.get('lang','ar');new='en' if cur=='ar' else 'ar';session['lang']=new;return jsonify(ok=True,lang=new)

@app.route('/api/login_public',methods=['POST'])
def api_login_public():
    uin=request.form.get('userin','').strip();pw=request.form.get('password','')
    u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
    if u and check_password_hash(u['password'],pw):
        session['phone']=u['phone'];session['username']=u.get('username') or u['phone'];session.permanent=True
        return jsonify(ok=True,role=u.get('role'))
    return jsonify(ok=False,msg='خطأ بالدخول'),401

@app.route('/api/export/<tbl>')
@login_required
def api_export(tbl):
    output=io.StringIO();w=csv.writer(output)
    dish_tbl=get_dish_table()
    if tbl=='dishes':
        rows=qall(f"SELECT * FROM {dish_tbl} ORDER BY id DESC");w.writerow(['ID','اسم الصحن','IP','الموقع'])
        for r in rows:w.writerow([r['id'],r.get('dish_name',''),r.get('ip',''),r.get('location','')]);fname='dishes.csv'
    elif tbl=='subs':
        rows=qall("SELECT * FROM subs ORDER BY id DESC");w.writerow(['ID','الاسم','رقم','ملاحظة'])
        for r in rows:w.writerow([r['id'],r.get('name',''),r.get('phone',''),r.get('note','')]);fname='subs.csv'
    elif tbl=='users':
        rows=qall("SELECT phone,username,role FROM users ORDER BY phone DESC");w.writerow(['يوزر/رقم','اسم المستخدم','الرتبة'])
        for r in rows:w.writerow([r.get('phone',''),r.get('username',''),r.get('role','')]);fname='users.csv'
    elif tbl=='towers':
        rows=qall("SELECT * FROM towers ORDER BY id DESC");w.writerow(['ID','اسم البرج','المنطقة','lat','lng'])
        for r in rows:w.writerow([r['id'],r.get('name',''),r.get('area',''),r.get('lat',''),r.get('lng','')]);fname='towers.csv'
    elif tbl=='logs':
        rows=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 1000");w.writerow(['ID','المستخدم','العملية','التفاصيل','الوقت'])
        for r in rows:w.writerow([r['id'],r.get('user_phone',''),r.get('action',''),r.get('detail',''),r.get('time','')]);fname='logs.csv'
    else:w.writerow(['ID']);fname='export.csv'
    return Response(output.getvalue(),mimetype='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename={fname}'})

@app.route('/')
def ix():return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login')
def login():
    return """<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<style>*{box-sizing:border-box;font-family:system-ui}body{margin:0;min-height:100vh;background:radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 55%, #070a1f 100%);display:flex;flex-direction:column;align-items:center;justify-content:center;color:#fff}
.card{background:linear-gradient(180deg, #222b45cc, #1a2035cc);border:1px solid #ffffff18;padding:26px;border-radius:22px;width:92%;max-width:380px}
input{width:100%;padding:14px;margin:9px 0;background:#0f1424;border:1px solid #ffffff22;color:#fff;border-radius:14px;font-size:15px}
.btn{width:100%;padding:14px;border:0;border-radius:14px;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:900;font-size:17px;cursor:pointer;margin-top:12px}
#loader{position:fixed;inset:0;background:#0a0e2a;z-index:9999;display:flex;flex-direction:column;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:opacity.15s}
#loader.show{opacity:1;pointer-events:auto}
.spinner{width:38px;height:38px;border:4px solid #ffffff18;border-top-color:#ffbe4d;border-radius:50%;animation:spin.6s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}</style></head><body>
<div id=loader><div class=spinner></div><div style='margin-top:10px;color:#ffbe4d;font-weight:800'>⏳ جاري التحميل...</div></div>
<div style='font-size:30px;font-weight:900;margin-bottom:14px'>OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<div class=card><form id=loginForm><input name=userin id=userin placeholder='📱 رقم / يوزر' required autocomplete=username><input name=password id=password type=password placeholder='🔑 كلمة السر' required autocomplete=current-password><label style='display:flex;gap:8px;font-size:13px;color:#aaa;margin:8px 0'><input type=checkbox id=savePass style='width:auto'> حفظ</label><button class=btn id=loginBtn>✨ دخول فوري</button><div id=msg style='text-align:center;margin-top:8px;color:#ff6b6b;font-size:13px'></div></form></div>
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
    like="%"+q+"%";results=[]
    dish_tbl=get_dish_table()
    try:
        for r in qall(f"SELECT * FROM {dish_tbl} WHERE ip LIKE? OR dish_name LIKE? OR location LIKE? ORDER BY id DESC LIMIT 20",(like,like,like)):results.append({"title":r.get('dish_name') or r.get('ip') or 'صحن',"sub":r.get('ip',''),"page":"dishes","type":"dish"})
        for r in qall("SELECT * FROM subs WHERE name LIKE? OR phone LIKE? ORDER BY id DESC LIMIT 15",(like,like)):results.append({"title":r.get('name',''),"sub":r.get('phone',''),"page":"subs","type":"sub"})
        for r in qall("SELECT * FROM towers WHERE name LIKE? OR area LIKE? ORDER BY id DESC LIMIT 15",(like,like)):results.append({"title":r.get('name',''),"sub":r.get('area',''),"page":"towers","type":"tower"})
        for r in qall("SELECT * FROM users WHERE phone LIKE? OR username LIKE? LIMIT 10",(like,like)):results.append({"title":r.get('username') or r.get('phone',''),"sub":r.get('phone',''),"page":"settings","type":"user"})
        for r in qall("SELECT * FROM ledger WHERE name LIKE? OR note LIKE? ORDER BY id DESC LIMIT 10",(like,like)):results.append({"title":r.get('name',''),"sub":str(r.get('amount','')),"page":"ledger","type":"ledger"})
    except:pass
    return jsonify(results[:25])

@app.route('/toggle_theme')
@login_required
def tt():cur=session.get('theme','dark');session['theme']='light' if cur=='dark' else 'dark';return jsonify(ok=True)

@app.route('/add_dish',methods=['POST'])
@login_required
def ad():
    dish_tbl=get_dish_table()
    ip=request.form.get('ip','').strip();name=request.form.get('dish_name','').strip();loc=request.form.get('location','').strip()
    if not ip:return "IP مطلوب",400
    if not is_valid_ip(ip):return "IP غير صالح",400
    ex=qone(f"SELECT * FROM {dish_tbl} WHERE ip=?",(ip,))
    if ex:
        qexec(f"UPDATE {dish_tbl} SET dish_name=?,location=? WHERE ip=?",(name,loc,ip))
        if dish_tbl=='ips':
            try:qexec("UPDATE dish_ips SET dish_name=?,location=? WHERE ip=?",(name,loc,ip))
            except:pass
        return "ok updated"
    qexec(f"INSERT INTO {dish_tbl}(ip,location,dish_name) VALUES(?,?,?)",(ip,loc,name))
    if dish_tbl=='ips':
        try:qexec("INSERT INTO dish_ips(ip,location,dish_name) VALUES(?,?,?)",(ip,loc,name))
        except:pass
    else:
        try:qexec("INSERT INTO ips(ip,location,dish_name) VALUES(?,?,?)",(ip,loc,name))
        except:pass
    return "ok"

@app.route('/edit_dish/<int:i>',methods=['POST'])
@login_required
def ed(i):
    if not is_manager():return "ممنوع للفني",403
    dish_tbl=get_dish_table()
    qexec(f"UPDATE {dish_tbl} SET dish_name=?,ip=?,location=? WHERE id=?",(request.form.get('dish_name',''),request.form.get('ip',''),request.form.get('location',''),i));return "ok"

@app.route('/del_dish/<int:i>')
@login_required
def dd(i):
    if not is_manager():return "ممنوع للفني",403
    dish_tbl=get_dish_table()
    qexec(f"DELETE FROM {dish_tbl} WHERE id=?",(i,));return "ok"

@app.route('/add_tower',methods=['POST'])
@login_required
def at():
    lat=request.form.get('lat','').strip();lng=request.form.get('lng','').strip()
    try:la=float(lat) if lat else 35.1312;ln=float(lng) if lng else 36.7578
    except:la=35.1312;ln=36.7578
    qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",(request.form.get('name',''),request.form.get('area',''),la,ln));return "ok"

@app.route('/del_tower/<int:i>')
@login_required
def dt(i):
    if not is_manager():return "ممنوع للفني",403
    qexec("DELETE FROM towers WHERE id=?",(i,));return "ok"

@app.route('/edit_tower/<int:i>',methods=['POST'])
@login_required
def et(i):
    if not is_manager():return "ممنوع للفني",403
    lat=request.form.get('lat','').strip();lng=request.form.get('lng','').strip()
    try:la=float(lat) if lat else 35.1318;ln=float(lng) if lng else 36.7578
    except:la=35.1318;ln=36.7578
    qexec("UPDATE towers SET name=?,area=?,lat=?,lng=? WHERE id=?",(request.form.get('name',''),request.form.get('area',''),la,ln,i));return "ok"

@app.route('/add_sub',methods=['POST'])
@login_required
def asub():qexec("INSERT INTO subs(name,phone,note) VALUES(?,?,?)",(request.form.get('name',''),request.form.get('phone',''),request.form.get('note','')));return "ok"

@app.route('/del_sub/<int:i>')
@login_required
def dsub(i):
    if not is_manager():return "ممنوع للفني",403
    qexec("DELETE FROM subs WHERE id=?",(i,));return "ok"

@app.route('/edit_sub/<int:i>',methods=['POST'])
@login_required
def esub(i):
    if not is_manager():return "ممنوع للفني",403
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
    if not is_manager():return "ممنوع للفني",403
    qexec("DELETE FROM ledger WHERE id=?",(i,));return "ok"

@app.route('/edit_ledger/<int:i>',methods=['POST'])
@login_required
def el(i):
    if not is_manager():return "ممنوع للفني",403
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
    def L(ar,en):return ar if req_lang=='ar' else en
    if v=='home':
        st=get_home_stats()
        ns=st.get('subs',0);nd=st.get('dishes',0);nt=st.get('towers',0);nl=st.get('ledger',0)
        logs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 4")
        log_html="".join([f"<div style='display:flex;justify-content:space-between;padding:7px 10px;border-bottom:1px dashed #ffffff10'><div><b style='color:#ffbe4d'>{esc(l.get('user_phone',''))}</b> {esc(l.get('action',''))}</div><small style='color:#777'>{esc(l.get('time',''))}</small></div>" for l in logs])
        return f'''<div style='max-width:900px;margin:0 auto'><div style='display:grid;grid-template-columns:1fr 1fr;gap:14px'>
        <div class='card anim' onclick="loadPage('subs')" style='cursor:pointer;background:linear-gradient(135deg,#1e2a4a 0%,#162040 100%)'><div style='display:flex;justify-content:space-between'><div><h3 style='margin:0;color:#aab4d0;font-size:13px'>{L('المشتركين','Subs')}</h3><h2 style='margin:6px 0 0;font-size:36px'>{ns}</h2></div><div style='font-size:36px'>👥</div></div></div>
        <div class='card anim' onclick="loadPage('dishes')" style='cursor:pointer;background:linear-gradient(135deg,#1e2f4a 0%,#162840 100%)'><div style='display:flex;justify-content:space-between'><div><h3 style='margin:0;color:#aab4d0;font-size:13px'>{L('الصحون','Dishes')}</h3><h2 style='margin:6px 0 0;font-size:36px'>{nd}</h2><small style='color:#22c55e'>☁ {dish_tbl}</small></div><div style='font-size:36px'>📡</div></div></div>
        <div class='card anim' onclick="loadPage('towers')" style='cursor:pointer;background:linear-gradient(135deg,#2a1e4a 0%,#201640 100%)'><div style='display:flex;justify-content:space-between'><div><h3 style='margin:0;color:#aab4d0;font-size:13px'>{L('الأبراج','Towers')}</h3><h2 style='margin:6px 0 0;font-size:36px'>{nt}</h2></div><div style='font-size:36px'>🗼</div></div></div>
        <div class='card anim' onclick="loadPage('ledger')" style='cursor:pointer;background:linear-gradient(135deg,#4a2a1e 0%,#402016 100%)'><div style='display:flex;justify-content:space-between'><div><h3 style='margin:0;color:#aab4d0;font-size:13px'>{L('الحسابات','Accounts')}</h3><h2 style='margin:6px 0 0;font-size:36px'>{nl}</h2></div><div style='font-size:36px'>📒</div></div></div></div>
        <div class=card style='margin-top:14px'><div style='display:flex;justify-content:space-between;flex-wrap:wrap'><h4>📊 {L('التقارير','Reports')} - <small style='color:#22c55e'>☁ {dish_tbl}</small></h4><div style='display:flex;gap:8px'><a href='/api/export/dishes' class=btn-gold style='text-decoration:none;padding:8px 12px;background:linear-gradient(90deg,#22c55e,#16a34a);color:#fff'>📗 Excel</a></div></div></div>
        <div class=card><h4>📜 {L('آخر النشاطات','Recent')}</h4>{log_html or 'لا يوجد'}<button class=btn-gold onclick="loadPage('logs')" style='width:100%;margin-top:8px'>عرض السجل</button></div></div>'''
    if v=='ping':
        return f'''<div style='max-width:800px;margin:0 auto'>
        <div class=card style='background:linear-gradient(135deg,#0f172a,#1e293b);border:1px solid #22c55e33'>
        <h3 style='margin:0'>📶 {L('بنج منفصل','Separate Ping')} 🔥 نار</h3>
        <p style='color:#9ca3af;font-size:12px;margin:6px 0'>⚡ سريع - {dish_tbl} ☁</p>
        <div style='display:flex;gap:8px;margin-top:12px;flex-wrap:wrap'>
        <input id=pingIp placeholder='192.168.1.1' style='flex:1;min-width:160px;padding:14px;border-radius:12px;background:#0f1424;border:1px solid #ffffff20;color:#fff;font-family:monospace'>
        <input id=pingPort placeholder='Port' value='80' style='width:80px;padding:14px;border-radius:12px;background:#0f1424;border:1px solid #ffffff20;color:#fff'>
        <button class=btn-gold onclick="doSinglePing()" style='padding:14px 20px;background:linear-gradient(90deg,#22c55e,#16a34a);color:#fff'>📶 Ping</button>
        <button class=btn-gold onclick="doTcpPing()" style='padding:14px 16px;background:linear-gradient(90deg,#0ea5e9,#0284c7);color:#fff'>TCP</button>
        </div>
        <div id=pingResult style='margin-top:14px;min-height:60px;background:#0008;border:1px solid #ffffff0a;border-radius:12px;padding:14px;font-family:monospace;font-size:13px;white-space:pre-wrap'>جاهز...</div>
        <div style='display:flex;gap:8px;margin-top:10px'><button class=btn-gold onclick="pingAllDishes()" style='flex:1;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111'>🚀 فحص كل الصحون</button><button class=btn-gold onclick="clearPing()" style='background:#ffffff10;color:#fff'>🗑</button></div>
        </div>
        <div class=card><h4>⚡ صحون سريعة - <small style='color:#22c55e'>{dish_tbl}</small></h4><div id=quickDishes>⏳...</div></div>
        <div class=card><h4>📜 سجل البنج</h4><div id=pingLog style='max-height:200px;overflow:auto;font-size:12px'></div></div>
        </div><script>
        async function doSinglePing(){{
        let ip=document.getElementById('pingIp').value.trim(); if(!ip){{alert('اكتب IP');return;}}
        let out=document.getElementById('pingResult'); out.textContent='⏳ فحص '+ip+'...'; out.style.color='#ffbe4d';
        try{{let r=await fetch('/api/ping?ip='+encodeURIComponent(ip),{{cache:'no-store'}}); let j=await r.json(); out.textContent=j.out; out.style.color=j.ok?'#22c55e':'#ef4444'; addLog(ip,j.ok?'✅':'❌',j.out.slice(0,60));}}catch(e){{out.textContent='❌ '+e;}}
        }}
        async function doTcpPing(){{
        let ip=document.getElementById('pingIp').value.trim(); let port=document.getElementById('pingPort').value.trim()||'80'; if(!ip){{alert('IP');return;}}
        let out=document.getElementById('pingResult'); out.textContent='⏳ '+ip+':'+port+'...';
        try{{let r=await fetch('/api/ping_tcp?ip='+encodeURIComponent(ip)+'&port='+port); let j=await r.json(); out.textContent=j.out; out.style.color=j.ok?'#22c55e':'#ef4444';}}catch(e){{out.textContent='خطأ';}}
        }}
        function clearPing(){{document.getElementById('pingResult').textContent='جاهز...';}}
        function addLog(ip,status,msg){{let l=document.getElementById('pingLog'); let d=new Date().toLocaleTimeString(); l.innerHTML='<div style="padding:6px 8px;border-bottom:1px solid #ffffff08"><span>'+status+' '+ip+' - '+msg.slice(0,50)+'</span></div>'+l.innerHTML;}}
        async function pingAllDishes(){{
        let out=document.getElementById('pingResult'); out.textContent='🚀 فحص...';
        try{{let r=await fetch('/api/search?q=192'); let d=await r.json(); out.textContent=''; for(let dish of d.filter(x=>x.page==='dishes').slice(0,20)){{out.textContent+='⏳ '+dish.sub+'\\n'; try{{let pr=await fetch('/api/ping?ip='+encodeURIComponent(dish.sub)); let pj=await pr.json(); out.textContent+= (pj.ok?'✅ ':'❌ ')+dish.sub+' -> '+pj.out.slice(0,60)+'\\n';}}catch(e){{}} await new Promise(r=>setTimeout(r,200));}}}}catch(e){{out.textContent='خطأ: '+e;}}
        }}
        (async()=>{{try{{let r=await fetch('/api/search?q=192'); let d=await r.json(); let h=''; d.filter(x=>x.page==='dishes').slice(0,8).forEach(x=>{{h+='<div style="display:flex;justify-content:space-between;padding:8px 10px;border-bottom:1px solid #ffffff08"><span>🌐 '+x.sub+' - '+x.title+'</span><button class=btn-gold onclick="document.getElementById(\\'pingIp\\').value=\\''+x.sub+'\\'; doSinglePing()" style="padding:5px 10px">Ping</button></div>';}}); document.getElementById('quickDishes').innerHTML=h||'لا يوجد';}}catch(e){{}}}})();
        </script>'''
    if v=='dishes':
        rs=qall(f"SELECT * FROM {dish_tbl} ORDER BY id DESC LIMIT 300")
        rows_html=""
        for r in rs:
            dn=esc(r.get('dish_name') or 'صحن');ip=esc(r.get('ip') or '');loc=esc(r.get('location') or '');rid=r['id']
            rows_html+=f'<div class="card anim" id="dish-{rid}" data-name="{dn}" data-ip="{ip}" data-loc="{loc}" style="display:flex;justify-content:space-between"><div><b>{dn}</b><br><a href="http://{ip}" target=_blank style="background:#000;color:#ffbe4d;padding:5px 10px;border-radius:8px;font-family:monospace;text-decoration:none">🌐 {ip}</a><br><small style="color:#888">{loc}</small></div><div style="display:flex;flex-direction:column;gap:6px"><button class=btn-gold onclick="quickPingD({rid})" style="padding:7px 12px;background:linear-gradient(90deg,#22c55e,#16a34a);color:#fff">📶</button><div style="display:flex;gap:4px"><button class=btn-gold onclick="editDish({rid})" style="padding:7px 9px">✏</button><button class=btn-del onclick="askDel(\'/del_dish/{rid}\')" style="padding:7px 9px">🗑</button></div></div></div>'
        return f'''<div style='max-width:900px;margin:0 auto'><div class=card><div style='display:flex;justify-content:space-between;flex-wrap:wrap'><h3>📡 الصحون - {len(rs)}</h3><a href='/api/export/dishes' class=btn-gold style='text-decoration:none;padding:7px 12px'>📗 Excel</a></div><form data-ajax method=post action=/add_dish style='display:flex;gap:6px;flex-wrap:wrap;margin-top:10px'><input name=dish_name placeholder='اسم الصحن' required style='flex:1'><input name=ip placeholder='192.168.1.1' required style='flex:1'><input name=location placeholder='موقع' style='flex:1'><button class=btn-gold>➕ حفظ</button></form><input id=searchBox placeholder='🔍 بحث...' oninput="searchDishes(this.value)" style='margin-top:10px;width:100%;padding:12px;border-radius:12px;background:#0f1424;border:1px solid #ffffff18'></div><div id=dl>{rows_html}</div></div><script>
        function editDish(id){{let c=document.getElementById('dish-'+id);document.getElementById('editModal').classList.add('show');document.getElementById('editBody').innerHTML='<input id=edit_dish_name value="'+c.dataset.name+'" style="width:100%;padding:12px;margin:4px 0"><input id=edit_ip value="'+c.dataset.ip+'" style="width:100%;padding:12px;margin:4px 0"><input id=edit_loc value="'+c.dataset.loc+'" style="width:100%;padding:12px;margin:4px 0"><button onclick="saveDish('+id+')" class=btn-gold style="width:100%;padding:12px">💾 حفظ</button>';}}
        function saveDish(id){{let nn=document.getElementById('edit_dish_name').value;let ii=document.getElementById('edit_ip').value;let ll=document.getElementById('edit_loc').value;fetch('/edit_dish/'+id,{{method:'POST',body:new URLSearchParams({{dish_name:nn,ip:ii,location:ll}})}}).then(()=>{{closeEditModal();loadPage('dishes',true);}});}}
        function quickPingD(id){{let c=document.getElementById('dish-'+id);loadPage('ping');setTimeout(()=>{{let inp=document.getElementById('pingIp');if(inp){{inp.value=c.dataset.ip;doSinglePing();}}}},300);}}
        function searchDishes(q){{q=(q||'').toLowerCase();document.querySelectorAll('[id^=dish-]').forEach(card=>{{let txt=(card.dataset.name+card.dataset.ip+card.dataset.loc).toLowerCase();card.style.display=txt.includes(q)?'flex':'none';}});}}
        </script>'''
    if v=='towers':
        rs=qall("SELECT * FROM towers ORDER BY id DESC")
        rows="".join([f"<div class='card anim' id='tower-{r['id']}' data-name='{esc(r['name'])}' data-area='{esc(r['area'] or '')}' data-lat='{r.get('lat') or 0}' data-lng='{r.get('lng') or 0}'><div style='display:flex;justify-content:space-between'><div><b>🗼 {esc(r['name'])}</b><br><small>{esc(r['area'] or '')}</small></div><div style='display:flex;gap:5px'><button class=btn-gold onclick=\"openEditTower({r['id']})\" style='padding:8px 10px'>✏</button><button class=btn-del onclick=\"askDel('/del_tower/{r['id']}')\" style='padding:8px 10px'>🗑</button></div></div></div>" for r in rs])
        return f'''<div style='max-width:700px;margin:0 auto'><div class=card><h3>🗼 الأبراج</h3><form data-ajax method=post action=/add_tower style='display:flex;gap:6px;flex-wrap:wrap;margin-top:8px'><input name=name placeholder='اسم البرج' required style='flex:1'><input name=area placeholder='المنطقة' style='flex:1'><input name=lat placeholder='lat' style='flex:0.6'><input name=lng placeholder='lng' style='flex:0.6'><button class=btn-gold>➕</button></form></div>{rows}</div><script>
        function openEditTower(id){{let c=document.getElementById('tower-'+id);document.getElementById('editModal').classList.add('show');document.getElementById('editBody').innerHTML='<input id=edit_t_name value="'+c.dataset.name+'" style="width:100%;margin:6px 0;padding:12px"><input id=edit_t_area value="'+c.dataset.area+'" style="width:100%;margin:6px 0;padding:12px"><input id=edit_t_lat value="'+c.dataset.lat+'" style="width:100%;margin:6px 0;padding:12px"><input id=edit_t_lng value="'+c.dataset.lng+'" style="width:100%;margin:6px 0;padding:12px"><button onclick="saveTower('+id+')" class=btn-gold style="width:100%;padding:12px">💾 حفظ</button>';}}
        function saveTower(id){{let nn=document.getElementById('edit_t_name').value;let aa=document.getElementById('edit_t_area').value;let la=document.getElementById('edit_t_lat').value;let ln=document.getElementById('edit_t_lng').value;fetch('/edit_tower/'+id,{{method:'POST',body:new URLSearchParams({{name:nn,area:aa,lat:la,lng:ln}})}}).then(()=>{{closeEditModal();loadPage('towers',true);}});}}
        </script>'''
    if v=='subs':
        rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 200")
        rows="".join([f"<div class='card anim' id='sub-{r['id']}' data-name='{esc(r['name'])}' data-phone='{esc(r['phone'] or '')}' data-note='{esc(r['note'] or '')}' style='display:flex;justify-content:space-between'><div><b>{esc(r['name'])}</b><br>📞 {esc(r['phone'] or '')}</div><div style='display:flex;gap:5px'><button class=btn-gold onclick=\"openEditSub({r['id']})\" style='padding:8px 10px'>✏</button><button class=btn-del onclick=\"askDel('/del_sub/{r['id']}')\" style='padding:8px 10px'>🗑</button></div></div>" for r in rs])
        return f'''<div style='max-width:700px;margin:0 auto'><div class=card><h3>👥 المشتركين</h3><form data-ajax method=post action=/add_sub style='display:flex;gap:5px;flex-wrap:wrap'><input name=name placeholder='الاسم' required style='flex:1'><input name=phone placeholder='رقم' style='flex:1'><input name=note placeholder='ملاحظة' style='flex:1'><button class=btn-gold>➕</button></form></div>{rows}<script>
        function openEditSub(id){{let c=document.getElementById('sub-'+id);document.getElementById('editModal').classList.add('show');document.getElementById('editBody').innerHTML='<input id=edit_s_name value="'+c.dataset.name+'" style="width:100%;margin:6px 0;padding:12px"><input id=edit_s_phone value="'+c.dataset.phone+'" style="width:100%;margin:6px 0;padding:12px"><input id=edit_s_note value="'+c.dataset.note+'" style="width:100%;margin:6px 0;padding:12px"><button onclick="saveSub('+id+')" class=btn-gold style="width:100%;padding:12px">💾</button>';}}
        function saveSub(id){{let nn=document.getElementById('edit_s_name').value;let pp=document.getElementById('edit_s_phone').value;let no=document.getElementById('edit_s_note').value;fetch('/edit_sub/'+id,{{method:'POST',body:new URLSearchParams({{name:nn,phone:pp,note:no}})}}).then(()=>{{closeEditModal();loadPage('subs',true);}});}}
        </script>'''
    if v=='ledger':
        rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 200")
        rows="".join([f"<div class='card anim' id='led-{r['id']}' data-name='{esc(r['name'])}' data-amount='{r['amount']}'><div style='display:flex;justify-content:space-between'><div><b>{esc(r['name'])}</b> - <b style='color:#ffbe4d'>{r['amount']}</b></div><div><button class=btn-gold onclick=\"openEditLed({r['id']})\" style='padding:7px 9px'>✏</button><button class=btn-del onclick=\"askDel('/del_ledger/{r['id']}')\" style='padding:7px 9px'>🗑</button></div></div></div>" for r in rs])
        return f'''<div style='max-width:700px;margin:0 auto'><div class=card><h3>📒 الحسابات</h3><form data-ajax method=post action=/add_ledger style='display:flex;gap:5px;flex-wrap:wrap'><input name=name placeholder='الاسم' required style='flex:1'><input name=amount type=number step=0.01 placeholder='المبلغ' required style='flex:1'><input name=note placeholder='ملاحظة' style='flex:1'><select name=currency style='flex:0.5'><option>USD</option><option>SYP</option></select><button class=btn-gold>➕</button></form></div>{rows}<script>
        function openEditLed(id){{let c=document.getElementById('led-'+id);document.getElementById('editModal').classList.add('show');document.getElementById('editBody').innerHTML='<input id=edit_l_name value="'+c.dataset.name+'" style="width:100%;margin:6px 0;padding:12px"><input id=edit_l_amount value="'+c.dataset.amount+'" style="width:100%;margin:6px 0;padding:12px"><button onclick="saveLed('+id+')" class=btn-gold style="width:100%;padding:12px">💾</button>';}}
        function saveLed(id){{let nn=document.getElementById('edit_l_name').value;let aa=document.getElementById('edit_l_amount').value;fetch('/edit_ledger/'+id,{{method:'POST',body:new URLSearchParams({{name:nn,amount:aa,note:'',currency:'USD'}})}}).then(()=>{{closeEditModal();loadPage('ledger',true);}});}}
        </script>'''
    if v=='logs':
        rs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 200")
        rows="".join([f"<div class='card anim' style='font-size:13px;border-left:3px solid #ffbe4d'><b style='color:#ffbe4d'>{esc(r['user_phone'])}</b> {esc(r['action'])} - {esc(r['detail'])}<br><small style='color:#777'>{esc(r['time'])}</small></div>" for r in rs])
        return f"<div style='max-width:900px;margin:0 auto'><div class=card style='display:flex;justify-content:space-between'><h3>📜 السجل</h3><a href='/api/export/logs' class=btn-gold style='text-decoration:none;padding:7px 12px'>📗 Excel</a></div>{rows or 'لا يوجد'}</div>"
    if v=='network':
        dishes=qall(f"SELECT * FROM {get_dish_table()} ORDER BY id DESC LIMIT 100")
        rows="".join([f"<div class='card anim' id='net-{d['id']}' data-ip='{esc(d.get('ip',''))}' style='display:flex;justify-content:space-between'><div><b>{esc(d.get('dish_name') or 'صحن')}</b> - {esc(d.get('ip',''))}<br><small class='net-out'>⏳...</small></div><button class=btn-gold onclick='checkOne({d['id']})'>📶</button></div>" for d in dishes])
        return f'''<div style='max-width:800px;margin:0 auto'><div class=card><h3>📊 حالة الشبكة LIVE</h3><button class=btn-gold onclick='checkAll()' style='width:100%;background:linear-gradient(90deg,#22c55e,#16a34a);color:#fff;padding:12px'>🚀 فحص الكل</button><div id=summary style='margin-top:10px;font-weight:800'></div></div>{rows}<script>
        async function checkOne(id){{let c=document.getElementById('net-'+id);let out=c.querySelector('.net-out');out.textContent='⏳...';try{{let r=await fetch('/api/ping?ip='+c.dataset.ip);let j=await r.json();out.textContent=j.out.slice(0,80);out.style.color=j.ok?'#22c55e':'#ef4444';}}catch(e){{out.textContent='❌';}}}}
        async function checkAll(){{for(let c of document.querySelectorAll('[id^=net-]')){{let out=c.querySelector('.net-out');out.textContent='⏳...'; try{{let r=await fetch('/api/ping?ip='+c.dataset.ip);let j=await r.json();out.textContent=j.ok?'✅ '+j.out.slice(0,50):'❌ '+j.out.slice(0,50);out.style.color=j.ok?'#22c55e':'#ef4444';}}catch(e){{}} await new Promise(r=>setTimeout(r,200));}}}}
        </script></div>'''
    if v=='map':
        towers=qall("SELECT * FROM towers")
        tj_json=json.dumps([{"name":t['name'],"area":t.get('area') or '',"lat":float(t.get('lat') or 35.1318),"lng":float(t.get('lng') or 36.7578)} for t in towers],ensure_ascii=False)
        return f'''<div class=card style='padding:10px'><div style='display:flex;gap:6px;margin-bottom:8px;flex-wrap:wrap'><input id=mapSearch placeholder='🔍 بحث برج...' style='flex:1;min-width:140px;padding:10px;border-radius:10px;background:#1f2937;border:1px solid #ffffff15;color:#fff'><button class=btn-gold onclick="doMapSearch()">بحث</button><button class=btn-gold onclick="locateMe()" style='background:#22c55e;color:#fff'>📍 موقعي</button><span id=coordsLabel style='color:#ffbe4d'>📍 -</span></div><div id=map style='height:72vh;min-height:460px;border-radius:16px;background:#0f172a'></div></div><script>
        let _towers={tj_json}; let _map=null;
        window.doMapSearch=function(){{let q=document.getElementById('mapSearch').value.trim().toLowerCase(); let f=_towers.find(t=>t.name.toLowerCase().includes(q)); if(f && _map) _map.flyTo([f.lat,f.lng],16);}}
        window.locateMe=function(){{if(_map && navigator.geolocation) navigator.geolocation.getCurrentPosition(p=>{{_map.flyTo([p.coords.latitude,p.coords.longitude],16); L.marker([p.coords.latitude,p.coords.longitude]).addTo(_map).bindPopup('📍 موقعك').openPopup();}});}}
        function initMap(){{if(typeof L==='undefined'){{setTimeout(initMap,200);return;}} _map=L.map('map').setView([35.1318,36.7578],13); L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png').addTo(_map); _towers.forEach(t=>{{L.marker([t.lat,t.lng]).addTo(_map).bindPopup(t.name);}}); _map.on('click',e=>{{document.getElementById('coordsLabel').textContent='📍 '+e.latlng.lat.toFixed(5)+','+e.latlng.lng.toFixed(5);}}); setTimeout(()=>_map.invalidateSize(),300);}}
        initMap();
        </script>'''
    if v=='settings':
        us=qall("SELECT * FROM users ORDER BY phone DESC")
        uh="".join([f'<div class="card anim" id="user-{esc(u["phone"])}" data-phone="{esc(u["phone"])}" data-role="{esc(u.get("role") or "")}" style="display:flex;justify-content:space-between"><div>{esc(u.get("username") or "")} - {esc(u["phone"])}</div><div><button class=btn-gold onclick="openEditUser(\'{esc(u["phone"])}\')">✏</button> <button class=btn-del onclick="askDel(\'/del_user/{esc(u["phone"])}\')">🗑</button></div></div>' for u in us])
        return f'''<div style='max-width:800px;margin:0 auto'><div class=card><h3>👤 اضافة يوزر</h3><form data-ajax method=post action=/add_user style='display:flex;gap:8px'><input name=user_field placeholder='رقم' required style='flex:1'><input name=password type=password placeholder='باسورد' required style='flex:1'><select name=role style='flex:0.5'><option value=tech>فني</option><option value=manager>مدير</option></select><button class=btn-gold>➕</button></form></div>{uh}</div>'''
    return "<div class=card>ok</div>"

def layout(c,v='home'):
    cur_user=qone("SELECT * FROM users WHERE phone=?",(session.get('phone') or '',))
    role=(cur_user.get('role') or 'tech') if cur_user else 'tech'
    return f"""<html dir=rtl lang=ar><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<link rel=stylesheet href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'>
<style>
*{{box-sizing:border-box;font-family:system-ui}}body{{margin:0;background:#0a0e2a;color:#fff}}
.top{{position:fixed;top:0;left:0;right:0;height:60px;background:#0f172a;color:#fff;display:flex;align-items:center;justify-content:space-between;padding:0 14px;z-index:1003;border-bottom:1px solid #ffffff12}}
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
</style></head><body>
<div id=overlay onclick="toggleSb(false)"></div>
<div class=sidebar id=sb>
<div style='padding:0 16px 8px;border-bottom:1px solid #ffffff0a'><b>OMAIA <span style='color:#ffbe4d'>ISP</span> <small style='color:#22c55e'>نار</small></b></div>
<a href="javascript:loadPage('home')" id=nav-home>🏠 الرئيسية</a>
<a href="javascript:loadPage('ping')" id=nav-ping>📶 Ping</a>
<a href="javascript:loadPage('network')" id=nav-network>📊 الشبكة</a>
<a href="javascript:loadPage('dishes')" id=nav-dishes>📡 الصحون</a>
<a href="javascript:loadPage('towers')" id=nav-towers>🗼 الأبراج</a>
<a href="javascript:loadPage('subs')" id=nav-subs>👥 المشتركين</a>
<a href="javascript:loadPage('ledger')" id=nav-ledger>📒 الحسابات</a>
<a href="javascript:loadPage('map')" id=nav-map>🗺 الخريطة</a>
<a href="javascript:loadPage('settings')" id=nav-settings>⚙ الإعدادات</a>
<a href="javascript:logoutFast()" style='margin-top:10px;background:#ef444422'>🚪 خروج</a>
</div>
<div class=top><span onclick="toggleSb()" style='font-size:24px;cursor:pointer'>☰</span><input id=topsearch placeholder='🔍 بحث...' oninput="globalSearchTop(this.value)" style='background:#1f2937;border:1px solid #ffffff15;color:#fff;padding:8px 12px;border-radius:10px;width:42px;transition:width.2s' onfocus="this.style.width='160px'" onblur="setTimeout(()=>this.style.width='42px',200)"><div style='font-weight:900'>OMAIA <span style='color:#ffbe4d'>ISP</span></div></div>
<div id=searchResults style='position:fixed;top:64px;right:10px;left:10px;max-width:420px;margin:0 auto;background:#1e2433;border:1px solid #ffffff15;border-radius:12px;z-index:1500;display:none;max-height:50vh;overflow:auto'></div>
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
window.globalSearchTop=async function(q){{let b=document.getElementById('searchResults'); if(!q){{b.style.display='none'; return;}} try{{let r=await fetch('/api/search?q='+encodeURIComponent(q)); let d=await r.json(); if(!d.length){{b.style.display='none'; return;}} let h=''; d.forEach(x=>{{h+='<div onclick="loadPage(\\''+x.page+'\\');b.style.display=\\'none\\'" style="padding:9px 12px;border-top:1px solid #ffffff08;cursor:pointer"><b>'+x.title+'</b> <small style="color:#888">'+x.sub+'</small></div>';}}); b.innerHTML=h; b.style.display='block';}}catch(e){{}}}};
window.logoutFast=async function(){{await fetch('/api/logout',{{method:'POST'}}); location.replace('/login');}};
bind(); execScripts();
</script></body></html>"""

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
