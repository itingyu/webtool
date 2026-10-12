# feed 源实测清单（2026-10-12）

原则：**能用官方 feed 用官方**（稳定、无限流）；官方被墙/壳化/需 cookie 的走 RSSHub 公共实例。
「官方优先」的判据不是"有没有 feed"，而是"这个 feed 含不含你要的栏目"——`feed radar` 会交叉校验官网 feed 栏目分布与路由目标栏目。

## 随包精选种子（`src/webtool/data/feeds.seed.json`）

**104 个源，14 类**：AI 专题 19 / 技术社区 17 / 大厂技术博客 13 / 前端设计 12 / 编程语言官方 10 / 安全 7 / RSS 工具 5 / 版本追踪 5 / 周刊 4 / 科技媒体 6 / 学术 2 / 新闻 2 / 知乎 2 / RSSHub 路由若干。来自 [JackyST0/awesome-rsshub-routes](https://github.com/JackyST0/awesome-rsshub-routes)，双通道逐条实测。

- 安装时自动并入 `~/.webtool/feeds.json`（setup.py 钩子 + 运行时兜底），**只增不覆盖**用户改动；`WEBTOOL_NO_SEED=1` 关闭
- 实测 98+ 可用；arXiv 4 源周末 skipDays 空 feed 属正常；LinuxDo 3 源 CF 403 需登录态

## 官方 feed 实测可用（直连出数据）

| 名字 | URL | 备注 |
|---|---|---|
| kr36 | https://www.36kr.com/feed | **必须带 www**；30 条 = 主站 10 + 快讯 20，与 RSSHub 路由同源，优先官网 |
| theverge / arstechnica / wired / mittr | 官方 feed | 国际科技媒体 |
| ieee_ai | https://spectrum.ieee.org/feeds/topic/artificial-intelligence.rss | IEEE Spectrum AI |
| arxiv_csai | https://export.arxiv.org/rss/cs.AI | 周末空 feed 正常 |
| producthunt | https://www.producthunt.com/feed | 日榜 |
| krebs / anquanke | 官方 | 安全 |
| juejin_rss / leiphone / geekpark | 官方 | 中文科技 |
| qbitai | 官方 | 曾判定 403，换指纹通道后复测已通——**「官方不可用」的结论有时效，每次换通道要复测** |

（sspai / ithome / ifanr / ruanyifeng / github_blog / v2ex / cnode 为内置预设）

## 官方挂 → RSSHub 路由兜底

| 站点 | 路由 | 状态 |
|---|---|---|
| B站综合热门 | /bilibili/popular/all | ✅ 实例实测 |
| 知乎热榜/日报/周刊 | /zhihu/hotlist /daily /weekly | daily/weekly ✅（hotlist 429，用 rank zhihu 更好） |
| 微博 | /weibo/search/hot 等 | 需 cookie，公共实例挂，用 rank weibo |
| Solidot | /solidot | 公共实例超时，需自建 |

## RSSHub 公共实例池（官方清单全量实测）

可用 4：`rsshub.rssforever.com`(AE) / `hub.slarker.me`(US) / `rss.wudifeixue.com`(CA) / `rsshub.isrss.com`(US)。
半可用：`rsshub.ktachibana.party`（429 频繁）。其余挂/壳页（rsshub.app 403、owo.nz 502 等）。

```sh
webtool feed instances              # 探活今天谁活着, 默认自动挑最快的
webtool feed radar bilibili --pick 1 --example --add rbili   # 路由 → 落地
```

429 时**轮换实例前缀**而非换源；重度用建议自建。

## 放弃清单（2026-10 复测）

engadget 403 / bleepingcomputer 403 / solidot 403 / cnbeta DNS 挂 / dongqiudi 567 / infzm 404 / thn feedburner 超时 / techcrunch 直连抖动（feed 可用但慢）。
