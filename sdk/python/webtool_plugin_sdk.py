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


def hit(kind="custom", sign="", why="", left=0):
    """构造一条命中（返回给 webtool 的 hit 对象）"""
    return {"hit": {"kind": kind, "sign": sign, "why": why, "left": int(left)}}


def bypass(how="", url="", headers=None, profile="", delay=0.0, retry=True):
    """构造一条绕法；至少给 how 或 url 才有意义"""
    return {"bypass": {"how": how, "url": url, "headers": dict(headers or {}),
                       "profile": profile, "delay": float(delay),
                       "retry": bool(retry)}}


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
