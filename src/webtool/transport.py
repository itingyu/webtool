# -*- coding: utf-8 -*-
"""统一传输层: curl_cffi 浏览器指纹 + 降级重试 + 节奏控制 + 验证码处置

UA 与 impersonate 版本严格对齐, header 按 kind 分型 (nav 页面导航 / xhr 页面
JS 请求 / api 公开 REST), sec-fetch-site 按可注册域判定; cookie 经 state
持久化; 被拦走 冷却→退避换指纹→代理直连互换 降级梯; 每引擎限速+抖动。
"""
import random
import threading
import time
import urllib.parse

from curl_cffi import requests as _cr
HAS_CFFI = True

from . import captcha, state

# ---------------- 浏览器指纹档案 (UA 与 impersonate 版本严格对齐) ----------------

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

# 常见多级后缀 (可注册域判定用)
_SFX2 = ('com.cn', 'net.cn', 'org.cn', 'gov.cn', 'com.hk', 'com.tw',
         'com.au', 'co.uk', 'co.jp', 'com.br', 'com.sg')


def _registrable(host):
    host = (host or '').split(':')[0].lower()
    if host.startswith('www.'):
        host = host[4:]
    labels = host.rsplit('.', 2)
    if len(labels) == 3 and labels[1] + '.' + labels[2] in _SFX2:
        return host
    if len(labels) >= 2:
        return labels[-2] + '.' + labels[-1]
    return host


# ---------------- 节奏控制 (每引擎最小间隔 + 抖动) ----------------

RATE = {'baidu': 1.2, 'sogou': 0.8, 'bing': 0.5, 'google': 1.0}
_last_hit = {}
_rate_lock = threading.Lock()


def _pace(engine):
    """请求前节奏控制: 距上次请求不足 min_interval 时随机补足"""
    if not engine:
        return
    gap = RATE.get(engine, 0.4)
    with _rate_lock:
        last = _last_hit.get(engine, 0.0)
        wait = gap - (time.time() - last) + random.uniform(0.05, 0.4)
        _last_hit[engine] = time.time() + max(0.0, wait)
    if wait > 0:
        time.sleep(wait)


# ---------------- header 构造 ----------------

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


# ---------------- 会话 (UA/cookie 固定, 持久化) ----------------

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


def _new_session(profile_name, proxy=None, engine=None):
    """新会话: 指纹档案 (名或 dict) + state 里的持久 cookie 预载"""
    if isinstance(profile_name, dict):
        p = profile_name
    else:
        p = PROFILES[profile_name]
    s = _cr.Session(impersonate=p['impersonate'], proxy=proxy or None)
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


# ---------------- 异常 ----------------

class BlockedError(RuntimeError):
    """验证码/风控页, 多通道尝试后仍被拦"""


class CooldownError(RuntimeError):
    """引擎处于反爬冷却期, 应换引擎"""


# ---------------- 主入口 ----------------

def get(url, *, kind='nav', referer=None, proxy=None, timeout=15,
        engine=None, rate_engine=None, headers=None, lang=LANG_ZH,
        allow_fallback=True, max_bytes=8 * 1024 * 1024, profile=None,
        session=None, _depth=0):
    """浏览器指纹 GET → (text, status, via)

    via: 'cffi' | 'urllib'
    - engine: 反爬冷却/验证码检测/cookie 持久化都挂在这个名字上 (baidu/sogou/...)
    - rate_engine: 节奏控制的桶 (一般与 engine 相同, resolve 类可单列)
    - allow_fallback=False: 不做代理→直连互换 (google 这类直连无意义的通道)
    - session: 外部管理的会话 (引擎自带预热流程时传入), 此时指纹档案取 profile
    """
    if engine and _depth == 0 and captcha.suspended(engine):
        # 冷却门只在顶层检查: 降级梯内部重试不受影响 (否则会撞上自己刚记的冷却)
        raise CooldownError(
            f'{engine} 冷却中({captcha.cooldown_left(engine)}s, 此前触发人机验证), '
            f'请换引擎或 webtool engines 查看')
    _pace(rate_engine or engine)

    text, status, via = _get_once(url, kind=kind, referer=referer, proxy=proxy,
                                  timeout=timeout, engine=engine,
                                  headers=headers, lang=lang,
                                  max_bytes=max_bytes, profile=profile,
                                  session=session)
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
    # 梯子: 换指纹新会话(原配置) → 代理互换 → 再换指纹
    swap_proxy = None if (proxy and _depth == 1 and allow_fallback) else proxy
    try:
        return get(url, kind=kind, referer=referer, proxy=swap_proxy,
                   timeout=timeout, engine=engine, rate_engine=rate_engine,
                   headers=headers, lang=lang, allow_fallback=allow_fallback,
                   max_bytes=max_bytes, profile=profile, session=None,
                   _depth=_depth + 1)
    except CooldownError:
        raise
    except BlockedError:
        # 梯内递归已把最终 BlockedError 组装好, 直接上抛 (google 等上层按此降级 news)
        raise
    except Exception as e:
        raise BlockedError(f'{engine} 验证页拦截({sign}), 降级梯失败: {str(e)[:150]}; '
                           f'冷却{captcha.cooldown_left(engine)}s, 请换引擎')


