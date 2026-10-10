# -*- coding: utf-8 -*-
"""磁盘缓存: 搜索 60s / 正文 10s / 跳转解析 10min 分桶 TTL

TTL 语义 (2026-10-11 调整): 缓存主要防「短窗口内重复查询/重复抓取」——
1) 省时 2) 避免对反爬引擎暴露重复行为模式. 数据新鲜度优先于流量节省:
search/fetch 档位短, 数据基本实时; resolve 是永久事实映射, 仍给 10min.
"""
import hashlib
import json
import os
import time

TTL = {'search': 60, 'fetch': 10, 'resolve': 600}

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
