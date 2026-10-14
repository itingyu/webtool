# feed 源

原则：能用官方 feed 就用官方（稳定、无限流），官方被墙/壳化/需 cookie 的走 RSSHub 公共实例。「官方优先」的判据不是「有没有 feed」，而是「这个 feed 含不含你要的栏目」—— `feed radar` 会交叉校验官网 feed 栏目分布与路由目标栏目，`--no-xcheck` 关掉。

## 种子源（`src/webtool/data/feeds.seed.json`）

111 个源，两种形态：

```json
"zhihu_weekly": {"url": "https://hub.slarker.me/zhihu/weekly", "desc": "知乎周刊 (RSSHub)"}
"sspai":       {"url": "https://sspai.com/feed", "desc": "少数派文章", "default": true}
```

- 数据里**没有分类字段**，分类信息只写在 `desc` 前缀里，按类别统计只能解析 `desc`
- 带 `default` 的源决定无参 `webtool feed` 的默认集合

合并规则（`feeds/sources.py:_seed_user_feeds`）：**只增不覆盖** —— 用户 `~/.webtool/feeds.json` 里已存在的同名项保留，缺失的从 seed 补入；`WEBTOOL_NO_SEED=1` 关闭。

构成：国际科技媒体官方 feed（ArsTechnica / TechCrunch / TheVerge / Wired / MITTechnologyReview 等）、arXiv 4 源、中文科技（sspai / ithome / ifanr / ruanyifeng / github_blog）、安全（krebs / anquanke）、中文社区（v2ex / cnode / juejin_rss / leiphone）、RSSHub 路由（zhihu_weekly / zhihu_daily / LinuxDo 三源）。

已知取不到数据的：arXiv 4 源周末 `skipDays` 空 feed（正常现象，不是故障）；LinuxDo 3 源 CF 403，需登录态。

网上流传的「官方可用」清单里有些源并不在本仓（kr36 / qbitai / producthunt / geekpark），要用得自己 `--add`。

## 官网挂了的站点走 RSSHub 路由

| 站点 | 路由 | 说明 |
|---|---|---|
| B站综合热门 | `/bilibili/popular/all` | 可用 |
| 知乎日报/周刊 | `/zhihu/daily` `/zhihu/weekly` | 可用；`hotlist` 429，知乎热榜改用 `rank zhihu` |
| 微博 | `/weibo/search/hot` 等 | 需 cookie，公共实例基本挂；改用 `rank weibo` |
| Solidot | `/solidot` | 公共实例超时，需自建 |

## 公共实例池

配置在 `src/webtool/data/instances.json`：`rsshub.rssforever.com`(AE) / `hub.slarker.me`(US) / `rss.wudifeixue.com`(CA) / `rsshub.isrss.com`(US)。`rsshub.app` 403、`owo.nz` 502、`rsshub.ktachibana.party` 频繁 429 —— 不要在代码里写死实例，走 `--instance` / 用户覆盖。

```sh
webtool feed instances                                  # 探活, 默认挑最快
webtool feed radar bilibili --pick 1 --example --add rbili
```

`feed radar` 开关：`--pick N` 选第几条路由、`--example` 用官方示例路径填参、`--top N` 用第 N 条真实样例填参、`--radar-refresh` 刷新路由库缓存（默认 7 天）、`--no-xcheck` 跳过官网交叉校验、`--items` 输出校验后的完整条目。
