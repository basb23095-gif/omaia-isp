from flask import Flask, request, redirect, session, jsonify, Response
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, html, ipaddress, subprocess, json, socket, platform, io, csv, datetime, re, time
import psycopg2, psycopg2.extras
from psycopg2 import pool as pg_pool
import sqlite3

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "omia-sec-2026-CHANGE-ME-STRONG")
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(days=30)

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
USE_PG = bool(DATABASE_URL)

# --- Pool + Cache سريع ---
_pg_pool_obj = None
_dish_cache = {"name": None, "ts": 0}
_cnt_cache = {} # tbl -> (val, ts)
_stats_cache = {"data": None, "ts": 0}

def get_pg_pool():
    global _pg_pool_obj
    if _pg_pool_obj:
        return _pg_pool_obj
    if not USE_PG:
        return None
    try:
        _pg_pool_obj = pg_pool.SimpleConnectionPool(1, 10, dsn=DATABASE_URL, sslmode='require', connect_timeout=3)
        return _pg_pool_obj
    except Exception as e:
        print(f"[POOL ERR] {e}")
        return None

def get_conn():
    if USE_PG:
        p = get_pg_pool()
        if p:
            try:
                return p.getconn()
            except:
                pass
        return psycopg2.connect(DATABASE_URL, sslmode='require', connect_timeout=5)
    c = sqlite3.connect("omia.db", check_same_thread=False, timeout=10)
    c.row_factory = sqlite3.Row
    return c

def release_conn(conn):
    if USE_PG:
        p = get_pg_pool()
        if p:
            try:
                p.putconn(conn)
                return
            except:
                pass
    try:
        conn.close()
    except:
        pass

def esc(s): return html.escape(str(s or ''), quote=True)

def qall(q, a=()):
    conn = None
    try:
        conn = get_conn()
        if USE_PG:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(q.replace("?", "%s"), a)
            rs = [dict(r) for r in cur.fetchall()]
            cur.close()
            release_conn(conn)
            return rs
        else:
            rs = [dict(r) for r in conn.execute(q, a).fetchall()]
            conn.close()
            return rs
    except Exception as e:
        print(f"[qall] {e}")
        if conn:
            release_conn(conn)
        return []

def qone(q, a=()):
    r = qall(q, a)
    return r[0] if r else None

def qexec(q, a=()):
    conn = None
    try:
        conn = get_conn()
        if USE_PG:
            cur = conn.cursor()
            cur.execute(q.replace("?", "%s"), a)
            conn.commit()
            cur.close()
            release_conn(conn)
        else:
            conn.execute(q, a)
            conn.commit()
            conn.close()
        _cnt_cache.clear()
        _stats_cache["ts"] = 0
        return True
    except Exception as e:
        print(f"[qexec] {e} {q}")
        if conn: release_conn(conn)
        return False

def get_dish_table():
    now = time.time()
    if _dish_cache["name"] and now - _dish_cache["ts"] < 120:
        return _dish_cache["name"]
    if not USE_PG:
        return "dish_ips"
    try:
        rows = qall("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name IN ('ips','dish_ips')")
        names = [r.get('table_name') for r in rows]
        tbl = "ips" if 'ips' in names else "dish_ips"
        _dish_cache["name"] = tbl
        _dish_cache["ts"] = now
        return tbl
    except:
        return "dish_ips"

def fast_count(tbl, ttl=20):
    now = time.time()
    if tbl in _cnt_cache:
        v, ts = _cnt_cache[tbl]
        if now - ts < ttl:
            return v
    c = (qone(f"SELECT COUNT(*) as c FROM {tbl}") or {}).get('c', 0)
    _cnt_cache[tbl] = (c, now)
    return c

def get_home_stats():
    now = time.time()
    if _stats_cache["data"] and now - _stats_cache["ts"] < 20:
        return _stats_cache["data"]
    tbl = get_dish_table()
    try:
        if USE_PG:
            row = qone(f"SELECT (SELECT COUNT(*) FROM subs) as subs, (SELECT COUNT(*) FROM towers) as towers, (SELECT COUNT(*) FROM ledger) as ledger, (SELECT COUNT(*) FROM {tbl}) as dishes")
        else:
            row = qone(f"SELECT (SELECT COUNT(*) FROM subs) as subs, (SELECT COUNT(*) FROM towers) as towers, (SELECT COUNT(*) FROM ledger) as ledger, (SELECT COUNT(*) FROM {tbl}) as dishes")
        if row:
            _stats_cache["data"] = row
            _stats_cache["ts"] = now
            return row
    except:
        pass
    return {"subs": fast_count("subs"), "towers": fast_count("towers"), "ledger": fast_count("ledger"), "dishes": fast_count(tbl)}

