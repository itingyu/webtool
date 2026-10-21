# 外部插件（所有类别）与无源码插件

拦截器（以及其它插件）默认从 Python 源码 `import`。两种“没有源码”的场景各有出口。

## 1. Python 但不给源码

| 形态 | 做法 | 备注 |
|---|---|---|
| `.pyc` | `python -m compileall -b`，保留 `包/模块.pyc` 原位 | `__pycache__/x.pyc` 无源 **不行** |
| zip 包 | `pkg.zip` 丢进插件目录 | 已自动加入 `sys.path`（zipimport） |
| C 扩展 | 编译出 `mod.cpython-3xx-*.so` 放包内 | 需与解释器 ABI 匹配 |

插件目录：`$WEBTOOL_PLUGIN_DIR`，默认 `~/.webtool/plugins`。`entry` 写法不变：
`"module": "mypkg.mod:MyInterceptor"`。

`.pyc` 与解释器版本不匹配时报 `bad magic number`，体检归入 `missing`，不会中断请求。

## 2. 非 Python：声明 `type: external`

任何类别都适用：`engine` / `hot` / `site` / `extractor` / `resolver` / `filter` /
`transformer` 用统一的 `op=call`；`interceptor` 用第 3 节的专用 op（因为它有
`bypass` 和生命周期）。先看 `interceptor` 的写法：

```json
{
  "interceptor": {
    "waf_go": {
      "type": "external",
      "command": ["/opt/waf-plugin", "--stdio"],
      "timeout": 0.2,
      "hosts": ["example.com"],
      "max_text": 1000000,
      "cools_down": false,
      "priority": 40
    }
  }
}
```

| 字段 | 默认 | 说明 |
|---|---|---|
| `command` | 必填 | 列表形式，直接 `exec`，不经 shell |
| `timeout` | 0.5s | 单次请求超时；超时 kill 进程并冷却 30s |
| `hosts` | `[]` | 域名预筛，空 = 所有请求都看（有开销，建议按站声明） |
| `max_text` | 1e6 | 传给插件的正文上限，超出带 `truncated: true` |
| `cools_down` | `false` | 是否需要 `preflight`/`note_ok` 生命周期 |
| `priority` | 50 | 越小越先判 |

行为：懒启动 → `ping` 握手 → 常驻复用；进程挂了、超时、返回非 JSON，都只让该插件
掉队（静默），不影响其它拦截器和请求。`plugins check` 会实际起一次进程，起不来
列入 `missing`，退出码仍为 0。

### 2.1 其它类别

```json
{
  "filter":  {"only_docs": {"type": "external", "command": ["node", "/opt/filter.js"]}},
  "engine":  {"my_engine": {"type": "external", "command": ["/opt/engine"]}},
  "extractor": {"pdf2md": {"type": "external", "command": ["/opt/pdf2md"]}}
}
```

这些声明在注册表里被套成一个普通 callable，调用方（`ENGINES['my_engine']['fn'](...)`）
完全不知道背后是子进程。调用协议：

```json
{"op":"call","kind":"filter","args":[[{"url":"..."}]],"kwargs":{}}
{"result": [{"url":"..."}]}
```

`args` 是调用方原样传来的位置参数，`kwargs` 是关键字参数；返回 `{"result": ...}`
（可 JSON 化），出错返回 `{"error": "..."}`。插件不可用时调用返回 `null`，
上层按“无结果”处理，不抛异常。

## 3. 协议（stdio + NDJSON）

一行一个 JSON，UTF-8。请求带 `op`，响应可为空对象 `{}`。

| op | 请求附加字段 | 响应 |
|---|---|---|
| `ping` | `protocol: 1` | `{"ok": true}` |
| `preflight` | `ctx` | `{"hit": {...}}` 或 `{}` |
| `inspect` | `ctx` | `{"hit": {...}}` 或 `{}` |
| `bypass` | `ctx`, `hit` | `{"bypass": {...}}` 或 `{}` |
| `call` | `kind`, `args`, `kwargs` | `{"result": ...}` 或 `{"error": "..."}` |
| `note_ok` | `ctx` | `{}` |
| `note_hit` | `ctx`, `hit` | `{}` |

`ctx` 字段：`site`、`url`、`status`、`via`、`text`（可能截断）、`truncated`。

`hit` 字段：`kind`、`sign`、`why`、`left`（剩余冷却秒数，可省）。
`bypass` 字段：`how`、`url`、`headers`、`profile`、`delay`、`retry`（均可省）。

一次典型会话：

```
→ {"op":"ping","protocol":1}
← {"ok":true}
→ {"op":"inspect","ctx":{"site":"example.com","url":"https://example.com/a","status":200,"text":"..."}}
← {"hit":{"kind":"waf","sign":"cf-challenge","why":"质询页"}}
→ {"op":"bypass","ctx":{...},"hit":{"kind":"waf","sign":"cf-challenge"}}
← {"bypass":{"how":"换移动端入口","url":"https://m.example.com/a"}}
```

## 4. 实现骨架（任意语言）

```
loop:
  line = stdin.readline()
  msg  = json.parse(line)
  resp = handle(msg)          # 只看 op，无状态也可以
  stdout.write(json.dumps(resp) + "\n"); stdout.flush()
```

注意三点：逐行 flush；stdout 只放协议（日志走 stderr，当前被丢弃）；单次处理别超过 `timeout`。

## 5. 安全边界

- `command` 仅接受列表，框架不拼 shell，不展开通配符。
- 插件能看到响应正文（默认最多 1MB），按 `hosts` 缩小暴露面；敏感站点可调小 `max_text`。
- 外部插件在独立进程，崩溃/死循环不会拖垮 webtool 主进程。
- 不建议用 ctypes/FFI 接不可信 `.so`：同进程段错误无法隔离。
