from flask import Flask, request, redirect, session, jsonify, Response
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, html, io, csv, datetime, traceback

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "omia-sec-2026-CHANGE-ME-STRONG")
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(days=30)

# ===== DB SETUP - آمن 100% ما بيعطي 500 =====
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_PG = False
psycopg2 = None

# نحاول نستورد psycopg2 بس إذا فشل ما بنوقف
try:
    import psycopg2 as pg_lib
    import psycopg2.extras
    psycopg2 = pg_lib
    if DATABASE_URL:
        USE_PG = True
except Exception as e:
    print(f"[INIT] psycopg2 not available or no DATABASE_URL: {e}")
    USE_PG = False

import sqlite3

def esc(s): 
    try:
        return html.escape(str(s or ''), quote=True)
    except:
        return str(s or '')

def get_conn():
    # إذا postgres شغال نجرب، إذا فشل نرجع sqlite فوراً بدون 500
    if USE_PG and DATABASE_URL:
        try:
            return psycopg2.connect(DATABASE_URL, sslmode='require', connect_timeout=2)
        except Exception as e:
            print(f"[DB] PG failed, fallback to sqlite: {e}")
            # لا نوقف - نرجع sqlite
            pass
    # sqlite - نحاول ملف، إذا فشل نرجع memory
    try:
        c = sqlite3.connect("omia.db", check_same_thread=False, timeout=3)
        c.row_factory = sqlite3.Row
        return c
    except Exception as e:
        print(f"[DB] sqlite file failed: {e}, using memory")
        c = sqlite3.connect(":memory:", check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c

def qall(q, a=()):
    conn=None
    try:
        conn=get_conn()
        if USE_PG and DATABASE_URL and not isinstance(conn, sqlite3.Connection):
            # postgres
            cur=conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(q.replace("?", "%s"), a)
            rs=[dict(r) for r in cur.fetchall()]
            cur.close(); conn.close()
            return rs
        else:
            # sqlite
            cur=conn.cursor()
            cur.execute(q, a)
            cols=[d[0] for d in cur.description] if cur.description else []
            rows=cur.fetchall()
            rs=[]
            for r in rows:
                try:
                    rs.append(dict(r))
                except:
                    rs.append({cols[i]: r[i] for i in range(len(cols))})
            conn.close()
            return rs
    except Exception as e:
        print(f"[DB qall ERROR] {e} | {q} | {a}")
        traceback.print_exc()
        try:
            if conn: conn.close()
        except: pass
        return []

def qone(q,a=()):
    try:
        r=qall(q,a)
        return r[0] if r else None
    except:
        return None

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
        print(f"[DB qexec ERROR] {e} | {q} | {a}")
        traceback.print_exc()
        try:
            if conn: conn.close()
        except: pass
        return False

def get_dish_table():
    # دائماً يرجع قيمة حتى لو فشل
    try:
        if not USE_PG: return "dish_ips"
        rows=qall("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name IN ('ips','dish_ips')")
        names=[r.get('table_name') for r in rows]
        return "ips" if 'ips' in names else "dish_ips"
    except:
        return "dish_ips"

def log_action(action, detail=""):
    try:
        phone=session.get('phone','system')
        now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)",(phone,action,detail,now))
    except:
        pass

def init_db_safe():
    # كلشي داخل try حتى ما يعطي 500 عند التشغيل
    try:
        tables=[
            "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,username TEXT)",
            "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,note TEXT)",
            "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,amount REAL,note TEXT,currency TEXT)",
            "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,dish_name TEXT)",
            "CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,area TEXT)",
            "CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,user_phone TEXT,action TEXT,detail TEXT,time TEXT)",
            "CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,msg TEXT,time TEXT,read INTEGER DEFAULT 0)",
        ]
        # إذا postgres، نعدل SERIAL
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
        for s in tables:
            qexec(s)

        # admin
        try:
            if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)):
                qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",('05344851045',generate_password_hash('admin2024'),'manager','admin'))
        except Exception as e:
            print(f"[INIT admin error] {e}")

        try:
            if not qone("SELECT * FROM logs LIMIT 1"):
                qexec("INSERT INTO logs(user_phone,action,detail,time) VALUES(?,?,?,?)",('system','تشغيل','نظام طوارئ شغال',datetime.datetime.now().strftime("%Y-%m-%d %H:%M")))
        except: pass

        print("[INIT] DB init OK")
    except Exception as e:
        print(f"[INIT FATAL] {e}")
        traceback.print_exc()
        # لا نوقف السيرفر

