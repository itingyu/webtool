# webtool

网页搜索与内容获取 CLI。搜索、抓正文、热榜、RSS、站内搜索、免费层大模型对话、MCP 客户端、股票数据，输出 markdown / text / json。

## 安装

```bash
pip install 'git+https://github.com/itingyu/webtool'
```

依赖全装，没有 extras。发行版保护系统 Python（PEP 668，Kali/Debian/新 Alpine 会报 `externally-managed-environment`）时改用 venv 或 pipx：

```bash
python3 -m venv ~/.webtool-venv && ~/.webtool-venv/bin/pip install 'git+https://github.com/itingyu/webtool'
pipx install 'git+https://github.com/itingyu/webtool'
pip install --user 'git+https://github.com/itingyu/webtool'    # --user 是开关, 不带值
```

Termux 上没有 PyPI 轮子（`cryptography`/`numpy`/`pandas`/`lxml` 要源码构建，rustup 不认 `android` target），先用包管理器装原生库再 pip：

```bash
pkg install tur-repo python-cryptography python-numpy python-pandas python-lxml
pip install 'git+https://github.com/itingyu/webtool'
```

升级与卸载：

```bash
webtool upgrade                    # pip 升级, 线路按 rules.json
webtool upgrade --check            # 只问有没有新版: 退 0 最新 / 1 有新版 / 2 判不出
webtool uninstall                  # 只卸包, ~/.webtool 数据留着
webtool uninstall --purge-data --yes   # 连配置/凭据/缓存一起删 (缺 --yes 则不动手)
```

`webtool -v -f json` 打印版本与运行环境（Python/平台/代码路径/依赖），报障带上它。

## 命令

| 命令 | 用途 |
|---|---|
| `search` | 多引擎网页搜索（含 exa/parallel/firecrawl 语义搜索） |
| `fetch` | 抓 URL 提取正文；二进制直接下载 |
| `rank` | 榜单聚合：19 个热榜源 |
| `feed` | RSS/Atom 订阅抓取，含 RSSHub 路由库查询 |
| `site` | 18 个站点站内搜索 |
| `zen` | OpenCode Zen 免费层对话，无需 key |
| `mcp` | 通用 MCP 客户端 |
| `stock` | 股票：行情/选股/研报 + 1300+ 底层接口 |
| `proxy` | 代理配置、凭据、按域名/IP/端口分流 |
| `config` / `plugins` / `cache` / `blocklist` | 配置、插件、缓存、黑名单 |
| `engines` | 引擎清单与体检 |
| `upgrade` / `uninstall` | 升级、卸载 |

## search

```bash
webtool search "LLM 排行榜" -n 5                # 默认 bing,sogou,baidu
webtool search "query" -e marginalia             # 小站/老网页长尾
webtool search "查询词" --preset zh               # 引擎组合预设
webtool search "query" -e exa,parallel           # 语义引擎
```

- 引擎：`bing` / `sogou` / `baidu` / `so360` / `marginalia`（境内直连）· `google`（被墙，需代理；代理不可用时静默跳过，429 降级 news RSS，结果标 `channel: news`）· `exa` / `parallel` / `firecrawl`（语义搜索，匿名免 key，默认关）
- 默认引擎集 `bing,sogou,baidu`；`--preset zh|en|direct` 用预设组合（`webtool engines presets` 列），优先级 `-e` > `--preset` > `config.default_engines` > 内置默认
- 语义引擎按需加：`exa` 召回条数常最多 / `parallel` 最快且返回带日期 / `firecrawl` 能过 JS（search 免费 500 次/月），与关键词引擎重叠少
- `--operators passthrough|strip|strict` 控制高级操作符（支持 `site:` `intitle:` `inurl:` `-词`）；`--blocklist a.com,b.com` 覆盖黑名单（前缀 `!` 表例外，`off` 关闭）
- 跳转链默认自动解码成真实 URL（`--no-resolve` 关）；结果综合加权排序，`-f json` 看 `weight` 与 `engines`（交叉验证数）
- `webtool engines list|test|presets`：清单与冷却状态 / 实发体检 / 预设组合

## fetch

```bash
webtool fetch <url> --max-chars 4000            # 正文 → markdown
webtool fetch <url> --with-metadata -f json     # 附标题/作者/日期
webtool fetch --url-file urls.txt -o out/       # 批量
webtool fetch <pdf-url> --save /tmp/            # 二进制落盘
```

