import base64, os

def get_colors():
    return {
        'main': '#295591',
        'accent': '#f5c86e',
        'menu_bg': '#0f2e5a',
        'menu_text': '#ffffff',
        'top_bg': '#0f2e5a',
        'body_bg': '#0f2e5a',
        'text': '#fdf6e3',
        'link': '#f5c86e',
        'card_bg': 'rgba(15,46,90,.88)',
        'card_border': 'rgba(245,200,110,.25)',
        'sun1': '#ffd700',
        'sun2': '#ff9a3c',
        'gold': '#f5c86e',
    }

def get_bg_css():
    c = get_colors()
    return (
        f"background:radial-gradient(circle at 50% -10%, {c['sun2']}33 0%, transparent 40%),"
        f"linear-gradient(135deg,#0f2e5a 0%,#1a3a6e 50%,#0f2e5a 100%);"
        f"background-color:{c['body_bg']};"
    )

def get_logo_html():
    p = "static/logo.png" if os.path.exists("static/logo.png") else "logo.png" if os.path.exists("logo.png") else None
    if not p: return "<b style='font-size:22px'>☀️</b>"
    try:
        import base64
        with open(p,"rb") as f:
            d = base64.b64encode(f.read()).decode()
        return f'<img src="data:image/png;base64,{d}" style="width:38px;height:38px;border-radius:10px;object-fit:cover;border:2px solid #f5c86e;">'
    except: return "<b>☀️</b>"

def get_menu_css():
    c = get_colors()
    return f"""
    .sb{{background:{c['menu_bg']}!important;opacity:1!important;backdrop-filter:none!important;border:1px solid {c['card_border']}!important;box-shadow:0 8px 32px rgba(0,0,0,.6)!important;}}
    .sb a{{color:{c['menu_text']}!important;opacity:1!important;background:rgba(255,255,255,.05)!important;border-right:3px solid transparent;}}
    .sb a:hover{{background:linear-gradient(90deg,{c['main']},{c['sun2']}44)!important;border-right:3px solid {c['gold']};}}
    .top{{background:{c['top_bg']}!important;opacity:1!important;border-bottom:2px solid {c['gold']}55!important;}}
    body{{color:{c['text']}!important;}}
    .card{{background:{c['card_bg']}!important;border:1px solid {c['card_border']}!important;}}
    #mb{{background:linear-gradient(135deg,{c['sun1']},{c['sun2']})!important;color:#0f2e5a!important;font-weight:900;}}
    .btn-soft{{background:linear-gradient(135deg,{c['sun1']},{c['sun2']})!important;color:#0f2e5a!important;font-weight:900;}}
    th{{color:{c['gold']}!important;}}
    .stat h2{{color:{c['gold']}!important;}}
    """
