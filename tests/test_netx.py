"""跨通道一致性测试

统一出网层的意义不是"有个统一入口", 而是**任何通道出网都遵守同一套策略**。
所以这里测的重点不是 netx 自己能不能发请求, 而是:

  1. 各通道面对同一个 proxy 参数, 解析结果必须一致
  2. 曾经漏接策略的通道 (probe) 现在接上了 —— 用规则拦截证明
  3. 证书策略在各通道语义一致 (尤其 tls.policy 返回 CA 路径 vs urllib 只认布尔)

需要联网的部分 (打真站点) 由 NETX_LIVE=1 开启; 默认全离线跑, 断言的是
策略逻辑而不是网络可用性 —— 后者在 CI 上本来就不该依赖。
"""
import io
import json
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

WEBTOOL_DIR = tempfile.mkdtemp(prefix='netx-test-')
os.environ['WEBTOOL_DIR'] = WEBTOOL_DIR
for _k in ('WEBTOOL_SECRET_KEY',):
    os.environ.pop(_k, None)

PASS = FAIL = SKIP = 0


def check(cond, msg, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'PASS {msg}' + (f' ({detail})' if detail else ''))
    else:
        FAIL += 1
        print(f'FAIL {msg}' + (f' (实际 {detail})' if detail else ''))


def skip(label, why):
    global SKIP
    SKIP += 1
    print(f'SKIP {label} ({why})')


def write_rules(spec):
    """写规则并把它挂到 config.json。

    注意必须**合并**而不是覆盖 config.json —— 覆盖会连带抹掉 proxy_auth
    (保险库密文), 于是后续 store_password 写入的密码和 resolve_proxy 查的
    就落在两份不同的配置上, 测出来的是"密码补不上"的假象。
    """
    path = os.path.join(WEBTOOL_DIR, 'rules.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(spec, f)
    cfg_path = os.path.join(WEBTOOL_DIR, 'config.json')
    cfg = {}
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, encoding='utf-8') as f:
                cfg = json.load(f)
        except ValueError:
            cfg = {}
    cfg['rules_file'] = path
    with open(cfg_path, 'w', encoding='utf-8') as f:
        json.dump(cfg, f)
    return path


def set_cfg(key, value):
    """往 config.json 合并一个键 —— write_rules 只管规则, 别的配置项走这里"""
    cfg_path = os.path.join(WEBTOOL_DIR, 'config.json')
    cfg = {}
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, encoding='utf-8') as f:
                cfg = json.load(f)
        except ValueError:
            cfg = {}
    cfg[key] = value
    with open(cfg_path, 'w', encoding='utf-8') as f:
        json.dump(cfg, f)


# 本文件测的是"通道/路由语义", 与代理活没活无关 —— 关掉可达性兜底
# (proxy_fallback), 免得 9.9.9.9:8080 这类探不通的假代理被判成"没起来"而改走
# 直连, 把断言悄悄变成"兜底在不在"的测试。兜底本身见 tests/test_proxy_reach.py。
set_cfg('proxy_fallback', 'off')


from webtool.net import netx           # noqa: E402
from webtool.net import tls           # noqa: E402


print('\n=== 1. resolve_proxy: 各通道共享的归一语义 ===')
# None / 'direct' / 'auto' / URL 四种形态的语义必须全库一致,
# 否则会出现"某通道走直连、transport 走代理"这种无法排查的分裂
check(netx.resolve_proxy(None) is None, 'None = 直连')
check(netx.resolve_proxy('direct') is None, "'direct' = 直连")
check(netx.resolve_proxy('') is None, '空串 = 直连')
check(netx.resolve_proxy('http://127.0.0.1:8080') == 'http://127.0.0.1:8080',
      '显式 URL 原样保留')
check(netx.resolve_proxy('auto') is None, "'auto' 无 url 时降级直连 (不猜)")

print('\n=== 2. auto 必须真的问路由表 ===')
# 代理 URL 里用户名必须写成 user@host —— 写 user:host 会有歧义
# (`http://tk:9.9.9.9:8080` 里的 `tk:9.9.9.9` 本身就是合法 user:pass 形态,
#  会被当成"已带密码"而不去查保险库)。命令行要的是无歧义的 user@host。
write_rules({'default': 'direct',
             'proxies': {'tokyo': {'url': 'http://9.9.9.9:8080'}},
             'rules': [{'match': {'domain': ['x.com']}, 'action': 'proxy:tokyo'},
                       {'match': {'domain': ['blocky.com']}, 'action': 'block'}]})
check(netx.resolve_proxy('auto', 'https://x.com/a') == 'http://9.9.9.9:8080',
      "auto 命中命名代理规则",
      netx.resolve_proxy('auto', 'https://x.com/a'))
check(netx.resolve_proxy('auto', 'https://other.com/a') is None,
      'auto 未命中 → 直连')
try:
    netx.resolve_proxy('auto', 'https://blocky.com/a')
    check(False, 'auto 命中 block 应抛 RuleError')
except Exception as e:
    check(type(e).__name__ == 'RuleError', 'auto 命中 block → RuleError',
          type(e).__name__)

print('\n=== 3. 保险库密码只在归一处补一次 ===')
from webtool.core import secrets_store as SS   # noqa: E402
from webtool.net import proxy as PX            # noqa: E402
cfg = PX.load_config()
SS.store_password('tk', 'PW_TK')
# 带凭据的命名代理 (用户名写成 user@host —— 写 user:host 会有歧义:
# `http://tk:9.9.9.9:8080` 里的 `tk:9.9.9.9` 本身就是合法 user:pass 形态)
write_rules({'default': 'direct',
             'proxies': {'tk': {'url': 'http://tk@9.9.9.9:8080'}},
             'rules': [{'match': {'domain': ['tk.com']}, 'action': 'proxy:tk'}]})
r = netx.resolve_proxy('auto', 'https://tk.com/a')
check(r == 'http://tk:PW_TK@9.9.9.9:8080',
      'auto 命中的命名代理自动补上保险库密码', r)
# 幂等: 已带明文密码的再跑一次不能变成"密码密码"
check(netx.resolve_proxy(r) == r, '重复归一幂等 (不会二次补密码)')
# 缺密码要报, 不能拿空密码去撞 407
write_rules({'default': 'direct',
             'proxies': {'ghost': {'url': 'http://ghostpw@9.9.9.9:8080'}},
             'rules': [{'match': {'domain': ['g.com']}, 'action': 'proxy:ghost'}]})
try:
    netx.resolve_proxy('auto', 'https://g.com/a')
    check(False, '缺密码应抛 SecretError')
except SS.SecretError as e:
    check('ghostpw' in str(e), '缺密码 → SecretError 且点名用户', str(e)[:70])
# 无凭据的代理 (只有 host:port) 绝不能被当成凭据
check(netx.resolve_proxy('http://127.0.0.1:2080') == 'http://127.0.0.1:2080',
      '无凭据代理原样 (host:port 不误判成 user:pass)')
check(netx.resolve_proxy('http://myhost:8080') == 'http://myhost:8080',
      '无凭据 + 主机名同样原样')

