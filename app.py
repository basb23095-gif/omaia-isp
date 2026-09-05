from flask import Flask, request, redirect, render_template_string, session, Response
import os, datetime, io, csv, time
from functools import lru_cache
try: import routeros_api
except: routeros_api=None
try: import psycopg2, psycopg2.extras
except: psycopg2=None
import sqlite3
from colors import get_colors, save_colors_dict, reset_colors, DEFAULT_COLORS

app=Flask(__name__)
app.secret_key=os.environ.get("SECRET_KEY","omaia-sec")
DATABASE_URL=os.environ.get("DATABASE_URL","")
USE_PG=bool(DATABASE_URL and psycopg2)
_pg_conn=None;_pg_time=0
SUPPORT_WA=os.environ.get("SUPPORT_WA","905344851045")

@lru_cache(maxsize=1)
def get_colors_cached():
    return get_colors()

def db():
    global _pg_conn,_pg_time
    if USE_PG:
        now=time.time()
        if _pg_conn and now-_pg_time<300:
            try:_pg_conn.cursor().execute("SELECT 1");return _pg_conn
            except:pass
        try:_pg_conn.close()
        except:pass
        _pg_conn=psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=5)
        _pg_conn.autocommit=True;_pg_time=now;return _pg_conn
    con=sqlite3.connect("omaia_company.db");con.row_factory=sqlite3.Row;return con

def close_con(con):
    if not USE_PG:
        try:con.close()
        except:pass

def ex(con,q,args=()):
    if USE_PG:
        cur=con.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(q.replace("?","%s"),args);return cur
    return con.execute(q,args)

def get_count(con,table):
    try:
        r=ex(con,f"SELECT COUNT(*) c FROM {table}").fetchone()
        return r['c'] if isinstance(r,dict) else r[0]
    except: return 0

def init():
    con=db()
    if USE_PG:
        cur=con.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,active INT DEFAULT 1)")
        cur.execute("CREATE TABLE IF NOT EXISTS subs(id SERIAL PRIMARY KEY,name TEXT,phone TEXT,speed TEXT,status TEXT,server_id INT,dish_ip TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS accounts(sub_id INT PRIMARY KEY,usd FLOAT DEFAULT 0,syr FLOAT DEFAULT 0)")
        cur.execute("CREATE TABLE IF NOT EXISTS ledger(id SERIAL PRIMARY KEY,sub_id INT,date TEXT,usd FLOAT,syr FLOAT,note TEXT,by_user TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS servers(id SERIAL PRIMARY KEY,name TEXT,host TEXT,username TEXT,password TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS dish_ips(id SERIAL PRIMARY KEY,ip TEXT UNIQUE,location TEXT,sub_id INT)")
        cur.execute("CREATE TABLE IF NOT EXISTS notifications(id SERIAL PRIMARY KEY,msg TEXT,date TEXT,by_user TEXT)")
        for s in ["ALTER TABLE dish_ips ADD COLUMN IF NOT EXISTS site TEXT","ALTER TABLE users ADD COLUMN IF NOT EXISTS username TEXT","ALTER TABLE servers ADD COLUMN IF NOT EXISTS sstp_host TEXT","ALTER TABLE servers ADD COLUMN IF NOT EXISTS sstp_user TEXT","ALTER TABLE servers ADD COLUMN IF NOT EXISTS sstp_pass TEXT","ALTER TABLE servers ADD COLUMN IF NOT EXISTS conn_type TEXT DEFAULT 'api'"]:
            try:cur.execute(s)
            except:pass
        for s in ["CREATE INDEX IF NOT EXISTS idx_subs_name ON subs(name)","CREATE INDEX IF NOT EXISTS idx_ledger_sub ON ledger(sub_id)"]:
            try:cur.execute(s)
            except:pass
        cur.execute("SELECT * FROM users WHERE phone='05344851045'")
        if not cur.fetchone():cur.execute("INSERT INTO users(phone,password,role,active) VALUES('05344851045','admin2024','super',1)")
        con.commit();cur.close();return
    con.execute("CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,active INT DEFAULT 1)")
    con.execute("CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,speed TEXT,status TEXT,server_id INT,dish_ip TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS accounts(sub_id INTEGER PRIMARY KEY,usd REAL DEFAULT 0,syr REAL DEFAULT 0)")
    con.execute("CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,sub_id INT,date TEXT,usd REAL,syr REAL,note TEXT,by_user TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS servers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,host TEXT,username TEXT,password TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT UNIQUE,location TEXT,sub_id INT)")
    con.execute("CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,msg TEXT,date TEXT,by_user TEXT)")
    for s in ["ALTER TABLE dish_ips ADD COLUMN site TEXT","ALTER TABLE users ADD COLUMN username TEXT","ALTER TABLE servers ADD COLUMN sstp_host TEXT","ALTER TABLE servers ADD COLUMN sstp_user TEXT","ALTER TABLE servers ADD COLUMN sstp_pass TEXT","ALTER TABLE servers ADD COLUMN conn_type TEXT DEFAULT 'api'","CREATE INDEX IF NOT EXISTS idx_subs_name ON subs(name)","CREATE INDEX IF NOT EXISTS idx_ledger_sub ON ledger(sub_id)"]:
        try:con.execute(s)
        except:pass
    try:con.execute("DELETE FROM users WHERE phone='0900000000'")
    except:pass
    if not con.execute("SELECT * FROM users WHERE phone='05344851045'").fetchone():
        con.execute("INSERT INTO users(phone,password,role,active) VALUES('05344851045','admin2024','super',1)")
    con.commit();close_con(con)
