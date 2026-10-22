"""进程内跑一条 webtool 命令, 拿它的 stdout / JSON 结果

给 `zen --agent` 的工具 (websearch/webfetch) 和 `ask` 复用: 要的是"本仓自己的
search / fetch 管线", 但管线入口吃几十个字段的 args 对象, 自己拼等于在本仓里
复制一份 CLI 契约, 迟早漂 (`search` 已经 29 个字段)。所以直接跑 CLI 本身。

两处全局状态必须复原, 否则第一次内层调用就把外层弄坏:
  `_CTX`          —— app 回调每次都 `_CTX.clear()`, 复原前外层已取到的 args 不受
                     影响, 但之后的读 (如 args.format) 会读到空;
  日志级别        —— 回调按本层 argv 的 debug 次数重新 setup(0), 会把外层 `-d` 抹掉。
"""

import io
import json
from contextlib import redirect_stdout


def run_cli(argv):
    """进程内跑一条命令 → (rc, stdout)"""
    # 延迟导入: cli.app 会拉进全部命令模块, 顶层导入在命令内部会成环
    from webtool.cli import app as _app
    from webtool.cli._ctx import _CTX
    from webtool.core import logging as _log
    saved_ctx = dict(_CTX)
    saved_dbg = _log.debug_level()
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            rc = _app.main(argv)
    finally:
        _CTX.clear()
        _CTX.update(saved_ctx)
        _log.setup(saved_dbg)
    return rc, buf.getvalue()


def cli_json(argv):
    """跑一条命令取 JSON 结果 → (ok, 值或原始文本)"""
    rc, out = run_cli(argv)
    try:
        return True, json.loads(out)
    except ValueError:
        return False, (out.strip() or '(webtool %s 无输出, rc=%s)'
                       % (' '.join(argv[:1]), rc))
