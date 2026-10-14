"""代理凭据保险库测试 (tests/test_secrets.py)

重点不在"能不能加密", 而在三件事:
  1. 密文真落盘了吗 —— 配置里不能出现任何明文密码
  2. 脱敏够不够狠 —— 日志/报错里不能漏密码, 也不能把正常文本改坏
  3. 缺密码时是否明确报错 —— 绝不能拿空密码去撞 407

全程用临时 WEBTOOL_DIR, 不碰用户真实的 ~/.webtool。
"""
import json
import os
import stat
import sys
import tempfile

WEBTOOL_DIR = tempfile.mkdtemp(prefix='wt-secrets-')
os.environ['WEBTOOL_DIR'] = WEBTOOL_DIR
os.environ.pop('WEBTOOL_SECRET_KEY', None)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from webtool.core import secrets_store as S   # noqa: E402

fails = []


def check(cond, msg):
    print(('PASS ' if cond else 'FAIL ') + msg)
    if not cond:
        fails.append(msg)


def cfg_path():
    return os.path.join(WEBTOOL_DIR, 'config.json')


def read_cfg():
    with open(cfg_path(), encoding='utf-8') as f:
        return json.load(f)


print('\n=== 1. 加密往返 ===')
if not S.have_crypto():
    print('SKIP 未安装 cryptography, 加密类用例跳过')
    blob = S.encrypt
else:
    blob = S.encrypt('p@ssw0rd-中文')
    check(S.is_encrypted(blob), f'密文带版本前缀 (实际 {blob[:12]}...)')
    check(S.decrypt(blob) == 'p@ssw0rd-中文', 'decrypt 还原原文')
    check(S.encrypt(blob) == blob, '重复加密幂等 (不会把密文再加密一遍)')
    check(S.is_encrypted('plain-text') is False, '明文不被当成密文')
    check(S.decrypt('plain-text') == 'plain-text', '非本模块的值原样返回')
    check(blob != 'p@ssw0rd-中文', '密文不等于明文')

    print('\n=== 2. 篡改的密文解不开 (完整性校验) ===')
    bad = S.PREFIX + ('A' * 40)
    try:
        S.decrypt(bad)
        check(False, '被篡改的密文应当解密失败')
    except S.SecretError:
        check(True, '被篡改的密文 → SecretError')
    except Exception as e:
        check(False, f'被篡改的密文抛了非 SecretError: {type(e).__name__}')

print('\n=== 3. 落盘不含明文 ===')
S.store_password('alice', 'sup3r-s3cret')
raw = open(cfg_path(), encoding='utf-8').read()
check('sup3r-s3cret' not in raw, 'config.json 全文不含明文密码')
auth = read_cfg().get('proxy_auth') or {}
check('alice' in auth, 'proxy_auth 里有 alice')
check(S.is_encrypted(auth.get('alice', '')), '存的是密文')
check(read_cfg().get('proxy') is None, 'store_password 不擅自改 proxy 字段')

print('\n=== 4. 重复存储不报"新建" ===')
check(S.store_password('bob', 'pw-bob') is True, '新用户 → True')
check(S.store_password('bob', 'pw-bob2') is False, '已存在用户 → False')
check(S.decrypt(read_cfg()['proxy_auth']['bob']) == 'pw-bob2', '密码已更新')

print('\n=== 5. resolve_auth 补密码 ===')
full = S.resolve_auth('http://alice@127.0.0.1:2080')
check(full == 'http://alice:sup3r-s3cret@127.0.0.1:2080',
      f'查保险库补上密码 (实际 {S.redact(full)})')
check(S.resolve_auth('http://bob:pw@1.2.3.4:80') == 'http://bob:pw@1.2.3.4:80',
      'URL 已带明文密码 → 原样返回 (老用法不破坏)')
check(S.resolve_auth('socks5://alice@1.2.3.4:1080') ==
      'socks5://alice:sup3r-s3cret@1.2.3.4:1080', 'socks5 同样能补')
