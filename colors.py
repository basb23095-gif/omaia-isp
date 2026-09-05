import base64, os

def get_colors():
    return {
        'main': '#ff5a2a',
        'accent': '#4a7bff',
        'menu_bg': '#1e1f3d',
        'menu_text': '#c2c4d6',
        'top_bg': '#171834',
        'body_bg': '#171834',
        'card_bg': '#23244d',
        'text': '#e8eaf0',
        'link': '#4a7bff',
        'gold': '#ff5a2a',
    }

def get_bg_css():
    c = get_colors()
    return f"background:{c['body_bg']};background-color:{c['body_bg']};"

def get_logo_html():
    p = "static/logo.png" if os.path.exists("static/logo.png") else None
    if not p: return "<b style='font-size:22px'>📊</b>"
    try:
        with open(p,"rb") as f:
            d = base64.b64encode(f.read()).decode()
        return f'<img src="data:image/png;base64,{d}" style="width:38px;height:38px;border-radius:10px;object-fit:cover;">'
    except: return "<b>📊</b>"

def get_menu_css():
    c = get_colors()
    return f"""
    body{{background:{c['body_bg']}!important;color:{c['text']}!important;}}
    .sb{{background:{c['menu_bg']}!important;opacity:1!important;backdrop-filter:none!important;border:none!important;}}
    .sb a{{color:{c['menu_text']}!important;opacity:1!important;background:transparent!important;}}
    .sb a:hover,.sb a.active{{color:#fff!important;background:rgba(255,90,42,.15)!important;border-left:3px solid {c['main']};}}
    .top{{background:{c['top_bg']}!important;opacity:1!important;border-bottom:1px solid rgba(255,255,255,.06)!important;}}
    .card{{background:{c['card_bg']}!important;border:none!important;border-radius:12px!important;box-shadow:0 4px 12px rgba(0,0,0,.25)!important;}}
    #mb{{background:{c['card_bg']}!important;color:{c['text']}!important;border:1px solid rgba(255,255,255,.1)!important;}}
    .btn-soft{{background:linear-gradient(135deg,{c['main']},#ff7a4a)!important;color:#fff!important;font-weight:800;border:none;}}
    th{{color:{c['menu_text']}!important;opacity:.7;}}
    .stat h2{{color:#fff!important;}}
    input,select{{background:#1e1f3d!important;border:1px solid rgba(255,255,255,.08)!important;color:#fff!important;}}
    """
