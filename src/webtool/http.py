# -*- coding: utf-8 -*-
"""HTTP 底层: opener 构建 / 抓取 / gzip / UA"""
import gzip
import io
import random
import urllib.request
import urllib.error

UAS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64; rv:132.0) Gecko/20100101 Firefox/132.0',
]

BASE_HEADERS = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip',
}


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


def http_get(url, proxy=None, timeout=15, headers=None, opener=None, max_bytes=8 * 1024 * 1024):
    """GET 页面, 返回 (text, status). 自动 gzip 解码."""
    h = dict(BASE_HEADERS)
    h['User-Agent'] = random.choice(UAS)
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    op = opener or build_opener(proxy)
    r = op.open(req, timeout=timeout)
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
