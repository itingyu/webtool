# -*- coding: utf-8 -*-
"""传输层探活: 轻量探测代理/直连连通性 (rank 自动降级用)

探活请求同样带浏览器指纹 (chrome131 impersonate), 不裸奔 —
出口网络/代理侧也会记录裸 HEAD 流量特征。
"""


def head_probe(proxy=None, timeout=6):
    """经 proxy (None=直连) HEAD https://www.bing.com/generate_204,
    拿到任何 HTTP 状态码即视为连通。失败抛异常/返回 False。"""
    from curl_cffi import requests as _cr
    r = _cr.head('https://www.bing.com/generate_204',
                 impersonate='chrome131', proxy=proxy or None,
                 timeout=timeout, allow_redirects=False)
    return r.status_code < 600
