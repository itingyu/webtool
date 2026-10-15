# -*- coding: utf-8 -*-
"""分层 import 守卫 (纯本地): 圈层规则钉死在测试里, 违者当面报错

规则 (docs/coding-standard.md §1, 依赖只许向下):

  cli → 业务(feeds/stock/radar/pipeline/render/engines) → net → core
  - core    不 import 任何上层 (net/engines/pipeline/render/feeds/stock/radar/cli)
  - net     不 import 业务与 cli (core 可以)
  - engines 不 import pipeline/feeds/stock/radar/cli (net/core 可以)
  - render  是纯函数层, 不 import net/engines/stock/feeds/cli
  - stock/bridge/sources 只 import net/core + 本包 (不出业务层)

例外以显式白名单登记, 注释写原因 —— 没写注释的例外直接 FAIL。

跑法: python3 tests/test_layering.py
"""
import ast
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    'src', 'webtool')
fails = []

def check(name, cond, detail=''):
    print(('PASS' if cond else 'FAIL') + ' ' + name + (f' ({detail})' if detail and not cond else ''))
    if not cond:
        fails.append(name)

def top_module(dotted):
    parts = dotted.split('.')
    return 'webtool.' + parts[1] if len(parts) > 1 and parts[0] == 'webtool' else None

def imports_of(path):
    """文件 import 的 webtool 顶层包集合 (ast 解析, 含函数内延迟 import)"""
    out = set()
    with open(path, encoding='utf-8') as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                m = top_module(a.name)
                if m:
                    out.add(m)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            m = top_module(node.module)
            if m:
                out.add(m)
    return out

UPPER = {
    'core':    {'net', 'engines', 'pipeline', 'render', 'feeds', 'stock',
                'radar', 'cli', 'filters', 'data'},
    'net':     {'engines', 'pipeline', 'render', 'feeds', 'stock', 'radar',
                'cli', 'filters'},
    'engines': {'pipeline', 'feeds', 'stock', 'radar', 'cli'},
    'render':  {'net', 'engines', 'pipeline', 'stock', 'feeds', 'radar', 'cli'},
}

# 显式白名单: (包, 文件, 允许的上层包) — 必须写原因
WHITELIST = {
    # (无) —— 目前没有已登记的例外; 加例外先在这里写原因, 测试会替你追问
}

for pkg, forbidden in UPPER.items():
    pdir = os.path.join(ROOT, pkg)
    for dirpath, dirnames, filenames in os.walk(pdir):
        dirnames[:] = [d for d in dirnames if d != '__pycache__']
        for fn in filenames:
            if not fn.endswith('.py'):
                continue
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, ROOT)
            found = imports_of(path) & forbidden
            allowed = {w_pkg for (w_file, w_pkg) in WHITELIST
                       if w_file in rel}
            bad = found - allowed
            check(f'{rel} 不依赖上层', not bad, sorted(bad) and str(sorted(bad)))

# 数据源包: 只吃 net/core/本包
src_dir = os.path.join(ROOT, 'stock', 'bridge', 'sources')
for dirpath, dirnames, filenames in os.walk(src_dir):
    dirnames[:] = [d for d in dirnames if d != '__pycache__']
    for fn in filenames:
        if not fn.endswith('.py'):
            continue
        path = os.path.join(dirpath, fn)
        rel = os.path.relpath(path, ROOT)
        found = imports_of(path) - {'webtool', 'webtool.net', 'webtool.core',
                                    'webtool.stock'}
        check(f'{rel} 只依赖 net/core/stock', not found, str(sorted(found)))

# 源注册表与 APIClient 一致性
from webtool.stock.bridge import sources as S
names = sorted(S.SOURCES)
check('注册表覆盖全部源 (10 个)', len(names) == 10, str(names))
try:
    S.source_class('nope')
    check('source_class 未知名字抛 KeyError', False)
except KeyError as e:
    check('source_class 未知名字抛 KeyError 并列可用项', '可用' in str(e))
for n, c in S.SOURCES.items():
    check(f'注册表 {n} -> {c.__name__}', isinstance(c, type))

# gtimg 迁移后: SinaSource 不再持 gtimg, TencentSource 持有
check('gtimg_* 已归位 TencentSource',
      all(hasattr(S.TencentSource, m)
          for m in ('gtimg_hq', 'gtimg_quote_flat', 'gtimg_fund'))
      and not any(m.startswith('gtimg_') for m in dir(S.SinaSource)))

print()
if fails:
    print('FAILED: %d 项 -> %s' % (len(fails), ', '.join(fails)))
    sys.exit(1)
print('ALL PASS')
