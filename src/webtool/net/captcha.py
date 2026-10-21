"""验证码识别 + 冷却 (state 持久化, 指数加长跨进程生效)

指纹与冷却秒数来自插件清单 engine.<name>.params:
    captcha_signs: [[算子, 值], ...]   算子 ∈ contains / title_contains / len_lt
    cooldown:      秒数               触发验证页后的静默期 (未声明用 30)
清单改动按 mtime 热生效, 新引擎不再改本文件。generic 段对所有引擎生效。
"""
import time

from webtool.dao import state

# 验证页指纹的通用段: 任何引擎命中都算被拦 (Cloudflare 质询等)
# 只放"整句/专有标记": 裸 'verify' 会把标题含 Verify 的正常文章判成验证页,
# 而验证页冷却呈指数加长 —— 误判一次要等很久。
_GENERIC_SIGNS = [
    ('title_contains', 'captcha'),
    ('title_contains', '安全验证'),
    ('title_contains', 'verify you are human'),
    ('title_contains', 'just a moment'),
    ('title_contains', 'attention required'),
    ('contains', 'cf-challenge'),
    ('contains', 'checking your browser'),
]
_DEFAULT_COOLDOWN = 30


def _engine_params():
    """engine 段插件表 (name -> params); mtime 热生效"""
    from webtool.core.plugins import table as _plugin_table
    return {n: (s.get('params') or {}) for n, s in _plugin_table('engine').items()}


def _signs_for(engine):
    ps = _engine_params().get(engine) or {}
    return [tuple(x) for x in (ps.get('captcha_signs') or ())] + _GENERIC_SIGNS


def detect(engine, html, low=None):
    """判定是否验证页. 返回 (blocked, hit_sign)

    low 可传已小写化的正文 (框架的 Ctx.lower() 缓存), 省掉每个插件各 lower 一遍
    几 MB 正文的开销。
    """
    if not html:
        return False, None
    signs = _signs_for(engine)
    # 先看长度: 短页是最便宜的命中, 命中就不必再扫全文
    for kind, val in signs:
        if kind == 'len_lt' and len(html) < val:
            return True, f'{kind}<{val}'
    low = low if low is not None else html.lower()
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


# ── 拦截绕过接口的实现 ────────────────────────────────────────────────────
# 验证页是"被挡住"的一种, 但 transport 不该知道"验证码"这三个字: 它只问
# intercept 两句 —— 这次被挡了吗、有没有绕法。所以这里把上面几个函数包成
# 一个 Interceptor: 判定与冷却记账都归它, 将来换/加策略只动插件。

from webtool.net.intercept import Hit, Interceptor, register   # noqa: E402


class CaptchaInterceptor(Interceptor):
    """人机验证页: 只判不绕

    现在没有通用解法 (点选/滑块得靠外部服务), 所以 bypass 返回 None —— 由
    transport 按冷却 + 降级梯处理。将来接上打码服务, 只要在这里实现 bypass
    返回一个 Bypass 就行, transport 不用改。
    """

    name = 'captcha'
    priority = 10                   # 最基础的拦截类型, 先判
    cooldown = _DEFAULT_COOLDOWN
    cools_down = True               # 会累计冷却 → 参与 preflight / note_ok

    def preflight(self, ctx):
        """冷却期内就别发了 —— 这个通道现在发也是白挨一下"""
        if not ctx.engine or not suspended(ctx.engine):
            return None
        return Hit(kind='captcha', by=self.name, sign='冷却中',
                   why='人机验证', left=cooldown_left(ctx.engine))

    def inspect(self, ctx):
        if not ctx.engine or not ctx.text:
            return None
        blocked, sign = detect(ctx.engine, ctx.text, low=ctx.lower())
        if not blocked:
            return None
        return Hit(kind='captcha', by=self.name, sign=sign or '',
                   why='验证页拦截', left=cooldown_left(ctx.engine))

    def note_ok(self, ctx):
        # 正常情况下 hits 已归零: 别为此每次成功请求都落盘 (state.json 写放大)
        if ctx.engine and state.get_captcha(ctx.engine).get('hits'):
            mark_ok(ctx.engine)

    def note_hit(self, ctx, hit):
        if ctx.engine:
            mark_blocked(ctx.engine)
            hit.left = cooldown_left(ctx.engine)   # 报错信息要用 (见接口契约)


register(CaptchaInterceptor)
