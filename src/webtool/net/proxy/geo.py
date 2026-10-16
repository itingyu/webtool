"""proxy 子命令: GeoIP / geosite / ASN 库的配置与体检"""
import os
import sys

from webtool.net.proxy.store import save_config


def _geoip(args, cfg):
    """geoip <库路径> — 配国家库并立刻体检。格式自动识别:
    MaxMind .mmdb 或 v2ray/sing-box 的 geoip.dat"""
    from webtool.net import geodata as _gd
    val = args.value
    if not val:
        print('usage: webtool proxy geoip <GeoLite2-Country.mmdb 或 geoip.dat>')
        return 2
    path = os.path.expanduser(val)
    if not os.path.isfile(path):
        print(f'文件不存在: {path}', file=sys.stderr)
        return 2
    fmt = _gd.detect_format(path)
    if fmt not in ('mmdb', 'geoip'):
        print(f'认不出库格式: {path}\n'
              f'支持 MaxMind .mmdb 与 v2ray/sing-box geoip.dat', file=sys.stderr)
        return 2
    cfg['geoip_db'] = path
    save_config(cfg)
    print(f'geoip_db = {path}  (格式: {fmt})')
    _probe_geoip(path)
    print('若同时配了 geosite, geoip 规则会优先按域名判 (免 DNS): '
          'webtool proxy geosite <geosite.dat>')
    return 0


def _geosite(args, cfg):
    """geosite <geosite.dat> — 按域名分类的库, 判规则时不需要 DNS"""
    from webtool.net import geodata as _gd
    val = args.value
    if not val:
        print('usage: webtool proxy geosite <geosite.dat>')
        return 2
    path = os.path.expanduser(val)
    if not os.path.isfile(path):
        print(f'文件不存在: {path}', file=sys.stderr)
        return 2
    fmt = _gd.detect_format(path)
    if fmt != 'geosite':
        print(f'不是 geosite 库 (认出来是 {fmt or "未知"}): {path}',
              file=sys.stderr)
        return 2
    cats = _gd.categories(path)
    cfg['geosite_db'] = path
    save_config(cfg)
    print(f'geosite_db = {path}')
    # 不同库的分类名大小写不一 (v2ray-rules-dat 用 CN/GOOGLE, v2fly 用 cn),
    # 查询本身大小写不敏感, 这里按小写索引再展示, 免得误报"没有"
    low = {c.lower() for c in cats}
    print(f'共 {len(cats)} 个分类; 常用: '
          + (', '.join(c for c in ('cn', 'google', 'github', 'category-ads')
                        if c in low) or '这几个分类库里没有'))
    _probe_geosite(path)
    print('用法: 规则里 {"geosite":["cn"]} —— 纯域名判定, 不解析 IP, '
          '不会被 CDN 就近解析带偏')
    return 0


def _probe_geoip(path):
    from webtool.net import geodata as _gd
    probes = ['8.8.8.8', '1.1.1.1', '114.114.114.114', '223.5.5.5']
    hits = [(ip, _gd.country_of_ip(ip, path)) for ip in probes]
    ok = [(ip, cc) for ip, cc in hits if cc]
    if ok:
        print('自检(IP→国家): ' + ', '.join(f'{ip}→{cc}' for ip, cc in ok))
        print(f'  {len(ok)}/{len(probes)} 个探针命中, 库可用')
    else:
        print('自检: 探针都没命中。可能是精简/测试库 (只覆盖少数网段), '
              '或类型不对 (要国家库不要 ASN 库)')


def _probe_geosite(path):
    from webtool.net import geodata as _gd
    for host, cat in [('www.baidu.com', 'cn'), ('www.google.com', 'google')]:
        try:
            hit = _gd.domain_in_category(host, cat, path)
        except Exception:
            hit = None
        print(f'  自检: {host} ∈ {cat} → {hit}')


def _asn(args, cfg):
    from webtool.net import rules as R
    val = args.value
    if not val:
        print('usage: webtool proxy asn <GeoLite2-ASN.mmdb>')
        return 2
    path = os.path.expanduser(val)
    if not os.path.isfile(path):
        print(f'文件不存在: {path}', file=sys.stderr)
        return 2
    if R._reader(path) is None:
        print(f'无法打开 mmdb: {path} (pip install maxminddb)',
              file=sys.stderr)
        return 2
    probe = R.geoip_asn('8.8.8.8', path)
    cfg['asn_db'] = path
    save_config(cfg)
    print(f'asn_db = {path}\n自检: 8.8.8.8 → AS{probe or "查不到"}')
    return 0
