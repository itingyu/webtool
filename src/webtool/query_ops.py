"""Google 风格操作符解析 + 按引擎能力路由 (site:/intitle:/inurl:/-word 排除)

没实现的操作符原样丢给引擎会被当普通词, 返回全跑偏的噪声。策略: passthrough
原样透传 (默认) / strip 剔除不支持的 / strict 直接报错; 支持面见 SUPPORT,
会随引擎改版漂移, 保守取交集。
"""
import re

_OPERATORS = ('site', 'intitle', 'inurl')
_OP_RE = re.compile(r'\b(site|intitle|inurl):(?:"([^"]+)"|(\S+))', re.I)
# -word 排除: 前面不能是空白(否则是长破折号/负数), 且不能紧跟冒号(那是 -site:foo)
_EXCLUDE_RE = re.compile(r'(?<!\S)-([^\s:][^\s]*)')

# 引擎支持哪些操作符, 来自插件清单 engine.<name>.params.ops;
# 集合外的操作符按 strip 策略丢弃。未声明的引擎保守起见全部丢弃
# (宁可少筛, 不要噪声)
_DEFAULT_SUPPORT = frozenset()
_SUP_CACHE = {}


def _ops_map():
    """插件表 → {engine: {操作符}}; 清单改动后自动重读 (mtime 失效)"""
    from webtool.plugins import ENGINES
    items = ENGINES.items()
    key = tuple(sorted(items))
    hit = _SUP_CACHE.get('key')
    if hit != key:
        _SUP_CACHE['key'] = key
        _SUP_CACHE['ops'] = {
            n: frozenset(s.get('ops') or ()) for n, s in items.items()}
    return _SUP_CACHE['ops']


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
    return _ops_map().get((engine or '').lower(), _DEFAULT_SUPPORT)


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