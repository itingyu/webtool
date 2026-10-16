# -*- coding: utf-8 -*-
"""TLS 证书策略回归测试 (纯离线, 不出网)

覆盖 net.tls 的三件事:
1. 开关语义 —— ssl_verify 总开关 / ca_bundle / verify_hosts 点名豁免
2. 域名解析 —— host_of / hit_insecure (子域、端口、凭据、大小写)
3. 异常分类 —— is_tls_error 必须认出三条通道各自包装的证书错误

第 3 条是踩过的坑: urllib 把 SSLError 裹进 URLError.reason, requests 的
SSLError 又不是 ssl.SSLError 的子类 —— 任何类型元组都盖不全, 漏网的后果是
证书失败被当成网络抖动进降级梯重试 4 次。这里用真实的异常类型锁死。

跑法: python3 tests/test_tls.py
"""
import json
import os
import ssl
import sys
import tempfile
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import requests

from webtool.net import tls

fails = []


def check(cond, msg):
    if not cond:
        fails.append(msg)
    print(('PASS ' if cond else 'FAIL ') + msg)


class _Cfg:
    """把 ~/.webtool/config.json 指到临时文件, 测完还原 (不碰用户真实配置)"""

    def __init__(self, **kw):
        self.kw = kw
        self.tmp = tempfile.NamedTemporaryFile('w', suffix='.json',
                                               delete=False)
        self.tmp.write('{}')
        self.tmp.close()
        self.saved = os.environ.get('WEBTOOL_TEST_CFG')

    def __enter__(self):
        os.environ['WEBTOOL_TEST_CFG'] = self.tmp.name
        json.dump(self.kw, open(self.tmp.name, 'w'))
        tls._CACHE = (None, None)          # 绕过 mtime 缓存
        return self

    def __exit__(self, *a):
        os.unlink(self.tmp.name)
        if self.saved is None:
            os.environ.pop('WEBTOOL_TEST_CFG', None)
        else:
            os.environ['WEBTOOL_TEST_CFG'] = self.saved
        tls._CACHE = (None, None)
        return False


# ---- 1. 域名解析 ----
_hcases = [('https://a.com/x', 'a.com', '基本'),
           ('https://WWW.A.com:8443/x?y=1', 'www.a.com', '大小写+端口+query'),
           ('https://user:pw@a.com/x', 'a.com', '带凭据'),
           ('a.com/path', 'a.com', '无 scheme'),
           ('https://[::1]:443/x', '::1', 'IPv6 字面量'),
           ('', '', '空串'),
           (None, '', 'None')]
_bad = [d for u, w, d in _hcases if tls.host_of(u) != w]
check(not _bad, f'host_of 域名解析 {len(_hcases)} 例全对 (错: {_bad or "无"})')

# 子域匹配: a.com 应覆盖 www.a.com, 但不能覆盖 evil-a.com
_hosts = frozenset({'a.com'})
check(tls.hit_insecure('a.com', _hosts), '精确命中')
check(tls.hit_insecure('www.a.com', _hosts), '子域命中')
check(tls.hit_insecure('deep.www.a.com', _hosts), '多级子域命中')
check(not tls.hit_insecure('evil-a.com', _hosts), 'evil-a.com 不算 a.com 子域')
check(not tls.hit_insecure('b.com', _hosts), '无关域不命中')
check(not tls.hit_insecure('', _hosts), '空 host 不命中')

