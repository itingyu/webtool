"""插件注册表: 九类扩展点的统一入口

清单在 src/webtool/data/plugins.json (内置) + ~/.webtool/plugins.json (用户),
用户文件按段深合并覆盖内置 —— 改权重、加插件、调顺序都不用改代码。

## 声明格式 (所有类别同一套)

    "<名字>": {
      "entry":     "包路径:函数",   # 必填, 主调用入口
      "desc":      "一句话说明",
      "version":   "1.0",
      "enabled":   true,            # false 则注册表不暴露
      "priority":  100,             # 越小越先, 同值按声明顺序
      "params":    { ... },         # 类别专属参数
      "lifecycle": {
        "setup":      "包路径:函数",  # 首次解析后调一次, 返回实例 (可省略)
        "teardown":   "包路径:函数",  # reload / 关闭前调, 释放资源
        "healthcheck":"包路径:函数"   # 返回 (ok: bool, reason: str)
      }
    }

类别与入口签名 (fn = entry 解析出的函数):

    engine       fn(query, max_results, proxy, timeout, market=None) -> [结果]
    hot          fn(query, limit, proxy, timeout) -> [结果]
    site         fn(query, limit, proxy, timeout, **kw) -> [结果]
    extractor    fn(html, url, meta) -> (正文, meta); spec 加 "dump": true 标记
                 整页兜底层 (只在内容层全空时用, 不参与择优)
    resolver     fn(url, proxy, timeout) -> 新 url
    filter       fn(results, ctx) -> [结果]
    transformer  fn(results, ctx) -> [结果]

兼容: "module" 是 "entry" 的别名; 写在顶层的类别专属键 (base/proxy/match/
search/...) 自动并入 params, 老配置不用改。

代码注册用装饰器:
    from webtool.core.plugins import SITES
    @SITES.register('mysite', desc='我的站点')
    def mysite(q, limit, proxy, timeout): return [...]

proxy 一律由管线传入 (缺省 'auto', 走路由表), 插件**不要**自己写死
`proxy=None` 之类的强制直连 —— 直连/走哪条代理是用户的部署决定, 用规则表
(`webtool proxy rule add <域名> direct`) 配置。

## 生命周期

    declared → (enabled=false) disabled
             → entry 解析成功 → loaded → setup 成功 → active
             → entry/setup 出错 → failed
    reload() / teardown() → unloaded

entry 懒解析, setup 只在该插件首次被取用时跑一次 (避免为用不到的插件建连接)。
reload() 会先 teardown 再重载, 保证长驻进程里的资源不泄漏。

热更新口径:
- JSON 清单 (内置/用户)  → mtime 变化自动重读, 无需干预
- 装饰器注册的代码      → 进程内固定, 改了需重启
- 外部 .py 插件         → reload() 重载模块后生效
"""
import importlib
import os
import sys
from pathlib import Path

from webtool.core import config_data
from webtool.core import external, jsonfmt

DATA_DIR = config_data.DATA_DIR          # 打包数据在包根 webtool/data/
PLUGIN_DIR = Path(os.environ.get('WEBTOOL_PLUGIN_DIR',
                                 os.path.expanduser('~/.webtool/plugins')))

# 统一信封字段 (不属于类别专属参数, 不并入 params)
ENVELOPE_KEYS = frozenset({'entry', 'module', 'kind', 'desc', 'version',
                           'enabled', 'priority', 'params', 'lifecycle'})

# 各类别入口的约定签名, 供 plugins check 体检 (对照 fn 形参个数/关键字可接性)
SIGNATURES = {
    'engine': (['query', 'max_results', 'proxy', 'timeout'], {'market'}),
    'hot': (['query', 'limit', 'proxy', 'timeout'], set()),
    'site': (['query', 'limit', 'proxy', 'timeout'], None),   # None = **kw 任意
    'extractor': (['html', 'url', 'meta'], set()),
    'resolver': (['url', 'proxy', 'timeout'], set()),
    'filter': (['results', 'ctx'], set()),
    'transformer': (['results', 'ctx'], set()),
}


