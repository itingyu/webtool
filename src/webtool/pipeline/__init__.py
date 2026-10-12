"""流水线层: 搜索业务的编排

search 调度多引擎, merge 排序去重, rank 榜单, topup 补量, qhint 质量诊断。
可依赖 core 与 net 与 render, 不被 engines/ 反向依赖。
"""
