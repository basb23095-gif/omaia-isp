from flask import Flask, request, redirect, session, jsonify, Response
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, html, ipaddress, subprocess, json, socket, platform, io, csv
try:
    import psycopg2, psycopg2.extras
except:
    psycopg2 = None
import sqlite3

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY","omia-sec-2026-CHANGE-ME")
DATABASE_URL = os.environ.get("DATABASE_URL","").strip().replace("postgresql://","postgres://")
USE_PG = bool(DATABASE_URL.startswith("postgres://") and psycopg2)
_pg = None

def esc(s): return html.escape(str(s or ''), quote=True)
def db():
    global _pg
    if USE_PG:
        try:
            if _pg: cur=_pg.cursor();cur.execute("SELECT 1");cur.close();return _pg
        except: _pg=None
        try: _pg=psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=10);_pg.autocommit=True;return _pg
        except: pass
    c=sqlite3.connect("omia.db",check_same_thread=False);c.row_factory=sqlite3.Row;return c
def cc(c):
    if not USE_PG:
        try:c.close()
        except:pass
def qall(q,a=()):
    c=db()
    try:
        if USE_PG: cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor);cur.execute(q.replace("?","%s"),a);rs=[dict(r) for r in cur.fetchall()];cur.close();return rs
        else: rs=[dict(r) for r in c.execute(q,a).fetchall()];cc(c);return rs
    except: cc(c);return []
def qone(q,a=()): r=qall(q,a);return r[0] if r else None
def qexec(q,a=()):
    c=db()
    try:
        if USE_PG: cur=c.cursor();cur.execute(q.replace("?","%s"),a);cur.close()
        else: c.execute(q,a);c.commit();cc(c)
    except: cc(c)

def init():
    ss=["CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,username TEXT)","CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,note TEXT)","CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,amount REAL,note TEXT,currency TEXT)","CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,dish_name TEXT)","CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,area TEXT,lat REAL,lng REAL)","CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,user TEXT,action TEXT,at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"]
    if USE_PG: ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
    for s in ss: qexec(s)
    if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)): qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",('05344851045',generate_password_hash('admin2024'),'manager','admin'))
init()

def login_required(f):
    @wraps(f)
    def w(*a,**kw):
        if not session.get('phone'): return redirect('/login')
        return f(*a,**kw)
    return w
def role_required(r='manager'):
    def dec(f):
        @wraps(f)
        def w(*a,**kw):
            u=qone("SELECT * FROM users WHERE phone=?",(session.get('phone'),))
            if not u: return redirect('/login')
            if r=='manager' and u.get('role')!='manager': return "ممنوع",403
            return f(*a,**kw)
        return w
    return dec
def add_log(a):
    try: qexec("INSERT INTO logs(user,action) VALUES(?,?)",(session.get('phone','?'),a))
    except: pass
def is_valid_ip(ip):
    ip=ip.strip();
    if not ip: return False
    try: ipaddress.ip_address(ip);return True
    except: return len(ip)>=7 and '.' in ip

@app.route('/health')
def health(): return "ok",200
@app.route('/api/ping')
@login_required
def api_ping():
    ip=request.args.get('ip','').strip()
    if not is_valid_ip(ip): return jsonify(ok=False)
    try: out=subprocess.check_output(['ping','-c','1','-W','2',ip],timeout=3).decode(); return jsonify(ok='ttl=' in out.lower())
    except: return jsonify(ok=False)
@app.route('/api/net_status')
@login_required
def net_status():
    rows=qall("SELECT ip,dish_name FROM dish_ips");res=[]
    for r in rows:
        try: out=subprocess.check_output(['ping','-c','1','-W','1',r['ip']],timeout=2).decode();ok='ttl=' in out.lower()
        except: ok=False
        res.append({"ip":r['ip'],"name":r.get('dish_name',''),"ok":ok})
    return jsonify(res)
