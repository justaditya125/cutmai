import json
import urllib.request
import urllib.error

# Start server in background
import subprocess
import time
import os
os.chdir('D:\\botai\\botai')
proc = subprocess.Popen(['python', 'simple_server.py'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
time.sleep(3)

try:
    # Test login
    url = 'http://localhost:3000/api/auth/login'
    data = json.dumps({'email': 'secure_admin', 'password': 'M!7vQ2rL$9xT@4pK^8n'}).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'}, method='POST')
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        print('Login response:', resp.status)
        print('Body:', resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        print('Login error:', e.code)
        print('Error body:', e.read().decode('utf-8'))
        print('Headers:', dict(e.headers))
finally:
    proc.terminate()