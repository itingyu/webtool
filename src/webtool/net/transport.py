"""统一传输层: curl_cffi 浏览器指纹 + 降级重试 + 节奏控制 + 验证码处置

UA 与 impersonate 版本严格对齐, header 按 kind 分型 (nav 页面导航 / xhr 页面
JS 请求 / api 公开 REST), sec-fetch-site 按可注册域判定; cookie 经 state
持久化; 被拦走 冷却→退避换指纹→代理直连互换 降级梯; 每引擎限速+抖动。

证书校验统一走 net.tls (ssl_verify / ca_bundle / verify_hosts), 每请求
按 URL 现算 verify 后传给 curl_cffi; 证书失败抛 TlsError 直接上抛, 不进
降级梯 —— 换指纹换代理对证书问题一点用没有, 只是把 1 次失败放大成 4 次。
"""
import logging
import random
import time
import urllib.error
import urllib.parse

from curl_cffi import requests as _cr
from curl_cffi.requests.exceptions import CertificateVerifyError
HAS_CFFI = True

logger = logging.getLogger(__name__)

# 指纹/档案层已拆到 net/fingerprints (P4); 这里再导出, 老引用 (transport.PROFILES 等) 不用改
from webtool.net.fingerprints import (  # noqa: E402,F401
    ACCEPT_XHR, LANG_EN, LANG_ZH, PROFILES, _ACCEPT_NAV, _ROTATION, _UA131,
    _sec_fetch_site, headers_for, pick_profile as _pick_profile,
    profile_for_impersonate,
)

# 节奏/超时层已拆到 net/pacing (P4); 这里再导出旧名, 老引用 (transport._pace 等) 不用改
from webtool.net.pacing import (  # noqa: E402,F401
    DEFAULT_RATE as _DEFAULT_RATE, pace as _pace, rate_of as _rate_of,
    rule_timeout as _rule_timeout,
)


from webtool.dao import state
from webtool.core import secrets_store
from webtool.net import tls
from webtool.core import urls
from webtool.net.tls import TlsError
from webtool.net import intercept

# 证书类异常的判定统一交给 net.tls.is_tls_error —— urllib 把 SSLError 裹在
# URLError.reason 里, requests.SSLError 又不是 ssl.SSLError 的子类,
# 任何类型元组都盖不全, 漏网的后果是证书失败被降级梯当成普通抖动重试 4 次

# 浏览器指纹档案 (UA 与 impersonate 版本严格对齐)






_registrable = urls.registrable   # 可注册域判定 (含 com.cn/co.uk 等二级后缀)

# 各引擎的实际入口。_new_session 只拿得到 engine 名, 而 'auto' 的线路要按
# 域名问路由表 —— 没有 URL 就只能退回默认动作, 于是 `*.cn` direct 这类规则
# 对会话失效 (而引擎会话打的恰恰是境内站, 最容易被分流)。调用方有实际 URL
# 时优先传 url=, 这里是没传时的兜底。
_ENGINE_URL = {
    'bing': 'https://cn.bing.com/search',
    'sogou': 'https://www.sogou.com/web',
    'baidu': 'https://www.baidu.com/s',
    'so360': 'https://www.so.com/s',
    'google': 'https://www.google.com/search',
    'marginalia': 'https://search.marginalia.nu/search',
}


# 节奏控制 (每引擎最小间隔 + 抖动) 已迁到 net/pacing

# header 构造





# 会话 (UA/cookie 固定, 持久化)

def _export_cookies(session):
    out = []
    try:
        for c in session.cookies.jar:
            out.append({'name': c.name, 'value': c.value or '',
                        'domain': c.domain, 'path': c.path,
                        'expires': c.expires, 'secure': bool(c.secure)})
    except Exception as e:
        logger.debug('transport | 导出会话 cookies 失败 (返回已收 %d 条): %s',
                     len(out), e, exc_info=True)
    return out


