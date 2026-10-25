# -*- coding: utf-8 -*-
"""非模型命令也要"能先出的先出"

三处一起钉住:
  1. _run: 文本输出不落盘时不再整段缓冲 —— 命令 print 完就已在 stdout 上;
  2. crawl: 抓到第二页之前, 第一页已经打出来了;
  3. fetch --url-file: 快的 URL 不等慢的; -f json 仍等全部收齐 (否则半截数组)。

跑法: python3 tests/test_streaming.py
"""
import io
import os
import sys
import tempfile
import time
from contextlib import redirect_stdout
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'src'))
os.environ['WEBTOOL_DIR'] = tempfile.mkdtemp(prefix='webtool-stream-')

from webtool.cli import _ctx as CX                          # noqa: E402
from webtool.cli import crawl as C                          # noqa: E402
import webtool.pipeline.fetch as F                          # noqa: E402

fails = []

def check(ok, name, detail=''):
    print('%s %s' % ('ok  ' if ok else 'FAIL', name))
    if not ok:
        fails.append(name)
        if detail:
            print('     ' + str(detail)[:300])

# ── 1) _run: 文本透传, 函数执行中就已在 stdout 上 ──────────────────────
CX._CTX.clear()
CX._CTX.update({'args': SimpleNamespace(), 'proxy': None, 'no_cache': False})

outer = io.StringIO()
seen_inside = {}

def fn(args, cfg):
    print('第一段')
    seen_inside['mid'] = outer.getvalue()
    print('第二段')
    return 0

with redirect_stdout(outer):
    rc = CX._run('data', fn, 'text', None, False, False)
check(rc == 0 and '第一段' in seen_inside.get('mid', ''),
      '_run: 函数还没返回, 第一段已经写到 stdout', seen_inside.get('mid'))

# json 仍必须缓冲: 函数执行期间不该有半截输出
outer2 = io.StringIO()
seen_json = {}

def fn_json(args, cfg):
    print('{"a": 1}')
    seen_json['mid'] = outer2.getvalue()
    return 0

with redirect_stdout(outer2):
    CX._run('data', fn_json, 'json', None, False, False)
check(seen_json.get('mid') == '', '_run: json 执行期间不吐半截', seen_json.get('mid'))

# ── 2) crawl: 抓第二页时, 第一页已在输出里 ─────────────────────────────
SITE = {
    'https://s.test/': {'title': '根', 'links': ['https://s.test/a'], 'content': 'root'},
    'https://s.test/a': {'title': 'A', 'links': [], 'content': 'a'},
}
state = {'calls': 0}
buf = io.StringIO()

def fake_page(url, max_chars):
    if url.endswith('robots.txt'):
        return {'url': url, 'content': 'User-agent: *\nDisallow: /nope\n'}
    state['calls'] += 1
    if state['calls'] == 2:                 # 抓第二页时回头看输出
        state['mid'] = buf.getvalue()
    row = SITE[url]
    return {'url': url, 'content': row['content'], 'links': row['links'],
            'chars': len(row['content']), 'metadata': {'title': row['title']}}

C._fetch_page = fake_page
C.cli_json = lambda argv: (True, {'url': 'robots', 'content': ''})

cargs = SimpleNamespace(url='https://s.test/', depth=1, max=10, delay=0,
                        include=None, exclude=None, any_host=False,
                        no_robots=True, max_chars=0, save_dir=None,
                        format='text', output=None, no_proxy=True, no_cache=True)
with redirect_stdout(buf):
    rc = C.do_crawl(cargs, {})
check(rc == 0, 'crawl: 退出码 0', rc)
check('根' in state.get('mid', ''), 'crawl: 抓第 2 页时第 1 页已输出',
      state.get('mid'))

# ── 3) fetch --url-file: 快的先出, 慢的不挡路 ──────────────────────────
with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False) as fh:
    fh.write('https://fast.test/\nhttps://slow.test/\n')
    url_file = fh.name

fbuf = io.StringIO()

def fake_one(u, args, cfg, proxy, timeout, extract_mode='auto'):
    if u.startswith('https://fast.test'):
        time.sleep(0.05)
        return {'url': u, 'content': 'FAST-BODY', 'chars': 9}
    time.sleep(0.6)
    # 慢的那条收尾时, 快的应该早已打印 (读当前 stdout, 不是上一轮的缓冲)
    state['fetch_mid'] = getattr(sys.stdout, 'getvalue', lambda: '')()
    return {'url': u, 'content': 'SLOW-BODY', 'chars': 9}

F._fetch_one = fake_one

def fargs(fmt):
    return SimpleNamespace(
        url=None, url_file=url_file, format=fmt, output=None, max_chars=0,
        no_cache=True, raw=False, with_metadata=False, via='local',
        pdf_pages=None, structured=False, fields=None, links=False,
        links_same_host=True, profile=None, resume=False,
        mark_untrusted=False, agent_max_chars=8000, extract=None,
        save=None, jobs=None, progress=False, no_proxy=True)

with redirect_stdout(fbuf):
    rc = F.do_fetch(fargs('text'), {})
check(rc == 0, 'fetch: 退出码 0', rc)
check('FAST-BODY' in state.get('fetch_mid', ''),
      'fetch: 慢 URL 还没回来时, 快的已经输出', state.get('fetch_mid'))
check('FAST-BODY' in fbuf.getvalue() and 'SLOW-BODY' in fbuf.getvalue(),
      'fetch: 两条正文都完整')

# json: 期间不吐, 结束后是单个可解析数组
jbuf = io.StringIO()
state.pop('fetch_mid', None)
with redirect_stdout(jbuf):
    F.do_fetch(fargs('json'), {})
import json                                                  # noqa: E402
try:
    arr = json.loads(jbuf.getvalue())
    ok_json = isinstance(arr, list) and len(arr) == 2
except Exception:
    ok_json = False
check(ok_json, 'fetch: json 仍是完整数组 (不流式)', jbuf.getvalue()[:120])
check('fetch_mid' not in state or 'FAST-BODY' not in state['fetch_mid'],
      'fetch: json 模式下执行期间不吐半截')

print()
if fails:
    print('FAILED: %s' % ', '.join(fails))
    sys.exit(1)
print('ALL PASS')
