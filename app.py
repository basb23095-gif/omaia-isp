THEME = {
    "bg": "#0b111e",
    "card": "#1e293b",
    "sidebar": "#111827",
    "main": "#00D4FF",
    "text": "#e2e8f0",
    "bg_image": "",  # حط رابط صورة هنا اذا بدك خلفية صورة
}
def get_colors():
    return THEME
def get_bg_css():
    c = THEME
    if c.get("bg_image"):
        return f"background: linear-gradient(rgba(11,17,30,.90), rgba(11,17,30,.90)), url('{c['bg_image']}'); background-size:cover; background-attachment:fixed;"
    return f"background:{c['bg']};"
