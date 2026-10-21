# webtool 文档

命令行抓取 / 搜索 / 订阅工具。所有文档以当前代码为准，改动功能时请同步对应篇章。

| 文档 | 讲什么 |
|---|---|
| [design.md](design.md) | 分层、一次请求怎么走、配置与存储位置、失败语义 |
| [plugins.md](plugins.md) | 九类插件、注册与生命周期、外部进程插件、SDK、无源码加载 |
| [intercept.md](intercept.md) | 拦截判定、按站点冷却、绕行降级梯、拦截日志 |
| [custom-sites.md](custom-sites.md) | 用 JSON 接一个站内搜索，不写 Python |
| [coding-standard.md](coding-standard.md) | 改代码前必须知道的硬约束与自检方式 |
| [testing.md](testing.md) | 测试怎么组织、怎么跑、环境怎么隔离 |

## 先跑起来

```bash
webtool search "关键词"                 # 聚合搜索
webtool fetch https://example.com       # 正文提取
webtool rank zhihu                      # 热榜
webtool plugins check                   # 插件体检
webtool intercept-log -n 20             # 最近的拦截记录
```

命令全集与参数见仓库根目录 `README.md`。

## 三个约定

- **用户数据只落 `~/.webtool/`**：配置、状态、缓存、日志都在这里；设 `WEBTOOL_DIR`
  可整体换根（测试即靠它隔离）。
- **配置改了不用重启**：`plugins.json` / `filters.json` 等按 mtime 自动重读；
  外部插件进程在 `plugins reload` 时重建。
- **出网只有 `net/transport.py` 一条路**：新增采集逻辑不要直接 `requests.get`，
  否则代理、TLS、重试、限速、拦截判定全部绕过去了。
