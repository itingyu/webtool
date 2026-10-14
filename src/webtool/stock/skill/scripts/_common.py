"""
stock-master 共享层
==================
所有 fetcher / analysis 共用的：
  - 雪球 session（curl_cffi + warmup）
  - 同花顺 session（qjs 算 v token）
  - stdlib requests session
  - 日志、错误兜底
"""
import sys
import subprocess
import re
import glob
import warnings
from datetime import datetime

warnings.filterwarnings("ignore")

try:
    import requests as std_requests
    from curl_cffi import requests as cffi_requests
except ImportError as e:
    print(f"[FATAL] 缺依赖: {e}", file=sys.stderr)
    sys.exit(1)


def _find_ths_js():
    """定位 akshare 的 ths.js（不写死 python 版本号）"""
    pats = [
        "/usr/lib/python3*/site-packages/akshare/data/ths.js",
        "/usr/lib/python3*/site-packages/akshare/data/ths.js",
        "/usr/local/lib/python3*/site-packages/akshare/data/ths.js",
    ]
    for p in pats:
        hit = sorted(glob.glob(p))
        if hit:
            return hit[-1]
    # 兜底：按当前解释器路径推导
    for sp in sys.path:
        p = f"{sp}/akshare/data/ths.js"
        if glob.glob(p):
            return p
    return None


THS_JS = _find_ths_js()


def log(msg, level="INFO"):
    """统一日志（输出到 stderr，不污染 stdout JSON）"""
    print(f"[{level}] {datetime.now().strftime('%H:%M:%S')} {msg}", file=sys.stderr)


def get_v_token():
    """用 qjs 跑 akshare 的 ths.js, 提取 60 字符 v token"""
    try:
        script = f'{open(THS_JS).read()}\nconsole.log(JSON.stringify(v()));'
        r = subprocess.run(["qjs", "-e", script],
                           capture_output=True, text=True, timeout=8)
        m = re.search(r'"([A-Za-z0-9_-]{20,80})"', r.stdout)
        return m.group(1) if m else None
    except Exception as e:
        log(f"qjs v token 计算失败: {e}", level="WARN")
        return None


# ============================================================
#  Session 单例（避免重复 warmup）
# ============================================================
_XQ_SESSION = None
_THS_SESSION = None
_STD_SESSION = None


def std_session():
    """stdlib requests（东财 / 巨潮 / 新浪 / 百度 / 腾讯）"""
    global _STD_SESSION
    if _STD_SESSION is None:
        _STD_SESSION = std_requests.Session()
    return _STD_SESSION


def xq_session():
    """雪球：curl_cffi Chrome110 + 3 页 warmup"""
    global _XQ_SESSION
    if _XQ_SESSION is None:
        s = cffi_requests.Session(impersonate="chrome110")
        for url in ["https://xueqiu.com/", "https://xueqiu.com/hq", "https://xueqiu.com/S/SH600519"]:
            try:
                s.get(url, timeout=6)
            except Exception:
                pass
        _XQ_SESSION = s
    return _XQ_SESSION


def ths_session():
    """同花顺：qjs 算 v token + 设 cookie"""
    global _THS_SESSION
    if _THS_SESSION is None:
        s = std_requests.Session()
        s.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        try:
            s.get("http://q.10jqka.com.cn/", timeout=6)
        except Exception:
            pass
        token = get_v_token()
        if token:
            s.cookies.set("v", token, domain=".10jqka.com.cn")
        _THS_SESSION = s
    return _THS_SESSION


# ============================================================
#  工具函数
# ============================================================
def to_xueqiu_symbol(code):
    """A 股代码 → 雪球 symbol: 600519 → SH600519, 920178 → BJ920178

    代码段规则:
      - 6xxxxx / 9xxxxx(非920) → 上交所主板（含 900/901/903 等 B 股）
      - 688xxx → 科创板
      - 5xxxxx → 上交所基金/ETF（仍归 SH）
      - 920xxx / 430xxx / 8xxxxx / 87xxxx / 88xxxx → 北交所
      - 0xxxxx / 3xxxxx → 深交所主板 / 创业板
    """
    code = code.strip().upper()
    if code.startswith(("SH", "SZ", "BJ")):
        return code
    # 北交所：必须先判（920/430/8 开头），否则会被下面的 9/5 误归 SH
    if code.startswith(("920", "430", "83", "87", "88")):
        return "BJ" + code
    # 上交所主板/科创板/B股/基金
    if code.startswith(("60", "68", "9", "5")):
        return "SH" + code
    # 深交所主板/创业板
    return "SZ" + code


def to_sina_symbol(code):
    """A 股代码 → 新浪 symbol: 600519 → sh600519, 920178 → bj920178"""
    code = code.strip().lower()
    if code.startswith(("sh", "sz", "bj")):
        return code
    if code.startswith(("920", "430", "83", "87", "88")):
        return "bj" + code
    if code.startswith(("60", "68", "9", "5")):
        return "sh" + code
    return "sz" + code


