from flask import Flask, request, redirect, render_template_string, session
import sqlite3, os, datetime
try: import routeros_api
except: routeros_api=None

app=Flask(__name__)
app.secret_key=os.urandom(24)
DB="omaia_company.db"

def db():
    con=sqlite3.connect(DB)
    con.row_factory=sqlite3.Row
    return con

def init():
    con=db()
    con.execute("CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,active INTEGER DEFAULT 1)")
    con.execute("CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,speed TEXT,status TEXT,server_id INTEGER,dish_ip TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS accounts(sub_id INTEGER PRIMARY KEY,usd REAL DEFAULT 0,syr REAL DEFAULT 0)")
    con.execute("CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,sub_id INTEGER,date TEXT,usd REAL,syr REAL,note TEXT,by_user TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS servers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,host TEXT,username TEXT,password TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT UNIQUE,location TEXT,sub_id INTEGER)")
    # أدمن رئيسي
    if not con.execute("SELECT * FROM users WHERE phone='0900000000'").fetchone():
        con.execute("INSERT INTO users VALUES('0900000000','admin123','super',1)")
    con.commit(); con.close()
init()

def mk_server(srv_id):
    con=db()
    s=con.execute("SELECT * FROM servers WHERE id=?",(srv_id,)).fetchone()
    con.close()
    return s

def mk_action(host,user,pwd,action,ip):
    if not routeros_api: return "مكتبة routeros غير مثبتة"
    try:
        pool=routeros_api.RouterOsApiPool(host,username=user,password=pwd,plaintext_login=True)
        api=pool.get_api()
        lst=api.get_resource('/ip/firewall/address-list')
        if action=='block':
            lst.add(list='Blocked',address=ip,comment='OMAIA')
        else:
            for e in lst.get(address=ip):
                lst.remove(id=e['id'])
        pool.disconnect()
        return "تم"
    except Exception as e: return f"خطأ: {e}"

def mk_users_online(s):
    if not routeros_api: return []
    try:
        pool=routeros_api.RouterOsApiPool(s['host'],username=s['username'],password=s['password'],plaintext_login=True)
        api=pool.get_api()
        res=api.get_resource('/ppp/active').get()
        pool.disconnect()
        return res
    except: return []

LAYOUT="""<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OMAIA Company</title>
<style>body{font-family:Arial;background:#0b0f19;color:#fff;margin:0}nav{background:#111827;color:#d4af37;padding:16px;text-align:center;border-bottom:2px solid #d4af37;font-size:20px}
.container{max-width:1100px;margin:15px auto;background:#111827;padding:18px;border-radius:12px}.menu{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.menu a{background:#1f2937;color:#fff;padding:9px 12px;border-radius:8px;text-decoration:none;font-size:14px}.menu a:hover{color:#d4af37;border:1px solid #d4af37}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{padding:8px;border-bottom:1px solid #2a344a;text-align:center}th{color:#d4af37;background:#1a2336}
input,select{width:100%;padding:9px;margin:5px 0;background:#1f2937;border:1px solid #374151;color:#fff;border-radius:8px;box-sizing:border-box}
button{background:#d4af37;padding:10px;width:100%;border:none;border-radius:8px;font-weight:bold;cursor:pointer}.badge{padding:3px 10px;border-radius:20px;font-size:12px}.on{background:#065f46;color:#34d399}.off{background:#7f1d1d;color:#fca5a5}
.card{background:#1a2336;padding:12px;border-radius:10px;margin:10px 0}</style></head><body><nav>🏢 OMAIA - نظام الشركة الخاص</nav><div class="container">
{% if sess %}<div class="menu">
<a href="/dash?view=subs">المشتركين</a><a href="/dash?view=add">➕ إضافة</a><a href="/dash?view=ledger">💰 دفتر الحسابات</a>
<a href="/dash?view=dishes">📡 صحون</a><a href="/dash?view=servers">🖥️ سيرفرات</a>
{% if sess_role=='super' %}<a href="/dash?view=users">👥 المستخدمين</a>{% endif %}
<a href="/logout" style="background:#7f1d1d">خروج ({{sess_phone}})</a></div>{% endif %}{{content|safe}}</div></body></html>"""

