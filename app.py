from flask import Flask, request, redirect, session, jsonify, Response
from colors import COLORS, logo_html
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, datetime, json, html, subprocess, platform, ipaddress, io, csv
try: import psycopg2, psycopg2.extras
except: psycopg2=None
import sqlite3

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY","omia-sec-2026-CHANGE-ME")
DATABASE_URL = os.environ.get("DATABASE_URL","").strip().replace("postgresql://","postgres://")
USE_PG = bool(DATABASE_URL.startswith("postgres://") and psycopg2)
_pg=None
def esc(s): return html.escape(str(s or ''), quote=True)
def js_esc(s): return json.dumps(str(s or ''), ensure_ascii=False)
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
            cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor);cur.execute(q.replace("?","%s"),a);rs=[dict(r) for r in cur.fetchall()];cur.close();return rs
        else: rs=[dict(r) for r in c.execute(q,a).fetchall()];cc(c);return rs
    except Exception as e: print("qall",e);cc(c);return []
def qone(q,a=()):
    r=qall(q,a);return r[0] if r else None
def qexec(q,a=()):
    c=db()
    try:
        if USE_PG: cur=c.cursor();cur.execute(q.replace("?","%s"),a);cur.close()
        else: c.execute(q,a);c.commit();cc(c)
    except Exception as e: print("qexec",e);cc(c)
def fnum(v):
    try:return float(v or 0)
    except:return 0
def init():
    ss=["CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,active INT DEFAULT 1,username TEXT)",
    "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT)",
    "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,amount REAL,typ TEXT,dt TEXT,currency TEXT)",
    "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,dish_name TEXT)",
    "CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,area TEXT,lat REAL,lng REAL)",
    "CREATE TABLE IF NOT EXISTS activity_log(id INTEGER PRIMARY KEY AUTOINCREMENT,time TEXT,action TEXT,phone TEXT,username TEXT)",
    "CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY,v TEXT)"]
    if USE_PG: ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
    for s in ss: qexec(s)
    qexec("CREATE INDEX IF NOT EXISTS idx_ip ON dish_ips(ip)")
    # settings default
    if not qone("SELECT * FROM settings WHERE k='allow_edit'"): qexec("INSERT INTO settings(k,v) VALUES('allow_edit','1')")
    if not qone("SELECT * FROM settings WHERE k='allow_del'"): qexec("INSERT INTO settings(k,v) VALUES('allow_del','1')")
    if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username,active) VALUES(?,?,?,?,1)",('05344851045',generate_password_hash('admin2024'),'manager','admin'))
init()
def get_set(k): r=qone("SELECT * FROM settings WHERE k=?",(k,));return r['v'] if r else '1'
def add_log(action):
    ph=session.get('phone','system');u=qone("SELECT username FROM users WHERE phone=?",(ph,));un=u['username'] if u else ph
    qexec("INSERT INTO activity_log(time,action,phone,username) VALUES(?,?,?,?)",(datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),action,ph,un))
def login_required(f):
    @wraps(f)
    def w(*a,**kw):
        if not session.get('phone'):
            if request.path.startswith('/api/'): return jsonify(ok=False),401
            return redirect('/login')
        return f(*a,**kw)
    return w
def manager_required(f):
    @wraps(f)
    def w(*a,**kw):
        if not session.get('phone'): return redirect('/login')
        m=qone("SELECT * FROM users WHERE phone=?",(session.get('phone'),))
        if not m or m['role']=='tech': return "ممنوع",403
        return f(*a,**kw)
    return w
def me(): return qone("SELECT * FROM users WHERE phone=?",(session.get('phone'),))
def can_edit():
    m=me()
    if not m: return False
    if m['role']=='tech': return False
    return get_set('allow_edit')=='1'
def can_del():
    m=me()
    if not m: return False
    if m['role']=='tech': return False
    return get_set('allow_del')=='1'
def is_internal_ip(ip):
    try:
        o=ipaddress.ip_address(ip.strip())
        return o.is_private and not o.is_loopback and not o.is_multicast
    except: return False
def cur_theme(): return session.get('theme','dark')

