"""
研报模板生成器（简化版）
========================
不调用 alphaear-reporter 的 ReportAgent，本地模板 + 数据填充
agent 用 LLM 能力补足深度分析
"""
from datetime import datetime


def single_stock_report(analysis_result, news=None, sentiment=None):
    """
    单股研报模板（基于 single_analysis.analyze 输出）
    """
    a = analysis_result
    q = a.get("quote", {})
    t = a.get("technical", {})
    ind = a.get("industry", [])

    industry_str = " / ".join([i.get("ind_name", "") for i in ind if i.get("ind_type") == 1])

    report = f"""# {a.get('code')} {a.get('name')} — 单股研报

**数据时间**：{a.get('as_of', '')}
**评级**：{a.get('signal', 'N/A')}（综合评分 {a.get('score', 0)}/100 = 技术 60 + 消息 30 + 宏观 10）
**行业**：{industry_str or '未知'}

## 1. 估值与市值

| 指标 | 数值 |
|---|---|
| 当前价 | {q.get('current', 'N/A')} 元 |
| 日涨跌幅 | {q.get('percent', 'N/A')}% |
| 流通市值 | {q.get('float_market_capital_yi', 'N/A')} 亿 |
| PE (TTM) | {q.get('pe_ttm', 'N/A')} |
| PB | {q.get('pb', 'N/A')} |
| 换手率 | {q.get('turnover_rate', 'N/A')}% |

## 2. 技术面

| 指标 | 数值 |
|---|---|
| 现价 | {t.get('current_price')} |
| MA5 / MA10 / MA20 / MA60 | {t.get('ma5')} / {t.get('ma10')} / {t.get('ma20')} / {t.get('ma60')} |
| 量比（5日/60日） | {t.get('vol_ratio')} |
| ATR (14) | {t.get('atr')} |
| 支撑位 | {t.get('support')} |
| 阻力位 | {t.get('resistance')} |
| 60 日新高 | {t.get('recent_high_60d')} |
| 60 日新低 | {t.get('recent_low_60d')} |
| 乖离率 MA5 | {t.get('bias_ma5_pct')}% |
| RSI (6) | {t.get('rsi6')} |
| MACD HIST | {t.get('macd_hist')} |

## 3. 入场价位

| 类型 | 价位 | 触发 |
|---|---|---|
| 突破买入 | {t.get('entry_breakout')} | 量比 ≥ 1.5 + 板块共振 |
| 回踩低吸 | {t.get('entry_pullback')} | 缩量回踩 MA10 |
| 集合竞价 | {t.get('entry_observing')} | 9:25 高开 + 板块走强 |

## 4. 风控

- **硬止损**：{t.get('hard_stop')} (-7%)
- **第一目标**：{t.get('target_1')} (+8%)
- **第二目标**：{t.get('target_2')} (+15%)

## 5. 近期公告

"""

    if a.get("announcements_7d"):
        for ann in a["announcements_7d"][:5]:
            report += f"- [{ann.get('title')}]({ann.get('url')}) ({ann.get('time')})\n"
    else:
        report += "（最近 7 天无重要公告）\n"

    if sentiment:
        report += f"\n## 6. 新闻情绪\n\n- 评分: {sentiment.get('score')} | {sentiment.get('summary')}\n- 看多关键词 {sentiment.get('positive_count')} / 看空关键词 {sentiment.get('negative_count')}\n"

    report += "\n---\n**免责声明**：本报告基于公开信息研究，不构成投资建议。\n"

    return report


def short_screen_report(screen_result, news_map=None):
    """
    短线选股报告模板（基于 short_pool.run 输出）
    """
    res = screen_result
    passed = res.get("passed", [])
    failed = res.get("failed", [])

    md = f"""# 短线选股报告

**筛选时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**候选池**：{res.get('pool_size')} 只 → **通过**：{res.get('passed_count')} 只（评分 ≥ {res.get('min_score_threshold', 60)}）

## 通过的候选（按评分排序）

| 代码 | 名称 | 评分 | 现价 | 突破价 | 回踩价 | 止损价 | 流通市值(亿) | 行业 |
|---|---|---|---|---|---|---|---|---|
"""

    for p in passed[:20]:
        t = p.get("technical") or {}
        ind = p.get("industry")
        # short_pool 给的是申万一级字符串；兼容旧的行业列表结构
        if isinstance(ind, str):
            ind_str = ind
        elif isinstance(ind, list):
            ind_str = " / ".join([i.get("ind_name", "") for i in ind
                                  if isinstance(i, dict) and i.get("ind_type") == 1][:2])
        else:
            ind_str = ""
        md += (f"| {p.get('code')} | {p.get('name')} | {p.get('score')} | "
               f"{t.get('current_price')} | {t.get('entry_breakout')} | "
               f"{t.get('entry_pullback')} | {t.get('hard_stop')} | "
               f"{p.get('float_market_capital_yi', 'N/A')} | {ind_str or 'N/A'} |\n")

    md += f"\n## 未通过：{len(failed)} 只\n\n"
    fail_by_gate = {}
    for f in failed:
        gate = f.get("failed_gate", "其他")
        fail_by_gate.setdefault(gate, []).append(f)
    for gate, items in fail_by_gate.items():
        md += f"### {gate} ({len(items)})\n\n"
        for i in items[:5]:
            md += f"- {i.get('code')} {i.get('name')}: {i.get('error')}\n"
        if len(items) > 5:
            md += f"- ... 等 {len(items) - 5} 只\n"
        md += "\n"

    return md