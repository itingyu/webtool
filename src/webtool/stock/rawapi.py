"""桥接 api_client.APIClient 的 152 个低阶方法

`/var/minis/shared/股票/API调研/api_client.py` 是本次股票能力的**数据底座**:
雪球/同花顺/东财/新浪/巨潮/百度/腾讯/中证 8 大源、26 个 HTTP endpoint 与 5 个
efinance 函数的统一封装, 每源自带 fallback 链与重试。

stock 服务端只把其中 56 个方法聚合成 24 个高阶工具给 Agent 用; 剩下 96 个
(股东研究、盈利预测、财务分析、研报日历、早盘晚报、板块多维排行、分钟线、
产业链分类……) 仍然有价值, 通过本模块按需直接调用。

## 分工

- 高阶、已聚合的能力 → 走 `stock/srv.py` (服务端 24 工具)
- 低阶、没被聚合的     → 走本模块 (152 方法全量可调)

`webtool stock api <方法> --arg K=V` 是通用入口, 服务端未覆盖的能力都能调;
高频的几个另加了专门动作 (holder/forecast/zaopan/minute 等), 免记方法名。

⚠️ 返回形状与 stock 服务端一致: `{"ok":bool, "data":..., "error":...}`,
失败抛 RawApiError 由上层转成退出码 1, 不静默返回空。
"""
import importlib
import inspect
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
    """按数据源前缀分组, 便于发现 (ths_/sina_/xueqiu_/em_/gtimg_/cninfo_/...)"""
    out = {}
    for m in methods():
        out.setdefault(m.split('_')[0], []).append(m)
    return {k: sorted(v) for k, v in sorted(out.items())}


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