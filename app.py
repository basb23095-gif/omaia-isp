from flask import Flask, request, redirect, render_template_string, session, Response
import os, datetime, io, csv, json, time
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

_pg_conn=None
_pg_time=0
def db():
    global _pg_conn,_pg_time
    if USE_PG:
        now=time.time()
        if _pg_conn and now-_pg_time<300:
            try:
                _pg_conn.cursor().execute("SELECT 1")
                return _pg_conn
            except: pass
        try:
            if _pg_conn: _pg_conn.close()
        except: pass
        _pg_conn=psycopg2.connect(DATABASE_URL, sslmode='require', connect_timeout=5)
        _pg_conn.autocommit=True
        _pg_time=now
        return _pg_conn
    con=sqlite3.connect("omaia_company.db")
    con.row_factory=sqlite3.Row
    return con

def close_con(con):
    if not USE_PG:
        try: con.close()
        except: pass

def ex(con,q,args=()):
    if USE_PG:
        cur=con.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(q.replace("?","%s"), args)
        return cur
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
        # عمود موقع البرج - ما يضيع القديم
        try: cur.execute("ALTER TABLE dish_ips ADD COLUMN IF NOT EXISTS site TEXT")
        except: pass
        cur.execute("CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY,v TEXT)")
        cur.execute("SELECT * FROM users WHERE phone='0900000000'")
        if not cur.fetchone():
            cur.execute("INSERT INTO users(phone,password,role,active) VALUES('0900000000','admin123','super',1)")
        con.commit();cur.close();return
    con.execute("CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,active INT DEFAULT 1)")
    con.execute("CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,speed TEXT,status TEXT,server_id INT,dish_ip TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS accounts(sub_id INTEGER PRIMARY KEY,usd REAL DEFAULT 0,syr REAL DEFAULT 0)")
    con.execute("CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,sub_id INT,date TEXT,usd REAL,syr REAL,note TEXT,by_user TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS servers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,host TEXT,username TEXT,password TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT UNIQUE,location TEXT,sub_id INT)")
    try: con.execute("ALTER TABLE dish_ips ADD COLUMN site TEXT")
    except: pass
    con.execute("CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY,v TEXT)")
    if not con.execute("SELECT * FROM users WHERE phone='0900000000'").fetchone():
        con.execute("INSERT INTO users VALUES('0900000000','admin123','super',1)")
    con.commit();close_con(con)
init()

def mk_action(host,user,pwd,action,ip):
    if not routeros_api: return
    try:
        pool=routeros_api.RouterOsApiPool(host,username=user,password=pwd,plaintext_login=True)
        api=pool.get_api(); lst=api.get_resource('/ip/firewall/address-list')
        if action=='block': lst.add(list='Blocked',address=ip,comment='OMAIA')
        else:
            for e in lst.get(address=ip): lst.remove(id=e['id'])
        pool.disconnect()
    except: pass

def mk_online(s):
    if not routeros_api: return []
    try:
        pool=routeros_api.RouterOsApiPool(s['host'],username=s['username'],password=s['password'],plaintext_login=True,port=8728)
        api=pool.get_api(); r=api.get_resource('/ppp/active').get(); pool.disconnect(); return r
    except: return []

