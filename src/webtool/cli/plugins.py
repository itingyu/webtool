"""plugins 子命令: 查插件清单/来源, 体检加载, enable/disable, 手动热重载"""
import json
import sys

from webtool.core import config_data, external, plugins

_KINDS = tuple((reg.kind, reg) for reg in plugins._REGISTRIES)


def handle(args):
    action = getattr(args, 'action', None) or 'list'
    if action == 'list':
        return _list(args)
    if action == 'reload':
        return _reload()
    if action == 'check':
        return _check()
    if action == 'doctor':
        return _doctor()
    if action == 'enable':
        return _set_enabled(args, True)
    if action == 'disable':
        return _set_enabled(args, False)
    return 2


# ============================================================ doctor
# 自检: 扫 engines/ 下所有"站点适配器形状"的函数, 跟 plugins.json 已注册的
# 站点对账 —— 找出"代码写了、清单漏登记"的孤儿 (ithome_so 就是这么丢的:
# 适配器写好了但没进 plugins.json, 站点搜索里根本调不到)。
# check 管的是"清单有、代码缺/坏"; doctor 管反方向"代码有、清单缺"。

# 站点适配器约定签名 (与 core.plugins.SIGNATURES['site'] 一致)
_SITE_SIG = ('q', 'limit', 'proxy', 'timeout')

# 这些模块里的函数不是站点适配器 (工具函数/基类/内部件), 扫到也不算数
_SITE_SKIP_FILES = ('source.py', 'extractors.py', 'boilerplate.py')


def _scan_site_adapters():
    """扫 webtool/engines/*.py, 返回 {func_name: (module_path, qualname)}

    判据: 函数形参前四位是 (q, limit, proxy, timeout) —— 站点适配器的约定
    形状。辅助函数 (只有 q 或没有 q) 不会被误判。
    """
    import ast
    import os
    import inspect as _inspect

    try:
        import webtool.engines as _eng
        pkg_dir = os.path.dirname(_eng.__file__)
    except Exception:
        return {}

    found = {}
    try:
        files = sorted(f for f in os.listdir(pkg_dir) if f.endswith('.py'))
    except OSError:
        return {}

    for fname in files:
        if fname in _SITE_SKIP_FILES or fname.startswith('_'):
            continue
        path = os.path.join(pkg_dir, fname)
        try:
            src = open(path, encoding='utf-8').read()
            tree = ast.parse(src)
        except (OSError, SyntaxError):
            continue
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            names = [a.arg for a in node.args.args]
            if tuple(names[:4]) == _SITE_SIG:
                found[node.name] = (f'webtool.engines.{fname[:-3]}',
                                    f'{fname[:-3]}.{node.name}')
    return found


def _doctor():
    """doctor: 反向对账 —— 代码里有适配器但清单没登记的孤儿"""
    from webtool.core import config_data as _cd

    raw = _cd.load('site', 'plugins.json')
    registered = set(raw or {})

    # 同一个适配器形状的函数也可能登记在别的段 (hotsites 的榜单源登记在 hot 段,
    # 不是 site 段)。覆盖判定要跨段, 否则全被误报成孤儿。
    covered_modules = set()
    for kind in ('site', 'hot', 'engine', 'source', 'extractor',
                 'resolver', 'filter', 'transformer'):
        try:
            sec = _cd.load(kind, 'plugins.json') or {}
        except Exception:                        # noqa: BLE001 段不存在就跳过
            continue
        for spec in sec.values():
            mod = str(spec.get('module', ''))
            if ':' in mod:
                covered_modules.add(mod.rsplit(':', 1)[1])

    adapters = _scan_site_adapters()
    orphans = []
    for fn_name, (module, qual) in sorted(adapters.items()):
        if fn_name in registered or fn_name in covered_modules:
            continue
        orphans.append({'function': fn_name, 'module': module,
                        'qualname': qual,
                        'hint': f'在 plugins.json 的 site 段加一条 '
                                f'"module": "{module}:{fn_name}"'})

    # 反向: 清单登记了但代码里找不到同名适配器 (check 只看模块能否加载,
    # 这里看适配器形状本身是否还在)
    stale = []
    for name, spec in (raw or {}).items():
        mod = str(spec.get('module', ''))
        if ':' not in mod:
            continue
        fn_name = mod.rsplit(':', 1)[1]
        if fn_name in adapters:
            continue
        try:
            mod_path, attr = mod.split(':', 1)
            import importlib
            obj = importlib.import_module(mod_path)
            target = getattr(obj, attr, None)
            if target is None:
                stale.append({'plugin': name, 'module': mod,
                              'error': '模块里没有该名字'})
            elif not callable(target):
                stale.append({'plugin': name, 'module': mod,
                              'error': '不是可调用对象'})
        except Exception as e:                    # noqa: BLE001
            stale.append({'plugin': name, 'module': mod,
                          'error': f'{type(e).__name__}: {str(e)[:120]}'})

    print(json.dumps({
        'registered_sites': len(registered),
        'scanned_adapters': len(adapters),
        'unregistered_adapters': len(orphans),
        'orphans': orphans,
        'stale_entries': stale,
        'note': ('orphan = 代码里写了适配器但 plugins.json 没登记, 站点搜索调不到; '
                 'stale = 清单登记了但代码里找不到'),
    }, ensure_ascii=False, indent=2))
    return 1 if (orphans or stale) else 0


