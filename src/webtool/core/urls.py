"""URL 归一化工具类

同一 URL 在去重、黑名单、可注册域判定、路由反查等场景需要不同的"归一",
此前散在 feed/blocklist/merge/transport/zen/radar 各写一份正则。这里按
语义拆成独立函数, 命名即用途, 避免再出现"归一化"的五种变体。

    norm_key   去重键: 去 www./大小写/query/fragment/尾斜杠
    host_of    取 host 并去 www.
    registrable 可注册域 (含 com.cn/co.uk 等二级后缀), 用于同站判定
    section_of 取 URL 首段路径 (栏目), 用于 feed 栏目比对
    strip_scheme 去协议前缀
"""
import re
from urllib.parse import urlparse

_RE_SCHEME = re.compile(r'^https?://', re.I)
_RE_WWW = re.compile(r'^www\.', re.I)

# 常见多级后缀 (可注册域判定用)
_SFX2 = ('com.cn', 'net.cn', 'org.cn', 'gov.cn', 'edu.cn', 'com.hk', 'com.tw',
         'com.au', 'co.uk', 'co.jp', 'com.br', 'com.sg')

def strip_scheme(u):
    """去 http(s):// 前缀, 不动其余部分"""
    return _RE_SCHEME.sub('', u or '')

def norm_key(u):
    """URL 去重键: 去 www./大小写/query/fragment/尾斜杠

    用于"这两个结果是不是同一个页面"的比对, 不是用于展示或请求。
    """
    u = strip_scheme((u or '').strip()).split('#')[0].split('?')[0].rstrip('/')
    return _RE_WWW.sub('', u).lower()

def host_of(u):
    """取 host 并去 www./端口; 解析失败返回空串"""
    try:
        host = (urlparse(u or '').netloc or '').lower()
    except ValueError:
        return ''
    if '@' in host:                       # 去掉 user:pass@
        host = host.rpartition('@')[2]
    if host.startswith('www.'):
        host = host[4:]
    return host.split(':')[0]

def registrable(host):
    """可注册域: example.com.cn → example.com.cn, a.b.example.com → example.com"""
    host = (host or '').split(':')[0].lower()
    if host.startswith('www.'):
        host = host[4:]
    labels = host.rsplit('.', 2)
    if len(labels) == 3 and labels[1] + '.' + labels[2] in _SFX2:
        return host
    if len(labels) >= 2:
        return labels[-2] + '.' + labels[-1]
    return host

def same_site(a, b):
    """两 URL 是否同一可注册域 (a/b 可传 URL 或裸 host)"""
    ha, hb = registrable(host_of(a) or a), registrable(host_of(b) or b)
    return bool(ha) and ha == hb

def section_of(u):
    """URL 首段路径 = 栏目名 (https://x.com/news/1 → news); 无路径返回空串"""
    rest = strip_scheme(u or '').partition('/')[2].split('?')[0].split('#')[0]
    return rest.split('/')[0] if rest else ''