"""config.json 的**唯一**键表: 默认值、用户可见说明、取值校验都在这里

以前是两份表: `net/proxy/store.py:DEFAULTS` 是 load_config 的白名单,
`cli/config.py:CONFIG_KEYS` 是 CLI 的描述与校验。同一批键写两遍, 于是出了三类
事故 —— 都属于"用户配了没反应", 而现场离真凶很远:

① config set 写得进、业务读不回来 (键只在 CLI 那份表里 → load_config 静默过滤)
② 键在白名单里、却没人从 config.json 读它 (低_prior 那三个, 真实来源是
   data/filters.json 的 merge 段) —— 配进去原样返回, 零效果零提示
③ 校验分支按类型复用区间, 把 timeout 的 5~60 套到了 proxy_dns_ttl 上,
   于是 `config set proxy_dns_ttl 300` (恰是它的默认值) 被拒

所以每个键在这里声明一次: 默认值(读侧兜底链的底) + 说明/合法值(给人看) +
校验(set 时当场验) + 是否给用户 `config set` 入口。两侧都从这里派生:

    net.proxy.store.DEFAULTS  ← DEFAULTS   (load_config 的白名单)
    cli.config.CONFIG_KEYS    ← cli_keys() (描述/提示/类型)

**默认值是"用户没配时 load_config 返回什么"**, 因此写 None 就是"键存在但值为
None" —— 读侧 `cfg.get(k, 自己的默认)` 拿不到自己的默认了。所以只有确实"没配就
没有值"的键才写 None (market/default_engines/jobs/blocklist 等), 有内置底的写那个
底。注意 `timeout` 写的是 15 而不是 None: 十四个读点用的是 `cfg.get('timeout', 15)`
这种形状, 改成 None 会让它们拿到 None 而不是 15 —— 那是行为变更, 不是重构。

本模块在 core 层: 不知道 net/engines/pipeline 的存在, 也不 import 它们 —— 它只
描述"用户配置文件长什么样"。
"""

import json
import os
from collections import namedtuple

from webtool.core.config_data import USER_DIR

# check(key, raw) -> (ok, 转换后的值 | 错误说明); None = 按 kind 走通用校验
# values: 枚举键的合法值表 —— 校验与 CLI 展示的"合法值"同源, 不写两遍
Key = namedtuple('Key', 'default desc hint kind values check cli',
                 defaults=(None, None, True))

# 类型常量必须先于 _EMPTY 绑定 —— 模块级自上而下执行, 放在 _EMPTY 之后会
# NameError: name 'TEXT' is not defined (整个包 import 即炸)。
TEXT, INT, FLOAT, ENUM = 'text', 'int', 'float', 'enum'

_EMPTY = Key(None, '', '', TEXT, None, None, True)


def _enum_key(default, desc, hint, values, cli=True):
    """枚举键: 合法值只在这里写一次, 校验与展示都从它派生"""
    return Key(default, desc, hint, ENUM, tuple(values), _enum(values), cli)


def _int_range(lo, hi, why):
    """整数键的取值范围 —— 每个键一份, 不共用别人的区间"""
    def check(_key, raw):
        try:
            v = int(raw)
        except (TypeError, ValueError):
            return False, '需要整数: %s' % raw
        if not (lo <= v <= hi):
            return False, '取值范围 %d ~ %d (%s)' % (lo, hi, why)
        return True, v
    return check


def _float_range(lo, hi, why):
    def check(_key, raw):
        try:
            v = float(raw)
        except (TypeError, ValueError):
            return False, '需要浮点数: %s' % raw
        if not (lo <= v <= hi):
            return False, '取值范围 %g ~ %g (%s)' % (lo, hi, why)
        return True, v
    return check


def _enum(values, why=''):
    def check(_key, raw):
        v = str(raw).strip().lower()
        if v not in values:
            return False, '合法值: %s%s' % ('/'.join(values),
                                            (' (%s)' % why) if why else '')
        return True, v
    return check


def _file(path_kinds, suffix=None):
    """路径类键: 文件必须**当场**存在 —— 写进去一个不存在的路径, 等到出网时才炸
    最难查 (那时现场已经离 config set 十万八千里)"""
    def check(_key, raw):
        p = os.path.expanduser(str(raw).strip())
        if not os.path.isfile(p):
            return False, '文件不存在: %s' % p
        if suffix and not p.endswith(suffix):
            return False, '%s 应为 %s (MaxMind DB 格式)' % (p, suffix)
        return True, p
    return check


def _hosts(_key, raw):
    """关校验的域名单: 只要域名, 带路径/空格的一定是误写"""
    hosts = [h.strip().lower().lstrip('.')
             for h in str(raw).replace(';', ',').split(',') if h.strip()]
    if not hosts:
        return False, '至少给一个域名, 或用 unset 清空'
    bad = [h for h in hosts if '/' in h or ' ' in h]
    if bad:
        return False, '只写域名不要带路径/空格: %s' % ', '.join(bad)
    return True, hosts


