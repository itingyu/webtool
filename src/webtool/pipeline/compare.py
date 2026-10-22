"""多源并排对比: 几个 URL 各自讲了什么, 哪些是共有的, 哪些是独有的

为什么不用关键词词频: 中文没有空格, 词频要分词器 (jieba 之类), 引依赖
重且对短文本不稳。这里用**句子级 bigram 相似度** —— 不需要分词, 中文
英文都能算, 而且"这篇有、那篇没有的要点"直接用句子表达, 比一堆孤立
关键词更可读。
"""

import json
import re
import sys

# 句子切分: 中英文句末标点 + 换行
_SPLIT = re.compile(r'(?<=[。！？!?；;])|[\n\r]+')

_MIN_LEN = 12      # 太短的句子不当要点 ("点击查看" 这种)
_MAX_LEN = 220     # 太长的切不开, 但仍保留 (截断展示)
_MIN_DOC = 200     # 正文短于这个字数视为无效来源 (404/导航页/空壳)

_FRONT = re.compile(r'\A---\s*\n(.*?)\n---\s*\n', re.S)

# 噪声句: 广告尾巴 / 导流 / 版权 / 链接残留。这些句子信息密度为零,
# 但长度和位置往往很像"要点", 不滤掉就会占满"独有要点" (实测搜狐
# 的文章末尾全是「点击这里，一键生成周报总结」)。
_NOISE = re.compile(
    r'点击|扫码|关注我们|下载客户端|一键生成|无脑|转发|责任编辑|原标题|'
    r'举报|免责声明|版权归|未经授权|更多精彩|来源：|编辑：|实习生|'
    r'https?://|\]\(|_trans_|\bAPP\b|公众号|'
    # 第一人称推销/软文尾巴 (实测漏网: "让我这个 30+打工人的工作效率
    # 提升至少30%，年底成功达到加薪目标！")。只收高置信度的营销词,
    # 不收"打工人""效率提升"这类正文里也常见的说法。
    r'加薪目标|亲测|血赚|真香|绝了|神器|限时|免费领|速看|闭眼入|'
    r'让我|我这个|我亲|安利给|不买后悔')



def split_front(text):
    """拆出 YAML front-matter; 返回 (meta_dict, body)

    fetch 的 content 可能带元数据头 (title/url/author 等), 那几行
    既不是正文也不是要点, 不剥掉会被当要点抽出来。
    """
    m = _FRONT.match(text or '')
    if not m:
        return {}, text or ''
    meta = {}
    for line in m.group(1).splitlines():
        if ':' in line:
            k, v = line.split(':', 1)
            meta[k.strip().lower()] = v.strip().strip('"\'')
    return meta, (text or '')[m.end():]


def sentences(text):
    """切句 + 去噪, 保留原顺序"""
    out = []
    for raw in _SPLIT.split(text or ''):
        s = (raw or '').strip()
        # 去掉 markdown 标记 / 列表符号 / 页眉噪声
        s = re.sub(r'^[#>*\-+\s]+', '', s)
        s = re.sub(r'\s+', ' ', s)
        if len(s) < _MIN_LEN:
            continue
        if _NOISE.search(s):
            continue
        out.append(s[:_MAX_LEN])
    return out


def bigrams(s):
    """字符 bigram 集合 (相似度的基础)"""
    s = re.sub(r'\s+', '', s or '')
    if len(s) < 2:
        return set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def sim(a, b):
    """Jaccard 相似度, 0-1 (对称; 判"两句话说的是不是同一件事")"""
    ba, bb = bigrams(a), bigrams(b)
    if not ba or not bb:
        return 0.0
    inter = len(ba & bb)
    return inter / float(len(ba | bb))


def contain(a, b):
    """包含度: 交集 / 较短那句的 bigram 数 (0-1)

    为什么还要这个: 同一件事常被不同媒体写成"长版"和"压缩版"
    (「特斯拉第三季度交付量为 46.3 万辆，同比增长 6%」vs
    「特斯拉三季度交付 46.3 万辆，同比增 6%」)。Jaccard 会被长度差
    拉低到 0.3 左右而漏判, 包含度能到 0.8 以上。
    """
    ba, bb = bigrams(a), bigrams(b)
    if not ba or not bb:
        return 0.0
    return len(ba & bb) / float(min(len(ba), len(bb)))


