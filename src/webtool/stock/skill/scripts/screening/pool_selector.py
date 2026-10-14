"""
池路由（按用户输入选择合适的池）
================================
"""
from webtool.stock.skill.scripts.screening import short_pool, mid_pool, long_pool


def select(pool_name, **kwargs):
    """
    pool_name: short / mid / long
    路由到对应池
    """
    if pool_name == "short":
        return short_pool.run(**kwargs)
    elif pool_name == "mid":
        # mid_pool.run(codes=[...])，不能直接 **kwargs 透传
        codes = kwargs.pop("codes", [])
        return mid_pool.run(codes=codes)
    elif pool_name == "long":
        # 长线池通常用户提供代码列表（参考典型）
        codes = kwargs.get("codes", [])
        passed = []
        failed = []
        for c in codes:
            r = long_pool.screen_one(c.get("code"), c.get("name"))
            if "error" in r:
                failed.append(r)
            else:
                passed.append(r)
        return {"passed": passed, "failed": failed}
    else:
        raise ValueError(f"未知池名: {pool_name}")