def _rules_file(_key, raw):
    """规则文件允许不存在 (用户可能先 set 再写), 但存在时必须能解析"""
    p = os.path.expanduser(str(raw).strip())
    if os.path.isfile(p):
        try:
            with open(p, encoding='utf-8') as f:
                json.load(f)
        except ValueError as e:
            return False, '规则文件不是合法 JSON: %s: %s' % (p, e)
    return True, p


KEYS = {
    # ── 抓取与输出 ──────────────────────────────────────────────────
    # 15 是"内置底", 不是"没配": 十四个读点写的是 cfg.get('timeout', 15),
    # 改成 None 会让它们拿到 None —— 那是行为变更 (见文件头)
    'timeout': Key(
        15, '请求超时秒数', '5 ~ 60 整数', INT, None, _int_range(5, 60, '秒'), True),
    'default_format': _enum_key(
        None, '默认输出格式', 'json / text / markdown',
        ('json', 'text', 'markdown')),
    'cache': _enum_key(None, '缓存开关', 'on / off', ('on', 'off')),
    'cache_dir': Key(
        str(USER_DIR / 'cache'), '缓存目录', '默认 ~/.webtool/cache; 换目录后旧缓存不迁移',
        TEXT, None, None, True),
    'cache_ttl': Key(
        {}, '分桶缓存 TTL 秒覆盖',
        '按桶名设: webtool config set cache_ttl.search=30 '
        '(桶: search/fetch/resolve/hot/zen)', TEXT, None, None, False),
    'extract': _enum_key(
        'auto', '正文提取器',
        'auto=内容层择优 (默认, 最干净) / trafilatura / readability / '
        'boilerplate / inscriptis',
        ('auto', 'trafilatura', 'readability', 'boilerplate', 'inscriptis')),
    # ── 搜索行为 ────────────────────────────────────────────────────
    'default_engines': Key(
        None, '默认引擎组合', '逗号分隔: bing,sogou,baidu,google; 未知引擎退 2',
        TEXT, None, None, True),
    'market': Key(
        None, '搜索市场', 'zh-CN / en-US 等 bing mkt 值 (仅 bing 消费)',
        TEXT, None, None, True),
    # 0 = 按源数 (上限 4), 是有意义的取值 —— 旧校验只收 1~16, 与说明自相矛盾
    'jobs': Key(
        None, '搜索并发引擎数', '0 ~ 16 整数; 1=串行, 0/不设=按源数(上限 4)', INT,
        None, _int_range(0, 16, '1=串行, 0=按源数'), True),
    'blocklist': Key(
        None, '黑名单覆盖', '逗号分隔域名, ! 前缀表白名单例外, off 关闭',
        TEXT, None, None, True),
    # ── 证书 ────────────────────────────────────────────────────────
    'ssl_verify': _enum_key(
        True, '证书校验总开关',
        'on / off (off = 全站不校验证书, 慎用, 通常应该用 verify_hosts 点名)',
        ('on', 'off')),
    'ca_bundle': Key(
        None, '自定义 CA 包路径 (ssl_verify=on 时替代系统 CA)',
        '如 /etc/ssl/corp-ca.pem; 想追加而非替代请自行 cat 合并', TEXT,
        None, _file('pem'), True),
    'verify_hosts': Key(
        [], '关校验的域名单 (自签/过期证书站)',
        '逗号分隔, 如 czce.com.cn,gtjaqh.com (覆盖子域); 其余域仍严格校验。'
        '有该站证书时优先用规则: 证书丢 ~/.webtool/certs/extra/ 后 '
        'webtool proxy cert sync', TEXT, None, _hosts, True),
    # ── 路由规则与地理库 ────────────────────────────────────────────
    'rules_file': Key(
        None, '路由规则文件路径', '默认 ~/.webtool/rules.json',
        TEXT, None, _rules_file, True),
    'geoip_db': Key(
        None, 'GeoIP 国家库',
        'GeoLite2-Country.mmdb 路径; 不配则 geoip 规则不生效', TEXT,
        None, _file('mmdb', '.mmdb'), True),
    'geosite_db': Key(
        None, 'GeoSite 域名分类库', 'geosite.dat 路径; 供规则表按域名分类命中',
        TEXT, None, None, True),
    'asn_db': Key(
        None, 'GeoIP ASN 库', 'GeoLite2-ASN.mmdb 路径', TEXT,
        None, _file('mmdb', '.mmdb'), True),
    'proxy_dns_ttl': Key(
        300, '代理解析 DNS 缓存秒数', '正整数, 默认 300', INT,
        None, _int_range(1, 86400, '秒'), True),
    'proxy_fallback': _enum_key(
        'on', '代理连不上时改走直连',
        'on=代理没起来就走直连 (默认) / off=照配置报错; 只认"连不上"'
        '(端口没监听/拒绝/超时/DNS 不通), 代理自己返回的错误不算', ('on', 'off')),
    # ── 弹性 (重试与熔断) ───────────────────────────────────────────
    # 默认都关: 失败就当场报出来, 不静默重发。重试会把 1 次失败放大成多次
    # 请求 (再叠降级梯更甚), 熔断冷却又把整个域名短路几分钟 —— 排查现场时
    # 这两件事都在"真相"之外, 所以默认关掉, 要的人自己开。
    'retries': Key(
        0, '失败重试次数 (仅幂等 GET/HEAD)', '0 ~ 10 整数; 0=不重试 (默认)', INT,
        None, _int_range(0, 10, '次数'), True),
    'retry_backoff': _enum_key(
        'exp', '重试退避方式', 'exp=指数退避+jitter (默认) / flat=固定间隔',
        ('exp', 'flat')),
    'breaker_fails': Key(
        5, '域级熔断: 连续失败阈值', '1 ~ 100 整数; 冷却为 0 时熔断不生效', INT,
        None, _int_range(1, 100, '次'), True),
    'breaker_cool': Key(
        0, '域级熔断冷却秒数', '0 ~ 3600 整数; 0=关闭熔断 (默认)', INT,
        None, _int_range(0, 3600, '秒'), True),
    'ladder_steps': Key(
        0, '反爬降级梯最大步数',
        '0 ~ 10 整数; 0=首次被拦即报 (默认); 仅带引擎名的抓页通道', INT,
        None, _int_range(0, 10, '步'), True),
    # ── 凭据 (不进 CLI 键表) ─────────────────────────────────────────
    # 密文由 `webtool proxy setpass` 写, 不给用户一条 set 入口: 手改密文字段
    # 只会写坏保险库, 而 config list 也不该把它印出来
    'proxy_auth': Key(
        {}, '代理密码 (密文, 由 webtool proxy setpass 维护)', '', TEXT,
        None, None, False),
}

