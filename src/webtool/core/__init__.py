"""L0 基础设施层: 不认识任何业务概念, 只提供通用能力

text / urls / jsonfmt 是抽出来的通用工具类, 被 L1+ 各层共用;
config / plugins / cache / state / http / probe / resilient 是运行底座。
这一层禁止 import 上层 (engines/search/feed/rank/cli 等)。
"""
