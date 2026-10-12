# -*- coding: utf-8 -*-
"""plugins 子命令: 查插件清单/来源, 体检加载, 手动热重载"""
import json
import sys

from . import config_data, plugins

_KINDS = (('engine', plugins.ENGINES),
          ('hot', plugins.HOT_SITES),
          ('site', plugins.SITES),
          ('extractor', plugins.EXTRACTORS))


def handle(args):
    action = getattr(args, 'action', None) or 'list'
    if action == 'list':
        return _list(args)
    if action == 'reload':
        return _reload()
    if action == 'check':
        return _check()
    return 2


def _list(args):
    kind = getattr(args, 'kind', None)
    out = {}
    for name, reg in _KINDS:
        if kind and name != kind:
            continue
        src = dict(reg.sources())
        out[name] = [{'name': n, 'source': src.get(n, 'builtin')}
                     for n in sorted(reg.names())]
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def _check():
    """体检: 逐个解析插件的 module 路径, 报出加载失败/签名缺失的"""
    bad, ok = [], 0
    for name, reg in _KINDS:
        for pname in sorted(reg.names()):
            spec = reg[pname]
            fn = spec.get('fn')
            if isinstance(fn, plugins._Missing):
                bad.append({'kind': name, 'plugin': pname,
                            'module': str(spec.get('module', '')),
                            'error': fn.reason})
            elif not callable(fn):
                bad.append({'kind': name, 'plugin': pname,
                            'module': str(spec.get('module', '')),
                            'error': 'fn 不可调用'})
            else:
                ok += 1
    print(json.dumps({'ok': ok, 'failed': len(bad), 'errors': bad},
                     ensure_ascii=False, indent=2))
    return 1 if bad else 0


def _reload():
    # 先取外部模块列表再清缓存, 否则 reload 后缓存重建会看不到引用
    ext = sorted({m for _, reg in _KINDS for m in reg.external_modules()})
    done = sorted({m for _, reg in _KINDS for m in reg.reload()})
    config_data.invalidate()
    print(json.dumps({'reloaded_modules': done,
                      'external_modules': ext,
                      'note': '装饰器注册 (@register) 的代码需重启进程'},
                     ensure_ascii=False, indent=2))
    return 0