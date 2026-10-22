"""stock 命令: 每个动作一个子命令, 只带自己的参数

历史: 原来所有 60+ 动作共用一个函数签名, `webtool stock --help` 要列 55 个
选项, 而每个动作实际只用 0-3 个。现在按动作拆成 typer 子命令, 冷门动作
统一走 `stock run <动作>` 兜底 (参数与旧版完全一致)。

用法不变的部分: `webtool stock quote 600519` —— 动作本来就是第一个位置参数,
拆成子命令后命令行写法一模一样。
"""
import typer

from webtool.cli._ctx import _CTX, _entry_fn, _run, Fmt, Output
from webtool.cli.app import app

stock_app = typer.Typer(
    add_completion=False, no_args_is_help=False, rich_markup_mode=None,
    help='股票: 行情/涨停池/资金/新闻/财报/K线/选股/风险 (无参看目录)',
    context_settings={'help_option_names': ['-h', '--help']})

# do_stock 会读的全部字段默认值; 子命令只覆盖自己用得到的
_DEFAULTS = {
    'action': '', 'codes': [], 'date': None, 'only_buy': False,
    'scope': 'industry', 'pool': 'short', 'min_score': 60,
    'limit': 10, 'n': 3, 'tool': None, 'params': None, 'keyword': '',
    'timeout': 60.0, 'method': None, 'by': 'source',
    'url': '', 'referer': '', 'encoding': '', 'pick': '', 'raw': False,
    'form': {}, 'http_timeout': 20.0, 'post': False, 'method_only': False,
    'lib': 'akshare', 'full': False, 'texts': [],
    'excel': None, 'kind': None, 'name': None, 'thesis': None,
    'drivers': [], 'risks': [], 'catalysts': [], 'mid': [],
    'bars': 120, 'period': 'day', 'chart': False, 'chart_out': None,
    'ma': '5,10,20', 'start': None, 'end': None, 'days': 1,
    'no_auction': False, 'png': False, 'mavg': None, 'macd': False,
    'after_hours': False, 'gran': 60, 'auto_y': False, 'combo': False,
    'dma': '5,10,20,60', 'ascii_art': False, 'limit_y': False,
}


def _dispatch(action, fmt, output, **kw):
    """把子命令参数塞进 _CTX 的 args 后交给 do_stock 分发

    -f/-o 写在子命令前面 (webtool stock -f json quote ...) 时由 callback
    存进 _CTX, 这里兜底取 —— 两处都认。
    """
    fmt = fmt or _CTX.get('stock_fmt')
    output = output or _CTX.get('stock_output')
    a = _CTX['args']
    for k, v in _DEFAULTS.items():
        setattr(a, k, v)
    a.action = action
    for k, v in kw.items():
        setattr(a, k, v)
    return _run(None, _entry_fn('stock'), fmt, output, False, False)


@stock_app.callback(invoke_without_command=True)
def _root(ctx: typer.Context, fmt: str = Fmt, output: str = Output):
    """无子命令时打动作目录 (与旧版行为一致: rc=2)"""
    _CTX['stock_fmt'] = fmt
    _CTX['stock_output'] = output
    if ctx.invoked_subcommand is None:
        return _dispatch('', fmt, output)
    return None


# ---------------------------------------------------------------- 数据动作

@stock_app.command('quote')
def _quote(codes: list[str] = typer.Argument(..., help='股票代码, 可多个; 支持 上证指数/创业板指 等别名'),
           fmt: str = Fmt, output: str = Output):
    """实时行情"""
    return _dispatch('quote', fmt, output, codes=list(codes))


@stock_app.command('pool')
def _pool(date: str = typer.Option(None, '--date', help='数据日 YYYY-MM-DD 或 last (上一交易日)'),
          only_buy: bool = typer.Option(False, '--only-buy', help='只留可买板块'),
          fmt: str = Fmt, output: str = Output):
    """涨停池 (连板/首封/炸板/封单/行业)"""
    return _dispatch('pool', fmt, output, date=date, only_buy=only_buy)


@stock_app.command('check')
def _check(codes: list[str] = typer.Argument(..., help='股票代码, 可多个'),
           fmt: str = Fmt, output: str = Output):
    """可买性核查 (板块归属 + ST/退市风险)"""
    return _dispatch('check', fmt, output, codes=list(codes))


