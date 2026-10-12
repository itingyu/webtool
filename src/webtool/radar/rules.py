"""Radar 规则库 (公共实例 GET /api/radar/rules)

只有 source(网页 URL 模式) → target(路由模板), 用于 --from-url 反推, 以及
主源拉取失败时的降级查询路径。
"""

import json
import time
from pathlib import Path

from webtool.radar.instances_cfg import default_instances
from webtool.radar.template import render_url

RADAR_FILE = Path.home() / '.webtool' / 'cache' / 'radar_rules.json'
RADAR_TTL = 7 * 86400


# ---------------------------------------------------------------- Radar 规则库 (降级/反推)


def load_rules(proxy=None, refresh=False, timeout=20):
    """载入 radar rules (缓存优先), 返回 dict; 失败抛异常"""
    if not refresh and RADAR_FILE.exists():
        try:
            o = json.loads(RADAR_FILE.read_text())
            if time.time() - o.get('ts', 0) < RADAR_TTL and o.get('rules'):
                return o['rules']
        except Exception:
            pass
    from webtool.net import transport
    errs = []
    for base in default_instances():
        # 直连优先 (CF 对代理出口更敏感), 失败再试代理
        attempts = [None] + ([proxy] if proxy else [])
        for px in attempts:
            try:
                text, st, _ = transport.get(base + '/api/radar/rules', kind='plain',
                                            timeout=timeout, proxy=px,
                                            allow_fallback=False)
                if st == 200 and text.lstrip().startswith('{'):
                    rules = json.loads(text)
                    RADAR_FILE.parent.mkdir(parents=True, exist_ok=True)
                    RADAR_FILE.write_text(json.dumps(
                        {'ts': time.time(), 'base': base, 'rules': rules},
                        ensure_ascii=False))
                    return rules
                errs.append(f'{base}: HTTP {st}')
            except Exception as e:
                errs.append(f'{base}: {str(e)[:60]}')
    raise RuntimeError('radar rules 拉取失败 (全实例): ' + '; '.join(errs))


def search(rules, kw, limit=30):
    """按关键词查 radar 规则 (域名、站名、标题、target 模糊匹配)

    返回 [(domain, site_name, title, target)] — target 保留 :param 模板
    """
    kw_l = kw.lower()
    out = []
    for dom, paths in rules.items():
        if not isinstance(paths, dict):
            continue
        site = paths.get('_name', '')
        hit_site = kw_l in dom.lower() or kw_l in site.lower()
        for path, arr in paths.items():
            if path == '_name' or not isinstance(arr, list):
                continue
            for r in arr:
                t = r.get('title', '')
                tg = r.get('target', '')
                if hit_site or kw_l in t.lower() or kw_l in tg.lower():
                    out.append((dom, site, t, tg))
    # 排序: 域名精确命中 > 站名命中; 同域按 title
    out.sort(key=lambda x: (0 if kw_l in x[0].lower() else 1, x[0], x[2]))
    return out[:limit]


def render(instance, target, **params):
    """兼容旧接口: 实例前缀 + radar target + 关键字参数 → 订阅 URL"""
    return render_url(instance, target, params)


def stats(rules):
    sites = sum(1 for v in rules.values()
                if isinstance(v, dict) and '_name' in v)
    n = sum(len([r for p, rs in v.items() if isinstance(rs, list) for r in rs])
            for v in rules.values() if isinstance(v, dict))
    return sites, n
