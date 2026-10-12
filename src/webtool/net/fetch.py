"""fetch: URL -> 纯净正文 (markdown/text/json/html)
提取链: trafilatura → readability-lxml → html2text → 保底全文; 桌面指纹
拿到壳页/过薄页时自动切移动指纹重试一次。
"""
import concurrent.futures as cf
import json
import re
import sys
import time

from webtool.core import cache
import webtool.engines.extractors as extractors


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
        from webtool.core.resilient import fetch as rfetch
        profile = getattr(args, 'profile', None)
        html, status, via = rfetch(url, proxy=proxy, timeout=timeout,
                                   profile=profile)
        if not getattr(args, 'profile', None):
            # 桌面指纹拿到的像壳页/过薄, 自动切移动指纹再试一次 (按 UA 分流站点)
            thin = len(html or '') < 6000 or not _spa_marker(html)
            if thin:
                try:
                    h2, s2, v2 = rfetch(url, proxy=proxy, timeout=timeout,
                                        profile='chrome131_android')
                    if len(h2) > len(html) * 1.5:
                        html, status, via = h2, s2, f'{v2}+mobile-fallback'
                except Exception:
                    pass
    except Exception as e:
        return {'url': url, 'error': str(e)[:300], 'took_ms': int((time.time() - t0) * 1000)}
    if args.raw:
        return {'url': url, 'status': status, 'html': html, 'via': via,
                'took_ms': int((time.time() - t0) * 1000)}
    content, meta = _extract(html, url)
    js_shell = meta.pop('_js_shell', None)
    thin = not content or len(content) < 150 or _is_nav_shell(content)
    if js_shell or thin or _looks_spa(html):
        # SPA 页: 收割内嵌 state (SSR JSON); 采用条件是明显优于现有产出
        # (>= 2x 且 >= 300 字), 防止用列表/配置噪声盖掉正常正文
        try:
            from webtool.net import spa
            md, note = spa.harvest(html, url)
        except Exception:
            md, note = '', None
        if md and len(md) >= max(300, 2 * len(content or '')):
            content = md
            if args.max_chars and len(content) > args.max_chars:
                content = content[:args.max_chars] + '\n…[truncated]'
            out = {'url': url, 'status': status, 'via': via,
                   'took_ms': int((time.time() - t0) * 1000),
                   'chars': len(content), 'content': content,
                   'extract': 'embedded-state'}
            if note:
                out['spa_note'] = note
            if args.with_metadata and args.format == 'json':
                out['metadata'] = meta
            cache.put(cfg, 'fetch', ckey, out)
            out['cache'] = 'miss'
            return out
    if js_shell:
        return {'url': url, 'status': status, 'via': via,
                'took_ms': int((time.time() - t0) * 1000), 'chars': 0,
                'content': '',
                'error': 'JS-only shell page: 内容由 JavaScript 渲染, 纯 HTTP 拿不到正文',
                'hint': '需要 JS 渲染的页面; 可试: ①该站的 WWW 版而非 M 版 '
                        '②移动端 UA: --profile chrome131_android '
                        '③site 子命令站点适配器'}
    if _looks_spa(html) and _is_nav_shell(content or ''):
        # SPA 页提取产物只是导航/页脚噪声 (下载引导页/登录墙等), 诚实报错
        return {'url': url, 'status': status, 'via': via,
                'took_ms': int((time.time() - t0) * 1000), 'chars': 0,
                'content': '',
                'error': '导航壳页: 该 URL 只有导航/下载引导, 无正文数据',
                'hint': '可试: ①该站的正式内容页而非首页壳 ②--profile chrome131_android '
                        '换移动指纹 ③搜索引擎搜标题拿正文页 URL'}
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


def _spa_marker(html):
    """内嵌 SSR state 特征 (供自动降级判断)"""
    return bool(re.search(
        r'id="RENDER_DATA"|__NEXT_DATA__|__NUXT__|__INITIAL_STATE__'
        r'|__PRELOADED_STATE__|>(?:%7B|%7b|%5B|%5b)[^<]{2000,}',
        html[:200000]))


def _looks_spa(html):
    """是否带内嵌 SSR state 的 SPA 页 (供空正文时决定要不要收割)"""
    return bool(re.search(
        r'id="RENDER_DATA"|window\.(__NEXT_DATA__|__NUXT__|__INITIAL_STATE__'
        r'|__INITIAL_DATA__|__PRELOADED_STATE__)|>(?:%7B|%7b|%5B|%5b)[^<]{2000,}',
        html[:400000]))


# 导航壳页特征: 提取出的是导航栏/页脚级噪声 (app 下载页, 登录墙等),
# 不是正文 —— 极短 + 模板词, 用于收紧 thin 判定
_NAV_SHELL_RE = re.compile(
    r'打开APP|APP内打开|下载.{0,4}APP|打开.{0,4}应用|登录.{0,4}后.{0,6}(查看|继续)'
    r'|产品功能|隐私政策|权限列表|ICP备|粤ICP|京ICP', re.I)


def _is_nav_shell(content):
    """提取产物是否导航壳噪声: 极短文本 + 模板词, 或 < 90 字符"""
    body = re.sub(r'^---[\s\S]*?---', '', content or '').strip()  # 去 YAML 头
    body = re.sub(r'\s+', '', body)
    if len(body) < 90:
        return True
    return len(body) < 260 and bool(_NAV_SHELL_RE.search(body))


def _extract(html, url):
    """提取器策略链 (见 extractors.py): 壳页预检 → 按优先级降级"""
    if extractors.is_js_shell(html):
        return '', {'_js_shell': '1', 'title': ''}
    return extractors.run_chain(html, url, {})


def _emit(r, args, single):
    if 'error' in r:
        print(json.dumps(r, ensure_ascii=False), file=sys.stderr)
        return
    if args.format == 'json':
        print(json.dumps(r, ensure_ascii=False, indent=1))
    elif args.format == 'text':
        import re as _re
        txt = _re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', r.get('content', ''))
        print(txt)
    else:  # markdown
        print(r.get('content', ''))
        if not single:
            print(f'\n---\nsource: {r["url"]} ({r.get("chars", 0)} chars, {r.get("cache", "?")})')
