出网路由: 代理完全由规则表决定
================================

**没有任何一条数据通道自己决定走不走代理。** 四条通道全部问
`netx.resolve_proxy('auto', url)`, 也就是 `~/.webtool/rules.json` + `config.json`
里那套规则; 代码里不硬编码代理地址, 也不按域名白名单直连。

改规则立即生效, 不需要重启: 路由决策按 `(域名, 生效的代理)` 缓存, 换代理
后自动重算 (`_routing.reset_cache()` 可手动清)。

四条通道的实现方式
------------------

| 通道 | 网络栈 | 怎么接到规则表 | 调用点是否要改 |
|---|---|---|---|
| `bridge/sources/` (154 方法) | requests + curl_cffi | `RoutedAdapter` / `RoutedCffiSession` 包装, **每请求现算** | 不改 (61 处裸 `.get()` 自动生效) |
| `stock/skill/` (2 处出网) | urllib | `bridge._stockmaster_net.get_opener(url)` | 改 2 行 (调用 opener 而非全局 `urlopen`) |
| `bridge/eco.py` (akshare 等) | 库内部自建 session | 调用期间给 `requests.Session.request` 包一层 | 不改 (理由见下) |
| `bridge/http.py` (裸 HTTP) | requests | 原本就调 `netx.resolve_proxy` | 不改 |

**出网只有 requests 与 curl_cffi 两条库内通道, 全仓没有 shell 出网出口。**
多一个 shell 出口就多一处能绕过规则表的地方, 而症状是裸连超时、整条链路全挂,
极难定位 —— 所以这层刻意不留口子。

为什么 sources 用"适配器"而不是逐个传 `proxies=`
------------------------------------------------

`sources/` 里有 **61 处** `self._std.get(...)`。逐个加 `proxies=` 漏一处,
那个源就静默绕过规则表 —— 而症状是"某个接口偶发被封", 极难定位。所以把决策
下沉到传输层: `RoutedAdapter.send()` 从 `request.url` 取目标域名现算代理,
调用方一行不动。curl_cffi 那边同理, 但它是函数式调用, 用
`RoutedCffiSession` 包一层即可 (只有 14 处, 但同样保持零改动)。

为什么 eco 要限定作用域
------------------------

akshare 有 326 个文件自带网络栈, efinance/tushare 各有自己的 session。
它们都是**外部依赖**, 改其源码每次升级都要重打一遍, 代价与收益不成比例。
所以这里在 `eco.call()` **作用域内**给 `requests.Session.request` 包一层默认
代理, 出作用域自动还原。

限定作用域的原因: 若进程内永久打补丁, 一次 `stock eco` 会把策略泄漏给同进程
后续的普通抓取 —— `stock eco` 与 `webtool fetch` 在同一进程里跑是常见组合。

本仓自己的代码 (`stock/skill/`、`bridge/sources/`) 则直接改, 不绕。

`baostock` 是例外, 它自己建 socket 不走 requests, 规则表管不到。
`stock health` 的 `route.eco` 里如实标了 `routed: false`, 不假装覆盖。

验证方法
--------

配置里放一个不存在的代理, 所有通道都该失败且报同一个代理:

```bash
# 临时把全局代理指向死端口
python3 - <<'EOF'
import json, os
p = os.path.expanduser('~/.webtool/config.json')
c = json.load(open(p)); c['proxy'] = 'http://127.0.0.1:9'
json.dump(c, open(p, 'w'), ensure_ascii=False)
EOF

webtool stock quote 600519          # → Connection refused 127.0.0.1:9
webtool stock http get <url>        # → 同上
webtool stock eco akshare stock_zh_a_spot_em   # → 同上
```

若某条通道仍能取到数, 说明它脱管了, 不是配置问题。