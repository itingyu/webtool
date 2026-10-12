# -*- coding: utf-8 -*-
"""结果合并: 去重 + 权重排序

去重: URL 归一化 (去 utm/跟踪参数, 尾斜杠, http/https) + 标题指纹,
多引擎命中时保留信息最全的一条, 其他引擎计 confirmations。
weight = base(引擎分) × pos(1/log2(rank+1)) × agree(1+0.35×(引擎数-1)) ×
sem(0.4+0.9×BM25归一化分) × entity(英文实体命中) × prior(词典/百科先验) ×
(0.2 if is_ad); quality 断层自适应: poor = sem < max(0.12, top×0.35)。
"""
import math
import re
from urllib.parse import urlparse, parse_qsl, urlencode

from .adfilter import is_ad


def _engine_base():
    """引擎权重表 (engine.<name>.params.base); 每次现取插件表, 清单改动即时生效"""
    from .plugins import table as _plugin_table
    return {name: spec.get('base')
            for name, spec in _plugin_table('engine').items()
            if spec.get('base')}

# ---------------- 域名先验 ----------------
# 技术性/实体 query 下, 词典/通用百科页几乎必是噪声 (如 "GPT Claude Gemini"
# 命中「大(汉语文字)」); 但对「X 是什么意思」类 query 又是好结果 → 不拉黑, 只降权。
# 域名表在 data/filters.json 的 merge 段 (ref_hosts), 用户可增删
from .config_data import load as _cfg_load

_EN_TOKEN_RE = re.compile(r'[A-Za-z][A-Za-z0-9+#.]{2,}')
_EN_WORD_RE = re.compile(r'^[A-Za-z][A-Za-z0-9+#.\-]*$')


def _merge_cfg():
    """merge 段配置 (ref_hosts/track_params/short_entities); mtime 热生效"""
    return _cfg_load('merge', 'filters.json')


def _domain_prior(r, query):
    """词典/百科先验: query 含英文实体(≥2个独立 token)时对词典/百科域名降权"""
    if not _EN_TOKEN_RE.search(query or ''):
        return 1.0
    try:
        host = (urlparse(r.get('url', '')).netloc or '').lower()
    except Exception:
        return 1.0
    if any(h == host or host.endswith('.' + h) for h in _merge_cfg().get('ref_hosts', ())):
        return 0.5
    return 1.0

# ---------------- URL 归一化 ----------------


def normalize_url(u):
    """URL 归一化: 去跟踪参数/host前缀/尾斜杠/fragment, 小写 host"""
    try:
        p = urlparse(u.strip())
    except Exception:
        return u
    track = set(_merge_cfg().get('track_params', ()))
    host = p.netloc.lower().replace('www.', '', 1) if p.netloc.startswith('www.') else p.netloc.lower()
    qs = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
          if k.lower() not in track]
    path = p.path.rstrip('/') or '/'
    return f'{p.scheme}://{host}{path}' + (f'?{urlencode(qs)}' if qs else '')


def title_fingerprint(t):
    """标题指纹: 去空白/标点, 取前 24 字符 (中英文通用)"""
    s = re.sub(r'[\s\W_]+', '', (t or '').lower())
    return s[:24]


# ---------------- 权重重排 ----------------
def rerank(results, query, use_semantic=True):
    """评分排序: merge() 的排序半程, 供多轮召回复用

    每条结果带 engines/weight/sem_score(0-1 BM25 归一化)/confirmations/quality。
    quality 断层自适应: cut = max(0.12, top×0.35), sem<cut=poor (与批内头部
    断层 → 噪声), sem>=top×0.5=good, 其余 fair。比固定阈值更能贴合每批分布。
    """
    if not results:
        return results
    # 先重算 engines (dedupe 已合并; 单引擎直通时补齐)
    for r in results:
        if not r.get('engines'):
            r['engines'] = [r.get('engine')] if r.get('engine') else []

    n_engines_used = len({r['engine'] for r in results if r.get('engine')})

    if use_semantic:
        sem_scores = _semantic_scores(query, results)
    else:
        sem_scores = {i: 1.0 for i in range(len(results))}

    for i, r in enumerate(results):
        base = _engine_base().get(r.get('engine'), 0.7)
        rank = r.get('rank', 10)
        pos = 1.0 / math.log2(rank + 1)
        n_eng = len(r['engines'])
        agree = 1.0 + 0.35 * (n_eng - 1)
        raw = sem_scores[i]
        # 排序乘区上下限 0.4-1.3
        sem = max(0.4, min(1.3, 0.4 + 0.9 * raw))
        if not use_semantic:
            sem = 1.0
        ent = 1.0
        if use_semantic:
            ent = _entity_factor(query, r)
        prior = _domain_prior(r, query)
        w = base * pos * agree * sem * ent * prior
        if is_ad(r):
            w *= 0.2
        r['sem_score'] = round(raw, 3)
        r['weight'] = round(w, 4)
        r['confirmations'] = n_eng

    results.sort(key=lambda r: -r['weight'])
    # quality: 断层自适应 — 坏结果是与批内头部断层, 而非绝对分低;
    # 0.12 下限防全垃圾批互相抬轿, 35% 相对线贴合每批分布
    sems = [r['sem_score'] for r in results]
    top = max(sems) if sems else 0.0
    cut = max(0.12, top * 0.35)
    for r in results:
        s = r['sem_score']
        if s < cut:
            r['quality'] = 'poor'
        elif s >= 0.5 * top:
            r['quality'] = 'good'
        else:
            r['quality'] = 'fair'

    for i, r in enumerate(results):
        r['rank'] = i + 1
    return results


