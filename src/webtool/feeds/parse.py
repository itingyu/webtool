"""RSS 2.0 / RSS 1.0 / Atom 解析: 纯标准库, 不出网

时间统一转东八区 (Asia/Shanghai, 无夏令时) 的 ISO 8601；
条目尽量保留作者、分类、guid、更新时间，渲染层再决定显示哪些。

XML 脏数据容忍两轮: 去掉 <?xml 声明前的杂质, 还失败就剥掉 <script>/<style>
再试; 两轮都挂才报错。
"""

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from webtool.core import text

_clean = text.clean_markup
_CST = timezone(timedelta(hours=8))
_DATE_RE = re.compile(
    r'(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})'
    r'(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?'
)


# ============================================================ 解析 (纯标准库)

_NS = {
    'atom': 'http://www.w3.org/2005/Atom',
    'content': 'http://purl.org/rss/1.0/modules/content/',
    'dc': 'http://purl.org/dc/elements/1.1/',
    'dcterms': 'http://purl.org/dc/terms/',
    'itunes': 'http://www.itunes.com/dtds/podcast-1.0.dtd',
}


def _strip_cdata(s):
    return re.sub(r'^<!\[CDATA\[|\]\]>$', '', (s or '').strip())


def _find(el, path):
    """按路径找元素; 先按命名空间, 失败再按 local-name 逐层匹配 (RSS 1.0)"""
    x = el.find(path, _NS)
    if x is not None:
        return x
    cur = [el]
    for seg in path.split('/'):
        want = seg.rsplit(':', 1)[-1]
        cur = [c for node in cur for c in list(node)
               if c.tag.rsplit('}', 1)[-1] == want]
        if not cur:
            return None
    return cur[0]


def _text_of(el, *paths):
    """按优先级取子元素文本 (含 CDATA/XHTML 嵌套清洗)"""
    for p in paths:
        x = _find(el, p)
        if x is None:
            continue
        s = _strip_cdata(''.join(x.itertext()))
        if s:
            return s
    return ''


def _norm_date(value):
    """任意常见 feed 时间 → 东八区 ISO 8601; 认不出就原样返回"""
    s = (value or '').strip()
    if not s:
        return ''
    dt = None
    try:
        dt = parsedate_to_datetime(s)          # RFC 822: Sun, 25 Oct 2026 14:15:59 GMT
    except (TypeError, ValueError):
        pass
    if dt is None:
        iso = s.replace('Z', '+00:00')
        iso = re.sub(r'\s+([+-]\d{2}:?\d{2})$', r'\1', iso)
        try:
            dt = datetime.fromisoformat(iso)
        except ValueError:
            m = _DATE_RE.search(s)
            if not m:
                return s
            try:
                dt = datetime(*(int(x) if x else 0 for x in m.groups()),
                              tzinfo=_CST)
            except ValueError:
                return s
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_CST)            # 无时区按北京时间理解
    return dt.astimezone(_CST).isoformat(timespec='seconds')


def _author(el):
    return _text_of(el, 'author', 'dc:creator', 'itunes:author',
                    'atom:author/atom:name', 'author/name')


def _categories(el):
    out = []
    for c in el:
        if c.tag.rsplit('}', 1)[-1] not in ('category', 'subject', 'tag'):
            continue
        v = (c.get('term') or _strip_cdata(''.join(c.itertext()))).strip()
        if v and v not in out:
            out.append(v)
    return out


def _updated(el):
    return _norm_date(_text_of(el, 'atom:updated', 'updated',
                               'dc:modified', 'dcterms:modified'))


def _item(title, link, snippet, date, el):
    item = {
        'title': title,
        'url': link,
        'snippet': snippet,
        'date': _norm_date(date),
    }
    if date and date != item['date']:
        item['date_raw'] = date
    author = _author(el)
    cats = _categories(el)
    guid = _text_of(el, 'guid', 'atom:id', 'id')
    updated = _updated(el)
    if author:
        item['author'] = author
    if cats:
        item['categories'] = cats
    if guid:
        item['guid'] = guid
    if updated:
        item['updated'] = updated
    return item


def parse_feed(txt, source_name=''):
    """RSS 2.0 / RSS 1.0 / Atom 统一解析

    返回 [{rank,title,url,snippet,date,author?,categories?,guid?,updated?,source?}]
    date/updated 为东八区 ISO 8601；date 保留原始字符串到 date_raw 供排查。
    """
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
                link = _text_of(e, 'atom:link', 'link', 'atom:id')
            snippet = _clean(_text_of(e, 'atom:summary', 'atom:content',
                                      'content:encoded', 'summary'))[:160]
            date = _text_of(e, 'atom:published', 'published', 'dc:date',
                            'dcterms:issued')
            if title:
                items.append(_item(title, link, snippet, date, e))
    # RSS 2.0 / 1.0 / 0.9x
    else:
        for ch in root.iter():
            if ch.tag.rsplit('}', 1)[-1] == 'item':
                title = _text_of(ch, 'title')
                link = _text_of(ch, 'link', 'atom:link', 'guid')
                snippet = _clean(_text_of(ch, 'description', 'content:encoded',
                                          'content'))[:160]
                date = _text_of(ch, 'pubDate', 'dc:date', 'dcterms:issued',
                                'atom:published', 'updated')
                if title:
                    items.append(_item(title, link, snippet, date, ch))
    for i, x in enumerate(items):
        x['rank'] = i + 1
        if source_name:
            x['source'] = source_name
    return items
