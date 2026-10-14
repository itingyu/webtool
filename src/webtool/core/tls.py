"""TLS 策略: 证书校验的唯一决策点。

curl_cffi / urllib / requests 三条通道都从这里取 CA, 不各自读环境变量 ——
否则 REQUESTS_CA_BUNDLE、CURL_CA_BUNDLE、SSL_CERT_FILE 各认各的, 同一次
调用里三条通道可能用三套信任根, 出了证书问题没法定位。

## 配置 (~/.webtool/config.json, 用 `webtool config set` 写)

| 键 | 值 | 含义 |
|---|---|---|
| `ssl_verify` | `on` / `off` | 总开关, 默认 `on` |
| `ca_bundle` | 路径 | `on` 时用自定义 CA 包**替代**系统 CA (想追加就自己 cat 合并) |
| `verify_hosts` | `a.com,b.cn` | 这些域名单独关校验, 其余域仍严格校验 |

`verify_hosts` 存在的理由: 郑商所 / 国泰君安 / 99期货 这类交易所站点用自签或
过期证书, 但为了抓它们把全局校验关掉, 等于把代理 MITM 也一起放进来了。名单
模式只对指定域开口, 其余流量照常 fail-closed。

## 环境没有 CA 包时

精简环境可能压根没装 ca-certificates。此时 `ssl_verify=on` 会让**所有 HTTPS
请求失败**, 且报错 (CERTIFICATE_VERIFY_FAILED) 完全指不到"系统没证书"这个
根因。所以 `_probe_ca()` 会先探环境: 一个可用 CA 源都没有时自动降级为不校验
(可用 > 安全), 并把原因写进 `describe()` 的 `warning` —— 降级是看得见的,
不会静悄悄生效。装上 `ca-certificates` 后自动恢复严格校验。

## 决策优先级

单次调用 `verify=` 参数 > `verify_hosts` 命中 > `ssl_verify` 总开关。

返回值统一用 curl_cffi / requests 通用语义: `False` (不校验) 或 `'<CA 路径>'`
(校验, 且信任根由本模块指定)。校验开启时**不给 True** —— curl_cffi 与 requests
看到 True 会各自去读 REQUESTS_CA_BUNDLE / CURL_CA_BUNDLE, 三通道就可能各用各的
信任根; 显式给路径才能保证同源。
"""
import os
import ssl
import threading

__all__ = ['TlsError', 'TlsConfigError', 'policy', 'ssl_context', 'describe',
           'insecure_hosts', 'host_of', 'hit_insecure', 'is_tls_error',
           'ca_available']

# 配置文件读一次, 按 (mtime, size) 指纹缓存 —— 改配置后同进程内自动生效
_LOCK = threading.Lock()
_CACHE = (None, None)          # (stamp, (verify_on, ca_path, hosts_frozenset))

_TRUTHY = ('on', 'true', '1', 'yes', 'y')
_FALSY = ('off', 'false', '0', 'no', 'n')


class TlsError(RuntimeError):
    """证书校验失败 —— 不可降级重试的硬失败。

    与 BlockedError 区分开: 验证码可以换指纹/换代理再试, 证书不行, 再试
    多少次都是同样的结果, 只会白白打满退避梯。
    """


class TlsConfigError(TlsError):
    """TLS 配置非法 (ca_bundle 路径不存在等), 属于配置问题不是网络问题"""


def _as_bool(v, default=True):
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    if s in _TRUTHY:
        return True
    if s in _FALSY:
        return False
    raise TlsConfigError(
        f'ssl_verify 只认 on/off, 收到: {v!r} (webtool config set ssl_verify on|off)')


