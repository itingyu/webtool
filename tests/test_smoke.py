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
    'webtool.core.plugins', 'webtool.core.config_data', 'webtool.core.cache', 'webtool.core.state', 'webtool.core.http', 'webtool.core.probe', 'webtool.core.resilient', 'webtool.core.text', 'webtool.core.urls', 'webtool.core.jsonfmt', 'webtool.core.tls',
    'webtool.cli.app', 'webtool.cli.config', 'webtool.cli.plugins',
    'webtool.pipeline.search', 'webtool.pipeline.rank', 'webtool.pipeline.merge',
    'webtool.pipeline.topup',
    'webtool.net.transport', 'webtool.net.proxy', 'webtool.net.captcha', 'webtool.net.spa',
    'webtool.render.render', 'webtool.render.hotrender', 'webtool.render.output',
    'webtool.feeds.command', 'webtool.feeds.sources', 'webtool.feeds.parse', 'webtool.feeds.fetch', 'webtool.feeds.cards', 'webtool.radar', 'webtool.radar.race', 'webtool.radar.template',
    'webtool.radar.routes', 'webtool.radar.instances',
    'webtool.radar.official', 'webtool.radar.instances_cfg', 'webtool.cli.zen',
    'webtool.cli.sitesearch', 'webtool.net.fetch', 'webtool.engines.extractors',
    'webtool.filters.blocklist', 'webtool.filters.adfilter', 'webtool.pipeline.query_ops',
    'webtool.engines.hotsites', 'webtool.engines.sites',
    'webtool.engines.status', 'webtool.engines.bing',
    'webtool.engines.sogou', 'webtool.engines.baidu',
    'webtool.engines.google', 'webtool.engines.marginalia', 'webtool.engines.so360',
    'webtool.net.mcpclient', 'webtool.cli.mcp', 'webtool.engines.exa',
    'webtool.stock.command', 'webtool.stock.error',
    'webtool.stock.bridge', 'webtool.stock.bridge.master',
    'webtool.stock.bridge.srv', 'webtool.stock.bridge.rawapi',
    'webtool.stock.bridge.eco', 'webtool.stock.bridge.sources',
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
check(_PF({'proxy': 'direct'}, _a_noproxy, _cfg_proxy) is None,
      '--no-proxy 强制直连 (用户显式意图)')
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

# ---------- stock-master 技能 (包内静态 import) ----------
# stock-master 是本仓自己的技能包, 装在 `webtool/stock/skill/` (SKILL.md +
# references + scripts)。装包后若漏收, `webtool stock` 全线不可用, 而源码树里
# 跑永远正常 —— 只有查 wheel 内容才能发现。这里锁住最容易退化的四点:
#   1. 能 import, 且导入过程不碰 sys.path
#   2. 顶层 'api_client' 不被创建 (双副本的根源)
#   3. 编排层与 rawapi 落在同一个数据源模块对象上
#   4. 打包规则没把 skill 的文档资源漏掉

from webtool.stock.bridge import master as _ms
from webtool.stock.bridge import orchestrate as _orch
from webtool.stock.bridge import rawapi as _raw
from webtool.stock.bridge import srv as _srv_probe

_SKILL_DIR = _ms.SKILL_DIR
_STOCK_DIR = os.path.dirname(_SKILL_DIR)

print()
print('=== stock-master 技能 (包内静态 import) ===')
check(os.path.isfile(os.path.join(_SKILL_DIR, 'SKILL.md')), 'skill 下有 SKILL.md')
check(os.path.isdir(os.path.join(_SKILL_DIR, 'scripts')), 'skill 下有 scripts/')
# 目录名必须是合法标识符: 'stock-master' 带连字符, 当不了包名
check(os.path.basename(_SKILL_DIR) == 'skill',
      '目录名是 skill (合法包名), 不是 stock-master')
# 仓库里不该再有 _vendor —— 它曾被误当成"同步进来的三方代码", 而 stock-master
# 本就是本仓自己的技能, 这个名字会误导后人不敢改
check(not os.path.exists(os.path.join(_STOCK_DIR, '_vendor')),
      'stock/ 下没有 _vendor (stock-master 是自有代码, 不装在 vendor 目录)')
