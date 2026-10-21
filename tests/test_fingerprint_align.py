"""UA 与 impersonate 目标的对齐

要点: 求解器解出来的 cf_clearance 绑在"那台浏览器"上, 抓取端复用它时
impersonate 的 Chrome 版本得跟求解端对上, 否则 clearance 绑定不上。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
os.environ['WEBTOOL_DIR'] = tempfile.mkdtemp(prefix='wt-fpalign-')

from webtool.net import fingerprints                       # noqa: E402

checks = fails = 0


def check(cond, msg, got=''):
    global checks, fails
    if cond:
        checks += 1
        print('PASS', msg)
    else:
        fails += 1
        print('FAIL', msg, '|', got)


WIN136 = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
          '(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36')
LINUX131 = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
ANDROID142 = ('Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/142.0.0.0 Mobile Safari/537.36')
MAC150 = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
          '(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36')

# ── 1. UA → impersonate 目标 ───────────────────────────────────────────
t, major, plat = fingerprints.impersonate_for_ua(WIN136)
check(t == 'chrome136', 'Windows Chrome/136 → chrome136', t)
check(major == 136, '主版本号认对了', str(major))
check(plat == 'win', '平台认成 win', plat)

t, major, plat = fingerprints.impersonate_for_ua(LINUX131)
check(t == 'chrome131', 'Linux Chrome/131 → chrome131', t)
check(plat == 'linux', '平台认成 linux', plat)

t, major, plat = fingerprints.impersonate_for_ua(ANDROID142)
check(t == 'chrome142', 'Android Chrome/142 → chrome142', t)
check(plat == 'android', '平台认成 android', plat)

t, major, plat = fingerprints.impersonate_for_ua(MAC150)
check(t == 'chrome150', 'macOS Chrome/150 → chrome150', t)
check(plat == 'mac', '平台认成 mac', plat)

check(fingerprints.impersonate_for_ua('') is None, '空 UA 不瞎猜')
check(fingerprints.impersonate_for_ua('Mozilla/5.0 curl/8') is None,
      '非 Chrome UA 不瞎猜')

# ── 2. 目标清单是活的 (curl_cffi 升版就跟着多) ─────────────────────────
targets = fingerprints.chrome_targets()
check('chrome131' in targets, '清单含 chrome131', str(targets[:6]))
check(any(t.startswith('chrome13') and t != 'chrome131' for t in targets),
      '清单含更新的 Chrome 版本 (求解器那边早 136+)', str(targets[-6:]))

# ── 3. profile_for_ua: 能直接当档案用 ──────────────────────────────────
p = fingerprints.profile_for_ua(WIN136)
check(bool(p), 'UA 能换出档案')
check(p['impersonate'] == 'chrome136', '档案的 impersonate 对得上', p['impersonate'])
check(p['ua'] == WIN136, '档案带着原始 UA (给 urllib 兜底用)')
check(p['sec_ch_ua'] == '',
      'sec_ch_ua 留空 (品牌列表随版本变, 交给 impersonate 自己发)')
check(p['platform'] == '"Windows"', '平台提示按 UA 走', p['platform'])
check(fingerprints.profile_for_ua('') is None, '空 UA 换不出档案')

# ── 4. 兜底: 认不出的档案名不 KeyError, 借默认档案换 impersonate ──────
from webtool.net import transport                            # noqa: E402

prof = transport._profile('chrome136')
check(prof['impersonate'] == 'chrome136', '未知档案名走兜底', prof.get('impersonate'))
check('ua' in prof, '兜底档案仍带字段')
prof2 = transport._profile('chrome131_win')
check(prof2['impersonate'] == 'chrome131', '已知档案名照旧', prof2.get('impersonate'))
prof3 = transport._profile({'impersonate': 'chrome142', 'ua': 'X'})
check(prof3['impersonate'] == 'chrome142', 'dict 档案原样透传')

# ── 5. SDK 侧同一套逻辑 (外部插件进程只能用 SDK) ───────────────────────
import os                                                # noqa: E402
import importlib.util                                     # noqa: E402

_sdk_path = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'sdk', 'python', 'webtool_plugin_sdk.py')
_spec = importlib.util.spec_from_file_location('_wsdk', _sdk_path)
_wsdk = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_wsdk)

_ua136 = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
          '(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36')
_p = _wsdk.profile_for_ua(_ua136)
check(_p is not None and _p['impersonate'] == 'chrome136',
      'SDK: UA→impersonate 目标一致', _p)
check(_p and _p['sec_ch_ua'] == '',
      'SDK: sec_ch_ua 留空 (交给 impersonate 自己发)')
check(_p and _p['platform'] == '"Windows"',
      'SDK: 平台提示跟 UA 对上', _p and _p.get('platform'))
check(_wsdk.profile_for_ua('curl/8.0') is None,
      'SDK: 不是浏览器 UA 就别硬猜')

print()
print(f'{checks} PASS, {fails} FAIL')
sys.exit(1 if fails else 0)
