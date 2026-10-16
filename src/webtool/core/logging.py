"""分级彩色日志: 全命令 --debug / --log-file 的基础设施

约定 (docs/coding-standard.md §2.6):
- 打印给人看的用 print, 定位问题用的必须走 logger (`logging.getLogger(__name__)`)
- 日志一律到 **stderr** —— stdout 是数据通道 (管道/`-f json` 消费), 混进日志
  等于毁掉 `x | webtool ...` 范式
- 默认级别 WARNING: 不带 --debug 时行为与从前完全一致 (零日志输出);
  `--debug/-d` (可叠加) 放开各级别, 颜色分级 DEBUG 灰 / INFO 绿 / WARN 黄 / ERROR 红
- 非 tty 或 NO_COLOR 自动去色; 去色逻辑只碰本 handler 的格式, 不动全局

级别映射:
  -d×1         → DEBUG (本仓自己的日志)
  -d×2 及以上  → 连三方库 (urllib3/curl_cffi/hpack) 也放到 DEBUG, 排查传输层用
  也认 WEBTOOL_DEBUG / WEBTOOL_LOG_FILE 环境变量 (脚本/Agent 免加参数)
  --log-file P → 额外把 DEBUG 全量写进文件 (纯文本无颜色), 便于事后定位

handler 只装一次, 重复调用 (每命令的 callback 都会进来) 直接改级别/换文件即可。

输出格式 (终端, 无颜色时同样):
  `12:34:56.789 D [MainThread] netx.py:70 <消息>`
即 "时间(毫秒) 级别 线程 文件:行号", 消息体自带 `<模块> | 动作` 前缀。
文件 (.log) 额外带完整日期与 logger 名; .jsonl 每行一个事件 (含 thread/file)。
"""
import contextlib
import json
import logging
import os
import re
import sys
import time

# 排查要能在几百行里①按时间对齐 (含毫秒, 并发下不带毫秒分不清先后);
# ②按来源定位到"哪个文件哪一行" (光有 logger 名还得再去搜一遍);
# ③按线程分辨交错输出 (搜索是多线程抓引擎, 少了线程名两行日志就串成一件事)。
# 三样缺一样, 日志就只是"一段文本"。
# 终端省掉 logger 名 (消息本身已带 `<模块> |` 前缀) 换宽度; 文件另带全量信息。
_FMT = ('%(asctime)s.%(msecs)03d %(levelname).1s [%(threadName)s] '
        '%(filename)s:%(lineno)d %(message)s')
_DATEFMT = '%H:%M:%S'                    # 终端看当下, 日期看会话上下文即可
_FILE_FMT = ('%(asctime)s.%(msecs)03d %(levelname)-5s [%(threadName)s] '
             '%(filename)s:%(lineno)d %(name)s: %(message)s')
_FILE_DATEFMT = '%Y-%m-%d %H:%M:%S'      # 文件是事后翻的, 必须带日期

# 级别 → ANSI 色; 去色时由 _color 化整为零直接不拼
_COLOR = {'D': '\033[90m', 'I': '\033[32m', 'W': '\033[33m', 'E': '\033[31m'}
_RESET = '\033[0m'

# 三方库噪声源: -d×2 时也放开, 平时按 WARNING 压着
_THIRD_PARTY = ('urllib3', 'curl_cffi', 'requests', 'hpack', 'charset_normalizer')


class _ColorFmt(logging.Formatter):
    def __init__(self):
        super().__init__(fmt=_FMT, datefmt=_DATEFMT)
        self._color = (sys.stderr.isatty() if hasattr(sys.stderr, 'isatty')
                       else False) and not os.environ.get('NO_COLOR')

    def format(self, rec):
        msg = super().format(rec)
        if self._color:
            c = _COLOR.get(rec.levelname[0])
            if c:
                return c + msg + _RESET
        return msg


_h = None
_debug = 0          # setup() 记下的 debug 档位, 供 is_debug() 查询
_fh = None
_fh_path = None


def setup(debug=0, log_file=None):
    """按 --debug 叠加次数 + --log-file 装配根 ('webtool') logger; 幂等

    debug>=1 → DEBUG 全放开; >=2 → 三方库也 DEBUG; 0 → WARNING (等效于关闭:
    正常路径没有 WARNING 以上日志, 出了问题该吵还是会吵)。
    log_file 给了就额外挂一个 DEBUG 全量的文件 handler (纯文本, 无颜色)。
    """
    global _h, _fh, _fh_path, _debug
    root = logging.getLogger('webtool')
    _debug = debug
    level = logging.DEBUG if debug else logging.WARNING
    path = log_file or os.environ.get('WEBTOOL_LOG_FILE') or ''
    # 有文件 handler 时, logger 本体放到 DEBUG: 文件才拿得到全量;
    # stderr 的可见度仍由 _h 的 level (level) 单独卡。
    root.setLevel(logging.DEBUG if path else level)
    if _h is None:
        _h = logging.StreamHandler(sys.stderr)
        _h.setFormatter(_ColorFmt())
        root.addHandler(_h)
        root.propagate = False
    _h.setLevel(level)
    for name in _THIRD_PARTY:
        logging.getLogger(name).setLevel(
            logging.DEBUG if debug >= 2 else logging.WARNING)

    _bind_file(root, path)
    _log_setup(root, debug, path, level)
    return root


