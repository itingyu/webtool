"""代理路由规则: 按域名 / IP / 端口 / 协议 / GeoIP 决定走不走代理、走哪个

## 为什么按请求目标分流, 而不是按引擎名

按**引擎名**分流 (google 走代理, exa 走直连) 的粒度是代码里写死的插件名, 而真实
需求是按**请求目标**分流: 同一个引擎里境外站走代理、境内站直连; 或者某个 CDN 子域
走另一条线路。规则要能看 URL 才能判 —— 所以线路只有一个决策点: 这份规则表。

## 规则格式 (`~/.webtool/rules.json`, 或 config.json 的 proxy_rules 段)

```jsonc
{
  "default": "direct",              // 未命中时的动作
  "rules": [
    {"match": {"domain": ["*.cn", "baidu.com"]}, "action": "direct"},
    {"match": {"domain_suffix": ".googlesource.com"}, "action": "proxy:tokyo"},
    {"match": {"cidr": ["10.0.0.0/8", "192.168.1.1"]}, "action": "direct"},
    {"match": {"port": [443, 8443]}, "action": "proxy"},
    {"match": {"scheme": ["http"]}, "action": "direct"},
    {"match": {"geoip": ["CN", "HK"]}, "action": "direct"},
    {"match": {"asn": [15169]}, "action": "proxy"},
    {"match": {"domain": ["api.anthropic.com"]},
     "action": "proxy", "name": "外网必走"}
  ],
  "proxies": {
    "tokyo": {"url": "socks5://127.0.0.1:1081"},
    "direct": null
  }
}
```

- **自上而下, 第一个命中的规则生效** (顺序即优先级)
- `action`: `direct`(直连) / `block`(拒绝, 不发请求) / `proxy`(用全局代理)
  / `proxy:<名>`(用命名代理)
- `match` 内多个条件是 **AND**; 同一条件内多个值是 **OR**
- `*.cn` 匹配 `a.cn` 与 `a.b.cn`; 无 `*` 的按**后缀**匹配 (裸 `cn` 不生效,
  免得误伤 `example.com.cn` 之外的一切)

## GeoIP / ASN 库

`geoip_db` / `asn_db` 指向 MaxMind `.mmdb` 文件 (读库用 maxminddb, 可选依赖)。
没配或没装 → 带 `geoip`/`asn` 条件的规则**跳过并给出明确提示**, 而不是
悄悄当成不匹配 (那会让用户以为规则生效了)。域名要先解析出 IP 才能查
GeoIP, 所以 **DNS 结果带进程内缓存** (TTL 由 `--proxy-dns-ttl` 或配置控制,
默认 300s), 免得每请求都打一次 DNS。
"""
import fnmatch
import ipaddress
import json
import os
import socket
import time
from urllib.parse import urlsplit

# 进程内 DNS 缓存: 域名 → (ip, 解析时刻)
_DNS_CACHE = {}
DNS_TTL = 300.0
# GeoIP 查表缓存: ip → 国家码 (GeoIP 数据几乎不变, 缓存久一点没问题)
_GEO_CACHE = {}

VALID_ACTIONS = ('direct', 'proxy', 'block')


class RuleError(RuntimeError):
    """规则配置非法"""


# ---------------------------------------------------------------- 动作解析

def resolve_action(action):
    """'proxy:tokyo' → ('proxy', 'tokyo'); 'direct' → ('direct', None)"""
    if action in (None, ''):
        return 'direct', None
    a = str(action)
    if a.startswith('proxy:'):
        return 'proxy', a.split(':', 1)[1].strip()
    if a not in VALID_ACTIONS:
        raise RuleError(
            f'未知动作: {a}\n合法值: direct / proxy / block / proxy:<名字>')
    return a, None


# ---------------------------------------------------------------- 匹配器

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


# ---------------------------------------------------------------- DNS / GeoIP

# ------------------------------------------------------- 新规则覆盖试算

