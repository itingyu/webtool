# -*- coding: utf-8 -*-
"""feed sources find: 键名/站名/域名/描述 模糊搜

默认清单不铺 4000+ 派生源, 找源全靠这条; 排序必须让精确键名排第一,
否则搜 "36kr" 先出来一堆含 36kr 的长尾。

跑法: python3 tests/test_feed_find.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'src'))

from webtool.feeds.find import search                          # noqa: E402

fails = []


def check(ok, name, detail=''):
    print('%s %s' % ('ok  ' if ok else 'FAIL', name))
    if not ok:
        fails.append(name)
        if detail:
            print('     ' + str(detail)[:300])


USER = {
    '36氪官网': {'url': 'https://www.36kr.com/feed', 'desc': '新闻资讯 · 官方 feed'},
    'x': {'url': 'https://example.org/rss', 'desc': '示例'},
}
DERIVED = {
    '36kr': {'desc': '36kr · 资讯热榜', 'site': '36kr', 'group': '36kr',
             'domain': '36kr.com', 'route_name': '资讯热榜', 'doc': '24 小时热榜',
             'categories': ['new-media'], 'params': {'category': ''}, 'heat': 99,
             'template': '/36kr/hot-list/:category?'},
    '36kr_2': {'desc': '36kr · 快讯', 'site': '36kr', 'group': '36kr',
               'domain': '36kr.com', 'route_name': '快讯', 'doc': '',
               'categories': ['new-media'], 'params': {}, 'heat': 10,
               'template': '/36kr/news'},
    'zhihu': {'desc': '知乎 · 热榜', 'site': '知乎', 'group': 'zhihu',
              'domain': 'zhihu.com', 'route_name': '热榜', 'doc': '',
              'categories': ['new-media'], 'params': {'category': ''},
              'heat': 80, 'template': '/zhihu/hot/:category?'},
}


rows = search(USER, DERIVED, '36kr')
check(bool(rows) and rows[0]['key'] == '36kr', '精确键名排第一', [r['key'] for r in rows])
check([r['key'] for r in rows].count('36kr_2') == 1, '同域路由也能被键名命中')

rows = search(USER, DERIVED, '知乎')
check([r['key'] for r in rows] == ['zhihu'], '按中文站名搜', rows)

rows = search(USER, DERIVED, 'zhihu.com')
check([r['key'] for r in rows] == ['zhihu'], '按域名搜', rows)

rows = search(USER, DERIVED, '热榜')
check({r['key'] for r in rows} == {'36kr', 'zhihu'}, '按描述/路由名搜', rows)

rows = search(USER, DERIVED, '36kr.com')
check('36氪官网' in [r['key'] for r in rows], '自定义源按域名搜', rows)

rows = search(USER, DERIVED, '36氪')
check('36氪官网' in [r['key'] for r in rows], '自定义源按描述搜', rows)

rows = search(USER, DERIVED, '36kr', cat='new-media')
check(len(rows) >= 2, '分类过滤保留命中', rows)
rows = search(USER, DERIVED, '36kr', cat='finance')
check(rows == [], '分类过滤能排除', rows)

rows = search(USER, DERIVED, '36kr', limit=1)
check(len(rows) == 1, 'limit 生效', rows)

check(search(USER, DERIVED, 'zzz-not-exist') == [], '无命中返回空')
check(search(USER, DERIVED, '') == [], '空词返回空')

print()
if fails:
    print(f'{len(fails)} FAILED: {", ".join(fails)}')
    sys.exit(1)
print('all passed')
