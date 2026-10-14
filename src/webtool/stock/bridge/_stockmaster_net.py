"""stock-master 的两处出网接入统一规则表

`stock_master/scripts/` 里有且只有两个出网点 (`clients._http` 与
`short_tool._get`), 都是裸 `urllib.request.urlopen` —— 不带代理、不带证书
策略、不看路由表。用户配的"境内直连、境外走代理"对这条通道无效。

这里不改动 vendor 目录 (那是同步来的), 而是提供一个 opener 工厂, 由
`bridge/master.py` 在包化时注入; vendor 侧只需改这两行调用 `get_opener()`。
之所以能动 vendor: 它已在 webtool 仓内、由 `bridge/README.md` 记录同步口径,
且这两处是纯传输细节, 不属于 stock-master 的业务语义。
"""
from __future__ import annotations

import ssl
import urllib.request

from webtool.net import netx
from webtool.core import tls

_opener: urllib.request.OpenerDirector | None = None
_opener_key: tuple | None = None


def get_opener(url: str) -> urllib.request.OpenerDirector:
    """按规则表为该 URL 建 opener —— 有代理就挂 ProxyHandler, 直连就不挂

    两条都得显式给字典:
    - 直连给 `{}` —— 否则 `http_proxy` 环境变量仍生效, "规则表说直连"其实没直连;
    - 有代理时给 `{'http': px, 'https': px}` —— 传 `None` 会退回读环境变量,
      环境里没有代理就变直连, 规则表等于没生效。

    证书策略同 netx: `tls.policy` 返回 False (跳过校验) 或 CA 路径; urllib
    只认布尔, CA 的活交给 `ssl_context` 自己取 policy。
    """
    global _opener, _opener_key
    px = netx.resolve_proxy('auto', url)
    key = (px, tls.policy(url, None))
    if _opener is not None and _opener_key == key:
        return _opener

    handlers = []
    # 直连时也要装空的 ProxyHandler: 否则环境变量里的 http_proxy 生效
    handlers.append(urllib.request.ProxyHandler({} if not px else {'http': px, 'https': px}))
    ver = tls.policy(url, None)
    if ver is False:
        ctx = ssl._create_unverified_context()
    else:
        ctx = ssl.create_default_context(cafile=ver if isinstance(ver, str) else None)
    handlers.append(urllib.request.HTTPSHandler(context=ctx))
    _opener = urllib.request.build_opener(*handlers)
    _opener_key = key
    return _opener


def reset() -> None:
    """规则表热改后丢弃缓存的 opener"""
    global _opener, _opener_key
    _opener = _opener_key = None