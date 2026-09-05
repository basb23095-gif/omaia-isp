from flask import Flask,request,redirect,render_template_string,session,send_from_directory
import os,sqlite3,time
from datetime import datetime
try: import psycopg2,psycopg2.extras
except: psycopg2=None
try: import pandas as pd
except: pd=None
from colors import get_colors
app=Flask(__name__);app.secret_key=os.environ.get("SECRET_KEY","omaia-sec")
DBURL=os.environ.get("DATABASE_URL","");USE_PG=bool(DBURL and psycopg2)
WA_DISPLAY="0095344851045";WA_LINK="963544851045"
_pg=None;_pt=0
def db():
 global _pg,_pt
 if USE_PG:
  if _pg and time.time()-_pt<280:
   try:_pg.cursor().execute("SELECT 1");return _pg
   except:pass
  import psycopg2 as p;_pg=p.connect(DBURL,sslmode='require');_pg.autocommit=True;_pt=time.time();return _pg
 c=sqlite3.connect("omaia.db",check_same_thread=False);c.row_factory=sqlite3.Row;return c
def close(c):
 if not USE_PG:
  try:c.close()
  except:pass
def ex(c,q,a=()):
 if USE_PG:
  cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor);cur.execute(q.replace("?","%s"),a);return cur
 return c.execute(q,a)
