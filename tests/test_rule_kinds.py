# -*- coding: utf-8 -*-
"""规则引擎 kind 条目与 DNS 层的边界单测 (纯本地, 不联网)

覆盖三件事:
  1. Router.params_for: kind 条目按环节生效, 与路由条目互不干扰
  2. net/dns.resolve_ip: IP 直通 / 负缓存 (解析失败只打一次)
  3. transport._rule_timeout: 显式 timeout 优先, 规则填空缺, 无命中走 15

跑法: python3 tests/test_rule_kinds.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

fails = []

def check(cond, msg):
    print(('PASS' if cond else 'FAIL') + ' ' + msg)
    if not cond:
        fails.append(msg)

# ── 1. params_for ────────────────────────────────────────────────
from webtool.net import rules as R

spec = {
    'default': 'direct',
    'rules': [
        # 路由条目 (无 kind): 不该被 params_for 认领
        {'match': {'domain': 'em.com'}, 'action': 'proxy:default'},
        # kind 条目: 不该参与路由
        {'kind': 'http', 'match': {'domain': 'xueqiu.com'},
         'timeout': 25, 'fingerprint': 'chrome131'},
        {'kind': 'http', 'match': {'domain_suffix': '.cn'}, 'timeout': 8},
        {'kind': 'retry', 'match': {'domain': 'sina.com.cn'},
         'retries': 5, 'backoff': 'exp'},
    ],
    'proxies': {'default': 'http://127.0.0.1:9'},
}
r = R.Router(spec)

p = r.params_for('http', 'https://xueqiu.com/S/SH600519')
check(p.get('timeout') == 25 and p.get('fingerprint') == 'chrome131', 'http 规则按域名命中')
check('kind' not in p and 'match' not in p, 'kind 不混入返回字段')

p2 = r.params_for('http', 'https://a.b.cn/x')
check(p2.get('timeout') == 8, 'domain_suffix 也能命中')

check(r.params_for('http', 'https://example.org/') == {}, '无命中返回空 dict')
check(r.params_for('breaker', 'https://xueqiu.com/') == {}, '未知 kind 返回空 dict')
check(r.params_for('retry', 'https://sina.com.cn/x').get('retries') == 5, 'retry kind 生效')

# kind 条目不参与路由: xueqiu 无路由条目 → default
check(r.proxy_for('https://xueqiu.com/') is None, 'kind 条目不影响路由')
# 路由条目不被 params_for 认领
check(r.params_for('http', 'https://em.com/') == {}, '路由条目不被 params_for 认领')

# first-match-wins: 同 kind 两条都命中, 取文件顺序靠前的
spec2 = {'default': 'direct', 'rules': [
    {'kind': 'http', 'match': {'domain': 'a.cn'}, 'timeout': 3},
    {'kind': 'http', 'match': {'domain': '*.cn'}, 'timeout': 9},
]}
check(R.Router(spec2).params_for('http', 'https://a.cn/').get('timeout') == 3,
      '同 kind first-match-wins')

# 路由行为回归: 原有规则仍按文件顺序生效
r3 = R.Router({'default': 'direct', 'proxies': {'default': 'http://127.0.0.1:9'},
               'rules': [{'match': {'domain': '*.cn'}, 'action': 'proxy:default'}]})
check(r3.proxy_for('https://baidu.cn/') == 'http://127.0.0.1:9', '路由条目照常生效')

# ── 2. DNS 层 ────────────────────────────────────────────────────
from webtool.net import dns as D

check(D.resolve_ip('10.0.0.1') == '10.0.0.1', 'IP 直通不查缓存')
check(D.resolve_ip('') is None and D.resolve_ip(None) is None, '空值返回 None')

D._CACHE.clear()
calls = []
_orig_gai = D.socket.getaddrinfo
def _fail_gai(host, *a, **kw):
    calls.append(host)
    raise D.socket.gaierror(1, 'mock 失败')
D.socket.getaddrinfo = _fail_gai
try:
    check(D.resolve_ip('nope.example') is None, '解析失败返回 None')
    D.resolve_ip('nope.example')
    check(len(calls) == 1, '负缓存: 失败只解析一次')
finally:
    D.socket.getaddrinfo = _orig_gai
    D._CACHE.clear()

def _ok_gai(host, *a, **kw):
    return [(None, None, 6, '', ('93.184.216.34', 0))]
D.socket.getaddrinfo = _ok_gai
try:
    check(D.resolve_ip('ok.example') == '93.184.216.34', '正常解析')
finally:
    D.socket.getaddrinfo = _orig_gai
    D._CACHE.clear()

# ── 3. _rule_timeout ─────────────────────────────────────────────
from webtool.net import transport as T

check(T._rule_timeout('https://xueqiu.com/', 5) == 5, '显式 timeout 优先')
check(T._rule_timeout('https://example.org/') == 15, '无规则走通用 15')

_orig_router = R.router
class _FakeRouter:
    def __init__(self, p):
        self.p = p
    def params_for(self, kind, url):
        return self.p if kind == 'http' else {}
R.router = lambda cfg=None: _FakeRouter({'timeout': 42})
try:
    check(T._rule_timeout('https://xueqiu.com/') == 42.0, '规则 timeout 填空缺')
finally:
    R.router = _orig_router

R.router = lambda cfg=None: (_ for _ in ()).throw(RuntimeError('boom'))
try:
    check(T._rule_timeout('https://xueqiu.com/') == 15, '规则查询炸了退通用默认')
finally:
    R.router = _orig_router

# ── 4. kind 注册制 + match 键校验 ────────────────────────────────
from webtool.net.rules import RuleSpec, register, specs

check({'http', 'retry', 'breaker'} <= set(specs()),
      '内置 kind 已注册 (http/retry/breaker)')

# 模拟新环节注册 (不改 rules 包)
register(RuleSpec('demo', fields=('x',), match_keys=('domain',)))
check('demo' in specs(), '新环节可注册')

_bad = R.Router({'default': 'direct', 'rules': [
    {'kind': 'http', 'match': {'domian': 'x.com'}, 'timeout': 9}]})
check(any('domian' in w for w in _bad.warnings), 'kind 条目 match 键拼错会告警')

_ok = R.Router({'default': 'direct', 'rules': [
    {'kind': 'http', 'match': {'domain': 'x.com'}, 'timeout': 9}]})
check(not any('无法识别' in w for w in _ok.warnings),
      'kind 条目 match 键正确不告警')

print()
if fails:
    print('FAILED: %d 项 -> %s' % (len(fails), ', '.join(fails)))
    sys.exit(1)
print('ALL PASS')
