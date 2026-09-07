from flask import Flask, request, redirect, session, jsonify
from colors import COLORS, logo_html
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, datetime, json, html, subprocess, platform, ipaddress, socket, threading, time
try: import psycopg2, psycopg2.extras
except: psycopg2=None
import sqlite3
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY","omia-sec-2026-FINAL")
DATABASE_URL = os.environ.get("DATABASE_URL","").strip().replace("postgresql://","postgres://")
USE_PG = bool(DATABASE_URL.startswith("postgres://") and psycopg2)
_pg=None
WA="https://wa.me/905344851045"
INSTA="https://www.instagram.com/af_20_1999/"
def esc(s): return html.escape(str(s or ''),quote=True)
def js_esc(s): return json.dumps(str(s or ''),ensure_ascii=False)
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
def safe_alter(t,col,d):
    try:
        if USE_PG: qexec(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS {col} {d}")
        else:
            cols=qall(f"PRAGMA table_info({t})")
            if not any(x['name']==col for x in cols): qexec(f"ALTER TABLE {t} ADD COLUMN {col} {d}")
    except:pass
def init():
    ss=["CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,active INT DEFAULT 1,username TEXT)","CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,active INT DEFAULT 1)","CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,amount REAL,typ TEXT,dt TEXT,note TEXT,currency TEXT)","CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,lat REAL DEFAULT 0,lng REAL DEFAULT 0,dish_name TEXT,tower_name TEXT)","CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,lat REAL,lng REAL,location TEXT,fixed INT DEFAULT 0,area TEXT)","CREATE TABLE IF NOT EXISTS activity_log(id INTEGER PRIMARY KEY AUTOINCREMENT,time TEXT,action TEXT,phone TEXT,username TEXT)","CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,time TEXT,title TEXT,msg TEXT,read INT DEFAULT 0)","CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY,v TEXT)"]
    if USE_PG: ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
    for s in ss: qexec(s)
    for t,c,d in [("towers","location","TEXT"),("towers","fixed","INT DEFAULT 0"),("towers","area","TEXT"),("dish_ips","dish_name","TEXT"),("dish_ips","tower_name","TEXT"),("users","username","TEXT"),("activity_log","username","TEXT"),("settings","v","TEXT")]: safe_alter(t,c,d)
    try: qexec("CREATE INDEX IF NOT EXISTS idx_ip ON dish_ips(ip)");qexec("CREATE INDEX IF NOT EXISTS idx_name ON dish_ips(dish_name)")
    except:pass
    if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)): qexec("INSERT INTO users(phone,password,role,username,active) VALUES(?,?,?,?,?)",('05344851045',generate_password_hash('admin2024'),'manager','admin',1))
    if not qone("SELECT v FROM settings WHERE k='allow_edit'"): qexec("INSERT INTO settings(k,v) VALUES('allow_edit','1')")
    if not qone("SELECT v FROM settings WHERE k='allow_delete'"): qexec("INSERT INTO settings(k,v) VALUES('allow_delete','1')")
init()
def backup_auto():
    while True:
        time.sleep(86400)
        try:
            data={}
            for t in ["users","subs","dish_ips","towers","ledger"]:
                data[t]=qall(f"SELECT * FROM {t} LIMIT 5000")
            open("backup.json","w",encoding="utf-8").write(json.dumps(data,ensure_ascii=False))
        except:pass
threading.Thread(target=backup_auto,daemon=True).start()
def get_set(k,d="1"):
    r=qone("SELECT v FROM settings WHERE k=?",(k,));return r['v'] if r else d
def add_log(a):
    ph=session.get('phone','system');u=qone("SELECT username FROM users WHERE phone=?",(ph,));un=u['username'] if u and u.get('username') else ph
    qexec("INSERT INTO activity_log(time,action,phone,username) VALUES(?,?,?,?)",(datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),a,ph,un))
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
        if not m or m.get('role')=='tech': return "ممنوع",403
        return f(*a,**kw)
    return w
def me(): return qone("SELECT * FROM users WHERE phone=?",(session.get('phone'),))
def can_edit():
    if get_set("allow_edit")=="0": return False
    m=me();return m and m['role']!='tech'
def can_delete():
    if get_set("allow_delete")=="0": return False
    m=me();return m and m['role']!='tech'