init()

def notif_count_reuse(con=None):
    try:
        own=False
        if con is None: con=db();own=True
        c=len(ex(con,"SELECT id FROM notifications ORDER BY id DESC LIMIT 5").fetchall())
        if own: close_con(con)
        return c
    except: return 0

LAYOUT="""<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>OMAIA ISP</title>
<style>
body{font-family:Arial;margin:0;min-height:100vh;background:__BG__;color:__TEXT__}
.topbar{position:fixed;top:0;right:0;left:0;height:56px;background:__SIDEBAR__;display:flex;align-items:center;justify-content:space-between;padding:0 12px;z-index:1002;border-bottom:1px solid #334155}
.topbar b{color:__MAIN__}
.top-left{display:flex;gap:8px;align-items:center}
.icon-btn{background:__CARD__;border:1px solid #334155;border-radius:8px;padding:6px 10px;font-size:18px;cursor:pointer;color:#fff;text-decoration:none}
.menu-btn{background:__MAIN__;border:none;border-radius:8px;padding:8px 12px;font-size:18px;cursor:pointer;color:#000;width:auto}
.sidebar{width:250px;padding:15px;position:fixed;top:56px;bottom:0;right:0;overflow-y:auto;background:__SIDEBAR__;transform:translateX(105%);transition:0.3s;z-index:1003}
.sidebar.open{transform:translateX(0)}
.sidebar h2{color:__MAIN__;text-align:center}
.sidebar a{display:block;color:#fff;padding:10px;margin:6px 0;background:__CARD__;text-decoration:none;border-radius:8px}
.overlay{display:none;position:fixed;top:56px;left:0;right:0;bottom:0;background:rgba(0,0,0,0.55);z-index:1001}
.overlay.show{display:block}
.main{padding:76px 16px 20px 16px;max-width:1100px;margin:auto}
.login-wrap{display:flex;align-items:center;justify-content:center;min-height:80vh}
.login-box{width:340px;max-width:92%;text-align:center;padding:22px;border-radius:14px;background:__CARD__;border:1px solid #334155}
.login-box h2{color:__MAIN__;margin:5px 0}
table{width:100%;border-collapse:collapse;font-size:14px;background:__CARD__;border-radius:10px;overflow:hidden}
th,td{padding:8px;border-bottom:1px solid #334155;text-align:center}
th{color:__MAIN__}
input,select{width:100%;padding:9px;margin:5px 0;border-radius:8px;box-sizing:border-box;background:#0f172a;border:1px solid #334155;color:#fff}
button{padding:10px;width:100%;border:none;border-radius:8px;font-weight:bold;cursor:pointer;background:__MAIN__;color:#000}
.card{padding:12px;border-radius:10px;margin:10px 0;border:1px solid #334155;background:__CARD__}
.form2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.wa-float{position:fixed;bottom:18px;left:18px;width:56px;height:56px;background:#25D366;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:30px;text-decoration:none;z-index:1004}
.footer{text-align:center;padding:18px;color:#94a3b8;font-size:13px;margin-top:20px}
.footer a{color:__MAIN__;text-decoration:none}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
@media(max-width:700px){.stats{grid-template-columns:1fr 1fr}}
</style></head><body>
<div class="topbar"><button class="menu-btn" onclick="toggleSide()">☰</button><b>OMAIA ISP</b><div class="top-left"><a class="icon-btn" href="/search">🔍</a><a class="icon-btn" href="/dash?view=notifs">🔔<span id="nc">__NOTIF__</span></a></div></div>
<div class="overlay" id="ovl" onclick="toggleSide()"></div>
<div class="sidebar" id="sdb"><h2>OMAIA ISP</h2>{% if sess %}<a href="/dash?view=home">🏠 الرئيسية</a><a href="/dash?view=subs">المشتركين</a><a href="/search">🔍 بحث</a><a href="/dash?view=add">إضافة</a><a href="/dash?view=ledger">دفتر الحسابات</a><a href="/dash?view=dishes">صحون</a><a href="/dash?view=servers">سيرفرات</a><a href="/dash?view=notifs">🔔 الإشعارات</a>{% if role=='super' %}<a href="/dash?view=settings">إعدادات</a>{% endif %}<a href="/logout">خروج</a>{% endif %}</div>
<div class="main" id="mainc">{{content|safe}}<div class="footer">تصميم م عبدو عباس<br><a href="https://wa.me/905344851045" target="_blank">تواصل دعم فني واتساب</a></div></div>
<a class="wa-float" href="https://wa.me/905344851045" target="_blank">💬</a>
<script>
function toggleSide(){var s=document.getElementById('sdb');var o=document.getElementById('ovl');s.classList.toggle('open');o.classList.toggle('show');}
document.getElementById('mainc').addEventListener('click',function(){var s=document.getElementById('sdb');if(s.classList.contains('open')){s.classList.remove('open');document.getElementById('ovl').classList.remove('show');}});
if("Notification" in window && Notification.permission=="default"){Notification.requestPermission();}
</script>
</body></html>"""

