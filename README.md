# webtool

免费、免 key 的 Agent 网页工具：**搜索 + 榜单 + 站内搜索 + RSS 订阅 + 正文提取**，输出纯净 markdown/text/json，HTML→正文压缩到 ~2%（省 98% token）。

## 安装

```bash
pip install 'git+https://github.com/itingyu/webtool#egg=webtool[full]'
# full extra = trafilatura 正文提取 + curl_cffi TLS 指纹 + pysocks 代理（建议必装）
# 裸装也可跑: bing/sogou/google 全功能, 正文提取降级基础模式
```

## 命令

```bash
webtool search "LLM 排行榜" -n 5              # 多引擎: bing,sogou,baidu (默认) / google / marginalia
webtool fetch <url> --max-chars 4000          # 正文提取 → markdown (text/json/html)
webtool rank                                  # 榜单清单 (18 源热榜: 知乎/微博/抖音/B站/HN/GitHub Trending...)
webtool rank zhihu weibo -q "汽车"            # 语义筛选 + 跨源重排 (-t 阈值, 默认 0.15)
webtool feed                                  # RSS 清单 (7 预设 + 103 随包精选源 + 任意 feed URL)
webtool feed sspai ithome --new-only          # 增量: 只出上次之后的新条目
webtool feed radar 36kr                       # 查 RSSHub 官方路由库 (2069 站 / 3947 路由, 带参数说明/真实样例/官网 feed)
webtool feed radar 36kr --pick 2 --param category=newsflashes   # 选第2条路由, 填参, 直接拉数据输出
webtool feed instances                         # 公共实例探活 (哪几个今天还活着)
webtool site github fastapi                   # 站内搜索 (18 站点)
webtool feed health / --retest KEY / --mark KEY "备注"   # 坏源登记/复查/人工备注
webtool proxy set http://127.0.0.1:2080       # 代理 (直连失败自动探活降级)
```

## RSS 订阅 (feed)

- 任意 RSS/Atom URL 直接喂：`webtool feed https://example.com/feed.xml`
- 自定义源：`--add NAME URL [desc]` / `--del NAME`（存 `~/.webtool/feeds.json`，预设不可删）
- RSSHub 路由直接用：`webtool feed --add r36kr https://rsshub.rssforever.com/36kr/newsflashes`；`feed radar <关键词>` 查**官方路由目录** docs.rsshub.app/routes.json（2069 站 / 3947 路由）拿到路由模板 + 参数枚举说明 + 官方示例 + 真实样例，`--pick <序号|模板子串>` 选定路由（不填则取 heat 最高的一条）→ `--param K=V` 填参后**直接把数据拉出来**（模板行保持原样，参数只作用于选中那条）；免填参可用 `--example`（官方示例路径）或 `--top N`（第 N 条真实样例）；`--from-url <网页URL>` 可从任意页面反推路由；公共实例用 `feed instances` 探活（可用性逐日变化），限流 429 时轮换前缀
- 坏源自动登记：失败入 `~/.webtool/feed_health.json`，`feed health` 查看，恢复自动移除

## 设计要点

- **反探测**：全命令统一浏览器指纹——cffi 通道 curl_cffi impersonate（UA/TLS/HTTP2 同源生成），REST/urllib 兜底套浏览器档案 UA；指纹轮换池 chrome131/safari18_4/移动端
- **SPA 壳页**：内嵌 SSR state 自动收割（RENDER_DATA/`__NEXT_DATA__`/`__NUXT__` 框架无关）；壳页显式报错不吐假正文
- **排序**：引擎基础分 × 位置衰减 × 多引擎共识 × BM25 语义 × 实体命中 × 域名先验；BM25 本地分词（中文 2-gram），无外部 API
- **Agent 友好**：json/text/markdown 信息对齐、`-o` 落盘按 `-f` 补扩展名、错误带处置建议、过滤链每层剔除量回显

## 局限

- 不做 JS 渲染：SPA 首屏内嵌数据大多能收割，纯前端渲染返回 hint
- 按 UA 分流的站点：`fetch --profile chrome131_android` 切真移动 TLS 指纹重试
- 知乎正文 403（需登录态）；google web 需代理（429 自动降级 news RSS）

## 给 Agent 用

复制 `skills/webtool/SKILL.md` 到 Agent 的 skill 目录（Claude Code `.claude/skills/`、Minis `/var/minis/skills/`）。

详细设计：`docs/design.md`；自定义站点：`docs/custom-sites.md`；feed 源实测：`docs/feed-sources.md`。
