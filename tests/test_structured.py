# -*- coding: utf-8 -*-
"""core/structured 结构化抽取 (JSON-LD / OG / meta) — 纯离线

跑法: python3 tests/test_structured.py
"""
import sys

fails = []


def check(cond, msg, detail=''):
    print(('PASS' if cond else 'FAIL') + ' ' + msg)
    if not cond:
        fails.append(msg)
        if detail:
            print('   ', detail)


from webtool.core import structured as st

PRODUCT = '''<html><head><title>页面标题</title>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"测试商品",
 "offers":{"@type":"Offer","price":"99.00","priceCurrency":"CNY",
           "availability":"https://schema.org/InStock"},
 "aggregateRating":{"ratingValue":"4.6","reviewCount":"128"},
 "brand":{"name":"ACME"}}
</script>
<meta property="og:type" content="product">
<meta property="og:title" content="OG 标题">
</head><body>x</body></html>'''

GRAPH = '''<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
 {"@type":"BreadcrumbList","name":"面包屑"},
 {"@type":["NewsArticle","Article"],"headline":"新闻标题",
  "datePublished":"2026-10-01T08:00:00+08:00",
  "author":[{"@type":"Person","name":"张三"}],
  "image":{"@type":"ImageObject","url":"https://x/a.jpg"}}]}
</script></head><body>x</body></html>'''

BROKEN = '''<html><head><title>T</title>
<script type="application/ld+json">{不是合法 JSON</script>
</head><body>x</body></html>'''

r = st.parse(PRODUCT)
check(r['types'] == ['Product'], 'types 认得 Product')
check(r['fields'].get('name') == '测试商品', 'name 取出')
check(r['fields'].get('price') == '99.00', 'price 从 offers.price 取出')
check(r['fields'].get('currency') == 'CNY', 'currency 从 offers.priceCurrency 取出')
check('InStock' in (r['fields'].get('availability') or ''), 'availability 取出')
check(r['fields'].get('rating') == '4.6', 'rating 从 aggregateRating 取出')
check(r['fields'].get('reviews') == '128', 'reviews 从 reviewCount 取出')
check(r['fields'].get('brand') == 'ACME', 'brand 从 brand.name 取出')
check(r['og'].get('og:type') == 'product', 'og 取出')
check(r['meta'].get('title') == '页面标题', 'meta title 取出')

g = st.parse(GRAPH)
check('NewsArticle' in g['types'] and 'Article' in g['types'],
      '@type 数组拆开')
check('BreadcrumbList' in g['types'], '@graph 也摊平')
check(g['fields'].get('title') == '新闻标题', 'Article 的 headline 当 title')
check(g['fields'].get('author') == '张三', 'author 从列表里取 name')
check(g['fields'].get('image') == 'https://x/a.jpg', 'image 从 ImageObject.url 取')
check((g['fields'].get('published') or '').startswith('2026-10-01'),
      'published 从 datePublished 取')

b = st.parse(BROKEN)
check(b['types'] == [] and b['meta'].get('title') == 'T',
      '坏 JSON-LD 被跳过, 其它照抽')
check(st.parse('')['fields'] == {}, '空 HTML 不炸')
check(st.parse('<html><body>无头</body></html>')['fields'] == {},
      '完全没有结构化数据时 fields 为空')

p = st.pick(r, ['name', 'price', 'offers.price', 'nope', 'currency'])
check(p.get('name') == '测试商品', 'pick 取常用名')
check(p.get('offers.price') == '99.00', 'pick 支持路径')
check('nope' not in p, 'pick 缺字段就不出现 (不返回 None)')
check(p.get('currency') == 'CNY', 'pick 多字段')

# 只有 OG 的站点: fields 用 OG 兜底
og_only = st.parse('<html><head><title>T2</title>'
                   '<meta property="og:title" content="OGT">'
                   '<meta property="og:description" content="OGD">'
                   '</head></html>')
check(og_only['fields'].get('title') == 'OGT', 'OG 兜底 title')
check(og_only['fields'].get('description') == 'OGD', 'OG 兜底 description')

if fails:
    print('\nFAILED: %d 项' % len(fails))
    sys.exit(1)
print('\nALL PASS')
