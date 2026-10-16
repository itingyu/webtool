"""proxy 子命令: 全局/命名代理的增删查测 (get/set/unset/test/named/noproxy)"""
import sys
import time
from urllib.parse import quote

from webtool.core.secrets_store import redact, resolve_auth
from webtool.net.proxy.auth import _ask_password, _vault_has
from webtool.net.proxy.rules_cli import (_default_proxy_url, _load_rules_file,
                                         _proxy_is_used, _rules_path,
                                         _save_rules)
from webtool.net.proxy.store import (_MIGRATION_NOTES, _norm_proxy_url,
                                     _rule_syntax, _store_proxy_password,
                                     proxy_url_parts)


def _get(args, cfg):
    from webtool.net import rules as _R
    r = _R.router(cfg)
    for w in getattr(r, 'warnings', []):
        print(f'  ⚠ {w}', file=sys.stderr)
    spec = _load_rules_file(cfg)
    dflt = (spec.get('proxies') or {}).get('default')
    if dflt:
        print('默认代理:', redact(dflt if isinstance(dflt, str)
                                  else (dflt or {}).get('url')))
    else:
        print('默认代理: (未配置; 未命中规则一律直连)')
    print('default 动作:', spec.get('default') or '(未写, 见上面告警)')
    print('规则文件:', _rules_path(cfg))
    auth = cfg.get('proxy_auth') or {}
    if auth:
        print('proxy_auth:', ', '.join(f'{u}(密文)' for u in auth))
    for n in _MIGRATION_NOTES:
        print(f'已迁移: {n}')
    return 0


def _set(args, cfg):
    """`proxy set <url>` = 设命名代理 default + 补 default 动作

    URL 里**不许带密码**: 命令行参数会进 shell history 和 ps 输出, 等于明文
    外泄。密码要么已在保险库 (直接通过), 要么现场交互输入, 要么先 setpass。
    """
    val = args.value
    if not val:
        print('usage: webtool proxy set http://[user@]host:port  '
              '(支持 http/https/socks5://; 带用户名时密码交互输入)',
              file=sys.stderr)
        return 2
    url = _rule_syntax(val)
    scheme, user, password, host, port = proxy_url_parts(url)
    if scheme not in ('http', 'https', 'socks5', 'socks5h', 'socks4'):
        print(f'不支持的代理协议: {scheme or "(无)"} '
              '(支持 http/https/socks5/socks5h/socks4)', file=sys.stderr)
        return 2
    if not host:
        print('代理地址缺少主机名', file=sys.stderr)
        return 2
    if password:
        print('拒绝执行: URL 里带明文密码会进 shell history 和 ps 输出\n'
              f'处理: 先 webtool proxy setpass {user}@{host}'
              f'{":" + port if port else ""} "<密码>" (省略密码则交互输入),\n'
              f'      再 webtool proxy set {scheme}://{user}@{host}'
              f'{":" + port if port else ""}',
              file=sys.stderr)
        return 2
    hostport = f'{host}:{port}' if port else host
    if user and not _vault_has(f'{user}@{hostport}') and not _vault_has(user):
        # 库里没有这个凭据, 当场补录 (真终端不回显; 无 TTY 走 stdin)
        pwd = _ask_password(f'{user}@{hostport}')
        if pwd is None:
            return 130 if sys.stdin.isatty() else 2
        try:
            _store_proxy_password(user, pwd, host, port)
        except Exception as e:
            print(f'密码存储失败: {redact(str(e))}', file=sys.stderr)
            return 2
        print(f'密码已加密存进保险库 (条目 {user}@{hostport}); 出网时才解密')
    elif user:
        print(f'使用保险库已有条目 {user}@{hostport}')
    clean = (f'{scheme}://{quote(user, safe="")}@{hostport}' if user
             else f'{scheme}://{hostport}')
    spec = _load_rules_file(cfg)
    spec.setdefault('proxies', {})['default'] = clean
    if not spec.get('default'):
        spec['default'] = 'proxy:default'
        print("default 动作已设为 proxy:default (原来没写)")
    from webtool.net import rules as _R
    if _R.seed_rules(spec):
        print('已补一份默认分流规则 (一条国内直连, 其余走默认代理); '
              '看/改: webtool proxy rules, webtool proxy tidy')
    _save_rules(cfg, spec)
    print(f'默认代理已存: {redact(clean)} -> {_rules_path(cfg)}')
    return 0


