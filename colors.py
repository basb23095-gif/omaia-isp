import json, os

COLOR_FILE = "colors.json"

DEFAULT_COLORS = {
    "BG": "#0a1628",
    "CARD": "#1e3a5f",
    "SIDEBAR": "#0f2540",
    "MAIN": "#c0c9d6",
    "TEXT": "#e8eef5",
}

def get_colors():
    if os.path.exists(COLOR_FILE):
        try:
            with open(COLOR_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                # دمج مع الافتراضي مشان ما ينقص مفتاح
                out = DEFAULT_COLORS.copy()
                out.update(d)
                return out
        except:
            pass
    return DEFAULT_COLORS.copy()

def save_colors_dict(d):
    try:
        with open(COLOR_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        # مسح كاش الألوان بـ app.py اذا موجود
        try:
            from functools import lru_cache
            import app
            if hasattr(app.get_colors_cached, "cache_clear"):
                app.get_colors_cached.cache_clear()
        except:
            pass
        return True
    except Exception as e:
        print("save colors error:", e)
        return False

def reset_colors():
    try:
        if os.path.exists(COLOR_FILE):
            os.remove(COLOR_FILE)
    except:
        pass
    return DEFAULT_COLORS.copy()
