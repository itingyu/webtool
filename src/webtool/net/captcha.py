"""验证页识别 + 冷却 (state 持久化, 指数加长跨进程生效)

判断只看响应本身: 通用特征 + 插件清单里所有 captcha_signs 合并成一张全局特征表,
不区分请求走的是哪个引擎。冷却按站点 (host) 记, 同一站不管从哪条路进来都算一笔账。
"""
import time

from webtool.dao import state

# 验证页指纹的通用段: 任何请求命中都算被拦 (Cloudflare 质询等)
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

# ── Cloudflare 质询 (非交互式 JS 质询: 浏览器里等几秒就自动放行那种) ──────
# 这类拦截纯 HTTP 过不了 —— 服务端要的是浏览器算出来的 token, 没有 JS 引擎
# 就拿不到。所以它单列一档: 冷却更久 (5 分钟起, 翻倍上限 4×), 报错里带处置
# 建议 (换线路/换引擎/接真浏览器求解), 免得用户以为是"多试几次就好"。
#
# 特征只取**质询页专有**的: cf-ray/turnstile/cf-mitigated 之外的泛用串不能进
# —— 正常文章页挂个 Turnstile 挂件、CF 站点带 cf-ray 页脚, 全站套用会把
# 正常页判成被拦, 而误判要付冷却代价 (指数加长, 很贵)。
_CF_COOLDOWN = 300
_CF_SIGNS = [
    ('title_contains', 'just a moment'),      # 质询页标题 (CF 签名)
    ('contains', 'cf-challenge-running'),
    ('contains', 'challenge-spinner'),
    ('contains', 'cf-please-wait'),
    ('contains', 'trk_jschal_js'),
    ('contains', '_cf_chl_opt'),
    ('contains', 'orchestrate/chl_page'),     # 质询编排接口路径
    ('contains', '/cdn-cgi/challenge-platform/h/'),
]
_CF_HINT = ('CF 质询(等几秒自动放行那种)纯 HTTP 过不了: 换出口线路/换引擎, '
            '或接真浏览器求解(远端 FlareSolverr/Byparr)取 cf_clearance 复用; '
            '求解与抓取须同一出口 IP 且 UA 一致')


_SIGNS, _SIGNS_AT, _SIGNS_TTL = [], 0.0, 5.0


def _all_signs():
    """全量特征: 通用段 + 清单中各引擎声明的 captcha_signs, 去重后合并

    引擎段在这里只是"特征存放位置", 不是判断条件 —— 请求不带引擎名也照样用。
    结果缓存 5s: 每条响应都重建 62 个插件的表要多花 ~4ms, 不值得。
    """
    global _SIGNS, _SIGNS_AT
    now = time.monotonic()
    if _SIGNS and now - _SIGNS_AT < _SIGNS_TTL:
        return _SIGNS
    from webtool.core.plugins import table as _plugin_table
    raw = list(_GENERIC_SIGNS)
    for spec in _plugin_table('engine').values():
        for kind, val in (spec.get('params') or {}).get('captcha_signs') or ():
            # len_lt 是站点专属启发式 (百度短页), 全站套用会把所有短页判成验证页;
            # 只合并不依赖站点体积的特征。
            if kind != 'len_lt':
                raw.append((kind, val))
    seen, out = set(), []
    for kind, val in raw:
        key = (kind, str(val))
        if key in seen:
            continue
        seen.add(key)
        out.append((kind, val))
    _SIGNS, _SIGNS_AT = out, now
    return out


