"""搜索/站内/榜单引擎 → 数据源适配器 (SourceBase 实现)

`DataPacket` 契约在 `webtool.sources.contract`; 这里只负责把「调一个已登记插件
拿一批结果」包装成标准信封, 让 pipeline 之外的调用方 (agent / 脚本 / 未来的新
业务流程) 能用一个统一入口取数, 不必知道插件注册表长什么样。

三个引擎类插件的调用约定不同 (都在 plugins.SIGNATURES 里), 适配器把它们抹平:

  engine   fn(query, max_results=, proxy=, timeout=)   → get_source('search', engine='bing')
  site     fn(query, limit, proxy, timeout, **extra)   → get_source('site', site='github')
  hot      fn(query, limit, proxy, timeout)            → get_source('hot', hot='zhihu')
"""
from webtool.core.plugins import table as _plugin_table
from webtool.sources.contract import DataPacket, SourceBase, SourceError


def _spec_of(kind, name):
    """取一类插件里某一条的规格; 不在就报错并列出可用项 (别只说"没有")"""
    tbl = _plugin_table(kind)
    spec = tbl.get(name)
    if not spec:
        raise SourceError(f'未知 {kind} 源 {name!r}; 可用: {", ".join(tbl) or "(空)"}')
    return spec


def _fail(source_id, kind, meta, e):
    """取数失败不抛: 信封带 error, 调用方决定换源还是就报这一条"""
    return DataPacket(source_id, kind, [], meta=meta,
                      error=f'{type(e).__name__}: {e}')


class SearchSource(SourceBase):
    """把搜索引擎包成数据源; items 形状与引擎原生结果一致"""

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
        try:
            spec = _spec_of('engine', self.engine)
            kw = {'max_results': int(req.get('max_results') or 10)}
            if self.proxy is not None:
                kw['proxy'] = self.proxy
            if self.timeout is not None:
                kw['timeout'] = self.timeout
            raw = spec['fn'](query, **kw) or []
        except SourceError:
            raise
        except Exception as e:                   # noqa: BLE001
            return _fail(self.source_id, 'search', {'engine': self.engine}, e)
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


class SiteSource(SourceBase):
    """站内搜索源 (官方 API 白名单, 不参与黑名单过滤)

    站点可在 plugins.json 的 `params.args` 里声明额外参数 (如 wikipedia 的 lang),
    随请求的 `extra` 带上即可 —— 不在适配器里按站点名写分支。
    """

    name = 'site'
    kind = 'site'

    def __init__(self, site='github', proxy=None, timeout=None, **opts):
        super().__init__(**opts)
        self.site = site
        self.proxy = proxy
        self.timeout = timeout

    @property
    def source_id(self):
        return f'site:{self.site}'

    def fetch(self, req) -> DataPacket:
        req = dict(req or {})
        query = str(req.get('query') or '').strip()
        if not query:
            raise SourceError('site 源需要非空 query')
        limit = int(req.get('limit') or req.get('max_results') or 10)
        extra = dict(req.get('extra') or {})
        try:
            spec = _spec_of('site', self.site)
            raw = spec['fn'](query, limit, self.proxy, self.timeout, **extra) or []
        except SourceError:
            raise
        except Exception as e:                   # noqa: BLE001
            return _fail(self.source_id, 'site', {'site': self.site}, e)
        items = [dict(r, site=self.site) for r in raw]
        return DataPacket(self.source_id, 'site', items,
                          meta={'site': self.site, 'total': len(items)})

    def health(self) -> dict:
        try:
            spec = _plugin_table('site').get(self.site)
        except Exception as e:                   # noqa: BLE001
            return {'source': self.source_id, 'ok': False, 'error': str(e)}
        return {'source': self.source_id, 'ok': bool(spec),
                'desc': (spec or {}).get('desc', '')}


class HotSource(SourceBase):
    """榜单源 (热搜/热榜); `hot=` 给源名, 不给就用 `platform` 声明名"""

    name = 'hot'
    kind = 'hot'

    def __init__(self, hot='', proxy=None, timeout=None, **opts):
        super().__init__(**opts)
        self.hot = hot
        self.proxy = proxy
        self.timeout = timeout

    @property
    def source_id(self):
        return f'hot:{self.hot}'

    def fetch(self, req) -> DataPacket:
        req = dict(req or {})
        name = str(req.get('hot') or self.hot or '').strip()
        if not name:
            raise SourceError('hot 源需要 hot=<源名> (webtool rank list 看全部)')
        query = str(req.get('query') or '')
        limit = int(req.get('limit') or req.get('max_results') or 20)
        try:
            spec = _spec_of('hot', name)
            raw = spec['fn'](query, limit, self.proxy, self.timeout) or []
        except SourceError:
            raise
        except Exception as e:                   # noqa: BLE001
            return _fail(self.source_id, 'hot', {'hot': name}, e)
        items = [dict(r, hot=name) for r in raw]
        return DataPacket(f'hot:{name}', 'hot', items,
                          meta={'hot': name, 'total': len(items)})

    def health(self) -> dict:
        try:
            spec = _plugin_table('hot').get(self.hot)
        except Exception as e:                   # noqa: BLE001
            return {'source': self.source_id, 'ok': False, 'error': str(e)}
        return {'source': self.source_id, 'ok': bool(spec),
                'desc': (spec or {}).get('desc', '')}
