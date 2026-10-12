# webtool

网页搜索与内容获取 CLI。输出 markdown/text/json。

## 安装

```bash
pip install 'git+https://github.com/itingyu/webtool'
# 依赖含 trafilatura / curl_cffi / pysocks 等, 随安装自动装
```

## 命令

```bash
webtool search "LLM 排行榜" -n 5              # 多引擎: bing,sogou,baidu (默认) / google / marginalia
webtool fetch <url> --max-chars 4000          # 正文提取 → markdown (text/json/html)
webtool rank                                  # 榜单清单 (19 源热榜)
webtool rank zhihu weibo -q "汽车"            # 语义筛选 + 跨源重排
webtool feed                                  # 源清单 (7 预设 + 104 种子)
webtool feed sspai ithome --new-only          # 抓 feed, 增量模式
webtool feed radar 36kr --pick 1 --example    # 查 RSSHub 路由库 → 填参 → 拉数据
webtool feed instances                        # 公共实例探活
webtool feed health                           # 坏源登记表
webtool site github fastapi                   # 站内搜索 (20 站点)
webtool zen "问题"                            # OpenCode Zen 免费层对话, 无需 key
webtool proxy set http://127.0.0.1:2080       # 代理 (google 等被墙源必须)
```

## 功能

### search
- 引擎：bing（直连）/ sogou（直连）/ baidu（直连）/ google（必须代理，429 降级 news RSS，链接已还原原文 URL）/ marginalia
- `-e` 组合引擎；跳转链默认自动解码；query 精简（核心实体 + 意图词，优先英文）
- 低质量批带 `quality_hint` 提示，按提示改词重搜

### fetch
- HTML → markdown/text/json/html；SPA 壳页收割内嵌 SSR state，拿不到时显式报错
- 按 UA 分流的站点：`--profile chrome131_android` 切移动指纹重试
- `--url-file` 批量；`--raw`；`--with-metadata`

### rank
19 源：zhihu / weibo / baidu / douyin / douyin_hot / toutiao / toutiao_hot / bili_hot / bili_rank / bili_word / tieba / sina_hot / douban_movie / netease_music / ithome / hn_official / github_trend / lobsters / reddit。
无参数 = 清单；指定源按源分组原序输出；`-q` BM25 语义筛选 + 跨源重排；`-t` 默认 0.15，`-t 0` 只列清单。

### feed
- 任意 RSS/Atom URL 直接喂；`--add NAME URL [desc]` / `--del NAME`（`~/.webtool/feeds.json`，预设不可删）
- 104 个种子源随包分发，安装时自动并入（只增不覆盖；`WEBTOOL_NO_SEED=1` 关）
- `--new-only` 增量；`-q/-t` 同 rank
- 坏源失败自动登记：`feed health` / `--retest KEY|all` / `--mark KEY [URL] "备注"`
- feed radar：RSSHub 官方路由库查询（缓存 7 天）
  ```bash
  webtool feed radar 36kr                       # 搜路由卡片
  webtool feed radar 36kr --pick 2 --param category=newsflashes   # 填参拉数据
  webtool feed radar 36kr --pick 2 --example    # 官方示例路径 (免填参)
  webtool feed radar --from-url <页面URL>        # 反推路由
  webtool feed radar 36kr --pick 2 --example --add r36kr   # 落地订阅源
  ```
- feed instances：实例探活，默认挑最快的
- 公共实例：rsshub.rssforever.com / hub.slarker.me / rss.wudifeixue.com / rsshub.isrss.com；429 时轮换前缀

### site
20 站点：github / so / hn / wikipedia / arxiv / csdn / csdn_so / juejin / juejin2 / bilibili / bili2 / sspai / npm / npmjs_github / thepaper / eastmoney / sov2ex / douban / gh_search / v2ex。
JSON 扩展见 `docs/custom-sites.md`（`~/.webtool/sites/*.json`）。

### zen
```bash
webtool zen "你好"                    # 默认 big-pickle
webtool zen "问题" --model ling-3.1-flash-free
webtool zen --list-free               # 免费模型清单 (实时拉)
webtool zen "问题" --system "只回 JSON" --tool-choice none
```
模型上下架频繁，先 `--list-free` 再用；403 FreeTierError = 模型已下架。

## 通用约定

- `-n` 条数 / `-f` 格式（`md`≡`markdown`、`txt`≡`text`，大小写不敏感）/ `-o` 落盘（按 `-f` 补扩展名）/ `--no-cache` / `--no-proxy`
- 退出码：0 成功 / 2 用法错误（提示走 stderr）
- 缓存 TTL：search 60s / fetch 10s / 跳转解析 10min（`config set cache_ttl.<桶>=<秒>` 覆盖）
- 出网全走浏览器指纹，直连优先、失败才探活代理重试；google / docs.rsshub.app 必须代理
- 报错自带处置建议，照做即可