def _new_session(profile_name, proxy=None, engine=None, url=None):
    """新会话: 指纹档案 (名或 dict) + state 里的持久 cookie 预载

    `proxy` 走 netx 归一 —— 'auto' 之类的值原样塞给 curl_cffi 会被当成主机名解析
    (`Could not resolve proxy: auto`), 配了代理反而全挂。

    **url 必须传**: `'auto'`/`None` 的线路由路由表按域名决定, 没有目标 URL 就只能退回
    默认动作, 于是 `*.cn` direct 这类规则对会话失效 (引擎的会话恰恰是打
    境内站, 最容易被规则分流)。引擎手上都有实际要请求的 URL, 传进来即可。
    归一只对**同一个 URL** 幂等: 引擎自己先 resolve 过、再把已归一的 URL 传进来,
    不会二次补密码。但若拿另一个 URL (如 CN 端点) 判完再把结果回喂, 规则按
    path/port 写时就可能翻案 —— 提前归一过就回喂 `proxy or 'direct'`
    ('direct' 是"已判定直连"的幂等写法, 见 bing)。

    engines 取每个引擎的实际入口 (只用于判定线路, 不发请求)。
    """
    from webtool.net import netx
    if url is None and engine:
        url = _ENGINE_URL.get(engine)
    proxy = netx.resolve_proxy(proxy, url)
    if isinstance(profile_name, dict):
        p = profile_name
    else:
        p = PROFILES[profile_name]
    # trust_env=False: curl_cffi 默认读 http_proxy/https_proxy, 于是'直连' 的主机
    # 会被环境变量送去代理 —— 线路只认配置文件, 不信环境
    s = _cr.Session(impersonate=p['impersonate'], proxy=proxy or None,
                    trust_env=False)
    if engine:
        for c in state.load_cookies(engine):
            try:
                s.cookies.set(c['name'], c['value'], domain=c.get('domain'),
                              path=c.get('path') or '/')
            except Exception:
                pass
    return s, p


def _persist_cookies(session, engine):
    if engine:
        state.save_cookies(engine, _export_cookies(session))


# 异常

class BlockedError(RuntimeError):
    """验证码/风控页, 多通道尝试后仍被拦"""


class CooldownError(RuntimeError):
    """引擎处于反爬冷却期, 应换引擎"""


__all__ = ['BlockedError', 'CooldownError', 'TlsError', 'Resp', 'get',
           'headers_for', 'new_session', 'open_stream', 'request',
           'resolve_redirect', 'session_get', 'warm_session',
           'PROFILES', 'LANG_ZH', 'LANG_EN', 'ACCEPT_XHR']


# 主入口

# 反爬降级梯最大步数: 被拦后换指纹/换头重试几次。**默认 0 = 不降级**
# (首次被拦即报 BlockedError) —— 梯子会把 1 次被拦放大成多次请求, 默认关掉,
# 要的人 `webtool config set ladder_steps N` (或按站写规则)。例外: 插件明确
# 给出绕法时, 默认也放行一次 (只这一次, 见 _get_ladder), 否则 bypass 契约空转。
# 检测与冷却按站点算, 与请求挂不挂引擎名无关。
DEFAULT_LADDER_STEPS = 0




def _ladder_steps():
    from webtool.core.resilient import config_snapshot
    cfg = config_snapshot()
    v = cfg.get('ladder_steps')
    try:
        v = int(v) if v is not None else DEFAULT_LADDER_STEPS
    except (TypeError, ValueError):
        v = DEFAULT_LADDER_STEPS
    return max(0, v)


def get(url, *, kind='nav', referer=None, proxy=None, timeout=None,
        engine=None, rate_engine=None, headers=None, lang=LANG_ZH, max_bytes=8 * 1024 * 1024, profile=None,
        session=None, verify=None, _depth=0, raw=False, cookies=None):
    """浏览器指纹 GET → (text, status, via)

    via: 'cffi' | 'urllib'
    - engine: 仅用于限速/cookie 分桶等调度, 拦截判定不看它 (baidu/sogou/...)
    - rate_engine: 节奏控制的桶 (一般与 engine 相同, resolve 类可单列)
    - session: 外部管理的会话 (引擎自带预热流程时传入), 此时指纹档案取 profile
    - verify: 证书校验覆盖 (None=按 net.tls 全局策略; True/False 定点决定)
    - timeout: None 时由 http 规则 (kind:http) 填补, 仍无则通用默认 15s
    """
    timeout = _rule_timeout(url, timeout)
    if _depth == 0:
        # 冷却门只在顶层检查: 降级梯内部重试不受影响 (否则会撞上自己刚记的冷却)
        # 具体封多久、为什么封, 是拦截器自己的事 —— transport 只认结论。
        _hit = intercept.preflight(intercept.Ctx(url=url))
        if _hit is not None:
            raise CooldownError(
                f'{intercept.Ctx(url=url).site} 冷却中({_hit.left}s, '
                f'此前触发{_hit.why}), 请换站点或稍后再试')
    _pace(rate_engine or engine)

    # 代理归一交给 netx (唯一该碰代理的地方): 'auto' → 问路由表, 'user@host' →
    # 补保险库密码。这里不自己判断, 免得出现第二份与 netx 不一致的副本。
    from webtool.net import netx as _netx
    proxy = _netx.resolve_proxy(proxy, url)

    # 域级熔断: 同一个站在反复失败就别再打了 (阈值/冷却走 kind:breaker 规则)。
    # 这里只做短路, 不套 retry_call —— get 自己已有"换指纹→urllib"降级梯,
    # 再叠一层重试会把 1 次失败放大成 4 次, 正是当初引熔断要治的病。
    br = _breaker_guard(url)
    try:
        result = _get_ladder(url, kind=kind, referer=referer, proxy=proxy,
                             timeout=timeout, engine=engine,
                             rate_engine=rate_engine, headers=headers,
                             lang=lang, max_bytes=max_bytes, profile=profile,
                             session=session, verify=verify, raw=raw,
                             _depth=_depth, cookies=cookies)
    except Exception as e:
        _count_failure(br, e)
        raise
    br.record(True)
    return result


