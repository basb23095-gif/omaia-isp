from flask import Flask, request, redirect, session, jsonify, render_template_string
import os, datetime, json, html, subprocess, platform, ipaddress
try:
    import psycopg2, psycopg2.extras
except: psycopg2=None
import sqlite3
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY","omia-sec-2026")
DATABASE_URL = os.environ.get("DATABASE_URL","").strip().replace("postgresql://","postgres://")
USE_PG = bool(DATABASE_URL.startswith("postgres://") and psycopg2)
_pg = None

# سجل النشاطات
ACTIVITY_LOG = []

def add_log(action):
    ACTIVITY_LOG.insert(0, {"time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "action": action})
    if len(ACTIVITY_LOG) > 50: ACTIVITY_LOG.pop()

def esc(s): return html.escape(str(s or ''), quote=True)
def db():
    global _pg
    if USE_PG:
        try:
            if _pg:
                cur=_pg.cursor();cur.execute("SELECT 1");cur.close();return _pg
        except:
            try:_pg.close()
            except:pass
            _pg=None
        _pg=psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=5);_pg.autocommit=True;return _pg
    c=sqlite3.connect("omia.db");c.row_factory=sqlite3.Row;return c
def cc(c):
    if not USE_PG:
        try:c.close()
        except:pass
def qall(q,a=()):
    c=db()
    try:
        if USE_PG:
            cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(q.replace("?","%s"),a);rs=[dict(r) for r in cur.fetchall()];cur.close();return rs
        else: rs=[dict(r) for r in c.execute(q,a).fetchall()];cc(c);return rs
    except Exception as e: print(e);cc(c);return []
def qone(q,a=()):
    r=qall(q,a);return r[0] if r else None
def qexec(q,a=()):
    c=db()
    try:
        if USE_PG: cur=c.cursor();cur.execute(q.replace("?","%s"),a);cur.close()
        else: c.execute(q,a);c.commit();cc(c)
    except Exception as e: print(e);cc(c)
def fnum(v):
    try:return float(v or 0)
    except:return 0
def init():
    ss=["CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,active INT DEFAULT 1)","CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,active INT DEFAULT 1)","CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,sub_id INT,amount REAL,typ TEXT,dt TEXT,note TEXT,currency TEXT DEFAULT 'SYP',name TEXT)","CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,lat REAL DEFAULT 0,lng REAL DEFAULT 0,dish_name TEXT,tower_name TEXT)","CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,lat REAL,lng REAL,location TEXT,fixed INT DEFAULT 0)"]
    if USE_PG: ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
    for s in ss: qexec(s)
    try: qexec("ALTER TABLE towers ADD COLUMN fixed INT DEFAULT 0")
    except: pass
    if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username,active) VALUES(?,?,?,?,?)",('05344851045','admin2024','manager','admin',1))
    # نقطة ثابتة افتراضية
    if not qone("SELECT * FROM towers WHERE fixed=1"):
        qexec("INSERT INTO towers(name,lat,lng,location,fixed) VALUES(?,?,?,?,1)",('برج الحصن الرئيسي',34.73,36.71,'حمص',1))
        add_log("تم اضافة نقطة ثابتة: برج الحصن الرئيسي")
init()
def me(): return qone("SELECT * FROM users WHERE phone=?",(session.get('phone'),))
def can_edit():
    m=me(); return not (m and m.get('role')=='tech')
def dark(): return session.get('theme','light')
def is_internal_ip(ip):
    try:
        ip_o = ipaddress.ip_address(ip.strip())
        return ip_o.is_private
    except: return False

