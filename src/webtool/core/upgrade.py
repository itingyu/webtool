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
import re
import shutil
import subprocess
import sys
import tempfile
import time
from importlib import metadata

from webtool.core.logging import get_logger

logger = get_logger(__name__)

DIST_NAME = 'webtool'
# scp 式地址 (git@github.com:owner/repo.git) —— 冒号后不跟 // 才算
_SCP_LIKE = re.compile(r'^(?:([^@/]+)@)?([^:/@]+):(?!//)(.+)$')
# 本项目从 git 装 (不是 PyPI), 读不到安装来源时按官方仓库升
DEFAULT_REPO = 'https://github.com/itingyu/webtool'
PIP_TIMEOUT = 600
GIT_TIMEOUT = 600


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
    # 用的 ssh 地址、记录的是 https)。vcs_info 里往往只有 commit_id ——
    # 只看 vcs_info.url 会漏认 git 装法。
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


_SRC_FILE = 'upgrade_source.txt'


def _src_file():
    from webtool.core.config_data import USER_DIR
    return os.path.join(str(USER_DIR), _SRC_FILE)


def saved_source():
    """上次记下的上游 (没有就 None)

    两步走之后代码是从**本地目录**装进去的, direct_url.json 记的就是那个临时目录;
    不记一笔, 下次升级拿它当上游, 等于升个寂寞。
    """
    try:
        with open(_src_file(), encoding='utf-8') as f:
            return f.read().strip() or None
    except OSError:
        return None


def remember_source(url):
    try:
        with open(_src_file(), 'w', encoding='utf-8') as f:
            f.write((url or '').strip() + '\n')
    except OSError as e:
        logger.debug('upgrade | 记上游失败: %s', e)


def upgrade_target():
    """pip 的升级 spec: 装哪个源就升哪个, 读不到用官方仓库

    上次两步走过的话以记下的上游为准 (见 saved_source)。
    """
    url = _vcs_url(_direct_url()) or saved_source()
    return '%s @ git+%s' % (DIST_NAME, url or DEFAULT_REPO), (url or DEFAULT_REPO)


def installed_version():
    try:
        return metadata.version(DIST_NAME)
    except metadata.PackageNotFoundError:
        return None

def spec_url(spec=None):
    """pip spec → (判线路用的 URL, 传输方式)

    传输方式: 'https'(含 http) / 'ssh' / 'git' / 'index'(PyPI) / 'local'。
    只有 https 与 index 会认 HTTP(S)_PROXY 环境变量 —— 这是给调用方判断
    "把代理塞进环境变量到底有没有用"用的, 别拿 ssh 源去套 http 代理。
    """
    raw = (spec or upgrade_target()[0]).strip()
    if ' @ ' in raw:                        # '名字 @ 源'
        raw = raw.split(' @ ', 1)[1].strip()
    if raw.startswith('git+'):
        raw = raw[4:]
    if raw.startswith('ssh://'):
        return raw, 'ssh'
    m = _SCP_LIKE.match(raw)
    if m:                                   # git@github.com:owner/repo.git
        user = m.group(1)
        return 'ssh://%s%s/%s' % (user + '@' if user else '', m.group(2),
                                  m.group(3)), 'ssh'
    if raw.startswith(('http://', 'https://')):
        return raw, 'https'
    if raw.startswith('git://'):
        return raw, 'git'                   # 裸 git 协议同样不认 http 代理
    if raw.startswith(('file://', '/', '.', '~')):
        return raw, 'local'
    return 'https://pypi.org/simple/', 'index'


_ERR_MARK = ('error', 'fatal', 'cannot', 'could not', 'no matching',
             'permission denied', 'externally-managed', 'not found',
             'timed out', 'ssl', 'certificate', 'proxy', 'denied',
             'did not run successfully', 'exit code', 'unable to')
# pip 的样板话术: 谁看都没用, 偏偏还带 "error" 字样, 最容易被截尾留下来
_SKIP = ('note: this error originates from a subprocess',)


