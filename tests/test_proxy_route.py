# -*- coding: utf-8 -*-
"""代理线路自检的回归测试

盯两个曾经真实发生的坑:
  1. 显式指定的代理被 `no_proxy` 绕过 —— `no_proxy='*'`(或 `.host` 后缀形式)
     会让"规则表判了走代理"的请求静默直连, `proxy test` 还把死代理报成 OK。
  2. `proxy test` 只回 OK/FAIL, 不说这条线是否与目标 URL 的真实线路一致。

跑法: python3 tests/test_proxy_route.py
"""
import contextlib
import http.server
import io
import json
import os
import socket
import socketserver
import sys
import tempfile
import threading
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'src'))

# 配置目录要在 import 之前定好 (load_config 读 WEBTOOL_DIR)
TMP = tempfile.mkdtemp(prefix='webtool-proxy-test-')
os.environ['WEBTOOL_DIR'] = TMP
with open(os.path.join(TMP, 'rules.json'), 'w', encoding='utf-8') as f:
    json.dump({'default': 'proxy:default',
               'proxies': {'default': 'http://127.0.0.1:2080',
                           'ghost': 'http://127.0.0.1:2080'},
               'rules': [{'match': {'domain': ['*.cn']}, 'action': 'direct'},
                         {'match': {'domain': ['*.so.com']}, 'action': 'direct'}]}, f)

from webtool.net import http as whttp
from webtool.net import netx as wnetx
from webtool.net import proxy as wproxy
from webtool.net import proxyhelper as wpxh

fails = []


def check(cond, msg, detail=''):
    if cond:
        print(f'PASS {msg}')
    else:
        print(f'FAIL {msg} {detail}')
        fails.append(msg)


def dead_port():
    """拿一个确定没人监听的端口 (关掉临时 socket 后的那个号)"""
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _FakeProxy(http.server.BaseHTTPRequestHandler):
    """假代理: 收绝对形式请求 (proxy 风格) 并回 204

    够用来判定"请求到底有没有交给代理" —— 因为目标域名用的是 .invalid,
    DNS 必然解析失败, 只有代理这条路径能拿到 204。
    """
    seen = []

    def do_GET(self):
        type(self).seen.append(self.path)
        self.send_response(204)
        self.end_headers()

    def log_message(self, *a):
        pass


def serve_fake_proxy():
    srv = socketserver.TCPServer(('127.0.0.1', 0), _FakeProxy)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f'http://127.0.0.1:{srv.server_address[1]}'


# --- 1. 显式代理不被 no_proxy 绕过 -------------------------------------------
srv, proxy_url = serve_fake_proxy()
os.environ['no_proxy'] = '*'
os.environ['NO_PROXY'] = '*'
try:
    op = whttp.build_opener(proxy_url)
    r = op.open('http://nothing.invalid/x', timeout=10)
    check(r.status == 204, 'no_proxy=* 时显式代理仍生效', r.status)
    check(any('nothing.invalid' in p
                                    for p in _FakeProxy.seen), '请求确实交给了代理', _FakeProxy.seen)
except Exception as e:
    check(False, 'no_proxy=* 时显式代理仍生效', str(e)[:120])

# 直连 opener 仍不该偷偷用环境里的代理 (两条路径不能互相污染)
try:
    op2 = whttp.build_opener('direct')
    try:
        op2.open('http://nothing.invalid/x', timeout=5)
        check(False, 'direct 不被环境代理劫持', '竟然连通了')
    except Exception:
        check(True, 'direct 不被环境代理劫持')
except Exception as e:
    check(False, 'direct 不被环境代理劫持', str(e)[:120])

# --- 2. 死代理 + no_proxy=* 必须 FAIL (曾经报 OK) -----------------------------
port = dead_port()
cfg = wproxy.load_config()
buf_o, buf_e = io.StringIO(), io.StringIO()
with contextlib.redirect_stdout(buf_o), contextlib.redirect_stderr(buf_e):
    rc = wproxy._test(types.SimpleNamespace(
        value=f'http://127.0.0.1:{port}', url=None), cfg)
out = buf_o.getvalue() + buf_e.getvalue()
check(rc == 1, '死代理 + no_proxy=* 判 FAIL', f'rc={rc} out={out.strip()[:120]}')
check(f'127.0.0.1:{port}' in out, 'FAIL 信息里带上被绕过的代理地址', out[:120])

# --- 3. 目标线路与所测代理不一致时要说明 --------------------------------------
buf_o, buf_e = io.StringIO(), io.StringIO()
with contextlib.redirect_stdout(buf_o), contextlib.redirect_stderr(buf_e):
    rc = wproxy._test(types.SimpleNamespace(
        value=proxy_url, url='http://x.cn/robots.txt'), cfg)
out = buf_o.getvalue() + buf_e.getvalue()
check('不是一条线' in out, '目标走直连时提示"不是一条线"', out.strip()[:160])

