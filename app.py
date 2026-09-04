from flask import Flask, request, redirect, render_template_string
import sqlite3, os

app = Flask(__name__)
DB = "omaia.db"

def init_db():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS subs
    (id INTEGER PRIMARY KEY, name TEXT, phone TEXT, address TEXT, speed TEXT, price TEXT, status TEXT)""")
    con.close()
init_db()

HTML = """
<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OMAIA ISP - لوحة التحكم</title>
<style>
body{font-family:Arial;background:#f1f5f9;margin:0}
nav{background:#0f172a;color:#fff;padding:15px;text-align:center;font-size:20px}
.container{max-width:800px;margin:20px auto;background:#fff;padding:20px;border-radius:12px}
input,select{width:100%;padding:10px;margin:8px 0;border:1px solid #ccc;border-radius:8px}
button{background:#2563eb;color:#fff;padding:12px;border:none;border-radius:8px;width:100%;font-size:16px}
table{width:100%;border-collapse:collapse;margin-top:20px}
th,td{border:1px solid #ddd;padding:8px;text-align:center}
th{background:#f8fafc}
a.btn{display:inline-block;padding:6px 12px;background:#ef4444;color:#fff;border-radius:6px;text-decoration:none}
.top{display:flex;gap:10px;margin-bottom:10px}
.top a{flex:1;text-align:center;background:#e2e8f0;padding:10px;border-radius:8px;text-decoration:none;color:#000}
</style></head><body>
<nav>OMAIA ISP - لوحة التحكم</nav>
<div class="container">
<div class="top"><a href="/?pg=add">إضافة مشترك</a><a href="/?pg=list">المشتركون</a></div>
{% if pg=='add' %}
<h3>إضافة مشترك</h3>
<form method="post" action="/add">
<input name="name" placeholder="الاسم" required>
<input name="phone" placeholder="هاتف" required>
<input name="address" placeholder="عنوان">
<input name="speed" placeholder="سرعة - مثال 10Mbps">
<input name="price" placeholder="سعر">
<select name="status"><option>نشط</option><option>موقوف</option></select>
<button>حفظ</button>
</form>
{% else %}
<h3>المشتركون</h3>
<table><tr><th>الاسم</th><th>هاتف</th><th>سرعة</th><th>حالة</th><th>حذف</th></tr>
{% for s in subs %}
<tr><td>{{s[1]}}</td><td>{{s[2]}}</td><td>{{s[4]}}</td><td>{{s[6]}}</td>
<td><a class="btn" href="/del/{{s[0]}}">X</a></td></tr>
{% endfor %}</table>
{% endif %}
</div></body></html>
"""

@app.route('/')
def home():
    pg = request.args.get('pg','add')
    con = sqlite3.connect(DB)
    subs = con.execute("SELECT * FROM subs").fetchall()
    con.close()
    return render_template_string(HTML, pg=pg, subs=subs)

@app.route('/add', methods=['POST'])
def add():
    d = (request.form['name'], request.form['phone'], request.form['address'],
         request.form['speed'], request.form['price'], request.form['status'])
    con = sqlite3.connect(DB)
    con.execute("INSERT INTO subs (name,phone,address,speed,price,status) VALUES (?,?,?,?,?,?)", d)
    con.commit(); con.close()
    return redirect('/?pg=list')

@app.route('/del/<int:id>')
def delete(id):
    con = sqlite3.connect(DB)
    con.execute("DELETE FROM subs WHERE id=?", (id,))
    con.commit(); con.close()
    return redirect('/?pg=list')

if __name__ == '__main__':
    app.run()