def _unset(args, cfg):
    spec = _load_rules_file(cfg)
    proxies = spec.get('proxies') or {}
    gone = proxies.pop('default', None)
    if spec.get('default') in ('proxy', 'proxy:default'):
        spec['default'] = 'direct'
    _save_rules(cfg, spec)
    print('默认代理已清除' if gone else '(本来就没有默认代理)')
    refs = [i for i, r in enumerate(spec.get('rules') or [])
            if isinstance(r, dict)
            and str(r.get('action')) in ('proxy', 'proxy:default')]
    if refs:
        print(f'⚠ 规则 {refs} 还引用默认代理 (action=proxy), '
              '现在会解析失败; 请改成 proxy:<名字> 或 direct', file=sys.stderr)
    return 0


def _test(args, cfg):
    """探活一条代理; 目标 URL 可换 (`--url`)

    只回"OK/FAIL"是不够的, 这里必须把两件事说清楚, 否则结论会误导人:
      - 通的这条线, 与目标 URL 按规则表实际会走的线, 是不是同一条
      - 这条代理有没有被任何规则/default 引用 (没被引用 = 测通也没流量走它)

    探活本身走 `net.http.build_opener`, 与真实取数同一条通道 —— 早前这里是
    裸 `urllib` 装 `ProxyHandler`, 环境里 `no_proxy='*'`/`.host` 会让它静默直连
    并把死代理报成 OK; 现在显式指定的代理不再被环境绕过, 假 OK 不复现。
    """
    from webtool.net import rules as _R
    target = (getattr(args, 'url', None) or
              'https://www.google.com/generate_204')
    val = None
    if args.value:
        # `proxy test 名字` 该测那条命名代理 —— 之前会被当成主机名解析成
        # `http://名字:` 去撞 DNS, 报个 "Name does not resolve" 让人莫名其妙
        nm = str(args.value).strip()
        named = (_load_rules_file(cfg).get('proxies') or {}).get(nm)
        if named:
            print(f'{nm} = {redact(str(named))}')
            val = str(named)
        else:
            val = _rule_syntax(nm)
            if '://' not in str(args.value) and '.' not in nm:
                print(f'⚠ 没有名为 {nm} 的命名代理, 按主机名解析成 {val}; '
                      f'看现有名字: webtool proxy rules', file=sys.stderr)
    else:
        val = _default_proxy_url(cfg)
    if not val:
        print('no proxy to test. use: webtool proxy test http://127.0.0.1:2080',
              file=sys.stderr)
        return 2
    verdict = None
    try:
        verdict = _R.load_router(cfg).explain(target)
    except Exception as e:
        print(f'⚠ 规则表读不出来 ({redact(str(e))[:80]}), 只测这条代理本身',
              file=sys.stderr)

    import urllib.request
    from webtool.net import http as _http
    try:
        # 出网前补上保险库里的密码; 缺失要明确报错而不是拿空密码去撞 407
        val = resolve_auth(val)
        if val.startswith('socks'):
            import socks  # noqa: F401
        opener = _http.build_opener(val)
        t0 = time.time()
        from webtool.net.transport import headers_for as _hf
        r = opener.open(urllib.request.Request(
            target, headers=_hf('nav', target, full=True)), timeout=10)
        body = r.read(64)
        print(f'OK {r.status} {len(body)}B in {time.time()-t0:.1f}s '
              f'via {redact(val)}')
    except Exception as e:
        print(f'FAIL via {redact(val)}: {redact(str(e))}', file=sys.stderr)
        return 1

    if target.endswith('/generate_204') and r.status != 204:
        print(f'  ⚠ 期望 204, 实得 {r.status} —— 代理可能返回了自家页面 '
              '(门户劫持/需要认证), 不能只看"有响应"', file=sys.stderr)
    if verdict:
        rp = verdict.get('resolved_proxy')
        same = rp and _norm_proxy_url(rp) == _norm_proxy_url(val)
        line = f'  目标 {target} 规则判定: {verdict.get("action")}'
        if rp:
            line += f' → {redact(rp)}'
        line += '  (与所测一致)' if same else '  ⚠ 与所测代理不是一条线, 该目标的真实线路不受本次结果影响'
        print(line)
    if not _proxy_is_used(cfg, val):
        print('  ⚠ 这条代理没有被任何规则或 default 引用 —— 测通了也没有流量走它 '
              '(要让它生效: webtool proxy set 把它设成默认, 或 rule add ... proxy:<名字>)',
              file=sys.stderr)
    return 0


