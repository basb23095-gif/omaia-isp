import base64, os
def get_colors():
    return {
        'main':'#ff5a2a','accent':'#4a7bff','text':'#e8eaf0','card_bg':'#23244d','link':'#4a7bff',
        'body_bg':'#171834','top_bg':'#171834','menu_bg':'#1e1f3d','menu_text':'#c2c4d6',
        'icon_momtaz':'#ff4d6d','icon_mowazin':'#ffaa00','icon_modirin':'#8b3dff','icon_monqatein':'#00d1b2',
        'icon_no_expire':'#6c8cff','icon_expired':'#ff4d6d','icon_active':'#00d1b2','icon_blocked':'#8b3dff',
    }
def get_bg_css():
    c=get_colors(); return f"background:{c['body_bg']};background-color:{c['body_bg']};"
def get_logo_html(s=38):
    c=get_colors()
    return f'<div style="width:{s}px;height:{s}px;border-radius:10px;background:linear-gradient(135deg,{c["main"]},{c["accent"]});display:flex;align-items:center;justify-content:center;color:#fff;font-weight:900">O</div>'
def get_menu_css():
    c=get_colors()
    return f"body{{background:{c['body_bg']}!important;color:{c['text']}!important;}}.sb{{background:{c['menu_bg']}!important;}}.sb a{{color:{c['menu_text']}!important;}}.card{{background:{c['card_bg']}!important;}}"
'icon_ip':'#0099ff','icon_disabled':'#ff6b6b','icon_online':'#00d1b2',
