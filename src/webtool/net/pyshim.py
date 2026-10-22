"""外部行情库 (akshare / efinance / ...) 经 webtool 传输层出网的 requests 门替

问题: 这类库 99% 的出网是裸 `requests` —— 无 TLS 指纹、无限流、无代理路由,
站点一升级反爬就 `RemoteDisconnected` (akshare 的东财系全中)。逐接口手写
重做不可持续: 1141 个接口每个版本都会漂。

方案:patch **requests.Session.request** 这一个漏斗 —— requests.get/post 与
session.get/post 全部经过它。改道后每个请求:
- 走 RoutedCffiSession (chrome131_win 指纹, TLS 层过反爬)
- 逐 URL 问代理规则表 + 证书策略 (webtool.net.routing, 与数据源同一套)
- 自带最小间隔限流 + 幂等方法自动重试 (GET/HEAD 2 次退避)
- 仍以 requests.Response 形态返回 —— 业务代码零改动

不 patch 的情况: webtool 自己的桥 (sources/_base.py) 有独立传输层。
shim 是显式 opt-in (CLI `pydata` / `install()`), 默认进程不生效。
"""
import base64
import json as _json
import threading
import time
from datetime import timedelta

import requests
import requests.exceptions as _rex
import requests.sessions as _sess

_original_request = _sess.Session.request
_lock = threading.Lock()
_local = threading.local()          # 每线程自己的 curl_cffi 会话 (Session 非线程安全)

# ── 状态 ────────────────────────────────────────────────────────
_installed_at = None                # 用于提示 / 判定
_pace_ms = 120                      # 相邻请求最小间隔 (限流, 0=关)
_pace_until = 0.0                   # 上一请求的放行时刻
_timeout = 15                       # requests 默认 None (无限挂), 这里兜底

_EMOJI_NOTE = ('[shim] requests → webtool 传输层 '
               '(chrome131 指纹/代理路由/限流 {pace}ms)')


def install(timeout: int = 15, pace_ms: int = 120, verbose: bool = False) -> bool:
    """把 requests 的出网漏斗替换成 webtool 传输层 (幂等, 可反复调)"""
    global _installed_at, _pace_ms, _timeout
    with _lock:
        _pace_ms = max(0, pace_ms)
        _timeout = timeout
        if _installed_at is None:
            _sess.Session.request = _shimmed_request
            _installed_at = time.monotonic()
            if verbose:
                print(_EMOJI_NOTE.format(pace=_pace_ms))
        return True


def uninstall() -> None:
    """恢复原生 requests.Session.request"""
    global _installed_at
    with _lock:
        if _installed_at is not None:
            _sess.Session.request = _original_request
            _installed_at = None


def is_active() -> bool:
    return _sess.Session.request is _shimmed_request


def _session():
    """线程私有的指纹会话 (lazy)"""
    s = getattr(_local, 's', None)
    if s is None:
        from webtool.net.routing import RoutedCffiSession
        s = _local.s = RoutedCffiSession(impersonate=None)   # 默认 chrome131_win
    return s


def _pace():
    """相邻请求最小间隔 (域名无关, 进程级; 精度要求不高, 够防突发)"""
    global _pace_until
    d = _pace_ms / 1000.0
    with _lock:
        wait = _pace_until - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _pace_until = time.monotonic() + d


# ── 请求出口 ───────────────────────────────────────────────────
def _shimmed_request(self, method, url,
                     params=None, data=None, headers=None, cookies=None,
                     files=None, auth=None, timeout=None,
                     allow_redirects=True, proxies=None, hooks=None,
                     stream=None, verify=None, cert=None, json=None, **kw):
    if files:
        raise TypeError('webtool requests-shim: 文件上传未支持, 该调用请走原生 requests')
    from webtool.net.tls import policy as _tls_policy
    from webtool.net import routing as _rt

    m = (method or 'GET').upper()
    tmo = timeout
    if isinstance(tmo, (tuple, list)) and tmo:
        tmo = float(tmo[0]) or 8.0
    tmo = float(tmo) if tmo else _timeout

    # 合并 session 级与请求级 headers / cookies (原生 request 漏斗里做的那步)
    # 关键: 先滤掉裸 requests 的身份头 (UA=python-requests 等) —— 顶着这个
    # UA, curl_cffi 的浏览器指纹等于白挂; 然后垫底 webtool 按站点给的
    # 浏览器档案头 (UA/Accept-Language), 库里显式设的头 (Referer 等) 在上、仍赢。
    from webtool.net import routing as _rt2

    def _bot_header(k, v):
        if k.lower() == 'user-agent':
            return 'python-requests' in str(v)
        if k.lower() == 'accept-encoding':
            return str(v).replace(' ', '') in (
                'gzip,deflate', 'gzip,deflate,br', 'gzip', 'identity')
        return False

    h = {k: v for k, v in dict(getattr(self, 'headers', None) or {}).items()
         if not _bot_header(k, v)}
    h = {**_rt2.headers_for(url), **h}
    if headers:
        h.update(headers)

    ck = {}
    try:
        for i, c in enumerate(getattr(self, 'cookies', None) or []):
            ck[c.name] = c.value
    except Exception:                                   # noqa: BLE001
        pass
    if cookies:
        ck.update(cookies if isinstance(cookies, dict) else _jar_to_dict(cookies))

    if auth is not None:
        if isinstance(auth, (tuple, list)) and len(auth) == 2:
            raw = base64.b64encode(f'{auth[0]}:{auth[1]}'.encode()).decode()
            h.setdefault('Authorization', f'Basic {raw}')
        else:
            raise TypeError(f'requests-shim: 暂不支持的 auth 类型 {type(auth).__name__}')

    _pace()

    attempts = 2 if m in ('GET', 'HEAD', 'OPTIONS') else 1
    last = None
    for i in range(attempts):
        try:
            crude = _session()._s.request(
                m, url,
                params=params, data=data, json=json, headers=h,
                cookies=ck or None, timeout=tmo,
                allow_redirects=allow_redirects,
                proxies=_rt.proxies_for(url, 'auto') or None,
                verify=_tls_policy(url, verify),
            )
            return _to_requests_response(crude)
        except Exception as e:                          # noqa: BLE001
            last = e
            if i + 1 < attempts:
                time.sleep(0.8 * (i + 1))
                _pace()
    # 网络层错误 → requests 家族 (业务里 except requests.exceptions.* 能接住);
    # 其余异常 (KeyError/ValueError 这些业务态) 原样抛, 包一层只会毁调试。
    try:
        from curl_cffi.curl import CurlError
    except ImportError:                                 # noqa: F401
        CurlError = ()
    if isinstance(last, _rex.RequestException):
        raise last
    if isinstance(last, CurlError):
        if 'timed out' in str(last) or getattr(last, 'code', 0) == 28:
            raise _rex.Timeout(f'requests-shim: {last}') from last
        raise _rex.ConnectionError(f'requests-shim: {last}') from last
    raise last


