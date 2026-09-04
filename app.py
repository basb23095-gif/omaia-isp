from flask import Flask, request, redirect, render_template_string, session, Response
import os, datetime, io, csv, time
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
        try:cur.execute("ALTER TABLE dish_ips ADD COLUMN IF NOT EXISTS site TEXT")
        except:pass
        try:cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS username TEXT")
        except:pass
        cur.execute("SELECT * FROM users WHERE phone='0900000000'")
        if not cur.fetchone():cur.execute("INSERT INTO users(phone,password,role,active) VALUES('0900000000','admin123','super',1)")
        con.commit();cur.close();return
    con.execute("CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,active INT DEFAULT 1)")
    con.execute("CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,speed TEXT,status TEXT,server_id INT,dish_ip TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS accounts(sub_id INTEGER PRIMARY KEY,usd REAL DEFAULT 0,syr REAL DEFAULT 0)")
    con.execute("CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,sub_id INT,date TEXT,usd REAL,syr REAL,note TEXT,by_user TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS servers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,host TEXT,username TEXT,password TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT UNIQUE,location TEXT,sub_id INT)")
    try:con.execute("ALTER TABLE dish_ips ADD COLUMN site TEXT")
    except:pass
    try:con.execute("ALTER TABLE users ADD COLUMN username TEXT")
    except:pass
    if not con.execute("SELECT * FROM users WHERE phone='0900000000'").fetchone():
        con.execute("INSERT INTO users VALUES('0900000000','admin123','super',1)")
    con.commit();close_con(con)
init()

def mk_action(host,user,pwd,action,ip):
    if not routeros_api: return
    try:
        pool=routeros_api.RouterOsApiPool(host,username=user,password=pwd,plaintext_login=True)
        api=pool.get_api();lst=api.get_resource('/ip/firewall/address-list')
        if action=='block':lst.add(list='Blocked',address=ip,comment='OMAIA')
        else:
            for e in lst.get(address=ip):lst.remove(id=e['id'])
        pool.disconnect()
    except:pass

def mk_online(s):
    if not routeros_api:return []
    try:
        pool=routeros_api.RouterOsApiPool(s['host'],username=s['username'],password=s['password'],plaintext_login=True,port=8728)
        api=pool.get_api();r=api.get_resource('/ppp/active').get();pool.disconnect();return r
    except:return []

# LAYOUT يستخدم رموز من ملف colors.py فقط - الالوان ما تغيرت
LAYOUT="""<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>OMAIA</title>
<style>
body{font-family:Arial;margin:0;min-height:100vh;background:__BG__;color:__TEXT__}
.topbar{position:fixed;top:0;right:0;left:0;height:56px;background:__SIDEBAR__;display:flex;align-items:center;justify-content:space-between;padding:0 12px;z-index:1002;border-bottom:1px solid #334155}
.topbar b{color:__MAIN__}
.menu-btn{background:__MAIN__;border:none;border-radius:8px;padding:8px 12px;font-size:18px;cursor:pointer;color:#000;width:auto}
.sidebar{width:250px;padding:15px;position:fixed;top:56px;bottom:0;right:0;overflow-y:auto;background:__SIDEBAR__;transform:translateX(105%);transition:0.3s;z-index:1003}
.sidebar.open{transform:translateX(0)}
.sidebar h2{color:__MAIN__;text-align:center}
.sidebar a{display:block;color:#fff;padding:10px;margin:6px 0;background:__CARD__;text-decoration:none;border-radius:8px}
.overlay{display:none;position:fixed;top:56px;left:0;right:0;bottom:0;background:rgba(0,0,0,0.55);z-index:1001}
.overlay.show{display:block}
.main{padding:76px 16px 20px 16px;max-width:1100px;margin:auto}
table{width:100%;border-collapse:collapse;font-size:14px;background:__CARD__;border-radius:10px;overflow:hidden}
th,td{padding:8px;border-bottom:1px solid #334155;text-align:center}
th{color:__MAIN__}
input,select{width:100%;padding:9px;margin:5px 0;border-radius:8px;box-sizing:border-box;background:#0f172a;border:1px solid #334155;color:#fff}
button{padding:10px;width:100%;border:none;border-radius:8px;font-weight:bold;cursor:pointer;background:__MAIN__;color:#000}
.card{padding:12px;border-radius:10px;margin:10px 0;border:1px solid #334155;background:__CARD__}
.form2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.wa-float{position:fixed;bottom:18px;left:18px;width:56px;height:56px;background:#25D366;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:30px;text-decoration:none;z-index:1004;box-shadow:0 4px 14px rgba(0,0,0,0.4)}
.footer{text-align:center;padding:18px;color:#94a3b8;font-size:13px;margin-top:20px}
.footer a{color:__MAIN__;text-decoration:none}
</style></head><body>
<div class="topbar"><button class="menu-btn" onclick="toggleSide()">☰</button><b>OMAIA</b><span>🔔</span></div>
<div class="overlay" id="ovl" onclick="toggleSide()"></div>
<div class="sidebar" id="sdb"><h2>OMAIA</h2>{% if sess %}<a href="/dash?view=subs">المشتركين</a><a href="/search">بحث</a><a href="/dash?view=add">إضافة</a><a href="/dash?view=ledger">دفتر الحسابات</a><a href="/dash?view=dishes">صحون</a><a href="/dash?view=servers">سيرفرات</a>{% if role=='super' %}<a href="/dash?view=settings">إعدادات</a>{% endif %}<a href="/logout">خروج</a>{% endif %}</div>
<div class="main" id="mainc">{{content|safe}}<div class="footer">تصميم م عبدو عباس<br><a href="https://wa.me/963900000000" target="_blank">تواصل دعم فني واتساب</a></div></div>
<a class="wa-float" href="https://wa.me/963900000000" target="_blank">💬</a>
<script>
function toggleSide(){var s=document.getElementById('sdb');var o=document.getElementById('ovl');s.classList.toggle('open');o.classList.toggle('show');}
document.getElementById('mainc').addEventListener('click',function(){var s=document.getElementById('sdb');if(s.classList.contains('open')){s.classList.remove('open');document.getElementById('ovl').classList.remove('show');}});
</script>
</body></html>"""

