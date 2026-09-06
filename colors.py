def get_colors():
    return {
        'bg1': '#0a1930',
        'bg2': '#1e3a8a',
        'bg3': '#1e40af',
        'text': '#ffffff',
        'text2': '#7dd3fc',
        'link': '#7dd3fc',
        'main': '#3b82f6',
        'accent': '#06b6d4',
        'card_bg': 'linear-gradient(135deg,rgba(30,58,138,.9),rgba(30,64,175,.7))',
        'card_border': 'rgba(255,255,255,.12)',
        'top_bg': 'rgba(10,25,47,.95)',
        'logo_bg': '#ef4444',
        'icon_ip': 'linear-gradient(135deg,#3b82f6,#06b6d4)',
        'icon_active': 'linear-gradient(135deg,#8b5cf6,#ec4899)',
        'btn': 'linear-gradient(135deg,#3b82f6,#06b6d4)',
        'del': '#ef4444',
        'input_bg': 'rgba(255,255,255,.08)',
    }

def get_bg_css():
    c = get_colors()
    return f"background:linear-gradient(135deg,{c['bg1']} 0%,{c['bg2']} 50%,{c['bg3']} 100%);min-height:100vh;"

def get_menu_css():
    return ".top{display:flex;align-items:center;justify-content:space-between}"

def get_logo_html():
    c = get_colors()
    return f"<span style='display:inline-block;width:28px;height:28px;background:{c['logo_bg']};border-radius:8px;vertical-align:middle'></span>"
