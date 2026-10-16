"""规则引擎 (原 net/rules.py, 按职责拆子包)

代理路由规则 + 各环节 kind 规则。对外接口保持不变: 老代码 `from webtool.net
import rules` 后 `rules.router() / rules.Router / rules.resolve_route` 等照常可用,
本 __init__ 负责再导出。

子模块:
  spec      动作解析 + kind 元数据注册表 (新环节在此之外 register, 不用改本包)
  builtin   内置三个 kind (http/retry/breaker) 的元数据
  matchers  域名/端口/协议/CIDR/glob/ASN 匹配器 + URL 解析
  geodb     IP → 国家码/ASN, DNS 转发
  router    Router: 线路决策 + params_for
  tidy      规则表整理: seed / shadow_check / tidy_spec
  migrate   命名代理明文密码 → 保险库
  loader    读文件 → 迁移 → 构造 Router (带缓存) + resolve_route
"""
from webtool.net.rules import builtin as _builtin      # noqa: F401  注册内置 kind
from webtool.net.rules.geodb import geoip_asn, geoip_country, resolve_ip
from webtool.net.rules.geodb import _reader            # noqa: F401  兼容旧引用
from webtool.net.rules.loader import (
    explain_route, load_router, router, resolve_route)
from webtool.net.rules.migrate import migrate_plaintext_proxies
from webtool.net.rules.router import Router
from webtool.net.rules.spec import (
    MATCH_KEYS, RuleError, RuleSpec, VALID_ACTIONS, register, resolve_action,
    spec_for, specs)
from webtool.net.rules.tidy import seed_rules, shadow_check, tidy_spec

__all__ = [
    'MATCH_KEYS', 'RuleError', 'RuleSpec', 'Router', 'VALID_ACTIONS',
    'explain_route', 'geoip_asn', 'geoip_country', 'load_router',
    'migrate_plaintext_proxies', 'register', 'resolve_action', 'resolve_ip',
    'resolve_route', 'router', 'seed_rules', 'shadow_check', 'spec_for',
    'specs', 'tidy_spec',
]
