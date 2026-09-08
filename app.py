from flask import Flask, request, redirect, session, jsonify, Response
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, html, io, csv, datetime, traceback

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "omia-sec-2026-CHANGE-ME-STRONG")
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(days=30)

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_PG = False
psycopg2 = None
try:
    import psycopg2 as pg_lib
    import psycopg2.extras
    psycopg2 = pg_lib
    if DATABASE_URL:
        USE_PG = True
except:
    USE_PG = False

import sqlite3

def esc(s): 
    try: return html.escape(str(s or ''), quote=True)
    except: return str(s or '')

def get_conn():
    if USE_PG and DATABASE_URL:
        try: return psycopg2.connect(DATABASE_URL, sslmode='require', connect_timeout=2)
        except: pass
    try:
        c = sqlite3.connect("omia.db", check_same_thread=False, timeout=3)
        c.row_factory = sqlite3.Row
        return c
    except:
        c = sqlite3.connect(":memory:", check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c

def qall(q, a=()):
    conn=None
    try:
        conn=get_conn()
        if USE_PG and DATABASE_URL and not isinstance(conn, sqlite3.Connection):
            cur=conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(q.replace("?", "%s"), a)
            rs=[dict(r) for r in cur.fetchall()]
            cur.close(); conn.close()
            return rs
        cur=conn.cursor()
        cur.execute(q, a)
        cols=[d[0] for d in cur.description] if cur.description else []
        rows=cur.fetchall()
        rs=[]
        for r in rows:
            try: rs.append(dict(r))
            except: rs.append({cols[i]: r[i] for i in range(len(cols))})
        conn.close()
        return rs
    except Exception as e:
        print(f"[DB qall] {e}")
        try:
            if conn: conn.close()
        except: pass
        return []

def qone(q,a=()):
    r=qall(q,a)
    return r[0] if r else None

def qexec(q,a=()):
    conn=None
    try:
        conn=get_conn()
        if USE_PG and DATABASE_URL and not isinstance(conn, sqlite3.Connection):
            cur=conn.cursor()
            cur.execute(q.replace("?", "%s"), a)
            conn.commit(); cur.close(); conn.close()
        else:
            conn.execute(q,a); conn.commit(); conn.close()
        return True
    except Exception as e:
        print(f"[DB qexec] {e}")
        try:
            if conn: conn.close()
        except: pass
        return False

def get_dish_table():
    try:
        if not USE_PG: return "dish_ips"
        rows=qall("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name IN ('ips','dish_ips')")
        names=[r.get('table_name') for r in rows]
        return "ips" if 'ips' in names else "dish_ips"
    except: return "dish_ips"

def log_action(action, detail=""):
    try:
        phone=session.get('phone','system')
        now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)",(phone,action,detail,now))
    except: pass

def init_db_safe():
    try:
        if USE_PG:
            tables=[
                "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,username TEXT)",
                "CREATE TABLE IF NOT EXISTS subs(id SERIAL PRIMARY KEY,name TEXT,phone TEXT,note TEXT)",
                "CREATE TABLE IF NOT EXISTS ledger(id SERIAL PRIMARY KEY,name TEXT,amount REAL,note TEXT,currency TEXT)",
                "CREATE TABLE IF NOT EXISTS dish_ips(id SERIAL PRIMARY KEY,ip TEXT,location TEXT,dish_name TEXT)",
                "CREATE TABLE IF NOT EXISTS towers(id SERIAL PRIMARY KEY,name TEXT,area TEXT)",
                "CREATE TABLE IF NOT EXISTS logs(id SERIAL PRIMARY KEY,user_phone TEXT,action TEXT,detail TEXT,time TEXT)",
                "CREATE TABLE IF NOT EXISTS notifications(id SERIAL PRIMARY KEY,title TEXT,msg TEXT,time TEXT,read INTEGER DEFAULT 0)",
            ]
        else:
            tables=[
                "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,username TEXT)",
                "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,note TEXT)",
                "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,amount REAL,note TEXT,currency TEXT)",
                "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,dish_name TEXT)",
                "CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,area TEXT)",
                "CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,user_phone TEXT,action TEXT,detail TEXT,time TEXT)",
                "CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,msg TEXT,time TEXT,read INTEGER DEFAULT 0)",
            ]
        for s in tables: qexec(s)
        if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)):
            qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",('05344851045',generate_password_hash('admin2024'),'manager','admin'))
        print("[INIT] OK")
    except Exception as e:
        print(f"[INIT] {e}")
        traceback.print_exc()

