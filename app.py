from flask import Flask, request, redirect, session, jsonify, Response
from colors import COLORS, logo_html
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, datetime, json, html, subprocess, platform, ipaddress, shutil, threading, time
try: import psycopg2, psycopg2.extras
except: psycopg2=None
import sqlite3
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY","omia-sec-2026-CHANGE-ME")
DATABASE_URL = os.environ.get("DATABASE_URL","").strip().replace("postgresql://","postgres://")
USE_PG = bool(DATABASE_URL.startswith("postgres://") and psycopg2)
_pg=None
INSTA="https://www.instagram.com/af_20_1999/"
WA="https://wa.me/905344851045"

def backup_db():
    if not USE_PG and os.path.exists("omia.db"):
        os.makedirs("backups",exist_ok=True)
        try: shutil.copy("omia.db",f"backups/omia_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.db")
        except: pass
def _ab():
    while True:
        time.sleep(86400); backup_db()
threading.Thread(target=_ab,daemon=True).start()
def esc(s): return html.escape(str(s or ''),quote=True)
def db():
    global _pg
    if USE_PG:
        try:
            if _pg:
                c=_pg.cursor();c.execute("SELECT 1");c.close();return _pg
        except:
            try:_pg.close()
            except:pass
            _pg=None
        _pg=psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=5);_pg.autocommit=True;return _pg
    c=sqlite3.connect("omia.db",check_same_thread=False);c.row_factory=sqlite3.Row;return c
def cc(c):
    if not USE_PG:
        try:c.close()
        except:pass
def qall(q,a=()):
    c=db()
    try:
        if USE_PG:
            cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor);cur.execute(q.replace("?","%s"),a);r=[dict(x) for x in cur.fetchall()];cur.close();return r
        else:
            r=[dict(x) for x in c.execute(q,a).fetchall()];cc(c);return r
    except: cc(c);return []
def qone(q,a=()):
    r=qall(q,a);return r[0] if r else None
def qexec(q,a=()):
    c=db()
    try:
        if USE_PG: cur=c.cursor();cur.execute(q.replace("?","%s"),a);cur.close()
        else: c.execute(q,a);c.commit();cc(c)
    except Exception as e: print(e);cc(c)

def safe_alter(t,col,d):
    try:
        if USE_PG: qexec(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS {col} {d}")
        else:
            cols=qall(f"PRAGMA table_info({t})")
            if not any(x['name']==col for x in cols): qexec(f"ALTER TABLE {t} ADD COLUMN {col} {d}")
    except: pass

def init():
    ss=["CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,active INT DEFAULT 1,username TEXT)","CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,active INT DEFAULT 1)","CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,amount REAL,typ TEXT,dt TEXT,note TEXT,currency TEXT)","CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,lat REAL DEFAULT 0,lng REAL DEFAULT 0,dish_name TEXT,tower_name TEXT)","CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,lat REAL,lng REAL,location TEXT,fixed INT DEFAULT 0,area TEXT)","CREATE TABLE IF NOT EXISTS activity_log(id INTEGER PRIMARY KEY AUTOINCREMENT,time TEXT,action TEXT,phone TEXT,username TEXT)","CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,time TEXT,title TEXT,msg TEXT,read INT DEFAULT 0)","CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY,v TEXT)"]
    if USE_PG: ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
    for s in ss: qexec(s)
    safe_alter("activity_log","username","TEXT")
    if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)): qexec("INSERT INTO users(phone,password,role,username,active) VALUES(?,?,?,?,?)",('05344851045',generate_password_hash('admin2024'),'manager','admin',1))
    backup_db()
init()

def get_setting(k,d="1"):
    r=qone("SELECT v FROM settings WHERE k=?",(k,));return r['v'] if r else d
def add_log(a):
    ph=session.get('phone','system');u=qone("SELECT username FROM users WHERE phone=?",(ph,));un=u['username'] if u else ph
    qexec("INSERT INTO activity_log(time,action,phone,username) VALUES(?,?,?,?)",(datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),a,ph,un))
def login_required(f):
    @wraps(f)
    def w(*a,**kw):
        if not session.get('phone'): return redirect('/login')
        return f(*a,**kw)
    return w