def _beats(a, b, priority):
    """动作 a 的规则压得住动作 b 的规则吗（用于"新规则会不会被吃掉"试算）"""
    if a == 'block':
        return True                       # 显式拒绝最高优先, 直连也压得住
    if b == 'block':
        return False
    if priority == 'order':
        return True                       # 顺序机制下, 排在前面就赢
    return a == 'direct' and b != 'direct'


def shadow_check(router, match, action, index):
    """新规则插到 `index` 后, 会不会被前面的规则**完全**吃掉

    返回 (序号, 动作) 或 None。这是**试算不是证明**: 只对纯域名规则
    (domain / domain_suffix) 生效, 拿每个后缀本身和一个二级探针域名去撞
    前面的规则, 全部撞中才算覆盖。带 port/scheme/cidr 的规则一律不猜,
    宁可不报也不误报。
    """
    if not match or set(match) - {'domain', 'domain_suffix'}:
        return None
    doms = []
    for key in ('domain', 'domain_suffix'):
        v = match.get(key)
        doms += v if isinstance(v, list) else ([v] if v else [])
    probes = []
    for pat in doms:
        base = str(pat).lower().strip().lstrip('.')
        if base.startswith('*.'):
            base = base[2:]
        if not base:
            return None
        probes += [base, 'zz-probe.' + base]      # 后缀本体 + 一个子域
    try:
        verb, _ = resolve_action(action)
    except RuleError:
        return None
    for i, r in enumerate(router.rules[:index]):
        if not isinstance(r, dict):
            continue
        try:
            act_i, _ = resolve_action(r.get('action'))
        except RuleError:
            continue
        if not _beats(act_i, verb, router.priority):
            continue
        m = r.get('match') or {}
        if all(router._match(m, h, None, 'https', _IPRef(h)) for h in probes):
            return i, act_i
    return None


# ---------------------------------------------------------------- URL 解析

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
            self._ip = resolve_ip(self.host)
            self._done = True
        return self._ip


def resolve_ip(host, timeout=3.0):
    """域名 → IP (带进程内缓存)。已是 IP 直接返回。"""
    if not host:
        return None
    try:
        ipaddress.ip_address(host)
        return host                       # 本来就是 IP
    except ValueError:
        pass
    now = time.time()
    hit = _DNS_CACHE.get(host)
    if hit and now - hit[1] < DNS_TTL:
        return hit[0]
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
        ip = infos[0][4][0]
    except (socket.gaierror, OSError, IndexError):
        ip = None
    _DNS_CACHE[host] = (ip, now)          # 负缓存也缓存, 防反复打 DNS
    return ip


_MMDB = {}


def _reader(path):
    """mmdb 读取器缓存 (同一路径只开一次)"""
    if not path:
        return None
    p = os.path.expanduser(str(path))
    if p in _MMDB:
        return _MMDB[p]
    try:
        import maxminddb
    except ImportError:
        _MMDB[p] = None                   # 没装: 缓存 None, 别反复 import 失败
        return None
    if not os.path.isfile(p):
        _MMDB[p] = None
        return None
    try:
        r = maxminddb.open_database(p)
    except Exception:
        _MMDB[p] = None
        return None
    _MMDB[p] = r
    return r


def geoip_country(ip, db_path):
    """IP → 国家码 ('CN'/'US'), 查不到返回 None。两种库都吃:
    MaxMind 的 .mmdb, 以及 v2ray/sing-box 的 geoip.dat (protobuf)。"""
    if not ip or not db_path:
        return None
    ck = (db_path, ip)
    if ck in _GEO_CACHE:
        return _GEO_CACHE[ck]
    from webtool.net import geodata as _gd
    out = _gd.country_of_ip(ip, db_path)
    _GEO_CACHE[ck] = out
    return out


def geoip_asn(ip, db_path):
    """IP → ASN 号, 查不到返回 None"""
    if not ip or not db_path:
        return None
    r = _reader(db_path)
    if r is None:
        return None
    try:
        rec = r.get(ip)
        if rec:
            return rec.get('autonomous_system_number')
    except Exception:
        return None
    return None


