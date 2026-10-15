"""桥接环境里的第三方金融数据生态库 (akshare / tushare / baostock / efinance)

`shared/股票/API调研/函数.json` 是这几个库的接口调研底稿。它们覆盖数据源层
没有的领域 (宏观/另类数据/期货/基金/外汇 等), 接口数比数据源层的 157 个方法
大一个量级:

- **akshare** (1137 导出): 最全 —— 龙虎榜/板块资金/宏观/商品/可转债/基金/
  期货/期权/全球市场, 几乎所有 A 股细分数据都能在这儿找到
- **tushare** (134): 需要 token 的专业数据 (研报盈利预测、股东数、限售解禁…),
  token 在环境变量里, 没配就明说而不是静默失败
- **baostock** (38): 免费的日/周/线历史数据与财务数据
- **efinance**: 与数据源层内部用的同一套

## 与前两层的分工

| 层 | 覆盖 | 特点 |
|---|---|---|
| `srv.py` (服务端 24 工具) | 高阶聚合 | 口径统一、有 fallback 链 |
| `rawapi.py` (数据源层 154) | 按源分包 | 每次调用都现取, 无重试 |
| **本模块** (生态库 ~1300) | 长尾 + 宏观 + 全球 | **有重试与限流**, 返回 DataFrame 摘要 |

## 性能与限流纪律 ⚠️

生态库接口的耗时跨度极大 (0.5s ~ 100s+), 且无内置限流。规矩:

1. **慢接口必须显式警告** —— `stock_zh_a_spot_em` 这类全市场快照要 70s+, 文档与
   `_slow_hints` 都要标出来, 不能让调用方盲等后以为卡死
2. **默认超时 120s** (`timeout=`), 超时抛 `EcoError` 而不是挂着
3. **不做并发** —— 这些库多数没做并发保护, 并发调用等于自己制造限流。
   批量场景靠调用方串行 + `sleep` 控制, 本模块不代劳
4. **返回 DataFrame 摘要而非全量** —— 动辄几千行的表倾倒出来没法看。
   给 shape / 列名 / 前 N 行预览, 要全量用 `-f json --preview-rows N`
"""
import importlib
import inspect
import os
import sys
import time
from webtool.stock.error import EcoError
from webtool.stock.bridge import _eco_net

TIMEOUT = float(os.environ.get('STOCK_ECO_TIMEOUT', '120'))

# 全市场快照类接口, 单次 60s+, 文档与警告都要用
_SLOW_HINTS = {
    'stock_zh_a_spot_em': '全市场 5000+ 快照, 约 70s',
    'stock_zh_a_spot': '全市场快照, 约 60s',
    'stock_board_industry_name_em': '行业板块全量, 约 20s',
    'stock_board_concept_name_em': '概念板块全量, 约 20s',
    'stock_lhb_detail_em': '龙虎榜明细全量, 约 30s',
    'fund_etf_spot_em': 'ETF 全市场, 约 60s',
    'stock_hsgt_fund_flow_summary_em': '沪深港通资金流全量, 约 20s',
    'option_current_em': '期权全市场, 约 40s',
    'futures_zh_spot': '期货快照全量, 约 30s',
}




def health():
    """各库可用性与可调接口数 (只数真函数, 不含类与常量)"""
    out = {}
    for lib in libs():
        m = _try_import(lib)
        if m is None:
            out[lib] = {'installed': False, 'funcs': 0}
            continue
        names, _ = _entries(lib, m)
        out[lib] = {'installed': True, 'funcs': len(names)}
    return out


def available():
    """至少一个库可用"""
    return any(v['installed'] for v in health().values())


