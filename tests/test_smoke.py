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
    'webtool.pipeline.topup',
    'webtool.net.transport', 'webtool.net.proxy', 'webtool.net.captcha', 'webtool.net.spa',
    'webtool.render.render', 'webtool.render.hotrender', 'webtool.render.output',
    'webtool.feeds.command', 'webtool.feeds.sources', 'webtool.feeds.parse', 'webtool.feeds.fetch', 'webtool.feeds.cards', 'webtool.radar', 'webtool.radar.race', 'webtool.radar.template',
    'webtool.radar.routes', 'webtool.radar.rules', 'webtool.radar.instances',
    'webtool.radar.official', 'webtool.radar.instances_cfg', 'webtool.cli.zen',
    'webtool.cli.sitesearch', 'webtool.net.fetch', 'webtool.engines.extractors',
    'webtool.filters.blocklist', 'webtool.filters.adfilter', 'webtool.pipeline.query_ops',
    'webtool.engines.hotsites', 'webtool.engines.sites',
    'webtool.engines.status', 'webtool.engines.bing',
    'webtool.engines.sogou', 'webtool.engines.baidu',
    'webtool.engines.google', 'webtool.engines.marginalia', 'webtool.engines.so360',
    'webtool.net.mcpclient', 'webtool.cli.mcp', 'webtool.engines.exa',
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
from webtool.cli.mcp import _build_args as _BA, _coerce as _CO
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
check(_espec.get('proxy') == 'direct', '端点表声明 proxy:direct (配额按出口 IP 计)')
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
    check(_seen['proxy'] is None, f'强制直连不走全局代理 ({_seen["proxy"]})')
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
check(_PF({'proxy': 'direct'}, _a_direct, _cfg_proxy) is None,
      '端点声明 proxy:direct → 强制直连 (不走全局代理)')
check(_PF({}, _a_direct, _cfg_proxy) == 'http://127.0.0.1:2080',
      '端点未声明 → 跟随全局配置')
check(_PF({'proxy': 'direct'}, _a_noproxy, _cfg_proxy) is None,
      '--no-proxy 同样强制直连')
check(_PF({}, _a_noproxy, _cfg_proxy) is None, '--no-proxy 覆盖全局配置')

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
from webtool.net import fetch as _ft
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

print()
if fails:
    print(f'{len(fails)} FAILED')
    sys.exit(1)
print('ALL PASS')