@app.route('/api/login_public',methods=['POST'])
def api_login_public():
    uin=request.form.get('userin','').strip();pw=request.form.get('password','')
    u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
    if u and check_password_hash(u['password'],pw): session['phone']=u['phone'];add_log('دخول');return jsonify(ok=True)
    return jsonify(ok=False),401
@app.route('/')
def ix(): return redirect('/dash') if session.get('phone') else redirect('/login')
@app.route('/login',methods=['GET'])
def login(): return """<html dir=rtl><head><meta charset=utf-8><style>body{background:#0a0e2a;color:#fff;display:flex;align-items:center;justify-content:center;min-height:100vh;font-family:system-ui}.card{background:#1e2433;padding:25px;border-radius:20px;width:360px}input{width:100%;padding:12px;margin:8px 0;border-radius:12px;border:1px solid #ffffff20;background:#0f1424;color:#fff}.btn{width:100%;padding:13px;background:#ffbe4d;border:0;border-radius:12px;font-weight:900}</style></head><body><div class=card><form id=f><input name=userin placeholder='يوزر' required><input name=password type=password placeholder='كلمة السر' required><button class=btn>دخول</button></form></div><script>document.getElementById('f').onsubmit=async e=>{e.preventDefault();let r=await fetch('/api/login_public',{method:'POST',body:new FormData(e.target)});if(r.ok)location.href='/dash?v=home';else alert('خطأ')}</script></body></html>"""
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
    q=request.args.get('q','').strip()
    if q: return jsonify(qall("SELECT * FROM dish_ips WHERE ip LIKE? OR dish_name LIKE? OR location LIKE? ORDER BY id DESC LIMIT 100",("%"+q+"%","%"+q+"%","%"+q+"%")))
    return jsonify(qall("SELECT * FROM dish_ips ORDER BY id DESC LIMIT 100"))
@app.route('/toggle_theme')
@login_required
def tt(): session['theme']='light' if session.get('theme','dark')=='dark' else 'dark';return jsonify(ok=True)
@app.route('/add_dish',methods=['POST'])
@login_required
def ad(): ip=request.form.get('ip','').strip();name=request.form.get('dish_name','').strip();loc=request.form.get('location','').strip();qexec("INSERT OR REPLACE INTO dish_ips(ip,location,dish_name) VALUES(?,?,?)",(ip,loc,name));return "ok"
@app.route('/del_dish/<int:i>')
@login_required
def dd(i): qexec("DELETE FROM dish_ips WHERE id=?",(i,));return "ok"

