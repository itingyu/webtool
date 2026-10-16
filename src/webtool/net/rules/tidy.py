"""规则表的整理工具: 种子补全 (seed) / 死规则试算 (shadow) / 合并裁剪 (tidy)

都是纯函数 (不联网、不改传进来的 dict), 供 `webtool proxy` 系列命令用。
"""
import copy
import json

from webtool.net.rules.matchers import (
    _domains_of, _is_domain_only, _IPRef, _norm_pat, _pat_covers)
from webtool.net.rules.spec import RuleError, resolve_action


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


def seed_rules(spec, path=None):
    """规则表为空时, 把包内默认规则 (data/rules.json) 补进去

    为什么要有这一步: 默认规则表只在"存在代理"时才有意义 —— 它的作用是
    把国内站钉在直连上, 而没配代理时所有流量本来就直连 (此时规则是冗余的,
    `proxy tidy` 会建议删掉)。所以种子不在首次启动时落, 而是在 `proxy set`
    把默认动作切成代理的那一刻读模板补上。这样模板是唯一事实来源, 代码里
    不再存第二份规则清单。

    返回补进去的条数 (0 = 没动)。
    """
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
    spec = copy.deepcopy(spec) if isinstance(spec, dict) else {}
    rules = spec.get('rules') or []
    report = []
    default_action = spec.get('default') or 'direct'

    kept = []                    # [{'match':…, 'action':…, 'doms':[…] 或 None}]
    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            continue
        if rule.get('kind'):
            # kind 条目 (http/retry/breaker/tls) 没有 action, 不参与线路整理。
            # 漏掉这一支的话, 下面"动作与默认同结果 → 删"会把它读成 direct
            # (resolve_action(None)), 一次 `tidy --apply` 就把限速/重试/熔断/
            # 证书整批删光 —— 而输出还写着"整理成功"。
            kept.append({'rule': rule, 'act': None, 'doms': None, 'idx': i})
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
