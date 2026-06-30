import re, subprocess, os

files = {
    'login.html': 'D:/botai/botai/login.html',
    'signup.html': 'D:/botai/botai/signup.html',
    'admin.html': 'D:/botai/botai/admin.html',
    'index.html': 'D:/botai/botai/index.html',
}

for name, fname in files.items():
    with open(fname, 'r', encoding='utf-8') as f:
        html = f.read()
    scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
    for i, script in enumerate(scripts):
        script = script.strip()
        if not script:
            continue
        tmpfile = os.environ.get('TEMP', '.') + '\\_check_%s_%d.js' % (name.replace('.', '_'), i)
        with open(tmpfile, 'w', encoding='utf-8') as fout:
            fout.write(script)
        try:
            result = subprocess.run(['node', '--check', tmpfile], capture_output=True, text=True, timeout=15)
            if result.returncode == 0:
                print('OK: %s block %d' % (name, i))
            else:
                print('ERROR: %s block %d' % (name, i))
                print('  ' + result.stderr.replace('\n', '\n  '))
        except Exception as e:
            print('FAIL: %s block %d - %s' % (name, i, e))
        finally:
            try: os.remove(tmpfile)
            except: pass

# Check file-handler.js
jsfile = 'D:/botai/botai/static/js/file-handler.js'
result = subprocess.run(['node', '--check', jsfile], capture_output=True, text=True, timeout=15)
if result.returncode == 0:
    print('OK: file-handler.js')
else:
    print('ERROR: file-handler.js')
    print('  ' + result.stderr.replace('\n', '\n  '))
