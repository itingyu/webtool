"""stock 核心数据动作: 行情/资金/分析/选股/图表"""
"""webtool stock 子命令: 动作分发 + 输出渲染

两座桥 (bridge/engine.py 脚本层 / bridge/srv.py 编排层) 在这里汇合成一个扁平的动作表。动作分三类:

    数据动作  quote pool check calendar flow news announcement financials
              analyze screen risk            —— 走 engine 脚本层
    透传动作  mcp <tool>                     —— 按名调用 24 个动作 (未单独暴露的那些)
    元动作   tools health                    —— 能力清单与两侧探活

输出与 webtool 其他数据命令一致: 数据动作按 args.format 自己渲染 (json 全字段 /
text 行内可读 / markdown 表格), 走 cli.app._run 的 emit 落盘通道。

口径纪律 (从 stock-master 继承, 现由 engine 维护):
  - 接口返回 0/空 不当正常值, 由各桥透传 status, 渲染时显式标注
  - 北向资金不可用必须显式 ⚠, 不填 0
  - 池/榜单类结果必带数据日 (date), 涨停池尤其 —— 接口对无效日期会静默回旧数据
"""

from webtool.stock.bridge import engine as _engine
from webtool.stock.bridge import rawapi as _raw
from webtool.stock.bridge import srv as _srv


from webtool.stock.command._common import _args_dict
from webtool.stock.command._common import _code
from webtool.stock.command._common import codes_input
from webtool.stock.command._common import _index_symbol
from webtool.stock.command._common import _write_kline_chart
from webtool.stock.command._common import _kline_rows, _kline_title
from webtool.stock.command._common import (_write_intraday_chart,
                                            _write_intraday_combo,
                                            _dma_levels)

def _act_quote(args, cfg):
    return _engine.do_quote(codes_input(args))

def _act_pool(args, cfg):
    return _engine.do_pool(args.date, args.only_buy)

def _act_check(args, cfg):
    return _engine.do_check(codes_input(args))

def _act_calendar(args, cfg):
    return _engine.do_calendar(args.date, args.n)

def _act_flow(args, cfg):
    return _engine.do_capital_flow(args.scope)

def _act_news(args, cfg):
    return _engine.do_news(_code(args), args.limit)

def _act_announcement(args, cfg):
    return _engine.do_announcements(_code(args), args.limit)

def _act_financials(args, cfg):
    return _engine.do_financials(_code(args))

def _act_analyze(args, cfg):
    return _engine.do_analyze(_code(args))

def _act_screen(args, cfg):
    return _engine.do_screen(args.pool, args.min_score, args.codes)

def _act_risk(args, cfg):
    return _engine.do_risk(codes_input(args))

def _act_holder(args, cfg):
    """股东研究 (东财) —— 持仓变动/机构调研, 比 stock_top_holders 动作更细"""
    code = _code(args)
    mkt = 'SH' if code.startswith('6') else ('SZ' if code[0] in '03' else 'BJ')
    return _raw.call('em_shareholder_research', {'code': f'{mkt}{code}'})

def _act_forecast(args, cfg):
    """盈利预测 (东财) + 主营构成 (em_business_analysis) 交叉"""
    code = _code(args)
    mkt = 'SH' if code.startswith('6') else ('SZ' if code[0] in '03' else 'BJ')
    return _raw.call('em_profit_forecast', {'code': f'{mkt}{code}'})

def _act_report(args, cfg):
    return _engine.do_report(code=_code(args, required=False), pool=args.pool,
                             news=list(args.texts or []) or None)

def _act_excel(args, cfg):
    if not args.excel:
        raise ValueError('excel 需要 --excel 指定输出路径, 例: --excel picks.xlsx')
    return _engine.do_excel(args.excel, pool='short', min_score=args.min_score)

def _act_sentiment(args, cfg):
    items = list(args.texts or [])
    if not items:
        # 没给 --text 就理解为"给这只票的新闻打分", 省一次取新闻的重复输入
        items = _engine._news_texts(_code(args))
    return _engine.do_sentiment(items)

