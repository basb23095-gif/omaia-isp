from flask import Flask, request, redirect, session
from colors import COLORS, logo_html
import os, datetime, json, html
try: import psycopg2, psycopg2.extras
except: psycopg2=None
import sqlite3

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY","omia-sec-2026")
DATABASE_URL = os.environ.get("DATABASE_URL","").strip().replace("postgresql://","postgres://")
USE_PG = bool(DATABASE_URL.startswith("postgres://") and psycopg2)
_pg = None

def esc(s): return html.escape(str(s or ''), quote=True)
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
        _pg=psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=5)
        _pg.autocommit=True
        return _pg
    c=sqlite3.connect("omia.db");c.row_factory=sqlite3.Row;return c
def cc(c):
    if not USE_PG:
        try:c.close()
        except:pass
def qall(q,a=()):
    c=db()
    try:
        if USE_PG:
            cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(q.replace("?","%s"),a);rs=[dict(r) for r in cur.fetchall()];cur.close();return rs
        else:
            rs=[dict(r) for r in c.execute(q,a).fetchall()];cc(c);return rs
    except: cc(c);return []
def qone(q,a=()):
    r=qall(q,a);return r[0] if r else None
def qexec(q,a=()):
    c=db()
    try:
        if USE_PG: cur=c.cursor();cur.execute(q.replace("?","%s"),a);cur.close()
        else: c.execute(q,a);c.commit();cc(c)
    except: cc(c)
def fnum(v):
    try:return float(v or 0)
    except:return 0

def init():
    ss=[
    "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,active INT DEFAULT 1)",
    "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,active INT DEFAULT 1)",
    "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,sub_id INT,amount REAL,typ TEXT,dt TEXT,note TEXT)",
    "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,lat REAL DEFAULT 0,lng REAL DEFAULT 0,dish_name TEXT,tower_name TEXT)",
    "CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,lat REAL,lng REAL)"
    ]
    if USE_PG: ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
    for s in ss: qexec(s)
    for col in ["ALTER TABLE users ADD COLUMN username TEXT","ALTER TABLE dish_ips ADD COLUMN dish_name TEXT","ALTER TABLE dish_ips ADD COLUMN tower_name TEXT","ALTER TABLE ledger ADD COLUMN sub_id INT","ALTER TABLE ledger ADD COLUMN note TEXT"]:
        try: qexec(col)
        except: pass
    if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username,active) VALUES(?,?,?,?,?)",('05344851045','admin2024','manager','admin',1))
init()

def me(): return qone("SELECT * FROM users WHERE phone=?",(session.get('phone'),))
def is_tech(): m=me(); return m and m.get('role')=='tech'
def can_edit(): return not is_tech()
def dark(): return session.get('theme','light')

