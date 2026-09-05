# colors.py - أزرق غامق / فضي غامق / دهبي مع فضي
def get_colors():
    return {
        'main': '#0a1a3a',      # أزرق غامق رئيسي
        'accent': '#1e3a6e',    # أزرق أفتح للتدريج
        'card_bg': 'linear-gradient(145deg, #1a1f2e, #252b3d)', # فضي غامق
        'text': '#e8eaf0',
        'link': '#d4af37',      # دهبي للروابط
        # الأيقونات - دهبي مع فضي
        'icon_ip': 'linear-gradient(135deg, #d4af37, #8a8f98)',
        'icon_disabled': 'linear-gradient(135deg, #b8860b, #6b7280)',
        'icon_online': 'linear-gradient(135deg, #ffd700, #c0c0c0)',
        'icon_active': 'linear-gradient(135deg, #d4af37, #a8adb5)',
        'icon_monqatein': 'linear-gradient(135deg, #8a8f98, #4a5568)',
        'icon_modirin': 'linear-gradient(135deg, #c9a227, #8a8f98)',
        'icon_no_expire': 'linear-gradient(135deg, #a67c00, #6b7280)',
        'icon_expired': 'linear-gradient(135deg, #8b0000, #4a4a4a)',
        'icon_blocked': 'linear-gradient(135deg, #5a5a5a, #2d2d2d)',
    }

def get_bg_css():
    return "background: radial-gradient(ellipse at top, #0e2247 0%, #070f24 60%, #030711 100%); min-height:100vh;"

def get_menu_css():
    c = get_colors()
    return f"""
    .top{{background: linear-gradient(90deg, #0a1a3a, #1e3a6e); border-bottom: 1px solid #d4af3755;}}
    .sb{{background: linear-gradient(180deg, #101a30, #0a1225); border:1px solid #d4af3733;}}
    .sb a{{color:#c0c8d8;}}
    .sb a:hover{{background: linear-gradient(90deg, #d4af3733, #c0c0c022); color:#ffd700;}}
    .eye{{border:1px solid #d4af3722;}}
    """

def get_logo_html(size=32):
    import os
    logo_path = "static/logo.png"
    if os.path.exists(logo_path):
        return f"<img src='/static/logo.png' style='width:{size}px;height:{size}px;border-radius:50%;border:2px solid #d4af37;object-fit:cover'>"
    # شعار بديل دهبي وفضي اذا ما في صورة
    return f"<div style='width:{size}px;height:{size}px;border-radius:50%;background:linear-gradient(135deg,#d4af37,#c0c0c0);display:flex;align-items:center;justify-content:center;font-size:{size//2}px;border:2px solid #d4af37'>🛰️</div>"
