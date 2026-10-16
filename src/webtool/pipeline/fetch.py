"""fetch: URL -> 纯净正文 (markdown/text/json/html)
提取链: trafilatura → readability-lxml → html2text → 保底全文; 桌面指纹
拿到壳页/过薄页时自动切移动指纹重试一次。
"""
import concurrent.futures as cf
import json
import mimetypes
import os
import re
import sys
import time
from urllib.parse import unquote, urlparse

from webtool.dao import cache
from webtool.core import text
import webtool.engines.extractors as extractors
from webtool.core.logging import get_logger

logger = get_logger(__name__)

# 提取链世代: 提取算法换一代就 +1。缓存键里带着它, 换了算法就等于换了一套缓存,
# 免得把上一代留下的垃圾正文 (整页 dump 那种) 继续端给用户。
_EXTRACT_GEN = 'x2'

# 目标类型判定
# fetch 老的假设是"你要的就是网页"。但 URL 后面可能是图片/视频/压缩包/API,
# 拿它们当 HTML 走提取链只会得到一堆乱码。先按响应头 (Content-Type) 认类型:
# 认得出就不必再猜, 也不必浪费一次提取。
_TEXT_MIME = {
    'application/json', 'application/ld+json', 'application/x-ndjson',
    'application/xml', 'application/rss+xml', 'application/atom+xml',
    'application/javascript', 'application/x-javascript', 'application/x-yaml',
}
_BIN_MIME = {
    'application/pdf': 'pdf',
    'application/zip': 'archive', 'application/x-tar': 'archive',
    'application/gzip': 'archive', 'application/x-7z-compressed': 'archive',
    'application/x-rar-compressed': 'archive', 'application/x-bzip2': 'archive',
    'application/x-xz': 'archive', 'application/vnd.rar': 'archive',
    'application/x-gzip': 'archive', 'application/x-zip-compressed': 'archive',
    'application/x-zip': 'archive', 'application/x-bzip': 'archive',
    'application/x-compressed-tar': 'archive',
    'application/vnd.android.package-archive': 'binary',
    'application/octet-stream': 'binary', 'application/x-msdownload': 'binary',
}
_RAW_MAX_BYTES = 32 * 1024 * 1024   # 文本类目标上限 (json/xml 可能很大)
_HTML_MAX_BYTES = 8 * 1024 * 1024   # 网页整段读的上限; 二进制没这个限制 (流式落盘)

_EXT_MIME = {                     # 服务端不报类型时的退路: 看扩展名
    '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.gif': 'image/gif', '.webp': 'image/webp', '.svg': 'image/svg+xml',
    '.bmp': 'image/bmp', '.ico': 'image/x-icon', '.avif': 'image/avif',
    '.mp4': 'video/mp4', '.webm': 'video/webm', '.mov': 'video/quicktime',
    '.mkv': 'video/x-matroska', '.avi': 'video/x-msvideo',
    '.mp3': 'audio/mpeg', '.m4a': 'audio/mp4', '.wav': 'audio/wav',
    '.flac': 'audio/flac', '.ogg': 'audio/ogg',
    '.pdf': 'application/pdf', '.zip': 'application/zip', '.tar': 'application/x-tar',
    '.gz': 'application/gzip', '.tgz': 'application/gzip', '.7z': 'application/x-7z-compressed',
    '.rar': 'application/x-rar-compressed', '.bz2': 'application/x-bzip2',
    '.xz': 'application/x-xz', '.xz2': 'application/x-xz',
    '.woff': 'font/woff', '.woff2': 'font/woff2', '.ttf': 'font/ttf',
    '.exe': 'application/x-msdownload', '.apk': 'application/vnd.android.package-archive',
    '.json': 'application/json', '.txt': 'text/plain', '.csv': 'text/csv',
    '.xml': 'application/xml', '.js': 'application/javascript',
}


def target_kind(ctype, url=''):
    """按响应头 (拿不到就看扩展名) 判断目标是什么, 返回 (kind, mime)

    kind: html / text / image / video / audio / pdf / archive / font / binary
    html 才走正文提取; text 原样给; 其余是二进制, 落盘或只报元信息。

    头里没类型也没认得的扩展名时按 html 处理 —— fetch 的入口就是 URL, 绝大多数
    情况是网页, 不能因为对方没报 Content-Type 就放弃正文提取。
    """
    mime = (ctype or '').split(';')[0].strip().lower()
    if mime in ('text/html', 'application/xhtml+xml'):
        return 'html', mime
    if mime.startswith('text/') or mime in _TEXT_MIME:
        return 'text', mime
    if mime in _BIN_MIME:
        return _BIN_MIME[mime], mime
    if mime.startswith(('image/', 'video/', 'audio/', 'font/')):
        return mime.split('/')[0], mime
    if mime:
        return 'binary', mime
    path = urlparse(url or '').path
    guess = _EXT_MIME.get(os.path.splitext(path)[1].lower(), '')
    if guess:
        return target_kind(guess)
    return 'html', ''


