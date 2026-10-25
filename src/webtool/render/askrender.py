"""ask 的输出渲染 (纯函数: 数据进, 字符串出; 不 import 本仓其它层)"""

def _pick(sources, cited):
    """要列哪些来源: 有引用就只列被引的, 一条没引就全列并说明"""
    if not cited:
        return sources, False
    want = set(cited)
    return [s for s in sources if s['n'] in want], True

def render_sources(out, fmt='text'):
    """只渲染来源段 (正文已实时流出去时补这一段)"""
    md = fmt in ('markdown', 'md')
    used, by_model = _pick(out['sources'], out['cited'])
    if md:
        lines = ['**参考来源**' if by_model
                 else '**参考来源** (模型未逐条标注, 下列为全部资料)', '']
        for s in used:
            lines.append('%d. [%s](%s)' % (s['n'], s['title'], s['url']))
    else:
        lines = ['参考来源' if by_model
                 else '参考来源 (模型未逐条标注, 下列为本次检索到的全部资料)']
        for s in used:
            lines.append('[%d] %s' % (s['n'], s['title']))
            lines.append('    %s' % s['url'])
    return '\n'.join(lines)

def render_text(out):
    return out['answer'].rstrip() + '\n\n' + render_sources(out, 'text')

def render_md(out):
    return out['answer'].rstrip() + '\n\n' + render_sources(out, 'markdown')

def render_ask(out, fmt='text'):
    if fmt in ('json', 'JSON'):
        import json
        return json.dumps(out, ensure_ascii=False, indent=1)
    if fmt in ('markdown', 'md'):
        return render_md(out)
    return render_text(out)