def _log_setup(root, debug, path, level):
    """把"日志这一层到底怎么配的"记一笔。

    排查第一件事就是确认日志本身有没有被配歪: 级别是不是 DEBUG、文件挂上没、
    用户目录在哪 (配置/规则/缓存全在那)。这条只在 -d 下可见, 不干扰正常输出。
    """
    from webtool.core.config_data import USER_DIR
    root.debug('logging | 装配完成 debug=%d stderr=%s file=%s 三方库=%s dir=%s',
               debug, logging.getLevelName(level), path or '-',
               'DEBUG' if debug >= 2 else 'WARNING',
               os.environ.get('WEBTOOL_DIR') or str(USER_DIR))


def _bind_file(root, path):
    """挂/换/撤文件 handler; 文件 handler 恒为 DEBUG 全量, 与终端级别解耦"""
    global _fh, _fh_path
    path = os.path.expanduser(str(path).strip()) if path else ''
    if path == _fh_path:
        return
    if _fh is not None:
        root.removeHandler(_fh)
        try:
            _fh.close()
        except Exception:
            pass
        _fh = None
    _fh_path = path
    if not path:
        return
    try:
        _fh = logging.FileHandler(path, encoding='utf-8')
    except OSError:
        return                      # 路径不可写: 静默降级, 别把命令弄挂
    _fh.setFormatter(_JsonFmt() if _is_jsonl(path)
                     else logging.Formatter(_FILE_FMT, datefmt=_FILE_DATEFMT))
    _fh.setLevel(logging.DEBUG)
    root.addHandler(_fh)


def _is_jsonl(path):
    return str(path).lower().endswith(('.jsonl', '.ndjson'))


class _JsonFmt(logging.Formatter):
    """JSON Lines: 一行一个事件, 供进程/Agent 消费 (ts/level/module/msg + 附加字段)"""

    def format(self, record):
        ev = {
            'ts': round(record.created, 3),
            'level': record.levelname,
            'module': record.name,
            'thread': record.threadName,
            'file': '%s:%d' % (record.filename, record.lineno),
            'msg': record.getMessage(),
        }
        for k in ('url', 'rule', 'elapsed_ms', 'kind'):
            v = getattr(record, k, None)
            if v is not None:
                ev[k] = v
        if record.exc_info:
            ev['exc'] = self.formatException(record.exc_info)
        return json.dumps(ev, ensure_ascii=False)


def env_debug():
    """环境变量兜底: WEBTOOL_DEBUG=1/debug 等效 -d (脚本/Agent 免加参数)"""
    v = os.environ.get('WEBTOOL_DEBUG', '').strip().lower()
    return 1 if v in ('1', 'debug', 'true', 'yes') else 0


_SENSITIVE_Q = re.compile(r'^(token|key|password|passwd|pwd|secret|sign|signature|'
                         r'sig|auth|access_key|apikey|api_key|session|sid)$', re.I)


def redact_url(url):
    """URL 进日志前先打码: query 里 token/key/password 一类的值换成 ***。

    日志会被贴进 issue、发给别人看, 带令牌的 URL 是最常见的泄漏口; 而这种
    泄漏往往就发生在"为了排查方便把 URL 打全"的时候。只留参数名, 够定位。
    """
    if not isinstance(url, str) or '?' not in url:
        return url
    try:
        head, _, q = url.partition('?')
        out = []
        for kv in q.split('&'):
            k, eq, _v = kv.partition('=')
            out.append(f'{k}=***' if (eq and _SENSITIVE_Q.match(k)) else kv)
        return head + '?' + '&'.join(out)
    except Exception:
        return url


@contextlib.contextmanager
def timed(logger, label, **fields):
    """耗时埋点: `with timed(logger, 'fetch', url=u): ...` → debug 一行

    只在 debug 下才有价值; 用 perf_counter, 异常也照记 (finally)。
    fields 里别塞敏感值 (密码/令牌)。
    """
    if 'url' in fields:
        fields['url'] = redact_url(fields['url'])
    t0 = time.perf_counter()
    err = None
    try:
        yield
    except BaseException as e:            # noqa: BLE001 记录后原样抛出
        err = e
        raise
    finally:
        ms = (time.perf_counter() - t0) * 1000.0
        extra = dict(fields)
        extra['elapsed_ms'] = round(ms, 1)
        if err is not None:
            extra['error'] = '%s: %s' % (type(err).__name__, str(err)[:120])
        plain = ' '.join('%s=%s' % kv for kv in fields.items())
        try:
            logger.debug('timed | 耗时 %.0fms %s%s', ms, label,
                         (' ' + plain) if plain else '', extra=extra)
        except Exception:
            pass


def is_debug():
    """当前是否 -d 及以上 (决定异常要不要抖 traceback)"""
    return _debug >= 1


def debug_level():
    """当前 debug 叠加次数 (0 / 1 / 2) —— 供需要复原日志配置的调用方

    is_debug() 只答"开没开", 复原配置时 -d 与 -dd 得分清 (前者只放本仓 DEBUG,
    后者连三方库一起放), 所以这里给原值。
    """
    return _debug


def get_logger(name):
    """统一入口; 名字传 __name__ (webtool.* 前缀自动挂到根 logger 下)"""
    return logging.getLogger(name)