# ---------------------------------------------------------------- 规则引擎

class Router:
    """按规则表决定某个 URL 该走哪条线路"""

    def __init__(self, spec, geoip_db=None, asn_db=None, default_proxy=None,
                 geosite_db=None):
        """spec: {'default': ..., 'rules': [...], 'proxies': {...}}"""
        spec = spec or {}
        self.rules = spec.get('rules') or []
        self.proxies = spec.get('proxies') or {}
        self.geoip_db = geoip_db
        self.asn_db = asn_db
        # geosite 是**按域名分类**的库。判 geoip 规则时优先用它: "这域名算不算
        # CN" 不用解析 IP, 也就不会被 CDN 就近解析把 IP 判到别国去
        self.geosite_db = geosite_db
        # spec 没显式写 default 时: 有全局 proxy 就沿用它, 否则直连。
        # 绝不能无条件当 'direct' —— 用户只配了 proxy 没配规则时, 那台代理
        # 会被静默忽略, google/docs.rsshub.app 这类必须代理的目标直接连不通,
        # 而且现象是"没走代理"而不是任何报错。
        if 'default' in spec:
            self.default_action, _ = resolve_action(spec['default'])
        else:
            self.default_action = 'proxy' if default_proxy else 'direct'
        self.default_proxy = default_proxy
        self.warnings = []      # 配置问题累积 (比如 geoip 库没配)
        # 命中策略:
        #   direct —— **direct 规则优先**: 任一条匹配规则是 direct 就用它, 不受前面
        #             更宽的 proxy 规则阻挡; block 例外(deny > allow)
        #   order  —— 老口径: 纯 first-match-wins, 文件里谁在前谁生效
        # 写错的取值一律退回 direct 并告警, 不静默当 order —— 那等于用户
        # 以为自己开了 direct 规则优先, 实际还是顺序优先, 排查毫无线索。
        prio = str(spec.get('priority') or 'direct').lower()
        if prio not in ('direct', 'order'):
            self.warnings.append(f"priority 取值 '{prio}' 无效, 按 'direct' 处理")
            prio = 'direct'
        self.priority = prio
        for i, r in enumerate(self.rules):
            # 规则是用户手写的 JSON, 混进一个字符串/数字是完全正常的编辑事故。
            # 这里必须逐条跳过而不是让 r.get() 抛 AttributeError —— 后者会让
            # "第 3 条少了个引号"变成整个工具启动即崩, 且报错完全指不到配置。
            if not isinstance(r, dict):
                self.warnings.append(f'rules[{i}] 不是对象, 已跳过')
                continue
            if not isinstance(r.get('match'), dict) or not r.get('match'):
                self.warnings.append(f'rules[{i}] 缺 match 段, 已跳过')
            try:
                resolve_action(r.get('action'))
            except RuleError as e:
                self.warnings.append(f'rules[{i}] {e}')

    def rule(self, url):
        """URL → (action, proxy_name, 命中的规则序号 或 None)

        命中策略见 `self.priority`（rules.json 顶层 `"priority"`）：
        `direct` 时 direct 规则优先，前面的宽 proxy 规则压不过后面的 direct 规则。
        """
        host, port, scheme = _split_url(url)
        ip_ref = _IPRef(host)
        first = None                    # 第一条命中的 (priority=order 就用它)
        direct = block = None           # 直连 / 拦截候选
        for i, r in enumerate(self.rules):
            if not isinstance(r, dict):
                continue
            m = r.get('match')
            if not isinstance(m, dict) or not m:
                continue
            if not self._match(m, host, port, scheme, ip_ref):
                continue
            try:
                act, name = resolve_action(r.get('action'))
            except RuleError:
                # 动作非法的规则在 __init__ 里已经警告过, 这里跳过继续往下
                # 找。让它抛出去的话, 一条手写错的规则会让**所有**请求
                # 全挂, 而不是"这一条没生效" —— 故障范围差着量级。
                continue
            if first is None:
                first = (act, name, i)
            if act == 'block':
                block = (act, name, i)
                break               # deny 最高优先, 后面不必再扫
            if act == 'direct' and direct is None:
                direct = (act, name, i)
        if block:
            return block
        if direct and self.priority != 'order':
            return direct
        return first or (self.default_action, None, None)

    def matched(self, url):
        """所有命中规则 [(序号, 动作字符串)], 文件顺序。

        给 `explain` 用: 只有把"匹配了但没生效"的也列出来, 用户才能看出
        自己写的规则是被 direct 规则优先压掉了, 而不是没匹配上 —— 这两者
        只报最终命中项时长得一模一样。
        """
        host, port, scheme = _split_url(url)
        ip_ref = _IPRef(host)
        out = []
        for i, r in enumerate(self.rules):
            if not isinstance(r, dict):
                continue
            m = r.get('match')
            if not isinstance(m, dict) or not m:
                continue
            if self._match(m, host, port, scheme, ip_ref):
                out.append((i, str(r.get('action'))))
        return out

    def _match(self, m, host, port, scheme, ip_ref):
        """match 各条件 AND; 需要 IP 的条件惰性求值 (避免无谓 DNS)"""
        if 'domain' in m and not any(_domain_match(host, d)
                                    for d in _as_list(m['domain'])):
            return False
        if 'domain_suffix' in m and not any(
                _domain_match(host, d) for d in _as_list(m['domain_suffix'])):
            return False
        if 'host' in m and not any(_glob_match(host, d)
                                   for d in _as_list(m['host'])):
            return False
        if 'port' in m and not _port_match(port, m['port']):
            return False
        if 'scheme' in m and not _scheme_match(scheme, m['scheme']):
            return False
        if 'cidr' in m and not _cidr_match(ip_ref(), m['cidr']):
            return False
        if 'ip' in m and not _cidr_match(ip_ref(), m['ip']):
            return False
        if 'geosite' in m:
            if not self.geosite_db:
                _warn_once(self.warnings, 'geosite',
                           '规则用到 geosite 但没配 geosite_db, 该条规则不生效 '
                           '(配 webtool proxy geosite <geosite.dat>)')
                return False          # 判不了 = 不匹配 (不是"跳过当通过")
            from webtool.net import geodata as _gd
            if not any(_gd.domain_in_category(host, str(c), self.geosite_db)
                       for c in _as_list(m['geosite'])):
                return False
        if 'geoip' in m:
            want = {str(x).upper() for x in _as_list(m['geoip'])}
            # 优先用 geosite 按域名判 (免 DNS、不受 CDN 就近解析影响);
            # 没配 geosite 才回落到解析 IP 查 geoip 库
            if self.geosite_db and host:
                from webtool.net import geodata as _gd
                if any(_gd.domain_in_category(host, c, self.geosite_db)
                       for c in want):
                    return True
                # 域名分类判完没命中, 仍继续走 IP 判定 (两库可互补)
            if not self.geoip_db:
                _warn_once(self.warnings, 'geoip',
                           '规则用到 geoip 但没配 geoip_db/geosite_db, '
                           '该条规则不生效 (配 webtool proxy geoip <库>)')
                return False
            cc = geoip_country(ip_ref(), self.geoip_db)
            if cc is None or str(cc).upper() not in want:
                return False
        if 'asn' in m:
            if not self.asn_db:
                _warn_once(self.warnings, 'asn',
                           '规则用到 asn 但没配 asn_db, 该条规则不生效 '
                           '(配 webtool proxy asn <GeoLite2-ASN.mmdb>)')
                return False          # 同上: 判不了 = 不匹配, 不是"通过"
            if not _asn_match(geoip_asn(ip_ref(), self.asn_db), m['asn']):
                return False
        return True

    def proxy_for(self, url):
        """URL → 实际代理 URL (None=直连), 这是给上层用的主入口"""
        act, name, idx = self.rule(url)
        if act == 'direct':
            return None
        if act == 'block':
            raise RuleError(f'规则拦截: {url}')
        if act == 'proxy':
            if name:
                spec = self.proxies.get(name)
                if spec is None and name not in self.proxies:
                    raise RuleError(f'规则引用了未定义的代理: {name}')
                return (spec or {}).get('url') if isinstance(spec, dict) else spec
            return self.default_proxy
        return None

    def explain(self, url):
        """给 CLI 看: 命中了哪条规则, 最终走哪条线路"""
        act, name, idx = self.rule(url)
        if act == 'proxy' and name:
            spec = self.proxies.get(name) or {}
            target = spec.get('url') if isinstance(spec, dict) else spec
        elif act == 'proxy':
            target = self.default_proxy
        else:
            target = None
        out = {
            'url': url,
            'action': act,
            'proxy_name': name,
            'rule_index': idx,
            'rule': self.rules[idx] if idx is not None else None,
            'resolved_proxy': _mask(target),
            'priority': self.priority,
        }
        hits = self.matched(url)
        if hits:
            out['matched'] = [{'index': i, 'action': a, 'effective': i == idx}
                              for i, a in hits]
        # 有命中但没生效的 —— 要么被 direct 规则优先压掉, 要么被靠前的先吃掉。
        # 不点出来的话, 用户看着跟自己写的规则"没匹配上"是一回事。
        for i, a in hits:
            if i == idx:
                continue
            if self.priority != 'order' and act == 'direct' and a.startswith('proxy'):
                out['note'] = (f"规则[{i}] ({a}) 也匹配, 但规则[{idx}] 是 direct: "
                               f"priority=direct 下 direct 规则压过 proxy 规则")
            else:
                out.setdefault('note', (f"规则[{i}] ({a}) 也匹配, 未生效: "
                                        f"规则[{idx}] 在先 / 优先级更高"))
            break
        return out


