def get_colors():
 return {
  'bg1':'#0a1930','bg2':'#1e3a8a','text':'#ffffff','link':'#7dd3fc',
  'main':'#3b82f6','card':'rgba(255,255,255,0.08)','top':'rgba(10,25,47,0.95)',
  'logo':'#ef4444'
 }
def get_bg_css():
 c=get_colors()
 return f"background:linear-gradient(135deg,{c['bg1']},{c['bg2']});min-height:100vh;"
def get_menu_css(): return ""
def get_logo_html():
 c=get_colors()
 return f"<span style='width:26px;height:26px;background:{c['logo']};border-radius:8px;display:inline-block;vertical-align:middle'></span>"
