"""数据源出网策略 —— 代理/证书/UA 全部由 `netx` 的规则表决定

## 为什么数据源层要接规则表

`requests.Session()` 与 `curl_cffi` 会话若直接出网, 代理、证书策略、
`proxy_auth` 保险库一律不生效 —— 用户在 `~/.webtool/config.json` 写的路由规则
(境内直连/境外走代理) 就管不到这一百五十多个方法。规则表必须覆盖全部出口,
所以这层的会话统一挂适配器。

## 怎么接的

策略决策全部委托 `netx` (`resolve_proxy` / `tls.policy` / `default_headers`),
本模块只做一件事: **按目标 URL 把决策结果套到具体会话上**。

关键点是代理**不能绑在 session 上**。`requests` 支持请求级 `proxies=`, 所以
`SourceBase._std` 一份 session 就够, 每次请求现算:

    self._std = requests.Session()          # 无代理, 干净
    ...
    r = self._std.get(url, proxies=netx.pxies_for(url))   # 每请求按域名算

若把代理写进 `session.proxies`, 一条 session 就只能服务一个出口, 而
数据源层同时打十余个域名, 路由表就失去了逐域名决策的能力。

`curl_cffi` 会话 (雪球 TLS 指纹) 同理 —— `proxies=` 是请求级参数。

## 覆盖方式

优先级从高到低:

1. 构造参数 `APIClient(proxy=...)` —— 一次调用内所有域统一走这条
2. `'direct'` —— 强制直连, 无视路由表 (只有显式要求才会出现)
3. 未指定 / `'auto'` (默认) —— 逐 URL 问 `~/.webtool/config.json` 的规则表

选线**只由 config.json + rules.json 决定**: 代码里不写死线路, 也不留环境变量旁路
(曾经有过 STOCK_DIRECT_DOMAINS 直连名单和 STOCK_PROXY 兜底, 都是同一件事的第二个
决策源 —— 它们会与配置文件打架, 且用户改配置改不动, 已删)。要临时直连用
`webtool --no-proxy`。

## 默认 UA

`netx.default_headers` 按站点补浏览器指纹档案, 各源不再各写一份 UA。
个别源有硬性 UA 要求时在方法内显式传 `headers=`, 优先级高于默认档案。
"""
from __future__ import annotations


from webtool.net import netx
from webtool.core import tls

# 进程内缓存: 同一域名反复查表会重复读配置 + 解析规则
_PROXY_CACHE: dict[str, str | None] = {}

# 不走"端点自带线路"的名单: 线路只由构造参数 override 与 rules.json 决定,
# 多一个决策源会与规则表打架, 还会静默吃掉构造参数的显式指定。要固定某站
# 直连就写进 ~/.webtool/rules.json —— 那份文件用户看得见也改得动。


def resolve(url: str, override: str | None = None) -> str | None:
    """URL → 该走哪条代理。返回 None = 直连。

    调 `netx.resolve_proxy` (它内部问规则表并补保险库密码), 结果按域名缓存 ——
    路由表是静态配置, 一次进程内不会变, 但 `proxy_auth` 可能被用户中途改,
    所以缓存的是「域名 → 命中哪条命名代理」这一步之外的内容: 这里缓存最终
    结果, 由 `netx.resolve_proxy` 负责密码补全的时机。
    """
    mode = 'auto' if override is None else override     # 没表态就跟配置走
    if mode == 'direct':
        return None
    host = url.split('/')[2].lower() if '://' in url else url.lower()
    if mode != 'auto':
        return netx.resolve_proxy(mode, url)
    if host not in _PROXY_CACHE:
        _PROXY_CACHE[host] = netx.resolve_proxy('auto', url)
    return _PROXY_CACHE[host]


def proxies_for(url: str, override: str | None = None) -> dict | None:
    """给 requests / curl_cffi 的请求级 `proxies=`。直连时返回 None。"""
    px = resolve(url, override)
    if not px:
        return None
    if 'socks5://' in px and 'socks5h://' not in px:
        # socks5 会被 requests 本地解析 DNS, 代理服务器根本用不上
        px = px.replace('socks5://', 'socks5h://', 1)
    return {'http': px, 'https': px}


def verify_for(url: str, verify=None):
    """证书策略 → requests/curl_cffi 认的形态 (False 或 CA 路径)。"""
    return tls.policy(url, verify)


def headers_for(url: str, headers=None, referer=None, kind='nav') -> dict:
    """默认 UA/Accept-Language: 走统一浏览器指纹档案, 不各源各写一份。"""
    return netx.default_headers(url, headers, kind=kind, referer=referer)


def reset_cache() -> None:
    """配置热改后清缓存 (CLI 管理命令改完代理立即生效)。"""
    _PROXY_CACHE.clear()


class RoutedCffiSession:
    """curl_cffi 会话 —— 每个请求按目标 URL 现算代理

    与 `RoutedAdapter` 同一思路, 只是挂在 curl_cffi 上: 雪球/腾讯 K 线要
    `impersonate` 的 TLS 指纹, 走不了 requests, 但 `proxies=` 同样是请求级
    参数, 所以规则表照样管得到。

    用 `__getattr__` 透传其余方法与属性 (post/put/close/cookies…), 只覆盖
    get/post —— 这两个是数据源实际用到的出网方法。
    """

    def __init__(self, *a, override=None, **kw):
        from curl_cffi import requests as cr
        kw.setdefault('trust_env', False)   # 环境变量不参与选线
        self._s = cr.Session(*a, **kw)
        self._override = override

    def get(self, url, **kw):
        kw.setdefault('proxies', _routing_proxies(url, self._override))
        return self._s.get(url, **kw)

    def post(self, url, **kw):
        kw.setdefault('proxies', _routing_proxies(url, self._override))
        return self._s.post(url, **kw)

    def __getattr__(self, name):
        return getattr(self._s, name)


def _routing_proxies(url, override):
    """`proxies_for` 在本模块内的短别名 (类定义早于它, 运行时解析)"""
    return proxies_for(url, override)