def _act_diagram(args, cfg):
    return _engine.do_diagram(args.kind or 'tree', code=_code(args, required=False),
                              name=args.name, thesis=args.thesis,
                              drivers=list(args.drivers or []),
                              risks=list(args.risks or []),
                              catalysts=list(args.catalysts or []),
                              mid=list(getattr(args, 'mid', None) or []))

def _act_kline(args, cfg):
    """K 线: 取数 (编排层 stock_kline 的多源回退) + 可选出图

    `--chart` 落一份自包含 SVG —— 零依赖, 不用装 matplotlib, 也不用联网取
    字体; 生成的文件在 app 里可直接预览。`--start/--end` 支持指定区间:
    源多按"根数"取数, 所以按区间跨度反推根数, 取回后再按日期裁 (两条源
    都能用, 不依赖某个源是否支持 beg/end)。
    """
    from webtool.stock.command._common import _kline_range, _clip_kline_range
    code = (list(args.codes or ['']) or [''])[0]
    start = _norm_day(getattr(args, 'start', None))
    end = _norm_day(getattr(args, 'end', None))
    bars = int(getattr(args, 'bars', 0) or 120)
    # 区间取数要给均线留预热窗口: 画 MA120 时, 可见首根之前必须有 119 根,
    # 否则图上 MA120 会"从中途才开始", 看着像数据缺失。
    ma_arg = getattr(args, 'ma', None) or '5,10,20'
    ma_vals = [int(m) for m in ma_arg.split(',') if m.strip().isdigit()]
    warm = max(ma_vals) if ma_vals else 0
    count = bars if not (start or end) else min(_kline_range(start, end) + warm, 3000)
    out = _srv.do_call('stock_kline', {'symbol': code,
                                       'period': args.period or 'day',
                                       'count': count}, timeout=args.timeout)
    # 源普遍多给一根 (腾讯按 count 返回 count+1), 裁到用户要的根数 ——
    # 否则标题写"60 根"、实际画 61 根, 图与命令不符。给了区间就按区间裁。
    d = out.get('data') if isinstance(out, dict) else None
    if isinstance(d, dict):
        # 各源对'周期'的叫法不一 (腾讯有 period, 东财没有) —— 我们要的就是
        # args.period, 统一回填, 免得渲染层把周线标成日线。
        d.setdefault('period', args.period or 'day')
        for key in ('klines', 'rows'):
            ks = d.get(key)
            if not isinstance(ks, list) or not ks:
                continue
            raw = ks[:]          # 作图要用未裁剪的全量算均线 (预热窗口)
            if start or end:
                ks = _clip_kline_range(ks, start, end, bars if not start else 0)
            elif len(ks) > bars:
                ks = ks[-bars:]
            d[key] = ks
            full_rows = raw
    if getattr(args, 'chart', False) and isinstance(out, dict):
        out['chart_path'] = _write_kline_chart(out, args, code, count,
                                               full_rows=locals().get('full_rows'))
    if getattr(args, 'ascii_art', False) and isinstance(out, dict):
        from webtool.render.ascii_chart import kline_ascii
        rows_a = _kline_rows(out)
        period = getattr(args, 'period', 'day') or 'day'
        cn = {'day': '日线', 'week': '周线', 'month': '月线'}.get(period, period)
        head = f'{_kline_title(out, code)} · {cn} · {len(rows_a)} 根'
        hh = int(getattr(args, 'ascii_h', 0) or 0) or 20
        ww = int(getattr(args, 'ascii_w', 0) or 0) or None
        print(kline_ascii(rows_a,
                          ma=[m for m in (getattr(args, 'ma', '') or '').split(',') if m.strip()],
                          title=head, color=not getattr(args, 'no_color', False),
                          height=hh, width=ww,
                          plain=bool(getattr(args, 'ascii_plain', False)),
                          wide=bool(getattr(args, 'ascii_wide', False)),
                          gap=bool(getattr(args, 'ascii_gap', False))))
    return out


