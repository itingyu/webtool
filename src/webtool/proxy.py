# -*- coding: utf-8 -*-
"""代理与全局配置: ~/.webtool/config.json"""
import json
import os
import sys
import time

CONFIG_PATH = os.path.expanduser('~/.webtool/config.json')

DEFAULTS = {
    'proxy': None,
    'engine_proxy': {
        'bing': None, 'sogou': None,
        'duckduckgo': None, 'jina': None,
    },
    'fetch_proxy': None,
    'timeout': 15,
    'ua': 'auto',
    'cache_dir': os.path.expanduser('~/.webtool/cache'),
}


def load_config():
    cfg = json.loads(json.dumps(DEFAULTS))  # deep copy
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding='utf-8') as f:
                user = json.load(f)
            cfg.update({k: v for k, v in user.items() if k in cfg})
        except Exception:
            pass
    return cfg


def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def handle(args, cfg):
    """webtool proxy get|set|unset|test"""
    if args.action == 'get':
        p = cfg.get('proxy')
        print(p if p else '(no proxy configured)')
        print('engine_proxy:', json.dumps(cfg.get('engine_proxy') or {}))
        return
    if args.action == 'set':
        val = args.value
        if not val:
            print('usage: webtool proxy set http://host:port  (支持 http/https/socks5://)', file=sys.stderr)
            return 2
        val = val.rstrip('/')
        if not val.startswith(('http://', 'https://', 'socks5://', 'socks5h://')):
            val = 'http://' + val
        cfg['proxy'] = val
        save_config(cfg)
        print(f'proxy saved: {val} -> {CONFIG_PATH}')
        return
    if args.action == 'unset':
        cfg['proxy'] = None
        save_config(cfg)
        print('proxy cleared')
        return
    if args.action == 'test':
        val = args.value or cfg.get('proxy')
        if not val:
            print('no proxy to test. use: webtool proxy test http://127.0.0.1:2080', file=sys.stderr)
            return 2
        import urllib.request
        from . import http as _http
        try:
            if val.startswith('socks'):
                try:
                    import socks  # noqa: F401
                except ImportError:
                    print('socks 代理需要 pysocks: pip install pysocks', file=sys.stderr)
                    return 2
            opener = _http.build_opener(val)
            t0 = time.time()
            r = opener.open(urllib.request.Request('https://www.bing.com/robots.txt',
                              headers={'User-Agent': 'Mozilla/5.0'}), timeout=10)
            body = r.read(64)
            print(f'OK {r.status} {len(body)}B in {time.time()-t0:.1f}s via {val}')
        except Exception as e:
            print(f'FAIL via {val}: {e}', file=sys.stderr)
            return 1
