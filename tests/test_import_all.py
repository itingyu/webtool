# -*- coding: utf-8 -*-
"""全模块导入冒烟: 每个 .py 都 import 一遍

为什么单列一个测试: 拆包时最容易犯的错是"少导出一个名字", 而它只在**某条
调用路径被走到**时才炸 (本次 _textfmt 拆分就漏了 _industry_cell, 只有跑
业务渲染才会红)。逐个 import 能把这类错误在 1 秒内全暴露 —— 拆包、改名、
挪文件之后先跑它。

跳过: scripts/ 下的开发脚本与 tests/ 自身 (只关心装出来的包)。
跑法: python3 tests/test_import_all.py
"""
import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    'src', 'webtool')
SKIP_DIRS = {'__pycache__'}

fails = []


def modname(path):
    rel = os.path.relpath(path, os.path.dirname(ROOT)).replace(os.sep, '.')
    assert rel.endswith('.py')
    rel = rel[:-3]
    return rel[:-9] if rel.endswith('.__init__') else rel


mods = []
for dirpath, dirnames, filenames in os.walk(ROOT):
    dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
    for f in sorted(filenames):
        if f.endswith('.py'):
            mods.append(modname(os.path.join(dirpath, f)))

print('待导入模块 %d 个' % len(mods))
bad = []
for m in sorted(mods):
    try:
        importlib.import_module(m)
    except Exception as e:
        bad.append((m, '%s: %s' % (type(e).__name__, e)))

print('PASS 全部可导入' if not bad else 'FAIL %d 个模块导入失败' % len(bad))
for m, e in bad:
    print('  FAIL %s -> %s' % (m, e))

# 顶层包也要能 import (__init__ 里往往有导出面)
for top in ('webtool', 'webtool.cli', 'webtool.net', 'webtool.core',
            'webtool.pipeline', 'webtool.engines',
            'webtool.feeds', 'webtool.radar', 'webtool.render'):
    try:
        importlib.import_module(top)
    except Exception as e:
        bad.append((top, str(e)))
        print('  FAIL %s -> %s' % (top, e))

if bad:
    print('\nFAILED: %d 个模块导入失败' % len(bad))
    sys.exit(1)
print('ALL PASS')