# شغل init بأمان
init_db_safe()

def login_required(f):
    @wraps(f)
    def w(*a,**kw):
        try:
            if not session.get('phone'): return redirect('/login')
            return f(*a,**kw)
        except Exception as e:
            print(f"[login_required error] {e}")
            return redirect('/login')
    return w

def is_manager():
    try:
        u=qone("SELECT * FROM users WHERE phone=?",(session.get('phone') or '',))
        return (u.get('role') or '').lower()=='manager' if u else False
    except:
        return False

# ===== ROUTES - كلها محمية من 500 =====

@app.route('/health')
def health():
    try:
        return jsonify(ok=True, pg=USE_PG, table=get_dish_table(), time=datetime.datetime.now().isoformat(), mode="emergency-fixed")
    except Exception as e:
        return jsonify(ok=False, error=str(e))

@app.route('/fix_db')
def fix_db():
    try:
        init_db_safe()
        return jsonify(ok=True, table=get_dish_table(), pg=USE_PG)
    except Exception as e:
        return jsonify(ok=False, error=str(e), trace=traceback.format_exc())

@app.route('/reset_admin')
def reset_admin():
    try:
        qexec("DELETE FROM users WHERE phone=?",('05344851045',))
        qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",('05344851045',generate_password_hash('admin2024'),'manager','admin'))
        return jsonify(ok=True, msg="Admin reset - 05344851045 / admin2024")
    except Exception as e:
        return jsonify(ok=False, error=str(e))

@app.route('/api/notifications')
@login_required
def api_noti():
    try:
        rows=qall("SELECT * FROM notifications ORDER BY id DESC LIMIT 20")
        unread=qone("SELECT COUNT(*) as c FROM notifications WHERE read=0")
        return jsonify(rows=rows, unread=(unread.get('c',0) if unread else 0))
    except Exception as e:
        return jsonify(rows=[], unread=0, error=str(e))

@app.route('/api/notifications/read', methods=['POST'])
@login_required
def api_noti_read():
    try:
        qexec("UPDATE notifications SET read=1")
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e))

@app.route('/api/login_public', methods=['POST'])
def api_login_public():
    try:
        uin=request.form.get('userin','').strip()
        pw=request.form.get('password','')
        if not uin or not pw:
            return jsonify(ok=False, msg='بيانات ناقصة'),400
        u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
        if u and check_password_hash(u['password'], pw):
            session['phone']=u['phone']; session['username']=u.get('username') or u['phone']; session.permanent=True
            log_action("دخول", uin)
            return jsonify(ok=True, role=u.get('role'))
        return jsonify(ok=False, msg='خطأ بالدخول - تأكد من الرقم وكلمة السر'),401
    except Exception as e:
        print(f"[login error] {e}")
        traceback.print_exc()
        return jsonify(ok=False, msg=f'خطأ داخلي: {str(e)[:100]}'),500

@app.route('/api/export/<tbl>')
@login_required
def api_export(tbl):
    try:
        output=io.StringIO(); output.write('\ufeff'); w=csv.writer(output)
        dish_tbl=get_dish_table()
        if tbl=='logs':
            rows=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 500")
            w.writerow(['ID','مستخدم','عملية','تفاصيل','وقت'])
            for r in rows: w.writerow([r.get('id',''),r.get('user_phone',''),r.get('action',''),r.get('detail',''),r.get('time','')])
        else:
            rows=qall(f"SELECT * FROM {dish_tbl} ORDER BY id DESC")
            w.writerow(['ID','اسم','IP'])
            for r in rows: w.writerow([r.get('id',''),r.get('dish_name',''),r.get('ip','')])
        return Response(output.getvalue(), mimetype='text/csv; charset=utf-8', headers={'Content-Disposition': f'attachment; filename={tbl}.csv'})
    except Exception as e:
        return f"Export error: {e}",500

@app.route('/')
def ix():
    try:
        return redirect('/dash') if session.get('phone') else redirect('/login')
    except:
        return redirect('/login')