def _jar_to_dict(jar):
    out = {}
    try:
        for c in jar:
            out[c.name] = c.value
    except Exception:                                   # noqa: BLE001
        pass
    return out


def _to_requests_response(cr):
    """curl_cffi Response → 真·requests.Response (json/text/content 全兼容)"""
    r = requests.models.Response()
    from requests.structures import CaseInsensitiveDict as _CID
    from requests.cookies import RequestsCookieJar as _RJ
    r.status_code = int(cr.status_code)
    r.url = cr.url
    r.headers = _CID({k: v for k, v in
                      dict(getattr(cr, 'headers', {}) or {}).items()})
    r._content = cr.content or b''
    r.encoding = getattr(cr, 'encoding', None) or 'utf-8'
    r.elapsed = timedelta(seconds=0)
    r.request = None
    r.reason = str(getattr(cr, 'reason', '') or '')
    jar = _RJ()
    try:
        for k, v in (getattr(cr, 'cookies', None) or {}).items():
            jar.set(k, v)          # RequestsCookieJar 自带缺省 domain/path
    except Exception:                                   # noqa: BLE001
        pass
    r.cookies = jar
    return r


# ── 泛型调用入口: 任意库函数一键跑通 ─────────────────────────────
def call_py(qual: str, js_args=None, *, lib: str = 'akshare',
            timeout: int = 15, pace_ms: int = 120):
    """import + 调外部库函数, 结果归一成可 JSON 的 dict

    qual: 'akshare.stock_zh_a_hist_pre_min_em' 或深路径
          'akshare.stock.stock_zh_a_hist_em.stock_zh_a_hist'
    js_args: JSON dict → kwargs / JSON list → 位置参数 / 字符串 → 单个位置参数
    """
    install(timeout=timeout, pace_ms=pace_ms)
    import importlib
    t0 = time.monotonic()
    first = qual.split('.', 1)[0]
    if lib and first != lib and '.' not in qual:
        qual = f'{lib}.{qual}'          # 只帮 "stock_zh_a_hist" 这种裸函数补包名
    modname, fname = qual.rsplit('.', 1)
    mod = importlib.import_module(modname)
    fn = getattr(mod, fname)
    if js_args is None:
        args, kwargs = [], {}
    elif isinstance(js_args, dict):
        args, kwargs = [], dict(js_args)
    elif isinstance(js_args, list):
        args, kwargs = js_args, {}
    else:
        args, kwargs = [js_args], {}
    out = fn(*args, **kwargs)
    rows, columns, n = None, None, None
    try:
        import pandas as _pd
        if isinstance(out, _pd.DataFrame):
            df = out.copy()
            df.columns = [str(c) for c in df.columns]
            from pandas.api import types as _pat
            for c in df.columns:
                # datetime64 直接转字符串: to_json 会给纪元毫秒数, 读不认
                if _pat.is_datetime64_any_dtype(df[c]):
                    df[c] = df[c].astype(str)
            columns = list(df.columns)
            n = len(df)
            payload = _json.loads(df.to_json(orient='records', force_ascii=False))
            rows = payload
            return {'kind': 'dataframe', 'rows': rows, 'columns': columns,
                    'n': n, 'module': modname, 'func': fname,
                    'elapsed_s': round(time.monotonic() - t0, 2), 'shim': True}
    except ImportError:
        pass
    if isinstance(out, (list, dict, str, int, float, bool, type(None))):
        return {'kind': type(out).__name__, 'value': out, 'module': modname,
                'func': fname, 'elapsed_s': round(time.monotonic() - t0, 2),
                'shim': True}
    return {'kind': 'text', 'value': str(out), 'module': modname,
            'func': fname, 'elapsed_s': round(time.monotonic() - t0, 2),
            'shim': True}
