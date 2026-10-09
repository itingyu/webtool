# -*- coding: utf-8 -*-
"""自定义站点扩展: ~/.webtool/sites/*.json

内置站点在 engines/sites.py; 用户把新的站点适配器写成 JSON 即可扩展,
无需改代码。JSON 适配器 = {搜索URL模板 + 提取规则}, 覆盖常见 JSON API 形态。

格式 (一个文件可含多个站点):
{
  "v2ex": {
    "desc": "V2EX 主题",
    "url": "https://www.sov2ex.com/api/search?q={query}&size={limit}",
    "proxy": "direct",                      // direct | proxy | auto (默认 auto)
    "headers": {"User-Agent": "Mozilla/5.0"},  // 可选, 覆盖默认头
    "results_path": "data",                 // 结果数组所在 JSON 路径, / 分层
    "fields": {                             // 结果字段映射, {xx} 引用 + |strip_html
      "title": "title",
      "url": "https://www.v2ex.com/t/{id}",
      "snippet": "content|strip_html",
      "score": "score"
    }
  }
}

url 模板变量: {query}(URL编码后的搜索词), {limit}, {page}(从1起)
字段值支持:
- "path/to/field"       结果对象的 JSON 路径
- "https://xx/t/{id}"   模板拼接 (引用结果字段)
- "content|strip_html"  管道后处理: strip_html / trunc200 / date_ts / date_iso
"""
import json
import os
import re
import urllib.parse

from .resilient import fetch as rfetch
from .engines.sites import _headers

SITES_DIR = os.path.expanduser('~/.webtool/sites')


def load_custom_sites():
    """加载所有自定义站点定义"""
    customs = {}
    if not os.path.isdir(SITES_DIR):
        return customs
    for fn in sorted(os.listdir(SITES_DIR)):
        if not fn.endswith('.json'):
            continue
        try:
            with open(os.path.join(SITES_DIR, fn), encoding='utf-8') as f:
                data = json.load(f)
            for name, spec in data.items():
                if _validate(spec):
                    customs[name] = spec
                else:
                    customs[name] = {'_error': 'invalid spec: need url+results_path+fields'}
        except Exception as e:
            customs[fn[:-5]] = {'_error': f'load fail: {str(e)[:100]}'}
    return customs


def _validate(spec):
    return isinstance(spec, dict) and spec.get('url') and spec.get('results_path') is not None and spec.get('fields')


def search_custom(name, spec, query, limit=10, proxy=None, timeout=15):
    url = (spec['url'].replace('{query}', urllib.parse.quote(query))
           .replace('{limit}', str(limit))
           .replace('{page}', '1'))
    extra = dict(spec.get('headers') or {})
    kind = extra.pop('_kind', 'api')  # api(XHR指纹) | nav(浏览器导航)
    headers = _headers(url, kind, extra or None)
    txt, st, _via = rfetch(url, proxy=proxy, timeout=timeout, headers=headers)
    data = json.loads(txt)
    arr = _dig(data, spec['results_path'])
    if arr is None:
        raise RuntimeError(f'results_path "{spec["results_path"]}" not found in response')
    out = []
    for item in arr[:limit * 2]:
        if not isinstance(item, dict):
            continue
        row = {}
        for k, tpl in spec['fields'].items():
            v = _render(tpl, item)
            if v is not None:
                row[k] = v
        if row.get('title') and row.get('url'):
            row['rank'] = len(out) + 1
            out.append(row)
        if len(out) >= limit:
            break
    return out


def _dig(obj, path):
    cur = obj
    for part in path.split('/'):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return cur


def _render(tpl, item):
    # 管道后处理: "path|strip_html|trunc200"
    parts = tpl.split('|')
    path, pipes = parts[0].strip(), parts[1:]
    if path.startswith('http'):            # 静态模板 URL
        val = path
        for p in pipes:
            val = _pipe(val, p)
        return val
    val = _dig(item, path)
    if val is None:
        return None
    val = str(val)
    # 模板变量 {field}
    def sub(m):
        return str(_dig(item, m.group(1)) or '')
    val = re.sub(r'\{([\w/]+)\}', sub, val)
    for p in pipes:
        val = _pipe(val, p)
    return val


def _pipe(v, p):
    p = p.strip()
    if p == 'strip_html':
        return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', v)).strip()
    if p == 'trunc200':
        return v[:200]
    if p == 'date_ts':                      # unix 秒 → 日期
        try:
            import datetime
            return datetime.datetime.fromtimestamp(int(v)).strftime('%Y-%m-%d')
        except Exception:
            return v
    if p == 'date_iso':                     # ISO → 日期
        return v[:10]
    if p.startswith('prefix:'):
        return p[7:] + v
    return v
