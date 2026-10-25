"""cli 命令: 代理 / 插件 / 引擎 / MCP / 缓存 / 黑名单 / 升级 / 配置

从 app.py 拆出, 注册到共享的 Typer app。共享 plumbing 见 webtool.cli._ctx。
"""
import os
import re
import sys
from typing import List

import typer

from webtool.net import proxy as _proxy
from webtool.cli._ctx import (
    Fmt, NoProxy, Output, _CTX, _run,
)
from webtool.cli._help import verbatim as _verbatim
from webtool.cli.app import app
from webtool.core.logging import get_logger

logger = get_logger(__name__)

def _pip_route_note(spec, env):
    """线路对**这个源**到底有没有用 —— 没用就得说出来

    ssh / git:// 源是子进程 ssh、git-daemon 出网, 它们眼里没有 http.proxy,
    规则表判了代理也是白判。判据要自己问规则表 (代理现在塞在 GIT_CONFIG_* 里,
    从环境变量上看不出来), 否则就会变成"线路: 走代理"却实际直连。
    """
    from webtool.core import upgrade as _up
    url, transport = _up.spec_url(spec)
    if transport not in ('ssh', 'git'):
        return None                      # https/index 走 http 栈, 能吃到代理; local 不出网
    from webtool.net import netx
    if not netx.resolve_proxy('auto', url):
        return None                      # 本来就是直连, 没骗人
    return ('源 (%s) 的传输方式吃不到代理 —— 代理是给 http(s) 用的, '
            '这条实际直连。要真走代理, 换 https 源: '
            '`webtool upgrade --from git+https://…`' % transport)

def _pip_tls_env(spec=None):
    """证书与"别卡死"的环境变量, 能给的都给子进程

    pip/git 读不到 webtool 的配置, 只能在环境变量这层对齐 —— 少给一项, 它就会
    自己撞一次墙:
      - 有信任根 → 指给它 (PIP_CERT / GIT_SSL_CAINFO / *_CA_BUNDLE), 校验照做
      - `ssl_verify off` (默认值 —— 没配就是它) → 说清楚别校验
        (git 有开关 `GIT_SSL_NO_VERIFY`; pip 没有全局开关, 只能按主机放行)
      - 不弹交互: 要凭据时立刻失败, 而不是挂在那儿等人输入 —— 脚本里最难查
        的一种"卡住"就是它
      - 超时与重试给死: 网络抖一下不该让整个升级失败
    没关校验也没信任根时, 只留"别卡死"那几项, 不替用户把证书校验降级。
    """
    from webtool.core import upgrade as _up
    from webtool.net import tls
    env = {'GIT_TERMINAL_PROMPT': '0', 'PIP_NO_INPUT': '1',
           'PIP_DEFAULT_TIMEOUT': '60', 'PIP_RETRIES': '3'}
    for cand in tls.ca_bundle_candidates():
        if cand and os.path.isfile(str(cand)):
            bundle = str(cand)
            env.update({'PIP_CERT': bundle, 'GIT_SSL_CAINFO': bundle,
                        'REQUESTS_CA_BUNDLE': bundle, 'CURL_CA_BUNDLE': bundle})
            break
    url, transport = _up.spec_url(spec)
    try:
        if tls.policy(url) is not False:
            return env
    except Exception:
        return env
    env['GIT_SSL_NO_VERIFY'] = '1'
    env['PYTHONHTTPSVERIFY'] = '0'
    hosts = []
    m = re.match(r'https?://([^/:]+)', url or '')
    if m:
        hosts.append(m.group(1))
    if transport == 'index':                 # 还得放行托管包文件的那台
        hosts += ['pypi.org', 'files.pythonhosted.org']
    if hosts:
        env['PIP_TRUSTED_HOST'] = ' '.join(dict.fromkeys(hosts))
    return env