@stock_app.command('calendar')
def _calendar(date: str = typer.Option(None, '--date', help='从哪天起算; last=上一交易日'),
              n: int = typer.Option(3, '--n', help='往后几个交易日'),
              fmt: str = Fmt, output: str = Output):
    """交易日历"""
    return _dispatch('calendar', fmt, output, date=date, n=n)


@stock_app.command('flow')
def _flow(scope: str = typer.Option('industry', '--scope',
                                    help='口径: industry(行业)/individual(个股)/north(北向)'),
          fmt: str = Fmt, output: str = Output):
    """资金流榜单"""
    return _dispatch('flow', fmt, output, scope=scope)


@stock_app.command('news')
def _news(code: str = typer.Argument(..., help='股票代码'),
          limit: int = typer.Option(10, '-n', '--limit', help='条数'),
          fmt: str = Fmt, output: str = Output):
    """个股新闻"""
    return _dispatch('news', fmt, output, codes=[code], limit=limit)


@stock_app.command('announcement')
def _announcement(code: str = typer.Argument(..., help='股票代码'),
                  limit: int = typer.Option(10, '-n', '--limit', help='条数'),
                  fmt: str = Fmt, output: str = Output):
    """公告列表"""
    return _dispatch('announcement', fmt, output, codes=[code], limit=limit)


@stock_app.command('financials')
def _financials(code: str = typer.Argument(..., help='股票代码'),
                fmt: str = Fmt, output: str = Output):
    """核心财务指标"""
    return _dispatch('financials', fmt, output, codes=[code])


@stock_app.command('analyze')
def _analyze(code: str = typer.Argument(..., help='股票代码'),
             fmt: str = Fmt, output: str = Output):
    """单股深度 (技术面 + 评分 + 决策信号 + 画像)"""
    return _dispatch('analyze', fmt, output, codes=[code])


@stock_app.command('screen')
def _screen(pool: str = typer.Option('short', '--pool', help='池: short(1-5日)/mid(3-6月)/long(6-18月)'),
            min_score: int = typer.Option(60, '--min-score', help='技术面分门槛 (short 池)'),
            fmt: str = Fmt, output: str = Output):
    """选股池"""
    return _dispatch('screen', fmt, output, pool=pool, min_score=min_score)


@stock_app.command('risk')
def _risk(codes: list[str] = typer.Argument(..., help='股票代码, 可多个'),
          fmt: str = Fmt, output: str = Output):
    """风险核查 (重组/减持/立案/预亏)"""
    return _dispatch('risk', fmt, output, codes=list(codes))


@stock_app.command('report')
def _report(code: str = typer.Argument(None, help='股票代码 (与 --pool 二选一)'),
            pool: str = typer.Option(None, '--pool', help='短线池成稿: short'),
            text: list[str] = typer.Option(None, '--text', metavar='文本', help='补充论点, 可多次'),
            fmt: str = Fmt, output: str = Output):
    """成稿研报 (markdown)"""
    codes = [code] if code else []
    return _dispatch('report', fmt, output, codes=codes, pool=pool, texts=list(text or []))


@stock_app.command('excel')
def _excel(path: str = typer.Option(..., '--excel', help='输出 xlsx 路径'),
           min_score: int = typer.Option(60, '--min-score', help='技术面分门槛'),
           fmt: str = Fmt, output: str = Output):
    """选股池导出 xlsx (需 openpyxl)"""
    return _dispatch('excel', fmt, output, excel=path, min_score=min_score)


@stock_app.command('sentiment')
def _sentiment(code: str = typer.Argument(None, help='股票代码 (不给则必须给 --text)'),
               text: list[str] = typer.Option(None, '--text', metavar='文本', help='直接打分的文本, 可多次'),
               fmt: str = Fmt, output: str = Output):
    """消息面打分 -100~+100"""
    codes = [code] if code else []
    return _dispatch('sentiment', fmt, output, codes=codes, texts=list(text or []))


@stock_app.command('boards')
def _boards(keyword: str = typer.Argument('', help='板块关键词 (不填列全部)'),
            fmt: str = Fmt, output: str = Output):
    """板块目录 (行业 + 概念), 给 kline/intraday 挑名字"""
    return _dispatch('boards', fmt, output, codes=[keyword] if keyword else [])


