"""cli 命令: 代理 / 插件 / 引擎 / MCP / 缓存 / 黑名单 / 升级 / 配置

从 app.py 拆出, 注册到共享的 Typer app。共享 plumbing 见 webtool.cli._ctx。
"""
import os
import sys
from typing import List

import typer

from webtool.net import proxy as _proxy
from webtool.cli._ctx import (
    Fmt, NoProxy, Output, _CTX, _run,
)
from webtool.cli._help import verbatim as _verbatim
from webtool.cli.app import app

def _pip_route_note(spec, env):
    """线路环境变量对**这个源**到底有没有用 —— 没用就得说出来

    ssh / git:// 源是子进程 ssh、git-daemon 出网, 它们眼里没有 HTTP(S)_PROXY,
    规则表判了代理也是白判。不说清楚就会变成"线路: 走代理"却实际直连。
    """
    from webtool.core import upgrade as _up
    _url, transport = _up.spec_url(spec)
    if transport in ('https', 'index', 'local'):
        return None                      # local 压根不出网, 谈不上代理白判
    if not (env or {}).get('HTTPS_PROXY'):
        return None                      # 本来就是直连, 没骗人
    return ('源 (%s) 的传输方式不认 HTTP(S)_PROXY —— 代理是给 http(s) 用的, '
            '这条实际直连。要真走代理, 换 https 源: '
            '`webtool upgrade --from git+https://…`' % transport)

def _pip_proxy_env(spec=None):
    """pip/git 是子进程, 代理只能靠环境变量给 —— 但如果拿我们自研的 httpx
    专家库那套再包一层就等于给自己加坑, 所以直接问 netx, 它负责看 rules.json。

    判线路要用**源的地址**, 不是写死的 github.com: `--from` 换源 (镜像/内网 gitlab)
    时, 那条源的线路跟 github 未必一样。
    """
    from webtool.core import upgrade as _up
    from webtool.net import netx
    route = netx.resolve_proxy('auto', _up.spec_url(spec)[0])
    if not route:
        # 规则表判为直连: 清掉环境里可能存在的代理, 别让子进程偷偷走代理
        # —— 但用户**显式**在环境里设了代理就不许动: 那是他的明确选择 (规则表没
        # 覆盖到的网络, 比如只在 shell 里挂的代理), 我们再塞 NO_PROXY=* 等于把
        # "我说的才算"盖到他头上 —— 症状就是"我明明 export 了代理还是直连".
        mine = {k: os.environ[k] for k in
                ('HTTPS_PROXY', 'https_proxy', 'HTTP_PROXY', 'http_proxy',
                 'ALL_PROXY', 'all_proxy') if os.environ.get(k)}
        if mine:
            return mine
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
        spec = args.spec or None
        env = _pip_proxy_env(spec)
        note = _pip_route_note(spec, env)
        if args.check_only:
            info = _up.check(spec, env_extra=env, note=note)
            print(_json.dumps(info, ensure_ascii=False, indent=2) if want_json
                  else _up.describe(info))
            # 退出码给脚本用: 0 已最新 / 1 有新版本 / 2 判不出来
            return {'up_to_date': 0, 'behind': 1}.get(info['state'], 2)
        res = _up.upgrade(spec, env_extra=env, note=note)
        if want_json:
            print(_json.dumps(res, ensure_ascii=False, indent=2))
        else:
            for line in res['log']:
                print(line)
        return 0 if res['ok'] else 1
    return _run(None, fn, fmt, output, False, False)

_PROXY_EPILOG = _verbatim("""子命令
  线路  get set unset test noproxy named
  凭据  passwd setpass delpass cert
  分流  rules tidy rule ruledel
  数据  geoip geosite geo asn

例
  webtool proxy set http://127.0.0.1:2080
  webtool proxy test
  webtool proxy rules
  webtool proxy named hk http://127.0.0.1:2081
  webtool proxy rule add '{"domain":["example.com"]}' proxy:hk
  webtool proxy geo""")


@app.command('proxy', epilog=_PROXY_EPILOG)
def proxy_cmd(action: str = typer.Argument(..., help='子命令, 完整清单见下方目录 (或直接跑 webtool proxy)'),
              value: str = typer.Argument(None, help='代理地址; 或 rule/cert 的子命令; 或试算用的 URL'),
              user: str = typer.Argument(None, help='setpass/delpass 的用户名; rule add 的 match JSON; ruledel 的序号'),
              act: str = typer.Argument(None, help='rule add 的动作: direct/proxy/block/proxy:<名字>'),
              first: bool = typer.Option(False, '--first', help='rule add: 插到规则表最前面 (默认追加到末尾, 会被前面的规则吃掉)'),
              pos: int = typer.Option(None, '--pos', help='rule add: 插到第 N 位 (0 = 最前)'),
              apply: bool = typer.Option(False, '--apply', help='tidy: 落盘 (默认干跑, 落盘前自动备份)'),
              url: str = typer.Option(None, '--url', help='test: 探活目标 (默认 google generate_204)')):
    """代理配置: 选线路 / 存凭据(密文) / 按域名-IP-端口-协议-GeoIP 分流"""
    a = _CTX['args']
    a.action, a.value, a.user, a.act = action, value, user, act
    a.first, a.pos, a.apply, a.url = first, pos, apply, url
    cfg = _proxy.load_config()
    if _CTX.get('proxy'):
        cfg['proxy'] = _CTX['proxy']
    return _proxy.handle(a, cfg) or 0

@app.command('pkg', context_settings={'allow_extra_args': True,
                                      'ignore_unknown_options': True})
def pkg_cmd(ctx: typer.Context,
            no_proxy: bool = NoProxy,
            proxy: str = typer.Option(None, '--proxy',
                                      help='强制线路: direct / 代理名 / 完整 URL '
                                           '(缺省按规则表判)')):
    """包管理器/git 等命令透传, 线路按规则表换算成环境变量交给子进程

    webtool pkg npm install lodash
    webtool pkg git clone https://github.com/x/y
    选项要写在命令名前面: webtool pkg --no-proxy pip install ...
    """
    cfg = _proxy.load_config()
    if _CTX.get('proxy'):
        cfg['proxy'] = _CTX['proxy']
    from webtool.cli import pkg as _pkg
    return _pkg.handle(list(ctx.args), cfg, no_proxy=no_proxy, proxy=proxy)

@app.command('engines')
def engines_cmd(action: str = typer.Argument('list', help='list=清单+冷却状态; test=实发体检; presets=引擎组合预设'),
                name: str = typer.Argument(None, help='test 时的引擎名; 省略=全部引擎'),
                check: bool = typer.Option(False, '--check', help='实发一次测试请求 (等价 engines test)'),
                query: str = typer.Option('python', '--query', help='test 用的测试词'),
                fmt: str = Fmt, output: str = Output):
    """引擎状态与预设"""
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
        from webtool.dao import cache
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

@app.command('update', hidden=True)          # 旧命令名别名
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
                kind: str = typer.Argument(None, help='engine, hot, site, source, extractor, resolver, filter, transformer, interceptor'),
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