def _get_ladder(url, *, kind, referer, proxy, timeout, engine, rate_engine=None,
                headers=None, lang=None, max_bytes=0, profile=None, session=None,
                verify=None, raw=False, _depth=0, cookies=None):
    """取页本体: raw 直取 / 普通走拦截检测与降级梯 (熔断记账在 get 里)"""
    if raw:
        # raw 只要响应头 + 原始字节 (fetch 判目标类型/落盘用), 不进验证码降级梯:
        # 梯子是给"要正文"的通道用的, 二进制目标没有"被拦换指纹"这回事
        return _get_once(url, kind=kind, referer=referer, proxy=proxy,
                         timeout=timeout, engine=engine, headers=headers,
                         lang=lang, max_bytes=max_bytes, profile=profile,
                         session=session, verify=verify, raw=True,
                         cookies=cookies)

    text, status, via, rhdrs = _get_once(url, kind=kind, referer=referer,
                                         proxy=proxy, timeout=timeout,
                                         engine=engine, headers=headers, lang=lang,
                                         max_bytes=max_bytes, profile=profile,
                                         session=session, verify=verify,
                                         cookies=cookies)
    logger.debug('transport | GET %s -> %s via %s (timeout=%s)', url, status, via, timeout)
    # 拦截检测 + 降级梯: 拿到正文就判, 不看通道类型和引擎名
    # transport 不认识"验证码": 谁挡的、凭什么、要不要冷却、有没有绕法, 全问
    # net.intercept 的拦截器插件 (captcha 只是其中一个实现)。
    if not text:
        return text, status, via

    # 没挂引擎名的页面通道也要判 (fetch/resolve/radar 都从这儿过)。冷却/日志
    # 一律按站点分桶, 不按引擎 —— 谁挡的、挡的是哪个站, 与走哪条代码路径无关。
    ctx = intercept.Ctx(url=url, status=status, text=text, headers=rhdrs or {},
                        profile=profile or '', attempt=_depth, via=via)
    label = ctx.site
    hit = intercept.inspect(ctx)
    if hit is None:
        intercept.note_ok(ctx)
        if session is not None:
            _persist_cookies(session, engine)
        return text, status, via

    # 被拦: 记账 → 问绕法 → 退避 → 降级梯 (最多 ladder_steps 步; note_hit 记的
    # 冷却不影响梯内重试, 冷却门只在 _depth==0 检查)
    intercept.note_hit(ctx, hit)
    intercept.log(ctx, hit, 'blocked', detail=f'depth={_depth}')
    steps = _ladder_steps()
    bp = intercept.bypass(ctx, hit)
    if bp is not None and steps == 0 and _depth == 0:
        # 插件明确给了绕法: 默认也要试一次 —— 否则梯子关着时 bypass 成了摆设。
        # 只放一次: 失败即报错, 不把 1 次被拦放大成多次请求 (梯子的本意)。
        steps = 1
        logger.debug('transport | %s 被拦, 采用插件绕法: %s', label, bp.how)
    if _depth >= steps:
        intercept.log(ctx, hit, 'failed',
                      detail=f'重试{_depth}次仍被拦' + (f', 绕法: {bp.how}' if bp else ''))
        raise BlockedError(
            f'{label} {hit.why}({hit.sign}), 已重试{_depth}次仍被拦; '
            f'冷却{hit.left}s, 请换引擎'
            + (f'; {hit.hint}' if hit.hint else ''))
    delay = min(2 ** _depth, 4) + random.uniform(0, 0.8)
    if bp is not None:
        intercept.log(ctx, hit, 'bypass', detail=bp.how)
        # 插件给的绕法: 只改这一次重试的形状 (换地址/加头/换指纹/先等一会儿)。
        # 注意梯子本身只换**指纹会话**、线路不变 —— 被拦就偷偷退直连会让
        # "这条规则为什么对某些请求不生效"无法排查。
        if bp.delay:
            delay = bp.delay
        if bp.url:
            url = bp.url
        if bp.headers:
            headers = {**(headers or {}), **bp.headers}
        if bp.profile:
            profile = bp.profile
        if bp.cookies:
            # 插件给的 cookie (如求解器拿到的 cf_clearance) 灌进下一次重试的会话
            cookies = {**(cookies or {}), **bp.cookies}
        if bp.user_agent:
            headers = {**(headers or {}), 'User-Agent': bp.user_agent}
    time.sleep(delay)
    try:
        result = get(url, kind=kind, referer=referer, proxy=proxy,
                     timeout=timeout, engine=engine, rate_engine=rate_engine,
                     headers=headers, lang=lang,
                     max_bytes=max_bytes, profile=profile, session=None,
                     verify=verify, _depth=_depth + 1, cookies=cookies)
    except (CooldownError, TlsError):
        raise
    except BlockedError:
        # 梯内递归已把最终 BlockedError 组装好, 直接上抛 (google 等上层按此降级 news)
        raise
    except Exception as e:
        raise BlockedError(f'{label} {hit.why}({hit.sign}), 降级梯失败: '
                           f'{str(e)[:150]}; '
                           f'冷却{hit.left}s, 请换引擎')
    intercept.log(ctx, hit, 'passed', detail=f'重试{_depth + 1}次后通过')
    return result


