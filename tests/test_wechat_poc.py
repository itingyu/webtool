"""微信 POC 校验页: 识别 + 补 chksm 绕过 + 专用正文提取

不联外网: 本地 HTTP 服务模拟公众号的两种响应
  /s?...            无 chksm → 返回 secitptpage 校验页
  /s?...&chksm=...  有 chksm → 返回文章 HTML
"""
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

TMP = tempfile.mkdtemp(prefix='webtool-wx-')
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


VERIFY = ('<html><head><title></title>'
          '<link rel="stylesheet" href="//res.wx.qq.com/mmbizwap/zh_CN/'
          'htmledition/style/page/secitptpage/verify81568d.css"></head>'
          '<body>weui-msg</body></html>')

ARTICLE = '''<html><head><meta property="og:title" content="测试文章"></head><body>
<h1 id="activity-name"> 测试文章 </h1>
<a id="js_name">测试公众号</a>
<div class="rich_media_content" id="js_content" style="visibility: hidden;">
  <section><p>第一段正文，讲了一个技术细节。</p>
  <p>第二段正文，继续展开。</p>
  <img data-src="https://mmbiz.qpic.cn/a.jpg" />
  </section>
</div>
<div class="qr_code_pc">微信扫一扫 关注该公众号</div>
</body></html>'''

IMAGE_POST = '''<html><head></head><body>
<h1 id="activity-name">图片消息</h1><a id="js_name">某号</a>
<div id="js_content"><section><img data-src="https://mmbiz.qpic.cn/long.jpg"/></section></div>
</body></html>'''

HITS = {'verify': 0, 'article': 0}


class _H(BaseHTTPRequestHandler):
    def do_GET(self):                       # noqa: N802
        if 'chksm=' in self.path:
            HITS['article'] += 1
            body = ARTICLE
        else:
            HITS['verify'] += 1
            body = VERIFY
        raw = body.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


_srv = HTTPServer(('127.0.0.1', 0), _H)
PORT = _srv.server_address[1]
threading.Thread(target=_srv.serve_forever, daemon=True).start()
BASE = 'http://127.0.0.1:%d' % PORT

from webtool.engines import wechat                  # noqa: E402
from webtool.net import intercept, transport        # noqa: E402
from webtool.net.intercept import Bypass, Hit, Interceptor   # noqa: E402

# ── 1. 插件在册且优先级正确 ─────────────────────────────────────────────
names = [p.name for p in intercept.interceptors()]
check('wechat_poc' in names, '内置 wechat_poc 已注册', str(names))
prio = {p.name: p.priority for p in intercept.interceptors()}
check(prio.get('wechat_poc') == 15, 'wechat_poc 优先级 15', str(prio))

# ── 2. 只认公众号域名 ──────────────────────────────────────────────────
hit = intercept.inspect(intercept.Ctx(engine='wechat', url=BASE + '/s?x=1',
                                     status=200, text=VERIFY))
check(hit is None, '非公众号域名不误判', repr(hit))

# ── 3. 校验页被判出来, 且给出补 chksm 的绕法 ────────────────────────────
WX = 'https://mp.weixin.qq.com/s?__biz=x&mid=1&idx=1&sn=abc'
hit = intercept.inspect(intercept.Ctx(engine='wechat', url=WX,
                                     status=200, text=VERIFY))
check(hit is not None and hit.kind == 'verify', '公众号校验页被判出', repr(hit))
bp = intercept.bypass(intercept.Ctx(engine='wechat', url=WX, text=VERIFY), hit)
check(bp is not None and 'chksm=' in (bp.url or ''), '绕法是补 chksm', repr(bp))
bp2 = intercept.bypass(intercept.Ctx(engine='wechat',
                                    url=WX + '&chksm=1', text=VERIFY), hit)
check(bp2 is None, '已带 chksm 仍被拦 → 不硬试', repr(bp2))

# ── 4. 专用提取: 文字 + 图片, 且不把页面 UI 当正文 ───────────────────────
md, meta = wechat.extract(ARTICLE)
check(md.startswith('# 测试文章'), '提取出标题', md[:30])
check('第一段正文' in md and '第二段正文' in md, '提取出段落正文')
check('mmbiz.qpic.cn/a.jpg' in md, '提取出正文图片', md[-80:])
check('微信扫一扫' not in md, '页面 UI 没混进正文')
check(meta.get('author') == '测试公众号', '提取出作者', str(meta))

md2, meta2 = wechat.extract(IMAGE_POST)
check(meta2.get('image_post') is True and 'long.jpg' in md2,
      '图片消息识别为 image_post 且保留图片', f'{meta2} {md2[:60]}')

# ── 5. 端到端: 判定 → 换 URL → 重取, 全链走 transport ─────────────────
class _LocalWx(Interceptor):
    """本地同款插件: 只认本地 host, 验的是 transport 的绕法执行语义"""
    name = 'local_wx'
    priority = 16

    def inspect(self, ctx):
        if 'secitptpage/verify' in (ctx.text or ''):
            return Hit(kind='verify', why='本地校验页', sign='secitptpage')
        return None

    def bypass(self, ctx, hit):
        return Bypass(how='补 chksm', url=ctx.url + '&chksm=test')


intercept.register(_LocalWx)
before = dict(HITS)
try:
    txt, _st, _via = transport.get(BASE + '/s?__biz=x', engine='wxlocal',
                                   proxy='direct', timeout=5)
    err = None
except Exception as e:                      # noqa: BLE001
    txt, err = '', e
check(err is None and '第一段正文' in txt, '端到端: 绕法后拿到正文', repr(err))
check(HITS['article'] == before['article'] + 1 and
      HITS['verify'] == before['verify'] + 1,
      '端到端: 只多发一次请求', str(HITS))

_srv.shutdown()
print()
print('%d PASS, %d FAIL' % (N[0] - len(FAIL), len(FAIL)))
sys.exit(1 if FAIL else 0)