def _warn_once(warnings, key, msg):
    """同一条规则只警告一次: Router 是每请求现算的, 不去重会被刷屏"""
    if key in _WARNED:
        return
    _WARNED.add(key)
    warnings.append(msg)


_WARNED = set()


def _as_list(v):
    return v if isinstance(v, (list, tuple)) else [v]


def _mask(url):
    """出口处统一脱敏: 万一有带密码的 URL 漏进来, 也不至于打进日志"""
    from webtool.core.secrets_store import redact
    return redact(url)


def migrate_plaintext_proxies(spec, cfg_path=None):
    """把规则表 proxies 段里的**明文密码**迁进保险库, 返回 (spec, 迁移条数)

    命名代理的 URL 写在 rules.json 里, 而 rules.json 是要人工编辑的文件 ——
    密码写在里面就是明文落盘, 与 proxy_auth 保险库那套机制割裂了。这里在
    加载时顺手迁移: 密码存进 config.json 的 proxy_auth (密文), rules.json
    只留 `user@host`, 出网时由 resolve_auth 补回 (上层两条通道都调它)。

    幂等: 迁完再读不会重复处理。没装 cryptography 时原样返回 —— 不能因为
    加密依赖缺失就让用户的规则彻底跑不起来, 那比明文更糟。
    """
    from webtool.core import secrets_store as _S
    from webtool.net.proxy import proxy_url_parts
    proxies = (spec or {}).get('proxies')
    if not isinstance(proxies, dict) or not _S.have_crypto():
        return spec, 0
    n = 0
    for name, entry in proxies.items():
        url = entry.get('url') if isinstance(entry, dict) else entry
        if not url or not isinstance(url, str):
            continue
        scheme, user, password, host, port = proxy_url_parts(url)
        if not password:
            continue                    # 已是 user@host, 无需迁移
        try:
            _S.store_password(user, password)
        except Exception:
            continue                    # 存不进去就保持原样, 不丢配置
        clean = (f'{scheme}://{user}@{host}' + (f':{port}' if port else ''))
        if isinstance(entry, dict):
            entry['url'] = clean
        else:
            proxies[name] = clean
        n += 1
    if n and cfg_path and os.path.isfile(cfg_path):
        try:
            with open(cfg_path, 'w', encoding='utf-8') as f:
                json.dump(spec, f, ensure_ascii=False, indent=2)
            os.chmod(cfg_path, 0o600)
        except OSError:
            pass
    return spec, n