check(S.resolve_auth('') == '' and S.resolve_auth(None) is None, '空输入安全')

print('\n=== 6. 缺密码必须报错, 不能静默用空密码 ===')
try:
    S.resolve_auth('http://nosuchuser@127.0.0.1:2080')
    check(False, '保险库里没有该用户时应当报错')
except S.SecretError as e:
    check('nosuchuser' in str(e), f'错误信息点明缺哪个用户 (实际 {e})')
    check('127.0.0.1' in str(e), '错误信息里带上目标主机, 便于定位')

print('\n=== 7. 密钥换了 → 旧密文解不开, 且不当明文用 ===')
key_path = os.path.join(WEBTOOL_DIR, 'secret.key')
os.replace(key_path, key_path + '.bak')
old_key = open(key_path + '.bak', 'rb').read()
old_alice_blob = read_cfg()['proxy_auth']['alice']   # 旧密钥下的密文, 留着
try:
    S.store_password('eve', 'eve-pw')    # 密钥文件已移走 → 自动生成**新**密钥
    new_key = open(key_path, 'rb').read()
    check(new_key != old_key, '密钥文件丢失后自动生成了不同的新密钥')
    try:
        S.decrypt(old_alice_blob)
        check(False, '换密钥后旧密文应当解不开')
    except S.SecretError:
        check(True, 'decrypt 换密钥后的旧密文 → SecretError (不是退回明文)')
    # 关键安全性质: 解不开的密文必须让 resolve_auth 报"缺密码",
    # 而不是塞个空密码去连 —— 那只会得到一个毫无线索的 407
    try:
        S.resolve_auth('http://alice@127.0.0.1:2080')
        check(False, '换密钥后 resolve_auth 应当报缺少密码')
    except S.SecretError as e:
        check('保险库里没有' in str(e), '换密钥后走"缺密码"提示, 不静默用空密码')
    # 用新密钥写的用户仍然正常 (别把整个保险库判死)
    check(S.resolve_auth('http://eve@127.0.0.1:2080') ==
          'http://eve:eve-pw@127.0.0.1:2080', '新密钥下的用户不受影响')
finally:
    os.replace(key_path + '.bak', key_path)      # 还原旧密钥, 不影响后续用例

print('\n=== 8. 环境变量密钥优先于文件 ===')
if S.have_crypto():
    from cryptography.fernet import Fernet
    env_key = Fernet.generate_key().decode()
    old = os.environ.get('WEBTOOL_SECRET_KEY')
    os.environ['WEBTOOL_SECRET_KEY'] = env_key
    try:
        blob2 = S.encrypt('env-pw')
        f = Fernet(env_key)
        check(f.decrypt(blob2[len(S.PREFIX):].encode()).decode() == 'env-pw',
              '密文确实由环境变量密钥生成')
        check(S.status()['key_file'].startswith('$'), 'status 显示密钥来自环境变量')
    finally:
        if old is None:
            os.environ.pop('WEBTOOL_SECRET_KEY', None)
        else:
            os.environ['WEBTOOL_SECRET_KEY'] = old

print('\n=== 9. 密钥文件权限 ===')
if os.path.isfile(key_path):
    mode = stat.S_IMODE(os.stat(key_path).st_mode)
    check(mode & 0o077 == 0, f'密钥文件不对同组/其他人开放 (实际 {oct(mode)})')
if os.path.isfile(cfg_path()):
    mode = stat.S_IMODE(os.stat(cfg_path()).st_mode)
    check(mode & 0o077 == 0, f'配置文件不对同组/其他人开放 (实际 {oct(mode)})')

print('\n=== 10. redact 脱敏 ===')
check(S.redact('http://u:p4ss@1.2.3.4:8080') == 'http://u:***@1.2.3.4:8080',
      f'user:pass@host → 脱敏 (实际 {S.redact("http://u:p4ss@1.2.3.4:8080")})')
