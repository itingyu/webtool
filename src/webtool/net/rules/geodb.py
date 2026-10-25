"""IP 地理/ASN 查询与 DNS 转发: 规则里 geoip/asn 条件的支撑

只做"IP → 国家码 / ASN"和"域名 → IP"两件事, 不认识 Router。
mmdb 读取器与查询结果都带进程内缓存 (GeoIP 数据几乎不变)。
"""
import os

from webtool.net import dns as _dns

# GeoIP 查表缓存: ip → 国家码 (GeoIP 数据几乎不变, 缓存久一点没问题)
_GEO_CACHE = {}
_MMDB = {}


def resolve_ip(host, timeout=3.0):
    """域名 → IP (带进程内缓存)。已是 IP 直接返回。"""
    return _dns.resolve_ip(host)


def _reader(path):
    """mmdb 读取器缓存 (同一路径只开一次)"""
    if not path:
        return None
    p = os.path.expanduser(str(path))
    if p in _MMDB:
        return _MMDB[p]
    try:
        import maxminddb
    except ImportError:
        _MMDB[p] = None                   # 没装: 缓存 None, 别反复 import 失败
        return None
    if not os.path.isfile(p):
        _MMDB[p] = None
        return None
    try:
        r = maxminddb.open_database(p)
    except Exception:
        _MMDB[p] = None
        return None
    _MMDB[p] = r
    return r


def geoip_country(ip, db_path):
    """IP → 国家码 ('CN'/'US'), 查不到返回 None。两种库都吃:
    MaxMind 的 .mmdb, 以及 v2ray/sing-box 的 geoip.dat (protobuf)。"""
    if not ip or not db_path:
        return None
    ck = (db_path, ip)
    if ck in _GEO_CACHE:
        return _GEO_CACHE[ck]
    from webtool.net import geodata as _gd
    out = _gd.country_of_ip(ip, db_path)
    _GEO_CACHE[ck] = out
    return out


def geoip_asn(ip, db_path):
    """IP → ASN 号, 查不到返回 None"""
    if not ip or not db_path:
        return None
    r = _reader(db_path)
    if r is None:
        return None
    try:
        rec = r.get(ip)
        if rec:
            return rec.get('autonomous_system_number')
    except Exception:
        return None
    return None
