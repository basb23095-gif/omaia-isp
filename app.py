from flask import Flask, request, redirect, session, jsonify
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, html, ipaddress, subprocess, json, socket, platform
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
            if _pg:
                try:
                    c=_pg.cursor();c.execute("SELECT 1");c.close();return _pg
                except:
                    try:_pg.close()
                    except:pass
                    _pg=None
        except: _pg=None
        try:
            _pg=psycopg2.connect(DATABASE_URL,sslmode='require',connect_timeout=10)
            _pg.autocommit=True
            return _pg
        except Exception as e:
            print(f"PG fail -> SQLite: {e}")
    try:
        c=sqlite3.connect("omia.db",check_same_thread=False)
        c.row_factory=sqlite3.Row
        return c
    except:
        c=sqlite3.connect(":memory:",check_same_thread=False)
        c.row_factory=sqlite3.Row
        return c

def cc(c):
    if not USE_PG:
        try:c.close()
        except:pass

def qall(q,a=()):
    c=db()
    try:
        if USE_PG:
            cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(q.replace("?","%s"),a)
            rs=[dict(r) for r in cur.fetchall()]
            cur.close()
            return rs
        else:
            rs=[dict(r) for r in c.execute(q,a).fetchall()]
            cc(c)
            return rs
    except:
        cc(c)
        return []

def qone(q,a=()):
    r=qall(q,a)
    return r[0] if r else None

def qexec(q,a=()):
    c=db()
    try:
        if USE_PG:
            cur=c.cursor()
            cur.execute(q.replace("?","%s"),a)
            cur.close()
        else:
            c.execute(q,a)
            c.commit()
            cc(c)
    except:
        cc(c)

def init():
    try:
        ss=[
        "CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,password TEXT,role TEXT,username TEXT)",
        "CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,note TEXT)",
        "CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,amount REAL,note TEXT,currency TEXT)",
        "CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,location TEXT,dish_name TEXT)",
        "CREATE TABLE IF NOT EXISTS towers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,area TEXT,lat REAL,lng REAL)"
        ]
        if USE_PG:
            ss=[s.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY") for s in ss]
        for s in ss:
            qexec(s)
        if not qone("SELECT * FROM users WHERE phone=?",('05344851045',)):
            qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",
                  ('05344851045',generate_password_hash('admin2024'),'manager','admin'))
        if not qone("SELECT * FROM towers WHERE name=?",('نقطة حماة الرئيسية',)):
            qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",
                  ('نقطة حماة الرئيسية','حماة',35.1318,36.7578))
    except Exception as e:
        print(f"init warn {e}")

init()

def login_required(f):
    @wraps(f)
    def w(*a,**kw):
        if not session.get('phone'):
            return redirect('/login')
        return f(*a,**kw)
    return w

def is_valid_ip(ip):
    try:
        ipaddress.ip_address(ip.strip())
        return True
    except:
        return False

def is_internal_ip(ip):
    try:
        o=ipaddress.ip_address(ip.strip())
        return o.is_private and not o.is_loopback and not o.is_multicast and not o.is_unspecified
    except:
        return False

@app.route('/api/ping')
@login_required
def api_ping():
    ip=request.args.get('ip','').strip()
    if not ip:
        return jsonify(ok=False,out='لا يوجد IP')
    if is_internal_ip(ip):
        try:
            for port in [80,8291,8728,22,443]:
                sock=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
                sock.settimeout(1.2)
                try:
                    r=sock.connect_ex((ip,port))
                    sock.close()
                    if r==0:
                        return jsonify(ok=True,out=f'✅ {ip}:{port} متصل')
                except:
                    try:sock.close()
                    except:pass
        except: pass
    try:
        cmd=['ping','-c','1','-W','2',ip] if platform.system().lower()!='windows' else ['ping','-n','1','-w','2000',ip]
        out=subprocess.check_output(cmd,timeout=4).decode(errors='ignore')
        ok='ttl=' in out.lower() or 'bytes from' in out.lower()
        return jsonify(ok=ok,out=('✅ متصل ' if ok else '❌ لا يرد ')+out[:400])
    except Exception as e:
        return jsonify(ok=False,out=f'❌ لا يرد {e}')

