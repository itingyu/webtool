# 拦截与绕过

所有页面请求共用一套判定：**不看引擎、不看调用通道，只看响应本身**。
命中后按站点记账、询问绕法、必要时重试；答案与过程都写进拦截日志。

## 判定入口

- `net/transport.py` 的 `get()`：读完正文后判定（搜索、resolve、radar 都走这里）。
- `pipeline/fetch.py`：流式抓取解码后判定（`fetch` 的全部站点）。
- `transport.request()` 是裸 API 通道，响应流交给调用方，不做中途判定。

判定键是 `Ctx.site`（host，去端口）。同一站点无论从搜索还是 fetch 进来，
冷却与日志都是同一笔账。

## 怎么判

特征来自 `data/plugins.json`：通用段（标题含 captcha/安全验证/just a moment，
正文含 cf-challenge 等）加上各引擎段的 `captcha_signs`，**加载时合并成一张
全局特征表**。因此请求带不带引擎名，判定一致。Cloudflare 质询单列一档，
**先判它**（见下节），其余走通用段。

- `len_lt`（正文过短）不参与合并：它是站点专属启发式，全站套用会把正常短页
  全判成验证页，而误判要付冷却代价。
- 特征表缓存 5 秒，避免每条响应重建 62 个插件的表；实测判定约 0.08ms。

## Cloudflare 质询（单列一档）

「浏览器里等几秒就自动放行」那种拦截是 Cloudflare 的**非交互式 JS 质询**：
服务端要的是浏览器算出来的 token，纯 HTTP 拿不到。它因此单列一档：

- **识别**：响应头 `cf-mitigated: challenge`（官方标记，最可靠）优先；正文只认
  质询页专有特征（`cf-challenge-running` / `challenge-spinner` / `cf-please-wait` /
  `trk_jschal_js` / `_cf_chl_opt` / `orchestrate/chl_page` / 标题 "Just a moment"）。
  **不放** `cf-ray`、`turnstile`、`cdn-cgi/challenge-platform` 这类泛用串 ——
  正常文章页挂 Turnstile 挂件、CF 站带 cf-ray 页脚，误判要付冷却代价。
- **冷却**：CF 质询按 **5 分钟起**翻倍（上限 4×），普通验证页仍是 30s 起。
  短冷却对这种拦截没意义，只会把 1 次拦截放大成连续请求，把站点信誉打得更差。
- **报错**：`BlockedError` 附处置建议 —— 换出口线路/换引擎，或接真浏览器求解
  （远端 FlareSolverr/Byparr）取 `cf_clearance` 复用；求解与抓取须**同一出口 IP
  且 UA 一致**，否则 clearance 失效。
- 命中类型记为 `cf_challenge`（普通验证页仍是 `captcha`），拦截日志的 `kind`
  字段能直接区分。

本项目**只识别不求解**（求解要真浏览器）。`Hit.hint` 字段就是给插件写处置
建议用的：命中时带上，报错时附在消息末尾。

## 冷却

按站点记：首次命中 30s，连续命中翻倍，上限 4×（即 120s）。冷却期内顶层请求
直接抛 `CooldownError`，不发请求；降级梯内部重试不受冷却门限制。

热更新特征：改 `plugins.json` 后 5 秒内生效；想立刻解除冷却，删
`~/.webtool/state.json` 的 `captcha` 段。

看当前谁在冷却：`webtool plugins engines list` 输出的 `cooldowns` 字段（键是站点），
代码里用 `intercept.cooldown_of(url)`。引擎名不是账本键 —— 同一引擎可能跨站
（google 的搜索页与 news 页各记各的）。

## 绕行与降级梯

被拦后先 `note_hit` 记账，再问插件有没有 `Bypass`：

```python
Bypass(how="补 chksm", url="…", headers={...}, profile="safari17",
       delay=0.0, retry=True, cookies={...}, user_agent="…")
```

- 重试次数由 `config.json` 的 `ladder_steps` 决定（默认 0）。
- 即使 `ladder_steps=0`，只要插件给了 `Bypass`，也会放行 **一次**；失败即报错，
  不放大请求量。
- 梯子内部只换指纹会话（`profile`），不会偷偷退直连；线路由 `rules.json` 决定。
- 全部用尽仍被拦 → `BlockedError`，消息里带命中特征与冷却秒数。
- `cookies` 灌进下一次重试的**会话 jar**（不是裸 `Cookie` 头：裸头会和会话
  自己的 cookie 打架、也会被目标站刚下发的 `Set-Cookie` 覆盖）；域名取目标站
  host，目标站才认。
- `user_agent` 会覆盖 impersonate 自带的 UA —— 这会让「UA 与 TLS 指纹同源」
  自曝。更稳的做法是用 `profile` 切到同版本档案，**并让求解器跑同一版本的
  浏览器**（CF 把 clearance 绑在访客/设备上，版本对不上照样拦）。

### 接一个真浏览器求解器

CF 质询这类拦截纯 HTTP 过不了，要过就得让真浏览器算一次 token，再把
`cf_clearance` 交回给 webtool 复用。插件侧的形状是：

```python
def bypass(self, ctx, hit):
    sol = solver.solve(ctx.url)          # 远端 FlareSolverr / Byparr / 自建
    if not sol:
        return None                       # 求解不了就老实报错, 别空转
    return Bypass(how='cf_clearance',
                  cookies={'cf_clearance': sol['cf_clearance']},
                  profile=sol.get('profile', ''))   # 同版本指纹档案
```

三条硬约束（否则求解白做）：**求解与抓取同一出口 IP**、**UA 一致**、
**浏览器版本与 `profile` 一致**。参考实现见
`sdk/examples/python/solver_flaresolverr.py`。

## 插件契约

拦截器类需继承 `net.intercept.Interceptor`，可选实现：

| 方法 | 时机 | 返回 |
|---|---|---|
| `preflight(ctx)` | 发请求前 | `Hit` 或 `None`（冷却短路） |
| `inspect(ctx)` | 拿到正文 | `Hit` 或 `None` |
| `bypass(ctx, hit)` | 命中后 | `Bypass` 或 `None` |
| `note_ok(ctx)` | 未命中 | 无 |
| `note_hit(ctx, hit)` | 确认命中 | 无（可更新 `hit.left`） |

`hosts=(...)` 预筛域名；`cools_down=True` 才参与冷却；`priority` 越小越先问
（captcha=10，wechat_poc=15）。

## 拦截日志

JSONL 写到 `~/.webtool/intercept.log`（随 `WEBTOOL_DIR`），2MB 轮转 `.1`。
只记判定事件，不记正常请求：`blocked / bypass / passed / failed`。

```bash
webtool intercept-log -n 20
webtool intercept-log --action blocked
webtool intercept-log --json
webtool intercept-log --clear
```

每条含 `ts / action / site / url / status / kind / sign / why / by / detail`。

## 案例：微信公众号 POC

`mp.weixin.qq.com/s?...` 缺少 `chksm` 参数会被判可疑，302 到
`/mp/wappoc_appmsgcaptcha` 或返回 `secitptpage/verify` 壳页。绕法是补任意
`chksm` 值（插件 `WechatPocInterceptor`，只对 `mp.weixin.qq.com` 生效），
补参后与正常链接内容 md5 一致。

真 TCaptcha 滑块无法纯 HTTP 通过，插件返回 `None`，不会制造无效重试。
