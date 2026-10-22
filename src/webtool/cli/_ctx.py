"""cli 命令共享 plumbing: 输出格式归一 / --think 归一 / 数据命令执行器 / 全局 _CTX

各命令按域拆进 cli/commands/*, 共享部分都从这里取。本模块**不 import app**,
避免与 app.py 形成循环 (app.py 在底部 import 各命令模块完成注册)。
"""
import io
import sys
from contextlib import redirect_stdout

import typer

# typer 0.26 起 vendor 了 click: 异常类在 typer._click.exceptions, 与顶层 click 不同源
try:
    from typer._click.exceptions import UsageError as _UsageError
except ImportError:                        # typer <= 0.25: 异常来自顶层 click
    from click.exceptions import UsageError as _UsageError

from webtool.core.logging import get_logger
from webtool.net import proxy as _proxy
from webtool.render.output import FORMATS, emit

logger = get_logger(__name__)


__all__ = ['Fmt', 'Output', 'NoProxy', 'NoCache', '_norm_fmt', '_THINK_OFF',
           'DEFAULT_THINK', '_norm_think', '_run', '_CTX', '_do', '_entry_fn',
           '_argv_format']

Fmt = typer.Option(None, '-f', '--format',
                   help='输出格式 json/text/markdown (大小写不敏感; md=markdown, txt=text)')

Output = typer.Option(None, '-o', '--output',
                      help='输出到文件 (按 -f 补扩展名; 目录则自动命名; -o - 强制 stdout)')

NoProxy = typer.Option(False, '--no-proxy', help='本次不走代理(覆盖配置)')

NoCache = typer.Option(False, '--no-cache', help='跳过缓存')

def _norm_fmt(v, default):
    """归一化输出格式; 非法值直接报错退出, 不静默回落 text。

    静默回落会让 Agent 拿到人类可读文本却毫无提示, 解析阶段才炸, 难排查。
    """
    if not v:
        return default
    x = v.strip().lower()
    x = {'md': 'markdown', 'txt': 'text'}.get(x, x)
    if x not in FORMATS:
        raise _UsageError(f'未知输出格式 {v!r}; 可用: {", ".join(sorted(FORMATS))}'
                          f' (别名 md=markdown, txt=text)')
    return x

_THINK_OFF = ('off', 'none', 'no')

DEFAULT_THINK = 'medium'

def _norm_think(v):
    """归一化 --think 取值 → 上游 reasoning_effort

    **不预判合法值**: 可选值随模型而异 (有的只认 low/medium/high, 有的还收
    none/minimal/xhigh, 有的压根不吃这个字段), 上游自己的清单才是唯一权威 ——
    客户端写死一套只会把"其实能用"的值挡在门外。
    不填 → 默认 medium (随手要一个默认强度); 显式 off/none → 不带该字段。
    """
    if v is None:
        return DEFAULT_THINK
    x = v.strip()
    if not x or x.lower() in _THINK_OFF:
        return None
    return x

