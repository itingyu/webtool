"""降级梯默认 0 步时, 插件给的绕法仍要生效一次 (且只一次)

背景: bypass 只在降级梯内部被调用, 而 ladder_steps 默认 0 —— 插件按契约
实现了绕法却永远跑不到。这里钉住三条行为:

1. 有绕法 → 试一次, 拿到正常页
2. 无绕法 → 首次被拦即报错, 不额外发请求 (默认仍不放大请求)
3. 绕法失败 → 只多打一次就报错, 不会无限重试
"""
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

TMP = tempfile.mkdtemp(prefix='webtool-bypass-')
os.environ['WEBTOOL_DIR'] = TMP
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# 刻意不写 ladder_steps: 验的就是"默认 0 步"下的行为
with open(os.path.join(TMP, 'config.json'), 'w', encoding='utf-8') as f:
    json.dump({}, f)

FAIL = []
N = [0]


def check(cond, msg, detail=''):
    N[0] += 1
    if cond:
        print('PASS %s' % msg)
    else:
        FAIL.append(msg)
        print('FAIL %s  %s' % (msg, detail))


BLOCKED = ('<html><head><title>Just a moment</title></head>'
           '<body>cf-challenge 请稍候</body></html>')
OK = '<html><head><title>正常</title></head><body>' + ('正文 ' * 400) + '</body></html>'

HITS = {'blocked': 0, 'blocked2': 0, 'ok': 0}


class _H(BaseHTTPRequestHandler):
    def do_GET(self):                       # noqa: N802
        if self.path.startswith('/ok'):
            HITS['ok'] += 1
            body, code = OK, 200
        elif self.path.startswith('/blocked2'):
            HITS['blocked2'] += 1
            body, code = BLOCKED, 200
        else:
            HITS['blocked'] += 1
            body, code = BLOCKED, 200
        raw = body.encode('utf-8')
        self.send_response(code)
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

from webtool.net import captcha, intercept, transport      # noqa: E402
from webtool.net.intercept import Bypass, Hit, Interceptor  # noqa: E402


class _Time:
    """退避换成记账, 测试不真等"""

    def __init__(self, real):
        self._real = real

    def __getattr__(self, n):
        return getattr(self._real, n)

    def sleep(self, s):
        pass


transport.time = _Time(time)


class Bypasser(Interceptor):
    """给 /blocked 一条绕法: 换到 /ok"""
    name = 'bypasser'
    priority = 20

    def inspect(self, ctx):
        if 'cf-challenge' in (ctx.text or ''):
            return Hit(kind='waf', why='质询页', sign='cf-challenge')
        return None

    def bypass(self, ctx, hit):
        return Bypass(how='换通道', url=ctx.url.replace('/blocked', '/ok'))


# ── 1. 无绕法: 首次被拦即报错, 只打一次 ────────────────────────────────
captcha.mark_ok('eng1')
before = HITS['blocked']
err = None
try:
    transport.get(BASE + '/blocked', engine='eng1', proxy='direct', timeout=5)
except Exception as e:                      # noqa: BLE001
    err = e
check(err is not None and type(err).__name__ == 'BlockedError',
      '默认 0 步: 被拦当场报错', repr(err))
check(HITS['blocked'] == before + 1,
      '无绕法时不多发请求 (1 次被拦不放大)', str(HITS))

# ── 2. 有绕法: 试一次并拿到正常页 ──────────────────────────────────────
intercept.register(Bypasser)
captcha.mark_ok('eng2')
before_b, before_ok = HITS['blocked'], HITS['ok']
txt, err2 = '', None
try:
    txt, _st, _via = transport.get(BASE + '/blocked', engine='eng2',
                                   proxy='direct', timeout=5)
except Exception as e:                      # noqa: BLE001
    err2 = e
check(err2 is None and '正文' in txt,
      '默认 0 步: 插件绕法仍被执行一次', repr(err2))
check(HITS['blocked'] == before_b + 1, '绕法只重试一次', str(HITS))
check(HITS['ok'] == before_ok + 1, '绕法目标被请求到', str(HITS))

# ── 3. 绕法也失败: 只多打一次就报错, 不无限重试 ─────────────────────────
class BadBypass(Interceptor):
    name = 'badbypass'
    priority = 15

    def inspect(self, ctx):
        if 'cf-challenge' in (ctx.text or ''):
            return Hit(kind='waf', why='质询页', sign='cf-challenge')
        return None

    def bypass(self, ctx, hit):
        return Bypass(how='换到另一个同样被拦的地址',
                      url=ctx.url.replace('/blocked', '/blocked2'))


intercept.register(BadBypass)
captcha.mark_ok('eng3')
b1, b2 = HITS['blocked'], HITS['blocked2']
err3 = None
try:
    transport.get(BASE + '/blocked', engine='eng3', proxy='direct', timeout=5)
except Exception as e:                      # noqa: BLE001
    err3 = e
check(err3 is not None, '绕法失败后报错', repr(err3))
check(HITS['blocked'] == b1 + 1 and HITS['blocked2'] == b2 + 1,
      '绕法失败不放大成多次请求', str(HITS))

_srv.shutdown()

print()
print('%d PASS, %d FAIL' % (N[0] - len(FAIL), len(FAIL)))
sys.exit(1 if FAIL else 0)
