"""engine —— 业务脚本层（选股池 / 评分 / 可买性闸门 / 研报模板）

子包按需导出: `from webtool.stock.engine import analysis` 仍然可用 (PEP 562),
但 `import webtool.stock.engine.short_tool` 不再顺带把 analysis/screening/
visualization 全拉起来 —— 那几包会拖进 pandas/numpy (~1.5s), 而查个交易日历
一个都用不上。
"""
import importlib

__all__ = [
    "analysis",
    "screening",
    "sentiment",
    "research",
    "visualization",
]


def __getattr__(name):
    if name in __all__:
        mod = importlib.import_module('%s.%s' % (__name__, name))
        globals()[name] = mod          # 只算一次, 后续取 by attribute
        return mod
    raise AttributeError("module %r has no attribute %r" % (__name__, name))
