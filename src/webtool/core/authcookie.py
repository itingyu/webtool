"""登录态 cookie 的解析与导出

三种来源格式都要能吃, 因为用户手里是哪一种不由我们决定:
- 请求头串 `a=1; b=2`      (从 DevTools 的 Cookie 头直接复制)
- JSON 数组 / 对象          (Cookie-Editor / EditThisCookie 导出)
- Netscape cookies.txt      (浏览器插件与 curl 见的文件格式)

只做纯转换, 不碰网络与落盘 —— 落盘走 dao.state, 抓取走 net.transport。
"""
from __future__ import annotations

import json

# 一律按"值里可能带等号/分号"处理: 只按第一个 '=' 切
def parse_header(text):
    """`a=1; b=2` → [{name,value,...}]"""
    out = []
    for seg in (text or '').split(';'):
        seg = seg.strip()
        if not seg or '=' not in seg:
            continue
        name, value = seg.split('=', 1)
        name, value = name.strip(), value.strip().strip('"')
        if name:
            out.append({'name': name, 'value': value})
    return out


def _norm(item, default_domain=''):
    if not isinstance(item, dict):
        return None
    name = item.get('name') or item.get('Name') or ''
    value = item.get('value')
    if value is None:
        value = item.get('Value', '')
    if not name:
        return None
    c = {'name': str(name), 'value': str(value)}
    dom = item.get('domain') or item.get('Domain') or default_domain
    if dom:
        c['domain'] = str(dom)
    c['path'] = str(item.get('path') or item.get('Path') or '/')
    exp = item.get('expires') or item.get('expirationDate')
    if isinstance(exp, (int, float)):
        c['expires'] = int(exp)
    if item.get('secure') or item.get('Secure'):
        c['secure'] = True
    return c


def parse_netscape(text, default_domain=''):
    """Netscape cookies.txt: 每行 7 个制表符字段, # 开头是注释"""
    out = []
    for line in (text or '').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        f = line.split('\t')
        if len(f) < 7:
            continue
        c = _norm({'domain': f[0], 'path': f[2], 'secure': f[3] == 'TRUE',
                   'expires': int(f[4] or 0), 'name': f[5], 'value': f[6]},
                  default_domain)
        if c:
            out.append(c)
    return out


def parse(text, default_domain=''):
    """自动识别格式: JSON → Netscape → 请求头串

    识别顺序有讲究: Netscape 行里也有 '=' , 先试 JSON 再试制表符,
    最后才按 ';' 切 —— 反过来会把 cookies.txt 解析成一堆垃圾键。
    """
    text = (text or '').strip()
    if not text:
        return []
    if text[0] in '[{':
        try:
            d = json.loads(text)
        except ValueError:
            d = None
        if isinstance(d, list):
            return [c for c in (_norm(i, default_domain) for i in d) if c]
        if isinstance(d, dict):
            # 两种形态: {"a": "1"} 或 {"cookies": [...]}
            inner = d.get('cookies')
            if isinstance(inner, list):
                return [c for c in (_norm(i, default_domain) for i in inner) if c]
            return [c for c in (_norm({'name': k, 'value': v}, default_domain)
                                for k, v in d.items()) if c]
    if '\t' in text:
        return parse_netscape(text, default_domain)
    return [_norm(c, default_domain) for c in parse_header(text)]


def to_header(cookies):
    """[{name,value}] → `a=1; b=2` (Cookie 请求头的值)"""
    return '; '.join(f"{c['name']}={c['value']}" for c in cookies or [])


def missing(cookies, required):
    """required 里哪些 cookie 没给 —— 报错时直接点出缺哪个, 别让用户猜"""
    have = {c['name'] for c in cookies or []}
    return [n for n in required if n not in have]
