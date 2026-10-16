"""节奏控制与超时规则 (L7 请求节律): 每引擎最小间隔+抖动 + timeout 规则补位

从 net/transport 拆出 (P4); transport 再导出旧名 (_rule_timeout/_pace/_rate_of)
保兼容。二者是"请求该以什么节律发出去"的同一件事, 与指纹/会话/降级梯无关。
"""
import logging
import random
import threading
import time

logger = logging.getLogger(__name__)


def rule_timeout(url, timeout=None):
    """timeout 空缺时由 http 规则 (rules.json 的 kind:http 条目) 填补

    调用方显式传的 timeout 优先 —— 规则只接管"没指定"的场合 (特殊走规则,
    否则走通用 15s)。规则查询走已缓存的 Router, 每请求一次字典匹配, 开销可忽略。
    """
    if timeout is not None:
        return timeout
    try:
        from webtool.net import rules as _rules
        v = _rules.router().params_for('http', url).get('timeout')
        if v:
            logger.debug('http 规则 timeout=%s (%s)', v, url)
            return float(v)
    except Exception as e:
        logger.debug('http 规则查询失败, 用通用默认: %s', e)
    return 15


# 节奏控制 (每引擎最小间隔 + 抖动)

DEFAULT_RATE = 0.4
_last_hit = {}
_rate_lock = threading.Lock()


def rate_of(engine):
    """每引擎最小请求间隔秒数; engine.<name>.params.rate, 未声明用默认"""
    if not engine:
        return DEFAULT_RATE
    from webtool.core.plugins import table as _plugin_table
    spec = _plugin_table('engine').get(engine) or {}
    return (spec.get('params') or {}).get('rate', DEFAULT_RATE)


def pace(engine):
    """请求前节奏控制: 距上次请求不足 min_interval 时随机补足"""
    if not engine:
        return
    gap = rate_of(engine)
    with _rate_lock:
        last = _last_hit.get(engine, 0.0)
        wait = gap - (time.time() - last) + random.uniform(0.05, 0.4)
        _last_hit[engine] = time.time() + max(0.0, wait)
    if wait > 0:
        time.sleep(wait)
