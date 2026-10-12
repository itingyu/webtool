"""feed 能力包: 订阅源清单 / 解析 / 取数 / 路由卡片 / 子命令编排

分层: sources(数据) → parse(纯解析) → fetch(出网) → cards(呈现) → command(编排)。
想只用 RSS 解析直接 import webtool.feeds.parse; 子命令入口是 command.do_feed。
"""