print('\n=== 4. verify_arg: 修掉 CA 路径喂给 urllib 的坑 ===')
# tls.policy 返回 False 或 CA 路径 (cffi/requests 用), 而 urllib 的
# ssl_context 只认布尔。直接透传会报 "ssl_verify 只认 on/off"。
if tls.ca_available()[0]:
    # ssl_verify 默认 off (b9e2718, 首次可用优先), 所以这里显式开校验再测
    # "CA 路径 → urllib 布尔" 的转换, 否则 policy 返回 False 测不到转换逻辑
    from webtool.net import proxy as _pm
    _slc = _pm.load_config
    _pm.load_config = lambda *a, **kw: {'ssl_verify': 'on'}
    tls._CACHE = (None, None)
    ver = tls.policy('https://example.com', None)
    check(ver is not False, '有 CA 且开校验时 policy 给出非 False 值')
    check(netx.verify_arg(ver) is True,
          f'CA 路径 → urllib 侧转成 True (实际 {netx.verify_arg(ver)!r})')
    _pm.load_config = _slc
    tls._CACHE = (None, None)
check(netx.verify_arg(False) is False, 'False 原样保留 (豁免不丢)')
check(netx.verify_arg(True) is True, 'True 原样保留')

print('\n=== 6. socks 代理的远端解析必须收口在归一层 ===')
# requests / curl 都把 socks5:// 读成**本地**解析 DNS, 代理服务器根本用不上;
# 远端解析必须写 socks5h:// —— 这个坑只会表现为"配了 socks 却还直连"。
# 升级点已收口到 netx.resolve_proxy (所有通道共用), 各下游只做形状转换。
_s5u = 'https://example.com/x'
check(netx.resolve_proxy('socks5://1.2.3.4:1080', _s5u) ==
      'socks5h://1.2.3.4:1080', 'netx 把 socks5 升成 socks5h (远端解析)',
      repr(netx.resolve_proxy('socks5://1.2.3.4:1080', _s5u)))
check(netx.resolve_proxy('socks5h://1.2.3.4:1080', _s5u) ==
      'socks5h://1.2.3.4:1080', 'socks5h 不被二次改写')
check(netx.resolve_proxy('http://1.2.3.4:8080', _s5u) == 'http://1.2.3.4:8080',
      'http 代理原样, 不被误改')
print('\n=== 7. probe 探活也要补密码 ===')
# 探活拿不到密码就会把"带认证的代理"误判成不可用, 上层据此放弃重试,
# 排查方向完全指不到真实原因
write_rules({'default': 'direct', 'proxies': {}, 'rules': []})
SS.store_password('pu', 'PW_PU')
resolved = netx.resolve_proxy('http://pu@9.9.9.9:1')
check(resolved == 'http://pu:PW_PU@9.9.9.9:1', 'probe 用的代理能补上密码', resolved)

print('\n=== 8. 默认头不许出裸 urllib 指纹 ===')
h1 = netx.default_headers('https://example.com')
check('Mozilla' in h1.get('User-Agent', ''), '默认 UA 是浏览器指纹',
      h1.get('User-Agent', '')[:40])
check(h1.get('Accept-Language'), '默认带 Accept-Language')
h2 = netx.default_headers('https://example.com', {'User-Agent': 'Custom/1.0'})
check(h2['User-Agent'] == 'Custom/1.0', '调用方显式给的头不被覆盖')

print('\n=== 9. 静态审计: 别再有通道绕过统一层 ===')
# 光测行为不够 —— 新增通道时很容易又忘了接。这里扫源码: 凡是自己写
# 'auto' 路由判断或 resolve_auth 的地方, 都应该已经收敛到 netx
import subprocess
out = subprocess.run(
    ['rg', '-n', "-l", r"proxy == 'auto'|resolve_route\(", 'src'],
    cwd=ROOT, capture_output=True, text=True).stdout.strip().splitlines()
AUTO_OK = {'src/webtool/net/netx.py', 'src/webtool/net/http.py',
           'src/webtool/net/rules/loader.py'}   # rules 包是路由表实现本身
stray = [f for f in out if f.endswith('.py') and f not in AUTO_OK]
check(not stray,
      '没有通道自己判断 auto/调 resolve_route (只能经 netx 或 build_opener)',
      str(stray))
check('resolve_proxy' in open(os.path.join(ROOT, 'src/webtool/net/http.py'),
                               encoding='utf-8').read(),
      'build_opener 的 auto 分支确实转给 netx')

out2 = subprocess.run(
    ['rg', '-n', '-l', r'resolve_auth\(', 'src'],
    cwd=ROOT, capture_output=True, text=True).stdout.strip().splitlines()
# resolve_auth 允许出现在这几处, 各有明确理由:
#   secrets_store.py — 定义处
#   netx.py          — 统一层的归一入口
#   net/http.py     — build_opener 是 urllib 侧的公共出口, zen/mcpclient/
#                      sogou/gnews 都直接调它, 补密码必须发生在这里
#   net/transport.py — _get_once 是预热/降级梯的深层出口, 保留兜底
#   net/proxy/pool.py — proxy set/test 的 CLI 路径, 要在报错前先补全
ALLOWED_AUTH = {'src/webtool/core/secrets_store.py', 'src/webtool/net/netx.py',
                'src/webtool/net/http.py', 'src/webtool/net/transport.py',
                'src/webtool/net/proxy/pool.py',
                # 给 ffmpeg 子进程设 http(s)_proxy 环境变量: 子进程拿不到我们的
                # 会话, 只能把带凭据的 URL 写进 env, 补密码必须在这发生
                'src/webtool/cli/commands/media.py'}
stray2 = [f for f in out2 if f.endswith('.py') and f not in ALLOWED_AUTH]
check(not stray2, 'resolve_auth 没扩散到未经审计的模块', str(stray2))

out3 = subprocess.run(
    ['rg', '-n', '-l', r'proxies=', 'src'],
    cwd=ROOT, capture_output=True, text=True).stdout.strip().splitlines()
# 例外按路径片段匹配, 不用硬编码全路径 —— HTTP 通道在 net/http.py,
# 写死整条路径会让它混进 bad3 而误报
# 例外 = 合法传 proxies 的通道: netx 自己、三条 webtool HTTP 通道, 以及
# 路由层 (net/routing + sources/_adapter/_base: 那里是按 URL 现算代理的
# 实现, 正是本测试想确保的"唯一的合法出处")
_ok_exc = ('netx.py', 'transport.py', 'net/http.py', 'adapters.py',
           'bridge/http.py', 'bridge/_eco_net.py',
           'bridge/sources/_adapter.py', 'net/routing.py',
           'bridge/sources/_base.py',
           # pyshim 是 requests 的补丁通道: 打补丁后必须把路由算出的 proxy 显式
           # 传给底层 session, 否则补丁形同虚设
           'pyshim.py')
bad3 = [f for f in out3 if f.endswith('.py')
        and not any(x in f for x in _ok_exc)]
check(not bad3, '只有已知通道给底层库传 proxies', str(bad3))

print('\n=== 10. 真站点联调 (需 NETX_LIVE=1) ===')
if os.environ.get('NETX_LIVE') != '1':
    skip('真实出网', '未设 NETX_LIVE=1')
else:
    write_rules({'default': 'direct', 'proxies': {}, 'rules': []})
    try:
        text, st = netx.get('https://www.baidu.com', timeout=15)
        check(st == 200 and len(text) > 1000, 'netx.get 真站点 200',
              f'status={st} len={len(text)}')
    except Exception as e:
        check(False, 'netx.get 真站点', f'{type(e).__name__}: {str(e)[:90]}')
    try:
        text, st = netx.get('https://expired.badssl.com/', timeout=15)
        check(False, '过期证书站应抛 TlsError', f'居然 status={st}')
    except tls.TlsError:
        check(True, '过期证书站硬失败 (不重试不降级)')
    except Exception as e:
        check(False, '过期证书站应抛 TlsError', f'{type(e).__name__}')

