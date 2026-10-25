"""配置里有、代码里没有的插件: 不报错, 只在真正调用时提示"插件未找到"

回归点: plugins check 把缺失算成 missing 而不是 failed (退出码 0);
拦截器缺失时静默跳过, 其余功能照常。
"""
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout

TMP = tempfile.mkdtemp(prefix='webtool-missing-')
os.environ['WEBTOOL_DIR'] = TMP
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

with open(os.path.join(TMP, 'plugins.json'), 'w', encoding='utf-8') as f:
    json.dump({'interceptor': {
        'ghost': {'module': 'webtool.net.nope:NoSuchPlugin', 'priority': 5}}}, f)

FAIL = []
N = [0]


def check(cond, msg, detail=''):
    N[0] += 1
    if cond:
        print('PASS %s' % msg)
    else:
        FAIL.append(msg)
        print('FAIL %s  %s' % (msg, detail))
from webtool.cli import plugins as cli_plugins          # noqa: E402
from webtool.core import plugins                        # noqa: E402
from webtool.net import intercept                       # noqa: E402

buf = io.StringIO()
with redirect_stdout(buf):
    code = cli_plugins._check()
rep = json.loads(buf.getvalue())
check(code == 0, '体检退出码为 0 (缺失不算失败)', code)
check(rep['failed'] == 0, '缺失不计入 failed', rep['failed'])
check(rep['missing'] >= 1, '缺失单独列在 missing', rep['missing'])
check(any(m['plugin'] == 'ghost' for m in rep['missing_plugins']),
      'missing_plugins 点名 ghost', rep['missing_plugins'])

check('ghost' in intercept.missing(), '拦截器层也认下这条缺失')
names = [p.name for p in intercept.interceptors()]
check('captcha' in names, '缺失插件不影响其余拦截器加载', names)
check('ghost' not in names, '缺失插件不会混进生效列表', names)

try:
    plugins.INTERCEPTORS.call('ghost')
    err = None
except Exception as e:                      # noqa: BLE001
    err = e
check(type(err).__name__ == 'PluginError' and '插件未找到' in str(err),
      '真要调用时才提示插件未找到', repr(err))

ok, why = plugins.INTERCEPTORS.health('ghost')
check(ok is False and '插件未找到' in why, 'health 同样给人话', why)

st = plugins.INTERCEPTORS.status('ghost')
check(st and st[0]['state'] == 'missing', 'status 标成 missing', st)

print('\n%d PASS, %d FAIL' % (N[0] - len(FAIL), len(FAIL)))
sys.exit(1 if FAIL else 0)
