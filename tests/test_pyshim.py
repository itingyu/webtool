"""pyshim 离线自检: requests 门替的装/卸与响应映射 (脚本式, 直接 python 跑)

不打出网请求 —— 上游可达性波动太大, 出网验证靠真实调用
(`webtool pydata akshare.stock_zh_a_hist ...`)。

用法: PYTHONPATH=src python tests/test_pyshim.py
"""
import sys

from webtool.net import pyshim
import requests.sessions as _sess

fails = []


def check(name, fn):
    try:
        fn()
        print('  PASS', name)
    except Exception as e:                                  # noqa: BLE001
        fails.append(name)
        print(f'  FAIL {name} → {type(e).__name__}: {e}')


def t_install_uninstall():
    orig = _sess.Session.request
    pyshim.install()
    assert pyshim.is_active(), 'install 后应为激活态'
    assert _sess.Session.request is pyshim._shimmed_request
    pyshim.uninstall()
    assert _sess.Session.request is orig, 'uninstall 不还原'
    pyshim.install()          # 留在激活态, 后面的映射测试用得到


def t_response_mapping():
    class _FakeCr:            # 模拟 curl_cffi Response 的够用面
        status_code = 200
        url = 'https://x/y?a=1'

        class _H(dict):
            pass

        headers = {'Content-Type': 'application/json; charset=utf-8',
                   'Server': 'nginx'}
        content = b'{"ok": 1}'
        encoding = None
        cookies = {'k': 'v'}
        reason = 'OK'

    r = pyshim._to_requests_response(_FakeCr())
    assert r.status_code == 200 and r.ok
    assert r.json() == {'ok': 1}, f'json 解析不对: {r.json()!r}'
    assert r.headers.get('server') == 'nginx'
    assert r.text == '{"ok": 1}'
    assert r.url == 'https://x/y?a=1'
    assert r.cookies.get('k') == 'v', 'response cookies 应进 jar'
    assert r.history == []          # 单跳无重定向链


def t_client_headers_filtered():
    """裸 requests 的 python-requests UA 必须被滤掉, 换成浏览器档案 UA"""
    class _FakeInner:
        kw = None

        def __init__(self):
            self._s = self                 # pyshim 走 s._s.request

        def request(self, method, url, **kw):
            self.kw = kw
            raise RuntimeError('stop')          # 拿到 headers 即断

    holder = []

    class _FakeCls:
        def __new__(cls, *a, **kw):
            fi = _FakeInner()
            holder.append(fi)
            return fi

    import webtool.net.routing as _rt
    orig = _rt.RoutedCffiSession
    _rt.RoutedCffiSession = _FakeCls
    try:
        class _S:           # 只用 headers/cookies 两个属性
            headers = {'User-Agent': 'python-requests/2.32.0',
                       'Accept-Encoding': 'gzip, deflate', 'X-Lib': '1'}
            cookies = []

        try:
            pyshim._shimmed_request(_S, 'GET', 'https://push2.eastmoney.com/x',
                                    timeout=5, verify=False)
        except RuntimeError:
            pass
        h = holder[0].kw['headers']
        assert 'python-requests' not in str(h.get('User-Agent')), 'UA 未滤'
        assert h.get('X-Lib') == '1', '库自定义头应保留'
        assert h.get('User-Agent') and h['User-Agent'] != 'python-requests'
    finally:
        _rt.RoutedCffiSession = orig


if __name__ == '__main__':
    for t in (('install/uninstall 幂等', t_install_uninstall),
              ('curl响应→requests.Response 映射', t_response_mapping),
              ('requests 身份头过滤/浏览器档案垫底', t_client_headers_filtered)):
        check(*t)
    if fails:
        print(f'\nFAILED {len(fails)} 项: {fails}')
        sys.exit(1)
    print('ALL PASS')