def _pip_proxy_env(spec=None):
    """子进程的环境: 证书策略见 _pip_tls_env, 代理**只给 git**, 不给 pip

    判线路用**源的地址**, 不是写死的 github.com: `--from` 换源 (镜像/内网 gitlab)
    时, 那条源的线路跟 github 未必一样。

    代理为什么不塞 HTTP_PROXY 系变量: 那会把 pip 自己的请求也一起带走。pip 要的是
    PyPI (多半直连可达), 被代理带着反而容易卡死, 报出来还是"代理连不上" —— 跟真因
    差着十万八千里。真正需要代理的只有 git 那条腿, 所以用 GIT_CONFIG_* 单独塞给它。
    """
    from webtool.core import upgrade as _up
    from webtool.net import netx
    out = dict(_pip_tls_env(spec))
    url, transport = _up.spec_url(spec)
    route = netx.resolve_proxy('auto', url)
    if not route:
        # 规则表判直连: 子进程是 dict(os.environ, **env) 起的, 用户 shell 里的
        # HTTP(S)_PROXY 会漏进去, 等于绕过规则表 —— 显式关掉
        out.update({'NO_PROXY': '*', 'no_proxy': '*'})
        return out
    if transport != 'https':
        # 只有 git-over-https 这条腿要代理: ssh / git:// 吃不到 http.proxy, index
        # 则是 pip 自己在拉包 —— pip 不该走代理 (它要的 PyPI 多半直连可达), 免得被
        # 代理带着卡死, 报出来还成了"代理连不上"。
        return out or None
    # GIT_CONFIG_* 是 git 认的"用环境变量塞配置"写法 (2.31+), 只落在 git 身上
    out.update({'GIT_CONFIG_COUNT': '1',
                'GIT_CONFIG_KEY_0': 'http.proxy',
                'GIT_CONFIG_VALUE_0': route})
    try:
        from webtool.net.proxy import load_config
        _want = str((load_config() or {}).get('pip_proxy', 'off'))
    except Exception:
        _want = 'off'
    if _want.strip().lower() in ('on', '1', 'true', 'yes'):
        # pip_proxy on: 连 pip 自己的请求也交给代理。默认不给 —— pip 要的 PyPI 多半
        # 直连可达, 带上代理反而容易卡死, 还报成"代理连不上"。企业网里 pip 只能靠
        # 代理出网时才开这个。
        out.update({'HTTP_PROXY': route, 'HTTPS_PROXY': route, 'ALL_PROXY': route,
                    'http_proxy': route, 'https_proxy': route,
                    'all_proxy': route,
                    'NO_PROXY': 'localhost,127.0.0.1,::1',
                    'no_proxy': 'localhost,127.0.0.1,::1'})
    keys = ','.join(sorted(out))
    logger.debug('upgrade | 给子进程的环境: %s (代理只给 git: %s)', keys, route)
    return out

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
        if res.get('ok') and str(cfg.get('upgrade_deps', 'on')).lower() not in (
                'off', '0', 'false', 'no'):
            # 升级只换了自己那份代码 (--no-deps), 依赖得有地方补: 按声明的清单走一趟。
            # pip 只补缺的, 已满足的不动 —— 全齐时它连索引都不问, 离线也不会卡。
            reqs = _up.dep_list()
            if reqs:
                import tempfile as _tf
                fd, path = _tf.mkstemp(prefix='webtool-deps-', suffix='.txt')
                os.close(fd)
                with open(path, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(reqs) + '\n')
                rc, out, err = _up.pip(['install', '-r', path], env_extra=env)
                if rc == 0:
                    res['log'].append('依赖: 齐了 (缺的已补, 已有的没动)')
                else:
                    tail = [l for l in (err or out or '').splitlines() if l.strip()]
                    res['log'].append('依赖没补齐: %s' % ' | '.join(tail[-3:]))
        if want_json:
            print(_json.dumps(res, ensure_ascii=False, indent=2))
        else:
            for line in res['log']:
                print(line)
        return 0 if res['ok'] else 1
    return _run(None, fn, fmt, output, False, False)

_PROXY_EPILOG = _verbatim("""子命令
  线路  get set unset test named noproxy
  凭据  passwd setpass delpass cert
  分流  rules rule add|del tidy
  数据  geoip geosite geo asn

例
  webtool proxy set http://127.0.0.1:7890     # 端口换成你代理客户端监听的 (常见 7890/clash, 10809/v2rayN)
  webtool proxy test
  webtool proxy rules
  webtool proxy named hk http://127.0.0.1:2081
  webtool proxy rule add '{"domain":["example.com"]}' proxy:hk
  webtool proxy geo

注: 上面都是举例地址, 没有任何一个是 webtool 的内置默认值 —— 没配就是直连。""")