def _lower_keys(headers):
    """响应头键统一小写 (cffi 本来就小写, urllib 是 Content-Type), 消费者别猜"""
    try:
        return {str(k).lower(): v for k, v in dict(headers).items()}
    except Exception:
        return {}


def _cookie_header(cookies):
    """把 cookie 字典拼成 Cookie 头 (给没有 jar 的通道用)"""
    return '; '.join(f'{k}={v}' for k, v in (cookies or {}).items()
                     if v is not None)


def _apply_cookies(session, url, cookies):
    """把插件给的 cookie 灌进会话 jar (如求解器拿到的 cf_clearance)

    灌 jar 而不是拼 Cookie 头: jar 能与会话自己的 cookie 一起发, 也不会
    覆盖掉目标站刚下发的 Set-Cookie。域名取 url 里的 host —— 目标站才认。
    """
    if not cookies:
        return
    host = url.split('//', 1)[-1].split('/', 1)[0].split(':', 1)[0]
    for k, v in cookies.items():
        if v is None:
            continue
        try:
            session.cookies.set(str(k), str(v), domain=host, path='/')
        except Exception as e:      # 非法 cookie 不该拖垮整条请求
            logger.debug('transport | 注入 cookie %s 失败: %s', k, e)


class _UrllibStream:
    """urllib 响应的流式外壳: 跟 curl_cffi 的 resp 用同一套读法

    下载路径只认 iter_content(chunk), 不该为"cffi 崩了"分出第二条下载代码 ——
    那意味着续传/进度/校验要在两处各写一遍, 迟早只修一处。
    """

    def __init__(self, r):
        self._r = r
        self.headers = r.headers
        self.status_code = r.status

    def iter_content(self, chunk_size=1024):
        while True:
            buf = self._r.read(chunk_size)
            if not buf:
                break
            yield buf

    def close(self):
        try:
            self._r.close()
        except Exception:
            pass


def open_stream(url, *, kind='nav', referer=None, proxy=None, timeout=None,
                engine=None, headers=None, lang=LANG_ZH, profile=None,
                verify=None, session=None):
    """打开请求但先不读 body, 返回 (resp, status, via, headers)

    resp.iter_content(n) 边收边给 —— 下载要流式落盘, 不能先整个读进内存。
    用来省掉"HEAD 探类型 + 再 GET 下载"那两次请求: 响应头到手后由调用方决定
    是整段读 (网页) 还是流式写盘 (二进制)。

    代理跟 get() 走同一条决策: 先 resolve_proxy 归一路由表, 再补保险库密码。
    下载和取页各判一次代理, 迟早出现"网页能取、同一个站的文件下不来"。
    """
    from webtool.net import netx as _netx
    timeout = _rule_timeout(url, timeout)
    proxy = _netx.resolve_proxy(proxy, url)
    proxy_arg = None if proxy == 'direct' else proxy
    if proxy_arg:
        proxy_arg = secrets_store.resolve_auth(proxy_arg)
    try:
        if session is not None:
            s, p = session, (profile or PROFILES['chrome131_win'])
        else:
            if isinstance(profile, dict):
                prof, p = 'custom', profile
            else:
                prof = profile or _pick_profile(engine)
                p = PROFILES[prof]
            s = _new_session(prof, proxy_arg, engine)[0]
        h = headers_for(kind, url, referer=referer, lang=lang, profile=p, extra=headers)
        r = s.get(url, headers=h, timeout=timeout, allow_redirects=True,
                  verify=tls.policy(url, verify), stream=True)
        return r, r.status_code, 'cffi', _lower_keys(r.headers)
    except CertificateVerifyError as e:
        raise TlsError(_tls_msg(url, verify, e)) from e
    except Exception:
        # cffi 崩了 (缺 so/证书栈异常) 才走 urllib 全指纹兜底, 跟 _get_once 同策略
        pass
    from webtool.net.http import http_open
    h = headers_for(kind, url, referer=referer, lang=lang, full=True, extra=headers)
    r = http_open(url, proxy=proxy_arg, timeout=timeout, headers=h, verify=verify)
    return _UrllibStream(r), r.status, 'urllib', _lower_keys(r.headers)


