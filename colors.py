# colors.py - نسخة آمنة
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
        'main': '#ff5a2a',
        'main2': '#ff7a4a',
        'accent': '#4a7bff',
        'input_bg': '#1e1f3d',
        'border': 'rgba(255,255,255,.08)',
    }

def get_bg_css():
    return "background:#171834;background-color:#171834;"

def get_logo_html(s=38):
    try:
        p = "static/logo.png"
        if os.path.exists(p):
            with open(p,"rb") as f:
                d = base64.b64encode(f.read()).decode()
            return f'<img src="data:image/png;base64,{d}" style="width:{s}px;height:{s}px;border-radius:10px;object-fit:cover;">'
    except:
        pass
    return f'<div style="width:{s}px;height:{s}px;border-radius:10px;background:linear-gradient(135deg,#ff5a2a,#ff7a4a);display:flex;align-items:center;justify-content:center;color:#fff;font-weight:900">O</div>'

def get_menu_css():
    c = get_colors()
    return f"""
    body{{background:{c['body_bg']}!important;color:{c['text']}!important;}}
    .top{{background:{c['top_bg']}!important;}}
    .sb{{background:{c['menu_bg']}!important;}}
    .sb a{{color:{c['menu_text']}!important;}}
    .card{{background:{c['card_bg']}!important;}}
    """