# ---- 2. 开关语义 ----
# 默认: 严格校验, 返回解析好的 CA 路径 (不是 True —— True 会让各通道
# 自己去读 REQUESTS_CA_BUNDLE, 三通道就可能用三套信任根)
import webtool.net.proxy as _px
_orig_path = _px.store.CONFIG_PATH
with tempfile.TemporaryDirectory() as _d:
    _cfg = os.path.join(_d, 'config.json')
    _px.store.CONFIG_PATH = _cfg
    try:
        def _write(**kw):
            json.dump(kw, open(_cfg, 'w'))
            tls._CACHE = (None, None)

        _write()
        check(tls.policy('https://a.com') != False,   # noqa: E712
              f'默认严格校验 ({tls.policy("https://a.com")})')
        check(tls.describe()['ssl_verify'] == 'on', 'describe 默认 on')

        # ssl_verify 总开关
        _write(ssl_verify='off')
        check(tls.policy('https://a.com') is False, 'ssl_verify=off 全站不校验')
        _write(ssl_verify='on')
        check(tls.policy('https://a.com') != False,   # noqa: E712
              'ssl_verify=on 恢复校验')

        # verify_hosts 点名豁免: 只对该域开口, 其余流量不受影响
        _write(ssl_verify='on', verify_hosts=['expired.badssl.com'])
        check(tls.policy('https://expired.badssl.com') is False, '白名单域放行')
        check(tls.policy('https://www.expired.badssl.com') is False, '白名单子域放行')
        check(tls.policy('https://other.com') != False,   # noqa: E712
              '白名单不影响其他域')

        # 字符串形式也认 (用户手改 config.json 常见)
        _write(verify_hosts='a.com, b.com')
        check(tls.hit_insecure('a.com') and tls.hit_insecure('b.com'),
              'verify_hosts 字符串解析 (逗号/分号/空格)')

        # 调用方显式覆盖优先于配置
        _write(ssl_verify='on', verify_hosts=['a.com'])
        check(tls.policy('https://a.com', verify=True) != False,  # noqa: E712
              'verify=True 覆盖白名单')
        _write(ssl_verify='off')
        check(tls.policy('https://a.com', verify=True) != False,  # noqa: E712
              'verify=True 覆盖全局 off')

        # ca_bundle: 存在 → 用它; 不存在 → 当场报错而不是静默降级
        _ca = os.path.join(_d, 'ca.pem')
        ssl.get_default_verify_paths() and open(_ca, 'w').write('')
        _write(ssl_verify='on', ca_bundle=_ca)
        check(tls.policy('https://a.com') == _ca, 'ca_bundle 指定自定义 CA')
        _write(ssl_verify='on', ca_bundle='/nope/missing.pem')
        try:
            tls.policy('https://a.com')
            check(False, 'ca_bundle 路径不存在应报错')
        except tls.TlsConfigError as e:
            check('不存在' in str(e), f'ca_bundle 路径不存在即报错 ({str(e)[:40]})')

        # 非法 ssl_verify 值
        _write(ssl_verify='maybe')
        try:
            tls.policy('https://a.com')
            check(False, 'ssl_verify 非法值应报错')
        except tls.TlsConfigError:
            check(True, 'ssl_verify 非法值即报错')
    finally:
        _px.store.CONFIG_PATH = _orig_path
        tls._CACHE = (None, None)

# ---- 3. ssl_context 语义 ----
_ctx_strict = tls.ssl_context('https://a.com', verify=True)
check(_ctx_strict.verify_mode == ssl.CERT_REQUIRED and _ctx_strict.check_hostname,
      'ssl_context 严格模式 CERT_REQUIRED + check_hostname')
_ctx_off = tls.ssl_context('https://a.com', verify=False)
check(_ctx_off.verify_mode == ssl.CERT_NONE and not _ctx_off.check_hostname,
      'ssl_context verify=False 走 CERT_NONE')
check(tls.ssl_context('https://a.com', verify=True) is _ctx_strict,
      'ssl_context 同参数复用 (避免每请求重建)')

# ---- 4. is_tls_error: 三通道的证书错误都得认出 ----
class _FakeCffiErr(OSError):
    """模拟 curl_cffi 的 CertificateVerifyError (只继承 OSError, 不是 ssl.*)"""


_FakeCffiErr.__module__ = 'curl_cffi.requests.exceptions'
_FakeCffiErr.__name__ = 'CertificateVerifyError'

_tls_cases = [
    (ssl.SSLError('x'), True, 'ssl.SSLError'),
    (ssl.CertificateError('x'), True, 'ssl.CertificateError'),
    (tls.TlsConfigError('x'), True, 'TlsConfigError'),
    (urllib.error.URLError(ssl.SSLCertVerificationError('expired')), True,
     'urllib 把 SSLError 裹进 URLError.reason'),
    (requests.exceptions.SSLError('x'), True, 'requests.SSLError (非 ssl 子类)'),
    (_FakeCffiErr('x'), True, 'curl_cffi.CertificateVerifyError'),
    (ConnectionRefusedError('x'), False, '连接被拒 (非证书)'),
    (requests.exceptions.ConnectionError('x'), False, 'requests 连接错'),
    (TimeoutError('x'), False, '超时'),
    (urllib.error.HTTPError('u', 404, 'nf', {}, None), False, 'HTTP 404'),
]
_bad = [d for e, w, d in _tls_cases if tls.is_tls_error(e) != w]
check(not _bad, f'is_tls_error 跨通道分类 {len(_tls_cases)} 例全对 (错: {_bad or "无"})')

