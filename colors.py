import json, os

DEFAULT_COLORS = {
    "main": "#c9a86a", # ذهبي غامض
    "bg": "#0b0e14", # خلفية كحلي غامق
    "card": "#151b26", # بطاقات رمادي غامق
    "sidebar": "#0d1117", # قائمة جانبية
    "topbar": "#11161f", # شريط علوي
    "success": "#1db954", # إشعار نجاح
    "error": "#e5484d", # إشعار خطأ
    "info": "#4c8dff", # إشعار معلومات
    "warning": "#d4a017" # إشعار تحذير
}

FILE = "colors.json"

def get_colors():
    c = DEFAULT_COLORS.copy()
    if os.path.exists(FILE):
        try:
            with open(FILE, "r", encoding="utf-8") as f:
                c.update(json.load(f))
        except:
            pass
    return c

def save_colors_dict(d):
    c = get_colors()
    for k in DEFAULT_COLORS:
        if k in d and d[k]:
            c[k] = d[k]
    with open(FILE, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False)

def reset_colors():
    try:
        os.remove(FILE)
    except:
        pass

def notify_style(kind="info"):
    return get_colors().get(kind, "#4c8dff")
