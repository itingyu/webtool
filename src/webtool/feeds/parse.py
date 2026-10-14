"""RSS 2.0 / Atom 解析: 纯标准库, 不出网

XML 脏数据容忍两轮: 去掉 <?xml 声明前的杂质, 还失败就剥掉 <script>/<style>
再试; 两轮都挂才报错。
"""

import re
import xml.etree.ElementTree as ET

from webtool.core import text

_clean = text.clean_markup


# ============================================================ 解析 (纯标准库)

_NS = {
    'atom': 'http://www.w3.org/2005/Atom',
    'content': 'http://purl.org/rss/1.0/modules/content/',
}


def _strip_cdata(s):
    return re.sub(r'^<!\[CDATA\[|\]\]>$', '', (s or '').strip())


def _text_of(el, *paths):
    """按优先级取子元素 text (含 CDATA 清洗)"""
    for p in paths:
        x = el.find(p, _NS)
        if x is not None and (x.text or '').strip():
            return _strip_cdata(x.text)
    return ''


def parse_feed(txt, source_name=''):
    """RSS 2.0 / Atom 统一解析 → [{rank,title,url,snippet,date}]"""
    # 清理可能导致解析失败的垃圾 (xml 声明前杂质)
    i = txt.find('<?xml')
    if i > 0:
        txt = txt[i:]
    items = []
    try:
        root = ET.fromstring(txt.encode('utf-8'))
    except ET.ParseError:
        # 容错: 去 <script>/<style> 再试
        txt2 = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', txt, flags=re.S | re.I)
        try:
            root = ET.fromstring(txt2.encode('utf-8'))
        except ET.ParseError:
            raise RuntimeError('feed 解析失败: 非 RSS/Atom XML')
    # Atom
    if root.tag.endswith('feed'):
        for e in root.findall('atom:entry', _NS):
            title = _text_of(e, 'atom:title', 'title')
            link = ''
            for l in e.findall('atom:link', _NS):
                if not l.get('rel') or l.get('rel') == 'alternate':
                    link = l.get('href') or ''
                    break
            if not link:
                link = _text_of(e, 'atom:link', 'link')
            snippet = _clean(_text_of(e, 'atom:summary', 'atom:content', 'content:encoded', 'summary'))[:160]
            date = _text_of(e, 'atom:published', 'atom:updated', 'published', 'updated')
            if title:
                items.append({'title': title, 'url': link, 'snippet': snippet, 'date': date})
    # RSS 2.0 / 0.9x
    else:
        for ch in root.iter():
            if ch.tag.rsplit('}', 1)[-1] == 'item':
                title = _text_of(ch, 'title')
                link = _text_of(ch, 'link', 'atom:link', 'guid')
                snippet = _clean(_text_of(ch, 'description', 'content:encoded', 'content'))[:160]
                date = _text_of(ch, 'pubDate', 'atom:published', 'dc:date')
                if title:
                    items.append({'title': title, 'url': link, 'snippet': snippet, 'date': date})
    for i, x in enumerate(items):
        x['rank'] = i + 1
        if source_name:
            x['source'] = source_name
    return items
