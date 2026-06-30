import re

files_to_check = ['login.html', 'signup.html', 'admin.html', 'index.html']
for filename in files_to_check:
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()
    scripts = re.findall(r'<script[^>]*>(.*?)</script>', content, re.DOTALL)
    for sidx, script in enumerate(scripts):
        script = script.strip()
        if not script:
            continue
        depth = 0
        in_string = False
        string_char = None
        lines = script.split('\n')
        has_function = False
        for lnum, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith('//'):
                continue
            # Track function declarations
            if any(stripped.startswith(kw) for kw in ['function ', 'async function ', 'const ', 'let ', 'var ']):
                if 'function' in stripped or '=>' in stripped:
                    has_function = True
            i = 0
            while i < len(line):
                ch = line[i]
                if in_string:
                    if ch == '\\' and i + 1 < len(line):
                        i += 2
                        continue
                    if ch == string_char:
                        in_string = False
                elif ch in ('"', "'", '`'):
                    in_string = True
                    string_char = ch
                elif ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                i += 1
            if depth == 0 and (stripped.startswith('return ') or stripped == 'return;'):
                print('%s:%d: TOP-LEVEL RETURN in script block %d: %s' % (filename, lnum, sidx, stripped[:80]))
print("Done")
