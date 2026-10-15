"""代理路由规则测试 (tests/test_rules.py)

覆盖 Router 的判定语义, 重点在几个容易写错、且错了不报错的地方:
  - 规则一律**文件顺序** first-match-wins (曾经有 priority 字段, 已废弃)
  - match 内 AND、条件内 OR
  - 默认动作: 配了命名代理 default 却没写 default 动作时不能默默直连
  - 判不了的库 (geoip/asn/geosite 没配) → 不匹配 + 警告, 而不是"跳过当通过"
  - 纯域名规则不该触发 DNS
  - 出口脱敏: explain 不该把密码打出来
  - 规则文件坏掉 → 退回直连 + 警告 (不是静默用全局代理)
"""
import json
import os
import sys
import tempfile

WEBTOOL_DIR = tempfile.mkdtemp(prefix='wt-rules-')
os.environ['WEBTOOL_DIR'] = WEBTOOL_DIR
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.dirname(__file__))

from webtool.net import rules as R            # noqa: E402
from make_geodata_fixtures import make_geosite_dat   # noqa: E402

fails = []

def check(cond, msg):
    print(('PASS ' if cond else 'FAIL ') + msg)
    if not cond:
        fails.append(msg)

GEOSITE = os.path.join(tempfile.mkdtemp(prefix='wt-rules-geo-'), 'geosite.dat')
with open(GEOSITE, 'wb') as f:
    f.write(make_geosite_dat())

P1 = 'http://p:1'


def spec_with_default(rules, default='direct'):
    """带命名代理 default 的规则表 (裸 action=proxy 即指它)

    default 动作默认给 'direct': 这样"没命中"与"命中走代理"在断言里分得清。
    """
    return {'default': default, 'proxies': {'default': P1}, 'rules': rules}


print('\n=== 1. 命中顺序 = 文件顺序 (first-match-wins) ===')
# 曾经有 priority 字段 (block > direct > proxy), 结果"后面的窄规则能压过前面
# 的宽规则"成了隐藏规则, 排障只能靠猜。现在只有一种策略: 谁在前谁生效。
_cn = {'cn': {'url': 'http://cn.proxy:8080'}}
r = R.Router({'default': 'direct', 'proxies': _cn, 'rules': [
    {'match': {'domain': ['baidu.com']}, 'action': 'proxy:cn'},
    {'match': {'domain': ['baidu.com']}, 'action': 'block'},
]})
check(r.proxy_for('https://www.baidu.com/x') == 'http://cn.proxy:8080',
      '先写的 proxy 生效, 后面的 block 不越级 (文件顺序)')

r = R.Router({'default': 'direct', 'proxies': _cn, 'rules': [
    {'match': {'domain': ['baidu.com']}, 'action': 'block'},
    {'match': {'domain': ['baidu.com']}, 'action': 'proxy:cn'},
]})
try:
    r.proxy_for('https://www.baidu.com/x')
    check(False, 'block 写在前头才拦得住')
except R.RuleError:
    check(True, 'block 写在前头: 命中即断 (不再有"deny 优先"的隐藏规则)')

r = R.Router({'default': 'direct', 'proxies': _cn, 'rules': [
    {'match': {'domain': ['baidu.com']}, 'action': 'proxy:cn'},
    {'match': {'domain': ['baidu.com']}, 'action': 'direct'},
]})
check(r.proxy_for('https://www.baidu.com/x') == 'http://cn.proxy:8080',
      '后面的 direct 压不过前面的 proxy (旧 priority=direct 行为已删)')
check(r.rule('https://www.baidu.com/x')[2] == 0, '命中序号指向生效的那条')
check([h[0] for h in r.matched('https://www.baidu.com/x')] == [0, 1],
      'matched 把"匹配了但没生效"的也列出来 (排障要看得出被谁压掉)')
_ex = r.explain('https://www.baidu.com/x')
check(_ex['rule_index'] == 0 and _ex.get('note') and '规则[1]' in _ex['note'],
      f'explain 说明哪条被压掉 (实际 {_ex.get("note")})')

