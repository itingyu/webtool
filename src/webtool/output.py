"""webtool CLI 输出统一出口: 渲染 + 可选写文件 (-o/--output)

-o file 按 -f 格式落盘, -o - 或未指定走 stdout; 未给扩展名按 -f 自动补;
-o 目录时自动命名 webtool-<cmd>-<ts>.<ext>; 写文件成功后回一行提示。
"""
import json
import os
import sys
from datetime import datetime

EXT = {'json': '.json', 'markdown': '.md', 'md': '.md', 'text': '.txt',
       'txt': '.txt', 'html': '.html'}


def emit(payload_str, fmt, output):
    """统一输出: output=None/- → stdout; 否则写文件并打一行提示。

    payload_str: 已按 fmt 序列化好的完整文本
    返回 exit code (0)
    """
    if not output or output == '-':
        print(payload_str)
        return 0
    path = os.path.expanduser(output)
    if path.endswith(os.sep) or os.path.isdir(path):
        ts = datetime.now().strftime('%Y%m%d-%H%M%S')
        name = f'webtool-{os.environ.get("WEBTOOL_CMD", "out")}-{ts}{EXT.get(fmt, ".txt")}'
        path = os.path.join(path, name)
    else:
        root, ext = os.path.splitext(path)
        if not ext:
            path = root + EXT.get(fmt, '.txt')
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(payload_str)
        if payload_str and not payload_str.endswith('\n'):
            f.write('\n')
    n = os.path.getsize(path)
    print(f'saved: {path} ({n} bytes, format={fmt})', file=sys.stderr)
    return 0