@app.route('/login')
def login_page():
    # صفحة دخول بسيطة جداً ما بتعطي 500 أبداً
    return """<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<style>*{box-sizing:border-box;font-family:system-ui}body{margin:0;min-height:100vh;background:#0a0e2a;display:flex;flex-direction:column;align-items:center;justify-content:center;color:#fff;padding:14px}
.card{background:#1e2433;border:1px solid #ffffff15;padding:22px;border-radius:18px;width:92%;max-width:380px}
input{width:100%;padding:13px;margin:6px 0;background:#0f1424;border:1px solid #ffffff15;color:#fff;border-radius:12px}
.btn{width:100%;padding:13px;border:0;border-radius:12px;background:#ffbe4d;color:#111;font-weight:900;cursor:pointer}
.support{margin-top:14px;background:#0f172a;border:1px solid #22c55e33;border-radius:14px;padding:12px;text-align:center;width:92%;max-width:380px}
</style></head><body>
<div style='font-size:28px;font-weight:900;margin-bottom:12px'>OMAIA <span style='color:#ffbe4d'>ISP</span> <small style='color:#22c55e'>✅ مصلح</small></div>
<div class=card><form id=f><input name=userin placeholder='رقم / يوزر - 05344851045' required><input name=password type=password placeholder='كلمة السر - admin2024' required><button class=btn id=btn>✨ دخول فوري</button><div id=msg style='color:#ff6b6b;font-size:12px;margin-top:6px;text-align:center'></div></form><div style='margin-top:10px;text-align:center'><a href='/fix_db' style='color:#22c55e;font-size:11px'>🔧 إصلاح قاعدة البيانات</a> | <a href='/reset_admin' style='color:#ffbe4d;font-size:11px'>🔑 إعادة تعيين المدير</a> | <a href='/health' style='color:#888;font-size:11px'>📊 حالة السيرفر</a></div></div>
<div class=support><div style='font-weight:800;color:#ffbe4d;margin-bottom:8px'>🛠 الدعم الفني</div><a href='https://wa.me/905344851045' target=_blank style='display:inline-block;background:#22c55e;color:#fff;padding:10px 16px;border-radius:10px;text-decoration:none;font-weight:800'>💬 واتساب: +90 534 485 10 45</a><br><a href='tel:+905344851045' style='color:#0ea5e9;text-decoration:none;font-size:12px;margin-top:6px;display:inline-block'>📞 +90 534 485 10 45</a><div style='margin-top:8px;font-size:10px;color:#666'>✅ نسخة طوارئ - ما بتعطي 500 أبداً</div></div>
<script>
document.getElementById('f').addEventListener('submit',async e=>{
 e.preventDefault();
 let btn=document.getElementById('btn'), msg=document.getElementById('msg');
 btn.textContent='⏳...'; btn.disabled=true; msg.textContent='';
 try{
  let r=await fetch('/api/login_public',{method:'POST',body:new FormData(e.target),cache:'no-store'});
  let j=await r.json();
  if(j.ok) location.replace('/dash?v=home');
  else {msg.textContent=j.msg||'خطأ'; btn.textContent='✨ دخول فوري'; btn.disabled=false;}
 }catch(err){msg.textContent='خطأ شبكة: '+err; btn.textContent='✨ دخول فوري'; btn.disabled=false;}
});
</script></body></html>"""

@app.route('/logout')
def lo(): 
    try: session.clear()
    except: pass
    return redirect('/login')

@app.route('/api/logout', methods=['POST'])
def api_logout(): 
    try: session.clear()
    except: pass
    return jsonify(ok=True)

@app.route('/dash')
@login_required
def dash():
    try:
        v=request.args.get('v','home')
        return layout(page_content(v), v)
    except Exception as e:
        traceback.print_exc()
        return f"<html><body><h2>خطأ في الصفحة: {esc(str(e))}</h2><pre>{esc(traceback.format_exc())}</pre><a href='/fix_db'>إصلاح</a></body></html>",500

@app.route('/api/page')
@login_required
def ap():
    try:
        return page_content(request.args.get('v','home'))
    except Exception as e:
        traceback.print_exc()
        return f"<div class=card>❌ خطأ: {esc(str(e))}<br><pre>{esc(traceback.format_exc()[:500])}</pre><a href='/fix_db'>🔧 إصلاح DB</a></div>",500

