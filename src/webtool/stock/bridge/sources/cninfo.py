"""巨潮资讯 (cninfo) —— 6 个方法

端点: www.cninfo.com.cn
反爬: 先 GET 首页收 cookie 再 POST; 部分接口需 JSESSIONID (未自动化, 用 http-post 手动带)

"""
from webtool.stock.bridge.sources._base import _err, _ok, SourceBase


class CninfoSource(SourceBase):
    """巨潮资讯 (cninfo) 方法集 —— 由 sources/__init__.py 的 APIClient 混入"""

    def cninfo_company_profile(self, code: str = "688825") -> dict:
        """公司介绍"""
        try:
            r = self._std.get(
                "https://www.cninfo.com.cn/data20/companyOverview/getCompanyIntroduction",
                params={"scode": code},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            return _ok(j.get("data"), len(r.text))
        except Exception as e:
            return _err(str(e))

    def cninfo_index(self) -> dict:
        """首页 (可达性检测)"""
        try:
            r = self._std.get("https://www.cninfo.com.cn/new/index",
                              timeout=self.BASE_TIMEOUT)
            return _ok({"reachable": r.status_code == 200, "size": len(r.text)},
                       len(r.text))
        except Exception as e:
            return _err(str(e))

    # 新浪 (4 个)

    def cninfo_announcement(self, stock: str = "688825",
                            org_id: str = "9920000008",
                            page: int = 1, page_size: int = 10,
                            column: str = "sse",
                            se_date: str = "2025-01-01~2026-08-09") -> dict:
        """巨潮公告 (hisAnnouncement/query, POST + Cookie 真通)

        走 hisAnnouncement/query POST + Cookie 反爬补强;
        disclosure/detail / queryAnnouncement / fulltextSearch 返 200 但 0 字节

        参数:
          stock: 股票代码 (不带前缀, e.g. "688825" 或 "600519")
          org_id: 巨潮 orgId
            A 股主板 SH600519 → orgId="gssh0600519"
            科创板 SH688825 → orgId="9920000008" (不带 gssh 前缀)
          column: sse (沪主板) / szse (深主板/创业板) / bj (北交所) / hke (港股)
          se_date: 起始日期~结束日期
        """
        try:
            # 必须先 GET 首页拿 cookie
            self._std.get("https://www.cninfo.com.cn/new/index", timeout=self.BASE_TIMEOUT)
            r = self._std.post(
                "https://www.cninfo.com.cn/new/hisAnnouncement/query",
                data={"pageNum": page, "pageSize": page_size,
                      "column": column, "tabName": "fulltext",
                      "stock": f"{stock},{org_id}",
                      "seDate": se_date},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            announcements = j.get("announcements") or []
            return _ok({
                "stock": stock, "org_id": org_id, "total": j.get("totalAnnouncement", 0),
                "count": len(announcements),
                "announcements": announcements,
                "sample": announcements[0] if announcements else None,
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    def cninfo_fulltext_search(self, keyword: str = "贵州茅台",
                               page: int = 1, page_size: int = 10) -> dict:
        """巨潮全文搜索公告 (fulltextSearch/full, POST + Cookie 真通)

        已验证:
          "贵州茅台" → 1278 条公告
          "688825" → 17 条公告 (含 SH688825 长鑫科技)
        """
        try:
            self._std.get("https://www.cninfo.com.cn/new/index", timeout=self.BASE_TIMEOUT)
            r = self._std.post(
                "https://www.cninfo.com.cn/new/fulltextSearch/full",
                data={"pageNum": page, "pageSize": page_size,
                      "searchkey": keyword, "maxNum": 50},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            announcements = j.get("announcements") or []
            return _ok({
                "keyword": keyword, "total": j.get("totalAnnouncement", 0),
                "count": len(announcements),
                "announcements": announcements,
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    def cninfo_pdf(self, adjunct_url: str) -> dict:
        """巨潮公告 PDF 下载 (static.cninfo.com.cn, 反爬补强后真通)

        adjunctUrl 来自 cninfo_announcement/fulltext_search 返回的 adjunctUrl 字段
        例: "finalpage/2026-07-24/1225439536.PDF"

        已验证: 长鑫科技 IPO 公告 PDF size=20371136 (20MB)
        """
        try:
            url = f"https://static.cninfo.com.cn/{adjunct_url}"
            r = self._std.get(url, timeout=30)
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            return _ok({
                "url": url, "size": len(r.content),
                "content_type": r.headers.get("Content-Type", ""),
            }, len(r.content))
        except Exception as e:
            return _err(str(e))

    def cninfo_szse_stock_list(self) -> dict:
        """巨潮深交所股票全列表 (szse_stock.json, 反爬补强后真通)

        已验证: 6230 只深交所股票
        """
        try:
            r = self._std.get(
                "https://www.cninfo.com.cn/new/data/szse_stock.json",
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            stock_list = j.get("stockList", [])
            return _ok({
                "total": len(stock_list),
                "sample": stock_list[:3],
            }, len(r.text))
        except Exception as e:
            return _err(str(e))
