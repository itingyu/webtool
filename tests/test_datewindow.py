# -*- coding: utf-8 -*-
"""--since/--until 时间窗口: 相对写法 + 绝对日期 + 引擎参数

跑法: python3 tests/test_datewindow.py
"""
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'src'))

from webtool.core import datewindow as dw                    # noqa: E402
from webtool.engines import baidu, bing, google, sogou       # noqa: E402

fails = []
NOW = dt.datetime(2026, 10, 23, 12, 0)


def check(ok, name, detail=''):
    print('%s %s' % ('ok  ' if ok else 'FAIL', name))
    if not ok:
        fails.append(name)
        if detail:
            print('     ' + str(detail)[:300])


D = dt.date

check(dw.parse_date('7d', NOW) == D(2026, 10, 16), '相对 7d')
check(dw.parse_date('近7天', NOW) == D(2026, 10, 16), '相对 近7天')
check(dw.parse_date('3周', NOW) == D(2026, 10, 2), '相对 3周')
check(dw.parse_date('2个月', NOW) == D(2026, 8, 24), '相对 2个月')
check(dw.parse_date('1y', NOW) == D(2025, 10, 23), '相对 1y')
check(dw.parse_date('24h', NOW) == D(2026, 10, 22), '相对 24h')
check(dw.parse_date('昨天', NOW) == D(2026, 10, 22), '关键词 昨天')
check(dw.parse_date('今天', NOW) == D(2026, 10, 23), '关键词 今天')
check(dw.parse_date('上周', NOW) == D(2026, 10, 12), '关键词 上周')
check(dw.parse_date('上月', NOW) == D(2026, 9, 1), '关键词 上月')
check(dw.parse_date('2026-10-01', NOW) == D(2026, 10, 1), '绝对 短横线')
check(dw.parse_date('2026/9/5', NOW) == D(2026, 9, 5), '绝对 斜杠')
check(dw.parse_date('20261001', NOW) == D(2026, 10, 1), '绝对 紧凑')
check(dw.parse_window('7d', None, NOW) == (D(2026, 10, 16), D(2026, 10, 23)),
      '只给 since 补今天')
check(dw.parse_window(None, '2026-10-01', NOW) == (None, D(2026, 10, 1)),
      '只给 until 起点为空')

check(dw.parse_window('', '', NOW) == (None, None), '空串当作没给')

for bad in ('xyz', '2026-13-40'):
    try:
        dw.parse_window(bad, None, NOW)
        check(False, f'非法输入要报错: {bad!r}', '没抛 ValueError')
    except ValueError:
        check(True, f'非法输入要报错: {bad!r}')

try:
    dw.parse_window('2026-10-10', '2026-10-01', NOW)
    check(False, '起点晚于终点要报错')
except ValueError:
    check(True, '起点晚于终点要报错')

G = google._time_qs(D(2026, 10, 1), D(2026, 10, 23))
check('cdr' in G and '2026' in G, 'google tbs 自定义区间', G)
check(google._time_qs(None, None) == '', 'google 无窗口不带参数')

B = bing._time_qs(D(2026, 10, 1), D(2026, 10, 23))
check('ez5' in B and '2026' in B, 'bing filters 自定义区间', B)

BD = baidu._gpc_qs(D(2026, 10, 1), D(2026, 10, 23))
check('stf' in BD and 'stftype' in BD, 'baidu gpc 时间戳区间', BD)

check(sogou._tsn_qs(D(2026, 10, 16), D(2026, 10, 23)) == '&tsn=2',
      'sogou 一周 → tsn=2')
check(sogou._tsn_qs(D(2026, 9, 23), D(2026, 10, 23)) == '&tsn=3',
      'sogou 一月 → tsn=3')
S = sogou._tsn_qs(D(2026, 10, 1), D(2026, 10, 11))
check('tsn=5' in S and 'ft=' in S, 'sogou 自定义区间 → tsn=5&ft', S)

# 引擎签名都要能吃 since/until (TypeError 就是没接住)
import inspect                                                    # noqa: E402
for mod in (google, bing, baidu, sogou):
    sig = inspect.signature(mod.search)
    check('since' in sig.parameters and 'until' in sig.parameters,
          f'{mod.__name__.split(".")[-1]} search 接受 since/until')

# 默认窗口: 近 15 天
dw = __import__('webtool.core.datewindow', fromlist=['default_window'])
check(dw.default_window(D(2026, 10, 23)) == (D(2026, 10, 8), D(2026, 10, 23)),
      'default_window = 近 15 天')

# datefilter 优先用已解析窗口 (win_start/win_end), 不再依赖 since/until 字符串
from types import SimpleNamespace                                     # noqa: E402
from webtool.filters.datefilter import filter_by_date                 # noqa: E402
res = [{'title': '2019年1月1日 旧文', 'url': 'https://a.example/1', 'snippet': ''},
       {'title': '2026年10月20日 新文', 'url': 'https://b.example/2', 'snippet': ''}]
kept = filter_by_date(res, {'args': SimpleNamespace(win_start='2026-10-08',
                                                   win_end='2026-10-23',
                                                   date_strict=False), 'cfg': {}})
check(len(kept) == 1 and '新文' in kept[0]['title'], 'datefilter 用显式窗口', kept)

# RSS 通道已移除 (bing/google), 防止回潮
from webtool.engines import bing as _b, google as _g               # noqa: E402
check(not hasattr(_b, '_rss'), 'bing 无 RSS 通道')
check(not hasattr(_g, '_news'), 'google 无 news RSS 通道')

print()
if fails:
    print(f'{len(fails)} FAILED:', ', '.join(fails))
    sys.exit(1)
print('all passed')
