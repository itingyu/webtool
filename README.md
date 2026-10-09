# webtool

免费、免 key 的 Agent 网页工具：**多引擎搜索 + 站内搜索 + 正文提取**，输出纯净 markdown/text/json，实测 HTML→正文压缩到 1.6%（省 98% token）。

## 功能

| 功能 | 说明 |
|---|---|
| 🔍 多引擎搜索 | Bing RSS / 搜狗 / 百度（TLS 指纹突破风控）/ Google News，全部免 key |
| 🌐 站内搜索 | 10 站点官方 API：GitHub、Stack Overflow、HN、Wikipedia、arXiv、CSDN、掘金、B站、少数派、npm；JSON 配置可自定义扩展 |
| 📄 正文提取 | trafilatura 四级降级链，HTML→纯净 markdown/json，去广告/导航/页眉 |
| 🧹 结果清洗 | 跨引擎去重、内容农场黑名单（21 内置可自定义）、广告识别、语义加权排序、权重阈值 |
| 🛡️ 反反爬 | 浏览器 TLS 指纹、验证页识别+冷却、代理断线自动降级直连 |
| ⚡ Agent 友好 | 全 JSON 输出、token 极省、错误信息带处置建议、结果缓存 |

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
webtool proxy set http://127.0.0.1:2080        # 配代理(可选, 断线自动直连)
webtool search "fastapi 教程" -e bing,baidu -n 5   # 多引擎搜索
webtool fetch <url> -f markdown --max-chars 4000   # 提取正文
webtool site github fastapi                        # 站内搜索
```

## 命令速查

| 命令 | 说明 |
|---|---|
| `search <q>` | `-e` 引擎组合 `-n` 条数 `--min-weight N` 权重阈值 `--block/--allow` 临时黑白名单 |
| `fetch <url>` | `-f markdown/text/json/html` `--max-chars` `--raw` `--url-file` 批量 |
| `site <site> <q>` | 站内搜索；`site list` 查全部，`docs/custom-sites.md` 自定义 |
| `proxy set/test/unset` | 代理配置（http/socks5） |
| `blocklist show/add/remove/reset` | 黑名单管理 |
| `engines --check` / `cache clear/info` | 健康检查 / 缓存 |

过滤开关：`--no-blocklist` `--no-weight-filter`（默认剔权重垫底 15%）`--keep-ad` `--no-dedupe` `--no-semantic`。每层剔除量回显在 `filters_applied` 字段。

## 给 Agent 用（skill）

复制 `skills/webtool/SKILL.md` 到 Agent 的 skill 目录（如 Claude Code `.claude/skills/`、Minis `/var/minis/skills/`）即可让 Agent 自动学会用法。

## 局限

- 不做 JS 渲染（SPA 页 fetch 空时返回 hint）
- 知乎正文 403（需登录态）；Google 仅 News RSS（Web 搜索需 JS）