proxy_app = typer.Typer(add_completion=False, no_args_is_help=True,
                        rich_markup_mode=None, pretty_exceptions_enable=False, epilog=_PROXY_EPILOG,
                        context_settings={'help_option_names': ['-h', '--help']},
                        help='代理配置: 选线路 / 存凭据(密文) / 按域名-IP-端口-协议-GeoIP 分流')
rule_app = typer.Typer(add_completion=False, no_args_is_help=True,
                       rich_markup_mode=None, pretty_exceptions_enable=False,
                       context_settings={'help_option_names': ['-h', '--help']},
                       help='规则表: add <match JSON> <动作> | del <序号>')
proxy_app.add_typer(rule_app, name='rule')

_ProxyUrl = typer.Argument(None, help='代理地址, 如 http://127.0.0.1:7890')
_ProxyName = typer.Argument(None, help='命名代理的名字; 或 list / del')


def _p(action, **kw):
    """调 proxy 各动作; 参数语义按各 handler 自己的字段传, 不再做位置换位"""
    from webtool.net import proxy as _P
    cfg = _P.load_config()
    if _CTX.get('proxy'):
        cfg['proxy'] = _CTX['proxy']
    return _P.dispatch(action, cfg, **kw)


@proxy_app.command('get', help='查看当前线路、命名代理与规则来源')
def proxy_get():
    return _p('get')


@proxy_app.command('set', help='设全局线路 (URL 不许带明文密码, 用 setpass 存)')
def proxy_set(url: str = typer.Argument(..., help='代理地址, 如 http://127.0.0.1:7890')):
    return _p('set', value=url)


@proxy_app.command('unset', help='取消全局线路, 回到直连/按规则走')
def proxy_unset():
    return _p('unset')


@proxy_app.command('test', help='探活一条线路, 并说明它与目标 URL 实际走的线是否一致')
def proxy_test(which: str = typer.Argument(None, help='要测的线路: 名字或 URL (缺省测当前线路)'),
               url: str = typer.Option(None, '--url', help='探活目标 (默认 google generate_204)')):
    return _p('test', value=which, url=url)


@proxy_app.command('named', help='命名代理: named <名字> <URL> | named del <名字> | named (列全部)')
def proxy_named(name: str = _ProxyName, url: str = _ProxyUrl):
    return _p('named', value=name, user=url)


@proxy_app.command('noproxy', help='试算常见站点各走哪条线, 确认分流符合预期')
def proxy_noproxy(urls: str = typer.Argument(None, help='逗号分隔的 URL 列表 (缺省用内置样例)')):
    return _p('noproxy', value=urls)


@proxy_app.command('passwd', help='交互式设置全局线路的密码并加密存进保险库')
def proxy_passwd():
    return _p('passwd')


@proxy_app.command('setpass', help='存一条凭据: setpass <用户名> [密码] (密码留空则交互输入)')
def proxy_setpass(user: str = typer.Argument(..., help='用户名, 或 user@host:port'),
                  password: str = typer.Argument(None, help='密码 (留空则交互输入, 避免进 history)')):
    return _p('setpass', user=user, value=password)


@proxy_app.command('delpass', help='删掉一条已存凭据')
def proxy_delpass(user: str = typer.Argument(..., help='用户名, 或 user@host:port')):
    return _p('delpass', user=user)


@proxy_app.command('cert', help='站点证书: cert list | cert sync (按站点把信任根写进规则表)')
def proxy_cert(action: str = typer.Argument('list', help='list / sync')):
    return _p('cert', value=action)


@proxy_app.command('rules', help='打印规则表; 带 URL 时试算这条请求走哪条线')
def proxy_rules(url: str = typer.Argument(None, help='要试算的 URL (可选)')):
    return _p('rules', value=url)


@proxy_app.command('tidy', help='规则表去重/合并 (默认干跑, --apply 落盘并自动备份)')
def proxy_tidy(apply: bool = typer.Option(False, '--apply', help='落盘 (默认只展示改动)')):
    return _p('tidy', apply=apply)


@rule_app.command('add', help='加一条规则: add <match JSON> <动作>')
def proxy_rule_add(match: str = typer.Argument(..., help='match JSON, 如 {"domain":["example.com"]}'),
                   act: str = typer.Argument(..., help='direct / proxy / block / proxy:<名字>'),
                   first: bool = typer.Option(False, '--first', help='插到最前面 (默认追加到末尾, 会被前面的规则吃掉)'),
                   pos: int = typer.Option(None, '--pos', help='插到第 N 位 (0 = 最前)')):
    return _p('rule', user=match, act=act, first=first, pos=pos)


