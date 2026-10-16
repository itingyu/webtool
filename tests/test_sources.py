# -*- coding: utf-8 -*-
"""数据源契约层测试: DataPacket / SourceBase / 工厂 (不出网)

跑法: python3 tests/test_sources.py
"""
import sys

sys.path.insert(0, 'src')

fails = []


def check(name, cond, detail=''):
    print(('PASS' if cond else 'FAIL') + ' ' + name
          + (f' ({detail})' if detail and not cond else ''))
    if not cond:
        fails.append(name)


from webtool.sources import (DataPacket, SourceBase, SourceError,  # noqa: E402
                             get_source, register_source, source_names)
from webtool.sources import contract, registry              # noqa: E402

print('=== 1. DataPacket 契约 ===')
p = DataPacket('search:bing', 'search', [{'title': 't'}], {'total': 1})
check('ok 由 error 反推', p.ok is True and len(p) == 1)
check('error 非空即失败', DataPacket('x', 'k', error='boom').ok is False)
check('items 默认空列表且不共享',
      DataPacket('a', 'b').items == []
      and DataPacket('a', 'b').items is not DataPacket('c', 'd').items)
check('meta 默认空 dict', DataPacket('a', 'b').meta == {})

print('\n=== 2. SourceBase 是 ABC, 缺 fetch 不给实例化 ===')
check('SourceBase 抽象', isinstance(SourceBase, type)
      and getattr(SourceBase, '__abstractmethods__', set()) == {'fetch'},
      str(getattr(SourceBase, '__abstractmethods__', None)))
try:
    SourceBase()
    check('缺 fetch 实例化应报错', False)
except TypeError as e:
    check('缺 fetch 实例化报错', 'abstract' in str(e).lower()
          or 'fetch' in str(e), str(e)[:60])

print('\n=== 3. 实现类过 isinstance 校验, 默认 health 中性 ===')
class Dummy(SourceBase):
    name, kind = 'dummy', 'test'

    def fetch(self, req):
        return DataPacket(self.name, self.kind, [req])

d = Dummy()
check('fetch 返回信封', d.fetch({'q': 1}).items == [{'q': 1}])
check('默认 health 中性', d.health() == {'source': 'dummy', 'kind': 'test', 'ok': True})
check('opts 收进 self.opts', Dummy(a=1).opts == {'a': 1})

print('\n=== 4. 工厂: 内置源已在 plugins.json 登记 ===')
names = source_names()
check('五类内置源均已登记', {'search', 'site', 'hot', 'feed', 'page'} <= set(names),
      str(names))
s = get_source('search', engine='bing')
check('search 源实例化', isinstance(s, SourceBase))
check('source_id 带引擎名', s.source_id == 'search:bing', s.source_id)
check('health 不发请求即得描述', s.health().get('ok') is True and 'Bing' in s.health()['desc'])
for nm, kw, sid in (('site', {'site': 'github'}, 'site:github'),
                    ('hot', {'hot': 'zhihu'}, 'hot:zhihu'),
                    ('page', {}, 'page')):
    o = get_source(nm, **kw)
    check(f'{nm} 源实例化', isinstance(o, SourceBase) and o.kind == nm, o.kind)
    check(f'{nm} source_id 正确', o.source_id == sid, o.source_id)
    check(f'{nm} health 不发请求即得 ok', o.health().get('ok') is True,
          str(o.health()))
f = get_source('feed', feed='ruanyifeng')
check('feed 源实例化', isinstance(f, SourceBase) and f.kind == 'feed')
check('feed health 解析出 url', f.health().get('url', '').startswith('http'),
      str(f.health()))

print('\n=== 5. 未登记/非法实现一律 SourceError ===')
try:
    get_source('nope')
    check('未登记源报错', False)
except SourceError as e:
    check('未登记源报错并列可用项', '可用' in str(e), str(e)[:50])

check('register_source 可注册新源 (返回装饰器)',
      callable(register_source('dummy2', Dummy)))
check('新源可实例化', isinstance(get_source('dummy2'), Dummy))


class NotSource:
    pass


register_source('bad', NotSource)
try:
    get_source('bad')
    check('非 SourceBase 实现应报错', False)
