# -*- coding: utf-8 -*-
"""HTTP 底层: urllib 兜底通道 (transport 的降级备胎)

主力通道在 transport.py (curl_cffi 浏览器指纹)。本模块仅服务:
1. transport 的 urllib 兜底 (cffi 自身崩溃时)
2. 老式 socks 代理 (pysocks)
不再承担搜索引擎主路径。
"""
import gzip
import io
import urllib.request
import urllib.error


def build_opener(proxy=None, cookie_jar=None):
    handlers = []
    if proxy:
        if proxy.startswith('socks'):
            try:
                import socks  # noqa: F401
            except ImportError:
                raise RuntimeError('socks 代理需要 pysocks: pip install pysocks')
            handlers.append(urllib.request.ProxyHandler({}))  # 禁用环境代理
            import socket
            import socks as _s
            prefix, _, rest = proxy.partition('://')
            auth = ''
            if '@' in rest:
                auth, rest = rest.rsplit('@', 1)
            host, _, port = rest.partition(':')
            _s.set_default_proxy(_s.SOCKS5 if 'socks5' in prefix else _s.SOCKS4,
                                 host, int(port or 1080), True,
                                 **_parse_auth(auth))
            socket.socket = _s.socksocket
        else:
            handlers.append(urllib.request.ProxyHandler(
                {'http': proxy, 'https': proxy}))
    if cookie_jar is not None:
        handlers.append(urllib.request.HTTPCookieProcessor(cookie_jar))
    return urllib.request.build_opener(*handlers)


def _parse_auth(auth):
    if not auth or ':' not in auth:
        return {}
    user, pwd = auth.split(':', 1)
    return {'username': user, 'passwd': pwd}


def http_get(url, proxy=None, timeout=15, headers=None, opener=None,
             max_bytes=8 * 1024 * 1024):
    """GET 页面, 返回 (text, status). 自动 gzip 解码."""
    h = dict(headers or {})
    if not h.get('User-Agent'):
        from .transport import PROFILES
        h['User-Agent'] = PROFILES['chrome131_win']['ua']
    req = urllib.request.Request(url, headers=h)
    op = opener or build_opener(proxy)
    try:
        r = op.open(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        # 4xx/5xx 也把响应体读出来: 上层 (captcha/google) 需要状态码+特征做识别
        try:
            data = e.read(max_bytes)
            text = data.decode('utf-8', errors='replace')
        except Exception:
            text = ''
        return text, e.code
    data = r.read(max_bytes)
    if r.headers.get('Content-Encoding') == 'gzip':
        try:
            data = gzip.GzipFile(fileobj=io.BytesIO(data)).read()
        except Exception:
            pass
    charset = 'utf-8'
    ct = r.headers.get('Content-Type', '')
    m = None
    if 'charset=' in ct:
        m = ct.split('charset=')[-1].split(';')[0].strip()
    if not m:
        m = _sniff_charset(data)
    if m:
        charset = m.lower()
    try:
        text = data.decode(charset, errors='replace')
    except LookupError:
        text = data.decode('utf-8', errors='replace')
    return text, r.status


def _sniff_charset(data):
    head = data[:2048]
    m = None
    import re
    mm = re.search(rb'charset=["\']?([\w-]+)', head, re.I)
    if mm:
        m = mm.group(1).decode('ascii', 'ignore')
    else:
        try:
            data.decode('utf-8')
            m = 'utf-8'
        except UnicodeDecodeError:
            m = None
    return m
