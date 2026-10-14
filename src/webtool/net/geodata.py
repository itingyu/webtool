"""GeoIP / GeoSite 数据读取: MaxMind .mmdb 与 sing-box·v2ray .dat 两种格式

v2ray-rules-dat / sing-box 生态那套 `.dat` 是 protobuf 序列化的, 不是 mmdb:
    geoip.dat   GeoIPList{ repeated GeoIP country = 1 }
                GeoIP  { string country = 1; repeated CIDR cidr = 2 }
                CIDR   { bytes ip = 1; uint32 prefix = 2 }
    geosite.dat GeoSiteList{ repeated Site site = 1 }
                Site   { string country = 1; repeated Domain domain = 2 }
                Domain { Domain_Type type = 1; string value = 2 }
                Domain_Type: 0=plain 1=regex 2=domain(后缀) 3=full(全等)

为什么不直接用 mmdb 顶替:
- geosite 是**按域名分类**的 (`CN` / `GOOGLE` / `CATEGORY-ADS` 一千五百多个),
  判"这个域名属于哪类"不需要 DNS —— mmdb 只能按 IP 反查, 每次判规则都要解析
  一次 DNS, 又慢又会因为 CDN 就近解析把结果判歪。
- 分类名是大写的 (`GOOGLE` 而非 `google`), 这里统一大写比较。

惰性解析: geoip.dat 16MB / geosite.dat 11MB, 全量解成 dict 要好几秒。
但规则里真正引用到的分类通常只有个位数, 所以按需解码 + 进程内缓存,
第一次问某个分类才付那笔开销, 之后命中缓存。
"""
import ipaddress
import os
import re
import struct

__all__ = ['detect_format', 'country_of_ip', 'domain_in_category',
           'has_category', 'categories', 'GeoDataError']

# Domain_Type 枚举 → 判定方式
_T_RE, _T_SUFFIX, _T_FULL, _T_KEYWORD = 1, 2, 3, 4

_CACHE = {}      # (abspath, mtime_ns, kind, key) → 解好的结构
_INDEX = {}      # abspath → {kind: {name: (offset, length)}}, 懒建


class GeoDataError(RuntimeError):
    """GeoIP/GeoSite 数据不可用 (文件损坏 / 格式不认识)"""


def _varint(b, i):
    r = s = 0
    while True:
        if i >= len(b):
            raise GeoDataError('protobuf 长度截断')
        x = b[i]
        i += 1
        r |= (x & 0x7F) << s
        if not (x & 0x80):
            return r, i
        s += 7
        if s > 63:
            raise GeoDataError('protobuf varint 溢出')


def _fields(b, start, end):
    """遍历 protobuf 消息的顶层字段 → (field_no, wire_type, value)"""
    i = start
    while i < end:
        key, i = _varint(b, i)
        f, wt = key >> 3, key & 7
        if wt == 0:
            v, i = _varint(b, i)
            yield f, wt, v
        elif wt == 2:
            n, i = _varint(b, i)
            if i + n > end:
                return
            yield f, wt, b[i:i + n]
            i += n
        elif wt == 5:
            yield f, wt, b[i:i + 4]
            i += 4
        elif wt == 1:
            yield f, wt, b[i:i + 8]
            i += 8
        else:
            return


def detect_format(path):
    """判断数据文件是 mmdb 还是 dat → 'mmdb' | 'geoip' | 'geosite' | None"""
    if not path or not os.path.isfile(path):
        return None
    try:
        size = os.path.getsize(path)
        with open(path, 'rb') as f:
            head = f.read(8192)
            # mmdb 的 "« MaxMind.com" 标记在文件**尾部**元数据段里, 不在开头
            f.seek(max(0, size - 131072))
            tail = f.read()
    except OSError:
        return None
    if b'MaxMind.com' in tail:
        return 'mmdb'
    if not head:
        return None
    # .dat: 顶层是 field 1 的重复子消息, 每个子消息 field1=分类名
    try:
        for f, wt, v in _fields(head, 0, len(head)):
            if f != 1 or wt != 2 or not isinstance(v, bytes) or not v:
                continue
            name = None
            for f2, wt2, v2 in _fields(v, 0, len(v)):
                if f2 == 1 and wt2 == 2 and isinstance(v2, bytes):
                    name = v2.decode('utf-8', 'replace')
                    break
            if not name:
                continue
            # geoip 与 geosite 的条目结构不同, 用**条目第一个字段的 wire type**
            # 区分, 比看内容靠谱:
            #   geoip    CIDR  { bytes ip = 1; uint32 prefix = 2 } → field1 = wt 2
            #   geosite Domain{ Domain_Type type = 1; string value = 2 } → wt 0
            for f2, wt2, v2 in _fields(v, 0, len(v)):
                if f2 == 2 and wt2 == 2 and isinstance(v2, bytes) and v2:
                    for f3, wt3, _ in _fields(v2, 0, len(v2)):
                        if f3 == 1:
                            return 'geosite' if wt3 == 0 else 'geoip'
                    return 'geoip'
    except GeoDataError:
        return None
    return None


