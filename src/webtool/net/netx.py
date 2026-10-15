"""统一出网层: 一处决定「这条请求怎么打出去」

已接入的通道都从这里拿策略, 各自不判断代理与证书:


- `stock/bridge/http.py` — `Http(proxy=...)`, 默认 `'auto'` 问路由表
- `core/probe.py` — 探活补保险库密码, 缓存键用归一后的形态
- `core/http.py` / `net/transport.py` — 保留各自实现 (session 预热、指纹降级梯
  本层不重复造), 代理归一改成调 `resolve_proxy`
- 新增出口一律走本层: 自己写 auto 判断或密码补全 = 又造出一条不受路由表约束的链

## 这一层负责什么

只做**决策**, 不碰业务:

1. `proxy='auto'` → 问路由表 (域名/端口/GeoIP/geosite/命名代理)
2. `resolve_auth` 补保险库密码 —— 明文只在这里出现, 不落盘不进日志
3. 证书策略 `tls.policy()` → 每个通道拿同一个决定, 不会出现「curl_cffi 拒了
   urllib 放行」的分裂
4. 默认 UA 走浏览器指纹档案, 禁止裸 Python-urllib 指纹出网

## 怎么用

已接好的通道:

```python
from webtool.net import netx

text, status = netx.get(url)                     # 自动选通道 + 全部策略
text, status = netx.get(url, engine='google')    # 带引擎名 (走反爬/降级梯)
text, status = netx.get(url, proxy='direct')     # 强制直连
text, status = netx.get(url, verify=False)       # 定点豁免该站证书
```

想接新通道, 只要实现 `_run()` 里的分支, 别的地方不用动。
"""
import gzip
import io
import urllib.error
import urllib.request

from webtool.core import tls
from webtool.core.secrets_store import resolve_auth


class NetError(RuntimeError):
    """出网层统一错误 (上层只需认这一个, 不必逐个库去认异常)"""


def resolve_proxy(proxy, url=None):
    """把 proxy 参数归一成「实际代理 URL / None」。

    - `'auto'`  → 问路由表 (需要 url)
    - `None`    → 直连
    - `'direct'`→ 直连 (语义与 auto 不同: 这是调用方显式要求)
    - `<url>`   → 强制走这条, 并补上保险库密码

    这是**唯一**该碰代理的地方: 其他模块拿到的 proxy 一律是已归一、可直接
    交给底层库的值, 不再各自去 resolve_auth / 判断 auto。
    """
    if proxy == 'auto':
        if not url:
            return None
        from webtool.net import rules as _rules
        proxy = _rules.resolve_route(url)
    if not proxy or proxy == 'direct':
        return None
    # 缺密码要立刻说清楚, 不能拿空密码去撞 407 (那报错完全指不到原因)
    return resolve_auth(proxy)


def default_headers(url, headers=None, kind='nav', referer=None):
    """补默认头。反探测优先: UA/Accept-Language 取 transport 的浏览器指纹档案,
    裸 Python-urllib 指纹一律不出网。调用方显式给的头不被覆盖。"""
    h = dict(headers or {})
    if not h.get('User-Agent'):
        try:
            import webtool.net.transport as _t
            p = _t.PROFILES[_t._pick_profile(None)]
            h.setdefault('User-Agent', p['ua'])
            h.setdefault('Accept-Language', _t.LANG_ZH)
        except Exception:
            # 指纹档案不可用不能连带把请求搞挂, 但也不能发空 UA 出去
            h.setdefault('User-Agent',
                         'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                         'AppleWebKit/537.36 (KHTML, like Gecko) '
                         'Chrome/131.0.0.0 Safari/537.36')
    return h


def get(url, *, proxy=None, timeout=15, headers=None, verify=None,
        engine=None, opener=None, max_bytes=8 * 1024 * 1024, session=None,
        kind='nav', referer=None):
    """GET → (text, status)

    通道顺序: curl_cffi 浏览器指纹 → (它崩了) urllib 兜底。证书失败**不重试**,
    直接抛 —— 证书不对就是不对, 重试只会把 1 次失败放大成多次。

    引擎名 (engine) 只影响上层反爬策略, 这里只用于挑选 UA 档案。
    """
    proxy = resolve_proxy(proxy, url)
    ver = tls.policy(url, verify)

    if session is not None:
        # 外部管理的会话 (引擎自带 warmup 流程): 尊重它的代理与证书设置,
        # 只补默认头, 不去改会话本身 —— 那属于引擎自己的预热逻辑
        h = default_headers(url, headers, kind, referer)
        r = session.get(url, headers=h, timeout=timeout,
                        allow_redirects=True)
        return _decode(r.content, r.headers, max_bytes), r.status_code

    try:
        return _get_cffi(url, proxy=proxy, timeout=timeout, headers=headers,
                         ver=ver, engine=engine, max_bytes=max_bytes,
                         kind=kind, referer=referer)
    except tls.TlsError:
        raise                       # 证书硬失败, 不进兜底梯
    except Exception as cffi_err:
        # curl_cffi 不可用/崩溃时退回 urllib。保留原异常, 兜底也失败时报它
        try:
            return _get_urllib(url, proxy=proxy, timeout=timeout,
                               headers=headers, ver=ver, max_bytes=max_bytes,
                               kind=kind, referer=referer, opener=opener)
        except tls.TlsError:
            raise
        except Exception as url_err:
            raise NetError(
                f'GET {url[:120]} 两条通道都失败\n'
                f'  curl_cffi: {type(cffi_err).__name__}: {str(cffi_err)[:160]}\n'
                f'  urllib: {type(url_err).__name__}: {str(url_err)[:160]}'
            ) from url_err