@app.route('/api/ping')
@login_required
def api_ping():
    ip=request.args.get('ip','').strip()
    if not is_internal_ip(ip): return jsonify(ok=False,out='خارج الشبكة')
    # يحاول عبر الوكيل المحلي أولا (بنج حقيقي)
    # إذا ما فيه وكيل، يرجع تعليمات
    return jsonify(ok=True,out=f'للبنج الحقيقي شغل ping_agent.py على لابتوبك ثم استخدم الزر - IP: {ip}')

def page_content(v):
    can_e=can_edit();can_d=can_del()
    if v=='home':
        ns=(qone("SELECT COUNT(*) c FROM subs") or {}).get('c',0);nd=(qone("SELECT COUNT(*) c FROM dish_ips") or {}).get('c',0);nt=(qone("SELECT COUNT(*) c FROM towers") or {}).get('c',0)
        return f"<div style='max-width:700px;margin:0 auto;text-align:center'><div style='font-size:32px'>{logo_html()}</div><div style='display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:16px'><div class=card onclick=\"loadPage('subs')\" style='cursor:pointer'><h3>👥 المشتركين</h3><h2>{ns}</h2></div><div class=card onclick=\"loadPage('dishes')\" style='cursor:pointer'><h3>📡 الصحون</h3><h2>{nd}</h2></div><div class=card onclick=\"loadPage('towers')\" style='cursor:pointer'><h3>🗼 الأبراج</h3><h2>{nt}</h2></div><div class=card onclick=\"loadPage('map')\" style='cursor:pointer'><h3>🗺 الخريطة</h3><h2>📍</h2></div></div></div>"
    if v=='dishes':
        return """<div style='max-width:900px;margin:0 auto'>
        <div class=card style='text-align:center'><h3>📡 الصحون</h3>
        <input id=searchBox placeholder='🔍 بحث IP أو اسم + Enter' oninput="instantSearch(this.value)" onkeydown="if(event.key==='Enter')instantSearch(this.value)" style='max-width:400px;margin:0 auto'>
        <form data-ajax method=post action=/add_dish style='display:flex;gap:6px;max-width:500px;margin:8px auto;flex-wrap:wrap'><input name=dish_name required placeholder='اسم الصحن' style='flex:1'><input name=ip required placeholder='IP' style='flex:1'><input name=location placeholder='موقع' style='flex:1'><button class=btn-gold>اضافة</button></form>
        <div style='display:flex;gap:6px;justify-content:center'><button class=btn-blue onclick='exportExcel()'>📊 Excel</button><button class=btn-blue onclick="window.open('/export_pdf')">📄 PDF</button></div></div>
        <div id=dishList style='display:grid;grid-template-columns:1fr 1fr;gap:10px'></div>
        <div style='text-align:center;margin:10px'><button class=btn onclick='moreDishes()'>المزيد 20</button></div>
        <script>let pg=0;async function loadD(q=""){let r=await fetch('/api/search?q='+encodeURIComponent(q)+'&page='+pg);let d=await r.json();let h="";d.forEach(x=>{h+=`<div class=card style="display:flex;justify-content:space-between;align-items:center"><div><b>📡 ${x.dish_name||''}</b><br><span class=ip-badge>${x.ip}</span><br><small>${x.location||''}</small></div><div style="display:flex;gap:6px;flex-direction:column">`+(CAN_E?`<button onclick='editDish(${x.id},"${x.dish_name}","${x.ip}","${x.location||''}")' style="width:36px;height:36px;background:#FF9800;border:0;border-radius:10px">✏️</button>`:'')+(CAN_D?`<button onclick='delItem("/del_dish/${x.id}")' style="width:36px;height:36px;background:#F44336;border:0;border-radius:10px">🗑️</button>`:'')+`<button class=btn-blue onclick='pingDish("${x.ip}")'>بينغ</button></div></div>`});if(pg==0)document.getElementById('dishList').innerHTML=h;else document.getElementById('dishList').innerHTML+=h}
        async function instantSearch(q){pg=0;loadD(q)}function moreDishes(){pg++;loadD(document.getElementById('searchBox').value)}loadD();
        function editDish(id,n,ip,loc){let nn=prompt('اسم:',n);if(nn==null)return;let i2=prompt('IP:',ip);if(i2==null)return;let l2=prompt('موقع:',loc);fetch('/edit_dish/'+id,{method:'POST',body:new URLSearchParams({dish_name:nn,ip:i2,location:l2})}).then(()=>{toast('تم التعديل');loadPage('dishes',true)})}
        </script></div>""".replace("CAN_E","1" if can_e else "0").replace("CAN_D","1" if can_d else "0")
    if v=='towers':
        rs=qall("SELECT * FROM towers ORDER BY id DESC LIMIT 40")
        cards=""
        for r in rs:
            eb=f"<button onclick='editTower({r['id']},\"{esc(r['name'])}\")' style='width:36px;height:36px;background:#FF9800;border:0;border-radius:10px'>✏️</button>" if can_e else ""
            dbtn=f"<button onclick='delItem(\"/del_tower/{r['id']}\")' style='width:36px;height:36px;background:#F44336;border:0;border-radius:10px'>🗑️</button>" if can_d else ""
            cards+=f"<div class=card style='display:flex;justify-content:space-between;align-items:center'><div><b>🗼 {esc(r['name'])}</b><br><small>{esc(r['area'] or '')}</small></div><div style='display:flex;gap:6px'>{eb}{dbtn}</div></div>"
        return f"<div style='max-width:900px;margin:0 auto'><div class=card style='text-align:center'><h3>🗼 الأبراج</h3><form data-ajax method=post action=/add_tower><input name=name required placeholder='اسم البرج'><input name=area placeholder='المنطقة'><button class=btn-gold>اضافة</button></form></div><div style='display:grid;grid-template-columns:1fr 1fr;gap:10px'>{cards}</div><script>function editTower(id,n){{let nn=prompt('اسم:',n);if(nn==null)return;fetch('/edit_tower/'+id,{{method:'POST',body:new URLSearchParams({{name:nn}})}}).then(()=>loadPage('towers',true))}}</script></div>"
    if v=='subs':
        rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 20")
        rows="".join([f"<div class=card><b>{esc(r['name'])}</b> - {esc(r['phone'] or '')}</div>" for r in rs])
        return f"<div style='max-width:600px;margin:0 auto'><div class=card style='text-align:center'><h3>👥 المشتركين</h3><form data-ajax method=post action=/add_sub><input name=name required placeholder='الاسم'><input name=phone placeholder='هاتف'><button class=btn-gold>اضافة</button></form></div>{rows}</div>"
    if v=='ledger':
        rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 20")
        rows="".join([f"<div class=card>{esc(r['name'])} - {r['amount']}</div>" for r in rs])
        return f"<div style='max-width:600px;margin:0 auto'><div class=card style='text-align:center'><h3>📒 الحسابات</h3><form data-ajax method=post action=/add_ledger><input name=name required placeholder='الاسم'><input name=amount type=number step=0.01 required placeholder='مبلغ'><button class=btn-gold>اضافة</button></form></div>{rows}</div>"
    if v=='map':
        towers=qall("SELECT * FROM towers");tj=json.dumps([{"name":t['name'],"lat":float(t.get('lat') or 35.13),"lng":float(t.get('lng') or 36.75)} for t in towers],ensure_ascii=False)
        return "<div class=card><input id=mapSearch placeholder='ابحث + Enter يروح للموقع' onkeydown='if(event.key===\"Enter\")mapGo(this.value)' style='max-width:400px'><div id=map style='height:65vh;border-radius:12px'></div><script>var _t="+tj+";var map=L.map('map').setView([35.1318,36.7578],13);L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{maxZoom:19}).addTo(map);setTimeout(()=>map.invalidateSize(),400);_t.forEach(t=>L.marker([t.lat,t.lng]).addTo(map).bindPopup(t.name));window.mapGo=function(q){let f=_t.find(t=>t.name.includes(q));if(f)map.flyTo([f.lat,f.lng],17);else toast('غير موجود')};</script></div>"
    if v=='logs':
        rs=qall("SELECT * FROM activity_log ORDER BY id DESC LIMIT 50")
        rows="".join([f"<div class=log-row><b>{esc(r['username'] or r['phone'])}</b> ({esc(r['phone'])}) - {esc(r['action'])} <small>{esc(r['time'])}</small></div>" for r in rs])
        return f"<div style='max-width:650px;margin:0 auto'><div class=card><h3>📜 السجل</h3>{rows}</div></div>"
    if v=='support':
        return f"<div style='max-width:500px;margin:20px auto'><div class=card style='text-align:center'><h2>{logo_html()}</h2><a href='https://wa.me/905344851045' target=_blank style='background:#25D366;color:#fff;padding:12px 24px;border-radius:24px;text-decoration:none;display:inline-block;margin:6px'>💬 واتساب</a><br><a href='https://instagram.com/af_20_1999' target=_blank style='background:#E1306C;color:#fff;padding:12px 24px;border-radius:24px;text-decoration:none;display:inline-block;margin:6px'>📸 af_20_1999</a></div></div>"
    if v=='settings':
        ae=get_set('allow_edit');ad=get_set('allow_del')
        us=qall("SELECT * FROM users")
        uh=""
        for u in us:
            role_ar='فني' if u['role']=='tech' else 'مدير'
            uh+=f"<div class=card style='display:flex;justify-content:space-between'><div><b>{esc(u['username'])}</b><br><small>{esc(u['phone'])}</small><br><span style='background:#333;padding:2px 8px;border-radius:10px'>{role_ar}</span></div></div>"
        return f"<div style='max-width:600px;margin:0 auto'><div class=card style='text-align:center'><h3>⚙ الإعدادات</h3><label>تفعيل التعديل <input type=checkbox {'checked' if ae=='1' else ''} onchange=\"fetch('/set/allow_edit/'+(this.checked?'1':'0'))\"></label><br><label>تفعيل الحذف <input type=checkbox {'checked' if ad=='1' else ''} onchange=\"fetch('/set/allow_del/'+(this.checked?'1':'0'))\"></label><br><button class=btn onclick='toggleTheme()'>🌓 ليل/نهار</button><form data-ajax method=post action=/change_pass style='margin-top:8px'><input name=newpass type=password required placeholder='كلمة سر جديدة'><button class=btn-gold>تغيير</button></form></div><div class=card style='text-align:center'><h3>اضافة مستخدم</h3><form data-ajax method=post action=/add_user><input name=phone required placeholder='يوزر'><input name=password type=password required placeholder='كلمة السر'><select name=role><option value=tech>فني</option><option value=manager>مدير</option></select><button class=btn-gold>اضافة</button></form></div>{uh}</div>"
    return "ok"

