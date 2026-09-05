from flask import Flask, request, redirect, render_template_string, session, Response
import os, datetime, io, csv, time
from functools import lru_cache
try: import psycopg2, psycopg2.extras
except: psycopg2=None
import sqlite3

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY","omia-sec-2026")
DATABASE_URL = os.environ.get("DATABASE_URL","")
USE_PG = bool(DATABASE_URL and psycopg2)
_pg_conn=None; _pg_time=0

def get_colors():
    return {"bg":"#0b111e","card":"#1e293b","sidebar":"#111827","main":"#00D4FF","text":"#e2e8f0"}

@lru_cache(maxsize=1)
def get_colors_cached(): return get_colors()

def db():
    global _pg_conn,_pg_time
    if USE_PG:
        now=time.time()
        if _pg_conn and now-_pg_time<300:
            try: _pg_conn.cursor().execute("SELECT 1"); return _pg_conn
            except: pass
        _pg_conn=psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=5)
        _pg_conn.autocommit=True; _pg_time=now; return _pg_conn
    con=sqlite3.connect("omia.db"); con.row_factory=sqlite3.Row; return con

def close_con(con):
    if not USE_PG:
        try: con.close()
        except: pass

def ex(con,q,args=()):
    if USE_PG:
        cur=con.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(q.replace("?","%s"),args); return cur
    return con.execute(q,args)

def init():
    con=db()
    stmts=[
        "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,username TEXT,password TEXT,role TEXT,active INT DEFAULT 1)",
        "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,status TEXT)",
        "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,site TEXT)",
        "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,sub_id INT,date TEXT,usd REAL,syr REAL,note TEXT,by_user TEXT)",
        "CREATE TABLE IF NOT EXISTS servers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,host TEXT,username TEXT,password TEXT)",
        "CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,msg TEXT,date TEXT,by_user TEXT)"
    ]
    if USE_PG:
        stmts=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in stmts]
        cur=con.cursor()
        for s in stmts: cur.execute(s)
        cur.execute("SELECT * FROM users WHERE phone='05344851045'")
        if not cur.fetchone(): cur.execute("INSERT INTO users(phone,username,password,role,active) VALUES('05344851045','admin','admin2024','super',1)")
        con.commit(); cur.close()
    else:
        for s in stmts: con.execute(s)
        if not con.execute("SELECT * FROM users WHERE phone='05344851045'").fetchone():
            con.execute("INSERT INTO users(phone,username,password,role,active) VALUES('05344851045','admin','admin2024','super',1)")
        con.commit(); close_con(con)
init()

