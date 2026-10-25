"""SegmentFault 解析的离线测试: 只用 fixture, 不联网

服务端渲染的站点源没有契约可依, 唯一的护栏就是这份样本 ——
线上改版时解析先在这里挂掉, 而不是静默返回空列表。
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from webtool.engines.sites import _parse_segmentfault  # noqa: E402

_fails = []

def check(cond, name):
    if cond:
        print('PASS ' + name)
    else:
        print('FAIL ' + name)
        _fails.append(name)

with open(os.path.join(HERE, 'fixtures', 'segmentfault_search.html'),
          encoding='utf-8') as f:
    HTML = f.read()

rows = _parse_segmentfault(HTML, 10)
check(len(rows) == 3, '解析出 3 条')
check(all(r['title'] for r in rows), '每条都有标题')
check(all(r['url'].startswith('https://segmentfault.com/') for r in rows),
      'URL 已绝对化')
check(all(re.search(r'/(a|q)/\d+$', r['url']) for r in rows),
      'URL 指向文章或问答页')
check(len({r['url'] for r in rows}) == 3, 'URL 无重复')
check(all(r['snippet'] for r in rows), '每条都有摘要')
check(not any('<' in r['title'] for r in rows), '标题已去标签')
check(len(_parse_segmentfault(HTML, 2)) == 2, 'limit 生效')
check(_parse_segmentfault('', 10) == [], '空页返回空列表')
check(_parse_segmentfault('<html>改版了</html>', 10) == [],
      '改版页面返回空列表 (不抛异常)')

print('')
if _fails:
    print('FAILED: %d 项' % len(_fails))
    sys.exit(1)
print('ALL PASS')
