"""stock 子命令的输出分派: fmt 选择与 markdown/表格渲染"""
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
import sys



from webtool.stock.command._common import _fmt_vol
from webtool.stock.command._textfmt import _industry_cell
from webtool.stock.command._common import _j
from webtool.stock.command._common import _kline_rows
from webtool.stock.command._common import _kline_title
from webtool.stock.command._common import _norm_fmt
from webtool.stock.command._common import _passthrough
from webtool.stock.command._textfmt import _screen_counts
from webtool.stock.command._textfmt import _text
from webtool.stock.command._common import _unresolved

def _render(out, fmt, action):
    fmt = _norm_fmt(fmt)
    # http-rows / em-report 直接返回 DataFrame, 渲染层先转成可序列化形状
    if hasattr(out, 'to_dict') and hasattr(out, 'columns'):
        n = len(out)
        out = {'rows': n, 'columns': [str(c) for c in out.columns],
               'records': out.to_dict('records')}
    # 未解析载荷只在 text/markdown 显式标注; json 保持原样 —— 程序消费方
    # 可能自己要那份 html, 但不该由我们替它决定丢弃。
    note = _unresolved(out)
    if fmt == 'json':
        print(_j(out, 10 ** 9))
        return
    if action in ('api', 'data', 'data-call', 'data-url', 'data-find',
                  'data-list', 'data-health',
                  'forecast', 'api-list', 'api-search'):
        # 数据源层的接口形态千差万别 (含本身就返回 HTML 的), 那个"本该是
        # 列表却回了原始 HTML"的守卫对它不适用, 会把正常响应误报成未解析。
        note = None
    if note:
        print(f'⚠ {note}', file=sys.stderr)
    if fmt == 'markdown':
        _md(out, action)
    else:
        _text(out, action)

def _k(*row):
    """表格行: None → '—' (缺数据显式占位, 不印 0)"""
    return ' | '.join('—' if v is None or v == '' else str(v) for v in row)

def _table(head, rows):
    print('| ' + ' | '.join(head) + ' |')
    print('|' + '|'.join(['---'] * len(head)) + '|')
    for r in rows:
        print('| ' + _k(*r) + ' |')

