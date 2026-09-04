from flask import Flask, request, redirect, render_template_string, session
import sqlite3, os

try:
    import routeros_api
except:
    routeros_api = None

app = Flask(__name__)
app.secret_key = os.urandom(24)
DB = "omaia_isp_final.db"

def init_db():
    con = sqlite3.connect(DB)
    con.execute("CREATE TABLE IF NOT EXISTS subs (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, phone TEXT, speed TEXT, status TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS accounts (sub_id INTEGER PRIMARY KEY, usd REAL DEFAULT 0, syr REAL DEFAULT 0)")
    con.execute("CREATE TABLE IF NOT EXISTS ips (id INTEGER PRIMARY KEY AUTOINCREMENT, ip TEXT UNIQUE, sub_id INTEGER, note TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS admins (phone TEXT PRIMARY KEY, password TEXT)")
    cur = con.cursor()
    cur.execute("SELECT * FROM admins WHERE phone='0900000000'")
    if not cur.fetchone():
        cur.execute("INSERT INTO admins VALUES ('0900000000','admin123')")
    con.commit(); con.close()
init_db()

def mikrotik_block(ip, block=True):
    if not routeros_api: return
    try:
        pool = routeros_api.RouterOsApiPool('192.168.88.1', username='admin', password='admin')
        api = pool.get_api()
        fw = api.get_resource('/ip/firewall/address-list')
        if block:
            fw.add(list='Blocked', address=ip, comment='OMAIA')
        else:
            for e in fw.get(address=ip):
                fw.remove(id=e['id'])
        pool.disconnect()
    except: pass

LAYOUT = """<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OMAIA ISP</title>
<style>
body{font-family:Arial;background:#0b0f19;color:#fff;margin:0}nav{background:#111827;color:#d4af37;padding:18px;text-align:center;font-size:22px;border-bottom:2px solid #d4af37}
.container{max-width:1050px;margin:20px auto;background:#111827;padding:20px;border-radius:12px}
.menu{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:15px}.menu a{background:#1f2937;color:#fff;padding:10px 14px;border-radius:8px;text-decoration:none;font-weight:bold}.menu a:hover{border:1px solid #d4af37;color:#d4af37}
table{width:100%;border-collapse:collapse;margin-top:10px}th,td{padding:10px;border-bottom:1px solid #2a344a;text-align:center}th{color:#d4af37;background:#1a2336}
input,select{width:100%;padding:10px;margin:6px 0;background:#1f2937;border:1px solid #374151;color:#fff;border-radius:8px;box-sizing:border-box}
button{background:#d4af37;padding:12px;width:100%;border:none;border-radius:8px;font-weight:bold;cursor:pointer;margin-top:8px}
.badge{padding:4px 10px;border-radius:20px;font-size:12px}.on{background:#065f46;color:#34d399}.off{background:#7f1d1d;color:#fca5a5}
.card{background:#1a2336;padding:15px;border-radius:10px;margin:10px 0}
</style></head><body><nav>✨ OMAIA ISP PRO ✨</nav><div class="container">
{% if is_logged %}<div class="menu"><a href="/dashboard?view=subs">المشتركين</a><a href="/dashboard?view=add">➕ إضافة</a><a href="/dashboard?view=accounts">💰 الحسابات</a><a href="/dashboard?view=ips">🌐 IPs</a><a href="/logout" style="background:#7f1d1d">خروج</a></div>{% endif %}
{{content|safe}}</div></body></html>"""

@app.route('/')
def index(): return redirect('/dashboard') if session.get('ok') else redirect('/login')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        con=sqlite3.connect(DB)
        r=con.execute("SELECT * FROM admins WHERE phone=? AND password=?",(request.form['phone'],request.form['password'])).fetchone()
        con.close()
        if r:
            session['ok']=True
            return redirect('/dashboard')
        c="<p style='color:#f87171;text-align:center'>خطأ بالدخول</p>"
    else: c=""
    c+="<div style='max-width:380px;margin:30px auto'><h3 style='text-align:center;color:#d4af37'>تسجيل الدخول</h3><form method='post'><input name='phone' placeholder='0900000000' required><input type='password' name='password' placeholder='كلمة السر' required><button>دخول</button></form></div>"
    return render_template_string(LAYOUT,is_logged=False,content=c)

@app.route('/logout')
def logout(): session.clear(); return redirect('/login')