def render(c, con=None):
    col=get_colors_cached()
    h=LAYOUT
    for k,v in col.items(): h=h.replace("__"+k.upper()+"__",v)
    h=h.replace("__NOTIF__",str(notif_count_reuse(con)))
    return render_template_string(h,content=c,sess=session.get('phone'),role=session.get('role'))

@app.route('/')
def idx():return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login',methods=['GET','POST'])
def login():
    msg=""
    if request.method=='POST':
        ident=request.form.get('phone','').strip()
        pwd=request.form.get('password','')
        con=db()
        u=ex(con,"SELECT * FROM users WHERE phone=? OR username=?",(ident,ident)).fetchone()
        close_con(con)
        is_phone=ident.replace('+','').replace(' ','').isdigit()
        if not u:
            msg="<p style='color:#f87171'>خطأ في رقم الهاتف او غير موجود</p>" if is_phone else "<p style='color:#f87171'>خطأ في اسم المستخدم او غير موجود</p>"
        else:
            d=dict(u) if not isinstance(u,dict) else u
            if not d.get('active'): msg="<p style='color:#f87171'>الحساب معطل</p>"
            elif d.get('password')!=pwd: msg="<p style='color:#f87171'>خطأ في كلمة السر</p>"
            else:
                session['phone']=d.get('phone');session['role']=d.get('role');session['username']=d.get('username')
                return redirect('/dash?view=home')
    h="<div class='login-wrap'><div class='login-box'><h2>OMAIA ISP</h2><p>دخول باسم المستخدم او الهاتف</p>"+msg+"<form method='post' id='lf'><input name='phone' id='iu' placeholder='اسم المستخدم / الهاتف' required><input name='password' id='ip' type='password' placeholder='كلمة السر' required><label><input type='checkbox' id='rm' style='width:auto'> حفظ كلمة السر</label><button>دخول</button></form></div></div><script>if(localStorage.rm=='1'){iu.value=localStorage.u||'';ip.value=localStorage.p||'';rm.checked=true}lf.onsubmit=()=>{if(rm.checked){localStorage.u=iu.value;localStorage.p=ip.value;localStorage.rm='1'}else{localStorage.clear()}}</script>"
    return render(h)

@app.route('/logout')
def logout():session.clear();return redirect('/login')

