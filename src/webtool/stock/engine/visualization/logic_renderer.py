"""
逻辑图渲染器（mermaid 输出）
==========================
替代 alphaear-logic-visualizer 的 Draw.io XML
"""
def investment_logic(stock_code, stock_name, thesis, drivers, risks, catalysts):
    """
    投资逻辑图（mindmap）

    注意：mermaid mindmap 中 `((...))` 内不支持 `\n`，只能用一行；
    节点文本含 `(` `)` `[` `]` 等需清洗，否则解析失败。
    """
    def clean(t):
        return (str(t).replace("(", "（").replace(")", "）")
                .replace("[", "【").replace("]", "】")
                .replace("\n", " ").strip())

    md = "```mermaid\nmindmap\n"
    md += f"  root(({clean(stock_code)} {clean(stock_name)} {clean(thesis)}))\n"
    for label, items in (("核心驱动力", drivers), ("关键催化", catalysts),
                         ("风险点", risks)):
        md += f"    {label}\n"
        for it in items[:4]:
            md += f"      {clean(it)}\n"
    md += "```\n"
    return md


def decision_tree():
    """通用决策树"""
    return """```mermaid
graph TD
    A[候选池] --> B{主板可买?<br/>300/301/688/8/920/ST 排除}
    B -->|否| Z[剔除]
    B -->|是| C{流通市值 ≥ 50 亿?}
    C -->|否| Z
    C -->|是| D{20 日均额 ≥ 1 亿?}
    D -->|否| Z
    D -->|是| E{MA60 向上 且 现价 ≥ MA60?}
    E -->|否| Z
    E -->|是| F{资金面流入?<br/>北向/融资 任一}
    F -->|否| Z
    F -->|是| G[技术评分 ≥ 60]
    G --> H[候选池]
```"""


def industry_chain(name, upstream, midstream, downstream):
    """产业链图：上游 → 中游 → 下游"""
    md = "```mermaid\nflowchart LR\n"
    md += f"  subgraph {name}\n"
    md += "    direction LR\n"
    md += "    U[上游<br/>%s] --> M[中游<br/>%s] --> D[下游<br/>%s]\n" % (
        " / ".join(upstream[:4]), " / ".join(midstream[:4]),
        " / ".join(downstream[:4]))
    md += "  end\n```\n"
    return md