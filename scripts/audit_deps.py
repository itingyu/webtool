#!/usr/bin/env python3
"""审计: src/ 里真实 import 的第三方库 vs pyproject 声明

用法: python3 scripts/audit_deps.py [--all]
不带 --all 只看 src/ (发行包会跑到的代码); --all 连 scripts/ tests/ 一起看。
输出: 缺失(import 了但没声明) / 未用(声明了但没 import) 两张表。
"""
import ast
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# import 名 → PyPI 发行名 (大部分同名, 只有这些不一样)
ALIAS = {
    'curl_cffi': 'curl_cffi',
    'PIL': 'pillow',
    'yaml': 'PyYAML',
    'bs4': 'beautifulsoup4',
    'lxml': 'lxml',
    'dateutil': 'python-dateutil',
    'maxminddb': 'maxminddb',
    'cryptography': 'cryptography',
    'readability': 'readability-lxml',
    'trafilatura': 'trafilatura',
    'html2text': 'html2text',
    'inscriptis': 'inscriptis',
    'socks': 'pysocks',
    'typer': 'typer',
    'requests': 'requests',
    'pandas': 'pandas',
    'openpyxl': 'openpyxl',
    'click': 'click',
}
# 一级模块名 → 发行名; 表里没有的直接用原名
STDLIB = set(sys.stdlib_module_names)
FIRST_PARTY = {'webtool'}
# 本地约定用来做可选导入的函数名 (参数是库名字符串)
DYN_IMPORT_FUNCS = {'_try_import'}


# 故意不声明的可选依赖 (运行时探测, 有就用): 一级模块名 → 为什么可选
OPTIONAL = {
    'imageio_ffmpeg': '没系统 ffmpeg 时的兜底 (pip 装上就被认出, 自带二进制)',
    'static_ffmpeg': '同上, 另带 ffprobe',
    'xhshow': '小红书签名库 (第三方逆向实现, 只有小红书源要它; 没装时该源报可读提示)',
    'cairosvg': 'SVG→PNG 渲染 (要系统 cairo 库, 没装时走 rsvg-convert 兜底)',
}


def imports_of(path):
    """{一级模块名: 行号} —— 能拿到 AST 就行, 语法错的跳过"""
    try:
        tree = ast.parse(path.read_text(encoding='utf-8'))
    except (SyntaxError, UnicodeDecodeError):
        return {}, set()
    found = {}
    literals = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                found.setdefault(a.name.split('.')[0], node.lineno)
        elif isinstance(node, ast.ImportFrom):
            if node.level:                       # 相对导入, 就是本包
                continue
            if node.module:
                found.setdefault(node.module.split('.')[0], node.lineno)
        elif isinstance(node, ast.Call):
            # 动态 import: 库名是字符串, AST 里没有 Import 节点。本地就两处
            # 惯例 —— bridge/eco.py 的 _try_import('akshare') 和
            # importlib.import_module(...)。不认这两处, akshare 这种"声明了却
            # 扫不出 import"的会被误报成没人用。
            fn = node.func
            dyn = (isinstance(fn, ast.Name) and fn.id in DYN_IMPORT_FUNCS) \
                or (isinstance(fn, ast.Attribute) and fn.attr == 'import_module')
            if dyn and node.args and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str):
                found.setdefault(node.args[0].value.split('.')[0], node.lineno)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            literals.add(node.value)
    return found, literals


def declared():
    """pyproject 里的发行名 → 规格 (全装形态: 只有 dependencies, 没有 extras)"""
    with open(ROOT / 'pyproject.toml', 'rb') as f:
        d = tomllib.load(f)['project']
    return d.get('dependencies') or []


def dist_of(mod):
    return ALIAS.get(mod, mod)


def local_modules(dirs):
    """被扫目录里的 .py 都算一方模块 (tests/make_geodata_fixtures.py 这类别当依赖)"""
    names = set()
    for d in dirs:
        for f in (ROOT / d).rglob('*.py'):
            names.add(f.stem)
            if f.name == '__init__.py':
                names.add(f.parent.name)
    return names


def main():
    dirs = ['src'] + (['scripts', 'tests'] if '--all' in sys.argv else [])
    local = local_modules(dirs)
    used = {}
    literals = set()                     # 全部字符串常量: 兜动态 import
    for d in dirs:
        for f in sorted((ROOT / d).rglob('*.py')):
            _imports, _lits = imports_of(f)
            literals |= _lits
            for mod, line in _imports.items():
                if (mod in STDLIB or mod in FIRST_PARTY or mod in local
                        or mod.startswith('_')):
                    continue
                used.setdefault(dist_of(mod), set()).add(
                    '%s:%d' % (f.relative_to(ROOT), line))

    core = declared()
    def norm(spec):
        return spec.split('[')[0].split('>')[0].split('=')[0].split('<')[0].strip().lower()

    declared_all = {norm(spec): 'core' for spec in core}

    print('=== import 了但没声明 (缺失) ===')
    missing = []
    for dist in sorted(used):
        if dist.lower() in OPTIONAL:         # 可选依赖: 故意不声明, 见文件头 OPTIONAL
            continue
        if dist.lower() not in declared_all:
            missing.append(dist)
            print('  %-20s ← %s' % (dist, ', '.join(sorted(used[dist]))[:120]))
    if not missing:
        print('  (无)')

    print()
    print('=== 可选依赖 (故意不声明, 运行时探测) ===')
    for dist in sorted(used):
        if dist.lower() in OPTIONAL:
            print('  %-20s %s' % (dist, OPTIONAL[dist.lower()]))

    print('\n=== 声明了但 src 没用 (可能是脚本/测试依赖, 或已废弃) ===')
    for dist, where in sorted(declared_all.items()):
        # 动态 import 的库 (bridge/eco.py 的 akshare/tushare/baostock 来自一个
        # 名字元组) AST 里没有 Import 节点 —— 名字以字符串形式出现也算用到。
        if dist not in {d.lower() for d in used} and dist not in literals:
            print('  %-20s (%s)' % (dist, where))

    print('\n=== 用到且已声明 ===')
    for dist in sorted(used):
        if dist.lower() in declared_all:
            print('  %-20s (%s)' % (dist, declared_all[dist.lower()]))
    return 1 if missing else 0


if __name__ == '__main__':
    sys.exit(main())
