"""逆向接口文档检索层

`data/reverse/` 下是从 akshare 源码**手工逆向**出来的底层 HTTP 接口文档, 7 个
分册共 900+ 接口, 每条记录带源码文件:行号可回溯。本模块只做检索与节选, 不
复制文档内容。

## 与前两层的分工

| 层 | 覆盖 | 回答什么 |
|---|---|---|
| `srv.py` (24 工具) | 高阶聚合 | "给我茅台的财务" |
| `rawapi.py` (151) / `eco.py` (~1300) | 调用接口 | "用哪个函数调" |
| **本模块** | 900+ 逆向文档 | **"底层 URL/参数/字段什么意思"** |

## 为什么需要它

前三层给的都是**函数名**。但接一个没见过的数据源时, 真正要查的是:

- 端点 URL 是什么 (akshare 不暴露)
- `reportName` / `filter` / `columns` 怎么拼
- 返回字段是 `SECURITY_CODE` 还是 `SECUCODE`, 含义对应哪一列
- 哪些接口已下线、哪些要 token、哪些列序会静默错位

这些只在源码里, 逆向文档把它们抄成了可 grep 的文字。
"""
import json
import os
import re

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'reverse')
_IDX = os.path.join(_DIR, '_index.json')

_cache = {}


class DocsError(RuntimeError):
    """逆向文档不存在 / 检索失败"""


def _index():
    if 'idx' not in _cache:
        if not os.path.exists(_IDX):
            raise DocsError(f'逆向文档索引缺失: {_IDX}')
        with open(_IDX, encoding='utf-8') as f:
            _cache['idx'] = json.load(f)
    return _cache['idx']


def _book(fn):
    if fn not in _cache:
        p = os.path.join(_DIR, fn)
        if not os.path.exists(p):
            raise DocsError(f'分册不存在: {fn}')
        with open(p, encoding='utf-8') as f:
            _cache[fn] = f.read()
    return _cache[fn]


def books():
    """全部分册清单"""
    d = _index()
    return {'count': len(d['books']), 'books': d['books'],
            'reportNames': len(d['reportNames']),
            'endpoints': len(d['endpoints'])}


def stats():
    d = _index()
    return {'books': len(d['books']), 'reportNames': len(d['reportNames']),
            'endpoints': len(d['endpoints']),
            'total_lines': sum(b['lines'] for b in d['books']),
            'total_bytes': sum(b['bytes'] for b in d['books']),
            'categories': [b['category'] for b in d['books']]}


def _norm(t):
    """去掉标点与"逆向"等修饰词, 让 '衍生品' 能命中 '逆向-衍生品固收.md'"""
    t = t.lower()
    for w in ('逆向', '文档', '说明'):
        t = t.replace(w, '')
    return ''.join(ch for ch in t if ch.isalnum() or ch in '\u4e00-\u9fff')


def find_book(key):
    """按文件名 / 分类关键词定位分册

    宽松匹配: 去标点与 '逆向' 修饰词, 所以 docs-section 衍生品 期权 能命中
    '逆向-衍生品固收.md' 而不是报找不到。
    """
    d = _index()
    k = _norm(key)
    if not k:
        raise DocsError(f'分册关键词为空: {key!r}')
    for b in d['books']:
        if k in _norm(b['file']) or k in _norm(b['category']):
            return b
    near = [b['category'] for b in d['books'] if _norm(key)[:2] in _norm(b['category'])]
    raise DocsError(f'没匹配到分册: {key}' +
                    (f' (相近分类: {", ".join(near)})' if near else ' (webtool stock docs-books 看清单)'))


def _sections(text, pattern):
    """按二级标题切段, 返回 [(标题, 正文)]"""
    parts = re.split(r'^## ', text, flags=re.M)[1:]
    out = []
    for p in parts:
        nl = p.find('\n')
        head = p[:nl].strip()
        body = p[nl + 1:] if nl >= 0 else p
        if re.search(pattern, head, re.I):
            out.append((head, body))
    return out