@app.route('/dash')
def dash():
    if not session.get('phone'):return redirect('/login')
    v=request.args.get('view','home');con=db()
    def done(html):
        r=render(html,con);close_con(con);return r
    if v=='home':
        n_sub=get_count(con,"subs");n_srv=get_count(con,"servers");n_dish=get_count(con,"dish_ips");n_led=get_count(con,"ledger")
        last_subs=ex(con,"SELECT * FROM subs ORDER BY id DESC LIMIT 5").fetchall()
        last_dish=ex(con,"SELECT * FROM dish_ips ORDER BY id DESC LIMIT 5").fetchall()
        tr_s="".join([f"<tr><td>{r['name']}</td><td>{r['phone']}</td><td>{r['status']}</td></tr>" for r in last_subs])
        tr_d="".join([f"<tr><td>{dict(r).get('location')}</td><td><a href='http://{dict(r).get('ip')}' target='_blank' style='color:#38bdf8' dir='ltr'>{dict(r).get('ip')}</a></td></tr>" for r in last_dish])
        return done(f"<div class='stats'><div class='card'><b>{n_sub}</b><br>مشترك</div><div class='card'><b>{n_srv}</b><br>سيرفر</div><div class='card'><b>{n_dish}</b><br>صحن</div><div class='card'><b>{n_led}</b><br>حركة محاسبية</div></div><div class='card'><h4>آخر المشتركين</h4><table><tr><th>الاسم</th><th>هاتف</th><th>حالة</th></tr>{tr_s}</table></div><div class='card'><h4>آخر الصحون</h4><table><tr><th>شبكة</th><th>IP</th></tr>{tr_d}</table></div>")
    if v=='notifs':
        rows=ex(con,"SELECT * FROM notifications ORDER BY id DESC LIMIT 30").fetchall()
        tr=""
        for r in rows:
            d=dict(r) if not isinstance(r,dict) else r
            ctrl=f"<br><a href='/edit_notif/{d['id']}'>تعديل</a> | <a href='/del_notif/{d['id']}' style='color:#f87171' onclick=\"return confirm('حذف؟')\">حذف</a>" if session.get('role')=='super' else ""
            tr+=f"<div class='card'><small>{d.get('date','')}</small><br>{d.get('msg','')}<br><small>بواسطة {d.get('by_user','')}</small>{ctrl}</div>"
        form="<div class='card'><h4>إرسال إشعار جديد</h4><form method='post' action='/add_notif'><input name='msg' required placeholder='نص الإشعار'><button>إرسال 🔔</button></form></div>" if session.get('role')=='super' else ""
        return done(form+"<h3>الاشعارات</h3>"+tr)
    if v=='settings' and session.get('role')=='super':
        users=ex(con,"SELECT * FROM users ORDER BY phone").fetchall()
        utr="".join([f"<tr><td dir='ltr'>{u['phone']}</td><td>{u['password'] if isinstance(u,dict) else u[1]}</td><td>{'مفعل' if u['active'] else 'معطل'}</td><td><a href='/toggle_user?ph={u['phone']}'>تعطيل/تفعيل</a><br><a href='/del_user?ph={u['phone']}' style='color:#f87171'>حذف</a></td></tr>" for u in users])
        c=f"<div class='card' style='max-width:560px'><h4>الاعدادات - اليوزرات</h4><form method='post' action='/add_user'><input name='ident' required placeholder='رقم الهاتف / اسم المستخدم'><input name='password' required placeholder='باسورد'><select name='role'><option value='tech'>فني</option><option value='super'>super</option></select><button>إضافة</button></form><table><tr><th>اليوزر</th><th>الباسورد</th><th>الحالة</th><th>تحكم</th></tr>{utr}</table></div>"
        c+=f"<div class='card'><h4>تواصل دعم فني</h4><a href='https://wa.me/{SUPPORT_WA}' target='_blank'><button>واتساب الدعم الفني {SUPPORT_WA}</button></a></div>"
        return done(c)
    if v=='subs':
        rows=ex(con,"SELECT * FROM subs").fetchall()
        tr="".join([f"<tr><td>{r['name']}</td><td dir='ltr'>{r['phone']}</td><td>{r['status']}</td><td><a href='https://wa.me/{str(r['phone']).replace('+','').replace(' ','')}' target='_blank' style='color:#25D366'>واتساب</a> | <a href='/toggle/{r['id']}'>فصل/وصل</a> | <a href='/del_sub/{r['id']}' style='color:#f87171'>حذف</a></td></tr>" for r in rows])
        return done(f"<table><tr><th>الاسم</th><th>هاتف</th><th>حالة</th><th>تحكم</th></tr>{tr}</table>")
    if v=='dishes':
        rows=ex(con,"SELECT * FROM dish_ips").fetchall()
        tr="".join([f"<tr><td>{dict(r).get('location')}</td><td>{dict(r).get('site','-')}</td><td><a href='http://{dict(r).get('ip')}' target='_blank' style='color:#38bdf8;font-weight:bold' dir='ltr'>{dict(r).get('ip')}</a></td><td><a href='/edit_dish/{dict(r).get('id')}'>تعديل ip</a> | <a href='/del_dish/{dict(r).get('id')}' style='color:#f87171'>حذف</a></td></tr>" for r in rows])
        return done(f"<div class='card'><form method='post' action='/add_dish'><div class='form2'><input name='location' required placeholder='اسم الشبكة'><input name='site' placeholder='موقع البرج'><input name='ip' required placeholder='IP' dir='ltr'></div><button>إضافة</button></form></div><table><tr><th>شبكة</th><th>برج</th><th>IP</th><th>تحكم</th></tr>{tr}</table>")
    if v=='servers':
        rows=ex(con,"SELECT * FROM servers").fetchall()
        def gs2(r,k):
            try:return r[k] if isinstance(r,dict) else dict(r).get(k,'')
            except:return ''
        tr="".join([f"<tr><td>{gs2(r,'name')}</td><td dir='ltr'>{gs2(r,'host')}</td><td>{gs2(r,'conn_type')}<br><small dir='ltr'>{gs2(r,'sstp_host')}</small></td><td><a href='/edit_srv/{gs2(r,'id')}'>تعديل</a> | <a href='/del_srv/{gs2(r,'id')}' style='color:#f87171'>حذف</a></td></tr>" for r in rows])
        return done(f"<div class='card'><form method='post' action='/add_srv'><div class='form2'><input name='name' required placeholder='اسم'><input name='host' required placeholder='host API' dir='ltr'><input name='username' required placeholder='يوزر API'><input name='password' placeholder='باس API'><input name='sstp_host' placeholder='SSTP Host' dir='ltr'><input name='sstp_user' placeholder='SSTP يوزر'><input name='sstp_pass' placeholder='SSTP باس'><select name='conn_type'><option value='api'>API</option><option value='sstp'>SSTP</option><option value='both'>الاثنين</option></select></div><button>إضافة سيرفر</button></form></div><table><tr><th>اسم</th><th>host</th><th>نوع الاتصال</th><th>تحكم</th></tr>{tr}</table>")
    if v=='ledger':
        rows=ex(con,"SELECT l.*,s.name FROM ledger l LEFT JOIN subs s ON s.id=l.sub_id ORDER BY l.id DESC LIMIT 100").fetchall()
        subs=ex(con,"SELECT id,name FROM subs").fetchall()
        tot_u=ex(con,"SELECT SUM(usd) s FROM ledger").fetchone()
        tot_s=ex(con,"SELECT SUM(syr) s FROM ledger").fetchone()
        def gs(r):
            try:return r['s'] or 0
            except:return 0
        opts="".join([f"<option value='{s['id']}'>{s['name']}</option>" for s in subs])
        tr="".join([f"<tr><td>{r['date']}</td><td>{r['name']}</td><td style='color:{'#4ade80' if (r['usd'] or 0)>=0 else '#f87171'}'>{r['usd']}</td><td style='color:{'#4ade80' if (r['syr'] or 0)>=0 else '#f87171'}'>{r['syr']}</td><td>{r['note']}</td><td><a href='/edit_ledger/{r['id']}'>تعديل</a> | <a href='/del_ledger/{r['id']}' style='color:#f87171'>حذف</a></td></tr>" for r in rows])
        return done(f"<div class='stats'><div class='card'><b>{gs(tot_u)}</b><br>مجموع $</div><div class='card'><b>{gs(tot_s)}</b><br>مجموع ل.س</div></div><div class='card'><form method='post' action='/charge'><div class='form2'><select name='sub_id'>{opts}</select><input name='amount' placeholder='مبلغ' type='number' step='0.01' required><select name='currency'><option value='usd'>دولار</option><option value='syr'>سوري</option></select><select name='entry_type'><option value='debit'>دائن (+)</option><option value='credit'>مدين (-)</option></select><input name='note' placeholder='ملاحظة'></div><button>حفظ القيد</button></form></div><table><tr><th>تاريخ</th><th>مشترك</th><th>$</th><th>ل.س</th><th>ملاحظة</th><th>تحكم</th></tr>{tr}</table>")
    if v=='add':
        srvs=ex(con,"SELECT * FROM servers").fetchall();dishes=ex(con,"SELECT * FROM dish_ips").fetchall()
        so="".join([f"<option value='{s['id']}'>{s['name']}</option>" for s in srvs])
        do="".join([f"<option value='{dict(d).get('ip')}'>{dict(d).get('location')}</option>" for d in dishes])
        return done(f"<form method='post' action='/add_sub'><div class='form2'><input name='name' required placeholder='الاسم'><input name='phone' required placeholder='الهاتف' dir='ltr'><select name='dish_ip'><option value=''>صحن</option>{do}</select><select name='server_id'><option value=''>سيرفر</option>{so}</select><select name='status'><option>نشط</option><option>موقوف</option></select></div><button>حفظ</button></form>")
    close_con(con);return redirect('/dash?view=home')

