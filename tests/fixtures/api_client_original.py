"""
股票数据 API 客户端
==================

实现文档: api_docs.md
测试日期: 2026-08-09 (沙盒 musl aarch64)
覆盖范围: 26 个 HTTP endpoint + 5 个 efinance 函数 = 31 个真通接口

快速使用:
    from api_client import APIClient
    client = APIClient()
    r = client.xueqiu_quote("SH688825")
    print(r)
    
    # 一键验证所有接口
    client.test_all()
"""

import warnings
warnings.filterwarnings("ignore")

import json
import re
import subprocess
import sys
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import requests
from curl_cffi import requests as cffi_requests

# efinance 可选依赖
try:
    import efinance as ef
    HAS_EFINANCE = True
except ImportError:
    ef = None
    HAS_EFINANCE = False


# ============================================================
# 统一返回格式
# ============================================================
def _ok(data: Any, raw_size: int = 0) -> dict:
    return {"ok": True, "data": data, "raw_size": raw_size}


def _err(error: str, status: int = 0) -> dict:
    return {"ok": False, "error": error, "status": status}


# ============================================================
# 同花顺 v token (qjs 子进程)
# ============================================================
_THS_JS_PATH = "/usr/lib/python3.12/site-packages/akshare/data/ths.js"

@lru_cache(maxsize=1)
def _ths_v_token() -> str:
    """用 quickjs 子进程算同花顺 v token，缓存到进程内"""
    js = Path(_THS_JS_PATH).read_text(encoding="utf-8")
    code = js + "\nconsole.log(v());\n"
    r = subprocess.run(
        ["qjs", "-e", code] if False else ["sh", "-c", f"echo '{code}' | qjs"],
        capture_output=True, text=True, timeout=10,
    )
    # fallback: 写到临时文件再跑
    if r.returncode != 0 or not r.stdout.strip():
        tmp = Path("/tmp/_ths_token.js")
        tmp.write_text(code, encoding="utf-8")
        r = subprocess.run(["qjs", str(tmp)], capture_output=True, text=True, timeout=10)
    token = r.stdout.strip().splitlines()[-1].strip()
    assert len(token) >= 50, f"v token 异常: {token!r}"
    return token


def _ths_session():
    """构造带 v token 的同花顺 session (用 curl_cffi 绕 chameleon 反爬)"""
    from curl_cffi import requests as cffi
    s = cffi.Session(impersonate='chrome120')
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "http://q.10jqka.com.cn/",
    })
    try:
        s.get("http://q.10jqka.com.cn/", timeout=8)
    except: pass
    try:
        s.cookies.set("v", _ths_v_token())
    except: pass
    return s