def _entity_factor(query, r):
    """英文实体命中系数: title 精确命中 ×1.6 / snippet ×1.15 / 零命中 ×0.45

    只统计长度≥3 的独立英文 token (GPT/LLM 等短 token 单独白名单),
    至少 2 个实体 token 才启用 (避免英文单词 query 误伤)。
    """
    toks = [t for t in _EN_TOKEN_RE.findall(query or '')
            if len(t) >= 3 or t.upper() in set(_merge_cfg().get('short_entities', ()))]
    toks = [t for t in toks if _EN_WORD_RE.match(t)]
    if len(set(t.lower() for t in toks)) < 2:
        return 1.0
    title = (r.get('title') or '').lower()
    snip = (r.get('snippet') or '').lower()
    hit_title = sum(1 for t in set(t.lower() for t in toks) if t in title)
    n = len(set(t.lower() for t in toks))
    if hit_title >= 1:
        return 1.6
    hit_any = sum(1 for t in set(t.lower() for t in toks) if t in snip)
    if hit_any >= max(1, n // 2):
        return 1.15
    return 0.45


def merge(results, query, use_semantic=True, dedupe=True):
    """合并多引擎结果: 去重 → 评分 → 排序

    results: [{title,url,snippet,engine,rank,is_ad?}, ...]
    返回: 排序后的结果列表, 每条带 engines/weight/sem_score/confirmations/quality
    """
    if dedupe:
        results = _dedupe(results)
    # 去重产生的内部键不外泄 (json 输出干净)
    for r in results:
        r.pop('_key_u', None)
        r.pop('_key_t', None)
    return rerank(results, query, use_semantic=use_semantic)


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
            if r.get('engine') and r.get('engine') not in tgt['engines']:
                tgt['engines'].append(r['engine'])
            # 位置分取最优: 排得越靠前的引擎越可信
            if r.get('rank') and (not tgt.get('rank') or r['rank'] < tgt['rank']):
                tgt['rank'] = r['rank']
                if r.get('engine'):
                    tgt['engine'] = r['engine']
                for k in ('date',):
                    if r.get(k):
                        tgt[k] = r[k]
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

# ---------------- 语义相关性 (BM25, 零依赖) ----------------


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
    """BM25 相关性: query vs title×2 + snippet; 返回归一化 0-1。

    归一化分母 = query 各 token 的理论最大 idf 之和, 与候选分布无关,
    分数跨批稳定。
    """
    q_tokens = _tokenize(query)
    if not q_tokens:
        return {i: 1.0 for i in range(len(results))}
    k1, b = 1.2, 0.75
    docs = []
    for r in results:
        docs.append(_tokenize((r.get('title', '') + ' ') * 2 + ' ' + (r.get('snippet', ''))))
    n_docs = len(docs)
    avgdl = sum(len(d) for d in docs) / n_docs or 1
    df = {}
    for doc in docs:
        for t in set(doc):
            df[t] = df.get(t, 0) + 1

    def idf(t):
        return math.log(1 + (n_docs - df.get(t, 0) + 0.5) / (df.get(t, 0) + 0.5))

    uniq_q = set(q_tokens)
    max_s = sum(idf(t) for t in uniq_q) or 1.0
    scores = {}
    for i, doc in enumerate(docs):
        tf = {}
        for t in doc:
            tf[t] = tf.get(t, 0) + 1
        s = 0.0
        for t in uniq_q:
            if t not in tf:
                continue
            s += idf(t) * (tf[t] * (k1 + 1)) / (tf[t] + k1 * (1 - b + b * len(doc) / avgdl))
        scores[i] = max(0.0, min(1.0, s / max_s))
    return scores
