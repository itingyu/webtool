"""stdin / 管道输入: 文本命令的统一读入口

约定 (docs/coding-standard.md §2.7):
- `read_input(arg)`: arg 有值用 arg; arg 为 '-' 或 (无参且 stdin 非 tty) 读 stdin
- 只承诺文本; json/jsonl/url 列表等结构由调用方用 parse_jsonl/parse_lines 解
- 二进制不走这里 (fetch 的输出落盘走 -o, 输入侧没有二进制场景)

范式:
    cat urls.txt | webtool fetch -          # URL 列表逐个抓
    webtool rank 芯片 -f json | webtool search -   # 上游结果当下游输入
"""
import json
import sys


def is_pipe():
    """stdin 是否被管道/重定向喂着 (交互终端返回 False)"""
    try:
        return not sys.stdin.isatty()
    except Exception:
        return False


def read_input(arg=None, *, required=False, what='输入'):
    """取输入文本: 显式参数 > '-' 管道 > 无参管道 > None

    - arg 有值且不是 '-' → 原样返回
    - arg == '-' → 必须从 stdin 读, 读不到(是 tty)报用法错
    - arg 为 None 且 stdin 是管道 → 读 stdin (省掉 '-' 的便利写法)
    - 都没有 → required 时报错退出(2), 否则返回 None

    返回文本 (rstrip 掉末尾换行); 空管道输入按没有算。
    """
    if arg is not None and arg != '-':
        return arg
    if arg == '-' or (arg is None and is_pipe()):
        data = sys.stdin.read() if is_pipe() else ''
        data = data.rstrip('\n')
        if data:
            return data
        if arg == '-':
            _die(f'stdin 没有内容 ({what}用管道喂进来, 如: cat x.txt | {sys.argv[0]} -)')
        # arg is None: 空管道按没有输入处理, 继续走 required 检查
    if required:
        _die(f'缺少{what}: 传参数或用管道喂 stdin')
    return None


def parse_lines(text):
    """按行拆列表, 跳过空行与 # 注释 —— url 列表/代码列表的通用口径"""
    if not text:
        return []
    return [l.strip() for l in text.splitlines()
            if l.strip() and not l.strip().startswith('#')]


def parse_jsonl(text):
    """逐行 JSON, 坏行不静默: 报错带行号 (静默丢行 = 上游以为都处理了)"""
    out = []
    for i, line in enumerate(parse_lines(text), 1):
        try:
            out.append(json.loads(line))
        except ValueError as e:
            _die(f'stdin 第 {i} 行不是合法 JSON: {line[:80]!r} ({e})')
    return out


def _die(msg):
    print(f'webtool: {msg}', file=sys.stderr)
    raise SystemExit(2)
