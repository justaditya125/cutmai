import re, subprocess, os

files = ['D:/botai/botai/login.html', 'D:/botai/botai/signup.html', 
         'D:/botai/botai/admin.html', 'D:/botai/botai/index.html']

all_js_code = ''
for fname in files:
    with open(fname, 'r', encoding='utf-8') as f:
        html = f.read()
    scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
    for i, script in enumerate(scripts):
        script = script.strip()
        if script:
            all_js_code += '\n// === %s script block %d ===\n%s\n' % (os.path.basename(fname), i, script)

with open('D:/botai/botai/static/js/file-handler.js', 'r', encoding='utf-8') as f:
    all_js_code += '\n// === file-handler.js ===\n%s\n' % f.read()

tmpfile = os.environ.get('TEMP', '.') + '\\_check_syntax.js'
with open(tmpfile, 'w', encoding='utf-8') as f:
    f.write(all_js_code)

try:
    result = subprocess.run(['node', '--check', tmpfile], capture_output=True, text=True, timeout=15)
    if result.returncode == 0:
        print('All JS syntax OK')
    else:
        print('SYNTAX ERROR:')
        print(result.stderr[:1000])
except FileNotFoundError:
    print('Node.js not found - cannot check JS syntax')
except Exception as e:
    print('Error:', e)
finally:
    try:
        os.remove(tmpfile)
    except:
        pass
