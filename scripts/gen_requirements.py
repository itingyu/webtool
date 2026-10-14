#!/usr/bin/env python3
"""从 pyproject.toml 生成 requirements*.txt (别手改这两个文件)

pyproject 是唯一权威: `pip install webtool` 会自动装 [project.dependencies],
可选功能走 extras。requirements 文件只是给不看 pyproject 的人/脚本一个清单,
所以必须由本脚本生成 —— `tests/test_smoke.py` 会校验两者一致, 手改会被测出来。

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


def specs():
    with open(ROOT / 'pyproject.toml', 'rb') as f:
        proj = tomllib.load(f)['project']
    core = [s for s in proj.get('dependencies') or []]
    extras = proj.get('optional-dependencies') or {}
    full, seen = [], {s.split('>')[0].split('=')[0].strip().lower()
                      for s in core}
    for group in sorted(extras):
        for s in extras[group]:
            key = s.split('>')[0].split('=')[0].strip().lower()
            if key not in seen:                  # 与核心重复的不重复列
                seen.add(key)
                full.append(s)
    extra_names = ','.join(sorted(extras))
    files = {
        'requirements.txt': HEAD + '\n'.join(core) + '\n',
        'requirements-full.txt': (HEAD + '# 等价 `pip install webtool[%s]`\n'
                                  % extra_names) + '\n'.join(core + full) + '\n',
    }
    return files


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
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
