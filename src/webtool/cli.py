#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""webtool - Agent 友好的网页搜索/内容获取 CLI (零硬依赖)"""
import argparse, json, sys, os, re, time

from . import proxy as _proxy
from . import http as _http
from .search import do_search
from .fetch import do_fetch


def main(argv=None):
    p = argparse.ArgumentParser(prog='webtool',
                                description='Agent 友好的网页搜索与内容获取工具')
    p.add_argument('--proxy', help='临时代理, 覆盖配置文件')
    p.add_argument('--no-cache', action='store_true')
    sub = p.add_subparsers(dest='cmd', required=True)

    ps = sub.add_parser('search', help='多引擎网页搜索')
    ps.add_argument('query')
    ps.add_argument('-e', '--engine', default='bing,sogou', help='逗号分隔: bing,sogou,baidu,google')
    ps.add_argument('-n', '--max', type=int, default=8, help='每引擎结果数')
    ps.add_argument('-f', '--format', choices=['json', 'text'], default='json')
    ps.add_argument('--market', default='zh-CN', help='市场: zh-CN / en-US')
    ps.add_argument('--resolve-links', action='store_true', help='解析搜狗跳转链为真实 URL')
    ps.add_argument('--no-ad', action='store_true', help='过滤广告结果')
    ps.add_argument('--no-proxy', action='store_true', help='本次不走代理(覆盖配置)')
    ps.add_argument('--keep-ad', action='store_true', help='保留广告结果并标记 is_ad (默认已过滤)')
    ps.add_argument('--no-dedupe', action='store_true', help='关闭跨引擎去重')
    ps.add_argument('--no-semantic', action='store_true', help='关闭语义向量排序(纯位置权重)')

    pf = sub.add_parser('fetch', help='抓取 URL 并提取正文')
    pf.add_argument('url', nargs='?', help='要抓取的 URL')
    pf.add_argument('--url-file', help='从文件读多个 URL(每行一个)')
    pf.add_argument('-f', '--format', choices=['markdown', 'text', 'json', 'html'], default='markdown')
    pf.add_argument('--max-chars', type=int, default=0, help='正文截断字符数, 0=不截断')
    pf.add_argument('--raw', action='store_true', help='跳过正文提取, 输出原始 HTML')
    pf.add_argument('--with-metadata', action='store_true', help='json 格式附带标题/作者/日期')

    pp = sub.add_parser('proxy', help='代理配置')
    pp.add_argument('action', choices=['get', 'set', 'unset', 'test'])
    pp.add_argument('value', nargs='?', help='代理地址, 如 http://127.0.0.1:2080 或 socks5://...')

    pe = sub.add_parser('engines', help='查看搜索引擎状态')
    pe.add_argument('--check', action='store_true', help='实际发一次测试请求')

    pcache = sub.add_parser('cache', help='缓存管理')
    pcache.add_argument('action', choices=['clear', 'info'])

    psite = sub.add_parser('site', help='站内搜索(知名站点官方接口, 与传统搜索引擎区分)')
    psite.add_argument('site', nargs='?', help='站点 key, `webtool site list` 查看全部')
    psite.add_argument('query', nargs='?', help='站内搜索词')
    psite.add_argument('-n', '--max', type=int, default=10)
    psite.add_argument('-f', '--format', choices=['json', 'text'], default='json')
    psite.add_argument('--lang', default='zh', help='wikipedia 语言版本')
    psite.add_argument('--no-proxy', action='store_true', help='本次不走代理')

    args = p.parse_args(argv)
    cfg = _proxy.load_config()
    if args.proxy:
        cfg['proxy'] = args.proxy

    try:
        if args.cmd == 'search':
            if args.keep_ad:
                # --keep-ad: 只标记不过滤
                from .search import do_search_raw
                out = do_search_raw(args, cfg)
            else:
                args.no_ad = True
                out = do_search(args, cfg)
        elif args.cmd == 'fetch':
            out = do_fetch(args, cfg)
        elif args.cmd == 'proxy':
            out = _proxy.handle(args, cfg)
        elif args.cmd == 'engines':
            from .engines import status as _status_mod
            out = _status_mod.status(args, cfg)
        elif args.cmd == 'cache':
            from .cache import handle
            out = handle(args, cfg)
        elif args.cmd == 'site':
            from .sitesearch import do_site
            out = do_site(args, cfg)
        return 0
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    sys.exit(main())
