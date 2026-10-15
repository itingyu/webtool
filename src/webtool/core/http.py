"""HTTP 底层: urllib 兜底通道 (transport 的降级备胎) + 老式 socks 代理。

http_get 未显式给 UA 时自动套 transport 指纹档案的浏览器 UA,
禁止裸 Python-urllib 指纹出网。

证书校验走 core.tls 的全局策略 (ssl_verify / ca_bundle / verify_hosts),
本模块不自建 SSLContext, 三条通道同源。
"""
import gzip
import io
import urllib.request
import urllib.error

from webtool.core import tls
from webtool.core.secrets_store import resolve_auth


def build_opener(proxy=None, cookie_jar=None, url=None, verify=None,
                 ssl_context=None):
    """建 opener。证书策略默认取 tls.ssl_context(), url/verify 只影响该 opener。

    显式传 ssl_context 则原样使用 (调用方自管证书时)。

    proxy 里带 `user@host` 而密码在保险库时, 这里补上明文密码再交给 urllib ——
    明文只在内存里, 不落盘也不进日志 (出网前的脱敏在 secrets_store)。

    proxy='auto' 交给 netx 问路由表 (域名/IP/端口规则、命名代理)。此前这里
    只做 resolve_auth (补密码), 不认 'auto', 于是 'auto' 会被当成代理主机名
    装进 ProxyHandler —— 每个请求都 DNS 失败, 而且报的是"无法解析 auto",
    完全指不到真实原因。走 build_opener 的通道 (zen / sogou / gnews /
    mcpclient) 都会中招, 所以归一放在这里而不是各调用方。
    url 给了才能问规则; 没给则无法判断 (预热/探活场景), 按直连处理。
    """
    if proxy == 'auto':
        from webtool.net import netx as _netx
        proxy = _netx.resolve_proxy('auto', url) if url else None
    handlers = []
    if proxy and proxy != 'direct':
        proxy = resolve_auth(proxy)
    # 'direct' 是"强制直连"的约定语义 (与 transport/netx 一致), 不是主机名 ——
    # 当代理装进 ProxyHandler 会让每个请求去解析主机 "direct"。
    if proxy and proxy != 'direct':
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
    else:
        # 直连也要传一个**空** ProxyHandler。build_opener 见到同类的处理器就
        # 不加默认的那个, 而默认 ProxyHandler 会读 http_proxy/https_proxy ——
        # 不给的话, 规则表判定直连的主机被环境变量悄悄送去代理, 配置文件说了
        # 不算 (容器里 HTTPS_PROXY 是常见配置)。空字典自身没有 *_open 方法,
        # 装代理和读环境变量两件事都因此不发生。
        handlers.append(urllib.request.ProxyHandler({}))
    if cookie_jar is not None:
        handlers.append(urllib.request.HTTPCookieProcessor(cookie_jar))
    if ssl_context is None:
        # 配置非法 (ca_bundle 路径不存在) 要当场炸, 不能默默降级成不校验
        ssl_context = tls.ssl_context(url, verify)
    handlers.append(urllib.request.HTTPSHandler(context=ssl_context))
    return urllib.request.build_opener(*handlers)


def _parse_auth(auth):
    if not auth or ':' not in auth:
        return {}
    # resolve_auth 拼回 URL 时做了 percent-encode, 这里得解回来
    from urllib.parse import unquote
    user, pwd = auth.split(':', 1)
    return {'username': unquote(user), 'passwd': unquote(pwd)}


def http_get(url, proxy=None, timeout=15, headers=None, opener=None,
             max_bytes=8 * 1024 * 1024, verify=None, raw=False):
    """GET 页面, 返回 (text, status); raw=True 时返回 (bytes, status, headers).

    二进制目标 (图片/视频/压缩包) 要的是原始字节和响应头, 解码成文本就毁了 ——
    raw 走的就是这条路, 不做 charset 猜测、不 decode.

    默认头反探测: UA/Accept-Language 自动取 transport 指纹档案 (调用方
    未给时), 与 curl_cffi 通道同源 — 裸 Python-urllib 指纹一律不出网。

    verify=None 走全局 TLS 策略; 传 True/False 定点覆盖 (自签站点豁免用)。
    传了 opener 则由它自己负责证书策略, verify 不生效。
    proxy='auto' 表示问路由表 (域名/IP/端口/协议/GeoIP 规则)。
    """
    # 代理归一与默认头都交给 netx —— 别处不各自判断 'auto'/补密码
    from webtool.net import netx as _netx
    proxy = _netx.resolve_proxy(proxy, url)
    h = _netx.default_headers(url, headers)
    req = urllib.request.Request(url, headers=h)
    op = opener or build_opener(proxy, url=url, verify=verify)
    try:
        r = op.open(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        # 4xx/5xx 也把响应体读出来: 上层 (captcha/google) 需要状态码+特征做识别
        try:
            data = e.read(max_bytes)
            text = data.decode('utf-8', errors='replace')
        except Exception:
            data, text = b'', ''
        return (data, e.code, dict(e.headers)) if raw else (text, e.code)
    data = r.read(max_bytes)
    if r.headers.get('Content-Encoding') == 'gzip':
        try:
            data = gzip.GzipFile(fileobj=io.BytesIO(data)).read()
        except Exception:
            pass
    if raw:
        return data, r.status, dict(r.headers)
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


def http_open(url, proxy=None, timeout=15, headers=None, opener=None, verify=None):
    """发起请求但不读 body, 返回原始响应对象 (给流式下载用)

    与 http_get 共用同一条代理/证书通道 (build_opener), 不然"网页能取、下载取不了"
    这种分裂迟早出现 —— 代理认证与 CA bundle 只有一处实现。
    """
    op = opener or build_opener(proxy, url=url, verify=verify)
    req = urllib.request.Request(url, headers=headers or {})
    return op.open(req, timeout=timeout)


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