@stock_app.command('diagram')
def _diagram(kind: str = typer.Option(..., '--kind', help='图类型: logic(投资逻辑)/tree(产业链树)/chain(链条)'),
             name: str = typer.Option(None, '--name', help='标的/产业链名'),
             thesis: str = typer.Option(None, '--thesis', help='投资逻辑主线 (logic)'),
             driver: list[str] = typer.Option(None, '--driver', help='驱动因素 (logic) / 上游 (chain), 可多次'),
             mid: list[str] = typer.Option(None, '--mid', help='产业链中游 (chain), 可多次'),
             catalyst: list[str] = typer.Option(None, '--catalyst', help='催化剂 (logic) / 下游 (chain), 可多次'),
             risk: list[str] = typer.Option(None, '--risk', help='风险 (logic), 可多次'),
             code: str = typer.Argument(None, help='股票代码 (logic 用)'),
             fmt: str = Fmt, output: str = Output):
    """mermaid 图 (logic/tree/chain)"""
    return _dispatch('diagram', fmt, output, kind=kind, name=name, thesis=thesis,
                     drivers=list(driver or []), mid=list(mid or []),
                     catalysts=list(catalyst or []), risks=list(risk or []),
                     codes=[code] if code else [])


@stock_app.command('kline')
def _kline(code: str = typer.Argument(..., help='股票代码 (A股/港股/美股)'),
           bars: int = typer.Option(120, '--bars', help='取几根 K 线'),
           start: str = typer.Option(None, '--start', help='起始日期 YYYY-MM-DD'),
           end: str = typer.Option(None, '--end', help='结束日期 YYYY-MM-DD'),
           period: str = typer.Option('day', '--period', help='周期: day/week/month'),
           ma: str = typer.Option('5,10,20', '--ma', help='均线, 逗号分隔'),
           macd: bool = typer.Option(False, '--macd', help='加 MACD(12,26,9) 副图'),
           chart: bool = typer.Option(False, '--chart', help='出 SVG 图 (红涨绿跌 + 均线 + 量能)'),
           chart_out: str = typer.Option(None, '--chart-out', help='图输出路径 (默认 <代码>-<周期>.svg)'),
           png: bool = typer.Option(False, '--png', help='图表输出 PNG (默认 SVG)'),
           ascii_art: bool = typer.Option(False, '--ascii', help='终端字符画'),
           fmt: str = Fmt, output: str = Output):
    """K 线"""
    return _dispatch('kline', fmt, output, codes=[code], bars=bars, start=start,
                     end=end, period=period, ma=ma, macd=macd, chart=chart,
                     chart_out=chart_out, png=png, ascii_art=ascii_art)


@stock_app.command('intraday')
def _intraday(code: str = typer.Argument(..., help='股票代码'),
              days: int = typer.Option(1, '--days', help='1=当日, 5=五日'),
              no_auction: bool = typer.Option(False, '--no-auction', help='不含集合竞价'),
              after_hours: bool = typer.Option(False, '--after-hours', help='保留 15:05 后盘后交易'),
              gran: int = typer.Option(60, '--gran', help='量柱粒度(秒): 60=分钟, 30/15 用逐笔聚合'),
              dma: str = typer.Option('5,10,20,60', '--dma', help='叠加日线均线, 逗号分隔; 空串关闭'),
              mavg: str = typer.Option(None, '--mavg', help='分时均线, 逗号分隔, 如 5,20'),
              limit_y: bool = typer.Option(False, '--limit-y', help='纵轴强制撑满涨跌停'),
              auto_y: bool = typer.Option(False, '--auto-y', help='纵轴按实际波动自适应'),
              combo: bool = typer.Option(False, '--combo', help='三合一长图 (当日/30秒/五日)'),
              chart: bool = typer.Option(False, '--chart', help='出 SVG 图'),
              chart_out: str = typer.Option(None, '--chart-out', help='图输出路径'),
              png: bool = typer.Option(False, '--png', help='图表输出 PNG'),
              ascii_art: bool = typer.Option(False, '--ascii', help='终端字符画'),
              fmt: str = Fmt, output: str = Output):
    """分时图 (默认含集合竞价)"""
    return _dispatch('intraday', fmt, output, codes=[code], days=days,
                     no_auction=no_auction, after_hours=after_hours, gran=gran,
                     dma=dma, mavg=mavg, limit_y=limit_y, auto_y=auto_y,
                     combo=combo, chart=chart, chart_out=chart_out, png=png,
                     ascii_art=ascii_art)


