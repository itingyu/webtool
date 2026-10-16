"""proxy 子命令: 代理凭据保险库 (setpass / delpass / passwd)"""
import sys

from webtool.core.secrets_store import (drop_password, redact,
                                        status as secret_status,
                                        store_password)
from webtool.net.proxy.store import CONFIG_PATH


def _ask_password(ref):
    """终端交互读密码 (getpass, 不回显); 无 TTY 时读 stdin 一行 (管道场景)。

    返回 None = 用户中断/给了空行。必须先判 isatty 再决定走哪条: getpass
    在无 TTY 时会静默降级成读 stdin 并往 stderr 打警告, 两条路不能混。"""
    if sys.stdin.isatty():
        import getpass
        try:
            return getpass.getpass(f'输入 {ref} 的代理密码 (不回显): ')
        except (EOFError, KeyboardInterrupt):
            print(file=sys.stderr)
            return None
        except Exception as e:
            # 没有 /dev/tty (某些容器/重定向环境): 退回读 stdin, 别直接崩
            print(f'无法交互输入 ({e}); 请改用管道: '
                  f'echo "<密码>" | webtool proxy setpass {ref}',
                  file=sys.stderr)
            return None
    return sys.stdin.readline().rstrip('\n') or None


def _vault_has(ref):
    from webtool.core.secrets_store import _load_store
    return ref in _load_store()


def _setpass(args, cfg):
    """把账号密码加密存进保险库, 配置里只留用户名

    密码来源按优先级:
      1. 终端交互 (getpass, **不回显**) —— 真终端下的默认路径 (省略密码参数)
      2. stdin 管道 —— 供 Agent / 脚本 `echo pw | webtool proxy setpass <用户>`
      3. 位置参数 `<密码>` —— **会留在 shell history 和 ps 输出里**, 只在
         明知无泄漏环境 (CI 临时容器) 时用
    """
    user = args.user
    if not user:
        print('usage: webtool proxy setpass <用户名|用户名@主机> [<密码>]', file=sys.stderr)
        print('  省略密码则终端交互输入 (不回显); 也可从 stdin 管道读',
              file=sys.stderr)
        return 2
    pwd = args.value
    if pwd is None:
        pwd = _ask_password(user)
        if pwd is None:
            return 130 if sys.stdin.isatty() else 2
    if not pwd:
        print('密码为空', file=sys.stderr)
        return 2
    try:
        created = store_password(user, pwd)
    except Exception as e:
        print(f'存储失败: {redact(str(e))}', file=sys.stderr)
        return 2
    print(f'{"已新增" if created else "已更新"} {user} 的密码 '
          f'(密文存于 {CONFIG_PATH} 的 proxy_auth)\n'
          f'用法: webtool proxy set http://{user}@host:port')
    return 0


def _delpass(args, cfg):
    if not args.user:
        print('usage: webtool proxy delpass <用户名>', file=sys.stderr)
        return 2
    if not drop_password(args.user):
        print(f'保险库里没有 {args.user}', file=sys.stderr)
        return 2
    print(f'已删除 {args.user} 的密码')
    return 0


def _passwd(args, cfg):
    for k, v in secret_status().items():
        print(f'  {k:12} {v}')
    return 0
