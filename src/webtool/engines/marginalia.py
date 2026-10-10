# -*- coding: utf-8 -*-
"""Marginalia 引擎: 独立索引 (非 Google 系), 非商业小站/老网页覆盖好, 免 key

2026-10-10 攻关实录 (数据中心 IP 实测):
- marginaalia 新 UI 对高频 bot 有 'Wait A Moment' 挑战, 但纯 HTTP 可解:
  GET(挑战页) → 提取 sst= token 链接 → 等 2s → GET(发 sst-SE cookie) →
  再 GET(带 cookie) → 放行。整个握手 ≤3 跳, 实测 3/3 query 全过
- 结果结构: h2>a(title) + a(url 重复) + p(摘要), 免二次跳转解析
- 特点: 独立爬取索引 (crawler-ips 公开), 结果与 Google/Bing 差异大,
  适合做长尾补充源; 中文覆盖弱 (索引以英文技术内容为主)
"""
import re
import time
import urllib.parse

from .. import captcha, transport, state

_BASE = 'https://marginalia-search.com'
_MAX_HOPS = 6          # 挑战握手最多跟几跳
_WAIT = 2.2            # 挑战倒计时 1s + 余量


def search(query, max_results=10, proxy=None, timeout=15, market=None, page=1):
    if page > 3:                      # 深翻页无收益, 独立索引首页质量最高
        return []
    q = urllib.parse.quote(query)
    url = f'{_BASE}/search?query={q}'
    if page > 1:
        url += f'&page={page}'
    main = _fetch_result_main(url, proxy, timeout)
    out = _parse(main, max_results)
    captcha.mark_ok('marginalia')
    return out


def _fetch_result_main(url, proxy, timeout):
    """挑战握手: GET → sst 链接 → 等待 → 带 cookie 重放, 直到 main 区出结果"""
    s = transport._cr.Session(impersonate='chrome131', proxy=proxy or None)
    main = ''
    for _hop in range(_MAX_HOPS):
        try:
            r = s.get(url, timeout=timeout,
                      headers=transport.headers_for('nav', url, referer=_BASE + '/'))
            t = r.text
        except Exception:
            raise RuntimeError('marginalia 网络错误')
        i = t.find('<main')
        main = t[i:t.find('</main>')] if i > 0 else t
        if 'Wait A Moment' not in main:
            return main
        # 提取 sst 续链 (challenge 页/页脚都有)
        m = (re.search(r'href="(/search\?[^"]*sst=[^"]+)"', main)
             or re.search(r'href="(/search\?[^"]*sst=[^"]+)"', t))
        if not m:
            raise RuntimeError('marginalia 挑战流程变更 (无 sst 链接)')
        url = _BASE + m.group(1).replace('&amp;', '&')
        time.sleep(_WAIT)
    raise RuntimeError(f'marginalia 挑战未通过 ({_MAX_HOPS} 跳)')


def _parse(main, max_results):
    """h2>a(title) 逐条; 摘要在结果块 p.mt-2 节点"""
    out, seen = [], set()
    for m in re.finditer(r'<h2[^>]*>\s*<a[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>', main, re.S):
        u = m.group(1)
        if u in seen:
            continue
        title = _text(m.group(2))
        if not title:
            continue
        seen.add(u)
        # 摘要: 结果块内 <p class="mt-2 ..."> 节点
        after = main[m.end():m.end() + 3000]
        sn = re.search(r'<p class="mt-2[^"]*"[^>]*>(.*?)</p>', after, re.S)
        snippet = _text(sn.group(1))[:200] if sn else ''
        out.append({'rank': len(out) + 1, 'title': title, 'url': u,
                    'snippet': snippet, 'channel': 'marginalia'})
        if len(out) >= max_results:
            break
    return out


def _text(s):
    s = re.sub(r'<[^>]+>', '', s or '')
    from html import unescape
    return unescape(s).strip()
