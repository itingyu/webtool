# -*- coding: utf-8 -*-
"""带自动降级的 HTTP 获取: 代理失败(超时/拒连/5xx)自动切直连重试

策略:
- 配置了代理时: 先走代理, 失败(连接类错误或 429/5xx)再直连重试一次
- 记忆降级: 代理连续失败 >= 2 次后, 后续请求直连优先(60s 冷却期内不再试代理)
- 直连成功/代理恢复即重置计数
"""
import threading
import time

_state = {'proxy_fails': 0, 'direct_until': 0.0}
_lock = threading.Lock()
COOLDOWN = 60          # 代理连败后的直连冷却秒数
FAIL_THRESHOLD = 2     # 触发冷却的连续失败次数


class FetchError(Exception):
    pass


def _note(ok, used_proxy):
    with _lock:
        if ok:
            _state['proxy_fails'] = 0
        elif used_proxy:
            _state['proxy_fails'] += 1
            if _state['proxy_fails'] >= FAIL_THRESHOLD:
                _state['direct_until'] = time.time() + COOLDOWN


def proxy_suspended():
    return time.time() < _state['direct_until']


def fetch(url, proxy=None, timeout=15, headers=None, opener=None,
          fallback_direct=True):
    """返回 (text, status, via)  via: 'proxy' | 'direct'

    代理不稳定时自动降级:
    1. 代理请求抛连接类异常(URLError/timeout/refused/reset) -> 直连重试
    2. 代理返回 429/5xx -> 直连重试
    3. 连续 >= FAIL_THRESHOLD 次失败 -> COOLDOWN 秒内跳过代理直接直连
    4. 两者都失败 -> 抛 FetchError(附两个错误信息)
    """
    from .http import http_get
    attempts = []
    use_proxy_first = bool(proxy) and not (fallback_direct and proxy_suspended())

    order = []
    if use_proxy_first:
        order = [('proxy', proxy), ('direct', None)]
    elif proxy:
        order = [('direct', None), ('proxy', proxy)]
    else:
        order = [('direct', None)]

    last_err = None
    for mode, p in order:
        try:
            text, status = http_get(url, proxy=p, timeout=timeout,
                                    headers=headers, opener=opener)
            if mode == 'proxy' and status in (429, 500, 502, 503, 504) and fallback_direct:
                attempts.append(f'{mode}:HTTP{status}')
                _note(False, True)
                last_err = f'{mode} HTTP {status}'
                continue
            _note(True, mode == 'proxy')
            return text, status, mode
        except Exception as e:
            attempts.append(f'{mode}:{type(e).__name__}')
            _note(False, mode == 'proxy')
            last_err = f'{mode}: {e}'
            continue

    raise FetchError(f'{url} failed [{", ".join(attempts)}] last={last_err}')
