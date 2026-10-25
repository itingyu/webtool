#!/usr/bin/env python3
"""时间过滤器本地验证: 日期识别 / 相对时间 / 边界, 全离线, 不碰外网"""
import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from webtool.filters import datefilter as D

FAIL = []


def check(cond, label):
    print(('PASS ' if cond else 'FAIL ') + label)
    if not cond:
        FAIL.append(label)


TODAY = datetime.date(2026, 10, 22)


def _args(since=None, until=None, strict=False):
    class A:
        pass
    a = A()
    a.since, a.until, a.date_strict = since, until, strict
    return {'args': a}


print('=== 1. 绝对日期识别 (中/英/斜杠) ===')
for txt, exp in (('2026-10-15', '2026-10-15'),
                  ('2026/10/15', '2026-10-15'),
                  ('2026年10月15日', '2026-10-15'),
                  ('2026.10.15', '2026-10-15'),
                  ('Oct 15, 2026', '2026-10-15'),
                  ('15 Oct 2026', '2026-10-15'),
                  ('2026年10月15日 12:30', '2026-10-15')):
    d, _low = D._parse_text(txt, TODAY)
    check(str(d) == exp, f'{txt!r} -> {exp} (得到 {d})')

print()
print('=== 2. 相对时间识别 ===')
for txt, exp in (('3天前', '2026-10-19'),
                  ('昨天', '2026-10-21'),
                  ('今天', '2026-10-22'),
                  ('刚刚', '2026-10-22'),
                  ('5分钟前', '2026-10-22'),
                  ('2小时前', '2026-10-22'),
                  ('2周前', '2026-10-08'),
                  ('1个月前', '2026-09-22')):
    d, _low = D._parse_text(txt, TODAY)
    check(str(d) == exp, f'{txt!r} -> {exp} (得到 {d})')

print()
print('=== 3. 无年份的日期按今年算 ===')
d, low = D._parse_text('10月15日', TODAY)
check(str(d) == '2026-10-15', f'10月15日 -> 2026-10-15 (得到 {d})')
check(low is True, '无年份标记为低置信')

print()
print('=== 4. 认不出日期的文本 ===')
d, _low = D._parse_text('完全没有日期的一段话', TODAY)
check(d is None, '无日期返回 None')

print()
print('=== 5. --since 解析 ===')
for spec, exp in (('2026-10-01', '2026-10-01'), ('7d', '2026-10-15'),
                   ('2w', '2026-10-08'), ('3m', '2026-07-22'),
                   ('1y', '2025-10-22'), ('今天', '2026-10-22'),
                   ('昨天', '2026-10-21')):
    d = D.parse_since(spec, TODAY)
    check(str(d) == exp, f'{spec!r} -> {exp} (得到 {d})')

print()
print('=== 6. --until 只认绝对日期 (方向跟 --since 相反) ===')
check(str(D.parse_until('2026-10-20', TODAY)) == '2026-10-20', '绝对日期能解')
check(D.parse_until('7d', TODAY) is None, '相对写法不认 (方向会反, 不猜)')
check(D.parse_until('', TODAY) is None, '空值返回 None')
check(D.parse_until(None, TODAY) is None, 'None 返回 None')

print()
print('=== 7. 月底平移不溢出 ===')
check(str(D._shift_months(datetime.date(2026, 3, 31), -1)) == '2026-02-28',
      '3月31退一个月 = 2月28 (平年)')
check(str(D._shift_months(datetime.date(2024, 3, 31), -1)) == '2024-02-29',
      '3月31退一个月 = 2月29 (闰年)')

print()
print('=== 8. 过滤行为 ===')
items = [
    {'title': '无日期条目', 'url': 'a'},
    {'title': '2020年1月1日 旧闻', 'url': 'b'},
    {'title': '2026年10月20日 新闻', 'url': 'c'},
    {'title': '3天前的新闻', 'url': 'd'},
    {'title': '昨天更新', 'url': 'e'},
    {'title': '2026年10月25日 未来', 'url': 'f'},
]


def titles(res):
    return [r['title'] for r in res]


kept = D.filter_by_date(items, _args(since='2026-10-01'))
check('2020年1月1日 旧闻' not in titles(kept), 'since 剔掉窗口外的旧闻')
check('2026年10月20日 新闻' in titles(kept), 'since 保留窗口内')
check('无日期条目' in titles(kept), '默认保留认不出日期的')

kept = D.filter_by_date(items, _args(since='2026-10-01', strict=True))
check('无日期条目' not in titles(kept), 'strict 剔掉认不出日期的')

kept = D.filter_by_date(items, _args(until='2026-10-20'))
check('2026年10月25日 未来' not in titles(kept), 'until 剔掉之后的')
check('2020年1月1日 旧闻' in titles(kept), 'until 保留之前的')

kept = D.filter_by_date(items, _args(since='7d'))
check('2020年1月1日 旧闻' not in titles(kept), 'since=7d 剔掉一周前的')
check('3天前的新闻' in titles(kept), 'since=7d 保留三天前的')

print()
print('=== 9. 认不出日期时不乱滤 (until 认不出就当没给) ===')
kept = D.filter_by_date(items, _args(until='乱写的'))
check(len(kept) == len(items), 'until 认不出时全放行, 不清空结果')

print()
print('=== 10. 结构化日期字段优先 ===')
it = [{'title': '标题里没日期', 'publish_date': '2026-10-10', 'url': 'x'}]
kept = D.filter_by_date(it, _args(since='2026-10-15'))
check(len(kept) == 0, 'publish_date 字段被识别并据此过滤')

print()
if FAIL:
    print(f'{len(FAIL)} FAIL')
    for f in FAIL:
        print('  -', f)
    sys.exit(1)
print('ALL PASS')
