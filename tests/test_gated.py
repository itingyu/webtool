"""登录态源 (小红书/BOSS) 的离线测试

不联网: cookie 解析、必填校验、两个站点的 JSON 解析都用固定样本。
真实验证靠 `webtool auth test <site>` —— 那条路要用户自己的 cookie。
"""
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from webtool.core import authcookie
from webtool.engines import gated

FAILED = []


def check(cond, msg):
    if cond:
        print(f'PASS {msg}')
    else:
        print(f'FAIL {msg}')
        FAILED.append(msg)


# ---- cookie 解析: 三种来源 ----
ck = authcookie.parse('a1=xx; web_session=yy')
check(len(ck) == 2, '头串解析出 2 个 cookie')
check({c['name'] for c in ck} == {'a1', 'web_session'}, '头串拿到正确名字')

ck = authcookie.parse('[{"name":"a1","value":"xx","domain":".xiaohongshu.com"}]')
check(len(ck) == 1 and ck[0]['domain'] == '.xiaohongshu.com', 'JSON 列表解析')

ck = authcookie.parse('{"a1":"xx"}')
check(len(ck) == 1 and ck[0]['name'] == 'a1', 'JSON 字典解析')

net = ('# Netscape HTTP Cookie File\n'
       '.xiaohongshu.com\tTRUE\t/\tTRUE\t0\ta1\txx\n')
ck = authcookie.parse(net)
check(len(ck) == 1 and ck[0]['name'] == 'a1', 'Netscape 格式解析')
check(ck[0].get('domain') == '.xiaohongshu.com', 'Netscape 保留域')

ck = authcookie.parse('a1=xx', default_domain='.xiaohongshu.com')
check(ck[0].get('domain') == '.xiaohongshu.com', '缺域时用默认域')

check(authcookie.parse('随便一段没有等号的文字') == [], '垃圾输入返回空')
check(authcookie.to_header([{'name': 'a1', 'value': 'xx'}]) == 'a1=xx',
      'to_header 拼头串')
check(authcookie.missing([{'name': 'a1', 'value': 'x'}], ['a1', 'web_session'])
      == ['web_session'], 'missing 列出缺的')

# ---- 必填校验: 没 cookie 要给能照做的报错 ----
_orig_load = gated.state.load_cookies
gated.state.load_cookies = lambda engine: []
try:
    gated.require('xhs')
    check(False, '缺 cookie 时应抛错')
except gated.SiteAuthError as e:
    check('webtool auth set xhs' in str(e), '报错里带操作指引')

gated.state.load_cookies = lambda engine: [{'name': 'a1', 'value': 'x'}]
try:
    gated.require('xhs')
    check(False, '缺关键项时应抛错')
except gated.SiteAuthError as e:
    check('web_session' in str(e), '报错里点名缺哪个')
gated.state.load_cookies = _orig_load

# ---- BOSS JSON 解析 ----
boss_json = {'code': 0, 'zpData': {'jobList': [
    {'jobName': 'Python 后端', 'encryptJobId': 'abc123',
     'salaryDesc': '20-40K', 'cityName': '上海', 'areaDistrict': '浦东新区',
     'jobExperience': '3-5年', 'jobDegree': '本科',
     'companyName': '某某科技', 'skills': ['Python', 'Django']},
    {'jobName': '缺 id 的脏数据', 'companyName': 'x'},
]}}
rows = gated._parse_boss(boss_json, 10)
check(len(rows) == 1, 'BOSS 脏数据被跳过')
r = rows[0]
check(r['url'].endswith('/job_detail/abc123.html'), 'BOSS 链接正确')
check('Python 后端' in r['title'] and '某某科技' in r['title'], 'BOSS 标题带职位与公司')
check('20-40K' in r['snippet'] and '浦东新区' in r['snippet'], 'BOSS 摘要带薪资与地点')
check(gated._parse_boss(boss_json, 1) == rows[:1], 'BOSS limit 生效')
check(gated._parse_boss({'code': 0, 'zpData': {}}, 5) == [], 'BOSS 空列表不炸')

# ---- 小红书 JSON 解析 ----
xhs_json = {'code': 0, 'data': {'items': [
    {'id': 'n1', 'note_card': {'display_title': '露营好物', 'desc': '户外装备',
                               'user': {'nickname': '小明'},
                               'interact_info': {'liked_count': '1.2万'},
                               'type': 'normal'}},
    {'id': '', 'note_card': {'display_title': '没 id'}},
]}}
rows = gated._parse_xhs(xhs_json, 10)
check(len(rows) == 1, '小红书脏数据被跳过')
r = rows[0]
check(r['url'].endswith('/explore/n1'), '小红书链接正确')
check(r['title'] == '露营好物', '小红书标题正确')
check(r.get('author') == '小明', '小红书带作者')
check(gated._parse_xhs({'code': 0, 'data': {}}, 5) == [], '小红书空列表不炸')

# ---- 站点元数据一致 ----
for site, sp in gated.AUTH_SITES.items():
    check(bool(sp.get('label') and sp.get('domain') and sp.get('hint')),
          f'{site} 元数据齐全')
    check(site in gated.AUTH_FN, f'{site} 在函数表里')

if FAILED:
    print(f'\nFAILED: {len(FAILED)} 项')
    sys.exit(1)
print('\nALL PASS')
