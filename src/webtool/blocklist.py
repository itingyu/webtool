# -*- coding: utf-8 -*-
"""站点黑名单: 低质量/内容农场站点过滤

三层来源 (后者覆盖前者同名字段):
1. 内置默认 (DEFAULT_BLOCKLIST): 常见内容农场/SEO 垃圾站, 开箱即用
2. 用户配置 ~/.webtool/blocklist.json:
   {"block": ["csdn.net", ...], "allow": ["blog.csdn.net/gitblog_xxx"]}
   - block: 域名后缀匹配 (netloc == d 或 netloc.endswith('.' + d))
   - allow: 白名单例外, 优先级高于 block (可精确放行某子域)
3. 命令行 --block / --allow: 临时追加, 不落盘

匹配范围: 搜索结果 url; site 子命令结果同样生效 (--no-blocklist 关闭)。
被剔除条目计入输出 blocked_by_blocklist 计数, json 可查。
"""
import json
import os
import re
from urllib.parse import urlparse

# ---- 内置黑名单: 内容农场 / SEO 模板站 / 低质量聚合 (2026-10 整理) ----
DEFAULT_BLOCKLIST = [
    # CSDN 系: 博客正文被折叠要登录, 大量搬运/营销号
    'csdn.net', 'cdnbaidujc.com',
    # SEO 农场 / 模板采集站
    'jb51.net',           # 脚本之家: 大量无署名搬运
    'huaweicloud.com',    # 云社区采集文
    'aliyun.com',         # 开发者社区同上 (保留 ask.aliyun? 后缀匹配会全拦, 值得)
    '51cto.com',          # 采集/营销号混合
    'easylearn.baidu.com',
    'baijiahao.baidu.com',
    'zhimind.com', 'kaipuyun.cn', 'chinanpo.gov.cn',
    # 问答低质站
    'wenda.so.com', 'yisu.com', 'php.cn', 'divcss5.com',
    'dazhuanlan.com', 'xiaoheiseo.com',
    # 资源站引流的假下载页
    'win7xzb.com', 'pc6.com', 'downxia.com', 'greenxiazai.com',
    # 百科/词典: 技术与实体 query 下的高频噪声源 (泛匹配页)
    'baike.baidu.com',
    # 知乎: 正文 403 (需登录态), fetch 拿不到内容
    'zhihu.com',
]

# 用户自定义持久黑名单 (~/.webtool/blocklist.json)
# 默认不带 zhihu: 如需屏蔽 run: webtool blocklist add zhihu.com

# 域名规范化: 小写, 去 www. 前缀
def _norm_host(host):
    host = (host or '').lower().strip()
    if host.startswith('www.'):
        host = host[4:]
    return host


def load_blocklist():
    """返回 (block_set, allow_set)"""
    block = set(DEFAULT_BLOCKLIST)
    allow = set()
    path = os.path.expanduser('~/.webtool/blocklist.json')
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                user = json.load(f)
            block |= {d.lower().strip() for d in user.get('block', [])}
            allow |= {d.lower().strip() for d in user.get('allow', [])}
        except (OSError, ValueError):
            pass
    return block, allow


def is_blocked(url, block=None, allow=None, extra_block=(), extra_allow=()):
    """URL 是否命中黑名单. allow 优先于 block.

    block/allow 缺省时自动加载内置默认表 (不含用户自定义文件),
    避免无参调用恒 False 的陷阱。
    """
    if block is None or allow is None:
        _block, _allow = load_blocklist()
        block = _block if block is None else block
        allow = _allow if allow is None else allow
    host = _norm_host(urlparse(url or '').netloc)
    if not host:
        return False
    for a in list(allow) + list(extra_allow):
        if host == a or host.endswith('.' + a):
            return False
    for d in list(block) + list(extra_block):
        if host == d or host.endswith('.' + d):
            return True
    return False


def filter_blocklist(results, extra_block=(), extra_allow=()):
    """剔除黑名单结果, 返回 (kept, blocked_count)"""
    block, allow = load_blocklist()
    kept = []
    blocked = 0
    for r in results:
        if is_blocked(r.get('url', ''), block, allow, extra_block, extra_allow):
            blocked += 1
        else:
            kept.append(r)
    return kept, blocked


def handle_cli(args):
    """webtool blocklist show/add/remove/reset"""
    path = os.path.expanduser('~/.webtool/blocklist.json')
    data = {'block': [], 'allow': []}
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError):
            pass
    if args.action == 'show':
        print(json.dumps({'file': path,
                          'block': sorted(data.get('block', [])),
                          'allow': sorted(data.get('allow', [])),
                          'builtin_count': len(DEFAULT_BLOCKLIST)},
                         ensure_ascii=False, indent=1))
        return 0
    if args.action == 'reset':
        if os.path.exists(path):
            os.unlink(path)
        print('blocklist reset to builtin defaults')
        return 0
    if args.action in ('add', 'remove'):
        key = 'allow' if getattr(args, 'allow', False) else 'block'
        domain = (args.domain or '').lower().strip().lstrip('.')
        if not domain:
            print('usage: webtool blocklist add <domain> [--allow]', file=__import__('sys').stderr)
            return 2
        if args.action == 'add':
            if domain not in data.get(key, []):
                data.setdefault(key, []).append(domain)
        else:
            data[key] = [d for d in data.get(key, []) if d != domain]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        print(f'{args.action} {key}: {domain} -> {path}')
        return 0
    return 2
