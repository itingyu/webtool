"""proxy 子命令里"规则表"那一族: 读写 rules.json + rule add/del/tidy/rules

规则文件是分流的单一事实来源, 写它只走 _save_rules —— 不碰 config.json
(否则会拿旧快照覆盖刚写入的密文)。
"""
import json
import os
import sys
import time

from webtool.core.config_data import USER_DIR
from webtool.core.secrets_store import redact
from webtool.net.proxy.store import _norm_proxy_url


def _rules_path(cfg=None):
    """规则文件路径: 显式配置 > <USER_DIR>/rules.json"""
    p = (cfg or {}).get('rules_file')
    return os.path.expanduser(p) if p else str(USER_DIR / 'rules.json')


def _load_rules_file(cfg=None):
    """读规则文件。顺带把 proxies 段里的明文密码迁进保险库 ——
    `proxy rules` / `rule add` 这些命令走这里而不是 load_router, 漏掉的话
    用户在 CLI 里看到的还是明文, 而且规则写回时会把明文又存一遍。"""
    path = _rules_path(cfg)
    if os.path.isfile(path):
        try:
            with open(path, encoding='utf-8') as f:
                spec = json.load(f)
        except (ValueError, OSError):
            return {}
        from webtool.net import rules as _R
        spec, n = _R.migrate_plaintext_proxies(spec, path)
        if n:
            print(f'已把 {n} 个命名代理的密码加密存进保险库, '
                  f'{path} 里只留用户名', file=sys.stderr)
        return spec
    return {}