def render(c):
    col=get_colors()
    h=LAYOUT
    for k,v in col.items():
        h=h.replace("__"+k.upper()+"__",v)
    return render_template_string(h,content=c,sess=session.get('phone'),role=session.get('role'))

@app.route('/')
def idx():return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        con=db();u=ex(con,"SELECT * FROM users WHERE phone=? AND password=? AND active=1",(request.form['phone'],request.form['password'])).fetchone();close_con(con)
        if u:
            session['phone']=u['phone'] if isinstance(u,dict) else u[0]
            session['role']=u['role'] if isinstance(u,dict) else u[2]
            return redirect('/dash')
        return render("<p>دخول مرفوض</p><form method='post'><input name='phone'><input type='password' name='password'><button>دخول</button></form>")
    return render("<div><h3>دخول الشركة</h3><form method='post'><input name='phone' required placeholder='الهاتف'><input type='password' name='password' required placeholder='كلمة السر'><button>دخول</button></form></div>")

@app.route('/logout')
def logout():session.clear();return redirect('/login')

@app.route('/dash')
def dash():
    if not session.get('phone'):return redirect('/login')
    v=request.args.get('view','subs');con=db()
    if v=='settings' and session.get('role')=='super':
        try:ex(con,"ALTER TABLE users ADD COLUMN username TEXT")
        except:pass
        users=ex(con,"SELECT * FROM users ORDER BY phone").fetchall()
        def gd(u,k):
            try: return u[k] if isinstance(u,dict) else ""
            except: return ""
        # الاعدادات مجمعة بزاوية الصفحة
        utr="".join([f"<tr><td>{u['phone']}<br><small>{gd(u,'username')}</small></td><td>{gd(u,'password') or u['password'] if isinstance(u,dict) else u[2]}</td><td>{u['role']}</td><td>{'مفعل' if u['active'] else 'معطل'}</td><td><a href='/toggle_user?ph={u['phone']}'>تعطيل/تفعيل</a><br><a href='/del_user?ph={u['phone']}' style='color:#f87171'>حذف</a></td></tr>" for u in users])
        c=f"<div class='card' style='max-width:520px;margin-right:0;border:2px solid __MAIN__'><h4>الاعدادات - اليوزرات</h4><form method='post' action='/add_user'><div class='form2'><input name='phone' required placeholder='هاتف'><input name='username' placeholder='يوزر'><input name='password' required placeholder='باسورد'><select name='role'><option value='tech'>فني</option><option value='super'>super</option></select></div><button>إضافة</button></form><div style='overflow-x:auto'><table><tr><th>اليوزر / هاتف</th><th>الباسورد</th><th>الدور</th><th>الحالة</th><th>تحكم</th></tr>{utr}</table></div></div>"
        c+="<div class='card'><h4>اللغة</h4><a href='/lang/ar'>العربية</a> | <a href='/lang/en'>English</a></div>"
        c+="<div class='card'><h4>تواصل دعم فني</h4><a href='https://wa.me/963900000000' target='_blank'><button>واتساب الدعم الفني</button></a></div>"
        close_con(con);return render(c)
    if v=='subs':
        rows=ex(con,"SELECT s.*,a.usd FROM subs s LEFT JOIN accounts a ON a.sub_id=s.id").fetchall();close_con(con)
        tr="".join([f"<tr><td>{r['name']}</td><td>{r['phone']}</td><td>{r['status']}</td><td><a href='/toggle/{r['id']}'>فصل/وصل</a> | <a href='/del_sub/{r['id']}'>حذف</a></td></tr>" for r in rows])
        return render(f"<table><tr><th>الاسم</th><th>هاتف</th><th>حالة</th><th>تحكم</th></tr>{tr}</table>")
    if v=='dishes':
        rows=ex(con,"SELECT * FROM dish_ips").fetchall();close_con(con)
        tr="".join([f"<tr><td>{dict(r).get('location')}</td><td>{dict(r).get('site','-')}</td><td dir='ltr'>{dict(r).get('ip')}</td><td><a href='/edit_dish/{dict(r).get('id')}'>تعديل ip</a> | <a href='/del_dish/{dict(r).get('id')}' style='color:#f87171'>حذف</a></td></tr>" for r in rows])
        return render(f"<div class='card'><form method='post' action='/add_dish'><div class='form2'><input name='location' required placeholder='اسم الشبكة'><input name='site' placeholder='موقع البرج'><input name='ip' required placeholder='IP' dir='ltr'></div><button>إضافة</button></form></div><table><tr><th>شبكة</th><th>برج</th><th>IP</th><th>تحكم</th></tr>{tr}</table>")
    if v=='servers':
        rows=ex(con,"SELECT * FROM servers").fetchall();close_con(con)
        tr="".join([f"<tr><td>{r['name']}</td><td>{r['host']}</td><td><a href='/del_srv/{r['id']}'>حذف</a></td></tr>" for r in rows])
        return render(f"<div class='card'><form method='post' action='/add_srv'><div class='form2'><input name='name' required placeholder='اسم'><input name='host' required placeholder='host'><input name='username' required placeholder='يوزر'><input name='password' placeholder='باس'></div><button>إضافة</button></form></div><table>{tr}</table>")
    if v=='ledger':
        rows=ex(con,"SELECT l.*,s.name FROM ledger l LEFT JOIN subs s ON s.id=l.sub_id ORDER BY l.id DESC LIMIT 100").fetchall()
        subs=ex(con,"SELECT id,name FROM subs").fetchall();close_con(con)
        opts="".join([f"<option value='{s['id']}'>{s['name']}</option>" for s in subs])
        tr="".join([f"<tr><td>{r['date']}</td><td>{r['name']}</td><td>{r['usd']}</td><td>{r['syr']}</td><td>{r['note']}</td></tr>" for r in rows])
        return render(f"<div class='card'><form method='post' action='/charge'><div class='form2'><select name='sub_id'>{opts}</select><input name='amount' placeholder='مبلغ'><select name='currency'><option value='usd'>دولار</option><option value='syr'>سوري</option></select><input name='note' placeholder='ملاحظة'></div><button>حفظ</button></form></div><table><tr><th>تاريخ</th><th>مشترك</th><th>$</th><th>ل.س</th><th>ملاحظة</th></tr>{tr}</table>")
    if v=='add':
        srvs=ex(con,"SELECT * FROM servers").fetchall();dishes=ex(con,"SELECT * FROM dish_ips").fetchall();close_con(con)
        so="".join([f"<option value='{s['id']}'>{s['name']}</option>" for s in srvs])
        do="".join([f"<option value='{dict(d).get('ip')}'>{dict(d).get('location')}</option>" for d in dishes])
        return render(f"<form method='post' action='/add_sub'><div class='form2'><input name='name' required placeholder='الاسم'><input name='phone' required placeholder='الهاتف'><select name='dish_ip'><option value=''>صحن</option>{do}</select><select name='server_id'><option value=''>سيرفر</option>{so}</select><select name='status'><option>نشط</option><option>موقوف</option></select></div><button>حفظ</button></form>")
    close_con(con);return render("<h3>لوحة التحكم</h3>")

