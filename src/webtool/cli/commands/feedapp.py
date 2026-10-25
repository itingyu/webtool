"""feed: 抓取 / 源管理 / 路由(radar) 拆开

`webtool feed 36kr` 保持原样 —— 第一个词不是子命令时交给 get
(cls=_DefaultGroup 的默认命令)。
"""
import typer

from webtool.cli.commands._group import make_group

from webtool.cli._ctx import (
    Fmt, NoCache, NoProxy, Output, _CTX, _entry_fn, _run,
)
from webtool.cli.app import app



feed_app = make_group('get',
    'RSS/Atom 订阅: feed <源> | feed sources | feed radar')


def _build(fmt, output, no_proxy, no_cache, **kw):
    a = _CTX['args']
    a.sources = kw.get('sources') or []
    a.max = kw.get('max', 10)
    a.query = kw.get('query')
    a.threshold = kw.get('threshold', 0.15)
    a.no_url = kw.get('no_url', False)
    a.meta = kw.get('meta', False)
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
    a.radar = kw.get('radar', False)
    return _run('data', _entry_fn('feed'), fmt, output, no_cache, no_proxy)


@feed_app.command('health')
def _feed_health(fmt: str = Fmt, output: str = Output,
                 no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """坏源登记表 (官网挂了的站)"""
    return _build(fmt, output, no_proxy, no_cache, sources=['health'])


@feed_app.command('instances')
def _feed_instances(fmt: str = Fmt, output: str = Output,
                    no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """探活公共 RSSHub 实例"""
    return _build(fmt, output, no_proxy, no_cache, sources=['instances'])


@feed_app.command('get')
def _get(sources: list[str] = typer.Argument(None, help='feed key 或任意 RSS/Atom URL; 无参数 = 清单+用法'),
         limit: int = typer.Option(10, '-n', '--limit', help='每源条数'),
         query: str = typer.Option(None, '-q', '--query', help='语义筛选词 (BM25 本地筛 + 相关度重排)'),
         threshold: float = typer.Option(0.15, '-t', '--threshold',
                                         help='语义筛选阈值 (0=只重排不过滤)'),
         new_only: bool = typer.Option(False, '--new-only', help='增量: 只显示上次抓取后的新条目'),
         no_url: bool = typer.Option(False, '--no-url', help='输出不带链接'),
         meta: bool = typer.Option(False, '--meta',
                                   help='附带作者/分类等元数据 (默认只带发布时间)'),
         param: list[str] = typer.Option(None, '-p', '--param',
                                         help='给带参路由填值, 可重复: -p category=news'),
         example: bool = typer.Option(False, '-e', '--example',
                                      help='用路由的官方 example 路径 (免填参)'),
         instance: str = typer.Option(None, '-I', '--instance',
                                      help='RSSHub 实例前缀 (默认挑最快)'),
         fmt: str = Fmt, output: str = Output,
         no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """抓取订阅源 (默认命令: webtool feed 36kr 等同 feed get 36kr)"""
    return _build(fmt, output, no_proxy, no_cache, sources=list(sources or []),
                  max=limit, query=query, threshold=threshold,
                  new_only=new_only, no_url=no_url, meta=meta, param=param,
                  example=example, instance=instance)


sources_app = make_group('list', '订阅源: 清单 / 增删 / 登记坏源 / 复查恢复')

@sources_app.command('list')
def _src_list(radar: bool = typer.Option(False, '--radar',
                                         help='列出 RSSHub 派生源 (按分类分组)'),
              cat: str = typer.Option(None, '-c', '--cat',
                                      help='只看某分类, 配合 --radar (如 finance)'),
              fmt: str = Fmt, output: str = Output,
              no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """列出订阅源"""
    return _build(fmt, output, no_proxy, no_cache, sources=[], radar=radar,
                  cat=cat)

@sources_app.command('find')
def _src_find(word: str = typer.Argument(..., help='键名/站名/域名/描述 关键词'),
              cat: str = typer.Option(None, '-c', '--cat',
                                      help='按分类过滤 (RSSHub 派生源)'),
              limit: int = typer.Option(20, '-n', '--limit', help='最多几条'),
              fmt: str = Fmt, output: str = Output,
              no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """模糊搜源: 键名 / 站名 / 域名 / 描述"""
    return _build(fmt, output, no_proxy, no_cache,
                  sources=['find', word], cat=cat, max=limit)


@sources_app.command('add')
def _src_add(name: str = typer.Argument(..., help='源名'),
             url: str = typer.Argument(..., help='RSS/Atom 地址'),
             desc: str = typer.Argument(None, help='描述 (可选)'),
             fmt: str = Fmt, output: str = Output,
             no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """新增订阅源"""
    return _build(fmt, output, no_proxy, no_cache,
                  add=[name, url] + ([desc] if desc else []))

@sources_app.command('del')
def _src_del(key: str = typer.Argument(..., help='源名'),
             fmt: str = Fmt, output: str = Output,
             no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """删除订阅源"""
    return _build(fmt, output, no_proxy, no_cache, del_src=key)

@sources_app.command('mark')
def _src_mark(key: str = typer.Argument(..., help='源名'),
              url: str = typer.Argument(None, help='新的地址 (可选)'),
              note: str = typer.Argument(None, help='备注 (可选)'),
              fmt: str = Fmt, output: str = Output,
              no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """登记坏源 / 改地址"""
    return _build(fmt, output, no_proxy, no_cache,
                  mark=[x for x in (key, url, note) if x])

@sources_app.command('sync')
def _src_sync(force: bool = typer.Option(False, '-R', '--refresh',
                                         help='强制重拉 RSSHub 路由库再物化'),
              fmt: str = Fmt, output: str = Output,
              no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """把 RSSHub 路由库重新物化成 feed 源"""
    return _build(fmt, output, no_proxy, no_cache, sources=['sync'],
                  radar_refresh=force)


@sources_app.command('retest')
def _src_retest(key: str = typer.Argument('all', help='源名或 all'),
                fmt: str = Fmt, output: str = Output,
                no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """复查坏源是否恢复"""
    return _build(fmt, output, no_proxy, no_cache, retest=key or 'all')


radar_app = make_group('find', '路由库: 找 feed 地址 / 反推 / 填参')

def _radar_build(cat=None, pick=None, param=None, example=False, top=None,
                 from_url=None, instance=None, refresh=False,
                 no_xcheck=False, items=False, keyword=None,
                 fmt='text', output=None, no_proxy=False, no_cache=False):
    kw = dict(cat=cat, pick=pick, param=list(param or []), example=example,
              top=top, from_url=from_url, instance=instance,
              radar_refresh=refresh, no_xcheck=no_xcheck, items=items)
    kw['sources'] = ['radar'] + ([keyword] if keyword else [])
    return _build(fmt, output, no_proxy, no_cache, **kw)

@radar_app.command('find')
def _radar_find(keyword: str = typer.Argument(None, help='按关键词找路由 (可选)'),
                cat: str = typer.Option(None, '-c', '--cat',
                                        help='分类: new-media/programming/finance/...'),
                instance: str = typer.Option(None, '-I', '--instance',
                                             help='指定实例前缀 (默认自动挑最快)'),
                refresh: bool = typer.Option(False, '-R', '--refresh',
                                             help='强制刷新路由库缓存 (默认 7 天)'),
                no_xcheck: bool = typer.Option(False, '--no-xcheck',
                                               help='不与官网 feed 交叉校验'),
                pick: str = typer.Option(None, '--pick',
                                         help='选定第 N 条 (1 起) 或模板子串'),
                param: list[str] = typer.Option(None, '-p', '--param',
                                                help='给选中路由填参, 可重复: -p category=news'),
                example: bool = typer.Option(False, '-e', '--example',
                                             help='用官方 example 路径取数 (免填参)'),
                sample_row: int = typer.Option(None, '-r', '--sample-row', '--top',
                                               help='用第 N 条真实样例填参'),
                items: bool = typer.Option(False, '-i', '--items',
                                           help='把选中源的条目完整输出'),
                fmt: str = Fmt, output: str = Output,
                no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """按关键词/分类找 feed 路由 (可选定并试跑)"""
    return _radar_build(cat=cat, instance=instance, refresh=refresh,
                        no_xcheck=no_xcheck, keyword=keyword, pick=pick,
                        param=param, example=example, top=sample_row,
                        items=items, fmt=fmt, output=output,
                        no_proxy=no_proxy, no_cache=no_cache)

@radar_app.command('url')
def _radar_url(url: str = typer.Argument(..., help='网页 URL, 反推它对应的路由'),
               instance: str = typer.Option(None, '-I', '--instance'),
               refresh: bool = typer.Option(False, '-R', '--refresh'),
               fmt: str = Fmt, output: str = Output,
               no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """给网页 URL, 反推 feed 路由"""
    return _radar_build(from_url=url, instance=instance, refresh=refresh,
                        fmt=fmt, output=output,
                        no_proxy=no_proxy, no_cache=no_cache)

@sources_app.callback(invoke_without_command=True)
def _sources_root(ctx: typer.Context):
    """无参 = 列订阅源"""
    if ctx.invoked_subcommand is None:
        raise typer.Exit(_build('text', None, False, False, sources=[]))


@radar_app.callback(invoke_without_command=True)
def _radar_root(ctx: typer.Context):
    """无参 = 路由库总览"""
    if ctx.invoked_subcommand is None:
        raise typer.Exit(_radar_build())


feed_app.add_typer(sources_app, name='sources')
feed_app.add_typer(radar_app, name='radar')

def _err():
    import sys
    return sys.stderr


@feed_app.callback(invoke_without_command=True)
def _root(ctx: typer.Context):
    """无参 = 列订阅源清单 (等价 feed get)"""
    if ctx.invoked_subcommand is None:
        raise typer.Exit(_build(None, None, False, False, sources=[]))

app.add_typer(feed_app, name='feed')
