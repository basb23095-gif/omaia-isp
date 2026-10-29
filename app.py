@app.route('/login')
def login():
    l = request.cookies.get('lang', 'ar'); tr = TR.get(l, TR['ar'])
    return f"""<html dir="{tr['dir']}"><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>OMAIA ISP</title>
<style>
*{{box-sizing:border-box;font-family:system-ui}}body{{margin:0;min-height:100vh;background:radial-gradient(120% 120% at 10% 10%,#1a2344,#0a0e2a 60%);display:flex;align-items:center;justify-content:center;color:#fff}}
.card{{background:rgba(20, 25, 45, 0.6);backdrop-filter:blur(20px);border:1px solid rgba(255,255,255,0.15);padding:24px;border-radius:16px;width:92%;max-width:350px;box-shadow:0 10px 30px rgba(0,0,0,0.5)}}
input{{width:100%;padding:12px;margin:8px 0;background:#0f1424;border:1px solid #ffffff22;color:#fff;border-radius:10px}}
.btn{{width:100%;padding:12px;border:0;border-radius:10px;background:linear-gradient(90deg,#ffbe4d,#ffb020);color:#111;font-weight:800;cursor:pointer;margin-top:12px}}
</style></head><body>
<div class=card>
<div style='text-align:center;font-weight:900;font-size:26px;margin-bottom:16px'>OMAIA <span style='color:#ffbe4d'>ISP</span></div>
<form id=loginForm>
<input name=userin placeholder='{tr['phone']}' required autofocus>
<input name=password type=password placeholder='***' required>
<label style="display:flex;align-items:center;gap:6px;font-size:13px;margin-top:10px;cursor:pointer">
  <input type="checkbox" name="remember" checked id="rememberBox" style="width:auto;margin:0"> حفظ الدخول
</label>
<button class=btn id=loginBtn>تسجيل الدخول</button>
<div id=msg style='text-align:center;color:#ff6b6b;font-size:12px;margin-top:10px;font-weight:bold'></div>

<!-- أضف روابط الدعم الفني هنا -->
<div style="display: flex; justify-content: center; gap: 20px; margin-top: 15px;">
  <a href="https://wa.me/963xxxxxxxxx" target="_blank" style="color: #25D366; text-decoration: none; font-size: 13px; font-weight: bold;">واتساب الدعم</a>
  <a href="https://instagram.com/your_account" target="_blank" style="color: #E1306C; text-decoration: none; font-size: 13px; font-weight: bold;">انستغرام</a>
</div>

</form>
</div>
...
