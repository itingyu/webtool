"""结果合并: 去重 + 权重排序

去重: URL 归一化 (去 utm/跟踪参数, 尾斜杠, http/https) + 标题指纹,
多引擎命中时保留信息最全的一条, 其余引擎名并入 engines 数组。
位置分 pos = Σ(base × pos_rank) / 引擎个数 —— 引擎可信度加权的简单平均
base_avg = Σ(引擎 base × 该引擎本次贡献结果数) / 总结果数   —— 批级量
raw     = prior × √(pos(1/log2(rank+1)) × base_avg) × sem((1+√BM25)/2)
weight  = raw / max(raw)   —— 批内相对分, top 恒为 1.0, 随候选数 n 变化

三因子, prior = 0 (广告) / 0.4 (低质量站 low_prior) / 0.5 (词典百科
ref_hosts) / 1.0 (其余)。原先 is_ad 走 ×0.2, 那个常数把广告留在候选里
靠排名挤出去; 判 0 语义更明确。

排完按 weight_floor 过滤 (默认 0.12): 广告 weight 必为 0 必被剔除, 该
阈值另挡掉位置分与相关性双低的尾部噪声。配 0 关闭。

low_prior 与 blocklist 的分工: 克隆官网/洗稿/需登录的站硬过滤 (拉黑无
争议); 无署名搬运、内容本身可用的站只降权 —— 硬过滤过重, 留在结果里让
用户自行取用更合理。
"""
import math
import re
from urllib.parse import urlparse, parse_qsl, urlencode

from webtool.core import urls
from webtool.core.config_data import load as _cfg_load
from webtool.core.plugins import table as _plugin_table
from webtool.filters.adfilter import is_ad
from webtool.filters.blocklist import is_blocked


def _merge_cfg():
    """merge 段配置 (ref_hosts/track_params/short_entities); mtime 热生效"""
    return _cfg_load('merge', 'filters.json')


_EN_TOKEN_RE = re.compile(r'[A-Za-z][A-Za-z0-9+#.]{2,}')


def _host_in(host, domains):
    return bool(host) and any(host == d or host.endswith('.' + d)
                              for d in domains or ())


def _domain_prior(r, query, apply_blocklist=True, blocklist=None):
    """域名先验, 四档: 黑名单 0 / 低质量站 0.4 / 词典百科 0.5 / 其余 1.0

    广告不走这里 (在调用处判 0)。

    blocklist (硬过滤站): 克隆官网、洗稿、需登录正文、纯 SEO 垃圾站 —— 判 0
    而不是在进 merge 前就剔除。先算完再按 weight 过滤, 好处是黑名单条目
    仍参与去重 (同一页被多引擎命中时能合并 engines, 不会出现"半条结果"),
    且过滤依据是最终权重而非 URL 字符串匹配。

    ref_hosts (词典/百科): query 含英文时几乎必是噪声 —— "GPT Claude
    Gemini" 命中「大(汉语文字)」是典型误报; 但对「X 是什么意思」类 query
    又是有用结果 → 不拉黑, 只降权。

    low_prior (内容可用但质量存疑的无署名搬运/云厂商社区): 硬过滤过重,
    降权后可留在结果里, 用户自行取用。

    域名表在 data/filters.json, 用户可增删。
    """
    cfg = _merge_cfg()
    url = r.get('url', '')
    if apply_blocklist and is_blocked(url, *(blocklist or (None, None))):
        return 0.0
    host = urls.host_of(url)
    if _host_in(host, cfg.get('low_prior')):
        return float(cfg.get('low_prior_value') or 0.4)
    if _EN_TOKEN_RE.search(query or '') and _host_in(host, cfg.get('ref_hosts')):
        return 0.5
    return 1.0


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


