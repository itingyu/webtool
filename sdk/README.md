# webtool 插件 SDK

所有类别插件（engine / filter / extractor / resolver / site / transformer /
interceptor）的最小开发套件。两条路：

| 形态 | 入口 | 适合 |
|---|---|---|
| Python 进程内 | 继承 `webtool.net.intercept.Interceptor` | 能装 webtool、追求零额外开销 |
| 外部进程（任意语言） | 本目录 SDK / 示例 + `type: external` | 不想绑 Python、要隔离、已有服务 |

协议规范见 [`docs/external-plugins.md`](../docs/external-plugins.md)，
机读 schema 见 [`schema/interceptor.json`](schema/interceptor.json)。

## Python（无依赖，可单独拷走）

```python
from webtool_plugin_sdk import Plugin, hit, serve

class Waf(Plugin):
    name = "waf"
    def inspect(self, ctx):
        if "cf-challenge" in (ctx.get("text") or ""):
            return hit("waf", "cf-challenge", "质询页")
        return None

if __name__ == "__main__":
    serve(Waf())
```

接入：把 SDK 文件放到插件旁边，`plugins.json` 写

```json
{"interceptor": {"waf": {"type": "external",
  "command": ["python3", "/path/to/plugin.py"],
  "timeout": 0.2, "hosts": ["example.com"]}}}
```

## 非拦截器类别（engine / filter / extractor ...）

实现 `call(kind, args, kwargs)`，原样接住调用方参数、返回可 JSON 化的结果：

```python
class OnlyDocs(Plugin):
    def call(self, kind, args, kwargs):
        rows = args[0] if args else []
        return [r for r in rows if "/docs/" in r.get("url", "")]
```

```json
{"filter": {"only_docs": {"type": "external",
  "command": ["python3", "/path/to/plugin.py"]}}}
```

注册表会把它包成普通 callable，`filter(...)` / `engine(...)` 的调用方无感；
不可用时调用返回 `None`，按“无结果”处理。

## 其它语言

- [`examples/node/plugin.js`](examples/node/plugin.js)：`readline` 逐行处理
- [`examples/go/main.go`](examples/go/main.go)：`bufio.Scanner` 逐行处理

共同要求：**stdout 只写协议行、逐行 flush**；日志走 stderr；单次处理不超过 `timeout`。

## 自测

```bash
# 直接手工发一行
echo '{"op":"ping"}' | python3 sdk/examples/python/plugin.py
# 让 webtool 体检（会真的起进程 ping）
webtool plugins check
```

## 打包发布

- Python：`.py` / `.pyc`（`compileall -b`）/ zip 包 / `.so` 均可，`module` 指向
  `pkg.mod:Class`；外部形态直接给 `command`。
- 其它语言：编成单文件二进制，`command` 用绝对路径；跨平台就按平台各编一份。