@app.route('/search')
def search():
    if not session.get('phone'):return redirect('/login')
    q=request.args.get('q','').strip();con=db();like=f"%{q}%"
    subs=ex(con,"SELECT * FROM subs WHERE name LIKE? OR phone LIKE?",(like,like)).fetchall() if q else ex(con,"SELECT * FROM subs LIMIT 50").fetchall()
    dishes=ex(con,"SELECT * FROM dish_ips").fetchall();close_con(con)
    tr1="".join([f"<tr><td>{dict(r).get('name')}</td><td>{dict(r).get('phone')}</td></tr>" for r in subs])
    tr2="".join([f"<tr><td>{dict(r).get('location')}</td><td>{dict(r).get('ip')}</td></tr>" for r in dishes])
    return render(f"<form method='get'><input name='q' value='{q}' placeholder='بحث'><button>بحث</button></form><h3>مشتركين</h3><table>{tr1}</table><h3>صحون</h3><table>{tr2}</table>")

@app.route('/add_sub',methods=['POST'])
def add_sub():
    con=db()
    cur=con.cursor();cur.execute("INSERT INTO subs(name,phone,status,server_id,dish_ip) VALUES(?,?,?,?,?)",(request.form['name'],request.form['phone'],request.form.get('status','نشط'),request.form.get('server_id') or None,request.form.get('dish_ip','')))
    sid=cur.lastrowid;cur.execute("INSERT OR IGNORE INTO accounts(sub_id) VALUES(?)",(sid,));con.commit();close_con(con);return redirect('/dash?view=subs')

