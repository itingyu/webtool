# webtool 架构

给 Agent 用的网页搜索与内容获取 CLI：`search` 多引擎搜索、`fetch` 取正文与文件，输出 markdown / text / json。

## 分层

```
src/webtool/
├── cli/                 # typer 声明式 CLI (app/config/plugins); 命令函数填 SimpleNamespace 复用 do_*(args, cfg); 帮助用普通 click 样式 (rich_markup_mode=None, 不用 rich 面板大框)
│   └── sitesearch / zen / zenproto   # 站内搜索调度 / LLM 对话编排 / OpenAI 兼容协议
├── feeds/               # RSS/Atom 订阅聚合: command / sources / parse / fetch / cards / feedhealth
├── radar/               # RSSHub 路由查询与参数填充: routes / rules / instances / official / template / race
├── pipeline/            # search 调度 / fetch URL→正文 / rank 榜单 / merge 排序去重 / topup 补量 / qhint 质量诊断 / query_ops
├── render/              # render 正文渲染 / hotrender 榜单分节 / output 落盘
├── filters/             # blocklist 站点黑名单 / adfilter 广告识别 (纯规则, 不出网)
├── net/                 # L0 网络底座按 OSI 归位: transport 指纹传输 / fingerprints 指纹档案 / pacing 节奏·超时 /
│                        #   adapters requests 适配器 / proxy 线路 / tls 证书策略 / stream SSE+WS /
│                        #   rules 规则引擎 / http urllib 通道 / download 分片下载 / connectivity 探活 / dns / intercept 拦截绕过 / captcha / spa
├── engines/             # 各站适配器 (由 plugins.json 的 module 指向) + extractors / customsites / source (SearchSource 适配器)
├── sources/             # 数据契约层 (L0'): DataPacket 统一信封 + SourceBase 接口 + 注册表工厂
│                        #   五类内置源: search(引擎) · site(站内) · hot(榜单) · feed(RSS) · page(URL→正文)
├── dao/                 # DAO 层: cache 分桶 TTL / state 跨进程状态 / checkpoint 断点 (只存取, 不懂业务)
├── core/                # L0 底座
│   ├── plugins.py       # Registry: 八类插件统一注册表 (engine/site/hot/extractor/resolver/filter/transformer/interceptor/source)
│   ├── config_data.py   # 配置合并: 包内 data/*.json + ~/.webtool/ 同名文件 (深合并, 列表替换, 指纹判失效)
│   ├── resilient.py     # 弹性: parallel_map / thread_pool(守护线程池) / retry / breaker / fetch 包装
│   ├── shutdown.py      # 优雅关闭: Ctrl-C 一次协作退出 (rc 130)、两次强制 os._exit
│   └── text.py urls.py jsonfmt.py errors.py logging.py stdin.py
├── stock/               # 股票: command (动作) / bridge (数据源层) / data/reverse (逆向文档)
│                        #   data/trading_calendar/holidays-<年>.json = 交易日历 (运行必需,
│                        #   随包分发; 曾经读项目外的 shared/短线复盘/, 换机就静默降级)
└── data/                # plugins.json / filters.json / instances.json / zen.json / feeds.seed.json
                         #   certs/ca-bundle.pem = 兜底 CA (随包); 站点证书投放点
                         #   是用户目录 ~/.webtool/certs/extra/ (包内同名目录只是预置)
                         #   站点证书要由 rules.json 里的 kind:tls 规则点名才生效
                         #   (webtool proxy cert sync 按证书域名自动生成)
                         # 注: 在包根, core.config_data.DATA_DIR 指向它
```

依赖只允许向下：`cli` → `feeds`/`radar`/`zen` → `pipeline`/`render` → `net`/`engines` → `core`。

**扩展方式**：各类插件（engine / hot / site / extractor / resolver / filter / transformer / interceptor / source）在 `data/plugins.json` 声明元数据与模块路径，用户经 `~/.webtool/plugins.json` 覆盖或追加，`包路径:函数名` 约定，详见 README。适配器函数体（URL 构造、解析）属代码，留在 `engines/*.py`；权重、描述、代理偏好、过滤规则等元数据全部外置到 JSON。

## search 与 fetch

搜索：多引擎并发 → 归一化 → 去重合并（跨引擎佐证进 `weight`）→ 跳转链解码 → 输出 `rank/title/url/snippet/engines/weight`。默认只给摘要，正文另跑 `fetch`。

fetch 的四步：