def keypoints(text, n=6):
    """取一篇的要点: 先按信息密度打分, 再保持原文顺序

    打分只看文本本身, 不依赖外部知识:
    - 含数字/百分比/年份 -> 通常是事实性要点
    - 长度适中 -> 太长是段落, 太短是碎片
    - 位置靠前 -> 新闻/文章的导语信息量最大
    """
    sents = sentences(text)
    if not sents:
        return []
    scored = []
    for i, s in enumerate(sents):
        score = 0.0
        if re.search(r'\d', s):
            score += 2.0
        if re.search(r'%|％|亿|万|倍|元|美元', s):
            score += 1.0
        ln = len(s)
        if 20 <= ln <= 120:
            score += 1.5
        elif ln < 20:
            score += 1.0
        # 前 10 句给位置加成, 之后快速衰减
        if i < 3:
            score += 3.0
        elif i < 10:
            score += 1.5 - i * 0.1
        scored.append((score, i, s))
    # 先取分高的, 再按原文顺序输出
    top = sorted(scored, key=lambda x: (-x[0], x[1]))[:n]
    return [s for _, _, s in sorted(top, key=lambda x: x[1])]


def unique_points(docs, points, threshold=0.30):
    """每篇独有的要点: 与其它篇所有句子都不像的

    docs: [{'url':..., 'text':...}]
    points: {url: [要点]}
    返回 {url: [独有要点]}
    """
    sents = {d['url']: sentences(d.get('text') or '') for d in docs}
    out = {}
    for d in docs:
        u = d['url']
        others = [s for o in docs if o['url'] != u for s in sents[o['url']]]
        if not others:
            out[u] = list(points.get(u) or [])
            continue
        mine = []
        for p in points.get(u) or []:
            best = max((sim(p, o) for o in others), default=0.0)
            if best < threshold:
                mine.append(p)
        out[u] = mine
    return out


def shared_points(docs, points, threshold=0.55):
    """跨篇共有的要点: 至少两篇都说了同一件事

    做法是把各篇要点互相比对, 相似度超过阈值的并成一簇,
    簇里涉及的 url 去重后 >= 2 就算共有 (按涉及篇数排序)。
    """
    items = []
    for d in docs:
        for p in points.get(d['url']) or []:
            items.append((d['url'], p))
    clusters = []
    for url, p in items:
        placed = False
        for c in clusters:
            if any(contain(p, q) >= threshold for _, q in c['items']):
                if not any(u == url for u, _ in c['items']):
                    c['items'].append((url, p))
                    c['urls'].add(url)
                placed = True
                break
        if not placed:
            clusters.append({'items': [(url, p)], 'urls': {url}})
    shared = [c for c in clusters if len(c['urls']) >= 2]
    shared.sort(key=lambda c: (-len(c['urls']), -len(c['items'])))
    return [{'urls': sorted(c['urls']), 'text': c['items'][0][1],
             'count': len(c['items'])} for c in shared]


def build(docs, n=6):
    """汇总成可直接渲染的结构"""
    points = {d['url']: keypoints(d.get('text') or '', n=n) for d in docs}
    return {
        'docs': [{'url': d['url'], 'title': d.get('title') or '',
                  'chars': len(d.get('text') or ''), 'sentences': len(sentences(d.get('text') or ''))}
                 for d in docs],
        'points': points,
        'shared': shared_points(docs, points),
        'unique': unique_points(docs, points),
    }


# ---------------------------------------------------------------- 命令入口

def _short(url, width=48):
    return url if len(url) <= width else url[:width - 1] + '…'


def _host(url):
    """只要域名: 标题已经说了是哪个页面, 再跟一长串路径是噪声"""
    try:
        from urllib.parse import urlsplit
        return urlsplit(url).netloc or _short(url)
    except Exception:
        return _short(url)


