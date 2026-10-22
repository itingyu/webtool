"""扫码登录: 生成二维码 → 用户用 App 扫 → 轮询 → 把 cookie 落到 state

两家的协议不一样, 各自实现:

- xhs  (小红书)
  create: POST /api/sns/web/v1/login/qrcode/create
          签名走 x-s/x-t, 但必须用 xyw 格式 (用 xys 会被拒; 见 xhshow
          的 sign_xyw 注释)。必需 cookie: a1 + webId。
  二维码内容: data.url (xhsdiscover:// App deep link)
  轮询: GET /api/sns/web/v1/login/qrcode/status?qr_id=..&code=..
        code_status: 0 等待扫码 / 1 已扫待确认 / 2 成功 / 3 取消或过期

- boss (BOSS直聘)
  create: GET /wapi/zppassport/captcha/randkey?pk=cpc_user_sign_up_wap
          返回 zpData.qrId
  二维码内容: qrId 字符串本身 (前端用 bzl-qrcode 把这个字符串渲染成图)
  轮询: GET /wapi/zppassport/qrcode/scan?qrId=..      → scaned
        GET /wapi/zppassport/qrcode/scanLogin?qrId=..  → login
        GET /wapi/zppassport/qrcode/dispatcher?qrId=..&pk=..  → 换会话 cookie

cookie 从会话的 Set-Cookie 里收, 成功后交给 state.save_cookies。
"""
from __future__ import annotations

import time

QR_SITES = {
    'xhs': {
        'label': '小红书',
        'hint': '用小红书 App 扫二维码 (扫的是 xhsdiscover:// 深链)',
    },
    'boss': {
        'label': 'BOSS直聘',
        'hint': '用 BOSS 直聘 App 扫二维码 (扫的是 bosszp- 开头的会话串)',
    },
}


class QRError(RuntimeError):
    """扫码登录失败; message 直接可读"""

    def __init__(self, message, hint=''):
        super().__init__(message)
        self.hint = hint or ''


class QRTimeout(QRError):
    """超时没人扫"""


def _session():
    from curl_cffi import requests as cr
    s = cr.Session(impersonate='chrome')
    return s


# ---------------------------------------------------------------- xhs


def _xhs_client():
    """xhshow 是可选依赖: 没装就报可读提示, 不静默失败"""
    try:
        from xhshow import Xhshow
    except ImportError as e:
        raise QRError(
            '小红书扫码登录需要 xhshow 签名库: pip install xhshow',
            '装上后重试; 只想手动导入 cookie 的话用 webtool auth set xhs') from e
    return Xhshow()


def _xhs_create(session):
    X = _xhs_client()
    a1 = X.generate_a1()
    web_id = X.generate_web_id(a1)
    ck = {'a1': a1, 'webId': web_id}
    for k, v in ck.items():
        session.cookies.set(k, v, domain='.xiaohongshu.com')
    uri = '/api/sns/web/v1/login/qrcode/create'
    hdr = X.sign_headers_post(uri, ck, payload={}, sign_format='xyw')
    hdr.update({
        'Content-Type': 'application/json',
        'Origin': 'https://www.xiaohongshu.com',
        'Referer': 'https://www.xiaohongshu.com/login',
    })
    r = session.post('https://edith.xiaohongshu.com' + uri, headers=hdr,
                     json={}, timeout=20)
    try:
        d = r.json()
    except Exception as e:
        raise QRError(f'小红书二维码接口返回非 JSON: {r.text[:120]}') from e
    if d.get('code') != 0 or not d.get('data'):
        raise QRError(f'小红书二维码接口拒绝: {d.get("msg") or d}')
    data = d['data']
    text = data.get('url') or data.get('qr_id') or ''
    if not text:
        raise QRError('小红书二维码接口没给扫码内容')
    return {'text': text, 'qr_id': data.get('qr_id'),
            'code': data.get('code'), 'cookies': ck}


# 小红书 code_status 含义 (前端 login/qrcode/status 用同一套值)
XHS_STATUS_TEXT = {
    0: '等待扫码',
    1: '已扫码, 等待在 App 上确认',
    2: '登录成功',
    3: '已取消或二维码已过期',
}


def xhs_status_text(code_status):
    """小红书扫码状态码 → 人话 (纯函数, 便于测)"""
    return XHS_STATUS_TEXT.get(code_status, f'未知状态({code_status})')


def boss_login_done(data):
    """BOSS 的 scan 响应里 login=true 才算登录成功

    实测 scaned=true 在没真扫码时也会出现, 拿它当成功信号会误判。
    """
    return bool(isinstance(data, dict) and data.get('login'))


