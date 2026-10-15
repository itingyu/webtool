# -*- coding: utf-8 -*-
"""遗留配置迁移的边界单测 (纯本地, 不联网)

背景是一条真实事故: `tests/test_smoke.py` 里那段"改配置看路由是否跟随"的用例
直接改真实 ~/.webtool/config.json, 塞进 `proxy: http://127.0.0.1:9`; 而
`_migrate_legacy_config` 会在下次读配置时把遗留键搬进 rules.json 的
proxies.default —— 测试只还原了 config.json, 于是每跑一次测试, 用户现网的默认
代理就被改成死端口 (实测 2080 → :9, 用户视角是"我没改, 它自己变的")。

这里盯两件事:
  1. 迁移不许覆盖 rules.json 里已经明确的 proxies.default (遗留键不得改现网分流)
  2. 迁移该迁的还得迁 (升级路径不能因此破掉), 没迁成的键不许从 config.json 删掉

隔离方式: 直接改 `webtool.net.proxy` 自己的 CONFIG_PATH / USER_DIR 全局 ——
这是那个函数真正读的两个变量 (先前只改 config_data.USER_DIR, 结果用例读写的
是真实文件, 断言全部落空)。另外每步都核对真实文件没被动过。

跑法: python3 tests/test_config_migrate.py
"""
import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from webtool.net import proxy as P

fails = []


def check(name, cond, detail=''):
    if cond:
        print(f'PASS {name}')
    else:
        print(f'FAIL {name} {detail}')
        fails.append(name)


def _md5(p):
    try:
        return hashlib.md5(Path(p).read_bytes()).hexdigest()
    except OSError:
        return None


# 真实文件指纹: 用例跑完必须原样 (helper 写错路径时能立刻发现, 而不是把现网改坏)
REAL_CFG, REAL_RULES = str(P.CONFIG_PATH), str(P.USER_DIR / 'rules.json')
_before = (_md5(REAL_CFG), _md5(REAL_RULES))


def run(cfg, rules):
    """在临时目录跑一次迁移, 返回 (rules, config, 迁移说明)"""
    d = Path(tempfile.mkdtemp(prefix='wt-migrate-'))
    (d / 'config.json').write_text(json.dumps(cfg, ensure_ascii=False),
                                   encoding='utf-8')
    (d / 'rules.json').write_text(json.dumps(rules, ensure_ascii=False),
                                  encoding='utf-8')
    o_cfg, o_dir, o_notes = P.CONFIG_PATH, P.USER_DIR, list(P._MIGRATION_NOTES)
    P.CONFIG_PATH = str(d / 'config.json')
    P.USER_DIR = d
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            P._migrate_legacy_config()
        notes = ' / '.join(P._MIGRATION_NOTES[len(o_notes):])
        return (json.loads((d / 'rules.json').read_text(encoding='utf-8')),
                json.loads((d / 'config.json').read_text(encoding='utf-8')),
                notes)
    finally:
        P.CONFIG_PATH, P.USER_DIR = o_cfg, o_dir
        del P._MIGRATION_NOTES[len(o_notes):]


LEGACY = {'proxy': 'http://127.0.0.1:9'}
EXISTING = {'default': 'proxy:default',
            'proxies': {'default': 'http://127.0.0.1:2080'},
            'rules': [{'match': {'domain': ['*.cn']}, 'action': 'direct'}]}

# 1. 规则文件已有 default → 遗留键不许覆盖, 且要出声
rules, cfg, notes = run(dict(LEGACY), dict(EXISTING))
check('已有 proxies.default 不被遗留键覆盖',
      rules['proxies']['default'] == 'http://127.0.0.1:2080', rules.get('proxies'))
check('覆盖被拒时给出说明并带上被丢弃的值',
      '未迁' in notes and '127.0.0.1:9' in notes, notes[:200])
check('规则文件其余内容不被顺手改写', rules['rules'] == EXISTING['rules'], rules)
check('被拒的遗留键从 config.json 摘掉 (不再反复唠叨)', 'proxy' not in cfg, cfg)

# 2. 规则文件为空 → 正常迁移 (升级路径不能破)
rules, cfg, notes = run(dict(LEGACY), {'rules': []})
check('无已有配置时正常迁移',
      rules['proxies']['default'] == 'http://127.0.0.1:9'
      and rules.get('default') == 'proxy:default', rules)
check('迁移后 config.json 摘掉遗留键', 'proxy' not in cfg, cfg)

# 3. 值相同 → 不算冲突
rules, cfg, notes = run(dict(LEGACY),
                        dict(EXISTING, proxies={'default': 'http://127.0.0.1:9'}))
check('值与现有一致时不报冲突',
      rules['proxies']['default'] == 'http://127.0.0.1:9' and '未迁' not in notes,
      notes[:120])

# 4. 没迁成的 proxy_rules 必须留在 config.json (不能假称保留实则删掉)
rules, cfg, notes = run({'proxy_rules': [{'domain': ['x.com'], 'action': 'direct'}]},
                        dict(EXISTING))
check('没迁成的 proxy_rules 留在 config.json', 'proxy_rules' in cfg, cfg)

# 5. 没有遗留键时什么都不写 (读操作不该有副作用)
_c = {'rules_file': None, 'proxies': {}}
rules, cfg, notes = run({'theme': 'dark'}, dict(EXISTING))
check('没有遗留键时不写 rules.json', rules == EXISTING, rules)
check('没有遗留键时不改 config.json', cfg == {'theme': 'dark'}, cfg)

# 6. 真实文件零改动 (helper 打错路径会在这里当场暴露)
check('真实 config.json/rules.json 未被本测试改动',
      (_md5(REAL_CFG), _md5(REAL_RULES)) == _before,
      f'{_before} → {(_md5(REAL_CFG), _md5(REAL_RULES))}')

print('\n' + ('ALL PASS' if not fails else f'FAILED: {fails}'))
sys.exit(1 if fails else 0)
