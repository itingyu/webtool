# -*- coding: utf-8 -*-
"""人机验证页识别与自动处置

识别 (captcha detect):
- 特征库: 每个引擎的验证页指纹 (标题/DOM标记/长度特征)
- 返回结构化 verdict: {blocked: bool, kind: 'captcha'|'rate_limit'|'ok', engine}

处置策略 (分层, 纯 HTTP 可做的都在这):
1. 指纹冷却: 被验证页拦截后按引擎冷却 (baidu 90s / sogou 30s), 冷却期直接跳过该引擎
2. 路径重试: 换 UA 池下一个 → 重建 cookie 会话 → 直连/代理互换 → 退避指数增长
3. 参数降级: 减 rn/条数, 去掉翻页参数, 换 market
4. 无法绕过 (Google reCAPTCHA JS 盒 / 百度滑块) → 明确报 kind 让上层换引擎,
   不做无意义重试浪费 token
"""
import random
import threading
import time

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

_state = {}          # engine -> {'until': ts, 'hits': n}
_lock = threading.Lock()


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
    """记录某引擎触发验证页, 进入冷却"""
    with _lock:
        st = _state.setdefault(engine, {'until': 0, 'hits': 0})
        st['hits'] += 1
        cd = COOLDOWN.get(engine, 30)
        # 连续触发则指数加长冷却
        st['until'] = time.time() + cd * min(st['hits'], 4)


def mark_ok(engine):
    """某引擎成功通过, 重置冷却与计数"""
    with _lock:
        _state[engine] = {'until': 0, 'hits': 0}


def suspended(engine):
    with _lock:
        st = _state.get(engine)
        return bool(st and time.time() < st['until'])


def cooldown_left(engine):
    with _lock:
        st = _state.get(engine)
        return max(0, int(st['until'] - time.time())) if st else 0


def status():
    with _lock:
        return {e: {'cooldown_left': cooldown_left(e), 'hits': st['hits']}
                for e, st in _state.items() if st.get('until', 0) > 0 or st.get('hits')}