TR = {
 'ar': {'home':'الرئيسية','ping':'بينغ','subs':'المشتركين','ledger':'دفتر الحسابات','dishes':'الصحون','towers':'الأبراج','map':'الخريطة','settings':'الإعدادات','logout':'خروج','notifications':'الإشعارات','support':'الدعم الفني','logs':'سجل النشاطات'},
 'en': {'home':'Home','ping':'Ping','subs':'Subscribers','ledger':'Ledger','dishes':'Dishes','towers':'Towers','map':'Map','settings':'Settings','logout':'Logout','notifications':'Notifications','support':'Support','logs':'Activity Log'}
}
def T(k):
    lang=session.get('lang','ar')
    return TR.get(lang,TR['ar']).get(k,k)

@app.route('/api/ping')
def api_ping():
    ip=request.args.get('ip','').strip()
    if not ip: return jsonify(ok=False,out='no ip')
    if not is_internal_ip(ip):
        return jsonify(ok=False,out='No Ping - خارج الشبكة / Outside network')
    try:
        w=platform.system().lower()=='windows'
        cmd=['ping','-n','2',ip] if w else ['ping','-c','2','-W','2',ip]
        o=subprocess.run(cmd,capture_output=True,text=True,timeout=8)
        return jsonify(ok=True,out=((o.stdout or '')+(o.stderr or ''))[:2000])
    except Exception as e: return jsonify(ok=False,out=str(e))

@app.route('/toggle_lang')
def tl(): session['lang']='en' if session.get('lang','ar')=='ar' else 'ar';return "ok"
@app.route('/toggle_theme_ajax')
def tt(): session['theme']='light' if dark()=='dark' else 'dark';return "ok"

