"""跨源事件聚类: 把多个榜单里讲同一件事的条目归成一簇

rank 的卖点是"今天什么火", 但同一个热点在每个平台各出现一次 —— 微信、
百度、抖音各占一行, 看的人得自己认这是同一件事。聚类后能直接看出
"这件事占了 3 个平台的热搜", 那才是真正的舆情热度。

为什么是纯词法匹配 (不是语义模型):
  本项目没有向量模型, 语义重排走的是 BM25 (_semantic_scores)。BM25 算的是
  "跟查询词的相关度", 不是"两条标题说的是不是同一件事", 没法用来聚类。
  中文短标题 (6-20 字) 上, 字符/词元的重叠其实比语义更可靠 —— 同一条
  新闻在不同平台的标题必然共享实体词 ("红军长征" "iPhoneDuo")。

相似度: IDF 加权的词元包含度 (containment)
  containment = |A∩B| / min(|A|,|B|)
  取 min 而不是并集, 是因为长短标题都在: 一个 8 字的标题和 20 字的标题
  讲同一件事时, 短的那个才是信息量所在, 并集会把分数压到 0.2 以下。

为什么要 IDF 加权:
  不加权时 "黄豆吃多在列车连放128个闷屁" 和 "湖人22分大胜勇士" 能有 0.38
  的字符重叠 —— 全是常用字撞的, 不是同一件事。IDF 让"长征""旭日旗""闷屁"
  这类区分度高的词占主导, 常用字几乎不贡献分数。实测真实五源榜单:
  加权后这两条降到 0.26 以下, 而真同事件的能到 0.61+。

判定规则 (两个条件都满足才算同一事件):
  1. 共享词元里至少有一个"强词" —— 即在本次语料里出现得少的词
     (按文档频次占比判定, 不用 IDF 绝对值, 见 _is_strong)
  2. IDF 加权包含度 >= 0.15, 且 (强词数 >= 2 或 分数 >= 0.25)
  第 2 条的后半段是必要的: 单个强词 + 中等分数, 多半是两条不同的新闻
  恰好都提到了那个热门实体 (实测 "A股继续探底" vs "消费市场继续扩容"
  就属于这种 —— 只有"继续"一个强词, 0.18 分, 必须排除)。

聚类用并查集 (传递闭包): A~B, B~C 则 A,B,C 同簇。这符合直觉 ——
"长征"这个话题在抖音/百度/头条/微博可能各用不同措辞, 但都互相像。
"""

import math
import re
from collections import Counter

# 词元: 拉丁词 (len>=2) + CJK 连续段的 2-gram
_SEG = re.compile(r'[^a-z0-9一-鿿]+')
_LAT = re.compile(r'^[a-z0-9+#.]+$')

# 包含度下限 (IDF 加权的共享词元质量 / 较短一侧的总质量)
_MIN_SCORE = 0.15
# 单个强词时要求的更高分数 (只撞上一个强词证据不足)
_MIN_SCORE_SINGLE = 0.25


def tokenize(title):
    """标题 → 词元集合 (小写)

    CJK 段切 2-gram: 中文没空格, 2-gram 是没有分词器时最稳的近似
    ("地铁" "铁站" "站内" 能把 "地铁站内看书" 和 "地铁站" 连起来)。
    """
    out = set()
    for seg in _SEG.split((title or '').lower()):
        if not seg:
            continue
        if _LAT.match(seg):
            if len(seg) > 1:
                out.add(seg)
            continue
        if len(seg) == 1:
            out.add(seg)
            continue
        for i in range(len(seg) - 1):
            out.add(seg[i:i + 2])
    return out


def _idf_table(docs):
    """词元 → (IDF, 文档频次) (语料=本次参与聚类的所有标题)

    IDF 用语料规模算, 但"强词"的判定不能直接卡 IDF 绝对值 ——
    IDF 的量纲跟着语料大小走: 3 篇标题的语料里, 最罕见的词 IDF 也才
    log(4/2)≈0.69, 卡 2.0 的话一个强词都没有, 聚类直接瘫掉; 75 篇的
    语料里同一个词的 IDF 又完全不同。同一套阈值必须跟语料规模解耦。
    所以强词改用**文档频次占比**判定: 在语料里出现得少 = 强。

    IDF 公式取 log((n+1)/c) 而不是常见的 log((n+1)/(c+1)): 后者在词元
    出现在全部文档时 (c=n) 会算出 0, 于是"两条标题完全一样"这种最该
    判成同一事件的情况, 共享词元的总质量成了 0, 相似度直接归零。
    小语料最容易撞上这个 (2 篇相同标题 → c=n=2 → IDF 全 0)。
    """
    df = Counter()
    for ts in docs:
        df.update(ts)
    n = len(docs) or 1
    idf = {w: math.log((n + 1) / c) for w, c in df.items() if c > 0}
    return idf, df, n


