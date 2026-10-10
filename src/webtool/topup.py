# -*- coding: utf-8 -*-
"""search 自动补量: 黑名单/广告/去重后不足 requested 时, 翻页补拉重过滤

策略 (宁少勿滥, 有硬上限):
- 触发: 过滤后总条数 < requested → 对有翻页能力的引擎补拉 page 2,3 (上限2页)
- 补拉单页量 = need+4 (够用即可, 不白拉); 页间随机延迟 0.6-1.4s 防连打
- 补拉结果重新过 广告→黑名单 过滤链, 与首轮合并后再走一遍 merge 排序去重
- 补拉失败/无更多结果 → 静默停 (尽力而为, 不算引擎 error)
- 引擎签名无 page 参数 (sogou) 自动跳过; 最终凑不足就诚实返回短列表
- 补拉不走缓存 (cache key 无页码维度), 输出的 topup.fetched 记录补拉条数
"""
import random
import time

MAX_EXTRA_PAGES = 2        # 每引擎最多补 2 页
PAGE_DELAY = (0.6, 1.4)    # 补页间随机延迟区间(秒)


def _supports_page(fn):
    import inspect
    try:
        return 'page' in inspect.signature(fn).parameters
    except (ValueError, TypeError):
        return False


def top_up(engine, fn, query, want, have_count, proxy, timeout, market,
           filter_ad=True, is_blocked_fn=None, rng=None):
    """单引擎补拉: 返回 (extra_results, fetched_raw_count)

    want: 目标条数 (= args.max); have_count: 过滤后现存条数
    """
    need = want - have_count
    if need <= 0 or not _supports_page(fn):
        return [], 0
    rng = rng or random
    fetch_n = min(want, need + 4)   # 单页拉取量: 够用即可, 不白拉整页
    extra = []
    fetched = 0
    for page in range(2, 2 + MAX_EXTRA_PAGES):
        if len(extra) >= need:
            break
        try:
            rs = fn(query, max_results=fetch_n, proxy=proxy, timeout=timeout,
                    market=market, page=page)
        except Exception:
            break
        if not rs:
            break
        fetched += len(rs)
        if filter_ad:
            from .adfilter import is_ad
            rs = [r for r in rs if not r.get('is_ad') and not is_ad(r)]
        else:
            from .adfilter import mark_ads
            mark_ads(rs)
        if is_blocked_fn:
            rs = [r for r in rs if not is_blocked_fn(r.get('url', ''))]
        extra.extend(rs)
        if len(rs) < fetch_n // 2:
            break            # 该页过滤后产量骤减 → 引擎没料了, 别再翻
        time.sleep(rng.uniform(*PAGE_DELAY))
    return extra, fetched