def manager_required(f):
    @wraps(f)
    def w(*a,**kw):
        if not session.get('phone'): return redirect('/login')
        m=qone("SELECT * FROM users WHERE phone=?",(session.get('phone'),))
        if not m or m.get('role')=='tech': return "ممنوع",403
        return f(*a,**kw)
    return w
def me(): return qone("SELECT * FROM users WHERE phone=?",(session.get('phone'),))
def can_delete():
    if get_setting("allow_delete")=="0": return False
    m=me();return m and m['role']!='tech'
def is_internal_ip(ip):
    try:
        o=ipaddress.ip_address(ip.strip());return o.is_private and not o.is_loopback
    except: return False

@app.route('/api/ping')
@login_required
def api_ping():
    ip=request.args.get('ip','').strip()
    if not is_internal_ip(ip): return jsonify(ok=False,out='خارج الشبكة')
    try:
        win=platform.system().lower()=='windows';cmd=['ping','-n','2',ip] if win else ['ping','-c','2','-W','2',ip]
        o=subprocess.run(cmd,capture_output=True,text=True,timeout=4)
        return jsonify(ok=True,out=(o.stdout or '')[:1200])
    except Exception as e: return jsonify(ok=False,out=str(e)[:200])

@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        uin=request.form.get('userin','').strip();pw=request.form.get('password','')
        u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
        if u and check_password_hash(u['password'],pw):
            session['phone']=u['phone'];add_log(f"دخول {uin}");return redirect('/dash')
        return "<script>alert('خطأ بالدخول');location.href='/login'</script>"
    return f"""<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
    <style>body{{background:{COLORS['bg']};color:{COLORS['text']};font-family:sans-serif;text-align:center;padding:30px}}
    input{{padding:12px;margin:6px;width:280px;border-radius:10px;border:1px solid {COLORS['gold']};background:#1e1e1e;color:#fff;text-align:center}}
    button{{background:{COLORS['gold']};padding:12px 40px;border:0;border-radius:12px;font-weight:bold;font-size:16px;cursor:pointer}}</style></head>
    <body>{logo_html()}<h2 style='color:{COLORS['gold']}'>OMAIA ISP</h2>
    <form method=post id=lf>
    <input id=uin name=userin placeholder='يوزر / هاتف'><br>
    <input id=pw name=password type=password placeholder='كلمة السر' autocomplete="current-password"><br>
    <label style='display:flex;align-items:center;justify-content:center;gap:8px;margin:12px;color:#ccc;font-size:14px;cursor:pointer'>
    <input type=checkbox id=rm style='width:18px;height:18px'> حفظ كلمة السر على هذا الجهاز</label>
    <button>دخول</button></form>
    <div style='margin-top:25px'><div style='color:#aaa;font-size:14px;margin-bottom:8px'>الدعم الفني</div>
    <a href='{WA}' target=_blank style='font-size:34px;text-decoration:none'>💬</a></div>
    <script>
    window.onload=function(){{
      var u=localStorage.getItem('omia_u'); var p=localStorage.getItem('omia_p');
      if(u){{document.getElementById('uin').value=u;document.getElementById('rm').checked=true;}}
      if(p){{document.getElementById('pw').value=p;}}
    }};
    document.getElementById('lf').onsubmit=function(){{
      if(document.getElementById('rm').checked){{
        localStorage.setItem('omia_u',document.getElementById('uin').value);
        localStorage.setItem('omia_p',document.getElementById('pw').value);
      }}else{{localStorage.removeItem('omia_u');localStorage.removeItem('omia_p');}}
    }};
    </script></body></html>"""

@app.route('/logout')
def lo(): session.clear();return redirect('/login')

@app.route('/add_dish',methods=['POST'])
@login_required
def add_dish():
    qexec("INSERT INTO dish_ips(dish_name,ip,location) VALUES(?,?,?)",(request.form.get('dish_name'),request.form.get('ip'),request.form.get('location')))
    add_log(f"اضافة صحن {request.form.get('dish_name')}");return "ok"
