"""HTML 里抽链接 / robots.txt 判定 (纯函数, 无网络)

`fetch --links` 和 `webtool crawl` 共用: 一次抓取同时拿到正文和可继续跟的链接,
crawl 就不用为抽链接再抓一遍 HTML。
"""
import re
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlsplit

_SKIP_EXT = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.ico', '.bmp',
             '.css', '.js', '.pdf', '.zip', '.gz', '.rar', '.7z', '.tar',
             '.mp3', '.mp4', '.avi', '.mov', '.mkv', '.webm', '.woff', '.woff2',
             '.ttf', '.eot', '.exe', '.dmg', '.apk', '.iso')
_SKIP_SCHEME = ('javascript:', 'mailto:', 'tel:', 'data:', 'sms:', 'ftp:')


class _AnchorParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hrefs = []
        self.base = None
        self._in_base = False

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == 'base' and d.get('href'):
            self.base = d['href'].strip()
        elif tag == 'a' and d.get('href'):
            self.hrefs.append(d['href'].strip())


def extract_links(html, base_url, same_host=True, limit=2000):
    """抽 `http(s)` 站内链接 → 绝对 URL 列表 (已去重、去片段、去静态资源)

    same_host=True 只留同 host 的 (爬站默认就该这样, 不然两层就爬到外网去了)。
    """
    if not html:
        return []
    p = _AnchorParser()
    try:
        p.feed(html)
    except Exception:
        return []
    root = p.base or base_url
    host = (urlsplit(base_url).hostname or '').lower()
    out, seen = [], set()
    for href in p.hrefs:
        low = href.lower()
        if not href or low.startswith('#'):
            continue
        if low.startswith(_SKIP_SCHEME):
            continue
        try:
            u = urldefrag(urljoin(root, href))[0]
        except ValueError:
            continue
        s = urlsplit(u)
        if s.scheme not in ('http', 'https') or not s.hostname:
            continue
        if same_host and s.hostname.lower() != host:
            continue
        path = (s.path or '/').lower()
        if path.endswith(_SKIP_EXT):
            continue
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
        if len(out) >= limit:
            break
    return out


def parse_robots(txt):
    """极简 robots.txt 解析 → 规则列表 [(allow, path_prefix)]

    只认 `User-agent: *` / `User-agent: webtool` 段里的 Allow/Disallow,
    足够本地礼貌性遵守; 复杂匹配交给专业爬虫。
    """
    rules, active = [], False
    for raw in (txt or '').splitlines():
        line = raw.split('#', 1)[0].strip()
        if not line or ':' not in line:
            continue
        k, v = line.split(':', 1)
        k, v = k.strip().lower(), v.strip()
        if k == 'user-agent':
            active = v in ('*', 'webtool')
        elif k in ('allow', 'disallow') and active and v:
            rules.append((k == 'allow', v))
    return rules


def _rule_re(prefix):
    """robots.txt 的路径规则 → 正则: 支持 `*` 通配与结尾 `$` 锚定"""
    anchored = prefix.endswith('$')
    pat = prefix[:-1] if anchored else prefix
    rx = '.*'.join(re.escape(p) for p in pat.split('*'))
    return re.compile('^' + rx + ('$' if anchored else ''))


def robots_allows(rules, url):
    """最长匹配优先, 同长度 Allow 优先; 没有规则就放行

    比"只比前缀"多认两样真实站点常用的写法: `*` 通配和结尾 `$`。
    没有它们, `Disallow: /*.pdf$` 这类规则会被静默当成字面量从而失效。
    """
    if not rules:
        return True
    path = urlsplit(url).path or '/'
    best, verdict = -1, True
    for allow, prefix in rules:
        if not _rule_re(prefix).match(path):
            continue
        n = len(prefix)
        if n > best or (n == best and allow):
            best, verdict = n, allow
    return verdict


_RE_TITLE = re.compile(r'<title[^>]*>(.*?)</title>', re.I | re.S)


def host_of(url):
    return (urlsplit(url).hostname or '').lower()
