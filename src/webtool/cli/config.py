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

from webtool.core import config_schema as _schema
from webtool.core.config_data import USER_DIR
from webtool.core.secrets_store import redact as _redact
from webtool.net.proxy import store as _store

CONFIG_PATH = str(USER_DIR / 'config.json')

# 键表在 core/config_schema.py (唯一来源: 默认值/说明/校验都在那里), 这里只取
# 展示用的投影。同一个键写两遍的后果见那个文件的文件头。
CONFIG_KEYS = _schema.cli_table()

# 废弃配置的提示文案 (set/get 都指回规则表)
_DEP_ENGINE_PROXY = _schema.DEPRECATED_ENGINE_PROXY


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
    """set 前的取值校验 → (ok, 转换后的值/错误信息)

    校验规则跟着键走 (core/config_schema.py): 每个键自带范围/枚举/路径检查,
    不再在这里按类型共用一段区间 —— `typ=int` 被 timeout 与 proxy_dns_ttl 共用
    时, 后者被套上了前者的 5~60, 于是 `config set proxy_dns_ttl 300` (恰是它
    的默认值) 被拒。
    """
    return _schema.validate(key, value)


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
        # 文件里有、但没人认的键: 读配置时会被丢掉, 且每次启动刷一条警告。
        # 不列出来用户就只能看到警告、不知道那个键叫什么名字 —— 列出来才删得掉。
        junk = _store.unknown_keys()
        for k in junk:
            rows.append({'key': k, 'desc': '⚠ 文件里有、但没人认的键 (会被忽略)',
                         'current': _redact(json.dumps(cfg.get(k), ensure_ascii=False)),
                         'hint': f'删掉它: webtool config unset {k}'})
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
