"""stock text 视图: 行情/资金/分析/风险/选股/股东族"""
"""stock 子命令的 text 视图: 各 action 的纯文本渲染"""
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
import json



from webtool.stock.command._common import _fmt_vol
from webtool.stock.command._common import _kline_rows
from webtool.stock.command._common import _kline_title
from webtool.stock.command._common import _table_of

from webtool.stock.command._textfmt_data import _text_raw
from webtool.stock.command._textfmt_data import _text_raw_tail

def _text_analyze(out):
    """单股深度: 结论先行 (评分/信号), 再给三档入场价与止损。

    这份数据的消费者是人或 Agent 读结论, 不是程序读字段 —— 默认吐裸 JSON
    会把最关键的"能不能买、什么价买"埋在 20 行里。程序要字段用 -f json。
    """
    if not isinstance(out, dict):
        print(json.dumps(out, ensure_ascii=False))
        return
    t = out.get('technical') or {}
    q = out.get('quote') or {}
    bd = out.get('score_breakdown') or {}
    print(f"{out.get('code')} {out.get('name')} — {out.get('signal')} "
          f"(综合 {out.get('score')}/100)")
    if bd:
        print('  ' + '  '.join(f'{k.split("(")[0]}:{v}' for k, v in bd.items()))
    print(f"  现价 {q.get('current')} ({q.get('percent')}%)  PE {q.get('pe_ttm')}  "
          f"PB {q.get('pb')}  流通 {q.get('float_market_capital_yi')}亿")
    if t:
        print(f"  三档入场  突破 {t.get('entry_breakout')} / 回踩 {t.get('entry_pullback')} / "
              f"观察 {t.get('entry_observing')}")
        print(f"  止损 {t.get('hard_stop')}  目标 {t.get('target_1')} / {t.get('target_2')}")
        print(f"  MA5 {t.get('ma5')} MA20 {t.get('ma20')} MA60 {t.get('ma60')}  "
              f"RSI6 {t.get('rsi6')}  量比 {t.get('vol_ratio')}")
    for w in out.get('warnings') or []:
        print(f'  ⚠ {w}')
    prof = out.get('profile') or {}
    if prof.get('main_business'):
        print(f"  主营 {str(prof['main_business'])[:60]}")

def _text_sentiment(out):
    """消息面打分: 结论先行 (分数 + 倾向), 再列命中词。

    分数必须带符号显式印出 (+12 / -8), 不给绝对值 —— 消息面的关键信息是
    方向, 印成 12 会被读成"强利好"。
    """
    if not isinstance(out, dict):
        print(json.dumps(out, ensure_ascii=False))
        return
    s = out.get('score')
    n = out.get('news_count', 0)
    if not n:
        # 0 条 ≠ 中性。个股新闻源解析不出时打分器会给 0 分, 直接印"消息面 0 (中性)"
        # 会让调用方误以为"查过了没消息", 实际是根本没取到新闻。
        print('消息面 未取得 — 0 条输入 (新闻源未解析出条目, 或未指定 --text)')
        return
    s_txt = f'{s:+g}' if isinstance(s, (int, float)) else '未取得'
    tone = '利好' if isinstance(s, (int, float)) and s > 0 else (
        '利空' if isinstance(s, (int, float)) and s < 0 else '中性')
    print(f"消息面 {s_txt} ({tone}) — {n} 条, "
          f"正面 {out.get('positive_count', 0)} / 负面 {out.get('negative_count', 0)}")
    hits = out.get('hits')
    if isinstance(hits, dict):
        # 结构是 {"正": [命中词...], "负": [...]} 分组, 不是扁平的列表
        for tone, words in hits.items():
            if words:
                print(f'  [{tone}] {"、".join(str(w) for w in words)}')
    elif hits:
        for h in hits:
            print(f'  - {h.get("keyword") if isinstance(h, dict) else h}')
    if out.get('summary'):
        print(out['summary'])