LAYOUT="""<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OMAIA</title>
<style>
body{font-family:Arial;background:__BG__;color:#fff;margin:0;display:flex;min-height:100vh}
.sidebar{width:230px;background:__SIDEBAR__;border-left:2px solid __MAIN__;padding:15px;position:fixed;left:0;top:0;bottom:0;overflow-y:auto;transition:transform.3s;z-index:1000}
.sidebar.closed{transform:translateX(-100%)}
.sidebar h2{color:__MAIN__;text-align:center;font-size:18px;border-bottom:1px solid #2a344a;padding-bottom:10px}
.sidebar a{display:block;background:#1f2937;color:#fff;padding:12px;margin:8px 0;border-radius:10px;text-decoration:none;font-size:14px;font-weight:bold}
.sidebar a:hover{background:__MAIN__;color:#000}
.sidebar a.active{background:__MAIN__;color:#000}
.main{margin-left:230px;flex:1;padding:20px;transition:margin.3s;width:100%}
.main.full{margin-left:0}
.topbar{background:__TOPBAR__;color:__MAIN__;padding:14px;border-radius:12px;margin-bottom:15px;text-align:center;border:1px solid __MAIN__;display:flex;align-items:center;justify-content:space-between}
.menu-btn{background:__MAIN__;color:#000;border:none;padding:8px 14px;border-radius:8px;font-size:18px;cursor:pointer;width:auto}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{padding:8px;border-bottom:1px solid #2a344a;text-align:center}th{color:__MAIN__;background:__CARD__}
input,select{width:100%;padding:9px;margin:5px 0;background:#1f2937;border:1px solid #374151;color:#fff;border-radius:8px;box-sizing:border-box}
button{background:__MAIN__;padding:10px;width:100%;border:none;border-radius:8px;font-weight:bold;cursor:pointer}
.card{background:__CARD__;padding:12px;border-radius:10px;margin:10px 0}
.form2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
@media(max-width:600px){.form2{grid-template-columns:1fr}}
.badge{padding:3px 10px;border-radius:20px;font-size:12px}.on{background:#065f46;color:#34d399}.off{background:#7f1d1d;color:#fca5a5}
</style></head><body>
<div class="sidebar" id="sb"><h2>🏢 OMAIA</h2>
{% if sess %}
<a href="/dash?view=subs">🏠 المشتركين</a>
<a href="/search">🔍 بحث</a>
<a href="/dash?view=add">➕ إضافة</a>
<a href="/dash?view=ledger">💰 دفتر الحسابات</a>
<a href="/dash?view=dishes">📡 صحون</a>
<a href="/dash?view=servers">🖥️ سيرفرات</a>
{% if role=='super' %}<a href="/dash?view=settings">⚙️ إعدادات</a>{% endif %}
<a href="/logout" style="background:#7f1d1d;color:#fff">خروج</a>
{% endif %}</div>
<div class="main" id="mn"><div class="topbar"><button class="menu-btn" onclick="toggleSb(event)">☰</button><span>نظام الشركة الخاص - OMAIA</span><span></span></div>{{content|safe}}</div>
<script>
function toggleSb(e){ if(e) e.stopPropagation(); document.getElementById('sb').classList.toggle('closed'); document.getElementById('mn').classList.toggle('full'); }
function closeSb(){document.getElementById('sb').classList.add('closed');document.getElementById('mn').classList.add('full')}
// تسكير القائمة بس تكبس بأي مكان بالشاشة
document.addEventListener('click', function(e){
  var sb=document.getElementById('sb');
  var btn=document.querySelector('.menu-btn');
  if(sb.classList.contains('closed')) return;
  if(sb.contains(e.target)) return;
  if(btn && btn.contains(e.target)) return;
  closeSb();
});
document.querySelectorAll('.sidebar a').forEach(a=>{ if(a.getAttribute('href')===location.pathname+location.search) a.classList.add('active')});
if(window.innerWidth<900){closeSb()}
</script>
</body></html>"""

def render(c):
    col=get_colors()
    html=LAYOUT.replace("__MAIN__",col["main"]).replace("__BG__",col["bg"]).replace("__CARD__",col["card"]).replace("__SIDEBAR__",col.get("sidebar","#111827")).replace("__TOPBAR__",col.get("topbar","#111827"))
    return render_template_string(html,content=c,sess=session.get('phone'),role=session.get('role'))

@app.route('/')
def idx(): return redirect('/dash') if session.get('phone') else redirect('/login')
@app.route('/dashboard')
def old(): return redirect('/dash')

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        con=db(); u=ex(con,"SELECT * FROM users WHERE phone=? AND password=? AND active=1",(request.form['phone'],request.form['password'])).fetchone(); close_con(con)
        if u:
            session['phone']=u['phone'] if isinstance(u,dict) else u[0]
            session['role']=u['role'] if isinstance(u,dict) else u[2]
            return redirect('/dash')
        return render("<p style='color:red;text-align:center'>دخول مرفوض</p><form method='post'><input name='phone'><input type='password' name='password'><button>دخول</button></form>")
    return render("<div style='max-width:360px;margin:30px auto'><h3 style='text-align:center'>دخول الشركة</h3><form method='post'><input name='phone' required placeholder='الهاتف'><input type='password' name='password' required placeholder='كلمة السر'><button>دخول</button></form></div>")