def init():
    tables_pg = [
        "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,username TEXT)",
        "CREATE TABLE IF NOT EXISTS subs(id SERIAL PRIMARY KEY,name TEXT,phone TEXT,note TEXT)",
        "CREATE TABLE IF NOT EXISTS ledger(id SERIAL PRIMARY KEY,name TEXT,amount REAL,note TEXT,currency TEXT)",
        "CREATE TABLE IF NOT EXISTS dish_ips(id SERIAL PRIMARY KEY,ip TEXT,location TEXT,dish_name TEXT)",
        "CREATE TABLE IF NOT EXISTS towers(id SERIAL PRIMARY KEY,name TEXT,area TEXT,lat DOUBLE PRECISION,lng DOUBLE PRECISION)",
        "CREATE TABLE IF NOT EXISTS logs(id SERIAL PRIMARY KEY,user_phone TEXT,action TEXT,detail TEXT,time TEXT)",
        "CREATE TABLE IF NOT EXISTS notifications(id SERIAL PRIMARY KEY,title TEXT,msg TEXT,time TEXT,read INTEGER DEFAULT 0)",
        "CREATE TABLE IF NOT EXISTS ips(id SERIAL PRIMARY KEY, ip TEXT, location TEXT, dish_name TEXT, created_at TIMESTAMP DEFAULT NOW())"
    ]
    tables_sqlite = [t.replace("SERIAL PRIMARY KEY","INTEGER PRIMARY KEY AUTOINCREMENT").replace("DOUBLE PRECISION","REAL").replace("NOW()","CURRENT_TIMESTAMP") for t in tables_pg]
    for s in (tables_pg if USE_PG else tables_sqlite):
        qexec(s)
    qexec("CREATE INDEX IF NOT EXISTS idx_dish_ip ON dish_ips(ip)")
    qexec("CREATE INDEX IF NOT EXISTS idx_ips_ip ON ips(ip)")
    if not qone("SELECT * FROM users WHERE phone=?", ('05344851045',)):
        qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)", ('05344851045', generate_password_hash('admin2024'), 'manager', 'admin'))
    if not qone("SELECT * FROM towers WHERE name=?", ('نقطة حماة الرئيسية',)):
        qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)", ('نقطة حماة الرئيسية', 'حماة', 35.1318, 36.7578))

init()

def login_required(f):
    @wraps(f)
    def w(*a, **kw):
        if not session.get('phone'): return redirect('/login')
        return f(*a, **kw)
    return w
def is_manager():
    u = qone("SELECT * FROM users WHERE phone=?", (session.get('phone') or '',))
    return (u.get('role') or '').lower() == 'manager' if u else False
def role_required_manager(f):
    @wraps(f)
    def w(*a, **kw):
        if not is_manager(): return "ممنوع", 403
        return f(*a, **kw)
    return w
def is_valid_ip(ip):
    try: ipaddress.ip_address((ip or '').strip()); return True
    except: return False

@app.after_request
def add_headers(resp):
    if request.path.startswith('/api/'): resp.headers['Cache-Control'] = 'no-store'
    return resp

@app.route('/ping')
@app.route('/health')
def public_ping():
    return jsonify(ok=True, pg=USE_PG, table=get_dish_table(), time=datetime.datetime.now().isoformat())

@app.route('/api/ping')
@login_required
def api_ping():
    ip = request.args.get('ip','').strip()
    if not is_valid_ip(ip): return jsonify(ok=False, out='IP غير صالح')
    for port in [80,443,8080,8291,22,53]:
        s=socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.settimeout(0.8)
        try:
            if s.connect_ex((ip,port))==0: s.close(); return jsonify(ok=True, out=f'✅ {ip}:{port} مفتوح', method='tcp')
            s.close()
        except:
            try: s.close()
            except: pass
    return jsonify(ok=False, out=f'❌ {ip} لا يرد')

@app.route('/api/ping_tcp')
@login_required
def api_ping_tcp():
    ip=request.args.get('ip','').strip(); port=int(request.args.get('port','80') or 80)
    s=socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.settimeout(1.2)
    try: r=s.connect_ex((ip,port)); s.close(); return jsonify(ok=r==0, out=f'✅ {ip}:{port} مفتوح' if r==0 else f'❌ {ip}:{port} مغلق')
    except Exception as e: return jsonify(ok=False, out=str(e))

@app.route('/api/notifications')
@login_required
def api_noti():
    rows=qall("SELECT * FROM notifications ORDER BY id DESC LIMIT 20")
    unread=qone("SELECT COUNT(*) as c FROM notifications WHERE read=0")
    return jsonify(rows=rows, unread=unread.get('c',0) if unread else 0)

@app.route('/api/notifications/read', methods=['POST'])
@login_required
def api_noti_read(): qexec("UPDATE notifications SET read=1"); return jsonify(ok=True)

@app.route('/api/network_status')
@login_required
def api_network(): return jsonify(get_home_stats())

@app.route('/toggle_lang')
@login_required
def toggle_lang_route():
    session['lang']='en' if session.get('lang','ar')=='ar' else 'ar'
    return jsonify(ok=True)

@app.route('/api/login_public', methods=['POST'])
def api_login_public():
    uin=request.form.get('userin','').strip(); pw=request.form.get('password','')
    u=qone("SELECT * FROM users WHERE phone=? OR username=?", (uin,uin))
    if u and check_password_hash(u['password'], pw):
        session['phone']=u['phone']; session['username']=u.get('username') or u['phone']; session.permanent=True
        return jsonify(ok=True)
    return jsonify(ok=False, msg='خطأ بالدخول'),401

@app.route('/api/export/<tbl>')
@login_required
def api_export(tbl):
    output=io.StringIO(); output.write('\ufeff'); w=csv.writer(output); dish_tbl=get_dish_table()
    if tbl=='dishes':
        rows=qall(f"SELECT * FROM {dish_tbl} ORDER BY id DESC"); w.writerow(['ID','اسم الصحن','IP','الموقع'])
        for r in rows: w.writerow([r.get('id',''),r.get('dish_name',''),r.get('ip',''),r.get('location','')])
    elif tbl=='subs':
        rows=qall("SELECT * FROM subs ORDER BY id DESC"); w.writerow(['ID','الاسم','رقم','ملاحظة'])
        for r in rows: w.writerow([r.get('id',''),r.get('name',''),r.get('phone',''),r.get('note','')])
    else: w.writerow(['ID'])
    return Response(output.getvalue(), mimetype='text/csv; charset=utf-8', headers={'Content-Disposition': f'attachment; filename={tbl}.csv'})