def _named(args, cfg):
    """named <名字> <代理URL> / named del <名字> / named list — 配命名代理

    规则表里的 `proxy:<名字>` 靠这里配: 密码进保险库, rules.json 只留
    `user@host`, 与全局 proxy 走同一套凭据机制 (rules.json 是人工维护的文件,
    明文密码不能落进去)。
    """
    spec = _load_rules_file(cfg)
    proxies = spec.setdefault('proxies', {})
    sub = getattr(args, 'value', None)
    if sub in (None, '', 'list'):
        if not proxies:
            print('未配置命名代理\n添加: webtool proxy named <名字> <代理URL>')
            return 0
        print('命名代理:')
        for k, v in proxies.items():
            url = v.get('url') if isinstance(v, dict) else v
            print(f'  {k:14} {redact(url)}')
        return 0
    if sub == 'del':
        name = getattr(args, 'user', None)
        if not name:
            print('用法: webtool proxy named del <名字>', file=sys.stderr)
            return 2
        if name not in proxies:
            print(f'没有名为 {name} 的代理', file=sys.stderr)
            return 2
        proxies.pop(name)
        _save_rules(cfg, spec)
        print(f'已删除命名代理 {name}')
        return 0
    # named <名字> <url>  → 位置参数: value=名字, user=url
    name, url = sub, getattr(args, 'user', None)
    if not name or not url:
        print('用法: webtool proxy named <名字> <代理URL>\n'
              '      webtool proxy named del <名字>\n'
              '      webtool proxy named list', file=sys.stderr)
        return 2
    url = _rule_syntax(url)
    scheme, user, password, host, port = proxy_url_parts(url)
    if scheme not in ('http', 'https', 'socks5', 'socks5h', 'socks4'):
        print(f'不支持的代理协议: {scheme or "(无)"}', file=sys.stderr)
        return 2
    if not host:
        print('代理地址缺少主机名', file=sys.stderr)
        return 2
    clean = f'{scheme}://{host}' + (f':{port}' if port else '')
    if password:
        # 同 proxy set: 命令行明文密码 = 进 history 和 ps, 拒绝
        print('拒绝执行: URL 里带明文密码会进 shell history 和 ps 输出\n'
              f'处理: webtool proxy setpass {user}@{host}'
              f'{":" + port if port else ""} 后重试, 或 URL 只写 user@host '
              '(密码库里有就直接用, 没有会交互补录)', file=sys.stderr)
        return 2
    if user:
        hostport = f'{host}:{port}' if port else host
        if not _vault_has(f'{user}@{hostport}') and not _vault_has(user):
            pwd = _ask_password(f'{user}@{hostport}')
            if pwd is None:
                return 130 if sys.stdin.isatty() else 2
            try:
                _store_proxy_password(user, pwd, host, port)
            except Exception as e:
                print(f'密码存储失败: {redact(str(e))}', file=sys.stderr)
                return 2
            print(f'密码已加密存进保险库 (条目 {user}@{hostport}); 出网时才解密')
        clean = (f'{scheme}://{quote(user, safe="")}@{hostport}')
    proxies[name] = {'url': clean}
    _save_rules(cfg, spec)
    print(f'命名代理 {name} = {redact(clean)} -> {_rules_path(cfg)}')
    return 0


def _noproxy(args, cfg):
    """列出当前规则命中的走向, 便于确认分流是否符合预期"""
    from webtool.net import rules as R
    r = R.load_router(cfg)
    for u in (args.value.split(',') if args.value else [
            'https://www.bing.com/search?q=x',
            'https://www.google.com/search?q=x',
            'https://www.baidu.com/s?wd=x',
            'https://www.czce.com.cn/cn/index.jsp']):
        e = r.explain(u.strip())
        via = e['resolved_proxy'] or '直连'
        idx = e['rule_index']
        src = f'规则[{idx}]' if idx is not None else '默认'
        print(f'  {u[:48]:50} → {src:10} {via}')
    return 0
