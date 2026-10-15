# -*- coding: utf-8 -*-
"""zen 客户端边界单测 (纯本地, 不联网): 思考段切分 + max_tokens 降档解析

跑法: python3 tests/test_zen_limits.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

fails = []

def check(name, cond):
    print(('PASS' if cond else 'FAIL') + ' ' + name)
    if not cond:
        fails.append(name)

from webtool.cli.zen.client import _max_tokens_limit, split_think

# ── max_tokens 400 解析 ──────────────────────────────────────────
real = {'status': 400,
        'error_body': 'data: {"error":{"param":"max_tokens is too large: '
                      '200000. This model supports at most 131072 completion '
                      'tokens, whereas you provided 200000."}}'}
check('解析出模型上限', _max_tokens_limit(real) == 131072)
check('别的 400 不认领', _max_tokens_limit({'status': 400,
                                            'error_body': 'bad request'}) is None)
check('非 400 不看', _max_tokens_limit({'status': 500, 'error_body': 'at most 1'}) is None)
check('空响应安全', _max_tokens_limit(None) is None and _max_tokens_limit({}) is None)
check('文案里没数字 → None',
      _max_tokens_limit({'status': 400,
                         'error_body': 'max_tokens too large'}) is None)
check('大小写不敏感',
      _max_tokens_limit({'status': 400,
                         'error_body': 'MAX_TOKENS ... AT MOST 32768'}) == 32768)

# ── 思考段切分 ───────────────────────────────────────────────────
check('标准标签切分', split_think('a<thinking>x</thinking>b') == ('a<thinking>x', 'b'))
check('只有闭标签: 前面都算思考',
      split_think('推理过程</think>答案') == ('推理过程', '答案'))
check('有开无闭 (被截断) → 整段思考',
      split_think('推理<thinking>还没写完') == ('推理<thinking>还没写完', ''))
check('无标签原样返回', split_think('普通正文') == ('', '普通正文'))
check('空串', split_think('') == ('', ''))
check('多个闭标签取最早', split_think('a</think>b</think>c') == ('a', 'b</think>c'))

print()
if fails:
    print('FAILED: %d 项 -> %s' % (len(fails), ', '.join(fails)))
    sys.exit(1)
print('ALL PASS')