@app.route('/charge',methods=['POST'])
def charge():
    sid=request.form['sub_id'];amt=float(request.form.get('amount') or 0);cur=request.form.get('currency','usd')
    usd=amt if cur=='usd' else 0;syr=amt if cur=='syr' else 0
    con=db();ex(con,"UPDATE accounts SET usd=usd+?,syr=syr+? WHERE sub_id=?",(usd,syr,sid))
    ex(con,"INSERT INTO ledger(sub_id,date,usd,syr,note,by_user) VALUES(?,?,?,?,?,?)",(sid,datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),usd,syr,request.form.get('note',''),session.get('phone')))
    con.commit();close_con(con);return redirect('/dash?view=ledger')

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
    r=ex(con,"SELECT * FROM dish_ips WHERE id=?",(i,)).fetchone();close_con(con)
    d=dict(r) if r else {}
    return render(f"<div class='card'><h4>تعديل IP</h4><form method='post'><input name='location' value='{d.get('location','')}' placeholder='اسم الشبكة'><input name='site' value='{d.get('site','')}' placeholder='موقع البرج'><input name='ip' value='{d.get('ip','')}' dir='ltr' placeholder='IP'><button>حفظ التعديل</button></form></div>")

@app.route('/del_dish/<int:i>')
def del_dish(i):con=db();ex(con,"DELETE FROM dish_ips WHERE id=?",(i,));con.commit();close_con(con);return redirect('/dash?view=dishes')

@app.route('/add_srv',methods=['POST'])
def add_srv():con=db();ex(con,"INSERT INTO servers(name,host,username,password) VALUES(?,?,?,?)",(request.form['name'],request.form['host'],request.form['username'],request.form.get('password','')));con.commit();close_con(con);return redirect('/dash?view=servers')

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
    if ph not in ('0900000000',):con=db();u=ex(con,"SELECT active FROM users WHERE phone=?",(ph,)).fetchone();ex(con,"UPDATE users SET active=? WHERE phone=?",(0 if u['active'] else 1,ph));con.commit();close_con(con)
    return redirect('/dash?view=settings')

@app.route('/del_user')
def del_user_q():
    if session.get('role')!='super':return redirect('/dash?view=settings')
    ph=request.args.get('ph','')
    if ph!='0900000000' and ph!=session.get('phone'):con=db();ex(con,"DELETE FROM users WHERE phone=?",(ph,));con.commit();close_con(con)
    return redirect('/dash?view=settings')

@app.route('/add_user',methods=['POST'])
def add_user():
    if session.get('role')!='super':return redirect('/dash?view=settings')
    con=db()
    try:ex(con,"INSERT INTO users(phone,username,password,role,active) VALUES(?,?,?,?,1)",(request.form.get('phone','').strip(),request.form.get('username','').strip(),request.form.get('password',''),request.form.get('role','tech')));con.commit()
    except:pass
    close_con(con);return redirect('/dash?view=settings')

@app.route('/edit_user/<ph>',methods=['POST'])
def edit_user(ph):
    if session.get('role')!='super':return redirect('/dash?view=settings')
    con=db();un=request.form.get('username','').strip();pw=request.form.get('password','').strip()
    if pw:ex(con,"UPDATE users SET username=?,password=? WHERE phone=?",(un,pw,ph))
    else:ex(con,"UPDATE users SET username=? WHERE phone=?",(un,ph))
    con.commit();close_con(con);return redirect('/dash?view=settings')

@app.route('/lang/<l>')
def set_lang(l):session['lang']=l;return redirect('/dash?view=settings')

@app.route('/export')
def export():
    con=db();rows=ex(con,"SELECT s.name,s.phone,s.status FROM subs s").fetchall();close_con(con)
    out=io.StringIO();w=csv.writer(out);w.writerow(['الاسم','الهاتف','الحالة'])
    for r in rows:w.writerow([r['name'],r['phone'],r['status']])
    return Response(out.getvalue().encode('utf-8-sig'),mimetype='text/csv',headers={'Content-Disposition':'attachment;filename=subs.csv'})

if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.environ.get('PORT',10000)))