print('\n=== 11. 代码里不得残留强制直连 ===')
# 曾经 exa/parallel 在端点表声明 "proxy":"direct" 并硬编码 proxy=None 绕开
# 全局代理 (理由: 免 key 配额按出口 IP 计)。那是服务方的计量策略, 不该由内置
# 数据替用户决定 —— 现在一律跟随配置 (engine_proxy.<引擎> 或规则表)。
import glob                                              # noqa: E402
import json as _json                                     # noqa: E402

endpoints = _json.load(
    open(os.path.join(ROOT, 'src/webtool/data/mcp.json'),
         encoding='utf-8'))['mcp']
bad_ep = [n for n, s in endpoints.items() if 'proxy' in s]
check(not bad_ep, '端点表不再声明代理策略', str(bad_ep))

# 插件清单同理: engine.*.params.proxy_hint 曾经给 8 个引擎写死 "direct",
# site.*.proxy 给 17 个站点写死 "direct"。site 那条是**真的强制直连** ——
# sitesearch.py 见到 direct 就把 proxy 置 None, 完全绕开 config 和路由表。
plugins = _json.load(
    open(os.path.join(ROOT, 'src/webtool/data/plugins.json'),
         encoding='utf-8'))
bad_site = [k for k, v in plugins['site'].items() if 'proxy' in v]
check(not bad_site, '站点表不再声明出网线路', str(bad_site))
bad_eng = [k for k, v in plugins['engine'].items()
           if (v.get('params') or {}).get('proxy_hint') == 'direct']
check(not bad_eng, '引擎表不再有 "建议直连" 的硬编码', str(bad_eng))
# proxy_hint 现在只表示"这个引擎直连必然不通", 不能用来锁死线路
hints = {(v.get('params') or {}).get('proxy_hint') for v in plugins['engine'].values()}
check(hints <= {None, 'required'},
      "proxy_hint 只剩 None/'required' 两种取值", str(sorted(map(str, hints))))

# 引擎里把 proxy=None 写死传给底层 = 忽略管线传入的代理 = 事实上的强制直连。
# 只看**真实调用的实参**, 不看 docstring/注释 —— 注释里提"曾写死 proxy=None"
# 是解释历史, 属于该留的信息, 误伤它等于逼人把说明删掉。
hard = []
for f in glob.glob(os.path.join(ROOT, 'src/webtool/engines/*.py')):
    lines = open(f, encoding='utf-8').read().splitlines()
    for i, line in enumerate(lines, 1):
        s = line.strip()
        if s.startswith('#'):
            continue                    # 纯注释行不是调用
        # 调用的实参里写死 proxy=None (允许跨行到右括号为止, 但不跨注释)
        if re.search(r'\b(?:call_tool|call_verb)\s*\(', line):
            buf = []
            for j in range(i, min(i + 8, len(lines) + 1)):
                buf.append(lines[j - 1])
                if lines[j - 1].rstrip().endswith(')'):
                    break
            arg = '\n'.join(buf)
            arg = re.sub(r'#.*', '', arg)          # 去掉行内注释再判
            if re.search(r'proxy\s*=\s*None', arg):
                hard.append(f'{os.path.basename(f)}:{i}')
check(not hard, '引擎不得把 proxy=None 写死传给 MCP 底层', str(hard))


print('\n=== 12. 不得再有 failover (先直连不通再代理) ===')
# 走哪条线由配置 + 路由表一次决定, 历史上那 7 处"直连优先/失败换代理"已全部
# 拿掉 (理由见 docs/coding-standard.md「不许 failover」)。这里只留**行为**断言:
# 参数没了就没法再走那条路; 文案措辞不做断言 (换个说法就误报, 且拦不住任何 bug)。

import inspect                                  # noqa: E402
from webtool.net import transport as _T          # noqa: E402
check('allow_fallback' not in inspect.signature(_T.get).parameters,
      'transport.get 签名里没有 allow_fallback (别误导调用方)')


print('\n=== 13. cffi 主通道必须真跑 (不带 engine 的调用) ===')
# 回归: _get_cffi 里 `import transport as _t` 曾经写在 `if engine:` 分支内,
# 而 else 分支又直接用 _t.PROFILES —— 于是所有**不带 engine** 的调用
# (探活 / 站点 / feed 走的都是这条) 一进来就 UnboundLocalError,
# cffi 一次没真跑, 全部静默落到 urllib。症状极隐蔽: 结果照样对, 只是指纹
# 和代理错误信息全失真, 只有真正依赖浏览器指纹的站才会挂。
import curl_cffi.requests as _cr                    # noqa: E402
import inspect as _ins                              # noqa: E402
_seen = {}
_real_sess, _real_get = _cr.Session, _cr.get
# 真库在**请求级**只认 Session.request 的这些参数。桩必须同样挑参数 ——
# 曾经这里的 _fake_get(url, **kw) 什么 kwargs 都收, 于是给模块级 cr.get()
# 传它不接受的 trust_env=False 时照样"通过", 而线上是当场 TypeError +
# 静默回退 urllib (cffi 通道一次没真跑过), 指纹全丢。比真库宽松的桩 =
# 假保证。
_legal = set(_ins.signature(_real_sess.request).parameters) - {'self'}


class _FakeSess:
    def __init__(self, **kw):
        _seen.clear()
        _seen['ctor'] = kw

    def get(self, url, **kw):
        bad = set(kw) - _legal
        if bad:
            raise TypeError('Session.request() got an unexpected keyword '
                            'argument %r' % sorted(bad)[0])
        _seen.update(kw)
        _seen['url'] = url
        return type('R', (), {'content': b'<html>ok</html>',
                              'headers': {'Content-Type': 'text/html'},
                              'status_code': 200})()


def _forbidden_get(*a, **k):
    raise AssertionError('netx 不该用模块级 curl_cffi.requests.get: '
                         '它不接受 trust_env, 必须走 Session(trust_env=False)')


_cr.Session, _cr.get = _FakeSess, _forbidden_get
try:
    text, status = netx.get('https://example.com/x', proxy='direct')
    check(status == 200 and 'ok' in text,
          '不带 engine 的 netx.get 走的是 cffi (没落 urllib)', f'status={status}')
    check((_seen.get('ctor') or {}).get('trust_env') is False,
          'cffi 会话在会话级关掉 trust_env', str(_seen.get('ctor')))
    check(bool(_seen.get('impersonate')),
          'cffi 请求带了 impersonate 指纹', str(_seen.get('impersonate')))
    check('proxy' not in _seen,
          "proxy='direct' 时不给 cffi 传 proxy 参数 (否则强制挂代理)")
    check(not (set(_seen) - _legal - {'ctor'}),
          'cffi 请求用的都是真库认的参数',
          str(sorted(set(_seen) - _legal - {'ctor'})))
    text, status = netx.get('https://example.com/y',
                            proxy='http://u:p@1.2.3.4:8080')
    check(_seen.get('proxy') == 'http://u:p@1.2.3.4:8080',
          '显式代理原样传给 cffi', str(_seen.get('proxy')))
    text, status = netx.get('https://example.com/z',
                            proxy='http://1.2.3.4:8080', engine='bing')
    check(bool(_seen.get('impersonate')),
          '带 engine 时也用对应指纹档案', str(_seen.get('impersonate')))
finally:
    _cr.Session, _cr.get = _real_sess, _real_get

print('\n=== 14. curl_cffi 会话必须认 proxy 的四种形态 ===')
# 回归: _new_session 曾把 proxy 原样塞给 curl_cffi, 而 search 管线传的正是
# 'auto' —— curl 于是去解析一个叫 "auto" 的主机名:
#   ProxyError: Could not resolve proxy: auto
# sogou/baidu/google/marginalia 全线命中。症状是"配了代理反而全挂"。
from webtool.net import transport as _TR          # noqa: E402
check(_TR._new_session('chrome131_win', None, None)[0].proxies in ({}, None),
      'None = 直连, 不挂代理')