DEFAULTS = {k: v.default for k, v in KEYS.items()}

# 复合键: 用户写的是 cache_ttl.<桶名>, 落盘时展开成 cache_ttl 这个 dict 的子键。
# 桶名自由 (引擎名也行), 但帮助文案里那个占位符不是桶名 —— 照抄会写进一个
# 永远命不中的桶, 且从外面看不出错。
DYNAMIC = {
    'cache_ttl.<bucket>': ('分桶缓存 TTL 秒覆盖',
                           '<bucket>=<sec>, 如 cache_ttl.search=30 '
                           '(桶: search/fetch/resolve/hot/zen)'),
}

# 类型名 → cli/config.py 曾经用的 typ (bool 不再用: 全仓没有布尔型键)
_KIND_ALIAS = {TEXT: None, INT: int, FLOAT: float, ENUM: None}


def cli_keys():
    """给 CLI 用的键表 {键: (说明, 合法值, typ)} —— 只含给用户留了 set 入口的"""
    return {k: (v.desc, v.hint, _KIND_ALIAS[v.kind]) for k, v in KEYS.items() if v.cli}


def cli_table():
    """CLI 键表 + 复合键条目 (config list / 帮助文案要一起列)"""
    out = cli_keys()
    for k, (desc, hint) in DYNAMIC.items():
        out[k] = (desc, hint, None)
    return out


DEPRECATED_ENGINE_PROXY = (
    'engine_proxy.<引擎> 已被移除: 现在线路只由 ~/.webtool/rules.json 判一次, '
    '不再按引擎名配代理。要固定某个站走直连就加一条规则: '
    'webtool proxy rule add \'{"domain":["exa.ai"]}\' direct；删: '
    'webtool config unset engine_proxy.<引擎>')


def validate(key, value):
    """set 前的取值校验 → (ok, 转换后的值 | 错误说明)

    复合键 (cache_ttl.<桶>) 在这里展开校验: 桶名照抄占位符当场拒。
    """
    if key.startswith('engine_proxy'):
        # 老的每引擎覆盖: 先于"未知键"报出来, 否则用户只看到一句"未知配置键"
        return False, DEPRECATED_ENGINE_PROXY
    if key.startswith('cache_ttl.'):
        bucket = key.split('.', 1)[1]
        if not bucket or '<' in bucket or '>' in bucket:
            return False, ('桶名要写实际名字, 不能照抄占位符: 如 '
                           'cache_ttl.search=30 (桶: search/fetch/resolve/hot/zen/引擎名)')
        return True, value                     # 复合键: 桶名自由, 值按原样
    spec = KEYS.get(key)
    if spec is None or not spec.cli:
        known = ', '.join(list(cli_table()))
        return False, '未知配置键: %s\n可用键: %s' % (key, known)
    if spec.check:
        return spec.check(key, value)
    if spec.kind == INT:
        return _int_range(-2 ** 31, 2 ** 31 - 1, '整数')(key, value)
    if spec.kind == FLOAT:
        return _float_range(-1e9, 1e9, '')(key, value)
    return True, value