def _stamp():
    from webtool.net.proxy import CONFIG_PATH
    try:
        st = os.stat(CONFIG_PATH)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _load():
    """读配置 → (verify_on, ca_path, insecure_hosts), 带 mtime 缓存"""
    global _CACHE
    with _LOCK:
        stamp = _stamp()
        if _CACHE[1] is not None and _CACHE[0] == stamp:
            return _CACHE[1]
        from webtool.net.proxy import load_config
        cfg = load_config()
        on = _as_bool(cfg.get('ssl_verify'), True)
        ca = cfg.get('ca_bundle') or None
        if ca:
            ca = os.path.expanduser(str(ca).strip())
            if not os.path.isfile(ca):
                raise TlsConfigError(
                    f'ca_bundle 指向的文件不存在: {ca}\n'
                    f'  修正: webtool config set ca_bundle <真实路径>, 或 '
                    f'webtool config unset ca_bundle 回系统 CA')
        raw = cfg.get('verify_hosts') or []
        if isinstance(raw, str):
            raw = raw.replace(';', ',').split(',')
        hosts = frozenset(
            str(h).strip().lower().lstrip('.')
            for h in raw if str(h).strip())
        _CACHE = (stamp, (on, ca, hosts))
        return _CACHE[1]


def host_of(url):
    """从 URL 取 hostname (去端口/路径/大小写), 认不出域名返回 ''"""
    if not url:
        return ''
    s = str(url)
    if '://' in s:
        s = s.split('://', 1)[1]
    for sep in ('/', '?', '#'):
        s = s.split(sep, 1)[0]
    if '@' in s:                       # user:pass@host
        s = s.rsplit('@', 1)[1]
    s = s.strip().lower()
    if s.startswith('['):              # IPv6 字面量 [::1]:443
        return s[1:s.find(']')] if ']' in s else s
    return s.split(':', 1)[0]


def hit_insecure(host, hosts=None):
    """host 是否命中关校验名单: 精确相等或子域 (a.com 覆盖 www.a.com)"""
    hosts = insecure_hosts() if hosts is None else hosts
    if not host or not hosts:
        return False
    return host in hosts or any(host.endswith('.' + h) for h in hosts)


def insecure_hosts():
    """当前关校验的域名单 (frozenset)"""
    return _load()[2]


_CA_CACHE = (None, None)     # (stamp, (path_or_None, reason))


def _probe_ca():
    """探测环境里可用的 CA 源 → (路径 或 None, 说明)

    为什么要有探测: 有些精简环境压根没装 ca-certificates (Alpine 需
    `apk add ca-certificates`)。此时若照常返回 True 让上层严格校验,
    **所有 HTTPS 请求会 100% 失败** —— 搜索/抓取/zen 全线瘫, 而且报的错是
    CERTIFICATE_VERIFY_FAILED, 完全看不出根因是"系统没证书"。

    所以这里先探: 一个可用 CA 源都没有时降级为不校验 (可用 > 安全), 并把
    原因带进 describe(), 让降级是**看得见**的而不是静悄悄的。
    """
    global _CA_CACHE
    with _LOCK:
        stamp = _stamp()
        if _CA_CACHE[1] is not None and _CA_CACHE[0] == stamp:
            return _CA_CACHE[1]
        # 环境变量优先 (与 curl_cffi/openssl 约定一致), 再系统路径, 最后 certifi
        import certifi
        cands = [os.environ.get('SSL_CERT_FILE'),
                 os.environ.get('CURL_CA_BUNDLE'),
                 os.environ.get('REQUESTS_CA_BUNDLE')]
        dp = ssl.get_default_verify_paths()
        cands += [dp.cafile, dp.openssl_cafile, certifi.where()]
        seen = set()
        for c in cands:
            if not c:
                continue
            p = os.path.expanduser(c)
            if p in seen:
                continue
            seen.add(p)
            if os.path.isfile(p):
                try:
                    if os.path.getsize(p) > 0:
                        _CA_CACHE = (stamp, (p, f'CA 包 {p}'))
                        return _CA_CACHE[1]
                except OSError:
                    continue
        _CA_CACHE = (stamp, (None, '环境里找不到任何 CA 包 '
                                   '(装 ca-certificates 或配 ca_bundle)'))
        return _CA_CACHE[1]


def ca_available():
    """环境是否有可用 CA 源 → (bool, 说明)"""
    path, _reason = _probe_ca()
    return path is not None, _reason


def _system_ca():
    """系统 CA 包路径; 一个都没有时返回 None (由 policy 决定降级)"""
    return _probe_ca()[0]