def is_tech():
    m=me();return m and m.get('role')=='tech'
def is_internal_ip(ip):
    try:
        o=ipaddress.ip_address(ip.strip());return o.is_private and not o.is_loopback and not o.is_multicast
    except:return False
@app.route('/api/ping')
@login_required
def api_ping():
    ip=request.args.get('ip','').strip()
    if not is_internal_ip(ip): return jsonify(ok=False,out='خارج الشبكة')
    try:
        s=socket.socket();s.settimeout(1.2)
        for p in [80,8291,8728]:
            try:
                if s.connect_ex((ip,p))==0: s.close();return jsonify(ok=True,out=f'✅ {ip}:{p} متصل')
            except:pass
        s.close()
    except:pass
    try:
        w=platform.system().lower()=='windows';cmd=['ping','-n','2',ip] if w else ['ping','-c','2','-W','2',ip]
        o=subprocess.run(cmd,capture_output=True,text=True,timeout=4)
        return jsonify(ok=True,out=(o.stdout+o.stderr)[:1200])
    except Exception as e: return jsonify(ok=False,out=str(e)[:200])
@app.route('/api/search')
@login_required
def api_search():
    q=request.args.get('q','').strip();page=int(request.args.get('page',0))
    where="";a=[]
    if q: where="WHERE ip LIKE? OR dish_name LIKE?";a=[f"%{q}%",f"%{q}%"]
    rs=qall(f"SELECT * FROM dish_ips {where} ORDER BY id DESC LIMIT 20 OFFSET {page*20}",tuple(a))
    return jsonify(rs)
