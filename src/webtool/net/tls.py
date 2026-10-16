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
仓库自带一份 CA 包 (Mozilla 根证书集, 随 wheel 分发), 探测链把它排在最后兜底
—— 所以"环境没 CA"在装了本包的环境里已经不成立, 不会再出现"为了能用就把全站
校验关掉"。首次运行时它会被落到 `~/.webtool/certs/ca-bundle.pem` (可增补企业根),
那份优先; 缺了回落到包内 `webtool/data/certs/ca-bundle.pem`, 删掉重跑即重新落一份。

## 站点自签证书放哪 —— `~/.webtool/certs/extra/*.pem` + 一条 tls 规则

把站点自己的证书丢进 `~/.webtool/certs/extra/`, 再把**它覆盖的域名**配成规则,
该站就走"正常校验 + 这套信任根", 不必 `verify_hosts` 关校验:

    {"kind": "tls", "match": {"domain": ["*.zce.com.cn"]}, "ca": "extra/zce.pem"}

为什么非要那条规则: 证书是**某个站点的**证书, 信任根就该只对这个站点生效。
以前 extra/ 是全局并进信任根的 —— 一份站点自签证书顺手给所有域名开了口子,
企业 MITM 根一旦丢进去全站都认它。现在按站点配, 命中才现拼一份
"基础 CA + 该站证书"的合并文件 (缓存在 cache/tls/), 没命中一分钱不多花。

规则里的 `ca` 是**追加**语义 (基础 CA + 该站证书), 与全局 `ca_bundle` 的
"替代"语义相反: 站点证书只对自己有意义, 没理由把公共根挡在外面。`ca` 可以写
绝对路径, 也可以写相对 `~/.webtool/certs/` 的路径 (`extra/zce.pem`) —— 后者
换机器、换 home 目录都还认。`verify: off` 则只对该站关校验 (比 verify_hosts
多一个精确性: 规则里能连端口一起限)。

`webtool proxy cert list` 看 extra/ 里每份证书**是哪些站点的**、顶上有没有规则;
`webtool proxy cert sync` 按证书里的域名把规则自动写好。

投放点必须落在**用户目录**: 包内那份 (`webtool/data/certs/extra/`) 在
site-packages 里, 升级时整棵被替换掉 —— 实测往包目录塞的证书
`pip install --upgrade` 之后片甲不留, 表现成"某个站的证书突然又报错了"。
包内目录只作发行方预置 (同名时用户目录优先)。

## 决策优先级

单次调用 `verify=` 参数 > tls 规则命中该域名 > `verify_hosts` 命中 > `ssl_verify` 总开关。

tls 规则排第二: 规则是"这个域名该用什么信任根"的**站点级**答案, 比全域总开关
和全域名单都具体。`verify=` 参数排第一仍是惯例 —— 调用方显式指定的定点豁免
(某个已知自签接口) 优先于配置, 否则老代码的意图会被规则悄悄改掉。

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
           'ca_available', 'bundled_ca', 'ca_bundle_candidates', 'extra_certs',
           'extra_dirs', 'cert_advice', 'rule_params', 'tls_rules',
           'cert_sites', 'site_certs', 'cert_rules', 'cert_status',
           'resolve_cert_path']

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
    from webtool.net.proxy.store import CONFIG_PATH
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

def extra_dirs():
    """站点证书投放点, 用户目录在前 (同名时用户那份胜出)

    用户目录 (`~/.webtool/certs/extra/`, 跟 WEBTOOL_DIR 走) 是给"用的人"的:
    包目录在 site-packages 里, `pip install --upgrade` 会把整棵目录换掉,
    塞在那儿的证书活不过一次升级。包内目录留着当发行方预置。
    """
    from webtool.core.config_data import USER_DIR
    return [os.path.join(str(USER_DIR), 'certs', 'extra'),
            os.path.join(_certs_dir(), 'extra')]

