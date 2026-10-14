"""geodata / 路由规则测试

样本用 tests/make_geodata_fixtures.py 现造 (几 KB 的 protobuf), 而不是把
十几 MB 的真实 geoip.dat 提交进仓库。真库 (Loyalsoldier/v2ray-rules-dat)
在联网环境下可以用 GEODATA_REAL_GEOIP / GEODATA_REAL_GEOSITE 指过去做对照。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
os.environ.setdefault('WEBTOOL_DIR', tempfile.mkdtemp(prefix='wt-geodata-'))

from make_geodata_fixtures import make_geoip_dat, make_geosite_dat  # noqa: E402
from webtool.net import geodata as G                            # noqa: E402
from webtool.net import rules as R                               # noqa: E402

fails = []


def check(cond, msg):
    print(('PASS ' if cond else 'FAIL ') + msg)
    if not cond:
        fails.append(msg)


TMP = tempfile.mkdtemp(prefix='wt-geo-data-')
GEOIP = os.path.join(TMP, 'geoip.dat')
GEOSITE = os.path.join(TMP, 'geosite.dat')
with open(GEOIP, 'wb') as f:
    f.write(make_geoip_dat())
with open(GEOSITE, 'wb') as f:
    f.write(make_geosite_dat())

print('\n=== 1. 格式识别 ===')
check(G.detect_format(GEOIP) == 'geoip', f'geoip.dat → geoip (实际 {G.detect_format(GEOIP)})')
check(G.detect_format(GEOSITE) == 'geosite', f'geosite.dat → geosite (实际 {G.detect_format(GEOSITE)})')
check(G.detect_format('/nope/x.dat') is None, '不存在的文件 → None')
check(G.detect_format('') is None, '空路径 → None')

print('\n=== 2. IP → 国家 (geoip.dat) ===')
check(G.country_of_ip('1.2.3.4', GEOIP) == 'CN',
      f'1.2.3.4 → CN (实际 {G.country_of_ip("1.2.3.4", GEOIP)})')
check(G.country_of_ip('8.8.8.8', GEOIP) == 'US',
      f'8.8.8.8 → US (实际 {G.country_of_ip("8.8.8.8", GEOIP)})')
check(G.country_of_ip('2001:db8::1', GEOIP) is None, 'IPv6 不在库 → None')
check(G.country_of_ip('not-an-ip', GEOIP) is None, '非法 IP → None (不抛异常)')
check(G.country_of_ip('1.2.3.4', '/nope.dat') is None, '库文件缺失 → None')

print('\n=== 3. 域名 → 分类 (geosite.dat, 无需 DNS) ===')
for host, cat, want in [('www.baidu.com', 'cn', True),
                        ('example.cn', 'cn', True),
                        ('api.github.com', 'github', True),
                        ('sub.deep.google.com', 'google', True),
                        ('example.com', 'cn', False),
                        ('www.baidu.com', 'github', False)]:
    got = G.domain_in_category(host, cat, GEOSITE)
    check(got == want, f'{host} ∈ {cat} → {got} (期望 {want})')
check(G.domain_in_category('WWW.BAIDU.COM', 'CN', GEOSITE) is True,
      '大小写不敏感 (WWW.BAIDU.COM ∈ CN)')
check(G.domain_in_category('', 'cn', GEOSITE) is False, '空域名 → False')
check(G.domain_in_category('a.cn', 'no-such-category', GEOSITE) is False,
      '不存在的分类 → False (不抛)')

print('\n=== 4. 分类名大小写不敏感 ===')
cats = G.categories(GEOSITE)
check(set(cats) == {'CN', 'GOOGLE', 'GITHUB', 'EXACTCAT', 'CATEGORY-ADS'},
      f'分类列表 = {sorted(cats)}')
check(G.domain_in_category('www.baidu.com', 'CN', GEOSITE) is True, '大写分类名可用')
check(G.domain_in_category('www.baidu.com', 'cn', GEOSITE) is True, '小写分类名可用')

print('\n=== 5. 精确域名 vs 后缀, 不能混淆 ===')
# exact:example.com 不应匹配 www.example.com
check(G.domain_in_category('www.example.com', 'exactcat', GEOSITE) is False,
      'exact 条目不匹配子域')
check(G.domain_in_category('example.com', 'exactcat', GEOSITE) is True,
      'exact 条目匹配本域')
# domain 后缀条目语义 = 本域 + 全部子域, 裸域名本身必须命中。
# (v2ray 里 domain 类型条目 'example.cn' 覆盖 example.cn 和 *.example.cn;
#  如果实现里剥标签时漏掉第一级, 裸域名会漏判 —— 这条就是那个回归锁)
check(G.domain_in_category('example.cn', 'cn', GEOSITE) is True,
      'domain 条目匹配裸域名本身')
check(G.domain_in_category('a.b.example.cn', 'cn', GEOSITE) is True,
      'domain 条目匹配多级子域')
check(G.domain_in_category('notexample.cn', 'cn', GEOSITE) is False,
      'domain 条目不做字符串包含匹配 (避免 example.cn 误命中 notexample.cn)')
check(G.domain_in_category('example.com.evil.net', 'cn', GEOSITE) is False,
      '后缀不在尾部则不命中')

print('\n=== 6. geosite 免 DNS: 不该触发解析 ===')
seen = []
_orig = R.resolve_ip
R.resolve_ip = lambda h: (seen.append(h), '9.9.9.9')[1]
try:
    r = R.Router({'default': 'direct',
                  'rules': [{'match': {'geosite': ['cn']}, 'action': 'direct'}]},
                 geosite_db=GEOSITE)
    check(r.explain('https://www.baidu.com/x')['rule_index'] == 0,
          'geosite 规则命中')
    check(seen == [], f'全程零 DNS 解析 (实际解析了 {seen})')
finally:
    R.resolve_ip = _orig

print('\n=== 7. geoip 规则优先用 geosite 判 (免 DNS) ===')
r = R.Router({'default': 'direct',
              'rules': [{'match': {'geoip': ['CN']}, 'action': 'direct'}]},
             geosite_db=GEOSITE)
e = r.explain('https://www.baidu.com/x')
check(e['rule_index'] == 0, f'geoip 规则由 geosite 兜住 (规则{e["rule_index"]})')

print('\n=== 8. 缺库 = 不匹配 (fail-closed, 不能"跳过当通过") ===')
r2 = R.Router({'default': 'proxy',
               'rules': [{'match': {'geosite': ['cn']}, 'action': 'direct'}]},
              geosite_db=None)
e2 = r2.explain('https://www.baidu.com/x')
check(e2['rule_index'] is None and e2['action'] == 'proxy',
      'geosite 缺库 → 落到默认, 而不是让 direct 规则对所有流量生效')

print('\n=== 9. 规则表里的 geosite 条件 ===')
r3 = R.Router({'default': 'direct',
               'rules': [{'match': {'geosite': ['google']}, 'action': 'block'}]},
              geosite_db=GEOSITE)
try:
    r3.proxy_for('https://www.google.com/x')
    check(False, 'block 动作应抛 RuleError')
except R.RuleError:
    check(True, 'geosite 命中 → block 抛 RuleError')
check(r3.proxy_for('https://www.baidu.com/x') is None, '非命中 → 直连')

print('\n=== 10. 真库对照 (可选, 需联网先下载) ===')
for env, fn in (('GEODATA_REAL_GEOIP', lambda p: G.country_of_ip('1.2.3.4', p)),
                ('GEODATA_REAL_GEOSITE',
                 lambda p: G.domain_in_category('www.baidu.com', 'cn', p))):
    p = os.environ.get(env)
    if p and os.path.isfile(p):
        try:
            check(fn(p) is not None, f'{env} 真库可用 → {fn(p)!r}')
        except Exception as e:
            check(False, f'{env} 真库出错: {e}')
    else:
        print(f'SKIP {env} (未设置)')

print()
print(f'{len(fails)} FAILED')
sys.exit(1 if fails else 0)