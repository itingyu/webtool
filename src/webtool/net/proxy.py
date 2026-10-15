"""代理与全局配置

线路只有一个决策点: `~/.webtool/rules.json` (net.rules)。
  - `proxies` — 命名代理表 (`default` 是未命中规则时的默认代理)
  - `default` — 未命中规则时的动作: direct / block / proxy:<名>
  - `rules` / `geoip_db` / `geosite_db` / `asn_db` — 分流规则与其依赖的库
  - `proxy_auth` — 账号密码**密文** (core.secrets_store 管加密, 本模块只读写)

config.json 里的 `proxy` / `fetch_proxy` / `proxy_rules` 已废弃, load_config
会自动迁进 rules.json 并从 config.json 删掉。运行期 `cfg['proxy']` 只剩一个
含义: 本次运行的强制覆盖 (只有 'direct', 由 --no-proxy 写入)。

**任何输出与报错一律脱敏** (secrets_store.redact): 原实现把完整代理 URL 拼进
rank/zen 的错误串, 密码会进到 CLI 输出、用户贴的日志与 issue 里。
"""
import json
import os
import re
import sys
import time
from urllib.parse import quote, unquote

from webtool.core.config_data import USER_DIR
from webtool.core.secrets_store import (drop_password, redact, resolve_auth,
                                       status as secret_status, store_password)

CONFIG_PATH = str(USER_DIR / 'config.json')

DEFAULTS = {
    'timeout': 15,
    'ua': 'auto',
    'extract': 'auto',           # 正文提取器: auto=内容层择优 / 具名=只用那一个
    'cache_dir': str(USER_DIR / 'cache'),
    # TLS (实际决策在 webtool.core.tls, 这里只负责存)
    'ssl_verify': True,          # 证书校验总开关
    'ca_bundle': None,           # 自定义 CA 包路径 (替代系统 CA)
    'verify_hosts': [],          # 关校验的域名单 (自签/过期证书的交易所站)
    # 代理
    'proxy_auth': {},            # 引用名 → 密码密文 (user@host 或裸 user)
    'rules_file': None,          # 规则文件路径, 默认 ~/.webtool/rules.json
    'geoip_db': None,            # GeoIP 国家库 (rules.json 里的同名字段优先)
    'geosite_db': None,          # geosite 域名分类库 (同上)
    'asn_db': None,              # GeoIP ASN 库 (同上)
    'proxy_dns_ttl': 300,        # 规则里查 GeoIP 时的 DNS 缓存秒数
}

# DEFAULTS 里没登记的键会在 load_config 被过滤掉 —— 新增配置项必须同时加这里
_KNOWN = set(DEFAULTS)
# 已废弃的持久配置键: 迁进 rules.json 后从 config.json 删除
_LEGACY_KEYS = ('proxy', 'fetch_proxy', 'proxy_rules')


_MIGRATION_NOTES = []          # 本次进程里迁移做了什么; proxy get 时展示


