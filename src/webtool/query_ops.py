# -*- coding: utf-8 -*-
"""Google 风格高级操作符: 解析 + 按引擎能力路由

支持 4 个操作符:
    site:example.com   只看某域
    intitle:foo        标题含 foo
    inurl:foo          URL 含 foo
    -foo               排除 foo (全引擎通用语法, 非 site: 形式)

为什么需要路由: 各引擎对操作符的支持面不同, 把没实现的操作符原样丢给引擎,
引擎会当成普通词去搜, 返回一堆噪声 (看着"有结果"其实全跑偏)。三种策略:

    passthrough  原样发给引擎 (默认, 保持旧行为)
    strip        静默丢掉该引擎不支持的操作符, 其余保留
    strict       有引擎不支持就直接报错退出, 不发请求

支持面矩阵 (实测/文档已知, 会随引擎改版漂移, 保守取交集):
    google   4 项全支持 (语法原生)
    bing     4 项全支持
    baidu    site/intitle/exclude 支持, inurl 不支持
    sogou    site/intitle/exclude 支持, inurl 不支持
    marginalia 全不支持 (自有语法, 操作符按字面量搜)
"""
import re

# 操作符全名 → 是否需要冒号取值 (exclude 是 -word 形式, 无冒号)
_OPERATORS = ('site', 'intitle', 'inurl')
_OP_RE = re.compile(r'\b(site|intitle|inurl):(?:"([^"]+)"|(\S+))', re.I)
# -word 排除: 前面不能是空白(否则是长破折号/负数), 且不能紧跟冒号(那是 -site:foo)
_EXCLUDE_RE = re.compile(r'(?<!\S)-([^\s:][^\s]*)')

# 引擎 → 支持的操作符集合; 集合外的操作符按 strip 策略丢弃
SUPPORT = {
    'google':     {'site', 'intitle', 'inurl', 'exclude'},
    'bing':       {'site', 'intitle', 'inurl', 'exclude'},
    'baidu':      {'site', 'intitle', 'exclude'},
    'sogou':      {'site', 'intitle', 'exclude'},
    'marginalia': set(),
}
# 未登记引擎的默认策略: 保守起见全部丢弃操作符 (宁可少筛, 不要噪声)
_DEFAULT_SUPPORT = set()


class ParsedQuery:
    """解析结果: 操作符 / 排除词 / 裸词"""

    __slots__ = ('raw', 'operators', 'excludes', 'bare_terms')

    def __init__(self, raw):
        self.raw = raw
        self.operators = []   # [(op, value), ...] op ∈ site/intitle/inurl
        self.excludes = []    # [word, ...]
        self.bare_terms = []  # 裸词 (送引擎检索的主体)

    @property
    def has_operators(self):
        return bool(self.operators or self.excludes)

    def __repr__(self):
        return (f'ParsedQuery(ops={self.operators}, excludes={self.excludes}, '
                f'bare={self.bare_terms})')


def parse(query):
    """把查询串拆成 操作符 / 排除词 / 裸词"""
    pq = ParsedQuery(query)
    rest = query

    for m in _OP_RE.finditer(query):
        val = m.group(2) if m.group(2) is not None else m.group(3)
        pq.operators.append((m.group(1).lower(), val))
    rest = _OP_RE.sub(' ', rest)

    for m in _EXCLUDE_RE.finditer(rest):
        pq.excludes.append(m.group(1))
    rest = _EXCLUDE_RE.sub(' ', rest)

    pq.bare_terms = rest.split()
    return pq


def render(operators, excludes, bare_terms):
    """按 Google 语法拼回查询串 (幂等: parse→render→parse 结果一致)"""
    parts = [f'{op}:{val}' for op, val in operators]
    parts += list(bare_terms)
    parts += [f'-{w}' for w in excludes]
    return ' '.join(parts).strip()


def supported_ops(engine):
    """该引擎支持的操作符集合"""
    return SUPPORT.get((engine or '').lower(), _DEFAULT_SUPPORT)


def engine_supports(engine, op):
    return op.lower() in supported_ops(engine)


def unsupported_for(pq, engine):
    """返回 [(op, value)] — 该引擎不支持的操作符"""
    sup = supported_ops(engine)
    bad = [(op, val) for op, val in pq.operators if op not in sup]
    if 'exclude' not in sup and pq.excludes:
        bad += [('exclude', w) for w in pq.excludes]
    return bad


def strip_unsupported(pq, engine):
    """丢掉该引擎不支持的操作符, 重建查询串"""
    sup = supported_ops(engine)
    ops = [(op, val) for op, val in pq.operators if op in sup]
    exc = pq.excludes if 'exclude' in sup else []
    return render(ops, exc, pq.bare_terms)


def apply(query, engines, strategy='passthrough'):
    """按策略算出 每个引擎各自的查询串 → {engine: query}

    strategy:
        passthrough  原样返回 (不解析)
        strip        逐引擎剔除不支持的操作符
        strict       任一引擎不支持 → 返回 (None, 错误信息列表)

    返回 (mapping, unsupported_map): strict 模式下 mapping 为 None,
    unsupported_map 为 {engine: [(op, value), ...]}。
    """
    if strategy == 'passthrough':
        return {e: query for e in engines}, {}

    pq = parse(query)
    if not pq.has_operators:
        return {e: query for e in engines}, {}

    unsupported = {e: unsupported_for(pq, e) for e in engines}
    unsupported = {e: v for e, v in unsupported.items() if v}

    if strategy == 'strict' and unsupported:
        return None, unsupported

    if strategy not in ('strip', 'strict'):
        return {e: query for e in engines}, {}

    mapping = {}
    for e in engines:
        if e in unsupported:
            new_q = strip_unsupported(pq, e)
            # 剔完只剩裸词就退回原串, 避免空查询打过去
            mapping[e] = new_q or query
        else:
            mapping[e] = query
    return mapping, unsupported


def describe(query):
    """人类可读的操作符摘要 (给 engines list / 报错用)"""
    pq = parse(query)
    bits = [f'{op}:{val}' for op, val in pq.operators]
    bits += [f'-{w}' for w in pq.excludes]
    return ' '.join(bits)