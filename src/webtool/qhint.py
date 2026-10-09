# -*- coding: utf-8 -*-
"""召回质量诊断: 检测低质量结果集并生成 query 优化建议

原则: 不自动改写 query — 改写可能把用户意图改出歧义 (改词权在用户),
只做两件事:
  1. need_retry 判定结果集是否整体与 query 脱节 (sem_score 绝对值过低)
  2. build_hint 生成一句话建议, 交由输出层提醒用户
"""
import re

_EN_TOKEN_RE = re.compile(r'[A-Za-z][A-Za-z0-9+#.\-]{1,}')


def need_retry(sem_scores):
    """低质量判定: 最高 sem<0.30, 或 ≥3 条均值<0.18 → 触发建议

    阈值依据: 中文 2-gram 命中下正常相关页普遍 ≥0.3, 只有
    「实体全不沾边」的泛匹配页 (节假日/词典/百科) 才会整体低于此线。
    """
    if not sem_scores:
        return False
    vals = list(sem_scores.values())
    if max(vals) < 0.30:
        return True
    return len(vals) >= 3 and sum(vals) / len(vals) < 0.18


def build_hint(query, results):
    """按 query 特征生成建议 (不改写, 只提醒)"""
    q = (query or '').strip()
    tips = []
    if len(q) > 20:
        tips.append('缩短 query, 只留「核心实体 + 意图词」')
    if _EN_TOKEN_RE.search(q):
        tips.append('英文实体单独成词, 别埋在长中文句里')
    if not tips:
        tips.append('换更通用的领域词重试')
    return '召回质量低: ' + '; '.join(tips)
