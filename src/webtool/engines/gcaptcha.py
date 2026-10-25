"""Google 429 挑战 (reCAPTCHA no-js form) 处置模块

实现到表单提交一步: anchor 可取 recaptcha-token, 但评分依赖 botguard.bg
(浏览器内 VM + scrypt POW) 生成的环境 blob, 纯 HTTP 过不了评分, 提交仍 429。
保留表单重放与 anchor-token 两条路径, 评分放宽后 solve() 自动生效。
"""
import base64
import re
import time
import urllib.parse

_SITEKEY = '6LfwuyUTAAAAAOAmoS0fdqijC2PbbdH4kjq62Y1b'
_R_V = 'nY0xPItgwtlvjEjk2TqdwOQz'      # releases 版本 (enterprise.js loader 动态拉)


def _parse_challenge(html):
    """从 429/sorry 页提取挑战要素: action / q 令牌 / continue / data-s"""
    form_m = re.search(r'<form id="captcha-form"[^>]*action="([^"]+)"[^>]*>(.*?)</form>',
                       html, re.S)
    if not form_m:
        return None
    body = form_m.group(2)
    q = re.search(r"name='q' value='([^']+)'", body) or \
        re.search(r'name="q" value="([^"]+)"', body)
    cont = re.search(r'name="continue" value="([^"]+)"', body)
    ds = re.search(r'data-s="([^"]+)"', body)
    if not q:
        return None
    return {
        'action': form_m.group(1),
        'q': q.group(1),
        'continue': (cont.group(1).replace('&amp;', '&') if cont else None),
        'data_s': ds.group(1) if ds else None,
    }


def _b64_origin(origin):
    """anchor co 参数: base64(origin) 去 padding — urlencode 形式会被判 Invalid domain"""
    return base64.b64encode(origin.encode()).decode().rstrip('=')


def _anchor_token(session, chal, challenge_url, timeout):
    """enterprise anchor (带 s=<data-s>) 取 recaptcha-token; 失败返 None"""
    co = _b64_origin('https://www.google.com')
    cb = 'c' + re.sub(r'[^A-Za-z0-9]', '', str(time.time()))[:16]
    url = (f'https://www.google.com/recaptcha/enterprise/anchor?ar=1&k={_SITEKEY}'
           f'&co={co}&hl=en&v={_R_V}&cb={cb}'
           + (f'&s={urllib.parse.quote(chal["data_s"], safe="")}' if chal.get('data_s') else ''))
    try:
        ra = session.get(url, timeout=timeout, headers={'Referer': challenge_url})
        m = re.search(r'id="recaptcha-token" value="([^"]+)"', ra.text)
        return m.group(1) if m else None
    except Exception:
        return None


def _post_sorry(session, chal, challenge_url, timeout, token):
    """把挑战表单 POST 回 /sorry/index (challenge 页实际 URL 域下)"""
    fields = {'q': chal['q'],
              'continue': chal['continue'] or 'https://www.google.com/'}
    if token:
        fields['g-recaptcha-response'] = token
    r = session.post('https://www.google.com/sorry/index',
                     data=urllib.parse.urlencode(fields).encode(),
                     timeout=timeout,
                     headers={'Referer': challenge_url,
                              'Content-Type': 'application/x-www-form-urlencoded',
                              'Origin': 'https://www.google.com',
                              'Sec-Fetch-Dest': 'document',
                              'Sec-Fetch-Mode': 'navigate',
                              'Sec-Fetch-Site': 'same-origin',
                              'Upgrade-Insecure-Requests': '1'},
                     allow_redirects=True)
    return r


def solve(session, html, challenge_url, timeout=12, attempts=2):
    """入口: 给 429/sorry 挑战页 HTML, 尝试纯 HTTP 攻破.
    返回 (ok: bool, final_text|None, how: str)
    how 取值: not-challenge / passed-undemanding / anchor-token / exhausted
    """
    chal = _parse_challenge(html)
    if not chal:
        return False, None, 'not-challenge'

    # 部分边缘节点对 q 令牌时效校验宽松, 直接重放表单可过
    for _ in range(attempts):
        try:
            r = _post_sorry(session, chal, challenge_url, timeout, token=None)
            if r.status_code == 200 and 'captcha-form' not in r.text \
                    and '/sorry/' not in r.url:
                return True, r.text, 'passed-undemanding'
        except Exception:
            pass
        time.sleep(1.2)

    # anchor-token: token 可取但 botguard 评分不过, 保留等评分放宽
    token = _anchor_token(session, chal, challenge_url, timeout)
    if token:
        time.sleep(2.0)          # 模拟人从加载到提交的间隔
        try:
            r = _post_sorry(session, chal, challenge_url, timeout, token)
            if r.status_code == 200 and 'captcha-form' not in r.text \
                    and '/sorry/' not in r.url:
                return True, r.text, 'anchor-token'
        except Exception:
            pass

    return False, None, 'exhausted'


def is_challenge(resp_text, status=None):
    """快速判定: 这个响应是不是 429/sorry 挑战页"""
    if status is not None and status != 429:
        return False
    return 'captcha-form' in resp_text and 'data-sitekey' in resp_text