@app.route('/logout')
def logout(): session.clear(); return redirect('/login')

@app.route('/dash')
def dash():
    if not session.get('phone'): return redirect('/login')
    v=request.args.get('view','subs'); con=db()
    r=ex(con,"SELECT (SELECT COUNT(*) FROM subs) as t,(SELECT COUNT(*) FROM subs WHERE status='نشط') as a,(SELECT COALESCE(SUM(usd),0) FROM accounts) as u,(SELECT COUNT(*) FROM servers) as s,(SELECT COUNT(*) FROM dish_ips) as d").fetchone()
    total=r['t']; active=r['a']; sum_usd=r['u']; srv_cnt=r['s']; dish_cnt=r['d']
    stats=f"""<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin-bottom:15px">
    <div style="background:linear-gradient(135deg,#d4af37,#a67c00);padding:14px;border-radius:12px;text-align:center;color:#000"><h2>{total}</h2><div>مشترك</div></div>
    <div style="background:linear-gradient(135deg,#10b981,#065f46);padding:14px;border-radius:12px;text-align:center"><h2>{active}</h2><div>نشط</div></div>
    <div style="background:linear-gradient(135deg,#ef4444,#7f1d1d);padding:14px;border-radius:12px;text-align:center"><h2>{total-active}</h2><div>موقوف</div></div>
    <div style="background:linear-gradient(135deg,#3b82f6,#1e3a8a);padding:14px;border-radius:12px;text-align:center"><h2>${sum_usd:.0f}</h2><div>رصيد $</div></div>
    <div style="background:linear-gradient(135deg,#8b5cf6,#4c1d95);padding:14px;border-radius:12px;text-align:center"><h2>{srv_cnt}</h2><div>سيرفر</div></div>
    <div style="background:linear-gradient(135deg,#f59e0b,#92400e);padding:14px;border-radius:12px;text-align:center"><h2>{dish_cnt}</h2><div>صحن</div></div></div>"""
    c=""
    if v=='subs':
        rows=ex(con,"SELECT s.*,a.usd,sv.name as svname FROM subs s LEFT JOIN accounts a ON a.sub_id=s.id LEFT JOIN servers sv ON sv.id=s.server_id").fetchall()
        tr=""
        for r2 in rows:
            dip=r2['dish_ip']; dname="-"
            if dip:
                dd=ex(con,"SELECT location,site FROM dish_ips WHERE ip=?",(dip,)).fetchone()
                if dd:
                    loc=dd['location'] if isinstance(dd,dict) else dd[0]
                    dname=loc if loc else dip
                else: dname=dip
            tr+=f"<tr><td>{r2['name']}</td><td>{r2['phone']}</td><td>{dname}</td><td>{r2['svname'] or '-'}</td><td>${r2['usd'] or 0}</td><td><span class='badge {'on' if r2['status']=='نشط' else 'off'}'>{r2['status']}</span></td><td><a href='/toggle/{r2['id']}' style='color:#d4af37'>فصل/وصل</a> | <a href='/del_sub/{r2['id']}' style='color:#f87171' onclick='return confirm(\"حذف؟\")'>حذف</a></td></tr>"
        c=stats+f"<table><tr><th>الاسم</th><th>هاتف</th><th>الصحن</th><th>سيرفر</th><th>$</th><th>حالة</th><th>تحكم</th></tr>{tr}</table>"
    elif v=='add':
        srvs=ex(con,"SELECT * FROM servers").fetchall()
        opts="".join([f"<option value='{s['id']}'>{s['name']}</option>" for s in srvs])
        dishes=ex(con,"SELECT * FROM dish_ips").fetchall()
        dopts=""
        for d in dishes:
            dd=dict(d) if not isinstance(d,dict) else d
            l=dd.get('location') or dd.get('ip')
            s=dd.get('site') or ''
            dopts+=f"<option value='{dd.get('ip')}'>{l} - {s} ({dd.get('ip')})</option>"
        c=f"<h3>إضافة مشترك</h3><form method='post' action='/add_sub'><div class='form2'><input name='name' required placeholder='الاسم'><input name='phone' required placeholder='الهاتف'><input name='speed' placeholder='السرعة'><select name='dish_ip'><option value=''>اختر الصحن</option>{dopts}</select><select name='server_id'><option value=''>بدون سيرفر</option>{opts}</select><select name='status'><option>نشط</option><option>موقوف</option></select></div><button>حفظ</button></form>"
    elif v=='ledger':
        rows=ex(con,"SELECT l.*,s.name FROM ledger l LEFT JOIN subs s ON s.id=l.sub_id ORDER BY l.id DESC LIMIT 100").fetchall()
        subs=ex(con,"SELECT id,name FROM subs").fetchall()
        opts="".join([f"<option value='{s['id']}'>{s['name']}</option>" for s in subs])
        tr="".join([f"<tr><td>{r['date']}</td><td>{r['name']}</td><td>{r['usd']}</td><td>{r['syr']}</td><td>{r['note']}</td><td>{r['by_user']}</td></tr>" for r in rows])
        c=f"<div class='card'><form method='post' action='/charge'><div class='form2'><select name='sub_id'>{opts}</select><input name='amount' placeholder='المبلغ'><select name='currency'><option value='usd'>دولار</option><option value='syr'>سوري</option></select><input name='note' placeholder='ملاحظة'></div><button>حفظ</button></form></div><table><tr><th>التاريخ</th><th>المشترك</th><th>$</th><th>ل.س</th><th>ملاحظة</th><th>بواسطة</th></tr>{tr}</table>"
    elif v=='dishes':
        rows=ex(con,"SELECT * FROM dish_ips").fetchall()
        tr=""
        for r in rows:
            d=dict(r) if not isinstance(r,dict) else r
            tr+=f"<tr><td>{d.get('location') or '-'}</td><td>{d.get('site') or '-'}</td><td style='direction:ltr'>{d.get('ip')}</td><td><a href='/del_dish/{d.get('id')}' style='color:#f87171'>حذف</a></td></tr>"
        c=f"<div class='card'><form method='post' action='/add_dish'><div class='form2'><input name='location' required placeholder='اسم الشبكة'><input name='site' placeholder='موقع البرج'><input name='ip' required placeholder='IP الصحن' style='direction:ltr'></div><button>إضافة</button></form></div><table><tr><th>اسم الشبكة</th><th>موقع البرج</th><th>IP</th><th></th></tr>{tr}</table>"
    elif v=='servers':
        srvs=ex(con,"SELECT * FROM servers").fetchall()
        tr="".join([f"<tr><td>{s['name']}</td><td>{s['host']}</td><td>-</td><td><a href='/dash?view=srv_detail&id={s['id']}' style='color:#d4af37'>مراقبة</a> | <a href='/del_srv/{s['id']}' style='color:#f87171'>حذف</a></td></tr>" for s in srvs])
        c=f"<div class='card'><form method='post' action='/add_srv'><div class='form2'><input name='name' required placeholder='اسم السيرفر'><input name='host' required placeholder='192.168.88.1'><input name='username' required placeholder='يوزر'><input name='password' placeholder='باسورد'></div><button>إضافة سيرفر</button></form></div><table><tr><th>الاسم</th><th>الهوست</th><th>متصل</th><th>تحكم</th></tr>{tr}</table>"
    elif v=='srv_detail':
        s=ex(con,"SELECT * FROM servers WHERE id=?",(request.args.get('id'),)).fetchone()
        on=mk_online(s); tr="".join([f"<tr><td>{u.get('name','')}</td><td>{u.get('address','')}</td><td>{u.get('uptime','')}</td></tr>" for u in on])
        c=f"<h3>{s['name']} - {len(on)} متصل</h3><table><tr><th>المستخدم</th><th>IP</th><th>المدة</th></tr>{tr}</table>"
    elif v=='settings' and session.get('role')=='super':
        col=get_colors()
        users=ex(con,"SELECT * FROM users").fetchall()
        utr=""
        for u in users:
            ph=u['phone']; rl=u['role']; ac=u['active']
            utr+=f"<tr><td>{ph}</td><td>{rl}</td><td>{'مفعل' if ac else 'موقوف'}</td><td><a href='/dash?view=settings&edit={ph}' style='color:#60a5fa'>تعديل</a> | <a href='/toggle_user/{ph}' style='color:#d4af37'>تفعيل/ايقاف</a> | <a href='/del_user/{ph}' style='color:#f87171' onclick='return confirm(\"حذف؟\")'>حذف</a></td></tr>"
        edit_id=request.args.get('edit'); edit_form=""
        if edit_id:
            eu=ex(con,"SELECT * FROM users WHERE phone=?",(edit_id,)).fetchone()
            if eu:
                eph=eu['phone']; erl=eu['role']
                edit_form=f"<div class='card'><h4>تعديل {eph}</h4><form method='post' action='/edit_user/{eph}'><div class='form2'><input name='new_phone' value='{eph}' required><input name='password' placeholder='باسورد جديد'><select name='role'><option value='staff' {'selected' if erl=='staff' else ''}>موظف</option><option value='super' {'selected' if erl=='super' else ''}>مدير</option></select></div><button>حفظ التعديل</button></form></div>"
        c=edit_form+f"<div class='card'><h4>👥 اليوزرات وكلمات السر</h4><form method='post' action='/add_user'><div class='form2'><input name='phone' required placeholder='هاتف'><input name='password' required placeholder='باسورد'><select name='role'><option value='staff'>موظف</option><option value='super'>مدير</option></select></div><button>إضافة يوزر</button></form><table><tr><th>يوزر</th><th>دور</th><th>حالة</th><th>تحكم</th></tr>{utr}</table></div>"
        c+=f"""<div class='card'><h4>تغيير كلمة سرك</h4><form method='post' action='/change_pass'><input type='password' name='newpass' required placeholder='جديدة'><button>تغيير</button></form></div>
        <div class='card'><h4>🎨 الألوان</h4><form method='post' action='/save_colors'><div class='form2'>
        <div><label>الرئيسي</label><input type='color' name='main' value='{col["main"]}'></div>
        <div><label>الخلفية</label><input type='color' name='bg' value='{col["bg"]}'></div>
        <div><label>البطاقات</label><input type='color' name='card' value='{col["card"]}'></div>
        <div><label>القائمة</label><input type='color' name='sidebar' value='{col.get("sidebar","#111827")}'></div>
        <div><label>العلوي</label><input type='color' name='topbar' value='{col.get("topbar","#111827")}'></div>
        </div><button>حفظ الألوان</button></form><a href='/reset_colors' style='color:#f87171'>استعادة الافتراضي</a></div>"""
    close_con(con); return render(c)