def layout(c,v='home'):
    th=cur_theme();bg=COLORS.get('bg_dark' if th=='dark' else 'bg_light','#0a1938');card=COLORS.get('card_dark','#222');txt='#fff';gold=COLORS.get('gold','#ffbe4d')
    return f"<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><link rel='stylesheet' href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'><style>*{{box-sizing:border-box;font-family:sans-serif}}body{{margin:0;background:{bg};color:{txt}}}.sidebar{{position:fixed;right:-280px;top:0;width:260px;height:100%;background:#111;z-index:1000;padding-top:70px;transition:.25s}}.sidebar.active{{right:0}}.sidebar a{{display:block;padding:12px;color:#fff;text-decoration:none}}.top{{position:fixed;top:0;left:0;right:0;height:60px;background:#1a1a1a;display:flex;align-items:center;justify-content:space-between;padding:0 12px;z-index:101}}.main{{margin-top:60px;padding:8px}}.card{{background:{card};padding:12px;border-radius:12px;margin-bottom:10px;border:1px solid #333}}input,select{{width:100%;padding:10px;margin:4px 0;background:#111;border:1px solid #444;color:#fff;border-radius:8px}}.btn-gold{{background:{gold};color:#000;padding:10px;border:0;border-radius:8px;font-weight:bold}}.btn-blue{{background:#2196F3;color:#fff;padding:8px;border:0;border-radius:8px}}.btn{{background:#333;color:#fff;padding:8px;border:0;border-radius:8px}}.ip-badge{{background:#000;color:{gold};padding:3px 8px;border-radius:10px;font-family:monospace}}#toast{{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:#333;color:#fff;padding:10px 20px;border-radius:20px;display:none;z-index:9999}}.log-row{{padding:6px;border-bottom:1px solid #333;font-size:13px}}@media(max-width:768px){{*{{animation:none!important;transition:none!important}}}}</style></head><body><div id=toast></div><div class=sidebar id=sb><a href=\"javascript:loadPage('home')\">🏠 الرئيسية</a><a href=\"javascript:loadPage('dishes')\">📡 الصحون</a><a href=\"javascript:loadPage('towers')\">🗼 الأبراج</a><a href=\"javascript:loadPage('map')\">🗺 الخريطة</a><a href=\"javascript:loadPage('logs')\">📜 السجل</a><a href=\"javascript:loadPage('support')\">🛠 الدعم</a><a href=\"javascript:loadPage('settings')\">⚙ الإعدادات</a><a href=/logout>🚪 خروج</a></div><div class=top><div onclick=\"document.getElementById('sb').classList.toggle('active')\" style='font-size:22px'>☰</div><div>{logo_html()}</div><div><button class=btn onclick=\"loadPage(cur,true)\">↻</button></div></div><div class=main id=mn>{c}</div><script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script><script>let cur='{v}';let cache={{}};function toast(m){{let t=document.getElementById('toast');t.textContent=m;t.style.display='block';setTimeout(()=>t.style.display='none',2000)}}async function loadPage(v,f){{cur=v;document.getElementById('sb').classList.remove('active');try{{let ch=localStorage.getItem('p_'+v);if(ch&&!f){{document.getElementById('mn').innerHTML=ch;exe()}}}}catch(e){{}}if(cache[v]&&!f){{document.getElementById('mn').innerHTML=cache[v];exe();return}}let r=await fetch('/api/page?v='+v);let h=await r.text();cache[v]=h;try{{localStorage.setItem('p_'+v,h)}}catch(e){{}}document.getElementById('mn').innerHTML=h;exe();if('serviceWorker' in navigator){{}}}}function exe(){{document.getElementById('mn').querySelectorAll('script').forEach(s=>{{try{{eval(s.textContent)}}catch(e){{}}}});bind()}}function bind(){{document.querySelectorAll('form[data-ajax]').forEach(f=>{{f.onsubmit=async e=>{{e.preventDefault();await fetch(f.action,{{method:'POST',body:new FormData(f)}});Object.keys(cache).forEach(k=>delete cache[k]);toast('تم ✅');loadPage(cur,true)}}}})}}window.delItem=async function(u){{if(!confirm('حذف؟'))return;await fetch(u);Object.keys(cache).forEach(k=>delete cache[k]);toast('انحذف');loadPage(cur,true)}};window.pingDish=async function(ip){{toast('بينغ '+ip+'...');try{{let r=await fetch('http://localhost:5001/ping?ip='+ip);let j=await r.json();toast(j.out.slice(0,120))}}catch(e){{let r2=await fetch('/api/ping?ip='+ip);let j2=await r2.json();toast(j2.out.slice(0,120))}}}};window.toggleTheme=async()=>{{await fetch('/toggle_theme');location.reload()}};window.exportExcel=()=>{{window.open('/export_excel')}};setInterval(async()=>{{try{{await fetch('/api/page?v=home',{cache:'no-store'})}}catch(e){{}}}},60000);bind();exe();</script></body></html>"