def _pick(text, n=6):
    """从 pip 输出里挑几行"说人话"的

    pip 把真正的失败原因放在中间, 尾巴全是 "note: This error originates from a
    subprocess..." 之类的样板 —— 直接截尾会让用户只看到"完了", 看不到"为什么"。
    """
    lines = [l.rstrip() for l in (text or '').splitlines() if l.strip()]
    lines = [l for l in lines if not any(s in l.lower() for s in _SKIP)]
    if not lines:
        return []
    picked = []
    for l in lines:
        if any(m in l.lower() for m in _ERR_MARK) and l not in picked:
            picked.append(l)
        if len(picked) >= n:
            break
    return picked or lines[-n:]


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
    low = t.lower()
    if ('certificate' in low or 'unable to get local issuer' in low
            or 'certificate_verify_failed' in low):
        return ('这次握手是 pip/git 在做, webtool 的 ssl_verify / ca_bundle 管不着 '
                '它俩。把企业根证书喂给它们: `export GIT_SSL_CAINFO=/path/corp-root.pem` '
                '(pip 同理用 PIP_CERT), 或临时 `export GIT_SSL_NO_VERIFY=1`; '
                '也可先把仓库弄到本地, 再 `webtool upgrade --from /本地/webtool`。')
    if 'cannot find command' in low:
        return ('pip 装 git 源必须调 git, 这台机器上没有: '
                '`apt install git` / `apk add git` / Windows 装 Git for Windows 后重开终端; '
                '或先把仓库弄到本地, 再 `webtool upgrade --from /本地/webtool`。')
    if any(s in low for s in ('could not connect', 'failed to connect',
                              'could not resolve', 'connection timed out',
                              'network is unreachable', 'temporary failure')):
        return ('连不上源码仓库 (本项目只从 git 分发, PyPI 上没有)。代理只认环境变量: '
                '`HTTPS_PROXY=http://127.0.0.1:2080 webtool upgrade`; '
                '或把仓库弄到本地, 再 `webtool upgrade --from /本地/webtool`。')
    return None


def _dump_log(text, tag='upgrade'):
    """把子进程的完整输出落盘 —— 失败时用户总得有东西可查

    终端只挑几行给他看 (见 `_pick`), 全文塞进 `<用户目录>/logs/`, 路径随结果打出来。
    """
    from webtool.core.config_data import USER_DIR
    try:
        d = os.path.join(str(USER_DIR), 'logs')
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, '%s-%s.log' % (tag, time.strftime('%Y%m%d-%H%M%S')))
        with open(p, 'w', encoding='utf-8') as f:
            f.write(text)
        return p
    except OSError:
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


def pip(args, env_extra=None):
    """公开的 pip 入口 (给 CLI 补装依赖用)"""
    return _pip(args, env_extra=env_extra)


def dep_list():
    """本包声明的依赖 (来自元数据, 即 pyproject 里那份, 含上下界)

    装的时候 pip 只补**缺的** —— 已经在的它不碰, 所以不会因为一次升级顺手把
    pandas 之类追到最新版。
    """
    try:
        reqs = metadata.requires(DIST_NAME) or []
    except metadata.PackageNotFoundError:
        return []
    return [r for r in reqs if '; extra' not in r.lower()]


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


