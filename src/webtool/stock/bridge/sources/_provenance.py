"""切分来源记录

`sources/` 下十个源模块由单个 `api_client.py`（3251 行 / 169 个 def）按方法名前缀
切分而来。那份原文件是切分时的唯一真值来源，成员完整性校验以它为准，现随仓存放在
`tests/fixtures/api_client_original.py`。

曾经写成项目外的绝对路径（`/var/minis/shared/股票/API调研/api_client.py`）——换台
机器、换个用户目录就没有那份文件，守卫会静默 SKIP，看着在跑其实什么都没查。基线
必须跟代码在同一个仓里，缺了就该 FAIL。
"""
# 基线相对仓库根的位置 (测试自己拼路径并断言存在, 这里只留事实)
BASELINE = 'tests/fixtures/api_client_original.py'
