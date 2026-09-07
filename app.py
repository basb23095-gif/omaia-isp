from flask import Flask, request, redirect, session, jsonify, Response
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, html, ipaddress, subprocess, json, socket, platform, io, csv, datetime
try:
    import psycopg2, psycopg2.extras
except:
    psycopg2 = None
import sqlite3

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY","omia-sec-2026-CHANGE-ME")
DATABASE_URL = os.environ.get("DATABASE_URL","").strip().replace("postgresql://","postgres://")
USE_PG = bool(DATABASE_URL.startswith("postgres://") and psycopg2)
_pg = None

def esc(s): return html.escape(str(s or ''), quote=True)

def db():
    global _pg
    if USE_PG:
        try:
            if _pg:
                try:
                    c=_pg.cursor();c.execute("SELECT 1");c.close();return _pg
                except:
                    try:_pg.close()
                    except:pass
                    _pg=None
        except: _pg=None
        try:
            _pg=psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=10)
            _pg.autocommit=True
            return _pg
        except: pass
    try:
        c=sqlite3.connect("omia.db",check_same_thread=False)
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
    except Exception as e:
        cc(c)
        print("qall err",e,q)
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
    except Exception as e:
        cc(c)
        print("qexec err",e)

def add_log(user_phone, action, detail):
    try:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)",(user_phone or 'unknown', action, detail, now))
        qexec("INSERT INTO notifications(title,msg,time) VALUES(?,?,?)",(action, str(user_phone)+": "+str(detail), now))
    except: pass

def init():
    ss=[
    "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,username TEXT)",
    "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,note TEXT)",
    "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,amount REAL,note TEXT,currency TEXT)",
    "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,dish_name TEXT)",
    "CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,area TEXT,lat REAL,lng REAL)",
    "CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,user_phone TEXT,action TEXT,detail TEXT,time TEXT)",
    "CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,msg TEXT,time TEXT,read INTEGER DEFAULT 0)"
    ]
    if USE_PG:
        ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
    for s in ss:
        qexec(s)
    if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",('05344851045',generate_password_hash('admin2024'),'manager','admin'))
    if not qone("SELECT * FROM towers WHERE name=?",('نقطة حماة الرئيسية',)):
        qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",('نقطة حماة الرئيسية','حماة',35.1318,36.7578))

init()

def login_required(f):
    @wraps(f)
    def w(*a,**kw):
        if not session.get('phone'):
            return redirect('/login')
        return f(*a,**kw)
    return w

def is_manager():
    u = qone("SELECT * FROM users WHERE phone=?",(session.get('phone') or '',))
    if not u: return False
    return (u.get('role') or '').lower() == 'manager'

def role_required_manager(f):
    @wraps(f)
    def w(*a,**kw):
        if not is_manager():
            return "🚫 ممنوع - صلاحية مدير فقط", 403
        return f(*a,**kw)
    return w

def is_valid_ip(ip):
    ip=ip.strip()
    if not ip: return False
    try:
        ipaddress.ip_address(ip)
        return True
    except:
        return len(ip)>=7 and '.' in ip

def is_internal_ip(ip):
    try:
        o=ipaddress.ip_address(ip.strip())
        return o.is_private and not o.is_loopback and not o.is_multicast and not o.is_unspecified
    except: return False

# ---- PUBLIC PING FOR cron-job.org ----
@app.route('/ping')
@app.route('/health')
def public_ping():
    return jsonify(ok=True, status='alive', app='omaia-isp', time=datetime.datetime.now().isoformat())

@app.route('/api/ping')
@login_required
def api_ping():
    ip=request.args.get('ip','').strip()
    if not ip:
        return jsonify(ok=False,out='لا يوجد IP')
    if not is_valid_ip(ip):
        return jsonify(ok=False,out='IP غير صالح')
    try:
        cmd=['ping','-c','1','-W','2',ip] if platform.system().lower()!='windows' else ['ping','-n','1','-w','2000',ip]
        out=subprocess.check_output(cmd,timeout=3,stderr=subprocess.STDOUT).decode(errors='ignore')
        ok='ttl=' in out.lower() or 'bytes from' in out.lower() or '1 received' in out.lower()
        if ok:
            return jsonify(ok=True,out='✅ متصل - '+out[:300])
    except FileNotFoundError:
        pass
    except Exception as e:
        if 'No such file' not in str(e):
            pass
    common_ports=[80,443,8080,8291,22,23,53,8000,8081,8728]
    for port in common_ports:
        try:
            s=socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.2)
            if s.connect_ex((ip, port))==0:
                s.close()
                return jsonify(ok=True,out=f'✅ متصل - منفذ {port} مفتوح - {ip}:{port}')
            s.close()
        except: continue
    return jsonify(ok=False,out=f'❌ {ip} لا يرد')

@app.route('/api/ping_tcp')
@login_required
def api_ping_tcp():
    ip=request.args.get('ip','').strip()
    port=int(request.args.get('port','80') or 80)
    if not is_valid_ip(ip):
        return jsonify(ok=False,out='IP غير صالح')
    try:
        s=socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        r=s.connect_ex((ip,port))
        s.close()
        return jsonify(ok=r==0,out=f'✅ {ip}:{port} مفتوح' if r==0 else f'❌ {ip}:{port} مغلق')
    except Exception as e:
        return jsonify(ok=False,out=f'❌ {e}')

@app.route('/api/notifications')
@login_required
def api_noti():
    rows=qall("SELECT * FROM notifications ORDER BY id DESC LIMIT 30")
    unread=qone("SELECT COUNT(*) c FROM notifications WHERE read=0")
    cnt = unread.get('c',0) if unread else 0
    return jsonify(rows=rows, unread=cnt)

@app.route('/api/notifications/read', methods=['POST'])
@login_required
def api_noti_read():
    qexec("UPDATE notifications SET read=1")
    return jsonify(ok=True)

@app.route('/api/logs')
@login_required
def api_logs():
    rows=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 200")
    return jsonify(rows)

@app.route('/api/network_status')
@login_required
def api_network():
    dishes=qall("SELECT * FROM dish_ips ORDER BY id DESC")
    towers=qall("SELECT * FROM towers ORDER BY id DESC")
    subs_cnt=(qone("SELECT COUNT(*) c FROM subs") or {}).get('c',0)
    return jsonify(dishes=len(dishes), towers=len(towers), subs=subs_cnt, dishes_list=dishes[:50])

@app.route('/toggle_lang')
@login_required
def toggle_lang_route():
    cur=session.get('lang','ar')
    session['lang']='en' if cur=='ar' else 'ar'
    return jsonify(ok=True)

@app.route('/api/login',methods=['POST'])
@login_required
def api_login_fast():
    return jsonify(ok=True)

@app.route('/api/login_public',methods=['POST'])
def api_login_public():
    uin=request.form.get('userin','').strip()
    pw=request.form.get('password','')
    u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
    if u and check_password_hash(u['password'],pw):
        session['phone']=u['phone']
        session['username']=u.get('username') or u['phone']
        add_log(u['phone'], 'دخل النظام', 'تسجيل دخول')
        return jsonify(ok=True, role=u.get('role'))
    return jsonify(ok=False,msg='خطأ بالدخول'),401

@app.route('/api/export/<tbl>')
@login_required
def api_export(tbl):
    output=io.StringIO()
    w=csv.writer(output)
    if tbl=='dishes':
        rows=qall("SELECT * FROM dish_ips ORDER BY id DESC")
        w.writerow(['ID','اسم الصحن','IP','الموقع'])
        for r in rows: w.writerow([r['id'],r.get('dish_name',''),r.get('ip',''),r.get('location','')])
        fname='dishes.csv'
    elif tbl=='subs':
        rows=qall("SELECT * FROM subs ORDER BY id DESC")
        w.writerow(['ID','الاسم','رقم','ملاحظة'])
        for r in rows: w.writerow([r['id'],r.get('name',''),r.get('phone',''),r.get('note','')])
        fname='subs.csv'
    elif tbl=='users':
        rows=qall("SELECT phone,username,role FROM users ORDER BY phone DESC")
        w.writerow(['يوزر/رقم','اسم المستخدم','الرتبة'])
        for r in rows: w.writerow([r.get('phone',''),r.get('username',''),r.get('role','')])
        fname='users.csv'
    elif tbl=='towers':
        rows=qall("SELECT * FROM towers ORDER BY id DESC")
        w.writerow(['ID','اسم البرج','المنطقة','lat','lng'])
        for r in rows: w.writerow([r['id'],r.get('name',''),r.get('area',''),r.get('lat',''),r.get('lng','')])
        fname='towers.csv'
    elif tbl=='logs':
        rows=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 1000")
        w.writerow(['ID','المستخدم','العملية','التفاصيل','الوقت'])
        for r in rows: w.writerow([r['id'],r.get('user_phone',''),r.get('action',''),r.get('detail',''),r.get('time','')])
        fname='logs.csv'
    else:
        w.writerow(['ID'])
        fname='export.csv'
    return Response(output.getvalue(),mimetype='text/csv; charset=utf-8',headers={'Content-Disposition': f'attachment; filename={fname}'})

