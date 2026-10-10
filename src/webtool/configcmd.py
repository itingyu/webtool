# -*- coding: utf-8 -*-
"""webtool config: 统一配置管理子命令

配置层级 (优先级从高到低):
1. 命令行参数 (--proxy / --block / --no-blocklist ...)
2. 引擎/站点级配置 (~/.webtool/config.json 的 engine_proxy)
3. 全局配置 (config set 写入的键)
4. 内置默认值

存 ~/.webtool/config.json, 与 proxy/blocklist 文件共存。
"""
import json
import os
import sys

CONFIG_PATH = os.path.expanduser('~/.webtool/config.json')

# 可配置键白名单: (键名, 说明, 合法值)
CONFIG_KEYS = {
    'proxy':            ('HTTP/SOCKS 代理地址', '如 http://127.0.0.1:2080 / socks5://...', None),
    'blocklist':        ('黑名单开关', 'on / off', ('on', 'off')),
    'ad_filter':        ('广告过滤开关', 'on / off', ('on', 'off')),
    'dedupe':           ('跨引擎去重开关', 'on / off', ('on', 'off')),
    'semantic':         ('语义排序开关', 'on / off', ('on', 'off')),
    'default_engines':  ('默认引擎组合', '逗号分隔: bing,sogou,baidu,google', None),
    'default_format':   ('默认输出格式', 'json / text / markdown', ('json', 'text', 'markdown')),
    'timeout':          ('请求超时秒数', '5 ~ 60 整数', int),
    'cache':            ('缓存开关', 'on / off', ('on', 'off')),
    'engine_proxy.<engine>': ('单引擎代理覆盖', '<engine>=<url> 形式 set, 如 engine_proxy.google=http://...', None),
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
    if key not in CONFIG_KEYS:
        return False, f'未知配置键: {key}\n可用键: {", ".join(CONFIG_KEYS)}'
    desc, hint, typ = CONFIG_KEYS[key]
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
        print(f'配置文件: {CONFIG_PATH}')
        print()
        for k, (desc, hint, _t) in CONFIG_KEYS.items():
            base = k.split('.')[0]
            if k.startswith('engine_proxy.'):
                v = cfg.get('engine_proxy', {})
                cur = json.dumps(v, ensure_ascii=False) if v else '(未设置)'
            else:
                cur = json.dumps(cfg.get(base, '(未设置)'), ensure_ascii=False)
            print(f'  {k:24} {desc}')
            print(f'  {"":24} 当前: {cur}   合法值: {hint}')
        return 0

    if args.action == 'get':
        if not args.key:
            print('usage: webtool config get <key>', file=sys.stderr)
            return 2
        base = args.key.split('.')[0]
        if args.key.startswith('engine_proxy.'):
            eng = args.key.split('.', 1)[1]
            print(json.dumps(cfg.get('engine_proxy', {}).get(eng, '(未设置)'), ensure_ascii=False))
        else:
            print(json.dumps(cfg.get(base, '(未设置)'), ensure_ascii=False))
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
        else:
            cfg[args.key] = v
        save_config(cfg)
        print(f'set {args.key} = {json.dumps(v, ensure_ascii=False)} -> {CONFIG_PATH}')
        return 0
    return 0
