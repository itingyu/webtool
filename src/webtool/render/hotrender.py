"""rank / hot 渲染: 按源分节输出 (json / text / markdown), -q 时另有跨源重排清单"""
import json
import sys


def strip_urls(out):
    """--no-url: 抹掉每条目的 url, 让输出只剩标题/摘要

    只改"出门的副本", 缓存与增量状态都已在渲染前用完 url (feed --new-only
    靠 url 去重), 到这里再删不影响下次抓取。
    三种格式一次生效, 不用各写一遍: json 里没有 url 字段; markdown 的
    [标题](链接) 退化成纯标题; text 少的正是那行链接 (见本文件各处
    `if r.get('url')`)。out['no_url'] 留个标记, 消费者才知道链接是"被要求
    去掉"而不是"源里就没有"。
    """
    for key in ('results', 'sources_data'):
        v = out.get(key)
        if isinstance(v, dict):
            for items in v.values():
                _drop_url(items)
        elif isinstance(v, list):
            _drop_url(v)
    out['no_url'] = True
    return out


def _drop_url(items):
    for r in items or []:
        if isinstance(r, dict):
            r.pop('url', None)


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
                      + (f" sem:{r['_sem']}" if r.get('_sem') is not None else '')
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
                      + (f"  sem={r['_sem']}" if r.get('_sem') is not None else ''))
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


def render_keyed_list(out, fmt, kind='admin', title='清单', desc_fields=('desc',)):
    """key-value 型清单的统一渲染 (site list / plugins list 等)

    与 render_feed_list 的区别: 那是 feed 专属列 (name/origin/default),
    这里按行里实际出现的键自动定列, 一份实现覆盖各种清单。
    """
    rows = out.get('results') or []
    if fmt == 'json':
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    # 列序: title/描述字段在前, 其余按首次出现顺序
    lead = [c for c in ('site', 'name', 'key', 'title') if any(c in r for r in rows)]
    descs = [c for c in desc_fields if any(c in r for r in rows)]
    cols = lead + descs
    rest = []
    seen = set(cols)
    for r in rows:
        for k in r:
            if k not in seen:
                seen.add(k)
                rest.append(k)
    cols = cols + rest
    if fmt == 'markdown':
        print(f'## {title} ({len(rows)} 项)\n')
        print('| ' + ' | '.join(cols) + ' |')
        print('|' + '|'.join(['---'] * len(cols)) + '|')
        for r in rows:
            print('| ' + ' | '.join(str(r.get(c, '')).replace('|', '\\|')
                                     for c in cols) + ' |')
        return
    # text
    print(f'{title} ({len(rows)} 项):\n')
    for r in rows:
        label = str(r.get(lead[0], '')) if lead else ''
        desc = str(r.get(descs[0], '')) if descs else ''
        extra = ' '.join(f'{k}={r[k]}' for k in rest if r.get(k))
        print(f'  {label:16s} {desc} {extra}'.rstrip())


def render_feed_list(out, fmt):
    """feed 清单输出 (webtool feed list -f <fmt>)

    清单本质是表格数据, 所以四种格式都真正生效, 不像别的清单那样 -f 摆设。
    """
    rows = out.get('results') or []
    if fmt == 'json':
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    if fmt == 'markdown':
        print(f"## feed 订阅源 ({out.get('seed_count')} 预设 + "
              f"{out.get('user_count')} 自定义)\n")
        print('| name | origin | default | desc | url |')
        print('|---|---|:-:|---|---|')
        for r in rows:
            print(f"| {r['name']} | {r['origin']} | "
                  f"{'✓' if r['default'] else ''} | {r['desc']} | {r['url']} |")
        return
    # text
    print(f"webtool feed 订阅源 ({out.get('seed_count')} 预设 + "
          f"{out.get('user_count')} 自定义):\n")
    for r in rows:
        star = ' *' if r['default'] else ''
        tag = f" ({r['origin']})" if r['origin'] == 'custom' else ''
        print(f"  {r['name']:14s} {r['desc']}{star}{tag} {r['url']}")


# 兼容旧别名 (hot 命令若仍被调用)
def render_hot(out, fmt):
    render_rank(out, fmt, ['无过滤动作 (0 剔除)'])
