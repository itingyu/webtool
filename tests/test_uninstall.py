#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""webtool uninstall 的契约测试 (跑 python3 tests/test_uninstall.py)

关键就两条: ①卸包只报命令、不自己动手; ②清数据必须显式 --yes, 不加就不动。
全程在临时目录里折腾, 不碰真的 ~/.webtool。
"""
import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))

from webtool.core import config_data as _cd      # noqa: E402
from webtool.core import uninstall as _un        # noqa: E402
from webtool.cli import app as _app_mod          # noqa: E402

PASS = FAIL = SKIP = 0


def check(cond, msg, extra=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print('PASS ' + msg)
    else:
        FAIL += 1
        print('FAIL ' + msg + (' | ' + str(extra) if extra else ''))


def run(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = _app_mod.main(list(argv))
    return rc, buf.getvalue()


_TMP = Path(tempfile.mkdtemp(prefix='wt-uninst-'))
_REAL_DIR = _cd.USER_DIR
_cd.USER_DIR = _TMP                     # 全部操作都落在临时目录
_ver_mod = __import__('webtool.core.version', fromlist=['x'])
_real_info = _ver_mod.info

try:
    print('\n=== 1. 安装形态 → 卸载命令 ===')
    check(_un.install_mode(prefix='/home/u/.local/pipx/venvs/webtool',
                           base_prefix='/usr')[0] == 'pipx',
          'pipx 环境 → pipx uninstall')
    check(_un.install_mode(prefix='/x/venv', base_prefix='/usr',
                           purelib='/x/venv/lib')[1].endswith(
                               '-m pip uninstall webtool'),
          'venv 环境 → 用 venv 里的 pip')
    _ver_mod.info = lambda: {'running_from_source': True}
    check(_un.install_mode(prefix='/usr', base_prefix='/usr')[0] == 'editable',
          'editable/源码安装 → 单独一档, 说明源码目录不动')
    _ver_mod.info = lambda: {'running_from_source': False}
    check(_un.install_mode(prefix='/usr', base_prefix='/usr',
                           purelib=str(Path.home() / '.local/lib/python3.12'))[0]
          == 'user', '--user 装到 ~/.local → 认出来是用户目录安装')
    check(_un.install_mode(prefix='/usr', base_prefix='/usr',
                           purelib='/usr/lib/python3/site-packages')[0]
          == 'system', '系统级安装 → 提醒可能该用发行版包管理器卸')
    check(all(_un.install_mode(prefix='/usr', base_prefix='/usr')[1]
              for _ in range(3)), '三种形态都给出具体命令, 不是空话')

    print('\n=== 2. 数据分类: 哪些删了就没 ===')
    (_TMP / 'cache').mkdir()
    (_TMP / 'cache' / 'a.bin').write_bytes(b'x' * 2048)
    (_TMP / 'secret.key').write_text('k')
    (_TMP / 'rules.json').write_text('{}')
    (_TMP / 'rules.json.bak-20260101').write_text('{}')
    (_TMP / 'state.json').write_text('{}')
    (_TMP / 'feeds.json').write_text('{}')
    (_TMP / 'something.new').write_text('?')
    inv = _un.data_inventory()
    names = lambda k: [i['name'] for i in inv['items'][k]]
    check('secret.key' in names('precious') and 'rules.json' in names('precious'),
          '保险库密钥与手写规则算不可再生', names('precious'))
    check('rules.json.bak-20260101' in names('precious'),
          '规则的备份也按不可再生算 (别被顺手带走)')
    check('feeds.json' in names('precious'), '自己加的 feed 源算不可再生')
    check('cache' in names('regen') and 'state.json' in names('regen'),
          '缓存与增量状态算可再生')
    check('something.new' in names('other'),
          '不认识的条目单列, 不擅自归类')
    check(inv['bytes'] >= 2048, '统计了总占用', inv['bytes'])

    print('\n=== 3. 删数据必须显式 --yes ===')
    check(_un.purge(yes=False)['removed'] is False and _TMP.exists(),
          '不加 yes → 只列不删')
    check(_un.purge(yes=True)['removed'] is True and not _TMP.exists(),
          '加 yes → 真删')

    print('\n=== 4. CLI ===')
    _TMP2 = Path(tempfile.mkdtemp(prefix='wt-uninst2-'))
    (_TMP2 / 'secret.key').write_text('k')
    _cd.USER_DIR = _TMP2
    rc, out = run('uninstall')
    check(rc == 0 and 'pip uninstall webtool' in out and '删了就没了' in out,
          'webtool uninstall 报命令 + 数据清单', out.splitlines()[:2])
    check('--purge-data --yes' in out, '顺手告诉怎么连数据一起清')
    rc, out = run('uninstall', '--purge-data')
    check(rc == 2 and _TMP2.exists(),
          '--purge-data 不带 --yes: rc=2 且一个字节都没动')
    rc, out = run('uninstall', '-f', 'json')
    d = json.loads(out)
    check(rc == 0 and d['data']['dir'] == str(_TMP2)
          and d['data']['items']['precious'],
          '-f json 可解析, 路径与分类都在')
    rc, out = run('uninstall', '--purge-data', '--yes', '-f', 'json')
    check(rc == 0 and json.loads(out)['purge']['removed'] and not _TMP2.exists(),
          '--purge-data --yes 真删, 且结果可解析')
finally:
    _ver_mod.info = _real_info
    _cd.USER_DIR = _REAL_DIR

print(f'\n{PASS + FAIL + SKIP} 项: {PASS} PASS, {FAIL} FAIL, {SKIP} SKIP')
sys.exit(1 if FAIL else 0)
