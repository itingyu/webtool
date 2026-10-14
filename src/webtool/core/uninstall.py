# -*- coding: utf-8 -*-
"""卸载 (webtool uninstall)

分两件事，谁也不替谁干：

1. **包**——默认就卸，但**只卸包**（安全卸载）：数据、配置、凭据一概留着，装回来
   就是原样。命令按装法给（pipx / venv / --user / 系统），系统包管理器装的包试 pip
   失败时会指回 apk/apt。
2. **数据**——`~/.webtool` 里的东西 pip 完全不知道，属于"完全卸载"那一档：必须显式
   `--purge-data --yes` 才动，而且会先列清楚哪些删了就没了（保险库密钥、手写规则、
   自定义站点）。

不着手反悔的两种"只报不删"：`--dry-run` 和 `--purge-data` 缺 `--yes`。
"""
import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

from webtool.core import config_data

# 删了就没了: 保险库密钥、手写规则、自定义站点、插件清单
PRECIOUS = ('secret.key', 'rules.json', 'config.json', 'plugins.json',
            'sites', 'filters.json', 'feeds.json', 'zen.json')
# 跑起来会自己长回来的
REGEN = ('cache', 'state.json', 'sticky.json', 'feed_state.json',
         'feed_health.json')


def install_mode(prefix=None, base_prefix=None, purelib=None):
    """(形态, 卸载命令, 附注) —— 只报命令, 不执行

    形态影响命令: pipx 有 pipx 自己的清单, venv 要用 venv 里的 pip, 系统级
    就别带 venv 假设。editable (跑源码) 单独说一句 —— 解除链接, 源码目录不动。
    """
    prefix = str(prefix if prefix is not None else sys.prefix)
    base_prefix = str(base_prefix if base_prefix is not None else sys.base_prefix)
    purelib = str(purelib or sysconfig.get_paths().get('purelib', ''))
    py = sys.executable or 'python3'
    from webtool.core import version as _ver
    if 'pipx/venvs' in prefix.replace('\\', '/'):
        return 'pipx', 'pipx uninstall webtool', 'pipx 环境, 用它自己的清单卸'
    if prefix != base_prefix:
        return 'venv', '%s -m pip uninstall webtool' % py, \
            'venv 环境, 用 venv 里的 pip; 删掉整个 venv 目录也等效'
    if _ver.info().get('running_from_source'):
        return 'editable', '%s -m pip uninstall webtool' % py, \
            'editable/源码安装: 只解除链接, 源码目录原地不动 (不想留就自己删)'
    if str(Path(purelib).resolve()).startswith(str(Path.home() / '.local')):
        return 'user', '%s -m pip uninstall webtool' % py, \
            '--user/用户目录安装, 删包只用得上这一条'
    return 'system', '%s -m pip uninstall webtool' % py, \
        '系统级安装; 若包是发行版包管理器装的, 用它卸 (apk/apt), 别用 pip'


def _kind(name):
    if name in PRECIOUS or name.startswith('rules.json.bak'):
        return 'precious'
    if name in REGEN:
        return 'regen'
    return 'other'


def _size(path):
    p = Path(path)
    if p.is_file():
        return p.stat().st_size
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def data_inventory(user_dir=None):
    """数据目录清单: 有什么、多大、哪些删了就没"""
    d = Path(user_dir or config_data.USER_DIR)
    items = {'precious': [], 'regen': [], 'other': []}
    if d.exists():
        for name in sorted(os.listdir(d)):
            items[_kind(name)].append(
                {'name': name, 'bytes': _size(d / name)})
    return {'dir': str(d), 'exists': d.exists(),
            'bytes': _size(d) if d.exists() else 0, 'items': items}


def plan(user_dir=None):
    """卸载指引: 命令 + 数据清单。只报不做"""
    mode, cmd, note = install_mode()
    return {'mode': mode, 'uninstall_cmd': cmd, 'note': note,
            'data': data_inventory(user_dir)}


def purge(user_dir=None, yes=False):
    """删数据目录。yes=False 时只报不删 —— 默认什么都不动"""
    inv = data_inventory(user_dir)
    if not inv['exists']:
        return {'ok': True, 'removed': False, 'reason': '目录不存在',
                'path': inv['dir'], 'bytes': 0}
    if not yes:
        return {'ok': True, 'removed': False, 'reason': '未加 --yes, 只列不删',
                'path': inv['dir'], 'bytes': inv['bytes']}
    shutil.rmtree(inv['dir'])
    return {'ok': not os.path.exists(inv['dir']), 'removed': True,
            'path': inv['dir'], 'bytes': inv['bytes']}