@app.route('/')
def ix():
    return redirect('/dash') if session.get('phone') else redirect('/login')

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        uin=request.form.get('userin','').strip()
        pw=request.form.get('password','')
        u=qone("SELECT * FROM users WHERE phone=? OR username=?",(uin,uin))
        if u and check_password_hash(u['password'],pw):
            session['phone']=u['phone']
            session['username']=u.get('username') or u['phone']
            return redirect('/dash')
        return "<script>alert('خطأ بالدخول');location.href='/login'</script>"
    return """<html dir=rtl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<style>
body{margin:0;min-height:100vh;background:linear-gradient(180deg,#0a0e2a,#1a1446);display:flex;flex-direction:column;align-items:center;justify-content:center;color:#fff;font-family:system-ui}
.card{background:#1e2433cc;border:1px solid #ffffff15;padding:25px;border-radius:20px;width:92%;max-width:340px;box-shadow:0 20px 60px #0008}
input{width:100%;padding:12px;margin:8px 0;background:#0f1424;border:1px solid #ffffff20;color:#fff;border-radius:12px;box-sizing:border-box}
.btn{width:100%;padding:13px;border:0;border-radius:12px;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:900;font-size:16px;cursor:pointer;margin-top:10px}
.save-row{display:flex;align-items:center;gap:8px;margin:8px 0;font-size:13px;color:#aaa}
.save-row input{width:auto;margin:0}
</style></head><body>
<div style='font-size:28px;font-weight:900;margin-bottom:12px'>OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<div class=card>
<form method=post id=loginForm>
<input name=userin id=userin placeholder='📱 رقم / يوزر' required autocomplete='username'>
<input name=password id=password type=password placeholder='🔑 كلمة السر' required autocomplete='current-password'>
<label class=save-row><input type=checkbox id=savePass> 💾 حفظ كلمة السر</label>
<button class=btn>✨ دخول</button>
</form>
<div style='text-align:center;margin-top:12px'><a href='https://wa.me/905344851045' style='color:#22c55e;text-decoration:none'>💬 واتساب</a> | <a href='https://instagram.com/af_20_1999' style='color:#e1306c;text-decoration:none'>📸 af_20_1999</a></div>
</div>
<script>
let u=document.getElementById('userin'), p=document.getElementById('password'), s=document.getElementById('savePass');
let su=localStorage.getItem('omaia_user'), sp=localStorage.getItem('omaia_pass');
if(su){u.value=su; if(sp){p.value=sp; s.checked=true;}}
document.getElementById('loginForm').addEventListener('submit',()=>{
 if(s.checked){localStorage.setItem('omaia_user',u.value);localStorage.setItem('omaia_pass',p.value);}
 else{localStorage.removeItem('omaia_user');localStorage.removeItem('omaia_pass');}
});
</script>
</body></html>"""

@app.route('/logout')
def lo():
    session.clear()
    return redirect('/login')

@app.route('/dash')
@login_required
def dash():
    v=request.args.get('v','home')
    return layout(page_content(v),v)

@app.route('/api/page')
@login_required
def ap():
    return page_content(request.args.get('v','home'))

@app.route('/api/search')
@login_required
def s():
    q=request.args.get('q','').strip()
    if q:
        return jsonify(qall("SELECT * FROM dish_ips WHERE ip LIKE ? OR dish_name LIKE ? OR location LIKE ? ORDER BY id DESC LIMIT 40",
                            ("%"+q+"%","%"+q+"%","%"+q+"%")))
    return jsonify(qall("SELECT * FROM dish_ips ORDER BY id DESC LIMIT 40"))

@app.route('/toggle_theme')
@login_required
def tt():
    cur=session.get('theme','dark')
    session['theme']='light' if cur=='dark' else 'dark'
    return jsonify(ok=True,theme=session['theme'])

@app.route('/add_dish',methods=['POST'])
@login_required
def ad():
    ip=request.form.get('ip','').strip()
    if not is_valid_ip(ip):
        return "IP غير صالح",400
    if qone("SELECT * FROM dish_ips WHERE ip=?",(ip,)):
        return "IP موجود مسبقاً",400
    qexec("INSERT INTO dish_ips(ip,location,dish_name) VALUES(?,?,?)",
          (ip,request.form.get('location',''),request.form.get('dish_name','')))
    return "ok"

@app.route('/edit_dish/<int:i>',methods=['POST'])
@login_required
def ed(i):
    qexec("UPDATE dish_ips SET dish_name=?,ip=?,location=? WHERE id=?",
          (request.form.get('dish_name',''),request.form.get('ip',''),request.form.get('location',''),i))
    return "ok"

@app.route('/del_dish/<int:i>')
@login_required
def dd(i):
    qexec("DELETE FROM dish_ips WHERE id=?",(i,))
    return "ok"

@app.route('/add_tower',methods=['POST'])
@login_required
def at():
    qexec("INSERT INTO towers(name,area,lat,lng) VALUES(?,?,?,?)",
          (request.form.get('name',''),request.form.get('area',''),35.1312,36.7578))
    return "ok"

@app.route('/del_tower/<int:i>')
@login_required
def dt(i):
    qexec("DELETE FROM towers WHERE id=?",(i,))
    return "ok"

@app.route('/edit_tower/<int:i>',methods=['POST'])
@login_required
def et(i):
    qexec("UPDATE towers SET name=?,area=? WHERE id=?",
          (request.form.get('name',''),request.form.get('area',''),i))
    return "ok"

