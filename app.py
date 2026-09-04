from flask import Flask, request, redirect, render_template_string, session, Response
import sqlite3, os, datetime, io, csv
try: import routeros_api
except: routeros_api=None

app=Flask(__name__)
app.secret_key=os.urandom(24)
DB="omaia_company.db"

def db():
    con=sqlite3.connect(DB); con.row_factory=sqlite3.Row; return con

def init():
    con=db()
    con.execute("CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,active INTEGER DEFAULT 1)")
    con.execute("CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,speed TEXT,status TEXT,server_id INTEGER,dish_ip TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS accounts(sub_id INTEGER PRIMARY KEY,usd REAL DEFAULT 0,syr REAL DEFAULT 0)")
    con.execute("CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,sub_id INTEGER,date TEXT,usd REAL,syr REAL,note TEXT,by_user TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS servers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,host TEXT,username TEXT,password TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT UNIQUE,location TEXT,sub_id INTEGER)")
    if not con.execute("SELECT * FROM users WHERE phone='0900000000'").fetchone():
        con.execute("INSERT INTO users VALUES('0900000000','admin123','super',1)")
    con.commit(); con.close()
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
        pool=routeros_api.RouterOsApiPool(s['host'],username=s['username'],password=s['password'],plaintext_login=True)
        api=pool.get_api(); r=api.get_resource('/ppp/active').get(); pool.disconnect(); return r
    except: return []

LAYOUT="""<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OMAIA</title>
<style>
body{font-family:Arial;background:#0b0f19;color:#fff;margin:0;display:flex;min-height:100vh}
.sidebar{width:230px;background:#111827;border-left:2px solid #d4af37;padding:15px;position:fixed;left:0;top:0;bottom:0;overflow-y:auto}
.sidebar h2{color:#d4af37;text-align:center;font-size:18px;border-bottom:1px solid #2a344a;padding-bottom:10px}
.sidebar a{display:block;background:#1f2937;color:#fff;padding:12px;margin:8px 0;border-radius:10px;text-decoration:none;font-size:14px;font-weight:bold}
.sidebar a:hover,.sidebar a.active{background:#d4af37;color:#000}
.main{margin-left:230px;flex:1;padding:20px}
.topbar{background:#111827;color:#d4af37;padding:14px;border-radius:12px;margin-bottom:15px;text-align:center;border:1px solid #d4af37}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{padding:8px;border-bottom:1px solid #2a344a;text-align:center}th{color:#d4af37;background:#1a2336}
input,select{width:100%;padding:9px;margin:5px 0;background:#1f2937;border:1px solid #374151;color:#fff;border-radius:8px;box-sizing:border-box}
button{background:#d4af37;padding:10px;width:100%;border:none;border-radius:8px;font-weight:bold;cursor:pointer}
.card{background:#1a2336;padding:12px;border-radius:10px;margin:10px 0}
.badge{padding:3px 10px;border-radius:20px;font-size:12px}.on{background:#065f46;color:#34d399}.off{background:#7f1d1d;color:#fca5a5}
@media(max-width:768px){.sidebar{width:70px}.sidebar a{font-size:11px;padding:8px;text-align:center}.main{margin-left:70px}}
</style></head><body>
<div class="sidebar"><h2>🏢 OMAIA</h2>
{% if sess %}
<a href="/dash?view=subs">🏠 المشتركين</a>
<a href="/search">🔍 بحث</a>
<a href="/dash?view=add">➕ إضافة</a>
<a href="/dash?view=ledger">💰 دفتر الحسابات</a>
<a href="/dash?view=dishes">📡 صحون</a>
<a href="/dash?view=servers">🖥️ سيرفرات</a>
{% if role=='super' %}<a href="/dash?view=users">👥 المستخدمين</a><a href="/dash?view=settings">⚙️ إعدادات</a>{% endif %}
<a href="/logout" style="background:#7f1d1d;color:#fff">خروج</a>
{% endif %}</div>
<div class="main"><div class="topbar">نظام الشركة الخاص - OMAIA</div>{{content|safe}}</div>
</body></html>"""

def render(c): return render_template_string(LAYOUT,content=c,sess=session.get('phone'),role=session.get('role'))

@app.route('/')
def idx(): return redirect('/dash') if session.get('phone') else redirect('/login')
@app.route('/dashboard')
def old(): return redirect('/dash')
@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        con=db(); u=con.execute("SELECT * FROM users WHERE phone=? AND password=? AND active=1",(request.form['phone'],request.form['password'])).fetchone(); con.close()
        if u: session['phone']=u['phone']; session['role']=u['role']; return redirect('/dash')
        return render("<p style='color:red;text-align:center'>دخول مرفوض</p><form method='post'><input name='phone'><input type='password' name='password'><button>دخول</button></form>")
    return render("<div style='max-width:360px;margin:30px auto'><h3 style='text-align:center;color:#d4af37'>دخول الشركة</h3><form method='post'><input name='phone' required placeholder='الهاتف'><input type='password' name='password' required placeholder='كلمة السر'><button>دخول</button></form></div>")