def render(c):
    return render_template_string(LAYOUT,content=c,sess=session.get('phone'),sess_phone=session.get('phone'),sess_role=session.get('role'))

@app.route('/')
def i(): return redirect('/dash') if session.get('phone') else redirect('/login')
@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        con=db(); u=con.execute("SELECT * FROM users WHERE phone=? AND password=? AND active=1",(request.form['phone'],request.form['password'])).fetchone(); con.close()
        if u:
            session['phone']=u['phone']; session['role']=u['role']
            return redirect('/dash')
        return render("<p style='color:red;text-align:center'>دخول مرفوض</p><form method='post'><input name='phone' placeholder='الهاتف'><input type='password' name='password' placeholder='كلمة السر'><button>دخول</button></form>")
    return render("<div style='max-width:360px;margin:30px auto'><h3 style='text-align:center;color:#d4af37'>دخول الشركة</h3><form method='post'><input name='phone' required placeholder='رقم الهاتف'><input type='password' name='password' required placeholder='كلمة السر'><button>دخول</button></form></div>")

@app.route('/logout')
def logout(): session.clear(); return redirect('/login')

@app.route('/dash')
def dash():
    if not session.get('phone'): return redirect('/login')
    v=request.args.get('view','subs'); con=db(); c=""
    if v=='subs':
        subs=con.execute("SELECT s.*,a.usd,a.syr,sv.name as svname FROM subs s LEFT JOIN accounts a ON a.sub_id=s.id LEFT JOIN servers sv ON sv.id=s.server_id").fetchall()
        tr=""
        for s in subs:
            badge=f"<span class='badge {'on' if s['status']=='نشط' else 'off'}'>{s['status']}</span>"
            tr+=f"<tr><td>{s['name']}</td><td>{s['phone']}</td><td>{s['dish_ip'] or '-'}</td><td>{s['svname'] or '-'}</td><td>${s['usd'] or 0}</td><td>{badge}</td><td><a href='/toggle/{s['id']}' style='color:#d4af37'>فصل/وصل</a> | <a href='/del_sub/{s['id']}' style='color:#f87171' onclick='return confirm(\"حذف؟\")'>حذف</a></td></tr>"
        c=f"<h3>المشتركين ({len(subs)})</h3><table><tr><th>الاسم</th><th>هاتف</th><th>IP صحن</th><th>سيرفر</th><th>$</th><th>حالة</th><th>تحكم</th></tr>{tr}</table>"
    elif v=='add':
        srvs=con.execute("SELECT * FROM servers").fetchall()
        opts="".join([f"<option value='{s['id']}'>{s['name']} - {s['host']}</option>" for s in srvs])
        c=f"<h3>إضافة مشترك</h3><form method='post' action='/add_sub'><input name='name' required placeholder='الاسم'><input name='phone' required placeholder='الهاتف'><input name='speed' placeholder='السرعة'><input name='dish_ip' placeholder='IP الصحن'><select name='server_id'><option value=''>بدون سيرفر</option>{opts}</select><select name='status'><option>نشط</option><option>موقوف</option></select><button>حفظ</button></form>"
    elif v=='ledger':
        rows=con.execute("SELECT l.*,s.name FROM ledger l LEFT JOIN subs s ON s.id=l.sub_id ORDER BY l.id DESC LIMIT 100").fetchall()
        subs=con.execute("SELECT id,name FROM subs").fetchall()
        opts="".join([f"<option value='{s['id']}'>{s['name']}</option>" for s in subs])
        tr="".join([f"<tr><td>{r['date']}</td><td>{r['name']}</td><td>{r['usd']}</td><td>{r['syr']}</td><td>{r['note']}</td><td>{r['by_user']}</td></tr>" for r in rows])
        c=f"<div class='card'><h3>شحن رصيد</h3><form method='post' action='/charge'><select name='sub_id'>{opts}</select><input name='usd' placeholder='دولار'><input name='syr' placeholder='سوري'><input name='note' placeholder='ملاحظة'><button>شحن وتسجيل</button></form></div><h3>سجل الحركات</h3><table><tr><th>التاريخ</th><th>المشترك</th><th>$</th><th>ل.س</th><th>ملاحظة</th><th>بواسطة</th></tr>{tr}</table>"
    elif v=='dishes':
        rows=con.execute("SELECT d.*,s.name FROM dish_ips d LEFT JOIN subs s ON s.id=d.sub_id").fetchall()
        tr="".join([f"<tr><td>{r['ip']}</td><td>{r['location'] or ''}</td><td>{r['name'] or 'حر'}</td><td><a href='/del_dish/{r['id']}' style='color:#f87171'>حذف</a></td></tr>" for r in rows])
        c=f"<div class='card'><h3>إضافة IP صحن</h3><form method='post' action='/add_dish'><input name='ip' required placeholder='192.168.1.50'><input name='location' placeholder='الموقع / اسم الصحن'><button>إضافة</button></form></div><table><tr><th>IP</th><th>الموقع</th><th>مرتبط</th><th></th></tr>{tr}</table>"
    elif v=='servers':
        srvs=con.execute("SELECT * FROM servers").fetchall()
        tr=""
        for s in srvs:
            online=mk_users_online(s)
            tr+=f"<tr><td>{s['name']}</td><td>{s['host']}</td><td>{len(online)} متصل</td><td><a href='/dash?view=server_detail&id={s['id']}' style='color:#d4af37'>مراقبة</a> | <a href='/del_srv/{s['id']}' style='color:#f87171'>حذف</a></td></tr>"
        c=f"<div class='card'><h3>إضافة سيرفر مايكروتك</h3><form method='post' action='/add_srv'><input name='name' required placeholder='اسم السيرفر'><input name='host' required placeholder='192.168.88.1'><input name='username' required placeholder='admin'><input name='password' placeholder='كلمة سر المايكروتك'><button>إضافة سيرفر</button></form></div><table><tr><th>الاسم</th><th>الهوست</th><th>المتصلين</th><th>تحكم</th></tr>{tr}</table>"
    elif v=='server_detail':
        sid=request.args.get('id'); s=con.execute("SELECT * FROM servers WHERE id=?",(sid,)).fetchone()
        online=mk_users_online(s)
        tr="".join([f"<tr><td>{u.get('name','')}</td><td>{u.get('address','')}</td><td>{u.get('uptime','')}</td></tr>" for u in online])
        c=f"<h3>مراقبة {s['name']} - {len(online)} متصل</h3><table><tr><th>المستخدم</th><th>IP</th><th>المدة</th></tr>{tr}</table><a href='/dash?view=servers'>رجوع</a>"
    elif v=='users' and session.get('role')=='super':
        users=con.execute("SELECT * FROM users").fetchall()
        tr="".join([f"<tr><td>{u['phone']}</td><td>{u['role']}</td><td>{'مفعل' if u['active'] else 'موقوف'}</td><td><a href='/toggle_user/{u['phone']}' style='color:#d4af37'>تفعيل/إيقاف</a> {'| <a href=\'/del_user/'+u['phone']+'\' style=\'color:#f87171\'>حذف</a>' if u['phone']!='0900000000' else ''}</td></tr>" for u in users])
        c=f"<div class='card'><h3>إضافة شخص (بقي {3-len(users)} أماكن)</h3><form method='post' action='/add_user'><input name='phone' required placeholder='رقم الهاتف'><input name='password' required placeholder='كلمة السر'><select name='role'><option value='staff'>موظف</option><option value='super'>مدير</option></select><button>إضافة</button></form></div><table><tr><th>الهاتف</th><th>الدور</th><th>الحالة</th><th>تحكم</th></tr>{tr}</table>"
    con.close()
    return render(c)

