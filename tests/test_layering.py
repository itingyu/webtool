# -*- coding: utf-8 -*-
"""分层 import 守卫 (纯本地): 圈层规则钉死在测试里, 违者当面报错

规则 (docs/coding-standard.md §1, 依赖只许向下):

  cli → 业务(feeds/radar/pipeline/render/engines) → net → core
  - core    不 import 任何上层 (net/engines/pipeline/render/feeds/radar/cli)
  - net     不 import 业务与 cli (core 可以)
  - engines 不 import pipeline/feeds/radar/cli (net/core 可以)
  - render  是纯函数层, 不 import net/engines/feeds/cli

例外以显式白名单登记, 注释写原因 —— 没写注释的例外直接 FAIL。

跑法: python3 tests/test_layering.py
"""
import ast
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    'src', 'webtool')
fails = []

def check(cond, msg, detail=''):
    tag = f' ({detail})' if detail and not cond else ''
    print(('PASS' if cond else 'FAIL') + ' ' + msg + tag)
    if not cond:
        fails.append(msg)

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
    'core':    {'webtool.net', 'webtool.engines', 'webtool.pipeline',
                'webtool.render', 'webtool.feeds',
                'webtool.radar', 'webtool.cli', 'webtool.filters'},
    'dao':     {'webtool.net', 'webtool.engines', 'webtool.pipeline',
                'webtool.render', 'webtool.feeds',
                'webtool.radar', 'webtool.cli', 'webtool.filters',
                'webtool.core'},
    # sources 是契约层: 只出 DataPacket/SourceBase/工厂, 实现由采集层提供
    'sources': {'webtool.net', 'webtool.engines', 'webtool.pipeline',
                'webtool.render', 'webtool.feeds',
                'webtool.radar', 'webtool.cli', 'webtool.filters'},
    'net':     {'webtool.engines', 'webtool.pipeline', 'webtool.render',
                'webtool.feeds', 'webtool.radar',
                'webtool.cli', 'webtool.filters'},
    'engines': {'webtool.pipeline', 'webtool.feeds',
                'webtool.radar', 'webtool.cli'},
    'render':  {'webtool.net', 'webtool.engines', 'webtool.pipeline',
                'webtool.feeds', 'webtool.radar', 'webtool.cli'},
}

# 显式白名单: (文件相对路径子串, 允许的上层包) — 必须写原因, 并标注清理批次
WHITELIST = {
    # 弹性层 fetch() 直接包 net.transport/proxyhelper; 待 P4 把纯弹性
    # (parallel_map/retry/breaker/checkpoint) 与 net 取数包装拆开
    ('core/resilient.py', 'webtool.net'),
    # dao 只准碰 core.logging 这一个无依赖的基础模块 (拿统一 logger/--debug 集成);
    # dao 不得反向 import core 的其余部分, 免得两个基础包互相咬住成环
    ('dao/cache.py', 'webtool.core'),
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
            check(not bad, f'{rel} 不依赖上层', sorted(bad) and str(sorted(bad)))

print()
if fails:
    print('FAILED: %d 项 -> %s' % (len(fails), ', '.join(fails)))
    sys.exit(1)
print('ALL PASS')