def book(key, max_chars=6000):
    """取整个分册 (超长自动截断)"""
    b = find_book(key)
    text = _book(b['file'])
    truncated = len(text) > max_chars
    return {'file': b['file'], 'category': b['category'], 'desc': b['desc'],
            'lines': b['lines'], 'chars': len(text), 'truncated': truncated,
            'content': text[:max_chars]}


def report(rn, max_chars=4000):
    """按 reportName 取单个接口的完整逆向条目"""
    d = _index()
    rn = rn.upper()
    hit = next((x for x in d['reportNames'] if x['reportName'] == rn), None)
    if not hit:
        near = [x['reportName'] for x in d['reportNames']
                if rn[:6] in x['reportName']][:8]
        raise DocsError(f'没找到 reportName: {rn}' +
                        (f' (相近: {", ".join(near)})' if near else ''))
    text = _book('东财reportName逆向.md')
    m = re.search(r'^## \d+\. `' + re.escape(rn) + r'`\s*$(.*?)(?=^## \d+\. `|\Z)',
                  text, re.M | re.S)
    body = (m.group(1).strip() if m else '(条目缺失, 用 docs-book 东财reportName 看全文)')
    return {'reportName': hit['reportName'], 'akshare_func': hit['func'],
            'source': hit['src'], 'truncated': len(body) > max_chars,
            'content': body[:max_chars]}


def endpoint(ep, max_chars=6000):
    """按 URL 片段反查: 哪些分册提到这个端点"""
    d = _index()
    key = ep.rstrip('/').split('?')[0]
    found = [b['file'] for b in d['books']
             if key in _book(b['file'])]
    if not found:
        # 退一步只匹配域名
        host = key.split('://')[-1].split('/')[0]
        found = [b['file'] for b in d['books']
                 if f'://{host}' in _book(b['file'])]
        if not found:
            raise DocsError(f'没找到端点: {ep}')
        return {'query': ep, 'matched_by': 'host', 'books': found,
                'note': '仅按域名匹配, 用 docs-search 精确找段落'}
    snips = []
    for fn in found:
        text = _book(fn)
        for i, line in enumerate(text.split('\n')):
            if key in line:
                lo = max(0, i - 6)
                blk = '\n'.join(text.split('\n')[lo:i + 30])
                if len(blk) > max_chars:
                    blk = blk[:max_chars]
                snips.append({'book': fn, 'line': i + 1, 'snippet': blk})
                break
    return {'query': ep, 'matched_by': 'path', 'books': found, 'snippets': snips}


def search(kw, limit=20):
    """全文 grep 逆向文档, 带行号上下文"""
    if not kw or not kw.strip():
        raise DocsError('搜索关键词为空')
    kw = kw.strip()
    hits = []
    for b in _index()['books']:
        text = _book(b['file'])
        lines = text.split('\n')
        for i, line in enumerate(lines):
            if kw.lower() in line.lower():
                lo = max(0, i - 2)
                hits.append({'book': b['file'], 'category': b['category'],
                             'line': i + 1,
                             'snippet': '\n'.join(lines[lo:i + 3])[:600]})
                if len(hits) >= limit:
                    return {'keyword': kw, 'count': len(hits),
                            'truncated': True, 'hits': hits}
    return {'keyword': kw, 'count': len(hits), 'truncated': False, 'hits': hits}


def section(key, pattern, max_chars=4000):
    """取分册内匹配的二级标题段落 (如某国宏观、某交易所期权)"""
    b = find_book(key)
    secs = _sections(_book(b['file']), pattern)
    if not secs:
        avail = [h[:24] for h in re.findall(r'^## (.+)$', _book(b['file']), re.M)][:10]
        raise DocsError(f'{b["file"]} 里没有匹配 "{pattern}" 的章节' +
                        (f'\n该册章节: {", ".join(avail)}' if avail else ''))
    out = []
    total = 0
    for head, body in secs:
        chunk = '## ' + head + '\n' + body
        if total + len(chunk) > max_chars:
            chunk = chunk[:max(0, max_chars - total)]
        out.append(chunk)
        total += len(chunk)
        if total >= max_chars:
            break
    return {'book': b['file'], 'matched': len(secs), 'returned': len(out),
            'truncated': len(out) < len(secs), 'content': '\n\n'.join(out)}
