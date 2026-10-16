# -*- coding: utf-8 -*-
"""core/logging (--debug 基础设施) 的边界单测 (纯本地, 不联网)

覆盖: 级别映射 (-d → DEBUG, 默认 WARNING)、stderr 路由、NO_COLOR/非 tty 去色、
幂等 setup、WEBTOOL_DEBUG 环境变量。

跑法: python3 tests/test_debug_log.py
"""
import io
import logging
import os
import re as _re3
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

fails = []

def check(cond, msg):
    print(('PASS' if cond else 'FAIL') + ' ' + msg)
    if not cond:
        fails.append(msg)

from webtool.core import logging as L

# 隔离: 换根 logger 名下 handler 之前清掉既有 handler, 避免吃到本仓其它测试的装配
root = logging.getLogger('webtool')
for h in list(root.handlers):
    root.removeHandler(h)
L._h = None

buf = io.StringIO()

class _FakeErr(io.StringIO):
    def isatty(self):
        return False


# 非 tty (StringIO 无 isatty → 按非 tty) → 去色
old_err = sys.stderr
sys.stderr = _FakeErr()
try:
    L.setup(1)
finally:
    sys.stderr = old_err

rec = logging.LogRecord('webtool.test', logging.DEBUG, 'x.py', 1,
                        'hello %s', ('world',), None)
msg = L._h.format(rec)
check('\033[' not in msg, '非 tty 去色')
check('D ' in msg and msg.endswith('hello world'), '格式含级别缩写与消息')
# 时间/线程/文件行号是排查三要素, 缺任一项这行日志都不及格 (见 test_smoke §17)
check(_re3.match(r'\d\d:\d\d:\d\d\.\d{3} ', msg) is not None, '格式含时间(带毫秒)')
check('[MainThread] ' in msg, '格式含线程名')
check(' x.py:1 ' in msg, '格式含文件:行号')

check(root.level == logging.DEBUG and L._h.level == logging.DEBUG, '-d → DEBUG')

# 幂等: 再调 setup 不加 handler
L.setup(1)
check(len([h for h in root.handlers if h is L._h]) == 1 and len(root.handlers) == 1,
      'setup 幂等, handler 只装一次')

# NO_COLOR: 即便 tty 也去色
class _Tty(io.StringIO):
    def isatty(self):
        return True
L._h = None
for h in list(root.handlers):
    root.removeHandler(h)
old_err, old_nocolor = sys.stderr, os.environ.get('NO_COLOR')
os.environ['NO_COLOR'] = '1'
sys.stderr = _Tty()
try:
    L.setup(1)
    rec = logging.LogRecord('webtool.test', logging.ERROR, 'x.py', 1, 'boom', None, None)
    check('\033[' not in L._h.format(rec), 'NO_COLOR 下 tty 也去色')
finally:
    sys.stderr = old_err
    if old_nocolor is None:
        os.environ.pop('NO_COLOR', None)
    else:
        os.environ['NO_COLOR'] = old_nocolor

# tty 无 NO_COLOR → ERROR 红 (重建 handler: 上一段的 handler 是 NO_COLOR 下造的;
# 本沙箱环境自带 NO_COLOR=1, 必须显式摘掉再验, 结束后恢复)
L._h = None
for h in list(root.handlers):
    root.removeHandler(h)
_saved_nc = os.environ.pop('NO_COLOR', None)
sys.stderr = _Tty()
try:
    L.setup(1)
    rec = logging.LogRecord('webtool.test', logging.ERROR, 'x.py', 1, 'boom', None, None)
    check('\033[31m' in L._h.format(rec), 'tty 下 ERROR 带色')
    check(L._h.stream is sys.stderr or isinstance(L._h.stream, _Tty),
          '日志进 stderr handler')
finally:
    if _saved_nc is not None:
        os.environ['NO_COLOR'] = _saved_nc
    sys.stderr = old_err

# WEBTOOL_DEBUG 环境变量
os.environ['WEBTOOL_DEBUG'] = '1'
check(L.env_debug() == 1, 'WEBTOOL_DEBUG=1 等效 -d')
os.environ['WEBTOOL_DEBUG'] = ''
check(L.env_debug() == 0, '空值不算开')
os.environ.pop('WEBTOOL_DEBUG', None)

# 日志确实路由到 stderr 而非 stdout: propagate 必须关
check(root.propagate is False, 'propagate 关闭 (不污染上游 root)')

# --log-file / WEBTOOL_LOG_FILE: 文件拿全量 DEBUG, stderr 不冒
import tempfile  # noqa: E402
_tmpf = os.path.join(tempfile.mkdtemp(), 'wt.log')
for h in list(root.handlers):
    root.removeHandler(h)
L.setup(0, log_file=_tmpf)
logging.getLogger('webtool.dao.cache').debug('trace-me')
check(os.path.exists(_tmpf) and 'trace-me' in open(_tmpf, encoding='utf-8').read(),
      'log-file 捕获 DEBUG (即使没开 -d)')
check(logging.getLogger('webtool').level == logging.DEBUG,
      'log-file 时 logger 本体放到 DEBUG')
check(L._h.level == logging.WARNING, 'stderr handler 仍按 debug 卡在 WARNING')

for h in list(root.handlers):
    root.removeHandler(h)
L.setup(2)
check(logging.getLogger('urllib3').level == logging.DEBUG,
      '-dd 放开三方库 DEBUG')
for h in list(root.handlers):
    root.removeHandler(h)

print()
if fails:
    print('FAILED: %d 项 -> %s' % (len(fails), ', '.join(fails)))
    sys.exit(1)
print('ALL PASS')
