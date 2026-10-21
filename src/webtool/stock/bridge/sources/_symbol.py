"""代码归一 —— 各数据源要求不同的 symbol 形态, 统一在这里收口

## 为什么需要这一层

三个源对同一个 A 股代码要的写法完全不同, 且**传错不报错**:

| 源 | 要的形态 | 传错的后果 |
|---|---|---|
| 雪球 | `SH600519` | `sh600519` → `ok=True` 但返回**过期缓存** (ts 差 4 天, 价格 1263 vs 1274) |
| 新浪 | `sh600519` | `SH600519` → `ok=True` 但字段全空 (`fields=['']`) |
| 腾讯 | `sh600519` | `SH600519` → `ok=True` 但 `pv_none_match` |

三个都是 HTTP 200 + 合法 JSON, 信封照样 `ok=True`。雪球那条最毒: 拿到的是
**另一天的价格**, 下游算涨跌幅/均线全部算错, 而且没有任何信号表明数据不对。

调用方有 150+ 个方法、四种写法混着 (`sh688825` / `SH600519` / `688825` /
`600519.SH`), 靠"每个调用方自己记得传对"是假的 —— 归一必须在一个地方做。

所以归一放在**源入口**: 调用方传什么形态都能吃, 源自己转成需要的形态。

## 设计原则: 只在"能确定"时改写

`rt_hk01810` / `s_sz000001` / `usTSLA` / `jj000001` / `hkHSI` / `us.DJI` /
`sh000300` 这些是各站的专有 prefix, 不在归一范围内 —— **原样透传**。
只有能被解析成 (市场, 6 位数字) 的才改写, 解析不了的一律不动。

宁可放过, 不可改错: 猜错市场前缀会把一只票打到另一只票上。

## 裸 6 位代码的市场推断

无前缀时按首位推断, 与本仓既有口径一致:
`6/5/9` → 沪, `4/8` → 北, 其余 → 深。

例外: `92xxxx` 是北交所新代码段, 但首位 `9` 会判成沪 —— 单独处理。

**指数是已知歧义**: `000001` 默认判成深 (平安银行), 而上证指数也是
`000001`; `399001` 判成深 (深证成指) 恰好正确。裸指数代码无法区分,
调用方须显式传 `sh000001` / `sz399001`。
"""
from __future__ import annotations

import re

# 显式前缀 (大小写不敏感), 与后缀 `.SH` 两种写法等价
_PREFIXED = re.compile(r'^(SH|SZ|BJ)(\d{4,6})$', re.I)
_DOTTED = re.compile(r'^(\d{4,6})\.(SH|SZ|BJ)$', re.I)
# 裸代码只认 6 位: A 股 / 场内基金 / 债券 (510300, 019547) 都是 6 位。
# 放宽到 4-5 位会把港股 (`00700`) 误判成深市 —— 5 位数字在 A 股不存在。
_BARE = re.compile(r'^\d{6}$')

def market_of(code: str) -> str | None:
    """裸代码 → 市场 ('SH'/'SZ'/'BJ'), 非裸代码返回 None。"""
    c = str(code).strip()
    if not _BARE.match(c):
        return None
    if c.startswith('92'):          # 北交所新代码段 (92xxxx), 首位 9 会误判沪
        return 'BJ'
    head = c[0]
    if head in '659':
        return 'SH'
    if head in '48':
        return 'BJ'
    return 'SZ'

def parse(code: str) -> tuple[str, str] | None:
    """任意常见写法 → (市场, 数字部分); 不是 A 股代码则 None。

    认: `600519` / `sh600519` / `SH600519` / `600519.SH` / `600519.sh`
    不认 (返回 None, 调用方原样透传): `rt_hk01810` / `s_sz000001` /
    `usTSLA` / `jj000001` / `hkHSI` / `us.DJI`
    """
    c = str(code).strip()
    m = _PREFIXED.match(c)
    if m:
        return m.group(1).upper(), m.group(2)
    m = _DOTTED.match(c)
    if m:
        return m.group(2).upper(), m.group(1)
    mk = market_of(c)
    return (mk, c) if mk else None

# ── 各源要的形态 ────────────────────────────────────────────────────

def xueqiu(code: str) -> str:
    """雪球: `SH600519` / `SZ000001` / `BJ430047` / `HK00700`

    大小写敏感 —— 小写前缀命中的是雪球 CDN 的旧缓存, 返回过期价格。

    港股走 `HK00700`。美股**不在这里处理**: 雪球要裸 ticker (`TSLA`), 加
    `us` 前缀 (`usTSLA`) 反而查不到 (返回空), 而"裸字母"与雪球的指数
    写法 (`us.DJI`) 同形, 通用正则会把 `us.DJI` 误改成 `US.DJI`。所以美股由
    调用方给裸 ticker, 这里只管前缀确定的情况。
    """
    c = str(code).strip()
    p = parse(c)
    if p:
        return f'{p[0]}{p[1]}'
    m = re.fullmatch(r'(?:hk|HK)?(\d{4,5})', c)
    if m:
        return f'HK{m.group(1).zfill(5)}'
    return c

def sina(code: str) -> str:
    """新浪: `sh600519` / `sz000001` / `bj430047` (小写前缀)"""
    p = parse(code)
    return f'{p[0].lower()}{p[1]}' if p else str(code).strip()

def tencent(code: str) -> str:
    """腾讯 qt.gtimg.cn / web.ifzq: `sh600519` (小写前缀)"""
    return sina(code)

def em(code: str) -> str:
    """东财 emweb F10: 裸 `600519` (不带市场前缀)"""
    p = parse(code)
    return p[1] if p else str(code).strip()

def em_secid(code: str) -> str:
    """东财 push2: `1.600519` (1=沪 0=深) —— 非 A 股原样透传

    板块 (行业/概念, 东财编号 `BKxxxx`) 归 `90.` 市场 —— K 线、分时同一条
    secid 通道; 传 '半导体' 这类中文名走不到这里 (在编排层先换成 BK 代码)。
    """
    p = parse(code)
    if not p:
        c = str(code).strip().upper()
        if re.fullmatch(r'BK\d{4}', c):
            return f'90.{c}'
        return str(code).strip()
    return f'1.{p[1]}' if p[0] == 'SH' else f'0.{p[1]}'

def em_secucode(code: str) -> str:
    """东财 datacenter: `600519.SH` (数字在前, 后缀是市场)"""
    p = parse(code)
    return f'{p[1]}.{p[0]}' if p else str(code).strip()

def em_market(code: str) -> str:
    """东财 push2 单字母市场码: `1`=沪 `0`=深/北 (取数字部分即可判)"""
    p = parse(code)
    if not p:
        return '0'
    return '1' if p[0] == 'SH' else '0'

def split_many(codes) -> list[str]:
    """逗号分隔批量 → 逐个归一 (非字符串原样返回列表)"""
    if isinstance(codes, (list, tuple)):
        return [xueqiu(c) for c in codes]
    return [xueqiu(x) for x in str(codes).split(',') if x.strip()]

def join_xq(codes) -> str:
    """雪球批量: 逗号分隔的 symbol 串 → 逐个归一后仍以逗号连接"""
    if isinstance(codes, (list, tuple)):
        return ','.join(xueqiu(c) for c in codes)
    return ','.join(xueqiu(x) for x in str(codes).split(',') if x.strip())

def join(codes, form=xueqiu) -> str:
    """任意源的批量形态 —— `form` 取本模块的逐个归一函数"""
    if isinstance(codes, (list, tuple)):
        return ','.join(form(c) for c in codes)
    return ','.join(form(x) for x in str(codes).split(',') if x.strip())