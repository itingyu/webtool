"""用户目录路径: 一律现算, 尊重 WEBTOOL_DIR (测试/多实例隔离)"""
import os
from pathlib import Path


def user_dir() -> Path:
    return Path(os.environ.get('WEBTOOL_DIR') or '~/.webtool').expanduser()


def user_path(*parts) -> Path:
    return user_dir().joinpath(*parts)
