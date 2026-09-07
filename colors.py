# colors.py - OMAIA ISP Colors matched to login screenshot
COLORS = {
    # الأساسيات من الصورة
    'bg_dark': '#0a0e2a',      # خلفية علوية داكنة
    'bg_gradient_end': '#1a1446', # خلفية سفلية بنفسجية
    'bg_light': '#f5f7ff',

    'card_dark': '#1e2433',    # لون كرت تسجيل الدخول
    'card_light': '#ffffff',
    'card_border': '#ffffff15',

    'input_dark': '#0f1424',   # لون حقول الإدخال
    'border_dark': '#ffffff20',

    # التدرجات
    'title_grad_start': '#5aa9ff', # بداية عنوان شركة أمية
    'title_grad_end': '#c084fc',   # نهاية العنوان
    'btn_grad_start': '#3b9dff',   # زر الدخول
    'btn_grad_end': '#8b5cf6',

    'text_blue': '#5aa9ff',    # لون تسجيل الدخول
    'text_muted_dark': '#8a9bb8',
    'text_muted': '#aaa',

    # ألوان عامة للداشبورد
    'gold': '#5aa9ff',         # استبدلنا الذهبي بالأزرق ليتناسق
    'blue': '#3b9dff',
    'btn_blue': '#3b9dff',
    'purple': '#8b5cf6',
    'green': '#25D366',
    'red': '#f44336',
    'btn_red': '#f44336',

    'white': '#ffffff',
    'black': '#000000',
    'menu_bg': '#111827',
    'top_bg': '#111827',
}

def logo_html():
    # نفس تدرج العنوان اللي بالصورة
    return f"""<span style='background:linear-gradient(90deg,{COLORS['title_grad_start']},{COLORS['title_grad_end']});-webkit-background-clip:text;-webkit-text-fill-color:transparent;font-weight:800;font-size:22px'>شركة أمية للإنترنت</span>"""

def login_css():
    # اذا حبيت تستدعيه بصفحة الدخول
    return f"""
    body{{margin:0;min-height:100vh;background:linear-gradient(180deg,{COLORS['bg_dark']} 0%,{COLORS['bg_gradient_end']} 100%);display:flex;flex-direction:column;align-items:center;justify-content:center;font-family:sans-serif;color:#fff}}
    .card{{background:{COLORS['card_dark']}cc;border:1px solid {COLORS['card_border']};padding:25px;border-radius:20px;width:320px;box-shadow:0 20px 60px #0008}}
    input{{background:{COLORS['input_dark']};border:1px solid {COLORS['border_dark']};color:#fff}}
    .btn{{background:linear-gradient(90deg,{COLORS['btn_grad_start']},{COLORS['btn_grad_end']})}}
    .title{{background:linear-gradient(90deg,{COLORS['title_grad_start']},{COLORS['title_grad_end']});-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
    """
