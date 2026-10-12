# -*- coding: utf-8 -*-
"""engines 子命令: list=列引擎清单 / test=实发请求体检

排障入口: Agent 或人问"百度今天怎么没结果", 要能一眼分清三种情况——
引擎被反爬冷却 (captcha cooldown) / 引擎挂了 (error) / 引擎活着但召回为 0。
`list` 只读本地状态 (不发请求), `test` 真打一次搜索拿耗时与条数。
"""
import json
import time

from .bing import search as bing
from .sogou import search as sogou
from .google import search as google
from .marginalia import search as marginalia
from .baidu import search as baidu
from .. import captcha

ENGINES = {
    'bing': {'desc': 'Bing HTML 主通道+RSS兜底, chrome指纹, 国内 cn. 直连', 'fn': bing},
    'sogou': {'desc': '搜狗: PC优先(chrome指纹)→移动端(Android指纹,直出真实URL)', 'fn': sogou},
    'google': {'desc': 'Google: web(需代理,常IP级reCAPTCHA)→news RSS 自动降级+文章链还原', 'fn': google},
    'baidu': {'desc': '百度网页, 多步预热(cookie+sugrec行为链), 反爬严(滑块)', 'fn': baidu},
    'marginalia': {'desc': 'Marginalia 独立索引, 小站/老网页长尾, 免key直连, sst挑战自动解', 'fn': marginalia},
}


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
    for name, meta in ENGINES.items():
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
        else list(ENGINES)
    bad = [n for n in names if n not in ENGINES]
    if bad:
        print(f'unknown engine: {",".join(bad)}\navailable: '
              f'{",".join(ENGINES)}', flush=True)
        return 2
    query = getattr(args, 'query', None) or 'python'
    # required 引擎无可用代理时标 skipped, 不白等超时
    from ..search import ENGINE_PROXY_HINT, _proxy_alive
    out = []
    for name in names:
        meta = ENGINES[name]
        row = {'engine': name}
        cd = captcha.cooldown_left(name)
        if cd:
            row['cooldown'] = f'{cd}s (此前触发反爬)'
        proxy = (cfg.get('engine_proxy') or {}).get(name) or cfg.get('proxy')
        if ENGINE_PROXY_HINT.get(name) == 'required' and not _proxy_alive(cfg):
            row.update({'ok': False, 'skipped': True,
                        'error': '需代理 (webtool proxy set <url> 后再试)'})
            out.append(row)
            continue
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