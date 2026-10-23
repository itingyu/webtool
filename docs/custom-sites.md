# 自定义站点

内置站点在 `data/plugins.json` 的 `site` 段。想加自己的站，不用改代码：
在 `~/.webtool/sites/` 放一个 JSON，启动时自动并入（`webtool search --sources` 可见）。

## 文件格式

```json
{
  "name": "example",
  "url": "https://example.com/search?q={query}&page={page}",
  "headers": {"Accept-Language": "zh-CN"},
  "encoding": "utf-8",
  "list": "div.result",
  "item": {
    "title": "h3 a",
    "url": "h3 a@href",
    "snippet": "p.desc"
  },
  "page_start": 1,
  "page_step": 1,
  "pipeline": ["strip_html", "trunc200"]
}
```

- `url` 必填，支持 `{query}`、`{page}` 占位；其余键可选。
- `item` 的取值支持 `选择器@属性`（`@href`/`@src`/`@text`）；不写 `@` 取文本。
- `pipeline` 可选算子：`strip_html`、`trunc200`、`date_ts`、`date_iso`。
- 解析用 CSS 选择器；分页从 `page_start` 起，按 `page_step` 递增。

## 使用与调试

```bash
webtool search --sources
webtool search -s example "关键词" -n 5
```

- 先确认 `list` 选择器能选中 ≥1 个节点，再看 `item` 的相对选择器；写错不会
  报解析错，只会得到空结果。
- 站点目录按 mtime 重读，改完不用重启；新文件当场生效。
- 自定义站点同样走 `net/transport`：代理、TLS、拦截与冷却全部继承，不需要在
  配置里再写一遍。

## 限制

- 只解析静态 HTML；前端渲染的站点请用 `fetch`（可执行 JS）或专用 `engine`。
- 需要登录/签名的接口不适合这里，写独立 `engine` 插件更合适。
- 站点结构变更时，先更新选择器，别在 `pipeline` 里堆正则补救。
