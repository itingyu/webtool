"""Firecrawl 搜索引擎: keyless MCP, 免费层 500 次/月

与 Exa / Parallel 同属 "MCP 端点兼作搜索引擎" 这一路 (见 coding-standard.md
的 engines/exa.py 样板), 但 Firecrawl 有两点不同:

1. **免 key 直接可用**。官方定价页的 Free Plan 是 500 searches/月 或
   1000 pages  scraped, 无需绑卡; mcp.firecrawl.dev 的 MCP 端点 keyless
   可连。配 FIRECRAWL_API_KEY 可提额, 没配也照常用。
2. **参数单字段**, 只有一个 query —— 不像 Parallel 要 objective +
   search_queries 双必填, 所以这里不需要变体派生。

返回是 JSON, 形状与 REST /v1/search 不同: MCP 端点把结果裹在
`data.web` 数组里 (REST 是裸 `data` 数组), 解析要认这两种。
"""

from webtool.core.text import truncate
from webtool.net import mcpclient as _mc

# 上游单次上限, 超出先封顶再截断 (免 key 层的并发本来就低)
_MAX_UPSTREAM = 10
# MCP 走握手 + 调用两趟往返, 管线默认 15s 对它偏紧
_MIN_TIMEOUT = 30


def _spec(name='firecrawl'):
    return _mc.endpoint(name)


def _items(data):
    """兼容 MCP(data.web) / REST(data) 及其他容器键名(results/news)"""
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for k in ('web', 'results', 'news', 'data'):
        v = data.get(k)
        if isinstance(v, list):
            return v
    # 单条对象直接当一条结果 (字段齐的才认, 否则说明这是包装层)
    return [data] if data.get('url') else []


def _parse(text, max_results):
    """MCP 返回的 JSON 文本 → [{rank, title, url, snippet}]"""
    import json
    try:
        d = json.loads(text or '')
    except (TypeError, ValueError):
        return []
    if not isinstance(d, dict) or not d.get('success', True):
        return []
    out, seen = [], set()
    for it in _items(d.get('data')):
        if not isinstance(it, dict):
            continue
        url = (it.get('url') or '').strip()
        if not url or url in seen:
            continue
        seen.add(url)
        out.append({
            'rank': len(out) + 1,
            'title': truncate((it.get('title') or '').strip(), 120),
            'url': url,
            # description 是 Firecrawl 给的摘要, 没有就用 url 兜底保证非空
            'snippet': truncate((it.get('description') or '').strip() or url, 300),
        })
        if len(out) >= max_results:
            break
    return out


def search(query, max_results=10, proxy=None, timeout=15, market=None, **_):
    """Firecrawl web 搜索 → 标准结果列表; 失败抛 RuntimeError 由管线记入 errors"""
    spec = _spec()
    tool = (spec.get('verbs') or {}).get('search')
    if not tool:
        raise RuntimeError("端点 'firecrawl' 未声明 search 动词")
    want = max(1, min(int(max_results or 10), _MAX_UPSTREAM))
    r = _mc.call_tool(spec.get('url', ''), tool, {'query': query, 'limit': want},
                      api_key=_mc.api_key_of(spec),
                      timeout=max(int(timeout or 0), _MIN_TIMEOUT),
                      # 代理跟随配置 (缺省 auto 走路由表); 曾写死 proxy=None
                      # 强制直连, 理由是免 key 层按出口 IP 计量 —— 那是服务方
                      # 的策略, 该用户配: config set engine_proxy.firecrawl direct
                      proxy=proxy if proxy is not None else 'auto')
    if 'error' in r:
        err = r['error'] if isinstance(r['error'], dict) else {'message': str(r['error'])}
        raise RuntimeError(
            f'Firecrawl 调用失败 (code={err.get("code")}): {str(err.get("message"))[:200]}')
    if r.get('is_error'):
        raise RuntimeError(f'Firecrawl 返回错误: {(r.get("text") or "")[:200]}')
    res = _parse(r.get('text'), want)
    if not res:
        raise RuntimeError('Firecrawl 返回空结果')
    return res
