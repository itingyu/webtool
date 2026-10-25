# -*- coding: utf-8 -*-
"""数据源契约层测试: DataPacket / SourceBase / 工厂 (不出网)

跑法: python3 tests/test_sources.py
"""
import sys

sys.path.insert(0, 'src')

fails = []


def check(cond, msg, detail=''):
    print(('PASS' if cond else 'FAIL') + ' ' + msg
          + (f' ({detail})' if detail and not cond else ''))
    if not cond:
        fails.append(msg)


from webtool.sources import (DataPacket, SourceBase, SourceError,  # noqa: E402
                             get_source, register_source, source_names)
from webtool.sources import contract, registry              # noqa: E402

print('=== 1. DataPacket 契约 ===')
p = DataPacket('search:bing', 'search', [{'title': 't'}], {'total': 1})
check(p.ok is True and len(p) == 1, 'ok 由 error 反推')
check(DataPacket('x', 'k', error='boom').ok is False, 'error 非空即失败')
check(DataPacket('a', 'b').items == []
      and DataPacket('a', 'b').items is not DataPacket('c', 'd').items,
      'items 默认空列表且不共享')
check(DataPacket('a', 'b').meta == {}, 'meta 默认空 dict')

print('\n=== 2. SourceBase 是 ABC, 缺 fetch 不给实例化 ===')
check(isinstance(SourceBase, type)
      and getattr(SourceBase, '__abstractmethods__', set()) == {'fetch'}, 'SourceBase 抽象',
      str(getattr(SourceBase, '__abstractmethods__', None)))
try:
    SourceBase()
    check(False, '缺 fetch 实例化应报错')
except TypeError as e:
    check('abstract' in str(e).lower()
          or 'fetch' in str(e), '缺 fetch 实例化报错', str(e)[:60])

print('\n=== 3. 实现类过 isinstance 校验, 默认 health 中性 ===')
class Dummy(SourceBase):
    name, kind = 'dummy', 'test'

    def fetch(self, req):
        return DataPacket(self.name, self.kind, [req])

d = Dummy()
check(d.fetch({'q': 1}).items == [{'q': 1}], 'fetch 返回信封')
check(d.health() == {'source': 'dummy', 'kind': 'test', 'ok': True}, '默认 health 中性')
check(Dummy(a=1).opts == {'a': 1}, 'opts 收进 self.opts')

print('\n=== 4. 工厂: 内置源已在 plugins.json 登记 ===')
names = source_names()
check({'search', 'site', 'hot', 'feed', 'page'} <= set(names), '五类内置源均已登记',
      str(names))
s = get_source('search', engine='bing')
check(isinstance(s, SourceBase), 'search 源实例化')
check(s.source_id == 'search:bing', 'source_id 带引擎名', s.source_id)
check(s.health().get('ok') is True and 'Bing' in s.health()['desc'], 'health 不发请求即得描述')
for nm, kw, sid in (('site', {'site': 'github'}, 'site:github'),
                    ('hot', {'hot': 'zhihu'}, 'hot:zhihu'),
                    ('page', {}, 'page')):
    o = get_source(nm, **kw)
    check(isinstance(o, SourceBase) and o.kind == nm, f'{nm} 源实例化', o.kind)
    check(o.source_id == sid, f'{nm} source_id 正确', o.source_id)
    check(o.health().get('ok') is True, f'{nm} health 不发请求即得 ok',
          str(o.health()))
f = get_source('feed', feed='ruanyifeng')
check(isinstance(f, SourceBase) and f.kind == 'feed', 'feed 源实例化')
check(f.health().get('url', '').startswith('http'), 'feed health 解析出 url',
      str(f.health()))

print('\n=== 5. 未登记/非法实现一律 SourceError ===')
try:
    get_source('nope')
    check(False, '未登记源报错')
except SourceError as e:
    check('可用' in str(e), '未登记源报错并列可用项', str(e)[:50])

