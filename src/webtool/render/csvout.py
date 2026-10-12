"""CSV 输出: 结果集导给 Excel/pandas

与 json/text/markdown 并列的第四种格式。列固定, 取并集后按出现顺序排,
缺列留空 —— 保证下游 pandas.read_csv 的列稳定, 不会因某条结果少个字段就错位。
"""
import csv
import io
import sys

# 固定列序: 身份在前, 溯源在后。sources_data 之类嵌套结构不进 CSV, 见 _flat
COLUMNS = ['rank', 'source', 'name', 'title', 'url', 'desc', 'origin', 'default',
           'snippet', 'engine', 'engines',
           'sem_score', 'weight', 'confirmations', 'quality', 'date',
           'hot', 'hot_value', 'score', 'stars', 'answers', 'comments', 'label']

# 嵌套/长字段不进 CSV: 拆成纯文本反而不好用, 需要时用 -f json
_SKIP = {'engines'}


def _flat(v):
    """列表/字典转紧凑文本; None → 空串"""
    if v is None:
        return ''
    if isinstance(v, list):
        return '|'.join(str(x) for x in v)
    if isinstance(v, dict):
        return '|'.join(f'{k}={val}' for k, val in v.items())
    return v


def rows_of(out, kind):
    """按 kind 取出待导出的行; 与 render._render_search 同一数据源"""
    if kind == 'rank':
        # rank 的结果按源分组在 sources_data, CSV 是平表 → 拍平并补 source 列
        flat = []
        for src, items in (out.get('sources_data') or {}).items():
            for r in items or []:
                row = dict(r)
                row.setdefault('source', src)
                row.setdefault('rank', len(flat) + 1)
                flat.append(row)
        return flat
    if kind == 'fetch':
        res = out.get('results')
        return res if isinstance(res, list) else [out]
    return out.get('results') or []


def render(out, kind):
    """打印 CSV 到 stdout (由 cli 的 emit 统一接 -o 落盘)"""
    rows = rows_of(out, kind)
    if not rows:
        return
    buf = io.StringIO()
    # 列序 = COLUMNS 里本数据集真出现的列 (保持固定相对次序) + 其余按首次出现顺序追加。
    # 管理命令 (engines/plugins) 的字段与搜索结果完全不同, 硬塞 19 列会全空 ——
    # 只输出实际有值的列, 下游 read_csv 拿到的表头才有意义。
    cols = [c for c in COLUMNS if any(r.get(c) not in (None, '', [], {}) for r in rows)]
    extra = []
    seen = set(cols)
    for r in rows:
        for k in r:
            if k not in seen and k not in _SKIP and r.get(k) not in (None, '', [], {}):
                seen.add(k)
                extra.append(k)
    cols = cols + extra
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction='ignore')
    w.writeheader()
    for r in rows:
        w.writerow({c: _flat(r.get(c)) for c in cols})
    sys.stdout.write(buf.getvalue())
