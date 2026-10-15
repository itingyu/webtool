"""360 搜索 (so.com): 国内直连, 与 bing/sogou/baidu 同阵营

结果块用 `<li class="res-list">` 切分, 标题在块内 `<h3>`, 真实地址优先取
`data-mdurl` 属性 (无则退回 so.com/link?m= 跳转链)。页面混有"360翻译"、
"360百科"、"其他人还搜了" 等导航块, 一律跳过 —— 它们没有 data-mdurl 或
指向站内, 按此过滤比按文案黑名单稳。
"""

from webtool.core import text
import re
import urllib.parse

from webtool.net import transport

ENDPOINT = 'https://www.so.com/s'

_BLOCK = re.compile(r'<li class="res-list".*?(?=<li class="res-list"|</ol>)', re.S)
_TITLE = re.compile(r'<h3[^>]*>(.*?)</h3>', re.S)
_MDURL = re.compile(r'data-mdurl="([^"]+)"')
_SNIPPET = re.compile(r'class="(?:res-desc|summary-text|content-right)[^"]*"[^>]*>(.*?)</(?:div|p|span)>', re.S)
# 站外广告位 (首条常是"xxx-短视频大全-高清在线观看")
_NOISE = re.compile(r'\[转\]|-?短视频大全|高清在线观看|图片大全|在线影院')

def search(query, max_results=10, proxy=None, timeout=15, market=None, **_):
    """360 搜索; 免 key 直连, 无需代理"""
    q = urllib.parse.quote(query)
    url = f'{ENDPOINT}?q={q}'
    text, status, _via = transport.get(url, kind='search', referer='https://www.so.com/',
                                       timeout=timeout, proxy=proxy)
    if not text:
        raise RuntimeError(f'so360 空响应 (status={status})')
    return _parse(text, max_results)

def _parse(html, max_results):
    out, seen = [], set()
    for blk in _BLOCK.findall(html):
        if len(out) >= max_results:
            break
        m = _TITLE.search(blk)
        if not m:
            continue
        title = _unescape(re.sub(r'<[^>]+>', '', m.group(1))).strip()
        if not title:
            continue
        md = _MDURL.search(blk)
        url = _unescape(md.group(1)) if md else _href(blk)
        if not url or url in seen:
            continue
        # 站内导航块 (翻译/百科/相关搜索) 一律不要
        host = urllib.parse.urlparse(url).netloc
        if 'so.com' in host:
            continue
        # 站外但仍是广告位 (短视频/图片聚合): 标题带明显视频化后缀
        if _NOISE.search(title):
            continue
        seen.add(url)
        sm = _SNIPPET.search(blk)
        snippet = _unescape(re.sub(r'<[^>]+>', '', sm.group(1)))[:300] if sm else ''
        out.append({'rank': len(out) + 1, 'title': title, 'url': url,
                    'snippet': snippet})
    return out

def _href(blk):
    """无 data-mdurl 时取块内第一个外链"""
    for h in re.findall(r'href="(https?://[^"]+)"', blk):
        u = _unescape(h)
        if 'so.com' not in urllib.parse.urlparse(u).netloc:
            return u
    return None

# 与 baidu/google 同款: 转义与去标签只有 core.text 一份实现, 这里只起个短名字
_unescape = text.unescape
