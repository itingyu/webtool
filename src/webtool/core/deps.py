"""装包完整性: 少依赖时给出"照抄就能修"的命令

webtool 是**全装**形态 —— 所有依赖 (含 pandas/numpy/akshare/cryptography 这些
重的) 都在 pyproject 的 dependencies 里, 没有 extras 分档。所以运行期 import
不到某个依赖, 只有两种可能:

  1. 装的时候用了 `--no-deps` 之类的非常规姿势, 依赖没跟着进来;
  2. 装完之后环境被动过 (有人卸了 pandas, 或 pipx venv 被清理)。

两种情况都用同一条指引修复, 只是命令随装法不同 (pipx 要用 pipx 重装, 系统级
被 PEP 668 挡着不能裸 pip)。装法判断复用 core/uninstall.py, 两处口径一致。

**别在这里写"pip install webtool[stock]"**: extras 已经没有了, 那样只会让
pip 打印 "does not provide the extra" 警告, 什么也没修。
"""

import sys


def reinstall_command():
    """按当前装法给出"重装 webtool (连依赖)"的确切命令"""
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
        # 源码/可编辑安装: 必须在仓库根目录重新解析依赖, 别去 PyPI 拉一份
        # 同名包把可编辑链接顶掉
        return f'{py} -m pip install -e .   (在 webtool 源码目录里跑)'
    if mode == 'system':
        # 系统 Python 被 PEP 668 保护: 裸 pip 会报 externally-managed-environment
        return (f'pipx install --force webtool   (推荐) 或 '
                f'{py} -m pip install --user --force-reinstall webtool')
    return f'{py} -m pip install --force-reinstall webtool'


def install_hint(missing=''):
    """一行"怎么修": [缺了什么 →] 重装命令。直接拼进报错/状态行"""
    cmd = reinstall_command()
    if missing:
        return f'缺 {missing} (装包不完整); 重装: {cmd}'
    return f'装包不完整; 重装: {cmd}'