def page_content(v):
    h=""; dis="" if can_edit() else "style='opacity:.35;pointer-events:none'"
    # 3 - dishes grid 2 columns CSS injected via layout
    if v=='home':
        ns=(qone("SELECT COUNT(*) c FROM subs") or {}).get('c',0)
        nd=(qone("SELECT COUNT(*) c FROM dish_ips") or {}).get('c',0)
        nt=(qone("SELECT COUNT(*) c FROM towers") or {}).get('c',0)
        h=f"<div class=grid><div class=kpi style='background:#2563eb'>👥<br>{ns}</div><div class=kpi style='background:#16a34a'>📡<br>{nd}</div><div class=kpi style='background:#dc2626'>🗼<br>{nt}</div></div><div class=card>مرحبا {esc(session.get('phone'))} - {esc(me().get('role',''))}</div>"
    elif v=='subs':
        rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 100")
        h="<div class=card><h3>👥 مشتركين</h3><form data-ajax method=post action=/add_sub><input name=name required placeholder=الاسم><input name=phone placeholder=هاتف><button>اضافة</button></form></div>"
        for r in rs:
            e=f"<a href=\"javascript:loadPage('edit_sub_{r['id']}')\" {dis}>✏️</a>" if can_edit() else ""
            h+=f"<div class=card>{esc(r['name'])} - {esc(r['phone'])} {e} <a href=/del_sub/{r['id']} data-del {dis} style='color:red'>🗑️</a></div>"
    elif v.startswith('edit_sub_'):
        if not can_edit(): return "ممنوع"
        r=qone("SELECT * FROM subs WHERE id=?", (v.split('_')[-1],))
        h=f"<div class=card><form data-ajax method=post action=/upd_sub/{r['id']}><input name=name value='{esc(r['name'])}'><input name=phone value='{esc(r['phone'])}'><button>💾 حفظ</button></form></div>"
    elif v=='dishes':
        rs=qall("SELECT * FROM dish_ips ORDER BY id DESC LIMIT 200")
        h="<div class=card><h3>📡 صحون</h3><form data-ajax method=post action=/add_dish><input name=dish_name required placeholder='📛 اسم صحن'><input name=ip required placeholder='🌐 IP'><input name=tower_name placeholder='🗼 اسم برج'><input name=location placeholder='📍 احداثيات وصف'><div style='display:grid;grid-template-columns:1fr 1fr;gap:6px'><input name=lat placeholder='lat'><input name=lng placeholder='lng'></div><button>اضافة</button></form></div><div class=grid2>"
        for r in rs:
            e=f"<a href=\"javascript:loadPage('edit_dish_{r['id']}')\" {dis}>✏️ تعديل</a>" if can_edit() else ""
            h+=f"<div class=card>📛 <b>{esc(r.get('dish_name') or r.get('location',''))}</b><br>🌐 <a href='http://{esc(r['ip'])}' target=_blank>{esc(r['ip'])}</a><br>🗼 {esc(r.get('tower_name',''))}<br>📍 {r.get('lat',0)},{r.get('lng',0)}<br>{e} <a href=/del_dish/{r['id']} data-del {dis} style='color:red'>🗑️ حذف</a></div>"
        h+="</div>"
    elif v.startswith('edit_dish_'):
        if not can_edit(): return "ممنوع"
        r=qone("SELECT * FROM dish_ips WHERE id=?", (v.split('_')[-1],))
        h=f"<div class=card><form data-ajax method=post action=/upd_dish/{r['id']}><input name=dish_name value='{esc(r.get('dish_name',''))}' placeholder='اسم صحن'><input name=ip value='{esc(r['ip'])}'><input name=tower_name value='{esc(r.get('tower_name',''))}'><input name=lat value='{r.get('lat',0)}'><input name=lng value='{r.get('lng',0)}'><button>💾 حفظ</button></form></div>"
    elif v=='towers':
        rs=qall("SELECT * FROM towers ORDER BY id DESC LIMIT 100")
        h="<div class=card><h3>🗼 ابراج</h3><form data-ajax method=post action=/add_tower><input name=name required placeholder=اسم><input name=lat placeholder=lat><input name=lng placeholder=lng><button>اضافة</button></form></div>"
        for r in rs:
            e=f"<a href=\"javascript:loadPage('edit_tower_{r['id']}')\" {dis}>✏️</a>" if can_edit() else ""
            h+=f"<div class=card>🗼 {esc(r['name'])} {e} <a href=/del_tower/{r['id']} data-del {dis} style='color:red'>حذف</a></div>"
    elif v.startswith('edit_tower_'):
        if not can_edit(): return "ممنوع"
        r=qone("SELECT * FROM towers WHERE id=?", (v.split('_')[-1],))
        h=f"<div class=card><form data-ajax method=post action=/upd_tower/{r['id']}><input name=name value='{esc(r['name'])}'><input name=lat value='{r.get('lat',0)}'><input name=lng value='{r.get('lng',0)}'><button>حفظ</button></form></div>"
    elif v=='ledger':
        try: rs=qall("SELECT l.*,s.name sname FROM ledger l LEFT JOIN subs s ON s.id=l.sub_id ORDER BY l.id DESC LIMIT 200")
        except: rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 200")
        ss=qall("SELECT id,name FROM subs LIMIT 200")
        o="".join([f"<option value='{x['id']}'>{esc(x['name'])}</option>" for x in ss])
        h=f"<div class=card><h3>📒 دفتر حسابات</h3><form data-ajax method=post action=/add_ledger><select name=sub_id><option value='0'>اختر مشترك</option>{o}</select><input name=amount type=number step=0.01 required placeholder=مبلغ><select name=typ><option>دين</option><option>دفع</option></select><input name=note placeholder=ملاحظة><button>اضافة</button></form><button onclick='window.print()'>🖨️ PDF</button> <a href=/export_ledger>📊 Excel</a></div>"
        for r in rs:
            e=f"<a href=\"javascript:loadPage('edit_ledger_{r['id']}')\" {dis}>✏️ تعديل</a>" if can_edit() else ""
            h+=f"<div class=card>👤 {esc(r.get('sname',''))} 💰 {r.get('amount',0)} {esc(r.get('typ',''))} 📝 {esc(r.get('note',''))} {e} <a href=/del_ledger/{r['id']} data-del {dis} style='color:red'>🗑️ حذف</a></div>"
    elif v.startswith('edit_ledger_'):
        if not can_edit(): return "ممنوع"
        r=qone("SELECT * FROM ledger WHERE id=?", (v.split('_')[-1],))
        h=f"<div class=card><form data-ajax method=post action=/upd_ledger/{r['id']}><input name=amount type=number step=0.01 value='{r.get('amount',0)}'><select name=typ><option>{esc(r.get('typ',''))}</option><option>دين</option><option>دفع</option></select><input name=note value='{esc(r.get('note',''))}'><button>💾 حفظ</button></form></div>"
    elif v=='map':
        ds=qall("SELECT lat,lng,dish_name,ip,tower_name FROM dish_ips WHERE lat!=0 LIMIT 300")
        dj=json.dumps([{"la":float(d.get("lat") or 0),"ln":float(d.get("lng") or 0),"n":str(d.get("dish_name","")),"ip":str(d.get("ip","")),"t":str(d.get("tower_name",""))} for d in ds if d.get("lat")]).replace("</","<\\/")
        h=f"<div class=card><h3>🗺️ خريطة</h3><div id=mp style='height:70vh;border-radius:10px'></div></div><script>var DS={dj};initMap();</script>"
    elif v=='settings':
        us=qall("SELECT phone,username,role FROM users ORDER BY phone")
        uh="".join([f"<div class=card>👤 {esc(u.get('username') or u['phone'])} ({esc(u['phone'])}) - {esc(u.get('role',''))} {'<a href=/del_user/'+esc(u['phone'])+' data-del style=color:red>🗑️</a>' if u['phone']!='05344851045' else ''}</div>" for u in us])
        h=f"<div class=card><h3>⚙️ اعدادات</h3><form data-ajax method=post action=/change_user><input name=newphone required placeholder='يوزر جديد رقم/اسم'><button>تغيير اليوزر</button></form><form data-ajax method=post action=/change_pass><input name=newpass type=password required placeholder='كلمة جديدة'><button>تغيير كلمة السر</button></form><a href=/toggle_theme data-ajax>🌙/☀️ تبديل الثيم</a></div><div class=card><h3>➕ اضافة يوزر</h3><form data-ajax method=post action=/add_user><input name=phone required placeholder='📱 رقم هاتف / اسم مستخدم'><input name=password type=password required placeholder='🔑 كلمة سر'><select name=role><option value=tech>🧑‍🔧 فني (يضيف فقط)</option><option value=manager>👑 مدير (كل الصلاحيات)</option></select><button>اضافة</button></form></div>{uh}"
    return h

