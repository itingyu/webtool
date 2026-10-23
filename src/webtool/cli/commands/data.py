"""cli 命令: 搜索 / 抓取 / AI / 站内 / 榜单 / 订阅 / 选股

从 app.py 拆出, 注册到共享的 Typer app。共享 plumbing 见 webtool.cli._ctx。
"""

import sys

import typer

from webtool.cli._ctx import (
    Fmt, NoCache, NoProxy, Output, _CTX, _do,
    _entry_fn, _run,
)
from webtool.cli.app import app
from webtool.cli.commands._group import make_group

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
               site: str = typer.Option(None, '-s', '--site',
                                        help='检索源: 站点 key 或引擎 key, 逗号分隔多个引擎 '
                                             '(清单: search -l)'),
               sources: bool = typer.Option(False, '-l', '--list',
                                            help='列出全部检索源 (多引擎 + 站内) 后退出'),
               lang: str = typer.Option('zh', '-L', '--lang',
                                        help='站内搜索的语言版本参数 (wikipedia 等)'),
               preset: str = typer.Option(None, '-p', '--preset',
                                          help='引擎组合预设 (webtool plugins engines presets 查看); '
                                               '优先级低于 -s 指定引擎'),
               max: int = typer.Option(8, '-n', '--limit', help='每引擎结果数'),
               fmt: str = Fmt, output: str = Output,
               no_proxy: bool = NoProxy, no_cache: bool = NoCache,
               operators: str = typer.Option('passthrough', '-O', '--operators',
                                             help='高级操作符路由: passthrough/strip/strict '
                                                  '(支持 site: intitle: inurl: -词)'),
               blocklist: str = typer.Option('', '-b', '--blocklist',
                                            help='黑名单覆盖: 逗号分隔域名, 前缀 ! 表白名单例外, '
                                                 '传 off 关闭黑名单'),
               jobs: int = typer.Option(None, '-j', '--jobs',
                                        help='并发抓取的源数 (默认=源数, 自动最多 4; 显式最高 16; 1=串行)'),
               since: str = typer.Option(None, '-S', '--since',
                                         help='起始: 相对 7d/2周/3个月/1y/today/yesterday '
                                              '或绝对 2026-10-01; 会下推给 google/bing/'
                                              'baidu/sogou 的原生时间参数; '
                                              '不填默认只搜近 15 天 (-A 取消)'),
               until: str = typer.Option(None, '-U', '--until',
                                         help='截止: 同上, 相对与绝对都认'),
               date_strict: bool = typer.Option(False, '--date-strict',
                                                help='认不出日期的结果也剔掉 (默认保留, '
                                                     '免得清空结果)'),
               all_time: bool = typer.Option(False, '-A', '--all-time',
                                             help='取消默认的"近 15 天"时间窗, 不限时间'),
               no_fallback: bool = typer.Option(False, '--no-fallback',
                                                help='关闭免 key 引擎降级: 主引擎结果不足时'
                                                     '不再补跑 marginalia/exa/firecrawl/parallel')):
    """搜索: 默认多引擎; `-s` 选站点或引擎, `-l` 列全部检索源"""
    a = _CTX['args']
    a.update = None
    engine = None

    def list_sources(args, cfg):
        import json as _json
        from webtool.engines.customsites import load_custom_sites
        from webtool.engines.status import listing
        from webtool.cli.sitesearch import sites_table
        engines = listing()
        sites = [{'site': k, 'desc': v['desc'], 'source': 'builtin'}
                 for k, v in sites_table().items()]
        for k, v in load_custom_sites().items():
            if v.get('_error'):
                sites.append({'site': k, 'desc': v['_error'],
                              'source': 'custom(BROKEN)'})
            else:
                sites.append({'site': k, 'desc': v.get('desc', ''),
                              'source': 'custom'})
        from webtool.net import intercept
        cool = {k: '%ds (此前%s)' % (v.left, v.why)
                for k, v in intercept.cooldowns().items()}
        if args.format == 'json':
            print(_json.dumps({'engines': engines, 'sites': sites,
                               'cooldowns': cool},
                              ensure_ascii=False, indent=1))
            return 0
        print('引擎 (%d):' % len(engines))
        for e in engines:
            print('  %-14s %s' % (e['engine'], e['desc']))
        print('\n站点 (%d):' % len(sites))
        for s in sites:
            print('  %-14s %s' % (s['site'], s['desc']))
        if cool:
            print('\n冷却中: ' + ', '.join('%s=%s' % (k, v)
                                          for k, v in cool.items()))
        print('\n用法: webtool search "词"                 # 默认引擎组合')
        print('      webtool search -s bing,sogou "词"   # 指定引擎')
        print('      webtool search -s github "词"       # 站内')
        return 0

    if sources:
        return _run('data', list_sources, fmt, output, False, False)

    from webtool.core import stdin as _stdin
    query = _stdin.read_input(query, required=True, what='搜索词')

    # 引擎和站点都是"检索源": 一个 -s 全包。多个引擎可逗号并列; 站点只能单选
    # (各站参数/返回结构不同, 混着搜没法统一渲染)。
    raw = site
    picked = [x.strip() for x in (raw or '').split(',') if x.strip()]
    if picked:
        from webtool.engines.status import listing as _listing
        from webtool.cli.sitesearch import sites_table as _sites
        from webtool.engines.customsites import load_custom_sites
        eng_names = [e['engine'] for e in _listing()]
        site_names = set(_sites()) | set(load_custom_sites())
        unknown = [x for x in picked if x not in eng_names and x not in site_names]
        if unknown:
            print('未知检索源: %s' % ', '.join(unknown), file=sys.stderr)
            print('用 `webtool search -l` 看全部源', file=sys.stderr)
            return 2
        # 引擎/站点不分工: 选中的源全部丢进 search 同一条管线并池 merge。
        eng = [x for x in picked if x in eng_names]
        sts = [x for x in picked if x not in eng_names]
        engine = ','.join(eng)
        a.sites, a.no_engines = sts, not eng
        a.lang = lang
    a.query, a.engine, a.preset, a.max = query, engine, preset, max
    a.operators, a.blocklist = operators, blocklist
    a.jobs = jobs
    a.since, a.until, a.date_strict = since, until, date_strict
    a.all_time = all_time
    a.no_fallback = no_fallback
    a.no_ad = True

    def fn(args, cfg):
        from webtool.pipeline.search import do_search
        return do_search(args, cfg)
    return _run('data', fn, fmt, output, no_cache, no_proxy)

