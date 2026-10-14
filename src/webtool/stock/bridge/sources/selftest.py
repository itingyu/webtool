"""全量自检 —— 逐个打真接口, 返回 {name: ok/error}

从原 `api_client.test_all` 还原 (拆包时丢了)。它是拆包与重构的主要防回归
工具: 漏拆一个模块级函数、加错一个 import, 单点调用未必撞上, 这里 29 个
case 会立刻把 NameError 打出来。

用法:
    python -m webtool.stock.bridge.sources.selftest        # 全部
    python -m webtool.stock.bridge.sources.selftest em     # 只打 em 源的
"""
import json
import sys

_CASES = [

        # 雪球
        ("xueqiu_quote",           lambda c: c.xueqiu_quote("SH688825")),
        ("xueqiu_f10_company",     lambda c: c.xueqiu_f10_company("SH688825")),
        ("xueqiu_f10_business",    lambda c: c.xueqiu_f10_business("SH688825")),
        ("xueqiu_kline_day",       lambda c: c.xueqiu_kline_day("SH688825")),
        ("xueqiu_kline_week",      lambda c: c.xueqiu_kline_week("SH688825")),
        ("xueqiu_realtime_batch",  lambda c: c.xueqiu_realtime_batch("SH688825,SH600519")),
        ("xueqiu_industry",        lambda c: c.xueqiu_industry("SH688825")),
        ("xueqiu_top_holders",     lambda c: c.xueqiu_top_holders("SH600519")),
        # 同花顺
        # ("ths_industry_list",      lambda c: c.ths_industry_list()),  # nginx 永久 IP ban
        # ("ths_concept_list",       lambda c: c.ths_concept_list()),   # nginx 永久 IP ban
        # ("ths_industry_detail",    lambda c: c.ths_industry_detail("881270")),  # nginx 永久 IP ban
        ("ths_bk_kline",           lambda c: c.ths_bk_kline("881270", 2026)),
        # 东财
        ("em_stock_get",           lambda c: c.em_stock_get("688825")),
        ("em_kline",               lambda c: c.em_kline("688825")),
        ("em_datacenter",          lambda c: c.em_datacenter()),
        ("em_f10_company",         lambda c: c.em_f10_company("SH688825")),
        ("em_f10_profile",         lambda c: c.em_f10_profile("SH688825")),
        # === 第11轮反爬: PC_HSF10/CompanySurvey/PageAjax ===
        ("em_company_survey",      lambda c: c.em_company_survey("SH600519")),
        ("em_capital_structure",   lambda c: c.em_capital_structure("SH600519")),
        ("em_profit_forecast",     lambda c: c.em_profit_forecast("SH600519")),
        # 巨潮
        ("cninfo_company_profile", lambda c: c.cninfo_company_profile("688825")),
        ("cninfo_index",           lambda c: c.cninfo_index()),
        # 新浪
        ("sina_hq_a",              lambda c: c.sina_hq_a("sh688825")),
        ("sina_hq_batch",          lambda c: c.sina_hq_batch()),
        ("sina_hq_hk",             lambda c: c.sina_hq_hk("01810")),
        ("sina_top_chg",           lambda c: c.sina_top_chg(5)),
        # 腾讯
        ("tencent_a",              lambda c: c.tencent_a("sh688825")),
        ("tencent_batch",          lambda c: c.tencent_batch()),
        ("tencent_hk",             lambda c: c.tencent_hk("hk01810")),
        # efinance
        ("ef_snapshot_a",          lambda c: c.ef_snapshot("688825")),
        ("ef_history_a",           lambda c: c.ef_history("688825")),
        ("ef_base_info",           lambda c: c.ef_base_info("688825")),
        ("ef_snapshot_hk",         lambda c: c.ef_snapshot("hk01810")),
        ("ef_snapshot_us",         lambda c: c.ef_snapshot("usTSLA")),
        # === 扩展接口 (api_docs_extra.md) ===
        # 雪球 screener
        ("xq_screener_sha",        lambda c: c.xueqiu_screener("sha")),
        ("xq_screener_sza",        lambda c: c.xueqiu_screener("sza")),
        ("xq_screener_us",         lambda c: c.xueqiu_screener("us")),
        ("xq_screener_hk",         lambda c: c.xueqiu_screener("hk")),
        # 雪球 kline month + 老股股东
        ("xq_kline_month",         lambda c: c.xueqiu_kline_month("SH688825")),
        ("xq_top_holders_full",    lambda c: c.xueqiu_top_holders_full("SH600519")),
        ("xq_skholderchg_full",    lambda c: c.xueqiu_skholderchg_full("SH600519")),
        # 中证
        ("csindex_300",            lambda c: c.csindex_perf("000300")),
        ("csindex_500",            lambda c: c.csindex_perf("000905")),
        ("csindex_1000",           lambda c: c.csindex_perf("000852")),
        # 东财 F10
        ("em_capital_structure",   lambda c: c.em_capital_structure("SH600519")),
        ("em_shareholder_research",lambda c: c.em_shareholder_research("SH600519")),
        ("em_business_analysis",   lambda c: c.em_business_analysis("SH600519")),
        ("em_new_finance_analysis",lambda c: c.em_new_finance_analysis("SH600519")),
        # 东财 F10 datacenter
        ("em_f10_main_finadata",   lambda c: c.em_f10_main_finadata("600519.SH")),
        ("em_f10_gincome",         lambda c: c.em_f10_gincome("600519.SH")),
        # 新浪
        ("sina_cyb",               lambda c: c.sina_list(node="cyb", num=3)),
        ("sina_kcb",               lambda c: c.sina_list(node="kcb", num=3)),
        ("sina_hs_b",              lambda c: c.sina_list(node="hs_b", num=3)),
        # 腾讯
        ("tencent_us_tsla",        lambda c: c.tencent_us("usTSLA")),
        ("tencent_us_aapl",        lambda c: c.tencent_us("usAAPL")),
        ("tencent_idx_hs300",      lambda c: c.tencent_index("s_sh000300")),
        ("tencent_idx_cyb",        lambda c: c.tencent_index("s_sz399006")),
        # === 第二轮探活 (api_docs_extra §七) ===
        ("em_f10_lico_cpd",        lambda c: c.em_f10_lico_fn_cpd("600519.SH")),
        # ("ths_concept_by_199112",  lambda c: c.ths_concept_by_addtime()),  # nginx 永久 IP ban
        ("ths_bk_kline_v2",        lambda c: c.ths_bk_kline_v2("881270", 2026)),
        ("sina_hs_a",              lambda c: c.sina_list(node="hs_a", num=3)),
        ("sina_sh_a",              lambda c: c.sina_list(node="sh_a", num=3)),
        ("sina_sz_a",              lambda c: c.sina_list(node="sz_a", num=3)),
        ("sina_corp_balance",      lambda c: c.sina_corp_finance("600519", "vFD_BalanceSheet")),
        ("csindex_000001",         lambda c: c.csindex_perf("000001")),
        ("csindex_000016",         lambda c: c.csindex_perf("000016")),
        # === 反爬抢救接口 (api_docs_rescued.md) ===
        # 腾讯 web.ifzq 全市场 K 线/分时
        ("tx_kline_hk00700",       lambda c: c.tencent_kline_global("hk00700", "day", 10)),
        ("tx_kline_sh600519",      lambda c: c.tencent_kline_global("sh600519", "day", 10)),
        ("tx_kline_usTSLA",        lambda c: c.tencent_kline_global("usTSLA", "day", 10)),
        ("tx_us_kline_tsla",       lambda c: c.tencent_us_kline("usTSLA", "day", 10)),
        ("tx_us_kline_aapl",       lambda c: c.tencent_us_kline("usAAPL", "day", 10)),
        ("tx_minute_sh600519",     lambda c: c.tencent_minute("sh600519")),
        ("tx_minute_hk00700",      lambda c: c.tencent_minute("hk00700")),
        ("tx_minute_usTSLA",       lambda c: c.tencent_minute("usTSLA")),
        # 腾讯 qt.gtimg.cn 全 market 真通
        ("tx_global_usAAPL",       lambda c: c.tencent_global("usAAPL")),
        ("tx_global_usNVDA",       lambda c: c.tencent_global("usNVDA")),
        ("tx_global_hk00700",      lambda c: c.tencent_global("hk00700")),
        ("tx_global_hk09988",      lambda c: c.tencent_global("hk09988")),
        ("tx_global_bSH900901",    lambda c: c.tencent_global("sh900901")),
        ("tx_global_idx_dji",      lambda c: c.tencent_global("usDJI")),
        ("tx_global_idx_hsi",      lambda c: c.tencent_global("hkHSI")),
        # 巨潮公告 + PDF
        ("cninfo_anno_sh688825",   lambda c: c.cninfo_announcement("688825", "9920000008")),
        ("cninfo_anno_sh600519",   lambda c: c.cninfo_announcement("600519", "gssh0600519")),
        ("cninfo_fulltext_gzmt",   lambda c: c.cninfo_fulltext_search("贵州茅台")),
        ("cninfo_szse_stock",      lambda c: c.cninfo_szse_stock_list()),
        # 中证 dataServer
        ("csindex_industry",       lambda c: c.csindex_industry_classify("1")),
        ("csindex_agents",         lambda c: c.csindex_agents_list()),
        # 雪球 industry 全列表
        ("xq_industry_full",       lambda c: c.xueqiu_industry_list_full("SH600519")),
        # 第7轮反爬: 雪球 f10 business_analysis + bonus
        ("xq_business_sh688825",   lambda c: c.xueqiu_business_analysis("SH688825")),
        ("xq_business_sh600519",   lambda c: c.xueqiu_business_analysis("SH600519")),
        ("xq_bonus_sh600519",      lambda c: c.xueqiu_bonus("SH600519")),
        # === 第10轮反爬: 雪球 f10/cn/industry.json 概念 ===
        ("xq_f10_concept_688825", lambda c: c.xueqiu_f10_concept("SH688825")),
        ("xq_f10_concept_600519", lambda c: c.xueqiu_f10_concept("SH600519")),
        # === 第10轮反爬: 雪球 screener/quote/list.json ===
        ("xq_screener_top",        lambda c: c.xueqiu_screener_list(1, 5, "percent", "desc")),
        # === 同花顺 data.10jqka.com.cn 子域 (反爬绕过) ===
        # ("ths_rank_cxfl",          lambda c: c.ths_rank_cxfl()),        # nginx 永久 IP ban
        # ("ths_market_rzrq",        lambda c: c.ths_market_rzrq()),      # nginx 永久 IP ban
        # ("ths_funds_ggzjl",        lambda c: c.ths_funds_ggzjl()),      # nginx 永久 IP ban
        # ("ths_funds_hyzjl",        lambda c: c.ths_funds_hyzjl()),      # nginx 永久 IP ban
        # ("ths_market_dzjy",        lambda c: c.ths_market_dzjy()),      # nginx 永久 IP ban
        # ("ths_ipo_xgpt",           lambda c: c.ths_ipo_xgpt()),         # nginx 永久 IP ban
        # ("ths_ipo_xgyp",           lambda c: c.ths_ipo_xgyp()),         # nginx 永久 IP ban
        # ("ths_market_ggsyl",       lambda c: c.ths_market_ggsyl()),     # nginx 永久 IP ban
        ("ths_stockpage_news",     lambda c: c.ths_stockpage_news("600519")),
        ("ths_stockpage_finance",  lambda c: c.ths_stockpage_finance("600519")),
        ("ths_stockpage_holder",   lambda c: c.ths_stockpage_holder("600519")),
        ("ths_stockpage_main",     lambda c: c.ths_stockpage_main("600519")),
        ("ths_stockpage_event",    lambda c: c.ths_stockpage_event("600519")),
        ("ths_stockpage_f10",      lambda c: c.ths_stockpage_f10("600519")),
        ("ths_stock_zaopan",       lambda c: c.ths_stock_zaopan()),
        ("ths_stock_fupan",        lambda c: c.ths_stock_fupan()),
        # ("ths_stock_newstock",     lambda c: c.ths_stock_newstock()),   # nginx 永久 IP ban
        ("ths_stock_fincalendar",  lambda c: c.ths_stock_fincalendar()),
        ("ths_stock_market",       lambda c: c.ths_stock_market()),
        ("ths_stock_chuangye",     lambda c: c.ths_stock_chuangye()),
        ("ths_news_yaowen",        lambda c: c.ths_news_yaowen()),
        ("ths_news_cjzx",          lambda c: c.ths_news_cjzx()),
        ("ths_news_guojicj",       lambda c: c.ths_news_guojicj()),
        ("ths_news_tzz",           lambda c: c.ths_news_tzz()),
        ("ths_futures_index",      lambda c: c.ths_futures_index()),
        # 雪球 indicator.json + screener f10/portfolio 真替身
        ("xq_indicator_sh600519",  lambda c: c.xueqiu_indicator("SH600519")),
        ("xq_indicator_sz000001",  lambda c: c.xueqiu_indicator("SZ000001")),
        # 多股测试发现的真替身 (company.json + industry.json 在 data 字段, 不在 items)
        ("xq_company_sh600519",    lambda c: c.xueqiu_company("SH600519")),
        ("xq_company_sh688825",    lambda c: c.xueqiu_company("SH688825")),
        ("xq_company_hk00700",     lambda c: c.xueqiu_company("HK00700")),
        ("xq_company_usTSLA",      lambda c: c.xueqiu_company("usTSLA")),
        ("xq_concept_industry_sh600519", lambda c: c.xueqiu_concept_industry("SH600519")),
        ("xq_concept_industry_sh688825", lambda c: c.xueqiu_concept_industry("SH688825")),
        ("xq_concept_industry_sz000858", lambda c: c.xueqiu_concept_industry("SZ000858")),
        # (xq_screener_f10/portfolio endpoint 200 但 list=[], 暂不放 test_all)
        # 新浪 K 线全粒度
        ("sina_kline_sh600519_5m", lambda c: c.sina_kline_min("sh600519", 5)),
        ("sina_kline_sh600519_60m",lambda c: c.sina_kline_min("sh600519", 60)),
        ("sina_kline_sh600519_d",  lambda c: c.sina_kline_min("sh600519", 240)),
        ("sina_kline_sh000001_d",  lambda c: c.sina_kline_min("sh000001", 240)),
        ("sina_kline_sz399001_d",  lambda c: c.sina_kline_min("sz399001", 240)),
        # === 第5轮反爬: 新版 datacenter reportName ===
        ("em_dmsk_balance",        lambda c: c.em_dmsk_balance("600519.SH", 3)),
        ("em_dmsk_income",         lambda c: c.em_dmsk_income("600519.SH", 5)),
        ("em_dmsk_balance_688825", lambda c: c.em_dmsk_balance("688825.SH", 3)),
        # === 第15轮反爬: RPT_F10_FINANCE_B* ===
        ("em_f10_balance_600519",  lambda c: c.em_f10_balance("600519.SH", 3)),
        ("em_f10_income_600519",   lambda c: c.em_f10_income("600519.SH", 3)),
        ("em_f10_cashflow_600519", lambda c: c.em_f10_cashflow("600519.SH", 3)),
        ("em_f10_balance_688825",  lambda c: c.em_f10_balance("688825.SH", 3)),
        ("em_f10_income_688825",   lambda c: c.em_f10_income("688825.SH", 3)),
        ("em_f10_cashflow_688825", lambda c: c.em_f10_cashflow("688825.SH", 3)),
        # === 第5轮反爬: F10 不带 PageAjax (HTML 含数据) ===
        ("em_f10_capital",         lambda c: c.em_f10_html("CapitalStockStructure")),
        ("em_f10_holder",          lambda c: c.em_f10_html("ShareholderResearch")),
        ("em_f10_business",        lambda c: c.em_f10_html("BusinessAnalysis")),
        # === 第6轮反爬: stock.eastmoney.com JS 暴露的新真通 endpoint ===
        ("em_industry_list",       lambda c: c.em_industry_list(10)),
        ("em_concept_list",        lambda c: c.em_concept_list(10)),
        ("em_open_data",           lambda c: c.em_open_data(5)),
        ("em_mutual_hold",         lambda c: c.em_mutual_hold(5)),
        ("em_mutual_holdranking",  lambda c: c.em_mutual_holdranking(5)),
        # === 第8轮反爬: RPT_INDEX_CONSTITUENT brute force ===
        ("em_index_constituent",   lambda c: c.em_index_constituent("000300", 5)),
        # === 第9轮反爬: RPT brute force 第二轮 ===
        ("em_gem_list",            lambda c: c.em_gem_list(5)),
        ("em_lico_fn_cpd",         lambda c: c.em_lico_fn_cpd(5)),
        ("em_fund_rank",           lambda c: c.em_fund_rank(5)),
        ("csindex_authorized",     lambda c: c.csindex_authorized_users()),
        ("em_margin_list",         lambda c: c.em_margin_list(5)),
        # === 第11轮反爬: RPT_INDUSTRY_LIST/CONCEPT_LIST/DIVIDEND_RANK brute force ===
        ("em_industry_list",       lambda c: c.em_industry_list(5)),
        ("em_concept_list",        lambda c: c.em_concept_list(5)),
        ("em_dividend_rank",       lambda c: c.em_dividend_rank(5)),
        # === 第11轮反爬: 新浪 vip / qt.gtimg.cn ===
        # 移除: 新浪 vip.stock.finance.sina.com.cn 沙盒 IP 触发 HTTP 456 ban
        # 改用: qt.gtimg.cn 作为 backup (见下方)
        ("gtimg_hq",              lambda c: c.gtimg_hq("sh600519,sh688825,hk00700")),
        # === 第11轮反爬: qt.gtimg.cn ===
        ("gtimg_hq",              lambda c: c.gtimg_hq("sh600519,sh688825,hk00700")),
        ("gtimg_us_hq",           lambda c: c.gtimg_us_hq("usTSLA,usAAPL")),
        ("gtimg_index",           lambda c: c.gtimg_index("sh000300,sh000001")),
        ("gtimg_hk_index",        lambda c: c.gtimg_hk_index("hkHSI,hkHSCEI")),
        # === 第12轮反爬: 雪球 screener 港美 + qt 行业指数 ===
        ("xq_screener_hk",        lambda c: c.xueqiu_screener_list(1, 5, "percent", "desc", "HK", "hk")),
        ("xq_screener_us",        lambda c: c.xueqiu_screener_list(1, 5, "percent", "desc", "US", "us")),
        ("gtimg_industry_idx",    lambda c: c.gtimg_index("sz399986,sz399987,sz399975")),
        # === 第12轮反爬: 雪球 f10/us (美股) ===
        ("xq_f10_us_industry",    lambda c: c.xueqiu_f10_industry_us("TSLA")),
        ("xq_f10_us_indicator",   lambda c: c.xueqiu_f10_indicator_us("TSLA")),
        ("xq_f10_us_bonus",       lambda c: c.xueqiu_f10_bonus_us("TSLA")),
        ("xq_f10_hk_industry",    lambda c: c.xueqiu_f10_industry_hk("HK00700")),
        # === 第14轮反爬: 雪球 f10/cn 新股业务介绍 ===
        ("xq_business_sz000333", lambda c: c.xueqiu_business_analysis("SZ000333")),
        ("xq_quote_sh600519",   lambda c: c.xueqiu_quote("SH600519")),
        ("xq_business_sh600519",lambda c: c.xueqiu_business_analysis("SH600519")),
        # === 第16轮反爬: 新浪 json_v2 备用接口 ===
        ("sina_bill",            lambda c: c.sina_bill("sh600519", 10)),
        ("sina_industry",        lambda c: c.sina_industry("041101", 5)),
        ("sina_company",         lambda c: c.sina_company("sh600519")),
        ("sina_market_amount",   lambda c: c.sina_market_sort("hs_a", 10, "amount", 0)),
        ("sina_market_volume",   lambda c: c.sina_market_sort("hs_a", 10, "volume", 0)),
        ("sina_kline_day",       lambda c: c.sina_kline_day("sh600519", 240, 100)),
        ("sina_kline_week",      lambda c: c.sina_kline_day("sh600519", 1200, 100)),
        ("sina_kline_month",     lambda c: c.sina_kline_day("sh600519", 2400, 100)),
        ("sina_kline_min_60",    lambda c: c.sina_kline_day("sh600519", 60, 100)),
        ("sina_corp_info",       lambda c: c.sina_corp_info("600519", 1)),
        ("sina_corp_bulletin",   lambda c: c.sina_corp_bulletin("600519")),
        ("sina_corp_bulletin2",  lambda c: c.sina_corp_bulletin2("600519")),
        # === 第17轮反爬: 雪球 screener 全市场 + 排序 ===
        ("xq_screener_amount",    lambda c: c.xueqiu_screener_list(1, 10, "amount", "desc", "CN", "sh_sz")),
        ("xq_screener_volume",    lambda c: c.xueqiu_screener_list(1, 10, "volume", "desc", "CN", "sh_sz")),
        ("xq_screener_cyb",       lambda c: c.xueqiu_screener_list(1, 10, "percent", "desc", "CN", "cyb")),
        ("xq_screener_kcb",       lambda c: c.xueqiu_screener_list(1, 10, "percent", "desc", "CN", "kcb")),
        ("xq_screener_pe",        lambda c: c.xueqiu_screener_list(1, 10, "pe_ttm", "asc", "CN", "sh_sz")),
        ("xq_screener_roe",       lambda c: c.xueqiu_screener_list(1, 10, "roe_ttm", "desc", "CN", "sh_sz")),
        ("xq_stock_html",         lambda c: c.xueqiu_stock_html("SH600519")),
        # === 第18轮反爬: 新浪 corp HTML 董监高/股本/新闻 ===
        ("sina_corp_manager",    lambda c: c.sina_corp_manager("600519")),
        ("sina_corp_structure",  lambda c: c.sina_corp_structure("600519")),
        ("sina_corp_holder",     lambda c: c.sina_corp_holder("600519")),
        ("sina_corp_finance_summary", lambda c: c.sina_corp_finance_summary("600519")),
        # === 第19轮反爬: 上交所 yunhq HTTP ===
        ("sse_yunhq_000001",   lambda c: c.sse_yunhq_snap("000001")),
        ("sse_yunhq_600519",   lambda c: c.sse_yunhq_snap("600519")),
        ("sse_yunhq_688825",   lambda c: c.sse_yunhq_snap("688825")),
        ("sse_yunhq_hs300",    lambda c: c.sse_yunhq_index("000300")),
        ("sse_yunhq_csi500",   lambda c: c.sse_yunhq_index("000905")),
        ("sse_yunhq_csi1000",  lambda c: c.sse_yunhq_index("000852")),
        # === 第20轮反爬: 东方财富 np-anotice 公告 API ===
        ("np_notice_600519",   lambda c: c.np_notice_ann("600519", 10, 1, "A")),
        ("np_notice_688825",   lambda c: c.np_notice_ann("688825", 10, 1, "A")),
        ("np_notice_000001",   lambda c: c.np_notice_ann("000001", 10, 1, "A")),
        ("np_notice_with_date",lambda c: c.np_notice_ann("600519", 10, 1, "A", "2025-08-01", "2025-08-09")),
        ("np_cnotice_ann",      lambda c: c.np_cnotice_ann("AN202607171827064564", 1)),
        # ("sina_corp_news",       lambda c: c.sina_corp_news("600519")),    # 404 HTML
        # ("sina_corp_equity",     lambda c: c.sina_corp_equity("600519")),   # sz=0
        # === 第13轮反爬: qt.gtimg.cn s_ prefix 全市场 ===
        ("gtimg_market_code",    lambda c: c.gtimg_market_code("s_sz000001,s_sz399001,s_sz399300,s_sz399987")),
        # === 第13轮反爬: qt 不带前缀 ===
        ("gtimg_market_all",     lambda c: c.gtimg_market_all("sz000001,sh600519,sh000300,sz399300,hk00700,usTSLA")),
        # === 第14轮反爬: qt 基金 ===
        ("gtimg_fund",           lambda c: c.gtimg_fund("jj000001,jj000300")),
        # === 第7轮反爬: push2.eastmoney.com kamt (沪股通资金) ===
        ("em_kamt",                lambda c: c.em_kamt()),
]


