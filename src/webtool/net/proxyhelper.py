"""proxyhelper —— 全项目**唯一**的代理决策入口

## 为什么要有这一层

请求从十几条通道发出去 (curl_cffi / urllib / requests / 各引擎), 每条都要回答
同一个问题: **这次请求该走哪条代理?** 历史上每条通道各答一次, 于是长出三类
分裂:

1. 有的通道根本不接代理 (`stock/http.py` 曾经一次都没把 proxy 传给 requests)
2. 有的通道把 `auto` 当主机名装进 ProxyHandler (`build_opener` 曾不认识 'auto')
3. 有的通道自己发明重试策略 —— 先直连, 失败了再换代理重试

第 3 类最要命: 它让**同一次请求的线路取决于它先失败在哪**, 行为不可预测; 而且
"代理失败就退直连"往往正是最不能退的时候 —— 目标本来就只允许代理出网。所以现在
**取消一切 failover**: 走哪条线由配置和路由表一次决定, 失败了就是失败了, 报错
指向真正的原因, 不靠换线路把问题掩盖掉。

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

    default='auto' 表示"调用方没表态"时按路由表分流, 而不是直连 —— 直连应该是
    显式选择 (`--no-proxy` / `engine_proxy.<名> direct`), 不是缺省值。
    """
    if proxy is None:
        proxy = default
    return netx.resolve_proxy(proxy, url)


def for_url(url, proxy=None):
    """只按 URL 决定 (调用方没有代理偏好时用这个)"""
    return resolve(proxy, url, default='auto')


__all__ = ['resolve', 'for_url']