from flask import Flask,request,redirect,url_for,render_template_string
import time,json,os,hashlib
app=Flask(__name__)
F='/tmp/db.json'
def load():
 try:return json.load(open(F))
 except:return{'users':{},'items':[],'sales':[],'colors':{},'notif':[]}
def save(d):json.dump(d,open(F,'w'))
def get_colors():
 d=load();c=d.get('colors',{})
 return{'m':c.get('m','#e74c3c'),'p':c.get('p','#3498db'),'s':c.get('s','#f39c12'),'t':c.get('t','#27ae60')}
def set_cache(k,h):pass
DB=load()
if'admin'not in DB['users']:DB['users']['admin']={'pw':hashlib.sha256('1234'.encode()).hexdigest(),'role':'admin'}
save(DB)
def login_req(f):
 def w(*a,**k):
  u=request.cookies.get('u')
  d=load()
  if not u or u not in d['users']:return redirect('/login')
  return f(*a,**k)
 w.__name__=f.__name__;return w
BASE="""<!doctype html><html dir=rtl lang=ar><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>مخزن</title><style>*{box-sizing:border-box}body{margin:0;font-family:system-ui;background:#f5f6fa;padding-bottom:80px}.top{background:#1e2a38;color:#fff;padding:12px;text-align:center;font-weight:800}.wrap{padding:10px;max-width:600px;margin:auto}.nav{position:fixed;bottom:0;right:0;left:0;background:#fff;display:flex;border-top:1px solid #ddd}.nav a{flex:1;text-align:center;padding:12px 0;text-decoration:none;color:#555;font-size:13px}.nav a.on{color:#1e2a38;font-weight:800}input,select,button{width:100%;padding:10px;margin:5px 0;border:1px solid #ddd;border-radius:8px}button{background:#1e2a38;color:#fff;border:0;font-weight:700}.card{background:#fff;padding:10px;border-radius:10px;margin:8px 0;box-shadow:0 1px 3px #0001}</style></head><body><div class=top>📦 نظام المخزن</div><div class=wrap>__BODY__</div><div class=nav><a href=/?v=home class=__H__>🏠<br>رئيسية</a><a href=/?v=inv class=__I__>📦<br>مخزون</a><a href=/?v=sales class=__S__>🧾<br>مبيع</a><a href=/?v=stats class=__T__>📊<br>تقارير</a><a href=/?v=set class=__C__>⚙️<br>إعدادات</a></div></body></html>"""
def page(b,v):
 h='on' if v=='home' else '';i='on' if v=='inv' else '';s='on' if v=='sales' else '';t='on' if v=='stats' else '';c='on' if v=='set' else ''
 return BASE.replace('__BODY__',b).replace('__H__',h).replace('__I__',i).replace('__S__',s).replace('__T__',t).replace('__C__',c)
