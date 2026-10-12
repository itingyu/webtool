# feed 源清单（2026-10-12 复核）

原则：**能用官方 feed 用官方**（稳定、无限流）；官方被墙/壳化/需 cookie 的走 RSSHub 公共实例。
「官方优先」的判据不是"有没有 feed"，而是"这个 feed 含不含你要的栏目"——`feed radar`
会交叉校验官网 feed 栏目分布与路由目标栏目，可用 `--no-xcheck` 关掉。

## 随包种子（`src/webtool/data/feeds.seed.json`）

**111 个源**。数据结构极简，只有两种形态：

```json
"zhihu_weekly": {"url": "https://hub.slarker.me/zhihu/weekly", "desc": "知乎周刊 (RSSHub)"}
"sspai":       {"url": "https://sspai.com/feed", "desc": "少数派文章", "default": true}
```

- 104 个只有 `url` + `desc`；7 个额外带 `default`（是否默认启用）
- **没有分类字段**——分类信息只写在 `desc` 前缀里（如 `🌐 科技媒体 · valid`），
  所以按类别统计必须靠 `desc` 字符串解析，不能靠结构化字段
- 7 个带 `default` 的源：`sspai` `ithome` `ifanr` `ruanyifeng` `github_blog`
  为 `true`；`cnode` `v2ex` 为 `false`

### seed 合并规则

`feeds/sources.py:_seed_user_feeds()`：**只增不覆盖**。用户 `~/.webtool/feeds.json`
里已存在的同名项保留（用户改动不丢），缺失的才从 seed 补入。

- `WEBTOOL_NO_SEED=1` 可关闭
- 装包时 `setup.py` 钩子并入，运行时还有兜底

当前本机 `~/.webtool/feeds.json` 实有 **124** 个源（111 seed + 用户自加 + 历史合并结果）。

## 种子里的源构成

按 `desc` 前缀粗分，主体是**国际科技媒体官方 feed** 与 **RSSHub 路由**两大类：

| 类别 | 样例 |
|---|---|
| 国际科技媒体（官方直连） | ArsTechnica / TechCrunch / TheVerge / Wired / MITTechnologyReview |
| 学术（官方直连） | `arXivAI` `arXivNLP` `arXiv计算机视觉` `arXiv机器学习`（4 个，走 export.arxiv.org） |
| 中文科技（官方直连） | `sspai` 少数派 / `ithome` IT之家 / `ifanr` 爱范儿 / `ruanyifeng` 阮一峰周刊 / `github_blog` |
| 安全 | `krebs` krebsonsecurity.com / `anquanke` 安全内参 |
| 中文社区（官方 feed，稳定性一般） | `v2ex` v2ex.com/index.xml / `cnode` cnodejs.org/rss / `juejin_rss` juejin.cn/rss / `leiphone` 雷锋网 |
| RSSHub 路由 | `zhihu_weekly` / `zhihu_daily`（hub.slarker.me）、`LinuxDo最新帖子` / `LinuxDo最新话题` / `LinuxDo热门话题` |

已知取不到数据的：
- arXiv 4 源周末 skipDays 空 feed —— 属正常现象，不是故障
- LinuxDo 3 源 CF 403，需登录态

> 注意：网上流传的"官方实测可用"清单里有些源**并不在本仓**（kr36、qbitai、
> producthunt、geekpark 均不在 `feeds.seed.json`）。要用得自己 `--add`。

## 官方挂 → RSSHub 路由兜底

| 站点 | 路由 | 说明 |
|---|---|---|
| B站综合热门 | `/bilibili/popular/all` | 实例实测可用 |
| 知乎日报/周刊 | `/zhihu/daily` `/zhihu/weekly` | 可用；hotlist 429，知乎热榜改用 `rank zhihu` |
| 微博 | `/weibo/search/hot` 等 | 需 cookie，公共实例基本挂；改用 `rank weibo` |
| Solidot | `/solidot` | 公共实例超时，需自建 |

## RSSHub 公共实例池

配置在 `src/webtool/data/instances.json`：

```
rsshub.rssforever.com  (AE)
hub.slarker.me         (US)
rss.wudifeixue.com      (CA)
rsshub.isrss.com        (US)
```

半可用：`rsshub.ktachibana.party`（429 频繁）。
已挂/壳页：`rsshub.app`（403）、`owo.nz`（502）等。

```sh
webtool feed instances              # 探活, 默认自动挑最快的
webtool feed radar bilibili --pick 1 --example --add rbili
```

`feed radar` 相关开关：`--pick N` 选第几条路由、`--example` 用官方 example 路径
填参、`--radar-refresh` 强制刷新路由库缓存（默认 7 天）、`--no-xcheck` 跳过
与官网 feed 的交叉校验、`--items` 输出校验后的完整条目。
