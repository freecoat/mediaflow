import re, pathlib
root = pathlib.Path('app/templates')
globaljs = pathlib.Path('app/static/js/global.js').read_text(encoding='utf-8', errors='ignore')
other_js = ''
for p in ['app/static/js/copilot.js','app/static/js/i18n.js','app/static/js/action_log.js','app/static/js/mobile.js']:
    other_js += pathlib.Path(p).read_text(encoding='utf-8', errors='ignore')
base = (root/'base.html').read_text(encoding='utf-8', errors='ignore')
comps = ''
for p in (root/'components').glob('*.html'):
    comps += p.read_text(encoding='utf-8', errors='ignore')

call_re = re.compile(r'on(?:click|change|input|submit|keydown|keyup|blur)\s*=\s*"([A-Za-z_$][\w$]*)\s*\(')
def defined(name, txt):
    return re.search(r'(?:function\s+'+re.escape(name)+r'\b|(?:window\.)?'+re.escape(name)+r'\s*=\s*(?:async\s*)?(?:function|\())', txt)

problems=[]
for f in list(root.rglob('*.html')):
    txt = f.read_text(encoding='utf-8', errors='ignore')
    names = set(call_re.findall(txt))
    for n in sorted(names):
        if n in ('alert','confirm','event','this','location','window','document','history','print'): continue
        scope = txt + globaljs + other_js + base + comps
        if not defined(n, scope):
            problems.append((str(f.relative_to(root)), n))
for f,n in problems:
    print(f, n)
print('TOTAL', len(problems))
