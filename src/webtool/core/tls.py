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

精简环境可能压根没装 ca-certificates（Alpine 需 `apk add ca-certificates`）。
仓库自带一份 CA 包 (`webtool/data/certs/ca-bundle.pem`, Mozilla 根证书集, 随
wheel 分发), 探测链把它排在最后兜底 —— 所以"环境没 CA"在装了本包的环境里
已经不成立, 不会再出现"为了能用就把全站校验关掉"。

## 站点自签证书放哪

`webtool/data/certs/extra/*.pem` 是包内受信任证书的投放点：把站点自己的
证书丢进去, 该站走**正常校验 + 这套信任根**, 不必 `verify_hosts` 关校验。
有 extra 时才现拼一份"基础 CA + extra"的合并文件 (缓存在 cache/tls/),
没 extra 的环境一分钱不多花。注意: 用户显式配了 `ca_bundle` 时按用户那份走,
extra 不掺和 (那份的语义就是"替代", 想追加自己 cat 合并)。

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
           'ca_available', 'bundled_ca', 'extra_certs', 'cert_advice']

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


def _certs_dir():
    """包内证书目录 (随 wheel 分发, 等同配置文件的位置)"""
    from webtool.core.config_data import DATA_DIR
    return os.path.join(str(DATA_DIR), 'certs')

def bundled_ca():
    """仓库自带的 CA 包路径; 没有 (或空) 返回 None"""
    p = os.path.join(_certs_dir(), 'ca-bundle.pem')
    try:
        return p if os.path.getsize(p) > 0 else None
    except OSError:
        return None

def extra_certs():
    """包内站点专有证书 `certs/extra/*.pem` (按文件名排序, 稳定可复现)

    自签/私有 CA 的站点: 把它的 .pem 丢进这个目录, 该站就"验得通"了 ——
    仍然是"验过才放行", 只是换了一套信任根, 比 verify_hosts 关校验强。
    """
    d = os.path.join(_certs_dir(), 'extra')
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return []
    out = []
    for n in names:
        if n.lower().endswith(('.pem', '.crt')):
            p = os.path.join(d, n)
            if os.path.isfile(p):
                out.append(p)
    return out

def _ca_signature():
    """CA 决策的全部输入指纹: 配置 + 每份 extra 证书

    不这么算的话, 往 extra/ 里新丢一份证书在**同进程内不生效** (缓存没失效),
    表现成"明明放了却还报证书错误"。
    """
    sig = [_stamp()]
    for p in extra_certs():
        try:
            st = os.stat(p)
            sig.append((p, st.st_mtime_ns, st.st_size))
        except OSError:
            sig.append((p, None))
    return tuple(sig)

def _merge_extras(base, extras):
    """基础 CA + extra 证书 → 合并文件路径 (按内容指纹缓存)

    返回 (路径, 附加说明)。写不进去就退回 base —— 不能因为缓存目录只读
    就把用户原有的信任根也弄丢。
    """
    import hashlib
    h = hashlib.sha256()
    for p in [base] + extras:
        try:
            st = os.stat(p)
            h.update(('%s|%s|%s\n' % (p, st.st_mtime_ns, st.st_size)).encode())
        except OSError:
            h.update(('%s|-\n' % p).encode())
    blob = []
    try:
        for p in [base] + extras:
            with open(p, 'rb') as f:
                blob.append(f.read())
    except OSError as e:
        return base, 'CA 包 %s (extra 读不到: %s)' % (base, e)
    out_dir = os.path.join(_cache_dir(), 'tls')
    out = os.path.join(out_dir, 'ca-%s.pem' % h.hexdigest()[:16])
    try:
        if not (os.path.isfile(out) and os.path.getsize(out) > 0):
            os.makedirs(out_dir, exist_ok=True)
            tmp = '%s.tmp%d' % (out, os.getpid())
            with open(tmp, 'wb') as f:
                f.write(b'\n'.join(blob))
            os.replace(tmp, out)
    except OSError as e:
        return base, 'CA 包 %s (extra 合并失败: %s)' % (base, e)
    return out, 'CA 包 %s + 包内 %d 份站点证书' % (base, len(extras))

def _cache_dir():
    from webtool.net.proxy import load_config
    cfg = load_config()
    return os.path.expanduser(cfg.get('cache_dir')
                              or os.path.join('~', '.webtool', 'cache'))