@app.command('fetch')
def fetch_cmd(url: str = typer.Argument(None, help='要抓取的 URL'),
              url_file: str = typer.Option(None, '-u', '--url-file', help='从文件读多个 URL(每行一个)'),
              proxy: str = typer.Option(None, '-p', '--proxy',
                                        help='本次线路: auto(默认, 走规则表) / direct / '
                                             '代理名 (webtool proxy named list) / 完整 URL'),
              fmt: str = Fmt, output: str = Output,
              no_proxy: bool = NoProxy, no_cache: bool = NoCache,
              resume: bool = typer.Option(False, '-r', '--resume',
                                          help='多 URL 批任务断点续跑: 跳过上批已成功的 URL '
                                               '(按 URL 集合指纹记账)'),
              max_chars: int = typer.Option(0, '-c', '--max-chars', help='正文截断字符数, 0=不截断'),
              raw: bool = typer.Option(False, '-R', '--raw', help='跳过正文提取, 输出原始 HTML'),
              with_metadata: bool = typer.Option(False, '--with-metadata',
                                                 help='json 格式附带标题/作者/日期'),
              mark_untrusted: bool = typer.Option(False, '-M', '--mark-untrusted',
                                                  help='把正文裹进 <<<BEGIN-UNTRUSTED … >>> 边界再输出 '
                                                       '(喂给模型时区分"资料"与"指令")'),
              structured: bool = typer.Option(False, '-S', '--structured',
                                              help='顺带抽 JSON-LD/OpenGraph 结构化字段 (商品价格/评分/发布时间等)'),
              fields: str = typer.Option(None, '-F', '--fields',
                                         help='只要这些结构化字段, 逗号分隔 (如 name,price,availability); '
                                              '隐含 --structured, 支持 offers.price 这类路径'),
              links: bool = typer.Option(False, '-L', '--links',
                                         help='顺带抽出页面里的站内链接 (json 里给 links, 供 crawl 用)'),
              profile: str = typer.Option(None, '--profile',
                                          help='传输指纹档案: chrome131_win/mac/linux/android, '
                                               'safari18_4_ios 等 (移动站/拿不到数据时试 android/ios)'),
              jobs: int = typer.Option(1, '-j', '--jobs',
                                       help='下载用几条连接 (分片并发, 最多 4); '
                                            '默认 1 (对站点最客气), 大文件可 4; '
                                            '服务端不认 Range 会自动退回单连接'),
              progress: bool = typer.Option(None, '--progress/--no-progress',
                                            help='下载进度条; 默认只在终端里刷'
                                                 ' (管道/日志里只报结果, 不刷 \r)'),
              save: str = typer.Option(None, '-s', '--save',
                                       help='存到哪 (文件或目录); 网页存原始 HTML, '
                                            '二进制目标默认就存当前目录, 用它可以换落点'),
              extract: str = typer.Option(None, '-x', '--extract',
                                          help='正文提取器: auto(默认, 内容层择优, 最干净) / '
                                               'trafilatura / readability / boilerplate / '
                                               'inscriptis; 也可用 config set extract 固定'),
              via: str = typer.Option('local', '-v', '--via',
                                      help='取正文通道: local=本地提取链(默认, 免配额) / '
                                           'auto=本地失败时兜底远程 reader / '
                                           'parallel|exa|firecrawl=直接走对应 MCP 的 web_fetch'),
              pdf_pages: str = typer.Option(None, '-g', '--pdf-pages',
                                            help='PDF 只抽这几页 (如 "1-5" / "1,3,5-7"); '
                                                 '不给=全文。配合本地 PDF 文本抽取')):
    """抓取 URL 并提取正文

    `--url-file` 多 URL 时, 文本输出谁先抓完谁先出 (不排在慢链接后面);
    `-f json` 等全部收齐再输出 (半截数组不可解析)。
    """
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
            max_chars: int = typer.Option(4000, '-c', '--max-chars',
                                          help='单篇正文截断字符数 (默认 4000)'),
            site: str = typer.Option(None, '-s', '--site',
                                     help='检索源 (同 search -s, 可混选引擎与站点)'),
            preset: str = typer.Option(None, '--preset', help='引擎组合预设 (同 search)'),
            since: str = typer.Option(None, '-S', '--since',
                                      help='只要这个时间之后的资料 (同 search -S: 7d/2周/2026-10-01)'),
            until: str = typer.Option(None, '-U', '--until',
                                      help='只要这个时间之前的资料 (同 search -U)'),
            all_time: bool = typer.Option(False, '-A', '--all-time',
                                          help='取消默认的"近 15 天"时间窗 (同 search -A)'),
            model: str = typer.Option(None, '--model', help='模型 id (默认取 zen.json / big-pickle)'),
            retries: int = typer.Option(2, '--retries', help='模型调用瞬时故障重试次数'),
            stream: bool = typer.Option(True, '--stream/--no-stream',
                                        help='边生成边输出 (json 格式恒不流式)'),
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
    a.site, a.preset = site, preset
    a.since, a.until = since, until
    a.all_time = all_time
    a.model = model
    a.system = None
    a.retries = max(1, retries)
    a.stream = stream
    a.think = None
    a.max_tokens = None
    return _run('data', _entry_fn('ask'), fmt, output, no_cache, no_proxy)

