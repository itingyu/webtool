# -*- coding: utf-8 -*-
"""自升级 (webtool upgrade / update)

只管一件事: 让 pip 把 webtool 升到最新。**不碰本地源码** —— 不看仓库、不跑
git、不判祖先关系, 那些都是开发者自己的事, 用户装的是包。

"最新从哪来"也不自己判断, 交给 pip: `--check` 用
`pip install --upgrade --dry-run --report` 问一遍, 报告里有新版本就有新版。

升级目标 spec 的取法 (本项目走 git 分发, 不在 PyPI):
  1. 安装元数据 (PEP 610 direct_url.json) 里记了 VCS 源 → 就升那个源;
  2. 读不到 (wheel/打包器等) → 默认官方仓库。

注意: 对 **editable/本地目录** 安装跑这个, pip 会用 git 版覆盖掉本地那份。
那是"不管本地源码"的应有结果, 不是 bug —— 本地开发想更新请自己在仓库里收代码。
"""
import json
import os
import subprocess
import sys
import tempfile
from importlib import metadata

DIST_NAME = 'webtool'
# 本项目从 git 装 (不是 PyPI), 读不到安装来源时按官方仓库升
DEFAULT_REPO = 'https://github.com/itingyu/webtool'
PIP_TIMEOUT = 600


def _vcs_info(raw):
    """direct_url.json → {'url':..., 'commit':...} (不是 VCS 安装则 {})"""
    if not raw:
        return {}
    try:
        d = json.loads(raw)
    except ValueError:
        return {}
    info = d.get('vcs_info') or {}
    if not info:
        return {}                     # dir_info (本地/editable) 不算 VCS 安装
    # PEP 610: 仓库地址在顶层 url; vcs_info.url 只在两者不一致时才给 (如装的时候
    # 用的 ssh 地址、记录的是 https)。真实报文里 vcs_info 往往只有 commit_id ——
    # 只看 vcs_info.url 会认不出 git 装法 (这个坑实测踩过)。
    url = (info.get('url') or d.get('url') or '').strip()
    if not url:
        return {}
    return {'url': url, 'commit': (info.get('commit_id') or '').strip()}


def _vcs_url(raw):
    """direct_url.json → VCS 源 URL (不是 VCS 安装则 None)"""
    return _vcs_info(raw).get('url')


def _direct_url():
    """读安装元数据里的 direct_url.json

    Distribution.read_text 走 files 清单, 遇到 src/*.egg-info 这类残留目录
    会返回空 (被逐出过一次: 手跑 setup.py egg_info 留下的), 所以拿不到时
    直接去 sys.path 上的 dist-info 目录找一遍。
    """
    try:
        raw = metadata.distribution(DIST_NAME).read_text('direct_url.json')
    except metadata.PackageNotFoundError:
        return None
    if raw:
        return raw
    for entry in sys.path:
        try:
            for d in os.listdir(entry or '.'):
                if d.startswith(DIST_NAME + '-') and d.endswith('.dist-info'):
                    f = os.path.join(entry or '.', d, 'direct_url.json')
                    if os.path.isfile(f):
                        with open(f, encoding='utf-8') as fh:
                            return fh.read()
        except OSError:
            continue
    return None


def upgrade_target():
    """pip 的升级 spec: 装哪个源就升哪个, 读不到用官方仓库"""
    url = _vcs_url(_direct_url())
    return '%s @ git+%s' % (DIST_NAME, url or DEFAULT_REPO), (url or DEFAULT_REPO)


def installed_version():
    try:
        return metadata.version(DIST_NAME)
    except metadata.PackageNotFoundError:
        return None


def _hint(text):
    """把两个高频报错翻译成下一步动作 (用户不该去读 PEP 号)"""
    t = text or ''
    if 'externally-managed-environment' in t or 'PEP 668' in t:
        return ('系统 Python 被发行版保护 (PEP 668, Kali/Debian/新 Alpine 默认如此)。'
                '请装到虚拟环境里: `python3 -m venv ~/.webtool-venv` 后用它里面的 '
                'pip/webtool, 或 `pipx install ...`, 或 `pip install --user ...`。'
                '`--break-system-packages` 能硬闯但会搅乱系统 Python, 不建议。')
    if 'does not take a value' in t:
        return 'pip 的 --user 是开关, 不带值: 写 `--user`, 不是 `--user=你的用户名`'
    return None


def _pip(args, timeout=PIP_TIMEOUT, env_extra=None):
    """跑 pip, 返回 (rc, stdout, stderr)

    env_extra 是调用方给的代理变量: pip 与它拉起的 git 都只认环境变量,
    所以代理必须在 CLI 层用 netx 判好再传进来 (core 层不碰 net/rules)。
    """
    env = dict(os.environ, PIP_DISABLE_PIP_VERSION_CHECK='1')
    env.update(env_extra or {})
    try:
        r = subprocess.run([sys.executable, '-m', 'pip'] + list(args),
                           capture_output=True, text=True, timeout=timeout,
                           env=env)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 1, '', 'pip 超时 (%ss)' % timeout
    except OSError as e:
        return 1, '', 'pip 起不来: %s' % e


def _report_versions(path):
    """pip --report 的 JSON → {包名: 装了/将装的版本}"""
    try:
        with open(path, encoding='utf-8') as f:
            rep = json.load(f)
    except (OSError, ValueError):
        return {}
    out = {}
    for item in (rep.get('install') or []):
        md = item.get('metadata') or {}
        if md.get('name'):
            out[md['name'].lower().replace('_', '-')] = md.get('version')
    return out


