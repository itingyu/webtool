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

Python 依赖全装（Pillow 已随包，`pic` 与 `banner --font big` 用它栅格化图像/汉字）。
唯一的系统工具依赖：`video` / `music` 解码要 **ffmpeg**（**ffprobe 可选** —— 没有它就用 ffmpeg 解一帧、问 Pillow 要尺寸）。它进不了 pyproject，所以运行时按三条路找，找到即用：① 环境变量 `WEBTOOL_FFMPEG` / `WEBTOOL_FFPROBE` 指路径；② PATH 里找（`apk add ffmpeg` / `apt install ffmpeg` / Windows、macOS 装官方便携包）；③ Python 包自带的静态二进制（`pip install imageio-ffmpeg` 带 ffmpeg，`pip install static-ffmpeg` 两个都带，装上就自动认出，不必再配）。三条都没有才报错，并把这三条路列出来。

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

升级分三步走（不再 `pip install git+…` 把 git 塞给 pip）：**① git 取源码** → **② pip 从本地目录装** → **③ 清理临时目录**（带守卫，只删自己建的）。代理、证书、依赖在三步里的分工：

- **代理**：先按 rules.json 判一次源地址走哪条线，然后**只把代理交给 git**（用 `GIT_CONFIG_*`
  塞 `http.proxy`）。pip 自己的请求默认直连 —— 它要的 PyPI 多半直连可达，被代理带着反而
  容易卡死，报出来还成了"代理连不上"。企业网里 pip 只能靠代理出网时：
  `webtool config set pip_proxy on`。
- **证书**：`ssl_verify off` 也带给子进程（git 给 `GIT_SSL_NO_VERIFY`；pip 没有全局开关，
  只能按主机 `PIP_TRUSTED_HOST` 放行）；有信任根就指给它们（`PIP_CERT` / `GIT_SSL_CAINFO`）。
  另外固定给 `GIT_TERMINAL_PROMPT=0` / `PIP_NO_INPUT=1`（要凭据时立刻失败，不挂在那儿等人
  输入）与 `PIP_DEFAULT_TIMEOUT` / `PIP_RETRIES`（网络抖一下不该让升级失败）。
- **依赖**：`--no-deps` 只换自己那份代码，升级完再按声明的清单补一次依赖 —— pip 只补缺的，
  已有的不动，全齐时连索引都不问。不想这步：`webtool config set upgrade_deps off`。

注意 **ssh 源（`git+ssh://` / `git@host:path`）吃不到代理** —— ssh 拿自己的连接出网，
判了代理也是直连；遇到这种源会直接提示，要真走代理就换 https 源：`webtool upgrade --from git+https://…`。

`webtool -v -f json` 打印版本与运行环境（Python/平台/代码路径/依赖），报障带上它。

**升级 / 重装 / 卸载都不动 `~/.webtool`**：那里是你手写的配置、分流规则和保险库凭据。
重装只会替换包本体的文件；首次运行补默认配置时是"缺哪份补哪份，已有的一律不碰"；
卸载默认只卸包，要连数据一起删得显式 `--purge-data --yes`。

## 命令

| 命令 | 用途 |
|---|---|
| `search` | 多引擎网页搜索（含 exa/parallel/firecrawl 语义搜索） |
| `fetch` | 抓 URL 提取正文；二进制直接下载 |
| `crawl` | 站内定向爬取；默认落盘到 `crawl_dir`（`~/.webtool/crawl`） |
| `rank` | 榜单聚合：19 个热榜源 |
| `feed` | RSS/Atom 订阅抓取，含 RSSHub 路由库查询 |
| `site` | 18 个站点站内搜索 |
| `zen` | OpenCode Zen 免费层对话，无需 key |
| `mcp` | 通用 MCP 客户端 |
| `stock` | 股票：行情/选股/研报 + 1300+ 底层接口 |
| `proxy` | 代理配置、凭据、按域名/IP/端口分流 |
| `pkg` | 包管理器/git 等命令透传，线路按规则表换算成环境变量 |
| `config` / `plugins` / `cache` / `blocklist` | 配置、插件、缓存、黑名单 |
| `engines` | 引擎清单与体检 |
| `upgrade` / `uninstall` | 升级、卸载 |
| `banner` | 文字排大字符（6 种点阵字体 + 汉字栅格化） |
| `pic` | 图片转字符画（路径/URL/data URI/base64/stdin） |
| `video` | 视频转字符动画（URL 直读，不整段下载） |
| `music` | 音乐转频谱柱动画（同上） |

## search

```bash
webtool search "LLM 排行榜" -n 5                # 默认 bing,sogou,baidu
webtool search "query" -s marginalia             # 小站/老网页长尾
webtool search "查询词" --preset zh               # 引擎组合预设
webtool search -s github "fastapi"               # 站内搜 (同一选择器)
webtool search "query" -s exa,parallel           # 语义引擎
webtool search "AI 芯片" -S 7d                   # 近 7 天 (相对: 7d/2周/3个月/1y/昨天)
webtool search "AI 芯片" -A                     # 不限时间 (默认只搜近 15 天)
webtool search "AI 芯片" -S 2026-10-01 -U 2026-10-23   # 绝对区间, 下推引擎原生参数
```