- HTML → 正文，默认 markdown；`--max-chars N` 截断（默认 0 不截断）；`--raw` 跳过提取吐原始 HTML
- **目标不一定是网页**：按响应头 `Content-Type` 判型（认不出才看 URL 后缀）—— html 才走提取；json/xml/纯文本原样输出；图片/视频/音频/PDF/压缩包/字体直接存文件（默认当前目录，`--save <文件或目录>` 改落点）。结果里给 `kind` / `type` / `file` / `size`。错误页不落盘、二进制不进 stdout
- 二进制流式下载：边收边写 · 断点续传（`.part` + `Range` + `If-Range` 验证器）· 进度条（终端自动刷，`--progress` 强制）· `--jobs N` 多连接分片（最多 4 条，段数随文件大小收敛，服务端不认 Range 自动退回单连接；默认 1）
- 正文提取是**同层择优**：trafilatura / boilerplate / readability 都跑，按碎片率与长度选最干净的；结果里的 `extract` 字段说明是谁出的活。`--extract auto|trafilatura|readability|boilerplate|inscriptis` 可固定（也可 `webtool config set extract <名>`），指定后没产出自动退回 auto
- 拿不到正文：SPA 壳页自动收割内嵌 SSR state；仍拿不到用 `--via auto` 或 `--via firecrawl`。按 UA 分流的站点用 `--profile chrome131_android` / `safari18_4_ios`
- `--via <通道>`：`local`（默认，纯本地，不消耗端点配额）/ `auto`（本地确定性硬失败时才兜底远程 reader）/ `parallel|exa|firecrawl`（直接走对应 MCP 的 fetch）
- `-f txt` 输出纯文本（抹掉 markdown 标记与元数据头）

## rank

19 源：zhihu / weibo / baidu / douyin / douyin_hot / toutiao / toutiao_hot / bili_hot / bili_rank / bili_word / tieba / sina_hot / douban_movie / netease_music / ithome / hn_official / github_trend / lobsters / reddit。

```bash
webtool rank                        # 无参 = 清单 + 用法
webtool rank zhihu weibo -q "汽车"    # 语义筛选 + 跨源重排
webtool rank -t 0                    # 只列清单, 不筛选不重排
```

`-q` 语义筛选词，`-t` 阈值（默认 0.15），`-n` 每源条数（默认 10）。

## feed

```bash
webtool feed                              # 源清单 (内置预设 + 自定义)
webtool feed sspai ithome --new-only      # 抓条目, 只出上次之后的新条目
webtool feed "https://example.com/rss.xml"   # 任意 RSS/Atom URL
webtool feed --add myblog --add <URL> --add "描述"   # 自定义源
webtool feed --del myblog                 # 删自定义源 (预设不可删)
webtool feed health                       # 坏源登记表
webtool feed --retest all                 # 复查坏源, 恢复即移除
webtool feed --mark <key> --mark "原因"    # 人工登记坏源
```

- 111 个种子源随包分发，安装时并入（只增不覆盖，`WEBTOOL_NO_SEED=1` 关）；`--new-only` 状态存 `~/.webtool/feed_state.json`
- `--add` / `--mark` 的值要各写一次旗标

RSSHub 路由库：

```bash
webtool feed radar 36kr                                        # 搜路由卡片
webtool feed radar 36kr --pick 2 --param category=newsflashes   # 填参拉数据
webtool feed radar 36kr --pick 2 --example                      # 官方示例路径
webtool feed radar 36kr --pick 2 --top 2                        # 用真实样例填参
webtool feed radar --from-url <页面URL>                          # 反推路由
webtool feed radar 36kr --pick 2 --example --add r36kr          # 落地成订阅源
```

`--pick` 选第几条命中的路由（不给则取热度最高），`--param` 只作用于选中的那条。默认与官网 feed 交叉校验并据此取数（`--no-xcheck` 关）。实例探活 `webtool feed instances`（默认挑最快）；公共实例 rsshub.rssforever.com / hub.slarker.me / rss.wudifeixue.com / rsshub.isrss.com，429 时轮换 `--instance`。

## site

18 站点：github / gh_search / so / hn / wikipedia / arxiv / csdn / csdn_so / juejin / juejin2 / bilibili / bili2 / sspai / npm / thepaper / eastmoney / sov2ex / douban。

```bash
webtool site list                     # 全部站点 (含自定义)
webtool site github fastapi           # 站内搜
webtool site wikipedia 量子计算 --lang en
```