check(not _TR._new_session('chrome131_win', 'direct', None)[0].proxies,
      "'direct' = 直连 (不把字符串 direct 当主机名解析)")
_seen_px = {}
_orig_resolve = netx.resolve_proxy


def _trace_resolve(proxy, url=None, *a, **kw):
    r = _orig_resolve(proxy, url, *a, **kw)
    _seen_px['in'] = proxy
    _seen_px['url'] = url
    _seen_px['out'] = r
    return r


netx.resolve_proxy = _trace_resolve
try:
    # 'auto' 问不到 URL 就退回默认动作, 至少不是把 'auto' 当主机名
    _TR._new_session('chrome131_win', 'auto', 'baidu',
                     url='https://www.baidu.com/s')
    check(_seen_px['out'] in (None, 'http://127.0.0.1:2080')
          or isinstance(_seen_px['out'], str),
          "'auto' 归一成了线路而非原样透传", str(_seen_px['out'])[:60])
    check(_seen_px['url'] == 'https://www.baidu.com/s',
          "会话按传入的目标 URL 问路由 (域名规则才对得上)")
    # engine 兜底: 没传 url 时用该引擎的入口
    _TR._new_session('chrome131_win', 'auto', 'bing')
    check('bing.com' in (_seen_px['url'] or ''),
          '没传 url 时按 engine 名取入口', str(_seen_px['url']))
    # 显式 URL 原样透传 (幂等: 不会二次补密码)
    _TR._new_session('chrome131_win', 'http://127.0.0.1:2080', None)
    check(_seen_px['out'] == 'http://127.0.0.1:2080',
          '显式 URL 原样透传给 curl_cffi', str(_seen_px['out']))
finally:
    netx.resolve_proxy = _orig_resolve

# 静态: 所有引擎都必须把实际 URL 交给 _new_session (漏传 = 该引擎的分流规则
# 静默失效, 且没有任何报错)。调用常跨行, 得读到右括号为止 —— 只看单行会把
# 所有多行写法全判成漏传。
eng_bad = []
for f in glob.glob(os.path.join(ROOT, 'src/webtool/engines/*.py')):
    lines = open(f, encoding='utf-8').read().splitlines()
    for i, line in enumerate(lines, 1):
        if '_new_session(' not in line or line.strip().startswith('#'):
            continue                    # 注释里提到函数名不是调用
        buf = []
        for j in range(i, min(i + 5, len(lines) + 1)):
            buf.append(lines[j - 1])
            if ')' in lines[j - 1] and not lines[j - 1].rstrip().endswith(','):
                break
        call = '\n'.join(buf)
        if 'url=' not in call:
            eng_bad.append(f'{os.path.basename(f)}:{i}')
check(not eng_bad, '引擎建会话都传了目标 URL', str(eng_bad))

print('\n=== 15. 残留直连审计 (本轮补挖出来的几处) ===')
# zen: call_zen_retry 曾经写死 proxy=None, 失败后调用方再走一遍代理 ——
# 标准"先直连、失败换代理"。且 fetch_models 也不传, 于是"能聊天但拉不到
# 模型清单"。两处都必须按 cfg 走。
import inspect                                  # noqa: E402
from webtool.cli import zen as _zen             # noqa: E402
from webtool.cli import app as _app              # noqa: E402
from webtool.pipeline import fetch as netfetch        # noqa: E402
import importlib                                # noqa: E402
# radar/__init__.py 把 instances/routes/rules re-export 成同名函数, 属性遮蔽了
# 子模块, 直接 import 会拿到函数 —— 只能按路径取模块
_ri = importlib.import_module('webtool.radar.instances')
_ro = importlib.import_module('webtool.radar.official')
_rr = importlib.import_module('webtool.radar.routes')
_zen_src = inspect.getsource(_zen.call_zen_retry)
check('proxy=None)' not in _zen_src,
      'call_zen_retry 不再写死 proxy=None 直连', _zen_src[-120:].strip()[:80])
check('_route(cfg' in _zen_src or '_route(' in _zen_src,
      'call_zen_retry 的线路来自 _route (cfg + 路由表)')
check(hasattr(_zen, 'call_zen_on_route'),
      "zen 的按配置入口叫 call_zen_on_route (名字不再宣称 failover)")
_m_src = inspect.getsource(_zen.fetch_models_detail)
check('proxy = _route(cfg, models_url, verbose=True)' in _m_src,
      'fetch_models_detail 模型清单与对话请求走同一条线路')
check('def fetch_models(' in inspect.getsource(_zen.fetch_models) and
      'fetch_models_detail(' in inspect.getsource(_zen.fetch_models),
      'fetch_models 仍可用 (id 列表, 薄封装在 detail 之上)')
# ── 三个改过的坑, 各留一条回归断言 ──────────────────────────────
# 1) 布尔标志声明顺序: '--no-x/--x' 会让 --x 解析成 False (Typer 语义颠倒),
#    实测确认过; 心跳开关必须"正名在前"。
_app_src = (inspect.getsource(_app)
            + inspect.getsource(
                __import__('webtool.cli.commands.data', fromlist=['x']))
            + inspect.getsource(
                __import__('webtool.cli.commands.zenapp', fromlist=['x'])))
for _flag in ("'--live/--no-live'", "'--reasoning/--no-reasoning'"):
    check(_flag in _app_src, f'app.py 布尔标志写法正确 {_flag}')
# 2) 退出码非零时不能把报告丢掉 (zen --check 全挂时人得看得到表)
_run_src = inspect.getsource(_app._run)
check('if out.strip():' in _run_src and 'emit(out' in _run_src,
      '_run 在非零退出码下也把已生成的报告 emit 出去')
# 3) 思考不是错误流: 人在终端时思考与回答都走 stdout, 重定向才分流
_dz_src = inspect.getsource(_zen._do_zen)
check('reason_sink = sys.stdout if tty else sys.stderr' in _dz_src,
      'zen 展示层: 终端里思考走 stdout, 仅重定向时才让出 stdout')
# ===== 粘性会话: 整点轮换 (同一小时内复用, 跨整点换新) =====
import tempfile as _tf                                  # noqa: E402
import time as _tm                                      # noqa: E402
from webtool.cli import zenproto as _zp                 # noqa: E402
_zd = _tf.mkdtemp()
_sp = os.path.join(_zd, 'sticky.json')
_new = lambda: _zp.StickySession(period=3600, path=_sp)  # noqa: E731
_ss1 = _new()
check(_ss1.ses_id == _new().ses_id, 'sticky: 同一小时内跨进程复用同一个 ses_id')
_h1 = _ss1.headers()
check(_h1['x-opencode-session-id'] == _ss1.ses_id
      and _h1['x-opencode-session'] == _ss1.ses_id, 'session-id 与 session 同值')
check(_ss1.headers()['x-opencode-request'] != _h1['x-opencode-request'],
      'msg/request id 逐请求换新 (不跟着 sticky)')
with open(_sp, encoding='utf-8') as _f:
    _d = json.load(_f)
