"""绕法里的 cookie / UA 有没有真的进请求

场景: 求解器插件拿到 cf_clearance 后, 把它交回给 webtool, 下一次重试必须
带着这个 cookie (而且要灌进会话 jar, 不是裸 Cookie 头 —— 裸头会和会话自己
的 cookie 打架, 也会被目标站刚下发的 Set-Cookie 覆盖)。
"""
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
_TMP = tempfile.mkdtemp(prefix='wt-bypass-')
os.environ['WEBTOOL_DIR'] = _TMP

from webtool.net import intercept, transport          # noqa: E402

checks = fails = 0


def check(cond, msg, got=''):
    global checks, fails
    if cond:
        checks += 1
        print('PASS', msg)
    else:
        fails += 1
        print('FAIL', msg, '|', got)


SEEN = []
ACTIVE = {'on': True}
STATE = {'blocked': False}


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        SEEN.append({'cookie': self.headers.get('Cookie', ''),
                     'ua': self.headers.get('User-Agent', ''),
                     'path': self.path})
        body = b'<html><body>hello</body></html>'
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


srv = ThreadingHTTPServer(('127.0.0.1', 0), H)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
time.sleep(0.2)
URL = f'http://127.0.0.1:{PORT}/p'

# 插件: 见什么都判被拦, 绕法是"带上求解器给的 cookie 与 UA"
class Solver(intercept.Interceptor):
    name = 'solver'
    priority = 1

    def inspect(self, ctx):
        if not ctx.text or not ACTIVE['on']:
            return None
        # 只拦第一次: 带上 clearance 之后就该放行 (真实质询就是这个语义)
        if STATE['blocked']:
            return None
        STATE['blocked'] = True
        return intercept.Hit(kind='cf_challenge', by=self.name,
                             sign='测试用', why='质询拦截',
                             hint='用求解器过')

    def bypass(self, ctx, hit):
        return intercept.Bypass(how='带 clearance 重试',
                                cookies={'cf_clearance': 'CLEAR-123'},
                                user_agent='Mozilla/5.0 (solver-ua)')


intercept.register(Solver)

# ── 1. 绕法里的 cookie 真的发出去了 ──────────────────────────────────────
text, status, via = transport.get(URL, proxy='direct', timeout=10)
check(status == 200, '重试后拿到 200', str(status))
check(len(SEEN) >= 2, '至少请求了两次 (首次被拦 + 带 cookie 重试)', str(len(SEEN)))
check('cf_clearance=CLEAR-123' in SEEN[-1]['cookie'],
      'cookie 进了重试请求', SEEN[-1]['cookie'])
check(SEEN[-1]['ua'] == 'Mozilla/5.0 (solver-ua)',
      'UA 跟着绕法换了', SEEN[-1]['ua'])

# ── 2. 没给 cookie 的请求不该凭空多出 Cookie 头 ─────────────────────────
SEEN.clear()
ACTIVE['on'] = False

transport.get(URL, proxy='direct', timeout=10)
check(not SEEN[-1]['cookie'] or 'cf_clearance' not in SEEN[-1]['cookie'],
      '没给绕法就不该带 clearance', SEEN[-1]['cookie'])
ACTIVE['on'] = True

# ── 3. Bypass / SDK 的字段齐全 ───────────────────────────────────────────
bp = intercept.Bypass(how='x', cookies={'a': '1'}, user_agent='UA')
check(bp.cookies == {'a': '1'} and bp.user_agent == 'UA',
      'Bypass 带 cookie 与 UA 字段')
check(intercept.Bypass().cookies == {} and intercept.Bypass().user_agent == '',
      '默认空值 (不改变老插件行为)')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'sdk', 'python'))
import webtool_plugin_sdk as sdk                      # noqa: E402
d = sdk.bypass(how='x', cookies={'cf_clearance': 'C'}, user_agent='UA')['bypass']
check(d['cookies'] == {'cf_clearance': 'C'} and d['user_agent'] == 'UA',
      'SDK bypass() 带 cookie 与 UA', str(d))

# ── 4. 外部插件协议映射不丢字段 ─────────────────────────────────────────
from webtool.net import extproc                     # noqa: E402
ep = extproc.ExternalInterceptor()
ep._ask = lambda op, **kw: {'bypass': {'how': 'h', 'cookies': {'k': 'v'},
                                       'user_agent': 'UA'}} if op == 'bypass' else {}
b = ep.bypass(intercept.Ctx(url='https://x.com', text='t'), intercept.Hit(kind='k'))
check(b is not None and b.cookies == {'k': 'v'} and b.user_agent == 'UA',
      '外部插件的 cookie/UA 映射到 Bypass', str(b))

print()
print(f'{checks} PASS, {fails} FAIL')
sys.exit(1 if fails else 0)
