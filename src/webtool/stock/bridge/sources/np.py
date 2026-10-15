"""东财公告域 (np-anotice) —— 2 个方法

端点: np-anotice-stock / np-cnotice-stock
反爬: 需 Referer 指向 data.eastmoney.com; em.py 的配方层覆盖不到这两个老域

走统一 requests 会话 (`self._std`, 带路由适配器与浏览器档案), 不发裸 curl
子进程 —— 出网只留 requests 与 curl_cffi 两条通道, 多一个 shell 出口就多一处
绕过规则表的地方 (代价是多一次进程 fork、拿不到连接复用、错误只剩 exit code)。

"必须裸 curl" 的判断源于当时请求缺 Referer 且未走统一指纹, 服务端才回 SPA 壳
而不是 JSON。补上 Referer 后三个端点用统一库全部 200:
- `np-cnotice-stock.../api/content/ann` → 1546 字节 JSON
- `np-anotice-stock.../api/security/ann` → 5962 字节 JSON
- `yunhq.sse.com.cn` (sse.py) → 313 字节 JSON
"""
from webtool.stock.bridge.sources._base import _err, _ok, SourceBase
import json


_REFERER = {'Referer': 'https://data.eastmoney.com/'}

class NpSource(SourceBase):
    """东财公告域 (np-anotice) 方法集 —— 由 sources/__init__.py 的 APIClient 混入"""

    def _np_get(self, url: str) -> dict:
        """np-* 两个接口的公共出口: 统一会话 + Referer + JSON 解析。

        两个方法只差 URL, 取数与解析完全一致, 所以收口在这里。
        """
        try:
            r = self._std.get(url, headers=_REFERER, timeout=self.BASE_TIMEOUT + 2)
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            return _ok(json.loads(r.text), len(r.text))
        except Exception as e:
            return _err(f'{type(e).__name__}: {e}')

    def np_cnotice_ann(self, art_code: str = "AN202607171827064564",
                       page_index: int = 1) -> dict:
        """东方财富 np-cnotice-stock 公告正文 API

        已验证: AN202607171827064564 茅台 / AN202601071816773188 茅台

        返回字段:
        - art_code: 公告代码
        - attach_list: [{attach_url (PDF URL), attach_type, attach_size, seq}]
        - 等其他字段
        """
        return self._np_get(
            f"https://np-cnotice-stock.eastmoney.com/api/content/ann"
            f"?art_code={art_code}&client_source=web&page_index={page_index}")

    def np_notice_ann(self, stock_list: str = "600519", page_size: int = 10,
                       page_index: int = 1, ann_type: str = "A",
                       begin_time: str = "", end_time: str = "") -> dict:
        """东方财富 np-anotice-stock 公告列表 API

        已验证: 600519 茅台 / 688825 长鑫 / 000001 平安 / 301707 展芯

        ann_type: A=一般公告, B=业绩公告, C=风险提示, D=其他

        返回 JSON:
        - art_code: 公告代码 (AN202607171827064564)
        - codes: [{stock_code, short_name, market_code, ann_type, inner_code}]
        - columns: [{column_code, column_name}]
        - display_time, eiTime, notice_date, product_code, language
        """
        url = (f"https://np-anotice-stock.eastmoney.com/api/security/ann"
               f"?sr=-1&page_size={page_size}&page_index={page_index}"
               f"&ann_type={ann_type}&stock_list={stock_list}")
        if begin_time:
            url += f"&begin_time={begin_time}"
        if end_time:
            url += f"&end_time={end_time}"
        return self._np_get(url)