def _is_strong(word, df, n):
    """词是不是"有辨识度"的强词 (跟语料规模无关)

    判据: 文档频次占语料的比例 <= 25%, 且绝对频次不超过语料的 1/4。
    小语料 (比如 3 篇) 也要能出结果, 所以下限给到 2 —— 只有 1 篇出现的词
    在 3 篇语料里既是强词, 也是唯一线索。
    """
    c = df.get(word, 0)
    if c <= 0:
        return False
    limit = max(2, math.ceil(n * 0.25))
    return c <= limit


def similarity(tok_a, tok_b, idf, df, n):
    """两标题的 (包含度, 共享强词数)"""
    if not tok_a or not tok_b:
        return 0.0, 0
    inter = tok_a & tok_b
    if not inter:
        return 0.0, 0
    strong = [w for w in inter if _is_strong(w, df, n)]
    if not strong:
        return 0.0, 0
    mass = sum(idf.get(w, 0.0) for w in inter)
    base = min(sum(idf.get(w, 0.0) for w in tok_a),
               sum(idf.get(w, 0.0) for w in tok_b))
    if base <= 0:
        return 0.0, 0
    return mass / base, len(strong)


def _linked(score, n_strong):
    """够不够格算"同一件事" """
    if score < _MIN_SCORE:
        return False
    return n_strong >= 2 or score >= _MIN_SCORE_SINGLE


def cluster_events(items, key='title'):
    """把条目按"讲的是同一件事"聚类

    items: [{title, source, ...}, ...]  (跨源混合)
    返回 [{'sources': [...], 'items': [...], 'size': n, 'source_count': m}, ...]
    只含 1 个源的簇不返回 —— 那是原榜单本身, 不是"跨源聚合"的信息。
    簇内按 (来源顺序, 原序) 保持稳定; 簇之间按 (源数, 条数, 最高分) 排序。
    """
    items = [it for it in (items or []) if (it.get(key) or '').strip()]
    if len(items) < 2:
        return []
    toks = [tokenize(it.get(key)) for it in items]
    idf, df, n_docs = _idf_table(toks)

    n = len(items)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    best = {}
    for i in range(n):
        for j in range(i + 1, n):
            sc, nstr = similarity(toks[i], toks[j], idf, df, n_docs)
            best[(i, j)] = sc
            if not _linked(sc, nstr):
                continue
            union(i, j)

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    out = []
    for members in groups.values():
        srcs = []
        for i in members:
            s = items[i].get('source')
            if s and s not in srcs:
                srcs.append(s)
        if len(srcs) < 2:
            continue
        # 簇内最高的两两相似度, 拿来排序和说明关联强度。
        # 并查集是传递闭包 (A-B、B-C 相通 ⇒ A、B、C 同簇), 所以峰值取簇内
        # 所有两两组合的最大值, 而不是只看"直接连上"的那几条边。
        peak = 0.0
        for a in range(len(members)):
            for b in range(a + 1, len(members)):
                key_ij = (members[a], members[b]) if members[a] < members[b] \
                    else (members[b], members[a])
                peak = max(peak, best.get(key_ij, 0.0))
        # 代表标题: 取簇内最长的那条 —— 短标题常常是摘要, 长标题信息更全
        rep = max(members, key=lambda i: len(items[i].get(key) or ''))
        out.append({
            'sources': srcs,
            'source_count': len(srcs),
            'size': len(members),
            'similarity': round(peak, 3),
            'title': items[rep].get(key),
            'items': [items[i] for i in members],
        })
    out.sort(key=lambda c: (-c['source_count'], -c['size'], -c['similarity']))
    return out


def summarize(clusters, max_title=60):
    """给渲染层用的一行摘要"""
    lines = []
    for c in clusters:
        titles = [((it.get('title') or '')[:max_title]) for it in c['items']]
        lines.append('  ' + ' ⟂ '.join(titles))
    return lines
