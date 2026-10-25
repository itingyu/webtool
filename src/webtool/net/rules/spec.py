"""规则引擎通用契约: 动作解析 + kind 元数据注册表

kind = 环节 (http / retry / breaker / ...)。规则条目带 `kind` 就按环节生效,
不带 `kind` 就是线路路由。本模块只放"与具体环节无关"的契约, 不认识匹配器
(matchers) 也不认识路由 (router)。

**新增环节不改本文件**: 环节自己的模块里 `register(RuleSpec(...))` 声明即可
(见 builtin.py 的三个内置 kind), 元数据用于: (1) `kinds()` 目录可被 CLI/文档
枚举; (2) Router 校验 kind 条目的 match 键, 揪出手写错键这种"静默死规则"。
"""
VALID_ACTIONS = ('direct', 'proxy', 'block')

# 规则 match 段允许的条件键 (各 kind 通用)。写别的键 = 拼错, 会告警。
MATCH_KEYS = ('domain', 'domain_suffix', 'host', 'port', 'scheme',
              'cidr', 'ip', 'geosite', 'geoip', 'asn')


class RuleError(RuntimeError):
    """规则配置非法"""


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


class RuleSpec:
    """一个环节的规则元数据

    - kind:       环节名 (规则条目的 `kind` 字段)
    - fields:     该环节允许的动作字段 (除 match/kind 外), 便于文档与校验
    - match_keys: 该环节允许的匹配键, 默认全量 MATCH_KEYS (粒度随对象定)
    - doc:        一句话说明
    """

    def __init__(self, kind, fields=(), match_keys=(), doc=''):
        self.kind = str(kind)
        self.fields = tuple(fields)
        self.match_keys = tuple(match_keys) or MATCH_KEYS
        self.doc = doc

    def __repr__(self):
        return f'RuleSpec({self.kind!r}, fields={list(self.fields)})'


_SPECS = {}


def register(spec):
    """注册/覆盖一个环节的 RuleSpec (后注册覆盖先注册, 便于用户侧扩展)"""
    _SPECS[spec.kind] = spec
    return spec


def specs():
    """已注册的 kind 目录 {kind: RuleSpec}"""
    return dict(_SPECS)


def spec_for(kind):
    return _SPECS.get(kind)
