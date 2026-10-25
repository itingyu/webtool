# -*- coding: utf-8 -*-
"""重装 / 升级 / 卸载不许动用户已有数据

~/.webtool 里的东西是用户手写的资产 (配置、分流规则、保险库凭据), 而
pip 重装、`webtool upgrade`、`webtool uninstall` 都会碰到同一个目录附近。
这条不变量必须钉死, 否则"升个级配置没了"这类事故没有任何东西能拦住。

这里锁的是**应用侧**的保证 (pip 那半由 test 里的"不动已有文件"口径覆盖):
  1. 首次运行补默认配置 —— 缺哪份补哪份, 已有的一律不碰;
  2. 配置迁移 (遗留键搬家) 不覆盖明确写下的配置, 也不删不认识的东西;
  3. 卸载默认只卸包, 数据一个字不动 (要删得显式 --purge-data --yes)。

跑法: python3 tests/test_reinstall_keeps_config.py
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'src'))

TMP = tempfile.mkdtemp(prefix='webtool-keepcfg-')
os.environ['WEBTOOL_DIR'] = TMP

from webtool.core import bootstrap as boot        # noqa: E402
from webtool.core import uninstall as un          # noqa: E402
from webtool.net import proxy as wproxy           # noqa: E402

fails = []


def check(cond, msg, detail=''):
    print(('PASS ' if cond else 'FAIL ') + msg + ('' if cond else '  ' + detail))
    if not cond:
        fails.append(msg)


def md5s(root):
    out = {}
    for r, _d, fs in os.walk(root):
        for f in fs:
            p = os.path.join(r, f)
            with open(p, 'rb') as fh:
                out[os.path.relpath(p, root)] = hashlib.md5(fh.read()).hexdigest()
    return out


def write(name, data):
    p = os.path.join(TMP, name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8') as f:
        f.write(data if isinstance(data, str)
                else json.dumps(data, ensure_ascii=False, indent=2))
    return p


# ── 1. 用户已有全套配置: 首次运行不许碰 ─────────────────────────────────
CONFIG = {'timeout': 33, 'ssl_verify': False, 'my_own_knob': 'keep-me'}
RULES = {'default': 'proxy:default',
         'proxies': {'default': 'http://127.0.0.1:2080'},
         'rules': [{'match': {'domain': ['*.cn']}, 'action': 'direct'}],
         'my_own_key': ['hand-written']}
write('config.json', CONFIG)
write('rules.json', RULES)
write('plugins.json', {'my_plugin': {'enabled': True}})
write('secrets/vault.json', '{"mine": "ciphertext"}')
write('MY-NOTES.md', 'do not touch')
# 证书目录: 首次运行会把包内那份落过来, 用户已经有的 (含自己改过的说明) 不许碰
write('certs/README.md', 'my own cert notes')
write('certs/ca-bundle.pem', 'my own bundle')
# geo 数据: 首次运行也会落一份 (包内自带), 用户已有的 (可能自己 upd 过) 不许碰
write('geo/geosite.dat', 'my own geosite')
write('geo/geoip.dat', 'my own geoip')
os.makedirs(os.path.join(TMP, 'certs', 'extra'), exist_ok=True)
before = md5s(TMP)

created = boot.ensure_user_files()
check(created == [], '首次运行: 已有的文件一个都没新建', str(created))
check(md5s(TMP) == before, '首次运行: 已有文件一个字节没变',
      str([k for k in before if before.get(k) != md5s(TMP).get(k)]))

# 规则表走一遍读取 (会经过遗留键迁移那条路)
wproxy._load_rules_file(None)
loaded = json.load(open(os.path.join(TMP, 'rules.json'), encoding='utf-8'))
check(loaded.get('my_own_key') == ['hand-written'], '读过规则表后: 手写键还在')
check(loaded['proxies']['default'] == 'http://127.0.0.1:2080',
      '读过规则表后: 代理线路没被改')
check(md5s(TMP)['rules.json'] == before['rules.json'], '读过规则表后: 文件没被重写')

# ── 2. 只缺 rules.json 时才补, 且不动别的 ───────────────────────────────
os.unlink(os.path.join(TMP, 'rules.json'))
created = boot.ensure_user_files()
check(os.path.isfile(os.path.join(TMP, 'rules.json')), '缺 rules.json → 补上')
check(json.load(open(os.path.join(TMP, 'config.json')))['my_own_knob'] == 'keep-me'
      and os.path.isfile(os.path.join(TMP, 'secrets', 'vault.json')),
      '补种子不改动 config.json / 凭据')

# ── 2.5 证书目录: 缺了就整棵补回来, 已有的不碰 ──────────────────────────
# 包目录在 site-packages 里, 升级整棵换掉 —— 所以"投放点"必须落在用户目录,
# 而且安装/首次运行就要建出来: 目录不存在, 用户按报错去放证书只会扑空。
os.unlink(os.path.join(TMP, 'rules.json'))
shutil.rmtree(os.path.join(TMP, 'certs'))
created = boot.ensure_user_files()
check(os.path.isdir(os.path.join(TMP, 'certs', 'extra')),
      '首次运行: 证书投放点 certs/extra/ 建出来了', str(created))
check(os.path.isfile(os.path.join(TMP, 'certs', 'ca-bundle.pem'))
      and os.path.getsize(os.path.join(TMP, 'certs', 'ca-bundle.pem')) > 0,
      '首次运行: 自带 CA 包复制到用户目录 (可增补企业根)')
check(os.path.isfile(os.path.join(TMP, 'certs', 'README.md')),
      '首次运行: 投放点说明一起落地 (空目录不解释自己)')
with open(os.path.join(TMP, 'certs', 'extra', 'mine.pem'), 'w') as f:
    f.write('my cert\n')
with open(os.path.join(TMP, 'certs', 'ca-bundle.pem'), 'w') as f:
    f.write('my own bundle\n')
created = boot.ensure_user_files()
check(created == [], '再跑一次: 已有的证书/目录一个都没重建', str(created))
check(open(os.path.join(TMP, 'certs', 'extra', 'mine.pem')).read() == 'my cert\n'
      and open(os.path.join(TMP, 'certs', 'ca-bundle.pem')).read() == 'my own bundle\n',
      '用户改过的证书与 CA 包不被包内那份覆盖')

# ── 2.6 geo 数据: 包内自带一份, 首次运行落到用户目录; 已有的不覆盖 ──────
shutil.rmtree(os.path.join(TMP, 'geo'))
created = boot.ensure_user_files()
check(os.path.getsize(os.path.join(TMP, 'geo', 'geosite.dat')) > 0
      and os.path.getsize(os.path.join(TMP, 'geo', 'geoip.dat')) > 0,
      '首次运行: geosite/geoip 落到用户 geo 目录 (规则装完即用)', str(created))
with open(os.path.join(TMP, 'geo', 'geosite.dat'), 'wb') as f:
    f.write(b'my updated geosite')
boot.ensure_user_files()
check(open(os.path.join(TMP, 'geo', 'geosite.dat'), 'rb').read() == b'my updated geosite',
      '用户 upd 过的 geo 库不被包内那份覆盖')

# ── 3. 种子文件清单只该有"整份落盘"的那几样 ─────────────────────────────
check('config.json' not in boot.SEED_FILES
      and 'plugins.json' not in boot.SEED_FILES,
      'SEED_FILES 只补整份落盘的文件 (不含走两层合并的 config.json)', str(boot.SEED_FILES))

# ── 4. 卸载默认不动数据, 只有显式 --purge-data 才删 ─────────────────────
inv = un.data_inventory()
check(inv is not None, '卸载: 默认报的是安全模式 (不删数据)')
dry = un.perform(dry=True)
check(dry['dry_run'] and 'uninstall' in ' '.join(dry['cmd']),
      '卸载 dry-run: 只列出 pip uninstall, 不碰数据')
check(os.path.isdir(TMP), '卸载后 ~/.webtool 仍在')

# ── 5. upgrade 的 pip 参数里不该出现任何"清home"的动作 ──────────────────
from webtool.core import upgrade as up            # noqa: E402
_real, _real_fetch = up._pip, up.fetch_git


def _capture(args, timeout=None, env_extra=None):
    _capture.args = list(args)
    return 0, '', ''


# 三步走之后 upgrade 先 fetch_git (真 git clone, 要网络), 这里两步都喂成假的。
# 断言只关心"pip 参数里没有卸载/删数据的动作" —— 主路与退路各验一次。
up._pip = _capture
up.fetch_git = lambda *a, **k: (TMP, [], None)      # ① 取到源码
up.upgrade('webtool @ git+https://github.com/itingyu/webtool')
_args = getattr(_capture, 'args', [])
check(_args[:3] == ['install', '--force-reinstall', '--no-deps'] and TMP in _args,
      '取到源码: pip install --force-reinstall --no-deps <本地目录>', str(_args))
_capture.args = []
up.fetch_git = lambda *a, **k: (None, [], None)     # ② 取不到源码的退路
up.upgrade('webtool @ git+https://github.com/itingyu/webtool')
_args2 = getattr(_capture, 'args', [])
check(_args2[:1] == ['install']
      and not any(a in _args2 for a in ('uninstall', '--purge', 'clean')),
      '退路: pip 装 VCS 源, 同样不卸载/不删数据', str(_args2))
up._pip = _real
up.fetch_git = _real_fetch

print()
if fails:
    print('FAILED: %s' % ', '.join(fails))
    sys.exit(1)
print('ALL PASS')
