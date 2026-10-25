"""所有 help 必须是纯文本: 不带 ANSI 颜色, 不带 rich 面板边框/标记"""
import os
import re
import subprocess
import sys

BAD = re.compile(r'\x1b\[|[\u2500-\u257f]|\[/?(?:bold|cyan|green|yellow|red|dim|italic)\]')

CASES = [
    [], ['search'], ['site'], ['fetch'], ['crawl'], ['rank'],
    ['feed'], ['feed', 'get'], ['feed', 'sources'],
    ['proxy'], ['pkg'], ['mcp'], ['plugins'], ['config'], ['render'],
    ['upgrade'], ['uninstall'], ['intercept-log'],
]
LLM_CASES = [['ask'], ['zen'], ['zen', 'chat']]


def run(args, llm=False):
    env = dict(os.environ)
    if llm:
        env['WEBTOOL_LLM'] = 'on'
    p = subprocess.run([sys.executable, '-m', 'webtool', *args],
                       capture_output=True, text=True, timeout=60, env=env)
    return p.returncode, (p.stdout or '') + (p.stderr or '')


def check(name, text):
    m = BAD.search(text)
    assert not m, f'{name}: 发现 rich/ANSI 痕迹 {m.group(0)!r}'
    assert text.strip(), f'{name}: 没有输出'
    print('PASS', name)


def main():
    for args in CASES:
        name = ' '.join(args) or '(顶层)'
        rc, out = run(args + ['-h'])
        assert rc == 0, f'{name}: -h 退出码 {rc}'
        check(name + ' -h', out)
    # 默认关闭: 顶层帮助不提 ask/zen, 命令入口直接拒绝
    rc, out = run([])
    assert rc == 0 and 'ask' not in out and 'zen' not in out, \
        '默认帮助不应出现 ask/zen'
    print('PASS 默认顶层帮助不含大模型命令')
    for c in ('ask', 'zen'):
        rc, out = run([c])
        assert rc == 2 and '大模型功能已关闭' in out, f'{c}: 默认应拒绝 (rc={rc})'
        check(c + ' 默认关闭', out)
    # 打开后帮助与子命令仍可用, 且保持纯文本
    for args in LLM_CASES:
        name = ' '.join(args)
        rc, out = run(args + ['-h'], llm=True)
        assert rc == 0, f'{name}: 开启后 -h 退出码 {rc}'
        check(name + ' -h (开启)', out)
    rc, out = run([], llm=True)
    assert 'ask' in out and 'zen' in out, '开启后帮助应列出 ask/zen'
    print('PASS 开启后顶层帮助')
    for args in ([], ['search']):
        name = ' '.join(args) or '(顶层)'
        rc, out = run(args)
        assert rc == 0, f'{name}: 无参数退出码 {rc}'
        check(name + ' 无参数', out)
    print('\nALL PASS')


if __name__ == '__main__':
    main()
