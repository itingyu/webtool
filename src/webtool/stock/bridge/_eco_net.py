"""eco 通道 (akshare/tushare/baostock/efinance) 接入统一规则表

这四个生态库各自在内部建 session —— akshare 有 326 个文件自带网络栈,
改不动也不该改。可行的只有一条: 在调用期间让 `requests` 的每个请求默认
带上规则表算出的代理。库自己传的 proxies 优先 (setdefault 语义),
所以不会覆盖库内有特殊要求的请求。

只在 `eco.call()` 作用域内生效 (context manager), 调用结束自动还原 ——
不让一次 `stock eco` 的策略泄漏到同进程后续的普通抓取。
"""
from __future__ import annotations

import contextlib
import pathlib
from typing import Any, Iterator

_INSTALLED = False


def _install() -> None:
    """给 requests.Session.request 包一层默认代理。幂等。"""
    global _INSTALLED
    if _INSTALLED:
        return
    import requests

    from webtool.net.routing import proxies_for

    orig = requests.sessions.Session.request

    def request(self, method, url, *a, **kw):
        if kw.get('proxies') is None:
            kw['proxies'] = proxies_for(url, 'auto')
        return orig(self, method, url, *a, **kw)

    requests.sessions.Session.request = request
    _INSTALLED = True


@contextlib.contextmanager
def routed() -> Iterator[None]:
    """作用域内让生态库走规则表"""
    _install()
    yield


def probe(lib: str) -> dict[str, Any]:
    """该库是否走 requests —— 走则规则表能管到, 不走要如实说

    网络栈常在子模块里 (akshare 的 `__init__.py` 只做 re-export), 所以
    扫整个包目录而不是只看顶层文件。
    """
    import importlib
    import inspect
    try:
        root = pathlib.Path(inspect.getfile(importlib.import_module(lib))).parent
    except Exception as e:                       # noqa: BLE001
        return {'routed': False, 'err': str(e)[:60]}
    hit = None
    for f in root.rglob('*.py'):
        txt = f.read_text(encoding='utf-8', errors='ignore')
        if 'import requests' in txt or 'from requests' in txt:
            hit = f.name
            break
    return {'routed': hit is not None, 'via': hit}