"""net.transport ↔ net.intercept 的接线: 拦截判定、冷却门、绕法真的生效

前一个文件测抽象层本身, 这里测"接到 transport 上还灵不灵" —— 用本地 HTTP
服务造真响应, 走 transport.get 的完整路径 (含降级梯与重试)。
"""
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

TMP = tempfile.mkdtemp(prefix='webtool-tpwiring-')
os.environ['WEBTOOL_DIR'] = TMP
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

FAIL = []
N = [0]


def check(name, cond, detail=''):
    N[0] += 1
    if cond:
        print('PASS %s' % name)
    else:
        FAIL.append(name)
        print('FAIL %s  %s' % (name, detail))


CAPTCHA_PAGE = ('<html><head><title>Please verify you are human</title>'
                '</head><body>请完成验证后继续访问</body></html>')
NORMAL_PAGE = '<html><head><title>正常结果页</title></head><body>' + \
              ('正常内容 ' * 400) + '</body></html>'
WAF_PAGE = '<html><head><title>拦截</title></head><body>' + \
           ('被盾 ' * 400) + '</body></html>'

HITS = {'captcha': 0, 'waf': 0}


class _H(BaseHTTPRequestHandler):
    def do_GET(self):                       # noqa: N802
        if self.path.startswith('/waf'):
            HITS['waf'] += 1
            body = WAF_PAGE
        elif self.path.startswith('/ok'):
            body = NORMAL_PAGE
        else:
            HITS['captcha'] += 1
            body = CAPTCHA_PAGE
        raw = body.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):              # 别往 stderr 喷日志
        pass


_srv = HTTPServer(('127.0.0.1', 0), _H)
PORT = _srv.server_address[1]
threading.Thread(target=_srv.serve_forever, daemon=True).start()
BASE = 'http://127.0.0.1:%d' % PORT

from webtool.net import captcha, intercept, transport     # noqa: E402
from webtool.net.intercept import Bypass, Hit, Interceptor   # noqa: E402

# 别真等: 退避与节奏控制换成记账, 断言还能看到"该等的时候等了"
SLEPT = []


class _Time:
    def __init__(self, real):
        self._real = real

    def __getattr__(self, n):
        return getattr(self._real, n)

    def sleep(self, s):
        SLEPT.append(s)


transport.time = _Time(time)

# ── 1. 判定接上了: 真响应里认得出验证页, 且记账 ──────────────────────────
t0 = len(SLEPT)
try:
    transport.get(BASE + '/s?q=x', engine='baidu', proxy='direct', timeout=5)
    err = None
except Exception as e:                      # noqa: BLE001
    err = e
check('验证页在 transport 里被判成"拦截"并报错',
      err is not None and '验证页拦截' in str(err), repr(err))
check('报错带上判定依据与冷却剩余',
      err is not None and '(' in str(err) and '冷却' in str(err), repr(err))
check('被拦后引擎进冷却 (note_hit 真的记了账)', captcha.suspended('baidu'))
check('降级梯里做了退避 (没白重试)', len(SLEPT) > t0, str(SLEPT[t0:]))
check('梯子重试了多次 (每次都撞上验证页)',
      HITS['captcha'] >= 2, str(HITS))

# ── 2. 冷却门接上了: 再发就拦在门口 (transport 不认识"验证码") ────────────
try:
    transport.get(BASE + '/s?q=x', engine='baidu', proxy='direct', timeout=5)
    err2 = None
except Exception as e:                      # noqa: BLE001
    err2 = e
check('冷却期内直接挡回 (CooldownError)',
      err2 is not None and type(err2).__name__ == 'CooldownError', repr(err2))
check('挡回的人话来自插件 (transport 不认识"验证码")',
      err2 is not None and '人机验证' in str(err2), repr(err2))
check('挡住时不发请求', HITS['captcha'] == 4, str(HITS))

# ── 3. 复位后能正常拿到正文 ──────────────────────────────────────────────
captcha.mark_ok('baidu')
try:
    txt, status, via = transport.get(BASE + '/ok', engine='baidu',
                                     proxy='direct', timeout=5)
    err3 = None
except Exception as e:                      # noqa: BLE001
    txt, err3 = '', e
check('复位后正常页直接返回', err3 is None and '正常内容' in txt, repr(err3))

# ── 4. 绕法生效: 新加的插件能改下一次重试的形状 ──────────────────────────
class Waf(Interceptor):
    """判 WAF 页并给绕法: 换到 /ok 通道 —— transport 该照办"""
    name = 'waf'
    priority = 30

    def inspect(self, ctx):
        if '被盾' in (ctx.text or ''):
            return Hit(kind='waf', why='WAF 拦截', sign='正文含 被盾')
        return None

    def bypass(self, ctx, hit):
        return Bypass(how='换通道重试', url=ctx.url.replace('/waf', '/ok'))


intercept.register(Waf)
before = HITS['waf']
try:
    txt4, _st, _via = transport.get(BASE + '/waf', engine='wafsrv',
                                    proxy='direct', timeout=5)
    err4 = None
except Exception as e:                      # noqa: BLE001
    txt4, err4 = '', e
check('插件给的绕法被 transport 执行 (换地址后拿到正常页)',
      err4 is None and '正常内容' in txt4, repr(err4))
check('绕法只在被拦后才用 (不是自动改写请求)', HITS['waf'] == before + 1,
      str(HITS))

_srv.shutdown()

print()
print('%d PASS, %d FAIL' % (N[0] - len(FAIL), len(FAIL)))
sys.exit(1 if FAIL else 0)
