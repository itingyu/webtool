"""cli 命令: 搜索 / 抓取 / AI / 站内 / 榜单 / 订阅 / 选股

从 app.py 拆出, 注册到共享的 Typer app。共享 plumbing 见 webtool.cli._ctx。
"""

import typer

from webtool.cli._ctx import (
    Fmt, NoCache, NoProxy, Output, _CTX, _do,
    _entry_fn, _run,
)
from webtool.cli.app import app

@app.command('pydata')
def pydata_cmd(qual: str = typer.Argument(None,
                                           help='外部库函数全限定名: akshare.stock_zh_a_hist_pre_min_em / '
                                                'efinance.stock.get_quote_history / 深模块路径也行'),
               payload: str = typer.Argument(None,
                                             help='实参: JSON dict → kwargs / JSON list → 位置参数 / 其他 → 单个位置参数'),
               lib: str = typer.Option('akshare', '--lib',
                                       help='qual 不带包名时用这个补全: akshare/efinance/adata/qstock...'),
               timeout: int = typer.Option(15, '--timeout', help='单请求超时秒'),
               pace_ms: int = typer.Option(120, '--pace-ms',
                                           help='相邻请求最小间隔 (防突发限流), 0=关'),
               rows: int = typer.Option(30, '-n', '--limit',
                                        help='text/csv 模式下最多打印多少行 (json 全量)'),
               fmt: str = Fmt, output: str = Output,
               no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """外部金融库任意函数, 走 webtool 传输层出网 (chrome 指纹/代理路由/限流重试)

    requests 原生成网会被站点掐 (python-requests UA + 无指纹), 这里把
    requests.Session.request 整个替换掉再调库, 业务代码零改动:

      webtool pydata akshare.stock_zh_a_hist '{"symbol":"600519","period":"daily",
        "start_date":"20251001","end_date":"20251020","adjust":"qfq"}' -f text
      webtool pydata efinance.stock.get_quote_history '["600519",101]' -f json
    """
    a = _CTX['args']
    a.no_cache = no_cache or _CTX['no_cache']
    a.no_proxy = no_proxy

    def fn(args, cfg):
        from webtool.net.pyshim import call_py
        import json as _json
        if not qual:
            print('用法: webtool pydata 库.函数 实参JSON  (akshare/efinance/adata/qstock '
                  '装哪个用哪个);  例: webtool pydata akshare.stock_zh_a_hist '
                  "'{\"symbol\":\"600519\",\"period\":\"daily\"}'")
            return 2
        pay = payload
        if pay in (None, '-'):
            import sys as _sys
            pay = _sys.stdin.read() if not _sys.stdin.isatty() else None
        if pay:
            try:
                parsed = _json.loads(pay) if pay[:1] in ('{', '[') else pay
            except ValueError:
                parsed = pay
        else:
            parsed = None
        try:
            res = call_py(qual, parsed, lib=lib, timeout=timeout, pace_ms=pace_ms)
        except Exception as e:                        # noqa: BLE001
            print(f'✗ {type(e).__name__}: {e}')
            return 1
        f = args.format
        if f == 'json':
            print(_json.dumps(res, ensure_ascii=False))
            return 0
        if res['kind'] == 'dataframe':
            import pandas as _pd
            df = _pd.DataFrame(res['rows'], columns=res['columns'])
            if f == 'csv':
                print(df.head(rows).to_csv(index=False), end='')
            else:
                print(f'{res["module"]}.{res["func"]}  {res["n"]} 行  '
                      f'{res["elapsed_s"]}s  (经 webtool 指纹通道)')
                print(df.head(rows).to_string(index=False, max_colwidth=28))
                if res['n'] > rows:
                    print(f'… 共 {res["n"]} 行, -f json 出全量')
        else:
            print(_json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    return _run('data', fn, fmt, output, no_cache, no_proxy)

@app.command('search')
def search_cmd(query: str = typer.Argument(None, help='搜索词 (留空时从 stdin 读一行, 如 echo 词 | webtool search -)'),
               engine: str = typer.Option(None, '-e', '--engine',
                                          help='逗号分隔的引擎 key: bing, sogou, google, baidu, so360, marginalia, '
                                                'exa, parallel, firecrawl (webtool engines 看状态)'),
               preset: str = typer.Option(None, '--preset',
                                          help='引擎组合预设 (webtool engines presets 查看); 优先级低于 --engine'),
               max: int = typer.Option(8, '-n', '--limit', help='每引擎结果数'),
               fmt: str = Fmt, output: str = Output,
               no_proxy: bool = NoProxy, no_cache: bool = NoCache,
               operators: str = typer.Option('passthrough', '--operators',
                                             help='高级操作符路由: passthrough/strip/strict '
                                                  '(支持 site: intitle: inurl: -词)'),
               blocklist: str = typer.Option('',
                                            help='黑名单覆盖: 逗号分隔域名, 前缀 ! 表白名单例外, '
                                                 '传 off 关闭黑名单'),
               jobs: int = typer.Option(None, '-j', '--jobs',
                                        help='并发抓取的源数 (默认=源数, 自动最多 4; 显式最高 16; 1=串行)'),
               since: str = typer.Option(None, '--since',
                                         help='只要这个时间之后的: YYYY-MM-DD 或 7d/2w/3m/1y '
                                              '(关键词引擎不给日期, 从标题摘要里认)'),
               until: str = typer.Option(None, '--until',
                                         help='只要这个时间之前的 (只认 YYYY-MM-DD)'),
               date_strict: bool = typer.Option(False, '--date-strict',
                                                help='认不出日期的结果也剔掉 (默认保留, '
                                                     '免得清空结果)'),
               no_fallback: bool = typer.Option(False, '--no-fallback',
                                                help='关闭免 key 引擎降级: 主引擎结果不足时'
                                                     '不再补跑 marginalia/exa/firecrawl/parallel')):
    """多引擎网页搜索"""
    a = _CTX['args']
    a.update = None
    from webtool.core import stdin as _stdin
    query = _stdin.read_input(query, required=True, what='搜索词')
    a.query, a.engine, a.preset, a.max = query, engine, preset, max
    a.operators, a.blocklist = operators, blocklist
    a.jobs = jobs
    a.since, a.until, a.date_strict = since, until, date_strict
    a.no_fallback = no_fallback
    a.no_ad = True

    def fn(args, cfg):
        from webtool.pipeline.search import do_search
        return do_search(args, cfg)
    return _run('data', fn, fmt, output, no_cache, no_proxy)

@app.command('fetch')
def fetch_cmd(url: str = typer.Argument(None, help='要抓取的 URL'),
              url_file: str = typer.Option(None, '--url-file', help='从文件读多个 URL(每行一个)'),
              proxy: str = typer.Option(None, '--proxy',
                                        help='本次线路: auto(默认, 走规则表) / direct / '
                                             '代理名 (webtool proxy named list) / 完整 URL'),
              fmt: str = Fmt, output: str = Output,
              no_proxy: bool = NoProxy, no_cache: bool = NoCache,
              resume: bool = typer.Option(False, '--resume',
                                          help='多 URL 批任务断点续跑: 跳过上批已成功的 URL '
                                               '(按 URL 集合指纹记账)'),
              max_chars: int = typer.Option(0, '--max-chars', help='正文截断字符数, 0=不截断'),
              raw: bool = typer.Option(False, '--raw', help='跳过正文提取, 输出原始 HTML'),
              with_metadata: bool = typer.Option(False, '--with-metadata',
                                                 help='json 格式附带标题/作者/日期'),
              mark_untrusted: bool = typer.Option(False, '--mark-untrusted',
                                                  help='把正文裹进 <<<BEGIN-UNTRUSTED … >>> 边界再输出 '
                                                       '(喂给模型时区分"资料"与"指令")'),
              structured: bool = typer.Option(False, '--structured',
                                              help='顺带抽 JSON-LD/OpenGraph 结构化字段 (商品价格/评分/发布时间等)'),
              fields: str = typer.Option(None, '--fields',
                                         help='只要这些结构化字段, 逗号分隔 (如 name,price,availability); '
                                              '隐含 --structured, 支持 offers.price 这类路径'),
              links: bool = typer.Option(False, '--links',
                                         help='顺带抽出页面里的站内链接 (json 里给 links, 供 crawl 用)'),
              profile: str = typer.Option(None, '--profile',
                                          help='传输指纹档案: chrome131_win/mac/linux/android, '
                                               'safari18_4_ios 等 (移动站/拿不到数据时试 android/ios)'),
              jobs: int = typer.Option(1, '--jobs',
                                       help='下载用几条连接 (分片并发, 最多 4); '
                                            '默认 1 (对站点最客气), 大文件可 4; '
                                            '服务端不认 Range 会自动退回单连接'),
              progress: bool = typer.Option(None, '--progress/--no-progress',
                                            help='下载进度条; 默认只在终端里刷'
                                                 ' (管道/日志里只报结果, 不刷 \r)'),
              save: str = typer.Option(None, '--save',
                                       help='存到哪 (文件或目录); 网页存原始 HTML, '
                                            '二进制目标默认就存当前目录, 用它可以换落点'),
              extract: str = typer.Option(None, '--extract',
                                          help='正文提取器: auto(默认, 内容层择优, 最干净) / '
                                               'trafilatura / readability / boilerplate / '
                                               'inscriptis; 也可用 config set extract 固定'),
              via: str = typer.Option('local', '--via',
                                      help='取正文通道: local=本地提取链(默认, 免配额) / '
                                           'auto=本地失败时兜底远程 reader / '
                                           'parallel|exa|firecrawl=直接走对应 MCP 的 web_fetch'),
              pdf_pages: str = typer.Option(None, '--pdf-pages',
                                            help='PDF 只抽这几页 (如 "1-5" / "1,3,5-7"); '
                                                 '不给=全文。配合本地 PDF 文本抽取')):
    """抓取 URL 并提取正文"""
    a = _CTX['args']
    a.url, a.url_file = url, url_file
    a.proxy = proxy
    a.max_chars, a.raw, a.with_metadata, a.profile = max_chars, raw, with_metadata, profile
    a.mark_untrusted = mark_untrusted
    a.structured, a.fields = structured, fields
    a.links, a.links_same_host = links, True
    a.extract = extract
    a.save = save
    a.progress = progress
    a.jobs = jobs
    a.via = via
    a.resume = resume
    a.pdf_pages = pdf_pages
    return _run('data', _do('fetch'), fmt, output, no_cache, no_proxy)

@app.command('ask')
def ask_cmd(question: list[str] = typer.Argument(None,
                                                 help='要问的问题, 如 webtool ask "长征九十周年有哪些纪念活动"'),
            num: int = typer.Option(8, '-n', '--limit',
                                    help='搜索取多少条 (默认 8)'),
            sources: int = typer.Option(4, '--sources',
                                        help='最多读几篇正文 (默认 4; 抓不到正文的退回搜索摘要)'),
            max_chars: int = typer.Option(4000, '--max-chars',
                                          help='单篇正文截断字符数 (默认 4000)'),
            engine: str = typer.Option(None, '-e', '--engine',
                                       help='搜索引擎 (同 search -e; 默认走默认预设)'),
            preset: str = typer.Option(None, '--preset', help='引擎组合预设 (同 search)'),
            since: str = typer.Option(None, '--since',
                                      help='只要这个时间之后的资料 (同 search --since)'),
            until: str = typer.Option(None, '--until',
                                      help='只要这个时间之前的资料 (同 search --until)'),
            model: str = typer.Option(None, '--model', help='模型 id (默认取 zen.json / big-pickle)'),
            retries: int = typer.Option(2, '--retries', help='模型调用瞬时故障重试次数'),
            fmt: str = Fmt, output: str = Output,
            no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """先检索再作答: 搜索 → 抓正文 → 归纳, 每条结论带来源 URL

    与 `zen` 的区别是**答案必须可核**: 只依据本次检索到的资料作答, 逐条标注
    [n] 对应文末来源; 检索不到资料就直接回"没查到", 不拿模型记忆充数。
    """
    a = _CTX['args']
    a.question = ' '.join(question).strip() if question else ''
    a.num = max(1, num)
    a.sources = max(1, sources)
    a.max_chars = max(200, max_chars)
    a.engine, a.preset = engine, preset
    a.since, a.until = since, until
    a.model = model
    a.system = None
    a.retries = max(1, retries)
    a.think = None
    a.max_tokens = None
    return _run('data', _entry_fn('ask'), fmt, output, no_cache, no_proxy)

@app.command('snapshot')
def snapshot_cmd(url: str = typer.Argument(None, help='要存快照的 URL'),
                 name: str = typer.Option(None, '--name',
                                          help='快照名 (默认从 URL 生成: 主机-路径)'),
                 list_: bool = typer.Option(False, '--list', help='列出已有快照'),
                 history: str = typer.Option(None, '--history',
                                             help='列出某个快照的全部版本'),
                 rm: str = typer.Option(None, '--rm', help='删掉某个快照'),
                 max_chars: int = typer.Option(0, '--max-chars',
                                               help='正文截断字符数, 0=不截断'),
                 fmt: str = Fmt, output: str = Output,
                 no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """页面快照: 存一版正文, 之后可 diff 出"变了什么\""""
    a = _CTX['args']
    a.url, a.name = url, name
    a.list, a.history, a.rm = list_, history, rm
    a.max_chars = max(0, max_chars)
    return _run('data', _entry_fn('snapshot'), fmt, output, no_cache, no_proxy)

@app.command('diff')
def diff_cmd(left: str = typer.Argument(None,
                                        help='旧: 快照名 / URL / 本地文件'),
             right: str = typer.Argument(None,
                                         help='新: 快照名 / URL / 本地文件 (省略则比该快照最近两版)'),
             context: int = typer.Option(3, '-C', '--context',
                                         help='差异上下文行数 (默认 3)'),
             ignore_ws: bool = typer.Option(False, '-w', '--ignore-ws',
                                            help='忽略行内空白差异'),
             no_meta: bool = typer.Option(False, '--no-meta',
                                          help='比正文时去掉开头的 YAML 元数据头 (跨 URL 对比时常需要)'),
             max_lines: int = typer.Option(400, '--max-lines',
                                           help='text/markdown 最多打印多少差异行'),
             max_chars: int = typer.Option(0, '--max-chars',
                                           help='抓 URL 时正文截断字符数, 0=不截断'),
             fmt: str = Fmt, output: str = Output,
             no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """对比两版页面/文件; 退出码 0=相同 1=有差异 2=出错"""
    a = _CTX['args']
    a.left, a.right = left, right
    a.context = max(0, context)
    a.ignore_ws, a.max_lines = ignore_ws, max(10, max_lines)
    a.no_meta = no_meta
    a.max_chars = max(0, max_chars)
    a.version = None
    return _run('data', _entry_fn('diff'), fmt, output, no_cache, no_proxy)


@app.command('compare')
def compare_cmd(urls: list[str] = typer.Argument(None,
                                                 help='要对比的 URL (至少 2 个)'),
                n: int = typer.Option(6, '-n', '--limit', help='每个来源取几条要点'),
                max_chars: int = typer.Option(0, '--max-chars',
                                              help='抓取时正文截断字符数, 0=不截断'),
                fmt: str = Fmt, output: str = Output,
                no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """多源并排对比: 几个 URL 各讲了什么, 哪些是共有的, 哪些是独有的"""
    a = _CTX['args']
    a.urls = list(urls or [])
    a.n = max(1, n)
    a.max_chars = max(0, max_chars)
    a.timeout = None
    return _run('data', _entry_fn('compare'), fmt, output, no_cache, no_proxy)

@app.command('watch')
def watch_cmd(target: list[str] = typer.Argument(None,
                                                help='关键词 (默认) 或榜单源名 (--kind rank)'),
              kind: str = typer.Option('search', '--kind',
                                       help='search=关键词检索 / rank=热榜'),
              num: int = typer.Option(20, '-n', '--limit', help='每次取多少条'),
              engine: str = typer.Option(None, '-e', '--engine', help='搜索引擎 (同 search -e)'),
              preset: str = typer.Option(None, '--preset', help='引擎组合预设 (同 search)'),
              since: str = typer.Option(None, '--since', help='只看这个时间之后 (同 search)'),
              until: str = typer.Option(None, '--until', help='只看这个时间之前 (同 search)'),
              name: str = typer.Option(None, '--name',
                                       help='桶名 (默认按参数哈希; 换参数就是另一个桶)'),
              list_: bool = typer.Option(False, '--list', help='列出已有桶与上次运行'),
              reset: bool = typer.Option(False, '--reset', help='清空该桶的已见记录'),
              max_seen: int = typer.Option(500, '--max-seen',
                                           help='每桶最多记多少条已见 (默认 500)'),
              fmt: str = Fmt, output: str = Output,
              no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """增量监控: 同一句检索反复跑, 只报"上次之后新出现的"

    适合挂定时任务: `webtool watch "关键词"` 有新增时退出码 1, 拿来决定要不要
    发通知。状态在 ~/.webtool/watch_state.json, 首次运行那批算基线。
    """
    a = _CTX['args']
    a.target = ' '.join(target).strip() if target else ''
    a.kind = (kind or 'search').strip().lower()
    a.num = max(1, num)
    a.engine, a.preset, a.since, a.until = engine, preset, since, until
    a.name = name
    a.list, a.reset = list_, reset
    a.max_seen = max(50, max_seen)
    return _run('data', _entry_fn('watch'), fmt, output, no_cache, no_proxy)

@app.command('crawl')
def crawl_cmd(url: str = typer.Argument(None, help='起点 URL'),
              depth: int = typer.Option(2, '--depth', help='最多跟几层链接 (0=只抓这一页)'),
              max_pages: int = typer.Option(20, '--max-pages', help='最多抓多少页'),
              delay: float = typer.Option(0.5, '--delay', help='每页之间停几秒 (别把人家站打疼)'),
              include: str = typer.Option(None, '--include', help='只跟匹配这个正则的 URL'),
              exclude: str = typer.Option(None, '--exclude', help='跳过匹配这个正则的 URL'),
              any_host: bool = typer.Option(False, '--any-host', help='允许跨域名'),
              no_robots: bool = typer.Option(False, '--no-robots', help='不读 robots.txt'),
              max_chars: int = typer.Option(0, '--max-chars', help='每页正文截断字符数, 0=不截断'),
              save_dir: str = typer.Option(None, '--save', help='把每页存成 markdown 到这个目录'),
              fmt: str = Fmt, output: str = Output,
              no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """小站/文档站抓取: 从一页顺着站内链接爬有限几页

    默认同 host、遵守 robots.txt、页间隔 0.5s, 深度和页数都有硬上限 ——
    是"把一个文档站读下来"的工具, 不是通用爬虫。正文照旧走 fetch (含缓存/抽取)。
    """
    a = _CTX['args']
    a.url, a.depth, a.max = url, depth, max(1, max_pages)
    a.delay, a.include, a.exclude = delay, include, exclude
    a.any_host, a.no_robots = any_host, no_robots
    a.max_chars, a.save_dir = max(0, max_chars), save_dir
    return _run('data', _entry_fn('crawl'), fmt, output, no_cache, no_proxy)

@app.command('site')
def site_cmd(site: str = typer.Argument(None, help='站点 key, `webtool site list` 查看全部'),
             query: str = typer.Argument(None, help='站内搜索词'),
             max: int = typer.Option(10, '-n', '--limit', help='返回条数'),
             lang: str = typer.Option('zh', '--lang', help='wikipedia 语言版本'),
             since: str = typer.Option(None, '--since',
                                       help='只要这个时间之后的 (YYYY-MM-DD 或 7d/2w/3m/1y)'),
             until: str = typer.Option(None, '--until',
                                       help='只要这个时间之前的 (只认 YYYY-MM-DD)'),
             fmt: str = Fmt, output: str = Output,
             no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """站内搜索: 各站官方接口 (站点清单 webtool site list)"""
    from webtool.core import stdin as _stdin
    a = _CTX['args']
    query = _stdin.read_input(query, what='站内搜索词')
    a.site, a.query, a.max, a.lang = site, query, max, lang
    a.since, a.until = since, until
    return _run('data', _entry_fn('site'), fmt, output, no_cache, no_proxy)

@app.command('rank')
def rank_cmd(sources: list[str] = typer.Argument(None, help='榜单源 key; 无参数 = 榜单清单+用法'),
             query: str = typer.Option(None, '-q', '--query',
                                       help='语义筛选词: 支持搜索的源透传站内过滤, 其余源拉榜后本地 BM25 筛选+跨源重排'),
             threshold: float = typer.Option(0.15, '-t', '--threshold',
                                             help='语义筛选阈值 0-1 (默认 0.15; 0=只列清单不过滤不重排)'),
             max: int = typer.Option(10, '-n', '--limit', help='每源条数'),
             no_url: bool = typer.Option(False, '--no-url',
                                         help='输出不带链接: 去掉每条的 url 字段 (markdown/text 只留标题)'),
             cluster: bool = typer.Option(False, '--cluster',
                                          help='跨源事件聚类: 把各榜单里讲同一件事的条目并成一条, '
                                               '按涉及平台数排 (看真实热度用这个)'),
             fmt: str = Fmt, output: str = Output,
             no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """榜单聚合: 无参=榜单清单; 指定源=按源分组原序; -q 语义筛选; --cluster 跨源事件聚类"""
    a = _CTX['args']
    # 默认值不能是 []: click 8.1.x 的 nargs=-1 参数带非 None default 直接 TypeError (老 typer 上炸)
    a.sources, a.query, a.threshold, a.max = sources or [], query, threshold, max
    a.no_url = no_url
    a.cluster = cluster
    return _run('data', _entry_fn('rank'), fmt, output, no_cache, no_proxy)

