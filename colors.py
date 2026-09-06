# colors.py - OMAIA ISP - ألوان مستوحاة من صورة الشبكة العالمية
class Colors:
    # مستوحى من الصورة - سماء كونية غامقة
    GOLD = "#00D4FF"  # كان ذهبي صار أزرق نيون شبكي - لون الشبكة
    GOLD_HOVER = "#00B8E6"
    GOLD_ACCENT = "#FFC400"  # الذهبي للتوهج
    
    # الثيم الغامق - كوني
    DARK_BG = "#070E22"      # خلفية الصفحة - كحلي فضائي غامق مثل الصورة
    DARK_CARD = "#101C3A"    # كروت - أزرق كوني
    DARK_INPUT = "#1A2A4F"
    DARK_BORDER = "#23365F"
    DARK_TEXT = "#E6F0FF"
    DARK_TEXT_MUTED = "#7A9CC6"
    
    # الثيم الفاتح
    LIGHT_BG = "#E8F0FE"
    LIGHT_CARD = "#FFFFFF"
    LIGHT_INPUT = "#FFFFFF"
    LIGHT_BORDER = "#C5D6F0"
    LIGHT_TEXT = "#070E22"
    LIGHT_TEXT_MUTED = "#5A7AB0"
    
    # ألوان الحالة - نيون
    BLUE = "#00D4FF"  # أزرق شبكي
    BLUE_HOVER = "#00A8CC"
    RED = "#FF3B5C"
    GREEN = "#00FFA6"
    GREEN_WA = "#25D366"
    ORANGE = "#FFB800"
    
    # شبكة وتوهج
    NETWORK_BLUE = "#1E90FF"
    GLOW_CYAN = "#00F0FF"
    GLOBE_GOLD = "#FFD60A"
    
    PING_BG = "#000000"
    PING_TEXT = "#00FFA6"

    @staticmethod
    def get_theme(is_dark=True):
        if is_dark:
            return {"bg": Colors.DARK_BG, "card": Colors.DARK_CARD, "input": Colors.DARK_INPUT, "border": Colors.DARK_BORDER, "text": Colors.DARK_TEXT, "muted": Colors.DARK_TEXT_MUTED}
        else:
            return {"bg": Colors.LIGHT_BG, "card": Colors.LIGHT_CARD, "input": Colors.LIGHT_INPUT, "border": Colors.LIGHT_BORDER, "text": Colors.LIGHT_TEXT, "muted": Colors.LIGHT_TEXT_MUTED}

COLORS = {
    "gold": Colors.GOLD,  # صار أزرق نيون
    "gold_hover": Colors.GOLD_HOVER,
    "gold_accent": Colors.GOLD_ACCENT,
    "bg_dark": Colors.DARK_BG,
    "bg_light": Colors.LIGHT_BG,
    "card_dark": Colors.DARK_CARD,
    "card_light": Colors.LIGHT_CARD,
    "top_bg": "#0A1931",
    "menu_bg": "#070E22",
    "btn": Colors.GOLD,
    "btn_blue": Colors.BLUE,
    "btn_red": Colors.RED,
    "text_dark": Colors.DARK_TEXT,
    "text_light": Colors.LIGHT_TEXT,
    "border_dark": Colors.DARK_BORDER,
    "border_light": Colors.LIGHT_BORDER,
    "input_dark": Colors.DARK_INPUT,
    "blue": Colors.BLUE,
    "red": Colors.RED,
    "green": Colors.GREEN,
    "network": Colors.NETWORK_BLUE,
    "glow": Colors.GLOW_CYAN,
}

def logo_html():
    # شعار بنفس ألوان الصورة - نيون أزرق مع توهج ذهبي
    return f"<span style='color:{COLORS['gold']};font-weight:900;letter-spacing:1px;text-shadow:0 0 10px {COLORS['gold']}66'>OMAIA</span> <span style='color:#fff;font-weight:800'>ISP</span>"

THEME_COLORS = Colors()
