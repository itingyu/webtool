"""webtool 包"""


def __getattr__(name):
    """版本号按需取 —— 别让每次 import 都去解析 pyproject

    `import webtool.<任意子模块>` 都会先执行这里; 之前写成
    `__version__ = get_version()`, 等于每条命令启动都付一次 tomllib 的导入
    (~85ms) + 文件路径解析。只有真要显示版本/报障时才需要它, 改成惰性。
    """
    if name == '__version__':
        from webtool.core.version import get_version
        return get_version()
    raise AttributeError("module 'webtool' has no attribute %r" % name)
