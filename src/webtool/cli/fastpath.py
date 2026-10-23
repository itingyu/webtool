"""快速路径: `-h/--help`、`-v/--version` 不加载 typer

为什么单开一个入口: 这两条是最常被跑的 (尤其 Agent 第一步就是 `webtool -h`),
而 `webtool.cli.app` 一 import 就要先把 typer/click 拖进来 (~0.3s), 命令树
还要再 import 一堆模块。帮助文本是静态的、版本号只读 pyproject, 完全用不上
那一整套 —— 先用本模块接住, 真的执行命令才转给 app.main。

约定必须与 app.main 一致 (它是同一套判断的另一半):
  - 不带参数 = 打印速查表 (与 `-h` 相同)
  - `pkg` 后面的 -v/--version 是子命令自己的参数, 不能截
"""
import sys

HELP = '''Agent 友好的网页搜索与内容获取工具

最常用 (按想做的事找):
  搜东西    search <词>           多引擎, 主引擎不足自动降级兜底
  读网页    fetch <url>           正文提取 / PDF 抽取 / --structured 结构化
  搜某站    search -s <站点> <词>  20 个站点, 清单见 search -l
  比口径    compare <url> <url>   多源并排: 哪些共有、哪些各有侧重
  看热榜    rank <源>...          19 个榜单源, 不带参数=列全部源
  问问题    ask <问题>            先检索再答, 每条结论带来源
  看股票    stock <子命令>        行情/涨停/资金/新闻/财报/K线/选股

全部命令分组:
  搜索  search  fetch  crawl  ask
  对比  diff  compare
  监控  watch  feed
  榜单  rank
  金融  stock  pydata
  基建  proxy  pkg  mcp  plugins  config
  展示  render
  其他  zen  upgrade  uninstall  intercept-log

每个命令:  webtool <命令> -h
'''


def wants_help(argv):
    return not argv or argv[0] in ('-h', '--help')


def wants_version(argv):
    """与 app.main 同一规则: 出现在任何位置都认, 但 pkg 透传除外"""
    return bool(argv) and argv[0] != 'pkg' and any(
        a in ('--version', '-v', '-V') for a in argv)


def _argv_format(argv):
    for i, a in enumerate(argv):
        if a in ('-f', '--format') and i + 1 < len(argv):
            return argv[i + 1].strip().lower()
        for pre in ('--format=', '-f='):
            if a.startswith(pre):
                return a[len(pre):].strip().lower()
    return ''


def print_version(argv):
    from webtool.core import version as _v
    if _argv_format(argv) == 'json':
        import json
        print(json.dumps(_v.info(), ensure_ascii=False, indent=2))
    else:
        print('webtool %s' % _v.get_version())
    return 0


def main(argv=None):
    """入口: 能自己答的当场答完, 其余交给 app.main (那时才 import typer)"""
    argv = list(sys.argv[1:] if argv is None else argv)
    if wants_help(argv):
        print(HELP)
        return 0
    if wants_version(argv):
        return print_version(argv)
    from webtool.cli.app import main as _main
    return _main(argv)
