"""pytest 入口：逐个子进程执行 tests/test_*.py 手写脚本，断言退出码 0

tests/ 下的脚本是顶层 check() + sys.exit 的手写序列，不能被 pytest 直接收集
（顶层 sys.exit 触发 INTERNALERROR）。收集约定见 pytest.ini（python_files=check_*.py），
本文件是唯一收集目标。脚本自身的独立跑法不变：python3 tests/test_xxx.py
"""
import glob
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))

SCRIPTS = sorted(
    os.path.relpath(p, HERE)
    for p in glob.glob(os.path.join(HERE, 'test_*.py'))
)


@pytest.mark.parametrize('script', SCRIPTS)
def test_script(script):
    r = subprocess.run(
        [sys.executable, os.path.join(HERE, script)],
        capture_output=True, text=True, timeout=600,
    )
    assert r.returncode == 0, (
        f'{script} 退出码 {r.returncode}\n'
        f'--- stdout(尾 2000 字) ---\n{r.stdout[-2000:]}\n'
        f'--- stderr(尾 2000 字) ---\n{r.stderr[-2000:]}'
    )
