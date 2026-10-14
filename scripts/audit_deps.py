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


def imports_of(path):
    """{一级模块名: 行号} —— 能拿到 AST 就行, 语法错的跳过"""
    try:
        tree = ast.parse(path.read_text(encoding='utf-8'))
    except (SyntaxError, UnicodeDecodeError):
        return {}
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                found.setdefault(a.name.split('.')[0], node.lineno)
        elif isinstance(node, ast.ImportFrom):
            if node.level:                       # 相对导入, 就是本包
                continue
            if node.module:
                found.setdefault(node.module.split('.')[0], node.lineno)
    return found


def declared():
    """pyproject 里的 (核心, 可选) 发行名 → 规格"""
    with open(ROOT / 'pyproject.toml', 'rb') as f:
        d = tomllib.load(f)['project']
    core = d.get('dependencies') or []
    opt = {}
    for name, items in (d.get('optional-dependencies') or {}).items():
        opt[name] = items
    return core, opt


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
    for d in dirs:
        for f in sorted((ROOT / d).rglob('*.py')):
            for mod, line in imports_of(f).items():
                if (mod in STDLIB or mod in FIRST_PARTY or mod in local
                        or mod.startswith('_')):
                    continue
                used.setdefault(dist_of(mod), set()).add(
                    '%s:%d' % (f.relative_to(ROOT), line))

    core, opt = declared()
    def norm(spec):
        return spec.split('[')[0].split('>')[0].split('=')[0].split('<')[0].strip().lower()

    declared_all = {}
    for spec in core:
        declared_all[norm(spec)] = 'core'
    for group, items in opt.items():
        for spec in items:
            declared_all.setdefault(norm(spec), 'optional:' + group)

    print('=== import 了但没声明 (缺失) ===')
    missing = []
    for dist in sorted(used):
        if dist.lower() not in declared_all:
            missing.append(dist)
            print('  %-20s ← %s' % (dist, ', '.join(sorted(used[dist]))[:120]))
    if not missing:
        print('  (无)')

    print('\n=== 声明了但 src 没用 (可能是脚本/测试依赖, 或已废弃) ===')
    for dist, where in sorted(declared_all.items()):
        if dist not in {d.lower() for d in used}:
            print('  %-20s (%s)' % (dist, where))

    print('\n=== 用到且已声明 ===')
    for dist in sorted(used):
        if dist.lower() in declared_all:
            print('  %-20s (%s)' % (dist, declared_all[dist.lower()]))
    return 1 if missing else 0


if __name__ == '__main__':
    sys.exit(main())
