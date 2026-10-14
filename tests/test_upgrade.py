#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""webtool --version / upgrade 的契约测试 (跑 python3 tests/test_upgrade.py)

升级逻辑全部走 pip: 判定与安装都交给 pip, 测试里 stub 掉 pip 调用 —— 不打网络,
也不动本机的安装。
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))

from webtool.core import upgrade as _up            # noqa: E402
from webtool.core import version as _ver           # noqa: E402

PASS = FAIL = SKIP = 0


def check(cond, label, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'PASS {label}' + (f' ({detail})' if detail else ''))
    else:
        FAIL += 1
        print(f'FAIL {label}' + (f' (实际 {detail})' if detail else ''))


def skip(label, why):
    global SKIP
    SKIP += 1
    print(f'SKIP {label} ({why})')


def git(repo, *args, ok=True):
    """在临时仓库里跑 git; user 身份写死在命令里, 免得依赖全局配置"""
    r = subprocess.run(
        ['git', '-c', 'user.email=t@example.com', '-c', 'user.name=t',
         '-c', 'commit.gpgsign=false', *args],
        cwd=str(repo), capture_output=True, text=True)
    if ok and r.returncode != 0:
        raise RuntimeError('git %s 失败: %s' % (' '.join(args), r.stderr.strip()))
    return r.stdout.strip()


def head(repo, rev='HEAD'):
    return git(repo, 'rev-parse', rev)


def commit_file(repo, name, text, msg):
    (Path(repo) / name).write_text(text, encoding='utf-8')
    git(repo, 'add', name)
    git(repo, 'commit', '-m', msg)
    return head(repo)