@app.route('/save_colors',methods=['POST'])
def save_colors():
    if session.get('role')!='super': return "مرفوض"
    save_colors_dict({k:request.form[k] for k in DEFAULT_COLORS if k in request.form})
    return redirect('/dash?view=settings')

@app.route('/reset_colors')
def reset_colors_route():
    if session.get('role')!='super': return "مرفوض"
    reset_colors()
    return redirect('/dash?view=settings')

@app.route('/search')
def search():
    if not session.get('phone'): return redirect('/login')
    q=request.args.get('q','').strip()
    con=db(); like="%"+q+"%"
    if q:
        # البحث فقط بالمشتركين - الايبيات ما تطلع
        rows=ex(con,"SELECT * FROM subs WHERE name LIKE? OR phone LIKE?",(like,like)).fetchall()
    else:
        rows=ex(con,"SELECT * FROM subs LIMIT 50").fetchall()
    close_con(con)
    tr=""
    for r in rows:
        d=dict(r) if not isinstance(r,dict) else r
        tr+="<tr><td>"+str(d.get('name',''))+"</td><td>"+str(d.get('phone',''))+"</td><td>"+str(d.get('status',''))+"</td></tr>"
    c="<form method='get' action='/search' style='display:flex;gap:8px;margin-bottom:15px'>"
    c+="<input name='q' value='"+q+"' placeholder='ابحث اسم مشترك او هاتف...' style='flex:1'>"
    c+="<button style='width:100px'>بحث</button></form>"
    c+="<h3>المشتركين ("+str(len(rows))+")</h3><table><tr><th>الاسم</th><th>الهاتف</th><th>الحالة</th></tr>"+tr+"</table>"
    return render(c)