def policy(url=None, verify=None):
    """该 URL 该怎么验证书 → False / '<CA 路径>'

    校验开着时返回**解析好的 CA 路径**而不是 True: curl_cffi 与 requests 见到
    True 会各自去读 REQUESTS_CA_BUNDLE / CURL_CA_BUNDLE, 三通道就可能用三套
    信任根; 显式给路径则完全由本模块说了算。

    verify=None 表示"按配置来"; 传 True/False 则无视配置直接决定
    (调用方显式意图优先, 例如某个已知自签接口的定点豁免)。

    环境无任何 CA 包时自动降级为 False (理由见 _probe_ca) —— 这种情况下
    严格校验等于全线不可用, 且报错完全指不到根因。
    """
    on, ca, hosts = _load()
    if verify is not None:
        on = _as_bool(verify)
    elif url and hit_insecure(host_of(url), hosts):
        on = False
    if not on:
        return False
    return ca or _system_ca() or False


def is_tls_error(exc):
    """判断一个异常是不是"证书/TLS 层面"的失败 (跨通道通用)。

    为什么不能只靠类型元组: 三条通道包装证书错误的方式完全不同 ——
      curl_cffi → CertificateVerifyError (自己继承 OSError)
      urllib    → URLError, 真正的 ssl.SSLError 藏在 .reason 里
      requests  → requests.exceptions.SSLError (只继承 OSError, **不是**
                  ssl.SSLError 的子类)
    所以这里逐层判定: 顶层类型 → urllib 的 .reason → requests 的类型。
    """
    import urllib.error
    if isinstance(exc, (ssl.SSLError, ssl.CertificateError, TlsConfigError)):
        return True
    # curl_cffi: 独立异常类, 只能按名字/模块认 (它可能没装)
    if type(exc).__name__ in ('CertificateVerifyError', 'SSLError'):
        if 'curl_cffi' in type(exc).__module__:
            return True
        # requests.exceptions.SSLError 同名但不同来源, 已在下面覆盖
    # urllib: SSL 错误裹在 URLError.reason
    reason = getattr(exc, 'reason', None)
    if isinstance(exc, urllib.error.URLError) and reason is not None:
        if isinstance(reason, (ssl.SSLError, ssl.CertificateError)):
            return True
    # requests: 自带 SSLError / CertificateError, 与 ssl.* 无继承关系
    mod = type(exc).__module__ or ''
    if mod.startswith('requests.exceptions') and type(exc).__name__ in (
            'SSLError', 'CertificateError'):
        return True
    return False


_CTX_CACHE = {}


def ssl_context(url=None, verify=None):
    """urllib 通道用: 配好校验策略的 SSLContext (同参数复用同一 context)

    verify=False 时给 CERT_NONE (自签/过期站专用); 指定 CA 时只加载该文件
    (替代而非追加系统 CA, 与 curl_cffi 的 CAINFO 语义保持一致)。
    """
    p = policy(url, verify)
    key = p if isinstance(p, str) else bool(p)
    ctx = _CTX_CACHE.get(key)
    if ctx is not None:
        return ctx
    if p is False:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    else:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
        if isinstance(p, str):
            ctx.load_verify_locations(cafile=p)
        else:
            ctx.load_default_certs(ssl.Purpose.SERVER_AUTH)
    _CTX_CACHE[key] = ctx
    return ctx


def describe():
    """人读摘要, 给 `webtool config list` / 故障排查用"""
    try:
        on, ca, hosts = _load()
    except TlsConfigError as e:
        return {'ssl_verify': f'配置错误: {e}', 'ca_bundle': None,
                'verify_hosts': [], 'warning': str(e)}
    ca_path, ca_reason = _probe_ca()
    effective = 'on' if (on and (ca or ca_path)) else 'off'
    out = {
        'ssl_verify': effective,
        'ca_bundle': ca or ca_path or '(未找到 CA 包)',
        'verify_hosts': sorted(hosts),
    }
    # 配置写 on 但环境没 CA 只能降级时必须报出来 —— 否则用户看到"生效策略是
    # on"却不知道实际没校验, 或者反过来满屏 CERTIFICATE_VERIFY_FAILED
    if on and not (ca or ca_path):
        out['warning'] = (
            f'配置为 ssl_verify=on, 但{ca_reason} —— 已自动降级为不校验。'
            f'修复: apk add ca-certificates, 或指定 '
            f'webtool config set ca_bundle <ca.pem>')
    elif ca_path:
        out['ca_source'] = ca_reason
    return out