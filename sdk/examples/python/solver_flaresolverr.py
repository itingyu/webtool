"""参考实现：接一个远端真浏览器求解器（FlareSolverr），把 cf_clearance 交回 webtool

用法（把它注册成外部进程插件）:

    {
      "interceptor": {
        "cf_solver": {
          "type": "external",
          "command": ["python3", "/path/to/solver_flaresolverr.py"],
          "timeout": 0.2,
          "hosts": ["example.com"],
          "max_text": 1
        }
      }
    }

远端要先起 FlareSolverr（docker run -p 8191:8191 ghcr.io/flaresolverr/flaresolverr:latest），
环境变量 FLARESOLVERR_URL 指向它。

三条硬约束（不满足就是白求解）:
  1. 求解器与 webtool 必须走**同一出口 IP** —— CF 的 clearance 绑在访客/设备上;
  2. UA 必须一致 —— 求解器用的 Chrome 版本要和 webtool 的 impersonate 档案对齐;
  3. 浏览器版本要与 profile 对应 —— 用 profile 换指纹，别直接覆盖 UA（UA 与
     TLS 指纹脱钩会自曝）。
"""

import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../python"))
from webtool_plugin_sdk import Plugin, bypass, hit, serve   # noqa: E402

FS_URL = os.environ.get("FLARESOLVERR_URL", "http://127.0.0.1:8191")
FS_TIMEOUT = int(os.environ.get("FLARESOLVERR_TIMEOUT", "90"))


def _post(path, payload, timeout):
    req = urllib.request.Request(
        FS_URL + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def solve(url):
    """让远端浏览器过一遍质询 → (cookies, user_agent) 或 None"""
    try:
        resp = _post("/v1", {"cmd": "request.get", "url": url,
                             "maxTimeout": FS_TIMEOUT * 1000}, FS_TIMEOUT)
    except (urllib.error.URLError, OSError, ValueError):
        return None
    if resp.get("status") != "ok":
        return None
    sol = resp.get("solution") or {}
    jar = {}
    for c in sol.get("cookies") or []:
        name, val = c.get("name"), c.get("value")
        if name and val is not None:
            jar[name] = val
    if "cf_clearance" not in jar:
        return None
    return jar, sol.get("userAgent", "")


class CfSolver(Plugin):
    name = "cf_solver"

    def inspect(self, ctx):
        # 内置识别已经覆盖 CF 质询（响应头 cf-mitigated + 质询页特征），
        # 这里只补一条: 远端求解器不可用时给出可执行的提示
        hdrs = {str(k).lower(): str(v) for k, v in (ctx.get("headers") or {}).items()}
        if hdrs.get("cf-mitigated") == "challenge":
            return hit("cf_challenge", "cf-mitigated: challenge",
                       "Cloudflare 质询拦截",
                       hint="需要真浏览器求解: 起 FlareSolverr 并与抓取同出口 IP")
        return None

    def bypass(self, ctx, h):
        got = solve(ctx["url"])
        if not got:
            return None
        jar, ua = got
        # 只把 clearance 交回去; UA 用 profile 换档案保持同源, 不直接覆盖
        return bypass("带 cf_clearance 重试", cookies=jar, retry=True)


if __name__ == "__main__":
    serve(CfSolver())
