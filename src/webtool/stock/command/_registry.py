"""动作表与用法文本 (单一事实来源, 入口从这里取)"""
"""webtool stock 子命令: 动作分发 + 输出渲染

两座桥 (bridge/engine.py 脚本层 / bridge/srv.py 编排层) 在这里汇合成一个扁平的动作表。动作分三类:

    数据动作  quote pool check calendar flow news announcement financials
              analyze screen risk            —— 走 engine 脚本层
    透传动作  mcp <tool>                     —— 按名调用 24 个动作 (未单独暴露的那些)
    元动作   tools health                    —— 能力清单与两侧探活

输出与 webtool 其他数据命令一致: 数据动作按 args.format 自己渲染 (json 全字段 /
text 行内可读 / markdown 表格), 走 cli.app._run 的 emit 落盘通道。

口径纪律 (从 stock-master 继承, 现由 engine 维护):
  - 接口返回 0/空 不当正常值, 由各桥透传 status, 渲染时显式标注
  - 北向资金不可用必须显式 ⚠, 不填 0
  - 池/榜单类结果必带数据日 (date), 涨停池尤其 —— 接口对无效日期会静默回旧数据
"""



from webtool.stock.command._actions import _act_analyze
from webtool.stock.command._actions import _act_announcement
from webtool.stock.command._actions_data import _act_api_list
from webtool.stock.command._actions_data import _act_api_search
from webtool.stock.command._actions import _act_calendar
from webtool.stock.command._actions import _act_check
from webtool.stock.command._actions_data import _act_data
from webtool.stock.command._actions_data import _act_data_call
from webtool.stock.command._actions_data import _act_data_find
from webtool.stock.command._actions_data import _act_data_health
from webtool.stock.command._actions_data import _act_data_list
from webtool.stock.command._actions_data import _act_data_url
from webtool.stock.command._actions import _act_diagram
from webtool.stock.command._actions_misc import _act_docs_book
from webtool.stock.command._actions_misc import _act_docs_books
from webtool.stock.command._actions_misc import _act_docs_endpoint
from webtool.stock.command._actions_misc import _act_docs_report
from webtool.stock.command._actions_misc import _act_docs_search
from webtool.stock.command._actions_misc import _act_docs_section
from webtool.stock.command._actions_misc import _act_docs_stats
from webtool.stock.command._actions_misc import _act_eco
from webtool.stock.command._actions_misc import _act_eco_health
from webtool.stock.command._actions_misc import _act_eco_list
from webtool.stock.command._actions_misc import _act_eco_search
from webtool.stock.command._actions_misc import _act_em_ctype
from webtool.stock.command._actions_misc import _act_em_report
from webtool.stock.command._actions_misc import _act_em_reports
from webtool.stock.command._actions_misc import _act_em_run
from webtool.stock.command._actions import _act_excel
from webtool.stock.command._actions import _act_financials
from webtool.stock.command._actions import _act_flow
from webtool.stock.command._actions import _act_forecast
from webtool.stock.command._actions_misc import _act_health
from webtool.stock.command._actions import _act_holder
from webtool.stock.command._actions_misc import _act_http_get
from webtool.stock.command._actions_misc import _act_http_post
from webtool.stock.command._actions_misc import _act_http_rows
from webtool.stock.command._actions import _act_kline
from webtool.stock.command._actions import _act_intraday
from webtool.stock.command._actions import _act_boards
from webtool.stock.command._actions_misc import _act_mcp
from webtool.stock.command._actions import _act_news
from webtool.stock.command._actions import _act_pool
from webtool.stock.command._actions import _act_quote
from webtool.stock.command._actions import _act_report
from webtool.stock.command._actions import _act_risk
from webtool.stock.command._actions import _act_screen
from webtool.stock.command._actions import _act_sentiment
from webtool.stock.command._actions import _act_std
from webtool.stock.command._actions_misc import _act_tools
from webtool.stock.command._common import _looks_like_list
from webtool.stock.command._actions_misc import _old_api

