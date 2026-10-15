"""中证指数 (csindex) —— 4 个方法

端点: www.csindex.com.cn
反爬: Referer 校验

"""
from webtool.stock.bridge.sources._base import _err, _ok, SourceBase


class CsindexSource(SourceBase):
    """中证指数 (csindex) 方法集 —— 由 sources/__init__.py 的 APIClient 混入"""

    def csindex_industry_classify(self, class_type: str = "1") -> dict:
        """中证行业分类 (dataServer/queryCsiPeIndustryByclassType)

        走 /csindex-home/dataServer/queryCsiPeIndustryByclassType (反爬补强);
        /data/json/getClassifyInfo 等 SPA API 全 404

        已验证: classType=1 → size=20229 (中证行业分类数据)
        classType: 行业分类类型
        """
        try:
            r = self._std.get(
                "https://www.csindex.com.cn/csindex-home/dataServer/queryCsiPeIndustryByclassType",
                params={"classType": class_type},
                headers={"Referer": "https://www.csindex.com.cn/"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            if j.get("code") != "200":
                return _err(f"code={j.get('code')} msg={j.get('msg','')[:50]}")
            data = j.get("data", [])
            return _ok({
                "class_type": class_type, "total": len(data),
                "data": data, "sample": data[:3] if data else None,
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    def csindex_authorized_users(self) -> dict:
        """中证授权机构列表 (dataServer/queryAuthorizeddatauser)

        已验证: size=4796 含 18 行授权机构 (北京指南针科技等)
        字段: id/userName/userEnName/indexClosing/monthlyClosingWeight/
              industryClassification/bondValuation/companyWebsite/chinaOutside/chineseMainland
        """
        try:
            r = self._std.get(
                "https://www.csindex.com.cn/csindex-home/dataServer/queryAuthorizeddatauser",
                headers={"Referer": "https://www.csindex.com.cn/"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            data = j.get("data", [])
            return _ok({
                "total": len(data), "data": data,
                "sample": data[:3] if data else None,
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    def csindex_agents_list(self) -> dict:
        """中证授权机构列表 (dataServer/queryAgentslist)

        走 dataServer/queryAgentslist size=1677; 其他 SPA API 全返 size=19697

        已验证: size=1677
        """
        try:
            r = self._std.get(
                "https://www.csindex.com.cn/csindex-home/dataServer/queryAgentslist",
                headers={"Referer": "https://www.csindex.com.cn/"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            data = j.get("data", [])
            return _ok({
                "total": len(data),
                "data": data,
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    def csindex_perf(self, index_code: str = "000300",
                     start_date: str = "20260101",
                     end_date: str = "20260809") -> dict:
        """中证指数历史收益 (000300沪深300 / 000905中证500 / 000852中证1000)"""
        try:
            r = self._std.get(
                "https://www.csindex.com.cn/csindex-home/perf/index-perf",
                params={"indexCode": index_code, "startDate": start_date,
                        "endDate": end_date},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            return _ok({"code": j.get("code"), "rows": j.get("data", [])},
                       len(r.text))
        except Exception as e:
            return _err(str(e))

    # 东财 F10 扩展