@app.route('/search')
def search():
    if not session.get('phone'):return redirect('/login')
    q=request.args.get('q','').strip();con=db();like=f"%{q}%"
    subs=ex(con,"SELECT * FROM subs WHERE name LIKE? OR phone LIKE?",(like,like)).fetchall() if q else ex(con,"SELECT * FROM subs LIMIT 50").fetchall()
    dishes=ex(con,"SELECT * FROM dish_ips").fetchall()
    tr1="".join([f"<tr><td>{dict(r).get('name')}</td><td dir='ltr'>{dict(r).get('phone')}</td><td><a href='https://wa.me/{str(dict(r).get('phone')).replace('+','')}' target='_blank'>واتساب</a></td></tr>" for r in subs])
    tr2="".join([f"<tr><td>{dict(r).get('location')}</td><td><a href='http://{dict(r).get('ip')}' target='_blank' dir='ltr'>{dict(r).get('ip')}</a></td></tr>" for r in dishes])
    r=render(f"<form method='get'><input name='q' value='{q}' placeholder='بحث عن مشترك...'><button>بحث 🔍</button></form><h3>مشتركين</h3><table>{tr1}</table><h3>صحون</h3><table>{tr2}</table>",con)
    close_con(con);return r

@app.route('/add_notif',methods=['POST'])
def add_notif():
    if session.get('role')!='super':return redirect('/dash?view=notifs')
    con=db();ex(con,"INSERT INTO notifications(msg,date,by_user) VALUES(?,?,?)",(request.form.get('msg',''),datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),session.get('phone')));con.commit();close_con(con)
    return redirect('/dash?view=notifs')

