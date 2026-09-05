return R(f"<div class=c><form method=post><input name=sub value='{r.get('sub','')}'><div style=display:flex;gap:6px><input name=amount type=number step=0.01 value='{r.get('amount') or 0}'><button type=button onclick=\"let s=document.getElementById('cur');s.value=s.value=='USD'?'SYR':'USD';this.textContent=s.value=='USD'?'💵 $':'💶 ل.س'\" style=width:110px>{lbl}</button><input type=hidden name=currency id=cur value={cur}></div><input name=note value='{r.get('note','')}'><button>💾 حفظ</button></form></div>")
@app.route('/del_ledger/<int:i>')
def d3(i):c=db();ex(c,"DELETE FROM ledger WHERE id=?",(i,));c.commit();close(c);return redirect('/dash?view=ledger')
@app.route('/upload_ledger',methods=['POST'])
def u3():
 if not pd:return "ثبت pandas"
 f=request.files.get('file')
 if f:
  df=pd.read_excel(f);c=db()
  for _,r in df.iterrows():ex(c,"INSERT INTO ledger(date,sub,amount,currency,note)VALUES(?,?,?,?,?)",(str(r.get('date','')),str(r.get('sub','')),float(r.get('amount',0) or 0),str(r.get('currency','USD')),str(r.get('note',''))))
  c.commit();close(c)
 return redirect('/dash?view=ledger')
@app.route('/add_user',methods=['POST'])
def a4():
 c=db();i=request.form.get('ident','').strip()
 if i:
  try:ex(c,"INSERT INTO users(phone,username,password,role,active)VALUES(?,?,?,?,1)",(i,i,request.form.get('password'),'tech'));c.commit()
  except:pass
 close(c);return redirect('/dash?view=settings')
@app.route('/edit_user/<p>',methods=['GET','POST'])
def e4(p):
 c=db()
 if request.method=='POST':ni=request.form.get('ident','').strip();ex(c,"UPDATE users SET phone=?,username=?,password=? WHERE phone=?",(ni,ni,request.form.get('password'),p));c.commit();close(c);return redirect('/dash?view=settings')
 u=dict(ex(c,"SELECT * FROM users WHERE phone=?",(p,)).fetchone());close(c)
 return R(f"<div class=c><form method=post><input name=ident value='{u['username']}' required><input name=password value='{u['password']}' required><button>💾 حفظ</button></form></div>")
@app.route('/toggle_user/<p>')
def t4(p):c=db();u=dict(ex(c,"SELECT * FROM users WHERE phone=?",(p,)).fetchone());ex(c,"UPDATE users SET active=? WHERE phone=?",(0 if u['active'] else 1,p));c.commit();close(c);return redirect('/dash?view=settings')
if name=='main':app.run(host='0.0.0.0',port=int(os.environ.get('PORT',10000)))
