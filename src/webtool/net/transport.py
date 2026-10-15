"""统一传输层: curl_cffi 浏览器指纹 + 降级重试 + 节奏控制 + 验证码处置

UA 与 impersonate 版本严格对齐, header 按 kind 分型 (nav 页面导航 / xhr 页面
JS 请求 / api 公开 REST), sec-fetch-site 按可注册域判定; cookie 经 state
持久化; 被拦走 冷却→退避换指纹→代理直连互换 降级梯; 每引擎限速+抖动。

证书校验统一走 core.tls (ssl_verify / ca_bundle / verify_hosts), 每请求
按 URL 现算 verify 后传给 curl_cffi; 证书失败抛 TlsError 直接上抛, 不进
降级梯 —— 换指纹换代理对证书问题一点用没有, 只是把 1 次失败放大成 4 次。
"""
import random
import socket
import threading
import time
import urllib.parse

from curl_cffi import requests as _cr
from curl_cffi.requests.exceptions import CertificateVerifyError
HAS_CFFI = True

from webtool.core import state
from webtool.core import secrets_store
from webtool.core import tls
from webtool.core import urls
from webtool.core.tls import TlsError
from webtool.net import captcha

# 证书类异常的判定统一交给 core.tls.is_tls_error —— urllib 把 SSLError 裹在
# URLError.reason 里, requests.SSLError 又不是 ssl.SSLError 的子类,
# 任何类型元组都盖不全, 漏网的后果是证书失败被降级梯当成普通抖动重试 4 次

# 浏览器指纹档案 (UA 与 impersonate 版本严格对齐)

_UA131 = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
          '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
_SCU131 = ('"Microsoft Edge";v="131", "Chromium";v="131", '
           '"Not_A Brand";v="24", "Google Chrome";v="131"')
_ACCEPT_NAV = ('text/html,application/xhtml+xml,application/xml;q=0.9,'
               'image/avif,image/webp,image/apng,*/*;q=0.8,'
               'application/signed-exchange;v=b3;q=0.7')

PROFILES = {
    'chrome131_win': {
        'impersonate': 'chrome131', 'ua': _UA131, 'sec_ch_ua': _SCU131,
        'platform': '"Windows"', 'mobile': '?0', 'accept_nav': _ACCEPT_NAV,
    },
    'chrome131_mac': {
        'impersonate': 'chrome131',
        'ua': _UA131.replace('Windows NT 10.0; Win64; x64',
                             'Macintosh; Intel Mac OS X 10_15_7'),
        'sec_ch_ua': _SCU131, 'platform': '"macOS"', 'mobile': '?0',
        'accept_nav': _ACCEPT_NAV,
    },
    'chrome131_linux': {
        'impersonate': 'chrome131',
        'ua': _UA131.replace('Windows NT 10.0; Win64; x64', 'X11; Linux x86_64'),
        'sec_ch_ua': _SCU131, 'platform': '"Linux"', 'mobile': '?0',
        'accept_nav': _ACCEPT_NAV,
    },
    # 移动端档案 (m.sogou 等移动站): UA 与 platform/mobile 全套对齐
    'chrome131_android': {
        'impersonate': 'chrome131_android',   # 真移动指纹 (TLS 层面)
        'ua': ('Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 '
               '(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36'),
        'sec_ch_ua': _SCU131, 'platform': '"Android"', 'mobile': '?1',
        'accept_nav': _ACCEPT_NAV,
    },
    # iOS Safari 档案: Safari 不发 sec-ch-ua client hints (Chromium 专属),
    # headers_for(full=True) 按空值跳过
    'safari18_4_ios': {
        'impersonate': 'safari184_ios',
        'ua': ('Mozilla/5.0 (iPhone; CPU iPhone OS 18_4 like Mac OS X) '
               'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.4 '
               'Mobile/15E148 Safari/604.1'),
        'sec_ch_ua': '', 'platform': '', 'mobile': '',
        'accept_nav': _ACCEPT_NAV,
    },
}

_ROTATION = ['chrome131_win', 'chrome131_win', 'chrome131_mac',
             'chrome131_linux', 'safari18_4_ios']

ACCEPT_XHR = 'application/json, text/plain, */*'
LANG_ZH = 'zh-CN,zh;q=0.9,en;q=0.8'
LANG_EN = 'en-US,en;q=0.9'


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


# 节奏控制 (每引擎最小间隔 + 抖动)

_DEFAULT_RATE = 0.4
_last_hit = {}
_rate_lock = threading.Lock()


