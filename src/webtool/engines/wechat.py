"""微信公众号正文提取: 直接读 #js_content, 不做通用正文推断

mp.weixin.qq.com 的文章页把正文全放在 `#js_content` 里, 页面其余部分是
"点赞/在看/小程序/扫码"这些固定 UI。通用提取器 (trafilatura 等) 会把这些
UI 当正文, 遇到"图片消息"(正文只有一张长图) 时更是只剩 UI 文案。

本模块只认公众号结构:
  - 标题 `#activity-name` / og:title
  - 作者 `#js_name`
  - 正文 `#js_content`: 段落文字 + 图片 (data-src / src)
图片消息没有任何文字时, 输出仍以图片清单为主体, 不返回空正文。
"""
import re

_META_RE = re.compile(
    r'<meta[^>]+property="og:title"[^>]+content="([^"]*)"', re.I)


def _text_of(node):
    return re.sub(r'\s+', ' ', node.get_text(' ', strip=True)).strip()


def _clean_img(u):
    return (u or '').replace('&amp;', '&').strip()


def extract(html, url=''):
    """→ (markdown, meta) ; 不是公众号结构时返回 ('', {})"""
    from bs4 import BeautifulSoup
    try:
        soup = BeautifulSoup(html, 'lxml')
    except Exception:
        soup = BeautifulSoup(html, 'html.parser')

    body = soup.select_one('#js_content') or soup.select_one('.rich_media_content')
    if body is None:
        return '', {}

    title_el = soup.select_one('#activity-name') or soup.select_one('h1.rich_media_title')
    title = _text_of(title_el) if title_el else ''
    if not title:
        m = _META_RE.search(html)
        title = (m.group(1) if m else '').strip()
    author_el = soup.select_one('#js_name')
    author = _text_of(author_el) if author_el else ''

    # 隐藏节点 (display:none) 是模板占位, 不该进正文
    for n in body.select('[style*="display: none"], [style*="display:none"]'):
        n.decompose()

    lines, seen = [], set()
    for el in body.descendants:
        name = getattr(el, 'name', None)
        if name == 'img':
            u = _clean_img(el.get('data-src') or el.get('src') or '')
            if u and not u.startswith('data:') and u not in seen:
                seen.add(u)
                lines.append(f'\n![图片]({u})\n')
        elif name in ('p', 'section', 'div', 'br', 'li', 'h1', 'h2', 'h3'):
            lines.append('\n')
        elif isinstance(el, str):
            t = el.strip()
            if t:
                lines.append(t)

    text = ''.join(lines)
    text = re.sub(r'[ \t\u00a0]+', ' ', text)
    text = re.sub(r' *\n *', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()

    imgs = [l for l in text.split('\n') if l.startswith('![图片]')]
    if not text:
        return '', {}
    # 图片消息: 没有文字时也要让调用方知道拿到的是图, 别当成空正文
    meta = {'title': title, 'author': author, 'images': imgs,
            'image_post': bool(imgs and len(re.sub(r'!\[图片\]\(\S+\)', '', text).strip()) < 40)}
    parts = []
    if title:
        parts.append(f'# {title}')
    if author:
        parts.append(f'> 公众号：{author}')
    parts.append(text)
    return '\n\n'.join(parts), meta