@app.route('/edit_notif/<int:i>',methods=['GET','POST'])
def edit_notif(i):
    if session.get('role')!='super':return redirect('/dash?view=notifs')
    con=db()
    if request.method=='POST':
        ex(con,"UPDATE notifications SET msg=? WHERE id=?",(request.form.get('msg',''),i));con.commit();close_con(con)
        return redirect('/dash?view=notifs')
    r=ex(con,"SELECT * FROM notifications WHERE id=?",(i,)).fetchone()
    d=dict(r) if r else {}
    h=render(f"<div class='card'><h4>تعديل إشعار</h4><form method='post'><input name='msg' value='{d.get('msg','')}' required><button>حفظ</button></form></div>",con)
    close_con(con);return h

@app.route('/del_notif/<int:i>')
def del_notif(i):
    if session.get('role')!='super':return redirect('/dash?view=notifs')
    con=db();ex(con,"DELETE FROM notifications WHERE id=?",(i,));con.commit();close_con(con)
    return redirect('/dash?view=notifs')

@app.route('/add_sub',methods=['POST'])
def add_sub():
    con=db()
    nm=request.form['name'].strip();ph=request.form['phone'].strip()
    dup=ex(con,"SELECT id FROM subs WHERE name=? OR phone=?",(nm,ph)).fetchone()
    if dup:
        r=render("<div class='card'><p style='color:#f87171'>الاسم او رقم الهاتف موجود مسبقاً</p><a href='/dash?view=add'>رجوع</a></div>",con);close_con(con);return r
    cur=con.cursor() if USE_PG else con
    if USE_PG:
        cur2=con.cursor();cur2.execute("INSERT INTO subs(name,phone,status,server_id,dish_ip) VALUES(%s,%s,%s,%s,%s) RETURNING id",(nm,ph,request.form.get('status','نشط'),request.form.get('server_id') or None,request.form.get('dish_ip','')));sid=cur2.fetchone()[0];cur2.close()
        try:ex(con,"INSERT INTO accounts(sub_id) VALUES(%s)",(sid,))
        except:pass
    else:
        cur.execute("INSERT INTO subs(name,phone,status,server_id,dish_ip) VALUES(?,?,?,?,?)",(nm,ph,request.form.get('status','نشط'),request.form.get('server_id') or None,request.form.get('dish_ip','')))
        sid=cur.lastrowid
        try:cur.execute("INSERT INTO accounts(sub_id) VALUES(?)",(sid,))
        except:pass
    con.commit();close_con(con);return redirect('/dash?view=subs')

@app.route('/charge',methods=['POST'])
def charge():
    sid=request.form['sub_id'];amt=float(request.form.get('amount') or 0);cur=request.form.get('currency','usd')
    etype=request.form.get('entry_type','debit');sign=1 if etype=='debit' else -1
    usd=amt*sign if cur=='usd' else 0;syr=amt*sign if cur=='syr' else 0
    con=db();ex(con,"UPDATE accounts SET usd=usd+?,syr=syr+? WHERE sub_id=?",(usd,syr,sid))
    ex(con,"INSERT INTO ledger(sub_id,date,usd,syr,note,by_user) VALUES(?,?,?,?,?,?)",(sid,datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),usd,syr,request.form.get('note','')+(" [دائن]" if sign>0 else " [مدين]"),session.get('phone')))
    con.commit();close_con(con);return redirect('/dash?view=ledger')