def _slice(path):
    with open(path, 'rb') as f:
        return f.read()


def _index(path):
    """列出顶层分组名 → 字节区间 (不解内层, 只扫一遍顶层)"""
    try:
        st = os.stat(path)
    except OSError:
        return {}
    key = (os.path.abspath(path), st.st_mtime_ns, 'idx')
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    b = _slice(path)
    idx = {}
    i = 0
    while i < len(b):
        try:
            k, i = _varint(b, i)
        except GeoDataError:
            break
        wt = k & 7
        if wt == 2:
            n, i = _varint(b, i)
            if i + n > len(b):
                break
            start = i
            name = None
            for f2, wt2, v2 in _fields(b, start, start + n):
                if f2 == 1 and wt2 == 2 and name is None and isinstance(v2, bytes):
                    name = v2.decode('utf-8', 'replace')
                if name:
                    break
            if name:
                idx[name.upper()] = (start, n)
            i = start + n
        elif wt == 0:
            _, i = _varint(b, i)
        elif wt == 5:
            i += 4
        elif wt == 1:
            i += 8
        else:
            break
    _CACHE[key] = idx
    return idx


def categories(path):
    """列出数据文件里可用的分类名 (大写)"""
    fmt = detect_format(path)
    if fmt == 'mmdb':
        return []
    if fmt is None:
        raise GeoDataError(f'不认识的 GeoData 格式: {path}')
    return sorted(_index(path).keys())


def _decode_geoip_group(b, start, n):
    """GeoIP 分组 → [(ip_int, mask_int)]"""
    nets = []
    for f2, wt2, v2 in _fields(b, start, start + n):
        if f2 != 2 or wt2 != 2:
            continue
        ip_b, prefix = None, 32
        for f3, wt3, v3 in _fields(v2, 0, len(v2)):
            if f3 == 1 and wt3 == 2 and isinstance(v3, bytes):
                ip_b = v3
            elif f3 == 2 and wt3 == 0:
                prefix = v3
        if not ip_b:
            continue
        try:
            if len(ip_b) == 4:
                val = struct.unpack('>I', ip_b)[0]
            elif len(ip_b) == 16:
                val = int.from_bytes(ip_b, 'big')
            else:
                continue
            bits = 32 if len(ip_b) == 4 else 128
            prefix = max(0, min(bits, prefix))
            mask = ((1 << prefix) - 1) << (bits - prefix) if prefix else 0
            nets.append((val & mask, mask))
        except (struct.error, ValueError):
            continue
    return nets


def _decode_geosite_group(b, start, n):
    """GeoSite 分组 → [(type, value)]"""
    out = []
    for f2, wt2, v2 in _fields(b, start, start + n):
        if f2 != 2 or wt2 != 2:
            continue
        ty, val = 0, None
        for f3, wt3, v3 in _fields(v2, 0, len(v2)):
            if f3 == 1 and wt3 == 0:
                ty = v3
            elif f3 == 2 and wt3 == 2 and isinstance(v3, bytes):
                val = v3.decode('utf-8', 'replace')
        if val:
            out.append((ty, val))
    return out


