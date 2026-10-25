# -*- coding: utf-8 -*-
"""代理可达性兜底单测 (纯本地, 不联网)

覆盖:
  1. reach.usable: 端口没监听 → False (改走直连); 端口在听 → True
  2. 探测结论有缓存: 同一 host:port 一个窗口只探一次
  3. 判不出来就不猜 (没写端口 / 解析不出的串)
  4. proxy_fallback=off → 不兜底, 照配置走
  5. netx.resolve_proxy: 代理没起 → None (直连); 在听 → 原样返回

跑法: python3 tests/test_proxy_reach.py
"""
import json
import os
import socket
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 配置落到临时目录, 不碰真实 ~/.webtool
_TMP = tempfile.mkdtemp(prefix='wt-reach-')
os.environ['HOME'] = _TMP
os.environ['WEBTOOL_DIR'] = os.path.join(_TMP, '.webtool')

fails = []


def check(cond, msg):
    print(('PASS' if cond else 'FAIL') + ' ' + msg)
    if not cond:
        fails.append(msg)


from webtool.net.proxy import reach
from webtool.net.proxy.store import CONFIG_PATH


def _free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _write_cfg(value):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump({'proxy_fallback': value}, f)


# ── 1. 默认 on: 代理没起来就改走直连 ──────────────────────────────
dead_port = _free_port()
check(reach.enabled() is True, '默认 proxy_fallback=on')
check(reach.usable(f'http://127.0.0.1:{dead_port}') is False,
      '代理端口没监听 → False (调用方改走直连)')

srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(('127.0.0.1', 0))
srv.listen(1)
live_port = srv.getsockname()[1]
check(reach.usable(f'http://127.0.0.1:{live_port}') is True,
      '代理端口在听 → True (照配置走代理)')

# ── 2. 缓存: 一个窗口只探一次 ────────────────────────────────────
probes = []
_real_connect = reach._connect


def _spy(host, port):
    probes.append((host, port))
    return False


reach._connect = _spy
reach.reset()
for _ in range(3):
    reach.usable('http://127.0.0.1:1')
reach._connect = _real_connect
check(len(probes) == 1, f'同一 host:port 一个窗口只探一次 (实际 {len(probes)})')

# ── 3. 判不出来就不猜 (宁可不兜底, 别把用户的代理绕过去) ──────────
reach.reset()
check(reach.usable('http://127.0.0.1') is True, '没写端口 → 不猜, 照配置走')
check(reach.usable('这不是代理') is True, '解析不出 host:port → 不猜, 照配置走')

# ── 4. proxy_fallback=off → 不兜底 ───────────────────────────────
_write_cfg('off')
check(reach.enabled() is False, 'proxy_fallback=off 生效')
reach.reset()
check(reach.usable(f'http://127.0.0.1:{dead_port}') is True,
      'off 时端口没监听也照配置走 (报错交给调用方)')

# ── 5. netx 归一点 (全项目唯一的代理决策出口) ────────────────────
_write_cfg('on')
reach.reset()
check(reach.enabled() is True, 'proxy_fallback 改回 on 生效')

from webtool.net import netx              # noqa: E402

_TARGET = 'https://example.com'


def _write_rules(proxy_url):
    with open(os.path.join(os.environ['WEBTOOL_DIR'], 'rules.json'), 'w',
              encoding='utf-8') as f:
        json.dump({'default': 'proxy:default',
                   'proxies': {'default': proxy_url}, 'rules': []}, f)


_write_rules(f'http://127.0.0.1:{dead_port}')
reach.reset()
check(netx.resolve_proxy(None, _TARGET) is None,
      '规则表定的代理没起 → None (直连)')

_write_rules(f'http://127.0.0.1:{live_port}')
reach.reset()
check(netx.resolve_proxy(None, _TARGET) == f'http://127.0.0.1:{live_port}',
      '规则表定的代理在听 → 原样返回')

# 显式传进来的线路不吃这条兜底: 探不通仍照配置走, 报错交给底层
check(netx.resolve_proxy(f'http://127.0.0.1:{dead_port}', _TARGET)
      == f'http://127.0.0.1:{dead_port}',
      '显式 --proxy 不受兜底影响 (显式优先)')

srv.close()

print()
if fails:
    print(f'{len(fails)} 项失败:')
    for m in fails:
        print('  - ' + m)
    sys.exit(1)
print('ALL PASS')
