"""webtool CLI (typer)

约定:
- 数据命令 (search/fetch/site/rank/feed/zen) 的 print 输出统一捕获后走 emit,
  支持 -f/-o 落盘; 管理命令 (proxy/engines/cache/blocklist/config/plugins) 也支持
  -f/-o, 由 cli/adminfmt.py 把它们吐出的 JSON 转成目标格式
- -f 大小写不敏感, md=markdown, txt=text; 非法值直接报错退出 (不静默回落);
  默认 txt (主要消费者是人; 程序/Agent 消费请显式 -f json)
- 退出码: 0 成功 / 2 用法错误 / 130 Ctrl-C
"""
import io
import sys
from contextlib import redirect_stdout
from typing import List

import typer

# typer 0.27 vendored 了 click: 异常类在 typer._click.exceptions, 与顶层 click 不同源
from typer._click.exceptions import UsageError as _UsageError, ClickException as _ClickException

from webtool.net import proxy as _proxy
from webtool.render.output import emit, FORMATS

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help='Agent 友好的网页搜索与内容获取工具',
                  context_settings={'help_option_names': ['-h', '--help']})

# ---------- 公共选项 ----------

Fmt = typer.Option(None, '-f', '--format',
                   help='输出格式 json/text/markdown (大小写不敏感; md=markdown, txt=text)')
Output = typer.Option(None, '-o', '--output',
                      help='输出到文件 (按 -f 补扩展名; 目录则自动命名; -o - 强制 stdout)')
NoProxy = typer.Option(False, '--no-proxy', help='本次不走代理(覆盖配置)')
NoCache = typer.Option(False, '--no-cache', help='跳过缓存')


def _norm_fmt(v, default):
    """归一化输出格式; 非法值直接报错退出, 不静默回落 text。

    静默回落会让 Agent 拿到人类可读文本却毫无提示, 解析阶段才炸, 难排查。
    """
    if not v:
        return default
    x = v.strip().lower()
    x = {'md': 'markdown', 'txt': 'text'}.get(x, x)
    if x not in FORMATS:
        raise _UsageError(f'未知输出格式 {v!r}; 可用: {", ".join(sorted(FORMATS))}'
                          f' (别名 md=markdown, txt=text)')
    return x


from types import SimpleNamespace


def _run(data_cmd, fn, fmt, output, no_cache, no_proxy, fmt_default='text'):
    """执行 do_* 并按数据命令约定处理输出; 返回 exit code

    data_cmd 非空 = 数据命令, 内部自己按 args.format 渲染, 这里只接住落盘;
    data_cmd 为空 = 管理命令, 内部 print 原样输出, 这里按 -f 转格式后再 emit。
    """
    cfg = _proxy.load_config()
    gproxy = _CTX.get('proxy')
    if gproxy:
        cfg['proxy'] = gproxy
    args = _CTX['args']
    args.no_cache = no_cache or _CTX['no_cache']
    args.no_proxy = no_proxy
    args.format = _norm_fmt(fmt, fmt_default)
    args.output = output
    if data_cmd:
        buf = io.StringIO()
        with redirect_stdout(buf):
            try:
                rc = fn(args, cfg)
            except ValueError as e:
                # 渲染层的用法错误不该甩 traceback
                raise _UsageError(str(e))
            except ImportError as e:
                # stock 是延迟导入 + requests 顶层 import, 少装依赖时表现是
                # 一串 importlib 栈, 而其余命令完全正常, 很难联想到缺包。
                raise _UsageError(
                    f'缺少依赖 {e.name or e}; 股票能力装: pip install "webtool[stock]"')
        out = buf.getvalue()
        if rc not in (0, None):
            # 命令已经跑出报告了, 退出码只是"有没有可用结果"的判据 (如 zen
            # --check 全挂) —— 别因为退出码非零就把人要看的报告丢掉。
            if out.strip():
                emit(out, args.format, output)
            return rc
        return emit(out, args.format, output)
    # 管理命令: 未指定 -f 时按 txt 渲染 (与数据命令默认一致)。
    # 但把 args.format 交回 None, 让 config list 这类内部会按 format 分支的
    # 命令走它自己的人类可读默认, 而不是看到 'text' 就交结构化数据。
    if not fmt and not output:
        args.format = None
        out_fmt = 'text'
    else:
        out_fmt = args.format
    buf = io.StringIO()
    with redirect_stdout(buf):
        try:
            rc = fn(args, cfg)
        except ImportError as e:
            # stock 是延迟导入 + requests 顶层 import, 少装依赖时表现是一串
            # importlib 栈, 而 search/fetch 等其余命令完全正常, 很难联想到
            # 是缺包。两条分支都要接住, 否则管理命令分支 (data_cmd 为空)
            # 会绕过这里的转换。
            raise _UsageError(
                f'缺少依赖 {e.name or e}; 股票能力装: pip install "webtool[stock]"')
    from webtool.cli.adminfmt import adapt
    if rc not in (0, None):
        # 与数据命令同理: 报告已经打出来了, 退出码只是"有没有可用结果"的判据
        # (如 upgrade --check 有新版就退 1), 别把报告一起吞掉。
        out = buf.getvalue()
        if out.strip():
            emit(adapt(out, out_fmt), out_fmt, output)
        return rc
    return emit(adapt(buf.getvalue(), out_fmt), out_fmt, output)