def _text_risk(out):
    """风险核查: 逐股列命中项。clean=True 也必须显式说"无风险命中" ——
    空列表不显形会让调用方分不清"查过了没事"和"根本没查到"。

    scan_many 返回 {code: {hit, pending, clean}}, scan 返回单份 —— 两种都收。
    """
    if isinstance(out, dict) and 'hit' not in out and 'clean' not in out:
        items = [v if isinstance(v, dict) else {'code': k, 'hit': [v]}
                 for k, v in out.items()]
    else:
        items = [out]
    for r in items:
        code = r.get('code')
        hits = r.get('hit') or []
        if r.get('err'):
            print(f'[{code}] 查询失败: {r["err"]}')
            continue
        if r.get('clean') or not hits:
            print(f'[{code}] {r.get("name") or ""} 无风险命中 ✓')
            continue
        kinds = sorted({h.get('type') for h in hits if h.get('type')})
        print(f'[{code}] {r.get("name") or ""} 命中 {len(hits)} 项: {"、".join(kinds)}')
        for h in hits:
            print(f'    - {h.get("keyword")}: {h.get("title")}')

def _screen_counts(out):
    """通过/剔除计数。

    short 池自带 passed_count/failed_count, mid/long 池只给 passed/failed 列表
    —— 直接读 *_count 会让 mid 池渲染成 "通过 None"。列表长度为唯一可靠来源,
    有计数字段时以它为准 (short 池的 list 可能被截断)。
    """
    passed, failed = out.get('passed') or [], out.get('failed') or []
    return (out.get('passed_count') if out.get('passed_count') is not None else len(passed),
            out.get('failed_count') if out.get('failed_count') is not None else len(failed),
            passed, failed)

def _industry_cell(v):
    """行业列。short 池给字符串, mid/long 给 [{ind_code,ind_name,...}] 数组。

    数组直接塞进表格会打印整坨 dict, 这里只取一级行业名 (ind_type==1)。
    """
    if not v:
        return '—'
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        names = [x.get('ind_name') for x in v
                 if isinstance(x, dict) and x.get('ind_name') and x.get('ind_type') == 1]
        return '/'.join(names) if names else (v[0].get('ind_name') if v and isinstance(v[0], dict) else str(v)[:20])
    return str(v)[:20]

def _text_screen(out):
    """选股池 text: 通过标的给三档入场价与硬止损, 剔除的必须带原因。

    剔除清单不能省 —— 调用方要判断"为什么没看到某只票", 只给通过名单等于
    让 Agent 以为它不存在。
    """
    p_cnt, f_cnt, passed, failed = _screen_counts(out)
    extra = ''
    if out.get('min_score_threshold') is not None:
        extra += f"  门槛 {out.get('min_score_threshold')}"
    if out.get('industry_dispersion') is not None:
        extra += f"  行业分散 {out.get('industry_dispersion')}"
    print(f"通过 {p_cnt} / 剔除 {f_cnt}{extra}")
    if passed:
        print('\n通过:')
        for p in passed:
            t = p.get('technical') or {}
            tag = p.get('position_tag')
            print(f"  [{p.get('code')}] {p.get('name')}  分{p.get('score')}"
                  f"  {_industry_cell(p.get('industry'))}{'  ' + tag if tag else ''}")
            if t:
                print(f"      现价{t.get('current_price')} 突破{t.get('entry_breakout')} "
                      f"回踩{t.get('entry_pullback')} 观察{t.get('entry_observing')} "
                      f"止损{t.get('hard_stop')} 目标{t.get('target_1')}/{t.get('target_2')}")
    if failed:
        print('\n剔除:')
        for f in failed:
            print(f"  [{f.get('code')}] {f.get('name')}  {f.get('error')}"
                  f"  (闸门: {f.get('failed_gate') or '—'})")

