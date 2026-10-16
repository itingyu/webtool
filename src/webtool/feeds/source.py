"""RSS/Atom 源 → 数据源适配器 (SourceBase 实现)

`DataPacket` 契约在 `webtool.sources.contract`; 这里把「取一个 feed 的最新条目」
包装成标准信封。feed 名走 `~/.webtool/feeds.json` + 随包种子 (见 feeds.sources),
也能直接给 url。

登记名 `feed`, 构造时给 `feed=` (或 `url=`):
    pkt = get_source('feed', feed='ruanyifeng').fetch({'limit': 20})
"""
from webtool.feeds.fetch import pull_one
from webtool.feeds.sources import load_user_feeds
from webtool.sources.contract import DataPacket, SourceBase, SourceError


class FeedSource(SourceBase):
    """把一个 RSS/Atom 源包成数据源; items 为 {rank,title,url,snippet,date}"""

    name = 'feed'
    kind = 'feed'

    def __init__(self, feed='', url='', limit=30, proxy=None, timeout=None,
                 **opts):
        super().__init__(**opts)
        self.feed = feed
        self.url = url
        self.limit = int(limit or 30)
        self.proxy = proxy
        self.timeout = timeout

    def _resolve(self, req):
        name = str(req.get('feed') or self.feed or '')
        url = str(req.get('url') or self.url or '')
        if url:
            return name or url, url
        if not name:
            raise SourceError('feed 源需要 feed= 或 url=')
        entry = load_user_feeds().get(name)
        if not entry:
            raise SourceError(f'未知 feed 源 {name!r}; 用 webtool feed --list 看清单')
        return name, entry.get('url') or ''

    def fetch(self, req) -> DataPacket:
        req = dict(req or {})
        name, url = self._resolve(req)
        if not url:
            raise SourceError(f'feed 源 {name!r} 没有 url')
        n = int(req.get('limit') or self.limit)
        try:
            items = pull_one(name, url, n, self.proxy, self.timeout) or []
        except Exception as e:                   # noqa: BLE001
            return DataPacket(f'feed:{name}', 'feed', [], meta={'url': url},
                              error=f'{type(e).__name__}: {e}')
        return DataPacket(f'feed:{name}', 'feed', items,
                          meta={'url': url, 'total': len(items)})

    def health(self) -> dict:
        try:
            name, url = self._resolve({})
        except SourceError as e:
            return {'source': f'feed:{self.feed}', 'ok': False, 'error': str(e)}
        return {'source': f'feed:{name}', 'ok': bool(url), 'url': url}
