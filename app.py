from flask import Flask, request, redirect, session, jsonify, Response
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, html, ipaddress, subprocess, json, socket, platform, io, csv
try:
    import psycopg2, psycopg2.extras
except:
    psycopg2 = None
import sqlite3

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or "omia-sec-2026-CHANGE-ME"
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
    except:
        cc(c)

def add_log(user_phone, action, detail):
    try:
        import datetime
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)",(user_phone or 'unknown', action, detail, now))
        qexec("INSERT INTO notifications(title,msg,time) VALUES(?,?,?)",(action, str(user_phone)+": "+str(detail), now))
    except:
        pass

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

def is_valid_ip(ip):
    ip=ip.strip()
    if not ip:
        return False
    try:
        import ipaddress
        ipaddress.ip_address(ip)
        return True
    except:
        parts=ip.split('.')
        if len(parts)==4:
            try:
                return all(0<=int(pp)<=255 for pp in parts)
            except:
                return False
        return False

def is_internal_ip(ip):
    try:
        o=ipaddress.ip_address(ip.strip())
        return o.is_private and not o.is_loopback and not o.is_multicast and not o.is_unspecified
    except:
        return False

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
        out=subprocess.check_output(cmd,timeout=4).decode(errors='ignore')
        ok='ttl=' in out.lower() or 'bytes from' in out.lower()
        return jsonify(ok=ok,out=('✅ متصل ' if ok else '❌ لا يرد ')+out[:400])
    except Exception as e:
        return jsonify(ok=False,out=f'❌ لا يرد {e}')

@app.route('/api/notifications')
@login_required
def api_noti():
    rows=qall("SELECT * FROM notifications ORDER BY id DESC LIMIT 20")
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
    rows=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 100")
    return jsonify(rows)

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
        return jsonify(ok=True)
    return jsonify(ok=False,msg='خطأ بالدخول'),401