def check(spec=None, env_extra=None, note=None):
    """问 pip 有没有新版 (dry-run + report, 判定交给 pip)

    note: 调用方给的"这条线路对本源其实不生效"之类的人话备注, 原样带进输出。
    """
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
    if note:
        info['route_note'] = note
    if rc != 0:
        info['state'] = 'unknown'
        info['error'] = (err or out).strip().splitlines()[-1:] and \
            ' | '.join(_pick(err or out, 3)) or 'pip 返回 %s' % rc
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
    if info.get('route_note'):
        lines.insert(2, '注意      %s' % info['route_note'])
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
    """把代理变量翻成人话给输出看 (密码打码)

    `_pip_proxy_env` 把代理塞在 GIT_CONFIG_VALUE_0 里 (默认只给 git); 再只看
    HTTPS_PROXY 就会一律显示"直连" —— 那是骗人。
    """
    env = env_extra or {}
    prox = env.get('HTTPS_PROXY') or env.get('https_proxy')
    if not prox and env.get('GIT_CONFIG_KEY_0') == 'http.proxy':
        prox = env.get('GIT_CONFIG_VALUE_0')
    if prox:
        from webtool.core.secrets_store import redact
        who = 'pip+git' if env.get('HTTP_PROXY') or env.get('http_proxy') \
            else '只给 git'
        return '走代理 %s (%s)' % (redact(prox), who)
    if env.get('NO_PROXY'):
        return '直连 (按规则表)'
    return '直连'


def _safe_rmtree(path):
    """只删我们自己建的临时源码目录 —— 有一条不满足就一个字节都不动

    判断依据 (全过才删): 路径存在、不是符号链接、是真目录、父目录正是系统临时目录、
    目录名带 webtool-src- 前缀。宁可留残渣, 也不能删错东西。
    """
    if not path:
        return '清理: 没有临时目录, 无需清理'
    real = os.path.realpath(path)
    tmp = os.path.realpath(tempfile.gettempdir())
    base = os.path.basename(real.rstrip(os.sep))
    why = ''
    if not os.path.exists(real):
        why = '目录已经不在了'
    elif os.path.islink(path):
        why = '它是个符号链接'
    elif not os.path.isdir(real):
        why = '它不是目录'
    elif os.path.dirname(real) != tmp:
        why = '它不在临时目录里 (%s)' % os.path.dirname(real)
    elif not base.startswith('webtool-src-'):
        why = '它不是我们建的 (%s)' % base
    if why:
        logger.debug('upgrade | 清理跳过 %s: %s', path, why)
        return '清理: 跳过 —— %s' % why
    shutil.rmtree(real, ignore_errors=True)
    left = os.path.exists(real)
    logger.debug('upgrade | 清理 %s → %s', real, '没删掉' if left else '已删')
    return '清理: %s %s' % ('没删掉' if left else '已删', real)


def fetch_git(spec, env_extra=None, timeout=GIT_TIMEOUT):
    """第一步: 用 git 把源码取到临时目录 —— 不再让 pip 内嵌 git

    返回 (目录, 日志行, 错误)。非 git 源 (本地目录 / PyPI) 直接 (None, [], None),
    由调用方按老路装。

    好处是把"取源码"和"装包"分成两条腿: 各自用各自的设置 (git 认 GIT_CONFIG_*
    与 GIT_SSL_*, pip 认自己的), 出错也分得清是哪一步。
    """
    url, transport = spec_url(spec)
    if transport not in ('https', 'ssh', 'git'):
        return None, [], None
    if shutil.which('git') is None:
        return None, [], ('没装 git —— 两步走的第一步就是它。'
                          '装一个 (apt install git / apk add git), '
                          '或换本地目录源: webtool upgrade --from /path/to/webtool')
    dest = tempfile.mkdtemp(prefix='webtool-src-')
    log = ['源码: git clone --depth 1 %s (%s)' % (url, _route_label(env_extra))]
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0')
    env.update(env_extra or {})
    logger.debug('upgrade | git clone --depth 1 %s → %s', url, dest)
    try:
        r = subprocess.run(['git', 'clone', '--depth', '1', url, dest],
                           capture_output=True, text=True, timeout=timeout,
                           env=env)
    except subprocess.TimeoutExpired:
        return dest, log, 'git clone 超时 (%ss)' % timeout
    except OSError as e:
        return dest, log, 'git 起不来: %s' % e
    if r.returncode:
        tail = _pick((r.stderr or '') + '\n' + (r.stdout or ''), 3)
        return dest, log, 'git clone 失败: %s' % ' | '.join(tail)
    return dest, log + ['源码已取回: %s' % dest], None


