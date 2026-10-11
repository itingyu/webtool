#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""webtool - Agent 友好的网页搜索/内容获取 CLI (零硬依赖, 纯 argparse, 无框架)

参数标准化约定 (v1.6.1, 全子命令统一):
- 通用短参: -n 条数 / -f 输出格式 / -o 输出文件 / -q 查询词 / -t 阈值 / -e 引擎
- 布尔开关一律 --no-* 关闭默认行为 (argparse 自动大小写敏感; 短参全小写)
- 同义参数跨命令同名同义: --no-proxy/--no-cache/--max/--format 全局一致
- search/fetch/site/rank 四个数据命令均支持 -o 落盘 (默认按 -f 补扩展名)
- 大小写: 短参区分 ( -n 与 -N 不同, 后者不存在 ); -f 值不区分 (JSON==json)
"""
import argparse, json, sys, os, re, time

from . import proxy as _proxy
from . import http as _http
from .output import emit

# ---------- 公共参数组 (跨子命令复用, 保证同名同义) ----------

def _add_common_output(g):
    """数据类子命令通用: 输出格式 + 落盘"""
    g.add_argument('-f', '--format', dest='format', default=None,
                   choices=['json', 'text', 'markdown', 'md', 'txt', 'JSON', 'TEXT', 'MARKDOWN', 'MD', 'TXT'],
                   help='输出格式 json/text/markdown (大小写不敏感; md=markdown, txt=text)')
    g.add_argument('-o', '--output', dest='output', default=None,
                   help='输出到文件 (默认按 -f 补扩展名 .json/.md/.txt; 目录则自动命名; '
                        '-o - 强制 stdout)')


def _add_common_net(g):
    g.add_argument('--no-proxy', action='store_true', help='本次不走代理(覆盖配置)')
    g.add_argument('--no-cache', action='store_true', help='跳过缓存')


def _norm_fmt(v, default):
    """-f 值归一化: 大小写不敏感 + md/txt 别名"""
    if not v:
        return default
    x = v.strip().lower()
    return {'md': 'markdown', 'txt': 'text'}.get(x, x)


def main(argv=None):
    p = argparse.ArgumentParser(prog='webtool',
                                description='Agent 友好的网页搜索与内容获取工具')
    p.add_argument('--proxy', help='临时代理, 覆盖配置文件')
    p.add_argument('--no-cache', action='store_true')
    sub = p.add_subparsers(dest='cmd', required=True)

    ps = sub.add_parser('search', help='多引擎网页搜索')
    ps.add_argument('query')
    ps.add_argument('-e', '--engine', default=None,
                    help='逗号分隔: bing,sogou,baidu,google,marginalia (默认 bing,sogou,baidu)')
    ps.add_argument('-n', '--max', type=int, default=8, help='每引擎结果数')
    _add_common_output(ps)
    _add_common_net(ps)
    ps.add_argument('--market', default='zh-CN', help='市场: zh-CN / en-US')
    ps.add_argument('--no-resolve', action='store_true',
                    help='关闭跳转链解码 (sogou/baidu link, gnews articles)')
    ps.add_argument('--keep-ad', action='store_true', help='保留广告结果并标记 is_ad (默认已过滤)')
    ps.set_defaults(no_ad=True)
    ps.add_argument('--no-dedupe', action='store_true', help='关闭跨引擎去重')
    ps.add_argument('--no-semantic', action='store_true', help='关闭语义向量排序(纯位置权重)')
    ps.add_argument('--no-retry', action='store_true', help='关闭低召回自动重试(默认开启)')
    ps.add_argument('--operators', default='passthrough',
                    choices=['passthrough', 'strip', 'strict'],
                    help='高级操作符路由: passthrough=原样透传(默认) / '
                         'strip=静默剔除该引擎不支持的操作符 / '
                         'strict=有引擎不支持就报错。'
                         '支持 site: intitle: inurl: -词')
    ps.add_argument('--block', action='append', default=[],
                    help='临时追加黑名单域名, 可多次')
    ps.add_argument('--allow', action='append', default=[],
                    help='临时白名单例外(优先于黑名单), 可多次')
    ps.add_argument('--no-blocklist', action='store_true', help='关闭黑名单过滤')

    pf = sub.add_parser('fetch', help='抓取 URL 并提取正文')
    pf.add_argument('url', nargs='?', help='要抓取的 URL')
    pf.add_argument('--url-file', help='从文件读多个 URL(每行一个)')
    _add_common_output(pf)
    _add_common_net(pf)
    pf.set_defaults(format_default='markdown')
    pf.add_argument('--max-chars', type=int, default=0, help='正文截断字符数, 0=不截断')
    pf.add_argument('--raw', action='store_true', help='跳过正文提取, 输出原始 HTML')
    pf.add_argument('--with-metadata', action='store_true', help='json 格式附带标题/作者/日期')
    pf.add_argument('--profile', default=None,
                    help='传输指纹档案: chrome131_win/mac/linux/android, safari18_4_ios 等 '
                         '(默认桌面 chrome; 移动站/拿不到数据时试 android/ios 档案)')

    pp = sub.add_parser('proxy', help='代理配置')
    pp.add_argument('action', choices=['get', 'set', 'unset', 'test'])
    pp.add_argument('value', nargs='?', help='代理地址, 如 http://127.0.0.1:2080 或 socks5://...')

    pe = sub.add_parser('engines', help='搜索引擎状态: list(默认,只读本地) / test(实发请求)')
    pe.add_argument('action', nargs='?', default='list',
                    choices=['list', 'test'],
                    help='list=列引擎清单+冷却状态(不发请求); test=实发一次搜索体检 (默认 list)')
    pe.add_argument('name', nargs='?',
                    help='test 时的引擎名 (bing/sogou/baidu/google/marginalia); 省略=全部引擎')
    pe.add_argument('--check', action='store_true',
                    help='实发一次测试请求 (等价 `engines test`)')
    pe.add_argument('--query', default='python',
                    help='test 用的测试词 (默认 python)')

    pcache = sub.add_parser('cache', help='缓存管理')
    pcache.add_argument('action', choices=['clear', 'info'])

    pbl = sub.add_parser('blocklist', help='黑名单管理 (低质量站点)')
    pbl.add_argument('action', choices=['show', 'add', 'remove', 'reset'])
    pbl.add_argument('domain', nargs='?', help='域名, 如 csdn.net')
    pbl.add_argument('--allow', action='store_true', help='add/remove 白名单例外')

    pcf = sub.add_parser('config', help='配置管理: 代理/黑名单/权重阈值/默认引擎等')
    pcf.add_argument('action', choices=['list', 'get', 'set', 'unset'])
    pcf.add_argument('key', nargs='?')
    pcf.add_argument('value', nargs='?')

    psite = sub.add_parser('site', help='站内搜索(知名站点官方接口, 与传统搜索引擎区分)')
    psite.add_argument('site', nargs='?', help='站点 key, `webtool site list` 查看全部')
    psite.add_argument('query', nargs='?', help='站内搜索词')
    psite.add_argument('-n', '--max', type=int, default=10)
    psite.add_argument('--lang', default='zh', help='wikipedia 语言版本')
    _add_common_output(psite)
    _add_common_net(psite)

    phot = sub.add_parser('rank', help='榜单聚合: 无参=榜单清单; 指定源=按源分组原序; -q 语义筛选')
    phot.add_argument('sources', nargs='*',
                      help='榜单源 key, 空格分隔; 无参数 = 榜单清单+用法 (同 `rank list`)')
    phot.add_argument('-q', '--query', default=None,
                      help='语义筛选词: 支持搜索的源透传站内过滤, 其余源拉榜后本地 BM25 筛选+跨源重排')
    phot.add_argument('-t', '--threshold', type=float, default=0.15,
                      help='语义筛选阈值 0-1 (默认 0.15; 0=只列清单不过滤不重排; 无 -q 忽略)')
    phot.add_argument('-n', '--max', type=int, default=10, help='每源条数')
    _add_common_output(phot)
    _add_common_net(phot)

    pfeed = sub.add_parser('feed', help='RSS/Atom 订阅源抓取 (官方 feed + 任意 URL; 支持增量)')
    pfeed.add_argument('sources', nargs='*',
                       help='feed key 或任意 RSS/Atom URL; 无参数 = 清单+用法')
    pfeed.add_argument('-n', '--max', type=int, default=10, help='每源条数')
    pfeed.add_argument('-q', '--query', default=None,
                       help='语义筛选词 (BM25 本地筛 + 按相关度重排)')
    pfeed.add_argument('-t', '--threshold', type=float, default=0.15,
                       help='语义筛选阈值 (默认 0.15; 0=只重排不过滤)')
    pfeed.add_argument('--new-only', action='store_true',
                       help='增量: 只显示上次抓取后的新条目 (状态存 ~/.webtool/feed_state.json)')
    pfeed.add_argument('--add', nargs='+', metavar=('NAME', 'URL'),
                       help='添加自定义源: --add NAME URL [描述] (存 ~/.webtool/feeds.json)')
    pfeed.add_argument('--del', dest='del_src', metavar='NAME',
                       help='删除自定义源 (--del NAME; 预设源不可删)')
    pfeed.add_argument('--mark', nargs='+', metavar=('KEY', 'NOTE'),
                       help='人工登记坏源: --mark KEY [URL] "原因备注" (存健康登记表)')
    pfeed.add_argument('--retest', metavar='KEY', default=None,
                       help='复查坏源是否恢复: --retest KEY 或 --retest all; 恢复即移除')
    _rg = pfeed.add_argument_group(
        'feed radar 专用 (查 RSSHub 路由 / 填参数)')
    _rg.add_argument('--pick', metavar='N|TEMPLATE', default=None,
                     help='选定命中的第几条路由 (列表序号 1 起) 或按模板子串匹配; '
                          '不给则自动取 heat 最高的一条')
    _rg.add_argument('--param', action='append', default=[], metavar='K=V',
                     help='给选中的那条路由填占位符, 可重复: --param category=newsflashes')
    _rg.add_argument('--example', action='store_true',
                     help='用官方 example 路径填参出订阅 URL')
    _rg.add_argument('--top', type=int, metavar='N', default=None,
                     help='用第 N 条真实实例样例 (topFeeds, 1 起) 填参')
    _rg.add_argument('--from-url', metavar='URL', default=None,
                     help='给定网页 URL, 用 radar.source 模式反推路由')
    _rg.add_argument('--instance', metavar='PREFIX', default=None,
                     help='指定实例前缀 (默认自动挑最快可用的)')
    _rg.add_argument('--cat', metavar='CAT', default=None,
                     help='按分类过滤路由 (new-media/programming/finance/...)')
    _rg.add_argument('--radar-refresh', action='store_true',
                     help='强制刷新路由库缓存 (默认 7 天)')
    _rg.add_argument('--no-xcheck', action='store_true',
                     help='不与官网 feed 交叉校验 (默认校验并据此决定取数源)')
    _rg.add_argument('--items', action='store_true',
                     help='校验后把选定源的条目完整输出 (-f 生效); '
                          '默认只报校验结论与耗时, 不重复打印条目')
    _add_common_output(pfeed)
    _add_common_net(pfeed)

    args = p.parse_args(argv)
    cfg = _proxy.load_config()
    if args.proxy:
        cfg['proxy'] = args.proxy

    # -f 归一化 (含默认值: fetch=markdown, 其余数据命令=json)
    if getattr(args, 'format', None) is not None or hasattr(args, 'output'):
        dflt = getattr(args, 'format_default', None) or 'json'
        args.format = _norm_fmt(getattr(args, 'format', None), dflt)

    # 输出捕获: 数据命令 print → 捕获后走 emit (统一 -o)
    data_cmds = {'search', 'fetch', 'site', 'rank', 'feed'}

    try:
        if args.cmd in data_cmds:
            import io
            from contextlib import redirect_stdout
            buf = io.StringIO()
            rc = None
            with redirect_stdout(buf):
                rc = _dispatch(args, cfg)
            if rc not in (0, None):
                return rc
            emit(buf.getvalue(), args.format, getattr(args, 'output', None))
            return 0
        return _dispatch(args, cfg) or 0
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        return 130


def _dispatch(args, cfg):
    """子命令分发 (数据命令的 stdout 由调用方捕获)"""
    if args.cmd == 'search':
        if args.keep_ad:
            from .search import do_search_raw
            return do_search_raw(args, cfg)
        from .search import do_search
        return do_search(args, cfg)
    if args.cmd == 'fetch':
        from .fetch import do_fetch
        return do_fetch(args, cfg)
    if args.cmd == 'proxy':
        return _proxy.handle(args, cfg)
    if args.cmd == 'engines':
        from .engines import status as _status_mod
        return _status_mod.status(args, cfg)
    if args.cmd == 'cache':
        from .cache import handle
        return handle(args, cfg)
    if args.cmd == 'site':
        from .sitesearch import do_site
        return do_site(args, cfg)
    if args.cmd == 'rank':
        from .rank import do_rank
        return do_rank(args, cfg)
    if args.cmd == 'feed':
        from .feed import do_feed
        return do_feed(args, cfg)
    if args.cmd == 'blocklist':
        from .blocklist import handle_cli
        return handle_cli(args)
    if args.cmd == 'config':
        from .configcmd import handle
        return handle(args)
    return 0


if __name__ == '__main__':
    sys.exit(main())