def page_content(v):
    h=""; dis="" if can_edit() else "style='opacity:.35;pointer-events:none'"
    lang=session.get('lang','ar')

    if v=='home':
        ns=(qone("SELECT COUNT(*) c FROM subs") or {}).get('c',0);nd=(qone("SELECT COUNT(*) c FROM dish_ips") or {}).get('c',0);nt=(qone("SELECT COUNT(*) c FROM towers") or {}).get('c',0)
        h=f"""<div class=cards>
        <div class=card><h3>عدد الصحون</h3><h2>{nd}</h2></div>
        <div class=card><h3>عدد الأبراج</h3><h2>{nt}</h2></div>
        <div class=card><h3>عدد الحسابات</h3><h2>{ns}</h2></div>
        </div>"""
        h+='<div class=card><h3>Ping Test - الشبكة الداخلية فقط</h3><div style="display:flex;gap:6px"><input id=ping_ip placeholder="192.168.1.1"><button onclick="doPing()">بينغ</button></div><pre id=ping_out style="background:#000;color:#0f0;padding:8px;border-radius:8px;min-height:60px"></pre></div><script>async function doPing(){var i=document.getElementById("ping_ip").value;document.getElementById("ping_out").textContent="...";var r=await fetch("/api/ping?ip="+encodeURIComponent(i));var j=await r.json();document.getElementById("ping_out").textContent=j.out}</script>'
        return h

    if v=='subs':
        rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 100")
        h="<div class=card><h3>المشتركين</h3><form data-ajax method=post action=/add_sub><input name=name required placeholder='الاسم'><input name=phone placeholder='رقم الهاتف'><button>اضافة</button></form></div>"
        for r in rs: h+="<div class=card grid-2><span>"+esc(r['name'])+" - "+esc(r['phone'])+"</span><div><button class=btn>تعديل</button> <a href=/del_sub/"+str(r['id'])+" data-del "+dis+" class='btn btn-danger'>حذف</a></div></div>"
        return h

    if v=='dishes':
        rs=qall("SELECT * FROM dish_ips ORDER BY id DESC LIMIT 200")
        h="<div class=card><h3>الصحون</h3><form data-ajax method=post action=/add_dish><input name=dish_name required placeholder='اسم الطبق'><button>اضافة</button></form></div><div class=grid-2>"
        for r in rs:
            h+="<div class='card small'><b>"+esc(r.get('dish_name') or '')+"</b><br><button class=btn onclick='pingDish(\""+esc(r['ip'])+"\")'>بينغ</button> <a href=/del_dish/"+str(r['id'])+" data-del "+dis+" class='btn btn-danger'>حذف</a></div>"
        return h+"</div>"

    if v=='towers':
        rs=qall("SELECT * FROM towers ORDER BY id DESC LIMIT 100")
        h="<div class=card><h3>الأبراج</h3><form data-ajax method=post action=/add_tower><input name=name required placeholder='اسم البرج'><input name=location placeholder='الموقع'><input name=lat placeholder='خط العرض'><input name=lng placeholder='خط الطول'><button>اضافة</button></form></div>"
        for r in rs:
            fixed = "<span style='color:orange'>[نقطة ثابتة]</span>" if r.get('fixed') else ""
            delbtn = "" if r.get('fixed') else f"<a href=/del_tower/{r['id']} data-del {dis} class='btn btn-danger'>حذف</a>"
            h+=f"<div class=card><b>{esc(r['name'])}</b> {fixed}<br>{esc(r.get('location',''))} - {r.get('lat',0)},{r.get('lng',0)}<br><button class=btn>تعديل</button> {delbtn}</div>"
        return h

    if v=='map':
        h="<div class=card><h3>قياس المسافة</h3><div class=grid-2><input id=lat1 placeholder='خط العرض 1'><input id=lng1 placeholder='خط الطول 1'><input id=lat2 placeholder='خط العرض 2'><input id=lng2 placeholder='خط الطول 2'></div><button class=btn onclick='calcDist()'>احسب المسافة</button><p id=distResult style='font-weight:bold;color:#3b82f6'></p></div>"
        return h

    if v=='logs':
        h="<div class=card><h3>سجل النشاطات</h3>"
        for log in ACTIVITY_LOG: h+=f"<p>{log['time']} - {log['action']}</p>"
        return h+"</div>"

    if v=='settings':
        us=qall("SELECT phone,username FROM users ORDER BY phone");uh=""
        for u in us: ph=esc(u['phone']);un=esc(u.get('username') or u['phone']);uh+="<div class='card user-card'><div class=avatar>"+esc(un[:1])+"</div><div><b>"+un+"</b><br><small>"+ph+"</small></div></div>"
        h="<div class=card style='max-width:500px;margin:10px auto;text-align:center'><h3>الإعدادات</h3><form data-ajax method=post action=/change_pass><input name=newpass type=password required placeholder='كلمة السر الجديدة'><button>حفظ</button></form></div>"
        h+="<div class=card style='max-width:500px;margin:10px auto;text-align:center'><h3>اضافة مستخدم</h3><form data-ajax method=post action=/add_user><input name=phone required placeholder='رقم الهاتف'><input name=password type=password required placeholder='كلمة السر'><select name=role><option value=tech>فني</option><option value=manager>مدير</option></select><button>اضافة</button></form></div><div class=user-grid>"+uh+"</div>"
        h+="<div class=card style='text-align:center;border:2px solid #25D366;max-width:500px;margin:10px auto'><h3>الدعم الفني</h3><div dir=ltr>+905345851045</div><a href='https://wa.me/905345851045' target=_blank style='display:inline-block;background:#25D366;color:#fff;padding:8px 16px;border-radius:20px;text-decoration:none;margin:6px'>واتساب</a></div>"
        return h
    return "ok"

