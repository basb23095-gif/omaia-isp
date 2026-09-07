def layout(c,v='home'):
 th=cur_theme();bg=COLORS.get('bg_dark' if th=='dark' else 'bg_light','#0a1938');card=COLORS.get('card_dark','#222');gold=COLORS.get('gold','#ffbe4d');lg=logo_html();lang=cur_lang();t=T[lang]
 tmpl="""<html dir=__DIR__><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<link rel='stylesheet' href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'>
<style>
*{box-sizing:border-box;font-family:sans-serif}
body{margin:0;background:__BG__;color:#fff}
body.light{background:#f5f5f5;color:#111}
.sidebar{position:fixed;right:-285px;top:0;width:275px;height:100%;background:rgba(17,24,39,0.82);z-index:1000;padding-top:70px;transition:right.3s;backdrop-filter:blur(18px);border-left:1px solid #ffffff18}
.sidebar.active{right:0}
.sidebar a{display:flex;gap:12px;padding:13px 18px;color:#fff;text-decoration:none;border-radius:12px;margin:4px 10px}
.sidebar a:hover{background:#ffffff1f}
.overlay{position:fixed;inset:0;background:#0006;display:none;z-index:999}.overlay.active{display:block}
.top{position:fixed;top:0;left:0;right:0;height:62px;background:rgba(17,24,39,0.85);display:flex;align-items:center;justify-content:space-between;padding:0 12px;z-index:101;backdrop-filter:blur(16px)}
.main{margin-top:62px;padding:10px}
.card{background:__CARD__;padding:14px;border-radius:18px;margin-bottom:10px;border:1px solid #ffffff12}
input,select{width:100%;padding:11px;margin:5px 0;background:#0f1424;border:1px solid #ffffff20;color:#fff;border-radius:12px}
.btn-gold{background:__GOLD__;color:#000;padding:11px 18px;border:0;border-radius:12px;font-weight:bold;cursor:pointer}
.btn-blue{background:#2196F3;color:#fff;padding:9px 14px;border:0;border-radius:10px;cursor:pointer}
.btn{background:#333;color:#fff;padding:9px 14px;border:0;border-radius:10px;cursor:pointer}
.icon-btn{width:38px;height:38px;border:0;border-radius:12px;cursor:pointer;color:#fff}
.ip-badge{background:#000;color:__GOLD__;padding:4px 10px;border-radius:20px;font-family:monospace}
#toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#1f2937ee;padding:12px 22px;border-radius:30px;display:none;z-index:9999}
.top-btn{background:#ffffff15;border:0;color:#fff;padding:8px 12px;border-radius:20px;cursor:pointer}
</style></head>
<body>
<div id=toast></div>
<div class=overlay id=ov onclick="tgM(false)"></div>
<div class=sidebar id=sb dir=rtl>
<a href="javascript:loadPage('home')">__HOME__</a>
<a href="javascript:loadPage('dishes')">__DISHES__</a>
<a href="javascript:loadPage('towers')">__TOWERS__</a>
<a href="javascript:loadPage('subs')">__SUBS__</a>
<a href="javascript:loadPage('ledger')">__LEDGER__</a>
<a href="javascript:loadPage('map')">__MAP__</a>
<a href="javascript:loadPage('ping')">__PING__</a>
<a href="javascript:loadPage('logs')">__LOGS__</a>
<a href="javascript:loadPage('support')">__SUPPORT__</a>
<a href="javascript:loadPage('settings')">__SETTINGS__</a>
<a href=/logout>__LOGOUT__</a>
</div>
<div class=top><div style='font-size:24px;cursor:pointer' onclick="tgM()">☰</div><div>__LOGO__</div><div><button class=top-btn onclick="tL()">__LANG__</button><button class=top-btn onclick="tT()">🌓</button></div></div>
<div class=main id=mn>__CONTENT__</div>
<script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>
<script>
let cur='__V__';let cache={};
function tgM(f){let sb=document.getElementById('sb');let ov=document.getElementById('ov');let o=f!==undefined?f:!sb.classList.contains('active');sb.classList.toggle('active',o);ov.classList.toggle('active',o)}
function toast(m){let t=document.getElementById('toast');t.textContent=m;t.style.display='block';clearTimeout(t._h);t._h=setTimeout(()=>t.style.display='none',2200)}
async function loadPage(v,f){cur=v;tgM(false);let mn=document.getElementById('mn');let r=await fetch('/api/page?v='+v);let h=await r.text();cache[v]=h;mn.innerHTML=h;mn.querySelectorAll('script').forEach(s=>{try{eval(s.textContent)}catch(e){}})}
window.tT=async()=>{await fetch('/toggle_theme');location.reload()};
window.tL=async()=>{await fetch('/toggle_lang');location.reload()};
if('__THEME__'=='light')document.body.classList.add('light');
</script>
</body></html>"""
 tmpl=tmpl.replace("__BG__",bg).replace("__CARD__",card).replace("__GOLD__",gold).replace("__LOGO__",lg).replace("__CONTENT__",c).replace("__V__",v).replace("__DIR__",'rtl' if lang=='ar' else 'ltr').replace("__LANG__",lang.upper()).replace("__THEME__",th).replace("__HOME__",t['home']).replace("__DISHES__",t['dishes']).replace("__TOWERS__",t['towers']).replace("__SUBS__",t['subs']).replace("__LEDGER__",t['ledger']).replace("__MAP__",t['map']).replace("__LOGS__",t['logs']).replace("__SUPPORT__",t['support']).replace("__SETTINGS__",t['settings']).replace("__LOGOUT__",t['logout']).replace("__PING__",t['ping'])
 return tmpl