def _run(data_cmd, fn, fmt, output, no_cache, no_proxy, fmt_default='text'):
    """执行 do_* 并按数据命令约定处理输出; 返回 exit code

    data_cmd 非空 = 数据命令, 内部自己按 args.format 渲染, 这里只接住落盘;
    data_cmd 为空 = 管理命令, 内部 print 原样输出, 这里按 -f 转格式后再 emit。
    """
    cfg = _proxy.load_config()
    # 命令入口全景: 排查先确认"到底是哪个命令、参数解析成了什么、配置从哪来"
    # —— 参数被吃/配置没加载到, 后面所有日志都会看着莫名其妙
    # 命令名取 argv 里第一个非选项参数 —— 得跳过带值的全局选项的值
    # (--log-file /tmp/x.jsonl 的 /tmp/x.jsonl 不是命令名)
    _argv = sys.argv[1:]
    _cmd, _skip = '?', False
    for _a in _argv:
        if _skip:
            _skip = False
            continue
        if _a in ('--log-file', '--output', '-o'):
            _skip = True
            continue
        if not _a.startswith('-'):
            _cmd = _a
            break
    logger.debug('cli | 入口 cmd=%s fmt=%s out=%s no_cache=%s no_proxy=%s '
                 'cfg=%d 键 argv=%s', _cmd, fmt or '(默认)', output,
                 no_cache, no_proxy, len(cfg), ' '.join(_argv[:4]))
    gproxy = _CTX.get('proxy')
    if gproxy:
        cfg['proxy'] = gproxy
    args = _CTX['args']
    args.no_cache = no_cache or _CTX['no_cache']
    args.no_proxy = no_proxy
    # 输出格式默认值收口在这里: CLI 显式 -f > config.json 的 default_format >
    # 命令自带默认。default_format 曾经只有 search 读, 别的数据命令
    # (fetch/feed/hot/site/rank) 配了不生效 —— 同一份配置在不同入口不同结果。
    args.format = _norm_fmt(fmt, cfg.get('default_format') or fmt_default)
    args.output = output
    if data_cmd:
        buf = io.StringIO()
        # 人在终端看文本输出 → 透传, 保留流式观感; 否则纯缓冲 (管道/文件不掺半截)
        _real = getattr(sys, '__stdout__', None)
        tee = None
        if ((not output or output == '-') and args.format != 'json'
                and _real is not None and getattr(_real, 'isatty', lambda: False)()):
            tee = _Tee(buf, _real)
        with redirect_stdout(tee or buf):
            try:
                rc = fn(args, cfg)
            except ValueError as e:
                # 渲染层的用法错误不该甩 traceback
                raise _UsageError(str(e))
            except ImportError as e:
                # stock 是延迟导入 + requests 顶层 import, 少装依赖时表现是
                # 一串 importlib 栈, 而其余命令完全正常, 很难联想到缺包。
                from webtool.core import deps
                raise _UsageError(deps.install_hint(e.name or ''))
        out = buf.getvalue()
        if tee is not None:
            # 内容已经实时打到终端了, 不再 emit 一遍 (否则屏幕上看两遍)
            return rc if rc not in (0, None) else 0
        if rc not in (0, None):
            # 命令已经跑出报告了, 退出码只是"有没有可用结果"的判据 (如 zen
            # --check 全挂) —— 别因为退出码非零就把人要看的报告丢掉。
            if out.strip():
                emit(out, args.format, output)
            return rc
        return emit(out, args.format, output)
    # 管理命令: 未指定 -f 时按 txt 渲染 (与数据命令默认一致)。
    # 但把 args.format 交回 None, 让 config list 这类内部会按 format 分支的
    # 命令走它自己的人类可读默认, 而不是看到 'text' 就交结构化数据。
    if not fmt and not output:
        args.format = None
        out_fmt = 'text'
    else:
        out_fmt = args.format
    buf = io.StringIO()
    with redirect_stdout(buf):
        try:
            rc = fn(args, cfg)
        except ImportError as e:
            # stock 是延迟导入 + requests 顶层 import, 少装依赖时表现是一串
            # importlib 栈, 而 search/fetch 等其余命令完全正常, 很难联想到
            # 是缺包。两条分支都要接住, 否则管理命令分支 (data_cmd 为空)
            # 会绕过这里的转换。
            from webtool.core import deps
            raise _UsageError(deps.install_hint(e.name or ''))
    from webtool.cli.adminfmt import adapt
    if rc not in (0, None):
        # 与数据命令同理: 报告已经打出来了, 退出码只是"有没有可用结果"的判据
        # (如 upgrade --check 有新版就退 1), 别把报告一起吞掉。
        out = buf.getvalue()
        if out.strip():
            emit(adapt(out, out_fmt), out_fmt, output)
        return rc
    return emit(adapt(buf.getvalue(), out_fmt), out_fmt, output)

_CTX = {}

def _do(name):
    def fn(args, cfg):
        import webtool.pipeline.fetch as fetch
        return getattr(fetch, f'do_{name}')(args, cfg)
    return fn

def _entry_fn(name):
    def fn(args, cfg):
        import importlib
        mod = {'zen': ('cli.zen', 'do_zen'), 'fetch': ('pipeline.fetch', 'do_fetch'),
               'site': ('cli.sitesearch', 'do_site'),
               'rank': ('pipeline.rank', 'do_rank'),
               'ask': ('cli.ask', 'do_ask'),
               'snapshot': ('cli.snapshot', 'do_snapshot'),
               'diff': ('cli.snapshot', 'do_diff'),
               'compare': ('pipeline.compare', 'do_compare'),
               'watch': ('cli.watch', 'do_watch'),
               'crawl': ('cli.crawl', 'do_crawl'),
               'stock': ('stock.command', 'do_stock'),
               'feed': ('feeds.command', 'do_feed')}[name]
        m = importlib.import_module('webtool.' + mod[0])
        return getattr(m, mod[1])(args, cfg)
    return fn

def _argv_format(argv):
    """预扫阶段 click 还没接管, 自己从原始 argv 取 -f/--format 的值"""
    for i, a in enumerate(argv):
        if a in ('-f', '--format') and i + 1 < len(argv):
            return argv[i + 1].strip().lower()
        for pre in ('--format=', '-f='):
            if a.startswith(pre):
                return a[len(pre):].strip().lower()
    return ''
class _Tee:
    """边写缓冲边写真终端: 让"人在终端"时能看到流式输出。

    数据命令的输出本来要整段捕获 (供 -f/-o 落盘), 但那样 zen 这种流式命令也
    被憋到结束才一次性吐。这里只在"真 stdout 是终端 + 文本格式 + 不落盘"时
    把输出同时透到终端, 其余一律纯缓冲 —— 管道/文件里绝不掺半截内容。
    isatty() 如实转达真终端, 于是 zen 内部判断"人在看"的那套逻辑照常成立。
    """

    def __init__(self, buf, live):
        object.__setattr__(self, '_buf', buf)
        object.__setattr__(self, '_live', live)

    def write(self, s):
        self._buf.write(s)
        try:
            self._live.write(s)
            self._live.flush()
        except Exception:
            pass
        return len(s)

    def flush(self):
        try:
            self._live.flush()
        except Exception:
            pass

    def isatty(self):
        try:
            return bool(self._live.isatty())
        except Exception:
            return False

    def __getattr__(self, name):          # encoding / fileno 等交给真终端
        return getattr(object.__getattribute__(self, '_live'), name)