def _rate_of(engine):
    """每引擎最小请求间隔秒数; engine.<name>.params.rate, 未声明用默认"""
    if not engine:
        return _DEFAULT_RATE
    from webtool.core.plugins import table as _plugin_table
    spec = _plugin_table('engine').get(engine) or {}
    return (spec.get('params') or {}).get('rate', _DEFAULT_RATE)


def _pace(engine):
    """请求前节奏控制: 距上次请求不足 min_interval 时随机补足"""
    if not engine:
        return
    gap = _rate_of(engine)
    with _rate_lock:
        last = _last_hit.get(engine, 0.0)
        wait = gap - (time.time() - last) + random.uniform(0.05, 0.4)
        _last_hit[engine] = time.time() + max(0.0, wait)
    if wait > 0:
        time.sleep(wait)


# header 构造

def _sec_fetch_site(target_url, referer):
    if not referer:
        return 'none'
    t, r = urllib.parse.urlparse(target_url), urllib.parse.urlparse(referer)
    if t.netloc.lower() == r.netloc.lower():
        return 'same-origin'
    if _registrable(t.netloc) == _registrable(r.netloc):
        return 'same-site'
    return 'cross-site'


def headers_for(kind, url, referer=None, lang=LANG_ZH, profile=None,
                extra=None, full=False):
    """按请求类型构造与真人一致的 header 集

    full=False (curl_cffi): 只补 impersonate 不会发的头 (sec-fetch-*/priority/
    upgrade-insecure-requests/referer/origin)。UA/sec-ch-ua/accept-encoding 交给
    impersonate 保证与 TLS 指纹同版本 — 手动传反而可能错位。
    full=True  (urllib 兜底): 显式全套, 包括 UA/sec-ch-ua/accept-encoding(gzip)。

    注意: curl_cffi 的 impersonate 自带 UA/指纹头 (与 impersonate 版本对齐,
    如 chrome131_android 自带 Android UA), 本函数 full=False 时**不会**设置
    UA — 传给 cffi 会话的 header 集不该含 User-Agent (传了反而把 impersonate
    的对齐 UA 覆盖成档案字符串, 出现 "UA 与 TLS 指纹不同源" 的自曝组合)。
    """
    p = profile or PROFILES['chrome131_win']
    h = {}
    if full:
        if p.get('ua'):
            h['User-Agent'] = p['ua']
        h['Accept-Encoding'] = 'gzip, deflate'
        if p.get('sec_ch_ua'):
            h['sec-ch-ua'] = p['sec_ch_ua']
        if p.get('mobile'):
            h['sec-ch-ua-mobile'] = p['mobile']
        if p.get('platform'):
            h['sec-ch-ua-platform'] = p['platform']
    if kind == 'nav':
        h.update({
            'Accept': p['accept_nav'],
            'Accept-Language': lang,
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-User': '?1',
            'Sec-Fetch-Site': _sec_fetch_site(url, referer),
            'priority': 'u=0, i',
        })
    elif kind in ('xhr', 'xhr_cross'):
        h.update({
            'Accept': ACCEPT_XHR,
            'Accept-Language': lang,
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': _sec_fetch_site(url, referer),
            'priority': 'u=1, i',
        })
        if referer:
            rp = urllib.parse.urlparse(referer)
            h.setdefault('Origin', f'{rp.scheme}://{rp.netloc}')
    elif kind == 'plain':
        h.update({'Accept': '*/*', 'Accept-Language': lang})
    if referer:
        h['Referer'] = referer
    if extra:
        for k, v in extra.items():
            if v is None:
                h.pop(k, None)
            else:
                h[k] = v
    return h


# 会话 (UA/cookie 固定, 持久化)

def _export_cookies(session):
    out = []
    try:
        for c in session.cookies.jar:
            out.append({'name': c.name, 'value': c.value or '',
                        'domain': c.domain, 'path': c.path,
                        'expires': c.expires, 'secure': bool(c.secure)})
    except Exception:
        pass
    return out