@app.route('/logout')
def logout(): session.clear(); return redirect('/login')

@app.route('/dash')
def dash():
    if not session.get('phone'): return redirect('/login')
    v=request.args.get('view','subs'); con=db()
    total=con.execute("SELECT COUNT(*) c FROM subs").fetchone()['c']
    active=con.execute("SELECT COUNT(*) c FROM subs WHERE status='نشط'").fetchone()['c']
    sum_usd=con.execute("SELECT SUM(usd) s FROM accounts").fetchone()['s'] or 0
    srv_cnt=con.execute("SELECT COUNT(*) c FROM servers").fetchone()['c']
    dish_cnt=con.execute("SELECT COUNT(*) c FROM dish_ips").fetchone()['c']
    stats=f"""<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin-bottom:15px">
    <div style="background:linear-gradient(135deg,#d4af37,#a67c00);padding:14px;border-radius:12px;text-align:center;color:#000"><h2>{total}</h2><div>مشترك</div></div>
    <div style="background:linear-gradient(135deg,#10b981,#065f46);padding:14px;border-radius:12px;text-align:center"><h2>{active}</h2><div>نشط</div></div>
    <div style="background:linear-gradient(135deg,#ef4444,#7f1d1d);padding:14px;border-radius:12px;text-align:center"><h2>{total-active}</h2><div>موقوف</div></div>
    <div style="background:linear-gradient(135deg,#3b82f6,#1e3a8a);padding:14px;border-radius:12px;text-align:center"><h2>${sum_usd:.0f}</h2><div>رصيد $</div></div>
    <div style="background:linear-gradient(135deg,#8b5cf6,#4c1d95);padding:14px;border-radius:12px;text-align:center"><h2>{srv_cnt}</h2><div>سيرفر</div></div>
    <div style="background:linear-gradient(135deg,#f59e0b,#92400e);padding:14px;border-radius:12px;text-align:center"><h2>{dish_cnt}</h2><div>صحن</div></div></div>"""
    c=""
    if v=='subs':
        rows=con.execute("SELECT s.*,a.usd,sv.name as svname FROM subs s LEFT JOIN accounts a ON a.sub_id=s.id LEFT JOIN servers sv ON sv.id=s.server_id").fetchall()
        tr="".join([f"<tr><td>{r['name']}</td><td>{r['phone']}</td><td>{r['dish_ip'] or '-'}</td><td>{r['svname'] or '-'}</td><td>${r['usd'] or 0}</td><td><span class='badge {'on' if r['status']=='نشط' else 'off'}'>{r['status']}</span></td><td><a href='/toggle/{r['id']}' style='color:#d4af37'>فصل/وصل</a> | <a href='/del_sub/{r['id']}' style='color:#f87171' onclick='return confirm(\"حذف؟\")'>حذف</a></td></tr>" for r in rows])
        c=stats+f"<table><tr><th>الاسم</th><th>هاتف</th><th>IP</th><th>سيرفر</th><th>$</th><th>حالة</th><th>تحكم</th></tr>{tr}</table>"
    elif v=='add':
        srvs=con.execute("SELECT * FROM servers").fetchall()
        opts="".join([f"<option value='{s['id']}'>{s['name']}</option>" for s in srvs])
        c=f"<h3>إضافة مشترك</h3><form method='post' action='/add_sub'><input name='name' required placeholder='الاسم'><input name='phone' required placeholder='الهاتف'><input name='speed' placeholder='السرعة'><input name='dish_ip' placeholder='IP الصحن'><select name='server_id'><option value=''>بدون سيرفر</option>{opts}</select><select name='status'><option>نشط</option><option>موقوف</option></select><button>حفظ</button></form>"
    elif v=='ledger':
        rows=con.execute("SELECT l.*,s.name FROM ledger l LEFT JOIN subs s ON s.id=l.sub_id ORDER BY l.id DESC LIMIT 100").fetchall()
        subs=con.execute("SELECT id,name FROM subs").fetchall()
        opts="".join([f"<option value='{s['id']}'>{s['name']}</option>" for s in subs])
        tr="".join([f"<tr><td>{r['date']}</td><td>{r['name']}</td><td>{r['usd']}</td><td>{r['syr']}</td><td>{r['note']}</td><td>{r['by_user']}</td></tr>" for r in rows])
        c=f"<div class='card'><form method='post' action='/charge'><select name='sub_id'>{opts}</select><input name='usd' placeholder='دولار'><input name='syr' placeholder='سوري'><input name='note' placeholder='ملاحظة'><button>شحن</button></form></div><table><tr><th>التاريخ</th><th>المشترك</th><th>$</th><th>ل.س</th><th>ملاحظة</th><th>بواسطة</th></tr>{tr}</table>"
    elif v=='dishes':
        rows=con.execute("SELECT * FROM dish_ips").fetchall()
        tr="".join([f"<tr><td>{r['ip']}</td><td>{r['location'] or ''}</td><td><a href='/del_dish/{r['id']}' style='color:#f87171'>حذف</a></td></tr>" for r in rows])
        c=f"<div class='card'><form method='post' action='/add_dish'><input name='ip' required placeholder='IP الصحن'><input name='location' placeholder='الموقع'><button>إضافة</button></form></div><table><tr><th>IP</th><th>الموقع</th><th></th></tr>{tr}</table>"
    elif v=='servers':
        srvs=con.execute("SELECT * FROM servers").fetchall()
        tr="".join([f"<tr><td>{s['name']}</td><td>{s['host']}</td><td>{len(mk_online(s))} متصل</td><td><a href='/dash?view=srv_detail&id={s['id']}' style='color:#d4af37'>مراقبة</a> | <a href='/del_srv/{s['id']}' style='color:#f87171'>حذف</a></td></tr>" for s in srvs])
        c=f"<div class='card'><form method='post' action='/add_srv'><input name='name' required placeholder='اسم السيرفر'><input name='host' required placeholder='192.168.88.1'><input name='username' required placeholder='يوزر'><input name='password' placeholder='باسورد'><button>إضافة سيرفر</button></form></div><table><tr><th>الاسم</th><th>الهوست</th><th>متصل</th><th>تحكم</th></tr>{tr}</table>"
    elif v=='srv_detail':
        s=con.execute("SELECT * FROM servers WHERE id=?",(request.args.get('id'),)).fetchone()
        on=mk_online(s); tr="".join([f"<tr><td>{u.get('name','')}</td><td>{u.get('address','')}</td><td>{u.get('uptime','')}</td></tr>" for u in on])
        c=f"<h3>{s['name']} - {len(on)} متصل</h3><table><tr><th>المستخدم</th><th>IP</th><th>المدة</th></tr>{tr}</table>"
    elif v=='users' and session.get('role')=='super':
        users=con.execute("SELECT * FROM users").fetchall()
        tr="".join([f"<tr><td>{u['phone']}</td><td>{u['role']}</td><td>{'مفعل' if u['active'] else 'موقوف'}</td><td><a href='/toggle_user/{u['phone']}' style='color:#d4af37'>تفعيل/إيقاف</a></td></tr>" for u in users])
        c=f"<div class='card'><form method='post' action='/add_user'><input name='phone' required placeholder='هاتف'><input name='password' required placeholder='باسورد'><select name='role'><option value='staff'>موظف</option><option value='super'>مدير</option></select><button>إضافة ({len(users)}/4)</button></form></div><table><tr><th>هاتف</th><th>دور</th><th>حالة</th><th>تحكم</th></tr>{tr}</table>"
    elif v=='settings' and session.get('role')=='super':
        c="<div class='card'><h4>تغيير كلمة سرك</h4><form method='post' action='/change_pass'><input type='password' name='newpass' required placeholder='جديدة'><button>تغيير</button></form></div>"
    con.close(); return render(c)