def load_router(cfg):
    """从配置构造 Router。规则来源: proxy_rules (内联) 或 rules_file (文件)"""
    spec = cfg.get('proxy_rules')
    rules_path = None
    if not spec:
        path = _rules_file_of(cfg)
        if os.path.isfile(path):
            rules_path = path
            try:
                with open(path, encoding='utf-8') as f:
                    spec = json.load(f)
            except (ValueError, OSError) as e:
                # 规则文件坏了不能整个工具瘫掉: 退回"用全局 proxy 或直连",
                # 但把原因挂出来 (不能退回纯直连, 那会让必须代理的目标连不通)
                return _broken_router(f'规则文件读取失败: {path}: {e}',
                                      cfg.get('proxy'))
    spec, _migrated = migrate_plaintext_proxies(spec, rules_path)
    return Router(spec or {},
                  geoip_db=cfg.get('geoip_db'),
                  asn_db=cfg.get('asn_db'),
                  geosite_db=cfg.get('geosite_db'),
                  default_proxy=cfg.get('proxy'))


_router_cache = (None, None)


def _cfg_stamp(cfg):
    """配置文件 + 规则文件的指纹, 任一变了就重建 Router"""
    import webtool.net.proxy as _px
    st = []
    for p in (_px.CONFIG_PATH, _rules_file_of(cfg)):
        try:
            s = os.stat(p)
            st.append((p, s.st_mtime_ns, s.st_size))
        except OSError:
            st.append((p, 0, 0))
    return tuple(st)


