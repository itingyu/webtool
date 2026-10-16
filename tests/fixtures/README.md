# tests/fixtures

测试用的**静态基线文件**，只作数据读，不被 import，也不参与 lint。

- `api_client_original.py` —— `src/webtool/stock/bridge/sources/` 切分前的原单体
  文件（3251 行 / 169 个 def），是"成员完整性"校验的唯一真值来源：
  `tests/test_smoke.py` 的「切分完整性」段按它核对每个原函数都已落位。
  它原先读项目外的 `/var/minis/shared/股票/API调研/api_client.py`——那份文件
  换台机器就没有，守卫会静默 SKIP（等于没有）。现在随仓，缺了就是 FAIL。
  切分已完成，这份基线只在重做/扩建 sources 时才需要更新。
