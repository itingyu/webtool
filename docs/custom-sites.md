# 自定义站点搜索配置

`webtool site` 支持通过 JSON 配置文件快速扩展，无需写代码。

## 配置位置

- `~/.webtool/sites/*.json`（用户级，可放多个文件）
- 配置可覆盖内置站点（同名 key）

## 格式

```json
{
  "站点key": {
    "desc": "人类可读描述",
    "url": "https://api.example.com/search?q={query}&limit={limit}",
    "proxy": "direct | proxy | auto",
    "method": "GET",
    "headers": {"X-Custom": "value"},
    "body": "POST 时的 JSON 模板, 同样支持 {query}/{limit} 变量",
    "results_path": "data.items",
    "fields": {
      "title": "title",
      "url": "https://example.com/p/{slug}",
      "snippet": "excerpt|strip_html|trunc200",
      "score": "relevance",
      "date": "created_at|date_iso"
    }
  }
}
```

## 说明

| 项 | 说明 |
|---|---|
| `{query}` / `{limit}` / `{page}` | URL/body 模板变量，请求前替换 |
| `proxy` | `direct`=直连（国内站），`proxy`=走代理，`auto`=跟随全局（默认） |
| `headers` | 追加请求头（会覆盖默认浏览器指纹头） |
| `results_path` | 响应 JSON 里结果数组的点分路径，如 `data.hits`；响应是数组时留空 |
| `fields` | 输出字段映射；`源字段\|管道函数` 支持链式 |

**管道函数**：`strip_html`（去标签）、`trunc200`（截断，数字可换）、`date_iso`（时间戳→ISO 日期）、`prepend:`、`append:`（拼固定串）、`int`。

**字段特殊值**：
- `url` 可以是模板（如 `https://example.com/p/{slug}`），变量从结果项取
- 任何字段值都以结果项 JSON 为根做路径取值（支持点分）

## 实例

仓库自带两个示例见 `~/.webtool/sites/custom.json`（首次运行 `webtool site list` 自动生成）：

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

## 验证

```sh
webtool site list                  # 新站点出现且无 (BROKEN) 标记
webtool site v2ex docker -n 3      # 实际搜索
```

配置写错（JSON 语法错/results_path 不存在）不会崩，`site list` 里标记 `(BROKEN)` 并带原因。
