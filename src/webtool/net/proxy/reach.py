"""代理可达性: "目标代理没起来"就改走直连 (config.json 的 proxy_fallback)

为什么值得单独一层: 本地代理 (Clash / 回环端口) 没启动是**最常见**的失败, 表现
却是"每条请求都失败", 报错指向连接被拒 —— 用户很难联想到"我的代理没开着"。
这类失败与"代理起来了、但目标站被墙/超时"是两码事, 所以这里只认前者: 连 TCP
都握不上手 (拒绝/超时/DNS 不通) 才算"未启动"。代理自己返回的 4xx/5xx 一律不算,
那是线路通了之后的业务结果。

代价: 一次 TCP 握手 + 30s 缓存。代理活着时探测就是一次回环连接 (毫秒级), 且
同一个 host:port 30s 内只探一次 —— 不会给每个请求都加一次 syscall。

不想兜底: `webtool config set proxy_fallback off`, 回到"线路只由配置决定,
连不上就报错"。
"""
import socket
import time

from webtool.core.logging import get_logger

logger = get_logger(__name__)

CACHE_TTL = 30.0        # 探测结论存活时长 (通的/不通的都缓存)
PROBE_TIMEOUT = 0.8     # 单次握手超时; 本机端口拒绝是瞬时的, 这个值只为远端黑洞

_cache = {}             # (host, port) -> (ts, ok)


def enabled():
    """config.json 的 proxy_fallback (默认 on)

    走 resilient.config_snapshot (mtime 缓存): 本函数在每个请求的路径上, 不能
    每请求都去解析一遍 config.json。键名保持字面量 —— 键表守卫靠正则找它。
    """
    try:
        from webtool.core import resilient
        cfg = resilient.config_snapshot()
    except Exception:                      # 读配置失败不能反过来把出网搞挂
        return True
    return str(cfg.get('proxy_fallback', 'on')).strip().lower() not in (
        'off', 'false', '0', 'no', 'disable')


def usable(proxy_url, url=''):
    """这条代理现在能用吗。False = 没起来, 调用方改走直连。

    **判不出来就返回 True**: 解析不出 host:port、端口不是数字这类情况一律照配置
    走 —— 拿一个猜出来的结论把用户的代理绕过去, 比不兜底更坏。
    """
    if not enabled():
        return True
    key = _key(proxy_url)
    if key is None:
        return True
    ok, first = _probe(key)
    if not ok and first:
        # 一个缓存窗口只吵一次: 代理没开时每个请求都来一条警告, 等于刷屏没人看
        logger.warning('proxy | 代理连不上 (%s:%s), 本次改走直连%s; 代理起来后自动'
                       '恢复; 关掉兜底: webtool config set proxy_fallback off',
                       key[0], key[1], f' ({url})' if url else '')
    return ok


def reset():
    """清空探测缓存 (给测试与"刚改完配置"的路径用)"""
    _cache.clear()


def _key(proxy_url):
    """代理 URL → (host, port); 取不到就 None (不猜)"""
    try:
        from webtool.net.proxy.store import proxy_url_parts
        _, _, _, host, port = proxy_url_parts(proxy_url)
    except Exception:
        return None
    if not host:
        return None
    try:
        port = int(port)
    except (TypeError, ValueError):
        return None                        # 没写端口 (或不是数字): 不知道探哪个口
    return host, port


def _probe(key):
    """返回 (是否连得上, 是不是本缓存窗口的第一次探测)"""
    now = time.monotonic()
    hit = _cache.get(key)
    if hit is not None and now - hit[0] < CACHE_TTL:
        return hit[1], False
    ok = _connect(*key)
    _cache[key] = (now, ok)
    return ok, True


def _connect(host, port):
    """一次 TCP 握手 —— 代理的监听端口在不在, 这是唯一可靠的判据"""
    try:
        with socket.create_connection((host, port), timeout=PROBE_TIMEOUT):
            return True
    except OSError as e:
        logger.debug('proxy | 探测 %s:%s 失败: %s: %s', host, port,
                     type(e).__name__, e)
        return False
