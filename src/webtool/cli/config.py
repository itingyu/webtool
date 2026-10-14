"""webtool config: 统一配置管理子命令

配置层级 (优先级从高到低):
1. 命令行参数 (--proxy / --blocklist ...)
2. 引擎/站点级配置 (~/.webtool/config.json 的 engine_proxy)
3. 全局配置 (config set 写入的键)
4. 内置默认值

存 ~/.webtool/config.json, 与 proxy/blocklist 文件共存。
"""
import json
import os
import re
import sys
import urllib.parse

from webtool.core.config_data import USER_DIR
from webtool.core.secrets_store import redact as _redact

CONFIG_PATH = str(USER_DIR / 'config.json')

# 可配置键白名单: (键名, 说明, 合法值)
CONFIG_KEYS = {
    'proxy':            ('全局代理 (不带凭据; 密码用 webtool proxy setpass 存)',
                         '如 http://127.0.0.1:2080 / socks5://...', None),
    'blocklist':        ('黑名单覆盖', '逗号分隔域名, ! 前缀表白名单例外, off 关闭', None),
    'market':           ('搜索市场', 'zh-CN / en-US 等 bing mkt 值 (仅 bing 消费)', None),
    'default_engines':  ('默认引擎组合', '逗号分隔: bing,sogou,baidu,google', None),
    'default_format':   ('默认输出格式', 'json / text / markdown', ('json', 'text', 'markdown')),
    'timeout':          ('请求超时秒数', '5 ~ 60 整数', int),
    'cache':            ('缓存开关', 'on / off', ('on', 'off')),
    'fetch_proxy':      ('抓取专用代理', '<url>; 空=跟随全局', None),
    'engine_proxy':     ('每引擎代理覆盖', '{"bing":null,"google":"<url>"}', None),
    'proxy_rules':      ('路由规则 (内联)', 'JSON: {default, proxies, rules}; '
                         '更推荐 webtool proxy rule add', None),
    'rules_file':       ('路由规则文件路径', '默认 ~/.webtool/rules.json', None),
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
    'engine_proxy.<engine>': ('单引擎代理覆盖',
                              '<engine>=<url> 形式 set, 如 engine_proxy.google=http://...', None),
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
    if key.startswith(('engine_proxy.', 'cache_ttl.')):
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
    if key in ('proxy', 'fetch_proxy'):
        v = value.strip()
        if not re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*://', v):
            v = 'http://' + v
        # 与 `webtool proxy set` 共用同一套拆分: 密码含 / 时 urlsplit 会把
        # host 截断再抛 Port could not be cast, 而这类密码并不罕见
        from webtool.net.proxy import proxy_url_parts
        scheme, user, password, host, port = proxy_url_parts(v)
        if scheme not in ('http', 'https', 'socks5', 'socks5h', 'socks4'):
            return False, (f'不支持的代理协议: {scheme or "(无)"} '
                           f'(支持 http/https/socks5/socks5h/socks4)')
        if not host:
            return False, '缺少主机名'
        # 密码进保险库, 配置里只留 user@ —— 明文不落盘
        if password:
            from webtool.core import secrets_store as _S
            try:
                _S.store_password(user, password)
            except _S.SecretError as e:
                return False, str(e)
            v = (f'{scheme}://{urllib.parse.quote(user, safe="")}@{host}'
                 + (f':{port}' if port else ''))
        return True, v
    if key == 'proxy_rules':
        try:
            spec = json.loads(value)
        except ValueError as e:
            return False, f'必须是合法 JSON: {e}'
        from webtool.net import rules as _R
        try:
            _R.Router(spec)            # 构造即校验
        except _R.RuleError as e:
            return False, str(e)
        except (TypeError, ValueError) as e:
            return False, f'规则结构非法: {e}'
        return True, spec
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
    return True, value  # 自由文本 (proxy/default_engines/engine_proxy.*)


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
            from webtool.core import tls as _tls
            tls_view = _tls.describe()
        except Exception:
            pass
        for k, (desc, hint, _t) in CONFIG_KEYS.items():
            base = k.split('.')[0]
            if k.startswith('engine_proxy.'):
                v = cfg.get('engine_proxy', {})
                cur = json.dumps(v, ensure_ascii=False) if v else '(未设置)'
            elif k in ('ssl_verify', 'ca_bundle', 'verify_hosts') and tls_view:
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
        base = args.key.split('.')[0]
        if args.key.startswith('engine_proxy.'):
            eng = args.key.split('.', 1)[1]
            print(_redact(json.dumps(cfg.get('engine_proxy', {}).get(eng, '(未设置)'), ensure_ascii=False)))
        else:
            print(_redact(json.dumps(cfg.get(base, '(未设置)'), ensure_ascii=False)))
        return 0

    if args.action == 'unset':
        if not args.key:
            print('usage: webtool config unset <key>', file=sys.stderr)
            return 2
        if args.key.startswith('engine_proxy.'):
            eng = args.key.split('.', 1)[1]
            cfg.setdefault('engine_proxy', {}).pop(eng, None)
        else:
            cfg.pop(args.key, None)
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
        if args.key.startswith('engine_proxy.'):
            eng = args.key.split('.', 1)[1]
            cfg.setdefault('engine_proxy', {})[eng] = v
        elif args.key.startswith('cache_ttl.'):
            bucket = args.key.split('.', 1)[1]
            cfg.setdefault('cache_ttl', {})[bucket] = v
        else:
            cfg[args.key] = v
        # _validate 里可能刚把密码密文写进 config.json, 而这里的 cfg 是
        # 进入 handle 时读的旧快照 —— 不合并回去, save_config 会用空的
        # proxy_auth 把刚存的密文覆盖掉 (命令看着成功了, 下次启动就没密码)
        if args.key in ('proxy', 'fetch_proxy'):
            merged = load_config().get('proxy_auth') or {}
            if merged != (cfg.get('proxy_auth') or {}):
                cfg['proxy_auth'] = merged
        save_config(cfg)
        print(f'set {args.key} = {json.dumps(v, ensure_ascii=False)} -> {CONFIG_PATH}')
        return 0
    return 0
