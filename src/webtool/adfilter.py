# -*- coding: utf-8 -*-
"""搜索结果广告过滤

三层判定 (is_ad=True 即可被 --no-ad 过滤):
1. 引擎标注: baidu 的 result-op 聚合卡片直接标 is_ad
2. 标题/摘要命中广告特征词
3. URL 命中广告/推广域名

宁可漏判不可误杀 — 特征词都是强广告信号, 不含"疑似"级噪声词。
"""
import re
from urllib.parse import urlparse

from .config_data import load

_CFG = load('adfilter', 'filters.json')

# 强广告特征词 (标题/摘要) / 广告落地域名 / URL 广告参数, 均可经 ~/.webtool/filters.json 覆盖
AD_KEYWORDS = _CFG.get('keywords', [])
AD_DOMAINS = _CFG.get('domains', [])
AD_URL_PAT = re.compile('|'.join(_CFG.get('url_patterns', ['$^'])) or '$^', re.I)


def is_ad(item):
    """单条结果广告判定"""
    url = item.get('url', '') or ''
    if item.get('is_ad'):
        return True
    host = urlparse(url).netloc.lower()
    if any(host == d or host.endswith('.' + d) for d in AD_DOMAINS):
        return True
    if AD_URL_PAT.search(url):
        return True
    text = (item.get('title', '') + ' ' + item.get('snippet', '')).lower()
    return any(k.lower() in text for k in AD_KEYWORDS)


def mark_ads(results):
    """批量标记 is_ad 字段 (不删除, 交给调用方决定)"""
    for r in results:
        if is_ad(r):
            r['is_ad'] = True
    return results


def filter_ads(results):
    """硬过滤: 移除广告结果"""
    return [r for r in results if not is_ad(r)]
