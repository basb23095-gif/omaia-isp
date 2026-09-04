DEFAULT_COLORS = {
    "bg": "#0f172a",
    "sidebar": "#020617",
    "card": "#1e293b",
    "main": "#38bdf8",
    "text": "#e5e7eb"
}

def get_colors():
    return DEFAULT_COLORS.copy()

def save_colors_dict(d):
    DEFAULT_COLORS.update(d)

def reset_colors():
    pass
