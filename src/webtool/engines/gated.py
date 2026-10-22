"""需要登录态的站点源: 小红书 / BOSS直聘

这两个站的接口对匿名请求一律软拒 (小红书 `-101 无登录信息`, BOSS
`code:37 您的环境存在异常`), 所以必须先有**用户自己的** cookie:
`webtool auth set xhs|boss` 导入, 存 dao.state 的 cookies 桶 (键名=站点名),
这里只读不写。

两个站的差别:
- BOSS: 普通 JSON 接口, 只需要 cookie (关键是 `__zp_stoken__`), 不签名
- 小红书: 每次请求都要 x-s/x-t 签名, 由可选依赖 `xhshow` 生成

xhshow 是第三方逆向实现, 算法随小红书前端变; 所以它是**可选依赖** ——
没装就报一句能照做的提示, 不让整个包硬依赖它。
"""
from __future__ import annotations

import json
import time
import urllib.parse

from webtool.core import authcookie
from webtool.dao import state
from webtool.net import transport

# 站点元数据: domain 用于落盘时标域, required 缺了就直说缺哪个
AUTH_SITES = {
    'xhs': {
        'label': '小红书',
        'domain': '.xiaohongshu.com',
        'required': ['a1'],
        'login': ['web_session'],
        'hint': ('浏览器登录 xiaohongshu.com → F12 → Network 任一请求的 Cookie 头, '
                 '整串复制; 关键项 a1 与 web_session'),
    },
    'boss': {
        'label': 'BOSS直聘',
        'domain': '.zhipin.com',
        'required': ['__zp_stoken__'],
        'login': [],
        'hint': ('浏览器登录 zhipin.com 搜索一次职位 → F12 → Network 里 '
                 'joblist.json 请求的 Cookie 头整串复制; 关键项 __zp_stoken__'),
    },
}


class SiteAuthError(RuntimeError):
    """cookie 缺失/失效/依赖缺失: message 直接可读, 调用方原样打给用户"""

    def __init__(self, message, hint=''):
        super().__init__(message)
        self.hint = hint or ''


def spec(site):
    return AUTH_SITES.get(site) or {}


def load(site):
    """该站已导入的 cookie 列表 (过期项由 dao.state 过滤)"""
    return state.load_cookies(site)


def needs(site):
    """必填项 = 技术必需(required) + 登录态必需(login)"""
    sp = spec(site)
    return list(sp.get('required') or []) + list(sp.get('login') or [])


def require(site):
    """取 cookie 并校验必需项; 不满足时抛 SiteAuthError (带操作指引)"""
    sp = spec(site)
    ck = load(site)
    if not ck:
        raise SiteAuthError(
            f'{sp.get("label", site)} 需要登录态: 先运行 '
            f'`webtool auth set {site}` 导入 cookie\n  {sp.get("hint", "")}')
    miss = authcookie.missing(ck, needs(site))
    if miss:
        raise SiteAuthError(
            f'{sp.get("label", site)} 的 cookie 缺关键项 {", ".join(miss)}: '
            f'重新导入完整 Cookie 头\n  {sp.get("hint", "")}')
    return ck


def _headers(site, ck, referer):
    return {
        'Cookie': authcookie.to_header(ck),
        'Referer': referer,
        'Accept': 'application/json, text/plain, */*',
    }


def _get_json(url, site, ck, referer, proxy, timeout):
    headers = _headers(site, ck, referer)
    txt, status, _via = transport.get(
        url, kind='api', proxy=proxy, timeout=timeout,
        engine=site, headers=headers)
    if status != 200:
        raise RuntimeError(f'HTTP {status}')
    try:
        return json.loads(txt)
    except ValueError:
        raise RuntimeError('返回不是 JSON (可能被风控页拦了)')


# ---------------- BOSS 直聘 ----------------

# 全国; BOSS 的城市码, 覆盖不到的城市可在 queries 里换
BOSS_CITY_ALL = '100010000'


def _parse_boss(d, limit=10):
    """zpData.jobList → 标准条目 (纯函数, 用 fixture 测)"""
    from webtool.engines.sites import _mk
    out = []
    for j in ((d or {}).get('zpData') or {}).get('jobList') or []:
        jid = j.get('encryptJobId') or j.get('encryptBossId')
        if not jid:
            continue
        loc = ''.join(x for x in (j.get('cityName'), j.get('areaDistrict'),
                                  j.get('businessDistrict')) if x)
        bits = [x for x in (j.get('salaryDesc'), loc,
                            j.get('jobExperience'), j.get('jobDegree')) if x]
        out.append(_mk(
            f"{j.get('jobName', '')} - {j.get('brandName') or j.get('companyName', '')}",
            'https://www.zhipin.com/job_detail/' + jid + '.html',
            ' · '.join(bits),
            extra={'company': j.get('companyName') or j.get('brandName'),
                   'salary': j.get('salaryDesc'),
                   'city': loc,
                   'skills': j.get('skills') or j.get('jobLabels')}))
        if len(out) >= limit:
            break
    return out