@app.route('/')
def ix():
    return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        uin=request.form.get('userin','').strip()
        pw=request.form.get('password','')
        u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
        if u and check_password_hash(u['password'],pw):
            session['phone']=u['phone']
            session['username']=u.get('username') or u['phone']
            return redirect('/dash')
        return "<script>alert('خطأ بالدخول');location.href='/login'</script>"
    return """<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<style>
*{box-sizing:border-box;font-family:system-ui}
body{margin:0;min-height:100vh;background:radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 55%, #070a1f 100%);display:flex;flex-direction:column;align-items:center;justify-content:center;color:#fff}
.card{background:linear-gradient(180deg, #222b45cc, #1a2035cc);backdrop-filter:blur(16px);border:1px solid #ffffff18;padding:26px;border-radius:22px;width:92%;max-width:380px;box-shadow:0 20px 60px #0008, inset 0 1px 0 #ffffff15;animation:fadeIn .5s ease}
@keyframes fadeIn{from{opacity:0;transform:translateY(20px) scale(.98)}to{opacity:1;transform:none}}
input{width:100%;padding:14px;margin:9px 0;background:#0f1424;border:1px solid #ffffff22;color:#fff;border-radius:14px;transition:all .2s;font-size:15px}
input:focus{border-color:#ffbe4d;box-shadow:0 0 0 3px #ffbe4d22;outline:none}
.btn{width:100%;padding:14px;border:0;border-radius:14px;background:linear-gradient(90deg,#ffbe4d,#ffb020,#ff9d00);color:#111;font-weight:900;font-size:17px;cursor:pointer;margin-top:12px;transition:all .2s;box-shadow:0 8px 24px #ffbe4d44}
.btn:hover{transform:translateY(-2px);box-shadow:0 12px 32px #ffbe4d66}
.btn:active{transform:scale(.97)}
.save-row{display:flex;align-items:center;gap:8px;margin:10px 0;font-size:13px;color:#aaa}
.save-row input{width:auto;margin:0}
#loader{position:fixed;inset:0;background:radial-gradient(100% 100% at 50% 50%, #121a35 0%, #0a0e2a 100%);z-index:9999;display:flex;flex-direction:column;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:opacity .35s}
#loader.show{opacity:1;pointer-events:auto}
.spinner{width:48px;height:48px;border:4px solid #ffffff18;border-top-color:#ffbe4d;border-radius:50%;animation:spin .8s linear infinite;box-shadow:0 0 20px #ffbe4d44}
@keyframes spin{to{transform:rotate(360deg)}}
.loader-text{margin-top:16px;font-weight:800;color:#ffbe4d;letter-spacing:.5px;animation:pulse 1s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.6}}
.logo{font-size:32px;font-weight:900;letter-spacing:1px;margin-bottom:14px;text-shadow:0 2px 20px #ffbe4d55}
.logo span{color:#ffbe4d}
</style></head><body>
<div id=loader><div class=spinner></div><div class=loader-text>⏳ جاري التحميل...</div></div>
<div class=logo>OMAIA <span>ISP</span></div>
<div class=card>
<form id=loginForm>
<input name=userin id=userin placeholder='📱 رقم / يوزر' required autocomplete='username'>
<input name=password id=password type=password placeholder='🔑 كلمة السر' required autocomplete='current-password'>
<label class=save-row><input type=checkbox id=savePass> 💾 حفظ كلمة السر</label>
<button class=btn id=loginBtn>✨ دخول فوري</button>
<div id=msg style='text-align:center;margin-top:10px;color:#ff6b6b;font-size:13px;min-height:18px'></div>
</form>
<div style='text-align:center;margin-top:14px'><a href='https://wa.me/905344851045' style='color:#22c55e;text-decoration:none;font-weight:800;font-size:14px'>💬 واتساب الدعم الفني فقط</a></div>
</div>
<script>
let u=document.getElementById('userin'), p=document.getElementById('password'), s=document.getElementById('savePass');
let su=localStorage.getItem('omaia_user'), sp=localStorage.getItem('omaia_pass');
if(su){u.value=su; if(sp){p.value=sp; s.checked=true;}}
document.getElementById('loginForm').addEventListener('submit',async e=>{
 e.preventDefault();
 let btn=document.getElementById('loginBtn'), msg=document.getElementById('msg'), loader=document.getElementById('loader');
 btn.textContent='⏳ جاري التحميل...'; btn.disabled=true; loader.classList.add('show');
 try{
  let fd=new FormData(e.target);
  let r=await fetch('/api/login_public',{method:'POST',body:fd});
  let j=await r.json();
  if(j.ok){
   if(s.checked){localStorage.setItem('omaia_user',u.value);localStorage.setItem('omaia_pass',p.value);}else{localStorage.removeItem('omaia_user');localStorage.removeItem('omaia_pass');}
   location.href='/dash?v=home';
  }else{msg.textContent=j.msg||'خطأ'; btn.textContent='✨ دخول فوري'; btn.disabled=false; loader.classList.remove('show');}
 }catch(err){msg.textContent='خطأ شبكة'; btn.textContent='✨ دخول فوري'; btn.disabled=false; loader.classList.remove('show');}
});
</script>
</body></html>"""

@app.route('/logout')
def lo():
    session.clear()
    return redirect('/login')

@app.route('/api/logout', methods=['POST'])
def api_logout():
    try: add_log(session.get('phone',''), 'خرج من النظام', 'تسجيل خروج')
    except: pass
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
    if not q:
        return jsonify([])
    like="%"+q+"%"
    results=[]
    for r in qall("SELECT * FROM dish_ips WHERE ip LIKE ? OR dish_name LIKE ? OR location LIKE ? ORDER BY id DESC LIMIT 30",(like,like,like)):
        results.append({"type":"dish","id":r['id'],"title":r.get('dish_name') or 'صحن',"sub":r.get('ip',''),"page":"dishes"})
    for r in qall("SELECT * FROM subs WHERE name LIKE ? OR phone LIKE ? OR note LIKE ? ORDER BY id DESC LIMIT 20",(like,like,like)):
        results.append({"type":"sub","id":r['id'],"title":r.get('name',''),"sub":r.get('phone',''),"page":"subs"})
    for r in qall("SELECT * FROM towers WHERE name LIKE ? OR area LIKE ? ORDER BY id DESC LIMIT 20",(like,like)):
        results.append({"type":"tower","id":r['id'],"title":r.get('name',''),"sub":r.get('area',''),"page":"towers"})
    for r in qall("SELECT * FROM users WHERE phone LIKE ? OR username LIKE ? ORDER BY phone DESC LIMIT 15",(like,like)):
        results.append({"type":"user","id":r['phone'],"title":r.get('phone',''),"sub":r.get('role',''),"page":"settings"})
    for r in qall("SELECT * FROM logs WHERE user_phone LIKE ? OR action LIKE ? OR detail LIKE ? ORDER BY id DESC LIMIT 20",(like,like,like)):
        results.append({"type":"log","id":r['id'],"title":r.get('action',''),"sub":r.get('user_phone',''),"page":"logs"})
    return jsonify(results)

@app.route('/toggle_theme')
@login_required
def tt():
    cur=session.get('theme','dark')
    session['theme']='light' if cur=='dark' else 'dark'
    return jsonify(ok=True,theme=session['theme'])

@app.route('/add_dish',methods=['POST'])
@login_required
def ad():
    ip=request.form.get('ip','').strip()
    name=request.form.get('dish_name','').strip()
    loc=request.form.get('location','').strip()
    if not ip: return "IP مطلوب",400
    if not is_valid_ip(ip): return "IP غير صالح - مثال 192.168.1.1",400
    ex=qone("SELECT * FROM dish_ips WHERE ip=?",(ip,))
    user=session.get('phone','')
    if ex:
        qexec("UPDATE dish_ips SET dish_name=?,location=? WHERE ip=?",(name,loc,ip))
        add_log(user, 'عدل صحن', name+" "+ip)
        return "ok updated"
    qexec("INSERT INTO dish_ips(ip,location,dish_name) VALUES(?,?,?)",(ip,loc,name))
    add_log(user, 'اضاف صحن', name+" "+ip)
    return "ok"

@app.route('/edit_dish/<int:i>',methods=['POST'])
@login_required
def ed(i):
    if not is_manager():
        return "ممنوع للفني",403
    qexec("UPDATE dish_ips SET dish_name=?,ip=?,location=? WHERE id=?",
          (request.form.get('dish_name',''),request.form.get('ip',''),request.form.get('location',''),i))
    add_log(session.get('phone',''), 'عدل صحن', f"id={i}")
    return "ok"

@app.route('/del_dish/<int:i>')
@login_required
def dd(i):
    if not is_manager():
        return "ممنوع للفني",403
    qexec("DELETE FROM dish_ips WHERE id=?",(i,))
    add_log(session.get('phone',''), 'حذف صحن', f"id={i}")
    return "ok"

@app.route('/add_tower',methods=['POST'])
@login_required
def at():
    lat=request.form.get('lat','').strip()
    lng=request.form.get('lng','').strip()
    try:
        la=float(lat) if lat else 35.1312
        ln=float(lng) if lng else 36.7578
    except:
        la=35.1312; ln=36.7578
    qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",
          (request.form.get('name',''),request.form.get('area',''),la,ln))
    add_log(session.get('phone',''), 'اضاف برج', request.form.get('name',''))
    return "ok"

@app.route('/del_tower/<int:i>')
@login_required
def dt(i):
    if not is_manager():
        return "ممنوع للفني",403
    qexec("DELETE FROM towers WHERE id=?",(i,))
    add_log(session.get('phone',''), 'حذف برج', f"id={i}")
    return "ok"

@app.route('/edit_tower/<int:i>',methods=['POST'])
@login_required
def et(i):
    if not is_manager():
        return "ممنوع للفني",403
    lat=request.form.get('lat','').strip()
    lng=request.form.get('lng','').strip()
    try:
        la=float(lat) if lat else 35.1318
        ln=float(lng) if lng else 36.7578
    except:
        la=35.1318; ln=36.7578
    qexec("UPDATE towers SET name=?,area=?,lat=?,lng=? WHERE id=?",
          (request.form.get('name',''),request.form.get('area',''),la,ln,i))
    add_log(session.get('phone',''), 'عدل برج', f"id={i}")
    return "ok"

@app.route('/add_sub',methods=['POST'])
@login_required
def asub():
    qexec("INSERT INTO subs(name,phone,note) VALUES(?,?,?)",
          (request.form.get('name',''),request.form.get('phone',''),request.form.get('note','')))
    add_log(session.get('phone',''), 'اضاف مشترك', request.form.get('name',''))
    return "ok"

@app.route('/del_sub/<int:i>')
@login_required
def dsub(i):
    if not is_manager():
        return "ممنوع للفني",403
    qexec("DELETE FROM subs WHERE id=?",(i,))
    return "ok"

@app.route('/edit_sub/<int:i>',methods=['POST'])
@login_required
def esub(i):
    if not is_manager():
        return "ممنوع للفني",403
    qexec("UPDATE subs SET name=?,phone=?,note=? WHERE id=?",
          (request.form.get('name',''),request.form.get('phone',''),request.form.get('note',''),i))
    return "ok"

@app.route('/add_ledger',methods=['POST'])
@login_required
def al():
    try: amt=float(request.form.get('amount') or 0)
    except: amt=0
    qexec("INSERT INTO ledger(name,amount,note,currency) VALUES(?,?,?,?)",
          (request.form.get('name',''),amt,request.form.get('note',''),request.form.get('currency','USD')))
    return "ok"

@app.route('/del_ledger/<int:i>')
@login_required
def dll(i):
    if not is_manager():
        return "ممنوع للفني",403
    qexec("DELETE FROM ledger WHERE id=?",(i,))
    return "ok"

@app.route('/edit_ledger/<int:i>',methods=['POST'])
@login_required
def el(i):
    if not is_manager():
        return "ممنوع للفني",403
    try: amt=float(request.form.get('amount') or 0)
    except: amt=0
    qexec("UPDATE ledger SET name=?,amount=?,note=?,currency=? WHERE id=?",
          (request.form.get('name',''),amt,request.form.get('note',''),request.form.get('currency','USD'),i))
    return "ok"

@app.route('/add_user',methods=['POST'])
@login_required
@role_required_manager
def au():
    ph=request.form.get('phone','').strip() or request.form.get('username','').strip() or request.form.get('user_field','').strip()
    if not ph: return "رقم مطلوب",400
    if qone("SELECT * FROM users WHERE phone=?",(ph,)):
        return "موجود مسبقاً",400
    qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",
          (ph,generate_password_hash(request.form.get('password','1234')),request.form.get('role','tech'),ph))
    add_log(session.get('phone',''), 'اضاف يوزر', ph)
    return "ok"

@app.route('/edit_user',methods=['POST'])
@login_required
@role_required_manager
def eu():
    old=request.form.get('old_phone','').strip()
    new_ph=request.form.get('phone','').strip() or request.form.get('user_field','').strip() or request.form.get('username','').strip()
    new_user=new_ph
    new_role=request.form.get('role','tech')
    new_pass=request.form.get('password','').strip()
    if not old: return "خطأ",400
    if new_pass:
        qexec("UPDATE users SET phone=?,username=?,role=?,password=? WHERE phone=?",
              (new_ph,new_user,new_role,generate_password_hash(new_pass),old))
    else:
        qexec("UPDATE users SET phone=?,username=?,role=? WHERE phone=?",
              (new_ph,new_user,new_role,old))
    if session.get('phone')==old:
        session['phone']=new_ph
    add_log(session.get('phone',''), 'عدل يوزر', f"{old} -> {new_ph}")
    return "ok"

