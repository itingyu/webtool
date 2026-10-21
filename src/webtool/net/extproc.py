"""拦截器专用的外部进程适配器: ctx/hit/bypass 映射 + 公共进程通道

配置 (plugins.json interceptor 段):
    {"waf_go": {"type": "external",
                "command": ["/opt/waf", "--stdio"],
                "timeout": 0.2, "hosts": ["example.com"]}}
"""
from webtool.core.external import (ExternalProcess, command_of,
                                   probe as _probe, timeout_of)
from webtool.net.intercept import Bypass, Hit, Interceptor


class ExternalInterceptor(Interceptor):
    def __init__(self):
        self.name = 'external'
        self.priority = 50
        self.hosts = ()
        self.cools_down = False
        self.command = []
        self.timeout = 0.5
        self.max_text = 1000000
        self._proc = ExternalProcess([], 0.5)

    def configure(self, name, spec):
        p = spec.get('params') or {}
        get = lambda k, d=None: spec.get(k, p.get(k, d))     # noqa: E731
        self.name = name
        self.priority = int(get('priority', 50) or 50)
        self.hosts = tuple(str(h).lower() for h in (get('hosts') or ()))
        self.cools_down = bool(get('cools_down', False))
        try:
            self.max_text = int(get('max_text', 1000000) or 1000000)
        except (TypeError, ValueError):
            self.max_text = 1000000
        cmd, tmo = command_of(spec), timeout_of(spec, 0.5)
        if cmd != self.command or tmo != self.timeout:
            self._proc.close()
            self._proc = ExternalProcess(cmd, tmo)
        self.command, self.timeout = cmd, tmo

    @property
    def last_error(self):
        return self._proc.last_error

    def close(self):
        self._proc.close()

    def _ask(self, op, **payload):
        return self._proc.call(op, **payload)

    def _ctx(self, ctx):
        text = ctx.text or ''
        out = {'site': ctx.site, 'url': ctx.url, 'status': ctx.status,
               'via': ctx.via, 'text': text[:self.max_text]}
        if len(text) > self.max_text:
            out['truncated'] = True
        # 响应头带上: 外部插件要判 Cloudflare 质询得看 cf-mitigated 头,
        # 只给正文它就认不出来 (正文特征随版本变, 那个头没变)
        hdrs = {str(k).lower(): str(v) for k, v in dict(ctx.headers or {}).items()}
        if hdrs:
            out['headers'] = hdrs
        return out

    # ── 拦截器接口 ────────────────────────────────────────────────────
    def preflight(self, ctx):
        h = (self._ask('preflight', ctx=self._ctx(ctx)) or {}).get('hit')
        if not h:
            return None
        return Hit(kind=str(h.get('kind') or 'external'), by=self.name,
                   sign=str(h.get('sign') or ''),
                   why=str(h.get('why') or '外部插件拦截'),
                   left=int(h.get('left') or 0),
                   hint=str(h.get('hint') or ''))

    def inspect(self, ctx):
        h = (self._ask('inspect', ctx=self._ctx(ctx)) or {}).get('hit')
        if not h:
            return None
        return Hit(kind=str(h.get('kind') or 'external'), by=self.name,
                   sign=str(h.get('sign') or ''),
                   why=str(h.get('why') or '外部插件判定'),
                   left=int(h.get('left') or 0),
                   hint=str(h.get('hint') or ''))

    def bypass(self, ctx, hit):
        b = (self._ask('bypass', ctx=self._ctx(ctx),
                       hit={'kind': hit.kind, 'sign': hit.sign,
                            'why': hit.why}) or {}).get('bypass')
        if not b:
            return None
        return Bypass(how=str(b.get('how') or self.name),
                      url=str(b.get('url') or ''),
                      headers=dict(b.get('headers') or {}),
                      profile=str(b.get('profile') or ''),
                      delay=float(b.get('delay') or 0),
                      retry=bool(b.get('retry', True)))

    def note_ok(self, ctx):
        self._ask('note_ok', ctx=self._ctx(ctx))

    def note_hit(self, ctx, hit):
        self._ask('note_hit', ctx=self._ctx(ctx),
                  hit={'kind': hit.kind, 'sign': hit.sign, 'why': hit.why})


def probe(spec, name='<external>'):
    """体检用: 起一次、ping 通、再关掉 → (ok, 原因)"""
    return _probe(spec, name)
