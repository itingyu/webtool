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
    if action == 'enable':
        return _set_enabled(args, True)
    if action == 'disable':
        return _set_enabled(args, False)
    return 2


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