def check_signature(kind, fn):
    """按约定签名对照 fn: 返回 (ok, 原因)

    规则 (宽松, 只拦硬伤):
    - fn 形参数 ≥ 约定必填数, 或带 *args/**kwargs → 过
    - fn 收的参数比调用方会传的少 (且无 *args) → 拦 (调用按位置传参会 TypeError)
    """
    import inspect as _inspect
    spec = SIGNATURES.get(kind)
    if spec is None:
        return True, ''
    pos, kwonly = spec
    try:
        sig = _inspect.signature(fn)
    except (TypeError, ValueError):
        return True, ''                       # 内建/C 扩展取不到签名, 放行
    has_varargs = any(p.kind is p.VAR_POSITIONAL for p in sig.parameters.values())
    has_varkw = any(p.kind is p.VAR_KEYWORD for p in sig.parameters.values())
    if has_varargs:
        return True, ''
    accepted = [p for p in sig.parameters.values()
                if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    # 调用方按约定位置传 len(pos) 个; fn 收不下 (除非有 **kwargs 也接不住位置实参)
    if len(accepted) < len(pos) and not has_varargs:
        return False, (f'fn 只收 {len(accepted)} 个位置形参, 调用约定要传 '
                       f'{len(pos)} 个 ({",".join(pos)})')
    names = [p.name for p in accepted]
    if names[:len(pos)] != pos and not has_varkw:
        return True, f'形参名 {names} 与约定 {pos} 不同 (按位置传参兼容)'
    return True, ''


class PluginError(RuntimeError):
    """插件缺失/加载失败/签名不符"""


class _Missing:
    """占位: 配置有、代码缺的插件不拖垮整表, 真正调用时才提示"""

    missing = True
    __slots__ = ('target', 'reason')

    def __init__(self, target, reason):
        self.target, self.reason = target, reason

    def __call__(self, *a, **kw):
        raise PluginError(f'插件未找到: {self.target}')

    def __repr__(self):
        return f'<unresolved {self.target}: {self.reason}>'


class PluginSpec(dict):
    """插件规格: dict 之上兼容"顶层平铺写"与"params 嵌套写"两种参数风格

    spec['base'] 与 spec.params['base'] 等价, 老代码与新配置都能用。
    """

    def __missing__(self, key):
        # 顶层没写就去 params 找 —— 让 params 成为参数的唯一真源
        params = dict.get(self, 'params') or {}
        if key in params:
            return params[key]
        raise KeyError(key)

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default


def normalize(raw, kind, name):
    """把一条声明规整成统一信封 (幂等)

    - module → entry
    - 顶层非信封键 → 并入 params
    - enabled/priority/lifecycle 补默认值
    """
    d = dict(raw or {})
    params = dict(d.get('params') or {})
    for k, v in d.items():
        if k in ENVELOPE_KEYS:
            continue
        params[k] = v            # 顶层类别专属键等价于写在 params 里
    if d.get('module') and not d.get('entry'):
        d['entry'] = d['module']
    rest = {k: v for k, v in d.items() if k not in ENVELOPE_KEYS}
    spec = {'name': name, 'kind': kind,
            'enabled': d.get('enabled', True),
            'priority': d.get('priority', 100),
            'entry': d.get('entry') or d.get('module'),
            'desc': d.get('desc', ''),
            'version': d.get('version', '1.0'),
            'lifecycle': dict(d.get('lifecycle') or {}),
            'params': params}
    spec.update(rest)           # entry/desc 等也留在顶层, 便于 spec.get()
    spec['params'] = params
    return PluginSpec(spec)


class Registry:
    """一类插件的注册表 (kind 见 SIGNATURES)"""

    def __init__(self, kind):
        self.kind = kind
        self._code = {}          # name -> {'fn': 函数或 'mod:attr', 'meta': {...}}
        self._state = {}         # name -> {'state': ..., 'error': ..., 'instance': ...}

    # 注册

    def register(self, name, fn=None, **meta):
        """注册插件。fn 可为函数或 'module.path:attr' 字符串 (懒加载)"""
        def deco(f):
            self._code[name] = {'fn': f, 'meta': dict(meta, name=name, kind=self.kind)}
            self._state.pop(name, None)
            return f
        return deco(fn) if fn is not None else deco

    def register_lazy(self, name, target, **meta):
        """注册懒加载插件: target='webtool.engines.bing:search'"""
        self._code[name] = {'fn': target, 'meta': dict(meta, name=name, kind=self.kind)}
        self._state.pop(name, None)

    # 查表

    def items(self, enabled_only=True):
        """三层来源合并后的 name -> PluginSpec (entry 已解析为 fn, 已排序)

        enabled_only=False 时连 `enabled: false` 的条目一并给出 —— 给"要知道
        哪些被显式停用"的调用方用 (默认过滤会让停用信息消失)。
        """
        out = {}
        for name, rec in self._code.items():
            raw = dict(rec['meta'])
            if isinstance(rec['fn'], str):      # 装饰器传了字符串目标
                raw.setdefault('entry', rec['fn'])
            else:
                raw['fn'] = rec['fn']
            out[name] = normalize(raw, self.kind, name)
        for name, meta in self._config().items():
            spec = out.get(name)
            merged = dict(spec) if spec is not None else dict(meta or {})
            if spec is not None:
                merged.update(meta or {})
            out[name] = normalize(merged, self.kind, name)
        for name, spec in out.items():
            if not callable(spec.get('fn')) and spec.get('entry'):
                spec['fn'] = _resolve(str(spec['entry']))
            # 外部进程插件: 套一个 callable 代理, 上层无需感知跨语言
            if (self.kind != 'interceptor' and not spec.get('fn')
                    and external.is_external(spec)):
                spec['fn'] = _external_for(name, self.kind, spec)
        if enabled_only:
            out = {n: s for n, s in out.items() if s.get('enabled', True)}
        return dict(sorted(out.items(),
                           key=lambda kv: (kv[1].get('priority', 100),)))

    def _config(self):
        """清单数据 (内置+用户), 走 config_data 的 mtime 缓存 —— 改了自动重读"""
        return config_data.load(self.kind, 'plugins.json')

    def get(self, name, default=None):
        return self.items().get(name, default)

    def names(self):
        return sorted(self.items())

    def get_all(self):
        return self.items()

    def call(self, name, *a, **kw):
        """取插件并调用 (走生命周期: 首次取用时自动 setup)

        声明了 setup 且 setup 失败的插件不裸调 entry —— 生命周期失败就停,
        不能绕过钩子直接执行。
        """
        spec = self.get(name)
        if spec is None:
            raise PluginError(f'插件未找到: {name}')
        fn = spec['fn']
        if isinstance(fn, _Missing):
            raise PluginError('插件未找到: %s (%s)' % (name, fn.target))
        inst = self.setup(name)
        has_setup = bool((spec.get('lifecycle') or {}).get('setup'))
        if has_setup and inst is None:
            st = self._state.get(name) or {}
            raise PluginError(f'插件 {name} setup 未通过: '
                              f'{st.get("error") or "disabled/failed"}')
        target = getattr(inst, 'run', None) if inst is not None else None
        return (target or fn)(*a, **kw)

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
            mod = str(s.get('entry', '') or '')
            if mod and ':' in mod and not mod.startswith('webtool.'):
                out.add(mod.partition(':')[0])
        return sorted(out)

    # 生命周期

    def setup(self, name):
        """解析 entry 并跑 setup 钩子; 返回实例 (无 setup 则 None)"""
        st = self._state.get(name)
        if st and st['state'] in ('active', 'loaded'):
            return st.get('instance')
        spec = self.get(name)
        if spec is None:
            self._state[name] = {'state': 'failed', 'error': '插件未找到: %s' % name,
                                 'instance': None}
            return None
        if not spec.get('enabled', True):
            self._state[name] = {'state': 'disabled', 'error': '', 'instance': None}
            return None
        fn = spec.get('fn')
        if isinstance(fn, _Missing) or not callable(fn):
            err = ('插件未找到: %s (%s)' % (name, fn.target)
                   if isinstance(fn, _Missing) else 'entry 不可调用')
            self._state[name] = {'state': 'failed', 'error': err, 'instance': None}
            return None
        inst = None
        hook = (spec.get('lifecycle') or {}).get('setup')
        if hook:
            try:
                inst = _import_target(hook)(spec)
            except Exception as e:
                self._state[name] = {
                    'state': 'failed',
                    'error': f'setup: {type(e).__name__}: {e}', 'instance': None}
                return None
        self._state[name] = {'state': 'active', 'error': '',
                             'instance': inst}
        return inst

    def teardown(self, name):
        """跑 teardown 钩子并回到 unloaded"""
        st = self._state.get(name)
        spec = self.get(name)
        if spec:
            hook = (spec.get('lifecycle') or {}).get('teardown')
            inst = (st or {}).get('instance')
            if hook:
                try:
                    _import_target(hook)(inst, spec)
                except Exception:
                    pass        # 释放失败不该挡住 reload
        self._state[name] = {'state': 'unloaded', 'error': '', 'instance': None}

    def reload(self):
        """teardown → 重载外部模块 → 清配置缓存 (下次取用重新 setup)"""
        for key, obj in list(_EXT_CALLERS.items()):
            if key[0] == self.kind:
                obj.close()
                _EXT_CALLERS.pop(key, None)
        for name in list(self._state):
            try:
                self.teardown(name)
            except Exception:
                pass
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
        self._state.clear()
        return reloaded

    def status(self, name=None):
        """逐个插件的生命周期状态 (不触发 setup, 纯观测)

        含 disabled 项 (来自原始声明层) —— 禁用不该等于失忆, 用户要能看到
        禁了什么、怎么恢复。
        """
        items = self.items()
        raw = self._config()               # 原始声明 (含 enabled=false 的)
        names = sorted(set(items) | set(raw)) if name is None else [name]
        out = []
        for pname in names:
            spec = items.get(pname)
            raw_spec = raw.get(pname) or {}
            st = self._state.get(pname) or {}
            state = st.get('state')
            if not state:
                if spec is None and raw_spec.get('enabled') is False:
                    state = 'disabled'
                elif spec is not None and isinstance(spec.get('fn'), _Missing):
                    state = 'missing'
                elif spec is not None:
                    state = 'declared' if spec.get('enabled', True) else 'disabled'
                else:
                    continue
            out.append({'kind': self.kind, 'name': pname, 'state': state,
                        'version': (spec or raw_spec).get('version', '1.0'),
                        'source': self._source_of(pname),
                        'error': st.get('error', ''),
                        'entry': (spec or raw_spec).get('entry') or
                                 ('<code>' if pname in self._code else '')})
        return out

    def _source_of(self, name):
        user = set(_raw_section(self.kind, 'plugins.json', user_only=True))
        if name in self._code:
            return 'code'
        return 'user' if name in user else 'builtin'

    def enable(self, name, on=True):
        """写用户清单的 enabled 开关 (disabled 插件管理闭环)"""
        user = _raw_section(self.kind, 'plugins.json', user_only=True)
        spec = user.get(name) or {}
        if not user.get(name):
            # 用户清单还没有这条: 从内置声明复制最小信封再翻转
            builtin = _raw_section(self.kind, 'plugins.json').get(name) or {}
            spec = {k: v for k, v in builtin.items() if k in ('entry', 'module', 'desc')}
        spec['enabled'] = bool(on)
        user[name] = spec
        import json as _json
        path = config_data.USER_DIR / 'plugins.json'
        config_data.USER_DIR.mkdir(parents=True, exist_ok=True)
        doc = {}
        try:
            doc = _json.loads(path.read_text(encoding='utf-8'))
        except (FileNotFoundError, ValueError, OSError):
            doc = {}
        doc.setdefault(self.kind, {}).update(user)
        path.write_text(_json.dumps(doc, ensure_ascii=False, indent=1),
                        encoding='utf-8')
        config_data.invalidate()
        self._state.pop(name, None)
        return True

    def health(self, name):
        """跑 healthcheck 钩子; 未声明则视为可用"""
        spec = self.get(name)
        if spec is None:
            return False, '插件未找到: %s' % name
        if isinstance(spec.get('fn'), _Missing):
            return False, '插件未找到: %s (%s)' % (name, spec['fn'].target)
        hook = (spec.get('lifecycle') or {}).get('healthcheck')
        if not hook:
            return True, ''
        try:
            r = _import_target(hook)(spec)
        except Exception as e:
            return False, f'{type(e).__name__}: {e}'
        if isinstance(r, tuple):
            return bool(r[0]), str(r[1]) if len(r) > 1 else ''
        return bool(r), ''

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


_EXTERNALS = set()      # 外部插件模块名 (reload 目标)


def _resolve(target):
    """'pkg.mod:attr' → 可调用对象; 失败返回 _Missing 占位, 不拖垮整表"""
    try:
        return _import_target(target)
    except PluginError as e:
        return _Missing(target, str(e))
    except Exception as e:
        return _Missing(target, f'{type(e).__name__}: {e}')


def _import_target(target, kind=None):
    """解析 'pkg.mod:attr' 成可调用对象; 外部模块挂上插件目录搜索路径"""
    if callable(target):
        return target
    mod, _, attr = str(target).partition(':')
    if not attr:
        raise PluginError(f"entry 缺函数名 (应为 包:函数): {target}")
    if not mod.startswith('webtool.'):
        # 外部插件: 目录放 .py / .pyc, 也可以直接丢一个 zip 包 (zipimport)
        d = PLUGIN_DIR
        if d.is_dir():
            for p in [str(d)] + [str(z) for z in sorted(d.glob('*.zip'))]:
                if p not in sys.path:
                    sys.path.insert(0, p)
        _EXTERNALS.add(mod)
    return getattr(importlib.import_module(mod), attr)


def _raw_section(kind, filename, user_only=False):
    """读单层原始配置 (不合并); 用于区分 builtin / user 来源"""
    base = config_data.USER_DIR if user_only else config_data.DATA_DIR
    return jsonfmt.read(base / filename).get(kind, {})


ENGINES = Registry('engine')             # 搜索引擎
SITES = Registry('site')                 # 站内搜索适配器
HOT_SITES = Registry('hot')              # 榜单源
EXTRACTORS = Registry('extractor')       # 正文提取器
RESOLVERS = Registry('resolver')         # 跳转链解码器 (按 URL 特征匹配)
FILTERS = Registry('filter')             # 结果过滤器
TRANSFORMERS = Registry('transformer')   # 结果改写
INTERCEPTORS = Registry('interceptor')   # 拦截检测/绕过 (见 net.intercept)
SOURCES = Registry('source')             # 数据源 (SourceBase: fetch(req)→DataPacket)

_REGISTRIES = (ENGINES, SITES, HOT_SITES, EXTRACTORS,
               RESOLVERS, FILTERS, TRANSFORMERS, INTERCEPTORS, SOURCES)


def by_kind(kind):
    reg = {r.kind: r for r in _REGISTRIES}.get(kind)
    if reg is None:
        raise KeyError(f'unknown plugin kind: {kind}')
    return reg


def resolve_match(url, resolvers=None):
    """认出 url 属于哪种跳转链, 返回对应 resolver 名; 不是跳转链返回 None

    与"结果来自哪个引擎"无关 —— 搜狗引擎给的链、自定义引擎给的链,
    只要 URL 特征对得上就走同一个解码器。
    """
    import re as _re
    from urllib.parse import urlparse
    reg = RESOLVERS if resolvers is None else resolvers
    specs = reg.items() if isinstance(reg, Registry) else reg
    netloc = urlparse(url).netloc or ''
    for name, spec in specs.items():
        for pat in (spec.get('match') or ()):
            if pat.startswith('~'):          # ~ 开头按正则匹配整个 url
                if _re.search(pat[1:], url):
                    return name
            elif pat in netloc or pat in url:  # 其余按子串匹配
                return name
    return None


_EXT_CALLERS = {}


def _external_for(name, kind, spec):
    """按 (kind, name) 复用代理; command/timeout 变了才重建进程"""
    key = (kind, name)
    cmd = tuple(external.command_of(spec))
    tmo = external.timeout_of(spec, 0.5)
    cur = _EXT_CALLERS.get(key)
    if cur is not None and (cur.command, cur.timeout) == (cmd, tmo):
        return cur
    if cur is not None:
        cur.close()
    obj = external.ExternalCallable(name, kind, spec)
    _EXT_CALLERS[key] = obj
    return obj


def reload_plugins():
    """重载全部注册表: 外部 .py 插件热替换 + 生命周期 teardown/重新 setup"""
    done = []
    for reg in _REGISTRIES:
        done.extend(reg.reload())
    return done


def table(kind, enabled_only=True):
    """转成普通 dict (fn 已解析), 供既有代码直接用

    enabled_only=False 时保留 `enabled: false` 的条目 (见 Registry.items)。
    """
    return dict(by_kind(kind).items(enabled_only=enabled_only))