def _decode(data, headers):
    """按响应头 charset 解原始字节: 先信 Content-Type 里的 charset, 没写按 utf-8;

    utf-8 解出一堆替换字符 (中文站常见 GBK 老页面) 再试 gbk。
    """
    if isinstance(data, str):
        return data
    ctype = headers.get('content-type', '') or ''
    m = re.search(r'charset=["\']?([\w-]+)', ctype, re.I)
    enc = m.group(1) if m else 'utf-8'
    try:
        out = data.decode(enc, 'replace')
    except LookupError:
        out = data.decode('utf-8', 'replace')
    if out.count('\ufffd') > len(out) / 200:            # 0.5% 以上是坏字: 换 gbk
        try:
            alt = data.decode('gbk', 'replace')
        except Exception:
            return out
        if alt.count('\ufffd') < out.count('\ufffd'):
            return alt
    return out


def _filename_for(headers, url, mime=''):
    """落盘要存成什么名: URL 末段说了算 —— 后缀跟 URL 一致

    后缀不能由 Content-Type 决定: 服务端报 octet-stream 时, 只有 URL 末段知道
    这是 .whl 还是 .zip; 而 CD 给的 filename 有服务端乱填的 (download.aspx 之类),
    所以顺序是 URL 末段 > Content-Disposition > MIME 推。URL 没后缀才按 MIME 补。
    """
    seg = urlparse(url or '').path.rstrip('/')
    name = unquote(os.path.basename(seg))
    if not name:
        cd = headers.get('content-disposition') or ''
        m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", cd, re.I)
        name = unquote(m.group(1).strip()) if m else ''
    name = re.sub(r'[\\/:*?"<>|]+', '_', name).strip('. ') or 'download'
    if '.' not in name:                   # 没后缀 (或无末段) 才按 MIME 补一个
        kind, t = target_kind(headers.get('content-type'), url)
        name += mimetypes.guess_extension(mime or t or '') or ''
    return name


def _save_body(args, url, data, headers, status=200, mime='', dest=None):
    """把原始响应体写盘, 返回绝对路径 (不写就返回空)

    网页与二进制共用这一个出口: 存的一律是这次请求拿到的原始字节。二进制目标不给
    --save 也要落盘 (终端糊不下图片视频压缩包), dest 就是那个默认落点。
    """
    save = getattr(args, 'save', None) or dest
    if not save:
        return ''
    if status and status >= 400:
        # 404 页面按 URL 末段命名会变成 main.zip —— 打开才知道里面是 "Not Found"。
        # 错就是错, 别往盘上写文件; 真要那具错误页就用 --raw。
        print(f'不落盘: 响应 {status} (内容多半是错误页, 要它加 --raw)', file=sys.stderr)
        return ''
    path = save
    if os.path.isdir(save) or save.endswith(('/', '\\')):
        path = os.path.join(save, _filename_for(headers, url, mime))
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(data if isinstance(data, bytes) else data.encode('utf-8', 'replace'))
    except OSError as e:
        print(f'落盘失败: {e}', file=sys.stderr)
        return ''
    return os.path.abspath(path)


def _dest_path(args, url, headers=None, mime=''):
    """二进制存哪: --save 给了就听它的 (目录拼名字/否则当文件名), 没给存当前目录

    headers 为 None 表示"响应头还没到", 此时只能按 URL 末段取名 —— 续传判断必须
    在发请求之前做完 (Range 得随请求头一起发), 所以先按 URL 定落点, 名字定不下来
    (URL 没末段) 就老老实实不续传, 等响应头到了再由 Content-Disposition 定名。
    """
    save = getattr(args, 'save', None)
    if save:
        if not (os.path.isdir(save) or save.endswith(('/', '\\'))):
            return save
        return os.path.join(save, _filename_for(headers or {}, url, mime))
    return os.path.join('.', _filename_for(headers or {}, url, mime))


def _read_capped(resp, cap):
    """把流读完 (最多 cap 字节) 再关掉 —— 网页/文本要的是整段, 不是文件"""
    buf = bytearray()
    try:
        for c in resp.iter_content(65536):
            buf += c
            if len(buf) >= cap:
                break
    except Exception:
        logger.debug('忽略异常 (容忍路径)', exc_info=True)
    finally:
        try:
            resp.close()
        except Exception:
            pass
    return bytes(buf[:cap])


