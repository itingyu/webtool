# -*- coding: utf-8 -*-
"""`webtool upgrade` 的线路判定回归测试

盯的是"线路: 走代理"这句会不会骗人:
  1. pip / git 只认环境变量, 判线路必须按**源**的协议来 —— ssh / git:// 源
     眼里没有 HTTP(S)_PROXY, 判了也是白判;
  2. 白判必须说出来 (route_note), 不能只印"走代理"让用户以为通了。

曾经的真事: 以 git+ssh 装 webtool 的机器上跑 upgrade, 输出"线路 走代理 127.0.0.1:2080",
实际 ssh 直连, 在只有代理能出网的环境里表现为长时间卡死 + 一句"判不出来"。

跑法: python3 tests/test_upgrade_spec.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'src'))

TMP = tempfile.mkdtemp(prefix='webtool-upgrade-spec-')
os.environ['WEBTOOL_DIR'] = TMP
with open(os.path.join(TMP, 'rules.json'), 'w', encoding='utf-8') as f:
    json.dump({'default': 'proxy:default',
               'proxies': {'default': 'http://127.0.0.1:2080'},
               'rules': [{'match': {'domain': ['*.lab']}, 'action': 'direct'}]}, f)

from webtool.core import upgrade as up          # noqa: E402
from webtool.cli import app as app_mod          # noqa: E402

fails = []


def check(name, cond, detail=''):
    if cond:
        print('PASS %s' % name)
    else:
        print('FAIL %s %s' % (name, detail))
        fails.append(name)


PROXY_ENV = {'HTTP_PROXY': 'http://127.0.0.1:2080',
             'HTTPS_PROXY': 'http://127.0.0.1:2080',
             'NO_PROXY': '', 'no_proxy': ''}
DIRECT_ENV = {'NO_PROXY': '*', 'no_proxy': '*'}

# ── spec_url: pip spec → (判线路用的 URL, 传输方式) ──────────────────────
cases = [
    ('webtool @ git+https://github.com/itingyu/webtool',
     'https://github.com/itingyu/webtool', 'https'),
    ('git+https://github.com/a/b.git@main', 'https://github.com/a/b.git@main',
     'https'),
    ('git+ssh://git@github.com/itingyu/webtool',
     'ssh://git@github.com/itingyu/webtool', 'ssh'),
    ('git@github.com:itingyu/webtool.git',
     'ssh://git@github.com/itingyu/webtool.git', 'ssh'),
    ('git://github.com/a/b.git', 'git://github.com/a/b.git', 'git'),
    ('requests', 'https://pypi.org/simple/', 'index'),
    ('/tmp/somewhere', '/tmp/somewhere', 'local'),
]
for spec, want_url, want_tr in cases:
    got_url, got_tr = up.spec_url(spec)
    check('spec_url %s' % spec, (got_url, got_tr) == (want_url, want_tr),
          '%r != %r' % ((got_url, got_tr), (want_url, want_tr)))

check('spec_url 不给 spec → 按默认官方仓库 (https)',
      up.spec_url(None)[1] == 'https', str(up.spec_url(None)))

# ── 只有 http(s)/index 才认环境变量里的代理 ─────────────────────────────
check('https 源 + 代理 → 无需提示',
      app_mod._pip_route_note('git+https://github.com/a/b', PROXY_ENV) is None)
check('PyPI 源 + 代理 → 无需提示',
      app_mod._pip_route_note('requests', PROXY_ENV) is None)
note = app_mod._pip_route_note('git+ssh://git@github.com/a/b', PROXY_ENV)
check('ssh 源 + 代理 → 明说代理无效并给出替代命令',
      note and '不认' in note and 'git+https' in note, str(note))
note = app_mod._pip_route_note('git://github.com/a/b.git', PROXY_ENV)
check('git:// 源 + 代理 → 同样明说', note and '不认' in note, str(note))
check('ssh 源但本来就是直连 → 不唠叨',
      app_mod._pip_route_note('git+ssh://git@github.com/a/b', DIRECT_ENV) is None)

# ── 判线路用的是"源的地址", 不是写死的 github.com ────────────────────────
check('默认源 (github) → 规则表判代理, 给 pip 塞代理变量',
      app_mod._pip_proxy_env().get('HTTPS_PROXY') == 'http://127.0.0.1:2080',
      str(app_mod._pip_proxy_env()))
check('--from 换成规则表判直连的源 → 改成 NO_PROXY=* (不拿 github 的线路套)',
      set(app_mod._pip_proxy_env('git+https://git.lab/x/y.git')) ==
      {'NO_PROXY', 'no_proxy'},
      str(app_mod._pip_proxy_env('git+https://git.lab/x/y.git')))

# ── note 要出现在人读输出与 json 里 ─────────────────────────────────────
_real_pip = up._pip
up._pip = lambda args, timeout=None, env_extra=None: (0, '', '')
_info = up.check('git+ssh://git@github.com/a/b', env_extra=PROXY_ENV, note=note)
check('check: json 带 route_note', _info.get('route_note') == note)
check('check: describe 打成"注意"行', '注意' in up.describe(_info),
      up.describe(_info).replace('\n', ' | ')[:120])
_info2 = up.check('git+https://github.com/a/b', env_extra=PROXY_ENV)
check('check: 正常源不带 route_note, 也不多一行',
      'route_note' not in _info2 and '注意' not in up.describe(_info2))

_res = up.upgrade('git+ssh://git@github.com/a/b', env_extra=PROXY_ENV, note=note)
check('upgrade: log 里紧跟 pip 行插了注意',
      _res['log'][1].startswith('注意') and _res['route_note'] == note,
      str(_res['log'][:2]))
up._pip = _real_pip

print()
if fails:
    print('FAILED: %s' % ', '.join(fails))
    sys.exit(1)
print('ALL PASS')
