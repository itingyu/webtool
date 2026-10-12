"""webtool CLI (typer)

约定:
- 数据命令 (search/fetch/site/rank/feed/zen) 的 print 输出统一捕获后走 emit,
  支持 -f/-o 落盘; 管理命令 (proxy/engines/cache/blocklist/config) 直接输出
- -f 大小写不敏感, md=markdown, txt=text; 默认 json (fetch/zen 例外)
- 退出码: 0 成功 / 2 用法错误 / 130 Ctrl-C
"""
import io
import sys
from contextlib import redirect_stdout

import typer

# typer 0.27 vendored 了 click: 异常类在 typer._click.exceptions, 与顶层 click 不同源
from typer._click.exceptions import UsageError as _UsageError, ClickException as _ClickException

from webtool.net import proxy as _proxy
from webtool.render.output import emit

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
    if not v:
        return default
    x = v.strip().lower()
    return {'md': 'markdown', 'txt': 'text'}.get(x, x)


from types import SimpleNamespace


def _run(data_cmd, fn, fmt, output, no_cache, no_proxy, fmt_default='json'):
    """执行 do_* 并按数据命令约定处理输出; 返回 exit code"""
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
            rc = fn(args, cfg)
        if rc not in (0, None):
            return rc
        return emit(buf.getvalue(), args.format, output)
    return fn(args, cfg) or 0


_CTX = {}


@app.callback()
def _main(ctx: typer.Context,
          proxy: str = typer.Option(None, '--proxy', help='临时代理, 覆盖配置文件'),
          no_cache: bool = typer.Option(False, '--no-cache', help='跳过缓存')):
    _CTX.clear()
    _CTX.update(proxy=proxy, no_cache=no_cache, args=SimpleNamespace())


# ---------- search ----------

@app.command('search')
def search_cmd(query: str = typer.Argument(..., help='搜索词'),
               engine: str = typer.Option(None, '-e', '--engine',
                                          help='逗号分隔: bing,sogou,baidu,google,marginalia (默认 bing,sogou,baidu)'),
               max: int = typer.Option(8, '-n', '--max', help='每引擎结果数'),
               fmt: str = Fmt, output: str = Output,
               no_proxy: bool = NoProxy, no_cache: bool = NoCache,
               market: str = typer.Option('zh-CN', help='市场: zh-CN / en-US'),
               no_resolve: bool = typer.Option(False, '--no-resolve',
                                               help='关闭跳转链解码 (sogou/baidu link, gnews articles)'),
               keep_ad: bool = typer.Option(False, '--keep-ad',
                                            help='保留广告结果并标记 is_ad (默认已过滤)'),
               no_dedupe: bool = typer.Option(False, '--no-dedupe', help='关闭跨引擎去重'),
               no_semantic: bool = typer.Option(False, '--no-semantic',
                                                help='关闭语义向量排序(纯位置权重)'),
               no_retry: bool = typer.Option(False, '--no-retry',
                                             help='关闭低召回自动重试(默认开启)'),
               operators: str = typer.Option('passthrough', '--operators',
                                             help='高级操作符路由: passthrough/strip/strict '
                                                  '(支持 site: intitle: inurl: -词)'),
               block: list[str] = typer.Option([], '--block', help='临时追加黑名单域名, 可多次'),
               allow: list[str] = typer.Option([], '--allow', help='临时白名单例外(优先于黑名单), 可多次'),
               no_blocklist: bool = typer.Option(False, '--no-blocklist', help='关闭黑名单过滤')):
    """多引擎网页搜索"""
    a = _CTX['args']
    a.update = None
    a.query, a.engine, a.max = query, engine, max
    a.market, a.no_resolve, a.keep_ad = market, no_resolve, keep_ad
    a.no_dedupe, a.no_semantic, a.no_retry = no_dedupe, no_semantic, no_retry
    a.operators, a.block, a.allow, a.no_blocklist = operators, block, allow, no_blocklist
    a.no_ad = not keep_ad

    def fn(args, cfg):
        if keep_ad:
            from webtool.pipeline.search import do_search_raw
            return do_search_raw(args, cfg)
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
                                               'safari18_4_ios 等 (移动站/拿不到数据时试 android/ios)')):
    """抓取 URL 并提取正文"""
    a = _CTX['args']
    a.url, a.url_file = url, url_file
    a.max_chars, a.raw, a.with_metadata, a.profile = max_chars, raw, with_metadata, profile
    return _run('data', _do('fetch'), fmt, output, no_cache, no_proxy, 'markdown')


