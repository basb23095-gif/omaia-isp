from flask import Flask,request,redirect,render_template_string,session,send_from_directory
import os,sqlite3,time
from datetime import datetime
try: import psycopg2,psycopg2.extras
except: psycopg2=None
try: import pandas as pd
except: pd=None
from colors import get_colors
app=Flask(__name__);app.secret_key=os.environ.get("SECRET_KEY","omaia-sec")
DBURL=os.environ.get("DATABASE_URL","");USE_PG=bool(DBURL and psycopg2)
WA_DISPLAY="0095344851045";WA_LINK="963544851045"
_pg=None;_pt=0
def db():
 global _pg,_pt
 if USE_PG:
  if _pg and time.time()-_pt<280:
   try:_pg.cursor().execute("SELECT 1");return _pg
   except:pass
  import psycopg2 as p;_pg=p.connect(DBURL,sslmode='require');_pg.autocommit=True;_pt=time.time();return _pg
 c=sqlite3.connect("omaia.db",check_same_thread=False);c.row_factory=sqlite3.Row;return c
def close(c):
 if not USE_PG:
  try:c.close()
  except:pass
def ex(c,q,a=()):
 if USE_PG:
  cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor);cur.execute(q.replace("?","%s"),a);return cur
 return c.execute(q,a)
