import os
import pandas as pd
from flask import Flask, request, redirect

app = Flask(__name__)

# افترضنا وجود هذه الدوال لديك سابقاً في المشروع:
# db(), ex(), close(), R()


# إحالة الصفحة الرئيسية لتجنب خطأ 404 Not Found
@app.route("/")
def home():
    return redirect("/dash?view=ledger")


def render_ledger_form(r, cur, lbl):
    sub_val = r.get("sub", "") or ""
    amount_val = r.get("amount") if r.get("amount") is not None else 0
    note_val = r.get("note", "") or ""

    return R(
        f'<div class="c">'
        f'<form method="post">'
        f'<input name="sub" value="{sub_val}">'
        f'<div style="display:flex;gap:6px">'
        f'<input name="amount" type="number" step="0.01" value="{amount_val}">'
        f"<button type="button" onclick="let s=document.getElementById('cur');s.value=s.value=='USD'?'SYR':'USD';this.textContent=s.value=='USD'?'💵 $':'💶 ل.س'" style="width:110px">{lbl}</button>"
        f'<input type="hidden" name="currency" id="cur" value="{cur}">'
        f"</div>"
        f'<input name="note" value="{note_val}">'
        f"<button>💾 حفظ</button>"
        f"</form>"
        f"</div>"
    )


@app.route("/del_ledger/<int:i>")
def d3(i):
    c = db()
    ex(c, "DELETE FROM ledger WHERE id=?", (i,))
    c.commit()
    close(c)
    return redirect("/dash?view=ledger")


@app.route("/upload_ledger", methods=["POST"])
def u3():
    if "pd" not in globals() or pd is None:
        return "ثبت pandas"

    f = request.files.get("file")
    if f:
        df = pd.read_excel(f)
        df = df.fillna("")
        c = db()
        for _, r in df.iterrows():
            amount = r.get("amount", 0)
            try:
                amount = float(amount)
            except (ValueError, TypeError):
                amount = 0.0

            ex(
                c,
                "INSERT INTO ledger(date,sub,amount,currency,note) VALUES(?,?,?,?,?)",
                (
                    str(r.get("date", "")),
                    str(r.get("sub", "")),
                    amount,
                    str(r.get("currency", "USD")),
                    str(r.get("note", "")),
                ),
            )
        c.commit()
        close(c)
    return redirect("/dash?view=ledger")


@app.route("/add_user", methods=["POST"])
def a4():
    c = db()
    i = request.form.get("ident", "").strip()
    if i:
        try:
            ex(
                c,
                "INSERT INTO users(phone,username,password,role,active) VALUES(?,?,?,?,1)",
                (i, i, request.form.get("password"), "tech"),
            )
            c.commit()
        except Exception:
            pass
    close(c)
    return redirect("/dash?view=settings")


@app.route("/edit_user/<p>", methods=["GET", "POST"])
def e4(p):
    c = db()
    if request.method == "POST":
        ni = request.form.get("ident", "").strip()
        ex(
            c,
            "UPDATE users SET phone=?,username=?,password=? WHERE phone=?",
            (ni, ni, request.form.get("password"), p),
        )
        c.commit()
        close(c)
        return redirect("/dash?view=settings")

    res = ex(c, "SELECT * FROM users WHERE phone=?", (p,)).fetchone()
    if not res:
        close(c)
        return "المستخدم غير موجود", 404

    u = dict(res)
    close(c)
    return R(
        f'<div class="c">'
        f'<form method="post">'
        f'<input name="ident" value="{u.get("username", "")}" required>'
        f'<input name="password" value="{u.get("password", "")}" required>'
        f"<button>💾 حفظ</button>"
        f"</form>"
        f"</div>"
    )


@app.route("/toggle_user/<p>")
def t4(p):
    c = db()
    res = ex(c, "SELECT active FROM users WHERE phone=?", (p,)).fetchone()
    if res:
        u = dict(res)
        new_status = 0 if u["active"] else 1
        ex(
            c,
            "UPDATE users SET active=? WHERE phone=?",
            (new_status, p),
        )
        c.commit()
    close(c)
    return redirect("/dash?view=settings")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