class Resp:
    """统一响应外壳: cffi 与 urllib 两条底层给出同一种读法

    调用方 (MCP / LLM / 行情) 只认这几个成员, 不必知道这次走的是哪条底层 ——
    也就不会出现"某条路线上少判一次代理/证书"的分裂。
    """

    def __init__(self, r, via='cffi'):
        self._r = r
        self.via = via
        self._content = None
        self.status_code = int(getattr(r, 'status_code', None)
                               or getattr(r, 'status', None)
                               or getattr(r, 'code', 0) or 0)
        self.headers = _lower_keys(getattr(r, 'headers', {}) or {})
        self.url = str(getattr(r, 'url', '') or '')

    @property
    def content(self):
        if self._content is None:
            c = getattr(self._r, 'content', None)
            if c is None:
                c = self._r.read()
                if self.headers.get('content-encoding') == 'gzip':
                    try:                       # urllib 不自动解 gzip
                        import gzip as _gz
                        import io as _io
                        c = _gz.GzipFile(fileobj=_io.BytesIO(c)).read()
                    except Exception:          # noqa: BLE001 解不开就用原字节
                        pass
            self._content = c or b''
        return self._content

    @property
    def text(self):
        t = getattr(self._r, 'text', None)
        if isinstance(t, str):
            return t                           # cffi 自己按头/内容猜的编码
        data = self.content
        cs = ''
        ct = str(self.headers.get('content-type', ''))
        if 'charset=' in ct:
            cs = ct.split('charset=')[-1].split(';')[0].strip()
        if not cs:
            from webtool.net.http import _sniff_charset
            cs = _sniff_charset(data) or 'utf-8'
        try:
            return data.decode(cs, errors='replace')
        except LookupError:
            return data.decode('utf-8', errors='replace')

    def json(self):
        import json as _json
        return _json.loads(self.text)

    def iter_content(self, chunk_size=65536):
        def _chunks():
            data = self.content
            for i in range(0, len(data), chunk_size):
                yield data[i:i + chunk_size]

        it = getattr(self._r, 'iter_content', None)
        # cffi 的 iter_content 只对 stream=True 的响应有效, 其余会当场断言;
        # 用它之前先看队列在不在, 免得"能不能流读"变成调用方的负担
        if it is not None and getattr(self._r, 'queue', None):
            def _gen():
                try:
                    for c in it(chunk_size):
                        yield c
                except AssertionError:          # noqa: BLE001 退化成整块切
                    for c in _chunks():
                        yield c
            return _gen()
        return _chunks()

    @property
    def raw(self):
        """底层响应对象 —— 流式读 (read1/lines) 这类特殊读法要拿它

        只给"确实需要字节级控制"的调用方 (LLM 的 SSE: read1 有多少读多少,
        read(n) 会阻塞到攒满 n 字节, 流式就没了)。
        """
        return self._r

    def close(self):
        try:
            self._r.close()
        except Exception:                      # noqa: BLE001 关不掉就算了
            pass


def new_session(profile=None, proxy=None, engine=None, url=None):
    """建一个外部会话 (要预热/攒 cookie 时用): 指纹与线路都按本层规矩

    返回 (session, 档案 dict)。线路归一到 netx 并补保险库密码 —— 自己拼一个
    Session 再塞个 'auto' 进去, 只会在解析主机名时炸, 报错还指不到配置。
    """
    proxy = _resolve_proxy_auth(proxy, url)
    prof = profile or _pick_profile(engine)
    return _new_session(prof, proxy, engine, url)


def _resolve_proxy_auth(proxy, url):
    """线路归一 (netx) + 补保险库密码 —— 唯一该做的两件事, 别处不许各判一份"""
    from webtool.net import netx as _netx
    p = _netx.resolve_proxy(proxy, url)
    if p and p != 'direct':
        p = secrets_store.resolve_auth(p)
    return p


# 熔断原语已收口到 core.resilient (get/request/download 三通道共用);
# 这里保留同名转发, 老调用点与测试按老路径取用不受影响
from webtool.core.resilient import BreakerOpenError as BreakerOpenError


def _breaker_guard(url):
    """域级熔断检查: 打开期直接短路 (不发请求)"""
    from webtool.core.resilient import guard
    return guard(url)


def _count_failure(br, e):
    """记账: 只有"这台站点不给数据"算失败; 证书错是配置问题, 不该连坐熔断"""
    from webtool.core.resilient import count_failure
    count_failure(br, e, exempt=(TlsError,))


