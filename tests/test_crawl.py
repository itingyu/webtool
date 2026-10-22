"""crawl 的离线测试: 打桩 _fetch_page, 不碰网络"""
import io
import json
import os
import shutil
import sys
import tempfile
from contextlib import redirect_stdout
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from webtool.cli import crawl as C  # noqa: E402

_fails = []


def check(cond, name):
    if cond:
        print('PASS ' + name)
    else:
        print('FAIL ' + name)
        _fails.append(name)


# 一个假站点: 根页链到 a/b/外站/robots 禁止页; a 页链到 c
SITE = {
    'https://s.test/': {'title': '根', 'links': ['https://s.test/a', 'https://s.test/b',
                                                'https://other.test/x', 'https://s.test/private/x'],
                        'content': 'root'},
    'https://s.test/a': {'title': 'A', 'links': ['https://s.test/c'], 'content': 'a'},
    'https://s.test/b': {'title': 'B', 'links': [], 'content': 'b'},
    'https://s.test/c': {'title': 'C', 'links': [], 'content': 'c'},
}

_fetched = []


def _fake_page(url, max_chars):
    _fetched.append(url)
    if url.endswith('/robots.txt'):
        return {'url': url, 'content': 'User-agent: *\nDisallow: /private\n'}
    row = SITE.get(url)
    if not row:
        return None
    return {'url': url, 'content': row['content'], 'links': row['links'],
            'chars': len(row['content']), 'metadata': {'title': row['title']}}


C._fetch_page = _fake_page

# robots.txt 由 _robots_rules 经 cli_json 取, 单独打桩: 禁 /private
C.cli_json = lambda argv: (True, {'url': 'robots', 'content': 'User-agent: *\nDisallow: /private\n'})



def _args(**kw):
    base = dict(url='https://s.test/', depth=2, max=10, delay=0, include=None,
                exclude=None, any_host=False, no_robots=False, max_chars=0,
                save_dir=None, format='text', no_proxy=True, no_cache=True)
    base.update(kw)
    return SimpleNamespace(**base)


def _run(**kw):
    _fetched.clear()
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = C.do_crawl(_args(**kw), {})
    return rc, buf.getvalue()
rc, out = _run(depth=2)
pages = [u for u in _fetched if not u.endswith('robots.txt')]
check(rc == 0, '正常爬完退出码 0')
check(pages[0] == 'https://s.test/', '先抓种子页')
check('https://s.test/a' in pages and 'https://s.test/b' in pages, '跟到了站内链接')
check('https://s.test/c' in pages, '深度 2 能到 c')
check('https://other.test/x' not in pages, '默认不跨域')
check(len(pages) == len(set(pages)), '同一页不重复抓')
check('爬取 4 页' in out, '报告页数')
check('根' in out, '列出标题')

rc, out = _run(depth=0)
pages = [u for u in _fetched if not u.endswith('robots.txt')]
check(pages == ['https://s.test/'], 'depth=0 只抓种子')

rc, out = _run(depth=2, max=2)
pages = [u for u in _fetched if not u.endswith('robots.txt')]
check(len(pages) == 2, '--max-pages 限制页数')

rc, out = _run(depth=2, include=r'/a$|/c$')
pages = [u for u in _fetched if not u.endswith('robots.txt')]
check('https://s.test/a' in pages, 'include 放行匹配的')
check('https://s.test/b' not in pages, 'include 拦掉不匹配的')

rc, out = _run(depth=2, exclude=r'/b$')
pages = [u for u in _fetched if not u.endswith('robots.txt')]
check('https://s.test/b' not in pages, 'exclude 生效')

# ── robots / 保存 / 空结果 ────────────────────────────────
rc, out = _run(depth=2, delay=0)
pages = [u for u in _fetched if not u.endswith('robots.txt')]
check(not any('/private/' in u for u in pages), 'robots 禁止的路径不抓')

rc, out = _run(url='https://s.test/', depth=0, max_pages=0)
check(rc == 0, 'max_pages 至少按 1 处理')

rc, out = _run(url='https://nothere.test/', depth=1)
check(rc == 2, '起点抓不到 → 退出码 2')

print()
if _fails:
    print('FAILED: %d 项 -> %s' % (len(_fails), ', '.join(_fails)))
    sys.exit(1)
print('ALL PASS')
