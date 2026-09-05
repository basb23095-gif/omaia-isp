  def icard(key, emoji, title, val):
   bg=col.get(key,'#2a2e5a')
   return f"""<div style="background:{bg};border-radius:12px;padding:14px 8px;color:#e6e9f5;text-align:center;border:1px solid #ffffff0d"><div style="font-size:11px;color:#9aa0c3;margin-bottom:8px">{title} {emoji}</div><div style="font-size:26px;font-weight:300">{val}</div></div>"""