@app.route('/export')
def export():
    con=db(); rows=ex(con,"SELECT s.name,s.phone,s.status,s.dish_ip,a.usd,a.syr FROM subs s LEFT JOIN accounts a ON a.sub_id=s.id").fetchall(); close_con(con)
    out=io.StringIO(); w=csv.writer(out); w.writerow(['الاسم','الهاتف','الحالة','IP','دولار','سوري'])
    for r in rows: w.writerow([r['name'],r['phone'],r['status'],r['dish_ip'],r['usd'] or 0,r['syr'] or 0])
    return Response(out.getvalue().encode('utf-8-sig'),mimetype='text/csv',headers={'Content-Disposition':'attachment;filename=subs.csv'})

@app.route('/add_user',methods=['POST'])
def add_user():
    if session.get('role')!='super': return "مرفوض"
    con=db()
    if ex(con,"SELECT COUNT(*) c FROM users").fetchone()['c']>=10: close_con(con); return "الحد 10 فقط"
    try: ex(con,"INSERT INTO users VALUES(?,?,?,1)",(request.form['phone'],request.form['password'],request.form['role']))
    except: pass
    con.commit();close_con(con); return redirect('/dash?view=settings')

@app.route('/edit_user/<p>',methods=['POST'])
def edit_user(p):
    if session.get('role')!='super': return "مرفوض"
    np=request.form.get('new_phone',p); pw=request.form.get('password'); rl=request.form.get('role')
    con=db()
    if np!=p:
        ex(con,"UPDATE users SET phone=?,role=? WHERE phone=?",(np,rl,p))
        ex(con,"UPDATE ledger SET by_user=? WHERE by_user=?",(np,p))
    else:
        ex(con,"UPDATE users SET role=? WHERE phone=?",(rl,p))
    if pw: ex(con,"UPDATE users SET password=? WHERE phone=?",(pw,np))
    con.commit();close_con(con); return redirect('/dash?view=settings')