ACTIONS = {
    'quote': _act_quote, 'pool': _act_pool, 'check': _act_check,
    'calendar': _act_calendar, 'flow': _act_flow, 'news': _act_news,
    'announcement': _act_announcement, 'financials': _act_financials,
    'analyze': _act_analyze, 'screen': _act_screen, 'risk': _act_risk,
    'report': _act_report, 'excel': _act_excel, 'sentiment': _act_sentiment,
    'diagram': _act_diagram,
    'mcp': _act_mcp, 'tools': _act_tools, 'health': _act_health,
    'holder': _act_holder, 'forecast': _act_forecast,

    # 编排层动作升格 (原来只能 mcp --tool 透传)
    'kline': _act_kline,
    'intraday': _act_intraday,
    'boards': _act_boards,
    'index': _act_std('stock_index'),
    'income': _act_std('stock_income_statement'),
    'balance': _act_std('stock_balance_sheet'),
    'cashflow': _act_std('stock_cashflow'),
    'company': _act_std('stock_company'),
    'business': _act_std('stock_business_analysis'),
    'holders': _act_std('stock_top_holders'),
    'holder_chg': _act_std('stock_holder_change'),
    'industry': _act_std('stock_industry_list'),
    'concept': _act_std('stock_concept_list'),
    'industry_of': _act_std('stock_industry_concept'),
    'dividend': _act_std('stock_dividend_rank'),
    'margin': _act_std('stock_margin_list'),
    'screener': _act_std('stock_screener'),
    'ipo': _act_std('stock_ipo'),

    # 通用取数入口 (融合原 api/eco/http/em/docs 五组)
    'data': _act_data, 'data-find': _act_data_find, 'data-call': _act_data_call,
    'data-url': _act_data_url, 'data-list': _act_data_list,
    'data-health': _act_data_health,

    # 兼容别名 → data 子动作 (隐藏不宣传, 下一大版本删)
    'api': lambda a, c: _act_data_list(a, c) if _looks_like_list(a) else _old_api(a),
    'api-list': _act_api_list, 'api-search': _act_api_search,
    'eco': _act_eco, 'eco-search': _act_eco_search,
    'eco-list': _act_eco_list, 'eco-health': _act_eco_health,
    'http-get': _act_http_get, 'http-post': _act_http_post,
    'http-rows': _act_http_rows, 'em-report': _act_em_report,
    'em-ctype': _act_em_ctype,
    'em-reports': _act_em_reports, 'em-run': _act_em_run,
    'docs-books': _act_docs_books, 'docs-stats': _act_docs_stats,
    'docs-search': _act_docs_search, 'docs-book': _act_docs_book,
    'docs-section': _act_docs_section, 'docs-report': _act_docs_report,
    'docs-endpoint': _act_docs_endpoint,
}