def _read_json(path):
    try:
        with open(path, encoding='utf-8') as f:
            v = json.load(f)
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def _write_json(path, data):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _migrate_legacy_config():
    """config.json 的 proxy / fetch_proxy / proxy_rules 一次性迁进 rules.json

    - proxy → rules.json 的 proxies.default + default='proxy:default'
      (语义等价: 未命中规则走原全局代理)
    - fetch_proxy 的"抓取整线覆盖"没了 —— 分流只按目标 URL 判。URL 先落成
      命名代理 fetch, 要给某些目标用就写 proxy:fetch 规则
    - proxy_rules 内联表 → 挪进规则文件 (文件已有规则时不覆盖, 键保留并告警)
    - rules.json 顶层废弃的 priority 键顺手删掉
    幂等: 迁过的键不在 config.json 里, 第二次进来什么都不做。
    """
    if not os.path.exists(CONFIG_PATH):
        return
    raw = _read_json(CONFIG_PATH)
    if not any(k in raw and raw[k] for k in _LEGACY_KEYS):
        return
    try:
        rules_path = os.path.expanduser(raw.get('rules_file')
                                        or str(USER_DIR / 'rules.json'))
        spec = _read_json(rules_path)
        moved, kept, kept_keys = [], [], set()

        if raw.get('proxy'):
            # 规则文件是唯一事实来源: 遗留键不许覆盖已经明确写下的 proxies.default
            # —— 否则任何"暂时把 config.json 改成死地址"的外部动作 (测试、脚本、
            # 手误留下的快照) 都会顺手改掉现网分流, 而用户看到的却是"我没改, 它
            # 自己变的"(真实事故: 跑一次 tests/test_smoke.py, 2080 变 :9)。
            cur = (spec.get('proxies') or {}).get('default')
            if cur and _norm_proxy_url(cur) != _norm_proxy_url(raw['proxy']):
                kept.append(f'proxy {redact(raw["proxy"])} 未迁: 规则文件里 '
                            f'proxies.default 已是 {redact(cur)} (规则文件优先); '
                            f'确实要换默认代理请用 webtool proxy set')
            else:
                spec.setdefault('proxies', {})['default'] = raw['proxy']
                if not spec.get('default'):
                    spec['default'] = 'proxy:default'
                moved.append(f"proxy {redact(raw['proxy'])} → proxies.default")
        if raw.get('fetch_proxy'):
            spec.setdefault('proxies', {})['fetch'] = raw['fetch_proxy']
            moved.append(f"fetch_proxy {redact(raw['fetch_proxy'])} → "
                         '命名代理 "fetch" (整线覆盖已废弃, 按需写 '
                         "proxy:fetch 规则)")
        if raw.get('proxy_rules'):
            if (isinstance(raw['proxy_rules'], dict) and raw['proxy_rules']
                    and not (spec.get('rules') or spec.get('proxies'))):
                for k in ('default', 'rules', 'proxies'):
                    if k in raw['proxy_rules']:
                        spec[k] = raw['proxy_rules'][k]
                moved.append('proxy_rules (内联) → 规则文件')
            else:
                # 规则文件已有内容、或形状我们读不懂 (不是 dict) —— 一律原样留着
                # 让人自己合。悄悄删掉一个读不懂的键才是真的数据丢失。
                kept.append('proxy_rules 未迁 (规则文件已有内容或形状不认识), '
                            '原样保留, 请手工合并')
                kept_keys.add('proxy_rules')

        if 'priority' in spec:
            del spec['priority']
            moved.append("priority 键已删 (废弃: 规则一律按文件顺序生效)")

        if moved:
            _write_json(rules_path, spec)
        # 只有真正迁走的键才从 config.json 删掉: 用 kept(消息列表) 判会恒为真,
        # 于是"没迁成"的 proxy_rules 也被删 —— 那才叫数据丢失。
        new_raw = {k: v for k, v in raw.items()
                   if not (k in _LEGACY_KEYS and k not in kept_keys)}
        _write_json(CONFIG_PATH, new_raw)
        _MIGRATION_NOTES.extend(moved + kept)
    except Exception as e:                     # noqa: BLE001
        # 迁移失败不能让整个工具起不来: 老配置原样保留
        _MIGRATION_NOTES.append(f'迁移失败 (老配置原样保留): {redact(str(e))}')


def load_config():
    _migrate_legacy_config()
    cfg = json.loads(json.dumps(DEFAULTS))  # deep copy
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding='utf-8') as f:
                user = json.load(f)
            cfg.update({k: v for k, v in user.items() if k in _KNOWN})
        except Exception:
            pass
    return cfg


def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(CONFIG_PATH, 0o600)   # 含密文, 别让同机其他用户读到
    except OSError:
        pass


def _rule_syntax(val):
    """补协议前缀: '127.0.0.1:2080' → 'http://127.0.0.1:2080'"""
    val = val.rstrip('/')
    if not val.startswith(('http://', 'https://', 'socks5://', 'socks5h://',
                           'socks4://')):
        val = 'http://' + val
    return val


