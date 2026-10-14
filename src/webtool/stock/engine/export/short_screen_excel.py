"""
短线选股 Excel 导出脚本
========================
按 references/templates/excel-short-screen.md 规范生成 xlsx
4 个 sheet：精选 / 候选 / 板块行业趋势 / 事件日历

调用方式：
    from webtool.stock.engine.export.short_screen_excel import build_workbook
    build_workbook(
        output_path="/var/minis/shared/股票/短线选股/短线选股_20260810.xlsx",
        picks=[...], candidates=[...], sectors=[...], events=[...],
        meta={"base_date":"2026-08-07", ...},
    )
"""
from openpyxl import Workbook
from openpyxl.styles import (
    Alignment, PatternFill, Font, Border, Side,
)
from openpyxl.utils import get_column_letter


# ===== 颜色编码 =====
COLORS = {
    "header": "1F4E78",          # 深蓝表头
    "header_text": "FFFFFF",
    "selected": "FFF2CC",         # 精选 sheet 底色
    "candidate": "F2F2F2",        # 候选 sheet 底色
    "summary": "E2EFDA",          # 汇总行底色
    "main_strong": "FFD966",      # 主线★★★★★ 底色
    "main_med": "FFE699",
    "strategy_breakout": "C6EFCE",   # 突破 - 绿
    "strategy_pullback": "BDD7EE",   # 回踩 - 蓝
    "strategy_limit_up": "F8CBAD",   # 涨停 - 红
    "strategy_event": "F4B084",      # 事件 - 橙
    "strategy_reverse": "C9B1D9",    # 反包 - 紫
    "strategy_mainline": "9DC3E6",   # 主线 - 青
    "risk_high": "F4CCCC",           # 高风险（超买等）
    "risk_med": "FCE4D6",
    "risk_gray": "D9D9D9",
    "critical_event": "C00000",      # 关键事件
    "critical_event_text": "FFFFFF",
}

# 6 主策略填色
STRATEGY_COLORS = {
    "突破跟随": COLORS["strategy_breakout"],
    "回踩低吸": COLORS["strategy_pullback"],
    "涨停战法": COLORS["strategy_limit_up"],
    "事件驱动": COLORS["strategy_event"],
    "反包形态": COLORS["strategy_reverse"],
    "主线跟随": COLORS["strategy_mainline"],
}

# 风险等级填色
RISK_COLORS = {
    "极度超买(RSI>95)": COLORS["risk_high"],
    "超买(RSI>80)": COLORS["risk_med"],
    "MA60下破": COLORS["risk_med"],
    "估值过高(PE>150)": COLORS["risk_gray"],
    "追高(乖离>15%)": COLORS["risk_med"],
    "流动性边缘": COLORS["risk_gray"],
}


# ===== 通用样式 =====
def _thin_border():
    s = Side(border_style="thin", color="999999")
    return Border(left=s, right=s, top=s, bottom=s)


def _header_style(cell):
    cell.font = Font(bold=True, color=COLORS["header_text"], size=11)
    cell.fill = PatternFill("solid", fgColor=COLORS["header"])
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    cell.border = _thin_border()


def _data_style(cell, wrap=True, bold=False, fill=None, align="left"):
    cell.font = Font(bold=bold, size=10)
    cell.alignment = Alignment(horizontal=align, vertical="top", wrap_text=wrap)
    cell.border = _thin_border()
    if fill:
        cell.fill = PatternFill("solid", fgColor=fill)


def _auto_width(ws, max_width=50):
    """根据内容自动调列宽（带上限）"""
    for col_idx in range(1, ws.max_column + 1):
        col_letter = get_column_letter(col_idx)
        max_len = 0
        for row in ws.iter_rows(min_col=col_idx, max_col=col_idx, values_only=True):
            if row[0] is None:
                continue
            # 估算：中文字符按 2 算
            zh_count = sum(1 for c in str(row[0]) if ord(c) > 127)
            ascii_count = len(str(row[0])) - zh_count
            est = zh_count * 2 + ascii_count
            if est > max_len:
                max_len = est
        # 数值列短一点
        adjusted = min(max(max_len + 2, 8), max_width)
        ws.column_dimensions[col_letter].width = adjusted


