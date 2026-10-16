"""webtool config: 统一配置管理子命令

配置层级 (优先级从高到低):
1. 命令行参数 (--proxy / --no-proxy / --blocklist ...)
2. 全局配置 (config set 写入的键)
3. 内置默认值

线路 (直连还是走代理) 不在这里配: 只有规则表一个决策点, 见 webtool proxy rule。

存 ~/.webtool/config.json, 与 proxy/blocklist 文件共存。
"""
import json
import os
import sys

from webtool.core.config_data import USER_DIR
from webtool.core.secrets_store import redact as _redact

CONFIG_PATH = str(USER_DIR / 'config.json')

# 可配置键白名单: (键名, 说明, 合法值)
# 废弃配置的提示文案 (set/get 都指回规则表)
_DEP_ENGINE_PROXY = ('engine_proxy 已废弃: 线路统一由规则表决定, 这里配了不起作用。改用 `webtool proxy rule add <域名> direct` 或 `… proxy:<代理名>`;要清掉旧值: `webtool config unset engine_proxy`')

CONFIG_KEYS = {
    'blocklist':        ('黑名单覆盖', '逗号分隔域名, ! 前缀表白名单例外, off 关闭', None),
    'market':           ('搜索市场', 'zh-CN / en-US 等 bing mkt 值 (仅 bing 消费)', None),
    'default_engines':  ('默认引擎组合', '逗号分隔: bing,sogou,baidu,google', None),
    'jobs':             ('搜索并发引擎数', '1 ~ 16 整数; 1=串行, 0/不设=按源数(上限 4)', int),
    'default_format':   ('默认输出格式', 'json / text / markdown', ('json', 'text', 'markdown')),
    'timeout':          ('请求超时秒数', '5 ~ 60 整数', int),
    'cache':            ('缓存开关', 'on / off', ('on', 'off')),
    'rules_file':       ('路由规则文件路径', '默认 ~/.webtool/rules.json', None),
    'extract':          ('正文提取器', 'auto=内容层择优 (默认, 最干净) / '
                                       'trafilatura / readability / boilerplate / inscriptis',
                         ('auto', 'trafilatura', 'readability', 'boilerplate',
                          'inscriptis')),
    'geoip_db':        ('GeoIP 国家库', 'GeoLite2-Country.mmdb 路径; '
                         '不配则 geoip 规则不生效', None),
    'asn_db':          ('GeoIP ASN 库', 'GeoLite2-ASN.mmdb 路径', None),
    'proxy_dns_ttl':   ('代理解析 DNS 缓存秒数', '正整数, 默认 60', int),
    'ssl_verify':       ('证书校验总开关', 'on / off (off = 全站不校验证书, '
                          '慎用, 通常应该用 verify_hosts 点名)', ('on', 'off')),
    'ca_bundle':        ('自定义 CA 包路径 (ssl_verify=on 时替代系统 CA)',
                          '如 /etc/ssl/corp-ca.pem; 想追加而非替代请自行 cat 合并', None),
    'verify_hosts':     ('关校验的域名单 (自签/过期证书站)',
                          '逗号分隔, 如 czce.com.cn,gtjaqh.com (覆盖子域); '
                          '其余域仍严格校验', None),
    'cache_ttl.<bucket>':   ('分桶缓存 TTL 秒覆盖',
                             '<bucket>=<sec>, 如 cache_ttl.search=30 (桶: search/fetch/resolve/hot/zen)',
                             None),
}


def load_config():
    cfg = {}
    try:
        with open(CONFIG_PATH, encoding='utf-8') as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=1)


