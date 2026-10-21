"""cli 命令: 拦截日志

只记判定过的事件 (blocked / bypass / passed / failed), 正常请求不记 —— 否则
日志会被淹没。数据源是 ~/.webtool/intercept.log (JSONL), 跟着 WEBTOOL_DIR 走。
"""
import json
import os

import typer

from webtool.net import intercept as _ic
from webtool.cli.app import app

_COLORS = {'blocked': 'red', 'bypass': 'yellow', 'passed': 'green',
           'failed': 'red'}


def _read(limit=20, action=None):
    p = _ic.log_path()
    try:
        with open(p, encoding='utf-8') as f:
            rows = []
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if action and rec.get('action') != action:
                    continue
                rows.append(rec)
    except OSError:
        return []
    if limit and limit > 0:
        rows = rows[-limit:]
    return rows


@app.command('intercept-log')
def intercept_log_cmd(
        limit: int = typer.Option(20, '-n', '--limit',
                                  help='最近 N 条; 0 = 全部'),
        action: str = typer.Option(None, '--action',
                                   help='只看某类: blocked / bypass / passed / failed'),
        as_json: bool = typer.Option(False, '--json', help='原样输出 JSONL'),
        clear: bool = typer.Option(False, '--clear', help='清空日志 (含轮转文件)'),
        show_path: bool = typer.Option(False, '--path', help='只打印日志路径')):
    """拦截日志: 谁在什么时候被哪个插件拦了、绕没绕过去"""
    p = _ic.log_path()
    if show_path:
        print(p)
        return 0
    if clear:
        for f in (p, p + '.1'):
            try:
                os.remove(f)
            except OSError:
                pass
        print('已清空: %s' % p)
        return 0
    rows = _read(limit, action)
    if not rows:
        print('（暂无拦截记录）' if not os.path.exists(p)
              else '（没有匹配的记录）')
        print('日志: %s' % p)
        return 0
    if as_json:
        for r in rows:
            print(json.dumps(r, ensure_ascii=False))
        return 0
    for r in rows:
        act = '%-7s' % (r.get('action') or '-')
        act = typer.style(act, fg=_COLORS.get(r.get('action')))
        print('%s %s %-22s %-12s %-22s %s' % (
            (r.get('ts') or '')[5:19].replace('T', ' '),
            act,
            (r.get('site') or '-')[:22],
            (r.get('by') or '-')[:12],
            (r.get('sign') or r.get('detail') or '-')[:22],
            (r.get('url') or '')[:80]))
    print('\n共 %d 条 · %s' % (len(rows), p))
    return 0
