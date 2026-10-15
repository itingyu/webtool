"""stock text 视图: 裸调用/生态库/服务/原始字段类 (data 与 srv 族)"""
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



from webtool.stock.command._common import _items_of
from webtool.stock.command._common import _j


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
    """动作载荷的 text 渲染: 结构化则列条目, 未解析只给提示。

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

def _text_raw(out, action=''):
    """原始 API 载荷: 摘要 + 键结构, 不倾倒原始 JSON。

    数据源层返回的数据量动辄几十 KB (股东研究一家 34KB), 全量印出来
    既刷屏又淹掉重点。这里只给: 状态 / 来源 / 各键的条目数与首条要点。
    要全量用 -f json。
    """
    if not isinstance(out, dict):
        print(json.dumps(out, ensure_ascii=False)[:2000])
        return
    if action == 'api-list':
        print(f"数据源层共 {out.get('count')} 个方法 "
              f"(按{(out.get('by') or 'source')}):")
        if out.get('by') == 'function':
            for label, c in (out.get('categories') or {}).items():
                n = len(c['primary']) + len(c['fallback'])
                print(f"\n{label} ({n})  {c['desc']}")
                print(f"  首选: {' '.join(c['primary'])}")
                if c['fallback']:
                    print(f"  备选: {' '.join(c['fallback'])}")
            return
        for src, ms in (out.get('methods') or {}).items():
            print(f"  {src}({len(ms)}): {' '.join(ms[:6])}{' …' if len(ms) > 6 else ''}")
        return
    if action == 'api-search':
        if out.get('by') == 'category':
            print(f'"{out["keyword"]}" 命中 {out["count"]} 个功能类:')
            for label, c in (out.get('categories') or {}).items():
                print(f"\n{label}  {c['desc']}")
                print(f"  首选: {' '.join(c['primary'])}")
                if c['fallback']:
                    print(f"  备选: {' '.join(c['fallback'])}")
            return
        print(f'"{out["keyword"]}" 命中 {out["count"]} 个方法:')
        for m in (out.get('methods') or []):
            cat = f"[{m['category']}] " if m.get('category') else ''
            print(f"  {cat}{m['method']}{m['sig']}")
            if m.get('doc'):
                print(f"      {m['doc'][:90]}")
        return
    print(f"ok={out.get('ok')}" + (f"  源={out['source']}" if out.get('source') else '')
          + (f"  {out['raw_size']} 字符" if out.get('raw_size') else ''))
    if out.get('error'):
        print(f'  错误: {out["error"]}')
        return
    data = out.get('data')
    if not isinstance(data, dict):
        print(json.dumps(data, ensure_ascii=False)[:1000])
        return
    for k, v in data.items():
        if isinstance(v, list):
            if not v:
                print(f'  {k}: (空)')
            else:
                first = v[0]
                hint = (', '.join(list(first)[:5]) + '…'
                        if isinstance(first, dict) else str(first)[:60])
                print(f'  {k}: {len(v)} 条  首条字段[{hint}]')
        elif isinstance(v, dict):
            print(f'  {k}: {{}} {len(v)} 键 {list(v)[:5]}')
        elif v not in (None, '', []):
            print(f'  {k}: {str(v)[:80]}')

def _text_raw_tail(out):
    """给摘要渲染收尾: 剩下的键用条数说明 (不重复已展示的大块)"""
    data = out.get('data') or {}
    shown = {'gdrs', 'sdgd', 'jgcc', 'sdltgd'}
    rest = [k for k in data if k not in shown]
    if rest:
        parts = [f'{k}({len(data[k])})' if isinstance(data[k], (list, dict)) else k
                 for k in rest]
        print(f"\n其余字段: {', '.join(parts)}  (用 -f json 看全量)")

def _text_eco(out):
    """生态库返回: 形状摘要 + 前几行预览 (DataFrame 转 dict 前 N 行)。

    akshare 很多接口返回几千行 (全市场快照 5923×23), 直接印会刷屏 —— 默认只给
    形状与预览, --full 才给全量。
    """
    if not isinstance(out, dict):
        print(_j(out, 2000))
        return
    if out.get('ok') is False:
        print(f"error: {out.get('error')}")
        return
    print(f"[{out.get('lib')}.{out.get('name')}] {out.get('kind')}"
          f" shape={out.get('shape')}  {out.get('took_s')}s"
          + (f"  列={out['columns']}" if out.get('columns') else ''))
    for i, row in enumerate(out.get('preview') or []):
        print(f'  {i + 1}. {_j(row)}')
    if out.get('truncated'):
        print(f"  …共 {out.get('shape')} 行, --full 取全量")

def _text_eco_list(out):
    if not isinstance(out, dict):
        print(json.dumps(out, ensure_ascii=False))
        return
    lib, n = out.get('library'), out.get('count')
    if 'signature' in out:
        print(f"{lib}.{out.get('name')}  ({out.get('lib')} 共 {n} 个接口)")
        print(f"  签名: {out['signature']}")
        doc = (out.get('doc') or '').strip().splitlines()
        for line in doc[:6]:
            print(f'  {line}')
        return
    print(f"{lib} 共 {n} 个接口")
    for f in out.get('funcs') or []:
        print(f'  {f}')
    if out.get('truncated'):
        print('  …用 --limit 调整, 或 eco-search <关键词> 精确找')

def _text_eco_search(out):
    if not isinstance(out, dict):
        print(json.dumps(out, ensure_ascii=False))
        return
    if not out.get('libraries'):
        print(f"无匹配: {out.get('keyword')}")
        return
    print(f"\"{out.get('keyword')}\" 匹配 {out.get('count')} 个:")
    for lib, names in out['libraries'].items():
        print(f"  {lib} ({len(names)}): {' '.join(names[:8])}{' …' if len(names) > 8 else ''}")

