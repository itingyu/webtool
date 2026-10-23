"""crawl: 从一个 URL 出发, 沿站内链接爬有限几页

深度/页数都有硬上限, 默认同 host + 遵守 robots.txt + 每页之间 sleep ——
是给"把某个小站/文档站抓下来"用的, 不是通用爬虫。
"""
import re
import sys
import time
from urllib.parse import urlsplit

from webtool.cli._bridge import cli_json
from webtool.core import links as _lk


def _fetch_page(url, max_chars):
    argv = ['fetch', url, '-f', 'json', '--links', '--with-metadata',
            '--max-chars', str(max(0, max_chars))]
    ok, data = cli_json(argv)
    if not ok or not isinstance(data, dict):
        return None
    return data


def _robots_rules(seed):
    """取一次 robots.txt; 取不到就当没有限制"""
    scheme = urlsplit(seed).scheme or 'https'
    host = _lk.host_of(seed)
    if not host:
        return []
    ok, data = cli_json(['fetch', '%s://%s/robots.txt' % (scheme, host),
                         '-f', 'json', '--max-chars', '200000'])
    if not ok or not isinstance(data, dict):
        return []
    txt = data.get('content') or ''
    return _lk.parse_robots(txt) if txt else []


def _norm(url):
    s = urlsplit(url)
    path = s.path or '/'
    if path != '/' and path.endswith('/'):
        path = path.rstrip('/')
    return '%s://%s%s' % (s.scheme.lower(), (s.hostname or '').lower(), path)


def _keep(url, args, inc, exc, host, rules):
    if inc and not inc.search(url):
        return False
    if exc and exc.search(url):
        return False
    if not getattr(args, 'any_host', False) and _lk.host_of(url) != host:
        return False
    if rules and not _lk.robots_allows(rules, url):
        return False
    return True


def do_crawl(args, cfg):
    seed = (getattr(args, 'url', '') or '').strip()
    if not seed:
        print('用法: webtool crawl <URL> [--depth 2] [--max-pages 20]', file=sys.stderr)
        return 2
    if not seed.startswith(('http://', 'https://')):
        seed = 'https://' + seed
    depth_max = max(0, getattr(args, 'depth', 2))
    page_max = max(1, getattr(args, 'max', 20))
    delay = max(0.0, float(getattr(args, 'delay', 0.5) or 0))
    max_chars = getattr(args, 'max_chars', 0)
    inc = re.compile(getattr(args, 'include')) if getattr(args, 'include', None) else None
    exc = re.compile(getattr(args, 'exclude')) if getattr(args, 'exclude', None) else None
    host = _lk.host_of(seed)
    rules = [] if getattr(args, 'no_robots', False) else _robots_rules(seed)

    # 文本/表格直接透传时, 抓到一页就打一页 (不必等整站跑完)
    fmt0 = getattr(args, 'format', 'text') or 'text'
    stream = fmt0 != 'json' and getattr(args, 'output', None) in (None, '-')
    if stream:
        print(('## 爬取 %s (深度 %d)\n' if fmt0 == 'markdown'
               else '爬取 %s (深度 %d)') % (seed, depth_max))

    def _say(i, page, url):
        if not stream:
            return
        if page and page.get('ok'):
            if fmt0 == 'markdown':
                print('%d. [%s](%s) — %d 字' % (i, page.get('title') or url,
                                                url, page.get('chars', 0)))
            else:
                print('[%d] %s  (%d 字)' % (i, page.get('title') or url,
                                           page.get('chars', 0)))
                print('    %s' % url)
        elif fmt0 == 'markdown':
            print('%d. × %s (抓取失败)' % (i, url))
        else:
            print('[×] %s  (抓取失败)' % url)

    queue = [(seed, 0)]
    seen = {_norm(seed)}
    pages, skipped = [], 0
    first = True
    while queue and len(pages) < page_max:
        url, depth = queue.pop(0)
        if not first and delay:
            time.sleep(delay)
        first = False
        data = _fetch_page(url, max_chars)
        if data is None:
            pages.append({'url': url, 'depth': depth, 'ok': False, 'chars': 0})
            _say(len(pages), None, url)
            continue
        meta = data.get('metadata') or {}
        title = (meta.get('title') or '').strip()
        text = data.get('content') or ''
        pages.append({'url': url, 'depth': depth, 'ok': bool(text),
                      'chars': len(text), 'title': title, 'content': text})
        _say(len(pages), pages[-1], url)
        if depth >= depth_max:
            continue
        for nxt in (data.get('links') or []):
            key = _norm(nxt)
            if key in seen:
                continue
            if not _keep(nxt, args, inc, exc, host, rules):
                skipped += 1
                continue
            seen.add(key)
            queue.append((nxt, depth + 1))
    return _emit_crawl(args, seed, depth_max, pages, len(seen), skipped,
                       streamed=stream)