LAYOUT="""<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>OMIA ISP</title>
<style>
*{box-sizing:border-box;transition:all .25s cubic-bezier(.4,0,.2,1)}
body{font-family:Tahoma,Arial;margin:0;min-height:100vh;background:__BG__;color:__TEXT__;opacity:0;animation:fadeIn .4s ease forwards}
@keyframes fadeIn{to{opacity:1}}
@keyframes slideUp{from{opacity:0;transform:translateY(15px)}to{opacity:1;transform:none}}
.topbar{position:fixed;top:0;right:0;left:0;height:56px;background:rgba(17,24,39,.9);backdrop-filter:blur(12px);display:flex;align-items:center;justify-content:space-between;padding:0 12px;z-index:1002;border-bottom:1px solid rgba(0,212,255,.2)}
.sidebar{width:260px;padding:15px;position:fixed;top:56px;bottom:0;right:0;overflow-y:auto;background:__SIDEBAR__;transform:translateX(105%);transition:transform .35s cubic-bezier(.4,0,.2,1);z-index:1003;box-shadow:-10px 0 30px rgba(0,0,0,.3)}
.sidebar.open{transform:translateX(0)}
.sidebar a{display:flex;align-items:center;gap:10px;color:#fff;padding:12px;margin:6px 0;background:__CARD__;text-decoration:none;border-radius:10px;transform:translateX(20px);opacity:0;animation:slideUp .3s forwards}
.sidebar.open a:nth-child(2){animation-delay:.05s}.sidebar.open a:nth-child(3){animation-delay:.1s}.sidebar.open a:nth-child(4){animation-delay:.15s}.sidebar.open a:nth-child(5){animation-delay:.2s}
.sidebar a:hover{background:rgba(0,212,255,.15);transform:translateX(-4px)}
.sidebar a.active{background:linear-gradient(135deg,rgba(0,212,255,.3),rgba(0,212,255,.1));border:1px solid rgba(0,212,255,.4);color:__MAIN__}
.overlay{display:none;position:fixed;top:56px;left:0;right:0;bottom:0;background:rgba(0,0,0,.5);backdrop-filter:blur(2px);z-index:1001;opacity:0}
.overlay.show{display:block;opacity:1}
.main{padding:76px 16px 20px;max-width:1100px;margin:auto;animation:slideUp .4s ease}
.card{padding:14px;border-radius:14px;margin:10px 0;border:1px solid rgba(0,212,255,.15);background:rgba(30,41,59,.6);backdrop-filter:blur(8px);animation:slideUp .4s ease}
.card:hover{transform:translateY(-2px);box-shadow:0 8px 25px rgba(0,212,255,.1)}
table{width:100%;border-collapse:collapse;font-size:14px;background:rgba(30,41,59,.6);border-radius:12px;overflow:hidden}
th,td{padding:10px;border-bottom:1px solid #334155;text-align:center}
th{color:__MAIN__}
tr{transition:background .2s}
tr:hover{background:rgba(0,212,255,.05)}
input,select{width:100%;padding:10px;margin:5px 0;border-radius:10px;background:#0f172a;border:1px solid #334155;color:#fff}
input:focus{border-color:__MAIN__;box-shadow:0 0 0 2px rgba(0,212,255,.2);outline:none}
button{padding:11px;width:100%;border:none;border-radius:10px;font-weight:bold;cursor:pointer;background:linear-gradient(135deg,__MAIN__,#0090c0);color:#001}
button:hover{transform:translateY(-1px);box-shadow:0 5px 15px rgba(0,212,255,.3)}
button:active{transform:scale(.98)}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.stat-num{font-size:28px;font-weight:bold;color:__MAIN__}
@media(max-width:700px){.stats{grid-template-columns:1fr 1fr}}
.page-transition{opacity:0;transform:translateY(10px)}
</style></head><body>
<div class="topbar"><button onclick="toggleSide()" style="width:auto;padding:8px 14px">☰</button><b style="color:__MAIN__">✨ OMIA ISP</b><div><a href="/search" style="color:#fff;text-decoration:none;padding:8px">🔍</a><a href="/dash?view=notifs" style="color:#fff;text-decoration:none">🔔</a></div></div>
<div class="overlay" id="ovl" onclick="toggleSide()"></div>
<div class="sidebar" id="sdb"><h2 style="color:__MAIN__;text-align:center">OMIA ISP</h2>
<a href="/dash?view=home" data-v="home">🏠 الرئيسية</a>
<a href="/dash?view=subs" data-v="subs">👥 المشتركين</a>
<a href="/dash?view=dishes" data-v="dishes">📡 الصحون</a>
<a href="/dash?view=ledger" data-v="ledger">📒 الحسابات</a>
<a href="/dash?view=servers" data-v="servers">🖥️ سيرفرات</a>
<a href="/dash?view=settings" data-v="settings">⚙️ الإعدادات</a>
<a href="/logout">🚪 خروج</a></div>
<div class="main" id="mainc">{{content|safe}}</div>
<script>
function toggleSide(){document.getElementById('sdb').classList.toggle('open');document.getElementById('ovl').classList.toggle('show')}
document.addEventListener('click',e=>{
  let s=document.getElementById('sdb');
  if(s.classList.contains('open') && !s.contains(e.target) && !e.target.closest('button')) toggleSide();
});
// تنقل سلس بدون ريلود كامل
document.querySelectorAll('.sidebar a[data-v]').forEach(a=>{
  a.addEventListener('click',e=>{
    e.preventDefault();
    let url=a.href;
    document.getElementById('mainc').classList.add('page-transition');
    toggleSide();
    setTimeout(()=>{window.location.href=url},150);
  });
});
// تمييز القسم النشط
let v=new URLSearchParams(location.search).get('view')||'home';
document.querySelectorAll('[data-v]').forEach(a=>{if(a.dataset.v===v)a.classList.add('active')});
</script></body></html>"""

def render(c):
    col=get_colors_cached(); h=LAYOUT
    for k,v in col.items(): h=h.replace("__"+k.upper()+"__",v)
    return render_template_string(h,content=c)