# 关键负样本: requests.SSLError 不是 ssl.SSLError 子类, 只查类型元组会漏
check(not issubclass(requests.exceptions.SSLError, ssl.SSLError),
      'requests.SSLError 确实不是 ssl.SSLError 子类 (元组方案为何失效)')

# ---- 5. CA 环境探测与"无 CA 自动降级" ----
# 精简环境可能没装 ca-certificates。此时若照常严格校验, 所有 HTTPS 会 100%
# 失败且报错指不到根因 —— 所以必须探环境并降级, 且降级要写进 describe()。
_ok, _why = tls.ca_available()
check(isinstance(_ok, bool) and bool(_why), f'ca_available 返回 (bool, 说明) ({_why})')
check(tls.policy('https://a.com') != False,   # noqa: E712
      '有 CA 时 policy 给路径 (不是 True, 否则各通道各读环境变量)')


def _no_ca_env():
    """把所有 CA 来源都指向不存在的文件, 模拟没装 ca-certificates

    仓库自带的那份 CA 包 (`data/certs/ca-bundle.pem`) 也要一起拿掉 —— 它就是
    最后的保底, 不屏蔽的话"无 CA"这个场景根本造不出来。
    """
    import certifi
    saved = {k: os.environ.get(k) for k in
             ('SSL_CERT_FILE', 'CURL_CA_BUNDLE', 'REQUESTS_CA_BUNDLE')}
    for k in saved:
        os.environ[k] = '/nonexistent/ca.pem'
    orig_paths, orig_where = ssl.get_default_verify_paths, certifi.where
    orig_bundled = tls.bundled_ca
    ssl.get_default_verify_paths = lambda: ssl.DefaultVerifyPaths(
        cafile='/nonexistent/a.pem', capath='/nonexistent/dir',
        openssl_cafile='/nonexistent/a.pem', openssl_capath='/nonexistent/dir',
        openssl_cafile_env='SSL_CERT_FILE', openssl_capath_env='SSL_CERT_DIR')
    certifi.where = lambda: '/nonexistent/certifi.pem'
    tls.bundled_ca = lambda: None
    tls._CA_CACHE = tls._CACHE = (None, None)

    def _restore():
        ssl.get_default_verify_paths, certifi.where = orig_paths, orig_where
        tls.bundled_ca = orig_bundled
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        tls._CA_CACHE = tls._CACHE = (None, None)
    return _restore


_restore = _no_ca_env()
try:
    check(tls.ca_available()[0] is False, '无 CA 环境探测为不可用')
    check(tls.policy('https://a.com') is False,
          '无 CA 时 policy 降级为 False (而非全线失败)')
    _d = tls.describe()
    check(_d['ssl_verify'] == 'off', '无 CA 时 describe 显示生效策略 off')
    check('warning' in _d and 'ca_bundle' in _d['warning'],
          f'降级原因写进 describe.warning ({"有" if "warning" in _d else "无"})')
    _ctx = tls.ssl_context('https://a.com')
    check(_ctx.verify_mode == ssl.CERT_NONE,
          '无 CA 时 ssl_context 走 CERT_NONE')
finally:
    _restore()
check(tls.ca_available()[0] is True, 'CA 恢复后自动探测回可用 (无需改配置)')

# ---- 6. 配置键注册与校验 ----
from webtool.cli import config as _cfgmod
for k in ('ssl_verify', 'ca_bundle', 'verify_hosts'):
    check(k in _cfgmod.CONFIG_KEYS, f'config 键 {k} 已注册')

ok, v = _cfgmod._validate('ssl_verify', 'off')
check(ok and v == 'off', 'ssl_verify=off 校验通过')
ok, v = _cfgmod._validate('verify_hosts', ' a.com , b.com ')
check(ok and v == ['a.com', 'b.com'], f'verify_hosts 归一化 ({v})')
ok, _v = _cfgmod._validate('verify_hosts', 'https://a.com/x')
check(not ok, 'verify_hosts 拒带路径的值')
ok, _v = _cfgmod._validate('verify_hosts', '  ')
check(not ok, 'verify_hosts 拒空值')

# DEFAULTS 必须含这三个键, 否则 load_config 的白名单过滤会把用户配置丢掉
from webtool.net.proxy import DEFAULTS as _D
for k in ('ssl_verify', 'ca_bundle', 'verify_hosts'):
    check(k in _D, f'proxy.DEFAULTS 含 {k} (否则用户配置被过滤掉)')

print()
if fails:
    print(f'{len(fails)} FAILED')
    sys.exit(1)
print('ALL PASS')