def _set_enabled(args, on):
    """plugins enable|disable <kind> <name>: 写用户清单翻转 enabled"""
    kind = getattr(args, 'kind', None)
    name = getattr(args, 'plugin', None) or (
        getattr(args, 'plugin_arg', None))
    if not kind or not name:
        print('usage: webtool plugins enable|disable <kind> <name>\n'
              f'kind: {", ".join(k for k, _ in _KINDS)}', file=sys.stderr)
        return 2
    reg = plugins.by_kind(kind)
    if name not in reg:
        from webtool.core import config_data as _cd
        if name not in _cd.load(kind, 'plugins.json'):
            print(f'unknown {kind} plugin: {name}', file=sys.stderr)
            return 2
    reg.enable(name, on)
    print(json.dumps({'plugin': name, 'kind': kind,
                      'enabled': on, 'note': 'JSON 清单 mtime 自动生效, 无需重启'},
                     ensure_ascii=False))
    return 0


def _list(args):
    kind = getattr(args, 'kind', None)
    show_all = getattr(args, 'all', False)
    out = {}
    for name, reg in _KINDS:
        if kind and name != kind:
            continue
        if show_all:
            # 含 disabled: 从生命周期 status 取 (names() 只有启用的)
            out[name] = reg.status()
        else:
            src = dict(reg.sources())
            out[name] = [{'name': n, 'source': src.get(n, 'builtin')}
                         for n in sorted(reg.names())]
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def _bad_interceptor(fn):
    """拦截器类体检: 不过关返回人话原因, 过关返回 ''"""
    from webtool.net.intercept import Interceptor
    if not (isinstance(fn, type) and issubclass(fn, Interceptor)):
        return '不是 net.intercept.Interceptor 的子类'
    if not getattr(fn, 'name', ''):
        return '缺 name (配置里要靠它启用/停用)'
    for attr in ('inspect',):
        m = getattr(fn, attr, None)
        if m is None or getattr(m, '__isabstractmethod__', False):
            return f'没实现 {attr}()'
    return ''


def _check():
    """体检: 逐个解析插件的 module 路径 + 签名对照, 报出加载失败/签名不符的"""
    bad, miss, ok = [], [], 0
    for name, reg in _KINDS:
        for pname in sorted(reg.names()):
            spec = reg[pname]
            fn = spec.get('fn')
            if isinstance(fn, plugins._Missing):
                # 配置有、代码缺: 不算失败, 只是用不了 —— 真正调用时才提示
                miss.append({'kind': name, 'plugin': pname,
                             'module': str(spec.get('module', '')),
                             'error': fn.reason})
                continue
            if external.is_external(spec):
                # 外部插件: 起一次、ping 通即可; 起不来算 missing 不算失败
                from webtool.core.external import probe
                okping, why = probe(spec, pname)
                if okping:
                    ok += 1
                else:
                    miss.append({'kind': name, 'plugin': pname,
                                 'module': ' '.join(external.command_of(spec)),
                                 'error': why or '无法启动'})
                continue
            if not callable(fn):
                bad.append({'kind': name, 'plugin': pname,
                            'module': str(spec.get('module', '')),
                            'error': 'fn 不可调用'})
                continue
            if name == 'interceptor':
                # 拦截器是类不是函数: 签名那套对不上, 单独验"是不是 Interceptor
                # 子类 + 有没有实现 inspect"
                msg = _bad_interceptor(fn)
                if msg:
                    bad.append({'kind': name, 'plugin': pname,
                                'module': str(spec.get('module', '')),
                                'error': msg})
                    continue
            sig_ok, sig_msg = plugins.check_signature(name, fn)
            if not sig_ok:
                bad.append({'kind': name, 'plugin': pname,
                            'module': str(spec.get('module', '')),
                            'error': f'签名不符: {sig_msg}'})
                continue
            # 声明了 lifecycle 钩子的: 校验钩子目标可解析
            for hook_kind, hook in (spec.get('lifecycle') or {}).items():
                try:
                    plugins._import_target(hook)
                except Exception as e:
                    bad.append({'kind': name, 'plugin': pname,
                                'module': str(hook),
                                'error': f'lifecycle.{hook_kind} 不可解析: {e}'})
                    break
            else:
                ok += 1
    # 拦截器还会在**运行期**记错 (插件抛错只让它掉队, 不中断请求), 一并报出来
    runtime = {}
    try:
        from webtool.net import intercept as _ic
        runtime = _ic.problems()
        seen = {(m['kind'], m['plugin']) for m in miss}
        for pname, why in _ic.missing().items():
            if ('interceptor', pname) not in seen:
                miss.append({'kind': 'interceptor', 'plugin': pname,
                             'module': '', 'error': why})
    except Exception:                       # noqa: BLE001 拉不起来不影响体检结论
        pass
    print(json.dumps({'ok': ok, 'failed': len(bad),
                      'missing': len(miss), 'missing_plugins': miss,
                      'errors': bad, 'runtime_errors': runtime},
                     ensure_ascii=False, indent=2))
    return 1 if bad else 0


def _reload():
    try:
        from webtool.net import intercept as _ic
        _ic.close_external()
    except Exception:                       # noqa: BLE001
        pass
    # 先取外部模块列表再清缓存, 否则 reload 后缓存重建会看不到引用
    ext = sorted({m for _, reg in _KINDS for m in reg.external_modules()})
    done = sorted({m for _, reg in _KINDS for m in reg.reload()})
    config_data.invalidate()
    print(json.dumps({'reloaded_modules': done,
                      'external_modules': ext,
                      'note': '装饰器注册 (@register) 的代码需重启进程'},
                     ensure_ascii=False, indent=2))
    return 0