def _file_result(url, r, kind, mime, status, via, t0):
    """把下载器的结果折成 fetch 的结果形状 (元信息 + 落点, 二进制不进正文)"""
    out = {'url': url, 'kind': kind, 'type': mime or 'application/octet-stream',
           'extract': 'raw-binary', 'status': r.get('status', status),
           'via': r.get('via', via), 'took_ms': int((time.time() - t0) * 1000)}
    for k in ('file', 'size', 'resumed_from', 'partial', 'jobs'):
        if r.get(k) is not None:
            out[k] = r[k]
    if r.get('error'):
        out['error'] = r['error']
    return out


def _text_result(url, data, status, via, headers, kind, mime, args, t0):
    """文本类目标 (json/xml/纯文本): 原样给, 不提取

    走不到这里就说明它不是网页 —— 拿 JSON 去跑正文提取, 出来的是被抹掉标点的
    残渣。二进制目标也不走这里: 它们由 download 流式落盘 (见 _file_result)。
    """
    out = {'url': url, 'status': status, 'via': via, 'kind': kind,
           'type': mime or 'text/plain', 'size': len(data),
           'extract': 'raw-text', 'took_ms': int((time.time() - t0) * 1000)}
    total = headers.get('content-length')
    if total and total.isdigit() and int(total) > len(data):
        out['truncated'] = True              # 被单次上限截了
        out['size_declared'] = int(total)
    txt = data.decode('utf-8', errors='replace')
    if args.max_chars and len(txt) > args.max_chars:      # 0 = 不截断
        txt = txt[:args.max_chars] + '\n…[truncated]'
    out['content'] = txt
    return out


def _resolve_cli_proxy(val, cfg):
    """--proxy 取值归一: auto / direct / 命名代理名 / 完整 URL"""
    from webtool.net import rules as _R
    if val in ('auto', 'direct'):
        return val
    r = _R.router(cfg)
    if val in (r.proxies or {}):
        spec = r.proxies[val]
        return spec.get('url') if isinstance(spec, dict) else spec
    if '://' in val:
        return val
    known = ', '.join(sorted(r.proxies or {})) or '(无)'
    raise SystemExit(f"error: --proxy 未知代理名 {val!r}; 现有: {known}\n"
                     "也可给完整 URL (http://... / socks5://...) 或 direct/auto")


