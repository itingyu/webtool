"""
engine 共享层 —— 纯口径工具
==========================
只放**不取数**的共用件：日志、代码归一转发、外链拼装、不可买板块判定、TTL 缓存。

传输层（session / curl_cffi 指纹 / 同花顺 v token）全在 `bridge/sources/_base.py`
—— 本模块曾经自带一套 qjs + 三个 session，与数据源层重复，已删：取数只有
`sources` 一处实现，这里再留一份只会漂。

代码归一的唯一事实来源是 `bridge/sources/_symbol.py`，本模块只做转发，
不重写规则（历史上这里与 short_tool / clients 各有一份前缀表，920xxx 的归属
三处不一致，打错过 symbol）。
"""
from datetime import datetime
import sys
import warnings

warnings.filterwarnings("ignore")

from webtool.stock.bridge.sources import _symbol


def log(msg, level="INFO"):
    """统一日志（输出到 stderr，不污染 stdout JSON）"""
    print(f"[{level}] {datetime.now().strftime('%H:%M:%S')} {msg}", file=sys.stderr)


# ============================================================
#  代码归一（转发 sources/_symbol，不重写规则）
# ============================================================
def _zfill6(code):
    """补足 6 位 —— 兼容 '2414' 这类简写输入

    **带显式前缀/后缀的不动**：`sh000001` 是上证指数，剥掉前缀补零会变成
    深市平安银行；那类形态交给 `_symbol.parse` 自己判。`_symbol` 对 4-5 位
    数字的判定是"港股"（雪球那边 00700 就是港股），所以补零必须在转发之前做。
    """
    c = str(code).strip().upper()
    if c[:2] in ("SH", "SZ", "BJ") and c[2:].isdigit():
        return c
    return c.zfill(6) if c.isdigit() else c


def to_xueqiu_symbol(code):
    """A 股代码 → 雪球 symbol: 600519 → SH600519, 920178 → BJ920178"""
    return _symbol.xueqiu(_zfill6(code))


def to_sina_symbol(code):
    """A 股代码 → 新浪 symbol: 600519 → sh600519, 920178 → bj920178"""
    return _symbol.sina(_zfill6(code))


def market_of(code):
    """6 位 A 股代码 → 市场前缀 'SH'/'SZ'/'BJ'（规则见 sources/_symbol.py）

    Examples:
        >>> market_of('600519')
        'SH'
        >>> market_of('002414')
        'SZ'
        >>> market_of('920001')
        'BJ'
        >>> market_of('sz002414')
        'SZ'
        >>> market_of('2414')
        'SZ'
    """
    p = _symbol.parse(_zfill6(code))
    return p[0] if p else "SH"


def stock_links(code):
    """生成 7 个数据源链接 dict（统一由脚本生成，模板/agent 不应自行拼接）

    Returns:
        dict，键名固定，值是已拼好的完整 URL:
          eastmoney_quote / eastmoney_f10 / eastmoney_flow / eastmoney_notice /
          xueqiu / ths / sina

    实测状态（2026-08-09，浏览器 GET 实测）：
      - eastmoney_* ✅   HTTP 200 + title/DOM 正常
      - xueqiu      ✅   SPA，浏览器渲染后含完整内容
      - ths         ✅   需用 mobile UA（desktop UA HEAD 返回 403，不影响 GET）
      - sina        ✅   原 URL 自动跳转 m 站，HTTP 200

    边界：北交所个股（920/830 等）`eastmoney_quote` 返回 404（东财无北交所
    个股页），其余 6 个链接正常。

    弃用：~~cninfo 主站个股页~~（被劫持到 webchat.cninfo.com.cn）、
    ~~basic.10jqka.com.cn/{code}.html~~（SPA 客户端不把数据写进 DOM）。

    Examples:
        >>> from webtool.stock.engine._common import stock_links
        >>> stock_links('002414')['eastmoney_quote']
        'https://quote.eastmoney.com/sz002414.html'
        >>> stock_links('920001')['xueqiu']
        'https://xueqiu.com/S/BJ920001'
        >>> stock_links('sz002414')['sina']            # 输入容错：剥前缀 / 补 0
        'https://finance.sina.com.cn/realstock/company/sz002414/nc.shtml'
    """
    code = _zfill6(code)
    market_upper = market_of(code)        # 雪球显示用大写
    market_lower = market_upper.lower()   # 东财/新浪均接受小写前缀
    return {
        "eastmoney_quote":  f"https://quote.eastmoney.com/{market_lower}{code}.html",
        "eastmoney_f10":    f"https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/Index?type=web&code={market_lower}{code}",
        "eastmoney_flow":   f"https://data.eastmoney.com/zjlx/detail/{code}.html",
        "eastmoney_notice": f"https://data.eastmoney.com/notices/stock/{code}.html",
        "xueqiu":           f"https://xueqiu.com/S/{market_upper}{code}",
        "ths":              f"https://m.10jqka.com.cn/stockpage/hs_{code}/",
        "sina":             f"https://finance.sina.com.cn/realstock/company/{market_lower}{code}/nc.shtml",
    }


# ============================================================
#  不可买板块（全局唯一口径）
#  short_tool / clients / screening / analysis 一律调用本函数，
#  禁止各自复制一份判断逻辑。
# ============================================================
_BLOCK_PREFIX = {
    "300": "创业板", "301": "创业板",
    "688": "科创板", "689": "科创板",
    "8": "北交所", "920": "北交所", "430": "北交所",
    "83": "北交所", "87": "北交所", "88": "北交所",
    "900": "沪市B股", "200": "深市B股",
}
_MAIN_PREFIX = ("600", "601", "603", "605", "000", "001", "002", "003")


def unbuyable_reason(code, name=None):
    """不可买板块判定：不可买返回原因字符串，可买返回 None

    Args:
        code: 6 位代码（接受 '600519' / 'sh600519' / '519'）
        name: 股票名称，用于识别 ST / 退市整理

    Returns:
        None（可买）或原因字符串（不可买）

    Examples:
        >>> unbuyable_reason('600121') is None
        True
        >>> unbuyable_reason('300913')
        '创业板 300 不可买'
        >>> unbuyable_reason('600519', 'ST茅台')
        'ST / 退市整理'
        >>> unbuyable_reason('920178')          # 北交所新代码段，必须先判
        '北交所 920 不可买'
    """
    c = _zfill6(code)
    if not c.isdigit():
        return "非数字代码"
    nm = str(name or "").upper()
    if "ST" in nm or "退" in nm:
        return "ST / 退市整理"
    for p in sorted(_BLOCK_PREFIX, key=len, reverse=True):
        if c.startswith(p):
            return f"{_BLOCK_PREFIX[p]} {p} 不可买"
    if c.startswith(_MAIN_PREFIX):
        return None
    return "未知前缀，默认排除"


def is_tradable(code, name=None):
    """是否可买（不可买板块规则的单点入口）"""
    return unbuyable_reason(code, name) is None


def cache_ttl(ttl_seconds=300):
    """带 TTL 的进程内缓存装饰器（防限流；返回 None / 空值时不缓存）"""
    import functools
    import time as _time

    def deco(fn):
        store = {}

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            now = _time.time()
            hit = store.get(key)
            if hit and now - hit[0] < ttl_seconds:
                return hit[1]
            val = fn(*args, **kwargs)
            if val:                      # 空结果不缓存，避免把「限流」当成「无数据」
                store[key] = (now, val)
            return val

        wrapper.cache_clear = store.clear
        return wrapper

    return deco
