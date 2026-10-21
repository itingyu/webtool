"""插件 SDK: 单文件 serve 循环 + 示例插件可被 webtool 直接驱动"""
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stderr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "sdk", "python"))
sys.path.insert(0, os.path.join(ROOT, "src"))

from webtool_plugin_sdk import Plugin, bypass, hit, serve   # noqa: E402

TMP = tempfile.mkdtemp(prefix="webtool-sdk-")
os.environ["WEBTOOL_DIR"] = TMP
os.environ["WEBTOOL_PLUGIN_DIR"] = os.path.join(TMP, "plugins")

FAIL = []
N = [0]


def check(cond, msg, detail=""):
    N[0] += 1
    if cond:
        print("PASS %s" % msg)
    else:
        FAIL.append(msg)
        print("FAIL %s  %s" % (msg, detail))


class Demo(Plugin):
    name = "demo"

    def inspect(self, ctx):
        return hit("waf", "demo", "示例") if "BLOCK" in (ctx.get("text") or "") else None

    def bypass(self, ctx, h):
        return bypass("换入口", ctx["url"] + "?ok=1")


def _roundtrip(lines):
    inp, out = io.StringIO("\n".join(lines) + "\n"), io.StringIO()
    serve(Demo(), stdin=inp, stdout=out)
    return [json.loads(x) for x in out.getvalue().splitlines()]


rows = _roundtrip([
    json.dumps({"op": "ping"}),
    json.dumps({"op": "inspect", "ctx": {"text": "BLOCK here"}}),
    json.dumps({"op": "inspect", "ctx": {"text": "normal"}}),
    json.dumps({"op": "bypass", "ctx": {"url": "https://e.com/a"}}),
    json.dumps({"op": "wat"}),
])
check(rows[0].get("ok") is True and rows[0].get("protocol") == 1, "SDK: ping 带协议版本", rows[0])
check(rows[1].get("hit", {}).get("sign") == "demo", "SDK: inspect 返回 hit", rows[1])
check(rows[2] == {}, "SDK: 未命中返回 {}", rows[2])
check("ok=1" in rows[3].get("bypass", {}).get("url", ""), "SDK: bypass 返回绕法", rows[3])
check(rows[4] == {}, "SDK: 未知 op 返回 {}", rows[4])


class Boom(Plugin):
    def inspect(self, ctx):
        raise RuntimeError("boom")


inp, out, err = io.StringIO('{"op":"inspect","ctx":{}}\n'), io.StringIO(), io.StringIO()
with redirect_stderr(err):
    serve(Boom(), stdin=inp, stdout=out)
check(json.loads(out.getvalue()) == {}, "SDK: 插件抛错仍回合法 JSON", out.getvalue())
check("boom" in err.getvalue(), "SDK: 堆栈走 stderr 不进协议", err.getvalue()[:60])

# ── 示例插件真进程 + webtool 适配器 ─────────────────────────────────────
from webtool.net import intercept                       # noqa: E402
from webtool.net.extproc import probe                   # noqa: E402

plugin = os.path.join(ROOT, "sdk", "examples", "python", "plugin.py")
spec = {"command": [sys.executable, plugin], "timeout": 1.0,
        "params": {"timeout": 1.0}}
check(probe(spec, "sdk_example")[0], "示例插件可被 probe 拉起")

with open(os.path.join(TMP, "plugins.json"), "w", encoding="utf-8") as f:
    json.dump({"interceptor": {"sdk_example": {
        "type": "external", "command": [sys.executable, plugin],
        "timeout": 1.0}}}, f)

ctx = intercept.Ctx(url="https://www.example.com/a", status=200,
                    text="<html><title>Just a moment...</title></html>")
inst = next(p for p in intercept.interceptors() if p.name == "sdk_example")
hit_obj = inst.inspect(ctx)
check(hit_obj is not None and hit_obj.by == "sdk_example",
      "示例插件接入后能判定", hit_obj)
check(intercept.inspect(ctx) is not None, "通用链路上同样判出 (captcha 先命中)", None)

bp = intercept.bypass(ctx, hit_obj)
check(bp is not None and "m.example.com" in bp.url, "示例插件绕法生效", bp)
intercept.close_external()

print("\n%d PASS, %d FAIL" % (N[0] - len(FAIL), len(FAIL)))
sys.exit(1 if FAIL else 0)
