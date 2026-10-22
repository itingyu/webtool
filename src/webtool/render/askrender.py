"""ask 的输出渲染 (纯函数: 数据进, 字符串出; 不 import 本仓其它层)"""


def _pick(sources, cited):
    """要列哪些来源: 有引用就只列被引的, 一条没引就全列并说明"""
    if not cited:
        return sources, False
    want = set(cited)
    return [s for s in sources if s['n'] in want], True


def render_text(out):
    lines = [out['answer'].rstrip(), '']
    used, by_model = _pick(out['sources'], out['cited'])
    if by_model:
        lines.append('参考来源')
    else:
        lines.append('参考来源 (模型未逐条标注, 下列为本次检索到的全部资料)')
    for s in used:
        lines.append('[%d] %s' % (s['n'], s['title']))
        lines.append('    %s' % s['url'])
    return '\n'.join(lines).rstrip()


def render_md(out):
    lines = [out['answer'].rstrip(), '']
    used, by_model = _pick(out['sources'], out['cited'])
    lines.append('**参考来源**' if by_model
                 else '**参考来源** (模型未逐条标注, 下列为全部资料)')
    lines.append('')
    for s in used:
        lines.append('%d. [%s](%s)' % (s['n'], s['title'], s['url']))
    return '\n'.join(lines).rstrip()


def render_ask(out, fmt='text'):
    if fmt in ('json', 'JSON'):
        import json
        return json.dumps(out, ensure_ascii=False, indent=1)
    if fmt in ('markdown', 'md'):
        return render_md(out)
    return render_text(out)
