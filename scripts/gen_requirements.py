#!/usr/bin/env python3
"""从 pyproject.toml 生成 requirements.txt (别手改这个文件)

pyproject 是唯一权威: `pip install webtool` 会自动装 [project.dependencies]。
**全装是唯一形态** —— 没有 extras 分档, 所以只需要一个 requirements.txt。
`tests/test_smoke.py` 会校验两者一致, 手改会被测出来。

用法: python3 scripts/gen_requirements.py [--check]
  --check 只比不写 (给测试/CI 用), 不一致时退出码 1
"""
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HEAD = """# 自动生成, 不要手改 —— 改 pyproject.toml 后跑:
#   python3 scripts/gen_requirements.py
# (tests/test_smoke.py 会校验本文件与 pyproject 一致)
"""

# 曾经生成过的文件, 现在不该再存在 (全装化后并入 requirements.txt)
STALE = ('requirements-full.txt',)


def specs():
    with open(ROOT / 'pyproject.toml', 'rb') as f:
        proj = tomllib.load(f)['project']
    core = [s for s in proj.get('dependencies') or []]
    if proj.get('optional-dependencies'):
        raise SystemExit('pyproject 还有 optional-dependencies —— 本仓库只做全装, '
                         '请把依赖并进 dependencies')
    return {'requirements.txt': HEAD + '\n'.join(core) + '\n'}


def main():
    check = '--check' in sys.argv
    bad = []
    for name, want in specs().items():
        path = ROOT / name
        now = path.read_text(encoding='utf-8') if path.exists() else None
        if now == want:
            print('一致  %s' % name)
            continue
        if check:
            bad.append(name)
            print('不一致 %s (跑 python3 scripts/gen_requirements.py)' % name)
            continue
        path.write_text(want, encoding='utf-8')
        print('已写  %s (%d 行)' % (name, want.count('\n') - 3))
    for name in STALE:
        path = ROOT / name
        if not path.exists():
            continue
        if check:
            bad.append(name)
            print('多余 %s (全装化后应删除)' % name)
        else:
            path.unlink()
            print('已删  %s (全装化后不再生成)' % name)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