# --- 4. 线路比较只看 scheme://host:port --------------------------------------
check(wproxy._norm_proxy_url('http://h:1/') ==
      wproxy._norm_proxy_url('http://h:1'), '线路比较忽略尾斜杠')
check(wproxy._norm_proxy_url('1.2.3.4:8080') ==
      'http://1.2.3.4:8080', '裸 host:port 自动补 scheme')
check(wproxy._proxy_is_used(
    cfg, 'http://127.0.0.1:2080'), '被 default 引用的代理算"在用"')
check(not wproxy._proxy_is_used(
    cfg, 'http://127.0.0.1:34567'), '没人引用的代理不算"在用"')

srv.shutdown()
# --- 5. proxy=None 必须与 'auto' 同义 (曾经是"强制直连", 规则表连问都不问) ----
# 症状: 引擎签名都写 `proxy=None`, 谁忘了把管线传下来的 'auto' 再传下去,
# 谁的会话就永久直连 —— 用户在 rules.json 里写的域名规则对那个引擎完全失效。
DIRECT_URL = 'https://www.so.com/s?q=x'          # 命中 *.so.com -> direct
DEFAULT_URL = 'https://example.com/page'         # 无规则命中 -> default 代理
DEFAULT_PX = 'http://127.0.0.1:2080'

check(wnetx.resolve_proxy(None, DEFAULT_URL) == wnetx.resolve_proxy('auto', DEFAULT_URL),
      'None 与 auto 同结果 (无规则命中处)',
      f'{wnetx.resolve_proxy(None, DEFAULT_URL)!r} vs {wnetx.resolve_proxy("auto", DEFAULT_URL)!r}')
check(wnetx.resolve_proxy(None, DEFAULT_URL) == DEFAULT_PX,
      'None 会走默认代理而非被当成直连',
      repr(wnetx.resolve_proxy(None, DEFAULT_URL)))
check(wnetx.resolve_proxy(None, DIRECT_URL) is None,
      'None 时域名规则仍然生效',
      repr(wnetx.resolve_proxy(None, DIRECT_URL)))
check(wnetx.resolve_proxy('direct', DEFAULT_URL) is None,
      "显式 'direct' 才是强制直连",
      repr(wnetx.resolve_proxy('direct', DEFAULT_URL)))

# 两条入口 (transport 走 netx / resilient·feeds 走 proxyhelper) 不能再给出相反答案
for _u in (DEFAULT_URL, DIRECT_URL):
    check(wnetx.resolve_proxy(None, _u) == wpxh.resolve(None, _u),
          f'两条入口对 None 一致 ({_u.split("/")[2]})',
          f'netx={wnetx.resolve_proxy(None, _u)!r} proxyhelper={wpxh.resolve(None, _u)!r}')

check(wnetx.resolve_proxy(None, None) == DEFAULT_PX,
      '没给 url 时退默认动作而非抛错',
      repr(wnetx.resolve_proxy(None, None)))

# 归一结果再喂回来 (同一 URL) 必须等价 —— 引擎把上游归一出的 None 原样回传
# (bing 就这么干) 时, 不该被当成"没表态"再问一次规则表而翻案。
for _u in (DEFAULT_URL, DIRECT_URL):
    _once = wnetx.resolve_proxy(None, _u)
    _twice = wnetx.resolve_proxy(_once or 'direct', _u)
    check(_once == _twice, f'归一结果回喂等价 ({_u.split("/")[2]})',
          f'{_once!r} -> {_twice!r}')

# --- 6. SOCKS5 的 DNS 归属: socks5:// 各库都读成本地解析, 等于代理白配 ----
# curl 与 requests 都把 `socks5://` 当"本机解析域名、只把 IP 交给代理",
# `socks5h://` 才是远端解析。国内本机 DNS 常被污染 —— 用户写 socks5:// 时
# 看着走了代理, 实际 DNS 仍走本地。归一层统一升级, 各通道一起到位。
_socks_url = 'https://www.example.org/x'
check(wnetx.resolve_proxy('socks5://127.0.0.1:1080', _socks_url) ==
      'socks5h://127.0.0.1:1080',
      'socks5:// 归一成 socks5h:// (远端解析)',
      repr(wnetx.resolve_proxy('socks5://127.0.0.1:1080', _socks_url)))
check(wnetx.resolve_proxy('socks5h://127.0.0.1:1080', _socks_url) ==
      'socks5h://127.0.0.1:1080',
      'socks5h:// 已经是远端解析, 不重复改写',
      repr(wnetx.resolve_proxy('socks5h://127.0.0.1:1080', _socks_url)))
check(wnetx.resolve_proxy('http://127.0.0.1:2080', _socks_url) ==
      'http://127.0.0.1:2080',
      'http:// 代理不被误改')

print('\n' + ('ALL PASS' if not fails else f'FAILED: {fails}'))
sys.exit(1 if fails else 0)
