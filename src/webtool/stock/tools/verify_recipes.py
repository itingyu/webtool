"""批量验证东财 reportName 配方的真实可用率。

入参按 `args` (akshare 函数签名) 采样 —— 不是 `filter_vars` (后者是函数体内
派生出来的名字, 如 `start_date_str`), 否则 pre 预处理会失效。

用法:
    python3 tools/verify_recipes.py            # 全量
    python3 tools/verify_recipes.py RPT_LICO   # 只测匹配的
    python3 tools/verify_recipes.py --pages 3  # 每个配方翻 3 页
"""
import argparse
import json
import os
import re
import sys
import warnings

warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

from webtool.stock.em import EmError, maps, recipes, run      # noqa: E402

MAPS = maps()
DATE_ARG = re.compile(r'date|time|period|month|year', re.I)


def sample_value(name, table):
    """给一个入参名挑个大概能用的值。优先用映射表里的中文枚举。"""
    if table:
        for k in table:
            if isinstance(k, str):
                return k
    if DATE_ARG.search(name):
        return '20260930'
    if name in ('symbol', 'code', 'stock_code', 'secu_code'):
        return '600519'
    if name == 'market':
        return '沪市'
    return '20260930'


def build_kwargs(rec):
    kw = {}
    tbl = rec.get('map_hint') or {}
    for a in (rec['args'].split(',') if rec['args'] else []):
        a = a.strip()
        if not a:
            continue
        kw[a] = sample_value(a, tbl.get(a))
    return kw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pattern', nargs='?', default='')
    ap.add_argument('--pages', type=int, default=1)
    ap.add_argument('--out', default='')
    args = ap.parse_args()

    # filter 里出现的 xxx_map[yyy] 指出入参该取哪张表的值。**必须用配方自带的
    # 作用域映射**: akshare 里有几十个同名 symbol_map, 用全局表会采样到别的
    # 模块的枚举值 (如大宗交易要 "A股"->"1", 却采到债券的 "中国1年期国债")。
    all_rec = recipes()
    for rn, rec in all_rec.items():
        hint = {}
        for tbl, key in re.findall(r'\b(\w+_map)\[(\w+)\]', str(rec['params'].get('filter', ''))):
            hint[key] = rec.get('maps', {}).get(tbl) or MAPS.get(tbl, {})
        rec['map_hint'] = hint

    ok, empty, err = [], [], []
    for rn, rec in all_rec.items():
        if args.pattern and args.pattern.lower() not in rn.lower():
            continue
        kw = build_kwargs(rec)
        try:
            r = run(rn, max_pages=args.pages, **kw)
            ok.append((rn, r['rows'], len(r['df'].columns)))
            print(f"OK      {rn[:46]:46s} rows={r['rows']:5d} cols={len(r['df'].columns)}",
                  flush=True)
        except EmError as e:
            msg = str(e).replace('\n', ' | ')
            # 9201 = 参数被接受了, 但该期无数据 —— 不算配方坏
            (empty if 'code=9201' in msg else err).append((rn, msg[:110]))
            print(f"{'EMPTY' if '9201' in msg else 'ERR'}    {rn[:46]:46s} {msg[:62]}",
                  flush=True)
        except Exception as e:                       # noqa: BLE001
            err.append((rn, f'{type(e).__name__}: {e}'[:110]))
            print(f"ERR     {rn[:46]:46s} {type(e).__name__}: {str(e)[:60]}", flush=True)

    total = len(ok) + len(empty) + len(err)
    print(f"\n汇总 配方可用 {len(ok)}/{total}"
          f"  |  参数正确但无数据 {len(empty)}  |  真失败 {len(err)}")
    if args.out:
        json.dump({'ok': ok, 'empty': empty, 'err': err},
                  open(args.out, 'w'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()