# ---------------------------------------------------------------- 工具与透传

@stock_app.command('tools')
def _tools(keyword: str = typer.Argument('', help='按关键词筛工具'),
           fmt: str = Fmt, output: str = Output):
    """列可透传调用的动作清单"""
    return _dispatch('tools', fmt, output, keyword=keyword)


@stock_app.command('health')
def _health(fmt: str = Fmt, output: str = Output):
    """两侧探活 (engine 脚本层 / srv 编排层)"""
    return _dispatch('health', fmt, output)


@stock_app.command('mcp')
def _mcp(action: str = typer.Argument(..., help='动作名, 见 `webtool stock tools`'),
         arg: list[str] = typer.Option(None, '--arg', metavar='K=V', help='参数, 可多次; 值按 JSON 字面量猜类型'),
         timeout: float = typer.Option(60.0, '--timeout', help='子进程超时秒'),
         fmt: str = Fmt, output: str = Output):
    """按名透传调用 (24 个动作)"""
    return _dispatch('mcp', fmt, output, tool=action, params=list(arg or []), timeout=timeout)


@stock_app.command('data')
def _data(parts: list[str] = typer.Argument(None, help='list/find/call/url/health, 或域/关键词'),
          lib: str = typer.Option('akshare', '--lib', help='生态库: akshare/tushare/baostock/efinance'),
          full: bool = typer.Option(False, '--full', help='eco 返回完整数据 (默认只给形状+预览)'),
          raw: bool = typer.Option(False, '--raw', help='输出 JSON 记录而非表格'),
          limit: int = typer.Option(10, '-n', '--limit', help='条数'),
          method: str = typer.Option(None, '--method', help='接口/方法名 (data call 用)'),
          url: str = typer.Option('', '--url', help='data url 的 URL (也可直接位置参数给)'),
          post: bool = typer.Option(False, '--post', help='data url 走 POST'),
          form: str = typer.Option('', '--form', help='POST 表单 k=v&k2=v2'),
          pick: str = typer.Option('', '--pick', help='取嵌套路径, 如 data.0.quote'),
          referer: str = typer.Option('', '--referer', help='覆盖默认 Referer'),
          encoding: str = typer.Option('', '--encoding', help='强制解码 (gbk/gb18030)'),
          method_only: bool = typer.Option(False, '--method-only', help='只回原始响应文本'),
          fmt: str = Fmt, output: str = Output):
    """通用取数入口 (1300+ 接口): data [list|find|call|url]"""
    _form = {}
    for pair in (form or '').split('&'):
        if '=' in pair:
            k, v = pair.split('=', 1)
            _form[k] = v
    return _dispatch('data', fmt, output, codes=list(parts or []), lib=lib, full=full,
                     raw=raw, limit=limit, method=method, url=url, post=post,
                     form=_form, pick=pick, referer=referer, encoding=encoding,
                     method_only=method_only)


# ---------------------------------------------------------------- 冷门动作兜底