def _get_once(url, *, kind, referer, proxy, timeout, engine, headers,
              lang, max_bytes, profile, session):
    """单次请求: curl_cffi 浏览器指纹 → (cffi 崩了才走) urllib 全指纹兜底"""
    proxy_arg = None if proxy == 'direct' else proxy
    last_cffi_err = 'skipped'
    # --- 通道1: curl_cffi ---
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
        r = s.get(url, headers=h, timeout=timeout, allow_redirects=True)
        text = r.text[:max_bytes]
        if session is None:
            _persist_cookies(s, engine)
        return text, r.status_code, 'cffi'
    except Exception as e:
        last_cffi_err = f'{type(e).__name__}: {str(e)[:150]}'
    # 通道2: urllib (仅 cffi 自身崩溃时)
    from .http import http_get
    h = headers_for(kind, url, referer=referer, lang=lang, full=True,
                    extra=headers)
    try:
        text, status = http_get(url, proxy=proxy_arg, timeout=timeout,
                                headers=h, max_bytes=max_bytes)
        return text, status, 'urllib'
    except Exception as e:
        raise RuntimeError(f'GET {url} failed [cffi: {last_cffi_err}; '
                           f'urllib: {type(e).__name__}: {str(e)[:120]}]')


_fp_lock = threading.Lock()
_fp_map = {}


def _pick_profile(engine):
    """同引擎同进程内固定一个指纹, 新进程轮换 (冷却后新会话自然换指纹)"""
    key = engine or 'default'
    with _fp_lock:
        if key not in _fp_map:
            _fp_map[key] = random.choice(_ROTATION)
        return _fp_map[key]


# ---------------- 便捷入口 ----------------

def resolve_redirect(url, *, referer=None, proxy=None, timeout=10,
                     profile=None):
    """302/跳转链解析: 不跟随重定向, 返回 Location (非跳转返回 None)"""
    _pace(None)
    proxy_arg = None if proxy == 'direct' else proxy
    try:
        prof = profile or _pick_profile(None)
        s, p = _new_session(prof, proxy_arg, None)
        h = headers_for('nav', url, referer=referer, profile=p)
        r = s.get(url, headers=h, timeout=timeout, allow_redirects=False)
        loc = r.headers.get('Location', '') or ''
        if loc.startswith('http'):
            return loc
        if loc:
            base = urllib.parse.urlparse(url)
            return f'{base.scheme}://{base.netloc}' + loc
    except Exception:
        pass
    return None


def session_get(url, session, *, kind='nav', referer=None, timeout=15,
                headers=None, lang=LANG_ZH, profile=None,
                max_bytes=8 * 1024 * 1024):
    """在外部管理的会话上请求 (引擎自带预热流程时用), 返回 (text, status)"""
    p = profile or PROFILES['chrome131_win']
    h = headers_for(kind, url, referer=referer, lang=lang, profile=p,
                    extra=headers)
    r = session.get(url, headers=h, timeout=timeout)
    return r.text[:max_bytes], r.status_code


def warm_session(session, home, *, kind='nav', referer=None, timeout=10,
                 profile=None, max_bytes=512 * 1024):
    """公共首页预热: 领会话 cookie + 一次落地导航。

    SUID/SNUID/NID 这类 cookie 只在首页响应里下发, 裸打搜索端点会被判成
    无来源的机器人查询。指纹头按 profile 生成, 与后续请求同源。
    返回是否成功, 不抛异常: 预热尽力而为, 失败也要继续。
    """
    try:
        session_get(home, session, kind=kind, referer=referer,
                    timeout=timeout, profile=profile, max_bytes=max_bytes)
        return True
    except Exception:
        return False
