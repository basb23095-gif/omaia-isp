from flask import Flask,request,redirect,render_template_string,session,send_from_directory
import os,sqlite3,time
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
 qs=["CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,username TEXT,password TEXT,role TEXT,active INT)",
 "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,status TEXT)",
 "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,name TEXT,network TEXT,tower TEXT)",
 "CREATE TABLE IF NOT EXISTS servers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,ip TEXT,location TEXT)",
 "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,date TEXT,sub TEXT,amount REAL,currency TEXT,note TEXT)"]
 if USE_PG:
  cur=c.cursor()
  for q in qs:cur.execute(q.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY"))
  # ترقية من النظام القديم بدون تخريب
  for col in ["name","network","tower","amount","currency"]:
   try:cur.execute(f"ALTER TABLE dish_ips ADD COLUMN {col} TEXT" if col in ["name","network","tower"] else f"ALTER TABLE ledger ADD COLUMN {col} TEXT")
   except:pass
  cur.execute("SELECT 1 FROM users WHERE phone='05344851045'")
  if not cur.fetchone():cur.execute("INSERT INTO users VALUES('05344851045','05344851045','admin2024','super',1)")
  c.commit();cur.close();return
 for q in qs:c.execute(q)
 for t,col in [("dish_ips","name"),("dish_ips","network"),("dish_ips","tower"),("ledger","amount"),("ledger","currency")]:
  try:c.execute(f"SELECT {col} FROM {t} LIMIT 1")
  except:
   try:c.execute(f"ALTER TABLE {t} ADD COLUMN {col} TEXT");c.commit()
   except:pass
 if not c.execute("SELECT 1 FROM users WHERE phone='05344851045'").fetchone():
  c.execute("INSERT INTO users VALUES('05344851045','05344851045','admin2024','super',1)");c.commit()
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

CSS="body{font-family:Arial;margin:0;background:__BG__;color:__TEXT__}body.lb{background:linear-gradient(rgba(4,30,54,.55),rgba(4,30,54,.78)),url('/bg.jpg') center/cover fixed,__BG__;min-height:100vh;display:flex;align-items:center;justify-content:center}.t{position:fixed;top:0;left:0;right:0;height:52px;background:__SIDEBAR__;display:flex;align-items:center;justify-content:space-between;padding:0 12px;z-index:20;border-bottom:1px solid __MAIN__}.m{padding:62px 10px;max-width:1050px;margin:auto}.c{background:__CARD__;border:1px solid __MAIN__;border-radius:12px;padding:12px;margin:8px 0}button{background:__MAIN__;border:0;padding:9px;width:100%;border-radius:8px;font-weight:bold;cursor:pointer}input,select{width:100%;padding:8px;margin:4px 0;border-radius:8px;border:1px solid #334155;background:#0f172a;color:#fff;box-sizing:border-box}table{width:100%;border-collapse:collapse}td,th{padding:7px;border-bottom:1px solid #334155;text-align:center;font-size:14px}th{color:__MAIN__}.g4{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.g2{display:grid;grid-template-columns:1fr 1fr;gap:8px}@media(max-width:700px){.g4{grid-template-columns:1fr 1fr}.g2{grid-template-columns:1fr}}.drawer{position:fixed;top:0;right:-280px;width:260px;height:100%;background:__SIDEBAR__;z-index:30;transition:.3s;padding:60px 12px}.drawer.open{right:0}.overlay{position:fixed;inset:0;background:rgba(0,0,0,.5);display:none;z-index:25}.overlay.show{display:block}.drawer a{display:block;color:#fff;text-decoration:none;padding:11px;border-bottom:1px solid #1e3a5f}.foot{text-align:center;font-size:12px;color:__MAIN__;margin:18px 0}"
LAY="""<!DOCTYPE html><html dir=rtl><head><meta charset=UTF-8><meta name=viewport content='width=device-width,initial-scale=1'><title>OMAIA</title><style>"""+CSS+"""</style></head><body class=__BC__>
<div class=t><b style=color:__MAIN__>OMAIA ISP</b><div><a href=/lang/toggle style='color:#fff;text-decoration:none;margin:0 10px;font-size:18px' title='لغة'>🌐</a><span onclick="document.getElementById('dr').classList.add('open');document.getElementById('ov').classList.add('show')" style=cursor:pointer;font-size:22px;color:#fff>☰</span></div></div>
<div id=ov class=overlay onclick="document.getElementById('dr').classList.remove('open');this.classList.remove('show')"></div>
<div id=dr class=drawer>
<a href=/dash>🏠 الرئيسية</a><a href=/dash?view=subs>👥 المشتركين</a><a href=/dash?view=dishes>📡 الصحون</a><a href=/dash?view=servers>🖥️ سيرفرات</a><a href=/dash?view=ledger>📒 دفتر حسابات</a><a href=/dash?view=settings>⚙️ الإعدادات</a><a href=/logout>🚪 خروج</a>
<hr><a href='https://wa.me/"""+WA_LINK+"""' target=_blank>📞 دعم فني """+WA_DISPLAY+"""</a>
</div><div class=m>{{c|safe}}<div class=foot>تصميم م. عبدو عباس<br><a href='https://wa.me/"""+WA_LINK+"""' style=color:__MAIN__;text-decoration:none>📞 تواصل دعم فني """+WA_DISPLAY+"""</a></div></div></body></html>"""
def R(h,bc=""):
 s=LAY;co=get_colors()
 for k,v in co.items():s=s.replace("__"+k+"__",v)
 return render_template_string(s.replace("__BC__",bc),c=h)
def gv(r):
 try:return list(dict(r).values())[0]
 except:return r[0] if r else 0

@app.route('/',methods=['GET','POST'])
def login():
 if request.method=='POST':
  i=request.form.get('phone','').strip();c=db();u=ex(c,"SELECT * FROM users WHERE phone=? OR username=?",(i,i)).fetchone();d=dict(u) if u else None;close(c)
  if d and d['password']==request.form.get('password') and d['active']:
   session['p']=d['phone'];return redirect('/dash')
  return R("<div class=c style='width:320px;text-align:center'><p style=color:red>خطأ</p><a href=/>رجوع</a></div>","lb")
 return R("<div class=c style='width:320px;text-align:center'><h2 style=color:#00D4FF>OMAIA ISP</h2><form method=post><input name=phone placeholder='رقم هاتف / اسم مستخدم' required><input name=password type=password placeholder='باسورد' required><button>دخول</button></form><p style=font-size:12px;color:#00D4FF>تصميم م. عبدو عباس</p></div>","lb")
@app.route('/logout')
def lo():session.clear();return redirect('/')
@app.route('/lang/toggle')
def lt():session['lang']='en' if session.get('lang')=='ar' else 'ar';return redirect(request.referrer or '/dash')

@app.route('/dash')
def dash():
 if 'p' not in session:return redirect('/')
 v=request.args.get('view','home');c=db();M=get_colors()['MAIN']
 def F(h):r=R(h);close(c);return r
 if v=='home':
  ns=gv(ex(c,"SELECT COUNT(*)k FROM subs").fetchone());nd=gv(ex(c,"SELECT COUNT(*)k FROM dish_ips").fetchone());nl=gv(ex(c,"SELECT COUNT(*)k FROM ledger").fetchone());nu=gv(ex(c,"SELECT COUNT(*)k FROM users").fetchone())
  return F(f"<div class=g4><div class=c style=text-align:center><h2 style=color:{M}>{ns}</h2>👥</div><div class=c style=text-align:center><h2 style=color:{M}>{nd}</h2>📡</div><div class=c style=text-align:center><h2 style=color:{M}>{nl}</h2>📒</div><div class=c style=text-align:center><h2 style=color:{M}>{nu}</h2>👤</div></div>")
 if v=='subs':
  rows=ex(c,"SELECT * FROM subs ORDER BY id DESC LIMIT 50").fetchall()
  tr="".join(f"<tr><td>{dict(x).get('name')}</td><td>{dict(x).get('phone')}</td><td><a href=/edit_sub/{dict(x)['id']}>✏️</a></td></tr>" for x in rows)
  return F(f"<div class=c><form method=post action=/add_sub><input name=name placeholder='اسم' required><input name=phone placeholder='هاتف'><button>+</button></form></div><div class=c><table><tr><th>اسم</th><th>هاتف</th><th>تعديل</th></tr>{tr}</table></div>")
 if v=='dishes':
  rows=ex(c,"SELECT * FROM dish_ips ORDER BY id DESC LIMIT 50").fetchall()
  tr="".join(f"<tr><td dir=ltr>{dict(x).get('ip','')}</td><td>{dict(x).get('name','') or dict(x).get('location','')}</td><td>{dict(x).get('network','')}</td><td>{dict(x).get('tower','') or dict(x).get('region','')}</td><td><a href=/del_dish/{dict(x)['id']}>🗑️</a></td></tr>" for x in rows)
  return F(f"<div class=c><h3>📡 الصحون</h3><form method=post action=/add_dish><input name=ip placeholder='IP' dir=ltr required><input name=name placeholder='الاسم' required><input name=network placeholder='الشبكة'><input name=tower placeholder='البرج'><button>+ إضافة</button></form></div><div class=c><table><tr><th>IP</th><th>الاسم</th><th>الشبكة</th><th>البرج</th><th></th></tr>{tr}</table></div>")
 if v=='servers':
  rows=ex(c,"SELECT * FROM servers ORDER BY id DESC LIMIT 50").fetchall()
  tr="".join(f"<tr><td>{dict(x).get('name')}</td><td dir=ltr>{dict(x).get('ip')}</td><td><a href=/del_server/{dict(x)['id']}>🗑️</a></td></tr>" for x in rows)
  return F(f"<div class=c><form method=post action=/add_server><input name=name placeholder='سيرفر' required><input name=ip placeholder='IP' dir=ltr><button>+</button></form></div><div class=c><table>{tr}</table></div>")
 if v=='ledger':
  rows=ex(c,"SELECT * FROM ledger ORDER BY id DESC LIMIT 50").fetchall()
  def fmt(x):
   d=dict(x);amt=d.get('amount');cur=d.get('currency','USD')
   if amt is None: # دعم قديم usd/syr
    if d.get('usd'):amt,cur=d.get('usd'),'USD'
    else:amt,cur=d.get('syr',''),'SYR'
   sym='$' if cur=='USD' else 'ل.س';return f"{amt} {sym}"
  tr="".join(f"<tr><td>{dict(x).get('date')}</td><td>{dict(x).get('sub')}</td><td>{fmt(x)}</td><td><a href=/edit_ledger/{dict(x)['id']}>✏️</a> <a href=/del_ledger/{dict(x)['id']}>🗑️</a></td></tr>" for x in rows)
  return F(f"""<div class=c><h3>📒 دفتر حسابات</h3>
  <form method=post action=/add_ledger><input name=date type=date required><input name=sub placeholder='الاسم' required>
  <div style=display:flex;gap:6px><input name=amount type=number step=0.01 placeholder='المبلغ' required>
  <button type=button id=curBtn onclick="let s=document.getElementById('cur');s.value=s.value=='USD'?'SYR':'USD';this.textContent=s.value=='USD'?'💵 $':'💶 ل.س'" style=width:90px>💵 $</button>
  <input type=hidden name=currency id=cur value=USD></div>
  <input name=note placeholder='ملاحظة'><button>+ حفظ</button></form>
  <form method=post action=/upload_ledger enctype=multipart/form-data><input type=file name=file accept=.xlsx required><button>📤 رفع اكسل</button></form></div>
  <div class=c><table><tr><th>تاريخ</th><th>اسم</th><th>مبلغ</th><th>تعديل+حفظ</th></tr>{tr}</table></div>""")
 if v=='settings':
  us=ex(c,"SELECT * FROM users LIMIT 100").fetchall()
  tr="".join(f"<tr><td dir=ltr>{dict(x).get('username')}</td><td><a href=/edit_user/{dict(x)['phone']}>✏️</a> <a href=/toggle_user/{dict(x)['phone']}>🔄</a></td></tr>" for x in us)
  return F(f"<div class=c><h3>⚙️ الإعدادات</h3><form method=post action=/add_user><input name=ident placeholder='هاتف / مستخدم' required><input name=password placeholder='باسورد' required><button>+ يوزر</button></form><table>{tr}</table></div>")
 return F("")

@app.route('/add_sub',methods=['POST'])
def a1():c=db();ex(c,"INSERT INTO subs(name,phone,status)VALUES(?,?,'active')",(request.form.get('name'),request.form.get('phone')));c.commit();close(c);return redirect('/dash?view=subs')
@app.route('/edit_sub/<int:i>',methods=['GET','POST'])
def e1(i):
 c=db()
 if request.method=='POST':ex(c,"UPDATE subs SET name=?,phone=? WHERE id=?",(request.form.get('name'),request.form.get('phone'),i));c.commit();close(c);return redirect('/dash?view=subs')
 r=dict(ex(c,"SELECT * FROM subs WHERE id=?",(i,)).fetchone());close(c)
 return R(f"<div class=c><form method=post><input name=name value='{r['name']}'><input name=phone value='{r['phone']}'><button>💾 حفظ</button></form></div>")
@app.route('/add_dish',methods=['POST'])
def a2():c=db();ex(c,"INSERT INTO dish_ips(ip,name,network,tower)VALUES(?,?,?,?)",(request.form.get('ip'),request.form.get('name'),request.form.get('network'),request.form.get('tower')));c.commit();close(c);return redirect('/dash?view=dishes')
@app.route('/del_dish/<int:i>')
def d2(i):c=db();ex(c,"DELETE FROM dish_ips WHERE id=?",(i,));c.commit();close(c);return redirect('/dash?view=dishes')
@app.route('/add_server',methods=['POST'])
def asv():c=db();ex(c,"INSERT INTO servers(name,ip,location)VALUES(?,?,?)",(request.form.get('name'),request.form.get('ip'),''));c.commit();close(c);return redirect('/dash?view=servers')
@app.route('/del_server/<int:i>')
def dsv(i):c=db();ex(c,"DELETE FROM servers WHERE id=?",(i,));c.commit();close(c);return redirect('/dash?view=servers')
@app.route('/add_ledger',methods=['POST'])
def a3():c=db();ex(c,"INSERT INTO ledger(date,sub,amount,currency,note)VALUES(?,?,?,?,?)",(request.form.get('date'),request.form.get('sub'),float(request.form.get('amount') or 0),request.form.get('currency'),request.form.get('note')));c.commit();close(c);return redirect('/dash?view=ledger')
@app.route('/edit_ledger/<int:i>',methods=['GET','POST'])
def el(i):
 c=db()
 if request.method=='POST':ex(c,"UPDATE ledger SET date=?,sub=?,amount=?,currency=?,note=? WHERE id=?",(request.form.get('date'),request.form.get('sub'),float(request.form.get('amount') or 0),request.form.get('currency'),request.form.get('note'),i));c.commit();close(c);return redirect('/dash?view=ledger')
 r=dict(ex(c,"SELECT * FROM ledger WHERE id=?",(i,)).fetchone());close(c)
 cur=r.get('currency','USD') or 'USD';lbl='💵 $' if cur=='USD' else '💶 ل.س'
 return R(f"""<div class=c><h3>تعديل قيد</h3><form method=post><input name=date type=date value='{r.get('date','')}'>
 <input name=sub value='{r.get('sub','')}'><div style=display:flex;gap:6px><input name=amount type=number step=0.01 value='{r.get('amount') or r.get('usd') or r.get('syr') or 0}'>
 <button type=button onclick="let s=document.getElementById('cur');s.value=s.value=='USD'?'SYR':'USD';this.textContent=s.value=='USD'?'💵 $':'💶 ل.س'" style=width:90px>{lbl}</button>
 <input type=hidden name=currency id=cur value={cur}></div><input name=note value='{r.get('note','')}'><button>💾 حفظ</button></form></div>""")
@app.route('/del_ledger/<int:i>')
def d3(i):c=db();ex(c,"DELETE FROM ledger WHERE id=?",(i,));c.commit();close(c);return redirect('/dash?view=ledger')
@app.route('/upload_ledger',methods=['POST'])
def u3():
 if not pd:return "ثبت pandas"
 f=request.files.get('file')
 if f:
  df=pd.read_excel(f);c=db()
  for _,r in df.iterrows():ex(c,"INSERT INTO ledger(date,sub,amount,currency,note)VALUES(?,?,?,?,?)",(str(r.get('date','')),str(r.get('sub','')),float(r.get('amount',0) or 0),str(r.get('currency','USD')),str(r.get('note',''))))
  c.commit();close(c)
 return redirect('/dash?view=ledger')
@app.route('/add_user',methods=['POST'])
def a4():
 c=db();i=request.form.get('ident','').strip()
 if i:
  try:ex(c,"INSERT INTO users(phone,username,password,role,active)VALUES(?,?,?,?,1)",(i,i,request.form.get('password'),'tech'));c.commit()
  except:pass
 close(c);return redirect('/dash?view=settings')
@app.route('/edit_user/<p>',methods=['GET','POST'])
def e4(p):
 c=db()
 if request.method=='POST':ni=request.form.get('ident','').strip();ex(c,"UPDATE users SET phone=?,username=?,password=? WHERE phone=?",(ni,ni,request.form.get('password'),p));c.commit();close(c);return redirect('/dash?view=settings')
 u=dict(ex(c,"SELECT * FROM users WHERE phone=?",(p,)).fetchone());close(c)
 return R(f"<div class=c><form method=post><input name=ident value='{u['username']}' required><input name=password value='{u['password']}' required><button>💾 حفظ</button></form></div>")
@app.route('/toggle_user/<p>')
def t4(p):c=db();u=dict(ex(c,"SELECT * FROM users WHERE phone=?",(p,)).fetchone());ex(c,"UPDATE users SET active=? WHERE phone=?",(0 if u['active'] else 1,p));c.commit();close(c);return redirect('/dash?view=settings')
if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.environ.get('PORT',10000)))
