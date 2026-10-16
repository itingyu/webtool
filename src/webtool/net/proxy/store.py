"""代理与全局配置的存储层: config.json 读写 + 代理 URL 原语

线路的唯一决策点是 `~/.webtool/rules.json` (net.rules); 本模块只管 config.json
这一侧: 默认值、字段白名单、遗留键迁移、代理 URL 解析、密码入库原语。

**任何输出与报错一律脱敏** (secrets_store.redact)。
"""
import json
import logging
import os
import re
from urllib.parse import unquote

from webtool.core.config_data import USER_DIR

logger = logging.getLogger(__name__)

# 白名单丢键只吵一次: load_config 每进程会被调很多次 (tls/pacing/命令入口)
_WARNED_KEYS = set()
from webtool.core.secrets_store import redact, store_password


CONFIG_PATH = str(USER_DIR / 'config.json')


DEFAULTS = {
    'timeout': 15,
    'default_format': None,      # 数据命令的默认输出格式 (cli._ctx 收口读取)
    'cache': None,               # 磁盘缓存总开关 on/off; None=开
    'extract': 'auto',           # 正文提取器: auto=内容层择优 / 具名=只用那一个
    'cache_dir': str(USER_DIR / 'cache'),
    # 搜索行为 (cli 侧可写; 业务侧在 pipeline/search 读)
    'market': None,              # 搜索市场 (bing mkt); None=zh-CN
    'default_engines': None,     # 默认引擎组合; None=内置组合
    'jobs': None,                # 搜索并发引擎数; None=按源数(上限 4)
    'blocklist': None,           # 域名黑名单覆盖; None=用内置表
    'cache_ttl': {},             # 分桶 TTL 覆盖 {"search": 30, ...}
    # 合并排序权重 (pipeline/merge 读, 手写 config.json 生效)
    'low_prior': None,           # 低优先域名单
    'low_prior_value': 0.4,      # 命中低优先域时权重削到多少
    'ref_hosts': None,           # 英文 query 才启用的参考站点
    # TLS (实际决策在 webtool.net.tls, 这里只负责存)
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


_KNOWN = set(DEFAULTS)


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
        except Exception as e:
            # 曾经是 except: pass —— 配置文件写坏了会当"没配"静默跑下去,
            # 用户看到的是"我明明配了却不生效", 却没有一行日志指向这里
            logger.warning('config | 读取失败, 本次全用默认值: %s (%s: %s)',
                           CONFIG_PATH, type(e).__name__, e)
            user = None
        if isinstance(user, dict):
            dropped = sorted(k for k in user if k not in _KNOWN)
            cfg.update({k: v for k, v in user.items() if k in _KNOWN})
            # 键在文件里、却不在 DEFAULTS 白名单 → 被静默过滤。config set
            # 能写进去 (它走自己那份键表), 业务侧却读不到, 是"配了没反应"的
            # 头号成因。见 tests/test_smoke.py §15 的键表对齐守卫。
            fresh = [k for k in dropped if k not in _WARNED_KEYS]
            if fresh:
                _WARNED_KEYS.update(fresh)
                # 光说"不在白名单"用户删不掉它: 文件名、键名、删除命令都得给,
                # 否则就是每次启动刷一条没人能处理的警告 (老版本留下的死键尤其
                # 像"我明明配了却不生效")。config list 末尾也会把它们列出来。
                logger.warning(
                    'config | 键不在白名单, 已忽略: %s —— 拼错了? 还是老版本留下的'
                    '死键? 文件 %s; 删: webtool config unset <键>; 看: webtool '
                    'config list 末尾"没人认的键"',
                    ','.join(fresh), CONFIG_PATH)
        elif user is not None:
            logger.warning('config | 顶层不是对象而是 %s, 已忽略: %s',
                           type(user).__name__, CONFIG_PATH)
    return cfg


def unknown_keys():
    """config.json 里有、却没人认的键 (读配置时会被丢掉的那些)

    给 `webtool config list` 用 —— 用户看不见一个键, 就永远删不掉它, 只能
    反复吃那条"键不在白名单"的警告。只读一眼文件, 不碰缓存。
    """
    try:
        with open(CONFIG_PATH, encoding='utf-8') as f:
            user = json.load(f)
    except (OSError, ValueError):
        return []
    if not isinstance(user, dict):
        return []
    return sorted(k for k in user if k not in _KNOWN)

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


def _norm_proxy_url(u):
    """比线路用: 只看 scheme://host:port, 忽略路径/尾斜杠/大小写"""
    s = str(u or '').strip().rstrip('/')
    if '://' not in s:
        s = 'http://' + s
    return s.lower()
