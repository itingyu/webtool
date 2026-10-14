"""各数据源的公共底座: 传输层与返回信封

拆包的依据是**数据源**, 不是文件位置 —— `sources/ths.py` 装同花顺的全部方法,
`sources/em.py` 装东财的, 依此类推。但传输层是跨源共享的, 所以抽到这里:

- `_ok` / `_err`   统一返回信封 (各源各定义一份会漂)
- `SourceBase`     持三个 session: `_std` (requests+Retry) / `_xs`
                   (curl_cffi chrome110, 雪球/腾讯 K 线共用指纹) / `_ths`
                   (同花顺 v cookie, 懒加载)
- 同花顺 v token   qjs 子进程跑 akshare 的 ths.js, 进程内缓存

划分依据: 私有辅助方法按实际调用方归属 ——
`_ths_data` 只被 ths_* 调, 留在 `ths.py`; `_xueqiu_session` 除 xueqiu_* 外还被
`tencent_kline_global` / `tencent_us_kline` / `tencent_minute` 借用 (要 curl_cffi
指纹才能过 web.ifzq.gtimg.cn, 但请求打的是腾讯域名), 属传输层, 放公共底座。

对外仍是 `APIClient` (见 `__init__.py` 的聚合门面), 154 个方法齐备,
所以 `rawapi` / 服务端 / stock-master 的调用方零改动。
"""
import warnings
warnings.filterwarnings('ignore')

import json
import re
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests
from curl_cffi import requests as cffi_requests

from webtool.stock.bridge.sources import _routing, _symbol


def _ok(data: Any, raw_size: int = 0) -> dict:
    """成功信封。所有源统一, 渲染层靠它识别成功。"""
    return {'ok': True, 'data': data, 'raw_size': raw_size}


def _err(error: str, status: int = 0) -> dict:
    """失败信封。带状态码, 渲染层与 fallback 链靠它换源。"""
    return {'ok': False, 'error': error, 'status': status}


# ── 同花顺 v token (qjs 子进程, 进程内只算一次) ──────────────────────
_THS_JS_PATH = '/usr/lib/python3.12/site-packages/akshare/data/ths.js'


@lru_cache(maxsize=1)
def _ths_v_token() -> str:
    """用 quickjs 算同花顺 v cookie 的值, 缓存到进程内。

    token 由 akshare 自带的 ths.js 生成, 是公开的反爬参数不是凭证。
    qjs 缺失时抛错让上层换源, 不静默发无 token 的请求 (会被 ban)。
    """
    js = Path(_THS_JS_PATH).read_text(encoding='utf-8')
    code = js + '\nconsole.log(v());\n'
    r = subprocess.run(['sh', '-c', f"echo '{code}' | qjs"],
                       capture_output=True, text=True, timeout=10)
    # fallback: 写到临时文件再跑
    if r.returncode != 0 or not r.stdout.strip():
        tmp = Path('/tmp/_ths_token.js')
        tmp.write_text(code, encoding='utf-8')
        r = subprocess.run(['qjs', str(tmp)], capture_output=True, text=True, timeout=10)
    token = r.stdout.strip().splitlines()[-1].strip()
    # 不用 assert: python -O 下断言被剥离, token 异常时会静默把垃圾 cookie 发出去
    if len(token) < 50:
        raise RuntimeError(f'同花顺 v token 异常 (len={len(token)}): {token[:80]!r}; '
                           f'检查 qjs 与 {_THS_JS_PATH}')
    return token


