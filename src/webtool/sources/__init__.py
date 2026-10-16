"""数据源接口层 (L0'): 统一数据契约 + 适配器接口 + 工厂

`DataPacket` 是取数的统一信封, `SourceBase` 是数据源要实现的接口, `get(name)`
是按名字造实例的工厂。三者都不依赖任何采集实现 —— 实现落在各自的层:

  engines/source.py   `SearchSource`  包一个搜索/站点引擎 → DataPacket
  feeds/source.py     `FeedSource`    包一个 RSS/Atom 源     → DataPacket

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
