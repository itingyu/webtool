"""从 HTML 里抽结构化数据: JSON-LD / OpenGraph / meta

商品价格、评分、库存、发布时间这些字段, 站点通常已经用 schema.org 的 JSON-LD
写在 `<script type="application/ld+json">` 里 —— 直接读它比从正文猜准得多,
也省 token (一段 JSON 几十字 vs 正文几千字)。

只用标准库 (HTMLParser), 不给 fetch 的依赖面再加东西; JSON-LD 本身是 JSON,
解析靠 json 模块。脏数据一律跳过, 抽不到就是抽不到, 不猜。
"""

import json
from html.parser import HTMLParser

# 常见字段的取值路径: 先按别名找, 找不到再按顺序试这些路径
_ALIASES = {
    'title': ('name', 'headline', 'title'),
    'name': ('name', 'headline'),
    'price': ('offers.price', 'offers.lowPrice', 'price', 'offers.0.price'),
    'currency': ('offers.priceCurrency', 'priceCurrency', 'offers.0.priceCurrency'),
    'availability': ('offers.availability', 'offers.0.availability'),
    'rating': ('aggregateRating.ratingValue', 'ratingValue'),
    'reviews': ('aggregateRating.reviewCount', 'reviewCount'),
    'brand': ('brand.name', 'brand'),
    'sku': ('sku', 'productID', 'mpn'),
    'image': ('image.url', 'image.0', 'image'),
    'published': ('datePublished', 'dateCreated', 'uploadDate'),
    'author': ('author.name', 'author.0.name', 'author'),
    'description': ('description', 'abstract'),
    'address': ('address.streetAddress', 'address.addressLocality', 'address'),
    'company': ('hiringOrganization.name',),
}

# 优先拿哪一类实体: 商品页的 Product, 文章页的 Article, 招聘的 JobPosting
_PREFER = ('Product', 'Offer', 'Article', 'NewsArticle', 'BlogPosting',
           'Recipe', 'JobPosting', 'Event', 'Movie', 'Book')

_OG_KEYS = ('og:title', 'og:description', 'og:image', 'og:site_name',
            'og:type', 'og:url', 'article:published_time', 'article:author')


class _Picker(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ld = []
        self.metas = {}
        self.title = ''
        self._in_ld = False
        self._in_title = False
        self._buf = []

    def handle_starttag(self, tag, attrs):
        d = {k.lower(): (v or '') for k, v in attrs}
        if tag == 'script' and d.get('type', '').split(';')[0].strip().lower() \
                == 'application/ld+json':
            self._in_ld, self._buf = True, []
        elif tag == 'meta':
            k = (d.get('property') or d.get('name') or '').lower()
            v = d.get('content') or ''
            if k and v:
                self.metas.setdefault(k, v)
        elif tag == 'title':
            self._in_title, self._buf = True, []

    def handle_data(self, data):
        if self._in_ld or self._in_title:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self._in_ld:
            self._in_ld = False
            raw = ''.join(self._buf).strip()
            if raw:
                try:
                    self.ld.append(json.loads(raw))
                except ValueError:
                    pass
        elif tag == 'title' and self._in_title:
            self._in_title = False
            self.title = ''.join(self._buf).strip()


def _flatten(node, out):
    """JSON-LD 可能是单对象 / 列表 / @graph 包裹, 统一摊平"""
    if isinstance(node, list):
        for it in node:
            _flatten(it, out)
    elif isinstance(node, dict):
        if '@graph' in node:
            _flatten(node['@graph'], out)
        if node.get('@type'):
            out.append(node)


def _types(obj):
    t = obj.get('@type')
    if isinstance(t, list):
        return [str(x) for x in t]
    return [str(t)] if t else []


def _dig(obj, path):
    """按 'offers.price' / 'offers.0.price' 取嵌套值; 取不到返回 None"""
    cur = obj
    for part in path.split('.'):
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
        if cur is None:
            return None
    return cur


def _scalar(v):
    """JSON-LD 值可能是 {'@value': x} / 列表 / 带 @id 的引用 — 压成可读值"""
    if isinstance(v, dict):
        if '@value' in v:
            return _scalar(v['@value'])
        if 'name' in v:
            return _scalar(v['name'])
        return None
    if isinstance(v, list):
        return ', '.join(str(x) for x in (_scalar(i) for i in v) if x) or None
    if isinstance(v, (str, int, float, bool)):
        return v
    return None


def _best(entities):
    ranked = sorted(entities, key=lambda e: (
        0 if any(t in _PREFER for t in _types(e)) else 1))
    return ranked[0] if ranked else None


def parse(html):
    """HTML → {jsonld, types, meta, og, fields}

    jsonld 是摊平后的实体列表; fields 是常见字段的取值 (抽不到的不出现在里面)。
    """
    p = _Picker()
    try:
        p.feed(html or '')
        p.close()
    except Exception:                      # HTML 再脏也不该让 fetch 整个失败
        pass
    ents = []
    for node in p.ld:
        _flatten(node, ents)
    fields = {}
    best = _best(ents)
    if best is not None:
        for key, paths in _ALIASES.items():
            for path in paths:
                val = _scalar(_dig(best, path))
                if val not in (None, ''):
                    fields[key] = val
                    break
    og = {k: p.metas[k] for k in _OG_KEYS if p.metas.get(k)}
    meta = {k: p.metas[k] for k in
            ('description', 'author', 'keywords', 'title') if p.metas.get(k)}
    if p.title:
        meta.setdefault('title', p.title)
    # JSON-LD 没给标题/描述时用 meta 兜底 (常见于只有 OG 的站点)
    for key, src in (('title', 'og:title'), ('description', 'og:description')):
        if key not in fields and og.get(src):
            fields[key] = og[src]
    if 'title' not in fields and meta.get('title'):
        fields['title'] = meta['title']
    types = [t for e in ents for t in _types(e)]
    return {'jsonld': ents, 'types': sorted(set(types)),
            'fields': fields, 'og': og, 'meta': meta}


def pick(result, names):
    """从 parse() 的结果里挑指定字段; 支持 'offers.price' 这类路径

    返回 {name: value}, 取不到的值不出现 (不返回 None 占位, 免得下游误以为有)。
    """
    out = {}
    fields = result.get('fields') or {}
    for name in names:
        name = name.strip()
        if not name:
            continue
        if name in fields:
            out[name] = fields[name]
            continue
        for ent in result.get('jsonld') or []:
            val = _scalar(_dig(ent, name))
            if val not in (None, ''):
                out[name] = val
                break
        else:
            if result.get('og', {}).get(name):
                out[name] = result['og'][name]
    return out
