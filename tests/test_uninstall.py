#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""webtool uninstall 的契约测试 (跑 python3 tests/test_uninstall.py)

关键就两条: ①卸包只报命令、不自己动手; ②清数据必须显式 --yes, 不加就不动。
全程在临时目录里折腾, 不碰真的 ~/.webtool。
"""
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))

from webtool.core import config_data as _cd      # noqa: E402
from webtool.core import uninstall as _un        # noqa: E402
from webtool.cli import app as _app_mod          # noqa: E402

PASS = FAIL = SKIP = 0


def check(cond, msg, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print('PASS ' + msg)
    else:
        FAIL += 1
        print('FAIL ' + msg + (' | ' + str(detail) if detail else ''))


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
    _ph = Path(tempfile.mkdtemp(prefix='wt-pipxhome-')) / 'venvs' / 'webtool'
    _ph.mkdir(parents=True)
    (_ph / 'pipx_metadata.json').write_text('{}')
    check(_un.install_mode(prefix=str(_ph), base_prefix='/usr')[0] == 'pipx',
          'PIPX_HOME 自定义成不含 pipx/venvs 的路径 → 靠 pipx_metadata.json 仍认得出')
    _vd = Path(tempfile.mkdtemp(prefix='wt-plainvenv-'))
    check(_un.install_mode(prefix=str(_vd), base_prefix='/usr')[0] == 'venv',
          '普通 venv (无 pipx 元数据) → 不会被误判成 pipx')
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

    print('\n=== 3. 默认 = 安全卸载 (卸包, 留数据) ===')
    calls = []

    def fake_spawn(cmd, timeout=300):
        calls.append(cmd)
        return 0, 'Successfully uninstalled webtool-1.8.0', ''
    _real_spawn = _un._spawn
    _un._spawn = fake_spawn
    _TMP3 = Path(tempfile.mkdtemp(prefix='wt-uninst3-'))
    (_TMP3 / 'secret.key').write_text('k')
    _cd.USER_DIR = _TMP3
    r = _un.perform()
    check(r['ok'] and calls and calls[-1][-1] == 'webtool'
          and '-y' in calls[-1] and 'uninstall' in calls[-1],
          'perform 真的卸包 (pip uninstall -y webtool)', calls[-1])
    check(_TMP3.exists() and (_TMP3 / 'secret.key').exists(),
          '安全卸载不动数据目录 (凭据还在)')
    _un._spawn = lambda cmd, timeout=300: (1, '', 'ERROR: 没有权限')
    check(_un.perform()['ok'] is False, 'pip 报错时不谎报成功')
    _un._spawn = fake_spawn

    print('\n=== 4. 完全卸载必须带参数 ===')
    calls.clear()
    rc, out = run('uninstall', '--purge-data')
    check(rc == 2 and not calls and _TMP3.exists(),
          '--purge-data 缺 --yes: rc=2, 连包都不卸, 数据也不动')
    calls.clear()
    rc, out = run('uninstall', '--dry-run')
    check(rc == 0 and not calls and 'pip uninstall' in out,
          '--dry-run 只报要跑什么, 不动手')
    calls.clear()
    rc, out = run('uninstall')
    check(rc == 2 and not calls and _TMP3.exists(),
          '默认无参: 拒绝执行 (危险命令要先确认), 包和数据都不动', rc)
    calls.clear()
    rc, out = run('uninstall', '--yes')
    check(rc == 0 and calls and _TMP3.exists() and '数据没动' in out,
          '--yes: 卸包 + 明确告诉你数据没动', out.splitlines()[:1])
    calls.clear()
    rc, out = run('uninstall', '--purge-data', '--yes', '-f', 'json')
    d = json.loads(out)
    check(rc == 0 and calls and d['package_removed']
          and d['purge']['removed'] and not _TMP3.exists(),
          '--purge-data --yes: 卸包 + 删数据, 结果可解析')

    print('\n=== 5. 装法不同, 命令不同 ===')
    _p = _un.install_mode
    _un.install_mode = lambda *a, **k: ('pipx', 'pipx uninstall webtool', '')
    calls.clear()
    _un.perform()
    check(calls[-1] == ['pipx', 'uninstall', 'webtool'],
          'pipx 装法走 pipx uninstall, 不硬套 python -m pip', calls[-1])
    _un.install_mode = lambda *a, **k: ('system', 'x', 'y')
    _un._spawn = lambda cmd, timeout=300: (1, '', 'ERROR: not installed')
    r = _un.perform()
    check('apk' in (r.get('hint') or '') and 'apt' in (r.get('hint') or ''),
          '系统级装法被 pip 拒 → 指回发行版包管理器', r.get('hint'))
    _un.install_mode, _un._spawn = _p, _real_spawn

finally:
    _ver_mod.info = _real_info
    _cd.USER_DIR = _REAL_DIR

print(f'\n{PASS + FAIL + SKIP} 项: {PASS} PASS, {FAIL} FAIL, {SKIP} SKIP')
sys.exit(1 if FAIL else 0)