def _rules_file_of(cfg):
    p = (cfg or {}).get('rules_file')
    if p:
        return os.path.expanduser(p)
    from webtool.core.config_data import USER_DIR
    return str(USER_DIR / 'rules.json')


def router(cfg=None):
    """带缓存的 Router: 每个请求都会问一次路由, 重建不能太贵"""
    global _router_cache
    if cfg is None:
        from webtool.net.proxy import load_config
        cfg = load_config()
    stamp = _cfg_stamp(cfg)
    if _router_cache[0] == stamp and _router_cache[1] is not None:
        return _router_cache[1]
    _router_cache = (stamp, load_router(cfg))
    return _router_cache[1]


def resolve_route(url, cfg=None, engine=None):
    """请求链路入口: URL → 该走的代理 URL (None = 直连)

    这是让规则真正生效的那一刀。调用方把 proxy 传成 'auto' 即可接入, 语义:
      'auto'   问路由 (默认动作/规则/命名代理)
      None     直连 (老代码显式要直连, 保持不变)
      'direct' 强制直连
      <url>    强制走这条 (老代码显式指定, 保持不变)

    只有 'auto' 会查规则 —— 这样既接上了新能力, 又完全不改变现有调用方的行为。
    """
    r = router(cfg)
    try:
        return r.proxy_for(url)
    except RuleError:
        raise
    except Exception:
        # 路由本身出错不能连带把正常请求搞挂, 退回直连
        return None


def explain_route(url, cfg=None):
    """试算: 返回命中了哪条规则、最终走哪条线 (不真正发请求)"""
    return router(cfg).explain(url)


class _broken_router:
    """规则文件坏了也要能跑: 全部走默认, 但把原因挂在 warnings 上"""

    def __init__(self, msg, default_proxy=None):
        self.rules, self.proxies = [], {}
        self.geoip_db = self.asn_db = None
        self.default_action = 'proxy' if default_proxy else 'direct'
        self.default_proxy = default_proxy
        self.warnings = [msg]

    def rule(self, url):
        return self.default_action, None, None

    def proxy_for(self, url):
        return self.default_proxy

    def explain(self, url):
        return {'url': url, 'action': self.default_action, 'proxy_name': None,
                'rule_index': None, 'rule': None,
                'resolved_proxy': _mask(self.default_proxy)}