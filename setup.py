# -*- coding: utf-8 -*-
"""安装期把精选 RSS 源种子 (src/webtool/data/feeds.seed.json) 落到 ~/.webtool/。

setuptools 的 PEP 517 构建没有通用的 "post-install" 钩子, 所以挂在 build_py
上 —— 它在 `pip install .` 和 `pip install -e .` 两条路径上都会跑。

三条硬约束:
  1. 绝不覆盖用户已有文件里改过的项: 已存在的 key 以用户版本为准, 只补缺的。
  2. 绝不因写盘失败让安装失败: HOME 只读 / 交叉编译 / CI 里跳过, 全部静默。
  3. 可用 WEBTOOL_NO_SEED=1 显式关闭 (如做 deb/rpm 打包时)。

运行时还有一道兜底: webtool.feed._load_user_feeds() 每次读源清单时也会把
seed 里缺的项并进去, 所以就算安装期没落地 (如直接拷 wheel 解包), 也能补上。
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, 'src', 'webtool', 'data', 'feeds.seed.json')
TARGET_DIR = os.path.expanduser('~/.webtool')
TARGET = os.path.join(TARGET_DIR, 'feeds.json')


def seed_feeds():
    """把 seed 并进 ~/.webtool/feeds.json, 返回新增条数。"""
    if os.environ.get('WEBTOOL_NO_SEED'):
        return 0
    try:
        with open(SEED, 'r', encoding='utf-8') as f:
            seed = json.load(f) or {}
    except Exception:
        return 0
    try:
        with open(TARGET, 'r', encoding='utf-8') as f:
            user = json.load(f) or {}
        if not isinstance(user, dict):
            user = {}
    except Exception:
        user = {}

    added = [k for k in seed if k not in user]
    if not added:
        return 0

    merged = dict(seed)
    merged.update(user)          # 用户同名项优先, 不覆盖本地改动
    try:
        os.makedirs(TARGET_DIR, exist_ok=True)
        with open(TARGET, 'w', encoding='utf-8') as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
    except Exception:
        return 0
    return len(added)


def _build_py():
    from setuptools.command.build_py import build_py as _build_py_base

    class BuildPyWithSeed(_build_py_base):
        def run(self):
            _build_py_base.run(self)
            n = seed_feeds()
            if n:
                print('[webtool] 已把 %d 个精选 RSS 源并入 %s' % (n, TARGET),
                      file=sys.stderr)
    return BuildPyWithSeed


try:
    from setuptools import setup as _setup
except ImportError:                                   # 允许只 import setup.py
    _setup = None

if _setup is not None and __name__ == '__main__':
    _setup(cmdclass={'build_py': _build_py()})
