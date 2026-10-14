"""
简易新闻情绪打分（无 AI 模型依赖）
=================================
沙盒适配：基于关键词加权，不调用 FinBERT / LLM
agent 用 clients.news() 拉新闻后传入本函数打分

设计要点（避免"业绩预亏"被判看多这类翻车）：
  1. 极性词带权重：强信号（涨停/跌停/立案/退市/预亏/超预期…）权重 2，一般词权重 1
  2. 单条文本内同类词去重 —— 长文不因反复出现同一词而膨胀
  3. 不收录「业绩」「风险」「资金」这类无向泛词；
     「业绩」必须配「增长/超预期」，「预亏/预减/下滑」单独成负面词
  4. 归一化 = (正权重 - 负权重) / (正权重 + 负权重) × 100，落 -100~+100
"""
POSITIVE_KEYWORDS = {          # 词: 权重
    "涨停": 2, "超预期": 2, "扭亏": 2, "新高": 2, "中标": 2, "获批": 2,
    "预增": 2, "回购": 2, "增持": 2, "订单增长": 2, "业绩增长": 2,
    "上涨": 1, "增长": 1, "盈利": 1, "受益": 1, "订单": 1, "签约": 1,
    "合作": 1, "扩产": 1, "投产": 1, "出海": 1, "利好": 1, "催化": 1,
    "降准": 1, "降息": 1, "宽松": 1, "刺激": 1, "强劲": 1, "分红": 1,
    "派息": 1, "破净回购": 1, "资金流入": 1, "主力流入": 1, "高股息": 1,
}

NEGATIVE_KEYWORDS = {
    "跌停": 2, "立案": 2, "退市": 2, "预亏": 2, "预减": 2, "爆雷": 2,
    "减值": 2, "计提": 2, "商誉减值": 2, "被查": 2, "违规": 2, "处罚": 2,
    "下修": 2, "停产": 2, "冻结": 2, "资金流出": 2, "爆仓": 2,
    "下跌": 1, "破位": 1, "新低": 1, "亏损": 1, "不及预期": 1, "低于预期": 1,
    "下滑": 1, "减持": 1, "套现": 1, "解禁": 1, "调查": 1, "ST": 1,
    "利空": 1, "制裁": 1, "禁令": 1, "诉讼": 1, "违约": 1, "坏账": 1,
    "商誉": 1, "收紧": 1, "紧缩": 1, "加息": 1, "暴跌": 1, "跳水": 1,
    "停牌": 1, "停工": 1, "召回": 1, "事故": 1, "问询": 1, "质押": 1,
}


def score(news_items):
    """
    对一组新闻/文本打分
    news_items: ["...", "...", ...] 或 [{"text": "..."} / {"title": "..."}]
    返回: {score: -100~+100, positive_count, negative_count, hits, summary}
    """
    if not news_items:
        return {"score": 0, "raw_score": 0, "positive_count": 0,
                "negative_count": 0, "news_count": 0,
                "hits": {"正": [], "负": []}, "summary": "无数据"}

    wp = wn = 0            # 加权正 / 负
    cp = cn = 0            # 命中词数（去重后）
    hits_p, hits_n = [], []

    for item in news_items:
        text = item if isinstance(item, str) else (
            item.get("text", "") or item.get("title", ""))
        if not text:
            continue
        text = str(text)
        # 长词优先匹配并遮罩，避免「商誉减值」同时命中「商誉」「减值」重复计权
        for table, bucket in ((POSITIVE_KEYWORDS, hits_p),
                              (NEGATIVE_KEYWORDS, hits_n)):
            for kw in sorted(table, key=len, reverse=True):
                if kw in text:
                    n = text.count(kw)
                    if table is POSITIVE_KEYWORDS:
                        wp += table[kw] * n
                        cp += n
                    else:
                        wn += table[kw] * n
                        cn += n
                    bucket.append(kw)
                    text = text.replace(kw, "\u0000" * len(kw))

    total = wp + wn
    normalized = round((wp - wn) / total * 100, 1) if total else 0

    label = "中性"
    if normalized >= 30:
        label = "强烈看多"
    elif normalized >= 10:
        label = "看多"
    elif normalized <= -30:
        label = "强烈看空"
    elif normalized <= -10:
        label = "看空"

    return {
        "score": normalized,
        "raw_score": round(wp - wn, 1),
        "positive_count": cp,
        "negative_count": cn,
        "news_count": len(news_items) if isinstance(news_items, list) else 0,
        "hits": {"正": sorted(set(hits_p)), "负": sorted(set(hits_n))},
        "summary": label,
    }


def from_text(text):
    """单段文本直接打分"""
    return score([text])