- 引擎：`bing` / `sogou` / `baidu` / `so360`（境内直连）· `marginalia`（境内直连，独立索引的小站/老网页长尾；**默认关**，要就用 `-s marginalia`）· `google`（被墙，需代理；无代理或被风控直接跳过，**不再降级 news RSS**）· `exa` / `parallel` / `firecrawl`（语义搜索，匿名免 key，默认关）
- 默认引擎集 `bing,sogou,baidu,so360`；`--preset zh|en|direct` 用预设组合（`webtool plugins engines presets` 列），优先级 `-s` > `--preset` > `config.default_engines` > 内置默认
- 语义引擎按需加：`exa` 召回条数常最多 / `parallel` 最快且返回带日期 / `firecrawl` 能过 JS（search 免费 500 次/月），与关键词引擎重叠少
- `--operators passthrough|strip|strict` 控制高级操作符（支持 `site:` `intitle:` `inurl:` `-词`）；`--blocklist a.com,b.com` 覆盖黑名单（前缀 `!` 表例外，`off` 关闭）
- **多引擎并发抓取**：一次搜索同时打所有引擎（不同站点、互不排队），墙钟≈最慢那个引擎而不是各家之和。默认并发=源数（上限 4，`core.resilient.MAX_WORKERS` 常量），`-j/--jobs N` 调（`1` = 串行，`config set jobs N` 持久化）。结果与报错一律按 `-s` 声明顺序回填，同一 query 的输出稳定可复现
- 跳转链默认自动解码成真实 URL（`--no-resolve` 关）；结果综合加权排序，`-f json` 看 `weight` 与 `engines`（交叉验证数）
- `webtool search -l`：引擎 + 站内源统一清单（含冷却状态）；`webtool plugins engines test|presets`：实发体检 / 预设组合

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
webtool rank zhihu --no-url          # 输出不带链接 (只要标题/热度)
```

`-q` 语义筛选词，`-t` 阈值（默认 0.15），`-n` 每源条数（默认 10）。
`--no-url` 去掉每条目的 url：json 里没有该字段，markdown/text 退化成纯标题（要喂给
模型做摘要时链路最干净）。

## feed

```bash
webtool feed                              # 源清单 (内置预设 + 自定义)
webtool feed sspai ithome --new-only      # 抓条目, 只出上次之后的新条目
webtool feed "https://example.com/rss.xml"   # 任意 RSS/Atom URL
webtool feed --add myblog --add <URL> --add "描述"   # 自定义源
webtool feed --del myblog                 # 删自定义源 (预设不可删)
webtool feed health                       # 坏源登记表
webtool feed sources retest all           # 复查坏源, 恢复即移除
webtool feed sources mark <key> "原因"     # 人工登记坏源 (可再跟 URL)
webtool feed get sspai --no-url           # 输出不带链接 (只要标题/摘要)
```

- 111 个种子源随包分发，安装时并入（只增不覆盖，`WEBTOOL_NO_SEED=1` 关）；`--new-only` 状态存 `~/.webtool/feed_state.json`
- `--add` / `--mark` 的值要各写一次旗标

RSSHub 路由库：

```bash
webtool feed radar find 36kr                                    # 搜路由卡片 (裸 radar 同)
webtool feed radar find 36kr --pick 2 --param category=newsflashes  # 填参拉数据
webtool feed radar find 36kr --pick 2 --example                 # 官方示例路径
webtool feed radar find 36kr --pick 2 --sample-row 2            # 用真实样例填参
webtool feed radar url <页面URL>                                 # 反推路由
webtool feed radar find 36kr --pick 2 --example --add r36kr     # 落地成订阅源
```

RSSHub 路由也会自动变成 feed 源（物化到 `~/.webtool/feed_radar.json`，radar 缓存更新后自动重建）：
键名 = 域名短名，同站多条路由用 `36kr_hot_list` 这种后缀。

```bash
webtool feed 36kr                  # 免填参路由直接抓 (可选参数按默认)
webtool feed bilibili              # 缺必填 → 打印参数表 + 可照抄的示例
webtool feed bilibili -p uid=2267573
webtool feed bilibili -e           # 官方 example 路径, 免填参
webtool feed sources find 知乎      # 按键名/站名/域名/描述模糊搜
webtool feed sources find bilibili.com   # 按域名搜
webtool feed sources --radar       # 派生源按分类分组, 每类再分免填参/带参
webtool feed sources --radar -c finance   # 只看财经类
webtool feed sources sync -R       # 重拉路由库并重建物化表
```

`--pick` 选第几条命中的路由（不给则取热度最高），`--param` 只作用于选中的那条。默认与官网 feed 交叉校验并据此取数（`--no-xcheck` 关）。实例探活 `webtool feed instances`（默认挑最快）；公共实例 rsshub.rssforever.com / hub.slarker.me / rss.wudifeixue.com / rsshub.isrss.com，429 时轮换 `--instance`。

## 站内搜索 (site)

入口在 `search -s`，不再单独占一个命令。18 站点：github / gh_search / so / hn / wikipedia / arxiv / csdn / csdn_so / juejin / juejin2 / bilibili / bili2 / sspai / npm / thepaper / eastmoney / sov2ex / douban。

```bash
webtool search -l              # 全部检索源 (引擎 + 站点)
webtool search -s github fastapi      # 站内搜
webtool search -s wikipedia 量子计算 --lang en
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
webtool zen limits                        # 看记住的模型输出上限 (目录预取 / 上游 400 报过)
webtool zen "问题" --dry-run              # 打印将发出的请求, 不出网
webtool zen "问题" --show headers         # request(默认)/headers/body/text
webtool zen "问题" --no-sticky            # 会话 id 每次换新 (默认粘性, 按整点轮换)
```

### zen --agent（多轮工具循环）

不带 `--agent` 时模型要调工具就算失败（`client.call_zen` 报 no tool loop）—— 没有循环没人执行。带了就地补上那个循环：模型要工具 → 本地执行 → 结果按 `role:tool` 回喂 → 再问，直到它给出答案或到步数上限。

```bash
webtool zen "这个仓库是干什么的" --agent                  # 自动 glob/read/grep
webtool zen "查一下今天有什么新闻" --agent                # 自动 websearch/webfetch
webtool zen "看看 src 里的分层对不对" --agent -w .        # 工作空间 = 当前目录
webtool zen "继续" --agent --continue                    # 接最近一条会话
webtool zen "刚才那个再说细点" --agent --session notes     # 命名会话, 同名再跑即接着聊
webtool zen --sessions                                    # 列会话 (不联网)
webtool zen --session notes --clear-session               # 删掉某条会话
webtool zen "问题" --agent --agent-max-steps 40           # 放宽轮数 (默认 20)
webtool zen "问题" --agent --agent-tools read,grep        # 只给模型看这几个工具
```

- **执行的只有只读 + web 类**：`read` / `glob` / `grep` / `websearch` / `webfetch`。`websearch`/`webfetch` 走本仓自己的 search / fetch 管线（线路、缓存、过滤全一致），不另写一份抓取逻辑
- **`bash` / `write` / `edit` 没有实现**：调用它们会拿到一条"不可用"的工具结果（不是静默忽略——那会让模型以为已执行然后编造结果）。工具清单里仍留着 `bash`/`read`，因为免费层闸门要求这两个同时在（缺任一即 403）
- **工作空间是条边界**：`-w/--workspace <目录>`（默认当前目录），`read`/`glob`/`grep` 的路径只能在它里面解析，相对路径、绝对路径、symlink 绕出去一律拒绝并把理由回给模型；工作空间里的 `AGENTS.md` 会并进 system prompt
- **会话落盘**：`--session <名>` 存 `~/.webtool/zen_sessions/<名>.json`（messages 全量），**每轮存一次**——中途断网时已问过的还在；`--continue` 接最近一条。恢复时只保留最新的一份 system（旧那份的工具集/工作空间可能已变）
- 终端里边收边打，每步打 `[第 N 步] <工具> <参数>` 与一行结果摘要；`--agent-max-chars`（默认 8000）控制单次工具输出回喂的字数，超出截断并在尾部标明原文长度
- 到 `--agent-max-steps` 仍要工具就**如实报停**（`stopped_by_limit`），不假装答完了

- 模型上下架频繁，先 `--list-free` 再用；清单按命名约定推免费层，能否用只有 `--check` 真调才算数
- `--think` 原样透传上游 `reasoning_effort`，可选值随模型而异，客户端不预判；被上游拒会自动去掉该字段重试一次
- 终端里边收边打、思考与正文分开着色；管道/`-f json` 时一次性输出（`--no-reasoning` 只要答案）
- 默认值写 `~/.webtool/zen.json` 的 `zen` 段（`model` / `max_tokens` / `reasoning_effort` / `system` / `tools` / `tool_choice` / `live` / `extra_body`），优先级 命令行 > zen.json > 内置；换端点改 `chat_url` / `models_url`
- `extra_body` 原样并入请求体（同名字段以它为准），用来补上游扩展字段
- **模型输出上限会被记住**：`max_tokens` 各家上限不同（8k ~ 131k），而真值只有上游在 400 里才报。报错里抠出上限就落盘（`~/.webtool/zen_limits.json`），下次运行**直接按上限发请求**，不再每次先撞一次墙；`webtool zen limits` 看记住的值（`-f json` 给脚本），`webtool zen limits --forget [--model <名>]` 忘掉。抠不出数字不记也不重试——猜一个值静默沿用比每次撞墙更糟
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
- exa / parallel / firecrawl 已并入 `search` 引擎池（`-s exa`），没有独立的 `webtool exa` 命令；其 `web_fetch` 也被 `fetch --via` 复用。exa 免 key 配额按出口 IP 计，走代理易 429，需保持 `exa.ai` 直连
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
webtool stock kline 600519 --bars 120          # K 线 (A股/港股/美股)
webtool stock kline 半导体 --chart             # 行业板块: 中文名或 BK 代码都行 (东财 BKxxxx)
webtool stock intraday 电信运营商 --chart      # 板块分时 (仅东财, 无竞价段)
webtool stock kline 600519 --chart             # 出图: SVG (红涨绿跌 + MA + 量能)
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
webtool stock data list api                    # 数据源层 157 个方法 (按源分组)

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
- `kline` / `intraday` 支持**板块**：中文名（`半导体`/`通信运营商`，带不带"行业"后缀都行，全量目录 1h 缓存内解析→BK 代码）、或直接给 `BKxxxx`。K 线/分时都走东财 `90.BKxxxx`；板块没有撮合竞价，分时无竞价段，均价（黄线）按成分股加权价（系数固定×100）。名字对不上时（如东财把"光模块"叫"光通信模块"）会列相近候选；全表用 `webtool stock boards <关键词>` 查
- `--ascii` 直出终端字符画（影线 `│`/阳 `█`/阴 `▓` 形状级区分；盲文点阵分时），颜色自动探测：`NO_COLOR`/`TERM=dumb`/非 tty 降级无色，`FORCE_COLOR=1` 管道强制；`boards` 表的涨跌% 同口径红涨绿跌
- `--arg` 的值纯数字一律留字符串（600519 是代码），与 `webtool mcp` 的猜测口径不同
- `report` / `diagram` / `excel` 原样透传（markdown、mermaid 源码、落盘确认）；`screen` 输出含剔除清单与闸门原因
- 口径：涨停池输出必带真实数据日；北向等数据缺位标 ⚠「未取得」，不当 0；上游未解析出条目时显式标注
- 退出码：0 成功 / 1 数据动作失败 / 2 用法错误

## pydata (外部金融库经 webtool 出网)

akshare / efinance / adata / qstock 这些库的出网 99% 是裸 requests（无 TLS 指纹、无代理路由、无限流），站点一收紧反爬就 `RemoteDisconnected`。`pydata` 不重写它们的任何接口——把 `requests.Session.request` 整个换成 webtool 传输层（chrome 指纹会话、逐 URL 代理规则、证书策略、最小间隔限流、幂等自动重试），业务代码原样跑：

```
webtool pydata akshare.stock_zh_a_hist '{"symbol":"600519","period":"daily","start_date":"20251001","end_date":"20251020","adjust":"qfq"}'
webtool pydata efinance.stock.get_quote_history '["600519",101]' -f json
webtool pydata akshare.stock_zh_a_tick_tx_js '"sz300750"' -n 50
```

- 实参：JSON dict → kwargs、JSON list → 位置参数、其他字符串 → 单个位置参数；`-n` 控 text/csv 截行数，`-f json` 全量
- 裸 requests 的身份头（`python-requests/*` UA 等）在出网前被滤掉，换成 webtool 按站点给的浏览器档案头；库里显式设置的头（Referer 等）仍以库为准
- 库没装会给出安装提示（`pip install akshare`）；`--pace-ms` 控限流（默认 120ms），接口数量大时别关
- 仅 `pydata` 与 `webtool.net.pyshim.install()` 生效，webtool 自身桥不经过它；`uninstall()` 随时还原原生 requests
- 已知边界：`files`（文件上传）不支持；库函数若返回非 DataFrame/list/dict 会按文本带 `kind=text` 返回

## 字符渲染 (banner / pic / video / music)

终端里把文字、图片、视频、音乐画成字符动画，渲染全在本地。Python 依赖已随包（Pillow）；
`video` / `music` 另需 **ffmpeg**（ffprobe 可选，来源见文首「依赖」段）。

```bash
webtool render text "HELLO" --font slant        # 文字排大字符 (6 种点阵字体, --list 看全)
webtool render text 你好                        # 汉字/emoji 自动走字体栅格化
webtool render image photo.jpg -w 90                # 图片转字符画
webtool render image "data:image/png;base64,...."   # 也吃 data URI / 裸 base64 / - (读 stdin)
webtool render video clip.mp4 --dur 10            # 视频转字符动画 (Bad Apple 效果)
webtool render music song.mp3 --bands 24          # 音乐转频谱柱动画
```

**尺寸**（`pic` / `video` / `music`）：默认按终端自动适配 —— 列数取终端宽度，行数按原始宽高比换算，装不下就自动收窄。想固定就写 `--size 120x40`（也认 `120*40`、`120,40`，只给一个数就是宽度），或用 `-w/--width`、`--height` 单独指定。`music` 另有 `--bands`（柱数，上限 64）与 `--rows`（柱高）。

**`banner --font big` 的字体**：先看 `WEBTOOL_BANNER_FONT`，其次用**随包带的 Noto Sans CJK SC 子集**（4736 字：ASCII + GB2312 一级汉字 + 常用标点/制表符），装上就能画汉字，PC 上也不必另配；最后才去找系统字体（Linux / macOS / Windows 的常见字体目录）。子集来源与许可见 `webtool/data/banner-cjk-sc-OFL.md`（OFL-1.1，允许再分发）。

**网络素材怎么取**（`video` / `music`）：三级阶梯，流量逐级变大。

1. **默认直读** — URL 直接交给 ffmpeg（HTTP Range 可 seek，HLS 也能放；探测深度限到 1MB）。
   实测 17MB 片源放 2 秒只传约 4.2MB。
2. **webtool 通道** — ffmpeg 直读失败（防盗链等）时，走本工具自己的取字节通道边收边喂 ffmpeg，
   仍然不整段下载；容器索引在文件尾的流没法顺读，自动落到第三级。
3. **整段下载** — `--download` 强制走这条，下到临时文件、放完即删。要音轨同步也得用它：
   流式模式没有本地文件可交给播放器。

取源会带上规则表给该 URL 定的代理（以 `http_proxy` 环境变量传给 ffmpeg/ffprobe/播放器）。

## 通用约定

- `-n` 条数 · `-f json|text|markdown`（`md`≡`markdown`、`txt`≡`text`，大小写不敏感）· `-o` 落盘（按 `-f` 补扩展名，`-o -` 强制 stdout）
- `--no-cache` 跳缓存 · `--no-proxy` 本次直连 · `--proxy URL` 临时代理
- `-d/--debug` 调试日志到 **stderr**（级别着色：DEBUG 灰 / INFO 绿 / WARN 黄 / ERROR 红；非终端与 `NO_COLOR` 自动去色），stdout 保持纯数据，可安全配 `-f json`；`WEBTOOL_DEBUG=1` 等效。日志会打出线路决策（只落 `host:port`，不带密码）、规则命中、重试与熔断状态，定位问题先加 `-d`
- **支持 stdin 管道**：`webtool fetch -` 读 URL 列表（跳空行与 `#` 注释），`webtool search -` 读搜索词，可串联（`webtool rank 芯片 -f json | webtool search -`）；坏 JSON 行会带行号报错，不静默丢
- 缓存 TTL：search 60s / fetch 10s / 跳转解析 10min（`config set cache_ttl.<桶>=<秒>` 覆盖）
- 退出码：0 成功 / 1 数据动作失败 / 2 用法错误（提示走 stderr）
- 出网走浏览器指纹；**走哪条线一次定死**：配置与路由表在请求前决定，失败就是失败，不做"直连↔代理"隐式切换。要临时直连用 `--no-proxy`，要单点覆盖加规则条目

### 证书校验

```bash
webtool config set ssl_verify on|off                    # 总开关, 默认 off (没配就不校验)
webtool config set ca_bundle /path/to/ca.pem            # 自定义 CA, 替代系统 CA
webtool config set verify_hosts czce.com.cn,gtjaqh.com  # on 之下点名豁免, 其余域仍严格
webtool config list                                     # 看实际生效策略与 CA 来源
```

**默认不校验**：新装 / 无配置的环境（Android、容器、公司网络 MITM、系统 CA 缺失）最常见的处境就是"证书还没准备好"，默认严格会让首次使用直接不可用——证书该不该放过是用户的决定，不是工具的默认。要严格就显式 `ssl_verify on`：那时 `ca_bundle` 指向不存在的文件会当场报错，`verify_hosts` 用于点名豁免自签/过期证书站（覆盖子域）。证书失败抛 `TlsError` 直接上抛，不重试、不降级。

CA 从哪来（按顺序）：环境变量 → 系统 CA → certifi → **仓库自带** `webtool/data/certs/ca-bundle.pem`（Mozilla 根证书集，随 wheel 分发）。所以宿主没装 `ca-certificates` 也能拿到完整根证书——显式开了 `ssl_verify on` 也校验得动，不必"为了能用就把全站校验关掉"。

站点专有证书（自签/内部 CA）放 `~/.webtool/certs/extra/*.pem`，**再按站点配一条规则**——证书是哪个站的，信任根就只对那个站生效：

```bash
webtool proxy cert list        # 每份证书是哪些站点的、顶上有没有规则、何时过期
webtool proxy cert sync        # 按证书自称的域名 (SAN/CN) 自动写好规则
```

```json
{"kind": "tls", "match": {"domain": ["zce.com.cn", "*.zce.com.cn"]},
 "ca": "extra/zce.pem"}          // 该站: 完整校验 + 这套信任根 (追加到基础 CA)
{"kind": "tls", "match": {"domain": ["old.example.cn"]},
 "verify": "off"}                // 该站: 单独关校验 (比 verify_hosts 多一层端口限制)
```

**光把证书放进 `extra/` 不生效**——没规则的证书不会并进信任根（否则一份站点证书等于给所有域名开口子），`config list` 会点名提醒。`ca` 支持相对 `~/.webtool/certs/` 的路径，换机器、换 home 都还认。决策优先级：`verify=` 参数 > tls 规则 > `verify_hosts` > `ssl_verify`。

证书失败会分**类别**报，并给出对应处置（`tls.cert_advice`）：域名不符 / 自签 / 过期 / 缺中间证书 / 需旧版 TLS 重协商 —— 各不相同，别一律去改 `ca_bundle`。

### 出网只有一条通道

`requests` 也收进来了：启动时 `adapters.patch_requests()` 把 transport 适配器挂成 `requests.Session` 的默认出口。**第三方库自己造的会话**（akshare、trafilatura 等）因此同样按目标域名现算线路、走 `tls.policy` 校验证书、补齐缺省头指纹、按 (线路, 主机) 复用连接。库若自己再 `mount` 适配器，仍以它为准。

- `ssl_verify off` 时这层一并放行（`requests.Session.request` 注入 `verify=False`），所以总开关是"全站"，不是"只有 webtool 自己的通道"
- 排查"是不是这层惹的"：`WEBTOOL_NO_PATCH_REQUESTS=1` 关掉整层
- 管不到的三处：pip/git 是**子进程**（用 `GIT_SSL_CAINFO` / `PIP_CERT` 喂根证书）；sogou 的 Android TLS 指纹腿刻意保留原生会话（证书仍走策略）；`netx` 的 urllib 兜底通道是 net 层内部实现，策略与线路同源、传输栈不同

### 代理与分流

```bash
webtool proxy test [代理URL|名字] [--url 目标]        # 探活 + 线路自检 (规则判定/是否被引用/是否真走代理)
webtool proxy set http://user@host:port            # 密码在库里有就直接用, 没有则交互输入 (不回显)
webtool proxy setpass <用户名|用户名@主机>           # 单独存密码; URL 里带 :pass@ 会被拒绝 (防 history/ps 泄漏)
webtool proxy passwd | delpass <引用名>
webtool proxy named tokyo socks5://user@127.0.0.1:1081     # 命名代理
webtool proxy unset                                        # 清默认代理

webtool proxy rule add '{"domain":["*.cn"]}' direct        # 按域名
webtool proxy rule add '{"geosite":["cn"]}' direct         # 按域名库 (不解析 DNS)
webtool proxy rule add '{"geoip":["CN","HK"]}' direct      # 按 IP 归属地
webtool proxy rule add '{"port":[8080]}' proxy:tokyo       # 走命名代理
webtool proxy rule add '{"domain":["ads.tracker.io"]}' block
webtool proxy rule del 2                                    # 0 起
webtool proxy rules [URL]                                   # 列规则 / 试算
webtool proxy tidy [--apply]                                # 合并同动作规则 / 去冗余 (干跑默认, 落盘先备份)
webtool proxy cert list                                     # 站点证书: 覆盖哪些域名 / 有没有规则 / 有效期
webtool proxy cert sync                                     # 按证书自称的域名把证书规则写进规则表
webtool proxy geosite [<geosite.dat>|update]                # 配域名库 (MaxMind .mmdb 或 v2ray/sing-box .dat) / 只更 geosite
webtool proxy geoip [<GeoLite2-Country.mmdb>|update]        # 配国家库 / 只更 geoip
webtool proxy geo update [geosite|geoip|all]                # 在线更新 (默认两个都更, 落 ~/.webtool/geo/)
webtool proxy geo status                                    # 看当前生效的库: 显式配置 / 用户目录 / 包内自带
```

- `proxy set` = 设命名代理 `default` 并补 `default: proxy:default`——未命中规则的流量走它；旧 config.json 的 `proxy`/`fetch_proxy`/`proxy_rules` 首次运行自动迁进 rules.json
- 动作 `direct` / `block` / `proxy:<名字>`（裸 `proxy` 等价 `proxy:default`）；`--first` 插到最前、`--pos N` 插到第 N 位（默认追加到末尾）
- **顺序即优先级**，第一个命中的生效；`match` 内多条件 AND、同条件内多值 OR；判不出来 = 不匹配（缺库则该条跳过并提示）
- 分流优先用 `geosite` 而不是 `geoip`：按域名查库不解析 IP，不受 CDN 就近解析影响
- **geo 库开箱即用**：包内自带 `geosite.dat` / `geoip.dat` 各一份，首次运行落到 `~/.webtool/geo/`，规则里 `{"geosite":["cn"]}` 不需先手动配库。`proxy geo update` 从上游（Loyalsoldier/v2ray-rules-dat release）拉最新写进用户目录，**下到的不是 geo 库就拒绝替换**（上游抽风回 HTML 错误页时不毁旧库）；国内拉 GitHub 一般要给规则表配代理，或用 `WEBTOOL_GEO_SOURCE_GEOSITE` / `WEBTOOL_GEO_SOURCE_GEOIP` 指镜像
- 首次运行自动生成默认 `~/.webtool/rules.json`（**一条**合并规则：`*.cn` + 国内常见站 + `opencode.ai`/`exa.ai` 直连），已存在则永不覆盖
- `proxy tidy` 做三件事，都只动语义等价或纯死重的部分：同动作规则合成一条、同一规则内被宽条目覆盖的去重、被前面规则完全覆盖或与默认动作同结果的规则删掉；**默认干跑**，`--apply` 落盘并先备份（规则表是分流总闸，不偷偷改）
- `proxy test` 不只回 OK/FAIL，它还说清三件事：这条线通不通、**目标 URL 按规则表实际会走哪条线**（不一致时提示"本次结果不影响该目标的真实线路"）、这条代理**有没有被任何规则/default 引用**（没被引用 = 测通也没流量走它）。默认目标是 `https://www.google.com/generate_204`（实得非 204 会提示可能被门户劫持/需认证），参数也可写命名代理：`webtool proxy test default`
- **显式指定的线路不被环境变量改写**：`no_proxy='*'`（或 `.host` 后缀形式）曾能让"规则表判了走代理"的请求静默直连，并把死代理报成 OK、报错退化成"直连超时"指不到真因；现在规则表/命令行指定的代理不再被 `no_proxy` 绕过
- 规则写散了不必手抠：同动作的多条规则迟早互相遮蔽，`webtool proxy rules` 检测到冗余会直接提示跑 tidy
- 没配代理时默认动作是 `direct`（此时直连规则是冗余的，tidy 会建议删）；`proxy set` 把默认动作切成代理的那一刻，若规则表为空会自动补一条国内直连规则

### pkg —— 让 npm/git 等走规则表

```sh
webtool pkg npm install lodash
webtool pkg git clone https://github.com/x/y
webtool pkg --no-proxy pip install -r requirements.txt
webtool pkg --proxy tokyo git pull
```

- 线路按规则表判（参数里的 URL / 该工具默认源 / 路由表 default），换算成 `HTTP(S)_PROXY`/`ALL_PROXY` 交给子进程；继承环境里的代理键先清掉
- 选项写在命令名前；多个目标被判到不同线路时拒绝执行并列出判定，要继续用 `--proxy` 强制
- 退出码透传；判定结果打 stderr，stdout 干净可接管道
- 命名代理密码与全局代理共用同一套保险库（`rules.json` 只留 `user@host`，密文在 `config.json` 的 `proxy_auth`，出网时内存解密）；日志与报错里统一脱敏成 `***`
- google / docs.rsshub.app 被墙，直连不通，需代理或规则

## 配置与插件

```bash
webtool config list|get|set|unset      # default_engines/extract/market/timeout/cache/ssl_verify/...
webtool plugins list|check|reload|enable|disable
webtool config cache info|clear          # HTTP 缓存
webtool config blocklist show|add|remove|reset  # 低质站黑名单
```

九类插件：`engine`（搜索引擎）、`hot`（榜单源）、`site`（站内站点）、`extractor`（正文提取器）、`resolver`（跳转链解码）、`filter`（结果过滤）、`transformer`（结果改写）、`interceptor`（拦截检测与绕过）、`source`（数据源，`SourceBase` 实现）。清单在 `src/webtool/data/plugins.json`，用户在 `~/.webtool/plugins.json` 覆盖或追加：

```jsonc
// ~/.webtool/plugins.json
{
  "engine":  {"bing": {"base": 0.6}, "my_eng": {"module": "mypkg.search:run", "desc": "自建引擎"}},
  "extractor": {"my_ext": {"module": "mypkg.extract:run", "desc": "自定义提取器"}},
  "interceptor": {"captcha": {"enabled": false}}   // 停用内置的人机验证识别
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
| `interceptor` | `Interceptor` 子类（见下） |

- `module` 格式 `包路径:函数名`；三层来源后者覆盖前者：包内 JSON → 用户 JSON → `WEBTOOL_PLUGIN_DIR` 外部 `.py`
- `hot`/`extractor`/`filter`/`transformer` 按插入顺序执行，提取器首个返回非空正文的生效
- 过滤规则可配：`~/.webtool/filters.json` 覆盖 `adfilter`（广告词/域名）、`blocklist`（低质站点）、`merge`（词典先验域/跟踪参数）、`spa`（内嵌 state 挂载点）
- 引擎行为参数在 `engine.<name>.params`：`rate`（请求间隔秒）、`captcha_signs`（验证页指纹，加载时并入全局特征表）；冷却时长不按引擎配，统一由 `captcha` 插件的站点冷却决定（30s 起，连续命中翻倍，上限 4×）
- 热更新：`plugins.json` / `filters.json` 按 mtime 自动生效；外部插件 `.py` 改动需 `plugins reload`
- 跳转链解码是 `resolver` 插件，按 URL 特征认链；`match` 里普通串按子串匹配，`~` 开头按正则

### 拦截与绕过（`interceptor`）

被挡住的响应（人机验证、WAF 页、限流、登录墙）不写死在传输层：`net/transport.py` 只问
`net/intercept.py` 两句 —— 这次是不是被挡了、有没有绕法。判定与记账都是插件，`captcha`
（人机验证 + 冷却）是第一个实现，`module` 指向 **`Interceptor` 子类**：

```python
from webtool.net.intercept import Interceptor, Hit, Bypass

class MyWall(Interceptor):
    name, priority = 'mywall', 30          # priority 小的先判；配置里可覆盖

    def inspect(self, ctx):                # 必实现: 挡没挡
        if ctx.status == 403 and '请稍候' in ctx.text:
            return Hit(kind='waf', why='WAF 拦截', sign='403+请稍候')
        return None

    def bypass(self, ctx, hit):            # 可选: 下一次重试怎么改
        return Bypass(how='换新闻通道', url=ctx.url.replace('/s?', '/n?'))

    def preflight(self, ctx): ...          # 可选: 发之前能不能发 (冷却门)
    def note_ok(self, ctx): ...            # 可选: 没被挡, 复位计数
    def note_hit(self, ctx, hit): ...      # 可选: 记冷却, 把剩余秒数写回 hit.left
```

- `ctx`（`Ctx`）只读：`url / status / text / headers / profile / attempt / via`，
  另有派生属性 `host`（主机名带端口）与 `site`（主机名，去端口 —— 冷却与日志的记账键）。
  `ctx.engine` 只是遗留信息字段，判定逻辑不读它
- `bypass` 返回的 `Bypass` 支持 `url` / `headers` / `profile` / `delay` / `retry` /
  `cookies` / `user_agent`，由传输层执行（`cookies` 灌进会话 jar，如求解器拿到的
  `cf_clearance`；`user_agent` 覆盖 UA 会与 TLS 指纹脱钩，更稳的是用 `profile` 切同版本档案）
- `Hit` 可带 `hint`（处置建议）：命中时附在 `BlockedError` 消息末尾，告诉人下一步该干什么
- 只判不绕也合法（`captcha` 现在就是）：传输层按**站点**冷却 + 降级梯处理
- 引擎自己试通道的路径（sogou PC/移动双通道、baidu 预热会话、google web/news 降级）
  同样过拦截器：调 `intercept.gate(text, url=…)` 判定 + 记账，
  `intercept.cooldown_of(url)` 取该站点剩余冷却
- 插件抛错只让它自己掉队，不拖垮整条请求链路；`webtool plugins check interceptor` 看谁坏了
- **Cloudflare 质询单列一档**（`kind=cf_challenge`）：靠响应头 `cf-mitigated: challenge`
  与质询页专有特征识别，冷却 5 分钟起（普通验证页 30s 起），报错附处置建议。
  纯 HTTP 过不了这类拦截（要浏览器算 token），本项目**只识别不求解**；
  要过就得接真浏览器求解器，并复用 `cf_clearance`（须与抓取同出口 IP、同 UA）。
  细节见 [docs/intercept.md](docs/intercept.md)
- 判定挂在**每一个读完正文的入口**：`transport.get()`（搜索 / resolve / radar）与
  `pipeline/fetch.py`（全部抓取）；不看引擎、不看调用通道，只按响应本身判。
  唯一例外是 `transport.request()` —— 裸 API 通道，响应流直接交给调用方
  （股票接口、MCP、LLM），不在中途读体判定，因此不会被验证页特征误伤；
  出网统一走 `net/transport.py` 的规矩见 `docs/coding-standard.md`

## 开发

```bash
python3 scripts/gen_requirements.py    # pyproject.toml 是依赖唯一权威; 生成 requirements.txt (写下界)
                                       # 与 requirements.lock (钉死当前已装版本, 复现: pip install -r requirements.lock)
python3 scripts/audit_deps.py          # 查 import 了却没声明的依赖
python3 -m pytest tests -q             # 手写脚本以子进程方式逐个跑 (tests/check_all_scripts.py)
ruff check src tests                   # 门禁: E9 + F 全开 (含 F401)
```

新增模块后**必须重装**（`pip install --force-reinstall --no-deps .`，**不要 `-e`**）——源码目录只是开发时的临时视图，正式装要落成 site-packages 里的独立一份；否则 CLI 报"装包不完整"。
分层守卫钉在 `tests/test_layering.py`（含函数内延迟 import 的 ast 扫描）：依赖反向、
`sources/` 越层、注册表与实现漂移都会当场红。

代码分层 `cli` → `feeds`/`radar`/`zen` → `pipeline`/`render` → `net`/`engines` → `core`，只允许向下依赖。改代码前读 [docs/coding-standard.md](docs/coding-standard.md)，架构见 [docs/design.md](docs/design.md)，站点/订阅扩展见 [docs/custom-sites.md](docs/custom-sites.md)。
