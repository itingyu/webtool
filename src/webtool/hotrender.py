# -*- coding: utf-8 -*-
"""rank / hot 渲染: 按源分节输出 (json / text / markdown), -q 时另有跨源重排清单"""
import json
import sys


def _meta_of(r):
    meta = []
    for k in ('hot', 'hot_value', 'score', 'stars', 'answers', 'comments', 'lang', 'sub'):
        v = r.get(k)
        if v not in (None, ''):
            meta.append(f'{k}:{v}')
    return meta


def _print_errors_md(errors):
    for nm, e in (errors or {}).items():
        print(f"\n### ⚠ {nm}\n\n> {e}")


def render_rank(out, fmt, filters):
    if fmt == 'json':
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    data = out.get('sources_data') or {}
    errors = out.get('errors') or {}
    if fmt == 'markdown':
        print(f"## 榜单聚合 ({len(data)}/{len(out['sources'])} 源, "
              f"{out['total']} 条, {out['took_ms']}ms)")
        if out.get('query'):
            print(f"\n筛选: `{out['query']}`"
                  + (f", 阈值 {out.get('threshold')}" if out.get('threshold') else '')
                  + (f", 剔除 {out['filtered_out']} 条" if out.get('filtered_out') else ''))
        if out.get('results'):
            mode = '跨源重排' if out.get('threshold') else '跨源清单 (原序)'
            print(f"\n### {mode} ({len(out['results'])})\n")
            for r in out['results'][:30]:
                url = r.get('url') or ''
                t = r.get('title') or ''
                link = f'[{t}]({url})' if url else t
                print(f"{r['rank']}. {link} — *{r['source']}"
                      + (f" sem:{r['sem_score']}" if r.get('sem_score') is not None else '')
                      + '*')
        for nm in out['sources']:
            items = data.get(nm)
            if not items:
                continue
            print(f"\n### {nm} ({len(items)})\n")
            for i, r in enumerate(items, 1):
                url = r.get('url') or ''
                t = r.get('title') or ''
                link = f'[{t}]({url})' if url else t
                meta = _meta_of(r)
                print(f"{i}. {link}" + (f" — *{' '.join(meta)}*" if meta else ''))
        _print_errors_md(errors)
        if filters:
            print(f"\n---\n**过滤统计**: {'; '.join(filters)}")
    else:  # text
        if out.get('results'):
            print('== 重排 (跨源) ==' if out.get('threshold') else '== 清单 (原序) ==')
            for r in out['results']:
                print(f"[{r['rank']}] ({r['source']}) {r.get('title') or ''}"
                      + (f"  sem={r['sem_score']}" if r.get('sem_score') is not None else ''))
                if r.get('url'):
                    print(f"    {r['url']}")
            print()
        for nm in out['sources']:
            items = data.get(nm)
            if not items:
                continue
            print(f"== {nm} ==")
            for i, r in enumerate(items, 1):
                print(f"[{i}] {r.get('title') or ''}")
                if r.get('url'):
                    print(f"    {r['url']}")
            print()
        for nm, e in errors.items():
            print(f"== {nm} == FAILED: {e}", file=sys.stderr)
        if filters:
            print('— ' + '; '.join(filters), file=sys.stderr)


# 兼容旧别名 (hot 命令若仍被调用)
def render_hot(out, fmt):
    render_rank(out, fmt, ['无过滤动作 (0 剔除)'])
