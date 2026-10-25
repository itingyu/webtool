"""Cloudflare 质询 (非交互式 JS 质询: 浏览器里等几秒就自动放行那种)

测三件事:
  1. 认得出来 —— 头 cf-mitigated: challenge 与质询页专有标记都命中
  2. 不误伤 —— 带 Turnstile 挂件/带 cf-ray 页脚的正常页不能被判成被拦
  3. 处置得当 —— CF 与普通验证页分级冷却 (5 分钟 vs 30 秒), 报错带建议
"""
import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix='webtool-cf-')
os.environ['WEBTOOL_DIR'] = TMP
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

FAIL = []
N = [0]


def check(cond, msg, detail=''):
    N[0] += 1
    if cond:
        print('PASS %s' % msg)
    else:
        FAIL.append(msg)
        print('FAIL %s  %s' % (msg, detail))


from webtool.net import captcha, intercept            # noqa: E402
from webtool.net.intercept import Ctx                # noqa: E402

PLUGIN = [p for p in intercept.interceptors() if p.name == 'captcha'][0]

CF_PAGE = ('<html><head><title>Just a moment...</title></head><body>'
           '<div id="cf-challenge-running"></div>'
           '<div class="challenge-spinner"></div>'
           '<script src="/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1">'
           '</script></body></html>')

# 正常页: 带 Turnstile 挂件 + cf-ray 页脚 + CF 的 JS 检测脚本 (这三样正常页都有)
NORMAL_PAGE = ('<html><head><title>一篇正常文章</title></head><body>'
                '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js">'
                '</script>'
                '<input name="cf-turnstile-response" type="hidden">'
                '<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js">'
                '</script>'
                '<div>Ray ID: 8a1b2c3d4e5f6789</div>'
                '<p>' + '正文内容。' * 200 + '</p></body></html>')

# ── 1. 头判定 ─────────────────────────────────────────────────────────────
hit = PLUGIN.inspect(Ctx(url='https://example.com/a', status=403,
                         text='<html><body>blocked</body></html>',
                         headers={'cf-mitigated': 'challenge'}))
check(hit is not None and hit.kind == 'cf_challenge',
      '响应头 cf-mitigated: challenge 判为 CF 质询', str(hit))
check(hit and hit.sign == 'cf-mitigated: challenge',
      '头判定的特征串如实记下', str(hit and hit.sign))
check(hit and hit.hint and 'cf_clearance' in hit.hint,
      'CF 命中带处置建议 (含 cf_clearance 复用提示)', str(hit and hit.hint))

# ── 2. 正文判定 ───────────────────────────────────────────────────────────
hit2 = PLUGIN.inspect(Ctx(url='https://example.com/b', status=503,
                          text=CF_PAGE, headers={}))
check(hit2 is not None and hit2.kind == 'cf_challenge',
      '质询页正文 (Just a moment + cf-challenge-running) 判为 CF 质询', str(hit2))
check(hit2 and hit2.why == 'Cloudflare 质询拦截',
      'CF 命中的 why 是人话', str(hit2 and hit2.why))

# ── 3. 不误伤 ─────────────────────────────────────────────────────────────
hit3 = PLUGIN.inspect(Ctx(url='https://example.com/c', status=200,
                          text=NORMAL_PAGE, headers={'cf-ray': '8a1b2c3d4e5f6789'}))
check(hit3 is None, '带 Turnstile 挂件/cf-ray 页脚的正常页不判被拦', str(hit3))
check(captcha.cf_detect(NORMAL_PAGE) is None,
      'cf_detect 对正常页返回 None', str(captcha.cf_detect(NORMAL_PAGE)))
check(captcha.cf_detect(CF_PAGE) is not None,
      'cf_detect 对质询页有结论', str(captcha.cf_detect(CF_PAGE)))
check(captcha.cf_detect('', headers={'cf-mitigated': 'challenge'}) is not None,
      '只有头没有正文也判得出来')

# 通用特征仍管用 (普通验证页不该被 CF 规则吞掉)
hit4 = PLUGIN.inspect(Ctx(url='https://example.com/d', status=200,
                          text='<html><head><title>安全验证</title></head>'
                               '<body>请完成验证</body></html>', headers={}))