check(S.redact('socks5://u:p4ss@1.2.3.4:1080') == 'socks5://u:***@1.2.3.4:1080',
      'socks5 同样脱敏')
check(S.redact('http://1.2.3.4:8080') == 'http://1.2.3.4:8080', '无凭据不动')
check(S.redact('http://user@1.2.3.4:8080') == 'http://user@1.2.3.4:8080',
      '只有用户名没有密码 → 不动')
check(S.redact('https://a.com/x@y') == 'https://a.com/x@y',
      '路径里的 @ 不当成凭据分隔符')
check(S.redact('mailto:a@b.com') == 'mailto:a@b.com', '非 URL scheme 不动')
check(S.redact('/data/x@y/z') == '/data/x@y/z', '文件系统路径不动')
check(S.redact('plain text') == 'plain text', '普通文本不动')
check(S.redact('') == '' and S.redact(None) is None, '空输入安全')
check(S.redact('连接代理失败 http://u:secret@h:1', keep_tail=2) ==
      '连接代理失败 http://u:***et@h:1', 'keep_tail 只留尾部')

print('\n=== 11. status 不含明文 ===')
st = S.status()
blob_text = json.dumps(st, ensure_ascii=False)
check('sup3r-s3cret' not in blob_text and 'pw-bob2' not in blob_text,
      'status 不泄露任何明文密码')
check('alice' in st['users'] and 'bob' in st['users'], 'status 列出用户名')

print('\n=== 12. 删除 ===')
check(S.drop_password('bob') is True, '删除已存在用户 → True')
check(S.drop_password('bob') is False, '重复删除 → False')
check('bob' not in (read_cfg().get('proxy_auth') or {}), 'bob 已从密文表移除')
check('alice' in (read_cfg().get('proxy_auth') or {}), '删 bob 不影响 alice')

print('\n=== 13. 配置损坏时不崩 ===')
with open(cfg_path(), 'w', encoding='utf-8') as f:
    f.write('{ this is not json')
check(S.status().get('users') == [], '坏 JSON → status 返回空列表, 不抛')
check(S.store_password('carol', 'pw') is True, '坏 JSON 上写入能恢复成合法配置')
check(S.decrypt(read_cfg()['proxy_auth']['carol']) == 'pw', '恢复后密文可解')

print('\n=== 14. CLI 位置参数映射 (setpass/delpass) ===')
# proxy 的位置参数是 <action> [value] [user] [act], 而 _setpass 期望
# user=用户名 / value=密码。这层换序在 proxy.handle 里做 —— 一旦漏掉,
# `webtool proxy setpass bob` 会静默变成"没给用户名"并只打 usage, 很难联想到
# 是参数映射错了。所以直接调 handle 验, 覆盖真实调用路径。
import io                      # noqa: E402
import types                   # noqa: E402
from webtool.net import proxy as PX   # noqa: E402

_stdout, _stderr = sys.stdout, sys.stderr
out = io.StringIO()
sys.stdout = out
try:
    rc = PX.handle(types.SimpleNamespace(action='setpass', value='dave',
                                         user='dave-pw', act=None), {})
finally:
    sys.stdout = _stdout
check(rc == 0, f'setpass 位置参数 (用户名在前, 密码在后) 可用 (rc={rc})')
check('dave' in (read_cfg().get('proxy_auth') or {}), 'setpass 写进了 dave')
check(S.decrypt(read_cfg()['proxy_auth']['dave']) == 'dave-pw', '密码落对用户')

out = io.StringIO()
sys.stdout = out
try:
    rc = PX.handle(types.SimpleNamespace(action='delpass', value='dave',
                                         user=None, act=None), {})
    rc2 = PX.handle(types.SimpleNamespace(action='delpass', value='ghost',
                                          user=None, act=None), {})
finally:
    sys.stdout = _stdout
check(rc == 0, 'delpass 删已存在用户 → 0')
check(rc2 == 2, 'delpass 删不存在用户 → 2 (用法错)')
sys.stderr = _stderr

