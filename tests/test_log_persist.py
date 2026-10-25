# -*- coding: utf-8 -*-
"""默认日志落盘: 不带 -d / --log-file 也要在 ~/.webtool/logs 留全量 DEBUG"""
import logging
import logging.handlers
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

fails = []

def check(cond, msg):
    print(('PASS' if cond else 'FAIL') + ' ' + msg)
    if not cond:
        fails.append(msg)

td = tempfile.mkdtemp(prefix='wt-log-')
os.environ['WEBTOOL_DIR'] = td
os.environ.pop('WEBTOOL_LOG_FILE', None)

from webtool.core import logging as L  # noqa: E402

root = logging.getLogger('webtool')
for h in list(root.handlers):
    root.removeHandler(h)
L._h = None
L._fh = None
L._fh_path = None
L.setup(0)
logging.getLogger('webtool.test').debug('persist-me')

path = os.path.join(td, 'logs', 'webtool.log')
check(os.path.exists(path), '默认生成 logs/webtool.log')
body = open(path, encoding='utf-8').read()
check('persist-me' in body, '没开 -d 也把 DEBUG 写进文件')
check(L._h.level == logging.WARNING, 'stderr 仍静默')
check(isinstance(L._fh, logging.handlers.TimedRotatingFileHandler),
      '按时间滚动而不是按大小')
check(L._fh.when == 'MIDNIGHT' and L._fh.backupCount == 7,
      '每天零点滚动, 保留 7 天')

os.environ['WEBTOOL_LOG_FILE'] = 'off'
L.setup(0)
for h in list(root.handlers):
    root.removeHandler(h)
check(L._fh is None, 'WEBTOOL_LOG_FILE=off 撤掉文件 handler')

if fails:
    print('FAILED: %d' % len(fails))
    sys.exit(1)
print('ALL PASS')