def request(method, url, **kw):
    """弹性入口: 熔断检查 + 幂等方法按 retry 规则重试; 本体 _request_once

    熔断按域名计 (core.resilient.Breaker, 阈值/冷却走 kind:breaker 规则);
    重试只对幂等方法 (GET/HEAD), 次数/退避走 kind:retry 规则。非幂等
    (POST/PUT) 不重试也不套重试循环 —— 重复提交不是弹性是事故。
    """
    from webtool.core import logging as _log
    from webtool.core.resilient import retry_call
    br = _breaker_guard(url)
    m = (method or 'GET').upper()
    with _log.timed(logger, 'HTTP %s' % m, url=url):
        if m in ('GET', 'HEAD'):
            return _guarded(br, lambda: retry_call(
                lambda: _request_once(method, url, **kw), url=url))
        return _guarded(br, lambda: _request_once(method, url, **kw))


def _guarded(br, fn):
    """成败都记账: 成功清零连败, 失败累计 (到阈值由 Breaker 打开)"""
    try:
        r = fn()
    except Exception as e:
        _count_failure(br, e)
        raise
    br.record(True)
    return r


def _request_once(method, url, *, kind='api', referer=None, proxy=None, timeout=None,
            engine=None, rate_engine=None, headers=None, lang=LANG_ZH,
            profile=None, session=None, cookiejar=None, via='auto', verify=None,
            params=None, data=None, json_body=None, allow_redirects=True,
            stream=False, raw_headers=False):
    """通用请求 (GET/POST/...): 代理、证书、指纹、会话全按本层决策 → Resp

    与 get() 的分工: get() 是**抓页面**的通道, 带反爬判定与降级梯; 这条不带
    (engine 在这里只用来挑指纹档案与限速桶)。给"不该有验证码语义"的通道用:
    MCP 服务、LLM API、行情接口 —— 这些上游不会弹人机验证页, 套上判定只是
    多读一遍正文的开销。

    via 选底层: 'auto' (cffi 指纹优先, 失败退 urllib) / 'urllib' (强制) /
    'cffi' (强制)。**它是兜底路径的立身之本**: sogou 的 urllib 兜底、gnews 的
    article 通道之所以能当兜底, 靠的就是换一套 HTTP/TLS 栈, 全塞回 cffi 就等于
    没有兜底。cookie 连续性三种给法: `session` (cffi Session) / `cookiejar`
    (stdlib CookieJar, 走 urllib)。

    raw_headers=True 表示请求头由调用方全权给定 (LLM 这类对上家协议敏感的通道):
    这条走**不带 impersonate** 的底层, 所以连 sec-fetch-*/客户端提示都不会被
    悄悄塞进去 —— 本层只负责线路与证书。(给了 session= 则 session 优先: 那时
    调用方要的是 cookie 连续性。)
    """
    proxy = _resolve_proxy_auth(proxy, url)
    proxy_arg = None if proxy == 'direct' else proxy
    timeout = _rule_timeout(url, timeout)
    if engine:
        _pace(rate_engine or engine)
    use_urllib = via == 'urllib' or cookiejar is not None \
        or (raw_headers and session is None)
    if session is not None:
        s, p = session, (profile if isinstance(profile, dict) else
                         (PROFILES.get(profile) if profile
                          else PROFILES['chrome131_win']))
    else:
        s, p = _new_session(profile or _pick_profile(engine), proxy_arg,
                            engine, url)
    if raw_headers:
        h = dict(headers or {})
        h_urllib = dict(headers or {})
    else:
        # cffi 只补 impersonate 不会发的头 (UA/sec-ch-* 由指纹自己带, 手动传
        # 反而可能与 TLS 版本错位); urllib 没有 impersonate, 得补全套
        h = headers_for(kind, url, referer=referer, lang=lang, profile=p,
                        extra=headers)
        h_urllib = headers_for(kind, url, referer=referer, lang=lang,
                               profile=p, extra=headers, full=True)
    if not use_urllib:
        try:
            r = s.request((method or 'GET').upper(), url, headers=h,
                          params=params, data=data, json=json_body,
                          timeout=timeout, verify=tls.policy(url, verify),
                          allow_redirects=allow_redirects, stream=stream)
            return Resp(r, 'cffi')
        except CertificateVerifyError as e:
            raise TlsError(_tls_msg(url, verify, e)) from e
        except Exception:                      # noqa: BLE001 换 urllib 兜底
            pass
    body = data
    if json_body is not None:
        import json as _json
        body = _json.dumps(json_body).encode('utf-8')
        h_urllib.setdefault('Content-Type', 'application/json')
    if params:
        sep = '&' if '?' in url else '?'
        url = url + sep + urllib.parse.urlencode(params)
    from webtool.net.http import http_open
    try:
        r = http_open(url, proxy=proxy_arg, timeout=timeout, headers=h_urllib,
                      verify=verify, method=method, data=body,
                      cookiejar=cookiejar, allow_redirects=allow_redirects)
    except urllib.error.HTTPError as e:
        r = e                                  # HTTPError 本身就是可读的响应
    return Resp(r, 'urllib')


