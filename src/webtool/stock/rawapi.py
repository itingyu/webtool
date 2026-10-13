"""桥接 api_client.APIClient 的 151 个低阶方法

`/var/minis/shared/股票/API调研/api_client.py` 是本次股票能力的**数据底座**:
雪球/同花顺/东财/新浪/巨潮/百度/腾讯/中证 8 大源、26 个 HTTP endpoint 与 5 个
efinance 函数的统一封装, 每源自带 fallback 链与重试。

stock 服务端只把其中一部分聚合成 24 个高阶工具给 Agent 用; 剩下的低阶方法
(股东研究、盈利预测、财务分析、研报日历、早盘晚报、板块多维排行、分钟线、
产业链分类……) 仍然有价值, 通过本模块按需直接调用。

## 分工

- 高阶、已聚合的能力 → 走 `stock/srv.py` (服务端 24 工具)
- 低阶、没被聚合的     → 走本模块 (151 方法全量可调)

## 两个维度

151 个方法有两套索引, 各回答一个问题:

| 维度 | API | 回答 |
|---|---|---|
| 数据源 | `methods_by_source()` | 哪个站 (ths_/sina_/xueqiu_/em_/gtimg_/cninfo_/...) |
| **功能** | `methods_by_function()` | **要干什么** (行情/K线/财报/股东/板块/资金/公告/指数/新股) |

功能维度是使用方真正需要的: "查个股财报用哪个方法" 才是问题, "哪个站能用"
不是。分类表是数据 (data/api_categories.json), 加载时与实际方法对账 ——
加了方法没加分类会落到 uncategorized 而不是静默消失。

`webtool stock api <方法> --arg K=V` 是通用入口, 服务端未覆盖的能力都能调;
高频的几个另加了专门动作 (holder/forecast 等), 免记方法名。

⚠️ 返回形状与 stock 服务端一致: `{"ok":bool, "data":..., "error":...}`,
失败抛 RawApiError 由上层转成退出码 1, 不静默返回空。
"""
import importlib
import inspect
import json
import os
import sys

HOME = os.environ.get('STOCK_API_HOME', '/var/minis/shared/股票/API调研')
CLIENT_MOD = 'api_client'

_client = None


class RawApiError(RuntimeError):
    """api_client 不可用 / 方法不存在 / 调用失败"""


def client():
    """进程内拿 APIClient 单例 (它内部有 lru_cache 的 token/session, 复用才对)。

    延迟 import + 缓存: 放在模块级会让 webtool 所有命令都依赖这个路径存在,
    而它缺失只该让 stock 的 raw 动作退 2。
    """
    global _client
    if _client is not None:
        return _client
    if HOME not in sys.path:
        sys.path.insert(0, HOME)
    try:
        mod = importlib.import_module(CLIENT_MOD)
    except ImportError as e:
        raise RawApiError(f'api_client 导入失败: {e} (STOCK_API_HOME 可覆盖路径)') from e
    try:
        _client = mod.APIClient()
    except Exception as e:                                  # noqa: BLE001
        raise RawApiError(f'APIClient 初始化失败: {type(e).__name__}: {e}') from e
    return _client


def available():
    try:
        return bool(methods())
    except RawApiError:
        return False


def methods():
    """全部可调用方法名 (排除 dunder 与 test_all —— 那是全量自检, 太慢且不该从 CLI 触发)"""
    c = client()
    return sorted(m for m in dir(c)
                  if not m.startswith('_')
                  and callable(getattr(c, m))
                  and m not in ('test_all', 'run', 'close'))


def methods_by_source():
    """按数据源前缀分组 (ths_/sina_/xueqiu_/em_/gtimg_/cninfo_/...)

    数据源维度回答"哪个站", 但对使用方没用 —— 没人知道该用哪个站, 只知道
    "我要查财报"。功能维度见 categories() / methods_by_function()。
    """
    out = {}
    for m in methods():
        out.setdefault(m.split('_')[0], []).append(m)
    return {k: sorted(v) for k, v in sorted(out.items())}


# ---------- 功能维度分类 ----------

_CATS = None


