"""Router: 按规则表决定某个 URL 走哪条线路, 以及各环节 (kind) 的参数

线路只有一个决策点 (本类); kind 条目 (http/retry/breaker/...) 与路由条目在
同一份 rules.json 里共存, 互不干扰。"""
import logging

from webtool.net.rules.geodb import geoip_asn, geoip_country
from webtool.net.rules.matchers import (
    _as_list, _asn_match, _cidr_match, _domain_match, _glob_match,
    _IPRef, _port_match, _scheme_match, _split_url)
from webtool.net.rules.spec import MATCH_KEYS, RuleError, spec_for, resolve_action

logger = logging.getLogger(__name__)


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
                self._check_kind_rule(i, r)
                continue
            if not isinstance(r.get('match'), dict) or not r.get('match'):
                self.warnings.append(f'rules[{i}] 缺 match 段, 已跳过')
            try:
                resolve_action(r.get('action'))
            except RuleError as e:
                self.warnings.append(f'rules[{i}] {e}')

    def _check_kind_rule(self, i, r):
        """kind 条目的静态体检: match 键拼错 = 静默死规则, 必须报出来"""
        kind = r.get('kind')
        m = r.get('match')
        if not isinstance(m, dict) or not m:
            self.warnings.append(f'rules[{i}] (kind:{kind}) 缺 match 段, 已跳过')
            return
        allowed = MATCH_KEYS
        sp = spec_for(kind)
        if sp is not None:
            allowed = sp.match_keys
        bad = [k for k in m if k not in allowed]
        if bad:
            self.warnings.append(
                f'rules[{i}] (kind:{kind}) match 里有无法识别的键 {bad}, '
                f'该条件不生效 (允许: {", ".join(allowed)})')

    def rule(self, url):
        """URL → (action, proxy_name, 命中的规则序号 或 None)

        文件顺序 first-match-wins; block 命中即断。"""
        host, port, scheme = _split_url(url)
        ip_ref = _IPRef(host)
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
                logger.debug('rules | rule[%s] 命中 %s: %s', kind, host, p)
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


def _mask(url):
    """出口处统一脱敏: 万一有带密码的 URL 漏进来, 也不至于打进日志"""
    from webtool.core.secrets_store import redact
    return redact(url)