def do_fetch(args, cfg):
    urls = []
    if args.url_file:
        with open(args.url_file, encoding='utf-8') as f:
            urls = [x.strip() for x in f if x.strip() and not x.startswith('#')]
    else:
        # stdin 兜底: `cat urls.txt | webtool fetch -`(或无参且被管道喂着)。
        # read_input 统一口径: 显式参数 > '-' 管道 > 无参管道; parse_lines
        # 跳空行与 # 注释, 与 --url-file 同款。
        from webtool.core import stdin as _stdin
        urls = _stdin.parse_lines(_stdin.read_input(args.url))
    if not urls:
        print('need url or --url-file', file=sys.stderr)
        return 2

    single = len(urls) == 1

    # 断点续跑 (R9): 批任务挂掉重跑, 已成功的条目不再花网络。按 URL 集合
    # 指纹记账 —— 同一批 URL 共享一个 checkpoint, 换一批互不干扰。
    cp = None
    if getattr(args, 'resume', False) and not single:
        import hashlib
        from webtool.core.resilient import Checkpoint
        cp = Checkpoint('fetch-' + hashlib.md5(
            '\n'.join(sorted(urls)).encode()).hexdigest()[:10])
        done_n = len(urls) - len(cp.pending(urls))
        if done_n:
            print(f'[resume] 跳过已完成 {done_n}/{len(urls)}', file=sys.stderr)
        urls = cp.pending(urls)
        if not urls:
            print('[resume] 本批全部已完成', file=sys.stderr)
            return 0
    results = []
    # 'auto' = 路由表按域名/IP/协议分流; --proxy 可临时点名或强制直连
    proxy = 'auto'
    cli_proxy = getattr(args, 'proxy', None)
    if cli_proxy:
        proxy = _resolve_cli_proxy(cli_proxy, cfg)
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
        from webtool.core.resilient import MAX_WORKERS
        with cf.ThreadPoolExecutor(min(MAX_WORKERS, len(urls))) as ex:
            results = list(ex.map(work, urls))

    if cp is not None:
        for u, r in zip(urls, results):
            if not r.get('error'):
                cp.done(u)

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

    proxy 传进来而不是自己定: 远程 reader 和本地链打的是同一次请求的两个出口,
    线路必须一致 (都按配置 + 路由表), 否则同一个 URL 两条出口两种 IP。
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
    from webtool.core.resilient import open_stream
    from webtool.net import download as dl
    profile = getattr(args, 'profile', None)
    # 落点先按 URL 定 (续传要在请求头里带 Range, 只能提前决定); URL 没末段就先空着
    hint = _filename_for({}, url)
    dest = _dest_path(args, url) if hint != 'download' else ''
    start, validator = dl.resume_state(dest, url) if dest else (0, '')
    try:
        # 流式开: 先只拿响应头, 按 Content-Type 认清目标是什么, 再决定怎么读 ——
        # 网页/文本整段读进内存, 二进制边收边写盘 (含续传与进度)。
        resp, status, via, headers = open_stream(
            url, proxy=proxy, timeout=timeout, profile=profile,
            headers=dl.request_headers(start, validator))
    except Exception as e:
        return {'url': url, 'error': str(e)[:300], 'took_ms': int((time.time() - t0) * 1000)}
    kind, mime = target_kind(headers.get('content-type'), url)
    if kind not in ('html', 'text'):
        r = dl.download(
            url, dest or _dest_path(args, url, headers, mime),
            lambda h: open_stream(url, proxy=proxy, timeout=timeout, profile=profile,
                                  headers=h),
            progress=getattr(args, 'progress', None),
            jobs=max(1, getattr(args, 'jobs', 1) or 1), t0=t0,
            opened=None if start else (resp, status, via, headers))
        return _file_result(url, r, kind, mime, status, via, t0)
    if start:
        # 之前给这个 URL 留过半截 .part, 但这次服务端说是网页/文本: Range 头会
        # 只给我们半页, 重开一次不带 Range 的
        try:
            resp.close()
        except Exception:
            pass
        resp, status, via, headers = open_stream(url, proxy=proxy, timeout=timeout,
                                                 profile=profile)
    payload = _read_capped(resp, _HTML_MAX_BYTES if kind == 'html' else _RAW_MAX_BYTES)
    if kind == 'text':
        return _text_result(url, payload, status, via, headers, kind, mime, args, t0)
    html = _decode(payload, headers)
    saved = _save_body(args, url, payload, headers, status)
    try:
        if not getattr(args, 'profile', None):
            # 桌面指纹拿到的像壳页/过薄, 自动切移动指纹再试一次 (按 UA 分流站点)
            thin = len(html or '') < 6000 or not _spa_marker(html)
            if thin:
                try:
                    r2, s2, v2, h2 = open_stream(url, proxy=proxy, timeout=timeout,
                                                 profile='chrome131_android')
                    p2 = _decode(_read_capped(r2, _HTML_MAX_BYTES), h2)
                    if len(p2) > len(html) * 1.5:
                        html, status, via = p2, s2, f'{v2}+mobile-fallback'
                except Exception:
                    pass
    except Exception:
        logger.debug('忽略异常 (容忍路径)', exc_info=True)
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
                   'extract': 'embedded-state', **({'file': saved} if saved else {})}
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
           'chars': len(content or ''), 'content': content or '',
           **({'file': saved} if saved else {})}
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
    if 'content' not in r and 'html' not in r:
        # 图片/视频/压缩包之类: 二进制绝不往终端吐 (会糊一屏控制字符, 管道里更是垃圾),
        # 默认就存成文件, 这里只报"是什么、多大、存哪了"。
        line = f'[非网页] {r.get("type", "?")} · {r.get("size", 0)} 字节 · {r["url"]}'
        if r.get('truncated'):
            line += (f'\n  未落盘: 单次上限内只收到 {r.get("size")} 字节'
                     f' (声明 {r.get("size_declared")}), 截断的残件不如不存')
        if r.get('file'):
            line += f'\n  已存: {r["file"]}'
        else:
            line += '\n  没落盘 (原因见上一条); 换落点用 --save <文件或目录>'
        print(line, file=sys.stderr)
        return
    # --raw 的产出放在 'html' 而不是 'content' —— 各格式分支都得认它
    if r.get('file'):
        print(f'已存: {r["file"]}', file=sys.stderr)
    body = r['html'] if 'html' in r else r.get('content', '')
    if args.format == 'text' and 'html' not in r and r.get('extract') not in (
            'raw-text', 'raw-binary'):
        # 只抹 [文字](url) 是不够的: `## 标题` `**重点**` `| 表格 |` 会原样留下,
        # 说好的纯文本到手还是 markdown。走 core.text.md_to_text 统一处理, 并且
        # 连 YAML 元数据头一起去掉 —— 正文纯文本前面不该顶一段机器头, 要元数据
        # 走 `-f json`。
        body = text.md_to_text(body, keep_meta=False)
    print(body)
    if args.format != 'text' and not single and 'html' not in r:
        print(f'\n---\nsource: {r["url"]} ({r.get("chars", 0)} chars, {r.get("cache", "?")})')
