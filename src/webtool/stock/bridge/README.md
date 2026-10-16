# stock bridge — 取数下沉层

## 为什么要这一层

重构前 `stock/` 下七个取数模块与 `command.py` **平级**。后果不是难看, 是三层具体故障:

1. **CLI 被迫知道实现细节。** `command.py` 同时做动作分发 (CLI 该干) 和
   `import` 七个文件 (数据层该干), 于是 `do_stock` 里堆了六路
   `except MasterMissing / SrvError / RawApiError / EcoError / DocsError /
   HttpError` —— 唯一作用是判断"哪个文件抛的错"。(`MasterMissing` 本轮已随
   文件改名成 `EngineMissing`, 下文同。)
2. **七种异常类型。** `EcoError` / `DocsError` / `SrvError` / `HttpError` /
   `RawApiError` / `EmError` / `MasterMissing` 各继承 `RuntimeError`,
   调用方没法只接一层。现在全部继承 `StockError` (见 `error.py`),
   通道信息收进 `source` 字段, 退出码由类型自己声明。
3. **新增一个数据源要改五个地方。** 加接口 → 改对应 `sources/<源>.py` →
   改 `api_categories.json` → 改 `rawapi.py` 文档 → 改 `orchestrate.py` 的对应 `t_stock_*`。

现在分两层:

```
stock/
  command.py       ← CLI: 只做参数解析与输出
  bridge/          ← 本层: 只回答"数据怎么到手"
```

## 数据源按源拆分

`sources/` 下十个数据源模块 (另加传输/归一/自检等基建), **对外仍是一个 `APIClient`**:

```python
from webtool.stock.bridge.sources import APIClient
c = APIClient()
c.em_f10_balance('600519.SH')      # 方法名与拆包前逐字一致
```

| 模块 | 源 | 方法数 | 反爬手段 |
|---|---|---|---|
| `ths.py` | 同花顺 | 35 | v cookie (qjs 跑 akshare ths.js) + chrome120 指纹 |
| `em.py` | 东方财富 | 32 | 固定 `ut` token; datacenter 需 `source=WEB` |
| `xueqiu.py` | 雪球 | 31 | chrome110 TLS 指纹 + 3 页 warmup, 无 token |
| `sina.py` | 新浪财经 | 28 | Referer 校验 |
| `tencent.py` | 腾讯财经 | 9 | 部分端点需 curl_cffi 指纹 |
| `cninfo.py` | 巨潮 | 6 | 先 GET 首页收 cookie 再 POST |
| `csindex.py` | 中证指数 | 4 | Referer 校验 |
| `sse.py` | 上交所 | 3 | 直连 |
| `np.py` | 东财公告老域 | 2 | 统一 requests 会话 + 固定 UA |
| `ef.py` | efinance | 3 | 本地库, 无网络栈直控 |

合计 157 个方法: 由重构前那份 `api_client.py` 的公开方法切分而来, 另加各源补齐的
若干 (`gtimg_quote_flat` / `em_zt_pool` 等)。清单以 `webtool stock data list api`
的输出为准 —— 数字会变, 别把具体值当契约。

### 按域名归属, 不按方法名前缀

`gtimg_*` 七个方法虽然是"腾讯行情", 实际打的是
`vip.stock.finance.sina.com.cn` —— 按域名归入 `sina.py`, 名字保留不改
(改名会让上层和 `api_categories.json` 一起坏, 而域归属是维护者该查的信息,
不该由方法名承担)。

### 传输层不属于任何源

`_xueqiu_session` 名义属雪球, 但 `tencent_kline_global` / `tencent_us_kline`
/ `tencent_minute` 也借它 —— 要 curl_cffi 指纹才过 `web.ifzq.gtimg.cn`,
请求却打腾讯域名。指纹是**传输层**属性, 故放 `_base.py` 的 `SourceBase`。

## 非源类通道

| 模块 | 是什么 | 为什么不按源分 |
|---|---|---|
| `engine.py` | engine 脚本层 (选股/评分/研报口径) | 跨源聚合, 业务逻辑高于数据源; 取数仍经 sources |
| `srv.py` | 服务端 24 个高阶工具 | 同上, 且自带 fallback 链 |
| `eco.py` | akshare/tushare/baostock/efinance | 是"库集合"不是"站", 一个接口背后可能多源 |
| `em.py` (bridge 层) | 东财 reportName 配方泛化 | 建立在 `sources/em.py` 之上, 是配方层不是源 |
| `docs.py` | 逆向接口文档 | 纯本地文本, 一行 HTTP 都不发 |
| `http.py` | 裸 HTTP 直调 | 绕过全部封装的逃生口, 必须留在底层 |

## 出网路由

代理完全由 `~/.webtool/rules.json` + `config.json` 决定, 每条通道无一例外 ——
代码里不硬编码代理地址, 也不按域名白名单直连。三种网络栈各自的接法
(适配器 / 作用域补丁 / 直调) 与验证方法见 [`ROUTING.md`](ROUTING.md)。
engine 层不出网: 它的 HTTP 全部经 sources, 早先引擎自带的那两个 urllib
出口已并进 `sources/sina.py`、`sources/em.py`。

## 换版本

本仓 `sources/` 是按源重新拆分 `api_client.py` 的产物 (方法体逐字保留, 只改了
import 与注解), 拆完那份原单体就不再随仓 —— 它是**一次性迁移**的输入, 不是
长期依赖, 留着只会让"守卫"去比对一份永不变的历史文件。

- 上游更新 → 拿新版 `api_client.py` 当参考，按源改本仓对应模块，别整文件覆盖
- 完整性靠当下能验的东西: `sources/selftest.py` 真打接口, `test_smoke.py` 检
  `self.X(` 悬空 (漏拆的私有辅助当场暴露) + `test_sources.py` 查契约
- 无外部覆盖路径: 覆盖加载出的模块与包内那份是两个对象, 会导致两份
  `APIClient` 各带一份 token/session 缓存

## 打包

`sources/` 是普通子包, `packages.find` 自动收进 wheel。`test_smoke.py`
逐个点名十个源模块, 漏一个会在装包后才暴露。