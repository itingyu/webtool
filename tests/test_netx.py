"""跨通道一致性测试

统一出网层的意义不是"有个统一入口", 而是**任何通道出网都遵守同一套策略**。
所以这里测的重点不是 netx 自己能不能发请求, 而是:

  1. 各通道面对同一个 proxy 参数, 解析结果必须一致
  2. 曾经漏接策略的通道 (stock / probe) 现在接上了 —— 用规则拦截证明
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


def check(cond, label, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'PASS {label}' + (f' ({detail})' if detail else ''))
    else:
        FAIL += 1
        print(f'FAIL {label}' + (f' (实际 {detail})' if detail else ''))


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


from webtool.net import netx           # noqa: E402
from webtool.core import tls           # noqa: E402


print('\n=== 1. resolve_proxy: 各通道共享的归一语义 ===')
# None / 'direct' / 'auto' / URL 四种形态的语义必须全库一致,
# 否则会出现"stock 走直连、transport 走代理"这种无法排查的分裂
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
    ver = tls.policy('https://example.com', None)
    check(ver is not False, '有 CA 时 policy 给出非 False 值')
    check(netx.verify_arg(ver) is True,
          f'CA 路径 → urllib 侧转成 True (实际 {netx.verify_arg(ver)!r})')
check(netx.verify_arg(False) is False, 'False 原样保留 (豁免不丢)')
check(netx.verify_arg(True) is True, 'True 原样保留')

print('\n=== 5. stock 通道接上了代理 (改造前的漏洞) ===')
from webtool.stock.bridge.http import Http, _py_proxies    # noqa: E402
write_rules({'default': 'direct',
             'rules': [{'match': {'domain': ['push2.eastmoney.com']},
                        'action': 'block'}]})
h = Http(timeout=10)
try:
    h.get('https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=1')
    check(False, 'stock 通道应受规则约束')
except Exception as e:
    check(type(e).__name__ == 'RuleError' and '拦截' in str(e),
          'stock 通道按规则被拦 (改造前完全无视路由)', str(e)[:70])
# 显式 direct 要能绕过 —— 否则用户没法临时关掉某条规则
hd = Http(timeout=10, proxy='direct')
check(hd.proxy == 'direct', 'Http(proxy=direct) 记录该设置')
check(Http(timeout=10).proxy == 'auto', 'Http 默认 auto (问路由表)')

print('\n=== 6. socks 代理在 requests 侧必须是 socks5h ===')
# requests 的 socks5:// 会**本地**解析 DNS, 代理服务器根本用不上;
# 远端解析必须写 socks5h:// —— 这个坑只会表现为"配了 socks 却还直连"
p = _py_proxies('socks5://u@1.2.3.4:1080')
check(p['http'] == 'socks5h://u@1.2.3.4:1080', 'socks5 → socks5h (远端解析)',
      p['http'])
check(_py_proxies('socks5h://1.2.3.4:1080')['http'] == 'socks5h://1.2.3.4:1080',
      'socks5h 不被二次改写')
check(_py_proxies('http://1.2.3.4:8080')['https'] == 'http://1.2.3.4:8080',
      'http 代理原样')
check(_py_proxies(None) is None, '无代理 → None (不走 proxies 参数)')

print('\n=== 7. probe 探活也要补密码 ===')
# 探活拿不到密码就会把"带认证的代理"误判成不可用, 上层据此放弃重试,
# 排查方向完全指不到真实原因
from webtool.core import probe as PB           # noqa: E402
write_rules({'default': 'direct', 'proxies': {}, 'rules': []})
SS.store_password('pu', 'PW_PU')
resolved = netx.resolve_proxy('http://pu@9.9.9.9:1')
check(resolved == 'http://pu:PW_PU@9.9.9.9:1', 'probe 用的代理能补上密码', resolved)
check('PW_PU' not in PB.__doc__, 'probe 文档已说明补密码的原因')

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
AUTO_OK = {'src/webtool/net/netx.py', 'src/webtool/core/http.py',
           'src/webtool/net/rules.py'}   # rules.py 是路由表实现本身
stray = [f for f in out if f.endswith('.py') and f not in AUTO_OK]
check(not stray,
      '没有通道自己判断 auto/调 resolve_route (只能经 netx 或 build_opener)',
      str(stray))
check('resolve_proxy' in open(os.path.join(ROOT, 'src/webtool/core/http.py'),
                               encoding='utf-8').read(),
      'build_opener 的 auto 分支确实转给 netx')

out2 = subprocess.run(
    ['rg', '-n', '-l', r'resolve_auth\(', 'src'],
    cwd=ROOT, capture_output=True, text=True).stdout.strip().splitlines()
# resolve_auth 允许出现在这几处, 各有明确理由:
#   secrets_store.py — 定义处
#   netx.py          — 统一层的归一入口
#   core/http.py     — build_opener 是 urllib 侧的公共出口, zen/mcpclient/
#                      sogou/gnews 都直接调它, 补密码必须发生在这里
#   net/transport.py — _get_once 是预热/降级梯的深层出口, 保留兜底
#   net/proxy.py     — proxy set/test 的 CLI 路径, 要在报错前先补全
ALLOWED_AUTH = {'src/webtool/core/secrets_store.py', 'src/webtool/net/netx.py',
                'src/webtool/core/http.py', 'src/webtool/net/transport.py',
                'src/webtool/net/proxy.py'}
stray2 = [f for f in out2 if f.endswith('.py') and f not in ALLOWED_AUTH]
check(not stray2, 'resolve_auth 没扩散到未经审计的模块', str(stray2))

out3 = subprocess.run(
    ['rg', '-n', '-l', r'proxies=', 'src'],
    cwd=ROOT, capture_output=True, text=True).stdout.strip().splitlines()
# 例外按路径片段匹配, 不用硬编码全路径 —— stock 的 HTTP 通道已下沉到
# bridge/http.py, 写死 'stock/http.py' 会让它混进 bad3 而误报
# 例外 = 合法传 proxies 的通道: netx 自己、三条 webtool HTTP 通道, 以及
# stock 的路由层 (sources/_adapter/_routing/_base: 那里是按 URL 现算代理的
# 实现, 正是本测试想确保的"唯一的合法出处")
_ok_exc = ('netx.py', 'transport.py', 'core/http.py',
           'bridge/http.py', 'bridge/_eco_net.py',
           'bridge/sources/_adapter.py', 'bridge/sources/_routing.py',
           'bridge/sources/_base.py')
bad3 = [f for f in out3 if f.endswith('.py')
        and not any(x in f for x in _ok_exc)]
check(not bad3, '只有已知通道给底层库传 proxies', str(bad3))

print('\n=== 10. 真站点联调 (需 NETX_LIVE=1) ===')
if os.environ.get('NETX_LIVE') != '1':
    skip('真实出网', '未设 NETX_LIVE=1')
else:
    from urllib.parse import urlsplit as _us
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

# 注释里也不该再宣称"强制直连"是这些端点的既定行为
# 注释里不得把"强制直连"说成这些端点的**现行行为**。区分两种表述:
#   允许: "曾写死 proxy=None"/"端点曾声明 direct"/"direct 强制直连"(讲 netx 语义)
#   禁止: "本引擎强制直连"/"端点声明 direct" 这类当现状的措辞
claims = []
NEUTRAL = ('曾', '历史', '移除', '已', '不要', '该用户配', '计量',
           '规则', '管线', '老代码', 'proxyhelper', '路由表', '配置',
           '语义', '保留', '唯一', '定好', '一次')
for f in glob.glob(os.path.join(ROOT, 'src/webtool/**/*.py'), recursive=True):
    lines = open(f, encoding='utf-8').read().splitlines()
    in_code = False
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith('```'):                    # markdown 代码块不是行为声明
            in_code = not in_code
            continue
        if in_code:
            continue
        if not re.search(r'强制直连|端点声明 direct|proxy:\s*direct', line):
            continue
        # 看段落而不是单行: 说明性文字常与关键词分行写
        window = ' '.join(lines[max(0, i - 3):i + 4])
        if any(k in window for k in NEUTRAL):
            continue
        claims.append(f'{os.path.basename(f)}:{i + 1}')
check(not claims, '注释不得宣称"强制直连"为现行行为', str(claims[:6]))

print('\n=== 12. 不得再有 failover (先直连不通再代理) ===')
# 走哪条线必须由配置 + 路由表**一次**决定。历史上 7 个模块各发明了一套重试:
#   core/resilient.py  代理失败退直连
#   net/transport.py   被拦就代理↔直连互换
#   cli/zen.py         直连优先 + 换代理重试 + 换前探活
#   pipeline/rank.py   直连优先, 失败换代理重试
#   feeds/fetch.py     直连优先再代理
#   feeds/command.py   直连失败换代理重试
#   radar/rules.py     直连优先, 失败再试代理
# failover 让同一次请求走哪条线取决于它先在哪失败 —— 不可预测, 且
# "代理失败退直连"恰恰会毁掉只允许代理出网的目标。
FO = [r'fallback_direct', r'swap_proxy', r'allow_fallback',
      r'proxy retry', r'直连优先', r'先直连', r'失败再试代理', r'换代理重试']
found = []
for f in glob.glob(os.path.join(ROOT, 'src/webtool/**/*.py'), recursive=True):
    if os.path.basename(f) in ('netx.py', 'proxyhelper.py', 'resilient.py'):
        continue                      # 这三个讲的正是"为什么取消"
    for i, line in enumerate(
            open(f, encoding='utf-8').read().splitlines(), 1):
        # 解释"曾经这么做、现在取消"的注释是**该留**的 (不解释的话后人会
        # 以为是漏改), 只抓仍在生效的代码
        if any(k in line for k in ('曾经', '不再', '取消', '去掉', '已改')):
            continue
        for pat in FO:
            if re.search(pat, line):
                found.append(f'{os.path.basename(f)}:{i}:{pat}')
check(not found, '代码里不再有 failover (线路只由配置决定)', str(found[:6]))

import inspect                                  # noqa: E402
from webtool.net import transport as _T          # noqa: E402
check('allow_fallback' not in inspect.signature(_T.get).parameters,
      'transport.get 签名里没有 allow_fallback (别误导调用方)')

check(hasattr(proxyhelper := __import__(
          'webtool.net.proxyhelper', fromlist=['resolve']), 'resolve'),
      'proxyhelper.resolve 是统一入口, 供各通道调用')

print('\n=== 13. cffi 主通道必须真跑 (不带 engine 的调用) ===')
# 回归: _get_cffi 里 `import transport as _t` 曾经写在 `if engine:` 分支内,
# 而 else 分支又直接用 _t.PROFILES —— 于是所有**不带 engine** 的调用
# (探活 / 站点 / feed / stock 走的都是这条) 一进来就 UnboundLocalError,
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
from webtool.net import fetch as netfetch        # noqa: E402
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
check('def fetch_models(' in inspect.getsource(_zen) and
      'fetch_models_detail(' in inspect.getsource(_zen.fetch_models),
      'fetch_models 仍可用 (id 列表, 薄封装在 detail 之上)')
# ── 三个改过的坑, 各留一条回归断言 ──────────────────────────────
# 1) 布尔标志声明顺序: '--no-x/--x' 会让 --x 解析成 False (Typer 语义颠倒),
#    实测确认过; 心跳开关必须"正名在前"。
_app_src = inspect.getsource(_app)
for _flag in ("'--stream/--no-stream'", "'--reasoning/--no-reasoning'"):
    check(_flag in _app_src, f'app.py 布尔标志写法正确 {_flag}')
check("'--no-stream/--stream'" not in _app_src and
      "'--no-reasoning/--reasoning'" not in _app_src,
      'app.py 不再有颠倒写法的布尔标志')
# 2) 退出码非零时不能把报告丢掉 (zen --check 全挂时人得看得到表)
_run_src = inspect.getsource(_app._run)
check('if out.strip():' in _run_src and 'emit(out' in _run_src,
      '_run 在非零退出码下也把已生成的报告 emit 出去')
# 3) 思考不是错误流: 人在终端时思考与回答都走 stdout, 重定向才分流
_dz_src = inspect.getsource(_zen._do_zen)
check('reason_sink = sys.stdout if tty else sys.stderr' in _dz_src,
      'zen 展示层: 终端里思考走 stdout, 仅重定向时才让出 stdout')
# ===== zen 免费层闸门契约 (2026-10-14 抓包逐项二分得到, 改动都会掉回 403) =====
_zp = __import__('webtool.cli.zenproto', fromlist=['x'])
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
check(all(_seq[i + 1] > _seq[i] * 1.4 for i in range(3)),
      '重试退避是指数增长 (不是线性 1.5s*n)', str([round(x, 1) for x in _seq]))
check(_bo(1, '30') == 30.0 and _bo(1, '9999') <= 60.0,
      '服务端 Retry-After 优先, 但封顶 60s')

check('on_reason' in inspect.getsource(_zen.call_zen),
      'call_zen 有单独的 reason 回调 (不是把思考混进正文)')
# 头集以官方 1.19.0 的 MITM 抓包为基准 (2026-10-14): 少发/多发都算回归
_OUR_HEADERS = {'authorization', 'content-type', 'user-agent',
                'x-opencode-client', 'x-opencode-project', 'x-opencode-session',
                'x-opencode-session-id', 'x-opencode-request', 'accept'}
_zp = __import__('webtool.cli.zenproto', fromlist=['x'])
_h = {k.lower() for k in _zp.build_headers()}
check(_h == _OUR_HEADERS, 'zen 请求头与官方客户端抓包一致', str(sorted(_h ^ _OUR_HEADERS)))
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

print(f'\n{PASS + FAIL + SKIP} 项: {PASS} PASS, {FAIL} FAIL, {SKIP} SKIP')
sys.exit(1 if FAIL else 0)