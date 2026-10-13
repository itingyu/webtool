"""webtool stock 子命令: 动作分发 + 输出渲染

两座桥 (master.py / mcp.py) 在这里汇合成一个扁平的动作表。动作分三类:

    数据动作  quote pool check calendar flow news announcement financials
              analyze screen risk            —— 走 stock-master 脚本层
    MCP 动作  mcp <tool>                     —— 透传调用服务端 24 个工具
    元动作   tools health                    —— 能力清单与两侧探活

输出与 webtool 其他数据命令一致: 数据动作按 args.format 自己渲染 (json 全字段 /
text 行内可读 / markdown 表格), 走 cli.app._run 的 emit 落盘通道。

口径纪律 (来自 stock-master 硬约束, 这里继承):
  - 接口返回 0/空 不当正常值, 由各桥透传 status, 渲染时显式标注
  - 北向资金不可用必须显式 ⚠, 不填 0
  - 池/榜单类结果必带数据日 (date), 涨停池尤其 —— 接口对无效日期会静默回旧数据
"""
import json
import sys
import time

from webtool.stock import master as _master
from webtool.stock import srv as _srv


def _norm_fmt(v, default='text'):
    return v or default


def _unresolved(out):
    """检测"服务端回了但没解析出结构"的情况。

    stock-master 的 clients 把服务端载荷原样透传, 所以会碰到两种形状:
    同花顺 stockpage 是 SPA, 服务端解析不出列表就把 100KB 原始 HTML 塞进 data.html;
    另一路把结构化结果 json.dumps 成了字符串塞进 data。
    这两种都不是"没数据", 强行当结果渲染会把 HTML 噪声喂给 Agent ——
    按硬约束第 9 条显式标注, 由调用方决定是换源还是自行解析。
    """
    if not isinstance(out, dict):
        return None
    if not out.get('ok', True):
        return out.get('err') or out.get('error') or '接口返回失败'
    data = out.get('data')
    if isinstance(data, str) and data.lstrip()[:1] in '{[':
        try:
            return _unresolved(json.loads(data))
        except json.JSONDecodeError:
            return None
    if isinstance(data, dict):
        if data.get('error'):
            return f'数据源错误: {data["error"]}'
        if _table_of(data):
            return None                     # headers+rows 表结构, 各动作自己渲染
        if data.get('html') and _items_of(data) is None:
            return (f'源返回原始 HTML 未解析出条目 ({len(data["html"])} 字符, '
                    f'html_len={data.get("html_len")}); 换 news 源或用 webtool fetch 自行解析')
    return None


def _table_of(data):
    """headers+rows 表结构 (同花顺资金流)。识别到就返回 (headers, rows) 供渲染。"""
    if isinstance(data, dict) and isinstance(data.get('headers'), list) \
            and isinstance(data.get('rows'), list):
        return data['headers'], data['rows']
    return None


# ---------- 动作表 ----------

def _code(args, required=True):
    """单股动作取代码: 用位置参数 codes 的第一项。

    这些动作只对一只股票, 但 CLI 统一用 codes 位置参数收 (quote/check/risk 是
    多股), 这里取首个并校验 —— 没给就报错退 2, 不把空代码丢给数据源。
    required=False 用于 report/diagram 这类既可单股又可不带代码的动作。
    """
    codes = getattr(args, 'codes', None) or []
    if not codes:
        if not required:
            return None
        raise ValueError('需要一个股票代码, 例: webtool stock analyze 600519')
    return codes[0]


def _act_quote(args, cfg):
    return _master.do_quote(args.codes)


def _act_pool(args, cfg):
    return _master.do_pool(args.date, args.only_buy)


def _act_check(args, cfg):
    return _master.do_check(args.codes)


def _act_calendar(args, cfg):
    return _master.do_calendar(args.date, args.n)


def _act_flow(args, cfg):
    return _master.do_capital_flow(args.scope)


def _act_news(args, cfg):
    return _master.do_news(_code(args), args.limit)


def _act_announcement(args, cfg):
    return _master.do_announcements(_code(args), args.limit)


