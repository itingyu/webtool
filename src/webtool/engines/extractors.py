"""正文提取策略链 (Strategy Chain)

清单在 data/plugins.json 的 "extractor" 段:

    {"extractor": {"我的": {"module": "mypkg.mymod:extract", "desc": "..."}}}

在用户配置里追加即可插新提取器。顺序即 dict 插入序, 后注册的同名条目覆盖前者。

分两层, 由 spec 里的 `"dump": true` 标记:

- **内容层** (trafilatura / boilerplate / readability): 真在找正文。同层的一起
  跑, 结果按"碎片率 + 长度"择优 (见 pick_best) —— 谁先谁后不该决定结果好坏,
  同一个页面 trafilatura 可能把文章区的推广块一起收进来, readability 却切得干净;
- **兜底层** (inscriptis / 零依赖剥标签): 整页纯文本。只在内容层全空时才用,
  **不参与择优** —— 它永远"非空", 一竞争就会用整页噪声盖掉正文。

单个提取器抛异常/缺依赖都不影响后续, 跳过即可; 缺的是谁记在 meta['_missing'],
由上层提示补依赖。

返回的 meta 里带 `_via` = 最终生效的提取器名, 用于观测"这次是谁出的活"。
"""
import re
import warnings


def extract_trafilatura(html, url, meta):
    """markdown + 元数据; 首个也是主力提取器"""
    import trafilatura
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        md = trafilatura.extract(html, url=url, output_format='markdown',
                                 include_links=True, include_tables=True,
                                 with_metadata=True)
    if not (md and md.strip()):
        return '', meta
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            m = trafilatura.bare_extraction(html, url=url, with_metadata=True,
                                            only_with_metadata=False)
        keys = ('title', 'author', 'date', 'sitename', 'description')
        if m and not isinstance(m, dict):
            meta.update({k: str(getattr(m, k)) for k in keys if getattr(m, k, None)})
        elif m:
            meta.update({k: str(m[k]) for k in keys if m.get(k)})
    except Exception:
        pass
    return md, meta


def extract_readability(html, url, meta):
    """readability-lxml 摘要 + html2text 转 markdown"""
    from readability import Document
    import html2text
    doc = Document(html)
    title = doc.short_title()
    if title:
        meta['title'] = title
    h = html2text.HTML2Text()
    h.body_width = 0
    h.ignore_images = True
    h.ignore_emphasis = False
    return h.handle(doc.summary(html_partial=True)).strip(), meta


def extract_inscriptis(html, url, meta):
    """全文纯文本, 保底永不返空"""
    import inscriptis
    return inscriptis.get_text(html), meta


def basic_text(html):
    """零依赖正则剥标签; inscriptis 也缺时的最终兜底"""
    import html as _h
    html = re.sub(r'<(script|style|noscript)[^>]*>.*?</\1>', '', html, flags=re.S | re.I)
    html = re.sub(r'<br[^>]*>|</p>|</div>|</h\d>', '\n', html, flags=re.I)
    txt = _h.unescape(re.sub(r'<[^>]+>', '', html))
    txt = re.sub(r'\n{3,}', '\n\n', txt)
    return re.sub(r'[ \t]+', ' ', txt).strip()


_JS_SHELL_RE = re.compile(
    r'请开启|请启用|需要开启|需要启用|需要允许|允许.{0,6}执行|开启.{0,8}JavaScript'
    r'|enable.{0,20}javascript|turn.{0,10}on.{0,10}javascript'
    r'|requires?\s+javascript|浏览器不支持|请使用.{0,10}浏览器'
    r'|您需要|你需要|需开启|需启用|需允许|需要.{0,6}浏览器'
    r'|please\s+enable\s+javascript|enable\s+javascript', re.I)


def is_js_shell(html):
    """SPA 空壳识别: 剥标签后正文 <500 字符且开头 30 字符内是"请开启JS"类提示词

    这类页面提取出来是提示语而非正文, 提前短路让上层给 hint 而非缓存垃圾。
    不带 ^ 锚 — 容忍 title/站点名前置噪声。
    """
    from html import unescape
    text = re.sub(r'<script[\s\S]*?</script>|<style[\s\S]*?</style>|<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', unescape(text)).strip()
    return len(text) < 500 and bool(_JS_SHELL_RE.search(text[:30]))


_FM_RE = re.compile(r'\A---\n[\s\S]*?\n---\n')          # YAML 元数据头