@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')
@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        uin=request.form.get('userin','').strip();pw=request.form.get('password','')
        u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
        if u and check_password_hash(u['password'],pw): session['phone']=u['phone'];session['role']=u['role'];add_log("دخول");return redirect('/dash')
        return "<script>alert('خطأ');location.href='/login'</script>"
    return f"<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'></head><body style='background:#0a1938;color:#fff;text-align:center;padding:40px'>{logo_html()}<h2>OMAIA</h2><form method=post><input name=userin placeholder='يوزر' style='padding:10px;margin:5px'><br><input name=password type=password placeholder='كلمة السر' style='padding:10px;margin:5px'><br><button style='background:#ffbe4d;padding:10px 30px;border:0;border-radius:8px'>دخول</button></form></body></html>"
@app.route('/logout')
def lo(): session.clear();return redirect('/login')
@app.route('/dash')
@login_required
def dash(): return layout(page_content(request.args.get('v','home')),request.args.get('v','home'))
@app.route('/api/page')
@login_required
def ap(): return page_content(request.args.get('v','home'))
@app.route('/api/search')
@login_required
def s():
    q=request.args.get('q','').strip();pg=int(request.args.get('page',0));off=pg*20
    if q: return jsonify(qall(f"SELECT * FROM dish_ips WHERE ip LIKE? OR dish_name LIKE? ORDER BY id DESC LIMIT 20 OFFSET {off}",("%"+q+"%","%"+q+"%")))
    return jsonify(qall(f"SELECT * FROM dish_ips ORDER BY id DESC LIMIT 20 OFFSET {off}"))
