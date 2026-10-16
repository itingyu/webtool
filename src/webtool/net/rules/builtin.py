"""内置 kind 元数据: 已有消费方的四个环节 (http / retry / breaker / tls)

只登记元数据 (kind 名 / 动作字段 / 允许的匹配键), **不放默认值** —— 通用默认
值住在各环节模块的顶部常量 (transport 的 15s、resilient 的 retries/backoff/
fail_threshold), 那里是"无命中时"的唯一来源。本文件的作用是让 `kinds()` 能
被 CLI/文档枚举, 并让 Router 校验 kind 条目的 match 键拼写。

新增环节: 在环节自己的模块里 `register(RuleSpec(...))` 即可, 不必改这里 ——
这里只是随包内置的四个已接线 kind 的清单。
"""
from webtool.net.rules.spec import RuleSpec, register

register(RuleSpec(
    'http',
    fields=('timeout', 'fingerprint'),
    doc='HTTP 请求参数: timeout 空缺时填补, fingerprint 指定传输指纹档案'))

register(RuleSpec(
    'retry',
    fields=('retries', 'backoff'),
    doc='重试策略: retries 次数 / backoff 退避方式 (exp / flat)'))

register(RuleSpec(
    'breaker',
    fields=('fail_threshold', 'cool_seconds'),
    doc='熔断: fail_threshold 连续失败阈值 / cool_seconds 冷却秒数'))

register(RuleSpec(
    'tls',
    fields=('verify', 'ca', 'auto'),
    doc='证书策略: verify=on/off 该站单独关校验 / '
        'ca=<信任根文件> 用站点自己的证书验 (追加到基础 CA)'))
