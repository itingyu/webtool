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
from webtool.net import tls                                    # noqa: E402

PASS = FAIL = 0


def check(cond, msg, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print('PASS', msg)
    else:
        FAIL += 1
        print('FAIL', msg, ' ', detail)


REAL = tls.bundled_ca()
check(REAL and os.path.getsize(REAL) > 50000,
      '仓库自带 ca-bundle.pem 存在且非空', str(REAL))
try:
    ssl.create_default_context(cafile=REAL)
    ok_load = True
except Exception as e:                                          # noqa: BLE001
    ok_load = str(e)
check(ok_load is True, '自带 CA 能被 OpenSSL 直接加载', str(ok_load))
check(tls.ca_available()[0] is True, 'ca_available() 探得到 CA')

# 从真 bundle 里切两份真证书当 extra: 合并后还得是合法 CA 文件
raw = open(REAL, 'rb').read()
blocks = [b'-----BEGIN CERTIFICATE-----' + b + b'-----END CERTIFICATE-----\n'
          for b in raw.split(b'-----BEGIN CERTIFICATE-----')[1:]]
check(len(blocks) > 50, '自带 bundle 里切出了证书块', str(len(blocks)))


def sandbox():
    """造一份"包内证书目录"的替身 (extra/ 先留空)

    特意放在 `pkg/certs/` 而不是 `certs/`: 用户目录是 `$WEBTOOL_DIR/certs/extra`,
    两者得分开才测得出"读的是哪一份"。
    """
    d = os.path.join(TMP, 'pkg', 'certs')
    os.makedirs(os.path.join(d, 'extra'), exist_ok=True)
    with open(os.path.join(d, 'ca-bundle.pem'), 'wb') as f:
        f.write(raw)
    return d


base_dir = sandbox()
tls._certs_dir = lambda: base_dir
tls._CA_CACHE = (None, None)
# 把环境变量指到这份替身, 决策就完全由我们控制 (环境变量是第一候选)
os.environ['SSL_CERT_FILE'] = os.path.join(base_dir, 'ca-bundle.pem')

check(tls._probe_ca()[0] == os.environ['SSL_CERT_FILE'],
      'extra/ 空时: 直接用基础 CA, 不做合并', str(tls._probe_ca()))
check(tls.extra_certs() == [], 'extra() 空目录 → []')

# 往 extra/ 丢一份证书 —— 同进程内必须立刻生效 (缓存按内容指纹失效)
with open(os.path.join(base_dir, 'extra', 'site.pem'), 'wb') as f:
    f.write(blocks[0])
tls._CA_CACHE = (None, None)
merged, why = tls._probe_ca()
check(merged != os.environ['SSL_CERT_FILE'], 'extra/ 有证书 → 走合并文件 (不是基础 CA)', merged)
check('/tls/' in merged.replace(os.sep, '/'), '合并文件落在 cache/tls/ 下', merged)
check('+ 站点证书 1 份' in why, '合并说明写清了份数', why)
check(open(merged, 'rb').read().count(b'BEGIN CERTIFICATE') == len(blocks) + 1,
      '合并文件里基础 CA 与 extra 都在',
      str(open(merged, 'rb').read().count(b'BEGIN CERTIFICATE')))
try:
    ssl.create_default_context(cafile=merged)
    ok2 = True
except Exception as e:                                          # noqa: BLE001
    ok2 = str(e)
check(ok2 is True, '合并出来的文件本身是合法 CA 文件', str(ok2))
check(tls._probe_ca()[0] == merged,
      '重复探测 → 同一份合并文件 (走缓存)')

with open(os.path.join(base_dir, 'extra', 'site.pem'), 'wb') as f:
    f.write(blocks[1])
tls._CA_CACHE = (None, None)
check(tls._probe_ca()[0] != merged,
      '换掉 extra 里的证书 → 重新合并 (新文件)', tls._probe_ca()[0])

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
check(os.path.join(base_dir, 'ca-bundle.pem') in why,
      '宿主没 CA → 用仓库自带那份兜底', why)
check('宿主没装 ca-certificates' in why, '自带兜底是"看得见"的', why)
check(tls.policy('https://push2.eastmoney.com/') is not False,
      '宿主没 CA 也仍然开着校验 (不再降级为不校验)',
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
check(back == os.environ['SSL_CERT_FILE'] and '合并失败' in why2,
      '合并失败 → 退回基础 CA, 不丢信任根', why2)

# ── 证书失败的分类: 类别不同, 处置就必须不同 ────────────────────────────
def _err(code=None, msg='boom'):
    e = ssl.SSLCertVerificationError(1, msg)
    if code:
        e.verify_code = code
    return e


k62, f62 = tls.cert_advice(_err(62, 'hostname mismatch'), 'www.gfex.com.cn')
check('域名不符' in k62 and 'gfex' in f62, '62 → 域名不符', k62)
check('别去动 ca_bundle' in f62, '62 的修法明确劝住"别改 ca_bundle"', f62)
k18, f18 = tls.cert_advice(_err(18, 'self signed certificate'), 'x.com')
check('自签' in k18 and '~/.webtool/certs/extra/' in f18,
      '18 → 自签, 指向用户目录的投放点 (包目录升级即被替换)', f18)
k10, f10 = tls.cert_advice(_err(10, 'certificate has expired'), 'x.com')
check('过期' in k10 and 'verify_hosts' in f10, '10 → 过期, 不说"塞 CA 能修"', f10)
k20, f20 = tls.cert_advice(_err(20, 'unable to get local issuer certificate'), 'x.com')
check('中间证书' in k20 and 'ca_bundle' in f20, '20 → 缺中间证书, 指向 ca_bundle', f20)
kL, fL = tls.cert_advice(
    Exception('SSLError(1, "[SSL: UNSAFE_LEGACY_RENEGOTIATION_DISABLED]")'),
    'human.amac.org.cn')
check('不是证书问题' in kL, 'legacy 重协商 → 明说"不是证书问题"', kL)
kX, fX = tls.cert_advice(Exception('connection reset'), 'x.com')
check(kX == '' and fX == '', '分不出来的不硬编', kX)
kC, fC = tls.cert_advice(Exception('wrapped'), 'x.com')
check(tls.cert_advice(type('E', (Exception,), {'reason': _err(18, 'self signed')})(),
                      'x.com')[0] != '',
      '裹在 .reason 里的也能认出来', '')

# ── 投放点必须在用户目录: 包目录升级整棵被替换 ──────────────────────────
# 包内 extra/ 落在 site-packages, `pip install --upgrade` 会把整棵目录换掉 ——
# 实测用户塞在包目录的证书活不过一次 force-reinstall, 表现成"某站证书突然又报错"。
_user_extra = os.path.join(TMP, 'certs', 'extra')          # ~/.webtool/certs/extra
check(tls.extra_dirs()[0] == _user_extra
      and tls.extra_dirs()[1] == os.path.join(base_dir, 'extra'),
      '投放点: 用户目录在前, 包内目录只当发行方预置', str(tls.extra_dirs()))
os.makedirs(_user_extra, exist_ok=True)
with open(os.path.join(_user_extra, 'mine.pem'), 'wb') as f:
    f.write(blocks[0])
got = tls.extra_certs()
check(os.path.basename(got[0]) == 'mine.pem' and got[0].startswith(_user_extra),
      '用户目录里的证书被收下且排最前', str(got))
tls._CA_CACHE = (None, None)
check(open(tls._probe_ca()[0], 'rb').read().count(b'BEGIN CERTIFICATE') ==
      len(blocks) + 2,
      '用户目录的证书真的进了合并文件 (基础 CA + 2 份)', str(tls._probe_ca()[0]))
with open(os.path.join(base_dir, 'extra', 'mine.pem'), 'wb') as f:
    f.write(blocks[3])
got = tls.extra_certs()
check([os.path.basename(p) for p in got].count('mine.pem') == 1
      and got[0].startswith(_user_extra),
      '同名证书: 只有用户目录那份被采用 (包内预置不覆盖用户)', str(got))

# 自带 CA 包: 用户目录那份优先, 缺了回落包内那份
check(tls.ca_bundle_candidates()[0] == os.path.join(TMP, 'certs', 'ca-bundle.pem')
      and tls.ca_bundle_candidates()[1] == os.path.join(base_dir, 'ca-bundle.pem'),
      '自带 CA 包候选: 用户目录在前, 包内兜底', str(tls.ca_bundle_candidates()))
check(tls.bundled_ca() == os.path.join(base_dir, 'ca-bundle.pem'),
      '用户目录没有 CA 包 → 回落包内那份', str(tls.bundled_ca()))
_user_ca = os.path.join(TMP, 'certs', 'ca-bundle.pem')
with open(_user_ca, 'wb') as f:
    f.write(raw)
check(tls.bundled_ca() == _user_ca, '用户目录有 CA 包 → 用那份 (可增补企业根)',
      str(tls.bundled_ca()))
os.unlink(_user_ca)
tls._CA_CACHE = (None, None)

# ── extra/ 里的东西必须是证书, 别的文件别瞎认 ──────────────────────────
with open(os.path.join(base_dir, 'extra', 'notes.txt'), 'w') as f:
    f.write('hi')
with open(os.path.join(base_dir, 'extra', 'another.crt'), 'wb') as f:
    f.write(blocks[2])
tls._CA_CACHE = (None, None)
got = [os.path.basename(p) for p in tls.extra_certs()]
check(got == ['mine.pem', 'another.crt', 'site.pem'],
      '.txt 忽略, .crt 收下 (用户目录在前)', str(got))

shutil.rmtree(TMP, ignore_errors=True)
print('\n%d PASS, %d FAIL' % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
