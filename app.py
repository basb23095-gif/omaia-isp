from flask import Flask,request,redirect,render_template_string,session,send_from_directory
import os,sqlite3,time
try: import psycopg2,psycopg2.extras
except: psycopg2=None
try: import pandas as pd
except: pd=None
from colors import get_colors

app=Flask(__name__)
app.secret_key=os.environ.get("SECRET_KEY","omaia-sec")
DBURL=os.environ.get("DATABASE_URL","")
USE_PG=bool(DBURL and psycopg2)
WA="905344851045"
_pg=None;_pt=0

def db():
 global _pg,_pt
 if USE_PG:
  if _pg and time.time()-_pt<280:
   try: _pg.cursor().execute("SELECT 1");return _pg
   except: pass
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
 qs=["CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,username TEXT,password TEXT,role TEXT,active INT)",
 "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,status TEXT)",
 "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,region TEXT,site TEXT)",
 "CREATE TABLE IF NOT EXISTS servers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,ip TEXT,location TEXT)",
 "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,date TEXT,sub TEXT,usd REAL,syr REAL,note TEXT)"]
 if USE_PG:
  cur=c.cursor()
  for q in qs: cur.execute(q.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY"))
  cur.execute("SELECT 1 FROM users WHERE phone='05344851045'")
  if not cur.fetchone(): cur.execute("INSERT INTO users VALUES('05344851045','05344851045','admin2024','super',1)")
  c.commit();cur.close();return
 for q in qs: c.execute(q)
 try: c.execute("SELECT region FROM dish_ips LIMIT 1")
 except:
  try: c.execute("ALTER TABLE dish_ips ADD COLUMN region TEXT");c.commit()
  except:pass
 if not c.execute("SELECT 1 FROM users WHERE phone='05344851045'").fetchone():
  c.execute("INSERT INTO users VALUES('05344851045','05344851045','admin2024','super',1)");c.commit()
 close(c)
init()

@app.after_request
def hdr(r):
 if request.path.startswith('/static') or request.path=='/bg.jpg':
  r.headers['Cache-Control']='public, max-age=86400'
 else: r.headers['Cache-Control']='no-store'
 return r

@app.route('/bg.jpg')
def bg():
 try: return send_from_directory('static','bg.jpg')
 except: return send_from_directory('.','bg.jpg')

CSS="body{font-family:Arial;margin:0;background:__BG__;color:__TEXT__}body.lb{background:linear-gradient(rgba(5,11,24,.65),rgba(5,11,24,.75)),url('/bg.jpg') center/cover fixed,__BG__;min-height:100vh;display:flex;align-items:center;justify-content:center}.t{position:fixed;top:0;left:0;right:0;height:52px;background:__SIDEBAR__;display:flex;align-items:center;justify-content:space-between;padding:0 12px;z-index:9;border-bottom:1px solid __MAIN__}.m{padding:62px 10px;max-width:1050px;margin:auto}.c{background:__CARD__;border:1px solid __MAIN__;border-radius:12px;padding:12px;margin:8px 0}button{background:__MAIN__;border:0;padding:9px;width:100%;border-radius:8px;font-weight:bold;cursor:pointer;color:#001}input,select{width:100%;padding:8px;margin:4px 0;border-radius:8px;border:1px solid #334155;background:#0f172a;color:#fff;box-sizing:border-box}table{width:100%;border-collapse:collapse}td,th{padding:7px;border-bottom:1px solid #334155;text-align:center;font-size:14px}th{color:__MAIN__}.g4{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.g2{display:grid;grid-template-columns:1fr 1fr;gap:8px}@media(max-width:700px){.g4{grid-template-columns:1fr 1fr}.g2{grid-template-columns:1fr}}.n a{color:#fff;margin:0 6px;text-decoration:none;font-size:16px}"
LAY="<!DOCTYPE html><html dir=rtl><head><meta charset=UTF-8><meta name=viewport content='width=device-width,initial-scale=1'><title>OMAIA</title><style>"+CSS+"</style></head><body class=__BC__><div class=t><b style=color:__MAIN__>OMAIA ISP</b><div class=n><a href=/dash title='الرئيسية'>🏠</a><a href=/dash?view=subs title='المشتركين'>👥</a><a href=/dash?view=dishes title='صحون'>📡</a><a href=/dash?view=servers title='سيرفرات'>🖥️</a><a href=/dash?view=ledger title='دفتر'>📒</a><a href=/dash?view=settings title='ضبط'>⚙️</a><a href=/logout>🚪</a></div></div><div class=m>{{c|safe}}</div></body></html>"

def R(h,bc=""):
 s=LAY;co=get_colors()
 for k,v in co.items(): s=s.replace("__"+k+"__",v)
 return render_template_string(s.replace("__BC__",bc),c=h)
def gv(r):
 try: return list(dict(r).values())[0]
 except: return r[0] if r else 0

@app.route('/',methods=['GET','POST'])
def login():
 if request.method=='POST':
  i=request.form.get('phone','').strip();c=db()
  u=ex(c,"SELECT * FROM users WHERE phone=? OR username=?",(i,i)).fetchone()
  d=dict(u) if u else None;close(c)
  if d and d['password']==request.form.get('password') and d['active']:
   session['p']=d['phone'];session['r']=d['role'];session['lang']=session.get('lang','ar');return redirect('/dash')
  return R("<div class=c style='width:320px;text-align:center'><p style=color:red>خطأ بالدخول</p><a href=/>رجوع</a></div>","lb")
 return R("<div class=c style='width:320px;text-align:center'><h2 style=color:#00D4FF>OMAIA ISP</h2><form method=post><input name=phone placeholder='رقم هاتف / اسم مستخدم' required><input name=password type=password placeholder='باسورد' required><button>دخول</button></form></div>","lb")

@app.route('/logout')
def lo(): session.clear();return redirect('/')
@app.route('/lang/<l>')
def lang(l): session['lang']=l;return redirect(request.referrer or '/dash')

@app.route('/dash')
def dash():
 if 'p' not in session: return redirect('/')
 v=request.args.get('view','home');page=int(request.args.get('page',1));per=20;off=(page-1)*per
 c=db();M=get_colors()['MAIN']
 def F(h): r=R(h);close(c);return r
 # 3 الرئيسية فيها معلومات
 if v=='home':
  ns=gv(ex(c,"SELECT COUNT(*)k FROM subs").fetchone());nd=gv(ex(c,"SELECT COUNT(*)k FROM dish_ips").fetchone());nl=gv(ex(c,"SELECT COUNT(*)k FROM ledger").fetchone());nu=gv(ex(c,"SELECT COUNT(*)k FROM users").fetchone())
  ls=ex(c,"SELECT * FROM subs ORDER BY id DESC LIMIT 5").fetchall();ld=ex(c,"SELECT * FROM dish_ips ORDER BY id DESC LIMIT 5").fetchall()
  ts="".join(f"<tr><td>{dict(x).get('name')}</td><td>{dict(x).get('phone')}</td></tr>" for x in ls)
  td="".join(f"<tr><td>{dict(x).get('location')}</td><td>{dict(x).get('region','')}</td><td dir=ltr>{dict(x).get('ip')}</td></tr>" for x in ld)
  return F(f"<div class=g4><div class=c style=text-align:center><h2 style=color:{M}>{ns}</h2>👥 مشتركين</div><div class=c style=text-align:center><h2 style=color:{M}>{nd}</h2>📡 صحون</div><div class=c style=text-align:center><h2 style=color:{M}>{nl}</h2>📒 دفتر</div><div class=c style=text-align:center><h2 style=color:{M}>{nu}</h2>👤 يوزرات</div></div><div class=g2><div class=c><b>آخر المشتركين</b><table>{ts}</table></div><div class=c><b>آخر الصحون</b><table>{td}</table></div></div>")
 # 4 المشتركين تعديل منها
 if v=='subs':
  q=request.args.get('q','')
  if q: rows=ex(c,"SELECT * FROM subs WHERE name LIKE? OR phone LIKE? ORDER BY id DESC LIMIT 50",(f"%{q}%",f"%{q}%")).fetchall()
  else: rows=ex(c,"SELECT * FROM subs ORDER BY id DESC LIMIT? OFFSET?",(per,off)).fetchall()
  tr="".join(f"<tr><td>{dict(x).get('name')}</td><td>{dict(x).get('phone')}</td><td><a href=/edit_sub/{dict(x)['id']}>✏️</a> <a href=/del_sub/{dict(x)['id']}>🗑️</a></td></tr>" for x in rows)
  return F(f"<div class=c><form><input name=q value='{q}' placeholder='بحث سريع'><input type=hidden name=view value=subs><button>بحث</button></form><form method=post action=/add_sub><div style=display:flex;gap:6px><input name=name placeholder='اسم' required><input name=phone placeholder='هاتف'><button style=width:auto>+</button></div></form></div><div class=c><table><tr><th>اسم</th><th>هاتف</th><th>تعديل</th></tr>{tr}</table></div>")
 # 5 صحون + منطقة
 if v=='dishes':
  rows=ex(c,"SELECT * FROM dish_ips ORDER BY id DESC LIMIT 50").fetchall()
  tr="".join(f"<tr><td>{dict(x).get('location')}</td><td>{dict(x).get('region','')}</td><td dir=ltr>{dict(x).get('ip')}</td><td><a href=/del_dish/{dict(x)['id']}>🗑️</a></td></tr>" for x in rows)
  return F(f"<div class=c><h3>📡 صحون</h3><form method=post action=/add_dish><input name=location placeholder='اسم الشبكة' required><input name=region placeholder='المنطقة'><input name=ip placeholder='IP' dir=ltr required><button>+ إضافة صحن</button></form></div><div class=c><table><tr><th>شبكة</th><th>المنطقة</th><th>IP</th><th></th></tr>{tr}</table></div>")
 if v=='servers':
  rows=ex(c,"SELECT * FROM servers ORDER BY id DESC LIMIT 50").fetchall()
  tr="".join(f"<tr><td>{dict(x).get('name')}</td><td dir=ltr>{dict(x).get('ip')}</td><td>{dict(x).get('location')}</td><td><a href=/del_server/{dict(x)['id']}>🗑️</a></td></tr>" for x in rows)
  return F(f"<div class=c><h3>🖥️ سيرفرات</h3><form method=post action=/add_server><input name=name placeholder='اسم السيرفر' required><input name=ip placeholder='IP' dir=ltr><input name=location placeholder='الموقع'><button>+ سيرفر</button></form></div><div class=c><table><tr><th>اسم</th><th>IP</th><th>موقع</th><th></th></tr>{tr}</table></div>")
 # 6 دفتر شغال + اكسل
 if v=='ledger':
  rows=ex(c,"SELECT * FROM ledger ORDER BY id DESC LIMIT 50").fetchall()
  tr="".join(f"<tr><td>{dict(x).get('date')}</td><td>{dict(x).get('sub')}</td><td>{dict(x).get('usd')}</td><td>{dict(x).get('syr')}</td><td><a href=/del_ledger/{dict(x)['id']}>🗑️</a></td></tr>" for x in rows)
  return F(f"<div class=c><h3>📒 دفتر الحسابات</h3><form method=post action=/add_ledger><div style=display:flex;gap:6px><input name=date type=date required><input name=sub placeholder='مشترك'></div><div style=display:flex;gap:6px><input name=usd type=number step=0.01 placeholder='$'><input name=syr type=number placeholder='ل.س'></div><input name=note placeholder='ملاحظة'><button>+ قيد</button></form><form method=post action=/upload_ledger enctype=multipart/form-data><input type=file name=file accept=.xlsx,.xls required><button>📤 رفع اكسل</button></form></div><div class=c><table><tr><th>تاريخ</th><th>مشترك</th><th>$</th><th>ل.س</th><th></th></tr>{tr}</table></div>")
 # ضبط: اعدادات + يوزرات + لغة
 if v=='settings':
  us=ex(c,"SELECT * FROM users LIMIT 100").fetchall()
  tr="".join(f"<tr><td dir=ltr>{dict(x).get('username')} {'❌' if not dict(x).get('active') else ''}</td><td>{dict(x).get('role')}</td><td><a href=/edit_user/{dict(x)['phone']}>✏️</a> <a href=/toggle_user/{dict(x)['phone']}>🔄</a> <a href=/del_user/{dict(x)['phone']}>🗑️</a></td></tr>" for x in us)
  return F(f"<div class=c><h3>⚙️ الإعدادات</h3><p>اللغة: {session.get('lang','ar')} <a href=/lang/ar>عربي</a> | <a href=/lang/en>EN</a></p><a href='https://wa.me/{WA}' target=_blank><button>واتساب</button></a></div><div class=c><h3>👤 اليوزرات - رقم هاتف / اسم مستخدم</h3><form method=post action=/add_user><div style=display:flex;gap:6px><input name=ident placeholder='هاتف / مستخدم' required><input name=password placeholder='باسورد' required><select name=role style=width:auto><option value=tech>فني</option><option value=super>super</option></select><button style=width:auto>+</button></div></form><table><tr><th>يوزر</th><th>دور</th><th>تحكم (تعديل/تفعيل)</th></tr>{tr}</table></div><div class=c><h3>🌐 اللغة</h3><a href=/lang/ar><button>عربي</button></a><a href=/lang/en><button>English</button></a></div>")
 return F("")

@app.route('/add_sub',methods=['POST'])
def a1():c=db();ex(c,"INSERT INTO subs(name,phone,status)VALUES(?,?,'active')",(request.form.get('name'),request.form.get('phone')));c.commit();close(c);return redirect('/dash?view=subs')
@app.route('/edit_sub/<int:i>',methods=['GET','POST'])
def e1(i):
 c=db()
 if request.method=='POST':ex(c,"UPDATE subs SET name=?,phone=? WHERE id=?",(request.form.get('name'),request.form.get('phone'),i));c.commit();close(c);return redirect('/dash?view=subs')
 r=dict(ex(c,"SELECT * FROM subs WHERE id=?",(i,)).fetchone());close(c)
 return R(f"<div class=c><h3>تعديل مشترك</h3><form method=post><input name=name value='{r['name']}' required><input name=phone value='{r['phone']}'><button>حفظ</button></form></div>")
@app.route('/del_sub/<int:i>')
def d1(i):c=db();ex(c,"DELETE FROM subs WHERE id=?",(i,));c.commit();close(c);return redirect('/dash?view=subs')
@app.route('/add_dish',methods=['POST'])
def a2():c=db();ex(c,"INSERT INTO dish_ips(ip,location,region,site)VALUES(?,?,?,?)",(request.form.get('ip'),request.form.get('location'),request.form.get('region',''),''));c.commit();close(c);return redirect('/dash?view=dishes')
@app.route('/del_dish/<int:i>')
def d2(i):c=db();ex(c,"DELETE FROM dish_ips WHERE id=?",(i,));c.commit();close(c);return redirect('/dash?view=dishes')
@app.route('/add_server',methods=['POST'])
def asv():c=db();ex(c,"INSERT INTO servers(name,ip,location)VALUES(?,?,?)",(request.form.get('name'),request.form.get('ip'),request.form.get('location')));c.commit();close(c);return redirect('/dash?view=servers')
@app.route('/del_server/<int:i>')
def dsv(i):c=db();ex(c,"DELETE FROM servers WHERE id=?",(i,));c.commit();close(c);return redirect('/dash?view=servers')
@app.route('/add_ledger',methods=['POST'])
def a3():c=db();ex(c,"INSERT INTO ledger(date,sub,usd,syr,note)VALUES(?,?,?,?,?)",(request.form.get('date'),request.form.get('sub'),float(request.form.get('usd') or 0),float(request.form.get('syr') or 0),request.form.get('note')));c.commit();close(c);return redirect('/dash?view=ledger')
@app.route('/del_ledger/<int:i>')
def d3(i):c=db();ex(c,"DELETE FROM ledger WHERE id=?",(i,));c.commit();close(c);return redirect('/dash?view=ledger')
@app.route('/upload_ledger',methods=['POST'])
def u3():
 if not pd: return "ثبت pandas+openpyxl"
 f=request.files.get('file')
 if f:
  df=pd.read_excel(f);c=db()
  for _,r in df.iterrows(): ex(c,"INSERT INTO ledger(date,sub,usd,syr,note)VALUES(?,?,?,?,?)",(str(r.get('date','')),str(r.get('sub','')),float(r.get('usd',0) or 0),float(r.get('syr',0) or 0),str(r.get('note',''))))
  c.commit();close(c)
 return redirect('/dash?view=ledger')
@app.route('/add_user',methods=['POST'])
def a4():
 c=db();i=request.form.get('ident','').strip()
 if i:
  try: ex(c,"INSERT INTO users(phone,username,password,role,active)VALUES(?,?,?,?,1)",(i,i,request.form.get('password'),request.form.get('role','tech')));c.commit()
  except:pass
 close(c);return redirect('/dash?view=settings')
@app.route('/edit_user/<p>',methods=['GET','POST'])
def e4(p):
 c=db()
 if request.method=='POST':ni=request.form.get('ident','').strip();ex(c,"UPDATE users SET phone=?,username=?,password=?,role=? WHERE phone=?",(ni,ni,request.form.get('password'),request.form.get('role'),p));c.commit();close(c);return redirect('/dash?view=settings')
 u=dict(ex(c,"SELECT * FROM users WHERE phone=?",(p,)).fetchone());close(c)
 return R(f"<div class=c><h3>تعديل يوزر</h3><form method=post><input name=ident value='{u['username']}' required><input name=password value='{u['password']}' required><select name=role><option value=tech {'selected' if u['role']=='tech' else ''}>فني</option><option value=super {'selected' if u['role']=='super' else ''}>super</option></select><button>حفظ</button></form></div>")
@app.route('/toggle_user/<p>')
def t4(p):c=db();u=dict(ex(c,"SELECT * FROM users WHERE phone=?",(p,)).fetchone());ex(c,"UPDATE users SET active=? WHERE phone=?",(0 if u['active'] else 1,p));c.commit();close(c);return redirect('/dash?view=settings')
@app.route('/del_user/<p>')
def d4(p):
 if p!='05344851045':c=db();ex(c,"DELETE FROM users WHERE phone=?",(p,));c.commit();close(c)
 return redirect('/dash?view=settings')

if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get('PORT',10000)))
