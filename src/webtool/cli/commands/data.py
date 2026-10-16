"""cli 命令: 搜索 / 抓取 / AI / 站内 / 榜单 / 订阅 / 选股

从 app.py 拆出, 注册到共享的 Typer app。共享 plumbing 见 webtool.cli._ctx。
"""

import typer

from webtool.cli._ctx import (
    Fmt, NoCache, NoProxy, Output, _CTX, _do,
    _entry_fn, _norm_think, _run,
)
from webtool.cli.app import app

@app.command('search')
def search_cmd(query: str = typer.Argument(None, help='搜索词 (留空时从 stdin 读一行, 如 echo 词 | webtool search -)'),
               engine: str = typer.Option(None, '-e', '--engine',
                                          help='逗号分隔: bing,sogou,baidu,so360,google,marginalia'),
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
                                        help='并发抓取的源数 (默认 源数, 上限 4; 1=串行)')):
    """多引擎网页搜索"""
    a = _CTX['args']
    a.update = None
    from webtool.core import stdin as _stdin
    query = _stdin.read_input(query, required=True, what='搜索词')
    a.query, a.engine, a.preset, a.max = query, engine, preset, max
    a.operators, a.blocklist = operators, blocklist
    a.jobs = jobs
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
                                           'parallel|exa=直接走对应 MCP 的 web_fetch')):
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
            sticky: bool = typer.Option(True, '--sticky/--no-sticky',
                                        help='固定会话 id, 按整点轮换 (默认开); --no-sticky 每次运行换新'),
            fmt: str = Fmt, output: str = Output,
            no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """OpenCode Zen 免费层对话 (OpenAI 兼容, 公开模式, 无需 key)"""
    a = _CTX['args']
    # 默认值优先级: 命令行 > ~/.webtool/zen.json 的 zen 段 > 内置 (见 zenproto.DEFAULTS)
    from webtool.cli import zenproto as _zp
    dfl = _zp.defaults()
    a.prompt = ' '.join(prompt) if prompt else ''
    a.model = model or dfl['model']
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
    a.reasoning = show_reasoning
    a.think = _norm_think(think if think is not None else dfl['reasoning_effort'])
    return _run('data', _entry_fn('zen'), fmt, output, no_cache, no_proxy)

@app.command('site')
def site_cmd(site: str = typer.Argument(None, help='站点 key, `webtool site list` 查看全部'),
             query: str = typer.Argument(None, help='站内搜索词'),
             max: int = typer.Option(10, '-n', '--max'),
             lang: str = typer.Option('zh', '--lang', help='wikipedia 语言版本'),
             fmt: str = Fmt, output: str = Output,
             no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """站内搜索(知名站点官方接口, 与传统搜索引擎区分)"""
    from webtool.core import stdin as _stdin
    a = _CTX['args']
    query = _stdin.read_input(query, what='站内搜索词')
    a.site, a.query, a.max, a.lang = site, query, max, lang
    return _run('data', _entry_fn('site'), fmt, output, no_cache, no_proxy)

@app.command('rank')
def rank_cmd(sources: list[str] = typer.Argument(None, help='榜单源 key; 无参数 = 榜单清单+用法'),
             query: str = typer.Option(None, '-q', '--query',
                                       help='语义筛选词: 支持搜索的源透传站内过滤, 其余源拉榜后本地 BM25 筛选+跨源重排'),
             threshold: float = typer.Option(0.15, '-t', '--threshold',
                                             help='语义筛选阈值 0-1 (默认 0.15; 0=只列清单不过滤不重排)'),
             max: int = typer.Option(10, '-n', '--max', help='每源条数'),
             fmt: str = Fmt, output: str = Output,
             no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """榜单聚合: 无参=榜单清单; 指定源=按源分组原序; -q 语义筛选"""
    a = _CTX['args']
    # 默认值不能是 []: click 8.1.x 的 nargs=-1 参数带非 None default 直接 TypeError (老 typer 上炸)
    a.sources, a.query, a.threshold, a.max = sources or [], query, threshold, max
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
             fmt: str = Fmt, output: str = Output,
             no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """RSS/Atom 订阅源抓取 (官方 feed + 任意 URL; 支持增量)"""
    a = _CTX['args']
    a.sources, a.max, a.query, a.threshold = sources or [], max, query, threshold
    a.new_only, a.add, a.del_src, a.mark, a.retest = new_only, add, del_src, mark, retest
    a.pick, a.param, a.example, a.top = pick, param, example, top
    a.from_url, a.instance, a.cat = from_url, instance, cat
    a.radar_refresh, a.no_xcheck, a.items = radar_refresh, no_xcheck, items
    return _run('data', _entry_fn('feed'), fmt, output, no_cache, no_proxy)
