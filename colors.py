# colors.py - نظام الألوان المركزي OMAIA ISP
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
    BLACK = "#000000"
    WHITE = "#ffffff"
    PING_BG = "#000000"
    PING_TEXT = "#00ff00"
    @staticmethod
    def get_theme(is_dark=True):
        if is_dark:
            return {"bg": Colors.DARK_BG, "card": Colors.DARK_CARD, "input": Colors.DARK_INPUT, "border": Colors.DARK_BORDER, "text": Colors.DARK_TEXT, "muted": Colors.DARK_TEXT_MUTED}
        else:
            return {"bg": Colors.LIGHT_BG, "card": Colors.LIGHT_CARD, "input": Colors.LIGHT_INPUT, "border": Colors.LIGHT_BORDER, "text": Colors.LIGHT_TEXT, "muted": Colors.LIGHT_TEXT_MUTED}

COLORS = {
    "gold": Colors.GOLD, "gold_hover": Colors.GOLD_HOVER,
    "bg_dark": Colors.DARK_BG, "bg_light": Colors.LIGHT_BG,
    "card_dark": Colors.DARK_CARD, "card_light": Colors.LIGHT_CARD,
    "top_bg": Colors.DARK_CARD, "menu_bg": Colors.DARK_BG,
    "btn": Colors.GOLD, "btn_blue": Colors.BLUE, "btn_red": Colors.RED, "btn_wa": Colors.GREEN_WA,
    "text_dark": Colors.DARK_TEXT, "text_light": Colors.LIGHT_TEXT,
    "text_muted_dark": Colors.DARK_TEXT_MUTED, "text_muted_light": Colors.LIGHT_TEXT_MUTED,
    "border_dark": Colors.DARK_BORDER, "border_light": Colors.LIGHT_BORDER,
    "input_dark": Colors.DARK_INPUT, "input_light": Colors.LIGHT_INPUT,
    "blue": Colors.BLUE, "red": Colors.RED, "green": Colors.GREEN,
    "white": Colors.WHITE, "black": Colors.BLACK,
    "ping_bg": Colors.PING_BG, "ping_text": Colors.PING_TEXT,
}
def logo_html():
    return f"<span style='color:{COLORS['gold']};font-weight:900;letter-spacing:1px'>OMAIA ISP</span>"
THEME_COLORS = Colors()
