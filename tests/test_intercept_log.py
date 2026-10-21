"""拦截检测覆盖所有页面通道 + 拦截日志

不联外网: 本地 HTTP 服务模拟 Cloudflare 式验证页
"""
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

TMP = tempfile.mkdtemp(prefix='webtool-int-')
os.environ['WEBTOOL_DIR'] = TMP
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

FAIL, N = [], [0]


def check(cond, msg, detail=''):
    N[0] += 1
    print(('PASS ' if cond else 'FAIL ') + msg + ('' if cond else '  ' + str(detail)))
    if not cond:
        FAIL.append(msg)


CHALLENGE = ('<html><head><title>Just a moment...</title></head><body>'
             + '<div>Checking your browser before accessing.</div>' * 200 +
             '</body></html>')
NORMAL = ('<html><head><title>正常文章</title></head><body>'
          + '<p>正文内容</p>' * 300 + '</body></html>')
HITS = {'challenge': 0, 'ok': 0}


class _H(BaseHTTPRequestHandler):
    def do_GET(self):                       # noqa: N802
        if self.path.startswith('/ok'):
            HITS['ok'] += 1
            body = NORMAL
        else:
            HITS['challenge'] += 1
            body = CHALLENGE
        raw = body.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


_srv = HTTPServer(('127.0.0.1', 0), _H)
PORT = _srv.server_address[1]
threading.Thread(target=_srv.serve_forever, daemon=True).start()
BASE = 'http://127.0.0.1:%d' % PORT

from webtool.net import intercept, transport          # noqa: E402
from webtool.net.intercept import Bypass, Hit, Interceptor  # noqa: E402


class LocalFix(Interceptor):
    name, priority = 'local_fix', 30
    hosts = ('127.0.0.1',)

    def inspect(self, ctx):
        if 'Just a moment' in (ctx.text or ''):
            return Hit(kind='captcha', sign='title:just a moment', why='本地验证页')
        return None

    def bypass(self, ctx, hit):
        return Bypass(how='换正常页', url=BASE + '/ok')


intercept.register(LocalFix)

from webtool.pipeline.fetch import _verify_bypass   # noqa: E402


def _log_rows():
    p = intercept.log_path()
    if not os.path.exists(p):
        return []
    with open(p, encoding='utf-8') as f:
        return [json.loads(x) for x in f if x.strip()]


# ── 1. fetch 通道: 非公众号站点也会检测并绕行 ───────────────────────────
md, st, via, replaced = _verify_bypass(BASE + '/s?x=1', CHALLENGE, 200, 'cffi',
                                       proxy='direct', timeout=5)
check(replaced and '正常文章' in md, 'fetch: 验证页被绕行拿到正文', (st, md[:40]))
rows = _log_rows()
acts = [r['action'] for r in rows]
check('blocked' in acts and 'bypass' in acts and 'passed' in acts,
      'fetch: 日志含 被拦/绕行/通过', acts)
check(all(r['site'] == '127.0.0.1' for r in rows),
      'fetch: 日志按站点记', [r['site'] for r in rows])
check(rows[0]['url'].startswith(BASE), 'fetch: 日志记了原始 URL', rows[0]['url'])
check(rows[-1].get('detail', '').startswith('fetch 绕法成功'),
      'fetch: 成功原因落在 detail', rows[-1].get('detail'))

# ── 2. 无引擎名的页面通道 (transport.get) 也要检测 ──────────────────────
# 换个 host 走: LocalFix 只认 127.0.0.1, 这里要验的是"没有绕法 → 抛错"的分支
before = len(_log_rows())
try:
    transport.get(BASE.replace('127.0.0.1', 'localhost') + '/s?x=2',
                  proxy='direct', timeout=5)
    err = None
except Exception as e:                      # noqa: BLE001
    err = e
check(type(err).__name__ == 'BlockedError', '无引擎名: 被拦并抛出', repr(err))
rows = _log_rows()[before:]
acts = [r['action'] for r in rows]
check('blocked' in acts and 'failed' in acts, '无引擎名: 日志含 被拦/失败', acts)
check(all(r['site'] == 'localhost' for r in rows),
      '无引擎名: 检测键就是站点', [r['site'] for r in rows])
check(any('仍被拦' in (r.get('detail') or '') for r in rows),
      '无引擎名: 失败原因写明重试结果', rows[-1].get('detail'))

# ── 3. 正常页不写日志 (日志只记判定过的事件) ───────────────────────────
before = len(_log_rows())
_verify_bypass(BASE + '/ok?x=1', NORMAL, 200, 'cffi', proxy='direct', timeout=5)
check(len(_log_rows()) == before, '正常页不产生日志', len(_log_rows()) - before)

# ── 4. 日志只留一份轮转文件, 且清空可用 ────────────────────────────────
p = intercept.log_path()
check(os.path.getsize(p) > 0, '日志文件已落盘', p)
os.remove(p)
check(not os.path.exists(p), '删除即清空 (--clear 同义)')

_srv.shutdown()
print('\n%d PASS, %d FAIL' % (N[0] - len(FAIL), len(FAIL)))
sys.exit(1 if FAIL else 0)