def cf_detect(html, low=None, headers=None):
    """这是 Cloudflare 质询吗? → 特征串 (None = 不是)

    头优先: 官方给"这次被质询了"的标记是响应头 `cf-mitigated: challenge`,
    比正文特征可靠得多 —— 质询页正文随版本变, 这个头没变。

    正文特征只认质询页专有标记, 见 _CF_SIGNS 的注释 (泛用串会误伤正常页)。
    """
    if headers:
        try:
            v = str(headers.get('cf-mitigated') or '').strip().lower()
        except AttributeError:
            v = ''
        if v == 'challenge':
            return 'cf-mitigated: challenge'
    if not html:
        return None
    low = low if low is not None else html.lower()
    for kind, val in _CF_SIGNS:
        if kind == 'title_contains':
            tl = low.find('<title')
            if tl >= 0:
                te = low.find('</title>', tl)
                title = low[tl:te] if te > 0 else low[tl:tl + 200]
                if val.lower() in title:
                    return f'cf:{val}'
        elif kind == 'contains' and str(val).lower() in low:
            return f'cf:{val}'
    return None


def detect(html, low=None):
    """判定是否验证页. 返回 (blocked, hit_sign)

    low 可传已小写化的正文 (框架的 Ctx.lower() 缓存), 省掉每个插件各 lower 一遍
    几 MB 正文的开销。
    """
    if not html:
        return False, None
    signs = _all_signs()
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


def mark_blocked(site, base=None, kind=''):
    """记录某站点触发验证页, 进入冷却 (持久化, 指数加长跨进程生效)

    base: 冷却基数秒。CF 质询用 300 (5 分钟起) —— 那种拦截重试再快也没用,
    短冷却只会把 1 次拦截放大成连续请求, 反而把站点信誉打得更差。
    """
    st = state.get_captcha(site)
    st['hits'] += 1
    cd = base or _DEFAULT_COOLDOWN
    state.set_captcha(site, time.time() + cd * min(st['hits'], 4), st['hits'],
                      kind=kind)


def mark_ok(site):
    """某站点成功通过, 重置冷却与计数"""
    state.reset_captcha(site)


def suspended(site):
    return time.time() < state.get_captcha(site).get('until', 0)


def cooldown_left(site):
    return max(0, int(state.get_captcha(site).get('until', 0) - time.time()))


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
        """冷却期内就别发了 —— 这个站现在发也是白挨一下"""
        key = ctx.site
        if not key or not suspended(key):
            return None
        st = state.get_captcha(key)
        kind = st.get('kind') or 'captcha'
        return Hit(kind=kind, by=self.name, sign='冷却中',
                   why=('Cloudflare 质询拦截' if kind == 'cf_challenge'
                        else '验证页拦截'),
                   left=cooldown_left(key), hint=(_CF_HINT if kind == 'cf_challenge'
                                                  else ''))

    def inspect(self, ctx):
        # CF 质询先判: 它的正文也会命中通用特征 (标题 "Just a moment..."),
        # 但处置完全不同 —— 单独一档 kind, 冷却更久, 报错带建议
        sign = cf_detect(ctx.text, low=ctx.lower(), headers=ctx.headers)
        if sign:
            key = ctx.site
            return Hit(kind='cf_challenge', by=self.name, sign=sign,
                       why='Cloudflare 质询拦截',
                       left=cooldown_left(key) if key else 0, hint=_CF_HINT)
        if not ctx.text:
            return None
        blocked, sign = detect(ctx.text, low=ctx.lower())
        if not blocked:
            return None
        key = ctx.site
        return Hit(kind='captcha', by=self.name, sign=sign or '',
                   why='验证页拦截', left=cooldown_left(key) if key else 0)

    def note_ok(self, ctx):
        # 正常情况下 hits 已归零: 别为此每次成功请求都落盘 (state.json 写放大)
        key = ctx.site
        if key and state.get_captcha(key).get('hits'):
            mark_ok(key)

    def note_hit(self, ctx, hit):
        key = ctx.site
        if key:
            base = _CF_COOLDOWN if hit.kind == 'cf_challenge' else None
            mark_blocked(key, base=base, kind=hit.kind)
            hit.left = cooldown_left(key)          # 报错信息要用 (见接口契约)


register(CaptchaInterceptor)
