"""pkg —— 包管理器/任意命令透传, 线路由规则表换算成环境变量

    webtool pkg npm install lodash
    webtool pkg git clone https://github.com/x/y
    webtool pkg --no-proxy pip install -r req.txt

npm/pip/git 这类工具各自认代理的方式五花八门 (npm 认自己的 config, git 认
http.proxy 配置, pip 认 env), 统一入口在这里做一次决策, 然后用**环境变量**
交给子进程 —— 这是所有主流工具都认的公共接口 (curl/go/npm/pip/git 全认
HTTP(S)_PROXY, socks 另加 ALL_PROXY)。

线路决策与 fetch/zen 同源: 命令行参数里抽 URL (含 git 的 git@host:path
scp 写法), 逐个问规则表; 抽不到就用该工具的默认源 (npm→registry.npmjs.org,
pip→pypi.org, git 无 URL→github.com...)。多个目标被判到不同线路时**拒绝
执行并列出判定** —— 静默挑一条会让人以为另一条也走了代理。

本进程自己的出网层在三处堵死了环境代理 (trust_env=False / 空 ProxyHandler),
所以往子进程 env 里塞代理不会反过来影响 webtool 自身的请求。
"""
import os
import re
import sys

# 各工具的默认源: 命令行里抽不到 URL 时用它问路由表
TOOL_DEFAULT_URL = {
    'npm': 'https://registry.npmjs.org',
    'pnpm': 'https://registry.npmjs.org',
    'yarn': 'https://registry.yarnpkg.com',
    'pip': 'https://pypi.org/simple',
    'pip3': 'https://pypi.org/simple',
    'uv': 'https://pypi.org/simple',
    'cargo': 'https://crates.io',
    'go': 'https://proxy.golang.org',
    'gem': 'https://rubygems.org',
    'composer': 'https://packagist.org',
    'git': 'https://github.com',          # git pull/fetch 的 remote 多半是它
}

_URL_RE = re.compile(r'(?:https?|ssh)://[^\s\'"<>]+')
# git 的 scp 写法: git@github.com:owner/repo.git (host 后必须跟冒号, 排除盘符 C:\)
_SCP_RE = re.compile(r'\b[\w.-]+@([\w.-]+):\S+')


def _candidate_urls(tool, args):
    """从命令行参数里抽目标 URL; 抽不到回落该工具的默认源"""
    urls = []
    blob = ' '.join(args)
    urls += _URL_RE.findall(blob)
    for m in _SCP_RE.finditer(blob):
        host = m.group(1)
        if host and '.' in host:                    # 排除 ./a:b 这类路径
            urls.append(f'ssh://{host}/')
    if not urls:
        d = TOOL_DEFAULT_URL.get(tool)
        if d:
            urls.append(d)
    return urls


_PLACEHOLDER = 'https://pkg.webtool.invalid/'   # 未知工具且抽不到 URL: 占位问默认动作


def _decide(urls, cfg):
    """逐个 URL 问规则表 → {url: 代理URL 或 None}。线路冲突时抛 _Mixed"""
    from webtool.net import rules as _R
    r = _R.router(cfg)
    out = {}
    for u in urls:
        try:
            out[u] = r.proxy_for(u)
        except _R.RuleError as e:
            raise SystemExit(f'error: {e}')
    proxies = {p for p in out.values() if p}
    if len(proxies) > 1 or (proxies and None in out.values()):
        raise _Mixed(out)
    return out, (next(iter(proxies)) if proxies else None)


class _Mixed(Exception):
    def __init__(self, decisions):
        self.decisions = decisions


def _resolve_cli_proxy(val, cfg):
    """--proxy 取值: direct / 代理名 / 完整 URL"""
    from webtool.net import rules as _R
    if val == 'direct':
        return None
    r = _R.router(cfg)
    if val in (r.proxies or {}):
        spec = r.proxies[val]
        return spec.get('url') if isinstance(spec, dict) else spec
    if '://' in val:
        return val
    known = ', '.join(sorted(r.proxies or {})) or '(无)'
    raise SystemExit(f"error: --proxy 未知代理名 {val!r}; 现有: {known}")


def _build_env(proxy):
    """代理 URL → 子进程环境变量。原环境里的代理键全部清掉:
    线路只认配置/规则表, 不信继承来的环境 (同出网层 trust_env=False 的口径)"""
    env = os.environ.copy()
    for k in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY',
              'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy'):
        env.pop(k, None)
    if not proxy:
        return env, '直连'
    if proxy.startswith('socks'):
        # git/curl 认 ALL_PROXY 里的 socks; npm 新版也认。http(s) 系工具
        # 对 socks 支持参差, 报错时会看到清晰失败而不是静默直连
        env['ALL_PROXY'] = proxy
    else:
        env['HTTP_PROXY'] = env['HTTPS_PROXY'] = proxy
        env['http_proxy'] = env['https_proxy'] = proxy
    env['NO_PROXY'] = env['no_proxy'] = 'localhost,127.0.0.1,::1'
    from webtool.core.secrets_store import redact
    return env, f'走代理 {redact(proxy)}'


def handle(argv, cfg, no_proxy=False, proxy=None):
    """webtool pkg [--no-proxy] [--proxy <名|URL|direct>] <命令> [参数...]"""
    if not argv:
        print('usage: webtool pkg [--no-proxy|--proxy <名|URL|direct>] '
              '<命令> [参数...]\n'
              '例: webtool pkg npm install lodash\n'
              '    webtool pkg git clone https://github.com/x/y\n'
              '线路按规则表判定, 换算成 HTTP(S)_PROXY/ALL_PROXY 交给子进程',
              file=sys.stderr)
        return 2
    tool, rest = argv[0], argv[1:]
    from webtool.core.secrets_store import redact
    urls = _candidate_urls(tool, rest)
    if not urls:
        # 未知工具且参数里没有 URL: 占位问路由表默认动作 —— 与全工具的
        # 'auto' 口径一致 (未命中规则走 default), 而不是悄悄直连
        urls = [_PLACEHOLDER]
    if proxy:
        forced = _resolve_cli_proxy(proxy, cfg)
        decisions = {u: forced for u in urls}
        via = ('直连 (--proxy direct)' if forced is None
               else f'走代理 {redact(forced)} (--proxy)')
    elif no_proxy:
        decisions, forced, via = {}, None, '直连 (--no-proxy)'
    else:
        try:
            decisions, forced = _decide(urls, cfg)
        except _Mixed as e:
            print('拒绝执行: 参数里的目标被判到不同线路, 挑一条会误导\n'
                  '要强制单一线路请加 --proxy <名|URL|direct>:', file=sys.stderr)
            for u, p in e.decisions.items():
                print(f'  {u} → {p or "直连"}', file=sys.stderr)
            return 2
        via = '直连' if not forced else f'走代理 {redact(forced)}'
    # 命中信息给 stderr: 执行结果 stdout 必须干净 (管道里要能接)
    for u, p in decisions.items():
        if p is not None and forced is not None and p != forced:
            print(f'⚠ {u} 判为 {redact(p)}, 已被 --proxy 覆盖', file=sys.stderr)
    print(f'[pkg] {tool} → {via}', file=sys.stderr)
    env, _ = _build_env(forced)
    # Python 起子进程 (不 execvpe 替换自身): 退出码透传, 找不到命令给可读报错
    import subprocess
    try:
        return subprocess.run(argv, env=env).returncode
    except FileNotFoundError:
        print(f'error: 找不到命令: {tool}', file=sys.stderr)
        return 127
    except KeyboardInterrupt:
        return 130
