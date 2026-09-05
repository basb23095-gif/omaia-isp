THEME = {
    "bg": "#041a2e",
    "card": "#0a2540",
    "sidebar": "#071c33",
    "main": "#00D4FF",
    "text": "#e0f4ff",
    "bg_image": "/static/login_bg.jpg",
}

def get_colors():
    return THEME

def get_bg_css():
    c = THEME
    if c.get("bg_image"):
        return f"background: linear-gradient(rgba(4,26,46,.92), rgba(4,26,46,.92)), url('{c['bg_image']}'); background-size:cover; background-attachment:fixed; background-position:center;"
    return f"background:{c['bg']};"

def get_login_css():
    c = THEME
    # خلفية الدخول بدون تعتيم قوي مشان تبين الصورة
    return f"background: linear-gradient(rgba(4,26,46,.35), rgba(4,26,46,.70)), url('{c['bg_image']}'); background-size:cover; background-position:center;"