init_db_safe()

def login_required(f):
    @wraps(f)
    def w(*a,**kw):
        if not session.get('phone'): return redirect('/login')
        return f(*a,**kw)
    return w

@app.route('/health')
def health():
    return jsonify(ok=True, pg=USE_PG, table=get_dish_table(), time=datetime.datetime.now().isoformat())

@app.route('/fix_db')
def fix_db():
    init_db_safe()
    return jsonify(ok=True, table=get_dish_table())

@app.route('/reset_admin')
def reset_admin():
    qexec("DELETE FROM users WHERE phone=?",('05344851045',))
    qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",('05344851045',generate_password_hash('admin2024'),'manager','admin'))
    return jsonify(ok=True)

@app.route('/api/notifications')
@login_required
def api_noti():
    rows=qall("SELECT * FROM notifications ORDER BY id DESC LIMIT 20")
    unread=qone("SELECT COUNT(*) as c FROM notifications WHERE read=0")
    return jsonify(rows=rows, unread=(unread.get('c',0) if unread else 0))

@app.route('/api/notifications/read', methods=['POST'])
@login_required
def api_noti_read():
    qexec("UPDATE notifications SET read=1")
    return jsonify(ok=True)

@app.route('/api/login_public', methods=['POST'])
def api_login_public():
    try:
        uin=request.form.get('userin','').strip()
        pw=request.form.get('password','')
        u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
        if u and check_password_hash(u['password'], pw):
            session['phone']=u['phone']
            session.permanent=True
            log_action("دخول", uin)
            return jsonify(ok=True)
        return jsonify(ok=False, msg='خطأ بالدخول'),401
    except Exception as e:
        return jsonify(ok=False, msg=str(e)),500

@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login')
def login_page():
    return """<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<style>*{box-sizing:border-box;font-family:system-ui}body{margin:0;min-height:100vh;background:#0a0e2a;display:flex;flex-direction:column;align-items:center;justify-content:center;color:#fff;padding:14px}
.card{background:#1e2433;border:1px solid #ffffff15;padding:22px;border-radius:18px;width:92%;max-width:380px}
input{width:100%;padding:13px;margin:6px 0;background:#0f1424;border:1px solid #ffffff15;color:#fff;border-radius:12px}
.btn{width:100%;padding:13px;border:0;border-radius:12px;background:#ffbe4d;color:#111;font-weight:900;cursor:pointer}
</style></head><body>
<div style='font-size:28px;font-weight:900;margin-bottom:12px'>OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<div class=card><form id=f><input name=userin placeholder='05344851045' required><input name=password type=password placeholder='admin2024' required><button class=btn>دخول</button><div id=msg style='color:#ff6b6b;font-size:12px;margin-top:6px;text-align:center'></div></form></div>
<script>
document.getElementById('f').addEventListener('submit',async e=>{
 e.preventDefault();
 let btn=e.target.querySelector('button'); btn.textContent='⏳...';
 try{
  let r=await fetch('/api/login_public',{method:'POST',body:new FormData(e.target),cache:'no-store'});
  let j=await r.json();
  if(j.ok) location.replace('/dash?v=home');
  else {document.getElementById('msg').textContent=j.msg; btn.textContent='دخول';}
 }catch(err){document.getElementById('msg').textContent='خطأ: '+err; btn.textContent='دخول';}
});
</script></body></html>"""

