from flask import Flask, request, jsonify
import subprocess
import platform

app = Flask(__name__)

@app.route('/ping')
def ping():
    ip = request.args.get('ip')
    # أمر البنج حسب النظام
    cmd = ["ping", "-n", "1", "-w", "1000", ip] if platform.system()=="Windows" else ["ping", "-c", "1", "-W", "1", ip]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
        ok = out.returncode == 0
        # استخراج الوقت
        ms = 0
        for line in out.stdout.splitlines():
            if "time=" in line.lower() or "زمن=" in line:
                import re
                m = re.search(r'(\d+)\s*ms', line)
                if m: ms = int(m.group(1))
        return jsonify({"ip": ip, "online": ok, "ms": ms})
    except:
        return jsonify({"ip": ip, "online": False, "ms": 0})

app.run(host='0.0.0.0', port=5000)