def _save_rules(cfg, spec):
    """规则一律写 rules.json (单一事实来源)。**不碰 config.json**:
    调用链上常刚把密码密文写进保险库 (store_password 直接落 config.json),
    这里再 save_config(cfg) 会拿旧快照把密文覆盖掉 (看着成功, 重启就没密码)"""
    path = _rules_path(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(spec, f, ensure_ascii=False, indent=2)
    print(f'规则已写 {path}')


def _default_proxy_url(cfg):
    """rules.json 里的命名代理 default (没有就 None)"""
    spec = _load_rules_file(cfg)
    d = (spec.get('proxies') or {}).get('default')
    return (d or {}).get('url') if isinstance(d, dict) else d


def _proxy_is_used(cfg, val):
    """这条代理是否被规则或 default 引用 —— 测通了但没人用它, 等于白测"""
    spec = _load_rules_file(cfg)
    want = _norm_proxy_url(val)
    names = [n for n, p in (spec.get('proxies') or {}).items()
             if _norm_proxy_url(p.get('url') if isinstance(p, dict) else p) == want]
    if not names:
        return False
    d_act = (spec.get('default') or 'direct')
    if d_act.startswith('proxy') and (d_act.split(':', 1)[1].strip() or 'default') in names:
        return True
    for r in (spec.get('rules') or []):
        a = str((r or {}).get('action') or '')
        if a.startswith('proxy') and (a.split(':', 1)[1].strip() or 'default') in names:
            return True
    return False


def _drift_hint(spec, cfg):
    """用户规则缺随包默认的 direct 域名时, 给一句可执行的补法"""
    import json as _json
    from importlib import resources

    from webtool.net import rules as _R
    try:
        shipped = _json.loads(
            resources.files('webtool').joinpath('data/rules.json').read_text())
    except (OSError, ValueError):
        return
    def domains(sp):
        out = set()
        for r in (sp or {}).get('rules') or []:
            if not isinstance(r, dict) or r.get('kind'):
                continue
            if _R.resolve_action(r.get('action'))[0] != 'direct':
                continue
            for d in (r.get('match') or {}).get('domain') or []:
                out.add(d.lower().lstrip('*').lstrip('.'))
        return out
    missing = domains(shipped) - domains(spec)
    if missing:
        sample = ' '.join(sorted(missing)[:6])
        print('ℹ 随包默认的直连域名有更新, 你的规则文件还没有 (%d 个): %s'
              % (len(missing), sample))
        print("  补: webtool proxy rule add '{\"domain\":[\"%s\"]}' direct"
              % '", "'.join(sorted(missing)[:6]))


def _rules(args, cfg):
    """规则查看 / 试算"""
    from webtool.net import rules as R
    r = R.load_router(cfg)
    for w in getattr(r, 'warnings', []):
        print(f'  ⚠ {w}', file=sys.stderr)
    if args.value:                       # 带 URL → 试算这条请求走哪条线路
        print(json.dumps(r.explain(args.value), ensure_ascii=False, indent=1))
        return 0
    spec = _load_rules_file(cfg)
    print(f'默认动作: {getattr(r, "default_action", "direct")}')
    print(f'命名代理: {json.dumps({k: redact(v.get("url") if isinstance(v, dict) else v) for k, v in (getattr(r, "proxies", {}) or {}).items()}, ensure_ascii=False)}')
    print(f'规则文件: {_rules_path(cfg)}')
    rules = (spec or {}).get('rules')
    if not rules:
        print('未配置规则')
        print('添加: webtool proxy rule add \'{"domain":["*.cn"]}\' direct')
        return 0
    for i, rule in enumerate(rules):
        act, name = R.resolve_action(rule.get('action'))
        via = f' → {name}' if name else ''
        print(f'  [{i}] {json.dumps(rule.get("match"), ensure_ascii=False)}'
              f'  ⇒ {act}{via}')
    # 配置漂移提醒: 随包默认的 direct 域名后来又加过新的 (引擎声明直连的站),
    # 用户文件按约定永不被覆盖, 旧快照就会一直缺 —— 引擎实际走的通道与
    # docstring 声称不符, 这种错只在某个引擎悄悄 0 结果时才被发现。
    _drift_hint(spec, cfg)
    # 有冗余就当场说, 别等用户自己发现规则表越长越难维护
    try:
        _, report = R.tidy_spec(spec)
    except Exception:
        report = []
    if report:
        # "与默认同结果"这类不算结构问题 (写出来当文档很常见), 不计入唠叨
        n = sum(1 for x in report if x.startswith('〔')
                and not x.startswith(('〔同默认〕', '〔提示〕')))
        if n:
            print(f'\n⚠ {n} 处可合并/冗余 —— 跑 webtool proxy tidy 预览, '
                  f'加 --apply 落盘 (会先备份)')
    return 0


def _tidy(args, cfg):
    """规则表合并: 同动作合并 + 冗余条目去除 + 与默认动作重复的规则去掉

    默认干跑 (只打印报告和结果), `--apply` 才落盘 —— 规则表是分流的总闸,
    偷偷改掉会让人查半天"为什么昨天还走代理今天直连了"。
    """
    from webtool.net import rules as R
    spec = _load_rules_file(cfg)
    try:
        new, report = R.tidy_spec(spec)
    except Exception as e:
        print(f'合并失败: {e}', file=sys.stderr)
        return 2
    if not report:
        print('规则表已经是合并后的形态, 无需改动')
        return 0
    print('\n'.join(report))
    before = len(spec.get('rules') or [])
    after = len(new.get('rules') or [])
    print(f'\n条数 {before} → {after}')
    if not getattr(args, 'apply', False):
        print('\n(干跑, 未改动。--apply 落盘, 会先备份原文件)\n')
        print(json.dumps(new, ensure_ascii=False, indent=1))
        return 0
    path = _rules_path(cfg)
    bak = None
    if os.path.isfile(path):
        bak = f'{path}.bak-{time.strftime("%Y%m%d-%H%M%S")}'
        try:
            import shutil
            shutil.copy2(path, bak)
        except OSError as e:
            print(f'备份失败, 未改动: {e}', file=sys.stderr)
            return 2
    _save_rules(cfg, new)
    print(f'\n已写入 {path}' + (f' (备份 {bak})' if bak else ''))
    print('校验: webtool proxy rules / webtool proxy rules https://google.com')
    return 0


def _ruleadd(args, cfg):
    """`proxy rule add <match JSON> <动作>`  →  args.user=JSON, args.act=动作"""
    from webtool.net import rules as R
    spec = _load_rules_file(cfg)
    raw = getattr(args, 'user', None)
    act = getattr(args, 'act', None)
    if not raw or not act:
        print('用法: webtool proxy rule add \'<match JSON>\' '
              '<direct|proxy|block|proxy:<名字>>', file=sys.stderr)
        return 2
    try:
        m = json.loads(raw)
    except ValueError as e:
        print(f'match 必须是合法 JSON: {e}\n'
              f'提示: shell 会吃掉双引号, 整段用单引号包起来;\n'
              f'  webtool proxy rule add \'{{"port":[8080,9000-9100]}}\' direct\n'
              f'注意端口区间写成字符串或数字都行, 但 [9000-9100] 少了引号/逗号'
              f'会被解析成减法', file=sys.stderr)
        return 2
    if not isinstance(m, dict) or not m:
        print('match 必须是非空 JSON 对象, 如 {"domain":["*.cn"]}',
              file=sys.stderr)
        return 2
    try:
        act_v, name = R.resolve_action(act)
    except R.RuleError as e:
        print(str(e), file=sys.stderr)
        return 2
    if act_v == 'proxy' and name and name not in (spec.get('proxies') or {}):
        print(f'注意: 命名代理 "{name}" 尚未在 proxies 里定义, '
              f'该规则会解析失败', file=sys.stderr)

    # 插入位置: 默认追加末尾; --first 插 [0]; --pos N 插第 N 位。
    # 追加位置在宽规则之后会被整条吃掉 (first-match-wins), 所以默认插到最前。
    # 所以下面还要跑一次覆盖试算, 被吃掉就直接说, 别等用户自己发现规则没用。
    rules = spec.setdefault('rules', [])
    first = bool(getattr(args, 'first', False))
    pos = getattr(args, 'pos', None)
    if first and pos is not None:
        print('--first 与 --pos 只能给一个', file=sys.stderr)
        return 2
    if first:
        at = 0
    elif pos is None:
        at = len(rules)
    else:
        try:
            at = int(pos)
        except (TypeError, ValueError):
            print('--pos 要整数', file=sys.stderr)
            return 2
        if not 0 <= at <= len(rules):
            print(f'--pos 越界 (0 ~ {len(rules)})', file=sys.stderr)
            return 2

    rules.insert(at, {'match': m, 'action': act})
    _save_rules(cfg, spec)
    print(f'规则已加 (第 {at} 条): '
          f'{json.dumps(m, ensure_ascii=False)} ⇒ {act}')

    # 覆盖试算: 插进去也可能永远不生效, 当场说清楚
    if at > 0:
        try:
            router = R.Router(spec)
            hit = R.shadow_check(router, m, act, at)
        except Exception:                                # noqa: BLE001
            hit = None
        if hit:
            print(f'⚠ 这条规则不会生效: 上面的规则[{hit[0]}] ({hit[1]}) '
                  f'已经覆盖了同样的域名, {("priority=direct 下 direct 规则压过 proxy 规则" if router.priority != "order" else "顺序在前")}'
                  f'。要它生效请用 --first 或 --pos 插到规则[{hit[0]}] 之前',
                  file=sys.stderr)
    return 0


def _ruledel(args, cfg):
    """`proxy rule del <序号>` → args.user=序号"""
    spec = _load_rules_file(cfg)
    try:
        idx = int(getattr(args, 'user', None))
    except (TypeError, ValueError):
        print('用法: webtool proxy rule del <序号>', file=sys.stderr)
        return 2
    rules = spec.get('rules') or []
    if not (0 <= idx < len(rules)):
        print(f'序号越界 (0 ~ {len(rules) - 1})', file=sys.stderr)
        return 2
    gone = rules.pop(idx)
    _save_rules(cfg, spec)
    print(f'已删除规则 {idx}: {json.dumps(gone, ensure_ascii=False)}')
    return 0