# 权重重排
def rerank(results, query, use_semantic=True, apply_blocklist=True,
          blocklist=None, stats=None, max_n=None):
    """评分排序: merge() 的排序半程, 供多轮召回复用

    每条结果最终只带 title/url/snippet/weight/rank + 引擎字段:
      engine   单引擎命中时的来源 (字符串)
      engines  精确命中同一页面时的来源数组; 交叉验证强度另按 base 加权的
               排名均值计算 (pos), 故长度为 1 不代表未被其他引擎认可
    _sem 是评分中间量, 算完即弃 —— 不进对外结果。
    """
    if not results:
        return results
    # 先重算 engines (dedupe 已合并; 单引擎直通时补齐)
    for r in results:
        if not r.get('engines'):
            r['engines'] = [r.get('engine')] if r.get('engine') else []

    if use_semantic:
        sem_scores = _semantic_scores(query, results)
    else:
        sem_scores = {i: 1.0 for i in range(len(results))}

    cred = _engine_cred()
    # 批级 base_avg: 按各引擎本次实际贡献的结果数加权; 单引擎批次退化为该引擎
    # 自身的 base。
    _cnt = {}
    for r in results:
        e = r.get('engine')
        if e:
            _cnt[e] = _cnt.get(e, 0) + 1
    _tot = sum(_cnt.values())
    base_avg = (sum(cred.get(e, 0.8) * c for e, c in _cnt.items()) / _tot
                if _tot else 0.8)
    for i, r in enumerate(results):
        # 三因子: 先验(广告/词典) × 引擎可信度加权位置 × 语义相关性
        rank = r.get('rank', 10)
        # 位置分 = (1/log2(rank+1)) × base_avg, 再开根号。
        # base_avg 是批级量 (按各引擎本次贡献数加权), 单条只用自己的 rank
        # 取对数衰减 —— 别逐引擎算 pos 再平均, 那等于把引擎可信度用两次。
        pos = 1.0 / math.log2(rank + 1) * base_avg
        raw = sem_scores[i]
        # (1+√sem)/2 : 把 BM25 分压到 [0.5, 1.0]。直接用 raw 时零命中结果被
        # 乘到 0.1 以下几乎出局, 而 BM25 分档又极粗 (要么满分要么触底),
        # 乘性放大会把噪声一起放大。压到 0.5~1 后 sem 从"一票否决"变"温和调节",
        # 位置与交叉验证主导排序, 相关性只在同档内微调。
        sem = (1.0 + math.sqrt(max(0.0, raw))) / 2 if use_semantic else 1.0
        # pos 先开根号再乘 sem: pos 的对数衰减 (rank1→rank10 差 3.4 倍)
        # 直接进权重会把长尾压死, 开根号压回接近加性的量级, sem 才得以
        # 在同等权重上参与排序。
        # prior: 广告判 0 (权重直接归零, 取代原先的 ×0.2 —— 那个常数把广告
        # 留在候选里靠排名挤出去, 判 0 语义更明确); 词典/百科页 ×0.5。
        prior = (0.0 if is_ad(r)
                 else _domain_prior(r, query, apply_blocklist, blocklist))
        w = prior * math.sqrt(pos) * sem
        r['_sem'] = round(raw, 3)      # 中间量, 排完即删
        r['_prior'] = round(prior, 3)
        r['weight'] = round(w, 4)

    # 先归一再过滤: 除以批内最高分让 weight 成为相对分 (top 恒为 1.0),
    # 随候选集大小 n 变化 —— 8 条候选时 0.47 是中游, 30 条候选时 0.47
    # 可能已在尾部, 绝对分跨 n 不可比。归一后才谈得上"比头部差多少"的阈值。
    top = max((r['weight'] for r in results), default=0.0)
    if top > 0:
        for r in results:
            r['weight'] = round(r['weight'] / top, 4)
    results.sort(key=lambda r: -r['weight'])
    # 算完再过滤: prior=0 的广告与黑名单站 weight 必为 0, 在此一并剔除 ——
    # 它们进 merge 前不做剔除, 以便参与去重 (多引擎命中的同一页能完整合并
    # engines, 不留半条结果)。weight_floor 另兜底位置分与相关性双低的尾部。
    # (原 n_zero 零分计数已无消费方, 阈值由 floor 公式直接决定)
    # 阈值按 n 动态算: n = min(用户要的条数, 去重过滤后实际条数)。
    # floor = √(pos(n) × base_avg) × 0.5, 即"排在第 n 位的结果可能拿到的
    # 最低权重" —— 低于它的说明位置与相关性双低, 属尾部噪声。
    # base_avg 已归入 pos, 此处沿用同一量纲; ×0.5 是 sem 的下限。
    # n < 3 时不启用: 候选太少时任何阈值都是噪声 (n=2 时一条正常结果就可能
    # 落在理论下界之下), 不如原样返回。
    n = len(results)
    if max_n:
        n = min(max_n, n)
    floor = (math.sqrt((1.0 / math.log2(n + 1)) * base_avg) * 0.5
             if n >= 3 else 0.0)
    kept = [r for r in results if r['weight'] > floor]
    if stats is not None:
        stats['blocked'] = sum(1 for r in results
                               if r['weight'] <= floor and r.get('_prior') == 0.0)
        stats['floor_dropped'] = len(results) - len(kept) - stats['blocked']
        stats['weight_floor'] = round(floor, 4)
    results = kept
    # 中间量与重复项一并清掉: 对外只有 engines 一个来源字段, 且恒为数组
    # (单引擎也是单元素数组 —— 形状一致, 消费方无需分支判断)
    for i, r in enumerate(results):
        r.pop('_sem', None)
        r.pop('_prior', None)
        r.pop('engine', None)
        r['rank'] = i + 1
    return results

def merge(results, query, use_semantic=True, dedupe=True,
         apply_blocklist=True, blocklist=None, stats=None, max_n=None):
    """合并多引擎结果: 去重 → 评分 → 排序

    results: [{title,url,snippet,engine,rank,is_ad?}, ...]
    返回: 排序后的结果列表, 每条带 rank/title/url/snippet/weight + 引擎字段
    """
    n_in = len(results)
    if dedupe:
        results = _dedupe(results)
    if stats is not None:
        stats['dedup_removed'] = n_in - len(results)
    # 去重产生的内部键不外泄 (json 输出干净)
    for r in results:
        r.pop('_key_u', None)
        r.pop('_key_t', None)
    return rerank(results, query, use_semantic=use_semantic,
                  apply_blocklist=apply_blocklist, blocklist=blocklist,
                  stats=stats, max_n=max_n)


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

# 语义相关性 (BM25, 零依赖)


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
