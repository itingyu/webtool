"""代理路由规则: 按域名 / IP / 端口 / 协议 / GeoIP 决定走不走代理、走哪个

分流粒度是**请求目标** (域名/IP/端口/协议/GeoIP), 不是引擎名 —— 同一个引擎里
境内站直连、境外站走代理是常态, 只有拿到 URL 才判得出来。线路只有这一个决策点。

## 规则格式 (`~/.webtool/rules.json`, 或 config.json 的 rules_file 指向的文件)

```jsonc
{
  "default": "proxy:default",       // 未命中时的动作 (direct / block / proxy:<名>)
  "rules": [
    {"match": {"domain": ["*.cn", "baidu.com"]}, "action": "direct"},
    {"match": {"domain_suffix": ".googlesource.com"}, "action": "proxy:tokyo"},
    {"match": {"cidr": ["10.0.0.0/8", "192.168.1.1"]}, "action": "direct"},
    {"match": {"port": [443, 8443]}, "action": "proxy:default"},
    {"match": {"scheme": ["http"]}, "action": "direct"},
    {"match": {"geoip": ["CN", "HK"]}, "action": "direct"},
    {"match": {"asn": [15169]}, "action": "proxy:tokyo"}
  ],
  "proxies": {
    "default": "socks5://127.0.0.1:1081",   // "默认代理", proxy:<名> 可引用
    "tokyo": {"url": "socks5://127.0.0.1:1081"}
  },
  "geoip_db": "/path/GeoLite2-Country.mmdb", // 库路径写在这, 规则与依赖同文件
  "geosite_db": null,
  "asn_db": null
}
```

- **自上而下, 第一个命中的规则生效** (顺序即优先级; block 例外, 见下)
- `action`: `direct`(直连) / `block`(拒绝, 不发请求) / `proxy:<名>`(用命名代理);
  裸 `proxy` 等价 `proxy:default`
- `match` 内多个条件是 **AND**; 同一条件内多个值是 **OR**
- `*.cn` 匹配 `a.cn` 与 `a.b.cn`; 无 `*` 的按**后缀**匹配 (裸 `cn` 不生效,
  免得误伤 `example.com.cn` 之外的一切)
- 旧版 `priority` 键已废弃: 一律按文件顺序生效, direct 规则想优先就写在前面

## 其他环节的规则 (kind 条目)

带 `kind` 字段的条目不参与线路路由, 按环节生效 (`Router.params_for(kind, url)`,
first-match-wins, 无命中走该环节的通用默认): `http` (timeout/fingerprint)、
`retry` (retries/backoff)、`breaker` (fail_threshold/cool_seconds)。match 语法
与线路规则完全一致, 粒度一般按域名配。

## GeoIP / ASN 库

`geoip_db` / `asn_db` 指向 MaxMind `.mmdb` 文件 (读库用 maxminddb, 随包安装)。
没配或没装 → 带 `geoip`/`asn` 条件的规则**跳过并给出明确提示**, 不许静默按
不匹配处理。域名要先解析出 IP 才能查 GeoIP, DNS 结果带进程内缓存
(TTL 由 `--proxy-dns-ttl` 或配置控制, 默认 300s)。
"""
import fnmatch
import ipaddress
import json
import logging
import os
from urllib.parse import urlsplit

from webtool.net import dns as _dns

logger = logging.getLogger(__name__)
# GeoIP 查表缓存: ip → 国家码 (GeoIP 数据几乎不变, 缓存久一点没问题)
_GEO_CACHE = {}

VALID_ACTIONS = ('direct', 'proxy', 'block')


class RuleError(RuntimeError):
    """规则配置非法"""


# 动作解析

def resolve_action(action):
    """'proxy:tokyo' → ('proxy', 'tokyo'); 'direct' → ('direct', None)

    裸 'proxy' 归一成 ('proxy', 'default') —— "默认代理"是命名代理里的
    default 条目, 语义只有一种写法。"""
    if action in (None, ''):
        return 'direct', None
    a = str(action)
    if a.startswith('proxy:'):
        return 'proxy', a.split(':', 1)[1].strip() or 'default'
    if a == 'proxy':
        return 'proxy', 'default'
    if a not in VALID_ACTIONS:
        raise RuleError(
            f'未知动作: {a}\n合法值: direct / block / proxy:<名字>')
    return a, None


# 匹配器

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


# DNS / GeoIP

