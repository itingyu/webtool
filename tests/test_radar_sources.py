# -*- coding: utf-8 -*-
"""RSSHub 路由 → feed 源 的全量物化

4005 条路由里 1235 条免填参、其余带参数。物化规则必须是确定的:
键名固定、模板带站点前缀、缺必填参数要能生成可照抄的提示。

跑法: python3 tests/test_radar_sources.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'src'))

from webtool import radar                                       # noqa: E402
from webtool.feeds import radar_sources as rs                  # noqa: E402

fails = []


def check(ok, name, detail=''):
    print('%s %s' % ('ok  ' if ok else 'FAIL', name))
    if not ok:
        fails.append(name)
        if detail:
            print('     ' + str(detail)[:300])


ROUTES = {
    'demo': {
        'name': '示例站', 'url': 'demo.com',
        'routes': {
            '/demo/list': {'path': '/demo/list', 'name': '列表',
                           'heat': 9, 'example': '/demo/list'},
            '/demo/tag/:tag': {'path': '/demo/tag/:tag', 'name': '标签',
                               'heat': 5, 'parameters': {'tag': '标签名'},
                               'example': '/demo/tag/tech'},
            '/demo/multi': {'path': ['/multi', '/multi2'], 'name': '多路径',
                            'heat': 1},
        },
    },
}
src = rs.build(ROUTES)

check('demo' in src, '单站最热路由占域名短名', sorted(src))
check('demo_tag' in src, '其余路由用 域名_路由 命名', sorted(src))
check(len([k for k in src if k.startswith('demo_multi')]) == 2,
      '多路径展开成多条', sorted(src))
check(src['demo']['template'] == '/demo/list', '模板带站点前缀',
      src['demo']['template'])
check(src['demo']['required'] == [], '免填参路由不高亮参数', src['demo'])

url = rs.render(src['demo'], instance='https://i.test')
check(url == 'https://i.test/demo/list', '无参路由直接拼实例', url)

url = rs.render(src['demo_tag'], {'tag': 'go'}, instance='https://i.test')
check(url == 'https://i.test/demo/tag/go', '填参渲染', url)

url = rs.render(src['demo_tag'], example=True, instance='https://i.test')
check(url == 'https://i.test/demo/tag/tech', 'example 免填参', url)

try:
    rs.render(src['demo_tag'], instance='https://i.test')
    check(False, '缺必填参数抛 MissingParams', '没有抛异常')
except radar.MissingParams as e:
    check(bool(e.missing) and e.missing[0][0] == 'tag',
          '缺必填参数抛 MissingParams', str(e))

text = rs.hint('demo_tag', src['demo_tag'])
check('-p tag=' in text, '提示含填参写法', text)
check('-e' in text and '/demo/tag/tech' in text, '提示含官方示例', text)

GROUPS = {
    'fin1': {'categories': ['finance'], 'params': {}},
    'fin2': {'categories': ['finance'], 'params': {'id': ''}},
    'fin3': {'categories': ['finance', 'other'], 'params': {}},
    'game1': {'categories': ['game'], 'params': {}},
    'misc': {'categories': [], 'params': {}},
}
gs = rs.group_by_category(GROUPS)
check([g['cat'] for g in gs][0] == 'finance', '按分类分段, 条数多的在前',
      [(g['cat'], len(g['free']) + len(g['param'])) for g in gs])
fin = gs[0]
check(fin['label'] == '财经', '分类有中文段名', fin['label'])
check(set(fin['free']) == {'fin1', 'fin3'} and fin['param'] == ['fin2'],
      '段内再分免填参/带参', fin)
check([g['cat'] for g in rs.group_by_category(GROUPS, cat='game')] == ['game'],
      'cat 过滤只留一类')
check('fin1' not in [k for g in rs.group_by_category(GROUPS, exclude={'fin1'})
                     for k in g['free']], 'exclude 去掉被用户源覆盖的键')

print()
if fails:
    print(f'{len(fails)} FAILED: {", ".join(fails)}')
    sys.exit(1)
print('all passed')