@app.route('/toggle_theme')
@login_required
def tt(): session['theme']='light' if cur_theme()=='dark' else 'dark';return "ok"
@app.route('/set/<k>/<v>')
@manager_required
def setv(k,v): qexec("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v" if USE_PG else "INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)",(k,v));return "ok"
@app.route('/add_dish',methods=['POST'])
@login_required
def ad():
    ip=request.form.get('ip','').strip()
    if not is_internal_ip(ip): return "IP غير داخلي",400
    qexec("INSERT INTO dish_ips(ip,location,dish_name) VALUES(?,?,?)",(ip,request.form.get('location',''),request.form.get('dish_name','')));add_log("اضافة صحن "+ip);return "ok"
@app.route('/edit_dish/<int:i>',methods=['POST'])
@login_required
def ed(i):
    if not can_edit(): return "ممنوع",403
    qexec("UPDATE dish_ips SET dish_name=?,ip=?,location=? WHERE id=?",(request.form.get('dish_name',''),request.form.get('ip','').strip(),request.form.get('location',''),i));add_log("تعديل صحن");return "ok"
@app.route('/del_dish/<int:i>')
@login_required
def dd(i):
    if not can_del(): return "ممنوع",403
    qexec("DELETE FROM dish_ips WHERE id=?",(i,));add_log("حذف صحن");return "ok"
