"""东财 (push2/push2his/datacenter-web/emweb) 数据源

42 个端点按族拆进 mixin, 组合成一个 EmSource —— 方法都只用 self,
拆开不影响任何调用点 (对外仍是 EmSource)."""
"""东方财富 (eastmoney) —— 32 个方法

端点: push2 / push2his / emweb / datacenter-web
反爬: push2 需固定 ut token; datacenter 需 source=WEB+client=PC; 公告一路走 curl 子进程

"""
from webtool.stock.bridge.sources._base import SourceBase



from webtool.stock.bridge.sources.em._quote import EmQuoteMixin
from webtool.stock.bridge.sources.em._f10 import EmF10Mixin
from webtool.stock.bridge.sources.em._datacenter import EmDatacenterMixin
from webtool.stock.bridge.sources.em._core import EmCoreMixin


class EmSource(EmQuoteMixin, EmF10Mixin, EmDatacenterMixin, EmCoreMixin, SourceBase):
    """组合式 EmSource: 各族混入, 公共零件在 _core"""
