"""匹配器: 域名 / 端口 / 协议 / CIDR / glob / ASN 五类条件 + URL 解析

纯函数, 不碰 Router 状态; 供 router 的 _match 与 tidy 的覆盖面推算共用。
"""
import fnmatch
import ipaddress
from urllib.parse import urlsplit


def _as_list(v):
    return v if isinstance(v, (list, tuple)) else [v]


def _domain_match(host, pattern):
    """支持两种写法: *.cn (含子域) / 裸后缀 (也含子域)"""
    if not host or not pattern:
        return False
    host = host.lower().rstrip('.')
    p = str(pattern).lower().strip().lstrip('.')
    if not p:
        return False
    if p.startswith('*.'):
        base = p[2:]
        return host == base or host.endswith('.' + base)
    return host == p or host.endswith('.' + p)


def _port_match(port, spec):
    """端口匹配: 80 / '80' / '8000-8100' / [80, 443] / '80,443,8000-8100'"""
    if port is None:
        return False
    ports = spec if isinstance(spec, (list, tuple)) else [spec]
    for p in ports:
        p = str(p).strip()
        if not p:
            continue
        if '-' in p:
            lo, _, hi = p.partition('-')
            try:
                if int(lo) <= port <= int(hi):
                    return True
            except ValueError:
                continue
        else:
            try:
                if port == int(p):
                    return True
            except ValueError:
                continue
    return False


def _scheme_match(scheme, spec):
    schemes = spec if isinstance(spec, (list, tuple)) else [spec]
    return scheme in {str(s).lower() for s in schemes}


def _cidr_match(ip, spec):
    """ip 是否落在任一 CIDR/单 IP 里。域名传进来先不解析 (纯域名规则不该触发 DNS)"""
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    nets = spec if isinstance(spec, (list, tuple)) else [spec]
    for n in nets:
        try:
            if '/' in str(n):
                if addr in ipaddress.ip_network(str(n), strict=False):
                    return True
            elif addr == ipaddress.ip_address(str(n)):
                return True
        except ValueError:
            continue
    return False


def _glob_match(value, pattern):
    return fnmatch.fnmatch(str(value).lower(), str(pattern).lower())


def _asn_match(asn, spec):
    if asn is None:
        return False
    want = spec if isinstance(spec, (list, tuple)) else [spec]
    for a in want:
        try:
            if str(int(a)) == str(asn):
                return True
        except (TypeError, ValueError):
            if str(a) == str(asn):
                return True
    return False


# ── URL 解析 ─────────────────────────────────────────────────────

_DEFAULT_PORTS = {'http': 80, 'https': 443, 'ws': 80, 'wss': 443}


def _split_url(url):
    """URL → (host, port, scheme)。解析不出来给 ('', None, 'http')

    URL 不写端口时补上 scheme 的默认端口 (http 80 / https 443) —— 规则里写
    `{"port": [443]}` 的本意就是"https 流量", 若 port 只认显式端口, 这条规则
    对 `https://host/` 永远不生效, 且不报错, 是条查不出来的死规则。
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return '', None, 'http'
    scheme = (parts.scheme or 'http').lower()
    try:
        port = parts.port
    except ValueError:
        port = None                      # 端口写了非数字, 当没写
    if port is None:
        port = _DEFAULT_PORTS.get(scheme)
    return (parts.hostname or ''), port, scheme


class _IPRef:
    """惰性 DNS —— 只有真的用到 IP 类条件时才解析, 一次扫描内只解析一次"""

    def __init__(self, host):
        self.host, self._done, self._ip = host, False, None

    def __call__(self):
        if not self._done:
            from webtool.net.rules.geodb import resolve_ip
            self._ip = resolve_ip(self.host)
            self._done = True
        return self._ip


# ── 域名模式归一 (tidy 用) ───────────────────────────────────────

def _norm_pat(pat):
    """域名模式归一: 去前导 '*.' 与点, 小写 —— `*.cn` 与 `cn` 是同一个东西"""
    p = str(pat or '').lower().strip().lstrip('.').rstrip('.')
    return p[2:] if p.startswith('*.') else p


def _pat_covers(broad, narrow):
    """broad 模式是否完全覆盖 narrow (含子域语义, 与 _domain_match 一致)"""
    b, n = _norm_pat(broad), _norm_pat(narrow)
    return bool(b) and bool(n) and (n == b or n.endswith('.' + b))


def _is_domain_only(match):
    """只带 domain 的规则才参与合并/裁剪 —— 混了 port/cidr 的规则一改就可能
    改变语义 (不同 key 之间是 AND, 但覆盖面推算要按集合乘积做, 不值当)"""
    m = match if isinstance(match, dict) else {}
    return bool(m) and set(m) <= {'domain', 'domain_suffix'}


def _domains_of(match):
    out = []
    for key in ('domain', 'domain_suffix'):
        v = (match or {}).get(key)
        out += v if isinstance(v, list) else ([v] if v else [])
    return [str(x) for x in out if str(x or '').strip()]
