"""
同花顺 fetcher
==============
沙盒验证：行业板块列表 (35KB) / 板块 K 线 (12KB) 通
关键修复：qjs 算 v token + 设 cookie + 完整 headers

死锁清单（参考 接口指南.md）：
  - gn (概念板块) 返回 0 字节 → 沙盒 ban，不可用
  - thshy/getBsMarketDataAjax 404 → endpoint 下线
  - stocks/zyjs 404 → endpoint 下线
"""
import re
import json
from datetime import datetime

from webtool.stock.skill.scripts._common import ths_session, log


# ============================================================
#  行业板块（申万一级 / 同花顺行业）
# ============================================================
def industry_list():
    """
    申万一级行业（按涨跌幅排序）
    返回: [{code, name, pct, leader, leader_code}]
    """
    try:
        r = ths_session().get(
            "http://q.10jqka.com.cn/thshy/index/field/199112/order/desc/page/1/ajax/1/free/1/",
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Referer": "http://q.10jqka.com.cn/",
                "Accept": "application/json, text/javascript, */*; q=0.01",
            },
            timeout=10,
        )
        if r.status_code != 200:
            log(f"同花顺 industry_list HTTP {r.status_code}", "WARN")
            return []
        if len(r.content) < 1000:
            log(f"同花顺 industry_list 返回过短 ({len(r.content)}B，可能是沙盒 IP ban)", "WARN")
            return []
        text = r.content.decode("gbk", errors="ignore")
        items = []
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', text, re.DOTALL)
        for row in rows:
            # 板块链接：<a href="http://q.10jqka.com.cn/thshy/detail/code/881175/">{name}</a>
            link = re.search(
                r'href="https?://q\.10jqka\.com\.cn/thshy/detail/code/(\w+)/"[^>]*>([^<]+)</a>',
                row,
            )
            if not link:
                link = re.search(r'href="/thshy/detail/code/(\w+)/"[^>]*>([^<]+)</a>', row)
            if not link:
                continue
            code = link.group(1)
            name = link.group(2).strip()
            # 涨跌幅可能是 <td class="c-rise">8.34</td> 或 <td>1.23%</td>
            pct = re.search(r'class="(?:c-rise|c-fall)">(\-?\d+\.\d{1,2})</td>', row)
            if not pct:
                pct = re.search(r'>(\-?\d+\.\d{1,2})%</td>', row)
            # 领涨股在 stockpage.10jqka.com.cn/{code}/
            leader = re.search(
                r'stockpage\.10jqka\.com\.cn/(\w+)/"[^>]*>([^<]+)</a>', row
            )
            leader_code = leader.group(1) if leader else ""
            leader_name = leader.group(2).strip() if leader else ""
            items.append({
                "code": code,
                "name": name,
                "pct": f"{pct.group(1)}%" if pct else "0.00%",
                "leader": leader_name,
                "leader_code": leader_code,
            })
        if not items:
            log("同花顺 industry_list 解析为 0 条（HTML 结构可能变更）", "WARN")
        return items
    except Exception as e:
        log(f"同花顺 industry_list 失败: {type(e).__name__}: {str(e)[:80]}", "WARN")
        return []


def industry_kline(code, year=None):
    """
    板块 K 线（日线 JSONP）

    返回结构是双层包装：
      quotebridge_v4_line_bk_881270_01_2026({"data":"<csv_string>"});
    内层 data 是 CSV-like 字符串：`;` 分行，`，` 分字段。

    形态：date,open,high,low,close,volume,amount,,,,flag
    """
    if year is None:
        year = datetime.now().year
    try:
        from webtool.stock.skill.scripts._common import std_session
        r = std_session().get(
            f"https://d.10jqka.com.cn/v4/line/bk_{code}/01/{year}.js",
            headers={"Referer": "http://q.10jqka.com.cn/"},
            timeout=10,
        )
        if r.status_code != 200:
            log(f"同花顺 industry_kline {code} HTTP {r.status_code}", "WARN")
            return []
        if len(r.content) < 100:
            log(f"同花顺 industry_kline {code} 返回过短 ({len(r.content)}B)", "WARN")
            return []
        text = r.text
        # 找第一个 '('：JSONP 调用起点
        i = text.find("(")
        if i < 0:
            log(f"同花顺 industry_kline {code} 无 quotebridge 包装", "WARN")
            return []
        # 用 raw_decode 解析外层 JSON（自动跳过内层字符串中的 ））
        decoder = json.JSONDecoder()
        outer, _ = decoder.raw_decode(text, i + 1)
        # 内层是 CSV-like 字符串
        inner_str = outer.get("data")
        if not inner_str or not isinstance(inner_str, str):
            log(f"同花顺 industry_kline {code} 内层 data 为空", "WARN")
            return []
        rows = [r for r in inner_str.split(";") if r.strip()]
        if not rows:
            log(f"同花顺 industry_kline {code} {year} 年 CSV 解析为 0 行", "WARN")
            return []
        out = []
        for row in rows:
            fields = row.split(",")
            if len(fields) < 6:
                continue
            out.append({
                "date": fields[0],
                "open": _to_float(fields[1]),
                "high": _to_float(fields[2]),
                "low": _to_float(fields[3]),
                "close": _to_float(fields[4]),
                "volume": _to_int(fields[5]),
                "amount": _to_float(fields[6]) if len(fields) > 6 else None,
            })
        return out
    except Exception as e:
        log(f"同花顺 industry_kline {code} 失败: {type(e).__name__}: {str(e)[:80]}", "WARN")
        return []


def _to_float(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _to_int(s):
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return None


def industry_detail(code):
    """
    板块成分股列表（HTML 解析）

    同花顺页面每个股票有两行链接：
      <a href="http://stockpage.10jqka.com.cn/600265/" target="_blank">600265</a>
      <a href="http://stockpage.10jqka.com.cn/600265" target="_blank">*ST景谷</a>
    第一个是代码，第二个是名称（无尾斜杠）。脚本跳过名称 == 6 位数字的链接。
    """
    try:
        r = ths_session().get(
            f"http://q.10jqka.com.cn/thshy/detail/code/{code}/",
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Referer": "http://q.10jqka.com.cn/",
            },
            timeout=10,
        )
        if r.status_code != 200:
            log(f"同花顺 industry_detail {code} HTTP {r.status_code}", "WARN")
            return []
        if len(r.content) < 1000:
            log(f"同花顺 industry_detail {code} 返回过短 ({len(r.content)}B)", "WARN")
            return []
        text = r.content.decode("gbk", errors="ignore")

        # 用单条正则同时抓代码（带 /）+ 名称（不带 /）
        # 模式：在连续两行 <a ...>code</a> 名称</a> 中配对
        stocks = []
        pattern = re.compile(
            r'href="http://stockpage\.10jqka\.com\.cn/(\d+)/"[^>]*>\d+</a>'
            r'\s*</td>\s*<td>\s*<a href="http://stockpage\.10jqka\.com\.cn/\d+"[^>]*>([^<]+)</a>',
            re.DOTALL,
        )
        for m in pattern.finditer(text):
            code6 = m.group(1)
            name = m.group(2).strip()
            if name and len(code6) == 6:
                stocks.append({"code": code6, "name": name})
        if not stocks:
            log(f"同花顺 industry_detail {code} 解析为 0 条（HTML 结构可能变更）", "WARN")
        return stocks
    except Exception as e:
        log(f"同花顺 industry_detail {code} 失败: {type(e).__name__}: {str(e)[:80]}", "WARN")
        return []