def market_of(code):
    """6 位 A 股代码 → 市场前缀 'SH'/'SZ'/'BJ'

    代码段规则与 to_xueqiu_symbol / to_sina_symbol 保持一致：
      - 北交所（920/430/83/87/88 开头）→ BJ
      - 上交所主板/科创板/B 股/基金（60/68/9/5 开头）→ SH
      - 深交所主板/创业板（00/30 开头）→ SZ

    Args:
        code: 6 位 A 股代码；自动 zfill(6) 兼容 '2414' / '002414' / 'SZ002414'
              接受 'SH' / 'SZ' / 'BJ' 前缀（自动剥离）

    Returns:
        大写市场前缀字符串 'SH' / 'SZ' / 'BJ'。需要小写时调用方自己 .lower()。
        未知代码段兜底返回 'SH'。

    Examples:
        >>> market_of('600519')
        'SH'
        >>> market_of('002414')
        'SZ'
        >>> market_of('920001')
        'BJ'
        >>> market_of('sz002414')   # 自动剥离前缀
        'SZ'
        >>> market_of('2414')       # 自动补 0
        'SZ'
    """
    code = str(code).strip().upper()
    if code.startswith(("SH", "SZ", "BJ")):
        code = code[2:]
    code = code.zfill(6)
    # 北交所必须先判，否则 9 开头会被误归 SH
    if code.startswith(("920", "430", "83", "87", "88")):
        return "BJ"
    if code.startswith(("600", "601", "603", "605", "688", "689", "9", "5")):
        return "SH"
    if code.startswith(("000", "002", "003", "300", "301")):
        return "SZ"
    return "SH"  # 兜底


def stock_links(code):
    """生成 7 个数据源链接 dict（统一由脚本生成，模板/agent 不应自行拼接）

    Args:
        code: 6 位 A 股代码；接受任意能被 market_of() 识别的格式
              （'002414' / 'sz002414' / '2414' 都可以）

    Returns:
        dict，键名固定，值是已拼好的完整 URL:
          - eastmoney_quote : 东财个股行情页
          - eastmoney_f10   : 东财 F10 资料
          - eastmoney_flow  : 东财资金流向
          - eastmoney_notice: 东财公告聚合（替代已失效的巨潮主站入口）
          - xueqiu          : 雪球个股页
          - ths             : 同花顺个股页（**手机版**；电脑版 basic.10jqka.com.cn 是 SPA 空壳）
          - sina            : 新浪财经

    实测状态（2026-08-09，浏览器 GET 实测）：
      - eastmoney_* ✅  HTTP 200 + title/DOM 正常
      - xueqiu      ✅  SPA，浏览器渲染后含完整内容
      - ths         ✅  需用 mobile UA；desktop UA HEAD 返回 403（反爬，不影响 GET）
      - sina        ✅  原 URL 自动跳转 m 站，HTTP 200

    边界情况：
      - 北交所个股（920/830 等）：`eastmoney_quote` 返回 404（东财无北交所个股页），
        其他 6 个链接正常

    弃用：
      - ~~www.cninfo.com.cn/new/disclosure/stock?stockCode=...~~ 浏览器被劫持到 webchat.cninfo.com.cn
      - ~~basic.10jqka.com.cn/{code}.html~~ SPA 客户端未把数据写到 DOM
      - 巨潮公告 PDF 仍用 static.cninfo.com.cn/finalpage/...（API 返回，curl/浏览器 PDF 均正常）

    Examples:
        >>> from webtool.stock.skill.scripts._common import stock_links
        >>> links = stock_links('002414')
        >>> links['eastmoney_quote']
        'https://quote.eastmoney.com/sz002414.html'
        >>> links['xueqiu']
        'https://xueqiu.com/S/SZ002414'
        >>> links['ths']
        'https://m.10jqka.com.cn/stockpage/hs_002414/'

        >>> # 北交所（注意 eastmoney_quote 该 URL 在浏览器返回 404，东财无北交所个股页）
        >>> stock_links('920001')['eastmoney_quote']
        'https://quote.eastmoney.com/bj920001.html'
        >>> stock_links('920001')['xueqiu']
        'https://xueqiu.com/S/BJ920001'

        >>> # 输入容错：自动剥离前缀 / 自动补 0
        >>> stock_links('sz002414')['eastmoney_quote']
        'https://quote.eastmoney.com/sz002414.html'
        >>> stock_links('2414')['eastmoney_quote']
        'https://quote.eastmoney.com/sz002414.html'

        >>> # 在 single_analysis.analyze() 返回 dict 里直接读 r['links']
        >>> # r = single_analysis.analyze('002414')
        >>> # r['links']['eastmoney_notice']
        >>> # 'https://data.eastmoney.com/notices/stock/002414.html'
    """
    code = str(code).strip().upper()
    if code.startswith(("SH", "SZ", "BJ")):
        code = code[2:]
    code = code.zfill(6)
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
#  规则来源：references/data/board-rules.md
#  short_pool / short_tool / single_analysis 一律调用本函数，
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
        >>> unbuyable_reason('600121')
        >>> unbuyable_reason('300913')
        '创业板 300 不可买'
        >>> unbuyable_reason('600519', 'ST茅台')
        'ST / 退市整理'
    """
    c = str(code).strip().upper()
    if c.startswith(("SH", "SZ", "BJ")):
        c = c[2:]
    c = c.zfill(6)
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