def _validate(key, value):
    """返回 (ok, 转换后的值/错误信息)"""
    if key.startswith('engine_proxy'):
        # 老的每引擎覆盖: 先于"未知键"报出来, 否则用户只看到一句"未知配置键"
        return False, _DEP_ENGINE_PROXY
    if key.startswith('cache_ttl.'):
        return True, value          # 复合键: 桶/引擎名自由, 值按原样
    if key not in CONFIG_KEYS:
        return False, f'未知配置键: {key}\n可用键: {", ".join(CONFIG_KEYS)}'
    desc, hint, typ = CONFIG_KEYS[key]
    if key == 'ca_bundle':
        # 路径必须当场验: 写进去一个不存在的文件, 等到出网时才炸最难查
        path = os.path.expanduser(value.strip())
        if not os.path.isfile(path):
            return False, f'CA 文件不存在: {path}'
        return True, path
    if key == 'verify_hosts':
        raw = value.replace(';', ',').split(',')
        hosts = [h.strip().lower().lstrip('.') for h in raw if h.strip()]
        if not hosts:
            return False, '至少给一个域名, 或用 unset 清空'
        bad = [h for h in hosts if '/' in h or ' ' in h]
        if bad:
            return False, f'只写域名不要带路径/空格: {", ".join(bad)}'
        return True, hosts
    if key in ('geoip_db', 'asn_db'):
        path = os.path.expanduser(value.strip())
        if not os.path.isfile(path):
            return False, f'数据库文件不存在: {path}'
        if not path.endswith('.mmdb'):
            return False, 'GeoIP 库应为 .mmdb (MaxMind DB 格式)'
        return True, path
    if key == 'rules_file':
        path = os.path.expanduser(value.strip())
        # 规则文件允许不存在 (用户可能先 set 再写), 但存在时必须能解析
        if os.path.isfile(path):
            try:
                with open(path, encoding='utf-8') as f:
                    json.load(f)
            except ValueError as e:
                return False, f'规则文件不是合法 JSON: {path}: {e}'
        return True, path
    if key == 'jobs':
        try:
            v = int(value)
        except ValueError:
            return False, '并发数要是整数 (1 ~ 16; 1=串行)'
        if not (1 <= v <= 16):
            return False, '取值范围 1 ~ 16 (1=串行)'
        return True, v
    if typ in (float, int):
        try:
            v = typ(value)
            if typ is float and not (0 <= v <= 2.0):
                return False, '取值范围 0 ~ 2.0'
            if typ is int and not (5 <= v <= 60):
                return False, '取值范围 5 ~ 60'
            return True, v
        except ValueError:
            return False, f'需要 {"浮点" if typ is float else "整数"}: {value}'
    if isinstance(typ, tuple):
        if value.lower() not in typ:
            return False, f'合法值: {"/".join(typ)}'
        return True, value.lower()
    return True, value  # 自由文本 (proxy/default_engines 等)


def handle(args):
    """webtool config get|set|unset|list [key] [value]"""
    cfg = load_config()

    if args.action == 'list':
        fmt = getattr(args, 'format', None)
        # 只有显式给了非 json 的 -f 才交结构化数据 (默认 txt 走人类表格)
        rows = []
        # TLS 三项的"当前"取实际生效策略而非配置字面值: 配置写 on 但环境
        # 没 CA 包时实际是 off, 只显示字面值会误导排查方向
        tls_view = {}
        try:
            from webtool.net import tls as _tls
            tls_view = _tls.describe()
        except Exception:
            pass
        for k, (desc, hint, _t) in CONFIG_KEYS.items():
            base = k.split('.')[0]
            if k in ('ssl_verify', 'ca_bundle', 'verify_hosts') and tls_view:
                cur = json.dumps(tls_view.get(k, cfg.get(base, '(未设置)')),
                                 ensure_ascii=False)
            else:
                cur = json.dumps(cfg.get(base, '(未设置)'), ensure_ascii=False)
            rows.append({'key': k, 'desc': desc, 'current': _redact(cur),
                         'hint': hint})
        warn = tls_view.get('warning')
        # 给了 -f 就交结构化数据给 cli/adminfmt 转格式; 没给保持人类可读表格
        if fmt and fmt != 'json':
            print(json.dumps(rows, ensure_ascii=False, indent=1))
            return 0
        print(f'配置文件: {CONFIG_PATH}')
        print()
        for r in rows:
            print(f'  {r["key"]:24} {r["desc"]}')
            print(f'  {"":24} 当前: {r["current"]}   合法值: {r["hint"]}')
        if warn:
            print()
            print(f'  ⚠ 证书: {warn}')
        return 0

    if args.action == 'get':
        if not args.key:
            print('usage: webtool config get <key>', file=sys.stderr)
            return 2
        if args.key.startswith('engine_proxy'):
            print(_DEP_ENGINE_PROXY)          # 这是要给的答案, 走 stdout
            return 2
        base = args.key.split('.')[0]
        print(_redact(json.dumps(cfg.get(base, '(未设置)'), ensure_ascii=False)))
        return 0

    if args.action == 'unset':
        if not args.key:
            print('usage: webtool config unset <key>', file=sys.stderr)
            return 2
        if args.key.startswith('engine_proxy.'):
            eng = args.key.split('.', 1)[1]
            cfg.setdefault('engine_proxy', {}).pop(eng, None)
            print('(注意: engine_proxy 已废弃, 线路统一由规则表决定)')
        else:
            cfg.pop(args.key.split('.')[0] if args.key == 'engine_proxy'
                    else args.key, None)
        save_config(cfg)
        print(f'unset {args.key} -> {CONFIG_PATH}')
        return 0

    if args.action == 'set':
        if not args.key or not args.value:
            print('usage: webtool config set <key> <value>', file=sys.stderr)
            return 2
        ok, v = _validate(args.key, args.value)
        if not ok:
            print(v, file=sys.stderr)
            return 2
        if args.key.startswith('cache_ttl.'):
            bucket = args.key.split('.', 1)[1]
            cfg.setdefault('cache_ttl', {})[bucket] = v
        else:
            cfg[args.key] = v
        save_config(cfg)
        print(f'set {args.key} = {json.dumps(v, ensure_ascii=False)} -> {CONFIG_PATH}')
        return 0
    return 0
