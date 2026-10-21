"""跨进程持久状态: ~/.webtool/state.json

CLI 每次调用都是新进程, 冷却/熔断/cookie 必须落盘才能跨调用生效,
回头客会话持久化更可信。写盘: 锁内变更 + tmp+rename 原子替换, 接口全带
try/except, state 坏了只影响性能不影响功能。
"""
import json
import os
import tempfile
import threading
import logging
import time

logger = logging.getLogger(__name__)

PATH = None                 # 显式覆盖 (测试/特殊部署); None → 按 WEBTOOL_DIR 现算
TTL = {'cookies': 14 * 86400,
       'probe': 60}

_lock = threading.RLock()   # 可重入: save_* → load() 嵌套持锁
_mem = None
_mem_path = None


def _path():
    """state.json 位置: 显式 PATH > WEBTOOL_DIR > ~/.webtool

    必须与 core.config_data 同源: WEBTOOL_DIR 表达的是"整份用户状态搬到别处",
    冷却/cookie/熔断跟着 config 走, 否则测试与多实例会写同一份 state。
    """
    if PATH:
        return PATH
    base = os.environ.get('WEBTOOL_DIR') or '~/.webtool'
    return os.path.join(os.path.expanduser(base), 'state.json')


def _empty():
    return {'captcha': {}, 'cookies': {}, 'breakers': {}, 'probe': {}}


def load():
    """读盘 → 内存缓存 (带锁, 进程内单例)

    路径变了 (显式改 PATH / WEBTOOL_DIR) 就重新读, 别把上一个目录的缓存
    带到新目录里。
    """
    global _mem, _mem_path
    with _lock:
        p = _path()
        if _mem is None or _mem_path != p:
            _mem = _empty()
            _mem_path = p
            try:
                with open(p, encoding='utf-8') as f:
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
    p = _path()
    d = os.path.dirname(p) or '.'
    try:
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, prefix='.state-')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(_mem, f, ensure_ascii=False)
        os.replace(tmp, p)
    except OSError:
        pass


# captcha 冷却

def get_captcha(engine):
    st = load().get('captcha', {}).get(engine)
    if not st:
        return {'until': 0.0, 'hits': 0, 'kind': ''}
    # 冷却自然过期后保留 hits 计数 (指数加长仍生效), until 清零
    if time.time() >= st.get('until', 0):
        st['until'] = 0.0
    return st


def set_captcha(engine, until, hits, kind=''):
    with _lock:
        load()['captcha'][engine] = {'until': float(until), 'hits': int(hits),
                                     'kind': kind or ''}
        _save_locked()


def reset_captcha(engine):
    with _lock:
        load()['captcha'][engine] = {'until': 0.0, 'hits': 0, 'kind': ''}
        _save_locked()


# 会话 cookie

def save_cookies(engine, cookies):
    """cookies: [{name,value,domain,path,expires,secure}, ...] 过期项已滤除"""
    if cookies is None or not isinstance(cookies, list):
        # 上游导出 cookie 失败时(曾返回 None)会把 items 写成 null, 落盘后
        # 下次 load_cookies 直接 TypeError, 而报错点离真凶很远。宁可少存一次
        logger.warning('state | 拒绝写入非列表 cookies engine=%s type=%s',
                       engine, type(cookies).__name__)
        return
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
    for c in (box.get('items') or []):      # 老数据可能是 null, 别炸在这
        exp = c.get('expires')
        if exp and exp < now:            # 会话 cookie (exp=None) 保留
            continue
        out.append(c)
    return out


# 熔断 / 代理记忆 / 探活

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
        'path': _path(),
        'captcha': {e: {'cooldown_left': max(0, int(s.get('until', 0) - now)),
                        'hits': s.get('hits', 0),
                        'kind': s.get('kind', '')}
                    for e, s in m.get('captcha', {}).items() if s.get('until', 0) > now or s.get('hits')},
        'cookies': {e: len(b.get('items', [])) for e, b in m.get('cookies', {}).items() if b.get('items')},
        'breakers': {k: v for k, v in m.get('breakers', {}).items()},
    }