自定义站点放 `~/.webtool/sites/*.json`（格式见 [docs/custom-sites.md](docs/custom-sites.md)）。

## zen

OpenCode Zen 免费层对话，OpenAI 兼容协议，公开模式无需 key。

```bash
webtool zen "问题"                        # 默认 big-pickle
webtool zen --list-free                   # 免费层清单
webtool zen --list-models                 # 全部模型 id
webtool zen --list-free --check           # 逐个真调验证 (默认只验免费层, --check-all 连收费一起)
webtool zen "问题" --model ling-3.1-flash-free
webtool zen "问题" --system "只回 JSON" --tool-choice none
webtool zen "问题" --tools all            # 工具集: min(默认 bash+read)/all/逗号清单
webtool zen "问题" --think high           # 思考强度 (透传 reasoning_effort, 默认 medium)
webtool zen "问题" --max-tokens 8000
webtool zen "问题" --dry-run              # 打印将发出的请求, 不出网
webtool zen "问题" --show headers         # request(默认)/headers/body/text
webtool zen "问题" --no-sticky            # 会话 id 每次换新 (默认粘性, 按整点轮换)
```

- 模型上下架频繁，先 `--list-free` 再用；清单按命名约定推免费层，能否用只有 `--check` 真调才算数
- `--think` 原样透传上游 `reasoning_effort`，可选值随模型而异，客户端不预判；被上游拒会自动去掉该字段重试一次
- 终端里边收边打、思考与正文分开着色；管道/`-f json` 时一次性输出（`--no-reasoning` 只要答案）
- 默认值写 `~/.webtool/zen.json` 的 `zen` 段（`model` / `max_tokens` / `reasoning_effort` / `system` / `tools` / `tool_choice` / `live` / `extra_body`），优先级 命令行 > zen.json > 内置；换端点改 `chat_url` / `models_url`
- `extra_body` 原样并入请求体（同名字段以它为准），用来补上游扩展字段
- `usage_available: false` 且 `ok: true` = 调用成功但端点不给用量统计；429 按指数退避重试（`--retries`）

## mcp

JSON-RPC 2.0 over Streamable HTTP，纯标准库，不绑死任何 server。

```bash
webtool mcp probe exa                            # 端点体检
webtool mcp list exa                             # 列工具 (name/描述/参数)
webtool mcp call exa web_search_exa --arg query="..." --arg numResults=3
webtool mcp call https://my.site/mcp my_tool '{"k":"v"}'
```

- 传参两条通道：`--arg k=v`（可多次，值按 JSON 字面量猜类型）或位置 JSON；同给时 `--arg` 覆盖；`--tools a,b` 下发工具白名单
- 端点别名在 `src/webtool/data/mcp.json`，用户可建 `~/.webtool/mcp.json` 同构覆盖：`{"mcp":{"my_srv":{"url":"...","api_key_env":"MY_KEY","verbs":{"search":"..."}}}}`
- key 只经环境变量名映射，配置文件不存明文；免 key 服务不发认证头
- exa / parallel / firecrawl 已并入 `search` 引擎池（`-e exa`），没有独立的 `webtool exa` 命令；其 `web_fetch` 也被 `fetch --via` 复用。exa 免 key 配额按出口 IP 计，走代理易 429，需保持 `exa.ai` 直连
- 先 `probe`/`list` 再 `call`：免 key 与带 key 暴露的工具集可能不同；失败走 stderr + 退出码 1

## stock

