"""net.intercept: 拦截绕过的抽象层 —— 插件注册 / 判定 / 绕过 / 记账

captcha 只是其中一个实现, 所以这里既测 captcha 的接线, 也测"换一个插件
能不能接上""插件抛错会不会把整条链路带崩"。
"""
import json
import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix='webtool-intercept-')
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


from webtool.core import config_data                 # noqa: E402
from webtool.net import intercept                     # noqa: E402
from webtool.net.intercept import Bypass, Ctx, Hit, Interceptor   # noqa: E402

CAPTCHA_PAGE = ('<html><head><title>安全验证</title></head><body>'
                + '请完成验证后继续访问' * 40 + '</body></html>')

# ── 内置注册 ─────────────────────────────────────────────────────────────
names = [p.name for p in intercept.interceptors()]
check('captcha' in names, '内置 captcha 在册', str(names))
check([p.priority for p in intercept.interceptors()
       if p.name == 'captcha'] == [10],
      'captcha 的优先级是 10')
check(intercept.describe()[0]['name'] == 'captcha'
      and 'captcha' in intercept.describe()[0]['module'],
      'describe 能报出插件与来源')

# ── 判定 ─────────────────────────────────────────────────────────────────
hit = intercept.inspect(Ctx(engine='baidu', url='https://www.baidu.com/s?wd=x',
                            status=200, text=CAPTCHA_PAGE))
check(hit is not None and hit.kind == 'captcha', '验证页被判出来', str(hit))
check(hit and hit.by == 'captcha', '命中者记在 hit.by 上')
check(hit and hit.sign != '', '判定依据带在 hit.sign 上 (报错要用)')
# baidu 的判定里有一条"正文短得可疑", 所以正常页要造够长 (2400 字)
check(intercept.inspect(Ctx(engine='baidu', text='正常结果 ' * 400)) is None,
      '正常页不误报')
check(intercept.inspect(Ctx(url='https://example.com/a', text=CAPTCHA_PAGE)) is not None,
      '不带引擎名的请求也判 (只看响应是否被拦)')
check(intercept.blocked_by(CAPTCHA_PAGE) is not None,
      '引擎侧便捷入口同样走全部拦截器')

# ── 记账与冷却门 ─────────────────────────────────────────────────────────
pre = intercept.preflight(Ctx(url='https://www.baidu.com/'))
check(pre is None, '没被拦过的引擎不封门')
ctx2 = Ctx(engine='baidu', url='https://www.baidu.com/s?wd=x',
           status=200, text=CAPTCHA_PAGE)
h2 = intercept.inspect(ctx2)
intercept.note_hit(ctx2, h2)
check(h2.left > 0, 'note_hit 把冷却剩余写回 hit.left', str(h2.left))
pre2 = intercept.preflight(Ctx(url='https://www.baidu.com/'))
check(pre2 is not None and pre2.left > 0, '冷却期内 preflight 拦下', str(pre2))
check(pre2 and pre2.why == '验证页拦截', 'preflight 用的人话是"验证页拦截"')
intercept.note_ok(ctx2)
check(intercept.preflight(Ctx(url='https://www.baidu.com/')) is None,
      'note_ok 复位后门就开了')

# ── 插件: 顺序 / 报错隔离 / 绕过 ──────────────────────────────────────────
class Boom(Interceptor):
    name = 'boom'
    priority = 5                       # 排最前, 但一上来就抛
    def inspect(self, ctx):
        raise RuntimeError('插件自己炸了')


class Waf(Interceptor):
    name = 'waf'
    priority = 20
    seen = []
    def inspect(self, ctx):
        Waf.seen.append(ctx.url)
        if '被盾' in (ctx.text or ''):
            return Hit(kind='waf', why='WAF 拦截', sign='正文含 被盾')
        return None
    def bypass(self, ctx, hit):
        return Bypass(how='换通道重试', url='https://mirror.example/fix',
                      headers={'X-Retry': '1'}, profile='chrome124',
                      delay=0.01)

class Slow(Interceptor):
    """故意比 Waf 优先, 但什么都不判 —— 验证"先跑的不吃独食""" 
    name = 'slow'
    priority = 15
    def inspect(self, ctx):
        return None


intercept.register(Boom)
intercept.register(Waf)
intercept.register(Slow)

hit3 = intercept.inspect(Ctx(engine='x', url='https://t/1', text='页面写着 被盾 两个字母'))
check(hit3 is not None and hit3.by == 'waf', '插件抛错不影响后面的插件', str(hit3))
check(any(d['name'] == 'boom' and d['error'] for d in intercept.describe()),
      '抛错的插件在 describe 里看得见',
      str(intercept.describe()))
check(Waf.seen == ['https://t/1'],
      '优先级小的先跑 (slow 先于 waf, 但判不出就让位)', str(Waf.seen))

