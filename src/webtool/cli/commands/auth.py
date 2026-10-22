"""webtool auth: 登录态 cookie 管理 (给需要登录的站点用)

匿名请求这些站只回 "环境异常" / "登录已过期", 必须带用户自己的 cookie。
cookie 存 dao.state 的 cookies 桶 (键名 = 站点名), 站点源只读不写。

安全约定: 任何输出都只列 cookie **名字**, 不打印值。
"""

from __future__ import annotations

import sys

import typer

from webtool.cli._ctx import Fmt
from webtool.cli.app import app
from webtool.core import authcookie
from webtool.dao import state
from webtool.engines import gated


def _norm_site(site):
    s = (site or '').strip().lower()
    if s not in gated.AUTH_SITES:
        raise typer.BadParameter(
            f'未知站点 {site!r}; 可用: {", ".join(sorted(gated.AUTH_SITES))}')
    return s


def _read_input(cookie, path):
    """三种来源: --cookie 直接给头串 / --file 读文件 / 否则读 stdin"""
    if cookie:
        return cookie
    if path:
        try:
            with open(path, encoding='utf-8', errors='ignore') as f:
                return f.read()
        except OSError as e:
            raise typer.BadParameter(f'读不到文件 {path}: {e}') from e
    if sys.stdin.isatty():
        raise typer.BadParameter(
            '没给 cookie 内容: 用 --cookie "k=v; k2=v2" / --file 路径 / 直接管道输入')
    return sys.stdin.read()


def _status(site):
    """取某站已导入的 cookie, 补上 domain, 返回 (items, 缺哪些必填)"""
    spec = gated.AUTH_SITES[site]
    items = []
    for c in state.load_cookies(site):
        c = dict(c)
        c.setdefault('domain', spec['domain'])
        c.setdefault('path', '/')
        items.append(c)
    have = {c.get('name') for c in items}
    missing = [k for k in gated.needs(site) if k not in have]
    return items, missing


def _fmt_list(fmt):
    rows = []
    for site, spec in sorted(gated.AUTH_SITES.items()):
        items, missing = _status(site)
        rows.append({'site': site, 'label': spec['label'],
                     'imported': len(items),
                     'cookies': sorted({c.get('name') for c in items}),
                     'missing': missing, 'ok': bool(items) and not missing})
    if fmt == 'json':
        return rows
    out = [f'登录态源 ({len(rows)} 个):']
    for r in rows:
        mark = 'OK' if r['ok'] else ('部分' if r['imported'] else '未导入')
        line = (f"  {r['site']:<6} {r['label']:<8} {mark:<4} "
                f"已存 {r['imported']} 个: {', '.join(r['cookies']) or '-'}")
        out.append(line)
        if r['missing']:
            out.append(f"         缺: {', '.join(r['missing'])}  "
                       f"→ webtool auth set {r['site']}")
    return '\n'.join(out)


def _fmt_detail(site, fmt):
    spec = gated.AUTH_SITES[site]
    items, missing = _status(site)
    data = {'site': site, 'label': spec['label'],
            'cookies': sorted({c.get('name') for c in items}),
            'missing': missing, 'ok': bool(items) and not missing,
            'hint': spec['hint']}
    if fmt == 'json':
        return data
    out = [f"{site} ({spec['label']})  {'可用' if data['ok'] else '不可用'}",
           f"  已存 cookie: {', '.join(data['cookies']) or '-'}"]
    if missing:
        out.append(f"  缺必填: {', '.join(missing)}")
    out.append(f"  说明: {spec['hint']}")
    return '\n'.join(out)


def _do_set(site, text, fmt):
    spec = gated.AUTH_SITES[site]
    items = authcookie.parse(text, default_domain=spec['domain'])
    if not items:
        raise typer.BadParameter('没解析出任何 cookie (支持: 头串 / JSON / Netscape txt)')
    names = {c['name'] for c in items}
    missing = [k for k in gated.needs(site) if k not in names]
    # 合并进已有桶: 同名覆盖, 不丢别的站点的 cookie
    old = {c.get('name'): c for c in state.load_cookies(site)}
    for c in items:
        c.setdefault('domain', spec['domain'])
        c.setdefault('path', '/')
        old[c['name']] = c
    state.save_cookies(site, list(old.values()))
    data = {'site': site, 'imported': len(old), 'cookies': sorted(old),
            'missing': missing, 'ok': not missing}
    if fmt == 'json':
        return data
    out = [f'已导入 {site}: {len(old)} 个 cookie ({", ".join(sorted(old))})']
    if missing:
        out.append(f'注意: 缺必填 {", ".join(missing)} —— 该站会直接拒绝')
    return '\n'.join(out)