@stock_app.command('run', context_settings={'ignore_unknown_options': False})
def _run_action(
        action: str = typer.Argument(..., help='动作名 (60+ 个, 见 `webtool stock tools`)'),
        codes: list[str] = typer.Argument(None, help='股票代码 / 域 / 关键词 (按动作解释)'),
        date: str = typer.Option(None, '--date'), only_buy: bool = typer.Option(False, '--only-buy'),
        scope: str = typer.Option('industry', '--scope'),
        pool: str = typer.Option('short', '--pool'), min_score: int = typer.Option(60, '--min-score'),
        limit: int = typer.Option(10, '-n', '--limit'), n: int = typer.Option(3, '--n'),
        tool: str = typer.Option(None, '--tool'), params: list[str] = typer.Option(None, '--arg', metavar='K=V'),
        keyword: str = typer.Option('', '--keyword'), timeout: float = typer.Option(60.0, '--timeout'),
        method: str = typer.Option(None, '--method'),
        by: str = typer.Option('source', '--by'),
        text: list[str] = typer.Option(None, '--text', metavar='文本'),
        excel: str = typer.Option(None, '--excel'),
        kind: str = typer.Option(None, '--kind'), name: str = typer.Option(None, '--name'),
        thesis: str = typer.Option(None, '--thesis'),
        driver: list[str] = typer.Option(None, '--driver'), risk: list[str] = typer.Option(None, '--risk'),
        catalyst: list[str] = typer.Option(None, '--catalyst'), mid: list[str] = typer.Option(None, '--mid'),
        bars: int = typer.Option(120, '--bars'), period: str = typer.Option('day', '--period'),
        chart: bool = typer.Option(False, '--chart'), chart_out: str = typer.Option(None, '--chart-out'),
        ma: str = typer.Option('5,10,20', '--ma'), mavg: str = typer.Option(None, '--mavg'),
        start: str = typer.Option(None, '--start'), end: str = typer.Option(None, '--end'),
        days: int = typer.Option(1, '--days'), no_auction: bool = typer.Option(False, '--no-auction'),
        after_hours: bool = typer.Option(False, '--after-hours'), gran: int = typer.Option(60, '--gran'),
        dma: str = typer.Option('5,10,20,60', '--dma'), limit_y: bool = typer.Option(False, '--limit-y'),
        combo: bool = typer.Option(False, '--combo'), auto_y: bool = typer.Option(False, '--auto-y'),
        png: bool = typer.Option(False, '--png'), macd: bool = typer.Option(False, '--macd'),
        ascii_art: bool = typer.Option(False, '--ascii'),
        url: str = typer.Option('', '--url'), referer: str = typer.Option('', '--referer'),
        encoding: str = typer.Option('', '--encoding'), pick: str = typer.Option('', '--pick'),
        form: str = typer.Option('', '--form'), raw: bool = typer.Option(False, '--raw'),
        http_timeout: float = typer.Option(20.0, '--http-timeout'),
        post: bool = typer.Option(False, '--post'), method_only: bool = typer.Option(False, '--method-only'),
        lib: str = typer.Option('akshare', '--lib'), full: bool = typer.Option(False, '--full'),
        fmt: str = Fmt, output: str = Output):
    """专家模式: 任意动作 + 完整参数 (旧版接口)"""
    _form = {}
    for pair in (form or '').split('&'):
        if '=' in pair:
            k, v = pair.split('=', 1)
            _form[k] = v
    return _dispatch(action, fmt, output, codes=list(codes or []), date=date,
                     only_buy=only_buy, scope=scope, pool=pool, min_score=min_score,
                     limit=limit, n=n, tool=tool, params=list(params or []),
                     keyword=keyword, timeout=timeout, method=method, by=by,
                     texts=list(text or []), excel=excel, kind=kind, name=name,
                     thesis=thesis, drivers=list(driver or []), risks=list(risk or []),
                     catalysts=list(catalyst or []), mid=list(mid or []),
                     bars=bars, period=period, chart=chart, chart_out=chart_out,
                     ma=ma, mavg=mavg, start=start, end=end, days=days,
                     no_auction=no_auction, after_hours=after_hours, gran=gran,
                     dma=dma, limit_y=limit_y, combo=combo, auto_y=auto_y,
                     png=png, macd=macd, ascii_art=ascii_art, url=url,
                     referer=referer, encoding=encoding, pick=pick, form=_form,
                     raw=raw, http_timeout=http_timeout, post=post,
                     method_only=method_only, lib=lib, full=full)


app.add_typer(stock_app, name='stock')


# ---------------------------------------------------------------- 标准动作
# _act_std 系列: 单代码 + 无额外参数, 批量注册避免 15 段重复代码

_STD_ACTIONS = {
    'income': '利润表',
    'balance': '资产负债表',
    'cashflow': '现金流量表',
    'company': '公司概况',
    'business': '主营业务构成',
    'holders': '十大股东',
    'holder_chg': '股东变动',
    'industry': '行业板块列表',
    'concept': '概念板块列表',
    'industry_of': '个股所属行业/概念',
    'dividend': '分红排行',
    'margin': '融资融券',
    'screener': '条件选股',
    'ipo': '新股',
    'index': '指数成分',
    'holder': '股东户数',
    'forecast': '业绩预告',
}


def _mk_std(action, desc):
    def cmd(code: str = typer.Argument(None, help='股票代码'),
            limit: int = typer.Option(10, '-n', '--limit', help='条数'),
            fmt: str = Fmt, output: str = Output):
        return _dispatch(action, fmt, output, codes=[code] if code else [], limit=limit)
    cmd.__doc__ = desc
    return cmd


for _name, _desc in _STD_ACTIONS.items():
    stock_app.command(_name)(_mk_std(_name, _desc))
