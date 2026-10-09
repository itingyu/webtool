# webtool

免费、免 key 的 Agent 网页工具：**多引擎搜索 + 站内搜索 + 正文提取**，输出纯净 markdown/text/json，实测 HTML→正文压缩到 1.6%（省 98% token）。

## 功能

| 功能 | 说明 |
|---|---|
| 🔍 多引擎搜索 | Bing RSS / 搜狗 / 百度（TLS 指纹突破风控）/ Google News，全部免 key |
| 🌐 站内搜索 | 10 站点官方 API：GitHub、Stack Overflow、HN、Wikipedia、arXiv、CSDN、掘金、B站、少数派、npm；JSON 配置可自定义扩展 |
| 📄 正文提取 | trafilatura 四级降级链，HTML→纯净 markdown/text/json(/html)，去广告/导航/页眉 |
| 🧹 结果清洗 | 跨引擎去重、内容农场黑名单（21 内置可自定义）、广告识别、语义加权排序、权重阈值 |
| 🛡️ 反反爬 | 浏览器 TLS 指纹、验证页识别+冷却、代理断线自动降级直连 |
| ⚙️ 持久化配置 | `config` 子命令管理默认引擎/格式/过滤开关/单引擎代理，即时写盘 |
| ⚡ Agent 友好 | json/text/markdown 三格式信息对齐、token 极省、错误带处置建议、结果缓存 |

## 安装

```bash
# 从 GitHub（推荐）
pip install 'git+https://github.com/itingyu/webtool#egg=webtool[tls]'

# 或 clone 后本地装
git clone git@github.com:itingyu/webtool.git && cd webtool
pip install -e '.[tls]'
```

可选 extra：`tls`（curl_cffi，百度必需）、`extract`（trafilatura 最佳提取）、`socks`、`full`（全量）。

## 快速上手

```bash
webtool proxy set http://127.0.0.1:2080            # 配代理(可选, 断线自动直连)
webtool config set default_engines bing,baidu      # 持久化默认配置
webtool search "fastapi 教程" -n 5                 # 多引擎搜索(合并/去重/黑名单/语义排序)
webtool fetch <url> -f markdown --max-chars 4000   # 提取正文
webtool site github fastapi                        # 站内搜索
```

## 命令速查

| 命令 | 说明 |
|---|---|
| `search <q>` | `-e` 引擎组合 `-n` 条数 `-f json/text/markdown` `--min-weight N` 权重阈值 `--block/--allow` 临时黑白名单 |
| `fetch <url>` | `-f markdown/text/json/html` `--max-chars` `--raw` `--url-file` 批量 |
| `site <site> <q>` | 站内搜索（同支持三格式与过滤链）；`site list` 查全部，`docs/custom-sites.md` 自定义 |
| `config list/get/set/unset` | 持久化配置：默认引擎/格式/权重阈值/各过滤开关/单引擎代理 |
| `proxy set/test/unset` | 代理配置（http/socks5） |
| `blocklist show/add/remove/reset` | 黑名单管理 |
| `engines --check` / `cache clear/info` | 健康检查 / 缓存 |

过滤开关：`--no-blocklist` `--no-weight-filter`（默认剔权重垫底 15%）`--keep-ad` `--no-dedupe` `--no-semantic`。

**三格式与过滤回显**：search/site 的 json/text/markdown 信息量对齐，每层剔除量（广告/黑名单/权重/去重）三种格式都回显并附撤销参数——json `filters_applied` 字段、text 末尾 `—` 行、markdown `**过滤统计**` 块。

**持久化配置**（`webtool config set <k> <v>`，写 `~/.webtool/config.json`，CLI 参数运行时覆盖）：

| key | 说明 | 示例 |
|---|---|---|
| `default_engines` | 默认引擎组合 | `bing,baidu` |
| `default_format` | 默认输出格式 | `markdown` |
| `min_weight` | 默认权重阈值 | `0.5` |
| `blocklist` / `ad_filter` / `weight_filter` / `dedupe` / `semantic` | 各过滤开关 | `on` / `off` |
| `engine_proxy.<engine>` | 单引擎代理 | `engine_proxy.google http://...` |
| `timeout` / `cache` | 超时秒数 / 缓存开关 | `25` / `off` |

## 黑名单与过滤

| 层 | 说明 | 关闭 |
|---|---|---|
| 广告 | baidu result-op 卡片 + 广告词/域名识别 | `--keep-ad` 只标记 |
| 黑名单 | 21 内置内容农场；`~/.webtool/blocklist.json` 可加 block/allow（allow 优先） | `--no-blocklist` |
| 权重 | 默认剔垫底 ~15%（至少留 3 条）；`--min-weight 0.8` 显式阈值 | `--no-weight-filter` |

```bash
webtool blocklist add csdn.net                  # 追加黑名单(持久)
webtool blocklist add blog.csdn.net/x --allow   # 白名单例外
webtool search q --block jb51.net               # 临时追加(不落盘)
```

权重公式：`引擎排名衰减(1/√rank) × 引擎可信度 × 多引擎确认加成 × 语义相关度`；每条结果带 `weight`/`sem_score` 字段。

## 引擎说明

| 引擎 | 通道 | 代理需求 |
|---|---|---|
| bing | cn.bing.com RSS（免key免JS，支持 setmkt/翻页） | 直连 |
| sogou | 搜狗网页 HTML，link 跳转链自动解析 | 直连 |
| baidu | `curl_cffi` TLS 指纹模拟（urllib 必被风控），302 解析真实链接 | 直连；需 `[tls]` extra |
| google | Google News RSS（100 条/次，web 搜索不可纯 HTTP） | 需代理 |

site 站内搜索通道与代理策略见 `docs/design.md`，自定义站点配置见 `docs/custom-sites.md`。

## 给 Agent 用（skill）

复制 `skills/webtool/SKILL.md` 到 Agent 的 skill 目录（如 Claude Code `.claude/skills/`、Minis `/var/minis/skills/`）即可让 Agent 自动学会用法。

## 局限

- 不做 JS 渲染（SPA 页 fetch 空时返回 hint）
- 知乎正文 403（需登录态）；Google 仅 News RSS（Web 搜索需 JS）
