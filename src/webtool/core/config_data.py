"""配置加载: 包内 data/*.json (默认) + ~/.webtool/*.json (用户覆盖) 两层合并

用户文件存在即按段深合并 (用户段里的 key 覆盖默认, 未提及的保持默认),
所以用户只需写要改的那几项, 不必复制整份默认。

改动文件后同进程内自动生效: 按 mtime/size 指纹判定缓存失效, 变了才重新
解析, 没变直接复用 (避免每次访问都读盘+解析)。

新增一类配置: 在本模块加一个 load_xxx() 包装 load(section, default_file),
并在 src/webtool/data/ 下建对应的 json。
"""
import os
from pathlib import Path

from webtool.core import jsonfmt

DATA_DIR = Path(__file__).parent.parent / 'data'   # 打包数据统一在包根 webtool/data/
# 用户目录单一来源: config / proxy / secrets_store 都从这里取,
# WEBTOOL_DIR 可把整份用户状态隔离到别处 (测试、多实例并行)
USER_DIR = Path(os.environ.get('WEBTOOL_DIR', '~/.webtool')).expanduser()

# geo 数据 (geosite/geoip) 的**用户侧**落地目录。包内 data/geo/ 自带一份,
# 首次运行由 bootstrap 复制过来; `webtool proxy geo update` 也只更新这里这份 ——
# 包目录在 site-packages 里, pip 升级整棵替换, 不是放"会变的数据"的地方。
USER_GEO_DIR = USER_DIR / 'geo'


def user_geo_path(kind):
    """用户目录下 geo 数据的默认路径。kind: 'geosite' | 'geoip'"""
    return USER_GEO_DIR / f'{kind}.dat'


_CACHE = {}          # (section, filename, user_file) -> (stamp, value)

def _merge(base, over):
    """字典深合并; 列表整体替换 (不做集合并, 便于用户精确表达意图)"""
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out

def load(section, filename, user_file=None, use_cache=True):
    """读 data/<filename> 的 section 段, 叠加用户 ~/.webtool/<user_file> 同段

    热更新: 源文件指纹变化即自动重新读取, 调用方无需重启。
    """
    key = (section, filename, user_file)
    base_path = DATA_DIR / filename
    user_path = USER_DIR / (user_file or filename)
    stamp = (jsonfmt.fingerprint(base_path), jsonfmt.fingerprint(user_path))
    if use_cache:
        hit = _CACHE.get(key)
        if hit and hit[0] == stamp:
            return hit[1]
    value = _merge(jsonfmt.read(base_path).get(section, {}),
                   jsonfmt.read(user_path).get(section, {}))
    _CACHE[key] = (stamp, value)
    return value

def invalidate():
    """清空缓存, 下次 load 全量重读 (外部批量改配置后调用)"""
    _CACHE.clear()

def get(path, default=None, filename='config.json'):
    """读单值, 路径形如 'ranking.semantic_threshold': load('ranking','config.json')"""
    cur = load(filename=filename)
    for part in path.split('.'):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur