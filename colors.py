# colors.py - المتحكم الوحيد بكل الألوان
import base64, os

def get_colors():
    return {
        'body_bg': '#171834',
        'top_bg': '#171834',
        'menu_bg': '#1e1f3d',
        'menu_text': '#c2c4d6',
        'card_bg': '#23244d',
        'text': '#e8eaf0',
        'muted': '#8a8da3',
        'main': '#ff5a2a',      # لون الأزرار الرئيسي
        'main2': '#ff7a4a',     # تدرج الزر
        'accent': '#4a7bff',    # لون ثانوي
        'success': '#22c55e',
        'danger': '#ff4444',
        'input_bg': '#1e1f3d',
        'border': 'rgba(255,255,255,.08)',
    }

def get_bg_css():
    c = get_colors()
    return f"background:{c['body_bg']};background-color:{c['body_bg']};"

def get_logo_html(s=38):
    p = "static/logo.png" if os.path.exists("static/logo.png") else None
    if not p: return ""
    with open(p,"rb") as f:
        d = base64.b64encode(f.read()).decode()
    return f'<img src="data:image/png;base64,{d}" style="width:{s}px;height:{s}px;border-radius:10px;object-fit:cover;">'

def get_menu_css():
    c = get_colors()
    return f"""
    /* خلفية ونص */
    body{{background:{c['body_bg']}!important;color:{c['text']}!important;}}
    .top{{background:{c['top_bg']}!important;border-bottom:1px solid {c['border']}!important;}}
    .sb{{background:{c['menu_bg']}!important;}}
    .sb a{{color:{c['menu_text']}!important;}}
    .sb a:hover,.sb a.active{{background:{c['main']}22!important;color:#fff!important;border-right:3px solid {c['main']};}}

    /* كروت - الرئيسية + الاعدادات + الصحون */
    .card,.sec,.k,.hero,.kpi-card{{background:{c['card_bg']}!important;border:1px solid {c['border']}!important;color:{c['text']}!important;}}

    /* كل الأزرار */
    .btn-soft,#mb,.btnx{{background:linear-gradient(135deg,{c['main']},{c['main2']})!important;color:#fff!important;border:none!important;}}
    button[type=submit]{{background:linear-gradient(135deg,{c['main']},{c['main2']})!important;color:#fff!important;border:none!important;}}

    /* مدخلات - الاعدادات والصحون */
    input,select,textarea{{background:{c['input_bg']}!important;color:{c['text']}!important;border:1px solid {c['border']}!important;}}

    /* جداول */
    table{{background:{c['card_bg']}!important;color:{c['text']}!important;}}
    th{{color:{c['muted']}!important;}}
    td{{border-bottom:1px solid {c['border']}!important;}}

    /* نصوص وروابط */
    a{{color:{c['accent']};}}
    h2,h3{{color:#fff!important;}}
    .muted{{color:{c['muted']}!important;}}
    """
