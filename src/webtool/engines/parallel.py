"""Parallel 语义搜索: 走 Parallel Search MCP 的 web_search 工具

与 `engines/exa.py` 同为"出网交给 MCP 客户端、只做参数组装与解析"的引擎,
端点声明 (url / verbs / proxy / api_key_env) 全部读 `data/mcp.json`。

Parallel 有两处与 Exa 不同的调用形状, 是本模块的全部复杂度所在:

1. **`objective` 与 `search_queries` 双必填**, 且角色不同。官方要求
   objective 写自然语言研究目标(可整句), search_queries 给 2-3 个 3-6 词的
   关键词变体、角度要多样、不能是句子。而管线只给一个 query 字符串, 故
   `_queries()` 负责派生变体。
2. **返回是 JSON**, 不是 Exa 那种 `Title:/URL:` 纯文本块, 解析无歧义。

免费额度: 匿名免 key 可用 (走 fast 模式); 注册后每月有 $5 循环额度
(搜索 $1/1000 请求, 约合 5000 次/月), 配 PARALLEL_API_KEY 自动生效。

代理: **不写死**。曾与 Exa 一样硬编码 `proxy=None` (免 key 配额按出口 IP 计), 但
那是服务方的计量策略, 不该由代码替用户决定 —— 需要直连时在规则表里给它的域名
写一条: `webtool proxy rule add <该域名> direct`。

上游请求条数封顶同 Exa: 单次条数越多越慢且更易触发限流, 故对上游封顶, 返回值
再截断到调用方要的数。
"""
import json
import re

from webtool.core.text import truncate
from webtool.net import mcpclient as _mc

_MAX_UPSTREAM = 10
_MIN_TIMEOUT = 30
_SNIPPET_CHARS = 300

# 意图词/修饰词: 派生关键词变体时剥掉, 只留实体与主题。
# 中英混排都要覆盖 —— 中文按子串切, 英文按词切。
_STOP = re.compile(
    r'(最新|最新消息|怎么样|如何|是什么|为什么|哪个|哪些|多少|介绍|教程|指南|解析'
    r'|对比|比较|优缺点|怎么样做|怎么用|详细|全面'
    r'|the|a|an|of|for|to|in|on|with|is|are|what|how|why|which|best|top'
    r'|latest|news|guide|tutorial|vs|versus|compared|comparison|review)\b',
    re.I)


def _queries(query):
    """单条 query → ([search_queries...], objective)

    objective 原样传管线给的 query (它已被 query_ops 精简过, 接近自然语言目标);
    search_queries 派生关键词变体。官方要求 2-3 个 3-6 词、角度多样的短查询,
    所以**下限是 2**: 派生不出来也要凑够 (宁可给同义角度, 也别给单条让对方
    拿不到多样性)。变体只做去停用词与截断, 不做同义改写 —— 没有词表支撑
    的"改写"是噪声源。
    """
    q = (query or '').strip()
    words = q.split()
    out = [q]
    if len(words) >= 2:
        meaningful = [w for w in words
                      if not _STOP.fullmatch(w.strip('.,:;?，。：；？'))]
        cands = []
        if meaningful and len(meaningful) != len(words):
            cands.append(' '.join(meaningful))          # 剥意图词, 留实体
        cands.append(' '.join((meaningful or words)[:6]))  # 前 6 实词 (官方建议长度)
        if len(words) > 3:
            cands.append(' '.join((meaningful or words)[:3]))  # 更窄的角度
        for v in cands:
            if v and v not in out:
                out.append(v)
    # 下限兜底: 词少到派不出变体时, 用前两词切一个窄查询
    if len(out) < 2 and len(words) >= 2:
        v = ' '.join(words[:2])
        if v not in out:
            out.append(v)
    return out, q


def _parse(text, max_results):
    """MCP 返回的 JSON → [{rank, title, url, snippet}]

    结构: {"search_id":..., "results":[{"url","title","publish_date","excerpts":[...]}]}
    注意 publish_date 大量为 null (实测 10 条里 6-8 条), excerpts 是数组且
    首条可能很长 —— 拼前若干条后按上限截断。
    """
    try:
        d = json.loads(text or '')
    except (TypeError, ValueError):
        return []
    if isinstance(d, dict):
        items = d.get('results') or []
    elif isinstance(d, list):
        items = d
    else:
        items = []

    out, seen = [], set()
    for it in items:
        if not isinstance(it, dict):
            continue
        url = (it.get('url') or '').strip()
        title = (it.get('title') or '').strip()
        if not url or not title or url in seen:
            continue
        seen.add(url)
        ex = it.get('excerpts') or []
        if isinstance(ex, str):
            ex = [ex]
        snippet = ' '.join(x.strip() for x in ex if isinstance(x, str) and x.strip())
        item = {'rank': len(out) + 1, 'title': title, 'url': url,
                'snippet': truncate(snippet, _SNIPPET_CHARS)}
        # 日期对时效类查询很有用, 有才带 (webtool 结果结构允许附加字段)
        if it.get('publish_date'):
            item['publish_date'] = str(it['publish_date'])[:10]
        out.append(item)
        if len(out) >= max_results:
            break
    return out


def search(query, max_results=10, proxy=None, timeout=15, market=None, **_):
    """Parallel 语义搜索; 匿名免 key 可用 (代理跟随配置)"""
    sqs, objective = _queries(query)
    r = _mc.call_verb('parallel', 'search',
                      {'objective': objective, 'search_queries': sqs},
                      timeout=max(timeout or 0, _MIN_TIMEOUT),
                      proxy=proxy if proxy is not None else 'auto')
    if 'error' in r:
        code = (r['error'] or {}).get('code')
        msg = r['error'].get('message') if isinstance(r['error'], dict) else str(r['error'])
        if code in (401, 403):
            raise RuntimeError(f'Parallel 鉴权失败 ({msg}); 可配 PARALLEL_API_KEY')
        if code == 429:
            raise RuntimeError(
                f'Parallel 429 ({msg}); 匿名层有速率上限, 仍受限则配 PARALLEL_API_KEY '
                f'(https://parallel.ai)')
        raise RuntimeError(f'Parallel 调用失败: {msg}')
    if r.get('is_error'):
        raise RuntimeError(f'Parallel 返回错误: {truncate(r.get("text", ""), 200)}')

    res = _parse(r.get('text', ''), max_results or _MAX_UPSTREAM)
    if not res:
        raise RuntimeError('Parallel 返回空结果')
    return res
