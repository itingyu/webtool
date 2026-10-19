# -*- coding: utf-8 -*-
"""站点证书要按站点配到规则里 —— 不再"放进 extra/ 就全局受信"

覆盖四件事:
1. `tls` kind 注册在册, 字段拼错会被 Router 报出来 (静默死配置最要命)
2. cert_sites: 从证书自己读"它覆盖哪些域名" (SAN 为主, CN 兜底)
3. cert_rules: 一份证书 → 一条按站点的 kind:tls 规则 (ca 用相对路径)
4. policy 决策: 规则 ca / 规则 verify:off / 参数优先 / 没规则就拒

为什么这些断言值得锁: "放进 extra/ 就生效"改成"要有规则点名"之后, 失败的
表现不再是报错, 而是**静默回到系统信任根** —— 用户看到的是"这站又报证书
错误了", 与"压根没放证书"长得一模一样。

跑法: python3 tests/test_tls_rules.py
"""
import json
import os
import shutil
import ssl
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

TMP = tempfile.mkdtemp(prefix='webtool-tlsrules-')
os.environ['WEBTOOL_DIR'] = TMP
# 这些断言验的是**严格校验下**的 CA 分层与规则优先级 (规则 ca / 别域名照旧基础
# CA / verify: off)。校验默认已改成 off (没配就不校验), 不显式打开的话所有域名
# 都直接返回 False, 这几条就无从验起。
with open(os.path.join(TMP, 'config.json'), 'w') as _f:
    json.dump({'ssl_verify': 'on'}, _f)
FIX = os.path.join(os.path.dirname(__file__), 'fixtures', 'tls')

PASS = FAIL = 0


