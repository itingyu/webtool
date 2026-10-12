"""结果合并: 去重 + 权重排序

去重: URL 归一化 (去 utm/跟踪参数, 尾斜杠, http/https) + 标题指纹,
多引擎命中时保留信息最全的一条, 其余引擎名并入 engines 数组。
位置分 pos = mean over engines( base(引擎可信度) / log2(该引擎的 rank+1) )
weight = √pos × sem((1+√BM25归一化分)/2, ∈[0.5,1]) × (0.2 if is_ad)

两因子。原先 agree=1+0.15×(引擎数-1) 按引擎个数线性加成, 把"命中引擎多"
与"引擎可信"混为一谈, 已由 pos 内的 base 加权取代。
"""
import math
import re
from urllib.parse import urlparse, parse_qsl, urlencode

from webtool.core import urls
from webtool.core.config_data import load as _cfg_load
from webtool.core.plugins import table as _plugin_table
from webtool.filters.adfilter import is_ad


def _merge_cfg():
    """merge 段配置 (ref_hosts/track_params/short_entities); mtime 热生效"""
    return _cfg_load('merge', 'filters.json')


def _engine_cred():
    """引擎可信度表 name -> base (plugins.json 声明, 缺省 0.8)"""
    try:
        t = _plugin_table('engine')
        return {n: float(s.get('base') or 0.8) for n, s in t.items()}
    except Exception:
        return {}


def normalize_url(u):
    """URL 归一化: 去跟踪参数/host前缀/尾斜杠/fragment, 小写 host"""
    try:
        p = urlparse(u.strip())
    except Exception:
        return u
    track = set(_merge_cfg().get('track_params', ()))
    host = urls.host_of(u)
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

    每条结果最终只带 title/url/snippet/weight/rank + 引擎字段:
      engine   单引擎命中时的来源 (字符串)
      engines  多引擎命中时的来源数组 (交叉验证, 长度即验证数)
    sem_score/quality/confirmations 是评分中间量, 算完即弃 —— 不进对外结果。
    quality 判据: cut = max(0.12, top×0.35), sem<cut 视为与批内头部断层(噪声)。
    """
    if not results:
        return results
    # 先重算 engines (dedupe 已合并; 单引擎直通时补齐)
    for r in results:
        if not r.get('engines'):
            r['engines'] = [r.get('engine')] if r.get('engine') else []
        if '_ranks' not in r:                # dedupe 直通路径 (--no-dedupe) 补齐
            e, rk = r.get('engine'), r.get('rank')
            r['_ranks'] = {e: rk} if e and rk else {}

    if use_semantic:
        sem_scores = _semantic_scores(query, results)
    else:
        sem_scores = {i: 1.0 for i in range(len(results))}

    cred = _engine_cred()
    for i, r in enumerate(results):
        # 两因子: 引擎可信度加权排名位置 × 语义相关性。
        # 曾有 ent(英文实体)/prior(词典域名降权) 两项, 实测对排序几乎无影响
        # (prior 的 ref_hosts 全是国内词典, 英文 query 基本不命中), 已撤除。
        # 曾撤除的 base 现在回来了 —— 不是当独立因子, 而是作为位置分的权重。
        rank = r.get('rank', 10)
        # 位置分 = 各引擎 (可信度 × 自身 pos) 的均值, 再开根号。
        # 原式 pos(全局最优 rank) × agree(1+0.15×(引擎数-1)) 有两处失真:
        #   1) 只用最优 rank, 丢掉其余引擎的排名信息;
        #   2) agree 按引擎个数线性加成, 把"多"和"可信"混为一谈 ——
        #      搜狗+百度 双命中拿 1.15 倍加成, 不如 google 单命中, 但
        #      后者反而没有任何加成。改按 base 加权后两者自然分出高下。
        eranks = r.get('_ranks') or {}
        if not eranks and r.get('engine') and rank:
            eranks = {r['engine']: rank}
        acc = sum(cred.get(en, 0.8) / math.log2(rk + 1) for en, rk in eranks.items())
        pos = acc / len(eranks) if eranks else 1.0 / math.log2(rank + 1)
        raw = sem_scores[i]
        # (1+√sem)/2 : 把 BM25 分压到 [0.5, 1.0]。直接用 raw 时零命中结果被
        # 乘到 0.1 以下几乎出局, 而 BM25 分档又极粗 (要么满分要么触底),
        # 乘性放大会把噪声一起放大。压到 0.5~1 后 sem 从"一票否决"变"温和调节",
        # 位置与交叉验证主导排序, 相关性只在同档内微调。
        sem = (1.0 + math.sqrt(max(0.0, raw))) / 2 if use_semantic else 1.0
        # pos 先开根号再乘 sem: pos 的对数衰减 (rank1→rank10 差 3.4 倍)
        # 直接进权重会把长尾压死, 开根号压回接近加性的量级, sem 才得以
        # 在同等权重上参与排序。
        w = math.sqrt(pos) * sem
        if is_ad(r):
            w *= 0.2
        r['_sem'] = round(raw, 3)      # 中间量, 排完即删
        r['weight'] = round(w, 4)

    results.sort(key=lambda r: -r['weight'])
    # 中间量与重复项一并清掉: 对外只有 engines 一个来源字段, 且恒为数组
    # (单引擎也是单元素数组 —— 形状一致, 消费方无需分支判断)
    for i, r in enumerate(results):
        r.pop('_sem', None)
        r.pop('_ranks', None)
        r.pop('engine', None)
        r['rank'] = i + 1
    return results

def merge(results, query, use_semantic=True, dedupe=True):
    """合并多引擎结果: 去重 → 评分 → 排序

    results: [{title,url,snippet,engine,rank,is_ad?}, ...]
    返回: 排序后的结果列表, 每条带 rank/title/url/snippet/weight + 引擎字段
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
            # 记下每个引擎各自的 rank: 重排要按引擎可信度分别算 pos 再取均值,
            # 只留全局最优 rank 会丢信息 (bing 第1 与 sogou 第2 的可信度不同)
            if r.get('engine') and r.get('rank'):
                tgt['_ranks'][r['engine']] = r['rank']
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
            r['_ranks'] = ({r['engine']: r['rank']}
                           if r.get('engine') and r.get('rank') else {})
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
