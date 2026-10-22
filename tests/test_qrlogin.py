#!/usr/bin/env python3
"""扫码登录的离线测试 (不联网)"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from webtool.core import qrimg
from webtool.engines import qrlogin

FAILED = []


def check(cond, msg):
    if cond:
        print('PASS ' + msg)
    else:
        print('FAIL ' + msg)
        FAILED.append(msg)


# --- 站点表 ---------------------------------------------------------------
check('xhs' in qrlogin.QR_SITES, 'xhs 在扫码站点表里')
check('boss' in qrlogin.QR_SITES, 'boss 在扫码站点表里')
for _s in ('xhs', 'boss'):
    _sp = qrlogin.QR_SITES[_s]
    check(bool(_sp.get('label')), f'{_s} 有中文名')
    check(bool(_sp.get('hint')), f'{_s} 有扫码提示')

# --- 二维码渲染 -----------------------------------------------------------
_p = os.path.join(tempfile.mkdtemp(), 'q.png')
qrimg.render('hello-world', _p)
check(os.path.exists(_p), 'qr_png 生成了文件')
with open(_p, 'rb') as _f:
    check(_f.read(8) == b'\x89PNG\r\n\x1a\n', '生成的是合法 PNG')
check(os.path.getsize(_p) > 100, 'PNG 不是空壳')

# --- 状态判定 (纯逻辑) ----------------------------------------------------
check(qrlogin.xhs_status_text(0) == '等待扫码', 'xhs 状态 0 = 等待扫码')
check('确认' in qrlogin.xhs_status_text(1), 'xhs 状态 1 = 已扫码待确认')
check('成功' in qrlogin.xhs_status_text(2), 'xhs 状态 2 = 登录成功')
check('过期' in qrlogin.xhs_status_text(3), 'xhs 状态 3 = 已过期')
check('未知' in qrlogin.xhs_status_text(9), 'xhs 未知状态有兜底文案')

check(qrlogin.boss_login_done({'login': True}) is True, 'BOSS login=true 算成功')
check(qrlogin.boss_login_done({'login': False}) is False, 'BOSS login=false 不算成功')
check(qrlogin.boss_login_done({'scaned': True}) is False,
      'BOSS 只回 scaned=true 不算成功 (实测会误判)')
check(qrlogin.boss_login_done(None) is False, 'BOSS 响应缺失时不算成功')

# --- 异常类型 -------------------------------------------------------------
try:
    raise qrlogin.QRTimeout('超时了', '重试')
except qrlogin.QRError as e:
    check('超时了' in str(e), 'QRTimeout 是 QRError 的子类, 消息可读')
    check(getattr(e, 'hint', '') == '重试', '异常带 hint')

print()
if FAILED:
    print('FAILED: %d 项' % len(FAILED))
    sys.exit(1)
print('ALL PASS')