r = R.Router({'default': 'direct', 'proxies': _cn, 'priority': 'order',
              'rules': [{'match': {'domain': ['baidu.com']}, 'action': 'proxy:cn'}]})
check(any('priority' in w and '废弃' in w for w in r.warnings),
      f"写 'priority' 键要警告已废弃 (实际 {r.warnings})")

print('\n=== 2. match 内 AND ===')
r = R.Router(spec_with_default([
    {'match': {'domain': ['baidu.com'], 'scheme': ['https']}, 'action': 'proxy'},
]))
check(r.proxy_for('https://www.baidu.com/') == P1, '两条件都满足 → 命中')
check(r.proxy_for('http://www.baidu.com/') is None,
      '只满足 domain → 不命中 (AND 语义)')

print('\n=== 3. 条件内 OR ===')
r = R.Router(spec_with_default([
    {'match': {'domain': ['a.com', 'b.com']}, 'action': 'proxy'},
]))
check(r.proxy_for('https://b.com/') == P1, '多值 OR: 第二个也命中')

print('\n=== 4. 默认动作: 配了默认代理就不能默默直连 ===')
r = R.Router({'proxies': {'default': P1},
              'rules': [{'match': {'domain': ['x.com']}, 'action': 'direct'}]})
check(r.default_action == 'proxy', '未写 default + 有命名代理 default → 默认走代理')
check(r.proxy_for('https://nomatch.com/') == P1,
      '未命中的请求继承默认代理 (而不是静默直连)')
check(any('未写 default' in w for w in r.warnings), '这种推断必须留下警告')
r = R.Router({'rules': []})
check(r.default_action == 'direct', '未写 default + 无代理 → 默认直连')
check(any('直连' in w for w in r.warnings), '直连兜底也要说明 (排查"为什么没走代理")')

print('\n=== 5. block 动作 ===')
r = R.Router({'default': 'direct', 'rules': [
    {'match': {'domain': ['blocked.com']}, 'action': 'block'}]})
try:
    r.proxy_for('https://blocked.com/')
    check(False, 'block 应当抛 RuleError')
except R.RuleError:
    check(True, 'block → RuleError')

print('\n=== 6. 非法配置收集成警告, 不抛 ===')
r = R.Router({'default': 'direct', 'rules': [
    'not-a-dict',
    {'action': 'direct'},                       # 缺 match
    {'match': {'domain': ['ok.com']}, 'action': 'fly'},   # 非法动作
]})
check(len(r.warnings) == 3, f'三条问题各出一条警告 (实际 {r.warnings})')
check(r.proxy_for('https://ok.com/') is None, '合法规则照常生效')

print('\n=== 7. 未知动作在 resolve_action 就该拦 ===')
try:
    R.resolve_action('teleport')
    check(False, '未知动作应当抛 RuleError')
except R.RuleError as e:
    check('direct' in str(e) and 'block' in str(e), '错误信息列出合法动作')
check(R.resolve_action('proxy:tokyo') == ('proxy', 'tokyo'), 'proxy:名字 解析正确')
check(R.resolve_action('proxy') == ('proxy', 'default'),
      "裸 'proxy' 归一成 proxy:default (只有一种写法)")
check(R.resolve_action(None) == ('direct', None), '缺省动作 = direct')

print('\n=== 8. 引用未定义的命名代理要报错 ===')
r = R.Router({'default': 'direct', 'rules': [
    {'match': {'domain': ['x.com']}, 'action': 'proxy:ghost'}]})
try:
    r.proxy_for('https://x.com/')
    check(False, '未定义的命名代理应当报错')
except R.RuleError as e:
    check('ghost' in str(e), '错误信息点名是哪个代理')

print('\n=== 9. geoip/asn/geosite 缺库 = 不匹配, 且给出警告 ===')
for cond, key in (({'geoip': ['CN']}, 'geoip'),
                  ({'asn': [15169]}, 'asn'),
                  ({'geosite': ['cn']}, 'geosite')):
    r = R.Router({'default': 'direct', 'rules': [{'match': cond, 'action': 'block'}]})
    out = r.proxy_for('https://x.com/')
    joined = ' '.join(r.warnings)
    check(out is None, f'{key} 缺库 → 不匹配 (而非放行)')
    check(key in joined, f'{key} 缺库有明确提示 (实际: {joined[:60]})')