@app.route('/search')
def search():
    if not session.get('phone'): return redirect('/login')
    q=request.args.get('q',''); con=db()
    rows=con.execute("SELECT * FROM subs WHERE name LIKE ? OR phone LIKE ? OR dish_ip LIKE ?",(f'%{q}%',f'%{q}%',f'%{q}%')).fetchall(); con.close()
    tr="".join([f"<tr><td>{r['name']}</td><td>{r['phone']}</td><td>{r['dish_ip']}</td><td>{r['status']}</td><td><a href='/toggle/{r['id']}' style='color:#d4af37'>فصل/وصل</a></td></tr>" for r in rows])
    c=f"<form action='/search' style='display:flex;gap:8px'><input name='q' value='{q}' placeholder='بحث بالاسم / هاتف / IP'><button style='width:120px'>بحث</button></form><a href='/export' style='color:#d4af37'>📥 تصدير Excel</a><table><tr><th>الاسم</th><th>هاتف</th><th>IP</th><th>حالة</th><th>تحكم</th></tr>{tr}</table>"
    return render(c)

@app.route('/export')
def export():
    con=db(); rows=con.execute("SELECT s.name,s.phone,s.status,s.dish_ip,a.usd,a.syr FROM subs s LEFT JOIN accounts a ON a.sub_id=s.id").fetchall(); con.close()
    out=io.StringIO(); w=csv.writer(out); w.writerow(['الاسم','الهاتف','الحالة','IP','دولار','سوري'])
    for r in rows: w.writerow([r['name'],r['phone'],r['status'],r['dish_ip'],r['usd'] or 0,r['syr'] or 0])
    return Response(out.getvalue().encode('utf-8-sig'),mimetype='text/csv',headers={'Content-Disposition':'attachment;filename=subs.csv'})

