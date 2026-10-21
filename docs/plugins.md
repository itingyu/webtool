# 插件体系

所有可替换能力都在 `plugins.json` 里注册，代码里不写死。九类插件共用一套
注册、优先级、启停、热加载与外部进程机制。

## 注册

```json
{
  "engine": {"my_engine": {"module": "pkg.mod:search", "priority": 50}},
  "filter": {"only_docs": {"type": "external",
                           "command": ["node", "/opt/filter.js"],
                           "timeout": 0.5}}
}
```

字段：

| 字段 | 说明 |
|---|---|
| `module` | 进程内实现，`包.模块:函数或类` |
| `type` | `external` 表示外部进程（此时不需要 `module`） |
| `command` | 外部进程启动命令（列表，不经 shell） |
| `timeout` | 单次调用超时秒数，默认 0.5 |
| `priority` | 越小越先；拦截器默认 50 |
| `enabled` | `false` 停用 |
| `params` | 类别专属参数，原样随声明保留 |
| `hosts` | 仅拦截器：只在命中域名时调用 |
| `lifecycle` | `setup/teardown/healthcheck` 钩子，仅进程内插件 |

覆盖规则：`~/.webtool/plugins.json` 按类别按名字合并，只写要改的键；包内
`src/webtool/data/plugins.json` 是默认值。文件按 mtime 热加载；外部进程插件
改配置后执行 `webtool plugins reload` 关闭旧进程。

## 九类契约

| 类别 | 调用形态 | 返回 |
|---|---|---|
| `engine` | `fn(query, max_results, proxy, timeout)` | `[{title,url,snippet,...}]` |
| `hot` | `fn(query, limit, proxy, timeout)` | 热榜条目列表 |
| `site` | `fn(query, limit, proxy, timeout)` | 站内结果列表 |
| `extractor` | `fn(html, url, meta)` | 正文/markdown 或结构化片段 |
| `resolver` | `fn(url, proxy, timeout)` | 解析后的真实 URL |
| `filter` | `fn(results, ctx)` | 过滤后的结果列表 |
| `transformer` | `fn(results, ctx)` | 改写后的结果列表 |
| `interceptor` | 五个方法，见 `intercept.md` | `Hit` / `Bypass` / `None` |
| `source` | `SourceBase.fetch(req) -> DataPacket`、`health()` | 数据包 |

前七类在注册表里就是普通 callable，调用方直接 `FN(name)(...)`；外部进程由
代理透明转发，签名不变。

## 状态

`webtool plugins status <name>` 可能看到：

`declared`（声明了未加载）→ `loaded` / `active`；`failed`（代码报错）；
`missing`（配置有、代码或进程找不到）。缺失不报错，只在使用时提示
“插件未找到”，体检里单列 `missing`，不影响退出码。

## 两种实现形态

**进程内**：`module` 指向函数（前七类）或 `Interceptor` 子类。零额外开销，
能直接复用 `net.transport`、`dao` 等内部能力，但要求同 Python 环境。

**外部进程**：任意语言，声明 `type: external`。首次使用时拉起，`ping` 握手
通过后常驻复用；超时、崩溃、乱回都只让该插件掉队（30s 内不再重启），请求照走。
外部插件拿不到进程内对象，只能看到协议里给的数据。

外部插件的两种协议：

- 拦截器：`ping / preflight / inspect / bypass / note_ok / note_hit`
- 其它类别：`ping / call`，即
  `{"op":"call","kind":"filter","args":[...],"kwargs":{}}` → `{"result": ...}`

`ctx` 字段：`site`、`url`、`status`、`via`、`text`（默认截断到 1MB，可配
`max_text`）。`hit` 字段：`kind`、`sign`、`why`、`left`；`bypass` 字段：
`how`、`url`、`headers`、`profile`、`delay`、`retry`。

外部进程的 stdout 只放协议，一行一条；stderr 被丢弃，不要往 stdout 打日志。

## 无源码

- `.pyc`：`python -m compileall -b` 生成，放在插件目录即可 import。
- zip 包：丢进 `$WEBTOOL_PLUGIN_DIR`，自动加入 `sys.path`。
- `.so`：标准 C 扩展，版本需与解释器 ABI 匹配。

`__pycache__/x.pyc` 缺少源文件时不可用；版本不匹配会归入 `missing`。

## SDK

`sdk/python/webtool_plugin_sdk.py` 是单文件零依赖 SDK：`Plugin` 基类 +
`serve()`，拦截器实现 `inspect/bypass`，其它类别实现 `call(kind, args, kwargs)`。
`sdk/examples/` 有 Python / Node / Go 示例，`sdk/schema/interceptor.json`
是协议 schema。

自测：`echo '{"op":"ping"}' | python3 sdk/examples/python/plugin.py`

## 体检

```bash
webtool plugins list                 # 声明与状态
webtool plugins check                # 加载 / 签名 / 外部进程 ping；缺失归 missing
webtool plugins reload               # 重载代码与外部进程
webtool plugins disable <name>       # 等价于配置 enabled:false
```
