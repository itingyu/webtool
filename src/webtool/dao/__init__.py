"""DAO 层: 只看存取, 不懂业务 (缓存 / 持久化状态 / 断点)

从 core 分出 (P5)。这个包是**持久化原语**层, 依赖方向在 core 之下:
只 import 标准库与 `core.logging`(无依赖的基础模块), 不碰 net/engines/pipeline
等任何上层, 也不回指 core 的其他部分 —— 否则「core 用 dao、dao 用 core」会成环。

为什么不在方案原画的 L1 而在这里: `state` 存的是 cookie 与熔断器状态, 消费方是
`net/transport.py` 与 `net/captcha.py` —— 把 dao 放在 net 之上会让 net 反向依赖
上层。持久化原语必须待在网络底座之下, 这是依赖图决定的, 不是图好看决定的。

  cache.py       磁盘缓存: 分桶 TTL (search/fetch/resolve/hot/zen)
  state.py       跨进程状态: cookie jar / 熔断器计数
  checkpoint.py  批任务断点: 已完成条目落盘, 重跑跳过
"""
from webtool.dao import cache as cache
from webtool.dao import state as state
from webtool.dao.checkpoint import Checkpoint as Checkpoint

__all__ = ['Checkpoint', 'cache', 'state']
