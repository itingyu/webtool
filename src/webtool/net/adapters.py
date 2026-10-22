"""requests 兼容适配器 (L7 适配层): 让 requests 的调用点原样复用 transport 通道

stock 有 61 处 `self._std.get(url, …)`, 逐个改成 transport.request 既费事又会漏。
适配器把 requests.Session 的 send() 桥到 transport.request, 于是调用点写什么都
不影响线路与证书的判断 —— 真正出网的是 transport 层。

从 net/transport 拆出 (P4), transport 再导出 requests_session 保兼容。
本模块不新开出网通道 (出网仍经 transport.request), 故不进 test_netx 的出网原语登记。
"""
import logging
import threading
import time
import urllib.parse

from webtool.net.fingerprints import headers_for
from webtool.net.tls import TlsError

logger = logging.getLogger(__name__)


def _transport():
    """惰性拿 transport 本体 (transport 模块级再导出本模块, 直接用会循环)"""
    from webtool.net import transport
    return transport


_ADAPTER = {}


def requests_session(*, proxy='auto', kind='api', profile=None, timeout=None,
                     retries=2):
    """stock/data 源用的 requests.Session: 每个请求都回到 transport 层出网

    调用点不必改 (仍是 `s.get` / `s.post` / …), 但请求由 transport 发出:

    - 线路按目标 URL 现算 (逐域名问规则表, 不绑在 session 上)
    - 证书走 `tls.policy`, 头走指纹档案 (裸 python-requests 指纹会被反爬站 403)
    - 连接按 (线路, 主机) 复用 —— 一次调用打十余个域名也不会每请求重开 TLS
    - 幂等请求带收敛重试 (RemoteDisconnected/5xx 换连接重试)

    也就是说 stock 与搜索引擎共用同一条通道, 不再是"抓网页走代理、取行情直连"。
    """
    import requests
    ad = _transport_adapter()(proxy=proxy, kind=kind, profile=profile,
                              timeout=timeout, retries=retries)
    s = requests.Session()
    s.trust_env = False                    # 空 proxies 不够: 环境变量还会漏进来
    s.proxies = {}
    s.mount('http://', ad)
    s.mount('https://', ad)
    return s


def patch_requests(**kw):
    """把 transport 适配器挂成**所有** requests.Session 的默认出口

    第三方库 (akshare / trafilatura / 任何内部自建 Session 的代码) 不走我们的
    工厂, 它们只认 python-requests —— 这一步让它们也回到统一通道: 线路按目标域名
    现算、证书走 `tls.policy`、缺省头补指纹、连接按 (线路, 主机) 复用。

    想自己挂适配器的库仍然优先: 它在 `__init__` 之后 mount, 覆盖我们这一次。
    幂等; `WEBTOOL_NO_PATCH_REQUESTS=1` 可整体关掉 (排查"是不是这层惹的")。
    """
    import os
    if os.environ.get('WEBTOOL_NO_PATCH_REQUESTS'):
        return False
    import requests
    if getattr(requests.Session, '_webtool_unified', False):
        return False
    _orig_init = requests.Session.__init__

    def _init(self, *a, **k):
        _orig_init(self, *a, **k)
        try:
            ad = _transport_adapter()(**kw)
            self.mount('http://', ad)
            self.mount('https://', ad)
        except Exception:                     # noqa: BLE001
            pass                              # 挂不上就退回原生适配器, 不能连累调用方

    requests.Session.__init__ = _init
    requests.Session._webtool_unified = True
    return True


