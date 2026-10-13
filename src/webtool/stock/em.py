"""东财 datacenter 泛化调用

`http.py` 的 `em_datacenter()` 要手拼 reportName/filter/sort。逆向出的 122 个
reportName 各有各的 filter 语法、排序列名、字段清单, 手拼必然踩 `code=9501`。

本模块把这些差异**做成配方**(`data/reverse/em_recipes.json`, 从
`东财reportName逆向.md` 机器提取), 于是:

```python
em.list_reports('龙虎榜')          # 按用途搜 reportName
em.run('RPT_DAILYBILLBOARD_DETAILSNEW',
       start_date='2026-09-01', end_date='2026-09-30')   # 变量自动填进 filter
```

配方里的 filter 是 f-string 原文, 形如 `(TRADE_DATE<='{end_date}')`; 传入同名
参数即被替换, 没传的变量会留空 —— 所以**入参名直接沿用 akshare 的入参名**,
不用另记一套。

`run()` 自动处理: 分页 (东财 pages 常上千)、排序列与 sortTypes 数量对齐、
错误码转可读提示、以及 `rename` 字段还原。
"""

import json
import os
import re

from webtool.stock.http import Http

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    'data', 'reverse')
_RECIPE = os.path.join(_DIR, 'em_recipes.json')
_MAPS = os.path.join(_DIR, 'em_maps.json')

BASE = 'https://datacenter-web.eastmoney.com/api/data/v1/get'

_cache = {}


class EmError(RuntimeError):
    """东财调用失败"""


def recipes():
    if 'r' not in _cache:
        if not os.path.exists(_RECIPE):
            raise EmError(f'配方库缺失: {_RECIPE}')
        with open(_RECIPE, encoding='utf-8') as f:
            _cache['r'] = json.load(f)
    return _cache['r']


def stats():
    r = recipes()
    return {'reports': len(r),
            'with_filter_vars': sum(1 for x in r.values() if x['filter_vars']),
            'with_rename': sum(1 for x in r.values() if x['rename']),
            'functions': len({x['func'] for x in r.values() if x['func']}),
            'sample': sorted(r)[:5]}


def get(rn):
    """取单个 reportName 的配方"""
    r = recipes()
    if rn not in r:
        near = [k for k in r if rn.upper() in k][:6]
        raise EmError(f'没有 reportName {rn}' +
                      (f'\n相近: {chr(10).join("  " + n for n in near)}'
                       if near else '\nwebtool stock em-reports 看全部清单'))
    return r[rn]


def list_reports(kw='', limit=60):
    """按用途/函数名/reportName 搜配方。空关键词返回全部。"""
    r = recipes()
    kw = (kw or '').strip()
    if not kw:
        items = [{'reportName': k, 'func': v['func'], 'use': v['use'],
                  'vars': v['filter_vars']} for k, v in r.items()]
        return {'total': len(items), 'reports': items[:limit]}
    k = kw.lower()
    hits = []
    for name, v in r.items():
        blob = f"{name} {v['func']} {v['use']} {' '.join(v['filter_vars'])}".lower()
        if k in blob:
            hits.append({'reportName': name, 'func': v['func'],
                         'use': v['use'], 'vars': v['filter_vars'],
                         'sort': v['params'].get('sortColumns', '')})
    return {'keyword': kw, 'total': len(hits), 'reports': hits[:limit]}



def maps():
    """akshare 里那些「中文入参 -> reportName 编码」的映射表。

    配方里的 filter 常写成 `(STATISTICS_CYCLE="{symbol_map[symbol]}")`,
    因为上游代码先把 `symbol="近一月"` 翻成 `"01"` 再拼进 filter。
    这里把 8 张表 (从 akshare 源码合并提取) 接上, 于是入参直接写中文即可。
    """
    if 'm' not in _cache:
        try:
            with open(_MAPS, encoding='utf-8') as f:
                _cache['m'] = json.load(f)
        except OSError:
            _cache['m'] = {}
    return _cache['m']


def map_options(kind='symbol_map'):
    """列出某张映射表的全部可选入参值"""
    return sorted(maps().get(kind, {}))



