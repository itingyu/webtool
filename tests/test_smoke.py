# -*- coding: utf-8 -*-
"""冒烟测试: 全模块 import + 七类插件表非空 + plugins 体检 + 关键配置装载

跑法: python3 tests/test_smoke.py   (或 pytest tests/test_smoke.py)
P0 教训: Registry.items() 误当 dict 迭代曾把 rank/feed 全崩 —— 一行
import 测试就能拦住, 所以把 import 全量放最前。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import importlib

MODULES = [
    'webtool.core.plugins', 'webtool.core.config_data', 'webtool.core.cache', 'webtool.core.state', 'webtool.core.http', 'webtool.core.probe', 'webtool.core.resilient', 'webtool.core.text', 'webtool.core.urls', 'webtool.core.jsonfmt',
    'webtool.cli.app', 'webtool.cli.config', 'webtool.cli.plugins',
    'webtool.pipeline.search', 'webtool.pipeline.rank', 'webtool.pipeline.merge',
    'webtool.pipeline.topup', 'webtool.pipeline.qhint',
    'webtool.net.transport', 'webtool.net.proxy', 'webtool.net.captcha', 'webtool.net.spa',
    'webtool.render.render', 'webtool.render.hotrender', 'webtool.render.output',
    'webtool.feeds.command', 'webtool.feeds.sources', 'webtool.feeds.parse', 'webtool.feeds.fetch', 'webtool.feeds.cards', 'webtool.radar', 'webtool.zen',
    'webtool.sitesearch', 'webtool.fetch', 'webtool.extractors',
    'webtool.blocklist', 'webtool.adfilter', 'webtool.query_ops',
    'webtool.engines.hotsites', 'webtool.engines.sites',
    'webtool.engines.status', 'webtool.engines.bing',
    'webtool.engines.sogou', 'webtool.engines.baidu',
    'webtool.engines.google', 'webtool.engines.marginalia',
]

fails = []


def check(cond, msg):
    if not cond:
        fails.append(msg)
    print(('PASS ' if cond else 'FAIL ') + msg)


# 1. 全模块 import (拦 Registry 解包/签名这类 import 期崩溃)
for m in MODULES:
    try:
        importlib.import_module(m)
        check(True, f'import {m}')
    except Exception as e:
        check(False, f'import {m}: {type(e).__name__}: {e}')

# 2. 七类插件表非空且可迭代 (k,v) 对
from webtool.core import plugins
for kind in ('engine', 'hot', 'site', 'extractor', 'resolver', 'filter'):
    try:
        items = list(plugins.table(kind).items())
        check(len(items) > 0, f'table({kind}) 非空 ({len(items)})')
    except Exception as e:
        check(False, f'table({kind}): {type(e).__name__}: {e}')
check(isinstance(plugins.table('transformer'), dict), 'table(transformer) 可用 (可为空)')

# 3. 遍历注册表的契约: Registry.items() 返回 dict —— 再 .items() 才是 (k,v) 对;
#    直接 for n, s in registry.items() 是 P0 崩溃根因, 这里锁死正确姿势与错误姿势
try:
    d = plugins.HOT_SITES.items()
    pairs = list(d.items())
    check(len(pairs) > 0 and isinstance(pairs[0], tuple) and len(pairs[0]) == 2,
          'Registry.items().items() 给 (k,v) 对')
except Exception as e:
    check(False, f'Registry.items().items(): {e}')
try:
    bad_iter = False
    for n, s in plugins.HOT_SITES.items():   # noqa: B007 — 故意错误姿势
        pass
    # 迭代 dict 给的是 key 字符串, 解包成单字符 —— 上面没炸说明 key 是单字符?
    # 真实 key 都是多字符, 必炸; 走到这说明行为变了, 标记复核
    bad_iter = True
except ValueError:
    check(True, '错误姿势 (for n,s in registry.items()) 如预期抛 ValueError')
except Exception as e:
    check(True, f'错误姿势抛 {type(e).__name__} (可接受)')
if bad_iter:
    check(False, 'Registry.items() 行为变了: 直接解包不再报错, 需复核契约')

# 4. 默认榜单解析
from webtool.engines.hotsites import default_hot_sources
check(len(default_hot_sources()) > 0, 'default_hot_sources 非空')

# 5. plugins 体检: 全部插件可解析 + 签名合规
bad = []
for kind, reg in ((r.kind, r) for r in plugins._REGISTRIES):
    for pname in sorted(reg.names()):
        spec = reg[pname]
        fn = spec.get('fn')
        if isinstance(fn, plugins._Missing):
            bad.append((kind, pname, str(fn)[:60])); continue
        if not callable(fn):
            bad.append((kind, pname, 'not callable')); continue
        ok, msg = plugins.check_signature(kind, fn)
        if not ok:
            bad.append((kind, pname, msg))
check(not bad, f'插件体检 0 异常 ({bad[:3] if bad else "ok"})')

# 6. 配置文件装载
from webtool.core.config_data import load
for section, fn_ in (('adfilter', 'filters.json'), ('blocklist', 'filters.json'),
                     ('merge', 'filters.json'), ('rsshub', 'instances.json')):
    d = load(section, fn_)
    check(bool(d), f'load({section}, {fn_}) 非空')

# 7. captcha 配置驱动 (engine.params.captcha_signs)
from webtool.net import captcha
blocked, hit = captcha.detect('baidu', '<html><title>百度安全验证</title></html>')
check(blocked, f'captcha.detect baidu 命中配置指纹 ({hit})')

# 8. merge 配置驱动 (track_params/ref_hosts)
from webtool.pipeline.merge import normalize_url, _engine_base
u = normalize_url('https://www.Example.com/a/?utm_source=x&id=1')
check(u == 'https://example.com/a?id=1', f'normalize_url 走配置 ({u})')
check(bool(_engine_base()), 'engine_base 来自清单')

print()
if fails:
    print(f'{len(fails)} FAILED')
    sys.exit(1)
print('ALL PASS')
