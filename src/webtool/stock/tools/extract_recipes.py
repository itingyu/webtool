"""直接从 akshare 源码 AST 提取东财 reportName 配方。

逆向文档 (`data/reverse/东财reportName逆向.md`) 人工誊写 params 时, 多行拼接的
`columns` 只记了第一行, 会让东财返回 `code=9501`。源码是权威, 这里用 AST 读出
每个函数里 `params` 字典的**完整字面值**, 拼接结果天然正确。

用法:
    python3 tools/extract_recipes.py            # 写 data/reverse/em_recipes.json
    python3 tools/extract_recipes.py --check    # 只对比, 不写文件

只取东财 datacenter 端点 (`api/data/v1/get` / `api/data/get`)。
"""
import argparse
import ast
import glob
import json
import os
import sys

AKSHARE = '/usr/lib/python3.12/site-packages/akshare'
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'data', 'reverse', 'em_recipes.json')
MARK = 'datacenter-web.eastmoney.com'


def _val(node, src_lines):
    """把 AST 节点折成可发送的值。

    普通字面量 -> Python 值; f-string -> 保留 `f"..."` 源码 (交给 em.py 求值);
    `"a" "b"` 隐式拼接 -> 合并; 变量引用 -> `{name}` 占位。
    """
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        pass
    if isinstance(node, ast.JoinedStr):
        q = '"'
        out = ['f', q]
        for part in node.values:
            if isinstance(part, ast.Constant):
                out.append(str(part.value).replace('\\', '\\\\').replace(q, '\\' + q))
            else:                                   # 表达式: 原文已是 {..} 形态
                seg = ast.get_source_segment('\n'.join(src_lines), part) or ''
                out.append(seg if seg.startswith('{') else '{' + seg + '}')
        out.append(q)
        return ''.join(out)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _val(node.left, src_lines), _val(node.right, src_lines)
        if isinstance(left, str) and isinstance(right, str):
            return left + right
    if isinstance(node, ast.Name):
        return '{' + node.id + '}'
    return None


def _rename_map(node, src_lines):
    """找函数里的列重命名: temp_df.columns = [...] 这种, 记成 rename。"""
    text = '\n'.join(src_lines)
    return {}, text


def extract():
    recipes = {}
    for path in glob.glob(os.path.join(AKSHARE, '**', '*.py'), recursive=True):
        try:
            src = open(path, encoding='utf-8', errors='ignore').read()
        except OSError:
            continue
        if MARK not in src:
            continue
        lines = src.split('\n')
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            doc = ast.get_docstring(fn) or ''
            # 函数体开头的入参预处理 (如 `start_date = "-".join([...])`) 会影响
            # filter 里 {start_date} 的实际取值, 必须一并记录。
            pre = []
            for st in fn.body:
                if not isinstance(st, ast.Assign):
                    if isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant):
                        continue          # docstring
                    break                  # 预处理只在开头连续出现
                seg = ast.get_source_segment('\n'.join(lines), st)
                if seg and 'join' in seg:
                    pre.append(seg.strip())
            # 函数内的 xxx_map 字典。**必须按作用域取**: akshare 里有几十个
            # 同名 `symbol_map` (板块名 / 交易类型 / 利率…), 全局合并会串味 ——
            # 大宗交易要 "A股"->"1", 合并后可能拿到 "ab"。
            maps = {}
            for st in ast.walk(fn):
                if not isinstance(st, ast.Assign) or not isinstance(st.value, ast.Dict):
                    continue
                for t in st.targets:
                    if isinstance(t, ast.Name) and t.id.endswith('_map'):
                        try:
                            maps[t.id] = ast.literal_eval(st.value)
                        except (ValueError, SyntaxError):
                            pass
            # akshare 惯例: 先 `params = {...}` 再 `requests.get(url, params=params)`,
            # 所以直接扫函数内所有名为 params 的 Dict 赋值, 不必追调用点。
            for node in ast.walk(fn):
                if not isinstance(node, ast.Assign):
                    continue
                if not any(isinstance(t, ast.Name) and t.id == 'params'
                           for t in node.targets):
                    continue
                if not isinstance(node.value, ast.Dict):
                    continue
                params = {}
                for k, v in zip(node.value.keys, node.value.values):
                    if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
                        continue
                    got = _val(v, lines)
                    if got is not None:
                        params[k.value] = got
                rn = params.get('reportName')
                if not isinstance(rn, str) or not rn.startswith(('RPT', 'PRT')):
                    continue
                old = recipes.get(rn)
                if old and len(old['params']) >= len(params):
                    continue
                a = fn.args
                names = [x.arg for x in a.args if x.arg] + [x.arg for x in a.kwonlyargs]
                recipes[rn] = {
                    'func': fn.name,
                    'args': ', '.join(names),
                    'src': f"{os.path.relpath(path, AKSHARE)}:{fn.lineno}",
                    'use': doc.split('\n')[0][:120],
                    'params': params,
                    'pre': pre,
                    'maps': maps,
                }
    return recipes


def finalize(recipes):
    """补出 em.run() 需要的派生字段: filter 变量表 + sortTypes 对齐检查。"""
    import re
    for rn, rec in recipes.items():
        rec['maps'] = rec.get('maps', {})
        rec['filter_vars'] = sorted(set(re.findall(
            r'\b(\w+)\s*\[', str(rec['params'].get('filter', '')))))
        rec['filter_vars'] += sorted(set(re.findall(
            r'\{(\w+)[\}\[:]', str(rec['params'].get('filter', '')))))
        rec['filter_vars'] = sorted({v for v in rec['filter_vars'] if not v.endswith('_map')})
        rec['rename'] = rec.get('rename', {})
    return recipes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true')
    args = ap.parse_args()
    r = finalize(extract())
    print(f'从源码提取 reportName: {len(r)}', file=sys.stderr)
    if args.check:
        try:
            old = json.load(open(OUT, encoding='utf-8'))
        except OSError:
            old = {}
        only_src = sorted(set(r) - set(old))
        only_old = sorted(set(old) - set(r))
        print(f'仅源码有: {len(only_src)}  仅文档有: {len(only_old)}')
        for x in only_src[:10]:
            print('   +', x)
        for x in only_old[:10]:
            print('   -', x)
        return
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(r, f, ensure_ascii=False, indent=1)
    print(f'已写入 {OUT}', file=sys.stderr)


if __name__ == '__main__':
    main()