@app.route('/del_user/<ph>')
@login_required
@role_required_manager
def du(ph):
    if ph=='05344851045':
        return "ممنوع حذف المدير",400
    qexec("DELETE FROM users WHERE phone=?",(ph,))
    return "ok"

@app.route('/change_pass',methods=['POST'])
@login_required
def cp():
    np=request.form.get('newpass','').strip()
    if not np: return "فارغة",400
    qexec("UPDATE users SET password=? WHERE phone=?",
          (generate_password_hash(np),session.get('phone')))
    return "ok"

def page_content(v):
    is_mgr = is_manager()
    # --- HOME ---
    if v=='home':
        ns=(qone("SELECT COUNT(*) c FROM subs") or {}).get('c',0)
        nd=(qone("SELECT COUNT(*) c FROM dish_ips") or {}).get('c',0)
        nt=(qone("SELECT COUNT(*) c FROM towers") or {}).get('c',0)
        nl=(qone("SELECT COUNT(*) c FROM ledger") or {}).get('c',0)
        logs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 5")
        log_html=""
        for l in logs:
            log_html+=f"<div style='display:flex;justify-content:space-between;padding:8px 10px;border-bottom:1px dashed #ffffff12'><div><b style='color:#ffbe4d'>{esc(l.get('user_phone',''))}</b> {esc(l.get('action',''))} <small style='color:#aaa'>{esc(l.get('detail','')[:40])}</small></div><small style='color:#777'>{esc(l.get('time',''))}</small></div>"
        return f"""
        <div style='max-width:900px;margin:0 auto'>
          <!-- كروت فخمة طافية - ارقام واضحة جدا -->
          <div style='display:grid;grid-template-columns:1fr 1fr;gap:14px'>
            <div class='card anim' onclick="loadPage('subs')" style='cursor:pointer;position:relative;overflow:hidden;background:linear-gradient(135deg,#1e2a4a 0%,#162040 100%);border:1px solid #ffffff18;box-shadow:0 10px 30px #0005, 0 0 0 1px #ffffff0a inset, 0 1px 0 #ffffff15 inset;transform:translateZ(0)'>
              <div style='position:absolute;top:-20px;right:-20px;width:80px;height:80px;background:radial-gradient(circle,#ffbe4d22 0%,transparent 70%);border-radius:50%'></div>
              <div style='display:flex;justify-content:space-between;align-items:center'><div><h3 style='margin:0;color:#aab4d0;font-size:13px;letter-spacing:.5px'>المشتركين</h3><h2 style='margin:6px 0 0;font-size:36px;font-weight:900;color:#fff;text-shadow:0 2px 10px #0008'>{ns}</h2><small style='color:#22c55e'>● نشط</small></div><div style='font-size:38px;opacity:.9'>👥</div></div>
            </div>
            <div class='card anim' onclick="loadPage('dishes')" style='cursor:pointer;position:relative;overflow:hidden;background:linear-gradient(135deg,#1e2f4a 0%,#162840 100%);border:1px solid #ffffff18;box-shadow:0 10px 30px #0005, inset 0 1px 0 #ffffff15;'>
              <div style='position:absolute;top:-20px;right:-20px;width:80px;height:80px;background:radial-gradient(circle,#22c55e22 0%,transparent 70%);border-radius:50%'></div>
              <div style='display:flex;justify-content:space-between;align-items:center'><div><h3 style='margin:0;color:#aab4d0;font-size:13px'>الصحون</h3><h2 style='margin:6px 0 0;font-size:36px;font-weight:900;color:#fff'>{nd}</h2><small style='color:#22c55e'>● متصل</small></div><div style='font-size:38px'>📡</div></div>
            </div>
            <div class='card anim' onclick="loadPage('towers')" style='cursor:pointer;position:relative;overflow:hidden;background:linear-gradient(135deg,#2a1e4a 0%,#201640 100%);border:1px solid #ffffff18;box-shadow:0 10px 30px #0005, inset 0 1px 0 #ffffff15;'>
              <div style='display:flex;justify-content:space-between;align-items:center'><div><h3 style='margin:0;color:#aab4d0;font-size:13px'>الأبراج</h3><h2 style='margin:6px 0 0;font-size:36px;font-weight:900;color:#fff'>{nt}</h2><small style='color:#a78bfa'>🗼 جاهز</small></div><div style='font-size:38px'>🗼</div></div>
            </div>
            <div class='card anim' onclick="loadPage('ledger')" style='cursor:pointer;position:relative;overflow:hidden;background:linear-gradient(135deg,#4a2a1e 0%,#402016 100%);border:1px solid #ffffff18;box-shadow:0 10px 30px #0005, inset 0 1px 0 #ffffff15;'>
              <div style='display:flex;justify-content:space-between;align-items:center'><div><h3 style='margin:0;color:#aab4d0;font-size:13px'>الحسابات</h3><h2 style='margin:6px 0 0;font-size:36px;font-weight:900;color:#fff'>{nl}</h2><small style='color:#ffbe4d'>💰</small></div><div style='font-size:38px'>📒</div></div>
            </div>
          </div>

          <!-- ازرار اكسل و pdf مرتبة -->
          <div class=card style='margin-top:14px;background:linear-gradient(180deg,#1e2433,#171e2f);border:1px solid #ffffff12'>
            <div style='display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px'>
              <h4 style='margin:0'>📊 التقارير السريعة</h4>
              <div style='display:flex;gap:8px;flex-wrap:wrap'>
                <a href='/api/export/dishes' class=btn-gold style='text-decoration:none;padding:9px 14px;border-radius:10px;background:linear-gradient(90deg,#22c55e,#16a34a);color:#fff;font-size:13px'>📗 Excel صحون</a>
                <a href='/api/export/subs' class=btn-gold style='text-decoration:none;padding:9px 14px;border-radius:10px;background:linear-gradient(90deg,#0ea5e9,#0284c7);color:#fff;font-size:13px'>📘 Excel مشتركين</a>
                <a href='/api/export/logs' class=btn-gold style='text-decoration:none;padding:9px 14px;border-radius:10px;background:linear-gradient(90deg,#8b5cf6,#7c3aed);color:#fff;font-size:13px'>📜 سجل Excel</a>
                <button onclick="window.print()" class=btn-gold style='padding:9px 14px;border-radius:10px;background:linear-gradient(90deg,#ffbe4d,#ffb020);font-size:13px'>📄 PDF</button>
              </div>
            </div>
          </div>

          <div style='display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px'>
            <div class=card style='text-align:right'><h4>📶 حالة الشبكة</h4><div id=netStatus>⏳ فحص...</div><button class=btn-gold onclick="checkNetwork()" style='width:100%;margin-top:8px'>🔄 فحص الآن</button></div>
            <div class=card style='text-align:right'><h4>🔔 الإشعارات <span id=homeNotifCount style='background:#ef4444;color:#fff;padding:2px 7px;border-radius:10px;font-size:11px'>0</span></h4><div id=homeNoti>⏳...</div><button class=btn-gold onclick="loadPage('logs')" style='width:100%;margin-top:8px'>📜 عرض السجل</button></div>
          </div>

          <div class=card style='margin-top:12px;text-align:right'><h4>📜 آخر النشاطات - سجل الدخول والتعديلات</h4>{log_html or '<small style=color:#777>لا يوجد</small>'}<button class=btn-gold onclick="loadPage('logs')" style='width:100%;margin-top:10px'>عرض كل السجل</button></div>
        </div>
        <!-- واتساب ثابت بالشاشة الرئيسية -->
        <a href='https://wa.me/905344851045' target=_blank title='واتساب الدعم' style='position:fixed;left:18px;bottom:18px;background:linear-gradient(135deg,#25D366,#128C7E);color:#fff;width:58px;height:58px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:28px;text-decoration:none;box-shadow:0 8px 24px #0008, 0 0 0 3px #25D36633;z-index:9999;animation:floatWa 2.5s ease-in-out infinite'>💬</a>
        <style>@keyframes floatWa{{0%,100%{{transform:translateY(0)}}50%{{transform:translateY(-6px)}}}}</style>
        <script>
        async function checkNetwork(){{
          let el=document.getElementById('netStatus');
          try{{
            let r=await fetch('/api/network_status');
            let j=await r.json();
            el.innerHTML='<div style="font-size:22px;font-weight:900;color:#22c55e">● '+j.dishes+' صحن متصل</div><small>'+j.towers+' برج • '+j.subs+' مشترك</small>';
          }}catch(e){{el.innerHTML='❌ خطأ';}}
        }}
        checkNetwork();
        async function loadHomeNoti(){{
          try{{
            let r=await fetch('/api/notifications'); let j=await r.json();
            document.getElementById('homeNotifCount').textContent=j.unread||0;
            let h=''; j.rows.slice(0,3).forEach(n=>{{h+='<div style="padding:6px 0;border-bottom:1px solid #ffffff0a"><b style="color:#ffbe4d;font-size:12px">'+n.title+'</b><br><small style="color:#aaa">'+n.msg.slice(0,60)+'</small></div>';}});
            document.getElementById('homeNoti').innerHTML=h||'لا يوجد';
          }}catch(e){{}}
        }}
        loadHomeNoti();
        </script>
        """

    if v=='dishes':
        rs=qall("SELECT * FROM dish_ips ORDER BY id DESC")
        rows_html=""
        for r in rs:
            dn=esc(r.get('dish_name') or 'صحن')
            ip=esc(r.get('ip') or '')
            loc=esc(r.get('location') or '')
            rid=r['id']
            rows_html+= f'<div class="card anim" id="dish-{rid}" data-name="{dn}" data-ip="{ip}" data-loc="{loc}" style="display:flex;justify-content:space-between;align-items:center;background:linear-gradient(180deg,#1f2937,#111827);border:1px solid #ffffff12;box-shadow:0 6px 20px #0004"><div><b style="font-size:16px;color:#fff">{dn}</b><br><a href="http://{ip}" target=_blank style="background:#000;color:#ffbe4d;padding:6px 12px;border-radius:10px;font-family:monospace;text-decoration:none;display:inline-block;margin:4px 0">🌐 {ip} ↗</a><br><small style="color:#aaa">{loc}</small><br><small class="ping-out" style="font-size:11px;color:#777">جاهز للـ Ping</small></div><div style="display:flex;flex-direction:column;gap:6px"><button class=btn-gold onclick="window.doPing({rid})" style="padding:8px 12px">📶 Ping</button><div style="display:flex;gap:5px"><button class=btn-gold onclick="window.doEditDish({rid})" style="padding:8px 10px" {"disabled" if not is_mgr else ""}>✏</button><button class=btn-del onclick="askDel(\'/del_dish/{rid}\')" style="padding:8px 10px" {"disabled" if not is_mgr else ""}>🗑</button></div></div></div>'
        return f"""<div style='max-width:900px;margin:0 auto'>
<div class=card style='background:linear-gradient(180deg,#1e2433,#171e2f);border:1px solid #ffffff12;box-shadow:0 8px 24px #0005'>
<div style='display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px'>
<h3 style='margin:0'>📡 الصحون - {len(rs)} صحن</h3>
<div style='display:flex;gap:6px'>
<button onclick="pingAll()" class=btn-gold style='padding:7px 12px;font-size:12px;background:linear-gradient(90deg,#22c55e,#16a34a);color:#fff'>📶 فحص الكل</button>
<a href='/api/export/dishes' class=btn-gold style='text-decoration:none;padding:7px 12px;font-size:12px;background:#ffffff15;color:#fff'>📗 Excel</a>
<button onclick="window.print()" class=btn-gold style='padding:7px 12px;font-size:12px'>📄 PDF</button>
</div>
</div>
<form data-ajax method=post action=/add_dish style='display:flex;gap:6px;flex-wrap:wrap;margin-top:10px'>
<input name=dish_name placeholder='اسم الصحن' required style='flex:1;min-width:120px'>
<input name=ip placeholder='IP مثال 192.168.1.1' required style='flex:1;min-width:130px'>
<input name=location placeholder='موقع' style='flex:1;min-width:100px'>
<button class=btn-gold>➕ إضافة</button>
</form>
<input id=searchBox placeholder='🔍 بحث IP أو اسم...' oninput="window.searchDishes(this.value)" style='margin-top:10px;width:100%;padding:12px;border-radius:12px;background:#0f1424;border:1px solid #ffffff18'>
<div id=addMsg style='font-size:12px;color:#22c55e;margin-top:6px'>✅ {len(rs)} صحن • الفني لا يمكنه الحذف/التعديل</div>
</div>
<div id=dl>{rows_html}</div>
</div>
<script>
window.openChrome=function(ip){{window.open('http://'+ip,'_blank');}};
window.doEditDish=function(id){{let c=document.getElementById('dish-'+id); document.getElementById('editModal').classList.add('show'); document.getElementById('editTitle').textContent='✏ تعديل صحن'; document.getElementById('editBody').innerHTML='<input id=edit_dish_name value="'+c.dataset.name+'" style="width:100%;padding:12px;border-radius:10px;margin:4px 0"><input id=edit_ip value="'+c.dataset.ip+'" style="width:100%;padding:12px;border-radius:10px;margin:4px 0"><input id=edit_loc value="'+c.dataset.loc+'" style="width:100%;padding:12px;border-radius:10px;margin:4px 0"><button onclick="window.saveEdit(\\'dish\\',"+id+")" class=btn-gold style="width:100%;margin-top:10px;padding:12px">💾 حفظ</button>';}}
window.saveEdit=function(type,id){{let nn=document.getElementById('edit_dish_name').value;let ii=document.getElementById('edit_ip').value;let ll=document.getElementById('edit_loc').value;fetch('/edit_dish/'+id,{{method:'POST',body:new URLSearchParams({{dish_name:nn,ip:ii,location:ll}})}}).then(r=>{{if(!r.ok)alert('ممنوع للفني'); else{{closeEditModal(); loadPage('dishes',true);}}}});}}
window.doPing=function(id){{let c=document.getElementById('dish-'+id);let out=c.querySelector('.ping-out');out.textContent='⏳ ping...';fetch('/api/ping?ip='+encodeURIComponent(c.dataset.ip)).then(r=>r.json()).then(j=>{{out.textContent=j.out.slice(0,200);out.style.color=j.ok?'#22c55e':'#ef4444';}});}}
window.pingAll=async function(){{let cards=document.querySelectorAll('[id^=dish-]');for(let c of cards){{let out=c.querySelector('.ping-out');if(!out)continue;out.textContent='⏳...';try{{let r=await fetch('/api/ping?ip='+encodeURIComponent(c.dataset.ip));let j=await r.json();out.textContent=j.ok?'✅ '+j.out.slice(0,50):'❌ '+j.out.slice(0,50);out.style.color=j.ok?'#22c55e':'#ef4444';}}catch(e){{out.textContent='خطأ';}}await new Promise(r=>setTimeout(r,250));}}}}
window.searchDishes=function(q){{q=(q||'').toLowerCase();document.querySelectorAll('[id^=dish-]').forEach(card=>{{let txt=(card.dataset.name+card.dataset.ip+card.dataset.loc).toLowerCase();card.style.display=txt.includes(q)?'flex':'none';}});}}
</script>
"""

    if v=='towers':
        rs=qall("SELECT * FROM towers ORDER BY id DESC")
        rows=""
        for r in rs:
            sn=esc(r['name'])
            sa=esc(r['area'] or '')
            lat=r.get('lat') or 0
            lng=r.get('lng') or 0
            rows+=f"<div class='card anim' id='tower-{r['id']}' data-name='{sn}' data-area='{sa}' data-lat='{lat}' data-lng='{lng}' style='background:linear-gradient(180deg,#1f2937,#111827);border:1px solid #ffffff10'><div style='display:flex;justify-content:space-between'><div><b>🗼 {sn}</b><br><small>{sa}</small><br><small style='color:#ffbe4d'>📍 {lat} , {lng}</small></div><div style='display:flex;gap:5px'><button class=btn-gold onclick=\"window.openEditTower({r['id']})\" style='padding:8px 10px' {'disabled' if not is_mgr else ''}>✏</button><button class=btn-del onclick=\"askDel('/del_tower/{r['id']}')\" style='padding:8px 10px' {'disabled' if not is_mgr else ''}>🗑</button></div></div><div style='margin-top:6px'><a href='https://maps.google.com/?q={lat},{lng}' target=_blank style='font-size:12px;color:#22c55e'>🗺 خرائط</a> | <button onclick=\"navigator.clipboard.writeText('{lat},{lng}')\" style='font-size:12px;background:transparent;border:0;color:#ffbe4d;cursor:pointer'>📋 نسخ</button></div></div>"
        return f"""<div style='max-width:700px;margin:0 auto'>
<div class=card style='background:linear-gradient(180deg,#1e2433,#171e2f)'><div style='display:flex;justify-content:space-between'><h3>🗼 الأبراج</h3><div><a href='/api/export/towers' class=btn-gold style='text-decoration:none;padding:7px 12px;font-size:12px'>📗 Excel</a> <button onclick="window.print()" class=btn-gold style='padding:7px 12px;font-size:12px'>📄 PDF</button></div></div>
<form data-ajax method=post action=/add_tower style='display:flex;gap:6px;flex-wrap:wrap;margin-top:8px'>
<input name=name placeholder='اسم البرج' required style='flex:1'>
<input name=area placeholder='المنطقة' style='flex:1'>
<input name=lat placeholder='lat 35.1318' style='flex:0.6'>
<input name=lng placeholder='lng 36.7578' style='flex:0.6'>
<button class=btn-gold>➕ إضافة</button>
</form></div>
{rows or '<div class=card>لا يوجد أبراج</div>'}
<script>
window.openEditTower=function(id){{let c=document.getElementById('tower-'+id);document.getElementById('editModal').classList.add('show');document.getElementById('editTitle').textContent='✏ تعديل برج';document.getElementById('editBody').innerHTML='<input id=edit_t_name value="'+c.dataset.name+'" style="width:100%;margin:6px 0;padding:12px;border-radius:10px"><input id=edit_t_area value="'+c.dataset.area+'" style="width:100%;margin:6px 0;padding:12px;border-radius:10px"><input id=edit_t_lat value="'+c.dataset.lat+'" style="width:100%;margin:6px 0;padding:12px;border-radius:10px"><input id=edit_t_lng value="'+c.dataset.lng+'" style="width:100%;margin:6px 0;padding:12px;border-radius:10px"><button onclick="window.saveTower('+id+')" class=btn-gold style="width:100%;padding:12px">💾 حفظ</button>';}}
window.saveTower=function(id){{let nn=document.getElementById('edit_t_name').value;let aa=document.getElementById('edit_t_area').value;let la=document.getElementById('edit_t_lat').value;let ln=document.getElementById('edit_t_lng').value;fetch('/edit_tower/'+id,{{method:'POST',body:new URLSearchParams({{name:nn,area:aa,lat:la,lng:ln}})}}).then(r=>{{if(!r.ok)alert('ممنوع للفني'); else{{closeEditModal(); loadPage('towers',true);}}}});}}
</script></div>"""

    if v=='subs':
        rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 200")
        rows=""
        for r in rs:
            rows+=f"<div class='card anim' id='sub-{r['id']}' data-name='{esc(r['name'])}' data-phone='{esc(r['phone'] or '')}' data-note='{esc(r['note'] or '')}' style='display:flex;justify-content:space-between;align-items:center;background:linear-gradient(180deg,#1f2937,#111827)'><div><b>{esc(r['name'])}</b><br>📞 {esc(r['phone'] or '')}<br><small>{esc(r['note'] or '')}</small></div><div style='display:flex;gap:5px'><button class=btn-gold onclick=\"window.openEditSub({r['id']})\" style='padding:8px 10px' {'disabled' if not is_mgr else ''}>✏</button><button class=btn-del onclick=\"askDel('/del_sub/{r['id']}')\" style='padding:8px 10px' {'disabled' if not is_mgr else ''}>🗑</button></div></div>"
        return f"""<div style='max-width:700px;margin:0 auto'>
<div class=card><div style='display:flex;justify-content:space-between;align-items:center'><h3>👥 المشتركين</h3><div><a href='/api/export/subs' class=btn-gold style='text-decoration:none;padding:7px 12px;font-size:12px'>📗 Excel</a> <button onclick="window.print()" class=btn-gold style='padding:7px 12px;font-size:12px'>📄 PDF</button></div></div>
<form data-ajax method=post action=/add_sub style='display:flex;gap:5px;flex-wrap:wrap;margin-top:8px'>
<input name=name placeholder='الاسم / اليوزر' required style='flex:1'>
<input name=phone placeholder='رقم' style='flex:1'>
<input name=note placeholder='ملاحظة' style='flex:1'>
<button class=btn-gold>➕</button>
</form></div>
{rows or '<div class=card>لا يوجد</div>'}
<script>
window.openEditSub=function(id){{let c=document.getElementById('sub-'+id);document.getElementById('editModal').classList.add('show');document.getElementById('editTitle').textContent='✏ تعديل مشترك';document.getElementById('editBody').innerHTML='<input id=edit_s_name value="'+c.dataset.name+'" style="width:100%;margin:6px 0;padding:12px;border-radius:10px"><input id=edit_s_phone value="'+c.dataset.phone+'" style="width:100%;margin:6px 0;padding:12px;border-radius:10px"><input id=edit_s_note value="'+c.dataset.note+'" style="width:100%;margin:6px 0;padding:12px;border-radius:10px"><button onclick="window.saveSub('+id+')" class=btn-gold style="width:100%;padding:12px">💾 حفظ</button>';}}
window.saveSub=function(id){{let nn=document.getElementById('edit_s_name').value;let pp=document.getElementById('edit_s_phone').value;let no=document.getElementById('edit_s_note').value;fetch('/edit_sub/'+id,{{method:'POST',body:new URLSearchParams({{name:nn,phone:pp,note:no}})}}).then(r=>{{if(!r.ok)alert('ممنوع للفني'); else{{closeEditModal(); loadPage('subs',true);}}}});}}
</script></div>"""

    if v=='ledger':
        rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 200")
        rows=""
        for r in rs:
            rows+=f"<div class='card anim' id='led-{r['id']}' data-name='{esc(r['name'])}' data-amount='{r['amount']}' style='display:flex;justify-content:space-between;align-items:center;background:linear-gradient(180deg,#1f2937,#111827)'><div><b>{esc(r['name'])}</b> - <b style='color:#ffbe4d;font-size:18px'>{r['amount']}</b> {esc(r['currency'] or 'USD')}<br><small>{esc(r['note'] or '')}</small></div><div style='display:flex;gap:5px'><button class=btn-gold onclick=\"window.openEditLed({r['id']})\" style='padding:8px 10px' {'disabled' if not is_mgr else ''}>✏</button><button class=btn-del onclick=\"askDel('/del_ledger/{r['id']}')\" style='padding:8px 10px' {'disabled' if not is_mgr else ''}>🗑</button></div></div>"
        return f"""<div style='max-width:700px;margin:0 auto'>
<div class=card><h3>📒 الحسابات</h3>
<form data-ajax method=post action=/add_ledger style='display:flex;gap:5px;flex-wrap:wrap'>
<input name=name placeholder='الاسم' required style='flex:1'>
<input name=amount type=number step=0.01 placeholder='المبلغ' required style='flex:1'>
<input name=note placeholder='ملاحظة' style='flex:1'>
<select name=currency style='flex:0.5'><option value=USD>USD</option><option value=SYP>SYP</option></select>
<button class=btn-gold>➕</button>
</form></div>
{rows}
<script>
window.openEditLed=function(id){{let c=document.getElementById('led-'+id);document.getElementById('editModal').classList.add('show');document.getElementById('editTitle').textContent='✏ تعديل حساب';document.getElementById('editBody').innerHTML='<input id=edit_l_name value="'+c.dataset.name+'" style="width:100%;margin:6px 0;padding:12px;border-radius:10px"><input id=edit_l_amount value="'+c.dataset.amount+'" style="width:100%;margin:6px 0;padding:12px;border-radius:10px"><button onclick="window.saveLed('+id+')" class=btn-gold style="width:100%;padding:12px">💾 حفظ</button>';}}
window.saveLed=function(id){{let nn=document.getElementById('edit_l_name').value;let aa=document.getElementById('edit_l_amount').value;fetch('/edit_ledger/'+id,{{method:'POST',body:new URLSearchParams({{name:nn,amount:aa,note:'',currency:'USD'}})}}).then(r=>{{if(!r.ok)alert('ممنوع'); else{{closeEditModal(); loadPage('ledger',true);}}}});}}
</script></div>"""

    if v=='logs':
        rs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 300")
        rows=""
        for r in rs:
            rows+=f"<div class='card anim' style='font-size:13px;background:linear-gradient(180deg,#1f2937,#111827);border-left:3px solid #ffbe4d'><div style='display:flex;justify-content:space-between'><b style='color:#ffbe4d'>👤 {esc(r['user_phone'])}</b><small style='color:#777'>{esc(r['time'])}</small></div><div style='margin-top:4px'><b>{esc(r['action'])}</b> - {esc(r['detail'])}</div></div>"
        return f"<div style='max-width:900px;margin:0 auto'><div class=card style='display:flex;justify-content:space-between;align-items:center;background:linear-gradient(180deg,#1e2433,#171e2f)'><h3>📜 سجل النشاطات - مين دخل ومين عدل</h3><div style='display:flex;gap:6px'><a href='/api/export/logs' class=btn-gold style='text-decoration:none;padding:7px 12px;font-size:12px'>📗 Excel</a><button onclick='window.print()' class=btn-gold style='padding:7px 12px;font-size:12px'>📄 PDF</button></div></div>{rows or '<div class=card>لا يوجد سجل</div>'}</div>"

    if v=='network':
        dishes=qall("SELECT * FROM dish_ips ORDER BY id DESC")
        online=0
        rows=""
        for d in dishes:
            rows+=f"<div class='card anim' id='net-{d['id']}' data-ip='{esc(d.get('ip',''))}' style='display:flex;justify-content:space-between;align-items:center'><div><b>{esc(d.get('dish_name') or 'صحن')}</b> - {esc(d.get('ip',''))}<br><small>{esc(d.get('location',''))}</small><br><small class='net-out' style='font-weight:800'>⏳...</small></div><button class=btn-gold onclick='checkOne({d['id']})'>📶 فحص</button></div>"
        return f"""<div style='max-width:800px;margin:0 auto'>
<div class=card style='background:linear-gradient(135deg,#0f172a,#1e293b);border:1px solid #ffbe4d33'><h3>📶 حالة الشبكة - فحص حي</h3><div style='display:flex;gap:8px;margin-top:8px'><button class=btn-gold onclick='checkAll()' style='flex:1;background:linear-gradient(90deg,#22c55e,#16a34a);color:#fff;padding:12px'>🚀 فحص كل الشبكة</button><button class=btn-gold onclick='loadPage("network",true)' style='flex:1'>🔄 تحديث</button></div><div id=summary style='margin-top:10px;font-weight:800;font-size:16px'></div></div>
{rows or '<div class=card>لا يوجد صحون</div>'}
<script>
let online=0, offline=0;
async function checkOne(id){{let c=document.getElementById('net-'+id);let out=c.querySelector('.net-out');out.textContent='⏳...';try{{let r=await fetch('/api/ping?ip='+encodeURIComponent(c.dataset.ip));let j=await r.json();out.textContent=j.out.slice(0,80);out.style.color=j.ok?'#22c55e':'#ef4444';}}catch(e){{out.textContent='❌ خطأ';out.style.color='#ef4444';}}}}
async function checkAll(){{let cards=document.querySelectorAll('[id^=net-]');online=0;offline=0;for(let c of cards){{let out=c.querySelector('.net-out');out.textContent='⏳...';try{{let r=await fetch('/api/ping?ip='+encodeURIComponent(c.dataset.ip));let j=await r.json();out.textContent=j.ok?'✅ '+j.out.slice(0,60):'❌ '+j.out.slice(0,60);out.style.color=j.ok?'#22c55e':'#ef4444';if(j.ok)online++;else offline++;}}catch(e){{out.textContent='❌';offline++;}}document.getElementById('summary').innerHTML='✅ متصل: '+online+' | ❌ غير متصل: '+offline+' | الكل: '+(online+offline);await new Promise(r=>setTimeout(r,200));}}}}
checkAll();
</script></div>"""

    if v=='map':
        towers=qall("SELECT * FROM towers")
        import json as _json
        tj_json=_json.dumps([{"name":t['name'],"area":t.get('area') or '',"lat":float(t.get('lat') or 35.1318),"lng":float(t.get('lng') or 36.7578)} for t in towers],ensure_ascii=False)
        return f"""<div class=card style='padding:8px;background:linear-gradient(180deg,#0f172a,#111827)'>
<div style='display:flex;gap:6px;margin-bottom:8px;flex-wrap:wrap'>
<input id=mapSearch placeholder='🔍 بحث برج + Enter' onkeydown="if(event.key==='Enter'){{window.mapGo(this.value)}}" style='flex:1;min-width:160px;background:#1f2937;border:1px solid #ffffff15;color:#fff;padding:10px 12px;border-radius:10px'>
<button class=btn-gold onclick="window.mapGo(document.getElementById('mapSearch').value)" style='padding:10px 14px'>🔍 بحث</button>
<button class=btn-gold onclick="locateMe()" style='background:linear-gradient(90deg,#22c55e,#16a34a);color:#fff;padding:10px 12px'>📍 موقعي</button>
<button class=btn-gold onclick="toggleMeasure()" id=measureBtn style='background:linear-gradient(90deg,#0ea5e9,#0284c7);color:#fff;padding:10px 12px'>📏 قياس</button>
<button class=btn-gold onclick="clearMeasure()" style='background:linear-gradient(90deg,#ef4444,#dc2626);color:#fff;padding:10px 12px'>🗑 مسح</button>
<span id=distanceLabel style='padding:8px 12px;background:#1f2937;border:1px solid #ffbe4d33;border-radius:10px;font-size:13px;color:#ffbe4d;font-weight:800'>📏 المسافة: 0 كم</span>
</div>
<div id=map style='height:78vh;min-height:500px;border-radius:16px;background:#0f172a;z-index:1;border:2px solid #ffffff0f;box-shadow:0 10px 40px #0008'></div>
<div style='margin-top:8px;display:flex;gap:8px;flex-wrap:wrap;font-size:12px;color:#aaa'><span>💡 اسحب الخريطة - دوّر للزوم - اضغط للقياس</span><span>🛰 قمر صناعي وعادي</span><span>📍 دقة عالية</span></div>
</div>
<script>
let _towers={tj_json};
let measureMode=false; let measurePoints=[]; let measureLine=null; let measureMarkers=[];
setTimeout(()=>{{
  if(typeof L==='undefined'){{document.getElementById('map').innerHTML='<div style=text-align:center;padding:40px>⚠ فشل تحميل الخريطة</div>';return;}}
  let map=L.map('map',{{zoomControl:true,maxZoom:19,minZoom:5}}).setView([35.1318,36.7578],13);
  let osm=L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:19,attribution:'© OSM',maxNativeZoom:19}}).addTo(map);
  let sat=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',{{maxZoom:20,maxNativeZoom:19}});
  let topo=L.tileLayer('https://{{s}}.tile.opentopomap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:17}});
  L.control.layers({{"🗺 عادية":osm,"🛰 قمر صناعي عالي الدقة":sat,"⛰ تضاريس":topo}}).addTo(map);
  L.control.scale({{metric:true,imperial:false}}).addTo(map);
  setTimeout(()=>map.invalidateSize(),400);
  _towers.forEach(t=>{{
    let m=L.marker([t.lat,t.lng],{{draggable:true}}).addTo(map);
    m.bindPopup('<div style="min-width:140px"><b>🗼 '+t.name+'</b><br><small>'+t.area+'</small><br><small style="color:#ffbe4d">'+t.lat.toFixed(5)+','+t.lng.toFixed(5)+'</small><br><a href="https://maps.google.com/?q='+t.lat+','+t.lng+'" target=_blank style="color:#22c55e">فتح جوجل</a></div>');
  }});
  window.mapGo=function(q){{q=(q||'').toLowerCase().trim(); if(!q){{alert('اكتب اسم');return;}} let f=_towers.find(t=>t.name.toLowerCase().includes(q)||t.area.toLowerCase().includes(q)); if(f){{map.flyTo([f.lat,f.lng],17,{{animate:true,duration:1}}); L.popup().setLatLng([f.lat,f.lng]).setContent('<b>'+f.name+'</b>').openOn(map);}} else {{alert('غير موجود: '+q);}} }};
  window.locateMe=function(){{ if(navigator.geolocation){{navigator.geolocation.getCurrentPosition(p=>{{map.flyTo([p.coords.latitude,p.coords.longitude],16); L.marker([p.coords.latitude,p.coords.longitude]).addTo(map).bindPopup('📍 موقعك الحالي').openPopup();}}, err=>alert('فشل تحديد الموقع'));}} }};
  window.toggleMeasure=function(){{measureMode=!measureMode; let btn=document.getElementById('measureBtn'); btn.style.background=measureMode?'linear-gradient(90deg,#22c55e,#16a34a)':'linear-gradient(90deg,#0ea5e9,#0284c7)'; btn.textContent=measureMode?'✅ اضغط على الخريطة':'📏 قياس'; if(!measureMode){{map.getContainer().style.cursor='';}} else {{map.getContainer().style.cursor='crosshair';}} }};
  window.clearMeasure=function(){{measurePoints=[]; if(measureLine){{map.removeLayer(measureLine); measureLine=null;}} measureMarkers.forEach(m=>map.removeLayer(m)); measureMarkers=[]; document.getElementById('distanceLabel').textContent='📏 المسافة: 0 كم';}};
  map.on('click',e=>{{
    if(!measureMode) return;
    measurePoints.push(e.latlng);
    let mk=L.marker(e.latlng,{{draggable:true,icon:L.divIcon({{className:'measure-dot',html:'<div style="width:14px;height:14px;background:#ffbe4d;border:2px solid #fff;border-radius:50%;box-shadow:0 0 8px #ffbe4d"></div>',iconSize:[14,14]}})}}).addTo(map);
    measureMarkers.push(mk);
    mk.on('drag',()=>{{measurePoints[measureMarkers.indexOf(mk)]=mk.getLatLng(); updateMeasure();}});
    updateMeasure();
  }});
  function updateMeasure(){{
    if(measureLine) map.removeLayer(measureLine);
    if(measurePoints.length>1){{
      measureLine=L.polyline(measurePoints,{{color:'#ffbe4d',weight:4,opacity:.9,dashArray:'10,10'}}).addTo(map);
      let d=0; for(let i=1;i<measurePoints.length;i++){{d+=measurePoints[i-1].distanceTo(measurePoints[i]);}}
      let km=(d/1000).toFixed(3);
      document.getElementById('distanceLabel').innerHTML='📏 المسافة: <b style="color:#fff">'+km+' كم</b> ('+d.toFixed(0)+' متر)';
    }}
  }}
}},150);
</script>
"""

    if v=='support':
        return """<div class=card style='text-align:center;max-width:500px;margin:0 auto;background:linear-gradient(180deg,#1e2433,#171e2f);border:1px solid #ffffff12;box-shadow:0 10px 30px #0005'>
<h2 style='font-size:26px'>🛠 الدعم الفني - OMAIA ISP</h2>
<p style='color:#aaa'>نظام إدارة شبكة متكامل - فخم وسريع 🔥</p>
<a href='https://wa.me/905344851045' target=_blank style='display:inline-block;background:linear-gradient(135deg,#25D366,#128C7E);color:#fff;padding:14px 24px;border-radius:14px;text-decoration:none;margin:8px;font-weight:800;box-shadow:0 6px 20px #25D36644'>💬 واتساب الدعم الفني</a><br>
<a href='https://instagram.com/af_20_1999' target=_blank style='display:inline-block;background:linear-gradient(45deg,#feda75,#fa7e1e,#d62976,#4f5bd5);color:#fff;padding:12px 22px;border-radius:14px;text-decoration:none;margin:8px;font-weight:800'>📸 @af_20_1999 انستا</a><br>
<a href='tel:+905344851045' style='display:inline-block;background:linear-gradient(90deg,#0ea5e9,#0284c7);color:#fff;padding:12px 22px;border-radius:14px;text-decoration:none;margin:8px;font-weight:700'>📞 +90 534 485 10 45</a>
<div style='margin-top:16px;padding:12px;background:#ffffff06;border-radius:12px;font-size:12px;color:#777'>OMAIA ISP v2.0 • نظام فخم • سرعة نار 🔥</div>
</div>"""

    if v=='settings':
        us=qall("SELECT * FROM users ORDER BY phone DESC")
        uh=""
        for u in us:
            ph=esc(u['phone'])
            un=esc(u['username'] or '')
            ro=esc(u['role'])
            role_badge = "<span style='background:#ffbe4d;color:#111;padding:2px 8px;border-radius:8px;font-size:11px;font-weight:800'>مدير</span>" if ro=='manager' else "<span style='background:#ffffff15;color:#aaa;padding:2px 8px;border-radius:8px;font-size:11px'>فني</span>"
            uh+=f'<div class="card anim" id="user-{ph}" data-phone="{ph}" data-username="{un}" data-role="{ro}" style="display:grid;grid-template-columns:1fr auto;gap:12px;align-items:center;background:linear-gradient(180deg,#1f2937,#111827);border:1px solid #ffffff0f"><div style="display:flex;align-items:center;gap:12px"><div style="width:44px;height:44px;border-radius:12px;background:linear-gradient(135deg,#ffbe4d,#ffb020);display:flex;align-items:center;justify-content:center;color:#111;font-weight:900;font-size:18px;box-shadow:0 4px 12px #ffbe4d33">{un[:1].upper() if un else ph[:1]}</div><div><b style="font-size:15px">{un}</b><br><span style="color:#ffbe4d;font-family:monospace;font-size:13px">{ph}</span> {role_badge}</div></div><div style="display:flex;gap:6px"><button class=btn-gold onclick="window.openEditUser(\'{ph}\')" style="padding:9px 12px">✏</button><button class=btn-del onclick="askDel(\'/del_user/{ph}\')" style="padding:9px 12px">🗑</button></div></div>'
        return f"""<div style='max-width:800px;margin:0 auto'>
<div class=card style='background:linear-gradient(180deg,#1e2433,#171e2f);border:1px solid #ffffff10'><h3>🔑 كلمة السر الخاصة بي</h3>
<form data-ajax method=post action=/change_pass style='display:flex;gap:8px'>
<input name=newpass type=password placeholder='كلمة سر جديدة' required style='flex:1'>
<button class=btn-gold style='padding:12px 18px'>💾 حفظ</button>
</form></div>

<div style='display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:12px'>
<div class=card style='background:linear-gradient(135deg,#1a2340,#121a30);border:1px solid #ffbe4d22;text-align:center'>
<h4 style='margin:0 0 10px'>🌐 اللغة</h4>
<button onclick="toggleLang()" id=langBtnSettings style='width:100%;padding:12px;border-radius:12px;border:1px solid #ffffff15;background:linear-gradient(90deg,#1f2937,#111827);color:#fff;font-weight:800;cursor:pointer;font-size:16px'>🌐 عربي</button>
<p style='font-size:11px;color:#777;margin-top:8px'>القائمة ثابتة يمين - فخمة</p>
</div>
<div class=card style='background:linear-gradient(180deg,#1e2433,#0f1424);border:1px solid #ffbe4d30'>
<h4 style='text-align:center;margin:0 0 12px'>👤 اضافة يوزر</h4>
<form data-ajax method=post action=/add_user style='display:flex;flex-direction:column;gap:10px'>
<input name=user_field placeholder='📱 رقم / يوزر' required style='font-size:15px;padding:14px;background:#0f1424;border:1px solid #ffffff20;border-radius:12px;color:#fff'>
<input name=password type=password placeholder='🔑 password' required style='padding:14px;background:#0f1424;border:1px solid #ffffff20;border-radius:12px;color:#fff'>
<select name=role style='padding:12px;background:#0f1424;border:1px solid #ffffff20;border-radius:12px;color:#fff'><option value=tech>فني - بدون تعديل/حذف</option><option value=manager>مدير - كل الصلاحيات</option></select>
<button class=btn-gold style='padding:14px;font-size:16px;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:900'>➕ اضافة يوزر</button>
</form>
</div>
<div class=card style='background:linear-gradient(180deg,#1e2433,#0f1424)'><h4>📊 تصدير</h4><div style='display:flex;flex-direction:column;gap:8px'><a href='/api/export/users' class=btn-gold style='text-decoration:none;padding:10px;text-align:center;background:linear-gradient(90deg,#22c55e,#16a34a);color:#fff;border-radius:10px'>📗 يوزرات Excel</a><a href='/api/export/dishes' class=btn-gold style='text-decoration:none;padding:10px;text-align:center;background:linear-gradient(90deg,#0ea5e9,#0284c7);color:#fff;border-radius:10px'>📘 صحون Excel</a><a href='/api/export/logs' class=btn-gold style='text-decoration:none;padding:10px;text-align:center;background:linear-gradient(90deg,#8b5cf6,#7c3aed);color:#fff;border-radius:10px'>📜 سجل Excel</a><button onclick="window.print()" class=btn-gold style='padding:10px;border-radius:10px'>📄 PDF</button></div></div>
</div>

<div style='margin-bottom:10px;display:flex;justify-content:space-between;align-items:center'><h3 style='margin:0'>👥 المستخدمين - صلاحيات</h3><small style='color:#aaa'>الفني: عرض فقط • المدير: كل الصلاحيات</small></div>
{uh}
<script>
window.openEditUser=function(ph){{let c=document.getElementById('user-'+ph);document.getElementById('editModal').classList.add('show');document.getElementById('editTitle').textContent='✏ تعديل يوزر';document.getElementById('editBody').innerHTML='<label style="display:block;font-size:12px;margin-top:6px">اليوزر / الرقم</label><input id=edit_u_field value="'+c.dataset.phone+'" style="width:100%;padding:12px;border-radius:10px;margin-top:4px"><label style="display:block;font-size:12px;margin-top:8px">كلمة سر جديدة (فاضي = بدون تغيير)</label><input id=edit_u_pass type="password" placeholder="••••••" style="width:100%;padding:12px;border-radius:10px;margin-top:4px"><label style="display:block;font-size:12px;margin-top:8px">الصلاحية</label><select id=edit_u_role style="width:100%;padding:12px;border-radius:10px;margin-top:4px"><option value="tech" '+(c.dataset.role=='tech'?'selected':'')+'>فني</option><option value="manager" '+(c.dataset.role=='manager'?'selected':'')+'>مدير</option></select><button onclick="window.saveUser(\\''+ph+'\\')" class=btn-gold style="width:100%;padding:14px;margin-top:12px;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:900">💾 حفظ</button>';}}
window.saveUser=function(oldPh){{let ff=document.getElementById('edit_u_field').value.trim();let pw=document.getElementById('edit_u_pass').value;let ro=document.getElementById('edit_u_role').value;if(!ff){{alert('مطلوب');return;}}let data={{old_phone:oldPh,phone:ff,username:ff,role:ro}};if(pw.trim()!='')data.password=pw.trim();fetch('/edit_user',{{method:'POST',body:new URLSearchParams(data)}}).then(r=>{{if(!r.ok)r.text().then(t=>alert(t));else{{closeEditModal(); loadPage('settings',true);}}}});}}
</script></div>"""
    return "<div class=card>ok</div>"