# 适配器里的方法参数就叫 request (requests 的签名), 会遮住本模块的 request()
# —— 别名一个名字给它, 免得"看起来在调自己"




def _proxy_choice(proxies, override):
    """requests 传进来的请求级 `proxies=` → 本层的 proxy 取值

    - 给了真代理 → 用它
    - 给了键却没给值 (`{'https': None}`) → "这条强制直连"
    - `{}` / `None` → **调用点没表态**, 按建成时的 override ('auto' 即问路由表)

    那个 `{}` 是最坑的一格: requests 的 `Session.send` 每回都会把
    `merge_setting(request.proxies, session.proxies)` 塞给适配器, 而
    `requests_session` 建出来的 session 恰好 `proxies={}` —— 于是**每一发**
    都带着个空 dict 进来。老代码把它读成"调用点表态了: 强制直连", 结果整个
    stock 桥 (61 处 requests_session) 一律直连, `rules.json` 形同虚设 ——
    实测规则写着走代理, 日志却是 `线路=直连 (显式direct)`, 请求照样直连出门。
    """
    if proxies:
        return proxies.get('https') or proxies.get('http') or 'direct'
    return override


# requests 兼容适配器已拆到 net/adapters (P4); 再导出保兼容
from webtool.net.adapters import requests_session  # noqa: E402,F401


def _get_once(url, *, kind, referer, proxy, timeout, engine, headers,
              lang, max_bytes, profile, session, verify=None, raw=False,
              cookies=None):
    """单次请求: curl_cffi 浏览器指纹 → (cffi 崩了才走) urllib 全指纹兜底

    证书策略每请求现算 (tls.policy 会看 verify_hosts 白名单), cffi 与 urllib
    两条通道拿同一个决定, 不会出现"cffi 拒了 urllib 放行"的分裂。

    代理里的 `user@host` 在这里补上保险库密码 —— 配置文件里只有用户名与密文,
    明文密码不落盘; curl_cffi 与 urllib 两条通道都在这里补, 行为一致。
    """
    proxy_arg = None if proxy == 'direct' else proxy
    if proxy_arg:
        # 密码缺失要立刻说清楚, 不能拿空密码去撞 407 (那报错完全指不到原因)
        proxy_arg = secrets_store.resolve_auth(proxy_arg)
    last_cffi_err = 'skipped'
    # 通道1: curl_cffi
    try:
        if session is not None:
            s = session
            p = profile or PROFILES['chrome131_win']
        else:
            # profile 可传档案名 (str) 或档案 dict; dict 时直接用
            if isinstance(profile, dict):
                prof = profile
                p = profile
            else:
                prof = profile or _pick_profile(engine)
                p = PROFILES[prof]
            s = _new_session(prof, proxy_arg, engine)[0]
        _apply_cookies(s, url, cookies)
        h = headers_for(kind, url, referer=referer, lang=lang, profile=p,
                        extra=headers)
        r = s.get(url, headers=h, timeout=timeout, allow_redirects=True,
                  verify=tls.policy(url, verify))
        payload = r.content[:max_bytes] if raw else r.text[:max_bytes]
        if session is None:
            _persist_cookies(s, engine)
        if raw:
            return payload, r.status_code, 'cffi', _lower_keys(r.headers)
        return payload, r.status_code, 'cffi', _lower_keys(r.headers)
    except CertificateVerifyError as e:
        # 硬失败: 证书不对就是不对, 换指纹/换代理/换 urllib 全都救不了,
        # 直接上抛, 别让降级梯把 1 次失败放大成 4 次
        raise TlsError(_tls_msg(url, verify, e)) from e
    except Exception as e:
        last_cffi_err = f'{type(e).__name__}: {str(e)[:150]}'
        # cffi 崩了才轮到 urllib。成功结果里只有 via=urllib, 不带原因 ——
        # 这条是"为什么这次换了通道/为什么慢/为什么特征变了"的唯一线索
        logger.debug('transport | cffi 通道失败, 降级 urllib url=%s kind=%s: %s',
                     url, kind, last_cffi_err)
    # 通道2: urllib (仅 cffi 自身崩溃时)
    from webtool.net.http import http_get
    h = headers_for(kind, url, referer=referer, lang=lang, full=True,
                    extra=headers)
    # urllib 通道没有 cookie jar, 插件给的 cookie 只能拼成 Cookie 头
    if cookies:
        h = {**h, 'Cookie': _cookie_header(cookies)}
    try:
        if raw:
            body, status, hdrs = http_get(url, proxy=proxy_arg, timeout=timeout,
                                          headers=h, max_bytes=max_bytes,
                                          verify=verify, raw=True)
            return body, status, 'urllib', _lower_keys(hdrs)
        text, status, hdrs = http_get(url, proxy=proxy_arg, timeout=timeout,
                                      headers=h, max_bytes=max_bytes,
                                      verify=verify, with_headers=True)
        return text, status, 'urllib', _lower_keys(hdrs)
    except Exception as e:
        # urllib 把证书错误裹在 URLError.reason 里, 类型元组盖不住, 走分类器
        if tls.is_tls_error(e):
            raise TlsError(_tls_msg(url, verify, e)) from e
        raise RuntimeError(f'GET {url} failed [cffi: {last_cffi_err}; '
                           f'urllib: {type(e).__name__}: {str(e)[:120]}]')


