"""外部（非 Python）拦截器 + 无源码加载

覆盖:
1. stdio NDJSON 适配器: 判定 / 绕法 / 域名隔离
2. 超时或进程挂掉: 静默跳过, 不拖垮请求
3. 体检: 能启动算 ok, 起不来归 missing (不算失败)
4. .pyc / zip 形态的 Python 插件可以直接 import
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import zipfile
from contextlib import redirect_stdout

TMP = tempfile.mkdtemp(prefix='webtool-ext-')
os.environ['WEBTOOL_DIR'] = TMP
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

PLUG = os.path.join(TMP, 'plug.py')
with open(PLUG, 'w', encoding='utf-8') as f:
    f.write('''import json, sys
for line in sys.stdin:
    m = json.loads(line)
    op = m.get("op")
    out = {}
    if op == "ping":
        out = {"ok": True}
    elif op == "inspect":
        out = ({"hit": {"kind": "waf", "sign": "ext-block", "why": "外部判定"}}
               if "ext-block" in m["ctx"].get("text", "") else {})
    elif op == "bypass":
        out = {"bypass": {"how": "外部换通道",
                          "url": m["ctx"]["url"].replace("/blocked", "/ok")}}
    print(json.dumps(out, ensure_ascii=False), flush=True)
''')

with open(os.path.join(TMP, 'plugins.json'), 'w', encoding='utf-8') as f:
    json.dump({'interceptor': {'ext1': {
        'type': 'external', 'command': [sys.executable, PLUG],
        'timeout': 0.5, 'hosts': ['example.com']}}}, f)

FAIL = []
N = [0]


def check(cond, msg, detail=''):
    N[0] += 1
    if cond:
        print('PASS %s' % msg)
    else:
        FAIL.append(msg)
        print('FAIL %s  %s' % (msg, detail))


os.environ['WEBTOOL_PLUGIN_DIR'] = os.path.join(TMP, 'plugins')

from webtool.net import intercept                              # noqa: E402
from webtool.net.extproc import ExternalInterceptor, probe     # noqa: E402

# ── 1. 判定 / 绕法 / 域名隔离 ────────────────────────────────────────────
names = [p.name for p in intercept.interceptors()]
check('ext1' in names, '配置里的外部插件已生效', names)

ctx = intercept.Ctx(url='https://example.com/a?x=1', status=200,
                    text='页里有 ext-block 标记')
hit = intercept.inspect(ctx)
check(hit is not None and hit.by == 'ext1' and hit.sign == 'ext-block',
      '外部插件判出 Hit', str(hit))

bp = intercept.bypass(intercept.Ctx(url='https://example.com/blocked?x=1', text=''), hit)
check(bp is not None and '/ok?' in bp.url, '外部插件给出绕法', str(bp))

check(intercept.inspect(intercept.Ctx(url='https://example.com/b',
                                      text='正常页面')) is None,
      '正常页不误报')
check(intercept.inspect(intercept.Ctx(url='https://other.com/c',
                                      text='ext-block')) is None,
      '非目标域名不会被调用 (hosts 分发)')

# ── 2. 超时只让插件掉队 ─────────────────────────────────────────────────
slow = os.path.join(TMP, 'slow.py')
with open(slow, 'w', encoding='utf-8') as f:
    f.write('import time\nwhile True: time.sleep(1)\n')
inst = ExternalInterceptor()
inst.configure('slow', {'command': [sys.executable, slow], 'timeout': 0.15,
                        'params': {}})
t0 = time.time()
check(inst.inspect(intercept.Ctx(url='https://example.com/x', text='x')) is None,
      '超时返回 None (不抛错)')
check(time.time() - t0 < 1.0, '超时按配置生效', round(time.time() - t0, 2))
t1 = time.time()
check(inst.inspect(intercept.Ctx(url='https://example.com/x', text='x')) is None
      and time.time() - t1 < 0.05, '失败后 30s 内不再重试拉起')
inst.close()

# ── 3. 体检: 起得来算 ok, 起不来算 missing ──────────────────────────────
check(probe({'command': [sys.executable, PLUG], 'timeout': 0.5}, 'ext1')[0],
      'probe: 正常插件 ping 通')
ok_bad, why_bad = probe({'command': ['/no/such/binary'], 'timeout': 0.2}, 'bad')
check(ok_bad is False and why_bad, 'probe: 起不来给出原因', why_bad)

with open(os.path.join(TMP, 'plugins.json'), encoding='utf-8') as f:
    cfg = json.load(f)
cfg['interceptor']['ext_bad'] = {'type': 'external',
                                 'command': ['/no/such/binary'],
                                 'timeout': 0.2}
with open(os.path.join(TMP, 'plugins.json'), 'w', encoding='utf-8') as f:
    json.dump(cfg, f)
from webtool.core import config_data                     # noqa: E402
config_data.invalidate()

from webtool.cli import plugins as cli_plugins           # noqa: E402
buf = io.StringIO()
with redirect_stdout(buf):
    code = cli_plugins._check()
rep = json.loads(buf.getvalue())
check(code == 0 and rep['failed'] == 0, '体检退出码 0, 外部插件缺失不算失败', rep)
check(any(m['plugin'] == 'ext_bad' for m in rep['missing_plugins']),
      '缺失的外部插件归入 missing', rep['missing_plugins'])

# ── 4. 无源码: .pyc / zip 都能按 entry 加载 ─────────────────────────────
pdir = os.path.join(TMP, 'plugins')
os.makedirs(pdir, exist_ok=True)
src = os.path.join(pdir, 'sourceless.py')
with open(src, 'w', encoding='utf-8') as f:
    f.write('def ping():\n    return "pong"\n')
subprocess.run([sys.executable, '-m', 'compileall', '-b', '-q', src], check=True)
os.remove(src)
from webtool.core import plugins as core_plugins         # noqa: E402
check(core_plugins._import_target('sourceless:ping')() == 'pong',
      '.pyc 无源码可加载')

zpath = os.path.join(pdir, 'zpkg.zip')
with zipfile.ZipFile(zpath, 'w') as z:
    z.writestr('zplug/__init__.py', '')
    z.writestr('zplug/mod.py', 'def ping():\n    return "zip-pong"\n')
check(core_plugins._import_target('zplug.mod:ping')() == 'zip-pong',
      'zip 包可加载')

# ── 5. 真请求: 被拦 → 外部绕法 → 拿到正常页 ────────────────────────────
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

HITS = {'blocked': 0, 'ok': 0}


class _H(BaseHTTPRequestHandler):
    def do_GET(self):                       # noqa: N802
        if self.path.startswith('/ok'):
            HITS['ok'] += 1
            body = '<html><body>OK-PAGE</body></html>'
        else:
            HITS['blocked'] += 1
            body = '<html><body>ext-block</body></html>'
        raw = body.encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


srv = HTTPServer(('127.0.0.1', 0), _H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = 'http://127.0.0.1:%d' % srv.server_address[1]

cfg['interceptor']['ext1']['hosts'] = ['127.0.0.1']
with open(os.path.join(TMP, 'plugins.json'), 'w', encoding='utf-8') as f:
    json.dump(cfg, f)
config_data.invalidate()

from webtool.net import transport        # noqa: E402
txt, st, via = transport.get(BASE + '/blocked?x=1', proxy='direct', timeout=5)
check('OK-PAGE' in txt and HITS['ok'] >= 1,
      'transport 执行外部绕法并拿到正文', (HITS, txt[:40]))
srv.shutdown()

print('\n%d PASS, %d FAIL' % (N[0] - len(FAIL), len(FAIL)))
sys.exit(1 if FAIL else 0)
