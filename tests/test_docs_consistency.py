"""README 与真实命令/插件表的一致性检查."""

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from webtool.cli.app import _CMD_MODULE  # noqa: E402

README = (ROOT / 'README.md').read_text(encoding='utf-8')
PLUGINS = json.loads((ROOT / 'src/webtool/data/plugins.json').read_text(encoding='utf-8'))
fails = []


def check(ok, msg):
    print(('PASS ' if ok else 'FAIL ') + msg)
    if not ok:
        fails.append(msg)


# 1. README 命令表里的每个命令都真实注册
section = README.split('## 命令', 1)[1].split('## search', 1)[0]
documented = set()
for line in section.splitlines():
    if not line.startswith('|'):
        continue
    cell = line.split('|')[1]
    documented.update(re.findall(r'`([a-z][a-z0-9-]*)', cell))
COMMANDS = set(_CMD_MODULE) | {'site'}  # site 在 data 模块内注册, 不在分发表
unknown = documented - COMMANDS
check(not unknown, f'命令表无虚构命令 (未知: {sorted(unknown)})')
missing = COMMANDS - documented
check(not missing, f'命令表覆盖全部命令 (缺: {sorted(missing)})')

# 2. README 站点清单与插件表一致
line = next((x for x in README.splitlines() if x.startswith('- 站点 key：')), '')
keys = set(re.findall(r'[a-z][a-z0-9_]+', line.split('：', 1)[-1]))
check(keys == set(PLUGINS['site']),
      f'站点清单与 plugins.json 一致 (多: {sorted(keys - set(PLUGINS["site"]))}, '
      f'少: {sorted(set(PLUGINS["site"]) - keys)})')

# 3. 旧命令/旧参数不再出现
stale = ['webtool cache', 'webtool blocklist', 'webtool engines',
         'webtool banner', 'webtool pic', 'webtool video', 'webtool music',
         'plugins status', '--no-resolve']
hits = [s for s in stale if s in README]
check(not hits, f'README 无已删除用法 ({hits})')

print('\nALL PASS' if not fails else f'\n{len(fails)} FAILED')
sys.exit(1 if fails else 0)