@app.route('/')
def idx(): return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login',methods=['GET','POST'])
def login():
    msg=""
    if request.method=='POST':
        ident=request.form.get('phone','').strip(); pwd=request.form.get('password','')
        con=db(); u=ex(con,"SELECT * FROM users WHERE phone=? OR username=?",(ident,ident)).fetchone(); close_con(con)
        if u:
            d=dict(u)
            if d['password']==pwd:
                session['phone']=d['phone']; session['role']=d['role']
                return redirect('/dash?view=home')
            else: msg="<p style='color:#f87171'>كلمة السر خطأ</p>"
        else: msg="<p style='color:#f87171'>المستخدم غير موجود</p>"
    return render(f"<div class='card' style='max-width:380px;margin:40px auto;text-align:center'><h2 style='color:#00D4FF'>✨ OMIA ISP</h2>{msg}<form method='post'><input name='phone' placeholder='مستخدم / هاتف' required><input name='password' type='password' placeholder='كلمة السر' required><button>دخول</button></form></div>")

@app.route('/logout')
def logout(): session.clear(); return redirect('/login')

@app.route('/dash')
def dash():
    if not session.get('phone'): return redirect('/login')
    v=request.args.get('view','home'); con=db()
    def done(h):
        r=render(h); close_con(con); return r
    if v=='home':
        ns=len(ex(con,"SELECT id FROM subs").fetchall())
        nd=len(ex(con,"SELECT id FROM dish_ips").fetchall())
        nu=len(ex(con,"SELECT phone FROM users").fetchall())
        nl=len(ex(con,"SELECT id FROM ledger").fetchall())
        return done(f"<div class='stats'><div class='card'><div class='stat-num'>{ns}</div>مشتركين</div><div class='card'><div class='stat-num'>{nd}</div>صحون</div><div class='card'><div class='stat-num'>{nu}</div>مستخدمين</div><div class='card'><div class='stat-num'>{nl}</div>قيود</div></div><div class='card' style='text-align:center'><h3>مرحباً بك في OMIA ISP</h3><p style='color:#94a3b8'>نظام سلس وسريع</p></div>")
    if v=='subs':
        rows=ex(con,"SELECT * FROM subs").fetchall()
        tr="".join([f"<tr><td>{r['name']}</td><td>{r['phone']}</td><td>{r['status']}</td><td><a href='/del_sub/{r['id']}'>حذف</a></td></tr>" for r in rows])
        return done(f"<div class='card'><form method='post' action='/add_sub'><input name='name' placeholder='الاسم' required><input name='phone' placeholder='هاتف' required><button>إضافة مشترك</button></form></div><table><tr><th>الاسم</th><th>هاتف</th><th>حالة</th><th></th></tr>{tr}</table>")
    if v=='dishes':
        rows=ex(con,"SELECT * FROM dish_ips").fetchall()
        tr="".join([f"<tr><td>{r['location']}</td><td><a href='http://{r['ip']}' target='_blank' style='color:#00D4FF' dir='ltr'>{r['ip']}</a></td><td><a href='/del_dish/{r['id']}'>حذف</a></td></tr>" for r in rows])
        return done(f"<div class='card'><form method='post' action='/add_dish'><input name='location' placeholder='اسم الموقع' required><input name='ip' placeholder='IP' dir='ltr' required><input name='site' placeholder='البرج / المنطقة'><button>إضافة صحن</button></form></div><div class='card'><input placeholder='🔍 بحث...' oninput=\"document.querySelectorAll('table tr').forEach((x,i)=>{{if(i==0)return;x.style.display=x.innerText.includes(this.value)?'':'none'}})\"></div><table><tr><th>الموقع</th><th>IP</th><th></th></tr>{tr}</table>")
    if v=='ledger':
        rows=ex(con,"SELECT l.*,s.name FROM ledger l LEFT JOIN subs s ON s.id=l.sub_id ORDER BY l.id DESC LIMIT 100").fetchall()
        subs=ex(con,"SELECT id,name FROM subs").fetchall()
        opts="".join([f"<option value='{s['id']}'>{s['name']}</option>" for s in subs])
        tr="".join([f"<tr><td>{r['name']}</td><td>{r['usd']}</td><td>{r['syr']}</td><td>{r['date']}</td></tr>" for r in rows])
        return done(f"<div class='card'><form method='post' action='/charge'><select name='sub_id'>{opts}</select><input name='amount' type='number' step='0.01' placeholder='المبلغ' required><select name='currency'><option value='usd'>دولار $</option><option value='syr'>سوري ل.س</option></select><input name='note' placeholder='ملاحظة'><button>⚡ شحن</button></form></div><table><tr><th>الشخص</th><th>$</th><th>ل.س</th><th>تاريخ</th></tr>{tr}</table>")
    if v=='servers':
        rows=ex(con,"SELECT * FROM servers").fetchall()
        tr="".join([f"<tr><td>{r['name']}</td><td dir='ltr'>{r['host']}</td></tr>" for r in rows])
        return done(f"<div class='card'><form method='post' action='/add_srv'><input name='name' placeholder='اسم' required><input name='host' placeholder='host' dir='ltr' required><button>إضافة</button></form></div><table>{tr}</table>")
    if v=='settings':
        users=ex(con,"SELECT * FROM users").fetchall()
        tr="".join([f"<tr><td>{u['username']}</td><td>{u['phone']}</td><td>{u['password']}</td></tr>" for u in users])
        return done(f"<div class='card'><form method='post' action='/add_user'><input name='username' placeholder='مستخدم' required><input name='phone' placeholder='هاتف' required><input name='password' placeholder='باسورد' required><button>إضافة يوزر</button></form></div><table><tr><th>مستخدم</th><th>هاتف</th><th>باسورد</th></tr>{tr}</table>")
    close_con(con); return redirect('/dash?view=home')