@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login')
def login():
    return """<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><style>*{box-sizing:border-box;font-family:system-ui}body{margin:0;min-height:100vh;background:#0a0e2a;display:flex;align-items:center;justify-content:center;color:#fff}.card{background:#1a2035cc;border:1px solid #ffffff18;padding:26px;border-radius:22px;width:92%;max-width:380px}input{width:100%;padding:14px;margin:9px 0;background:#0f1424;border:1px solid #ffffff22;color:#fff;border-radius:14px}.btn{width:100%;padding:14px;border:0;border-radius:14px;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:900;font-size:17px;cursor:pointer}</style></head><body><div style='font-size:28px;font-weight:900;margin-bottom:14px'>OMAIA <span style='color:#ffbe4d'>ISP</span></div><div class=card><form id=loginForm><input name=userin id=userin placeholder='📱 رقم / يوزر' required><input name=password id=password type=password placeholder='🔑 كلمة السر' required><button class=btn>✨ دخول فوري</button><div id=msg style='text-align:center;margin-top:8px;color:#ff6b6b;font-size:13px'></div></form></div><script>
document.getElementById('loginForm').addEventListener('submit',async e=>{e.preventDefault();let r=await fetch('/api/login_public',{method:'POST',body:new FormData(e.target)});let j=await r.json(); if(j.ok) location.replace('/dash?v=home'); else document.getElementById('msg').textContent='خطأ بالدخول';});
</script></body></html>"""

@app.route('/logout')
def lo(): session.clear(); return redirect('/login')
@app.route('/api/logout', methods=['POST'])
def api_logout(): session.clear(); return jsonify(ok=True)
@app.route('/dash')
@login_required
def dash(): return layout(page_content(request.args.get('v','home')), request.args.get('v','home'))
@app.route('/api/page')
@login_required
def ap(): return page_content(request.args.get('v','home'))

@app.route('/api/search')
@login_required
def s():
    q=request.args.get('q','').strip()
    if not q: return jsonify([])
    like="%"+q+"%"; results=[]; dish_tbl=get_dish_table()
    try:
        for r in qall(f"SELECT * FROM {dish_tbl} WHERE ip LIKE? OR dish_name LIKE? OR location LIKE? ORDER BY id DESC LIMIT 15", (like,like,like)):
            results.append({"title":r.get('dish_name') or r.get('ip'),"sub":r.get('ip',''),"page":"dishes"})
        for r in qall("SELECT * FROM subs WHERE name LIKE? OR phone LIKE? ORDER BY id DESC LIMIT 10", (like,like)):
            results.append({"title":r.get('name',''),"sub":r.get('phone',''),"page":"subs"})
        for r in qall("SELECT * FROM towers WHERE name LIKE? OR area LIKE? ORDER BY id DESC LIMIT 10", (like,like)):
            results.append({"title":r.get('name',''),"sub":r.get('area',''),"page":"towers"})
    except: pass
    return jsonify(results[:20])

@app.route('/toggle_theme')
@login_required
def tt(): session['theme']='light' if session.get('theme','dark')=='dark' else 'dark'; return jsonify(ok=True)
@app.route('/add_dish', methods=['POST'])
@login_required
def ad():
    dish_tbl=get_dish_table(); ip=request.form.get('ip','').strip()
    if not is_valid_ip(ip): return "IP غير صالح",400
    if qone(f"SELECT * FROM {dish_tbl} WHERE ip=?", (ip,)): qexec(f"UPDATE {dish_tbl} SET dish_name=?,location=? WHERE ip=?", (request.form.get('dish_name',''),request.form.get('location',''),ip))
    else: qexec(f"INSERT INTO {dish_tbl}(ip,location,dish_name) VALUES(?,?,?)", (ip,request.form.get('location',''),request.form.get('dish_name','')))
    return "ok"
@app.route('/edit_dish/<int:i>', methods=['POST'])
@login_required
def ed(i):
    if not is_manager(): return "ممنوع",403
    qexec(f"UPDATE {get_dish_table()} SET dish_name=?,ip=?,location=? WHERE id=?", (request.form.get('dish_name',''),request.form.get('ip',''),request.form.get('location',''),i)); return "ok"
@app.route('/del_dish/<int:i>')
@login_required
def dd(i):
    if not is_manager(): return "ممنوع",403
    qexec(f"DELETE FROM {get_dish_table()} WHERE id=?", (i,)); return "ok"
@app.route('/add_tower', methods=['POST'])
@login_required
def at():
    try: la=float(request.form.get('lat') or 35.1318); ln=float(request.form.get('lng') or 36.7578)
    except: la=35.1318; ln=36.7578
    qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",(request.form.get('name',''),request.form.get('area',''),la,ln)); return "ok"
@app.route('/del_tower/<int:i>')
@login_required
def dt(i):
    if not is_manager(): return "ممنوع",403
    qexec("DELETE FROM towers WHERE id=?",(i,)); return "ok"
