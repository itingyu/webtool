# webtool

免费、免 key 的 Agent 网页工具：**搜索 + 榜单 + 站内搜索 + RSS 订阅 + 免费层 LLM 对话 + 正文提取**，输出纯净 markdown/text/json，HTML→正文压缩到 ~2%（省 98% token）。

## 安装

```bash
pip install 'git+https://github.com/itingyu/webtool#egg=webtool[full]'
# full extra = trafilatura 正文提取 + curl_cffi TLS 指纹 + pysocks 代理（建议必装）
# 裸装也可跑: bing/sogou/google 全功能, 百度引擎与最佳正文提取需 full
```

## 命令

```bash
webtool search "LLM 排行榜" -n 5              # 多引擎: bing,sogou,baidu (默认) / google / marginalia
webtool fetch <url> --max-chars 4000          # 正文提取 → markdown (text/json/html)
webtool rank                                  # 榜单清单 (19 源热榜: 知乎/微博/抖音/B站/HN/GitHub Trending...)
webtool rank zhihu weibo -q "汽车"            # BM25 语义筛选 + 跨源重排
webtool feed                                  # 源清单 (7 预设 + 104 精选种子)
webtool feed sspai ithome --new-only          # 增量: 只出上次之后的新条目
webtool feed radar 36kr --pick 1 --example    # 查 RSSHub 路由库 → 填参 → 直接拉数据
webtool feed instances                        # 公共实例探活
webtool feed health                           # 坏源登记表
webtool site github fastapi                   # 站内搜索 (20 站点)
webtool zen "问题"                            # OpenCode Zen 免费层对话, 无需 key
webtool proxy set http://127.0.0.1:2080       # 代理 (被墙源必须; 直连优先, 失败才走)
```

## RSS 订阅 (feed)

- 任意 RSS/Atom URL 直接喂；`--add NAME URL [desc]` / `--del NAME`（存 `~/.webtool/feeds.json`，预设不可删）
- **104 个精选种子源随包分发**（AI 专题 / 技术社区 / 大厂博客 / 前端 / 安全 / 学术 / 开发工具版本追踪等 14 类，来自 awesome-rsshub-routes 清单并逐条实测），安装时自动并入，只增不覆盖用户改动
- `--new-only` 增量；`-q` 语义筛选重排；坏源失败自动登记，`health` / `--retest` / `--mark` 管理
- **feed radar**：查 RSSHub 官方路由库（~2069 站 / ~3947 路由），`--pick N --param k=v` 填参、`--example` 官方示例、`--from-url` 页面反推、`--add` 落地；官网 feed 与路由交叉校验，官网含目标栏目时优先官网
- RSSHub 公共实例实测 4 个可用（rssforever / slarker / wudifeixue / isrss），429 轮换前缀；详见 `docs/feed-sources.md`

## zen：免费层 LLM（无需 key）

OpenCode Zen 公开模式，默认 `big-pickle`；`--list-free` 实时拉免费模型（上下架频繁，别凭记忆报模型名）。免费层形状校验已绕过：默认只发 bash+read 空壳工具定义，请求体省 98%。

## 设计要点

- **反探测**：全命令统一浏览器指纹——cffi 通道 curl_cffi impersonate（UA/TLS/HTTP2 同源生成），REST/urllib 兜底套档案 UA；轮换池 chrome131/safari18_4/移动端；直连优先，传输层失败才探活代理
- **SPA 壳页**：内嵌 SSR state 自动收割（RENDER_DATA/`__NEXT_DATA__`/`__NUXT__` 框架无关）；壳页显式报错不吐假正文
- **排序**：引擎基础分 × 位置衰减 × 多引擎共识 × BM25 语义 × 实体命中 × 域名先验；BM25 本地分词（中文 2-gram），无外部 API
- **Agent 友好**：json/text/markdown 信息对齐、`-o` 落盘补扩展名、错误带处置建议、过滤链每层剔除量回显、退出码 0/2 约定

## 局限

- 不做 JS 渲染：SPA 首屏内嵌数据大多能收割，纯前端渲染返回 hint
- 按 UA 分流的站点：`fetch --profile chrome131_android` 切真移动 TLS 指纹重试
- 知乎正文 403（需登录态）；google web / docs.rsshub.app 需代理（google 429 自动降级 news RSS）
- arXiv feed 周末 skipDays 空属正常；LinuxDo 等 CF 站需登录态

## 给 Agent 用

复制 `skills/webtool/SKILL.md` 到 Agent 的 skill 目录（Claude Code `.claude/skills/`、Minis `/var/minis/skills/`）。

深入文档：`docs/design.md`（架构与调研决策）· `docs/feed-sources.md`（feed 源实测清单）· `docs/custom-sites.md`（site JSON 扩展）· `docs/engine-notes.md`（引擎通道实测记录）。