def layout(c,v='home'):
    th=dark(); bg=COLORS['bg_dark'] if th=='dark' else COLORS['bg_light']
    card=COLORS['card_dark'] if th=='dark' else COLORS['card_light']
    txt='#fff' if th=='dark' else '#000'
    return f"""<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<link rel=stylesheet href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'>
<style>
*{{box-sizing:border-box}}body{{margin:0;font-family:sans-serif;background:{bg};color:{txt}}}
.top{{position:fixed;top:0;left:0;right:0;background:{COLORS['top_bg']};color:#fff;padding:12px;z-index:101;display:flex;align-items:center;gap:12px}}
.burger{{font-size:24px;cursor:pointer}}
.menu{{position:fixed;top:48px;bottom:0;right:0;width:210px;background:{COLORS['menu_bg']};padding:10px;z-index:100;transition:.25s;transform:translateX(0)}}
.menu.hide{{transform:translateX(100%)}}
.menu a{{display:block;color:#fff;text-decoration:none;padding:11px;border-radius:8px;margin:2px 0}}
.overlay{{position:fixed;inset:48px 0 0 0;background:rgba(0,0,0,.4);display:none;z-index:99}}
.overlay.show{{display:block}}
.main{{margin-right:220px;margin-top:60px;padding:10px;transition:.25s}}
.main.full{{margin-right:0}}
.card{{background:{card};padding:10px;border-radius:10px;margin:8px 0}}
.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}
.kpi{{padding:12px;border-radius:10px;color:#fff;text-align:center;font-weight:bold}}
input,select{{width:100%;padding:8px;margin:4px 0;border-radius:7px;border:1px solid #ccc}}
button{{background:{COLORS['btn']};color:#fff;border:0;padding:8px 12px;border-radius:7px;cursor:pointer}}
#ld{{position:fixed;top:50px;left:50%;transform:translateX(-50%);background:#f59e0b;color:#000;padding:4px 14px;border-radius:20px;display:none;z-index:200;font-size:13px}}
@media(max-width:700px){{.menu{{width:200px}}.main{{margin-right:0}}.grid2{{grid-template-columns:1fr 1fr}} }}
</style></head><body>
<div class=top><span class=burger onclick="toggleMenu()">☰</span><div>{logo_html()}</div></div>
<div class=overlay id=ov onclick="toggleMenu(true)"></div>
<div class=menu id=mn>
<a href="javascript:loadPage('home')">🏠 الرئيسية</a>
<a href="javascript:loadPage('subs')">👥 مشتركين</a>
<a href="javascript:loadPage('ledger')">📒 دفتر</a>
<a href="javascript:loadPage('dishes')">📡 صحون</a>
<a href="javascript:loadPage('towers')">🗼 ابراج</a>
<a href="javascript:loadPage('map')">🗺️ خريطة</a>
<a href="javascript:loadPage('settings')">⚙️ اعدادات</a>
<a href=/logout>🚪 خروج</a>
</div>
<div class=main id=main>{c}</div>
<div id=ld>⏳ جاري التحميل...</div>
<script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>
<script>
var curV='{v}';
function toggleMenu(forceClose){{let m=document.getElementById('mn'),o=document.getElementById('ov');let hide=m.classList.contains('hide');let shouldHide=forceClose?true:!hide;m.classList.toggle('hide',shouldHide);o.classList.toggle('show',!shouldHide);document.getElementById('main').classList.toggle('full',shouldHide)}}
if(window.innerWidth<700)toggleMenu(true);
window.loadPage=async function(v){{
curV=v;toggleMenu(true);
let l=document.getElementById('ld');l.style.display='block';
try{{let r=await fetch('/api/page?v='+v);document.getElementById('main').innerHTML=await r.text();bindAjax();}}catch(e){{}}
l.style.display='none';window.scrollTo({{top:0}});
}};
function initMap(){{
if(typeof L=='undefined'){{setTimeout(initMap,300);return}}
var m=L.map('mp').setView([35.13,36.75],12);
L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',{{maxZoom:18}}).addTo(m);
if(typeof DS!='undefined')DS.forEach(d=>L.marker([d.la,d.ln]).addTo(m).bindPopup(d.n+'<br>'+d.ip+'<br>'+d.t));
setTimeout(()=>m.invalidateSize(),300);
}};
function bindAjax(){{
document.querySelectorAll('form[data-ajax]').forEach(f=>{{f.onsubmit=async e=>{{e.preventDefault();await fetch(f.action,{{method:'POST',body:new FormData(f)}});loadPage(curV)}};}});
document.querySelectorAll('a[data-ajax]').forEach(a=>{{a.onclick=async e=>{{e.preventDefault();await fetch(a.href);loadPage(curV)}};}});
document.querySelectorAll('a[data-del]').forEach(a=>{{a.onclick=async e=>{{e.preventDefault();if(confirm('حذف؟')){{await fetch(a.href);loadPage(curV)}}}}}});
}};
bindAjax();
</script></body></html>"""