diff_app = make_group(
    'diff', '页面版本对比: diff <a> [b] | diff save <url> | diff list | diff history <名> | diff rm <名>')


@diff_app.command('diff')
def _diff_run(left: str = typer.Argument(None,
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
              max_chars: int = typer.Option(0, '-c', '--max-chars',
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


def _snapshot_args(url=None, name=None, list_=False, history=None, rm=None,
                   max_chars=0):
    a = _CTX['args']
    a.url, a.name = url, name
    a.list, a.history, a.rm = list_, history, rm
    a.max_chars = max(0, max_chars)


@diff_app.command('save')
def _diff_save(url: str = typer.Argument(..., help='要存快照的 URL'),
               name: str = typer.Option(None, '--name',
                                        help='快照名 (默认从 URL 生成: 主机-路径)'),
               max_chars: int = typer.Option(0, '-c', '--max-chars',
                                             help='正文截断字符数, 0=不截断'),
               fmt: str = Fmt, output: str = Output,
               no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """存一版快照 (之后 `diff <快照名>` 看改了什么)"""
    _snapshot_args(url=url, name=name, max_chars=max_chars)
    return _run('data', _entry_fn('snapshot'), fmt, output, no_cache, no_proxy)


@diff_app.command('list')
def _diff_list(fmt: str = Fmt, output: str = Output):
    """列已有快照"""
    _snapshot_args(list_=True)
    return _run('data', _entry_fn('snapshot'), fmt, output, False, False)


@diff_app.command('history')
def _diff_history(name: str = typer.Argument(..., help='快照名'),
                  fmt: str = Fmt, output: str = Output):
    """列某个快照的全部版本"""
    _snapshot_args(history=name)
    return _run('data', _entry_fn('snapshot'), fmt, output, False, False)


@diff_app.command('rm')
def _diff_rm(name: str = typer.Argument(..., help='快照名'),
             fmt: str = Fmt, output: str = Output):
    """删掉一个快照 (连同各版本)"""
    _snapshot_args(rm=name)
    return _run('data', _entry_fn('snapshot'), fmt, output, False, False)


@diff_app.callback(invoke_without_command=True)
def _diff_root(ctx: typer.Context):
    """无参 = 打印用法 (需要左右两版)"""
    if ctx.invoked_subcommand is None:
        raise typer.Exit(_diff_run(
            left=None, right=None, context=3, ignore_ws=False, no_meta=False,
            max_lines=400, max_chars=0, fmt='txt', output=None,
            no_proxy=False, no_cache=False))


app.add_typer(diff_app, name='diff')

@app.command('compare')
def compare_cmd(urls: list[str] = typer.Argument(None,
                                                 help='要对比的 URL (至少 2 个)'),
                n: int = typer.Option(6, '-n', '--limit', help='每个来源取几条要点'),
                max_chars: int = typer.Option(0, '-c', '--max-chars',
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
              site: str = typer.Option(None, '-s', '--site',
                                       help='检索源 (同 search -s)'),
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
    a.engine, a.preset, a.since, a.until = site, preset, since, until
    a.name = name
    a.list, a.reset = list_, reset
    a.max_seen = max(50, max_seen)
    return _run('data', _entry_fn('watch'), fmt, output, no_cache, no_proxy)

@app.command('crawl')
def crawl_cmd(url: str = typer.Argument(None, help='起点 URL'),
              depth: int = typer.Option(2, '-d', '--depth', help='最多跟几层链接 (0=只抓这一页)'),
              max_pages: int = typer.Option(20, '-m', '--max-pages', help='最多抓多少页'),
              delay: float = typer.Option(0.5, '-w', '--delay', help='每页之间停几秒 (别把人家站打疼)'),
              include: str = typer.Option(None, '-i', '--include', help='只跟匹配这个正则的 URL'),
              exclude: str = typer.Option(None, '-X', '--exclude', help='跳过匹配这个正则的 URL'),
              any_host: bool = typer.Option(False, '-a', '--any-host', help='允许跨域名'),
              no_robots: bool = typer.Option(False, '-R', '--no-robots', help='不读 robots.txt'),
              max_chars: int = typer.Option(0, '-c', '--max-chars', help='每页正文截断字符数, 0=不截断'),
              save_dir: str = typer.Option(None, '-s', '--save', help='把每页存成 markdown 到这个目录'),
              fmt: str = Fmt, output: str = Output,
              no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """小站/文档站抓取: 从一页顺着站内链接爬有限几页

    默认同 host、遵守 robots.txt、页间隔 0.5s, 深度和页数都有硬上限 ——
    是"把一个文档站读下来"的工具, 不是通用爬虫。正文照旧走 fetch (含缓存/抽取)。
    文本/表格输出是一页抓到就打一页; `-f json` 等全部跑完再给完整数组。
    """
    a = _CTX['args']
    a.url, a.depth, a.max = url, depth, max(1, max_pages)
    a.delay, a.include, a.exclude = delay, include, exclude
    a.any_host, a.no_robots = any_host, no_robots
    a.max_chars, a.save_dir = max(0, max_chars), save_dir
    return _run('data', _entry_fn('crawl'), fmt, output, no_cache, no_proxy)

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

