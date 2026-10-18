"""fetch 主获取通道: transport 浏览器指纹, cffi 全挂时内部落到 urllib。

opener 参数保留兼容旧调用, 实际不再使用。

本模块同时是**弹性层** (docs/coding-standard.md §2.9): 并发 / 重试 / 熔断 /
断点恢复的统一出口, 业务模块不自己写线程池与重试循环。

**重试与熔断默认都关** (retries=0 / breaker_cool=0): 失败当场报出来, 不静默
重发、不把域名短路几分钟。要的人用 `webtool config set retries N` (或按站写
rules.json 的 kind 条目) 自己开。取值优先级: kind 规则 > config.json > 常量。

策略常量是"用户没配时的底": 重试默认 0 次, 熔断冷却默认 0 秒 (=关闭)。
"""
import contextlib
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from webtool.core.logging import get_logger

logger = get_logger(__name__)

# ── 通用默认值 (特殊走 kind 规则 > config.json > 这里) ──────────────
DEFAULT_RETRIES = 0              # 默认不重试 (失败当场抛, 不放大请求)
DEFAULT_BACKOFF = 'exp'          # exp=指数退避+jitter; flat=固定间隔
RETRY_BASE = 0.5                 # 首次重试等待秒数
RETRY_CAP = 8.0                  # 退避上限秒数
DEFAULT_FAIL_THRESHOLD = 5       # 连续失败 N 次 → 熔断打开
DEFAULT_COOL_SECONDS = 0         # 熔断冷却 0 = 关闭 (不打开)
MAX_WORKERS = 4                  # 并发上限 (全仓唯一来源): 出口是同一条代理/
# 同一条网, 4 条已能把首轮墙钟压到接近最慢那个源; 再往上收益是零头, 风险是
# 把自己这条线路打满导致超时。业务模块别自己写 6/8/16, 从这里取。


# config.json 读一次带 mtime 缓存 (每请求都要问一次, 不能每请求读盘);
# 配置改了就自动失效。做法同 net/pacing._cfg_timeout。
_CFG_LOCK = threading.Lock()
_CFG_CACHE = (None, None)        # (stamp, cfg dict | None)


def _config():
    """config.json 全量 (mtime 缓存); 读不到返回 {}。"""
    global _CFG_CACHE
    from webtool.net.proxy.store import CONFIG_PATH
    try:
        st = os.stat(CONFIG_PATH)
        stamp = (st.st_mtime_ns, st.st_size)
    except OSError:
        stamp = None
    with _CFG_LOCK:
        if _CFG_CACHE[1] is not None and _CFG_CACHE[0] == stamp:
            return _CFG_CACHE[1]
        try:
            from webtool.net.proxy import load_config
            cfg = load_config() or {}
        except Exception as e:             # 配置读不到不能连累重试/熔断
            logger.debug('resilient | config 读取失败: %s', e)
            cfg = {}
        _CFG_CACHE = (stamp, cfg)
        return cfg


def config_snapshot():
    """config.json 全量 (mtime 缓存) —— 给同层的 net 模块复用, 免得再抄一份缓存。

    读不到返回 {}; 调用方用 `cfg.get('键', 默认)` 取。键名保持字面量: 键表守卫
    (tests/test_smoke.py) 靠正则找 `cfg.get('键')`, 接收者变量名须为 cfg/config/
    _cfg/conf, 否则新键会被当成"没人读的死键"。
    """
    return _config()


def _rule_params(kind, url):
    try:
        from webtool.net import rules as _rules
        return _rules.router().params_for(kind, url or '') or {}
    except Exception as e:                 # 规则读不到不能连累重试/熔断
        logger.debug('resilient | %s 规则查询失败, 用配置/默认: %s', kind, e)
        return {}


def retry_policy(url):
    """URL → (retries, backoff): kind:retry 规则 > config.json > 通用默认

    `retries` 用显式 None 判定而非 `or` —— 0 ("不重试") 是合法且有意义的取值,
    `or` 会把它当假值跳过, 于是"配了 0"被悄悄改成默认, 与 jobs=0 是同一类坑。
    """
    p = _rule_params('retry', url)
    cfg = _config()
    r = p.get('retries')
    if r is None:
        r = cfg.get('retries')
    if r is None:
        r = DEFAULT_RETRIES
    b = p.get('backoff') or cfg.get('retry_backoff') or DEFAULT_BACKOFF
    return int(r), str(b)


