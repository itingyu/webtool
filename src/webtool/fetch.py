# -*- coding: utf-8 -*-
"""fetch: URL -> 纯净正文 (markdown/text/json/html)"""
import concurrent.futures as cf
import json
import re
import sys
import time
import urllib.parse

from . import cache
from .http import http_get


def do_fetch(args, cfg):
    urls = []
    if args.url_file:
        with open(args.url_file, encoding='utf-8') as f:
            urls = [x.strip() for x in f if x.strip() and not x.startswith('#')]
    elif args.url:
        urls = [args.url]
    if not urls:
        print('need url or --url-file', file=sys.stderr)
        return 2

    single = len(urls) == 1
    results = []
    proxy = cfg.get('fetch_proxy') if cfg.get('fetch_proxy') is not None else cfg.get('proxy')
    timeout = cfg.get('timeout', 15)

    def work(u):
        return _fetch_one(u, args, cfg, proxy, timeout)

    if single:
        results = [work(urls[0])]
    else:
        with cf.ThreadPoolExecutor(min(5, len(urls))) as ex:
            results = list(ex.map(work, urls))

    if args.format == 'json' and not single:
        print(json.dumps(results, ensure_ascii=False, indent=1))
    else:
        for r in results:
            _emit(r, args, single)
    return 0


def _fetch_one(url, args, cfg, proxy, timeout):
    t0 = time.time()
    ckey = f'{url}|{args.format}|{args.max_chars}'
    cached = None if (args.no_cache or args.raw) else cache.get(cfg, 'fetch', ckey)
    if cached is not None:
        cached['cache'] = 'hit'
        return cached
    try:
        from .resilient import fetch as rfetch
        html, status, via = rfetch(url, proxy=proxy, timeout=timeout)
    except Exception as e:
        return {'url': url, 'error': str(e)[:300], 'took_ms': int((time.time() - t0) * 1000)}
    if args.raw:
        return {'url': url, 'status': status, 'html': html, 'via': via,
                'took_ms': int((time.time() - t0) * 1000)}
    content, meta = _extract(html, url)
    if args.max_chars and content and len(content) > args.max_chars:
        content = content[:args.max_chars] + '\n…[truncated]'
    out = {'url': url, 'status': status, 'via': via, 'took_ms': int((time.time() - t0) * 1000),
           'chars': len(content or ''), 'content': content or ''}
    if args.with_metadata and args.format == 'json':
        out['metadata'] = meta
    if out['content']:
        cache.put(cfg, 'fetch', ckey, out)
    else:
        out['hint'] = 'extract empty: try --format html --raw or site needs JS'
    out['cache'] = 'miss'
    return out


def _extract(html, url):
    """trafilatura -> readability-lxml -> html2text 三级提取"""
    meta = {}
    # 1. trafilatura
    try:
        import trafilatura
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            md = trafilatura.extract(html, url=url, output_format='markdown',
                                     include_links=True, include_tables=True,
                                     with_metadata=True)
        if md and md.strip():
            m = None
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore')
                    m = trafilatura.bare_extraction(html, url=url, with_metadata=True,
                                                    only_with_metadata=False)
                if m and not isinstance(m, dict):
                    meta = {k: str(getattr(m, k)) for k in
                            ('title', 'author', 'date', 'sitename', 'description')
                            if getattr(m, k, None)}
                elif m:
                    meta = {k: str(m[k]) for k in
                            ('title', 'author', 'date', 'sitename', 'description')
                            if m.get(k)}
            except Exception:
                pass
            return md, meta
    except ImportError:
        pass
    except Exception:
        pass
    # 2. readability-lxml + html2text
    try:
        from readability import Document
        import html2text
        doc = Document(html)
        title = doc.short_title()
        if title:
            meta['title'] = title
        summ = doc.summary(html_partial=True)
        h = html2text.HTML2Text()
        h.body_width = 0
        h.ignore_images = True
        h.ignore_emphasis = False
        return h.handle(summ).strip(), meta
    except ImportError:
        pass
    except Exception:
        pass
    # 3. 保底: 全文文本
    try:
        import inscriptis
        return inscriptis.get_text(html), meta
    except Exception:
        return _basic_text(html), meta


def _basic_text(html):
    html = re.sub(r'<(script|style|noscript)[^>]*>.*?</\1>', '', html, flags=re.S | re.I)
    html = re.sub(r'<br[^>]*>|</p>|</div>|</h\d>', '\n', html, flags=re.I)
    txt = re.sub(r'<[^>]+>', '', html)
    import html as _h
    txt = _h.unescape(txt)
    txt = re.sub(r'\n{3,}', '\n\n', txt)
    txt = re.sub(r'[ \t]+', ' ', txt)
    return txt.strip()


def _emit(r, args, single):
    if 'error' in r:
        print(json.dumps(r, ensure_ascii=False), file=sys.stderr)
        return
    if args.format == 'json':
        print(json.dumps(r, ensure_ascii=False, indent=1))
    elif args.format == 'html':
        print(r.get('html', r.get('content', '')))
    elif args.format == 'text':
        import re as _re
        txt = _re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', r.get('content', ''))
        print(txt)
    else:  # markdown
        print(r.get('content', ''))
        if not single:
            print(f'\n---\nsource: {r["url"]} ({r.get("chars", 0)} chars, {r.get("cache", "?")})')
