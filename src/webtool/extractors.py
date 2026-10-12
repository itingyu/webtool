"""正文提取策略链 (Strategy Chain)

提取器按优先级依次尝试, 首个返回非空正文的生效 — 天然降级, 单个提取器
异常/缺依赖不影响后续。清单在 data/plugins.json 的 "extractor" 段:

    {"extractor": {"我的": {"module": "mypkg.mymod:extract", "desc": "..."}}}

在用户配置里追加即可插新提取器 (放最后 = 最低优先级)。顺序即 dict 插入序,
后注册的同名条目覆盖前者。
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


def run_chain(html, url, meta):
    """按优先级遍历提取器, 返回 (正文, meta); 全失败用 basic_text 兜底"""
    from webtool.plugins import table
    for name, spec in table('extractor').items():
        try:
            text, m = spec['fn'](html, url, meta)
            if text and text.strip():
                return text, (m if m is not None else meta)
        except ImportError:
            continue
        except Exception:
            continue
    return basic_text(html), meta