# ===== Sheet 1: 精选 =====
def _build_picks_sheet(wb, picks, meta):
    ws = wb.active
    ws.title = "精选"

    # 顶部总评
    ws["A1"] = "📌 下周一短线选股 — 精选标的"
    ws["A1"].font = Font(bold=True, size=14, color="FFFFFF")
    ws["A1"].fill = PatternFill("solid", fgColor=COLORS["header"])
    ws["A1"].alignment = Alignment(horizontal="left", vertical="center")
    ws.merge_cells("A1:X1")
    ws.row_dimensions[1].height = 28

    base_date = meta.get("base_date", "")
    total_pos = sum(p.get("仓位%", 0) for p in picks)
    ws["A2"] = f"数据基准日：{base_date}  |  持仓周期：1-5 个交易日  |  总仓位：{total_pos:.1f}%  |  板块分散度：{len(set(p.get('申万一级','') for p in picks))} 个申万一级"
    ws["A2"].font = Font(italic=True, size=10, color="595959")
    ws.merge_cells("A2:X2")

    headers = [
        "代码", "名称", "申万一级", "评分", "市值(亿)", "现价",
        "主策略", "突破入场", "回踩入场", "竞价入场", "不买区",
        "硬止损", "目标1", "目标2", "仓位%", "持有期",
        "推荐逻辑", "关键催化", "政策催化", "行业地位",
        "估值水位", "风险点", "注意事项", "消息面核查",
    ]
    HEADER_ROW = 4
    for col_idx, h in enumerate(headers, 1):
        c = ws.cell(row=HEADER_ROW, column=col_idx, value=h)
        _header_style(c)
    ws.row_dimensions[HEADER_ROW].height = 32

    # 数据行
    for i, p in enumerate(picks, 1):
        row = HEADER_ROW + i
        strategy = p.get("主策略", "主线跟随")
        fill = STRATEGY_COLORS.get(strategy, None)

        values = [
            p.get("代码", ""), p.get("名称", ""), p.get("申万一级", ""),
            p.get("评分", ""), p.get("市值(亿)", ""), p.get("现价", ""),
            strategy,
            p.get("突破入场", ""), p.get("回踩入场", ""),
            p.get("竞价入场", ""), p.get("不买区", ""),
            p.get("硬止损", ""), p.get("目标1", ""), p.get("目标2", ""),
            p.get("仓位%", ""), p.get("持有期", ""),
            p.get("推荐逻辑", ""), p.get("关键催化", ""),
            p.get("政策催化", ""), p.get("行业地位", ""),
            p.get("估值水位", ""), p.get("风险点", ""),
            p.get("注意事项", ""), p.get("消息面核查", ""),
        ]
        for col_idx, v in enumerate(values, 1):
            c = ws.cell(row=row, column=col_idx, value=v)
            # 数值列右对齐
            if col_idx in (4, 5, 6, 8, 9, 10, 11, 12, 13, 14, 15):
                align = "right"
                if isinstance(v, (int, float)):
                    c.number_format = "#,##0.00" if col_idx != 15 else "0.00"
                else:
                    c.number_format = "@"
            else:
                align = "left"
            _data_style(c, wrap=True, align=align, fill=fill)

        # 行高根据最长备注自适应
        max_lines = 1
        for v in values[16:]:  # 备注列 Q-X
            if v:
                lines = str(v).count("\n") + max(1, len(str(v)) // 35)
                max_lines = max(max_lines, lines)
        ws.row_dimensions[row].height = max(20, max_lines * 18)

    # 汇总行
    sum_row = HEADER_ROW + len(picks) + 1
    ws.cell(row=sum_row, column=1, value="合计").font = Font(bold=True)
    ws.cell(row=sum_row, column=1).fill = PatternFill("solid", fgColor=COLORS["summary"])
    ws.merge_cells(start_row=sum_row, start_column=1, end_row=sum_row, end_column=14)
    ws.cell(row=sum_row, column=15, value=round(total_pos, 2))
    ws.cell(row=sum_row, column=15).number_format = "0.00"
    ws.cell(row=sum_row, column=15).font = Font(bold=True)
    ws.cell(row=sum_row, column=15).fill = PatternFill("solid", fgColor=COLORS["summary"])
    ws.cell(row=sum_row, column=15).alignment = Alignment(horizontal="right")
    # 备注列写风险总闸
    ws.cell(row=sum_row, column=16, value="—")
    ws.cell(row=sum_row, column=17, value=meta.get("风控总闸", "硬止损 -7% 必须执行；外盘/政策突发开盘前 30 分钟不建仓"))
    ws.merge_cells(start_row=sum_row, start_column=17, end_row=sum_row, end_column=24)
    for c in range(16, 25):
        cell = ws.cell(row=sum_row, column=c)
        cell.fill = PatternFill("solid", fgColor=COLORS["summary"])
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        cell.border = _thin_border()
        cell.font = Font(bold=True, size=10)

    _auto_width(ws, max_width=50)
    ws.freeze_panes = "B5"


# ===== Sheet 2: 候选 =====
def _build_candidates_sheet(wb, candidates):
    ws = wb.create_sheet("候选")

    ws["A1"] = "📋 通过硬门槛但未入选 — 观察池"
    ws["A1"].font = Font(bold=True, size=14, color="FFFFFF")
    ws["A1"].fill = PatternFill("solid", fgColor=COLORS["header"])
    ws.merge_cells("A1:M1")
    ws.row_dimensions[1].height = 28

    headers = [
        "代码", "名称", "申万一级", "评分", "市值(亿)", "现价",
        "RSI6", "乖离率MA5%", "MA60状态",
        "剔除原因", "风险信号", "重新关注条件", "观察池标记",
    ]
    HEADER_ROW = 3
    for col_idx, h in enumerate(headers, 1):
        c = ws.cell(row=HEADER_ROW, column=col_idx, value=h)
        _header_style(c)
    ws.row_dimensions[HEADER_ROW].height = 28

    for i, c in enumerate(candidates, 1):
        row = HEADER_ROW + i
        risk = c.get("风险信号", "")
        fill = RISK_COLORS.get(risk, COLORS["candidate"])

        values = [
            c.get("代码", ""), c.get("名称", ""), c.get("申万一级", ""),
            c.get("评分", ""), c.get("市值(亿)", ""), c.get("现价", ""),
            c.get("RSI6", ""), c.get("乖离率MA5%", ""),
            c.get("MA60状态", ""),
            c.get("剔除原因", ""), c.get("风险信号", ""),
            c.get("重新关注条件", ""), c.get("观察池标记", ""),
        ]
        for col_idx, v in enumerate(values, 1):
            cell = ws.cell(row=row, column=col_idx, value=v)
            if col_idx in (4, 5, 6, 7, 8):
                cell.alignment = Alignment(horizontal="right", vertical="top")
                if isinstance(v, (int, float)):
                    cell.number_format = "#,##0.00"
            else:
                cell.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
            cell.border = _thin_border()
            cell.font = Font(size=10)
            if fill:
                cell.fill = PatternFill("solid", fgColor=fill)

        # 行高
        max_lines = 1
        for v in values[9:]:
            if v:
                lines = str(v).count("\n") + max(1, len(str(v)) // 30)
                max_lines = max(max_lines, lines)
        ws.row_dimensions[row].height = max(20, max_lines * 18)

    _auto_width(ws, max_width=45)
    ws.freeze_panes = "B4"


# ===== Sheet 3: 板块行业趋势 =====
def _build_sectors_sheet(wb, sectors, meta):
    ws = wb.create_sheet("板块行业趋势")

    # 总评段
    ws["A1"] = "🧭 当前主线判断 + 资金切换路径"
    ws["A1"].font = Font(bold=True, size=14, color="FFFFFF")
    ws["A1"].fill = PatternFill("solid", fgColor=COLORS["header"])
    ws.merge_cells("A1:J1")
    ws.row_dimensions[1].height = 28

    summary_lines = meta.get("板块总评", [])
    for i, line in enumerate(summary_lines, 2):
        ws.cell(row=i, column=1, value=line).font = Font(size=10, italic=True)
        ws.merge_cells(start_row=i, start_column=1, end_row=i, end_column=10)
        ws.cell(row=i, column=1).alignment = Alignment(wrap_text=True, vertical="top")

    HEADER_ROW = len(summary_lines) + 4

    headers = [
        "申万一级", "本周涨幅%", "排名", "主线状态",
        "持续天数", "核心驱动", "政策催化",
        "资金共识", "拥挤度", "下周展望",
    ]
    for col_idx, h in enumerate(headers, 1):
        c = ws.cell(row=HEADER_ROW, column=col_idx, value=h)
        _header_style(c)
    ws.row_dimensions[HEADER_ROW].height = 28

    for i, s in enumerate(sectors, 1):
        row = HEADER_ROW + i
        rating = s.get("主线状态", "")
        fill = COLORS["main_strong"] if "★★★★★" in rating else (
            COLORS["main_med"] if "★★★★" in rating else None)

        values = [
            s.get("板块", ""), s.get("涨幅%", ""), s.get("排名", ""),
            rating, s.get("持续天数", ""), s.get("核心驱动", ""),
            s.get("政策催化", ""), s.get("资金共识", ""),
            s.get("拥挤度", ""), s.get("下周展望", ""),
        ]
        for col_idx, v in enumerate(values, 1):
            cell = ws.cell(row=row, column=col_idx, value=v)
            if col_idx in (2, 3, 5):
                cell.alignment = Alignment(horizontal="right", vertical="top")
                if isinstance(v, (int, float)) and col_idx == 2:
                    cell.number_format = "0.00"
            else:
                cell.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
            cell.border = _thin_border()
            cell.font = Font(size=10)
            if fill and col_idx == 4:  # 只在评级列上色
                cell.fill = PatternFill("solid", fgColor=fill)

        max_lines = 1
        for v in values[5:]:
            if v:
                lines = str(v).count("\n") + max(1, len(str(v)) // 30)
                max_lines = max(max_lines, lines)
        ws.row_dimensions[row].height = max(20, max_lines * 18)

    _auto_width(ws, max_width=40)
    ws.freeze_panes = f"B{HEADER_ROW + 1}"


# ===== Sheet 4: 事件日历 =====
def _build_events_sheet(wb, events, meta):
    ws = wb.create_sheet("事件日历")

    ws["A1"] = "📅 下周关键事件日历"
    ws["A1"].font = Font(bold=True, size=14, color="FFFFFF")
    ws["A1"].fill = PatternFill("solid", fgColor=COLORS["header"])
    ws.merge_cells("A1:G1")
    ws.row_dimensions[1].height = 28

    ws["A2"] = meta.get("事件总评", "本周最关键事件：美国 7 月 CPI（8/12）决定 9 月降息预期")
    ws["A2"].font = Font(italic=True, size=10, color="595959")
    ws.merge_cells("A2:G2")

    HEADER_ROW = 4
    headers = ["日期", "星期", "事件", "影响板块", "对应持仓", "应对动作", "关键程度"]
    for col_idx, h in enumerate(headers, 1):
        c = ws.cell(row=HEADER_ROW, column=col_idx, value=h)
        _header_style(c)
    ws.row_dimensions[HEADER_ROW].height = 28

    for i, e in enumerate(events, 1):
        row = HEADER_ROW + i
        critical = e.get("关键程度", 0)
        is_critical = critical >= 5

        values = [
            e.get("日期", ""), e.get("星期", ""), e.get("事件", ""),
            e.get("影响板块", ""), e.get("对应持仓", ""),
            e.get("应对动作", ""), critical,
        ]
        for col_idx, v in enumerate(values, 1):
            cell = ws.cell(row=row, column=col_idx, value=v)
            cell.alignment = Alignment(horizontal="left" if col_idx != 7 else "center",
                                        vertical="top", wrap_text=True)
            cell.border = _thin_border()
            cell.font = Font(size=10, bold=is_critical and col_idx == 7)
            if is_critical:
                cell.fill = PatternFill("solid", fgColor=COLORS["critical_event"])
                cell.font = Font(size=10, bold=True, color=COLORS["critical_event_text"])

        max_lines = 1
        for v in values:
            if v:
                lines = str(v).count("\n") + max(1, len(str(v)) // 35)
                max_lines = max(max_lines, lines)
        ws.row_dimensions[row].height = max(20, max_lines * 18)

    _auto_width(ws, max_width=35)
    ws.freeze_panes = "B5"


# ===== 主入口 =====
def build_from_screen(result, output_path, meta=None):
    """
    便捷入口：直接把 screening.short_pool.run() 的结果落成 Excel
    :param result: short_pool.run() 的返回 dict
    :param output_path: 输出 xlsx 路径
    """
    picks = result.get("passed", [])
    failed = result.get("failed", [])
    candidates = [{"code": p.get("code"), "name": p.get("name"),
                   "score": p.get("score"), "industry": p.get("industry"),
                   "float_market_capital_yi": p.get("float_market_capital_yi"),
                   "position_tag": p.get("position_tag"),
                   "position_60d": p.get("position_60d"),
                   "status": "通过"} for p in picks]
    candidates += [{"code": f.get("code"), "name": f.get("name"),
                    "score": f.get("score", 0), "industry": f.get("industry"),
                    "float_market_capital_yi": f.get("float_market_capital_yi"),
                    "position_tag": f.get("position_tag"),
                    "position_60d": f.get("position_60d"),
                    "status": f"剔除（{f.get('failed_gate') or f.get('error')}）"}
                   for f in failed]

    ind = {}
    for p in picks:
        k = p.get("industry") or "未分类"
        d = ind.setdefault(k, {"name": k, "count": 0, "zone": "", "picks": []})
        d["count"] += 1
        d["picks"].append(f"{p.get('code')} {p.get('name')}")
    sectors = sorted(ind.values(), key=lambda x: -x["count"])

    notes = result.get("portfolio_notes") or []
    meta = dict(meta or {})
    meta.setdefault("base_date", "")
    meta.setdefault("风控总闸", "")
    # 板块总评是**行列表**（渲染器逐行写入），传字符串会被逐字符拆开
    if "板块总评" not in meta:
        inds = result.get("industries") or []
        head = (f"申万一级覆盖 {result.get('industry_dispersion', 0)} 个："
                + ("、".join(inds) if inds else "无"))
        meta["板块总评"] = [head] + list(notes)
    meta.setdefault("事件总评", "；".join(notes) if notes else "无组合层提示")
    meta["portfolio_notes"] = notes
    return build_workbook(output_path, picks, candidates, sectors, [], meta=meta)


def build_workbook(output_path, picks, candidates, sectors, events, meta=None):
    """
    生成短线选股 Excel 工作簿
    :param output_path: 输出 xlsx 路径
    :param picks: 精选标的 list of dict
    :param candidates: 候选标的 list of dict
    :param sectors: 板块 list of dict
    :param events: 事件 list of dict
    :param meta: dict，含 base_date / 风控总闸 / 板块总评 / 事件总评
    """
    meta = meta or {}
    wb = Workbook()

    _build_picks_sheet(wb, picks, meta)
    _build_candidates_sheet(wb, candidates)
    _build_sectors_sheet(wb, sectors, meta)
    _build_events_sheet(wb, events, meta)

    wb.save(output_path)
    return output_path


if __name__ == "__main__":
    # 简单自检
    picks = [{
        "代码": "000506", "名称": "招金黄金", "申万一级": "贵金属", "评分": 84,
        "市值(亿)": 168.37, "现价": 18.13, "主策略": "主线跟随",
        "突破入场": 16.83, "回踩入场": 14.40, "竞价入场": 18.18, "不买区": 19.62,
        "硬止损": 16.86, "目标1": 19.58, "目标2": 20.85,
        "仓位%": 1.5, "持有期": "1-5 个交易日",
        "推荐逻辑": "黄金主线最直接 A 股标的，央行二季度购金 288.9 吨同比 +62%",
        "关键催化": "美国 CPI 8/12 公布；9 月 FOMC 加息预期反复升温",
        "政策催化": "美联储降息路径博弈",
        "行业地位": "申万一级贵金属（本周 +4.11%）",
        "估值水位": "PE 48.2 / PB 18.9（行业中位数 ~12）",
        "风险点": "美联储 9 月意外加息、央行购金放缓",
        "注意事项": "回踩 MA10 试仓，突破 16.75 阻力加仓",
        "消息面核查": "现货金突破 4200 美元，日本汇率干预催化",
    }]
    candidates = [{
        "代码": "600161", "名称": "天坛生物", "申万一级": "生物制品",
        "评分": 64, "市值(亿)": 129.0, "现价": 107.88,
        "RSI6": 98.3, "乖离率MA5%": 22.14, "MA60状态": "上",
        "剔除原因": "RSI 98.3 极度超买 + 乖离率 22% 追高",
        "风险信号": "极度超买(RSI>95)",
        "重新关注条件": "RSI 回落至 70 以下 + 乖离率回到 ±5% 区间",
        "观察池标记": "是（跟踪 BD 业绩兑现节奏）",
    }]
    sectors = [{
        "板块": "医疗服务", "涨幅%": 8.34, "排名": 1,
        "主线状态": "★★★★★", "持续天数": 4,
        "核心驱动": "基药目录首次纳入 16 种创新药",
        "政策催化": "2026 版基药目录 + 创新药 BD 爆发",
        "资金共识": "BD 1063 亿美元 + 药明康德上调指引",
        "拥挤度": "RSI 普遍 > 80，板块一致性极高",
        "下周展望": "若继续冲高则减仓兑现，不追",
    }]
    events = [{
        "日期": "2026-08-12", "星期": "周二", "事件": "美国 7 月 CPI",
        "影响板块": "全市场 / 黄金", "对应持仓": "招金黄金、华友钴业",
        "应对动作": "当天不建新仓；若 CPI 超预期优先减仓华友钴业",
        "关键程度": 5,
    }]
    meta = {
        "base_date": "2026-08-07",
        "风控总闸": "硬止损 -7% 必须执行；外盘/政策突发开盘前 30 分钟不建仓",
        "板块总评": [
            "当前主线：医药生物（★★★★★）+ 有色金属（★★★★）",
            "持续性：医药 4 天 / 有色 5 天",
            "拥挤度：医药 RSI 普遍 > 80 已拥挤；有色相对健康",
        ],
        "事件总评": "本周最关键事件：美国 7 月 CPI（8/12）决定 9 月降息预期",
    }
    out = build_workbook("/tmp/test_short_screen.xlsx", picks, candidates, sectors, events, meta)
    print(f"已生成：{out}")