def layout(c,v='home'):
    th=dark();bg='#0f172a' if th=='dark' else '#f1f5f9';card='#1e293b' if th=='dark' else '#fff';txt='#fff' if th=='dark' else '#000'
    p=f"""<html dir=rtl lang=ar><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>لوحة تحكم OMAIA</title>
    <style>
    *{{margin:0;padding:0;box-sizing:border-box;font-family:'Cairo',sans-serif}}
    body{{background:{bg};color:{txt};overflow-x:hidden}}
   .loader{{position:fixed;top:0;left:0;width:100%;height:100%;background:{bg};z-index:9999;display:flex;align-items:center;justify-content:center;font-size:20px}}
   .sidebar{{position:fixed;right:-280px;top:0;width:280px;height:100%;background:{card};transition:0.3s;z-index:1000;padding-top:60px;box-shadow:-5px 0 15px rgba(0,0,0,0.3)}}
   .sidebar.active{{right:0}}
   .sidebar a{{display:block;padding:15px 20px;color:{txt};text-decoration:none;transition:0.2s}}
   .sidebar a:hover{{background:#334155}}
   .overlay{{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.5);display:none;z-index:999}}
   .overlay.active{{display:block}}
   .top{{position:fixed;top:0;left:0;right:0;background:{card};padding:15px;z-index:101;display:flex;align-items:center;justify-content:space-between}}
   .cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:15px;padding:20px;margin-top:60px}}
   .card{{background:{card};padding:20px;border-radius:12px;animation:slideUp 0.5s}}
    @keyframes slideUp{{from{{opacity:0;transform:translateY(20px)}}to{{opacity:1;transform:translateY(0)}}}}
   .grid-2{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
   .btn{{background:#3b82f6;border:none;color:#fff;padding:8px 15px;border-radius:6px;cursor:pointer;margin:3px}}
   .btn-danger{{background:#ef4444}}
    input,select{{width:100%;padding:8px;background:#334155;border:1px solid #475569;border-radius:6px;color:#fff;margin:5px 0}}
   .main{{padding:20px;margin-top:60px}}
    </style></head><body>
    <div class=loader id=loader>جاري التحميل...</div>
    <div class=overlay id=overlay onclick='toggleMenu()'></div>
    <div class=sidebar id=sidebar>
      <a href="javascript:loadPage('home')">⌂ {T('home')}</a>
      <a href="javascript:loadPage('subs')">◈ {T('subs')}</a>
      <a href="javascript:loadPage('dishes')">⬢ {T('dishes')}</a>
      <a href="javascript:loadPage('towers')">⬣ {T('towers')}</a>
      <a href="javascript:loadPage('map')">◎ قياس المسافة</a>
      <a href="javascript:loadPage('logs')">📜 {T('logs')}</a>
      <a href="javascript:loadPage('settings')">⚙ {T('settings')}</a>
      <a href=/logout>⎋ {T('logout')}</a>
    </div>
    <div class=top>
      <span style='font-size:24px;cursor:pointer' onclick='toggleMenu()'>☰</span>
      <span style='font-weight:800'>OMAIA ISP</span>
      <div><button class=btn onclick="fetch('/toggle_lang').then(()=>location.reload())">EN/AR</button></div>
    </div>
    <div class=main id=main>{c}</div>
    <script>
    function toggleMenu(){{document.getElementById('sidebar').classList.toggle('active');document.getElementById('overlay').classList.toggle('active')}}
    window.onload=()=>{{setTimeout(()=>{{document.getElementById('loader').style.display='none'}},800)}}
    window.loadPage=async function(v){{document.getElementById('loader').style.display='flex';var r=await fetch('/api/page?v='+v);document.getElementById('main').innerHTML=await r.text();document.getElementById('loader').style.display='none';bindAjax()}}
    function bindAjax(){{document.querySelectorAll('form[data-ajax]').forEach(f=>{{f.onsubmit=async e=>{{e.preventDefault();await fetch(f.action,{{method:'POST',body:new FormData(f)}});loadPage('home')}}}});document.querySelectorAll('a[data-del]').forEach(a=>{{a.onclick=async e=>{{e.preventDefault();if(confirm('تأكيد الحذف؟')){{await fetch(a.href);loadPage('home')}}}}}})}}
    function calcDist(){{let d1=parseFloat(lat1.value),d2=parseFloat(lat2.value),d3=parseFloat(lng1.value),d4=parseFloat(lng2.value);let dist=Math.sqrt((d2-d1)**2+(d4-d3)**2)*111;distResult.innerText="المسافة: "+dist.toFixed(2)+" كم"}}
    function pingDish(ip){{fetch('/api/ping?ip='+ip).then(r=>r.json()).then(j=>alert(j.out.slice(0,300)))}}
    bindAjax();
    </script></body></html>"""
    return p

