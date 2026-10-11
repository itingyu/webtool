# -*- coding: utf-8 -*-
"""radar: RSSHub Radar 规则库查询 (1310 站点 / 5284 条可订阅路由)

数据源: 任意公共实例 GET /api/radar/rules (官方 rsshub.app 有 CF 挑战, 用社区实例),
缓存 ~/.webtool/cache/radar_rules.json (TTL 7 天, rules 更新不频繁)。

结构: {域名: {'_name': 站名, web路径: [{title, source, target, docs?}]}}
target 即 RSSHub 路由模板 (:param 为参数), 实例前缀 + target + 实参 = 订阅 URL。
"""

import json
import re
import time
import urllib.parse
from pathlib import Path

RADAR_FILE = Path.home() / '.webtool' / 'cache' / 'radar_rules.json'
RADAR_TTL = 7 * 86400
_DEFAULT_INSTANCES = [
    'https://rsshub.rssforever.com',
    'https://hub.slarker.me',
    'https://rss.wudifeixue.com',
    'https://rsshub.isrss.com',
]


def load_rules(proxy=None, refresh=False, timeout=20):
    """载入 radar rules (缓存优先), 返回 dict; 失败抛异常"""
    if not refresh and RADAR_FILE.exists():
        try:
            o = json.loads(RADAR_FILE.read_text())
            if time.time() - o.get('ts', 0) < RADAR_TTL and o.get('rules'):
                return o['rules']
        except Exception:
            pass
    from . import transport
    errs = []
    for base in _DEFAULT_INSTANCES:
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
    """按关键词查站点/路由 (域名、站名、标题、target 模糊匹配)

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


def render_url(instance, target, **params):
    """实例前缀 + 路由模板 + 参数 → 订阅 URL

    params 按 target 中 :name 出现顺序填入; 未提供的可选参数 (:name?) 剔除该段。
    简化处理: 按顺序替换, 缺参留 :name (让 RSSHub 自己报错提示)。
    """
    url = target
    for name, val in params.items():
        url = url.replace(f':{name}', str(val))
    url = re.sub(r'/:[a-zA-Z_]+\??(?=/|$)', '', url)   # 未提供的可选段剔除
    url = url.rstrip('/')
    return instance.rstrip('/') + url


def stats(rules):
    sites = sum(1 for v in rules.values()
                if isinstance(v, dict) and '_name' in v)
    n = sum(len([r for p, rs in v.items() if isinstance(rs, list) for r in rs])
            for v in rules.values() if isinstance(v, dict))
    return sites, n