```bash
# 行情与单股
webtool stock quote 600519 600036 创业板指     # 实时行情 (指数别名可用)
webtool stock pool --date last --only-buy     # 涨停池
webtool stock check 600519 300913             # 可买性 (创业板/科创板标不可买)
webtool stock calendar --n 5                  # 交易日历
webtool stock flow --scope north              # 资金流 industry/individual/north
webtool stock news 600519 -n 5                # 新闻 / announcement 公告
webtool stock financials 600519               # 核心财务指标
webtool stock analyze 600519                  # 单股深度 (技术面 + 100 分制评分 + 信号)
webtool stock screen --pool short --min-score 70   # 选股池 short/mid/long
webtool stock risk 600623                     # 风险核查 (重组/减持/立案/预亏)
webtool stock report 600519                   # 成稿研报 (--pool short 出短线池研报, 约 70s)
webtool stock excel --excel picks.xlsx        # 选股池导出 xlsx (需 openpyxl)
webtool stock sentiment 600519                # 消息面打分 (-100~+100; 也可 --text "...")
webtool stock diagram --kind tree             # mermaid: tree/logic/chain
webtool stock holder 600519                   # 股东研究摘要
webtool stock forecast 600519                 # 盈利预测
webtool stock mcp --tool stock_kline --arg symbol=600519 --arg period=day
webtool stock tools                           # 24 个动作清单
webtool stock health                          # 探活

# 底层取数: 15 个功能域, 1300+ 接口
webtool stock data                             # 入口导航 (各域接口数)
webtool stock data list [域]                    # 域总览 / 域内明细
webtool stock data find <关键词>                # 跨域搜 (eco/api/em配方/docs)
webtool stock data call <接口名> --arg k=v      # 按名调
webtool stock data url "<URL>"                 # 裸 HTTP 直调 (反爬内置)
webtool stock data list api                    # 数据源层 156 个方法 (按源分组)

# 生态库 (akshare/tushare/baostock/efinance, 约 1300 接口, 返回 DataFrame)
webtool stock eco-health
webtool stock eco-search 龙虎榜
webtool stock eco --method stock_zh_a_hist --arg symbol=600519     # 默认给形状+前 5 行, --full 取全量
webtool stock api --method ths_rank_cxfl --arg sort_type=1

# 逆向接口文档 (7 分册 / 122 reportName / 322 端点)
webtool stock docs-search companyType
webtool stock docs-report RPT_LICO_FN_CPD
webtool stock docs-stats
```

- 单股动作的代码走位置参数（`quote`/`check`/`risk` 可给多个）；**没有 `--code` 选项**
- `--arg` 的值纯数字一律留字符串（600519 是代码），与 `webtool mcp` 的猜测口径不同
- `report` / `diagram` / `excel` 原样透传（markdown、mermaid 源码、落盘确认）；`screen` 输出含剔除清单与闸门原因
- 口径：涨停池输出必带真实数据日；北向等数据缺位标 ⚠「未取得」，不当 0；上游未解析出条目时显式标注
- 退出码：0 成功 / 1 数据动作失败 / 2 用法错误

## 通用约定

- `-n` 条数 · `-f json|text|markdown`（`md`≡`markdown`、`txt`≡`text`，大小写不敏感）· `-o` 落盘（按 `-f` 补扩展名，`-o -` 强制 stdout）
- `--no-cache` 跳缓存 · `--no-proxy` 本次直连 · `--proxy URL` 临时代理
- 缓存 TTL：search 60s / fetch 10s / 跳转解析 10min（`config set cache_ttl.<桶>=<秒>` 覆盖）
- 退出码：0 成功 / 1 数据动作失败 / 2 用法错误（提示走 stderr）
- 出网走浏览器指纹；**走哪条线一次定死**：配置与路由表在请求前决定，失败就是失败，不做"直连↔代理"隐式切换。要临时直连用 `--no-proxy`，要单点覆盖加规则条目

### 证书校验

```bash
webtool config set ssl_verify on|off                    # 总开关, 默认 on
webtool config set ca_bundle /path/to/ca.pem            # 自定义 CA, 替代系统 CA
webtool config set verify_hosts czce.com.cn,gtjaqh.com  # 点名豁免, 其余域仍严格
webtool config list                                     # 看实际生效策略与 CA 来源
```

默认严格校验（fail-closed）；`ca_bundle` 指向不存在的文件会当场报错。`verify_hosts` 优先于全局开关，用于自签/过期证书站（覆盖子域）。证书失败抛 `TlsError` 直接上抛，不重试、不降级。环境里没装 `ca-certificates` 时自动降级为不校验并在 `config list` 打警告。

### 代理与分流

```bash
webtool proxy set http://user:pass@host:port       # 密码加密入库, 配置只留用户名
webtool proxy setpass <用户名>                      # 终端交互输入 (不回显)
webtool proxy passwd | delpass <用户名>
webtool proxy named tokyo socks5://user@127.0.0.1:1081     # 命名代理

webtool proxy rule add '{"domain":["*.cn"]}' direct        # 按域名
webtool proxy rule add '{"geosite":["cn"]}' direct         # 按域名库 (不解析 DNS)
webtool proxy rule add '{"geoip":["CN","HK"]}' direct      # 按 IP 归属地
webtool proxy rule add '{"port":[8080]}' proxy:tokyo       # 走命名代理
webtool proxy rule add '{"domain":["ads.tracker.io"]}' block
webtool proxy rule del 2                                    # 0 起
webtool proxy rules [URL]                                   # 列规则 / 试算
webtool proxy geosite /path/geosite.dat                     # 配域名库 (MaxMind .mmdb 或 v2ray/sing-box .dat)
webtool proxy geoip /path/GeoLite2-Country.mmdb
```

