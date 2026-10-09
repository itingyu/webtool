# -*- coding: utf-8 -*-
"""搜索结果广告过滤

三层判定 (is_ad=True 即可被 --no-ad 过滤):
1. 引擎标注: baidu 的 result-op 聚合卡片直接标 is_ad
2. 标题/摘要命中广告特征词
3. URL 命中广告/推广域名

原则: 宁可漏判不可误杀 — 特征词都是强广告信号, 不含"疑似"级噪声词。
"""
import re
from urllib.parse import urlparse

# 强广告特征词 (标题/摘要)
AD_KEYWORDS = [
    '百度营销', '招商加盟', '免费注册领取', '限时优惠', '立即咨询',
    '官方网站注册', '点击咨询', '在线客服', '预约试听', '领取优惠券',
    '低价', '促销', '代办理', '一站式服务', '官方授权经销商',
    'sponsored', 'ad ·', 'promo',
]

# 常见广告/推广落地域名
AD_DOMAINS = [
    'baidujc.com',          # 百度联盟跳转
    'pos.baidu.com',
    'recommend_list.baidu.com',
    'nourl.ubs.baidu.com',
    'ocsp.baidu.com',
]

# 广告参数特征
AD_URL_PAT = re.compile(r'[?&](prosite=1|tn=baiduad|bd_vid=)', re.I)


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
