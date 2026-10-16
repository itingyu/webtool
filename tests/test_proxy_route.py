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
               'rules': [{'match': {'domain': ['*.cn']}, 'action': 'direct'}]}, f)

from webtool.net import http as whttp
from webtool.net import proxy as wproxy

fails = []


def check(name, cond, detail=''):
    if cond:
        print(f'PASS {name}')
    else:
        print(f'FAIL {name} {detail}')
        fails.append(name)


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
    check('no_proxy=* 时显式代理仍生效', r.status == 204, r.status)
    check('请求确实交给了代理', any('nothing.invalid' in p
                                    for p in _FakeProxy.seen), _FakeProxy.seen)
except Exception as e:
    check('no_proxy=* 时显式代理仍生效', False, str(e)[:120])

# 直连 opener 仍不该偷偷用环境里的代理 (两条路径不能互相污染)
try:
    op2 = whttp.build_opener('direct')
    try:
        op2.open('http://nothing.invalid/x', timeout=5)
        check('direct 不被环境代理劫持', False, '竟然连通了')
    except Exception:
        check('direct 不被环境代理劫持', True)
except Exception as e:
    check('direct 不被环境代理劫持', False, str(e)[:120])

# --- 2. 死代理 + no_proxy=* 必须 FAIL (曾经报 OK) -----------------------------
port = dead_port()
cfg = wproxy.load_config()
buf_o, buf_e = io.StringIO(), io.StringIO()
with contextlib.redirect_stdout(buf_o), contextlib.redirect_stderr(buf_e):
    rc = wproxy._test(types.SimpleNamespace(
        value=f'http://127.0.0.1:{port}', url=None), cfg)
out = buf_o.getvalue() + buf_e.getvalue()
check('死代理 + no_proxy=* 判 FAIL', rc == 1, f'rc={rc} out={out.strip()[:120]}')
check('FAIL 信息里带上被绕过的代理地址', f'127.0.0.1:{port}' in out, out[:120])

# --- 3. 目标线路与所测代理不一致时要说明 --------------------------------------
buf_o, buf_e = io.StringIO(), io.StringIO()
with contextlib.redirect_stdout(buf_o), contextlib.redirect_stderr(buf_e):
    rc = wproxy._test(types.SimpleNamespace(
        value=proxy_url, url='http://x.cn/robots.txt'), cfg)
out = buf_o.getvalue() + buf_e.getvalue()
check('目标走直连时提示"不是一条线"', '不是一条线' in out, out.strip()[:160])

# --- 4. 线路比较只看 scheme://host:port --------------------------------------
check('线路比较忽略尾斜杠', wproxy._norm_proxy_url('http://h:1/') ==
      wproxy._norm_proxy_url('http://h:1'))
check('裸 host:port 自动补 scheme', wproxy._norm_proxy_url('1.2.3.4:8080') ==
      'http://1.2.3.4:8080')
check('被 default 引用的代理算"在用"', wproxy._proxy_is_used(
    cfg, 'http://127.0.0.1:2080'))
check('没人引用的代理不算"在用"', not wproxy._proxy_is_used(
    cfg, 'http://127.0.0.1:34567'))

srv.shutdown()
print('\n' + ('ALL PASS' if not fails else f'FAILED: {fails}'))
sys.exit(1 if fails else 0)
