# -*- coding: utf-8 -*-
"""搜索引擎结果页 (SERP) 必须挡在结果集之外

sogou 的"相关资讯"卡片会把自己的 /sogou?query= 页当成一条结果吐回来;
`ask` 抓它当资料, 答案就变成一堆标题和跳转链。这类 URL 是索引不是正文,
在 merge 入口统一剔除。

跑法: python3 tests/test_serp_filter.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'src'))

from webtool.core.urls import is_serp_url                      # noqa: E402
from webtool.pipeline.merge import merge                        # noqa: E402

fails = []

def check(ok, name, detail=''):
    print('%s %s' % ('ok  ' if ok else 'FAIL', name))
    if not ok:
        fails.append(name)
        if detail:
            print('     ' + str(detail)[:300])

# ── 认得出来: 各大引擎的结果页 ──────────────────────────────────────────
SERP = [
    'https://www.sogou.com/sogou?query=%E5%8C%97%E4%BA%AC',
    'https://m.sogou.com/web/searchList.jsp?keyword=x',
    'https://www.baidu.com/s?wd=x',
    'https://cn.bing.com/search?q=x',
    'https://www.google.com/search?q=x',
    'https://www.so.com/s?q=x',
    'https://duckduckgo.com/?q=x',
    'https://search.yahoo.com/search?p=x',
]
for u in SERP:
    check(is_serp_url(u), '识别为 SERP: %s' % u[:48])

# ── 不能误伤: 同域名的正常页面 / 跳转链 / 别家的站内搜索 ────────────────
OK = [
    'https://zhidao.baidu.com/question/474273385.html',
    'https://baike.baidu.com/item/Python',
    'https://news.baidu.com/',
    'https://www.sogou.com/link?url=abc',
    'https://github.com/search?q=python',
    'https://docs.python.org/3/whatsnew/3.13.html',
    'https://www.weather.com.cn/weather/101010100.shtml',
]
for u in OK:
    check(not is_serp_url(u), '不算 SERP: %s' % u[:48])

# ── merge 入口真的会剔除, 并记账 ────────────────────────────────────────
rows = [
    {'title': '今天北京天气怎么样_相关资讯', 'snippet': 'q', 'engine': 'sogou',
     'rank': 1, 'url': 'https://www.sogou.com/sogou?query=%E5%A4%A9%E6%B0%94'},
    {'title': '北京天气预报', 'snippet': 'q', 'engine': 'bing', 'rank': 1,
     'url': 'https://www.weather.com.cn/weather/101010100.shtml'},
]
stats = {}
out = merge([dict(r) for r in rows], '北京天气', use_semantic=False, stats=stats)
check(len(out) == 1 and 'weather.com.cn' in out[0]['url'],
      'merge 剔除 SERP, 保留正常结果', [r['url'] for r in out])
check(stats.get('serp_dropped') == 1, 'merge 记账 serp_dropped=1', stats)

# ── sogou 解析器自身也不产出 SERP / 相关搜索卡片 ────────────────────────
from webtool.engines import sogou as SG                          # noqa: E402

html = (
    '<h3 class="vr-title"><a href="https://www.sogou.com/sogou?query=x">'
    '今天北京天气怎么样_相关资讯</a></h3>'
    '<h3 class="vr-title"><a href="/link?url=abc">真结果</a></h3>'
    '<h3 class="vr-title"><a href="https://www.sogou.com/web?query=y">'
    '相关搜索</a></h3>'
)
parsed = SG._parse_pc(html, 10)
urls = [r['url'] for r in parsed]
check(len(urls) == 1 and '/link?url=abc' in urls[0],
      'sogou PC 解析: 只留跳转链, 丢掉自指页与相关搜索', urls)

print()
if fails:
    print('FAILED: %s' % ', '.join(fails))
    sys.exit(1)
print('ALL PASS')