def describe(plan_info, purge_result=None):
    """人话版 (返回字符串, 调用方决定怎么输出)"""
    d = plan_info['data']
    lines = ['卸载是两件事: 包归 pip, 数据归下面这份目录。', '',
             '1) 卸包 (形态: %s)' % plan_info['mode'],
             '   %s' % plan_info['uninstall_cmd'],
             '   %s' % plan_info['note'], '',
             '2) 数据目录%s: %s' % (
                 ' (%d KB)' % (d['bytes'] // 1024) if d['exists'] else ' (不存在)',
                 d['dir'])]
    if d['exists']:
        for key, label in (('precious', '删了就没了'),
                           ('regen', '自己会长回来'),
                           ('other', '其他')):
            names = ['%s%s' % (i['name'],
                               ' (%d KB)' % (i['bytes'] // 1024) if i['bytes'] >= 1024 else '')
                     for i in d['items'][key]]
            if names:
                lines.append('   %s: %s' % (label, ', '.join(names)))
        lines.append('   想连数据一起清掉: webtool uninstall --purge-data --yes')
    if purge_result:
        if purge_result.get('removed'):
            lines.append('   已删除 %s (%d KB)' % (
                purge_result['path'], purge_result['bytes'] // 1024))
        else:
            lines.append('   未删除: %s' % purge_result.get('reason'))
    return '\n'.join(lines)


def purge_data(user_dir=None, yes=False):
    """CLI 用的删数据入口 (yes=False 只列不删, 由调用方给退出码)"""
    return purge(user_dir, yes=yes)


def _spawn(cmd, timeout=300):
    """跑外部命令 (单独一层, 便于测试; 不做 shell 解释)"""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout or '', r.stderr or ''
    except subprocess.TimeoutExpired:
        return 1, '', '超时 (%ss)' % timeout
    except OSError as e:
        return 1, '', str(e)


def perform(dry=False):
    """默认动作: 安全卸载 —— 卸包, 数据原样留着

    自己删自己这件事得有个度: 跑在被删的那份代码里, 文件都删掉了进程也还活着,
    所以不看"进程是否还在"来判断成败, 直接看命令退出码。
    """
    mode, cmd, note = install_mode()
    argv = (['pipx', 'uninstall', 'webtool'] if mode == 'pipx'
            else [sys.executable or 'python3', '-m', 'pip', 'uninstall', '-y',
                  'webtool'])
    if dry:
        return {'ok': True, 'dry_run': True, 'mode': mode, 'cmd': argv,
                'note': note}
    rc, out, err = _spawn(argv)
    res = {'ok': rc == 0, 'dry_run': False, 'mode': mode, 'cmd': argv,
           'note': note, 'out': out.strip(), 'err': err.strip()}
    if rc and mode == 'system':
        # 系统级装法可能是发行版包管理器装的, pip 卸不动 (也不该由它卸)
        res['hint'] = ('若这是发行版包管理器装的包, 用它卸载: '
                       'apk del <包名> / apt remove <包名>')
    return res


def describe_uninstall(res, data, purge=None):
    """卸载结果的人话版"""
    lines = []
    if res.get('dry_run'):
        lines.append('--dry-run: 什么都没动。默认会跑:')
        lines.append('   %s' % ' '.join(res['cmd']))
    elif res.get('ok'):
        lines.append('已安全卸载 (形态: %s): %s' % (res['mode'], ' '.join(res['cmd'])))
    else:
        lines.append('卸包失败 (形态: %s): %s' % (res['mode'], ' '.join(res['cmd'])))
        last = (res.get('err') or res.get('out') or '').strip().splitlines()
        if last:
            lines.append('   %s' % last[-1])
        if res.get('hint'):
            lines.append('   %s' % res['hint'])
    lines.append('数据没动: %s%s' % (
        data['dir'],
        ' (%d KB)' % (data['bytes'] // 1024) if data['exists'] else ' (不存在)'))
    if data['exists'] and data.get('items', {}).get('precious'):
        lines.append('   里面这些删了要重配: %s' % ', '.join(
            i['name'] for i in data['items']['precious']))
    if purge is None:
        lines.append('   要连数据一起删 (完全卸载): webtool uninstall --purge-data --yes')
    else:
        lines.append('   数据已删: %s%s' % (
            purge['path'], ' (%d KB)' % (purge['bytes'] // 1024)
            if purge.get('bytes') else ''))
    return '\n'.join(lines)
