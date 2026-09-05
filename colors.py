import json
import os

COLOR_FILE = "colors.json"

DEFAULT_COLORS = {
    "BG": "#060d1d",
    "CARD": "#0d1e3a",
    "SIDEBAR": "#081427",
    "MAIN": "#c8d2e0",
    "TEXT": "#e8f0fe",
}

def get_colors():
    if os.path.exists(COLOR_FILE):
        try:
            with open(COLOR_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
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
    try:
        from app import get_colors_cached
        if hasattr(get_colors_cached, "cache_clear"):
            get_colors_cached.cache_clear()
    except:
        pass
    return DEFAULT_COLORS.copy()
