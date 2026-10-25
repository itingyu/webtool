# 测试

## 组织

`tests/` 下有两种文件：

- `test_*.py`：手写脚本，顶层 `check(cond, msg)`，失败 `sys.exit(1)`。
- `check_*.py`：供 pytest 收集的入口；`check_all_scripts.py` 以子进程逐个
  执行 `test_*.py` 并断言退出码 0，避免直接 import 触发 `sys.exit`。

`pytest.ini` 只收集 `check_*.py`，所以 `pytest -q` 是“全量跑一遍脚本”。

## 运行

```bash
# 单个脚本（开发时最常用）
PYTHONPATH=src python3 tests/test_intercept.py

# 全量
pytest -q
```

断了就按输出里的 `FAIL <说明>  <细节>` 定位，每个脚本都能单独复现。

## 约定

- **隔离**：涉及配置/状态/缓存的测试，开头设置
  `os.environ['WEBTOOL_DIR'] = tempfile.mkdtemp()`，禁止读写真实 `~/.webtool`。
- **不打真网**：用 `http.server` 起本地服务，或直接构造 HTML/JSON 文本；
  验证拦截、绕行、超时都用假插件。
- **多进程**：外部插件测试自己写临时脚本与 `plugins.json`，结束不残留进程。
- **分层**：改动 import 后跑 `tests/test_layering.py`，它按层校验依赖方向。
- **插件**：新增/修改注册逻辑后跑 `webtool plugins check`，再看
  `test_intercept_dispatch`、`test_plugin_missing`、`test_extplugin*`。

## 环境相关失败

字体/证书/代理相关的用例依赖运行环境（系统字体、系统 CA、可用出口、ffmpeg）。
缺失时表现为该脚本单独失败，不影响其它用例；先看错误类型再判断是否代码问题。