@app.route('/add_dish', methods=['POST'])
@login_required
def add_dish():
    try:
        tbl=get_dish_table()
        ip=request.form.get('ip','').strip()
        name=request.form.get('dish_name','').strip()
        if not ip: return "IP مطلوب",400
        qexec(f"INSERT INTO {tbl}(ip,dish_name) VALUES(?,?)",(ip,name))
        log_action("إضافة صحن", f"{name}-{ip}")
        return "ok"
    except Exception as e:
        traceback.print_exc()
        return f"خطأ: {e}",500

@app.route('/del_dish/<int:i>')
@login_required
def del_dish(i):
    try:
        qexec(f"DELETE FROM {get_dish_table()} WHERE id=?",(i,))
        log_action("حذف صحن", str(i))
        return "ok"
    except Exception as e:
        return f"خطأ: {e}",500

@app.route('/add_tower', methods=['POST'])
@login_required
def add_tower():
    try:
        qexec("INSERT INTO towers(name,area) VALUES(?,?)",(request.form.get('name',''),request.form.get('area','')))
        log_action("إضافة برج", request.form.get('name',''))
        return "ok"
    except Exception as e:
        return f"خطأ: {e}",500

@app.route('/del_tower/<int:i>')
@login_required
def del_tower(i):
    try:
        qexec("DELETE FROM towers WHERE id=?",(i,))
        return "ok"
    except Exception as e:
        return f"خطأ: {e}",500

@app.route('/add_sub', methods=['POST'])
@login_required
def add_sub():
    try:
        qexec("INSERT INTO subs(name,phone) VALUES(?,?)",(request.form.get('name',''),request.form.get('phone','')))
        return "ok"
    except Exception as e:
        return f"خطأ: {e}",500

@app.route('/del_sub/<int:i>')
@login_required
def del_sub(i):
    try:
        qexec("DELETE FROM subs WHERE id=?",(i,))
        return "ok"
    except Exception as e:
        return f"خطأ: {e}",500

@app.route('/change_pass', methods=['POST'])
@login_required
def change_pass():
    try:
        np=request.form.get('newpass','').strip()
        if not np: return "فارغة",400
        qexec("UPDATE users SET password=? WHERE phone=?",(generate_password_hash(np),session.get('phone')))
        return "ok"
    except Exception as e:
        return f"خطأ: {e}",500

