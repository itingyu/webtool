"""URL → 正文/文件 → 数据源适配器 (SourceBase 实现)

把 `pipeline.fetch` 那条「取 → 判型 → 提取 → 落盘」的链路包成标准信封, 于是
"给一个 URL 拿一篇正文"和"给一个词拿一批搜索结果"在调用方看来是同一种动作:
都是 `DataPacket`。取数细节 (指纹轮换、代理线路、拦截判定、正文提取器择优) 都
留在 `_fetch_one` 里, 适配器只管把请求翻译成它认的 args。

登记名 `page`:
    pkt = get_source('page').fetch({'url': 'https://example.com'})
    print(pkt.items[0]['content'])
"""
from types import SimpleNamespace

from webtool.engines import extractors as _extractors
from webtool.net.proxy.store import load_config as _load_config
from webtool.pipeline.fetch import _fetch_one
from webtool.sources.contract import DataPacket, SourceBase, SourceError


class PageSource(SourceBase):
    """抓一个 URL 并提取正文 (或落盘二进制); 一次调用一个 URL, items 恒为 0/1 条

    默认值抄 CLI 的 `fetch_cmd` (`format=text` 等): format 参与缓存 key,
    两条路给不同默认值会让同一个 URL 在两边取到不同东西。
    """

    name = 'page'
    kind = 'page'

    def __init__(self, format='text', max_chars=0, proxy=None, timeout=None,
                 extract=None, profile=None, raw=False, no_cache=False, **opts):
        super().__init__(**opts)
        self.format = format
        self.max_chars = max_chars
        self.proxy = proxy
        self.timeout = timeout
        self.extract = extract
        self.profile = profile
        self.raw = raw
        self.no_cache = no_cache

    @property
    def source_id(self):
        return 'page'

    def fetch(self, req) -> DataPacket:
        req = dict(req or {})
        url = str(req.get('url') or '').strip()
        if not url:
            raise SourceError('page 源需要非空 url')

        cfg = _load_config()
        mode = _extractors.resolve_mode(req.get('extract') or self.extract
                                        or cfg.get('extract'))
        args = SimpleNamespace(
            url=url,
            format=req.get('format') or self.format,
            max_chars=int(req.get('max_chars') or self.max_chars),
            raw=bool(req.get('raw', self.raw)),
            no_cache=bool(req.get('no_cache', self.no_cache)),
            with_metadata=bool(req.get('with_metadata', False)),
            via=req.get('via') or 'local',
            profile=req.get('profile') or self.profile,
        )
        timeout = self.timeout if self.timeout is not None else cfg.get('timeout', 15)

        try:
            r = _fetch_one(url, args, cfg, self.proxy, timeout, mode)
        except Exception as e:                   # noqa: BLE001
            # 与其它源一致: 失败落进信封, 不抛 —— 调用方要的是"这一条取不到"
            return DataPacket(self.source_id, 'page', [],
                              meta={'url': url},
                              error=f'{type(e).__name__}: {e}')

        r = r or {}
        items = [r] if r else []
        return DataPacket(self.source_id, 'page', items,
                          meta={'url': url, 'total': len(items),
                                'status': r.get('status'), 'via': r.get('via')},
                          error=str(r.get('error') or ''))

    def health(self) -> dict:
        return {'source': self.source_id, 'ok': True,
                'desc': 'URL → 正文/文件 (取数细节全在 pipeline.fetch)'}
