"""错误与退出码的唯一口径 (G9 / R12)

退出码约定 (docs/coding-standard.md §2.11):
    0    成功
    1    运行时失败 (网络/上游/数据问题, 重试也没用)
    2    用法错误 (参数非法/缺输入/未知子命令) —— 属于"你调用错了"
    130  被 Ctrl-C 打断 (SIGINT)

进程边界 (main) 是唯一 catch-all: 命令内部**不要**自己 sys.exit/return 杂码,
要么 return 0/2 表达"用法/成功", 要么抛 WebtoolError 让 main 统一落地。
抛异常的好处: 带上下文, 且 --debug 时能看到 traceback。
"""
import sys

OK = 0
FAILURE = 1
USAGE = 2
INTERRUPTED = 130

#: 退出码 → 一句话含义 (文档/测试共用, 别各写一份)
MEANING = {
    OK: '成功',
    FAILURE: '运行时失败',
    USAGE: '用法错误',
    INTERRUPTED: '被中断 (Ctrl-C)',
}


class WebtoolError(RuntimeError):
    """本仓错误的基类: 带退出码, 交给 main 打印 + 落地

    子类只改 exit_code 即可; 消息给人看, 不堆栈 (要堆栈就 --debug)。
    """

    exit_code = FAILURE

    def __init__(self, msg='', code=None):
        super().__init__(msg)
        if code is not None:
            self.exit_code = code


class UsageError(WebtoolError):
    """参数/输入用法错误 → 退出 2, main 会附一句 "看 --help" """

    exit_code = USAGE


class NotFound(WebtoolError):
    """目标不存在 (未知 site/key/源/引擎) → 退出 2 (是调用方用错了名字)"""

    exit_code = USAGE


def die(msg, code=FAILURE):
    """打印 `webtool: <msg>` 到 stderr 并以 code 退出 (给无法 return 的深层用)"""
    print('webtool: %s' % msg, file=sys.stderr)
    raise SystemExit(code)
