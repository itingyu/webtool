"""efinance —— 3 个方法

端点: (本地库, 非 HTTP 直连)
反爬: efinance 包调用, 内部自行取数, 无网络栈直控

"""
from webtool.stock.bridge.sources._base import _err, _ok, SourceBase

# efinance 顶层 import 会把 pandas/numpy 一起拉起来 (~2.5s)。只有真调 ef_*
# 这 3 个方法时才需要它 —— 别的源、甚至同包其他类都不该替它付这笔钱。
_ef_mod = None
_HAS_EF = None


def _ef():
    """(efinance 模块 | None)。首次调用才探测, 结果缓存"""
    global _ef_mod, _HAS_EF
    if _HAS_EF is None:
        try:
            import efinance as _m
            _ef_mod, _HAS_EF = _m, True
        except ImportError:
            _ef_mod, _HAS_EF = None, False
    return _ef_mod



class EfSource(SourceBase):
    """efinance 方法集 —— 由 sources/__init__.py 的 APIClient 混入"""

    def _ef_check(self):
        if _ef() is None:
            from webtool.core import deps
            return _err('efinance 不可用: ' + deps.install_hint('efinance'))
        return None

    def ef_snapshot(self, code: str = "688825") -> dict:
        """实时快照 -> dict"""
        err = self._ef_check()
        if err: return err
        try:
            s = _ef().stock.get_quote_snapshot(code)
            if s is None:
                return _err("返回 None")
            d = dict(s)
            # 兼容两种 key: 名称 (Series) / 股票名称
            d.setdefault("股票名称", d.get("名称"))
            return _ok(d, len(s))
        except Exception as e:
            return _err(str(e))

    def ef_history(self, code: str = "688825") -> dict:
        """历史 K 线 -> DataFrame 转 list[dict]"""
        err = self._ef_check()
        if err: return err
        try:
            df = _ef().stock.get_quote_history(code)
            return _ok(df.to_dict(orient="records"), len(df))
        except Exception as e:
            return _err(str(e))

    def ef_base_info(self, code: str = "688825") -> dict:
        """基本信息"""
        err = self._ef_check()
        if err: return err
        try:
            s = _ef().stock.get_base_info(code)
            if s is None:
                return _err("返回 None")
            d = dict(s)
            d.setdefault("股票名称", d.get("名称"))
            return _ok(d, len(s))
        except Exception as e:
            return _err(str(e))

    # 同花顺 data.10jqka.com.cn 子域 (反爬绕过: 借浏览器定位发现)
