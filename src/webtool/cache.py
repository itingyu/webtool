# -*- coding: utf-8 -*-
"""磁盘缓存: 搜索 30min / 正文 24h / 跳转解析 7d 分桶 TTL"""
import hashlib
import json
import os
import time

TTL = {'search': 1800, 'fetch': 86400, 'resolve': 604800}


def _path(cfg, bucket, key):
    d = os.path.join(cfg.get('cache_dir') or os.path.expanduser('~/.webtool/cache'), bucket)
    os.makedirs(d, exist_ok=True)
    h = hashlib.sha256(key.encode('utf-8')).hexdigest()[:24]
    return os.path.join(d, h + '.json')


def get(cfg, bucket, key):
    p = _path(cfg, bucket, key)
    try:
        with open(p, encoding='utf-8') as f:
            obj = json.load(f)
        if time.time() - obj['t'] < TTL.get(bucket, 3600):
            return obj['v']
        os.unlink(p)
    except (OSError, KeyError, ValueError):
        pass
    return None


def put(cfg, bucket, key, value):
    p = _path(cfg, bucket, key)
    try:
        with open(p, 'w', encoding='utf-8') as f:
            json.dump({'t': time.time(), 'v': value}, f, ensure_ascii=False)
    except OSError:
        pass


def clear(cfg):
    import shutil
    d = cfg.get('cache_dir') or os.path.expanduser('~/.webtool/cache')
    if os.path.isdir(d):
        shutil.rmtree(d)
        return True
    return False


def info(cfg):
    d = cfg.get('cache_dir') or os.path.expanduser('~/.webtool/cache')
    n = 0
    size = 0
    for root, _, files in os.walk(d):
        for f in files:
            n += 1
            try:
                size += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return {'files': n, 'bytes': size, 'dir': d}


def handle(args, cfg):
    if args.action == 'clear':
        print('cache cleared' if clear(cfg) else 'no cache')
    else:
        print(json.dumps(info(cfg), ensure_ascii=False))
