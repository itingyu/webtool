"""免 key 引擎降级链

主引擎全挂 (被拦/超时/返回空) 时, 用不依赖任何 key 的引擎兜一层。
"免 key" 由 plugins.json 的 engine.params.keyless 声明, fallback_rank 定顺序,
不在这里写死引擎名 —— 加一个免 key 引擎只需改数据。

纯选择逻辑, 不放抓取与合并 (那部分在 pipeline.search 里, 要用它的缓存/过滤闭包)。
"""
from __future__ import annotations


def chain(table):
    """按 fallback_rank 排出免 key 引擎名, 只保留有 fn 的

    table 是 engine 插件表 (name -> spec)。
    """
    rows = []
    for name, spec in (table or {}).items():
        params = spec.get('params') or {}
        if not params.get('keyless'):
            continue
        if not spec.get('fn'):
            continue
        rows.append((params.get('fallback_rank', 99), name))
    rows.sort()
    return [name for _, name in rows]


def needed(got, want):
    """结果是否少到值得降级

    阈值取 min(want, 3): 用户要 1 条时 0 条才降级; 要 10 条时不足 3 条才降。
    宁可少兜几次, 也别让正常搜索多付一轮外网请求。
    """
    return got < min(max(want, 1), 3)


def select(table, tried, limit=3):
    """挑出待降级的引擎: 链上未被本次搜索跑过的, 最多 limit 个"""
    tried = set(tried or ())
    return [n for n in chain(table) if n not in tried][:max(limit, 0)]