@app.route('/add_user',methods=['POST'])
def add_user():
    if session.get('role')!='super': return "مرفوض"
    con=db()
    if con.execute("SELECT COUNT(*) c FROM users").fetchone()['c']>=4: con.close(); return "الحد 4 فقط"
    try: con.execute("INSERT INTO users VALUES(?,?,?,1)",(request.form['phone'],request.form['password'],request.form['role']))
    except: pass
    con.commit();con.close(); return redirect('/dash?view=users')
@app.route('/toggle_user/<p>')
def tu(p):
    con=db();con.execute("UPDATE users SET active=1-active WHERE phone=?",(p,));con.commit();con.close();return redirect('/dash?view=users')
@app.route('/add_sub',methods=['POST'])
def add_sub():
    con=db();cur=con.cursor()
    cur.execute("INSERT INTO subs(name,phone,speed,status,server_id,dish_ip) VALUES(?,?,?,?,?,?)",(request.form['name'],request.form['phone'],request.form.get('speed',''),request.form.get('status','نشط'),request.form.get('server_id') or None,request.form.get('dish_ip','')))
    sid=cur.lastrowid; cur.execute("INSERT OR IGNORE INTO accounts(sub_id) VALUES(?)",(sid,)); con.commit();con.close(); return redirect('/dash?view=subs')
@app.route('/charge',methods=['POST'])
def charge():
    sid=request.form['sub_id']; usd=float(request.form.get('usd') or 0); syr=float(request.form.get('syr') or 0)
    con=db(); con.execute("UPDATE accounts SET usd=usd+?,syr=syr+? WHERE sub_id=?",(usd,syr,sid))
    con.execute("INSERT INTO ledger(sub_id,date,usd,syr,note,by_user) VALUES(?,?,?,?,?,?)",(sid,datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),usd,syr,request.form.get('note',''),session.get('phone')))
    con.commit();con.close(); return redirect('/dash?view=ledger')
@app.route('/add_dish',methods=['POST'])
def add_dish():
    con=db()
    try: con.execute("INSERT INTO dish_ips(ip,location) VALUES(?,?)",(request.form['ip'],request.form.get('location','')))
    except: pass
    con.commit();con.close(); return redirect('/dash?view=dishes')
@app.route('/del_dish/<int:i>')
def del_dish(i): con=db();con.execute("DELETE FROM dish_ips WHERE id=?",(i,));con.commit();con.close();return redirect('/dash?view=dishes')
@app.route('/add_srv',methods=['POST'])
def add_srv():
    con=db();con.execute("INSERT INTO servers(name,host,username,password) VALUES(?,?,?,?)",(request.form['name'],request.form['host'],request.form['username'],request.form.get('password','')));con.commit();con.close();return redirect('/dash?view=servers')
@app.route('/del_srv/<int:i>')
def del_srv(i): con=db();con.execute("DELETE FROM servers WHERE id=?",(i,));con.commit();con.close();return redirect('/dash?view=servers')
@app.route('/toggle/<int:sid>')
def toggle(sid):
    con=db(); s=con.execute("SELECT * FROM subs WHERE id=?",(sid,)).fetchone()
    if s:
        new='موقوف' if s['status']=='نشط' else 'نشط'
        con.execute("UPDATE subs SET status=? WHERE id=?",(new,sid));con.commit()
        if s['server_id'] and s['dish_ip']:
            srv=con.execute("SELECT * FROM servers WHERE id=?",(s['server_id'],)).fetchone()
            if srv: mk_action(srv['host'],srv['username'],srv['password'],'block' if new=='موقوف' else 'unblock',s['dish_ip'])
    con.close(); return redirect('/dash?view=subs')
@app.route('/del_sub/<int:sid>')
def del_sub(sid): con=db();con.execute("DELETE FROM subs WHERE id=?",(sid,));con.commit();con.close();return redirect('/dash?view=subs')
@app.route('/change_pass',methods=['POST'])
def cp(): con=db();con.execute("UPDATE users SET password=? WHERE phone=?",(request.form['newpass'],session.get('phone')));con.commit();con.close();return redirect('/dash?view=settings')

if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get('PORT',10000)))
