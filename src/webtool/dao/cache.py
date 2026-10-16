"""磁盘缓存: 分桶 TTL (search 60s / fetch 10s / resolve 600s / hot 120s)

防短窗口内重复查询/抓取, 也避免对反爬引擎暴露重复行为模式; 新鲜度优先,
resolve 是稳定映射故给 10min。
"""
import hashlib
import json
import os
import time

from webtool.core.logging import get_logger

logger = get_logger(__name__)

TTL = {'search': 60, 'fetch': 10, 'resolve': 600, 'hot': 120, 'zen': 604800}


def _ttl(cfg, bucket):
    """分桶 TTL: 内置默认 + 用户 config set cache_ttl.<bucket>=<sec> 覆盖"""
    over = (cfg or {}).get('cache_ttl')
    if isinstance(over, dict) and bucket in over:
        try:
            return float(over[bucket])
        except (TypeError, ValueError):
            pass
    return TTL.get(bucket, 3600)

def enabled(cfg):
    """磁盘缓存总开关 (`config set cache on|off`); 没设 = 开。

    曾经是死键: `cli/config.py` 的键表里有它, 但 `net.proxy.store` 的白名单
    (_KNOWN) 里没有, 于是用户设了也读不到 —— 配置能写能存, 就是没人读。
    """
    v = (cfg or {}).get('cache')
    if v is None or v == '':
        return True
    return str(v).strip().lower() in ('on', 'true', '1', 'yes', '开')


def _path(cfg, bucket, key):
    d = os.path.join(cfg.get('cache_dir') or os.path.expanduser('~/.webtool/cache'), bucket)
    os.makedirs(d, exist_ok=True)
    h = hashlib.sha256(key.encode('utf-8')).hexdigest()[:24]
    return os.path.join(d, h + '.json')

def get(cfg, bucket, key):
    if not enabled(cfg):
        logger.debug('cache 已关 (config cache=off), 跳过读取')
        return None
    p = _path(cfg, bucket, key)
    try:
        with open(p, encoding='utf-8') as f:
            obj = json.load(f)
        if time.time() - obj['t'] < _ttl(cfg, bucket):
            logger.debug('cache hit %s/%s', bucket, key[:40])
            return obj['v']
        os.unlink(p)
    except (OSError, KeyError, ValueError):
        pass
    logger.debug('cache miss %s/%s', bucket, key[:40])
    return None

def put(cfg, bucket, key, value):
    if not enabled(cfg):
        return
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