def _new_session(profile_name, proxy=None, engine=None, url=None):
    """新会话: 指纹档案 (名或 dict) + state 里的持久 cookie 预载

    `proxy` 走 netx 归一 —— 'auto' 之类的值原样塞给 curl_cffi 会被当成主机名解析
    (`Could not resolve proxy: auto`), 配了代理反而全挂。

    **url 必须传**: 'auto' 的线路由路由表按域名决定, 没有目标 URL 就只能退回
    默认动作, 于是 `*.cn` direct 这类规则对会话失效 (引擎的会话恰恰是打
    境内站, 最容易被规则分流)。引擎手上都有实际要请求的 URL, 传进来即可。
    归一是幂等的 —— 引擎自己先 resolve 过再传已归一的 URL, 不会二次补密码。

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


__all__ = ['BlockedError', 'CooldownError', 'TlsError', 'get', 'headers_for',
           'resolve_redirect', 'session_get', 'warm_session',
           'PROFILES', 'LANG_ZH', 'LANG_EN', 'ACCEPT_XHR']


# 主入口

def get(url, *, kind='nav', referer=None, proxy=None, timeout=15,
        engine=None, rate_engine=None, headers=None, lang=LANG_ZH, max_bytes=8 * 1024 * 1024, profile=None,
        session=None, verify=None, _depth=0, raw=False):
    """浏览器指纹 GET → (text, status, via)

    via: 'cffi' | 'urllib'
    - engine: 反爬冷却/验证码检测/cookie 持久化都挂在这个名字上 (baidu/sogou/...)
    - rate_engine: 节奏控制的桶 (一般与 engine 相同, resolve 类可单列)
    - session: 外部管理的会话 (引擎自带预热流程时传入), 此时指纹档案取 profile
    - verify: 证书校验覆盖 (None=按 core.tls 全局策略; True/False 定点决定)
    """
    if engine and _depth == 0 and captcha.suspended(engine):
        # 冷却门只在顶层检查: 降级梯内部重试不受影响 (否则会撞上自己刚记的冷却)
        raise CooldownError(
            f'{engine} 冷却中({captcha.cooldown_left(engine)}s, 此前触发人机验证), '
            f'请换引擎或 webtool engines 查看')
    _pace(rate_engine or engine)

    # 代理归一交给 netx (唯一该碰代理的地方): 'auto' → 问路由表, 'user@host' →
    # 补保险库密码。这里不自己判断, 免得出现第二份与 netx 不一致的副本。
    from webtool.net import netx as _netx
    proxy = _netx.resolve_proxy(proxy, url)

    if raw:
        # raw 只要响应头 + 原始字节 (fetch 判目标类型/落盘用), 不进验证码降级梯:
        # 梯子是给"要正文"的通道用的, 二进制目标没有"被拦换指纹"这回事
        return _get_once(url, kind=kind, referer=referer, proxy=proxy,
                         timeout=timeout, engine=engine, headers=headers,
                         lang=lang, max_bytes=max_bytes, profile=profile,
                         session=session, verify=verify, raw=True)

    text, status, via = _get_once(url, kind=kind, referer=referer, proxy=proxy,
                                  timeout=timeout, engine=engine,
                                  headers=headers, lang=lang,
                                  max_bytes=max_bytes, profile=profile,
                                  session=session, verify=verify)
    # 验证码检测 + 降级梯 (只对挂了引擎名的通道做, fetch/resolve 不折腾)
    if not (engine and text):
        return text, status, via

    blocked, sign = captcha.detect(engine, text)
    if not blocked:
        captcha.mark_ok(engine)
        if session is not None:
            _persist_cookies(session, engine)
        return text, status, via

    # 被拦: 记冷却 → 退避 → 降级梯 (最多 3 步; mark_blocked 记的冷却不影响
    # 梯内重试, 冷却门只在 _depth==0 检查)
    captcha.mark_blocked(engine)
    if _depth >= 3:
        raise BlockedError(
            f'{engine} 验证页拦截({sign}), 已重试{_depth}次仍被拦; '
            f'冷却{captcha.cooldown_left(engine)}s, 请换引擎')
    time.sleep(min(2 ** _depth, 4) + random.uniform(0, 0.8))
    # 梯子只换**指纹会话**(丢弃 cookie 重新握手), 线路不变 —— 被拦就偷偷退直连,
    # 会让"这条规则为什么对某些请求不生效"无法排查, 对必须走代理的目标也只是
    # 换一种错法。
    try:
        return get(url, kind=kind, referer=referer, proxy=proxy,
                   timeout=timeout, engine=engine, rate_engine=rate_engine,
                   headers=headers, lang=lang,
                   max_bytes=max_bytes, profile=profile, session=None,
                   verify=verify, _depth=_depth + 1)
    except (CooldownError, TlsError):
        raise
    except BlockedError:
        # 梯内递归已把最终 BlockedError 组装好, 直接上抛 (google 等上层按此降级 news)
        raise
    except Exception as e:
        raise BlockedError(f'{engine} 验证页拦截({sign}), 降级梯失败: {str(e)[:150]}; '
                           f'冷却{captcha.cooldown_left(engine)}s, 请换引擎')


def _lower_keys(headers):
    """响应头键统一小写 (cffi 本来就小写, urllib 是 Content-Type), 消费者别猜"""
    try:
        return {str(k).lower(): v for k, v in dict(headers).items()}
    except Exception:
        return {}


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


def open_stream(url, *, kind='nav', referer=None, proxy=None, timeout=15,
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
    from webtool.core.http import http_open
    h = headers_for(kind, url, referer=referer, lang=lang, full=True, extra=headers)
    r = http_open(url, proxy=proxy_arg, timeout=timeout, headers=h, verify=verify)
    return _UrllibStream(r), r.status, 'urllib', _lower_keys(r.headers)


def _get_once(url, *, kind, referer, proxy, timeout, engine, headers,
              lang, max_bytes, profile, session, verify=None, raw=False):
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
        h = headers_for(kind, url, referer=referer, lang=lang, profile=p,
                        extra=headers)
        r = s.get(url, headers=h, timeout=timeout, allow_redirects=True,
                  verify=tls.policy(url, verify))
        payload = r.content[:max_bytes] if raw else r.text[:max_bytes]
        if session is None:
            _persist_cookies(s, engine)
        if raw:
            return payload, r.status_code, 'cffi', _lower_keys(r.headers)
        return payload, r.status_code, 'cffi'
    except CertificateVerifyError as e:
        # 硬失败: 证书不对就是不对, 换指纹/换代理/换 urllib 全都救不了,
        # 直接上抛, 别让降级梯把 1 次失败放大成 4 次
        raise TlsError(_tls_msg(url, verify, e)) from e
    except Exception as e:
        last_cffi_err = f'{type(e).__name__}: {str(e)[:150]}'
    # 通道2: urllib (仅 cffi 自身崩溃时)
    from webtool.core.http import http_get
    h = headers_for(kind, url, referer=referer, lang=lang, full=True,
                    extra=headers)
    try:
        if raw:
            body, status, hdrs = http_get(url, proxy=proxy_arg, timeout=timeout,
                                          headers=h, max_bytes=max_bytes,
                                          verify=verify, raw=True)
            return body, status, 'urllib', _lower_keys(hdrs)
        text, status = http_get(url, proxy=proxy_arg, timeout=timeout,
                                headers=h, max_bytes=max_bytes, verify=verify)
        return text, status, 'urllib'
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


_fp_lock = threading.Lock()
_fp_map = {}


def _pick_profile(engine):
    """同引擎同进程内固定一个指纹, 新进程轮换 (冷却后新会话自然换指纹)"""
    key = engine or 'default'
    with _fp_lock:
        if key not in _fp_map:
            _fp_map[key] = random.choice(_ROTATION)
        return _fp_map[key]


# 便捷入口

def resolve_redirect(url, *, referer=None, proxy=None, timeout=10,
                     profile=None, verify=None):
    """302/跳转链解析: 不跟随重定向, 返回 Location (非跳转返回 None)"""
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
    except Exception:
        pass
    return None


def session_get(url, session, *, kind='nav', referer=None, timeout=15,
                headers=None, lang=LANG_ZH, profile=None, verify=None,
                max_bytes=8 * 1024 * 1024):
    """在外部管理的会话上请求 (引擎自带预热流程时用), 返回 (text, status)"""
    p = profile or PROFILES['chrome131_win']
    h = headers_for(kind, url, referer=referer, lang=lang, profile=p,
                    extra=headers)
    try:
        r = session.get(url, headers=h, timeout=timeout,
                        verify=tls.policy(url, verify))
    except CertificateVerifyError as e:
        raise TlsError(_tls_msg(url, verify, e)) from e
    return r.text[:max_bytes], r.status_code


def warm_session(session, home, *, kind='nav', referer=None, timeout=10,
                 profile=None, verify=None, max_bytes=512 * 1024):
    """公共首页预热: 领会话 cookie + 一次落地导航。

    SUID/SNUID/NID 这类 cookie 只在首页响应里下发, 裸打搜索端点会被判成
    无来源的机器人查询。指纹头按 profile 生成, 与后续请求同源。
    返回是否成功, 不抛异常: 预热尽力而为, 失败也要继续
    (证书失败除外 —— 那是配置/站点问题, 继续走只会得到一堆无意义的失败)。
    """
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
