# -*- coding: utf-8 -*-
"""core/errors 退出码口径 + main 兜底单测 (纯本地, 不联网)

跑法: python3 tests/test_errors.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from webtool.core import errors as E                    # noqa: E402
from webtool.cli.app import main                        # noqa: E402

fails = []


def check(name, cond, extra=''):
    print(('PASS' if cond else 'FAIL') + ' ' + name + ('  ' + extra if extra else ''))
    if not cond:
        fails.append(name)


# ── 1. 退出码口径 ───────────────────────────────────────────────
print('=== 1. 退出码 ===')
check('常量 0/1/2/130',
      (E.OK, E.FAILURE, E.USAGE, E.INTERRUPTED) == (0, 1, 2, 130))
check('MEANING 覆盖全部码', set(E.MEANING) == {0, 1, 2, 130})

# ── 2. 异常自带码 ───────────────────────────────────────────────
print('=== 2. 异常 → 退出码 ===')
check('WebtoolError 默认 1', E.WebtoolError('x').exit_code == 1)
check('UsageError → 2', E.UsageError('x').exit_code == 2)
check('NotFound → 2', E.NotFound('x').exit_code == 2)
check('code= 可覆盖', E.WebtoolError('x', code=7).exit_code == 7)

# ── 3. die() ────────────────────────────────────────────────────
print('=== 3. die ===')
try:
    E.die('boom', code=3)
    check('die 抛 SystemExit', False)
except SystemExit as e:
    check('die 抛 SystemExit 且带码', e.code == 3)

# ── 4. CLI 层退出码 ─────────────────────────────────────────────
print('=== 4. main 兜底 ===')
check('未知子命令 → 2', main(['nosuchcmd']) == 2)
check('非法输出格式 → 2', main(['search', 'x', '-f', 'bogus']) == 2)

print()
if fails:
    print('FAILED: %d 项 -> %s' % (len(fails), ', '.join(fails)))
    sys.exit(1)
print('ALL PASS')
