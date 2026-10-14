# 抖音：只做热榜，不做内容搜索

抖音内容搜索没有免登录的纯 HTTP 通道，不接入 `rank` / `site`；热榜是免签名的，`rank` 的 `douyin` / `douyin_hot` 两源已覆盖。

不要再试这些通道：`iesdouyin.com` 的 `web/api/v2/search/*` 系列已下线（回 `Url doesn't match` 或 404），`douyin.com/aweme/v1/web/search/item` 需要 `a_bogus`/`msToken` 签名（无签名回 `status_code:2483`），搜索页是 VM 混淆的 JS 壳（无 RENDER_DATA/SSR）。`a_bogus` 由混淆 JS 按 UA/时间戳生成，纯 Python 复刻维护不起；要做只能上 headless 浏览器，超出本工具的定位。

## `-q` 在热榜上的回退行为

```sh
webtool rank douyin -q "AI"      # 热搜词榜; 另有 douyin_hot 热点榜
```

BM25 筛选后的相似度全部低于阈值（默认 0.15）时会**回退全量**：stderr 打 `threshold 0.15 筛空全榜, 回退全量`，返回的是整榜无关热词。所以 `-q` 只适合榜内粗筛（能命中相关词时才有效），不能当内容搜索用 —— 每次都要看 stderr 有没有「回退全量」，否则会把无关结果当成命中。

短视频内容搜索可用 `webtool site bili2 "关键词"`（B站）。