def _group(path, kind, name):
    """取并缓存某个分类的解码结果"""
    name = (name or '').upper()
    idx = _index(path)
    span = idx.get(name)
    if not span:
        return None
    st = os.stat(path)
    key = (os.path.abspath(path), st.st_mtime_ns, kind, name)
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    b = _slice(path)
    start, n = span
    try:
        val = (_decode_geoip_group(b, start, n) if kind == 'geoip'
               else _decode_geosite_group(b, start, n))
    except (GeoDataError, IndexError, ValueError, struct.error):
        # 截断/损坏的数据文件: 索引能建但某段解不开。必须降级成空而不是把
        # TypeError 抛到请求链路 —— 规则判不出来时应当"不匹配", 不是整个请求崩
        val = ()
    _CACHE[key] = val
    return val


def has_category(path, name):
    if not path or not os.path.isfile(path):
        return False
    return (name or '').upper() in _index(path)


def country_of_ip(ip, path):
    """IP → 国家码 (如 'CN' / 'US'); 支持 .mmdb 与 geoip.dat。查不到返回 None"""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    fmt = detect_format(path)
    if fmt == 'mmdb':
        try:
            import maxminddb
            rec = maxminddb.open_database(path).get(str(addr))
        except Exception:
            return None
        if not rec:
            return None
        return (rec.get('country') or {}).get('iso_code') or rec.get(
            'registered_country', {}).get('iso_code')
    if fmt != 'geoip':
        return None
    val = int(addr)
    for ctry, (_, _) in _index(path).items():
        nets = _group(path, 'geoip', ctry)
        if not nets:
            continue
        for net, mask in nets:
            if (val & mask) == net:
                return ctry
    return None


def domain_in_category(host, category, path):
    """域名是否属于 geosite 分类。**不需要 DNS** —— 这是 geosite 相对 mmdb
    的核心优势: 按域名分类判定, 不会因为 CDN 就近解析把 IP 判到别的国家去。

    性能: 分类预编译成 (exact集合, suffix集合, keyword列表, 正则列表)。
    suffix 匹配靠**逐级剥标签查集合** (a.b.c → a.b.c / b.c / c), 是 O(标签数)
    次哈希查找, 不是逐条比对 —— CN 这类上万条的分类否则单次要 5ms+。
    """
    if not host:
        return False
    host = host.strip('.').lower()
    idx = _site_index(path, category)
    if not idx:
        return False
    exact, suffix, keywords, regexes = idx
    if host in exact:
        return True
    # 逐级剥标签查集合: a.b.c.com → a.b.c.com / b.c.com / c.com / com
    # 每一级都要查 —— 漏掉第一级的话, 条目 "example.cn" 就匹配不上 example.cn
    # 本身 (v2ray 的 domain 条目语义是"本域 + 全部子域")。
    rest = host
    while rest:
        if rest in suffix or '.' + rest in suffix:
            return True
        if '.' not in rest:
            break
        rest = rest.split('.', 1)[1]
    if keywords:
        for kw in keywords:
            if kw in host:
                return True
    for rx in regexes:
        try:
            if rx.search(host):
                return True
        except re.error:
            continue
    return False


def _site_index(path, category):
    """分类 → 预编译查询结构, 带缓存。判不出来一律返回 None (fail-closed)"""
    global _SITE_IDX
    if not path:
        return None
    try:
        key = (os.path.abspath(path), os.path.getmtime(path), category.upper())
    except OSError:
        return None                    # 文件不存在/不可读: 不匹配, 不抛
    hit = _SITE_IDX.get(key)
    if hit is not None:
        return hit or None
    if detect_format(path) != 'geosite':
        _SITE_IDX[key] = False
        return None
    entries = _group(path, 'geosite', category)
    if entries is None:
        _SITE_IDX[key] = False          # 分类不存在于该库
        return None
    exact, suffix, keywords, regexes = set(), set(), [], []
    for ty, val in entries:
        v = val.lower()
        if ty == _T_SUFFIX:
            suffix.add(v.lstrip('.'))
        elif ty == _T_FULL:
            exact.add(v)
        elif ty == _T_RE:
            try:
                regexes.append(re.compile(val))
            except re.error:
                pass
        elif ty == _T_KEYWORD:
            keywords.append(v)
    val = (exact, suffix, tuple(keywords), tuple(regexes))
    _SITE_IDX[key] = val
    return val


_SITE_IDX = {}