"""让 `requests.Session` 的每个请求都按规则表现算代理

## 为什么不改 61 个调用点

`sources/` 下十一个源模块里有 61 处 `self._std.get(url, ...)`。逐个加
`proxies=` 能生效, 但那是机械改动 —— 漏一处就是一个源绕过规则表, 而且下次
有人加新方法又得记得传。**在传输层注入**只需改一个地方, 且对新方法自动生效。

`HTTPAdapter.send(request, ..., proxies=...)` 的 `proxies` 正是 urllib3 选
连接池的依据, 在这里覆盖就能决定这条请求走哪条代理。

## 为什么不能写进 session.proxies

`session.proxies` 是 session 级的, 一旦设定, 该 session 的**所有**请求共用同
一条代理。而一个 `APIClient` 同时打十余个域名 (东财/雪球/新浪/同花顺/巨潮…),
路由表的价值恰恰在于逐域名决策 ("境内直连、境外走代理")。绑在 session 上就
退化成"整个股票模块一条代理", 等于把规则表架空。

所以: session 保持干净, 代理在 `send` 里按 `request.url` 现算。

## curl_cffi 侧

雪球/腾讯 K 线走 `curl_cffi` 会话 (`impersonate` 指纹)。它的 `proxies=` 也是
请求级参数, 由 `_routing.cffi_proxies()` 提供 —— 见 `_base.py` 的
`_xueqiu_session`。
"""
from __future__ import annotations

from requests.adapters import HTTPAdapter

from webtool.stock.bridge.sources import _routing


class RoutedAdapter(HTTPAdapter):
    """按目标 URL 现算代理的 HTTPAdapter

    `override` = None/'auto' 时问规则表; 'direct' 强制直连; URL 强制走那条。
    与 `SourceBase.__init__` 收到的 `proxy` 参数同义 —— 适配器拿不到 session,
    所以由 `SourceBase` 在构造时传进来。
    """

    def __init__(self, *a, override=None, **kw):
        super().__init__(*a, **kw)
        self._override = override

    def send(self, request, stream=False, timeout=None, verify=True,
             cert=None, proxies=None):
        # 调用点若已显式给了 proxies, 以调用点为准 (逃生口: 单点定死一条)
        if not proxies:
            proxies = _routing.proxies_for(request.url, self._override)
        return super().send(request, stream=stream, timeout=timeout,
                            verify=verify, cert=cert, proxies=proxies)


def mount(session, *, override=None, max_retries=None, pool_maxsize=20):
    """把带路由的适配器装到 http/https 两个 scheme 上

    `max_retries` 保留 urllib3 Retry (解决间歇性 RemoteDisconnected):
    代理换路后重试依然有意义, 但只对幂等 GET 重试, 不放大写操作的副作用。
    """
    if max_retries is None:
        from urllib3.util.retry import Retry
        max_retries = Retry(
            total=3,
            backoff_factor=0.3,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=['GET'],
            raise_on_status=False,
        )
    ad = RoutedAdapter(max_retries=max_retries, pool_maxsize=pool_maxsize,
                       override=override)
    session.mount('https://', ad)
    session.mount('http://', ad)
    return ad