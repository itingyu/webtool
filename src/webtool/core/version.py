# -*- coding: utf-8 -*-
"""版本号与运行环境信息 (webtool --version / webtool version)

版本号只有一个真源: `pyproject.toml` 的 `project.version`。
  - 源码树里跑: 读 pyproject —— 本地改了版本号立刻生效, 不用重装 (这个仓库
    的开发方式就是这样: 改完直接 `webtool ...` 跑);
  - 装成 wheel 后: wheel 不带 pyproject, 回落到 importlib.metadata 的安装记录;
  - 都拿不到: 'unknown' (只影响显示, 不该让 import 失败)。

`__version__` 由这里派生, tests/test_smoke.py 会校验它与真源一致。
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

    先按行扫 `[project]` 段: 只为一个版本号把 tomllib 拉进来要 ~85ms, 而这条
    路径在 `webtool --version` / 报障输出上每次都要走。扫不到 (非标准写法/没有
    pyproject) 才回落到 tomllib, 结果仍是同一份文件说了算。
    """
    try:
        with open(_PYPROJECT, encoding='utf-8') as f:
            in_project = False
            for line in f:
                s = line.strip()
                if s.startswith('['):
                    in_project = s == '[project]'
                    continue
                if not in_project or '=' not in s:
                    continue
                key, _, val = s.partition('=')
                if key.strip() == 'version':
                    val = val.split('#', 1)[0].strip().strip('"\'')
                    if val:
                        return val
    except OSError:
        return None
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
            out[name] = None                     # 没装: 如实标 None (全装形态下=装包不完整)
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
        from webtool.core import deps as _deps
        lines.append('未装     ' + ', '.join(miss)
                     + '  —— ' + _deps.install_hint(', '.join(miss)))
    return '\n'.join(lines)