- 动作 `direct` / `block` / `proxy` / `proxy:<名字>`；`--first` 插到最前、`--pos N` 插到第 N 位（默认追加到末尾）
- **顺序即优先级**，第一个命中的生效；`match` 内多条件 AND、同条件内多值 OR；判不出来 = 不匹配（缺库则该条跳过并提示）
- 分流优先用 `geosite` 而不是 `geoip`：按域名查库不解析 IP，不受 CDN 就近解析影响
- 首次运行自动生成默认 `~/.webtool/rules.json`（国内常见站 + `opencode.ai` / `exa.ai` 直连），已存在则永不覆盖
- 命名代理密码与全局代理共用同一套保险库（`rules.json` 只留 `user@host`，密文在 `config.json` 的 `proxy_auth`，出网时内存解密）；日志与报错里统一脱敏成 `***`
- google / docs.rsshub.app 被墙，直连不通，需代理或规则

## 配置与插件

```bash
webtool config list|get|set|unset      # default_engines/extract/market/timeout/cache/ssl_verify/...
webtool plugins list|check|reload|enable|disable
webtool cache / webtool blocklist
```

七类插件：`engine`（搜索引擎）、`hot`（榜单源）、`site`（站内站点）、`extractor`（正文提取器）、`resolver`（跳转链解码）、`filter`（结果过滤）、`transformer`（结果改写）。清单在 `src/webtool/data/plugins.json`，用户在 `~/.webtool/plugins.json` 覆盖或追加：

```jsonc
// ~/.webtool/plugins.json
{
  "engine":  {"bing": {"base": 0.6}, "my_eng": {"module": "mypkg.search:run", "desc": "自建引擎"}},
  "extractor": {"my_ext": {"module": "mypkg.extract:run", "desc": "自定义提取器"}}
}
```

| 类别 | 签名 |
|---|---|
| `engine` | `(query, max_results, proxy, timeout, market) -> [结果]`（`base` 决定排序权重） |
| `hot` | `(query, limit, proxy, timeout) -> [结果]`（`search` 决定能否直接传关键词） |
| `site` | `(query, limit, proxy, timeout, **kw) -> [结果]` |
| `extractor` | `(html, url, meta) -> (正文, meta)` |
| `resolver` | `(url, proxy, timeout) -> 新 url`（`match` 指认跳转链特征） |
| `filter` / `transformer` | `(results, ctx) -> [结果]` |

- `module` 格式 `包路径:函数名`；三层来源后者覆盖前者：包内 JSON → 用户 JSON → `WEBTOOL_PLUGIN_DIR` 外部 `.py`
- `hot`/`extractor`/`filter`/`transformer` 按插入顺序执行，提取器首个返回非空正文的生效
- 过滤规则可配：`~/.webtool/filters.json` 覆盖 `adfilter`（广告词/域名）、`blocklist`（低质站点）、`merge`（词典先验域/跟踪参数）、`spa`（内嵌 state 挂载点）
- 引擎行为参数在 `engine.<name>.params`：`rate`（请求间隔秒）、`captcha_signs`（验证页指纹）、`cooldown`（触发后静默秒）
- 热更新：`plugins.json` / `filters.json` 按 mtime 自动生效；外部插件 `.py` 改动需 `plugins reload`
- 跳转链解码是 `resolver` 插件，按 URL 特征认链；`match` 里普通串按子串匹配，`~` 开头按正则

## 开发

```bash
python3 scripts/gen_requirements.py    # pyproject.toml 是依赖唯一权威, 改完重新生成 requirements.txt
python3 scripts/audit_deps.py          # 查 import 了却没声明的依赖
python3 -m pytest tests -q
```

代码分层 `cli` → `feeds`/`radar`/`zen` → `pipeline`/`render` → `net`/`engines` → `core`，只允许向下依赖。改代码前读 [docs/coding-standard.md](docs/coding-standard.md)，架构见 [docs/design.md](docs/design.md)，站点/订阅扩展见 [docs/custom-sites.md](docs/custom-sites.md)。
