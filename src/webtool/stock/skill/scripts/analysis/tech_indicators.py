"""
技术指标计算
============
从 a-share-short-screen 和 stock-analysis 整合去重
所有指标只用 pandas / numpy，不依赖 akshare
"""
import numpy as np
import pandas as pd


def calc(df):
    """
    计算所有技术指标
    输入: DataFrame 含 close / high / low / volume 列
    输出: DataFrame 新增 ma5/ma10/ma20/ma60/vol_ratio/atr/macd/rsi6/bias
    """
    if df.empty or len(df) < 20:
        return df

    df = df.copy()

    # 必备列兜底
    for c in ["open", "close", "high", "low", "volume"]:
        if c not in df.columns:
            df[c] = np.nan

    # 均线
    df["ma5"] = df["close"].rolling(5).mean()
    df["ma10"] = df["close"].rolling(10).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma60"] = df["close"].rolling(60).mean()

    # 量能
    df["vol_ma5"] = df["volume"].rolling(5).mean()
    df["vol_ma60"] = df["volume"].rolling(min(60, len(df))).mean()
    df["vol_ratio"] = df["vol_ma5"] / df["vol_ma60"].replace(0, np.nan)
    df["vol_ratio"] = df["vol_ratio"].fillna(1.0)

    # ATR (14)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close_prev = df["close"].shift(1).astype(float)
    tr = pd.concat([
        (high - low),
        (high - close_prev).abs(),
        (low - close_prev).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = tr.rolling(14).mean()

    # 乖离率
    df["bias_ma5"] = (df["close"] - df["ma5"]) / df["ma5"] * 100
    df["bias_ma20"] = (df["close"] - df["ma20"]) / df["ma20"] * 100

    # MACD
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["macd_dif"] = ema12 - ema26
    df["macd_dea"] = df["macd_dif"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = 2 * (df["macd_dif"] - df["macd_dea"])

    # RSI (6)
    delta = df["close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(6).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(6).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi6"] = 100 - (100 / (1 + rs))

    return df


def score_short(df):
    """
    短线技术评分 0-100（a-share-short-screen 原版逻辑）
    加分项: 均线(20) + 量能(20) + MACD(20) + RSI(20) + 乖离率(20)

    返回: (score, breakdown, last_row)
    """
    if df is None or len(df) < 20:
        return None, None, None

    last = df.iloc[-1]
    prev = df.iloc[-2]
    score = 0
    breakdown = {}

    # 1. 均线多头排列 (20)
    above_ma5 = last["close"] > last["ma5"]
    above_ma10 = last["close"] > last["ma10"]
    above_ma20 = last["close"] > last["ma20"]
    above_ma60 = last["close"] > last["ma60"] if not pd.isna(last["ma60"]) else False
    ma20_up = last["ma20"] > prev["ma20"]
    ma60_up = (last["ma60"] > prev["ma60"]) if not pd.isna(last["ma60"]) else False

    long_arr = sum([above_ma5, above_ma10, above_ma20, above_ma60])
    if long_arr == 4 and ma20_up and ma60_up:
        score += 20; breakdown["均线多头"] = 20
    elif long_arr >= 3 and ma20_up:
        score += 14; breakdown["均线偏多"] = 14
    elif long_arr >= 2:
        score += 8

    # 2. 量能 (20)
    vr = last["vol_ratio"]
    if pd.isna(vr):
        vr = 1.0
    if vr >= 1.5 and last["close"] > prev["close"]:
        score += 20; breakdown["放量上涨"] = 20
    elif vr >= 1.2:
        score += 14; breakdown["温和放量"] = 14
    elif vr >= 0.8:
        score += 8
    elif vr < 0.5:
        breakdown["缩量"] = 0

    # 3. MACD (20)
    dif, dea = last["macd_dif"], last["macd_dea"]
    h_now, h_prev = last["macd_hist"], prev["macd_hist"]
    if dif > dea and h_now > 0 and h_now > h_prev:
        score += 20; breakdown["MACD金叉向上"] = 20
    elif dif > dea and h_now > 0:
        score += 14; breakdown["MACD多头"] = 14
    elif dif > dea:
        score += 8

    # 4. RSI (20)
    rsi = last["rsi6"]
    if pd.isna(rsi):
        rsi = 50
    if 50 <= rsi <= 70:
        score += 20; breakdown["RSI健康"] = 20
    elif 40 <= rsi < 50:
        score += 14; breakdown["RSI偏弱"] = 14
    elif 70 < rsi <= 80:
        score += 10; breakdown["RSI偏强"] = 10
    elif rsi > 80 or rsi < 30:
        breakdown["RSI极值"] = 0

    # 5. 乖离率 (20)
    bias = last["bias_ma5"]
    if pd.isna(bias):
        bias = 0
    if -2 <= bias <= 5:
        score += 20; breakdown["乖离合理"] = 20
    elif 5 < bias <= 10:
        score += 12; breakdown["轻微追高"] = 12
    elif bias > 10:
        score += 4; breakdown["追高风险"] = 4
    elif bias < -10:
        score += 8; breakdown["超跌"] = 8

    return score, breakdown, last


def score_general(df, news_items=None, macro_score=None):
    """
    综合评分 0-100（技术面 60 + 消息面 30 + 宏观 10）

    归一化说明：
      score_short 产出 0-100 → 技术面贡献 = score_short × 0.6（0-60）
      消息面 30 分由 news_scorer.score() 的 -100~+100 映射：(s + 100) / 200 × 30
      宏观 10 分由调用方传入（0-10），缺省按中性 5 计
      三项相加即为 0-100 综合分，与短选门槛「≥ 60 / 100」同口径

    硬规则:
      RSI > 80 → 禁买
      bias_ma5 > 5% → 禁买（不追高）
    """
    if df is None or len(df) < 20:
        return None, None, None, []

    last = df.iloc[-1]
    breakdown = {}
    warnings = []

    rsi = last["rsi6"] if not pd.isna(last["rsi6"]) else 50
    bias = last["bias_ma5"] if not pd.isna(last["bias_ma5"]) else 0

    if rsi > 80:
        warnings.append("RSI > 80 超买")
    if bias > 5:
        warnings.append(f"乖离率 MA5 = {bias:.2f}% 追高风险")

    short_score, short_bd, _ = score_short(df)
    if short_score is None:
        return None, None, None, warnings

    # 技术面 0-60
    tech_score = round(short_score * 0.6, 1)
    breakdown["技术面(60)"] = tech_score

    # 消息面 0-30（-100~+100 线性映射）
    if news_items is not None:
        from webtool.stock.skill.scripts.sentiment import news_scorer
        ns = news_scorer.score(news_items)["score"]
        news_score = round((ns + 100) / 200 * 30, 1)
    else:
        ns = None
        news_score = 15.0          # 无数据按中性 15/30
    breakdown["消息面(30)"] = news_score

    # 宏观 0-10
    mac = 5.0 if macro_score is None else max(0.0, min(10.0, float(macro_score)))
    breakdown["宏观(10)"] = mac

    score = round(tech_score + news_score + mac, 1)
    return score, breakdown, last, warnings


def technical_levels(df, last=None):
    """
    计算三档入场价位 + 支撑阻力 + 止损止盈（a-share-short-screen 原版）
    输入: 已 calc 后的 DataFrame + last 行
    """
    if df is None or (last is None and len(df) == 0):
        return None

    if last is None:
        last = df.iloc[-1]

    close = float(last["close"])
    ma5 = float(last["ma5"]) if not pd.isna(last["ma5"]) else close
    ma10 = float(last["ma10"]) if not pd.isna(last["ma10"]) else close
    ma20 = float(last["ma20"]) if not pd.isna(last["ma20"]) else close
    ma60 = float(last["ma60"]) if not pd.isna(last["ma60"]) else close
    atr = float(last["atr"]) if not pd.isna(last["atr"]) else close * 0.02
    vol_ratio = float(last["vol_ratio"]) if not pd.isna(last["vol_ratio"]) else 1.0

    recent_high = float(df["high"].tail(60).max())
    recent_low = float(df["low"].tail(60).min())

    support = max([s for s in [ma20, ma60, recent_low * 0.98] if not pd.isna(s)])
    resistance = min([r for r in [recent_high, ma5 * 1.05, close * 1.05] if not pd.isna(r)])

    bias = float(last["bias_ma5"]) if not pd.isna(last.get("bias_ma5", 0)) else 0
    rsi = float(last["rsi6"]) if not pd.isna(last.get("rsi6", 50)) else 50

    return {
        "current_price": round(close, 2),
        "ma5": round(ma5, 2),
        "ma10": round(ma10, 2),
        "ma20": round(ma20, 2),
        "ma60": round(ma60, 2) if not pd.isna(last["ma60"]) else None,
        "atr": round(atr, 2),
        "vol_ratio": round(vol_ratio, 2),
        "support": round(support, 2),
        "resistance": round(resistance, 2),
        "recent_high_60d": round(recent_high, 2),
        "recent_low_60d": round(recent_low, 2),
        "entry_breakout": round(resistance * 1.005, 2),
        "entry_pullback": round(ma10 * 0.99, 2),
        "entry_observing": round(close * (1.003 if close > ma5 else 1.0), 2),
        "hard_stop": round(close * 0.93, 2),       # -7%
        "target_1": round(close * 1.08, 2),
        "target_2": round(close * 1.15, 2),
        "bias_ma5_pct": round(bias, 2),
        "rsi6": round(rsi, 1),
        "macd_hist": round(float(last.get("macd_hist", 0)) if not pd.isna(last.get("macd_hist", 0)) else 0, 4),
    }