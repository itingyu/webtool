"""proxyhelper —— 全项目**唯一**的代理决策入口

请求从十几条通道发出去 (curl_cffi / urllib / requests / 各引擎), 都要回答同一个
问题: **这次请求该走哪条代理?** 走哪条线由配置和路由表一次决定, 失败就是失败 ——
不 failover、不「代理失败就退直连」(目标本来就只允许代理出网时, 那是最不能退的
时候), 报错指向真正原因, 不靠换线路把问题掩盖掉。

## 唯一职责

    proxyhelper.resolve(proxy, url)  →  最终代理 URL 或 None

    proxy=None / 'direct'            → None          (强制直连)
    proxy='auto'                     → 问路由表
    proxy='http://u@h:8080'          → 补保险库密码
    proxy 未给 (None)                → 'auto'         (缺省问路由表)

想临时直连用 `webtool --no-proxy`, 不要在调用点写 `proxy=None` 硬编码 —— 那是把
用户的选择写死在代码里。
"""

from webtool.net import netx


def resolve(proxy, url=None, default='auto'):
    """归一这次请求的代理。返回代理 URL 字符串或 None (直连)。

    default='auto' 表示"调用方没表态"时按规则表分流, 而不是直连 —— 直连应该是
    显式选择 (`--no-proxy`), 不是缺省值。
    """
    if proxy is None:
        proxy = default
    return netx.resolve_proxy(proxy, url)


def for_url(url, proxy=None):
    """只按 URL 决定 (调用方没有代理偏好时用这个)"""
    return resolve(proxy, url, default='auto')


__all__ = ['resolve', 'for_url']