_CTX = {}


@app.callback()
def _main(ctx: typer.Context,
          proxy: str = typer.Option(None, '--proxy', help='临时代理, 覆盖配置文件'),
          no_cache: bool = typer.Option(False, '--no-cache', help='跳过缓存')):
    # --version / -V 不在 click 层, 由 main() 预扫 (子命令后面也能用), 见 main
    _CTX.clear()
    _CTX.update(proxy=proxy, no_cache=no_cache, args=SimpleNamespace())


# ---------- search ----------

@app.command('search')
def search_cmd(query: str = typer.Argument(..., help='搜索词'),
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
                                                 '传 off 关闭黑名单')):
    """多引擎网页搜索"""
    a = _CTX['args']
    a.update = None
    a.query, a.engine, a.preset, a.max = query, engine, preset, max
    a.operators, a.blocklist = operators, blocklist
    a.no_ad = True

    def fn(args, cfg):
        from webtool.pipeline.search import do_search
        return do_search(args, cfg)
    return _run('data', fn, fmt, output, no_cache, no_proxy)


# ---------- fetch ----------

@app.command('fetch')
def fetch_cmd(url: str = typer.Argument(None, help='要抓取的 URL'),
              url_file: str = typer.Option(None, '--url-file', help='从文件读多个 URL(每行一个)'),
              fmt: str = Fmt, output: str = Output,
              no_proxy: bool = NoProxy, no_cache: bool = NoCache,
              max_chars: int = typer.Option(0, '--max-chars', help='正文截断字符数, 0=不截断'),
              raw: bool = typer.Option(False, '--raw', help='跳过正文提取, 输出原始 HTML'),
              with_metadata: bool = typer.Option(False, '--with-metadata',
                                                 help='json 格式附带标题/作者/日期'),
              profile: str = typer.Option(None, '--profile',
                                          help='传输指纹档案: chrome131_win/mac/linux/android, '
                                               'safari18_4_ios 等 (移动站/拿不到数据时试 android/ios)'),
              via: str = typer.Option('local', '--via',
                                      help='取正文通道: local=本地提取链(默认, 免配额) / '
                                           'auto=本地失败时兜底远程 reader / '
                                           'parallel|exa=直接走对应 MCP 的 web_fetch')):
    """抓取 URL 并提取正文"""
    a = _CTX['args']
    a.url, a.url_file = url, url_file
    a.max_chars, a.raw, a.with_metadata, a.profile = max_chars, raw, with_metadata, profile
    a.via = via
    return _run('data', _do('fetch'), fmt, output, no_cache, no_proxy)


def _do(name):
    def fn(args, cfg):
        import webtool.net.fetch as fetch
        return getattr(fetch, f'do_{name}')(args, cfg)
    return fn


# ---------- zen ----------

