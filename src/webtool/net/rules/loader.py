"""规则加载: 读文件 → 迁移 → 构造 Router, 带配置/文件指纹缓存

`router()` 是全仓唯一的 Router 工厂 (调用点一律现取, 不做模块级快照),
`resolve_route()` 是线路决策对外的入口。
"""
import json
import logging
import os

from webtool.net.rules.migrate import migrate_plaintext_proxies
from webtool.net.rules.router import Router
from webtool.net.rules.spec import RuleError

logger = logging.getLogger(__name__)


def load_router(cfg):
    """从配置构造 Router。规则只来自 rules_file 指向的文件 (默认 rules.json);
    geoip/geosite/asn 库路径: 文件里的值优先, config.json 里的作回落"""
    spec = _load_spec(cfg)
    if isinstance(spec, _BrokenSpec):
        r = Router({})
        r.warnings = spec.warnings + [
            '已退回: 未命中规则一律直连 (不能退成"用全局代理", '
            '那会让直连该走的目标悄悄挂掉)']
        return r
    spec, _migrated = migrate_plaintext_proxies(spec, _rules_file_of(cfg))
    return Router(spec or {},
                  geoip_db=spec.get('geoip_db') or cfg.get('geoip_db'),
                  asn_db=spec.get('asn_db') or cfg.get('asn_db'),
                  geosite_db=spec.get('geosite_db') or cfg.get('geosite_db'))


def _load_spec(cfg):
    """读规则文件。文件坏了不能整个工具瘫掉: 退回全直连, 原因挂 warnings"""
    path = _rules_file_of(cfg)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            spec = json.load(f)
        return spec if isinstance(spec, dict) else {}
    except (ValueError, OSError) as e:
        return _BrokenSpec(path, e)


class _BrokenSpec(dict):
    """坏文件占位: Router 拿到空规则, warnings 里带原因"""

    def __init__(self, path, err):
        super().__init__()
        self.warnings = [f'规则文件读取失败: {path}: {err}']


_router_cache = (None, None)


def _cfg_stamp(cfg):
    """配置文件 + 规则文件的指纹, 任一变了就重建 Router"""
    import webtool.net.proxy as _px
    st = []
    for p in (_px.CONFIG_PATH, _rules_file_of(cfg)):
        try:
            s = os.stat(p)
            st.append((p, s.st_mtime_ns, s.st_size))
        except OSError:
            st.append((p, 0, 0))
    return tuple(st)


def _rules_file_of(cfg):
    p = (cfg or {}).get('rules_file')
    if p:
        return os.path.expanduser(p)
    from webtool.core.config_data import USER_DIR
    return str(USER_DIR / 'rules.json')


def router(cfg=None):
    """带缓存的 Router: 每个请求都会问一次路由, 重建不能太贵"""
    global _router_cache
    if cfg is None:
        from webtool.net.proxy import load_config
        cfg = load_config()
    stamp = _cfg_stamp(cfg)
    if _router_cache[0] == stamp and _router_cache[1] is not None:
        return _router_cache[1]
    _router_cache = (stamp, load_router(cfg))
    return _router_cache[1]


def resolve_route(url, cfg=None, engine=None):
    """请求链路入口: URL → 该走的代理 URL (None = 直连)

    这是让规则真正生效的那一刀。调用方把 proxy 传成 'auto' 即可接入, 语义:
      'auto'   问路由 (默认动作/规则/命名代理)
      None     直连 (老代码显式要直连, 保持不变)
      'direct' 强制直连
      <url>    强制走这条 (老代码显式指定, 保持不变)

    只有 'auto' 会查规则 —— 这样既接上了新能力, 又完全不改变现有调用方的行为。
    """
    r = router(cfg)
    try:
        p = r.proxy_for(url)
        act = r.rule(url)[0]
        logger.debug('路由 %s -> %s', url, act)
        return p
    except RuleError:
        raise
    except Exception:
        # 路由本身出错不能连带把正常请求挂掉, 退回直连
        return None


def explain_route(url, cfg=None):
    """试算: 返回命中了哪条规则、最终走哪条线 (不真正发请求)"""
    return router(cfg).explain(url)
