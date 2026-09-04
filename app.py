    elif view == 'add_sub':
        con.close()
        content = """
        <h3>إضافة مشترك جديد</h3>
        <form method="post" action="/add_sub">
            <input name="name" placeholder="اسم المشترك" required>
            <input name="phone" placeholder="رقم الهاتف" required>
            <input name="address" placeholder="العنوان">
            <input name="speed" placeholder="السرعة (مثال: 10 Mbps)">
            <select name="status"><option>نشط</option><option>موقوف</option></select>
            <button type="submit">حفظ المشترك</button>
        </form>
        """
    elif view == 'accounts':
        subs = con.execute("SELECT s.id, s.name, a.balance_usd, a.balance_syr FROM subs s LEFT JOIN accounts a ON s.id=a.sub_id").fetchall()
        con.close()
        rows=""
        for sid, name, usd, syr in subs:
            rows += f"<tr><td>{name}</td><td>${usd or 0}</td><td>{syr or 0} ل.س</td><td><a href='/dashboard?view=accounts' style='color:var(--gold)'>تفاصيل</a></td></tr>"
        content = f"<h3>دفتر الحسابات</h3><table><tr><th>المشترك</th><th>دولار</th><th>سوري</th><th>تحكم</th></tr>{rows}</table>"
    elif view == 'ips':
        ips = con.execute("SELECT ip_address, sub_id, notes FROM ips").fetchall()
        con.close()
        rows="".join([f"<tr><td>{ip[0]}</td><td>{ip[1] or '-'}</td><td>{ip[2] or ''}</td></tr>" for ip in ips])
        content = f"<h3>إدارة IPs</h3><table><tr><th>IP</th><th>مشترك</th><th>ملاحظات</th></tr>{rows}</table>"
    else:
        con.close()
        content = "<h3>مرحبا بك</h3>"

    return render_template_string(HTML_LAYOUT, is_logged=True, content=content)

@app.route('/add_sub', methods=['POST'])
def add_sub():
    if not session.get('logged_in'): return redirect('/login')
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("INSERT INTO subs (name, phone, address, speed, status) VALUES (?,?,?,?,?)",
                (request.form['name'], request.form['phone'], request.form.get('address',''), request.form.get('speed',''), request.form.get('status','نشط')))
    sid = cur.lastrowid
    cur.execute("INSERT INTO accounts (sub_id) VALUES (?)", (sid,))
    con.commit(); con.close()
    return redirect('/dashboard?view=subs')

@app.route('/toggle_status/<int:sid>')
def toggle_status(sid):
    if not session.get('logged_in'): return redirect('/login')
    con = sqlite3.connect(DB)
    cur = con.execute("SELECT status FROM subs WHERE id=?", (sid,)).fetchone()
    if cur:
        new = 'موقوف' if cur[0]=='نشط' else 'نشط'
        con.execute("UPDATE subs SET status=? WHERE id=?", (new, sid))
        con.commit()
    con.close()
    return redirect('/dashboard?view=subs')

@app.route('/del_sub/<int:sid>')
def del_sub(sid):
    if not session.get('logged_in'): return redirect('/login')
    con = sqlite3.connect(DB)
    con.execute("DELETE FROM subs WHERE id=?", (sid,))
    con.execute("DELETE FROM accounts WHERE sub_id=?", (sid,))
    con.commit(); con.close()
    return redirect('/dashboard?view=subs')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
