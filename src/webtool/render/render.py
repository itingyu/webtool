"""统一输出格式化: search/site/fetch 共用

三格式对齐 (无论选哪种都能拿到同样信息):
- json:  机器可读, 全字段
- text:  人类/Agent 易读纯文本, 元信息以 [key: value] 行内嵌
- markdown: 结构化 md, 表格+清单, 适合直接投喂 LLM

过滤统计 (filters_applied) 只进 json 供程序化消费; 文本/markdown 不回显 ——
用户要的是结果本身, "广告过滤 3 条" 这类内部计数只是噪音。
"""
import json
import sys


def _fmt_filters(out):
    """过滤说明行 -> 单行字符串"""
    parts = []
    # 只报"少了东西"的过滤 —— 用户可能追问"csdn 怎么没了", 数量异常也是
    # 排查线索。去重与翻页补拉不报: 那是内部实现细节, 用户无从据此行动。
    if out.get('ad_filtered'):
        parts.append(f"广告过滤 {out['ad_filtered']} 条")
    if out.get('blocked_by_blocklist'):
        parts.append(f"黑名单剔除 {out['blocked_by_blocklist']} 条")
    if out.get('date_filtered'):
        parts.append(f"时间过滤 {out['date_filtered']} 条")
    return parts



def render(out, fmt, kind):
    """kind: 'search' | 'site' | 'fetch'; fmt: 'json' | 'text' | 'markdown'"""
    # 无过滤时留空数组 —— 不编造 "无过滤动作 (0 剔除)" 这种占位文案
    out['filters_applied'] = _fmt_filters(out)
    if fmt == 'json':
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    if kind == 'fetch':
        _render_fetch(out, fmt)
    else:
        _render_search(out, fmt)


# search / site

def _render_search(out, fmt):
    results = out.get('results') or []
    if fmt == 'markdown':
        print(f"## 搜索: {out['query']}")
        if out.get('site'):
            print(f"\n站点: `{out['site']}` (站内搜索)")
        meta = [f"结果 {out['total']} 条", f"{out['took_ms']}ms"]
        if out.get('sorted_by'):
            meta.append(f"排序: {out['sorted_by']}")
        if out.get('source'):
            meta.append(f"缓存: {out['source']}")
        if out.get('engine_channels'):
            meta.append('通道: ' + ', '.join(f"{k}={v}"
                                             for k, v in out['engine_channels'].items()))
        print(f"\n> {' | '.join(meta)}")
        for r in results:
            w = f" `w={r['weight']:.2f}`" if r.get('weight') is not None else ''
            # 交叉验证数不再单列: 引擎名已列出几个就是几个, ✕N 纯属重复
            eng = ','.join(r['engines']) if r.get('engines') else r.get('engine', '')
            print(f"\n### {r['rank']}. [{r['title']}]({r['url']})")
            sub = []
            if eng: sub.append(f"引擎: {eng}{w}")
            if r.get('is_ad'): sub.append('**广告**')
            if sub: print(f"\n*{'; '.join(sub)}*")
            if r.get('snippet'):
                print(f"\n{r['snippet'][:200]}")
    else:  # text
        if not results:
            where = f'站点 {out["site"]} ' if out.get('site') else ''
            print(f'{where}没有搜索结果 (共 0 条) —— 换个关键词, 或 `webtool site list` 看站点状态')
            return
        for r in results:
            eng = ','.join(r['engines']) if r.get('engines') else r.get('engine', '')
            line = f"[{r['rank']}] {r['title']}"
            flags = []
            if eng: flags.append(eng)
            if r.get('weight') is not None: flags.append(f"w={r['weight']:.2f}")
            if r.get('is_ad'): flags.append('AD')
            if r.get('fallback'): flags.append('fallback')
            if flags: line += f"  ({';'.join(flags)})"
            print(line)
            print(f"    {r['url']}")
            if r.get('snippet'):
                print(f"    {r['snippet'][:150]}")
        if out.get('degraded'):
            for d in out['degraded']:
                print('note: ' + d, file=sys.stderr)
        if out.get('errors'):
            print('errors: ' + json.dumps(out['errors'], ensure_ascii=False), file=sys.stderr)


# fetch

def _render_fetch(out, fmt):
    items = out['results'] if isinstance(out.get('results'), list) else [out]
    if fmt == 'markdown':
        for r in items:
            if r.get('error'):
                print(f"## ⚠ 抓取失败: {r['url']}\n\n> {r['error']}\n")
                continue
            title = (r.get('metadata') or {}).get('title') or r['url']
            print(f"## {title}\n")
            meta = [f"来源: {r['url']}", f"{r['chars']} 字符"]
            if r.get('took_ms') is not None: meta.append(f"{r['took_ms']}ms")
            if r.get('via'): meta.append(f"via {r['via']}")
            if r.get('cache'): meta.append(f"缓存: {r['cache']}")
            print(f"> {' | '.join(meta)}\n")
            print((r.get('content') or '').rstrip())
            print()
    else:  # text
        for r in items:
            if r.get('error'):
                print(f"ERROR {r['url']}: {r['error']}", file=sys.stderr)
                continue
            meta = []
            if r.get('via'): meta.append(f"via={r['via']}")
            if r.get('took_ms') is not None: meta.append(f"{r['took_ms']}ms")
            if r.get('chars') is not None: meta.append(f"{r['chars']}ch")
            if r.get('cache'): meta.append(f"cache={r['cache']}")
            head = f"[{r['url']}]" + (f" ({';'.join(meta)})" if meta else '')
            print(head)
            print((r.get('content') or '').rstrip())
            print()
        if out.get('errors'):
            print('errors: ' + json.dumps(out['errors'], ensure_ascii=False), file=sys.stderr)
