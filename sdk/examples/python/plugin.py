"""示例：判 Cloudflare 质询页，并给一条绕法"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../python"))
from webtool_plugin_sdk import Plugin, bypass, hit, serve   # noqa: E402


class Waf(Plugin):
    name = "waf_example"

    def inspect(self, ctx):
        low = (ctx.get("text") or "")[:200000].lower()
        if "cf-challenge" in low or "just a moment" in low:
            return hit("waf", "cf-challenge", "Cloudflare 质询页")
        return None

    def bypass(self, ctx, h):
        # 真实场景按站点给移动端/镜像地址；这里只演示协议
        return bypass("换移动端入口", ctx["url"].replace("www.", "m."), retry=True)


if __name__ == "__main__":
    serve(Waf())
