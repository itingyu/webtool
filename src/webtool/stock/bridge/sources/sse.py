"""上交所 (sse) —— 3 个方法

端点: yunhq.sse.com.cn
命名: `sse` 指 **上海证券交易所** (Shanghai Stock Exchange), 与 HTTP 的
      Server-Sent Events 无关 —— 本仓唯一用 SSE 流的地方是
      `net/mcpclient.py` (MCP 协议握手), 与本模块无调用关系, 同名纯属缩写撞车。

"""
from webtool.stock.bridge.sources._base import _err, _ok, SourceBase
from webtool.stock.bridge.sources import _symbol
import json

class SseSource(SourceBase):
    """上交所 (sse) 方法集 —— 由 sources/__init__.py 的 APIClient 混入"""

    def sse_yunhq_snap(self, code: str = "000001") -> dict:
        """上交所 yunhq.sse.com.cn 实时快照 (HTTP 非 HTTPS)

        code 收 6 位裸代码; 传 `SH600519` 会拼出 `/snap/SH600519` 取不到,
        所以先经 `_symbol.em()` 剥掉市场前缀 (沪市专用, 不做市场推断)。

        已验证:
        - 000001 上证指数 / 000300 沪深300 / 000905 中证500 / 000852 中证1000
        - 600519 茅台 / 688825 长鑫
        - 任何 6 位代码

        返回 JSON: code/date/time/snap[] = [名称, 当前, 昨收, 今开, 最高, 最低, 涨跌, 涨跌额, ...]

        走统一会话 `self._std`, 返回 200 / 313 字节 JSON。

        两个坑不要踩: 一是别为绕 `HTTPS SSL handshake failed (curl error 35)`
        改走 HTTP —— 根因是 TLS 指纹而非协议版本, curl_cffi 指纹会话已在库层面
        解决; 二是别退回裸 `curl` 子进程 —— 代价是进程 fork、无连接复用、错误
        只剩 exit code, 且绕过路由表, 全局代理一改整条就挂。
        """
        try:
            url = (f'http://yunhq.sse.com.cn:32041/v1/sh1/snap/'
                   f'{_symbol.em(code)}')
            r = self._std.get(url, timeout=self.BASE_TIMEOUT)
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            return _ok(json.loads(r.text), len(r.text))
        except Exception as e:
            return _err(f'{type(e).__name__}: {e}')

    def sse_yunhq_index(self, code: str = "000300") -> dict:
        """上交所 yunhq 指数实时快照 (HTTP)

        已验证: 000300 沪深300 / 000905 中证500 / 000852 中证1000
                / 000001 上证指数

        snap[]: 名称, 当前, 昨收, 今开, 最高, 最低, 涨跌, 涨跌幅, 成交量, 成交额, ...
        """
        return self.sse_yunhq_snap(code)

    def sse_yunhq_stock(self, code: str = "600519") -> dict:
        """上交所 yunhq 个股实时 (HTTP)"""
        return self.sse_yunhq_snap(code)