def layout(c,v='home'):
    th=session.get('theme','dark')
    is_dark=(th=='dark')
    bg='radial-gradient(120% 120% at 10% 10%, #1a2344 0%, #0a0e2a 60%, #070a1f 100%)' if is_dark else '#f1f5f9'
    card_bg='#1e2433' if is_dark else '#ffffff'
    txt='#ffffff' if is_dark else '#0f172a'
    border='#ffffff12' if is_dark else '#e2e8f0'
    cur_user = qone("SELECT * FROM users WHERE phone=?",(session.get('phone') or '',))
    role = (cur_user.get('role') or 'tech') if cur_user else 'tech'
    return f"""<html dir=rtl lang=ar><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1,maximum-scale=1'>
<link rel=stylesheet href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'>
<style>
*{{box-sizing:border-box;font-family:system-ui, -apple-system, Segoe UI, Cairo}}body{{margin:0;background:{bg};color:{txt};overflow-x:hidden;direction:rtl}}
.anim{{animation:fadeUp .32s cubic-bezier(.2,.8,.2,1) both}}@keyframes fadeUp{{from{{opacity:0;transform:translateY(14px) scale(.98)}}to{{opacity:1;transform:none}}}}
.top{{position:fixed;top:0;left:0;right:0;height:62px;background:linear-gradient(90deg,#0f172af2,#111827f2);backdrop-filter:blur(18px) saturate(1.3);color:#fff;display:flex;align-items:center;justify-content:space-between;padding:0 14px;z-index:1003;border-bottom:1px solid #ffffff12;box-shadow:0 4px 24px #0006}}
.sidebar{{position:fixed;right:0 !important;left:auto !important;top:0;direction:rtl;width:280px;height:100%;background:linear-gradient(180deg,#0f172a 0%,#0b1225 50%,#070e22 100%);color:#fff;z-index:1002;padding-top:72px;transform:translateX(110%);transition:transform .36s cubic-bezier(.4,0,.2,1);overflow-y:auto;box-shadow:-10px 0 40px #0008;border-left:1px solid #ffffff0f}}
.sidebar::before{{content:'';position:absolute;top:0;right:0;width:100%;height:100%;background:linear-gradient(180deg, #ffbe4d08 0%, transparent 40%);pointer-events:none}}
.sidebar.active{{transform:none}}
.sidebar a{{display:flex;align-items:center;gap:12px;padding:13px 16px;margin:7px 12px;color:#cbd5e1;text-decoration:none;border-radius:14px;background:linear-gradient(90deg,#ffffff06,#ffffff03);border:1px solid #ffffff06;transition:all .28s cubic-bezier(.2,.8,.2,1);position:relative;overflow:hidden}}
.sidebar a::before{{content:'';position:absolute;top:0;left:-100%;width:100%;height:100%;background:linear-gradient(90deg, transparent, #ffffff12, transparent);transition:left .6s}}
.sidebar a:hover::before{{left:100%}}
.sidebar a:hover{{background:linear-gradient(90deg,#ffffff12,#ffffff06);transform:translateX(-6px);color:#fff;box-shadow:0 4px 18px #0005, 0 0 0 1px #ffffff10 inset;border-color:#ffffff15}}
.sidebar a.active{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:800;box-shadow:0 6px 20px #ffbe4d44, 0 0 0 1px #ffbe4d66 inset;transform:translateX(-2px)}}
#overlay{{position:fixed;inset:0;background:#0009;backdrop-filter:blur(4px);z-index:1001;display:none;opacity:0;transition:opacity .3s}}#overlay.show{{display:block;opacity:1}}
.main{{margin-top:74px;padding:14px;min-height:90vh}}@media(max-width:700px){{.main{{padding:10px}}}}
.card{{background:linear-gradient(180deg,{card_bg},{card_bg});color:{txt};padding:16px;border-radius:16px;margin-bottom:12px;border:1px solid {border};transition:all .24s cubic-bezier(.2,.8,.2,1);box-shadow:0 4px 16px #0002, 0 1px 0 #ffffff08 inset;position:relative}}
.card::after{{content:'';position:absolute;inset:0;border-radius:16px;background:linear-gradient(180deg,#ffffff06 0%,transparent 60%);pointer-events:none}}
.card:hover{{transform:translateY(-3px) scale(1.01);box-shadow:0 12px 32px #0005, 0 0 0 1px #ffffff12 inset, 0 1px 0 #ffffff12 inset}}
input,select{{padding:12px 14px;margin:6px 0;border-radius:12px;border:1px solid {border};width:100%;background:#ffffff07;color:{txt};transition:all .22s;font-size:14px}}
input:focus{{border-color:#ffbe4d;box-shadow:0 0 0 3px #ffbe4d22;outline:none;background:#ffffff0a}}
.btn-gold{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;padding:10px 18px;border:0;border-radius:12px;font-weight:800;cursor:pointer;transition:all .22s;box-shadow:0 4px 14px #ffbe4d33;position:relative;overflow:hidden}}
.btn-gold::before{{content:'';position:absolute;top:0;left:-100%;width:100%;height:100%;background:linear-gradient(90deg,transparent,#ffffff55,transparent);transition:left .5s}}
.btn-gold:hover::before{{left:100%}}
.btn-gold:hover{{transform:translateY(-2px);box-shadow:0 8px 22px #ffbe4d55}}
.btn-gold:active{{transform:scale(.97)}}
.btn-del{{background:linear-gradient(90deg,#ef4444,#dc2626);color:#fff;padding:9px 14px;border:0;border-radius:12px;cursor:pointer;transition:all .2s;box-shadow:0 4px 12px #ef444433}}
.btn-del:hover{{transform:translateY(-1px);box-shadow:0 6px 18px #ef444455}}
#delModal, #editModal{{position:fixed;inset:0;background:#000a;backdrop-filter:blur(10px);display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:.32s cubic-bezier(.4,0,.2,1);z-index:2000}}
#delModal.show, #editModal.show{{opacity:1;pointer-events:auto}}
#delBox, #editBox{{background:linear-gradient(180deg,{card_bg},#0f1424);color:{txt};padding:26px;border-radius:20px;width:92%;max-width:460px;text-align:right;transform:scale(.92) translateY(20px);transition:.36s cubic-bezier(.4,0,.2,1);border:1px solid #ffffff12;box-shadow:0 20px 60px #000a}}
#delModal.show #delBox, #editModal.show #editBox{{transform:scale(1) translateY(0)}}
@media print{{.top,.sidebar,#overlay,#editModal,#delModal{{display:none !important}}.main{{margin-top:0}}}}
/* شريط تمرير فخم */
::-webkit-scrollbar{{width:8px}}::-webkit-scrollbar-track{{background:#0a0e2a}}::-webkit-scrollbar-thumb{{background:linear-gradient(180deg,#ffbe4d,#ffb020);border-radius:8px}}
</style></head>
<body>
<div id=overlay onclick="toggleSb(false)"></div>
<div class=sidebar id=sb>
<div style='padding:0 20px 12px;border-bottom:1px solid #ffffff0a;margin-bottom:8px'><div style='font-weight:900;font-size:18px'>OMAIA <span style='color:#ffbe4d'>ISP</span></div><small style='color:#64748b'>{esc(cur_user.get('username') or session.get('phone') or '')} • {role}</small></div>
<a href="javascript:loadPage('home')" id=nav-home>🏠 الرئيسية</a>
<a href="javascript:loadPage('network')" id=nav-network>📶 حالة الشبكة <span style='background:#22c55e;color:#fff;padding:2px 6px;border-radius:8px;font-size:10px;margin-right:auto'>LIVE</span></a>
<a href="javascript:loadPage('dishes')" id=nav-dishes>📡 الصحون</a>
<a href="javascript:loadPage('towers')" id=nav-towers>🗼 الأبراج</a>
<a href="javascript:loadPage('subs')" id=nav-subs>👥 المشتركين</a>
<a href="javascript:loadPage('ledger')" id=nav-ledger>📒 الحسابات</a>
<a href="javascript:loadPage('logs')" id=nav-logs>📜 السجل</a>
<a href="javascript:loadPage('map')" id=nav-map>🗺 الخريطة الحية <span style='background:#0ea5e9;color:#fff;padding:2px 6px;border-radius:8px;font-size:10px;margin-right:auto'>HD</span></a>
<a href="javascript:loadPage('support')" id=nav-support>🛠 الدعم</a>
<a href="javascript:loadPage('settings')" id=nav-settings>⚙ الإعدادات</a>
<a href="javascript:toggleNotif();toggleSb(false)" style='margin-top:8px'>🔔 الإشعارات <span id=menuNotifCount style='background:#ef4444;color:#fff;padding:3px 8px;border-radius:10px;font-size:11px;display:none;margin-right:auto'>0</span></a>
<a href="javascript:loadPage('dishes');setTimeout(()=>{{if(window.pingAll) pingAll();}},600)" style='background:linear-gradient(90deg,#22c55e18,#16a34a18);border:1px solid #22c55e33'>📶 فحص Ping الكل</a>
<a href="javascript:logoutFast()" style='margin-top:12px;background:linear-gradient(90deg,#ef444418,#dc262618);border:1px solid #ef444433'>🚪 خروج</a>
</div>
<div class=top>
<div style='display:flex;gap:8px;align-items:center'>
<span onclick="toggleSb()" style='font-size:24px;cursor:pointer;padding:6px 8px;border-radius:10px;background:#ffffff0a'>☰</span>
<div style='position:relative'>
<input id=topsearch placeholder='🔍 بحث شامل...' oninput="globalSearchTop(this.value)" style='background:#1f2937;border:1px solid #ffffff15;color:#fff;padding:9px 14px;border-radius:12px;width:42px;font-size:13px;transition:all .28s' onfocus="this.style.width='220px'" onblur="setTimeout(()=>{{this.style.width='42px'; document.getElementById('searchResults').style.display='none';}},200)">
</div>
</div>
<div style='font-weight:900;letter-spacing:.5px;font-size:17px'>OMAIA <span style='color:#ffbe4d;text-shadow:0 0 12px #ffbe4d66'>ISP</span></div>
<div style='display:flex;gap:8px;align-items:center'>
<div id=notifBell onclick="toggleNotif()" style='position:relative;cursor:pointer;font-size:22px;padding:6px 8px;border-radius:10px;background:#ffffff08'>🔔<span id=notifCount style='display:none;position:absolute;top:-4px;right:-4px;background:linear-gradient(90deg,#ef4444,#dc2626);color:#fff;font-size:10px;width:20px;height:20px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:900;box-shadow:0 2px 8px #ef444488'>0</span></div>
<button onclick="toggleTheme()" style='background:#ffffff0a;color:#fff;border:1px solid #ffffff0f;padding:9px 12px;border-radius:12px;cursor:pointer' title='ليل/نهار'>🌓</button>
</div>
</div>
<div id=searchResults style='position:fixed;top:66px;right:12px;left:12px;max-width:520px;margin:0 auto;background:linear-gradient(180deg,#1e2433,#171e2f);border:1px solid #ffffff15;border-radius:14px;z-index:1500;display:none;max-height:65vh;overflow:auto;box-shadow:0 16px 40px #000a'></div>
<div id=notifPanel style='position:fixed;top:66px;left:12px;max-width:380px;width:92%;background:linear-gradient(180deg,#1e2433,#111827);border:1px solid #ffffff12;border-radius:16px;z-index:2000;display:none;max-height:72vh;overflow:auto;box-shadow:0 16px 40px #000a'></div>
<div class=main id=mn>{c}</div>
<div id=delModal><div id=delBox><div style='font-size:48px;text-align:center'>🗑</div><h3 style='text-align:center;margin:8px 0'>تأكيد الحذف؟</h3><p style='color:#aaa;font-size:13px;text-align:center'>لا يمكن التراجع عن هذا الإجراء</p><div style='display:flex;gap:10px;margin-top:16px'><button onclick="closeDel()" style='flex:1;padding:13px;border-radius:12px;border:1px solid {border};background:transparent;color:{txt};cursor:pointer;font-weight:700'>تراجع</button><button id=delYes style='flex:1;padding:13px;border-radius:12px;background:linear-gradient(90deg,#ef4444,#dc2626);color:#fff;border:0;cursor:pointer;font-weight:800;box-shadow:0 6px 16px #ef444444'>حذف</button></div></div></div>
<div id=editModal><div id=editBox><div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:16px'><h3 id=editTitle style='margin:0'>✏ تعديل</h3><button onclick="closeEditModal()" style='background:#ffffff12;border:0;color:{txt};width:34px;height:34px;border-radius:50%;cursor:pointer;font-size:16px'>✕</button></div><div id=editBody></div></div></div>
<script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>
<script>
let cur='{v}';
let lang=localStorage.getItem('omaia_lang')||'ar';
const T={{
  ar:{{subs:'المشتركين',dishes:'الصحون',towers:'الأبراج',ledger:'الحسابات',home:'الرئيسية',network:'الشبكة',logs:'السجل',map:'الخريطة'}},
  en:{{subs:'Subscribers',dishes:'Dishes',towers:'Towers',ledger:'Accounts',home:'Home',network:'Network',logs:'Logs',map:'Map'}}
}};
function applyLang(){{
  document.querySelectorAll('[data-l]').forEach(e=>{{
    let k=e.getAttribute('data-l');
    if(T[lang][k])e.textContent=T[lang][k];
  }});
  let lbs=document.getElementById('langBtnSettings'); if(lbs) lbs.textContent=lang==='ar'?'🌐 عربي':'🌐 English';
  document.documentElement.lang=lang;
  document.documentElement.dir='rtl';
  document.body.style.direction='rtl';
  localStorage.setItem('omaia_lang',lang);
}}
window.toggleLang=function(){{
  lang=lang==='ar'?'en':'ar';
  localStorage.setItem('omaia_lang',lang);
  applyLang();
  fetch('/toggle_lang').then(()=>{{ loadPage(cur,true); }});
}}
applyLang();
function toggleSb(force){{
  let sb=document.getElementById('sb'),ov=document.getElementById('overlay');
  let open=force!==undefined?force:!sb.classList.contains('active');
  sb.classList.toggle('active',open);
  ov.classList.toggle('show',open);
  if(open){{ov.style.display='block'; setTimeout(()=>ov.style.opacity='1',10);}} else {{ov.style.opacity='0'; setTimeout(()=>ov.style.display='none',300);}}
}}
// سرعة نار وشرار 🔥🔥🔥 - تحميل فوري مع prefetch
let prefetchCache={{}};
async function loadPage(v,force=false,push=true){{
  if(push && cur!==v){{ try{{history.pushState({{page:v}}, '', '/dash?v='+v);}}catch(e){{}} }}
  cur=v;
  try{{localStorage.setItem('omaia_last_page',v);}}catch(e){{}}
  toggleSb(false);
  document.querySelectorAll('.sidebar a').forEach(a=>a.classList.remove('active'));
  let nav=document.getElementById('nav-'+v);
  if(nav)nav.classList.add('active');
  let mn=document.getElementById('mn');
  // عرض فوري من الكاش اذا موجود
  if(prefetchCache[v] && !force){{
    mn.innerHTML=prefetchCache[v];
    bind();execScripts();
    // تحديث خفي
    fetch('/api/page?v='+v,{{cache:'no-store'}}).then(r=>r.text()).then(h=>{{prefetchCache[v]=h;}}).catch(()=>{{}});
    // prefetch باقي الصفحات
    prefetchOthers(v);
    return;
  }}
  mn.innerHTML='<div class=card style="text-align:center;padding:30px"><div style="width:36px;height:36px;border:3px solid #ffffff15;border-top-color:#ffbe4d;border-radius:50%;animation:spin .8s linear infinite;margin:0 auto"></div><div style="margin-top:12px;color:#ffbe4d;font-weight:800">⏳ جاري التحميل...</div></div><style>@keyframes spin{{to{{transform:rotate(360deg)}}}}</style>';
  try{{
    let ctrl=new AbortController();
    let to=setTimeout(()=>ctrl.abort(),8000);
    let r=await fetch('/api/page?v='+v,{{cache:'no-store',signal:ctrl.signal}});
    clearTimeout(to);
    let h=await r.text();
    prefetchCache[v]=h;
    mn.innerHTML=h;
    bind();execScripts();
    prefetchOthers(v);
  }}catch(e){{
    mn.innerHTML='<div class=card>❌ خطأ: '+e+'<br><br><button class=btn-gold onclick="loadPage(\\''+v+'\\',true)">↻ حاول مرة ثانية</button></div>';
  }}
}}
function prefetchOthers(current){{
  let pages=['home','dishes','towers','subs','network','map','logs'];
  pages.forEach(p=>{{
    if(p!==current && !prefetchCache[p]){{
      fetch('/api/page?v='+p,{{cache:'no-store'}}).then(r=>r.text()).then(h=>{{prefetchCache[p]=h;}}).catch(()=>{{}});
    }}
  }});
}}
function execScripts(){{
  document.getElementById('mn').querySelectorAll('script').forEach(s=>{{try{{(0,eval)(s.textContent)}}catch(e){{console.error(e)}}}});
}}
function bind(){{
  document.querySelectorAll('form[data-ajax]').forEach(f=>{{
    if(f.dataset.bound) return;
    f.dataset.bound='1';
    f.onsubmit=async e=>{{
      e.preventDefault();
      let btn=f.querySelector('button');
      let old=btn?btn.innerHTML:'';
      if(btn){{btn.innerHTML='⏳ جاري...'; btn.disabled=true;}}
      try{{
        let r=await fetch(f.action,{{method:'POST',body:new FormData(f)}});
        let txt=await r.text();
        if(r.ok){{
          delete prefetchCache[cur];
          await loadPage(cur,true);
        }}else{{
          alert(txt);
          if(btn){{btn.innerHTML=old; btn.disabled=false;}}
        }}
      }}catch(err){{
        alert(err);
        if(btn){{btn.innerHTML=old; btn.disabled=false;}}
      }}
    }};
  }});
}}
function askDel(u){{window._delUrl=u;document.getElementById('delModal').classList.add('show');}}
function closeDel(){{document.getElementById('delModal').classList.remove('show');window._delUrl=null;}}
window.closeEditModal=function(){{document.getElementById('editModal').classList.remove('show');}}
document.getElementById('editModal').addEventListener('click',e=>{{if(e.target.id==='editModal')closeEditModal();}});
document.getElementById('delModal').addEventListener('click',e=>{{if(e.target.id==='delModal')closeDel();}});
document.getElementById('delYes').onclick=async()=>{{
  if(window._delUrl){{
    let r=await fetch(window._delUrl);
    if(!r.ok){{let t=await r.text(); alert(t); closeDel(); return;}}
    delete prefetchCache[cur];
    closeDel();
    loadPage(cur,true);
  }}
}};
async function toggleTheme(){{
  try{{ await fetch('/toggle_theme'); location.reload(); }}catch(e){{location.reload();}}
}}
let searchTimer=null;
window.globalSearchTop=async function(q){{
  let box=document.getElementById('searchResults');
  if(!q || q.length<1){{ box.style.display='none'; return; }}
  clearTimeout(searchTimer);
  searchTimer=setTimeout(async ()=>{{
    try{{
      let r=await fetch('/api/search?q='+encodeURIComponent(q),{{cache:'no-store'}});
      let d=await r.json();
      if(!d || d.length==0){{ box.innerHTML='<div style="padding:14px;text-align:center;color:#777">🔍 لا يوجد نتائج لـ: '+q+'</div>'; box.style.display='block'; return; }}
      let h='<div style="padding:10px;background:#ffffff06;font-weight:800;border-bottom:1px solid #ffffff0a">🔍 نتائج ('+d.length+')</div>';
      d.slice(0,10).forEach(x=>{{
        h+='<div style="padding:12px;border-bottom:1px solid #ffffff06;cursor:pointer;display:flex;justify-content:space-between;align-items:center" onclick="loadPage(\\''+x.page+'\\');document.getElementById(\\'searchResults\\').style.display=\\'none\\'"><div><b>'+x.title+'</b><br><small style=color:#888>'+x.sub+'</small></div><small style=color:#ffbe4d>'+x.page+'</small></div>';
      }});
      box.innerHTML=h; box.style.display='block';
    }}catch(e){{ box.style.display='none'; }}
  }},250);
}}
window.toggleNotif=async function(){{
  let panel=document.getElementById('notifPanel');
  panel.style.display=panel.style.display==='block'?'none':'block';
  if(panel.style.display==='block'){{
    try{{
      let r=await fetch('/api/notifications');
      let j=await r.json();
      let h='<div style="padding:14px"><div style="display:flex;justify-content:space-between;align-items:center"><b>🔔 الإشعارات ('+j.unread+')</b><button onclick="readAllNotif()" style="background:linear-gradient(90deg,#ffbe4d,#ffb020);border:0;padding:6px 12px;border-radius:8px;font-weight:800;cursor:pointer">مقروء</button></div><hr style="border-color:#ffffff0f;margin:10px 0">';
      j.rows.forEach(n=>{{ h+='<div style="padding:10px;border-bottom:1px solid #ffffff08"><b style="color:#ffbe4d;font-size:13px">'+n.title+'</b><br><small style="color:#ccc">'+n.msg+'</small><br><small style="color:#666">'+n.time+'</small></div>'; }});
      h+='</div>'; panel.innerHTML=h;
    }}catch(e){{}}
  }}
}}
window.readAllNotif=async function(){{
  try{{ await fetch('/api/notifications/read',{{method:'POST'}}); }}catch(e){{}}
  document.getElementById('notifCount').style.display='none';
  let mc=document.getElementById('menuNotifCount'); if(mc) mc.style.display='none';
  document.getElementById('notifPanel').style.display='none';
}}
async function loadNotif(){{
  try{{
    let r=await fetch('/api/notifications');
    let j=await r.json();
    let c=document.getElementById('notifCount'); let mc=document.getElementById('menuNotifCount');
    if(j.unread>0){{ c.textContent=j.unread>99?'99+':j.unread; c.style.display='flex'; if(mc){{mc.textContent=j.unread; mc.style.display='inline-block';}} }} else {{ c.style.display='none'; if(mc) mc.style.display='none'; }}
  }}catch(e){{}}
}}
loadNotif(); setInterval(loadNotif,12000);
window.logoutFast=async function(){{ try{{await fetch('/api/logout',{{method:'POST'}});}}catch(e){{}} localStorage.clear(); location.replace('/login'); }};
window.addEventListener('popstate', (e)=>{{ let v='home'; if(e.state && e.state.page){{ v=e.state.page; }} else {{ let p=new URLSearchParams(window.location.search); v=p.get('v')||'home'; }} loadPage(v,false,false); }});
bind();
execScripts();
prefetchOthers(cur);
if(!history.state){{ try{{history.replaceState({{page:cur}}, '', '/dash?v='+cur);}}catch(e){{}} }}
// keepalive لـ cron-job.org
setInterval(()=>{{fetch('/ping').catch(()=>{{}});}}, 600000);
</script>
</body></html>"""

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