@app.route('/add_sub',methods=['POST'])
@login_required
def asub():
    qexec("INSERT INTO subs(name,phone,note) VALUES(?,?,?)",
          (request.form.get('name',''),request.form.get('phone',''),request.form.get('note','')))
    return "ok"

@app.route('/del_sub/<int:i>')
@login_required
def dsub(i):
    qexec("DELETE FROM subs WHERE id=?",(i,))
    return "ok"

@app.route('/edit_sub/<int:i>',methods=['POST'])
@login_required
def esub(i):
    qexec("UPDATE subs SET name=?,phone=?,note=? WHERE id=?",
          (request.form.get('name',''),request.form.get('phone',''),request.form.get('note',''),i))
    return "ok"

@app.route('/add_ledger',methods=['POST'])
@login_required
def al():
    try: amt=float(request.form.get('amount') or 0)
    except: amt=0
    qexec("INSERT INTO ledger(name,amount,note,currency) VALUES(?,?,?,?)",
          (request.form.get('name',''),amt,request.form.get('note',''),request.form.get('currency','USD')))
    return "ok"

@app.route('/del_ledger/<int:i>')
@login_required
def dll(i):
    qexec("DELETE FROM ledger WHERE id=?",(i,))
    return "ok"

@app.route('/edit_ledger/<int:i>',methods=['POST'])
@login_required
def el(i):
    try: amt=float(request.form.get('amount') or 0)
    except: amt=0
    qexec("UPDATE ledger SET name=?,amount=?,note=?,currency=? WHERE id=?",
          (request.form.get('name',''),amt,request.form.get('note',''),request.form.get('currency','USD'),i))
    return "ok"

@app.route('/add_user',methods=['POST'])
@login_required
def au():
    ph=request.form.get('phone','').strip()
    if not ph:
        return "رقم مطلوب",400
    if qone("SELECT * FROM users WHERE phone=?",(ph,)):
        return "موجود مسبقاً",400
    qexec("INSERT INTO users(phone,password,role,username) VALUES(?,?,?,?)",
          (ph,generate_password_hash(request.form.get('password','1234')),request.form.get('role','tech'),request.form.get('username',ph)))
    return "ok"

@app.route('/edit_user',methods=['POST'])
@login_required
def eu():
    old=request.form.get('old_phone','').strip()
    new_ph=request.form.get('phone','').strip()
    if not old:
        return "خطأ",400
    qexec("UPDATE users SET phone=?,username=?,role=? WHERE phone=?",
          (new_ph,request.form.get('username',''),request.form.get('role','tech'),old))
    if session.get('phone')==old:
        session['phone']=new_ph
    return "ok"

@app.route('/del_user/<ph>')
@login_required
def du(ph):
    if ph=='05344851045':
        return "ممنوع حذف المدير",400
    qexec("DELETE FROM users WHERE phone=?",(ph,))
    return "ok"

@app.route('/change_pass',methods=['POST'])
@login_required
def cp():
    np=request.form.get('newpass','').strip()
    if not np:
        return "فارغة",400
    qexec("UPDATE users SET password=? WHERE phone=?",
          (generate_password_hash(np),session.get('phone')))
    return "ok"