def _fill_filter(expr, values, rec_maps=None):
    """求值配方里的 filter。

    配方是从 akshare 源码抄下来的**原始字符串字面量**, 两层结构:

        "f\"(REPORTDATE='{'-'.join([date[:4], date[4:6], date[6:]])}')\""
         └─ 第 1 层: Python 源码里的字符串  └─ 第 2 层: 真正的 f-string

    所以分两步: 先 eval 第 1 层拿到 f-string 源码, 再按 f-string 语义求值第 2 层。
    变量名沿用 akshare 入参名 (symbol/start_date/date/...), 缺参数会明确报出。
    """
    if not expr:
        return None
    src = expr.strip()
    # 第 1 层: 字符串字面量 -> 里面的 f-string 源码
    try:
        if src[:1] in '"\'':
            inner = eval(src, {'__builtins__': {}}, {})        # noqa: S307
        else:
            inner = src
    except Exception:                                           # noqa: BLE001
        inner = src.strip('"\'')
    inner = inner.strip()
    if inner[:1] == 'f' and inner[1:2] in '"\'':
        inner = inner[1:]
    for _ in range(2):
        if len(inner) >= 2 and inner[0] == inner[-1] and inner[0] in '"\'':
            inner = inner[1:-1]
    if not inner:
        return None
    # 只把 {} 表达式**外面**的单引号换双引号 (f-string 内部字符串保持原样,
    # 否则 "{'-'.join(...)}" 会被改坏成 '{"-"...}' 而失去 join 语义)。
    # 注意: **不要**预先换引号。f-string 的表达式里允许混合引号,
    # 用三引号包裹后 Python 自身就能正确解析, 手工改引号反而会改坏
    # `{'-'.join(...)}` 这类片段。
    env = {k: v for k, v in values.items() if v is not None}
    # 上游的中文入参 -> 编码映射: symbol_map[symbol] 等先算成字面值
    ms = dict(maps())
    ms.update(rec_maps)                    # 配方自带的作用域映射优先
    for tbl, key in re.findall(r'\b(\w+_map)\[(\w+)\]', inner):
        table = ms.get(tbl, {})
        val = env.get(key)
        if val is None:
            raise EmError(f'缺入参 {key} (用于 {tbl})\n'
                          f'  可选值示例: {list(table)[:6]}')
        if val not in table:
            raise EmError(f'{key}="{val}" 不在 {tbl} 里\n'
                          f'  可选值: {list(table)[:10]}')
        env[tbl] = table
    # 第 2 层: f-string 语义求值
    # 用三引号包 f-string: 内容里常有双引号 (如 (X="{symbol_map[symbol]}"))
    # 源码里 filter 常是多行 f-string (三引号), 提取后仍带缩进换行;
    # 缩进换行对东财无意义, 但会破坏 eval, 所以先压成单行。
    inner = ' '.join(inner.split())
    lit = 'f"""' + inner.replace('\\', '\\\\').replace('"""', '\\"\\"\\"') + '"""'
    try:
        out = eval(lit, {'__builtins__': {}}, env)                # noqa: S307
    except Exception as e:                                       # noqa: BLE001
        need = sorted(set(re.findall(r'\b(\w+)\[', inner)))
        hint = f'; 这条需要入参: {need}' if need else ''
        if isinstance(e, NameError):
            hint = f'; 这条需要入参: {need}' if need else ''
        raise EmError(f'filter 求值失败: {inner[:110]}\n'
                      f'  {type(e).__name__}: {e}{hint}') from None
    out = str(out).replace('\\"', '"').replace("\\'", "'")
    out = re.sub(r'\(\s*\)', '', out)
    out = out.replace('""', '').strip()
    return out or None


def _sync_sort(sort, types):
    """sortColumns 有几列, sortTypes 就得有几个, 否则东财报 9501"""
    if not sort:
        return sort, types
    n = len(sort.split(','))
    if not types:
        return sort, ','.join(['-1'] * n)
    have = types.split(',')
    if len(have) < n:
        have += ['-1'] * (n - len(have))
    return sort, ','.join(have[:n])


def _run_pre(rec, values):
    """执行配方记录的入参预处理。

    上游很多函数在拼 filter 前先转日期, 例如:
        start_date = "-".join([start_date[:4], start_date[4:6], start_date[6:]])
    这些语句不在 params 里, 但直接决定 filter 的取值, 所以照做一遍。
    """
    env = {k: v for k, v in values.items() if v is not None}
    for stmt in rec.get('pre') or []:
        try:
            exec(stmt, {'__builtins__': {}}, env)      # noqa: S102 - 受限, 来自本仓配方
        except Exception:                              # noqa: BLE001,S112
            continue                                    # 预处理失败不该拖垮取数
    return env


def run(rn, max_pages=1, http=None, rename=True, **values):
    """按配方取数。`values` 用 akshare 的入参名 (symbol/start_date/...)。"""
    rec = get(rn)
    values = _run_pre(rec, values)
    p = dict(rec['params'])
    filt = _fill_filter(p.get('filter'), values, rec.get('maps'))
    sort, stypes = _sync_sort(p.get('sortColumns'), p.get('sortTypes'))
    http = http or Http()
    out, total = [], 0
    for page in range(1, max(1, int(max_pages)) + 1):
        q = {'reportName': rn,
             'columns': values.get('columns', p.get('columns') or 'ALL'),
             'pageSize': str(values.get('page_size', p.get('pageSize') or 500)),
             'pageNumber': str(page),
             'source': 'WEB', 'client': 'WEB'}
        if filt:
            q['filter'] = filt
        if sort:
            q['sortColumns'] = sort
            q['sortTypes'] = stypes
        raw = http.get(BASE, params=q)
        d = http.json(raw)
        if not d.get('success'):
            code, msg = d.get('code'), str(d.get('message'))[:150]
            hint = ''
            if code in (9501, 9201):
                hint = (f'\n  排序列/列名不对? webtool stock docs-report {rn} 查源码用的列')
            raise EmError(f'{rn} code={code}: {msg}{hint}')
        res = d.get('result') or {}
        recs = res.get('data') or []
        total = int(res.get('count') or res.get('pages') and 0 or len(recs))
        pages = int(res.get('pages') or 1)
        out.extend(recs)
        if page >= pages:
            break
    df = __import__('pandas').DataFrame(out)
    if rename and rec['rename']:
        df = df.rename(columns={k: v for k, v in rec['rename'].items()
                                if k in df.columns})
    return {'reportName': rn, 'func': rec['func'], 'use': rec['use'],
            'filter_sent': filt, 'rows': len(df), 'pages_fetched': page,
            'df': df}