@app.route('/add_user',methods=['POST'])
def add_user():
    if session.get('role')!='super': return "مرفوض"
    con=db()
    cnt=con.execute("SELECT COUNT(*) c FROM users").fetchone()['c']
    if cnt>=4: con.close(); return "الحد الأقصى 4 أشخاص (انت + 3)"
    try: con.execute("INSERT INTO users VALUES(?,?,?,1)",(request.form['phone'],request.form['password'],request.form['role']))
    except: pass
    con.commit();con.close(); return redirect('/dash?view=users')

@app.route('/toggle_user/<phone>')
def toggle_user(phone):
    if session.get('role')!='super': return "مرفوض"
    con=db(); con.execute("UPDATE users SET active=1-active WHERE phone=?",(phone,)); con.commit();con.close()
    return redirect('/dash?view=users')
@app.route('/del_user/<phone>')
def del_user(phone):
    if session.get('role')!='super' or phone=='0900000000': return "مرفوض"
    con=db(); con.execute("DELETE FROM users WHERE phone=?",(phone,)); con.commit();con.close()
    return redirect('/dash?view=users')

@app.route('/add_sub',methods=['POST'])
def add_sub():
    con=db(); cur=con.cursor()
    sid_empty=request.form.get('server_id') or None
    cur.execute("INSERT INTO subs(name,phone,speed,status,server_id,dish_ip) VALUES(?,?,?,?,?,?)",(request.form['name'],request.form['phone'],request.form.get('speed',''),request.form.get('status','نشط'),sid_empty,request.form.get('dish_ip','')))
    sid=cur.lastrowid
    cur.execute("INSERT OR IGNORE INTO accounts(sub_id) VALUES(?)",(sid,))
    con.commit();con.close(); return redirect('/dash?view=subs')

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
def del_dish(i):
    con=db(); con.execute("DELETE FROM dish_ips WHERE id=?",(i,)); con.commit();con.close(); return redirect('/dash?view=dishes')

