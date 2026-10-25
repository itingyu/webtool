#!/usr/bin/env python3
"""提取质量体检: 同一批 URL 上, 每个提取器各产出多少、有多脏、最后谁胜出

改提取算法 (engines/boilerplate.py 的打分/清尾, extractors.pick_best 的权重)
之后跑一遍, 看有没有把好页面搞坏 —— 单测用合成 HTML 锁行为, 这个用真实页面看
效果, 两件事。

跑法:
    python3 scripts/eval_extract.py URL [URL ...]
    python3 scripts/eval_extract.py --url-file urls.txt

每行: 名字 字数 碎片率 耗时; 最后一行是 run_chain 的胜出者 (带 `->`)。
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from webtool.core import http as H                      # noqa: E402
from webtool.engines import extractors as EX            # noqa: E402
from webtool.engines import boilerplate as BO           # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('urls', nargs='*')
    ap.add_argument('--url-file')
    ap.add_argument('--timeout', type=int, default=20)
    a = ap.parse_args()
    urls = list(a.urls)
    if a.url_file:
        urls += [x.strip() for x in open(a.url_file, encoding='utf-8')
                 if x.strip() and not x.startswith('#')]
    if not urls:
        ap.error('给 URL 或 --url-file')

    for url in urls:
        try:
            html = H.http_get(url, timeout=a.timeout)[0]
        except Exception as e:
            print(f'### {url}\n    取页失败: {str(e)[:80]}')
            continue
        print(f'### {url}  (html {len(html)})')
        for name, fn in (('trafilatura', EX.extract_trafilatura),
                         ('boilerplate', BO.extract_boilerplate),
                         ('readability', EX.extract_readability),
                         ('inscriptis', EX.extract_inscriptis)):
            t0 = time.time()
            try:
                txt, _ = fn(html, url, {})
            except Exception as e:
                print(f'    {name:<12} 失败 {str(e)[:60]}')
                continue
            txt = txt or ''
            print(f'    {name:<12} {len(txt):>7} 字  碎片 {EX.fragment_ratio(txt) * 100:>4.0f}%'
                  f'  {(time.time() - t0) * 1000:>5.0f}ms')
        t, m = EX.run_chain(html, url, {})
        print(f'  -> 胜出 {m.get("_via")}  {len(t)} 字  碎片 '
              f'{EX.fragment_ratio(t) * 100:.0f}%'
              + (f'  缺依赖 {m["_missing"]}' if m.get('_missing') else ''))
        print('    ' + (t[:160].replace('\n', ' / ') or '(空)'))


if __name__ == '__main__':
    main()
