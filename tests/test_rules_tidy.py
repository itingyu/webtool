# -*- coding: utf-8 -*-
"""规则表合并 (tidy_spec) 单测: 纯逻辑, 不联网

合并是"改分流总闸"的操作, 所以每条都盯两件事: 改对了、且没改多。
等价性用 Router 前后对同一批域名判线做回归。

跑法: python3 tests/test_rules_tidy.py
"""
import copy
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from webtool.net import rules as R

fails = []


def check(cond, msg, detail=''):
    if cond:
        print(f'PASS {msg}')
    else:
        print(f'FAIL {msg} {detail}')
        fails.append(msg)


def spec(rules, default='proxy:default', proxies=None):
    return {'rules': rules, 'default': default,
            'proxies': proxies or {'default': 'http://127.0.0.1:2080'}}


def doms(s, i=0):
    return (s['rules'][i].get('match') or {}).get('domain') or []


# 1. 同一规则内被宽条目覆盖的删掉, 宽条目自己留着
s, rep = R.tidy_spec(spec([{'match': {'domain': ['opencode.ai', '*.opencode.ai']},
                            'action': 'direct'}]))
check(doms(s) == ['opencode.ai'], '子域条目被裸后缀覆盖 → 删', doms(s))

# 2. 前一条规则已覆盖的条目 → 整条删 (first-match-wins 下永不生效)
s, rep = R.tidy_spec(spec([
    {'match': {'domain': ['*.cn']}, 'action': 'direct'},
    {'match': {'domain': ['*.sina.com.cn', '*.10jqka.com.cn']}, 'action': 'direct'}]))
check(len(s['rules']) == 1 and doms(s) == ['*.cn'], '被前面规则覆盖的死规则被删',
      s['rules'])
check(any('死规则' in x for x in rep), '死规则有报告', rep)

# 3. 同动作合并: 中间夹着异动作规则, 且不冲突 → 合
s, rep = R.tidy_spec(spec([
    {'match': {'domain': ['*.a.com']}, 'action': 'direct'},
    {'match': {'domain': ['google.com']}, 'action': 'proxy:default'},
    {'match': {'domain': ['*.b.com']}, 'action': 'direct'}]))
check(len(s['rules']) == 1
      and set(doms(s)) == {'*.a.com', '*.b.com'}, '跨异动作规则的安全合并', s['rules'])

# 4. 合并不安全: 两条 direct 单独都不覆盖中间那条, 但合并后的并集覆盖
#    (中间规则的多个域名分别落在两边) → 拒绝合并
s, rep = R.tidy_spec(spec([
    {'match': {'domain': ['a.com']}, 'action': 'direct'},
    {'match': {'domain': ['shop-a.a.com', 'shop-b.b.com']}, 'action': 'proxy:other'},
    {'match': {'domain': ['b.com']}, 'action': 'direct'}],
    proxies={'default': 'http://127.0.0.1:2080',
             'other': 'socks5h://127.0.0.1:1080'}))
check(len(s['rules']) == 3, '合并会吃掉中间规则时不合并', s['rules'])
check([r['action'] for r in s['rules']] ==
      ['direct', 'proxy:other', 'direct'], '两条 direct 都还在', s['rules'])

# 5. 与默认动作相同的规则 → 删, 并给提示
s, rep = R.tidy_spec(spec([{'match': {'domain': ['google.com']},
                            'action': 'proxy:default'}]))
check(s['rules'] == [], '与默认同结果的规则被删', s['rules'])
check(any('提示' in x and '默认' in x for x in rep),
      '给出"改默认动作会连带变"的提示', rep)

# 6. 混了 port/cidr 的规则一律不动
mixed = {'match': {'domain': ['x.com'], 'port': [8080]}, 'action': 'direct'}
s, rep = R.tidy_spec(spec([mixed, {'match': {'domain': ['x.com']}, 'action': 'direct'}]))
check(s['rules'][0] == mixed, '非纯域名规则原样保留', s['rules'])