def check(cond, msg, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print('PASS', msg)
    else:
        FAIL += 1
        print('FAIL', msg, ' ', detail)


from webtool.net import rules as R                              # noqa: E402
from webtool.net import tls                                     # noqa: E402

RULES_PATH = os.path.join(TMP, 'rules.json')
EXTRA = os.path.join(TMP, 'certs', 'extra')
os.makedirs(EXTRA, exist_ok=True)


def write_rules(rules):
    with open(RULES_PATH, 'w') as f:
        json.dump({'default': 'direct', 'proxies': {}, 'rules': rules}, f)
    R._router_cache = (None, None)          # 规则文件改了, 重建 Router
    tls._CA_CACHE = (None, None)


def put_cert(src, name='site.pem'):
    dst = os.path.join(EXTRA, name)
    shutil.copyfile(os.path.join(FIX, src), dst)
    return dst


write_rules([])

# ── 1. kind 注册与字段校验 ──────────────────────────────────────────────
sp = R.spec_for('tls')
check(sp is not None and 'ca' in sp.fields and 'verify' in sp.fields,
      'tls kind 在册, 字段含 ca / verify', str(sp))
check('tls' in R.specs(), 'kinds() 目录里枚举得到 tls', str(sorted(R.specs())))

r = R.Router({'default': 'direct', 'rules': [
    {'kind': 'tls', 'match': {'domain': ['a.cn']}, 'verfiy': 'off'}]})
check(any('认不出的字段' in w and 'verfiy' in w for w in r.warnings),
      '规则字段拼错 (verfiy) 会被报出来, 不静默', str(r.warnings))
r2 = R.Router({'default': 'direct', 'rules': [
    {'kind': 'tls', 'match': {'domain': ['a.cn']}, 'verify': 'off',
     'ca': 'extra/x.pem'}]})
check(not r2.warnings, '字段写对了就没有告警', str(r2.warnings))

# ── 2. 证书自己说它是哪些站点的 ─────────────────────────────────────────
san = put_cert('site-san.pem', 'zce.pem')
cn = put_cert('site-cn-only.pem', 'only.pem')
check(tls.cert_sites(san) == ['zce.com.cn', '*.zce.com.cn', 'www.zce.com.cn'],
      'SAN 里的域名全读出来 (顺序即证书里的顺序)', str(tls.cert_sites(san)))
check(tls.cert_sites(cn) == ['only.example.cn'],
      '没有 SAN 时用 CN 兜底 (只有看着像域名的才收)', str(tls.cert_sites(cn)))
check(tls.cert_sites('/nope/none.pem') == [],
      '读不出的证书返回 [], 不抛异常', '')

infos = {c['name']: c for c in tls.site_certs()}
check(set(infos) == {'zce.pem', 'only.pem'}, 'site_certs 收全 extra/ 里的证书',
      str(sorted(infos)))
check(infos['zce.pem']['self_signed'] is True, '自签认得出 (subject == issuer)',
      str(infos['zce.pem']))
check(infos['only.pem']['not_after'],
      '带上有效期 (排查"这站为什么还报错"的第一眼)', str(infos['only.pem']))

# ── 3. 证书 → 规则 (ca 用相对路径, 换 home 也认) ────────────────────────
gen = tls.cert_rules()
check(len(gen) == 2 and all(x['kind'] == 'tls' for x in gen),
      '一份证书一条 kind:tls 规则', json.dumps(gen, ensure_ascii=False))
zce_rule = next(x for x in gen if 'zce.com.cn' in x['match']['domain'])
check(zce_rule['ca'] == 'extra/zce.pem',
      'ca 写相对 ~/.webtool/certs/ 的路径, 不写死绝对路径', str(zce_rule))
check(tls.resolve_cert_path('extra/zce.pem') == san,
      '相对路径解析得到真实文件', tls.resolve_cert_path('extra/zce.pem'))
check(tls.resolve_cert_path('/nope.pem') == '', '不存在的路径解析成空串', '')
check(tls.resolve_cert_path('') == '', '空路径解析成空串', '')

# tidy 不许把 kind 条目当"与默认同动作"删掉
spec_tidy, _report = R.tidy_spec(
    {'default': 'direct', 'rules': [dict(zce_rule)]})
check(len(spec_tidy.get('rules') or []) == 1,
      'tidy 不动 kind 条目 (漏掉就会把证书/限速/重试配置整批删光)',
      json.dumps(spec_tidy, ensure_ascii=False))

# ── 4. policy: 规则说了算 ───────────────────────────────────────────────
URL = 'https://www.zce.com.cn/api'
base_ca = tls._system_ca()
check(base_ca is not None, '环境有基础 CA 可用 (自带兜底)', str(base_ca))

# 光有证书、没有规则 → 照旧用系统信任根 (证书不生效, 必须看得见)
write_rules([])
check(tls.policy(URL) == base_ca,
      'extra/ 里有证书但没规则 → 仍走基础 CA (不再全局受信)',
      str(tls.policy(URL)))
c0 = tls._cert_info(san)
ok0, why0 = tls.cert_status(c0)
check(ok0 is False and 'tls 规则' in why0,
      'cert_status 明说"还没配进规则表"', why0)
check('cert sync' in (tls.describe().get('warning') or ''),
      'describe() 里带 warning, 指向 cert sync (不然现象只是"还是报错")',
      str(tls.describe().get('warning'))[:120])

# 配上规则 → 信任根 = 基础 CA + 该站证书
write_rules([{'kind': 'tls', 'match': {'domain': ['zce.com.cn', '*.zce.com.cn']},
              'ca': 'extra/zce.pem'}])
p = tls.policy(URL)
check(p not in (False, base_ca) and '/tls/' in p.replace(os.sep, '/'),
      '规则点名 → 用"基础 CA + 该站证书"的合并文件', str(p))
blob = open(p, 'rb').read()
check(blob.count(b'BEGIN CERTIFICATE')
      == open(base_ca, 'rb').read().count(b'BEGIN CERTIFICATE') + 1,
      '合并文件 = 基础 CA 里的全部 + 该站证书 1 份',
      str(blob.count(b'BEGIN CERTIFICATE')))
ssl.create_default_context(cafile=p)
check(True, '合并出来的文件是合法 CA 文件')
check(tls.policy('https://www.eastmoney.com/') == base_ca,
      '规则只对它点名的域名生效, 别的域名照旧基础 CA',
      str(tls.policy('https://www.eastmoney.com/')))
check(tls.cert_status(c0)[0] is True
      and 'zce.pem' not in (tls.describe().get('warning') or '')
      and 'only.pem' in (tls.describe().get('warning') or ''),
      '配上规则的证书转正; 没配的 (only.pem) 仍然被点名', str(tls.describe().get('warning')))

# 规则 verify: off → 该站不校验 (比 verify_hosts 强在能带端口一起限)
write_rules([{'kind': 'tls', 'match': {'domain': ['zce.com.cn']}, 'verify': 'off'}])
check(tls.policy(URL) is False, '规则 verify: off → 该站不校验', str(tls.policy(URL)))
check(tls.policy('https://other.cn/') not in (False,), '别的域名不受影响', '')
write_rules([{'kind': 'tls', 'match': {'domain': ['zce.com.cn'], 'port': [8443]},
              'verify': 'off'}])
check(tls.policy('https://www.zce.com.cn:8443/x') is False
      and tls.policy('https://www.zce.com.cn/x') != False,  # noqa: E712
      '规则能连端口一起限 (verify_hosts 做不到)', '')

# 规则写坏了必须炸出来, 不能静默沿用系统 CA
write_rules([{'kind': 'tls', 'match': {'domain': ['zce.com.cn']},
              'ca': 'extra/nope.pem'}])
try:
    tls.policy(URL)
    bad = ''
except tls.TlsConfigError as e:
    bad = str(e)
check('不存在' in bad and 'extra/nope.pem' in bad,
      '规则 ca 指向不存在的文件 → 硬失败且指名道姓', bad[:80])
write_rules([{'kind': 'tls', 'match': {'domain': ['zce.com.cn']}, 'verify': 'nope'}])
try:
    tls.policy(URL)
    bad2 = ''
except tls.TlsConfigError as e:
    bad2 = str(e)
check('认不出' in bad2, '规则 verify 值写错 → 硬失败 (静默当没表态最坏)', bad2[:80])

# 参数优先于规则 (老代码的定点豁免不能被规则改掉)
write_rules([{'kind': 'tls', 'match': {'domain': ['zce.com.cn']},
              'ca': 'extra/zce.pem'}])
check(tls.policy(URL, verify=False) is False, 'verify=False 参数压过规则', '')
check(tls.policy(URL, verify=base_ca) == base_ca,
      'verify=<CA 路径> 参数原样照用 (绕开规则)', str(tls.policy(URL, verify=base_ca)))

# verify_hosts 仍然是独立的一条路 (老配置照常生效)
from webtool.net.proxy import store as _store                    # noqa: E402
write_rules([])
os.makedirs(os.path.dirname(_store.CONFIG_PATH), exist_ok=True)
with open(_store.CONFIG_PATH, 'w') as f:
    json.dump({'ssl_verify': 'on', 'verify_hosts': ['zce.com.cn']}, f)
tls._CACHE = (None, None)
check(tls.policy(URL) is False, 'verify_hosts 名单照旧对老配置生效', str(tls.policy(URL)))
write_rules([{'kind': 'tls', 'match': {'domain': ['zce.com.cn']},
              'ca': 'extra/zce.pem'}])
check(tls.policy(URL) not in (False, base_ca),
      '规则比 verify_hosts 具体: 有 ca 规则时按规则校验, 而不是关校验',
      str(tls.policy(URL)))

shutil.rmtree(TMP, ignore_errors=True)
print('\n%d PASS, %d FAIL' % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
