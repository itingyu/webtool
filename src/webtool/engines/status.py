# -*- coding: utf-8 -*-
"""engines status: 列出引擎与健康检查"""
import json
import time


# 检查各引擎状态
def status(args, cfg):
    from .bing import search as bing
    from .sogou import search as sogou
    from .google import search as google
    from .marginalia import search as marginalia
    from .baidu import search as baidu
    from .. import captcha
    engines = {
        'bing': {'desc': 'Bing HTML 主通道+RSS兜底, chrome指纹, 国内 cn. 直连', 'fn': bing},
        'sogou': {'desc': '搜狗: PC优先(chrome指纹)→移动端(Android指纹,直出真实URL)', 'fn': sogou},
        'google': {'desc': 'Google: web(需代理,常IP级reCAPTCHA)→news RSS 自动降级+文章链还原', 'fn': google},
        'baidu': {'desc': '百度网页, 多步预热(cookie+sugrec行为链), 反爬严(滑块)', 'fn': baidu},
        'marginalia': {'desc': 'Marginalia 独立索引, 小站/老网页长尾, 免key直连, sst挑战自动解', 'fn': marginalia},
    }
    out = []
    for name, meta in engines.items():
        row = {'engine': name, 'desc': meta['desc']}
        cd = captcha.cooldown_left(name)
        if cd:
            row['cooldown'] = f'{cd}s (此前触发反爬)'
        if args.check:
            t0 = time.time()
            try:
                proxy = ((cfg.get('engine_proxy') or {}).get(name)
                         or cfg.get('proxy'))
                rs = meta['fn']('python', max_results=3, timeout=10,
                                proxy=proxy)
                row.update({'ok': True, 'results': len(rs),
                            'latency_ms': int((time.time() - t0) * 1000)})
            except Exception as e:
                row.update({'ok': False, 'error': str(e)[:150]})
        out.append(row)
    print(json.dumps(out, ensure_ascii=False, indent=1))