check(callable(register_source('dummy2', Dummy)),
      'register_source 可注册新源 (返回装饰器)')
check(isinstance(get_source('dummy2'), Dummy), '新源可实例化')


class NotSource:
    pass


register_source('bad', NotSource)
try:
    get_source('bad')
    check(False, '非 SourceBase 实现应报错')
except SourceError as e:
    check('SourceBase' in str(e), '非 SourceBase 实现报错', str(e)[:60])

print('\n=== 6. 契约层不 import 采集实现 (静态检查) ===')
for mod in (contract, registry):
    src = open(mod.__file__, encoding='utf-8').read()
    bad = [x for x in ('webtool.engines', 'webtool.feeds', 'webtool.net')
           if x in src]
    check(not bad, f'{mod.__name__} 不依赖采集实现', str(bad))

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
    check(_calls['args'] == ('q',) and _calls['kw'].get('max_results') == 3,
          'engine 源用关键字调 (max_results=)',
          f'{_calls}')

    pkt = _es.SiteSource(site='fake').fetch({'query': 'q', 'limit': 5,
                                             'extra': {'lang': 'zh'}})
    check(_calls['args'][:2] == ('q', 5) and len(_calls['args']) == 4,
          'site 源用位置参调 (query, limit, proxy, timeout)',
          f'{_calls}')
    check(_calls['kw'] == {'lang': 'zh'}, 'site 源透传 extra 到插件', f'{_calls}')
    check(pkt.items[0].get('site') == 'fake', 'items 盖上站点名', str(pkt.items))

    hkt = _es.HotSource(hot='fake').fetch({'query': '', 'limit': 7})
    check(_calls['args'] == ('', 7, None, None),
          'hot 源用位置参调且首位补空 query', f'{_calls}')
    check(hkt.items[0].get('hot') == 'fake', 'items 盖上榜单名', str(hkt.items))

    _calls.clear()

    def _boom(*a, **kw):
        raise RuntimeError('引擎炸了')
    _es._plugin_table = lambda kind: {'fake': {'fn': _boom, 'desc': ''}}
    bad = _es.SearchSource(engine='fake').fetch({'query': 'q'})
    check(bad.ok is False and 'RuntimeError' in bad.error, '取数失败落进信封而非抛出',
          str(bad.error))
    check(bad.items == []
          and bad.meta.get('engine') == 'fake', '失败时 items 为空且 meta 带上源名', str(bad.meta))
finally:
    _es._plugin_table = _real_table

print('\n=== 8. 缺参数一律 SourceError (不看底层插件) ===')
try:
    _es.SiteSource(site='github').fetch({})
    check(False, 'site 缺 query 报错')
except SourceError as e:
    check('query' in str(e), 'site 缺 query 报错', str(e)[:50])
try:
    _es.HotSource(hot='').fetch({})
    check(False, 'hot 缺 hot 名报错')
except SourceError as e:
    check('hot' in str(e), 'hot 缺 hot 名报错', str(e)[:50])
try:
    get_source('page').fetch({})
    check(False, 'page 缺 url 报错')
except SourceError as e:
    check('url' in str(e), 'page 缺 url 报错', str(e)[:50])

print('\n=== 9. 未知插件名报错时列出可用项 ===')
for cls, kw, kind in ((_es.SearchSource, {'engine': '_none'}, 'engine'),
                      (_es.SiteSource, {'site': '_none'}, 'site'),
                      (_es.HotSource, {'hot': '_none'}, 'hot')):
    try:
        cls(**kw).fetch({'query': 'q'})
        check(False, f'{kind} 未知名报错')
    except SourceError as e:
        check('可用' in str(e), f'{kind} 未知名报错并列出可用项', str(e)[:40])

print()
if fails:
    print('FAILED: %d 项 -> %s' % (len(fails), ', '.join(fails)))
    sys.exit(1)
print('ALL PASS')