def check(spec=None, env_extra=None):
    """问 pip 有没有新版 (dry-run + report, 判定交给 pip)"""
    spec = spec or upgrade_target()[0]
    fd, path = tempfile.mkstemp(prefix='webtool-report-', suffix='.json')
    os.close(fd)
    try:
        rc, out, err = _pip(['install', '--upgrade', '--dry-run', '--quiet',
                             '--report', path, spec], env_extra=env_extra)
        want = _report_versions(path)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    cur = installed_version()
    new = want.get('webtool')
    info = {'current': cur, 'latest': new or cur, 'spec': spec,
            'target_url': upgrade_target()[1], 'route': _route_label(env_extra),
            'ok': rc == 0}
    if rc != 0:
        info['state'] = 'unknown'
        info['error'] = (err or out).strip().splitlines()[-1:] and \
            (err or out).strip().splitlines()[-1] or 'pip 返回 %s' % rc
        info['hint'] = _hint((err or '') + (out or ''))
    elif new and cur and new != cur:
        info['state'] = 'behind'
    else:
        info['state'] = 'up_to_date'
        vcs = vcs_status(env_extra)          # 同版本的新提交只有远端知道
        if vcs:
            info['vcs'] = vcs
            if vcs.get('behind'):
                info['state'] = 'behind'
    return info


def describe(info):
    """人类可读的检查结果 (返回字符串, 调用方决定怎么输出)"""
    zh = {'up_to_date': '已是最新', 'behind': '有新版本可升',
          'unknown': '判不出来 (网络/pip 不通?)'}
    lines = ['webtool %s  (pip 通路: %s)' % (info['current'] or '?',
                                             info['spec']),
             '线路      %s' % (info.get('route') or '直连'),
             '最新      %s' % (info['latest'] or '?'),
             '状态      %s' % zh.get(info['state'], info['state'])]
    vcs = info.get('vcs') or {}
    if vcs.get('remote') or vcs.get('installed'):
        lines.append('提交      远端 %s / 已装 %s%s' % (
            (vcs.get('remote') or '?')[:7], (vcs.get('installed') or '?')[:7],
            '   ← 远端有新提交' if vcs.get('behind') else ''))
    if vcs.get('error'):
        lines.append('提交      问不到 (%s)' % vcs['error'])
    if info.get('error'):
        lines.append('备注      %s' % info['error'])
    if info.get('hint'):
        lines.append('怎么办    %s' % info['hint'])
    return '\n'.join(lines)


def _route_label(env_extra):
    """把代理变量翻成人话给输出看 (密码打码)"""
    prox = (env_extra or {}).get('HTTPS_PROXY') or \
        (env_extra or {}).get('https_proxy')
    if prox:
        from webtool.core.secrets_store import redact
        return '走代理 %s' % redact(prox)
    if (env_extra or {}).get('NO_PROXY'):
        return '直连 (按规则表)'
    return '直连'


def upgrade(spec=None, env_extra=None):
    """真的升级; 返回 {ok, action, log}

    git 源要 `--force-reinstall --no-deps`: pip 对"直接 URL 需求"只比**版本号**,
    同名同版本就报 "Requirement already satisfied" 然后什么都不干 —— 我们按 commit
    发代码、版本号不跟着动, 不强制重装的话 `upgrade` 是个装饰品 (实测: commit 原地
    不动)。`--no-deps` 是关键的另一半: 只换自己这份代码, 不去动依赖。
    """
    spec = spec or upgrade_target()[0]
    args = ['install', '--upgrade', spec]
    if 'git+' in spec:
        args = ['install', '--force-reinstall', '--no-deps', spec]
    rc, out, err = _pip(args, env_extra=env_extra)
    tail = [l for l in (out or '').strip().splitlines() if l.strip()][-6:]
    hint = _hint((err or '') + (out or '')) if rc else None
    if hint:
        tail = tail[-2:] + ['怎么办: %s' % hint]
    after = installed_version()
    return {'ok': rc == 0, 'action': 'pip-upgrade' if rc == 0 else 'none',
            'version': after, 'route': _route_label(env_extra),
            'log': ['pip: %s (%s)' % (spec, _route_label(env_extra))] + tail
            + ([err.strip().splitlines()[-1]] if rc and err.strip() else [])}


def vcs_status(env_extra=None):
    """远端 HEAD vs 已装的 commit: 有没有新提交

    pip 只比版本号, 看不出"同版本的新提交", 所以这一步自己问远端 (git ls-remote,
    只问远端、不碰任何本地仓库)。没 git / 没网络 / 不是 git 装法 → 返回 None,
    由调用方退回只看版本号, 不假装知道。
    """
    info = _vcs_info(_direct_url())
    if not info.get('url'):
        return None
    env = dict(os.environ)
    env.update(env_extra or {})
    try:
        r = subprocess.run(['git', 'ls-remote', info['url'], 'HEAD'],
                           capture_output=True, text=True, timeout=60, env=env)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {'url': info['url'], 'installed': info.get('commit', ''),
                'remote': None, 'behind': None, 'error': str(e) or '超时'}
    if r.returncode != 0:
        return {'url': info['url'], 'installed': info.get('commit', ''),
                'remote': None, 'behind': None,
                'error': (r.stderr or '').strip().splitlines()[-1:] and
                (r.stderr or '').strip().splitlines()[-1] or 'git ls-remote 失败'}
    remote = (r.stdout or '').strip().split('\t')[0].strip()
    got = info.get('commit', '')
    if not remote or not got:
        return {'url': info['url'], 'installed': got, 'remote': remote or None,
                'behind': None, 'error': 'commit 信息不全'}
    return {'url': info['url'], 'installed': got, 'remote': remote,
            'behind': remote != got}
