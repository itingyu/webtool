"""zen: 对话 / agent / 模型管理 / 会话 / 调试, 按用途拆子命令

`webtool zen "问题"` 保持原样 —— 第一个词不是子命令时交给 chat
(cls=_DefaultGroup 的默认命令)。
"""
import typer
from typer.core import TyperGroup

from webtool.cli._ctx import (
    Fmt, NoCache, NoProxy, Output, _CTX, _entry_fn, _norm_think, _run,
)
from webtool.cli.app import app


class _DefaultGroup(TyperGroup):
    """第一个词不是已知子命令 (也不是选项) 时, 当作默认命令的参数"""
    default_cmd = 'chat'

    def resolve_command(self, ctx, args):
        # 空参数也交给默认命令 (feed 无参=列清单, zen 无参=空 prompt)。
        # 用 get_commands(ctx): TyperGroup.commands 依赖 ctx, 无参时是空的。
        names = self.list_commands(ctx)
        if self.default_cmd in names and (
                not args or (args[0] not in names and not args[0].startswith('-'))):
            return (self.default_cmd,
                    self.get_command(ctx, self.default_cmd), args)
        return super().resolve_command(ctx, args)


zen_app = typer.Typer(
    cls=_DefaultGroup, add_completion=False, no_args_is_help=False,
    rich_markup_mode=None,
    help='OpenCode Zen 对话 (公开模式, 无需 key): zen "问题" | zen models | zen agent',
    context_settings={'help_option_names': ['-h', '--help']})


def _build(fmt, output, no_proxy, no_cache, **kw):
    """按 zenproto 默认值补齐 args, 再覆盖子命令给的值"""
    from webtool.cli import zenproto as _zp
    d = _zp.defaults()
    a = _CTX['args']
    a.prompt = kw.get('prompt') or ''
    a.model = kw.get('model') or d['model']
    a.model_explicit = bool(kw.get('model'))
    a.system = kw['system'] if kw.get('system') is not None else d['system']
    a.tool_choice = kw.get('tool_choice') or d['tool_choice']
    a.tools = kw.get('tools') or d['tools']
    a.max_tokens = kw.get('max_tokens') or d['max_tokens']
    a.list_models = kw.get('list_models', False)
    a.list_free = kw.get('list_free', False)
    a.check = kw.get('check', False) or kw.get('check_all', False)
    a.check_all = kw.get('check_all', False)
    a.refresh = kw.get('refresh', False)
    a.dry_run = kw.get('dry_run', False)
    a.show = kw.get('show')
    a.show_body = a.show_text = False
    a.stream = d['live'] if kw.get('live') is None else kw['live']
    a.retries = kw.get('retries', 2)
    a.sticky = kw.get('sticky', True)
    a.agent = kw.get('agent', False)
    a.agent_tools = kw.get('agent_tools')
    a.agent_max_steps = max(1, kw.get('agent_max_steps', 20))
    a.agent_max_chars = max(200, kw.get('agent_max_chars', 8000))
    a.workspace = kw.get('workspace')
    a.session = kw.get('session')
    a.continue_session = kw.get('continue_session', False)
    a.sessions = kw.get('sessions', False)
    a.clear_session = kw.get('clear_session', False)
    a.limits = kw.get('limits', False)
    a.forget_limits = kw.get('forget_limits', False)
    a.reasoning = kw.get('reasoning', True)
    a.think = _norm_think(kw['think'] if kw.get('think') is not None
                          else d['reasoning_effort'])
    return _run('data', _entry_fn('zen'), fmt, output, no_cache, no_proxy)


