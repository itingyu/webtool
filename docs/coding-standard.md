# 工程规范

规则不是审美：每一条都能在测试或代码结构里找到落点，改完跑一遍就知道有没有
破线。

## 分层

依赖只能向下，唯一权威是 `tests/test_layering.py`（改动 import 先跑它）：

```
cli  →  pipeline / engines / sources / feeds / radar / render / filters / core
pipeline / engines / sources  →  net / dao / core
net / dao  →  core
core  →  只依赖标准库
```

- `core` 不认识任何上层业务，也不做网络请求。
- **出网决策统一走 `net/netx.py`**：代理路由、认证、TLS 策略、默认 UA 只从这里拿。
  具体通道是 `net/transport.py`（curl_cffi 指纹）与 `net/http.py`（urllib 兜底），
  禁止在引擎、流水线里直接 `requests/urllib/curl`，否则代理、TLS、重试、拦截全部绕空。
- 插件通过 `plugins.json` + 注册表接入，不在业务代码里写具体引擎名分支。

## 配置与常量

- 会变的都进配置：域名、选择器、站点清单、超时、降级步数。写死在代码里的
  只能是算法常量（如退避上限）。
- 读取统一走 `core/config_data`（带 mtime 缓存）；不要自己 `open(json)`。
- 配置缺失/写错必须能降级运行，错误可在 `webtool config list` 看到。

## 错误与日志

- 失败要分类：参数错误（退出 2）、运行期错误（退出 1）、用户中断（130）。
- 网络层只抛 `BlockedError / CooldownError / TlsError`，上层按类型决定换引擎
  还是直接退出；不要把所有异常压成一句“请求失败”。
- 允许 best-effort 的地方（落日志、记指标、清理临时文件）可以吞异常，但必须
  `logger.debug` 留痕，禁止裸 `except: pass`。
- stdout 只放结果；过程日志默认落 `~/.webtool/logs/webtool.log`，`-d/--debug` 才同时打 stderr。

## 代码风格

- 注释写“为什么”，不写“做了什么”；中文为主，术语保留英文。
- 公共函数返回数据，不打印、不 `sys.exit`；输出与退出码由 `cli` 决定。
- 数据结构用 `dataclass`（`Ctx / Hit / Bypass / DataPacket`），不要用裸 dict
  传内部契约；对外 JSON 才用 dict。
- 一个模块只解决一件事；跨模块复用先放 `core`，不要在引擎之间互相 import。
- 新增依赖要慎重：Alpine 下优先 apk 包，纯 Python 包才 pip；网络库不新增，
  统一用 `net` 层。

## 测试

- 测试是脚本式：`tests/test_*.py` 顶层 `check()` 断言，失败 `sys.exit(1)`，
  可直接 `PYTHONPATH=src python3 tests/test_xxx.py` 运行。
- 涉及配置/状态的测试必须设置 `WEBTOOL_DIR` 到临时目录，禁止写脏 `~/.webtool`。
- 不打真网：用本地 `HTTPServer` 或构造响应文本；验证降级/绕行用假插件。
- 新增行为至少覆盖：正常路径、失败路径、边界（超时、缺失、空响应）。

## 提交前

```bash
python3 -m compileall -q src/webtool
PYTHONPATH=src python3 tests/test_<相关模块>.py
PYTHONPATH=src python3 tests/test_layering.py      # 动了 import 必跑
webtool plugins check                              # 动了插件/配置必跑
```

- 行为变更同步改文档（本目录），文档与代码同一个提交。
- 不把无关改动（README 手改、临时脚本）混进提交。
- 新增配置项：写进 `core/config_schema.py`，并更新 `docs/design.md` 的配置表。
