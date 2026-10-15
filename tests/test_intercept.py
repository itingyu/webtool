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


def check(name, cond, detail=''):
    N[0] += 1
    if cond:
        print('PASS %s' % name)
    else:
        FAIL.append(name)
        print('FAIL %s  %s' % (name, detail))


from webtool.core import config_data                 # noqa: E402
from webtool.net import intercept                     # noqa: E402
from webtool.net.intercept import Bypass, Ctx, Hit, Interceptor   # noqa: E402

CAPTCHA_PAGE = '请完成验证后继续访问' * 40

# ── 内置注册 ─────────────────────────────────────────────────────────────
names = [p.name for p in intercept.interceptors()]
check('内置 captcha 在册', 'captcha' in names, str(names))
check('captcha 的优先级是 10',
      [p.priority for p in intercept.interceptors()
       if p.name == 'captcha'] == [10])
check('describe 能报出插件与来源',
      intercept.describe()[0]['name'] == 'captcha'
      and 'captcha' in intercept.describe()[0]['module'])

# ── 判定 ─────────────────────────────────────────────────────────────────
hit = intercept.inspect(Ctx(engine='baidu', status=200, text=CAPTCHA_PAGE))
check('验证页被判出来', hit is not None and hit.kind == 'captcha', str(hit))
check('命中者记在 hit.by 上', hit and hit.by == 'captcha')
check('判定依据带在 hit.sign 上 (报错要用)', hit and hit.sign != '')
# baidu 的判定里有一条"正文短得可疑", 所以正常页要造够长 (2400 字)
check('正常页不误报',
      intercept.inspect(Ctx(engine='baidu', text='正常结果 ' * 400)) is None)
check('没有引擎名的通道不判 (fetch/resolve 不折腾)',
      intercept.inspect(Ctx(engine='', text=CAPTCHA_PAGE)) is None)
check('引擎侧便捷入口同样走全部拦截器',
      intercept.blocked_by('baidu', CAPTCHA_PAGE) is not None)

# ── 记账与冷却门 ─────────────────────────────────────────────────────────
pre = intercept.preflight(Ctx(engine='baidu'))
check('没被拦过的引擎不封门', pre is None)
ctx2 = Ctx(engine='baidu', status=200, text=CAPTCHA_PAGE)
h2 = intercept.inspect(ctx2)
intercept.note_hit(ctx2, h2)
check('note_hit 把冷却剩余写回 hit.left', h2.left > 0, str(h2.left))
pre2 = intercept.preflight(Ctx(engine='baidu'))
check('冷却期内 preflight 拦下', pre2 is not None and pre2.left > 0, str(pre2))
check('preflight 用的人话是"人机验证"', pre2 and pre2.why == '人机验证')
intercept.note_ok(ctx2)
check('note_ok 复位后门就开了',
      intercept.preflight(Ctx(engine='baidu')) is None)

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
check('插件抛错不影响后面的插件', hit3 is not None and hit3.by == 'waf', str(hit3))
check('抛错的插件在 describe 里看得见',
      any(d['name'] == 'boom' and d['error'] for d in intercept.describe()),
      str(intercept.describe()))
check('优先级小的先跑 (slow 先于 waf, 但判不出就让位)',
      Waf.seen == ['https://t/1'], str(Waf.seen))

bp = intercept.bypass(Ctx(engine='x', url='https://t/1', text='被盾'), hit3)
check('判定的插件给出的绕法能拿到', bp is not None and bp.how == '换通道重试')

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
check('配置里能改内置插件的优先级',
      [p.priority for p in intercept.interceptors()
       if p.name == 'captcha'] == [3],
      str([(p.name, p.priority) for p in intercept.interceptors()]))

write_user_interceptor({'captcha': {
    'module': 'webtool.net.captcha:CaptchaInterceptor', 'enabled': False}})
check('配置里能停用内置插件',
      'captcha' not in [p.name for p in intercept.interceptors()],
      str([p.name for p in intercept.interceptors()]))
check('停用后验证页不再命中 captcha',
      intercept.blocked_by('baidu', CAPTCHA_PAGE) is None)

# ── 体检: 写错插件要在 `plugins check` 里看得见 ───────────────────────────
from webtool.cli import plugins as pcmd                 # noqa: E402
from webtool.net.captcha import CaptchaInterceptor      # noqa: E402


class NoInspect(Interceptor):
    name = 'noinspect'                                # 忘了实现 inspect


check('体检认得过关的实现', pcmd._bad_interceptor(CaptchaInterceptor) == '',
      pcmd._bad_interceptor(CaptchaInterceptor))
check('体检拦下不是 Interceptor 的东西',
      '不是' in pcmd._bad_interceptor(dict), pcmd._bad_interceptor(dict))
check('体检拦下忘了实现 inspect 的插件',
      'inspect' in pcmd._bad_interceptor(NoInspect),
      pcmd._bad_interceptor(NoInspect))

print()
print('%d PASS, %d FAIL' % (N[0] - len(FAIL), len(FAIL)))
sys.exit(1 if FAIL else 0)
