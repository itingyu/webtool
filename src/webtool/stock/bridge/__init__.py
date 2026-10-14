"""取数桥: 只回答"数据怎么到手", 不知道 CLI 与能力域的存在

下沉前, 七个桥模块与 `command.py` 平级, 于是 CLI 层被迫 import 七个文件、
维护六路 except。分层的意义是"上管意图、下管取数", 边界该画在职责上而不是
文件位置上 —— 所以这一层整体沉到 `stock/bridge/`, 能力域 (`stock/domains/`)
只管"用户要什么", CLI 只管参数与输出。

## 用法

**按模块直接 import** (推荐 —— 就是普通包内模块, 没有动态加载):

    from webtool.stock.bridge import engine, rawapi, eco
    engine.do_quote(['600519'])

**延迟加载**给"某条桥可能缺依赖、缺了只让对应能力退 2"的场景用:

    from webtool.stock import bridge
    bridge.load('engine').do_quote(['600519'])

## 通道清单

| 模块 | 通道 | 回答 |
|---|---|---|
| `sources/` | 按数据源拆的 API 池 | 156 个低阶方法 (同花顺/东财/雪球/新浪/腾讯/巨潮/中证/上交所/efinance) |
| `srv.py` | stock 数据桥 (进程内直调 handler) | 24 个高阶聚合工具, 带 fallback 链 |
| `engine.py` | engine 脚本层 | 行情/涨停池/选股/评分/研报 |
| `eco.py` | akshare/tushare/baostock/efinance | 长尾 + 宏观 + 全球 |
| `em.py` | 东财 datacenter 配方 | 123 条 reportName 泛化调用 |
| `docs.py` | 逆向接口文档 (纯本地) | 底层 URL/参数/字段含义 |
| `http.py` | 裸 HTTP | 已封装之外自己打 |

`docs.py` 是纯本地文本检索, 一行 HTTP 都不发; `em.py` 是 `http.py` 的东财特化。
两者都在这一层内, 上层只按"要什么能力"找, 不按"哪个文件"找。

错误统一抛 `error.StockError` 子类, `source` 标明通道。
"""
import importlib

# 模块名 → 装包提示的渠道名
_CHANNELS = {
    'engine': 'engine 脚本层', 'srv': 'stock 数据桥', 'rawapi': '数据源池',
    'eco': '生态库', 'em': '东财配方', 'docs': '逆向文档', 'http': 'HTTP 直调',
}


def load(name):
    """延迟 import 一条桥模块。

    与直接 `from webtool.stock.bridge import engine` 的区别只在失败时的
    异常类型: 这里转成统一的 `BridgeMissing` 并给出装包提示, 适合上层
    想"缺了就退 2、别拖垮整条命令"的场景。
    """
    from webtool.stock.error import BridgeMissing
    try:
        return importlib.import_module(f'webtool.stock.bridge.{name}')
    except ImportError as e:
        from webtool.core import deps
        raise BridgeMissing(
            f'{_CHANNELS.get(name, name)} 桥不可用: {e}\n'
            f'  {deps.install_hint(getattr(e, "name", None) or "")}') from e


def health():
    """七条通道各自探活 —— 任一条不可用照实报, 不因一条挂了就不查别的"""
    probes = {
        'engine': lambda m: m.available(),
        'srv': lambda m: m.available(),
        'rawapi': lambda m: m.available(),
        'eco': lambda m: m.available(),
        'em': lambda m: m.stats()['reports'] > 0,
        'docs': lambda m: len(m.books()) > 0,
        'http': lambda m: m.Http is not None,
    }
    out = {}
    for name, probe in probes.items():
        try:
            out[name] = {'ok': bool(probe(load(name)))}
        except Exception as e:                              # noqa: BLE001
            out[name] = {'ok': False, 'err': f'{type(e).__name__}: {e}'}
    return out