bp = intercept.bypass(Ctx(engine='x', url='https://t/1', text='被盾'), hit3)
check(bp is not None and bp.how == '换通道重试', '判定的插件给出的绕法能拿到')

# ── 配置覆盖: 同名换实现 / 显式停用 ───────────────────────────────────────
# 用户侧 plugins.json 若不存在就现写一份 (只写要改的段, 深合并前不必抄整份)
pfile = os.path.join(TMP, 'plugins.json')


def write_user_interceptor(entry):
    d = {}
    if os.path.exists(pfile):
        try:
            d = json.load(open(pfile, encoding='utf-8'))
        except ValueError:
            d = {}
    d['interceptor'] = entry
    json.dump(d, open(pfile, 'w', encoding='utf-8'), ensure_ascii=False)
    config_data.invalidate()


write_user_interceptor({'captcha': {
    'module': 'webtool.net.captcha:CaptchaInterceptor', 'priority': 3}})
check([p.priority for p in intercept.interceptors()
       if p.name == 'captcha'] == [3],
      '配置里能改内置插件的优先级',
      str([(p.name, p.priority) for p in intercept.interceptors()]))

write_user_interceptor({'captcha': {
    'module': 'webtool.net.captcha:CaptchaInterceptor', 'enabled': False}})
check('captcha' not in [p.name for p in intercept.interceptors()],
      '配置里能停用内置插件',
      str([p.name for p in intercept.interceptors()]))
check(intercept.blocked_by(CAPTCHA_PAGE) is None,
      '停用后验证页不再命中 captcha')

# ── 体检: 写错插件要在 `plugins check` 里看得见 ───────────────────────────
from webtool.cli import plugins as pcmd                 # noqa: E402
from webtool.net.captcha import CaptchaInterceptor      # noqa: E402


class NoInspect(Interceptor):
    name = 'noinspect'                                # 忘了实现 inspect


check(pcmd._bad_interceptor(CaptchaInterceptor) == '', '体检认得过关的实现',
      pcmd._bad_interceptor(CaptchaInterceptor))
check('不是' in pcmd._bad_interceptor(dict),
      '体检拦下不是 Interceptor 的东西', pcmd._bad_interceptor(dict))
check('inspect' in pcmd._bad_interceptor(NoInspect),
      '体检拦下忘了实现 inspect 的插件',
      pcmd._bad_interceptor(NoInspect))

# ── 引擎内部的通道探测也得过拦截器 ───────────────────────────────────────
# 引擎自己造会话、自己读正文的路径 (sogou PC/移动双通道、baidu 预热会话、
# google web …) 以前直接调 captcha.detect/mark_*, 于是新加的拦截器插件对
# 这些路径莫名不生效。现在统一走 intercept.gate (判定 + 记账一次做完)。
class Gate(Interceptor):
    name = 'gate'
    priority = 40
    seen = []

    def inspect(self, ctx):
        Gate.seen.append((ctx.site, ctx.url))
        if '挡路石' in (ctx.text or ''):
            return Hit(kind='waf', why='WAF 拦截', sign='含 挡路石')
        return None


intercept.register(Gate)
_h4, _c4 = intercept.gate('页面写着 挡路石',
                           url='https://www.sogou.com/web')
check(_h4 is not None and _h4.by == 'gate',
      '引擎侧 gate 也走全部拦截器 (自定义插件管得到)', str(_h4))
check(Gate.seen[-1] == ('www.sogou.com', 'https://www.sogou.com/web'),
      'gate 交出的 ctx 就是插件看到的那次', str(Gate.seen[-1]))
check(intercept.cooldown_of('https://www.sogou.com/web') is None,
      'gate 只通知判定的插件记账 (captcha 不该跟着记黑账)',
      str(intercept.cooldown_of('https://www.sogou.com/web')))
check(intercept.cooldown_of() is None,
      '不给 URL 就查不到冷却 (冷却按站点记账, 引擎名不是键)')

import glob                                             # noqa: E402
import re as _re                                        # noqa: E402
_SRC = os.path.join(os.path.dirname(__file__), '..', 'src', 'webtool')
_leaks = []
for _f in (glob.glob(os.path.join(_SRC, 'engines', '*.py'))
           + [os.path.join(_SRC, 'net', 'transport.py')]):
    for _i, _ln in enumerate(open(_f, encoding='utf-8').read().splitlines(), 1):
        if _re.search(r'\bcaptcha\.(detect|mark_ok|mark_blocked|suspended'
                      r'|cooldown_left)\b', _ln):
            _leaks.append(f'{os.path.basename(_f)}:{_i}')
check(not _leaks, '引擎/传输层不再直连 captcha (否则自定义拦截器管不到)',
      str(_leaks))

print()
print('%d PASS, %d FAIL' % (N[0] - len(FAIL), len(FAIL)))
sys.exit(1 if FAIL else 0)