@app.route('/del_dish/<int:id>')
@login_required
def del_dish(id):
    if not can_delete(): return "ممنوع",403
    qexec("DELETE FROM dish_ips WHERE id=?",(id,));return "ok"
@app.route('/add_sub',methods=['POST'])
@login_required
def add_sub():
    qexec("INSERT INTO subs(name,phone) VALUES(?,?)",(request.form.get('name'),request.form.get('phone')));return "ok"
@app.route('/del_sub/<int:id>')
@login_required
def del_sub(id):
    if not can_delete(): return "ممنوع",403
    qexec("DELETE FROM subs WHERE id=?",(id,));return "ok"
@app.route('/add_tower',methods=['POST'])
@login_required
def add_tower():
    qexec("INSERT INTO towers(name,lat,lng,location) VALUES(?,?,?,?)",(request.form.get('name'),request.form.get('lat'),request.form.get('lng'),request.form.get('location')));return "ok"
@app.route('/del_tower/<int:id>')
@login_required
def del_tower(id):
    if not can_delete(): return "ممنوع",403
    qexec("DELETE FROM towers WHERE id=?",(id,));return "ok"

def page_content(v):
    if v=='support':
        return f"""<div class=wrap><div class=card style='text-align:center;padding:35px'>
        <h2>🛠️ قسم الدعم الفني</h2><p style='color:#aaa'>تواصل معنا مباشرة</p>
        <div style='display:flex;gap:30px;justify-content:center;margin-top:20px'>
        <a href='{WA}' target=_blank style='font-size:52px;text-decoration:none'>💬<div style='font-size:14px;color:#25d366'>واتساب</div></a>
        <a href='{INSTA}' target=_blank style='font-size:52px;text-decoration:none'>📸<div style='font-size:14px;color:#e1306c'>انستجرام</div></a>
        </div></div></div>"""
    if v=='dishes':
        rows=qall("SELECT * FROM dish_ips ORDER BY id DESC")
        h="".join([f"<div class=card><b>{esc(r.get('dish_name'))}</b> - {esc(r.get('ip'))} <a href='/del_dish/{r['id']}'>🗑️</a></div>" for r in rows])
        return f"<div class=wrap><div class=card><h3>إضافة صحن</h3><form method=post action=/add_dish onsubmit=\"fetch(this.action,{{method:'POST',body:new FormData(this)}}).then(()=>location.reload());return false\"><input name=dish_name placeholder='اسم الصحن'><input name=ip placeholder='IP'><input name=location placeholder='الموقع'><button class=btn>حفظ</button></form></div>{h}</div>"
    dc=qone("SELECT COUNT(*) c FROM dish_ips")['c']
    sc=qone("SELECT COUNT(*) c FROM subs")['c']
    return f"<div class=wrap><div class=grid><div class=card><h3>📡 صحون</h3><h2>{dc}</h2></div><div class=card><h3>👥 مشتركين</h3><h2>{sc}</h2></div></div></div>"

def layout(c,v):
    return f"""<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
    <style>body{{background:{COLORS['bg']};color:{COLORS['text']};font-family:sans-serif;margin:0}}
   .nav{{background:#1a1a1a;padding:12px;display:flex;gap:12px;align-items:center}}
   .nav a{{color:{COLORS['text']};text-decoration:none;padding:8px 12px;background:#222;border-radius:8px}}
   .wrap{{padding:15px;max-width:900px;margin:auto}}.card{{background:#1e1e1e;padding:15px;border-radius:12px;margin:10px 0;border:1px solid #333}}
   .grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}.btn{{background:{COLORS['gold']};border:0;padding:10px 20px;border-radius:8px;font-weight:bold}}
    input{{padding:10px;margin:5px;border-radius:8px;border:1px solid #444;background:#111;color:#fff}}</style></head>
    <body><div class=nav>{logo_html()}<a href='/dash?v=home'>🏠</a><a href='/dash?v=dishes'>📡</a><a href='/dash?v=support'>🛠️ دعم</a><a href='/logout'>🚪</a></div>{c}</body></html>"""

@app.route('/dash')
@login_required
def dash():
    v=request.args.get('v','home')
    return layout(page_content(v),v)

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
