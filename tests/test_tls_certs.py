"""证书机制: 自带 CA 兜底 / extra 合并 / 失败分类

不进网络。断言的是"探测与合并的决策", 不是某个站点的证书。
"""
import os
import shutil
import ssl
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

TMP = tempfile.mkdtemp(prefix='webtool-certs-')
os.environ['WEBTOOL_DIR'] = TMP
from webtool.core import tls                                    # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print('PASS', name)
    else:
        FAIL += 1
        print('FAIL', name, ' ', detail)


REAL = tls.bundled_ca()
check('仓库自带 ca-bundle.pem 存在且非空',
      REAL and os.path.getsize(REAL) > 50000, str(REAL))
try:
    ssl.create_default_context(cafile=REAL)
    ok_load = True
except Exception as e:                                          # noqa: BLE001
    ok_load = str(e)
check('自带 CA 能被 OpenSSL 直接加载', ok_load is True, str(ok_load))
check('ca_available() 探得到 CA', tls.ca_available()[0] is True)

# 从真 bundle 里切两份真证书当 extra: 合并后还得是合法 CA 文件
raw = open(REAL, 'rb').read()
blocks = [b'-----BEGIN CERTIFICATE-----' + b + b'-----END CERTIFICATE-----\n'
          for b in raw.split(b'-----BEGIN CERTIFICATE-----')[1:]]
check('自带 bundle 里切出了证书块', len(blocks) > 50, str(len(blocks)))


def sandbox():
    """造一份"包内证书目录"的替身 (extra/ 先留空)"""
    d = os.path.join(TMP, 'certs')
    os.makedirs(os.path.join(d, 'extra'), exist_ok=True)
    with open(os.path.join(d, 'ca-bundle.pem'), 'wb') as f:
        f.write(raw)
    return d


base_dir = sandbox()
tls._certs_dir = lambda: base_dir
tls._CA_CACHE = (None, None)
# 把环境变量指到这份替身, 决策就完全由我们控制 (环境变量是第一候选)
os.environ['SSL_CERT_FILE'] = os.path.join(base_dir, 'ca-bundle.pem')

check('extra/ 空时: 直接用基础 CA, 不做合并',
      tls._probe_ca()[0] == os.environ['SSL_CERT_FILE'], str(tls._probe_ca()))
check('extra() 空目录 → []', tls.extra_certs() == [])

# 往 extra/ 丢一份证书 —— 同进程内必须立刻生效 (缓存按内容指纹失效)
with open(os.path.join(base_dir, 'extra', 'site.pem'), 'wb') as f:
    f.write(blocks[0])
tls._CA_CACHE = (None, None)
merged, why = tls._probe_ca()
check('extra/ 有证书 → 走合并文件 (不是基础 CA)', merged != os.environ['SSL_CERT_FILE'], merged)
check('合并文件落在 cache/tls/ 下', '/tls/' in merged.replace(os.sep, '/'), merged)
check('合并说明写清了份数', '+ 包内 1 份站点证书' in why, why)
check('合并文件里基础 CA 与 extra 都在',
      open(merged, 'rb').read().count(b'BEGIN CERTIFICATE') == len(blocks) + 1,
      str(open(merged, 'rb').read().count(b'BEGIN CERTIFICATE')))
try:
    ssl.create_default_context(cafile=merged)
    ok2 = True
except Exception as e:                                          # noqa: BLE001
    ok2 = str(e)
check('合并出来的文件本身是合法 CA 文件', ok2 is True, str(ok2))
check('重复探测 → 同一份合并文件 (走缓存)',
      tls._probe_ca()[0] == merged)

with open(os.path.join(base_dir, 'extra', 'site.pem'), 'wb') as f:
    f.write(blocks[1])
tls._CA_CACHE = (None, None)
check('换掉 extra 里的证书 → 重新合并 (新文件)',
      tls._probe_ca()[0] != merged, tls._probe_ca()[0])

# ── 宿主没有 CA 时, 兜底到自带包 (而不是"关校验") ──────────────────────
class _NoPaths:
    cafile = '/nope/cert.pem'
    openssl_cafile = '/nope/openssl.pem'
    openssl_capath = '/nope'
    capath = None


