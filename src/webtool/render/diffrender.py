"""diff 输出渲染 (纯函数: 结果 dict 进, 字符串出)"""


def _summary(res, la, lb):
    s = res['stats']
    head = '%s  →  %s' % (la, lb)
    if not res['hunks']:
        return head + '\n无差异'
    pct = s['similarity'] * 100
    return '%s\n+%d 行  -%d 行  相同 %d 行  相似度 %.1f%%' % (
        head, s['added'], s['removed'], s['unchanged'], pct)


def render_text(res, la, lb, max_lines=400):
    out = [_summary(res, la, lb), '']
    n = 0
    for h in res['hunks']:
        out.append('@@ -%d,%d +%d,%d @@' % (h['old_start'], h['old_len'], h['new_start'], h['new_len']))
        for op, text in h['lines']:
            if n >= max_lines:
                out.append('… 差异过长已截断 (用 -f json 取全量)')
                return '\n'.join(out)
            out.append('%s %s' % (op, text))
            n += 1
    return '\n'.join(out).rstrip()


def render_md(res, la, lb, max_lines=400):
    out = ['**%s**' % _summary(res, la, lb).replace('\n', '  \n'), '']
    if not res['hunks']:
        return out[0]
    out.append('```diff')
    n = 0
    for h in res['hunks']:
        out.append('@@ -%d,%d +%d,%d @@' % (h['old_start'], h['old_len'], h['new_start'], h['new_len']))
        for op, text in h['lines']:
            if n >= max_lines:
                out.append('… 差异过长已截断')
                out.append('```')
                return '\n'.join(out)
            out.append('%s %s' % (op, text))
            n += 1
    out.append('```')
    return '\n'.join(out)


def render_diff(res, fmt, la='旧', lb='新', max_lines=400):
    """res 需含 hunks/stats; text / markdown / json"""
    if fmt == 'json':
        import json
        return json.dumps(dict(res, old=la, new=lb), ensure_ascii=False,
                          indent=1)
    if fmt in ('markdown', 'md'):
        return render_md(res, la, lb, max_lines)
    return render_text(res, la, lb, max_lines)
