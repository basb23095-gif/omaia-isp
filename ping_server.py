from flask import Flask, request, jsonify
import subprocess, platform, ipaddress, re

app = Flask(__name__)

def is_valid_ip(ip):
    try:
        ipaddress.ip_address(ip.strip())
        return True
    except:
        return False

@app.route('/ping')
def ping():
    ip = request.args.get('ip','').strip()
    if not is_valid_ip(ip):
        return jsonify({"ip": ip, "online": False, "ms": 0, "error": "IP غير صالح"}), 400
    is_win = platform.system().lower() == "windows"
    cmd = ["ping", "-n", "1", "-w", "1000", ip] if is_win else ["ping", "-c", "1", "-W", "1", ip]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
        ok = out.returncode == 0
        ms = 0
        text = out.stdout + out.stderr
        m = re.search(r'time[=<]\s*(\d+)', text, re.I)
        if m:
            ms = int(m.group(1))
        return jsonify({"ip": ip, "online": ok, "ms": ms})
    except:
        return jsonify({"ip": ip, "online": False, "ms": 0})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