def _do(name):
    def fn(args, cfg):
        from webtool import fetch
        return getattr(fetch, f'do_{name}')(args, cfg)
    return fn


# ---------- zen ----------

@app.command('zen')
def zen_cmd(prompt: list[str] = typer.Argument([], help='要问的问题 (留空则走 --list-models)'),
            model: str = typer.Option('big-pickle', '--model',
                                      help='模型 id (不带 provider 前缀; 见 zen --list-models)'),
            protocol: str = typer.Option(None, '--protocol',
                                         help='协议: openai (默认) / anthropic; 不给则读 zen.json 的 protocol'),
            system: str = typer.Option(None, '--system',
                                       help='system prompt (分类器只验 role:system 存在, 不读内容)'),
            tool_choice: str = typer.Option('none', '--tool-choice',
                                            help='是否允许模型调工具; 默认 none。调用只打印不执行'),
            full_tools: bool = typer.Option(False, '--full-tools',
                                            help='发完整的 11 个工具定义 (默认只发 bash+read)'),
            list_models: bool = typer.Option(False, '--list-models', help='列出 /v1/models 的全部 id'),
            list_free: bool = typer.Option(False, '--list-free',
                                           help='只列免费层 id (按命名约定筛, 不是保证)'),
            check: bool = typer.Option(False, '--check',
                                       help='配合 --list-free: 真调每个模型验证能不能用'),
            refresh: bool = typer.Option(False, '--refresh', help='绕过 1h 模型清单缓存'),
            show_body: bool = typer.Option(False, '--show-body',
                                           help='打印将要发送的请求体并退出, 不联网'),
            show_text: bool = typer.Option(False, '--show-text',
                                           help='只打印 messages (原样 JSON), 不联网'),
            stream: bool = typer.Option(True, '--no-stream/--stream',
                                        help='不流式, 缓冲到最后一次性输出'),
            retries: int = typer.Option(3, '--retries', help='瞬时故障 (连接错/408/429/5xx) 重试次数'),
            sticky: bool = typer.Option(False, '--sticky',
                                        help='复用同一 ses_id (默认关: 实测 Zen 免费层不返回 prompt cache 统计, 开不开耗时无差异)'),
            fmt: str = Fmt, output: str = Output,
            no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """LLM 对话: 默认 OpenCode Zen 免费层 (公开模式, 无需 key);
    --protocol anthropic 可切到 Claude 兼容端点 (需 ~/.webtool/zen.json 配 key/url)"""
    a = _CTX['args']
    a.prompt, a.model, a.system = ' '.join(prompt) if prompt else '', model, system
    a.protocol = protocol
    a.tool_choice, a.full_tools = tool_choice, full_tools
    a.list_models, a.list_free, a.check, a.refresh = list_models, list_free, check, refresh
    a.show_body, a.show_text, a.stream = show_body, show_text, stream
    a.retries, a.sticky = retries, sticky
    return _run('data', _entry_fn('zen'), fmt, output, no_cache, no_proxy, 'text')


def _entry_fn(name):
    def fn(args, cfg):
        import importlib
        mod = {'zen': ('zen', 'do_zen'), 'fetch': ('fetch', 'do_fetch'),
               'site': ('sitesearch', 'do_site'),
               'rank': ('pipeline.rank', 'do_rank'),
               'feed': ('feeds.command', 'do_feed')}[name]
        m = importlib.import_module('.' + mod[0], package='webtool')
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
def proxy_cmd(action: str = typer.Argument(..., help='get/set/unset/test'),
              value: str = typer.Argument(None, help='代理地址, 如 http://127.0.0.1:2080 或 socks5://...')):
    """代理配置"""
    a = _CTX['args']
    a.action, a.value = action, value
    cfg = _proxy.load_config()
    if _CTX.get('proxy'):
        cfg['proxy'] = _CTX['proxy']
    return _proxy.handle(a, cfg) or 0


@app.command('engines')
def engines_cmd(action: str = typer.Argument('list', help='list=清单+冷却状态; test=实发体检'),
                name: str = typer.Argument(None, help='test 时的引擎名; 省略=全部引擎'),
                check: bool = typer.Option(False, '--check', help='实发一次测试请求 (等价 engines test)'),
                query: str = typer.Option('python', '--query', help='test 用的测试词')):
    """搜索引擎状态"""
    a = _CTX['args']
    a.action, a.name, a.check, a.query = action, name, check, query

    def fn(args, cfg):
        from webtool.engines.status import status
        return status(args, cfg)
    return _run(None, fn, None, None, False, False)


@app.command('cache')
def cache_cmd(action: str = typer.Argument(..., help='clear/info')):
    """缓存管理"""
    a = _CTX['args']
    a.action = action

    def fn(args, cfg):
        from webtool.core import cache
        return cache.handle(args, cfg)
    return _run(None, fn, None, None, False, False)


@app.command('blocklist')
def blocklist_cmd(action: str = typer.Argument(..., help='show/add/remove/reset'),
                  domain: str = typer.Argument(None, help='域名, 如 csdn.net'),
                  allow: bool = typer.Option(False, '--allow', help='add/remove 白名单例外')):
    """黑名单管理 (低质量站点)"""
    a = _CTX['args']
    a.action, a.domain, a.allow = action, domain, allow

    def fn(args, cfg):
        from webtool import blocklist
        return blocklist.handle_cli(args)
    return _run(None, fn, None, None, False, False)


@app.command('config')
def config_cmd(action: str = typer.Argument(..., help='list/get/set/unset'),
               key: str = typer.Argument(None),
               value: str = typer.Argument(None)):
    """配置管理: 代理/黑名单/权重阈值/默认引擎等"""
    a = _CTX['args']
    a.action, a.key, a.value = action, key, value

    def fn(args, cfg):
        from webtool.cli import config as _cfg_cmd
        return _cfg_cmd.handle(args)
    return _run(None, fn, None, None, False, False)


@app.command('plugins')
def plugins_cmd(action: str = typer.Argument('list', help='list/check/reload/enable/disable'),
                kind: str = typer.Argument(None, help='engine/hot/site/extractor/resolver/filter/transformer'),
                plugin: str = typer.Argument(None, help='enable/disable 的插件名'),
                all: bool = typer.Option(False, '--all', '-a', help='list 含 disabled 项')):
    """插件管理: 清单与来源 / 加载体检 / 启停 / 热重载外部插件"""
    a = _CTX['args']
    a.action, a.kind, a.plugin, a.all = action, kind, plugin, all

    def fn(args, cfg):
        from webtool.cli import plugins as _plug_cmd
        return _plug_cmd.handle(args)
    return _run(None, fn, None, None, False, False)


def main(argv=None):
    """入口: argv=None 走 sys.argv; 退出码 0/2/130

    standalone_mode=False 让 click 把用法错误抛成 UsageError 而非自退,
    这里统一转成 stderr 提示 + rc 2。
    """
    try:
        if argv is None:
            rc = app(standalone_mode=False, prog_name='webtool')
        else:
            rc = app(args=argv, standalone_mode=False, prog_name='webtool')
        return rc if isinstance(rc, int) else 0
    except (typer.Exit, SystemExit) as e:      # --help / --version
        code = e.code if isinstance(e, SystemExit) else e.exit_code
        return code if isinstance(code, int) else 0
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