1. **一次流式请求同时拿到响应头与 body 通道**（`transport.open_stream`），不做 "HEAD 探类型 + GET 下载" 两趟（HEAD 常被 405 或回假头）。
2. **按 `Content-Type` 判型**（`fetch.target_kind`），头认不出才看 URL 后缀。html → 提取链；text（json/xml/纯文本）→ 原样输出；image/video/audio/pdf/archive/font/binary → 落盘。
3. **落点**：`--save <文件或目录>` 覆盖，否则当前目录；文件名按 URL 末段（`.tar.gz` 双后缀保留），URL 没末段才退到 `Content-Disposition` → MIME。续传要求发请求前就知道落点（`Range` 得随请求头发出），定不出名字时不续传。
4. **三条守规矩**：4xx/5xx 错误页不落盘；超上限不留残件；二进制不进 stdout（类型/体积/落点走 stderr）。

二进制下载（`net/download/`）：边收边写、`.part` + `Range` + `If-Range` 续传、下完才改名；404 / 不认 Range / 响应被压缩时旧片段作废重下。`--jobs N` 多连接分片先探 `Range: bytes=0-0` 确认服务端认账与总大小，再把 `.part` 预分配成总大小，各段 seek 到自己的偏移写不相交区间；段数 `min(jobs, 4, 总大小/1MB)`，默认单连接（并发只在每条连接被限速时才有收益）。

## 正文提取

两层，清单在 `data/plugins.json` 的 `extractor` 段：

- **内容层**：trafilatura / boilerplate / readability —— 同层一起跑，按「碎片率 + 长度」择优（`extractors.pick_best`），不是先到先得。门户页 trafilatura 会带进推广块、长文合集页 readability 会丢正文，没有单一提取器通吃。
- **兜底层**：inscriptis / 零依赖剥标签 —— 整页纯文本，只在内容层全空时跑，不参与择优（它永远非空）。
- `boilerplate` 是 readability 算法的纯标准库实现，供装不上 lxml 的平台（Termux/Android）使用。

默认 `auto` 择优，`--extract <名>` / `config set extract <名>` 可固定，指定后无产出自动退回 auto。结果里的 `extract` 字段标明本次用的哪个提取器。

## 路由与网络

线路只由规则表判一次（`net/netx` 是唯一决策点），引擎、适配器、端点都不自报线路。

```jsonc
// ~/.webtool/config.json —— 只剩与线路无关的项 (timeout/cache/TLS...) + proxy_auth 密文
{ "timeout": 15, "cache_dir": "~/.webtool/cache" }

// ~/.webtool/rules.json —— 线路唯一决策源 (默认代理也在这)
{
  "default": "proxy:default",  // 未命中时的动作 (direct / block / proxy:<名>)
  "rules": [{"match": {"geosite": ["cn"]}, "action": "direct"}],
  "proxies": {"default": "http://127.0.0.1:2080"}
}
```

- `match` 内多条件 AND，同条件内多值 OR；判不出来 = 不匹配（缺库则跳过该条并提示）
- geo 库（geosite/geoip）随包自带一份，首次运行落到 `~/.webtool/geo/`，无需手动配就能用 `{"geosite":["cn"]}`；
  `webtool proxy geo update` 刷新用户态那份（下载内容不是 geo 库则拒绝替换）
- 带 `kind` 的规则不吃线路，按环节生效（`http` / `retry` / `breaker` / `tls`），与线路规则同住一份 rules.json、互不干扰
- 不支持按引擎名配代理；要单点覆盖就加一条规则（按域名/IP/端口/协议），或用 `--no-proxy` / `--proxy`
- 环境变量 `http_proxy`/`https_proxy` 不作为决策源（opener 层已堵死）；socks5 走 pysocks
- 证书**默认不校验**（`ssl_verify` 默认 `off`：没配就不校验，证书怎么处理由用户显式决定），
  失败直接抛错不重试；要严格就 `ssl_verify on`，按站点配用 `kind:tls` 规则（`ca` 换信任根 / `verify: off` 关该站校验），
  全局兜底才是 `verify_hosts` 点名豁免与 `ca_bundle` 换 CA；优先级 `verify=` 参数 > tls 规则 > `verify_hosts` > `ssl_verify`

## 输出

```jsonc
// search -f json
{"query":"...", "took_ms":1100, "results":[
  {"rank":1, "title":"...", "url":"https://...", "snippet":"...", "engines":["bing","sogou"], "weight":0.72}]}

// fetch -f json
{"url":"...", "status":200, "kind":"html", "title":"...", "content":"...",
 "metadata":{"author":"...","date":"...","sitename":"..."}, "took_ms":2300}

// 错误统一
{"error":"...", "url":"...", "hint":"建议: --engine sogou 或 --proxy ..."}
```

省 token 的手段：默认 markdown 正文（去广告/导航/脚本）· `--max-chars` 截断 · 搜索只给摘要 · 分桶缓存（search 60s / fetch 10s / 跳转解析 10min）· 输出去噪（合并空行、去 cookie 提示条等）· `-f txt` 是真纯文本（`core.text.md_to_text` 抹掉标记与 YAML 头）。