def ca_bundle_candidates():
    """自带 CA 包的候选路径: 用户目录那份在前, 包内那份兜底

    用户那份是"可以增补的" (把企业根 cat 进去), 包内那份是发行时的那一版。
    """
    from webtool.core.config_data import USER_DIR
    return [os.path.join(str(USER_DIR), 'certs', 'ca-bundle.pem'),
            os.path.join(_certs_dir(), 'ca-bundle.pem')]

def bundled_ca():
    """当前该用的自带 CA 包路径; 两份都没有 (或都空) 返回 None"""
    for p in ca_bundle_candidates():
        try:
            if os.path.getsize(p) > 0:
                return p
        except OSError:
            continue
    return None

def extra_certs():
    """站点专有证书: 用户目录 `~/.webtool/certs/extra/` + 包内预置, 按名去重

    自签/私有 CA 的站点: 把它的 .pem 丢进用户目录, 再按站点配一条 tls 规则
    (webtool proxy cert sync 自动做), 该站就"验得通"了 —— 仍然是"验过才放行",
    只是换了一套只对它生效的信任根。**放进 extra/ 本身不生效**, 一定要有规则
    点名 (见 cert_status)。
    """
    out, seen = [], set()
    for d in extra_dirs():
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for n in names:
            p = os.path.join(d, n)
            if not n.lower().endswith(('.pem', '.crt')) or n in seen:
                continue
            if os.path.isfile(p):
                seen.add(n)
                out.append(p)
    return out

def _ca_signature():
    """CA 决策的全部输入指纹: 配置 + 每份 CA 包

    注意**不含** extra/ 里的站点证书: 它们不再全局并进信任根 (那是"一份站点
    证书给所有域名开口子"), 只对规则点名的站点生效 —— 那份合并走
    _scoped_ca, 指纹由 _merge_extras 自己按内容算, 与这里的探测缓存无关。
    """
    sig = [_stamp()]
    # 用户目录那份 CA 包是可编辑的 —— 换了它必须让缓存失效, 否则"改了没生效"
    for p in ca_bundle_candidates():
        try:
            st = os.stat(p)
            sig.append((p, st.st_mtime_ns, st.st_size))
        except OSError:
            sig.append((p, None))
    return tuple(sig)

def _merge_extras(base, extras):
    """基础 CA + 站点证书 → 合并文件路径 (按内容指纹缓存)

    返回 (路径, 附加说明)。写不进去就退回 base —— 不能因为缓存目录只读
    就把用户原有的信任根也弄丢。

    先按指纹算文件名、命中就直接返回, **不读内容**: 这个函数在请求链路上
    (每个 tls 规则命中的站点都要一次), 每次都把 200KB 的 CA 包读一遍等于
    给每个请求加一次全量 IO。
    """
    import hashlib
    h = hashlib.sha256()
    for p in [base] + extras:
        try:
            st = os.stat(p)
            h.update(('%s|%s|%s\n' % (p, st.st_mtime_ns, st.st_size)).encode())
        except OSError:
            h.update(('%s|-\n' % p).encode())
    out_dir = os.path.join(_cache_dir(), 'tls')
    out = os.path.join(out_dir, 'ca-%s.pem' % h.hexdigest()[:16])
    why = 'CA 包 %s + 站点证书 %d 份' % (base, len(extras))
    try:
        if os.path.isfile(out) and os.path.getsize(out) > 0:
            return out, why
    except OSError:
        pass
    blob = []
    try:
        for p in [base] + extras:
            with open(p, 'rb') as f:
                blob.append(f.read())
    except OSError as e:
        return base, 'CA 包 %s (extra 读不到: %s)' % (base, e)
    try:
        os.makedirs(out_dir, exist_ok=True)
        tmp = '%s.tmp%d' % (out, os.getpid())
        with open(tmp, 'wb') as f:
            f.write(b'\n'.join(blob))
        os.replace(tmp, out)
    except OSError as e:
        return base, 'CA 包 %s (extra 合并失败: %s)' % (base, e)
    return out, why

def _cache_dir():
    from webtool.net.proxy import load_config
    cfg = load_config()
    return os.path.expanduser(cfg.get('cache_dir')
                              or os.path.join('~', '.webtool', 'cache'))