@app.route('/add_tower',methods=['POST'])
@login_required
def at():
    qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",(request.form.get('name',''),request.form.get('area',''),35.1318,36.7578));add_log("اضافة برج");return "ok"
@app.route('/edit_tower/<int:i>',methods=['POST'])
@login_required
def et(i):
    if not can_edit(): return "ممنوع",403
    qexec("UPDATE towers SET name=? WHERE id=?",(request.form.get('name',''),i));return "ok"
@app.route('/del_tower/<int:i>')
@login_required
def dt(i):
    if not can_del(): return "ممنوع",403
    qexec("DELETE FROM towers WHERE id=?",(i,));return "ok"
@app.route('/add_sub',methods=['POST'])
@login_required
def asub(): qexec("INSERT INTO subs(name,phone) VALUES(?,?)",(request.form.get('name',''),request.form.get('phone','')));return "ok"
@app.route('/add_ledger',methods=['POST'])
@login_required
def al(): qexec("INSERT INTO ledger(name,amount,typ,dt,currency) VALUES(?,?,?,?,?)",(request.form.get('name',''),fnum(request.form.get('amount')), 'دين', datetime.datetime.now().isoformat(),'USD'));return "ok"
@app.route('/add_user',methods=['POST'])
@manager_required
def au():
    ph=request.form.get('phone','').strip()
    if qone("SELECT * FROM users WHERE phone=?",(ph,)): return "موجود",400
    qexec("INSERT INTO users(phone,password,role,username,active) VALUES(?,?,?,?,1)",(ph,generate_password_hash(request.form.get('password','')),request.form.get('role','tech'),ph));return "ok"
@app.route('/change_pass',methods=['POST'])
@login_required
def cp(): qexec("UPDATE users SET password=? WHERE phone=?",(generate_password_hash(request.form.get('newpass','')),session.get('phone')));return "ok"
@app.route('/export_excel')
@manager_required
def ee():
    rs=qall("SELECT * FROM dish_ips");out=io.StringIO();w=csv.writer(out);w.writerow(['name','ip','location'])
    for r in rs: w.writerow([r['dish_name'],r['ip'],r['location']])
    return Response(out.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment;filename=dishes.csv'})
@app.route('/export_pdf')
@manager_required
def ep():
    rs=qall("SELECT * FROM dish_ips")
    h="<h1>Dishes</h1><table border=1>"+"".join([f"<tr><td>{esc(r['dish_name'])}</td><td>{esc(r['ip'])}</td></tr>" for r in rs])+"</table>"
    return h
@app.route('/backup')
@manager_required
def bk(): return jsonify(towers=qall("SELECT * FROM towers"),dishes=qall("SELECT * FROM dish_ips"))

if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