def init():
 c=db()
 qs=["CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,username TEXT,password TEXT,role TEXT,active INT)","CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,status TEXT)","CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,name TEXT,network TEXT,tower TEXT)","CREATE TABLE IF NOT EXISTS servers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,ip TEXT,location TEXT)","CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,date TEXT,sub TEXT,amount REAL,currency TEXT,note TEXT)"]
 if USE_PG:
  cur=c.cursor()
  for q in qs:cur.execute(q.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY"))
  cur.execute("SELECT 1 FROM users WHERE phone='05344851045'")
  if not cur.fetchone():
   cur.execute("INSERT INTO users VALUES('05344851045','05344851045','admin2024','super',1)")
  else:
   cur.execute("UPDATE users SET password='admin2024', active=1, username='05344851045' WHERE phone='05344851045'")
  c.commit();cur.close();return
 for q in qs:c.execute(q)
 for t,col in [("dish_ips","name"),("dish_ips","network"),("dish_ips","tower"),("ledger","amount"),("ledger","currency")]:
  try:c.execute(f"SELECT {col} FROM {t} LIMIT 1")
  except:
   try:c.execute(f"ALTER TABLE {t} ADD COLUMN {col} TEXT");c.commit()
   except:pass
 if not c.execute("SELECT 1 FROM users WHERE phone='05344851045'").fetchone():
  c.execute("INSERT INTO users VALUES('05344851045','05344851045','admin2024','super',1)")
 else:
  c.execute("UPDATE users SET password='admin2024', active=1, username='05344851045' WHERE phone='05344851045'")
 c.commit()
 close(c)
init()
@app.after_request
def hdr(r):
 r.headers['Cache-Control']='public,max-age=86400' if request.path.endswith('bg.jpg') else 'no-store'
 return r
@app.route('/bg.jpg')
def bg():
 try:return send_from_directory('static','bg.jpg')
 except:return send_from_directory('.','bg.jpg')

TR={"ar":{"home":"الرئيسية","subs":"المشتركين","dishes":"الصحون","servers":"السيرفرات","ledger":"دفتر الحسابات","settings":"الإعدادات"},"en":{"home":"Home","subs":"Subscribers","dishes":"Dishes","servers":"Servers","ledger":"Ledger","settings":"Settings"}}
def T(k):
 return TR.get(session.get('lang','ar'),TR['ar']).get(k,k)

CSS = """*{box-sizing:border-box}html{scroll-behavior:smooth}body{font-family:'Segoe UI',Arial;margin:0;background:BG;color:TEXT;animation:pageIn 1s cubic-bezier(.22,1,.36,1)}"""

# تم تصحيح طريقة دمج المتغير WA_LINK هنا في أسطر روابط الواتساب بالأسفل
LAY = """<!DOCTYPE html><html dir=rtl><head><meta charset=UTF-8><meta name=viewport content="width=device-width,initial-scale=1.0"></head><body>
<div class="tx"><div style="display:flex;gap:10px;align-items:center"><div class="menubtn" onclick="document.getElementById('dr').classList.add('open');document.getElementById('ov').style='display:flex;gap:10px;align-items:center'"><span class="logo" style="color:#00D4FF">&#00D4FF;</span><span> OMAIA ISP </span></div></div></div>
<div id="ov" class="overlay" onclick="document.getElementById('dr').classList.remove('open');this.style=''"></div>
<div id="dr" class="drawer"><a onclick="go('/dash?view=home')"> _HOME_ </a><a onclick="go('/dash?view=subs')"> _SUBS_ </a><a onclick="go('/dash?view=dishes')"> _DISHES_ </a><a onclick="go('/dash?view=servers')"> _SERVERS_ </a><a onclick="go('/dash?view=ledger')"> _LEDGER_ </a></div>
<div class="m" id="main">{{c|safe}}</div><div class="foot"> تصميم م. عبدو عمايا <br><a href="https://wa.me""" + WA_LINK + """" target="_blank"> تواصل معنا عبر الواتساب </a>
<a class="wa" href="https://wa.me""" + WA_LINK + """" target="_blank"></a></div>
<script>if(localStorage.getItem('th')=='1'){document.body.classList.add('Light');}async function go(u){"""

def R(h):
    s = LAY; co = get_colors()
    for k, v in co.items(): s = s.replace("_" + k + "_", v)
    s = s.replace("_HOME_", T("home")).replace("_SUBS_", T("subs")).replace("_DISHES_", T("dishes")).replace("_SERVERS_", T("servers")).replace("_LEDGER_", T("ledger"))
    if request.headers.get('X-Requested-With') == 'Fetch':
        return render_template_string(h)
    return render_template_string(s, c=h)

def gv(r):
    try:
        if hasattr(r, 'keys'): return r[r.keys()[0]]
        if isinstance(r, dict): return list(r.values())[0]
        return r[0]
    except: return 0

def title(t, icon): return f"<div class=pt>{icon} {t}</div>"

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        i = request.form.get('phone', '').strip()
        c = db()
        u = ex(c, "SELECT * FROM users WHERE phone=? OR username=?", (i, i))
        
        # تم إصلاح الخطأ هنا لجلب السجل الأول بشكل متوافق مع SQLite و PostgreSQL بأمان
                d = u.fetchone() if hasattr(u, 'fetchone') else (u[0] if u else None)
        if d and d['password'] == request.form.get('password') and d['active']:
            session['p'] = d['phone']
            return redirect('/dash')
        return R("<div class='c' style='width:320px;text-align:center'><p style='color:red'>خطأ في اسم المستخدم أو كلمة المرور</p><a href='/'>إعادة المحاولة</a></div>", "lb")
        
    return R("<div class='c' style='width:330px;text-align:center'><h2 style='color:#00D4FF'><span class='logo'>&#00D4FF;</span> OMAIA ISP</h2><form method='post'><input name='phone' placeholder='اسم / رقم هاتف' required><input name='password' type='password' placeholder='كلمة المرور' required><button>دخول</button></form></div>", "lb")

@app.route('/logout')
def lo():
    session.clear()
    return redirect('/')

@app.route('/lang/toggle')
def lt():
    cur = session.get('lang', 'ar')
    session['lang'] = 'en' if cur == 'ar' else 'ar'
    session.modified = True
    # حماية المسار في حال كان الـ referrer فارغاً لمنع خطأ الـ URL الـ مكسور
    ref = request.referrer
    return redirect(ref if ref else '/dash')

@app.route('/reset!')
def reset():
    c = db()
    cur = ex(c, "UPDATE users SET password='admin2024', active=1 WHERE phone='05344851045'", ())
    # إغلاق الكرسر لـ PostgreSQL لضمان حقن التعديل في السيرفر السحابي بأمان
    if hasattr(cur, 'close'): 
        cur.close()
    else:
        c.commit()
    return "تم التصفير: 05344851045 / admin2024"