check(set(_d) == {'session_id', 'bucket', 'created'}, 'sticky 状态含 {id,bucket,created}')
check(_d['bucket'] == int(_tm.time() // 3600), 'sticky: bucket 即当前小时数 (按整点对齐)')
_d['bucket'] -= 1                                       # 模拟"上一个整点"
with open(_sp, 'w', encoding='utf-8') as _f:
    json.dump(_d, _f)
check(_new().ses_id != _ss1.ses_id, 'sticky: 跨整点换新 ses_id (按整点, 非满一小时)')
check(_zp.StickySession(period=3600, path=os.path.join(_zd, 'none.json')).ses_id.startswith('ses_'),
      'sticky: 状态文件缺失时自建, 不报错')

# ===== zen 免费层闸门契约 (2026-10-14 抓包逐项二分得到, 改动都会掉回 403) =====
check(_zp._endpoints()[0].endswith('/inference/v1/chat/completions'),
      'zen 打新推理端点 /inference/v1 (旧 /zen/v1 不给免费层)')
_dt = {t['function']['name']: t for t in _zp.tools()}
check(set(_dt) == {'bash', 'read'}, '默认工具集 = bash+read (闸门最小集)', str(sorted(_dt)))
check(all(len(t['function'].get('description', '')) > 700 for t in _dt.values()),
      '工具描述是原版全文 (截短会被 403)',
      str([len(t['function'].get('description', '')) for t in _dt.values()]))
check(all(t['function'].get('parameters', {}).get('properties') for t in _dt.values()),
      '工具参数是真 schema, 不是空壳')
_b = __import__('json').loads(_zp.build_body('big-pickle', 'hi'))
check(_b['tool_choice'] == 'auto', '默认 tool_choice=auto (闸门判据)')
check(len(_zp.tools('all')) == 12, 'tools(all) 给全 12 个真机定义')
_bo = _zen._backoff
_seq = [_bo(i) for i in (1, 2, 3, 4)]
# 断言按"基准 ± 抖动"来, 别按相邻比值 —— 抖动 ±25% 时相邻比值最低 1.2,
# 用 >1.4 判会偶发假失败 (2026-10-15 撞上过一次)
check(all(abs(x - r) <= r * _zen.RETRY_JITTER + 1e-9
          for x, r in zip(_seq, (2, 4, 8, 16))),
      '重试退避基准 2/4/8/16s, 偏差不超 ±25% 抖动', str([round(x, 1) for x in _seq]))
check(all(_seq[i + 1] > _seq[i] for i in range(3)) and _bo(9) <= 60.0,
      '退避单调递增且封顶 60s (抖动不打乱次序)')
check(_bo(1, '30') == 30.0 and _bo(1, '9999') <= 60.0,
      '服务端 Retry-After 优先, 但封顶 60s')

check('on_reason' in inspect.getsource(_zen.call_zen),
      'call_zen 有单独的 reason 回调 (不是把思考混进正文)')
# 真机 13 个头 (2026-10-15 抓包): 头名集合必须一致, 不能少也不能多
_REAL_HDRS_LOWER = {'authorization', 'content-type', 'user-agent',
                    'x-opencode-client', 'x-opencode-project',
                    'x-opencode-request', 'x-opencode-session',
                    'x-opencode-session-id', 'connection', 'accept', 'host',
                    'accept-encoding', 'content-length'}
# 头集以官方 1.19.0 的 MITM 抓包为基准 (2026-10-14/15): 少发/多发都算回归。
# 我们手写 10 个 (accept-encoding 是后来补的), 另三个不由我们写: host 与
# content-length http.client 补, connection 被 urllib 写死成 close (真机是
# keep-alive) —— 加起来就是真机那 13 个头。
_OUR_HEADERS = {'authorization', 'content-type', 'user-agent',
                'x-opencode-client', 'x-opencode-project', 'x-opencode-session',
                'x-opencode-session-id', 'x-opencode-request', 'accept',
                'accept-encoding'}
# 库自己加/改的三个: host、content-length 由 http.client 补, connection 被 urllib 写死成 close
_LIB_HEADERS = {'host', 'content-length', 'connection'}
_h = {k.lower() for k in _zp.build_headers()}
check(_h == _OUR_HEADERS, 'zen 手写请求头与官方抓包一致 (10 个',
      str(sorted(_h ^ _OUR_HEADERS)))
check(_h | _LIB_HEADERS == _REAL_HDRS_LOWER,
      '手写 10 + 库补/改的 3 = 真机 13 个, 不多不少')
_hs = _zp.build_headers(ses_id='ses_test')
check(_hs['x-opencode-session'] == _hs['x-opencode-session-id'],
      'x-opencode-session 与 x-opencode-session-id 同值 (真机如此)')
_zp_ua = inspect.getsource(__import__('webtool.cli.zenproto', fromlist=['x']))
check(re.search(r"USER_AGENT = 'opencode/\d+\.\d+\.\d+ "
                r"ai-sdk/provider-utils/\d+\.\d+\.\d+ "
                r"runtime/bun/\d+\.\d+\.\d+'", _zp_ua) is not None,
      'UA 三段形状完整 (改版本号时别写残)')
_m_src2 = inspect.getsource(_zen._print_models)
check('created' in _m_src2 and 'owned_by' in _m_src2 and
      '未' not in _m_src2.split('免费层')[0][-40:],
      '模型表只用接口字段 (id/created/owned_by) + 命名约定的免费层')
# mcp fetch --via exa/parallel/firecrawl: call_verb 的默认 proxy=None 会让它
# 直连, 而同一 URL 的本地链走代理 —— 两条出口两种 IP。
_f_src = inspect.getsource(netfetch._fetch_via_mcp)
check("proxy=proxy if proxy is not None else 'auto'" in _f_src,
      '远程 reader 与本地链线路一致 (不再隐式直连)')
# radar 两件套 (rules.py 已删: load_rules 一调必炸的零调用死模块):
# proxy=None 曾 = 直连, 与 instances 的 auto 语义打架
for _fn, _nm in ((_ri.instances, 'instances'),
                 (_rr.load_routes, 'load_routes')):
    check('or \'auto\'' in inspect.getsource(_fn),
          f'radar.{_nm} 的 proxy=None 按 auto 处理 (非强制直连)')
check("proxy = proxy or 'auto'" in inspect.getsource(_ro.probe_official),
      'radar.probe_official 的 proxy=None 按 auto 处理')

# ===== zen 请求查看 (--dry-run / --show) 与 --tools 取值 =====
import contextlib                               # noqa: E402
import types as _ty                             # noqa: E402
from webtool.cli import app as _cli_app         # noqa: E402
_rt = _zp.resolve_tool_names
check(_rt(None) is None and _rt('min') is None, '--tools 默认/min → 闸门最小集 bash+read')
check(_rt('all') == 'all', '--tools all → 12 个真机 schema')
check(_rt('bash,read,grep') == ['bash', 'read', 'grep'] and _rt('bash read') == ['bash', 'read'],
      '--tools 逗号/空格清单切成名字表')
_pv = _zp.request_preview('big-pickle', 'hi')
check(set(_pv) == {'method', 'url', 'headers', 'body'},
      'request_preview 给 method/url/headers/body 四件')
check(_pv['method'] == 'POST' and _pv['url'] == _zp._endpoints()[0],
      '预览用的就是真会发的端点')
def _hget(headers, name):
    return next(v for k, v in headers.items() if k.lower() == name.lower())


check(_hget(_pv['headers'], 'x-opencode-session-id')
      == _hget(_pv['headers'], 'x-opencode-session'),
      '预览头里 session-id 与 session 同值')
_pv_l = {k.lower() for k in _pv['headers']}
check(_pv_l == _REAL_HDRS_LOWER, '预览头集合 = 真机 13 个, 不多不少',
      str(sorted(_pv_l ^ _REAL_HDRS_LOWER)))
check(list(_pv['headers'])[:10] == ['Authorization', 'Content-Type', 'User-Agent',
                                    'X-Opencode-Client', 'X-Opencode-Project',
                                    'X-Opencode-Request', 'X-Opencode-Session',
                                    'X-Opencode-Session-Id', 'Accept',
                                    'Accept-Encoding'],
      '我们手写的 10 个顺序照真机 (request 在 session 前), 头名按 urllib 规范化')
# 两处与真机必然不同, 且都不是我们选的: 头名大小写 / Connection 被写死成 close
check(_pv['headers']['Connection'] == 'close',
      'Connection 被 urllib 写死为 close (真机 keep-alive), 写进 headers 也是死代码')
_body_len = len(_zp.build_body('big-pickle', 'hi'))
check(_pv['headers']['Host'] == 'opencode.ai'
      and _pv['headers']['Content-Length'] == str(_body_len),
      'Host / Content-Length 由 http.client 补, 值取真 (长度 = 这份体的字节数)')
_u = _zen._unzipper
check(_u(None)(b'abc') == b'abc' and _u('identity')(b'abc') == b'abc', '无压缩时不折腾')
import zlib as _zl
_gz = _zl.compressobj(9, _zl.DEFLATED, 16 + _zl.MAX_WBITS)
_ug = _u('gzip')                             # 一个解压器全程复用 (增量)
check(_ug(_gz.compress(b'data: x')) + _ug(_gz.flush()) == b'data: x',
      'gzip 压缩流可增量解 (头抄了真机就得能接住)')
try:
    _u('br')(b'x')
    _br_ok = False
except RuntimeError as e:
    _br_ok = 'br' in str(e)
check(_br_ok, 'br/zstd 没有 stdlib 支持 → 明确报错, 不喂乱码')
check(sorted(t['function']['name'] for t in _pv['body']['tools']) == ['bash', 'read'],
      '默认预览体 = 闸门最小集 (bash+read)')
check(len(_zp.request_preview('m', 'p', tool_names='all')['body']['tools']) == 12,
      '--tools all 的预览体带全 12 个')
_sv = _zen._show_view
check(_sv(_ty.SimpleNamespace(dry_run=True)) == 'request'
      and _sv(_ty.SimpleNamespace(show='headers')) == 'headers',
      '--dry-run = --show request; --show 认四段')
check(_sv(_ty.SimpleNamespace(show_body=True)) == 'body'
      and _sv(_ty.SimpleNamespace(show_text=True)) == 'text',
      '旧名 --show-body/--show-text 仍映射到对应段')
check(_sv(_ty.SimpleNamespace()) is None, '没给查看开关 → 正常发请求')


def _cli_merged(*argv):
    """stdout+stderr 一起收 (CLI 的错误说明走 stderr)"""
    buf, ebuf = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(ebuf):
        rc = _cli_app.main(list(argv))
    return rc, buf.getvalue() + ebuf.getvalue()


def _cli(*argv):
    """进程内跑 CLI, 抓 stdout, 返回 (rc, 输出)"""
    _buf = io.StringIO()
    with contextlib.redirect_stdout(_buf):
        _rc = _cli_app.main(list(argv))
    return _rc, _buf.getvalue()


_rc, _o = _cli('zen', 'debug', '来看看')
check(_rc == 0 and _o.startswith('POST https://')
      and 'X-Opencode-Session-Id: ses_' in _o        # 预览给的是服务端视角的头名
      and 'Connection: close' in _o and '"tool_choice": "auto"' in _o,
      'zen debug: URL + 请求头 (服务端视角) + 请求体 一次看全, 不出网')
_rc, _o = _cli('zen', 'debug', '来看看', '--show', 'headers')
check(_rc == 0 and 'Authorization:' in _o and '{' not in _o, 'zen debug --show headers: 只出请求头')
_rc, _o = _cli('zen', 'debug', '来看看', '-f', 'json')
check(json.loads(_o)['body']['tools'][0]['function']['name'] == 'bash',
      'zen debug -f json: 结构可直接管道')
_rc, _o = _cli('zen', 'debug', '来看看', '--show', 'body')
check(_rc == 0 and json.loads(_o)['model'] == 'big-pickle', 'zen debug --show body: 结构可解析')
_rc, _o = _cli('zen', 'debug', '来看看', '--show', 'bogus')
check(_rc == 2, '--show 传错值报错退出 (不再静默 exit 0)')
_w = _zen._tool_warn
check(_w(_ty.SimpleNamespace(tools='min')) is None and _w(_ty.SimpleNamespace(tools='all')) is None,
      '--tools min/all 不报警')
check('缺 read' in (_w(_ty.SimpleNamespace(tools='bash,edit')) or ''),
      '--tools 缺 bash/read → 提醒大概率 403')
check('工具名不存在' in (_w(_ty.SimpleNamespace(tools='bash,read,nope')) or ''),
      '--tools 写了不存在的工具名 → 提醒会被丢掉')
_rc, _o = _cli('zen', 'chat', '-h')      # 布尔对要在 help 里成对出现
check(_rc == 0 and '--live' in _o and '--no-live' in _o,
      '--live / --no-live 布尔对能解析')

print('\n=== 思考标签 / 思考强度 / 着色 ===')
# 混在正文里的思考标签: 标签前是思考, 标签后才是答案
check(_zen.split_think('想了半天</think>答案在这') == ('想了半天', '答案在这'),
      'split_think: </think> 前归思考, 后归正文')
check(_zen.split_think('只有开标签<think>没写完')[1] == '',
      '只有开标签 (截断) → 整段算思考')
check(_zen.split_think('干净正文') == ('', '干净正文'), '没有标签原样返回')
check(_zen.split_think('</think>直接答案') == ('', '直接答案'),
      '上游只留了闭标签也能剥')
_s = _zen._ThinkSplitter()
_parts = []
for _c in ['abc', '<', 'think', '>', 'zz', '</', 'think', '>', 'done']:
    _parts += _s.feed(_c)
_parts += _s.flush()
check(''.join(t for k, t in _parts if k == 'think') == 'zz'
      and ''.join(t for k, t in _parts if k == 'text') == 'abcdone',
      '流式分片: 跨 chunk 的标签也认得出, 标签本身不打出去')
_s2 = _zen._ThinkSplitter()
_half = '我刚才在想' + '</thi'          # 尾巴是半个闭标签, 必须扣住
check(''.join(t for k, t in _s2.feed(_half) if k == 'text') == '我刚才在想',
      '扣住可能是标签前缀的尾巴, 不吐半截')
check(''.join(t for k, t in _s2.feed('nk>') if k == 'text') == '',
      '标签补齐后不把 </think> 当正文')
# _do_zen 里正文与思考标签的最终定性, 由 split_think 兜底
_b = _zp.build_body('m', 'p', tool_names=None)
check(b'reasoning_effort' not in _b, 'build_body 不显式给就不带 reasoning_effort')
_b = _zp.build_body('m', 'p', tool_names=None, reasoning_effort='xhigh')
check(json.loads(_b)['reasoning_effort'] == 'xhigh',
      '--think 的值原样进请求体 (可选值随模型而异, 不预判)')
check(_cli_app._norm_think(None) == 'medium', '不填 --think → 默认 medium')
check(_cli_app._norm_think('off') is None and _cli_app._norm_think('none') is None,
      '--think off/none → 不带该字段')
check(_cli_app._norm_think('XHigh') == 'XHigh', '取值只去空白, 不改大小写')
_rc, _o = _cli('zen', 'debug', 'x', '--think', 'xhigh', '-f', 'json')
check(_rc == 0 and json.loads(_o)['body']['reasoning_effort'] == 'xhigh',
      'dry-run 预览里能看到 --think 落到请求体')
_rc, _o = _cli('zen', 'debug', 'x', '-f', 'json')
check(json.loads(_o)['body']['reasoning_effort'] == 'medium',
      '不填时请求体里带默认 medium')
_rc, _o = _cli('zen', 'debug', 'x', '--think', 'off', '-f', 'json')
check(_rc == 0 and 'reasoning_effort' not in json.loads(_o)['body'],
      '--think off → 不带该字段')
check(_zen._blames_effort({'status': 400,
                           'error_body': 'Unsupported parameter: reasoning_effort'})
      and not _zen._blames_effort({'status': 400, 'error_body': 'bad tools'}),
      '只在报错真提到 effort 时才归因到思考强度')
check(_zen._color_on() is False, '非终端不上色 (测试进程 stdout 不是 tty)')

print('\n=== zen 默认值可配 (命令行 > zen.json > 内置) ===')
# 命令行是变长参数, 拼一次; 早前 _do_zen 又 join 了一次, 把字符串按**字符**插空格
_rc, _o = _cli('zen', 'debug', 'hello world', '--show', 'text', '-f', 'json')
check(json.loads(_o)[1]['content'] == 'hello world',
      '提示词不被二次 join 拆成单字 (h e l l o)')
_rc, _o = _cli('zen', 'debug', 'x', '-f', 'json')
_b = json.loads(_o)['body']
check(_b['max_tokens'] == _zp.DEFAULT_MAX_TOKENS == 200000,
      'max_tokens 内置默认 200000')
check(_b['model'] == 'big-pickle' and _b['tool_choice'] == 'auto',
      'model/tool_choice 内置默认')
_zd = os.path.join(WEBTOOL_DIR, 'zen.json')
with open(_zd, 'w', encoding='utf-8') as _f:
    json.dump({'zen': {'model': 'mimo-x', 'max_tokens': 8000,
                       'reasoning_effort': 'high', 'tools': 'all',
                       'live': False, 'tool_choice': 'auto',
                       'extra_body': {'thinking': {'type': 'enabled'}}}}, _f)
from webtool.core import config_data as _CD          # noqa: E402
_CD.invalidate()
try:
    _rc, _o = _cli('zen', 'debug', 'x', '-f', 'json')
    _b = json.loads(_o)['body']
    check(_b['model'] == 'mimo-x' and _b['max_tokens'] == 8000
          and _b['reasoning_effort'] == 'high' and len(_b['tools']) == 12,
          'zen.json 的 zen 段覆盖内置默认')
    _rc, _o = _cli('zen', 'debug', 'x', '--max-tokens', '100',
                   '--think', 'low', '--model', 'y', '-f', 'json')
    _b = json.loads(_o)['body']
    check(_b['max_tokens'] == 100 and _b['reasoning_effort'] == 'low'
          and _b['model'] == 'y', '命令行覆盖 zen.json')
    _dd = _zp.defaults()
    check(_dd['live'] is False, 'zen.json 的 live 生效 (默认是否边收边打也可配)')
    check(_dd['extra_body'] == {'thinking': {'type': 'enabled'}},
          'extra_body 原样读进来')
    check(json.loads(_o)['body']['thinking'] == {'type': 'enabled'},
          'extra_body 并入请求体 (thinking 之类的上游字段由它补)')
finally:
    os.remove(_zd)
    _CD.invalidate()

print('\n=== 线路只有一个决策点: 规则表 ===')
_ROOT = __import__('pathlib').Path(__file__).resolve().parent.parent
_SRC = _ROOT / 'src' / 'webtool'
for _f in ('pipeline/search.py', 'cli/sitesearch.py', 'engines/status.py',
           'net/transport.py', 'net/proxy/pool.py', 'net/mcpclient.py'):
    _t = (_SRC / _f).read_text(encoding='utf-8')
    check('engine_proxy' not in _t or '已废弃' in _t,
          f'{_f}: 没有引擎级线路覆盖 (只剩"已废弃"提示)', _f)
for _f in ('pipeline/search.py', 'cli/sitesearch.py', 'engines/status.py',
           'net/transport.py'):
    _t = (_SRC / _f).read_text(encoding='utf-8')
    check('proxy_hint' not in _t and '_proxy_alive' not in _t,
          f'{_f}: 没有"引擎自报线路"的残留', _f)
_pj = (_SRC / 'data/plugins.json').read_text(encoding='utf-8')
check('proxy_hint' not in _pj, '插件清单里不再声明 proxy_hint')
_rc, _o = _cli_merged('config', 'get', 'engine_proxy.google')
check(_rc == 2 and 'rules.json' in (_o or ''), 'config get engine_proxy.* 被拒并指向规则表', _rc)
_rc, _o = _cli_merged('config', 'set', 'engine_proxy.google', 'http://x')
check(_rc == 2 and 'rules.json' in (_o or ''), 'config set engine_proxy.* 被拒并指向规则表', _rc)
_rc, _o = _cli('proxy', 'get')
check('engine_proxy' not in (_o or '') or '已废弃' in _o,
      'proxy get 不再把 engine_proxy 当正常配置项', (_o or '')[:40])

print('\n=== 13. 出网原语必须登记 (新出口不许悄悄开) ===')
# netx 的统一是"决策"不是"实现": 现役出网实现就下面这些, 每条都得显式登记
# 并说明它靠哪条通道。新增一处 `requests.` / `_cr.Session` / `urlopen` 就是
# 又开了一个不受设计与测试照看的口子 —— 必须来这里签字 (顺手想清楚它要不要
# 反爬判定、走不走路由表)。
_NET_CHANNELS = {
    # 这三个不是"另开出口": 是补丁/类型层 —— tls.py 与 pyshim.py patch
    # requests.Session.request 把调用桥回 transport, fingerprints.py 只
    # 是导 curl_cffi 的类型字面量
    'net/tls.py': 'patch requests 会话的证书校验 (桥回 transport)',
    'net/pyshim.py': 'patch requests.Session.request (桥回 transport)',
    'net/fingerprints.py': '指纹档案: 导 curl_cffi 类型字面量, 不出网',
    'net/http.py': 'urllib 通道本体 (transport 备胎/探活)',
    'engines/sogou.py': 'PC cffi / urllib / 移动端 三通道',
    'net/netx.py': '决策层 + 参考通道 netx.get (当前无生产调用者)',
    'net/transport.py': '主通道: 指纹会话 + 降级梯 + 拦截判定',
    'net/adapters.py': 'requests 兼容适配器: 桥到 transport.request (转发, 不自己出网)',
    'net/routing.py': '出网路由: 逐请求线路 + cffi 会话 (数据源与 pyshim 共用)',
    'net/proxy/reach.py': '代理可达性探测: 一次 TCP 握手判"代理没起" (决定改不改走直连)',
}
_PRIMS = [r'^\s*import\s+requests\b', r'^\s*from\s+requests\b',
          r'^\s*import\s+http\.client\b', r'^\s*from\s+http\.client\b',
          r'^\s*import\s+socket\b',
          r'\brequests\.(get|post|request|Session)\b', r'\bcurl_requests\.',
          r'from curl_cffi', r'\b_cr\.[A-Z]', r'\bcr\.Session\(', r'urlopen\(',
          r'\bhttp\.client\b', r'HTTPConnection\(', r'\bsocket\.socket\b',
          r'\bsocket\.create_connection\b']
def _code_only(path):
    """原文照留, 只把字符串/注释的内容抹成空格

    之前试过逐 token 拼回去, `requests.Session` 会被拼成
    `requests . Session`, 正则反而失配; 也试过"含字符串就整行丢弃",
    结果 `transport._cr.Session(impersonate='...')` 这种行被整条吞掉,
    真出网的行反而漏检、已登记的通道被误判过时。按坐标挖空内容才对。
    """
    import io as _io
    import tokenize as _tk
    _src = path.read_text(encoding='utf-8')
    try:
        _toks = list(_tk.generate_tokens(_io.StringIO(_src).readline))
    except (_tk.TokenError, IndentationError):
        return _src
    _lines = [list(_l) for _l in _src.splitlines()]
    for _t in _toks:
        if _t.type not in (_tk.STRING, _tk.COMMENT):
            continue
        (_r1, _c1), (_r2, _c2) = _t.start, _t.end
        for _r in range(_r1, _r2 + 1):
            if _r - 1 >= len(_lines):
                break
            _a = _c1 if _r == _r1 else 0
            _b = _c2 if _r == _r2 else len(_lines[_r - 1])
            for _i in range(_a, min(_b, len(_lines[_r - 1]))):
                _lines[_r - 1][_i] = ' '
    return '\n'.join(''.join(_l) for _l in _lines)


_unregistered = []
for _f in _SRC.rglob('*.py'):
    _rel = str(_f.relative_to(_SRC)).replace('\\', '/')
    _txt = _code_only(_f)
    if any(re.search(_p, _txt) for _p in _PRIMS) and _rel not in _NET_CHANNELS:
        _unregistered.append(_rel)
check(not _unregistered,
      '出网原语只出现在登记过的通道里 (新出口要显式登记)',
      str(_unregistered))
# re.M: _PRIMS 里 ^ 锚定的规则要逐行匹配, 否则只认全文第一行 (老 bug)
_stale = [k for k in _NET_CHANNELS
          if not any(re.search(_p, _code_only(_SRC / k), re.M)
                     for _p in _PRIMS)]
check(not _stale, '登记表没有过时条目 (改过的通道要同步)', str(_stale))

# ── 线路决策必须收口: 谁都别自己决定"直连还是走代理" ──────────────────────────
# 起因: netx.resolve_proxy 曾把 None 当"强制直连", 而 proxyhelper.resolve 把
# None 升成 auto —— 同一份 rules.json 在两条入口上给出相反结果。更坑的是调用方
# 看不出区别: 引擎签名都是 `proxy=None`, 谁忘了把管线传下来的 'auto' 再传下去,
# 谁的会话就永久直连、规则表连问都不问一次。
print('\n== 线路决策只许有一个出口 ==')

_route_callers = set()
for _f in _SRC.rglob('*.py'):
    _rel = str(_f.relative_to(_SRC)).replace('\\', '/')
    _txt = _f.read_text(encoding='utf-8')
    if re.search(r'(?<!def )\b(?:rules\.)?(?:resolve_route|proxy_for)\(', _txt):
        # 去掉"定义处": `def proxy_for(` 不算调用
        _calls = [m for m in re.finditer(r'\b(?:rules\.)?(?:resolve_route|proxy_for)\(', _txt)
                  if 'def ' not in _txt[max(0, m.start() - 4):m.start()]]
        if _calls:
            _route_callers.add(_rel)
_ROUTE_OK = {
    'net/netx.py',        # 唯一收口点: 把 None/'auto'/'direct'/具体 URL 归一
    'net/rules/loader.py',  # 路由表实现本身 (自检入口)
    'net/rules/router.py',  # 路由表实现本身 (proxy_for 的定义)
    'cli/pkg.py',         # 终端消费者: 只把结论翻成子进程的 *_PROXY 环境变量
}
_stray_route = sorted(_route_callers - _ROUTE_OK)
check(not _stray_route,
      'resolve_route/proxy_for 没扩散 (别的模块一律经 netx.resolve_proxy)',
      str(_stray_route))

# 只在**线路**上做 'auto' 分支。`via == 'auto'` 那类取数通道选择不算 (另一码事)
_out_auto = subprocess.run(['rg', '-n', '-l', r"proxy\w*\s*==\s*'auto'", 'src'],
                           cwd=ROOT, capture_output=True, text=True).stdout
_auto_users = set(_out_auto.strip().splitlines()) if _out_auto.strip() else set()
_AUTO_USERS_OK = {'src/webtool/net/netx.py', 'src/webtool/net/http.py',
                  'src/webtool/net/rules/loader.py',
                  'src/webtool/cli/pkg.py', 'src/webtool/net/proxyhelper.py'}
check(not (_auto_users - _AUTO_USERS_OK),
      "只有归一层的入口能在 proxy 上做 'auto' 分支",
      str(sorted(_auto_users - _AUTO_USERS_OK)))

# --no-proxy 的约定值: 必须写字符串 'direct'。写 None 会被当成"没表态"交回规则表,
# 于是 --no-proxy 反而"跟配置走"。这一条是纯文本守卫, 专治手滑。
# 只看两种真出事的写法: `None if ... no_proxy` / `if ... no_proxy:` 紧跟 `return None`。
# (函数签名里的 `no_proxy=False, proxy=None` 和纯转发 `_run(None, ..., no_proxy)` 不算)
_bad_np = []
for _f in _SRC.rglob('*.py'):
    _lines = _f.read_text(encoding='utf-8').splitlines()
    for _i, _ln in enumerate(_lines, 1):
        if 'def ' in _ln or 'no_proxy' not in _ln:
            continue
        _nxt = _lines[_i].strip() if _i < len(_lines) else ''
        if re.search(r'None\s+if', _ln) or re.match(r'return\s+None\b', _nxt):
            _bad_np.append(f'{_f.relative_to(_SRC)}:{_i}')
check(not _bad_np,
      "no_proxy 的行不许拿 None 当强制直连 (要写 'direct')", str(_bad_np))

# 代理归一必须带目标 URL: 只传代理、不传 URL 等于规则表拿不到域名, 只能退默认动作,
# 域名规则对那条请求就是失效的 —— 用户看到的"规则没起作用"多半是这个。
# netx.resolve_proxy / proxyhelper.resolve 形参是 (proxy, url) → 必须两参;
# _routing.resolve 是 (url, override) → 一参正常。
# 只认这几个具名入口, 免得 Path.resolve() 之类混进来。
_bare_resolve = []
for _f in _SRC.rglob('*.py'):
    _txt = _f.read_text(encoding='utf-8')
    _rel = str(_f.relative_to(_SRC)).replace('\\', '/')
    for _m in re.finditer(r'\b(resolve_proxy|_routing\.resolve|proxyhelper\.resolve|'
                          r'netx\.resolve|_netx\.resolve)\(([^()]*)\)', _txt):
        _fn, _args = _m.group(1), _m.group(2)
        if 'def ' in _txt[max(0, _m.start() - 30):_m.start()]:
            continue
        # _routing.resolve(url, override) 首参就是 URL, 一参也合规;
        # 其余几个形参是 (proxy, url), 少了 URL 就是规则表拿不到域名
        _need_two = _fn != '_routing.resolve'
        if not _args or (_need_two and ',' not in _args):
            _bang = _txt[: _m.start()].count('\n') + 1
            _bare_resolve.append(f'{_rel}:{_bang} ({_fn})')
check(not _bare_resolve,
      '每次线路归一都带上了目标 URL (单参调用规则表拿不到域名)',
      str(_bare_resolve))

print(f'\n{PASS + FAIL + SKIP} 项: {PASS} PASS, {FAIL} FAIL, {SKIP} SKIP')
sys.exit(1 if FAIL else 0)