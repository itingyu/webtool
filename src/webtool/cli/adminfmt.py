"""管理命令 (engines/plugins/cache/blocklist/config) 的输出格式适配

这些命令的 `-f` 支持: 捕获它们吐出的 JSON,
按请求格式重新渲染 —— 让 agent 用同一套 `-f json/text/markdown` 读所有子命令。

命令内部格式不统一 (有 print(json) 有 print(文本)), 这里不猜:
拿不到合法 JSON 就原样透传, 保持现状不倒退。
"""
import json

def adapt(raw, fmt, kind='admin'):
    """把命令原始输出按 fmt 重新渲染, 返回 str (供 emit 落盘/打印)。

    raw: 命令内部 print 出来的文本
    fmt: 已归一化的格式名; None/空 → 原样返回
    """
    if not fmt or fmt == 'json':
        return raw
    data = _try_json(raw)
    if data is None:
        # 命令输出的是人类可读文本而非 JSON, 无从转格式 → 原样透传
        return raw
    if not isinstance(data, (dict, list)):
        # config get 打印的是 JSON 标量 (如 "en-US"); 塞进表格会渲染成
        # (空), 直接输出值本身
        return str(data)
    if fmt == 'markdown':
        return _to_md(_rows(data))
    if fmt == 'text':
        return _to_text(_rows(data))
    return raw


def _try_json(raw):
    s = (raw or '').strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return None


def _rows(data):
    """统一成 [{...}, ...] 供 text/markdown 表格渲染消费

    plugins list 这类是 {kind: [{name,source}, ...]} 的两层结构, 直接当一行
    会把整个列表塞进单元格 → 展平成 {kind, name, source} 的平表。
    """
    if isinstance(data, list):
        # 标量列表 (如 config get verify_hosts → ["a.com"]) 不能按 dict 行
        # 过滤, 否则全被滤空渲染成 (空); 包成 {'value': v} 走同一套渲染
        return [r if isinstance(r, dict) else {'value': r} for r in data]
    if isinstance(data, dict):
        # 全部值都是 list → 两层结构, 展平
        if data and all(isinstance(v, list) for v in data.values()):
            flat = []
            for kind, items in data.items():
                for it in items:
                    row = dict(it) if isinstance(it, dict) else {'value': it}
                    row.setdefault('kind', kind)
                    flat.append(row)
            return flat
        return [data]
    return []


def _to_text(data):
    if isinstance(data, list):
        lines = []
        for i, r in enumerate(data, 1):
            lines.append(f"[{i}] " + ' | '.join(f'{k}: {v}' for k, v in r.items()))
        return '\n'.join(lines) if lines else '(空)'
    if isinstance(data, dict):
        return '\n'.join(f'{k}: {v}' for k, v in data.items())
    return str(data)


def _to_md(data):
    if isinstance(data, list) and data and all(isinstance(r, dict) for r in data):
        cols = []
        for r in data:
            for k in r:
                if k not in cols:
                    cols.append(k)
        out = ['| ' + ' | '.join(cols) + ' |',
               '|' + '|'.join(['---'] * len(cols)) + '|']
        for r in data:
            out.append('| ' + ' | '.join(str(r.get(c, '')).replace('|', '\\|')
                                        for c in cols) + ' |')
        return '\n'.join(out)
    if isinstance(data, dict):
        return '\n'.join(f'- **{k}**: {v}' for k, v in data.items())
    return str(data)
