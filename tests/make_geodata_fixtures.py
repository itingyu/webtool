"""生成 geodata 测试样本 (v2ray/sing-box .dat protobuf 格式)

这里的样本是给**单元测试**用的: 按同样的 wire format 手写最小可解析样本,
几 KB 就能把解析逻辑锁住 (格式哪天变了 / 哪个分支写错了, 样本照样测得出),
不必拿十几 MB 真库拖慢每次跑测试。
真库另有其路: 随包分发在 src/webtool/data/geo/ (geosite.dat / geoip.dat),
首次运行由 bootstrap 落到 ~/.webtool/geo/, `webtool proxy geo update` 负责刷新;
解析对照仍可用 GEODATA_REAL_GEOIP / GEODATA_REAL_GEOSITE 指过去。

## 为什么自己手写 protobuf 而不用 protobuf 库

规则库里这层结构极简 (一层 repeated 子消息 + 几种 varint/bytes 字段),
引 protobuf 只会让测试多一个依赖。几十行 varint 写入就够, 而且测试真正验的
是"解析端能不能读", 写入端越朴素越不容易自己骗自己。
"""
import ipaddress
import os

# Domain_Type 枚举, 与 webtool.net.geodata 的常量一一对应
DOMAIN_TYPES = {
    'plain': 0,
    'regex': 1,
    'domain': 2,      # 后缀匹配: 条目本身 + 所有子域
    'full': 3,        # 精确匹配: 只有条目本域
    'keyword': 4,
}


# ---- protobuf 写入 (wire type 0=varint, 1=64bit, 2=length-delimited, 5=32bit) ----

def varint(n):
    n = int(n)
    if n < 0:
        raise ValueError('varint 不支持负数')
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def tag(field, wt):
    return varint((field << 3) | wt)


def msg_bytes(field, payload):
    return tag(field, 2) + varint(len(payload)) + payload


def msg_varint(field, n):
    return tag(field, 0) + varint(n)


def field_str(field, s):
    return msg_bytes(field, s.encode())


# ---- geoip.dat: GeoIPList{ repeated GeoIP country=1 }
#      GeoIP  { string country=1; repeated CIDR cidr=2 }
#      CIDR   { bytes ip=1; uint32 prefix=2 }

def make_geoip(groups):
    """groups: {'CN': ['1.2.3.0/24', ...], ...} → bytes"""
    out = bytearray()
    for ctry, cidrs in groups.items():
        body = bytearray(field_str(1, ctry))
        for cidr in cidrs:
            net = ipaddress.ip_network(cidr, strict=True)
            entry = (msg_bytes(1, net.network_address.packed)
                     + msg_varint(2, net.prefixlen))
            body += msg_bytes(2, entry)
        out += msg_bytes(1, bytes(body))
    return bytes(out)


# ---- geosite.dat: GeoSiteList{ repeated Site site=1 }
#      Site   { string country=1; repeated Domain domain=2 }
#      Domain { Domain_Type type=1; string value=2 }

def make_geosite(groups):
    """groups: {'CN': [('domain','baidu.com'), ('full','jd.example.cn')]} → bytes

    条目类型可以给名字 ('domain'/'full'/'regex'/'keyword'/'plain') 或直接给
    枚举整数; 给名字时这里查 DOMAIN_TYPES 转成整数。
    """
    out = bytearray()
    for ctry, domains in groups.items():
        body = bytearray(field_str(1, ctry))
        for ty, val in domains:
            code = DOMAIN_TYPES.get(ty, ty) if isinstance(ty, str) else int(ty)
            entry = msg_varint(1, code) + field_str(2, val)
            body += msg_bytes(2, entry)
        out += msg_bytes(1, bytes(body))
    return bytes(out)


# ---- 给测试用的固定样本 ----
# 取值刻意做得"互相不沾": 1.2.3.4 只能在 CN、8.8.8.8 只能在 US,
# example.cn 属于 CN 但 example.com 不属于 —— 这样"判错分类"不会因为样本
# 重叠而蒙混过关。

def make_geoip_dat():
    return make_geoip({
        'CN': ['1.2.3.0/24', '223.5.5.0/24', '114.114.114.0/24'],
        'US': ['8.8.8.0/24'],
        'JP': ['203.0.113.0/24'],
    })


def make_geosite_dat():
    return make_geosite({
        'CN': [('domain', 'baidu.com'), ('domain', 'qq.com'),
               ('domain', 'example.cn')],
        'GOOGLE': [('domain', 'google.com')],
        'GITHUB': [('domain', 'github.com')],
        # 精确条目: example.com 本域命中, www.example.com 不命中
        'EXACTCAT': [('full', 'example.com')],
        'CATEGORY-ADS': [('full', 'ads.tracker.io')],
    })


def build(dest_dir):
    """把两个样本写到 dest_dir, 返回 (geoip_bytes, geosite_bytes)"""
    os.makedirs(dest_dir, exist_ok=True)
    g, s = make_geoip_dat(), make_geosite_dat()
    with open(os.path.join(dest_dir, 'geoip.dat'), 'wb') as f:
        f.write(g)
    with open(os.path.join(dest_dir, 'geosite.dat'), 'wb') as f:
        f.write(s)
    return g, s


if __name__ == '__main__':
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else 'tests/data'
    build(d)
    print(f'已生成样本到 {d}')