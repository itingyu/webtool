"""微信 POC 人机校验: 识别 + 按链接形态补 chksm 绕过

mp.weixin.qq.com 的 /s 链接缺 `chksm` 参数时会被风控判成"抓取/重构链接",
返回 302 → `/mp/wappoc_appmsgcaptcha`(POC 校验) 或直接吐 secitptpage 壳页;
带上任意 `chksm=` 值即恢复正文。这是链接形态规则, 不是验证码 —— 所以能在
纯 HTTP 层绕开, 不必碰 TCaptcha。

只判"微信 /s 链接": 别的站出现 verify 字样不归本插件管 (captcha 插件仍在
更前面处理通用验证页)。补参数后仍被拦就返回 None, 交给上层按冷却/降级处理,
不制造无限重试。
"""
import zlib

from webtool.net.intercept import Bypass, Hit, Interceptor, register

_HOST = 'mp.weixin.qq.com'
_MARKS = ('wappoc_appmsgcaptcha', 'secitptpage/verify', 'TCaptcha.js')


def _host(url):
    return url.split('/')[2].lower() if '://' in url else ''


class WechatPocInterceptor(Interceptor):
    """POC 校验页: 缺 chksm 的链接补上再取一次"""

    name = 'wechat_poc'
    priority = 15                   # 比通用 captcha(10) 宽泛规则更具体, 但仍排在其后
    hosts = ('mp.weixin.qq.com',)   # 只在这个域名上被调用, 别的站不跑本插件

    def inspect(self, ctx):
        if _host(ctx.url) != _HOST:
            return None
        text = ctx.text or ''
        for m in _MARKS:
            if m in text:
                return Hit(kind='verify', sign=m, why='微信人机校验')
        return None

    def bypass(self, ctx, hit):
        # bypass 会向所有插件征集兜底绕法, 必须守住域名, 否则会给任意被拦 URL
        # 补一个毫无意义的 chksm
        if _host(ctx.url) != _HOST:
            return None
        if 'chksm=' in ctx.url:
            # 已经带了还拦: 说明不是链接形态问题, 本插件没有绕法
            return None
        token = '%016x' % (zlib.crc32(ctx.url.encode()) & 0xFFFFFFFFFFFFFFFF)
        sep = '&' if '?' in ctx.url else '?'
        return Bypass(how='补 chksm 恢复公众号链接形态',
                      url=f'{ctx.url}{sep}chksm={token}')


register(WechatPocInterceptor)
