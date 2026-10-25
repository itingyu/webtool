"""需要大模型的功能开关 (ask / zen)

默认关闭: 这两个命令要调外部模型, 不是"搜网页/抓正文"的基础能力。
关闭时顶层帮助不列、命令入口直接拒绝; 要开就 `webtool config set llm on`。

只读 config.json 的一个键, 不 import 网络栈 —— fastpath 打印帮助时会调用,
不能为了一个布尔值把 requests/typer 拖进来。WEBTOOL_LLM=on/off 可临时覆盖
(测试与多实例用)。
"""
import json
import os
from pathlib import Path

_ON = ('on', 'true', '1', 'yes', 'enable', 'enabled')


def _config_path():
    return Path(os.environ.get('WEBTOOL_DIR', '~/.webtool')).expanduser() / 'config.json'


def llm_enabled():
    env = os.environ.get('WEBTOOL_LLM')
    if env is not None:
        return env.strip().lower() in _ON
    try:
        with open(_config_path(), encoding='utf-8') as f:
            cfg = json.load(f)
        return str(cfg.get('llm', 'off')).strip().lower() in _ON
    except (OSError, ValueError, TypeError):
        return False


DISABLED = ('大模型功能已关闭 (ask / zen 需要外部模型)。'
            '启用: webtool config set llm on')
