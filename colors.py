import json, time, os
try: import psycopg2
except: psycopg2=None
import sqlite3

DATABASE_URL=os.environ.get("DATABASE_URL","")
USE_PG=bool(DATABASE_URL and psycopg2)

DEFAULT_COLORS={
 "main":"#d4af37",
 "bg":"#0b0f19",
 "card":"#1a2336",
 "sidebar":"#111827",
 "topbar":"#111827"
}

_cache={"v":None,"t":0}

def _db():
    if USE_PG:
        c=psycopg2.connect(DATABASE_URL, sslmode='require', connect_timeout=5)
        c.autocommit=True
        return c
    c=sqlite3.connect("omaia_company.db")
    c.row_factory=sqlite3.Row
    return c

def get_colors():
    if _cache["v"] and time.time()-_cache["t"]<300:
        return _cache["v"]
    try:
        con=_db(); cur=con.cursor()
        if USE_PG: cur.execute("SELECT v FROM settings WHERE k=%s",('colors',))
        else: cur.execute("SELECT v FROM settings WHERE k=?",('colors',))
        r=cur.fetchone(); con.close()
        if r:
            v=r[0] if isinstance(r,tuple) else r["v"]
            data=json.loads(v)
            full=DEFAULT_COLORS.copy(); full.update(data)
            _cache["v"]=full; _cache["t"]=time.time()
            return full
    except: pass
    return DEFAULT_COLORS.copy()

def save_colors_dict(d):
    full=DEFAULT_COLORS.copy()
    for k in full:
        if k in d and d[k]: full[k]=d[k]
    _cache["v"]=full; _cache["t"]=time.time()
    j=json.dumps(full)
    con=_db(); cur=con.cursor()
    if USE_PG: cur.execute("INSERT INTO settings(k,v) VALUES(%s,%s) ON CONFLICT(k) DO UPDATE SET v=EXCLUDED.v",('colors',j))
    else: cur.execute("INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)",('colors',j))
    con.commit(); con.close()
    return full

def reset_colors():
    _cache["v"]=DEFAULT_COLORS.copy(); _cache["t"]=time.time()
    try:
        con=_db(); cur=con.cursor()
        if USE_PG: cur.execute("DELETE FROM settings WHERE k=%s",('colors',))
        else: cur.execute("DELETE FROM settings WHERE k=?",('colors',))
        con.commit(); con.close()
    except: pass
    return DEFAULT_COLORS.copy()