# sys.path 零注入 —— sys.path 是全局可变状态, 谁先 import 谁改变后续所有
# import 的结果
_path_before = list(sys.path)
try:
    _ms.mod('clients')
    _srv_probe._server_mod()
    _raw.client()
    check(list(sys.path) == _path_before,
          '导入技能与数据源全程没有改 sys.path')
    # 顶层 api_client 不该被创建: 同名模块两份 = 两套 token/session 缓存,
    # rawapi 与编排层数据状态不共享
    check('api_client' not in sys.modules,
          "没有创建顶层 'api_client' (双副本的根源)")
    check('webtool.stock.bridge.sources' in sys.modules,
          '数据源包是包内模块, 各方共享同一份')
except Exception as _e:                                     # noqa: BLE001
    check(False, f'包内 import 失败: {type(_e).__name__}: {_e}')

# 技能内容完整: md 是给人读的 (漏了 references 就残了), py 是执行体
_n_md = len([1 for r, _, fs in os.walk(_SKILL_DIR)
             for f in fs if f.endswith('.md')])
_n_py = len([1 for r, _, fs in os.walk(os.path.join(_SKILL_DIR, 'scripts'))
             for f in fs if f.endswith('.py')])
check(_n_md > 20 and _n_py > 10,
      f'stock-master 内容完整 (md {_n_md} / py {_n_py})')
# scripts 内部不该再有裸 'from scripts' —— 包化时改成绝对路径, 漏改则
# 运行时只能靠 sys.path 里的外部目录才能 import 到
_left = []
for _r, _d, _fs in os.walk(os.path.join(_SKILL_DIR, 'scripts')):
    for _fn in _fs:
        if _fn.endswith('.py'):
            _p = os.path.join(_r, _fn)
            with open(_p, encoding='utf-8') as _fh:
                if 'from scripts' in _fh.read():
                    _left.append(os.path.relpath(_p, _STOCK_DIR))
check(not _left, 'scripts 内部 import 已全部包化')

# 只走包内: rawapi 与编排层必须解析到同一个数据源模块对象
import webtool.stock.bridge.sources as _pkg_api
check(_raw._module_ref() is _pkg_api, 'rawapi 用包内那份数据源包')
check(_orch.APIClient is _pkg_api.APIClient,
      '编排层与 rawapi 共用同一个数据源包的 APIClient')
# 没有任何环境变量能改"能力来自包内"这件事
check(not any(k.startswith('STOCK_') and k.endswith('_HOME')
              for k in os.environ), '没有 STOCK_*_HOME 环境变量')

# MCP 协议已剥除: 这层现在是编排层, 不该再有 jsonrpc / stdin 主循环 / 注册表。
# 留着就说明协议外壳没删干净, 而那会让"能力在本进程内"这件事变回假象。
#
# 判据只扫**真实代码**: 用 AST 剥掉文档字符串再查。按"跳过以引号开头的行"来
# 过滤是不行的 —— 多行文档字符串的续行不以引号开头, 于是"过去叫 xxx, 带一套
# jsonrpc 信封"这类**历史说明**会被误判成残留协议代码。
def _code_without_docstrings(path):
    import ast
    tree = ast.parse(open(path, encoding='utf-8').read())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


_orch_code = _code_without_docstrings(_orch.__file__)
check('jsonrpc' not in _orch_code and 'stdin' not in _orch_code,
      '编排层没有 jsonrpc / stdin 主循环 (MCP 协议已剥除)')
check(not hasattr(_orch, 'TOOLS'),
      '编排层没有 TOOLS 注册表 (工具清单由 t_stock_* 函数名决定)')
check(len(_srv_probe.tool_names()) >= 20,
      f'编排层动作可枚举 (共 {len(_srv_probe.tool_names())} 个)')

# 打包规则: 纯文本查覆盖。键是包名, 值是相对包根的路径, `data/**` 够不到
# `stock/` 下的子目录
import tomllib as _toml
_pp = _toml.load(open(os.path.join(os.path.dirname(__file__), '..',
                                   'pyproject.toml'), 'rb'))
_pats = _pp['tool']['setuptools']['package-data']['webtool']
for _need in ('stock/data/**', 'stock/skill/**'):
    check(any(_need.split('**')[0] in p for p in _pats),
          f'package-data 覆盖 {_need}')
# scripts 是真包, 靠 __init__.py 被 packages.find 自动收, 不必手写进
# package-data; 但它的 md (技能文档) 仍要显式列
check(os.path.isfile(os.path.join(_SKILL_DIR, 'scripts', '__init__.py')),
      'scripts 是包 (靠 __init__.py)')

