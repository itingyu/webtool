"""代理与全局配置: ~/.webtool/config.json

配置分三处, 职责不重叠:
  - `proxy` / `fetch_proxy` — 选哪条线路 (本模块); 具体哪个 URL 走哪条线
    由规则表定 (net.rules)
  - `proxy_auth` — 账号密码**密文** (core.secrets_store 管加密, 本模块只读写)
  - `proxy_rules` / `rules_file` / `geoip_db` / `asn_db` — 按 URL 分流 (net.rules)

**任何输出与报错一律脱敏** (secrets_store.redact): 原实现把完整代理 URL 拼进
rank/zen 的错误串, 密码会进到 CLI 输出、用户贴的日志与 issue 里。
"""
import json
import os
import re
import sys
import time
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from webtool.core.config_data import USER_DIR
from webtool.core.secrets_store import (drop_password, redact, resolve_auth,
                                       status as secret_status, store_password)

CONFIG_PATH = str(USER_DIR / 'config.json')

DEFAULTS = {
    'proxy': None,
    'fetch_proxy': None,
    'timeout': 15,
    'ua': 'auto',
    'cache_dir': str(USER_DIR / 'cache'),
    # --- TLS (实际决策在 webtool.core.tls, 这里只负责存) ---
    'ssl_verify': True,          # 证书校验总开关
    'ca_bundle': None,           # 自定义 CA 包路径 (替代系统 CA)
    'verify_hosts': [],          # 关校验的域名单 (自签/过期证书的交易所站)
    # --- 代理 ---
    'proxy_auth': {},            # 用户名 → 密码密文
    'proxy_rules': None,         # 内联规则表 (与 rules_file 二选一)
    'rules_file': None,          # 规则文件路径, 默认 ~/.webtool/rules.json
    'geoip_db': None,            # GeoIP 国家库: .mmdb 或 v2ray/sing-box 的 geoip.dat
    'geosite_db': None,          # geosite 域名分类库 (geosite.dat): 按域名判分类, 无需 DNS
    'asn_db': None,              # GeoIP ASN 库 (.mmdb 或 .db/.dat)
    'proxy_dns_ttl': 300,        # 规则里查 GeoIP 时的 DNS 缓存秒数
}

# DEFAULTS 里没登记的键会在 load_config 被过滤掉 —— 新增配置项必须同时加这里
_KNOWN = set(DEFAULTS)


def load_config():
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


# ---------------------------------------------------------------- 各子命令

def _get(args, cfg):
    p = cfg.get('proxy')
    print(redact(p) if p else '(no proxy configured)')
    if cfg.get('engine_proxy'):
        # 老的每引擎覆盖: 不再生效, 但别装作没看见 —— 告诉用户这条线该写在哪
        print('engine_proxy: (已废弃, 线路统一由规则表决定: '
              'webtool proxy rule add <域名> direct|proxy:<代理名>)')
    auth = cfg.get('proxy_auth') or {}
    if auth:
        print('proxy_auth:', ', '.join(f'{u}(密文)' for u in auth))
    return 0


def _set(args, cfg):
    val = args.value
    if not val:
        print('usage: webtool proxy set http://host:port  '
              '(支持 http/https/socks5://; 带密码会自动存进保险库)',
              file=sys.stderr)
        return 2
    url = _rule_syntax(val)
    # URL 里带了密码 → 明文不许落盘: 存进保险库, 配置里只留 user@host
    scheme, user, password, host, port = proxy_url_parts(url)
    if scheme not in ('http', 'https', 'socks5', 'socks5h', 'socks4'):
        print(f'不支持的代理协议: {scheme or "(无)"} '
              '(支持 http/https/socks5/socks5h/socks4)', file=sys.stderr)
        return 2
    if not host:
        print('代理地址缺少主机名', file=sys.stderr)
        return 2
    if password:
        if not user:
            print('URL 里有密码但没用户名, 无法存保险库', file=sys.stderr)
            return 2
        try:
            store_password(user, password)
        except Exception as e:
            print(f'密码存储失败: {redact(str(e))}', file=sys.stderr)
            return 2
        # 关键: store_password 已经把密文写进 config.json 了, 这里必须把
        # 密文同步回内存里的 cfg —— 否则下面 save_config(cfg) 会拿一份
        # proxy_auth 还是 {} 的旧快照把刚写的密文覆盖掉 (看着像存成功了,
        # 下次启动就没密码了)
        cfg['proxy_auth'] = load_config().get('proxy_auth') or {}
        url = (f'{scheme}://{quote(user, safe="")}@{host}'
               + (f':{port}' if port else ''))
        print(f'密码已加密存进保险库 (用户 {user}); '
              f'配置文件只留用户名, 出网时才解密')
    cfg['proxy'] = url
    save_config(cfg)
    print(f'proxy saved: {redact(cfg["proxy"])} -> {CONFIG_PATH}')
    return 0


def _unset(args, cfg):
    cfg['proxy'] = None
    save_config(cfg)
    print('proxy cleared')
    return 0


