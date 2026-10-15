"""stock text 视图分派: action → 渲染函数"""
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



from webtool.stock.command._common import _passthrough
from webtool.stock.command._common import _unresolved

# 视图助手: _render 等外部调用方按本模块 (text 视图门面) 取用, 不直接
# 摸子模块 —— 子模块怎么分是内部事, 对外只认这一层
from webtool.stock.command._textfmt_quote import _industry_cell as _industry_cell
from webtool.stock.command._textfmt_quote import _screen_counts as _screen_counts
from webtool.stock.command._textfmt_quote import _text_analyze
from webtool.stock.command._textfmt_data import _text_eco
from webtool.stock.command._textfmt_data import _text_eco_list
from webtool.stock.command._textfmt_data import _text_eco_search
from webtool.stock.command._textfmt_quote import _text_flow
from webtool.stock.command._textfmt_quote import _text_holder
from webtool.stock.command._textfmt_quote import _text_kline
from webtool.stock.command._textfmt_data import _text_raw
from webtool.stock.command._textfmt_quote import _text_risk
from webtool.stock.command._textfmt_quote import _text_screen
from webtool.stock.command._textfmt_quote import _text_sentiment
from webtool.stock.command._textfmt_data import _text_srv

def _text(out, action):
    if action == 'eco':
        _text_eco(out)
        return
    if action == 'eco-list':
        _text_eco_list(out)
        return
    if action == 'eco-search':
        _text_eco_search(out)
        return
    if action in ('http-get', 'http-post'):
        print(out if isinstance(out, str) else json.dumps(out, ensure_ascii=False, indent=1))
        return

    if action and action.startswith('docs-'):
        c = out.get('content')
        if c:
            print(c)
            rest = {k: v for k, v in out.items() if k != 'content'}
            if rest:
                print('\n--- meta ---')
                print(json.dumps(rest, ensure_ascii=False, indent=1))
            return
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return

    if action == 'eco-health':
        for lib, st in (out or {}).items():
            if st.get('installed'):
                print(f"  ✓ {lib}: {st.get('funcs')} 个接口")
            else:
                print(f"  ✗ {lib}: 未安装")
        return
    if action in ('news', 'announcement', 'financials', 'mcp'):
        _text_srv(out, note_only=bool(_unresolved(out)))
        return
    if action == 'holder':
        _text_holder(out)
        return
    if action in ('api', 'forecast', 'api-list', 'api-search'):
        # 不跑 _unresolved 守卫: 那守卫针对 news/announcement 那类"本该给列表
        # 却回了原始 HTML"的情况。数据源层有些接口 (如 ths_stockpage_finance)
        # 本身就返回 HTML 表格, 套同一个守卫会误报成"未解析"。
        _text_raw(out, action)
        return
    if action == 'analyze':
        _text_analyze(out)
        return
    if action == 'risk':
        _text_risk(out if isinstance(out, dict) else {})
        return
    if action == 'flow':
        _text_flow(out)
        return
    if action == 'kline':
        _text_kline(out)
        return
    if action in ('report', 'diagram'):
        _passthrough(out, 'md' if action == 'diagram' else 'report')
        return
    if action == 'excel':
        if isinstance(out, dict) and out.get('ok'):
            print(f"已导出 {out.get('path')} — 通过 {out.get('passed')} / 剔除 {out.get('failed')}")
        else:
            print(json.dumps(out, ensure_ascii=False))
        return
    if action == 'sentiment':
        _text_sentiment(out)
        return
    if action == 'quote':
        for q in out:
            if not q.get('ok'):
                print(f"[{q.get('input')}] 无数据: {q.get('err')}")
                continue
            print(f"[{q.get('name')}] {q.get('现价')}  {q.get('涨跌幅')}%  "
                  f"换手{q.get('换手%')}% 量比{q.get('量比')} "
                  f"流通市值{q.get('流通市值亿')}亿 PE{q.get('PE动')}")
        return
    if action == 'screen' and isinstance(out, dict):
        _text_screen(out)
        return
    if action == 'tools' and isinstance(out, dict) and 'tools' in out:
        for t in out['tools']:
            print(f"{t['name']}  {t.get('desc')}")
        return
    if action == 'pool' and isinstance(out, dict):
        if not out.get('ok'):
            print(f"涨停池失败: {out.get('err') or out.get('error')}")
            return
        print(f"涨停池 {out.get('date')} — {out.get('count')} 只")
        if out.get('提示'):
            print(f"⚠ {out['提示']}")
        for r in out.get('rows') or []:
            print(f"[{r.get('code')}] {r.get('name')}  {r.get('行业') or ''}  "
                  f"连板{r.get('连板', '—')}  {r.get('涨停统计') or ''}  "
                  f"封单{r.get('封单亿', '—')}亿")
        return
    # 通用兜底: 非结构化的按 key: value 或原样 JSON
    if isinstance(out, dict):
        for k, v in out.items():
            if isinstance(v, (dict, list)):
                print(f"{k}: {json.dumps(v, ensure_ascii=False)}")
            else:
                print(f"{k}: {v}")
    else:
        print(json.dumps(out, ensure_ascii=False, indent=1))