@zen_app.command('chat')
def _chat(prompt: list[str] = typer.Argument(None, help='要问的问题'),
          model: str = typer.Option(None, '--model', help='模型 id (见 zen models)'),
          system: str = typer.Option(None, '--system', help='system prompt'),
          think: str = typer.Option(None, '--think', '--reasoning-effort',
                                    help='思考强度: off/low/medium/high (默认 medium)'),
          max_tokens: int = typer.Option(None, '--max-tokens', help='回复上限 token'),
          tools: str = typer.Option(None, '--tools', help='工具集: min(all 默认)/all/逗号清单'),
          live: bool = typer.Option(True, '--live/--no-live', '--stream/--no-stream',
                                    help='边收边打印 (默认开)'),
          reasoning: bool = typer.Option(True, '--reasoning/--no-reasoning',
                                         help='打印思考过程 (默认开)'),
          retries: int = typer.Option(2, '--retries', help='瞬时故障重试次数'),
          sticky: bool = typer.Option(True, '--sticky/--no-sticky', help='固定会话 id (默认开)'),
          fmt: str = Fmt, output: str = Output,
          no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """对话 (默认命令: webtool zen "问题" 等同 zen chat "问题")"""
    return _build(fmt, output, no_proxy, no_cache,
                  prompt=' '.join(prompt or []), model=model, system=system,
                  think=think, max_tokens=max_tokens, tools=tools, live=live,
                  reasoning=reasoning, retries=retries, sticky=sticky)


@zen_app.command('agent')
def _agent(prompt: list[str] = typer.Argument(None, help='要完成的任务'),
           model: str = typer.Option(None, '--model', help='模型 id'),
           system: str = typer.Option(None, '--system', help='system prompt'),
           tools: str = typer.Option(None, '--tools', help='可用工具, 逗号分隔 (默认 read,glob,grep,websearch,webfetch)'),
           max_steps: int = typer.Option(20, '--max-steps', help='最多几轮模型请求'),
           max_chars: int = typer.Option(8000, '--max-chars', help='单次工具输出回喂上限字数'),
           workspace: str = typer.Option(None, '-w', '--workspace', help='工作空间目录 (默认当前目录)'),
           session: str = typer.Option(None, '--session', help='命名会话; 同名再跑接着聊'),
           continue_session: bool = typer.Option(False, '--continue', help='接最近一条会话'),
           think: str = typer.Option(None, '--think', help='思考强度'),
           fmt: str = Fmt, output: str = Output,
           no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """多轮工具循环: 模型调工具 → 本地执行 → 回喂 → 再问, 直到给出答案"""
    return _build(fmt, output, no_proxy, no_cache,
                  prompt=' '.join(prompt or []), model=model, system=system,
                  think=think, tools=tools, agent=True, agent_tools=tools,
                  agent_max_steps=max_steps, agent_max_chars=max_chars,
                  workspace=workspace, session=session,
                  continue_session=continue_session)


@zen_app.command('models')
def _models(free: bool = typer.Option(False, '--free', help='只列免费层 id'),
            check: bool = typer.Option(False, '--check', help='真调一次验证可用性 (默认只验免费层)'),
            check_all: bool = typer.Option(False, '--check-all', help='连收费模型一起验 (慢, 易限流)'),
            refresh: bool = typer.Option(False, '--refresh', help='绕过 1h 清单缓存'),
            fmt: str = Fmt, output: str = Output,
            no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """列出可用模型"""
    return _build(fmt, output, no_proxy, no_cache, list_models=True,
                  list_free=free, check=check, check_all=check_all, refresh=refresh)


@zen_app.command('limits')
def _limits(forget: bool = typer.Option(False, '--forget', help='忘掉记住的上限'),
            model: str = typer.Option(None, '--model', help='只处理这一个模型'),
            fmt: str = Fmt, output: str = Output,
            no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """模型输出上限记录 (上游在 400 里报过的; 不联网)"""
    return _build(fmt, output, no_proxy, no_cache, limits=True,
                  forget_limits=forget, model=model)


@zen_app.command('sessions')
def _sessions(clear: str = typer.Option(None, '--clear', help='删掉指定会话 (不给名字则删最近一条)'),
              fmt: str = Fmt, output: str = Output,
              no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """列出/删除保存的会话 (不联网)"""
    if clear is None:
        return _build(fmt, output, no_proxy, no_cache, sessions=True)
    return _build(fmt, output, no_proxy, no_cache, clear_session=True,
                  session=clear)


@zen_app.command('debug')
def _debug(prompt: list[str] = typer.Argument(None, help='要预览的问题'),
           show: str = typer.Option(None, '--show', help='只看一段: request/headers/body/text'),
           model: str = typer.Option(None, '--model', help='模型 id'),
           system: str = typer.Option(None, '--system', help='system prompt'),
           max_tokens: int = typer.Option(None, '--max-tokens', help='回复上限 token'),
           think: str = typer.Option(None, '--think',
                                     help='思考档位: off/low/medium/high/xhigh'),
           tools: str = typer.Option(None, '--tools', help='工具集: min/all/逗号清单'),
           fmt: str = Fmt, output: str = Output,
           no_proxy: bool = NoProxy, no_cache: bool = NoCache):
    """打印将要发出的请求, 不联网"""
    return _build(fmt, output, no_proxy, no_cache,
                  prompt=' '.join(prompt or []), model=model, system=system,
                  max_tokens=max_tokens, think=think, tools=tools,
                  dry_run=True, show=show)


@zen_app.callback(invoke_without_command=True)
def _root(ctx: typer.Context):
    """无参 = 列可用模型 (等价 zen models)"""
    if ctx.invoked_subcommand is None:
        raise typer.Exit(_build(None, None, False, False, list_models=True))

app.add_typer(zen_app, name='zen')
