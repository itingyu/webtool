# -*- coding: utf-8 -*-
"""插件注册表: 四类扩展点 (engine/site/hot/extractor) 的统一查找入口

清单在 src/webtool/data/plugins.json (内置) + ~/.webtool/plugins.json (用户),
用户文件按段深合并覆盖内置 —— 改权重、加插件、调顺序都不用改代码。

代码注册: 用装饰器把函数挂进对应注册表:
    from .plugins import SITES
    @SITES.register('mysite', desc='我的站点', proxy='direct')
    def mysite(q, limit, proxy, timeout): return [...]

配置里写 "module": "包路径:函数名" 即懒加载; 外部目录 (WEBTOOL_PLUGIN_DIR,
默认 ~/.webtool/plugins) 下的 .py 也支持, 改完调 plugins.reload() 生效。

热更新口径:
- JSON 清单 (内置/用户)  → mtime 变化自动重读, 无需干预
- 装饰器注册的代码      → 进程内固定, 改了需重启 (Python 不可能安全热替换已执行代码)
- 外部 .py 插件         → reload() 重载模块后生效
"""
import importlib
import os
import sys
from pathlib import Path

from . import config_data

DATA_DIR = Path(__file__).parent / 'data'
PLUGIN_DIR = Path(os.environ.get('WEBTOOL_PLUGIN_DIR',
                                 os.path.expanduser('~/.webtool/plugins')))


class PluginError(RuntimeError):
    """插件缺失/加载失败/签名不符"""


class _Missing:
    """占位: 解析失败的插件不拖垮整表, 真正调用时才报错"""

    __slots__ = ('target', 'reason')

    def __init__(self, target, reason):
        self.target, self.reason = target, reason

    def __call__(self, *a, **kw):
        raise PluginError(f'插件 {self.target} 不可用: {self.reason}')

    def __repr__(self):
        return f'<unresolved {self.target}: {self.reason}>'


class Registry:
    """一类插件的注册表 (kind: 'engine'/'site'/'hot'/'extractor')"""

    def __init__(self, kind):
        self.kind = kind
        self._code = {}          # name -> {'fn': 函数或 'mod:attr', 'meta': {...}}

    # ---- 注册 ----

    def register(self, name, fn=None, **meta):
        """注册插件。fn 可为函数或 'module.path:attr' 字符串 (懒加载)"""
        def deco(f):
            self._code[name] = {'fn': f, 'meta': dict(meta, name=name, kind=self.kind)}
            return f
        return deco(fn) if fn is not None else deco

    def register_lazy(self, name, target, **meta):
        """注册懒加载插件: target='webtool.engines.bing:search'"""
        self._code[name] = {'fn': target, 'meta': dict(meta, name=name, kind=self.kind)}

    # ---- 查表 ----

    def items(self):
        """三层来源合并后的 name -> spec (fn 已解析)"""
        out = {}
        for name, rec in self._code.items():
            out[name] = {**rec['meta'], 'fn': self._resolve(rec['fn'])}
        for name, meta in self._config().items():
            spec = out.get(name)
            if spec is None:
                out[name] = {'name': name, 'kind': self.kind, **meta,
                             'fn': self._resolve(meta.get('fn') or meta.get('module'))}
            else:
                spec.update({k: v for k, v in meta.items() if v is not None})
        return out

    def _config(self):
        """清单数据 (内置+用户), 走 config_data 的 mtime 缓存 —— 改了自动重读"""
        return config_data.load(self.kind, 'plugins.json')

    def get(self, name, default=None):
        return self.items().get(name, default)

    def names(self):
        return sorted(self.items())

    def get_all(self):
        return self.items()

    def sources(self):
        """按来源列出插件: 'code'(装饰器) / 'builtin'(内置 json) / 'user'(用户 json)"""
        user = set(_raw_section(self.kind, 'plugins.json', user_only=True))
        code = set(self._code)
        return [(name, 'code' if name in code
                 else ('user' if name in user else 'builtin'))
                for name in self.names()]

    def external_modules(self):
        """当前引用到的外部插件模块 (改完调 reload() 生效)"""
        out = set()
        for s in self.items().values():
            mod = str(s.get('module', '') or s.get('fn', ''))
            mod = mod if isinstance(mod, str) else ''
            if mod and ':' in mod and not mod.startswith('webtool.'):
                out.add(mod.partition(':')[0])
        return sorted(out)

    def reload(self):
        """重载外部插件模块 + 清空配置缓存 (装饰器注册的代码仍需重启)"""
        config_data.invalidate()
        reloaded = []
        for mod in list(_EXTERNALS):
            m = sys.modules.get(mod)
            if m is None:
                continue
            try:
                importlib.reload(m)
                reloaded.append(mod)
            except Exception:
                pass        # reload 失败保留旧模块, 不影响其他插件
        return reloaded

    def __contains__(self, name):
        return name in self.items()

    def __len__(self):
        return len(self.items())

    def __getitem__(self, name):
        spec = self.items().get(name)
        if spec is None:
            raise KeyError(f'no such {self.kind} plugin: {name}')
        return spec

    def __iter__(self):
        return iter(self.items())

    # ---- 懒加载 ----

    def _resolve(self, fn):
        if not isinstance(fn, str):
            return fn
        mod, _, attr = fn.partition(':')
        if not attr:
            return _Missing(fn, 'target 缺函数名 (应为 包:函数)')
        if not mod.startswith('webtool.'):
            # 外部模块: 挂上插件目录搜索路径, 记进 _EXTERNALS 供 reload()
            d = str(PLUGIN_DIR)
            if d not in sys.path and PLUGIN_DIR.is_dir():
                sys.path.insert(0, d)
            _EXTERNALS.add(mod)
        try:
            m = importlib.import_module(mod)
        except Exception as e:
            return _Missing(fn, f'{type(e).__name__}: {e}')
        got = getattr(m, attr, None)
        if got is None:
            return _Missing(fn, f'模块里没有 {attr}')
        return got


_EXTERNALS = set()      # 外部插件模块名 (reload 目标)


def _raw_section(kind, filename, user_only=False):
    """读单层原始配置 (不合并); 用于区分 builtin / user 来源"""
    import json
    base = config_data.USER_DIR if user_only else config_data.DATA_DIR
    try:
        return json.loads((base / filename).read_text(encoding='utf-8')).get(kind, {})
    except (FileNotFoundError, ValueError, OSError):
        return {}


ENGINES = Registry('engine')        # 搜索引擎
SITES = Registry('site')            # 站内搜索适配器
HOT_SITES = Registry('hot')         # 榜单源
EXTRACTORS = Registry('extractor')  # 正文提取器

_REGISTRIES = (ENGINES, SITES, HOT_SITES, EXTRACTORS)


def reload_plugins():
    """重载全部注册表: 外部 .py 插件热替换 + 配置缓存清空"""
    done = []
    for reg in _REGISTRIES:
        done.extend(reg.reload())
    return done


def table(kind):
    """转成普通 dict (fn 已解析), 供既有代码直接用"""
    return dict({'engine': ENGINES, 'site': SITES, 'hot': HOT_SITES,
                 'extractor': EXTRACTORS}[kind].items())