def _test(args, cfg):
    val = _rule_syntax(args.value) if args.value else cfg.get('proxy')
    if not val:
        print('no proxy to test. use: webtool proxy test http://127.0.0.1:2080',
              file=sys.stderr)
        return 2
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
            'https://www.bing.com/robots.txt',
            headers=_hf('nav', 'https://www.bing.com/robots.txt',
                        full=True)), timeout=10)
        body = r.read(64)
        print(f'OK {r.status} {len(body)}B in {time.time()-t0:.1f}s '
              f'via {redact(val)}')
    except Exception as e:
        print(f'FAIL via {redact(val)}: {redact(str(e))}', file=sys.stderr)
        return 1


def _setpass(args, cfg):
    """把账号密码加密存进保险库, 配置里只留用户名

    密码来源按优先级:
      1. 位置参数 `<密码>` —— 方便脚本, 但**会留在 shell history 和 ps 输出里**,
         交互使用应该省略它 (走第 2 条)
      2. 终端交互 (getpass, **不回显**) —— 真终端下的默认路径
      3. stdin 管道 —— 供 Agent / 脚本 `echo pw | webtool proxy setpass <用户>`
    """
    user = args.user
    if not user:
        print('usage: webtool proxy setpass <用户名> [<密码>]', file=sys.stderr)
        print('  省略密码则终端交互输入 (不回显); 也可从 stdin 管道读',
              file=sys.stderr)
        return 2
    pwd = args.value
    if pwd is None:
        if sys.stdin.isatty():
            # 真终端: 交互输入且不回显。必须先判 isatty —— getpass 在无 TTY
            # 时会静默降级成读 stdin 并往 stderr 打警告, 那正是下面第 3 条
            # 该走的路, 不能两条路混在一起
            import getpass
            try:
                pwd = getpass.getpass(f'输入 {user} 的代理密码 (不回显): ')
            except (EOFError, KeyboardInterrupt):
                print(file=sys.stderr)
                return 130
            except Exception as e:
                # 没有 /dev/tty (某些容器/重定向环境): 退回读 stdin, 别直接崩
                print(f'无法交互输入 ({e}); 请改用管道: '
                      f'echo "<密码>" | webtool proxy setpass {user}',
                      file=sys.stderr)
                return 2
        else:
            pwd = sys.stdin.readline().rstrip('\n')
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
    spec = cfg.get('proxy_rules') or _load_rules_file(cfg)
    print(f'默认动作: {getattr(r, "default_action", "direct")}')
    print(f'命名代理: {json.dumps({k: redact(v.get("url") if isinstance(v, dict) else v) for k, v in (getattr(r, "proxies", {}) or {}).items()}, ensure_ascii=False)}')
    print(f'规则文件: {_rules_path(cfg)}'
          f'{"" if cfg.get("proxy_rules") else " (proxy_rules 为空, 读文件)"}')
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
    return 0


def _ruleadd(args, cfg):
    """`proxy rule add <match JSON> <动作>`  →  args.user=JSON, args.act=动作"""
    from webtool.net import rules as R
    spec = cfg.get('proxy_rules') or _load_rules_file(cfg)
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
    # 追加之所以危险, 是因为 first-match-wins 下前面的宽规则会把它整条吃掉,
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
    spec = cfg.get('proxy_rules') or _load_rules_file(cfg)
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
    """规则一律写 rules.json (单一事实来源), 顺手清掉可能并存的内联副本"""
    path = _rules_path(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(spec, f, ensure_ascii=False, indent=2)
    cfg['rules_file'] = path
    if cfg.get('proxy_rules'):
        cfg['proxy_rules'] = None
    save_config(cfg)
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

    规则表里的 `proxy:<名字>` 之前只能手写 JSON 才能配, 而 rules.json 是要人工
    维护的文件 —— 密码写进去就是明文落盘。这里统一: 密码进保险库, rules.json
    只留 `user@host`, 与全局 proxy 走同一套凭据机制。
    """
    spec = cfg.get('proxy_rules') or _load_rules_file(cfg)
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
        if not user:
            print('URL 里有密码但没用户名, 无法存保险库', file=sys.stderr)
            return 2
        try:
            store_password(user, password)
        except Exception as e:
            print(f'密码存储失败: {redact(str(e))}', file=sys.stderr)
            return 2
        cfg['proxy_auth'] = load_config().get('proxy_auth') or {}
        clean = (f'{scheme}://{quote(user, safe="")}@{host}'
                 + (f':{port}' if port else ''))
    proxies[name] = {'url': clean}
    _save_rules(cfg, spec)
    print(f'命名代理 {name} = {redact(clean)} -> {_rules_path(cfg)}')
    if password:
        print(f'  密码已加密存进保险库 (用户 {user}), 出网时才解密')
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
    'rule': _ruleadd,       # rule add (deld 走 app 层分发)
    'ruledel': _ruledel,
    'geoip': _geoip,
    'geosite': _geosite,
    'asn': _asn,
    'noproxy': _noproxy,
}