# -*- coding: utf-8 -*-
"""ask 流式输出: 正文边到边打, 文末补来源段; json 恒不流

免费额度随时可能 429, 所以这里把搜索/抓正文/模型三步都替换成假实现,
只钉住"什么时候往 stdout 写"和"最终字节长什么样"。

跑法: python3 tests/test_ask_stream.py
"""
import io
import os
import sys
import types
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'src'))

import webtool.cli.ask as A                       # noqa: E402
import webtool.cli.zen.client as Z                # noqa: E402

fails = []

def check(ok, name, detail=''):
    print('%s %s' % ('ok  ' if ok else 'FAIL', name))
    if not ok:
        fails.append(name)
        if detail:
            print('     ' + str(detail)[:300])

ROWS = [
    {'title': '资料一', 'url': 'https://example.com/a', 'snippet': '摘要一'},
    {'title': '资料二', 'url': 'https://example.com/b', 'snippet': '摘要二'},
]

def _args(fmt='text', stream=True):
    return types.SimpleNamespace(
        question='测试问题', num=2, sources=2, max_chars=4000, engine=None,
        preset=None, since=None, until=None, model='fake', system=None,
        retries=1, think=None, max_tokens=None, format=fmt, output=None,
        no_cache=True, no_proxy=True, stream=stream)

# 搜索/抓正文不联网
A._search = lambda q, a: (True, [dict(r) for r in ROWS])
A._fetch = lambda urls, a: {}
CALLS = []

def fake_retry(model, prompt, system, session, on_delta, tool_choice,
               tool_names, cfg, **kw):
    CALLS.append(bool(on_delta))
    for chunk in ('结论一 [1]。', '\n结论二 [1][2]。'):
        if on_delta:
            on_delta(chunk)
    return {'ok': True, 'text': '结论一 [1]。\n结论二 [1][2]。', 'status': 200}

Z.call_zen_retry = fake_retry

# ── 1) 文本: 第一块 delta 到达时就该出现在 stdout 上 ────────────────────
seen_mid = []

class Probe(io.StringIO):
    def write(self, s):
        r = super().write(s)
        seen_mid.append(self.getvalue())
        return r

buf = Probe()
with redirect_stdout(buf):
    rc = A.do_ask(_args(), {})
out = buf.getvalue()
check(rc == 0, 'text: 退出码 0', rc)
check(len(seen_mid) >= 2 and '结论一' in seen_mid[0],
      'text: 第一块 delta 到达前已实时写入 stdout (非结束后一次性)',
      seen_mid[:2])
check(out.count('结论一') == 1, 'text: 正文只出现一次 (不重复打)', out[:120])
check('参考来源' in out and 'https://example.com/a' in out,
      'text: 文末仍补上来源段', out[-120:])
check(out.index('结论一') < out.index('参考来源'), 'text: 来源在正文之后')

# ── 2) --no-stream: 结束才写, 但最终字节和流式一致 ──────────────────────
buf2 = io.StringIO()
with redirect_stdout(buf2):
    rc2 = A.do_ask(_args(stream=False), {})
check(rc2 == 0 and buf2.getvalue() == out,
      '--no-stream: 最终输出与流式完全一致', repr(buf2.getvalue()[:80]))

# ── 3) json: 不流式 (半截 JSON 不可解析), 且只输出一个对象 ──────────────
buf3 = io.StringIO()
with redirect_stdout(buf3):
    rc3 = A.do_ask(_args(fmt='json'), {})
import json                                        # noqa: E402
try:
    d = json.loads(buf3.getvalue())
    ok_json = True
except Exception:
    d, ok_json = {}, False
check(rc3 == 0 and ok_json, 'json: 输出是单个合法 JSON', buf3.getvalue()[:120])
check(d.get('cited') == [1, 2], 'json: cited 解析正确', d.get('cited'))
check(len(d.get('sources') or []) == 2, 'json: sources 完整')

print()
if fails:
    print('FAILED: %s' % ', '.join(fails))
    sys.exit(1)
print('ALL PASS')
