"""Exa 语义搜索: 走 Exa MCP 端点的 web_search_exa 工具

与 bing/sogou/baidu 那批"抓 HTML 自己解析"不同, 这里把出网交给 MCP 客户端
(`net/mcpclient`), 只负责拼参数 + 把返回的纯文本解析成标准结果结构。

端点声明 (url / verbs / api_key_env) 全部读 `data/mcp.json`, 与
`webtool mcp call exa ...` 同一份数据, 加端点只改 JSON 不改代码。本模块不再
import `cli/` —— engines 是 L1, cli 是 L4, 不得反向依赖。

代理: **不写死**, 跟随配置 —— 免 key 配额按出口 IP 计是服务方的计量策略, 由规则表
表达更合适 (用户可能有自己的额度, 或代理出口本身有配额):

- 确实需要直连时, 在规则表里给它的域名写一条: `webtool proxy rule add <该域名> direct`
- 规则对 MCP 端点同样生效 (不按引擎名分, 只看请求目标)

只有 `numResults` 封顶这一项仍写死: MCP 单次调用条数越多越慢且更易触发限流,
故对上游封顶, 返回值再截断到调用方要的数。
"""
import os

from webtool.core import config_data as _cfg_data
from webtool.core.text import truncate
from webtool.net import mcpclient as _mc

# 上游单次最多要几条: 超出部分对召回无益, 只增加耗时与限流风险
_MAX_UPSTREAM = 10
# MCP 有握手 + 调用两趟网络往返, 管线默认 15s 对它偏紧, 给个下限
_MIN_TIMEOUT = 30


def _spec(name='exa'):
    """端点声明 (含 verbs); 取不到抛错, 由管线记入 errors"""
    table = _cfg_data.load('mcp', 'mcp.json')
    spec = table.get(name)
    if not spec:
        raise RuntimeError(f'未登记端点 {name!r}; 可用: {", ".join(sorted(table)) or "(无)"}')
    return spec


def _parse(text, max_results):
    """MCP 返回的纯文本 → [{rank, title, url, snippet}]

    文本块形如 (块间以 Title: 起新一条):

        Title: 教程 - 用户指南 - FastAPI
        URL: https://fastapi.tiangolo.com/zh/tutorial/
        Published: N/A
        Author: N/A
        Highlights:
        <正文片段, 含 markdown 与省略号>

    Highlights 是正文而非摘要, 直接当 snippet 会很长, 故截断。
    """
    out, seen = [], set()
    cur = None
    key = None
    for raw in (text or '').splitlines():
        line = raw.rstrip()
        if line.startswith('Title: '):
            if cur:
                out.append(cur)
            cur = {'rank': len(out) + 1, 'title': line[7:].strip(),
                   'url': '', 'snippet': ''}
            key = 'title'
            continue
        if cur is None:
            continue
        if line.startswith('URL: '):
            cur['url'] = line[5:].strip()
            key = 'url'
        elif line.startswith('Highlights:'):
            key = 'snippet'
        elif line.startswith(('Published:', 'Author:', 'Published Date:')):
            key = None
        elif key == 'snippet':
            # Highlights 正文可能含 markdown 标题/列表, 取前若干行作摘要
            cur['snippet'] = (cur['snippet'] + ' ' + line).strip() if cur['snippet'] else line
    if cur:
        out.append(cur)

    res = []
    for r in out:
        if not r['title'] or not r['url'] or r['url'] in seen:
            continue
        seen.add(r['url'])
        res.append({'rank': len(res) + 1, 'title': r['title'],
                    'url': r['url'], 'snippet': truncate(r['snippet'], 300)})
        if len(res) >= max_results:
            break
    return res


def search(query, max_results=10, proxy=None, timeout=15, market=None,
           since=None, until=None, **_):
    """Exa 语义搜索。线路由规则表定 (要直连就给它的域名加一条 direct 规则)"""
    spec = _spec()
    tool = (spec.get('verbs') or {}).get('search')
    if not tool:
        raise RuntimeError('端点表未声明 search 动词, 无法作为搜索引擎使用')

    n = min(max_results or _MAX_UPSTREAM, _MAX_UPSTREAM)
    payload = {'query': query, 'numResults': n}
    if since:
        payload['startPublishedDate'] = since.isoformat()
    if until:
        payload['endPublishedDate'] = until.isoformat()
    r = _mc.call_tool(
        spec.get('url', ''), tool, payload,
        api_key=os.environ.get(spec.get('api_key_env', ''), ''),
        timeout=max(timeout or 0, _MIN_TIMEOUT),
        proxy=proxy if proxy is not None else 'auto',
    )
    if 'error' in r:
        code = (r['error'] or {}).get('code')
        msg = r['error'].get('message') if isinstance(r['error'], dict) else str(r['error'])
        if code == 429:
            raise RuntimeError(
                f'Exa 429: 免 key 配额按出口 IP 计, 换出口 IP 不会变多。'
                f'配 {spec.get("api_key_env", "EXA_API_KEY")} 可用独立额度 '
                f'(https://dashboard.exa.ai/api-keys); '
                f'或给它的域名加一条直连规则: webtool proxy rule add <该域名> direct。'
                f'原始错误: {msg}')
        raise RuntimeError(f'Exa 调用失败: {msg}')
    if r.get('is_error'):
        raise RuntimeError(f'Exa 返回错误: {truncate(r.get("text", ""), 200)}')

    res = _parse(r.get('text', ''), max_results or _MAX_UPSTREAM)
    if not res:
        raise RuntimeError('Exa 返回空结果')
    return res
