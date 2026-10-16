"""fetch 主获取通道: transport 浏览器指纹, cffi 全挂时内部落到 urllib。

opener 参数保留兼容旧调用, 实际不再使用。

本模块同时是**弹性层** (docs/coding-standard.md §2.9): 并发 / 重试 / 熔断 /
断点恢复的统一出口, 业务模块不自己写线程池与重试循环。策略默认值住在
这里的常量; 按域名特殊化走 rules.json 的 kind 条目 (`retry` / `breaker`,
见 net.rules.Router.params_for)。
"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from webtool.core.logging import get_logger

logger = get_logger(__name__)

# ── 通用默认值 (特殊走规则, 否则走这里) ─────────────────────────────
DEFAULT_RETRIES = 2
DEFAULT_BACKOFF = 'exp'          # exp=指数退避+jitter; flat=固定间隔
RETRY_BASE = 0.5                 # 首次重试等待秒数
RETRY_CAP = 8.0                  # 退避上限秒数
DEFAULT_FAIL_THRESHOLD = 5       # 连续失败 N 次 → 熔断打开
DEFAULT_COOL_SECONDS = 300       # 熔断冷却半开期
MAX_WORKERS = 4                  # 并发上限 (全仓唯一来源): 出口是同一条代理/
# 同一条网, 4 条已能把首轮墙钟压到接近最慢那个源; 再往上收益是零头, 风险是
# 把自己这条线路打满导致超时。业务模块别自己写 6/8/16, 从这里取。


def retry_policy(url):
    """URL → (retries, backoff): kind:retry 规则 > 通用默认"""
    try:
        from webtool.net import rules as _rules
        p = _rules.router().params_for('retry', url or '')
        return int(p.get('retries') or DEFAULT_RETRIES), \
            str(p.get('backoff') or DEFAULT_BACKOFF)
    except Exception as e:                 # 规则读不到不能连累重试
        logger.debug('resilient | retry 规则查询失败, 用默认: %s', e)
        return DEFAULT_RETRIES, DEFAULT_BACKOFF


def breaker_policy(url):
    """URL → (fail_threshold, cool_seconds): kind:breaker 规则 > 通用默认"""
    try:
        from webtool.net import rules as _rules
        p = _rules.router().params_for('breaker', url or '')
        return int(p.get('fail_threshold') or DEFAULT_FAIL_THRESHOLD), \
            int(p.get('cool_seconds') or DEFAULT_COOL_SECONDS)
    except Exception as e:
        logger.debug('resilient | breaker 规则查询失败, 用默认: %s', e)
        return DEFAULT_FAIL_THRESHOLD, DEFAULT_COOL_SECONDS


def retry_call(fn, *, url=None, retries=None, backoff=None,
               exceptions=(Exception,), on_retry=None, sleep=time.sleep):
    """带退避的重试包装: 只重试幂等请求, 结果按原样返回 / 异常原样抛

    retries/backoff 不给时按 retry 规则 (kind:retry) 或通用默认。
    on_retry(attempt, err) 是观察钩子 (打日志/计数), 不控制流程。
    """
    r, b = retry_policy(url) if retries is None or backoff is None \
        else (retries, backoff)
    attempt = 0
    while True:
        try:
            return fn()
        except exceptions as e:
            attempt += 1
            if attempt > r:
                raise
            if b == 'exp':
                import random
                d = RETRY_BASE * (2 ** (attempt - 1))
                d *= 0.5 + random.random()        # jitter, 防同时打
                d = min(RETRY_CAP, d)             # 上限在加完 jitter 之后
            else:
                d = min(RETRY_CAP, RETRY_BASE)
            if on_retry:
                on_retry(attempt, e)
            logger.debug('resilient | 重试 %s/%s (%s: %s), 等 %.1fs',
                         attempt, r, type(e).__name__, str(e)[:80], d)
            sleep(d)


# ── 熔断: 按域名连续失败计数, 状态经 dao.state 跨进程生效 ──────────
class BreakerOpenError(RuntimeError):
    """域级熔断打开中: 请求被短路, 剩余冷却秒数在消息里"""
class Breaker:
    """域级熔断器: 连续失败 fail_threshold 次 → 打开 cool_seconds

    状态名 `resilient:<host>`, 与 gnews 等各自命名的 breaker 互不干扰。
    打开期调用方应直接短路 (不发请求); 冷却过半开: 计数清零放行试探,
    试探再失败会在 record 里立即重开。
    """

    def __init__(self, url):
        from urllib.parse import urlsplit
        self.host = urlsplit(url or '').hostname or ''
        self.name = 'resilient:' + self.host

    def _load(self):
        from webtool.dao import state
        return state.get_breaker(self.name)

    def check(self):
        """熔断打开返回剩余冷却秒数 (调用方直接短路), 否则 None"""
        br = self._load()
        until = br.get('open_until', 0)
        left = until - time.time()
        if left > 0:
            logger.debug('resilient | 熔断打开 %s (剩 %.0fs)', self.host, left)
            return left
        if until and br.get('fails'):
            self._record(fails=0)          # 半开放行试探
        return None

    def record(self, ok):
        """记账: 失败累计到阈值则打开; 成功清零"""
        br = self._load()
        if ok:
            if br.get('fails'):
                self._record(fails=0)
            return
        threshold, cool = breaker_policy('https://' + self.host if self.host
                                         else '')
        fails = int(br.get('fails', 0)) + 1
        if fails >= threshold:
            logger.debug('resilient | 熔断打开 %s (%d 连败, 冷却 %ss)',
                         self.host, fails, cool)
            self._record(fails=fails, open_until=time.time() + cool)
        else:
            self._record(fails=fails)

    def _record(self, **kv):
        from webtool.dao import state
        state.set_breaker(self.name, **kv)


def guard(url):
    """域级熔断检查: 打开期直接抛 BreakerOpenError (不发请求)

    三条出网通道 (get / request / download) 共用; 熔断的意义就是别再打,
    所以这里只短路。返回的 Breaker 由调用方在成败处 record。
    """
    br = Breaker(url)
    left = br.check()
    if left is not None:
        raise BreakerOpenError(
            '熔断打开中 %s (剩 %.0fs), 先修原因或等冷却' % (url, left))
    return br


def count_failure(br, e, *, exempt=()):
    """记账: 命中 exempt 的异常不算站点失败 (如证书错 = 配置问题)"""
    if isinstance(e, exempt):
        return
    br.record(False)


# ── 并发: 统一线程池入口 (共享状态只在主线程写, 见规范"多源抓取"节) ──
def parallel_map(items, fn, *, max_workers=None, desc=''):
    """items 并发跑 fn, **按声明顺序**返回 (结果, 异常或 None) 列表

    - 顺序恒定: 下游排序对并列项才稳定, 回填顺序不能随线程完成顺序漂
    - 单个任务异常被捕获放回自己的槽位, 不炸整批
    - max_workers 上限 MAX_WORKERS (=4, 全仓唯一来源): 出口是同一条代理/
      同一条网, 开太满只是把自己打满
    """
    items = list(items)
    if not items:
        return []
    workers = max(1, min(int(max_workers or MAX_WORKERS), MAX_WORKERS,
                         len(items)))
    out = [None] * len(items)
    if workers == 1:
        for i, it in enumerate(items):
            try:
                out[i] = (fn(it), None)
            except Exception as e:
                out[i] = (None, e)
        return out
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fn, it): i for i, it in enumerate(items)}
        for f in as_completed(futs):
            i = futs[f]
            try:
                out[i] = (f.result(), None)
            except Exception as e:
                out[i] = (None, e)
    logger.debug('resilient | parallel_map %s: %d 项 / %d 线程 / %.1fs',
                 desc or '', len(items), workers, time.time() - t0)
    return out


# ── 断点恢复 (Checkpoint) 已迁 dao/checkpoint.py; 再导出保兼容 ──
from webtool.dao.checkpoint import Checkpoint  # noqa: E402,F401


from webtool.net import transport
from webtool.net import proxyhelper


def fetch(url, proxy=None, timeout=None, headers=None, opener=None,
          profile=None, raw=False, max_bytes=None):
    """返回 (text, status, via); raw=True 时返回 (bytes, status, via, headers)

    raw 给"目标可能根本不是网页"的场景用 (fetch 判类型/存图片视频压缩包):
    不解码、不降级, 拿到响应头和原始字节就够。
    via: 'proxy' | 'direct' | 'cffi' | 'urllib'

    **单线路, 不 failover**。走哪条线由 proxyhelper 依据配置 + 路由表一次决定,
    请求失败就报错 —— 退直连重试会掩盖真实原因 (代理挂了 → 目标拒绝/超时, 报出来
    的是后者), 对"只允许代理出网"的目标也只是换一种错法。

    timeout 默认 None = 交 transport 的通用兜底链 (http 规则 →
    config.json 的 timeout → 内置 15), 写死 15 会让用户配的超时失效。

    - profile: 传输指纹档案名 (transport.PROFILES 键, 如 'chrome131_android'),
      None 时由 transport 自选桌面档案
    """
    p = proxyhelper.resolve(proxy, url)
    prof = profile if (isinstance(profile, str) and profile in transport.PROFILES) else None
    if raw:
        kw = {} if max_bytes is None else {'max_bytes': max_bytes}
        return transport.get(url, kind='nav', proxy=p, timeout=timeout,
                             headers=headers, profile=prof, raw=True, **kw)
    text, status, via = transport.get(
        url, kind='nav', proxy=p, timeout=timeout,
        headers=headers, profile=prof)
    return text, status, via


def open_stream(url, proxy=None, timeout=None, headers=None, profile=None):
    """流式打开 (不读 body), 返回 (resp, status, via, headers) —— 下载用

    代理与 fetch 同一处决定 (proxyhelper.resolve): 二进制下载也是出网请求,
    凭什么规则表管网页却不管文件。
    """
    p = proxyhelper.resolve(proxy, url)
    prof = profile if (isinstance(profile, str) and profile in transport.PROFILES) else None
    return transport.open_stream(url, kind='nav', proxy=p, timeout=timeout,
                                 headers=headers, profile=prof)
