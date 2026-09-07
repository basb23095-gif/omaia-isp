# colors.py - OMAIA ISP Theme by Muse
COLORS = {
    # الخلفيات
    'bg_dark': '#0a0e1f',      # كحلي غامق فخم
    'bg_light': '#f4f6fb',     # أبيض مزرق نضيف
    'card_dark': '#151b33',    # كارت ليلي
    'card_light': '#ffffff',   # كارت نهاري

    # الألوان الأساسية
    'gold': '#ffbe4d',         # ذهبي OMAIA
    'gold_dark': '#e6a635',
    'blue': '#3b82f6',
    'green': '#25D366',        # واتساب
    'pink': '#E1306C',         # انستغرام
    'red': '#F44336',
    'cyan': '#00e5ff',

    # النصوص
    'text_dark': '#ffffff',
    'text_light': '#111827',
    'muted': '#8b93a7',
}

def logo_html(size=22):
    return f"""<span style="
        font-weight:900;
        font-size:{size}px;
        letter-spacing:3px;
        background:linear-gradient(135deg, {COLORS['gold']}, #fff2cc, {COLORS['gold']});
        -webkit-background-clip:text;
        -webkit-text-fill-color:transparent;
        text-shadow:0 0 20px {COLORS['gold']}55;
        font-family:sans-serif;
    ">OMAIA ISP</span>"""
