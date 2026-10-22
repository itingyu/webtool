"""core.links 与 robots 的离线测试"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from webtool.core import links as L  # noqa: E402

_fails = []


def check(cond, name):
    if cond:
        print('PASS ' + name)
    else:
        print('FAIL ' + name)
        _fails.append(name)

HTML = """
<a href="/a/1">A</a>
<a href="b/2">B</a>
<a href="https://other.com/x">外站</a>
<a href="mailto:me@x.com">邮件</a>
<a href="javascript:void(0)">js</a>
<a href="#frag">锚点</a>
<a href="/img/p.png">图</a>
<a href="/a/1">重复</a>
"""

u = L.extract_links(HTML, 'https://site.com/docs/page.html')
check('https://site.com/a/1' in u, '绝对路径补全')
check('https://site.com/docs/b/2' in u, '相对路径按 base 解析')
check(not any('other.com' in x for x in u), '默认只留同 host')
check(not any(x.startswith('mailto:') for x in u), '跳过 mailto')
check(not any(x.startswith('javascript:') for x in u), '跳过 javascript')
check(not any('#' in x for x in u), '去掉锚点')
check(not any(x.endswith('.png') for x in u), '跳过图片')
check(len(u) == len(set(u)), '去重')

ROBOTS = """
User-agent: BadBot
Disallow: /

User-agent: *
Disallow: /private/
Disallow: /tmp/*.pdf
Allow: /private/ok
"""

rules = L.parse_robots(ROBOTS)
check(L.robots_allows(rules, 'https://s.com/public/x') is True, '没被禁的放行')
check(L.robots_allows(rules, 'https://s.com/private/x') is False, 'Disallow 目录被拦')
check(L.robots_allows(rules, 'https://s.com/private/ok/1') is True, 'Allow 覆盖更长前缀')
check(L.robots_allows(rules, 'https://s.com/tmp/a.pdf') is False, '通配 Disallow 命中')
check(L.robots_allows(rules, 'https://s.com/tmp/a.html') is True, '通配不误伤')
check(L.robots_allows(L.parse_robots(''), 'https://s.com/x') is True, '空 robots 全放行')

check(L.host_of('https://A.com/x') == 'a.com', 'host 小写化')

print()
if _fails:
    print('FAILED: %d 项' % len(_fails))
    sys.exit(1)
print('ALL PASS')
