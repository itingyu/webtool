"""stock 命令 (最后注册, 保持 `webtool --help` 的原顺序)"""
import typer

from webtool.cli._ctx import _CTX, _entry_fn, _run, Fmt, Output
from webtool.cli._help import verbatim as _verbatim
from webtool.cli.app import app


_EPILOG = _verbatim("""常用动作
  quote        实时行情 (可多股/指数别名)
  kline        K 线 (--start/--end 区间, --chart 出图)
  intraday     分时 (当日/五日, 默认含集合竞价)
  pool         涨停池
  flow         资金流榜单
  screen       选股池
  analyze      单股深度
  risk         风险核查
  news         个股新闻
  financials   核心财务
  mcp          透传调用 24 工具
  data         通用取数入口 (1300+ 接口)

示例
  webtool stock quote 600519 sh000001
  webtool stock kline 600519 --chart
  webtool stock kline 600519 --start 2025-01-01 --end 2025-06-30 --chart
  webtool stock intraday 600519 --chart
  webtool stock intraday 600519 --days 5 --chart --png
  webtool stock screen --pool short --min-score 70

全部动作 (60+): webtool stock""")


@app.command('stock', epilog=_EPILOG)
def stock_cmd(action: str = typer.Argument(None, help='动作名, 见下方常用动作; 缺省打印完整目录'),
              codes: list[str] = typer.Argument(None, help='股票代码 (位置参数: quote/check/risk 可多个, 其余单股动作取首个)'),
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
              bars: int = typer.Option(120, '--bars', help='kline 取几根 K 线'),
              period: str = typer.Option('day', '--period', help='kline 周期: day/week/month'),
              chart: bool = typer.Option(False, '--chart', help='kline 出一张 SVG 图 (红涨绿跌 + 均线 + 量能)'),
              chart_out: str = typer.Option(None, '--chart-out',
                                            help='kline 图输出路径 (默认 <代码>-<周期>.svg)'),
              ma: str = typer.Option('5,10,20', '--ma',
                                     help='kline 均线, 逗号分隔 (可多个值画多条)'),
              mavg: str = typer.Option(None, '--mavg',
                                       help='intraday 分时均线 (按分钟价格), 逗号分隔, 如 5,20'),
              start: str = typer.Option(None, '--start',
                                        help='kline 起始日期 YYYY-MM-DD (与 --end 配合)'),
              end: str = typer.Option(None, '--end',
                                      help='kline 结束日期 YYYY-MM-DD'),
              days: int = typer.Option(1, '--days',
                                       help='intraday 天数: 1=当日 5=五日'),
              no_auction: bool = typer.Option(False, '--no-auction',
                                              help='intraday 当日图不含集合竞价'),
              after_hours: bool = typer.Option(False, '--after-hours',
                                               help='intraday 保留 15:05 后的盘后固定价格交易'),
              gran: int = typer.Option(60, '--gran',
                                       help='intraday 量柱粒度(秒): 60=分钟, 30/15 用逐笔聚合'),
              dma: str = typer.Option('5,10,20,60', '--dma',
                                      help='intraday 叠加日线均线横线, 逗号分隔; 传空串关闭'),
              limit_y: bool = typer.Option(False, '--limit-y',
                                           help='intraday 纵轴强制撑满涨跌停(默认按波动取景)'),
              combo: bool = typer.Option(False, '--combo',
                                         help='intraday 出一张三合一长图(当日/30秒/五日)'),
              auto_y: bool = typer.Option(False, '--auto-y',
                                          help='intraday 纵轴按当日实际波动自适应(默认按涨跌停固定)'),
              png: bool = typer.Option(False, '--png',
                                       help='图表输出 PNG (默认 SVG)'),
              macd: bool = typer.Option(False, '--macd',
                                        help='kline 加 MACD(12,26,9) 副图'),
              ascii_art: bool = typer.Option(False, '--ascii',
                                             help='终端字符画 (K线/分时), 直接打到 stdout'),
              no_color: bool = typer.Option(False, '--no-color',
                                            help='字符画不带 ANSI 颜色'),
              ascii_h: int = typer.Option(0, '--ascii-h',
                                          help='字符画高度(行), 0=默认 20(K线)/16(分时)'),
              ascii_w: int = typer.Option(0, '--ascii-w',
                                          help='字符画宽度(列), 0=跟随终端'),
              ascii_plain: bool = typer.Option(False, '--ascii-plain',
                                               help='纯 ASCII 字符画 (字体缺盲文/方块时用)'),
              ascii_wide: bool = typer.Option(False, '--ascii-wide',
                                              help='K线实体用实心块 (默认细柱)'),
              ascii_gap: bool = typer.Option(False, '--ascii-gap',
                                             help='每根K线占2列(留间隔, 同色不粘连)'),
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
    """股票能力: 行情/涨停池/资金/新闻/财报/K线/选股/风险 + 生态库/底层直调/逆向文档"""
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
    a.bars, a.period, a.chart, a.chart_out, a.ma = bars, period, chart, chart_out, ma
    a.start, a.end, a.days, a.no_auction, a.png = start, end, days, no_auction, png
    a.mavg, a.macd, a.after_hours = mavg, macd, after_hours
    a.gran, a.auto_y, a.combo, a.dma = gran, auto_y, combo, dma
    a.ascii_art, a.no_color = ascii_art, no_color
    a.ascii_h, a.ascii_w = ascii_h, ascii_w
    a.ascii_plain, a.ascii_wide = ascii_plain, ascii_wide
    a.ascii_gap = ascii_gap
    a.limit_y = limit_y
    # stock 不走 net 层, 无代理/缓存概念; 仍走 _run 统一 -f/-o 与退出码
    return _run(None, _entry_fn('stock'), fmt, output, False, False)
