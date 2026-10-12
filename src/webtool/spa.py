# -*- coding: utf-8 -*-
"""SPA 内嵌状态数据提取 (SSR harvester)

SPA 站点的首屏数据通常以 JSON 形态内嵌在 HTML 的 <script> 里 (SSR/hydration):
- URL 编码 JSON: 头条 m 站 RENDER_DATA (%7B%22... 开头的大块)
- window 全局挂载: __NEXT_DATA__ / __NUXT__ / __INITIAL_STATE__ / __PRELOADED_STATE__ ...
- <script type="application/json">: 通用 JSON 块

常规正文提取器 (trafilatura/readability) 只看 DOM 文本, 看不到 script 内部,
于是 SPA 壳页被误判为 "JS-only, 拿不到正文"。本模块把这些内嵌 state 解出来,
递归找两类有效数据:

1. 文章正文: 足够长的文本/HTML 节点 (键名或内容形态判断)
2. 内容列表: 含 title+url 的条目数组 (feed/推荐流) -> 渲染成 markdown 清单

框架无关, 不依赖站点专属逻辑; 找不到就返回空, 上层保持原行为。
"""
import json
import re
import urllib.parse

# window.<STATE> = {...} 挂载点 (Next/Nuxt/Redux/Vue/自研常见命名)
_STATE_RE = re.compile(
    r'window\.(__NEXT_DATA__|__NUXT__|__INITIAL_STATE__|__INITIAL_DATA__'
    r'|__PRELOADED_STATE__|__APP_DATA__|__INITIAL_PROPS__|__STORE__'
    r'|__REDUX_STATE__|__APOLLO_STATE__|INITIAL_STATE|RENDER_DATA)'
    r'\s*=\s*')

_MAX_SCRIPT = 3_000_000      # 单 script 解析上限
_MAX_NODES = 50_000          # 单 state 递归节点上限
_MAX_DEPTH = 15

_KEY_CONTENT = re.compile(r'(content|article|body|text|html|rich)', re.I)
_KEY_TITLE = re.compile(r'(title|subject|name)', re.I)
_KEY_URL = re.compile(r'(url|link|href|uri)', re.I)
_KEY_SNIPPET = re.compile(r'(abstract|summary|digest|description|excerpt)', re.I)
_KEY_TIME = re.compile(r'(publish_?time|publish_?ts|created?_?at|create_?time|published?_?at)', re.I)


def first_state(html):
    """取首个可解析的内嵌 state (供外部模块复用)"""
    try:
        sts = _collect_states(html)
        return sts[0][1] if sts else None
    except Exception:
        return None


def harvest(html, url):
    """从 HTML 内嵌 state 提取数据. 返回 (markdown, note) 或 ('', None)

    note: {'strategy', 'state', 'node', 'type': 'article'|'list', 'items': n}
    """
    try:
        states = _collect_states(html)
    except Exception:
        return '', None
    if not states:
        return '', None
    best_content = ('', None)      # (md, path)
    best_list = ([], None, None)   # (items, path, state_name)
    for state_name, root in states:
        try:
            for path, val in _walk(root, max_depth=8):
                if isinstance(val, list) and 3 <= len(val) <= 200:
                    items = _as_items(val, url)
                    if items and len(items) > len(best_list[0]):
                        best_list = (items, path, state_name)
        except Exception:
            continue
    # 文章正文优先于列表 (列表是降级产物)
    for state_name, root in states:
        try:
            for path, val in _walk(root):
                if isinstance(val, str):
                    if len(best_content[0]) < 3000 or not best_content[0]:
                        md = _as_content(val)
                        if md and len(md) > len(best_content[0]):
                            best_content = (md, path)
        except Exception:
            continue
    if best_content[0]:
        return best_content[0], {'strategy': 'embedded-state', 'type': 'article',
                                 'node': best_content[1], 'state': None}
    if best_list[0]:
        md = _render_list(best_list[0])
        return md, {'strategy': 'embedded-state', 'type': 'list',
                    'node': best_list[1], 'state': best_list[2],
                    'items': len(best_list[0])}
    return '', None


# ---------- state 收集 ----------

def _collect_states(html):
    out = []
    for m in re.finditer(r'<script\b[^>]*>([\s\S]*?)</script>', html, re.I):
        blob = m.group(1).strip()
        if not blob or len(blob) > _MAX_SCRIPT:
            continue
        # URL 编码 JSON
        if blob[:3] in ('%7B', '%7b', '%5B', '%5b'):
            try:
                out.append(('urlencoded-json', json.loads(urllib.parse.unquote(blob))))
            except Exception:
                pass
            continue
        wm = _STATE_RE.search(blob)
        if wm:
            obj = _loads_tail(blob[wm.end():])
            if obj is not None:
                out.append((wm.group(1), obj))
            continue
        if re.search(r'type\s*=\s*["\']application/(?:ld\+)?json["\']',
                     m.group(0)[:200], re.I):
            try:
                out.append(('json-script', json.loads(blob)))
            except Exception:
                pass
    return out


def _loads_tail(tail):
    """解析赋值号后的 JS 段: 直接 loads, 失败则截掉尾部 JS 语句重试"""
    tail = tail.strip().rstrip(';').strip()
    starts = [i for i in (tail.find('{'), tail.find('[')) if i >= 0]
    if not starts:
        return None
    base = tail[min(starts):]
    cands = [base]
    pos = base.rfind('}')
    for _ in range(3):
        if pos <= 0:
            break
        cands.append(base[:pos + 1])
        pos = base.rfind('}', 0, pos)
    for c in cands:
        if len(c) > _MAX_SCRIPT:
            continue
        try:
            return json.loads(c)
        except Exception:
            continue
    return None


