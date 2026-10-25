# -*- coding: utf-8 -*-
"""geo 数据在线更新 (proxy geo update): 下载 → 格式校验 → 原子替换 → 写配置

端到端跑真实下载链路: 用 make_geodata_fixtures 造的小库起一个本地 HTTP 服务
当上游, WEBTOOL_DIR 隔离用户目录。中途把源换成"不是 geo 库"的文件, 验证
**坏数据不覆盖旧库** —— 这是这个功能最容易出事的地方 (上游抽风回个 HTML 错误页)。

跑法: python3 tests/test_geo_update.py
"""
import functools
import http.server
import os
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'src'))
sys.path.insert(0, HERE)

TMP = tempfile.mkdtemp(prefix='wt-geoupd-')
os.environ['WEBTOOL_DIR'] = TMP
os.environ['no_proxy'] = '*'
os.environ['NO_PROXY'] = ''

from make_geodata_fixtures import make_geoip_dat, make_geosite_dat  # noqa: E402

from webtool.net.proxy import geo_update as gu                       # noqa: E402

SRC = os.path.join(TMP, 'src')
os.makedirs(SRC, exist_ok=True)
with open(os.path.join(SRC, 'geosite.dat'), 'wb') as f:
    f.write(make_geosite_dat())
with open(os.path.join(SRC, 'geoip.dat'), 'wb') as f:
    f.write(make_geoip_dat())
with open(os.path.join(SRC, 'bad.dat'), 'wb') as f:
    f.write(b'<html>404 not found</html>')

Handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=SRC)
srv = http.server.HTTPServer(('127.0.0.1', 0), Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f'http://127.0.0.1:{srv.server_address[1]}'

fails = []


def check(cond, msg, detail=''):
    print(('PASS ' if cond else 'FAIL ') + msg + ('' if cond else '  ' + detail))
    if not cond:
        fails.append(msg)


# ── 1. 正常更新 ─────────────────────────────────────────────────────────
os.environ['WEBTOOL_GEO_SOURCE_GEOSITE'] = BASE + '/geosite.dat'
os.environ['WEBTOOL_GEO_SOURCE_GEOIP'] = BASE + '/geoip.dat'

r = gu.update('geosite')
check(r.get('ok') and os.path.isfile(r['path']), 'geosite 更新成功', str(r))
check(r['path'] == os.path.join(TMP, 'geo', 'geosite.dat'),
      'geosite 落到用户 geo 目录', r.get('path'))

import webtool.net.geodata as G                                     # noqa: E402
check(G.detect_format(r['path']) == 'geosite', '落盘内容是合法 geosite 库')
check(G.domain_in_category('www.baidu.com', 'cn', r['path']),
      '更新后的库可用于域名判定')

r2 = gu.update('geoip')
check(r2.get('ok') and G.detect_format(r2['path']) == 'geoip',
      'geoip 更新成功且格式正确', str(r2))
check(G.country_of_ip('223.5.5.5', r2['path']) == 'CN', '更新后的库可用于 IP 判定')

# ── 2. 坏数据不覆盖旧库 ─────────────────────────────────────────────────
with open(r['path'], 'rb') as f:
    before = f.read()
os.environ['WEBTOOL_GEO_SOURCE_GEOSITE'] = BASE + '/bad.dat'
r3 = gu.update('geosite')
with open(r['path'], 'rb') as f:
    after = f.read()
check(not r3.get('ok') and '不是 geosite' in (r3.get('error') or ''),
      '坏数据被拒 (认出非 geosite)', str(r3))
check(before == after, '坏数据不覆盖旧库 (字节不变)')
check(not os.path.exists(r['path'] + '.new'), '失败后不留临时文件')

# ── 3. 未知类型 ─────────────────────────────────────────────────────────
check(not gu.update('nope').get('ok'), '未知类型被拒')
check(set(gu.update_all()) == {'geosite', 'geoip'}, 'update_all 覆盖两个库')

srv.shutdown()
print()
if fails:
    print('FAILED: %s' % ', '.join(fails))
    sys.exit(1)
print('ALL PASS')
