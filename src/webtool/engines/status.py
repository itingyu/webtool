"""engines 子命令: list=列引擎清单 / test=实发请求体检

排障入口: Agent 或人问"百度今天怎么没结果", 要能一眼分清三种情况——
引擎被反爬冷却 (captcha cooldown) / 引擎挂了 (error) / 引擎活着但召回为 0。
`list` 只读本地状态 (不发请求), `test` 真打一次搜索拿耗时与条数。
"""
import json
import time

from webtool.net import captcha
from webtool.core.plugins import table as _plugin_table


def _engines():
    """引擎表; 每次现取, 清单改动即时生效"""
    return _plugin_table('engine')


def status(args, cfg):
    """分发: list (默认) / test; 旧的 --check 视作 test 全体"""
    action = getattr(args, 'action', None) or 'list'
    if getattr(args, 'check', False):
        action = 'test'
    if action == 'test':
        return _test(args, cfg)
    return _list(cfg)


def _list(cfg):
    """列引擎清单 + 本地冷却状态 (不发请求)"""
    out = []
    for name, meta in _engines().items():
        row = {'engine': name, 'desc': meta['desc']}
        cd = captcha.cooldown_left(name)
        if cd:
            row['cooldown'] = f'{cd}s (此前触发反爬)'
        out.append(row)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


def _test(args, cfg):
    """实发一次请求: 指定引擎或全部; 报 ok/条数/耗时/错误"""
    names = [getattr(args, 'name', None)] if getattr(args, 'name', None) \
        else list(_engines())
    bad = [n for n in names if n not in _engines()]
    if bad:
        print(f'unknown engine: {",".join(bad)}\navailable: '
              f'{",".join(_engines())}', flush=True)
        return 2
    query = getattr(args, 'query', None) or 'python'
    out = []
    for name in names:
        meta = _engines()[name]
        row = {'engine': name}
        cd = captcha.cooldown_left(name)
        if cd:
            row['cooldown'] = f'{cd}s (此前触发反爬)'
        # 线路由规则表判定 (netx.resolve_proxy), 这里不预判、不跳过:
        # 该走代理却没配/不通, 就按真实错误报出来
        proxy = cfg.get('proxy')
        t0 = time.time()
        try:
            rs = meta['fn'](query, max_results=3, timeout=10, proxy=proxy)
            row.update({'ok': True, 'results': len(rs),
                        'latency_ms': int((time.time() - t0) * 1000)})
            if rs:
                row['top'] = {'title': rs[0].get('title', '')[:80],
                              'url': rs[0].get('url', '')}
        except Exception as e:
            row.update({'ok': False, 'error': str(e)[:150],
                        'latency_ms': int((time.time() - t0) * 1000)})
        out.append(row)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    # 有引擎测试失败时用非零退出码, 方便脚本/Agent 判断 (全被冷却也算失败)
    return 0 if all(r.get('ok') for r in out) else 1