def _act_financials(args, cfg):
    return _master.do_financials(_code(args))


def _act_analyze(args, cfg):
    return _master.do_analyze(_code(args))


def _act_screen(args, cfg):
    return _master.do_screen(args.pool, args.min_score, args.codes)


def _act_risk(args, cfg):
    return _master.do_risk(args.codes)


def _act_report(args, cfg):
    return _master.do_report(code=_code(args, required=False), pool=args.pool,
                             news=list(args.texts or []) or None)


def _act_excel(args, cfg):
    if not args.excel:
        raise ValueError('excel 需要 --excel 指定输出路径, 例: --excel picks.xlsx')
    return _master.do_excel(args.excel, pool='short', min_score=args.min_score)


def _act_sentiment(args, cfg):
    items = list(args.texts or [])
    if not items:
        # 没给 --text 就理解为"给这只票的新闻打分", 省一次取新闻的重复输入
        items = _master._news_texts(_code(args))
    return _master.do_sentiment(items)


def _act_diagram(args, cfg):
    return _master.do_diagram(args.kind or 'tree', code=_code(args, required=False),
                              name=args.name, thesis=args.thesis,
                              drivers=list(args.drivers or []),
                              risks=list(args.risks or []),
                              catalysts=list(args.catalysts or []),
                              mid=list(getattr(args, 'mid', None) or []))


def _act_mcp(args, cfg):
    if not getattr(args, 'tool', None):
        names = sorted(_srv.tool_names())
        raise ValueError(
            f'mcp 动作需要 --tool 指定工具名, 可用: {", ".join(names[:6])} ... '
            f'(完整清单: webtool stock tools)')
    params = {}
    for kv in (getattr(args, 'params', None) or ()):
        if '=' not in kv:
            raise ValueError(f'--arg 需要 k=v 形式, 收到 {kv!r}')
        k, _, v = kv.partition('=')
        params[k.strip()] = _coerce(v)
    return _srv.do_call(args.tool, params, timeout=args.timeout)


def _act_tools(args, cfg):
    return _srv.do_tools(args.keyword or '')


def _act_health(args, cfg):
    """两侧探活。任一侧不可用都照实报 unavailable, 不因为一侧挂了就不查另一侧"""
    out = {'master': {}, 'mcp': {}}
    home = _master.home()
    out['master']['home'] = home
    out['master']['installed'] = _master.available()
    if out['master']['installed']:
        t0 = time.time()
        try:
            q = _master.do_quote(['600519'])
            hit = next((x for x in q if x.get('ok')), None)
            out['master'].update(ok=bool(hit), took_ms=int((time.time() - t0) * 1000),
                                 probe='quote 600519', sample=hit.get('name') if hit else None)
        except Exception as e:                              # noqa: BLE001
            out['master'].update(ok=False, err=f'{type(e).__name__}: {e}')
    else:
        out['master']['err'] = f'未装在 {home} (可用 STOCK_MASTER_HOME 覆盖)'

    out['mcp']['server'] = f'{_srv.SERVER_HOME}/{_srv.SERVER_MOD}.py'
    out['mcp']['found'] = _srv.available()
    if out['mcp']['found']:
        t0 = time.time()
        try:
            _srv.call('stock_health_check', {})
            out['mcp'].update(ok=True, took_ms=int((time.time() - t0) * 1000),
                              tools=len(_srv.tool_names()))
        except Exception as e:                              # noqa: BLE001
            out['mcp'].update(ok=False, err=f'{type(e).__name__}: {e}')
    else:
        out['mcp']['err'] = f'服务端不可用 (STOCK_MCP_HOME 可覆盖路径)'
    out['ok'] = bool(out['master'].get('ok') or out['mcp'].get('ok'))
    return out


ACTIONS = {
    'quote': _act_quote, 'pool': _act_pool, 'check': _act_check,
    'calendar': _act_calendar, 'flow': _act_flow, 'news': _act_news,
    'announcement': _act_announcement, 'financials': _act_financials,
    'analyze': _act_analyze, 'screen': _act_screen, 'risk': _act_risk,
    'report': _act_report, 'excel': _act_excel, 'sentiment': _act_sentiment,
    'diagram': _act_diagram,
    'mcp': _act_mcp, 'tools': _act_tools, 'health': _act_health,
}