# ---------- 结构探测 ----------

def _walk(root, max_depth=_MAX_DEPTH):
    """深度优先遍历, yield (路径, 值); 带节点数/深度护栏"""
    count = [0]

    def rec(o, path, depth):
        if depth > max_depth:
            return
        count[0] += 1
        if count[0] > _MAX_NODES:
            return
        yield path, o
        if isinstance(o, dict):
            for k, v in list(o.items())[:500]:
                yield from rec(v, f'{path}/{k}' if path else str(k), depth + 1)
        elif isinstance(o, list):
            for i, v in enumerate(o[:300]):
                yield from rec(v, f'{path}[{i}]', depth + 1)

    return rec(root, '', 0)


def _as_content(val):
    """字符串是否像文章正文/富文本 -> markdown"""
    if not val or len(val) < 200:
        return None
    s = val.strip()
    # JSON/类 JSON 载荷串不是正文 (SPA 常把整块 cell JSON 塞进字符串字段)
    if s[0] in '{[':
        return None
    is_html = bool(re.search(r'<(p|div|section|article|br|h\d|img|li)\b', s[:4000], re.I))
    if is_html:
        return _html_to_md(s)
    plain = re.sub(r'\s+', ' ', s).strip()
    sample = plain[:2000]
    printable = sum(c.isprintable() and not c.isspace() for c in sample)
    if printable / max(len(sample), 1) < 0.6:
        return None
    # 正文必须像"人话": 中文占比或英文词对 — 排除 base64/签名/hex 串
    cjk = len(re.findall(r'[\u4e00-\u9fff]', sample))
    if cjk / max(len(sample), 1) >= 0.05:
        return plain
    if len(re.findall(r'[A-Za-z]{2,}\s+[A-Za-z]{2,}', sample)) < 8:
        return None
    return plain if len(plain) >= 200 else None


def _as_items(arr, base_url):
    """数组是否像内容列表 (title + url/abstract) -> 规整条目

    元素本身没 title 时, 在元素内部下钻 (≤4 层) 找带 title 的子 dict ——
    兼容 feed 类 SSR 数据的 cell 包装结构 (data[i].assembleCell.itemCell.articleBase.title)。
    条目必须 title + (url|snippet|time) 之一, 过滤纯按钮/配置项数组。
    """
    if not arr or not all(isinstance(it, (dict, type(None))) for it in arr):
        return None
    dicts = [it for it in arr if isinstance(it, dict)]
    if len(dicts) < max(3, int(0.6 * len(arr))):
        return None

    def record(d):
        title = _first(d, _KEY_TITLE)
        if not title or not (2 < len(str(title)) < 300):
            return None
        row = {'title': str(title).strip()}
        u = _first(d, _KEY_URL)
        if u and str(u).startswith('/'):
            u = urllib.parse.urljoin(base_url, str(u))
        if u:
            row['url'] = str(u)
        snip = _first(d, _KEY_SNIPPET)
        if snip:
            row['snippet'] = re.sub(r'\s+', ' ', str(snip)).strip()[:120]
        ts = _first(d, _KEY_TIME)
        if ts:
            t = _fmt_time(ts)
            if t:
                row['time'] = t
        return row if len(row) >= 2 else None

    items = []
    for it in dicts:
        row = record(it)
        if row is None:
            cands = [r for _, v in _walk(it, max_depth=4)
                     if isinstance(v, dict) and v is not it
                     for r in [record(v)] if r]
            if cands:
                row = max(cands, key=lambda r: len(r))
        if row:
            items.append(row)
    return items if len(items) >= 3 and len(items) * 2 >= len(dicts) else None


def _first(d, pat):
    """按键名模式取第一个像样的字符串/数值"""
    best = None
    for k, v in d.items():
        if pat.search(str(k)) and v is not None:
            if isinstance(v, str) and 1 < len(v) < 3000:
                return v
            if isinstance(v, (int, float)) and pat is _KEY_TIME:
                return v
            if best is None and isinstance(v, str):
                best = v
    return best


def _fmt_time(v):
    import datetime
    try:
        ts = int(v)
        if ts > 1e12:
            ts //= 1000
        if 1e9 < ts < 4e9:
            return datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')
    except Exception:
        pass
    return None


def _render_list(items):
    lines = []
    for i, it in enumerate(items[:30], 1):
        t = it['title']
        line = f"{i}. [{t}]({it['url']})" if it.get('url') else f"{i}. {t}"
        extra = ' | '.join(x for x in (it.get('time'), it.get('snippet')) if x)
        if extra:
            line += f'\n   {extra}'
        lines.append(line)
    return '\n'.join(lines)


def _html_to_md(html):
    """轻量 HTML→markdown (正文场景够用, 零强依赖)"""
    md = re.sub(r'<img[^>]*?src=["\']([^"\']+)["\'][^>]*>', r'\n![](\1)\n', html, flags=re.I)
    md = re.sub(r'<br\s*/?>|</p\s*>|</div\s*>|</h\d\s*>|</li\s*>', '\n', md, flags=re.I)
    md = re.sub(r'<[^>]+>', '', md)
    import html as _h
    md = _h.unescape(md)
    md = re.sub(r'\n{3,}', '\n\n', md)
    md = re.sub(r'[ \t]+', ' ', md)
    return md.strip()