@app.route('/dashboard')
def dash():
    if not session.get('ok'): return redirect('/login')
    v=request.args.get('view','subs')
    con=sqlite3.connect(DB); c=""
    if v=='subs':
        rows=con.execute("SELECT s.id,s.name,s.phone,s.speed,s.status,a.usd,a.syr,(SELECT ip FROM ips WHERE sub_id=s.id) FROM subs s LEFT JOIN accounts a ON a.sub_id=s.id").fetchall()
        tr=""
        for sid,name,phone,speed,status,usd,syr,ip in rows:
            usd=usd or 0; syr=syr or 0; ip=ip or '—'
            badge=f"<span class='badge {'on' if status=='نشط' else 'off'}'>{status}</span>"
            tr+=f"<tr><td>{name}</td><td>{phone}</td><td>{speed or '-'}</td><td>{ip}</td><td>${usd}</td><td>{syr}</td><td>{badge}</td><td><a href='/toggle/{sid}' style='color:#d4af37'>🔄</a> <a href='/del/{sid}' style='color:#f87171' onclick='return confirm(\"حذف؟\")'>🗑️</a></td></tr>"
        c=f"<h3>المشتركين ({len(rows)})</h3><table><tr><th>الاسم</th><th>هاتف</th><th>سرعة</th><th>IP</th><th>$</th><th>ل.س</th><th>حالة</th><th>تحكم</th></tr>{tr}</table>"
    elif v=='add':
        c="<h3>إضافة مشترك</h3><form method='post' action='/add'><input name='name' placeholder='الاسم' required><input name='phone' placeholder='الهاتف' required><input name='speed' placeholder='السرعة مثلا 10M'><input name='ip' placeholder='IP مثلا 192.168.1.10'><select name='status'><option>نشط</option><option>موقوف</option></select><button>حفظ</button></form>"
    elif v=='accounts':
        rows=con.execute("SELECT s.id,s.name,a.usd,a.syr FROM subs s LEFT JOIN accounts a ON a.sub_id=s.id").fetchall()
        tr=""
        for sid,name,usd,syr in rows:
            tr+=f"<tr><td>{name}</td><td>${usd or 0}</td><td>{syr or 0}</td><td><form method='post' action='/charge/{sid}' style='display:flex;gap:5px'><input name='usd' placeholder='$' style='width:70px'><input name='syr' placeholder='ل.س' style='width:90px'><button style='width:auto;padding:8px'>شحن</button></form></td></tr>"
        c=f"<h3>دفتر الحسابات</h3><table><tr><th>المشترك</th><th>دولار</th><th>سوري</th><th>شحن رصيد</th></tr>{tr}</table>"
    elif v=='ips':
        rows=con.execute("SELECT ips.ip, subs.name, ips.note FROM ips LEFT JOIN subs ON subs.id=ips.sub_id").fetchall()
        tr="".join([f"<tr><td>{r[0]}</td><td>{r[1] or 'حر'}</td><td>{r[2] or ''}</td></tr>" for r in rows])
        c=f"<h3>إدارة IPs</h3><div class='card'><form method='post' action='/add_ip'><input name='ip' placeholder='IP جديد' required><input name='note' placeholder='ملاحظة'><button>إضافة IP</button></form></div><table><tr><th>IP</th><th>مرتبط بـ</th><th>ملاحظة</th></tr>{tr}</table>"
    con.close()
    return render_template_string(LAYOUT,is_logged=True,content=c)

@app.route('/add', methods=['POST'])
def add():
    con=sqlite3.connect(DB); cur=con.cursor()
    cur.execute("INSERT INTO subs (name,phone,speed,status) VALUES (?,?,?,?)",(request.form['name'],request.form['phone'],request.form.get('speed',''),request.form.get('status','نشط')))
    sid=cur.lastrowid
    cur.execute("INSERT OR IGNORE INTO accounts (sub_id) VALUES (?)",(sid,))
    ip=request.form.get('ip','').strip()
    if ip:
        try: cur.execute("INSERT INTO ips (ip,sub_id) VALUES (?,?)",(ip,sid))
        except: pass
    con.commit(); con.close()
    if request.form.get('status')=='موقوف' and ip: mikrotik_block(ip,True)
    return redirect('/dashboard?view=subs')

@app.route('/add_ip', methods=['POST'])
def add_ip():
    con=sqlite3.connect(DB)
    try: con.execute("INSERT INTO ips (ip,note) VALUES (?,?)",(request.form['ip'],request.form.get('note','')))
    except: pass
    con.commit(); con.close()
    return redirect('/dashboard?view=ips')

@app.route('/charge/<int:sid>', methods=['POST'])
def charge(sid):
    try: u=float(request.form.get('usd') or 0)
    except: u=0
    try: s=float(request.form.get('syr') or 0)
    except: s=0
    con=sqlite3.connect(DB)
    con.execute("UPDATE accounts SET usd=usd+?, syr=syr+? WHERE sub_id=?",(u,s,sid))
    con.commit(); con.close()
    return redirect('/dashboard?view=accounts')

@app.route('/toggle/<int:sid>')
def toggle(sid):
    con=sqlite3.connect(DB)
    r=con.execute("SELECT status FROM subs WHERE id=?",(sid,)).fetchone()
    ip=con.execute("SELECT ip FROM ips WHERE sub_id=?",(sid,)).fetchone()
    if r:
        new='موقوف' if r[0]=='نشط' else 'نشط'
        con.execute("UPDATE subs SET status=? WHERE id=?",(new,sid)); con.commit()
        if ip: mikrotik_block(ip[0], new=='موقوف')
    con.close()
    return redirect('/dashboard?view=subs')

@app.route('/del/<int:sid>')
def delete(sid):
    con=sqlite3.connect(DB)
    con.execute("DELETE FROM subs WHERE id=?",(sid,)); con.execute("DELETE FROM accounts WHERE sub_id=?",(sid,)); con.execute("UPDATE ips SET sub_id=NULL WHERE sub_id=?",(sid,))
    con.commit(); con.close()
    return redirect('/dashboard?view=subs')

if __name__=='__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT',10000)))
