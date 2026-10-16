"""DNS 解析层: 域名 → IP, 带进程内缓存 (负缓存也缓存)

只做"域名怎么变成 IP"这一件事, 不知道规则、代理、GeoIP 的存在;
rules 包等需要 IP 的模块从这里取。

TTL 读 config 的 `proxy_dns_ttl` (默认 300s), 每次现取不缓存快照 ——
这是配置热更新名实相符的前提 (见 docs/coding-standard.md §3)。

只走系统 resolver (socket.getaddrinfo): GeoIP 判定这类场景只需要
"拿个能查库的 IP", CDN 就近解析的偏差由 geosite 按域名判兜底
(见 rules._match 的 geoip 分支)。DoH 等独立解析通道有真实需求时再进
本模块, 加一个 resolver 参数即可, 不必现在抽。
"""
import ipaddress
import logging
import socket
import time

logger = logging.getLogger(__name__)

# 进程内 DNS 缓存: 域名 → (ip, 解析时刻)
_CACHE = {}
_DEFAULT_TTL = 300.0


def _ttl():
    """TTL 现取 config; 读不到配置就退默认 (DNS 失败不能连带规则失效)"""
    try:
        from webtool.net.proxy import load_config
        v = load_config().get('proxy_dns_ttl')
        return float(v) if v else _DEFAULT_TTL
    except Exception:
        return _DEFAULT_TTL


def resolve_ip(host, timeout=3.0):
    """域名 → IP (带进程内缓存)。已是 IP 直接返回; 解析失败返回 None。

    负结果同样进缓存: 规则判定路径上, 一个解析不通的域名反复重打 DNS
    只会把每次请求都拖慢 timeout 秒, 别无收益。
    """
    if not host:
        return None
    try:
        ipaddress.ip_address(host)
        return host                       # 本来就是 IP
    except ValueError:
        pass
    now = time.time()
    hit = _CACHE.get(host)
    ttl = _ttl()
    if hit and now - hit[1] < ttl:
        return hit[0]
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
        ip = infos[0][4][0]
    except (socket.gaierror, OSError, IndexError) as e:
        logger.debug('DNS 解析失败 %s: %s', host, e)
        ip = None
    logger.debug('DNS %s -> %s (ttl=%ss)', host, ip, ttl)
    _CACHE[host] = (ip, now)
    return ip


def clear_cache():
    """测试用: 清空进程内缓存"""
    _CACHE.clear()