def page_content(v):
    if v=='home':
        ns=(qone("SELECT COUNT(*) c FROM subs") or {}).get('c',0)
        nd=(qone("SELECT COUNT(*) c FROM dish_ips") or {}).get('c',0)
        nt=(qone("SELECT COUNT(*) c FROM towers") or {}).get('c',0)
        nl=(qone("SELECT COUNT(*) c FROM ledger") or {}).get('c',0)
        return f"""
        <div style='max-width:700px;margin:0 auto;text-align:center'>
          <div style='display:grid;grid-template-columns:1fr 1fr;gap:12px'>
            <div class='card anim' onclick="loadPage('subs')" style='cursor:pointer'><h3 data-l='subs'>المشتركين</h3><h2>{ns}</h2></div>
            <div class='card anim' onclick="loadPage('dishes')" style='cursor:pointer'><h3 data-l='dishes'>الصحون</h3><h2>{nd}</h2></div>
            <div class='card anim' onclick="loadPage('towers')" style='cursor:pointer'><h3 data-l='towers'>الأبراج</h3><h2>{nt}</h2></div>
            <div class='card anim' onclick="loadPage('ledger')" style='cursor:pointer'><h3 data-l='ledger'>الحسابات</h3><h2>{nl}</h2></div>
          </div>
        </div>"""
    if v=='dishes':
        return """<div style='max-width:900px;margin:0 auto'>
<div class=card>
<h3 data-l='dishes'>الصحون</h3>
<form data-ajax method=post action=/add_dish style='display:flex;gap:5px;flex-wrap:wrap'>
<input name=dish_name placeholder='اسم الصحن' required style='flex:1'>
<input name=ip placeholder='IP' required style='flex:1'>
<input name=location placeholder='موقع' style='flex:1'>
<button class=btn-gold>➕ إضافة</button>
</form>
<input id=searchBox placeholder='🔍 بحث IP أو اسم + Enter' oninput="window.searchDishes(this.value)" onkeydown="if(event.key==='Enter')window.searchDishes(this.value)" style='margin-top:8px'>
</div>
<div id=dl></div>
</div>
<script>
window.escH=function(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
window.doEditDish=function(id){
  let card=document.getElementById('dish-'+id);
  let n=card.dataset.name, ip=card.dataset.ip, loc=card.dataset.loc;
  let nn=prompt('اسم:',n);if(nn==null)return;
  let ii=prompt('IP:',ip);if(ii==null)return;
  let ll=prompt('موقع:',loc);if(ll==null)return;
  fetch('/edit_dish/'+id,{method:'POST',body:new URLSearchParams({dish_name:nn,ip:ii,location:ll})}).then(()=>window.ld(document.getElementById('searchBox').value||''));
}
window.doPing=function(id){
  let card=document.getElementById('dish-'+id);
  let ip=card.dataset.ip;
  let out=card.querySelector('.ping-out');
  out.textContent='⏳...';
  fetch('/api/ping?ip='+encodeURIComponent(ip)).then(r=>r.json()).then(j=>{
    out.textContent=j.out.slice(0,250);
    out.style.color=j.ok?'#22c55e':'#ef4444';
  }).catch(()=>{out.textContent='خطأ';});
}
window.ld=async function(q){
  let r=await fetch('/api/search?q='+encodeURIComponent(q||''));
  let d=await r.json();
  let h='';
  d.forEach(x=>{
    let safeName=window.escH(x.dish_name||'');
    let safeIp=window.escH(x.ip||'');
    let safeLoc=window.escH(x.location||'');
    h+=`<div class="card anim" id="dish-${x.id}" data-name="${(x.dish_name||'').replace(/"/g,'&quot;')}" data-ip="${x.ip}" data-loc="${(x.location||'').replace(/"/g,'&quot;')}" style="display:flex;justify-content:space-between;align-items:center">
      <div><b>${safeName}</b><br><span style="background:#000;color:#ffbe4d;padding:3px 8px;border-radius:10px;font-family:monospace">${safeIp}</span><br><small>${safeLoc}</small><br><small class="ping-out" style="font-size:11px"></small></div>
      <div style="display:flex;flex-direction:column;gap:5px">
        <button class=btn-gold onclick="window.doPing(${x.id})">📶 Ping</button>
        <div style="display:flex;gap:5px">
          <button class=btn-gold onclick="window.doEditDish(${x.id})">✏ تعديل</button>
          <button class=btn-del onclick="askDel('/del_dish/${x.id}')">🗑</button>
        </div>
      </div>
    </div>`;
  });
  document.getElementById('dl').innerHTML=h||'<div class=card>لا يوجد صحون</div>';
}
window.ld();
window.searchDishes=window.ld;
</script>
"""
    if v=='towers':
        rs=qall("SELECT * FROM towers ORDER BY id DESC")
        rows=""
        for r in rs:
            safe_name=esc(r['name'])
            safe_area=esc(r['area'] or '')
            # use data attributes to avoid quote issues
            rows+=f"<div class='card anim' id='tower-{r['id']}' data-name='{safe_name.replace(chr(34), '&quot;')}' data-area='{safe_area.replace(chr(34), '&quot;')}' style='display:flex;justify-content:space-between;align-items:center'><div><b>🗼 {safe_name}</b><br><small>{safe_area}</small></div><div style='display:flex;gap:5px'><button class=btn-gold onclick=\"window.doEditTower({r['id']})\">✏ تعديل</button> <button class=btn-del onclick=\"askDel('/del_tower/{r['id']}')\">🗑</button></div></div>"
        return f"""<div style='max-width:700px;margin:0 auto'>
<div class=card><h3 data-l='towers'>الأبراج</h3>
<form data-ajax method=post action=/add_tower style='display:flex;gap:6px'>
<input name=name placeholder='اسم البرج' required style='flex:1'>
<input name=area placeholder='المنطقة' style='flex:1'>
<button class=btn-gold>➕</button>
</form></div>
{rows or '<div class=card>لا يوجد أبراج</div>'}
<script>
window.doEditTower=function(id){{
  let card=document.getElementById('tower-'+id);
  let n=card.dataset.name, a=card.dataset.area;
  let nn=prompt('اسم البرج:',n);if(nn==null)return;
  let aa=prompt('المنطقة:',a);if(aa==null)return;
  fetch('/edit_tower/'+id,{{method:'POST',body:new URLSearchParams({{name:nn,area:aa}})}}).then(()=>loadPage('towers',true));
}}
</script></div>"""
    if v=='subs':
        rs=qall("SELECT * FROM subs ORDER BY id DESC LIMIT 200")
        rows=""
        for r in rs:
            rows+=f"<div class='card anim' id='sub-{r['id']}' data-name='{esc(r['name']).replace(chr(34),'&quot;')}' data-phone='{esc(r['phone'] or '').replace(chr(34),'&quot;')}' data-note='{esc(r['note'] or '').replace(chr(34),'&quot;')}' style='display:flex;justify-content:space-between;align-items:center'><div><b>{esc(r['name'])}</b><br>📞 {esc(r['phone'] or '')}<br><small>{esc(r['note'] or '')}</small></div><div style='display:flex;gap:5px'><button class=btn-gold onclick=\"window.doEditSub({r['id']})\">✏</button><button class=btn-del onclick=\"askDel('/del_sub/{r['id']}')\">🗑</button></div></div>"
        return f"""<div style='max-width:700px;margin:0 auto'>
<div class=card><h3 data-l='subs'>المشتركين</h3>
<form data-ajax method=post action=/add_sub style='display:flex;gap:5px;flex-wrap:wrap'>
<input name=name placeholder='الاسم / اليوزر' required style='flex:1'>
<input name=phone placeholder='رقم' style='flex:1'>
<input name=note placeholder='ملاحظة' style='flex:1'>
<button class=btn-gold>➕</button>
</form></div>
{rows or '<div class=card>لا يوجد</div>'}
<script>
window.doEditSub=function(id){{
  let card=document.getElementById('sub-'+id);
  let n=card.dataset.name, p=card.dataset.phone, no=card.dataset.note;
  let nn=prompt('الاسم:',n);if(nn==null)return;
  let pp=prompt('رقم:',p);if(pp==null)return;
  let nno=prompt('ملاحظة:',no)||'';
  fetch('/edit_sub/'+id,{{method:'POST',body:new URLSearchParams({{name:nn,phone:pp,note:nno}})}}).then(()=>loadPage('subs',true));
}}
</script></div>"""
    if v=='ledger':
        rs=qall("SELECT * FROM ledger ORDER BY id DESC LIMIT 200")
        rows=""
        for r in rs:
            rows+=f"<div class='card anim' id='led-{r['id']}' data-name='{esc(r['name']).replace(chr(34),'&quot;')}' data-amount='{r['amount']}' data-note='{esc(r['note'] or '').replace(chr(34),'&quot;')}' style='display:flex;justify-content:space-between;align-items:center'><div><b>{esc(r['name'])}</b> - {r['amount']} {esc(r['currency'] or 'USD')}<br><small>{esc(r['note'] or '')}</small></div><div style='display:flex;gap:5px'><button class=btn-gold onclick=\"window.doEditL({r['id']})\">✏</button><button class=btn-del onclick=\"askDel('/del_ledger/{r['id']}')\">🗑</button></div></div>"
        return f"""<div style='max-width:700px;margin:0 auto'>
<div class=card><h3 data-l='ledger'>الحسابات</h3>
<form data-ajax method=post action=/add_ledger style='display:flex;gap:5px;flex-wrap:wrap'>
<input name=name placeholder='الاسم' required style='flex:1'>
<input name=amount type=number step=0.01 placeholder='المبلغ' required style='flex:1'>
<input name=note placeholder='ملاحظة' style='flex:1'>
<select name=currency style='flex:0.5'><option value=USD>USD</option><option value=SYP>SYP</option></select>
<button class=btn-gold>➕</button>
</form></div>
{rows}
<script>
window.doEditL=function(id){{
  let card=document.getElementById('led-'+id);
  let n=card.dataset.name, a=card.dataset.amount;
  let nn=prompt('الاسم:',n);if(nn==null)return;
  let aa=prompt('المبلغ:',a);if(aa==null)return;
  fetch('/edit_ledger/'+id,{{method:'POST',body:new URLSearchParams({{name:nn,amount:aa,note:'',currency:'USD'}})}}).then(()=>loadPage('ledger',true));
}}
</script></div>"""
    if v=='map':
        towers=qall("SELECT * FROM towers")
        tj=json.dumps([{"name":t['name'],"area":t.get('area') or '',"lat":float(t.get('lat') or 35.1318),"lng":float(t.get('lng') or 36.7578)} for t in towers],ensure_ascii=False)
        return f"""<div class=card style='padding:6px'>
<div style='display:flex;gap:6px;margin-bottom:6px'><input id=mapSearch placeholder='🔍 بحث برج + Enter' onkeydown="if(event.key==='Enter')window.mapGo(this.value)" style='flex:1'><button class=btn-gold onclick="window.mapGo(document.getElementById('mapSearch').value)">اذهب</button></div>
<div id=map style='height:72vh;min-height:450px;border-radius:14px;background:#e5e7eb;z-index:1'></div>
</div>
<script>
let _towers={tj};
setTimeout(()=>{{
  if(typeof L==='undefined'){{document.getElementById('map').innerHTML='<div style=text-align:center;padding:40px>⚠ فشل تحميل الخريطة</div>';return;}}
  let map=L.map('map').setView([35.1318,36.7578],12);
  let osm=L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:19,attribution:'© OSM'}}).addTo(map);
  let sat=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',{{maxZoom:19}});
  L.control.layers({{"عادية":osm,"قمر صناعي":sat}}).addTo(map);
  setTimeout(()=>map.invalidateSize(),350);
  _towers.forEach(t=>{{L.marker([t.lat,t.lng]).addTo(map).bindPopup('<b>'+t.name+'</b><br>'+t.area);}});
  window.mapGo=function(q){{
    q=(q||'').toLowerCase().trim(); if(!q)return;
    let f=_towers.find(t=>t.name.toLowerCase().includes(q)||t.area.toLowerCase().includes(q));
    if(f){{map.flyTo([f.lat,f.lng],16);}} else alert('غير موجود');
  }};
}},120);
</script>"""
    if v=='support':
        return """<div class=card style='text-align:center;max-width:500px;margin:0 auto'>
<h2>🛠 الدعم الفني</h2>
<a href='https://wa.me/905344851045' target=_blank style='display:inline-block;background:#22c55e;color:#fff;padding:14px 24px;border-radius:12px;text-decoration:none;margin:6px;font-weight:800'>💬 واتساب</a><br>
<a href='https://instagram.com/af_20_1999' target=_blank style='display:inline-block;background:linear-gradient(45deg,#feda75,#fa7e1e,#d62976);color:#fff;padding:12px 22px;border-radius:12px;text-decoration:none;margin:6px;font-weight:800'>📸 @af_20_1999 انستا</a><br>
<a href='tel:+905344851045' style='display:inline-block;background:#0ea5e9;color:#fff;padding:12px 22px;border-radius:12px;text-decoration:none;margin:6px'>📞 +90 534 485 10 45</a>
</div>"""
    if v=='settings':
        us=qall("SELECT * FROM users ORDER BY phone DESC")
        uh=""
        for u in us:
            uh+=f"<div class='card anim' id='user-{esc(u['phone'])}' data-phone='{esc(u['phone'])}' data-username='{esc(u['username'] or '').replace(chr(34),'&quot;')}' data-role='{esc(u['role'])}' style='display:flex;justify-content:space-between;align-items:center'><div><b>{esc(u['username'] or u['phone'])}</b><br>📞 {esc(u['phone'])} | {esc(u['role'])} </div><div style='display:flex;gap:5px'><button class=btn-gold onclick=\"window.doEditU('{esc(u['phone'])}')\">✏</button><button class=btn-del onclick=\"askDel('/del_user/{esc(u['phone'])}')\">🗑</button></div></div>"
        return f"""<div style='max-width:600px;margin:0 auto'>
<div class=card><h3>🔑 حفظ كلمة السر</h3>
<form data-ajax method=post action=/change_pass style='display:flex;gap:6px'>
<input name=newpass type=password placeholder='كلمة سر جديدة' required style='flex:1'>
<button class=btn-gold>💾 حفظ كلمة السر</button>
</form></div>
<div class=card><h3>👥 المستخدمين - رقم/يوزر فقط</h3>
<form data-ajax method=post action=/add_user style='display:flex;gap:5px;flex-wrap:wrap'>
<input name=username placeholder='اليوزر' required style='flex:1'>
<input name=phone placeholder='رقم/يوزر' required style='flex:1'>
<input name=password type=password placeholder='كلمة السر' style='flex:1'>
<select name=role style='flex:0.5'><option value=tech>فني</option><option value=manager>مدير</option></select>
<button class=btn-gold>إضافة</button>
</form></div>
{uh}
<script>
window.doEditU=function(ph){{
  let card=document.getElementById('user-'+ph);
  if(!card){{card=document.querySelector('[data-phone="'+ph+'"]');}}
  let old=ph, n=card?card.dataset.username:'', rl=card?card.dataset.role:'tech';
  let nn=prompt('اليوزر:',n);if(nn==null)return;
  let pp=prompt('رقم/يوزر جديد:',old);if(pp==null)return;
  fetch('/edit_user',{{method:'POST',body:new URLSearchParams({{old_phone:old,phone:pp,username:nn,role:rl}})}}).then(()=>loadPage('settings',true));
}}
</script></div>"""
    return "<div class=card>ok</div>"

