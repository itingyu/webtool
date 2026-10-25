"""带"默认命令"的 Typer 组: 第一个词不是子命令时, 交给默认命令

`webtool zen "问题"` / `webtool diff <url> <url>` 这类"主用法没有子命令词"的
场景共用这一份实现, 别再每个模块抄一遍。
"""
from typer.core import TyperGroup


class DefaultGroup(TyperGroup):
    """子类只需设 default_cmd"""

    default_cmd = None

    def parse_args(self, ctx, args):
        # 组会先解析自己的选项, 未知选项在那一步就报错; 所以选项开头时
        # 提前补上默认命令词, 让默认命令去接这些选项
        names = self.list_commands(ctx)
        if (self.default_cmd in names and args
                and args[0].startswith('-') and args[0] != '-'
                and args[0] not in ('-h', '--help')
                and args[0] not in names):
            args = [self.default_cmd] + list(args)
        super().parse_args(ctx, args)

    def resolve_command(self, ctx, args):
        # 空参数也交给默认命令 (zen 无参=空 prompt, diff 无参=给用法);
        # 选项开头也交 (webtool feed radar --cat finance), 但 --help 留给本组
        names = self.list_commands(ctx)
        if self.default_cmd in names:
            head = args[0] if args else None
            if head is None or head not in names:
                if head is None or not head.startswith('-') or head not in (
                        '-h', '--help'):
                    return (self.default_cmd,
                            self.get_command(ctx, self.default_cmd), args)
        return super().resolve_command(ctx, args)


def make_group(default_cmd, help_text):
    """省掉每个调用点重复的 Typer(...) 参数"""
    import typer

    class _G(DefaultGroup):
        pass

    _G.default_cmd = default_cmd
    return typer.Typer(
        cls=_G, add_completion=False, no_args_is_help=False,
        rich_markup_mode=None, pretty_exceptions_enable=False, help=help_text,
        context_settings={'help_option_names': ['-h', '--help']})
