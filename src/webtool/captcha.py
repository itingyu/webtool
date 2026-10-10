# -*- coding: utf-8 -*-
"""验证码识别 + 冷却 (state 持久化, 指数加长跨进程生效)"""
import threading
import time

from . import state

# ---- 验证页指纹 (按引擎) ----
CAPTCHA_SIGNS = {
    'baidu': [
        ('title_contains', '百度安全验证'),
        ('contains', 'wappass.baidu.com'),
        ('contains', 'mkdjump_v2'),
        ('len_lt', 2000),
    ],
    'sogou': [
        ('contains', 'antispider'),
        ('title_contains', '验证码'),
        ('contains', 'seccodeimage'),
        ('contains', '403 forbidden'),   # nginx 硬拦 (DC IP 常见)
        ('len_lt', 1300),                # 564B/1150B 跳转壳都算被拦
    ],
    'google': [
        ('contains', 'unusual traffic'),
        ('contains', 'www.google.com/sorry'),
        ('contains', 'recaptcha'),
    ],
    'bing': [
        ('contains', 'challenge-form'),   # DDG 同款 anomaly, bing 极少触发
    ],
    'generic': [
        ('title_contains', 'captcha'),
        ('title_contains', 'verify'),
        ('title_contains', '安全验证'),
        ('contains', 'cf-challenge'),
        ('contains', 'Just a moment'),
    ],
}

# 引擎冷却秒数: 触发验证页后, 该引擎静默期
COOLDOWN = {'baidu': 90, 'sogou': 30, 'google': 300, 'bing': 30, 'generic': 30}


def detect(engine, html):
    """判定是否验证页. 返回 (blocked, hit_sign)"""
    if not html:
        return False, None
    signs = CAPTCHA_SIGNS.get(engine, []) + CAPTCHA_SIGNS['generic']
    low = html.lower()
    title_m = None
    tl = low.find('<title')
    if tl >= 0:
        te = low.find('</title>', tl)
        title_m = low[tl:te] if te > 0 else low[tl:tl + 200]
    for kind, val in signs:
        if kind == 'contains' and val.lower() in low:
            return True, f'{kind}:{val}'
        if kind == 'title_contains' and title_m and val.lower() in title_m:
            return True, f'{kind}:{val}'
        if kind == 'len_lt' and len(html) < val:
            return True, f'{kind}<{val}'
    return False, None


def mark_blocked(engine):
    """记录某引擎触发验证页, 进入冷却 (持久化, 指数加长跨进程生效)"""
    st = state.get_captcha(engine)
    st['hits'] += 1
    cd = COOLDOWN.get(engine, 30)
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