USAGE = """用法: webtool stock <动作> [参数]

数据动作 (走 stock-master 脚本层)
  quote <代码...>              实时行情, 支持指数别名(上证指数/创业板指)
  pool [--date D] [--only-buy] 涨停池 (连板/首封/炸板/封单/行业)
  check <代码...>              可买性核查 (板块归属 + ST/退市风险)
  calendar [--date D] [-n N]   交易日历
  flow [--scope industry|individual|north]  资金流榜单
  news <代码> [-n N]           个股新闻
  announcement <代码> [-n N]   公告列表
  financials <代码>            核心财务指标
  analyze <代码>               单股深度 (技术面+评分+决策信号+画像)
  screen [--pool short|mid|long] [--min-score N]  选股池
  risk <代码...>               风险核查 (重组/减持/立案/预亏)
  report <代码> | --pool short  成稿研报 (markdown, 单股/短线池)
  excel --excel 路径 [--min-score N]   选股池导出 xlsx (需 openpyxl)
  sentiment <代码> | --text "..."      消息面打分 -100~+100 (不给 --text 则给该股新闻打分)
  diagram --kind logic|tree|chain [...] mermaid 图
             tree  无参; logic 需 --code --name --thesis;
             chain 需 --name --driver(上游) --mid(中游) --catalyst(下游)

MCP 动作 (透传调用服务端 24 个工具)
  mcp <工具名> [--arg k=v]     透传调用, 例: webtool stock mcp stock_indicators --arg symbol=600519
  tools [关键词]               列工具清单

元动作
  health                       两侧探活
"""


def _coerce(v):
    """--arg 的值猜类型。与 cli/mcp.py 的差别: 纯数字一律留字符串。

    股票代码 (600519 / 00700) 恒是字符串标识, 服务端 schema 也是 string;
    按 JSON 字面量猜成 int 会被工具拒 (symbol must be non-empty string, got 600519)。
    其余值 (排序字段/枚举/布尔/嵌套 JSON) 仍按 JSON 解析。
    """
    s = v.strip()
    if not s:
        return v
    if s.isdigit() or (s.startswith('-') and s[1:].isdigit()):
        return s
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return v


def do_stock(args, cfg):
    """分发 + 渲染。返回退出码: 0 成功 / 1 动作失败 / 2 用法错"""
    action = args.action
    if not action:
        print(USAGE, file=sys.stderr)
        return 2
    fn = ACTIONS.get(action)
    if not fn:
        print(f'unknown action: {action}\n\n{USAGE}', file=sys.stderr)
        return 2

    try:
        out = fn(args, cfg)
    except _master.MasterMissing as e:
        print(f'error: {e}', file=sys.stderr)
        return 2
    except _srv.SrvError as e:
        print(f'error: {e}', file=sys.stderr)
        return 1
    except ValueError as e:
        print(f'error: {e}', file=sys.stderr)
        return 2

    # 载荷形状问题在渲染层拦 (raw HTML / 字符串化 data), 不让噪声进结果
    _render(out, args.format, action)
    return 0


# ---------- 渲染 ----------

def _render(out, fmt, action):
    fmt = _norm_fmt(fmt)
    # 未解析载荷只在 text/markdown 显式标注; json 保持原样 —— 程序消费方
    # 可能自己要那份 html, 但不该由我们替它决定丢弃。
    note = _unresolved(out)
    if fmt == 'json':
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    if note:
        print(f'⚠ {note}', file=sys.stderr)
    if fmt == 'markdown':
        _md(out, action)
    else:
        _text(out, action)


# ---- 原样透传类动作 ----
# report / diagram / excel 产出的是"可直接给人看的东西" (成稿 markdown /
# mermaid 源码 / 已落盘文件), 再包一层 JSON 或表格反而破坏可读性 —— 直接出。

