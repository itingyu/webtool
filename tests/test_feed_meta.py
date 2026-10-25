#!/usr/bin/env python3
"""feed 解析与输出: 东八区时间 / 作者分类 / --meta 渲染, 全离线"""
import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from webtool.feeds.parse import parse_feed
from webtool.filters.datefilter import _parse_structured
from webtool.render.hotrender import render_hot

FAIL = []


def check(cond, label):
    print(('PASS ' if cond else 'FAIL ') + label)
    if not cond:
        FAIL.append(label)


RSS = '''<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>
<item><title>A</title><link>https://x/a</link>
<pubDate>Sun, 25 Oct 2026 14:15:59 GMT</pubDate>
<author>alice</author><category>tech</category><category>ai</category>
<guid>g1</guid><description><![CDATA[<p>hello</p>]]></description></item>
</channel></rss>'''

RSS1 = '''<?xml version="1.0"?><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel><title>T</title></channel><item><title>A</title><link>https://x/a</link>
<dc:date>2026-10-25T10:00:00Z</dc:date><dc:creator>bob</dc:creator>
<dc:subject>news</dc:subject></item></rdf:RDF>'''

ATOM = '''<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<title>T</title><entry><title>A</title><link rel="alternate" href="https://x/a"/>
<published>2026-10-25T10:00:00Z</published><updated>2026-10-26T01:00:00Z</updated>
<author><name>carol</name></author><category term="news"/>
<summary type="html"><p>hi</p></summary></entry></feed>'''

print('=== 1. RSS 2.0: 时间转东八区, 保留作者/分类/guid ===')
r = parse_feed(RSS, 'src')[0]
check(r['date'] == '2026-10-25T22:15:59+08:00', f"date={r['date']}")
check(r['date_raw'] == 'Sun, 25 Oct 2026 14:15:59 GMT', '保留 date_raw')
check(r['author'] == 'alice', f"author={r.get('author')}")
check(r['categories'] == ['tech', 'ai'], f"categories={r.get('categories')}")
check(r['guid'] == 'g1', f"guid={r.get('guid')}")
check(r['snippet'] == 'hello', 'HTML 摘要清洗')

print()
print('=== 2. RSS 1.0: dc:date 不报错, 命名空间正常 ===')
r = parse_feed(RSS1, 'src')[0]
check(r['title'] == 'A', f"title={r.get('title')}")
check(r['date'] == '2026-10-25T18:00:00+08:00', f"date={r['date']}")
check(r['author'] == 'bob', f"author={r.get('author')}")
check(r['categories'] == ['news'], f"categories={r.get('categories')}")

print()
print('=== 3. Atom: published/updated 都保留 ===')
r = parse_feed(ATOM, 'src')[0]
check(r['date'] == '2026-10-25T18:00:00+08:00', f"date={r['date']}")
check(r['updated'] == '2026-10-26T09:00:00+08:00', f"updated={r['updated']}")
check(r['author'] == 'carol', f"author={r.get('author')}")

print()
print('=== 4. datefilter 认 RFC822 并转东八区 ===')
check(str(_parse_structured('Sun, 25 Oct 2026 20:00:00 GMT')) == '2026-10-26',
      'RFC822 GMT -> 东八区日期')

print()
print('=== 5. 文本/Markdown: 默认带时间, --meta 才带作者 ===')
OUT = {'cmd': 'feed', 'sources': ['src'], 'total': 1, 'took_ms': 1,
       'sources_data': {'src': [{'rank': 1, 'title': 'A', 'url': 'https://x/a',
                                 'date': '2026-10-25T22:15:59+08:00',
                                 'author': 'alice', 'categories': ['tech']}]},
       'errors': {}, 'failed': [], 'filtered_out': 0}
for fmt in ('text', 'markdown'):
    buf, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
        render_hot(OUT, fmt, False)
    plain = buf.getvalue()
    check('2026-10-25 22:15' in plain, f'{fmt} 默认有发布时间')
    check('alice' not in plain, f'{fmt} 默认不带作者')
    check(not err.getvalue().strip(), f'{fmt} 正常路径不往 stderr 写状态')
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        render_hot(OUT, fmt, True)
    full = buf.getvalue()
    check('作者:alice' in full and '分类:tech' in full, f'{fmt} --meta 带作者/分类')

print()
if FAIL:
    print(f'FAILED: {len(FAIL)}')
    sys.exit(1)
print('ALL PASS')
