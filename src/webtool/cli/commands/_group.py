"""带"默认命令"的 Typer 组: 第一个词不是子命令时, 交给默认命令

`webtool zen "问题"` / `webtool diff <url> <url>` 这类"主用法没有子命令词"的
场景共用这一份实现, 别再每个模块抄一遍。
"""
from typer.core import TyperGroup


class DefaultGroup(TyperGroup):
    """子类只需设 default_cmd"""

    default_cmd = None

    def resolve_command(self, ctx, args):
        # 空参数也交给默认命令 (zen 无参=空 prompt, diff 无参=给用法)
        names = self.list_commands(ctx)
        if self.default_cmd in names and (
                not args or (args[0] not in names and not args[0].startswith('-'))):
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
        rich_markup_mode=None, help=help_text,
        context_settings={'help_option_names': ['-h', '--help']})
