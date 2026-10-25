"""zen --agent 的工作空间: 一条路径边界 + 一份可选的项目说明

工作空间是 agent 能碰的**文件系统范围**: 文件类工具 (read/glob/grep) 只在它里面
解析路径, 越界 (含 symlink 绕出去) 一律拒绝并把理由回给模型, 让它换条路而不是
让客户端崩掉。web 类工具不受这条边界约束 —— 它们出网, 不碰本地文件。

`AGENTS.md` (若存在) 的内容并进 system prompt: 工作空间要成为"上下文"而不只是
一条沙箱线, 否则模型不知道这个目录是干什么的, 只能靠一次次 grep 摸。
"""

from pathlib import Path

from webtool.core.logging import get_logger

logger = get_logger(__name__)

AGENTS_FILES = ('AGENTS.md', 'AGENT.md', '.webtool/AGENTS.md')
MAX_AGENTS_CHARS = 4000


class Workspace:
    """一条路径边界 (root 已 resolve, symlink 已展开)"""

    def __init__(self, root):
        self.root = Path(root).resolve()

    def __repr__(self):
        return 'Workspace(%s)' % self.root

    @classmethod
    def resolve(cls, spec=None):
        """`--workspace` 取值 → Workspace; 不给就是当前目录

        目录不存在/ 不是目录 → UsageError (退出 2): 工作空间落错了要当场说,
        静默退回 cwd 会让模型在错误的目录里读写, 而用户以为限制了范围。
        """
        from webtool.core.errors import UsageError
        raw = (spec or '').strip() or '.'
        p = Path(raw).expanduser()
        if not p.exists():
            raise UsageError('工作空间不存在: %s' % p)
        if not p.is_dir():
            raise UsageError('工作空间不是目录: %s' % p)
        return cls(p)

    def inside(self, path):
        """这个路径能不能碰 → 解析后的绝对路径; 不能碰返回 None

        先 expanduser 再 resolve: resolve 会把 symlink 展开, 所以指向外部的
        软链同样落在界外 —— 只比字面路径前缀的话, 一个软链就足以读遍整机。
        """
        p = Path(str(path)).expanduser()
        p = (self.root / p) if not p.is_absolute() else p
        try:
            real = p.resolve()
        except OSError:                       # 死软链/权限异常: 当作界外
            return None
        try:
            real.relative_to(self.root)
        except ValueError:
            return None
        return real

    def check(self, path):
        """同 inside, 但越界时抛 UsageError (带可执行的下一步)"""
        from webtool.core.errors import UsageError
        real = self.inside(path)
        if real is None:
            raise UsageError('路径在工作空间外: %s (只能碰 %s 里面的东西)'
                             % (path, self.root))
        return real

    def agents_md(self):
        """工作空间里的项目说明 (AGENTS.md), 没有就是空串"""
        for name in AGENTS_FILES:
            p = self.root / name
            try:
                if p.is_file():
                    txt = p.read_text(encoding='utf-8', errors='replace')
                    return txt[:MAX_AGENTS_CHARS]
            except OSError as e:
                logger.debug('workspace | 读 %s 失败: %s', p, e)
        return ''