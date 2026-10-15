#!/usr/bin/env python3
"""transport.request / Resp: 通用请求通道 (给 MCP / LLM / 行情用)

在本地起一个 HTTP 服务当靶子, 验:
  - GET / POST(JSON) / POST(表单) 都能打, 状态码不藏 (4xx/5xx 照样给)
  - Resp 的读法对 cffi 与 urllib 两条底层一致 (text/content/json/iter_content)
  - raw_headers=True 时请求头由调用方全权给定 (上家协议敏感的通道要这个)
  - 默认走指纹会话, 且线路/证书仍由本层决策 (不自己判 auto)
  - 这条通道**不**做反爬处理: engine 非空也不进拦截判定/降级梯
"""
import json
import os
import sys
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TMP = tempfile.mkdtemp(prefix='webtool-tpreq-')
os.environ['WEBTOOL_DIR'] = TMP
os.environ.pop('HTTP_PROXY', None)
os.environ.pop('HTTPS_PROXY', None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from webtool.core import config_data              # noqa: E402
config_data.invalidate()
from webtool.net import intercept, transport      # noqa: E402

N = [0]
FAIL = []


def check(cond, msg, extra=''):
    N[0] += 1
    if cond:
        print(f'PASS {msg}' + (f' ({extra})' if extra else ''))
    else:
        FAIL.append(msg)
        print(f'FAIL {msg}' + (f' ({extra})' if extra else ''))


SEEN = []


class H(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    def _send(self, code, body=b'', ctype='text/plain; charset=utf-8', extra=None):
        self.send_response(code)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _record(self):
        n = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(n) if n else b''
        SEEN.append({'method': self.command, 'path': self.path,
                     'headers': {k.lower(): v for k, v in self.headers.items()},
                     'body': body})

    def do_GET(self):
        self._record()
        p = urllib.parse.urlparse(self.path)
        if p.path == '/json':
            self._send(200, json.dumps({'ok': True, 'q': p.query}).encode(),
                       'application/json; charset=utf-8')
        elif p.path == '/gbk':
            self._send(200, '中文'.encode('gbk'), 'text/plain; charset=gbk')
        elif p.path == '/404':
            self._send(404, b'nope')
        elif p.path == '/500':
            self._send(500, b'boom')
        elif p.path == '/big':
            self._send(200, b'x' * 300000)
        else:
            self._send(200, b'hello')

    def do_POST(self):
        self._record()
        p = urllib.parse.urlparse(self.path)
        if p.path == '/echo':
            self._send(200, self._last_body(), 'application/json')
        elif p.path == '/created':
            self._send(201, b'created')
        else:
            self._send(200, b'posted')

    def _last_body(self):
        return SEEN[-1]['body'] or b'{}'


srv = ThreadingHTTPServer(('127.0.0.1', 0), H)
PORT = srv.server_address[1]
BASE = f'http://127.0.0.1:{PORT}'
threading.Thread(target=srv.serve_forever, daemon=True).start()
time.sleep(0.2)

print('=== 1. GET: 状态码不藏, 读法与内容对得上 ===')
r = transport.request('GET', f'{BASE}/json', params={'a': '1', 'b': '中文'},
                      proxy='direct')
check(r.status_code == 200, 'GET 200', str(r.status_code))
check(r.json()['q'] == 'a=1&b=%E4%B8%AD%E6%96%87', 'params 编进查询串',
      r.json()['q'])
check(r.headers.get('content-type', '').startswith('application/json'),
      'Resp.headers 是小写键 dict', str(r.headers.get('content-type')))
check('a=1' in SEEN[-1]['path'], '服务端确实收到了 params', SEEN[-1]['path'])

r = transport.request('GET', f'{BASE}/404', proxy='direct')
check(r.status_code == 404, '4xx 如实给状态码 (不当异常抛)', str(r.status_code))
check(r.text == 'nope', '4xx 正文读得到', r.text)
r = transport.request('GET', f'{BASE}/500', proxy='direct')
check(r.status_code == 500, '5xx 如实给状态码', str(r.status_code))

r = transport.request('GET', f'{BASE}/gbk', proxy='direct')
check(r.text == '中文', 'GBK 页面按 charset 解出来', r.text)

r = transport.request('GET', f'{BASE}/big', proxy='direct')
_sz = sum(len(c) for c in r.iter_content(65536))
check(_sz == 300000, 'iter_content 能读完大响应', str(_sz))
r.close()

print('=== 2. POST: JSON / 表单 / 201 ===')
r = transport.request('POST', f'{BASE}/echo', json_body={'x': 1, 's': '值'},
                      proxy='direct')
check(r.status_code == 200 and json.loads(r.text) == {'x': 1, 's': '值'},
      'POST JSON 往返一致', r.text[:40])
check(SEEN[-1]['headers'].get('content-type', '').startswith('application/json'),
      'JSON 体自动带 Content-Type')

r = transport.request('POST', f'{BASE}/created', data=b'a=1',
                      headers={'Content-Type': 'application/x-www-form-urlencoded'},
                      proxy='direct')
check(r.status_code == 201, '201 照样给状态码', str(r.status_code))

print('=== 3. raw_headers: 头由调用方全权给定 ===')
transport.request('POST', f'{BASE}/echo', json_body={}, proxy='direct',
                  raw_headers=True,
                  headers={'Content-Type': 'application/json',
                           'User-Agent': 'my-llm-client/1.0',
                           'Accept': 'text/event-stream'})
_h = SEEN[-1]['headers']
check(_h.get('user-agent') == 'my-llm-client/1.0',
      'raw_headers 保住了调用方的 UA (没被指纹覆盖)', str(_h.get('user-agent')))
check(_h.get('accept') == 'text/event-stream', 'Accept 原样送出',
      str(_h.get('accept')))
check('sec-fetch-site' not in _h, 'raw_headers 不塞浏览器专属头')

print('=== 4. 默认: 走指纹会话, 且线路/证书仍由本层决策 ===')
transport.request('GET', f'{BASE}/json', proxy='direct')
_ua = SEEN[-1]['headers'].get('user-agent', '')
check('Mozilla/5.0' in _ua, '默认带浏览器指纹 (不是裸 python-urllib)', _ua[:40])
# 客户端提示 (sec-ch-ua) 是 Chrome 系指纹才发的头; 默认档案按进程轮换, 可能轮到
# 不发的 Safari 指纹 —— 要验"UA/客户端提示由档案统一给", 就指定一个 Chrome 档案
transport.request('GET', f'{BASE}/json', proxy='direct', profile='chrome131_win')
_h4 = SEEN[-1]['headers']
check('sec-ch-ua' in _h4 and _h4.get('user-agent', '') != '',
      'cffi 路径的 UA/客户端提示由指纹档案统一给', str(_h4.get('sec-ch-ua'))[:40])

_ok = True
try:
    transport.request('GET', f'{BASE}/json', proxy='auto')
except Exception as e:                             # noqa: BLE001
    _ok = False
    print('  auto 线路异常:', e)
check(_ok, "proxy='auto' 走 netx 决策而不是自己判 (本地直连不成问题)")

print('=== 5. 这条通道不做反爬处理 ===')
HITS = []


class Watch(intercept.Interceptor):
    name = 'watch'
    priority = 1

    def inspect(self, ctx):
        HITS.append(ctx.engine)
        return None


intercept.register(Watch)
transport.request('GET', f'{BASE}/json', proxy='direct', engine='google')
check(not HITS, 'engine 非空也不进拦截判定 (MCP/LLM/行情不该有验证码语义)',
      str(HITS))
check(intercept.cooldown_of('google') is None, '也不会顺手给引擎记冷却')

print('=== 6. 会话可复用自己的 (预热/攒 cookie 的通道) ===')
s, prof = transport.new_session(proxy='direct')
r = transport.request('GET', f'{BASE}/json', proxy='direct', session=s)
check(r.status_code == 200 and prof.get('impersonate'),
      'new_session 给的档案带 impersonate', str(prof.get('impersonate')))
check(hasattr(s, 'cookies'), '交回的会话是可复用的 (带 cookie jar)')

print()
print(f'{N[0] - len(FAIL)} PASS, {len(FAIL)} FAIL')
srv.shutdown()
sys.exit(1 if FAIL else 0)
