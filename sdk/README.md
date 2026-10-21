# webtool 插件 SDK

单文件、零依赖：`python/webtool_plugin_sdk.py`。拦截器、engine、filter 等所有
类别共用这一套。

## 拦截器

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

```json
{"interceptor": {"waf": {"type": "external",
  "command": ["python3", "/path/to/plugin.py"],
  "timeout": 0.2, "hosts": ["example.com"]}}}
```

可选方法：`preflight / inspect / bypass / note_ok / note_hit`；`hit()` 与
`bypass()` 负责拼协议字段。

## 其它类别（engine / filter / extractor ...）

实现 `call(kind, args, kwargs)`，原样接住调用方参数：

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

注册表会把它包成普通 callable，调用方无感；不可用时返回 `null`。

## 协议要点

- stdin/stdout 一行一个 JSON；stdout 只放协议，日志走 stderr。
- 握手：`{"op":"ping"}` → `{"ok":true}`。
- 拦截器：`preflight / inspect / bypass / note_ok / note_hit`。
- 其它类别：`{"op":"call","kind":"filter","args":[...],"kwargs":{}}` →
  `{"result": ...}`。
- 正文默认截断 1MB（配置 `max_text`），超时按 `timeout` 杀进程。

## 目录

- `python/webtool_plugin_sdk.py`：SDK 本体，可直接拷走。
- `examples/python|node|go/`：三种语言的最小实现。
- `schema/interceptor.json`：协议 schema，可用于 CI 校验。

自测：

```bash
echo '{"op":"ping"}' | python3 examples/python/plugin.py
webtool plugins check
```
