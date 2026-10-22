"""watch: 同一句检索反复跑, 只吐出"上次之后新出现的"

`feed --new-only` 只覆盖预设 RSS 源, search / rank 都没有跨轮状态 —— 想盯
"某关键词有什么新消息""某榜单新上了什么"就得自己 diff。这里把状态补上:
同一组参数算一个桶, 桶里记已见条目 (url 优先, 没 url 用标题), 下次只报差集。

状态: ~/.webtool/watch_state.json, 每桶最多记 --max-seen 条 (默认 500)。
退出码: 1 = 有新增 (方便挂定时任务), 0 = 没新增, 2 = 出错。

不直接发通知: 通知渠道是调用方的事 (minis-scheduled + android-notification),
webtool 只负责"变了没有、变了什么"。
"""

import hashlib
import json
import os
import sys
import time

WATCH_STATE_FILE = os.path.expanduser('~/.webtool/watch_state.json')


def _load(path=None):
    path = path or WATCH_STATE_FILE
    try:
        with open(path, encoding='utf-8') as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(state, path=None):
    path = path or WATCH_STATE_FILE
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(state, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _bucket_name(args, target):
    """同一组参数 → 同一个桶; --name 给显式名字时优先

    把影响结果的参数都算进去: 同一句词换个引擎/换个时间窗, 结果集本来就不同,
    混在一个桶里会把"换了参数导致的差异"误报成"新内容"。
    """
    if getattr(args, 'name', None):
        return args.name
    raw = '|'.join([getattr(args, 'kind', 'search') or 'search', target,
                    getattr(args, 'engine', '') or '',
                    getattr(args, 'preset', '') or '',
                    getattr(args, 'since', '') or '',
                    str(getattr(args, 'num', '') or '')])
    h = hashlib.sha1(raw.encode('utf-8')).hexdigest()[:10]
    return '%s-%s' % ((getattr(args, 'kind', 'search') or 'search'), h)


def _item_key(r):
    u = (r.get('url') or '').strip()
    if u:
        return 'u:' + u
    t = (r.get('title') or '').strip()
    if not t:
        return ''
    # 榜单里同一个标题可能来自不同平台, 不带源名会互相吞掉
    src = (r.get('source') or '').strip()
    return ('t:%s:%s' % (src, t)) if src else ('t:' + t)


def _label(r):
    t = (r.get('title') or r.get('url') or '(无标题)').strip()
    src = (r.get('source') or '').strip()
    return '[%s] %s' % (src, t) if src else t


def _fetch_items(args, target):
    """跑一次底层检索 → (items, err, via_note)

    复用 CLI 本身 (cli/_bridge): search / rank 的参数面都很宽 (引擎预设、时间
    过滤、黑名单…), 自己拼 args 就是在本仓里复制一份契约。
    """
    from webtool.cli._bridge import cli_json
    kind = getattr(args, 'kind', 'search') or 'search'
    nox = ['--no-proxy'] if getattr(args, 'no_proxy', False) else []
    if kind == 'rank':
        argv = ['rank'] + target.split() + ['-n', str(getattr(args, 'num', 20) or 20),
                                            '-f', 'json'] + nox
    else:
        argv = ['search', target, '-n', str(getattr(args, 'num', 20) or 20),
                '-f', 'json'] + nox
        if getattr(args, 'engine', None):
            argv += ['-e', args.engine]
        if getattr(args, 'preset', None):
            argv += ['--preset', args.preset]
        if getattr(args, 'since', None):
            argv += ['--since', args.since]
        if getattr(args, 'until', None):
            argv += ['--until', args.until]
    if getattr(args, 'no_cache', False):
        argv.append('--no-cache')
    ok, data = cli_json(argv)
    if not ok or not isinstance(data, dict):
        return [], str(data)[:300], ''
    items = [r for r in (data.get('results') or []) if isinstance(r, dict)]
    if not items:
        # rank 不带查询词时只给 sources_data (按源分组), 没有摊平的 results
        for src, rows in (data.get('sources_data') or {}).items():
            for r in (rows or []):
                if isinstance(r, dict):
                    items.append(dict(r, source=src))
    return items, '', kind


def do_watch(args, cfg):
    target = (getattr(args, 'target', None) or '').strip()
    state = _load()

    if getattr(args, 'list', False):
        return _print_buckets(state, args)

    if not target:
        print('用法: webtool watch "关键词" [-e bing] [-n 20]  |  '
              'webtool watch --kind rank zhihu weibo --name 热榜\n'
              '      webtool watch --list   看已有哪些桶', file=sys.stderr)
        return 2

    bucket = _bucket_name(args, target)

    if getattr(args, 'reset', False):
        state.pop(bucket, None)
        _save(state)
        print('watch: 已清空桶 %s, 下次运行会把当前结果全当新增' % bucket,
              file=sys.stderr)

    items, err, kind = _fetch_items(args, target)
    if err:
        print('watch: 检索失败 %s' % err, file=sys.stderr)
        return 2
    if not items:
        print('watch: 这次没取到任何条目 (检索本身空/被拦截), 不改状态',
              file=sys.stderr)
        return 2

    cur = state.get(bucket) or {}
    seen = list(cur.get('seen') or [])
    seen_set = set(seen)
    new = []
    for r in items:
        k = _item_key(r)
        if not k or k in seen_set:
            continue
        seen_set.add(k)
        new.append({'title': _label(r), 'url': (r.get('url') or '').strip(),
                    'key': k})

    max_seen = max(50, getattr(args, 'max_seen', 500) or 500)
    merged = ([x['key'] for x in new] + seen)[:max_seen]
    first = not cur
    state[bucket] = {'kind': kind, 'target': target,
                     'engine': getattr(args, 'engine', None),
                     'since': getattr(args, 'since', None),
                     'seen': merged, 'last_run': int(time.time()),
                     'last_new': len(new)}
    _save(state)

    out = {'bucket': bucket, 'kind': kind, 'target': target,
           'new': new, 'new_count': len(new), 'fetched': len(items),
           'seen_total': len(merged), 'first_run': first,
           'exit': 1 if new else 0}
    _render(out, args)
    return 1 if new else 0


def _render(out, args):
    fmt = getattr(args, 'format', None) or 'text'
    if fmt == 'json':
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    if fmt in ('markdown', 'md'):
        if not out['new']:
            print('**%s** — 无新增' % out['target'])
            return
        print('**%s** — 新增 %d 条' % (out['target'], out['new_count']))
        for i, it in enumerate(out['new'], 1):
            if it['url']:
                print('%d. [%s](%s)' % (i, it['title'], it['url']))
            else:
                print('%d. %s' % (i, it['title']))
        return
    if not out['new']:
        print('无新增 (%s, 本次取到 %d 条, 累计已见 %d 条)'
              % (out['target'], out['fetched'], out['seen_total']))
        return
    head = '新增 %d 条 (%s, 本次取到 %d 条)'
    print(head % (out['new_count'], out['target'], out['fetched']))
    if out['first_run']:
        print('  (首次运行, 这批算基线; 下次起才只报差集)', file=sys.stderr)
    for i, it in enumerate(out['new'], 1):
        print('[%d] %s' % (i, it['title']))
        if it['url']:
            print('    %s' % it['url'])


def _print_buckets(state, args):
    fmt = getattr(args, 'format', None) or 'text'
    rows = []
    for name, v in sorted(state.items(), key=lambda kv: -(kv[1].get('last_run') or 0)):
        rows.append({'bucket': name, 'kind': v.get('kind'),
                     'target': v.get('target'),
                     'seen': len(v.get('seen') or []),
                     'last_new': v.get('last_new'),
                     'last_run': time.strftime('%Y-%m-%d %H:%M',
                                               time.localtime(v.get('last_run') or 0))})
    if fmt == 'json':
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    if not rows:
        print('还没有任何 watch 桶')
        return 0
    print('%-26s %-6s %-8s %-6s %s' % ('桶', '类型', '已见', '上次新增', '上次运行'))
    for r in rows:
        print('%-26s %-6s %-8d %-6s %s'
              % (r['bucket'], r['kind'] or '', r['seen'],
                 r['last_new'] if r['last_new'] is not None else '-',
                 r['last_run']))
    print('\n共 %d 个桶 (状态: %s)' % (len(rows), WATCH_STATE_FILE))
    return 0