_saved = ssl.get_default_verify_paths
ssl.get_default_verify_paths = lambda: _NoPaths()
_mod = type(sys)('certifi')
_mod.where = lambda: '/nope/certifi.pem'
sys.modules['certifi'] = _mod
for k in ('SSL_CERT_FILE', 'CURL_CA_BUNDLE', 'REQUESTS_CA_BUNDLE'):
    os.environ.pop(k, None)
tls._CA_CACHE = (None, None)
got, why = tls._probe_ca()
# extra/ 里有证书时会给"自带 CA + extra"的合并文件, 所以这里认说明而不是路径
check('宿主没 CA → 用仓库自带那份兜底',
      os.path.join(base_dir, 'ca-bundle.pem') in why, why)
check('自带兜底是"看得见"的', '宿主没装 ca-certificates' in why, why)
check('宿主没 CA 也仍然开着校验 (不再降级为不校验)',
      tls.policy('https://push2.eastmoney.com/') is not False,
      str(tls.policy('https://push2.eastmoney.com/')))
ssl.get_default_verify_paths = _saved

# ── 合并写不进去时退回基础 CA (不能因为缓存目录只读就丢掉信任根) ────────
os.environ['SSL_CERT_FILE'] = os.path.join(base_dir, 'ca-bundle.pem')
_saved_cd = tls._cache_dir
tls._cache_dir = lambda: '/proc/definitely-not-writable'
try:
    back, why2 = tls._merge_extras(os.environ['SSL_CERT_FILE'], tls.extra_certs())
finally:
    tls._cache_dir = _saved_cd
check('合并失败 → 退回基础 CA, 不丢信任根',
      back == os.environ['SSL_CERT_FILE'] and '合并失败' in why2, why2)

# ── 证书失败的分类: 类别不同, 处置就必须不同 ────────────────────────────
def _err(code=None, msg='boom'):
    e = ssl.SSLCertVerificationError(1, msg)
    if code:
        e.verify_code = code
    return e


k62, f62 = tls.cert_advice(_err(62, 'hostname mismatch'), 'www.gfex.com.cn')
check('62 → 域名不符', '域名不符' in k62 and 'gfex' in f62, k62)
check('62 的修法明确劝住"别改 ca_bundle"', '别去动 ca_bundle' in f62, f62)
k18, f18 = tls.cert_advice(_err(18, 'self signed certificate'), 'x.com')
check('18 → 自签, 指向 data/certs/extra/', '自签' in k18 and 'extra/' in f18, f18)
k10, f10 = tls.cert_advice(_err(10, 'certificate has expired'), 'x.com')
check('10 → 过期, 不说"塞 CA 能修"', '过期' in k10 and 'verify_hosts' in f10, f10)
k20, f20 = tls.cert_advice(_err(20, 'unable to get local issuer certificate'), 'x.com')
check('20 → 缺中间证书, 指向 ca_bundle', '中间证书' in k20 and 'ca_bundle' in f20, f20)
kL, fL = tls.cert_advice(
    Exception('SSLError(1, "[SSL: UNSAFE_LEGACY_RENEGOTIATION_DISABLED]")'),
    'human.amac.org.cn')
check('legacy 重协商 → 明说"不是证书问题"', '不是证书问题' in kL, kL)
kX, fX = tls.cert_advice(Exception('connection reset'), 'x.com')
check('分不出来的不硬编', kX == '' and fX == '', kX)
kC, fC = tls.cert_advice(Exception('wrapped'), 'x.com')
check('裹在 .reason 里的也能认出来',
      tls.cert_advice(type('E', (Exception,), {'reason': _err(18, 'self signed')})(), 'x.com')[0] != '', '')

# ── extra/ 里的东西必须是证书, 别的文件别瞎认 ──────────────────────────
with open(os.path.join(base_dir, 'extra', 'notes.txt'), 'w') as f:
    f.write('hi')
with open(os.path.join(base_dir, 'extra', 'another.crt'), 'wb') as f:
    f.write(blocks[2])
tls._CA_CACHE = (None, None)
got = [os.path.basename(p) for p in tls.extra_certs()]
check('.txt 忽略, .crt 收下', got == ['another.crt', 'site.pem'], str(got))

shutil.rmtree(TMP, ignore_errors=True)
print('\n%d PASS, %d FAIL' % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
