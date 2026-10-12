"""传输层探活: 轻量探测代理/直连连通性 (rank 自动降级用)"""


def head_probe(proxy=None, timeout=6):
    """经 proxy (None=直连) HEAD https://www.bing.com/generate_204,
    拿到任何 HTTP 状态码即视为连通。失败抛异常/返回 False。"""
    from curl_cffi import requests as _cr
    r = _cr.head('https://www.bing.com/generate_204',
                 impersonate='chrome131', proxy=proxy or None,
                 timeout=timeout, allow_redirects=False)
    return r.status_code < 600


_proxy_alive = {}


def proxy_ok(proxy, timeout=6):
    """探活 + 进程内缓存: HEAD https://www.bing.com/generate_204 经代理可达即可用。

    上层 (rank/zen/fetch 等) 统一走这里 —— 探活属于传输层,
    不该让某个业务模块当公共依赖被反向引用。
    """
    if not proxy:
        return False
    if proxy in _proxy_alive:
        return _proxy_alive[proxy]
    ok = False
    try:
        ok = bool(head_probe(proxy, timeout))
    except Exception:
        ok = False
    _proxy_alive[proxy] = ok
    return ok