def categories():
    """功能分类表 (code -> label/desc/primary/fallback), 带缓存。

    分类表是数据不是逻辑 (data/api_categories.json), 且必须与 methods() 对得上
    —— 加载时校验, 对不上的方法走 uncategorized 而不是静默消失, 否则加方法
    忘了加分类就悄无声息地从清单里没了。
    """
    global _CATS
    if _CATS is not None:
        return _CATS
    p = os.path.join(os.path.dirname(__file__), 'data', 'api_categories.json')
    try:
        with open(p, encoding='utf-8') as f:
            raw = json.load(f)['categories']
    except (OSError, ValueError, KeyError) as e:
        raise RawApiError(f'功能分类表读取失败: {e} ({p})') from e
    try:
        real = set(methods())
    except RawApiError:
        raise
    listed, known = {}, set()
    for code, c in raw.items():
        prim = list(c.get('primary') or [])
        fb = list(c.get('fallback') or [])
        listed[code] = {'code': code, 'label': c.get('label') or code,
                        'desc': c.get('desc') or '',
                        'alias': list(c.get('alias') or []),
                        'primary': prim, 'fallback': fb}
        known |= set(prim) | set(fb)
    orphan = sorted(real - known)                   # 加了方法忘了加分类
    ghost = sorted(known - real)                   # 删了方法分类表没跟
    if orphan:
        listed['uncategorized'] = {
            'code': 'uncategorized', 'label': '未分类',
            'desc': '已实现但未登记功能分类的方法 (分类表需同步更新)',
            'alias': [], 'primary': orphan, 'fallback': []}
    for m in ghost:
        for c in listed.values():
            c['primary'] = [x for x in c['primary'] if x != m]
            c['fallback'] = [x for x in c['fallback'] if x != m]
    _CATS = listed
    return _CATS


def methods_by_function(code=None):
    """按功能分组, 可选只看某一类。

    code 为空返回全部 (按 primary 数量降序, 常用的排前面); 给了 code 返回单类,
    找不到就报错并列出可用的类 —— 不静默返回空, 否则调用方以为"没这类接口"。
    """
    cats = categories()
    if code:
        c = cats.get(code) or by_alias(cats, code)
        if c is None:
            raise RawApiError(
                f'未知功能类: {code} (可用: {", ".join(sorted(cats))})')
        return {c['label']: _one(c)}
    order = sorted(cats, key=lambda k: (-len(cats[k]['primary']), cats[k]['label']))
    return {cats[k]['label']: _one(cats[k]) for k in order}


def _one(c):
    return {'code': c['code'], 'label': c['label'], 'desc': c['desc'],
            'alias': c['alias'], 'primary': c['primary'], 'fallback': c['fallback']}


def by_alias(cats, kw):
    """按别名/标签/类码精确命中一类, 命中返回该类 dict, 否则 None。

    口语说法 ("财报"/"利润表"/"十大股东") 必须优先于模糊子串匹配 —— 否则
    "财报" 会因为公告资讯的 desc 里写了 "财报日历" 而先命中错的那一类,
    而用户想要的是财务报表。给 api-search 用。
    """
    kw = kw.lower()
    for c in cats.values():
        if c['code'].lower() == kw or c['label'].lower() == kw:
            return c
        if any(a.lower() == kw for a in c['alias']):
            return c
    return None


def category_of(method):
    """一个方法属于哪一类 (跨类的给第一个; 不在表里返回 None)"""
    for code, c in categories().items():
        if code == 'uncategorized':
            continue
        if method in c['primary'] or method in c['fallback']:
            return code
    return None


def method_doc(method):
    """方法的签名 + docstring 首行 —— api/search 按功能找接口时一并给出, 省一次 --method 试错"""
    fn = getattr(client(), method, None)
    if fn is None or not callable(fn):
        return None
    try:
        sig = str(inspect.signature(fn))
    except (TypeError, ValueError):
        sig = '(?)'
    doc = (inspect.getdoc(fn) or '').strip().splitlines()
    return {'sig': sig, 'doc': doc[0] if doc else ''}



def call(method, kwargs=None):
    """调一个 api_client 方法。参数按签名校验, 不做隐式转换。"""
    c = client()
    fn = getattr(c, method, None)
    if fn is None or method.startswith('_') or not callable(fn):
        raise RawApiError(f'未知方法: {method} (webtool stock api-list 看全部)')
    params = dict(kwargs or {})
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        sig = None
    if sig is not None:
        unknown = set(params) - set(sig.parameters)
        if unknown:
            # 签名不匹配时明确报错, 不把多余参数静默吞掉 —— 吞掉等于让调用方
            # 以为参数生效了, 实际跑的是默认值。
            raise RawApiError(f'{method} 不接受参数: {", ".join(sorted(unknown))} '
                              f'(可用: {", ".join(p for p in sig.parameters if p != "self") or "无"})')
    try:
        return fn(**params)
    except Exception as e:                                  # noqa: BLE001
        raise RawApiError(f'{method} 调用失败: {type(e).__name__}: {e}') from e