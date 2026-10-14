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
from webtool.core import text
import webtool.engines.extractors as extractors

# 提取链世代: 提取算法换一代就 +1。缓存键里带着它, 换了算法就等于换了一套缓存,
# 免得把上一代留下的垃圾正文 (整页 dump 那种) 继续端给用户。
_EXTRACT_GEN = 'x2'


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
    # fetch_proxy 显式指定优先; 否则交给路由表按域名/IP/协议分流
    fp = cfg.get('fetch_proxy')
    proxy = fp if fp is not None else 'auto'
    timeout = cfg.get('timeout', 15)
    via = (getattr(args, 'via', None) or 'local').lower()
    if via not in _VIA_CHANNELS:
        print(f'unknown --via {via!r}, available: {",".join(sorted(_VIA_CHANNELS))}',
              file=sys.stderr)
        return 2
    # 正文提取器: 命令行给的错值当场报错 (当场打的字值得立刻纠正), 配置里的错值
    # 静默退回 auto (config set 本来就按白名单校验, 剩下的是手改文件的场景)
    cli_extract = getattr(args, 'extract', None)
    if cli_extract and cli_extract.strip().lower() not in extractors.MODES:
        print(f'unknown --extract {cli_extract!r}, available: '
              f'{",".join(extractors.MODES)}', file=sys.stderr)
        return 2
    extract_mode = extractors.resolve_mode(cli_extract or cfg.get('extract'))

    def work(u):
        # 显式指定远程通道时直接走 reader, 不试本地链 (用户已表明意图)
        if via in _MCP_CHANNELS:
            return _fetch_via_mcp(u, args, cfg, via, timeout, proxy=proxy)
        local = _fetch_one(u, args, cfg, proxy, timeout, extract_mode)
        # auto: 仅在本地链明确搞不定时才花配额, 不做启发式猜测
        if via == 'auto' and not getattr(args, 'raw', False) and _needs_reader(local):
            for ch in _MCP_CHANNELS:
                if ch == 'auto':
                    continue
                got = _fetch_via_mcp(u, args, cfg, ch, timeout, prior=local,
                                     proxy=proxy)
                if not got.get('error'):
                    got['via_local_error'] = local.get('error', '')
                    return got
        return local

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


_VIA_CHANNELS = ('local', 'auto', 'parallel', 'exa', 'firecrawl')
_MCP_CHANNELS = ('parallel', 'exa', 'firecrawl')


def _needs_reader(local):
    """本地链是否明确搞不定 —— 只认确定性硬失败信号, 不做启发式猜测。

    这三个信号都是"纯 HTTP 拿不到正文"的既定事实, 也是远程 reader 真正
    擅长 (JS 渲染 / 反爬 / 付费墙) 的场景。内容薄但非壳页的不算 —— 那多半
    是页面本身短, 花配额去重读大概率也白花。
    """
    if local.get('error'):
        return True
    content = local.get('content') or ''
    return not content or _is_nav_shell(content)


def _reader_arg(channel, url):
    """各端点 web_fetch 的参数形状不同"""
    return {'firecrawl': {'url': url}}.get(channel, {'urls': [url]})


def _reader_text(channel, raw):
    """把 web_fetch 的返回转成正文。

    三个端点形状不同, 必须分派:
    - firecrawl 返回 JSON ({markdown: "..."})
    - parallel 返回 JSON ({results:[{title, excerpts:[...]}]}), 要取出 excerpts
    - exa 返回已拼好的 markdown 纯文本, 原样用
    """
    raw = (raw or '').strip()
    if not raw:
        return ''
    if channel not in ('parallel', 'firecrawl'):
        return raw
    try:
        d = json.loads(raw)
    except (TypeError, ValueError):
        return raw                      # 非 JSON 就当纯文本, 不丢内容
    if not isinstance(d, dict):
        return raw
    if channel == 'firecrawl':
        md = d.get('markdown')
        if isinstance(md, str) and md.strip():
            return md
        data = d.get('data')
        if isinstance(data, dict):
            md = data.get('markdown')
            if isinstance(md, str) and md.strip():
                return md
        return raw
    items = d.get('results') if isinstance(d, dict) else (d if isinstance(d, list) else [])
    parts = []
    for it in (items or []):
        if not isinstance(it, dict):
            continue
        title = (it.get('title') or '').strip()
        ex = it.get('excerpts') or []
        if isinstance(ex, str):
            ex = [ex]
        body = '\n\n'.join(x.strip() for x in ex if isinstance(x, str) and x.strip())
        if not body:
            continue
        parts.append(f'# {title}\n{body}' if title else body)
    return '\n\n---\n\n'.join(parts)