def _probe_ca():
    """探测环境里可用的 CA 源 → (路径 或 None, 说明)

    为什么要有探测: 有些精简环境压根没装 ca-certificates (Alpine 需
    `apk add ca-certificates`)。候选顺序是 环境变量 → 系统路径 → certifi
    → **仓库自带** `data/certs/ca-bundle.pem`: 最后那份是保底, 于是"宿主
    一个 CA 都没有"不再等于"全站不校验"。

    有 `certs/extra/*.pem` 时, 选中的 base 会与它们合并 (见 _merge_extras)。
    """
    global _CA_CACHE
    with _LOCK:
        stamp = _ca_signature()
        if _CA_CACHE[1] is not None and _CA_CACHE[0] == stamp:
            return _CA_CACHE[1]
        cands = [os.environ.get('SSL_CERT_FILE'),
                 os.environ.get('CURL_CA_BUNDLE'),
                 os.environ.get('REQUESTS_CA_BUNDLE')]
        dp = ssl.get_default_verify_paths()
        cands += [dp.cafile, dp.openssl_cafile]
        try:
            import certifi
            cands.append(certifi.where())
        except ImportError:                # 有自带 CA 后 certifi 只是加分项
            pass
        bundled = bundled_ca()
        cands.append(bundled)
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
                    if os.path.getsize(p) == 0:
                        continue
                except OSError:
                    continue
                extras = extra_certs()
                mp, reason = (_merge_extras(p, extras) if extras
                              else (p, 'CA 包 %s' % p))
                if bundled and os.path.abspath(p) == os.path.abspath(bundled):
                    reason += ' (仓库自带, 宿主没装 ca-certificates)'
                _CA_CACHE = (stamp, (mp, reason))
                return _CA_CACHE[1]
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
    (调用方显式意图优先, 例如某个已知自签接口的定点豁免)。**传 CA 文件路径**
    等价于 requests 的 `verify=<ca>`: 用它当信任根、开启校验。

    环境无任何 CA 包时自动降级为 False (理由见 _probe_ca) —— 这种情况下
    严格校验等于全线不可用, 且报错完全指不到根因。
    """
    # 调用方直接给 CA 路径 (requests 的 verify=<ca.pem> 语义): 拿它当信任根
    if isinstance(verify, str) and verify.strip():
        _s = verify.strip()
        if _s not in _TRUTHY and _s not in _FALSY:
            return _s
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


# OpenSSL verify_code → (类别, 修法)。别把所有证书错误都推给 ca_bundle:
# 下面这几类的处置**完全不同**, 一律叫用户塞 CA 只会白折腾。
_CERT_CODES = {
    9:  ('服务端证书还没生效 (本机时钟或签发时间有问题)',
         '先对时: date; 时间对不上就得处理, 塞 CA 没用'),
    10: ('服务端证书已过期',
         '证书过期不是信任根能修的: webtool config set verify_hosts <域名> '
         '(只对这个域关校验)'),
    18: ('自签证书 (站方自己签的)',
         '把该站证书丢进 webtool/data/certs/extra/ 即可被信任; '
         '或 webtool config set verify_hosts <域名>'),
    19: ('自签证书 (链内自签)',
         '同上: 证书放 data/certs/extra/, 或 verify_hosts 点名'),
    20: ('拿不到签发者证书 (上游没发中间证书)',
         '用 ca_bundle 把缺的中间证书补上: webtool config set ca_bundle <ca.pem> '
         '(把系统 CA 与中间证书 cat 在一起)'),
    21: ('证书链验不过 (链里没有有效签名)',
         '多半是中间人/上游配错: 先确认不是自己的代理 MITM, '
         '再把代理 CA 并进 ca_bundle'),
    62: ('服务端证书与域名不符',
         '证书是别的域名的 —— CDN 配错、域名迁移或中间人。别去动 ca_bundle: '
         '换一套信任根也修不了"名字不对"。核对真实域名后改用它, '
         '实在要用就 verify_hosts 点名关校验'),
}

# curl_cffi 走 libcurl, 拿不到 verify_code, 只能按文案认
_CERT_TEXT = (
    ('self signed certificate', 18),
    ('self-signed certificate', 18),
    ('certificate has expired', 10),
    ('certificate is not yet valid', 9),
    ('unable to get local issuer', 20),
    ('unable to get issuer certificate', 20),
    ('hostname mismatch', 62),
    ('no alternative certificate subject name', 62),
)

def _chain_exc(e):
    """把异常链摊平: verify_code 常常挂在被裹住的那层 (urllib 的 .reason)"""
    out, seen, stack = [], set(), [e]
    while stack:
        x = stack.pop()
        if x is None or id(x) in seen:
            continue
        seen.add(id(x))
        out.append(x)
        stack += [getattr(x, 'reason', None), getattr(x, '__cause__', None),
                  getattr(x, '__context__', None)]
    return out

def cert_advice(exc, host=''):
    """证书/TLS 失败的类别与处置 → (类别 或 '', 修法 或 '')

    分清楚再说, 因为"域名不符"和"自签"根本不是一回事: 前者塞多少证书都没用。
    """
    code, text = None, ''
    for x in _chain_exc(exc):
        c = getattr(x, 'verify_code', None)
        if c and not code:
            code = c
        t = str(x)
        if t and len(t) < 400:
            text += ' ' + t
    text = text.lower()
    if not code:
        for pat, c in _CERT_TEXT:
            if pat in text:
                code = c
                break
    label, fix = _CERT_CODES.get(code, ('', ''))
    if not label and ('unsafe_legacy_renegotiation' in text
                      or 'unsafe legacy renegotiation' in text):
        label = '服务端要旧的 TLS 重协商 (不是证书问题)'
        fix = ('上游 OpenSSL 太旧, 客户端需要 OP_LEGACY_SERVER_CONNECT; '
               '绕不过就 webtool config set verify_hosts %s' % (host or '<域名>'))
    if label and code == 62 and host:
        fix += ' (当前域名: %s)' % host
    return label, fix

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