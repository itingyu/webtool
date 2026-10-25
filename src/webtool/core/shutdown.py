"""优雅关闭: Ctrl-C 一次协作退出, 两次强制退出

为什么需要它
------------
CLI 里"按 Ctrl-C 停不下来"有两个来源, 都不是能靠一层 try/except 解决的:

1. **线程池收尾会 join worker**。`with ThreadPoolExecutor(...) as ex:` 退出时
   是 `shutdown(wait=True)` —— 在飞的网络请求(超时 15~60s)没回来, 主线程就得
   等着。`concurrent.futures.thread` 还在解释器退出时注册了 `_python_exit`,
   把**所有** worker 再 join 一遍, 于是 `sys.exit(130)` 也会被拖住。
   → 对策在 `core.resilient.thread_pool()`: 用不登记 `_threads_queues` 的守护线程池,
     配合"打断即取消未开始任务、不等待"。
2. **主线程卡在 C 调用里(如 libcurl 阻塞收发)时, Python 层的 SIGINT 处理器
   要等这个 C 调用返回才会跑**, 期间按 Ctrl-C 像是没反应。
   → 对策就是本模块: **再按一次直接 `os._exit(130)`**, 绕开 C 调用与所有 join。

行为
----
- 第 1 次 SIGINT/SIGTERM: 抛 `KeyboardInterrupt`, 交给上层走正常收尾(130)。
- 第 2 次: 冲刷 stdio 后 `os._exit(130)` —— 保证一定能停。
- 幂等: 重复 install 不叠加; 只在主线程生效(信号处理器本就只在主线程跑)。
"""
import os
import signal
import sys

_installed = False
_count = [0]


def hard_exit(code=130):
    """立即退出: 先冲刷 stdio, 再 os._exit (跳过 atexit 的线程 join)"""
    for s in (sys.stdout, sys.stderr):
        try:
            s.flush()
        except Exception:
            pass
    os._exit(code)


def _handler(signum, frame):
    _count[0] += 1
    if _count[0] >= 2:
        hard_exit(130)
    raise KeyboardInterrupt


def install():
    """装 SIGINT/SIGTERM 守卫 (幂等)。CLI 入口调一次即可。"""
    global _installed
    if _installed:
        return
    _installed = True
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handler)
        except (ValueError, OSError):
            pass                            # 非主线程/平台不支持: 保持默认
