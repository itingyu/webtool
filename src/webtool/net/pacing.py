"""节奏控制与超时规则 (L7 请求节律): 每引擎最小间隔+抖动 + timeout 规则补位

从 net/transport 拆出 (P4); transport 再导出旧名 (_rule_timeout/_pace/_rate_of)
保兼容。二者是"请求该以什么节律发出去"的同一件事, 与指纹/会话/降级梯无关。
"""
import logging
import os
import random
import threading
import time

logger = logging.getLogger(__name__)


_CFG_LOCK = threading.Lock()
_CFG_CACHE = (None, None)        # (stamp, timeout) —— 同 tls._load 的 mtime 缓存做法


def _cfg_timeout():
    """config.json 里的通用请求超时 (`webtool config set timeout N`)。

    带 mtime 缓存: 每请求都要问一次, 不能每请求读盘。配置改了就自动失效。
    """
    global _CFG_CACHE
    from webtool.net.proxy.store import CONFIG_PATH
    try:
        st = os.stat(CONFIG_PATH)
        stamp = (st.st_mtime_ns, st.st_size)
    except OSError:
        stamp = None
    with _CFG_LOCK:
        if _CFG_CACHE[1] is not None and _CFG_CACHE[0] == stamp:
            return _CFG_CACHE[1]
        try:
            from webtool.net.proxy import load_config
            v = (load_config() or {}).get('timeout')
            v = float(v) if v else None
        except Exception as e:
            logger.debug('config.json timeout 读取失败: %s', e)
            v = None
        _CFG_CACHE = (stamp, v)
        return v


def rule_timeout(url, timeout=None):
    """timeout 空缺时按「http 规则 → config.json → 内置 15」补位

    优先级: 调用方显式传的 > rules.json 的 kind:http 条目 (特殊站点特殊对待) >
    `config.json` 的 `timeout` (用户设的通用值) > 内置 15。

    中间那层曾经缺失 —— 兜底直接跳回内置 15, 于是 `webtool config set timeout 30`
    对**不显式传 timeout 的调用方** (搜索引擎全都如此) 完全失效: 用户改了配置,
    搜索还是 15s。与代理那次的 None/'auto' 是同一类毛病 —— 同一份配置在不同
    入口给出不同结果。

    **默认值必须是 None 而不是 15**: `timeout=15` 这种形参会短路整条链
    (看着像"没指定", 实际是"显式指定 15"), 配置永远轮不到。
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
    v = _cfg_timeout()
    if v:
        logger.debug('config.json timeout=%s (%s)', v, url)
        return v
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