@app.route('/logout')
def lo(): session.clear(); return redirect('/login')
@app.route('/api/logout', methods=['POST'])
def api_logout(): session.clear(); return jsonify(ok=True)

@app.route('/dash')
@login_required
def dash():
    v=request.args.get('v','home')
    return layout(page_content(v), v)

@app.route('/api/page')
@login_required
def ap(): return page_content(request.args.get('v','home'))

@app.route('/add_dish', methods=['POST'])
@login_required
def add_dish():
    tbl=get_dish_table()
    ip=request.form.get('ip','').strip()
    name=request.form.get('dish_name','').strip()
    if not ip: return "IP مطلوب",400
    qexec(f"INSERT INTO {tbl}(ip,dish_name) VALUES(?,?)",(ip,name))
    log_action("إضافة صحن", f"{name}-{ip}")
    return "ok"

@app.route('/del_dish/<int:i>')
@login_required
def del_dish(i):
    qexec(f"DELETE FROM {get_dish_table()} WHERE id=?",(i,))
    return "ok"

@app.route('/add_tower', methods=['POST'])
@login_required
def add_tower():
    qexec("INSERT INTO towers(name,area) VALUES(?,?)",(request.form.get('name',''),request.form.get('area','')))
    return "ok"

@app.route('/del_tower/<int:i>')
@login_required
def del_tower(i):
    qexec("DELETE FROM towers WHERE id=?",(i,))
    return "ok"

@app.route('/add_sub', methods=['POST'])
@login_required
def add_sub():
    qexec("INSERT INTO subs(name,phone) VALUES(?,?)",(request.form.get('name',''),request.form.get('phone','')))
    return "ok"

@app.route('/del_sub/<int:i>')
@login_required
def del_sub(i):
    qexec("DELETE FROM subs WHERE id=?",(i,))
    return "ok"

def page_content(v):
    tbl=get_dish_table()
    if v=='home':
        ns=(qone("SELECT COUNT(*) as c FROM subs") or {}).get('c',0)
        nd=(qone(f"SELECT COUNT(*) as c FROM {tbl}") or {}).get('c',0)
        nt=(qone("SELECT COUNT(*) as c FROM towers") or {}).get('c',0)
        logs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 4")
        log_html="".join([f"<div style='padding:6px;border-bottom:1px solid #ffffff0a;font-size:12px'><b style='color:#ffbe4d'>{esc(l.get('user_phone',''))}</b> {esc(l.get('action',''))}</div>" for l in logs])
        return f'''<div style='max-width:800px;margin:0 auto'>
        <div style='display:grid;grid-template-columns:1fr 1fr;gap:8px'>
        <div class='card' onclick="loadPage('dishes')" style='cursor:pointer'><h3>📡 {nd} صحن</h3></div>
        <div class='card' onclick="loadPage('towers')" style='cursor:pointer'><h3>🗼 {nt} برج</h3></div>
        <div class='card' onclick="loadPage('subs')" style='cursor:pointer'><h3>👥 {ns} مشترك</h3></div>
        <div class='card' onclick="loadPage('logs')" style='cursor:pointer'><h3>📜 السجل</h3></div>
        </div>
        <div class=card style='margin-top:8px'><h4>📜 السجل</h4>{log_html}<button class=btn-gold onclick="loadPage('logs')" style='width:100%;margin-top:6px'>عرض السجل</button></div>
        </div>'''
    if v=='dishes':
        rs=qall(f"SELECT * FROM {tbl} ORDER BY id DESC LIMIT 50")
        rows="".join([f'<div class="card" style="display:flex;justify-content:space-between"><div><b>{esc(r.get("dish_name") or "صحن")}</b> - {esc(r.get("ip") or "")}</div><button class=btn-del onclick="askDel(\'/del_dish/{r["id"]}\')">🗑</button></div>' for r in rs])
        return f'''<div style='max-width:700px;margin:0 auto'><div class=card><h3>📡 الصحون</h3><form data-ajax method=post action=/add_dish style='display:flex;gap:4px'><input name=dish_name placeholder='اسم' required style='flex:1'><input name=ip placeholder='IP' required style='flex:1'><button class=btn-gold>➕</button></form></div>{rows}</div>'''
    if v=='towers':
        rs=qall("SELECT * FROM towers ORDER BY id DESC")
        rows="".join([f"<div class='card' style='display:flex;justify-content:space-between'><b>{esc(r['name'])}</b><button class=btn-del onclick=\"askDel('/del_tower/{r['id']}')\">🗑</button></div>" for r in rs])
        return f'''<div style='max-width:600px;margin:0 auto'><div class=card><h3>🗼 الأبراج</h3><form data-ajax method=post action=/add_tower style='display:flex;gap:4px'><input name=name placeholder='اسم' required style='flex:1'><button class=btn-gold>➕</button></form></div>{rows}</div>'''
    if v=='subs':
        rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 100")
        rows="".join([f"<div class='card' style='display:flex;justify-content:space-between'><b>{esc(r['name'])}</b> {esc(r['phone'] or '')} <button class=btn-del onclick=\"askDel('/del_sub/{r['id']}')\">🗑</button></div>" for r in rs])
        return f'''<div style='max-width:600px;margin:0 auto'><div class=card><h3>👥 المشتركين</h3><form data-ajax method=post action=/add_sub style='display:flex;gap:4px'><input name=name placeholder='الاسم' required style='flex:1'><input name=phone placeholder='رقم' style='flex:1'><button class=btn-gold>➕</button></form></div>{rows}</div>'''
    if v=='logs':
        rs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 100")
        rows="".join([f"<div class='card' style='font-size:12px'><b style='color:#ffbe4d'>{esc(r.get('user_phone',''))}</b> {esc(r.get('action',''))} - {esc(r.get('detail',''))}<br><small style='color:#666'>{esc(r.get('time',''))}</small></div>" for r in rs])
        return f"<div style='max-width:700px;margin:0 auto'><div class=card><h3>📜 السجل</h3></div>{rows}</div>"
    return "<div class=card>✅ شغال</div>"

