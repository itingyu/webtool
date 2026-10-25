"""search / site 分流守卫: 引擎与站内搜索不再混用 (脚本式, 直接 python 跑)

用法: PYTHONPATH=src python tests/test_site_cmd.py
"""
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
ENV = dict(os.environ, PYTHONPATH=str(ROOT / 'src'),
           WEBTOOL_DIR=tempfile.mkdtemp(prefix='wt-site-'))
fails = []


def check(cond, name, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (': ' + detail if detail and not cond else ''))
    if not cond:
        fails.append(name)


def run(*argv):
    return subprocess.run([sys.executable, '-m', 'webtool', *argv],
                          capture_output=True, text=True, timeout=120, env=ENV)


r = run('site', '--help')
check(r.returncode == 0 and '站内搜索' in r.stdout, 'site 是独立命令')

r = run('search', '-s', 'juejin', 'Python')
check(r.returncode == 2 and 'webtool site juejin' in r.stderr,
      'search 拒绝站点名并指向 site', r.stderr[-200:])

r = run('site')
check(r.returncode == 0 and '站点搜索源' in r.stdout, 'site 无参时列站点')

r = run('search', '-s', 'bing', 'Python', '-n', '1')
check(r.returncode == 0, 'search 仍可按引擎搜索', (r.stderr or r.stdout)[-200:])

print('\nALL PASS' if not fails else f'\nFAILED: {fails}')
sys.exit(0 if not fails else 1)