def breaker_policy(url):
    """URL → (fail_threshold, cool_seconds): kind:breaker 规则 > config.json > 默认

    cool_seconds=0 表示关闭熔断 (不打开), 是默认值。
    """
    p = _rule_params('breaker', url)
    cfg = _config()
    thr = p.get('fail_threshold')
    if thr is None:
        thr = cfg.get('breaker_fails')
    if thr is None:
        thr = DEFAULT_FAIL_THRESHOLD
    cool = p.get('cool_seconds')
    if cool is None:
        cool = cfg.get('breaker_cool')
    if cool is None:
        cool = DEFAULT_COOL_SECONDS
    return int(thr), int(cool)


def retry_call(fn, *, url=None, retries=None, backoff=None,
               exceptions=(Exception,), on_retry=None, sleep=time.sleep):
    """带退避的重试包装: 只重试幂等请求, 结果按原样返回 / 异常原样抛

    retries/backoff 不给时按 kind:retry 规则 > config.json > 通用默认。
    **默认 retries=0 = 不重试** (失败当场抛, 不放大请求); 要重试用
    `webtool config set retries N` 或按站写 kind:retry 规则。
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

    **cool_seconds=0 表示关闭熔断** (默认): check 恒返回 None, record 不记账,
    于是既不短路也不写状态 —— 域名不会再被"锁"几分钟。
    """

    def __init__(self, url):
        from urllib.parse import urlsplit
        self.host = urlsplit(url or '').hostname or ''
        self.name = 'resilient:' + self.host

    def _policy(self):
        return breaker_policy('https://' + self.host if self.host else '')

    def _load(self):
        from webtool.dao import state
        return state.get_breaker(self.name)

    def check(self):
        """熔断打开返回剩余冷却秒数 (调用方直接短路), 否则 None"""
        _threshold, cool = self._policy()
        if cool <= 0:                      # 关闭: 不短路, 也不碰状态
            return None
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
        threshold, cool = self._policy()
        if cool <= 0 or threshold <= 0:    # 关闭: 不记账
            return
        br = self._load()
        if ok:
            if br.get('fails'):
                self._record(fails=0)
            return
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
# ── 并发: 统一线程池入口 (共享状态只在主线程写, 见规范"多源抓取"节) ──
#
# 为什么不用裸 ThreadPoolExecutor:
#   `with ThreadPoolExecutor(...)` 退出是 shutdown(wait=True) —— 在飞的网络请求
#   没回来就 join, Ctrl-C 于是"停不下来"; concurrent.futures 在解释器退出时还注册
#   了 _python_exit, 把所有 worker 再 join 一遍, 连 sys.exit(130) 都被拖住。
#   DaemonThreadPoolExecutor: worker 用 daemon 线程且**不登记 _threads_queues**,
#   _python_exit 不会等它们; 配合 thread_pool() 的"打断即取消未开始任务、不等待", 主线程
#   一抛 KeyboardInterrupt 就能退出(真卡在 C 调用里时由 core.shutdown 二次 Ctrl-C
#   强制兜底)。daemon 与"不登记"二者缺一不可 —— 只 daemon 仍会被 _python_exit 等。
try:
    from concurrent.futures.thread import _worker as _cf_worker
except Exception:                       # 未来版本移除私有名 → 退化为标准池
    _cf_worker = None


class DaemonThreadPoolExecutor(ThreadPoolExecutor):
    """ThreadPoolExecutor, 但 worker 是 daemon 且不被解释器退出 join"""

    def _adjust_thread_count(self):      # 与 stdlib 同形, 仅改 daemon + 不登记
        if _cf_worker is None:
            return super()._adjust_thread_count()
        import weakref
        if self._idle_semaphore.acquire(timeout=0):
            return

        def weakref_cb(_, q=self._work_queue):
            q.put(None)

        n = len(self._threads)
        if n < self._max_workers:
            name = '%s_%d' % (self._thread_name_prefix or self, n)
            t = threading.Thread(
                name=name, target=_cf_worker,
                args=(weakref.ref(self, weakref_cb), self._work_queue,
                      self._initializer, self._initargs),
                daemon=True)
            t.start()
            self._threads.add(t)
            # 故意不写 concurrent.futures.thread._threads_queues


@contextlib.contextmanager
def thread_pool(max_workers):
    """守护线程池上下文 (名字带 thread_, 免与业务里"结果池 pool=[]"撞名)

    正常路径仍需 shutdown(wait=True) —— 批任务要等结果收齐 (否则回填不完整)。
    "优雅关闭"针对的是**异常路径**: 收 KeyboardInterrupt 时 cancel_futures 丢掉还没
    排上的, 并且不等待在飞的请求, 让异常立刻往上走。
    """
    ex = DaemonThreadPoolExecutor(max_workers=max(1, int(max_workers)))
    try:
        yield ex
    except BaseException:
        ex.shutdown(wait=False, cancel_futures=True)
        raise
    else:
        ex.shutdown(wait=True)


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
    with thread_pool(workers) as ex:
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
