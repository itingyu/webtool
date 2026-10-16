"""搜索/站点引擎 → 数据源适配器 (SourceBase 实现)

`DataPacket` 契约在 `webtool.sources.contract`; 这里只负责把「调一个已登记引擎
拿一批结果」包装成标准信封, 让 pipeline 之外的调用方 (agent / 脚本 / 未来的
新业务流程) 能用一个统一入口取数, 不必知道引擎注册表长什么样。

登记名 `search`, 构造时给 `engine=`:
    pkt = get_source('search', engine='bing').fetch({'query': 'x'})
"""
from webtool.core.plugins import table as _plugin_table
from webtool.sources.contract import DataPacket, SourceBase, SourceError


class SearchSource(SourceBase):
    """把一个已登记引擎包成数据源; items 形状与引擎原生结果一致"""

    name = 'search'
    kind = 'search'

    def __init__(self, engine='bing', proxy=None, timeout=None, **opts):
        super().__init__(**opts)
        self.engine = engine
        self.proxy = proxy
        self.timeout = timeout

    @property
    def source_id(self):
        return f'search:{self.engine}'

    def fetch(self, req) -> DataPacket:
        req = dict(req or {})
        query = str(req.get('query') or '').strip()
        if not query:
            raise SourceError('search 源需要非空 query')
        spec = _plugin_table('engine').get(self.engine)
        if not spec:
            raise SourceError(f'未知引擎 {self.engine!r}; 可用: '
                              f'{", ".join(_plugin_table("engine"))}')
        kw = {'max_results': int(req.get('max_results') or 10)}
        if self.proxy is not None:
            kw['proxy'] = self.proxy
        if self.timeout is not None:
            kw['timeout'] = self.timeout
        try:
            raw = spec['fn'](query, **kw) or []
        except Exception as e:                   # noqa: BLE001
            # 引擎失败不抛: 信封带 error, 调用方决定换源还是就报这一条
            return DataPacket(self.source_id, 'search', [],
                              meta={'engine': self.engine},
                              error=f'{type(e).__name__}: {e}')
        items = [dict(r, engine=self.engine) for r in raw]
        return DataPacket(self.source_id, 'search', items,
                          meta={'engine': self.engine, 'total': len(items)})

    def health(self) -> dict:
        try:
            spec = _plugin_table('engine').get(self.engine)
        except Exception as e:                   # noqa: BLE001
            return {'source': self.source_id, 'ok': False, 'error': str(e)}
        return {'source': self.source_id, 'ok': bool(spec),
                'desc': (spec or {}).get('desc', '')}
