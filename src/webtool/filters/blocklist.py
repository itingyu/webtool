"""站点黑名单: 低质量/内容农场站点过滤 (filter 插件: blocklist)

三层来源 (后者覆盖前者同名字段):
1. 内置默认 (data/filters.json): 常见内容农场/SEO 垃圾站, 开箱即用;
   每条的背景在该文件 notes 段
2. 用户配置 ~/.webtool/blocklist.json:
   {"block": ["csdn.net", ...], "allow": ["blog.csdn.net/gitblog_xxx"]}
   - block: 域名后缀匹配 (netloc == d 或 netloc.endswith('.' + d))
   - allow: 白名单例外, 优先级高于 block (可精确放行某子域)
3. 命令行 --block / --allow: 临时追加, 不落盘

匹配范围: 搜索结果 url; site 子命令结果同样生效 (--blocklist off 关闭)。
被剔除条目计入输出 blocked_by_blocklist 计数, json 可查。
"""
import json
import os
from urllib.parse import urlparse
from webtool.core.config_data import load


def _norm_host(netloc):
    """netloc → host (去 www./端口/大小写)

    注意 urls.host_of 收完整 URL, 这里传的是裸 netloc —— 直接调会得到
    空串 (urlparse('a.com').netloc 为空), 导致黑名单全部失效。
    """
    h = (netloc or '').split('@')[-1].split(':')[0].strip().lower()
    return h[4:] if h.startswith('www.') else h


def builtin_blocklist():
    """内置黑名单域名; filters.json 改动按 mtime 自动生效"""
    return load('blocklist', 'filters.json').get('domains', [])


# 兼容旧引用 (仅统计展示用); 过滤判定一律走 load_blocklist() 现取
DEFAULT_BLOCKLIST = builtin_blocklist()


def load_blocklist():
    """返回 (block_set, allow_set); 内置表 mtime 热生效"""
    block = set(builtin_blocklist())
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


def filter_blocked(results, ctx=None):
    """filter 插件入口: (结果列表, 上下文) -> 过滤后列表"""
    return filter_blocklist(results)[0]


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