def upgrade(spec=None, env_extra=None, note=None):
    """真的升级; 返回 {ok, action, log}

    分三步走 (不再 `pip install git+…`, 把 git 塞给 pip):

      1. git   —— 取源码到临时目录 (git 这条腿的代理/证书单独给, 见 fetch_git)
      2. pip   —— 从**本地目录**装 (--force-reinstall --no-deps)
      3. 清理  —— 删掉临时目录 (成败都删)

    为什么 `--force-reinstall --no-deps`: pip 对"直接 URL 需求"只比**版本号**,
    同名同版本就报 "Requirement already satisfied" 然后什么都不干 —— 我们按 commit
    发代码、版本号不跟着动, 不强制重装等于没升; `--no-deps` 则只管自己这份代码,
    依赖由调用方另走一步 (CLI 的 upgrade_deps)。

    从本地目录装完, direct_url 记的是那个临时目录, 所以真上游要另记一笔
    (upgrade_source.txt), 否则下次不知道升哪儿。

    note 同 check: 线路对本源失效时要说出来, 不能让"线路: 走代理"骗人。
    """
    spec = spec or upgrade_target()[0]
    src_dir, step_log, err = fetch_git(spec, env_extra)
    if err:
        if src_dir:
            # 取源码失败时那目录里可能只有半个 clone, 照样按守卫清掉
            step_log = step_log + [_safe_rmtree(src_dir)]
        return {'ok': False, 'action': 'none', 'route': _route_label(env_extra),
                'log': step_log + [err]}
    if src_dir:
        # 本地目录: pip 这一步不再需要 git, 也不需要网络 (依赖另有一步)
        args = ['install', '--force-reinstall', '--no-deps', src_dir]
    else:
        args = ['install', '--upgrade', spec]
    logger.debug('upgrade | pip %s (线路: %s)', ' '.join(args),
                 _route_label(env_extra))
    rc, out, err = _pip(args, env_extra=env_extra)
    if src_dir:
        # 第三步: 清理 —— 先验明正身再删 (见 _safe_rmtree), 成败都清
        step_log = step_log + [_safe_rmtree(src_dir)]
        if rc == 0:
            plain = spec.split(' @ ')[-1].strip()
            remember_source(plain[4:] if plain.startswith('git+') else plain)
    logger.debug('upgrade | pip 退出码 %s; stdout %s 字节 / stderr %s 字节',
                 rc, len(out or ''), len(err or ''))
    tail = _pick(out, 4 if rc else 6)
    if rc:                    # 真正的原因通常在 stderr, 别只盯 stdout
        tail += [l for l in _pick(err, 5) if l not in tail]
    hint = _hint((err or '') + (out or '')) if rc else None
    if hint:
        tail = tail + ['怎么办: %s' % hint]
    if rc:
        _logp = _dump_log('$ pip %s\n\n--- stdout ---\n%s\n--- stderr ---\n%s'
                          % (' '.join(args), out or '', err or ''))
        if _logp:
            tail.append('完整输出: %s' % _logp)
    after = installed_version()
    res = {'ok': rc == 0, 'action': 'pip-upgrade' if rc == 0 else 'none',
           'version': after, 'route': _route_label(env_extra),
           'log': step_log + ['pip: %s (%s)' % (spec, _route_label(env_extra))]
                  + tail}
    if note:
        res['route_note'] = note
        res['log'].insert(1, '注意: %s' % note)
    return res


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
                ' | '.join(_pick(r.stderr, 3)) or 'git ls-remote 失败'}
    remote = (r.stdout or '').strip().split('\t')[0].strip()
    got = info.get('commit', '')
    if not remote or not got:
        return {'url': info['url'], 'installed': got, 'remote': remote or None,
                'behind': None, 'error': 'commit 信息不全'}
    return {'url': info['url'], 'installed': got, 'remote': remote,
            'behind': remote != got}