def _norm_day(s):
    """'20250101' / '2025-01-01' → '2025-01-01' (区间过滤统一用它比较)"""
    s = str(s or '').strip().replace('/', '-')
    if len(s) == 8 and s.isdigit():
        return f'{s[:4]}-{s[4:6]}-{s[6:8]}'
    return s[:10]


def _act_intraday(args, cfg):
    """分时: 当日 / 五日, 可出图 (左轴价格 + 右轴涨幅)

    当日图默认带集合竞价 (09:15-09:25), `--no-auction` 去掉; 竞价只有东财
    一个源, 拿不到时图照出、并在数据里写明 auction=False 与原因。
    """
    code = (list(args.codes or ['']) or [''])[0]
    ndays = 5 if int(getattr(args, 'days', 1) or 1) >= 5 else 1
    combo = bool(getattr(args, 'combo', False))
    gran = int(getattr(args, 'gran', 60) or 60)
    if combo and gran >= 60:
        gran = 30                     # 组合图默认带一张 30 秒的细粒度面板
    dma_spec = (getattr(args, 'dma', None) or '').strip()
    outk = None
    if combo or dma_spec:             # 分时叠日线均线要一份 K 线; 组合图本来也要
        outk = _srv.do_call('stock_kline',
                            {'symbol': code,
                             'period': 'day',
                             'count': 200},
                            timeout=args.timeout)
    out = _srv.do_call('stock_intraday',
                       {'symbol': code, 'ndays': ndays,
                        'auction': not getattr(args, 'no_auction', False),
                        'after_hours': bool(getattr(args, 'after_hours', False)),
                        'gran': gran},
                       timeout=args.timeout)
    if isinstance(out, dict) and outk:
        levels = _dma_levels(outk, dma_spec or '5,10,20,60')
        if levels:
            out.setdefault('data', {})['dma'] = levels
    if (getattr(args, 'chart', False) or combo) and isinstance(out, dict):
        if combo:
            out5 = _srv.do_call('stock_intraday',
                                {'symbol': code, 'ndays': 5, 'auction': False},
                                timeout=args.timeout)
            out['chart_path'] = _write_intraday_combo([out, out5], args, code,
                                                      kline=outk)
        else:
            out['chart_path'] = _write_intraday_chart(out, args, code)
    if getattr(args, 'ascii_art', False) and isinstance(out, dict):
        from webtool.render.ascii_chart import intraday_ascii
        d = out.get('data') or {}
        days = d.get('days') or []
        if days:
            nm = ' '.join(x for x in (d.get('name'), d.get('code')) if x)
            tag = '五日' if ndays >= 5 else '当日'
            head = f'{nm or code} · {tag}分时'
            if d.get('preclose'):
                head += f' · 昨收 {d["preclose"]:.2f}'
            hh = int(getattr(args, 'ascii_h', 0) or 0) or 16
            ww = int(getattr(args, 'ascii_w', 0) or 0) or None
            print(intraday_ascii(days, title=head,
                                 preclose=d.get('preclose'),
                                 color=not getattr(args, 'no_color', False),
                                 height=hh, width=ww,
                                 plain=bool(getattr(args, 'ascii_plain', False))))
    return out

def _act_std(action_name):
    """编排动作的通用子命令包装

    与 mcp 透传的区别: 位置参数直接给 symbol/codes (不用 --arg symbol=),
    渲染层按动作名走对表格, 编排层错误转 StockError 统一退出码。
    """
    def run(args, cfg):
        params = {}
        # 位置参数 → symbol (支持多个, 编排层只吃一个则取首个)
        codes = [c for c in (list(args.codes) if args.codes else []) if c]
        if codes and 'symbol' not in params:
            params['symbol'] = codes[0]
        # 指数动作: 中文别名/裸 6 位在动作层归一, 编排层只认标准形态
        if action_name == 'stock_index' and params.get('symbol'):
            params['symbol'] = _index_symbol(params['symbol'])
        params.update(_args_dict(args))
        return _srv.do_call(action_name, params, timeout=args.timeout)
    return run