def get_view_html(v,msg=''):
 d=load();col=get_colors();m=''
 if msg:m=f"<div class=card style='background:#d4edda'>{msg}</div>"
 if v=='home':
  def cnt(k):return sum(x['q'] for x in d['items'] if x.get('cat')==k)
  tot=sum(x['q'] for x in d['items'])
  def icard(key,emoji,title,val):
   bg=col.get(key,'#333')
   return f"<div style=\"background:{bg};border-radius:8px;padding:6px 2px;color:#fff;text-align:center;min-height:70px;max-height:70px;display:flex;flex-direction:column;justify-content:center;overflow:hidden\"><div style=\"font-size:14px;line-height:1\">{emoji}</div><div style=\"font-size:9px;font-weight:700;margin:2px 0;line-height:1.2\">{title}</div><div style=\"font-size:14px;font-weight:800;line-height:1\">{val}</div></div>"
  b=m+f"<div style='display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:5px;margin:8px 0'>"+icard('m','🔴','رجالي',cnt('m'))+icard('p','🔵','نسائي',cnt('p'))+icard('s','🟡','ولادي',cnt('s'))+icard('t','🟢','الإجمالي',tot)+"</div>"
  b+="<div class=card><b>🔔 تنبيهات</b><br>"+("<br>".join(d.get('notif',[])[-5:]) if d.get('notif') else "لا يوجد")+"</div>"
  return page(b,v)
 if v=='inv':
  b=m+"<div class=card><b>➕ إضافة صنف</b><form method=post action=/add><input name=name placeholder='اسم الصنف' required><select name=cat><option value=m>رجالي</option><option value=p>نسائي</option><option value=s>ولادي</option></select><input name=q type=number placeholder='الكمية' required><input name=price type=number step=0.01 placeholder='السعر' required><button>إضافة</button></form></div>"
  for idx,x in enumerate(d['items']):
   b+=f"<div class=card>{x['name']} - {x['cat']} - كمية:{x['q']} - ${x['price']} <a href=/del/{idx}>🗑️</a></div>"
  return page(b,v)
 if v=='sales':
  b=m+"<div class=card><b>🧾 بيع جديد</b><form method=post action=/sell><select name=idx>"+''.join([f"<option value={i}>{x['name']} ({x['q']})</option>" for i,x in enumerate(d['items'])])+"</select><input name=q type=number placeholder='الكمية' required><button>بيع</button></form></div>"
  for s in reversed(d['sales'][-20:]):b+=f"<div class=card>{s}</div>"
  return page(b,v)
 if v=='stats':
  b=m+"<div class=card><b>📊 التقارير</b><br>عدد الأصناف: "+str(len(d['items']))+"<br>عدد المبيعات: "+str(len(d['sales']))+"</div>"
  return page(b,v)
 if v=='set':
  b=m+f"<div class=card><b>🎨 ألوان الكروت</b><form method=post action=/colors>رجالي <input type=color name=m value={col['m']}> نسائي <input type=color name=p value={col['p']}> ولادي <input type=color name=s value={col['s']}> إجمالي <input type=color name=t value={col['t']}><button>حفظ الألوان</button></form></div>"
  b+="<div class=card><a href=/logout>تسجيل خروج</a></div>"
  return page(b,v)
 return page(m,v)
@app.route('/login',methods=['GET','POST'])
def login():
 if request.method=='POST':
  d=load();u=request.form['u'];p=hashlib.sha256(request.form['p'].encode()).hexdigest()
  if u in d['users'] and d['users'][u]['pw']==p:
   r=redirect('/');r.set_cookie('u',u);return r
  return 'خطأ'
 return '<form method=post style="max-width:300px;margin:50px auto"><input name=u placeholder=مستخدم><input name=p type=password placeholder=كلمة><button>دخول</button></form>'
@app.route('/logout')
def logout():
 r=redirect('/login');r.delete_cookie('u');return r
@app.route('/')
@login_req
def home():return get_view_html(request.args.get('v','home'))
@app.route('/add',methods=['POST'])
@login_req
def add():
 d=load();d['items'].append({'name':request.form['name'],'cat':request.form['cat'],'q':int(request.form['q']),'price':float(request.form['price'])});save(d);return redirect('/?v=inv')
@app.route('/del/<int:idx>')
@login_req
def dele(idx):
 d=load()
 if 0<=idx<len(d['items']):d['items'].pop(idx);save(d)
 return redirect('/?v=inv')
@app.route('/sell',methods=['POST'])
@login_req
def sell():
 d=load();i=int(request.form['idx']);q=int(request.form['q'])
 if 0<=i<len(d['items']) and d['items'][i]['q']>=q:
  d['items'][i]['q']-=q;d['sales'].append(f"بيع {q} من {d['items'][i]['name']} - {time.strftime('%Y-%m-%d %H:%M')}")
  if d['items'][i]['q']<=2:d['notif'].append(f"⚠️ {d['items'][i]['name']} قرب يخلص")
  save(d)
 return redirect('/?v=sales')
@app.route('/colors',methods=['POST'])
@login_req
def colors():
 d=load();d['colors']={'m':request.form['m'],'p':request.form['p'],'s':request.form['s'],'t':request.form['t']};save(d);return redirect('/?v=set')
if __name__=='__main__':app.run(host='0.0.0.0',port=10000)