def _text_flow(out):
    """资金流: 同花顺/东财回 headers+rows 的表格结构, 按表头直接铺。

    北向口径下 status=3 时数据源会显式给 unavailable, 这里照原样透出并标 ⚠,
    绝不当成 0 净额显示 —— 那会让 Agent 得出"北向零流入"的错误结论。
    """
    if not isinstance(out, dict):
        print(json.dumps(out, ensure_ascii=False, indent=1)[:2000])
        return
    if out.get('unavailable'):
        print(f"⚠ 资金流不可用: {out['unavailable']}")
        return
    source = out.get('source')
    if source:
        print(f'源: {source}')
    data = out.get('data')
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            print(data[:500])
            return
    if not isinstance(data, dict):
        print(json.dumps(data, ensure_ascii=False, indent=1)[:2000])
        return
    table = _table_of(data)
    if table:
        headers, rows = table
        print(' | '.join(str(h) for h in headers))
        for r in rows:
            if isinstance(r, list):
                print(' | '.join('—' if v in (None, '') else str(v) for v in r))
            else:
                print(json.dumps(r, ensure_ascii=False)[:300])
        return
    # 北向: data.data.{hk2sh,sh2hk,hk2sz,sz2hk} 四条通道, 每条带 status/date/净额
    inner = data.get('data')
    if isinstance(inner, dict) and any(k in inner for k in ('hk2sh', 'sh2hk', 'sz2hk', 'hk2sz')):
        got_real = False
        for ch, v in inner.items():
            if not isinstance(v, dict):
                continue
            if v.get('status') == 3:
                print(f'⚠ {ch}: 数据源声明不可用 (status=3)'
                      + (f' — {v.get("unavailable")}' if v.get('unavailable') else ''))
                continue
            date = v.get('date2') or '—'
            net, quota = v.get('dayNetAmtIn'), v.get('dayAmtThreshold')
            # 2024-08-19 起交易所不再披露北向净买入, 东财接口只剩额度: 该字段
            # 要么等于额度上限, 要么是 0, 两者都不是成交数据。一律按"未取得"
            # 标注 —— 印成 0 会被读成"今日北向零流入", 印成 4,200,000 万更离谱。
            if isinstance(net, (int, float)) and (net == 0
                                                  or (quota and net == quota)):
                print(f'⚠ {ch}  日期{date}  净流入未取得 (接口给的 {net:,.0f} 是占位/额度值)')
                continue
            got_real = True
            net_txt = f'{net:,.0f} 万' if isinstance(net, (int, float)) else '未取得'
            print(f'{ch}  日期{date}  净流入 {net_txt}')
        if not got_real:
            print('北向净买入自 2024-08-19 起停止披露, 全渠道已无真值 (不是"零流入")。\n'
                  '可替代: webtool stock data em_kamt (看额度字段) / '
                  'webtool stock flow --scope industry (行业资金)')
        return
    for k, v in data.items():
        if k == 'html':
            continue
        print(f'{k}: {json.dumps(v, ensure_ascii=False)[:300] if isinstance(v, (dict, list)) else v}')

def _text_kline(out):
    """K 线: 头一行关键信息 + 尾部若干根蜡烛 (输入本身是给程序看的,
    人要的是"最近怎么走的" —— 全 120 根铺终端没人读)"""
    if not isinstance(out, dict) or not out.get('ok'):
        print(f"K 线失败: {(out or {}).get('error') or (out or {}).get('err') or out}")
        return
    rows = _kline_rows(out)
    d = out.get('data') or {}
    period = {'day': '日线', 'week': '周线', 'month': '月线'}.get(
        (d.get('period') if isinstance(d, dict) else '') or 'day', '日线')
    if not rows:
        print(f'{_kline_title(out, "")} {period}: 无数据 (源 {out.get("source")})')
        return
    last, prev = rows[-1], (rows[-2] if len(rows) > 1 else rows[-1])
    chg = (last['close'] - prev['close']) / prev['close'] * 100 if prev['close'] else 0.0
    print(f"{_kline_title(out, '')}  {period}  {len(rows)} 根  "
          f"[{out.get('source')}]")
    print(f"最新 {last['date']}  收 {last['close']:.2f}  {chg:+.2f}%  "
          f"量 {_fmt_vol(last['volume'])}")
    lo, hi = min(r['low'] for r in rows), max(r['high'] for r in rows)
    print(f"区间 低 {lo:.2f} / 高 {hi:.2f}")
    for r in rows[-8:]:
        c = (r['close'] - r['open']) / r['open'] * 100 if r['open'] else 0.0
        print(f"  {r['date']}  开{r['open']:>9.2f} 高{r['high']:>9.2f} "
              f"低{r['low']:>9.2f} 收{r['close']:>9.2f}  {c:+6.2f}%  "
              f"{_fmt_vol(r['volume'])}")
    if out.get('chart_path'):
        print(f'图: {out["chart_path"]}')