def _passthrough(out, key):
    if isinstance(out, dict) and out.get(key):
        print(out[key])
    elif isinstance(out, dict):
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        print(out)


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
    if action == 'screen' and isinstance(out, dict):
        print(f"## 选股池 — 通过 {out.get('passed_count')} / 剔除 {out.get('failed_count')}"
              f", 门槛 {out.get('min_score_threshold')}\n")
        print('| 代码 | 名称 | 分 | 行业 | 位置 | 现价 | 突破 | 回踩 | 观察 | 止损 | 目标1 | 目标2 |')
        print('|---|---|---|---|---|---|---|---|---|---|---|---|')
        for p in out.get('passed') or []:
            t = p.get('technical') or {}
            print('| ' + _k(p.get('code'), p.get('name'), p.get('score'), p.get('industry'),
                            p.get('position_tag'), t.get('current_price'),
                            t.get('entry_breakout'), t.get('entry_pullback'),
                            t.get('entry_observing'), t.get('hard_stop'),
                            t.get('target_1'), t.get('target_2')) + ' |')
        failed = out.get('failed') or []
        if failed:
            print('\n### 剔除清单\n')
            print('| 代码 | 名称 | 闸门 | 原因 |')
            print('|---|---|---|---|')
            for f in failed:
                print('| ' + _k(f.get('code'), f.get('name'),
                                f.get('failed_gate'), f.get('error')) + ' |')
        return
    if action == 'tools' and isinstance(out, dict) and 'tools' in out:
        print(f'## stock MCP 工具 ({out.get("count", len(out["tools"]))} 个)\n')
        _table(['工具', '说明'], [(t['name'], t.get('desc')) for t in out['tools']])
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
        _table(['代码', '名称', '连板', '行业', '封单亿', '炸板', '首封'],
               [(r.get('code'), r.get('name'), r.get('连板'), r.get('行业'),
                 r.get('封单亿'), r.get('炸板次数'), r.get('首封'))
                for r in out.get('rows') or []])
        return
    print('```json')
    print(json.dumps(out, ensure_ascii=False, indent=1))
    print('```')


def _items_of(data, depth=6):
    """从 MCP 载荷里挖出条目列表 (广度优先下钻)。

    嵌套深度不固定: stock_news 是 data.items, stock_announcement 是 data.data.list,
    stock_capital_flow north 是 data.data.data.{hk2sh,sh2hk,...} (无列表)。
    只认显式的条目键 (items/list/rows) —— 其余 dict 键都往下钻一层。
    钻到底还没列表就返回 None 交给调用方标注, 不猜。
    """
    queue = [(data, 0)]
    while queue:
        node, d = queue.pop(0)
        if not isinstance(node, dict) or d > depth:
            continue
        for k in ('items', 'list', 'rows'):
            v = node.get(k)
            if isinstance(v, list):
                return v
        for v in node.values():
            if isinstance(v, dict):
                queue.append((v, d + 1))
    return None