def _md(out, action):
    if action in ('report', 'diagram'):
        _passthrough(out, 'md' if action == 'diagram' else 'report')
        return
    if action == 'intraday' and isinstance(out, dict):
        from webtool.stock.command._textfmt_quote import _md_intraday
        _md_intraday(out)
        return
    if action == 'kline' and isinstance(out, dict):
        rows = _kline_rows(out)
        d = out.get('data') or {}
        period = {'day': '日线', 'week': '周线', 'month': '月线'}.get(
            (d.get('period') if isinstance(d, dict) else '') or 'day', '日线')
        if not rows:
            print(f'**{_kline_title(out, "")}** {period}: 无数据 (源 {out.get("source")})')
            return
        last, prev = rows[-1], (rows[-2] if len(rows) > 1 else rows[-1])
        chg = (last['close'] - prev['close']) / prev['close'] * 100 if prev['close'] else 0.0
        print(f"## {_kline_title(out, '')} — {period} ({len(rows)} 根, 源 {out.get('source')})\n")
        print(f"最新 **{last['close']:.2f}** ({chg:+.2f}%) 于 {last['date']}; "
              f"区间 {min(r['low'] for r in rows):.2f} ~ {max(r['high'] for r in rows):.2f}\n")
        print('| 日期 | 开 | 高 | 低 | 收 | 涨跌 | 量 |')
        print('|---|---|---|---|---|---|---|')
        for r in rows[-10:]:
            c = (r['close'] - r['open']) / r['open'] * 100 if r['open'] else 0.0
            print(f"| {r['date']} | {r['open']:.2f} | {r['high']:.2f} | {r['low']:.2f} "
                  f"| {r['close']:.2f} | {c:+.2f}% | {_fmt_vol(r['volume'])} |")
        if out.get('chart_path'):
            print(f"\n图: `{out['chart_path']}`")
        return
    if action == 'screen' and isinstance(out, dict):
        p_cnt, f_cnt, passed, failed = _screen_counts(out)
        thr = out.get('min_score_threshold')
        print(f"## 选股池 — 通过 {p_cnt} / 剔除 {f_cnt}"
              + (f", 门槛 {thr}" if thr is not None else '') + '\n')
        print('| 代码 | 名称 | 分 | 行业 | 位置 | 现价 | 突破 | 回踩 | 观察 | 止损 | 目标1 | 目标2 |')
        print('|---|---|---|---|---|---|---|---|---|---|---|---|')
        for p in passed:
            t = p.get('technical') or {}
            print('| ' + _k(p.get('code'), p.get('name'), p.get('score'),
                            _industry_cell(p.get('industry')), p.get('position_tag'),
                            t.get('current_price'), t.get('entry_breakout'),
                            t.get('entry_pullback'), t.get('entry_observing'),
                            t.get('hard_stop'), t.get('target_1'), t.get('target_2')) + ' |')
        if failed:
            print('\n### 剔除清单\n')
            print('| 代码 | 名称 | 闸门 | 原因 |')
            print('|---|---|---|---|')
            for f in failed:
                print('| ' + _k(f.get('code'), f.get('name'),
                                f.get('failed_gate'), f.get('error')) + ' |')
        return
    if action == 'tools' and isinstance(out, dict) and 'tools' in out:
        print(f'## stock 动作 ({out.get("count", len(out["tools"]))} 个)\n')
        _table(['动作', '说明'], [(t['name'], t.get('desc')) for t in out['tools']])
        return
    if action == 'quote':
        print('## 实时行情\n')
        _table(['代码', '名称', '现价', '涨跌幅%', '换手%', '量比', '流通市值亿', 'PE动', 'PB'],
               [(q.get('input'), q.get('name'), q.get('现价'), q.get('涨跌幅'),
                 q.get('换手%'), q.get('量比'), q.get('流通市值亿'),
                 q.get('PE动'), q.get('PB')) for q in out])
        return
    if action == 'pool' and isinstance(out, dict):
        print(f"## 涨停池 ({out.get('date')}) — {out.get('count')} 只\n")
        if out.get('提示'):
            print(f"> ⚠ {out['提示']}\n")
        _table(['代码', '名称', '连板', '行业', '封单亿', '炸板', '首封'],
               [(r.get('code'), r.get('name'), r.get('连板'), r.get('行业'),
                 r.get('封单亿'), r.get('炸板次数'), r.get('首封'))
                for r in out.get('rows') or []])
        return
    if action in ('api-list', 'api-search') and isinstance(out, dict):
        # 功能分类表本身是"给人读的目录", 走默认的 ```json 围栏会毁掉可读性
        # (154 个方法名挤成一行)。这里给真 markdown。
        kw = out.get('keyword')
        title = '数据源层方法分类' if not kw else f'数据源层搜索: {kw}'
        if out.get('by') == 'function':
            title = f'数据源层共 {out.get("count")} 个方法 — 按功能'
        print(f'## {title}\n')
        groups = out.get('categories') or {}
        if groups:
            for label, c in groups.items():
                print(f'### {label}\n')
                if c.get('desc'):
                    print(f"{c['desc']}\n")
                prim = c.get('primary') or []
                if prim:
                    print(f"- **首选** ({len(prim)}): "
                          + ' '.join(f'`{x}`' for x in prim))
                fb = c.get('fallback') or []
                if fb:
                    print(f"- 备选 ({len(fb)}): "
                          + ' '.join(f'`{x}`' for x in fb))
                print()
            return
        methods = out.get('methods') or []
        if isinstance(methods, list):
            _table(['方法', '功能类', '签名', '说明'],
                   [(m.get('method'), m.get('category') or '—',
                     m.get('sig', ''), (m.get('doc') or '')[:70])
                    for m in methods])
            return
        if isinstance(methods, dict):
            _table(['数据源', '个数'],
                   [(k, len(v)) for k, v in methods.items()])
            return
    print('```json')
    print(json.dumps(out, ensure_ascii=False, indent=1))
    print('```')

