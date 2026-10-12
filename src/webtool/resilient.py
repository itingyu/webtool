"""fetch 主获取通道: transport 浏览器指纹, cffi 全挂时内部落到 urllib。

opener 参数保留兼容旧调用, 实际不再使用。
"""
from webtool import transport


def fetch(url, proxy=None, timeout=15, headers=None, opener=None,
          fallback_direct=True, profile=None):
    """返回 (text, status, via)  via: 'proxy' | 'direct' | 'cffi' | 'urllib'

    - 配置了代理: 走 transport(代理), 失败/被拦再降级直连
    - fallback_direct=False 时不做互换 (google 等代理专用通道)
    - profile: 传输指纹档案名 (transport.PROFILES 键, 如 'chrome131_android'),
      None 时由 transport 自选桌面档案
    """
    attempts = []
    order = []
    if proxy and proxy != 'direct':
        order = [(proxy, 'proxy'), (None, 'direct')] if fallback_direct \
            else [(proxy, 'proxy')]
    else:
        order = [(None, 'direct')]

    prof = profile if (isinstance(profile, str) and profile in transport.PROFILES) else None
    last_err = None
    for p, tag in order:
        try:
            text, status, via = transport.get(
                url, kind='nav', proxy=p, timeout=timeout,
                headers=headers, allow_fallback=False, profile=prof)
            if status in (403, 429, 500, 502, 503, 504) and tag == 'proxy' \
                    and fallback_direct and len(order) > 1:
                attempts.append(f'{tag}:HTTP{status}')
                last_err = f'{tag} HTTP {status}'
                continue
            return text, status, tag
        except Exception as e:
            attempts.append(f'{tag}:{type(e).__name__}')
            last_err = f'{tag}: {e}'
            continue
    raise RuntimeError(f'{url} failed [{", ".join(attempts)}] last={last_err}')
