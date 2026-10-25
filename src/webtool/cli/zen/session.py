"""zen --agent 的命名会话: 历史落盘, 可恢复

一条会话 = 一个 json 文件 (`~/.webtool/zen_sessions/<名>.json`), 存 messages 全量
(assistant 的 tool_calls 与 role:tool 的结果都在内) + 模型/工作空间/步数。

**每轮跑完就存**, 不是跑完才存: agent 循环中途断网/超时的话, 已经问过的几轮还在,
下次 `--continue` 能接着聊; 只在收尾写的话, 一次 429 就白跑十几轮。

名字不许带路径分隔符 —— 会话名是文件名而不是目录树, 想按目录分用 `--workspace`。
"""

import json
import re
import time

from webtool.core.config_data import USER_DIR
from webtool.core.errors import UsageError
from webtool.core.logging import get_logger

logger = get_logger(__name__)

SESSION_DIR = 'zen_sessions'
_BAD_NAME = re.compile(r'[^A-Za-z0-9._-]')
MAX_SESSIONS_LISTED = 50


def _dir():
    return USER_DIR / SESSION_DIR


def _check_name(name):
    name = (name or '').strip()
    if not name:
        raise UsageError('会话名不能为空')
    if _BAD_NAME.search(name) or name.startswith('.'):
        raise UsageError('会话名只认字母数字 . _ - (别的字符会被当路径分隔符)')
    return name


def path_of(name):
    """会话名 → 文件路径 (不校验存在)"""
    return _dir() / ('%s.json' % _check_name(name))


def load(name):
    """读一条会话; 不存在返回 None (调用方当"新建"处理, 不是错)"""
    p = path_of(name)
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        logger.warning('session | %s 读坏(%s), 当作新会话', p, e)
        return None
    if not isinstance(data, dict) or not isinstance(data.get('messages'), list):
        logger.warning('session | %s 结构不认识, 当作新会话', p)
        return None
    data.setdefault('name', name)
    return data


def save(name, messages, model=None, workspace=None):
    """原子写 (jsonfmt.write 内部走临时文件+replace), 跑完一轮就调一次

    `steps` 由 messages 里 assistant 条数算出来, 不另设参数 —— 两个来源必然
    对不上 (恢复旧会话时"这次跑了几轮"和"这条会话累计几轮"不是一回事)。
    """
    from webtool.core import jsonfmt
    p = path_of(name)
    old = load(name) or {}
    steps = sum(1 for m in messages if isinstance(m, dict) and m.get('role') == 'assistant')
    data = {
        'name': name,
        'model': model,
        'workspace': str(getattr(workspace, 'root', workspace) or '') or None,
        'steps': steps,
        'created': old.get('created') or time.time(),
        'updated': time.time(),
        'messages': messages,
    }
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        jsonfmt.write(p, data)
    except OSError as e:
        # 会话存不上不该让整轮对话失败: 结果已经拿到了, 只是下次接不上
        logger.warning('session | 写 %s 失败: %s', p, e)
        return False
    logger.debug('session | 存 %s (%d 条消息, %d 轮)', p, len(messages), steps)
    return True


def remove(name):
    """删一条会话; 返回删了几条 (0 = 本来就没有)"""
    p = path_of(name)
    try:
        p.unlink()
    except FileNotFoundError:
        return 0
    except OSError as e:
        logger.warning('session | 删 %s 失败: %s', p, e)
        return 0
    return 1


def recent():
    """按最近修改排序的会话摘要 [{name, updated, steps, model, workspace, messages}]"""
    d = _dir()
    try:
        files = [f for f in d.glob('*.json') if f.is_file()]
    except OSError:
        return []
    rows = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            rows.append({'name': f.stem, 'updated': f.stat().st_mtime,
                         'broken': True})
            continue
        if not isinstance(data, dict):
            continue
        rows.append({'name': data.get('name') or f.stem,
                     'updated': data.get('updated') or f.stat().st_mtime,
                     'steps': data.get('steps') or 0,
                     'model': data.get('model'),
                     'workspace': data.get('workspace'),
                     'messages': len(data.get('messages') or [])})
    rows.sort(key=lambda r: r['updated'], reverse=True)
    return rows[:MAX_SESSIONS_LISTED]


def latest():
    """最近动过的会话名 (给 --continue), 没有就是 None"""
    rows = recent()
    return rows[0]['name'] if rows else None


def fmt_rows(rows):
    """--sessions 的表格 (对齐走 zen.render._table, 中文表头才不会歪)"""
    from webtool.cli.zen.render import _fmt_ts, _table
    body = [[r['name'], _fmt_ts(r.get('updated')),
             '%d' % (r.get('steps') or 0), '%d' % (r.get('messages') or 0),
             r.get('model') or '-', r.get('workspace') or '-']
            for r in rows]
    if not body:
        return '还没有会话 (用 --session <名> 开一条)'
    head = ['会话', '最近', '轮数', '消息数', '模型', '工作空间']
    return '\n'.join([_table(head, body), '',
                      '接上一次: --continue    继续某条: --session <名>',
                      '清掉某条: --session <名> --clear-session'])