import base64, os

def get_colors():
    return {
        'main': '#2c3e50',
        'accent': '#7c3aed',
        'menu_bg': '#1a2f4a',
        'menu_text': '#ffffff',
        'top_bg': '#0f1420',
        'text': '#E8EAF0',
        'link': '#4da3ff',
        'card_bg': 'rgba(255,255,255,.06)'
    }

def get_bg_css():
    return "background:#0f1420;background-color:#0f1420;"

def get_logo_html():
    p = None
    if os.path.exists("static/logo.png"): p = "static/logo.png"
    elif os.path.exists("logo.png"): p = "logo.png"
    if not p:
        return "<b style='font-size:22px'>🏢</b>"
    try:
        with open(p,"rb") as f:
            d = base64.b64encode(f.read()).decode()
        return f'<img src="data:image/png;base64,{d}" style="width:38px;height:38px;border-radius:10px;object-fit:cover;display:inline-block;vertical-align:middle;">'
    except:
        return "<b>🏢</b>"

def get_menu_css():
    c = get_colors()
    return f"""
   .sb{{background:{c['menu_bg']}!important;opacity:1!important;backdrop-filter:none!important;-webkit-backdrop-filter:none!important;border:1px solid rgba(255,255,255,.12)!important;box-shadow:0 8px 24px rgba(0,0,0,.5)!important;}}
   .sb a{{color:{c['menu_text']}!important;opacity:1!important;background:rgba(255,255,255,.06)!important;}}
   .top{{background:{c['top_bg']}!important;opacity:1!important;backdrop-filter:none!important;-webkit-backdrop-filter:none!important;}}
   .eye{{backdrop-filter:none!important;-webkit-backdrop-filter:none!important;}}
    """