def _probe_ca():
    """探测环境里可用的 CA 源 → (路径 或 None, 说明)

    为什么要有探测: 有些精简环境压根没装 ca-certificates (Alpine 需
    `apk add ca-certificates`)。候选顺序是 环境变量 → 系统路径 → certifi
    → **自带** `~/.webtool/certs/ca-bundle.pem` (缺则包内那份): 最后那份兜底, 于是"宿主
    一个 CA 都没有"不再等于"全站不校验"。

    这里**只给基础 CA**: 站点自己的证书要由 tls 规则点名才生效 (见 _scoped_ca)，
    不再全局并进信任根。
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
                reason = 'CA 包 %s' % p
                if bundled and os.path.abspath(p) == os.path.abspath(bundled):
                    where = '用户目录' if p == ca_bundle_candidates()[0] else '包内'
                    reason += ' (自带 %s, 宿主没装 ca-certificates)' % where
                _CA_CACHE = (stamp, (p, reason))
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


# ── 站点级证书策略: rules.json 里的 kind:tls 规则 ──────────────────────

def tls_rules():
    """rules.json 里全部 kind:tls 规则 (原样返回, 顺序同文件)"""
    try:
        from webtool.net.rules import router as _router
        return [r for r in _router().kind_rules if r.get('kind') == 'tls']
    except Exception:                     # 规则文件坏了 → 当作没有 (policy 另有兜底)
        return []


def rule_params(url):
    """该 URL 命中的 tls 规则字段; 无命中 → {}

    走 Router.params_for —— 匹配器 (domain/host/port/scheme/cidr/geosite/…)
    与线路规则共用一套, 不在这里另写一份"域名怎么算命中"。
    """
    if not url:
        return {}
    try:
        from webtool.net.rules import router as _router
        return _router().params_for('tls', url) or {}
    except Exception:                     # 规则表坏了不能把请求连带干掉
        return {}


def resolve_cert_path(p):
    """把规则里的 ca 值解析成真实文件路径; 不存在 → ''

    支持三种写法, 按序试: 绝对/带 ~ 的路径 → 相对用户证书目录
    (`extra/zce.pem` = `~/.webtool/certs/extra/zce.pem`) → 相对包内证书目录。
    相对写法让规则换机器、换 home 都还认 —— 写死绝对路径的规则一换环境就失效,
    而失效的表现是"某站又开始报证书错误", 很难联想到规则。
    """
    if not p:
        return ''
    s = os.path.expanduser(str(p).strip())
    cands = [s]
    if not os.path.isabs(s):
        from webtool.core.config_data import USER_DIR
        cands += [os.path.join(str(USER_DIR), 'certs', s),
                  os.path.join(_certs_dir(), s)]
    for c in cands:
        try:
            if os.path.isfile(c) and os.path.getsize(c) > 0:
                return c
        except OSError:
            continue
    return ''


def _scoped_ca(ca, host=''):
    """tls 规则的 ca → 该站点的信任根文件路径 (基础 CA + 该站证书)

    **追加**语义, 与全局 ca_bundle 的"替代"相反 —— 站点自签证书只对自己有意义,
    没理由把公共根挡在外面。环境连基础 CA 都没有时退回"只用这份", 至少能用。
    """
    items = ca if isinstance(ca, (list, tuple)) else [ca]
    paths = [p for p in (resolve_cert_path(x) for x in items) if p]
    if not paths:
        raise TlsConfigError(
            f'tls 规则的 ca 指向的文件不存在: {ca!r}'
            f'{(" (域名 %s)" % host) if host else ""}\n'
            f'  相对路径按 ~/.webtool/certs/ 解析, 例如 "extra/zce.pem" → '
            f'{os.path.join(str(_user_dir()), "certs", "extra", "zce.pem")}\n'
            f'  修法: webtool proxy cert sync (按 extra/ 里的证书自动配), '
            f'或改掉这条规则的 ca')
    base = _system_ca()
    if not base:
        return paths[0]
    merged, _why = _merge_extras(base, paths)
    return merged


def _user_dir():
    from webtool.core.config_data import USER_DIR
    return USER_DIR


def cert_sites(path):
    """一份证书覆盖的域名 (SAN dNSName 在前, CN 兜底), 去重保序; 读不出 → []

    要它是因为"证书是哪些站点的"只有证书自己知道: 让用户拿 openssl 手抄域名
    再手写规则, 一份证书多个 SAN 就是一场抄错。这里直接从证书里读。
    """
    try:
        d = ssl._ssl._test_decode_cert(os.path.expanduser(str(path)))
    except Exception:                     # 坏文件/不是 PEM/不是证书对象
        return []
    out = []

    def _add(h):
        h = str(h or '').strip().lower().rstrip('.').lstrip('.')
        if h and h not in out and ' ' not in h:
            out.append(h)

    for kind, val in (d.get('subjectAltName') or ()):
        if str(kind).upper() in ('DNS', 'DNSNAME'):
            _add(val)
    for rdn in (d.get('subject') or ()):
        for k, v in rdn:
            # CN 只在看着像域名时收下: 通配/纯名字 (如 "My Company CA") 收进来
            # 只会生成一条永远命不中的规则
            if str(k) == 'commonName' and '.' in str(v or ''):
                _add(v)
    return out


def _cert_info(path):
    """一份证书的体检: 站点 / 自签与否 / 有效期"""
    info = {'path': path, 'name': os.path.basename(path), 'sites': []}
    try:
        d = ssl._ssl._test_decode_cert(os.path.expanduser(path))
    except Exception:
        info['error'] = '读不出证书内容 (不是 PEM/已损坏)'
        return info
    info['sites'] = cert_sites(path)
    sub = d.get('subject') or ()
    iss = d.get('issuer') or ()
    info['self_signed'] = _flatten(sub) == _flatten(iss)
    info['not_after'] = d.get('notAfter') or ''
    info.pop('error', None)
    return info


def _flatten(name):
    return tuple(sorted((str(k), str(v)) for rdn in (name or ()) for k, v in rdn))


def site_certs():
    """extra/ 里每份证书 → 它覆盖的站点 (给 CLI/体检用)

    返回 [{'path','name','sites','self_signed','not_after'}]。
    """
    return [_cert_info(p) for p in extra_certs()]


def cert_rules(certs=None):
    """extra/ 里的证书 → kind:tls 规则条目 (一份证书一条)

    match 用证书自称的域名, ca 用**相对 ~/.webtool/certs/ 的路径** —— 规则文件
    里写绝对路径的话, 换 home 就整批失效。
    """
    out = []
    for c in (site_certs() if certs is None else certs):
        if not c.get('sites') or c.get('error'):
            continue
        out.append({'kind': 'tls', 'match': {'domain': list(c['sites'])},
                    'ca': _rel_cert_path(c['path']), 'auto': 'cert'})
    return out


def _rel_cert_path(path):
    """证书路径 → 规则里的写法 (在用户证书目录下就用相对路径)"""
    p = os.path.abspath(os.path.expanduser(str(path)))
    base = os.path.join(str(_user_dir()), 'certs')
    try:
        rel = os.path.relpath(p, base)
    except ValueError:                    # 跨盘符 (Windows)
        return p
    if rel not in ('.', '..') and not rel.startswith('..' + os.sep):
        return rel.replace(os.sep, '/')
    return p


def cert_status(cert, rules=None):
    """这份证书有没有"落地" → (是否落地, 说明)

    落地 = 它覆盖的每个站点都命中一条 tls 规则。光把证书放进 extra/ 不再是
    生效条件了 —— 不提示的话, 用户会以为"放了就行", 而现象只是"还是报证书错误"。
    """
    rules = tls_rules() if rules is None else rules
    if cert.get('error'):
        return False, cert['error']
    if not cert.get('sites'):
        return False, '证书里读不出任何域名 (CA 证书? 需要手写 match)'
    unlanded = []
    for h in cert['sites']:
        rp = rule_params('https://%s/' % h)
        if not rp.get('ca') and 'verify' not in rp:
            unlanded.append(h)
    if unlanded:
        return False, (f'{len(unlanded)}/{len(cert["sites"])} 个域名没有 tls 规则'
                       f' (如 {unlanded[0]})')
    return True, '已按站点配进规则表'


def policy(url=None, verify=None):
    """该 URL 该怎么验证书 → False / '<CA 路径>'

    校验开着时返回**解析好的 CA 路径**而不是 True: curl_cffi 与 requests 见到
    True 会各自去读 REQUESTS_CA_BUNDLE / CURL_CA_BUNDLE, 三通道就可能用三套
    信任根; 显式给路径则完全由本模块说了算。

    verify=None 表示"按配置来"; 传 True/False 则无视配置直接决定
    (调用方显式意图优先, 例如某个已知自签接口的定点豁免)。**传 CA 文件路径**
    等价于 requests 的 `verify=<ca>`: 用它当信任根、开启校验。

    优先级: verify= 参数 > tls 规则 > verify_hosts > ssl_verify 总开关。
    环境无任何 CA 包时自动降级为 False (理由见 _probe_ca) —— 这种情况下
    严格校验等于全线不可用, 且报错完全指不到根因。
    """
    # 调用方直接给 CA 路径 (requests 的 verify=<ca.pem> 语义): 拿它当信任根
    if isinstance(verify, str) and verify.strip():
        _s = verify.strip()
        if _s not in _TRUTHY and _s not in _FALSY:
            return _s
    host = host_of(url)
    on, ca, hosts = _load()
    if verify is not None:
        # 调用方显式表态 (verify=False: 某个已知自签接口的定点豁免; verify=True:
        # 强制校验) —— 规则不参与。规则在这里插一杠子的话, 老代码"我知道这个
        # 接口是自签的"会被悄悄改成"按规则校验", 表现成同一个接口有时通有时不通。
        on = _as_bool(verify)
    else:
        rp = rule_params(url)
        if rp.get('ca'):
            # 规则点名了信任根: 校验开着, 且用"基础 CA + 该站证书"
            return _scoped_ca(rp['ca'], host)
        if 'verify' in rp:
            on = _rule_bool(rp['verify'], host)
        elif url and hit_insecure(host, hosts):
            on = False
    if not on:
        return False
    return ca or _system_ca() or False


def _rule_bool(v, host=''):
    """规则里的 verify 值 → bool。写错值当场报出来, 不静默当成"没表态"

    静默忽略最坏: 用户写了 `verify: "false"` 之外的拼写 (比如 `verify: "no!"`),
    校验照开、站点照报错, 而规则看上去"配了"。
    """
    try:
        return _as_bool(v)
    except TlsConfigError:
        raise TlsConfigError(
            f'rules.json 的 tls 规则 (域名 {host or "?"}) verify={v!r} 认不出; '
            f'只认 on/off (写成 true/false、1/0、yes/no 也认)') from None


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
         '把该站证书丢进 ~/.webtool/certs/extra/, 再跑 webtool proxy cert sync '
         '(按站点把信任根配进规则表); 或 webtool config set verify_hosts <域名>'),
    19: ('自签证书 (链内自签)',
         '同上: 证书放 ~/.webtool/certs/extra/ 后跑 webtool proxy cert sync, '
         '或 verify_hosts 点名'),
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
    # 站点证书: 放进 extra/ 只是"备着", 生效要有一条点名该站点的 tls 规则。
    # 这一条必须看得见, 否则现象只是"某站还是报证书错误", 与"没放证书"无异。
    certs = site_certs()
    if certs:
        rows = []
        for c in certs:
            landed, note = cert_status(c)
            rows.append({'name': c['name'], 'sites': c['sites'],
                         'landed': landed, 'note': note})
        out['site_certs'] = rows
        bad = [x['name'] for x in rows if not x['landed']]
        if bad:
            note = ('站点证书还没配进规则表 (%s): 光放进 extra/ 不会生效。'
                    '修: webtool proxy cert sync' % ', '.join(bad))
            out['warning'] = (out['warning'] + ' ' + note) if out.get('warning') else note
    return out