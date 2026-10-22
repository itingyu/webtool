"""snapshot / diff: 页面存档与版本对比

`snapshot` 把一页的正文存进 `~/.webtool/snapshots/`, `diff` 拿两版比。两者合起来
解决 webtool 之前完全没有的维度: **这个页面变了没有**。

    webtool snapshot https://example.com/price          # 存第一版
    webtool snapshot https://example.com/price          # 第二天再存 (内容没变就不追加)
    webtool diff example.com-price --prev               # 比最近两版
    webtool diff NAME https://example.com/price         # 存档 vs 现在 (边看边存)

diff 的退出码是判据: 0 = 没有差异, 1 = 有差异 (配合 minis-scheduled / cron
就是"变了就通知我")。命令本身失败才走 2。

三方输入都支持 (快照名 / URL / 本地文件), 所以也能 `webtool diff a.txt b.txt`。
"""

import os
import sys

from webtool.cli._bridge import cli_json as _cli_json
from webtool.core import difftxt
from webtool.dao import snapshot as store
from webtool.render.diffrender import render_diff


def _looks_url(s):
    return '://' in s or s.startswith('//') or (
        '/' in s and '.' in s.split('/')[0] and ' ' not in s)


def _fetch_text(url, args):
    """抓一页正文 → (ok, 正文 或 错误)"""
    argv = ['fetch', url, '-f', 'json']
    if getattr(args, 'max_chars', 0):
        argv += ['--max-chars', str(args.max_chars)]
    if getattr(args, 'no_cache', False):
        argv.append('--no-cache')
    if getattr(args, 'no_proxy', False):
        argv.append('--no-proxy')
    ok, data = _cli_json(argv)
    if not ok or not isinstance(data, dict):
        return False, str(data)[:300]
    if data.get('error'):
        return False, data['error']
    return True, data.get('content') or ''


def _resolve(spec, args):
    """快照名 / URL / 本地文件 → {label, content}"""
    if os.path.isfile(spec) and not _looks_url(spec):
        with open(spec, encoding='utf-8', errors='replace') as f:
            return {'label': spec, 'content': f.read()}
    snap = store.load(spec, getattr(args, 'version', None))
    if snap:
        return {'label': '%s (快照 v, %s)' % (snap['name'], snap['url'] or '-'),
                'content': snap['content']}
    if _looks_url(spec):
        ok, content = _fetch_text(spec, args)
        if not ok:
            raise ValueError('抓取 %s 失败: %s' % (spec, content))
        return {'label': spec, 'content': content}
    raise ValueError('找不到快照 %r (webtool snapshot --list 看已有的), '
                     '也不是能抓的 URL 或存在的文件' % spec)


