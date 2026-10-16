"""数据源契约 (L0'): `DataPacket` 统一信封 + `SourceBase` 适配器接口

把「数据源只负责取数, 不关心给谁用」从口号变成可落地的契约:

- 取数方 (engines / feeds / stock) 各自实现 `SourceBase.fetch`, 返回 `DataPacket`
- 用数方 (pipeline / render / cli) 只认识 `DataPacket`, 不认识任何具体数据源
- 工厂 (`sources.registry.get`) 按名字造实例, 调用点没有 if-else 链

契约不依赖任何采集实现 —— 实现放各自的层 (`engines/source.py`,
`feeds/source.py`), 由 `plugins.json` 的 `source` kind 登记。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class SourceError(RuntimeError):
    """数据源取数失败 (网络/解析/风控); 调用点可退到别的源"""


@dataclass
class DataPacket:
    """统一数据契约: 一次取数的结果信封

    source  数据源名 (search:bing / feed:ruanyifeng / quote:xueqiu)
    kind    数据形态: search / feed / quote / page …
    items   条目列表, 元素是纯 dict (上层不认数据源, 只认这个形状)
    meta    批级元信息 (条数 / 耗时 / 命中缓存 / 自报线路 …)
    error   非空表示这次取数失败 (items 可能仍有部分结果)
    """

    source: str
    kind: str
    items: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    error: str = ''

    @property
    def ok(self) -> bool:
        return not self.error

    def __len__(self) -> int:
        return len(self.items)


class SourceBase(ABC):
    """数据源接口: 不知道给谁用, 只承诺「给一个请求, 还一个 DataPacket」"""

    name = ''
    kind = ''

    def __init__(self, **opts):
        self.opts = dict(opts)

    @abstractmethod
    def fetch(self, req) -> DataPacket:
        """req 是纯 dict (如 `{'query': 'x', 'max_results': 10}`)"""

    def health(self) -> dict:
        """探活: 默认给中性答复, 有真实探活手段的子类覆写"""
        return {'source': self.name, 'kind': self.kind, 'ok': True}
