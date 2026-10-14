"""凭据保险库: 代理账号密码的加密存储与脱敏显示

## 为什么需要

代理 URL 形如 `http://user:pass@host:port`, 直接存进 `config.json` 有三个
问题: 明文落盘 (谁拿到这个 json 就拿到账号)、版本管理/日志/报错里外泄、
以及 `webtool proxy get` 直接把密码打在屏幕上。原代码里 rank/zen 的错误串
还会拼进完整代理 URL, 密码会进到 CLI 输出与用户贴的 issue 里。

## 存法

配置文件里**不再出现密码**, 改成引用保险库里的条目:

```jsonc
{
  "proxy": "http://default-user@127.0.0.1:2080",     // 用户名可留明文 (非秘密)
  "proxy_auth": {"default-user": "enc:v1:..."}        // 密码密文, 引用键=用户名
}
```

出网前由 `resolve_auth()` 把密文换回明文拼进 URL —— 明文只在内存里存在,
不落盘、不进日志。`enc:v1:` 前缀是版本标记, 将来换算法不影响老配置。

## 加密

Fernet (AES-128-CBC + HMAC-SHA256, 带时间戳与完整性校验)。密钥来自
`~/.webtool/secret.key`, 首次使用自动生成 (0400 权限), 也可用
`WEBTOOL_SECRET_KEY` 环境变量覆盖 (CI / 容器场景, 密钥不进文件)。

**注意**: 这挡的是"配置/日志意外泄漏"与"同机其他用户随手一读", 不是防
root。拿不到密钥 = 密文永久解不开, 这是有意的: 宁可配置失效也不能悄悄
降级成明文。

## 依赖

cryptography 为软依赖: 没装时本模块**只保留脱敏与引用解析**, `set` 命令
明确报错要求装包 —— 不做 base64 之类的假加密 (那等于没加密)。
"""
import os
import stat
from pathlib import Path

USER_DIR = Path(os.environ.get('WEBTOOL_DIR', '~/.webtool')).expanduser()
KEY_PATH = USER_DIR / 'secret.key'
ENV_KEY = 'WEBTOOL_SECRET_KEY'
PREFIX = 'enc:v1:'          # 版本标记: 换算法时靠它区分老密文


class SecretError(RuntimeError):
    """保险库相关错误 (无密钥 / 解不开 / 依赖缺失)"""


def have_crypto():
    try:
        __import__('cryptography.fernet')
        return True
    except ImportError:
        return False


def _f():
    from cryptography.fernet import Fernet
    return Fernet


def load_key(create=True):
    """取主密钥。优先环境变量, 其次密钥文件, 都没有就生成一个 (0400)。"""
    env = os.environ.get(ENV_KEY)
    if env:
        return env.strip().encode() if isinstance(env, str) else env
    if KEY_PATH.exists():
        data = KEY_PATH.read_bytes().strip()
        if not data:
            raise SecretError(
                f'密钥文件为空: {KEY_PATH}\n'
                f'处理: 删除该文件重新生成, 或设 {ENV_KEY} 环境变量')
        return data
    if not create:
        raise SecretError(
            f'没有主密钥: {KEY_PATH} 不存在\n'
            f'处理: 设 {ENV_KEY} 环境变量, 或让首次 set 自动生成')
    from cryptography.fernet import Fernet
    USER_DIR.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    KEY_PATH.write_bytes(key)
    try:
        os.chmod(KEY_PATH, stat.S_IRUSR | stat.S_IWUSR)   # 0400
    except OSError:
        pass                                        # 某些文件系统不支持 chmod
    return key


def encrypt(plaintext):
    """明文 → 'enc:v1:<token>'。没装 cryptography 直接报错 (不做假加密)"""
    if not isinstance(plaintext, str):
        plaintext = str(plaintext)
    if plaintext.startswith(PREFIX):
        return plaintext                       # 幂等: 别把密文再加密一遍
    if not have_crypto():
        raise SecretError(
            '加密需要 cryptography: apk add py3-cryptography 或 pip install cryptography')
    from cryptography.fernet import Fernet
    token = Fernet(load_key()).encrypt(plaintext.encode())
    return PREFIX + token.decode()


def decrypt(blob):
    """'enc:v1:<token>' → 明文。非本模块的密文 (别的工具/版本) 原样返回。

    解不开一律抛 SecretError: cryptography 的 InvalidToken 属于实现细节,
    让它漏出去的话, 上层 (CLI / 路由) 就得为每个后端各写一次异常捕获。
    """
    if not isinstance(blob, str) or not blob.startswith(PREFIX):
        return blob                            # 不是我们的密文: 当明文用
    if not have_crypto():
        raise SecretError('解密需要 cryptography: apk add py3-cryptography')
    from cryptography.fernet import Fernet
    from cryptography.fernet import InvalidToken
    try:
        return Fernet(load_key()).decrypt(
            blob[len(PREFIX):].encode()).decode()
    except InvalidToken as e:
        raise SecretError(
            f'密文解不开 (密钥不匹配或密文已损坏)\n'
            f'处理: 密钥在 {ENV_KEY} 环境变量或 {KEY_PATH}; '
            f'若换过密钥, 重新执行 webtool proxy setpass 写入密文') from e
    except UnicodeDecodeError as e:
        raise SecretError('密文解出的不是合法 UTF-8 文本, 已损坏') from e


def is_encrypted(blob):
    return isinstance(blob, str) and blob.startswith(PREFIX)


