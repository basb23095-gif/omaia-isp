DEFAULT_COLORS = {
    "bg": "#F1F5F9",
    "text": "#0F172A",
    "sidebar": "#1E3A8A",
    "card": "#FFFFFF",
    "main": "#2563EB"
}

_current = DEFAULT_COLORS.copy()

def get_colors():
    return _current

def save_colors_dict(d):
    global _current
    _current.update(d)
    return _current

def reset_colors():
    global _current
    _current = DEFAULT_COLORS.copy()
    return _current