@app.route('/del_user/<p>')
def del_user(p):
    if session.get('role')!='super': return "مرفوض"
    if p=='0900000000': return "لا يمكن حذف المدير الأساسي"
    if p==session.get('phone'): return "لا يمكن حذف نفسك"
    con=db();ex(con,"DELETE FROM users WHERE phone=?",(p,));con.commit();close_con(con);return redirect('/dash?view=settings')

@app.route('/toggle_user/<p>')
def tu(p):
    con=db();ex(con,"UPDATE users SET active=1-active WHERE phone=?",(p,));con.commit();close_con(con);return redirect('/dash?view=settings')

@app.route('/add_sub',methods=['POST'])
def add_sub():
    con=db()
    if USE_PG:
        cur=ex(con,"INSERT INTO subs(name,phone,speed,status,server_id,dish_ip) VALUES(?,?,?,?,?,?) RETURNING id",(request.form['name'],request.form['phone'],request.form.get('speed',''),request.form.get('status','نشط'),request.form.get('server_id') or None,request.form.get('dish_ip','')))
        sid=cur.fetchone()['id']
        ex(con,"INSERT INTO accounts(sub_id) VALUES(?) ON CONFLICT DO NOTHING",(sid,))
    else:
        cur=con.cursor()
        cur.execute("INSERT INTO subs(name,phone,speed,status,server_id,dish_ip) VALUES(?,?,?,?,?,?)",(request.form['name'],request.form['phone'],request.form.get('speed',''),request.form.get('status','نشط'),request.form.get('server_id') or None,request.form.get('dish_ip','')))
        sid=cur.lastrowid
        cur.execute("INSERT OR IGNORE INTO accounts(sub_id) VALUES(?)",(sid,))
    con.commit();close_con(con); return redirect('/dash?view=subs')