def page_content(v):
    if v == 'home':
        ns = qone("SELECT COUNT(*) c FROM subs").get('c',0)
        nd = qone("SELECT COUNT(*) c FROM dish_ips").get('c',0)
        nt = qone("SELECT COUNT(*) c FROM towers").get('c',0)
        # شلنا f"" وحطينا.format عشان الجافاسكريبت ما يخرب
        html = """<div style='max-width:700px;margin:0 auto;text-align:center'>
<div style='display:grid;grid-template-columns:1fr 1fr;gap:12px'>
<div class='card stat' onclick="loadPage('subs')"><h3>المشتركين</h3><h2 style='color:#ffbe4d;font-size:44px'>{0}</h2></div>
<div class='card stat' onclick="loadPage('dishes')"><h3>الصحون</h3><h2 style='color:#ffbe4d;font-size:44px'>{1}</h2></div>
<div class='card stat' onclick="loadPage('towers')"><h3>الأبراج</h3><h2 style='color:#ffbe4d;font-size:44px'>{2}</h2></div>
<div class='card stat' onclick="loadPage('net')"><h3>الشبكة</h3><h2 style='color:#ffbe4d'>حية</h2></div>
</div>
<div class='card'><h4>حالة الشبكة</h4><div id=netLive>جاري الفحص...</div></div>
</div><script>fetch('/api/net_status').then(r=>r.json()).then(d=>{{let h='';d.forEach(x=>{{h+='<div>'+x.name+' '+x.ip+' '+(x.ok?'ON':'OFF')+'</div>'}});document.getElementById('netLive').innerHTML=h}});</script>""".format(ns,nd,nt)
        return html
    if v == 'dishes':
        return """<div class=card><h3>الصحون</h3><form data-ajax method=post action=/add_dish><input name=dish_name placeholder='اسم' required><input name=ip placeholder='IP' required><button class=btn-gold>اضافة</button></form><input placeholder='بحث' oninput='doSearch(this.value)'></div><div id=dl></div><script>async function doSearch(q){let r=await fetch('/api/search?q='+q);let d=await r.json();let h='';d.forEach(x=>{h+='<div class=card><b>'+x.dish_name+'</b> '+x.ip+' <button onclick=\"askDel(\\'/del_dish/'+x.id+'\\')\">حذف</button></div>'});document.getElementById('dl').innerHTML=h}doSearch('');window.searchDishes=doSearch;</script>"""
    if v == 'net':
        return """<div class=card><h3>حالة الشبكة الحية</h3><button class=btn-gold onclick="loadNet()">تحديث</button><div id=nl></div></div><script>function loadNet(){fetch('/api/net_status').then(r=>r.json()).then(d=>{let h='';d.forEach(x=>{h+='<div>'+x.name+' '+(x.ok?'ON':'OFF')+'</div>'});document.getElementById('nl').innerHTML=h})};loadNet();setInterval(loadNet,30000)</script>"""
    return "<div class=card>صفحة "+esc(v)+"</div>"

def layout(c,v='home'):
    th=session.get('theme','dark');bg='#0a0e2a' if th=='dark' else '#fff';tx='#fff' if th=='dark' else '#000'
    return """<html dir=rtl><head><meta charset=utf-8><link rel=stylesheet href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'>
<style>body{margin:0;background:"""+bg+""";color:"""+tx+"""}.top{position:fixed;top:0;left:0;right:0;height:60px;background:#111827;color:#fff;display:flex;justify-content:space-between;align-items:center;padding:0 12px}.sidebar{position:fixed;right:0;top:0;width:250px;height:100%;background:#111827;padding-top:70px;transform:translateX(110%);transition:.2s}.sidebar.active{transform:none}.sidebar a{display:block;padding:12px;color:#fff;text-decoration:none}.main{margin-top:70px;padding:12px}.card{background:#1e2433;color:#fff;padding:14px;border-radius:14px;margin-bottom:10px}.btn-gold{background:#ffbe4d;border:0;padding:8px 14px;border-radius:10px}</style></head><body>
<div class=sidebar id=sb><a href="javascript:loadPage('home')">الرئيسية</a><a href="javascript:loadPage('dishes')">الصحون</a><a href="javascript:loadPage('net')">الشبكة</a><a href=/logout>خروج</a></div>
<div class=top><span onclick="document.getElementById('sb').classList.toggle('active')">☰</span><b>OMAIA ISP</b><button onclick="fetch('/toggle_theme').then(()=>location.reload())">🌓</button></div>
<div class=main id=mn>"""+c+"""</div>
<a href='https://wa.me/905344851045' style='position:fixed;bottom:20px;left:20px;background:#22c55e;color:#fff;width:50px;height:50px;border-radius:50%;display:flex;align-items:center;justify-content:center'>W</a>
<script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>
<script>async function loadPage(v){let mn=document.getElementById('mn');let r=await fetch('/api/page?v='+v);mn.innerHTML=await r.text();mn.querySelectorAll('script').forEach(s=>eval(s.textContent))}function bind(){document.querySelectorAll('form[data-ajax]').forEach(f=>{f.onsubmit=async e=>{e.preventDefault();let r=await fetch(f.action,{method:'POST',body:new FormData(f)});if(r.ok)loadPage('"""+v+"""')}})}function askDel(u){if(confirm('حذف؟'))fetch(u).then(()=>loadPage('"""+v+"""'))}bind();</script></body></html>"""

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