@app.route('/edit_tower/<int:i>', methods=['POST'])
@login_required
def et(i):
    if not is_manager(): return "ممنوع",403
    try: la=float(request.form.get('lat') or 35.1318); ln=float(request.form.get('lng') or 36.7578)
    except: la=35.1318; ln=36.7578
    qexec("UPDATE towers SET name=?,area=?,lat=?,lng=? WHERE id=?",(request.form.get('name',''),request.form.get('area',''),la,ln,i)); return "ok"
@app.route('/add_sub', methods=['POST'])
@login_required
def asub(): qexec("INSERT INTO subs(name,phone,note) VALUES(?,?,?)",(request.form.get('name',''),request.form.get('phone',''),request.form.get('note',''))); return "ok"
@app.route('/del_sub/<int:i>')
@login_required
def dsub(i):
    if not is_manager(): return "ممنوع",403
    qexec("DELETE FROM subs WHERE id=?",(i,)); return "ok"
@app.route('/edit_sub/<int:i>', methods=['POST'])
@login_required
def esub(i):
    if not is_manager(): return "ممنوع",403
    qexec("UPDATE subs SET name=?,phone=?,note=? WHERE id=?",(request.form.get('name',''),request.form.get('phone',''),request.form.get('note',''),i)); return "ok"
@app.route('/add_ledger', methods=['POST'])
@login_required
def al():
    try: amt=float(request.form.get('amount') or 0)
    except: amt=0
    qexec("INSERT INTO ledger(name,amount,note,currency) VALUES(?,?,?,?)",(request.form.get('name',''),amt,request.form.get('note',''),request.form.get('currency','USD'))); return "ok"
@app.route('/del_ledger/<int:i>')
@login_required
def dll(i):
    if not is_manager(): return "ممنوع",403
    qexec("DELETE FROM ledger WHERE id=?",(i,)); return "ok"
@app.route('/edit_ledger/<int:i>', methods=['POST'])
@login_required
def el(i):
    if not is_manager(): return "ممنوع",403
    try: amt=float(request.form.get('amount') or 0)
    except: amt=0
    qexec("UPDATE ledger SET name=?,amount=?,note=?,currency=? WHERE id=?",(request.form.get('name',''),amt,request.form.get('note',''),request.form.get('currency','USD'),i)); return "ok"
@app.route('/add_user', methods=['POST'])
@login_required
@role_required_manager
def au():
    ph=request.form.get('phone','').strip() or request.form.get('user_field','').strip()
    if qone("SELECT * FROM users WHERE phone=?",(ph,)): return "موجود",400
    qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",(ph,generate_password_hash(request.form.get('password','1234')),request.form.get('role','tech'),ph)); return "ok"
@app.route('/edit_user', methods=['POST'])
@login_required
@role_required_manager
def eu():
    old=request.form.get('old_phone','').strip(); new=request.form.get('phone','').strip() or request.form.get('user_field','').strip()
    pw=request.form.get('password','').strip(); role=request.form.get('role','tech')
    if pw: qexec("UPDATE users SET phone=?,username=?,role=?,password=? WHERE phone=?",(new,new,role,generate_password_hash(pw),old))
    else: qexec("UPDATE users SET phone=?,username=?,role=? WHERE phone=?",(new,new,role,old))
    if session.get('phone')==old: session['phone']=new
    return "ok"
@app.route('/del_user/<ph>')
@login_required
@role_required_manager
def du(ph):
    if ph=='05344851045': return "ممنوع",400
    qexec("DELETE FROM users WHERE phone=?",(ph,)); return "ok"
@app.route('/change_pass', methods=['POST'])
@login_required
def cp():
    qexec("UPDATE users SET password=? WHERE phone=?",(generate_password_hash(request.form.get('newpass','')),session.get('phone'))); return "ok"

