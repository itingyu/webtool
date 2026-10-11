# Folo/RSSHub 站点订阅源 → webtool feed 落地清单（实测 2026-10-11）

原则：能用官方 feed 用官方（稳定、无限流）；官方被墙/挂 JS 壳/需 cookie 的，走 RSSHub 公共实例（有 429 限流）或自建。

## 📦 随包精选源（`src/webtool/data/feeds.seed.json`）

精选 **103 个** 源（分类：AI 专题 / 技术社区 / 大厂技术博客 / 前端设计 / 编程语言官方博客 / 安全资讯 / 科技媒体 / 技术周刊 / 学术论文 / 开发工具版本追踪 / RSS 工具更新）。清单来自 [JackyST0/awesome-rsshub-routes](https://github.com/JackyST0/awesome-rsshub-routes)，2026-10-12 双通道（直连 + 代理）逐条实测。

**安装时自动落地**：seed 会在 `pip install` / `pip install -e` 时并入 `~/.webtool/feeds.json`（`setup.py` 的 `build_py` 钩子），运行时 `feed._load_user_feeds()` 还有一道兜底，所以直接解包 wheel / 手动拷源码也能补上。

**只增不覆盖**：用户 `--add` / `--del` 过的同名项以本地为准，seed 更新不会抹掉本地改动。打包场景可用 `WEBTOOL_NO_SEED=1` 显式关掉。HOME 只读或写盘失败一律静默，不影响安装。

**实测状态**：98 源可用；arXiv 4 源（cs.AI/LG/CL/CV）feed 有效但 `skipDays` 周末不更新，看到空 feed 属正常；LinuxDo 3 源（latest/top/posts.rss）Cloudflare 403，需登录态 cookie。

```bash
webtool feed list                          # 7 预设 + 103 精选
webtool feed arXivAI uvReleases Nature -n 5 # 按名字直接拉
```

## ✅ 官方 feed（全部 webtool 通道实测出数据）

### 国际科技/AI
| 名字 | URL | 说明 |
|---|---|---|
| theverge | https://www.theverge.com/rss/index.xml | The Verge 主站 |
| arstechnica | https://feeds.arstechnica.com/arstechnica/index | Ars Technica |
| wired | https://www.wired.com/feed/rss | Wired |
| mittr | https://www.technologyreview.com/feed/ | MIT 科技评论 |
| ieee_ai | https://spectrum.ieee.org/feeds/topic/artificial-intelligence.rss | IEEE Spectrum AI 频道 |
| arxiv_csai | https://export.arxiv.org/rss/cs.AI | arXiv cs.AI（周末 skipDays 空 feed 属正常） |
| producthunt | https://www.producthunt.com/feed | Product Hunt 日榜 |

### 安全/隐私
| 名字 | URL | 说明 |
|---|---|---|
| krebs | https://krebsonsecurity.com/feed/ | Krebs on Security |
| anquanke | https://api.anquanke.com/data/v1/rss | 安全客 |

### 中文科技
| 名字 | URL | 说明 |
|---|---|---|
| juejin_rss | https://juejin.cn/rss | 掘金全站（官方 RSS，无需 RSSHub） |
| leiphone | https://www.leiphone.com/feed | 雷峰网 |
| geekpark | https://www.geekpark.net/rss | 极客公园 |

（sspai/ithome/ifanr/ruanyifeng/github_blog/v2ex/cnode 已是 webtool 内置预设）

## ⚠️ 官方被墙/壳化 → 用 RSSHub 路由（已验证）

| 站点 | 官方状态 | 可用路由（rssforever/ktachibana 实测） |
|---|---|---|
| 36氪快讯 | /feed 返 JS 壳（火山引擎挑战） | https://rsshub.rssforever.com/36kr/newsflashes ✅20条 |
| B站综合热门 | 无官方 feed | https://rsshub.rssforever.com/bilibili/popular/all ✅ |
| 知乎热榜 | webtool rank zhihu 更好 | RSSHub /zhihu/hotlist 公共实例 429 |
| 微博热搜 | webtool rank weibo 更好 | RSSHub 需微博 cookie，公共实例挂 |
| Solidot | index.rss 403 | /solidot 公共实例超时，需自建 |

## RSSHub 公共实例池（2026-10-11 按 docs.rsshub.app/guide/instances 全量实测）

官方文档口径：官方 rsshub.app + 15 社区公共实例；Folo 内置实例不对外（Folo 只是个 AI RSS 阅读器 + 用户共享实例，与 webtool 无关，路由格式一致）。

**实测可用 4 个**（/36kr/newsflashes 验证出数据）：

| 实例 | 地区 | 状态 |
|---|---|---|
| rsshub.rssforever.com | AE | ✅ 直连稳定 |
| hub.slarker.me | US | ✅ |
| rss.wudifeixue.com | CA | ✅ |
| rsshub.isrss.com | US | ✅ |

**半可用**：rsshub.ktachibana.party（✅ 但 429 限流频繁，重试可用）。
**不可用**：rsshub.app（代理 403）、rss.owo.nz / rss.tips（502）、rss.datuan.dev（403）、cups.moe / 4040940.xyz（HTML 应用壳）、pseudoyu / henry.wang / umzzz / email-once / littlebaby / holoxx / spri（超时或解析失败）。

**用法**：实例地址直接换前缀 — `webtool feed --add 名字 https://hub.slarker.me/路由`；429 时轮换实例前缀而非换源。限流表现：同实例高频会 429，跨实例可分散。

## ❌ 放弃（实测不可用）
- engadget（403 cffi）、bleepingcomputer（403）、solidot（403）
- ~~qbitai 量子位~~ → 复测已通! curl 裸 UA 403, webtool 反探测指纹通道 200 (v1.8.0 价值实证)
- techcrunch/theverge 部分 CDN 对数据中心 IP 抖动 → techcrunch 直连超时
- cnbeta（DNS 挂）、dongqiudi（567）、infzm（404）、thn feedburner（超时）

## 已沉淀为自定义源（webtool feed 现状）
r36kr / rbili / rjuejin（RSSHub）+ myblog / hn_daily；官方类按需 `--add`。

## 用法
```bash
webtool feed theverge ieee_ai -n 5          # 任意 URL 直接喂
webtool feed --add mittr https://www.technologyreview.com/feed/ "MIT科技评论"
webtool feed r36kr --new-only               # RSSHub 源走增量
```
