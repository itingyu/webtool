"""统一输出格式化: search/site/fetch 共用

三格式对齐 (无论选哪种都能拿到同样信息):
- json:  机器可读, 全字段
- text:  人类/Agent 易读纯文本, 元信息以 [key: value] 行内嵌
- markdown: 结构化 md, 表格+清单, 适合直接投喂 LLM

过滤统计 (filters_applied) 三格式都输出, 不丢信息。
"""
import json
import sys


def _fmt_filters(out):
    """过滤说明行 -> 单行字符串"""
    parts = []
    if out.get('ad_filtered'):
        parts.append(f"广告过滤 {out['ad_filtered']} 条(--keep-ad 保留)")
    if out.get('blocked_by_blocklist'):
        parts.append(f"黑名单剔除 {out['blocked_by_blocklist']} 条(--no-blocklist 关闭)")
    if out.get('topup', {}).get('fetched'):
        parts.append(f"翻页补拉 {out['topup']['fetched']} 条(过滤后不足 {out.get('requested', '?')})")
    if out.get('dedup_removed'):
        parts.append(f"跨引擎去重合并 {out['dedup_removed']} 条(--no-dedupe 关闭)")
    return parts


def _fmt_degraded(out):
    """引擎降级说明 -> 单行字符串 (降级是静默的, 必须显式回显)"""
    dg = out.get('degraded')
    return '引擎降级: ' + '; '.join(dg) if dg else None


def render(out, fmt, kind):
    """kind: 'search' | 'site' | 'fetch'; fmt: 'json' | 'text' | 'markdown'"""
    filters = _fmt_filters(out)
    # 无过滤动作时也回显一行, 保持过滤统计在三格式里始终在场 (0 可查证)
    if not filters:
        filters = ['无过滤动作 (0 剔除)']
    out['filters_applied'] = filters
    degraded = _fmt_degraded(out)
    if fmt == 'json':
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    if kind == 'fetch':
        _render_fetch(out, fmt, filters)
    else:
        _render_search(out, fmt, filters, degraded)


# ---------- search / site ----------

def _render_search(out, fmt, filters, degraded=None):
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
        if degraded:
            print(f"\n⚠ {degraded} (覆盖范围可能小于全 Web 搜索)")
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
        if filters:
            print(f"\n---\n**过滤统计**: {'; '.join(filters)}")
        if out.get('errors'):
            print(f"\n⚠ 引擎错误: {json.dumps(out['errors'], ensure_ascii=False)}")
        if out.get('quality_hint'):
            print(f"\n> 💡 {out['quality_hint']}")
    else:  # text
        if degraded:
            print(f'⚠ {degraded}', file=sys.stderr)
        for r in results:
            eng = ','.join(r['engines']) if r.get('engines') else r.get('engine', '')
            line = f"[{r['rank']}] {r['title']}"
            flags = []
            if eng: flags.append(eng)
            if r.get('weight') is not None: flags.append(f"w={r['weight']:.2f}")
            if r.get('is_ad'): flags.append('AD')
            if flags: line += f"  ({';'.join(flags)})"
            print(line)
            print(f"    {r['url']}")
            if r.get('snippet'):
                print(f"    {r['snippet'][:150]}")
        if filters:
            print('— ' + '; '.join(filters))
        if out.get('errors'):
            print('errors: ' + json.dumps(out['errors'], ensure_ascii=False), file=sys.stderr)
        if out.get('quality_hint'):
            print('hint: ' + out['quality_hint'], file=sys.stderr)


# ---------- fetch ----------

def _render_fetch(out, fmt, filters):
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
        if filters:
            print(f"---\n**过滤统计**: {'; '.join(filters)}")
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
        if filters:
            print('— ' + '; '.join(filters))
        if out.get('errors'):
            print('errors: ' + json.dumps(out['errors'], ensure_ascii=False), file=sys.stderr)
