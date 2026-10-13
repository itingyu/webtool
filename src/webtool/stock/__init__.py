"""股票能力包: 桥接 stock-master 脚本层与 stock MCP 24 个工具

三块分工:
  master.py    桥 /var/minis/skills/stock-master 的 scripts (行情/涨停池/选股/风险)
  mcp.py       桥 stock MCP server 的 24 个 tool (公告/财务/资金流/股东/龙虎榜类)
  command.py   动作分发 + 输出渲染

两侧都不复制业务逻辑, 只做进程内 import / 子进程调用, 数据源与口径仍由
stock-master 与 stock MCP 各自维护。
"""