def _transport_adapter():
    """懒建适配器类: requests 只有真用这条通道时才需要 (懒导入依赖)"""
    if 'cls' in _ADAPTER:
        return _ADAPTER['cls']
    import requests

    class TransportAdapter(requests.adapters.BaseAdapter):
        """requests → transport 的桥

        stock 有 61 处 `self._std.get(url, …)`, 逐个改成 transport.request 既
        费事又会漏。真正出网的是 transport 层, 调用点写什么都不影响线路与证书的判断。
        """

        def __init__(self, *, proxy='auto', kind='api', profile=None,
                     timeout=None, retries=2):
            self.proxy = proxy
            self.kind = kind
            self.profile = profile
            self.timeout = timeout
            self.retries = int(retries or 0)
            self._pool = {}
            self._lock = threading.Lock()

        # ── 会话复用: 连接池按 (线路, 主机) 分家, 主机不同不复用连接 ──
        def _sess(self, url, proxy):
            host = urllib.parse.urlsplit(url).netloc
            with self._lock:
                key = (proxy, host)
                s = self._pool.get(key)
                if s is None:
                    s, _p = _transport().new_session(self.profile, proxy, None, url)
                    self._pool[key] = s
                return s

        def send(self, request, stream=False, timeout=None, verify=True,
                 cert=None, proxies=None):
            px = _transport()._proxy_choice(proxies, self.proxy)
            h = dict(request.headers)
            # 长度/编码交给底层按实际体算 (我们可能改过 body)
            for k in ('Content-Length', 'Content-Encoding', 'Transfer-Encoding'):
                h.pop(k, None)
            if request.body is not None and not h.get('Content-Type'):
                h['Content-Type'] = 'application/x-www-form-urlencoded'
            # 默认头在这里补: 调用点大多只给 Referer, 裸 python-requests 指纹会被
            # 反爬站直接 403 (同花顺 data 子域就是)。调用点自己设了 UA 就不动。
            _kind = 'plain' if self.kind == 'api' else self.kind
            for k, v in (headers_for(_kind, request.url, full=True) or {}).items():
                if k == 'User-Agent':
                    ua = h.get('User-Agent') or ''
                    if not ua or ua.startswith(('python-requests',
                                                'python-urllib')):
                        h[k] = v
                elif not h.get(k):
                    h[k] = v
            to = timeout if timeout is not None else (self.timeout or 15)
            last = None
            for attempt in range(max(1, self.retries + 1)):
                try:
                    r = _transport().request(
                        request.method, request.url, kind=self.kind,
                        headers=h, data=request.body, timeout=to,
                        verify=verify, proxy=px, stream=stream,
                        session=self._sess(request.url, px),
                        allow_redirects=False)
                except Exception as e:              # noqa: BLE001
                    last = e
                    if attempt < self.retries:
                        time.sleep(0.3 * (attempt + 1))   # 换连接/换指纹再试
                        continue
                    _raise_as_requests(e, request.url)
                # 5xx 收敛重试 (与旧 urllib3 Retry 的 status_forcelist 对齐)
                if (r.status_code in (500, 502, 503, 504) and attempt < self.retries
                        and request.method.upper() in ('GET', 'HEAD')):
                    last = None
                    _safe_close(r)
                    time.sleep(0.3 * (attempt + 1))
                    continue
                return _as_requests_response(r, request)
            raise requests.exceptions.ConnectionError(str(last))

        def close(self):
            with self._lock:
                for s in self._pool.values():
                    try:
                        s.close()
                    except Exception:               # noqa: BLE001
                        pass
                self._pool.clear()

    _ADAPTER['cls'] = TransportAdapter
    return TransportAdapter


def _safe_close(r):
    try:
        r.close()
    except Exception:                          # noqa: BLE001
        pass


def _raise_as_requests(e, url):
    """把 transport 层的错误翻成 requests 的异常类型

    stock 里有 `except requests.exceptions.*` 与 tls 的判定, 拿错类型会让
    "证书问题"被当成"网络问题"重试到底。
    """
    import requests
    if isinstance(e, TlsError):
        raise requests.exceptions.SSLError(str(e)) from e
    if isinstance(e, requests.exceptions.RequestException):
        raise
    raise requests.exceptions.ConnectionError(f'{url}: {e}') from e


def _as_requests_response(r, request):
    """Resp → requests.Response (stock 的调用点要的就是 requests 那个壳)"""
    import requests
    resp = requests.models.Response()
    resp.status_code = r.status_code
    resp.url = r.url or request.url
    resp.request = request
    resp.reason = ''
    resp.headers.update({k: v for k, v in (r.headers or {}).items()})
    resp._content = r.content
    ct = str((r.headers or {}).get('content-type', ''))
    if 'charset=' in ct:
        resp.encoding = ct.split('charset=')[-1].split(';')[0].strip()
    return resp


# ── 延迟补丁: 谁先用 requests, 谁触发 ────────────────────────────────────
# patch_requests() 本身要 import requests (~0.5s: requests + urllib3 + 编解码)。
# 以前每条命令启动都先付这笔钱, 连 `stock calendar` / `config get` 这种纯本地
# 动作也一样。改成挂在 requests 的首次导入上: 补丁仍然**早于任何 Session 创建**
# (第三方库 import requests 之后才会建 Session), 但不用它的命令一分不付。
_HOOK = None


class _PatchOnRequestsImport:
    """找到 `requests` 的 spec, 在它的 exec_module 之后立刻打补丁"""

    def find_spec(self, fullname, path=None, target=None):
        if fullname != 'requests':
            return None
        spec = None
        for finder in list(_sys().meta_path):
            if finder is self:
                continue
            find_spec = getattr(finder, 'find_spec', None)
            if find_spec is None:
                continue
            try:
                spec = find_spec(fullname, path, target)
            except Exception:                 # noqa: BLE001
                spec = None
            if spec is not None:
                break
        if spec is None or spec.loader is None:
            return None
        _orig_exec = spec.loader.exec_module
        _finder = self

        def _exec(module):
            _orig_exec(module)
            try:
                patch_requests()
            except Exception:                 # noqa: BLE001
                pass
            finally:
                try:
                    _sys().meta_path.remove(_finder)
                except ValueError:
                    pass

        spec.loader.exec_module = _exec
        return spec


def _sys():
    import sys
    return sys


def install_patch_hook():
    """装上"首次 import requests 时打补丁"的钩子 (幂等)"""
    import os
    import sys
    if os.environ.get('WEBTOOL_NO_PATCH_REQUESTS'):
        return False
    if 'requests' in sys.modules:             # 已经被谁抢先导入了: 立刻补
        return patch_requests()
    global _HOOK
    if _HOOK is not None and _HOOK in sys.meta_path:
        return False
    _HOOK = _PatchOnRequestsImport()
    sys.meta_path.insert(0, _HOOK)
    return True