def strip_front_matter(text):
    """去掉 YAML 头 (trafilatura 带元数据时的产物), 只留下正文用于比较"""
    return _FM_RE.sub('', text or '').lstrip()


_MD_LINE = re.compile(r'^\s*(?:[#>\-*+|`]|\d+[.、])\s')   # markdown 结构行不算碎片
_SENT_ENDS = '。！？；!?;'                                  # 句末标点: 句子的证据


def fragment_ratio(text):
    """碎片率: 正文里"短且没有句末标点"的行占多少字符

    这是判别"提取结果里混没混进广告/导航"的结构化指标 —— 不看任何关键词, 只看
    文本自己被切成了什么形状: 正文是一条条句子 (有 。！？), 而推广/分享/导航被
    切成一地碎片 ("分享到微信朋友圈" "扫描二维码关注"), 又短又没有句末标点。
    """
    body = strip_front_matter(text)
    if not body.strip():
        return 1.0
    frag = total = 0
    for raw in body.splitlines():
        line = raw.strip()
        if not line or _MD_LINE.match(raw):
            continue
        total += len(line)
        if len(line) <= 15 and not any(c in line for c in _SENT_ENDS):
            frag += len(line)
    return frag / total if total else 1.0


def pick_best(cands):
    """在多个提取结果里挑最干净的, 返回胜出的名字

    只比碎片率会偏好"就截了一句干净话"的产出, 只比长度会偏好整页 dump —— 所以
    合成一个连续分数:

        分 = 碎片率 + 0.25 * (1 - 本文长度 / 最长候选长度)

    也就是"干净"与"完整"一起算账: 长度只有最长候选一半的, 相当于多背 12.5 个
    百分点的碎片率。这样"长而略脏"压得过"短而极干净", 免得为了干净把文章丢了。
    cands 是 [(名字, 正文), ...], 顺序即注册顺序 (同分时前面的赢)。
    """
    rows = [(n, t, strip_front_matter(t)) for n, t in cands]
    longest = max((len(b) for _n, _t, b in rows), default=0)
    if longest <= 0:
        return rows[0][0] if rows else ''
    scored = []
    for i, (n, _t, body) in enumerate(rows):
        s = fragment_ratio(body) + 0.25 * (1 - len(body) / longest)
        scored.append((round(s, 4), i, n))
    return min(scored)[2]


def run_chain(html, url, meta):
    """按优先级遍历提取器, 返回 (正文, meta)

    与"第一个非空就用"的老做法不同, 这里让**同层的提取器都跑一遍再择优**
    (见 pick_best): 同一个页面, trafilatura 会把文章区的推广块 ("分享到微信
    朋友圈" "扫描二维码关注") 一起收进来, readability 却切得干净 —— 谁先谁后
    不该决定结果好坏。兜底层 (整页 dump) 只在内容层全空时才跑。
    """
    from webtool.core.plugins import table
    got, dumps, missing = [], [], []
    for name, spec in table('extractor').items():
        is_dump = bool(spec.get('dump'))
        if is_dump and got:
            continue                      # 内容层已有产出, 整页 dump 不必再跑
        try:
            text, _m = spec['fn'](html, url, meta)
        except ImportError as e:          # 缺依赖不算失败, 记下来给上层提示
            missing.append(getattr(e, 'name', None) or name)
            continue
        except Exception:
            continue
        if text and text.strip():
            (dumps if is_dump else got).append((name, text))
    if got:
        name = pick_best(got)
        meta['_via'] = name
        meta['_missing'] = missing
        return _with_front_matter(dict(got)[name], got), meta
    if dumps:                             # 内容层全空: 整页文本兜底
        meta['_via'] = dumps[0][0]
        meta['_missing'] = missing
        return dumps[0][1], meta
    meta['_via'] = 'basic_text'
    meta['_missing'] = missing
    return basic_text(html), meta


def _with_front_matter(body, got):
    """把别人产出的 YAML 元数据头接到胜出正文上

    YAML 头只有 trafilatura 会产出, 但胜出的可能是别的提取器 —— 元数据 (标题/
    日期/站点) 与被选中的正文是两件事, 不该因为换了正文就把元数据一起丢掉。
    """
    if _FM_RE.match(body):
        return body
    for _n, t in got:
        m = _FM_RE.match(t)
        if m:
            return m.group(0) + body
    return body