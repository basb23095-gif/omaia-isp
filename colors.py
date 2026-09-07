# colors.py - OMAIA ISP Colors
COLORS = {
    'gold': '#ffbe4d',
    'bg_dark': '#0a1938',
    'bg_light': '#f5f5f5',
    'card_dark': '#1e2a4a',
    'card_light': '#ffffff',
    'white': '#ffffff',
    'black': '#000000',
    'text_muted_dark': '#8a9bb8',
    'input_dark': '#1a2440',
    'border_dark': '#2a3a5f',
    'btn_blue': '#2196F3',
    'blue': '#2196F3',
    'btn_red': '#f44336',
    'red': '#f44336',
    'btn_wa': '#25D366',
    'menu_bg': '#0d1b3a',
    'top_bg': '#0d1b3a',
}

def logo_html():
    return f"<span style='color:{COLORS['gold']};font-weight:900;font-size:24px;letter-spacing:2px'>OMAIA</span> <span style='color:{COLORS['white']};font-weight:300;font-size:18px'>ISP</span>"