print('\n=== 10. 纯域名规则零 DNS ===')
seen = []
_orig = R.resolve_ip
R.resolve_ip = lambda h, timeout=3.0: (seen.append(h), '9.9.9.9')[1]
try:
    r = R.Router({'default': 'direct', 'rules': [
        {'match': {'domain': ['*.cn']}, 'action': 'block'},
        {'match': {'domain': ['x.com'], 'scheme': ['https']}, 'action': 'block'},
    ]})
    hit = 0
    for u in ('https://www.example.cn/a', 'https://x.com/a',
              'https://nomatch.com/a'):
        try:
            r.proxy_for(u)
        except R.RuleError:
            hit += 1
    check(hit == 2, f'两条规则各自命中 (实际命中 {hit}/2)')
    check(seen == [], f'domain/scheme 规则不触发 DNS (实际 {seen})')
finally:
    R.resolve_ip = _orig

print('\n=== 11. 端口 / 区间 / scheme ===')
r = R.Router(spec_with_default([
    {'match': {'port': [8080, '9000-9100']}, 'action': 'proxy'}]))
check(r.proxy_for('https://a.com:8080/') == P1, '端口精确匹配')
check(r.proxy_for('https://a.com:9050/') == P1, '端口区间匹配')
check(r.proxy_for('https://a.com:8081/') is None, '区间外不命中')
check(r.proxy_for('https://a.com/') is None, '无端口不命中端口规则')

print('\n=== 12. *.cn 与裸后缀 ===')
# 默认走代理, 规则把 .cn 拨去直连 —— 这样"None"就只可能是规则命中
r = R.Router(spec_with_default([
    {'match': {'domain': ['*.cn']}, 'action': 'direct'}], default='proxy'))
check(r.rule('https://a.cn/')[2] == 0, '*.cn 匹配 a.cn (命中该条)')
check(r.proxy_for('https://x.y.cn/') is None, '*.cn 匹配多级子域')
check(r.proxy_for('https://cn/') is None, '*.cn 匹配裸域 cn')
check(r.rule('https://a.cn.com/')[2] is None, '*.cn 不误伤 a.cn.com (没命中)')

print('\n=== 13. explain 出口脱敏 ===')
r = R.Router({'default': 'direct',
              'proxies': {'pw': {'url': 'http://user:s3cret@127.0.0.1:8080'}},
              'rules': [
                  {'match': {'domain': ['x.com']}, 'action': 'proxy:pw'}]})
e = r.explain('https://x.com/')
check('s3cret' not in json.dumps(e), f'explain 不含明文密码 (实际 {e["resolved_proxy"]})')
check(e['action'] == 'proxy' and e['proxy_name'] == 'pw', 'explain 报告动作与代理名')
check(e['rule_index'] == 0 and e['rule'] is not None, 'explain 报告命中规则')

print('\n=== 14. 坏规则文件退回直连 + 警告, 不退回"全局代理" ===')
_bf = os.path.join(WEBTOOL_DIR, 'rules.json')
with open(_bf, 'w', encoding='utf-8') as f:
    f.write('{ 这不是 JSON')
_broken = R.load_router({'rules_file': _bf})
check(_broken.proxy_for('https://x.com/') is None,
      '规则文件坏掉 → 未命中一律直连 (不能退成"用全局代理": 该直连的会悄悄挂掉)')
check(any('规则文件' in w for w in _broken.warnings),
      f'坏掉的原因挂在 warnings 上 (实际 {_broken.warnings})')
check(_broken.explain('https://x.com/')['action'] == 'direct',
      '坏规则时 explain 仍可用')

print('\n=== 15. 域名规则不该被 URL 里的端口/凭据干扰 ===')
r = R.Router(spec_with_default([
    {'match': {'domain': ['baidu.com']}, 'action': 'direct'}]))
check(r.proxy_for('https://www.baidu.com:8443/x') is None, '带端口仍匹配域名')
check(r.proxy_for('https://user:pw@www.baidu.com/x') is None, 'URL 内凭据不影响 host 提取')
check(r.proxy_for('not a url') is not None or True, '非法 URL 不崩')

