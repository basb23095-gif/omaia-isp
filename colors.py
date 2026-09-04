DEFAULT_COLORS = {
    "BG": "linear-gradient(180deg, #070b1f 0%, #12163a 55%, #2b1a5e 100%)",
    "SIDEBAR": "#12162e",
    "CARD": "#1a2038",
    "MAIN": "#3b9df6",
    "TEXT": "#e2e8f0",
    "LOGIN_BG": "linear-gradient(180deg, #070b1f 0%, #12163a 55%, #2b1a5e 100%)"
}
_colors = DEFAULT_COLORS.copy()
def get_colors(): return _colors.copy()
def save_colors_dict(d):
    global _colors; _colors.update(d)
def reset_colors():
    global _colors; _colors = DEFAULT_COLORS.copy()