def _entries(lib, m):
    """列出一个库的全部可调接口, 返回 (['stock.get_quote', ...], {名字: 函数})。

    归属判定用 `__module__` 的**包前缀**而不是精确等于包名: akshare 的函数定义
    在 `akshare.stock_feature.*` 下, 精确匹配会把 1099 个接口全判成"外来函数"
    误杀干净。

    顶层平铺的库 (akshare/tushare/baostock) 直接取模块属性; **子模块型的库**
    (efinance 0.5.x 只有 `efinance.stock` / `.fund` / `.bond` / `.futures`,
    顶层 0 个函数) 必须下钻子模块, 否则整条 `--lib efinance` 路是死的 ——
    名字统一带子模块前缀, 调用方拼回去即可。
    """
    names, fns = [], {}

    def own(obj):
        """是不是本库导出的**接口**: 排除类 (akshare 把 APIError 等异常类也导出了,
        当接口列出来只会误导) 与外部库函数; 但 lru_cache 包装的接口要保留 ——
        akshare 有 14 个 `@lru_cache` 接口是 `_lru_cache_wrapper`, 不是函数,
        用 inspect.isfunction 会把它们全丢掉。"""
        if inspect.isclass(obj):
            return False
        mod = getattr(obj, '__module__', '') or ''
        return mod == lib or mod.startswith(lib + '.')

    for x in dir(m):
        if x.startswith('_'):
            continue
        obj = getattr(m, x)
        if callable(obj) and own(obj):
            names.append(x)
            fns[x] = obj
    if names:
        return sorted(names), fns
    for sub in sorted(dir(m)):
        if sub.startswith('_'):
            continue
        sm = getattr(m, sub, None)
        if not inspect.ismodule(sm):
            continue
        for x in dir(sm):
            if x.startswith('_'):
                continue
            obj = getattr(sm, x, None)
            # eg efinance.stock.getter 的函数挂给 efinance.stock (前缀匹配)
            if (callable(obj) and not inspect.isclass(obj)
                    and (getattr(obj, '__module__', '') or '').startswith(f'{lib}.{sub}')):
                key = f'{sub}.{x}'
                names.append(key)
                fns[key] = obj
    return sorted(names), fns


def funcs(lib='akshare', skip=0, limit=0):
    """库里可调的接口名 (只取公开函数, 跳过类与常量; 子模块型带 `sub.` 前缀)"""
    m = require(lib)
    names, _ = _entries(lib, m)
    return names[skip:skip + limit] if limit else names[skip:]


def libs():
    return ('akshare', 'tushare', 'baostock', 'efinance')


def _lookup(lib, name):
    """在库里取函数。名字可带子模块前缀 (efinance 的 stock.get_quote)。"""
    m = require(lib)
    if '.' in name:
        mod, _, attr = name.rpartition('.')
        sm = getattr(m, mod, None)
        if sm is None:
            raise EcoError(f'{lib} 没有子模块 {mod} '
                           f'(webtool stock eco-list --lib {lib} 看可用接口)')
        fn = getattr(sm, attr, None)
    else:
        _, fns = _entries(lib, m)
        fn = fns.get(name)
    if fn is None or not callable(fn) or name.split('.')[-1].startswith('_'):
        raise EcoError(f'{lib} 里没有 {name} '
                       f'(webtool stock eco-search <关键词> 搜相关接口)')
    return fn


def _try_import(name):
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


def require(lib):
    """取一个库; 没装就抛带安装建议的错。tushare 额外要求 token"""
    m = _try_import(lib)
    if m is None:
        from webtool.core import deps
        hint = {'tushare': '需 token (环境变量 TUSHARE_TOKEN)',
                'baostock': '免费无需 token'}.get(lib, '')
        raise EcoError(f'{deps.install_hint(lib)} {hint}')
    if lib == 'tushare':
        tok = os.environ.get('TUSHARE_TOKEN')
        if not tok:
            # tushare 的接口全要 token, 没配就明说 —— 静默失败会让人以为是接口坏了
            raise EcoError('tushare 需要 TUSHARE_TOKEN 环境变量 (未配置)')
        try:
            m.set_token(tok)
            m.pro_api()          # 探测 token 有效性, 失败立刻报错而不是等到调接口
        except Exception as e:                              # noqa: BLE001
            raise EcoError(f'tushare token 无效: {type(e).__name__}: {str(e)[:80]}') from e
    return m


def search(keyword='', lib='', limit=0):
    """按关键词搜接口名 —— 这些库有上千个导出, 不可能都记住名字

    只搜公开函数: akshare 的 dir() 里混着 APIError/DataParsingError 这类异常类
    和常量, 把它们当"接口"报出来只会误导。中文关键词也支持 (库接口名是英文,
    但导出里有一部分带中文注释, 这里同时匹配文档首行)。
    """
    if not keyword:
        raise EcoError('需要关键词, 例: webtool stock eco-search 龙虎榜')
    out = {}
    for name in ((lib,) if lib else libs()):
        m = _try_import(name)
        if m is None:
            continue
        _, fns = _entries(name, m)
        hits = sorted(x for x, fn in fns.items() if _matches(x, fn, keyword))
        if hits:
            out[name] = hits[:limit] if limit else hits
    return out