USAGE = """用法: webtool stock <动作> [参数]

数据动作 (走 engine 脚本层)
  quote <代码...>              实时行情, 支持指数别名(上证指数/创业板指)
  pool [--date D] [--only-buy] 涨停池 (连板/首封/炸板/封单/行业)
  check <代码...>              可买性核查 (板块归属 + ST/退市风险)
  calendar [--date D] [-n N]   交易日历
  flow [--scope industry|individual|north]  资金流榜单
  news <代码> [-n N]           个股新闻
  announcement <代码> [-n N]   公告列表
  financials <代码>            核心财务指标
  analyze <代码>               单股深度 (技术面+评分+决策信号+画像)
  screen [--pool short|mid|long] [--min-score N]  选股池
  risk <代码...>               风险核查 (重组/减持/立案/预亏)
  report <代码> | --pool short  成稿研报 (markdown, 单股/短线池)
  excel --excel 路径 [--min-score N]   选股池导出 xlsx (需 openpyxl)
  sentiment <代码> | --text "..."      消息面打分 -100~+100 (不给 --text 则给该股新闻打分)
  diagram --kind logic|tree|chain [...] mermaid 图
             tree  无参; logic 需 代码 --name [--thesis];
             chain 需 --name --driver(上游) --mid(中游) --catalyst(下游)
  kline <代码> [--bars 120 | --start D --end D] [--period day|week|month]
              [--ma 5,10,20] [--chart] [--chart-out 路径] [--png]
             K 线 (A股/港股/美股); --start/--end 指定区间;
             --chart 出图 (红涨绿跌+均线+量能), --png 转 PNG
  intraday <代码> [--days 1|5] [--no-auction] [--chart] [--chart-out 路径] [--png]
  boards [关键词]        板块目录 (行业+概念, 代码/名称/涨跌%), 给 kline/intraday 挑名
             分时图; 默认含集合竞价(09:15-09:25), 左轴价格右轴涨幅

透传动作 (按名调用 24 个动作)
  mcp <动作名> [--arg k=v]     透传调用, 例: webtool stock mcp stock_indicators --arg symbol=600519
  tools [关键词]               列动作清单

通用取数入口 (按 15 个功能域组织, 1300+ 接口全从这里进)
  data                          入口导航 (15 个域, 各域接口数)
  data list                     域总览 (每域多少接口)
  data list <域>                域内明细 (api 分类 + eco 接口 + em 配方)
                                例: data list 行情 / data list 龙虎榜
  data <域> find <关键词>       域内搜, 例: data 行情 find 茅台 / data 龙虎榜 find lhb
  data find <关键词>            跨域搜四类目录 (eco/api/em配方/docs), 结果带来源
  data call <名称> [--arg k=v]  按名调, 分发顺序: em 配方 → api 方法 → eco 接口
                                例: data call RPT_LICO_FN_CPD --arg date=20260331
                                    data call sse_yunhq_snap --arg code=sh600519
  data url <URL> [--post] [--pick data.0.quote]   裸 HTTP 直调 (反爬已内置)
  data health                 数据面体检 (api/eco/em + 各库出网路由探测)

  域: 行情 龙虎榜 资金流 财报 股东 板块 选股排行 公告资讯 债券基金
      期货期权 外汇数字币 宏观 全球市场 指数 其他

生态库 (akshare 1093 / tushare 122 / baostock 29 / efinance 55 —— 实数以 data health 为准)
  注: efinance 是子模块结构, 接口名带前缀 (stock.get_quote_history / fund.get_base_info)

第五侧: 底层 HTTP 直调 (data url 的老入口, 逆向出的 900+ 接口都能自己打)
  反爬已内置: 雪球走 curl_cffi chrome110+token warmup, 新浪/中证自动带 Referer,
  东财 push2 自动补 ut, datacenter 自动补 token+source+client

第六侧: 逆向接口文档 (从 akshare 源码手工逆向, 900+ 接口, 带源码行号可回溯)
  回答的是前三层给不了的问题: 端点 URL 是什么 / 参数怎么拼 / 返回字段对应哪一列
  docs-search <关键词>                   全文检索, 带行号上下文 (例: companyType / hexin-v)
  docs-report <reportName>               单个接口的完整逆向条目 (参数表+字段列序映射)
  其余: docs-books / docs-stats / docs-book / docs-section / docs-endpoint

原始 API (数据源层 154 方法 — 编排层未覆盖的能力)
  api-list --by function       按**功能**分组 (行情/K线/财报/股东/公司/板块/
                              选股/资金/公告/指数/新股) —— 回答"要干什么"
  api <方法名> [--arg k=v]     直接调任一方法, 例: webtool stock api ths_stockpage_finance --arg code=600519
  holder <代码>                股东研究 (东财 持仓变动/机构调研)
  forecast <代码>              盈利预测 (东财)

财务/要素类 (编排层升格, 多源回退)
  kline <代码> [--arg period=week]     K 线 (东财/雪球/新浪)
  index <指数> [--arg count=30]        指数行情 (支持中文别名/裸代码)
  income|balance|cashflow <代码>       三大报表 (东财 F10 + 大盘表双源)
  company|business <代码>              公司概况 / 主营构成
  holders|holder_chg <代码>            十大股东 / 高管持股变动
  industry|concept                     行业板块 / 概念板块清单
  industry_of <代码>                   个股的板块归属
  dividend [--arg year=2025]           分红排名
  margin [--arg page=1]                两融标的
  screener [--arg market=cn_a]         全市场筛器 (雪球/新浪)
  ipo [--arg type=gem]                 IPO 清单 (主板/创业板/科创板)

元动作
  health                       三侧探活 (master / 编排层 / 原始 API)
"""