@app.route('/export/excel')
@login_required
def exp_excel():
    try:
        import pandas as pd;rs=qall("SELECT dish_name,ip,location FROM dish_ips")
        pd.DataFrame(rs).to_excel("/tmp/dishes.xlsx",index=False)
        return open("/tmp/dishes.xlsx","rb").read(),200,{'Content-Type':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','Content-Disposition':'attachment;filename=dishes.xlsx'}
    except Exception as e: return str(e),500
def page_content(v):
    can_e=can_edit();can_d=can_delete()
    eb="" if can_e else "disabled style='opacity:.3;pointer-events:none'"
    if v=='home':
        ns=(qone("SELECT COUNT(*) c FROM subs") or {}).get('c',0);nd=(qone("SELECT COUNT(*) c FROM dish_ips") or {}).get('c',0);nt=(qone("SELECT COUNT(*) c FROM towers") or {}).get('c',0)
        return f"<div style='max-width:700px;margin:0 auto;text-align:center'><div style='margin:20px 0'>{logo_html()}<p>OMAIA ISP</p></div><div style='display:grid;grid-template-columns:1fr 1fr;gap:12px'><div class=card onclick=\"loadPage('subs')\" style='cursor:pointer'><div style='font-size:28px'>👥</div><h3>المشتركين</h3><h2>{ns}</h2></div><div class=card onclick=\"loadPage('dishes')\" style='cursor:pointer'><div style='font-size:28px'>📡</div><h3>الصحون</h3><h2>{nd}</h2></div><div class=card onclick=\"loadPage('towers')\" style='cursor:pointer'><div style='font-size:28px'>🗼</div><h3>الأبراج</h3><h2>{nt}</h2></div><div class=card onclick=\"loadPage('map')\" style='cursor:pointer'><div style='font-size:28px'>🗺️</div><h3>الخريطة</h3><h2>📍</h2></div></div></div>"
    if v=='dishes':
        return f"""<div style='max-width:900px;margin:0 auto'><div style='display:grid;grid-template-columns:1fr 1fr;gap:12px'><div class=card style='text-align:center'><h3>📡 إضافة صحن</h3><form data-ajax method=post action=/add_dish style='display:flex;flex-direction:column;gap:8px'><input name=dish_name required placeholder='اسم الصحن'><input name=ip required placeholder='IP'><input name=location placeholder='الموقع'><button class=btn-gold>إضافة</button></form><div style='margin-top:10px'><input id=q oninput="s()" onkeydown="if(event.key=='Enter')s()" placeholder='🔍 بحث فوري IP أو اسم'><button class=btn onclick=s()>بحث</button> <button class=btn onclick="location.href='/export/excel'">📊 Excel</button></div><div id=toast style='position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:#333;color:#fff;padding:10px 20px;border-radius:20px;display:none;z-index:9999'></div></div><div id=list></div></div>
<script>
let pg=0,qq='';
function t(m){{let e=document.getElementById('toast');e.textContent=m;e.style.display='block';setTimeout(()=>e.style.display='none',2000)}}
async function s(){{qq=document.getElementById('q').value;pg=0;await load()}}
async function load(){{let r=await fetch('/api/search?q='+encodeURIComponent(qq)+'&page='+pg);let d=await r.json();let h='';d.forEach(x=>{{h+=`<div class=card style="display:grid;grid-template-columns:1fr 1fr;gap:8px"><div><b>📡 ${{x.dish_name||''}}</b><br><span class=ip-badge>${{x.ip}}</span><br><small>${{x.location||''}}</small></div><div style="display:flex;gap:6px;align-items:start;justify-content:end"><button class=btn-blue onclick="ping('${{x.ip}}')">بينغ</button>{'<button class=btn-icon edit '+eb+'>✏️</button>' if can_e else ''}{'<button class=btn-icon del onclick=delD('+''+'${x.id}'+''+')>🗑️</button>' if can_d else ''}</div></div>`}});document.getElementById('list').innerHTML=h+(d.length==20?`<button class=btn onclick="pg++;load()">التالي 20 ⏭</button>`:'');try{{localStorage.setItem('dishes_cache',document.getElementById('list').innerHTML)}}catch(e){{}}}}
async function ping(ip){{t('جاري البينغ...');let r=await fetch('/api/ping?ip='+ip);let j=await r.json();t(j.out.slice(0,80))}}
async function delD(id){{if(!confirm('حذف؟'))return;await fetch('/del_dish/'+id);t('تم الحذف');load()}}
if(!navigator.onLine){{let c=localStorage.getItem('dishes_cache');if(c)document.getElementById('list').innerHTML=c}}
load();setInterval(()=>fetch('/api/search?q=&page=0'),30000);
</script></div>"""
    if v=='towers':
        rs=qall("SELECT * FROM towers ORDER BY id DESC LIMIT 20")
        ch="".join([f"<div class=card style='display:grid;grid-template-columns:1fr auto;gap:8px;max-width:600px;margin:8px auto'><div><b>🗼 {esc(r['name'])}</b><br><small>{esc(r.get('area') or '')}</small></div><div style='display:flex;gap:6px'>{'<button class=btn-icon edit '+eb+'>✏️</button>' if can_e else ''}{'<a href=/del_tower/'+str(r['id'])+'><button class=btn-icon del>🗑️</button></a>' if can_d else ''}</div></div>" for r in rs])
        return f"<div style='max-width:650px;margin:0 auto'><div class=card style='text-align:center'><h3>🗼 الأبراج</h3><form data-ajax method=post action=/add_tower style='display:flex;flex-direction:column;gap:8px;max-width:400px;margin:auto'><input name=name required placeholder='اسم البرج'><input name=area required placeholder='المنطقة'><button class=btn-gold>إضافة</button></form></div>{ch}</div>"
    if v=='subs':
        rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 20")
        ch="".join([f"<div class=card style='display:grid;grid-template-columns:1fr auto;max-width:550px;margin:8px auto'><div><b>{esc(r['name'])}</b><br><small>{esc(r['phone'])}</small></div><div>{'<button class=btn-icon edit '+eb+'>✏️</button>' if can_e else ''}</div></div>" for r in rs])
        return f"<div style='max-width:600px;margin:0 auto'><div class=card style='text-align:center'><h3>👥 المشتركين</h3><form data-ajax method=post action=/add_sub><input name=name required placeholder='الاسم'><input name=phone placeholder='الهاتف'><button class=btn-gold>إضافة</button></form></div>{ch}</div>"
    if v=='logs':
        rs=qall("SELECT * FROM activity_log ORDER BY id DESC LIMIT 100")
        rh="".join([f"<div class=log-row><span>{esc(r['time'])}</span> <b>👤 {esc(r.get('username') or r['phone'])}</b> <span>{esc(r['action'])}</span></div>" for r in rs])
        return f"<div style='max-width:650px;margin:0 auto'><div class=card><h3 style='text-align:center'>📜 سجل النشاطات</h3>{rh}</div></div>"
    if v=='support':
        return f"<div style='max-width:500px;margin:20px auto'><div class=card style='text-align:center;border:2px solid gold'><h2>{logo_html()}</h2><p>الدعم الفني</p><div dir=ltr style='font-size:20px;font-weight:bold'>+90 534 485 10 45</div><div style='margin-top:15px;display:flex;gap:15px;justify-content:center'><a href='{WA}' target=_blank style='width:56px;height:56px;background:#25D366;border-radius:50%;display:flex;align-items:center;justify-content:center'><svg viewBox='0 0 32 32' width='30' height='30' fill='white'><path d='M16 3C9.4 3 4 8.4 4 15c0 2.4.7 4.7 2 6.7L4 29l7.5-2c2.6 4 1 6.5 1 6.6 0 12-5.4 12-12S22.6 3 16 3z'/></svg></a><a href='{INSTA}' target=_blank style='width:56px;height:56px;background:#E1306C;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:28px;text-decoration:none'>📸</a></div><div style='margin-top:10px;color:#aaa'>af_20_1999</div></div></div>"
    if v=='settings':
        us=qall("SELECT phone,username,role FROM users")
        uh="".join([f"<div class=card style='max-width:550px;margin:8px auto;display:flex;justify-content:space-between'><div><div class=avatar>{esc((u.get('username') or 'U')[:1])}</div><b>{esc(u.get('username') or '')}</b><br><small>{esc(u['phone'])}</small><br><small>{'فني' if u['role']=='tech' else 'مدير'}</small></div></div>" for u in us])
        ae=get_set("allow_edit");ad=get_set("allow_delete")
        return f"<div style='max-width:650px;margin:0 auto'><div class=card style='text-align:center'><h3>⚙ الإعدادات</h3><label><input type=checkbox {'checked' if ae=='1' else ''} onchange="fetch('/set/allow_edit/'+(this.checked?'1':'0')).then(()=>location.reload())"> تشغيل زر التعديل</label><br><label><input type=checkbox {'checked' if ad=='1' else ''} onchange="fetch('/set/allow_delete/'+(this.checked?'1':'0')).then(()=>location.reload())"> تشغيل زر الحذف</label><br><br><button class=btn onclick=toggleTheme()>🌓 ليل/نهار</button></div><div class=card style='text-align:center'><h3>➕ إضافة مستخدم</h3><form data-ajax method=post action=/add_user><input name=phone required placeholder='يوزر / رقم'><input name=password type=password required placeholder='كلمة السر'><select name=role><option value=tech>فني</option><option value=manager>مدير</option></select><button class=btn-gold>إضافة</button></form></div>{uh}</div>"
    if v=='map':
        tw=qall("SELECT * FROM towers");tj=json.dumps([{"name":t['name'],"lat":float(t.get('lat') or 35.13),"lng":float(t.get('lng') or 36.75)} for t in tw],ensure_ascii=False)
        return f"<div class=card><div id=map style='height:60vh'></div><input id=mq onkeydown=\"if(event.key=='Enter')goM()\" placeholder='ابحث IP و Enter يروح للموقع'><link rel='stylesheet' href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'/><script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script><script>let map=L.map('map').setView([35.13,36.75],12);L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}').addTo(map);let tw={tj};tw.forEach(t=>L.marker([t.lat,t.lng]).addTo(map).bindPopup(t.name));window.goM=function(){{let q=document.getElementById('mq').value;fetch('/api/search?q='+q).then(r=>r.json()).then(d=>{{if(d[0])map.flyTo([35.13,36.75],16)}})}}<\/script></div>"
    return "ok"
def layout(c,v='home'):
    bg=COLORS.get('bg_dark',COLORS.get('bg','#0a1938'));card=COLORS.get('card_dark','#1e1e1e');txt=COLORS.get('white','#fff');gold=COLORS.get('gold','#ffbe4d')
    return f"""<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><style>*{{box-sizing:border-box;font-family:sans-serif}}body{{margin:0;background:{bg};color:{txt}}}@media(max-width:768px){{*{{animation:none!important;transition:none!important}}}}.sidebar{{position:fixed;right:-300px;top:0;width:280px;height:100%;background:#111;transition:.3s;z-index:1000;padding-top:70px}}.sidebar.active{{right:0}}.sidebar a{{display:block;padding:12px 16px;color:{txt};text-decoration:none}}.top{{position:fixed;top:0;left:0;right:0;background:#1a1a1a;padding:0 16px;height:60px;display:flex;align-items:center;justify-content:space-between;z-index:101}}.main{{margin-top:60px;padding:12px}}.card{{background:{card};padding:16px;border-radius:14px;margin-bottom:12px;border:1px solid #333}}.btn{{background:#333;color:{txt};padding:8px 14px;border-radius:10px;border:0;cursor:pointer}}.btn-gold{{background:{gold};color:#000;padding:10px 18px;border-radius:10px;border:0;font-weight:bold;cursor:pointer}}.btn-blue{{background:#2196F3;color:#fff;padding:8px 14px;border-radius:10px;border:0;cursor:pointer}}.btn-icon{{width:38px;height:38px;border-radius:12px;border:0;cursor:pointer;font-size:18px}}.btn-icon.edit{{background:#FF9800;color:#fff}}.btn-icon.del{{background:#F44336;color:#fff}}.ip-badge{{background:#000;color:{gold};padding:4px 10px;border-radius:15px;font-family:monospace}}input,select{{width:100%;padding:10px;background:#111;border:1px solid #444;border-radius:8px;color:{txt};margin:4px 0}}.log-row{{padding:6px;border-bottom:1px solid #333;font-size:13px}}.avatar{{width:36px;height:36px;border-radius:50%;background:{gold};display:flex;align-items:center;justify-content:center;color:#000;font-weight:bold}}</style></head><body>
<div class=sidebar id=sb><a href="javascript:loadPage('home')">🏠 الرئيسية</a><a href="javascript:loadPage('dishes')">📡 الصحون</a><a href="javascript:loadPage('towers')">🗼 الأبراج</a><a href="javascript:loadPage('subs')">👥 المشتركين</a><a href="javascript:loadPage('map')">🗺 الخريطة</a><a href="javascript:loadPage('logs')">📜 السجل</a><a href="javascript:loadPage('support')">🛠 الدعم</a><a href="javascript:loadPage('settings')">⚙ الإعدادات</a><a href=/logout>🚪 خروج</a></div>
<div class=top><div onclick="document.getElementById('sb').classList.toggle('active')" style='font-size:22px;cursor:pointer'>☰</div><div>{logo_html()}</div><div><button class=btn onclick='loadPage(cur,true)'>↻</button></div></div>
<div class=main id=mn>{c}</div>
<script>
let cur='{v}';const cache={{}};
async function loadPage(v,f=false){{cur=v;document.getElementById('sb').classList.remove('active');if(cache[v]&&!f){{document.getElementById('mn').innerHTML=cache[v];bind();return}}let r=await fetch('/api/page?v='+v);let h=await r.text();cache[v]=h;document.getElementById('mn').innerHTML=h;bind();try{{localStorage.setItem('last_'+v,h)}}catch(e){{}}}}
function bind(){{document.querySelectorAll('form[data-ajax]').forEach(f=>{{f.onsubmit=async e=>{{e.preventDefault();await fetch(f.action,{{method:'POST',body:new FormData(f)}});Object.keys(cache).forEach(k=>delete cache[k]);loadPage(cur,true)}}}});document.getElementById('mn').querySelectorAll('script').forEach(s=>{{try{{eval(s.textContent)}}catch(e){{}}}})}}
function toggleTheme(){{fetch('/toggle_theme').then(()=>location.reload())}}
if(!navigator.onLine){{let c=localStorage.getItem('last_'+cur);if(c)document.getElementById('mn').innerHTML=c}}
bind();</script></body></html>"""
@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')
@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        uin=request.form.get('userin','').strip();pw=request.form.get('password','')
        u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
        if u and check_password_hash(u['password'],pw):
            session['phone']=u['phone'];add_log(f"دخول {uin}");return redirect('/dash')
        return "<script>alert('خطأ');location.href='/login'</script>"
    bg=COLORS.get('bg','#0a1938');gold=COLORS.get('gold','#ffbe4d')
    return f"""<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><style>body{{background:{bg};color:#fff;font-family:sans-serif;text-align:center;padding:30px}}input{{padding:12px;margin:6px;width:280px;border-radius:10px;border:1px solid {gold};background:#1e1e1e;color:#fff;text-align:center}}button{{background:{gold};padding:12px 40px;border:0;border-radius:12px;font-weight:bold;cursor:pointer}}</style></head><body>{logo_html()}<h2>OMAIA ISP</h2><form method=post id=lf><input id=uin name=userin placeholder='يوزر / هاتف'><br><input id=pw name=password type=password placeholder='كلمة السر'><br><label style='display:flex;align-items:center;justify-content:center;gap:8px;margin:10px'><input type=checkbox id=rm style='width:18px'> حفظ كلمة السر</label><button>دخول</button></form><div style='margin-top:20px'><div style='color:#aaa;font-size:14px'>الدعم الفني</div><a href='{WA}' target=_blank style='display:inline-block;width:56px;height:56px;background:#25D366;border-radius:50%;margin-top:8px'><svg viewBox='0 0 32 32' width='32' height='32' style='margin-top:12px' fill='white'><path d='M16 3C9.4 3 4 8.4 4 15c0 2.4.7 4.7 2 6.7L4 29l7.5-2c2.6 4 1 6.5 1 6.6 0 12-5.4 12-12S22.6 3 16 3z'/></svg></a></div><script>window.onload=function(){{let u=localStorage.getItem('omia_u'),p=localStorage.getItem('omia_p');if(u)document.getElementById('uin').value=u;if(p){{document.getElementById('pw').value=p;document.getElementById('rm').checked=true}}}};document.getElementById('lf').onsubmit=function(){{if(document.getElementById('rm').checked){{localStorage.setItem('omia_u',document.getElementById('uin').value);localStorage.setItem('omia_p',document.getElementById('pw').value)}}else{{localStorage.removeItem('omia_u');localStorage.removeItem('omia_p')}}}}<\/script></body></html>"""
@app.route('/logout')
def lo(): session.clear();return redirect('/login')
@app.route('/dash')
@login_required
def dash(): return layout(page_content(request.args.get('v','home')),request.args.get('v','home'))
@app.route('/api/page')
@login_required
def ap(): return page_content(request.args.get('v','home'))
@app.route('/toggle_theme')
@login_required
def tt(): return "ok"
@app.route('/set/<k>/<v>')
@manager_required
def st(k,v):
    qexec("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=?",(k,v,v)) if USE_PG else qexec("INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)",(k,v))
    return "ok"
@app.route('/add_dish',methods=['POST'])
@login_required
def ad():
    ip=request.form.get('ip','').strip()
    if not is_internal_ip(ip): return "IP غير داخلي",400
    qexec("INSERT INTO dish_ips(dish_name,ip,location) VALUES(?,?,?)",(request.form.get('dish_name'),ip,request.form.get('location')))
    add_log(f"اضافة صحن {request.form.get('dish_name')}");return "ok"
@app.route('/del_dish/<int:id>')
@login_required
def dd(id):
    if not can_delete(): return "ممنوع",403
    qexec("DELETE FROM dish_ips WHERE id=?",(id,));add_log(f"حذف صحن {id}");return "ok"
@app.route('/add_tower',methods=['POST'])
@login_required
def at():
    qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",(request.form.get('name'),request.form.get('area'),35.13,36.75));add_log(f"اضافة برج {request.form.get('name')}");return "ok"
@app.route('/del_tower/<int:id>')
@login_required
def dt(id):
    if not can_delete(): return "ممنوع",403
    qexec("DELETE FROM towers WHERE id=?",(id,));return "ok"
@app.route('/add_sub',methods=['POST'])
@login_required
def asu():
    qexec("INSERT INTO subs(name,phone) VALUES(?,?)",(request.form.get('name'),request.form.get('phone')));return "ok"
@app.route('/add_user',methods=['POST'])
@manager_required
def au():
    ph=request.form.get('phone','').strip()
    if qone("SELECT * FROM users WHERE phone=?",(ph,)): return "موجود",400
    qexec("INSERT INTO users(phone,password,role,username,active) VALUES(?,?,?,?,1)",(ph,generate_password_hash(request.form.get('password')),request.form.get('role','tech'),ph));return "ok"
if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
