"""compare 纯逻辑测试: 切句/相似度/要点/共有/独有/汇总"""

import sys
sys.path.insert(0, 'src')

from webtool.pipeline import compare as C

FAILED = []


def check(name, cond, detail=''):
    if cond:
        print('PASS', name)
    else:
        print('FAIL', name, detail)
        FAILED.append(name)


A = {
    'url': 'https://a.com',
    'title': '甲',
    'text': ('特斯拉第三季度交付量为 46.3 万辆，同比增长 6%。\n'
             '公司称 Model 3 与 Model Y 仍是主力车型，占总交付量的 95%。\n'
             '马斯克表示明年将推出更低价的车型，售价预计低于 2.5 万美元。\n'
             '分析师认为毛利率会继续承压，因为价格战尚未结束。'),
}
B = {
    'url': 'https://b.com',
    'title': '乙',
    'text': ('特斯拉三季度交付 46.3 万辆，同比增 6%，略低于市场预期。\n'
             '该季度产量为 47 万辆，库存因此小幅上升。\n'
             '欧洲市场需求疲软，柏林工厂产能利用率下降。\n'
             '分析师认为明年低价车型是增长关键。'),
}
D = {
    'url': 'https://c.com',
    'title': '丙',
    'text': ('完全无关的内容：今天菜市场的白菜涨到了三块钱一斤。\n'
             '摊主说今年的雨水太多，收成不好，价格还要涨。'),
}

# --- 切句 ---
s = C.sentences(A['text'])
check('切句数量', len(s) == 4, len(s))
check('切句去掉换行', all('\n' not in x for x in s))
check('短句被过滤', C.sentences('好。') == [])

# --- 相似度 ---
check('相似度: 同句=1', abs(C.sim('特斯拉交付46.3万辆', '特斯拉交付46.3万辆') - 1.0) < 1e-9)
check('相似度: 无关<0.2', C.sim('特斯拉交付46.3万辆', '今天菜市场白菜三块钱') < 0.2,
      C.sim('特斯拉交付46.3万辆', '今天菜市场白菜三块钱'))
check('相似度: 近似>0.5',
      C.sim('特斯拉三季度交付46.3万辆同比增长6%', '特斯拉三季度交付46.3万辆同比增6%') > 0.5)
check('相似度: 空输入=0', C.sim('', 'abc') == 0.0)

# --- 要点 ---
kp = C.keypoints(A['text'])
check('要点非空', len(kp) >= 2, kp)
check('要点含数字句', any('46.3' in x for x in kp))
check('要点保序', kp == sorted(kp, key=lambda x: C.sentences(A['text']).index(x)))
check('要点上限生效', len(C.keypoints(A['text'], n=2)) <= 2)
check('空文本要点为空', C.keypoints('') == [])

# --- 共有/独有 ---
docs = [A, B, D]
r = C.build(docs, n=6)
check('共有要点存在', len(r['shared']) >= 1, r['shared'])
sh = r['shared'][0]
check('共有涉及两篇', len(sh['urls']) >= 2, sh['urls'])
check('共有排在前面的是 A/B', set(sh['urls']) <= {'https://a.com', 'https://b.com'})

uniq = r['unique']
check('C 的独有要点非空', len(uniq['https://c.com']) >= 1, uniq['https://c.com'])
check('A 的独有要点含低价车型或毛利率',
      any(('低' in x or '毛利' in x) for x in uniq['https://a.com']), uniq['https://a.com'])
check('共有点不重复出现在独有里',
      not any(x in uniq['https://a.com'] for x in [sh['text']]))

# --- 汇总结构 ---
check('docs 数量', len(r['docs']) == 3)
check('docs 带 chars', all(d['chars'] > 0 for d in r['docs']))
check('docs 标题正确', r['docs'][0]['title'] == '甲')
check('单篇无共有', len(C.build([A])['shared']) == 0)

print()
print('ALL PASS' if not FAILED else 'FAILED: %d 项 -> %s' % (len(FAILED), ', '.join(FAILED)))
sys.exit(1 if FAILED else 0)
