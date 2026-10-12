"""JSON I/O 工具类

配置/状态/缓存三类 JSON 的读写此前各写一份 open+json.dump, 差别只在
"写坏了要不要报错"。收口成两个明确意图:

    read   读不到/坏了返回默认值 (配置与状态: 坏了退回默认, 不拖垮主流程)
    write  原子写 (临时文件 + rename): 状态/缓存写到一半崩了不留半截文件
"""
import json
import os
from pathlib import Path

def read(path, default=None):
    """读 JSON; 文件不存在/损坏返回 default (default 为 dict 时返回其浅拷贝)"""
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (FileNotFoundError, ValueError, OSError):
        return {} if default is None else default

def write(path, obj, indent=2):
    """原子写 JSON: 先写同目录临时文件再 rename, 避免半截文件"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + '.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=indent),
                   encoding='utf-8')
    os.replace(tmp, p)

def fingerprint(path):
    """文件指纹 (mtime_ns, size); 不存在返回 None —— 用于配置热更新判失效"""
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None