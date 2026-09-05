@app.route('/login',methods=['GET','POST'])
def login():
    msg=""
    if request.method=='POST':
        ident=request.form.get('phone','').strip()
        pwd=request.form.get('password','')
        con=db()
        # دور على المستخدم بدون باسورد لتعرف وين الغلط
        u=ex(con,"SELECT * FROM users WHERE phone=? OR username=?",(ident,ident)).fetchone()
        close_con(con)
        is_phone = ident.replace('+','').replace(' ','').isdigit()
        if not u:
            if is_phone:
                msg="<p style='color:#f87171'>رقم الهاتف غير موجود - تحقق من رقم الهاتف</p>"
            else:
                msg="<p style='color:#f87171'>اسم المستخدم غير موجود - تحقق من اسم المستخدم</p>"
        else:
            d=dict(u) if not isinstance(u,dict) else u
            if not d.get('active'):
                msg="<p style='color:#f87171'>هاد الحساب معطل</p>"
            elif d.get('password') != pwd:
                if is_phone:
                    msg="<p style='color:#f87171'>كلمة السر غلط - تحقق من رقم الهاتف وكلمة السر</p>"
                else:
                    msg="<p style='color:#f87171'>كلمة السر غلط - تحقق من اسم المستخدم وكلمة السر</p>"
            else:
                session['phone']=d.get('phone')
                session['role']=d.get('role')
                session['username']=d.get('username')
                return redirect('/dash?view=home')
    h="<div class='login-wrap'><div class='login-box'><h2>OMAIA ISP</h2><p>دخول باسم المستخدم او الهاتف</p>"+msg+"<form method='post' id='lf'><input name='phone' id='iu' placeholder='اسم المستخدم / الهاتف' required><input name='password' id='ip' type='password' placeholder='كلمة السر' required><label><input type='checkbox' id='rm' style='width:auto'> حفظ كلمة السر</label><button>دخول</button></form></div></div><script>if(localStorage.rm=='1'){iu.value=localStorage.u||'';ip.value=localStorage.p||'';rm.checked=true}lf.onsubmit=()=>{if(rm.checked){localStorage.u=iu.value;localStorage.p=ip.value;localStorage.rm='1'}else{localStorage.clear()}}</script>"
    return render(h)
