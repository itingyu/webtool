# Idea Generation — 通用选股思路

**触发词**：选股思路 / 给我想法 / 选股框架 / stock screen

## 4 大风格

### Value（价值）
- PE 行业相对值 < 历史中位数
- EV/EBITDA < 历史均值
- FCF Yield > 5%
- PB < 1.5x
- Insider buying 90 日
- 股息率 > 市场均值

### Growth（成长）
- 收入增速 > 15% YoY
- 净利润增速 > 20% YoY
- 增速加速（rate increasing）
- 利润率扩张
- ROIC > 15%
- 高留存（Net Retention > 110% SaaS）

### Quality（质量）
- 高 ROE 持续
- 低杠杆
- 现金流稳定
- 行业护城河

### Special Situation（事件驱动）
- M&A 并购
- 重组 / 分拆
- 退市 / 回购
- 政策窗口

## Geographic / Thematic

按用户需求调整：
- 中国 / 美国 / 港股
- 主题：AI / 出海 / 国产替代 / 高股息 / 创新药

## 工具

读 `../data/screen-criteria.md` + `../data/typical-stocks.md` 作为参考池
调 `scripts/screening/{short,mid,long}_pool` 跑具体筛选
调 `scripts/fetchers/` 拉数据

## 输出形态

按风格分类的标的清单 + 入选逻辑。