# 新规则覆盖试算

def shadow_check(router, match, action, index):
    """新规则插到 `index` 后, 会不会被前面的规则**完全**吃掉

    顺序机制下, 前面任意一条能命中探针域名的规则都会把它吃掉。返回
    (序号, 动作) 或 None。这是**试算不是证明**: 只对纯域名规则
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
        resolve_action(action)
    except RuleError:
        return None
    for i, r in enumerate(router.rules[:index]):
        if not isinstance(r, dict):
            continue
        try:
            act_i, _ = resolve_action(r.get('action'))
        except RuleError:
            continue
        m = r.get('match') or {}
        if all(router._match(m, h, None, 'https', _IPRef(h)) for h in probes):
            return i, act_i
    return None


# URL 解析

_DEFAULT_PORTS = {'http': 80, 'https': 443, 'ws': 80, 'wss': 443}


def seed_rules(spec, path=None):
    """规则表为空时, 把包内默认规则 (data/rules.json) 补进去

    为什么要有这一步: 默认规则表只在"存在代理"时才有意义 —— 它的作用是
    把国内站钉在直连上, 而没配代理时所有流量本来就直连 (此时规则是冗余的,
    `proxy tidy` 会建议删掉)。所以种子不在首次启动时落, 而是在 `proxy set`
    把默认动作切成代理的那一刻读模板补上。这样模板是唯一事实来源, 代码里
    不再存第二份规则清单。

    返回补进去的条数 (0 = 没动)。
    """
    import json
    if not isinstance(spec, dict) or spec.get('rules'):
        return 0
    p = path
    if p is None:
        try:
            from webtool.core.config_data import DATA_DIR
            p = DATA_DIR / 'rules.json'
        except Exception:
            return 0
    try:
        with open(p, encoding='utf-8') as f:
            tpl = json.load(f)
    except (OSError, ValueError):
        return 0
    rules = tpl.get('rules') if isinstance(tpl, dict) else None
    if not rules:
        return 0
    spec['rules'] = rules
    return len(rules)


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


def tidy_spec(spec):
    """合并/裁剪规则表: 同动作合并 + 冗余条目去除 + 与默认动作重复的规则去掉

    改动都建立在"语义等价或纯死重"上, 不做激进重写:
      - 同一规则内被更宽条目覆盖的 (opencode.ai 已覆盖 *.opencode.ai) → 删
      - 被前面规则完全覆盖的条目 (前面有 *.cn 时 *.sina.com.cn 永不生效) → 删
      - 仅含 domain、动作相同的规则 → 合成一条 (合并后若有中间规则被整条
        吃掉, 就不合, 只报出来)
      - 动作与 default 相同的规则恒为死规则 (命中与不命中结果一样) → 删除

    返回 (新 spec, 报告行列表)。纯函数, 不改传进来的 dict。
    """
    import copy
    spec = copy.deepcopy(spec) if isinstance(spec, dict) else {}
    rules = spec.get('rules') or []
    report = []
    default_action = spec.get('default') or 'direct'

    kept = []                    # [{'match':…, 'action':…, 'doms':[…] 或 None}]
    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            continue
        act = rule.get('action')
        match = rule.get('match') or {}
        if not _is_domain_only(match):
            kept.append({'rule': rule, 'act': act, 'doms': None, 'idx': i})
            continue
        doms = []
        for d in _domains_of(match):
            if _norm_pat(d) in [_norm_pat(x) for x in doms]:
                report.append(f'〔去重〕{d} 与前面的同一域名重复 → 删')
                continue
            # 同规则内被更宽条目覆盖
            broad = next((x for x in doms if _pat_covers(x, d)), None)
            if broad:
                report.append(f'〔去重〕{broad} 已覆盖 {d} → 删 {d}')
                continue
            doms.append(d)
        # 被前面的规则整条覆盖 → 永不生效
        dead_by = None
        for prev in kept:
            if not prev['doms']:
                continue
            if all(any(_pat_covers(p, d) for p in prev['doms']) for d in doms):
                dead_by = prev['idx']
                break
        if dead_by is not None and doms:
            report.append(f'〔死规则〕规则[{i}] 被规则[{dead_by}] 完全覆盖 '
                          f'(first-match-wins 下永不生效) → 删')
            continue
        if doms:
            kept.append({'rule': rule, 'act': act, 'doms': doms, 'idx': i})

    # 动作与默认一致 → 死规则 (命中/不命中结果相同)
    live = []
    dropped_default = []
    for k in kept:
        if k['doms'] is not None:
            try:
                a, nm = resolve_action(k['act'])
            except RuleError:
                live.append(k)
                continue
            d_act, _ = resolve_action(default_action)
            if a == d_act and (a != 'proxy' or nm == 'default'):
                # 前缀用〔同默认〕而不是〔死规则〕: 它确实是死规则, 但"与默认
                # 同结果"是很常见的写法 (写出来当文档), 全按死规则报会让
                # `proxy rules` 对新装的用户一直唠叨, 反而没人看告警。
                report.append(f'〔同默认〕规则[{k["idx"]}] 动作与默认动作 '
                              f'({default_action}) 相同 → 删')
                dropped_default.append(k['idx'])
                continue
        live.append(k)
    if dropped_default:
        report.append(f'〔提示〕上面删掉的规则与默认动作同结果, 线路由 default 决定;'
                      f' 以后若把 default 改成别的动作, 这些域名会跟着变 '
                      f'(原规则[{",".join(str(i) for i in dropped_default)}] 已在备份里)')

    # 同动作域名规则合并 (按位置保留最早那条)
    out_rules = []
    for k in live:
        if k['doms'] is None:
            out_rules.append((k, None))
            continue
        target = None
        for t in out_rules:
            if t[1] and t[0]['act'] == k['act']:
                # 合并会不会把夹在中间的异动作规则吃掉
                shadowed = None
                for mid in live:
                    if not (t[0]['idx'] < mid['idx'] < k['idx']) or not mid['doms']:
                        continue
                    try:
                        if resolve_action(mid['act'])[0] == resolve_action(k['act'])[0]:
                            continue
                    except RuleError:
                        continue
                    if all(any(_pat_covers(p, d) for p in t[0]['doms'] + k['doms'])
                           for d in mid['doms']):
                        shadowed = mid['idx']
                        break
                if shadowed is None:
                    target = t
                break
        if target:
            before = len(target[0]['doms'])
            merged = list(target[0]['doms'])
            for d in k['doms']:
                if any(_pat_covers(p, d) for p in merged):
                    report.append(f'〔去重〕{d} 被已合并的宽条目覆盖 → 删')
                    continue
                merged = [p for p in merged if not _pat_covers(d, p)]
                merged.append(d)
            target[0]['doms'] = merged
            report.append(f'〔合并〕规则[{k["idx"]}] → 规则[{target[0]["idx"]}] '
                          f'({k["act"]}, {before} → {len(merged)} 条)')
        else:
            out_rules.append((k, 'dommerged'))
    final = []
    for k, _ in out_rules:
        if k['doms'] is None:
            final.append(k['rule'])
            continue
        r = dict(k['rule'])
        match = dict(r.get('match') or {})
        match.pop('domain_suffix', None)
        match['domain'] = k['doms']
        r['match'] = match
        final.append(r)
    spec['rules'] = final
    if len(final) != len(rules):
        report.insert(0, f'规则条数 {len(rules)} → {len(final)}')
    return spec, report


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
    return _dns.resolve_ip(host)


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


# 规则引擎

class Router:
    """按规则表决定某个 URL 该走哪条线路"""

    def __init__(self, spec, geoip_db=None, asn_db=None, geosite_db=None):
        """spec: {'default': ..., 'rules': [...], 'proxies': {...}}"""
        spec = spec or {}
        self.spec = spec
        # kind 条目 (http/retry/breaker...) 与路由条目 (无 kind 字段) 分流:
        # 路由匹配不认识 kind 条目, 反过来 params_for 也不吃路由条目 ——
        # 同一份 rules.json, 两套用途互不干扰 (见 params_for)
        self.rules = [r for r in (spec.get('rules') or [])
                      if isinstance(r, dict) and not r.get('kind')]
        self.kind_rules = [r for r in (spec.get('rules') or [])
                           if isinstance(r, dict) and r.get('kind')]
        self.proxies = spec.get('proxies') or {}
        self.geoip_db = geoip_db
        self.asn_db = asn_db
        # geosite 是**按域名分类**的库。判 geoip 规则时优先用它: "这域名算不算
        # CN" 不用解析 IP, 也就不会被 CDN 就近解析把 IP 判到别国去
        self.geosite_db = geosite_db
        self.warnings = []      # 配置问题累积 (比如 geoip 库没配)
        # default 缺失时的推断只有一步, 且一定告警: 命名代理里有 "default"
        # 就拿它兜底, 否则直连。绝不静默猜一个方向 —— 用户以为的全局代理
        # 被忽略时, 现象是"没走代理"而不是任何报错, 排查毫无线索。
        if 'default' in spec:
            self.default_action, _ = resolve_action(spec['default'])
        elif 'default' in self.proxies:
            self.default_action, _ = resolve_action('proxy:default')
            self.warnings.append('rules.json 未写 default, '
                                 '按 proxies.default 兜底; 建议显式写')
        else:
            self.default_action, _ = 'direct', None
            self.warnings.append('rules.json 未写 default, 未命中规则一律直连; '
                                 '要走代理: webtool proxy set <url>')
        if 'priority' in spec:
            self.warnings.append("rules.json 的 'priority' 已废弃: "
                                 '规则一律按文件顺序生效, 请删掉该键')
        # 命中策略只有一种: 文件顺序, first-match-wins (block 例外: 显式拒绝
        # 最高优先, 命中即断)。旧版 priority=direct 的例外已删 —— 它让
        # "后面的 direct 压过前面的 proxy"成为隐藏规则, 一堆补丁机制
        # (shadow_check/matched/explain) 全在补救这个认知负担。
        self.priority = 'order'
        # 校验遍历**原始** rules (含 kind 条目与非对象项): 过滤后的 self.rules
        # 会把编辑事故静默吞掉 —— "第 3 条少了个引号"必须仍然报出来
        for i, r in enumerate(spec.get('rules') or []):
            # 规则是用户手写的 JSON, 混进一个字符串/数字是完全正常的编辑事故。
            # 这里必须逐条跳过而不是让 r.get() 抛 AttributeError —— 后者会让
            # "第 3 条少了个引号"变成整个工具启动即崩, 且报错完全指不到配置。
            if not isinstance(r, dict):
                self.warnings.append(f'rules[{i}] 不是对象, 已跳过')
                continue
            if r.get('kind'):
                continue                  # kind 条目不参与线路路由, 只查 match 合法性交由 params_for
            if not isinstance(r.get('match'), dict) or not r.get('match'):
                self.warnings.append(f'rules[{i}] 缺 match 段, 已跳过')
            try:
                resolve_action(r.get('action'))
            except RuleError as e:
                self.warnings.append(f'rules[{i}] {e}')

    def rule(self, url):
        """URL → (action, proxy_name, 命中的规则序号 或 None)

        文件顺序 first-match-wins; block 命中即断。"""
        host, port, scheme = _split_url(url)
        ip_ref = _IPRef(host)
        for i, r in enumerate(self.rules):
            if not isinstance(r, dict):
                continue
            m = r.get('match')
            if not isinstance(m, dict) or not m:                continue
            if not self._match(m, host, port, scheme, ip_ref):
                continue
            try:
                act, name = resolve_action(r.get('action'))
            except RuleError:
                # 动作非法的规则在 __init__ 里已经警告过, 这里跳过继续往下
                # 找。让它抛出去的话, 一条手写错的规则会让**所有**请求
                # 全挂, 而不是"这一条没生效" —— 故障范围差着量级。
                continue
            if act == 'block':
                return act, name, i      # 显式拒绝最高优先, 命中即断
            return act, name, i
        return self.default_action, resolve_action(self.default_action)[1], None

    def matched(self, url):
        """所有命中规则 [(序号, 动作字符串)], 文件顺序。

        给 `explain` 用: 只有把"匹配了但没生效"的也列出来, 用户才能看出
        自己的规则是被排在后面的规则压掉了, 而不是没匹配上 —— 这两者只报
        最终命中项时长得一模一样。
        """
        host, port, scheme = _split_url(url)
        ip_ref = _IPRef(host)
        out = []
        for i, r in enumerate(self.rules):
            if not isinstance(r, dict):
                continue
            m = r.get('match') or {}
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
        # act == 'proxy'; 裸 proxy 已在 resolve_action 归一成 default
        spec = self.proxies.get(name)
        if spec is None and name not in self.proxies:
            raise RuleError(
                f'规则引用了未定义的代理: {name}\n'
                f'现有: {", ".join(sorted(self.proxies)) or "(无)"}\n'
                f'处理: webtool proxy named add {name} <url>, '
                f'或把 default 显式配好')
        return (spec or {}).get('url') if isinstance(spec, dict) else spec

    def params_for(self, kind, url):
        """通用规则查询: 第一个 `kind` 命中条目的动作字段 (dict), 无命中 {}

        rules.json 里带 `kind` 的条目不参与线路路由, 按环节生效, 格式统一:

            {"kind": "http", "match": {"domain": "xueqiu.com"},
             "timeout": 15, "fingerprint": "chrome131"}
            {"kind": "retry", "match": {"domain": "sina.com.cn"},
             "retries": 5, "backoff": "exp"}

        返回该条目除 match/kind 外的全部字段; 匹配复用线路规则的 matcher
        (domain/host/port/scheme/cidr/geosite/geoip/asn)。**特殊走规则,
        否则走通用** —— 通用默认值住在各环节模块的顶部常量里, 不在这里。
        粒度随对象: 这类参数一般按域名配。
        """
        host, port, scheme = _split_url(url)
        ip_ref = _IPRef(host)
        for r in self.kind_rules:
            if r.get('kind') != kind:
                continue
            m = r.get('match') or {}
            if isinstance(m, dict) and self._match(m, host, port, scheme,
                                                   ip_ref):
                p = {k: v for k, v in r.items() if k not in ('match', 'kind')}
                logger.debug('rule[%s] 命中 %s: %s', kind, host, p)
                return p
        return {}

    def explain(self, url):
        """给 CLI 看: 命中了哪条规则, 最终走哪条线路"""
        act, name, idx = self.rule(url)
        if act == 'proxy':
            spec = self.proxies.get(name) or {}
            target = spec.get('url') if isinstance(spec, dict) else spec
        else:
            target = None
        out = {
            'url': url,
            'action': act,
            'proxy_name': name,
            'rule_index': idx,
            'rule': self.rules[idx] if idx is not None else None,
            'resolved_proxy': _mask(target),
        }
        hits = self.matched(url)
        if hits:
            out['matched'] = [{'index': i, 'action': a, 'effective': i == idx}
                              for i, a in hits]
            shadowed = [h for h in hits if h[0] != idx]
            if shadowed:
                out['note'] = (
                    f'规则[{shadowed[0][0]}] ({shadowed[0][1]}) 也匹配但未生效: '
                    f'规则[{idx}] 排在前面')
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
    加载时迁移: 密码存进 config.json 的 proxy_auth (密文), rules.json
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
            _S.store_password(f'{user}@{host}' + (f':{port}' if port else ''),
                              password)
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
    """从配置构造 Router。规则只来自 rules_file 指向的文件 (默认 rules.json);
    geoip/geosite/asn 库路径: 文件里的值优先, config.json 里的作回落"""
    spec = _load_spec(cfg)
    if isinstance(spec, _BrokenSpec):
        r = Router({})
        r.warnings = spec.warnings + [
            '已退回: 未命中规则一律直连 (不能退成"用全局代理", '
            '那会让直连该走的目标悄悄挂掉)']
        return r
    spec, _migrated = migrate_plaintext_proxies(spec, _rules_file_of(cfg))
    return Router(spec or {},
                  geoip_db=spec.get('geoip_db') or cfg.get('geoip_db'),
                  asn_db=spec.get('asn_db') or cfg.get('asn_db'),
                  geosite_db=spec.get('geosite_db') or cfg.get('geosite_db'))


def _load_spec(cfg):
    """读规则文件。文件坏了不能整个工具瘫掉: 退回全直连, 原因挂 warnings"""
    path = _rules_file_of(cfg)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            spec = json.load(f)
        return spec if isinstance(spec, dict) else {}
    except (ValueError, OSError) as e:
        return _BrokenSpec(path, e)


class _BrokenSpec(dict):
    """坏文件占位: Router 拿到空规则, warnings 里带原因"""

    def __init__(self, path, err):
        super().__init__()
        self.warnings = [f'规则文件读取失败: {path}: {err}']


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
        p = r.proxy_for(url)
        act = r.rule(url)[0]
        logger.debug('路由 %s -> %s', url, act)
        return p
    except RuleError:
        raise
    except Exception:
        # 路由本身出错不能连带把正常请求搞挂, 退回直连
        return None


def explain_route(url, cfg=None):
    """试算: 返回命中了哪条规则、最终走哪条线 (不真正发请求)"""
    return router(cfg).explain(url)