def layout(c, v='home'):
    # بدون f-string حتى ما يصير مشكلة method is not defined
    try:
        cur_user = qone("SELECT * FROM users WHERE phone=?",(session.get('phone') or '',)) or {}
        role = (cur_user.get('role') or 'tech')
        username_display = esc(cur_user.get('username') or cur_user.get('phone') or '')
    except:
        role='tech'
        username_display='admin'
    
    html_template = """
<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<style>
*{box-sizing:border-box;font-family:system-ui}body{margin:0;background:#0a0e2a;color:#fff}
.top{position:fixed;top:0;left:0;right:0;height:54px;background:#0f172a;color:#fff;display:flex;align-items:center;justify-content:space-between;padding:0 12px;z-index:1002;border-bottom:1px solid #ffffff10}
.sidebar{position:fixed;right:0;top:0;width:250px;height:100%;background:#0f172a;z-index:1001;padding-top:60px;transform:translateX(110%);transition:.15s}
.sidebar.active{transform:none}
.sidebar a{display:block;padding:10px 14px;margin:4px 8px;color:#ccc;text-decoration:none;background:#ffffff08;border-radius:8px}
.sidebar a.active{background:#ffbe4d;color:#111;font-weight:800}
#overlay{position:fixed;inset:0;background:#0007;z-index:1000;display:none}
#overlay.show{display:block}
.main{margin-top:60px;padding:10px}
.card{background:#1e2433;padding:10px;border-radius:10px;margin-bottom:6px;border:1px solid #ffffff0a}
input{padding:10px;border-radius:8px;border:1px solid #ffffff15;width:100%;background:#0f1424;color:#fff;margin:2px 0}
.btn-gold{background:#ffbe4d;color:#111;padding:6px 10px;border:0;border-radius:8px;font-weight:800;cursor:pointer}
.btn-del{background:#ef4444;color:#fff;padding:4px 8px;border:0;border-radius:6px}
#delModal{position:fixed;inset:0;background:#0008;display:flex;align-items:center;justify-content:center;display:none;z-index:2000}
#delModal.show{display:flex}
</style></head>
<body>
<div id="overlay" onclick="toggleSb(false)"></div>
<div class="sidebar" id="sb">
<a href="javascript:loadPage('home')" id="nav-home">🏠 الرئيسية</a>
<a href="javascript:loadPage('dishes')" id="nav-dishes">📡 الصحون</a>
<a href="javascript:loadPage('towers')" id="nav-towers">🗼 الأبراج</a>
<a href="javascript:loadPage('subs')" id="nav-subs">👥 المشتركين</a>
<a href="javascript:loadPage('logs')" id="nav-logs">📜 السجل</a>
<a href="javascript:logoutFast()">🚪 خروج</a>
<div style="padding:10px;font-size:10px;color:#666"><a href="/health" style="color:#666">health</a> | <a href="/fix_db" style="color:#22c55e">fix_db</a></div>
</div>
<div class="top"><span onclick="toggleSb()" style="cursor:pointer;background:#ffffff15;padding:6px 10px;border-radius:8px">☰</span><div style="font-weight:900">OMAIA <span style="color:#ffbe4d">ISP</span> <small style="color:#22c55e">✅ مصلح</small></div><div><a href="https://wa.me/905344851045" style="background:#22c55e;color:#fff;padding:4px 8px;border-radius:8px;text-decoration:none">💬</a></div></div>
<div class="main" id="mn">__CONTENT__</div>
<div id="delModal"><div style="background:#1e2433;padding:16px;border-radius:12px;width:90%;max-width:350px;text-align:center"><h3>حذف؟</h3><div style="display:flex;gap:6px;margin-top:10px"><button onclick="closeDel()" style="flex:1;padding:8px">لا</button><button id="delYes" style="flex:1;background:#ef4444;color:#fff;border:0;padding:8px;border-radius:8px">نعم</button></div></div></div>
<script>
let cur="__V__";
function toggleSb(f){let sb=document.getElementById('sb'),ov=document.getElementById('overlay'); let o=f!==undefined?f:!sb.classList.contains('active'); sb.classList.toggle('active',o); ov.classList.toggle('show',o);}
function loadPage(v){
 cur=v;
 document.querySelectorAll('.sidebar a').forEach(a=>a.classList.remove('active'));
 let nv=document.getElementById('nav-'+v); if(nv) nv.classList.add('active');
 toggleSb(false);
 document.getElementById('mn').innerHTML='<div class="card" style="text-align:center">⚡ جاري التحميل...</div>';
 fetch('/api/page?v='+v,{cache:'no-store'}).then(r=>r.text()).then(h=>{document.getElementById('mn').innerHTML=h; bind();}).catch(e=>{document.getElementById('mn').innerHTML='<div class="card">❌ '+e+'<br><a href="/fix_db">إصلاح</a></div>';});
}
function bind(){
 document.querySelectorAll('form[data-ajax]').forEach(f=>{if(f.dataset.bound) return; f.dataset.bound='1'; f.addEventListener('submit',e=>{e.preventDefault(); fetch(f.action,{method:'POST',body:new FormData(f)}).then(r=>{if(r.ok) loadPage(cur); else alert('خطأ');});});});
}
function askDel(u){window._delUrl=u; document.getElementById('delModal').classList.add('show');}
function closeDel(){document.getElementById('delModal').classList.remove('show');}
document.getElementById('delYes').onclick=()=>{fetch(window._delUrl).then(()=>{closeDel(); loadPage(cur);});};
function logoutFast(){fetch('/api/logout',{method:'POST'}).then(()=>location.replace('/login'));}
bind();
</script>
</body></html>
"""
    return html_template.replace("__CONTENT__", c).replace("__V__", v)

if __name__=='__main__':
    port=int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
