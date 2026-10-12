"""RSSHub 公共实例的默认表与探活常量

可用性每天在变, 别当常量信 —— 一律走 instances.instances() 现探现用。
用户可在 ~/.webtool/instances.json 同构覆盖 data/instances.json。
"""
from webtool.core.config_data import load as _cfg_load

def default_instances():
    """实例 URL 列表; 配置缺失时回落到内置三条"""
    return list((_cfg_load('rsshub', 'instances.json') or {}).get('instances') or [])

# 探活用的廉价路由, 任意一个实例能出条目即视为活着
PROBE_ROUTE = '/36kr/newsflashes'