@app.route('/edit_ledger/<int:i>',methods=['GET','POST'])
def edit_ledger(i):
    if not session.get('phone'):return redirect('/login')
    con=db()
    if request.method=='POST':
        usd=float(request.form.get('usd') or 0);syr=float(request.form.get('syr') or 0)
        old=ex(con,"SELECT * FROM ledger WHERE id=?",(i,)).fetchone()
        if old:
            d=dict(old) if not isinstance(old,dict) else old
            diff_u=usd-(d.get('usd') or 0);diff_s=syr-(d.get('syr') or 0)
            ex(con,"UPDATE ledger SET usd=?,syr=?,note=? WHERE id=?",(usd,syr,request.form.get('note',''),i))
            ex(con,"UPDATE accounts SET usd=usd+?,syr=syr+? WHERE sub_id=?",(diff_u,diff_s,d.get('sub_id')))
            con.commit()
        close_con(con);return redirect('/dash?view=ledger')
    r0=ex(con,"SELECT * FROM ledger WHERE id=?",(i,)).fetchone()
    d=dict(r0) if r0 else {}
    r=render(f"<div class='card'><h4>تعديل قيد #{i}</h4><form method='post'><input name='usd' value='{d.get('usd',0)}' placeholder='دولار'><input name='syr' value='{d.get('syr',0)}' placeholder='سوري'><input name='note' value='{d.get('note','')}' placeholder='ملاحظة'><button>حفظ التعديل</button></form></div>",con)
    close_con(con);return r

@app.route('/del_ledger/<int:i>')
def del_ledger(i):
    con=db();old=ex(con,"SELECT * FROM ledger WHERE id=?",(i,)).fetchone()
    if old:
        d=dict(old) if not isinstance(old,dict) else old
        ex(con,"UPDATE accounts SET usd=usd-?,syr=syr-? WHERE sub_id=?",(d.get('usd') or 0,d.get('syr') or 0,d.get('sub_id')))
        ex(con,"DELETE FROM ledger WHERE id=?",(i,));con.commit()
    close_con(con);return redirect('/dash?view=ledger')

@app.route('/add_dish',methods=['POST'])
def add_dish():
    con=db()
    try:ex(con,"INSERT INTO dish_ips(ip,location,site) VALUES(?,?,?)",(request.form.get('ip','').strip(),request.form.get('location','').strip(),request.form.get('site','').strip()))
    except:
        try:ex(con,"UPDATE dish_ips SET location=?,site=? WHERE ip=?",(request.form.get('location','').strip(),request.form.get('site','').strip(),request.form.get('ip','').strip()))
        except:pass
    con.commit();close_con(con);return redirect('/dash?view=dishes')

@app.route('/edit_dish/<int:i>',methods=['GET','POST'])
def edit_dish(i):
    if not session.get('phone'):return redirect('/login')
    con=db()
    if request.method=='POST':
        ex(con,"UPDATE dish_ips SET ip=?,location=?,site=? WHERE id=?",(request.form.get('ip','').strip(),request.form.get('location','').strip(),request.form.get('site','').strip(),i))
        con.commit();close_con(con);return redirect('/dash?view=dishes')
    r0=ex(con,"SELECT * FROM dish_ips WHERE id=?",(i,)).fetchone()
    d=dict(r0) if r0 else {}
    r=render(f"<div class='card'><h4>تعديل IP</h4><form method='post'><input name='location' value='{d.get('location','')}'><input name='site' value='{d.get('site','')}'><input name='ip' value='{d.get('ip','')}' dir='ltr'><button>حفظ التعديل</button></form></div>",con)
    close_con(con);return r

@app.route('/del_dish/<int:i>')
def del_dish(i):con=db();ex(con,"DELETE FROM dish_ips WHERE id=?",(i,));con.commit();close_con(con);return redirect('/dash?view=dishes')

@app.route('/add_srv',methods=['POST'])
def add_srv():
    con=db()
    ex(con,"INSERT INTO servers(name,host,username,password,sstp_host,sstp_user,sstp_pass,conn_type) VALUES(?,?,?,?,?,?,?,?)",(request.form['name'],request.form['host'],request.form['username'],request.form.get('password',''),request.form.get('sstp_host',''),request.form.get('sstp_user',''),request.form.get('sstp_pass',''),request.form.get('conn_type','api')))
    con.commit();close_con(con);return redirect('/dash?view=servers')

