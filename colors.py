# colors.py - نظام الألوان المركزي OMAIA ISP - النسخة المصلحة النهائية

class Colors:
    GOLD = "#D4AF37"
    GOLD_HOVER = "#B8941F"
    DARK_BG = "#0f172a"
    DARK_CARD = "#1e293b"
    DARK_INPUT = "#334155"
    DARK_BORDER = "#475569"
    DARK_TEXT = "#ffffff"
    DARK_TEXT_MUTED = "#94a3b8"
    LIGHT_BG = "#f1f5f9"
    LIGHT_CARD = "#ffffff"
    LIGHT_INPUT = "#ffffff"
    LIGHT_BORDER = "#e2e8f0"
    LIGHT_TEXT = "#0f172a"
    LIGHT_TEXT_MUTED = "#64748b"
    BLUE = "#3b82f6"
    BLUE_HOVER = "#2563eb"
    RED = "#ef4444"
    GREEN = "#22c55e"
    GREEN_WA = "#25D366"
    ORANGE = "#f59e0b"
    PING_BG = "#000000"
    PING_TEXT = "#00ff00"

    @staticmethod
    def get_theme(is_dark=True):
        if is_dark:
            return {"bg": Colors.DARK_BG, "card": Colors.DARK_CARD, "input": Colors.DARK_INPUT, "border": Colors.DARK_BORDER, "text": Colors.DARK_TEXT, "muted": Colors.DARK_TEXT_MUTED}
        else:
            return {"bg": Colors.LIGHT_BG, "card": Colors.LIGHT_CARD, "input": Colors.LIGHT_INPUT, "border": Colors.LIGHT_BORDER, "text": Colors.LIGHT_TEXT, "muted": Colors.LIGHT_TEXT_MUTED}

# هذا يلي ناقص وكان يسبب Internal Error
COLORS = {
    "gold": Colors.GOLD,
    "gold_hover": Colors.GOLD_HOVER,
    "bg_dark": Colors.DARK_BG,
    "bg_light": Colors.LIGHT_BG,
    "card_dark": Colors.DARK_CARD,
    "card_light": Colors.LIGHT_CARD,
    "top_bg": Colors.DARK_CARD,
    "menu_bg": Colors.DARK_BG,
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
}

def logo_html():
    return f"<span style='color:{COLORS['gold']};font-weight:900'>OMAIA</span> <span style='color:#fff'>ISP</span> <small style='background:{COLORS['gold']};color:#000;padding:2px 6px;border-radius:8px;font-size:10px;margin-right:6px'>PRO</small>"

THEME_COLORS = Colors()