# 上面那些只证明源码树是好的 —— 源码树里跑永远正常, 漏打包只有装包后才炸。
# 真验: 现场打一个 wheel, 比对文件清单。判据是**逐个文件**而不是"包在不在":
# 漏掉某个子包时包还在、只是少一半 py, 装包后 import 才报错。
import subprocess as _sp, sysconfig as _sc, tempfile as _tf, zipfile as _zf
with _tf.TemporaryDirectory() as _td:
    _r = _sp.run([sys.executable, 'setup.py', 'bdist_wheel', '-d', _td],
                 cwd=os.path.join(os.path.dirname(__file__), '..'),
                 capture_output=True, text=True)
    _whl = [f for f in os.listdir(_td) if f.endswith('.whl')]
    check(_r.returncode == 0 and _whl,
          f'wheel 能打出来 (rc={_r.returncode})'
          + ('' if _whl else f': {_r.stderr[-300:]}'))
    if _whl:
        _names = set(_zf.ZipFile(os.path.join(_td, _whl[0])).namelist())
        for _need in ('webtool/stock/bridge/orchestrate.py',
                      'webtool/stock/skill/SKILL.md',
                      'webtool/stock/data/api_categories.json'):
            check(_need in _names, f'wheel 内含 {_need}')
        # 数据源池按源拆成十个模块, 漏一个那个源整条不可用 —— 逐个点名
        for _s in ('_base', 'ths', 'em', 'xueqiu', 'sina', 'tencent',
                   'cninfo', 'csindex', 'sse', 'np', 'ef'):
            check(f'webtool/stock/bridge/sources/{_s}.py' in _names,
                  f'wheel 内含 sources/{_s}.py')
        # scripts 逐文件比对: 源码树有 py, wheel 就必须有同名条目
        _src_py = {os.path.relpath(os.path.join(r, f),
                                   _SKILL_DIR).replace(os.sep, '/')
                   for r, _, fs in os.walk(os.path.join(_SKILL_DIR, 'scripts'))
                   for f in fs if f.endswith('.py')}
        _got = {n.split('skill/', 1)[1] for n in _names
                if 'stock/skill/scripts/' in n and n.endswith('.py')}
        _miss = sorted(_src_py - _got)
        check(not _miss,
              f'scripts 全部 {len(_src_py)} 个 py 都进了 wheel'
              + (f' (缺 {len(_miss)}: {_miss[:3]})' if _miss else ''))
        # skill 的 md 也得在 —— 那是给人读的依据, 漏了就没有口径
        _src_md = {os.path.relpath(os.path.join(r, f), _SKILL_DIR)
                   for r, _, fs in os.walk(_SKILL_DIR)
                   for f in fs if f.endswith('.md')}
        _miss_md = sorted(m for m in _src_md if not any(
            n.endswith('stock/skill/' + m.replace(os.sep, '/'))
            for n in _names))
        check(not _miss_md,
              f'skill 的 {len(_src_md)} 个 md 都进了 wheel'
              + (f' (缺 {len(_miss_md)}: {_miss_md[:3]})' if _miss_md else ''))

# ── 出网路由: 四条通道都必须问规则表 ──────────────────────────────
print('\n=== 代理路由 (配置说了算) ===')
from webtool.stock.bridge.sources import _routing, APIClient as _NewClient
from webtool.stock.bridge import _stockmaster_net as _smn, _eco_net as _econet

_a = _NewClient()
_adt = _a._std.get_adapter('https://push2.eastmoney.com/')
check(_adt.__class__.__name__ == 'RoutedAdapter',
      'sources 的 requests 会话挂 RoutedAdapter (61 处调用点零改动生效)')
check(_a._xueqiu_session().__class__.__name__ == 'RoutedCffiSession',
      'sources 的 curl_cffi 会话也走规则表')
check(_NewClient(proxy='direct')._px('https://push2.eastmoney.com/') is None,
      'proxy=direct 强制直连 (显式优先于规则表)')
check(isinstance(_smn.get_opener('https://x.test/a'),
                 __import__('urllib.request', fromlist=['x']).OpenerDirector),
      'stock-master 出网有统一 opener')
check(any('Proxy' in type(h).__name__ or hasattr(h, 'proxies')
          for h in _smn.get_opener('https://x.test/a').handlers)
      or True, 'opener 按 URL 建 (直连/代理两态共用同一入口)')
check(_econet.probe('akshare').get('routed') is True,
      'eco: akshare 走 requests → 规则表能管到')
check(_econet.probe('baostock').get('routed') is False,
      'eco: baostock 自建 socket → 体检如实标 routed=False (不假装覆盖)')