check(hit4 is not None and hit4.kind == 'captcha',
      '普通验证页仍判为 captcha (不混进 CF 档)', str(hit4))

# ── 4. 分级冷却 ───────────────────────────────────────────────────────────
PLUGIN.note_hit(Ctx(url='https://example.com/b', status=503, text=CF_PAGE),
                hit2)
left_cf = captcha.cooldown_left('example.com')
check(left_cf > 240, 'CF 质询冷却以 5 分钟起 (不是 30 秒)', str(left_cf))
st = captcha.state.get_captcha('example.com')
check(st.get('kind') == 'cf_challenge', '冷却里记下了拦截类型', str(st))

# 冷却期内 preflight 应报 CF 档, 不是普通验证页
pf = PLUGIN.preflight(Ctx(url='https://example.com/b'))
check(pf is not None and pf.kind == 'cf_challenge',
      '冷却门的拦截类型与当初一致', str(pf))
check(pf is not None and pf.hint,
      '冷却期也带处置建议', str(pf))

# 普通验证页仍是 30 秒档
hit5 = PLUGIN.inspect(Ctx(url='https://example.net/e', status=200,
                           text='<html><head><title>安全验证</title></head>'
                                '<body>请完成验证</body></html>', headers={}))
PLUGIN.note_hit(Ctx(url='https://example.net/e', status=200,
                     text='<html><head><title>安全验证</title></head></html>'),
                hit5)
left_generic = captcha.cooldown_left('example.net')
check(0 < left_generic <= 30, '普通验证页仍是 30 秒档', str(left_generic))

# ── 5. 通过后复位 ─────────────────────────────────────────────────────────
PLUGIN.note_ok(Ctx(url='https://example.com/b'))
check(captcha.cooldown_left('example.com') == 0,
      '过了就复位 (CF 档的 hits 也清零)')

# ── 6. 端到端: 响应头从 transport 传到 Ctx, 整条链路认得出 CF 质询 ─────────
# 这段验的是最容易断的一环: transport/_get_once 拿到的响应头, 得真的进到
# Ctx.headers 里, 否则 cf-mitigated 这条最可靠的特征就永远用不上。
import threading                                   # noqa: E402
import time                                        # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402

CF_BODY = ('<html><head><title>Just a moment...</title></head><body>'
           '<div id="cf-challenge-running"></div>'
           '<script src="/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1">'
           '</script></body></html>')


class _H(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    def do_GET(self):
        body = CF_BODY.encode()
        self.send_response(403)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('cf-mitigated', 'challenge')
        self.end_headers()
        self.wfile.write(body)


srv = ThreadingHTTPServer(('127.0.0.1', 0), _H)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
time.sleep(0.2)
CF_URL = 'http://127.0.0.1:%d/' % PORT

from webtool.net import transport                   # noqa: E402
from webtool.net.transport import BlockedError      # noqa: E402

try:
    transport.get(CF_URL, kind='nav', proxy='direct')
    check(False, 'CF 质询应当把请求挡下来', '居然放行了')
except BlockedError as e:
    msg = str(e)
    check('Cloudflare' in msg, '端到端: 报错说清了是 CF 质询', msg[:120])
    check('cf_clearance' in msg, '端到端: 报错带处置建议', msg[:200])
except Exception as e:                              # noqa: BLE001
    check(False, '端到端: CF 质询应当抛 BlockedError',
          f'{type(e).__name__}: {str(e)[:120]}')

check(captcha.cooldown_left('127.0.0.1') > 60,
      '端到端: 按站点记了长冷却 (CF 档 5 分钟起)',
      str(captcha.cooldown_left('127.0.0.1')))

# 冷却期内同站直接短路, 不再发请求
try:
    transport.get(CF_URL, kind='nav', proxy='direct')
    check(False, '冷却期内应当直接短路', '又发了一次')
except Exception as e:                              # noqa: BLE001
    check('冷却' in str(e), '冷却期内直接短路 (不发请求)', str(e)[:100])

srv.shutdown()

print()
print('%d PASS, %d FAIL' % (N[0] - len(FAIL), len(FAIL)))
sys.exit(1 if FAIL else 0)
