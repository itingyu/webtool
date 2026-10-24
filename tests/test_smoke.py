# -*- coding: utf-8 -*-
"""冒烟测试: 全模块 import + 各类插件表非空 + plugins 体检 + 关键配置装载

跑法: python3 tests/test_smoke.py   (或 pytest tests/test_smoke.py)
P0 教训: Registry.items() 误当 dict 迭代曾把 rank/feed 全崩 —— 一行
import 测试就能拦住, 所以把 import 全量放最前。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import importlib

MODULES = [
    'webtool.core.plugins', 'webtool.core.config_data', 'webtool.core.resilient', 'webtool.core.text', 'webtool.core.urls', 'webtool.core.jsonfmt', 'webtool.core.errors',
    'webtool.dao', 'webtool.dao.cache', 'webtool.dao.state', 'webtool.dao.checkpoint',
    'webtool.sources', 'webtool.sources.contract', 'webtool.sources.registry',
    'webtool.engines.source', 'webtool.feeds.source',
    'webtool.cli.app', 'webtool.cli.config', 'webtool.cli.plugins',
    'webtool.pipeline.search', 'webtool.pipeline.rank', 'webtool.pipeline.merge',
    'webtool.pipeline.topup',
    'webtool.net.transport', 'webtool.net.proxy', 'webtool.net.captcha', 'webtool.net.spa',
    'webtool.net.tls', 'webtool.net.http', 'webtool.net.connectivity', 'webtool.net.stream',
    'webtool.net.fingerprints', 'webtool.net.pacing', 'webtool.net.adapters',
    'webtool.net.rules', 'webtool.net.rules.router', 'webtool.net.rules.loader',
    'webtool.render.render', 'webtool.render.hotrender', 'webtool.render.output',
    'webtool.feeds.command', 'webtool.feeds.sources', 'webtool.feeds.parse', 'webtool.feeds.fetch', 'webtool.feeds.cards', 'webtool.radar', 'webtool.radar.race', 'webtool.radar.template',
    'webtool.radar.routes', 'webtool.radar.instances',
    'webtool.radar.official', 'webtool.radar.instances_cfg', 'webtool.cli.zen',
    'webtool.cli.sitesearch', 'webtool.pipeline.fetch', 'webtool.engines.extractors',
    'webtool.engines.boilerplate',
    'webtool.filters.blocklist', 'webtool.filters.adfilter', 'webtool.pipeline.query_ops',
    'webtool.engines.hotsites', 'webtool.engines.sites',
    'webtool.engines.status', 'webtool.engines.bing',
    'webtool.engines.sogou', 'webtool.engines.baidu',
    'webtool.engines.google', 'webtool.engines.marginalia', 'webtool.engines.so360',
    'webtool.net.mcpclient', 'webtool.cli.mcp', 'webtool.engines.exa',
    'webtool.net.download', 'webtool.net.download.transfer',
    'webtool.net.download.resume', 'webtool.net.download.progress',
    'webtool.cli.zen.think', 'webtool.cli.zen.client',
]

fails = []


def check(cond, msg, detail=''):
    if not cond:
        fails.append(msg)
    print(('PASS ' if cond else 'FAIL ') + msg
          + (f'  [{detail}]' if detail and not cond else ''))


# 1. 全模块 import (拦 Registry 解包/签名这类 import 期崩溃)
for m in MODULES:
    try:
        importlib.import_module(m)
        check(True, f'import {m}')
    except Exception as e:
        check(False, f'import {m}: {type(e).__name__}: {e}')

# 2. 各类插件表非空且可迭代 (k,v) 对
from webtool.core import plugins
for kind in ('engine', 'hot', 'site', 'extractor', 'resolver', 'filter'):
    try:
        items = list(plugins.table(kind).items())
        check(len(items) > 0, f'table({kind}) 非空 ({len(items)})')
    except Exception as e:
        check(False, f'table({kind}): {type(e).__name__}: {e}')
check(isinstance(plugins.table('transformer'), dict), 'table(transformer) 可用 (可为空)')

# 3. 遍历注册表的契约: Registry.items() 返回 dict —— 再 .items() 才是 (k,v) 对
try:
    d = plugins.HOT_SITES.items()
    pairs = list(d.items())
    check(len(pairs) > 0 and isinstance(pairs[0], tuple) and len(pairs[0]) == 2,
          'Registry.items().items() 给 (k,v) 对')
except Exception as e:
    check(False, f'Registry.items().items(): {e}')

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

# 9. blocklist 域名匹配 (回归: 曾因 _norm_host 收 URL 却传裸 netloc 而全表失效)
from webtool.filters.blocklist import is_blocked as _isblk
_bcases = [('https://blog.csdn.net/abc', True, '子域'),
           ('https://csdn.net', True, 'apex'),
           ('https://www.zhihu.com/x', True, 'www 前缀'),
           ('https://user:pw@csdn.net/x', True, '带凭据'),
           ('https://csdn.net:8080/x', True, '带端口'),
           ('https://evil-csdn.net/x', False, '非子域不拦'),
           ('https://docs.python.org/3', False, '正常站不拦'),
           ('', False, '空 URL 不拦')]
_bad = [d for u, w, d in _bcases if _isblk(u) != w]
check(not _bad, f'blocklist 域名匹配 {len(_bcases)} 例全对 (错: {_bad or "无"})')

# 8. merge 配置驱动 (track_params/ref_hosts) + 两因子排序
from webtool.pipeline.merge import normalize_url, merge as _merge
u = normalize_url('https://www.Example.com/a/?utm_source=x&id=1')
check(u == 'https://example.com/a?id=1', f'normalize_url 走配置 ({u})')

# pos(排名) 单调影响权重
def _mk(title, rank, engines, ranks=None):
    return {'title': title, 'url': 'https://e.com/' + title, 'snippet': 'query 教程',
            'engine': engines[0], 'engines': list(engines), 'rank': rank}
_rr = _merge([_mk('alpha 教程', 1, ['bing']), _mk('beta 教程', 5, ['bing'])],
             'query', dedupe=False)
check(_rr[0]['weight'] > _rr[1]['weight'], f'pos 靠前权重高 ({_rr[0]["weight"]} > {_rr[1]["weight"]})')
# base_avg 是批级量: 同批内共享同一 base_avg, 故同 rank 同相关性的条目
# 必然等权 (归一后同为 1.0) —— 可信度不再逐条区分。
_m0 = _merge([_mk('gamma 教程', 1, ['google']), _mk('delta 教程', 1, ['sogou'])],
             '', use_semantic=False, dedupe=False)
_by_0 = {r['title']: r['weight'] for r in _m0}
check(_by_0['gamma 教程'] == _by_0['delta 教程'],
      f'批级 base_avg 同 rank 等权 ({_by_0["gamma 教程"]})')
# base_avg 随各引擎贡献数变化: 高可信引擎多贡献的批次, 整体权重应更高。
# 批A 全是 google, 批B 全是 sogou —— 各自归一后 top 都是 1.0, 故改看
# 同 rank 下的原始比例: 用两条不同 rank 条目比较衰减速度无意义, 直接
# 验证 base_avg 本身进了 pos: 低可信引擎独占批次时, 排名靠后条目衰减更快。
_mg = _merge([_mk('g1', 2, ['google']), _mk('g2', 8, ['google'])],
             '', use_semantic=False, dedupe=False)
_ms = _merge([_mk('s1', 2, ['sogou']), _mk('s2', 8, ['sogou'])],
             '', use_semantic=False, dedupe=False)
_g = {r['title']: r['weight'] for r in _mg}
_s = {r['title']: r['weight'] for r in _ms}
# 归一后尾/首比值 = (rank8 分/rank2 分), base_avg 是乘性因子会被约掉,
# 故两批比值相同 —— 断言批级化确实生效 (不再逐条按引擎区分)
check(abs((_g['g2'] / _g['g1']) - (_s['s2'] / _s['s1'])) < 1e-3,
      f'批级化后与引擎无关 ({_g["g2"]/_g["g1"]:.3f} ≈ {_s["s2"]/_s["s1"]:.3f})')
# sem 直接用 BM25 归一化分: 相关文档权重高于无关文档 (多文档才有区分度)
_docs = [_mk('alpha 相关页', 1, ['bing']), _mk('zeta 无关页', 1, ['bing'])]
_docs[0]['snippet'] = 'query 命中 snippet'
_docs[1]['snippet'] = '完全不相关的内容'
_r = _merge(_docs, 'query', dedupe=False)
_by_title = {r['title']: r['weight'] for r in _r}
check(_by_title['alpha 相关页'] > _by_title['zeta 无关页'],
      f'sem BM25 拉高相关结果 ({_by_title["alpha 相关页"]} '
      f'> {_by_title["zeta 无关页"]})')
# prior: 广告判 0 权重 (is_ad 恒 True, 绕开依赖具体广告域名)
_ad = _mk('广告页', 1, ['bing'])
_ad['is_ad'] = True
_p = _merge([_ad, _mk('正常页', 1, ['bing'])],
            'query', use_semantic=False, dedupe=False)
_by_p = {r['title']: r['weight'] for r in _p}
check('广告页' not in _by_p and _by_p.get('正常页', 0) > 0,
      f'prior 广告判 0 并被过滤 ({sorted(_by_p)})')
# prior: 英文 query 下词典域名降权 (ref_hosts: baike.baidu.com)
_dic = _mk('词典页', 1, ['bing'])
_dic['url'] = 'https://baike.baidu.com/item/x'
_d2 = _merge([_dic, _mk('正常页2', 1, ['bing'])],
             'python tutorial', use_semantic=False, dedupe=False)
_by_d = {r['title']: r['weight'] for r in _d2}
check(0 < _by_d['词典页'] < _by_d['正常页2'],
      f'prior 词典降权 ({_by_d["词典页"]} < {_by_d["正常页2"]})')
# blocklist 硬过滤改为 prior=0: 黑名单站算完权重后被剔除, 且参与去重
_blk = _mk('黑名单页', 1, ['bing'])
_blk['url'] = 'https://blog.csdn.net/abc/post/1'
_bw = _merge([_blk, _mk('正常页6', 1, ['bing'])], 'query',
             use_semantic=False, dedupe=False)
check('黑名单页' not in [r['title'] for r in _bw] and '正常页6' in [r['title'] for r in _bw],
      f'blocklist 判 prior=0 并被剔除 ({[r["title"] for r in _bw]})')
# apply_blocklist=False 时黑名单站照常返回 (--no-blocklist 语义)
_bt = [r['title'] for r in _merge([dict(_mk('黑名单页2', 1, ['bing']), url='https://blog.csdn.net/x'),
                                   _mk('正常页7', 1, ['bing'])], 'query',
                                  use_semantic=False, dedupe=False, apply_blocklist=False)]
check('黑名单页2' in _bt, f'apply_blocklist=False 放行 ({_bt})')
# prior: low_prior 降权 (从 blocklist 放出的内容可用但质量存疑的站)
_low = _mk('搬运页', 1, ['bing'])
_low['url'] = 'https://www.jb51.net/article/1'
_pw = _merge([_low, _mk('正常页3', 1, ['bing'])],
             'query', use_semantic=False, dedupe=False)
_by_w = {r['title']: r['weight'] for r in _pw}
check(0 < _by_w['搬运页'] < _by_w['正常页3'],
      f'prior low_prior 降权 ({_by_w["搬运页"]} < {_by_w["正常页3"]})')
# low_prior_value 生效: 归一后搬运页恰为该配置值
from webtool.core.config_data import load as _ld
_lpv = _ld('merge', 'filters.json')['low_prior_value']
check(abs(_by_w['搬运页'] - _lpv) < 1e-3,
      f'low_prior_value 精确生效 ({_by_w["搬运页"]} == {_lpv})')
# weight_floor 是兜底阈值: 实测真实结果权重集中在 0.47-0.95 (57 条样本
# min 0.465), 故 0.30 只挡异常值。两个方向各测一次 ——
# 相关结果即使排名靠后也不该被误杀;
_rel = _mk('相关页', 30, ['bing'])
_rel['snippet'] = 'query 命中 snippet'
_nf = _merge([_rel, _mk('正常页4', 1, ['bing'])], 'query', dedupe=False)
_titles = [r['title'] for r in _nf]
check('相关页' in _titles and '正常页4' in _titles,
      f'weight_floor 不误杀 ({_titles})')
# floor 按 n 动态算: √(pos(n)×base_avg)×0.5
# n<3 不启用 —— 候选太少时阈值无意义
def _junk():
    j = _mk('零相关页', 30, ['bing'])
    j['snippet'] = 'zzz'
    return j
_s2 = {}
_o2 = _merge([_mk('正常页5', 1, ['bing']), _junk()], 'query', dedupe=False,
             stats=_s2, max_n=None)
check(_s2.get('weight_floor') == 0 and len(_o2) == 2,
      f'n<3 不启用 floor ({_s2.get("weight_floor")}, {len(_o2)} 条)')
# n>=3 启用: floor 生效, 零相关尾部在候选足够多时被剔除
_s3 = {}
_o3 = _merge([_mk(f'r{i}', i + 1, ['bing']) for i in range(10)] + [_junk()],
             'query', dedupe=False, stats=_s3, max_n=None)
check(_s3.get('weight_floor', 0) > 0 and '零相关页' not in [r['title'] for r in _o3],
      f'n>=3 启用 floor 剔除零相关 (floor={_s3.get("weight_floor")}, '
      f'dropped={_s3.get("floor_dropped")})')
# max_n 限制 n: max_n=2 时即使候选 3 条也不启用
_s4 = {}
_merge([_mk('正常页6', 1, ['bing']), _junk(), _mk('第三页2', 2, ['bing'])],
       'query', dedupe=False, stats=_s4, max_n=2)
check(_s4.get('weight_floor') == 0, f'max_n=2 不启用 floor ({_s4.get("weight_floor")})')
# floor 随 n 上升而下降 (候选越多, 尾部容忍越高)
_fs = []
for nn in (3, 10, 30):
    _sx = {}
    _merge([_mk(f'r{i}', i + 1, ['bing']) for i in range(nn)], 'query',
           dedupe=False, stats=_sx, max_n=None)
    _fs.append(_sx.get('weight_floor'))
check(_fs[0] > _fs[1] > _fs[2], f'floor 随 n 递减 ({_fs})')

# 10. MCP 客户端: SSE 解析 / 双协议自适应 / URL 拼接 / 端点表 (纯离线, 不出网)
from webtool.net import mcpclient as _mc
_sse_cases = [
    ('text/event-stream', 'event: message\ndata: {"a":1}\n\n', {'a': 1}, 'SSE 常规帧'),
    ('application/json', '{"a":1}', {'a': 1}, '纯 JSON'),
    ('text/plain', 'data: {"a":2}\n\n', {'a': 2}, 'body 前缀嗅探兜底'),
    ('text/event-stream; charset=utf-8', ': keepalive\n\ndata: {"b":1}\n\n',
     {'b': 1}, '跳过 : 注释行'),
    ('text/event-stream', 'event: x\ndata: {"m":1}\n\ndata: {"m":2}\n\n',
     {'m': 2}, '多帧取最后一个'),
    ('text/event-stream', 'data: {"multi":\ndata: 1}\n\n', {'multi': 1}, '多行 data 拼接'),
]
_bad = [d for ct, body, want, d in _sse_cases if _mc.parse_response(ct, body) != want]
check(not _bad, f'SSE/JSON 双协议解析 {len(_sse_cases)} 例全对 (错: {_bad or "无"})')
# 非 JSON 的 data 帧不抛异常, 退回原始结构 (诊断信息不能被吞)
_raw = _mc.parse_sse_message('event: message\ndata: not-json\n\n')
check(_raw.get('data') == 'not-json' and 'raw' in _raw, 'SSE 解析失败退回原始结构')
# URL 拼接: 端点自带 query 时用 & 而不是再拼 ?
_ucases = [('https://x.com/mcp', '', 'https://x.com/mcp'),
           ('https://x.com/mcp', 'a,b', 'https://x.com/mcp?tools=a,b'),
           ('https://x.com/mcp?v=1', 'a,b', 'https://x.com/mcp?v=1&tools=a,b')]
_bad = [d for base, tf, want in _ucases if _mc.build_url(base, tf) != want]
check(not _bad, f'build_url 白名单拼接 {len(_ucases)} 例全对 (错: {_bad or "无"})')
# 空 key 不发认证头 (免 key 通道); 有 key 只发 x-api-key (实测三头冗余)
check('x-api-key' not in _mc.build_headers(''), '无 key 不发认证头')
check(_mc.build_headers('k').get('x-api-key') == 'k', '有 key 发 x-api-key')
# UA 与上游 exa-search 一致 (Minis/1.0), 避免同一客户端出现两种指纹
check(_mc.build_headers('')['User-Agent'] == 'Minis/1.0',
      f"UA 与上游一致 ({_mc.build_headers('')['User-Agent']})")
# 内置端点表可装载且 URL 合规
from webtool.core.config_data import load as _ld2
_mcps = _ld2('mcp', 'mcp.json')
check(bool(_mcps) and all(str(s.get('url', '')).startswith('https://')
                          for s in _mcps.values()),
      f'mcp.json 端点表装载 ({len(_mcps)} 项)')

# 11. MCP 拆参: 位置 JSON 与 --arg 合并, 值按 JSON 字面量猜类型
from webtool.cli.mcp import _build_args as _BA
_bcases = [('', None, {}),
           ('{"query":"x","n":3}', None, {'query': 'x', 'n': 3}),
           ('', ['query=hi', 'numResults=5', 'flag=true', 'nil=null'],
            {'query': 'hi', 'numResults': 5, 'flag': True, 'nil': None}),
           ('', ['q=webtool MCP 客户端', 'url=https://a.com/x?y=1&z=2'],
            {'q': 'webtool MCP 客户端', 'url': 'https://a.com/x?y=1&z=2'}),
           ('', ['urls=["https://a.com","https://b.com"]'],
            {'urls': ['https://a.com', 'https://b.com']}),
           ('{"query":"old","keep":1}', ['query=new'], {'query': 'new', 'keep': 1}),
           ('', ['q=a=b'], {'q': 'a=b'})]
_bad = [d for raw, pairs, want in _bcases if _BA(raw, pairs) != want]
check(not _bad, f'参数组装 {len(_bcases)} 例全对 (错: {_bad or "无"})')
# 非法输入一律返回 None (不抛), 由调用方退 2
check(all(_BA(x, y) is None for x, y in (('{bad', None), ('[1,2]', None),
                                         ('', ['noeq']), ('', ['=v']))),
      '非法参数组装退 None')

from types import SimpleNamespace as _SN

# 12. exa 引擎: 端点声明 + 文本解析 + 强制直连 + numResults 封顶
from webtool.engines import exa as _exa
_espec = _exa._spec('exa')
_verbs = (_espec or {}).get('verbs') or {}
check(set(_verbs) >= {'search'}, f'exa 声明 search 动词 ({sorted(_verbs)})')
check('proxy' not in (_espec or {}),
      '端点表不声明代理策略 (配额计量不该由内置数据替用户决定)')
_eng_exa_spec = __import__('webtool.core.plugins', fromlist=['table']).table('engine').get('exa') or {}
check(_eng_exa_spec.get('entry') == 'webtool.engines.exa:search',
      f'exa 引擎注册到插件表 ({_eng_exa_spec.get("entry")})')
check(_eng_exa_spec.get('params', {}).get('enabled_by_default') is False,
      'exa 不进默认引擎 (免 key 配额按 IP 计, 不宜默认开)')
# 纯文本 → 标准结果结构
_txt = ('Title: 甲文档\nURL: https://a.com/1\nPublished: N/A\nAuthor: N/A\n'
        'Highlights:\n甲的正文摘要\n第二行\n\n'
        'Title: 乙文档\nURL: https://b.com/2\nPublished: N/A\nAuthor: N/A\n'
        'Highlights:\n乙的正文\n\n'
        'Title: 重复\nURL: https://a.com/1\nHighlights:\n应被去重\n')
_parsed = _exa._parse(_txt, 10)
check([r['title'] for r in _parsed] == ['甲文档', '乙文档'],
      f'按 Title 切块并按 URL 去重 ({[r["title"] for r in _parsed]})')
check(_parsed and _parsed[0]['url'] == 'https://a.com/1'
      and '甲的正文摘要' in _parsed[0]['snippet'],
      'title/url/snippet 三段抽取正确')
check(len(_exa._parse(_txt, 1)) == 1, 'max_results 截断生效')
check(_exa._parse('', 5) == [] and _exa._parse('Title: 无URL\n', 5) == [],
      '空文本/缺 URL 不产出条目')
check(all(len(r['snippet']) <= 300 for r in _exa._parse(_txt, 10)),
      'snippet 长度受上限约束')
# 组装参数 + 强制直连: 传入 proxy 也必须以 proxy=None 出网
_seen = {}
_orig = _exa._mc.call_tool
def _fake(url, tool, args=None, **kw):
    _seen.update(url=url, tool=tool, args=args, **kw)
    return {'text': _txt, 'is_error': False, 'raw': {}}
_exa._mc.call_tool = _fake
try:
    _rs = _exa.search('q', max_results=25, proxy='http://127.0.0.1:2080', timeout=15)
    check(_seen['tool'] == 'web_search_exa', f'调 web_search_exa ({_seen["tool"]})')
    check(_seen['args'] == {'query': 'q', 'numResults': _exa._MAX_UPSTREAM},
          f'numResults 封顶 {_exa._MAX_UPSTREAM} ({_seen["args"]})')
    check(_seen['proxy'] == 'http://127.0.0.1:2080',
      f'管线传入的代理被透传, 不再强制直连 ({_seen["proxy"]})')
    check(_seen['timeout'] >= _exa._MIN_TIMEOUT,
          f'timeout 有下限 {_exa._MIN_TIMEOUT} ({_seen["timeout"]})')
    check(len(_rs) == 2, f'search 返回解析结果 ({len(_rs)})')
finally:
    _exa._mc.call_tool = _orig
# 端点报错 / 上游错误 / 空结果 要抛, 由管线记入 errors
def _raise_err(*_a, **kw):
    return {'error': {'code': -1, 'message': 'boom'}}
for _ret, _frag in ((_raise_err, 'boom'),
                    (lambda *a, **k: {'error': {'code': 429, 'message': 'too many'}}, '429'),
                    (lambda *a, **k: {'text': '', 'is_error': False, 'raw': {}}, '空结果'),
                    (lambda *a, **k: {'text': 'x', 'is_error': True}, 'Exa 返回错误')):
    _exa._mc.call_tool = _ret
    try:
        _exa.search('q', max_results=3, timeout=15)
        check(False, f'异常路径应抛出 ({_frag})')
    except RuntimeError as e:
        check(_frag in str(e), f'异常路径抛出可读错误 ({_frag})')
    except Exception as e:
        check(False, f'异常类型应为 RuntimeError ({type(e).__name__})')
_exa._mc.call_tool = _orig
# 引擎预设: --engine > --preset > cfg.default_engines > 默认开启的引擎
from webtool.pipeline.search import resolve_engines as _RE, presets as _PS
_ps = _PS()
check(set(_ps) >= {'zh', 'en', 'direct'}, f'预设表装载 ({sorted(_ps)})')
from webtool.core.plugins import table as _TBL
_eng_tbl = _TBL('engine')
_bad = [n for n, s in _ps.items()
        if not (s.get('engines') and all(e in _eng_tbl for e in s['engines']))]
check(not _bad, f'预设引用的引擎都存在 (坏: {_bad or "无"})')
_cfg_e = {'default_engines': 'bing,sogou'}
check(_RE(_SN(engine=None, preset='zh'), _cfg_e) == ('bing,sogou,baidu,so360', 'zh'),
      '--preset 展开为引擎组')
check(_RE(_SN(engine='bing', preset='zh'), _cfg_e) == ('bing', None),
      '--engine 优先于 --preset 且不记 preset')
check(_RE(_SN(engine=None, preset=None), _cfg_e) == ('bing,sogou', None),
      '无 preset 用 cfg.default_engines')
check(_RE(_SN(engine=None, preset=None), {})[1] is None, '无任何配置时不记 preset')
try:
    _RE(_SN(engine=None, preset='__nope__'), _cfg_e)
    check(False, '未知 preset 应抛 SystemExit')
except SystemExit as e:
    check(e.code == 2, f'未知 preset 退 2 (实得 {e.code})')
# 代理策略: 端点表给 exa 声明 proxy:direct (免 key 配额按 IP 计, 走代理必 429)
from webtool.cli.mcp import _proxy_for as _PF
_cfg_proxy = {'proxy': 'http://127.0.0.1:2080'}
_a_direct = _SN(no_proxy=False)
_a_noproxy = _SN(no_proxy=True)
check(_PF({'proxy': 'direct'}, _a_direct, _cfg_proxy) == 'auto',
      '端点表 proxy 声明已废弃, 即使残留也不强制直连')
# 缺省返回 'auto', 由 net.rules 按域名/IP/端口/协议/GeoIP 路由表
# 分流 (含默认动作与全局 proxy); 不是把全局 URL 抄一遍
check(_PF({}, _a_direct, _cfg_proxy) == 'auto',
      '端点未声明 → 交路由表 (auto), 由规则决定走哪条线')
# 'direct' 是"强制直连"的约定值: None 与 'auto' 同义 (都交规则表), 拿 None
# 当强制直连会让 --no-proxy 反而回去跟全局配置走 (见 net/netx.resolve_proxy)
check(_PF({'proxy': 'direct'}, _a_noproxy, _cfg_proxy) == 'direct',
      '--no-proxy 强制直连 (用户显式意图)')
check(_PF({}, _a_noproxy, _cfg_proxy) == 'direct', '--no-proxy 覆盖全局配置')

# 13. parallel 引擎 + fetch --via 远程 reader 兜底判定
from webtool.engines import parallel as _par
from webtool.net import mcpclient as _mc
from webtool.core.plugins import table as _TBL2
_par._eng_par_spec = _TBL2('engine').get('parallel') or {}
_pspec = _mc.endpoint('parallel')
check(set((_pspec.get('verbs') or {})) >= {'search', 'fetch'},
      f'parallel 声明 search/fetch ({sorted(_pspec.get("verbs") or {})})')
check(_pspec.get('url') == 'https://search.parallel.ai/mcp', 'parallel 端点 URL 正确')
check(_par._eng_par_spec.get('entry') == 'webtool.engines.parallel:search',
      f'parallel 引擎注册到插件表 ({_par._eng_par_spec.get("entry")})')
# 双必填参数: objective 原样, search_queries 派生 2-3 个且不重复
_sqs, _obj = _par._queries('latest python 3.14 release notes')
check(_obj == 'latest python 3.14 release notes', f'objective 原样传 ({_obj!r})')
check(2 <= len(_sqs) <= 3, f'search_queries 派生 2-3 条 ({_sqs})')
check(len(set(_sqs)) == len(_sqs), 'search_queries 无重复')
_sqs2, _ = _par._queries('A股')
check(len(_sqs2) == 1, f'中文无空格 query 不硬造变体 ({_sqs2})')
# JSON 解析: publish_date 可能 null, excerpts 是数组
_pj = ('{"results":[{"url":"https://a.com","title":"甲","publish_date":null,'
       '"excerpts":["甲正文"]},{"url":"https://b.com","title":"乙",'
       '"publish_date":"2026-07-28","excerpts":["乙正文1","乙正文2"]},'
       '{"url":"https://a.com","title":"重复","excerpts":["x"]}]}')
_pparsed = _par._parse(_pj, 10)
check([r['title'] for r in _pparsed] == ['甲', '乙'], f'JSON 解析+去重 ({len(_pparsed)})')
check('publish_date' not in _pparsed[0], 'publish_date 为 null 时不塞字段')
check(_pparsed[1].get('publish_date') == '2026-07-28', '有日期则保留')
check(_par._parse('not json', 10) == [] and _par._parse('', 10) == [], '非 JSON/空文本不产出')
check(len(_par._parse(_pj, 1)) == 1, 'max_results 截断生效')
# reader 返回分派: parallel 出 JSON 需解包, exa 出 markdown 原样
from webtool.pipeline import fetch as _ft
_pr = ('{"results":[{"title":"T","excerpts":["正文A","正文B"]}]}')
check(_ft._reader_text('parallel', _pr) == '# T\n正文A\n\n正文B', 'parallel JSON 解包为正文')
check(_ft._reader_text('exa', '# 标题\n正文') == '# 标题\n正文', 'exa markdown 原样透传')
check(_ft._reader_text('parallel', 'plain text') == 'plain text', 'parallel 非 JSON 当纯文本')
check(_ft._reader_text('parallel', '') == '', '空返回得空串')
# auto 兜底只认确定性硬失败信号
_long = ('完整正文' * 40)
check(not _ft._needs_reader({'content': _long}), '正常长正文不触发 reader')
check(_ft._needs_reader({'error': 'JS-only shell page'}), 'JS 壳页触发 reader')
check(_ft._needs_reader({'content': ''}), '空正文触发 reader')
check(_ft._needs_reader({'content': '打开APP 产品功能 隐私政策 京ICP备123号'}), '导航壳触发 reader')
check(_ft._needs_reader({'content': '短'}), '过短正文触发 reader (与既有 thin 判定一致)')
check(set(_ft._VIA_CHANNELS) >= {'local', 'auto', 'parallel', 'exa', 'firecrawl'},
      f'--via 通道表 ({sorted(_ft._VIA_CHANNELS)})')

# 14. firecrawl: keyless MCP + 单字段参数 + MCP 容器形状 + scrape 解包
from webtool.engines import firecrawl as _fc
_fspec = _mc.endpoint('firecrawl')
check((_fspec.get('verbs') or {}).get('search') == 'firecrawl_search',
      'firecrawl search 映射到 firecrawl_search')
check((_fspec.get('verbs') or {}).get('fetch') == 'firecrawl_scrape',
      'firecrawl fetch 映射到 firecrawl_scrape')
_fes = _TBL2('engine').get('firecrawl') or {}
check(_fes.get('entry') == 'webtool.engines.firecrawl:search',
      f'firecrawl 引擎注册 ({_fes.get("entry")})')
# MCP 把结果裹在 data.web, REST 是裸 data 数组 —— 两种容器都要认
_fj = ('{"success":true,"data":{"web":[{"url":"https://a.com","title":"甲",'
       '"description":"甲摘要","position":1},{"url":"https://a.com","title":"重",'
       '"description":"应去重"},{"url":"https://b.com","title":"乙"}]}}')
_fp = _fc._parse(_fj, 10)
check([r['title'] for r in _fp] == ['甲', '乙'], f'data.web 容器解析+去重 ({len(_fp)})')
check(_fp[0]['snippet'] == '甲摘要' and _fp[1]['snippet'] == 'https://b.com',
      'description 作摘要, 缺失时用 url 兜底')
check([r['title'] for r in _fc._parse(_fj.replace('"web"', '"results"'), 10)] == ['甲', '乙'],
      '兼容其他容器键名')
check(len(_fc._parse(_fj, 1)) == 1, 'firecrawl max_results 截断')
check(_fc._parse('{"success":false}', 10) == [] and _fc._parse('bad', 10) == [],
      'success:false / 非 JSON 不产出')
check(_fc._items([{'url': 'x'}]) == [{'url': 'x'}], '_items 兼容裸数组(REST 形状)')
check(_ft._reader_text('firecrawl', '{"markdown":"# T\\n正文"}') == '# T\n正文',
      'firecrawl scrape 解包 markdown')
check(_ft._reader_text('firecrawl', '{"data":{"markdown":"嵌套"}}') == '嵌套',
      'firecrawl 兼容 data.markdown 嵌套')
check(_ft._reader_arg('firecrawl', 'https://x.com') == {'url': 'https://x.com'},
      'firecrawl scrape 用 url 字段(非 urls)')
check(_ft._reader_arg('parallel', 'https://x.com') == {'urls': ['https://x.com']},
      'parallel/reader 用 urls 数组')
check('firecrawl' in _ft._VIA_CHANNELS and 'firecrawl' in _ft._MCP_CHANNELS,
      'firecrawl 已进 --via 通道表')

import pathlib as _pl  # noqa: E402
import subprocess as _sp  # noqa: E402
import tempfile as _tf  # noqa: E402

# ===== 依赖声明 (2026-10-15 审计补漏: certifi / urllib3) =====
# 三件事都要锁住, 否则装完包才在某个子命令里 ImportError:
#   ① src 里 import 的第三方库必须都在 pyproject 里声明 (审计脚本判)
#   ② requirements*.txt 由 pyproject 生成, 不能各说各话
#   ③ 核心依赖里必须含运行必需的那几个 (漏了它们整个 CLI 起不来)
_rd = _pl.Path(__file__).resolve().parent.parent
_audit = _sp.run([sys.executable, str(_rd / 'scripts' / 'audit_deps.py')],
                 cwd=_rd, capture_output=True, text=True)
_miss_txt = ''
if _audit.returncode:                       # 列出缺哪些, 别只说"失败"
    _miss_txt = _audit.stdout.split('=== import 了但没声明')[1].splitlines()[1].strip()
_msg = 'src 里 import 的第三方库都已声明 (scripts/audit_deps.py)'
if _miss_txt:
    _msg += ' —— 缺: ' + _miss_txt
check(_audit.returncode == 0, _msg)
_gen = _sp.run([sys.executable, str(_rd / 'scripts' / 'gen_requirements.py'),
                '--check'], cwd=_rd, capture_output=True, text=True)
check(_gen.returncode == 0, 'requirements*.txt 与 pyproject 一致 (自动生成, 别手改)'
      + (' —— ' + _gen.stdout.strip() if _gen.returncode else ''))
try:                                   # py3.9/3.10 用 tomli 兜底
    import tomllib as _tl              # noqa: E402
except ModuleNotFoundError:            # pragma: no cover
    import tomli as _tl                # noqa: E402
with open(_rd / 'pyproject.toml', 'rb') as _f:
    _proj = _tl.load(_f)['project']
_core = ' '.join(_proj['dependencies'])
check(all(k in _core for k in ('trafilatura', 'curl_cffi', 'typer', 'pysocks',
                               'certifi')),
      '核心依赖: 装包即装 (抓取/通道/CLI/CA 四件套在内)')
check(all(k in _core for k in ('cryptography', 'maxminddb', 'requests', 'urllib3')),
      '全装是唯一形态: secrets/geoip 等依赖全部进了基座')
check('optional-dependencies' not in _proj,
      '不再有 optional-dependencies (只允许全装)')
from webtool.core import deps as _deps                         # noqa: E402
_h = _deps.install_hint('cryptography')
check('cryptography' in _h and '重装' in _h and 'webtool[' not in _h,
      '缺依赖的指引给"重装"命令, 不再指向已取消的 extras')
import webtool.core.uninstall as _un                            # noqa: E402
for _mode, _need in (('pipx', 'pipx'), ('venv', 'pip'),
                     ('system', 'pipx'), ('editable', 'pip')):
    _orig = _un.install_mode
    _un.install_mode = lambda m=_mode: (m, '', '')
    try:
        _t = _deps.install_hint('cryptography')
    finally:
        _un.install_mode = _orig
    check(_need in _t and 'pip install "webtool[' not in _t,
          '装法 %s 给对命令 (%s)' % (_mode, _t.split('重装: ')[-1]))

# Termux/Android: PyPI 没有 android 轮子, cryptography 只能构建
# (cryptography 还要 Rust), 让他"重装 webtool"就是让他原地打转。
check(_deps.on_termux() is False, '沙箱不是 Termux: 判定不许误报')
_o_termux = _deps.on_termux
_deps.on_termux = lambda: True
try:
    _tc = _deps.install_hint('cryptography')
    check('pkg install python-cryptography' in _tc and '重装' not in _tc,
          'Termux: 缺 cryptography 指 pkg install, 不说"重装 webtool"')
finally:
    _deps.on_termux = _o_termux

# ---------- 正文提取: 内容层择优 + 碎片率 ----------
from webtool.engines import extractors as _ex
from webtool.engines import boilerplate as _bo

_et = plugins.table('extractor')
for _n in ('trafilatura', 'readability', 'boilerplate', 'inscriptis'):
    check(_n in _et, f'提取器注册表含 {_n}')
check(_et['inscriptis'].get('dump') is True, '整页 dump 的提取器被标成兜底层')
check(not _et['boilerplate'].get('dump'), '新提取器在内容层 (参与择优)')

# 碎片率: 正文是一条条句子, 推广/导航是一地碎片
_prose = '石油概念震荡反弹，和顺石油涨停。广汇能源、中国石油等跟涨。'
_junk = '\n'.join(['方便，快捷', '手机查看财经快讯', '微信扫一扫', '分享到您的',
                   '朋友圈', '扫描二维码关注'])
check(_ex.fragment_ratio(_prose) == 0, '正常正文碎片率为 0')
check(_ex.fragment_ratio(_junk) > 0.7, '推广碎片堆碎片率高')
check(_ex.fragment_ratio('') == 1, '空产出碎片率算满 (不会赢)')
check(_ex.fragment_ratio('---\ntitle: x\n---\n') == 1, 'YAML 头不算正文 (先剥掉)')

# pick_best: 干净和完整要一起算账
check(_ex.pick_best([('脏', _junk), ('净', _prose)]) == '净', '择优选干净的')
_long_dirty = ('这是一段正文，' * 40) + _junk          # 长而略脏
_short_clean = '正文一句话。'
check(_ex.pick_best([('长脏', _long_dirty), ('短净', _short_clean)]) == '长脏',
      '择优不为了干净把长正文丢掉')
check(_ex.pick_best([]) == '', '没有候选不炸')

# 无 lxml 平台的兜底: 纯标准库也要能把文章区从导航/推广里切出来
_page = ('<html><head><title>标题</title></head><body>'
         '<div class="nav"><a href="/a">财经</a><a href="/b">股票</a></div>'
         '<div class="article"><p>石油概念震荡反弹，和顺石油涨停。'
         '广汇能源、中国石油等跟涨，板块成交额明显放大。</p></div>'
         '<div class="qrapp"><p>方便，快捷</p><p>手机查看财经快讯</p>'
         '<p>微信扫一扫</p><p>分享到您的朋友圈</p></div>'
         '<div class="comment"><p>网友评论：沙发</p></div>'
         '</body></html>')
_bt, _ = _bo.extract_boilerplate(_page, 'http://x.test/a', {})
check('和顺石油涨停' in _bt, 'readability 算法能切出正文')
check('微信扫一扫' not in _bt and '方便，快捷' not in _bt,
      'readability 算法甩掉推广块 (没有关键词表)')
check(len(_bt) < 120, f'切出来的就是那一段 ({len(_bt)} 字)')

_rt, _rm = _ex.run_chain(_page, 'http://x.test/a', {})
check(_rm.get('_via') in _et, f'run_chain 交代价提取器名 (_via={_rm.get("_via")})')
check('和顺石油涨停' in _rt, 'run_chain 产出含正文')
check('微信扫一扫' not in _rt, 'run_chain 产出不含推广碎片')

# 提取器可配置 (--extract / config extract), 默认 auto = 内容层择优
from webtool.net import proxy as _prx
from webtool.cli.config import CONFIG_KEYS as _CK

check(_ex.MODES[0] == 'auto', 'MODES 第一个是 auto (默认值)')
check(set(_ex.MODES) - {'auto'} <= set(_et), 'MODES 里的名字都在提取器注册表里')
check('extract' in _prx.DEFAULTS,
      'extract 登记进 DEFAULTS (没登记会被 load_config 过滤掉, 配置等于没写)')
check('extract' in _CK and 'auto' in _CK['extract'][1],
      'config set extract 有白名单校验 (合法值写在提示里)')
check(_ex.resolve_mode(None) == 'auto' and _ex.resolve_mode('') == 'auto',
      '空配置 = auto')
check(_ex.resolve_mode('  READability ') == 'readability', '名字大小写/空格容忍')
check(_ex.resolve_mode('nosuch') == 'auto', '配置写错名字退回 auto, 不炸')

_t2, _m2 = _ex.run_chain(_page, 'http://x.test/a', {}, mode='inscriptis')
check(_m2.get('_via') == 'inscriptis', '指定提取器就用指定的那个')
# 比正文长度, 不比整串: auto 那条带 YAML 元数据头, 直接比长度其实在比头
check(len(_ex.strip_front_matter(_t2)) > len(_ex.strip_front_matter(_rt)),
      '整页 dump 指定了也给 (比择优链长)')
_t3, _m3 = _ex.run_chain(_page, 'http://x.test/a', {}, mode='boilerplate')
check(_m3.get('_via') == 'boilerplate', '指定 boilerplate 生效')
check('微信扫一扫' not in _t3, '指定的那个照样干净')

# -f txt 要真的是纯文本: 以前只抹 [文字](url), ## 和 ** 会原样留下
from webtool.core import text as _tx

check(_tx.md_to_text('## 标题\n\n**重点**和[链接](http://a/b)。') == '标题\n\n重点和链接。',
      'txt 模式抹掉 ## 与 **')
check(_tx.md_to_text('| 姓名 | 年龄 |\n|---|---|\n| 张三 | 30 |') == '姓名 年龄\n\n张三 30',
      '表格转空格分隔 (竖线不留)')
check(_tx.md_to_text('![封面图](http://a/i.png)\n\n正文。') == '封面图\n\n正文。',
      '图片保留 alt 文字')
check(_tx.md_to_text('a*b*c 与 snake_case 与 *斜体*') == 'a*b*c 与 snake_case 与 斜体',
      '别误伤 a*b*c / snake_case')
_fm = '---\ntitle: X\nurl: http://x\n---\n# 正文标题\n\n内容。'
check(_tx.md_to_text(_fm) == '---\ntitle: X\nurl: http://x\n---\n正文标题\n\n内容。',
      'YAML 元数据头原样保留 (含 --- 分隔线)')
check(_tx.md_to_text(_fm, keep_meta=False) == '正文标题\n\n内容。',
      'keep_meta=False: 连元数据头一起去掉 (-f txt 的用法)')
check(_tx.md_to_text(r'合作（\[email protected\] 见 [文档](https://a.com/x)）。')
      == '合作（[email protected] 见 文档）。',
      '标签里转义方括号的链接也能抹 (不然 [..](..) 原样留下)')
check(_tx.md_to_text(r'价格 \*literally\* 与 a*b*c') == '价格 *literally* 与 a*b*c',
      '转义星号还原成字面星号, 不当强调吃')

# --raw 的产出在 'html' 键上, 各格式都得认得 (以前只有 json 分支认, 默认 md/txt
# 打出个空行还退出码 0)
import io as _io
import contextlib as _ctx
from webtool.pipeline import fetch as _ft


class _A:
    format = 'md'
    raw = True


_a = _A()
_buf = _io.StringIO()
with _ctx.redirect_stdout(_buf):
    _ft._emit({'url': 'u', 'status': 200, 'via': 'local', 'took_ms': 1,
               'html': '<html>x</html>'}, _a, True)
check('<html>x</html>' in _buf.getvalue(), '--raw 在默认 (md) 格式下真的输出 HTML')

_a.format = 'text'
_buf = _io.StringIO()
with _ctx.redirect_stdout(_buf):
    _ft._emit({'url': 'u', 'status': 200, 'via': 'local', 'took_ms': 1,
               'html': '<html>x</html>'}, _a, True)
check('<html>x</html>' in _buf.getvalue(), '--raw 在 txt 格式下也输出 HTML (不抹标签)')

_a.format = 'json'
_buf = _io.StringIO()
with _ctx.redirect_stdout(_buf):
    _ft._emit({'url': 'u', 'status': 200, 'via': 'local', 'took_ms': 1,
               'html': '<html>x</html>'}, _a, True)
check('"html"' in _buf.getvalue(), '--raw 在 json 格式下带 html 字段')

# 非 raw 路径不受影响
_a.raw = False
_a.format = 'md'
_buf = _io.StringIO()
with _ctx.redirect_stdout(_buf):
    _ft._emit({'url': 'u', 'content': '## 标题\n\n正文。', 'chars': 6,
               'cache': 'miss'}, _a, True)
check('## 标题' in _buf.getvalue(), 'md 格式保留 markdown')
_a.format = 'text'
_buf = _io.StringIO()
with _ctx.redirect_stdout(_buf):
    _ft._emit({'url': 'u', 'content': '## 标题\n\n正文。', 'chars': 6,
               'cache': 'miss'}, _a, True)
check('##' not in _buf.getvalue() and '标题' in _buf.getvalue(), 'txt 格式抹掉标记')

# -f txt 的前面不该再顶一段机器头
_a.format = 'text'
_a.raw = False
_buf = _io.StringIO()
with _ctx.redirect_stdout(_buf):
    _ft._emit({'url': 'u', 'content': _fm, 'chars': 30, 'cache': 'miss'}, _a, True)
check('title:' not in _buf.getvalue() and '正文标题' in _buf.getvalue(),
      '-f txt 输出不含 YAML 元数据头')


# --- 目标类型判定: fetch 不能拿图片/压缩包当网页提取 ---------------------------
_tk = _ft.target_kind
check(_tk('text/html; charset=utf-8') == ('html', 'text/html'), 'text/html 认成网页')
check(_tk('application/xhtml+xml')[0] == 'html', 'xhtml 也认成网页')
check(_tk('image/png') == ('image', 'image/png'), 'Content-Type 认图片')
check(_tk('video/mp4')[0] == 'video', 'Content-Type 认视频')
check(_tk('application/zip') == ('archive', 'application/zip'), 'Content-Type 认压缩包')
check(_tk('application/pdf')[0] == 'pdf', 'Content-Type 认 PDF')
check(_tk('application/json') == ('text', 'application/json'),
      'json 当文本原样给 (不是网页, 别去提取)')
check(_tk('text/plain')[0] == 'text', 'text/plain 当文本')
check(_tk('application/octet-stream', 'http://x/a.mp4') == ('binary', 'application/octet-stream'),
      '服务端只说 octet-stream 时不看扩展名硬猜 (头比扩展名可信)')
check(_tk('', 'http://x/pic/a.JPG') == ('image', 'image/jpeg'),
      '头里没类型就看扩展名, 大小写无关')
check(_tk('', 'http://x/archive.zip')[0] == 'archive', '没头也没扩展名... 这条是 zip')
check(_tk('', 'http://x/news/123') == ('html', ''),
      '头里没类型也没认得的扩展名: 按网页处理 (不能因为对方不报头就放弃提取)')

# 落盘文件名: URL 末段说了算 (后缀跟 URL 一致), 没末段才看 CD / MIME
check(_ft._filename_for({}, 'http://x/y/logo.png') == 'logo.png', 'URL 末段就是文件名')
check(_ft._filename_for({'content-disposition': 'attachment; filename="报告.pdf"'},
                        'http://x/') == '报告.pdf',
      'URL 没末段才轮到 Content-Disposition')
check(_ft._filename_for({'content-disposition': 'attachment; filename="a.png"'},
                        'http://x/y/b.zip') == 'b.zip',
      'URL 有末段时 CD 不许抢: 后缀必须跟 URL 走')
check(_ft._filename_for({}, 'http://x/a/b/') == 'b', '路径以斜杠结尾: 取上一段')
check(_ft._filename_for({}, 'http://x/') == 'download',
      '连末段都没有才叫 download (别写出个空文件名)')
check(_ft._filename_for({}, 'http://x/d?v=2') == 'd',
      '查询串不算文件名 (?v= 不许写进名字)')
check(_ft._filename_for({}, 'http://x/pkg.tar.gz') == 'pkg.tar.gz',
      '双后缀照留 (猜 MIME 只会给出 .gz 半截)')
check(_ft._filename_for({}, 'http://x/img', 'image/png') == 'img.png',
      'URL 连后缀都没有: 才按 MIME 补')

# 落点: --save 给目录就按 URL 末段取名, 给文件名就用它, 没给存当前目录
check(_ft._dest_path(_SN(save=None), 'http://x/y/logo.png') == './logo.png',
      '没给 --save: 存当前目录, 名字按 URL')
check(_ft._dest_path(_SN(save='/tmp/wt_save_test'), 'http://x/y/logo.png')
      == '/tmp/wt_save_test/logo.png', '--save 给已存在的目录: 拼名字')
check(_ft._dest_path(_SN(save='/tmp/nope.png'), 'http://x/y/logo.png') == '/tmp/nope.png',
      '--save 给的是文件路径: 就用它 (哪怕后缀不一样)')

# 文本类目标: 原样给, 不提取
_args = _SN(save=None, max_chars=0, format='md')
_r = _ft._text_result('http://x/a.json', '{"a": 1}'.encode(), 200, 'cffi',
                      {'content-type': 'application/json'}, 'text',
                      'application/json', _args, 0)
check(_r['content'] == '{"a": 1}' and _r['extract'] == 'raw-text',
      'json 目标原样给正文, 不提取')
check(_r['size'] == 8 and 'file' not in _r, '文本目标不当文件存 (它就是正文)')
_r = _ft._text_result('http://x/a.json', b'x' * 99, 200, 'cffi',
                      {'content-type': 'application/json', 'content-length': '9999'},
                      'text', 'application/json', _args, 0)
check(_r.get('truncated') is True and _r['size_declared'] == 9999,
      '文本被单次上限截了要标 truncated')
_r = _ft._text_result('http://x/a.txt', b'x' * 99, 200, 'cffi',
                      {'content-type': 'text/plain'}, 'text', 'text/plain',
                      _SN(save=None, max_chars=10, format='md'), 0)
check(_r['content'].startswith('x' * 10) and 'truncated' in _r['content'],
      '--max-chars 给了就按它截 (0 才是不截断: [:0] 会切空, 早先真出过这毛病)')

# 下载结果 → fetch 结果形状 (二进制不进正文, 落点/续传信息照带)
_r = _ft._file_result('http://x/l.png',
                      {'file': '/tmp/l.png', 'size': 12, 'resumed_from': 500,
                       'status': 206, 'via': 'cffi'}, 'image', 'image/png', 200, 'cffi', 0)
check(_r['file'] == '/tmp/l.png' and _r['size'] == 12 and _r['resumed_from'] == 500,
      '下载结果折进 fetch 结果: 落点/大小/续传起点都带出来')
check(_r['kind'] == 'image' and _r['extract'] == 'raw-binary'
      and 'content' not in _r and 'html' not in _r,
      '二进制结果里不许出现 content/html 字段')
check(_r['status'] == 206, '下载时的状态码 (206=续传) 要顶掉判类型那次的')
_r = _ft._file_result('http://x/l.png', {'error': 'HTTP 404 Not Found'},
                      'image', 'image/png', 404, 'cffi', 0)
check(_r.get('error') == 'HTTP 404 Not Found' and 'file' not in _r,
      '下载失败: 只报错, 不给落点 (没存就不许说存了)')

# 终端上不许把二进制糊出来
_r2 = _ft._file_result('http://x/l.png', {'file': '/tmp/l.png', 'size': 12},
                       'image', 'image/png', 200, 'cffi', 0)
_o, _e = _io.StringIO(), _io.StringIO()
with _ctx.redirect_stdout(_o), _ctx.redirect_stderr(_e):
    _ft._emit(_r2, _SN(format='text', raw=False, with_metadata=False), True)
check(_o.getvalue() == '', '二进制目标: stdout 一个字节都不许有')
check('image/png' in _e.getvalue() and '已存' in _e.getvalue(),
      '二进制目标走 stderr 说明是什么、存哪了 (管道里不能掺垃圾)')

# --save: 网页与二进制共用一个出口 (存的就是原始响应体)
_LOGO = b'\x89PNG\r\n\x1a\n' + bytes(range(256)) * 4
_DEST = '/tmp/wt_save_test'
os.makedirs(_DEST, exist_ok=True)
_p = _ft._save_body(_SN(save=_DEST), 'http://x/logo.png', _LOGO,
                    {'content-type': 'image/png'})
check(os.path.basename(_p) == 'logo.png' and open(_p, 'rb').read() == _LOGO,
      '--save 给目录: 写原始字节, 名字按 URL')
check(_ft._save_body(_SN(save=None), 'http://x/a', b'x', {}) == '',
      '没给落点也不该默认存 (网页路径只认 --save, 自动落盘是二进制的事)')
check(_ft._save_body(_SN(save='/tmp/'), 'http://x/p', '文'.encode(), {}) == '/tmp/p',
      '--save 给目录路径时存原始名字')
check(_ft._save_body(_SN(save=_DEST), 'http://x/l.png', _LOGO, {}, status=404) == '',
      '404 不落盘 (存下来的会是那页错误信息)')

print('\n=== 15. 配置键只有一张表 (config set 写了要真生效) ===')
# 起因: `ua` 能写能存没人读; `cache`/`default_format` 键在 cli/config.py 的键表
# 里、却不在 net.proxy.store 的 _KNOWN 白名单里, 被 load_config 静默过滤;
# `default_engines`/`market`/`cache_ttl.*` 同样是"set 得进、读不回来" ——
# 用户配了没反应, 排查时还以为是代码 bug。
# 现在两张表都从 core/config_schema.py 派生 (structural: 不可能再漂), 检查从
# "两个键表对齐" 换成"两个键表确实派生自唯一来源 + 没有漏网的例外"。
import re as _re2
import json as _json15
from webtool.net.proxy.store import DEFAULTS as _DEF
from webtool.cli.config import CONFIG_KEYS as _CKEYS
_SRCW = _pl.Path(__file__).parent.parent / 'src'
_SKIPCFG = {'net/proxy/store.py', 'cli/config.py'}
_RUNTIME_ONLY = {'proxy'}          # cli/_ctx 运行时注入的, 不落盘
_READPAT = _re2.compile(
    r"\b(?:cfg|config|_cfg|conf)\s*\.get\(\s*['\"]([a-z_][a-z_0-9.]*)['\"]"
    r"|\b(?:cfg|config|_cfg|conf)\s*\[\s*['\"]([a-z_][a-z_0-9.]*)['\"]\s*\]")
# 这个扫描是纯文本的, 分不出一个 `cfg` 来自哪个配置文件。而 data/*.json 里的段
# 也是经 load(段, 文件) 拿的, 长得跟 config.json 一模一样 —— 于是
# pipeline/merge.py 从 **filters.json 的 merge 段** 读 low_prior/ref_hosts,
# 被当成了 config.json 的键, 为了"对齐"把那三个键塞进了 store.DEFAULTS
# (d8c341f)。后果是 config.json 白收三个没人读的键: 用户写进去 load_config
# 原样返回, 而唯一的消费方读的是另一个文件 —— 零效果、零警告。
#
# 归属规则: 读它的文件加载了某个 data 段、且那个段声明了这个键, 同时该文件
# 没碰 load_config() (碰了就不能断定那个 cfg 不是来自 config.json) → 归 data 文件。
_LOADPAT = _re2.compile(r"load\(\s*'([a-z]+)'\s*,\s*'([\w.]+\.json)'")
_HASCFG = _re2.compile(r"\bload_config\(\)")


def _data_section(fn, sec):
    """包内 data/<fn> 的 sec 段 (读不到/不是对象 → None, 归属失败)"""
    _p = _SRCW / 'webtool' / 'data' / fn
    try:
        _d = _json15.loads(_p.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return _d.get(sec) if isinstance(_d, dict) and isinstance(_d.get(sec), dict) else None


_read_keys, _data_owned = set(), {}
for _f in _SRCW.rglob('*.py'):
    _rel = str(_f.relative_to(_SRCW)).replace('\\', '/')
    if _rel in _SKIPCFG:
        continue
    _txt = _f.read_text(encoding='utf-8')
    _keys = {_m.group(1) or _m.group(2) for _m in _READPAT.finditer(_txt)}
    if not _keys:
        continue
    _loads = {(_s, _fn) for _s, _fn in _LOADPAT.findall(_txt) if _fn != 'config.json'}
    _may_cfg = bool(_HASCFG.search(_txt))
    for _k in _keys:
        _owner = next((('%s#%s' % (_fn, _s))
                       for _s, _fn in sorted(_loads)
                       if (_sec := _data_section(_fn, _s)) and _k in _sec), None)
        if _owner and not _may_cfg:
            _data_owned.setdefault(_owner, set()).add(_k)
        else:
            _read_keys.add(_k)
check(all(k not in _DEF for ks in _data_owned.values() for k in ks),
      '从 data 文件读的键不在 config.json 白名单里 (白收 = 配了没反应): '
      + ('; '.join('%s: %s' % (o, ','.join(sorted(ks)))
                   for o, ks in sorted(_data_owned.items())) or 'ok'))
_unreadable = sorted(_read_keys - set(_DEF) - _RUNTIME_ONLY)
check(not _unreadable,
      '业务读的配置键都在白名单里 (否则被 load_config 静默过滤): '
      + (', '.join(_unreadable) or 'ok'))

_unwritable = sorted({k.split('.')[0] for k in _CKEYS} - set(_DEF))
check(not _unwritable,
      'config set 能写的键都读得回来 (否则写了白写): '
      + (', '.join(_unwritable) or 'ok'))

# 派生关系本身要钉住: 两侧都从唯一来源投影, 而不是各自维护一份再对齐
from webtool.core import config_schema as _SCHEMA
check(_DEF == dict(_SCHEMA.DEFAULTS),
      'store.DEFAULTS 就是 schema.DEFAULTS (键表没有第二份)')
check(_CKEYS == _SCHEMA.cli_table(),
      'cli.CONFIG_KEYS 就是 schema.cli_table() (说明/提示没有第二份)')
# 不给 CLI 入口的键是**例外**, 不是默认: 新增一个必须在这里说清为什么
_NO_CLI = {k for k, v in _SCHEMA.KEYS.items() if not v.cli}
check(_NO_CLI == {'cache_ttl', 'proxy_auth'},
      '不进 CLI 键表的键就那两个 (复合键 + 密文), 没有漏网的例外: '
      + (', '.join(sorted(_NO_CLI)) or 'ok'))

_dead_cfg = []
for _k in sorted(_DEF):
    _pat = _re2.compile(r"\[['\"]%s['\"]\]|get\(\s*['\"]%s['\"]" % (_k, _k))
    _read = any(_pat.search(_f.read_text(encoding='utf-8'))
                for _f in _SRCW.rglob('*.py')
                if str(_f.relative_to(_SRCW)).replace('\\', '/') not in _SKIPCFG)
    if not _read:
        _dead_cfg.append(_k)
check(not _dead_cfg, 'config.json 每个键都有人读 (死键 = 用户配了没反应): '
      + (', '.join(_dead_cfg) or 'ok'))

print('\n=== 16. 日志文案必须能一眼定位来源 (格式守卫) ===')
# 排查时要在几十上百行里扫线索, 无主语的"忽略异常 (容忍路径)"等于没写 ——
# 你只知道"某处吞了异常", 不知道哪一层、为什么。统一成
# `<模块> | 动作 对象 key=value`, 便于 grep、便于肉眼扫、便于 JSONL 归类。
_LOGRE = _re2.compile(r"logger\.(debug|info|warning|error)\(\s*(?:f)?"
                      r"(?:'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\")")
_bad_log = []
for _f in _SRCW.rglob('*.py'):
    for _m in _LOGRE.finditer(_f.read_text(encoding='utf-8')):
        _msg = _m.group(2) or _m.group(3)
        if not _re2.match(r'^[a-z][a-z0-9_]* \| ', _msg):
            _bad_log.append(f'{_f.relative_to(_SRCW)}: {_msg[:40]}')
check(not _bad_log, '日志文案统一成 "<模块> | ..." (否则排查时无从定位): '
      + (str(_bad_log[:3]) if _bad_log else 'ok'))

print('\n=== 17. 日志行必须能对齐时间/定位文件/分辨线程 (格式守卫) ===')
# 光有消息体不够: 并发抓引擎时两行会串成一件事 (缺线程名), 事后翻盘又分不清
# 先后 (缺毫秒), 定位还得再搜一遍代码 (缺文件:行号)。三样必须都在格式里。
import webtool.core.logging as _logmod
import logging as _logging2
_fmt_fields = ('%(asctime)s', '%(msecs)', '%(threadName)s',
               '%(filename)s', '%(lineno)d')
check(all(f in _logmod._FMT for f in _fmt_fields),
      '终端日志格式含 时间/毫秒/线程/文件/行号: ' + str(_logmod._FMT))
check(all(f in _logmod._FILE_FMT for f in _fmt_fields),
      '文件日志格式含 时间/毫秒/线程/文件/行号: ' + str(_logmod._FILE_FMT))
_ev = _logmod._JsonFmt().format(_logging2.LogRecord(
    'webtool.x', _logging2.WARNING, 'x.py', 9, 'x | 事件', None, None))
check(all(k in _ev for k in ('"thread"', '"file"', '"ts"', '"msg"')),
      'JSONL 事件含 ts/thread/file/msg: ' + _ev)

print('\n=== 18. --no-url 去链接必须三格式同时生效 (rank/feed 共用) ===')
# 链接藏在 url 字段里, 渲染层三处各写一遍"有 url 就出链接" —— 所以去掉
# url 字段就等于三种格式一起生效 (json 无字段 / md 退化成纯标题 / text 少一行)。
# 这里锁住这个前提: 谁哪天把 md 改成无条件读 url, 这条会红。
from webtool.render.hotrender import strip_urls
_out = {'cmd': 'rank', 'results': [{'title': 'a', 'url': 'u1', 'rank': 1}],
        'sources_data': {'zhihu': [{'title': 'b', 'url': 'u2'}],
                         'weibo': [{'title': 'c'}]},
        'errors': {'x': 'boom'}}
strip_urls(_out)
check('url' not in _out['results'][0], 'results 里的 url 被摘掉')
check('url' not in _out['sources_data']['zhihu'][0],
      'sources_data 每个源都摘掉')
check(_out['sources_data']['weibo'][0] == {'title': 'c'},
      '本来就没 url 的条目不受影响')
check(_out['errors'] == {'x': 'boom'}, '非条目字段 (errors) 不动')
check(_out.get('no_url') is True,
      '留 no_url 标记 (链接是被要求去掉的, 不是源里没有)')

print('\n=== 20. 运行必需的数据不许落在项目外 (AST 扫常量) ===')
# 出过一次: 交易日历读项目外的 shared/短线复盘/*.json, 本地跑得通, 换机器
# 静默降级成"只按周末判交易日"。这类依赖的共同长相是"代码里写死的仓外路径",
# 所以用 AST 扫字符串常量 (跳过 docstring —— 文档里提一句旧路径不算依赖),
# 只放行用户目录 (~/.webtool 是用户数据) 与临时目录 (/tmp 是进程内中转)。
import ast as _ast2
_EXTERNAL_BAD = ('/var/minis', 'site-packages', '/usr/lib')
_EXTERNAL_OK = ('~/.webtool', '/tmp/')
_ext_hits = []
# 扫运行时代码 + 仓库脚本 (tests/ 不扫: 测试里造 /usr/lib/... 这类假路径是
# 正常的替身手法, 不是依赖)
_ext_files = sorted(_SRCW.rglob('*.py'))
_ext_files += sorted((_pl.Path(__file__).resolve().parents[1] / 'scripts').glob('*.py'))
for _f in _ext_files:
    try:
        _tree = _ast2.parse(_f.read_text(encoding='utf-8'))
    except SyntaxError:
        continue
    _docs = set()
    for _n in _ast2.walk(_tree):
        if isinstance(_n, (_ast2.Module, _ast2.ClassDef, _ast2.FunctionDef,
                           _ast2.AsyncFunctionDef)):
            _b = getattr(_n, 'body', None) or []
            if _b and isinstance(_b[0], _ast2.Expr) and \
                    isinstance(_b[0].value, _ast2.Constant) and \
                    isinstance(_b[0].value.value, str):
                _docs.add(id(_b[0].value))
    for _n in _ast2.walk(_tree):
        if not isinstance(_n, _ast2.Constant) or not isinstance(_n.value, str):
            continue
        if id(_n) in _docs:
            continue
        _v = _n.value
        if any(b in _v for b in _EXTERNAL_BAD) and not any(o in _v for o in _EXTERNAL_OK):
            try:
                _rel = _f.relative_to(_SRCW)
            except ValueError:                  # scripts/ 下的 (不在 src 内)
                _rel = _f.name
            _ext_hits.append(f'{_rel}:{_n.lineno} {_v[:60]}')
check(not _ext_hits,
      '代码常量里没有仓外路径 (有就换机器挂/静默降级): ' + str(_ext_hits[:3]))

print('\n=== 21. 各测试脚本的 check() 参数顺序统一 (AST 扫调用点) ===')
# 出过一次: 21 个脚本写 check(说明, 条件), 8 个写 check(条件, 说明), 同一个名字两套
# 顺序, 看的人得先翻定义。统一成 check(条件, 说明, detail='') 后, 最大的坑是漏搬
# 某个调用点 —— 如果那个脚本的 check() 体用 f-string 打印, 传反了也不报错, 只会
# 永远 PASS (说明文字是字符串, 恒真)。所以专门扫: 第一位不许是说明文字。
_MSG_BAD = 0
_tests_dir = _pl.Path(__file__).resolve().parent
for _f in sorted(_tests_dir.glob('test_*.py')):
    _t = _ast2.parse(_f.read_text(encoding='utf-8'))
    for _n in _ast2.walk(_t):
        if not (isinstance(_n, _ast2.Call) and getattr(_n.func, 'id', '') == 'check'):
            continue
        if not _n.args:
            continue
        _a0 = _n.args[0]
        _looks_like_msg = (
            (isinstance(_a0, _ast2.Constant) and isinstance(_a0.value, str))
            or isinstance(_a0, _ast2.JoinedStr)
            or (isinstance(_a0, _ast2.BinOp) and isinstance(_a0.op, _ast2.Mod)))
        if _looks_like_msg:
            _MSG_BAD += 1
            print('   %s:%d 第一位是说明文字' % (_f.name, _n.lineno))
check(_MSG_BAD == 0, 'check() 第一位一律是条件 (说明文字排第二): %d 处不符' % _MSG_BAD)

print('\n=== 22. 没人认的配置键: 看得见、删得掉 ===')
# store.load_config 会把 config.json 里不认识的键静默丢掉, 并每次启动刷一条警告。
# 只报不列, 用户就永远删不掉它 —— 老版本留下的死键 (ua / cafile 这类) 表现成
# "我明明配了却不生效", 而 config set 又拒绝未知键, 想删都不知道键叫什么。
# 所以三件事要齐: list 列得出来、警告里给得出删除命令、unset 删得掉。
import json as _json22
with _tf.TemporaryDirectory() as _td22:
    _env22 = dict(os.environ, WEBTOOL_DIR=_td22)
    _cfg22 = os.path.join(_td22, 'config.json')
    with open(_cfg22, 'w', encoding='utf-8') as _f22:
        _json22.dump({'ua': 'curl/8', 'cafile': '/etc/ssl/x.pem'}, _f22)

    def _cli22(*a):
        return _sp.run([sys.executable, '-m', 'webtool', *a], env=_env22,
                       capture_output=True, text=True)

    _r22 = _cli22('config', 'list')
    _o22 = _r22.stdout
    check('ua' in _o22 and 'cafile' in _o22 and '没人认的键' in _o22,
          'config list 把没人认的键列出来 (不列就删不掉)', _o22[-300:])
    check('webtool config unset ua' in _o22,
          '每个死键后面跟着怎么删 (照抄即用)', _o22[-300:])
    _w22 = _cli22('config', 'get', 'ca_bundle').stderr
    check('键不在白名单' in _w22 and 'config unset' in _w22 and 'config.json' in _w22,
          '警告要说清: 哪个文件、键叫什么、怎么删', _w22[-300:])
    check(_cli22('config', 'set', 'cache_ttl.<bucket>', '30').returncode == 2,
          '照抄帮助里的占位符当桶名 → 当场拒绝 (否则写进命不中的桶)')
    check(_cli22('config', 'set', 'cache_ttl.hot', '30').returncode == 0,
          '真桶名照写不误 (cache_ttl.hot)')
    check(_cli22('config', 'unset', 'ua').returncode == 0
          and _cli22('config', 'unset', 'cafile').returncode == 0,
          'unset 能删掉这些没人认的键')
    _o22b = _cli22('config', 'list').stdout
    _w22b = _cli22('config', 'get', 'ca_bundle').stderr
    check('没人认的键' not in _o22b and '键不在白名单' not in _w22b,
          '删干净后: list 不再列、警告不再刷', _o22b[-200:] + _w22b[-200:])

# 帮助页里的数量文案必须和注册表一致 (硬编码最易漂)
from webtool.cli import fastpath as _fp                              # noqa: E402
from webtool.core import plugins as _plugins                        # noqa: E402
import re as _re                                                     # noqa: E402
_m_site = _re.search(r'(\d+) 个站点', _fp.HELP)
_m_hot = _re.search(r'(\d+) 个榜单源', _fp.HELP)
check(bool(_m_site) and int(_m_site.group(1)) == len(_plugins.table('site')),
      '帮助页站点数与插件表一致')
check(bool(_m_hot) and int(_m_hot.group(1)) == len(_plugins.table('hot')),
      '帮助页榜单源数与插件表一致')

if fails:
    sys.exit(1)
print('ALL PASS')
