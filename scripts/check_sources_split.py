"""拆包完整性对账 —— 原始 api_client vs sources/ 十个模块

切分脚本是按行号切的, 一旦原始文件后续有改动 (或切点算错), 就会静默
丢方法: 模块照样能 import, 只有真调那个方法时才 AttributeError。

这个脚本把"丢没丢"变成一条可执行的断言, 而不是靠人肉比对。
"""
import ast
import pathlib
import re
import sys

# 基线随仓 (tests/fixtures/): 曾经读项目外的 shared/股票/API调研/api_client.py,
# 那份文件不在时脚本没法跑 —— 对账基准必须跟代码在同一个仓里
ORIG = (pathlib.Path(__file__).resolve().parents[1]
        / 'tests' / 'fixtures' / 'api_client_original.py')
SOURCES = pathlib.Path(__file__).resolve().parents[1] / 'src/webtool/stock/bridge/sources'

def methods_of(path: pathlib.Path) -> dict:
    """AST 取类内方法 (排除 __ 开头) → {name: lineno}"""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for f in node.body:
                if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not f.name.startswith('__'):
                        out[f.name] = f.lineno
    return out

def orig_methods() -> dict:
    """原始文件用正则 —— 它 import 了 akshare 等重依赖, AST 解析要能跑通才行

    实测 ast.parse 对该文件可用, 但为了不受缩进/嵌套风格影响, 这里仍用
    正则抓 `^    def ` (类体缩进), 足以覆盖。
    """
    text = ORIG.read_text(encoding='utf-8')
    out, lineno = {}, 0
    for line in text.splitlines():
        lineno += 1
        m = re.match(r'^    def ([a-zA-Z_]\w*)\(', line)
        if m:
            out[m.group(1)] = lineno
    return out

def main() -> int:
    orig = orig_methods()
    # 原文件里的自有 API 方法 (非自检/内部工具)
    skip = {'test_all', 'api', 'sse_yunhq_snap', '__init__'}
    orig_api = {k: v for k, v in orig.items() if k not in skip}

    got: dict[str, str] = {}
    dup: dict[str, list] = {}
    # 公共底座 `_base.py` 也要计入: 传输层 (`_xq_get` / `_xueqiu_session`)
    # 是切分时刻意从各源抽上去的, 不参与源归属, 但不能丢
    for f in sorted(SOURCES.glob('*.py')):
        if f.name.startswith('_') and f.name != '_base.py':
            continue
        for name in methods_of(f):
            # 私有方法也计入 —— 切分丢一个 `_em_get` 同样会让真调时炸
            if name in got:
                dup.setdefault(name, [got[name]]).append(f.name)
            got[name] = f.name

    missing = sorted(set(orig_api) - set(got))
    extra = sorted(set(got) - set(orig_api))

    print(f'原始方法  : {len(orig_api)}')
    print(f'现有方法  : {len(got)}')
    print(f'丢失      : {len(missing)}')
    for m in missing:
        print(f'   - {m:34s} (原 api_client.py:{orig_api[m]})')
    print(f'新增      : {len(extra)}')
    for m in extra:
        print(f'   + {m:34s} ({got[m]})')
    if dup:
        print(f'重复定义  : {len(dup)}')
        for m, where in dup.items():
            print(f'   ! {m:34s} {where}')
    return 1 if (missing or dup) else 0

if __name__ == '__main__':
    sys.exit(main())