def page_content(v):
    req_lang=request.args.get('lang') or session.get('lang','ar'); dish_tbl=get_dish_table()
    def L(ar,en): return ar if req_lang=='ar' else en
    if v=='home':
        st=get_home_stats(); ns=st.get('subs',0); nd=st.get('dishes',0); nt=st.get('towers',0); nl=st.get('ledger',0)
        logs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 3")
        log_html="".join([f"<div style='padding:6px 10px;border-bottom:1px dashed #ffffff10'><b style='color:#ffbe4d'>{esc(l.get('user_phone',''))}</b> {esc(l.get('action',''))}</div>" for l in logs])
        return f'''<div style='max-width:900px;margin:0 auto'><div style='display:grid;grid-template-columns:1fr 1fr;gap:12px'>
        <div class='card' onclick="loadPage('subs')" style='cursor:pointer'><h3 style='margin:0;color:#aab4d0;font-size:12px'>المشتركين</h3><h2 style='margin:4px 0;font-size:32px'>{ns}</h2></div>
        <div class='card' onclick="loadPage('dishes')" style='cursor:pointer'><h3 style='margin:0;color:#aab4d0;font-size:12px'>الصحون ☁ {dish_tbl}</h3><h2 style='margin:4px 0;font-size:32px'>{nd}</h2></div>
        <div class='card' onclick="loadPage('towers')" style='cursor:pointer'><h3 style='margin:0;color:#aab4d0;font-size:12px'>الأبراج</h3><h2 style='margin:4px 0;font-size:32px'>{nt}</h2></div>
        <div class='card' onclick="loadPage('ledger')" style='cursor:pointer'><h3 style='margin:0;color:#aab4d0;font-size:12px'>الحسابات</h3><h2 style='margin:4px 0;font-size:32px'>{nl}</h2></div></div>
        <div class=card style='margin-top:12px'><h4>📜 آخر النشاطات</h4>{log_html or 'لا يوجد'}</div></div>'''
    if v=='ping':
        return f'''<div style='max-width:800px;margin:0 auto'><div class=card><h3>📶 Ping سريع - {dish_tbl}</h3>
        <div style='display:flex;gap:8px;margin-top:10px'><input id=pingIp placeholder='192.168.1.1' style='flex:1;padding:12px;background:#0f1424;border:1px solid #ffffff20;color:#fff;border-radius:10px'><button class=btn-gold onclick="doSinglePing()">Ping</button></div>
        <div id=pingResult style='margin-top:10px;padding:12px;background:#0008;border-radius:10px;min-height:50px'>جاهز...</div></div>
        <div class=card><h4>صحون سريعة</h4><div id=quickDishes>⏳</div></div></div><script>
        async function doSinglePing(){{let ip=document.getElementById('pingIp').value.trim(); if(!ip) return; let o=document.getElementById('pingResult'); o.textContent='⏳ '+ip; try{{let r=await fetch('/api/ping?ip='+ip); let j=await r.json(); o.textContent=j.out; o.style.color=j.ok?'#22c55e':'#ef4444';}}catch(e){{o.textContent='❌ '+e;}}}}
        (async()=>{{try{{let r=await fetch('/api/search?q=192'); let d=await r.json(); let h=''; d.filter(x=>x.page==='dishes').slice(0,6).forEach(x=>{{h+='<div style="display:flex;justify-content:space-between;padding:8px;border-bottom:1px solid #ffffff08"><span>'+x.sub+'</span><button class=btn-gold onclick="document.getElementById(\\'pingIp\\').value=\\''+x.sub+'\\';doSinglePing()">Ping</button></div>';}}); document.getElementById('quickDishes').innerHTML=h;}}catch(e){{}}}})();
        </script>'''
    if v=='dishes':
        rs=qall(f"SELECT * FROM {dish_tbl} ORDER BY id DESC LIMIT 300")
        rows="".join([f'<div class="card" id="dish-{r["id"]}" data-name="{esc(r.get("dish_name") or "")}" data-ip="{esc(r.get("ip") or "")}" data-loc="{esc(r.get("location") or "")}" style="display:flex;justify-content:space-between"><div><b>{esc(r.get("dish_name") or "صحن")}</b><br><a href="http://{esc(r.get("ip") or "")}" target=_blank style="color:#ffbe4d;font-family:monospace">{esc(r.get("ip") or "")}</a></div><div><button class=btn-gold onclick="editDish({r["id"]})">✏</button> <button class=btn-del onclick="askDel(\'/del_dish/{r["id"]}\')">🗑</button></div></div>' for r in rs])
        return f'''<div style='max-width:900px;margin:0 auto'><div class=card><h3>📡 الصحون - {len(rs)}</h3><form data-ajax method=post action=/add_dish style='display:flex;gap:6px;flex-wrap:wrap'><input name=dish_name placeholder='اسم' required style='flex:1'><input name=ip placeholder='IP' required style='flex:1'><input name=location placeholder='موقع' style='flex:1'><button class=btn-gold>➕</button></form></div>{rows}</div><script>
        function editDish(id){{let c=document.getElementById('dish-'+id); document.getElementById('editModal').classList.add('show'); document.getElementById('editBody').innerHTML='<input id=ed_n value="'+c.dataset.name+'" style="width:100%;padding:10px;margin:4px 0"><input id=ed_ip value="'+c.dataset.ip+'" style="width:100%;padding:10px;margin:4px 0"><input id=ed_l value="'+c.dataset.loc+'" style="width:100%;padding:10px;margin:4px 0"><button onclick="saveDish('+id+')" class=btn-gold style="width:100%">حفظ</button>';}}
        function saveDish(id){{fetch('/edit_dish/'+id,{{method:'POST',body:new URLSearchParams({{dish_name:document.getElementById('ed_n').value,ip:document.getElementById('ed_ip').value,location:document.getElementById('ed_l').value}})}}).then(()=>{{closeEditModal(); loadPage('dishes',true);}});}}
        </script>'''
    if v=='towers':
        rs=qall("SELECT * FROM towers ORDER BY id DESC")
        rows="".join([f"<div class='card' id='tower-{r['id']}' data-name='{esc(r['name'])}' data-area='{esc(r['area'] or '')}' data-lat='{r.get('lat')}' data-lng='{r.get('lng')}' style='display:flex;justify-content:space-between'><div><b>🗼 {esc(r['name'])}</b><br><small>{esc(r['area'] or '')}</small></div><div><button class=btn-gold onclick=\"openEditTower({r['id']})\">✏</button> <button class=btn-del onclick=\"askDel('/del_tower/{r['id']}')\">🗑</button></div></div>" for r in rs])
        return f'''<div style='max-width:700px;margin:0 auto'><div class=card><h3>🗼 الأبراج</h3><form data-ajax method=post action=/add_tower style='display:flex;gap:6px;flex-wrap:wrap'><input name=name placeholder='اسم' required style='flex:1'><input name=area placeholder='منطقة' style='flex:1'><input name=lat placeholder='lat' style='width:90px'><input name=lng placeholder='lng' style='width:90px'><button class=btn-gold>➕</button></form></div>{rows}</div><script>
        function openEditTower(id){{let c=document.getElementById('tower-'+id); document.getElementById('editModal').classList.add('show'); document.getElementById('editBody').innerHTML='<input id=et_n value="'+c.dataset.name+'" style="width:100%;padding:10px"><input id=et_a value="'+c.dataset.area+'" style="width:100%;padding:10px;margin-top:6px"><input id=et_lat value="'+c.dataset.lat+'" style="width:100%;padding:10px;margin-top:6px"><input id=et_lng value="'+c.dataset.lng+'" style="width:100%;padding:10px;margin-top:6px"><button onclick="saveTower('+id+')" class=btn-gold style="width:100%;margin-top:8px">حفظ</button>';}}
        function saveTower(id){{fetch('/edit_tower/'+id,{{method:'POST',body:new URLSearchParams({{name:document.getElementById('et_n').value,area:document.getElementById('et_a').value,lat:document.getElementById('et_lat').value,lng:document.getElementById('et_lng').value}})}}).then(()=>{{closeEditModal(); loadPage('towers',true);}});}}
        </script>'''
    if v=='subs':
        rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 200")
        rows="".join([f"<div class='card' id='sub-{r['id']}' data-name='{esc(r['name'])}' data-phone='{esc(r['phone'] or '')}' data-note='{esc(r['note'] or '')}' style='display:flex;justify-content:space-between'><div><b>{esc(r['name'])}</b><br>{esc(r['phone'] or '')}</div><div><button class=btn-gold onclick=\"openEditSub({r['id']})\">✏</button> <button class=btn-del onclick=\"askDel('/del_sub/{r['id']}')\">🗑</button></div></div>" for r in rs])
        return f'''<div style='max-width:700px;margin:0 auto'><div class=card><h3>👥 المشتركين</h3><form data-ajax method=post action=/add_sub style='display:flex;gap:5px'><input name=name placeholder='الاسم' required style='flex:1'><input name=phone placeholder='رقم' style='flex:1'><button class=btn-gold>➕</button></form></div>{rows}</div><script>
        function openEditSub(id){{let c=document.getElementById('sub-'+id); document.getElementById('editModal').classList.add('show'); document.getElementById('editBody').innerHTML='<input id=es_n value="'+c.dataset.name+'" style="width:100%;padding:10px"><input id=es_p value="'+c.dataset.phone+'" style="width:100%;padding:10px;margin-top:6px"><button onclick="saveSub('+id+')" class=btn-gold style="width:100%;margin-top:8px">حفظ</button>';}}
        function saveSub(id){{fetch('/edit_sub/'+id,{{method:'POST',body:new URLSearchParams({{name:document.getElementById('es_n').value,phone:document.getElementById('es_p').value,note:''}})}}).then(()=>{{closeEditModal(); loadPage('subs',true);}});}}
        </script>'''
    if v=='ledger':
        rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 200")
        rows="".join([f"<div class='card' style='display:flex;justify-content:space-between'><div>{esc(r['name'])} - <b style='color:#ffbe4d'>{r['amount']}</b></div><button class=btn-del onclick=\"askDel('/del_ledger/{r['id']}')\">🗑</button></div>" for r in rs])
        return f'''<div style='max-width:700px;margin:0 auto'><div class=card><h3>📒 الحسابات</h3><form data-ajax method=post action=/add_ledger style='display:flex;gap:5px'><input name=name placeholder='الاسم' required style='flex:1'><input name=amount type=number step=0.01 placeholder='المبلغ' required style='flex:1'><button class=btn-gold>➕</button></form></div>{rows}</div>'''
    if v=='logs':
        rs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 200")
        rows="".join([f"<div class='card' style='font-size:13px'><b style='color:#ffbe4d'>{esc(r['user_phone'])}</b> {esc(r['action'])}<br><small style='color:#777'>{esc(r['time'])}</small></div>" for r in rs])
        return f"<div style='max-width:900px;margin:0 auto'>{rows or 'لا يوجد'}</div>"
    if v=='network':
        dish_tbl=get_dish_table(); dishes=qall(f"SELECT * FROM {dish_tbl} ORDER BY id DESC LIMIT 100")
        rows="".join([f"<div class='card' id='net-{d['id']}' data-ip='{esc(d.get('ip',''))}' style='display:flex;justify-content:space-between'><div>{esc(d.get('dish_name') or 'صحن')} - {esc(d.get('ip',''))}<br><small class='net-out'>⏳</small></div><button class=btn-gold onclick='checkOne({d['id']})'>📶</button></div>" for d in dishes])
        return f'''<div style='max-width:800px;margin:0 auto'><div class=card><h3>📊 حالة الشبكة LIVE</h3><button class=btn-gold onclick='checkAll()' style='width:100%'>🚀 فحص الكل</button><div id=summary style='margin-top:8px'></div></div>{rows}<script>
        async function checkOne(id){{let c=document.getElementById('net-'+id); let o=c.querySelector('.net-out'); o.textContent='⏳'; try{{let r=await fetch('/api/ping?ip='+c.dataset.ip); let j=await r.json(); o.textContent=j.out; o.style.color=j.ok?'#22c55e':'#ef4444';}}catch(e){{o.textContent='❌';}}}}
        async function checkAll(){{for(let c of document.querySelectorAll('[id^=net-]')){{checkOne(c.id.split('-')[1]); await new Promise(r=>setTimeout(r,150));}}}}
        </script></div>'''
    if v=='map':
        towers=qall("SELECT * FROM towers")
        tj=json.dumps([{"name":t['name'],"area":t.get('area') or '',"lat":float(t.get('lat') or 35.1318),"lng":float(t.get('lng') or 36.7578)} for t in towers], ensure_ascii=False)
        return f'''<div class=card style='padding:10px'><div style='display:flex;gap:6px;margin-bottom:8px;flex-wrap:wrap'><input id=mapSearch placeholder='🔍 بحث برج...' style='flex:1;min-width:140px;padding:10px;border-radius:10px;background:#1f2937;border:1px solid #ffffff15;color:#fff'><button class=btn-gold onclick="doMapSearch()">بحث</button><button class=btn-gold onclick="locateMe()" style='background:#22c55e;color:#fff'>📍 موقعي</button><span id=coordsLabel style='padding:8px;color:#ffbe4d'>📍 -</span></div><div id=map style='height:75vh;min-height:500px;border-radius:14px;background:#0f172a'></div></div><script>
        let _towers={tj}; let _map=null;
        function doMapSearch(){{let q=document.getElementById('mapSearch').value.trim().toLowerCase(); let f=_towers.find(t=>t.name.toLowerCase().includes(q)); if(f && _map) _map.flyTo([f.lat,f.lng],16);}}
        function locateMe(){{if(_map && navigator.geolocation) navigator.geolocation.getCurrentPosition(p=>{{_map.flyTo([p.coords.latitude,p.coords.longitude],16); L.marker([p.coords.latitude,p.coords.longitude]).addTo(_map).bindPopup('📍 موقعك').openPopup();}});}}
        function initMapNow(){{if(typeof L==='undefined'){{setTimeout(initMapNow,200); return;}} _map=L.map('map').setView([35.1318,36.7578],13); L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:19}}).addTo(_map); L.control.scale().addTo(_map); _towers.forEach(t=>{{L.marker([t.lat,t.lng]).addTo(_map).bindPopup('<b>'+t.name+'</b><br>'+t.area);}}); _map.on('click',e=>{{document.getElementById('coordsLabel').textContent='📍 '+e.latlng.lat.toFixed(5)+','+e.latlng.lng.toFixed(5);}}); setTimeout(()=>_map.invalidateSize(),300);}}
        initMapNow();
        </script>'''
    if v=='settings':
        us=qall("SELECT * FROM users ORDER BY phone DESC")
        uh="".join([f'<div class="card" style="display:flex;justify-content:space-between"><div>{esc(u.get("username") or "")} - {esc(u["phone"])}</div><button class=btn-del onclick="askDel(\'/del_user/{esc(u["phone"])}\')">🗑</button></div>' for u in us])
        return f'''<div style='max-width:700px;margin:0 auto'><div class=card><h3>👤 اضافة يوزر</h3><form data-ajax method=post action=/add_user style='display:flex;gap:8px'><input name=user_field placeholder='رقم' required style='flex:1'><input name=password type=password placeholder='باسورد' required style='flex:1'><select name=role style='flex:0.5'><option value=tech>فني</option><option value=manager>مدير</option></select><button class=btn-gold>➕</button></form></div>{uh}</div>'''
    return "<div class=card>ok</div>"

