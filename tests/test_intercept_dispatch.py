"""拦截器: 配置注册 + 按域名分发 + 只跑相关处理器

不联外网。验证四件事:
  1. 新插件靠 plugins.json 注册 (不用改代码)
  2. 声明 hosts 的插件只在自家域名被调用
  3. 不记冷却的插件不参与 preflight/note_ok
  4. 成功请求不再每次写 state.json
"""
import json
import os
import sys
import tempfile
import time

TMP = tempfile.mkdtemp(prefix='webtool-dispatch-')
os.environ['WEBTOOL_DIR'] = TMP
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, TMP)

FAIL = []
N = [0]


def check(cond, msg, detail=''):
    N[0] += 1
    if cond:
        print('PASS %s' % msg)
    else:
        FAIL.append(msg)
        print('FAIL %s  %s' % (msg, detail))


# 用户插件: 只在 example.com 生效, 不记冷却
PLUGIN_SRC = '''
from webtool.net.intercept import Hit, Interceptor

CALLS = {"inspect": 0, "preflight": 0, "note_ok": 0, "bypass": 0}

class MyWall(Interceptor):
    name = "mywall"
    priority = 5
    hosts = ("example.com",)

    def inspect(self, ctx):
        CALLS["inspect"] += 1
        if "挡路石" in (ctx.text or ""):
            return Hit(kind="waf", why="WAF 拦截", sign="挡路石")
        return None

    def preflight(self, ctx):
        CALLS["preflight"] += 1
        return None

    def note_ok(self, ctx):
        CALLS["note_ok"] += 1

    def bypass(self, ctx, hit):
        CALLS["bypass"] += 1
        return None
'''
open(os.path.join(TMP, 'mywall_plug.py'), 'w').write(PLUGIN_SRC)

cfg = {'interceptor': {'mywall': {'module': 'mywall_plug:MyWall', 'priority': 3}}}
open(os.path.join(TMP, 'plugins.json'), 'w').write(json.dumps(cfg))

from webtool.net import intercept          # noqa: E402
from webtool.net.intercept import Ctx      # noqa: E402

names = [p.name for p in intercept.interceptors()]
check('mywall' in names, '配置里的插件被注册', str(names))
check('captcha' in names, '包内默认插件仍在 (配置合并)', str(names))
prio = {p.name: p.priority for p in intercept.interceptors()}
check(prio.get('mywall') == 3, '配置里的优先级生效', str(prio))
check(prio.get('captcha') == 10 and prio.get('wechat_poc') == 15,
      '默认优先级不受影响', str(prio))

import mywall_plug                          # noqa: E402
C = mywall_plug.CALLS

# ── 域名分发 ────────────────────────────────────────────────────────────
NORMAL = '这是一段正常的搜索结果页面内容。' * 200      # > baidu 的 len_lt 2000 阈值
hit = intercept.inspect(Ctx(engine='baidu', url='https://www.baidu.com/s?wd=x',
                            text=NORMAL))
check(hit is None, '非目标域名不命中', str(hit))
check(C['inspect'] == 0, '非目标域名: 处理器根本没被调用', str(C))

hit = intercept.inspect(Ctx(engine='x', url='https://example.com/a', text='普通页'))
check(hit is None, '目标域名跑处理器但不误判')
check(C['inspect'] == 1, '目标域名: 处理器被调用一次', str(C))

hit = intercept.inspect(Ctx(engine='x', url='https://example.com/a', text='页里有挡路石'))
check(hit is not None and hit.by == 'mywall', '目标域名命中并定位到该插件', str(hit))

# ── preflight / note_ok 只问记账插件 ────────────────────────────────────
C['preflight'] = C['note_ok'] = 0
intercept.preflight(Ctx(engine='x', url='https://example.com/a'))
check(C['preflight'] == 1, '显式实现 preflight 的插件仍会被问', str(C))
intercept.note_ok(Ctx(engine='x', url='https://example.com/a'))
check(C['note_ok'] == 1, '显式实现 note_ok 的插件仍会被通知', str(C))

C['inspect'] = 0
intercept.note_ok(Ctx(engine='x', url='https://www.baidu.com/'))
check(C['inspect'] == 0, 'note_ok 不再跑 inspect', str(C))

# ── 成功请求不写 state.json ─────────────────────────────────────────────
p = os.path.join(TMP, 'state.json')
for _ in range(3):
    intercept.note_ok(Ctx(engine='baidu', url='https://www.baidu.com/s?wd=x'))
check(not os.path.exists(p), 'hits=0 时成功请求不落盘', p)

from webtool.net import captcha as _cap     # noqa: E402
_cap.mark_blocked('www.baidu.com')
stamp = os.stat(p).st_mtime_ns
time.sleep(0.05)
intercept.note_ok(Ctx(engine='baidu', url='https://www.baidu.com/s?wd=x'))
check(os.stat(p).st_mtime_ns != stamp, 'hits>0 时成功请求才复位并落盘')
check(_cap.suspended('www.baidu.com') is False, '复位后冷却解除')

# ── 停用: 配置说了算 ───────────────────────────────────────────────────
cfg['interceptor']['captcha'] = {'enabled': False}
open(os.path.join(TMP, 'plugins.json'), 'w').write(json.dumps(cfg))
os.utime(os.path.join(TMP, 'plugins.json'), (time.time() + 1, time.time() + 1))
names = [p.name for p in intercept.interceptors()]
check('captcha' not in names, '配置停用后插件不再运行', str(names))
check('mywall' in names, '其它插件不受影响', str(names))

print()
print('%d PASS, %d FAIL' % (N[0] - len(FAIL), len(FAIL)))
sys.exit(1 if FAIL else 0)