def do_snapshot(args, cfg):
    """存一版 / 列清单 / 看某一版 / 删"""
    if getattr(args, 'list', False):
        rows = store.listing()
        if args.format == 'json':
            import json
            print(json.dumps(rows, ensure_ascii=False, indent=1))
            return 0
        if not rows:
            print('还没有快照 (webtool snapshot <URL> 存一版)')
            return 0
        import time as _t
        print('%-40s %6s %8s  %s' % ('名字', '版数', '字数', '最近存档'))
        for r in rows:
            ts = _t.strftime('%Y-%m-%d %H:%M',
                             _t.localtime(r['latest_ts'])) if r['latest_ts'] else '-'
            print('%-40s %6d %8d  %s' % (r['name'][:40], r['versions'],
                                         r['latest_chars'] or 0, ts))
        return 0

    if getattr(args, 'rm', None):
        ok = store.remove(args.rm)
        print('已删快照 %s' % args.rm if ok else '没有快照 %s' % args.rm)
        return 0 if ok else 1

    if getattr(args, 'history', None):
        rows = store.versions(args.history)
        if not rows:
            print('没有快照 %s' % args.history, file=sys.stderr)
            return 1
        if args.format == 'json':
            import json
            print(json.dumps(rows, ensure_ascii=False, indent=1))
            return 0
        import time as _t
        for r in rows:
            ts = _t.strftime('%Y-%m-%d %H:%M', _t.localtime(r['ts']))
            print('v%-3d %s  %6d 字  %s' % (r['n'], ts, r['chars'],
                                            r['title'][:50]))
        return 0

    url = (args.url or '').strip()
    if not url:
        print('用法: webtool snapshot <URL> [--name 名字]  |  '
              'webtool snapshot --list  |  --history 名字  |  --rm 名字',
              file=sys.stderr)
        return 2
    if not _looks_url(url):
        print('snapshot 需要一个 URL (拿到的是 %r)' % url, file=sys.stderr)
        return 2

    ok, content = _fetch_text(url, args)
    if not ok:
        print('snapshot: 抓取失败: %s' % content, file=sys.stderr)
        return 1
    if not (content or '').strip():
        print('snapshot: %s 没抓到正文 (可能需 JS 渲染; 试 fetch --raw 看原始 HTML)'
              % url, file=sys.stderr)
        return 1

    info = store.save(url, content, title=None, name=getattr(args, 'name', None))
    if args.format == 'json':
        import json
        print(json.dumps(info, ensure_ascii=False, indent=1))
    elif info['changed']:
        print('已存快照 %s  v%d  %d 字' % (info['name'], info['version'],
                                          info['chars']))
    else:
        print('快照 %s 无变化 (仍是 v%d, %d 字)' % (info['name'], info['version'],
                                                 info['chars']))
    return 0


def do_diff(args, cfg):
    """两版对比; 退出码 0=无差异 1=有差异 2=出错"""
    a, b = (getattr(args, 'left', None) or '').strip(), \
           (getattr(args, 'right', None) or '').strip()

    # 单参数: 比同名快照的最近两版 ("这页跟上次比变了什么")
    if a and not b:
        rows = store.versions(a)
        if not rows:
            if _looks_url(a) or os.path.isfile(a):
                print('diff: 给两份才能比 (%r 不是快照名); 例: '
                      'webtool diff %s 另一版' % (a, a), file=sys.stderr)
            else:
                print('diff: 没有快照 %r (webtool snapshot --list 看已有的)'
                      % a, file=sys.stderr)
            return 2
        if len(rows) < 2:
            print('diff: 快照 %s 只有 1 版, 没法比 —— 再 snapshot 一次同一个 URL, '
                  '或给两个参数直接指定两侧' % a, file=sys.stderr)
            return 2
        old = store.load(a, -2)
        new = store.load(a, -1)
        la = '%s v%d' % (a, rows[-2]['n'])
        lb = '%s v%d' % (a, rows[-1]['n'])
    elif a and b:
        try:
            ra, rb = _resolve(a, args), _resolve(b, args)
        except ValueError as e:
            print('diff: %s' % e, file=sys.stderr)
            return 2
        old, new = ra, rb
        la = ra['label'] + (' @%s' % getattr(args, 'left_at', '') if
                            getattr(args, 'left_at', None) else '')
        lb = rb['label']
    else:
        print('用法: webtool diff <旧> <新>   (参数可为快照名 / URL / 本地文件)\n'
              '      webtool diff <快照名>      (比该快照最近两版)',
              file=sys.stderr)
        return 2

    old_c, new_c = old['content'], new['content']
    if getattr(args, 'no_meta', False):
        # 跨 URL 对比时 front matter 里的 url/hostname 必然不同, 全是噪声
        from webtool.core.text import strip_front_matter
        old_c, new_c = strip_front_matter(old_c), strip_front_matter(new_c)
    res = difftxt.compare(old_c, new_c,
                          context=getattr(args, 'context', 3),
                          ignore_ws=getattr(args, 'ignore_ws', False))
    print(render_diff(res, args.format or 'text', la, lb,
                      max_lines=getattr(args, 'max_lines', 400)))
    return 0 if not res['hunks'] else 1
