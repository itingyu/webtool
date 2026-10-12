# -*- coding: utf-8 -*-
"""自定义站点扩展: ~/.webtool/sites/*.json (JSON 适配器 = 搜索URL模板 + 提取规则)

一个文件可含多个站点, 每站字段: desc / url ({query}{limit}{page}) /
proxy (direct|proxy|auto, 默认 auto) / headers 可选 / results_path (JSON
路径, "*" 对数组每项下钻) / fields (值支持 "path"、"{id}" 模板拼接、
"path|strip_html|trunc200|date_ts|date_iso" 管道后处理)。
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
        msg = data.get('message') or data.get('error') if isinstance(data, dict) else None
        raise RuntimeError(f'results_path "{spec["results_path"]}" not found in response'
                           + (f' (server: {msg})' if msg else ''))
    if arr and not isinstance(arr, list):   # 单对象结果包成数组
        arr = [arr]
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
    parts = path.split('/')

    def walk(cur, i):
        if i == len(parts):
            return cur
        part = parts[i]
        if isinstance(cur, dict):
            return walk(cur[part], i + 1) if part in cur else None
        if isinstance(cur, list):
            if part == '*':                # 通配: 对数组每项继续下钻
                out = []
                for it in cur:
                    r = walk(it, i + 1)
                    if r is not None:
                        out.append(r)
                return out
            try:
                return walk(cur[int(part)], i + 1)
            except (ValueError, IndexError):
                return None
        return None
    return walk(obj, 0)


def _render(tpl, item):
    parts = tpl.split('|')
    path, pipes = parts[0].strip(), parts[1:]

    def sub(m):
        return str(_dig(item, m.group(1)) or '')

    if path.startswith('http'):            # 模板 URL (可引用结果字段 {id})
        val = re.sub(r'\{([\w/]+)\}', sub, path)
        for p in pipes:
            val = _pipe(val, p)
        return val
    val = _dig(item, path)
    if val is None:
        return None
    val = str(val)
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
    if p == 'date_ts':
        try:
            import datetime
            return datetime.datetime.fromtimestamp(int(v)).strftime('%Y-%m-%d')
        except Exception:
            return v
    if p == 'date_iso':
        return v[:10]
    if p.startswith('prefix:'):
        return p[7:] + v
    return v
