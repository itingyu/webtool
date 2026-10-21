"""HTTP 请求指纹与档案: UA / Sec-CH-UA / Accept 头族 + headers_for

从 net/transport.py 拆出 (P4): 纯数据 + 头构造, 不碰会话/线路/证书。
transport 仍再导出这些名字, 老引用无需改。
"""
import random
import re
import threading
import urllib.parse

from webtool.core import urls

_registrable = urls.registrable

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


def profile_for_impersonate(name, ua=None):
    """按 curl_cffi 的 impersonate 名取一个指纹档案

    同名档案直接复用 (UA/客户端提示一套); 没有就借默认档案, 只换 impersonate
    —— UA 与 TLS 版本本来就是 impersonate 自己保证的, 这里只是给 headers_for
    一个"该报哪个 UA"的依据 (stock 各源给的就是这个名, 别再各建一张 UA 表)。
    """
    if name in PROFILES:                   # 档案名 (chrome131_win 等) 优先
        return PROFILES[name]
    for p in PROFILES.values():
        if p.get('impersonate') == name:   # 只有 impersonate 名 (chrome131)
            return p
    d = dict(PROFILES['chrome131_win'])
    d['name'] = f'imp-{name}'
    d['impersonate'] = name
    if ua:
        d['ua'] = ua
    return d


def chrome_targets():
    """curl_cffi 当前支持的 Chrome 伪装目标 (运行时问它, 别写死)

    版本跟得动: curl_cffi 升一次就多几个目标, 写死的清单很快就过期
    (求解器那边 Chrome 早就 136+ 了)。
    """
    try:
        import typing
        from curl_cffi.requests.impersonate import BrowserTypeLiteral
        return [v for v in typing.get_args(BrowserTypeLiteral)
                if str(v).startswith('chrome')]
    except Exception:
        return ['chrome131']


def impersonate_for_ua(ua):
    """从 UA 推出该用哪个 impersonate 目标 → (target, major, platform) 或 None

    为什么需要: 求解器解出来的 cf_clearance 绑在"那台浏览器"上 (UA + IP +
    JS 环境), 抓取端要复用它, impersonate 的 Chrome 版本就得跟求解端对上。

    platform 是从 UA 认出来的, 但要知道 curl_cffi 的桌面目标**一律发 macOS
    UA 与 macOS 平台提示** (实测 chrome131/136/142/150 都是), 所以平台对不上
    只能靠覆盖 UA —— 细节见 docs/intercept.md 的"版本对齐"。
    """
    if not ua:
        return None
    s = str(ua)
    m = re.search(r'Chrome/(\d+)', s) or re.search(r'CriOS/(\d+)', s)
    if not m:
        return None
    major = int(m.group(1))
    if 'Android' in s:
        platform = 'android'
    elif 'iPhone' in s or 'iPad' in s:
        platform = 'ios'
    elif 'Windows' in s:
        platform = 'win'
    elif 'Macintosh' in s or 'Mac OS' in s:
        platform = 'mac'
    elif 'Linux' in s or 'X11' in s:
        platform = 'linux'
    else:
        platform = ''
    targets = chrome_targets()
    cands = ([f'chrome{major}_android', f'chrome{major}'] if platform == 'android'
             else [f'chrome{major}', f'chrome{major}a'])
    for t in cands:
        if t in targets:
            return (t, major, platform)
    # 没有同版本: 退到最接近的低版本 (TLS 指纹接近总比差一整代强)
    lower = [t for t in targets
             if t[6:].isdigit() and int(t[6:]) <= major]
    if lower:
        return (max(lower, key=lambda t: int(t[6:])), major, platform)
    return None


def profile_for_ua(ua):
    """求解器 UA → 可直接用的指纹档案 dict (形状同 PROFILES 条目) 或 None

    用途: 求解插件拿到 solver 的 UA 后, 算出该 impersonate 哪个 Chrome 版本,
    把档案填进 Bypass.profile —— 抓取端就与求解端同版本了。

    sec_ch_ua 故意留空: 品牌列表随版本变 (实测 chrome131 是 "Not_A Brand";
    v=24", chrome136 是 "Not.A/Brand";v="99", chrome150 又变), 硬编码必然
    对不上 —— 交给 impersonate 自己发, 它发的才是与该版本一致的。
    """
    got = impersonate_for_ua(ua)
    if not got:
        return None
    target, major, platform = got
    return {'impersonate': target, 'ua': str(ua), 'sec_ch_ua': '',
            'mobile': '?0',
            'platform': {'win': '"Windows"', 'mac': '"macOS"',
                         'linux': '"Linux"', 'android': '"Android"'}.get(platform, ''),
            'accept_nav': _ACCEPT_NAV}


# 指纹轮换状态 (同引擎同进程内固定, 新进程/冷却后新会话自然换)

_fp_lock = threading.Lock()
_fp_map = {}


def pick_profile(engine):
    """同引擎同进程内固定一个指纹轮换档位 (传 engine=None 走 'default')"""
    key = engine or 'default'
    with _fp_lock:
        if key not in _fp_map:
            _fp_map[key] = random.choice(_ROTATION)
        return _fp_map[key]
