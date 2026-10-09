#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Google (News RSS) + Baidu 引擎扩展 + 广告过滤 + --no-proxy 选项测试记录

实测结论 (2026-10-09):
1. Google Web 搜索: 不可行 (JS壳页/429 sorry)。Google News RSS 可行:
   news.google.com/rss/search?q=..&hl=..&ceid=.. 免key, 100条/次, 但文章链接是
   news.google.com/rss/articles/CBMi.. 跳转链, 新版无法离线解码 (旧 base64
   方案已失效, HTTP 400), 需逐条请求跳转页且页面 JS 渲染拿 data-n-au →
   纯 HTTP 不可解析。方案: 输出保留 Google 跳转链 + title/source/date,
   并在结果里给 google 原搜索 URL 供 Agent 兜底; title 已含来源站名。
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
"""