@app.route('/edit_srv/<int:i>',methods=['GET','POST'])
def edit_srv(i):
    if not session.get('phone'):return redirect('/login')
    con=db()
    if request.method=='POST':
        ex(con,"UPDATE servers SET name=?,host=?,username=?,password=?,sstp_host=?,sstp_user=?,sstp_pass=?,conn_type=? WHERE id=?",(request.form['name'],request.form['host'],request.form['username'],request.form.get('password',''),request.form.get('sstp_host',''),request.form.get('sstp_user',''),request.form.get('sstp_pass',''),request.form.get('conn_type','api'),i))
        con.commit();close_con(con);return redirect('/dash?view=servers')
    r0=ex(con,"SELECT * FROM servers WHERE id=?",(i,)).fetchone()
    d=dict(r0) if r0 else {}
    def gv(k): return d.get(k,'') if isinstance(d,dict) else ''
    r=render(f"<div class='card'><h4>تعديل سيرفر - API + SSTP</h4><form method='post'><input name='name' value='{gv('name')}' placeholder='اسم'><input name='host' value='{gv('host')}' dir='ltr' placeholder='host API'><input name='username' value='{gv('username')}' placeholder='يوزر API'><input name='password' value='{gv('password')}' placeholder='باس API'><input name='sstp_host' value='{gv('sstp_host')}' dir='ltr' placeholder='SSTP Host'><input name='sstp_user' value='{gv('sstp_user')}' placeholder='SSTP يوزر'><input name='sstp_pass' value='{gv('sstp_pass')}' placeholder='SSTP باس'><select name='conn_type'><option value='api'>API</option><option value='sstp'>SSTP</option><option value='both'>الاثنين</option></select><button>حفظ</button></form></div>",con)
    close_con(con);return r

@app.route('/del_srv/<int:i>')
def del_srv(i):con=db();ex(con,"DELETE FROM servers WHERE id=?",(i,));con.commit();close_con(con);return redirect('/dash?view=servers')

@app.route('/toggle/<int:sid>')
def toggle(sid):
    con=db();s=ex(con,"SELECT * FROM subs WHERE id=?",(sid,)).fetchone()
    if s:
        new='موقوف' if s['status']=='نشط' else 'نشط'
        ex(con,"UPDATE subs SET status=? WHERE id=?",(new,sid));con.commit()
    close_con(con);return redirect('/dash?view=subs')

@app.route('/del_sub/<int:sid>')
def del_sub(sid):con=db();ex(con,"DELETE FROM subs WHERE id=?",(sid,));con.commit();close_con(con);return redirect('/dash?view=subs')

@app.route('/toggle_user')
def toggle_user():
    if session.get('role')!='super':return redirect('/dash?view=settings')
    ph=request.args.get('ph','')
    if ph!='05344851045' and ph!=session.get('phone'):
        con=db();u=ex(con,"SELECT active FROM users WHERE phone=?",(ph,)).fetchone()
        if u:
            av=u['active'] if isinstance(u,dict) else u[0]
            ex(con,"UPDATE users SET active=? WHERE phone=?",(0 if av else 1,ph));con.commit();close_con(con)
    return redirect('/dash?view=settings')

@app.route('/del_user')
def del_user_q():
    if session.get('role')!='super':return redirect('/dash?view=settings')
    ph=request.args.get('ph','')
    if ph!='05344851045' and ph!=session.get('phone'):
        con=db();ex(con,"DELETE FROM users WHERE phone=?",(ph,));con.commit();close_con(con)
    return redirect('/dash?view=settings')

@app.route('/add_user',methods=['POST'])
def add_user():
    if session.get('role')!='super':return redirect('/dash?view=settings')
    ident=(request.form.get('ident') or request.form.get('phone') or request.form.get('username') or '').strip()
    pwd=request.form.get('password','')
    role=request.form.get('role','tech')
    if not ident:
        return redirect('/dash?view=settings')
    con=db()
    dup=ex(con,"SELECT phone FROM users WHERE phone=? OR username=?",(ident,ident)).fetchone()
    if dup:
        r=render("<div class='card'><p style='color:#f87171'>رقم الهاتف او اسم المستخدم موجود مسبقاً</p><a href='/dash?view=settings'>رجوع</a></div>",con);close_con(con);return r
    try:ex(con,"INSERT INTO users(phone,username,password,role,active) VALUES(?,?,?,?,1)",(ident,ident,pwd,role));con.commit()
    except:pass
    close_con(con);return redirect('/dash?view=settings')

@app.route('/export')
def export():
    con=db();rows=ex(con,"SELECT name,phone,status FROM subs").fetchall();close_con(con)
    out=io.StringIO();w=csv.writer(out);w.writerow(['الاسم','الهاتف','الحالة'])
    for r in rows:w.writerow([r['name'],r['phone'],r['status']])
    return Response(out.getvalue().encode('utf-8-sig'),mimetype='text/csv',headers={'Content-Disposition':'attachment;filename=subs.csv'})

if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