def _text_sentiment(out):
    """消息面打分: 结论先行 (分数 + 倾向), 再列命中词。

    分数必须带符号显式印出 (+12 / -8), 不给绝对值 —— 消息面的关键信息是
    方向, 印成 12 会被读成"强利好"。
    """
    if not isinstance(out, dict):
        print(json.dumps(out, ensure_ascii=False))
        return
    s = out.get('score')
    s_txt = f'{s:+g}' if isinstance(s, (int, float)) else '未取得'
    tone = '利好' if isinstance(s, (int, float)) and s > 0 else (
        '利空' if isinstance(s, (int, float)) and s < 0 else '中性')
    print(f"消息面 {s_txt} ({tone}) — {out.get('news_count', 0)} 条, "
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


def _text_screen(out):
    """选股池 text: 通过标的给三档入场价与硬止损, 剔除的必须带原因。

    剔除清单不能省 —— 调用方要判断"为什么没看到某只票", 只给通过名单等于
    让 Agent 以为它不存在。
    """
    passed = out.get('passed') or []
    failed = out.get('failed') or []
    print(f"通过 {out.get('passed_count', len(passed))} / 剔除 {out.get('failed_count', len(failed))}"
          f"  门槛 {out.get('min_score_threshold')}  行业分散 {out.get('industry_dispersion')}")
    if passed:
        print('\n通过:')
        for p in passed:
            t = p.get('technical') or {}
            print(f"  [{p.get('code')}] {p.get('name')}  分{p.get('score')}  {p.get('industry') or ''}"
                  f"  {p.get('position_tag') or ''}")
            print(f"      现价{t.get('current_price')} 突破{t.get('entry_breakout')} "
                  f"回踩{t.get('entry_pullback')} 观察{t.get('entry_observing')} "
                  f"止损{t.get('hard_stop')} 目标{t.get('target_1')}/{t.get('target_2')}")
    if failed:
        print('\n剔除:')
        for f in failed:
            print(f"  [{f.get('code')}] {f.get('name')}  {f.get('error')}"
                  f"  (闸门: {f.get('failed_gate') or '—'})")


def _text_item(it):
    """单条记录: 有标题就先给标题再列关键字段; 否则按键值列全 (截断长值)。"""
    head = next((it[k] for k in ('title', 'name', 'report_date', '公告标题')
                 if it.get(k)), None)
    if head:
        print(f'- {head}')
    for k, v in it.items():
        if v in (None, '', 0) and k != 'report_date':
            continue                      # 缺数据不显形, 别让 0/空 冒充真实值
        if isinstance(v, (dict, list)):
            print(f'  {k}: {json.dumps(v, ensure_ascii=False)[:200]}')
        else:
            print(f'  {k}: {v}')


def _text_srv(out, note_only=False):
    """服务端载荷的 text 渲染: 结构化则列条目, 未解析只给提示。

    载荷固定是 {"ok", "source", "data"(可能是 dict / 字符串化 JSON / raw html)}。
    """
    if note_only:
        return
    if not isinstance(out, dict):
        print(json.dumps(out, ensure_ascii=False, indent=1))
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
    if isinstance(data, dict):
        items = _items_of(data)
        if items is not None:
            if not items:
                print('(无条目)')
                return
            for it in items:
                if not isinstance(it, dict):
                    print(str(it)[:300])
                    continue
                _text_item(it)
            return
        for k, v in data.items():
            if k in ('html', 'raw_html'):
                continue
            if isinstance(v, (dict, list)):
                print(f'{k}: {json.dumps(v, ensure_ascii=False)[:400]}')
            else:
                print(f'{k}: {v}')
        return
    print(json.dumps(data, ensure_ascii=False, indent=1)[:2000])


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
        for ch, v in inner.items():
            if not isinstance(v, dict):
                continue
            if v.get('status') == 3:
                print(f'⚠ {ch}: 数据源声明不可用 (status=3)'
                      + (f' — {v.get("unavailable")}' if v.get('unavailable') else ''))
                continue
            date = v.get('date2') or '—'
            net, quota = v.get('dayNetAmtIn'), v.get('dayAmtThreshold')
            # 东财北向接口在未推送真实值时会把 dayNetAmtIn 填成额度上限,
            # 沪股通返回 0 而深股通返回额度上限, 自相矛盾。净流入等于额度上限
            # 一律按"未取得"标注 —— 印成 4,200,000 万 (=4200亿) 会让调用方
            # 得出完全错误的结论, 这比报错更糟。
            if isinstance(net, (int, float)) and quota and net == quota:
                print(f'⚠ {ch}  日期{date}  净流入未取得 (接口回填额度上限 {quota:,.0f} 万, 非真实值)')
                continue
            net_txt = f'{net:,.0f} 万' if isinstance(net, (int, float)) else '未取得'
            print(f'{ch}  日期{date}  净流入 {net_txt}')
        return
    for k, v in data.items():
        if k == 'html':
            continue
        print(f'{k}: {json.dumps(v, ensure_ascii=False)[:300] if isinstance(v, (dict, list)) else v}')


def _text(out, action):
    if action in ('news', 'announcement', 'financials', 'mcp'):
        _text_srv(out, note_only=bool(_unresolved(out)))
        return
    if action == 'risk':
        _text_risk(out if isinstance(out, dict) else {})
        return
    if action == 'flow':
        _text_flow(out)
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