@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')
@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        uin=request.form.get('userin','').strip();pw=request.form.get('password','');u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
        if u and u['password']==pw:
            session['phone']=u['phone'];add_log(f"تسجيل دخول: {u.get('username')}");return redirect('/dash')
    return """<html dir=rtl><head><meta charset=utf-8><style>body{background:#0f172a;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;font-family:sans-serif}.box{background:#1e293b;padding:30px;border-radius:15px;width:350px}</style></head><body><div class=box><h2 style='text-align:center'>تسجيل الدخول</h2><form method=post><input name=userin placeholder='اسم المستخدم' required><input name=password type=password placeholder='كلمة السر' required><button class=btn style='width:100%'>دخول</button></form></div></body></html>"""
@app.route('/logout')
def lo(): add_log("تسجيل خروج");session.clear();return redirect('/login')
@app.route('/dash')
def dash():
    if not session.get('phone'): return redirect('/login')
    return layout(page_content(request.args.get('v','home')),request.args.get('v','home'))
@app.route('/api/page')
def ap():
    if not session.get('phone'): return "login"
    return page_content(request.args.get('v','home'))
@app.route('/add_sub',methods=['POST'])
def a1(): name=request.form.get('name','');qexec("INSERT INTO subs(name,phone) VALUES(?,?)",(name,request.form.get('phone','')));add_log(f"اضافة مشترك: {name}");return "ok"
@app.route('/del_sub/<int:i>')
def a4(i):
    if not can_edit(): return "no"
    name=qone("SELECT name FROM subs WHERE id=?",(i,));qexec("DELETE FROM subs WHERE id=?",(i,));add_log(f"حذف مشترك: {name['name'] if name else ''}");return "ok"
@app.route('/add_dish',methods=['POST'])
def c1(): name=request.form.get('dish_name','');qexec("INSERT INTO dish_ips(dish_name) VALUES(?)",(name,));add_log(f"اضافة طبق: {name}");return "ok"
@app.route('/del_dish/<int:i>')
def c2(i):
    if not can_edit(): return "no"
    name=qone("SELECT dish_name FROM dish_ips WHERE id=?",(i,));qexec("DELETE FROM dish_ips WHERE id=?",(i,));add_log(f"حذف طبق: {name['dish_name'] if name else ''}");return "ok"
@app.route('/add_tower',methods=['POST'])
def d1(): name=request.form.get('name','');qexec("INSERT INTO towers(name,lat,lng,location) VALUES(?,?,?,?)",(name,fnum(request.form.get('lat')),fnum(request.form.get('lng')),request.form.get('location','')));add_log(f"اضافة برج: {name}");return "ok"
@app.route('/del_tower/<int:i>')
def d2(i):
    if not can_edit(): return "no"
    tower=qone("SELECT * FROM towers WHERE id=?",(i,));
    if tower and not tower.get('fixed'): qexec("DELETE FROM towers WHERE id=?",(i,));add_log(f"حذف برج: {tower['name']}");return "ok"
    return "no"
@app.route('/add_user',methods=['POST'])
def addu():
    if not can_edit(): return "no"
    f=request.form;ph=f.get('phone','').strip();qexec("INSERT INTO users(phone,password,role,username,active) VALUES(?,?,?,?,1)",(ph,f.get('password',''),f.get('role','tech'),ph));add_log(f"اضافة مستخدم: {ph}");return "ok"
@app.route('/change_pass',methods=['POST'])
def e2(): qexec("UPDATE users SET password=? WHERE phone=?",(request.form.get('newpass',''),session.get('phone')));add_log("تغيير كلمة السر");return "ok"
if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
