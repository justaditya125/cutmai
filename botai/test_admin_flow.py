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
    # 1. Login
    url = 'http://localhost:3000/api/auth/login'
    data = json.dumps({'email': 'secure_admin', 'password': 'M!7vQ2rL$9xT@4pK^8n'}).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'}, method='POST')
    resp = urllib.request.urlopen(req, timeout=10)
    print('1. Login:', resp.status)
    
    # Extract session cookie
    cookie_header = resp.headers.get('Set-Cookie', '')
    session_cookie = None
    for c in cookie_header.split(','):
        if 'session_token=' in c:
            session_cookie = c.strip().split(';')[0]
            break
    print('Session cookie:', session_cookie)
    
    # 2. Verify (like admin.html checkAdminAccess does)
    url2 = 'http://localhost:3000/api/auth/verify'
    req2 = urllib.request.Request(url2, data=b'{}', headers={
        'Content-Type': 'application/json',
        'Cookie': session_cookie
    }, method='POST')
    resp2 = urllib.request.urlopen(req2, timeout=10)
    verify_body = resp2.read().decode('utf-8')
    verify_data = json.loads(verify_body)
    print('2. Verify:', resp2.status)
    print('   User:', verify_data['user']['email'])
    print('   Is admin:', verify_data['user']['is_admin'])
    
    # 3. Test admin endpoint
    url3 = 'http://localhost:3000/api/admin/stats'
    req3 = urllib.request.Request(url3, data=b'{}', headers={
        'Content-Type': 'application/json',
        'Cookie': session_cookie
    }, method='POST')
    resp3 = urllib.request.urlopen(req3, timeout=10)
    print('3. Admin stats:', resp3.status)
    print('   Body:', resp3.read().decode('utf-8')[:200])
    
    print('\nAll tests passed!')
    
finally:
    proc.terminate()