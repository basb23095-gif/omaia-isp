COLORS = {
 "top_bg": "#1e3a8a",
 "menu_bg": "#1e3a8a",
 "btn": "#16a34a",
 "bg_light": "#f1f5f9",
 "bg_dark": "#0f172a",
 "card_light": "#ffffff",
 "card_dark": "#1e293b",
 "danger": "#dc2626",
}
LOGO_TEXT = "OMAIA ISP"
LOGO_URL = ""
def logo_html():
    return f'<img src="{LOGO_URL}" style="height:32px">' if LOGO_URL else LOGO_TEXT
