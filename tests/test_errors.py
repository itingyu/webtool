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


def check(cond, msg, detail=''):
    print(('PASS' if cond else 'FAIL') + ' ' + msg + ('  ' + detail if detail else ''))
    if not cond:
        fails.append(msg)


# ── 1. 退出码口径 ───────────────────────────────────────────────
print('=== 1. 退出码 ===')
check((E.OK, E.FAILURE, E.USAGE, E.INTERRUPTED) == (0, 1, 2, 130),
      '常量 0/1/2/130')
check(set(E.MEANING) == {0, 1, 2, 130}, 'MEANING 覆盖全部码')

# ── 2. 异常自带码 ───────────────────────────────────────────────
print('=== 2. 异常 → 退出码 ===')
check(E.WebtoolError('x').exit_code == 1, 'WebtoolError 默认 1')
check(E.UsageError('x').exit_code == 2, 'UsageError → 2')
check(E.NotFound('x').exit_code == 2, 'NotFound → 2')
check(E.WebtoolError('x', code=7).exit_code == 7, 'code= 可覆盖')

# ── 3. die() ────────────────────────────────────────────────────
print('=== 3. die ===')
try:
    E.die('boom', code=3)
    check(False, 'die 抛 SystemExit')
except SystemExit as e:
    check(e.code == 3, 'die 抛 SystemExit 且带码')

# ── 4. CLI 层退出码 ─────────────────────────────────────────────
print('=== 4. main 兜底 ===')
check(main(['nosuchcmd']) == 2, '未知子命令 → 2')
check(main(['search', 'x', '-f', 'bogus']) == 2, '非法输出格式 → 2')

print()
if fails:
    print('FAILED: %d 项 -> %s' % (len(fails), ', '.join(fails)))
    sys.exit(1)
print('ALL PASS')
