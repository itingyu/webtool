# 自定义站点搜索配置

`webtool site` 支持用 JSON 配置扩展站点搜索，无需写代码。

实现见 `src/webtool/engines/customsites.py`，调度入口 `src/webtool/cli/sitesearch.py`。

## 配置位置

- `~/.webtool/sites/*.json`（用户级，按文件名排序加载，可放多个文件）
- **同名 key 覆盖内置站点**：自定义配置优先于内置（`sitesearch.py` 中先查 `customs`，命中即用）
- 配置不会自动生成，需自行创建该目录和文件

## 格式

```json
{
  "站点key": {
    "desc": "人类可读描述",
    "url": "https://api.example.com/search?q={query}&limit={limit}",
    "proxy": "direct",
    "method": "GET",
    "headers": {"X-Custom": "value"},
    "body": "POST 时的模板, 同样支持 {query}/{limit} 变量",
    "results_path": "data.items",
    "fields": {
      "title": "title",
      "url": "https://example.com/p/{slug}",
      "snippet": "content|strip_html|trunc200",
      "score": "relevance",
      "date": "created_at|date_iso"
    }
  }
}
```

## 校验规则

`load_custom_sites()` 只做一次轻量校验（`_validate`），三个字段缺一即判定无效：

| 字段 | 要求 |
|---|---|
| `url` | 必须非空 |
| `results_path` | **必须存在**，可为空串 `""`（表示响应本身就是数组） |
| `fields` | 必须非空 |

无效时不会崩溃，该站点在列表里标记为 `custom(BROKEN)`，desc 显示
`invalid spec: need url+results_path+fields`。JSON 语法错误按文件名注册，标记
`load fail: <原因>`。

## 说明

| 项 | 说明 |
|---|---|
| `{query}` / `{limit}` | URL/body 模板变量，请求前替换（`query` 会做 URL 编码） |
| `proxy` | `direct`=直连，`proxy`=走全局代理，`auto`=问路由表（默认）。**仅自定义站点有效**：内置站点一律 `auto`，线路只由 `proxy` 配置和规则表决定（内置清单里不再有 `proxy` 字段）。命令行 `--no-proxy` 与 `engine_proxy["site:<key>"]` 优先级更高 |
| `headers` | 追加请求头 |
| `results_path` | 响应 JSON 里结果数组的点分路径，如 `data.hits` |
| `fields` | 输出字段映射；值支持 `源字段\|管道函数` 链式 |

**管道函数**（`_pipe` 实际支持的，**仅这 5 个**）：

| 名称 | 作用 |
|---|---|
| `strip_html` | 去标签并压缩空白 |
| `trunc200` | 截断到 200 字符（硬编码，改长度需改代码） |
| `date_ts` | Unix 时间戳 → `YYYY-MM-DD`，解析失败原样返回 |
| `date_iso` | 已是 ISO 串时取前 10 位 |
| `prefix:XXX` | 在值前拼接固定串 |

> 未实现的（网上流传的其他写法）：`prepend:` / `append:` / `int` 均**不生效**，
> 会原样返回入参值。

**取值规则**：
- 所有字段值都以「单条结果 JSON」为根做点分路径取值
- `url` 可以是模板 `https://example.com/p/{slug}`，变量从结果项取
- 路径不存在时返回空值，不抛异常

## 实例

`~/.webtool/sites/custom.json`（用户自建）：

```json
{
  "v2ex": {
    "desc": "V2EX 主题搜索",
    "url": "https://www.sov2ex.com/api/search?q={query}&size={limit}&from=0",
    "proxy": "direct",
    "results_path": "data",
    "fields": {
      "title": "title|strip_html",
      "url": "https://www.v2ex.com/t/{id}",
      "snippet": "content|strip_html|trunc200",
      "score": "score",
      "replies": "replies",
      "date": "created|date_iso"
    }
  }
}
```

> 注意：内置已有 `sov2ex` 走同一套 sov2ex 索引，自定义 `v2ex` 属于功能重复。
> 保留仅当你想改字段映射或 `proxy` 时；否则建议删掉自定义项避免混淆。

## 验证

```sh
webtool site list             # 输出 JSON 数组, 看 source 字段区分 builtin/custom
webtool site v2ex python -n 2 -f json
```

- `site list` 输出的是 **JSON 数组**（不是表格），字段：
  `site` / `desc` / `proxy` / `source`（`builtin`、`custom(~/.webtool/sites)`、`custom(BROKEN)`）
- 配置错误时直接搜索会 stderr 报错并 `exit 2`，不会静默降级
