"""webtool CLI (typer)

约定:
- 数据命令 (search/fetch/site/rank/feed/zen) 的 print 输出统一捕获后走 emit,
  支持 -f/-o 落盘; 管理命令 (proxy/engines/cache/blocklist/config/plugins) 也支持
  -f/-o, 由 cli/adminfmt.py 把它们吐出的 JSON 转成目标格式
- -f 大小写不敏感, md=markdown, txt=text; 非法值直接报错退出 (不静默回落);
  默认 txt (主要消费者是人; 程序/Agent 消费请显式 -f json)
- 退出码: 0 成功 / 2 用法错误 / 130 Ctrl-C
"""
import sys

import typer

# typer 0.26 起 vendor 了 click: 异常类在 typer._click.exceptions, 与顶层 click 不同源
try:
    from typer._click.exceptions import UsageError as _UsageError, ClickException as _ClickException
except ImportError:                        # typer <= 0.25: 异常来自顶层 click
    from click.exceptions import UsageError as _UsageError, ClickException as _ClickException

from webtool.core.errors import WebtoolError as _WebtoolError

from types import SimpleNamespace  # noqa: E402
from webtool.cli._ctx import _CTX, _argv_format  # noqa: E402

_HELP = '''Agent 友好的网页搜索与内容获取工具

最常用 (按想做的事找):
  搜东西    search <词>           多引擎, 主引擎不足自动降级兜底
  读网页    fetch <url>           正文提取 / PDF 抽取 / --structured 结构化
  搜某站    site <站点> <词>      20 个站点, 站点名见 site list
  比口径    compare <url> <url>   多源并排: 哪些共有、哪些各有侧重
  看热榜    rank <源>...          26 个榜单源, 不带参数=列全部源
  问问题    ask <问题>            先检索再答, 每条结论带来源
  看股票    stock <子命令>        行情/涨停/资金/新闻/财报/K线/选股

全部命令分组:
  搜索  search  fetch  site  crawl  ask
  对比  snapshot  diff  compare
  监控  watch  feed
  榜单  rank
  金融  stock  pydata
  基建  proxy  pkg  mcp  plugins  cache  config  engines  blocklist
  展示  pic  banner  video  music
  其他  zen  upgrade  uninstall  intercept-log

每个命令:  webtool <命令> -h
'''

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  rich_markup_mode=None,   # 关掉 rich 帮助面板 (不要大框框住)
                  help='Agent 友好的网页搜索与内容获取工具',
                  context_settings={'help_option_names': ['-h', '--help']})

@app.callback()
def _main(ctx: typer.Context,
          proxy: str = typer.Option(None, '--proxy', help='临时代理, 覆盖配置文件'),
          no_cache: bool = typer.Option(False, '--no-cache', help='跳过缓存'),
          log_file: str = typer.Option(None, '--log-file',
                                       help='把 DEBUG 全量日志写进文件 (纯文本; WEBTOOL_LOG_FILE 等效)'),
          debug: int = typer.Option(0, '--debug', '-d', count=True,
                                    help='调试日志到 stderr, 可叠加: -d 本仓, -dd 连三方库 (WEBTOOL_DEBUG=1 等效)')):
    # --version / -V 不在 click 层, 由 main() 预扫 (子命令后面也能用), 见 main
    from webtool.core import logging as _log
    _log.setup(debug + _log.env_debug(), log_file=log_file)
    from webtool.net import tls as _tls
    _tls.broadcast_env()       # 信任根也广播给第三方库 (akshare/trafilatura/requests)
    from webtool.net import adapters as _ad
    _ad.patch_requests()       # 第三方库自建的 requests 会话也回到统一通道
    _CTX.clear()
    _CTX.update(proxy=proxy, no_cache=no_cache, args=SimpleNamespace())

def main(argv=None):
    """入口: argv=None 走 sys.argv; 退出码 0/2/130

    standalone_mode=False 让 click 把用法错误抛成 UsageError 而非自退,
    这里统一转成 stderr 提示 + rc 2。
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    # 优雅关闭: 首次 Ctrl-C 抛 KeyboardInterrupt 走正常收尾, 再按一次强制 exit
    # (真卡在 C 调用/线程 join 里时, 这是唯一能停下来的路)。见 core/shutdown。
    from webtool.core import shutdown as _shutdown
    _shutdown.install()
    # -v/-V/--version 在 click 解析前先扫: 放在子命令后面 (webtool zen --version)
    # click 会当作未知选项报错, 而用户想看的只是版本号。
    # pkg 透传除外 —— 它后面的 -v/--version 是子命令的参数, 不能截
    if (argv and argv[0] != 'pkg'
            and ('--version' in argv or '-v' in argv or '-V' in argv)):
        from webtool.core import version as _v
        if _argv_format(argv) == 'json':
            import json
            print(json.dumps(_v.info(), ensure_ascii=False, indent=2))
        else:
            print('webtool %s' % _v.get_version())
        return 0
    # 顶层帮助: typer 的 rich 渲染会把多行帮助折成一段 (且不认 \b),
    # 直接打自己的速查表, 别让用户看到一坨。
    if not argv or argv[0] in ('-h', '--help'):
        print(_HELP)
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
        print('webtool: 已中断 (再按一次 Ctrl-C 强制退出)', file=sys.stderr)
        return 130
    except _WebtoolError as e:                  # 本仓统一异常: 自带退出码
        print(f'webtool: {e}', file=sys.stderr)
        return e.exit_code
    except Exception as e:                      # 兜底: 别把裸 traceback 甩给用户
        from webtool.core import logging as _log
        if _log.is_debug():
            raise                              # -d 时保留完整堆栈, 便于定位
        print(f'webtool: 内部错误 {type(e).__name__}: {str(e)[:200]}',
              file=sys.stderr)
        print('(加 -d 看完整堆栈)', file=sys.stderr)
        return 1


from webtool.cli.commands import banner as _banner_cmd   # noqa: F401,E402
from webtool.cli.commands import data as _data_cmds       # noqa: F401,E402
from webtool.cli.commands import intercept as _ic_cmds    # noqa: F401,E402
from webtool.cli.commands import maintenance as _mnt_cmds  # noqa: F401,E402
from webtool.cli.commands import media as _media_cmd    # noqa: F401,E402
from webtool.cli.commands import pic as _pic_cmd         # noqa: F401,E402
from webtool.cli.commands import stock as _stock_cmd  # noqa: F401,E402


if __name__ == '__main__':
    # `python -m webtool.cli.app` 会让本模块以 __main__ 身份再被 import 一次,
    # 那次 import 的命令注册在**另一个** app 对象上; 故这里转调包里那份, 保证注册生效
    from webtool.cli.app import main as _pkg_main
    sys.exit(_pkg_main())

# 兼容再导出: 老代码/测试从 app 模块取这些内部名
from webtool.cli._ctx import _run, _entry_fn, _norm_fmt, _norm_think  # noqa: E402,F401
from webtool.cli.commands.maintenance import _pip_proxy_env, _pip_route_note  # noqa: E402,F401