def verify_arg(ver):
    """把 tls.policy 的返回值转成 urllib 那侧认的形态。

    tls.policy 返回 False 或 **CA 路径** (路径是给 curl_cffi/requests 的, 它们
    见 True 就各自去读环境变量, 三通道就可能用三套信任根)。但 urllib 侧
    `ssl_context(url, verify)` 的 verify 只认布尔 —— 把路径塞进去会被当成
    `ssl_verify` 的取值解析, 报 "ssl_verify 只认 on/off"。
    CA 的活交给 ssl_context 自己做 (它能拿到 policy), 这里只回传"要不要验"。
    """
    return ver is not False


def _new_cffi_session():
    """每次请求新建 curl_cffi 会话 (trust_env=False, 线路只认配置文件)

    trust_env 只能在**会话级**设: 模块级 `cr.get()` / `Session.get()` 都不
    接受这个参数, 传了当场 TypeError, 而调用方又会静默回退 urllib —— 指纹
    和线路一起失真, 症状是"结果照样对, 反爬照挡"。同一类坑这是第二次:
    上一次是 `import transport as _t` 写在 `if engine:` 分支里, 不带 engine
    的调用全落 urllib。

    每次新建而不复用: 复用会把 cookie 带到后续请求上 (会话级 jar),
    与 transport 的做法也不一致。反复建会话要付握手成本, 但行为可预期。
    """
    from curl_cffi import requests as cr
    return cr.Session(trust_env=False)


def _get_cffi(url, *, proxy, timeout, headers, ver, engine, max_bytes,
              kind, referer):
    try:
        sess = _new_cffi_session()
    except ImportError as e:
        raise NetError(f'curl_cffi 不可用: {e}') from e
    h = default_headers(url, headers, kind, referer)
    kw = {}
    if proxy:
        kw['proxy'] = proxy
    # cffi 认 CA 路径或 bool, 由 tls.policy 决定 (有 CA 给路径, 无 CA 给 False)
    if ver is not None:
        kw['verify'] = ver
    # 指纹档案两条分支都要用, 必须在 if 外面导入 —— 放进 `if engine:` 里,
    # 不带 engine 的调用 (探活/站点/feed) 会 UnboundLocalError
    import webtool.net.transport as _t
    prof = _t.PROFILES[_t._pick_profile(engine)]
    try:
        r = sess.get(url, headers=h, timeout=timeout,
                     impersonate=prof['impersonate'], **kw)
    except Exception as e:
        if tls.is_tls_error(e):
            raise tls.TlsError(_tls_msg(url, e)) from e
        raise
    return _decode(r.content, r.headers, max_bytes), r.status_code


def _get_urllib(url, *, proxy, timeout, headers, ver, max_bytes, kind,
                referer, opener=None):
    from webtool.core import http as _http
    h = default_headers(url, headers, kind, referer)
    req = urllib.request.Request(url, headers=h)
    op = opener or _http.build_opener(proxy, url=url, verify=verify_arg(ver))
    try:
        r = op.open(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        # 4xx/5xx 也把响应体读出来: 上层 (captcha/google) 要状态码+特征做识别
        try:
            text = e.read(max_bytes).decode('utf-8', errors='replace')
        except Exception:
            text = ''
        return text, e.code
    except Exception as e:
        if tls.is_tls_error(e):
            raise tls.TlsError(_tls_msg(url, e)) from e
        raise
    return _decode(r.read(max_bytes), r.headers, max_bytes), r.status


def _tls_msg(url, e):
    host = url.split('/')[2] if '://' in url else url
    kind, fix = tls.cert_advice(e, host)
    head = f'{url[:120]} 证书校验失败'
    if kind:
        head += f' ({kind})'
    return (f'{head}: {str(e)[:160]}\n'
            f'  修法 → {fix or ("自签/过期证书站: webtool config set verify_hosts " + host)}')


def _decode(data, headers, max_bytes):
    """bytes → text。gzip 解码 + charset 嗅探, 与旧 urllib 通道行为一致。"""
    if not isinstance(data, (bytes, bytearray)):
        return data
    data = bytes(data)
    if len(data) > max_bytes:
        data = data[:max_bytes]
    if headers and headers.get('Content-Encoding') == 'gzip':
        try:
            data = gzip.GzipFile(fileobj=io.BytesIO(data)).read()
        except Exception:
            pass
    charset = 'utf-8'
    ct = (headers.get('Content-Type', '') if headers else '')
    m = None
    if 'charset=' in ct:
        m = ct.split('charset=')[-1].split(';')[0].strip()
    if not m:
        m = _sniff_charset(data)
    if m:
        charset = m.lower()
    try:
        return data.decode(charset, errors='replace')
    except LookupError:
        return data.decode('utf-8', errors='replace')


def _sniff_charset(data):
    import re
    mm = re.search(rb'charset=["\']?([\w-]+)', data[:2048], re.I)
    if mm:
        return mm.group(1).decode('ascii', 'ignore')
    try:
        data.decode('utf-8')
        return 'utf-8'
    except UnicodeDecodeError:
        return None