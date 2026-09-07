# ping_agent.py
from flask import Flask, request, jsonify
from flask_cors import CORS
import subprocess
app=Flask(__name__);CORS(app)
@app.route('/ping')
def p():
    import subprocess
    ip=request.args.get('ip','')
    o=subprocess.run(['ping','-n','2',ip],capture_output=True,text=True,timeout=5)
    return jsonify(out=o.stdout[:500])
app.run(port=5001)
