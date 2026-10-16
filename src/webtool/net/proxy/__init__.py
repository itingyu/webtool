"""代理与全局配置 (原 net/proxy.py, 按职责拆子包)

对外接口保持不变: `from webtool.net import proxy; proxy.load_config()` /
`proxy.handle(args, cfg)` / `proxy.CONFIG_PATH` 等照常可用, 本 __init__ 再导出。

子模块:
  store      config.json 读写 + 代理 URL 原语 + 遗留键迁移 (可复用, 不认识 CLI)
  rules_cli  rules.json 读写 + rule add/del/tidy/rules 子命令
  auth       代理凭据保险库 (setpass/delpass/passwd)
  geo        GeoIP / geosite / ASN 库配置与体检
  pool       全局/命名代理增删查测 (get/set/unset/test/named/noproxy)
  cli        子命令分发 (handle)
"""
# `X as X` = 显式再导出 (ruff F401 认这个写法)
from webtool.core.config_data import USER_DIR as USER_DIR
from webtool.net.proxy.auth import (_delpass as _delpass, _passwd as _passwd,
                                    _setpass as _setpass)
from webtool.net.proxy.cli import handle as handle
from webtool.net.proxy.geo import (_asn as _asn, _geoip as _geoip,
                                   _geosite as _geosite)
from webtool.net.proxy.pool import (_get as _get, _named as _named,
                                    _noproxy as _noproxy, _set as _set,
                                    _test as _test, _unset as _unset)
from webtool.net.proxy.rules_cli import (
    _default_proxy_url as _default_proxy_url, _drift_hint as _drift_hint,
    _load_rules_file as _load_rules_file, _proxy_is_used as _proxy_is_used,
    _ruleadd as _ruleadd, _ruledel as _ruledel, _rules as _rules,
    _rules_path as _rules_path, _save_rules as _save_rules, _tidy as _tidy)
from webtool.net.proxy.store import (
    CONFIG_PATH as CONFIG_PATH, DEFAULTS as DEFAULTS, _KNOWN as _KNOWN,
    _LEGACY_KEYS as _LEGACY_KEYS, _MIGRATION_NOTES as _MIGRATION_NOTES,
    _migrate_legacy_config as _migrate_legacy_config,
    _norm_proxy_url as _norm_proxy_url, _read_json as _read_json,
    _rule_syntax as _rule_syntax, _write_json as _write_json,
    hostport_of as hostport_of, load_config as load_config,
    proxy_url_parts as proxy_url_parts, save_config as save_config)

__all__ = [
    'CONFIG_PATH', 'DEFAULTS', 'USER_DIR', '_KNOWN', '_LEGACY_KEYS',
    '_MIGRATION_NOTES', 'handle', 'hostport_of', 'load_config',
    'proxy_url_parts', 'save_config',
]