def _do_rm(site, fmt):
    state.save_cookies(site, [])
    if fmt == 'json':
        return {'site': site, 'removed': True}
    return f'已清除 {site} 的登录态'


def _do_test(site, fmt, query):
    """实发一次, 看是不是真能过 —— 这是唯一诚实的验证方式"""
    fn = gated.AUTH_FN[site]
    items, missing = _status(site)
    if not items:
        raise typer.BadParameter(
            f'{site} 还没导入 cookie; 先 webtool auth set {site}')
    if missing:
        raise typer.BadParameter(
            f'{site} 缺必填 cookie: {", ".join(missing)}')
    try:
        rows = fn(query, 3)
    except gated.SiteAuthError as e:
        hint = getattr(e, 'hint', '') or gated.AUTH_SITES[site]['hint']
        data = {'site': site, 'ok': False, 'reason': str(e), 'hint': hint}
        if fmt == 'json':
            return data
        return f'{site} 不可用: {e}\n  → {hint}'
    except Exception as e:  # 网络/解析类
        data = {'site': site, 'ok': False, 'reason': str(e)}
        if fmt == 'json':
            return data
        return f'{site} 测试失败: {e}'
    data = {'site': site, 'ok': True, 'count': len(rows),
            'titles': [r.get('title') for r in rows[:3]]}
    if fmt == 'json':
        return data
    lines = [f'{site} 可用: 取到 {len(rows)} 条']
    for r in rows[:3]:
        lines.append(f"  {r.get('title')}")
    return '\n'.join(lines)


def _dispatch(action, site, cookie, file, query, fmt):
    """auth 的实际实现; typer 命令与 do_auth 入口都走这里"""
    fmt = (fmt or 'text').lower()
    act = (action or 'list').strip().lower()
    if act == 'list':
        if site:
            return _fmt_detail(_norm_site(site), fmt)
        return _fmt_list(fmt)
    site = _norm_site(site)
    if act == 'set':
        return _do_set(site, _read_input(cookie, file), fmt)
    if act == 'rm':
        return _do_rm(site, fmt)
    if act == 'test':
        return _do_test(site, fmt, query)
    raise typer.BadParameter(f'未知动作 {action!r}; 可用: list/set/rm/test')


@app.command('auth')
def auth_cmd(
        action: str = typer.Argument('list',
                                     help='list / set / rm / test'),
        site: str = typer.Argument(None,
                                   help='站点名: ' + ' / '.join(
                                       sorted(gated.AUTH_SITES))),
        cookie: str = typer.Option(None, '--cookie',
                                   help='直接给 Cookie 头串 (k=v; k2=v2)'),
        file: str = typer.Option(None, '--file', help='从文件读 (头串/JSON/Netscape)'),
        query: str = typer.Option('python', '--query', help='test 用的检索词'),
        fmt: str = Fmt):
    """管理需要登录态的站点 cookie (只显示名字, 不显示值)"""
    print(_dispatch(action, site, cookie, file, query, fmt))


def do_auth(args, cfg):
    """给 _entry_fn 用的入口 (args: 列表)"""
    argv = list(args or [])
    action = argv[0] if argv else 'list'
    site = argv[1] if len(argv) > 1 else None
    fmt = 'text'
    cookie = None
    path = None
    i = 2
    while i < len(argv):
        a = argv[i]
        if a in ('-f', '--format') and i + 1 < len(argv):
            fmt = argv[i + 1].lower()
            i += 2
            continue
        if a == '--cookie' and i + 1 < len(argv):
            cookie = argv[i + 1]
            i += 2
            continue
        if a == '--file' and i + 1 < len(argv):
            path = argv[i + 1]
            i += 2
            continue
        i += 1
    out = _dispatch(action, site, cookie, path, 'python', fmt)
    if fmt == 'json':
        import json
        print(json.dumps(out, ensure_ascii=False))
    else:
        print(out)
