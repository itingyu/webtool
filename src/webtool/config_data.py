# -*- coding: utf-8 -*-
"""配置加载: 包内 data/*.json (默认) + ~/.webtool/*.json (用户覆盖) 两层合并

用户文件存在即按段深合并 (用户段里的 key 覆盖默认, 未提及的保持默认),
所以用户只需写要改的那几项, 不必复制整份默认。

新增一类配置: 在本模块加一个 load_xxx() 包装 _load(section, default_file),
并在 src/webtool/data/ 下建对应的 json。
"""
import json
import os
from pathlib import Path

DATA_DIR = Path(__file__).parent / 'data'
USER_DIR = Path(os.path.expanduser('~/.webtool'))


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {}
    except (ValueError, OSError):
        return {}          # 配置坏了不该拖垮主流程, 退回内置默认


def _merge(base, over):
    """字典深合并; 列表整体替换 (不做集合并, 便于用户精确表达意图)"""
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load(section, filename, user_file=None):
    """读 data/<filename> 的 section 段, 叠加用户 ~/.webtool/<user_file> 同段"""
    base = _read(DATA_DIR / filename).get(section, {})
    user = _read(USER_DIR / (user_file or filename)).get(section, {})
    return _merge(base, user)


def get(path, default=None, filename='config.json'):
    """读单值, 路径形如 'ranking.semantic_threshold': load('ranking','config.json')"""
    cur = load(filename=filename)
    for part in path.split('.'):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur