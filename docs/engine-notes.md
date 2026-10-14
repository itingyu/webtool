# 引擎通道与解析要点

**Google Web 搜索接不进来**：返回 JS 壳页 / 429 sorry。走 Google News RSS：`news.google.com/rss/search?q=..&hl=..&ceid=..`，免 key，100 条/次，文章链是 `news.google.com/rss/articles/CBMi..` 跳转链，由 `engines/gnews.py::decode()` 经 batchexecute 通道反查，挂成 resolver 插件 `gnews`。该通道依赖上游，解析不出时返回 `None` 而非抛异常 —— 属预期行为。

**Baidu 可行但限频**：先 GET `www.baidu.com/` 领 cookie，再带 Referer 搜索，成功率约 3/4，其余回安全验证页（约 1438B，判定 `len < 10000` 或含「安全验证」）。结果节点 `<h3 class="...title..."><a href=".../link?url=..">`，跳转链 302 的 `Location` 就是真实 URL（不需要 cookie）；`mu=` 属性混着内部域，不可信。

**Baidu 广告**：结果页广告节点是 `result-op c-container`（部分带 `cr-content`），自然结果是 `result c-container`。`tuiguang` 一类词会出现在页面 CSS 里，必须按块级判断，别在整页里搜关键词。Bing RSS 无广告位。

**广告过滤**：`title`/`snippet` 命中关键词表 + url 命中广告域 → `is_ad`，规则在 `data/filters.json` 的 `adfilter` 段（`keywords` / `domains` / `url_patterns`）。

**跳转链 resolver 插件**（`plugins.json` 的 `resolver` 段，共 3 个）：`sogou` → `engines.sogou:resolve_link` · `baidu` → `engines.baidu:_resolve_one` · `gnews` → `engines.google:resolve_link`。