print('\n=== 15. 特殊字符密码 (含 / @ : 中文) ===')
# urlsplit 在 authority 里遇到 / 就截断, 再取 port 会抛
# "Port could not be cast to integer value" —— 曾经直接吐 traceback。
# 代理 URL 按"host 在最后"的实际形状手工拆, 这类密码才能原样存取。
from webtool.net.proxy import proxy_url_parts    # noqa: E402

for raw, want_pw in [
    ('http://u:p/w@h:2080', 'p/w'),
    ('http://u:p@ss@h:2080', 'p@ss'),          # 密码里的 @ 不能误切用户名
    ('http://u:p:w@h:2080', 'p:w'),            # 密码里的 :
    ('http://u:p@ss:w/rd-中文@h:2080', 'p@ss:w/rd-中文'),
    ('socks5://u:p/w@10.0.0.1:1080', 'p/w'),
]:
    scheme, user, pw, host, port = proxy_url_parts(raw)
    check(pw == want_pw and host == 'h' if port == '2080' else
          (pw == want_pw and host == '10.0.0.1'),
          f'{raw} → user={user} host={host} port={port} pw 还原正确')
check(proxy_url_parts('http://127.0.0.1:2080')[1] == '', '无凭据时 user 为空')
check(proxy_url_parts('127.0.0.1:2080') == ('', '', '', '', ''), '无 scheme 安全')

out = io.StringIO()
sys.stdout = out
try:
    PX.handle(types.SimpleNamespace(action='set', value='http://u9:p/w@h:9',
                                    user=None, act=None), PX.load_config())
finally:
    sys.stdout = _stdout
saved = read_cfg()
check(saved['proxy'] == 'http://u9@h:9', 'proxy set 存的是脱敏 URL')
check(S.decrypt(saved['proxy_auth']['u9']) == 'p/w', '含 / 的密码完整入库')
check('p/w' not in open(cfg_path(), encoding='utf-8').read(), '含 / 的密码不落盘')

print('\n=== 16. config set proxy 不覆盖刚存的密文 ===')
# store_password 写的是文件, 而 handle 里的 cfg 是旧快照; 不合并回去的话
# save_config 会用空的 proxy_auth 把刚写的密文盖掉 —— 命令成功但密码没了
from webtool.cli import config as CFG      # noqa: E402
with open(cfg_path(), 'w', encoding='utf-8') as f:
    json.dump({'proxy': None}, f)
out = io.StringIO()
sys.stdout = out
try:
    ok, v = CFG._validate('proxy', 'http://u8:p/w@h:8')
finally:
    sys.stdout = _stdout
check(ok and v == 'http://u8@h:8', f'_validate 返回脱敏 URL (实际 {v})')
check(S.decrypt(read_cfg()['proxy_auth']['u8']) == 'p/w', 'validate 已写密文')
stale = load_cfg_snapshot = json.load(open(cfg_path(), encoding='utf-8'))
stale['proxy'] = v                       # 模拟"旧快照 + 新值"
stale['proxy_auth'] = {}                 # 旧快照里的空 proxy_auth
from webtool.net import proxy as PX2      # noqa: E402
try:
    merged = PX2.load_config().get('proxy_auth') or {}
finally:
    pass
check('u8' in merged, '重新 load_config 能读回密文 (save_config 前需合并)')

print('\n=== 17. setpass 的三条密码来源 ===')
# 交互输入(TTY) 是安全默认路径, 管道是 Agent/脚本路径, 位置参数最方便但会
# 留在 shell history 里。三条都要能用 —— 之前 TTY 分支写反了 (真终端反而
# 只打 usage 拒绝), 导致交互使用被迫把密码写在命令行上。


_RealStdin = sys.stdin


