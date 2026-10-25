"""传输层探活: 轻量探测代理/直连连通性 (rank 自动降级用)

探活本身也是一次出网, 所以走 net.transport 那条主通道 (指纹 + 线路 + 证书都在
那层), 不另开一套只有它走的实现 —— 代理里的 `user@host` 由那一层补保险库密码,
否则带认证的代理会被误判成"不可用", 上层据此放弃重试, 排查方向完全指不到真实
原因 (凭据缺失)。
"""
from webtool.net import netx


def head_probe(proxy=None, timeout=6):
    """经 proxy HEAD https://www.bing.com/generate_204,
    拿到任何 HTTP 状态码即视为连通。失败抛异常/返回 False。"""
    from webtool.net import transport
    r = transport.request('HEAD', 'https://www.bing.com/generate_204',
                          kind='api', proxy=proxy, timeout=timeout,
                          allow_redirects=False)
    return r.status_code < 600

_proxy_alive = {}

def proxy_ok(proxy, timeout=6):
    """探活 + 进程内缓存: HEAD https://www.bing.com/generate_204 经代理可达即可用。

    上层 (rank/zen/fetch 等) 统一走这里 —— 探活属于传输层,
    不该让某个业务模块当公共依赖被反向引用。
    """
    if not proxy:
        return False
    # 缓存键用归一后的形态: 'user@host' 与 'user:明文@host' 指向同一条代理,
    # 分开缓存会让同一条代理被探两次 (后者还必然失败, 因为密码没补)
    try:
        # 缓存键取"这次探活实际会走的线路": 把探活 URL 交给规则表, 与 head_probe
        # 的决策同源 (留空 url 会退默认动作, 键就和真正用的线路对不上了)
        px = netx.resolve_proxy(proxy, 'https://www.bing.com/generate_204')
    except Exception:
        px = proxy
    key = px or proxy
    if key in _proxy_alive:
        return _proxy_alive[key]
    ok = False
    try:
        ok = bool(head_probe(px, timeout))
    except Exception:
        ok = False
    _proxy_alive[key] = ok
    return ok