@app.route('/charge',methods=['POST'])
def charge():
    sid=request.form['sub_id']
    amt=float(request.form.get('amount') or 0)
    cur=request.form.get('currency','usd')
    usd=amt if cur=='usd' else 0
    syr=amt if cur=='syr' else 0
    con=db(); ex(con,"UPDATE accounts SET usd=usd+?,syr=syr+? WHERE sub_id=?",(usd,syr,sid))
    ex(con,"INSERT INTO ledger(sub_id,date,usd,syr,note,by_user) VALUES(?,?,?,?,?,?)",(sid,datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),usd,syr,request.form.get('note',''),session.get('phone')))
    con.commit();close_con(con); return redirect('/dash?view=ledger')

@app.route('/add_dish',methods=['POST'])
def add_dish():
    con=db()
    ip=request.form.get('ip','').strip()
    loc=request.form.get('location','').strip()
    site=request.form.get('site','').strip()
    try:
        # حاول ادخال مع site، واذا العمود مو موجود ادخل بدون
        try: ex(con,"INSERT INTO dish_ips(ip,location,site) VALUES(?,?,?)",(ip,loc,site))
        except: ex(con,"INSERT INTO dish_ips(ip,location) VALUES(?,?)",(ip,loc))
    except:
        try:
            try: ex(con,"UPDATE dish_ips SET location=?, site=? WHERE ip=?",(loc,site,ip))
            except: ex(con,"UPDATE dish_ips SET location=? WHERE ip=?",(loc,ip))
        except: pass
    con.commit();close_con(con); return redirect('/dash?view=dishes')

@app.route('/del_dish/<int:i>')
def del_dish(i): con=db();ex(con,"DELETE FROM dish_ips WHERE id=?",(i,));con.commit();close_con(con);return redirect('/dash?view=dishes')

@app.route('/add_srv',methods=['POST'])
def add_srv():
    con=db();ex(con,"INSERT INTO servers(name,host,username,password) VALUES(?,?,?,?)",(request.form['name'],request.form['host'],request.form['username'],request.form.get('password','')));con.commit();close_con(con);return redirect('/dash?view=servers')

@app.route('/del_srv/<int:i>')
def del_srv(i): con=db();ex(con,"DELETE FROM servers WHERE id=?",(i,));con.commit();close_con(con);return redirect('/dash?view=servers')

@app.route('/toggle/<int:sid>')
def toggle(sid):
    con=db(); s=ex(con,"SELECT * FROM subs WHERE id=?",(sid,)).fetchone()
    if s:
        new='موقوف' if s['status']=='نشط' else 'نشط'
        ex(con,"UPDATE subs SET status=? WHERE id=?",(new,sid));con.commit()
        if s['server_id'] and s['dish_ip']:
            srv=ex(con,"SELECT * FROM servers WHERE id=?",(s['server_id'],)).fetchone()
            if srv: mk_action(srv['host'],srv['username'],srv['password'],'block' if new=='موقوف' else 'unblock',s['dish_ip'])
    close_con(con); return redirect('/dash?view=subs')

@app.route('/del_sub/<int:sid>')
def del_sub(sid): con=db();ex(con,"DELETE FROM subs WHERE id=?",(sid,));con.commit();close_con(con);return redirect('/dash?view=subs')

@app.route('/change_pass',methods=['POST'])
def cp(): con=db();ex(con,"UPDATE users SET password=? WHERE phone=?",(request.form['newpass'],session.get('phone')));con.commit();close_con(con);return redirect('/dash?view=settings')

if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get('PORT',10000)))