@rule_app.command('del', help='删一条规则: del <序号> (proxies rules 看序号)')
def proxy_rule_del(index: str = typer.Argument(..., help='规则序号, 从 0 开始')):
    return _p('ruledel', user=index)


@proxy_app.command('geoip', help='GeoIP 国家库: 带路径设库 / update 在线更新 / 不带看状态')
def proxy_geoip(ip: str = typer.Argument(None, help='库文件路径 (.mmdb 或 geoip.dat) 或 update')):
    return _p('geoip', value=ip)


@proxy_app.command('geosite', help='GeoSite 域名库: 带路径设库 / update 在线更新 / 不带看状态')
def proxy_geosite(domain: str = typer.Argument(None, help='库文件路径 (geosite.dat) 或 update')):
    return _p('geosite', value=domain)


@proxy_app.command('geo', help='GeoIP/GeoSite 数据: geo status|update [geosite|geoip|all]')
def proxy_geo(action: str = typer.Argument('status', help='status / update'),
              target: str = typer.Argument('all', help='geosite / geoip / all')):
    return _p('geo', value=action, user=target)


@proxy_app.command('asn', help='配 ASN 库 (GeoLite2-ASN.mmdb 路径), 并自检一条')
def proxy_asn(ip: str = typer.Argument(..., help='GeoLite2-ASN.mmdb 路径')):
    return _p('asn', value=ip)


app.add_typer(proxy_app, name='proxy')

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
        # 裸 `webtool uninstall` 以前会直接卸包 —— 手滑即自毁, 没有任何确认。
        # 现在必须先看 (--dry-run) 或明确确认 (--yes)。
        if not args.dry_run and not args.yes:
            print('webtool uninstall 会卸载 webtool 本身。\n'
                  '  先看要做什么:  webtool uninstall --dry-run\n'
                  '  确认卸载(留数据): webtool uninstall --yes\n'
                  '  连数据一起删:   webtool uninstall --purge-data --yes',
                  file=sys.stderr)
            return 2
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

config_app = typer.Typer(
    add_completion=False, no_args_is_help=True, rich_markup_mode=None, pretty_exceptions_enable=False,
    help='配置与本地状态: config get/set/list/unset | config cache | config blocklist',
    context_settings={'help_option_names': ['-h', '--help']})

cache_app = typer.Typer(add_completion=False, no_args_is_help=True,
                        rich_markup_mode=None, pretty_exceptions_enable=False,
                        help='HTTP 缓存: cache info | cache clear',
                        context_settings={'help_option_names': ['-h', '--help']})

blocklist_app = typer.Typer(add_completion=False, no_args_is_help=True,
                            rich_markup_mode=None, pretty_exceptions_enable=False,
                            help='低质量站点黑名单: show/add/remove/reset',
                            context_settings={'help_option_names': ['-h', '--help']})


def _cfg_run(action, key, value, fmt, output):
    a = _CTX['args']
    a.action, a.key, a.value = action, key, value

    def fn(args, cfg):
        from webtool.cli import config as _cfg_cmd
        return _cfg_cmd.handle(args)
    return _run(None, fn, fmt, output, False, False)


@config_app.command('list')
def _cfg_list(fmt: str = Fmt, output: str = Output):
    """列全部配置"""
    return _cfg_run('list', None, None, fmt, output)


@config_app.command('get')
def _cfg_get(key: str = typer.Argument(..., help='配置键, 如 proxy'),
             fmt: str = Fmt, output: str = Output):
    """看一项配置"""
    return _cfg_run('get', key, None, fmt, output)


@config_app.command('set')
def _cfg_set(key: str = typer.Argument(..., help='配置键'),
             value: str = typer.Argument(..., help='新值 (空字符串=清空)'),
             fmt: str = Fmt, output: str = Output):
    """改一项配置"""
    return _cfg_run('set', key, value, fmt, output)


@config_app.command('unset')
def _cfg_unset(key: str = typer.Argument(..., help='配置键'),
               fmt: str = Fmt, output: str = Output):
    """恢复默认值"""
    return _cfg_run('unset', key, None, fmt, output)


