# colors.py - ألوان مستنسخة من صورة الشبكة العالمية
COLORS = {
    'bg1': '#0a1938',      # كحلي غامق خلفية
    'bg2': '#0f2a5c',      # أزرق داكن
    'bg3': '#1a3a7a',      # أزرق متوسط
    'card': 'rgba(15,42,92,0.85)',  # بطاقة زجاجية زرقاء
    'text': '#ffffff',
    'blue': '#2eb5ff',     # أزرق الكرة الأرضية
    'blue_light': '#6ed3ff',
    'gold': '#ffbe4d',     # ذهبي الأضواء
    'gold_light': '#ffdf9e',
    'gold_dark': '#e69a1f',
    'green': '#25d366',
    'pink': '#e1306c',
    'muted': '#b8c6e0'
}

def logo_html():
    return """
    <div style='text-align:center;margin-bottom:15px'>
        <div style='font-size:52px;filter:drop-shadow(0 0 15px #2eb5ff)'>🌐</div>
        <div style='font-size:22px;font-weight:bold;
        background:linear-gradient(90deg,#2eb5ff,#ffbe4d);
        -webkit-background-clip:text;-webkit-text-fill-color:transparent;
        text-shadow:0 0 30px rgba(46,181,255,0.3)'>شركة أمية للإنترنت</div>
        <div style='color:#b8c6e0;font-size:12px;margin-top:5px'>✨ نظام إدارة المشتركين</div>
    </div>
    """