def _fetch_via_mcp(url, args, cfg, channel, timeout, prior=None, proxy=None):
    """走 MCP 端点的 web_fetch 拿 token-efficient markdown。

    与本地链的差别: 对方用浏览器集群取回页面, 能过 JS 渲染与大部分反爬;
    代价是每次调用消耗端点配额 (Parallel 匿名免 key 但有速率上限)。

    proxy 传进来而不是自己定: 远程 reader 和本地链打的是同一次请求的
    两个出口, 线路该一致 (都按配置 + 路由表)。曾经这里不传, call_verb 的
    默认值 proxy=None 生效 —— `--via exa/parallel/firecrawl` 无论怎么配
    代理都直连, 而本地链却走代理, 同一个 URL 两条出口两种 IP。
    """
    t0 = time.time()
    tool_arg = _reader_arg(channel, url)
    try:
        from webtool.net import mcpclient as mc
        r = mc.call_verb(channel, 'fetch', tool_arg,
                         timeout=max(timeout or 0, 30),
                         proxy=proxy if proxy is not None else 'auto')
    except Exception as e:
        return {'url': url, 'via': f'mcp:{channel}', 'took_ms': int((time.time() - t0) * 1000),
                'error': f'mcp 调用失败: {str(e)[:200]}'}
    took = int((time.time() - t0) * 1000)
    if 'error' in r:
        code = (r['error'] or {}).get('code')
        msg = r['error'].get('message') if isinstance(r['error'], dict) else str(r['error'])
        out = {'url': url, 'via': f'mcp:{channel}', 'took_ms': took,
               'error': f'{channel} reader 失败 (code={code}): {str(msg)[:200]}'}
        if prior and prior.get('error'):
            out['via_local_error'] = prior['error']
        out['hint'] = ('远程 reader 需要网络与端点配额; 可试 --via local 走本地提取链, '
                       '或换 URL')
        return out
    content = _reader_text(channel, r.get('text'))
    if r.get('is_error') or not content:
        out = {'url': url, 'via': f'mcp:{channel}', 'took_ms': took, 'chars': 0,
               'content': '', 'error': f'{channel} reader 返回空正文'}
        if prior and prior.get('error'):
            out['via_local_error'] = prior['error']
        return out
    if args.max_chars and len(content) > args.max_chars:
        content = content[:args.max_chars] + '\n…[truncated]'
    out = {'url': url, 'via': f'mcp:{channel}', 'took_ms': took,
           'chars': len(content), 'content': content,
           'extract': f'mcp-{channel}-web_fetch'}
    if prior and prior.get('error'):
        out['via_local_error'] = prior['error']
    return out


def _fetch_one(url, args, cfg, proxy, timeout, extract_mode='auto'):
    t0 = time.time()
    # via 进 key: 同一 URL 走本地链与走远程 reader 是两种产出, 共用缓存会串
    # 尾部的提取代数: 提取链换算法后要作废旧缓存, 否则公布出去的是上次的垃圾正文
    ckey = (f'{url}|{args.format}|{args.max_chars}|'
            f'{getattr(args, "via", "") or "local"}|{_EXTRACT_GEN}'
            f'|{extract_mode}')
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
    content, meta = _extract(html, url, extract_mode)
    js_shell = meta.pop('_js_shell', None)
    extract_via = meta.pop('_via', '')
    _warn_missing(meta.pop('_missing', None))
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
    out = {'url': url, 'status': status, 'via': via, 'extract': extract_via,
           'took_ms': int((time.time() - t0) * 1000),
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


def _extract(html, url, mode='auto'):
    """提取器策略链 (见 extractors.py): 壳页预检 → 按 mode 取正文"""
    if extractors.is_js_shell(html):
        return '', {'_js_shell': '1', 'title': ''}
    return extractors.run_chain(html, url, {}, mode=mode)


_warned_missing = set()


def _warn_missing(missing):
    """提取器缺依赖时提示一次 (stderr)

    静默降级最坑人: 用户看到满屏广告会以为 webtool 提取就这水平, 其实是少装
    了一个库、主力提取器根本没上场。提示走 stderr, 不污染 stdout 的正文。
    """
    for name in (missing or []):
        if name in _warned_missing:
            continue
        _warned_missing.add(name)
        try:
            from webtool.core import deps
            how = deps.install_hint(name)
        except Exception:
            how = f'缺 {name}'
        print(f'提示: 提取链缺 {name}, 这次用的是还装着的提取器 —— {how}',
              file=sys.stderr)


def _emit(r, args, single):
    if 'error' in r:
        print(json.dumps(r, ensure_ascii=False), file=sys.stderr)
        return
    if args.format == 'json':
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return
    # --raw 的产出放在 'html' 而不是 'content' —— 以前只在 json 分支认它, 于是
    # `fetch --raw` (默认 md/txt) 打出个空行还退出码 0: 说好的原始 HTML 一个字没有。
    body = r['html'] if 'html' in r else r.get('content', '')
    if args.format == 'text' and 'html' not in r:
        # 只抹 [文字](url) 是不够的: `## 标题` `**重点**` `| 表格 |` 会原样留下,
        # 说好的纯文本到手还是 markdown。走 core.text.md_to_text 统一处理。
        body = text.md_to_text(body)
    print(body)
    if args.format != 'text' and not single and 'html' not in r:
        print(f'\n---\nsource: {r["url"]} ({r.get("chars", 0)} chars, {r.get("cache", "?")})')