def _run(cases, verbose=True, client=None):
    """跑给定 case 列表, 返回 {name: True | 错误信息}"""
    if client is None:
        from webtool.stock.bridge.sources import APIClient
        client = APIClient()
    out = {}
    for name, fn in cases:
        try:
            r = fn(client)
            ok = bool(r.get('ok')) if isinstance(r, dict) else bool(r)
            out[name] = ok or (None if ok else str(r.get('error'))[:120])
            if verbose:
                mark = 'ok  ' if ok else 'FAIL'
                detail = '' if ok else str(out[name])
                print(f'{mark} {name:28s} {detail}')
        except Exception as e:                          # noqa: BLE001
            out[name] = f'{type(e).__name__}: {e}'
            if verbose:
                print(f'FAIL {name:28s} {type(e).__name__}: {str(e)[:100]}')
    return out


def selftest(verbose=True, source=None, client=None):
    """source=None 跑全部; 给源名 ('em'/'ths'/...) 只跑该源的 case"""
    cases = _CASES
    if source:
        cases = [c for c in cases if c[0].startswith(source + '_')
                 or c[0].startswith(source)]
    out = _run(cases, verbose=verbose, client=client)
    n = sum(1 for v in out.values() if v is True)
    if verbose:
        print(f'\n{n}/{len(out)} 通')
    return out


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    out = selftest(verbose=True, source=argv[0] if argv else None)
    if '-json' in argv:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if all(v is True for v in out.values()) else 1


if __name__ == '__main__':
    sys.exit(main())
