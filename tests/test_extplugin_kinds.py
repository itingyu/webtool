"""外部插件推广到所有类别: filter / engine 走 `op=call`

验证注册表里 type=external 的声明被套成普通 callable, 上层代码无需改。
"""
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout

TMP = tempfile.mkdtemp(prefix='webtool-kinds-')
os.environ['WEBTOOL_DIR'] = TMP
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

PLUG = os.path.join(TMP, 'plug.py')
with open(PLUG, 'w', encoding='utf-8') as f:
    f.write('''import json, sys
for line in sys.stdin:
    m = json.loads(line)
    op = m.get("op")
    if op == "ping":
        print(json.dumps({"ok": True, "protocol": 1}), flush=True)
        continue
    if op != "call":
        print("{}", flush=True)
        continue
    kind, args = m.get("kind"), m.get("args") or []
    if kind == "filter":
        rows = args[0] if args else []
        keep = [r for r in rows if "docs" in (r.get("url") or "")]
        out = {"result": keep}
    elif kind == "engine":
        q = args[0] if args else ""
        out = {"result": [{"title": "外部引擎:" + q, "url": "https://e/" + q,
                           "snippet": "from ext"}]}
    else:
        out = {"result": None}
    print(json.dumps(out, ensure_ascii=False), flush=True)
''')

with open(os.path.join(TMP, 'plugins.json'), 'w', encoding='utf-8') as f:
    json.dump({'filter': {'only_docs': {
                  'type': 'external', 'command': [sys.executable, PLUG]}},
               'engine': {'fake_eng': {
                  'type': 'external', 'command': [sys.executable, PLUG]}}}, f)

FAIL = []
N = [0]


def check(cond, msg, detail=''):
    N[0] += 1
    if cond:
        print('PASS %s' % msg)
    else:
        FAIL.append(msg)
        print('FAIL %s  %s' % (msg, detail))


from webtool.core import config_data, plugins       # noqa: E402
from webtool.cli import plugins as cli_plugins      # noqa: E402

# ── 1. filter: 普通 callable, 上层无感 ─────────────────────────────────
rows = [{'url': 'https://a/docs/1'}, {'url': 'https://b/x'}]
fn = plugins.FILTERS['only_docs']['fn']
out = fn(rows, {})
check(isinstance(out, list) and len(out) == 1 and 'docs' in out[0]['url'],
      '外部 filter 直接可调用', out)

# ── 2. engine: 同一套协议换 kind ───────────────────────────────────────
efn = plugins.ENGINES['fake_eng']['fn']
res = efn('minis', 3)
check(isinstance(res, list) and res and res[0]['title'].endswith('minis'),
      '外部 engine 返回结果', res)

# ── 3. 起不来的外部插件: 调用静默 None, 体检算 missing ─────────────────
with open(os.path.join(TMP, 'plugins.json'), encoding='utf-8') as f:
    cfg = json.load(f)
cfg['filter']['bad_ext'] = {'type': 'external', 'command': ['/no/such/bin'],
                            'timeout': 0.2}
with open(os.path.join(TMP, 'plugins.json'), 'w', encoding='utf-8') as f:
    json.dump(cfg, f)
config_data.invalidate()

bad = plugins.FILTERS['bad_ext']['fn']
check(bad([{'url': 'x'}], {}) is None, '不可用的外部插件调用返回 None (不抛)')

buf = io.StringIO()
with redirect_stdout(buf):
    code = cli_plugins._check()
rep = json.loads(buf.getvalue())
check(code == 0 and rep['failed'] == 0, '体检退出码 0', rep['failed'])
check(any(m['plugin'] == 'bad_ext' and m['kind'] == 'filter'
          for m in rep['missing_plugins']), 'filter 类别缺失归入 missing',
      rep['missing_plugins'])

print('\n%d PASS, %d FAIL' % (N[0] - len(FAIL), len(FAIL)))
sys.exit(1 if FAIL else 0)