def main():
    # ---------- 版本 ----------
    import tomllib
    with open(ROOT / 'pyproject.toml', 'rb') as f:
        proj_ver = tomllib.load(f)['project']['version']
    check(_ver.get_version() == proj_ver,
          '版本号一处真源: get_version() = pyproject', _ver.get_version())
    import webtool
    check(webtool.__version__ == proj_ver,
          '__version__ 不再是硬编码的第二份真相', webtool.__version__)
    _info = _ver.info()
    check({'version', 'python', 'platform', 'package_path', 'source_version',
           'installed_version', 'running_from_source', 'version_mismatch', 'deps'}
          == set(_info), 'version.info() 字段齐', str(sorted(_info))[:90])
    check(_info['deps'].get('trafilatura') and _info['deps'].get('curl_cffi'),
          'version.info() 带关键依赖版本')

    from webtool.cli import app as _app_mod
    cli = _app_mod.main

    def run(*argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli(list(argv))
        return rc, buf.getvalue()

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli(list(argv))
        return rc, buf.getvalue()

    _rc, _o = run('--version')
    check(_rc == 0 and _o.strip() == 'webtool %s' % proj_ver,
          'webtool --version 出单行版本号', _o.strip())
    check(run('-v')[1].strip() == 'webtool %s' % proj_ver, '-v 同 --version')
    check(run('-V')[1].strip() == 'webtool %s' % proj_ver, '-V 也认 (老习惯)')
    check(run('zen', '--version')[1].strip() == 'webtool %s' % proj_ver,
          '子命令后面也能 --version (main 预扫, 不走 click)')
    _rc, _o = run('--version', '-f', 'json')
    check(_rc == 0 and json.loads(_o)['version'] == proj_ver,
          'webtool --version -f json 出完整环境, 可解析')
    _rc, _o = run('version')               # 已撤掉的子命令, 别再回来
    check(_rc == 2 and 'version' not in _o,
          'version 子命令已撤 (只留 -v/--version 标志), 误输报 rc=2')

    # ---------- 升级: 判定交给 pip (全部 stub, 不打网络) ----------
    check('git+' not in _up.upgrade_target()[0] or _up.upgrade_target()[0]
          .startswith('webtool @ git+https://'),
          '升级目标从安装元数据推: VCS 源优先, 读不到用官方仓库',
          _up.upgrade_target()[0])
    check(_up._vcs_url('{"vcs_info": {"url": "https://x/y"}}') == 'https://x/y'
          and _up._vcs_url('{"dir_info": {"editable": true}}') is None
          and _up._vcs_url('not json') is None and _up._vcs_url(None) is None,
          '_vcs_url: 只认 VCS 安装, 本地目录/坏 JSON 一律 None')

    _rep = {'install': [{'metadata': {'name': 'webtool', 'version': '9.9.9'}},
                        {'metadata': {'name': 'Certifi', 'version': '1'}}]}
    _tf = Path(tempfile.mkdtemp(prefix='wt-rep-')) / 'r.json'
    _tf.write_text(json.dumps(_rep), encoding='utf-8')
    _pv = _up._report_versions(str(_tf))
    check(_pv.get('webtool') == '9.9.9' and _pv.get('certifi') == '1',
          'pip --report 解析: 包名归一化 (下划线→横线), 大小写无关')
    check(_up._report_versions(str(_tf.parent / 'nope.json')) == {},
          '报告文件不在 → 空 dict, 不抛异常')

    _real_pip = _up._pip

    def _stub(rc, report=None, err='', out=''):
        def f(args, timeout=None, env_extra=None):
            if report is not None:
                Path(args[args.index('--report') + 1]).write_text(
                    json.dumps(report), encoding='utf-8')
            return rc, out, err
        return f

    _up._pip = _stub(0, _rep)
    _info = _up.check()
    check(_info['state'] == 'behind' and _info['latest'] == '9.9.9',
          'pip 报告有新版 → state=behind', _info['state'])
    _up._pip = _stub(0, {'install': []})           # 没得升 → pip 不回 webtool
    _info = _up.check()
    check(_info['state'] == 'up_to_date' and _info['latest'] == _info['current'],
          'pip 报告无需安装 → up_to_date', _info['state'])
    _up._pip = _stub(1, None, err='ERROR: 连不上\nERROR: 真的连不上')
    _info = _up.check()
    check(_info['state'] == 'unknown' and '连不上' in _info['error'],
          'pip 失败 → unknown 且带 pip 最后一行错误 (不假装已最新)',
          _info['state'])
    res = _up.upgrade()
    check((not res['ok']) and res['action'] == 'none', 'pip 失败 → 不谎报成功',
          res['action'])
    _up._pip = _stub(0, None, out='Successfully installed webtool-9.9.9')
    res = _up.upgrade()
    check(res['ok'] and res['action'] == 'pip-upgrade'
          and any('Successfully installed' in l for l in res['log']),
          'pip 成功 → action=pip-upgrade 且回显 pip 原话', res['action'])
    _up._pip = _real_pip

    # git 源必须强制重装: pip 只比版本号, 同名同版本会直接跳过 (实测 commit 不动)
    _seen = []

    def _cap(args, timeout=None, env_extra=None):
        _seen.append(list(args))
        return 0, 'Successfully installed webtool-1.8.0', ''
    _up._pip = _cap
    _up.upgrade('webtool @ git+https://example.com/w')
    check('--force-reinstall' in _seen[-1] and '--no-deps' in _seen[-1],
          'git 升级: 强制重装+不动依赖 (否则 pip 报 satisfied 什么都不干)', _seen[-1])
    _up.upgrade('webtool')
    check('--force-reinstall' not in _seen[-1] and '--upgrade' in _seen[-1],
          '索引来源仍走普通 --upgrade (版本号说了算)')

    # 远端提交比对: 版本号没变时, 只有它看得见"新提交"
    import types as _types
    _real_sub = _up.subprocess
    _real_du = _up._direct_url
    _REAL = {'url': 'https://example.com/w',          # PEP 610 真实形状: 顶层 url
             'vcs_info': {'vcs': 'git', 'commit_id': 'a' * 40,
                          'requested_revision': None}}
    _up._direct_url = lambda: json.dumps(_REAL)
    check(_up._vcs_url(json.dumps(_REAL)) == 'https://example.com/w',
          'VCS 安装的仓库地址取自顶层 url (vcs_info 里常常没 url)')
    check(_up._vcs_url('{"url": "file:///x", "dir_info": {"editable": true}}')
          is None, '本地/editable 装法不算 VCS')
    _up.subprocess = _types.SimpleNamespace(
        run=lambda *a, **k: _types.SimpleNamespace(
            returncode=0, stdout='b' * 40 + '\tHEAD\n', stderr=''),
        TimeoutExpired=TimeoutError)
    v = _up.vcs_status()
    check(v['behind'] is True and v['remote'] == 'b' * 40,
          '远端 HEAD 与已装 commit 不同 → behind')
    _up.subprocess = _types.SimpleNamespace(
        run=lambda *a, **k: _types.SimpleNamespace(
            returncode=0, stdout='a' * 40 + '\tHEAD\n', stderr=''),
        TimeoutExpired=TimeoutError)
    check(_up.vcs_status()['behind'] is False, '同一个 commit → 不报有新东西')
    _up.subprocess = _types.SimpleNamespace(
        run=lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError('no git')),
        TimeoutExpired=TimeoutError)
    _v = _up.vcs_status()
    check(_v['behind'] is None and _v.get('error'),
          '没装 git → 老实说问不到, 不假装已最新', _v.get('error'))
    _up._direct_url = lambda: json.dumps({'dir_info': {'editable': True}})
    check(_up.vcs_status() is None, '非 git 装法直接跳过这一步')

    # check 把两者合起来: 版本号说最新, 但远端有新提交 → behind
    _up._direct_url = lambda: json.dumps(_REAL)
    _up.subprocess = _types.SimpleNamespace(
        run=lambda *a, **k: _types.SimpleNamespace(
            returncode=0, stdout='b' * 40 + '\tHEAD\n', stderr=''),
        TimeoutExpired=TimeoutError)
    _up._pip = _stub(0, {'install': []})
    _info = _up.check()
    check(_info['state'] == 'behind' and '远端有新提交' in _up.describe(_info),
          'pip 说版本最新但远端有新提交 → 判 behind 并说明')
    _up.subprocess, _up._direct_url, _up._pip = _real_sub, _real_du, _real_pip

    # 报错翻译: 用户不该去读 PEP 号
    check('虚拟环境' in (_up._hint('error: externally-managed-environment') or ''),
          'PEP 668 → 指到 venv/pipx/--user, 而不是甩个 PEP 链接')
    check('开关' in (_up._hint('--user option does not take a value') or ''),
          '--user=x 误用 → 指出 --user 不带值')
    check(_up._hint('ERROR: Could not find a version that satisfies') is None,
          '不认识的报错不乱猜原因')
    _up._pip = _stub(1, None, err='error: externally-managed-environment\nPEP 668')
    _info = _up.check()
    check('虚拟环境' in (_info.get('hint') or '') and '怎么办' in _up.describe(_info),
          'check 带上 hint, 且 describe 会打出来', _info['state'])
    _up._pip = _real_pip

    # 代理: 子进程只能拿环境变量, 判定交 netx (rules.json)
    from webtool.net import netx as _netx
    _real_rp = _netx.resolve_proxy
    _netx.resolve_proxy = lambda p, url=None: 'http://127.0.0.1:2080'
    _env = _app_mod._pip_proxy_env()
    check(_env.get('HTTPS_PROXY') == 'http://127.0.0.1:2080'
          and _env.get('http_proxy') == 'http://127.0.0.1:2080'
          and _env.get('NO_PROXY') == '',
          '规则表判代理 → pip/git 拿到 HTTP(S)_PROXY', str(sorted(_env))[:60])
    _netx.resolve_proxy = lambda p, url=None: None
    _env = _app_mod._pip_proxy_env()
    check(set(_env) == {'NO_PROXY', 'no_proxy'} and _env['NO_PROXY'] == '*',
          '规则表判直连 → 明确 NO_PROXY=* (屏蔽环境里可能残留的代理)',
          str(sorted(_env)))
    _netx.resolve_proxy = _real_rp

    # CLI 层: --check 走 stub, 输出与退出码 (0 最新 / 1 有新版本 / 2 判不出来)
    _up._pip = _stub(0, {'install': []})
    _rc, _o = run('upgrade', '--check')
    check(_rc == 0 and '已是最新' in _o and '线路' in _o,
          'webtool upgrade --check: 出线路与状态, 已最新退 0', _o.splitlines()[-1])
    _up._pip = _stub(0, _rep)
    _rc, _o = run('upgrade', '--check', '-f', 'json')
    check(_rc == 1 and json.loads(_o)['state'] == 'behind',
          '有新版本 → 退出码 1, -f json 可解析')
    _rc, _o = run('update', '--check')            # 别名
    check(_rc == 1, 'update 是 upgrade 的别名 (同一实现)')
    _up._pip = _stub(1, None, err='ERROR: nope')
    _rc, _o = run('upgrade', '--check')
    check(_rc == 2, '判不出来 → 退出码 2 (不是 0)')
    _up._pip = _stub(0, None, out='Successfully installed webtool-9.9.9')
    _rc, _o = run('upgrade', '--from', 'webtool @ git+https://example.com/w')
    check(_rc == 0 and 'Successfully installed' in _o,
          'webtool upgrade --from <spec> 换源可用 (默认走元数据里的源)')
    _up._pip = _real_pip

    print(f'\n{PASS + FAIL + SKIP} 项: {PASS} PASS, {FAIL} FAIL, {SKIP} SKIP')
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
