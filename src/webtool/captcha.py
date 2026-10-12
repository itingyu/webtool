"""验证码识别 + 冷却 (state 持久化, 指数加长跨进程生效)

指纹与冷却秒数来自插件清单 engine.<name>.params:
    captcha_signs: [[算子, 值], ...]   算子 ∈ contains / title_contains / len_lt
    cooldown:      秒数               触发验证页后的静默期 (未声明用 30)
清单改动按 mtime 热生效, 新引擎不再改本文件。generic 段对所有引擎生效。
"""
import threading
import time

from webtool import state
from webtool.config_data import load as _cfg_load

# 验证页指纹的通用段: 任何引擎命中都算被拦 (Cloudflare 质询等)
_GENERIC_SIGNS = [
    ('title_contains', 'captcha'),
    ('title_contains', 'verify'),
    ('title_contains', '安全验证'),
    ('contains', 'cf-challenge'),
    ('contains', 'Just a moment'),
]
_DEFAULT_COOLDOWN = 30


def _engine_params():
    """engine 段插件表 (name -> params); mtime 热生效"""
    from webtool.plugins import table as _plugin_table
    return {n: (s.get('params') or {}) for n, s in _plugin_table('engine').items()}


def _signs_for(engine):
    ps = _engine_params().get(engine) or {}
    return [tuple(x) for x in (ps.get('captcha_signs') or ())] + _GENERIC_SIGNS


def detect(engine, html):
    """判定是否验证页. 返回 (blocked, hit_sign)"""
    if not html:
        return False, None
    signs = _signs_for(engine)
    low = html.lower()
    title_m = None
    tl = low.find('<title')
    if tl >= 0:
        te = low.find('</title>', tl)
        title_m = low[tl:te] if te > 0 else low[tl:tl + 200]
    for kind, val in signs:
        if kind == 'contains' and str(val).lower() in low:
            return True, f'{kind}:{val}'
        if kind == 'title_contains' and title_m and str(val).lower() in title_m:
            return True, f'{kind}:{val}'
        if kind == 'len_lt' and len(html) < val:
            return True, f'{kind}<{val}'
    return False, None


def mark_blocked(engine):
    """记录某引擎触发验证页, 进入冷却 (持久化, 指数加长跨进程生效)"""
    st = state.get_captcha(engine)
    st['hits'] += 1
    ps = _engine_params().get(engine) or {}
    cd = ps.get('cooldown', _DEFAULT_COOLDOWN)
    state.set_captcha(engine, time.time() + cd * min(st['hits'], 4), st['hits'])


def mark_ok(engine):
    """某引擎成功通过, 重置冷却与计数"""
    state.reset_captcha(engine)


def suspended(engine):
    return time.time() < state.get_captcha(engine).get('until', 0)


def cooldown_left(engine):
    return max(0, int(state.get_captcha(engine).get('until', 0) - time.time()))


def status():
    return state.info()['captcha']