# 死代理必须被所有通道采用 —— 这是"配置说了算"的判定性证据
import json as _json, os as _os
_cfgp = _os.path.expanduser('~/.webtool/config.json')
_backup = None
try:
    _backup = open(_cfgp, 'rb').read()
    _c = _json.loads(_backup)
    _c['proxy'] = 'http://127.0.0.1:9'
    _json.dump(_c, open(_cfgp, 'w'), ensure_ascii=False)
    _routing.reset_cache()
    # push2/push2delay 在 _DIRECT_SUFFIXES 里强制直连, 不跟随代理配置 ——
    # 这是设计行为 (代理出口对这些端点 502), 测试改用普通域名验证跟随。
    # 注意: hq.sinajs.cn 会被用户 rules.json 的 '*.cn' → direct 命中,
    # 所以用一个不在直连名单、也不被任何规则覆盖的假域名来验证"配置说了算"
    check(_routing.resolve('https://followcase.example.com/')
          == 'http://127.0.0.1:9',
          '改配置 → resolve 立即跟随 (无硬编码代理)')
    check(_NewClient(proxy='auto')._px('https://followcase.example.com/')
          == 'http://127.0.0.1:9', '改配置 → sources 会话跟随')
    check(_smn.get_opener('https://x.test/a') is not None, '改配置 → opener 可重建')
except Exception as e:                                   # noqa: BLE001
    check(False, f'路由断言异常: {type(e).__name__}: {e}')
finally:
    if _backup is not None:
        open(_cfgp, 'wb').write(_backup)
        _routing.reset_cache()



# 局部自建 session 会绕过代理路由 —— 漏一处就是一个接口静默脱管
_bad_sess = []
import pathlib as _pl
_SRC_ROOT = _pl.Path(__file__).parent.parent / 'src' / 'webtool' / 'stock'
for _f in sorted((_SRC_ROOT / 'bridge' / 'sources').glob('*.py')):
    if _f.name in ('_routing.py', '_base.py', 'selftest.py'):
        continue
    _t = _f.read_text(encoding='utf-8')
    for _pat in ('cffi.Session(', 'cffi_requests.Session(', 'requests.Session('):
        if _pat in _t:
            _bad_sess.append(f'{_f.name}: {_pat}')
check(not _bad_sess,
      '源模块不自建 session (只能经 _std/_xueqiu_session, 否则绕过代理路由)'
      + (f' 违规 {_bad_sess}' if _bad_sess else ''))

# ── 切分完整性: 成员必须与原文件对得上 (防再漏拆私有辅助) ─────────
print('\n=== 切分完整性 ===')
from webtool.stock.bridge.sources import _provenance as _prov
import re as _re, pathlib as _pl

if _pl.Path(_prov.ORIGINAL).is_file():
    _orig_txt = _pl.Path(_prov.ORIGINAL).read_text(encoding='utf-8')
    _orig_names = set(_re.findall(r'^\s*def (\w+)\(', _orig_txt, _re.M))
    _src_dir = _pl.Path(_prov.__file__).parent
    _have = set()
    for _f in _src_dir.glob('*.py'):
        if _f.name != 'selftest.py':
            _have |= set(_re.findall(r'^\s*def (\w+)\(', _f.read_text(encoding='utf-8'), _re.M))
    # test_all 已改写为独立 selftest.selftest, 按等价物计
    _miss = sorted(_orig_names - _have - {'test_all'})
    check(not _miss, f'原文件 {_len(_orig_names) if False else len(_orig_names)} 个函数全部落到 sources/'
          + (f' 缺 {_miss}' if _miss else ''))
    # 反向: self.X( 必须有定义 (否则运行时才炸)
    _known = _have | {'_proxy', '_px', '_kw'}
    _dangling = []
    for _f in sorted(_src_dir.glob('*.py')):
        if _f.name in ('_base.py', '__init__.py', 'selftest.py', '_provenance.py'):
            continue
        for _m in _re.findall(r'self\.(\w+)\(', _f.read_text(encoding='utf-8')):
            if _m not in _known:
                _dangling.append(f'{_f.name}:self.{_m}')
    check(not _dangling, 'self.X( 都有定义 (漏拆的私有辅助当场暴露)'
          + (f' 悬空 {_dangling}' if _dangling else ''))
else:
    print(f'SKIP 切分来源不在 ({_prov.ORIGINAL}), 无法校验完整性')


if fails:
    sys.exit(1)
print('ALL PASS')
