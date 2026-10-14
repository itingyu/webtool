"""股票能力包: 桥接 stock-master 脚本层与多源编排层。

分工:
  bridge/master.py     包内的 stock-master 脚本层 (行情/涨停池/选股/风险)
  bridge/srv.py        多源回退编排层 (公告/财务/资金流/股东/龙虎榜类共 24 个动作)
  bridge/sources/      低阶取数层, 按数据源分文件 (雪球/东财/同花顺/新浪/...)
  command.py           动作分发 + 输出渲染 (render/ 下按格式分文件)

不复制业务逻辑, 只做进程内 import 与调用; 数据源与口径分别由 source 层与
编排层维护。
"""
