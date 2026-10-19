"""装包完整性: 少依赖时给出"照抄就能修"的命令

webtool 是**全装**形态 —— 所有依赖 (含 pandas/numpy/akshare/cryptography 这些
重的) 都在 pyproject 的 dependencies 里, 没有 extras 分档。所以运行期 import
不到某个依赖, 只有两种可能:

  1. 装的时候用了 `--no-deps` 之类的非常规姿势, 依赖没跟着进来;
  2. 装完之后环境被动过 (有人卸了 pandas, 或 pipx venv 被清理)。

两种情况都用同一条指引修复, 只是命令随装法不同 (pipx 要用 pipx 重装, 系统级
被 PEP 668 挡着不能裸 pip)。装法判断复用 core/uninstall.py, 两处口径一致。

**Termux / Android 是唯一的例外, 而且方向完全不同**: PyPI 上没有任何
`android_*` 平台的轮子 (只发 manylinux/macos/win), `cryptography`/`numpy`/
`pandas` 在 Termux 上只能从源码构建 —— cryptography 要 Rust 且 rustup 不认
`aarch64-unknown-linux-android` 这个 target, 直接构建失败。所以那边**不能
让 pip 去装**, 得用 Termux 自己的包 (`pkg install python-cryptography`)。
这种时候还甩一句 "重装 webtool" 是把人往坑里带: 他照着重装一百次还是一样报错。

**别在这里写"pip install webtool[stock]"**: extras 已经没有了, 那样只会让
pip 打印 "does not provide the extra" 警告, 什么也没修。
"""

import os
import sys

# Termux 上 PyPI 没有轮子的那几个: PyPI 名 → Termux 包名。
# termux-main 里有 cryptography/numpy/lxml/pillow; pandas/scipy 只在 TUR
# (第三方源), 得先 `pkg install tur-repo` 才搜得到。
TERMUX_NATIVE = {
    'cryptography': 'python-cryptography',
    'numpy': 'python-numpy',
    'lxml': 'python-lxml',
    'pillow': 'python-pillow',
    'pandas': 'python-pandas',
    'scipy': 'python-scipy',
}
TERMUX_NEEDS_TUR = ('pandas', 'scipy')


def on_termux():
    """是不是跑在 Termux (Android) 里

    TERMUX_VERSION 是 Termux 自己导出的; 拿不到时退回看安装前缀 —— 别的
    系统不会把包装到 /data/data/com.termux 底下。
    """
    if os.environ.get('TERMUX_VERSION'):
        return True
    for s in (sys.prefix, sys.executable, sys.base_prefix):
        if s and 'com.termux' in str(s):
            return True
    return False


def termux_command(lib):
    """Termux 上装某个库的正确命令; 不是 Termux 原生库就返回空串"""
    pkg = TERMUX_NATIVE.get((lib or '').strip().lower())
    if not pkg:
        return ''
    if (lib or '').strip().lower() in TERMUX_NEEDS_TUR:
        return f'pkg install tur-repo && pkg install {pkg}'
    return f'pkg install {pkg}'


def reinstall_command():
    """按当前装法给出"重装 webtool"的确切命令"""
    from webtool.core import uninstall as _un
    try:
        mode = _un.install_mode()[0]
    except Exception:
        mode = 'unknown'
    py = sys.executable or 'python3'
    if mode == 'pipx':
        # pipx reinstall 会照原样重装并补齐依赖, 比 install --force 更少副作用
        return 'pipx reinstall webtool'
    if mode == 'editable':
        # 源码目录运行只是一时的, 正式装要落成 site-packages 里的独立一份 ——
        # 一律不用 -e (可编辑本质是软链回源码, 源码一挪就断, 还和 upgrade 打架)。
        # --no-deps 只换本体, 缺的依赖交给 upgrade_deps 那一步补
        return (f'{py} -m pip install --force-reinstall --no-deps .   '
                f'(在 webtool 源码目录里跑; 装成正式包, 不要 -e)')
    if mode == 'system':
        # 系统 Python 被 PEP 668 保护: 裸 pip 会报 externally-managed-environment
        return (f'pipx install --force webtool   (推荐) 或 '
                f'{py} -m pip install --user --force-reinstall webtool')
    return f'{py} -m pip install --force-reinstall webtool'


def _ours_path(name):
    """缺的是不是我们自己的文件? 是就返回相对路径 (不是 → '')

    裸名字 (adminfmt) 和全名 (webtool.cli.adminfmt) 都认 —— 报错里两种都出现过。
    """
    import pathlib
    pkg = pathlib.Path(__file__).resolve().parent.parent   # …/site-packages/webtool
    tail = (name or '').split('.')[-1].strip()
    if not tail:
        return ''
    for hit in sorted(pkg.rglob(tail + '.py')):
        try:
            return str(hit.relative_to(pkg.parent))
        except ValueError:
            return str(hit)
    return ''


def install_hint(missing=''):
    """一行"怎么修": [缺了什么 →] 重装命令。直接拼进报错/状态行"""
    name = (missing or '').strip()
    if name and on_termux():
        tcmd = termux_command(name)
        if tcmd:
            return (f'缺 {name} (Android 上 PyPI 没有它的轮子, pip 装不了); '
                    f'装系统包: {tcmd}')
    where = _ours_path(name)
    if where:
        # 自家文件: 不是"少装了个依赖", 是这份安装本身不完整 —— 多半是上次升级
        # 只卸没装上 (pip 先卸后装), 或者机器上有两份 webtool, 跑的不是你以为的那份。
        return (f'自家文件 {where} 缺了 —— 这份安装不完整 (上次升级只卸没装上, '
                f'或机器上有两份 webtool)。先看跑的是哪一份: '
                f'python3 -c "import webtool;print(webtool.__file__)"; 再重装: '
                f'{reinstall_command()}')
    cmd = reinstall_command()
    if name:
        return f'缺 {name} (装包不完整); 重装: {cmd}'
    return f'装包不完整; 重装: {cmd}'
