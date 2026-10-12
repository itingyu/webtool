# -*- coding: utf-8 -*-
"""插件注册表: 引擎/站点/榜单源/提取器的统一注册与发现

设计要点:
1. 装饰器注册 (REGISTRY.register) —— 新增能力只需加一个带装饰器的模块, 不改核心
2. 元数据外置 (data/plugins.json) —— name/desc/proxy/权重等声明式数据与代码分离,
   加站点/调权重不必改 .py
3. 三层来源: 内置代码注册 → 包内 data/plugins.json → 用户 ~/.webtool/plugins.json
   后者覆盖前者同名项 (给用户改权重/加站点的口子)
4. 懒加载 —— fn 只登记名字, 首次调用时 import, 避免加载用不到的依赖

用法:
    @register_site('github', desc='GitHub', proxy='direct')
    def github(query, limit, proxy, timeout): ...

    SITES = PluginTable('site')          # 已有 dict 式访问
    SITES['github'](...)                 # 自动 import 并调用
"""
import importlib
import json
import os
from pathlib import Path

DATA_DIR = Path(__file__).parent / 'data'
USER_PLUGIN_FILE = Path(os.path.expanduser('~/.webtool/plugins.json'))


class PluginError(RuntimeError):
    """插件缺失/加载失败/签名不符"""


def _load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {}
    except (ValueError, OSError) as e:
        raise PluginError(f'{path} 解析失败: {e}') from e


class Registry:
    """一类插件的注册表 (kind: 'engine'/'site'/'hot'/'extractor')"""

    def __init__(self, kind):
        self.kind = kind
        self._code = {}          # name -> {'fn': 懒加载描述, 'meta': {...}}

    # ---- 注册 ----

    def register(self, name, fn=None, **meta):
        """注册一个插件。fn 可以是函数或 "module.path:attr" 字符串 (懒加载)"""
        def deco(f):
            self._code[name] = {'fn': f, 'meta': dict(meta, name=name, kind=self.kind)}
            return f
        return deco(fn) if fn is not None else deco

    def register_lazy(self, name, target, **meta):
        """注册懒加载插件: target='webtool.engines.bing:search'"""
        self._code[name] = {'fn': target, 'meta': dict(meta, name=name, kind=self.kind)}

    # ---- 查表 ----

    @property
    def items(self):
        """合并三层来源后的 name -> spec (fn 已解析为可调用)"""
        out = {}
        for name, rec in self._code.items():
            out[name] = {**rec['meta'], 'fn': self._resolve(rec['fn'])}
        for name, meta in _load_json(DATA_DIR / 'plugins.json').get(self.kind, {}).items():
            if name in out:
                out[name].update({k: v for k, v in meta.items() if v is not None})
            else:
                spec = {'name': name, 'kind': self.kind, **meta}
                spec['fn'] = self._resolve(meta.get('fn') or spec.get('module'))
                out[name] = spec
        for name, meta in _load_json(USER_PLUGIN_FILE).get(self.kind, {}).items():
            if name in out:
                out[name].update({k: v for k, v in meta.items() if v is not None})
            else:
                spec = {'name': name, 'kind': self.kind, **meta}
                spec['fn'] = self._resolve(meta.get('fn') or spec.get('module'))
                out[name] = spec
        return out

    def get(self, name, default=None):
        return self.items.get(name, default)

    def names(self):
        return sorted(self.items)

    def __contains__(self, name):
        return name in self.items

    def __len__(self):
        return len(self.items)

    def __getitem__(self, name):
        spec = self.items.get(name)
        if spec is None:
            raise KeyError(name)
        return spec

    # ---- 懒加载 ----

    @staticmethod
    def _resolve(fn):
        if not isinstance(fn, str):
            return fn
        mod, _, attr = fn.partition(':')
        try:
            m = importlib.import_module(mod)
        except ImportError as e:
            raise PluginError(f'插件模块导入失败: {mod} ({e})') from e
        if not attr:
            raise PluginError(f'插件 target 缺 attr: {fn}')
        return getattr(m, attr, None)


ENGINES = Registry('engine')       # 搜索引擎
SITES = Registry('site')           # 站内搜索适配器
HOT_SITES = Registry('hot')        # 榜单源
EXTRACTORS = Registry('extractor')  # 正文提取器


def table(kind):
    """把注册表转成旧式 dict (fn 已解析), 供既有代码零改动接入"""
    return {name: spec for name, spec in
            {'engine': ENGINES, 'site': SITES, 'hot': HOT_SITES,
             'extractor': EXTRACTORS}[kind].items.items()}