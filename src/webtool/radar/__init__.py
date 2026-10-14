"""radar: RSSHub 路由查询、参数填充、实例探活与官网 feed 兜底

两个数据源, 主备关系:
1. routes   官方路由目录 routes.json (数千站/路由), 唯一能"照着填参"的源
2. rules    Radar 规则库 (网页 URL 模式 → 路由模板), 用于 --from-url 反推

支撑模块: template(模板语法) / instances(公共实例探活) / official(官网 feed 探测)。
本模块只做再导出, 上层 import webtool.radar 后直接用 search_routes/fill_path 等。
"""
from webtool.radar.instances_cfg import PROBE_ROUTE, default_instances
from webtool.radar.instances import instances
from webtool.radar.official import (best_instance, official_coverage,
                                    official_feeds, official_section_url,
                                    probe_official)
from webtool.radar.race import race
from webtool.radar.routes import (from_url, load_routes, routes_stats,
                                  search_routes)
from webtool.radar.template import MissingParams, fill_path, parse_params, render_url

# 旧名兼容: 原 radar.py 单文件时代的私有名, 调用点还没全改过来
_PROBE_ROUTE = PROBE_ROUTE
_default_instances = default_instances

__all__ = [
    'PROBE_ROUTE', 'MissingParams', 'best_instance', 'default_instances',
    'fill_path', 'from_url', 'instances', 'load_routes',
    'official_coverage', 'official_feeds', 'official_section_url', 'parse_params',
    'probe_official', 'race', 'render_url', 'routes_stats',
    'search_routes',
]
