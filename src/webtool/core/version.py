# -*- coding: utf-8 -*-
"""版本号与运行环境信息 (webtool --version / webtool version)

版本号只有一个真源: `pyproject.toml` 的 `project.version`。
  - 源码树里跑: 读 pyproject —— 本地改了版本号立刻生效, 不用重装 (这个仓库
    的开发方式就是这样: 改完直接 `webtool ...` 跑);
  - 装成 wheel 后: wheel 不带 pyproject, 回落到 importlib.metadata 的安装记录;
  - 都拿不到: 'unknown' (只影响显示, 不该让 import 失败)。

以前 `webtool/__init__.py` 里写死一个 1.8.0, 与 pyproject 各说各话 —— 现在
`__version__` 由这里派生, tests/test_smoke.py 会校验它俩一致。
"""
import platform
import sys
from pathlib import Path

# 装包后看版本用 importlib.metadata; 源码树里以 pyproject 为准
_PYPROJECT = Path(__file__).resolve().parents[3] / 'pyproject.toml'
# 依赖里挑几个"缺了就明显不正常"的, 报障时一眼看出装没装
_KEY_DEPS = ('trafilatura', 'curl_cffi', 'typer', 'pysocks', 'certifi',
             'requests', 'pandas', 'numpy')


def _read_pyproject_version():
    """从 pyproject.toml 读版本 (唯一真源)

    tomllib 是 py3.11+ 标准库; 3.9/3.10 上**不去装 tomli** —— 为一个版本号
    多背一个依赖不值, 那两条路上直接用已安装包的元数据 (见 _installed_version),
    跑源码的开发者本来就 ≥3.11 居多。
    """
    try:
        import tomllib
    except ModuleNotFoundError:                 # py3.9/3.10
        return None
    try:
        with open(_PYPROJECT, 'rb') as f:
            return tomllib.load(f)['project']['version']
    except (OSError, KeyError, ValueError):
        return None


def _installed_version():
    try:
        from importlib.metadata import version
        return version('webtool')
    except Exception:                            # 没装 / 元数据坏
        return None


def get_version():
    """当前这份代码的版本号 (源码树优先, 其次安装记录)"""
    return _read_pyproject_version() or _installed_version() or 'unknown'


def _dep_versions():
    out = {}
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:                          # pragma: no cover
        return out
    for name in _KEY_DEPS:
        try:
            out[name] = version(name)
        except PackageNotFoundError:
            out[name] = None                     # 可选依赖没装: 如实标 None
        except Exception:
            out[name] = '?'
    return out


def info():
    """报障用的运行环境: 版本 / Python / 平台 / 代码位置 / 关键依赖

    source_version 与 installed_version 不一致时, 说明本地代码与装进去的那份
    不是一回事 —— 这是"我明明改了却没生效"的常见来源, 直接摆出来。
    """
    src_v, inst_v = _read_pyproject_version(), _installed_version()
    return {
        'version': get_version(),
        'source_version': src_v,
        'installed_version': inst_v,
        'version_mismatch': bool(src_v and inst_v and src_v != inst_v),
        'python': sys.version.split()[0],
        'platform': platform.platform(),
        'package_path': str(Path(__file__).resolve().parents[1]),
        'running_from_source': src_v is not None,
        'deps': _dep_versions(),
    }


def describe():
    """人类可读的多行文本 (webtool version 的默认输出)"""
    d = info()
    lines = ['webtool %s' % d['version']]
    if d['version_mismatch']:
        lines.append('  ⚠ 源码版本 %s 与已安装版本 %s 不一致: 你现在跑的是'
                     '源码树那份, 装进去的还是旧的'
                     % (d['source_version'], d['installed_version']))
    lines.append('python   %s' % d['python'])
    lines.append('平台     %s' % d['platform'])
    lines.append('代码     %s' % d['package_path'])
    if not d['running_from_source']:
        lines.append('来源     已安装的包 (非源码树)')
    deps = d['deps']
    miss = [k for k, v in deps.items() if v is None]
    lines.append('依赖     ' + ', '.join('%s %s' % (k, deps[k])
                                        for k in deps if deps[k]))
    if miss:
        lines.append('未装     ' + ', '.join(miss)
                     + '  (可选: pip install "webtool[stock]" 等)')
    return '\n'.join(lines)
