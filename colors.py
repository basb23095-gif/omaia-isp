# colors.py - ألوان متناسقة مع خلفية الدخول (القفل السماوي)
DEFAULT_COLORS = {
    "BG": "#050B18",      # خلفية الموقع - كحلي غامق جدا مثل الصورة
    "SIDEBAR": "#0A1830", # الشريط الجانبي - كحلي
    "CARD": "#0F2748",    # البطاقات - كحلي فاتح
    "MAIN": "#00D4FF",    # اللون الرئيسي - سماوي نيون مثل القفل
    "TEXT": "#E0F7FF",    # النصوص - أبيض مزرق
}

# تخزين مؤقت
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