def _matches(name, fn, keyword):
    kw = keyword.lower()
    if kw in name.lower():
        return True
    # 文档首行含关键词也算 (akshare 很多接口文档里直接写了"龙虎榜")
    doc = (inspect.getdoc(fn) or '').splitlines()
    return bool(doc) and kw in doc[0].lower()


def slow_hint(name):
    return _SLOW_HINTS.get(name)


def describe(name, lib=''):
    """接口名 + 签名 + 文档摘录 —— 调之前先看清参数, 免得试错"""
    for lb in ((lib,) if lib else libs()):
        m = _try_import(lb)
        if m is None:
            continue
        _, fns = _entries(lb, m)
        fn = fns.get(name)
        if fn is None:
            continue
        try:
            sig = str(inspect.signature(fn))
        except (TypeError, ValueError):
            sig = '(签名未知)'
        return {'lib': lb, 'name': name, 'signature': sig,
                'doc': (inspect.getdoc(fn) or '')[:400],
                'slow': slow_hint(name)}
    raise EcoError(f'{"该库里没有" if lib else "四个生态库里都没有"} {name} '
                   f'(webtool stock eco-search <关键词> 搜)')


def call(lib, name, kwargs=None, preview_rows=5, full=False):
    """调一个生态库接口, 返回摘要 (不是 DataFrame 本身)。

    DataFrame → {shape, columns, preview}; dict/list → 直接给 (截断到 preview_rows 量级)。
    """
    fn = _lookup(lib, name)
    t0 = time.time()
    try:
        # 生态库内部自带 session, 改不动; 作用域内让 requests 按规则表走,
        # 出了 with 自动还原, 不泄漏给同进程后续抓取
        with _eco_net.routed():
            df = fn(**(kwargs or {}))
    except TypeError as e:
        # 生态库函数的参数名极不一致 (symbol/code/symbols), 猜错就是 TypeError。
        # 直接把签名告诉调用方, 比让他猜参数名快得多。
        try:
            sig = str(inspect.signature(fn))
        except (TypeError, ValueError):
            sig = '(未知)'
        raise EcoError(f'{lib}.{name} 参数不匹配: {str(e)[:90]}\n  实际签名: {sig}') from e
    except Exception as e:                                  # noqa: BLE001
        raise EcoError(f'{lib}.{name} 调用失败: {type(e).__name__}: {str(e)[:120]}') from e

    took = round(time.time() - t0, 2)
    if full:
        # --full: DataFrame → records 全量 (可能几千行, 调用方自己负责承受)
        if hasattr(df, 'to_dict'):
            recs = df.to_dict('records')
            base = {'lib': lib, 'name': name, 'kind': 'records',
                    'n': len(recs), 'took_s': took}
            if hasattr(df, 'columns'):
                base['columns'] = [str(c) for c in df.columns]
            base['data'] = recs
            return base
    hint = slow_hint(name)
    if hint and took < 20:
        hint += f' (本次 {took}s, 有缓存时更快)'
    out = {'lib': lib, 'name': name, 'took_s': took}
    if hint:
        out['slow'] = hint

    if hasattr(df, 'shape') and hasattr(df, 'columns'):
        out['kind'] = 'DataFrame'
        out['shape'] = list(df.shape)
        out['columns'] = [str(c) for c in df.columns][:40]
        out['n_columns'] = len(df.columns)
        try:
            out['preview'] = df.head(preview_rows).to_dict('records')
        except Exception:                                   # noqa: BLE001
            out['preview'] = []
        return out
    if isinstance(df, dict):
        out['kind'] = 'dict'
        out['keys'] = list(df)[:20]
        out['n_keys'] = len(df)
        for k, v in list(df.items())[:3]:
            if isinstance(v, (dict, list)):
                out[f'sample.{k}'] = v[:preview_rows] if isinstance(v, list) else v
        return out
    if isinstance(df, list):
        out['kind'] = 'list'
        out['n'] = len(df)
        out['preview'] = df[:preview_rows]
        return out
    out['kind'] = type(df).__name__
    out['value'] = str(df)[:500]
    return out