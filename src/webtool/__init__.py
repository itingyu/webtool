"""webtool 包"""
from webtool.core.version import get_version as _get_version

# 版本号唯一真源是 pyproject.toml (装包后回落安装元数据), 见 core/version.py
__version__ = _get_version()