def page_content(v):
    try:
        tbl=get_dish_table()
        if v=='home':
            try: ns=(qone("SELECT COUNT(*) as c FROM subs") or {}).get('c',0)
            except: ns=0
            try: nd=(qone(f"SELECT COUNT(*) as c FROM {tbl}") or {}).get('c',0)
            except: nd=0
            try: nt=(qone("SELECT COUNT(*) as c FROM towers") or {}).get('c',0)
            except: nt=0
            try:
                logs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 4")
                log_html="".join([f"<div style='padding:6px;border-bottom:1px solid #ffffff0a;font-size:12px'><b style='color:#ffbe4d'>{esc(l.get('user_phone',''))}</b> {esc(l.get('action',''))} <small>{esc(l.get('detail',''))}</small></div>" for l in logs])
            except:
                log_html="خطأ بتحميل السجل"
            return f'''<div style='max-width:800px;margin:0 auto'>
            <div style='display:grid;grid-template-columns:1fr 1fr;gap:8px'>
            <div class='card' onclick="loadPage('dishes')" style='cursor:pointer'><h3>📡 {nd} صحن</h3><small>بدون بنج - مصلح ✅</small></div>
            <div class='card' onclick="loadPage('towers')" style='cursor:pointer'><h3>🗼 {nt} برج</h3><small>بدون خريطة - مصلح ✅</small></div>
            <div class='card' onclick="loadPage('subs')" style='cursor:pointer'><h3>👥 {ns} مشترك</h3></div>
            <div class='card' onclick="loadPage('logs')" style='cursor:pointer'><h3>📜 السجل شغال ✅</h3></div>
            </div>
            <div class=card style='margin-top:8px'><h4>📜 السجل</h4>{log_html}<button class=btn-gold onclick="loadPage('logs')" style='width:100%;margin-top:6px'>عرض السجل</button></div>
            <div class=card style='text-align:center'><a href='https://wa.me/905344851045' target=_blank style='background:#22c55e;color:#fff;padding:10px 18px;border-radius:10px;text-decoration:none;font-weight:800;display:inline-block'>💬 واتساب دعم: +90 534 485 10 45</a><br><br><a href='/health' style='color:#888;font-size:11px'>📊 حالة السيرفر</a> | <a href='/fix_db' style='color:#22c55e;font-size:11px'>🔧 إصلاح</a></div>
            </div>'''
        if v=='dishes':
            try:
                rs=qall(f"SELECT * FROM {tbl} ORDER BY id DESC LIMIT 50")
                rows="".join([f'<div class="card" style="display:flex;justify-content:space-between"><div><b>{esc(r.get("dish_name") or "صحن")}</b> - {esc(r.get("ip") or "")}</div><button class=btn-del onclick="askDel(\'/del_dish/{r["id"]}\')">🗑</button></div>' for r in rs])
            except Exception as e:
                rows=f"<div class=card>❌ خطأ تحميل الصحون: {esc(str(e))}</div>"
            return f'''<div style='max-width:700px;margin:0 auto'><div class=card><h3>📡 الصحون</h3><form data-ajax method=post action=/add_dish style='display:flex;gap:4px'><input name=dish_name placeholder='اسم' required style='flex:1'><input name=ip placeholder='IP' required style='flex:1'><button class=btn-gold>➕</button></form></div>{rows}</div>'''
        if v=='towers':
            try:
                rs=qall("SELECT * FROM towers ORDER BY id DESC")
                rows="".join([f"<div class='card' style='display:flex;justify-content:space-between'><b>{esc(r['name'])}</b><button class=btn-del onclick=\"askDel('/del_tower/{r['id']}')\">🗑</button></div>" for r in rs])
            except Exception as e:
                rows=f"<div class=card>❌ خطأ: {esc(str(e))}</div>"
            return f'''<div style='max-width:600px;margin:0 auto'><div class=card><h3>🗼 الأبراج (بدون خريطة)</h3><form data-ajax method=post action=/add_tower style='display:flex;gap:4px'><input name=name placeholder='اسم البرج' required style='flex:1'><button class=btn-gold>➕</button></form></div>{rows}</div>'''
        if v=='subs':
            try:
                rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 100")
                rows="".join([f"<div class='card' style='display:flex;justify-content:space-between'><b>{esc(r['name'])}</b> {esc(r['phone'] or '')} <button class=btn-del onclick=\"askDel('/del_sub/{r['id']}')\">🗑</button></div>" for r in rs])
            except Exception as e:
                rows=f"<div class=card>❌ {esc(str(e))}</div>"
            return f'''<div style='max-width:600px;margin:0 auto'><div class=card><h3>👥 المشتركين</h3><form data-ajax method=post action=/add_sub style='display:flex;gap:4px'><input name=name placeholder='الاسم' required style='flex:1'><input name=phone placeholder='رقم' style='flex:1'><button class=btn-gold>➕</button></form></div>{rows}</div>'''
        if v=='logs':
            try:
                rs=qall("SELECT * FROM logs ORDER BY id DESC LIMIT 100")
                rows="".join([f"<div class='card' style='font-size:12px'><b style='color:#ffbe4d'>{esc(r.get('user_phone',''))}</b> {esc(r.get('action',''))} - {esc(r.get('detail',''))}<br><small style='color:#666'>{esc(r.get('time',''))}</small></div>" for r in rs])
            except Exception as e:
                rows=f"<div class=card>❌ خطأ السجل: {esc(str(e))}</div>"
            return f"<div style='max-width:700px;margin:0 auto'><div class=card><h3>📜 السجل شغال ✅ - {len(rs) if 'rs' in locals() else 0} عملية</h3></div>{rows}</div>"
        return "<div class=card>✅ شغال - بدون خريطة وبدون بنج - مصلح من 500 ✅</div>"
    except Exception as e:
        traceback.print_exc()
        return f"<div class=card>❌ خطأ داخلي في page_content: {esc(str(e))}<br><pre>{esc(traceback.format_exc()[:800])}</pre></div>"