def _text_holder(out):
    """股东研究: 摘要 + 前十大股东表 + 股东户数趋势 (这是最该先看的两块)"""
    if not isinstance(out, dict) or not out.get('ok'):
        _text_raw(out)
        return
    data = out.get('data') or {}
    gdrs = data.get('gdrs') or []
    if gdrs:
        print('股东户数 (每报告期):')
        for g in gdrs[:6]:
            print(f"  {(g.get('END_DATE') or '')[:10]}  户数{g.get('HOLDER_TOTAL_NUM'):,}  "
                  f"户均持股{g.get('AVG_FREE_SHARES')}  集中度{g.get('HOLD_FOCUS')}")
    sd = data.get('sdgd') or []
    if sd:
        print(f"\n前十大股东 ({sd[0].get('END_DATE', '')[:10]}):")
        for h in sd[:10]:
            print(f"  {h.get('HOLDER_RANK')}. {str(h.get('HOLDER_NAME'))[:28]}  "
                  f"{h.get('HOLD_NUM_RATIO')}%  变动 {h.get('HOLD_NUM_CHANGE')}")
    jg = data.get('jgcc') or []
    if jg:
        print(f'\n机构持股 ({(jg[0].get("REPORT_DATE") or "")[:10]}):')
        for j in jg[:5]:
            print(f"  {j.get('ORG_TYPE')}  机构{j.get('TOTAL_ORG_NUM')}家  "
                  f"占流通股{j.get('TOTAL_SHARES_RATIO')}%")
    _text_raw_tail(out)


def _intraday_summary(out):
    """分时摘要行 (text / markdown 共用) → (标题行, [要点行], 点列表)"""
    d = (out or {}).get('data') or {}
    days = d.get('days') or []
    pts = [p for day in days for p in (day.get('points') or [])]
    if not pts:
        return d.get('name') or '', [], []
    first, last = pts[0], pts[-1]
    pre = d.get('preclose') or days[-1].get('preclose') or first['price']
    chg = last['price'] - pre
    pct = (chg / pre * 100) if pre else 0.0
    tag = '五日分时' if len(days) > 1 else '分时'
    head = (f"{d.get('name') or ''} {d.get('symbol') or ''}".strip()
            + f"  {tag}  {len(days)}日  [{out.get('source')}]")
    span = (f"{days[0].get('date')} {days[0]['points'][0]['t']} ~ "
            f"{days[-1].get('date')} {days[-1]['points'][-1]['t']}"
            if len(days) > 1 else f"{days[0].get('date')} {first['t']}-{last['t']}")
    hi = max(p['price'] for p in pts)
    lo = min(p['price'] for p in pts)
    avg = last.get('avg')
    lines = [f"现价 {last['price']:.2f}  涨跌 {chg:+.2f} ({pct:+.2f}%)  昨收 {pre:.2f}",
             f"区间 {span}  高 {hi:.2f}  低 {lo:.2f}"
             + (f"  均价 {avg:.2f}" if avg else '')]
    if len(days) == 1:
        if d.get('auction'):
            lines.append('集合竞价 已含 (09:15-09:25)')
        elif d.get('auction_note'):
            lines.append(f"集合竞价 未含 — {d['auction_note']}")
        else:
            lines.append('集合竞价 未含 (--no-auction)')
    return head, lines, pts


def _text_intraday(out):
    """分时: 摘要 + 最近若干分钟 (全量点铺终端没人读, 图才是主体)"""
    if not isinstance(out, dict) or not out.get('ok'):
        print(f"分时失败: {(out or {}).get('error') or out}")
        return
    head, lines, pts = _intraday_summary(out)
    if not pts:
        print(f'{head}: 无数据')
        return
    print(head)
    for ln in lines:
        print(f'  {ln}')
    print('  最近 10 分钟:')
    for p in pts[-10:]:
        print(f"    {p['t']}  {p['price']:>9.2f}  均 {p['avg']:>9.2f}  "
              f"量 {_fmt_vol(p.get('vol') or 0)}")
    if out.get('chart_path'):
        print(f'图: {out["chart_path"]}')


def _md_intraday(out):
    head, lines, pts = _intraday_summary(out)
    if not pts:
        print(f'**{head}**: 无数据')
        return
    print(f'## {head}\n')
    for ln in lines:
        print(f'- {ln}')
    print('\n| 时间 | 价格 | 均价 | 量 |')
    print('|---|---|---|---|')
    for p in pts[-10:]:
        print(f"| {p['t']} | {p['price']:.2f} | {p['avg']:.2f} | "
              f"{_fmt_vol(p.get('vol') or 0)} |")
    if out.get('chart_path'):
        print(f"\n图: `{out['chart_path']}`")
