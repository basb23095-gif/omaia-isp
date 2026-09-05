# colors.py - ألوان مميزة مريحة للعين
import json
import os

DEFAULT_COLORS = {
    "bg": "#0B1426",      # خلفية كحلي غامق مريح
    "text": "#F1F5F9",    # نص أبيض ناصع واضح
    "sidebar": "#13233F", # قائمة جانبية كحلي أفتح
    "card": "#162C4D",    # كروت زرقاء مميزة
    "main": "#2DD4BF"     # زر أساسي تركوازي مريح وواضح
}

FILE = "colors.json"

def get_colors():
    if os.path.exists(FILE):
        try:
            with open(FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                out = DEFAULT_COLORS.copy()
                out.update(d)
                return out
        except:
            pass
    return DEFAULT_COLORS.copy()

def save_colors_dict(d):
    try:
        with open(FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
    except:
        pass

def reset_colors():
    try:
        if os.path.exists(FILE):
            os.remove(FILE)
    except:
        pass
    return DEFAULT_COLORS.copy()
