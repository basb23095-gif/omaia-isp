DEFAULT_COLORS = {
    "bg": "#050B18",
    "text": "#E0F7FF",
    "sidebar": "#0A1830",
    "card": "#0F2340",
    "main": "#00D4FF"
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
