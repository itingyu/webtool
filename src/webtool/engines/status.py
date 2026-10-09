# -*- coding: utf-8 -*-
"""engines status: 列出引擎与健康检查"""
import json
import time


def status(args, cfg):
    from .bing import search as bing
    from .sogou import search as sogou
    engines = {
        'bing': {'desc': 'Bing RSS 接口, 免key免JS, 国内外直连', 'fn': bing},
        'sogou': {'desc': '搜狗网页, 中文覆盖好, link 需解析', 'fn': sogou},
    }
    out = []
    for name, meta in engines.items():
        row = {'engine': name, 'desc': meta['desc']}
        if args.check:
            t0 = time.time()
            try:
                rs = meta['fn']('python', max_results=3, timeout=10)
                row.update({'ok': True, 'results': len(rs),
                            'latency_ms': int((time.time() - t0) * 1000)})
            except Exception as e:
                row.update({'ok': False, 'error': str(e)[:150]})
        out.append(row)
    print(json.dumps(out, ensure_ascii=False, indent=1))