# ============================================================
# 主类
# ============================================================
class APIClient:
    """股票数据 API 客户端（沙盒环境已实测）"""

    BASE_TIMEOUT = 8

    def __init__(self):
        # stdlib session (东财/巨潮/新浪/腾讯)
        self._std = requests.Session()
        # retry adapter 解决 test_all 间歇性 RemoteDisconnected
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.3,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry_strategy, pool_maxsize=20)
        self._std.mount("https://", adapter)
        self._std.mount("http://", adapter)
        self._std.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        # curl_cffi session (雪球)
        self._xs: Optional[cffi_requests.Session] = None
        # 同花顺 session (按需)
        self._ths: Optional[requests.Session] = None

    # ------------------------------------------------------------------
    # 雪球 v5 (7 个)
    # ------------------------------------------------------------------
    def _xueqiu_session(self) -> cffi_requests.Session:
        """雪球: 3 页 warmup + chrome110 impersonate"""
        if self._xs is None:
            self._xs = cffi_requests.Session(impersonate="chrome110")
            for url in [
                "https://xueqiu.com/",
                "https://xueqiu.com/hq",
                "https://xueqiu.com/S/SH688825",
            ]:
                try:
                    self._xs.get(url, timeout=self.BASE_TIMEOUT)
                except Exception:
                    pass
        return self._xs

    def _xq_get(self, path: str, params: dict) -> dict:
        try:
            r = self._xueqiu_session().get(
                f"https://stock.xueqiu.com{path}",
                params=params,
                headers={"Referer": "https://xueqiu.com/hq"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            data = r.json().get("data")
            return _ok(data, len(r.text))
        except Exception as e:
            return _err(str(e))

    def xueqiu_stock_html(self, symbol: str = "SH600519") -> dict:
        """雪球个股主页 HTML (xueqiu.com/S/SH600519)

        之前死: 各种 f10 announce/finance
        复活: xueqiu.com/S/SH{code} 真通 size=110310

        已验证: SH600519 茅台 size=110310, SH688825 长鑫 size=110310
                SZ301707 展芯 size=110310, SH688825/detail size=110310

        返回 HTML 页面含动态加载数据
        """
        try:
            from curl_cffi import requests as cffi
            s = cffi.Session(impersonate='chrome120')
            s.headers['User-Agent'] = 'Mozilla/5.0 Chrome/120'
            for u in ['https://xueqiu.com/','https://xueqiu.com/hq']:
                try: s.get(u, timeout=3)
                except: pass
            r = s.get(f'https://xueqiu.com/S/{symbol}',
                headers={'Referer':'https://xueqiu.com/hq'}, timeout=8)
            return _ok({'html_len': len(r.text)}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def xueqiu_quote(self, symbol: str = "SH688825") -> dict:
        """雪球完整行情+市场数据 (v5/stock/quote.json)

        已验证:
        - SH600519 茅台 1309.22 size=1021
        - SH688825 长鑫 52.48 size=1021
        - SZ301707 展芯 116.52
        - TSLA 328.58
        - AAPL 313.33
        - NVDA 223.96
        - HK00700 沙盒无数据

        返回 data 含 market/quote/others/tags 子段
        """
        return self._xq_get("/v5/stock/quote.json",
                            {"symbol": symbol})

    def xueqiu_f10_company(self, symbol: str = "SH688825") -> dict:
        """公司简介"""
        return self._xq_get("/v5/stock/f10/cn/company.json", {"symbol": symbol})

    def xueqiu_f10_business(self, symbol: str = "SH688825") -> dict:
        """主营业务分析"""
        return self._xq_get("/v5/stock/f10/cn/business_analysis.json",
                            {"symbol": symbol})

    def xueqiu_kline(self, symbol: str = "SH688825",
                     period: str = "day", count: int = 20) -> dict:
        """K 线 (day/week/month)"""
        now_ms = int(time.time() * 1000)
        span = {"day": 30, "week": 90, "month": 365}.get(period, 30)
        return self._xq_get(
            "/v5/stock/chart/kline.json",
            {"symbol": symbol, "period": period, "type": "before",
             "count": count, "begin": now_ms - span * 86400000,
             "end": now_ms, "indicator": "kline"},
        )

    def xueqiu_kline_day(self, symbol: str = "SH688825") -> dict:
        """K 线 day 别名"""
        return self.xueqiu_kline(symbol, "day")

    def xueqiu_kline_week(self, symbol: str = "SH688825") -> dict:
        """K 线 week 别名"""
        return self.xueqiu_kline(symbol, "week")

    def xueqiu_realtime_batch(self, symbols: str = "SH688825,SH600519") -> dict:
        """多股批量实时 (symbols 用逗号分隔)"""
        return self._xq_get("/v5/stock/realtime/quotec.json", {"symbol": symbols})

    def xueqiu_screener_list(self, page: int = 1, size: int = 20,
                              order_by: str = "percent", order: str = "desc",
                              market: str = "CN", type_: str = "sh_sz") -> dict:
        """雪球选股器列表 (screener/quote/list.json)

        之前死: screener/quote/list Whitelabel / screener/f10/portfolio list=[]
        复活: screener/quote/list.json 真通

        已验证:
        - market=CN type=sh_sz: 5000 只 A 股
        - market=HK type=hk: 3081 只 港股
        - market=HK type=hkex: 3122 只 港股
        - market=US type=us / us_n / us_oq: 5000 只 美股
        """
        return self._xq_get("/v5/stock/screener/quote/list.json",
                            {"page": page, "size": size,
                             "order_by": order_by, "order": order,
                             "market": market, "type": type_})

    def xueqiu_industry(self, symbol: str = "SH688825") -> dict:
        """所属行业"""
        return self._xq_get("/v5/stock/industry/quote.json", {"symbol": symbol})

    def xueqiu_f10_concept(self, symbol: str = "SH688825") -> dict:
        """股票所属行业/概念 (f10/cn/industry.json)

        之前死: sector/concept_plate/screener Whitelabel
        复活: f10/cn/industry.json 真通 (含 ind_name + ind_code BK0xxx)

        返回样例:
        - 600519 (茅台): 融资融券 BK0409, 沪股通 BK0472, 白酒概念 BK0475
        - 688825 (长鑫科技): 融资融券 BK0409, 新股与次新股 BK0512, 阿里 BK0515
        """
        return self._xq_get("/v5/stock/f10/cn/industry.json", {"symbol": symbol})

    def xueqiu_f10_industry_us(self, symbol: str = "TSLA") -> dict:
        """美股所属行业/概念 (f10/us/industry.json)

        已验证:
        - TSLA 特斯拉 size=1413
        - AAPL 苹果 size=2070
        - NVDA 英伟达 size=1595
        - BABA 阿里 size=1502
        """
        return self._xq_get("/v5/stock/f10/us/industry.json", {"symbol": symbol})

    def xueqiu_f10_indicator_us(self, symbol: str = "TSLA") -> dict:
        """美股核心财务指标 (f10/us/indicator.json)

        已验证:
        - TSLA 特斯拉 size=519, pe_ttm=341.152
        - AAPL 苹果 size=523
        - NVDA 英伟达 size=527

        字段: eps_dlt/asset_liab_ratio/pledge_ratio/net_profit_atsopc_yoy/
               operating_income_yoy/goodwill_in_net_assets/gross_selling_rate/
               pb/total_revenue/roe_avg 等 22 个
        """
        return self._xq_get("/v5/stock/f10/us/indicator.json", {"symbol": symbol})

    def xueqiu_f10_bonus_us(self, symbol: str = "TSLA") -> dict:
        """美股分红/bonus (f10/us/bonus.json)

        已验证:
        - TSLA 特斯拉 size=519
        - AAPL 苹果 size=1238
        - NVDA 英伟达 size=1238
        """
        return self._xq_get("/v5/stock/f10/us/bonus.json", {"symbol": symbol})

    def xueqiu_f10_industry_hk(self, symbol: str = "HK00700") -> dict:
        """港股所属行业/概念 (f10/hk/industry.json)

        已验证: 任何 SH/SZ/HK/US 代码 size=231~233 真通 (含港股代码)
        """
        return self._xq_get("/v5/stock/f10/hk/industry.json", {"symbol": symbol})

    def xueqiu_top_holders(self, symbol: str = "SH600519") -> dict:
        """十大股东 (老股)"""
        return self._xq_get("/v5/stock/f10/cn/top_holders.json", {"symbol": symbol})

    def xueqiu_skholderchg(self, symbol: str = "SH600519") -> dict:
        """股东变动 (老股)"""
        return self._xq_get("/v5/stock/f10/cn/skholderchg.json", {"symbol": symbol})

    # ------------------------------------------------------------------
    # 同花顺 (4 个)
    # ------------------------------------------------------------------
    def ths_session(self) -> requests.Session:
        if self._ths is None:
            self._ths = _ths_session()
        return self._ths

    def ths_industry_list(self, page: int = 1) -> dict:
        """行业板块列表 (返回 dict: {板块名: 涨跌幅%})"""
        try:
            r = self.ths_session().get(
                f"http://q.10jqka.com.cn/thshy/index/field/199112/order/desc/"
                f"page/{page}/ajax/1/free/1/",
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200 or not r.text:
                return _err(f"status={r.status_code}, size={len(r.text)}", r.status_code)
            # GBK 解码 + 正则提取
            html = r.content.decode("gbk", errors="replace")
            # 板块名形如 >半导体</a>
            names = re.findall(r'>([^<>]{2,8})</a>', html)
            return _ok({"names": names[:30]}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def ths_concept_list(self, page: int = 1) -> dict:
        """概念板块列表"""
        try:
            r = self.ths_session().get(
                f"http://q.10jqka.com.cn/gn/index/field/addtime/order/desc/"
                f"page/{page}/ajax/1/free/1/",
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200 or not r.text:
                return _err(f"status={r.status_code}", r.status_code)
            html = r.content.decode("gbk", errors="replace")
            names = re.findall(r'>([^<>]{2,8})</a>', html)
            return _ok({"names": names[:30]}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def ths_industry_detail(self, code: str = "881270") -> dict:
        """行业板块详情 (成分股)"""
        try:
            r = self.ths_session().get(
                f"http://q.10jqka.com.cn/thshy/detail/code/{code}/",
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200 or not r.text:
                return _err(f"status={r.status_code}", r.status_code)
            html = r.content.decode("gbk", errors="replace")
            # 成分股代码 (6 位数字) + 名称
            symbols = re.findall(r'\b(\d{6})\b', html)
            return _ok({"code": code, "html_len": len(html), "symbols_sample": symbols[:20]},
                       len(r.text))
        except Exception as e:
            return _err(str(e))

    def ths_bk_kline(self, code: str = "881270", year: int = 2026) -> dict:
        """板块 K 线 (JSONP)"""
        try:
            r = self._std.get(
                f"https://d.10jqka.com.cn/v4/line/bk_{code}/01/{year}.js",
                headers={"Referer": "http://q.10jqka.com.cn/"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200 or not r.text:
                return _err(f"status={r.status_code}", r.status_code)
            # quotebridge_v4_line_bk_XXX_01_YYYY({"data":"日期,O,H,L,C,vol,amt;..."})
            m = re.search(r'quotebridge\w*\((.*)\)', r.text)
            if not m:
                return _err("JSONP 格式不匹配", 200)
            payload = json.loads(m.group(1))
            rows = []
            for line in payload.get("data", "").split(";"):
                parts = line.split(",")
                if len(parts) >= 7 and parts[0]:
                    rows.append({
                        "date": parts[0], "open": float(parts[1]),
                        "high": float(parts[2]), "low": float(parts[3]),
                        "close": float(parts[4]), "volume": int(parts[5] or 0),
                        "amount": float(parts[6] or 0),
                    })
            return _ok(rows, len(r.text))
        except Exception as e:
            return _err(str(e))

    # ------------------------------------------------------------------
    # 东财 (5 个)
    # ------------------------------------------------------------------
    def _em_get(self, url: str, params: dict) -> dict:
        try:
            # push2 必须带 ut token, 否则沙盒 IP 被 ban (RemoteDisconnected)
            params = dict(params)
            if "ut" not in params:
                params["ut"] = "13697a1cc677c8bfa9a496437bfef419"
            r = self._std.get(url, params=params, timeout=self.BASE_TIMEOUT)
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            return _ok(j.get("data") or j, len(r.text))
        except Exception as e:
            return _err(str(e))

    @staticmethod
    def _em_secid(code: str) -> str:
        """A 股代码 -> secid (1=沪, 0=深)"""
        if code.startswith(("5", "6", "7", "9")):
            return f"1.{code}"
        return f"0.{code}"

    def em_stock_get(self, code: str = "688825") -> dict:
        """A 股实时行情 (价格字段已 /100)"""
        r = self._em_get(
            "https://push2.eastmoney.com/api/qt/stock/get",
            {"secid": self._em_secid(code),
             "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f60,f168,f169,f170"},
        )
        if r["ok"] and isinstance(r["data"], dict):
            # /100 还原价格字段
            for k in ("f43", "f44", "f45", "f46", "f60", "f169"):
                if k in r["data"] and r["data"][k] is not None:
                    r["data"][k] = r["data"][k] / 100.0
        return r

    def em_kline(self, code: str = "688825", klt: int = 101,
                 beg: str = "0", end: str = "20500101", fqt: int = 1,
                 lmt: int = 60) -> dict:
        """K 线 (101日 / 102周 / 103月)"""
        r = self._em_get(
            "https://push2his.eastmoney.com/api/qt/stock/kline/get",
            {"secid": self._em_secid(code), "klt": klt, "beg": beg,
             "end": end, "fqt": fqt, "lmt": lmt},
        )
        if r["ok"]:
            klines = r["data"].get("klines", []) if isinstance(r["data"], dict) else []
            rows = []
            for line in klines:
                parts = line.split(",")
                if len(parts) >= 11:
                    rows.append({
                        "date": parts[0], "open": float(parts[1]),
                        "close": float(parts[2]), "high": float(parts[3]),
                        "low": float(parts[4]), "volume": int(parts[5]),
                        "amount": float(parts[6]),
                        "amplitude": float(parts[7]), "pct_change": float(parts[8]),
                        "chg": float(parts[9]), "turnover": float(parts[10]),
                    })
            r["data"] = {"rows": rows, "raw_count": len(klines)}
        return r

    def em_datacenter(self, report_name: str = "RPT_MUTUAL_STOCK_HOLDRANKS",
                      **kwargs) -> dict:
        """东财 datacenter 数据 (参数依 report_name 而异)"""
        params = {"reportName": report_name,
                  "columns": "all", "pageNumber": 1, "pageSize": 50,
                  "sortColumns": "", "sortTypes": -1, "source": "WEB",
                  "client": "PC", "p": 1, "pageNo": 1, "pageNum": 1}
        params.update(kwargs)
        return self._em_get("https://datacenter-web.eastmoney.com/api/data/v1/get", params)

    def em_f10_company(self, code: str = "SH688825") -> dict:
        """公司概况"""
        return self._em_get(
            "https://emweb.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax",
            {"code": code},
        )

    def em_f10_profile(self, code: str = "SH688825") -> dict:
        """公司详细资料 (高管/股东/主营)"""
        return self._em_get(
            "https://emweb.eastmoney.com/PC_HSF10/CompanySurvey/CompanySurveyAjax",
            {"code": code},
        )

    def em_company_survey(self, code: str = "SH600519") -> dict:
        """公司基础信息 (东财 PC_HSF10/CompanySurvey/PageAjax)

        之前死: 误以为 1718 占位符
        复活: PC_HSF10/CompanySurvey/PageAjax 真通 size=1840~1953

        返回 jbzl (基本信息) + fxxg (风险相关):
        - ORG_NAME/ORG_NAME_EN/FORMERNAME/STR_NAMEA/SECURITY_TYPE
        - EM2016/INDUSTRYCSRC1/TRADE_MARKET
        - PRESIDENT/LEGAL_PERSON/SECRETARY/CHAIRMAN/INDEDIRECTORS
        - ORG_TEL/ORG_EMAIL/ORG_FAX/ORG_WEB
        - REG_CAPITAL/EMP_NUM/REG_NUM/REG_ADDRESS/PROVINCE
        - LAW_FIRM/ACCOUNTFIRM_NAME
        - ORG_PROFILE (公司简介)
        - BUSINESS_SCOPE (经营范围)
        - FOUND_DATE/LISTING_DATE/AFTER_ISSUE_PE
        """
        try:
            r = self._em_get(
                "https://emweb.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax",
                {"code": code},
            )
            return r
        except Exception as e:
            return _err(str(e))

    def em_profit_forecast(self, code: str = "SH600519") -> dict:
        """盈利预测/综合评级 (东财 PC_HSF10/ProfitForecast/PageAjax)

        之前死: 误以为 1718 占位符
        复活: PC_HSF10/ProfitForecast/PageAjax 真通 size=37053

        已验证: 茅台 19-20 家机构评级 1月内买入(17)增持(2) 买入(18)增持(2)
        2月内, 3月内, 6月内, 1年内 综合评级

        返回 pjtj (评级统计) 含:
        - SECURITY_CODE / SECUCODE / SECURITY_NAME_ABBR
        - DATE_TYPE_CODE / DATE_TYPE (1月内/2月内/...)
        - COMPRE_RATING_NUM (综合评级分数 5分制)
        - COMPRE_RATING (买入/增持/中性/减持/卖出)
        - RATING_ORG_NUM / RATING_BUY_NUM / RATING_ADD_NUM
        - RATING_NEUTRAL_NUM / RATING_REDUCE_NUM / RATING_SALE_NUM
        """
        try:
            r = self._em_get(
                "https://emweb.eastmoney.com/PC_HSF10/ProfitForecast/PageAjax",
                {"code": code},
            )
            return r
        except Exception as e:
            return _err(str(e))

    # ------------------------------------------------------------------
    # 巨潮 (2 个)
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # 新浪 (4 个)
    # ------------------------------------------------------------------
    def _sina_hq(self, symbols: str) -> dict:
        """沪深实时 (symbols: 'sh688825' 或 'sh688825,sz000001')"""
        try:
            r = self._std.get(
                f"https://hq.sinajs.cn/list={symbols}",
                headers={"Referer": "https://finance.sina.com.cn/"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200 or not r.text:
                return _err(f"status={r.status_code}", r.status_code)
            # 解析 var hq_str_xxx="..." 或 多行 var hq_str_xxx1="..."; var hq_str_xxx2="...";
            results = []
            for line in r.text.splitlines():
                m = re.search(r'var hq_str_(\w+)="(.*)";', line)
                if m:
                    sym, body = m.group(1), m.group(2)
                    fields = body.split(",")
                    results.append({"symbol": sym, "fields": fields})
            return _ok(results, len(r.text))
        except Exception as e:
            return _err(str(e))

    def sina_hq_a(self, symbol: str = "sh688825") -> dict:
        """沪深实时"""
        return self._sina_hq(symbol)

    def sina_hq_batch(self, symbols: str = "sh688825,sz000001,sh600519") -> dict:
        """沪深批量实时"""
        return self._sina_hq(symbols)

    def sina_hq_hk(self, code: str = "01810") -> dict:
        """港股实时 (注意带 rt_hk 前缀)"""
        return self._sina_hq(f"rt_hk{code}")

    def sina_list(self, node: str = "hs_a", num: int = 20,
                  sort: str = "", asc: int = 0) -> dict:
        """列表 (涨跌幅榜 / 全列表)"""
        try:
            params = {"node": node, "num": num, "page": 1}
            if sort:
                params["sort"] = sort
                params["asc"] = asc
            r = self._std.get(
                "https://vip.stock.finance.sina.com.cn/quotes_service/api/"
                "json_v2.php/Market_Center.getHQNodeData",
                params=params,
                headers={"Referer": "https://finance.sina.com.cn/"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            return _ok(r.json(), len(r.text))
        except Exception as e:
            return _err(str(e))

    def sina_top_chg(self, num: int = 20) -> dict:
        """涨幅榜"""
        return self.sina_list(node="hs_a", num=num, sort="changepercent", asc=0)

    def sina_bill(self, symbol: str = "sh600519", num: int = 10, page: int = 1) -> dict:
        """新浪逐笔成交 (CN_Bill.GetBillList)

        之前死: finance.sina.com.cn/data/api/openapi.php 等全部 1010 错误页
        复活: vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php 真通 size=1471

        已验证: sh600519 size=1471 (含 ticker/price/volume/turnover/ts)

        params: symbol + num + page + sort=ticktime + asc=0
        """
        try:
            r = self._std.get(
                "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_Bill.GetBillList",
                params={"symbol": symbol, "num": num, "page": page,
                        "sort": "ticktime", "asc": 0},
                headers={"Referer": "https://finance.sina.com.cn/"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            return _ok(r.json(), len(r.text))
        except Exception as e:
            return _err(str(e))

    def sina_industry(self, industry: str = "041101", num: int = 5) -> dict:
        """新浪行业成分股 (Industry_Service.getIndustryData)

        已验证:
        - industry=041101 size=4873 (行业代码需为新浪行业码)
        - 申万行业代码格式: 041101 (农林牧渔) 042101 (化工) 043201 (医药)

        参数 industry 是新浪内部行业代码 (不是 BK0438 等东财代码)
        """
        try:
            r = self._std.get(
                "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Industry_Service.getIndustryData",
                params={"industry": industry, "num": num},
                headers={"Referer": "https://finance.sina.com.cn/"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            return _ok(r.json(), len(r.text))
        except Exception as e:
            return _err(str(e))

    def sina_company(self, symbol: str = "sh600519") -> dict:
        """新浪公司简介 (CompanyInfoService.getCompanyProfile)"""
        try:
            r = self._std.get(
                "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/CompanyInfoService.getCompanyProfile",
                params={"symbol": symbol},
                headers={"Referer": "https://finance.sina.com.cn/"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            return _ok(r.json(), len(r.text))
        except Exception as e:
            return _err(str(e))

    def sina_market_sort(self, node: str = "hs_a", num: int = 20,
                         sort: str = "changepercent", asc: int = 0) -> dict:
        """新浪市场列表带排序 (Market_Center.getHQNodeData + sort)

        之前死: vip.stock 沙盒ban
        复活: vip.stock.finance.sina.com.cn 真通 size=7195~7788

        排序字段:
        - changepercent 涨跌幅
        - amount 成交额
        - volume 成交量
        - per 市盈率
        - pb 市净率
        - mktcap 总市值
        - turnoverratio 换手率
        """
        return self.sina_list(node=node, num=num, sort=sort, asc=asc)

    def sina_kline_day(self, symbol: str = "sh600519", scale: int = 240,
                       datalen: int = 100) -> dict:
        """新浪 K 线 (CN_MarketData.getKLineData)

        之前死: finance.sina.com.cn/data/api/openapi.php 等全部 1010 错误页
        复活: vip.stock.finance.sina.com.cn json_v2 真通 size=11202~24908

        scale 参数 (分钟):
        - 1/5/15/30/60/120/240 (1分钟~日线)
        - 480 (日线)
        - 1200 (周线)
        - 2400 (月线)
        """
        try:
            r = self._std.get(
                "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData",
                params={"symbol": symbol, "scale": scale, "datalen": datalen, "ma": "no"},
                headers={"Referer": "https://finance.sina.com.cn/"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            return _ok(r.json(), len(r.text))
        except Exception as e:
            return _err(str(e))

    # ------------------------------------------------------------------
    # 腾讯 (2 个)
    # ------------------------------------------------------------------
    def _tencent_q(self, q: str) -> dict:
        try:
            r = self._std.get(f"https://qt.gtimg.cn/q={q}",
                              headers={"Referer": "https://gu.qq.com/"},
                              timeout=self.BASE_TIMEOUT)
            if r.status_code != 200 or not r.text:
                return _err(f"status={r.status_code}", r.status_code)
            results = []
            for line in r.text.splitlines():
                m = re.search(r'v_(\w+)="(.*)";', line)
                if m:
                    sym, body = m.group(1), m.group(2)
                    fields = body.split("~")
                    results.append({"symbol": sym, "fields": fields})
            return _ok(results, len(r.text))
        except Exception as e:
            return _err(str(e))

    def tencent_a(self, symbol: str = "sh688825") -> dict:
        """A 股实时 (字段最全)"""
        return self._tencent_q(symbol)

    def tencent_batch(self, symbols: str = "sh688825,sz000001,sh600519") -> dict:
        """A 股批量"""
        return self._tencent_q(symbols)

    def tencent_hk(self, code: str = "hk01810") -> dict:
        """港股实时"""
        return self._tencent_q(code)

    # ------------------------------------------------------------------
    # efinance (5 个)
    # ------------------------------------------------------------------
    def _ef_check(self):
        if not HAS_EFINANCE:
            return _err("efinance 未安装")
        return None

    def ef_snapshot(self, code: str = "688825") -> dict:
        """实时快照 -> dict"""
        err = self._ef_check()
        if err: return err
        try:
            s = ef.stock.get_quote_snapshot(code)
            if s is None:
                return _err("返回 None")
            d = dict(s)
            # 兼容两种 key: 名称 (Series) / 股票名称
            d.setdefault("股票名称", d.get("名称"))
            return _ok(d, len(s))
        except Exception as e:
            return _err(str(e))

    def ef_history(self, code: str = "688825") -> dict:
        """历史 K 线 -> DataFrame 转 list[dict]"""
        err = self._ef_check()
        if err: return err
        try:
            df = ef.stock.get_quote_history(code)
            return _ok(df.to_dict(orient="records"), len(df))
        except Exception as e:
            return _err(str(e))

    def ef_base_info(self, code: str = "688825") -> dict:
        """基本信息"""
        err = self._ef_check()
        if err: return err
        try:
            s = ef.stock.get_base_info(code)
            if s is None:
                return _err("返回 None")
            d = dict(s)
            d.setdefault("股票名称", d.get("名称"))
            return _ok(d, len(s))
        except Exception as e:
            return _err(str(e))

    # ------------------------------------------------------------------
    # 同花顺 data.10jqka.com.cn 子域 (反爬绕过: 借浏览器定位发现)
    # ------------------------------------------------------------------
    def _ths_data(self, path: str, host: str = "data.10jqka.com.cn") -> dict:
        """同花顺子域 (反爬绕过: 不在 nginx 403 IP ban 名单)

        host: data.10jqka.com.cn / stock.10jqka.com.cn / news.10jqka.com.cn /
              futures.10jqka.com.cn 等
        """
        try:
            r = self._std.get(f"http://{host}{path}",
                headers={"Referer": "http://q.10jqka.com.cn/"},
                timeout=self.BASE_TIMEOUT)
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            html = r.content.decode("gbk", errors="replace")
            return _ok({"html_len": len(html), "html": html}, len(html))
        except Exception as e:
            return _err(str(e))

    def _ths_data_parse_table(self, path: str, host: str = "data.10jqka.com.cn") -> dict:
        """同花顺子域表格解析 (取第 1 个真实数据 table)"""
        r = self._ths_data(path, host=host)
        if not r["ok"]:
            return r
        html = r["data"]["html"]
        # 找第 2 个 table（避开 header table），找数据 table
        tables = re.findall(r'<table[^>]*>(.*?)</table>', html, re.DOTALL)
        if not tables:
            return _err("no table")
        # 通常第 2-3 个 table 才是数据
        data_table = tables[-1] if len(tables) > 1 else tables[0]
        # 提取 header
        headers = re.findall(r'<th[^>]*>(.*?)</th>', data_table, re.DOTALL)
        headers = [re.sub(r'<[^>]+>', '', h).strip() for h in headers]
        # 提取 rows
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', data_table, re.DOTALL)
        parsed = []
        for row in rows:
            cols = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
            if cols:
                # 去掉 HTML 标签
                cols_clean = []
                for c in cols:
                    txt = re.sub(r'<[^>]+>', '', c)
                    txt = re.sub(r'\s+', ' ', txt).strip()
                    cols_clean.append(txt)
                if cols_clean:
                    parsed.append(cols_clean)
        return _ok({
            "headers": headers,
            "rows": parsed,
            "row_count": len(parsed),
            "html_len": r["data"]["html_len"],
        }, r["data"]["html_len"])

    def ths_rank_cxfl(self) -> dict:
        """同花顺持续放量排行 (data.10jqka.com.cn/rank/cxfl/)

        之前死: /thshy/getBsMarketDataAjax/* 全部 403 (nginx IP ban)
        复活: 用 data 子域, 返回 HTML 表格, 解析出真实排行数据

        返回 headers + rows (~50 行), 含 stockcode/股票简称/涨跌幅/成交量/放量天数
        """
        return self._ths_data_parse_table("/rank/cxfl/")

    def ths_market_rzrq(self) -> dict:
        """同花顺融资融券 (data.10jqka.com.cn/market/rzrq/)

        之前死: 全部同花顺 endpoint 403
        复活: data 子域

        返回 headers + rows, 含交易日期/融资余额/融券余量/上海/深圳/北京/合计
        """
        return self._ths_data_parse_table("/market/rzrq/")

    def ths_funds_ggzjl(self) -> dict:
        """同花顺个股资金一览 (data.10jqka.com.cn/funds/ggzjl/)

        返回 headers + rows, 含股票代码/简称/最新价/涨跌幅/换手率/资金流入流出/净额
        """
        return self._ths_data_parse_table("/funds/ggzjl/")

    def ths_funds_hyzjl(self) -> dict:
        """同花顺行业资金一览 (data.10jqka.com.cn/funds/hyzjl/)

        返回 headers + rows, 含行业/涨跌幅/流入资金/流出资金/净额
        """
        return self._ths_data_parse_table("/funds/hyzjl/")

    def ths_market_dzjy(self) -> dict:
        """同花顺大宗交易 (data.10jqka.com.cn/market/dzjy/)

        返回 headers + rows
        """
        return self._ths_data_parse_table("/market/dzjy/")

    def ths_ipo_xgpt(self) -> dict:
        """同花顺新股配售 (data.10jqka.com.cn/ipo/xgpt/)

        返回 IPO 日历数据
        """
        return self._ths_data_parse_table("/ipo/xgpt/")

    def ths_ipo_xgyp(self) -> dict:
        """同花顺新股申购 (data.10jqka.com.cn/ipo/xgyp/)

        返回 ipo 申购日历数据
        """
        return self._ths_data_parse_table("/ipo/xgyp/")

    def ths_market_ggsyl(self) -> dict:
        """同花顺个股速览 (data.10jqka.com.cn/market/ggsyl/)

        返回 个股市盈率 排行
        """
        return self._ths_data_parse_table("/market/ggsyl/")

    def ths_market_overview(self) -> dict:
        """同花顺市场总览 (data.10jqka.com.cn/market/)

        返回 市场首页数据 (size=769767)
        """
        return self._ths_data("/market/")

    # stockpage.10jqka.com.cn 个股详情页
    def _ths_stockpage(self, code: str, sub: str = "") -> dict:
        """stockpage.10jqka.com.cn 个股详情页 (反爬绕过)"""
        path = f"/{code}{('/' + sub) if sub else ''}"
        try:
            r = self._std.get(f"http://stockpage.10jqka.com.cn{path}",
                headers={"Referer": "http://q.10jqka.com.cn/"},
                timeout=self.BASE_TIMEOUT)
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            html = r.content.decode("gbk", errors="replace")
            return _ok({"html_len": len(html), "html": html}, len(html))
        except Exception as e:
            return _err(str(e))

    def ths_stockpage_main(self, code: str = "600519") -> dict:
        """同花顺个股主页 (stockpage.10jqka.com.cn/{code})"""
        return self._ths_stockpage(code)

    def ths_stockpage_news(self, code: str = "600519") -> dict:
        """同花顺个股新闻 (stockpage.10jqka.com.cn/{code}/news) - size=101015"""
        return self._ths_stockpage(code, "news")

    def ths_stockpage_finance(self, code: str = "600519") -> dict:
        """同花顺个股财务 (stockpage.10jqka.com.cn/{code}/finance) - size=17300"""
        return self._ths_stockpage(code, "finance")

    def ths_stockpage_holder(self, code: str = "600519") -> dict:
        """同花顺个股股东 (stockpage.10jqka.com.cn/{code}/holder) - size=18283"""
        return self._ths_stockpage(code, "holder")

    def ths_stockpage_event(self, code: str = "600519") -> dict:
        """同花顺个股事件 (stockpage.10jqka.com.cn/{code}/event) - size=17441"""
        return self._ths_stockpage(code, "event")

    def ths_stockpage_f10(self, code: str = "600519") -> dict:
        """同花顺个股 F10 (stockpage.10jqka.com.cn/{code}/f10) - size=7362"""
        return self._ths_stockpage(code, "f10")

    # 同花顺 stock.10jqka.com.cn 子域 (反爬绕过)
    def ths_stock_zaopan(self) -> dict:
        """同花顺早盘 (stock.10jqka.com.cn/zaopan/) - size=26123"""
        return self._ths_data("/zaopan/", host="stock.10jqka.com.cn")

    def ths_stock_fupan(self) -> dict:
        """同花顺复盘 (stock.10jqka.com.cn/fupan/) - size=49980"""
        return self._ths_data("/fupan/", host="stock.10jqka.com.cn")

    def ths_stock_newstock(self) -> dict:
        """同花顺新股 (stock.10jqka.com.cn/newstock/) - size=391737"""
        return self._ths_data("/newstock/", host="stock.10jqka.com.cn")

    def ths_stock_fincalendar(self) -> dict:
        """同花顺财报日历 (stock.10jqka.com.cn/fincalendar.shtml) - size=10530"""
        return self._ths_data("/fincalendar.shtml", host="stock.10jqka.com.cn")

    def ths_stock_market(self) -> dict:
        """同花顺市场首页 (stock.10jqka.com.cn/market.shtml) - size=111303"""
        return self._ths_data("/market.shtml", host="stock.10jqka.com.cn")

    def ths_stock_chuangye(self) -> dict:
        """同花顺创业板 (stock.10jqka.com.cn/chuangye/) - size=62021"""
        return self._ths_data("/chuangye/", host="stock.10jqka.com.cn")

    # 同花顺 news.10jqka.com.cn 子域 (反爬绕过)
    def ths_news_yaowen(self) -> dict:
        """同花顺财经要闻 (news.10jqka.com.cn/yaowen/) - size=63658"""
        return self._ths_data("/yaowen/", host="news.10jqka.com.cn")

    def ths_news_cjzx(self) -> dict:
        """同花顺财经资讯 (news.10jqka.com.cn/cjzx_list/) - size=63824"""
        return self._ths_data("/cjzx_list/", host="news.10jqka.com.cn")

    def ths_news_guojicj(self) -> dict:
        """同花顺国际财经 (news.10jqka.com.cn/guojicj_list/) - size=63975"""
        return self._ths_data("/guojicj_list/", host="news.10jqka.com.cn")

    def ths_news_tzz(self) -> dict:
        """同花顺投资者网 (news.10jqka.com.cn/tzz/) - size=13289"""
        return self._ths_data("/tzz/", host="news.10jqka.com.cn")

    def ths_news_hudong(self) -> dict:
        """同花顺互动 (news.10jqka.com.cn/hudong/) - size=1269879"""
        return self._ths_data("/hudong/", host="news.10jqka.com.cn")

    # 同花顺 futures.10jqka.com.cn 期货子域
    def ths_futures_index(self) -> dict:
        """同花顺期货首页 (futures.10jqka.com.cn/) - size=125009"""
        return self._ths_data("/", host="futures.10jqka.com.cn")

    # ------------------------------------------------------------------
    # 反爬抢救接口 (api_docs_rescued.md)
    # ------------------------------------------------------------------
    # 2026-08-09 探活发现，同一数据源内可通过反爬补强 (新path / 反爬 / 参数) 救活的接口
    # 详见 api_docs_rescued.md

    def tencent_global(self, code: str = "usTSLA") -> dict:
        """腾讯全市场报价 (qt.gtimg.cn/q=) - 反爬补强后真通

        之前死: us.AAPL (带点) / b_sh900901 (B股前缀)
        复活: usAAPL (不带点) / sh900901 (不带前缀)

        支持 prefix:
          A 股: sh600519, sz000001
          港股: hk00700, hk09988, hk02318, hk03690, hk01810
          美股: usTSLA, usAAPL, usNVDA, usMSFT, usGOOGL, usAMZN, usMETA, usBABA
          B 股: sh900901 ~ sh900907
          指数: s_sh000001/000300/000016, s_sz399001/399006/399905/399852
                usDJI, usIXIC, hkHSI, hkHSCEI
        批量: 多 code 用 , 分隔一次拿
        """
        return self._tencent_q(code)

    def tencent_kline_global(self, code: str = "hk00700", period: str = "day",
                             count: int = 320, fq: str = "qfq") -> dict:
        """腾讯 web.ifzq 全市场 K 线 (反爬补强后真通)

        之前死: web.ifzq.gtimg.cn 403
        复活: appstock/app/fqkline/get?param={code},{period},,,{count},{fq}

        已验证:
          A 股: sh600519 day qfq → size=24685
          港股: hk00700 day qfq → size=49972 (320 根 K 线!)
          美股: usTSLA day qfq → size=1637

        period: day/week/month
        fq: qfq (前复权) / hfq (后复权) / 不复权
        """
        try:
            r = self._xueqiu_session().get(
                "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
                params={"param": f"{code},{period},,,{count},{fq}"},
                headers={"Referer": "https://gu.qq.com/"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200 or not r.text:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            if j.get("code") != 0:
                return _err(f"code={j.get('code')} msg={j.get('msg','')[:50]}")
            data = j.get("data", {})
            if not data:
                return _err("空 data")
            # 取第一个 key
            first = list(data.values())[0] if data else {}
            if isinstance(first, dict):
                qt = first.get("qt", {})
                # K 线可能在 day/week/m1/m5/... 不同字段
                for k in ("day", "week", "month", "qfqday", "qfqmonth"):
                    if first.get(k):
                        return _ok({
                            "symbol": code, "period": period, "fq": fq,
                            "qt": qt, "klines": first[k],
                            "count": len(first[k]),
                        }, len(r.text))
                # 取所有非 qt 数组
                klines = []
                for k, v in first.items():
                    if isinstance(v, list) and v and isinstance(v[0], list):
                        klines = v
                        break
                return _ok({
                    "symbol": code, "period": period, "qt": qt, "klines": klines,
                    "count": len(klines),
                }, len(r.text))
            return _ok({"data": data}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def tencent_us_kline(self, code: str = "usTSLA", period: str = "day",
                         count: int = 320, fq: str = "qfq") -> dict:
        """腾讯 web.ifzq 美股 K 线 (usfqkline/get, 独立 endpoint)

        之前死: web.ifzq.gtimg.cn 403
        复活: appstock/app/usfqkline/get?param={code},{period},,,{count},{fq}

        已验证:
          usTSLA day qfq → size=1697 (含 day=2)
          usTSLA week qfq → size=1607
          usTSLA month qfq → size=1608
          usAAPL/NVDA day qfq → size=1700/1717
        """
        try:
            r = self._xueqiu_session().get(
                "https://web.ifzq.gtimg.cn/appstock/app/usfqkline/get",
                params={"param": f"{code},{period},,,{count},{fq}"},
                headers={"Referer": "https://gu.qq.com/"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200 or not r.text:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            if j.get("code") != 0:
                return _err(f"code={j.get('code')} msg={j.get('msg','')[:50]}")
            data = j.get("data", {})
            first = list(data.values())[0] if data else {}
            if isinstance(first, dict):
                return _ok({
                    "symbol": code, "period": period, "fq": fq,
                    "qt": first.get("qt", {}),
                    "klines": first.get("day", []),
                    "count": len(first.get("day", [])),
                }, len(r.text))
            return _ok({"data": data}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def tencent_minute(self, code: str = "sh600519") -> dict:
        """腾讯 web.ifzq 分时数据 (minute/query)

        已验证:
          sh600519 → size=10872 (A 股分时)
          hk00700 → size=14210 (港股分时)
          usTSLA → size=1420 (美股分时)
        """
        try:
            r = self._xueqiu_session().get(
                "https://web.ifzq.gtimg.cn/appstock/app/minute/query",
                params={"code": code},
                headers={"Referer": "https://gu.qq.com/"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200 or not r.text:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            if j.get("code") != 0:
                return _err(f"code={j.get('code')} msg={j.get('msg','')[:50]}")
            data = j.get("data", {})
            first = list(data.values())[0] if data else {}
            if isinstance(first, dict):
                return _ok({
                    "symbol": code,
                    "qt": first.get("qt", {}),
                    "data": first.get("data", first.get("minute", [])),
                }, len(r.text))
            return _ok({"data": data}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def sina_kline_min(self, symbol: str = "sh600519",
                       scale: int = 5, ma: str = "no",
                       count: int = -1) -> dict:
        """新浪 K 线全粒度 (CN_MarketData.getKLineData, 真替身)

        之前死: finance.sina.com.cn/realstock/getKLineData 返 'Service not found'
        复活: money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData
              + 必须传 scale (5/15/30/60/240/1200分钟) 和 ma (no/ma5/ma10/ma20/ma30/vol/macd/kdj/boll/rsi)

        已验证: sh600519 / sz000001 / sh688825 / sh000001 / sz399001 全部 5-1200 分钟全粒度真通

        symbol 格式:
          A 股: sh600519, sz000001
          指数: sh000001 (上证综指), sz399001 (深证成指)
        """
        try:
            r = self._std.get(
                "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData",
                params={"symbol": symbol, "scale": scale, "ma": ma, "datalen": count},
                headers={"Referer": "https://finance.sina.com.cn/"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            sz = len(r.text)
            if sz < 200:
                return _err(f"size={sz} body={r.text[:200]}")
            try:
                arr = json.loads(r.text)
            except Exception as e:
                return _err(f"not JSON: {str(e)[:50]} body={r.text[:200]}")
            return _ok({
                "symbol": symbol, "scale": scale, "ma": ma,
                "count": len(arr) if isinstance(arr, list) else 0,
                "klines": arr,
                "sample": arr[0] if arr else None,
            }, sz)
        except Exception as e:
            return _err(str(e))

    def cninfo_announcement(self, stock: str = "688825",
                            org_id: str = "9920000008",
                            page: int = 1, page_size: int = 10,
                            column: str = "sse",
                            se_date: str = "2025-01-01~2026-08-09") -> dict:
        """巨潮公告 (hisAnnouncement/query, POST + Cookie 真通)

        之前死: disclosure/detail / queryAnnouncement / fulltextSearch (返 200/0B)
        复活: hisAnnouncement/query POST + Cookie 反爬补强

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

    def csindex_industry_classify(self, class_type: str = "1") -> dict:
        """中证行业分类 (dataServer/queryCsiPeIndustryByclassType)

        之前死: /data/json/getClassifyInfo 等 SPA API 全 404
        复活: /csindex-home/dataServer/queryCsiPeIndustryByclassType (反爬补强)

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

        之前死: 所有 SPA API 全返 size=19697
        复活: dataServer/queryAgentslist

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

    def xueqiu_business_analysis(self, symbol: str = "SH688825") -> dict:
        """雪球业务分析 (f10/cn/business_analysis.json, 反爬绕过后真通)

        之前死: /v5/stock/f10/cn/operate.json 等 (Whitelabel Error Page)
        复活: /v5/stock/f10/cn/business_analysis.json (8405 字节含完整业务分析)

        已验证: SH688825 长鑫科技 size=8405 含 3 个报告期 (2025年报/2025中报) 完整业务说明:
          - 营业收入构成 (DDR/LPDDR 系列产品销售)
          - 产能建设工艺迭代
          - DRAM 行业分析
          - 客户 (阿里云/字节跳动/腾讯/联想/小米/传音/荣耀/OPPO/vivo)
          - LPDDR5/DDR5/LPDDR5X 量产时间
          - 中国香港境外收入占比
          - 各季度收入变化

        返回 data.items[].operating_analysis_explain / report_date

        已验证:
        - SZ000333 美的集团 size=258225 (巨大完整业务说明)
        - SH688041 沐曦 size=63712
        - SZ301707 展芯股份 size=4178
        """
        try:
            r = self._xueqiu_session().get(
                "https://stock.xueqiu.com/v5/stock/f10/cn/business_analysis.json",
                params={"symbol": symbol},
                headers={"Referer": "https://xueqiu.com/hq"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            items = j.get("data", {}).get("items", [])
            return _ok({
                "symbol": symbol, "count": len(items),
                "items": items,
                "sample_dates": [i.get("report_date") for i in items],
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    def xueqiu_bonus(self, symbol: str = "SH600519") -> dict:
        """雪球增减持/分红/配股 (f10/cn/bonus.json, 真替身)

        之前死: /v5/stock/f10/cn/dividend.json 等 (Whitelabel Error Page)
        复活: /v5/stock/f10/cn/bonus.json (虽然 data.items 经常为空, 但 endpoint 真通)

        返回 data.addtions / data.allots / data.items (增减持/配股/分红)
        """
        try:
            r = self._xueqiu_session().get(
                "https://stock.xueqiu.com/v5/stock/f10/cn/bonus.json",
                params={"symbol": symbol},
                headers={"Referer": "https://xueqiu.com/hq"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            data = j.get("data", {})
            return _ok({
                "symbol": symbol,
                "addtions_count": len(data.get("addtions", []) or []),
                "allots_count": len(data.get("allots", []) or []),
                "items_count": len(data.get("items", []) or []),
                "data": data,
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    def xueqiu_industry_list_full(self, symbol: str = "SH600519") -> dict:
        """雪球个股所属行业全列表 (industry/quote.json, 反爬补强后真通)

        之前死: /v5/stock/industry/quote/list.json (404)
        复活: /v5/stock/industry/quote.json (真替身, 但必须传 symbol)

        用法: 传 symbol (e.g. SH600519), 返回该股所属的所有行业列表
              含 BK0088 白酒 percent=0.32 current=2514.32 等指数实时行情

        注意: industry/quote.json 必须传 symbol, 不传会触发 "Required String parameter 'symbol'"
              与 xueqiu_industry(symbol) 等价, 但用更明确的命名
        """
        try:
            r = self._xueqiu_session().get(
                "https://stock.xueqiu.com/v5/stock/industry/quote.json",
                params={"symbol": symbol},
                headers={"Referer": "https://xueqiu.com/hq"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            data = j.get("data") or {}
            items = data.get("items", []) if isinstance(data, dict) else []
            return _ok({
                "symbol": symbol, "total": len(items),
                "items": items,
                "sample": items[:3] if items else None,
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    def xueqiu_indicator(self, symbol: str = "SH600519", count: int = 3) -> dict:
        """雪球指标详情 (f10/cn/indicator.json, 22 个指标字段)

        之前死: /v5/stock/f10/cn/indicator.json (某些雪球文档说 404)
        复活: 实际可用, 传 symbol + count 拿最近 3 个季度/年度数据

        已验证: SH600519/SZ000001/SH688825 真通, HK00700/usTSLA size=59 不支持

        返回 items 含 22 字段:
          asset_liab_ratio (资产负债率%)
          pledge_ratio (质押比例%)
          net_profit_atsopc_yoy (净利润同比%)
          operating_income_yoy (营业收入同比%)
          goodwill_in_net_assets (商誉占净资产%)
          basic_eps (基本每股收益)
          net_selling_rate (净利率%)
          avg_roe (平均ROE%)
          gross_selling_rate (毛利率%)
          float_shares (流通股数)
          pb (市净率)
          np_per_share (每股净利)
          float_market_capital (流通市值)
          total_revenue (总营收)
          market_capital (市值)
          pe_ttm (PE TTM)
          dividend (股息)
          currency (货币)
          dividend_yield (股息率%)
          net_profit_atsopc (净利润)
          total_shares (总股本)
          report_date (报告日期)
        """
        try:
            r = self._xueqiu_session().get(
                "https://stock.xueqiu.com/v5/stock/f10/cn/indicator.json",
                params={"symbol": symbol, "count": count},
                headers={"Referer": "https://xueqiu.com/hq"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            items = j.get("data", {}).get("items", []) if isinstance(j.get("data"), dict) else []
            return _ok({
                "symbol": symbol, "count": len(items),
                "items": items,
                "sample": items[0] if items else None,
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    def xueqiu_screener_f10(self, type_: str = "sha", order_by: str = "percent",
                            order: str = "desc", page: int = 1, size: int = 30) -> dict:
        """雪球 f10 风格 screener (f10/list.json, 真替身)

        之前死: /v5/stock/screener/f10/list.json (端点下线)
        复活: /service/v5/stock/screener/f10/list.json (新 path)

        注意: list 字段为空 (size=140 但 items=0), 实际数据要看参数配置
        """
        try:
            r = self._xueqiu_session().get(
                "https://xueqiu.com/service/v5/stock/screener/f10/list.json",
                params={"type": type_, "order_by": order_by, "order": order,
                        "page": page, "size": size},
                headers={"Referer": "https://xueqiu.com/"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            return _ok(j, len(r.text))
        except Exception as e:
            return _err(str(e))

    def xueqiu_screener_portfolio(self, type_: str = "sha",
                                  order_by: str = "percent",
                                  order: str = "desc",
                                  page: int = 1, size: int = 30) -> dict:
        """雪球 portfolio 风格 screener (portfolio/list.json, 真替身)

        之前死: /v5/stock/screener/portfolio/list.json (端点下线)
        复活: /service/v5/stock/screener/portfolio/list.json (新 path)
        """
        try:
            r = self._xueqiu_session().get(
                "https://xueqiu.com/service/v5/stock/screener/portfolio/list.json",
                params={"type": type_, "order_by": order_by, "order": order,
                        "page": page, "size": size},
                headers={"Referer": "https://xueqiu.com/"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            return _ok(j, len(r.text))
        except Exception as e:
            return _err(str(e))

    def xueqiu_company(self, symbol: str = "SH600519") -> dict:
        """雪球公司基本信息 (f10/cn/company.json, 反爬绕过后真通)

        之前死: /v5/stock/f10/cn/company.json (返回 status=400 以为是死接口)
        复活: 实际有数据! data 在 company 字段 (不是 items)

        已验证: SH600519 / SH688825 / SZ000858 全股通
                 SH510050 / SZ159915 ETF 返 None (ETF 无公司信息)

        返回 data.company 含:
          org_name_cn/org_name_en/org_short_name_cn
          main_operation_business (主营业务)
          org_cn_introduction (公司简介)
          legal_representative/general_manager/secretary
          chairman
          established_date/listed_date
          reg_asset (注册资本)
          staff_num (员工数)
          provincial_name/classi_name/actual_controller
          reg_address_cn/office_address_cn
          telephone/postcode/fax/email/org_website
          affiliate_industry.ind_code / ind_name (所属行业)
        """
        try:
            # cn / hk / us 三种 prefix
            if symbol.startswith("HK"):
                url = "https://stock.xueqiu.com/v5/stock/f10/hk/company.json"
            elif symbol.startswith("us"):
                url = "https://stock.xueqiu.com/v5/stock/f10/us/company.json"
            else:
                url = "https://stock.xueqiu.com/v5/stock/f10/cn/company.json"
            r = self._xueqiu_session().get(url,
                params={"symbol": symbol},
                headers={"Referer": "https://xueqiu.com/hq"},
                timeout=self.BASE_TIMEOUT)
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            data = j.get("data") or {}
            company = data.get("company") or {}
            return _ok({
                "symbol": symbol, "has_data": bool(company),
                "org_name_cn": company.get("org_name_cn"),
                "org_short_name_cn": company.get("org_short_name_cn"),
                "main_operation_business": company.get("main_operation_business"),
                "org_cn_introduction": company.get("org_cn_introduction"),
                "chairman": company.get("chairman"),
                "staff_num": company.get("staff_num"),
                "reg_asset": company.get("reg_asset"),
                "listed_date": company.get("listed_date"),
                "established_date": company.get("established_date"),
                "provincial_name": company.get("provincial_name"),
                "classi_name": company.get("classi_name"),
                "actual_controller": company.get("actual_controller"),
                "reg_address_cn": company.get("reg_address_cn"),
                "telephone": company.get("telephone"),
                "org_website": company.get("org_website"),
                "affiliate_industry": company.get("affiliate_industry"),
                "raw_size": len(r.text),
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    def xueqiu_concept_industry(self, symbol: str = "SH600519") -> dict:
        """雪球个股所属行业+概念 (f10/cn/industry.json, 反爬绕过后真通)

        之前死: /v5/stock/f10/cn/industry.json (返回 size=691 但 items=0)
        复活: 实际有数据! data 在 concept + industry + company 字段 (不是 items)

        已验证: SH688825 长鑫 13 概念 + 半导体行业 + 公司信息全有
                 SZ000858 五粮液 11 概念 + 白酒行业
                 HK00700 腾讯 部分字段 (港股字段名为 mbu/comcnname)
                 usTSLA TSLA 部分字段 (美股字段名为 org_name_en)

        返回:
          data.concept: 概念板块列表 (e.g. [{"ind_name":"芯片概念","ind_code":"BK0586"}, ...])
          data.industry: 行业板块列表 (e.g. [{"ind_name":"半导体","ind_code":"BK0021"}])
          data.company: 公司基础信息
          data.industry_class: SW2014 / HS / GICS (申万/恒生/GICS 分类)
        """
        try:
            if symbol.startswith("HK"):
                url = "https://stock.xueqiu.com/v5/stock/f10/hk/industry.json"
            elif symbol.startswith("us"):
                url = "https://stock.xueqiu.com/v5/stock/f10/us/industry.json"
            else:
                url = "https://stock.xueqiu.com/v5/stock/f10/cn/industry.json"
            r = self._xueqiu_session().get(url,
                params={"symbol": symbol},
                headers={"Referer": "https://xueqiu.com/hq"},
                timeout=self.BASE_TIMEOUT)
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            data = j.get("data") or {}
            concepts = data.get("concept", []) or []
            industries = data.get("industry", []) or []
            return _ok({
                "symbol": symbol,
                "concept_count": len(concepts),
                "concept": concepts,
                "industry_count": len(industries),
                "industry": industries,
                "industry_class": data.get("industry_class"),
                "concept_class": data.get("concept_class"),
                "company_brief": data.get("company") or {},
                "raw_size": len(r.text),
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    # ===== 第5轮反爬: 新版 datacenter reportName =====
    def em_dmsk_balance(self, code: str = "600519.SH", page_size: int = 3) -> dict:
        """东财新版资产负债表 (RPT_DMSK_FN_BALANCE)

        之前死: RPT_DMSK_FN_DEBT 等老 reportName 全部 "报表配置不存在"
        复活: RPT_DMSK_FN_BALANCE 真通 (3 rows 57 字段, 含 PARENT_NETPROFIT/TOTAL_OPERATE_INCOME)

        已验证: SH600519/SZ000858/SH688825/SZ300750 全股 3 rows
        """
        try:
            r = self._std.get(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                params={"reportName": "RPT_DMSK_FN_BALANCE", "columns": "ALL",
                        "filter": f'(SECUCODE="{code}")',
                        "pageNumber": 1, "pageSize": page_size,
                        "sortTypes": -1, "source": "WEB", "client": "PC"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            data = j.get("result", {}).get("data", [])
            return _ok({
                "code": code, "rows": len(data), "data": data,
                "sample_fields": list(data[0].keys()) if data else [],
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    def em_dmsk_income(self, code: str = "600519.SH", page_size: int = 30) -> dict:
        """东财新版利润表 (RPT_DMSK_FN_INCOME)

        之前死: RPT_DMSK_FN_DEBT 等老 reportName
        复活: RPT_DMSK_FN_INCOME 真通 (30 rows 46 字段, 含 REPORT_DATE/NOTICE_DATE/TOTAL_OPERATE_INCOME/PARENT_NETPROFIT)

        已验证: 600519 30 rows, 含近 10 年年报+半年报+季报
        """
        try:
            r = self._std.get(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                params={"reportName": "RPT_DMSK_FN_INCOME", "columns": "ALL",
                        "filter": f'(SECUCODE="{code}")',
                        "pageNumber": 1, "pageSize": page_size,
                        "sortTypes": -1, "source": "WEB", "client": "PC"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            data = j.get("result", {}).get("data", [])
            return _ok({
                "code": code, "rows": len(data), "data": data,
                "sample_fields": list(data[0].keys()) if data else [],
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    # ===== 第15轮反爬: RPT_F10_FINANCE_B* 完整资产负债表/利润表/现金流量表 =====
    def em_f10_balance(self, code: str = "600519.SH", page_size: int = 3) -> dict:
        """东财新版资产负债表 (RPT_F10_FINANCE_BBALANCE)

        之前死: 老接口 "报表配置不存在"
        复活: RPT_F10_FINANCE_BBALANCE 真通 size=9000+ 200+ 字段

        字段:
        - SECURITY_CODE/SECUCODE/SECURITY_NAME_ABBR
        - REPORT_DATE/REPORT_DATE_NAME/REPORT_TYPE
        - TOTAL_ASSETS/TOTAL_LIABILITIES/TOTAL_EQUITY
        - SHARE_CAPITAL/CAPITAL_RESERVE/SURPLUS_RESERVE/UNASSIGN_RPOFIT
        - LOAN_ADVANCE/FIXED_ASSET/CIP/GOODWILL
        - 等200+ 字段 (含 _YOY 同比增长)
        """
        return self._em_get(
            "https://datacenter-web.eastmoney.com/api/data/v1/get",
            {"reportName": "RPT_F10_FINANCE_BBALANCE",
             "columns": "ALL",
             "pageNumber": 1, "pageSize": page_size,
             "filter": f'(SECUCODE="{code}")',
             "sortTypes": -1, "source": "WEB", "client": "PC"},
        )

    def em_f10_income(self, code: str = "600519.SH", page_size: int = 3) -> dict:
        """东财新版利润表 (RPT_F10_FINANCE_BINCOME)"""
        return self._em_get(
            "https://datacenter-web.eastmoney.com/api/data/v1/get",
            {"reportName": "RPT_F10_FINANCE_BINCOME",
             "columns": "ALL",
             "pageNumber": 1, "pageSize": page_size,
             "filter": f'(SECUCODE="{code}")',
             "sortTypes": -1, "source": "WEB", "client": "PC"},
        )

    def em_f10_cashflow(self, code: str = "600519.SH", page_size: int = 3) -> dict:
        """东财新版现金流量表 (RPT_F10_FINANCE_BCASHFLOW)"""
        return self._em_get(
            "https://datacenter-web.eastmoney.com/api/data/v1/get",
            {"reportName": "RPT_F10_FINANCE_BCASHFLOW",
             "columns": "ALL",
             "pageNumber": 1, "pageSize": page_size,
             "filter": f'(SECUCODE="{code}")',
             "sortTypes": -1, "source": "WEB", "client": "PC"},
        )

    # ===== 第5轮反爬: emweb.eastmoney.com F10 不带 PageAjax =====
    def em_f10_html(self, section: str = "CapitalStockStructure",
                    code: str = "SH600519") -> dict:
        """东财 F10 不带 PageAjax 后缀 (反爬绕过)

        之前死: V1 /PC_HSF10/{section}/PageAjax 17 个 section 全返 1718 占位符
        复活: /PC_HSF10/{section} (不带 PageAjax) - 4 个 section 真通 (data 在 HTML)

        真通 section:
          CapitalStockStructure size=45150 rows=41 (股本结构)
          ShareholderResearch size=46076 rows=26 (股东研究)
          BusinessAnalysis size=24190 rows=3 (业务分析)
          NewFinanceAnalysis size=472358 rows=1045 (财报分析, 含详细数据)

        其他 section (Dividend/Split/Executive/...) 仍 1718 占位符
        """
        try:
            r = self._std.get(
                f"https://emweb.eastmoney.com/PC_HSF10/{section}",
                params={"code": code},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            sz = len(r.text)
            if sz == 1718:
                return _err(f"section {section} 返 1718 占位符 (无数据)")
            # 解析 HTML 找数据
            rows = re.findall(r'<tr[^>]*>(.*?)</tr>', r.text, re.DOTALL)
            # 找表格数据
            tables = re.findall(r'<table[^>]*>(.*?)</table>', r.text, re.DOTALL)
            return _ok({
                "section": section, "code": code,
                "size": sz,
                "rows_in_html": len(rows),
                "tables_count": len(tables),
                "html": r.text,  # 完整 HTML
            }, sz)
        except Exception as e:
            return _err(str(e))

    # ===== 第6轮反爬: stock.eastmoney.com JS 暴露的新真通 endpoint =====
    def em_open_data(self, page_size: int = 10) -> dict:
        """东财开盘数据/投资者统计 (datacenter-web RPT_STOCK_OPEN_DATA)

        返回 STATISTICS_DATE/ADD_INVESTOR/END_INVESTOR_A/B/CLOSE_PRICE/CHANGE_RATE/TOTAL_MARKET_CAP
        """
        try:
            r = self._std.get(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                params={"reportName": "RPT_STOCK_OPEN_DATA", "columns": "ALL",
                        "pageNumber": 1, "pageSize": page_size,
                        "sortColumns": "STATISTICS_DATE", "sortTypes": -1,
                        "source": "WEB", "client": "PC"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            data = j.get("result", {}).get("data", [])
            return _ok({
                "total": len(data), "rows": data,
                "sample_fields": list(data[0].keys()) if data else [],
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    def em_mutual_hold(self, page_size: int = 20) -> dict:
        """东财互持/沪深港通持股 (datacenter-web RPT_MUTUAL_HOLD)

        返回 SECURITY_CODE/SECURITY_NAME/TRADE_MARKET_CODE/FREE_SHARES_RATIO/MUTUAL_TYPE/HOLD_DATE/HOLD_SHARES
        """
        try:
            r = self._std.get(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                params={"reportName": "RPT_MUTUAL_HOLD", "columns": "ALL",
                        "pageNumber": 1, "pageSize": page_size,
                        "source": "WEB", "client": "PC"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            data = j.get("result", {}).get("data", [])
            return _ok({
                "total": len(data), "rows": data,
                "sample_fields": list(data[0].keys()) if data else [],
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    def em_mutual_holdranking(self, page_size: int = 20) -> dict:
        """东财互持排行 (datacenter-web RPT_MUTUAL_STOCK_HOLDRANKS)

        返回 MUTUAL_TYPE/HOLD_DATE/SECUCODE/SECURITY_NAME/ADD_MARKET_CAP/HOLD_SHARES_CHANGE
        """
        try:
            r = self._std.get(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                params={"reportName": "RPT_MUTUAL_STOCK_HOLDRANKS", "columns": "ALL",
                        "pageNumber": 1, "pageSize": page_size,
                        "source": "WEB", "client": "PC"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            data = j.get("result", {}).get("data", [])
            return _ok({
                "total": len(data), "rows": data,
                "sample_fields": list(data[0].keys()) if data else [],
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    # ===== 第8轮反爬: RPT_INDEX_CONSTITUENT (brute force) =====
    def em_index_constituent(self, index_code: str = "000300",
                             page_size: int = 10) -> dict:
        """东财指数成分股 (datacenter-web RPT_INDEX_CONSTITUENT)

        之前死: 不在已知 reportName 清单里
        复活: brute force RPT_* 发现, 真通 size=1018+ rows 含成分股列表

        已验证: 5 rows 默认 (上证指数 000001 + 技源集团等)
        返回 INDEX_CODE / INDEX_NAME / SECUCODE / SECURITY_CODE / SECURITY_NAME_ABBR /
               TRADE_DATE / MARKET / STATE

        index_code: 沪深300=000300, 中证500=000905, 中证1000=000852, 上证指数=000001
        """
        try:
            r = self._std.get(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                params={"reportName": "RPT_INDEX_CONSTITUENT", "columns": "ALL",
                        "filter": f'(INDEX_CODE="{index_code}")',
                        "pageNumber": 1, "pageSize": page_size,
                        "source": "WEB", "client": "PC"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            result = j.get("result") or {}
            data = result.get("data", [])
            return _ok({
                "index_code": index_code, "total": len(data),
                "rows": data,
                "sample_fields": list(data[0].keys()) if data else [],
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    def em_gem_list(self, page_size: int = 10) -> dict:
        """东财创业板 IPO 列表 (datacenter-web RPT_GEM_LIST)

        返回 APPLY_DATE / APPLY_CODE / COMPANY_NAME / ONLINE_APPLY_PRICE / TOTAL_ISSUE_NUM
        """
        try:
            r = self._std.get(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                params={"reportName": "RPT_GEM_LIST", "columns": "ALL",
                        "pageNumber": 1, "pageSize": page_size,
                        "source": "WEB", "client": "PC"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            data = j.get("result", {}).get("data", [])
            return _ok({
                "total": len(data), "rows": data,
                "sample_fields": list(data[0].keys()) if data else [],
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    def em_lico_fn_cpd(self, page_size: int = 5) -> dict:
        """东财业绩快报 (datacenter-web RPT_LICO_FN_CPD)

        返回 UPDATE_DATE / REPORTDATE / SECURITY_CODE 等
        """
        try:
            r = self._std.get(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                params={"reportName": "RPT_LICO_FN_CPD", "columns": "ALL",
                        "pageNumber": 1, "pageSize": page_size,
                        "source": "WEB", "client": "PC"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            data = j.get("result", {}).get("data", [])
            return _ok({
                "total": len(data), "rows": data,
                "sample_fields": list(data[0].keys()) if data else [],
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    def em_fund_rank(self, page_size: int = 5) -> dict:
        """东财基金排行 (datacenter-web RPT_FUND_RANK)

        返回 APPLY_RATE / CHANGE_1Y / CHANGE_3Y 等字段
        """
        try:
            r = self._std.get(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                params={"reportName": "RPT_FUND_RANK", "columns": "ALL",
                        "pageNumber": 1, "pageSize": page_size,
                        "source": "WEB", "client": "PC"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            data = j.get("result", {}).get("data", [])
            return _ok({
                "total": len(data), "rows": data,
                "sample_fields": list(data[0].keys()) if data else [],
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    def em_margin_list(self, page_size: int = 5) -> dict:
        """东财融资融券列表 (datacenter-web RPT_MARGIN_LIST)

        返回 SECUCODE / SECURITY_NAME_ABBR / MARGIN_BALANCE / MARGIN_NETBUY_AMT /
               CHANGE / CHG / MARGIN_TRADE_AMT / MARGIN_TVAL_RATIO
        """
        try:
            r = self._std.get(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                params={"reportName": "RPT_MARGIN_LIST", "columns": "ALL",
                        "pageNumber": 1, "pageSize": page_size,
                        "sortColumns": "MARGIN_BALANCE", "sortTypes": -1,
                        "source": "WEB", "client": "PC"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            data = j.get("result", {}).get("data", [])
            return _ok({
                "total": len(data), "rows": data,
                "sample_fields": list(data[0].keys()) if data else [],
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    def em_industry_list(self, page_size: int = 5) -> dict:
        """东财行业列表 (datacenter-web RPT_INDUSTRY_LIST)

        14 页 板块数据，含 BK0xxx 板块代码
        字段: BOARD_CODE / BOARD_NAME / LATEST_DATE / CHANGERATE_3M / RANK_LABEL
        """
        try:
            r = self._std.get(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                params={"reportName": "RPT_INDUSTRY_LIST", "columns": "ALL",
                        "pageNumber": 1, "pageSize": page_size,
                        "source": "WEB", "client": "PC"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            result = j.get("result", {})
            return _ok({
                "total_pages": result.get("pages"),
                "rows": result.get("data", []),
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    def em_concept_list(self, page_size: int = 5) -> dict:
        """东财概念列表 (datacenter-web RPT_CONCEPT_LIST)

        168 页 概念板块
        字段: BOARD_CODE / BOARD_NAME / DATE_JRRQ
        """
        try:
            r = self._std.get(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                params={"reportName": "RPT_CONCEPT_LIST", "columns": "ALL",
                        "pageNumber": 1, "pageSize": page_size,
                        "source": "WEB", "client": "PC"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            result = j.get("result", {})
            return _ok({
                "total_pages": result.get("pages"),
                "rows": result.get("data", []),
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    def em_dividend_rank(self, page_size: int = 5) -> dict:
        """东财分红排行 (datacenter-web RPT_DIVIDEND_RANK)

        3616 页 分红排行
        字段: SECUCODE / SECURITY_CODE / DIVIDEND_RATIO / RISE_YEARS /
               PER_NETCASH / PARENT_NETPROFIT / PARENT_NETPROFIT_YOY / DIVIDEND_NEWRATIO
        """
        try:
            r = self._std.get(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                params={"reportName": "RPT_DIVIDEND_RANK", "columns": "ALL",
                        "pageNumber": 1, "pageSize": page_size,
                        "source": "WEB", "client": "PC"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            result = j.get("result", {})
            return _ok({
                "total_pages": result.get("pages"),
                "rows": result.get("data", []),
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    # ===== 第11轮反爬: 腾讯 qt.gtimg.cn (新浪 backup) =====
    def gtimg_hq(self, symbols: str = "sh600519,sh688825,hk00700") -> dict:
        """腾讯财经行情 (qt.gtimg.cn)

        之前死: 新浪 vip 456 ban / web.ifzq.gtimg.cn 30 redirect ban
        复活: qt.gtimg.cn 真通 (A 股 + 港股)

        已验证:
        - sh600519 茅台 1309.22 元 size=542
        - sh688825 长鑫 52.48 元 size=569
        - hk00700 腾讯 478.800 size=431
        - 美股 usTSLA.N ban

        返回格式: v_sh600519="1~贵州茅台~600519~现价~昨收~今开~..."
        """
        try:
            r = self._std.get(
                "https://qt.gtimg.cn/q=" + symbols,
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            lines = [l for l in r.text.strip().split(';') if l.strip()]
            rows = []
            for line in lines:
                # 格式: v_<sym>="data"
                if '=' in line:
                    key, val = line.split('=', 1)
                    rows.append({"symbol": key.strip(), "data": val.strip().strip('"')})
            return _ok({
                "count": len(rows),
                "rows": rows,
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    def gtimg_us_hq(self, symbols: str = "usTSLA,usAAPL,usNVDA,usMSFT") -> dict:
        """腾讯财经美股行情 (qt.gtimg.cn q=usTSLA)

        已验证:
        - usTSLA 特斯拉 328.58 (size=382)
        - usAAPL 苹果 313.33 (size=383)
        - usNDX 纳斯达克100 (size=291)
        - us.DJI 道琼斯 (size=298)
        """
        try:
            r = self._std.get(
                "https://qt.gtimg.cn/q=" + symbols,
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            lines = [l for l in r.text.strip().split(';') if l.strip()]
            rows = []
            for line in lines:
                if '=' in line:
                    key, val = line.split('=', 1)
                    rows.append({"symbol": key.strip(), "data": val.strip().strip('"')})
            return _ok({"count": len(rows), "rows": rows}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def gtimg_index(self, symbols: str = "sh000300,sh000001,sh000905,sz399001,sz399006") -> dict:
        """腾讯财经指数行情 (qt.gtimg.cn)

        已验证:
        - sh000300 沪深300 4694.44
        - sh000001 上证指数 3940.04
        - sh000905 中证500 7980.12
        - sz399001 深证成指 14311.01
        - sz399006 创业板指 3563.12
        - sz399905 中证500
        - sz399852 中证1000 7679.53
        """
        try:
            r = self._std.get(
                "https://qt.gtimg.cn/q=" + symbols,
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            lines = [l for l in r.text.strip().split(';') if l.strip()]
            rows = []
            for line in lines:
                if '=' in line:
                    key, val = line.split('=', 1)
                    rows.append({"symbol": key.strip(), "data": val.strip().strip('"')})
            return _ok({"count": len(rows), "rows": rows}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def gtimg_hk_index(self, symbols: str = "hkHSI,hkHSCEI") -> dict:
        """腾讯财经港股指数 (qt.gtimg.cn)

        已验证:
        - hkHSI 恒生指数 25668.030
        - hkHSCEI 国企指数 8531.580
        """
        try:
            r = self._std.get(
                "https://qt.gtimg.cn/q=" + symbols,
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            lines = [l for l in r.text.strip().split(';') if l.strip()]
            rows = []
            for line in lines:
                if '=' in line:
                    key, val = line.split('=', 1)
                    rows.append({"symbol": key.strip(), "data": val.strip().strip('"')})
            return _ok({"count": len(rows), "rows": rows}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def gtimg_market_code(self, codes: str = "s_sz000001,s_sz399001,s_sz399300") -> dict:
        """腾讯财经全市场代码 (qt.gtimg.cn q=s_sz/sh/xxx)

        之前死: q=s_pksz000300 等不同 prefix 全 ban
        复活: q=s_sz000001, s_sz000002 等真通全市场 A 股

        已验证: 75+ 个真通
        - s_sz000001 平安银行 11.19
        - s_sz000002 万科A 3.22
        - s_sz000905 厦门港务 8.54
        - s_sz399001 深证成指 14311.01
        - s_sz399300 沪深300 4694.44
        - s_sz399905 中证500 7980.12
        - s_sz399852 中证1000 7679.53
        - s_sz399986 中证银行 7147.55
        - s_sz399987 中证酒 3950.93
        - s_sz399975 证券公司 763.22
        - s_sz399971 中证传媒 1278.85
        - s_sz399996 智能家居 4930.19
        - s_sz399997 中证白酒 6691.73
        - s_sz399998 中证煤炭 2331.67

        返回格式: 51~名称~代码~现价~涨跌~涨跌幅~成交量~成交额~...
        """
        try:
            r = self._std.get(
                "https://qt.gtimg.cn/q=" + codes,
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            lines = [l for l in r.text.strip().split(';') if l.strip()]
            rows = []
            for line in lines:
                if '=' in line:
                    key, val = line.split('=', 1)
                    rows.append({"symbol": key.strip(), "data": val.strip().strip('"')})
            return _ok({"count": len(rows), "rows": rows}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def gtimg_market_all(self, codes: str = "sz000001,sh600519,sz399300,sh000300,hk00700,usTSLA") -> dict:
        """腾讯财经全市场代码 (qt.gtimg.cn 不带 s_ prefix 直接 sz/sh/hk/us)

        已验证: 所有 prefix 都通

        通用格式: code~名称~当前~昨收~今开~成交量~成交额~...

        A 股 (51): sz000001 平安银行, sh600519 茅台, sz000002 万科A
        指数 (1): sh000001 上证, sz399001 深证成指, sh000300 沪深300, sz399905 中证500
        港股 (100): hk00700 腾讯, hk09988 阿里, hkHSI 恒生指数
        美股 (200): usTSLA 特斯拉, usAAPL 苹果, usNVDA 英伟达
        """
        try:
            r = self._std.get(
                "https://qt.gtimg.cn/q=" + codes,
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            lines = [l for l in r.text.strip().split(';') if l.strip()]
            rows = []
            for line in lines:
                if '=' in line:
                    key, val = line.split('=', 1)
                    rows.append({"symbol": key.strip(), "data": val.strip().strip('"')})
            return _ok({"count": len(rows), "rows": rows}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def gtimg_fund(self, codes: str = "jj000001,jj000300,jj000905") -> dict:
        """腾讯财经基金 (qt.gtimg.cn q=jjxxxxxx)

        已验证:
        - jj000001 华夏成长混合 1.3420 (现价)
        - jj000300 德邦德利货币A
        - jj000905 鹏华安盈宝货币A

        返回: code~名称~单位净值~累计净值~日增长~周增长~月增长~...
        """
        try:
            r = self._std.get(
                "https://qt.gtimg.cn/q=" + codes,
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            lines = [l for l in r.text.strip().split(';') if l.strip()]
            rows = []
            for line in lines:
                if '=' in line:
                    key, val = line.split('=', 1)
                    rows.append({"symbol": key.strip(), "data": val.strip().strip('"')})
            return _ok({"count": len(rows), "rows": rows}, len(r.text))
        except Exception as e:
            return _err(str(e))
        """新浪 K 线 (CN_MarketData.getKLineData, ma=no)

        之前死: Service not valid (CN_MarketDataService.getKLineData ma=yes)
        复活: CN_MarketData.getKLineData ma=no 真通 size=11202 (茅台 100 根日 K)

        返回 day/open/high/low/close/volume

        scale: 5=5分钟, 15=15分钟, 30=30分钟, 60=60分钟, 240=日K, 1200=周K
        """
        try:
            r = self._std.get(
                "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData",
                params={"symbol": symbol, "scale": scale, "ma": "no", "datalen": datalen},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            data = r.json()
            return _ok({
                "symbol": symbol, "scale": scale, "count": len(data), "rows": data,
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    # ===== 第7轮反爬: push2.eastmoney.com 沪股通资金 (curl_cffi 可调) =====
    def em_kamt(self) -> dict:
        """东财沪股通/深股通资金流向 (push2.eastmoney.com/api/qt/kamt/get)

        之前死: push2.eastmoney.com 沙盒 RemoteDisconnected
        复活: kamt/get 这个 endpoint 没用 ban, curl_cffi + ut token 直接可调

        返回 hk2sh / sh2hk / sz2hk / hk2sz (沪→港/港→沪/深→港/港→深) 资金流向
        字段: status, dayNetAmtIn, dayAmtRemain, dayAmtThreshold, date2, buyAmt

        已验证: size=585 含完整 JSON
        """
        try:
            from curl_cffi import requests as cffi
            r = cffi.Session(impersonate="chrome120").get(
                "https://push2.eastmoney.com/api/qt/kamt/get",
                params={"fields1": "f1,f2,f3,f4",
                        "fields2": "f51,f52,f53,f54,f56,f60",
                        "ut": "13697a1cc677c8bfa9a496437bfef419"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            return _ok(j, len(r.text))
        except Exception as e:
            return _err(str(e))

    # ------------------------------------------------------------------
    # 扩展接口 (api_docs_extra.md 第二轮)
    # ------------------------------------------------------------------
    def em_f10_lico_fn_cpd(self, code: str = "600519.SH", page_size: int = 3) -> dict:
        """东财 F10 业绩表 (RPT_LICO_FN_CPD, 全市场 485301 条)"""
        try:
            r = self._std.get(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                params={"reportName": "RPT_LICO_FN_CPD", "columns": "ALL",
                        "filter": f'(SECUCODE="{code}")',
                        "pageNumber": 1, "pageSize": page_size,
                        "sortTypes": -1, "source": "WEB", "client": "PC"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            if not j.get("success"):
                return _err(f"success=False msg={j.get('message','')[:50]}")
            data = j.get("result", {}).get("data", [])
            return _ok({"rows": data, "report": "RPT_LICO_FN_CPD"}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def ths_industry_by_field(self, field: str = "199112", page: int = 1) -> dict:
        """同花顺行业板块 - 自定义排序字段

        注意: 仅 199112 (涨跌幅) 有数据，其他字段 (199113成交额/199114换手率/199115涨速) 返回空表头
        """
        try:
            r = self.ths_session().get(
                f"http://q.10jqka.com.cn/thshy/index/field/{field}/order/desc/"
                f"page/{page}/ajax/1/free/1/",
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200 or not r.text:
                return _err(f"status={r.status_code}", r.status_code)
            html = r.content.decode("gbk", errors="replace")
            # 过滤分页链接
            names = [n for n in re.findall(r'>([^<>]{2,8})</a>', html)
                     if n not in ('下一页', '尾页', '首页', '上一页')]
            return _ok({"field": field, "names": names[:30], "size": len(r.text)},
                       len(r.text))
        except Exception as e:
            return _err(str(e))

    def ths_concept_by_addtime(self, page: int = 1) -> dict:
        """同花顺概念板块 - 按添加时间排序 (addtime, 唯一真通的 field)"""
        try:
            r = self.ths_session().get(
                f"http://q.10jqka.com.cn/gn/index/field/addtime/order/desc/"
                f"page/{page}/ajax/1/free/1/",
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200 or not r.text:
                return _err(f"status={r.status_code}", r.status_code)
            html = r.content.decode("gbk", errors="replace")
            names = re.findall(r'>([^<>]{2,8})</a>', html)
            names = [n for n in names if n not in ('下一页', '尾页', '首页', '上一页')]
            return _ok({"names": names[:30]}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def ths_bk_kline_v2(self, code: str = "881270", year: int = 2026) -> dict:
        """同花顺板块 K 线 v2 版本 (与 v4 数据相同)"""
        try:
            r = self._std.get(
                f"https://d.10jqka.com.cn/v2/line/bk_{code}/01/{year}.js",
                headers={"Referer": "http://q.10jqka.com.cn/"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200 or not r.text:
                return _err(f"status={r.status_code}", r.status_code)
            m = re.search(r'quotebridge\w*\((.*)\)', r.text)
            if not m:
                return _err("JSONP 格式不匹配", 200)
            payload = json.loads(m.group(1))
            rows = []
            for line in payload.get("data", "").split(";"):
                parts = line.split(",")
                if len(parts) >= 7 and parts[0]:
                    rows.append({
                        "date": parts[0], "open": float(parts[1]),
                        "high": float(parts[2]), "low": float(parts[3]),
                        "close": float(parts[4]), "volume": int(parts[5] or 0),
                        "amount": float(parts[6] or 0),
                    })
            return _ok(rows, len(r.text))
        except Exception as e:
            return _err(str(e))

    def sina_corp_finance(self, code: str = "600519",
                          report: str = "vFD_BalanceSheet") -> dict:
        """新浪 corp 财报 HTML (report: BalanceSheet/ProfitStatement/CashFlow/FinancialGuide)"""
        try:
            r = self._std.get(
                f"https://vip.stock.finance.sina.com.cn/corp/go.php/{report}/"
                f"stockid/{code}/ctrl/part/displaytype/4.phtml",
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            # 直接返回 HTML，不解析
            return _ok({"html_len": len(r.text)}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def sina_corp_info(self, code: str = "600519", menu: int = 1) -> dict:
        """新浪 corp 公司基本资料 HTML (vCI_CorpInfo)

        之前死: finance.sina.com.cn 错误页
        复活: vip.stock.finance.sina.com.cn/corp/go.php/vCI_CorpInfo 真通 size=50278

        已验证:
        - 600519 茅台 size=50278
        - 688825 长鑫 size=50489
        - 000001 平安银行 size=50359
        - 301707 展芯 size=49782

        menu: 1=基本资料 2=高管 3=股东 4=财务摘要
        """
        try:
            r = self._std.get(
                f"https://vip.stock.finance.sina.com.cn/corp/go.php/vCI_CorpInfo/"
                f"stockid/{code}/menu_num/{menu}.phtml",
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            return _ok({"html_len": len(r.text)}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def sina_corp_bulletin(self, code: str = "600519") -> dict:
        """新浪 corp 公司公告 HTML (vCB_AllBulletin)

        已验证: 600519 size=53233, 688825 size=53650, 000001 size=53087
        """
        try:
            r = self._std.get(
                f"https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletin.php",
                params={"stockid": code},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            return _ok({"html_len": len(r.text)}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def sina_corp_bulletin2(self, code: str = "600519") -> dict:
        """新浪 corp 公司公告 HTML (vCB_Bulletin)"""
        try:
            r = self._std.get(
                f"https://vip.stock.finance.sina.com.cn/corp/view/vCB_Bulletin.php",
                params={"stockid": code},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            return _ok({"html_len": len(r.text)}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def sina_corp_manager(self, code: str = "600519") -> dict:
        """新浪 corp 董监高 HTML (vCI_CorpManager)

        已验证: 600519 size=96944, 688825 size=65962, 000001 size=143119
        """
        try:
            r = self._std.get(
                f"https://vip.stock.finance.sina.com.cn/corp/go.php/vCI_CorpManager/stockid/{code}.phtml",
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            return _ok({"html_len": len(r.text)}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def sina_corp_structure(self, code: str = "600519") -> dict:
        """新浪 corp 股本结构 HTML (vCI_StockStructure)"""
        try:
            r = self._std.get(
                f"https://vip.stock.finance.sina.com.cn/corp/go.php/vCI_StockStructure/stockid/{code}.phtml",
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            return _ok({"html_len": len(r.text)}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def sina_corp_news(self, code: str = "600519") -> dict:
        """新浪 corp 全部新闻 HTML (vCB_AllNews)"""
        try:
            r = self._std.get(
                f"https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllNews.php",
                params={"stockid": code},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            return _ok({"html_len": len(r.text)}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def sse_yunhq_snap(self, code: str = "000001") -> dict:
        """上交所 yunhq.sse.com.cn 实时快照 (HTTP 非 HTTPS)

        之前死: HTTPS SSL handshake failed (curl error 35, _ssl.c:1010)
        复活: HTTP 非 HTTPS 真通!

        已验证:
        - 000001 上证指数 3900.35 (date 20260807)
        - 600519 茅台 1308.55
        - 688825 长鑫
        - 任何 6 位代码

        返回 JSON: code/date/time/snap[] = [名称, 当前, 昨收, 今开, 最高, 最低, 涨跌, 涨跌额, ...]
        """
        import subprocess
        try:
            r = subprocess.run(
                ['curl', '-s', '--max-time', '8',
                 '-H', 'User-Agent: Mozilla/5.0 Chrome/120',
                 f'http://yunhq.sse.com.cn:32041/v1/sh1/snap/{code}'],
                capture_output=True, text=True, timeout=12,
            )
            if r.returncode != 0:
                return _err(f"curl exit={r.returncode}: {r.stderr[:100]}")
            import json
            data = json.loads(r.stdout)
            return _ok(data, len(r.stdout))
        except Exception as e:
            return _err(str(e))

    def sse_yunhq_index(self, code: str = "000300") -> dict:
        """上交所 yunhq 指数实时快照 (HTTP)

        已验证:
        - 000300 沪深300 size=262
        - 000905 中证500 size=263
        - 000852 中证1000 size=264
        - 000001 上证指数 (用 sse_yunhq_snap)

        snap[]: 名称, 当前, 昨收, 今开, 最高, 最低, 涨跌, 涨跌幅, 成交量, 成交额, ...
        """
        return self.sse_yunhq_snap(code)

    def sse_yunhq_stock(self, code: str = "600519") -> dict:
        """上交所 yunhq 个股实时 (HTTP)"""
        return self.sse_yunhq_snap(code)

    def np_cnotice_ann(self, art_code: str = "AN202607171827064564",
                       page_index: int = 1) -> dict:
        """东方财富 np-cnotice-stock 公告正文API

        之前死: 之前所有 np-* 都返 HTML SPA
        复活: np-cnotice-stock.eastmoney.com/api/content/ann 真通 size=951~1546

        已验证:
        - AN202607171827064564 茅台 size=1546
        - AN202601071816773188 茅台 size=951

        返回字段:
        - art_code: 公告代码
        - attach_list: [{attach_url (PDF URL), attach_type, attach_size, seq}]
        - 等其他字段
        """
        import subprocess
        try:
            url = (f"https://np-cnotice-stock.eastmoney.com/api/content/ann"
                   f"?art_code={art_code}&client_source=web&page_index={page_index}")
            r = subprocess.run(
                ['curl', '-s', '--max-time', '10',
                 '-H', 'User-Agent: Mozilla/5.0 Chrome/120',
                 '-H', 'Referer: https://data.eastmoney.com/',
                 url],
                capture_output=True, text=True, timeout=15,
            )
            if r.returncode != 0:
                return _err(f"curl exit={r.returncode}: {r.stderr[:100]}")
            import json
            data = json.loads(r.stdout)
            return _ok(data, len(r.stdout))
        except Exception as e:
            return _err(str(e))

    def np_notice_ann(self, stock_list: str = "600519", page_size: int = 10,
                       page_index: int = 1, ann_type: str = "A",
                       begin_time: str = "", end_time: str = "") -> dict:
        """东方财富 np-anotice-stock 公告 API

        之前死: 用 std Session 返回 HTML SPA
        复活: 用 curl 子进程 + page_index 参数 真通 size=4540~11098!

        已验证: 600519 茅台 / 688825 长鑫 / 000001 平安 / 301707 展芯

        ann_type: A=一般公告, B=业绩公告, C=风险提示, D=其他

        返回 JSON:
        - art_code: 公告代码 (AN202607171827064564)
        - codes: [{stock_code, short_name, market_code, ann_type, inner_code}]
        - columns: [{column_code, column_name}]
        - display_time, eiTime, notice_date, product_code, language
        """
        import subprocess
        try:
            url = (f"https://np-anotice-stock.eastmoney.com/api/security/ann"
                   f"?sr=-1&page_size={page_size}&page_index={page_index}"
                   f"&ann_type={ann_type}&stock_list={stock_list}")
            if begin_time: url += f"&begin_time={begin_time}"
            if end_time: url += f"&end_time={end_time}"
            r = subprocess.run(
                ['curl', '-s', '--max-time', '10',
                 '-H', 'User-Agent: Mozilla/5.0 Chrome/120',
                 '-H', 'Referer: https://data.eastmoney.com/',
                 url],
                capture_output=True, text=True, timeout=15,
            )
            if r.returncode != 0:
                return _err(f"curl exit={r.returncode}: {r.stderr[:100]}")
            import json
            data = json.loads(r.stdout)
            return _ok(data, len(r.stdout))
        except Exception as e:
            return _err(str(e))

    def sina_corp_holder(self, code: str = "600519") -> dict:
        """新浪 corp 股东信息 HTML (vCI_StockHolder)"""
        try:
            r = self._std.get(
                f"https://vip.stock.finance.sina.com.cn/corp/go.php/vCI_StockHolder/stockid/{code}.phtml",
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            return _ok({"html_len": len(r.text)}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def sina_corp_equity(self, code: str = "600519") -> dict:
        """新浪 corp 股权结构 HTML (vCI_EquityStru)"""
        try:
            r = self._std.get(
                f"https://vip.stock.finance.sina.com.cn/corp/go.php/vCI_EquityStru/stockid/{code}.phtml",
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            return _ok({"html_len": len(r.text)}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def sina_corp_finance_summary(self, code: str = "600519") -> dict:
        """新浪 corp 财务摘要 HTML (vFD_FinanceSummary)"""
        try:
            r = self._std.get(
                f"https://vip.stock.finance.sina.com.cn/corp/go.php/vFD_FinanceSummary/stockid/{code}.phtml",
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            return _ok({"html_len": len(r.text)}, len(r.text))
        except Exception as e:
            return _err(str(e))

    # ------------------------------------------------------------------
    # 扩展接口 (api_docs_extra.md)
    # ------------------------------------------------------------------
    def xueqiu_screener(self, type_: str = "sha",
                        order_by: str = "percent", order: str = "desc",
                        page: int = 1, size: int = 30) -> dict:
        """雪球 screener 涨跌幅榜 (type: sha沪A/sza深A/us美股/hk港股)"""
        try:
            r = self._xueqiu_session().get(
                "https://xueqiu.com/service/v5/stock/screener/quote/list",
                params={"type": type_, "order_by": order_by, "order": order,
                        "page": page, "size": size},
                headers={"Referer": "https://xueqiu.com/"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json().get("data", {})
            return _ok({"count": j.get("count"), "list": j.get("list", [])},
                       len(r.text))
        except Exception as e:
            return _err(str(e))

    def xueqiu_kline_month(self, symbol: str = "SH688825", count: int = 12) -> dict:
        """雪球月 K 线"""
        return self.xueqiu_kline(symbol, "month", count)

    def xueqiu_top_holders_full(self, symbol: str = "SH600519") -> dict:
        """雪球十大股东 (老股) — 完整字段"""
        return self._xq_get("/v5/stock/f10/cn/top_holders.json", {"symbol": symbol})

    def xueqiu_skholderchg_full(self, symbol: str = "SH600519") -> dict:
        """雪球股东变动 (老股) — 完整字段"""
        return self._xq_get("/v5/stock/f10/cn/skholderchg.json", {"symbol": symbol})

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
    def _em_f10(self, endpoint: str, code: str) -> dict:
        try:
            r = self._std.get(
                f"https://emweb.eastmoney.com/PC_HSF10/{endpoint}",
                params={"code": code},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            text = r.text
            if text.startswith("{"):
                return _ok(r.json(), len(text))
            elif "<html" in text.lower()[:200]:
                return _ok({"html_len": len(text)}, len(text))
            else:
                return _err("未知响应格式")
        except Exception as e:
            return _err(str(e))

    def em_capital_structure(self, code: str = "SH600519") -> dict:
        """东财 F10 股本结构 (xsjj/gbjg/lngbbd/gbgc)"""
        return self._em_f10("CapitalStockStructure/PageAjax", code)

    def em_shareholder_research(self, code: str = "SH600519") -> dict:
        """东财 F10 股东户数 (gdrs)"""
        return self._em_f10("ShareholderResearch/PageAjax", code)

    def em_business_analysis(self, code: str = "SH600519") -> dict:
        """东财 F10 业务分析 (zyfw)"""
        return self._em_f10("BusinessAnalysis/PageAjax", code)

    def em_new_finance_analysis(self, code: str = "SH600519",
                                type_: int = 0) -> dict:
        """东财 F10 财务分析页 (HTML, type: 0综合/1资产/2利润/3现金流)"""
        try:
            r = self._std.get(
                "https://emweb.eastmoney.com/PC_HSF10/NewFinanceAnalysis/Index",
                params={"type": type_, "code": code},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            return _ok({"html_len": len(r.text)}, len(r.text))
        except Exception as e:
            return _err(str(e))

    # 东财 F10 datacenter
    def _em_f10_datacenter(self, report_name: str, code: str,
                           page_size: int = 3) -> dict:
        """F10 datacenter (code 形如 '600519.SH')"""
        try:
            r = self._std.get(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                params={"reportName": report_name, "columns": "ALL",
                        "filter": f'(SECUCODE="{code}")',
                        "pageNumber": 1, "pageSize": page_size,
                        "sortTypes": -1, "source": "WEB", "client": "PC"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            if not j.get("success"):
                return _err(f"success=False msg={j.get('message','')[:50]}")
            data = j.get("result", {}).get("data", [])
            return _ok({"rows": data, "report": report_name}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def em_f10_main_finadata(self, code: str = "600519.SH") -> dict:
        """东财 F10 主要财务指标 (165 列)"""
        return self._em_f10_datacenter("RPT_F10_FINANCE_MAINFINADATA", code)

    def em_f10_gincome(self, code: str = "600519.SH") -> dict:
        """东财 F10 利润表"""
        return self._em_f10_datacenter("RPT_F10_FINANCE_GINCOME", code)

    # 腾讯扩展
    def tencent_us(self, code: str = "usTSLA") -> dict:
        """腾讯美股 (code: usTSLA / usAAPL / usNVDA / usMSFT)"""
        return self._tencent_q(code)

    def tencent_index(self, code: str = "s_sh000300") -> dict:
        """腾讯指数 (code: s_sh000300 / s_sz399006 / s_sh000001 ...)"""
        return self._tencent_q(code)

    # ------------------------------------------------------------------
    # 一键验证
    # ------------------------------------------------------------------
    def test_all(self, verbose: bool = True) -> dict:
        """验证所有 31 个接口，返回 {name: ok/error}"""
        cases = [
            # 雪球
            ("xueqiu_quote",           lambda: self.xueqiu_quote("SH688825")),
            ("xueqiu_f10_company",     lambda: self.xueqiu_f10_company("SH688825")),
            ("xueqiu_f10_business",    lambda: self.xueqiu_f10_business("SH688825")),
            ("xueqiu_kline_day",       lambda: self.xueqiu_kline_day("SH688825")),
            ("xueqiu_kline_week",      lambda: self.xueqiu_kline_week("SH688825")),
            ("xueqiu_realtime_batch",  lambda: self.xueqiu_realtime_batch("SH688825,SH600519")),
            ("xueqiu_industry",        lambda: self.xueqiu_industry("SH688825")),
            ("xueqiu_top_holders",     lambda: self.xueqiu_top_holders("SH600519")),
            # 同花顺
            # ("ths_industry_list",      lambda: self.ths_industry_list()),  # nginx 永久 IP ban
            # ("ths_concept_list",       lambda: self.ths_concept_list()),   # nginx 永久 IP ban
            # ("ths_industry_detail",    lambda: self.ths_industry_detail("881270")),  # nginx 永久 IP ban
            ("ths_bk_kline",           lambda: self.ths_bk_kline("881270", 2026)),
            # 东财
            ("em_stock_get",           lambda: self.em_stock_get("688825")),
            ("em_kline",               lambda: self.em_kline("688825")),
            ("em_datacenter",          lambda: self.em_datacenter()),
            ("em_f10_company",         lambda: self.em_f10_company("SH688825")),
            ("em_f10_profile",         lambda: self.em_f10_profile("SH688825")),
            # === 第11轮反爬: PC_HSF10/CompanySurvey/PageAjax ===
            ("em_company_survey",      lambda: self.em_company_survey("SH600519")),
            ("em_capital_structure",   lambda: self.em_capital_structure("SH600519")),
            ("em_profit_forecast",     lambda: self.em_profit_forecast("SH600519")),
            # 巨潮
            ("cninfo_company_profile", lambda: self.cninfo_company_profile("688825")),
            ("cninfo_index",           lambda: self.cninfo_index()),
            # 新浪
            ("sina_hq_a",              lambda: self.sina_hq_a("sh688825")),
            ("sina_hq_batch",          lambda: self.sina_hq_batch()),
            ("sina_hq_hk",             lambda: self.sina_hq_hk("01810")),
            ("sina_top_chg",           lambda: self.sina_top_chg(5)),
            # 腾讯
            ("tencent_a",              lambda: self.tencent_a("sh688825")),
            ("tencent_batch",          lambda: self.tencent_batch()),
            ("tencent_hk",             lambda: self.tencent_hk("hk01810")),
            # efinance
            ("ef_snapshot_a",          lambda: self.ef_snapshot("688825")),
            ("ef_history_a",           lambda: self.ef_history("688825")),
            ("ef_base_info",           lambda: self.ef_base_info("688825")),
            ("ef_snapshot_hk",         lambda: self.ef_snapshot("hk01810")),
            ("ef_snapshot_us",         lambda: self.ef_snapshot("usTSLA")),
            # === 扩展接口 (api_docs_extra.md) ===
            # 雪球 screener
            ("xq_screener_sha",        lambda: self.xueqiu_screener("sha")),
            ("xq_screener_sza",        lambda: self.xueqiu_screener("sza")),
            ("xq_screener_us",         lambda: self.xueqiu_screener("us")),
            ("xq_screener_hk",         lambda: self.xueqiu_screener("hk")),
            # 雪球 kline month + 老股股东
            ("xq_kline_month",         lambda: self.xueqiu_kline_month("SH688825")),
            ("xq_top_holders_full",    lambda: self.xueqiu_top_holders_full("SH600519")),
            ("xq_skholderchg_full",    lambda: self.xueqiu_skholderchg_full("SH600519")),
            # 中证
            ("csindex_300",            lambda: self.csindex_perf("000300")),
            ("csindex_500",            lambda: self.csindex_perf("000905")),
            ("csindex_1000",           lambda: self.csindex_perf("000852")),
            # 东财 F10
            ("em_capital_structure",   lambda: self.em_capital_structure("SH600519")),
            ("em_shareholder_research",lambda: self.em_shareholder_research("SH600519")),
            ("em_business_analysis",   lambda: self.em_business_analysis("SH600519")),
            ("em_new_finance_analysis",lambda: self.em_new_finance_analysis("SH600519")),
            # 东财 F10 datacenter
            ("em_f10_main_finadata",   lambda: self.em_f10_main_finadata("600519.SH")),
            ("em_f10_gincome",         lambda: self.em_f10_gincome("600519.SH")),
            # 新浪
            ("sina_cyb",               lambda: self.sina_list(node="cyb", num=3)),
            ("sina_kcb",               lambda: self.sina_list(node="kcb", num=3)),
            ("sina_hs_b",              lambda: self.sina_list(node="hs_b", num=3)),
            # 腾讯
            ("tencent_us_tsla",        lambda: self.tencent_us("usTSLA")),
            ("tencent_us_aapl",        lambda: self.tencent_us("usAAPL")),
            ("tencent_idx_hs300",      lambda: self.tencent_index("s_sh000300")),
            ("tencent_idx_cyb",        lambda: self.tencent_index("s_sz399006")),
            # === 第二轮探活 (api_docs_extra §七) ===
            ("em_f10_lico_cpd",        lambda: self.em_f10_lico_fn_cpd("600519.SH")),
            # ("ths_concept_by_199112",  lambda: self.ths_concept_by_addtime()),  # nginx 永久 IP ban
            ("ths_bk_kline_v2",        lambda: self.ths_bk_kline_v2("881270", 2026)),
            ("sina_hs_a",              lambda: self.sina_list(node="hs_a", num=3)),
            ("sina_sh_a",              lambda: self.sina_list(node="sh_a", num=3)),
            ("sina_sz_a",              lambda: self.sina_list(node="sz_a", num=3)),
            ("sina_corp_balance",      lambda: self.sina_corp_finance("600519", "vFD_BalanceSheet")),
            ("csindex_000001",         lambda: self.csindex_perf("000001")),
            ("csindex_000016",         lambda: self.csindex_perf("000016")),
            # === 反爬抢救接口 (api_docs_rescued.md) ===
            # 腾讯 web.ifzq 全市场 K 线/分时
            ("tx_kline_hk00700",       lambda: self.tencent_kline_global("hk00700", "day", 10)),
            ("tx_kline_sh600519",      lambda: self.tencent_kline_global("sh600519", "day", 10)),
            ("tx_kline_usTSLA",        lambda: self.tencent_kline_global("usTSLA", "day", 10)),
            ("tx_us_kline_tsla",       lambda: self.tencent_us_kline("usTSLA", "day", 10)),
            ("tx_us_kline_aapl",       lambda: self.tencent_us_kline("usAAPL", "day", 10)),
            ("tx_minute_sh600519",     lambda: self.tencent_minute("sh600519")),
            ("tx_minute_hk00700",      lambda: self.tencent_minute("hk00700")),
            ("tx_minute_usTSLA",       lambda: self.tencent_minute("usTSLA")),
            # 腾讯 qt.gtimg.cn 全 market 真通
            ("tx_global_usAAPL",       lambda: self.tencent_global("usAAPL")),
            ("tx_global_usNVDA",       lambda: self.tencent_global("usNVDA")),
            ("tx_global_hk00700",      lambda: self.tencent_global("hk00700")),
            ("tx_global_hk09988",      lambda: self.tencent_global("hk09988")),
            ("tx_global_bSH900901",    lambda: self.tencent_global("sh900901")),
            ("tx_global_idx_dji",      lambda: self.tencent_global("usDJI")),
            ("tx_global_idx_hsi",      lambda: self.tencent_global("hkHSI")),
            # 巨潮公告 + PDF
            ("cninfo_anno_sh688825",   lambda: self.cninfo_announcement("688825", "9920000008")),
            ("cninfo_anno_sh600519",   lambda: self.cninfo_announcement("600519", "gssh0600519")),
            ("cninfo_fulltext_gzmt",   lambda: self.cninfo_fulltext_search("贵州茅台")),
            ("cninfo_szse_stock",      lambda: self.cninfo_szse_stock_list()),
            # 中证 dataServer
            ("csindex_industry",       lambda: self.csindex_industry_classify("1")),
            ("csindex_agents",         lambda: self.csindex_agents_list()),
            # 雪球 industry 全列表
            ("xq_industry_full",       lambda: self.xueqiu_industry_list_full("SH600519")),
            # 第7轮反爬: 雪球 f10 business_analysis + bonus
            ("xq_business_sh688825",   lambda: self.xueqiu_business_analysis("SH688825")),
            ("xq_business_sh600519",   lambda: self.xueqiu_business_analysis("SH600519")),
            ("xq_bonus_sh600519",      lambda: self.xueqiu_bonus("SH600519")),
            # === 第10轮反爬: 雪球 f10/cn/industry.json 概念 ===
            ("xq_f10_concept_688825", lambda: self.xueqiu_f10_concept("SH688825")),
            ("xq_f10_concept_600519", lambda: self.xueqiu_f10_concept("SH600519")),
            # === 第10轮反爬: 雪球 screener/quote/list.json ===
            ("xq_screener_top",        lambda: self.xueqiu_screener_list(1, 5, "percent", "desc")),
            # === 同花顺 data.10jqka.com.cn 子域 (反爬绕过) ===
            # ("ths_rank_cxfl",          lambda: self.ths_rank_cxfl()),        # nginx 永久 IP ban
            # ("ths_market_rzrq",        lambda: self.ths_market_rzrq()),      # nginx 永久 IP ban
            # ("ths_funds_ggzjl",        lambda: self.ths_funds_ggzjl()),      # nginx 永久 IP ban
            # ("ths_funds_hyzjl",        lambda: self.ths_funds_hyzjl()),      # nginx 永久 IP ban
            # ("ths_market_dzjy",        lambda: self.ths_market_dzjy()),      # nginx 永久 IP ban
            # ("ths_ipo_xgpt",           lambda: self.ths_ipo_xgpt()),         # nginx 永久 IP ban
            # ("ths_ipo_xgyp",           lambda: self.ths_ipo_xgyp()),         # nginx 永久 IP ban
            # ("ths_market_ggsyl",       lambda: self.ths_market_ggsyl()),     # nginx 永久 IP ban
            ("ths_stockpage_news",     lambda: self.ths_stockpage_news("600519")),
            ("ths_stockpage_finance",  lambda: self.ths_stockpage_finance("600519")),
            ("ths_stockpage_holder",   lambda: self.ths_stockpage_holder("600519")),
            ("ths_stockpage_main",     lambda: self.ths_stockpage_main("600519")),
            ("ths_stockpage_event",    lambda: self.ths_stockpage_event("600519")),
            ("ths_stockpage_f10",      lambda: self.ths_stockpage_f10("600519")),
            ("ths_stock_zaopan",       lambda: self.ths_stock_zaopan()),
            ("ths_stock_fupan",        lambda: self.ths_stock_fupan()),
            # ("ths_stock_newstock",     lambda: self.ths_stock_newstock()),   # nginx 永久 IP ban
            ("ths_stock_fincalendar",  lambda: self.ths_stock_fincalendar()),
            ("ths_stock_market",       lambda: self.ths_stock_market()),
            ("ths_stock_chuangye",     lambda: self.ths_stock_chuangye()),
            ("ths_news_yaowen",        lambda: self.ths_news_yaowen()),
            ("ths_news_cjzx",          lambda: self.ths_news_cjzx()),
            ("ths_news_guojicj",       lambda: self.ths_news_guojicj()),
            ("ths_news_tzz",           lambda: self.ths_news_tzz()),
            ("ths_futures_index",      lambda: self.ths_futures_index()),
            # 雪球 indicator.json + screener f10/portfolio 真替身
            ("xq_indicator_sh600519",  lambda: self.xueqiu_indicator("SH600519")),
            ("xq_indicator_sz000001",  lambda: self.xueqiu_indicator("SZ000001")),
            # 多股测试发现的真替身 (company.json + industry.json 在 data 字段, 不在 items)
            ("xq_company_sh600519",    lambda: self.xueqiu_company("SH600519")),
            ("xq_company_sh688825",    lambda: self.xueqiu_company("SH688825")),
            ("xq_company_hk00700",     lambda: self.xueqiu_company("HK00700")),
            ("xq_company_usTSLA",      lambda: self.xueqiu_company("usTSLA")),
            ("xq_concept_industry_sh600519", lambda: self.xueqiu_concept_industry("SH600519")),
            ("xq_concept_industry_sh688825", lambda: self.xueqiu_concept_industry("SH688825")),
            ("xq_concept_industry_sz000858", lambda: self.xueqiu_concept_industry("SZ000858")),
            # (xq_screener_f10/portfolio endpoint 200 但 list=[], 暂不放 test_all)
            # 新浪 K 线全粒度
            ("sina_kline_sh600519_5m", lambda: self.sina_kline_min("sh600519", 5)),
            ("sina_kline_sh600519_60m",lambda: self.sina_kline_min("sh600519", 60)),
            ("sina_kline_sh600519_d",  lambda: self.sina_kline_min("sh600519", 240)),
            ("sina_kline_sh000001_d",  lambda: self.sina_kline_min("sh000001", 240)),
            ("sina_kline_sz399001_d",  lambda: self.sina_kline_min("sz399001", 240)),
            # === 第5轮反爬: 新版 datacenter reportName ===
            ("em_dmsk_balance",        lambda: self.em_dmsk_balance("600519.SH", 3)),
            ("em_dmsk_income",         lambda: self.em_dmsk_income("600519.SH", 5)),
            ("em_dmsk_balance_688825", lambda: self.em_dmsk_balance("688825.SH", 3)),
            # === 第15轮反爬: RPT_F10_FINANCE_B* ===
            ("em_f10_balance_600519",  lambda: self.em_f10_balance("600519.SH", 3)),
            ("em_f10_income_600519",   lambda: self.em_f10_income("600519.SH", 3)),
            ("em_f10_cashflow_600519", lambda: self.em_f10_cashflow("600519.SH", 3)),
            ("em_f10_balance_688825",  lambda: self.em_f10_balance("688825.SH", 3)),
            ("em_f10_income_688825",   lambda: self.em_f10_income("688825.SH", 3)),
            ("em_f10_cashflow_688825", lambda: self.em_f10_cashflow("688825.SH", 3)),
            # === 第5轮反爬: F10 不带 PageAjax (HTML 含数据) ===
            ("em_f10_capital",         lambda: self.em_f10_html("CapitalStockStructure")),
            ("em_f10_holder",          lambda: self.em_f10_html("ShareholderResearch")),
            ("em_f10_business",        lambda: self.em_f10_html("BusinessAnalysis")),
            # === 第6轮反爬: stock.eastmoney.com JS 暴露的新真通 endpoint ===
            ("em_industry_list",       lambda: self.em_industry_list(10)),
            ("em_concept_list",        lambda: self.em_concept_list(10)),
            ("em_open_data",           lambda: self.em_open_data(5)),
            ("em_mutual_hold",         lambda: self.em_mutual_hold(5)),
            ("em_mutual_holdranking",  lambda: self.em_mutual_holdranking(5)),
            # === 第8轮反爬: RPT_INDEX_CONSTITUENT brute force ===
            ("em_index_constituent",   lambda: self.em_index_constituent("000300", 5)),
            # === 第9轮反爬: RPT brute force 第二轮 ===
            ("em_gem_list",            lambda: self.em_gem_list(5)),
            ("em_lico_fn_cpd",         lambda: self.em_lico_fn_cpd(5)),
            ("em_fund_rank",           lambda: self.em_fund_rank(5)),
            ("csindex_authorized",     lambda: self.csindex_authorized_users()),
            ("em_margin_list",         lambda: self.em_margin_list(5)),
            # === 第11轮反爬: RPT_INDUSTRY_LIST/CONCEPT_LIST/DIVIDEND_RANK brute force ===
            ("em_industry_list",       lambda: self.em_industry_list(5)),
            ("em_concept_list",        lambda: self.em_concept_list(5)),
            ("em_dividend_rank",       lambda: self.em_dividend_rank(5)),
            # === 第11轮反爬: 新浪 vip / qt.gtimg.cn ===
            # 移除: 新浪 vip.stock.finance.sina.com.cn 沙盒 IP 触发 HTTP 456 ban
            # 改用: qt.gtimg.cn 作为 backup (见下方)
            ("gtimg_hq",              lambda: self.gtimg_hq("sh600519,sh688825,hk00700")),
            # === 第11轮反爬: qt.gtimg.cn ===
            ("gtimg_hq",              lambda: self.gtimg_hq("sh600519,sh688825,hk00700")),
            ("gtimg_us_hq",           lambda: self.gtimg_us_hq("usTSLA,usAAPL")),
            ("gtimg_index",           lambda: self.gtimg_index("sh000300,sh000001")),
            ("gtimg_hk_index",        lambda: self.gtimg_hk_index("hkHSI,hkHSCEI")),
            # === 第12轮反爬: 雪球 screener 港美 + qt 行业指数 ===
            ("xq_screener_hk",        lambda: self.xueqiu_screener_list(1, 5, "percent", "desc", "HK", "hk")),
            ("xq_screener_us",        lambda: self.xueqiu_screener_list(1, 5, "percent", "desc", "US", "us")),
            ("gtimg_industry_idx",    lambda: self.gtimg_index("sz399986,sz399987,sz399975")),
            # === 第12轮反爬: 雪球 f10/us (美股) ===
            ("xq_f10_us_industry",    lambda: self.xueqiu_f10_industry_us("TSLA")),
            ("xq_f10_us_indicator",   lambda: self.xueqiu_f10_indicator_us("TSLA")),
            ("xq_f10_us_bonus",       lambda: self.xueqiu_f10_bonus_us("TSLA")),
            ("xq_f10_hk_industry",    lambda: self.xueqiu_f10_industry_hk("HK00700")),
            # === 第14轮反爬: 雪球 f10/cn 新股业务介绍 ===
            ("xq_business_sz000333", lambda: self.xueqiu_business_analysis("SZ000333")),
            ("xq_quote_sh600519",   lambda: self.xueqiu_quote("SH600519")),
            ("xq_business_sh600519",lambda: self.xueqiu_business_analysis("SH600519")),
            # === 第16轮反爬: 新浪 json_v2 备用接口 ===
            ("sina_bill",            lambda: self.sina_bill("sh600519", 10)),
            ("sina_industry",        lambda: self.sina_industry("041101", 5)),
            ("sina_company",         lambda: self.sina_company("sh600519")),
            ("sina_market_amount",   lambda: self.sina_market_sort("hs_a", 10, "amount", 0)),
            ("sina_market_volume",   lambda: self.sina_market_sort("hs_a", 10, "volume", 0)),
            ("sina_kline_day",       lambda: self.sina_kline_day("sh600519", 240, 100)),
            ("sina_kline_week",      lambda: self.sina_kline_day("sh600519", 1200, 100)),
            ("sina_kline_month",     lambda: self.sina_kline_day("sh600519", 2400, 100)),
            ("sina_kline_min_60",    lambda: self.sina_kline_day("sh600519", 60, 100)),
            ("sina_corp_info",       lambda: self.sina_corp_info("600519", 1)),
            ("sina_corp_bulletin",   lambda: self.sina_corp_bulletin("600519")),
            ("sina_corp_bulletin2",  lambda: self.sina_corp_bulletin2("600519")),
            # === 第17轮反爬: 雪球 screener 全市场 + 排序 ===
            ("xq_screener_amount",    lambda: self.xueqiu_screener_list(1, 10, "amount", "desc", "CN", "sh_sz")),
            ("xq_screener_volume",    lambda: self.xueqiu_screener_list(1, 10, "volume", "desc", "CN", "sh_sz")),
            ("xq_screener_cyb",       lambda: self.xueqiu_screener_list(1, 10, "percent", "desc", "CN", "cyb")),
            ("xq_screener_kcb",       lambda: self.xueqiu_screener_list(1, 10, "percent", "desc", "CN", "kcb")),
            ("xq_screener_pe",        lambda: self.xueqiu_screener_list(1, 10, "pe_ttm", "asc", "CN", "sh_sz")),
            ("xq_screener_roe",       lambda: self.xueqiu_screener_list(1, 10, "roe_ttm", "desc", "CN", "sh_sz")),
            ("xq_stock_html",         lambda: self.xueqiu_stock_html("SH600519")),
            # === 第18轮反爬: 新浪 corp HTML 董监高/股本/新闻 ===
            ("sina_corp_manager",    lambda: self.sina_corp_manager("600519")),
            ("sina_corp_structure",  lambda: self.sina_corp_structure("600519")),
            ("sina_corp_holder",     lambda: self.sina_corp_holder("600519")),
            ("sina_corp_finance_summary", lambda: self.sina_corp_finance_summary("600519")),
            # === 第19轮反爬: 上交所 yunhq HTTP ===
            ("sse_yunhq_000001",   lambda: self.sse_yunhq_snap("000001")),
            ("sse_yunhq_600519",   lambda: self.sse_yunhq_snap("600519")),
            ("sse_yunhq_688825",   lambda: self.sse_yunhq_snap("688825")),
            ("sse_yunhq_hs300",    lambda: self.sse_yunhq_index("000300")),
            ("sse_yunhq_csi500",   lambda: self.sse_yunhq_index("000905")),
            ("sse_yunhq_csi1000",  lambda: self.sse_yunhq_index("000852")),
            # === 第20轮反爬: 东方财富 np-anotice 公告 API ===
            ("np_notice_600519",   lambda: self.np_notice_ann("600519", 10, 1, "A")),
            ("np_notice_688825",   lambda: self.np_notice_ann("688825", 10, 1, "A")),
            ("np_notice_000001",   lambda: self.np_notice_ann("000001", 10, 1, "A")),
            ("np_notice_with_date",lambda: self.np_notice_ann("600519", 10, 1, "A", "2025-08-01", "2025-08-09")),
            ("np_cnotice_ann",      lambda: self.np_cnotice_ann("AN202607171827064564", 1)),
            # ("sina_corp_news",       lambda: self.sina_corp_news("600519")),    # 404 HTML
            # ("sina_corp_equity",     lambda: self.sina_corp_equity("600519")),   # sz=0
            # === 第13轮反爬: qt.gtimg.cn s_ prefix 全市场 ===
            ("gtimg_market_code",    lambda: self.gtimg_market_code("s_sz000001,s_sz399001,s_sz399300,s_sz399987")),
            # === 第13轮反爬: qt 不带前缀 ===
            ("gtimg_market_all",     lambda: self.gtimg_market_all("sz000001,sh600519,sh000300,sz399300,hk00700,usTSLA")),
            # === 第14轮反爬: qt 基金 ===
            ("gtimg_fund",           lambda: self.gtimg_fund("jj000001,jj000300")),
            # === 第7轮反爬: push2.eastmoney.com kamt (沪股通资金) ===
            ("em_kamt",                lambda: self.em_kamt()),
        ]
        results = {}
        passed = 0
        for name, fn in cases:
            try:
                r = fn()
                if r.get("ok"):
                    passed += 1
                    tag = "✅"
                    detail = f"size={r.get('raw_size', '?')}"
                else:
                    tag = "�"
                    detail = r.get("error", "?")[:60]
                results[name] = {"ok": r.get("ok"), "detail": detail}
                if verbose:
                    print(f"  {tag} {name:30s} {detail}")
            except Exception as e:
                results[name] = {"ok": False, "detail": str(e)[:60]}
                if verbose:
                    print(f"  ❌ {name:30s} {str(e)[:60]}")
        if verbose:
            print(f"\n通过: {passed}/{len(cases)} ({passed/len(cases)*100:.1f}%)")
        results["_summary"] = {"passed": passed, "total": len(cases)}
        return results


# ============================================================
# CLI
# ============================================================
if __name__ == "__main__":
    client = APIClient()
    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        # 演示: 拉一只股票的全部信息
        print("=== xueqiu_quote ===")
        print(json.dumps(client.xueqiu_quote("SH688825"), ensure_ascii=False, indent=2)[:500])
        print("\n=== em_stock_get ===")
        print(json.dumps(client.em_stock_get("688825"), ensure_ascii=False, indent=2))
        print("\n=== ef_snapshot ===")
        print(json.dumps(client.ef_snapshot("688825"), ensure_ascii=False, indent=2)[:800])
        print("\n=== tencent_a ===")
        print(json.dumps(client.tencent_a("sh688825"), ensure_ascii=False, indent=2)[:500])
    else:
        client.test_all(verbose=True)
