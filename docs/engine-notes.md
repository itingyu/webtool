引擎实测笔记 (Google News RSS / Baidu / 广告过滤 / --no-proxy)

结论基于 2026-10-09 实测，2026-10-12 复核当前实现。

1. Google Web 搜索: 不可行 (JS 壳页 / 429 sorry)。
   Google News RSS 可行: news.google.com/rss/search?q=..&hl=..&ceid=.. 免 key,
   100 条/次。
   文章链接是 news.google.com/rss/articles/CBMi.. 跳转链。旧 base64 方案已失效
   (HTTP 400)。当前解码走 gnews batchexecute 反查通道 (webtool/engines/gnews.py:
   decode())，经 engines/google.py:resolve_link() 挂为 resolver 插件 gnews。
   注意: 该通道依赖上游, 上游未解析出时返回 None, 不是异常 —— 属于预期行为,
   不是 bug。
2. Baidu: 可行但限频。先 GET www.baidu.com/ 领 cookie, 再带 Referer 搜索,
   成功率约 3/4 (其余返回安全验证页 1438B); 识别特征: len<10000 或含"安全验证"。
   解析: <h3 class="...title..."><a href="http://www.baidu.com/link?url=..">
   标题</a></h3>, 跳转链 302 Location 即真实 URL (无需 cookie)。
   mu= 属性有真实 URL 但混入 recommend_list/nourl 内部域, 不可靠。
3. Baidu 广告: 搜索结果页广告节点用 result-op c-container + 部分带
   cr-content; 自然结果 = result c-container。正文推广词出现在 CSS (误报),
   按块级判断: class 含 result-op 的聚合一律标记 is_ad=true 可过滤;
   tuiguang 词在本次页面 CSS 中, 需在块内检测。
4. Bing RSS 无广告注入 (RSS feed 本身无广告位)。
5. 通用广告过滤: title/snippet 命中广告词表 + url 命中广告域 → is_ad。
   规则已外置到 src/webtool/data/filters.json 的 adfilter 段:
   keywords 18 / domains 5 / url_patterns 1。

跳转链解码插件 (plugins.json → resolver 段, 共 3 个):
- sogou  → webtool.engines.sogou:resolve_link
- baidu  → webtool.engines.baidu:_resolve_one
- gnews  → webtool.engines.google:resolve_link

踩坑记录: google.py 曾写成 `from webtool import gnews` (错误路径, gnews 实际在
engines/ 下), 导致 gnews resolver 一调用就 ImportError。已改为
`from webtool.engines import gnews`。
