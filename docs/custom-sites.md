# 自定义站点

放 `~/.webtool/sites/*.json`，一个文件可放多个站点。文件名随意，
键名就是站点 key（`webtool site <key> <词>` 用它）。

只支持 **JSON API**，不做 HTML/CSS 选择器。先确认目标站有返回 JSON 的搜索接口。

## 最小示例

```json
{
  "example": {
    "desc": "示例站",
    "url": "https://example.com/api/search?q={query}&limit={limit}",
    "results_path": "data/items",
    "fields": {
      "title": "title",
      "url": "link",
      "snippet": "summary|strip_html|trunc200",
      "date": "published_at|date_iso"
    }
  }
}
```

```bash
webtool site example 关键词
webtool site                                  # 清单里会多出 example
```

## 字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `url` | 是 | 搜索地址模板；`{query}` 已 URL 编码，`{limit}` 与 `{page}` 直接替换 |
| `results_path` | 是 | JSON 结果数组路径，用 `/` 分隔；数组下标写数字，`*` 表示对数组每项继续下钻 |
| `fields` | 是 | 输出字段映射；至少要有 `title` 和 `url`，否则该条被丢弃 |
| `desc` | 否 | 描述 |
| `headers` | 否 | 额外请求头；特殊键 `_kind` 取 `api`（默认，XHR 指纹）或 `nav`（浏览器导航指纹） |

## fields 取值

值是一个路径模板，支持三种写法：

- 普通路径：`"title"`、`"author/name"`、`"data/items/0/name"`（`/` 分隔，数组用下标）
- 字段拼接：`"https://example.com/p/{id}"`，`{id}` 从当前结果项按同一路径规则取
- 管道后处理：`"summary|strip_html|trunc200"`

支持的管道：

| 管道 | 作用 |
|---|---|
| `strip_html` | 去标签、压空白 |
| `trunc200` | 截前 200 字 |
| `date_ts` | 10 位/13 位时间戳 → `YYYY-MM-DD` |
| `date_iso` | 取 ISO 时间前 10 位 |
| `prefix:<文本>` | 给值加前缀 |

## 排查

- 站点没出现在 `webtool site`：JSON 语法错，或缺少 `url` / `results_path` / `fields`
- 报 `results_path ... not found`：路径写错，或接口把错误信息放进了 JSON
- 结果为空：`fields` 里 `title` 或 `url` 取不到，去看原始响应
- 需要登录/特殊 UA：在 `headers` 里加；反爬强的站优先用内置源，不要硬塞自定义站
