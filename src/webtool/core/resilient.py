"""fetch 主获取通道: transport 浏览器指纹, cffi 全挂时内部落到 urllib。

opener 参数保留兼容旧调用, 实际不再使用。
"""
from webtool.net import transport
from webtool.net import proxyhelper


def fetch(url, proxy=None, timeout=15, headers=None, opener=None,
          profile=None, raw=False, max_bytes=None):
    """返回 (text, status, via); raw=True 时返回 (bytes, status, via, headers)

    raw 给"目标可能根本不是网页"的场景用 (fetch 判类型/存图片视频压缩包):
    不解码、不降级, 拿到响应头和原始字节就够。
    via: 'proxy' | 'direct' | 'cffi' | 'urllib'

    **单线路, 不 failover**。走哪条线由 proxyhelper 依据配置 + 路由表一次决定,
    请求失败就报错 —— 不再"代理失败退直连重试"。理由: 失败后退直连会掩盖真实
    原因 (代理挂了 → 目标拒绝/超时, 报出来的是后者), 而且对"只允许代理出网"的
    目标, 退直连只是换一种错法。

    - profile: 传输指纹档案名 (transport.PROFILES 键, 如 'chrome131_android'),
      None 时由 transport 自选桌面档案
    """
    p = proxyhelper.resolve(proxy, url)
    prof = profile if (isinstance(profile, str) and profile in transport.PROFILES) else None
    if raw:
        kw = {} if max_bytes is None else {'max_bytes': max_bytes}
        return transport.get(url, kind='nav', proxy=p, timeout=timeout,
                             headers=headers, profile=prof, raw=True, **kw)
    text, status, via = transport.get(
        url, kind='nav', proxy=p, timeout=timeout,
        headers=headers, profile=prof)
    return text, status, via
