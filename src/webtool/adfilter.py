# -*- coding: utf-8 -*-
"""搜索结果广告过滤 (filter 插件: ad)

三层判定 (is_ad=True 即可被 --no-ad 过滤):
1. 引擎标注: baidu 的 result-op 聚合卡片直接标 is_ad
2. 标题/摘要命中广告特征词
3. URL 命中广告/推广域名

宁可漏判不可误杀 — 特征词都是强广告信号, 不含"疑似"级噪声词。
"""
import re
from urllib.parse import urlparse

from .config_data import load


def _cfg():
    """每次读: filters.json 改动按 mtime 自动生效"""
    return load('adfilter', 'filters.json')


def is_ad(item):
    """单条结果广告判定"""
    c = _cfg()
    url = item.get('url', '') or ''
    if item.get('is_ad'):
        return True
    host = urlparse(url).netloc.lower()
    if any(host == d or host.endswith('.' + d) for d in c.get('domains', ())):
        return True
    pat = '|'.join(c.get('url_patterns', ())) or '$^'
    if re.search(pat, url, re.I):
        return True
    text = (item.get('title', '') + ' ' + item.get('snippet', '')).lower()
    return any(k.lower() in text for k in c.get('keywords', ()))


def mark_ads(results):
    """批量标记 is_ad 字段 (不删除, 交给调用方决定)"""
    for r in results:
        if is_ad(r):
            r['is_ad'] = True
    return results


def filter_ads(results):
    """硬过滤: 移除广告结果"""
    return [r for r in results if not is_ad(r)]


def filter_ad(results, ctx=None):
    """filter 插件入口: (结果列表, 上下文) -> 过滤后列表"""
    return filter_ads(results)
