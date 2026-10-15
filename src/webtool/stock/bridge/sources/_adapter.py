"""让 `requests.Session` 的每个请求都按规则表现算代理

## 代理在传输层注入, 不改 61 处调用点

`sources/` 下十一个源模块里有 61 处 `self._std.get(url, ...)`, 逐个加 `proxies=`
是机械改动 —— 漏一处就是一个源绕过规则表, 下次加新方法还得记得传。
`HTTPAdapter.send(request, ..., proxies=...)` 的 `proxies` 正是 urllib3 选连接池
的依据, 在这里覆盖只需改一个地方, 且对新方法自动生效。

## 不能写进 session.proxies

`session.proxies` 是 session 级的, 一设定则该 session 的**所有**请求共用同一条
代理。而一个 `APIClient` 同时打十余个域名 (东财/雪球/新浪/同花顺/巨潮…), 路由表
的价值恰在逐域名决策 ("境内直连、境外走代理")。绑在 session 上就退化成"整个股票
模块一条代理", 等于把规则表架空。

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
        # 默认头也在这里补: 61 个调用点大多只给 Referer, 裸 python-requests
        # 指纹会被反爬站直接 403 (同花顺 data 子域就是)。调用点自己设了 UA
        # 就不动 —— 只有缺 UA 或还是 python-* 默认指纹时才替换。
        ua = request.headers.get('User-Agent') or ''
        if not ua or ua.startswith(('python-requests', 'python-urllib')):
            try:
                for k, v in (_routing.headers_for(request.url) or {}).items():
                    if k == 'User-Agent' or not request.headers.get(k):
                        request.headers[k] = v
            except Exception:          # noqa: BLE001
                pass                   # 取指纹失败不能让请求本身挂掉
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