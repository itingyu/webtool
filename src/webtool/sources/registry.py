"""数据源注册表 / 工厂: 名字 → `SourceBase` 实例

登记走 `core.plugins` 的 `source` kind —— 与其余插件同一套三层来源 (代码注册 /
包内 plugins.json / 用户 plugins.json) 与懒加载, 于是数据源能像引擎一样在
`plugins.json` 里声明, 也能被外部 .py 插件热替换。

调用点只写 `get('search:bing')`, 不写 if-else 链 (工厂模式)。
"""
from webtool.core import plugins as _plugins
from webtool.sources.contract import SourceBase, SourceError


def registry():
    """source kind 的注册表本体"""
    return _plugins.by_kind('source')


def register(name, cls=None, **meta):
    """注册数据源。cls 为类, 或 'mod:attr' 懒加载串"""
    if isinstance(cls, str):
        return registry().register_lazy(name, cls, **meta)
    return registry().register(name, cls, **meta)


def names(enabled_only=True):
    return list(registry().names()) if enabled_only else list(registry().items(False))


def specs():
    return registry().items()


def get(name, **opts) -> SourceBase:
    """按名字造一个数据源实例; 未登记/构造失败一律抛 SourceError"""
    spec = registry().get(name)
    if spec is None:
        raise SourceError(f'未知数据源 {name!r}; 可用: '
                          f'{", ".join(names()) or "(空)"}')
    fn = spec.get('fn')
    if fn is None:
        raise SourceError(f'数据源 {name!r} 没有可用的实现 (entry 解析失败)')
    try:
        obj = fn(**opts) if isinstance(fn, type) else fn
    except Exception as e:                       # noqa: BLE001
        raise SourceError(f'数据源 {name!r} 构造失败: {type(e).__name__}: {e}') from e
    if not isinstance(obj, SourceBase):
        raise SourceError(f'数据源 {name!r} 的实现 {type(obj).__name__} '
                          f'不是 SourceBase 子类')
    return obj
