"""cli 命令: 搜索 / 抓取 / AI / 站内 / 榜单 / 订阅 / 选股

从 app.py 拆出, 注册到共享的 Typer app。共享 plumbing 见 webtool.cli._ctx。
"""

import typer

from webtool.cli._ctx import (
    Fmt, NoCache, NoProxy, Output, _CTX, _do,
    _entry_fn, _norm_think, _run,
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
               rows: int = typer.Option(30, '-n', '--rows',
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
               max: int = typer.Option(8, '-n', '--max', help='每引擎结果数'),
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
                                                     '免得清空结果)')):
    """多引擎网页搜索"""
    a = _CTX['args']
    a.update = None
    from webtool.core import stdin as _stdin
    query = _stdin.read_input(query, required=True, what='搜索词')
    a.query, a.engine, a.preset, a.max = query, engine, preset, max
    a.operators, a.blocklist = operators, blocklist
    a.jobs = jobs
    a.since, a.until, a.date_strict = since, until, date_strict
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
    a.extract = extract
    a.save = save
    a.progress = progress
    a.jobs = jobs
    a.via = via
    a.resume = resume
    a.pdf_pages = pdf_pages
    return _run('data', _do('fetch'), fmt, output, no_cache, no_proxy)

@app.command('zen')
def zen_cmd(prompt: list[str] = typer.Argument(None, help='要问的问题 (留空则走 --list-models)'),
            model: str = typer.Option(None, '--model',
                                      help='模型 id (不带 provider 前缀; 见 zen --list-models; 默认取 zen.json 的 model, 再回落 big-pickle)'),
            system: str = typer.Option(None, '--system',
                                       help='system prompt (分类器只验 role:system 存在, 不读内容)'),
            tool_choice: str = typer.Option(None, '--tool-choice',
                                            help='是否允许模型调工具; 默认 auto (闸门判据, 改 none 会被拒)'),
            tools: str = typer.Option(None, '--tools',
                                      help='工具集: min(默认, 闸门最小集 bash+read) / all / 逗号清单 (如 bash,read,grep)'),
            max_tokens: int = typer.Option(None, '--max-tokens',
                                           help='回复上限 token (默认取 zen.json 的 max_tokens, 再回落 200000)'),
            list_models: bool = typer.Option(False, '--list-models', help='列出 /v1/models 的全部 id'),
            list_free: bool = typer.Option(False, '--list-free',
                                           help='只列免费层 id (按命名约定筛, 不是保证)'),
            check: bool = typer.Option(False, '--check',
                                       help='真调一次验证可用性 (默认只验免费层)'),
            check_all: bool = typer.Option(False, '--check-all',
                                           help='连收费模型一起验 (80+ 个, 慢且易被上游限流); 自带 --check'),
            refresh: bool = typer.Option(False, '--refresh', help='绕过 1h 模型清单缓存'),
            dry_run: bool = typer.Option(False, '--dry-run',
                                         help='打印将要发出的请求 (URL + 请求头 + 请求体), 不联网'),
            show: str = typer.Option(None, '--show',
                                     help='只看请求的一段 (不联网): request / headers / body / text'),
            show_body: bool = typer.Option(False, '--show-body', hidden=True,
                                           help='(旧名) 同 --show body'),
            show_text: bool = typer.Option(False, '--show-text', hidden=True,
                                           help='(旧名) 同 --show text'),
            all_tools: bool = typer.Option(False, '--all-tools', hidden=True,
                                           help='(旧名) 同 --tools all'),
            live: bool = typer.Option(None, '--live/--no-live', '--stream/--no-stream',
                                      help='边收边打印 (默认开, 仅终端里生效); --no-live 攒到最后一次输出'),
            show_reasoning: bool = typer.Option(True, '--reasoning/--no-reasoning',
                                                help='打印思考过程 (默认开); --no-reasoning 只要答案 (不改请求体)'),
            think: str = typer.Option(None, '--think', '--reasoning-effort',
                                      help='思考强度 (透传上游 reasoning_effort; 可选值随模型而异, 如 low/medium/high; 默认 medium, off 则不带该字段)'),
            retries: int = typer.Option(2, '--retries', help='瞬时故障 (连接错/408/429/5xx) 重试次数; 退避指数 2/4/8s'),
            limits: bool = typer.Option(False, '--limits',
                                        help='列出记住的模型输出上限 (上游在 400 里报过的; 不联网)'),
            forget_limits: bool = typer.Option(False, '--forget-limits',
                                               help='忘掉记住的上限; 配合 --model 只忘那一个, 否则全忘'),
            sticky: bool = typer.Option(True, '--sticky/--no-sticky',
                                        help='固定会话 id, 按整点轮换 (默认开); --no-sticky 每次运行换新'),
            agent: bool = typer.Option(False, '--agent',
                                       help='多轮工具循环: 模型调工具 → 本地执行 → 结果回喂 → 再问, 直到给出答案'),
            agent_tools: str = typer.Option(None, '--agent-tools',
                                            help='agent 能用的工具 (逗号清单; 默认 read,glob,grep,websearch,webfetch)'),
            agent_max_steps: int = typer.Option(20, '--agent-max-steps',
                                                help='agent 最多几轮模型请求 (默认 20; 到顶如实报停)'),
            agent_max_chars: int = typer.Option(8000, '--agent-max-chars',
                                                help='单次工具输出回喂给模型的字数上限 (默认 8000, 超出截断)'),
            workspace: str = typer.Option(None, '--workspace', '-w',
                                          help='agent 工作空间目录 (默认当前目录); read/glob/grep 只能碰里面, AGENTS.md 会进 system'),
            session: str = typer.Option(None, '--session',
                                        help='命名会话 (首次自动创建, 存 ~/.webtool/zen_sessions/<名>.json); 同名再跑即接着聊'),
            continue_session: bool = typer.Option(False, '--continue',
                                                  help='接最近一条会话 (一般配合 --agent)'),
            sessions: bool = typer.Option(False, '--sessions',
                                          help='列出保存的会话 (不联网)'),
            clear_session: bool = typer.Option(False, '--clear-session',
                                               help='删掉 --session 指的会话 (不给则删最近一条)'),
            fmt: str = Fmt, output: str = Output,
            no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """OpenCode Zen 对话 (OpenAI 兼容, 公开模式, 无需 key)"""
    a = _CTX['args']
    # 默认值优先级: 命令行 > ~/.webtool/zen.json 的 zen 段 > 内置 (见 zenproto.DEFAULTS)
    from webtool.cli import zenproto as _zp
    dfl = _zp.defaults()
    a.prompt = ' '.join(prompt) if prompt else ''
    a.model = model or dfl['model']
    a.model_explicit = bool(model)      # --forget-limits 只清点名那个才需要它
    a.limits, a.forget_limits = limits, forget_limits
    a.system = system if system is not None else dfl['system']
    a.tool_choice = tool_choice or dfl['tool_choice']
    a.tools = 'all' if all_tools else (tools or dfl['tools'])
    a.max_tokens = max_tokens or dfl['max_tokens']
    a.list_models, a.list_free = list_models, list_free
    a.check = check or check_all          # --check-all 单独给也生效
    a.check_all, a.refresh = check_all, refresh
    a.dry_run, a.show = dry_run, show
    a.stream = dfl['live'] if live is None else live
    a.show_body, a.show_text = show_body, show_text
    a.retries, a.sticky = retries, sticky
    a.agent = agent
    a.agent_tools = agent_tools
    # 步数/输出上限取正数: 0 或负数会让循环一轮都不跑/立刻截断, 那是没配好不是用法
    a.agent_max_steps = max(1, agent_max_steps)
    a.agent_max_chars = max(200, agent_max_chars)
    a.workspace = workspace
    a.session, a.continue_session = session, continue_session
    a.sessions, a.clear_session = sessions, clear_session
    a.reasoning = show_reasoning
    a.think = _norm_think(think if think is not None else dfl['reasoning_effort'])
    return _run('data', _entry_fn('zen'), fmt, output, no_cache, no_proxy)

@app.command('ask')
def ask_cmd(question: list[str] = typer.Argument(None,
                                                 help='要问的问题, 如 webtool ask "长征九十周年有哪些纪念活动"'),
            num: int = typer.Option(8, '-n', '--num',
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

@app.command('site')
def site_cmd(site: str = typer.Argument(None, help='站点 key, `webtool site list` 查看全部'),
             query: str = typer.Argument(None, help='站内搜索词'),
             max: int = typer.Option(10, '-n', '--max', help='返回条数'),
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
             max: int = typer.Option(10, '-n', '--max', help='每源条数'),
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

@app.command('feed')
def feed_cmd(sources: list[str] = typer.Argument(None, help='feed key 或任意 RSS/Atom URL; 无参数 = 清单+用法'),
             max: int = typer.Option(10, '-n', '--max', help='每源条数'),
             query: str = typer.Option(None, '-q', '--query', help='语义筛选词 (BM25 本地筛 + 按相关度重排)'),
             threshold: float = typer.Option(0.15, '-t', '--threshold',
                                             help='语义筛选阈值 (默认 0.15; 0=只重排不过滤)'),
             new_only: bool = typer.Option(False, '--new-only',
                                           help='增量: 只显示上次抓取后的新条目 (状态存 ~/.webtool/feed_state.json)'),
             add: list[str] = typer.Option([], '--add',
                                           help='添加自定义源: --add NAME --add URL [--add 描述] (存 ~/.webtool/feeds.json)'),
             del_src: str = typer.Option(None, '--del', help='删除自定义源 (预设源不可删)'),
             mark: list[str] = typer.Option([], '--mark',
                                            help='人工登记坏源: --mark KEY [--mark URL] --mark "原因备注"'),
             retest: str = typer.Option(None, '--retest',
                                        help='复查坏源是否恢复: --retest KEY 或 --retest all'),
             pick: str = typer.Option(None, '--pick',
                                      help='选定命中的第几条路由 (1 起) 或按模板子串匹配; 不给则自动取 heat 最高'),
             param: list[str] = typer.Option([], '--param',
                                             help='给选中的那条路由填占位符, 可重复: --param category=newsflashes'),
             example: bool = typer.Option(False, '--example', help='用官方 example 路径填参出订阅 URL'),
             top: int = typer.Option(None, '--top', help='用第 N 条真实实例样例 (topFeeds, 1 起) 填参'),
             from_url: str = typer.Option(None, '--from-url', help='给定网页 URL, 用 radar.source 模式反推路由'),
             instance: str = typer.Option(None, '--instance', help='指定实例前缀 (默认自动挑最快可用的)'),
             cat: str = typer.Option(None, '--cat', help='按分类过滤路由 (new-media/programming/finance/...)'),
             radar_refresh: bool = typer.Option(False, '--radar-refresh', help='强制刷新路由库缓存 (默认 7 天)'),
             no_xcheck: bool = typer.Option(False, '--no-xcheck',
                                            help='不与官网 feed 交叉校验 (默认校验并据此决定取数源)'),
             items: bool = typer.Option(False, '--items',
                                        help='校验后把选定源的条目完整输出; 默认只报校验结论与耗时'),
             no_url: bool = typer.Option(False, '--no-url',
                                         help='输出不带链接: 去掉每条的 url 字段 (markdown/text 只留标题)'),
             fmt: str = Fmt, output: str = Output,
             no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """RSS/Atom 订阅源抓取 (官方 feed + 任意 URL; 支持增量)"""
    a = _CTX['args']
    a.sources, a.max, a.query, a.threshold = sources or [], max, query, threshold
    a.no_url = no_url
    a.new_only, a.add, a.del_src, a.mark, a.retest = new_only, add, del_src, mark, retest
    a.pick, a.param, a.example, a.top = pick, param, example, top
    a.from_url, a.instance, a.cat = from_url, instance, cat
    a.radar_refresh, a.no_xcheck, a.items = radar_refresh, no_xcheck, items
    return _run('data', _entry_fn('feed'), fmt, output, no_cache, no_proxy)