def redact(text, keep_tail=0):
    """把 URL / 任意串里的 `user:pass@` 脱敏成 `user:***@`。

    这是**日志与报错**的最后一层保险: 即便调用方不小心把完整代理 URL 拼进
    错误信息, 出口处也会被抹掉密码。keep_tail>0 时保留密码尾部若干字符,
    便于区分"是不是同一个密码", 但默认 0 (完全不露)。

    ## 为什么从**最后一个** `@` 倒推

    凭据段识别只有这一个可靠办法: 代理 URL 的形状是
    `scheme://[user[:pass]@]host[:port][/path]`, host 永远在最后。所以:
      - 用**最后一个** `@` 当 userinfo 与 host 的分界 (密码里含 `@` 不会误切)
      - `@` 之后必须是 `host[:port][/path]` 形状, 否则那不是凭据分隔符
        —— 这一条替掉了老代码的"`:` 与 `@` 之间不能含 `/`"检查, 后者会把
        密码含 `/` 的 URL (`http://u:p/w@h:2080`, 并不罕见) 整个放过去,
        密码原样打进日志。收紧成"@ 之后像 host"既能识别这类密码, 又不会把
        `https://a.com/x@y` 这种路径里的 @ 误判成凭据。
    """
    if not text:
        return text
    s = str(text)
    scheme_end = s.find('://')
    if scheme_end < 0:
        return s                              # 没有 scheme: 不是代理 URL 形状
    at = s.rfind('@')                          # 最后一个 @ (密码里含 @ 也安全)
    if at < scheme_end + 3:
        return s                              # @ 落在 scheme 里, 不是凭据
    tail_after = s[at + 1:]
    # @ 之后必须是 host[:port][/...] —— host 至少一个字符, 且不能以 : 或 / 开头
    if not tail_after or tail_after[0] in ':/':
        return s
    host = tail_after.split('/', 1)[0]
    if not host or host.startswith(':'):
        return s
    colon = s.find(':', scheme_end + 3)
    if colon < 0 or colon > at:
        return s                              # @ 前无冒号 → 只有用户名, 没密码
    pwd = s[colon + 1:at]
    if not pwd:
        return s
    if keep_tail and len(pwd) > keep_tail:
        pwd = '***' + pwd[-keep_tail:]
    else:
        pwd = '***'
    return s[:colon + 1] + pwd + s[at:]


def resolve_auth(url):
    """把 URL 里的用户名与保险库中的密码配对, 返回可直接出网的完整 URL。

    三种情形:
      user:pass@host   → 明文密码, 原样返回 (调用方的老用法)
      user@host + 库里有 → 查库补上密码
      user@host + 库里没有 → 报错 (凭据缺失要立刻说, 不能静默用空密码去连,
                              那会让代理返回 407 而错误信息完全指不到原因)
    """
    if not url or '@' not in url or '://' not in url:
        return url
    scheme, rest = url.split('://', 1)
    userinfo, _, hostpart = rest.rpartition('@')
    if not userinfo:
        return url
    if ':' in userinfo:
        return url                                # 已带密码: 明文用法, 不动
    store = _load_store()
    if userinfo in store:
        return f'{scheme}://{userinfo}:{store[userinfo]}@{hostpart}'
    raise SecretError(
        f'代理 {userinfo}@{hostpart.split("/")[0].split(":")[0]} 需要密码, '
        f'但保险库里没有 "{userinfo}"\n'
        f'处理: webtool proxy setpass {userinfo} "<密码>" '
        f'(或把密码直接写进 URL, 但那样会明文落盘)')


def _load_store():
    """读 config.json 里的 proxy_auth 密文表并解密"""
    import json
    cfg_path = USER_DIR / 'config.json'
    if not cfg_path.exists():
        return {}
    try:
        cfg = json.loads(cfg_path.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        return {}
    raw = cfg.get('proxy_auth') or {}
    if not isinstance(raw, dict):
        return {}
    out = {}
    for user, blob in raw.items():
        try:
            out[user] = decrypt(blob)
        except Exception:
            # 解不开 (密钥换了/密文损坏) 不能静默用空密码, 让 resolve_auth 报缺失
            continue
    return out


def store_password(user, password):
    """把密码写进 config.json 的 proxy_auth (密文)。返回是否新建。"""
    import json
    blob = encrypt(password)
    cfg_path = USER_DIR / 'config.json'
    cfg = {}
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding='utf-8'))
        except (ValueError, OSError):
            cfg = {}
    auth = cfg.get('proxy_auth') or {}
    created = user not in auth
    auth[user] = blob
    cfg['proxy_auth'] = auth
    USER_DIR.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                        encoding='utf-8')
    try:
        os.chmod(cfg_path, stat.S_IRUSR | stat.S_IWUSR)   # 配置文件含密文
    except OSError:
        pass
    return created


def drop_password(user):
    """从保险库删掉某个用户的密码。返回是否确实删掉了"""
    import json
    cfg_path = USER_DIR / 'config.json'
    if not cfg_path.exists():
        return False
    try:
        cfg = json.loads(cfg_path.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        return False
    auth = cfg.get('proxy_auth') or {}
    if user not in auth:
        return False
    auth.pop(user, None)
    cfg['proxy_auth'] = auth
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                        encoding='utf-8')
    return True


def status():
    """给 CLI 看的状态摘要 (不含任何明文密码)"""
    import json
    cfg_path = USER_DIR / 'config.json'
    users = []
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding='utf-8'))
            users = list((cfg.get('proxy_auth') or {}).keys())
        except (ValueError, OSError):
            users = []
    key_src = f'${ENV_KEY}' if os.environ.get(ENV_KEY) else str(KEY_PATH)
    return {
        'crypto': 'fernet (AES-128-CBC+HMAC)' if have_crypto() else '未安装 cryptography',
        'key_file': key_src,
        'key_exists': bool(os.environ.get(ENV_KEY) or KEY_PATH.exists()),
        'users': users,
        'note': '配置文件只存密文; 出网时才在内存解密',
    }