@app.command('zen')
def zen_cmd(prompt: list[str] = typer.Argument([], help='要问的问题 (留空则走 --list-models)'),
            model: str = typer.Option('big-pickle', '--model',
                                      help='模型 id (不带 provider 前缀; 见 zen --list-models)'),
            system: str = typer.Option(None, '--system',
                                       help='system prompt (分类器只验 role:system 存在, 不读内容)'),
            tool_choice: str = typer.Option('auto', '--tool-choice',
                                            help='是否允许模型调工具; 默认 auto (闸门判据, 改 none 会被拒)'),
            tools: str = typer.Option('min', '--tools',
                                      help='工具集: min(默认, 闸门最小集 bash+read) / all / 逗号清单 (如 bash,read,grep)'),
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
            live: bool = typer.Option(True, '--live/--no-live', '--stream/--no-stream',
                                      help='边收边打印 (默认开, 仅终端里生效); --no-live 攒到最后一次输出'),
            show_reasoning: bool = typer.Option(True, '--reasoning/--no-reasoning',
                                                help='打印思考过程 (默认开); --no-reasoning 只要答案 (不改请求体)'),
            retries: int = typer.Option(2, '--retries', help='瞬时故障 (连接错/408/429/5xx) 重试次数; 退避指数 2/4/8s'),
            sticky: bool = typer.Option(True, '--sticky/--no-sticky',
                                        help='固定会话 id, 按整点轮换 (默认开); --no-sticky 每次运行换新'),
            fmt: str = Fmt, output: str = Output,
            no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """OpenCode Zen 免费层对话 (OpenAI 兼容, 公开模式, 无需 key)"""
    a = _CTX['args']
    a.prompt, a.model, a.system = ' '.join(prompt) if prompt else '', model, system
    a.tool_choice = tool_choice
    a.tools = 'all' if all_tools else tools
    a.list_models, a.list_free = list_models, list_free
    a.check = check or check_all          # --check-all 单独给也生效 (以前是静默空转)
    a.check_all, a.refresh = check_all, refresh
    a.dry_run, a.show, a.stream = dry_run, show, live
    a.show_body, a.show_text = show_body, show_text
    a.retries, a.sticky = retries, sticky
    a.reasoning = show_reasoning
    return _run('data', _entry_fn('zen'), fmt, output, no_cache, no_proxy)


def _entry_fn(name):
    def fn(args, cfg):
        import importlib
        mod = {'zen': ('cli.zen', 'do_zen'), 'fetch': ('net.fetch', 'do_fetch'),
               'site': ('cli.sitesearch', 'do_site'),
               'rank': ('pipeline.rank', 'do_rank'),
               'stock': ('stock.command', 'do_stock'),
               'feed': ('feeds.command', 'do_feed')}[name]
        m = importlib.import_module('webtool.' + mod[0])
        return getattr(m, mod[1])(args, cfg)
    return fn


# ---------- site ----------

@app.command('site')
def site_cmd(site: str = typer.Argument(None, help='站点 key, `webtool site list` 查看全部'),
             query: str = typer.Argument(None, help='站内搜索词'),
             max: int = typer.Option(10, '-n', '--max'),
             lang: str = typer.Option('zh', '--lang', help='wikipedia 语言版本'),
             fmt: str = Fmt, output: str = Output,
             no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """站内搜索(知名站点官方接口, 与传统搜索引擎区分)"""
    a = _CTX['args']
    a.site, a.query, a.max, a.lang = site, query, max, lang
    return _run('data', _entry_fn('site'), fmt, output, no_cache, no_proxy)


# ---------- rank ----------

@app.command('rank')
def rank_cmd(sources: list[str] = typer.Argument([], help='榜单源 key; 无参数 = 榜单清单+用法'),
             query: str = typer.Option(None, '-q', '--query',
                                       help='语义筛选词: 支持搜索的源透传站内过滤, 其余源拉榜后本地 BM25 筛选+跨源重排'),
             threshold: float = typer.Option(0.15, '-t', '--threshold',
                                             help='语义筛选阈值 0-1 (默认 0.15; 0=只列清单不过滤不重排)'),
             max: int = typer.Option(10, '-n', '--max', help='每源条数'),
             fmt: str = Fmt, output: str = Output,
             no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """榜单聚合: 无参=榜单清单; 指定源=按源分组原序; -q 语义筛选"""
    a = _CTX['args']
    a.sources, a.query, a.threshold, a.max = sources, query, threshold, max
    return _run('data', _entry_fn('rank'), fmt, output, no_cache, no_proxy)


# ---------- feed ----------

@app.command('feed')
def feed_cmd(sources: list[str] = typer.Argument([], help='feed key 或任意 RSS/Atom URL; 无参数 = 清单+用法'),
             max: int = typer.Option(10, '-n', '--max', help='每源条数'),
             query: str = typer.Option(None, '-q', '--query', help='语义筛选词 (BM25 本地筛 + 按相关度重排)'),
             threshold: float = typer.Option(0.15, '-t', '--threshold',
                                             help='语义筛选阈值 (默认 0.15; 0=只重排不过滤)'),
             new_only: bool = typer.Option(False, '--new-only',
                                           help='增量: 只显示上次抓取后的新条目 (状态存 ~/.webtool/feed_state.json)'),
             add: list[str] = typer.Option([], '--add',
                                           help='添加自定义源: --add NAME URL [描述] (存 ~/.webtool/feeds.json)'),
             del_src: str = typer.Option(None, '--del', help='删除自定义源 (预设源不可删)'),
             mark: list[str] = typer.Option([], '--mark',
                                            help='人工登记坏源: --mark KEY [URL] "原因备注"'),
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
    a.sources, a.max, a.query, a.threshold = sources, max, query, threshold
    a.new_only, a.add, a.del_src, a.mark, a.retest = new_only, add, del_src, mark, retest
    a.pick, a.param, a.example, a.top = pick, param, example, top
    a.from_url, a.instance, a.cat = from_url, instance, cat
    a.radar_refresh, a.no_xcheck, a.items = radar_refresh, no_xcheck, items
    return _run('data', _entry_fn('feed'), fmt, output, no_cache, no_proxy)


# ---------- 管理命令 ----------

@app.command('proxy')
def proxy_cmd(action: str = typer.Argument(..., help='get/set/unset/test/setpass/delpass/passwd/rules/rule/ruledel/geoip/asn/noproxy'),
              value: str = typer.Argument(None, help='代理地址; 或 rule 的子命令; 或试算用的 URL'),
              user: str = typer.Argument(None, help='setpass/delpass 的用户名; rule add 的 match JSON; ruledel 的序号'),
              act: str = typer.Argument(None, help='rule add 的动作: direct/proxy/block/proxy:<名字>'),
              first: bool = typer.Option(False, '--first', help='rule add: 插到规则表最前面 (默认追加到末尾, 会被前面的规则吃掉)'),
              pos: int = typer.Option(None, '--pos', help='rule add: 插到第 N 位 (0 = 最前)')):
    """代理配置: 选线路 / 存凭据(密文) / 按域名-IP-端口-协议-GeoIP 分流"""
    a = _CTX['args']
    a.action, a.value, a.user, a.act = action, value, user, act
    a.first, a.pos = first, pos
    cfg = _proxy.load_config()
    if _CTX.get('proxy'):
        cfg['proxy'] = _CTX['proxy']
    return _proxy.handle(a, cfg) or 0


@app.command('engines')
def engines_cmd(action: str = typer.Argument('list', help='list=清单+冷却状态; test=实发体检; presets=引擎组合预设'),
                name: str = typer.Argument(None, help='test 时的引擎名; 省略=全部引擎'),
                check: bool = typer.Option(False, '--check', help='实发一次测试请求 (等价 engines test)'),
                query: str = typer.Option('python', '--query', help='test 用的测试词'),
                fmt: str = Fmt, output: str = Output):
    """搜索引擎状态"""
    a = _CTX['args']
    a.action, a.name, a.check, a.query = action, name, check, query

    def fn(args, cfg):
        if args.action == 'presets':
            import json as _j
            from webtool.pipeline.search import presets as _p
            rows = [{'preset': k, 'desc': v.get('desc', ''),
                     'engines': ','.join(v.get('engines', []))}
                    for k, v in _p().items()]
            print(_j.dumps(rows, ensure_ascii=False, indent=1))
            return 0
        from webtool.engines.status import status
        return status(args, cfg)
    return _run(None, fn, fmt, output, False, False)


@app.command('mcp')
def mcp_cmd(action: str = typer.Argument('list', help='list=列工具; probe=端点体检; call=调工具'),
            target: str = typer.Argument(..., help='MCP 端点 URL, 或 ~/.webtool/mcp.json 里的别名'),
            tool: str = typer.Argument(None, help='call 时的工具名'),
            arguments: str = typer.Argument(None, help="call 时的 JSON 参数, 如 '{\"query\":\"x\"}'"),
            params: List[str] = typer.Option(None, '--arg', metavar='K=V',
                                             help='call 时的拆开参数, 可多次; 值按 JSON 字面量猜类型'),
            key_env: str = typer.Option('', '--key-env', help='从哪个环境变量读 API key'),
            tools: str = typer.Option('', '--tools', help='工具白名单, 逗号分隔 (?tools=)'),
            timeout: float = typer.Option(45.0, '--timeout', help='单次请求超时秒'),
            fmt: str = Fmt, output: str = Output, no_proxy: bool = NoProxy):
    """通用 MCP 客户端 (不绑死具体 server)"""
    a = _CTX['args']
    a.action, a.target, a.tool, a.arguments = action, target, tool, arguments
    a.params = params
    a.key_env, a.tools, a.timeout = key_env, tools, timeout

    def fn(args, cfg):
        from webtool.cli.mcp import do_mcp
        return do_mcp(args, cfg)
    return _run(None, fn, fmt, output, False, no_proxy)


@app.command('cache')
def cache_cmd(action: str = typer.Argument(..., help='clear/info'),
               fmt: str = Fmt, output: str = Output):
    """缓存管理"""
    a = _CTX['args']
    a.action = action

    def fn(args, cfg):
        from webtool.core import cache
        return cache.handle(args, cfg)
    return _run(None, fn, fmt, output, False, False)


@app.command('blocklist')
def blocklist_cmd(action: str = typer.Argument(..., help='show/add/remove/reset'),
                  domain: str = typer.Argument(None, help='域名, 如 csdn.net'),
                  allow: bool = typer.Option(False, '--allow', help='add/remove 白名单例外'),
               fmt: str = Fmt, output: str = Output):
    """黑名单管理 (低质量站点)"""
    a = _CTX['args']
    a.action, a.domain, a.allow = action, domain, allow

    def fn(args, cfg):
        import webtool.filters.blocklist as blocklist
        return blocklist.handle_cli(args)
    return _run(None, fn, fmt, output, False, False)


def _pip_proxy_env():
    """pip/git 是子进程, 代理只能靠环境变量给 —— 但如果拿我们自研的 httpx
    专家库那套再包一层就等于给自己加坑, 所以直接问 netx, 它负责看 rules.json。"""
    from webtool.net import netx
    route = netx.resolve_proxy('auto', 'https://github.com')
    if not route:
        # 规则表判为直连: 明确让它别用环境里可能存在的代理
        return {'NO_PROXY': '*', 'no_proxy': '*'}
    return {'HTTP_PROXY': route, 'HTTPS_PROXY': route, 'ALL_PROXY': route,
            'http_proxy': route, 'https_proxy': route, 'all_proxy': route,
            'NO_PROXY': '', 'no_proxy': ''}


def _upgrade_run(check_only, spec, fmt, output):
    """upgrade 与别名 update 共用 (实现只一处)"""
    a = _CTX['args']
    a.check_only, a.spec = check_only, spec

    def fn(args, cfg):
        import json as _json
        from webtool.core import upgrade as _up
        want_json = (args.format or '') == 'json'
        env = _pip_proxy_env()
        spec = args.spec or None
        if args.check_only:
            info = _up.check(spec, env_extra=env)
            print(_json.dumps(info, ensure_ascii=False, indent=2) if want_json
                  else _up.describe(info))
            # 退出码给脚本用: 0 已最新 / 1 有新版本 / 2 判不出来
            return {'up_to_date': 0, 'behind': 1}.get(info['state'], 2)
        res = _up.upgrade(spec, env_extra=env)
        if want_json:
            print(_json.dumps(res, ensure_ascii=False, indent=2))
        else:
            for line in res['log']:
                print(line)
        return 0 if res['ok'] else 1
    return _run(None, fn, fmt, output, False, False)


@app.command('uninstall')
def uninstall_cmd(purge_data: bool = typer.Option(False, '--purge-data', help='完全卸载: 连 ~/.webtool 里的配置/凭据/缓存一起删'),
                  yes: bool = typer.Option(False, '--yes', '-y', help='确认删除数据 (--purge-data 必须带)'),
                  dry_run: bool = typer.Option(False, '--dry-run', help='只看要跑什么, 不动手'),
                  fmt: str = Fmt, output: str = Output):
    """卸载 webtool (默认只卸包留数据, 完全卸载要 --purge-data --yes)

    默认 = 安全卸载: 只卸包, 数据/配置/凭据原样留着 (装回来即原样)。
    完全卸载要显式 `--purge-data --yes` —— 那会连保险库密钥、手写规则一起删。
    """
    a = _CTX['args']
    a.purge_data, a.yes, a.dry_run = purge_data, yes, dry_run

    def fn(args, cfg):
        import json as _json
        from webtool.core import uninstall as _un
        want_json = (args.format or '') == 'json'
        # 先把两种"要动数据但没确认"的情况挡在门外: 一个字节都不动
        if args.purge_data and not args.yes:
            print('webtool uninstall: --purge-data 要真删得加 --yes (否则只是安全卸载)',
                  file=sys.stderr)
            return 2
        res = _un.perform(dry=args.dry_run)
        info = {'mode': res['mode'], 'cmd': ' '.join(res['cmd']),
                'dry_run': res['dry_run'], 'package_removed': res['ok'],
                'data': _un.data_inventory()}
        purge = None
        if args.purge_data and not args.dry_run:
            purge = _un.purge_data(yes=True)
            info['purge'] = purge
        if want_json:
            print(_json.dumps(info, ensure_ascii=False, indent=2))
        else:
            print(_un.describe_uninstall(res, info['data'], purge))
        return 0 if res['ok'] or res['dry_run'] else 1
    return _run(None, fn, fmt, output, False, False)


@app.command('upgrade')
def upgrade_cmd(check_only: bool = typer.Option(False, '--check', help='只问 pip 有没有新版, 不装'),
                from_: str = typer.Option(None, '--from', help='换升级源 (任意 pip spec, 如 git+https://… 或包名)'),
                fmt: str = Fmt, output: str = Output):
    """升级 webtool (走 pip, 代理按 rules.json; 别名 update)

    --check 退出码: 0 已最新 / 1 有新版本 / 2 判不出来 (pip 或网络不通)
    """
    return _upgrade_run(check_only, from_, fmt, output)


@app.command('update', hidden=True)          # 顺手给个别名, 老习惯能撞上
def update_cmd(check_only: bool = typer.Option(False, '--check'),
               from_: str = typer.Option(None, '--from'),
               fmt: str = Fmt, output: str = Output):
    """(别名) 同 upgrade"""
    return _upgrade_run(check_only, from_, fmt, output)


@app.command('config')
def config_cmd(action: str = typer.Argument(..., help='list/get/set/unset'),
               key: str = typer.Argument(None),
               value: str = typer.Argument(None),
               fmt: str = Fmt, output: str = Output):
    """配置管理: 代理/黑名单/权重阈值/默认引擎等"""
    a = _CTX['args']
    a.action, a.key, a.value = action, key, value

    def fn(args, cfg):
        from webtool.cli import config as _cfg_cmd
        return _cfg_cmd.handle(args)
    return _run(None, fn, fmt, output, False, False)


@app.command('plugins')
def plugins_cmd(action: str = typer.Argument('list', help='list/check/reload/enable/disable'),
                kind: str = typer.Argument(None, help='engine/hot/site/extractor/resolver/filter/transformer'),
                plugin: str = typer.Argument(None, help='enable/disable 的插件名'),
                all: bool = typer.Option(False, '--all', '-a', help='list 含 disabled 项'),
                fmt: str = Fmt, output: str = Output):
    """插件管理: 清单与来源 / 加载体检 / 启停 / 热重载外部插件"""
    a = _CTX['args']
    a.action, a.kind, a.plugin, a.all = action, kind, plugin, all

    def fn(args, cfg):
        from webtool.cli import plugins as _plug_cmd
        return _plug_cmd.handle(args)
    return _run(None, fn, fmt, output, False, False)


# ---------- stock ----------

@app.command('stock')
def stock_cmd(action: str = typer.Argument(None, help='quote/pool/check/calendar/flow/news/'
                                                        'announcement/financials/analyze/'
                                                        'screen/risk/mcp/tools/health'),
              codes: list[str] = typer.Argument(None, help='股票代码 (quote/check/risk 用, 可多个)'),
              date: str = typer.Option(None, '--date', help='数据日 (pool/calendar; last=上一交易日)'),
              only_buy: bool = typer.Option(False, '--only-buy', help='pool 只留可买板块'),
              scope: str = typer.Option('industry', '--scope',
                                        help='flow 资金流口径: industry/individual/north'),
              pool: str = typer.Option('short', '--pool',
                                       help='screen 池: short(1-5日)/mid(3-6月)/long(6-18月)'),
              min_score: int = typer.Option(60, '--min-score', help='screen 技术面分门槛 (short 池)'),
              limit: int = typer.Option(10, '-n', '--limit', help='news/announcement 条数'),
              n: int = typer.Option(3, '--n', help='calendar 往后几个交易日'),
              tool: str = typer.Option(None, '--tool', help='mcp 动作的 stock 工具名, 如 stock_indicators'),
              params: list[str] = typer.Option(None, '--arg', metavar='K=V',
                                               help='mcp 动作参数, 可多次; 值按 JSON 字面量猜类型'),
              keyword: str = typer.Option('', '--keyword',
                                        help='tools 动作按关键词筛工具; docs-* 动作的备用关键词入参'),
              method: str = typer.Option(None, '--method', help='api/eco 动作要调的方法或接口名'),
              lib: str = typer.Option('akshare', '--lib', help='eco 动作的库: akshare/tushare/baostock/efinance'),
              full: bool = typer.Option(False, '--full', help='eco 动作返回完整数据 (默认只给形状+预览)'),
              by: str = typer.Option('source', '--by',
                                     help='api-list 分类维度: source(数据源, 默认)/function(功能)'),
              text: list[str] = typer.Option(None, '--text', metavar='文本',
                                             help='sentiment 打分的文本, 可多次'),
              excel: str = typer.Option(None, '--excel', help='excel 动作的输出 xlsx 路径'),
              kind: str = typer.Option(None, '--kind', help='diagram 图类型: logic/tree/chain'),
              name: str = typer.Option(None, '--name', help='diagram 标的/产业链名'),
              thesis: str = typer.Option(None, '--thesis', help='diagram 投资逻辑主线'),
              driver: list[str] = typer.Option(None, '--driver', help='diagram 驱动因素 (logic) / 上游 (chain), 可多次'),
              risk: list[str] = typer.Option(None, '--risk', help='diagram 风险 (logic), 可多次'),
              catalyst: list[str] = typer.Option(None, '--catalyst', help='diagram 催化剂 (logic) / 下游 (chain), 可多次'),
              mid: list[str] = typer.Option(None, '--mid', help='diagram 产业链中游 (chain), 可多次'),
              timeout: float = typer.Option(60.0, '--timeout', help='mcp 动作子进程超时秒'),
              url: str = typer.Option('', '--url', help='http-* 动作的 URL (也可用位置参数)'),
              referer: str = typer.Option('', '--referer', help='覆盖默认 Referer'),
              encoding: str = typer.Option('', '--encoding', help='强制解码 (gbk/gb18030 等)'),
              pick: str = typer.Option('', '--pick', help='取嵌套路径, 如 data.0.quote'),
              form: str = typer.Option('', '--form', help='POST 表单, 形如 k=v&k2=v2'),
              raw: bool = typer.Option(False, '--raw', help='输出 JSON 记录而非表格'),
              http_timeout: float = typer.Option(20.0, '--http-timeout', help='http-* 请求超时秒'),
              post: bool = typer.Option(False, '--post', help='data url 走 POST (表单用 --form)'),
              method_only: bool = typer.Option(False, '--method-only', help='data url 只回原始响应文本, 不转表格'),
              fmt: str = Fmt, output: str = Output):
    """股票能力: engine 脚本层 + 编排 24 工具 + 生态库(~1300) + 底层 HTTP 直调(900+ 接口) + 逆向文档"""
    a = _CTX['args']
    a.action, a.codes, a.date = action, list(codes or []), date
    a.only_buy, a.scope, a.pool, a.min_score = only_buy, scope, pool, min_score
    a.limit, a.n = limit, n
    a.tool, a.params, a.keyword, a.timeout = tool, params, keyword, timeout
    a.method = method
    a.by = by
    _form = {}
    for pair in (form or '').split('&'):
        if '=' in pair:
            k, v = pair.split('=', 1)
            _form[k] = v
    a.url, a.referer, a.encoding, a.pick, a.raw = url, referer, encoding, pick, raw
    a.form = _form
    a.http_timeout = http_timeout
    a.post, a.method_only = post, method_only
    a.lib, a.full = lib, full
    a.texts = list(text or [])
    a.excel, a.kind, a.name, a.thesis = excel, kind, name, thesis
    a.drivers = list(driver or [])
    a.risks = list(risk or [])
    a.catalysts = list(catalyst or [])
    a.mid = list(mid or [])
    # stock 不走 net 层, 无代理/缓存概念; 仍走 _run 统一 -f/-o 与退出码
    return _run(None, _entry_fn('stock'), fmt, output, False, False)


def _argv_format(argv):
    """预扫阶段 click 还没接管, 自己从原始 argv 取 -f/--format 的值"""
    for i, a in enumerate(argv):
        if a in ('-f', '--format') and i + 1 < len(argv):
            return argv[i + 1].strip().lower()
        for pre in ('--format=', '-f='):
            if a.startswith(pre):
                return a[len(pre):].strip().lower()
    return ''


def main(argv=None):
    """入口: argv=None 走 sys.argv; 退出码 0/2/130

    standalone_mode=False 让 click 把用法错误抛成 UsageError 而非自退,
    这里统一转成 stderr 提示 + rc 2。
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    # -v/-V/--version 在 click 解析前先扫: 放在子命令后面 (webtool zen --version)
    # click 会当作未知选项报错, 而用户想看的只是版本号。
    if '--version' in argv or '-v' in argv or '-V' in argv:
        from webtool.core import version as _v
        if _argv_format(argv) == 'json':
            import json
            print(json.dumps(_v.info(), ensure_ascii=False, indent=2))
        else:
            print('webtool %s' % _v.get_version())
        return 0
    try:
        # 首次启动补齐缺失的用户配置文件 (主要是 rules.json) —— 装完就有一份
        # 可编辑的默认路由规则, 不用自己去 ~/.webtool 里造。
        from webtool.core import bootstrap as _boot
        _boot.ensure_user_files()
    except Exception:                          # 配置落地绝不拦命令
        pass
    try:
        rc = app(args=argv, standalone_mode=False, prog_name='webtool')
        return rc if isinstance(rc, int) else 0
    except (typer.Exit, SystemExit) as e:      # --help / --version
        code = e.code if isinstance(e, SystemExit) else e.exit_code
        if isinstance(code, int):
            return code
        if code:                               # SystemExit('说明性文字'): 别静默吞
            print('webtool: %s' % code, file=sys.stderr)
            return 2
        return 0
    except _UsageError as e:
        msg = e.format_message()
        print(f'webtool: {msg}', file=sys.stderr)
        print('(webtool --help 看用法)', file=sys.stderr)
        return 2
    except _ClickException as e:
        e.show()
        return e.exit_code
    except BrokenPipeError:                    # 管道给 head 之类截断
        return 0
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    sys.exit(main())