def _slug(url, idx):
    s = urlsplit(url)
    raw = (s.path or '/').strip('/') or 'index'
    raw = re.sub(r'[^A-Za-z0-9._\u4e00-\u9fff-]+', '-', raw)[:60].strip('-')
    return '%02d-%s.md' % (idx, raw or 'page')


def _emit_crawl(args, seed, depth_max, pages, seen_n, skipped, streamed=False):
    ok_pages = [p for p in pages if p.get('ok')]
    saved = 0
    outdir = getattr(args, 'save_dir', None)
    if outdir:
        import os
        os.makedirs(outdir, exist_ok=True)
        for i, p in enumerate(ok_pages, 1):
            path = os.path.join(outdir, _slug(p['url'], i))
            head = '# %s\n\n%s\n' % (p.get('title') or p['url'], p['url'])
            try:
                with open(path, 'w', encoding='utf-8') as fh:
                    fh.write(head + '\n' + (p.get('content') or ''))
                saved += 1
            except OSError as e:
                print('crawl: 写 %s 失败: %s' % (path, e), file=sys.stderr)

    fmt = getattr(args, 'format', 'text') or 'text'
    if fmt == 'json':
        import json
        print(json.dumps({'seed': seed, 'depth': depth_max,
                          'pages': [{k: v for k, v in p.items() if k != 'content'}
                                    for p in pages],
                          'fetched': len(pages), 'ok_count': len(ok_pages),
                          'seen': seen_n, 'skipped': skipped, 'saved': saved},
                         ensure_ascii=False, indent=1))
    elif streamed:
        # 条目已经边抓边打, 这里只补总计
        if skipped:
            print('\n> 跳过 %d 个链接 (跨站/robots/规则不匹配)' % skipped)
        print('\n爬取 %d 页 (深度 %d, 见过 %d 个链接, 失败 %d)'
              % (len(ok_pages), depth_max, seen_n, len(pages) - len(ok_pages)))
        if saved:
            print('已存 %d 个文件到 %s' % (saved, outdir))
    elif fmt == 'markdown':
        print('## 爬取 %d 页 (深度 %d)\n' % (len(ok_pages), depth_max))
        for i, p in enumerate(ok_pages, 1):
            print('%d. [%s](%s) — %d 字' % (i, p.get('title') or p['url'],
                                            p['url'], p.get('chars', 0)))
        if skipped:
            print('\n> 跳过 %d 个链接 (跨站/robots/规则不匹配)' % skipped)
    else:
        print('爬取 %d 页 (种子 %s, 深度 %d, 见过 %d 个链接)'
              % (len(ok_pages), seed, depth_max, seen_n))
        for i, p in enumerate(ok_pages, 1):
            print('[%d] %s  (%d 字)' % (i, p.get('title') or p['url'], p.get('chars', 0)))
            print('    %s' % p['url'])
        bad = len(pages) - len(ok_pages)
        if bad:
            print('(%d 页抓取失败)' % bad)
        if skipped:
            print('(跳过 %d 个链接: 跨站/robots/规则不匹配)' % skipped)
        if saved:
            print('已存 %d 个文件到 %s' % (saved, outdir))
    return 0 if ok_pages else 2
