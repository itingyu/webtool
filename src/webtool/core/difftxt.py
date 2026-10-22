"""文本差异计算 (纯函数, 不碰 IO)

给 `webtool diff` 用: 两段文本进来, 结构化差异出去。渲染在 render 层做,
这里只管"哪几行变了", 这样 text / markdown / json 三种输出共用同一份判断,
不会三种格式各算一遍、结论还不一致。

按**行**比较 (网页正文提取出来就是多行文本); 整段重排的页面行级 diff 会很难看,
所以配上相似度, 让调用方能判断"这页是不是整个改版了, 别读 diff 了"。
"""

import difflib
import re

_WS = re.compile(r'\s+')


def _norm(lines, ignore_ws):
    """行内空白归一: 只折叠空白, 不动大小写 (大小写常常是语义的)"""
    if not ignore_ws:
        return [ln.rstrip() for ln in lines]
    return [_WS.sub(' ', ln).strip() for ln in lines]


def split_lines(text):
    """正文 → 行列表; 末尾空行不算一行 (文件尾换行不该变成差异)"""
    lines = (text or '').replace('\r\n', '\n').replace('\r', '\n').split('\n')
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def compare(old, new, context=3, ignore_ws=False):
    """两段文本 → dict

    hunks: [{old_start, new_start, lines: [(op, text)]}]  op ∈ ' ', '-', '+'
    stats: {added, removed, unchanged, similarity}
    """
    a = _norm(split_lines(old), ignore_ws)
    b = _norm(split_lines(new), ignore_ws)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    hunks = []
    added = removed = same = 0
    for group in sm.get_grouped_opcodes(context):
        lines = []
        old_start = group[0][1] + 1
        new_start = group[0][3] + 1
        old_len = new_len = 0
        for tag, i1, i2, j1, j2 in group:
            old_len += i2 - i1
            new_len += j2 - j1
            if tag == 'equal':
                for k in range(i1, i2):
                    lines.append((' ', a[k]))
                    same += 1
            elif tag == 'replace':
                for k in range(i1, i2):
                    lines.append(('-', a[k]))
                    removed += 1
                for k in range(j1, j2):
                    lines.append(('+', b[k]))
                    added += 1
            elif tag == 'delete':
                for k in range(i1, i2):
                    lines.append(('-', a[k]))
                    removed += 1
            elif tag == 'insert':
                for k in range(j1, j2):
                    lines.append(('+', b[k]))
                    added += 1
        hunks.append({'old_start': old_start, 'new_start': new_start,
                      'old_len': old_len, 'new_len': new_len,
                      'lines': lines})
    return {'hunks': hunks, 'stats': {
        'added': added, 'removed': removed, 'unchanged': same,
        'similarity': round(sm.ratio(), 4),
        'old_lines': len(a), 'new_lines': len(b)}}


def unified(old, new, context=3, ignore_ws=False, label_old='旧', label_new='新'):
    """标准 unified diff 文本 (给 text/markdown 直接贴)"""
    a = _norm(split_lines(old), ignore_ws)
    b = _norm(split_lines(new), ignore_ws)
    return ''.join(difflib.unified_diff(a, b, label_old, label_new, n=context,
                                        lineterm=''))
