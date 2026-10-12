# 抖音搜索探测结论（2026-10-11 实测，2026-10-12 复核）

## 结论：纯 HTTP 无免登录搜索通道，不接入 rank/site

抖音内容搜索未做成插件。热榜（rank）是另一回事，已支持。

## 探测明细（全部 200/404，无一返回数据）

| 通道 | 结果 |
|---|---|
| `iesdouyin.com/web/api/v2/search/item/` | `status_code:1, Url doesn't match`（接口已下线/改路径） |
| `iesdouyin.com/web/api/v2/general/search/single/` | 同上 |
| `iesdouyin.com/web/discover/search/item/` | 404 HTML |
| `iesdouyin.com/web/api/v2/hotsearch/suggestions/` | `Url doesn't match` |
| `douyin.com/aweme/v1/web/search/item/`（无签名） | `status_code:2483`, `aweme_list=null` —— **需 a_bogus/msToken 签名** |
| `douyin.com/search/<kw>` 搜索页 | 72KB 纯 JS 混淆壳（`_$jsvmprt` VM 保护），无 RENDER_DATA/SSR，数据全走客户端 XHR |
| `so.douyin.com/aweme/v1/web/general/search/single/` | 3KB JS 引导壳，非 JSON |

## 为什么不硬做

1. `aweme/v1/web/search/item` 的 `a_bogus` 参数由 VM 混淆 JS 生成（依赖 UA/时间戳/
   滚动熵），纯 Python 复刻 = 维护无底洞（字节每几周一改）
2. 搜索页客户端渲染，无 SSR 数据可收割（对比：头条 m 站给 350KB SSR，所以 toutiao 能做）
3. 热榜是免签名的，`rank` 的 douyin / douyin_hot 两源已覆盖「抖音现在大家在搜什么」

## 替代路径

### 抖音热榜 + 语义筛选（有限，慎用）

```sh
webtool rank douyin              # 热搜词榜, 50 词
webtool rank douyin_hot          # 热点榜 (事件聚合+视频数)
```

`-q` 走本地 BM25 筛选，但**存在回退行为**：相似度低于 `threshold`（0.15）时，
程序会告警 `threshold 0.15 筛空全榜, 回退全量` 并返回**整榜无关结果**。

实测 `rank douyin -q "AI"` 筛空后回退，返回的是「冰雪大世界官宣联名迪士尼」
这类与 AI 无关的热词。所以：

> `-q` 只适合在榜内做粗筛（能命中相关词时才有效），**不能当作内容搜索用**。
> 必须检查 stderr 有没有 `回退全量` 告警，否则会把无关结果误当命中。

### 同类短视频内容

```sh
webtool site bili2 "关键词"       # B站视频搜索
```

### 真要全量抖音搜索

需 headless 浏览器（playwright + 反指纹），超出 webtool 纯 HTTP 定位。