def layout(c,v='home'):
    th=session.get('theme','dark')
    is_dark=(th=='dark')
    bg='#0a0e2a' if is_dark else '#f1f5f9'
    card_bg='#1e2433' if is_dark else '#ffffff'
    txt='#ffffff' if is_dark else '#0f172a'
    border='#ffffff15' if is_dark else '#e2e8f0'
    return f"""<html dir=rtl lang=ar><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1,maximum-scale=1'>
<link rel=stylesheet href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'>
<style>
*{{box-sizing:border-box;font-family:system-ui}}body{{margin:0;background:{bg};color:{txt};overflow-x:hidden}}
.anim{{animation:fadeUp .22s ease both}}@keyframes fadeUp{{from{{opacity:0;transform:translateY(8px)}}to{{opacity:1;transform:none}}}}
.top{{position:fixed;top:0;left:0;right:0;height:60px;background:#111827ee;backdrop-filter:blur(12px);color:#fff;display:flex;align-items:center;justify-content:space-between;padding:0 12px;z-index:1003;border-bottom:1px solid #ffffff10}}
.sidebar{{position:fixed;right:0;top:0;width:270px;height:100%;background:#111827f5;color:#fff;z-index:1002;padding-top:70px;transform:translateX(110%);transition:transform .26s ease;overflow-y:auto}}
.sidebar.active{{transform:none}}
.sidebar a{{display:flex;align-items:center;gap:10px;padding:12px 16px;margin:6px 12px;color:#fff;text-decoration:none;border-radius:12px;background:#ffffff10}}
.sidebar a.active{{background:#ffbe4d;color:#111;font-weight:800}}
#overlay{{position:fixed;inset:0;background:#0008;z-index:1001;display:none}}#overlay.show{{display:block}}
.main{{margin-top:70px;padding:12px;min-height:90vh}}@media(max-width:700px){{.main{{padding:8px}}}}
.card{{background:{card_bg};color:{txt};padding:14px;border-radius:14px;margin-bottom:10px;border:1px solid {border}}}
input,select{{padding:11px;margin:5px 0;border-radius:10px;border:1px solid {border};width:100%;background:#ffffff08;color:{txt}}}
.btn-gold{{background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;padding:10px 16px;border:0;border-radius:10px;font-weight:800;cursor:pointer}}
.btn-del{{background:#ef4444;color:#fff;padding:9px 14px;border:0;border-radius:10px;cursor:pointer}}
#delModal{{position:fixed;inset:0;background:#0009;backdrop-filter:blur(4px);display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:.25s;z-index:2000}}#delModal.show{{opacity:1;pointer-events:auto}}#delBox{{background:{card_bg};color:{txt};padding:24px;border-radius:18px;width:90%;max-width:340px;text-align:center;transform:scale(.9);transition:.25s}}#delModal.show #delBox{{transform:scale(1)}}
</style></head>
<body>
<div id=overlay onclick="toggleSb(false)"></div>
<div class=sidebar id=sb>
<a href="javascript:loadPage('home')" id=nav-home>🏠 الرئيسية</a>
<a href="javascript:loadPage('dishes')" id=nav-dishes>📡 الصحون</a>
<a href="javascript:loadPage('towers')" id=nav-towers>🗼 الأبراج</a>
<a href="javascript:loadPage('subs')" id=nav-subs>👥 المشتركين</a>
<a href="javascript:loadPage('ledger')" id=nav-ledger>📒 الحسابات</a>
<a href="javascript:loadPage('map')" id=nav-map>🗺 الخريطة</a>
<a href="javascript:loadPage('support')" id=nav-support>🛠 الدعم</a>
<a href="javascript:loadPage('settings')" id=nav-settings>⚙ الإعدادات</a>
<a href=/logout>🚪 خروج</a>
</div>
<div class=top>
<div style='display:flex;gap:8px;align-items:center'>
<span onclick="toggleSb()" style='font-size:24px;cursor:pointer'>☰</span>
<input id=topsearch placeholder='🔍 بحث' oninput="if(cur=='dishes'&&window.searchDishes)window.searchDishes(this.value)" style='background:#1f2937;border:1px solid #374151;color:#fff;padding:7px 10px;border-radius:10px;width:110px'>
</div>
<div style='font-weight:900'>OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<div style='display:flex;gap:6px;align-items:center'>
<button onclick="toggleLang()" id=langBtn style='background:#1f2937;color:#fff;border:0;padding:8px 10px;border-radius:10px;cursor:pointer'>🌐 ع</button>
<button onclick="toggleTheme()" style='background:#1f2937;color:#fff;border:0;padding:8px 10px;border-radius:10px;cursor:pointer' title='ليل/نهار'>🌓</button>
<button onclick="loadPage(cur,true)" style='background:#1f2937;color:#fff;border:0;padding:8px 10px;border-radius:10px;cursor:pointer'>↻</button>
</div>
</div>
<div class=main id=mn>{c}</div>
<div id=delModal><div id=delBox><div style='font-size:44px'>🗑</div><h3>تأكيد الحذف؟</h3><p style='color:#aaa;font-size:13px'>لا يمكن التراجع</p><div style='display:flex;gap:10px;margin-top:12px'><button onclick="closeDel()" style='flex:1;padding:12px;border-radius:12px;border:1px solid {border};background:transparent;color:{txt};cursor:pointer'>تراجع</button><button id=delYes style='flex:1;padding:12px;border-radius:12px;background:#ef4444;color:#fff;border:0;cursor:pointer;font-weight:800'>حذف</button></div></div></div>
<script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>
<script>
let cur='{v}';
let pageCache=JSON.parse(localStorage.getItem('omaia_cache')||'{{}}');
let lang=localStorage.getItem('omaia_lang')||'ar';
const T={{
  ar:{{subs:'المشتركين',dishes:'الصحون',towers:'الأبراج',ledger:'الحسابات',home:'الرئيسية'}},
  en:{{subs:'Subscribers',dishes:'Dishes',towers:'Towers',ledger:'Accounts',home:'Home'}}
}};
function saveCache(){{try{{localStorage.setItem('omaia_cache',JSON.stringify(pageCache))}}catch(e){{}}}}
function applyLang(){{
  document.querySelectorAll('[data-l]').forEach(e=>{{
    let k=e.getAttribute('data-l');
    if(T[lang][k])e.textContent=T[lang][k];
  }});
  document.getElementById('langBtn').textContent=lang==='ar'?'🌐 ع':'🌐 En';
  document.documentElement.lang=lang;
  document.documentElement.dir=lang==='ar'?'rtl':'ltr';
  localStorage.setItem('omaia_lang',lang);
}}
function toggleLang(){{lang=lang==='ar'?'en':'ar';applyLang();}}
applyLang();
function toggleSb(force){{
  let sb=document.getElementById('sb'),ov=document.getElementById('overlay');
  let open=force!==undefined?force:!sb.classList.contains('active');
  sb.classList.toggle('active',open);
  ov.classList.toggle('show',open);
}}
async function loadPage(v,force=false){{
  cur=v;
  localStorage.setItem('omaia_last_page',v);
  toggleSb(false);
  document.querySelectorAll('.sidebar a').forEach(a=>a.classList.remove('active'));
  let nav=document.getElementById('nav-'+v);
  if(nav)nav.classList.add('active');
  if(pageCache[v] && !force){{
    document.getElementById('mn').innerHTML=pageCache[v];
    bind();execScripts();
    fetch('/api/page?v='+v).then(r=>r.text()).then(h=>{{pageCache[v]=h;saveCache();}});
    return;
  }}
  let mn=document.getElementById('mn');
  mn.style.opacity='0.7';
  try{{
    let r=await fetch('/api/page?v='+v,{{cache:'no-store'}});
    let h=await r.text();
    pageCache[v]=h;saveCache();
    mn.innerHTML=h;
    mn.style.opacity='1';
    bind();execScripts();
  }}catch(e){{
    mn.innerHTML='<div class=card>❌ خطأ: '+e+'</div>';
    mn.style.opacity='1';
  }}
}}
function execScripts(){{
  document.getElementById('mn').querySelectorAll('script').forEach(s=>{{try{{(0,eval)(s.textContent)}}catch(e){{console.error(e)}}}});
}}
function bind(){{
  document.querySelectorAll('form[data-ajax]').forEach(f=>{{
    f.onsubmit=async e=>{{
      e.preventDefault();
      let btn=f.querySelector('button');
      let old=btn?btn.textContent:'';
      if(btn)btn.textContent='⏳...';
      try{{
        let r=await fetch(f.action,{{method:'POST',body:new FormData(f)}});
        if(r.ok){{
          delete pageCache[cur];
          await loadPage(cur,true);
        }}else{{alert(await r.text());}}
      }}catch(err){{alert(err);}}
      if(btn)btn.textContent=old;
    }};
  }});
}}
function askDel(u){{window._delUrl=u;document.getElementById('delModal').classList.add('show');}}
function closeDel(){{document.getElementById('delModal').classList.remove('show');window._delUrl=null;}}
document.getElementById('delYes').onclick=async()=>{{
  if(window._delUrl){{
    await fetch(window._delUrl);
    delete pageCache[cur];
    closeDel();
    loadPage(cur,true);
  }}
}};
async function toggleTheme(){{
  let stay=cur;
  try{{
    await fetch('/toggle_theme');
    location.reload();
    localStorage.setItem('omaia_last_page',stay);
  }}catch(e){{location.reload();}}
}}
let lastPage=localStorage.getItem('omaia_last_page');
if(lastPage && lastPage!==cur && cur==='home'){{
  loadPage(lastPage);
}}
bind();
execScripts();
</script>
</body></html>"""

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