def setpass_with(tty, argv_stdin='', password=None):
    """跑一次 proxy setpass, 返回 (rc, getpass 的提示语或 None)

    位置参数顺序按真实调用 `webtool proxy setpass <用户名> [<密码>]`:
    用户名落在 value 上, 密码落在 user 上 (handle 内部会换序)。
    """
    fed = []
    import getpass
    real_getpass = getpass.getpass

    class _FakeIn:
        def isatty(self):
            return tty

        def readline(self):
            return argv_stdin

    getpass.getpass = lambda prompt='': (fed.append(prompt) or 'tty-pw')
    sys.stdin = _FakeIn()
    out = io.StringIO()
    sys.stdout = out
    try:
        rc = PX.handle(types.SimpleNamespace(
            action='setpass', value='sess', user=password, act=None), {})
    finally:
        sys.stdout = _stdout
        sys.stdin = _RealStdin
        getpass.getpass = real_getpass
    return rc, (fed[0] if fed else None)


rc, prompt = setpass_with(tty=True)
check(rc == 0, f'TTY 下交互输入可用 (rc={rc})')
check(prompt and 'sess' in prompt, f'提示里点名是哪个用户 (实际 {prompt!r})')
check(S.decrypt(read_cfg()['proxy_auth']['sess']) == 'tty-pw',
      '交互输入的密码已加密入库')

S.drop_password('sess')
rc, prompt = setpass_with(tty=False, argv_stdin='pipe-pw\n')
check(rc == 0 and prompt is None, '管道路径读 stdin, 不走 getpass')
check(S.decrypt(read_cfg()['proxy_auth']['sess']) == 'pipe-pw',
      '管道密码已入库 (换行已去掉)')

S.drop_password('sess')
rc, _ = setpass_with(tty=False, password='arg-pw')
check(rc == 0, '位置参数路径仍可用 (脚本友好)')
check(S.decrypt(read_cfg()['proxy_auth']['sess']) == 'arg-pw',
      '位置参数密码已入库')

print('\n=== 18. redact 对特殊字符密码不得泄漏 ===')
# 老实现用"`:` 与 `@` 之间不能含 `/`"来排除路径里的 @, 结果把密码含 `/`
# 的 URL 整个放过 —— 密码原样打进 proxy get / proxy test 的报错。
# 现在改成从**最后一个 @** 倒推 + 校验其后是 host 形状。
LEAKY = [
    ('http://bob:secret@1.2.3.4:8080', '普通'),
    ('http://bob:p/w@1.2.3.4:8080', '密码含 /'),
    ('http://bob:p@ss@1.2.3.4:8080', '密码含 @'),
    ('http://bob:p:w@1.2.3.4:8080', '密码含 :'),
    ('socks5://bob:p/w/r@1.2.3.4:1080', 'socks5 密码含 /'),
    ('http://bob:密码@1.2.3.4:8080', '中文密码'),
    ('http://bob:p/w@h:1/x?y=z@1.2.3.4:9/p', '含路径与查询'),
    ('http://u:s3cr3t@[::1]:8080', 'IPv6 主机'),
    ('http://bob:p/w@1.2.3.4', '无端口'),
]
for url, desc in LEAKY:
    out = S.redact(url)
    pwd = url.split('://', 1)[1].split(':', 1)[1].rsplit('@', 1)[0]
    check('***' in out and pwd not in out,
          f'{desc}: 密码不出现明文 (实际 {out})')

print('\n=== 19. redact 不得误伤正常文本 ===')
for txt, desc in [('https://a.com/x@y', '路径里的 @'),
                  ('mailto:a@b.com', 'mailto'),
                  ('/data/x@y/z', '文件系统路径'),
                  ('plain text', '普通文本'),
                  ('http://1.2.3.4:8080', '无凭据'),
                  ('http://user@1.2.3.4:8080', '只有用户名'),
                  ('http://host/path@x', '@ 在路径'),
                  ('见 issue #42@github', 'issue 引用'),
                  ('a@b@c', '裸文本多个 @')]:
    check(S.redact(txt) == txt, f'{desc} 原样保留 (实际 {S.redact(txt)!r})')

print()
print(f'{len(fails)} FAILED')
sys.exit(1 if fails else 0)