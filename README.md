# webtool

Agent 友好的免费网页搜索 + 内容获取 CLI。零硬依赖，输出纯净 markdown/text/json，去广告省 token。

## 为什么做这个

Agent 抓网页的痛点：广告/导航/页头页尾占 90%+ token、HTML 噪声大、搜索 API 都要 key。
webtool 用 **Bing RSS + 搜狗** 两个免费引擎 + **trafilatura** 正文提取，实测压缩到原文 **1.6%**（省 98% token）。

## 安装

```bash
pip install -e .                  # 零硬依赖, 搜索+基础fetch即可用
pip install -e '.[full]'          # 推荐: trafilatura 提取 + socks 代理支持
```

## 快速上手

```bash
# 1. 配代理(可选, 支持断线自动降级直连)
webtool proxy set http://127.0.0.1:2080
webtool proxy test

# 2. 搜索 (双引擎合并, json 输出)
webtool search "fastapi 部署 docker" -e bing,sogou -n 5 --resolve-links

# 3. 抓正文 (默认 markdown, 自动去广告)
webtool fetch https://www.jb51.net/article/277965.htm --max-chars 4000

# 4. 结构化输出 (带元数据)
webtool fetch <url> -f json --with-metadata --max-chars 2000
```

## 命令

| 命令 | 说明 |
|---|---|
| `webtool search <query>` | 多引擎搜索。`-e` 引擎(bing,sogou) `-n` 条数 `--market zh-CN/en-US` `--resolve-links` 解析搜狗跳转链 |
| `webtool fetch <url>` | 抓取+提取正文。`-f markdown/text/json/html` `--max-chars N` 截断 `--raw` 原始HTML `--url-file` 批量 |
| `webtool proxy get/set/unset/test` | 代理配置, 存 `~/.webtool/config.json`, 支持 http/socks5 |
| `webtool engines [--check]` | 引擎健康检查 |
| `webtool cache clear/info` | 缓存管理 |

全局 flag: `--proxy` 临时代理、`--no-cache` 跳过缓存。

## 省 token 设计

1. 正文提取：trafilatura → readability-lxml → html2text → inscriptis 四级兜底，自动去广告/导航/脚本
2. `--max-chars`：硬截断，Agent 直接控制上下文大小
3. 搜索只回 title+url+snippet，需要正文再 fetch（两步制，省 token）
4. 缓存分桶 TTL：搜索 30min / 正文 24h / 跳转解析 7d
5. markdown 默认带 title/date/hostname frontmatter，Agent 不用再猜

## 代理设计

```jsonc
// ~/.webtool/config.json
{
  "proxy": "http://127.0.0.1:2080",       // 全局
  "engine_proxy": {"bing": null, "sogou": null},  // 每引擎覆盖(null=强制直连)
  "fetch_proxy": null,                     // fetch 专用
  "timeout": 15
}
```

自动降级（`resilient.py`）：
- 代理连不上/超时/429/5xx → 自动切直连重试
- 连续 2 次失败 → 60s 冷却期内直连优先，代理恢复自动切回
- json 输出带 `via: proxy|direct` 字段，Agent 可感知降级

## 引擎说明（全部免费无 key）

| 引擎 | 通道 | 特点 |
|---|---|---|
| bing | cn.bing.com RSS 接口 | 免key免JS，国内外直连，支持 setmkt/setlang/翻页 |
| sogou | 搜狗网页 HTML | 中文覆盖好（腾讯系），link 跳转链自动解析 |

实测数据见 `docs/design.md`（Google 需 JS 渲染、DDG 有 anomaly 盾、百度需验证码，均不可纯 HTTP 抓取，故未收录）。

## 站内搜索（与搜索引擎区分）

`webtool site <site> <query>` 走知名站点的**官方/公开接口**，只做站内检索，不当通用搜索引擎用：

| site | 说明 | site | 说明 |
|---|---|---|---|
| github | 仓库搜索（★/语言/更新时间） | csdn | CSDN 博客 |
| so | Stack Overflow 问答 | juejin | 掘金文章 |
| hn | Hacker News（Algolia 官方 API） | bilibili | B站视频（播放数排序参考） |
| wikipedia | 维基百科（`--lang en/zh/...`） | sspai | 少数派文章 |
| arxiv | arXiv 论文（作者/日期） | npm | npm 包 |

```bash
webtool site list                            # 列出全部站点
webtool site github fastapi -n 5             # JSON 输出带 stars/lang
webtool site wikipedia 机器学习 --lang zh
```

反爬一致性（实测）：所有站点统一 Chrome 131 浏览器 UA + XHR 指纹（Sec-Ch-Ua/Sec-Fetch/Referer/Origin 与真人浏览器一致）；裸 python UA 打 B站直接 412，浏览器 UA 全部 200。不用带项目联系方式的 tool UA。

## 局限与后续

- 不做 JS 渲染（SPA 页面 fetch 空时会有 hint 提示）
- 知乎正文 403（需登录态）；百度/Google/DDG 搜索不可纯 HTTP
- V2 计划：docling PDF 提取、SearXNG 自托管接入、cookie 池