# 7. 幂等: 合并过的表再合并不变
s1, _ = R.tidy_spec(spec([
    {'match': {'domain': ['*.cn', '*.sina.com.cn']}, 'action': 'direct'},
    {'match': {'domain': ['*.exa.ai']}, 'action': 'direct'},
    {'match': {'domain': ['google.com', '*.google.com']}, 'action': 'proxy:default'}]))
s2, rep2 = R.tidy_spec(s1)
check(s2 == s1 and not any(x.startswith('〔') for x in rep2), '幂等', rep2)

# 8. 语义等价回归: 合并前后逐域名判线必须一致
old = spec([
    {'match': {'domain': ['opencode.ai', '*.opencode.ai']}, 'action': 'direct'},
    {'match': {'domain': ['*.eastmoney.com', '*.sina.com.cn', '*.cn']}, 'action': 'direct'},
    {'match': {'domain': ['google.com', '*.google.com']}, 'action': 'proxy:default'},
    {'match': {'domain': ['*.baidu.com', '*.bing.com']}, 'action': 'direct'}])
new, _ = R.tidy_spec(old)
ro, rn = R.Router(old), R.Router(new)
probes = ['www.sina.com.cn', 'sina.cn', 'www.cs.com.cn', 'quote.eastmoney.com',
          'google.com', 'www.google.com', 'opencode.ai', 'www.opencode.ai',
          'api.exa.ai', 'www.bing.com', 'github.com', 'foo.cn', 'localhost']
diff = []
for h in probes:
    u = f'https://{h}/'
    a, b = ro.explain(u), rn.explain(u)
    if (a.get('action'), a.get('proxy')) != (b.get('action'), b.get('proxy')):
        diff.append((h, a.get('action'), b.get('action')))
check(not diff, '合并前后判线一致', diff)

# 9. 不修改传入的 dict (纯函数)
orig = spec([{'match': {'domain': ['*.cn', '*.sina.com.cn']}, 'action': 'direct'}])
snapshot = copy.deepcopy(orig)
R.tidy_spec(orig)
check(orig == snapshot, '不改传进来的 spec')

# 10. 种子规则: 空表才补 (从包内模板读), 已有规则一律不动
tpl = os.path.join(os.path.dirname(__file__), '..', 'src', 'webtool', 'data', 'rules.json')
s = spec([])
s['rules'] = []
n = R.seed_rules(s, tpl)
check(n >= 1 and len(s['rules']) == n, '空规则表从模板补种子', s)

s2 = spec([{'match': {'domain': ['*.mine.com']}, 'action': 'direct'}])
n2 = R.seed_rules(s2, tpl)
check(n2 == 0 and doms(s2) == ['*.mine.com'], '已有规则不覆盖', s2)

# 模板本身要是"合并后的形态"。注意 match 各条件是 AND 语义:
# geosite / geoip / domain 不能合成一条 (那会变成"必须同时命中"),
# 所以只要求**纯 domain 规则**里同动作只有一条 —— 这才是 tidy 能合的范围。
import json
tpl_spec = json.load(open(tpl, encoding='utf-8'))
dom_acts = [r.get('action') for r in tpl_spec.get('rules') or []
            if set((r.get('match') or {}).keys()) <= {'domain', 'domain_suffix'}]
check(len(dom_acts) == len(set(dom_acts)),
      '模板已合并 (纯 domain 规则同动作只有一条)', dom_acts)
check(not [x for x in R.tidy_spec(tpl_spec)[1]
           if x.startswith('〔') and not x.startswith(('〔同默认〕', '〔提示〕'))],
      '模板不含冗余条目 (tidy 无结构性问题)',
      R.tidy_spec(tpl_spec)[1])

print('\n' + ('ALL PASS' if not fails else f'FAILED: {fails}'))
sys.exit(1 if fails else 0)
