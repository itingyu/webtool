"""切分来源记录

`sources/` 下十个源模块由 `api_client.py` 按方法名前缀切分而来。
原文件是切分时的唯一真值来源, 成员完整性校验以它为准。
"""

# 切分前的原始文件 (随仓, 由 shared/股票/API调研/ 提供)
ORIGINAL = '/var/minis/shared/股票/API调研/api_client.py'

# 拆出的文件 (拆完即删, 原件留在上面那份)
SPLIT_FROM = ORIGINAL