def proxy_url_parts(url):
    """代理 URL → (scheme, user, password, host, port)

    为什么不直接 `urlsplit`: 密码里出现 `/` 时 netloc 会被 urlsplit 在 `/` 处
    截断 (RFC 3986 规定 `/` 结束 authority), 于是
    `http://u:p/w@h:2080` 被解析成 host=`h` 路径=`/w@h:2080`, 进一步取 port
    就抛 "Port could not be cast"。而 `p/w` 这种密码并不罕见。

    所以这里按代理 URL 的实际形状手工拆: 先切出 scheme, 再**从右往左**按
    最后一个 `@` 分出 userinfo 与 host:port (代理 URL 里 host 在最后, 密码
    里的 `@` 不会误伤), 最后在 userinfo 里按第一个 `:` 分用户名与密码。
    返回的 user/password 已 percent-decode。
    """
    s = str(url or '').strip()
    m = re.match(r'^([a-zA-Z][a-zA-Z0-9+.-]*)://(.*)$', s)
    if not m:
        return '', '', '', '', ''
    scheme, rest = m.group(1).lower(), m.group(2)
    rest = rest.split('/', 1)[0] if '/' in rest.split('@')[-1] else rest
    userinfo, sep, hostport = rest.rpartition('@')
    user = password = ''
    if sep and userinfo:
        raw_user, has_pw, raw_pw = userinfo.partition(':')
        user = unquote(raw_user)
        if has_pw:
            password = unquote(raw_pw)
    hostport = hostport.rsplit('@', 1)[-1]
    host, _, port_s = hostport.partition(':')
    return scheme, user, password, host, port_s


def hostport_of(url):
    """'http://u@h:2080' → 'h:2080' (给剥掉凭据后重建 URL 用)"""
    _, _, _, host, port = proxy_url_parts(url)
    return f'{host}:{port}' if port else host


def _store_proxy_password(user, password, host, port):
    """代理密码进保险库, 键带主机 (user@host:port) —— 两台代理同一个用户名、
    不同密码互不覆盖。返回条目名, 给提示文案用。"""
    hostport = f'{host}:{port}' if port else host
    store_password(f'{user}@{hostport}', password)
    return f'{user}@{hostport}'


def _default_proxy_url(cfg):
    """rules.json 里的命名代理 default (没有就 None)"""
    spec = _load_rules_file(cfg)
    d = (spec.get('proxies') or {}).get('default')
    return (d or {}).get('url') if isinstance(d, dict) else d


def handle(args, cfg):
    """webtool proxy <子命令>"""
    action = args.action
    # `proxy rule add <JSON> <动作>` 是三层, 这里拆成 _ruleadd/_ruledel
    if action == 'rule':
        sub = getattr(args, 'value', None)
        if sub == 'del':
            return _ruledel(args, cfg)
        if sub == 'add':
            return _ruleadd(args, cfg)
        print('用法: webtool proxy rule add \'<match JSON>\' <动作> | '
              'webtool proxy rule del <序号>', file=sys.stderr)
        return 2
    fn = _ACTIONS.get(action)
    if fn is None:
        print('usage: webtool proxy ' + '|'.join(sorted(_ACTIONS)),
              file=sys.stderr)
        return 2
    if action in ('setpass', 'delpass'):
        # 这两个子命令的位置参数顺序是 `<用户名> [<密码>]`, 落到 value/user 上;
        # 而 _setpass/_delpass 按 user=用户名 / value=密码 取。这里对齐, 否则
        # `proxy setpass bob` 会被当成没给用户名, 直接打 usage。
        args.value, args.user = args.user, args.value
    return fn(args, cfg)


# 各子命令

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


def _norm_proxy_url(u):
    """比线路用: 只看 scheme://host:port, 忽略路径/尾斜杠/大小写"""
    s = str(u or '').strip().rstrip('/')
    if '://' not in s:
        s = 'http://' + s
    return s.lower()


def _proxy_is_used(cfg, val):
    """这条代理是否被规则或 default 引用 —— 测通了但没人用它, 等于白测"""
    spec = _load_rules_file(cfg)
    want = _norm_proxy_url(val)
    names = [n for n, p in (spec.get('proxies') or {}).items()
             if _norm_proxy_url(p.get('url') if isinstance(p, dict) else p) == want]
    if not names:
        return False
    d_act = (spec.get('default') or 'direct')
    if d_act.startswith('proxy') and (d_act.split(':', 1)[1].strip() or 'default') in names:
        return True
    for r in (spec.get('rules') or []):
        a = str((r or {}).get('action') or '')
        if a.startswith('proxy') and (a.split(':', 1)[1].strip() or 'default') in names:
            return True
    return False