def _tls_msg(url, verify, e):
    """证书失败提示: 分清"配置错了"和"站点证书本身有问题", 并给出修法"""
    if isinstance(e, tls.TlsConfigError):
        return f'TLS 配置错误: {e}'
    host = tls.host_of(url)
    if verify is False:
        why = '调用方显式指定了 verify=False'
    elif host and tls.hit_insecure(host):
        why = f'{host} 在 verify_hosts 名单里 (校验已关)'
    else:
        why = 'ssl_verify=on 严格校验中'
    kind, fix = tls.cert_advice(e, host)
    lines = [f'证书校验失败: {url[:90]}']
    if kind:
        lines.append(f'  类别: {kind}')
    lines += [f'  原因: {str(e)[:180]}',
              f'  现状: {why}']
    if fix:
        lines.append(f'  修法: {fix}')
    else:
        lines += ['  修法: 站点自签/证书过期 → webtool config set verify_hosts '
                  f'{host or "<域名>"}',
                  '        代理 MITM    → 把代理 CA 并进去: '
                  'webtool config set ca_bundle <ca.pem>']
    return '\n'.join(lines)


# 便捷入口

def resolve_redirect(url, *, referer=None, proxy=None, timeout=None,
                     profile=None, verify=None):
    """302/跳转链解析: 不跟随重定向, 返回 Location (非跳转返回 None)"""
    timeout = _rule_timeout(url, timeout)
    _pace(None)
    proxy_arg = None if proxy == 'direct' else proxy
    try:
        prof = profile or _pick_profile(None)
        s, p = _new_session(prof, proxy_arg, None)
        h = headers_for('nav', url, referer=referer, profile=p)
        r = s.get(url, headers=h, timeout=timeout, allow_redirects=False,
                  verify=tls.policy(url, verify))
        loc = r.headers.get('Location', '') or ''
        if loc.startswith('http'):
            return loc
        if loc:
            base = urllib.parse.urlparse(url)
            return f'{base.scheme}://{base.netloc}' + loc
    except CertificateVerifyError as e:
        # 证书失败不静默返回 None —— 那会被上层当成"此 URL 无跳转",
        # 变成一个查不出原因的错误结果
        raise TlsError(_tls_msg(url, verify, e)) from e
    except Exception as e:
        logger.debug('transport | 跳转解析失败 url=%s: %s', url, e,
                     exc_info=True)
    return None


def session_get(url, session, *, kind='nav', referer=None, timeout=None,
                headers=None, lang=LANG_ZH, profile=None, verify=None,
                max_bytes=8 * 1024 * 1024):
    """在外部管理的会话上请求 (引擎自带预热流程时用), 返回 (text, status)

    timeout 默认 None = 走通用兜底链 (http 规则 → config.json → 15), 与
    主通道同一个决定 —— 写死 15 会让 `config set timeout` 对这条路径失效。
    """
    timeout = _rule_timeout(url, timeout)
    p = profile or PROFILES['chrome131_win']
    h = headers_for(kind, url, referer=referer, lang=lang, profile=p,
                    extra=headers)
    try:
        r = session.get(url, headers=h, timeout=timeout,
                        verify=tls.policy(url, verify))
    except CertificateVerifyError as e:
        raise TlsError(_tls_msg(url, verify, e)) from e
    return r.text[:max_bytes], r.status_code


def warm_session(session, home, *, kind='nav', referer=None, timeout=None,
                 profile=None, verify=None, max_bytes=512 * 1024):
    """公共首页预热: 领会话 cookie + 一次落地导航。

    SUID/SNUID/NID 这类 cookie 只在首页响应里下发, 裸打搜索端点会被判成
    无来源的机器人查询。指纹头按 profile 生成, 与后续请求同源。
    返回是否成功, 不抛异常: 预热尽力而为, 失败也要继续
    (证书失败除外 —— 那是配置/站点问题, 继续走只会得到一堆无意义的失败)。
    """
    timeout = _rule_timeout(home, timeout)
    try:
        session_get(home, session, kind=kind, referer=referer,
                    timeout=timeout, profile=profile, verify=verify,
                    max_bytes=max_bytes)
        return True
    except TlsError:
        raise
    except Exception:
        return False

# 代理策略 (原 search.py, engines 层也要用)
