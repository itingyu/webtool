# -*- coding: utf-8 -*-
"""跨进程持久状态: ~/.webtool/state.json

为什么需要: CLI 每次调用都是新进程, 内存里的冷却/熔断/cookie 一退出就丢:
- 冷却形同虚设 (90s 冷却只在本进程内有意义, 下次调用照打验证页)
- cookie 每次冷启动重新预热, 而 SUID/BAIDUID 这类「回头客」会话本身就是
  信任信号 — 持久化后比每次冷启动更像真人

内容:
- captcha:  各引擎冷却 {until, hits} (指数加长真正跨调用生效)
- cookies:  各引擎会话 cookie (curl_cffi jar 导出, 原子写盘)
- breakers: gnews 解码熔断 / 代理降级记忆
- probe:    代理探活缓存

写盘策略: 锁内变更 + tmp+rename 原子替换; 所有接口带 try/except,
state 坏了只影响性能不影响功能。
"""
import json
import os
import tempfile
import threading
import time

PATH = os.path.expanduser('~/.webtool/state.json')
TTL = {'cookies': 14 * 86400,          # cookie 保两周, 过期自动丢弃
       'probe': 60}

_lock = threading.RLock()   # 可重入: save_* → load() 嵌套持锁
_mem = None


def _empty():
    return {'captcha': {}, 'cookies': {}, 'breakers': {}, 'probe': {}}


def load():
    """读盘 → 内存缓存 (带锁, 进程内单例)"""
    global _mem
    with _lock:
        if _mem is None:
            _mem = _empty()
            try:
                with open(PATH, encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    for k in _empty():
                        if isinstance(data.get(k), dict):
                            _mem[k].update(data[k])
            except (OSError, ValueError):
                pass
        return _mem


def _save_locked():
    """原子写盘 (调用方持锁)"""
    try:
        os.makedirs(os.path.dirname(PATH), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(PATH), prefix='.state-')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(_mem, f, ensure_ascii=False)
        os.replace(tmp, PATH)
    except OSError:
        pass


# ---------------- captcha 冷却 ----------------

def get_captcha(engine):
    st = load().get('captcha', {}).get(engine)
    if not st:
        return {'until': 0.0, 'hits': 0}
    # 冷却自然过期后保留 hits 计数 (指数加长仍生效), until 清零
    if time.time() >= st.get('until', 0):
        st['until'] = 0.0
    return st


def set_captcha(engine, until, hits):
    with _lock:
        load()['captcha'][engine] = {'until': float(until), 'hits': int(hits)}
        _save_locked()


def reset_captcha(engine):
    with _lock:
        load()['captcha'][engine] = {'until': 0.0, 'hits': 0}
        _save_locked()


# ---------------- 会话 cookie ----------------

def save_cookies(engine, cookies):
    """cookies: [{name,value,domain,path,expires,secure}, ...] 过期项已滤除"""
    with _lock:
        load()['cookies'][engine] = {'ts': time.time(), 'items': cookies}
        _save_locked()


def load_cookies(engine):
    """返回合法 cookie 列表; 过期/超 TTL 返回空"""
    box = load().get('cookies', {}).get(engine)
    if not box:
        return []
    if time.time() - box.get('ts', 0) > TTL['cookies']:
        return []
    now = time.time()
    out = []
    for c in box.get('items', []):
        exp = c.get('expires')
        if exp and exp < now:            # 会话 cookie (exp=None) 保留
            continue
        out.append(c)
    return out


# ---------------- 熔断 / 代理记忆 / 探活 ----------------

def get_breaker(name):
    return load().get('breakers', {}).get(name, {})


def set_breaker(name, **kv):
    with _lock:
        load().setdefault('breakers', {}).setdefault(name, {}).update(kv)
        _save_locked()


def get_probe(key='proxy'):
    p = load().get('probe', {}).get(key)
    if p and time.time() - p.get('ts', 0) < TTL['probe']:
        return p.get('ok')
    return None


def set_probe(ok, key='proxy'):
    with _lock:
        load().setdefault('probe', {})[key] = {'ts': time.time(), 'ok': bool(ok)}
        _save_locked()


def info():
    """诊断: 各桶概况 (engines status / 调试用)"""
    m = load()
    now = time.time()
    return {
        'path': PATH,
        'captcha': {e: {'cooldown_left': max(0, int(s.get('until', 0) - now)),
                        'hits': s.get('hits', 0)}
                    for e, s in m.get('captcha', {}).items() if s.get('until', 0) > now or s.get('hits')},
        'cookies': {e: len(b.get('items', [])) for e, b in m.get('cookies', {}).items() if b.get('items')},
        'breakers': {k: v for k, v in m.get('breakers', {}).items()},
    }
