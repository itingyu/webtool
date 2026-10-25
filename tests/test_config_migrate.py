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


def check(cond, msg, detail=''):
    if cond:
        print(f'PASS {msg}')
    else:
        print(f'FAIL {msg} {detail}')
        fails.append(msg)


def _md5(p):
    try:
        return hashlib.md5(Path(p).read_bytes()).hexdigest()
    except OSError:
        return None


# 真实文件指纹: 用例跑完必须原样 (helper 写错路径时能立刻发现, 而不是把现网改坏)
REAL_CFG, REAL_RULES = str(P.store.CONFIG_PATH), str(P.store.USER_DIR / 'rules.json')
_before = (_md5(REAL_CFG), _md5(REAL_RULES))


def run(cfg, rules):
    """在临时目录跑一次迁移, 返回 (rules, config, 迁移说明)"""
    d = Path(tempfile.mkdtemp(prefix='wt-migrate-'))
    (d / 'config.json').write_text(json.dumps(cfg, ensure_ascii=False),
                                   encoding='utf-8')
    (d / 'rules.json').write_text(json.dumps(rules, ensure_ascii=False),
                                  encoding='utf-8')
    o_cfg, o_dir, o_notes = P.store.CONFIG_PATH, P.store.USER_DIR, list(P.store._MIGRATION_NOTES)
    P.store.CONFIG_PATH = str(d / 'config.json')
    P.store.USER_DIR = d
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            P._migrate_legacy_config()
        notes = ' / '.join(P.store._MIGRATION_NOTES[len(o_notes):])
        return (json.loads((d / 'rules.json').read_text(encoding='utf-8')),
                json.loads((d / 'config.json').read_text(encoding='utf-8')),
                notes)
    finally:
        P.store.CONFIG_PATH, P.store.USER_DIR = o_cfg, o_dir
        del P.store._MIGRATION_NOTES[len(o_notes):]


LEGACY = {'proxy': 'http://127.0.0.1:9'}
EXISTING = {'default': 'proxy:default',
            'proxies': {'default': 'http://127.0.0.1:2080'},
            'rules': [{'match': {'domain': ['*.cn']}, 'action': 'direct'}]}

# 1. 规则文件已有 default → 遗留键不许覆盖, 且要出声
rules, cfg, notes = run(dict(LEGACY), dict(EXISTING))
check(rules['proxies']['default'] == 'http://127.0.0.1:2080',
      '已有 proxies.default 不被遗留键覆盖', rules.get('proxies'))
check('未迁' in notes and '127.0.0.1:9' in notes,
      '覆盖被拒时给出说明并带上被丢弃的值', notes[:200])
check(rules['rules'] == EXISTING['rules'], '规则文件其余内容不被顺手改写', rules)
check('proxy' not in cfg, '被拒的遗留键从 config.json 摘掉 (不再反复唠叨)', cfg)

# 2. 规则文件为空 → 正常迁移 (升级路径不能破)
rules, cfg, notes = run(dict(LEGACY), {'rules': []})
check(rules['proxies']['default'] == 'http://127.0.0.1:9'
      and rules.get('default') == 'proxy:default',
      '无已有配置时正常迁移', rules)
check('proxy' not in cfg, '迁移后 config.json 摘掉遗留键', cfg)

# 3. 值相同 → 不算冲突
rules, cfg, notes = run(dict(LEGACY),
                        dict(EXISTING, proxies={'default': 'http://127.0.0.1:9'}))
check(rules['proxies']['default'] == 'http://127.0.0.1:9' and '未迁' not in notes,
      '值与现有一致时不报冲突',
      notes[:120])

# 4. 没迁成的 proxy_rules 必须留在 config.json (不能假称保留实则删掉)
rules, cfg, notes = run({'proxy_rules': [{'domain': ['x.com'], 'action': 'direct'}]},
                        dict(EXISTING))
check('proxy_rules' in cfg, '没迁成的 proxy_rules 留在 config.json', cfg)

# 5. 没有遗留键时什么都不写 (读操作不该有副作用)
_c = {'rules_file': None, 'proxies': {}}
rules, cfg, notes = run({'theme': 'dark'}, dict(EXISTING))
check(rules == EXISTING, '没有遗留键时不写 rules.json', rules)
check(cfg == {'theme': 'dark'}, '没有遗留键时不改 config.json', cfg)

# 6. 真实文件零改动 (helper 打错路径会在这里当场暴露)
check((_md5(REAL_CFG), _md5(REAL_RULES)) == _before,
      '真实 config.json/rules.json 未被本测试改动',
      f'{_before} → {(_md5(REAL_CFG), _md5(REAL_RULES))}')

print('\n' + ('ALL PASS' if not fails else f'FAILED: {fails}'))
sys.exit(1 if fails else 0)