@app.route('/api/export/<tbl>')
@login_required
def api_export(tbl):
    output=io.StringIO()
    w=csv.writer(output)
    if tbl=='dishes':
        rows=qall("SELECT * FROM dish_ips ORDER BY id DESC")
        w.writerow(['ID','اسم الصحن','IP','الموقع'])
        for r in rows:
            w.writerow([r['id'],r.get('dish_name',''),r.get('ip',''),r.get('location','')])
        fname='dishes.csv'
    elif tbl=='subs':
        rows=qall("SELECT * FROM subs ORDER BY id DESC")
        w.writerow(['ID','الاسم','رقم','ملاحظة'])
        for r in rows:
            w.writerow([r['id'],r.get('name',''),r.get('phone',''),r.get('note','')])
        fname='subs.csv'
    elif tbl=='users':
        rows=qall("SELECT phone,username,role FROM users ORDER BY phone DESC")
        w.writerow(['يوزر/رقم','اسم المستخدم','الرتبة'])
        for r in rows:
            w.writerow([r.get('phone',''),r.get('username',''),r.get('role','')])
        fname='users.csv'
    elif tbl=='towers':
        rows=qall("SELECT * FROM towers ORDER BY id DESC")
        w.writerow(['ID','اسم البرج','المنطقة','lat','lng'])
        for r in rows:
            w.writerow([r['id'],r.get('name',''),r.get('area',''),r.get('lat',''),r.get('lng','')])
        fname='towers.csv'
    elif tbl=='logs':
        rows=qall("SELECT * FROM logs ORDER BY id DESC")
        w.writerow(['ID','يوزر','فعل','تفصيل','وقت'])
        for r in rows:
            w.writerow([r['id'],r.get('user_phone',''),r.get('action',''),r.get('detail',''),r.get('time','')])
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
body{margin:0;min-height:100vh;background:#0a0e2a;display:flex;flex-direction:column;align-items:center;justify-content:center;color:#fff;font-family:system-ui}
.card{background:#1e2433cc;border:1px solid #ffffff15;padding:25px;border-radius:20px;width:92%;max-width:360px;box-shadow:0 20px 60px #0008;animation:fadeIn .4s ease}
@keyframes fadeIn{from{opacity:0;transform:translateY(15px)}to{opacity:1;transform:none}}
input{width:100%;padding:12px;margin:8px 0;background:#0f1424;border:1px solid #ffffff20;color:#fff;border-radius:12px;box-sizing:border-box;transition:border .2s}
input:focus{border-color:#ffbe4d;outline:none}
.btn{width:100%;padding:13px;border:0;border-radius:12px;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:900;font-size:16px;cursor:pointer;margin-top:10px;transition:all .2s}
.btn:hover{transform:translateY(-1px);box-shadow:0 6px 20px #ffbe4d55}
.btn:active{transform:scale(.98)}
.save-row{display:flex;align-items:center;gap:8px;margin:8px 0;font-size:13px;color:#aaa}
.save-row input{width:auto;margin:0}
</style></head><body>
<div style='font-size:28px;font-weight:900;margin-bottom:12px'>OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<div class=card>
<form id=loginForm>
<input name=userin id=userin placeholder='📱 رقم / يوزر' required autocomplete='username'>
<input name=password id=password type=password placeholder='🔑 كلمة السر' required autocomplete='current-password'>
<label class=save-row><input type=checkbox id=savePass> 💾 حفظ كلمة السر</label>
<button class=btn id=loginBtn>✨ دخول فوري</button>
<div id=msg style='text-align:center;margin-top:8px;color:#ef4444;font-size:13px'></div>
</form>
<div style='text-align:center;margin-top:12px'><a href='https://wa.me/905344851045' style='color:#22c55e;text-decoration:none;font-weight:800'>💬 واتساب الدعم الفني فقط</a></div>
</div>
<script>
let u=document.getElementById('userin'), p=document.getElementById('password'), s=document.getElementById('savePass');
let su=localStorage.getItem('omaia_user'), sp=localStorage.getItem('omaia_pass');
if(su){u.value=su; if(sp){p.value=sp; s.checked=true;}}
document.getElementById('loginForm').addEventListener('submit',async e=>{
 e.preventDefault();
 let btn=document.getElementById('loginBtn'), msg=document.getElementById('msg');
 btn.textContent='⏳ دخول...'; btn.disabled=true;
 try{
  let fd=new FormData(e.target);
  let r=await fetch('/api/login_public',{method:'POST',body:fd});
  let j=await r.json();
  if(j.ok){
   if(s.checked){localStorage.setItem('omaia_user',u.value);localStorage.setItem('omaia_pass',p.value);}else{localStorage.removeItem('omaia_user');localStorage.removeItem('omaia_pass');}
   location.href='/dash?v=home';
  }else{msg.textContent=j.msg||'خطأ'; btn.textContent='✨ دخول فوري'; btn.disabled=false;}
 }catch(err){msg.textContent='خطأ شبكة'; btn.textContent='✨ دخول فوري'; btn.disabled=false;}
});
</script>
</body></html>"""

@app.route('/logout')
def lo():
    try:
        add_log(session.get('phone',''), 'خرج من النظام', 'تسجيل خروج')
    except:
        pass
    session.clear()
    return redirect('/login')

@app.route('/api/logout', methods=['POST'])
def api_logout():
    try:
        add_log(session.get('phone',''), 'خرج من النظام', 'تسجيل خروج')
    except:
        pass
    session.clear()
    return jsonify(ok=True)

def logout_fast_js():
    return ""


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
    for r in qall("SELECT * FROM dish_ips WHERE ip LIKE ? OR dish_name LIKE ? OR location LIKE ? ORDER BY id DESC LIMIT 20",(like,like,like)):
        results.append({"type":"dish","id":r['id'],"title":r.get('dish_name') or 'صحن',"sub":r.get('ip',''),"page":"dishes"})
    for r in qall("SELECT * FROM subs WHERE name LIKE ? OR phone LIKE ? OR note LIKE ? ORDER BY id DESC LIMIT 20",(like,like,like)):
        results.append({"type":"sub","id":r['id'],"title":r.get('name',''),"sub":r.get('phone',''),"page":"subs"})
    for r in qall("SELECT * FROM towers WHERE name LIKE ? OR area LIKE ? ORDER BY id DESC LIMIT 20",(like,like)):
        results.append({"type":"tower","id":r['id'],"title":r.get('name',''),"sub":r.get('area',''),"page":"towers"})
    for r in qall("SELECT * FROM users WHERE phone LIKE ? OR username LIKE ? ORDER BY phone DESC LIMIT 20",(like,like)):
        results.append({"type":"user","id":r['phone'],"title":r.get('phone',''),"sub":r.get('role',''),"page":"settings"})
    for r in qall("SELECT * FROM logs WHERE user_phone LIKE ? OR action LIKE ? OR detail LIKE ? ORDER BY id DESC LIMIT 20",(like,like,like)):
        results.append({"type":"log","id":r['id'],"title":r.get('action',''),"sub":r.get('user_phone','')+" - "+r.get('detail',''),"page":"logs"})
    return jsonify(results)

@app.route('/api/dishes')
@login_required
def api_dishes():
    rs=qall("SELECT * FROM dish_ips ORDER BY id DESC")
    return jsonify(rs)

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
    if not ip:
        return "IP مطلوب",400
    if not is_valid_ip(ip):
        return "IP غير صالح - مثال 192.168.1.1",400
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
    qexec("UPDATE dish_ips SET dish_name=?,ip=?,location=? WHERE id=?",
          (request.form.get('dish_name',''),request.form.get('ip',''),request.form.get('location',''),i))
    add_log(session.get('phone',''), 'عدل صحن', f"id={i}")
    return "ok"

@app.route('/del_dish/<int:i>')
@login_required
def dd(i):
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
    qexec("DELETE FROM towers WHERE id=?",(i,))
    return "ok"

@app.route('/edit_tower/<int:i>',methods=['POST'])
@login_required
def et(i):
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
    return "ok"

@app.route('/del_sub/<int:i>')
@login_required
def dsub(i):
    qexec("DELETE FROM subs WHERE id=?",(i,))
    return "ok"

@app.route('/edit_sub/<int:i>',methods=['POST'])
@login_required
def esub(i):
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
    qexec("DELETE FROM ledger WHERE id=?",(i,))
    return "ok"

@app.route('/edit_ledger/<int:i>',methods=['POST'])
@login_required
def el(i):
    try: amt=float(request.form.get('amount') or 0)
    except: amt=0
    qexec("UPDATE ledger SET name=?,amount=?,note=?,currency=? WHERE id=?",
          (request.form.get('name',''),amt,request.form.get('note',''),request.form.get('currency','USD'),i))
    return "ok"

@app.route('/add_user',methods=['POST'])
@login_required
def au():
    ph=request.form.get('phone','').strip() or request.form.get('username','').strip() or request.form.get('user_field','').strip()
    if not ph:
        return "رقم مطلوب",400
    if qone("SELECT * FROM users WHERE phone=?",(ph,)):
        return "موجود مسبقاً",400
    qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",
          (ph,generate_password_hash(request.form.get('password','1234')),request.form.get('role','tech'),ph))
    return "ok"

@app.route('/edit_user',methods=['POST'])
@login_required
def eu():
    old=request.form.get('old_phone','').strip()
    new_ph=request.form.get('phone','').strip() or request.form.get('user_field','').strip() or request.form.get('username','').strip()
    new_user=new_ph
    new_role=request.form.get('role','tech')
    new_pass=request.form.get('password','').strip()
    if not old:
        return "خطأ",400
    if new_pass:
        qexec("UPDATE users SET phone=?,username=?,role=?,password=? WHERE phone=?",
              (new_ph,new_user,new_role,generate_password_hash(new_pass),old))
    else:
        qexec("UPDATE users SET phone=?,username=?,role=? WHERE phone=?",
              (new_ph,new_user,new_role,old))
    if session.get('phone')==old:
        session['phone']=new_ph
    return "ok"

@app.route('/del_user/<ph>')
@login_required
def du(ph):
    if ph=='05344851045':
        return "ممنوع حذف المدير",400
    qexec("DELETE FROM users WHERE phone=?",(ph,))
    return "ok"

@app.route('/change_pass',methods=['POST'])
@login_required
def cp():
    np=request.form.get('newpass','').strip()
    if not np:
        return "فارغة",400
    qexec("UPDATE users SET password=? WHERE phone=?",
          (generate_password_hash(np),session.get('phone')))
    return "ok"

def page_content(v):
    if v=='home':
        ns=(qone("SELECT COUNT(*) c FROM subs") or {}).get('c',0)
        nd=(qone("SELECT COUNT(*) c FROM dish_ips") or {}).get('c',0)
        nt=(qone("SELECT COUNT(*) c FROM towers") or {}).get('c',0)
        nl=(qone("SELECT COUNT(*) c FROM ledger") or {}).get('c',0)
        logs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 5")
        log_html=""
        for l in logs:
            log_html+="<div style='font-size:12px;padding:6px;border-bottom:1px solid #ffffff10'><b>"+esc(l.get('user_phone',''))+"</b> "+esc(l.get('action',''))+" <small>"+esc(l.get('detail',''))+"</small><br><small style='color:#aaa'>"+esc(l.get('time',''))+"</small></div>"
        return f"""
        <div style='max-width:700px;margin:0 auto;text-align:center'>
          <div style='display:grid;grid-template-columns:1fr 1fr;gap:12px'>
            <div class='card anim' onclick="loadPage('subs')" style='cursor:pointer'><h3>المشتركين</h3><h2>{ns}</h2></div>
            <div class='card anim' onclick="loadPage('dishes')" style='cursor:pointer'><h3>الصحون - Ping</h3><h2>{nd}</h2></div>
            <div class='card anim' onclick="loadPage('towers')" style='cursor:pointer'><h3>الأبراج</h3><h2>{nt}</h2></div>
            <div class='card anim' onclick="loadPage('ledger')" style='cursor:pointer'><h3>الحسابات</h3><h2>{nl}</h2></div>
          </div>
          <div class=card style='margin-top:12px;text-align:right'><h4>📜 اخر السجل - مين دخل ومين عدل</h4>{log_html}<button class=btn-gold onclick="loadPage('logs')" style='width:100%;margin-top:8px'>عرض كل السجل</button></div>
          <div style='margin-top:16px;display:flex;gap:8px;justify-content:center;flex-wrap:wrap'>
            <a href='/api/export/dishes' class=btn-gold style='text-decoration:none'>📊 صحون</a>
            <a href='/api/export/logs' class=btn-gold style='text-decoration:none'>📜 سجل</a>
            <button onclick="window.print()" class=btn-gold>📄 PDF</button>
          </div>
          <a href='https://wa.me/905344851045' target=_blank style='position:fixed;left:20px;bottom:20px;background:#25D366;color:#fff;width:56px;height:56px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:28px;text-decoration:none;box-shadow:0 8px 24px #0006;z-index:9999'>💬</a>
        </div>""".replace("{log_html}", log_html)


    if v=='dishes':
        rs=qall("SELECT * FROM dish_ips ORDER BY id DESC")
        rows_html=""
        for r in rs:
            dn=esc(r.get('dish_name') or 'صحن')
            ip=esc(r.get('ip') or '')
            loc=esc(r.get('location') or '')
            rid=r['id']
            rows_html+= '<div class="card anim" id="dish-'+str(rid)+'" data-name="'+dn+'" data-ip="'+ip+'" data-loc="'+loc+'" style="display:flex;justify-content:space-between;align-items:center"><div><b>'+dn+'</b><br><button onclick="window.openChrome(\''+ip+'\')" style="background:#000;color:#ffbe4d;padding:6px 12px;border-radius:10px;border:0;cursor:pointer;font-family:monospace">🌐 '+ip+' ↗ Chrome</button><br><small>'+loc+'</small><br><small class="ping-out" style="font-size:11px;color:#aaa">جاهز للـ Ping</small></div><div style="display:flex;flex-direction:column;gap:5px"><button class=btn-gold onclick="window.doPing('+str(rid)+')">📶 Ping</button><div style="display:flex;gap:5px"><button class=btn-gold onclick="window.doEditDish('+str(rid)+')" style="padding:8px 10px">✏</button><button class=btn-del onclick="askDel(\'/del_dish/'+str(rid)+'\')" style="padding:8px 10px">🗑</button></div></div></div>'
        return f"""<div style='max-width:900px;margin:0 auto'>
<div class=card>
<div style='display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px'>
<h3>📡 الصحون - مع Ping ({len(rs)}) - يظهر بالشاشة فورا</h3>
<div style='display:flex;gap:6px'>
<button onclick="pingAll()" class=btn-gold style='padding:6px 10px;font-size:12px'>📶 Ping الكل</button>
<a href='/api/export/dishes' class=btn-gold style='text-decoration:none;padding:7px 12px;font-size:13px'>📊 Excel</a>
</div>
</div>
<form data-ajax method=post action=/add_dish style='display:flex;gap:5px;flex-wrap:wrap;margin-top:8px'>
<input name=dish_name placeholder='اسم الصحن' required style='flex:1'>
<input name=ip placeholder='IP مثال 192.168.1.1' required style='flex:1'>
<input name=location placeholder='موقع' style='flex:1'>
<button class=btn-gold>➕ إضافة IP</button>
</form>
<input id=searchBox placeholder='🔍 بحث IP أو اسم' oninput="window.searchDishes(this.value)" style='margin-top:8px;width:100%;padding:10px;border-radius:10px'>
<div id=addMsg style='font-size:12px;color:#22c55e;margin-top:4px'>✅ {len(rs)} صحن محمل - يظهر بالشاشة + اشعارات</div>
</div>
<div id=dl>
{rows_html}
</div>
</div>
<script>
window.openEditModal=function(type,id){{
  let modal=document.getElementById('editModal');
  modal.classList.add('show');
  let card=document.getElementById(type+'-'+id);
  if(type==='dish'){{
    document.getElementById('editTitle').textContent='✏ تعديل صحن';
    document.getElementById('editBody').innerHTML='<label style="display:block;text-align:right;font-size:12px;margin-top:6px">اسم الصحن</label><input id=edit_dish_name value="'+(card.dataset.name||'').replace(/"/g,'&quot;')+'" style="width:100%;padding:10px;border-radius:8px;margin-top:4px"><label style="display:block;text-align:right;font-size:12px;margin-top:8px">IP</label><input id=edit_ip value="'+(card.dataset.ip||'')+'" style="width:100%;padding:10px;border-radius:8px;margin-top:4px"><label style="display:block;text-align:right;font-size:12px;margin-top:8px">موقع</label><input id=edit_loc value="'+(card.dataset.loc||'').replace(/"/g,'&quot;')+'" style="width:100%;padding:10px;border-radius:8px;margin-top:4px"><button onclick="window.saveEdit(\\'dish\\',"+id+")" class=btn-gold style="width:100%;margin-top:12px;padding:12px">💾 حفظ</button>';
  }}
}}
window.saveEdit=function(type,id){{
  if(type==='dish'){{
    let nn=document.getElementById('edit_dish_name').value;
    let ii=document.getElementById('edit_ip').value;
    let ll=document.getElementById('edit_loc').value;
    fetch('/edit_dish/'+id,{{method:'POST',body:new URLSearchParams({{dish_name:nn,ip:ii,location:ll}})}}).then(()=>{{closeEditModal(); loadPage('dishes',true);}});
  }}
}}
window.openChrome=function(ip){{ let url='http://'+ip; let w=window.open(url,'_blank'); if(!w){{ navigator.clipboard.writeText(url).then(()=>alert('تم نسخ: '+url+'\nالصق في كروم')).catch(()=>prompt('انسخ:',url)); }} }};
window.doEditDish=function(id){{ window.openEditModal('dish',id); }}
window.doPing=function(id){{
  let c=document.getElementById('dish-'+id);
  let out=c.querySelector('.ping-out');
  out.textContent='⏳ ping...';
  fetch('/api/ping?ip='+encodeURIComponent(c.dataset.ip)).then(r=>r.json()).then(j=>{{
    out.textContent=j.out.slice(0,250);
    out.style.color=j.ok?'#22c55e':'#ef4444';
  }}).catch(()=>{{out.textContent='خطأ';}});
}}
window.pingAll=async function(){{
  let cards=document.querySelectorAll('[id^=dish-]');
  for(let c of cards){{
    let out=c.querySelector('.ping-out');
    if(!out) continue;
    out.textContent='⏳...';
    try{{
      let r=await fetch('/api/ping?ip='+encodeURIComponent(c.dataset.ip));
      let j=await r.json();
      out.textContent=j.ok?'✅ '+j.out.slice(0,80):'❌ '+j.out.slice(0,80);
      out.style.color=j.ok?'#22c55e':'#ef4444';
    }}catch(e){{ out.textContent='خطأ'; }}
    await new Promise(r=>setTimeout(r,300));
  }}
}}
window.searchDishes=function(q){{
  q=(q||'').toLowerCase();
  document.querySelectorAll('[id^=dish-]').forEach(card=>{{
    let name=(card.dataset.name||'').toLowerCase();
    let ip=(card.dataset.ip||'').toLowerCase();
    let loc=(card.dataset.loc||'').toLowerCase();
    if(!q || name.includes(q) || ip.includes(q) || loc.includes(q)){{ card.style.display='flex'; }} else {{ card.style.display='none'; }}
  }});
}}
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
            rows+=f"<div class='card anim' id='tower-{r['id']}' data-name='{sn}' data-area='{sa}' data-lat='{lat}' data-lng='{lng}' style=''><div style='display:flex;justify-content:space-between'><div><b>🗼 {sn}</b><br><small>{sa}</small><br><small style='color:#ffbe4d'>📍 {lat} , {lng}</small></div><div style='display:flex;gap:5px'><button class=btn-gold onclick=\"window.openEditTower({r['id']})\" style='padding:8px 10px'>✏</button><button class=btn-del onclick=\"askDel('/del_tower/{r['id']}')\" style='padding:8px 10px'>🗑</button></div></div><div style='margin-top:6px'><a href='https://maps.google.com/?q={lat},{lng}' target=_blank style='font-size:12px;color:#22c55e'>🗺 فتح بخرائط جوجل</a> | <button onclick=\"navigator.clipboard.writeText('{lat},{lng}')\" style='font-size:12px;background:transparent;border:0;color:#ffbe4d;cursor:pointer'>📋 نسخ الاحداثية</button></div></div>"
        return f"""<div style='max-width:700px;margin:0 auto'>
<div class=card><div style='display:flex;justify-content:space-between'><h3>🗼 الأبراج</h3><div><a href='/api/export/towers' class=btn-gold style='text-decoration:none;padding:6px 10px;font-size:12px'>📊 Excel</a> <button onclick="window.print()" class=btn-gold style='padding:6px 10px;font-size:12px'>📄 PDF</button></div></div>
<form data-ajax method=post action=/add_tower style='display:flex;gap:6px;flex-wrap:wrap;margin-top:8px'>
<input name=name placeholder='اسم البرج' required style='flex:1'>
<input name=area placeholder='المنطقة' style='flex:1'>
<input name=lat placeholder='lat 35.1318' style='flex:0.6'>
<input name=lng placeholder='lng 36.7578' style='flex:0.6'>
<button class=btn-gold>➕ إضافة</button>
</form></div>
{rows or '<div class=card>لا يوجد أبراج</div>'}
<script>
window.openEditTower=function(id){{
  let c=document.getElementById('tower-'+id);
  document.getElementById('editModal').classList.add('show');
  document.getElementById('editTitle').textContent='✏ تعديل برج + احداثية';
  document.getElementById('editBody').innerHTML='<input id=edit_t_name value="'+c.dataset.name+'" placeholder="اسم" style="width:100%;margin:6px 0;padding:10px;border-radius:8px"><input id=edit_t_area value="'+c.dataset.area+'" placeholder="منطقة" style="width:100%;margin:6px 0;padding:10px;border-radius:8px"><input id=edit_t_lat value="'+c.dataset.lat+'" placeholder="lat" style="width:100%;margin:6px 0;padding:10px;border-radius:8px"><input id=edit_t_lng value="'+c.dataset.lng+'" placeholder="lng" style="width:100%;margin:6px 0;padding:10px;border-radius:8px"><button onclick="window.saveTower('+id+')" class=btn-gold style="width:100%;padding:12px">💾 حفظ</button>';
}}
window.saveTower=function(id){{
  let nn=document.getElementById('edit_t_name').value;
  let aa=document.getElementById('edit_t_area').value;
  let la=document.getElementById('edit_t_lat').value;
  let ln=document.getElementById('edit_t_lng').value;
  fetch('/edit_tower/'+id,{{method:'POST',body:new URLSearchParams({{name:nn,area:aa,lat:la,lng:ln}})}}).then(()=>{{closeEditModal(); loadPage('towers',true);}});
}}
</script></div>"""
    if v=='subs':
        rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 200")
        rows=""
        for r in rs:
            rows+=f"<div class='card anim' id='sub-{r['id']}' data-name='{esc(r['name'])}' data-phone='{esc(r['phone'] or '')}' data-note='{esc(r['note'] or '')}' style='display:flex;justify-content:space-between;align-items:center'><div><b>{esc(r['name'])}</b><br>📞 {esc(r['phone'] or '')}<br><small>{esc(r['note'] or '')}</small></div><div style='display:flex;gap:5px'><button class=btn-gold onclick=\"window.openEditSub({r['id']})\" style='padding:8px 10px'>✏</button><button class=btn-del onclick=\"askDel('/del_sub/{r['id']}')\" style='padding:8px 10px'>🗑</button></div></div>"
        return f"""<div style='max-width:700px;margin:0 auto'>
<div class=card><div style='display:flex;justify-content:space-between;align-items:center'><h3>👥 المشتركين</h3><div><a href='/api/export/subs' class=btn-gold style='text-decoration:none;padding:6px 10px;font-size:12px'>📊 Excel</a> <button onclick="window.print()" class=btn-gold style='padding:6px 10px;font-size:12px'>📄 PDF</button></div></div>
<form data-ajax method=post action=/add_sub style='display:flex;gap:5px;flex-wrap:wrap;margin-top:8px'>
<input name=name placeholder='الاسم / اليوزر' required style='flex:1'>
<input name=phone placeholder='رقم' style='flex:1'>
<input name=note placeholder='ملاحظة' style='flex:1'>
<button class=btn-gold>➕</button>
</form></div>
{rows or '<div class=card>لا يوجد</div>'}
<script>
window.openEditSub=function(id){{
  let c=document.getElementById('sub-'+id);
  document.getElementById('editModal').classList.add('show');
  document.getElementById('editTitle').textContent='✏ تعديل مشترك';
  document.getElementById('editBody').innerHTML='<input id=edit_s_name value="'+c.dataset.name+'" style="width:100%;margin:6px 0;padding:10px;border-radius:8px"><input id=edit_s_phone value="'+c.dataset.phone+'" style="width:100%;margin:6px 0;padding:10px;border-radius:8px"><input id=edit_s_note value="'+c.dataset.note+'" style="width:100%;margin:6px 0;padding:10px;border-radius:8px"><button onclick="window.saveSub('+id+')" class=btn-gold style="width:100%;padding:12px">💾 حفظ</button>';
}}
window.saveSub=function(id){{
  let nn=document.getElementById('edit_s_name').value;
  let pp=document.getElementById('edit_s_phone').value;
  let no=document.getElementById('edit_s_note').value;
  fetch('/edit_sub/'+id,{{method:'POST',body:new URLSearchParams({{name:nn,phone:pp,note:no}})}}).then(()=>{{closeEditModal(); loadPage('subs',true);}});
}}
</script></div>"""
    if v=='ledger':
        rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 200")
        rows=""
        for r in rs:
            rows+=f"<div class='card anim' id='led-{r['id']}' data-name='{esc(r['name'])}' data-amount='{r['amount']}' style='display:flex;justify-content:space-between;align-items:center'><div><b>{esc(r['name'])}</b> - {r['amount']} {esc(r['currency'] or 'USD')}<br><small>{esc(r['note'] or '')}</small></div><div style='display:flex;gap:5px'><button class=btn-gold onclick=\"window.openEditLed({r['id']})\" style='padding:8px 10px'>✏</button><button class=btn-del onclick=\"askDel('/del_ledger/{r['id']}')\" style='padding:8px 10px'>🗑</button></div></div>"
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
window.openEditLed=function(id){{
  let c=document.getElementById('led-'+id);
  document.getElementById('editModal').classList.add('show');
  document.getElementById('editTitle').textContent='✏ تعديل حساب';
  document.getElementById('editBody').innerHTML='<input id=edit_l_name value="'+c.dataset.name+'" style="width:100%;margin:6px 0;padding:10px;border-radius:8px"><input id=edit_l_amount value="'+c.dataset.amount+'" style="width:100%;margin:6px 0;padding:10px;border-radius:8px"><button onclick="window.saveLed('+id+')" class=btn-gold style="width:100%;padding:12px">💾 حفظ</button>';
}}
window.saveLed=function(id){{
  let nn=document.getElementById('edit_l_name').value;
  let aa=document.getElementById('edit_l_amount').value;
  fetch('/edit_ledger/'+id,{{method:'POST',body:new URLSearchParams({{name:nn,amount:aa,note:'',currency:'USD'}})}}).then(()=>{{closeEditModal(); loadPage('ledger',true);}});
}}
</script></div>"""
    if v=='logs':
        rs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 200")
        rows=""
        for r in rs:
            rows+=f"<div class='card anim' style='font-size:13px'><div style='display:flex;justify-content:space-between'><b style='color:#ffbe4d'>{esc(r['user_phone'])}</b><small>{esc(r['time'])}</small></div><div><b>{esc(r['action'])}</b> - {esc(r['detail'])}</div></div>"
        return f"<div style='max-width:800px;margin:0 auto'><div class=card><h3>📜 سجل النشاطات - يبين مين دخل ومين عدل وشو عدل</h3><a href='/api/export/logs' class=btn-gold style='text-decoration:none;padding:6px 10px'>تصدير Excel</a></div>{rows or '<div class=card>لا يوجد سجل</div>'}</div>"

    if v=='map':
        towers=qall("SELECT * FROM towers")
        tj=towers
        # Build JSON safely
        import json as _json
        tj_json=_json.dumps([{"name":t['name'],"area":t.get('area') or '',"lat":float(t.get('lat') or 35.1318),"lng":float(t.get('lng') or 36.7578)} for t in towers],ensure_ascii=False)
        return f"""<div class=card style='padding:6px'>
<div style='display:flex;gap:6px;margin-bottom:6px;flex-wrap:wrap'>
<input id=mapSearch placeholder='🔍 بحث برج + Enter' onkeydown="if(event.key==='Enter'){{window.mapGo(this.value)}}" style='flex:1'>
<button class=btn-gold onclick="window.mapGo(document.getElementById('mapSearch').value)">🔍 بحث بالخريطة</button>
<button class=btn-gold onclick="locateMe()" style='background:#22c55e'>📍 موقعي</button>
<button class=btn-gold onclick="toggleMeasure()" id=measureBtn style='background:#0ea5e9'>📏 قياس مسافة</button>
<button class=btn-gold onclick="clearMeasure()" style='background:#ef4444'>🗑 مسح</button>
<span id=distanceLabel style='padding:6px 10px;background:#1f2937;border-radius:8px;font-size:12px;color:#ffbe4d'>المسافة: 0 كم</span>
</div>
<div id=map style='height:72vh;min-height:450px;border-radius:14px;background:#e5e7eb;z-index:1'></div>
<div style='margin-top:6px;font-size:11px;color:#aaa'>💡 بحث بالخريطة شغال - اكتب اسم برج واضغط بحث - اضغط على الخريطة لقياس مسافة - اسحب النقطة للتحكم</div>
</div>
<script>
let _towers={tj_json};
let measureMode=false;
let measurePoints=[];
let measureLine=null;
let measureMarkers=[];
setTimeout(()=>{{
  if(typeof L==='undefined'){{document.getElementById('map').innerHTML='<div style=text-align:center;padding:40px>⚠ فشل تحميل الخريطة - تأكد من النت</div>';return;}}
  let map=L.map('map',{{zoomControl:true}}).setView([35.1318,36.7578],12);
  let osm=L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:19,attribution:'© OSM'}}).addTo(map);
  let sat=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',{{maxZoom:19}});
  L.control.layers({{"عادية":osm,"قمر صناعي":sat}}).addTo(map);
  L.control.scale().addTo(map);
  setTimeout(()=>map.invalidateSize(),300);
  _towers.forEach(t=>{{
    let m=L.marker([t.lat,t.lng],{{draggable:true}}).addTo(map);
    m.bindPopup('<b>🗼 '+t.name+'</b><br>'+t.area+'<br><small style=color:#ffbe4d>📍 '+t.lat+','+t.lng+'</small><br>اسحب النقطة للتحكم');
    m.on('dragend',e=>{{ let ll=e.target.getLatLng(); e.target.setPopupContent('<b>🗼 '+t.name+'</b><br>'+t.area+'<br><small style=color:#ffbe4d>📍 '+ll.lat.toFixed(5)+','+ll.lng.toFixed(5)+'</small>'); }});
  }});
  window.mapGo=function(q){{
    q=(q||'').toLowerCase().trim(); 
    if(!q){{ alert('اكتب اسم برج'); return; }}
    console.log('بحث عن:',q);
    let f=_towers.find(t=>t.name.toLowerCase().includes(q)||t.area.toLowerCase().includes(q));
    if(f){{
      map.flyTo([f.lat,f.lng],16);
      L.popup().setLatLng([f.lat,f.lng]).setContent('<b>🗼 '+f.name+'</b><br>'+f.area).openOn(map);
    }} else {{ alert('❌ البرج غير موجود: '+q+'\nالابراج المتاحة: '+_towers.map(t=>t.name).join(', ')); }}
  }};
  window.locateMe=function(){{
    if(navigator.geolocation){{
      navigator.geolocation.getCurrentPosition(p=>{{ map.flyTo([p.coords.latitude,p.coords.longitude],16); L.marker([p.coords.latitude,p.coords.longitude]).addTo(map).bindPopup('📍 موقعك الحالي').openPopup(); }}, err=>{{ alert('فشل تحديد الموقع: '+err.message); }});
    }} else {{ alert('المتصفح لا يدعم تحديد الموقع'); }}
  }};
  window.toggleMeasure=function(){{
    measureMode=!measureMode;
    document.getElementById('measureBtn').style.background=measureMode?'#22c55e':'#0ea5e9';
    document.getElementById('measureBtn').textContent=measureMode?'✅ اضغط على الخريطة لقياس':'📏 قياس مسافة';
  }};
  window.clearMeasure=function(){{
    measurePoints=[];
    if(measureLine){{ map.removeLayer(measureLine); measureLine=null; }}
    measureMarkers.forEach(m=>map.removeLayer(m));
    measureMarkers=[];
    document.getElementById('distanceLabel').textContent='المسافة: 0 كم';
    measureMode=false;
    document.getElementById('measureBtn').style.background='#0ea5e9';
    document.getElementById('measureBtn').textContent='📏 قياس مسافة';
  }};
  function calcDistance(latlngs){{
    let d=0;
    for(let i=1;i<latlngs.length;i++){{ d+=latlngs[i-1].distanceTo(latlngs[i]); }}
    return d;
  }}
  map.on('click',e=>{{
    if(!measureMode) return;
    measurePoints.push(e.latlng);
    let mk=L.marker(e.latlng,{{draggable:true,icon:L.divIcon({{className:'measure-dot',html:'<div style=width:12px;height:12px;background:#ffbe4d;border:2px solid #fff;border-radius:50%></div>',iconSize:[12,12]}})}}).addTo(map);
    mk.bindPopup('نقطة '+(measurePoints.length)+'<br>'+e.latlng.lat.toFixed(5)+','+e.latlng.lng.toFixed(5)).openPopup();
    mk.on('drag',ev=>{{
      measurePoints[measureMarkers.indexOf(mk)]=ev.latlng;
      if(measureLine) measureLine.setLatLngs(measurePoints);
      let dist=calcDistance(measurePoints);
      document.getElementById('distanceLabel').textContent='المسافة: '+(dist/1000).toFixed(2)+' كم ('+Math.round(dist)+' م)';
    }});
    measureMarkers.push(mk);
    if(measureLine) map.removeLayer(measureLine);
    if(measurePoints.length>1){{
      measureLine=L.polyline(measurePoints,{{color:'#ffbe4d',weight:4,dashArray:'8,8'}}).addTo(map);
      let dist=calcDistance(measurePoints);
      document.getElementById('distanceLabel').textContent='المسافة: '+(dist/1000).toFixed(2)+' كم ('+Math.round(dist)+' م) - '+measurePoints.length+' نقطة';
    }}
  }});
}},200);
</script>
"""

    if v=='support':
        return """<div class=card style='text-align:center;max-width:500px;margin:0 auto'>
<h2>🛠 الدعم الفني</h2>
<a href='https://wa.me/905344851045' target=_blank style='display:inline-block;background:#22c55e;color:#fff;padding:14px 24px;border-radius:12px;text-decoration:none;margin:6px;font-weight:800'>💬 واتساب</a><br>
<a href='https://instagram.com/af_20_1999' target=_blank style='display:inline-block;background:linear-gradient(45deg,#feda75,#fa7e1e,#d62976);color:#fff;padding:12px 22px;border-radius:12px;text-decoration:none;margin:6px;font-weight:800'>📸 @af_20_1999 انستا</a><br>
<a href='tel:+905344851045' style='display:inline-block;background:#0ea5e9;color:#fff;padding:12px 22px;border-radius:12px;text-decoration:none;margin:6px'>📞 +90 534 485 10 45</a>
</div>"""
    if v=='settings':
        us=qall("SELECT * FROM users ORDER BY phone DESC")
        uh=""
        for u in us:
            ph=esc(u['phone'])
            ro=esc(u['role'])
            display_val=ph
            uh+='<div class="card anim" id="user-'+ph+'" data-phone="'+ph+'" data-role="'+ro+'" style="display:flex;justify-content:space-between;align-items:center"><div style="display:flex;align-items:center;gap:10px"><div style="width:40px;height:40px;border-radius:50%;background:#ffbe4d;display:flex;align-items:center;justify-content:center;color:#000;font-weight:900">'+display_val[:1].upper()+'</div><div><b style="font-family:monospace;color:#ffbe4d;font-size:15px">'+display_val+'</b><br><small style="color:#aaa">'+ro+'</small></div></div><div style="display:flex;gap:6px"><button class=btn-gold onclick="window.openEditUser(\''+ph+'\')" style="padding:8px 12px">✏</button><button class=btn-del onclick="askDel(\'/del_user/'+ph+'\')" style="padding:8px 12px">🗑</button></div></div>'
        return f"""<div style='max-width:750px;margin:0 auto'>
<div class=card><h3>🔑 كلمة السر الخاصة بي</h3>
<form data-ajax method=post action=/change_pass style='display:flex;gap:6px'>
<input name=newpass type=password placeholder='كلمة سر جديدة' required style='flex:1'>
<button class=btn-gold>💾 حفظ</button>
</form></div>
<div style='display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px'>
<div class=card style='background:linear-gradient(180deg,#1e2433,#0f1424);border:1px solid #ffbe4d30'>
<h4 style='text-align:center;margin:0 0 12px'>👤 اضافة يوزر</h4>
<form data-ajax method=post action=/add_user style='display:flex;flex-direction:column;gap:10px'>
<input name=user_field placeholder='📱 رقم / يوزر' required style='font-size:15px;padding:14px;background:#0f1424;border:1px solid #ffffff20;border-radius:12px;color:#fff'>
<input name=password type=password placeholder='🔑 كلمة سر' required style='padding:14px;background:#0f1424;border:1px solid #ffffff20;border-radius:12px;color:#fff'>
<select name=role style='padding:12px;background:#0f1424;border:1px solid #ffffff20;border-radius:12px;color:#fff'><option value=tech>فني</option><option value=manager>مدير</option></select>
<button class=btn-gold style='padding:14px;font-size:16px'>➕ اضافة</button>
</form>
</div>
<div class=card><h4>📊 تصدير</h4><div style='display:flex;flex-direction:column;gap:8px'><a href='/api/export/users' class=btn-gold style='text-decoration:none;padding:10px;text-align:center'>📥 يوزرات Excel</a><a href='/api/export/dishes' class=btn-gold style='text-decoration:none;padding:10px;text-align:center'>📥 صحون Excel</a><a href='/api/export/logs' class=btn-gold style='text-decoration:none;padding:10px;text-align:center'>📥 سجل Excel</a><button onclick="window.print()" class=btn-gold style='padding:10px'>📄 طباعة PDF</button></div></div>
</div>
{uh}
<script>
window.openEditUser=function(ph){{
  let c=document.getElementById('user-'+ph);
  document.getElementById('editModal').classList.add('show');
  document.getElementById('editTitle').textContent='✏ تعديل يوزر';
  document.getElementById('editBody').innerHTML='<input id=edit_u_field value="'+c.dataset.phone+'" style="width:100%;padding:10px;border-radius:8px;margin:6px 0"><input id=edit_u_pass type="password" placeholder="كلمة سر جديدة (فاضي=بدون تغيير)" style="width:100%;padding:10px;border-radius:8px;margin:6px 0"><button onclick="window.saveUser(\\'"+ph+"\\')" class=btn-gold style="width:100%;padding:12px;margin-top:8px">💾 حفظ</button>';
}}
window.saveUser=function(oldPh){{
  let ff=document.getElementById('edit_u_field').value.trim();
  let pw=document.getElementById('edit_u_pass').value;
  if(!ff){{alert('required');return;}}
  let data={{old_phone:oldPh,phone:ff,username:ff,role:document.getElementById('user-'+oldPh).dataset.role}};
  if(pw.trim()!='') data.password=pw.trim();
  fetch('/edit_user',{{method:'POST',body:new URLSearchParams(data)}}).then(()=>{{closeEditModal(); loadPage('settings',true);}});
}}
</script></div>"""
    return "<div class=card>ok</div>"

def layout(c,v='home'):
    th=session.get('theme','dark')
    is_dark=(th=='dark')
    bg='#0a0e2a' if is_dark else '#f1f5f9'
    card_bg='#1e2433' if is_dark else '#ffffff'
    txt='#ffffff' if is_dark else '#0f172a'
    border='#ffffff15' if is_dark else '#e2e8f0'
    return f"""<html dir=rtl lang=ar><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1,maximum-scale=1'>
<link rel=stylesheet href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'>
<style>
*{{box-sizing:border-box;font-family:system-ui}}body{{margin:0;background:{bg};color:{txt};overflow-x:hidden;direction:rtl}}
.anim{{animation:fadeUp .22s ease both}}@keyframes fadeUp{{from{{opacity:0;transform:translateY(8px)}}to{{opacity:1;transform:none}}}}
.top{{position:fixed;top:0;left:0;right:0;height:60px;background:#111827ee;backdrop-filter:blur(12px);color:#fff;display:flex;align-items:center;justify-content:space-between;padding:0 12px;z-index:1003;border-bottom:1px solid #ffffff10}}
.sidebar{{position:fixed;right:0 !important;left:auto !important;top:0;direction:rtl;width:270px;height:100%;background:#111827f5;color:#fff;z-index:1002;padding-top:70px;transform:translateX(110%);transition:transform .26s cubic-bezier(.4,0,.2,1);overflow-y:auto}}
.sidebar.active{{transform:none}}
.sidebar a{{display:flex;align-items:center;gap:10px;padding:12px 16px;margin:6px 12px;color:#fff;text-decoration:none;border-radius:12px;background:#ffffff10;transition:all .2s}}
.sidebar a:hover{{background:#ffffff20;transform:translateX(-4px)}}
.sidebar a.active{{background:#ffbe4d;color:#111;font-weight:800}}
#overlay{{position:fixed;inset:0;background:#0008;z-index:1001;display:none}}#overlay.show{{display:block}}
.main{{margin-top:70px;padding:12px;min-height:90vh}}@media(max-width:700px){{.main{{padding:8px}}}}
.card{{background:{card_bg};color:{txt};padding:14px;border-radius:14px;margin-bottom:10px;border:1px solid {border};transition:all .18s}}
.card:hover{{transform:translateY(-1px);box-shadow:0 6px 18px #0002}}
input,select{{padding:11px;margin:5px 0;border-radius:10px;border:1px solid {border};width:100%;background:#ffffff08;color:{txt};transition:border .18s}}
input:focus{{border-color:#ffbe4d;outline:none}}
.btn-gold{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;padding:10px 16px;border:0;border-radius:10px;font-weight:800;cursor:pointer;transition:all .18s}}
.btn-gold:hover{{transform:translateY(-1px);box-shadow:0 4px 12px #ffbe4d44}}
.btn-gold:active{{transform:scale(.97)}}
.btn-del{{background:#ef4444;color:#fff;padding:9px 14px;border:0;border-radius:10px;cursor:pointer}}
#delModal, #editModal{{position:fixed;inset:0;background:#0009;backdrop-filter:blur(8px);display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:.25s;z-index:2000}}
#delModal.show, #editModal.show{{opacity:1;pointer-events:auto}}
#delBox, #editBox{{background:{card_bg};color:{txt};padding:24px;border-radius:18px;width:92%;max-width:440px;text-align:right;transform:scale(.92) translateY(15px);transition:.28s cubic-bezier(.4,0,.2,1)}}
#delModal.show #delBox, #editModal.show #editBox{{transform:scale(1) translateY(0)}}
</style></head>
<body>
<div id=overlay onclick="toggleSb(false)"></div>
<div class=sidebar id=sb>
<a href="javascript:loadPage('home')" id=nav-home>🏠 الرئيسية</a>
<a href="javascript:loadPage('dishes')" id=nav-dishes>📡 الصحون <span style='background:#ffbe4d;color:#111;padding:2px 6px;border-radius:6px;font-size:10px'>IP</span></a>
<a href="javascript:loadPage('towers')" id=nav-towers>🗼 الأبراج</a>
<a href="javascript:loadPage('subs')" id=nav-subs>👥 المشتركين</a>
<a href="javascript:loadPage('ledger')" id=nav-ledger>📒 الحسابات</a>
<a href="javascript:loadPage('logs')" id=nav-logs>📜 السجل - الاشعارات</a>
<a href="javascript:toggleNotif();toggleSb(false)" id=nav-notif>🔔 الاشعارات <span id=menuNotifCount style='background:#ef4444;color:#fff;padding:2px 6px;border-radius:10px;font-size:10px;display:none'>0</span></a>
<a href="javascript:loadPage('dishes');setTimeout(()=>{{if(window.pingAll) pingAll();}},600)" id=nav-ping>📶 بنج Ping الكل</a>
<a href="javascript:loadPage('map')" id=nav-map>🗺 الخريطة - قياس مسافة</a>
<a href="javascript:loadPage('support')" id=nav-support>🛠 الدعم</a>
<a href="javascript:loadPage('settings')" id=nav-settings>⚙ الإعدادات</a>
<a href="javascript:logoutFast()" id=nav-logout>🚪 خروج فوري</a>
</div>
<div class=top>
<div style='display:flex;gap:8px;align-items:center'>
<span onclick="toggleSb()" style='font-size:24px;cursor:pointer'>☰</span>
<input id=topsearch placeholder='🔍 بحث شامل' oninput="globalSearchTop(this.value)" style='background:#1f2937;border:1px solid #374151;color:#fff;padding:7px 10px;border-radius:10px;width:130px'>
</div>
<div style='font-weight:900'>OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<div style='display:flex;gap:6px;align-items:center'>
<div id=notifBell onclick="toggleNotif()" style='position:relative;cursor:pointer;font-size:20px'>🔔<span id=notifCount style='display:none;position:absolute;top:-6px;right:-6px;background:#ef4444;color:#fff;font-size:10px;width:18px;height:18px;border-radius:50%;display:flex;align-items:center;justify-content:center'>0</span></div>
<button onclick="toggleLang()" id=langBtn style='background:#1f2937;color:#fff;border:0;padding:8px 10px;border-radius:10px;cursor:pointer'>🌐 ع</button>
<button onclick="toggleTheme()" style='background:#1f2937;color:#fff;border:0;padding:8px 10px;border-radius:10px;cursor:pointer'>🌓</button>
<button onclick="loadPage(cur,true)" style='background:#1f2937;color:#fff;border:0;padding:8px 10px;border-radius:10px;cursor:pointer'>↻</button>
</div>
</div>
<div id=searchResults style='position:fixed;top:60px;right:10px;left:10px;max-width:500px;margin:0 auto;background:{card_bg};border:1px solid {border};border-radius:12px;z-index:1500;display:none;max-height:60vh;overflow:auto'></div>
<div id=notifPanel style='position:fixed;top:60px;left:10px;max-width:360px;background:{card_bg};border:1px solid {border};border-radius:14px;z-index:2000;display:none;max-height:70vh;overflow:auto'></div>
<div class=main id=mn>{c}</div>
<div id=delModal><div id=delBox><div style='font-size:44px;text-align:center'>🗑</div><h3 style='text-align:center'>تأكيد الحذف؟</h3><p style='color:#aaa;font-size:13px;text-align:center'>لا يمكن التراجع</p><div style='display:flex;gap:10px;margin-top:12px'><button onclick="closeDel()" style='flex:1;padding:12px;border-radius:12px;border:1px solid {border};background:transparent;color:{txt};cursor:pointer'>تراجع</button><button id=delYes style='flex:1;padding:12px;border-radius:12px;background:#ef4444;color:#fff;border:0;cursor:pointer;font-weight:800'>حذف</button></div></div></div>
<div id=editModal><div id=editBox><div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:14px'><h3 id=editTitle style='margin:0'>✏ تعديل</h3><button onclick="closeEditModal()" style='background:#ffffff15;border:0;color:{txt};width:32px;height:32px;border-radius:50%;cursor:pointer'>✕</button></div><div id=editBody></div></div></div>
<script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>
<script>
let cur='{v}';
let pageCache=JSON.parse(localStorage.getItem('omaia_cache')||'{{}}');
let lang=localStorage.getItem('omaia_lang')||'ar';
const T={{
  ar:{{subs:'المشتركين',dishes:'الصحون',towers:'الأبراج',ledger:'الحسابات',home:'الرئيسية'}},
  en:{{subs:'Subscribers',dishes:'Dishes',towers:'Towers',ledger:'Accounts',home:'Home'}}
}};
function saveCache(){{try{{localStorage.setItem('omaia_cache',JSON.stringify(pageCache))}}catch(e){{}}}}
function applyLang(){{
  document.getElementById('langBtn').textContent=lang==='ar'?'🌐 ع':'🌐 En';
  document.documentElement.dir='rtl';
  localStorage.setItem('omaia_lang',lang);
}}
window.toggleLang=function(){{
  lang=lang==='ar'?'en':'ar';
  localStorage.setItem('omaia_lang',lang);
  applyLang();
  pageCache={{}};
  saveCache();
  fetch('/toggle_lang').then(()=>{{ loadPage(cur,true); }});
}}
applyLang();
function toggleSb(force){{
  let sb=document.getElementById('sb'),ov=document.getElementById('overlay');
  let open=force!==undefined?force:!sb.classList.contains('active');
  sb.classList.toggle('active',open);
  ov.classList.toggle('show',open);
}}
async function loadPage(v,force=false,push=true){{
  if(push && cur!==v){{ history.pushState({{page:v}}, '', '/dash?v='+v); }}
  cur=v;
  localStorage.setItem('omaia_last_page',v);
  toggleSb(false);
  document.querySelectorAll('.sidebar a').forEach(a=>a.classList.remove('active'));
  let nav=document.getElementById('nav-'+v);
  if(nav)nav.classList.add('active');
  let mn=document.getElementById('mn');
  if(pageCache[v] && !force){{
    mn.innerHTML=pageCache[v];
    bind();execScripts();
    fetch('/api/page?v='+v).then(r=>r.text()).then(h=>{{pageCache[v]=h;saveCache();}});
    return;
  }}
  try{{
    let r=await fetch('/api/page?v='+v,{{cache:'no-store'}});
    let h=await r.text();
    pageCache[v]=h;saveCache();
    mn.innerHTML=h;
    bind();execScripts();
  }}catch(e){{
    mn.innerHTML='<div class=card>❌ خطأ: '+e+'</div>';
  }}
}}
function execScripts(){{
  document.getElementById('mn').querySelectorAll('script').forEach(s=>{{try{{(0,eval)(s.textContent)}}catch(e){{console.error(e)}}}});
}}
function bind(){{
  document.querySelectorAll('form[data-ajax]').forEach(f=>{{
    f.onsubmit=async e=>{{
      e.preventDefault();
      let btn=f.querySelector('button');
      let old=btn?btn.textContent:'';
      if(btn){{btn.textContent='⏳...'; btn.disabled=true;}}
      try{{
        let r=await fetch(f.action,{{method:'POST',body:new FormData(f)}});
        let txt=await r.text();
        if(r.ok){{
          delete pageCache[cur];
          await loadPage(cur,true);
        }}else{{
          alert(txt);
          if(btn){{btn.textContent=old; btn.disabled=false;}}
        }}
      }}catch(err){{
        alert(err);
        if(btn){{btn.textContent=old; btn.disabled=false;}}
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
    await fetch(window._delUrl);
    delete pageCache[cur];
    closeDel();
    loadPage(cur,true);
  }}
}};
async function toggleTheme(){{
  try{{ await fetch('/toggle_theme'); location.reload(); }}catch(e){{location.reload();}}
}}
window.globalSearchTop=async function(q){{
  let box=document.getElementById('searchResults');
  if(!q){{ box.style.display='none'; return; }}
  try{{
    let r=await fetch('/api/search?q='+encodeURIComponent(q));
    let d=await r.json();
    if(d.length==0){{ box.innerHTML='<div style="padding:12px;text-align:center;color:#aaa">لا يوجد نتائج</div>'; box.style.display='block'; return; }}
    let h='<div style="padding:8px;background:#ffffff08;font-weight:800;border-bottom:1px solid #ffffff15">🔍 نتائج ('+d.length+')</div>';
    d.forEach(x=>{{
      h+='<div style="padding:10px;border-bottom:1px solid #ffffff10;cursor:pointer;display:flex;justify-content:space-between" onclick="loadPage(\\''+x.page+'\\'); document.getElementById(\\'searchResults\\').style.display=\\'none\\';"><div><b>'+x.title+'</b><br><small style=color:#aaa>'+x.type+' - '+x.sub+'</small></div><small style=color:#ffbe4d>↗</small></div>';
    }});
    box.innerHTML=h;
    box.style.display='block';
  }}catch(e){{ box.style.display='none'; }}
}}
window.toggleNotif=async function(){{
  let panel=document.getElementById('notifPanel');
  panel.style.display=panel.style.display==='block'?'none':'block';
  if(panel.style.display==='block'){{
    try{{
      let r=await fetch('/api/notifications');
      let j=await r.json();
      let h='<div style="padding:12px"><div style="display:flex;justify-content:space-between;margin-bottom:8px"><b>🔔 الاشعارات ('+j.unread+')</b><button onclick="readAllNotif()" style="font-size:11px;padding:4px 8px;background:#ffbe4d;border:0;border-radius:6px;cursor:pointer">مقروء</button></div>';
      if(j.rows.length==0){{ h+='<div style="padding:20px;text-align:center;color:#aaa">لا يوجد</div>'; }}
      j.rows.forEach(n=>{{
        h+='<div style="padding:10px;border-bottom:1px solid #ffffff10;background:'+(n.read==0?'#ffffff08':'transparent')+'"><b style="color:#ffbe4d">'+n.title+'</b><br><small>'+n.msg+'</small><br><small style="color:#aaa">'+n.time+'</small></div>';
      }});
      h+='</div>';
      panel.innerHTML=h;
    }}catch(e){{ panel.innerHTML='<div style="padding:12px">خطأ</div>'; }}
  }}
}}
window.readAllNotif=async function(){{
  try{{ await fetch('/api/notifications/read',{{method:'POST'}}); }}catch(e){{}}
  document.getElementById('notifCount').style.display='none';
  document.getElementById('notifPanel').style.display='none';
  loadNotif();
}}
async function loadNotif(){{
  try{{
    let r=await fetch('/api/notifications');
    let j=await r.json();
    let c=document.getElementById('notifCount');
    let mc=document.getElementById('menuNotifCount');
    if(j.unread>0){{
      c.textContent=j.unread>99?'99+':j.unread; c.style.display='flex';
      if(mc){{ mc.textContent=j.unread>99?'99+':j.unread; mc.style.display='inline-block'; }}
    }} else {{
      c.style.display='none';
      if(mc) mc.style.display='none';
    }}
  }}catch(e){{}}
}}
loadNotif();
setInterval(loadNotif, 8000);
window.logoutFast=async function(){{
  try{{ await fetch('/api/logout',{{method:'POST'}}); }}catch(e){{}}
  localStorage.removeItem('omaia_last_page');
  location.replace('/login');
}};
window.globalSearchTop=async function(q){{
  let box=document.getElementById('searchResults');
  if(!q){{ box.style.display='none'; return; }}
  try{{
    let r=await fetch('/api/search?q='+encodeURIComponent(q));
    let d=await r.json();
    if(d.length==0){{ box.innerHTML='<div style="padding:12px;text-align:center;color:#aaa">🔍 لا يوجد نتائج لـ: '+q+'</div>'; box.style.display='block'; return; }}
    let h='<div style="padding:8px;background:#ffffff08;font-weight:800;border-bottom:1px solid #ffffff15">🔍 نتائج البحث ('+d.length+')</div>';
    d.forEach(x=>{{
      h+='<div style="padding:10px;border-bottom:1px solid #ffffff10;cursor:pointer;display:flex;justify-content:space-between;align-items:center" onclick="loadPage(\''+x.page+'\'); document.getElementById(\'searchResults\').style.display=\'none\'; document.getElementById(\'topsearch\').value=\'\';"><div><b>'+x.title+'</b><br><small style=color:#aaa>'+x.type+' - '+x.sub+'</small></div><small style=color:#ffbe4d>↗ '+x.page+'</small></div>';
    }});
    box.innerHTML=h;
    box.style.display='block';
  }}catch(e){{ box.style.display='none'; }}
}};

let lastPage=localStorage.getItem('omaia_last_page');
if(lastPage && lastPage!==cur && cur==='home'){{ loadPage(lastPage); }}
window.addEventListener('popstate', (e)=>{{ let v='home'; if(e.state && e.state.page){{ v=e.state.page; }} else {{ let p=new URLSearchParams(window.location.search); v=p.get('v')||'home'; }} loadPage(v,true,false); }});
bind();
execScripts();
if(!history.state){{ history.replaceState({{page:cur}}, '', '/dash?v='+cur); }}
</script>
</body></html>"""

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
