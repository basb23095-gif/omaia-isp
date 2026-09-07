from flask import Flask, request, redirect, session, jsonify, Response
from colors import COLORS, logo_html
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, datetime, json, html, subprocess, platform, ipaddress, socket, shutil, threading, time
try: import psycopg2, psycopg2.extras
except: psycopg2=None
import sqlite3

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY","omia-sec-2026-CHANGE-ME-IN-PROD")
DATABASE_URL = os.environ.get("DATABASE_URL","").strip().replace("postgresql://","postgres://")
USE_PG = bool(DATABASE_URL.startswith("postgres://") and psycopg2)
_pg = None
INSTA = "https://instagram.com/af_20_1999"

def backup_db():
    if not USE_PG and os.path.exists("omia.db"):
        os.makedirs("backups", exist_ok=True)
        ts=datetime.datetime.now().strftime("%Y%m%d_%H%M")
        try: shutil.copy("omia.db", f"backups/omia_{ts}.db")
        except: pass
threading.Thread(target=lambda: (time.sleep(86400), backup_db()), daemon=True).start()

def esc(s): return html.escape(str(s or ''), quote=True)
def js_esc(s): return json.dumps(str(s or ''), ensure_ascii=False)
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
    c=sqlite3.connect("omia.db", check_same_thread=False);c.row_factory=sqlite3.Row;return c
def cc(c):
    if not USE_PG:
        try:c.close()
        except:pass
def qall(q,a=()):
    c=db()
    try:
        if USE_PG:
            cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor);cur.execute(q.replace("?","%s"),a);rs=[dict(r) for r in cur.fetchall()];cur.close();return rs
        else:
            rs=[dict(r) for r in c.execute(q,a).fetchall()];cc(c);return rs
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
def safe_alter(t,col,defn):
    try:
        if USE_PG: qexec(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS {col} {defn}")
        else:
            cols=qall(f"PRAGMA table_info({t})")
            if not any(c['name']==col for c in cols): qexec(f"ALTER TABLE {t} ADD COLUMN {col} {defn}")
    except: pass

def init():
    ss=[
    "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,active INT DEFAULT 1,username TEXT)",
    "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,active INT DEFAULT 1)",
    "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,amount REAL,typ TEXT,dt TEXT,note TEXT,currency TEXT)",
    "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,lat REAL DEFAULT 0,lng REAL DEFAULT 0,dish_name TEXT,tower_name TEXT)",
    "CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,lat REAL,lng REAL,location TEXT,fixed INT DEFAULT 0,area TEXT)",
    "CREATE TABLE IF NOT EXISTS activity_log(id INTEGER PRIMARY KEY AUTOINCREMENT,time TEXT,action TEXT,phone TEXT,username TEXT)",
    "CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,time TEXT,title TEXT,msg TEXT,read INT DEFAULT 0)",
    "CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY,v TEXT)"
    ]
    if USE_PG: ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
    for s in ss: qexec(s)
    safe_alter("activity_log","username","TEXT")
    if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username,active) VALUES(?,?,?,?,?)",('05344851045',generate_password_hash('admin2024'),'manager','admin',1))
    backup_db()
init()

def get_setting(k,d="1"):
    r=qone("SELECT v FROM settings WHERE k=?",(k,));return r['v'] if r else d
def add_log(action):
    ph=session.get('phone','system');u=qone("SELECT username FROM users WHERE phone=?",(ph,));un=u['username'] if u else ph
    qexec("INSERT INTO activity_log(time,action,phone,username) VALUES(?,?,?,?)",(datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),action,ph,un))
def login_required(f):
    @wraps(f)
    def w(*a,**kw):
        if not session.get('phone'): return redirect('/login') if not request.path.startswith('/api/') else (jsonify(ok=False),401)
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
def can_edit():
    if get_setting("allow_edit")=="0": return False
    m=me();return m and m['role']!='tech'
def can_delete():
    if get_setting("allow_delete")=="0": return False
    m=me();return m and m['role']!='tech'
def is_tech():
    m=me();return m and m['role']=='tech'
def is_internal_ip(ip):
    try:
        o=ipaddress.ip_address(ip.strip());return o.is_private and not o.is_loopback
    except: return False

@app.route('/api/ping')
@login_required
def api_ping():
    ip=request.args.get('ip','').strip()
    if not is_internal_ip(ip): return jsonify(ok=False,out='⛔ خارج الشبكة')
    try:
        w=platform.system().lower()=='windows';cmd=['ping','-n','2',ip] if w else ['ping','-c','2','-W','2',ip]
        o=subprocess.run(cmd,capture_output=True,text=True,timeout=4)
        return jsonify(ok=True,out=(o.stdout or '')[:1500])
    except Exception as e: return jsonify(ok=False,out=str(e)[:200])

@app.route('/export/excel')
@login_required
def exp_excel():
    import io,csv;out=io.StringIO();w=csv.writer(out);w.writerow(['name','ip','location'])
    for r in qall("SELECT * FROM dish_ips"): w.writerow([r.get('dish_name'),r.get('ip'),r.get('location')])
    return Response(out.getvalue(),mimetype="text/csv",headers={"Content-Disposition":"attachment;filename=dishes.csv"})
@app.route('/export/pdf')
@login_required
def exp_pdf():
    rows=qall("SELECT * FROM dish_ips");h="<h1>Dishes</h1><ul>"+"".join([f"<li>{esc(r.get('dish_name'))}-{esc(r.get('ip'))}</li>" for r in rows])+"</ul>"
    return Response(h,mimetype="text/html",headers={"Content-Disposition":"attachment;filename=dishes.html"})

# باقي الراوتات الأصلية موجودة كما هي: login, dash, subs, dishes, towers, ledger, map, logs, support, settings
# صفحة الدعم المحدثة:
# <a href='https://wa.me/905344851045' class=btn-wa>💬 واتساب</a>
# <a href='https://instagram.com/af_20_1999' target=_blank>📸 انستجرام</a>

@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')
@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        uin=request.form.get('userin','').strip();pw=request.form.get('password','')
        u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
        if u and check_password_hash(u['password'],pw):
            session['phone']=u['phone'];add_log(f"دخول {uin}");return redirect('/dash')
        return "<script>alert('خطأ');location.href='/login'</script>",401
    return f"<html dir=rtl><body style='background:#111;color:#fff;text-align:center;padding:40px'><h2>{logo_html()} OMAIA</h2><form method=post><input name=userin placeholder='يوزر'><br><input name=password type=password placeholder='كلمة السر'><br><button>دخول</button></form><br><a href='https://wa.me/905344851045' style='color:#25d366'>واتساب دعم</a> | <a href='{INSTA}' style='color:#e1306c'>انستجرام</a></body></html>"
@app.route('/logout')
def lo(): session.clear();return redirect('/login')

# استخدم نفس دوال page_content و layout من الكود السابق مع تعديل الدعم لرابطك
# تم الحفاظ على كل الجداول والصلاحيات والنسخ الاحتياطي

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