except SourceError as e:
    check('非 SourceBase 实现报错', 'SourceBase' in str(e), str(e)[:60])

print('\n=== 6. 契约层不 import 采集实现 (静态检查) ===')
for mod in (contract, registry):
    src = open(mod.__file__, encoding='utf-8').read()
    bad = [x for x in ('webtool.engines', 'webtool.feeds', 'webtool.net')
           if x in src]
    check(f'{mod.__name__} 不依赖采集实现', not bad, str(bad))

print('\n=== 7. 适配器接线: 抹平三类插件不同的调用约定 ===')
# 用假插件表替掉真注册表, 只验"适配器有没有按对的约定去调, 传对了参数"
import webtool.engines.source as _es                          # noqa: E402

_calls = {}


def _fake_table(kind):
    def _fn(*a, **kw):
        _calls['args'], _calls['kw'] = a, kw
        return [{'title': 't', 'url': 'http://x/1'}]
    return {'fake': {'fn': _fn, 'desc': '假的'}}


_real_table = _es._plugin_table
_es._plugin_table = _fake_table
try:
    _es.SearchSource(engine='fake').fetch({'query': 'q', 'max_results': 3})
    check('engine 源用关键字调 (max_results=)',
          _calls['args'] == ('q',) and _calls['kw'].get('max_results') == 3,
          f'{_calls}')

    pkt = _es.SiteSource(site='fake').fetch({'query': 'q', 'limit': 5,
                                             'extra': {'lang': 'zh'}})
    check('site 源用位置参调 (query, limit, proxy, timeout)',
          _calls['args'][:2] == ('q', 5) and len(_calls['args']) == 4,
          f'{_calls}')
    check('site 源透传 extra 到插件', _calls['kw'] == {'lang': 'zh'}, f'{_calls}')
    check('items 盖上站点名', pkt.items[0].get('site') == 'fake', str(pkt.items))

    hkt = _es.HotSource(hot='fake').fetch({'query': '', 'limit': 7})
    check('hot 源用位置参调且首位补空 query',
          _calls['args'] == ('', 7, None, None), f'{_calls}')
    check('items 盖上榜单名', hkt.items[0].get('hot') == 'fake', str(hkt.items))

    _calls.clear()

    def _boom(*a, **kw):
        raise RuntimeError('引擎炸了')
    _es._plugin_table = lambda kind: {'fake': {'fn': _boom, 'desc': ''}}
    bad = _es.SearchSource(engine='fake').fetch({'query': 'q'})
    check('取数失败落进信封而非抛出', bad.ok is False and 'RuntimeError' in bad.error,
          str(bad.error))
    check('失败时 items 为空且 meta 带上源名', bad.items == []
          and bad.meta.get('engine') == 'fake', str(bad.meta))
finally:
    _es._plugin_table = _real_table

print('\n=== 8. 缺参数一律 SourceError (不看底层插件) ===')
try:
    _es.SiteSource(site='github').fetch({})
    check('site 缺 query 报错', False)
except SourceError as e:
    check('site 缺 query 报错', 'query' in str(e), str(e)[:50])
try:
    _es.HotSource(hot='').fetch({})
    check('hot 缺 hot 名报错', False)
except SourceError as e:
    check('hot 缺 hot 名报错', 'hot' in str(e), str(e)[:50])
try:
    get_source('page').fetch({})
    check('page 缺 url 报错', False)
except SourceError as e:
    check('page 缺 url 报错', 'url' in str(e), str(e)[:50])

print('\n=== 9. 未知插件名报错时列出可用项 ===')
for cls, kw, kind in ((_es.SearchSource, {'engine': '_none'}, 'engine'),
                      (_es.SiteSource, {'site': '_none'}, 'site'),
                      (_es.HotSource, {'hot': '_none'}, 'hot')):
    try:
        cls(**kw).fetch({'query': 'q'})
        check(f'{kind} 未知名报错', False)
    except SourceError as e:
        check(f'{kind} 未知名报错并列出可用项', '可用' in str(e), str(e)[:40])

print()
if fails:
    print('FAILED: %d 项 -> %s' % (len(fails), ', '.join(fails)))
    sys.exit(1)
print('ALL PASS')
