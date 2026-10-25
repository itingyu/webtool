"""公共实例探活: 并发打一条已知路由, 记录哪些实例此刻可用

结果缓存 ~/.webtool/cache/rsshub_instances.json (TTL 1h), 默认实例表来自
data/instances.json (用户可用 ~/.webtool/instances.json 覆盖)。
"""

import json
import re
import time
from pathlib import Path

from webtool.radar.instances_cfg import PROBE_ROUTE, default_instances
from webtool.radar.race import race

INSTANCES_FILE = Path.home() / '.webtool' / 'cache' / 'rsshub_instances.json'
INSTANCES_TTL = 3600


# 实例探活


def instances(proxy=None, refresh=False, need=None, timeout=10):
    """实例列表 + 探活结果 [{instance, ok, ms, items, err}], 缓存 1 小时

    公共实例可用性逐日变化, 默认实探而不是信文档。

    need=N 时凑够 N 个可用实例就返回 —— 全量探活要等每个挂掉的实例跑满
    超时, 只想找一个能用的没必要等全场。
    """
    if not refresh and INSTANCES_FILE.exists():
        try:
            o = json.loads(INSTANCES_FILE.read_text())
            lst = o.get('list') or []
            fresh = time.time() - o.get('ts', 0) < INSTANCES_TTL
            if fresh and lst:
                got = [i for i in lst if i.get('ok')]
                # partial 缓存 (有实例没探到) 只在"只需要够 N 个"时可信;
                # 要全量清单就得真探完, 否则会把 '未探测' 当结论用
                if need is not None and len(got) >= need:
                    return lst
                if o.get('complete'):
                    return lst
        except Exception:
            pass
    from webtool.net import transport

    def probe(base):
        t0 = time.time()
        # 单线路: 线路由路由表一次决定 (未配代理时 'auto' 落到默认规则),
        # 请求失败就是失败 —— 失败只意味着这个实例不可用, 不换线重试。
        px = proxy or 'auto'
        last = 'no route'
        try:
            text, st, _ = transport.get(base + PROBE_ROUTE, kind='plain',
                                        timeout=timeout, proxy=px)
            n = len(re.findall(r'<(?:item|entry)[\s>]', text or ''))
            if st == 200 and n:
                return {'instance': base, 'ok': True, 'items': n,
                        'ms': int((time.time() - t0) * 1000), 'err': ''}
            last = f'HTTP {st}' + (' 0 items' if st == 200 else '')
        except Exception as e:
            last = str(e)[:50]
        return {'instance': base, 'ok': False, 'items': 0,
                'ms': int((time.time() - t0) * 1000), 'err': last}

    jobs = {b: (lambda b=b: probe(b)) for b in default_instances()}
    if need is None:
        # 全量清单 (`feed instances` 用法) 必须等全部回来, 否则早退会把没探
        # 到的显示成 '未探测' —— 看着像挂了, 其实没问过
        found = race(jobs, ok=lambda r: False, timeout=timeout * 3, need=-1)
    else:
        found = race(jobs, ok=lambda r: bool(r and r['ok']),
                     timeout=timeout * 3, need=need)
    out = [found.get(b, {'instance': b, 'ok': False, 'items': 0, 'ms': 0,
                          'err': '未探测'})
           for b in default_instances()]
    complete = all(x['err'] != '未探测' for x in out)
    # 早退的部分结果也落盘, 否则紧接着的全量调用把刚省下的等待又付一遍
    INSTANCES_FILE.parent.mkdir(parents=True, exist_ok=True)
    INSTANCES_FILE.write_text(json.dumps(
        {'ts': time.time(), 'list': out, 'complete': complete},
        ensure_ascii=False))
    return out
