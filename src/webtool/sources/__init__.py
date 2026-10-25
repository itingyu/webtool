"""数据源接口层 (L0'): 统一数据契约 + 适配器接口 + 工厂

`DataPacket` 是取数的统一信封, `SourceBase` 是数据源要实现的接口, `get(name)`
是按名字造实例的工厂。三者都不依赖任何采集实现 —— 实现落在各自的层, 由契约把
三类插件各不相同的调用约定抹平:

  engines/source.py   `SearchSource` (engine) · `SiteSource` (site) · `HotSource` (hot)
  feeds/source.py     `FeedSource`   (RSS/Atom 源)
  pipeline/source.py  `PageSource`   (URL → 正文/文件)

登记与实例化见 `webtool.sources.registry`; 契约细节见 `contract`。
"""
from webtool.sources.contract import DataPacket as DataPacket
from webtool.sources.contract import SourceBase as SourceBase
from webtool.sources.contract import SourceError as SourceError
from webtool.sources.registry import get as get_source
from webtool.sources.registry import names as source_names
from webtool.sources.registry import register as register_source

__all__ = ['DataPacket', 'SourceBase', 'SourceError', 'get_source',
           'register_source', 'source_names']
