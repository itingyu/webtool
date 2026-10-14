#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stock 动作全量探活
逐个调用编排层 24 个动作，记录 ok / source / data 条数 / 错误。
走进程内 `srv.do_call`，不起子进程、不走网络之外的任何协议。
用法: python3 scripts/_probe_actions.py [--json]
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor

# action -> 探测参数
CASES = {
    "stock_quote": {"symbol": "600519"},
    "stock_kline": {"symbol": "600519", "count": 10},
    "stock_company": {"symbol": "600519"},
    "stock_business_analysis": {"symbol": "600519"},
    "stock_indicators": {"symbol": "600519", "count": 3},
    "stock_balance_sheet": {"symbol": "600519", "page_size": 2},
    "stock_income_statement": {"symbol": "600519", "page_size": 2},
    "stock_cashflow": {"symbol": "600519", "page_size": 2},
    "stock_top_holders": {"symbol": "600519"},
    "stock_holder_change": {"symbol": "600519"},
    "stock_industry_list": {"page": 1},
    "stock_concept_list": {"page": 1},
    "stock_industry_concept": {"symbol": "600519"},
    "stock_screener": {"market": "cn_a", "sort": "amount", "num": 10},
    "stock_index": {"symbol": "000300", "kind": "quote"},
    "stock_index_constituent": {"symbol": "000300", "page_size": 10},
    "stock_announcement": {"symbol": "600886", "page_size": 10},
    "stock_news": {"symbol": "600519"},
    "stock_capital_flow": {"scope": "industry"},
    "stock_dividend_rank": {"page_size": 10},
    "stock_margin_list": {"page_size": 10},
    "stock_ipo": {"page_size": 10},
    "stock_search_tools": {"keyword": "财务"},
    "stock_health_check": {},
}


def call(tool, args):
    from webtool.stock.bridge import srv
    t0 = time.time()
    try:
        payload = srv.call(tool, args)
    except Exception as e:                                       # noqa: BLE001
        return {"ok": False, "err": f"{type(e).__name__}: {e}",
                "ms": int((time.time() - t0) * 1000)}
    ms = int((time.time() - t0) * 1000)
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return {"ok": False, "err": f"非 JSON: {payload[:60]}", "ms": ms}
    if not payload.get("ok", True):
        return {"ok": False, "err": str(payload.get("err") or payload.get("error")
                                        or payload)[:80], "ms": ms}
    data = payload.get("data")
    if data is None and "data" not in payload:
        # 类 health_check 这类无 data 字段、仅 ok 标记的动作
        ok = bool(payload.get("ok")) and not payload.get("err")
        return {"ok": ok, "err": "" if ok else str(payload)[:80],
                "source": payload.get("source"), "n": 1 if ok else 0, "ms": ms}
    n = len(data) if isinstance(data, list) else (1 if data else 0)
    return {"ok": n > 0, "err": "" if n else "data 为空",
            "source": payload.get("source"), "n": n, "ms": ms}


def main():
    as_json = "--json" in sys.argv
    jobs = 1
    if "--jobs" in sys.argv:
        jobs = int(sys.argv[sys.argv.index("--jobs") + 1])
    names = list(CASES)
    # 默认串行 —— 雪球对并发很敏感, 并发首发会撞限流, 报出一堆假失败,
    # 探针就失去了意义。--jobs N 可放开, 但结果自负。
    if jobs > 1:
        with ThreadPoolExecutor(max_workers=jobs) as ex:
            results = list(ex.map(lambda t: (t, call(t, CASES[t])), names))
    else:
        results = [(t, call(t, CASES[t])) for t in names]
    if as_json:
        print(json.dumps(dict(results), ensure_ascii=False, indent=2))
        return
    ok_n = sum(1 for _, r in results if r["ok"])
    print(f"stock 动作探活：{ok_n}/{len(results)} 可用\n")
    for t, r in results:
        mark = "✅" if r["ok"] else "❌"
        extra = f"source={r.get('source')} n={r.get('n')}" if r["ok"] else r["err"]
        print(f"  {mark} {t:<26} {r['ms']:>6}ms  {extra}")
    bad = [t for t, r in results if not r["ok"]]
    if bad:
        print(f"\n不可用 {len(bad)} 项：{' '.join(bad)}")


if __name__ == "__main__":
    main()
