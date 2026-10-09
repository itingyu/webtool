# -*- coding: utf-8 -*-
"""结果合并: 去重 + 权重排序

去重: URL 归一化 (去 utm/跟踪参数, 尾斜杠, http/https) + 标题指纹,
     同一结果多引擎命中时保留信息最全的一条, 其他引擎作为 confirmations 计数。

排序: 混合权重 = 引擎基础分 × 跨引擎共识加成 × 归一化名次衰减
     语义向量 (可选): 本地 TF-IDF + 余弦相似度, 无需任何 API/model 下载,
     特征 = query 词袋 vs (title+snippet) 词袋, 中英文都按字符 n-gram 分词。

权重公式:
  base(e):  google=0.95, bing=0.90, baidu=0.80, sogou=0.75
  pos(e,r): 1 / log2(rank + 1)           # 第1名 1.0, 第2名 0.63, 第3名 0.5
  agree(r): 1 + 0.35 * (命中引擎数 - 1)   # 多引擎共识加成
  sem(r):   0.7 + 0.6 * cosine(query, r) # 语义相关度 0.7-1.3 乘区
  final = base * pos * agree * sem * (0.2 if is_ad else 1.0)
"""
import math
import re
from urllib.parse import urlparse, parse_qsl, urlencode

from .adfilter import is_ad

ENGINE_BASE = {'google': 0.95, 'bing': 0.90, 'baidu': 0.80, 'sogou': 0.75}

# URL 跟踪参数 (去重时忽略)
_TRACK_PARAMS = {'utm_source', 'utm_medium', 'utm_campaign', 'utm_term',
                 'utm_content', 'from', 'refer', 'refer_flag', 'fr',
                 'share_token', 'share_appid', 'vd', 'ns', 'seid', 'sc'}


def normalize_url(u):
    """URL 归一化: 去跟踪参数/host前缀/尾斜杠/fragment, 小写 host"""
    try:
        p = urlparse(u.strip())
    except Exception:
        return u
    host = p.netloc.lower().replace('www.', '', 1) if p.netloc.startswith('www.') else p.netloc.lower()
    qs = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
          if k.lower() not in _TRACK_PARAMS]
    path = p.path.rstrip('/') or '/'
    return f'{p.scheme}://{host}{path}' + (f'?{urlencode(qs)}' if qs else '')


def title_fingerprint(t):
    """标题指纹: 去空白/标点, 取前 24 字符 (中英文通用)"""
    s = re.sub(r'[\s\W_]+', '', (t or '').lower())
    return s[:24]


def merge(results, query, use_semantic=True, dedupe=True):
    """合并多引擎结果: 去重 → 评分 → 排序

    results: [{title,url,snippet,engine,rank,is_ad?}, ...]
    返回: 排序后的结果列表, 每条带 engines(命中的引擎)/weight/sem_score
    """
    if dedupe:
        results = _dedupe(results)

    if use_semantic:
        sem_scores = _semantic_scores(query, results)
    else:
        sem_scores = {i: 1.0 for i in range(len(results))}

    for i, r in enumerate(results):
        base = ENGINE_BASE.get(r.get('engine'), 0.7)
        rank = r.get('rank', 10)
        pos = 1.0 / math.log2(rank + 1)
        n_eng = len(r.get('engines', [r.get('engine')]))
        agree = 1.0 + 0.35 * (n_eng - 1)
        sem = sem_scores[i]
        w = base * pos * agree * sem
        if is_ad(r):
            w *= 0.2
        r['sem_score'] = round(sem, 3)
        r['weight'] = round(w, 4)
        r['confirmations'] = n_eng
    results.sort(key=lambda r: -r['weight'])
    for i, r in enumerate(results):
        r['rank'] = i + 1
    return results


def _dedupe(results):
    """URL 归一化 + 标题指纹双通道去重; 保留信息最全条, 合并 engines"""
    seen = {}
    out = []
    for r in results:
        key_u = normalize_url(r.get('url', ''))
        key_t = title_fingerprint(r.get('title'))
        dup_idx = None
        if key_u and key_u in seen:
            dup_idx = seen[key_u]
        elif key_t and key_t in seen:
            dup_idx = seen[key_t]
        if dup_idx is not None:
            tgt = out[dup_idx]
            if r.get('engine') not in tgt['engines']:
                tgt['engines'].append(r['engine'])
            # 补充更全的字段
            if len(r.get('snippet') or '') > len(tgt.get('snippet') or ''):
                tgt['snippet'] = r['snippet']
            if r.get('date') and not tgt.get('date'):
                tgt['date'] = r['date']
        else:
            r = dict(r)
            r['engines'] = [r.get('engine')] if r.get('engine') else []
            r['_key_u'] = key_u
            r['_key_t'] = key_t
            if key_u:
                seen[key_u] = len(out)
            if key_t:
                seen[key_t] = len(out)
            out.append(r)
    return out


# ---------------- 语义相关性 (本地 TF-IDF + 余弦, 零依赖) ----------------

def _tokenize(s):
    """中英文混合分词: 英文按词, 中文按 2-gram (零依赖, 对短查询够用)"""
    s = (s or '').lower()
    en = re.findall(r'[a-z][a-z0-9+#.]{1,}', s)
    zh = re.findall(r'[\u4e00-\u9fff]+', s)
    zhgrams = []
    for seg in zh:
        if len(seg) == 1:
            zhgrams.append(seg)
        else:
            zhgrams += [seg[i:i + 2] for i in range(len(seg) - 1)]
    return en + zhgrams


def _semantic_scores(query, results):
    """TF-IDF 余弦相似度: query vs title+snippet"""
    q_tokens = _tokenize(query)
    if not q_tokens:
        return {i: 1.0 for i in range(len(results))}
    # 文档频率
    docs = []
    for r in results:
        docs.append(_tokenize((r.get('title', '') + ' ') * 2 + ' ' + (r.get('snippet', ''))))
    n_docs = len(docs)
    df = {}
    for doc in docs:
        for t in set(doc):
            df[t] = df.get(t, 0) + 1

    def tfidf(tokens):
        tf = {}
        for t in tokens:
            tf[t] = tf.get(t, 0) + 1
        return {t: (c / len(tokens)) * math.log(1 + n_docs / (1 + df.get(t, 0)))
                for t, c in tf.items()}

    qv = tfidf(q_tokens)
    qnorm = math.sqrt(sum(v * v for v in qv.values())) or 1.0
    scores = {}
    for i, doc in enumerate(docs):
        dv = tfidf(doc)
        dot = sum(qv[t] * dv[t] for t in qv if t in dv)
        dnorm = math.sqrt(sum(v * v for v in dv.values())) or 1.0
        scores[i] = max(0.3, min(1.4, dot / (qnorm * dnorm) * 2.5 + 0.5))
    return scores