@app.route('/add_srv',methods=['POST'])
def add_srv():
    con=db(); con.execute("INSERT INTO servers(name,host,username,password) VALUES(?,?,?,?)",(request.form['name'],request.form['host'],request.form['username'],request.form.get('password','')))
    con.commit();con.close(); return redirect('/dash?view=servers')
@app.route('/del_srv/<int:i>')
def del_srv(i):
    con=db(); con.execute("DELETE FROM servers WHERE id=?",(i,)); con.commit();con.close(); return redirect('/dash?view=servers')

@app.route('/toggle/<int:sid>')
def toggle(sid):
    con=db(); s=con.execute("SELECT * FROM subs WHERE id=?",(sid,)).fetchone()
    if s:
        new='موقوف' if s['status']=='نشط' else 'نشط'
        con.execute("UPDATE subs SET status=? WHERE id=?",(new,sid)); con.commit()
        if s['server_id'] and s['dish_ip']:
            srv=con.execute("SELECT * FROM servers WHERE id=?",(s['server_id'],)).fetchone()
            if srv: mk_action(srv['host'],srv['username'],srv['password'],'block' if new=='موقوف' else 'unblock',s['dish_ip'])
    con.close(); return redirect('/dash?view=subs')

@app.route('/del_sub/<int:sid>')
def del_sub(sid):
    con=db(); con.execute("DELETE FROM subs WHERE id=?",(sid,)); con.execute("DELETE FROM accounts WHERE sub_id=?",(sid,)); con.commit();con.close()
    return redirect('/dash?view=subs')

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get('PORT',10000)))
