"""stock 统一错误类型

七条取数通道的异常 (MasterMissing / SrvError / RawApiError / EcoError /
DocsError / EmError / HttpError) 全部继承 `StockError`, 通道信息收进 `source`
字段 —— 分文件是为了内部分工, 不该泄漏到调用方: 调用方只需 `except StockError`
一路接住。

`exit_code` 由类型自己声明: 用法错退 2、数据源错退 1、证书错退 3, CLI 不用
逐个 if 转发。

错误语义 (与 stock-master 硬约束一致):
    - 数据源失败 ≠ 没数据。`StockError` 一律显式带原因, 不静默返回空
    - 接口返回 0/空 不当正常值, 由各桥透传 status
    - 北向资金不可用必须显式标注, 不填 0
"""


class StockError(RuntimeError):
    """所有 stock 取数失败的基类

    `source` 标明是哪条通道 (master / srv / rawapi / eco / em / docs / http),
    只用于错误信息与诊断, 调用方不该靠它做分支。
    `exit_code` 由子类声明, CLI 直接取用。
    """

    source = 'stock'
    exit_code = 1

    def __init__(self, message, source=None, cause=None):
        super().__init__(message)
        self.source = source or type(self).source
        self.cause = cause


class MasterMissing(StockError):
    """stock-master 不可 import —— 装包损坏, 退 2"""

    source = 'master'
    exit_code = 2


class SrvError(StockError):
    """stock 数据桥 (服务端 24 工具) 不可用 / 协议异常"""

    source = 'srv'
    exit_code = 1


class RawApiError(StockError):
    """数据源层不可用 / 方法不存在 / 调用失败"""

    source = 'rawapi'
    exit_code = 1


class EcoError(StockError):
    """生态库不可用 / 接口不存在 / 调用失败或超时"""

    source = 'eco'
    exit_code = 1


class DocsError(StockError):
    """逆向接口文档不存在 / 检索失败 —— 本地数据缺失, 退 2"""

    source = 'docs'
    exit_code = 2


class EmError(StockError):
    """东财 datacenter 调用失败 (reportName / 排序列 / 入参)"""

    source = 'em'
    exit_code = 1


class HttpError(StockError):
    """底层 HTTP 直调失败 —— 证书类问题单列, 退 3 (不是重试能解决的)"""

    source = 'http'
    exit_code = 3


class UsageError(StockError):
    """参数缺失/非法 —— 退 2, 与数据源失败区分开"""

    source = 'usage'
    exit_code = 2


class BridgeMissing(StockError):
    """取数桥整体不可用 (导入失败) —— 退 2, 提示装哪个 extra"""

    source = 'bridge'
    exit_code = 2