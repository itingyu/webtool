"""webtool 外部插件 SDK（零依赖，可单独拷进你的项目）

用法: 继承 Plugin，实现 inspect（可选 preflight/bypass/note_*），然后 serve()。
只依赖标准库，不需要安装 webtool；协议见 docs/external-plugins.md。

    from webtool_plugin_sdk import Plugin, serve, hit, bypass

    class Waf(Plugin):
        def inspect(self, ctx):
            if "cf-challenge" in ctx["text"]:
                return hit("waf", "cf-challenge", "质询页")
            return None

    if __name__ == "__main__":
        serve(Waf())
"""
import json
import sys
import traceback

PROTOCOL = 1


def hit(kind="custom", sign="", why="", left=0, hint=""):
    """构造一条命中（返回给 webtool 的 hit 对象）

    hint: 处置建议（可选）。命中后 webtool 会把它附在 BlockedError 消息末尾，
    告诉人下一步该干什么（换线路、换引擎、还是必须上浏览器求解器）。
    """
    return {"hit": {"kind": kind, "sign": sign, "why": why, "left": int(left),
                    "hint": str(hint or "")}}


def bypass(how="", url="", headers=None, profile="", delay=0.0, retry=True,
           cookies=None, user_agent=""):
    """构造一条绕法；至少给 how 或 url 才有意义

    cookies: 下一次重试要带的 cookie（如求解器拿到的 cf_clearance）
    user_agent: 换 UA。⚠ 覆盖 impersonate 自带的 UA 会让"UA 与 TLS 指纹
    不同源"自曝；更稳的是用 profile 切到同版本档案，求解器也跑同版浏览器。
    """
    return {"bypass": {"how": how, "url": url, "headers": dict(headers or {}),
                       "profile": profile, "delay": float(delay),
                       "retry": bool(retry), "cookies": dict(cookies or {}),
                       "user_agent": str(user_agent or "")}}


# curl_cffi 支持的 Chrome 伪装目标 (静态副本: SDK 零依赖, 问不了 curl_cffi;
# 升级 curl_cffi 后记得同步这份清单)
CHROME_TARGETS = ("chrome131", "chrome133a", "chrome136", "chrome142",
                  "chrome145", "chrome146", "chrome150", "chrome131_android")

_PLATFORM_HINT = {"win": '"Windows"', "mac": '"macOS"',
                  "linux": '"Linux"', "android": '"Android"'}


def profile_for_ua(ua):
    """求解器 UA → 指纹档案 dict (形状同 webtool 的 PROFILES 条目) 或 None

    用法: 求解插件拿到 solver 的 UA 后调它, 把结果填进 bypass(profile=...),
    抓取端就与求解端同 Chrome 版本了 —— clearance 绑在设备上, 版本对不上
    照样被拦。

    sec_ch_ua 留空: 品牌列表随版本变, 硬编码必然对不上, 交给 impersonate 自己发。
    """
    import re
    if not ua:
        return None
    s = str(ua)
    m = re.search(r"Chrome/(\d+)", s) or re.search(r"CriOS/(\d+)", s)
    if not m:
        return None
    major = int(m.group(1))
    if "Android" in s:
        platform = "android"
    elif "iPhone" in s or "iPad" in s:
        platform = "ios"
    elif "Windows" in s:
        platform = "win"
    elif "Macintosh" in s or "Mac OS" in s:
        platform = "mac"
    elif "Linux" in s or "X11" in s:
        platform = "linux"
    else:
        platform = ""
    cands = ([f"chrome{major}_android", f"chrome{major}"] if platform == "android"
             else [f"chrome{major}", f"chrome{major}a"])
    target = next((t for t in cands if t in CHROME_TARGETS), "")
    if not target:
        lower = [t for t in CHROME_TARGETS
                 if t[6:].isdigit() and int(t[6:]) <= major]
        target = max(lower, key=lambda t: int(t[6:])) if lower else ""
    if not target:
        return None
    return {"impersonate": target, "ua": str(ua), "sec_ch_ua": "",
            "mobile": "?0", "platform": _PLATFORM_HINT.get(platform, "")}


class Plugin:
    """外部插件基类：所有方法都可选，返回 None / {} 表示不处理"""

    name = "plugin"
    protocol = PROTOCOL

    def preflight(self, ctx):
        """请求发出前问一句：现在能用吗？返回 hit(...) 表示先别发"""
        return None

    def inspect(self, ctx):
        """判定响应是否被拦：返回 hit(...) 或 None"""
        return None

    def bypass(self, ctx, hit_obj):
        """给绕法：返回 bypass(...) 或 None"""
        return None

    def note_ok(self, ctx):
        """本次通过（可复位计数）"""

    def note_hit(self, ctx, hit_obj):
        """确认被拦（可记冷却）"""

    def call(self, kind, args, kwargs):
        """非拦截器类插件（engine/filter/extractor...）的统一入口

        kind 是类别名，args/kwargs 是调用方原样传来的参数；返回可 JSON 化的结果。
        """
        return None


def _dispatch(plugin, msg):
    op = msg.get("op")
    if op == "ping":
        return {"ok": True, "protocol": PROTOCOL, "name": plugin.name}
    if op == "inspect":
        return plugin.inspect(msg.get("ctx") or {}) or {}
    if op == "preflight":
        return plugin.preflight(msg.get("ctx") or {}) or {}
    if op == "bypass":
        return plugin.bypass(msg.get("ctx") or {}, msg.get("hit") or {}) or {}
    if op == "note_ok":
        plugin.note_ok(msg.get("ctx") or {})
        return {}
    if op == "note_hit":
        plugin.note_hit(msg.get("ctx") or {}, msg.get("hit") or {})
        return {}
    if op == "call":
        return {"result": plugin.call(msg.get("kind"), msg.get("args") or [],
                                      msg.get("kwargs") or {})}
    return {}


def serve(plugin, stdin=None, stdout=None):
    """stdio 主循环：一行请求、一行响应；异常写 stderr，不污染协议"""
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            resp = _dispatch(plugin, msg)
        except Exception:                       # noqa: BLE001
            traceback.print_exc(file=sys.stderr)
            resp = {}
        stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        stdout.flush()


if __name__ == "__main__":
    serve(Plugin())