@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')
@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        uin=request.form.get('userin','').strip();pw=request.form.get('password','')
        u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
        if u and u['password']==pw:
            session['phone']=u['phone'];return redirect('/dash')
    return f"""<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<style>body{{display:flex;align-items:center;justify-content:center;background:{COLORS['bg_dark']};min-height:100vh;margin:0;font-family:sans-serif}}.box{{background:#fff;padding:20px;border-radius:12px;width:92%;max-width:340px}}input{{width:100%;padding:10px;margin:6px 0;border-radius:8px;border:1px solid #ccc}}button{{width:100%;background:{COLORS['btn']};color:#fff;padding:10px;border:0;border-radius:8px}}</style>
</head><body><div class=box><h3 style='text-align:center'>{logo_html()}</h3>
<form method=post><input name=userin placeholder='رقم هاتف / اسم مستخدم' required><input name=password type=password placeholder='كلمة السر' required><button>دخول</button></form>
</div></body></html>"""
@app.route('/logout')
def lo(): session.clear();return redirect('/login')
@app.route('/dash')
def dash():
    if not session.get('phone'): return redirect('/login')
    return layout(page_content(request.args.get('v','home')),request.args.get('v','home'))
@app.route('/api/page')
def ap():
    if not session.get('phone'): return "login"
    return page_content(request.args.get('v','home'))
@app.route('/toggle_theme')
def tt(): session['theme']='dark' if dark()!='dark' else 'light';return "ok"
@app.route('/add_sub',methods=['POST'])
def a1(): qexec("INSERT INTO subs(name,phone) VALUES(?,?)",(request.form.get('name',''),request.form.get('phone','')));return "ok"
@app.route('/upd_sub/<int:i>',methods=['POST'])
def au1(i):
    if not can_edit(): return "no"
    qexec("UPDATE subs SET name=?,phone=? WHERE id=?",(request.form.get('name'),request.form.get('phone'),i));return "ok"
