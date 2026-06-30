import json
import urllib.request
import urllib.error
import time
import os
import subprocess

os.chdir('D:\\botai\\botai')
proc = subprocess.Popen(['python', 'simple_server.py'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
time.sleep(3)

try:
    # Test login
    url = 'http://localhost:3000/api/auth/login'
    data = json.dumps({'email': 'secure_admin', 'password': 'M!7vQ2rL$9xT@4pK^8n'}).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'}, method='POST')
    resp = urllib.request.urlopen(req, timeout=10)
    print('Login response:', resp.status)
    body = resp.read().decode('utf-8')
    print('Body:', body)
    
    # Get cookies
    cookie_header = resp.headers.get('Set-Cookie', '')
    print('All cookies:', cookie_header)
    
    # Extract session cookie
    session_cookie = None
    for c in cookie_header.split(','):
        if 'session_token=' in c:
            session_cookie = c.strip().split(';')[0]
            break
    
    print('Session cookie:', session_cookie)
    
    if session_cookie:
        # Test verify with cookie
        url2 = 'http://localhost:3000/api/auth/verify'
        req2 = urllib.request.Request(url2, data=b'{}', headers={
            'Content-Type': 'application/json',
            'Cookie': session_cookie
        }, method='POST')
        try:
            resp2 = urllib.request.urlopen(req2, timeout=10)
            print('Verify response:', resp2.status)
            print('Verify body:', resp2.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            print('Verify error:', e.code)
            print('Error body:', e.read().decode('utf-8'))
finally:
    proc.terminate()