def _render(res, fmt):
    """text/markdown 渲染: 先看共有, 再看各自独有"""
    md = fmt == 'markdown'
    docs = res.get('docs') or []
    out = []
    if md:
        out.append('## 对比 %d 个来源' % len(docs))
        out.append('')
        out.append('| # | 标题 | 字数 | 句数 | 链接 |')
        out.append('|---|---|---|---|---|')
        for i, d in enumerate(docs, 1):
            out.append('| %d | %s | %d | %d | %s |' % (
                i, d.get('title') or '(无标题)', d['chars'], d['sentences'], d['url']))
        out.append('')
    else:
        out.append('== 对比 %d 个来源 ==' % len(docs))
        for i, d in enumerate(docs, 1):
            out.append('  %d. %s  %s  %d 字 / %d 句' % (
                i, d.get('title') or '(无标题)', _short(d['url']), d['chars'], d['sentences']))
        out.append('')

    shared = res.get('shared') or []
    if shared:
        out.append('## 共有要点 (%d)' % len(shared) if md else '== 共有要点 (%d) ==' % len(shared))
        for i, s in enumerate(shared, 1):
            out.append('%s(%d 篇) %s' % ('- ' if md else '  ', len(s['urls']), s['text']))
        out.append('')

    uniq = res.get('unique') or {}
    pts = res.get('points') or {}
    out.append('## 各有侧重' if md else '== 各有侧重 ==')
    for d in docs:
        u = d['url']
        body = uniq.get(u) or []
        out.append('')
        header = '### %s' % (d.get('title') or _short(u))
        out.append(header if md else '--- %s (%s) ---' % (d.get('title') or '(无标题)', _host(u)))
        if not body:
            out.append('  (全部要点都与其他来源重合, 无独有内容)')
            continue
        for i, p in enumerate(body, 1):
            out.append('%s%d. %s' % ('- ' if md else '  ', i, p))
        # 重合掉的要点数, 便于判断"这篇是不是在抄"
        lost = len(pts.get(u) or []) - len(body)
        if lost > 0:
            out.append('  (另有 %d 条要点与其他来源重合)' % lost)
    errs = res.get('errors') or []
    if errs:
        out.append('')
        out.append('## 抓取失败' if md else '== 抓取失败 ==')
        for e in errs:
            out.append('- %s: %s' % (e['url'], e['error']) if md else '  %s: %s' % (e['url'], e['error']))
    print('\n'.join(out))


def do_compare(args, cfg):
    """抓多个 URL 并排对比; 返回 exit code"""
    from types import SimpleNamespace

    from webtool.pipeline.fetch import _fetch_one, _resolve_cli_proxy

    urls = [u for u in (getattr(args, 'urls', None) or []) if u]
    if len(urls) < 2:
        print('compare 至少要 2 个 URL', file=sys.stderr)
        return 2

    timeout = getattr(args, 'timeout', None) or 30
    # --no-proxy 时传 direct, 否则 auto (交给 rules 路由器决定)
    proxy = _resolve_cli_proxy(
        'direct' if getattr(args, 'no_proxy', False) else 'auto', cfg)
    n = max(1, int(getattr(args, 'n', 6) or 6))
    # 复用 fetch 的抓取链 (含 PDF/结构化/缓存), 只喂它需要的字段
    fa = SimpleNamespace(
        url=None, url_file=None, format='json', max_chars=getattr(args, 'max_chars', 0) or 0,
        no_cache=bool(getattr(args, 'no_cache', False)), raw=False, with_metadata=False,
        via=None, pdf_pages=None, structured=False, fields=None, links=False,
        links_same_host=True, profile=None, resume=False, mark_untrusted=False,
        agent_max_chars=8000,
    )

    docs, errors = [], []
    for u in urls:
        r = _fetch_one(u, fa, cfg, proxy, timeout)
        if not isinstance(r, dict):
            errors.append({'url': u, 'error': '抓取返回异常'})
            continue
        if r.get('error'):
            errors.append({'url': u, 'error': r['error']})
            continue
        meta, content = split_front(r.get('content') or '')
        if len(content.strip()) < _MIN_DOC:
            errors.append({'url': u,
                           'error': '正文太短 (%d 字), 可能是 404/跳转页' % len(content.strip())})
            continue
        title = r.get('title') or meta.get('title') or ''
        docs.append({'url': u, 'title': title, 'text': content})

    if len(docs) < 2:
        print('可用来源不足 2 个, 无法对比', file=sys.stderr)
        for e in errors:
            print('  %s: %s' % (e['url'], e['error']), file=sys.stderr)
        return 1

    res = build(docs, n=n)
    res['errors'] = errors
    if getattr(args, 'format', 'text') == 'json':
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        _render(res, getattr(args, 'format', 'text'))
    return 0