def _test(args, cfg):
    """探活一条代理; 目标 URL 可换 (`--url`)

    只回"OK/FAIL"是不够的, 这里必须把两件事说清楚, 否则结论会误导人:
      - 通的这条线, 与目标 URL 按规则表实际会走的线, 是不是同一条
      - 这条代理有没有被任何规则/default 引用 (没被引用 = 测通也没流量走它)

    探活本身走 `core.http.build_opener`, 与真实取数同一条通道 —— 早前这里是
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
    from webtool.core import http as _http
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


def _ask_password(ref):
    """终端交互读密码 (getpass, 不回显); 无 TTY 时读 stdin 一行 (管道场景)。

    返回 None = 用户中断/给了空行。必须先判 isatty 再决定走哪条: getpass
    在无 TTY 时会静默降级成读 stdin 并往 stderr 打警告, 两条路不能混。"""
    if sys.stdin.isatty():
        import getpass
        try:
            return getpass.getpass(f'输入 {ref} 的代理密码 (不回显): ')
        except (EOFError, KeyboardInterrupt):
            print(file=sys.stderr)
            return None
        except Exception as e:
            # 没有 /dev/tty (某些容器/重定向环境): 退回读 stdin, 别直接崩
            print(f'无法交互输入 ({e}); 请改用管道: '
                  f'echo "<密码>" | webtool proxy setpass {ref}',
                  file=sys.stderr)
            return None
    return sys.stdin.readline().rstrip('\n') or None


def _vault_has(ref):
    from webtool.core.secrets_store import _load_store
    return ref in _load_store()


def _setpass(args, cfg):
    """把账号密码加密存进保险库, 配置里只留用户名

    密码来源按优先级:
      1. 终端交互 (getpass, **不回显**) —— 真终端下的默认路径 (省略密码参数)
      2. stdin 管道 —— 供 Agent / 脚本 `echo pw | webtool proxy setpass <用户>`
      3. 位置参数 `<密码>` —— **会留在 shell history 和 ps 输出里**, 只在
         明知无泄漏环境 (CI 临时容器) 时用
    """
    user = args.user
    if not user:
        print('usage: webtool proxy setpass <用户名|用户名@主机> [<密码>]', file=sys.stderr)
        print('  省略密码则终端交互输入 (不回显); 也可从 stdin 管道读',
              file=sys.stderr)
        return 2
    pwd = args.value
    if pwd is None:
        pwd = _ask_password(user)
        if pwd is None:
            return 130 if sys.stdin.isatty() else 2
    if not pwd:
        print('密码为空', file=sys.stderr)
        return 2
    try:
        created = store_password(user, pwd)
    except Exception as e:
        print(f'存储失败: {redact(str(e))}', file=sys.stderr)
        return 2
    print(f'{"已新增" if created else "已更新"} {user} 的密码 '
          f'(密文存于 {CONFIG_PATH} 的 proxy_auth)\n'
          f'用法: webtool proxy set http://{user}@host:port')
    return 0


def _delpass(args, cfg):
    if not args.user:
        print('usage: webtool proxy delpass <用户名>', file=sys.stderr)
        return 2
    if not drop_password(args.user):
        print(f'保险库里没有 {args.user}', file=sys.stderr)
        return 2
    print(f'已删除 {args.user} 的密码')
    return 0


def _passwd(args, cfg):
    for k, v in secret_status().items():
        print(f'  {k:12} {v}')
    return 0


def _rules(args, cfg):
    """规则查看 / 试算"""
    from webtool.net import rules as R
    r = R.load_router(cfg)
    for w in getattr(r, 'warnings', []):
        print(f'  ⚠ {w}', file=sys.stderr)
    if args.value:                       # 带 URL → 试算这条请求走哪条线路
        print(json.dumps(r.explain(args.value), ensure_ascii=False, indent=1))
        return 0
    spec = _load_rules_file(cfg)
    print(f'默认动作: {getattr(r, "default_action", "direct")}')
    print(f'命名代理: {json.dumps({k: redact(v.get("url") if isinstance(v, dict) else v) for k, v in (getattr(r, "proxies", {}) or {}).items()}, ensure_ascii=False)}')
    print(f'规则文件: {_rules_path(cfg)}')
    rules = (spec or {}).get('rules')
    if not rules:
        print('未配置规则')
        print('添加: webtool proxy rule add \'{"domain":["*.cn"]}\' direct')
        return 0
    for i, rule in enumerate(rules):
        act, name = R.resolve_action(rule.get('action'))
        via = f' → {name}' if name else ''
        print(f'  [{i}] {json.dumps(rule.get("match"), ensure_ascii=False)}'
              f'  ⇒ {act}{via}')
    # 有冗余就当场说, 别等用户自己发现规则表越长越难维护
    try:
        _, report = R.tidy_spec(spec)
    except Exception:
        report = []
    if report:
        # "与默认同结果"这类不算结构问题 (写出来当文档很常见), 不计入唠叨
        n = sum(1 for x in report if x.startswith('〔')
                and not x.startswith(('〔同默认〕', '〔提示〕')))
        if n:
            print(f'\n⚠ {n} 处可合并/冗余 —— 跑 webtool proxy tidy 预览, '
                  f'加 --apply 落盘 (会先备份)')
    return 0


def _tidy(args, cfg):
    """规则表合并: 同动作合并 + 冗余条目去除 + 与默认动作重复的规则去掉

    默认干跑 (只打印报告和结果), `--apply` 才落盘 —— 规则表是分流的总闸,
    偷偷改掉会让人查半天"为什么昨天还走代理今天直连了"。
    """
    from webtool.net import rules as R
    spec = _load_rules_file(cfg)
    try:
        new, report = R.tidy_spec(spec)
    except Exception as e:
        print(f'合并失败: {e}', file=sys.stderr)
        return 2
    if not report:
        print('规则表已经是合并后的形态, 无需改动')
        return 0
    print('\n'.join(report))
    before = len(spec.get('rules') or [])
    after = len(new.get('rules') or [])
    print(f'\n条数 {before} → {after}')
    if not getattr(args, 'apply', False):
        print('\n(干跑, 未改动。--apply 落盘, 会先备份原文件)\n')
        print(json.dumps(new, ensure_ascii=False, indent=1))
        return 0
    path = _rules_path(cfg)
    bak = None
    if os.path.isfile(path):
        bak = f'{path}.bak-{time.strftime("%Y%m%d-%H%M%S")}'
        try:
            import shutil
            shutil.copy2(path, bak)
        except OSError as e:
            print(f'备份失败, 未改动: {e}', file=sys.stderr)
            return 2
    _save_rules(cfg, new)
    print(f'\n已写入 {path}' + (f' (备份 {bak})' if bak else ''))
    print('校验: webtool proxy rules / webtool proxy rules https://google.com')
    return 0


def _ruleadd(args, cfg):
    """`proxy rule add <match JSON> <动作>`  →  args.user=JSON, args.act=动作"""
    from webtool.net import rules as R
    spec = _load_rules_file(cfg)
    raw = getattr(args, 'user', None)
    act = getattr(args, 'act', None)
    if not raw or not act:
        print('用法: webtool proxy rule add \'<match JSON>\' '
              '<direct|proxy|block|proxy:<名字>>', file=sys.stderr)
        return 2
    try:
        m = json.loads(raw)
    except ValueError as e:
        print(f'match 必须是合法 JSON: {e}\n'
              f'提示: shell 会吃掉双引号, 整段用单引号包起来;\n'
              f'  webtool proxy rule add \'{{"port":[8080,9000-9100]}}\' direct\n'
              f'注意端口区间写成字符串或数字都行, 但 [9000-9100] 少了引号/逗号'
              f'会被解析成减法', file=sys.stderr)
        return 2
    if not isinstance(m, dict) or not m:
        print('match 必须是非空 JSON 对象, 如 {"domain":["*.cn"]}',
              file=sys.stderr)
        return 2
    try:
        act_v, name = R.resolve_action(act)
    except R.RuleError as e:
        print(str(e), file=sys.stderr)
        return 2
    if act_v == 'proxy' and name and name not in (spec.get('proxies') or {}):
        print(f'注意: 命名代理 "{name}" 尚未在 proxies 里定义, '
              f'该规则会解析失败', file=sys.stderr)

    # 插入位置: 默认追加末尾; --first 插 [0]; --pos N 插第 N 位。
    # 追加位置在宽规则之后会被整条吃掉 (first-match-wins), 所以默认插到最前。
    # 所以下面还要跑一次覆盖试算, 被吃掉就直接说, 别等用户自己发现规则没用。
    rules = spec.setdefault('rules', [])
    first = bool(getattr(args, 'first', False))
    pos = getattr(args, 'pos', None)
    if first and pos is not None:
        print('--first 与 --pos 只能给一个', file=sys.stderr)
        return 2
    if first:
        at = 0
    elif pos is None:
        at = len(rules)
    else:
        try:
            at = int(pos)
        except (TypeError, ValueError):
            print('--pos 要整数', file=sys.stderr)
            return 2
        if not 0 <= at <= len(rules):
            print(f'--pos 越界 (0 ~ {len(rules)})', file=sys.stderr)
            return 2

    rules.insert(at, {'match': m, 'action': act})
    _save_rules(cfg, spec)
    print(f'规则已加 (第 {at} 条): '
          f'{json.dumps(m, ensure_ascii=False)} ⇒ {act}')

    # 覆盖试算: 插进去也可能永远不生效, 当场说清楚
    if at > 0:
        try:
            router = R.Router(spec)
            hit = R.shadow_check(router, m, act, at)
        except Exception:                                # noqa: BLE001
            hit = None
        if hit:
            print(f'⚠ 这条规则不会生效: 上面的规则[{hit[0]}] ({hit[1]}) '
                  f'已经覆盖了同样的域名, {("priority=direct 下 direct 规则压过 proxy 规则" if router.priority != "order" else "顺序在前")}'
                  f'。要它生效请用 --first 或 --pos 插到规则[{hit[0]}] 之前',
                  file=sys.stderr)
    return 0


def _ruledel(args, cfg):
    """`proxy rule del <序号>` → args.user=序号"""
    spec = _load_rules_file(cfg)
    try:
        idx = int(getattr(args, 'user', None))
    except (TypeError, ValueError):
        print('用法: webtool proxy rule del <序号>', file=sys.stderr)
        return 2
    rules = spec.get('rules') or []
    if not (0 <= idx < len(rules)):
        print(f'序号越界 (0 ~ {len(rules) - 1})', file=sys.stderr)
        return 2
    gone = rules.pop(idx)
    _save_rules(cfg, spec)
    print(f'已删除规则 {idx}: {json.dumps(gone, ensure_ascii=False)}')
    return 0


def _rules_path(cfg=None):
    """规则文件路径: 显式配置 > <USER_DIR>/rules.json"""
    p = (cfg or {}).get('rules_file')
    return os.path.expanduser(p) if p else str(USER_DIR / 'rules.json')


def _load_rules_file(cfg=None):
    """读规则文件。顺带把 proxies 段里的明文密码迁进保险库 ——
    `proxy rules` / `rule add` 这些命令走这里而不是 load_router, 漏掉的话
    用户在 CLI 里看到的还是明文, 而且规则写回时会把明文又存一遍。"""
    path = _rules_path(cfg)
    if os.path.isfile(path):
        try:
            with open(path, encoding='utf-8') as f:
                spec = json.load(f)
        except (ValueError, OSError):
            return {}
        from webtool.net import rules as _R
        spec, n = _R.migrate_plaintext_proxies(spec, path)
        if n:
            print(f'已把 {n} 个命名代理的密码加密存进保险库, '
                  f'{path} 里只留用户名', file=sys.stderr)
        return spec
    return {}


def _save_rules(cfg, spec):
    """规则一律写 rules.json (单一事实来源)。**不碰 config.json**:
    调用链上常刚把密码密文写进保险库 (store_password 直接落 config.json),
    这里再 save_config(cfg) 会拿旧快照把密文覆盖掉 (看着成功, 重启就没密码)"""
    path = _rules_path(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(spec, f, ensure_ascii=False, indent=2)
    print(f'规则已写 {path}')


def _geoip(args, cfg):
    """geoip <库路径> — 配国家库并立刻体检。格式自动识别:
    MaxMind .mmdb 或 v2ray/sing-box 的 geoip.dat"""
    from webtool.net import geodata as _gd
    val = args.value
    if not val:
        print('usage: webtool proxy geoip <GeoLite2-Country.mmdb 或 geoip.dat>')
        return 2
    path = os.path.expanduser(val)
    if not os.path.isfile(path):
        print(f'文件不存在: {path}', file=sys.stderr)
        return 2
    fmt = _gd.detect_format(path)
    if fmt not in ('mmdb', 'geoip'):
        print(f'认不出库格式: {path}\n'
              f'支持 MaxMind .mmdb 与 v2ray/sing-box geoip.dat', file=sys.stderr)
        return 2
    cfg['geoip_db'] = path
    save_config(cfg)
    print(f'geoip_db = {path}  (格式: {fmt})')
    _probe_geoip(path)
    print('若同时配了 geosite, geoip 规则会优先按域名判 (免 DNS): '
          'webtool proxy geosite <geosite.dat>')
    return 0


def _geosite(args, cfg):
    """geosite <geosite.dat> — 按域名分类的库, 判规则时不需要 DNS"""
    from webtool.net import geodata as _gd
    val = args.value
    if not val:
        print('usage: webtool proxy geosite <geosite.dat>')
        return 2
    path = os.path.expanduser(val)
    if not os.path.isfile(path):
        print(f'文件不存在: {path}', file=sys.stderr)
        return 2
    fmt = _gd.detect_format(path)
    if fmt != 'geosite':
        print(f'不是 geosite 库 (认出来是 {fmt or "未知"}): {path}',
              file=sys.stderr)
        return 2
    cats = _gd.categories(path)
    cfg['geosite_db'] = path
    save_config(cfg)
    print(f'geosite_db = {path}')
    # 不同库的分类名大小写不一 (v2ray-rules-dat 用 CN/GOOGLE, v2fly 用 cn),
    # 查询本身大小写不敏感, 这里按小写索引再展示, 免得误报"没有"
    low = {c.lower() for c in cats}
    print(f'共 {len(cats)} 个分类; 常用: '
          + (', '.join(c for c in ('cn', 'google', 'github', 'category-ads')
                        if c in low) or '这几个分类库里没有'))
    _probe_geosite(path)
    print('用法: 规则里 {"geosite":["cn"]} —— 纯域名判定, 不解析 IP, '
          '不会被 CDN 就近解析带偏')
    return 0


def _probe_geoip(path):
    from webtool.net import geodata as _gd
    probes = ['8.8.8.8', '1.1.1.1', '114.114.114.114', '223.5.5.5']
    hits = [(ip, _gd.country_of_ip(ip, path)) for ip in probes]
    ok = [(ip, cc) for ip, cc in hits if cc]
    if ok:
        print('自检(IP→国家): ' + ', '.join(f'{ip}→{cc}' for ip, cc in ok))
        print(f'  {len(ok)}/{len(probes)} 个探针命中, 库可用')
    else:
        print('自检: 探针都没命中。可能是精简/测试库 (只覆盖少数网段), '
              '或类型不对 (要国家库不要 ASN 库)')


def _probe_geosite(path):
    from webtool.net import geodata as _gd
    for host, cat in [('www.baidu.com', 'cn'), ('www.google.com', 'google')]:
        try:
            hit = _gd.domain_in_category(host, cat, path)
        except Exception:
            hit = None
        print(f'  自检: {host} ∈ {cat} → {hit}')


def _asn(args, cfg):
    from webtool.net import rules as R
    val = args.value
    if not val:
        print('usage: webtool proxy asn <GeoLite2-ASN.mmdb>')
        return 2
    path = os.path.expanduser(val)
    if not os.path.isfile(path):
        print(f'文件不存在: {path}', file=sys.stderr)
        return 2
    if R._reader(path) is None:
        print(f'无法打开 mmdb: {path} (pip install maxminddb)',
              file=sys.stderr)
        return 2
    probe = R.geoip_asn('8.8.8.8', path)
    cfg['asn_db'] = path
    save_config(cfg)
    print(f'asn_db = {path}\n自检: 8.8.8.8 → AS{probe or "查不到"}')
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


_ACTIONS = {
    'get': _get,
    'set': _set,
    'unset': _unset,
    'test': _test,
    'setpass': _setpass,
    'delpass': _delpass,
    'named': _named,
    'passwd': _passwd,
    'rules': _rules,
    'tidy': _tidy,
    'rule': _ruleadd,       # rule add (deld 走 app 层分发)
    'ruledel': _ruledel,
    'geoip': _geoip,
    'geosite': _geosite,
    'asn': _asn,
    'noproxy': _noproxy,
}