def _xhs_poll(session, state, timeout, interval):
    X = _xhs_client()
    ck = state['cookies']
    uri = '/api/sns/web/v1/login/qrcode/status'
    params = {'qr_id': state['qr_id'], 'code': state['code']}
    deadline = time.time() + timeout
    seen = None
    while time.time() < deadline:
        hdr = X.sign_headers_get(uri, ck, params=params, sign_format='xyw')
        hdr.update({'Referer': 'https://www.xiaohongshu.com/login'})
        try:
            r = session.get('https://edith.xiaohongshu.com' + uri, params=params,
                            headers=hdr, timeout=20)
            d = r.json()
        except Exception as e:
            raise QRError(f'小红书状态查询失败: {e}') from e
        st = (d.get('data') or {}).get('code_status')
        if st == 2:
            return _cookies_of(session)
        if st in (3, 4):
            raise QRError('扫码已取消或二维码已过期, 重新生成一个')
        if st != seen:
            seen = st
        time.sleep(interval)
    raise QRTimeout(f'{timeout} 秒内没等到扫码确认',
                    '重新运行 webtool auth qr xhs 生成新二维码')


# ---------------------------------------------------------------- boss

_BOSS_PK = 'cpc_user_sign_up_wap'


def _boss_create(session):
    session.get('https://www.zhipin.com/web/user/?ka=header-login', timeout=25)
    hdr = {'X-Requested-With': 'XMLHttpRequest',
           'Referer': 'https://www.zhipin.com/web/user/?ka=header-login',
           'Accept': 'application/json, text/plain, */*'}
    r = session.get(
        'https://www.zhipin.com/wapi/zppassport/captcha/randkey',
        params={'pk': _BOSS_PK}, headers=hdr, timeout=25)
    try:
        d = r.json()
    except Exception as e:
        raise QRError(f'BOSS 二维码接口返回非 JSON: {r.text[:120]}') from e
    qr_id = (d.get('zpData') or {}).get('qrId')
    if not qr_id:
        raise QRError(f'BOSS 二维码接口没给 qrId: {d}')
    return {'text': qr_id, 'qr_id': qr_id, 'pk': _BOSS_PK}


def _boss_poll(session, state, timeout, interval):
    hdr = {'X-Requested-With': 'XMLHttpRequest',
           'Referer': 'https://www.zhipin.com/web/user/?ka=header-login',
           'Accept': 'application/json, text/plain, */*'}
    qr_id = state['qr_id']
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = session.get('https://www.zhipin.com/wapi/zppassport/qrcode/scan',
                        params={'qrId': qr_id}, headers=hdr, timeout=25)
        try:
            d = r.json()
        except Exception as e:
            raise QRError(f'BOSS 状态查询失败: {e}') from e
        # login=true 才是登录成功; scaned=true 只表示"已被扫到, 还在等 App 确认"
        # (实测未扫码时也可能回 scaned=true, 所以不能拿它当成功信号)
        if boss_login_done(d):
            break
        time.sleep(interval)
    else:
        raise QRTimeout(f'{timeout} 秒内没等到扫码确认',
                        '重新运行 webtool auth qr boss 生成新二维码')
    # 已扫码: 先问 scanLogin 要不要确认, 再用 dispatcher 换会话 cookie
    r = session.get('https://www.zhipin.com/wapi/zppassport/qrcode/scanLogin',
                    params={'qrId': qr_id}, headers=hdr, timeout=25)
    try:
        d = r.json()
    except Exception as e:
        raise QRError(f'BOSS 扫码确认失败: {e}') from e
    if not d.get('login') and not d.get('scaned'):
        raise QRError(f'BOSS 扫码未完成登录: {d}')
    r = session.get('https://www.zhipin.com/wapi/zppassport/qrcode/dispatcher',
                    params={'qrId': qr_id, 'pk': state['pk']},
                    headers=hdr, timeout=25)
    try:
        d = r.json()
    except Exception as e:
        raise QRError(f'BOSS 换取会话失败: {e}') from e
    if d.get('code') != 0:
        raise QRError(f'BOSS 换取会话被拒: {d.get("message") or d}')
    ck = _cookies_of(session)
    if not ck:
        raise QRError('BOSS 登录成功但没拿到 cookie (会话未下发)')
    return ck


# ---------------------------------------------------------------- 公共

_IMPL = {'xhs': (_xhs_create, _xhs_poll),
         'boss': (_boss_create, _boss_poll)}


def _cookies_of(session):
    """会话 jar 里的 cookie → webtool 的 [{'name','value','domain'}] 结构"""
    out = []
    for c in getattr(session.cookies, 'jar', session.cookies):
        domain = getattr(c, 'domain', '') or ''
        out.append({'name': c.name, 'value': c.value, 'domain': domain,
                    'path': getattr(c, 'path', '/') or '/'})
    return out


def create(site):
    """生成二维码内容, 返回 {'text','state'}"""
    if site not in _IMPL:
        raise QRError(f'不支持扫码登录的站点: {site}',
                      '可用: ' + ' / '.join(sorted(QR_SITES)))
    s = _session()
    create_fn, _ = _IMPL[site]
    st = create_fn(s)
    return {'text': st['text'], 'state': st, 'session': s,
            'label': QR_SITES[site]['label']}


def poll(site, ctx, timeout=120, interval=2.0):
    """轮询扫码状态; 成功返回 cookie 列表"""
    _, poll_fn = _IMPL[site]
    return poll_fn(ctx['session'], ctx['state'], timeout, interval)


def save(site, cookies):
    """把 cookie 落到 state (键名 = site)"""
    from webtool.dao import state as _state
    _state.save_cookies(site, cookies)
    return cookies