def _cache_run(action, fmt, output):
    a = _CTX['args']
    a.action = action

    def fn(args, cfg):
        from webtool.dao import cache
        return cache.handle(args, cfg)
    return _run(None, fn, fmt, output, False, False)


@cache_app.command('info')
def _cache_info(fmt: str = Fmt, output: str = Output):
    """缓存大小与条目数"""
    return _cache_run('info', fmt, output)


@cache_app.command('clear')
def _cache_clear(fmt: str = Fmt, output: str = Output):
    """清空缓存"""
    return _cache_run('clear', fmt, output)


def _bl_run(action, domain, allow, fmt, output):
    a = _CTX['args']
    a.action, a.domain, a.allow = action, domain, allow

    def fn(args, cfg):
        import webtool.filters.blocklist as blocklist
        return blocklist.handle_cli(args)
    return _run(None, fn, fmt, output, False, False)


@blocklist_app.command('show')
def _bl_show(fmt: str = Fmt, output: str = Output):
    """列当前黑名单"""
    return _bl_run('show', None, False, fmt, output)


@blocklist_app.command('add')
def _bl_add(domain: str = typer.Argument(..., help='域名, 如 csdn.net'),
            allow: bool = typer.Option(False, '--allow', help='加进白名单例外'),
            fmt: str = Fmt, output: str = Output):
    """加入黑名单"""
    return _bl_run('add', domain, allow, fmt, output)


@blocklist_app.command('remove')
def _bl_remove(domain: str = typer.Argument(..., help='域名'),
               allow: bool = typer.Option(False, '--allow', help='从白名单里移除'),
               fmt: str = Fmt, output: str = Output):
    """移出黑名单"""
    return _bl_run('remove', domain, allow, fmt, output)


@blocklist_app.command('reset')
def _bl_reset(fmt: str = Fmt, output: str = Output):
    """恢复默认黑名单"""
    return _bl_run('reset', None, False, fmt, output)


config_app.add_typer(cache_app, name='cache')
config_app.add_typer(blocklist_app, name='blocklist')
app.add_typer(config_app, name='config')


engines_app = typer.Typer(
    add_completion=False, no_args_is_help=True, rich_markup_mode=None, pretty_exceptions_enable=False,
    help='引擎体检: engines test [名] | engines presets (清单见 webtool search -l)',
    context_settings={'help_option_names': ['-h', '--help']})


def _eng_run(action, name, query, fmt, output):
    a = _CTX['args']
    a.action, a.name, a.query = action, name, query

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



@engines_app.command('test')
def _eng_test(name: str = typer.Argument(None, help='引擎名; 省略=全部引擎'),
              query: str = typer.Option('python', '--query', help='测试用的检索词'),
              fmt: str = Fmt, output: str = Output):
    """实发一次测试请求"""
    return _eng_run('test', name, query, fmt, output)


@engines_app.command('presets')
def _eng_presets(fmt: str = Fmt, output: str = Output):
    """引擎组合预设 (search --engine 里可用的名字)"""
    return _eng_run('presets', None, 'python', fmt, output)


mcp_app = typer.Typer(
    add_completion=False, no_args_is_help=True, rich_markup_mode=None, pretty_exceptions_enable=False,
    help='MCP 客户端: mcp list <端点> | mcp probe <端点> | mcp call <端点> <工具> [JSON]',
    context_settings={'help_option_names': ['-h', '--help']})


def _mcp_run(action, target, tool, arguments, params, key_env, tools, timeout,
             fmt, output, no_proxy):
    a = _CTX['args']
    a.action, a.target, a.tool, a.arguments = action, target, tool, arguments
    a.params = params
    a.key_env, a.tools, a.timeout = key_env, tools, timeout

    def fn(args, cfg):
        from webtool.cli.mcp import do_mcp
        return do_mcp(args, cfg)
    return _run(None, fn, fmt, output, False, no_proxy)


@mcp_app.command('list')
def _mcp_list(target: str = typer.Argument(..., help='MCP 端点 URL, 或 mcp.json 里的别名'),
              key_env: str = typer.Option('', '--key-env', help='从哪个环境变量读 API key'),
              tools: str = typer.Option('', '--tools', help='工具白名单, 逗号分隔 (?tools=)'),
              timeout: float = typer.Option(45.0, '--timeout', help='单次请求超时秒'),
              fmt: str = Fmt, output: str = Output, no_proxy: bool = NoProxy):
    """列端点提供的工具"""
    return _mcp_run('list', target, None, None, None, key_env, tools, timeout,
                    fmt, output, no_proxy)