print('\n=== 16. 命名代理的密码进保险库, rules.json 不留明文 ===')
# 命名代理写的是 rules.json —— 人工编辑的文件, 密码留在里面就是明文落盘。
# 迁移后 rules.json 只留 user@host, 出网时 resolve_auth 补回。
from webtool.net import rules as RR          # noqa: E402
from webtool.core import secrets_store as SS  # noqa: E402

rules_file = os.path.join(WEBTOOL_DIR, 'rules.json')
spec = {'default': 'direct',
        'proxies': {'tokyo': {'url': 'http://u:PLAIN_PW@10.0.0.1:8080'},
                    'osaka': {'url': 'socks5://10.0.0.2:1080'}},
        'rules': [{'match': {'domain': ['x.com']}, 'action': 'proxy:tokyo'}]}
with open(rules_file, 'w', encoding='utf-8') as f:
    json.dump(spec, f)
check('PLAIN_PW' in open(rules_file, encoding='utf-8').read(), '迁移前 rules.json 是明文')

if SS.have_crypto():
    out, n = RR.migrate_plaintext_proxies(spec, rules_file)
    check(n == 1, f'迁移了 1 条 (实际 {n})')
    check(out['proxies']['tokyo']['url'] == 'http://u@10.0.0.1:8080',
          f'URL 只留用户名 (实际 {out["proxies"]["tokyo"]["url"]})')
    check(out['proxies']['osaka']['url'] == 'socks5://10.0.0.2:1080',
          '无密码的代理原样保留')
    check('PLAIN_PW' not in open(rules_file, encoding='utf-8').read(),
          'rules.json 已无明文')
    check(SS.decrypt(SS._load_store()['u@10.0.0.1:8080']) == 'PLAIN_PW',
          '密码已进保险库 (键带主机, 两台代理同用户名不互撞)')
    out2, n2 = RR.migrate_plaintext_proxies(out, rules_file)
    check(n2 == 0, f'重复迁移是幂等的 (实际 {n2})')

    rr = RR.Router(out)
    check(rr.proxy_for('https://x.com/a') == 'http://u@10.0.0.1:8080',
          'Router 返回脱敏形态 (user@host)')
    from webtool.core.secrets_store import resolve_auth
    check(resolve_auth(rr.proxy_for('https://x.com/a')) ==
          'http://u:PLAIN_PW@10.0.0.1:8080', '出网时能补回明文密码')
    check(rr.explain('https://x.com/a')['resolved_proxy'] ==
          'http://u@10.0.0.1:8080', 'explain 仍脱敏')
else:
    print('SKIP 未装 cryptography, 迁移用例跳过')

print('\n=== 17. 首次启动落地默认 rules.json ===')
from webtool.core import bootstrap as BOOT       # noqa: E402
from webtool.core.config_data import DATA_DIR    # noqa: E402

_seed_dst = os.path.join(WEBTOOL_DIR, 'rules.json')
if os.path.exists(_seed_dst):                     # 别的用例已写过就清掉
    os.remove(_seed_dst)
_made = BOOT.ensure_user_files()
check(os.path.exists(_seed_dst), '缺失时把包内 rules.json 落到用户目录')
check(os.path.join(WEBTOOL_DIR, 'rules.json') in _made, '返回值报出新建的文件')
check(open(_seed_dst, encoding='utf-8').read()
      == open(os.path.join(DATA_DIR, 'rules.json'), encoding='utf-8').read(),
      '落地内容 = 包内默认逐字节一致')
_again = BOOT.ensure_user_files()
check(_again == [], f'已有文件不重复补 (实际 {_again})')
with open(_seed_dst, 'w', encoding='utf-8') as _f:
    _f.write('{"rules": [{"match": {"domain": ["keep.me"]}, "action": "block"}]}')
BOOT.ensure_user_files()
check('keep.me' in open(_seed_dst, encoding='utf-8').read(),
      '用户改过的 rules.json 绝不被默认覆盖')

print()
print(f'{len(fails)} FAILED')
sys.exit(1 if fails else 0)