@app.route('/search')
def search():
    if not session.get('phone'): return redirect('/login')
    q=request.args.get('q',''); con=db()
    rows=ex(con,"SELECT * FROM subs WHERE name LIKE ? OR phone LIKE ?", (f"%{q}%",f"%{q}%")).fetchall() if q else []
    close_con(con)
    tr="".join([f"<tr><td>{r['name']}</td><td>{r['phone']}</td></tr>" for r in rows])
    return render(f"<div class='card'><form><input name='q' value='{q}' placeholder='بحث...'><button>بحث</button></form></div><table>{tr}</table>")

@app.route('/add_sub',methods=['POST'])
def add_sub():
    con=db(); ex(con,"INSERT INTO subs(name,phone,status) VALUES(?,?,?)",(request.form['name'],request.form['phone'],'نشط')); con.commit(); close_con(con); return redirect('/dash?view=subs')
@app.route('/del_sub/<int i>')
def del_sub(i): con=db(); ex(con,"DELETE FROM subs WHERE id=?",(i,)); con.commit(); close_con(con); return redirect('/dash?view=subs')
@app.route('/add_dish',methods=['POST'])
def add_dish(): con=db(); ex(con,"INSERT INTO dish_ips(ip,location,site) VALUES(?,?,?)",(request.form['ip'],request.form['location'],request.form.get('site',''))); con.commit(); close_con(con); return redirect('/dash?view=dishes')
@app.route('/del_dish/<int i>')
def del_dish(i): con=db(); ex(con,"DELETE FROM dish_ips WHERE id=?",(i,)); con.commit(); close_con(con); return redirect('/dash?view=dishes')
@app.route('/add_srv',methods=['POST'])
def add_srv(): con=db(); ex(con,"INSERT INTO servers(name,host,username,password) VALUES(?,?,?,?)",(request.form['name'],request.form['host'],'u','p')); con.commit(); close_con(con); return redirect('/dash?view=servers')
@app.route('/add_user',methods=['POST'])
def add_user():
    con=db()
    try: ex(con,"INSERT INTO users(phone,username,password,role,active) VALUES(?,?,?,?,1)",(request.form['phone'],request.form['username'],request.form['password'],'tech')); con.commit()
    except: pass
    close_con(con); return redirect('/dash?view=settings')
@app.route('/charge',methods=['POST'])
def charge():
    sid=request.form['sub_id']; amt=float(request.form['amount']); cur=request.form['currency']
    usd=amt if cur=='usd' else 0; syr=amt if cur=='syr' else 0
    con=db(); ex(con,"INSERT INTO ledger(sub_id,date,usd,syr,note,by_user) VALUES(?,?,?,?,?,?)",(sid,datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),usd,syr,request.form.get('note',''),session.get('phone'))); con.commit(); close_con(con)
    return redirect('/dash?view=ledger')

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