def boss(q, limit=10, proxy=None, timeout=15, city=None):
    """BOSS 直聘职位搜索 (需要登录 cookie)"""
    ck = require('boss')
    url = ('https://www.zhipin.com/wapi/zpgeek/search/joblist.json'
           f'?scene=1&query={urllib.parse.quote(q)}'
           f'&city={(city or BOSS_CITY_ALL)}&page=1&pageSize={min(limit, 30)}')
    d = _get_json(url, 'boss', ck, 'https://www.zhipin.com/web/geek/job?query='
                  + urllib.parse.quote(q), proxy, timeout)
    code = d.get('code')
    if code != 0:
        raise SiteAuthError(
            f"BOSS 拒绝了请求 (code={code} {d.get('message', '')}): "
            '多半是 cookie 过期或 __zp_stoken__ 失效, 重新导入一次')
    return _parse_boss(d, limit)


# ---------------- 小红书 ----------------

XHS_SEARCH_URI = '/api/sns/web/v1/search/notes'
XHS_BASE = 'https://edith.xiaohongshu.com'
_XHS_SIGNER = None


def _signer():
    """xhshow 实例; 没装时给能照做的报错 (可选依赖, 不进硬依赖)"""
    global _XHS_SIGNER
    if _XHS_SIGNER is None:
        try:
            from xhshow import Xhshow
        except ImportError:
            raise SiteAuthError(
                '小红书需要签名库: pip install xhshow\n'
                '  (第三方逆向实现, 算法随前端变; 不装不影响其他站点)')
        _XHS_SIGNER = Xhshow()
    return _XHS_SIGNER


def _parse_xhs(d, limit=10):
    """data.items → 标准条目 (纯函数, 用 fixture 测)"""
    from webtool.engines.sites import _mk
    out = []
    for it in ((d or {}).get('data') or {}).get('items') or []:
        card = it.get('note_card') or {}
        nid = it.get('id') or card.get('note_id')
        title = card.get('display_title') or card.get('title') or ''
        if not nid or not title:
            continue
        user = (card.get('user') or {}).get('nickname') or it.get('note_card', {})
        inter = card.get('interact_info') or {}
        out.append(_mk(
            title,
            f'https://www.xiaohongshu.com/explore/{nid}',
            card.get('desc') or '',
            score=_int(inter.get('liked_count')),
            extra={'author': user if isinstance(user, str) else None,
                   'likes': _int(inter.get('liked_count')),
                   'type': 'video' if card.get('type') == 'video' else 'note'}))
        if len(out) >= limit:
            break
    return out


def _int(v):
    try:
        return int(str(v).replace('+', '').replace('万', '0000'))
    except (TypeError, ValueError):
        return None


def xhs(q, limit=10, proxy=None, timeout=15):
    """小红书笔记搜索 (需要登录 cookie + xhshow 签名)"""
    ck = require('xhs')
    payload = {'keyword': q, 'page': 1, 'page_size': min(limit, 20),
               'search_id': format(int(time.time() * 1000) % 10 ** 12, 'x'),
               'sort': 'general', 'note_type': 0}
    # 必须用 xyw 格式: 这是小红书网页版的签名格式。默认格式虽然不报错
    # (code=0), 但服务端会静默返回空 items —— 实测 xyw 才真正走到业务侧
    headers = _signer().sign_headers_post(
        XHS_SEARCH_URI, {c['name']: c['value'] for c in ck}, payload=payload,
        sign_format='xyw')
    headers.update(_headers('xhs', ck, 'https://www.xiaohongshu.com/'))
    headers['Content-Type'] = 'application/json'
    r = transport.request('POST', XHS_BASE + XHS_SEARCH_URI, kind='api',
                          proxy=proxy, timeout=timeout, engine='xhs',
                          headers=headers, json_body=payload)
    if r.status_code != 200:
        raise RuntimeError(f'HTTP {r.status_code}')
    try:
        d = r.json() if hasattr(r, 'json') else json.loads(r.text)
    except ValueError:
        raise RuntimeError('返回不是 JSON (可能被风控页拦了)')
    code = d.get('code')
    if code in (300011, 461) or str(d.get('msg', '')).lower().find('abnormal') >= 0:
        raise SiteAuthError(
            f"小红书判定账号异常 (code={code} {d.get('msg', '')})",
            '这个账号在服务端被风控了, 不是本地 cookie 的问题; '
            '换个账号扫码, 或在浏览器里搜一下确认是不是同样被拦')
    if code not in (0, None):
        raise SiteAuthError(
            f"小红书拒绝了请求 (code={code} {d.get('msg', '')}): "
            'code=-100/-101 是登录态失效, 重新导入 cookie')
    return _parse_xhs(d, limit)


# 站点名 → 抓取函数 (auth test 与 site 调度共用同一张表)
AUTH_FN = {'xhs': xhs, 'boss': boss}