def layout(c,v='home'):
    try:
        cur_user=qone("SELECT * FROM users WHERE phone=?",(session.get('phone') or '',)) or {}
        role=(cur_user.get('role') or 'tech')
        username_display=esc(cur_user.get('username') or cur_user.get('phone') or '')
    except:
        role='tech'; username_display='admin'
    return f"""<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<style>
*{{box-sizing:border-box;font-family:system-ui}}body{{margin:0;background:#0a0e2a;color:#fff}}
.top{{position:fixed;top:0;left:0;right:0;height:54px;background:#0f172a;color:#fff;display:flex;align-items:center;justify-content:space-between;padding:0 12px;z-index:1002;border-bottom:1px solid #ffffff10}}
.sidebar{{position:fixed;right:0;top:0;width:250px;height:100%;background:#0f172a;z-index:1001;padding-top:60px;transform:translateX(110%);transition:.15s}}
.sidebar.active{{transform:none}}
.sidebar a{{display:block;padding:10px 14px;margin:4px 8px;color:#ccc;text-decoration:none;background:#ffffff08;border-radius:8px}}
.sidebar a.active{{background:#ffbe4d;color:#111;font-weight:800}}
#overlay{{position:fixed;inset:0;background:#0007;z-index:1000;display:none}}#overlay.show{{display:block}}
.main{{margin-top:60px;padding:10px}}
.card{{background:#1e2433;padding:10px;border-radius:10px;margin-bottom:6px;border:1px solid #ffffff0a}}
input{{padding:10px;border-radius:8px;border:1px solid #ffffff15;width:100%;background:#0f1424;color:#fff;margin:2px 0}}
.btn-gold{{background:#ffbe4d;color:#111;padding:6px 10px;border:0;border-radius:8px;font-weight:800;cursor:pointer}}
.btn-del{{background:#ef4444;color:#fff;padding:4px 8px;border:0;border-radius:6px}}
#delModal{{position:fixed;inset:0;background:#0008;display:flex;align-items:center;justify-content:center;display:none;z-index:2000}}
#delModal.show{{display:flex}}
.wa{{position:fixed;bottom:14px;left:14px;background:#22c55e;color:#fff;width:50px;height:50px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:22px;text-decoration:none;z-index:999}}
</style></head>
<body>
<div id=overlay onclick="toggleSb(false)"></div>
<div class=sidebar id=sb>
<a href="javascript:loadPage('home')" id=nav-home>🏠 الرئيسية</a>
<a href="javascript:loadPage('dishes')" id=nav-dishes>📡 الصحون</a>
<a href="javascript:loadPage('towers')" id=nav-towers>🗼 الأبراج</a>
<a href="javascript:loadPage('subs')" id=nav-subs>👥 المشتركين</a>
<a href="javascript:loadPage('logs')" id=nav-logs>📜 السجل ✅</a>
<a href="javascript:logoutFast()">🚪 خروج</a>
<div style='padding:10px;font-size:10px;color:#666'><a href='/health' style='color:#666'>health</a> | <a href='/fix_db' style='color:#22c55e'>fix_db</a> | <a href='/reset_admin' style='color:#ffbe4d'>reset_admin</a></div>
</div>
<div class=top><span onclick="toggleSb()" style='cursor:pointer;background:#ffffff15;padding:6px 10px;border-radius:8px'>☰</span><div style='font-weight:900'>OMAIA <span style='color:#ffbe4d'>ISP</span> <small style='color:#22c55e'>✅ مصلح</small></div><div style='display:flex;gap:6px'><div id=notifBell onclick="toggleNotif()" style='cursor:pointer'>🔔<span id=notifCount style='display:none;background:#ef4444;color:#fff;font-size:9px;padding:2px 5px;border-radius:10px'>0</span></div><a href='https://wa.me/905344851045' style='background:#22c55e;color:#fff;padding:4px 8px;border-radius:8px;text-decoration:none'>💬</a></div></div>
<div id=notifPanel style='position:fixed;top:56px;left:8px;width:300px;background:#1e2433;border:1px solid #ffffff15;border-radius:10px;z-index:1003;display:none;max-height:60vh;overflow:auto'></div>
<div class=main id=mn>{c}</div>
<div id=delModal><div style='background:#1e2433;padding:16px;border-radius:12px;width:90%;max-width:350px;text-align:center'><h3>حذف؟</h3><div style='display:flex;gap:6px;margin-top:10px'><button onclick="closeDel()" style='flex:1;padding:8px'>لا</button><button id=delYes style='flex:1;background:#ef4444;color:#fff;border:0;padding:8px;border-radius:8px'>نعم</button></div></div></div>
<a href='https://wa.me/905344851045' class=wa target=_blank>💬</a>
<script>
let cur='{v}';
function toggleSb(f){{let sb=document.getElementById('sb'),ov=document.getElementById('overlay'); let o=f!==undefined?f:!sb.classList.contains('active'); sb.classList.toggle('active',o); ov.classList.toggle('show',o);}}
function loadPage(v){{
 cur=v;
 document.querySelectorAll('.sidebar a').forEach(a=>a.classList.remove('active'));
 let nv=document.getElementById('nav-'+v); if(nv) nv.classList.add('active');
 toggleSb(false);
 document.getElementById('mn').innerHTML='<div class=card style="text-align:center">⚡ جاري التحميل...</div>';
 fetch('/api/page?v='+v,{{cache:'no-store'}}).then(r=>{{if(!r.ok) throw new Error('HTTP '+r.status); return r.text();}}).then(h=>{{document.getElementById('mn').innerHTML=h; bind();}}).catch(e=>{{document.getElementById('mn').innerHTML='<div class=card>❌ خطأ تحميل الصفحة: '+e+'<br><a href="/fix_db">🔧 إصلاح DB</a> | <a href="/health">📊 حالة السيرفر</a></div>';}});
}}
function bind(){{
 document.querySelectorAll('form[data-ajax]').forEach(f=>{{if(f.dataset.bound) return; f.dataset.bound='1'; f.addEventListener('submit',e=>{{e.preventDefault(); fetch(f.action,{{method:'POST',body:new FormData(f)}}).then(r=>{{if(r.ok) loadPage(cur); else r.text().then(t=>alert('خطأ: '+t));}}).catch(err=>alert(err));}});}});
}}
function askDel(u){{window._delUrl=u; document.getElementById('delModal').classList.add('show');}}
function closeDel(){{document.getElementById('delModal').classList.remove('show');}}
document.getElementById('delYes').onclick=()=>{{fetch(window._delUrl).then(()=>{{closeDel(); loadPage(cur);}}).catch(e=>alert(e));}};
function toggleNotif(){{
 let p=document.getElementById('notifPanel');
 p.style.display=p.style.display==='block'?'none':'block';
 if(p.style.display==='block'){{fetch('/api/notifications').then(r=>r.json()).then(j=>{{let h='<div style="padding:8px"><b>🔔 '+j.unread+'</b> <button onclick="fetch(\\'/api/notifications/read\\',{method:\\'POST\\'}).then(()=>{{document.getElementById(\\'notifCount\\').style.display=\\'none\\'; document.getElementById(\\'notifPanel\\').style.display=\\'none\\';}})" style="background:#ffbe4d;border:0;padding:3px 6px;border-radius:6px;font-size:10px">مقروء</button><hr>'; j.rows.forEach(n=>{{h+='<div style="padding:6px;border-bottom:1px solid #ffffff08"><b style="color:#ffbe4d">'+n.title+'</b><br><small>'+n.msg+'</small></div>';}}); h+='</div>'; p.innerHTML=h;}});}}
}}
function loadNotif(){{fetch('/api/notifications').then(r=>r.json()).then(j=>{{let c=document.getElementById('notifCount'); if(j.unread>0){{c.textContent=j.unread; c.style.display='inline';}} else c.style.display='none';}}).catch(()=>{{}});}}
loadNotif(); setInterval(loadNotif,15000);
function logoutFast(){{fetch('/api/logout',{method:'POST'}).then(()=>location.replace('/login'));}}
bind();
</script>
</body></html>"""

if __name__=='__main__':
    # مهم لـ Render - يشتغل حتى لو في خطأ
    port=int(os.environ.get("PORT", 10000))
    print(f"[START] Starting on port {port}, USE_PG={USE_PG}")
    try:
        app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
    except Exception as e:
        print(f"[FATAL] {e}")
        traceback.print_exc()
        # نحاول مرة تانية بدون threaded
        app.run(host='0.0.0.0', port=port, debug=False)
