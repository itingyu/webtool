"""数据源聚合门面 —— 按源拆包, 对外仍是同一个 `APIClient`

拆分的理由: 这些方法全挤在一个 3251 行的 `api_client.py` 里时, 找"东财的
接口在哪"得全文搜。这里按**数据源**拆成十个模块 (另加传输/归一/自检基建), 但对外签名不变:

    from webtool.stock.bridge.sources import APIClient
    c = APIClient()
    c.em_f10_balance('600519.SH')     # 方法名不变, 上层零改动

`APIClient` 只是把各源 mixin 合到一个类上, 所以:
  - 153 个方法, 除 `_provenance` 记录的新增 2 个外, 名字/参数/行为与拆包前逐字一致
  - session 只有一份 (`SourceBase.__init__`), token 与 cookie 缓存仍共享
  - 新增一个源 = 加一个 `sources/<源>.py`, 这里加一行 mixin, 别处不动

## 源清单

| 模块 | 源 | 方法数 |
|---|---|---|
| `ths.py` | 同花顺 (v cookie 反爬) | 35 |
| `em.py` | 东方财富 (ut token) | 32 |
| `xueqiu.py` | 雪球 (TLS 指纹) | 31 |
| `sina.py` | 新浪财经 + 腾讯行情 CDN | 28 |
| `tencent.py` | 腾讯财经 | 9 |
| `gtimg_*` | 已并入 `sina.py` (实际域名是新浪) | — |
| `cninfo.py` | 巨潮资讯 | 6 |
| `csindex.py` | 中证指数 | 4 |
| `sse.py` | 上交所 | 3 |
| `np.py` | 东财公告老域 | 2 |
| `ef.py` | efinance (本地库) | 3 |

## 传输层为什么留在公共底座

`_xueqiu_session` 名义属雪球, 实际 `tencent_kline_global` / `tencent_us_kline`
/ `tencent_minute` 也借它 —— 要 curl_cffi 指纹才能过 `web.ifzq.gtimg.cn`,
但请求打的是腾讯域名。属传输层而非数据源, 故在 `_base.py`。
"""
from webtool.stock.bridge.sources._base import SourceBase, _err, _ok
from webtool.stock.bridge.sources.ths import ThsSource
from webtool.stock.bridge.sources.em import EmSource
from webtool.stock.bridge.sources.xueqiu import XueqiuSource
from webtool.stock.bridge.sources.sina import SinaSource
from webtool.stock.bridge.sources.tencent import TencentSource
from webtool.stock.bridge.sources.cninfo import CninfoSource
from webtool.stock.bridge.sources.csindex import CsindexSource
from webtool.stock.bridge.sources.sse import SseSource
from webtool.stock.bridge.sources.np import NpSource
from webtool.stock.bridge.sources.ef import EfSource


class APIClient(ThsSource, EmSource, XueqiuSource, SinaSource, TencentSource,
                CninfoSource, CsindexSource, SseSource, NpSource, EfSource):
    """十一个数据源的聚合客户端。

    MRO 上各源互不重叠 (方法名前缀即归属), 只有 session 状态来自
    `SourceBase.__init__` —— 三份持 token/session 的模块 (rawapi / 服务端 /
    stock-master) 拿到的仍是同一个类、同一份缓存。
    """
# 源 → mixin, 供 tools/ 与文档查询用, 也让新增源只需改这一处
SOURCES = {
    'ths': ThsSource, 'em': EmSource, 'xueqiu': XueqiuSource, 'sina': SinaSource,
    'tencent': TencentSource, 'cninfo': CninfoSource, 'csindex': CsindexSource,
    'sse': SseSource, 'np': NpSource, 'ef': EfSource,
}

__all__ = ['APIClient', 'SourceBase', 'SOURCES', '_ok', '_err']