"""跨源事件聚类 (pipeline/events.py) 单元测试 — 全本地, 不碰外网。

聚类要求共享 token 里至少有一个是稀有的, 否则会误并。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from webtool.pipeline.events import (  # noqa: E402
    cluster_events, tokenize, similarity, _idf_table)

FAILED = []


def ck(cond, label):
    if cond:
        print(f'PASS {label}')
    else:
        FAILED.append(label)
        print(f'FAIL {label}')


def items(pairs):
    return [{'title': t, 'source': s, 'url': f'https://x/{i}'}
            for i, (s, t) in enumerate(pairs)]


# === 1. 同源不聚 ===
r = cluster_events(items([
    ('zhihu', '南京警方回应旭日旗留学生事件'),
    ('zhihu', '南京旭日旗留学生后续通报'),
]))
ck(len(r) == 0, '同源不聚成跨源事件')

# === 2. 同一事件跨源聚成 1 簇 ===
r = cluster_events(items([
    ('zhihu', '南京警方回应旭日旗留学生事件'),
    ('toutiao', '南京旭日旗留学生后续通报'),
    ('baidu', '完全无关的另一条内容'),
]))
ck(len(r) == 1, '同一事件跨源聚成 1 簇 (实得 %d)' % len(r))
if r:
    ck(r[0]['source_count'] == 2, '簇涉及 2 个平台 (实得 %d)' % r[0]['source_count'])
    ck(r[0]['size'] == 2, '簇内 2 条 (实得 %d)' % r[0]['size'])
    ck(set(r[0]['sources']) == {'zhihu', 'toutiao'},
       '簇平台是 zhihu+toutiao (实得 %s)' % r[0]['sources'])
    ck(bool(r[0].get('title')), '簇有代表标题')
    ck(r[0]['similarity'] > 0, '簇有相似度分数')
    ck(len(r[0]['items']) == 2, '簇内条目完整')

# === 3. 完全无关的不聚 ===
r = cluster_events(items([
    ('zhihu', '南京警方回应旭日旗留学生事件'),
    ('toutiao', '今日股市收盘三大指数集体上涨'),
]))
ck(len(r) == 0, '无关标题不聚 (实得 %d)' % len(r))

# === 4. 只跨源同名才聚 (同源同名不算) ===
r = cluster_events(items([
    ('zhihu', '某公司发布新款旗舰手机'),
    ('toutiao', '某公司发布新款旗舰手机'),
]))
ck(len(r) == 1, '跨源同名聚成 1 簇 (实得 %d)' % len(r))

# === 5. 按平台数排序 ===
r = cluster_events(items([
    ('a', '南京警方回应旭日旗留学生事件'),
    ('b', '南京旭日旗留学生后续通报'),
    ('c', '南京旭日旗留学生最新进展通报'),
    ('x', '完全无关的股市收盘消息内容'),
]))
ck(len(r) >= 1, '至少 1 簇 (实得 %d)' % len(r))
if r:
    ck(r[0]['source_count'] >= 2, '最大的簇跨 >=2 平台')

# === 6. 空输入不炸 ===
ck(cluster_events([]) == [], '空输入返回空')
ck(cluster_events([{'title': '无源条目'}]) == [], '单条无跨源返回空')

# === 7. 缺 title 不炸 ===
r = cluster_events([{'source': 'a', 'title': None},
                    {'source': 'b', 'title': None}])
ck(isinstance(r, list), 'title 为 None 不炸')

# === 8. 中文切 2-gram ===
t = set(tokenize('新闻发布'))
ck(any('发布' in x for x in t), '中文切 2-gram')

# === 9. similarity 边界: 共享稀有词才算 ===
tok_a = set(tokenize('南京警方回应旭日旗留学生事件'))
tok_b = set(tokenize('南京旭日旗留学生后续通报'))
idf, df, n_docs = _idf_table([tok_a, tok_b])
sc, nstr = similarity(tok_a, tok_b, idf, df, n_docs)
ck(sc > 0, '相关标题相似度 > 0 (实得 %.3f)' % sc)
ck(nstr >= 1, '共享稀有词计数 >= 1 (实得 %d)' % nstr)

# === 10. 语料规模无关性 ===
# 同一个标题对, 在 3 篇语料和 20 篇语料里都该算出相似度 > 0。
# 强词判定若卡 IDF 绝对值, 小语料里 IDF 量纲不同会直接判不出强词。
tok_c = set(tokenize('完全无关的股市收盘消息内容'))
small_idf, small_df, small_n = _idf_table([tok_a, tok_b, tok_c])
sc_small, ns_small = similarity(tok_a, tok_b, small_idf, small_df, small_n)
ck(sc_small > 0, '小语料 (3篇) 也能算出相似度 (实得 %.3f)' % sc_small)
ck(ns_small >= 1, '小语料也能认出强词 (实得 %d)' % ns_small)

big_docs = [tok_a, tok_b] + [set(tokenize(f'无关内容{i} {i}')) for i in range(18)]
big_idf, big_df, big_n = _idf_table(big_docs)
sc_big, ns_big = similarity(tok_a, tok_b, big_idf, big_df, big_n)
ck(sc_big > 0, '大语料 (20篇) 同样能算出 (实得 %.3f)' % sc_big)
ck(ns_big >= 1, '大语料也能认出强词 (实得 %d)' % ns_big)

print()
if FAILED:
    print('%d FAILED' % len(FAILED))
    for f in FAILED:
        print('  -', f)
    sys.exit(1)
print('ALL PASS')