def layout(c, v='home'):
    cur_user=qone("SELECT * FROM users WHERE phone=?", (session.get('phone') or '',))
    if not cur_user: cur_user={}
    return f"""<html dir=rtl lang=ar><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<style>
*{{box-sizing:border-box;font-family:system-ui}}body{{margin:0;background:#0a0e2a;color:#fff;overflow-x:hidden}}
.top{{position:fixed;top:0;left:0;right:0;height:60px;background:#0f172aee;color:#fff;display:flex;align-items:center;justify-content:space-between;padding:0 14px;z-index:1003;border-bottom:1px solid #ffffff12}}
.sidebar{{position:fixed;right:0;top:0;width:270px;height:100%;background:#0f172a;z-index:1002;padding-top:70px;transform:translateX(110%);transition:transform.18s;overflow-y:auto}}
.sidebar.active{{transform:none}}
.sidebar a{{display:flex;gap:10px;padding:11px 14px;margin:5px 10px;color:#cbd5e1;text-decoration:none;border-radius:10px;background:#ffffff06}}
.sidebar a.active{{background:#ffbe4d;color:#111;font-weight:800}}
#overlay{{position:fixed;inset:0;background:#0008;z-index:1001;display:none}}#overlay.show{{display:block}}
.main{{margin-top:70px;padding:12px}}
.card{{background:#1e2433;padding:14px;border-radius:14px;margin-bottom:10px;border:1px solid #ffffff12}}
input,select{{padding:11px;margin:5px 0;border-radius:10px;border:1px solid #ffffff12;width:100%;background:#ffffff07;color:#fff}}
.btn-gold{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;padding:8px 14px;border:0;border-radius:10px;font-weight:800;cursor:pointer}}
.btn-del{{background:#ef4444;color:#fff;padding:7px 11px;border:0;border-radius:10px}}
#delModal,#editModal{{position:fixed;inset:0;background:#000a;display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;z-index:2000}}#delModal.show,#editModal.show{{opacity:1;pointer-events:auto}}
#delBox,#editBox{{background:#1e2433;padding:20px;border-radius:16px;width:92%;max-width:400px}}
</style></head><body>
<div id=overlay onclick="toggleSb(false)"></div>
<div class=sidebar id=sb>
<div style='padding:0 16px 8px;border-bottom:1px solid #ffffff0a'><b>OMAIA <span style='color:#ffbe4d'>ISP</span> <small style='color:#22c55e'>FAST</small></b></div>
<a href="javascript:loadPage('home')" id=nav-home>🏠 الرئيسية</a>
<a href="javascript:loadPage('ping')" id=nav-ping>📶 Ping</a>
<a href="javascript:loadPage('network')" id=nav-network>📊 الشبكة</a>
<a href="javascript:loadPage('dishes')" id=nav-dishes>📡 الصحون</a>
<a href="javascript:loadPage('towers')" id=nav-towers>🗼 الأبراج</a>
<a href="javascript:loadPage('subs')" id=nav-subs>👥 المشتركين</a>
<a href="javascript:loadPage('ledger')" id=nav-ledger>📒 الحسابات</a>
<a href="javascript:loadPage('map')" id=nav-map>🗺 الخريطة</a>
<a href="javascript:loadPage('settings')" id=nav-settings>⚙ الإعدادات</a>
<a href="javascript:logoutFast()" style='margin-top:10px;background:#ef444422'>🚪 خروج</a>
</div>
<div class=top><span onclick="toggleSb()" style='font-size:24px;cursor:pointer'>☰</span><input id=topsearch placeholder='🔍 بحث...' oninput="globalSearchTop(this.value)" style='background:#1f2937;border:1px solid #ffffff15;color:#fff;padding:8px 12px;border-radius:10px;width:42px;transition:width.2s' onfocus="this.style.width='160px'" onblur="setTimeout(()=>this.style.width='42px',200)"><div style='font-weight:900'>OMAIA <span style='color:#ffbe4d'>ISP</span></div></div>
<div id=searchResults style='position:fixed;top:64px;right:10px;left:10px;max-width:420px;margin:0 auto;background:#1e2433;border:1px solid #ffffff15;border-radius:12px;z-index:1500;display:none;max-height:50vh;overflow:auto'></div>
<div class=main id=mn>{c}</div>
<div id=delModal><div id=delBox><h3 style='text-align:center'>تأكيد الحذف؟</h3><div style='display:flex;gap:10px;margin-top:12px'><button onclick="closeDel()" style='flex:1;padding:10px;border-radius:10px'>تراجع</button><button id=delYes style='flex:1;padding:10px;border-radius:10px;background:#ef4444;color:#fff;border:0'>حذف</button></div></div></div>
<div id=editModal><div id=editBox><div style='display:flex;justify-content:space-between'><h3>✏ تعديل</h3><button onclick="closeEditModal()" style='background:#ffffff12;border:0;width:28px;height:28px;border-radius:50%'>✕</button></div><div id=editBody style='margin-top:10px'></div></div></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
let cur='{v}'; let pageCache={{}};
function toggleSb(f){{let sb=document.getElementById('sb'),ov=document.getElementById('overlay'); let o=f!==undefined?f:!sb.classList.contains('active'); sb.classList.toggle('active',o); ov.classList.toggle('show',o); ov.style.display=o?'block':'none';}}
async function loadPage(v,force=false){{cur=v; toggleSb(false); document.querySelectorAll('.sidebar a').forEach(a=>a.classList.remove('active')); let n=document.getElementById('nav-'+v); if(n) n.classList.add('active'); let mn=document.getElementById('mn'); if(!force && pageCache[v]){{mn.innerHTML=pageCache[v]; bind(); execScripts(); return;}} try{{let r=await fetch('/api/page?v='+v); let h=await r.text(); pageCache[v]=h; mn.innerHTML=h; bind(); execScripts();}}catch(e){{mn.innerHTML='<div class=card>❌ '+e+'</div>';}}}}
function execScripts(){{document.getElementById('mn').querySelectorAll('script').forEach(s=>{{try{{eval(s.textContent)}}catch(e){{}}}});}}
function bind(){{document.querySelectorAll('form[data-ajax]').forEach(f=>{{if(f.dataset.bound) return; f.dataset.bound='1'; f.onsubmit=async e=>{{e.preventDefault(); let r=await fetch(f.action,{{method:'POST',body:new FormData(f)}}); if(r.ok){{delete pageCache[cur]; loadPage(cur,true);}} else alert(await r.text());}};}});}}
function askDel(u){{window._delUrl=u; document.getElementById('delModal').classList.add('show');}}
function closeDel(){{document.getElementById('delModal').classList.remove('show');}}
window.closeEditModal=function(){{document.getElementById('editModal').classList.remove('show');}}
document.getElementById('delYes').onclick=async()=>{{if(window._delUrl){{await fetch(window._delUrl); delete pageCache[cur]; closeDel(); loadPage(cur,true);}}}};
window.globalSearchTop=async function(q){{let b=document.getElementById('searchResults'); if(!q){{b.style.display='none'; return;}} try{{let r=await fetch('/api/search?q='+encodeURIComponent(q)); let d=await r.json(); if(!d.length){{b.style.display='none'; return;}} let h=''; d.forEach(x=>{{h+='<div onclick="loadPage(\\''+x.page+'\\');b.style.display=\\'none\\'" style="padding:9px 12px;border-top:1px solid #ffffff08;cursor:pointer"><b>'+x.title+'</b> <small style="color:#888">'+x.sub+'</small></div>';}}); b.innerHTML=h; b.style.display='block';}}catch(e){{}}}};
window.logoutFast=async function(){{await fetch('/api/logout',{{method:'POST'}}); location.replace('/login');}};
bind(); execScripts();
</script></body></html>"""

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)), debug=False, threaded=True)