## 扩展

七类插件：搜索引擎（`engine`）、榜单源（`hot`）、站内站点（`site`）、正文提取器（`extractor`）、跳转链解码器（`resolver`）、结果过滤器（`filter`）、结果改写（`transformer`）。清单在 `src/webtool/data/plugins.json`，用户在 `~/.webtool/plugins.json` 可覆盖或追加，无需改代码：

```jsonc
// ~/.webtool/plugins.json
{
  "engine": {
    "bing": {"base": 0.6},                              // 改权重 (默认 0.9)
    "my_eng": {"module": "mypkg.search:run", "desc": "自建引擎"}
  },
  "extractor": {
    "my_ext": {"module": "mypkg.extract:run", "desc": "自定义提取器"}
  }
}
```

各类函数签名：

| 类别 | 签名 | 说明 |
|---|---|---|
| `engine` | `(query, max_results, proxy, timeout, market) -> [结果]` | `base` 决定排序权重 |
| `hot` | `(query, limit, proxy, timeout) -> [结果]` | `search` 决定能否直接传关键词 |
| `site` | `(query, limit, proxy, timeout, **kw) -> [结果]` | `proxy` 为 `direct`/`proxy` |
| `extractor` | `(html, url, meta) -> (正文, meta)` | 返回 `('' , {...})` 表示降级 |
| `resolver` | `(url, proxy, timeout) -> 新 url` | `match` 指认跳转链特征 |
| `filter` | `(results, ctx) -> [结果]` | 剔除不该出现在结果里的条目 |
| `transformer` | `(results, ctx) -> [结果]` | 补字段、改写 url 等 |

- `module` 格式 `包路径:函数名`
- 三层来源，后者覆盖前者：包内 JSON → 用户 JSON → `WEBTOOL_PLUGIN_DIR`（默认 `~/.webtool/plugins`，放外部 `.py` 后在配置里指向）
- 顺序即优先级：`hot`/`extractor`/`filter`/`transformer` 按插入顺序执行；提取器首个返回非空正文的生效
- 过滤规则同样可配：`~/.webtool/filters.json` 覆盖 `adfilter`（广告词/域名）、`blocklist`（低质站点）、`merge`（词典先验域/跟踪参数/短实体表）、`spa`（内嵌 state 挂载点追加）
- 引擎行为参数在 `engine.<name>.params`：`rate`（请求间隔秒）、`captcha_signs`（验证页指纹 `[算子,值]`，算子 contains/title_contains/len_lt）、`cooldown`（触发后静默秒）
- 启停：`webtool plugins enable|disable <kind> <name>`（写用户清单翻转 `enabled`，mtime 自动生效）；被禁用的插件在 `plugins list --all` 与 status 里仍可见（state=disabled）
- RSSHub 公共实例表在 `data/instances.json`（用户可建 `~/.webtool/instances.json` 同构覆盖）

### 跳转链解码

搜狗 `/link`、百度 `/link?`、Google News `/articles/` 这类跳转链会被还原成原始 URL（`--no-resolve` 关闭）。这一层是 `resolver` 插件，与引擎无关——**按 URL 特征认链，不是按结果来自哪个引擎**：

```jsonc
// ~/.webtool/plugins.json
{
  "resolver": {
    "myshort": {"module": "mypkg.deLink:resolve", "match": ["~t\\.co/"]}
  }
}
```

`match` 里普通字符串按子串匹配（域名和整条 URL 都比），`~` 开头按正则匹配整条 URL。加自己的短链服务只需照此声明一条。

### 热更新

| 改什么 | 生效方式 |
|---|---|
| `~/.webtool/plugins.json` 增删改条目 | **自动**（按 mtime 判定失效，同进程内立即生效） |
| `~/.webtool/filters.json` 过滤规则 | **自动**（同上） |
| 外部插件 `.py` 文件内容 | `webtool plugins reload`（Python 缓存了已导入模块，需显式重载） |
| 装饰器 `@register` 注册的代码 | 重启进程 |

`webtool plugins list`（清单与来源：builtin/user/code）、`plugins check`（逐个加载体检，报失败项）、`plugins reload`（重载外部模块并清配置缓存）。配置坏了不会拖垮进程，退回内置默认并在 `plugins check` 报错。

## 给 Agent 用

复制 `skills/webtool/SKILL.md` 到 Agent 的 skill 目录（Claude Code `.claude/skills/`、Minis `/var/minis/skills/`）。

深入文档：`docs/coding-standard.md`（**编码规范/分层，改代码先读**）· `docs/design.md`（架构）· `docs/feed-sources.md`（feed 源实测）· `docs/custom-sites.md`（site 扩展）· `docs/engine-notes.md`（引擎通道记录）。