@app.route('/del_sub/<int:i>')
def a4(i):
    if not can_edit(): return "no"
    qexec("DELETE FROM subs WHERE id=?",(i,));return "ok"
@app.route('/add_ledger',methods=['POST'])
def b1():
    f=request.form
    qexec("INSERT INTO ledger(sub_id,amount,typ,dt,note) VALUES(?,?,?,?,?)",(int(f.get('sub_id') or 0),fnum(f.get('amount')),f.get('typ','دين'),datetime.datetime.now().isoformat(),f.get('note','')))
    return "ok"
@app.route('/upd_ledger/<int:i>',methods=['POST'])
def bu(i):
    if not can_edit(): return "no"
    f=request.form;qexec("UPDATE ledger SET amount=?,typ=?,note=? WHERE id=?",(fnum(f.get('amount')),f.get('typ'),f.get('note',''),i));return "ok"
@app.route('/del_ledger/<int:i>')
def b2(i):
    if not can_edit(): return "no"
    qexec("DELETE FROM ledger WHERE id=?",(i,));return "ok"
@app.route('/export_ledger')
def ex():
    rs=qall("SELECT * FROM ledger ORDER BY id DESC")
    csv="id,amount,typ,note\n"+"\n".join([f"{r['id']},{r.get('amount',0)},{r.get('typ','')},{r.get('note','')}" for r in rs])
    return (csv,200,{'Content-Type':'text/csv','Content-Disposition':'attachment;filename=ledger.csv'})
@app.route('/add_dish',methods=['POST'])
def c1():
    f=request.form
    qexec("INSERT INTO dish_ips(ip,location,lat,lng,dish_name,tower_name) VALUES(?,?,?,?,?,?)",(f.get('ip',''),f.get('location',''),fnum(f.get('lat')),fnum(f.get('lng')),f.get('dish_name',''),f.get('tower_name','')))
    return "ok"
@app.route('/upd_dish/<int:i>',methods=['POST'])
def cu(i):
    if not can_edit(): return "no"
    f=request.form;qexec("UPDATE dish_ips SET ip=?,dish_name=?,tower_name=?,lat=?,lng=? WHERE id=?",(f.get('ip'),f.get('dish_name'),f.get('tower_name'),fnum(f.get('lat')),fnum(f.get('lng')),i));return "ok"
@app.route('/del_dish/<int:i>')
def c2(i):
    if not can_edit(): return "no"
    qexec("DELETE FROM dish_ips WHERE id=?",(i,));return "ok"
@app.route('/add_tower',methods=['POST'])
def d1():
    f=request.form;qexec("INSERT INTO towers(name,lat,lng) VALUES(?,?,?)",(f.get('name',''),fnum(f.get('lat')),fnum(f.get('lng'))));return "ok"
@app.route('/upd_tower/<int:i>',methods=['POST'])
def du2(i):
    if not can_edit(): return "no"
    f=request.form;qexec("UPDATE towers SET name=?,lat=?,lng=? WHERE id=?",(f.get('name'),fnum(f.get('lat')),fnum(f.get('lng')),i));return "ok"
@app.route('/del_tower/<int:i>')
def d2(i):
    if not can_edit(): return "no"
    qexec("DELETE FROM towers WHERE id=?",(i,));return "ok"
@app.route('/add_user',methods=['POST'])
def addu():
    if not can_edit(): return "no"
    f=request.form;ph=f.get('phone','').strip()
    qexec("INSERT INTO users(phone,password,role,username,active) VALUES(?,?,?,?,1)",(ph,f.get('password',''),f.get('role','tech'),ph))
    return "ok"
@app.route('/del_user/<ph>')
def delu(ph):
    if not can_edit(): return "no"
    if ph!='05344851045': qexec("DELETE FROM users WHERE phone=?",(ph,))
    return "ok"
@app.route('/change_user',methods=['POST'])
def e1():
    o=session.get('phone');n=request.form.get('newphone','').strip()
    if n.isdigit(): qexec("UPDATE users SET phone=? WHERE phone=?",(n,o));session['phone']=n
    else: qexec("UPDATE users SET username=? WHERE phone=?",(n,o))
    return "ok"
@app.route('/change_pass',methods=['POST'])
def e2(): qexec("UPDATE users SET password=? WHERE phone=?",(request.form.get('newpass',''),session.get('phone')));return "ok"
if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
