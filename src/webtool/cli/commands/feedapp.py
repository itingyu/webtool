"""feed: 抓取 / 源管理 / 路由(radar) 拆开

`webtool feed 36kr` 保持原样 —— 第一个词不是子命令时交给 get
(cls=_DefaultGroup 的默认命令)。
"""
import typer

from webtool.cli._ctx import (
    Fmt, NoCache, NoProxy, Output, _CTX, _entry_fn, _run,
)
from webtool.cli.app import app


from webtool.cli.commands._group import make_group

feed_app = make_group('get',
    'RSS/Atom 订阅: feed <源> | feed sources | feed radar')


def _build(fmt, output, no_proxy, no_cache, **kw):
    a = _CTX['args']
    a.sources = kw.get('sources') or []
    a.max = kw.get('max', 10)
    a.query = kw.get('query')
    a.threshold = kw.get('threshold', 0.15)
    a.no_url = kw.get('no_url', False)
    a.new_only = kw.get('new_only', False)
    a.add = kw.get('add') or []
    a.del_src = kw.get('del_src')
    a.mark = kw.get('mark') or []
    a.retest = kw.get('retest')
    a.pick = kw.get('pick')
    a.param = kw.get('param') or []
    a.example = kw.get('example', False)
    a.top = kw.get('top')
    a.from_url = kw.get('from_url')
    a.instance = kw.get('instance')
    a.cat = kw.get('cat')
    a.radar_refresh = kw.get('radar_refresh', False)
    a.no_xcheck = kw.get('no_xcheck', False)
    a.items = kw.get('items', False)
    return _run('data', _entry_fn('feed'), fmt, output, no_cache, no_proxy)


@feed_app.command('get')
def _get(sources: list[str] = typer.Argument(None, help='feed key 或任意 RSS/Atom URL; 无参数 = 清单+用法'),
         limit: int = typer.Option(10, '-n', '--limit', help='每源条数'),
         query: str = typer.Option(None, '-q', '--query', help='语义筛选词 (BM25 本地筛 + 相关度重排)'),
         threshold: float = typer.Option(0.15, '-t', '--threshold',
                                         help='语义筛选阈值 (0=只重排不过滤)'),
         new_only: bool = typer.Option(False, '--new-only', help='增量: 只显示上次抓取后的新条目'),
         no_url: bool = typer.Option(False, '--no-url', help='输出不带链接'),
         fmt: str = Fmt, output: str = Output,
         no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """抓取订阅源 (默认命令: webtool feed 36kr 等同 feed get 36kr)"""
    return _build(fmt, output, no_proxy, no_cache, sources=list(sources or []),
                  max=limit, query=query, threshold=threshold,
                  new_only=new_only, no_url=no_url)


@feed_app.command('sources')
def _sources(action: str = typer.Argument(None, help='list(默认) / add / del / mark / retest'),
             rest: list[str] = typer.Argument(None, help='add: NAME URL [描述] / del: KEY / mark: KEY [URL] [备注] / retest: KEY|all'),
             fmt: str = Fmt, output: str = Output,
             no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """订阅源管理: 增删 / 登记坏源 / 复查恢复"""
    act = (action or 'list').lower()
    rest = list(rest or [])
    if act == 'add':
        if len(rest) < 2:
            print('用法: webtool feed sources add NAME URL [描述]', file=_err())
            return 2
        return _build(fmt, output, no_proxy, no_cache, add=rest[:3])
    if act == 'del':
        if not rest:
            print('用法: webtool feed sources del KEY', file=_err())
            return 2
        return _build(fmt, output, no_proxy, no_cache, del_src=rest[0])
    if act == 'mark':
        if not rest:
            print('用法: webtool feed sources mark KEY [URL] [备注]', file=_err())
            return 2
        return _build(fmt, output, no_proxy, no_cache, mark=rest)
    if act == 'retest':
        return _build(fmt, output, no_proxy, no_cache,
                      retest=rest[0] if rest else 'all')
    if act == 'list':
        return _build(fmt, output, no_proxy, no_cache, sources=[])
    print(f'unknown: {action}\n用法: webtool feed sources [list|add|del|mark|retest]', file=_err())
    return 2


@feed_app.command('radar')
def _radar(keyword: str = typer.Argument(None, help='按关键词找路由 (可选)'),
           cat: str = typer.Option(None, '--cat', help='按分类过滤: new-media/programming/finance/...'),
           pick: str = typer.Option(None, '--pick', help='选第几条路由 (1 起) 或按模板子串匹配'),
           param: list[str] = typer.Option(None, '--param', help='给路由填占位符, 可重复: --param category=news'),
           example: bool = typer.Option(False, '--example', help='用官方 example 路径填参'),
           sample_row: int = typer.Option(None, '--sample-row', help='用第 N 条真实实例样例填参'),
           from_url: str = typer.Option(None, '--from-url', help='给定网页 URL, 反推路由'),
           instance: str = typer.Option(None, '--instance', help='指定实例前缀 (默认自动挑最快)'),
           refresh: bool = typer.Option(False, '--refresh', help='强制刷新路由库缓存 (默认 7 天)'),
           no_xcheck: bool = typer.Option(False, '--no-xcheck', help='不与官网 feed 交叉校验'),
           items: bool = typer.Option(False, '--items', help='把选定源的条目完整输出'),
           fmt: str = Fmt, output: str = Output,
           no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """路由库: 找 feed 地址 / 填参 / 交叉校验"""
    kw = dict(cat=cat, pick=pick, param=list(param or []), example=example,
              top=sample_row, from_url=from_url, instance=instance,
              radar_refresh=refresh, no_xcheck=no_xcheck, items=items)
    # do_feed 靠 sources[0]=='radar' 进雷达分支
    kw['sources'] = ['radar'] + ([keyword] if keyword else [])
    return _build(fmt, output, no_proxy, no_cache, **kw)


def _err():
    import sys
    return sys.stderr


@feed_app.callback(invoke_without_command=True)
def _root(ctx: typer.Context):
    """无参 = 列订阅源清单 (等价 feed get)"""
    if ctx.invoked_subcommand is None:
        raise typer.Exit(_build(None, None, False, False, sources=[]))

app.add_typer(feed_app, name='feed')