def init():
 c=db()
 qs=["CREATE TABLE IF NOT EXISTS users(phone TEXT PRIMARY KEY,username TEXT,password TEXT,role TEXT,active INT)","CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,status TEXT)","CREATE TABLE IF NOT EXISTS dish_ips(id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT,name TEXT,network TEXT,tower TEXT)","CREATE TABLE IF NOT EXISTS servers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,ip TEXT,location TEXT)","CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT,date TEXT,sub TEXT,amount REAL,currency TEXT,note TEXT)"]
 if USE_PG:
  cur=c.cursor()
  for q in qs:cur.execute(q.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY"))
  cur.execute("SELECT 1 FROM users WHERE phone='05344851045'")
  if not cur.fetchone():
   cur.execute("INSERT INTO users VALUES('05344851045','05344851045','admin2024','super',1)")
  else:
   cur.execute("UPDATE users SET password='admin2024', active=1, username='05344851045' WHERE phone='05344851045'")
  c.commit();cur.close();return # تم إصلاح الخطأ هنا: c.commit أصبحت الآن تعمل بشكل صحيح لأن c تم تعريفه في البداية كـ db()
 for q in qs:c.execute(q)
 for t,col in [("dish_ips","name"),("dish_ips","network"),("dish_ips","tower"),("ledger","amount"),("ledger","currency")]:
  try:c.execute(f"SELECT {col} FROM {t} LIMIT 1")
  except:
   try:c.execute(f"ALTER TABLE {t} ADD COLUMN {col} TEXT");c.commit()
   except:pass
 if not c.execute("SELECT 1 FROM users WHERE phone='05344851045'").fetchone():
  c.execute("INSERT INTO users VALUES('05344851045','05344851045','admin2024','super',1)")
 else:
  c.execute("UPDATE users SET password='admin2024', active=1, username='05344851045' WHERE phone='05344851045'")
 c.commit()
 close(c)
init()
@app.after_request
def hdr(r):
 r.headers['Cache-Control']='public,max-age=86400' if request.path.endswith('bg.jpg') else 'no-store'
 return r
@app.route('/bg.jpg')
def bg():
 try:return send_from_directory('static','bg.jpg')
 except:return send_from_directory('.','bg.jpg')

TR={"ar":{"home":"الرئيسية","subs":"المشتركين","dishes":"الصحون","servers":"السيرفرات","ledger":"دفتر الحسابات","settings":"الإعدادات"},"en":{"home":"Home","subs":"Subscribers","dishes":"Dishes","servers":"Servers","ledger":"Ledger","settings":"Settings"}}
def T(k):
 return TR.get(session.get('lang','ar'),TR['ar']).get(k,k)

CSS="""*{box-sizing:border-box}html{scroll-behavior:smooth}body{font-family:'Segoe UI',Arial;margin:0;background:__BG__;color:__TEXT__;animation:pageIn 1s cubic-bezier(.22,1,.36,1);overflow-x:hidden}body.lb.t{display:none!important}body.lb.drawer{display:none!important}body.lb.wa{display:none!important}body.lb #loader{display:none!important}@keyframes pageIn{from{opacity:0;transform:scale(.98)}to{opacity:1;transform:scale(1)}}@keyframes slowUp{from{opacity:0;transform:translateY(40px) scale(.98)}to{opacity:1;transform:translateY(0) scale(1)}}@keyframes fadeSlow{from{opacity:0}to{opacity:1}}@keyframes logoPulse{0%,100%{transform:scale(1)}50%{transform:scale(1.12)}}.logoA{animation:logoPulse 2s infinite;display:inline-block}body.lb{background:linear-gradient(rgba(4,30,54,.55),rgba(4,30,54,.78)),url('/bg.jpg') center/cover fixed,__BG__;min-height:100vh;display:flex;align-items:center;justify-content:center}.t{background:rgba(10,20,35,.8);backdrop-filter:blur(20px);color:#fff;padding:14px 12px;display:flex;align-items:center;justify-content:space-between;position:fixed;top:0;left:0;right:0;height:56px;z-index:20;border-bottom:2px solid #00D4FF;animation:fadeSlow.8s ease}.m{padding:66px 10px;max-width:1050px;margin:auto}body.lb.m{padding:10px;display:flex;align-items:center;justify-content:center;min-height:100vh}.c{background:rgba(255,255,255,.08);backdrop-filter:blur(14px);border:1px solid rgba(0,212,255,.35);border-radius:20px;padding:18px;margin:12px 0;box-shadow:0 10px 40px rgba(0,0,0,.3);animation:slowUp.9s cubic-bezier(.22,1,.36,1);animation-fill-mode:both;transition:transform.6s cubic-bezier(.22,1,.36,1),box-shadow.6s ease}.c:nth-child(2){animation-delay:.08s}.c:nth-child(3){animation-delay:.16s}.pt{text-align:right;font-weight:bold;font-size:19px;color:#00D4FF;margin:8px 2px}.ic{display:flex;align-items:center;gap:8px}button{background:linear-gradient(135deg,#00D4FF,#0090c8);border:0;padding:12px;width:100%;border-radius:14px;font-weight:bold;cursor:pointer;color:#021;font-size:15px;transition:all.5s cubic-bezier(.22,1,.36,1);box-shadow:0 6px 20px rgba(0,212,255,.25)}button:hover{transform:translateY(-2px);box-shadow:0 12px 35px rgba(0,212,255,.35)}button:active{transform:scale(.96);transition:.15s}input,select{width:100%;padding:12px;margin:6px 0;border-radius:14px;border:1px solid #334155;background:#0f172a;color:#fff;box-sizing:border-box;transition:all.5s ease}input:focus{border-color:#00D4FF;box-shadow:0 0 0 4px rgba(0,212,255,.12);outline:none;transform:translateY(-2px)}.searchB{position:sticky;top:62px;z-index:10;background:rgba(0,212,255,.15);border:1px solid #00D4FF}table{width:100%;border-collapse:separate;border-spacing:0}td,th{padding:9px;border-bottom:1px solid #234;text-align:center;font-size:14px;transition:background.4s ease}th{color:#00D4FF}tr{animation:fadeSlow.8s ease}tr:hover td{background:rgba(0,212,255,.06)}.late{color:#ff5555!important;font-weight:bold}.g4{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.g2{display:grid;grid-template-columns:1fr 1fr;gap:10px}@media(max-width:700px){.g4{grid-template-columns:1fr 1fr}.g2{grid-template-columns:1fr}}.drawer{position:fixed;top:0;right:-320px;width:300px;height:100%;background:__SIDEBAR__;backdrop-filter:blur(25px);z-index:30;transition:right.7s cubic-bezier(.22,1,.36,1);padding:62px 12px;box-shadow:-15px 0 50px rgba(0,0,0,.6)}.drawer.open{right:0}.overlay{position:fixed;inset:0;background:rgba(0,0,0,.55);display:none;z-index:25;transition:opacity.6s ease}.overlay.show{display:block}.drawer a{display:flex;gap:10px;color:#fff;text-decoration:none;padding:13px;border-radius:12px;cursor:pointer;transition:all.5s cubic-bezier(.22,1,.36,1)}.drawer a:hover{background:#123;transform:translateX(-6px)}.drawer.open a{animation:fadeSlow.6s ease backwards}.drawer.open a:nth-child(2){animation-delay:.05s}.drawer.open a:nth-child(3){animation-delay:.1s}.drawer.open a:nth-child(4){animation-delay:.15s}.menuBtn{cursor:pointer;font-size:24px;color:#fff;background:#00D4FF;width:42px;height:42px;display:flex;align-items:center;justify-content:center;border-radius:10px;transition:.4s}.menuBtn:hover{transform:scale(1.08)}body.light{background:#eef6ff!important;color:#102a43!important}body.light.c{background:rgba(255,255,255,.9);color:#102a43}body.light input,body.light select{background:#fff;color:#102a43}.foot{text-align:center;color:#00D4FF;font-weight:bold;margin:18px}.wa{position:fixed;bottom:16px;left:16px;background:#25D366;width:52px;height:52px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:26px;z-index:22;text-decoration:none;transition:all.6s cubic-bezier(.22,1,.36,1)}.wa:hover{transform:scale(1.12) rotate(8deg)}#loader{position:fixed;top:56px;left:0;right:0;height:3px;background:linear-gradient(90deg,#00D4FF,transparent);transform:scaleX(0);transform-origin:right;transition:.25s"""
