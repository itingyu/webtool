"""分级彩色日志: 全命令 --debug 的基础设施

约定 (docs/coding-standard.md §2.6):
- 打印给人看的用 print, 定位问题用的必须走 logger (`logging.getLogger(__name__)`)
- 日志一律到 **stderr** —— stdout 是数据通道 (管道/`-f json` 消费), 混进日志
  等于毁掉 `x | webtool ...` 范式
- 默认级别 WARNING: 不带 --debug 时行为与从前完全一致 (零日志输出);
  `--debug/-d` (可叠加) 放开各级别, 颜色分级 DEBUG 灰 / INFO 绿 / WARN 黄 / ERROR 红
- 非 tty 或 NO_COLOR 自动去色; 去色逻辑只碰本 handler 的格式, 不动全局

级别映射: -d×1 → DEBUG (全量); 也认 WEBTOOL_DEBUG 环境变量 (1/debug → DEBUG)。
handler 只装一次, 重复调用 (每命令的 callback 都会进来) 直接改级别即可。
"""
import logging
import os
import sys

_FMT = '%(asctime)s %(levelname).1s %(name)s: %(message)s'
_DATEFMT = '%H:%M:%S'

# 级别 → ANSI 色; 去色时由 _color 化整为零直接不拼
_COLOR = {'D': '\033[90m', 'I': '\033[32m', 'W': '\033[33m', 'E': '\033[31m'}
_RESET = '\033[0m'


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


def setup(debug=0):
    """按 --debug 叠加次数装配根 ('webtool') logger; 幂等, 每命令回调都调

    debug>=1 → DEBUG 全放开; 0 → WARNING (等效于关闭: 正常路径没有 WARNING
    以上日志, 出了问题该吵还是会吵)。
    """
    global _h
    root = logging.getLogger('webtool')
    level = logging.DEBUG if debug else logging.WARNING
    if _h is None:
        _h = logging.StreamHandler(sys.stderr)
        _h.setFormatter(_ColorFmt())
        root.addHandler(_h)
        root.propagate = False
    root.setLevel(level)
    _h.setLevel(level)
    # 三方库的 INFO/DEBUG 噪声 (urllib3/curl_cffi) 不跟随 --debug, 只留 WARNING
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    return root


def env_debug():
    """环境变量兜底: WEBTOOL_DEBUG=1/debug 等效 -d (脚本/Agent 免加参数)"""
    v = os.environ.get('WEBTOOL_DEBUG', '').strip().lower()
    return 1 if v in ('1', 'debug', 'true', 'yes') else 0


def get_logger(name):
    """统一入口; 名字传 __name__ (webtool.* 前缀自动挂到根 logger 下)"""
    return logging.getLogger(name)