@mcp_app.command('probe')
def _mcp_probe(target: str = typer.Argument(..., help='MCP 端点 URL, 或 mcp.json 里的别名'),
               key_env: str = typer.Option('', '--key-env', help='从哪个环境变量读 API key'),
               tools: str = typer.Option('', '--tools', help='工具白名单, 逗号分隔 (?tools=)'),
               timeout: float = typer.Option(45.0, '--timeout', help='单次请求超时秒'),
               fmt: str = Fmt, output: str = Output, no_proxy: bool = NoProxy):
    """端点体检 (握手 + 工具数)"""
    return _mcp_run('probe', target, None, None, None, key_env, tools, timeout,
                    fmt, output, no_proxy)


@mcp_app.command('call')
def _mcp_call(target: str = typer.Argument(..., help='MCP 端点 URL, 或 mcp.json 里的别名'),
              tool: str = typer.Argument(..., help='工具名'),
              arguments: str = typer.Argument(None, help="JSON 参数, 如 '{\"query\":\"x\"}'"),
              params: List[str] = typer.Option(None, '--arg', metavar='K=V',
                                               help='拆开传参, 可多次; 值按 JSON 字面量猜类型'),
              key_env: str = typer.Option('', '--key-env', help='从哪个环境变量读 API key'),
              tools: str = typer.Option('', '--tools', help='工具白名单, 逗号分隔 (?tools=)'),
              timeout: float = typer.Option(45.0, '--timeout', help='单次请求超时秒'),
              fmt: str = Fmt, output: str = Output, no_proxy: bool = NoProxy):
    """调一个工具"""
    return _mcp_run('call', target, tool, arguments, params, key_env, tools,
                    timeout, fmt, output, no_proxy)


app.add_typer(mcp_app, name='mcp')


plugins_app = typer.Typer(
    add_completion=False, no_args_is_help=True, rich_markup_mode=None, pretty_exceptions_enable=False,
    help='插件与引擎: plugins list/check/doctor/reload/enable/disable | plugins engines',
    context_settings={'help_option_names': ['-h', '--help']})


def _plug_run(action, kind, plugin, all_, fmt, output):
    a = _CTX['args']
    a.action, a.kind, a.plugin, a.all = action, kind, plugin, all_

    def fn(args, cfg):
        from webtool.cli import plugins as _plug_cmd
        return _plug_cmd.handle(args)
    return _run(None, fn, fmt, output, False, False)


@plugins_app.command('list')
def _plug_list(kind: str = typer.Argument(None, help='只列某一类: search/hot/site/source/extractor/mcp/llm/...'),
               all_: bool = typer.Option(False, '--all', '-a', help='含未启用的'),
               fmt: str = Fmt, output: str = Output):
    """列站点插件"""
    return _plug_run('list', kind, None, all_, fmt, output)


@plugins_app.command('check')
def _plug_check(kind: str = typer.Argument(None, help='只查某一类'),
                fmt: str = Fmt, output: str = Output):
    """检查插件可加载性"""
    return _plug_run('check', kind, None, False, fmt, output)


@plugins_app.command('doctor')
def _plug_doctor(fmt: str = Fmt, output: str = Output):
    """全面体检 (加载失败 / 冲突 / 缺依赖)"""
    return _plug_run('doctor', None, None, False, fmt, output)


@plugins_app.command('reload')
def _plug_reload(fmt: str = Fmt, output: str = Output):
    """重扫插件目录"""
    return _plug_run('reload', None, None, False, fmt, output)


@plugins_app.command('enable')
def _plug_enable(plugin: str = typer.Argument(..., help='插件名'),
                 fmt: str = Fmt, output: str = Output):
    """启用一个插件"""
    return _plug_run('enable', None, plugin, False, fmt, output)


@plugins_app.command('disable')
def _plug_disable(plugin: str = typer.Argument(..., help='插件名'),
                  fmt: str = Fmt, output: str = Output):
    """禁用一个插件"""
    return _plug_run('disable', None, plugin, False, fmt, output)


plugins_app.add_typer(engines_app, name='engines')
app.add_typer(plugins_app, name='plugins')