class SourceBase:
    """所有数据源方法混入此类。持 session 与超时, 不含任何源特有逻辑。"""

    BASE_TIMEOUT = 8

    def __init__(self, proxy=None):
        # proxy: None/'auto' = 逐 URL 问 netx 规则表 (默认); 'direct' 强制直连;
        # 传 URL 强制走那条。**不写进 session.proxies** —— 一次调用要打十余个
        # 域名, 绑在 session 上就只剩一个出口, 路由表逐域名决策的能力会失效。
        # 改成每请求现算 (见 self._px)。
        self._proxy = proxy
        self._std = requests.Session()
        self._std.proxies = {}            # 显式清空: 不继承环境变量
        self._std.trust_env = False       # 光清 proxies 不够: trust_env 还会
                                          # 把 http_proxy 合进来
        # 带路由的适配器: 每个请求按目标 URL 现算代理 (规则表说了算),
        # 内含 retry (解决间歇性 RemoteDisconnected)。61 个调用点零改动生效 ——
        # 逐个加 proxies= 漏一处就是一个源绕过规则表。
        from webtool.stock.bridge.sources._adapter import mount as _mount
        _mount(self._std, override=self._proxy)
        self._std.headers.update({'Accept-Language': 'zh-CN,zh;q=0.9'})
        # UA 不在这里写死: 由 _routing.headers_for() 按站点给浏览器指纹档案,
        # 与搜索引擎/抓取通道同一套, 免得每个源各留一份必然过期的硬编码。
        self._xs: Any = None            # curl_cffi, 雪球/腾讯 K 线
        self._ths: Any = None           # 同花顺 (懒加载)

    # ── 出网策略: 每请求现算, 不绑在 session 上 ──
    def _px(self, url):
        """本请求该走的代理 (None = 直连)。规则表说了算。"""
        return _routing.resolve(url, self._proxy)

    def _kwargs(self, url, **over):
        """给 requests.get/post 的请求级参数: 代理 + 证书 + 默认头。

        `over` 里的 headers/params 等原样带出; `verify=False` 这类显式豁免
        优先级高于规则表。
        """
        kw = dict(over)
        px = _routing.proxies_for(url, self._proxy)
        if px:
            kw['proxies'] = px
        if kw.get('verify') is None:
            kw['verify'] = _routing.verify_for(url)
        return kw

    # ── 传输层: curl_cffi 会话 (雪球 TLS 指纹 + 腾讯 K 线过反爬) ──
    def _xueqiu_session(self) -> Any:
        """curl_cffi chrome110 + 3 页 warmup 收 cookie。

        命名保留 xueqiu 是历史原因: 首个使用者是雪球, 后来腾讯 K 线也借它
        的指纹。新代码直接用这个名字即可, 不必关心归属哪个站。
        """
        if self._xs is None:
            self._xs = _routing.RoutedCffiSession(
                impersonate='chrome110', override=self._proxy)
            for url in ('https://xueqiu.com/', 'https://xueqiu.com/hq',
                        'https://xueqiu.com/S/SH688825'):
                try:
                    self._xs.get(url, timeout=self.BASE_TIMEOUT)
                except Exception:                        # noqa: BLE001
                    pass
        return self._xs

    def _xq_get(self, path: str, params: dict) -> dict:
        """雪球 /v5 系列统一入口: 指纹会话 + Referer + 代码归一 + 状态码转信封。

        `symbol` / `symbols` 在这里归一 (`_symbol.xueqiu`), 是 27 个雪球方法的
        唯一收口点。雪球对前缀大小写敏感, 小写命中 CDN 旧缓存返回**过期价格**
        (HTTP 200 + 合法 JSON, 信封照样 ok=True), 所以必须在入口拦住。
        """
        if params:
            if 'symbol' in params:
                params = dict(params, symbol=_symbol.xueqiu(params['symbol']))
            if 'symbols' in params:
                params = dict(params, symbols=_symbol.join_xq(params['symbols']))
        try:
            r = self._xueqiu_session().get(
                f'https://stock.xueqiu.com{path}',
                params=params,
                headers={'Referer': 'https://xueqiu.com/hq'},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f'status={r.status_code}', r.status_code)
            data = r.json().get('data')
            return _ok(data, len(r.text))
        except Exception as e:                            # noqa: BLE001
            return _err(f'{type(e).__name__}: {e}')